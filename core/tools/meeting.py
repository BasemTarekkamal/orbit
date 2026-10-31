#!/usr/bin/env python3
"""Transcribe a meeting recording locally (whisper.cpp; free; nothing leaves the Mac).

  python3 tools/meeting.py <audio-or-video file> [--title "Supplier call"]

Accepts anything ffmpeg reads: Telegram voice notes, m4a/mp3/wav, Zoom/Meet mp4 recordings.
Writes notes/meetings/<YYYY-MM-DD-HHMM>-<slug>/transcript.md (timestamped) and prints JSON:
{"dir", "transcript", "minutes", "duration_min", "chars"}. The agent then writes minutes.md there.
Harness-owned (called by staffd.py). ROOT = the employee workspace (STAFF_WORKSPACE).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("STAFF_WORKSPACE") or os.getcwd()  # the employee's workspace
MODEL = os.path.expanduser("~/Staff/models/ggml-large-v3-turbo-q5_0.bin")


def _bin(n):
    return shutil.which(n) or next((p for p in ("/opt/homebrew/bin/" + n, os.path.expanduser("~/.local/bin/") + n)
                                    if os.path.exists(p)), "/opt/homebrew/bin/" + n)


def duration_s(path: str) -> float:
    out = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def transcribe(path: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run([_bin("ffmpeg"), "-y", "-loglevel", "error", "-i", path, "-vn", "-ar", "16000",
                        "-ac", "1", wav], check=True, timeout=1800)
        out = subprocess.run([_bin("whisper-cli"), "-m", MODEL, "-l", "auto", "-t", "8", "-np", "-f", wav],
                             capture_output=True, text=True, timeout=7200)
        if out.returncode != 0:
            raise RuntimeError("whisper failed: %s" % out.stderr[-300:])
    lines = []
    for ln in out.stdout.splitlines():
        m = re.match(r"\[(\d\d:\d\d:\d\d)\.\d+ --> [^\]]+\]\s*(.*)", ln)
        if m and m.group(2).strip():
            lines.append("[%s] %s" % (m.group(1), m.group(2).strip()))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--title", default="meeting")
    a = ap.parse_args()
    slug = re.sub(r"[^\w]+", "-", a.title, flags=re.UNICODE).strip("-").lower()[:40] or "meeting"
    d = os.path.join(ROOT, "notes", "meetings", "%s-%s" % (dt.datetime.now().strftime("%Y-%m-%d-%H%M"), slug))
    os.makedirs(d, exist_ok=True)
    dur = duration_s(a.path)
    text = transcribe(a.path)
    tpath = os.path.join(d, "transcript.md")
    with open(tpath, "w", encoding="utf-8") as fh:
        fh.write("# Transcript: %s\n\nRecorded file: %s · %.0f min · transcribed locally by whisper "
                 "(may contain recognition errors, especially numbers and names)\n\n%s\n"
                 % (a.title, os.path.basename(a.path), dur / 60, text))
    print(json.dumps({"dir": os.path.relpath(d, ROOT), "transcript": os.path.relpath(tpath, ROOT),
                      "minutes": os.path.relpath(os.path.join(d, "minutes.md"), ROOT),
                      "duration_min": round(dur / 60, 1), "chars": len(text)}, ensure_ascii=False))
    return 0 if text else 2


if __name__ == "__main__":
    sys.exit(main())
