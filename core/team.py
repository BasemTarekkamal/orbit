"""Shared runtime for staffd and the control panel: running employees in the background, delivering
their words to owners on Telegram, the team room log, the order log, routine schedules.
Harness-owned. Python 3.9 compatible.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid

import abilities
import engine

TEAM = os.path.join(engine.HOME, "team")
LOG = os.path.join(TEAM, "staffd.log")
STATEF = os.path.join(TEAM, "staffd_state.json")
BUS = os.path.join(TEAM, "bus.jsonl")
FEED = os.path.join(TEAM, "feed.jsonl")          # the team room, as the control panel shows it
ORDERS = os.path.join(TEAM, "orders.jsonl")      # what owners asked for in the panel, and what happened
CHATLOG = os.path.join(TEAM, "chatlog.jsonl")
DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
JOBS = {"brief": "Morning brief", "standup": "Standup", "eod": "End of day", "scout": "Self-improvement",
        "evals": "Weekly self-test"}
DEFAULT_JOBS = {"brief": {"at": "08:30", "days": "work"}, "standup": {"at": "09:00", "days": "work"},
                "eod": {"at": "17:00", "days": "work"}, "scout": {"at": "19:00", "days": "daily"},
                "evals": {"at": "10:00", "days": "Fri"}}
LOCKS = {}                 # one run at a time per employee
DOING = {}                 # employee id → what they're running now
_io = threading.Lock()


def log(msg):
    os.makedirs(TEAM, exist_ok=True)
    with _io, open(LOG, "a", encoding="utf-8") as fh:
        fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def jload(p, default):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def append(p, rec):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with _io, open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def tail(p, n=200):
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()[-n:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def feed(from_id, from_name, to_id, body, channel):
    """One line in the team room. channel: bus | telegram | panel | job."""
    append(FEED, {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "from_id": from_id,
                  "from_name": from_name, "to_id": to_id, "body": str(body)[:8000], "channel": channel})


def order_log(by, kind, summary, status, result=""):
    append(ORDERS, {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by,
                    "kind": kind, "summary": summary[:300], "status": status, "result": str(result)[:500]})


def active(runtime_ok=True):
    return {k: e for k, e in engine.registry().get("employees", {}).items() if e.get("status", "active") == "active"}


# ------------------------------------------------------------------ Telegram delivery
def token_from(path):
    try:
        with open(os.path.expanduser(path)) as fh:
            return fh.read().strip()
    except (OSError, TypeError):
        return ""


def bot_token():
    return engine.secret("telegram_bot_token") or ""


def api(tok, method, params=None, timeout=60):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                   for k, v in (params or {}).items()}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://api.telegram.org/bot%s/%s" % (tok, method), data=data), timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "description": str(e)}


def group_id():
    return str(engine.registry().get("telegram", {}).get("group_id") or "")


def send(chat_id, text, emp=None):
    """Deliver text to an owner or the team group. Nobody else, whatever the caller asks."""
    reg = engine.registry()
    if str(chat_id) not in reg.get("owners", {}) and str(chat_id) != group_id():
        log("refused send to %s" % chat_id)
        return
    tok = bot_token()
    prefix = "%s: " % emp["name"] if emp else ""
    if not tok:
        append(os.path.join(TEAM, "undelivered.jsonl"), {"ts": time.strftime("%F %T"), "to": chat_id,
                                                         "from": emp and emp["id"], "text": text})
        return
    files = re.findall(r"ATTACH:\s*(\S+)", text)
    body = (prefix + re.sub(r"\s*ATTACH:\s*\S+", "", text).strip()) or "(done)"
    for i in range(0, len(body), 3900):
        api(tok, "sendMessage", {"chat_id": chat_id, "text": body[i:i + 3900], "disable_web_page_preview": "true"})
    ws = emp["workspace"] if emp else engine.HOME
    for f in files:
        p = os.path.realpath(os.path.join(ws, f))
        if p.startswith(os.path.realpath(ws) + os.sep) and os.path.isfile(p):
            subprocess.run(["curl", "-s", "-F", "chat_id=%s" % chat_id, "-F", "document=@%s" % p,
                            "https://api.telegram.org/bot%s/sendDocument" % tok], capture_output=True, timeout=120)


def to_people(emp, target):
    """'supervisor' | owner name | 'all' → owner chat ids."""
    reg = engine.registry()
    if target in ("both", "all"):
        return list(reg.get("owners", {}).keys())
    if target == "supervisor":
        target = emp.get("supervisor", "")
    oid = engine.owner_id(str(target))
    return [oid] if oid else list(reg.get("owners", {}).keys())[:1]


# ------------------------------------------------------------------ running employees
def run_async(emp_id, prompt, job, session_key, deliver_to, who="", on_done=None, extra_env=None, said=None, channel=None):
    """Runs an employee in the background (one run at a time each). on_done(output) gets the final text.
    `said` is the owner's own words (for the chat log); the prompt wraps them."""
    def work():
        lock = LOCKS.setdefault(emp_id, threading.Lock())
        with lock:
            emp = engine.employee(emp_id)
            DOING[emp_id] = ("Talking with %s" % who) if job == "chat" and who else "Running %s" % JOBS.get(job, job)
            try:
                res = engine.run(emp, prompt, job=job, session_key=session_key, extra_env=extra_env)
            except Exception:  # noqa: BLE001
                log("run error %s/%s: %s" % (emp_id, job, traceback.format_exc()[-400:]))
                res = {"ok": False, "text": "Something went wrong on my side (logged).", "error": "crash"}
            finally:
                DOING.pop(emp_id, None)
            out = res["text"]
            if on_done:
                try:
                    on_done(out)
                except Exception:  # noqa: BLE001
                    log("on_done error: %s" % traceback.format_exc()[-300:])
            if job == "chat" or (out and not out.upper().startswith("SILENT")):
                for c in deliver_to:
                    send(c, out, emp)
            if job == "chat":
                append(CHATLOG, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "who": who, "employee": emp_id, "channel": channel,
                                 "text": (said if said is not None else prompt)[:4000], "answer": out[:8000]})
            if not res["ok"] and job != "chat":
                st = jload(STATEF, {})
                k = "alert:%s:%s:%s" % (emp_id, job, time.strftime("%F"))
                if not st.get(k):
                    st[k] = 1
                    jsave(STATEF, st)
                    for c in to_people(emp, "supervisor"):
                        send(c, "My %s run failed (%s). I'll retry next time." % (JOBS.get(job, job), res["error"][:120]), emp)
            subprocess.run(["git", "add", "-A"], cwd=emp["workspace"], capture_output=True)
            subprocess.run(["git", "-c", "user.name=%s" % emp["name"], "-c", "user.email=%s@staffroom.local" % emp_id,
                            "commit", "-qm", "%s: %s" % (job, (out.splitlines() or ["-"])[0][:80])],
                           cwd=emp["workspace"], capture_output=True)
    threading.Thread(target=work, daemon=True).start()


def to_room(emp_id, name, to, channel):
    """on_done callback: post an employee's reply in the team room (skips SILENT)."""
    def post(out):
        if out and not out.strip().upper().startswith("SILENT"):
            feed(emp_id, name, to, out, channel)
    return post


def now_str():
    return time.strftime("%a %d %b %Y %H:%M")


def chat_prompt(who, where, text, extra=""):
    return ("[Message from %s (owner) in %s, %s local time]\n%s\n%s\n\nFollow CLAUDE.md and the handbook. Your "
            "final answer is sent to them verbatim (plain text; add 'ATTACH: <path in your folder>' to send a file). "
            "Update your memory files before you finish." % (who, where, now_str(), text, extra))


def panel_prompt(who, text, team):
    return ("[Message from %s (owner) %sin the control panel's team room, %s local time]\n%s\n\nFollow CLAUDE.md and "
            "the handbook. Your final answer is posted in the team room (plain text), where the owners read it.%s "
            "Update your memory files before you finish."
            % (who, "to the whole team " if team else "", now_str(), text,
               " Reply SILENT unless it's meant for you or you have something useful to add." if team else ""))


def recent_chat(emp_id, n=15):
    rows = ["- %s %s: %s" % (r["ts"], r["who"], r["text"][-160:].replace("\n", " "))
            for r in tail(CHATLOG, 300) if r.get("employee") == emp_id]
    return "\n".join(rows[-n:]) or "(none)"


def job_prompt(emp_id, e, job, note=""):
    with open(os.path.join(engine.CORE, "jobs", job + ".md"), encoding="utf-8") as fh:
        tpl = fh.read()
    ctx = "\n\n---\nContext: now %s local time.%s Recent owner messages to you:\n%s" % (now_str(), note, recent_chat(emp_id))
    tpl = tpl.replace("$STAFFROOM_KIT", engine.KIT)
    return tpl.replace("{name}", e["name"]).replace("{role}", e["role"]).replace("{supervisor}", e.get("supervisor", "")) + ctx


# ------------------------------------------------------------------ schedules
def job_spec(emp, job):
    reg = engine.registry()
    return {**DEFAULT_JOBS.get(job, {}), **reg.get("jobs", {}).get(job, {}), **emp.get("job_overrides", {}).get(job, {})}


def due_today(spec_days, wd):
    if spec_days == "daily":
        return True
    if spec_days == "work":
        return wd in [DAYS[d] for d in engine.registry().get("workdays", ["Mon", "Tue", "Wed", "Thu", "Fri"])]
    return wd in [DAYS[d] for d in str(spec_days).split(",") if d in DAYS]


def next_job(emp_id):
    """(job label, datetime) of the next routine this employee will run, or (None, None)."""
    emp = engine.employee(emp_id)
    now = dt.datetime.now()
    best = (None, None)
    for job in abilities.jobs(emp_id):
        spec = job_spec(emp, job)
        h, m = [int(x) for x in spec["at"].split(":")]
        for add in range(8):
            day = now + dt.timedelta(days=add)
            when = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if when > now and due_today(spec.get("days", "daily"), when.weekday()):
                if not best[1] or when < best[1]:
                    best = (JOBS[job], when)
                break
    return best
