"""Slack, through your own Slack app, in Socket Mode: the bot opens a websocket to Slack and events arrive over
it, so it needs no public address. Secrets: ~/Staff/.secrets/slack_bot_token (xoxb-…, the Bot User OAuth Token)
and slack_app_token (xapp-…, an app-level token with connections:write). Listening needs the `websocket-client`
package (`pip3 install --user websocket-client`); everything else is the standard library.
"""
from __future__ import annotations

import collections
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import engine

NAME, LIMIT = "slack", 3900
API = "https://slack.com/api/%s"
BACKOFF = 5                                               # seconds between reconnects
SUBTYPES = (None, "file_share", "thread_broadcast")       # the message subtypes that are a person talking
BAD_TOKEN = ("invalid_auth", "not_authed", "token_revoked", "account_inactive", "missing_scope")
_users = {}                                               # user id → (name, username), from users.info
_dms = {}                                                 # user id → private channel id, from conversations.open


def token():
    """The bot token, and only when the app token is saved too: Socket Mode needs both."""
    bot, app = engine.secret("slack_bot_token"), engine.secret("slack_app_token")
    return bot if bot and app else None


def _http(url, data=None, headers=None, timeout=20):
    """One HTTP request (POST when data is given, else GET) → (status, body bytes, headers). Everything the
    adapter sends goes through here, so tests can stand in for it."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def api(tok, method, params=None, form=False, timeout=20):
    """One Web API call → its parsed JSON ({"ok": False, "error": …} when the call itself fails). A JSON body,
    or a form body (form=True) for the methods that take nothing else: users.info, files.getUploadURLExternal,
    apps.connections.open."""
    h = {"Authorization": "Bearer %s" % tok}
    if form:
        data, h["Content-Type"] = urllib.parse.urlencode(params or {}).encode(), "application/x-www-form-urlencoded"
    else:
        data, h["Content-Type"] = json.dumps(params or {}).encode(), "application/json; charset=utf-8"
    try:
        return json.loads(_http(API % method, data, h, timeout)[1].decode())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def check():
    for name, prefix in (("slack_bot_token", "xoxb-"), ("slack_app_token", "xapp-")):
        if not engine.secret(name):
            return False, "no %s (%s…): `staff secret slack`" % (name.replace("_", " "), prefix)
    r = api(engine.secret("slack_bot_token"), "auth.test")
    return (True, "@%s in %s" % (r.get("user"), r.get("team"))) if r.get("ok") else (False, r.get("error", "no answer"))


def mention(handle) -> str:
    return "@" + handle


def clean(text, me=None) -> str:
    """Slack's message markup → plain text: <@U1> → @U1 (a mention of our own bot is dropped), <#C1|general> →
    #general, <!here> → @here, <https://x|label> and <https://x> → https://x, then the three escaped characters."""
    t = re.sub(r"<@([A-Z0-9]+)(?:\|[^>]*)?>", lambda m: "" if m.group(1) == me else "@" + m.group(1), text or "")
    t = re.sub(r"<#[A-Z0-9]+\|([^>]*)>", r"#\1", t)
    t = re.sub(r"<!([a-z]+)(?:\|[^>]*)?>", r"@\1", t)
    t = re.sub(r"<(?:mailto:)?([^|>]+@[^|>]+)(?:\|[^>]*)?>", r"\1", t)
    t = re.sub(r"<(https?://[^|>]+)(?:\|[^>]*)?>", r"\1", t)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def user_name(uid):
    """(display name, username) from users.info, cached per user; the id itself when Slack won't say."""
    if uid not in _users:
        u = api(token(), "users.info", {"user": uid}, form=True).get("user")
        if not u:
            return uid, None
        p = u.get("profile") or {}
        _users[uid] = ((p.get("display_name") or p.get("real_name") or u.get("real_name") or u.get("name") or uid)[:60],
                       u.get("name"))
    return _users[uid]


def normalize(ev, me=None):
    """A `message` event → the message dict; None for anything that isn't a person talking (bots, ourselves, edits,
    joins…). Slack never sends the replied-to text, so reply_to_text stays empty."""
    if ev.get("type") != "message" or ev.get("bot_id") or not ev.get("user") or ev.get("user") == me \
            or ev.get("subtype") not in SUBTYPES:
        return None
    atts = []
    for f in ev.get("files") or []:
        mime = f.get("mimetype") or ""
        kind = ("voice" if f.get("subtype") == "slack_audio" else "audio" if mime.startswith("audio/")
                else "photo" if mime.startswith("image/") else "video" if mime.startswith("video/") else "file")
        name = f.get("name") or f.get("title") or kind
        atts.append({"kind": kind, "name": name, "mime": mime, "size": f.get("size", 0),
                     "duration": int((f.get("duration_ms") or 0) / 1000),
                     "ref": {"url": f.get("url_private_download") or f.get("url_private"), "name": name}})
    name, username = user_name(ev["user"])
    dm = ev.get("channel_type") == "im"
    return {"channel": NAME, "sender": "slack:%s" % ev["user"], "sender_name": name, "username": username,
            "chat": "slack:%s" % ev.get("channel"), "is_group": not dm, "chat_title": None if dm else ev.get("channel"),
            "text": clean(ev.get("text"), me), "reply_to_text": "", "attachments": atts}


def listen(put, log, stop):
    """Socket Mode: apps.connections.open (with the app token) gives a one-use wss URL; envelopes arrive over it
    and each one is acked at once (Slack redelivers after 3 s without an ack). A `disconnect` envelope, a closed
    socket or any error means: open a fresh connection."""
    import websocket                                      # only the listener needs it
    app, me, last = engine.secret("slack_app_token"), None, [None]
    seen = collections.deque(maxlen=200)                  # event ids, so a redelivered envelope isn't handled twice

    def say(msg):                                         # the same trouble is logged once, not every 5 seconds
        if msg != last[0]:
            log("slack: " + msg)
            last[0] = msg

    while not stop.is_set():
        if not me:
            me = api(token(), "auth.test").get("user_id")  # our own user id, to skip our own messages and mentions
        r = api(app, "apps.connections.open", form=True)
        if not r.get("ok"):
            say("can't open Socket Mode: %s" % r.get("error"))
            stop.wait(BACKOFF * 12 if r.get("error") in BAD_TOKEN else BACKOFF)
            continue
        try:
            ws = websocket.create_connection(r["url"], timeout=30)
        except Exception as e:  # noqa: BLE001
            say("connect failed: %s" % e)
            stop.wait(BACKOFF)
            continue
        last[0] = None
        try:
            while not stop.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:                               # Slack closed the socket
                    break
                env = json.loads(raw)
                if env.get("envelope_id"):                # ack first, whatever it is
                    ws.send(json.dumps({"envelope_id": env["envelope_id"]}))
                if env.get("type") == "disconnect":       # Slack recycles connections now and then
                    break
                if env.get("type") != "events_api":
                    continue
                payload = env.get("payload") or {}
                eid = payload.get("event_id") or env["envelope_id"]
                if eid in seen:
                    continue
                seen.append(eid)
                msg = normalize(payload.get("event") or {}, me)
                if msg:
                    put(msg)
        except Exception as e:  # noqa: BLE001
            say("%s; reconnecting" % e)
            stop.wait(BACKOFF)
        finally:
            ws.close()
            ws.shutdown()                                 # close() is a no-op once Slack has closed its side


def send(chat_id, text) -> bool:
    return bool(api(token(), "chat.postMessage", {"channel": chat_id, "text": text, "unfurl_links": False}).get("ok"))


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
    """The three-step upload: get an upload URL, POST the bytes to it, complete the upload into the channel."""
    tok, name = token(), os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        r = api(tok, "files.getUploadURLExternal", {"filename": name, "length": len(data)}, form=True)
        if not r.get("ok"):
            return False
        body, ctype = multipart([("file", name, data, mimetypes.guess_type(path)[0] or "application/octet-stream")])
        if _http(r["upload_url"], body, {"Content-Type": ctype}, timeout=120)[0] != 200:
            return False
        done = {"files": [{"id": r["file_id"], "title": name}], "channel_id": chat_id}
        if caption:
            done["initial_comment"] = caption[:1000]
        return bool(api(tok, "files.completeUploadExternal", done).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def typing(chat_id) -> None:
    return None                                            # Slack has no typing indicator for bots


def dm_chat(user_id):
    uid = str(user_id)
    if uid not in _dms:
        r = api(token(), "conversations.open", {"users": uid})
        if not r.get("ok"):
            return None
        _dms[uid] = r["channel"]["id"]
    return _dms[uid]


def download(att, dest_dir, name):
    """Saves a file through its url_private_download link (bot token in the header) → the path, or None."""
    ref = att.get("ref") or {}
    url = ref.get("url")
    if not url:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(ref.get("name") or "")[1] if not os.path.splitext(name)[1] else ""
    dst = os.path.join(dest_dir, "%s-%s%s" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^\w.-]", "", name)[:30] or "file", ext))
    try:
        status, body, h = _http(url, None, {"Authorization": "Bearer %s" % token()}, timeout=120)
    except Exception:  # noqa: BLE001
        return None
    if status != 200 or (h.get("content-type", "").startswith("text/html") and not att.get("mime", "").startswith("text/html")):
        return None                                        # Slack answers an unauthorised download with its sign-in page
    with open(dst, "wb") as out:
        out.write(body)
    return dst
