#!/bin/sh
# script.json (the voice lines) + short.json (headlines, colours, watermark) → final.mp4 (1080x1920, 30 fps,
# -14 LUFS) and contact.jpg (12 frames: look at it before you call the video done).
set -e
cd "$(dirname "$0")"
.venv/bin/python vo.py script.json out
N=$(.venv/bin/python -c "import json,math;print(math.ceil(json.load(open('out/lines.json'))['T']*30))")
HALF=$((N / 2))
PAGE=short.html PORT=8821 node render.js 0 "$HALF" out/a.mp4 &
A=$!
PAGE=short.html PORT=8822 node render.js "$HALF" "$N" out/b.mp4 &
B=$!
wait $A && wait $B
.venv/bin/python mix.py out/lines.json out out/audio.wav
printf "file 'a.mp4'\nfile 'b.mp4'\n" > out/parts.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i out/parts.txt -i out/audio.wav -map 0:v -map 1:a -c:v libx264 -preset slow \
  -crf 20 -pix_fmt yuv420p -af loudnorm=I=-14:TP=-1.5 -c:a aac -b:a 192k -shortest -movflags +faststart final.mp4
T=$(.venv/bin/python -c "import json;print(json.load(open('out/lines.json'))['T'])")
ffmpeg -y -loglevel error -i final.mp4 -vf "fps=12/$T,scale=270:-2,tile=6x2" -frames:v 1 contact.jpg
echo "Done: final.mp4 and contact.jpg (look at contact.jpg before you deliver)"
