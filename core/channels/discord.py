"""Discord, through your own bot (discord.com/developers): the Gateway websocket for receiving, REST for
everything else; needs no public address. Secret: ~/Staff/.secrets/discord_bot_token. Listening needs the
`websocket-client` package (`pip3 install --user websocket-client`); everything else is the standard library.
"""
from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import engine

NAME, LIMIT = "discord", 1900
API = "https://discord.com/api/v10"
UA = "Staffroom (https://github.com, 0.1)"
BACKOFF = 5                                               # seconds between gateway connections
INTENTS = 1 | 512 | 4096 | 32768                          # GUILDS, GUILD_MESSAGES, DIRECT_MESSAGES, MESSAGE_CONTENT
VOICE_MESSAGE = 1 << 13                                   # message flag: a recorded voice message
FATAL = {4004: "the bot token was rejected: `orbit secret discord`", 4010: "invalid shard", 4011: "sharding required",
         4012: "invalid gateway version", 4013: "invalid intents",
         4014: "Message Content Intent is off: enable it under Bot → Privileged Gateway Intents"}
_dms = {}                                                 # user id → private channel id


def token():
    return engine.secret("discord_bot_token")


def _http(url, data=None, headers=None, timeout=20):
    """One HTTP request (POST when data is given, else GET) → (status, body bytes, headers). Everything the
    adapter sends goes through here, so tests can stand in for it."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def rest(path, body=None, data=None, ctype=None, timeout=20):
    """One REST call → (status, parsed JSON or {}): a GET, or a POST with a JSON body or raw data of type ctype.
    Status 0 means the request itself failed."""
    h = {"Authorization": "Bot %s" % token(), "User-Agent": UA}
    if body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    try:
        status, raw, _ = _http(API + path, data, h, timeout)
    except Exception as e:  # noqa: BLE001
        return 0, {"message": str(e)}
    try:
        return status, json.loads(raw.decode() or "{}")
    except ValueError:
        return status, {}


def check():
    if not token():
        return False, "no bot token: `orbit secret discord`"
    s, d = rest("/users/@me")
    return (True, d.get("username", "?")) if s == 200 else (False, d.get("message") or "HTTP %s" % s)


def mention(handle) -> str:
    return "@" + handle


def clean(text, me=None) -> str:
    """<@123> and <@!123> → @123 (a mention of our own bot is dropped), <#123> → #123."""
    t = re.sub(r"<@!?(\d+)>", lambda m: "" if m.group(1) == me else "@" + m.group(1), text or "")
    t = re.sub(r"<#(\d+)>", r"#\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def normalize(d, me=None):
    """A MESSAGE_CREATE event → the message dict; None for bots (us included). A DM has no guild_id."""
    a = d.get("author") or {}
    if a.get("bot") or not a.get("id"):
        return None
    voice = bool(int(d.get("flags") or 0) & VOICE_MESSAGE)
    atts = []
    for f in d.get("attachments") or []:
        mime = f.get("content_type") or ""
        kind = ("voice" if voice else "audio" if mime.startswith("audio/") else "photo" if mime.startswith("image/")
                else "video" if mime.startswith("video/") else "file")
        atts.append({"kind": kind, "name": f.get("filename") or kind, "mime": mime, "size": f.get("size", 0),
                     "duration": f.get("duration_secs") or 0, "ref": {"url": f.get("url"), "name": f.get("filename")}})
    group = bool(d.get("guild_id"))
    return {"channel": NAME, "sender": "discord:%s" % a["id"], "sender_name": (a.get("global_name") or a.get("username") or "")[:60],
            "username": a.get("username"), "chat": "discord:%s" % d.get("channel_id"), "is_group": group,
            "chat_title": d.get("channel_id") if group else None, "text": clean(d.get("content"), me),
            "reply_to_text": (d.get("referenced_message") or {}).get("content") or "", "attachments": atts}


def session(ws, tok, st, resume, put, say, stop, gone):
    """One gateway connection: HELLO → IDENTIFY (or RESUME), heartbeats in a thread, then events until Discord
    closes or asks us to reconnect. Returns the seconds to wait before the next connection; `st` carries the
    session (id, last sequence, resume URL, our user id) across connections."""
    import websocket
    beat = {"every": 41.25, "acked": True}

    def heartbeat():
        delay = beat["every"] * random.random()           # Discord asks for a random first delay
        while not gone.wait(delay):
            if not beat["acked"]:                         # no ack since the last beat: a zombie, drop it and resume
                ws.shutdown()
                return
            beat["acked"] = False
            try:
                ws.send(json.dumps({"op": 1, "d": st["seq"]}))
            except Exception:  # noqa: BLE001
                return
            delay = beat["every"]

    while not stop.is_set():
        try:
            opcode, raw = ws.recv_data()
        except websocket.WebSocketTimeoutException:
            continue
        if opcode == 8:                                   # a close frame: 2-byte code, then the reason
            code = struct.unpack(">H", raw[:2])[0] if len(raw) >= 2 else 0
            if code in FATAL:
                st["session"] = None
                say("closed (%d): %s" % (code, FATAL[code]))
                return BACKOFF * 12
            if code in (4007, 4009):                      # bad sequence / session timed out: identify afresh
                st["session"] = None
            say("closed (%d); reconnecting" % code)
            return BACKOFF
        if opcode not in (1, 2):
            continue
        ev = json.loads(raw)
        op, d, t = ev.get("op"), ev.get("d"), ev.get("t")
        if ev.get("s") is not None:
            st["seq"] = ev["s"]
        if op == 10:                                      # HELLO
            beat["every"] = d["heartbeat_interval"] / 1000.0
            threading.Thread(target=heartbeat, daemon=True, name="discord-heartbeat").start()
            if resume:
                ws.send(json.dumps({"op": 6, "d": {"token": tok, "session_id": st["session"], "seq": st["seq"]}}))
            else:
                ws.send(json.dumps({"op": 2, "d": {"token": tok, "intents": INTENTS,
                                                   "properties": {"os": "staffroom", "browser": "staffroom", "device": "staffroom"}}}))
        elif op == 1:                                     # Discord wants a heartbeat now
            ws.send(json.dumps({"op": 1, "d": st["seq"]}))
        elif op == 11:                                    # heartbeat ack
            beat["acked"] = True
        elif op == 7:                                     # RECONNECT: close, then resume
            return BACKOFF
        elif op == 9:                                     # INVALID_SESSION: d says whether it can be resumed
            if not d:
                st["session"] = None
            return BACKOFF
        elif op == 0 and t == "READY":
            st["me"], st["session"], st["resume_url"] = d["user"]["id"], d["session_id"], d.get("resume_gateway_url")
        elif op == 0 and t == "MESSAGE_CREATE":
            msg = normalize(d, st["me"])
            if msg:
                put(msg)
    return 0


def listen(put, log, stop):
    """Connects to the gateway (GET /gateway/bot) and identifies; after a drop, resumes the same session at the
    resume URL when Discord allows it, else identifies again. Never logs the token."""
    import websocket                                      # only the listener needs it
    tok, st, last = token(), {"me": None, "session": None, "seq": None, "resume_url": None}, [None]

    def say(msg):                                         # the same trouble is logged once, not every 5 seconds
        if msg != last[0]:
            log("discord: " + msg)
            last[0] = msg

    wait = 0
    while not stop.wait(wait):
        wait = BACKOFF
        resume = bool(st["session"] and st["resume_url"])
        url = st["resume_url"]
        if not resume:
            s, d = rest("/gateway/bot")
            if s != 200:
                say("can't reach the gateway: %s" % (d.get("message") or "HTTP %s" % s))
                continue
            url = d["url"]
        try:
            ws = websocket.create_connection(url.rstrip("/") + "/?v=10&encoding=json", timeout=30)
        except Exception as e:  # noqa: BLE001
            say("connect failed: %s" % e)
            continue
        gone = threading.Event()                          # ends this connection's heartbeat thread
        try:
            wait = session(ws, tok, st, resume, put, say, stop, gone)
        except Exception as e:  # noqa: BLE001
            say("%s; reconnecting" % e)
        finally:
            gone.set()
            ws.close()
            ws.shutdown()                                 # close() is a no-op once Discord has closed its side


def send(chat_id, text) -> bool:
    """Posts to the channel; one retry after a 429, waiting as long as Discord says."""
    for _ in range(2):
        s, d = rest("/channels/%s/messages" % chat_id, {"content": text})
        if s != 429:
            return 200 <= s < 300
        time.sleep(min(float(d.get("retry_after") or 1), 30))
    return False


def multipart(parts):
    """A multipart/form-data body by hand: parts are (field, filename or None, data, mime or None).
    Returns (body, Content-Type)."""
    b = "staffroom" + uuid.uuid4().hex
    out = []
    for field, fn, data, mime in parts:
        head = 'Content-Disposition: form-data; name="%s"' % field + ('; filename="%s"' % fn.replace('"', "'") if fn else "")
        head += ("\r\nContent-Type: " + mime) if mime else ""
        out += [("--%s\r\n%s\r\n\r\n" % (b, head)).encode(), data if isinstance(data, bytes) else data.encode(), b"\r\n"]
    out.append(("--%s--\r\n" % b).encode())
    return b"".join(out), "multipart/form-data; boundary=" + b


def send_file(chat_id, path, caption="") -> bool:
    name = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    payload = json.dumps({"content": caption[:LIMIT], "attachments": [{"id": 0, "filename": name}]})
    body, ctype = multipart([("payload_json", None, payload, "application/json"),
                             ("files[0]", name, data, mimetypes.guess_type(path)[0] or "application/octet-stream")])
    s, _ = rest("/channels/%s/messages" % chat_id, data=body, ctype=ctype, timeout=120)
    return 200 <= s < 300


def typing(chat_id) -> None:
    rest("/channels/%s/typing" % chat_id, data=b"", timeout=10)


def dm_chat(user_id):
    uid = str(user_id)
    if uid not in _dms:
        s, d = rest("/users/@me/channels", {"recipient_id": uid})
        if s != 200 or not d.get("id"):
            return None
        _dms[uid] = str(d["id"])
    return _dms[uid]


def download(att, dest_dir, name):
    """Saves an attachment from Discord's CDN (its links carry their own signature; no token) → the path, or None."""
    url = (att.get("ref") or {}).get("url")
    if not url:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] if not os.path.splitext(name)[1] else ""
    dst = os.path.join(dest_dir, "%s-%s%s" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^\w.-]", "", name)[:30] or "file", ext))
    try:
        status, body, _ = _http(url, None, {"User-Agent": UA}, timeout=120)
    except Exception:  # noqa: BLE001
        return None
    if status != 200:
        return None
    with open(dst, "wb") as out:
        out.write(body)
    return dst
