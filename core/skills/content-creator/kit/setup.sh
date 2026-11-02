#!/bin/sh
# One-time setup of the content kit in this folder (copy the kit into your own tools/ first): Node packages
# (three, playwright + its Chromium), a Python env for the voice (kokoro-onnx) and the voice model files.
# Free and local, about 400 MB. Safe to run again.
set -e
cd "$(dirname "$0")"
command -v node >/dev/null 2>&1 || { echo "Needs Node.js (Mac: brew install node; Linux/WSL: sudo apt install nodejs npm)"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "Needs ffmpeg (Mac: brew install ffmpeg; Linux/WSL: setup-linux.sh)"; exit 1; }
[ -d node_modules/three ] || npm install --silent --no-audit --no-fund three@0.160.0 playwright@1
npx --yes playwright install chromium >/dev/null
# The voice needs Python 3.10+: uv fetches its own small copy into .py/ when the system one is older
if [ ! -x .venv/bin/python ]; then
  UV=$(command -v uv || true)
  if [ -z "$UV" ]; then python3 -m pip install --user --quiet uv 2>/dev/null || python3 -m pip install --user --quiet --break-system-packages uv; UV="python3 -m uv"; fi
  UV_PYTHON_INSTALL_DIR="$PWD/.py" $UV venv --quiet --python 3.11 .venv
fi
if [ -x .venv/bin/pip ]; then .venv/bin/pip install --quiet kokoro-onnx soundfile scipy numpy
else ${UV:-uv} pip install --quiet --python .venv/bin/python kokoro-onnx soundfile scipy numpy; fi
mkdir -p models
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  if [ ! -s "models/$f" ]; then
    curl -L --fail --silent --show-error -o "models/$f.part" "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
    mv "models/$f.part" "models/$f"
  fi
done
echo "Content kit ready. Next: edit script.json and short.json, then ./make.sh"
