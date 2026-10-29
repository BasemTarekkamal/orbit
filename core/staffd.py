#!/usr/bin/env python3
"""staffd: runs the whole team. One launchd service (`staff start`); reads ~/Staff/staff.json every
loop, so a new hire is live within a minute with no restart. Harness-owned.

Each loop (about every minute):
  * Telegram, through the team's bot:
      DM:    "/sara <msg>" talks to Sara (and makes her your default), "/talk sara", "/team",
             plain text goes to your current default; voice notes transcribed on this Mac; photos and
             files saved into the employee's folder; long recordings → meeting minutes.
      Group: the team group (staff.json telegram.group_id): mention "@sara"/"Sara" or reply to her.
      Owners only. Anyone else is ignored (and listed in the control panel for the owner to approve).
  * The team bus (team/bus.jsonl): colleagues asking and answering each other, mirrored to the team room.
  * Routines (brief, standup, end of day, self-improvement, self-test) and reminders, per abilities.
  * The control panel on http://127.0.0.1:<port> (core/panel.py), in a thread.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(CORE, "tools"))
import abilities  # noqa: E402
import engine  # noqa: E402
import team  # noqa: E402
from team import api, jload, jsave, log, run_async, send, to_people  # noqa: E402

PENDING = os.path.join(team.TEAM, "pending_owners.json")


def download(tok, file_id, dest_dir, name):
    info = api(tok, "getFile", {"file_id": file_id})
    if not info.get("ok"):
        return None
    fp = info["result"]["file_path"]
    os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, "%s-%s%s" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^\w.-]", "", name)[:30] or "file",
                                              os.path.splitext(fp)[1] if not os.path.splitext(name)[1] else ""))
    with urllib.request.urlopen("https://api.telegram.org/file/bot%s/%s" % (tok, fp), timeout=120) as r, \
            open(dst, "wb") as out:
        out.write(r.read())
    return dst


def note_stranger(msg):
    """Someone who isn't an owner messaged the bot: list them for the owner, never reply."""
    frm = msg.get("from", {})
    if msg.get("chat", {}).get("type") != "private" or not frm.get("id"):
        return
    pend = jload(PENDING, {})
    pend[str(frm["id"])] = {"name": " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x)[:60],
                            "username": frm.get("username"), "at": time.strftime("%Y-%m-%d %H:%M")}
    jsave(PENDING, dict(list(pend.items())[-20:]))


def pick_employee(text, sticky, reply_name=None):
    emps = team.active()
    m = re.match(r"^/([a-z0-9-]+)(?:@\w+)?\s*(.*)$", text.strip(), re.S)
    if m and m.group(1) in emps:
        return m.group(1), m.group(2).strip()
    low = text.lower()
    for k, e in emps.items():
        if re.search(r"(^|\W)@?%s(\W|$)" % re.escape(k), low) or e["name"].lower() in low or \
                (reply_name and reply_name == e["name"]):
            return k, text
    if sticky in emps:
        return sticky, text
    if len(emps) == 1:
        return next(iter(emps)), text
    return None, text


def handle(tok, msg):
    reg = engine.registry()
    chat = msg.get("chat", {})
    sender = str(msg.get("from", {}).get("id", ""))
    if sender not in reg.get("owners", {}):
        note_stranger(msg)
        return
    who = reg["owners"][sender]["name"]
    group = team.group_id()
    is_group = chat.get("type") in ("group", "supergroup")
    if is_group and str(chat.get("id")) != group:
        log("message from unregistered group %s (%s); `staff group %s` to use it" % (chat.get("id"), chat.get("title"), chat.get("id")))
        return
    st = jload(team.STATEF, {})
    sticky_key = "sticky:%s" % (group if is_group else sender)
    text = (msg.get("text") or msg.get("caption") or "").strip()
    reply_name = None
    rt = (msg.get("reply_to_message") or {}).get("text", "")
    if rt and ":" in rt[:40]:
        reply_name = rt.split(":", 1)[0].strip()
    chat_id = str(chat.get("id"))

    if text in ("/team", "/start", "/help"):
        lines = ["%s — talk to someone with /<handle> <message>:" % reg.get("team_name", "Your team")]
        for k, e in team.active().items():
            lines.append("/%s — %s, %s" % (k, e["name"], e["role"]))
        lines.append("/talk <handle> — make them your default")
        send(chat_id, "\n".join(lines) if len(lines) > 2 else "Nobody works here yet. Hire someone in the control panel.")
        return
    m = re.match(r"^/talk\s+([a-z0-9-]+)", text)
    if m and m.group(1) in team.active():
        st[sticky_key] = m.group(1)
        jsave(team.STATEF, st)
        send(chat_id, "Now talking to %s. Switch any time with /talk <handle>." % engine.employee(m.group(1))["name"])
        return

    emp_id, body = pick_employee(text, st.get(sticky_key), reply_name)
    if is_group:
        mentioned = any(re.search(r"(^|\W)@?%s(\W|$)" % re.escape(k), text.lower()) or e["name"].lower() in text.lower()
                        for k, e in team.active().items()) or reply_name or text.startswith("/")
        if not mentioned:
            return                                        # owners talking to each other: stay out
    if not emp_id:
        send(chat_id, "Who should take this? " + " · ".join("/%s (%s)" % (k, e["role"]) for k, e in team.active().items()))
        return
    if not is_group:
        st[sticky_key] = emp_id
        jsave(team.STATEF, st)
    emp = engine.employee(emp_id)
    if not abilities.has(emp_id, "telegram"):
        send(chat_id, "%s's Telegram chat is switched off. Turn it on in the control panel (Abilities), or message "
                      "them in the team room there." % emp["name"])
        return

    def off(ability, what):
        if abilities.has(emp_id, ability):
            return False
        send(chat_id, "%s can't take %s: it's switched off in the control panel (Abilities)." % (emp["name"], what), emp)
        return True
    env_ws = dict(os.environ, STAFF_WORKSPACE=emp["workspace"], STAFF_EMPLOYEE=emp_id, STAFFROOM_HOME=engine.HOME)

    inbox = os.path.join(emp["workspace"], "state", "inbox")
    extra = ""
    low = body.lower()
    media = msg.get("voice") or msg.get("audio") or msg.get("video") or msg.get("video_note")
    doc = msg.get("document") or {}
    is_av_doc = str(doc.get("mime_type", "")).startswith(("audio/", "video/"))
    if (media or is_av_doc) and ((media or doc).get("duration", 0) >= 180 or msg.get("video") or is_av_doc
                                  or re.search(r"meeting|minutes|اجتماع|محضر", low)):
        f = media or doc
        if off("meetings", "meeting recordings"):
            return
        if f.get("file_size", 0) > 20 * 1024 * 1024:
            send(chat_id, "That's over Telegram's 20 MB bot limit: drop it in %s/state/meetings_in on the Mac." % emp["workspace"], emp)
            return
        p = download(tok, f["file_id"], inbox, f.get("file_name", "meeting.ogg"))
        send(chat_id, "Got the recording. Transcribing on the Mac; minutes shortly.", emp)

        def meet():
            r = subprocess.run([sys.executable, os.path.join(CORE, "tools", "meeting.py"), p, "--title", body or "meeting"],
                               capture_output=True, text=True, env=env_ws, timeout=7200)
            try:
                info = json.loads(r.stdout.strip().splitlines()[-1])
                minutes(emp_id, info, who, body or "meeting")
            except Exception as e:  # noqa: BLE001
                send(chat_id, "I couldn't transcribe that recording (%s)." % e, emp)
        threading.Thread(target=meet, daemon=True).start()
        return
    if media and off("voice", "voice notes"):
        return
    if (msg.get("photo") or doc) and not media and off("files", "photos and files"):
        return
    if media:
        p = download(tok, media["file_id"], inbox, "voice.ogg")
        r = subprocess.run([sys.executable, os.path.join(CORE, "tools", "transcribe.py"), p],
                           capture_output=True, text=True, timeout=600)
        said = r.stdout.strip()
        if not said:
            send(chat_id, "I couldn't transcribe that voice note (%s). Please type it." % (r.stderr.strip()[-120:] or "no speech found"), emp)
            return
        body = "[voice note, transcribed on the Mac; confirm any number before acting]\n%s\n%s" % (said, body)
    elif msg.get("photo"):
        p = download(tok, msg["photo"][-1]["file_id"], inbox, "photo.jpg")
        extra = "Attached photo saved at: %s (Read it)." % p
    elif doc:
        p = download(tok, doc["file_id"], inbox, doc.get("file_name", "file"))
        extra = "Attached file saved at: %s (Read it)." % p
    api(tok, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    where = "the team group" if is_group else "a private chat"
    on_done = None
    if is_group:                                          # the group is the team room too
        team.feed(who, who, emp_id, body, "telegram")
        on_done = team.to_room(emp_id, emp["name"], who, "telegram")
    run_async(emp_id, team.chat_prompt(who, where, body, extra), "chat",
              session_key=("group" if is_group else sender), deliver_to=[chat_id], who=who, on_done=on_done, said=body,
              channel="group" if is_group else "telegram")


def minutes(emp_id, info, who, title):
    prompt = ("An owner ({who}) had a meeting; it was transcribed on the Mac to {t} ({m} min). Write {mn} in the "
              "meeting's main language: summary, decisions, action items (owner, due; set a reminder with "
              "staff-remind for each dated one), items in your scope, open questions, 'My view:' (2–4 honest "
              "points). Flag numbers and names you rely on as (check). Then reply with a ≤ 15-line version for "
              "Telegram. Title: {title}").format(who=who, t=info["transcript"], m=info.get("duration_min"),
                                                  mn=info["minutes"], title=title)
    run_async(emp_id, prompt, "minutes", None, to_people(engine.employee(emp_id), "all"))


# ------------------------------------------------------------------ routines, reminders, bus
def tick_jobs():
    now = dt.datetime.now()
    for k, e in team.active().items():
        emp = engine.employee(k)
        st_f = os.path.join(emp["workspace"], "state", "schedule.json")
        st = jload(st_f, {})
        for job in abilities.jobs(k):
            spec = team.job_spec(emp, job)
            if not spec or not team.due_today(spec.get("days", "daily"), now.weekday()):
                continue
            if now.strftime("%H:%M") < spec["at"] or st.get(job) == now.strftime("%F"):
                continue
            late = (dt.datetime.strptime(spec["at"], "%H:%M") + dt.timedelta(hours=4)).strftime("%H:%M")
            st[job] = now.strftime("%F")
            jsave(st_f, st)
            if now.strftime("%H:%M") > late:
                continue                                  # missed its window (Mac was asleep): skip, don't spam
            log("job %s/%s" % (k, job))
            run_async(k, team.job_prompt(k, emp, job), job, None, to_people(emp, spec.get("to", "supervisor")),
                      on_done=team.to_room(k, emp["name"], emp.get("supervisor", ""), "job"))


def tick_reminders():
    import remind
    for k in team.active():
        if not abilities.has(k, "reminders"):
            continue
        emp = engine.employee(k)
        for r in remind.due(emp["workspace"]):
            targets = to_people(emp, r["to"]) if r["to"] != "me" else to_people(emp, "supervisor")
            if r.get("agent"):
                run_async(k, "Scheduled follow-up %s (you set it): %s\nDo it now. Your output is sent to %s; "
                          "reply SILENT if nothing needs saying." % (r["id"], r["text"], r["to"]),
                          "followup", None, targets)
            else:
                for c in targets:
                    send(c, "Reminder: " + r["text"], emp)


def tick_bus():
    st = jload(team.STATEF, {})
    done = set(st.get("bus_done", []))
    rows = team.tail(team.BUS, 2000)
    group = team.group_id()
    emps = team.active()
    reg = engine.registry()
    for r in rows:
        if r.get("id") in done:
            continue
        done.add(r["id"])
        if r.get("from") not in emps:                     # only employees write the bus
            continue
        frm = emps[r["from"]]["name"]
        if r["kind"] == "post":
            team.feed(r["from"], frm, "team", r["text"], "bus")
            for c in ([group] if group else list(reg.get("owners", {}).keys())):
                send(c, r["text"], engine.employee(r["from"]))
            continue
        if r.get("to") not in emps:
            continue
        team.feed(r["from"], frm, r["to"], r["text"], "bus")
        if not (abilities.has(r["to"], "team_room") and abilities.has(r["from"], "team_room")):
            log("bus %s: %s → %s skipped (team room off)" % (r["id"], r["from"], r["to"]))
            continue
        if group:
            send(group, "%s → %s: %s" % (frm, emps[r["to"]]["name"], r["text"][:600]))
        target = engine.employee(r["to"])
        if r["kind"] == "ask":
            prompt = ("[Message from your colleague %s via the team bus]\n%s\n\nAnswer them directly and "
                      "completely (your final output goes back to %s, not to an owner). If it's outside your "
                      "scope, say who should take it." % (frm, r["text"], frm))
            bus_answer(target, prompt, r)
        elif r["kind"] == "answer":
            prompt = ("[Answer from your colleague %s via the team bus]\n%s\n\nContinue the work this was for. "
                      "Your final output goes to your supervisor; reply SILENT if nothing needs saying yet." % (frm, r["text"]))
            run_async(target["id"], prompt, "bus", None, to_people(target, "supervisor"),
                      extra_env={"STAFF_THREAD": r.get("thread", ""), "STAFF_HOPS": str(r.get("hops", 0))})
    st["bus_done"] = list(done)[-5000:]
    jsave(team.STATEF, st)


def bus_answer(target, prompt, r):
    def write(out):
        team.append(team.BUS, {"id": "%x" % int(time.time() * 1e6), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "kind": "answer", "from": target["id"], "to": r["from"], "text": out[:4000],
                               "thread": r.get("thread", ""), "hops": r.get("hops", 0)})
    run_async(target["id"], prompt, "bus", None, [], on_done=write,
              extra_env={"STAFF_THREAD": r.get("thread", ""), "STAFF_HOPS": str(r.get("hops", 0))})


# ------------------------------------------------------------------ main loop
def main():
    os.makedirs(team.TEAM, exist_ok=True)
    log("staffd up (pid %d)" % os.getpid())
    try:
        import panel
        threading.Thread(target=panel.serve, daemon=True).start()
    except Exception:  # noqa: BLE001
        log("panel failed to start: %s" % traceback.format_exc()[-400:])
    offsets = jload(os.path.join(team.TEAM, "offsets.json"), {})
    last = {}
    while True:
        with open(os.path.join(team.TEAM, "staffd_alive"), "w") as fh:
            fh.write(str(int(time.time())))
        for name, fn, every in (("jobs", tick_jobs, 60), ("reminders", tick_reminders, 60), ("bus", tick_bus, 10)):
            if time.time() - last.get(name, 0) >= every:
                last[name] = time.time()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log("%s error: %s" % (name, traceback.format_exc()[-400:]))
        tok = team.bot_token()
        if not tok:
            time.sleep(10)
            continue
        key = tok.split(":")[0]
        res = api(tok, "getUpdates", {"offset": offsets.get(key, 0), "timeout": 20, "allowed_updates": ["message"]}, timeout=40)
        for u in res.get("result", []) if res.get("ok") else []:
            offsets[key] = u["update_id"] + 1
            jsave(os.path.join(team.TEAM, "offsets.json"), offsets)
            if "message" in u:
                try:
                    handle(tok, u["message"])
                except Exception:  # noqa: BLE001
                    log("handle error: %s" % traceback.format_exc()[-400:])
        if not res.get("ok"):
            time.sleep(5)


if __name__ == "__main__":
    main()
