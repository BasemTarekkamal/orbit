"""Chat channels: how owners reach the team, and the team reaches owners. One adapter per channel,
all with the same small interface. staffd runs a listener thread per configured channel; the harness
delivers through `team.send`. Employees never touch these: the guard blocks the raw chat APIs and the
sandbox can't reach them. Your bots are yours: each install talks only to the bots whose tokens you
saved in ~/Staff/.secrets, and nothing else.

Addresses: "<channel>:<id>", e.g. telegram:123456, slack:U0ABC12, discord:987654321. A bare number is
a Telegram id (the registry's original form). An owner is keyed by the address they first paired
with; more addresses for the same person live in owners.<key>.addresses. A user address names a
person; a chat address names where to deliver (a private chat or a team channel).

An adapter module (channels/<name>.py) provides:
  NAME                                 "slack"
  LIMIT                                characters per message
  token() -> str | None                its secret(s) from ~/Staff/.secrets, or None when not set up
  check() -> (ok, note)                can we talk to the service as that bot?
  listen(put, log, stop) -> None       blocking: put(message) for every new message until stop is set;
                                       staffd restarts it if it returns or raises
  send(chat_id, text) -> bool
  send_file(chat_id, path, caption="") -> bool
  typing(chat_id) -> None              best effort
  dm_chat(user_id) -> str | None       the chat id for a private message to this user
  download(att, dest_dir, name) -> str | None     saves an attachment, returns its path
  mention(handle) -> str               how to address an employee here ("/sara" or "@sara")

A message is a plain dict:
  channel, sender ("<channel>:<user id>"), sender_name, username, chat ("<channel>:<chat id>"),
  is_group, chat_title, text, reply_to_text,
  attachments: [{kind: voice|audio|video|video_note|photo|file, name, mime, size, duration, ref}]
Python 3.9 compatible.
"""
from __future__ import annotations

import importlib
import re

NAMES = ("telegram", "slack", "discord")
LABELS = {"telegram": "Telegram", "slack": "Slack", "discord": "Discord"}


def parse(address):
    """"slack:U1" → ("slack", "U1"); "123" / "-100123" → ("telegram", …); anything else → ("", address)."""
    s = str(address or "").strip()
    for n in NAMES:
        if s.startswith(n + ":"):
            return n, s[len(n) + 1:]
    if re.fullmatch(r"-?\d+", s):
        return "telegram", s
    return "", s


def addr(channel, cid) -> str:
    return "%s:%s" % (channel, cid)


def norm(address) -> str:
    """The canonical form: a bare Telegram id becomes telegram:<id>; unknown strings stay as they are."""
    ch, cid = parse(address)
    return addr(ch, cid) if ch else str(address or "").strip()


def get(name):
    if name not in NAMES:
        raise KeyError("no channel %r" % name)
    return importlib.import_module("channels." + name)


def configured() -> list:
    """The channels whose tokens are saved."""
    out = []
    for n in NAMES:
        try:
            if get(n).token():
                out.append(n)
        except Exception:  # noqa: BLE001  (an adapter missing its library must not stop the others)
            pass
    return out


def label(address) -> str:
    """"telegram:123" → "Telegram id 123"; "local-alex" → "this Mac only"."""
    ch, cid = parse(address)
    if not ch:
        return "this Mac only" if str(address).startswith("local-") else str(address)
    return "%s id %s" % (LABELS[ch], cid)


def guess(cid) -> str:
    """Which channel a team-chat id belongs to, from its shape: -100… Telegram, C…/G… Slack, 17–20 digits Discord."""
    s = str(cid).strip()
    if re.fullmatch(r"-\d+", s):
        return "telegram"
    if re.fullmatch(r"[CG][A-Z0-9]{6,}", s):
        return "slack"
    if re.fullmatch(r"\d{17,20}", s):
        return "discord"
    return ""
