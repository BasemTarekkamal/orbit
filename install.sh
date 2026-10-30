#!/bin/sh
# Installs the kit's few dependencies, puts `orbit` on your PATH, starts the team's service and opens
# the control panel, where you set up your team in the browser. Safe to run again. No sudo.
#   ./install.sh          asks about the optional voice-notes tools
#   ./install.sh --yes    asks nothing (how Claude runs it, from SETUP.md)
set -e
cd "$(dirname "$0")"
KIT=$(pwd -P)
YES=""
[ "$1" = "--yes" ] && YES=1

if [ "$(uname)" != "Darwin" ]; then
  echo "This kit runs on macOS for now (it uses the macOS sandbox and launchd)."; exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Run: xcode-select --install   then run this again."; exit 1
fi
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ] && [ ! -x "$HOME/.claude/local/claude" ]; then
  echo "Claude Code is missing. Install it with Anthropic's installer:"
  echo "  curl -fsSL https://claude.ai/install.sh | bash"
  echo "then run 'claude auth login' to sign in with your own Claude account, and run this again."; exit 1
fi

echo "1/4  Python packages for the page reader, the browser, documents and chat (your user only)…"
python3 -m pip install --user --quiet --upgrade requests beautifulsoup4 playwright pypdf websocket-client
# Apple's Python links LibreSSL; urllib3 v2 warns about it on every run. Keep the quiet 1.x line there.
if python3 -c 'import ssl,sys; sys.exit(0 if "LibreSSL" in ssl.OPENSSL_VERSION else 1)' 2>/dev/null; then
  python3 -m pip install --user --quiet "urllib3<2"
fi

echo "2/4  The headless browser employees research with (Chromium, about 150 MB)…"
python3 -m playwright install chromium

echo "3/4  Voice notes and call recordings, transcribed on this Mac (optional)…"
if [ -n "$YES" ]; then
  echo "     Skipped. Later: brew install ffmpeg whisper-cpp && orbit doctor --get-voice-model"
elif command -v brew >/dev/null 2>&1; then
  printf "     Install ffmpeg and whisper.cpp with Homebrew now? (y/N) "
  read -r a
  case "$a" in y*|Y*) brew install ffmpeg whisper-cpp && "$KIT/orbit" doctor --get-voice-model >/dev/null || true ;; esac
else
  echo "     Skipped (no Homebrew). Later: brew install ffmpeg whisper-cpp && orbit doctor --get-voice-model"
fi

echo "4/4  The orbit command and the team's service…"
mkdir -p "$HOME/.local/bin"
ln -sf "$KIT/orbit" "$HOME/.local/bin/orbit"
ln -sf "$KIT/staff" "$HOME/.local/bin/staff"   # the old name keeps working
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "     Add this to your ~/.zshrc so 'orbit' works everywhere:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
"$KIT/orbit" start
echo
echo "Done. Your control panel is opening in your browser: it asks your name and what your business does,"
echo "then you pick your first employee. Open it again any time with: orbit panel"
"$KIT/orbit" panel
