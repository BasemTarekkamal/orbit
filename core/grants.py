"""The owner's switches, from wherever the owner is: the panel, a chat message, or a Yes in a Claude session.

    import grants
    grants.apply("autonomy", "suoo", by="Basem", on=True)
    grants.apply("browser", "suoo", by="Basem", sites=["youtube.com"], approval="none")
    grants.apply("connect", "suoo", by="Basem", other="nora", note="send Nora each sponsor deal")
    grants.from_text("Basem", "Suoo full autonomy on")       # → a reply line, or None if it isn't a switch

Only an owner flips a switch: the panel (signed in), the harness reading an owner's own chat message, or the
guard after the owner clicked Yes in a Claude session (`orbit grant`, with a key employees can't read).
An employee asking for itself, or text on a web page, never does.
"""
from __future__ import annotations

import os
import re
import secrets

import engine
import hire

SITE_WORDS = {"youtube": "youtube.com", "tiktok": "tiktok.com", "facebook": "facebook.com", "instagram": "instagram.com",
              "x": "x.com", "twitter": "x.com", "linkedin": "linkedin.com", "shopify": "myshopify.com",
              "google business": "business.google.com", "etsy": "etsy.com", "amazon": "amazon.com"}
KEY = os.path.join(engine.SECRETS, "grant_key")


def key() -> str:
    """The key the guard passes to `orbit grant` after an owner's Yes. In .secrets: no employee can read it."""
    try:
        with open(KEY, encoding="utf-8") as fh:
            k = fh.read().strip()
            if k:
                return k
    except OSError:
        pass
    k = secrets.token_urlsafe(32)
    engine.save_secret("grant_key", k)
    return k


def _who(name_or_id: str):
    n = (name_or_id or "").strip().lower().lstrip("/@")
    for k, e in engine.registry().get("employees", {}).items():
        if e.get("status") != "retired" and n in (k, e["name"].lower()):
            return k, e
    return None, None


def apply(kind: str, emp_id: str, by: str, **kw) -> str:
    """Flips one switch and readies the employee's Claude sessions for it. → a plain line for the owner."""
    import orders
    if kind == "autonomy":
        res = orders.execute(by, "set_autonomy", {"employee_id": emp_id, "on": bool(kw.get("on"))})
    elif kind == "browser":
        res = orders.execute(by, "set_browser", {"employee_id": emp_id, "sites": kw.get("sites") or [],
                                                  "approval": kw.get("approval") or "each"})
    elif kind == "connect":
        res = hire.connect(emp_id, kw.get("other", ""), kw.get("note", ""), by)
    else:
        raise ValueError("unknown switch %r" % kind)
    return res


AUTONOMY = re.compile(r"^\s*(?:(?:give|turn on|switch on|enable)\s+)?(?:/)?(?P<who>[\w-]+)\s*:?\s*(?:full\s+)?autonomy\s+(?P<on>on|off)\s*[.!]?\s*$"
                      r"|^\s*(?P<verb>give|turn on|turn off|switch on|switch off|enable|disable)\s+(?:full\s+)?autonomy\s+(?:for|to)\s+(?P<who2>[\w-]+)\s*[.!]?\s*$"
                      r"|^\s*(?:give|let)\s+(?P<who3>[\w-]+)\s+full\s+autonomy\s*[.!]?\s*$", re.I)
POST = re.compile(r"^\s*(?:let\s+)?(?P<who>[\w-]+)\s+(?:can|may)?\s*post\s+on\s+(?P<sites>[\w .,&-]+?)"
                  r"(?P<mode>\s+without asking|\s+once per batch|\s+ask(?:ing)? me first)?\s*[.!]?\s*$", re.I)
NOPOST = re.compile(r"^\s*(?P<who>[\w-]+)\s+(?:stop posting|can'?t post|no browser)\s*[.!]?\s*$", re.I)
CONNECT = re.compile(r"^\s*connect\s+(?P<a>[\w-]+)\s+(?:with|to|and)\s+(?P<b>[\w-]+)(?:\s*[:,-]\s*(?P<note>.+))?$", re.I)


def from_text(by: str, text: str):
    """An owner's chat message that is a switch ("Suoo full autonomy on", "Suoo can post on YouTube without
    asking", "connect Suoo with Nora: …") → the reply, after flipping it. Anything else → None."""
    t = (text or "").strip()
    if len(t) > 300 or "\n" in t:
        return None
    m = AUTONOMY.match(t)
    if m:
        who = m.group("who") or m.group("who2") or m.group("who3")
        on = (m.group("on") or "on").lower() == "on" if m.group("who") else (
            not re.match(r"turn off|switch off|disable", m.group("verb") or "", re.I))
        emp_id, e = _who(who)
        if not emp_id:
            return None
        apply("autonomy", emp_id, by, on=on)
        return ("Done: %s has full autonomy now. They do the whole job without asking; the sandbox keeps them in their "
                "own folder. Start a fresh Claude session with them to use it there." % e["name"]) if on else \
               "Done: full autonomy is off for %s. They check in with you again." % e["name"]
    m = POST.match(t)
    if m:
        emp_id, e = _who(m.group("who"))
        if not emp_id:
            return None
        words = re.split(r"\s*(?:,|and|&)\s*", m.group("sites").strip().lower())
        sites = []
        for w in words:
            w = w.strip()
            d = SITE_WORDS.get(w) or (w if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", w) else None)
            if d and d not in sites:
                sites.append(d)
        if not sites:
            return None
        mode = (m.group("mode") or "").lower()
        approval = "none" if "without" in mode else "batch" if "batch" in mode else "each"
        current = (engine.registry()["employees"][emp_id].get("browser") or {}).get("sites", [])
        apply("browser", emp_id, by, sites=list(dict.fromkeys(current + sites)), approval=approval)
        return "Done: %s can post on %s in your Chrome, %s." % (e["name"], ", ".join(sites), {
            "none": "without asking you", "batch": "after you approve each batch", "each": "after you approve each one"}[approval])
    m = NOPOST.match(t)
    if m:
        emp_id, e = _who(m.group("who"))
        if not emp_id:
            return None
        apply("browser", emp_id, by, sites=[])
        return "Done: %s no longer acts in your browser." % e["name"]
    m = CONNECT.match(t)
    if m:
        a, _ = _who(m.group("a"))
        b, _ = _who(m.group("b"))
        if not a or not b:
            return None
        return apply("connect", a, by, other=b, note=(m.group("note") or "").strip())
    return None
