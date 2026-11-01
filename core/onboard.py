"""The hiring interview: the owner's own Claude asks the follow-up questions this particular job needs, then
composes the crew member's card (job, responsibilities, routines, abilities, the access to ask for, a weekly
token budget, the first task). Two short `claude -p` calls on the owner's plan, no tools, structured output.

    import onboard
    qs = onboard.questions(role, scope, name)                 # → [{id, text, why, type, options, placeholder}]
    card = onboard.compose(role, scope, name, answers)        # answers: [{"q": text, "a": text}]

Never asks for passwords or tokens: access is granted in the panel or by signing in in the crew member's own
browser. Orbit's policy is part of the prompt: acting as the owner (posting, portals) asks first; money is
read-only, never moved.
"""
from __future__ import annotations

import json
import os
import subprocess

import abilities
import engine

ACCESS_KINDS = ["sign_in", "post_with_approval", "finance_read_only", "files", "chat_channel", "other"]
BUDGETS = {"light": 1_000_000, "regular": 3_000_000, "heavy": 8_000_000}     # tokens a week
ROUTINES = ["brief", "standup", "eod"]

QUESTIONS_SCHEMA = {
    "type": "object", "required": ["intro", "questions"],
    "properties": {
        "intro": {"type": "string", "description": "One warm sentence to the owner about this hire, in their language"},
        "questions": {"type": "array", "minItems": 3, "maxItems": 6, "items": {
            "type": "object", "required": ["id", "text", "type", "options"],
            "properties": {
                "id": {"type": "string"}, "text": {"type": "string"}, "why": {"type": "string"},
                "type": {"type": "string", "enum": ["choice", "multi", "text"]},
                "options": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "placeholder": {"type": "string"}}}}}}

CARD_SCHEMA = {
    "type": "object",
    "required": ["role", "scope", "responsibilities", "first_task", "routines", "abilities", "access", "budget",
                 "model", "plan"],
    "properties": {
        "role": {"type": "string"}, "scope": {"type": "string"},
        "responsibilities": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "first_task": {"type": "string"},
        "plan": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4,
                 "description": "What they'll do in their first days, in order"},
        "routines": {"type": "object", "properties": {k: {"type": "boolean"} for k in ROUTINES}},
        "abilities": {"type": "array", "items": {"type": "string"}},
        "access": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "required": ["kind", "what", "why"],
            "properties": {"kind": {"type": "string", "enum": ACCESS_KINDS}, "what": {"type": "string"},
                           "why": {"type": "string"}, "site": {"type": "string"}}}},
        "budget": {"type": "string", "enum": list(BUDGETS)},
        "model": {"type": "string", "enum": ["haiku", "sonnet", "opus"]}}}

POLICY = """Orbit's rules, which every card must respect:
- Crew members run on the owner's own Claude plan. Budgets are tokens a week: light (about 1M), regular (about 3M), heavy (about 8M).
- Acting as the owner (posting, publishing, replying as them, changing things in a portal) is allowed only as "ask first, then do": the crew member prepares it, the owner approves it in the panel or on their phone, then the crew member does it.
- Money: read-only. A crew member may sign in to read statements, invoices and balances; it never pays, transfers or buys anything.
- Never ask for passwords, codes or tokens in a question. Access is given by the owner signing in once, in the crew member's own browser on this computer, or in the panel's settings.
- Never invent facts about the owner's business."""


def _context(name, role, scope):
    reg = engine.registry()
    try:
        with open(os.path.join(engine.HOME, "team", "ABOUT.md"), encoding="utf-8") as fh:
            about = fh.read()[:4000]
    except OSError:
        about = "(not written yet)"
    owner = next(iter(reg.get("owners", {}).values()), {}).get("name", "the owner")
    crew = ", ".join("%s (%s)" % (e["name"], e["role"]) for e in reg.get("employees", {}).values()
                     if e.get("status") != "retired") or "nobody yet"
    return ("Owner: %s. Team: %s.\nAbout the business, in the owner's words:\n%s\n\nAlready on the crew: %s\n\n"
            "The new hire: %s, %s.\nWhat the owner wants from them, in their words: %s"
            % (owner, reg.get("team_name", ""), about, crew, name or "(unnamed)", role, scope or "(not said)"))


def _ask(system, prompt, schema, timeout=150):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_")) and k != "CLAUDECODE"}
    if engine.registry().get("auth") == "api_key" and engine.secret("anthropic_api_key"):
        env["ANTHROPIC_API_KEY"] = engine.secret("anthropic_api_key")
    cmd = [engine.resolve_claude(), "-p", "--model", "sonnet", "--effort", "low", "--tools", "",
           "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config", "--output-format", "json",
           "--system-prompt", system, "--json-schema", json.dumps(schema)]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=engine.HOME, env=env)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("Claude didn't answer (%s)" % (r.stderr.strip()[-200:] or "no output"))
    if d.get("is_error") or not isinstance(d.get("structured_output"), dict):
        raise RuntimeError(engine.friendly_error(str(d.get("result", ""))))
    out = d["structured_output"]
    out["_tokens"] = engine.run_tokens(d)
    return out


def questions(role, scope, name=""):
    system = ("You are Orbit's hiring interviewer. An owner is hiring an AI crew member that runs on their own "
              "Claude plan on their computer. Ask the few questions this specific job needs so the crew member can "
              "do it the way the owner thinks. Prefer choices the owner can tap; use text only for names, links "
              "and specifics. Cover what the card doesn't know yet: their accounts, channels or sites; goals and "
              "numbers; tone and language; how often and when to report; what the crew member should do on its "
              "own and what it should prepare for approval; what access the owner is willing to give. Short "
              "questions, short options, the owner's language (from the About text). No question about money "
              "transfers, passwords or tokens.\n\n" + POLICY)
    out = _ask(system, _context(name, role, scope), QUESTIONS_SCHEMA)
    qs = []
    for i, q in enumerate(out.get("questions") or []):
        q["id"] = "q%d" % (i + 1)
        q["options"] = [str(o)[:120] for o in (q.get("options") or [])][:6]
        if q.get("type") not in ("choice", "multi", "text") or (q["type"] != "text" and not q["options"]):
            q["type"] = "text"
        qs.append(q)
    return {"intro": out.get("intro", ""), "questions": qs, "tokens": out.get("_tokens", 0)}


def compose(role, scope, name, answers):
    catalog = "\n".join("- %s: %s" % (a["id"], a.get("description", a.get("name", ""))) for a in abilities.catalog())
    qa = "\n".join("Q: %s\nA: %s" % (str(x.get("q", ""))[:300], str(x.get("a", ""))[:1500]) for x in answers or [])
    system = ("You are Orbit's hiring interviewer. From the owner's answers, write the new crew member's card: "
              "their job title, the scope in 2 to 4 sentences in the owner's words and language, concrete "
              "responsibilities, the first real task they can do today with free web tools, a short plan for their "
              "first days, which routines to switch on (brief = a morning brief, standup, eod = an end-of-day "
              "note), which abilities to tick (ids from the list only), the access to ask the owner for (only "
              "what this job needs; for posting use post_with_approval, for bank or payment portals "
              "finance_read_only, for accounts to read use sign_in), a weekly token budget and a model (haiku for "
              "simple routine work, sonnet for most jobs, opus only for hard analysis).\n\n" + POLICY +
              "\n\nAbilities (id: what it does):\n" + catalog)
    out = _ask(system, _context(name, role, scope) + "\n\nThe interview:\n" + (qa or "(no answers)"), CARD_SCHEMA)
    known = {a["id"] for a in abilities.catalog()}
    out["abilities"] = [a for a in out.get("abilities") or [] if a in known]
    out["routines"] = {k: bool((out.get("routines") or {}).get(k)) for k in ROUTINES}
    out["access"] = [a for a in out.get("access") or [] if a.get("kind") in ACCESS_KINDS][:6]
    out["budget"] = out.get("budget") if out.get("budget") in BUDGETS else "regular"
    out["weekly_tokens"] = BUDGETS[out["budget"]]
    out["tokens"] = out.pop("_tokens", 0)
    return out
