"""Telegram, through your own bot (@BotFather). Long-polls getUpdates; needs no public address.
Secret: ~/Staff/.secrets/telegram_bot_token. The reference adapter: see channels/__init__.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

import engine

NAME, LIMIT = "telegram", 3900
API = "https://api.telegram.org/bot%s/%s"


def token():
    return engine.secret("telegram_bot_token")


def api(tok, method, params=None, timeout=60):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                   for k, v in (params or {}).items()}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(API % (tok, method), data=data), timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "description": str(e)}


def check():
    r = api(token(), "getMe")
    return (True, "@%s" % r["result"]["username"]) if r.get("ok") else (False, r.get("description", "no answer"))


def mention(handle) -> str:
    return "/" + handle


def normalize(msg) -> dict:
    chat, frm = msg.get("chat", {}), msg.get("from", {})
    atts = []
    for kind in ("voice", "audio", "video", "video_note"):
        f = msg.get(kind)
        if f:
            atts.append({"kind": kind, "name": f.get("file_name") or kind + (".ogg" if kind == "voice" else ".mp4"),
                         "mime": f.get("mime_type", ""), "size": f.get("file_size", 0), "duration": f.get("duration", 0),
                         "ref": f["file_id"]})
    if msg.get("photo"):
        p = msg["photo"][-1]
        atts.append({"kind": "photo", "name": "photo.jpg", "mime": "image/jpeg", "size": p.get("file_size", 0), "duration": 0,
                     "ref": p["file_id"]})
    doc = msg.get("document")
    if doc:
        atts.append({"kind": "file", "name": doc.get("file_name", "file"), "mime": doc.get("mime_type", ""),
                     "size": doc.get("file_size", 0), "duration": 0, "ref": doc["file_id"]})
    return {"channel": NAME, "sender": "telegram:%s" % frm.get("id", ""),
            "sender_name": " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x)[:60],
            "username": frm.get("username"), "chat": "telegram:%s" % chat.get("id"),
            "is_group": chat.get("type") in ("group", "supergroup"), "chat_title": chat.get("title"),
            "text": (msg.get("text") or msg.get("caption") or "").strip(),
            "reply_to_text": (msg.get("reply_to_message") or {}).get("text", ""), "attachments": atts}


def listen(put, log, stop):
    tok = token()
    offsets_f = os.path.join(engine.HOME, "team", "offsets.json")
    try:
        with open(offsets_f, encoding="utf-8") as fh:
            offsets = json.load(fh)
    except (OSError, ValueError):
        offsets = {}
    key = tok.split(":")[0]
    while not stop.is_set():
        res = api(tok, "getUpdates", {"offset": offsets.get(key, 0), "timeout": 20, "allowed_updates": ["message"]}, timeout=40)
        if not res.get("ok"):
            log("telegram: %s" % res.get("description"))
            time.sleep(5)
            continue
        for u in res.get("result", []):
            offsets[key] = u["update_id"] + 1
            os.makedirs(os.path.dirname(offsets_f), exist_ok=True)
            with open(offsets_f, "w", encoding="utf-8") as fh:
                json.dump(offsets, fh)
            if "message" in u:
                put(normalize(u["message"]))


def send(chat_id, text) -> bool:
    return bool(api(token(), "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).get("ok"))


def send_file(chat_id, path, caption="") -> bool:
    args = ["curl", "-s", "-F", "chat_id=%s" % chat_id, "-F", "document=@%s" % path]
    if caption:
        args += ["-F", "caption=%s" % caption[:1000]]
    r = subprocess.run(args + [API % (token(), "sendDocument")], capture_output=True, timeout=120)
    return r.returncode == 0


def typing(chat_id) -> None:
    api(token(), "sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)


def dm_chat(user_id):
    return str(user_id)                                    # a private chat's id is the user's id


def download(att, dest_dir, name):
    tok = token()
    info = api(tok, "getFile", {"file_id": att["ref"]})
    if not info.get("ok"):
        return None
    fp = info["result"]["file_path"]
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(fp)[1] if not os.path.splitext(name)[1] else ""
    dst = os.path.join(dest_dir, "%s-%s%s" % (time.strftime("%Y%m%dT%H%M%S"), re.sub(r"[^\w.-]", "", name)[:30] or "file", ext))
    with urllib.request.urlopen("https://api.telegram.org/file/bot%s/%s" % (tok, fp), timeout=120) as r, open(dst, "wb") as out:
        out.write(r.read())
    return dst
