"""A crew member's plan: PLAN.md in its folder, the one place its strategy lives (goal, how, cadence, milestones,
numbers, reviews, decisions). The panel shows it on the Plan tab and on Today; an owner agrees to it with one
click; the weekly review rewrites it.

    import plan
    plan.summary("sara")          # {"status", "agreed", "goal", "next", "numbers", "reviewed", "decisions"}
    plan.agree("sara", by="Alex")  # Status: agreed on <date> by Alex
"""
from __future__ import annotations

import datetime as dt
import os
import re

import engine

FILE = "PLAN.md"


def path(emp_id: str) -> str:
    return os.path.join(engine.employee(emp_id)["workspace"], FILE)


def read(emp_id: str) -> str:
    try:
        with open(path(emp_id), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _sections(text: str) -> dict:
    out = {}
    for part in re.split(r"\n## ", "\n" + text)[1:]:
        head, _, body = part.partition("\n")
        out[head.strip().lower()] = body.strip()
    return out


def _find(secs: dict, *words):
    for k, v in secs.items():
        if any(w in k for w in words):
            return v
    return ""


def _table(body: str) -> list:
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.fullmatch(r"\|[\s|:-]+\|", line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:] if rows else []                     # the first row is the header


def _real(text: str) -> str:
    """The template's placeholder lines (in _italics_) don't count as content."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not re.fullmatch(r"\s*_.*_\s*", ln)]
    return "\n".join(lines).strip()


def summary(emp_id: str, text: str = None) -> dict:
    text = read(emp_id) if text is None else text
    if not text.strip():
        return {"status": "none"}
    m = re.search(r"^Status:\s*\**\s*(proposed|agreed)\**\s*(.*)$", text, re.M | re.I)
    status = m.group(1).lower() if m else "proposed"
    secs = _sections(text)
    goal = _real(_find(secs, "goal"))
    if not goal:
        return {"status": "none"}
    lines = [re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", ln).strip() for ln in goal.splitlines()]
    first = lines[0] + (" " + lines[1] if lines[0].endswith(":") and len(lines) > 1 else "")
    miles = _table(_find(secs, "milestone"))
    nxt = next(({"by": r[0], "what": r[1], "status": r[2] if len(r) > 2 else ""} for r in miles
                if len(r) >= 2 and not re.search(r"\bdone\b|✓|✅", r[2] if len(r) > 2 else "", re.I)), None)
    nums = [{"date": r[0], "metric": r[1], "value": r[2], "target": r[3] if len(r) > 3 else ""}
            for r in _table(_find(secs, "numbers")) if len(r) >= 3]
    reviews = re.findall(r"^\s*-\s*(\d{4}-\d{2}-\d{2})", _find(secs, "review"), re.M)
    decisions = [re.sub(r"^\s*\d+[.)]\s*", "", ln).strip() for ln in _real(_find(secs, "decision")).splitlines()
                 if re.match(r"^\s*(\d+[.)]|[-*])\s+", ln)]
    return {"status": status, "agreed": (m.group(2).strip() if m and status == "agreed" else ""), "goal": first[:240],
            "next": nxt, "numbers": nums[-4:], "reviewed": reviews[-1] if reviews else "", "decisions": decisions[:4]}


def agree(emp_id: str, by: str) -> str:
    text = read(emp_id)
    if summary(emp_id, text)["status"] == "none":
        raise ValueError("There's no plan to agree to yet")
    line = "Status: **agreed** on %s by %s" % (dt.date.today().isoformat(), by)
    new, n = re.subn(r"^Status:.*$", line, text, count=1, flags=re.M)
    if not n:
        new = re.sub(r"^(# .*\n)", lambda m: m.group(1) + "\n" + line + "\n", text, count=1)
    with open(path(emp_id), "w", encoding="utf-8") as fh:
        fh.write(new)
    return "Agreed. %s works to this plan now and reviews it with you every week." % engine.employee(emp_id)["name"]


REVIEWS = """
## Reviews
_Every week: what worked, what didn't, what changes. One line each:_
_- <date> · Kept: … · Stopped: … · Trying: … · Because: …_
"""


def ensure_reviews(emp_id: str) -> None:
    """Older plans get the Reviews section the weekly review writes into."""
    text = read(emp_id)
    if not text or re.search(r"^## Reviews", text, re.M):
        return
    m = re.search(r"^## Decisions I need", text, re.M)
    text = (text[:m.start()] + REVIEWS.lstrip("\n") + "\n" + text[m.start():]) if m else text.rstrip("\n") + "\n" + REVIEWS
    with open(path(emp_id), "w", encoding="utf-8") as fh:
        fh.write(text)
