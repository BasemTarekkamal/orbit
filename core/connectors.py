"""Connectors: the MCP servers a crew member may use (Notion, Gmail, HubSpot, Canva, QuickBooks…).

    import connectors
    connectors.suggest("suoo")                 # the library's best matches for this crew member's job
    connectors.search("newsletter analytics")  # the library, then the public MCP registry
    connectors.grant("suoo", "notion", by="Basem")   # the owner's yes (panel, chat, or a Yes in Claude)
    connectors.revoke("suoo", "notion", by="Basem")
    connectors.mcp_config(emp)                 # {"mcpServers": {...}} for its runs and Claude sessions

The library is core/connectors.json (remote servers from the official connector directory, matched to roles).
Granting adds the server to the crew member's runs (--mcp-config) and to Claude sessions in its folder (.mcp.json,
pre-approved). The first time, the owner signs in to the service in a Claude session with that crew member;
the sign-in is the owner's, Orbit never sees it. Financial services (money: true) are used read-only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

import engine

LIB = os.path.join(engine.CORE, "connectors.json")
REGISTRY_API = "https://registry.modelcontextprotocol.io/v0/servers"


def library() -> list:
    with open(LIB, encoding="utf-8") as fh:
        return json.load(fh)["connectors"]


def by_id(cid: str):
    return next((c for c in library() if c["id"] == cid), None)


def server_name(c: dict) -> str:
    """The name Claude knows it by (tools are mcp__<name>__…): lowercase letters, digits, dashes."""
    return re.sub(r"[^a-z0-9-]+", "-", (c.get("id") or c.get("name") or "server").lower()).strip("-")[:40] or "server"


def _role_id(emp: dict):
    try:
        with open(os.path.join(engine.CORE, "roles.json"), encoding="utf-8") as fh:
            roles = json.load(fh)["roles"]
    except (OSError, ValueError):
        return None
    low = (emp.get("role") or "").lower()
    return next((r["id"] for r in roles if r.get("role", "").lower() == low), None)


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def suggest(emp_id: str, limit: int = 8) -> list:
    """The library's best matches: the role's own list first, then words in the job that match a connector."""
    emp = engine.registry().get("employees", {}).get(emp_id) or {}
    return for_job(_role_id(emp), "%s %s" % (emp.get("role", ""), emp.get("scope", "")), set((emp.get("connectors") or {}).keys()), limit)


def for_job(rid, text: str, have=frozenset(), limit: int = 8) -> list:
    """Connectors for a job: those listed for its role, then any whose words match the job's description."""
    job = _words(text)
    scored = []
    for c in library():
        if server_name(c) in have:
            continue
        s = 0
        if rid and rid in c.get("roles", []):
            s += 10
        s += 3 * len(job & _words("%s %s %s" % (c["name"], c.get("keywords", ""), c.get("what", ""))))
        if "*" in c.get("roles", []):
            s += 1
        if s:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]


def search(words: str, limit: int = 12) -> list:
    """The library first (curated, from the official directory), then the public MCP registry (community servers:
    check who publishes one before granting it)."""
    q = _words(words)
    out = []
    for c in library():
        hits = len(q & _words("%s %s %s %s" % (c["name"], c.get("keywords", ""), c.get("what", ""), c["category"])))
        if hits:
            out.append((hits, dict(c, source="library")))
    out = [c for _, c in sorted(out, key=lambda x: -x[0])]
    if len(out) < limit and words.strip():
        try:
            url = REGISTRY_API + "?" + urllib.parse.urlencode({"search": words.strip()[:60], "limit": 20})
            req = urllib.request.Request(url, headers={"User-Agent": "orbit-connectors"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            seen = {c["url"] for c in out}
            for s in data.get("servers", []):
                x = s.get("server", s)
                remotes = [r.get("url") for r in (x.get("remotes") or []) if r.get("url")]
                if not remotes or remotes[0] in seen:
                    continue
                seen.add(remotes[0])
                out.append({"id": x.get("name", "").split("/")[-1][:40], "name": x.get("title") or x.get("name", ""),
                            "url": remotes[0], "what": (x.get("description") or "")[:160], "category": "Community",
                            "source": "registry (community: check the publisher, %s)" % x.get("name", "")})
        except Exception:  # noqa: BLE001
            pass
    return out[:limit]


def _resolve(ref: str, name: str = "") -> dict:
    c = by_id(ref)
    if c:
        return c
    if re.match(r"^https://[\w.-]+(/\S*)?$", ref or ""):
        host = urllib.parse.urlparse(ref).hostname or "server"
        return {"id": name or host.replace("mcp.", "").split(".")[0], "name": name or host, "url": ref, "category": "Added by link"}
    raise ValueError("No connector %r. Search with staff-connectors search, or give its https link." % ref)


def grant(emp_id: str, ref: str, by: str = "owner", name: str = "") -> str:
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id)
    if not e or e.get("status") == "retired":
        raise ValueError("No crew member %r" % emp_id)
    c = _resolve(ref, name)
    n = server_name(c)
    e.setdefault("connectors", {})[n] = {"url": c["url"], "name": c["name"], **({"money": True} if c.get("money") else {})}
    engine.save_registry(reg, "connector %s for %s (by %s)" % (n, emp_id, by))
    try:
        engine.claude_session(emp_id)
    except Exception:  # noqa: BLE001
        pass
    return ("Done: %s can use %s. The first time, open them in Claude and sign in to %s when it asks; Orbit never sees "
            "that sign-in." % (e["name"], c["name"], c["name"]))


def revoke(emp_id: str, ref: str, by: str = "owner") -> str:
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id) or {}
    have = e.get("connectors") or {}
    n = ref if ref in have else server_name(by_id(ref) or {"id": ref})
    if n not in have:
        return "%s doesn't have %s." % (e.get("name", emp_id), ref)
    have.pop(n)
    engine.save_registry(reg, "connector %s off for %s (by %s)" % (n, emp_id, by))
    try:
        engine.claude_session(emp_id)
    except Exception:  # noqa: BLE001
        pass
    return "Done: %s no longer uses %s." % (e.get("name", emp_id), n)


def mcp_config(emp: dict) -> dict:
    granted = (engine.registry().get("employees", {}).get(emp["id"], {}) or {}).get("connectors") or {}
    return {"mcpServers": {n: {"type": "http", "url": c["url"]} for n, c in granted.items()}}
