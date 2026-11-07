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


def keep_awake_cmd(pid: int, battery: bool = False, seconds: int = 0):
    """The command that stops this computer sleeping from idle until `pid` ends (or for `seconds`). battery=False:
    only while plugged in, where the system can tell. None when there's no way here. No admin rights, no setting changed."""
    if KIND == "mac":
        return ["caffeinate", "-s"] + (["-i"] if battery else []) + (["-t", str(seconds)] if seconds else ["-w", str(pid)])
    if KIND == "linux" and which("systemd-inhibit"):
        wait = ["sleep", str(seconds)] if seconds else ["tail", "--pid=%d" % pid, "-f", "/dev/null"]
        return ["systemd-inhibit", "--what=sleep:idle", "--who=Orbit", "--why=Your crew is working", "--mode=block"] + wait
    if KIND == "wsl":                                     # Windows' own sleep timer, reset from Linux until the process ends
        ps = ("$s=Add-Type -PassThru -Name OrbitAwake -MemberDefinition "
              "'[DllImport(\\\"kernel32.dll\\\")] public static extern uint SetThreadExecutionState(uint f);';"
              "[void]$s::SetThreadExecutionState(1)")
        check = "[ $SECONDS -lt %d ]" % seconds if seconds else "kill -0 %d 2>/dev/null" % pid
        return ["bash", "-c", 'while %s; do powershell.exe -NoProfile -NonInteractive -Command "%s" >/dev/null 2>&1; sleep 50; done' % (check, ps)]
    return None


RUNTIME = os.path.join(os.path.expanduser(os.environ.get("STAFFROOM_HOME", "~/Staff")), ".runtime")
NOTIFIER = os.path.join(RUNTIME, "Orbit.app")             # a tiny Mac app whose only job is to show notifications
NOTIFIER_VERSION = "1"
APPLET = """on run
	set f to (POSIX path of (path to home folder)) & "%s"
	try
		set raw to do shell script "cat " & quoted form of f
	on error
		return
	end try
	set AppleScript's text item delimiters to {linefeed}
	set parts to text items of raw
	if (count of parts) < 2 then return
	display notification (item 2 of parts) with title (item 1 of parts) sound name "Glass"
end run
"""


def notifier() -> str:
    """Builds (once) the Mac notifier app. Notifications from a plain script are dropped by macOS unless Script
    Editor is allowed; from an app of its own they show as "Orbit", after the owner says yes once. '' if it can't be built."""
    if KIND != "mac" or not which("osacompile"):
        return ""
    stamp = os.path.join(NOTIFIER, "Contents", "orbit-notifier.version")
    try:
        with open(stamp) as fh:
            if fh.read().strip() == NOTIFIER_VERSION and os.path.isdir(NOTIFIER):
                return NOTIFIER
    except OSError:
        pass
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        rel = os.path.relpath(os.path.join(RUNTIME, "notify.txt"), os.path.expanduser("~"))
        src = os.path.join(RUNTIME, "notifier.applescript")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(APPLET % rel)
        shutil.rmtree(NOTIFIER, ignore_errors=True)
        subprocess.run(["osacompile", "-o", NOTIFIER, src], capture_output=True, timeout=60, check=True)
        plist = os.path.join(NOTIFIER, "Contents", "Info.plist")
        for key, val in (("CFBundleIdentifier", "com.orbit.notifier"), ("CFBundleName", "Orbit"), ("LSUIElement", "true")):
            r = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Set :%s %s" % (key, val), plist], capture_output=True)
            if r.returncode:
                subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Add :%s %s %s" % (key, "bool" if val in ("true", "false") else "string", val), plist],
                               capture_output=True)
        with open(stamp, "w") as fh:
            fh.write(NOTIFIER_VERSION)
        return NOTIFIER
    except (OSError, subprocess.SubprocessError):
        return ""


def notify(title: str, text: str, more: str = "") -> bool:
    """A desktop notification on the owner's computer (when no phone channel is connected, so a crew member's
    routine message isn't missed). `more`: where the whole message is (shown after the first line). Best effort;
    False when this computer has no way to show one."""
    title = (title or "Orbit")[:60]
    body = " ".join((text or "").split())
    if len(body) > 200:
        body = body[:197].rsplit(" ", 1)[0] + "…"
    if more:
        body = (body + " (%s)" % more)[:240]
    try:
        if KIND == "mac":
            app = notifier()
            if app:
                with open(os.path.join(RUNTIME, "notify.txt"), "w", encoding="utf-8") as fh:
                    fh.write("%s\n%s\n" % (title, body))
                r = subprocess.run(["open", "-g", "-a", app], capture_output=True, timeout=15)
                if r.returncode == 0:
                    return True
            q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
            subprocess.run(["osascript", "-e", "display notification %s with title %s sound name \"Glass\"" % (q(body), q(title))],
                           capture_output=True, timeout=10)
            return True
        if KIND == "linux" and which("notify-send"):
            subprocess.run([which("notify-send"), title, body], capture_output=True, timeout=10)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def open_terminal(command: str, name: str = "orbit-chat") -> bool:
    """Opens a terminal window on the owner's screen running `command` (used for `orbit chat`). On a Mac the command
    goes in a small .command file that Terminal opens (no AppleScript, so no permission prompt). False when this
    computer has no way to; the caller then shows the command to type."""
    try:
        if KIND == "mac":
            os.makedirs(RUNTIME, exist_ok=True)
            script = os.path.join(RUNTIME, re.sub(r"[^a-z0-9-]", "-", name.lower()) + ".command")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/bash\nclear\n%s\n" % command)
            os.chmod(script, 0o755)
            r = subprocess.run(["open", "-a", "Terminal", script], capture_output=True, timeout=20)
            return r.returncode == 0
        if KIND == "wsl" and which("cmd.exe"):
            r = subprocess.run([which("cmd.exe"), "/c", "start", "", "wsl.exe", "bash", "-lc", command], capture_output=True, timeout=20)
            return r.returncode == 0
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
            exe = which(term)
            if exe:
                args = [exe, "--", "bash", "-lc", command] if term == "gnome-terminal" else [exe, "-e", "bash -lc %s" % _sh(command)]
                subprocess.Popen(args, start_new_session=True)
                return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def _sh(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


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
