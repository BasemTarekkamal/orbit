#!/usr/bin/env python3
"""Transcribe a Telegram voice note / audio file locally (whisper.cpp, no cloud, no cost).

  python3 tools/transcribe.py <audio file>      # prints the transcript (Arabic or English, auto-detected)

Needs: ffmpeg and whisper-cli (brew install ffmpeg whisper-cpp) and the model at
~/Staff/models/ggml-large-v3-turbo-q5_0.bin. Exit 1 with a reason on stderr if anything is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

MODEL = os.path.expanduser(os.environ.get("WHISPER_MODEL", "~/Staff/models/ggml-large-v3-turbo-q5_0.bin"))


def _bin(name: str) -> str | None:
    return shutil.which(name) or next((p for p in ("/opt/homebrew/bin/" + name, "/usr/local/bin/" + name)
                                       if os.path.exists(p)), None)


def transcribe(path: str) -> str:
    ff, wh = _bin("ffmpeg"), _bin("whisper-cli")
    if not ff or not wh:
        raise RuntimeError("ffmpeg/whisper-cli not installed")
    if not os.path.exists(MODEL):
        raise RuntimeError("speech model missing: %s" % MODEL)
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1", wav],
                       check=True, timeout=120)
        out = subprocess.run([wh, "-m", MODEL, "-l", "auto", "-nt", "-np", "-f", wav],
                             capture_output=True, text=True, timeout=600)
        if out.returncode != 0:
            raise RuntimeError("whisper failed: %s" % out.stderr[-300:])
        return " ".join(l.strip() for l in out.stdout.splitlines() if l.strip())


if __name__ == "__main__":
    try:
        print(transcribe(sys.argv[1]))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("%s\n" % e)
        sys.exit(1)
