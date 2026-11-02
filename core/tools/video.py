#!/usr/bin/env python3
"""staff-video: study a public video (YouTube, TikTok, Instagram, X, Facebook, Vimeo… anything yt-dlp reads):
its details, what's said in it, and what it looks like, so an employee can learn how it was made.

    staff-video <url> [--frames 12] [--minutes 20] [--no-frames]

Saves into <workspace>/research/videos/<id>/:
  info.json        title, channel, description, tags, chapters, duration, views, date, link
  transcript.txt   the captions (the creator's or automatic), else a local whisper transcript of the first
                   --minutes (needs ffmpeg + whisper-cli + the speech model, like voice notes)
  frames/NN.jpg    --frames stills spread over the video (needs ffmpeg): look at them with the Read tool
and prints a summary: title, description, tags, chapters, the start of the transcript, the frame paths.
Read the description and the transcript for the tools, voice, music and edit they name.

Runs outside the sandbox (a toolbelt gateway): public http(s) links only, never this computer or its
network; read-only, no login, no cookies. Needs yt-dlp (Mac: `brew install yt-dlp`; elsewhere pip).
Exit codes: 0 ok, 1 failed, 2 bad usage.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402

MAX_DOWNLOAD_MIN = 90          # longer videos: details and captions only, no frames or transcription


def _bin(name):
    return shutil.which(name) or next((p for p in ("/opt/homebrew/bin/" + name, "/usr/local/bin/" + name,
                                                   os.path.expanduser("~/.local/bin/") + name) if os.path.exists(p)), None)


def _ydl():
    """The yt-dlp program first (Homebrew's or the official standalone build: sites change weekly and it keeps
    up), the Python module only as a fallback (on old Pythons it's frozen at an old release)."""
    exe = _bin("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass
    raise RuntimeError("yt-dlp isn't installed. Mac: brew install yt-dlp. Windows/Linux: python3 -m pip install --user yt-dlp")


def _run(cmd, timeout, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:300] if (r.stderr or r.stdout).strip() else "failed")
    return r.stdout


def _vtt_text(path):
    """Captions file → plain text, without timings, tags or the repeated lines automatic captions carry."""
    out, last = [], ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line.isdigit():
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line and line != last:
                out.append(line)
                last = line
    return " ".join(out)


def _model():
    for p in (os.environ.get("WHISPER_MODEL"), os.path.join(_kit.HOME, "models", "ggml-large-v3-turbo-q5_0.bin")):
        if p and os.path.exists(os.path.expanduser(p)):
            return os.path.expanduser(p)
    return None


def study(url, frames=12, minutes=20, want_frames=True):
    url = _kit.safe_url(url)
    ydl = _ydl()
    info = json.loads(_run(ydl + ["--dump-single-json", "--no-playlist", "--no-warnings", url], 180))
    vid = re.sub(r"[^\w-]+", "-", "%s-%s" % (info.get("extractor_key", "video"), info.get("id", "x"))).strip("-").lower()[:80]
    out = _kit.out_dir("research", "videos", vid)
    keep = {k: info.get(k) for k in ("title", "uploader", "channel", "channel_url", "description", "tags", "categories",
                                     "chapters", "duration", "view_count", "like_count", "comment_count", "upload_date",
                                     "webpage_url", "width", "height", "fps")}
    with open(os.path.join(out, "info.json"), "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=1, ensure_ascii=False)
    notes = []
    transcript = ""
    with tempfile.TemporaryDirectory() as td:
        try:                                               # captions first: fast and exact
            _run(ydl + ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,ar.*,.*orig",
                        "--sub-format", "vtt", "--no-playlist", "-o", os.path.join(td, "c.%(ext)s"), url], 180)
            subs = sorted(glob.glob(os.path.join(td, "c*.vtt")), key=lambda p: ("orig" not in p, "-" in os.path.basename(p)))
            if subs:
                transcript = _vtt_text(subs[0])
                notes.append("transcript from captions (%s)" % os.path.basename(subs[0]).split(".", 1)[1].rsplit(".", 1)[0])
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            notes.append("no captions (%s)" % str(e)[:80])
        dur = float(info.get("duration") or 0)
        ff = _bin("ffmpeg")
        need_media = (want_frames and frames > 0) or not transcript
        if need_media and dur and dur > MAX_DOWNLOAD_MIN * 60:
            notes.append("longer than %d min: details and captions only" % MAX_DOWNLOAD_MIN)
            need_media = False
        if need_media and not ff:
            notes.append("ffmpeg isn't installed, so no frames or local transcript")
            need_media = False
        if need_media:
            media = os.path.join(td, "v.mp4")
            _run(ydl + ["-f", "b[height<=480]/bv*[height<=480]+ba/b", "--merge-output-format", "mp4", "--no-playlist",
                        "-o", media, url], 900)
            media = media if os.path.exists(media) else (glob.glob(os.path.join(td, "v.*")) or [media])[0]
            if want_frames and frames > 0:
                fdir = os.path.join(out, "frames")
                shutil.rmtree(fdir, ignore_errors=True)
                os.makedirs(fdir)
                span = dur or 60
                for i in range(frames):
                    t = span * (i + 0.5) / frames
                    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "%.2f" % t, "-i", media, "-frames:v", "1",
                                    "-vf", "scale=640:-2", os.path.join(fdir, "%02d.jpg" % (i + 1))], timeout=60)
                notes.append("%d frames" % len(glob.glob(os.path.join(fdir, "*.jpg"))))
            if not transcript:
                wh, model = _bin("whisper-cli"), _model()
                if wh and model:
                    wav = os.path.join(td, "a.wav")
                    subprocess.run([ff, "-y", "-loglevel", "error", "-i", media, "-t", str(minutes * 60), "-ar", "16000",
                                    "-ac", "1", wav], check=True, timeout=300)
                    r = subprocess.run([wh, "-m", model, "-l", "auto", "-nt", "-np", "-f", wav], capture_output=True,
                                       text=True, timeout=1800)
                    transcript = " ".join(l.strip() for l in r.stdout.splitlines() if l.strip())
                    notes.append("transcript by whisper on this computer (first %d min)" % minutes)
                else:
                    notes.append("no captions and no speech model: no transcript (orbit doctor --get-voice-model)")
    if transcript:
        with open(os.path.join(out, "transcript.txt"), "w", encoding="utf-8") as fh:
            fh.write(transcript + "\n")
    return out, keep, transcript, notes


def main(argv=None):
    ap = argparse.ArgumentParser(prog="staff-video", description="Study a public video: details, transcript, frames.")
    ap.add_argument("url")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--minutes", type=int, default=20, help="how much audio to transcribe when there are no captions")
    ap.add_argument("--no-frames", action="store_true")
    a = ap.parse_args(argv)
    _kit.require("web")
    try:
        out, info, transcript, notes = study(a.url, max(0, min(a.frames, 40)), max(1, min(a.minutes, 120)), not a.no_frames)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1
    mins = int(info.get("duration") or 0) // 60
    print("%s (%s, %d min, %s views, %s)" % (info.get("title"), info.get("uploader") or info.get("channel"), mins,
                                            info.get("view_count"), info.get("upload_date")))
    print("Saved in %s (info.json%s%s)" % (out, ", transcript.txt" if transcript else "",
                                          ", frames/" if os.path.isdir(os.path.join(out, "frames")) else ""))
    print("Notes: " + "; ".join(notes))
    if info.get("tags"):
        print("Tags: " + ", ".join(info["tags"][:30]))
    if info.get("chapters"):
        print("Chapters: " + " | ".join("%d:%02d %s" % (c["start_time"] // 60, c["start_time"] % 60, c.get("title", ""))
                                        for c in info["chapters"][:20]))
    print("\nDescription:\n" + (info.get("description") or "(none)")[:2500])
    if transcript:
        print("\nTranscript (start):\n" + transcript[:3000])
    frames = sorted(glob.glob(os.path.join(out, "frames", "*.jpg")))
    if frames:
        print("\nFrames (look at them with Read): " + ", ".join(frames))
    return 0


if __name__ == "__main__":
    sys.exit(main())
