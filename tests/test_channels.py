"""Channel adapter tests: Slack (Socket Mode) and Discord (Gateway), with fakes standing in for the network and
the websocket. Runs against a throwaway team folder; never makes a request.  python3 -m unittest tests.test_channels
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import types
import unittest

TMP = tempfile.mkdtemp(prefix="staffroom-channels-")
os.environ["STAFFROOM_HOME"] = TMP
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "core"))

import channels  # noqa: E402
import engine  # noqa: E402

BOT, APP, DISCORD = "xoxb-test-bot-token", "xapp-test-app-token", "discord-test-bot-token"
CONTRACT = ("NAME", "LIMIT", "token", "check", "listen", "send", "send_file", "typing", "dm_chat", "download", "mention")
MESSAGE_KEYS = {"channel", "sender", "sender_name", "username", "chat", "is_group", "chat_title", "text", "reply_to_text",
                "attachments"}


def secrets(**kv):
    shutil.rmtree(engine.SECRETS, ignore_errors=True)
    os.makedirs(engine.SECRETS)
    for k, v in kv.items():
        with open(os.path.join(engine.SECRETS, k), "w") as fh:
            fh.write(v + "\n")


class FakeHTTP:
    """Stands in for an adapter's _http: answers by a piece of the URL (first match wins), records every call.
    A route is a dict (200 + JSON), a tuple (status, body[, headers]) or a callable(url, data, headers) → either."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, data=None, headers=None, timeout=20):
        self.calls.append((url, data, headers or {}))
        for key, resp in self.routes.items():
            if key in url:
                if callable(resp):
                    resp = resp(url, data, headers or {})
                status, body, hdrs = (tuple(resp) + ({},))[:3] if isinstance(resp, tuple) else (200, resp, {})
                return status, (json.dumps(body).encode() if isinstance(body, (dict, list)) else body), hdrs
        raise AssertionError("unexpected request: " + url)

    def to(self, key):
        return [c for c in self.calls if key in c[0]]


class FakeSocket:
    """Plays a script: a dict is a frame from the server, "timeout" a socket timeout, ("after", text) waits until
    something we sent contains text (then times out), bytes are a close frame. When the script runs out it sets
    `stop` so the listener ends, and raises as a closed socket would."""
    def __init__(self, mod, script, stop, sent):
        self.mod, self.script, self.stop, self.sent, self.closed = mod, script, stop, sent, False

    def _next(self):
        while self.script:
            item = self.script.pop(0)
            if item == "timeout":
                raise self.mod.WebSocketTimeoutException("timed out")
            if isinstance(item, tuple):
                deadline = time.time() + 3
                while time.time() < deadline and not any(item[1] in s for s in self.sent):
                    time.sleep(0.005)
                raise self.mod.WebSocketTimeoutException("timed out")
            return item
        self.stop.set()
        raise self.mod.WebSocketConnectionClosedException("script over")

    def recv(self):
        return json.dumps(self._next())

    def recv_data(self):
        item = self._next()
        return (8, item) if isinstance(item, bytes) else (1, json.dumps(item).encode())

    def send(self, text):
        self.sent.append(text)

    def close(self):
        self.closed = True

    shutdown = close


def fake_websocket(script, stop, sent, opened):
    """A stand-in for the websocket-client module: create_connection hands out FakeSockets playing one shared script."""
    mod = types.ModuleType("websocket")
    mod.WebSocketException = type("WebSocketException", (Exception,), {})
    mod.WebSocketTimeoutException = type("WebSocketTimeoutException", (mod.WebSocketException,), {})
    mod.WebSocketConnectionClosedException = type("WebSocketConnectionClosedException", (mod.WebSocketException,), {})

    def create_connection(url, timeout=None, **kw):
        opened.append(url)
        return FakeSocket(mod, script, stop, sent)
    mod.create_connection = create_connection
    return mod


class Adapter:
    """Shared by both adapter test cases (a mixin, so unittest doesn't run it on its own)."""
    channel = ""

    def setUp(self):
        self.mod = channels.get(self.channel)
        self.mod._dms.clear()
        self.real_http, self.real_backoff = self.mod._http, self.mod.BACKOFF
        self.mod._http, self.mod.BACKOFF = FakeHTTP(self.routes()), 0
        self.http = self.mod._http
        self.saved_ws = sys.modules.get("websocket")

    def tearDown(self):
        self.mod._http, self.mod.BACKOFF = self.real_http, self.real_backoff
        if self.saved_ws is not None:
            sys.modules["websocket"] = self.saved_ws
        else:
            sys.modules.pop("websocket", None)

    def run_listen(self, script):
        """Runs listen() against the scripted socket until the script ends; → (messages put, frames sent, urls opened, log)."""
        stop, sent, opened, got, logs = threading.Event(), [], [], [], []
        sys.modules["websocket"] = fake_websocket(script, stop, sent, opened)
        th = threading.Thread(target=self.mod.listen, args=(got.append, logs.append, stop), daemon=True)
        th.start()
        th.join(10)
        self.assertFalse(th.is_alive(), "the listener did not stop")
        return got, sent, opened, logs

    def test_contract(self):
        for name in CONTRACT:
            self.assertTrue(hasattr(self.mod, name), name)
        self.assertEqual(self.mod.NAME, self.channel)
        self.assertEqual(self.mod.mention("sara"), "@sara")


class Slack(Adapter, unittest.TestCase):
    channel = "slack"

    def routes(self):
        return {
            "auth.test": {"ok": True, "user": "staffbot", "team": "Acme", "user_id": "UBOT"},
            "apps.connections.open": {"ok": True, "url": "wss://wss-primary.slack.com/link/?ticket=t1"},
            "users.info": {"ok": True, "user": {"id": "U777", "name": "alex", "real_name": "Alex Owner",
                                                "profile": {"display_name": "Alex"}}},
            "chat.postMessage": {"ok": True, "ts": "1.2"},
            "conversations.open": {"ok": True, "channel": {"id": "D999"}},
            "files.getUploadURLExternal": {"ok": True, "upload_url": "https://files.slack.com/upload/v1/abc", "file_id": "F1"},
            "files.slack.com/upload": (200, b"OK - 1"),
            "files.completeUploadExternal": {"ok": True},
            "files.slack.com/files-pri": (200, b"PNGDATA", {"content-type": "image/png"}),
        }

    def setUp(self):
        secrets(slack_bot_token=BOT, slack_app_token=APP)
        super().setUp()
        self.mod._users.clear()

    def test_token_needs_both_secrets(self):
        self.assertEqual(self.mod.token(), BOT)
        secrets(slack_bot_token=BOT)
        self.assertIsNone(self.mod.token())
        secrets(slack_app_token=APP)
        self.assertIsNone(self.mod.token())
        self.assertFalse(self.mod.check()[0])

    def test_check(self):
        self.assertEqual(self.mod.check(), (True, "@staffbot in Acme"))
        self.assertEqual(self.http.to("auth.test")[0][2]["Authorization"], "Bearer " + BOT)

    def test_listen_acks_normalizes_and_reconnects(self):
        def env(eid, event):
            return {"type": "events_api", "envelope_id": eid, "payload": {"event_id": "Ev" + eid, "event": event}}
        dm = {"type": "message", "channel": "D123", "user": "U777", "channel_type": "im", "ts": "1",
              "text": "Hey &lt;b&gt; &amp; <https://x.com|x> <@UBOT> @sara: check <https://y.com>"}
        share = {"type": "message", "subtype": "file_share", "channel": "C55", "user": "U777", "channel_type": "channel",
                 "text": "<@UBOT> look", "files": [
                     {"name": "shot.png", "mimetype": "image/png", "size": 10, "url_private_download": "https://files.slack.com/files-pri/1/shot.png"},
                     {"name": "audio.webm", "mimetype": "audio/webm", "subtype": "slack_audio", "duration_ms": 4200, "size": 5,
                      "url_private": "https://files.slack.com/files-pri/1/a.webm"},
                     {"name": "deck.pdf", "mimetype": "application/pdf", "size": 7, "url_private_download": "https://files.slack.com/files-pri/1/deck.pdf"}]}
        script = [{"type": "hello"}, "timeout", env("e1", dm),
                  env("e2", {"type": "message", "channel": "D123", "user": "UBOT", "bot_id": "B1", "channel_type": "im", "text": "me"}),
                  env("e3", {"type": "message", "subtype": "message_changed", "channel": "D123", "user": "U777", "channel_type": "im", "text": "x"}),
                  {"type": "disconnect", "reason": "refresh_requested"},
                  {"type": "hello"}, env("e4", share),
                  env("e1", dm)]                                      # a redelivery: same event id, not handled twice
        got, sent, opened, logs = self.run_listen(script)
        self.assertEqual([json.loads(s)["envelope_id"] for s in sent], ["e1", "e2", "e3", "e4", "e1"])   # every envelope acked
        self.assertEqual(opened, ["wss://wss-primary.slack.com/link/?ticket=t1"] * 2)                  # reconnected after disconnect
        self.assertEqual(len(self.http.to("apps.connections.open")), 2)
        self.assertEqual(self.http.to("apps.connections.open")[0][2]["Authorization"], "Bearer " + APP)
        self.assertEqual(self.http.to("auth.test")[0][2]["Authorization"], "Bearer " + BOT)
        self.assertEqual(len(got), 2)
        m = got[0]
        self.assertEqual(set(m), MESSAGE_KEYS)
        self.assertEqual((m["channel"], m["sender"], m["chat"], m["is_group"]), ("slack", "slack:U777", "slack:D123", False))
        self.assertEqual((m["sender_name"], m["username"], m["chat_title"], m["reply_to_text"]), ("Alex", "alex", None, ""))
        self.assertEqual(m["text"], "Hey <b> & https://x.com @sara: check https://y.com")
        self.assertEqual(m["attachments"], [])
        g = got[1]
        self.assertEqual((g["chat"], g["is_group"], g["chat_title"], g["text"]), ("slack:C55", True, "C55", "look"))
        self.assertEqual([a["kind"] for a in g["attachments"]], ["photo", "voice", "file"])
        self.assertEqual([a["name"] for a in g["attachments"]], ["shot.png", "audio.webm", "deck.pdf"])
        self.assertEqual([a["duration"] for a in g["attachments"]], [0, 4, 0])
        self.assertEqual(g["attachments"][1]["ref"], {"url": "https://files.slack.com/files-pri/1/a.webm", "name": "audio.webm"})
        self.assertEqual(g["attachments"][0]["mime"], "image/png")
        self.assertEqual(len(self.http.to("users.info")), 1)                                           # cached per user
        self.assertFalse(any(BOT in line or APP in line for line in logs), logs)

    def test_normalize_ignores_what_is_not_a_person(self):
        base = {"type": "message", "channel": "D1", "channel_type": "im", "text": "hi"}
        self.assertIsNone(self.mod.normalize({**base, "user": "UBOT"}, "UBOT"))
        self.assertIsNone(self.mod.normalize({**base, "user": "U1", "bot_id": "B1"}, "UBOT"))
        self.assertIsNone(self.mod.normalize({**base, "user": "U1", "subtype": "message_changed"}, "UBOT"))
        self.assertIsNone(self.mod.normalize({**base, "user": "U1", "subtype": "channel_join"}, "UBOT"))
        self.assertIsNone(self.mod.normalize({"type": "app_mention", "user": "U1", "channel": "C1", "text": "x"}, "UBOT"))
        self.assertIsNotNone(self.mod.normalize({**base, "user": "U1", "subtype": "thread_broadcast"}, "UBOT"))

    def test_clean(self):
        self.assertEqual(self.mod.clean("<@U1|alex> see <#C1|general> <!here> <mailto:a@b.co|a@b.co> 1 &lt; 2", "UBOT"),
                         "@U1 see #general @here a@b.co 1 < 2")

    def test_send_posts_to_the_channel(self):
        self.assertTrue(self.mod.send("D123", "hello"))
        url, data, h = self.http.to("chat.postMessage")[0]
        self.assertEqual(json.loads(data.decode()), {"channel": "D123", "text": "hello", "unfurl_links": False})
        self.assertEqual(h["Authorization"], "Bearer " + BOT)
        self.assertEqual(self.mod.LIMIT, 3900)
        self.assertIsNone(self.mod.typing("D123"))

    def test_dm_chat_caches(self):
        self.assertEqual(self.mod.dm_chat("U777"), "D999")
        self.assertEqual(self.mod.dm_chat("U777"), "D999")
        calls = self.http.to("conversations.open")
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0][1].decode()), {"users": "U777"})

    def test_send_file_uploads_in_three_steps(self):
        p = os.path.join(TMP, "note.txt")
        with open(p, "w") as fh:
            fh.write("file body here")
        self.assertTrue(self.mod.send_file("C55", p, "the notes"))
        url, data, h = self.http.to("files.getUploadURLExternal")[0]
        self.assertEqual(h["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(data.decode(), "filename=note.txt&length=14")
        url, data, h = self.http.to("files.slack.com/upload")[0]
        self.assertTrue(h["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'Content-Disposition: form-data; name="file"; filename="note.txt"', data)
        self.assertIn(b"\r\n\r\nfile body here\r\n", data)
        url, data, h = self.http.to("files.completeUploadExternal")[0]
        self.assertEqual(json.loads(data.decode()), {"files": [{"id": "F1", "title": "note.txt"}], "channel_id": "C55",
                                                     "initial_comment": "the notes"})
        self.assertFalse(self.mod.send_file("C55", os.path.join(TMP, "missing.txt")))

    def test_download_uses_the_bot_token(self):
        att = {"kind": "photo", "name": "shot.png", "mime": "image/png", "size": 7, "duration": 0,
               "ref": {"url": "https://files.slack.com/files-pri/1/shot.png", "name": "shot.png"}}
        dest = os.path.join(TMP, "inbox")
        p = self.mod.download(att, dest, "shot.png")
        self.assertTrue(p and p.startswith(dest + os.sep) and p.endswith("-shot.png"), p)
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"PNGDATA")
        url, data, h = self.http.to("files-pri")[0]
        self.assertIsNone(data)
        self.assertEqual(h["Authorization"], "Bearer " + BOT)
        self.http.routes["files.slack.com/files-pri"] = (200, b"<html>sign in</html>", {"content-type": "text/html"})
        self.assertIsNone(self.mod.download(att, dest, "shot.png"))                      # Slack's sign-in page is not the file


class Discord(Adapter, unittest.TestCase):
    channel = "discord"

    def routes(self):
        hits = {}

        def messages(url, data, headers):
            content = json.loads(data.decode())["content"] if headers.get("Content-Type") == "application/json" else ""
            hits[content] = hits.get(content, 0) + 1
            if content == "never" or (content == "slow" and hits[content] == 1):
                return 429, {"message": "You are being rate limited.", "retry_after": 0.01, "global": False}
            return 200, {"id": "m%d" % len(hits)}
        return {
            "/users/@me/channels": {"id": "777777777777777777", "type": 1},
            "/users/@me": {"id": "1000", "username": "staffbot", "bot": True},
            "/gateway/bot": {"url": "wss://gateway.discord.gg", "shards": 1},
            "/messages": messages,
            "/typing": (204, b""),
            "cdn.discordapp.com": (200, b"OGGDATA"),
        }

    def setUp(self):
        secrets(discord_bot_token=DISCORD)
        super().setUp()

    def test_token(self):
        self.assertEqual(self.mod.token(), DISCORD)
        secrets()
        self.assertIsNone(self.mod.token())
        self.assertFalse(self.mod.check()[0])

    def test_check(self):
        self.assertEqual(self.mod.check(), (True, "staffbot"))
        url, data, h = self.http.to("/users/@me")[0]
        self.assertEqual((h["Authorization"], h["User-Agent"]), ("Bot " + DISCORD, "Staffroom (https://github.com, 0.1)"))

    def test_listen_identifies_heartbeats_and_normalizes(self):
        def msg(**d):
            return {"op": 0, "t": "MESSAGE_CREATE", "s": d.pop("s", 2),
                    "d": {"id": "m1", "channel_id": "555", "author": {"id": "42", "username": "alex", "global_name": "Alex"},
                          "content": "<@1000> @sara hi", "attachments": [], "flags": 0, **d}}
        script = [{"op": 10, "d": {"heartbeat_interval": 300}},
                  {"op": 0, "t": "READY", "s": 1, "d": {"v": 10, "user": {"id": "1000", "username": "staffbot"},
                                                       "session_id": "sess1", "resume_gateway_url": "wss://gateway-us-east1-b.discord.gg"}},
                  ("after", '"op": 1'), {"op": 11}, {"op": 1}, "timeout",
                  msg(),
                  msg(author={"id": "1000", "username": "staffbot", "bot": True}, content="my own echo"),
                  msg(s=3, flags=8192, content="", attachments=[{"filename": "voice-message.ogg", "content_type": "audio/ogg", "size": 9,
                                                                 "url": "https://cdn.discordapp.com/attachments/1/2/voice-message.ogg",
                                                                 "duration_secs": 2.5}]),
                  msg(s=4, guild_id="999", channel_id="C1", content="sara: status?", referenced_message={"content": "Sara: earlier"},
                      attachments=[{"filename": "pic.jpg", "content_type": "image/jpeg", "size": 3,
                                    "url": "https://cdn.discordapp.com/attachments/1/3/pic.jpg"}])]
        got, sent, opened, logs = self.run_listen(script)
        self.assertEqual(opened, ["wss://gateway.discord.gg/?v=10&encoding=json"])
        frames = [json.loads(s) for s in sent]
        self.assertEqual(frames[0]["op"], 2)
        self.assertEqual(frames[0]["d"]["token"], DISCORD)
        self.assertEqual(frames[0]["d"]["intents"], 37377)
        self.assertEqual(frames[0]["d"]["properties"], {"os": "staffroom", "browser": "staffroom", "device": "staffroom"})
        beats = [f for f in frames if f["op"] == 1]
        self.assertGreaterEqual(len(beats), 2)                                      # the thread's beat, and the reply to op 1
        self.assertTrue(all(f["d"] in (None, 1) for f in beats), beats)             # the last sequence seen at the time
        self.assertEqual(len(got), 3)
        m = got[0]
        self.assertEqual(set(m), MESSAGE_KEYS)
        self.assertEqual((m["channel"], m["sender"], m["chat"], m["is_group"], m["chat_title"]), ("discord", "discord:42", "discord:555", False, None))
        self.assertEqual((m["sender_name"], m["username"], m["text"], m["reply_to_text"]), ("Alex", "alex", "@sara hi", ""))
        v = got[1]["attachments"][0]
        self.assertEqual((v["kind"], v["name"], v["mime"], v["size"], v["duration"]), ("voice", "voice-message.ogg", "audio/ogg", 9, 2.5))
        self.assertEqual(v["ref"]["url"], "https://cdn.discordapp.com/attachments/1/2/voice-message.ogg")
        g = got[2]
        self.assertEqual((g["chat"], g["is_group"], g["chat_title"], g["text"], g["reply_to_text"]), ("discord:C1", True, "C1", "sara: status?", "Sara: earlier"))
        self.assertEqual([a["kind"] for a in g["attachments"]], ["photo"])
        self.assertFalse(any(DISCORD in line for line in logs), logs)

    def test_listen_resumes_then_identifies_again(self):
        hello = {"op": 10, "d": {"heartbeat_interval": 60000}}
        ready = {"op": 0, "t": "READY", "s": 1, "d": {"user": {"id": "1000"}, "session_id": "sess1",
                                                     "resume_gateway_url": "wss://gateway-us-east1-b.discord.gg"}}
        script = [hello, ready, {"op": 7},                                    # RECONNECT → resume at the resume URL
                  hello, struct.pack(">H", 4000) + b"unknown error",          # a close frame → resume again
                  hello, {"op": 9, "d": False},                               # not resumable → identify afresh
                  hello, struct.pack(">H", 4014) + b"disallowed intents"]     # fatal: say why, drop the session
        got, sent, opened, logs = self.run_listen(script)
        gw, resume = "wss://gateway.discord.gg/?v=10&encoding=json", "wss://gateway-us-east1-b.discord.gg/?v=10&encoding=json"
        self.assertEqual(opened, [gw, resume, resume, gw, gw])                  # the last one: a fresh start after the fatal close
        frames = [json.loads(s) for s in sent]
        self.assertEqual([f["op"] for f in frames], [2, 6, 6, 2])
        self.assertEqual(frames[1]["d"], {"token": DISCORD, "session_id": "sess1", "seq": 1})
        self.assertEqual(len(self.http.to("/gateway/bot")), 3)
        self.assertTrue(any("Message Content Intent" in line for line in logs), logs)
        self.assertEqual(got, [])

    def test_normalize_ignores_bots(self):
        d = {"id": "1", "channel_id": "5", "author": {"id": "9", "username": "x", "bot": True}, "content": "hi"}
        self.assertIsNone(self.mod.normalize(d))
        self.assertIsNone(self.mod.normalize({"content": "no author"}))

    def test_send_retries_a_429_once(self):
        self.assertTrue(self.mod.send("555", "hi"))
        url, data, h = self.http.to("/channels/555/messages")[0]
        self.assertEqual(json.loads(data.decode()), {"content": "hi"})
        self.assertEqual((h["Authorization"], h["Content-Type"]), ("Bot " + DISCORD, "application/json"))
        self.assertTrue(self.mod.send("555", "slow"))
        self.assertEqual(len(self.http.to("/channels/555/messages")), 3)
        self.assertFalse(self.mod.send("555", "never"))
        self.assertEqual(len(self.http.to("/channels/555/messages")), 5)                 # tried twice, no more
        self.assertEqual(self.mod.LIMIT, 1900)

    def test_send_file_is_multipart(self):
        p = os.path.join(TMP, "note.txt")
        with open(p, "wb") as fh:
            fh.write(b"file body here")
        self.assertTrue(self.mod.send_file("555", p, "the notes"))
        url, data, h = self.http.to("/channels/555/messages")[-1]
        self.assertTrue(h["Content-Type"].startswith("multipart/form-data; boundary="))
        boundary = h["Content-Type"].split("boundary=")[1].encode()
        self.assertTrue(data.startswith(b"--" + boundary + b"\r\n") and data.endswith(b"--" + boundary + b"--\r\n"))
        self.assertIn(b'Content-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n', data)
        self.assertIn(json.dumps({"content": "the notes", "attachments": [{"id": 0, "filename": "note.txt"}]}).encode(), data)
        self.assertIn(b'Content-Disposition: form-data; name="files[0]"; filename="note.txt"\r\nContent-Type: text/plain\r\n\r\nfile body here\r\n', data)
        self.assertFalse(self.mod.send_file("555", os.path.join(TMP, "missing.txt")))

    def test_typing_and_dm_chat_cache(self):
        self.mod.typing("555")
        url, data, h = self.http.to("/channels/555/typing")[0]
        self.assertEqual(data, b"")
        self.assertEqual(self.mod.dm_chat("42"), "777777777777777777")
        self.assertEqual(self.mod.dm_chat(42), "777777777777777777")
        calls = self.http.to("/users/@me/channels")
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0][1].decode()), {"recipient_id": "42"})

    def test_download_needs_no_token(self):
        att = {"kind": "voice", "name": "voice-message.ogg", "mime": "audio/ogg", "size": 7, "duration": 2.5,
               "ref": {"url": "https://cdn.discordapp.com/attachments/1/2/voice-message.ogg?ex=1&is=2&hm=3", "name": "voice-message.ogg"}}
        dest = os.path.join(TMP, "inbox")
        p = self.mod.download(att, dest, "voice.ogg")
        self.assertTrue(p and p.startswith(dest + os.sep) and p.endswith("-voice.ogg"), p)
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"OGGDATA")
        url, data, h = self.http.to("cdn.discordapp.com")[0]
        self.assertIsNone(data)
        self.assertNotIn("Authorization", h)


if __name__ == "__main__":
    unittest.main()
