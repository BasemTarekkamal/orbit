"""Is this computer really awake, and keeping it awake for the crew. Nothing runs on a sleeping computer.

A sleeping laptop still wakes for a few seconds every 15 minutes or so (macOS calls it a dark wake): long enough
for the service to tick and start a run, which then freezes for hours and fails. So work starts only after the
computer has been awake for a minute without a gap, and once a run starts the computer stays up until it ends.

    awake.start()              # in the service: watches for sleep and applies the Keep awake setting
    awake.settled()            # awake for a minute without a gap: safe to start work
    awake.hold(pid)            # no idle sleep until that process ends (a run)
    awake.slept(24)            # {"hours", "longest", "from", "to"}: time asleep lately, for the owner to see

The Keep awake setting (registry "keep_awake"): "plugged" (default: never sleeps from idle while plugged in),
"always" (on battery too) or "off" (and runs don't hold it either). Closing a laptop's lid can still put it to sleep.
Sleep is seen by the wall clock jumping, so this works the same on a Mac, Linux and Windows (WSL).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

import engine
import osinfo

GAP = 30                   # seconds without a beat: it was asleep
SETTLE = 60                # dark wakes last up to about 45 seconds
MERGE = 180                # sleeps this close together are one sleep, split by a dark wake
FILE = os.path.join(engine.HOME, "team", "sleep.json")
MODES = ("plugged", "always", "off")

_since = 0.0               # awake without a gap since; 0 = not watching (tools and tests: always settled)
_last = 0.0
_proc = None               # the service-long keep-awake process
_mode = None


def mode() -> str:
    m = engine.registry().get("keep_awake")
    return m if m in MODES else "plugged"


def settled() -> bool:
    return time.time() - _since >= SETTLE


def _spawn(cmd):
    try:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError:
        return None


def hold(pid: int) -> None:
    """Until that process ends, this computer doesn't sleep from idle, on battery too. It needs no admin rights
    and changes no setting; it ends with the process."""
    if mode() != "off":
        cmd = osinfo.keep_awake_cmd(pid, battery=True)
        if cmd:
            _spawn(cmd)


def _apply_mode():
    """The Keep awake setting, for as long as the service runs."""
    global _proc, _mode
    m = mode()
    if m == _mode and (_proc is None or _proc.poll() is None):
        return
    if _proc and _proc.poll() is None:
        _proc.terminate()
    _proc, _mode = None, m
    if m != "off":
        cmd = osinfo.keep_awake_cmd(os.getpid(), battery=m == "always")
        _proc = _spawn(cmd) if cmd else None


def _load() -> list:
    try:
        with open(FILE, encoding="utf-8") as fh:
            rows = json.load(fh)
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def record(start: float, end: float) -> None:
    rows = _load()
    if rows and start - rows[-1]["to"] <= MERGE:
        rows[-1]["to"] = int(end)
    else:
        rows.append({"from": int(start), "to": int(end)})
    tmp = FILE + ".tmp"
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows[-60:], fh)
    os.replace(tmp, FILE)


def slept(hours: float = 24) -> dict:
    """Time asleep in the last `hours`, and the longest stretch."""
    now, total, best = time.time(), 0.0, None
    since = now - hours * 3600
    for r in _load():
        a, b = max(r["from"], since), min(r["to"], now)
        if b > a:
            total += b - a
            if not best or r["to"] - r["from"] > best["to"] - best["from"]:
                best = r
    out = {"hours": round(total / 3600, 1), "longest": 0, "from": "", "to": ""}
    if best:
        out.update(longest=round((best["to"] - best["from"]) / 3600, 1),
                   **{k: time.strftime("%a %d %b %H:%M", time.localtime(best[k])) for k in ("from", "to")})
    return out


def _watch():
    global _since, _last
    beats = 0
    while True:
        time.sleep(5)
        now = time.time()
        if now - _last > GAP:
            _since = now
            try:
                record(_last, now)
            except (OSError, KeyError, TypeError):
                pass
            if mode() != "off":                        # a real wake on battery can sleep again within the minute it takes to settle
                cmd = osinfo.keep_awake_cmd(os.getpid(), battery=True, seconds=SETTLE + 60)
                if cmd:
                    _spawn(cmd)
        _last = now
        beats += 1
        if beats % 6 == 0:
            _apply_mode()


def start() -> None:
    global _since, _last
    _since = _last = time.time()
    _apply_mode()
    threading.Thread(target=_watch, daemon=True, name="awake").start()
