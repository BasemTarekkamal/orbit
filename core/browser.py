"""Each crew member's own browser: a Chrome window of its own, apart from the owner's and from the rest of the crew.

A crew member browses in a Chrome that belongs to it alone, with its own profile (sign-ins, cookies, tabs) kept in
~/Staff/.runtime/<id>/browser. The owner signs it in to a site once, in that window (`orbit browser <handle>`); the
crew member never types a password. Its runs and its Claude chat all share that one window, through Microsoft's free
Playwright MCP server (pinned below) connected to its Chrome over a local DevTools port, one port per crew member.
Chrome starts the first time the crew member actually uses a browser tool, and stays open after the run with its
tabs, until the owner closes it. The owner's own Chrome is never touched: the guard blocks Claude in Chrome and
Claude's browser pane for crew members.

Why not an incognito window each: Chrome's incognito windows share one set of cookies with each other, and forget
every sign-in when they close. A profile per crew member keeps them apart and keeps them signed in. A crew member
whose browser is set to private gets a fresh profile every time its Chrome starts (it forgets, like incognito).

    import browser
    browser.mcp_server(emp)          # {"orbit-browser": {...}} for its runs and Claude sessions; {} when it can't run here
    browser.ensure("sara")           # → her DevTools port; starts her Chrome if it isn't running
    browser.open_tab("sara", url)    # a tab in her window (the owner signing her in)
    browser.close("sara")            # quits her Chrome (by its PID)
    browser.status("sara")           # {"running", "port", "profile", "private"}
    browser.ready()                  # (True, "") or (False, what's missing on this computer)
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import engine
import osinfo

PKG, PKG_VERSION = "@playwright/mcp", "0.0.83"            # pinned: a release that had been out for weeks
SERVER = "orbit-browser"                                  # its tools are mcp__orbit-browser__browser_*
MCP_DIR = os.path.join(engine.HOME, ".runtime", "browser-mcp")
CLI = os.path.join(MCP_DIR, "node_modules", "@playwright", "mcp", "cli.js")
PORTS = range(9310, 9910)                                 # one per crew member, kept while it's free
_STARTED = []


class BrowserError(RuntimeError):
    pass


def _dir(emp_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", emp_id or ""):
        raise BrowserError("bad crew member id %r" % emp_id)
    return os.path.join(engine.HOME, ".runtime", emp_id, "browser")


def profile(emp_id: str) -> str:
    return os.path.join(_dir(emp_id), "profile")


def _state(emp_id: str) -> dict:
    try:
        with open(os.path.join(_dir(emp_id), "state.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(emp_id: str, **kw) -> dict:
    d = {**_state(emp_id), **kw}
    os.makedirs(_dir(emp_id), exist_ok=True)
    tmp = os.path.join(_dir(emp_id), "state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, os.path.join(_dir(emp_id), "state.json"))
    return d


# ------------------------------------------------------------------ what this computer has
def chrome():
    """Google Chrome (or Chromium), else the Chromium that Playwright installs for the page reader. None if neither."""
    if os.environ.get("ORBIT_CHROME"):
        return os.environ["ORBIT_CHROME"]
    if osinfo.KIND == "mac":
        for app in ("Google Chrome.app/Contents/MacOS/Google Chrome", "Chromium.app/Contents/MacOS/Chromium"):
            for root in ("/Applications", os.path.expanduser("~/Applications")):
                if os.access(os.path.join(root, app), os.X_OK):
                    return os.path.join(root, app)
        pattern = "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            if osinfo.which(name):
                return osinfo.which(name)
        pattern = "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"
    found = sorted(glob.glob(os.path.expanduser(pattern)), key=_revision)
    return found[-1] if found else None


def _revision(path: str) -> int:
    m = re.search(r"chromium-(\d+)", path)
    return int(m.group(1)) if m else 0


def _version(node_path: str) -> tuple:
    try:
        out = subprocess.run([node_path, "-v"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ()
    m = re.match(r"v(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else ()


def node():
    """Node.js 20 or newer (the browser connector needs it): on PATH, Homebrew, or the newest nvm/volta one."""
    seen = []
    for p in [osinfo.which("node"), os.path.expanduser("~/.volta/bin/node")] + sorted(
            glob.glob(os.path.expanduser("~/.nvm/versions/node/v*/bin/node")),
            key=lambda p: [int(x) for x in re.findall(r"\d+", p.split("/node/v")[-1])[:3]], reverse=True):
        if p and p not in seen and os.access(p, os.X_OK):
            seen.append(p)
            if _version(p) >= (20, 0):
                return p
    return None


def installed() -> str:
    """The connector's installed version ('' when it isn't)."""
    try:
        with open(os.path.join(os.path.dirname(CLI), "package.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version", "")
    except (OSError, ValueError):
        return ""


def ready() -> tuple:
    """(True, '') when crew members can have their own browser here; else (False, the one thing missing)."""
    if not chrome():
        return False, "no Chrome on this computer: install Google Chrome"
    if not node():
        return False, "Node.js 20 or newer is missing (free, from nodejs.org)"
    if installed() != PKG_VERSION:
        return False, "the browser connector isn't installed yet: orbit browser --install"
    return True, ""


def _env(node_path: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([os.path.dirname(node_path)] + env.get("PATH", "").split(os.pathsep) + osinfo.path_dirs())
    return env


def install(timeout: int = 300) -> str:
    """Installs the pinned Playwright MCP into ~/Staff/.runtime/browser-mcp (free, ~20 MB, no browser download:
    it drives the Chrome already here). → its version. Raises BrowserError with the reason."""
    n = node()
    if not n:
        raise BrowserError("Node.js 20 or newer is missing (free, from nodejs.org)")
    if installed() == PKG_VERSION:
        return PKG_VERSION
    npm = os.path.join(os.path.dirname(n), "npm")
    os.makedirs(MCP_DIR, exist_ok=True)
    pkg = os.path.join(MCP_DIR, "package.json")
    if not os.path.exists(pkg):
        with open(pkg, "w", encoding="utf-8") as fh:
            json.dump({"name": "orbit-browser-mcp", "private": True}, fh)
    try:
        r = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error", "%s@%s" % (PKG, PKG_VERSION)],
                           cwd=MCP_DIR, capture_output=True, text=True, timeout=timeout, env=_env(n))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BrowserError("couldn't install the browser connector: %s" % e)
    if installed() != PKG_VERSION:
        raise BrowserError("couldn't install the browser connector: %s" % (r.stderr or r.stdout).strip()[-300:])
    return PKG_VERSION


# ------------------------------------------------------------------ the crew member's Chrome
def headless() -> bool:
    """No screen to show a window on (a Linux server, CI): Chrome runs without one."""
    if os.environ.get("ORBIT_BROWSER_HEADLESS"):
        return os.environ["ORBIT_BROWSER_HEADLESS"] not in ("0", "")
    return osinfo.KIND != "mac" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _get(port: int, path: str, method: str = "GET", timeout: float = 2):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _browser_id(p: int, timeout: float = 1) -> str:
    """The DevTools id of the Chrome answering on port p ('' if none): new each time a Chrome starts."""
    try:
        return str(_get(p, "/json/version", timeout=timeout).get("webSocketDebuggerUrl") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def running(emp_id: str) -> bool:
    """Its own Chrome (the one Orbit started for it, by its DevTools id) is up and answering on its port."""
    st = _state(emp_id)
    return bool(st.get("port") and st.get("id") and _browser_id(st["port"]) == st["id"])


def _free(p: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False


def port(emp_id: str) -> int:
    """This crew member's DevTools port: the one it has, while it's its Chrome there or the port is free; else the
    first free one no colleague holds."""
    p = _state(emp_id).get("port")
    if p and (running(emp_id) or _free(p)):
        return p
    taken = set()
    for f in glob.glob(os.path.join(engine.HOME, ".runtime", "*", "browser", "state.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                taken.add(json.load(fh).get("port"))
        except (OSError, ValueError):
            pass
    for p in PORTS:
        if p not in taken and _free(p):
            _save(emp_id, port=p)
            return p
    raise BrowserError("no free port for a browser between %d and %d" % (PORTS[0], PORTS[-1]))


def private(emp_id: str) -> bool:
    return bool((engine.registry().get("employees", {}).get(emp_id) or {}).get("browser_private"))


def set_private(emp_id: str, on: bool, by: str = "owner") -> bool:
    """The owner's choice: a fresh profile every time its Chrome starts (forgets sign-ins, like incognito)."""
    reg = engine.registry()
    e = reg.get("employees", {}).get(emp_id)
    if not e:
        raise BrowserError("No crew member %r" % emp_id)
    if on:
        e["browser_private"] = True
    else:
        e.pop("browser_private", None)
    engine.save_registry(reg, "browser: %s %s (by %s)" % (emp_id, "private" if on else "keeps its sign-ins", by))
    return on


def _name(emp_id: str, prof: str) -> None:
    """Chrome shows the crew member's name on its profile button, so the owner can tell the windows apart."""
    name = (engine.registry().get("employees", {}).get(emp_id) or {}).get("name") or emp_id
    path = os.path.join(prof, "Local State")
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    cache = st.setdefault("profile", {}).setdefault("info_cache", {}).setdefault("Default", {})
    if cache.get("name") == name + " (Orbit)":
        return
    cache.update({"name": name + " (Orbit)", "is_using_default_name": False})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh)


def _lock(emp_id: str):
    """One start at a time per crew member (a run and its chat may both reach for the browser)."""
    os.makedirs(_dir(emp_id), exist_ok=True)
    fh = open(os.path.join(_dir(emp_id), "start.lock"), "w")
    try:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_EX)
    except ImportError:                                   # not on a Mac or Linux: nothing to lock with
        pass
    return fh


def args(emp_id: str, p: int) -> list:
    out = ["--user-data-dir=" + profile(emp_id), "--remote-debugging-port=%d" % p, "--no-first-run",
           "--no-default-browser-check", "--restore-last-session"]
    return out + (["--headless=new"] if headless() else [])


def ensure(emp_id: str, timeout: float = 25) -> int:
    """Its Chrome, started if it isn't running. → the DevTools port. Raises BrowserError with the reason."""
    p = port(emp_id)
    if running(emp_id):
        return p
    with _lock(emp_id):
        if running(emp_id):
            return p
        exe = chrome()
        if not exe:
            raise BrowserError("there's no Chrome on this computer: install Google Chrome")
        prof = profile(emp_id)
        if private(emp_id):
            shutil.rmtree(prof, ignore_errors=True)
        os.makedirs(prof, exist_ok=True)
        _name(emp_id, prof)
        with open(os.path.join(_dir(emp_id), "chrome.log"), "ab") as log:
            proc = subprocess.Popen([exe] + args(emp_id, p), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True)   # outlives the run: the window stays with its tabs
        _STARTED.append(proc)                             # kept, not reaped: it's meant to outlive this process
        end = time.time() + timeout
        while time.time() < end:
            if proc.poll() is not None:
                break
            bid = _browser_id(p)
            if bid:
                _save(emp_id, port=p, pid=proc.pid, id=bid, started=time.strftime("%Y-%m-%dT%H:%M:%S"))
                return p
            time.sleep(0.25)
        try:
            with open(os.path.join(_dir(emp_id), "chrome.log"), "rb") as fh:
                tail = fh.read()[-400:].decode("utf-8", "replace").strip()
        except OSError:
            tail = ""
        if proc.poll() is None:
            _kill(proc.pid)
        raise BrowserError("its Chrome didn't start%s" % ((": " + tail.splitlines()[-1]) if tail else ""))


def _main_pid(emp_id: str) -> int:
    """The PID of its Chrome's main process: the recorded one if it's still that Chrome, else found by its profile."""
    flag = "--user-data-dir=" + profile(emp_id)
    pid = _state(emp_id).get("pid") or 0
    try:
        rows = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    mains = []
    for row in rows.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) == 2 and flag in parts[1] and "--type=" not in parts[1]:
            mains.append(int(parts[0]))
    return pid if pid in mains else (mains[0] if mains else 0)


def _kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def close(emp_id: str) -> bool:
    """Quits its Chrome (its tabs come back next time, unless it's private). False if it wasn't running."""
    pid = _main_pid(emp_id)
    if not pid:
        return False
    _kill(pid)
    for _ in range(40):
        if not _main_pid(emp_id):
            break
        time.sleep(0.25)
    _save(emp_id, pid=0, id="")
    return True


def open_tab(emp_id: str, url: str = "") -> dict:
    """Opens its window (starting its Chrome if needed) on a new tab, for the owner: to sign it in, or to watch."""
    url = url.strip() or "about:blank"
    if not re.match(r"^(https?://|about:blank$)", url):
        url = "https://" + url
    p = ensure(emp_id)
    try:
        t = _get(p, "/json/new?" + urllib.parse.quote(url, safe=":/?&=%#"), method="PUT", timeout=5)
        if t.get("id"):
            _get(p, "/json/activate/" + t["id"], timeout=5)
    except (OSError, ValueError):
        pass                                              # older Chrome answers /json/activate in plain text
    return {"port": p, "url": url, "profile": profile(emp_id)}


def status(emp_id: str) -> dict:
    return {"running": running(emp_id), "port": _state(emp_id).get("port"), "profile": profile(emp_id),
            "private": private(emp_id)}


# ------------------------------------------------------------------ the MCP server its sessions use
def mcp_server(emp: dict) -> dict:
    """The browser connector for this crew member's runs and Claude sessions: {} if its own browser is off or can't
    run on this computer (see ready())."""
    import abilities
    if "own_browser" not in abilities.effective(emp["id"]) or not ready()[0]:
        return {}
    py = sys.executable if sys.executable and os.path.exists(sys.executable) else (osinfo.which("python3") or "python3")
    return {SERVER: {"type": "stdio", "command": py, "args": [os.path.join(engine.CORE, "browser_mcp.py"), emp["id"]],
                     "env": {"STAFFROOM_HOME": engine.HOME}}}


def server_command(emp: dict, p: int) -> list:
    """The Playwright MCP server, connected to this crew member's Chrome on port p."""
    return [node() or "node", CLI, "--cdp-endpoint", "http://127.0.0.1:%d" % p, "--codegen", "none",
            "--output-dir", os.path.join(emp["workspace"], "state", "browser"), "--allow-unrestricted-file-access"]
