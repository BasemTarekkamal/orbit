#!/usr/bin/env python3
"""The team bus: how employees talk to each other (and to the team group).

  staff-bus ask <employee-id> "<question or task>"
  staff-bus post "<message for the team group>"
  staff-bus who                      # colleagues and what they own

`ask` queues a message for a colleague; staffd runs them with it and sends their answer back to you
as a new turn ("[Answer from …]"). Don't wait or poll. A conversation between employees stops after
4 hops (loop guard). Everything is logged in ~/Staff/team/bus.jsonl and visible to the owners.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

BUS = os.path.join(engine.HOME, "team", "bus.jsonl")
MAX_HOPS = 4


def append(rec: dict):
    os.makedirs(os.path.dirname(BUS), exist_ok=True)
    with open(BUS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read() -> list:
    try:
        return [json.loads(line) for line in open(BUS, encoding="utf-8") if line.strip()]
    except OSError:
        return []


def main():
    me = os.environ.get("STAFF_EMPLOYEE", "owner")
    thread = os.environ.get("STAFF_THREAD") or uuid.uuid4().hex[:8]
    hops = int(os.environ.get("STAFF_HOPS", "0"))
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    emps = {k: e for k, e in engine.registry().get("employees", {}).items() if e.get("status", "active") == "active"}
    if cmd == "who":
        for k, e in emps.items():
            print("%s (%s): %s — supervisor %s" % (k, e.get("name"), e.get("role"), e.get("supervisor")))
        return
    if cmd == "ask":
        if len(sys.argv) < 4:
            sys.exit("usage: staff-bus ask <employee-id> \"<text>\"")
        to, text = sys.argv[2].lower(), sys.argv[3]
        if to not in emps:
            sys.exit("no colleague %r. Try: staff-bus who" % to)
        import abilities
        if me in emps and not abilities.has(me, "team_room"):
            sys.exit("your 'Team room' ability is off; an owner can switch it on in the control panel")
        if not abilities.has(to, "team_room"):
            sys.exit("%s isn't taking colleague questions (ability off); tell your owner instead" % to)
        if to == me:
            sys.exit("that's you")
        if hops >= MAX_HOPS:
            sys.exit("loop guard: this thread already bounced %d times between colleagues; answer your owner instead" % hops)
        rec = {"id": uuid.uuid4().hex[:10], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "ask",
               "from": me, "to": to, "text": text[:4000], "thread": thread, "hops": hops + 1, "delivered": False}
        append(rec)
        print(json.dumps({"queued": rec["id"], "to": to, "note": "their answer will come to you as a new turn"}))
    elif cmd == "post":
        text = " ".join(sys.argv[2:])
        append({"id": uuid.uuid4().hex[:10], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "post",
                "from": me, "to": "team", "text": text[:4000], "thread": thread, "hops": hops, "delivered": False})
        print(json.dumps({"posted": True}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
