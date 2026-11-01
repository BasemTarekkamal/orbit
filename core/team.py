"""Shared runtime for staffd and the control panel: running employees in the background, delivering
their words to owners on whichever chat channel they use, the team room log, the order log, routine
schedules. Harness-owned. Python 3.9 compatible.
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
import uuid

import abilities
import channels
import engine
import osinfo

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
LABELS = {**JOBS, "first_day": "First day", "minutes": "Meeting minutes", "followup": "a follow-up",
          "bus": "a colleague's question"}
PAIRING = os.path.join(TEAM, "pairing.json")     # the one-time code that links an owner's phone to the team
DEFAULT_JOBS = {"brief": {"at": "08:30", "days": "work"}, "standup": {"at": "09:00", "days": "work"},
                "eod": {"at": "17:00", "days": "work"}, "scout": {"at": "19:00", "days": "daily"},
                "evals": {"at": "10:00", "days": "Fri"}}
LOCKS = {}                 # one run at a time per employee
DOING = {}                 # employee id → what they're running now
LIVE = {}                  # employee id → {"doing", "started", "steps"}: the live work view
LAST = {}                  # employee id → the finished run's receipt {"steps", "secs", "cost_usd"}
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


def feed(from_id, from_name, to_id, body, channel, receipt=None):
    """One line in the team room. channel: bus | telegram | slack | discord | group | panel | job | skill.
    receipt: how an employee's answer was made ({"steps", "secs", "cost_usd"}), shown under it."""
    rec = {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "from_id": from_id,
           "from_name": from_name, "to_id": to_id, "body": str(body)[:8000], "channel": channel}
    if receipt and receipt.get("steps"):
        rec["receipt"] = receipt
    append(FEED, rec)


def order_log(by, kind, summary, status, result=""):
    append(ORDERS, {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by,
                    "kind": kind, "summary": summary[:300], "status": status, "result": str(result)[:500]})


def active(runtime_ok=True):
    return {k: e for k, e in engine.registry().get("employees", {}).items() if e.get("status", "active") == "active"}


# ------------------------------------------------------------------ delivery (any channel)
def bot_token():
    """The Telegram bot token (kept for the setup wizard and older callers)."""
    return engine.secret("telegram_bot_token") or ""


def api(tok, method, params=None, timeout=60):
    """Telegram's API (kept for the setup wizard and older callers)."""
    return channels.get("telegram").api(tok, method, params, timeout)


def team_chats() -> dict:
    """{channel: chat id} of the team chats (the Telegram group, a Slack channel, a Discord channel)."""
    reg = engine.registry()
    out = {k: str(v) for k, v in (reg.get("team_chats") or {}).items() if v and k in channels.NAMES}
    legacy = (reg.get("telegram") or {}).get("group_id")
    if legacy and "telegram" not in out:
        out["telegram"] = str(legacy)
    return out


def team_addrs() -> set:
    return {channels.addr(k, v) for k, v in team_chats().items()}


def group_id():
    """The Telegram team group's id (older callers)."""
    return team_chats().get("telegram", "")


def dm_chats() -> dict:
    """{private chat address: owner key}: where each owner last wrote to us, per channel."""
    return jload(STATEF, {}).get("dms", {})


def remember_dm(chat, owner):
    st = jload(STATEF, {})
    dms = st.setdefault("dms", {})
    if dms.get(chat) != owner or st.get("last_dm:%s" % owner) != chat:
        dms[chat] = owner
        st["last_dm:%s" % owner] = chat
        jsave(STATEF, st)


def may_send_to(chat) -> bool:
    """Only an owner's own address, a private chat an owner opened, or a team chat. Nobody else, ever."""
    n = channels.norm(chat)
    return bool(engine.owner_key(n)) or n in dm_chats() or n in team_addrs()


def send(chat, text, emp=None):
    """Deliver text (and ATTACH: files) to an owner or a team chat, on the channel its address names."""
    chat = channels.norm(chat)
    if not may_send_to(chat):
        log("refused send to %s" % chat)
        return
    ch, cid = channels.parse(chat)
    try:
        mod = channels.get(ch)
        ready = bool(mod.token())
    except Exception:  # noqa: BLE001
        mod, ready = None, False
    prefix = "%s: " % emp["name"] if emp else ""
    if not ready:
        append(os.path.join(TEAM, "undelivered.jsonl"), {"ts": time.strftime("%F %T"), "to": chat,
                                                         "from": emp and emp["id"], "text": text})
        return
    files = re.findall(r"ATTACH:\s*(\S+)", text)
    body = (prefix + re.sub(r"\s*ATTACH:\s*\S+", "", text).strip()) or "(done)"
    for i in range(0, len(body), mod.LIMIT):
        try:
            mod.send(cid, body[i:i + mod.LIMIT])
        except Exception as e:  # noqa: BLE001
            log("%s send failed: %s" % (ch, e))
    ws = emp["workspace"] if emp else engine.HOME
    for f in files:
        p = os.path.realpath(os.path.join(ws, f))
        if p.startswith(os.path.realpath(ws) + os.sep) and os.path.isfile(p):
            try:
                mod.send_file(cid, p)
            except Exception as e:  # noqa: BLE001
                log("%s file send failed: %s" % (ch, e))


def owner_address(key):
    """Where to write to an owner: the private chat they last used, else a fresh private chat on the
    channel they paired with. None for an owner who only exists on this Mac."""
    st = jload(STATEF, {})
    last = st.get("last_dm:%s" % key)
    if last:
        return last
    o = engine.registry().get("owners", {}).get(key, {})
    for a in [key] + list(o.get("addresses", [])):
        ch, uid = channels.parse(a)
        if not ch:
            continue
        try:
            mod = channels.get(ch)
            if not mod.token():
                continue
            cid = mod.dm_chat(uid)
        except Exception:  # noqa: BLE001
            continue
        if cid:
            chat = channels.addr(ch, cid)
            remember_dm(chat, key)
            return chat
    return None


def to_people(emp, target):
    """'supervisor' | owner name | 'all' → delivery addresses (one per owner)."""
    reg = engine.registry()
    if target in ("both", "all"):
        keys = list(reg.get("owners", {}).keys())
    else:
        if target == "supervisor":
            target = emp.get("supervisor", "")
        oid = engine.owner_id(str(target))
        keys = [oid] if oid else list(reg.get("owners", {}).keys())[:1]
    return [a for a in (owner_address(k) for k in keys) if a]


# ------------------------------------------------------------------ running employees
BUDGET_NOTED: dict = {}


def over_budget(emp):
    """Has this crew member used its weekly token budget (set in the hiring interview or in Manage)? Says so in
    the team room once a day, then skips routines until the week rolls on."""
    cap = int(emp.get("weekly_tokens") or 0)
    if not cap:
        return False
    used = engine.stats(emp)["tokens_7d"]
    if used < cap:
        return False
    today = time.strftime("%Y-%m-%d")
    if BUDGET_NOTED.get(emp["id"]) != today:
        BUDGET_NOTED[emp["id"]] = today
        feed(emp["id"], emp["name"], emp.get("supervisor", "team"),
             "I've used my weekly budget (%s of %s tokens), so my routines wait until it frees up. I still answer you. "
             "Raise it in my Manage tab if you want more." % (fmt_tokens(used), fmt_tokens(cap)), "job")
    return True


def fmt_tokens(n):
    n = int(n or 0)
    return "%.1fM" % (n / 1e6) if n >= 1e6 else "%dk" % round(n / 1e3) if n >= 1e3 else str(n)


def run_async(emp_id, prompt, job, session_key, deliver_to, who="", on_done=None, extra_env=None, said=None, channel=None):
    """Runs an employee in the background (one run at a time each). on_done(output) gets the final text.
    `said` is the owner's own words (for the chat log); the prompt wraps them."""
    if job == "chat":
        import calls                                      # on a live call: point them at the running transcript
        prompt += calls.live_note(emp_id)

    def work():
        lock = LOCKS.setdefault(emp_id, threading.Lock())
        with lock:
            emp = engine.employee(emp_id)
            if job in DEFAULT_JOBS and over_budget(emp):     # routines wait; chats and owner requests never do
                return
            DOING[emp_id] = ("Talking with %s" % who) if job == "chat" and who else "Working on %s" % LABELS.get(job, job)
            LIVE[emp_id] = {"doing": DOING[emp_id], "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}

            def on_step(step, steps):
                LIVE[emp_id] = {**LIVE.get(emp_id, {}), "steps": [dict(s) for s in steps[-8:]], "count": len(steps)}
            try:
                res = engine.run(emp, prompt, job=job, session_key=session_key, extra_env=extra_env, on_step=on_step)
            except Exception:  # noqa: BLE001
                log("run error %s/%s: %s" % (emp_id, job, traceback.format_exc()[-400:]))
                res = {"ok": False, "text": "Something went wrong on my side (logged).", "error": "crash"}
            finally:
                DOING.pop(emp_id, None)
                LIVE.pop(emp_id, None)
            LAST[emp_id] = {"steps": res.get("steps") or [], "secs": res.get("secs"), "cost_usd": res.get("cost_usd")}
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
                row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "who": who, "employee": emp_id, "channel": channel,
                       "text": (said if said is not None else prompt)[:4000], "answer": out[:8000]}
                if LAST[emp_id]["steps"]:
                    row["receipt"] = LAST[emp_id]
                append(CHATLOG, row)
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
    """on_done callback: post an employee's reply in the team room (skips SILENT), with how it was made."""
    def post(out):
        if out and not out.strip().upper().startswith("SILENT"):
            feed(emp_id, name, to, out, channel, receipt=LAST.get(emp_id))
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


def minutes(emp_id, info, who, title):
    """Minutes from a transcript (a recording sent after the call, or a live call that just ended)."""
    prompt = osinfo.local("An owner ({who}) had a meeting; it was transcribed on the Mac to {t} ({m} min). Write {mn} in the "
              "meeting's main language: summary, decisions, action items (owner, due; set a reminder with "
              "staff-remind for each dated one), items in your scope, open questions, 'My view:' (2–4 honest "
              "points). Flag numbers and names you rely on as (check). Then reply with a ≤ 15-line version for "
              "chat. Title: {title}").format(who=who, t=info["transcript"], m=info.get("duration_min"),
                                             mn=info["minutes"], title=title)
    emp = engine.employee(emp_id)
    run_async(emp_id, prompt, "minutes", None, to_people(emp, "all"),
              on_done=to_room(emp_id, emp["name"], who, "job"))


def call_ended(emp_id, info):
    """calls.py hands a finished live call here."""
    minutes(emp_id, info, info.get("by") or "the owner", info.get("title") or "Call")


def recent_chat(emp_id, n=15):
    rows = ["- %s %s: %s" % (r["ts"], r["who"], r["text"][-160:].replace("\n", " "))
            for r in tail(CHATLOG, 300) if r.get("employee") == emp_id]
    return "\n".join(rows[-n:]) or "(none)"


def job_prompt(emp_id, e, job, note=""):
    with open(os.path.join(engine.CORE, "jobs", job + ".md"), encoding="utf-8") as fh:
        tpl = fh.read()
    ctx = "\n\n---\nContext: now %s local time.%s Recent owner messages to you:\n%s" % (now_str(), note, recent_chat(emp_id))
    tpl = tpl.replace("$STAFFROOM_KIT", engine.KIT)
    card = e.get("card") or {}
    if job == "first_day" and card.get("first_task"):
        note += (" Your first task, agreed in the hiring interview: %s Do that as your one piece of work." % card["first_task"])
        ctx = "\n\n---\nContext: now %s local time.%s Recent owner messages to you:\n%s" % (now_str(), note, recent_chat(emp_id))
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
