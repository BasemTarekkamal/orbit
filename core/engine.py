#!/usr/bin/env python3
"""The engine: the one way any employee "thinks". Harness-owned: employees can't edit it.

    import engine
    emp = engine.employee("sara")
    res = engine.run(emp, prompt, job="chat", session_key="12345")   # -> {"ok", "text", ...}

Every run is the unmodified `claude` CLI, signed in with the owner's own Claude account (or their own
API key), headless in the employee's folder, and gets whatever the employee's profile says:
  * the OS sandbox: shell commands reach only approved hosts and can't read secrets or colleagues'
    folders. The toolbelt gateways (staff-fetch, staff-browse, staff-apify, staff-watch) run outside
    it because they enforce their own limits (public web only, GET only, budget);
  * the staff guard (a Claude Code mod): blocks outside contact, payment sites, secrets, editing the
    harness; masks card numbers and IBANs; records plan usage;
  * abilities: tools, gateway commands and skills switched on or off per employee;
  * model routing: the employee's model, or the fallback when plan usage is high;
  * a cost/reliability log in <workspace>/state/runs.jsonl.
Python 3.9 compatible (the Mac's system python). The same on Windows (inside WSL2) and Linux, where the
sandbox is bubblewrap instead of macOS Seatbelt; osinfo.py holds the few differences.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import osinfo

CORE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(CORE)
BIN = os.path.join(KIT, "bin")
SKILLS = os.path.join(CORE, "skills")
GUARD = os.path.join(CORE, "guard", "staff-guard")
H = os.path.expanduser("~")
HOME = os.path.expanduser(os.environ.get("STAFFROOM_HOME", "~/Staff"))
REGISTRY = os.path.join(HOME, "staff.json")
SECRETS = os.path.join(HOME, ".secrets")

BASE_DOMAINS = ["pypi.org", "files.pythonhosted.org"]
SECRET_PATHS = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gh", "~/.config/rclone", "~/.netrc",
                "~/.claude/.credentials.json", "~/.claude/channels", "~/Library/Keychains",
                "~/Library/Application Support/Google/Chrome", "~/Library/Safari", "~/Library/Messages",
                "~/Library/Mail", "~/Desktop", "~/Documents", "~/Downloads", "~/.local/share/keyrings",
                "~/.mozilla", "~/.config/google-chrome", "~/.config/chromium", SECRETS]
if osinfo.KIND == "wsl":
    SECRET_PATHS.append("/mnt")                        # the Windows drives: their files stay out of reach
BASE_ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "TodoWrite", "Skill"]
BASE_DENIED = ["Bash(git push *)", "Bash(git push)", "Bash(git remote *)", "Bash(sudo *)",
               "Bash(ssh *)", "Bash(scp *)", "Bash(security *)", "Bash(osascript *)",
               "Bash(launchctl *)", "Bash(gh *)", "Bash(systemctl *)", "Bash(powershell.exe *)", "Bash(cmd.exe *)",
               "Bash(wsl.exe *)", "Bash(schtasks.exe *)", "Edit(profile.json)", "Write(profile.json)"]


# ------------------------------------------------------------------ registry
def registry() -> dict:
    try:
        with open(REGISTRY, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        return {"owners": {}, "employees": {}}


def save_registry(reg: dict, why: str = "") -> None:
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, REGISTRY)
    if why:
        subprocess.run(["git", "add", "staff.json"], cwd=HOME, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Staffroom", "-c", "user.email=staffroom@localhost",
                        "commit", "-qm", why], cwd=HOME, capture_output=True)


def employee(emp_id: str) -> dict:
    reg = registry()
    e = dict(reg["employees"][emp_id])
    ws = os.path.expanduser(e.get("workspace") or os.path.join(HOME, "employees", emp_id))
    try:
        with open(os.path.join(ws, "profile.json"), encoding="utf-8") as fh:
            prof = json.load(fh)
    except (OSError, ValueError):
        prof = {}
    e = {**reg.get("defaults", {}), **prof, **e}
    e["id"], e["workspace"] = emp_id, ws
    return e


def owners() -> dict:
    return registry().get("owners", {})


def owner_key(address):
    """The registry key of the owner who holds this address: their key itself ("telegram:123", or a bare
    Telegram id from older registries), or one of owners.<key>.addresses. None for strangers."""
    import channels
    s = str(address or "").strip()
    if not s:
        return None
    n = channels.norm(s)
    for key, o in owners().items():
        if s == key or n in {channels.norm(key)} | {channels.norm(a) for a in o.get("addresses", [])}:
            return key
    return None


def owner_id(name_or_id: str):
    """An owner's key from their key, any of their addresses, their name or an alias, any case."""
    key = str(name_or_id).strip().lower()
    for oid, o in owners().items():
        if key in [oid.lower(), o["name"].lower()] + [a.lower() for a in o.get("aliases", [])]:
            return oid
    return owner_key(name_or_id)


def owner_name(name_or_id: str):
    oid = owner_id(name_or_id)
    return owners()[oid]["name"] if oid else None


# ------------------------------------------------------------------ model routing
def usage() -> dict:
    """Newest plan-usage reading any employee's guard recorded (usage is per account, not per employee)."""
    best = None
    for f in glob.glob(os.path.join(HOME, "employees", "*", "state", "claude_usage.json")):
        try:
            with open(f) as fh:
                d = json.load(fh)
            if not best or d.get("at", "") > best.get("at", ""):
                best = d
        except (OSError, ValueError):
            pass
    out = {}
    for r in (best or {}).get("rateLimits", []):
        out[r.get("kind")] = float(r.get("percentUsed") or 0)
    return out


def pick_model(emp: dict) -> str:
    u = usage()
    if u.get("five_hour", 0) >= 80 or u.get("seven_day", 0) >= 90:
        return emp.get("fallback_model", "haiku")
    return emp.get("model", "sonnet")


# ------------------------------------------------------------------ launch
def resolve_claude() -> str:
    c = shutil.which("claude")
    if c:
        return c
    for pat in (H + "/.local/bin/claude", H + "/.claude/local/claude", "/opt/homebrew/bin/claude",
                "/usr/local/bin/claude", H + "/.nvm/versions/node/*/bin/claude"):
        found = sorted(glob.glob(pat))
        if found:
            return found[-1]
    return "claude"


def secret(name: str):
    try:
        with open(os.path.join(SECRETS, name), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def save_secret(name: str, value: str) -> None:
    """~/Staff/.secrets/<name>, readable by the owner only (employees can't: sandbox deny list + guard)."""
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("bad secret name")
    os.makedirs(SECRETS, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    p = os.path.join(SECRETS, name)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value.strip())
    os.chmod(p, 0o600)


def drop_secret(name: str) -> None:
    try:
        os.remove(os.path.join(SECRETS, name))
    except OSError:
        pass


def clean_env(emp: dict) -> dict:
    """The CLI signs in with its own login (keychain). Nothing of the caller's Claude settings leaks in."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK")) and k != "CLAUDECODE"}
    env["HOME"] = H
    env["PATH"] = ":".join([BIN, os.path.dirname(resolve_claude())] + osinfo.path_dirs())
    env["CLAUDE_CODE_FORK_SUBAGENT"] = "0"              # no hidden conversation-copying subagents
    env["STAFF_EMPLOYEE"] = emp["id"]
    env["STAFF_WORKSPACE"] = emp["workspace"]
    env["STAFFROOM_HOME"] = HOME
    env["STAFFROOM_KIT"] = KIT
    import abilities
    env["STAFF_ABILITIES"] = ",".join(sorted(abilities.effective(emp["id"])))   # read by the guard
    env["STAFF_BROWSER_SITES"] = ",".join((registry().get("employees", {}).get(emp["id"], {}).get("browser") or {}).get("sites", []))
    if os.path.exists("/etc/ssl/cert.pem"):               # TLS for curl/Go tools inside the sandbox
        env.setdefault("SSL_CERT_FILE", "/etc/ssl/cert.pem")
        env.setdefault("CURL_CA_BUNDLE", "/etc/ssl/cert.pem")
    if registry().get("auth") == "api_key" and secret("anthropic_api_key"):
        env["ANTHROPIC_API_KEY"] = secret("anthropic_api_key")   # the owner's own key, billed to them
    return env


def settings_json(emp: dict, unsandboxed: list) -> str:
    others = [p for p in glob.glob(os.path.join(HOME, "employees", "*"))
              if os.path.realpath(p) != os.path.realpath(emp["workspace"])]
    domains = BASE_DOMAINS + registry().get("network_domains", []) + emp.get("network_domains", [])
    return json.dumps({
        "enabledPlugins": {},
        "sandbox": {
            "enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
            "network": {"allowedDomains": sorted(set(domains)), "strictAllowlist": True},
            "filesystem": {"denyRead": SECRET_PATHS + others,
                           "allowWrite": [os.path.join(HOME, "team")]},   # the team bus
            "excludedCommands": ["%s *" % c for c in unsandboxed],
        },
    })


def skills_plugin(emp: dict, wanted: list) -> str:
    """The employee's skills bundle (~/Staff/.runtime/<id>/skills): links to the kit's playbooks for its
    abilities, its own learned skills (<workspace>/skills) and the team's shared ones (team/skills).
    Rebuilt before every run, so a new skill loads on the next run. The bundle lives outside the
    employee's folder, so it can't edit the kit's playbooks; its own skills it edits in place."""
    import skillbook
    root = os.path.join(HOME, ".runtime", emp["id"], "skills")
    sk = os.path.join(root, "skills")
    os.makedirs(os.path.join(root, ".claude-plugin"), exist_ok=True)
    os.makedirs(sk, exist_ok=True)
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    if not os.path.exists(manifest):
        with open(manifest, "w") as fh:
            json.dump({"name": "staffroom-skills", "version": "1.0.0",
                       "description": "The kit's playbooks, this employee's own skills and the team's shared ones"}, fh)
    links, _ = skillbook.bundle(emp["workspace"], wanted)
    for name in os.listdir(sk):
        p = os.path.join(sk, name)
        if name not in links or os.path.realpath(p) != os.path.realpath(links[name]):
            os.unlink(p)
    for name, src in links.items():
        p = os.path.join(sk, name)
        if not os.path.lexists(p):
            os.symlink(src, p)
    return root


def command(emp: dict, model: str) -> list:
    import abilities                                       # the owners' ticks decide the tools
    allow, block = abilities.tools(emp["id"])
    gateways = abilities.commands(emp["id"])
    bundle = skills_plugin(emp, abilities.skills(emp["id"]))
    cmd = [resolve_claude(), "-p", "--model", model, "--effort", emp.get("effort", "medium"),
           "--permission-mode", "dontAsk", "--output-format", "stream-json", "--verbose",
           "--setting-sources", "project", "--strict-mcp-config",
           "--settings", settings_json(emp, gateways), "--plugin-dir", GUARD, "--plugin-dir", bundle,
           "--append-system-prompt", "Paths: your team folder (~/Staff in the handbook) is %s; the kit (the handbook, "
           "skills and tools) is %s. %s" % (HOME, KIT, abilities.prompt(emp["id"])),
           "--allowedTools", *([t for t in BASE_ALLOWED if t not in block] + allow + emp.get("extra_tools", [])),
           "--disallowedTools", *(BASE_DENIED + block + emp.get("extra_denied", []))]
    for extra in emp.get("add_dirs", []):
        cmd += ["--add-dir", os.path.expanduser(extra)]
    if "act_in_browser" in abilities.effective(emp["id"]):   # the owner's own Chrome, through Claude in Chrome
        cmd.append("--chrome")
    return cmd


def friendly_error(err: str) -> str:
    if re.search(r"usage limit|rate limit|limit reached", err, re.I):
        return "I've hit the Claude usage limit; I'll pick this up after it resets. Nothing is lost."
    if re.search(r"authenticate|OAuth|not logged in|log in", err, re.I):
        return osinfo.local("My Claude sign-in on this Mac has expired. Owner: run `claude auth login` in Terminal.")
    if re.search(r"ENOTFOUND|ECONNRESET|network|reach the API", err, re.I):
        return "I couldn't reach Claude (internet down?). Please resend in a few minutes."
    return "Something went wrong on my side (logged). Please resend."


def stream(cmd: list, prompt: str, ws: str, env: dict, timeout: int, on_step=None):
    """Runs one claude turn, reading its stream-json events as they come: each tool call becomes a plain
    step ("Reading tiktok.com") passed to on_step(step, steps). Returns (final result event, steps)."""
    import steps as steps_mod
    t0, steps, result, killed = time.time(), [], None, []
    errf = tempfile.TemporaryFile()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf, text=True, cwd=ws, env=env)

    def kill():
        killed.append(1)
        p.kill()
    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        text = steps_mod.describe(b.get("name"), b.get("input"), ws)
                        if text and (not steps or steps[-1]["text"] != text):
                            s = {"t": round(time.time() - t0), "text": text}
                            steps.append(s)
                            if on_step:
                                try:
                                    on_step(s, steps)
                                except Exception:  # noqa: BLE001  (a display callback must never stop the work)
                                    pass
            elif ev.get("type") == "result":
                result = ev
        p.wait()
        if killed:
            return {"is_error": True, "result": "timed out after %d min" % max(1, timeout // 60)}, steps
        if not result:
            errf.seek(0)
            err = errf.read().decode("utf-8", "replace")
            result = {"is_error": True, "result": (err or "no output")[-400:]}
        return result, steps
    finally:
        timer.cancel()
        p.stdout.close()
        errf.close()


def run(emp: dict, prompt: str, job: str = "chat", session_key: str = None,
        timeout: int = 1800, extra_env: dict = None, on_step=None) -> dict:
    """Run the employee headless in its folder. Chats resume one session per (employee, person).
    on_step(step, steps) is called live for every tool call; the steps also come back in the result."""
    if os.environ.get("STAFFROOM_DEMO"):                  # `orbit demo`: canned answers, no Claude run
        import demo
        return demo.fake_run(emp, prompt, job, session_key, on_step)
    if not os.path.isfile(os.path.join(GUARD, "hooks", "register.js")):
        return {"ok": False, "text": "My safety guard is missing, so I've stopped myself. Owner: reinstall the kit.",
                "error": "guard missing", "model": None}
    ws = emp["workspace"]
    sessions_f = os.path.join(ws, "state", "sessions.json")
    try:
        with open(sessions_f) as fh:
            sessions = json.load(fh)
    except (OSError, ValueError):
        sessions = {}
    model = pick_model(emp)
    base = command(emp, model)
    attempts = []
    if session_key and sessions.get(session_key):
        attempts.append(("resume", sessions[session_key]))
    attempts.append(("new", str(uuid.uuid4())))
    t0, d, steps = time.time(), {}, []
    for kind, sid in attempts:
        cmd = base + (["--resume", sid] if kind == "resume" else ["--session-id", sid])
        d, steps = stream(cmd, prompt, ws, {**clean_env(emp), **(extra_env or {})}, timeout, on_step)
        if not d.get("is_error"):
            if session_key:
                sessions[session_key] = sid
                os.makedirs(os.path.dirname(sessions_f), exist_ok=True)
                with open(sessions_f, "w") as fh:
                    json.dump(sessions, fh, indent=1)
            break
        if re.search(r"limit|network|ENOTFOUND|ECONNRESET|authenticate", str(d.get("result", "")), re.I):
            break                                          # a fresh session won't help
    err = str(d.get("result", "")) if d.get("is_error") else ""
    text = friendly_error(err) if d.get("is_error") else (d.get("result") or "").strip()
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "employee": emp["id"], "job": job,
           "ok": not d.get("is_error"), "secs": round(time.time() - t0), "model": model,
           "turns": d.get("num_turns"), "cost_usd": d.get("total_cost_usd"), "tokens": run_tokens(d),
           "error": err[:200] or None, "steps": steps[-40:]}
    os.makedirs(os.path.join(ws, "state"), exist_ok=True)
    with open(os.path.join(ws, "state", "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": not d.get("is_error"), "text": text, "error": err, "model": model, "steps": steps[-40:],
            "secs": rec["secs"], "cost_usd": rec["cost_usd"], "tokens": rec["tokens"]}


def run_tokens(d: dict) -> int:
    """Tokens a run used on the owner's plan: what it read, wrote and newly cached (cache re-reads are cheap
    and left out). Plan use is shown in tokens, never dollars: nothing is billed on a subscription."""
    u = d.get("usage") or {}
    return int(sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")))


def tokens_of(r: dict) -> int:
    """A logged run's tokens. Runs logged before tokens were recorded: estimated from their API-equivalent cost
    (about 200,000 tokens per dollar on Sonnet)."""
    if r.get("tokens") is not None:
        return int(r["tokens"])
    return int(float(r.get("cost_usd") or 0) * 200000)


def stats(emp: dict) -> dict:
    """Runs and plan use today and over 7 days: tokens (what the owner's plan meters), plus the API-equivalent
    dollars kept for the record (nothing is billed on a subscription)."""
    today, week = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
    out = {"runs_today": 0, "failures_today": 0, "use_today": 0.0, "use_7d": 0.0, "tokens_today": 0, "tokens_7d": 0,
           "failures_7d": 0, "runs_7d": 0, "last_run": None}
    try:
        with open(os.path.join(emp["workspace"], "state", "runs.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                day = r.get("ts", "")[:10]
                if day >= week:
                    out["use_7d"] += float(r.get("cost_usd") or 0)
                    out["tokens_7d"] += tokens_of(r)
                    out["runs_7d"] += 1
                    out["failures_7d"] += 0 if r.get("ok") else 1
                if day == today:
                    out["runs_today"] += 1
                    out["failures_today"] += 0 if r.get("ok") else 1
                    out["use_today"] += float(r.get("cost_usd") or 0)
                    out["tokens_today"] += tokens_of(r)
                out["last_run"] = r.get("ts")
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ a Claude session in the employee's folder
SESSION_HELLO = ("Hi %s. Introduce yourself to me in a few short lines: your job as you understand it, what you'll "
                 "do first, and anything you need from me. Read your CLAUDE.md and notes first.")


def claude_session(emp_id: str) -> dict:
    """Readies the employee's folder so a Claude app session opened there is that employee, with the same locks
    as its runs: the sandbox, the deny list and the guard (installed for this folder only), its abilities and
    its tools. Written to .claude/settings.local.json, which the harness's own runs don't read (they use
    --setting-sources project), so runs and sessions never double up. → {"folder", "link", "hello"}"""
    import abilities
    emp = employee(emp_id)
    ws = emp["workspace"]
    allow, block = abilities.tools(emp["id"])
    sandbox = json.loads(settings_json(emp, abilities.commands(emp["id"])))["sandbox"]
    env = clean_env(emp)
    deny = []
    for rule in BASE_DENIED + block + emp.get("extra_denied", []):
        rule = re.sub(r"^Write\(", "Edit(", rule)          # Edit rules cover every file-editing tool
        if rule not in deny:
            deny.append(rule)
    path = os.path.join(ws, ".claude", "settings.local.json")
    try:
        with open(path, encoding="utf-8") as fh:
            local = json.load(fh)
    except (OSError, ValueError):
        local = {}
    local.update({
        "sandbox": sandbox,
        "permissions": {"allow": [t for t in BASE_ALLOWED if t not in block] + allow + emp.get("extra_tools", []),
                        "deny": deny},
        "env": {k: env[k] for k in ("STAFF_EMPLOYEE", "STAFF_WORKSPACE", "STAFFROOM_HOME", "STAFFROOM_KIT",
                                     "STAFF_ABILITIES", "STAFF_BROWSER_SITES", "PATH")},
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(local, fh, indent=2)
    with open(os.path.join(GUARD, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        version = json.load(fh).get("version", "")
    stamp = os.path.join(ws, ".claude", "orbit-guard.version")
    try:
        with open(stamp) as fh:
            have = fh.read().strip()
    except OSError:
        have = ""
    installed = (local.get("enabledPlugins") or {}).get("staff-guard@orbit")
    if not installed or have != version:                   # the guard is copied in at install: refresh it when the kit's changes
        env_cli = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_")) and k != "CLAUDECODE"}
        steps = ([["plugin", "marketplace", "add", os.path.join(KIT, "core"), "--scope", "local"],
                  ["plugin", "install", "staff-guard@orbit", "--scope", "local"]] if not installed else
                 [["plugin", "marketplace", "update", "orbit"], ["plugin", "update", "staff-guard@orbit", "--scope", "local"]])
        for args in steps:
            try:
                r = subprocess.run([resolve_claude()] + args, cwd=ws, capture_output=True, text=True, timeout=120, env=env_cli)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise RuntimeError("couldn't run Claude Code to add the guard (%s). Is it installed? `orbit doctor`" % e)
            if r.returncode != 0 and not re.search(r"already|up to date|latest", r.stdout + r.stderr, re.I):
                raise RuntimeError("couldn't add the guard to %s's folder: %s" % (emp["name"], (r.stderr or r.stdout).strip()[-200:]))
        with open(stamp, "w") as fh:
            fh.write(version)
    import urllib.parse
    hello = SESSION_HELLO % emp["name"]
    link = "claude://code/new?" + urllib.parse.urlencode({"folder": ws, "q": hello}, quote_via=urllib.parse.quote)
    return {"folder": ws, "link": link, "hello": hello}
