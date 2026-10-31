"""Live calls: a crew member listens on this Mac while you're on a call (Zoom, Meet, Teams, WhatsApp, FaceTime,
a phone on speaker), keeps a running transcript, answers questions about it during the call, and writes
minutes when it ends.

How: Orbit Listener records what the computer plays (them) and the microphone (you) as two raw 16 kHz
streams: on a Mac tools/call_listen.swift, built once into a tiny .app; on Windows and Linux
tools/call_listen.py (on Windows run by Python for Windows, since Linux inside WSL can't hear Windows apps). Every 30 s the new audio is cut at a quiet moment and
transcribed with whisper on this Mac. No bot joins the call, nothing is uploaded, and the raw audio is
deleted once it's transcribed.

Harness-owned: staffd and the panel run it in-process. start(), stop(), status(), live_note(), recover().
"""
from __future__ import annotations

import array
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave

import engine
import osinfo

CORE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(CORE, "tools", "call_listen.swift")
PY_SRC = os.path.join(CORE, "tools", "call_listen.py")
SR = 16000
CHUNK_S = 30
MAX_MIN = 180
QUIET_RMS = 0.004                      # below this a slice is silence: skip whisper (it invents words on silence)
STREAMS = (("them", "Them"), ("you", "You"))
CALLS: dict = {}                       # emp_id -> state
LOCK = threading.Lock()
PERMISSION_HELP = {
    "mac": ("The first time, macOS asks to let Orbit Listener hear the call. Open System Settings > "
            "Privacy & Security, turn Orbit Listener on under Screen & System Audio Recording and under "
            "Microphone, then start again."),
    "wsl": ("Windows didn't let Orbit hear the microphone. Open Settings > Privacy & security > Microphone, turn on "
            "\"Let desktop apps access your microphone\", then start again."),
    "linux": ("Orbit couldn't hear the microphone. Check that a microphone is connected and not muted in your sound "
              "settings, then start again."),
}.get(osinfo.KIND, "Orbit couldn't hear the microphone.")
WIN_SETUP = ("Live calls on Windows need Python for Windows once (it hears what Windows plays). In PowerShell run:  "
             "winget install Python.Python.3.12   then   py -m pip install soundcard numpy")


class CallError(Exception):
    pass


def _bin(n):
    return osinfo.which(n)


def model_path():
    for p in (os.environ.get("WHISPER_MODEL"), os.path.join(engine.HOME, "models", "ggml-large-v3-turbo-q5_0.bin"),
              os.path.expanduser("~/Staff/models/ggml-large-v3-turbo-q5_0.bin")):
        if p and os.path.exists(os.path.expanduser(p)):
            return os.path.expanduser(p)
    return None


def _py_ok(cmd):
    """Can this Python record (soundcard + numpy importable, a sound server there)?"""
    try:
        r = subprocess.run(cmd + ["-c", "import numpy, soundcard; soundcard.default_speaker()"], capture_output=True,
                           text=True, timeout=30, cwd="/mnt/c" if osinfo.KIND == "wsl" and os.path.isdir("/mnt/c") else None)
    except (OSError, subprocess.TimeoutExpired):
        return False, "timed out"
    return r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1][:160]


def ready():
    """→ (ok, plain reason). Live calls need whisper and its model, plus: on a Mac macOS 15+ and Apple's Swift
    compiler; on Windows, Python for Windows with soundcard; on Linux, soundcard and a sound server."""
    voice = "brew install ffmpeg whisper-cpp" if osinfo.KIND == "mac" else "orbit doctor --get-whisper"
    if not _bin("whisper-cli") or not model_path():
        return False, ("Live calls need the speech model, the same one voice notes use: %s, then  "
                       "orbit doctor --get-voice-model" % voice)
    if osinfo.KIND == "wsl":
        py = osinfo.win_python()
        if not py or not _py_ok(py)[0]:
            return False, WIN_SETUP
        return True, ""
    if osinfo.KIND != "mac":
        ok, why = _py_ok([sys.executable])
        if not ok:
            if "No module" in why:
                return False, "Live calls need one Python package: python3 -m pip install --user soundcard numpy"
            return False, "Live calls need a sound server (PulseAudio or PipeWire, there on any desktop Linux): %s" % why
        return True, ""
    try:
        major = int(subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.split(".")[0])
    except (ValueError, OSError):
        major = 0
    if major and major < 15:
        return False, "Live calls need macOS 15 or newer. You can still send a recording after the call."
    if not _bin("swiftc"):
        return False, "Live calls need Apple's developer tools once: run  xcode-select --install"
    return True, ""


# ------------------------------------------------------------------ the listener app
def listener_app():
    """Builds OrbitListener.app once per source version, so macOS asks permission for "Orbit Listener"."""
    with open(SRC, "rb") as fh:
        tag = hashlib.sha1(fh.read()).hexdigest()[:12]
    app = os.path.join(engine.HOME, "cache", "OrbitListener.app")
    stamp = os.path.join(app, "Contents", "Resources", "source.sha")
    try:
        with open(stamp) as fh:
            if fh.read().strip() == tag and os.access(os.path.join(app, "Contents", "MacOS", "orbit-listen"), os.X_OK):
                return app
    except OSError:
        pass
    swiftc = _bin("swiftc")
    if not swiftc:
        raise CallError("Live calls need Apple's developer tools once: run  xcode-select --install")
    shutil.rmtree(app, ignore_errors=True)
    for d in ("MacOS", "Resources"):
        os.makedirs(os.path.join(app, "Contents", d), exist_ok=True)
    cache = os.path.join(engine.HOME, "cache", "swift-modcache")
    r = subprocess.run([swiftc, "-O", "-module-cache-path", cache, SRC, "-o",
                        os.path.join(app, "Contents", "MacOS", "orbit-listen")],
                       capture_output=True, text=True, timeout=600, env=dict(os.environ, CLANG_MODULE_CACHE_PATH=cache))
    if r.returncode != 0:
        raise CallError("Couldn't build Orbit Listener: %s" % (r.stderr.strip()[-300:] or "swiftc failed"))
    with open(os.path.join(app, "Contents", "Info.plist"), "w") as fh:
        fh.write(INFO_PLIST)
    subprocess.run(["codesign", "-s", "-", "--force", app], capture_output=True)
    with open(stamp, "w") as fh:
        fh.write(tag)
    return app


INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>app.orbit.listener</string>
<key>CFBundleName</key><string>Orbit Listener</string>
<key>CFBundleDisplayName</key><string>Orbit Listener</string>
<key>CFBundleExecutable</key><string>orbit-listen</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>15.0</string>
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Orbit Listener hears your side of a call so your crew can take notes. Audio stays on this Mac.</string>
<key>NSAudioCaptureUsageDescription</key><string>Orbit Listener hears the other side of a call so your crew can take notes. Audio stays on this Mac.</string>
</dict></plist>
"""


# ------------------------------------------------------------------ audio → text
def _read(path, start, end):
    a = array.array("f")
    with open(path, "rb") as fh:
        fh.seek(start * 4)
        data = fh.read((end - start) * 4)
    a.frombytes(data[:len(data) // 4 * 4])
    return a


def _rms(a, i=0, j=None):
    j = len(a) if j is None else j
    if j <= i:
        return 0.0
    return math.sqrt(sum(x * x for x in a[i:j:4]) / max(1, len(range(i, j, 4))))


def _quiet_cut(a):
    """Index of the quietest 0.3 s in the last 5 s, so a chunk ends between words, not inside one."""
    win, look = int(0.3 * SR), int(5 * SR)
    if len(a) <= look + win:
        return len(a)
    best, at = None, len(a)
    for s in range(len(a) - look, len(a) - win, win // 2):
        e = _rms(a, s, s + win)
        if best is None or e < best:
            best, at = e, s + win // 2
    return at


def _whisper(a, prompt=""):
    """→ [(seconds into the slice, text)]."""
    model, wh = model_path(), _bin("whisper-cli")
    if not model or not wh:
        raise CallError("speech model missing")
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "s.wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(array.array("h", (int(max(-1.0, min(1.0, x)) * 32767) for x in a)).tobytes())
        cmd = [wh, "-m", model, "-l", "auto", "-t", "8", "-np", "-f", wav]
        if prompt:
            cmd += ["--prompt", prompt[-200:]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    out = []
    for ln in r.stdout.splitlines():
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\.(\d+) --> [^\]]+\]\s*(.*)", ln)
        if not m:
            continue
        text = m.group(5).strip()
        if not text or re.fullmatch(r"[\[\(].*[\]\)]", text):          # [BLANK_AUDIO], (music)
            continue
        out.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), text))
    return out


def _stamp(sec):
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def _consume(st, final=False):
    """Transcribes the audio that arrived since the last pass and appends it to the transcript."""
    lines = []
    for key, label in STREAMS:
        path = os.path.join(st["audio"], key + ".pcm")
        try:
            total = os.path.getsize(path) // 4
        except OSError:
            continue
        start = st["offset"][key]
        if total - start < (SR if final else (CHUNK_S - 5) * SR):
            continue
        a = _read(path, start, total)
        cut = len(a) if final else _quiet_cut(a)
        a = a[:cut]
        st["offset"][key] = start + cut
        if _rms(a) < QUIET_RMS:
            continue
        try:
            said = _whisper(a, st.get("tail", ""))
        except Exception as e:  # noqa: BLE001
            st["errors"] = st.get("errors", 0) + 1
            st["last_error"] = str(e)[:200]
            continue
        lines += [(start / SR + s, label, text) for s, text in said]
    them = [t for _, lab, t in lines if lab == "Them"]
    keep = []
    for sec, lab, text in sorted(lines):
        if lab == "You" and any(difflib.SequenceMatcher(None, text.lower(), t.lower()).ratio() > 0.75 for t in them):
            continue                                      # the mic heard the speakers: that line is theirs
        keep.append("[%s] %s: %s" % (_stamp(sec), lab, text))
    if keep:
        with open(st["transcript_abs"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(keep) + "\n")
        st["lines"] += len(keep)
        st["last"] = keep[-1][:200]
        st["tail"] = " ".join(k.split(": ", 1)[-1] for k in keep)[-200:]


# ------------------------------------------------------------------ lifecycle
def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def _listening(st):
    """Is the listener still running? The Mac app: its pid. The Python listener (on Windows a Windows process
    this Linux can't signal): the alive file it touches every second, and our handle on it."""
    proc = st.get("proc")
    if proc is not None and proc.poll() is not None:
        return False
    if proc is None and osinfo.KIND == "mac":
        return _alive(_pid(st))
    try:
        return time.time() - os.path.getmtime(os.path.join(st["audio"], "alive")) < 10
    except OSError:
        return False


def _pid(st):
    try:
        with open(os.path.join(st["audio"], "listener.pid")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def start(emp_id, by, title="", on_end=None, mic=True):
    """Starts listening for an employee. → status dict. Raises CallError with a plain reason."""
    with LOCK:
        if CALLS:
            other = next(iter(CALLS.values()))
            raise CallError("%s is already listening to a call. End it first." % other["name"])
        CALLS[emp_id] = {"starting": True, "name": "Someone"}
    try:
        return _start(emp_id, by, title, on_end, mic)
    except Exception:
        with LOCK:
            CALLS.pop(emp_id, None)
        raise


DEMO_LINES = [   # `orbit demo`: a pretend supplier call, a line every few seconds
    ("Them", "Hi Alex, thanks for making time. I've got the new price list for the Ethiopian beans."),
    ("You", "Great. Where did you land on the 20 kilo bags?"),
    ("Them", "Thirty one dollars a kilo from December, up from twenty eight. Freight went up again."),
    ("You", "That's more than ten percent. Can you hold twenty eight if we commit to three months?"),
    ("Them", "I can do twenty nine fifty on a three month order, paid on delivery."),
    ("You", "Okay. Send me that in writing and I'll confirm by Friday."),
    ("Them", "Will do. Also, the Colombian lot is delayed two weeks, it ships on the 20th now."),
    ("You", "Noted. Let's talk again after I've checked the numbers."),
]


def _demo_loop(st):
    i = 0
    while not st["stop"].wait(4) and i < len(DEMO_LINES):
        who, text = DEMO_LINES[i]
        line = "[%s] %s: %s" % (_stamp(8 + i * 14), who, text)
        with open(st["transcript_abs"], "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        st["lines"] += 1
        st["last"] = line
        i += 1
    st["stop"].wait()
    os.makedirs(st["audio"], exist_ok=True)
    _finish(st)


def _start(emp_id, by, title, on_end, mic):
    demo = bool(os.environ.get("STAFFROOM_DEMO"))
    ok, why = (True, "") if demo else ready()
    if not ok:
        raise CallError(why)
    emp = engine.employee(emp_id)
    ws = emp["workspace"]
    title = (title or "").strip()[:80] or "Call"
    slug = re.sub(r"[^\w]+", "-", title, flags=re.UNICODE).strip("-").lower()[:40] or "call"
    now = dt.datetime.now()
    d = os.path.join(ws, "notes", "meetings", "%s-%s" % (now.strftime("%Y-%m-%d-%H%M"), slug))
    audio = os.path.join(d, ".audio")
    os.makedirs(audio, exist_ok=True)
    if demo:
        return _launched(emp_id, emp, by, title, now, d, audio, ws, on_end, _demo_loop)
    extra = ["--max-min", str(MAX_MIN)] + ([] if mic else ["--no-mic"])
    proc = None
    if osinfo.KIND == "mac":
        app = listener_app()
        subprocess.run(["open", "-n", "-g", "-a", app, "--args", audio] + extra, capture_output=True, timeout=30)
    else:
        try:
            if osinfo.KIND == "wsl":
                cmd = (osinfo.win_python() or []) + [osinfo.win_path(PY_SRC), osinfo.win_path(audio)]
                cwd = "/mnt/c" if os.path.isdir("/mnt/c") else None
            else:
                cmd, cwd = [sys.executable, PY_SRC, audio], None
            log = open(os.path.join(audio, "listener.log"), "ab")
            proc = subprocess.Popen(cmd + extra, stdout=log, stderr=log, stdin=subprocess.DEVNULL, cwd=cwd,
                                    start_new_session=True)
        except OSError as e:
            shutil.rmtree(d, ignore_errors=True)
            raise CallError("Orbit Listener didn't start (%s). Run  orbit doctor" % e)
    err = os.path.join(audio, "error.txt")
    t_end = time.time() + (20 if osinfo.KIND == "mac" else 40)   # Windows Python is slower to start
    while time.time() < t_end:
        if os.path.exists(err) or os.path.exists(os.path.join(audio, "listener.pid")):
            break
        if os.path.exists(os.path.join(audio, "asking.txt")):
            t_end = max(t_end, time.time() + 5)               # macOS is showing the microphone prompt: wait for the click
        time.sleep(0.25)
        if proc is not None and proc.poll() is not None:
            break
        time.sleep(0.25)
    if os.path.exists(err) or not os.path.exists(os.path.join(audio, "listener.pid")):
        msg = ""
        if os.path.exists(err):
            with open(err, encoding="utf-8") as fh:
                msg = fh.read().strip()
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(d, ignore_errors=True)
        if msg.startswith("NEEDS_PERMISSION"):
            raise CallError(PERMISSION_HELP)
        if msg.startswith("NEEDS_SETUP"):
            raise CallError(WIN_SETUP if osinfo.KIND == "wsl" else
                            "Live calls need one Python package: python3 -m pip install --user soundcard numpy")
        raise CallError(msg or "Orbit Listener didn't start. Try again; if it keeps failing, run  orbit doctor")
    return _launched(emp_id, emp, by, title, now, d, audio, ws, on_end, _loop, proc)


def _launched(emp_id, emp, by, title, now, d, audio, ws, on_end, loop, proc=None):
    tpath = os.path.join(d, "transcript.md")
    with open(tpath, "w", encoding="utf-8") as fh:
        fh.write(osinfo.local("# Live call: %s\n\nStarted %s by %s · heard on this Mac (Them = what the Mac played, You = the "
                 "microphone) · transcribed locally, so check numbers and names\n\n") % (title, now.strftime("%Y-%m-%d %H:%M"), by))
    st = {"emp_id": emp_id, "name": emp["name"], "by": by, "title": title, "started": now.strftime("%Y-%m-%dT%H:%M:%S"),
          "t0": time.time(), "dir": d, "audio": audio, "ws": ws, "transcript_abs": tpath,
          "transcript": os.path.relpath(tpath, ws), "offset": {k: 0 for k, _ in STREAMS}, "lines": 0, "last": "",
          "stop": threading.Event(), "on_end": on_end, "proc": proc}
    with open(os.path.join(audio, "call.json"), "w") as fh:
        json.dump({k: st[k] for k in ("emp_id", "by", "title", "started")}, fh)
    th = threading.Thread(target=loop, args=(st,), daemon=True)
    st["thread"] = th
    with LOCK:
        CALLS[emp_id] = st
    th.start()
    return public(st)


def _loop(st):
    while not st["stop"].wait(CHUNK_S):
        _consume(st)
        if not _listening(st):                           # the time cap, or the listener was quit
            break
    _finish(st)


def _finish(st):
    open(os.path.join(st["audio"], "stop"), "w").close()
    for _ in range(40):
        if not _listening(st):
            break
        time.sleep(0.25)
    if st.get("proc") is not None and st["proc"].poll() is None:
        try:
            st["proc"].wait(5)
        except subprocess.TimeoutExpired:
            st["proc"].kill()
    _consume(st, final=True)
    mins = round((time.time() - st["t0"]) / 60, 1)
    with open(st["transcript_abs"], encoding="utf-8") as fh:
        body = fh.read()
    here = osinfo.local("· heard on this Mac")
    body = body.replace(here, "· %s min %s" % (mins, here), 1)
    if not st["lines"]:
        body += {"mac": "(Nothing was heard. Was the call's sound on, and is Orbit Listener allowed in System Settings?)\n",
                 "wsl": "(Nothing was heard. Was the call's sound on, and is the microphone allowed in Windows Settings?)\n",
                 }.get(osinfo.KIND, "(Nothing was heard. Was the call's sound on, and is the microphone working?)\n")
    with open(st["transcript_abs"], "w", encoding="utf-8") as fh:
        fh.write(body)
    if not st.get("errors"):
        shutil.rmtree(st["audio"], ignore_errors=True)    # transcript written: raw audio goes
    with LOCK:
        CALLS.pop(st["emp_id"], None)
    info = {"dir": os.path.relpath(st["dir"], st["ws"]), "transcript": st["transcript"],
            "minutes": os.path.relpath(os.path.join(st["dir"], "minutes.md"), st["ws"]),
            "duration_min": mins, "chars": len(body), "lines": st["lines"], "title": st["title"], "by": st["by"]}
    if st.get("on_end") and st["lines"]:
        try:
            st["on_end"](st["emp_id"], info)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("call on_end failed: %s\n" % e)
    return info


def stop(emp_id=None):
    """Ends the call (for that employee, or whichever is listening). → status dict, or None if nobody was."""
    with LOCK:
        st = CALLS.get(emp_id) if emp_id else next(iter(CALLS.values()), None)
    if not st or st.get("starting"):
        return None
    st["stop"].set()
    return {**public(st), "ending": True}


def public(st):
    return {"employee": st["emp_id"], "name": st["name"], "by": st["by"], "title": st["title"], "started": st["started"],
            "minutes": round((time.time() - st["t0"]) / 60, 1), "lines": st["lines"], "last": st["last"],
            "transcript": st["transcript"], "ending": st["stop"].is_set()}


def status():
    with LOCK:
        return {k: public(v) for k, v in CALLS.items() if not v.get("starting")}


def live_note(emp_id):
    """Context for a chat run while that employee is on a call."""
    with LOCK:
        st = CALLS.get(emp_id)
    if not st or st.get("starting"):
        return ""
    return ("\n\n[You are listening to a live call right now: \"%s\", started %s. The running transcript is %s (updated "
            "every 30 s; Them = the other side, You = the owner). If the owner asks about the call, Read it first and "
            "answer from it, quoting the line and its time. Keep answers short: they're on the call.]"
            % (st["title"], st["started"][11:16], st["transcript"]))


def recover(on_end=None):
    """After a restart: stop any listener left running and turn what it heard into a transcript."""
    try:
        reg = engine.registry().get("employees", {})
    except Exception:  # noqa: BLE001
        return
    for eid in reg:
        try:
            ws = engine.employee(eid)["workspace"]
        except Exception:  # noqa: BLE001
            continue
        for base in sorted(_glob_audio(ws)):
            try:
                with open(os.path.join(base, "call.json")) as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            d = os.path.dirname(base)
            st = {"emp_id": eid, "name": reg[eid].get("name", eid), "by": meta.get("by", ""), "title": meta.get("title", "Call"),
                  "started": meta.get("started", ""), "t0": time.time(), "dir": d, "audio": base, "ws": ws,
                  "transcript_abs": os.path.join(d, "transcript.md"), "transcript": os.path.relpath(os.path.join(d, "transcript.md"), ws),
                  "offset": {k: 0 for k, _ in STREAMS}, "lines": 0, "last": "", "stop": threading.Event(), "on_end": on_end}
            try:
                st["t0"] = dt.datetime.strptime(meta["started"], "%Y-%m-%dT%H:%M:%S").timestamp()
            except (KeyError, ValueError):
                pass
            with open(st["transcript_abs"], "w", encoding="utf-8") as fh:   # offsets weren't saved: redo from the start
                fh.write(osinfo.local("# Live call: %s\n\nStarted %s by %s · heard on this Mac (recovered after a restart)\n\n")
                         % (st["title"], st["started"].replace("T", " ")[:16], st["by"]))
            threading.Thread(target=_finish, args=(st,), daemon=True).start()


def _glob_audio(ws):
    root = os.path.join(ws, "notes", "meetings")
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return [os.path.join(root, n, ".audio") for n in names if os.path.isdir(os.path.join(root, n, ".audio"))]
