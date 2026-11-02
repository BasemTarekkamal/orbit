#!/usr/bin/env python3
"""The Short's sound: the voice-over at its times, a synthesized music bed that ducks under the voice, a whoosh
on every cut, and a soft master. All generated here, so no stock music and no copyright risk.

    python mix.py out/lines.json out/ audio.wav [--bpm 96] [--no-music]

Reads out/<id>.wav for each line. Writes a 48 kHz stereo WAV. Loudness is set later, when muxing (-14 LUFS).
Add your own beats (an impact at a key moment, music dropping out before a reveal) by editing `moments` below
or passing --drop <seconds> to cut the music for one beat there.
Needs: numpy, scipy, soundfile.
"""
import argparse
import json
import os

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

SR = 48000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lines"); ap.add_argument("wavs"); ap.add_argument("out")
    ap.add_argument("--bpm", type=float, default=96); ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--drop", type=float, action="append", default=[], help="music drops out for one beat here")
    a = ap.parse_args()
    tl = json.load(open(a.lines, encoding="utf-8"))
    T = float(tl["T"])
    N = int((T + 0.05) * SR)
    rng = np.random.default_rng(11)
    lp = lambda x, f: sosfilt(butter(2, f / (SR / 2), output="sos"), x)
    hp = lambda x, f: sosfilt(butter(2, f / (SR / 2), "high", output="sos"), x)
    bp = lambda x, lo, hi: sosfilt(butter(2, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)
    tt = lambda l: np.arange(int(l * SR)) / SR
    noise = lambda l: rng.normal(0, 1, int(l * SR))
    VO, MU, FX = np.zeros(N), np.zeros(N), np.zeros(N)

    def add(buf, sig, t0, g=1.0):
        i = int(t0 * SR)
        if i >= len(buf):
            return
        if i < 0:
            sig, i = sig[-i:], 0
        j = min(len(buf), i + len(sig))
        buf[i:j] += sig[:j - i] * g

    for line in tl["lines"]:
        v, sr = sf.read(os.path.join(a.wavs, "%s.wav" % line["id"]))
        v = v.mean(1) if v.ndim > 1 else v
        v = np.interp(np.arange(int(len(v) * SR / sr)) * sr / SR, np.arange(len(v)), v)
        add(VO, v / (np.max(np.abs(v)) + 1e-9) * 0.85, line["start"])
        x = tt(0.45)                                          # whoosh into every line (a cut)
        add(FX, bp(noise(0.45), 400, 5000) * np.sin(np.pi * x / 0.45) ** 2 * 0.35, line["start"] - 0.3)

    if not a.no_music:
        beat = 60.0 / a.bpm
        kick = lambda: (lambda x: np.tanh(2.2 * np.sin(2 * np.pi * np.cumsum(42 + 130 * np.exp(-x / 0.03)) / SR) * np.exp(-x / 0.2)))(tt(0.45))
        hat = lambda: hp(noise(0.05), 7000) * np.exp(-tt(0.05) / 0.012)
        snare = lambda: (lambda x: bp(noise(0.25), 1200, 7000) * np.exp(-x / 0.07) * 0.9 + np.sin(2 * np.pi * 185 * x) * np.exp(-x / 0.05) * 0.6)(tt(0.25))
        roots = [55.0, 51.9, 43.65, 49.0]
        bar = 0
        while bar * 4 * beat < T + 2:
            t0, r = bar * 4 * beat, roots[bar % 4]
            for k in range(4):
                add(MU, kick(), t0 + k * beat, 0.6)
                if k in (1, 3):
                    add(MU, snare(), t0 + k * beat, 0.22)
                for h in range(2):
                    add(MU, hat(), t0 + k * beat + h * beat / 2 + beat / 4, 0.07)
            x = tt(4 * beat)
            tb = x % (beat / 2)
            add(MU, np.tanh(2 * np.sin(2 * np.pi * r * x)) * 0.25 * np.exp(-tb / 0.2) * (1 - np.exp(-tb / 0.004)), t0)
            add(MU, lp(np.sin(2 * np.pi * r * 4 * x) + 0.5 * np.sin(2 * np.pi * r * 6 * x), 1800) * 0.05, t0)
            bar += 1
        for d in a.drop:                                       # music out for one beat, then slams back
            i, j = int(d * SR), int((d + 60.0 / a.bpm) * SR)
            MU[max(0, i):min(N, j)] *= 0.05

    env, e, av = np.zeros(N), 0.0, np.abs(VO)                 # duck the music under the voice
    for i in range(0, N, 32):
        blk = av[i:i + 32].max()
        e = e + (blk - e) * (0.3 if blk > e else 0.004)
        env[i:i + 32] = e
    mix = VO + MU * (1 - 0.7 * np.clip(env / 0.3, 0, 1)) * 0.5 + FX
    mix = np.tanh(mix * 1.1)
    mix = mix / (np.max(np.abs(mix)) + 1e-9) * 0.93
    sf.write(a.out, np.stack([mix, mix], 1).astype(np.float32), SR)
    print("mixed %.1f s → %s" % (T, a.out))


if __name__ == "__main__":
    main()
