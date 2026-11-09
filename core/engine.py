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
import socket
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


BRAIN_JOBS = ("chat", "standup", "initiative", "eod", "review", "catchup", "first_day", "minutes", "learn")


def pick_model(emp: dict, job: str = "chat") -> str:
    """Two models per crew member. The **brain** thinks and talks with the owner (standup, initiative, end of day,
    the weekly review, catching up, chats): Opus by default, the same brain the owner gets in their own Claude.
    The **hands** do the production runs and the scans (follow-ups, the morning brief, scout, self-test, colleague
    questions): Sonnet by default. When the owner's plan is nearly used up, both fall back to the light model."""
    u = usage()
    if u.get("five_hour", 0) >= 80 or u.get("seven_day", 0) >= 90:
        return emp.get("fallback_model", "haiku")
    if job in BRAIN_JOBS:
        return emp.get("brain") or "opus"
    return emp.get("model", "sonnet")


# ------------------------------------------------------------------ one running conversation
SESSION = "main"              # a crew member is one conversation: routines, follow-ups and every owner's chats land in it
HEAVY, FULL = 60_000, 150_000  # context tokens: heavy → start fresh on a new day; full → start fresh now
ORIENT = ("[New conversation. Your memory is in your files: read CLAUDE.md, the handbook, ~/Staff/team/ABOUT.md, PLAN.md, "
          "STATE.md, TASKS.md and LESSONS.md before you act, then carry on as if you never left.]\n\n")


def transcripts(ws: str) -> str:
    """Where Claude Code keeps this folder's session transcripts."""
    return os.path.join(os.path.expanduser("~/.claude/projects"), re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(ws)))


def context_tokens(ws: str, sid: str) -> int:
    """How much the conversation carries now: the context size of its last turn, read from Claude Code's own
    transcript of the session (no model call). 0 when there is no transcript yet."""
    path = os.path.join(transcripts(ws), sid + ".jsonl")
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return 0
    ctx = 0
    for line in tail.splitlines():
        if '"usage"' not in line:
            continue
        try:
            u = ((json.loads(line).get("message") or {}).get("usage")) or {}
        except (ValueError, AttributeError):
            continue
        if u:
            ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return ctx


def fresh_start(sessions: dict, ws: str, today: str = None) -> bool:
    """A conversation runs on while it's light, so the crew member remembers the day and the week like a chat window
    does. Once it has grown heavy it starts fresh on the next day (the files carry the memory across), and near
    Claude's context limit it starts fresh at once: no run pays to re-read a week of history."""
    sid = sessions.get(SESSION)
    if not sid:
        return False
    ctx = context_tokens(ws, sid)
    today = today or time.strftime("%F")
    return ctx >= FULL or (ctx >= HEAVY and sessions.get(SESSION + "_day") != today)


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


def autonomous(emp: dict) -> bool:
    import abilities
    return "full_autonomy" in abilities.effective(emp["id"])


def settings_json(emp: dict, unsandboxed: list) -> str:
    """The run's sandbox: its folder, no secrets, no colleagues. Network: the approved sites only, or (Full
    autonomy) any site, with the filesystem limits unchanged."""
    others = [p for p in glob.glob(os.path.join(HOME, "employees", "*"))
              if os.path.realpath(p) != os.path.realpath(emp["workspace"])]
    domains = BASE_DOMAINS + registry().get("network_domains", []) + emp.get("network_domains", [])
    return json.dumps({
        "enabledPlugins": {},
        "sandbox": {
            "enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
            "network": {"allowedDomains": sorted(set(domains)), "strictAllowlist": not autonomous(emp)},
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


def command(emp: dict, model: str, interactive: bool = False) -> list:
    """The claude command for one turn. interactive=True is the owner's own window on the same conversation
    (`orbit chat`): no -p, no stream, and a tool outside the allowlist asks instead of being refused."""
    import abilities                                       # the owners' ticks decide the tools
    allow, block = abilities.tools(emp["id"])
    gateways = abilities.commands(emp["id"])
    bundle = skills_plugin(emp, abilities.skills(emp["id"]))
    import connectors                                      # the MCP servers the owner granted this crew member
    servers = connectors.mcp_config(emp)["mcpServers"]
    mcp = []
    if servers:
        path = os.path.join(HOME, ".runtime", emp["id"], "mcp.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": servers}, fh)
        mcp = ["--mcp-config", path]
    mode = "bypassPermissions" if autonomous(emp) else ("default" if interactive else "dontAsk")
    cmd = [resolve_claude()] + ([] if interactive else ["-p"]) + ["--model", model, "--effort", emp.get("effort", "medium"),
           "--permission-mode", mode] + ([] if interactive else ["--output-format", "stream-json", "--verbose"]) + [
           "--setting-sources", "project", "--strict-mcp-config", *mcp,
           "--settings", settings_json(emp, gateways), "--plugin-dir", GUARD, "--plugin-dir", bundle,
           "--append-system-prompt", "Paths: your team folder (~/Staff in the handbook) is %s; the kit (the handbook, "
           "skills and tools) is %s. %s" % (HOME, KIT, abilities.prompt(emp["id"])),
           "--allowedTools", *([t for t in BASE_ALLOWED if t not in block] + allow + emp.get("extra_tools", []) +
                               ["mcp__%s" % n for n in servers]),
           "--disallowedTools", *(BASE_DENIED + block + emp.get("extra_denied", []))]
    for extra in emp.get("add_dirs", []):
        cmd += ["--add-dir", os.path.expanduser(extra)]
    if "act_in_browser" in abilities.effective(emp["id"]):   # the owner's own Chrome, through Claude in Chrome
        cmd.append("--chrome")
    return cmd


NETWORK = re.compile(r"ENOTFOUND|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|network|reach the API", re.I)


def online(timeout: float = 4) -> bool:
    """Can this computer reach Claude right now? A DNS lookup and a TCP connect to the API; nothing is sent.
    Behind a proxy we can't tell, so we say yes and let the run find out."""
    if any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY")):
        return True
    try:
        with socket.create_connection(("api.anthropic.com", 443), timeout=timeout):
            return True
    except OSError:
        return False


def wait_online(limit: int = 600, every: int = 20) -> bool:
    """After a network failure (the Mac just woke up, the Wi-Fi dropped): wait up to `limit` seconds for it back."""
    end = time.time() + limit
    while time.time() < end:
        if online():
            return True
        time.sleep(every)
    return online()


def friendly_error(err: str) -> str:
    if re.search(r"usage limit|rate limit|limit reached", err, re.I):
        return "I've hit the Claude usage limit; I'll pick this up after it resets. Nothing is lost."
    if re.search(r"authenticate|OAuth|not logged in|log in", err, re.I):
        return osinfo.local("My Claude sign-in on this Mac has expired. Owner: run `claude auth login` in Terminal.")
    if NETWORK.search(err):
        return "I couldn't reach Claude for 10 minutes: this computer looks asleep or offline. Send it again when it's back."
    return "Something went wrong on my side (logged). Please resend."


def why_failed(err: str) -> str:
    """The reason a routine didn't run, in a few plain words (for the team room)."""
    if NETWORK.search(err):
        return "this computer was asleep or offline when it was due"
    if re.search(r"usage limit|rate limit|limit reached", err, re.I):
        return "your Claude plan's limit was reached"
    if re.search(r"authenticate|OAuth|not logged in|log in", err, re.I):
        return "my Claude sign-in expired (run `claude auth login` in a terminal)"
    if re.search(r"timed out", err, re.I):
        return "it ran out of time"
    return "an error on my side (logged)"


def stream(cmd: list, prompt: str, ws: str, env: dict, timeout: int, on_step=None):
    """Runs one claude turn, reading its stream-json events as they come: each tool call becomes a plain
    step ("Reading tiktok.com") passed to on_step(step, steps). Returns (final result event, steps).
    What the crew member *says* is every message that ended a turn: when a background job it started finishes,
    Claude Code wakes it again and it ends another turn, so a run can speak more than once (the standup, then
    "the render passed"). All of it is delivered, not only the last line; text written beside tool calls is
    narration and stays in the receipt."""
    import steps as steps_mod
    t0, steps, result, killed, said = time.time(), [], None, [], []
    errf = tempfile.TemporaryFile()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf, text=True, cwd=ws, env=env)
    import awake                                           # the computer stays up until this run ends
    awake.hold(p.pid)

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
                msg = ev.get("message") or {}
                if msg.get("stop_reason") == "end_turn":
                    spoken = "\n".join(b.get("text", "") for b in msg.get("content") or []
                                       if isinstance(b, dict) and b.get("type") == "text").strip()
                    if spoken:
                        said.append(spoken)
                for b in msg.get("content") or []:
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
        parts = [s for s in said if not s.upper().startswith("SILENT")]
        if not result.get("is_error") and len(said) > 1 and parts:
            result = {**result, "result": "\n\n".join(parts)}
        return result, steps
    finally:
        timer.cancel()
        p.stdout.close()
        errf.close()


# ------------------------------------------------------------------ one conversation, two doors
# A crew member's conversation has one writer at a time: a run (busy.json) or the owner's own window on it
# (chat.json, written by `orbit chat`; or a Claude Code window on that session, seen in ~/.claude/sessions).
WINDOW_IDLE = 20 * 60          # a window left open but untouched this long no longer holds the routines


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def marker(ws: str, name: str):
    """state/<name>.json when the process that wrote it is still alive, else None (and the stale file goes)."""
    p = os.path.join(ws, "state", name + ".json")
    try:
        with open(p) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if _alive(d.get("pid")):
        return d
    try:
        os.remove(p)
    except OSError:
        pass
    return None


def mark(ws: str, name: str, **data) -> None:
    p = os.path.join(ws, "state", name + ".json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump({"pid": os.getpid(), "since": time.strftime("%Y-%m-%dT%H:%M:%S"), **data}, fh)


def unmark(ws: str, name: str) -> None:
    try:
        os.remove(os.path.join(ws, "state", name + ".json"))
    except OSError:
        pass


def busy(ws: str):
    """The run in progress on this conversation ({"pid", "since", "job"}), or None."""
    return marker(ws, "busy")


def main_session(ws: str):
    try:
        with open(os.path.join(ws, "state", "sessions.json")) as fh:
            return json.load(fh).get(SESSION)
    except (OSError, ValueError):
        return None


def window_open(ws: str):
    """Is the owner in a window on this crew member's conversation right now? `orbit chat` leaves state/chat.json;
    any Claude Code window on the same session shows in ~/.claude/sessions. → {"since", "kind"} or None."""
    m = marker(ws, "chat")
    if m:
        return {"since": m.get("since"), "kind": "terminal"}
    sid = main_session(ws)
    if not sid:
        return None
    for p in glob.glob(os.path.join(H, ".claude", "sessions", "*.json")):
        try:
            with open(p) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if d.get("sessionId") == sid and _alive(d.get("pid")):
            return {"since": d.get("procStart") or "", "kind": d.get("entrypoint") or "claude"}
    return None


def window_idle(ws: str) -> float:
    """Seconds since the conversation's transcript last changed (a window open but untouched)."""
    sid = main_session(ws)
    if not sid:
        return 0
    p = os.path.join(transcripts(ws), sid + ".jsonl")
    try:
        return max(0.0, time.time() - os.path.getmtime(p))
    except OSError:
        return 0


def wait_for_window(ws: str, on_wait=None, limit: int = WINDOW_IDLE, every: float = 5.0) -> bool:
    """A run waits while the owner has a window open on the conversation, like a colleague who doesn't start
    the standup while you're talking to them. A window left idle for `limit` seconds stops holding things:
    the run goes ahead. True when the way is clear, False when it went ahead over an idle window."""
    while True:
        w = window_open(ws)
        if not w:
            return True
        if window_idle(ws) >= limit:
            return False
        if on_wait:
            on_wait(w)
        time.sleep(every)


def remember_session(ws: str, key: str, sid: str) -> None:
    sessions_f = os.path.join(ws, "state", "sessions.json")
    try:
        with open(sessions_f) as fh:
            sessions = json.load(fh)
    except (OSError, ValueError):
        sessions = {}
    sessions[key], sessions[key + "_day"] = sid, time.strftime("%F")
    os.makedirs(os.path.dirname(sessions_f), exist_ok=True)
    with open(sessions_f, "w") as fh:
        json.dump(sessions, fh, indent=1)


def chat_window(emp: dict) -> dict:
    """The owner's own Claude window on this crew member's running conversation: `claude --resume <main>` in
    its folder with the same model, settings and locks as its runs. A new conversation (none yet, or the old
    one is full) starts with the orientation note as its first message. → {"cmd", "env", "cwd", "sid", "new"}"""
    ws = emp["workspace"]
    sid = main_session(ws)
    new = not sid or context_tokens(ws, sid) >= FULL
    if new:
        sid = str(uuid.uuid4())
    cmd = command(emp, pick_model(emp, "chat"), interactive=True)
    cmd += ["--resume", sid] if not new else ["--session-id", sid, ORIENT.strip()]
    return {"cmd": cmd, "env": clean_env(emp), "cwd": ws, "sid": sid, "new": new}


def run(emp: dict, prompt: str, job: str = "chat", session_key: str = None,
        timeout: int = 1800, extra_env: dict = None, on_step=None) -> dict:
    """Run the employee headless in its folder, in its one running conversation: every routine, follow-up and chat
    is a new turn of the same session, so it remembers the day like a chat window does (`session_key` names another
    thread; tests use it). on_step(step, steps) is called live for every tool call; the steps also come back in the result."""
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
    model = pick_model(emp, job)
    base = command(emp, model)
    key = session_key or SESSION
    while True:                                            # one writer at a time: another process's run finishes first
        b = busy(ws)
        if not b or b.get("pid") == os.getpid():
            break
        time.sleep(3)
    clear = wait_for_window(ws, on_step and (lambda w: on_step({"text": "Waiting: the owner has a chat window open", "wait": True}, [])))
    attempts = []
    if sessions.get(key) and not (key == SESSION and fresh_start(sessions, ws)):
        attempts.append(("resume", sessions[key]))
    attempts.append(("new", str(uuid.uuid4())))
    aside = not clear and key == SESSION                   # the owner's window stays on main: this turn runs on a copy

    def remember(sid):
        sessions[key], sessions[key + "_day"] = sid, time.strftime("%F")
        os.makedirs(os.path.dirname(sessions_f), exist_ok=True)
        with open(sessions_f, "w") as fh:
            json.dump(sessions, fh, indent=1)
    t0, d, steps = time.time(), {}, []
    if not online():
        wait_online()                                      # just woke up, or the Wi-Fi dropped: give it up to 10 minutes
    mark(ws, "busy", job=job)
    try:
        for kind, sid in attempts:
            cmd = base + (["--resume", sid] + (["--fork-session"] if aside and kind == "resume" else [])
                          if kind == "resume" else ["--session-id", sid])
            text = prompt if kind == "resume" else ORIENT + prompt
            d, steps = stream(cmd, text, ws, {**clean_env(emp), **(extra_env or {})}, timeout, on_step)
            if not d.get("is_error"):
                if not aside:
                    remember(sid)
                break
            if NETWORK.search(str(d.get("result", ""))) and wait_online():
                d, steps = stream(cmd, text, ws, {**clean_env(emp), **(extra_env or {})}, timeout, on_step)   # back online: once more
                if not d.get("is_error"):
                    if not aside:
                        remember(sid)
                    break
            if re.search(r"limit|authenticate", str(d.get("result", ""))) or NETWORK.search(str(d.get("result", ""))):
                break                                          # a fresh session won't help
    finally:
        unmark(ws, "busy")
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
            "secs": rec["secs"], "cost_usd": rec["cost_usd"], "tokens": rec["tokens"],
            "transient": bool(err) and bool(NETWORK.search(err) or re.search(r"usage limit|rate limit|limit reached", err, re.I))}


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
def claude_session(emp_id: str) -> dict:
    """Readies the employee's folder so a Claude app session opened there is that employee, with the same locks
    as its runs: the sandbox, the deny list and the guard (installed for this folder only), its abilities and
    its tools. Written to .claude/settings.local.json, which the harness's own runs don't read (they use
    --setting-sources project), so runs and sessions never double up. → {"folder", "link", "hello", "chat"}: `link` opens a new Claude app chat there
    whose first message sets up its routines (claudeapp); `chat` is the chat once it has (None before)."""
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
    import connectors
    servers = connectors.mcp_config(emp)["mcpServers"]
    mcp_path = os.path.join(ws, ".mcp.json")              # the granted connectors, pre-approved below
    if servers:
        with open(mcp_path, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": servers}, fh, indent=2)
    elif os.path.exists(mcp_path):
        os.remove(mcp_path)
    perms = {"allow": [t for t in BASE_ALLOWED if t not in block] + allow + emp.get("extra_tools", []) +
             ["mcp__%s" % n for n in servers], "deny": deny}
    if autonomous(emp):                                    # the owner's choice: no stops; the sandbox is the boundary
        perms["defaultMode"] = "bypassPermissions"
        perms["allow"] += [t for t in ("WebSearch", "WebFetch", "Task", "NotebookEdit") if t not in perms["allow"]]
    local["enabledMcpjsonServers"] = sorted(servers)
    local.update({
        "sandbox": sandbox,
        "permissions": perms,
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
    import grants                                          # the key the guard needs to apply an owner's Yes
    grants.key()
    import urllib.parse
    import claudeapp
    claudeapp.write_plan(emp_id)
    hello = claudeapp.setup_message(emp_id)                # the chat sets up its routines, then says hello
    link = "claude://code/new?" + urllib.parse.urlencode({"folder": ws, "q": hello}, quote_via=urllib.parse.quote)
    return {"folder": ws, "link": link, "hello": hello, "chat": claudeapp.chat_link(emp_id)}
