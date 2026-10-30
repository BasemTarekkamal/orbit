"""Hiring, pausing and retiring employees. Used by the `orbit` command, the control panel and staffd.

    import hire
    emp_id = hire.hire("Sara", "Legal researcher", "Company law and contracts", supervisor="Alex")
    hire.set_status("sara", "paused")      # active | paused | retired (folder and memory are kept)

A new hire gets a folder from templates/, the shared handbook, and every ability the catalog turns
on by default (or the super-agent preset), so they can do what the others do on day one.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess

import abilities
import engine

TEMPLATES = os.path.join(engine.KIT, "templates")
STATUS = ("active", "paused", "retired")


class HireError(ValueError):
    pass


def _write_new(path, text):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def handle_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def directory(reg=None):
    """team/DIRECTORY.md: who's who, read by every employee."""
    reg = reg or engine.registry()
    lines = ["# Team directory", "", "Written by the harness. Ask a colleague with `staff-bus ask <handle> \"…\"`.", "",
             "| Handle | Name | Role | Scope | Supervisor | Since |", "|---|---|---|---|---|---|"]
    for o in reg.get("owners", {}).values():
        lines.append("| — | %s | owner (human) | everything | — | — |" % o["name"])
    for k, e in reg.get("employees", {}).items():
        if e.get("status") == "retired":
            continue
        lines.append("| %s | %s | %s | %s | %s | %s |" % (k, e["name"], e["role"], e.get("scope", "")[:90].replace("|", "/"),
                                                         e.get("supervisor"), e.get("hired", "")))
    os.makedirs(os.path.join(engine.HOME, "team"), exist_ok=True)
    with open(os.path.join(engine.HOME, "team", "DIRECTORY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def hire(name: str, role: str, scope: str = "", supervisor: str = "", emp_id: str = None,
         preset: str = "default", picked: list = None, model: str = None, domains: list = None) -> str:
    name, role, scope = name.strip()[:60], role.strip()[:120], scope.strip()[:2000]
    if not name or not role:
        raise HireError("A name and a role are needed")
    reg = engine.registry()
    emp_id = emp_id or handle_for(name)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", emp_id or ""):
        raise HireError("Give a handle in Latin letters, digits or dashes for %r" % name)
    if emp_id in ("team", "all", "staff", "help", "start", "talk", "listen", "now", "stop"):
        raise HireError("%r is reserved; pick another handle" % emp_id)
    current = reg.get("employees", {}).get(emp_id)
    if current and current.get("status") != "retired":
        raise HireError("%s already works here" % emp_id)
    sup = engine.owner_name(supervisor) if supervisor else next(iter(reg.get("owners", {}).values()), {}).get("name")
    if not sup:
        raise HireError("The supervisor must be an owner (%s). New here? Run `orbit setup` first." % (", ".join(o["name"] for o in reg.get("owners", {}).values()) or "none yet"))
    ws = os.path.join(engine.HOME, "employees", emp_id)
    today = dt.date.today().isoformat()
    fill = {"{name}": name, "{role}": role, "{scope}": scope or "(to be set by the supervisor)",
            "{supervisor}": sup, "{id}": emp_id, "{today}": today, "{team}": reg.get("team_name", "the team"),
            "{kit}": engine.KIT}
    for src in sorted(os.listdir(TEMPLATES)):
        with open(os.path.join(TEMPLATES, src), encoding="utf-8") as fh:
            text = fh.read()
        for k, v in fill.items():
            text = text.replace(k, v)
        _write_new(os.path.join(ws, src.replace("__", "/")), text)
    profile = {"id": emp_id, "name": name, "role": role, "network_domains": list(domains or [])}
    _write_new(os.path.join(ws, "profile.json"), json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    for d in ("state", "notes", "tools", "research", "growth/scout", "evals/results"):
        os.makedirs(os.path.join(ws, d), exist_ok=True)
    if not os.path.isdir(os.path.join(ws, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=ws, capture_output=True)
    entry = {"name": name, "role": role, "scope": scope, "supervisor": sup, "hired": today, "status": "active",
             "abilities": abilities.validate(picked if picked is not None else abilities.preset(preset))}
    if model:
        entry["model"] = model
    reg.setdefault("employees", {})[emp_id] = entry
    engine.save_registry(reg, "hire: %s (%s), supervisor %s" % (name, role, sup))
    directory(reg)
    return emp_id


def set_status(emp_id: str, status: str) -> None:
    if status not in STATUS:
        raise HireError("Unknown status %r" % status)
    reg = engine.registry()
    if emp_id not in reg.get("employees", {}):
        raise HireError("No employee %r" % emp_id)
    reg["employees"][emp_id]["status"] = status
    reg["employees"][emp_id][status + "_on"] = dt.date.today().isoformat()
    engine.save_registry(reg, "%s: %s" % (status, emp_id))
    directory(reg)


def set_abilities(emp_id: str, ids: list, by: str = "owner"):
    """Saves the ticks; returns (+added names, −removed names)."""
    reg = engine.registry()
    if emp_id not in reg.get("employees", {}) or reg["employees"][emp_id].get("status") == "retired":
        raise HireError("No employee %r" % emp_id)
    before = abilities.effective(emp_id)
    reg["employees"][emp_id]["abilities"] = abilities.validate(ids)
    engine.save_registry(reg, "abilities: %s (by %s)" % (emp_id, by))
    after, names = abilities.effective(emp_id), abilities.by_id()
    return ([names[i]["name"] for i in sorted(after - before)], [names[i]["name"] for i in sorted(before - after)])


def set_field(emp_id: str, field: str, value) -> None:
    """Owner-editable settings: model, effort, scope, supervisor."""
    if field not in ("model", "effort", "scope", "supervisor", "role"):
        raise HireError("Can't change %r" % field)
    reg = engine.registry()
    if emp_id not in reg.get("employees", {}):
        raise HireError("No employee %r" % emp_id)
    if field == "supervisor":
        value = engine.owner_name(value) or ""
        if not value:
            raise HireError("The supervisor must be an owner")
    if field == "model" and value not in ("opus", "sonnet", "haiku", ""):
        raise HireError("Model must be opus, sonnet or haiku")
    if field == "effort" and value not in ("low", "medium", "high", ""):
        raise HireError("Effort must be low, medium or high")
    if value in ("", None):
        reg["employees"][emp_id].pop(field, None)
    else:
        reg["employees"][emp_id][field] = value
    engine.save_registry(reg, "%s: %s → %s" % (emp_id, field, value))
    directory(reg)
