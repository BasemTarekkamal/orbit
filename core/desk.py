"""Orbit's front desk: one Claude app chat for the owner's whole crew, for owners who don't use the panel.

In that chat the owner hires (the same interview as the panel: Claude asks what this job needs, writes the card,
the owner says yes), checks who's doing what, reads what the crew said, pauses or changes someone, and opens any
crew member's own chat. The chat lives in its own folder, ~/Staff/desk (not ~/Staff itself: a CLAUDE.md there
would be read by every crew member's session below it), and works through Orbit's own `orbit` command; hires and
changes go through the running service's panel API, exactly as the panel's buttons do.

    import desk
    desk.ensure()                 # writes ~/Staff/desk/CLAUDE.md and its settings (on every service start)
    desk.open_chat()              # → {"opened", "link", "new"}: the desk chat, or a new one that sets itself up
    desk.guide()                  # → the interview rules, roles, abilities and card format, for the chat
    desk.hire(payload)            # → "Hired Sara (handle sara)…": a card the chat wrote, through the service
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import engine
import osinfo

DIR = os.path.join(engine.HOME, "desk")
STATE = os.path.join(DIR, "state.json")
TEMPLATE = os.path.join(engine.CORE, "desk.md")                # the desk chat's CLAUDE.md, filled in
HELLO = ("Hi Orbit. Set yourself up (your CLAUDE.md says how), then tell me in a few lines who's on my crew, "
         "what they're doing, and what you can do for me here.")


def ensure() -> str:
    """The desk's folder, its CLAUDE.md (from the kit, refreshed) and settings: Orbit's command runs without a
    prompt; the team's secrets can't be read; the registry and crew folders change only through Orbit."""
    os.makedirs(os.path.join(DIR, "cards"), exist_ok=True)
    with open(TEMPLATE, encoding="utf-8") as fh:
        text = fh.read()
    owner = next(iter(engine.registry().get("owners", {}).values()), {}).get("name", "the owner")
    orbit = os.path.join(engine.KIT, "orbit")
    text = text.replace("{orbit}", orbit).replace("{home}", engine.HOME).replace("{owner}", owner).replace("{kit}", engine.KIT)
    _write(os.path.join(DIR, "CLAUDE.md"), text)
    absolute = lambda p: "/" + os.path.realpath(p)              # Claude Code's absolute-path rule form: //path
    settings = {"permissions": {
        "allow": ["Bash(%s *)" % orbit, "Bash(%s)" % orbit, "Bash(orbit *)", "Read(%s/**)" % absolute(engine.HOME),
                  "Write(%s/**)" % absolute(DIR), "Edit(%s/**)" % absolute(DIR)],
        "deny": ["Read(%s/**)" % absolute(engine.SECRETS), "Edit(%s)" % absolute(engine.REGISTRY),
                 "Write(%s)" % absolute(engine.REGISTRY), "Edit(%s/**)" % absolute(os.path.join(engine.HOME, "employees")),
                 "Write(%s/**)" % absolute(os.path.join(engine.HOME, "employees"))]}}
    os.makedirs(os.path.join(DIR, ".claude"), exist_ok=True)
    _write(os.path.join(DIR, ".claude", "settings.local.json"), json.dumps(settings, indent=2))
    return DIR


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def chat() -> str:
    """The desk chat's Claude app session id, once it has recorded itself ('' before)."""
    try:
        with open(STATE, encoding="utf-8") as fh:
            sid = str(json.load(fh).get("chat", ""))
    except (OSError, ValueError, AttributeError):
        return ""
    return sid if re.fullmatch(r"local_[0-9a-f-]{36}", sid) else ""


def link() -> tuple:
    """(link, new): the desk chat in the Claude app, or a new chat in the desk folder whose first message sets it up."""
    ensure()
    sid = chat()
    if sid:
        return "claude://claude.ai/epitaxy/" + sid, False
    q = urllib.parse.urlencode({"folder": DIR, "q": HELLO}, quote_via=urllib.parse.quote)
    return "claude://code/new?" + q, True


def open_chat() -> dict:
    url, new = link()
    opened = osinfo.KIND == "mac" and claude_app() and osinfo.open_url(url)
    return {"opened": bool(opened), "link": url, "new": new, "folder": DIR}


def claude_app() -> bool:
    return any(os.path.isdir(p) for p in ("/Applications/Claude.app", os.path.expanduser("~/Applications/Claude.app")))


# ------------------------------------------------------------------ hiring from the chat
def guide() -> str:
    """Everything the chat needs to run the same interview the panel runs, as plain text."""
    import abilities
    import onboard
    import rolebook
    roles = rolebook.all_roles().get("roles", [])
    lines = ["# Hiring a crew member (the same interview as Orbit's panel)", "",
             "## Asking the questions", onboard.ASK_GUIDE, "",
             "## Writing the card", onboard.CARD_GUIDE, "", onboard.POLICY, "",
             "## Jobs to start from (id: job, what it covers)"]
    lines += ["- %s: %s. %s" % (r["id"], r.get("role", ""), str(r.get("scope", ""))[:160]) for r in roles]
    lines += ["", "## Abilities (id: what it does)"]
    lines += ["- %s: %s" % (a["id"], a.get("description", a.get("name", ""))) for a in abilities.catalog()]
    lines += ["", "## The card file (JSON) for `orbit hire --card <file>`", json.dumps({
        "name": "Sara", "role": "Market researcher", "job": "researcher",
        "card": {"role": "Market researcher", "scope": "2 to 4 sentences, in the owner's words",
                 "responsibilities": ["…", "…"], "first_task": "a real task for today", "plan": ["Day 1: …", "Day 2: …"],
                 "routines": {k: k in ("standup", "eod", "review") for k in onboard.ROUTINES},
                 "abilities": ["web", "fetch"], "access": [{"kind": "sign_in", "what": "…", "why": "…"}],
                 "budget": "regular", "model": "sonnet", "interview": [{"q": "…", "a": "…"}]},
        "autonomy": True, "browser": {"sites": [], "approval": "each"}}, indent=1, ensure_ascii=False),
        "", "`job` is the id of the job they started from (optional). `browser.sites` are the sites they may post "
        "on for the owner, from their own browser window, and `approval` is each, batch or none: only what the owner said."]
    return "\n".join(lines)


def order(kind: str, payload: dict) -> str:
    """One order to the running service, through its panel API (the same path as the panel's buttons)."""
    import panel
    body = json.dumps({"kind": kind, **payload}).encode()
    base = "http://127.0.0.1:%d" % panel.port()
    req = urllib.request.Request(base + "/api/order", data=body, headers={
        "content-type": "application/json", "Origin": base, "Cookie": "sr%d=%s" % (panel.port(), panel.token())})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("message", "")
    except urllib.error.HTTPError as e:
        try:
            raise RuntimeError(json.load(e).get("error") or str(e))
        except ValueError:
            raise RuntimeError(str(e))
    except (urllib.error.URLError, OSError):
        raise RuntimeError("Orbit's service isn't running, so nothing was changed. Start it: orbit start")


def hire(payload: dict) -> str:
    """Hires from a card the chat wrote (see guide()), through the service: the card, abilities, routines, budget,
    the first-day task, then Full autonomy and the browser sites the owner chose. → a short report."""
    import onboard
    import rolebook
    name = str(payload.get("name") or "").strip()
    card = onboard.normalize(payload.get("card") or {})
    role = str(payload.get("role") or card.get("role") or "").strip()
    if not name or not role:
        raise ValueError("The card needs a name and a role")
    card.setdefault("interview", payload.get("card", {}).get("interview") or [])
    routines = [k for k, on in card["routines"].items() if on]
    job = str(payload.get("job") or "")
    template = next((r.get("template") for r in rolebook.all_roles().get("roles", []) if r.get("id") == job), None)
    owner = next(iter(engine.registry().get("owners", {}).values()), {}).get("name", "")
    msg = order("hire", {"name": name, "role": card.get("role") or role, "scope": card.get("scope") or payload.get("scope", ""),
                         "supervisor": owner, "model": card["model"], "template": template,
                         "abilities": ["telegram", "team_room"] + card["abilities"] + routines, "card": card})
    m = re.search(r"/([a-z0-9][a-z0-9-]*)", msg)
    handle = m.group(1) if m else ""
    notes = []
    if handle and payload.get("autonomy", True):
        order("set_autonomy", {"employee_id": handle, "on": True})
        notes.append("Full autonomy on")
    browser = payload.get("browser") or {}
    sites = [str(s).strip().lower() for s in browser.get("sites") or [] if str(s).strip()]
    if handle and sites:
        approval = browser.get("approval") if browser.get("approval") in ("each", "batch", "none") else "each"
        order("set_browser", {"employee_id": handle, "sites": sites, "approval": approval})
        notes.append("may post for you on %s from its own browser window (%s)" % (", ".join(sites), {"each": "asks each time", "batch": "asks once per batch", "none": "doesn't ask"}[approval]))
    return "Hired %s (handle %s). %s%sTheir first task has started. Next: `orbit open %s` opens their own chat%s." % (
        name, handle or "?", "; ".join(notes), ". " if notes else "", handle or "<handle>",
        ", and `orbit browser %s` opens their browser window for you to sign them in" % (handle or "<handle>") if sites else "")
