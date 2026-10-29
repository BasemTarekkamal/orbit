#!/bin/sh
# Installs the kit's few dependencies, puts `staff` on your PATH, then runs `staff setup`.
# Safe to run again. Nothing here needs sudo.
set -e
cd "$(dirname "$0")"
KIT=$(pwd -P)

if [ "$(uname)" != "Darwin" ]; then
  echo "This kit runs on macOS for now (it uses the macOS sandbox and launchd)."; exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Run: xcode-select --install   then run this again."; exit 1
fi
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ] && [ ! -x "$HOME/.claude/local/claude" ]; then
  echo "Claude Code is missing. Install it (https://claude.com/claude-code), run 'claude' once to sign in"
  echo "with your own Claude account, then run this again."; exit 1
fi

echo "1/4  Python packages for the page reader, the browser and documents (your user only)…"
python3 -m pip install --user --quiet --upgrade requests beautifulsoup4 playwright pypdf

echo "2/4  The headless browser (Chromium for Playwright, ~150 MB)…"
python3 -m playwright install chromium

echo "3/4  Voice notes and meeting recordings, transcribed on this Mac (optional)…"
if command -v brew >/dev/null 2>&1; then
  printf "     Install ffmpeg and whisper.cpp with Homebrew now? (y/N) "
  read -r a
  case "$a" in y*|Y*) brew install ffmpeg whisper-cpp && "$KIT/staff" doctor --get-voice-model >/dev/null || true ;; esac
else
  echo "     Skipped (no Homebrew). Later: brew install ffmpeg whisper-cpp && staff doctor --get-voice-model"
fi

echo "4/4  The staff command…"
mkdir -p "$HOME/.local/bin"
ln -sf "$KIT/staff" "$HOME/.local/bin/staff"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "     Add this to your ~/.zshrc so 'staff' works everywhere:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo
exec "$KIT/staff" setup
