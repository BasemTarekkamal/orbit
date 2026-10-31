"""Orbit Listener for Windows and Linux: what this computer plays (the other side of a call) and its
microphone (you), as two raw 16 kHz mono float32 files, until <dir>/stop appears or the time cap.
The Mac uses call_listen.swift; both write the same files, so core/calls.py treats them the same.

    python call_listen.py <dir> [--max-min 180] [--no-mic]

Writes <dir>/them.pcm, <dir>/you.pcm, <dir>/listener.pid, <dir>/alive (touched every second while
listening) and <dir>/error.txt (one plain line) on failure. On Windows it runs with Python for Windows
(started from WSL by core/calls.py, since Linux inside WSL can't hear Windows apps) and records with
WASAPI loopback; on Linux, PulseAudio or PipeWire. Needs: pip install soundcard numpy. Standalone on
purpose (no kit imports): Windows Python runs it straight from the kit folder. Nothing leaves the computer.
"""
import os
import sys
import threading
import time
import warnings

SR = 16000
REC_SR = 48000          # what sound cards give natively; averaged down 3:1 to 16 kHz
BLOCK = 4800            # 0.1 s at 48 kHz

args = sys.argv[1:]
if not args:
    sys.stderr.write("usage: call_listen.py <dir> [--max-min N] [--no-mic]\n")
    sys.exit(64)
DIR = args[0]
MAX_MIN = 180.0
if "--max-min" in args:
    try:
        MAX_MIN = float(args[args.index("--max-min") + 1])
    except (IndexError, ValueError):
        pass
WANT_MIC = "--no-mic" not in args
os.makedirs(DIR, exist_ok=True)
STOP = threading.Event()
ERRORS = []


def fail(msg, code=2):
    try:
        with open(os.path.join(DIR, "error.txt"), "w", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass
    sys.stderr.write(msg + "\n")
    sys.exit(code)


try:
    import numpy as np
    warnings.filterwarnings("ignore")             # soundcard warns on every gap in a silent loopback
    import soundcard as sc
except Exception as e:  # noqa: BLE001
    fail("NEEDS_SETUP soundcard: %s. Install it once:  pip install soundcard numpy" % e)


def record(name, mic, t0):
    """One stream into one file. Pads silence when the device sends nothing (a silent loopback sends no
    data on Windows), so both files keep the call's real timeline and the transcript times line up."""
    path = os.path.join(DIR, name)
    written = 0
    try:
        with open(path, "ab") as fh, mic.recorder(samplerate=REC_SR, blocksize=BLOCK * 2) as rec:
            while not STOP.is_set():
                data = rec.record(numframes=BLOCK)
                if data is not None and len(data):
                    a = np.asarray(data, dtype=np.float32)
                    if a.ndim > 1:                        # a single channel records garbage on Windows: mix down here
                        a = a.mean(axis=1)
                    n = len(a) - len(a) % 3
                    a = a[:n].reshape(-1, 3).mean(axis=1).astype(np.float32)
                else:
                    a = np.zeros(0, dtype=np.float32)
                behind = int((time.time() - t0) * SR) - (written + len(a))
                if behind > SR // 2:                     # more than 0.5 s missing: the device was quiet
                    fh.write(np.zeros(behind, dtype=np.float32).tobytes())
                    written += behind
                fh.write(a.tobytes())
                written += len(a)
                fh.flush()
    except Exception as e:  # noqa: BLE001
        ERRORS.append("%s: %s" % (name, e))
        STOP.set()


def main():
    try:
        speaker = sc.default_speaker()
        them = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    except Exception as e:  # noqa: BLE001
        fail("Couldn't find this computer's speakers to listen to: %s" % e)
    you = None
    if WANT_MIC:
        try:
            you = sc.default_microphone()
        except Exception as e:  # noqa: BLE001
            fail("NEEDS_PERMISSION microphone: %s" % e)
    for f in ("them.pcm", "you.pcm"):
        open(os.path.join(DIR, f), "ab").close()
    t0 = time.time()
    threads = [threading.Thread(target=record, args=("them.pcm", them, t0), daemon=True)]
    if you is not None:
        threads.append(threading.Thread(target=record, args=("you.pcm", you, t0), daemon=True))
    for t in threads:
        t.start()
    time.sleep(0.5)
    if ERRORS:
        msg = "; ".join(ERRORS)
        fail(("NEEDS_PERMISSION microphone: " if "you.pcm" in msg and "denied" in msg.lower() else "Couldn't start listening: ") + msg)
    with open(os.path.join(DIR, "listener.pid"), "w") as fh:
        fh.write(str(os.getpid()))
    alive = os.path.join(DIR, "alive")
    stop = os.path.join(DIR, "stop")
    while not STOP.is_set():
        open(alive, "w").close()
        if os.path.exists(stop) or time.time() - t0 > MAX_MIN * 60:
            break
        time.sleep(1)
    STOP.set()
    for t in threads:
        t.join(3)
    for f in ("listener.pid", "alive"):
        try:
            os.remove(os.path.join(DIR, f))
        except OSError:
            pass
    if ERRORS:
        fail("Listening stopped: " + "; ".join(ERRORS), 3)


if __name__ == "__main__":
    main()
