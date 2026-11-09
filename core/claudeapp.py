"""The crew member's chat in the Claude app: where it works and reports, like any Claude chat you leave running.

The owner talks to a crew member in one Claude app chat, opened in the crew member's own folder (so the same
sandbox, guard and abilities apply). A chat only acts when a message arrives, so its thinking routines (standup,
initiative, end of day, weekly review) are the Claude app's own scheduled tasks used as alarms: at the routine's
time the task's run sends one message into the chat ("your standup is due: do it now"), and the crew member does
the routine right there. The owner sees the work and the report in that chat, with the unread dot.
(The app's "notify on completion" doesn't wake a chat, so a run that did the work elsewhere never reached the owner;
a message from one session to another does: tested 9 Nov 2026.)

Orbit can't call the Claude app's tools itself, so it writes the plan and the chat sets it up:
  * state/claude_app_plan.json   written by Orbit: one entry per routine (task id, title, cron, alarm prompt)
  * core/jobs/claude_app.md      the brief the chat follows to create or update the tasks from the plan
  * state/claude_app.json        written by the chat: {"chat", "link", "routines", "plan"}; the alarm reads "chat"
While a routine is in state/claude_app.json the Claude app runs it, and staffd doesn't (no double runs). Follow-ups,
reminders, the morning brief, scout, the self-test, the team bus and phone channels stay with Orbit's service.

    import claudeapp
    claudeapp.write_plan("sara")      # → the plan dict (also saved in her folder)
    claudeapp.owned("sara")           # → {"standup", "eod", ...}: what the Claude app runs for her now
    claudeapp.chat_link("sara")       # → "claude://claude.ai/epitaxy/local_…" or None
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import engine

ROUTINES = ("standup", "initiative", "eod", "review")     # the thinking routines: the ones the owner reads
DOW = {"Sun": 0, "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6}   # cron's day numbers
LINK = "claude://claude.ai/epitaxy/%s"
ALARM = """This run is an alarm for {name}'s {label}, nothing more. Don't do the work here, and change no files.
1. Read state/claude_app.json in this folder: its "chat" is {name}'s chat with {supervisor}.
2. Load SendMessage with one ToolSearch call (query "select:SendMessage") and send that chat the message between the
   lines below, exactly as written. If SendMessage doesn't load, load mcp__ccd_session_mgmt__send_message the same way
   and send it with session_id set to the chat.
3. Reply with one line: sent, or why not.
----------
{message}
----------"""
MESSAGE = ("Your {label_lower} is due: the routine you set up in this chat at {supervisor}'s request. Do it now, here in "
           "this chat, as {name} for {supervisor}: follow {brief}. First read what your background runs reported since "
           "your last report here: your lines in {feed}, newest at the bottom. Your reply in this chat is what "
           "{supervisor} reads: what you did, where things stand, what you need from them. If there is truly nothing, "
           "say so in one line.")


def _ws(emp_id: str) -> str:
    return engine.employee(emp_id)["workspace"]


def cron(spec: dict) -> str:
    """A routine's schedule as a cron line in local time: {"at": "09:00", "days": "work"} → "0 9 * * 1,2,3,4,5"."""
    hh, mm = (str(spec.get("at") or "09:00").split(":") + ["0"])[:2]
    days = spec.get("days", "work")
    work = engine.registry().get("workdays", ["Mon", "Tue", "Wed", "Thu", "Fri"])
    if days == "daily":
        dow = "*"
    elif days == "work":
        dow = "*" if len(set(work)) == 7 else ",".join(str(DOW[d]) for d in work if d in DOW)
    elif days == "last_workday":
        dow = str(DOW.get(work[-1], 5)) if work else "5"
    else:
        dow = ",".join(str(DOW[d]) for d in str(days).split(",") if d in DOW) or "*"
    return "%d %d * * %s" % (int(mm), int(hh), dow)


def plan(emp_id: str) -> dict:
    """The routines the Claude app should run for this crew member, with the prompt each run gets."""
    import abilities
    import team
    e = engine.employee(emp_id)
    on = [j for j in abilities.jobs(emp_id) if j in ROUTINES]
    feed = os.path.join(engine.HOME, "team", "feed.jsonl")
    tasks = []
    sup = e.get("supervisor") or "the owner"
    for job in on:
        spec = team.job_spec(e, job)
        if not spec:
            continue
        label = team.JOBS.get(job, job)
        message = MESSAGE.format(label_lower=label.lower(), supervisor=sup, name=e["name"], feed=feed,
                                 brief=os.path.join(engine.CORE, "jobs", job + ".md"))
        tasks.append({"job": job, "task_id": "%s-%s" % (emp_id, job), "title": "%s · %s" % (e["name"], label),
                      "description": "Wakes %s's Claude chat for the %s" % (e["name"], label.lower()),
                      "cron": cron(spec), "message": message,
                      "prompt": ALARM.format(name=e["name"], label=label.lower(), supervisor=sup, message=message)})
    version = hashlib.sha1(json.dumps(tasks, sort_keys=True).encode()).hexdigest()[:10]
    return {"employee": emp_id, "name": e["name"], "supervisor": e.get("supervisor", ""), "version": version,
            "brief": os.path.join(engine.CORE, "jobs", "claude_app.md"), "tasks": tasks}


def write_plan(emp_id: str) -> dict:
    p = plan(emp_id)
    path = os.path.join(_ws(emp_id), "state", "claude_app_plan.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return p


def state(emp_id: str) -> dict:
    """What the crew member's Claude chat recorded after setting up its routines ({} when it hasn't)."""
    try:
        with open(os.path.join(_ws(emp_id), "state", "claude_app.json"), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError, KeyError):
        return {}
    if not isinstance(d, dict) or not re.fullmatch(r"local_[0-9a-f-]{36}", str(d.get("chat", ""))):
        return {}
    return d


def owned(emp_id: str) -> set:
    """The routines the Claude app runs for this crew member now; staffd leaves these alone."""
    return {j for j in state(emp_id).get("routines", []) if j in ROUTINES}


def chat_link(emp_id: str):
    s = state(emp_id)
    return LINK % s["chat"] if s else None


def stale(emp_id: str) -> bool:
    """The routines in the Claude app were set up from an older plan (times or prompts changed since)."""
    s = state(emp_id)
    if not s:
        return False
    try:
        with open(os.path.join(_ws(emp_id), "state", "claude_app_plan.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version") != s.get("plan")
    except (OSError, ValueError):
        return False


def setup_message(emp_id: str) -> str:
    """What the owner's first message (or a nudge) to the crew member's Claude chat says to set it all up."""
    e = engine.employee(emp_id)
    return ("Hi %s. This chat is where you and I work together from now on. Set up your routines here first: read "
            "%s and do what it says. Then introduce yourself in a few lines: your job as you understand it, what "
            "you'll do first, and anything you need from me." % (e["name"], os.path.join(engine.CORE, "jobs", "claude_app.md")))

