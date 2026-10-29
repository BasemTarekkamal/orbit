#!/usr/bin/env python3
"""staffd: runs the whole team. One launchd service (`staff start`); reads ~/Staff/staff.json every
loop, so a new hire is live within a minute with no restart. Harness-owned.

Each loop (about every second):
  * Chat channels (core/channels/: Telegram, Slack, Discord), each through your own bot, one listener
    thread per channel you connected:
      private chat: "/sara <msg>" (Telegram) or "@sara <msg>" talks to Sara and makes her your
             default; "talk sara"; "team" / "help"; plain text goes to your current default; voice
             notes transcribed on this Mac; photos and files saved into the employee's folder; long
             recordings → meeting minutes.
      team chat (staff.json team_chats): mention "@sara" / "Sara" or reply to her.
      Owners only. Anyone else is ignored (and listed in the control panel for the owner to approve).
  * The team bus (team/bus.jsonl): colleagues asking and answering each other, mirrored to the team room.
  * Routines (brief, standup, end of day, self-improvement, self-test) and reminders, per abilities.
  * New skills, mirrored to the team room.
  * The control panel on http://127.0.0.1:<port> (core/panel.py), in a thread.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(CORE, "tools"))
import abilities  # noqa: E402
import channels  # noqa: E402
import engine  # noqa: E402
import skillbook  # noqa: E402
import team  # noqa: E402
from team import jload, jsave, log, run_async, send, to_people  # noqa: E402

PENDING = os.path.join(team.TEAM, "pending_owners.json")
INBOX = queue.Queue()            # messages from every channel's listener thread
STOP = threading.Event()
LISTENERS = {}                   # channel → (thread, started at)


def note_stranger(msg):
    """Someone who isn't an owner messaged a bot: list them for the owner, never reply."""
    if msg.get("is_group") or not msg.get("sender"):
        return
    pend = jload(PENDING, {})
    pend[msg["sender"]] = {"name": (msg.get("sender_name") or "")[:60], "username": msg.get("username"),
                           "channel": msg.get("channel"), "at": time.strftime("%Y-%m-%d %H:%M")}
    jsave(PENDING, dict(list(pend.items())[-20:]))


def pick_employee(text, sticky, reply_name=None):
    emps = team.active()
    m = re.match(r"^[/@]([a-z0-9-]+)(?:@\w+)?[:,]?\s*(.*)$", text.strip(), re.S)
    if m and m.group(1).lower() in emps:
        return m.group(1).lower(), m.group(2).strip()
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


def help_text(mod):
    reg = engine.registry()
    lines = ["%s — talk to someone with %s <message>:" % (reg.get("team_name", "Your team"), mod.mention("<handle>"))]
    for k, e in team.active().items():
        lines.append("%s — %s, %s" % (mod.mention(k), e["name"], e["role"]))
    lines.append("talk <handle> — make them your default")
    return "\n".join(lines) if len(lines) > 2 else "Nobody works here yet. Hire someone in the control panel."


def try_pair(msg) -> bool:
    """The control panel's one-time code (team/pairing.json), sent to the bot in a private chat (Telegram's
    "Open in Telegram" link sends "/start <code>"), links that chat to the owner who asked for it. A wrong
    code counts against the code; five wrong tries and it's void."""
    p = jload(team.PAIRING, {})
    if not p.get("code") or p.get("paired_at") or msg.get("is_group") or time.time() > p.get("expires", 0):
        return False
    m = re.fullmatch(r"(?:/start\s+)?(\d{3})[\s-]?(\d{3})", (msg.get("text") or "").strip())
    if not m:
        return False
    if m.group(1) + m.group(2) != p["code"]:
        p["tries"] = p.get("tries", 0) + 1
        if p["tries"] >= 5:
            p["code"] = None
            log("pairing code voided after 5 wrong tries")
        jsave(team.PAIRING, p)
        return False
    import hire
    reg = engine.registry()
    owners = reg.setdefault("owners", {})
    sender, chat = channels.norm(msg["sender"]), channels.norm(msg["chat"])
    key = engine.owner_key(sender)
    want = p.get("owner") if p.get("owner") in owners else None
    if key:
        pass                                              # already theirs: nothing to add
    elif want and not owners[want].get("local"):
        owners[want].setdefault("addresses", []).append(sender)   # an owner adds another channel
        key = want
    else:                                                 # the first pairing: the owner set up in the browser
        local = want or next((k for k, o in owners.items() if o.get("local")), None)
        if local:
            reg["owners"] = {(sender if k == local else k): ({k2: v2 for k2, v2 in o.items() if k2 != "local"} if k == local else o)
                             for k, o in owners.items()}
        else:
            reg["owners"][sender] = {"name": (msg.get("sender_name") or "Owner")[:40], "aliases": []}
        key = sender
    engine.save_registry(reg, "paired %s on %s" % (reg["owners"][key]["name"], msg["channel"]))
    hire.directory(reg)
    p.update({"code": None, "paired_at": time.strftime("%Y-%m-%d %H:%M:%S"), "who": reg["owners"][key]["name"], "chat": chat})
    jsave(team.PAIRING, p)
    team.remember_dm(chat, key)
    emps = team.active()
    mod = channels.get(msg["channel"])
    first = next(iter(emps), None)
    hello = ("Connected. Hi %s: this is your team's chat. Just type (or send a voice note) and %s answers here." %
             (reg["owners"][key]["name"], emps[first]["name"])) if len(emps) == 1 else \
        "Connected. Hi %s: this is your team's chat.\n\n%s" % (reg["owners"][key]["name"], help_text(mod))
    send(chat, hello)
    return True


def handle(msg):
    if try_pair(msg):
        return
    reg = engine.registry()
    key = engine.owner_key(msg.get("sender"))
    if not key:
        note_stranger(msg)
        return
    who = reg["owners"][key]["name"]
    ch = msg["channel"]
    mod = channels.get(ch)
    chat = channels.norm(msg["chat"])
    cid = channels.parse(chat)[1]
    is_group = bool(msg.get("is_group"))
    if is_group and chat not in team.team_addrs():
        log("message from an unregistered %s chat %s (%s); `staff group %s --channel %s` to make it the team chat"
            % (ch, cid, msg.get("chat_title"), cid, ch))
        return
    if not is_group:
        team.remember_dm(chat, key)
    st = jload(team.STATEF, {})
    sticky_key = "sticky:%s" % (chat if is_group else key)
    text = (msg.get("text") or "").strip()
    reply_name = None
    rt = msg.get("reply_to_text") or ""
    if rt and ":" in rt[:40]:
        reply_name = rt.split(":", 1)[0].strip()
    low = text.lower()

    if low in ("/team", "/start", "/help", "help", "team"):
        send(chat, help_text(mod))
        return
    m = re.fullmatch(r"/?talk\s+@?([a-z0-9-]+)", low)
    if m and m.group(1) in team.active():
        st[sticky_key] = m.group(1)
        jsave(team.STATEF, st)
        send(chat, "Now talking to %s. Switch any time with: talk <handle>." % engine.employee(m.group(1))["name"])
        return

    emp_id, body = pick_employee(text, st.get(sticky_key), reply_name)
    if is_group:
        mentioned = any(re.search(r"(^|\W)@?%s(\W|$)" % re.escape(k), low) or e["name"].lower() in low
                        for k, e in team.active().items()) or reply_name or text.startswith("/")
        if not mentioned:
            return                                        # owners talking to each other: stay out
    if not emp_id:
        send(chat, "Who should take this? " + " · ".join("%s (%s)" % (mod.mention(k), e["role"]) for k, e in team.active().items()))
        return
    if not is_group:
        st[sticky_key] = emp_id
        jsave(team.STATEF, st)
    emp = engine.employee(emp_id)
    if not abilities.has(emp_id, "telegram"):
        send(chat, "%s's owner chat is switched off. Turn it on in the control panel (Abilities), or message them in "
                   "the team room there." % emp["name"])
        return

    def off(ability, what):
        if abilities.has(emp_id, ability):
            return False
        send(chat, "%s can't take %s: it's switched off in the control panel (Abilities)." % (emp["name"], what), emp)
        return True
    env_ws = dict(os.environ, STAFF_WORKSPACE=emp["workspace"], STAFF_EMPLOYEE=emp_id, STAFFROOM_HOME=engine.HOME)
    inbox = os.path.join(emp["workspace"], "state", "inbox")
    atts = msg.get("attachments") or []
    media = next((a for a in atts if a["kind"] in ("voice", "audio", "video", "video_note")), None)
    files = [a for a in atts if a["kind"] in ("photo", "file")]
    av_doc = next((a for a in files if str(a.get("mime", "")).startswith(("audio/", "video/"))), None)
    rec = media or av_doc
    if rec and (rec.get("duration", 0) >= 180 or rec["kind"] == "video" or av_doc is rec
                or re.search(r"meeting|minutes|اجتماع|محضر", low)):
        if off("meetings", "meeting recordings"):
            return
        if ch == "telegram" and rec.get("size", 0) > 20 * 1024 * 1024:
            send(chat, "That's over Telegram's 20 MB bot limit: drop it in %s/state/meetings_in on the Mac." % emp["workspace"], emp)
            return
        p = mod.download(rec, inbox, rec.get("name") or "meeting.ogg")
        if not p:
            send(chat, "I couldn't download that recording. Please send it again.", emp)
            return
        send(chat, "Got the recording. Transcribing on the Mac; minutes shortly.", emp)

        def meet():
            r = subprocess.run([sys.executable, os.path.join(CORE, "tools", "meeting.py"), p, "--title", body or "meeting"],
                               capture_output=True, text=True, env=env_ws, timeout=7200)
            try:
                info = json.loads(r.stdout.strip().splitlines()[-1])
                minutes(emp_id, info, who, body or "meeting")
            except Exception as e:  # noqa: BLE001
                send(chat, "I couldn't transcribe that recording (%s)." % e, emp)
        threading.Thread(target=meet, daemon=True).start()
        return
    if media and off("voice", "voice notes"):
        return
    if files and not media and off("files", "photos and files"):
        return
    extra = ""
    if media:
        p = mod.download(media, inbox, media.get("name") or "voice.ogg")
        if not p:
            send(chat, "I couldn't download that voice note. Please type it.", emp)
            return
        r = subprocess.run([sys.executable, os.path.join(CORE, "tools", "transcribe.py"), p],
                           capture_output=True, text=True, timeout=600)
        said = r.stdout.strip()
        if not said:
            send(chat, "I couldn't transcribe that voice note (%s). Please type it." % (r.stderr.strip()[-120:] or "no speech found"), emp)
            return
        body = "[voice note, transcribed on the Mac; confirm any number before acting]\n%s\n%s" % (said, body)
    saved = []
    for a in files:
        p = mod.download(a, inbox, a.get("name") or ("photo.jpg" if a["kind"] == "photo" else "file"))
        if p:
            saved.append(p)
    if saved:
        extra = "Attached %s saved at: %s (Read %s)." % ("file" if len(saved) == 1 else "files", ", ".join(saved),
                                                        "it" if len(saved) == 1 else "them")
    try:
        mod.typing(cid)
    except Exception:  # noqa: BLE001
        pass
    where = "the team chat" if is_group else "a private chat"
    on_done = None
    if is_group:                                          # the team chat is the team room too
        team.feed(who, who, emp_id, body, "group")
        on_done = team.to_room(emp_id, emp["name"], who, "group")
    run_async(emp_id, team.chat_prompt(who, where, body, extra), "chat",
              session_key=("group" if is_group else key), deliver_to=[chat], who=who, on_done=on_done, said=body,
              channel="group" if is_group else ch)


def minutes(emp_id, info, who, title):
    prompt = ("An owner ({who}) had a meeting; it was transcribed on the Mac to {t} ({m} min). Write {mn} in the "
              "meeting's main language: summary, decisions, action items (owner, due; set a reminder with "
              "staff-remind for each dated one), items in your scope, open questions, 'My view:' (2–4 honest "
              "points). Flag numbers and names you rely on as (check). Then reply with a ≤ 15-line version for "
              "chat. Title: {title}").format(who=who, t=info["transcript"], m=info.get("duration_min"),
                                             mn=info["minutes"], title=title)
    run_async(emp_id, prompt, "minutes", None, to_people(engine.employee(emp_id), "all"))


# ------------------------------------------------------------------ routines, reminders, bus, skills
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
    rooms = sorted(team.team_addrs())
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
            for c in (rooms or to_people(engine.employee(r["from"]), "all")):
                send(c, r["text"], engine.employee(r["from"]))
            continue
        if r.get("to") not in emps:
            continue
        team.feed(r["from"], frm, r["to"], r["text"], "bus")
        if not (abilities.has(r["to"], "team_room") and abilities.has(r["from"], "team_room")):
            log("bus %s: %s → %s skipped (team room off)" % (r["id"], r["from"], r["to"]))
            continue
        for c in rooms:
            send(c, "%s → %s: %s" % (frm, emps[r["to"]]["name"], r["text"][:600]))
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


def tick_skills():
    """New skills (learned, taught, shared, dropped) show up in the team room."""
    st = jload(team.STATEF, {})
    done = set(st.get("skills_done", []))
    emps = engine.registry().get("employees", {})
    new = False
    for r in team.tail(skillbook.LOG, 500):
        if r.get("id") in done:
            continue
        done.add(r["id"])
        new = True
        e = emps.get(r.get("emp"), {})
        what = skillbook.HOW.get(r.get("what"), r.get("what", ""))
        if r.get("what") in ("taught", "panel") and r.get("by"):
            what += " by %s" % r["by"]
        note = (": " + r["note"]) if r.get("note") else ""
        team.feed(r.get("emp"), e.get("name", r.get("emp")), "team", "%s, %s%s" % (what, r.get("name"), note), "skill")
    if new:
        st["skills_done"] = list(done)[-2000:]
        jsave(team.STATEF, st)


def bus_answer(target, prompt, r):
    def write(out):
        team.append(team.BUS, {"id": "%x" % int(time.time() * 1e6), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "kind": "answer", "from": target["id"], "to": r["from"], "text": out[:4000],
                               "thread": r.get("thread", ""), "hops": r.get("hops", 0)})
    run_async(target["id"], prompt, "bus", None, [], on_done=write,
              extra_env={"STAFF_THREAD": r.get("thread", ""), "STAFF_HOPS": str(r.get("hops", 0))})


# ------------------------------------------------------------------ main loop
def supervise():
    """One listener thread per connected channel; a dead one is restarted after 10 seconds."""
    now = time.time()
    for n in channels.configured():
        th, since = LISTENERS.get(n, (None, 0))
        if (th and th.is_alive()) or now - since < 10:
            continue

        def run(n=n):
            try:
                channels.get(n).listen(INBOX.put, log, STOP)
                log("%s listener stopped" % n)
            except Exception:  # noqa: BLE001
                log("%s listener died: %s" % (n, traceback.format_exc()[-400:]))
        th = threading.Thread(target=run, daemon=True, name="listen-" + n)
        th.start()
        LISTENERS[n] = (th, now)
        log("listening on %s" % n)


def main():
    os.makedirs(team.TEAM, exist_ok=True)
    log("staffd up (pid %d)" % os.getpid())
    try:
        import panel
        threading.Thread(target=panel.serve, daemon=True).start()
    except Exception:  # noqa: BLE001
        log("panel failed to start: %s" % traceback.format_exc()[-400:])
    last = {}
    while True:
        with open(os.path.join(team.TEAM, "staffd_alive"), "w") as fh:
            fh.write(str(int(time.time())))
        for name, fn, every in (("jobs", tick_jobs, 60), ("reminders", tick_reminders, 60), ("bus", tick_bus, 10),
                                ("skills", tick_skills, 30)):
            if time.time() - last.get(name, 0) >= every:
                last[name] = time.time()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log("%s error: %s" % (name, traceback.format_exc()[-400:]))
        try:
            supervise()
        except Exception:  # noqa: BLE001
            log("listener error: %s" % traceback.format_exc()[-400:])
        try:
            msg = INBOX.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            handle(msg)
        except Exception:  # noqa: BLE001
            log("handle error: %s" % traceback.format_exc()[-400:])


if __name__ == "__main__":
    main()
