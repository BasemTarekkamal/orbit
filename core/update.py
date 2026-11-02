"""Updates: Orbit tells the owner when a new release is out and updates only when they say so.

    import update
    update.check()        # once a day from staffd: the newest release of the official repository
    update.status()       # what the panel shows: current, latest, what's new, can_update, why_not
    update.apply()        # the owner pressed Update: fast-forward to that release, then restart the service

Safe by design: releases only (tagged versions with notes, not every push), only from the official
repository (OFFICIAL), never automatically, and only a fast-forward of an unmodified copy: a fork or a
copy with local changes is told what's new and how to update by hand, never changed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import engine

OFFICIAL = "BasemTarekkamal/orbit"
STATE = os.path.join(engine.HOME, "team", "update.json")
DAY = 86400


def current() -> str:
    try:
        with open(os.path.join(engine.KIT, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "0.0.0"


def _key(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def _git(*args, timeout=60):
    return subprocess.run(["git", "-C", engine.KIT] + list(args), capture_output=True, text=True, timeout=timeout)


def official_copy() -> bool:
    url = _git("remote", "get-url", "origin").stdout.strip().lower()
    return bool(re.search(r"github\.com[:/]%s(\.git)?/?$" % re.escape(OFFICIAL.lower()), url))


def _load() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, STATE)


def check(force: bool = False) -> dict:
    """Asks GitHub for the official repository's newest release (no login; once a day)."""
    d = _load()
    if not force and time.time() - d.get("checked", 0) < DAY:
        return d
    d["checked"] = time.time()
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % OFFICIAL,
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "orbit-update-check"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.loads(r.read().decode())
        d.update({"latest": rel.get("tag_name", "").lstrip("v"), "notes": (rel.get("body") or "")[:4000],
                  "url": rel.get("html_url", ""), "published": rel.get("published_at", ""), "error": ""})
    except Exception as e:  # noqa: BLE001
        d["error"] = str(e)[:200]
    _save(d)
    return d


def status() -> dict:
    d = _load()
    cur, latest = current(), d.get("latest") or ""
    newer = bool(latest) and _key(latest) > _key(cur)
    why = ""
    if newer:
        if not official_copy():
            why = "This copy isn't the official one (a fork), so update it yourself: git pull from where you got it."
        elif _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            why = "This copy has local changes, so it won't be overwritten. Keep them safe, then: git -C ~/orbit pull"
    return {"current": cur, "latest": latest, "newer": newer, "notes": d.get("notes", ""), "url": d.get("url", ""),
            "can_update": newer and not why, "why_not": why, "dismissed": d.get("dismissed") == latest}


def announce_once(version: str) -> bool:
    """True the first time a version is seen, so the team room hears about each release once."""
    d = _load()
    if d.get("announced") == version:
        return False
    d["announced"] = version
    _save(d)
    return True


def dismiss() -> None:
    d = _load()
    d["dismissed"] = d.get("latest")
    _save(d)


def apply() -> str:
    """Fast-forwards to the newest release, then restarts the service in the background (the panel goes down
    with it for a few seconds and comes back on the new version)."""
    s = status()
    if not s["newer"]:
        return "Already up to date (%s)." % s["current"]
    if not s["can_update"]:
        raise RuntimeError(s["why_not"])
    tag = "v" + s["latest"]
    r = _git("fetch", "--quiet", "--tags", "origin", timeout=180)
    if r.returncode != 0:
        raise RuntimeError("Couldn't reach GitHub: %s" % (r.stderr.strip()[-200:] or "fetch failed"))
    r = _git("merge", "--ff-only", "--quiet", tag)
    if r.returncode != 0:
        raise RuntimeError("Couldn't move to %s without touching your copy: %s" % (tag, r.stderr.strip()[-200:]))
    subprocess.Popen([sys.executable, os.path.join(engine.KIT, "orbit"), "restart"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     env=dict(os.environ, STAFFROOM_HOME=engine.HOME))
    return "Updated to %s. Orbit restarts now; the panel is back in a few seconds." % s["latest"]
