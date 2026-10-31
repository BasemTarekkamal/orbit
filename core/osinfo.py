"""Which computer Orbit runs on, and the few things that differ: a Mac, Windows (through WSL2, the Linux
that ships with Windows), or a Linux PC. Everything else in the kit is the same code on all three.

    import osinfo
    osinfo.KIND                 # "mac" | "wsl" | "linux"
    osinfo.DEVICE               # "Mac" | "PC" | "computer", for messages: "on this " + DEVICE
    osinfo.local(text)          # kit-written text with "this Mac" said the way this computer is called
    osinfo.open_url(url)        # opens a page in the owner's browser (on Windows: the Windows browser)
    osinfo.which(name)          # a program, also in Homebrew's and the user's own bin folders
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def _kind() -> str:
    if sys.platform == "darwin":
        return "mac"
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as fh:
            if "microsoft" in fh.read().lower():
                return "wsl"
    except OSError:
        pass
    return "linux" if sys.platform.startswith("linux") else sys.platform


KIND = os.environ.get("ORBIT_OS") or _kind()          # ORBIT_OS: tests pretend to be another computer
DEVICE = {"mac": "Mac", "wsl": "PC"}.get(KIND, "computer")
SUPPORTED = KIND in ("mac", "wsl", "linux")
NAME = {"mac": "macOS", "wsl": "Windows (WSL)", "linux": "Linux"}.get(KIND, KIND)
BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"), "/usr/bin", "/bin"]

_MAC = re.compile(r"\b(this|your|the|a) Mac\b")


def local(text: str) -> str:
    """'this Mac' / 'your Mac' / 'the Mac' in the kit's own words, said for this computer. Identity on a Mac."""
    if KIND == "mac" or not text:
        return text
    dev = {"wsl": "PC"}.get(KIND, "computer")
    return _MAC.sub(lambda m: "%s %s" % (m.group(1), dev), text)


def which(name: str):
    return shutil.which(name) or next((os.path.join(d, name) for d in BIN_DIRS
                                       if os.access(os.path.join(d, name), os.X_OK)), None)


def path_dirs() -> list:
    """Folders a service or an employee's shell looks in for programs, in order."""
    return [d for d in BIN_DIRS if d not in ("/usr/bin", "/bin")] + ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]


def open_url(url: str) -> bool:
    """Opens a page in the owner's browser. False when there is no screen to open it on."""
    if KIND == "mac":
        cmds = [["open", url]]
    elif KIND == "wsl":                                   # the Windows browser, not one inside Linux
        cmds = [["wslview", url], ["explorer.exe", url], ["cmd.exe", "/c", "start", "", url.replace("&", "^&")]]
    else:
        cmds = [["xdg-open", url]]
    for c in cmds:
        exe = which(c[0])
        if not exe:
            continue
        try:
            subprocess.Popen([exe] + c[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            continue
    return False


# ------------------------------------------------------------------ Windows, from inside WSL
def distro() -> str:
    return os.environ.get("WSL_DISTRO_NAME", "")


def win_path(p: str) -> str:
    """A Linux path as Windows programs see it (\\\\wsl.localhost\\Ubuntu\\home\\…)."""
    r = subprocess.run(["wslpath", "-w", p], capture_output=True, text=True, timeout=10)
    if r.returncode != 0 or not r.stdout.strip():
        raise OSError("wslpath couldn't convert %s" % p)
    return r.stdout.strip()


def win_env(name: str) -> str:
    """A Windows environment variable (APPDATA, USERPROFILE…), read through cmd.exe."""
    exe = which("cmd.exe") or "/mnt/c/Windows/System32/cmd.exe"
    try:
        r = subprocess.run([exe, "/c", "echo %" + name + "%"], capture_output=True, text=True, timeout=15,
                           cwd="/mnt/c" if os.path.isdir("/mnt/c") else None)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    v = r.stdout.strip().splitlines()[-1].strip() if r.stdout.strip() else ""
    return "" if v == "%" + name + "%" else v


def lin_path(winp: str) -> str:
    r = subprocess.run(["wslpath", "-u", winp], capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def win_python():
    """Python for Windows (for live calls: Linux inside WSL can't hear Windows apps). → command list or None."""
    for c in (["py.exe", "-3"], ["python.exe"], ["python3.exe"]):
        exe = which(c[0])
        if not exe:
            continue
        try:   # the Microsoft Store's python.exe stub prints nothing useful and exits non-zero
            r = subprocess.run([exe] + c[1:] + ["-c", "import sys; print(sys.version_info[0])"],
                               capture_output=True, text=True, timeout=20, cwd="/mnt/c" if os.path.isdir("/mnt/c") else None)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip() == "3":
            return [exe] + c[1:]
    return None
