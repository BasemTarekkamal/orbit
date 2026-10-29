"""Skills employees learn: the teachable layer on top of the fixed abilities (the locks).

Three places hold skills, each a folder of <name>/SKILL.md (Claude Code's own skill format):
  * the kit's playbooks, core/skills/: read-only, loaded per ability;
  * an employee's own, <workspace>/skills/: what an owner taught them (in chat or in the panel), or
    what they worked out themselves and kept (`staff-skill`, when "Learns skills" is on);
  * the team's, ~/Staff/team/skills/: an employee's skill shared with every colleague.
The engine links all three into the employee's skills bundle before every run, so a new skill loads
on the next run. A kit name beats an own name, an own name beats a team name. A skill is text: it can
describe how to do something, never grant a tool or lift a lock. Harness-owned. Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid

import engine

TEAM_DIR = os.path.join(engine.HOME, "team", "skills")
LOG = os.path.join(engine.HOME, "team", "skills_log.jsonl")      # every learned/taught/shared/removed event
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
MAX_TEXT = 60_000
SECRET_RE = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b|\bapify_api_[A-Za-z0-9]{10,}|\bsk-ant-[A-Za-z0-9_-]{10,}|"
                       r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bghp_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")
HOW = {"learned": "learned a skill", "taught": "was taught a skill", "panel": "was taught a skill in the panel",
       "shared": "shared a skill with the team", "updated": "updated a skill", "removed": "dropped a skill",
       "unshared": "removed a team skill"}

TEMPLATE = """---
name: {name}
description: {description}
---

# {title}

## When to use
{when}

## Steps
1. …

## Checks before you answer
- Every number and claim carries its source link.
- …

## Example
Asked: …
Did: …
"""


class SkillError(ValueError):
    pass


def own_dir(ws: str) -> str:
    return os.path.join(ws, "skills")


def is_kit(name: str) -> bool:
    return os.path.isdir(os.path.join(engine.SKILLS, name))


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ reading and checking
def problem_in(name: str, description: str, body: str, folder: str = None, skeleton_ok: bool = False) -> str:
    """'' when the skill is usable, else one plain line saying what's wrong."""
    if not NAME_RE.match(name or ""):
        return "name must be 2–64 lowercase letters, digits or dashes (tiktok-brand-check)"
    if folder and folder != name:
        return "name (%s) must match its folder (%s)" % (name, folder)
    if len(description or "") < 12:
        return "description too short: say what it does and when to use it, in one or two sentences"
    if len(description) > 1024:
        return "description over 1024 characters"
    if len((body or "").strip()) < 40:
        return "the body is empty: write the steps"
    if len(body) > MAX_TEXT:
        return "over 60,000 characters: split it"
    if SECRET_RE.search(body) or SECRET_RE.search(description):
        return "contains what looks like a token: a skill never holds a secret"
    if not skeleton_ok and re.search(r"^\s*1\.\s*(…|\.\.\.)?\s*$", body, re.M):
        return "step 1 is empty: write the steps, then check again"
    return ""


def check_text(text: str, folder: str = None, skeleton_ok: bool = False) -> dict:
    """SKILL.md text → {"name", "description", "body", "text", "problem"}."""
    out = {"name": "", "description": "", "body": "", "text": text, "problem": ""}
    m = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)$", text or "", re.S)
    if not m:
        out["problem"] = "no front matter: the file starts with ---, then name: …, description: …, then ---"
        return out
    for line in m.group(1).splitlines():
        if line[:1].isspace():
            continue
        k, sep, v = line.partition(":")
        if sep and k.strip().lower() in ("name", "description"):
            out[k.strip().lower()] = " ".join(v.strip().strip("\"'").split())
    out["body"] = m.group(2)
    out["problem"] = problem_in(out["name"], out["description"], out["body"], folder, skeleton_ok)
    return out


def parse(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(MAX_TEXT + 1)
    except OSError:
        return {"name": "", "description": "", "body": "", "text": "", "problem": "missing SKILL.md"}
    return check_text(text, os.path.basename(os.path.dirname(path)))


def meta(d: str) -> dict:
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _meta_write(d: str, m: dict) -> None:
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1, ensure_ascii=False)


def listing(root: str, source: str) -> list:
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        d = os.path.join(root, n)
        if n.startswith(".") or not os.path.isdir(d):
            continue
        p = parse(os.path.join(d, "SKILL.md"))
        out.append({"name": n, "description": p["description"], "problem": p["problem"], "source": source, "path": d,
                    **{k: v for k, v in meta(d).items() if isinstance(v, str)}})
    return out


def kit_list(emp_id: str) -> list:
    import abilities
    out = []
    for n in abilities.skills(emp_id):
        p = parse(os.path.join(engine.SKILLS, n, "SKILL.md"))
        out.append({"name": n, "description": p["description"], "source": "kit", "problem": ""})
    return out


def overview(emp_id: str) -> dict:
    ws = engine.employee(emp_id)["workspace"]
    return {"own": listing(own_dir(ws), "own"), "team": listing(TEAM_DIR, "team"), "kit": kit_list(emp_id)}


def bundle(ws: str, kit_names: list):
    """({name: folder} the engine links for an employee, [(name, why it was skipped)])."""
    links, skipped = {}, []
    for n in kit_names:
        d = os.path.join(engine.SKILLS, n)
        if os.path.isdir(d):
            links[n] = d
    for source, root in (("own", own_dir(ws)), ("team", TEAM_DIR)):
        for s in listing(root, source):
            if s["problem"]:
                skipped.append((s["name"], s["problem"]))
            elif s["name"] in links:
                skipped.append((s["name"], "a %s skill with that name already loads" % ("kit" if is_kit(s["name"]) else "own")))
            else:
                links[s["name"]] = s["path"]
    return links, skipped


# ------------------------------------------------------------------ writing
def event(emp_id: str, name: str, what: str, by: str, note: str = "") -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": uuid.uuid4().hex[:12], "ts": now(), "emp": emp_id, "name": name, "what": what,
                             "by": by, "note": str(note)[:300]}, ensure_ascii=False) + "\n")


def folder(emp_id: str, where: str, name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise SkillError("No skill called %r" % name)
    root = TEAM_DIR if where == "team" else own_dir(engine.employee(emp_id)["workspace"])
    d = os.path.join(root, name)
    if not os.path.isfile(os.path.join(d, "SKILL.md")):
        raise SkillError("No %s skill called %s" % (where, name))
    return d


def create(emp_id: str, name: str, description: str, text: str = "", by: str = "self", how: str = "learned",
           when: str = "", replace: bool = False) -> str:
    """Writes <workspace>/skills/<name>/SKILL.md and meta.json. No text → the skeleton (fill the steps,
    then check). Returns the folder."""
    ws = engine.employee(emp_id)["workspace"]
    name = (name or "").strip().lower()
    description = " ".join((description or "").split())
    if not NAME_RE.match(name):
        raise SkillError("The name must be 2–64 lowercase letters, digits or dashes, like tiktok-brand-check")
    if is_kit(name):
        raise SkillError("'%s' is one of the kit's own playbooks; pick another name" % name)
    d = os.path.join(own_dir(ws), name)
    if os.path.isfile(os.path.join(d, "SKILL.md")) and not replace:
        raise SkillError("There's already a skill called %s: edit skills/%s/SKILL.md, or drop it first" % (name, name))
    skeleton = not (text or "").strip()
    if skeleton:
        text = TEMPLATE.format(name=name, description=description, title=name.replace("-", " ").capitalize(), when=when or "…")
    elif not text.lstrip().startswith("---"):
        text = "---\nname: %s\ndescription: %s\n---\n\n%s\n" % (name, description, text.strip())
    c = check_text(text, name, skeleton_ok=skeleton)
    if c["problem"]:
        raise SkillError(c["problem"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    _meta_write(d, {"by": by, "how": how, "at": now()})
    event(emp_id, name, how, by, c["description"])
    return d


def read(emp_id: str, where: str, name: str) -> dict:
    if where == "kit":
        if not NAME_RE.match(name or "") or not is_kit(name):
            raise SkillError("No kit playbook called %r" % name)
        c = parse(os.path.join(engine.SKILLS, name, "SKILL.md"))
        return {"name": name, "where": "kit", "description": c["description"], "text": c["text"], "problem": "", "readonly": True}
    d = folder(emp_id, where, name)
    c = parse(os.path.join(d, "SKILL.md"))
    return {"name": name, "where": where, "description": c["description"], "text": c["text"], "problem": c["problem"],
            **{k: v for k, v in meta(d).items() if isinstance(v, str)}}


def save(emp_id: str, where: str, name: str, text: str, by: str) -> str:
    d = folder(emp_id, where, name)
    c = check_text(text, name)
    if c["problem"]:
        raise SkillError(c["problem"])
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    m = meta(d)
    m.update({"updated": now(), "updated_by": by})
    _meta_write(d, m)
    event(emp_id, name, "updated", by, c["description"])
    return "Saved. It loads on the next run."


def share(emp_id: str, name: str, by: str) -> str:
    src = folder(emp_id, "own", name)
    c = parse(os.path.join(src, "SKILL.md"))
    if c["problem"]:
        raise SkillError("Fix it first: " + c["problem"])
    dst = os.path.join(TEAM_DIR, name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    m = meta(dst)
    m.update({"shared_from": emp_id, "shared_by": by, "shared_at": now()})
    _meta_write(dst, m)
    event(emp_id, name, "shared", by, c["description"])
    return "Shared with the team: every employee loads it from their next run."


def remove(emp_id: str, where: str, name: str, by: str) -> str:
    d = folder(emp_id, where, name)
    root = TEAM_DIR if where == "team" else own_dir(engine.employee(emp_id)["workspace"])
    if not os.path.realpath(d).startswith(os.path.realpath(root) + os.sep):
        raise SkillError("Not a skill folder")
    shutil.rmtree(d)
    event(emp_id, name, "removed" if where == "own" else "unshared", by)
    return "Removed."
