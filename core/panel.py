"""The control panel: a small web app on this Mac (http://127.0.0.1:7317) where owners see and run
the team. No accounts, no cloud, nothing to build. Started by staffd in a thread; `staff panel`
opens it in the browser.

The page (core/panel/) is plain HTML, CSS and JavaScript; it talks to the JSON API below. Every change
goes through orders.py and is logged in team/orders.jsonl.

Security: listens on 127.0.0.1 only; a secret token (in ~/Staff/.secrets/panel_token, which employees
can't read) is exchanged once for an HttpOnly SameSite=Strict cookie; the Host header must be this Mac
(no DNS rebinding) and every write must carry our own Origin (no cross-site posts). Employees' shells
can't reach localhost (sandbox) and the toolbelt gateways refuse local addresses.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(CORE, "tools"))
import abilities  # noqa: E402
import engine  # noqa: E402
import hire  # noqa: E402
import orders  # noqa: E402
import skillbook  # noqa: E402
import team  # noqa: E402

STATIC = os.path.join(CORE, "panel")
ROLES_F = os.path.join(CORE, "roles.json")
ABOUT = os.path.join(team.TEAM, "ABOUT.md")
PENDING = os.path.join(team.TEAM, "pending_owners.json")
MEMORY_FILES = ("STATE.md", "TASKS.md", "GOALS.md", "LESSONS.md", "CLAUDE.md")
WORK_DIRS = ("research", "notes", "tools", "growth", "evals")
TEXT_EXT = (".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".py", ".sh", ".js", ".html", ".yaml", ".yml", ".log")
MAX_FILE = 400_000
_auth = {"at": 0.0, "ok": None, "note": ""}


def port() -> int:
    return int(engine.registry().get("panel", {}).get("port", 7317))


def token() -> str:
    t = engine.secret("panel_token")
    if not t:
        os.makedirs(engine.SECRETS, exist_ok=True)
        os.chmod(engine.SECRETS, 0o700)
        t = secrets.token_urlsafe(24)
        p = os.path.join(engine.SECRETS, "panel_token")
        with open(p, "w") as fh:
            fh.write(t)
        os.chmod(p, 0o600)
    return t


def url() -> str:
    return "http://127.0.0.1:%d/?t=%s" % (port(), token())


def daemon_online() -> bool:
    try:
        return time.time() - os.path.getmtime(os.path.join(team.TEAM, "staffd_alive")) < 120
    except OSError:
        return False


def claude_auth() -> dict:
    """`claude auth status`, cached for ten minutes (it takes a second)."""
    if time.time() - _auth["at"] < 600:
        return _auth
    _auth["at"] = time.time()
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_")) and k != "CLAUDECODE"}
        r = subprocess.run([engine.resolve_claude(), "auth", "status"], capture_output=True, text=True, timeout=20, env=env)
        d = json.loads(r.stdout or "{}")
        _auth["ok"] = bool(d.get("loggedIn"))
        _auth["note"] = d.get("authMethod", "") if _auth["ok"] else "not signed in"
    except Exception as ex:  # noqa: BLE001
        _auth["ok"], _auth["note"] = None, "couldn't check (%s)" % ex.__class__.__name__
    return _auth


# ------------------------------------------------------------------ reading the team
def members():
    reg = engine.registry()
    total = len(abilities.catalog())
    out = []
    for k, m in reg.get("employees", {}).items():
        if m.get("status") == "retired":
            continue
        emp = engine.employee(k)
        s = engine.stats(emp)
        paused = m.get("status") == "paused"
        nj, nw = team.next_job(k) if not paused else (None, None)
        out.append({"id": k, "name": m["name"], "role": m["role"], "scope": m.get("scope", ""), "supervisor": m.get("supervisor", ""),
                    "status": "paused" if paused else "active", "doing": team.DOING.get(k), "hired": m.get("hired"),
                    "last_run": s["last_run"], "next_job": nj, "next_job_at": nw.strftime("%Y-%m-%dT%H:%M:%S") if nw else None,
                    "runs_today": s["runs_today"], "failures_today": s["failures_today"],
                    "use_today": round(s["use_today"], 3), "use_7d": round(s["use_7d"], 3),
                    "abilities": sorted(abilities.effective(k)), "abilities_on": len(abilities.effective(k)), "abilities_total": total,
                    "model": m.get("model") or emp.get("model", "sonnet"), "effort": m.get("effort") or emp.get("effort", "medium")})
    return out


def waiting_lines(emp_id):
    """Bullets under 'Waiting on owners' in the employee's TASKS.md."""
    ws = engine.employee(emp_id)["workspace"]
    try:
        with open(os.path.join(ws, "TASKS.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            inside = "waiting on" in line.lower()
            continue
        if inside and line.strip().startswith(("-", "*")):
            out.append(line.strip()[1:].strip())
    return out[:10]


def reminders_for(emp_id, ws):
    import remind
    return remind.load(ws)


def needs_you(emps, ords, pending, usage):
    out = []
    today = time.strftime("%Y-%m-%d")
    day_ago = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    for i, p in pending.items():
        out.append({"kind": "owner", "title": "%s messaged your bot" % (p.get("name") or "Someone"),
                    "detail": "Approve them as an owner or ignore. Owners can direct every employee.", "href": "/settings#access"})
    for o in ords:
        if o.get("status") == "failed" and o.get("ts", "") >= day_ago:
            out.append({"kind": "failed", "title": o.get("summary", "An order failed"), "detail": o.get("result", ""), "href": "/"})
    for e in emps:
        if e["status"] == "paused":
            out.append({"kind": "paused", "title": "%s is paused" % e["name"], "detail": "Routines and chats are off until you resume them.",
                        "href": "/e/%s" % e["id"], "emp": e["id"]})
        if e["failures_today"]:
            out.append({"kind": "failed", "title": "%s: %d run%s failed today" % (e["name"], e["failures_today"], "" if e["failures_today"] == 1 else "s"),
                        "detail": "See Activity for the reason.", "href": "/e/%s/activity" % e["id"], "emp": e["id"]})
        for line in waiting_lines(e["id"]):
            out.append({"kind": "waiting", "title": line, "detail": "%s is waiting on you" % e["name"], "href": "/e/%s/memory" % e["id"], "emp": e["id"]})
        ws = engine.employee(e["id"])["workspace"]
        for r in reminders_for(e["id"], ws):
            if r.get("to") != "me" and r.get("at", "")[:10] <= today:
                out.append({"kind": "reminder", "title": r.get("text", ""), "detail": "Reminder from %s · %s" % (e["name"], r.get("at", "")[11:]),
                            "href": "/e/%s" % e["id"], "emp": e["id"]})
    if usage.get("five_hour", 0) >= 80 or usage.get("seven_day", 0) >= 90:
        out.append({"kind": "usage", "title": "Claude plan usage is high", "detail": "Employees switch to the light model until it resets.", "href": "/settings"})
    return out[:30]


def checklist(emps, feed):
    reg = engine.registry()
    auth = claude_auth()
    model = os.path.join(engine.HOME, "models", "ggml-large-v3-turbo-q5_0.bin")
    emp_ids = {e["id"] for e in emps}
    return [
        {"id": "claude", "done": bool(auth["ok"]), "title": "Claude Code signed in", "how": "Run `claude` in Terminal and sign in with your Claude account."},
        {"id": "service", "done": daemon_online(), "title": "The team service is running", "how": "Run `staff start` in Terminal. It starts at login from then on."},
        {"id": "telegram", "done": bool(team.bot_token()), "title": "Telegram bot connected", "how": "Create a bot with @BotFather, then run `staff secret telegram`."},
        {"id": "owner", "done": any(not o.get("local") for o in reg.get("owners", {}).values()), "title": "You're paired on Telegram",
         "how": "Message your bot once, then approve yourself under Access in Settings."},
        {"id": "hire", "done": bool(emps), "title": "First employee hired", "how": "Pick a role on the Hire page."},
        {"id": "hello", "done": any(r.get("from_id") in emp_ids for r in feed), "title": "First conversation", "how": "Open an employee and say hello."},
        {"id": "apify", "done": bool(engine.secret("apify_token")), "optional": True, "title": "Apify connected (social media and Maps research)",
         "how": "Free account at apify.com, then `staff secret apify`."},
        {"id": "voice", "done": os.path.exists(model), "optional": True, "title": "Voice notes on this Mac",
         "how": "`brew install ffmpeg whisper-cpp`, then `staff doctor --get-voice-model`."},
    ]


def state():
    reg = engine.registry()
    emps = members()
    feed = team.tail(team.FEED, 150)
    ords = team.tail(team.ORDERS, 40)
    pending = team.jload(PENDING, {})
    usage = engine.usage()
    me = next(iter(reg.get("owners", {}).values()), {}).get("name", "Owner")
    return {"team_name": reg.get("team_name", "Staffroom"), "me": me, "online": daemon_online(), "now": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "usage": usage, "owners": [{"id": i, "name": o["name"], "local": bool(o.get("local"))} for i, o in reg.get("owners", {}).items()],
            "employees": emps, "feed": feed, "orders": ords,
            "pending": [{"id": i, **p} for i, p in pending.items()],
            "needs": needs_you(emps, ords, pending, usage), "checklist": checklist(emps, feed),
            "working": dict(team.DOING), "jobs": team.JOBS,
            "team_skills": [{k: v for k, v in s.items() if k != "path"} for s in skillbook.listing(skillbook.TEAM_DIR, "team")]}


def employee_detail(emp_id):
    reg = engine.registry()
    if emp_id not in reg.get("employees", {}) or reg["employees"][emp_id].get("status") == "retired":
        return None
    m = next(e for e in members() if e["id"] == emp_id)
    emp = engine.employee(emp_id)
    ws = emp["workspace"]
    memory = {}
    for f in MEMORY_FILES:
        try:
            with open(os.path.join(ws, f), encoding="utf-8") as fh:
                memory[f] = fh.read()[:MAX_FILE]
        except OSError:
            memory[f] = ""
    runs = []
    try:
        with open(os.path.join(ws, "state", "runs.jsonl"), encoding="utf-8") as fh:
            for line in fh.readlines()[-80:]:
                try:
                    runs.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    files = []
    for d in WORK_DIRS:
        root = os.path.join(ws, d)
        for base, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for n in sorted(names):
                if n.startswith("."):
                    continue
                p = os.path.join(base, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                files.append({"path": os.path.relpath(p, ws), "size": st.st_size, "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
                              "text": n.lower().endswith(TEXT_EXT)})
                if len(files) >= 400:
                    break
    files.sort(key=lambda f: f["mtime"], reverse=True)
    # Private Telegram chats live only in the chat log; panel and group messages are already in the team room.
    dms = [r for r in team.tail(team.CHATLOG, 400) if r.get("employee") == emp_id and r.get("channel") == "telegram"]
    chat = [{"ts": r.get("ts", ""), "from_id": "owner", "from_name": r.get("who", "Owner"), "to_id": emp_id, "body": r.get("text", ""), "channel": "telegram"}
            for r in dms]
    chat += [{"ts": r.get("ts", "") + " ", "from_id": emp_id, "from_name": m["name"], "to_id": "owner", "body": r.get("answer", ""), "channel": "telegram"}
             for r in dms if r.get("answer")]
    chat += [r for r in team.tail(team.FEED, 400) if r.get("from_id") == emp_id or r.get("to_id") == emp_id]
    chat.sort(key=lambda r: r.get("ts", ""))
    sk = skillbook.overview(emp_id)
    skills = {k: [{a: b for a, b in s.items() if a != "path"} for s in v] for k, v in sk.items()}
    return {**m, "abilities": sorted(abilities.effective(emp_id)), "chosen": abilities.chosen(emp_id), "memory": memory,
            "runs": list(reversed(runs)), "files": files, "reminders": reminders_for(emp_id, ws), "chat": chat[-120:],
            "workspace": ws, "network_domains": emp.get("network_domains", []), "skills": skills}


def skill_action(f, me):
    """Owners teach, edit, share and remove skills from the panel. Logged like every order."""
    emp = str(f.get("emp") or "")
    where = "team" if f.get("where") == "team" else "own"
    name, do = str(f.get("name") or "").strip().lower(), str(f.get("do") or "")
    reg = engine.registry().get("employees", {})
    if emp not in reg or reg[emp].get("status") == "retired":
        raise orders.OrderError("No such employee")
    try:
        if do == "create":
            skillbook.create(emp, name, str(f.get("description") or ""), str(f.get("text") or ""), by=me, how="panel")
            res = "Taught. %s uses it from their next run." % reg[emp]["name"]
        elif do == "save":
            res = skillbook.save(emp, where, name, str(f.get("text") or ""), me)
        elif do == "share":
            res = skillbook.share(emp, name, me)
        elif do == "remove":
            res = skillbook.remove(emp, where, name, me)
        else:
            raise orders.OrderError("Unknown action")
    except skillbook.SkillError as ex:
        team.order_log(me, "skill", "%s skill %s" % (do.capitalize(), name), "failed", str(ex))
        raise orders.OrderError(str(ex))
    team.order_log(me, "skill", "%s skill %s (%s)" % (do.capitalize(), name, reg[emp]["name"]), "done", res)
    return res


def read_file(emp_id, rel):
    emp = engine.employee(emp_id)
    ws = os.path.realpath(emp["workspace"])
    p = os.path.realpath(os.path.join(ws, rel))
    if not p.startswith(ws + os.sep) or any(part in (".git", ".claude", "state") for part in rel.split(os.sep)):
        raise orders.OrderError("Not a file you can open here")
    if not p.lower().endswith(TEXT_EXT) or not os.path.isfile(p):
        raise orders.OrderError("Only text files open in the panel")
    with open(p, encoding="utf-8", errors="replace") as fh:
        text = fh.read(MAX_FILE + 1)
    return {"path": rel, "text": text[:MAX_FILE], "truncated": len(text) > MAX_FILE}


def set_rules(emp_id, by, text):
    """Replace the 'Role-specific rules' section of the employee's CLAUDE.md."""
    emp = engine.employee(emp_id)
    p = os.path.join(emp["workspace"], "CLAUDE.md")
    with open(p, encoding="utf-8") as fh:
        doc = fh.read()
    head = "## Role-specific rules"
    i = doc.find(head)
    body = doc[:i] if i >= 0 else doc.rstrip() + "\n\n"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body + head + "\n" + text.strip()[:20000] + "\n")
    subprocess.run(["git", "add", "CLAUDE.md"], cwd=emp["workspace"], capture_output=True)
    subprocess.run(["git", "-c", "user.name=%s" % by, "-c", "user.email=owner@staffroom.local", "commit", "-qm", "rules: edited by %s in the panel" % by],
                   cwd=emp["workspace"], capture_output=True)
    team.order_log(by, "rules", "Rules for %s" % emp["name"], "done", "%d characters" % len(text.strip()))
    return "Rules saved. %s reads them on their next run." % emp["name"]


def save_settings(f, by):
    reg = engine.registry()
    reg["team_name"] = (str(f.get("team_name") or "").strip() or "Staffroom")[:60]
    wd = [d for d in (f.get("workdays") or []) if d in team.DAYS]
    reg["workdays"] = wd or ["Mon", "Tue", "Wed", "Thu", "Fri"]
    doms = []
    for line in str(f.get("network_domains") or "").replace(",", "\n").splitlines():
        d = line.strip().lower()
        if d and all(c.isalnum() or c in ".-*" for c in d) and "." in d:
            doms.append(d)
    reg["network_domains"] = sorted(set(doms))[:100]
    jobs = reg.setdefault("jobs", {})
    for j, v in (f.get("jobs") or {}).items():
        v = str(v).strip()
        if j in team.JOBS and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            jobs.setdefault(j, {})["at"] = v
    ap = reg.setdefault("apify", {})
    for k, hi in (("monthly_budget_usd", 1000.0), ("max_run_usd", 2.0)):
        try:
            ap[k] = max(0.0, min(hi, float((f.get("apify") or {}).get(k))))
        except (TypeError, ValueError):
            pass
    engine.save_registry(reg, "settings changed in the control panel by %s" % by)
    if "about" in f:
        with open(ABOUT, "w", encoding="utf-8") as fh:
            fh.write(str(f["about"])[:6000].replace("\r\n", "\n"))
    return "Settings saved"


def approve_owner(f, me):
    pend = team.jload(PENDING, {})
    i = str(f.get("id") or "")
    if i not in pend:
        raise orders.OrderError("That request is gone")
    p = pend.pop(i)
    team.jsave(PENDING, pend)
    if f.get("do") != "approve":
        return "Ignored"
    name = (str(f.get("name") or "").strip() or p.get("name") or "Owner")[:40]
    reg = engine.registry()
    owners = reg.setdefault("owners", {})
    for k in [k for k, o in owners.items() if o.get("local") and o["name"].lower() == name.lower()]:
        owners.pop(k)                                     # the setup placeholder becomes the real Telegram owner
    owners[i] = {"name": name, "aliases": []}
    engine.save_registry(reg, "owner added: %s (by %s)" % (name, me))
    hire.directory(reg)
    team.order_log(me, "owner", "Make %s an owner" % name, "done", "Telegram id %s" % i)
    return "%s is now an owner" % name


def settings_view():
    reg = engine.registry()
    try:
        with open(ABOUT, encoding="utf-8") as fh:
            about = fh.read()
    except OSError:
        about = ""
    sys.path.insert(0, os.path.join(CORE, "tools"))
    import apify
    spent, pending = apify.month_spend(team.jload(os.path.join(engine.HOME, "state", "apify_spend.json"), {}))
    return {"team_name": reg.get("team_name", ""), "about": about, "workdays": reg.get("workdays", ["Mon", "Tue", "Wed", "Thu", "Fri"]),
            "network_domains": reg.get("network_domains", []), "jobs": {j: team.job_spec({}, j)["at"] for j in team.JOBS},
            "apify": {"token": bool(engine.secret("apify_token")), "spent": spent + pending, **reg.get("apify", {})},
            "auth": reg.get("auth", "subscription"), "claude": claude_auth(), "telegram": bool(team.bot_token()), "group_id": team.group_id(),
            "home": engine.HOME, "kit": engine.KIT, "port": port()}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "Staffroom"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; errors go to staffd.log
        pass

    # -- helpers
    def _origin(self):
        return "http://127.0.0.1:%d" % port(), "http://localhost:%d" % port()

    def _allowed_host(self):
        return "http://" + (self.headers.get("Host") or "").lower() in self._origin()

    def _authed(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sr" and hmac.compare_digest(v, token()):
                return True
        return False

    def _me(self):
        owners = engine.registry().get("owners", {})
        return next(iter(owners.values()), {}).get("name", "Owner")

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
                                                    "img-src 'self' data:; font-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", "sr=%s; HttpOnly; SameSite=Strict; Path=/" % cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _static(self, name):
        p = os.path.realpath(os.path.join(STATIC, name))
        if not p.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(p):
            return self._send(404, "Not found", "text/plain")
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(p, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # -- GET
    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, "Forbidden", "text/plain")
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if "t" in q:
            if hmac.compare_digest(q["t"][0], token()):
                return self._redirect(u.path or "/", cookie=token())
            return self._send(403, "Wrong link. Run `staff panel` in Terminal to open the panel.", "text/plain")
        if not self._authed():
            return self._send(401, "Open the panel with `staff panel` in Terminal.", "text/plain")
        path = u.path
        try:
            if path.startswith("/api/"):
                return self._api_get(path, q)
            if path in ("/app.css", "/app.js", "/icon.svg"):
                return self._static(path[1:])
            return self._static("index.html")               # the app routes the rest
        except orders.OrderError as ex:
            return self._json(400, {"error": str(ex)})
        except Exception as ex:  # noqa: BLE001
            team.log("panel error: %r" % ex)
            return self._json(500, {"error": "Something broke (logged in team/staffd.log)"})

    def _api_get(self, path, q):
        if path == "/api/state":
            return self._json(200, state())
        if path == "/api/abilities":
            return self._json(200, {"groups": abilities.groups(), "abilities": abilities.catalog()})
        if path == "/api/roles":
            with open(ROLES_F, encoding="utf-8") as fh:
                return self._json(200, json.load(fh))
        if path == "/api/settings":
            return self._json(200, settings_view())
        m = re.fullmatch(r"/api/employee/([a-z0-9-]+)", path)
        if m:
            d = employee_detail(m.group(1))
            return self._json(200, d) if d else self._json(404, {"error": "No such employee"})
        if path == "/api/file":
            return self._json(200, read_file(q.get("emp", [""])[0], q.get("path", [""])[0]))
        if path == "/api/skill":
            emp = q.get("emp", [""])[0]
            if emp not in engine.registry().get("employees", {}):
                return self._json(404, {"error": "No such employee"})
            where = q.get("where", [""])[0]
            try:
                return self._json(200, skillbook.read(emp, where if where in ("team", "kit") else "own", q.get("name", [""])[0]))
            except skillbook.SkillError as ex:
                return self._json(404, {"error": str(ex)})
        return self._json(404, {"error": "Not found"})

    # -- POST
    def do_POST(self):
        if not self._allowed_host() or not self._authed():
            return self._send(403, "Forbidden", "text/plain")
        if (self.headers.get("Origin") or "") not in self._origin():
            return self._send(403, "Forbidden", "text/plain")
        n = min(int(self.headers.get("Content-Length") or 0), 500_000)
        try:
            f = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(f, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "Bad request"})
        me = self._me()
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/order":
                kind = str(f.pop("kind", ""))
                return self._json(200, {"ok": True, "message": orders.execute(me, kind, f)})
            if path == "/api/settings":
                return self._json(200, {"ok": True, "message": save_settings(f, me)})
            if path == "/api/owner":
                return self._json(200, {"ok": True, "message": approve_owner(f, me)})
            if path == "/api/skill":
                return self._json(200, {"ok": True, "message": skill_action(f, me)})
            m = re.fullmatch(r"/api/employee/([a-z0-9-]+)/rules", path)
            if m and m.group(1) in engine.registry().get("employees", {}):
                return self._json(200, {"ok": True, "message": set_rules(m.group(1), me, str(f.get("text") or ""))})
            return self._json(404, {"error": "Not found"})
        except (orders.OrderError, hire.HireError) as ex:
            return self._json(400, {"error": str(ex)})
        except Exception as ex:  # noqa: BLE001
            team.log("panel order error: %r" % ex)
            return self._json(500, {"error": "Something broke (logged in team/staffd.log)"})


def serve():
    token()
    threading.Thread(target=claude_auth, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port()), Handler)
    srv.daemon_threads = True
    team.log("panel on http://127.0.0.1:%d" % port())
    srv.serve_forever()


if __name__ == "__main__":
    print(url())
    serve()
