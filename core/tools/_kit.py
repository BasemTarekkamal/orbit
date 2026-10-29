"""Shared helpers for the toolbelt (core/tools/*.py). Harness-owned: employees can read it, not change it.

Every tool runs either as an employee's command (STAFF_EMPLOYEE and STAFF_WORKSPACE are set by the
engine) or by the owner from a terminal (neither is set: no ability checks, output goes to the cwd).

    from _kit import config, require, secret, workspace, out_dir, safe_url
    require("apify")                       # exits with a clear message if this employee lacks it
    tok = secret("apify_token")            # ~/Staff/.secrets/apify_token, or None
    url = safe_url(url)                    # http(s) only, never this Mac or its local network
Python 3.9 compatible (macOS system python).
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import sys
import urllib.parse

TOOLS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(TOOLS)
KIT = os.path.dirname(CORE)
HOME = os.path.expanduser(os.environ.get("STAFFROOM_HOME", "~/Staff"))


def config() -> dict:
    """The team's settings (~/Staff/staff.json); {} before setup."""
    try:
        with open(os.path.join(HOME, "staff.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def employee_id():
    return os.environ.get("STAFF_EMPLOYEE") or None


def workspace() -> str:
    return os.environ.get("STAFF_WORKSPACE") or os.getcwd()


def require(ability: str) -> None:
    """Stop unless the running employee has this ability ticked. The owner (no STAFF_EMPLOYEE) always may."""
    emp = employee_id()
    if not emp:
        return
    sys.path.insert(0, CORE)
    import abilities  # noqa: E402  (core/abilities.py)
    if not abilities.has(emp, ability):
        name = abilities.by_id().get(ability, {}).get("name", ability)
        sys.exit("'%s' is switched off for you. Tell your owner in one line that it can be switched on in the "
                 "control panel (Abilities); don't work around it." % name)


def secret(name: str):
    try:
        with open(os.path.join(HOME, ".secrets", name), encoding="utf-8") as fh:
            v = fh.read().strip()
            return v or None
    except OSError:
        return None


def out_dir(*parts: str) -> str:
    """A folder inside the employee's workspace (created), e.g. out_dir("research", "scrapes")."""
    p = os.path.join(workspace(), *parts)
    os.makedirs(p, exist_ok=True)
    return p


def safe_url(url: str) -> str:
    """Refuse anything but public http(s) pages. Gateway tools run outside the sandbox, so they must
    never reach this Mac (the control panel, other services) or its local network."""
    u = urllib.parse.urlparse(str(url).strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only http(s) URLs are allowed: %r" % url)
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise ValueError("local addresses are off-limits: %s" % host)
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError("can't resolve %s (%s)" % (host, e))
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError("%s points to a private or local address (%s)" % (host, ip))
    return u.geturl()
