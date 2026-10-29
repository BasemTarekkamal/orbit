"""Abilities: what each employee may do. The catalog is core/abilities.json; the ticks are in
~/Staff/staff.json (employees.<id>.abilities), set in the control panel or with `staff abilities`.

  effective = locked ∪ chosen        chosen missing → the catalog defaults

The engine turns tools, gateway commands and skills on or off from this; staffd gates Telegram,
voice, files, meetings, reminders, the team room and which routines run with has(). Harness-owned:
employees can read it, not change it. Python 3.9 compatible.
"""
from __future__ import annotations

import json
import os

import engine

CATALOG_F = os.path.join(engine.CORE, "abilities.json")


def _load() -> dict:
    with open(CATALOG_F, encoding="utf-8") as fh:
        return json.load(fh)


def catalog() -> list:
    return _load()["abilities"]


def groups() -> list:
    return _load()["groups"]


def by_id() -> dict:
    return {a["id"]: a for a in catalog()}


def preset(name: str) -> list:
    """'default' or 'super' → the ability ids it ticks."""
    return [a["id"] for a in catalog() if not a.get("locked") and (name == "super" or a.get("default"))]


def chosen(emp_id: str) -> list:
    e = engine.registry().get("employees", {}).get(emp_id, {})
    return list(e["abilities"]) if "abilities" in e else preset("default")


def effective(emp_id: str) -> set:
    cat = by_id()
    return {k for k, a in cat.items() if a.get("locked")} | {k for k in chosen(emp_id) if k in cat}


def has(emp_id: str, ability: str) -> bool:
    return ability in effective(emp_id)


def jobs(emp_id: str) -> list:
    on = effective(emp_id)
    return [a["job"] for a in catalog() if a.get("job") and a["id"] in on]


def tools(emp_id: str):
    """(allow, block) for the engine: Claude tools, plus Bash rules for gateway commands that are off."""
    on = effective(emp_id)
    allow, block = [], []
    for a in catalog():
        (allow if a["id"] in on else block).extend(a.get("tools", []))
        if a["id"] not in on:
            block.extend("Bash(%s *)" % c for c in a.get("commands", []))
    return allow, block


def commands(emp_id: str) -> list:
    """Gateway commands this employee may run outside the sandbox (they enforce their own limits)."""
    on = effective(emp_id)
    return sorted({c for a in catalog() if a["id"] in on for c in a.get("commands", [])})


def skills(emp_id: str) -> list:
    on = effective(emp_id)
    return sorted({s for a in catalog() if a["id"] in on for s in a.get("skills", [])})


def prompt(emp_id: str) -> str:
    on = effective(emp_id)
    cat = catalog()
    yes = [a["name"] for a in cat if a["id"] in on]
    no = [a["name"] for a in cat if a["id"] not in on]
    return ("Your abilities are set by your owners in the control panel (Abilities). On: %s. Off: %s. "
            "If a request needs an ability that's off, say so in one line and that an owner can switch it on "
            "in the control panel; don't work around it." % (", ".join(yes), ", ".join(no) or "none"))


def validate(ids: list) -> list:
    """Cleans a requested set: known and not locked."""
    cat = by_id()
    return sorted({i for i in ids if i in cat and not cat[i].get("locked")})
