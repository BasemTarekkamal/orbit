#!/usr/bin/env python3
"""Three small records a crew member writes so the control panel can show its work as cards, bars and tiles.

  staff-record result --title "Roasting-day short" --kind short --where https://example.com/v/1 [--objective o-1]
  staff-record ask --title "Match the price cut?" --why "Harbor Roast went to $34" --kind decision --option "Match it" --option "Hold"
  staff-record objective --id o-cafes --title "Hold our café accounts" --due 2026-12-31
  staff-record kr --objective o-cafes --name "Cafés kept" --unit cafés --target 12 --current 11
  staff-record list results|asks|objectives [--json]

result     one row for each thing you shipped (kind: short, video, post, report, file or other).
ask        one question for your owner (kind: decision, approval or blocked). It shows up on their Home screen as a
           card with buttons; their answer is sent back to you as a message. Give --option for each choice.
objective  create or update an objective (a goal with a due date).
kr         create or update a key result of an objective, found by its name: what it measures, the target, where it is now.

Stored in <your workspace>/state/ (STAFF_EMPLOYEE picks the workspace): results.jsonl, asks.jsonl, objectives.json.
Times are this computer's local time. Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KINDS = ("short", "video", "post", "report", "file", "other")
ASK_KINDS = ("decision", "approval", "blocked")
FMT = "%Y-%m-%dT%H:%M:%S"


def ws_of(emp_id=None):
    """The crew member's workspace, found the way remind.py finds it."""
    import engine
    emp_id = emp_id or os.environ.get("STAFF_EMPLOYEE")
    if emp_id:
        return engine.employee(emp_id)["workspace"]
    return os.getcwd()


def _path(ws, name):
    return os.path.join(ws, "state", name)


def now():
    return dt.datetime.now().strftime(FMT)


def new_id(prefix):
    return "%s-%s" % (prefix, secrets.token_hex(2))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _read_rows(path):
    """Rows of a .jsonl file; lines that aren't a JSON object with an id are skipped."""
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("id"):
                    rows.append(r)
    except OSError:
        pass
    return rows


def _write_rows(path, rows):
    _write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# ------------------------------------------------------------------ results
def add_result(ws, title, kind="other", where="", objective=""):
    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("a result needs a --title")
    kind = kind if kind in KINDS else "other"
    p = _path(ws, "results.jsonl")
    rows = _read_rows(p)
    r = {"id": new_id("r"), "ts": now(), "title": title[:200], "kind": kind, "where": str(where or "").strip()[:500],
         "objective": str(objective or "").strip()[:60]}
    rows.append(r)
    _write_rows(p, rows)
    return r


def results(ws, days=7):
    """Results from the last `days` days (all of them when days is None), newest first."""
    rows = [r for r in _read_rows(_path(ws, "results.jsonl")) if str(r.get("ts", ""))[:1].isdigit()]
    if days is not None:
        cut = (dt.datetime.now() - dt.timedelta(days=days)).strftime(FMT)
        rows = [r for r in rows if str(r.get("ts", "")) >= cut]
    return sorted(rows, key=lambda r: str(r.get("ts", "")), reverse=True)


# ------------------------------------------------------------------ asks
def add_ask(ws, title, why="", kind="decision", options=None):
    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("an ask needs a --title")
    if kind not in ASK_KINDS:
        raise ValueError("--kind must be decision, approval or blocked")
    p = _path(ws, "asks.jsonl")
    rows = _read_rows(p)
    a = {"id": new_id("a"), "ts": now(), "title": title[:200], "why": " ".join(str(why or "").split())[:400], "kind": kind,
         "options": [" ".join(str(o).split())[:60] for o in (options or []) if str(o).strip()][:4], "status": "open",
         "answer": "", "answered_ts": ""}
    rows.append(a)
    _write_rows(p, rows)
    return a


def asks(ws, status=None):
    """Asks, oldest first (the one waiting longest leads); filtered to one status when given."""
    rows = _read_rows(_path(ws, "asks.jsonl"))
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return sorted(rows, key=lambda r: str(r.get("ts", "")))


def answer(ws, ask_id, text, status="answered"):
    """Marks an open ask answered (or dropped) and keeps the answer. Returns the row, or None if there is no such open ask."""
    p = _path(ws, "asks.jsonl")
    rows, hit = _read_rows(p), None
    for r in rows:
        if r.get("id") == ask_id and r.get("status") == "open":
            r.update({"status": status, "answer": " ".join(str(text or "").split())[:400], "answered_ts": now()})
            hit = r
            break
    if hit:
        _write_rows(p, rows)
    return hit


# ------------------------------------------------------------------ objectives
def objectives(ws):
    try:
        with open(_path(ws, "objectives.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for o in data if isinstance(data, list) else []:
        if isinstance(o, dict) and o.get("id"):
            o["key_results"] = [k for k in (o.get("key_results") or []) if isinstance(k, dict) and k.get("name")]
            out.append(o)
    return out


def _save_objectives(ws, items):
    _write(_path(ws, "objectives.json"), json.dumps(items, indent=1, ensure_ascii=False) + "\n")


def set_objective(ws, oid, title, due):
    oid = str(oid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", oid):
        raise ValueError("--id must be a short word like o-cafes (letters, digits, - and _)")
    try:
        dt.datetime.strptime(due, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("--due must look like 2026-12-31")
    items = objectives(ws)
    o = next((x for x in items if x["id"] == oid), None)
    if o is None:
        o = {"id": oid, "title": "", "due": due, "key_results": []}
        items.append(o)
    o.update({"title": " ".join(str(title or "").split())[:200] or o["title"], "due": due})
    _save_objectives(ws, items)
    return o


def _num(x):
    x = float(x)
    return int(x) if x == int(x) else x


def set_kr(ws, oid, name, unit, target, current):
    items = objectives(ws)
    o = next((x for x in items if x["id"] == oid), None)
    if o is None:
        raise ValueError("no objective %r: create it first with  staff-record objective" % oid)
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("a key result needs a --name")
    k = next((x for x in o["key_results"] if x["name"] == name), None)
    if k is None:
        k = {"name": name, "unit": "", "target": 0, "current": 0}
        o["key_results"].append(k)
    k.update({"unit": str(unit or "").strip()[:20], "target": _num(target), "current": _num(current)})
    _save_objectives(ws, items)
    return k


def progress(kr):
    """0..1: how far a key result is toward its target."""
    try:
        t, c = float(kr.get("target") or 0), float(kr.get("current") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c / t)) if t > 0 else 0.0


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--employee", help="whose workspace (default: you, from STAFF_EMPLOYEE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("result", help="record one thing you shipped")
    p.add_argument("--title", required=True, help="what it is, in a few words")
    p.add_argument("--kind", choices=KINDS, default="other")
    p.add_argument("--where", default="", help="a link, or a path inside your workspace")
    p.add_argument("--objective", default="", help="the objective id it serves")
    p = sub.add_parser("ask", help="ask your owner a question")
    p.add_argument("--title", required=True, help="the question, in one line")
    p.add_argument("--why", default="", help="why you need it, in one line")
    p.add_argument("--kind", choices=ASK_KINDS, required=True)
    p.add_argument("--option", action="append", default=[], help="one choice; repeat for each (up to 4)")
    p = sub.add_parser("objective", help="create or update an objective")
    p.add_argument("--id", required=True); p.add_argument("--title", required=True); p.add_argument("--due", required=True, help="YYYY-MM-DD")
    p = sub.add_parser("kr", help="create or update a key result of an objective")
    p.add_argument("--objective", required=True); p.add_argument("--name", required=True)
    p.add_argument("--unit", default=""); p.add_argument("--target", required=True, type=float); p.add_argument("--current", required=True, type=float)
    p = sub.add_parser("list", help="show your records")
    p.add_argument("what", choices=["results", "asks", "objectives"]); p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ws = ws_of(a.employee)
    try:
        if a.cmd == "result":
            print(add_result(ws, a.title, a.kind, a.where, a.objective)["id"])
        elif a.cmd == "ask":
            print(add_ask(ws, a.title, a.why, a.kind, a.option)["id"])
        elif a.cmd == "objective":
            print(set_objective(ws, a.id, a.title, a.due)["id"])
        elif a.cmd == "kr":
            k = set_kr(ws, a.objective, a.name, a.unit, a.target, a.current)
            print("%s: %s / %s" % (k["name"], k["current"], k["target"]))
        else:
            rows = {"results": lambda: results(ws, None), "asks": lambda: asks(ws), "objectives": lambda: objectives(ws)}[a.what]()
            if a.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for r in rows:
                    if a.what == "objectives":
                        print("%s  %s  due %s" % (r["id"], r["title"], r.get("due", "")))
                        for k in r["key_results"]:
                            print("    %s: %s / %s %s" % (k["name"], k.get("current"), k.get("target"), k.get("unit", "")))
                    elif a.what == "asks":
                        print("%s  %s  [%s, %s]%s" % (r["id"], r["title"], r.get("kind"), r.get("status"), "  -> " + r["answer"] if r.get("answer") else ""))
                    else:
                        print("%s  %s  %s  %s" % (r["id"], r["ts"], r["title"], r.get("where", "")))
    except ValueError as ex:
        sys.exit(str(ex))


if __name__ == "__main__":
    main()
