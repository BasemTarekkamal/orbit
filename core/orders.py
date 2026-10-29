"""Owner orders from the control panel: one function per kind, each returning a plain result line.
Every order is logged in team/orders.jsonl. Harness-owned: only owners reach this, never employees.
"""
from __future__ import annotations

import re

import abilities
import engine
import hire
import team

KINDS = ("message", "hire", "pause", "resume", "retire", "run_job", "set_abilities", "set_field")


class OrderError(ValueError):
    pass


def _emp(eid, want_active=True):
    reg = engine.registry().get("employees", {})
    if eid not in reg or reg[eid].get("status") == "retired":
        raise OrderError("No such employee")
    if want_active and reg[eid].get("status", "active") != "active":
        raise OrderError("%s is paused; resume them first" % reg[eid]["name"])
    return reg[eid]


def message(by, eid, text):
    text = str(text or "").strip()[:4000]
    if not text:
        raise OrderError("Write a message first")
    act = team.active()
    if eid and eid != "team":
        _emp(eid)
        targets = [eid]
    else:
        low = text.lower()
        targets = [k for k, e in act.items() if re.search(r"(^|\W)@?%s(\W|$)" % re.escape(k), low)
                   or e["name"].lower() in low] or list(act)
        eid = "team"
    if not targets:
        raise OrderError("Nobody is working yet: hire someone first")
    team.feed(by, by, eid, text, "panel")
    for t in targets:
        team.run_async(t, team.panel_prompt(by, text, team=eid == "team"), "chat", "panel:" + by.lower(), [], who=by,
                       on_done=team.to_room(t, act[t]["name"], by, "panel"), said=text, channel="panel")
    return "Passed to " + ", ".join(act[t]["name"] for t in targets)


def execute(by, kind, p):
    """→ result line. Raises OrderError with a plain reason."""
    if kind not in KINDS:
        raise OrderError("Unknown order")
    eid = str(p.get("employee_id") or "")
    try:
        if kind == "message":
            res = message(by, eid, p.get("text"))
            summary = "Message to %s" % (engine.registry()["employees"].get(eid, {}).get("name") or "the team")
        elif kind == "hire":
            sup = p.get("supervisor") or by
            preset = "super" if p.get("preset") == "super" else "default"
            picked = [str(x) for x in p["abilities"]][:100] if isinstance(p.get("abilities"), list) else None
            new = hire.hire(p.get("name", ""), p.get("role", ""), p.get("scope", ""), supervisor=sup, preset=preset,
                            picked=picked, model=p.get("model") or None)
            e = engine.registry()["employees"][new]
            team.feed("staff", "Staffroom", "team", "%s joined as %s, reporting to %s. Message them here, or /%s (@%s on "
                      "Slack and Discord) in your chat." % (e["name"], e["role"], e["supervisor"], new, new), "panel")
            summary, res = "Hire %s (%s)" % (e["name"], e["role"]), "Hired: handle /%s" % new
        elif kind in ("pause", "resume", "retire"):
            e = _emp(eid, want_active=False)
            hire.set_status(eid, {"pause": "paused", "resume": "active", "retire": "retired"}[kind])
            verb = {"pause": "Paused", "resume": "Resumed", "retire": "Retired"}[kind]
            summary, res = "%s %s" % (kind.capitalize(), e["name"]), "%s %s" % (verb, e["name"])
        elif kind == "run_job":
            job = p.get("job")
            if job not in team.JOBS:
                raise OrderError("Unknown routine")
            e = _emp(eid)
            emp = engine.employee(eid)
            team.run_async(eid, team.job_prompt(eid, emp, job, " Run now on request from %s." % by), job, None,
                           team.to_people(emp, "supervisor"), on_done=team.to_room(eid, e["name"], e.get("supervisor", ""), "job"))
            summary, res = "Run %s for %s now" % (team.JOBS[job], e["name"]), "Started; the result goes to the team room"
        elif kind == "set_abilities":
            e = _emp(eid, want_active=False)
            preset = p.get("preset")
            ids = abilities.preset(preset) if preset in ("default", "super") else list(p.get("abilities") or [])
            added, removed = hire.set_abilities(eid, ids, by)
            diff = ["+" + n for n in added] + ["−" + n for n in removed]
            label = " (super agent)" if preset == "super" else " (default)" if preset == "default" else ""
            summary = "Abilities for %s%s" % (e["name"], label)
            res = ", ".join(diff) if diff else "No change"
        else:  # set_field
            e = _emp(eid, want_active=False)
            field, value = p.get("field"), str(p.get("value") or "").strip()
            hire.set_field(eid, field, value)
            summary, res = "%s for %s" % (str(field).capitalize(), e["name"]), "Set to %s" % (value or "the default")
    except (hire.HireError, OrderError) as err:
        team.order_log(by, kind, kind.replace("_", " "), "failed", str(err))
        raise OrderError(str(err))
    team.order_log(by, kind, summary, "done", res)
    return "%s: %s" % (summary, res)
