"""Roles you can hire from: the kit's (core/roles.json), the community's (core/roles.d/<id>/), and your own
(~/Staff/team/roles/<id>/), made from a crew member you trained ("Save as a role") or imported from someone else.

    import rolebook
    rolebook.all_roles()                     # what the hiring page shows; your own first
    rolebook.save_role("suoo", "Channel manager", by="Basem")   # a trained crew member → a role, with its skills
    rolebook.apply_template("zain", "channel-manager")          # a new hire starts with that role's skills and rules
    rolebook.export_role("channel-manager", "/path/out")        # a folder anyone can import or contribute
    rolebook.import_role("/path/in")

A role folder: role.json (title, role, scope, abilities, model, try, connectors, rules) and skills/<name>/SKILL.md.
Nothing private travels: no notes, no memory, no files, no access grants, no tokens; only the job and the
know-how. Check the rules text before sharing a role outside your team.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil

import engine

KIT_ROLES = os.path.join(engine.CORE, "roles.json")
COMMUNITY = os.path.join(engine.CORE, "roles.d")
MINE = os.path.join(engine.HOME, "team", "roles")


class RoleError(ValueError):
    pass


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _folder_roles(root, source):
    out = []
    for f in sorted(glob.glob(os.path.join(root, "*", "role.json"))):
        try:
            r = _load(f)
        except (OSError, ValueError):
            continue
        r.setdefault("id", os.path.basename(os.path.dirname(f)))
        r["source"] = source
        r["template"] = os.path.basename(os.path.dirname(f))
        r.setdefault("names", [])
        r.setdefault("blurb", r.get("title", ""))
        r.setdefault("abilities", None)
        r.setdefault("try", [])
        out.append(r)
    return out


def all_roles() -> dict:
    d = _load(KIT_ROLES)
    community = _folder_roles(COMMUNITY, "community")
    mine = _folder_roles(MINE, "yours")
    d["roles"] = mine + d["roles"] + community
    extra = [r["id"] for r in mine + community]
    for s in d["situations"]:
        if s["id"] == "other":
            s["jobs"] = [r["id"] for r in mine] + s["jobs"] + [r["id"] for r in community]
    if mine:
        d["situations"].insert(0, {"id": "yours", "title": "Your own roles", "blurb": "Roles you saved from crew members you trained.",
                                   "jobs": [r["id"] for r in mine]})
    d["extra"] = extra
    return d


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "role"


def _rules(md: str) -> str:
    m = re.search(r"\n## Role-specific rules\n(.*?)(?=\n## |\Z)", md, re.S)
    text = (m.group(1).strip() if m else "")
    return "" if text.startswith("_Your supervisor adds rules here") else text


def save_role(emp_id: str, title: str = "", by: str = "owner") -> str:
    """A trained crew member → a role template: its job, abilities and model, its own skills, its role rules and
    the connectors it uses (as suggestions). Not its notes, memory, files or access grants."""
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id)
    if not e:
        raise RoleError("No crew member %r" % emp_id)
    ws = engine.employee(emp_id)["workspace"]
    rid = _slug(title or e["role"])
    dst = os.path.join(MINE, rid)
    os.makedirs(os.path.join(dst, "skills"), exist_ok=True)
    try:
        with open(os.path.join(ws, "CLAUDE.md"), encoding="utf-8") as fh:
            rules = _rules(fh.read())
    except OSError:
        rules = ""
    consent = {"full_autonomy", "act_in_browser"}
    role = {"id": rid, "title": title or e["role"], "role": e["role"], "scope": e.get("scope", ""),
            "abilities": [a for a in e.get("abilities", []) if a not in consent], "model": e.get("model", "sonnet"),
            "names": [], "try": [], "rules": rules, "made_from": "%s (%s), by %s" % (e["name"], emp_id, by),
            "connectors": [c.get("url") for c in (e.get("connectors") or {}).values()]}
    with open(os.path.join(dst, "role.json"), "w", encoding="utf-8") as fh:
        json.dump(role, fh, indent=1, ensure_ascii=False)
    n = 0
    for sk in glob.glob(os.path.join(ws, "skills", "*", "SKILL.md")):
        name = os.path.basename(os.path.dirname(sk))
        shutil.rmtree(os.path.join(dst, "skills", name), ignore_errors=True)
        shutil.copytree(os.path.dirname(sk), os.path.join(dst, "skills", name),
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv"))
        n += 1
    return "Saved \"%s\" as a role with %d skill%s. It's on the hiring page under Your own roles." % (role["title"], n, "" if n == 1 else "s")


def _find(template: str):
    for root in (MINE, COMMUNITY):
        p = os.path.join(root, template)
        if os.path.isfile(os.path.join(p, "role.json")):
            return p
    return None


def apply_template(emp_id: str, template: str) -> None:
    """A new hire starts with the role's skills (as its own, editable) and its rules."""
    src = _find(template)
    if not src:
        return
    ws = engine.employee(emp_id)["workspace"]
    for sk in glob.glob(os.path.join(src, "skills", "*", "SKILL.md")):
        name = os.path.basename(os.path.dirname(sk))
        dst = os.path.join(ws, "skills", name)
        if not os.path.exists(dst):
            shutil.copytree(os.path.dirname(sk), dst)
    rules = _load(os.path.join(src, "role.json")).get("rules", "").strip()
    if rules:
        path = os.path.join(ws, "CLAUDE.md")
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
        md = re.sub(r"(\n## Role-specific rules\n)_Your supervisor adds rules here[^\n]*\n", lambda m: m.group(1) + rules + "\n", md, count=1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)


def export_role(rid: str, out_dir: str) -> str:
    src = _find(rid)
    if not src:
        raise RoleError("No saved role %r" % rid)
    dst = os.path.join(os.path.abspath(out_dir), rid)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


def import_role(path: str) -> str:
    src = os.path.abspath(path)
    if not os.path.isfile(os.path.join(src, "role.json")):
        raise RoleError("%s has no role.json" % src)
    r = _load(os.path.join(src, "role.json"))
    rid = _slug(r.get("id") or r.get("title") or os.path.basename(src))
    dst = os.path.join(MINE, rid)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return "Imported \"%s\". It's on the hiring page under Your own roles." % r.get("title", rid)
