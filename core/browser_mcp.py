#!/usr/bin/env python3
"""The crew member's own browser, as the MCP server its runs and Claude sessions use (named orbit-browser).

It is Microsoft's Playwright MCP server (browser.py installs a pinned copy), connected to the crew member's own
Chrome. This wrapper passes every message through unchanged, and before each tool call makes sure that Chrome is
running (starting it the first time, or again if the owner quit it). So listing the tools opens no window: the
window appears only when the crew member actually browses.

    python3 core/browser_mcp.py <crew member id>       # run by Claude Code, speaking MCP on stdin/stdout
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import browser  # noqa: E402
import engine  # noqa: E402

OUT = threading.Lock()                                    # one message at a time on stdout, whoever writes it


def write(data: bytes) -> None:
    with OUT:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def pump(child) -> None:
    for line in iter(child.stdout.readline, b""):
        write(line)


def failed(msg: dict, why: str, handle: str) -> bytes:
    text = ("Your browser couldn't start: %s. Tell your owner in one line; they can run `orbit browser %s` to see "
            "what's wrong." % (why, handle))
    return (json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                        "result": {"content": [{"type": "text", "text": text}], "isError": True}}) + "\n").encode()


def relay(lines, forward, ensure, write, handle: str = "<handle>") -> None:
    """Passes each message on unchanged; before a tool call, ensure() (its Chrome is up). If that fails, the call is
    answered with the reason instead of being passed on."""
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            msg = None
        if isinstance(msg, dict) and msg.get("method") == "tools/call":
            try:
                ensure()
            except Exception as e:  # noqa: BLE001  reported to the crew member, never a crash
                write(failed(msg, str(e), handle))
                continue
        if not forward(line):
            return


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: browser_mcp.py <crew member id>\n")
        return 2
    emp_id = sys.argv[1]
    emp = engine.employee(emp_id)
    p = browser.port(emp_id)
    os.makedirs(os.path.join(emp["workspace"], "state", "browser"), exist_ok=True)
    n = browser.node() or "node"
    child = subprocess.Popen(browser.server_command(emp, p), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             cwd=emp["workspace"], env=browser._env(n))
    signal.signal(signal.SIGTERM, lambda *_: (child.terminate(), sys.exit(0)))
    threading.Thread(target=pump, args=(child,), daemon=True).start()

    def ensure():
        if browser.port(emp_id) != p:                     # someone else took its port while its Chrome was closed
            raise browser.BrowserError("its browser port changed; start a new session")
        browser.ensure(emp_id)

    def forward(line):
        try:
            child.stdin.write(line)
            child.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    relay(iter(sys.stdin.buffer.readline, b""), forward, ensure, write, emp_id)
    try:
        child.stdin.close()
    except OSError:
        pass
    try:
        return child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
