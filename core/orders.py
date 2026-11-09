"""Owner orders from the control panel: one function per kind, each returning a plain result line.
Every order is logged in team/orders.jsonl. Harness-owned: only owners reach this, never employees.
"""
from __future__ import annotations

import os
import re
import time

import abilities
import engine
import hire
import team

KINDS = ("message", "hire", "pause", "resume", "retire", "run_job", "set_abilities", "set_field", "set_browser", "set_autonomy",
         "connect", "connector", "teach", "save_role", "publish_role", "import_role", "agree_plan", "set_cloud", "call_start", "call_stop")


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
    import grants                                         # an owner's switch typed in the panel: Orbit flips it
    done = grants.from_text(by, text)
    if done:
        team.feed(by, by, eid or "team", text, "panel")
        team.feed("staff", "Orbit", eid or "team", done, "panel")
        return done
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
        team.run_async(t, team.panel_prompt(by, text, team=eid == "team"), "chat", None, [], who=by,
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
            card = p.get("card") if isinstance(p.get("card"), dict) else None
            new = hire.hire(p.get("name", ""), p.get("role", ""), p.get("scope", ""), supervisor=sup, preset=preset,
                            picked=picked, model=p.get("model") or None, card=card)
            if p.get("template"):                         # a saved or community role: its skills and rules come along
                import rolebook
                rolebook.apply_template(new, re.sub(r"[^a-z0-9-]", "", str(p["template"]))[:40])
            import cloud
            if p.get("cloud", True) and not cloud.available():   # the service sets up their cloud desk
                reg = engine.registry()
                reg["employees"][new]["cloud_shift"] = True
                engine.save_registry(reg, "cloud shift on for new hire %s" % new)
            e = engine.registry()["employees"][new]
            team.feed("staff", "Orbit", "team", "%s joined as %s, reporting to %s. Message them here, or /%s (@%s on "
                      "Slack and Discord) in your chat." % (e["name"], e["role"], e["supervisor"], new, new), "panel")
            if p.get("first_day", True):                  # they start with real work, not an empty chat
                team.run_async(new, team.job_prompt(new, engine.employee(new), "first_day"), "first_day", None, [],
                               who=sup, on_done=team.to_room(new, e["name"], e["supervisor"], "panel"))
            summary, res = "Hire %s (%s)" % (e["name"], e["role"]), "Hired: handle /%s" % new
        elif kind in ("pause", "resume", "retire"):
            e = _emp(eid, want_active=False)
            hire.set_status(eid, {"pause": "paused", "resume": "active", "retire": "retired"}[kind])
            import cloud
            if cloud.is_on(eid) and cloud.state(eid).get("slots"):
                try:                                      # resuming: the next tick brings them back on schedule
                    if kind == "resume":
                        cloud.rearm(eid, cloud.state(eid))
                    else:
                        cloud.hold(eid)
                except cloud.CloudError as ex:
                    team.log("cloud %s: %s" % (eid, ex))
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
        elif kind == "call_start":
            import calls
            e = _emp(eid)
            if not abilities.has(eid, "meetings"):
                raise OrderError("%s's Meetings ability is off: turn it on in Abilities first" % e["name"])
            try:
                calls.start(eid, by, p.get("title", ""), on_end=team.call_ended)
            except calls.CallError as err:
                raise OrderError(str(err))
            summary, res = "Listen to a call with %s" % e["name"], "Listening. Minutes come when you end it"
        elif kind == "call_stop":
            import calls
            e = _emp(eid, want_active=False)
            st = calls.stop(eid)
            if not st:
                raise OrderError("%s isn't listening to a call" % e["name"])
            summary, res = "End the call with %s" % e["name"], "Ended after %s min; writing the minutes" % st["minutes"]
        elif kind == "set_abilities":
            e = _emp(eid, want_active=False)
            preset = p.get("preset")
            ids = abilities.preset(preset) if preset in ("default", "super") else list(p.get("abilities") or [])
            added, removed = hire.set_abilities(eid, ids, by)
            diff = ["+" + n for n in added] + ["−" + n for n in removed]
            label = " (super agent)" if preset == "super" else " (default)" if preset == "default" else ""
            summary = "Abilities for %s%s" % (e["name"], label)
            res = ", ".join(diff) if diff else "No change"
        elif kind == "set_browser":                       # the owner's consent: post for them on these sites, from its own window
            e = _emp(eid, want_active=False)
            sites = [str(x) for x in p.get("sites") or []][:20] if isinstance(p.get("sites"), list) else []
            b = hire.set_browser(eid, sites, str(p.get("approval") or "each"), by)
            try:
                engine.claude_session(eid)                # their Claude sessions pick it up too
            except Exception as ex:  # noqa: BLE001
                team.log("claude_session after set_browser: %r" % ex)
            summary = "Posts for you: %s" % e["name"]
            res = ("On for %s, %s" % (", ".join(b["sites"]), {"none": "without asking you", "batch": "after you approve each batch"}
                                     .get(b.get("approval"), "after you approve each one"))) if b else "Off"
            team.feed("staff", "Orbit", eid, "%s: %s. %s" % (summary, res, "Open them in Claude again to use it there." if b else ""), "panel")
        elif kind == "connector":
            e = _emp(eid, want_active=False)
            import connectors
            try:
                res = (connectors.revoke(eid, str(p.get("ref") or ""), by) if p.get("off") else
                       connectors.grant(eid, str(p.get("ref") or ""), by, str(p.get("name") or "")))
            except ValueError as ex:
                raise OrderError(str(ex))
            summary = "Connector for %s" % e["name"]
        elif kind == "teach":                             # the owner's own know-how → the crew member's skills
            e = _emp(eid)
            text = str(p.get("text") or "").strip()[:200000]
            if len(text) < 40:
                raise OrderError("Paste the playbook, notes or process (a few lines at least)")
            ws = engine.employee(eid)["workspace"]
            slug = re.sub(r"[^a-z0-9]+", "-", str(p.get("title") or "experience").lower()).strip("-")[:40] or "experience"
            rel = os.path.join("notes", "teach", "%s-%s.md" % (time.strftime("%Y-%m-%d"), slug))
            os.makedirs(os.path.join(ws, "notes", "teach"), exist_ok=True)
            with open(os.path.join(ws, rel), "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            prompt = team.job_prompt(eid, engine.employee(eid), "learn").replace("$FILE", rel)
            team.run_async(eid, prompt, "learn", None, [], who=by, on_done=team.to_room(eid, e["name"], by, "panel"))
            summary, res = "Teach %s" % e["name"], "%s is reading it and turning it into skills" % e["name"]
        elif kind == "save_role":                         # with the draft the owner read and edited (Share)
            e = _emp(eid, want_active=False)
            import rolebook
            d = p.get("draft") if isinstance(p.get("draft"), dict) else None
            if d:
                d = {"title": str(d.get("title") or "")[:80], "summary": str(d.get("summary") or "")[:300],
                     "rules": str(d.get("rules") or "")[:20000], "experience": str(d.get("experience") or "")[:40000],
                     "trained_by": str(d.get("trained_by") or by)[:60],
                     "skills": [{"name": str(x.get("name") or ""), "text": str(x.get("text") or "")[:40000]}
                                for x in (d.get("skills") or [])[:30] if isinstance(x, dict)]}
            try:
                res = rolebook.save_role(eid, str(p.get("title") or ""), by, draft=d)
            except rolebook.RoleError as ex:
                raise OrderError(str(ex))
            summary = "Save %s as a role" % e["name"]
        elif kind == "publish_role":
            import rolebook
            try:
                out = rolebook.publish(re.sub(r"[^a-z0-9-]", "", str(p.get("role") or ""))[:40], by)
            except rolebook.RoleError as ex:
                raise OrderError(str(ex))
            summary, res = "Share a role with the community", out["url"]
            team.order_log(by, kind, summary, "done", res)
            return out
        elif kind == "import_role":
            import base64
            import rolebook
            try:
                if p.get("data"):
                    res = rolebook.import_role(data=base64.b64decode(str(p["data"]).split(",")[-1]))
                else:
                    res = rolebook.import_role(str(p.get("url") or "").strip())
            except (rolebook.RoleError, ValueError, OSError) as ex:
                raise OrderError(str(ex) or "Couldn't read that role")
            summary = "Add a role"
        elif kind == "set_cloud":                         # the owner's choice: work on in the cloud when this computer is away
            e = _emp(eid, want_active=False)
            import cloud
            try:
                res = cloud.enable(eid, by) if p.get("on") else cloud.disable(eid, by)
            except cloud.CloudError as ex:
                raise OrderError(str(ex))
            summary = "Cloud shift for %s" % e["name"]
        elif kind == "agree_plan":
            e = _emp(eid, want_active=False)
            import plan
            try:
                res = plan.agree(eid, by)
            except ValueError as ex:
                raise OrderError(str(ex))
            team.feed(by, by, eid, "I agree to your plan. Go.", "panel")
            summary = "Agree to %s's plan" % e["name"]
        elif kind == "connect":
            e = _emp(eid, want_active=False)
            res = hire.connect(eid, str(p.get("other") or ""), str(p.get("note") or ""), by)
            summary = "Connect %s" % e["name"]
        elif kind == "set_autonomy":
            e = _emp(eid, want_active=False)
            on = hire.set_autonomy(eid, bool(p.get("on")), by)
            try:
                engine.claude_session(eid)
            except Exception as ex:  # noqa: BLE001
                team.log("claude_session after set_autonomy: %r" % ex)
            summary, res = "Full autonomy for %s" % e["name"], "On" if on else "Off"
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
