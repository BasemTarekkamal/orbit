#!/usr/bin/env python3
"""Reminders and self-scheduled follow-ups for any employee. staffd delivers them.

  staff-remind add --at "2026-11-02 10:00" --to <owner name> --text "…"
  staff-remind add --in 2h --to all --agent --text "Re-check X and ask Y if still open"
  staff-remind add --at "2026-11-01 09:00" --to <owner name> --repeat monthly --text "…"
  staff-remind list | cancel R-0003

--to       an owner's name, "all", or "me" (wakes only you, with --agent)
--repeat   none | daily | weekly | monthly
--agent    at due time you are run with --text as your task; your output (unless SILENT) is sent.
Times are this Mac's local time. Stored in <your workspace>/state/reminders.json (STAFF_EMPLOYEE picks the workspace).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402


def ws_of(emp_id=None):
    emp_id = emp_id or os.environ.get("STAFF_EMPLOYEE")
    if emp_id:
        return engine.employee(emp_id)["workspace"]
    return os.getcwd()


def path(ws):
    return os.path.join(ws, "state", "reminders.json")


def load(ws):
    try:
        return json.load(open(path(ws)))
    except (OSError, ValueError):
        return []


def save(ws, items):
    os.makedirs(os.path.dirname(path(ws)), exist_ok=True)
    tmp = path(ws) + ".tmp"
    json.dump(items, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, path(ws))


def now():
    return dt.datetime.now().replace(second=0, microsecond=0)


def advance(w, rep):
    if rep == "daily":
        return w + dt.timedelta(days=1)
    if rep == "weekly":
        return w + dt.timedelta(days=7)
    if rep == "monthly":
        y, m = w.year + w.month // 12, w.month % 12 + 1
        for day in (w.day, 30, 29, 28):
            try:
                return w.replace(year=y, month=m, day=day)
            except ValueError:
                continue
    return None


def due(ws):
    """Pop due reminders (rescheduling repeats) and return them for delivery."""
    items, out, keep, t = load(ws), [], [], now()
    for r in items:
        w = dt.datetime.strptime(r["at"], "%Y-%m-%d %H:%M")
        if w <= t:
            out.append(dict(r))
            nxt = advance(w, r.get("repeat", "none"))
            while nxt and nxt <= t:
                nxt = advance(nxt, r["repeat"])
            if nxt:
                r["at"] = nxt.strftime("%Y-%m-%d %H:%M")
                keep.append(r)
        else:
            keep.append(r)
    if out:
        save(ws, keep)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--employee")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--at"); p.add_argument("--in", dest="within")
    p.add_argument("--to", required=True); p.add_argument("--text", required=True)
    p.add_argument("--repeat", choices=["none", "daily", "weekly", "monthly"], default="none")
    p.add_argument("--agent", action="store_true")
    sub.add_parser("list")
    p = sub.add_parser("cancel"); p.add_argument("id")
    a = ap.parse_args()
    me = a.employee or os.environ.get("STAFF_EMPLOYEE")
    if a.cmd == "add" and me:
        import abilities
        if not abilities.has(me, "reminders"):
            sys.exit("the 'Reminders' ability is off for you; an owner can switch it on in the control panel")
    ws = ws_of(a.employee)
    items = load(ws)
    if a.cmd == "add":
        if a.within:
            m = re.fullmatch(r"(\d+)\s*([mhd])", a.within.strip())
            if not m:
                sys.exit("--in must look like 30m, 2h or 3d")
            when = now() + dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]: int(m.group(1))})
        elif a.at:
            when = dt.datetime.strptime(a.at, "%Y-%m-%d %H:%M")
        else:
            sys.exit("give --at or --in")
        to = a.to.lower()
        if to not in ("both", "all", "me") and not engine.owner_id(to):
            sys.exit("--to must be an owner name, all, or me")
        cf = path(ws) + ".counter"
        n = max([int(r["id"][2:]) for r in items] + [int(open(cf).read()) if os.path.exists(cf) else 0]) + 1
        open(cf, "w").write(str(n))
        r = {"id": "R-%04d" % n, "at": when.strftime("%Y-%m-%d %H:%M"), "to": to, "text": a.text,
             "repeat": a.repeat, "agent": a.agent or to == "me", "created": now().strftime("%Y-%m-%d %H:%M")}
        items.append(r)
        save(ws, items)
        print(json.dumps(r, ensure_ascii=False))
    elif a.cmd == "list":
        print(json.dumps(sorted(items, key=lambda r: r["at"]), ensure_ascii=False, indent=1))
    else:
        left = [r for r in items if r["id"] != a.id]
        save(ws, left)
        print(json.dumps({"cancelled": a.id, "found": len(left) != len(items)}))


if __name__ == "__main__":
    main()
