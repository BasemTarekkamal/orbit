#!/usr/bin/env python3
"""Voice-over for a Short: one WAV per line, plus lines.json, the timing everything else follows.

    python vo.py script.json out/

script.json: {"voice": "am_michael", "speed": 1.12, "lang": "en-us",
              "lines": [["l0", "Hook question in under two seconds?", 0.35], ["l1", "One fact per line.", 0.45], ...]}
Writes out/<id>.wav per line (silence trimmed) and out/lines.json:
  {"lines": [{"id", "text", "dur", "start"}], "T": total seconds}
Voices (Kokoro, English): am_michael (energetic male, 1.10-1.15), af_heart (warm female, 0.95-1.0), and others
in the voices file. Write numbers as words ("twenty three"), acronyms with dots ("A.P.K."). No Arabic in Kokoro:
for Arabic, drop recorded WAVs named <id>.wav into out/ and run with --from-wavs to time them instead.
Needs: kokoro-onnx, soundfile, numpy (setup.sh installs them) and the model files in models/.
"""
import json
import os
import sys

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    from_wavs = "--from-wavs" in sys.argv
    os.makedirs(out, exist_ok=True)
    kokoro = None
    if not from_wavs:
        import shutil
        import espeakng_loader
        from kokoro_onnx import EspeakConfig, Kokoro
        data = espeakng_loader.get_data_path()
        if len(data) > 150:                     # espeak-ng can't open its data from a very long path: a short copy
            import tempfile
            short = os.path.join(tempfile.gettempdir(), "orbit-espeak-ng-data")
            if not os.path.isdir(short):
                shutil.copytree(data, short)
            data = short
        kokoro = Kokoro(os.path.join(HERE, "models", "kokoro-v1.0.int8.onnx"), os.path.join(HERE, "models", "voices-v1.0.bin"),
                        espeak_config=EspeakConfig(lib_path=espeakng_loader.get_library_path(), data_path=data))
    meta, t = [], 0.25
    for line_id, text, gap in spec["lines"]:
        path = os.path.join(out, "%s.wav" % line_id)
        if from_wavs:
            a, sr = sf.read(path)
            a = a.mean(1) if a.ndim > 1 else a
        else:
            a, sr = kokoro.create(text, voice=spec.get("voice", "am_michael"), speed=float(spec.get("speed", 1.12)),
                                  lang=spec.get("lang", "en-us"))
        a = np.asarray(a, dtype=np.float32)
        nz = np.where(np.abs(a) > 0.01)[0]
        if len(nz):
            a = a[max(0, nz[0] - 120): min(len(a), nz[-1] + 900)]
        sf.write(path, a, sr)
        d = len(a) / sr
        meta.append({"id": line_id, "text": text, "dur": round(d, 3), "start": round(t, 3)})
        t += d + float(gap)
    json.dump({"lines": meta, "T": round(t + 0.3, 2)}, open(os.path.join(out, "lines.json"), "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    print("%d lines, %.1f s: %s" % (len(meta), t + 0.3, os.path.join(out, "lines.json")))


if __name__ == "__main__":
    main()
