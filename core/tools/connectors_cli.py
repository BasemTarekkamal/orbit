#!/usr/bin/env python3
"""staff-connectors: find the connectors (MCP servers) that would make your job easier, and see yours.

    staff-connectors suggest              the library's best matches for your job
    staff-connectors search <words>       the library, then the public MCP registry (community servers)
    staff-connectors mine                 the ones your owner granted you

Then ask for one with the request_access tool: kind "connector", connector "<id or https link>", and one line on
why. Your owner gets a Yes button; the first time, they sign in to the service in a Claude session with you.
Runs outside the sandbox (it reads the public MCP registry). Exit codes: 0 ok, 2 bad usage.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import connectors  # noqa: E402
import engine  # noqa: E402


def show(rows):
    if not rows:
        print("Nothing found. Try other words, or ask your owner for the service's MCP link.")
    for c in rows:
        print("- %s [%s] %s%s\n  %s%s" % (c["name"], c.get("id", ""), c.get("what", ""), "  (money: read-only)" if c.get("money") else "",
                                        c["url"], ("\n  " + c["source"]) if str(c.get("source", "")).startswith("registry") else ""))


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("suggest", "search", "mine"):
        print(__doc__)
        return 2
    me = os.environ.get("STAFF_EMPLOYEE", "")
    if a[0] == "suggest":
        if not me:
            print("Run it as a crew member (STAFF_EMPLOYEE).")
            return 2
        show(connectors.suggest(me))
    elif a[0] == "search":
        show(connectors.search(" ".join(a[1:])))
    else:
        mine = (engine.registry().get("employees", {}).get(me, {}) or {}).get("connectors") or {}
        if not mine:
            print("None yet. See `staff-connectors suggest`.")
        for n, c in mine.items():
            print("- %s (%s): %s" % (c["name"], n, c["url"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
