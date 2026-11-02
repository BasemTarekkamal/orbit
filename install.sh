#!/bin/sh
# Installs the kit's few dependencies, puts `orbit` on your PATH, starts the team's service and opens
# the control panel, where you set up your team in the browser. Safe to run again. No sudo: on Windows (WSL)
# and Linux, the system packages come first from setup-linux.sh, which you run once with sudo yourself.
#   ./install.sh          asks about the optional voice-notes tools
#   ./install.sh --yes    asks nothing (how Claude runs it, from SETUP.md)
set -e
cd "$(dirname "$0")"
KIT=$(pwd -P)
YES=""
[ "$1" = "--yes" ] && YES=1

MAC=""
[ "$(uname)" = "Darwin" ] && MAC=1
if [ -z "$MAC" ] && [ "$(uname)" != "Linux" ]; then
  echo "Orbit runs on a Mac, on Windows (inside WSL: see the README) or on Linux."; exit 1
fi
if [ -z "$MAC" ]; then
  # Windows (WSL) and Linux: the sandbox needs bubblewrap and socat; pip and git come from the system too.
  MISSING=""
  for b in python3 git bwrap socat; do command -v "$b" >/dev/null 2>&1 || MISSING="$MISSING $b"; done
  python3 -m pip --version >/dev/null 2>&1 || MISSING="$MISSING pip"
  if [ -n "$MISSING" ]; then
    echo "First, a few system packages (missing:$MISSING). Run this once; it asks for your Linux password:"
    echo
    echo "  sudo sh $KIT/setup-linux.sh"
    echo
    echo "then run this again."; exit 1
  fi
  if uname -r | grep -q -- '-Microsoft$'; then         # WSL 1's kernel name; WSL 2's says microsoft-standard
    echo "This is WSL 1, which can't keep your crew in a sandbox. In PowerShell run:  wsl --set-version ${WSL_DISTRO_NAME:-Ubuntu} 2"
    exit 1
  fi
elif ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Run: xcode-select --install   then run this again."; exit 1
fi
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ] && [ ! -x "$HOME/.claude/local/claude" ]; then
  echo "Claude Code is missing. Install it with Anthropic's installer:"
  echo "  curl -fsSL https://claude.ai/install.sh | bash"
  echo "then run 'claude auth login' to sign in with your own Claude account, and run this again."; exit 1
fi

echo "1/4  Python packages for the page reader, the browser, documents and chat (your user only)…"
PKGS="requests beautifulsoup4 playwright pypdf websocket-client"
# Videos the crew studies (staff-video): yt-dlp, kept current (sites change weekly)
if [ -n "$MAC" ]; then
  command -v brew >/dev/null 2>&1 && { brew list yt-dlp >/dev/null 2>&1 || brew install yt-dlp >/dev/null 2>&1 || true; }
else
  PKGS="$PKGS yt-dlp"
fi
# Linux desktops hear calls through these (on Windows, Python for Windows does: see orbit doctor)
[ -z "$MAC" ] && ! grep -qi microsoft /proc/version 2>/dev/null && PKGS="$PKGS soundcard numpy"
# Newer Linux marks its Python "externally managed": --user packages are fine, pip just needs telling
python3 -m pip install --user --quiet --upgrade $PKGS 2>/dev/null || \
  python3 -m pip install --user --quiet --upgrade --break-system-packages $PKGS
# Apple's Python links LibreSSL; urllib3 v2 warns about it on every run. Keep the quiet 1.x line there.
if python3 -c 'import ssl,sys; sys.exit(0 if "LibreSSL" in ssl.OPENSSL_VERSION else 1)' 2>/dev/null; then
  python3 -m pip install --user --quiet "urllib3<2"
fi

echo "2/4  The headless browser employees research with (Chromium, about 150 MB)…"
python3 -m playwright install chromium

echo "3/4  Voice notes and call recordings, transcribed on this computer (optional)…"
if [ -z "$MAC" ]; then
  if [ -n "$YES" ]; then
    echo "     Skipped. Later: orbit doctor --get-whisper --get-voice-model"
  else
    printf "     Build the speech engine and download its model now (a few minutes, ~550 MB)? (y/N) "
    read -r a
    case "$a" in y*|Y*) "$KIT/orbit" doctor --get-whisper --get-voice-model >/dev/null || true ;; esac
  fi
elif [ -n "$YES" ]; then
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
  *) echo "     Add this to your ~/.zshrc (on Linux ~/.bashrc) so 'orbit' works everywhere:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
"$KIT/orbit" start
echo
echo "Done. Your control panel is opening in your browser: it asks your name and what your business does,"
echo "then you pick your first employee. Open it again any time with: orbit panel"
"$KIT/orbit" panel
