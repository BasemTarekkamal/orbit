"""Roles you can hire from: the kit's (core/roles.json), the community's (core/roles.d/<id>/), and your own
(~/Staff/team/roles/<id>/), made from a crew member you trained ("Share") or imported from someone else.

    import rolebook
    rolebook.all_roles()                     # what the hiring page shows; your own first
    d = rolebook.distill("sara")             # a shareable draft: job, rules, skills and experience, private bits taken out
    rolebook.save_role("sara", d["title"], by="Alex", draft=d)  # → a role, with its skills and EXPERIENCE
    rolebook.package("channel-manager")      # → one .orbit-role.zip file anyone can import
    rolebook.import_role("/path/or/https/link.zip")
    rolebook.publish("channel-manager", by="Alex")   # → a pull request to the Orbit community (or the page to send it)
    rolebook.apply_template("zain", "channel-manager")          # a new hire starts with that role's skills, rules, experience

A role folder: role.json (title, role, scope, abilities, model, try, connectors, rules, trained_by, stats),
experience.md and skills/<name>/SKILL.md. Nothing private travels: no notes, memory, files, access grants or
tokens; the experience and skills are rewritten without names, accounts, links or the business's numbers, and
the owner sees every word before anything is saved or sent.
"""
from __future__ import annotations

import datetime as dt
import glob
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

import engine

KIT_ROLES = os.path.join(engine.CORE, "roles.json")
COMMUNITY = os.path.join(engine.CORE, "roles.d")
MINE = os.path.join(engine.HOME, "team", "roles")
OFFICIAL = "BasemTarekkamal/orbit"
MAX_ZIP = 5_000_000


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
        r["experience"] = _read(os.path.join(os.path.dirname(f), "experience.md"), 6000)
        r["skills_in"] = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(os.path.dirname(f), "skills", "*", "SKILL.md")))
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
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > 40:                                       # cut at a word, not inside one
        s = s[:41].rsplit("-", 1)[0] if "-" in s[:41] else s[:40]
    return s.strip("-") or "role"


def _rules(md: str) -> str:
    m = re.search(r"\n## Role-specific rules\n(.*?)(?=\n## |\Z)", md, re.S)
    text = (m.group(1).strip() if m else "")
    return "" if text.startswith("_Your supervisor adds rules here") else text


def _read(path, limit=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read() if limit is None else fh.read(limit)
    except OSError:
        return ""


def stats(emp_id: str) -> dict:
    """How much a crew member has learned: days on the job, lessons, its own skills."""
    e = engine.registry().get("employees", {}).get(emp_id) or {}
    ws = engine.employee(emp_id)["workspace"]
    lessons = len(re.findall(r"^\s*-\s+\S", _read(os.path.join(ws, "LESSONS.md")), re.M))
    skills = len(glob.glob(os.path.join(ws, "skills", "*", "SKILL.md")))
    try:
        days = (dt.date.today() - dt.date.fromisoformat(str(e.get("hired"))[:10])).days
    except ValueError:
        days = 0
    return {"days": max(days, 0), "lessons": lessons, "skills": skills}


DISTILL_SCHEMA = {
    "type": "object", "required": ["title", "summary", "experience", "rules", "skills", "removed"],
    "properties": {
        "title": {"type": "string", "description": "The role's name, generic (\"YouTube Shorts channel manager\")"},
        "summary": {"type": "string", "description": "One line: what a crew member hired from this role is good at"},
        "experience": {"type": "string", "description": "EXPERIENCE.md in markdown"},
        "rules": {"type": "string", "description": "The role-specific rules, generic, as markdown bullets"},
        "skills": {"type": "array", "items": {"type": "object", "required": ["name", "text"],
                                               "properties": {"name": {"type": "string"}, "text": {"type": "string"}}}},
        "removed": {"type": "array", "items": {"type": "string"}, "maxItems": 12,
                    "description": "What kinds of private things you took out (\"the owner's name\", \"the channel's name\")"}}}

DISTILL_SYSTEM = """You prepare a trained AI crew member's know-how so its owner can share it with other people who
hire the same kind of role for a DIFFERENT business. Everything you write will be public.

Write:
- experience: EXPERIENCE.md, the hard-won know-how: what works and what doesn't in this job, the methods,
  the quality bar, the mistakes to avoid and the rules learned from feedback, grouped under short headings,
  as bullets that each state a rule and, briefly, why. Generalise every lesson ("the owner wanted a voiceover
  on every Short" -> "Every Short ships with a voiceover; silent Shorts were rejected"). 300-900 words.
- rules: the role-specific rules, generic.
- skills: each skill given to you, rewritten the same way, keeping its frontmatter (name, description) and
  its method. Keep the skill's name.
- removed: the kinds of private things you took out.

Take out everything private: people's names (owners, colleagues, customers), the business's and brand's names,
channel and account names, handles, emails, phone numbers, links to their own pages, file paths, dates tied
to them, their internal numbers (revenue, subscribers, views, prices they charge), passwords or tokens, and
anything the text calls private or secret. Public facts (platform rules, published thresholds, public
benchmarks) may stay. Never invent experience that isn't in the input. Write in the language of the input."""


def distill(emp_id: str) -> dict:
    """A shareable draft of what a crew member knows, with everything private taken out by Claude (one call on
    the owner's plan, no tools). Nothing is saved or sent: the owner reads and edits it first."""
    import onboard
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id)
    if not e:
        raise RoleError("No crew member %r" % emp_id)
    ws = engine.employee(emp_id)["workspace"]
    skills = []
    for sk in sorted(glob.glob(os.path.join(ws, "skills", "*", "SKILL.md"))):
        text = _read(sk)
        if len(text) <= 12000:
            skills.append({"name": os.path.basename(os.path.dirname(sk)), "text": text})
    parts = ["Job: %s. Scope: %s" % (e["role"], e.get("scope", "")),
             "Role rules:\n" + (_rules(_read(os.path.join(ws, "CLAUDE.md"))) or "(none)"),
             "LESSONS.md:\n" + _read(os.path.join(ws, "LESSONS.md"), 20000),
             "PLAN.md (the strategy and its reviews):\n" + _read(os.path.join(ws, "PLAN.md"), 8000),
             "EXPERIENCE.md it started with:\n" + (_read(os.path.join(ws, "EXPERIENCE.md"), 8000) or "(none)"),
             "Its own skills:\n" + ("\n\n".join("### skill %s\n%s" % (x["name"], x["text"]) for x in skills) or "(none)")]
    out = onboard._ask(DISTILL_SYSTEM, "\n\n---\n\n".join(parts), DISTILL_SCHEMA, timeout=300)
    names = {x["name"] for x in skills}
    out["skills"] = [x for x in out.get("skills") or [] if x.get("name") in names]
    out["stats"] = stats(emp_id)
    out["trained_by"] = e.get("supervisor") or ""
    out["role"] = e["role"]
    out.pop("_tokens", None)
    return out


def save_role(emp_id: str, title: str = "", by: str = "owner", draft: dict = None) -> str:
    """A trained crew member → a role: its job, abilities and model, its skills, its role rules, its experience
    and the connectors it uses (as suggestions). With a `draft` (from distill, as the owner edited it), the
    rewritten, private-free versions are what's saved. Never its notes, memory, files or access grants."""
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id)
    if not e:
        raise RoleError("No crew member %r" % emp_id)
    ws = engine.employee(emp_id)["workspace"]
    draft = draft or {}
    title = (title or draft.get("title") or e["role"]).strip()[:80]
    rid = _slug(title)
    dst = os.path.join(MINE, rid)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.join(dst, "skills"), exist_ok=True)
    rules = draft["rules"] if "rules" in draft else _rules(_read(os.path.join(ws, "CLAUDE.md")))
    consent = {"full_autonomy", "act_in_browser"}
    st = stats(emp_id)
    role = {"id": rid, "title": title, "role": e["role"], "scope": e.get("scope", "") if not draft else draft.get("summary", ""),
            "blurb": draft.get("summary", ""), "abilities": [a for a in e.get("abilities", []) if a not in consent],
            "model": e.get("model", "sonnet"), "names": [], "try": [], "rules": rules,
            "trained_by": (draft.get("trained_by") or by or "").strip()[:60], "stats": st,
            "shared_on": dt.date.today().isoformat(),
            "connectors": [c.get("url") for c in (e.get("connectors") or {}).values()]}
    with open(os.path.join(dst, "role.json"), "w", encoding="utf-8") as fh:
        json.dump(role, fh, indent=1, ensure_ascii=False)
    if (draft.get("experience") or "").strip():
        with open(os.path.join(dst, "experience.md"), "w", encoding="utf-8") as fh:
            fh.write(draft["experience"].strip() + "\n")
    n = 0
    if draft:
        for sk in draft.get("skills") or []:
            name = _slug(sk.get("name"))
            if not (sk.get("text") or "").strip():
                continue
            os.makedirs(os.path.join(dst, "skills", name), exist_ok=True)
            with open(os.path.join(dst, "skills", name, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write(sk["text"].strip() + "\n")
            n += 1
    else:
        for sk in glob.glob(os.path.join(ws, "skills", "*", "SKILL.md")):
            name = os.path.basename(os.path.dirname(sk))
            shutil.copytree(os.path.dirname(sk), os.path.join(dst, "skills", name),
                            ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv"))
            n += 1
    reg = engine.registry()
    reg["employees"][emp_id]["shared_as"] = rid
    engine.save_registry(reg, "%s saved as role %s" % (emp_id, rid))
    return "Saved \"%s\" as a role with %d skill%s%s. It's on the hiring page under Your own roles." % (
        title, n, "" if n == 1 else "s", " and its experience" if os.path.exists(os.path.join(dst, "experience.md")) else "")


def _find(template: str):
    for root in (MINE, COMMUNITY):
        p = os.path.join(root, template)
        if os.path.isfile(os.path.join(p, "role.json")):
            return p
    return None


def apply_template(emp_id: str, template: str) -> None:
    """A new hire starts with the role's skills (as its own, editable), its rules and its experience."""
    src = _find(template)
    if not src:
        return
    ws = engine.employee(emp_id)["workspace"]
    xp = os.path.join(src, "experience.md")
    if os.path.isfile(xp) and not os.path.exists(os.path.join(ws, "EXPERIENCE.md")):
        r = _load(os.path.join(src, "role.json"))
        head = "# EXPERIENCE: what the crew member this role was trained on learned%s\n\n" % (
            " (trained by %s)" % r["trained_by"] if r.get("trained_by") else "")
        with open(os.path.join(ws, "EXPERIENCE.md"), "w", encoding="utf-8") as fh:
            fh.write(head + _read(xp))
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


def package(rid: str) -> str:
    """One file anyone can import: <rid>.orbit-role.zip next to the role (role.json, experience.md, skills/)."""
    src = _find(rid)
    if not src:
        raise RoleError("No saved role %r" % rid)
    out = os.path.join(MINE, "%s.orbit-role.zip" % rid)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, names in os.walk(src):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".venv")]
            for n in names:
                if n.startswith("."):
                    continue
                p = os.path.join(base, n)
                z.write(p, os.path.join(rid, os.path.relpath(p, src)))
    return out


def _unzip(data: bytes, into: str) -> str:
    """A role zip → its folder under `into`. Refuses paths outside it, links, and anything too big."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RoleError("That isn't a role file (.orbit-role.zip)")
    infos = z.infolist()
    if len(infos) > 400 or sum(i.file_size for i in infos) > 20_000_000:
        raise RoleError("That role file is too big")
    for i in infos:
        name = i.filename
        if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or (i.external_attr >> 16) & 0o170000 == 0o120000:
            raise RoleError("That role file has an unsafe path (%s)" % name[:80])
    z.extractall(into)
    hits = [os.path.dirname(p) for p in glob.glob(os.path.join(into, "**", "role.json"), recursive=True)]
    if not hits:
        raise RoleError("That file has no role.json, so it isn't an Orbit role")
    return min(hits, key=len)


def import_role(path: str = "", data: bytes = None) -> str:
    """A role from a folder, a .orbit-role.zip (a path, its bytes, or an https link to it)."""
    tmp = tempfile.mkdtemp(prefix="orbit-role-")
    try:
        if data is None and path.startswith("https://"):
            req = urllib.request.Request(path, headers={"User-Agent": "orbit"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read(MAX_ZIP + 1)
            if len(data) > MAX_ZIP:
                raise RoleError("That role file is over 5 MB")
        elif data is None and path.startswith("http"):
            raise RoleError("Use an https link")
        if data is None and os.path.isfile(path):
            with open(path, "rb") as fh:
                data = fh.read(MAX_ZIP + 1)
        src = _unzip(data, tmp) if data is not None else os.path.abspath(path)
        if not os.path.isfile(os.path.join(src, "role.json")):
            raise RoleError("%s has no role.json" % (path or "That file"))
        try:
            r = _load(os.path.join(src, "role.json"))
        except ValueError:
            raise RoleError("Its role.json is broken")
        if not isinstance(r, dict) or not (r.get("title") or r.get("role")):
            raise RoleError("Its role.json has no title")
        rid = _slug(r.get("id") or r.get("title") or os.path.basename(src))
        dst = os.path.join(MINE, rid)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        r["id"] = rid
        with open(os.path.join(dst, "role.json"), "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=1, ensure_ascii=False)
        return "Added \"%s\"%s. It's on the hiring page under Your own roles: everything it brings (rules, skills, experience) shows before you hire." % (
            r.get("title", rid), " (trained by %s)" % r["trained_by"] if r.get("trained_by") else "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _gh(*args, cwd=None, timeout=120):
    return subprocess.run(["gh", *args], capture_output=True, text=True, cwd=cwd, timeout=timeout)


def publish(rid: str, by: str = "owner") -> dict:
    """Offers a saved role to everyone: a pull request adding it to the Orbit community (core/roles.d), made with
    the owner's own GitHub sign-in when the gh tool has one; reviewers check it is generic before merging, and it
    reaches every Orbit with the next update. Without gh: the file plus the page where they send it.
    → {"url", "how", "pr": bool}"""
    src = _find(rid)
    if not src:
        raise RoleError("No saved role %r" % rid)
    r = _load(os.path.join(src, "role.json"))
    zpath = package(rid)
    title = "Share a role: %s" % r.get("title", rid)
    body = ("A role trained in Orbit, to add to core/roles.d/%s.\n\nTrained by: %s\nOn the job: %s days, %s lessons, %s skills\n\n"
            "%s\n\nThe role file is attached (%s)." % (rid, r.get("trained_by") or by, (r.get("stats") or {}).get("days", "?"),
                                                      (r.get("stats") or {}).get("lessons", "?"), (r.get("stats") or {}).get("skills", "?"),
                                                      r.get("blurb") or r.get("scope", ""), os.path.basename(zpath)))
    issue = "https://github.com/%s/issues/new?%s" % (OFFICIAL, urllib.parse.urlencode(
        {"template": "share-a-role.yml", "title": title, "role": rid, "trained_by": r.get("trained_by") or by}))
    fallback = {"url": issue, "pr": False, "file": zpath,
                "how": "Your role file is ready. On the page that opens, drag %s in and press Submit. Reviewers check "
                       "it and it reaches every Orbit with the next update." % os.path.basename(zpath)}
    if not shutil.which("gh") or _gh("auth", "status").returncode != 0:
        return fallback
    try:
        me = _gh("api", "user", "--jq", ".login").stdout.strip()
        owner = OFFICIAL.split("/")[0]
        if me.lower() != owner.lower():
            _gh("repo", "fork", OFFICIAL, "--clone=false")
        repo = OFFICIAL if me.lower() == owner.lower() else "%s/%s" % (me, OFFICIAL.split("/")[1])
        work = tempfile.mkdtemp(prefix="orbit-publish-")
        try:
            if _gh("repo", "clone", repo, work, "--", "--depth", "1", "-q", timeout=300).returncode != 0:
                return fallback
            branch = "role/%s" % rid
            subprocess.run(["git", "checkout", "-qb", branch], cwd=work, check=True)
            dst = os.path.join(work, "core", "roles.d", rid)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".*", "*.zip"))
            subprocess.run(["git", "add", "-A"], cwd=work, check=True)
            subprocess.run(["git", "commit", "-qm", "roles: %s (trained by %s)" % (r.get("title", rid), r.get("trained_by") or by)],
                           cwd=work, check=True)
            subprocess.run(["git", "push", "-qu", "origin", branch, "--force"], cwd=work, check=True, timeout=300,
                           capture_output=True)
            pr = _gh("pr", "create", "--repo", OFFICIAL, "--head", "%s:%s" % (me, branch), "--title", title,
                     "--body", body.replace("The role file is attached", "Files in core/roles.d/" + rid), cwd=work)
            url = (pr.stdout.strip().splitlines() or [""])[-1]
            if not url.startswith("https://"):
                return fallback
            return {"url": url, "pr": True, "file": zpath,
                    "how": "Sent for review as a pull request. When it's merged, every Orbit gets the role with the next update."}
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except (subprocess.SubprocessError, OSError):
        return fallback


def share_nudge() -> list:
    """Crew members worth sharing, once each: a week or more on the job and real know-how (8+ lessons or 2+ of
    their own skills), never shared or offered before. → [(emp_id, stats)], marked as offered."""
    reg = engine.registry()
    out = []
    for k, e in reg.get("employees", {}).items():
        if e.get("status") == "retired" or e.get("share_offered") or e.get("shared_as"):
            continue
        st = stats(k)
        if st["days"] >= 7 and (st["lessons"] >= 8 or st["skills"] >= 2):
            out.append((k, st))
    if out:
        reg = engine.registry()
        for k, _ in out:
            reg["employees"][k]["share_offered"] = dt.date.today().isoformat()
        engine.save_registry(reg, "offered to share %s" % ", ".join(k for k, _ in out))
    return out
