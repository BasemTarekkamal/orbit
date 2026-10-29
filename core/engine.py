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
Python 3.9 compatible (the Mac's system python).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import time
import uuid

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
                "~/Library/Mail", "~/Desktop", "~/Documents", "~/Downloads", SECRETS]
BASE_ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "TodoWrite", "Skill"]
BASE_DENIED = ["Bash(git push *)", "Bash(git push)", "Bash(git remote *)", "Bash(sudo *)",
               "Bash(ssh *)", "Bash(scp *)", "Bash(security *)", "Bash(osascript *)",
               "Bash(launchctl *)", "Bash(gh *)", "Edit(profile.json)", "Write(profile.json)"]


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


def owner_id(name_or_id: str):
    """An owner's Telegram id from their id, name or alias, any case."""
    key = str(name_or_id).strip().lower()
    for oid, o in owners().items():
        if key in [oid, o["name"].lower()] + [a.lower() for a in o.get("aliases", [])]:
            return oid
    return None


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


def clean_env(emp: dict) -> dict:
    """The CLI signs in with its own login (keychain). Nothing of the caller's Claude settings leaks in."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK")) and k != "CLAUDECODE"}
    env["HOME"] = H
    env["PATH"] = ":".join([BIN, os.path.dirname(resolve_claude()), "/opt/homebrew/bin", "/usr/local/bin",
                            "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["CLAUDE_CODE_FORK_SUBAGENT"] = "0"              # no hidden conversation-copying subagents
    env["STAFF_EMPLOYEE"] = emp["id"]
    env["STAFF_WORKSPACE"] = emp["workspace"]
    env["STAFFROOM_HOME"] = HOME
    env["STAFFROOM_KIT"] = KIT
    import abilities
    env["STAFF_ABILITIES"] = ",".join(sorted(abilities.effective(emp["id"])))   # read by the guard
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
    """A read-only skills bundle for this employee (~/Staff/.runtime/<id>/skills): links to the kit's
    skills for its abilities. It lives outside the employee's folder, so the employee can't edit the
    kit's skills; skills it writes itself go in its own .claude/skills and load as usual."""
    root = os.path.join(HOME, ".runtime", emp["id"], "skills")
    sk = os.path.join(root, "skills")
    os.makedirs(os.path.join(root, ".claude-plugin"), exist_ok=True)
    os.makedirs(sk, exist_ok=True)
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    if not os.path.exists(manifest):
        with open(manifest, "w") as fh:
            json.dump({"name": "staffroom-skills", "version": "1.0.0",
                       "description": "The kit's research and work playbooks, per ability"}, fh)
    for name in os.listdir(sk):
        if name not in wanted:
            os.unlink(os.path.join(sk, name))
    for name in wanted:
        src, p = os.path.join(SKILLS, name), os.path.join(sk, name)
        if os.path.isdir(src) and not os.path.lexists(p):
            os.symlink(src, p)
    return root


def command(emp: dict, model: str) -> list:
    import abilities                                       # the owners' ticks decide the tools
    allow, block = abilities.tools(emp["id"])
    gateways = abilities.commands(emp["id"])
    bundle = skills_plugin(emp, abilities.skills(emp["id"]))
    cmd = [resolve_claude(), "-p", "--model", model, "--effort", emp.get("effort", "medium"),
           "--permission-mode", "dontAsk", "--output-format", "json",
           "--setting-sources", "project", "--strict-mcp-config",
           "--settings", settings_json(emp, gateways), "--plugin-dir", GUARD, "--plugin-dir", bundle,
           "--append-system-prompt", "Paths: your team folder (~/Staff in the handbook) is %s; the kit (the handbook, "
           "skills and tools) is %s. %s" % (HOME, KIT, abilities.prompt(emp["id"])),
           "--allowedTools", *([t for t in BASE_ALLOWED if t not in block] + allow + emp.get("extra_tools", [])),
           "--disallowedTools", *(BASE_DENIED + block + emp.get("extra_denied", []))]
    for extra in emp.get("add_dirs", []):
        cmd += ["--add-dir", os.path.expanduser(extra)]
    return cmd


def friendly_error(err: str) -> str:
    if re.search(r"usage limit|rate limit|limit reached", err, re.I):
        return "I've hit the Claude usage limit; I'll pick this up after it resets. Nothing is lost."
    if re.search(r"authenticate|OAuth|not logged in|log in", err, re.I):
        return "My Claude sign-in on this Mac has expired. Owner: run `claude auth login` in Terminal."
    if re.search(r"ENOTFOUND|ECONNRESET|network|reach the API", err, re.I):
        return "I couldn't reach Claude (internet down?). Please resend in a few minutes."
    return "Something went wrong on my side (logged). Please resend."


def run(emp: dict, prompt: str, job: str = "chat", session_key: str = None,
        timeout: int = 1800, extra_env: dict = None) -> dict:
    """Run the employee headless in its folder. Chats resume one session per (employee, person)."""
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
    t0, d = time.time(), {}
    for kind, sid in attempts:
        cmd = base + (["--resume", sid] if kind == "resume" else ["--session-id", sid])
        try:
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=ws,
                               env={**clean_env(emp), **(extra_env or {})}, timeout=timeout)
            try:
                d = json.loads(p.stdout or "{}")
            except ValueError:
                d = {}
            if not d:
                d = {"is_error": True, "result": (p.stderr or p.stdout or "no output")[-400:]}
        except subprocess.TimeoutExpired:
            d = {"is_error": True, "result": "timed out after %d min" % (timeout // 60)}
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
           "turns": d.get("num_turns"), "cost_usd": d.get("total_cost_usd"),
           "error": err[:200] or None}
    os.makedirs(os.path.join(ws, "state"), exist_ok=True)
    with open(os.path.join(ws, "state", "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return {"ok": not d.get("is_error"), "text": text, "error": err, "model": model}


def stats(emp: dict) -> dict:
    """Runs and plan use (API-equivalent dollars; nothing is billed on a subscription) today and 7 days."""
    today, week = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
    out = {"runs_today": 0, "failures_today": 0, "use_today": 0.0, "use_7d": 0.0, "last_run": None}
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
                if day == today:
                    out["runs_today"] += 1
                    out["failures_today"] += 0 if r.get("ok") else 1
                    out["use_today"] += float(r.get("cost_usd") or 0)
                out["last_run"] = r.get("ts")
    except OSError:
        pass
    return out
