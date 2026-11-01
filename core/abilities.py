"""Abilities: what each employee may do. The catalog is core/abilities.json; the ticks are in
~/Staff/staff.json (employees.<id>.abilities), set in the control panel or with `orbit abilities`.

  effective = locked ∪ chosen        chosen missing → the catalog defaults

The engine turns tools, gateway commands and skills on or off from this; staffd gates Telegram,
voice, files, meetings, reminders, the team room and which routines run with has(). Harness-owned:
employees can read it, not change it. Python 3.9 compatible.
"""
from __future__ import annotations

import json
import re
import os

import engine

CATALOG_F = os.path.join(engine.CORE, "abilities.json")


def _load() -> dict:
    import osinfo                                          # "this Mac" said as "this PC" on Windows
    with open(CATALOG_F, encoding="utf-8") as fh:
        return json.loads(osinfo.local(fh.read()))


def catalog() -> list:
    return _load()["abilities"]


def groups() -> list:
    return _load()["groups"]


def by_id() -> dict:
    return {a["id"]: a for a in catalog()}


def preset(name: str) -> list:
    """'default' or 'super' → the ability ids it ticks."""
    return [a["id"] for a in catalog() if not a.get("locked") and not a.get("consent") and (name == "super" or a.get("default"))]


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
    """Gateway commands this employee may run outside the sandbox (they enforce their own limits).
    An ability marked "sandboxed" keeps its command inside the sandbox; it's only gated, not excluded."""
    on = effective(emp_id)
    return sorted({c for a in catalog() if a["id"] in on and not a.get("sandboxed") for c in a.get("commands", [])})


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


def validate(ids: list, keep_consent_from: str = None) -> list:
    """Cleans a requested set: known and not locked. Consent abilities (acting in the owner's browser) are
    switched only by their own panel section (hire.set_browser), never by a preset or the ticks grid: the
    employee's current state is kept."""
    cat = by_id()
    out = {i for i in ids if i in cat and not cat[i].get("locked") and not cat[i].get("consent")}
    if keep_consent_from:
        out |= {i for i in chosen(keep_consent_from) if cat.get(i, {}).get("consent")}
    return sorted(out)


# Banking, payment and crypto hosts: the same list as the guard's MONEY_HOSTS (core/guard/.../register.js).
MONEY_HOSTS = re.compile(r"(^|\.)(paypal|stripe|wise|revolut|venmo|cash\.app|zelle|payoneer|skrill|westernunion|moneygram|remitly|klarna|afterpay|alipay|wechatpay|paytm|phonepe|razorpay|mpesa|instapay|fawry|paymob|valu|binance|coinbase|kraken|bybit|okx|kucoin|crypto\.com|metamask|blockchain\.com|chase|bankofamerica|wellsfargo|citi|hsbc|barclays|santander|lloydsbank|natwest|monzo|starlingbank|n26|bnpparibas|societegenerale|deutsche-bank|ing|rabobank|ubs|emiratesnbd|alrajhibank|qnb|cibeg|banquemisr|nbe)\.[a-z.]+$", re.I)


def money_host(host: str) -> bool:
    return bool(MONEY_HOSTS.search(str(host or "").lower()))
