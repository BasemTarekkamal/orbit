#!/bin/sh
# Orbit on Windows (inside WSL) or Linux: the system packages, installed once. Run it yourself, with sudo:
#
#   sudo sh ~/orbit/setup-linux.sh
#
# It installs: bubblewrap and socat (the sandbox that keeps your crew in its own folder and on the sites you
# approve: the same sandbox Claude Code uses), git, Python's pip, ffmpeg (voice notes), tesseract with
# Arabic (reading scans and photos), poppler (PDF pages), cmake and a compiler (to build the speech engine
# once), the PulseAudio library (calls on a Linux desktop) and the libraries the headless browser needs.
# On Ubuntu 24.04 and newer it also adds the AppArmor rule Anthropic's docs give for bubblewrap.
# Nothing else on the system changes. Safe to run again.
set -e
if [ "$(id -u)" != 0 ]; then
  echo "Run it with sudo:  sudo sh $0"; exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q git curl ca-certificates python3 python3-pip python3-venv bubblewrap socat ffmpeg \
    tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng poppler-utils build-essential cmake libpulse0
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q git curl python3 python3-pip bubblewrap socat ffmpeg-free tesseract tesseract-langpack-ara \
    tesseract-langpack-eng poppler-utils gcc-c++ make cmake pulseaudio-libs
else
  echo "This script knows apt (Ubuntu, Debian) and dnf (Fedora). Install these with your package manager:"
  echo "  git python3-pip bubblewrap socat ffmpeg tesseract (+ Arabic) poppler cmake g++ libpulse"
  exit 1
fi

# Ubuntu 24.04+: AppArmor stops bubblewrap making its sandbox unless bwrap has this profile
# (from https://code.claude.com/docs/en/sandboxing). Only bwrap itself is affected.
if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null)" = "1" ] && [ ! -e /etc/apparmor.d/bwrap ]; then
  cat > /etc/apparmor.d/bwrap <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
  systemctl reload apparmor 2>/dev/null || apparmor_parser -r /etc/apparmor.d/bwrap
  echo "Added the AppArmor rule for bubblewrap."
fi

# The libraries Chromium needs (the headless browser employees research with), via Playwright's own list
if command -v apt-get >/dev/null 2>&1; then
  T=$(mktemp -d)
  python3 -m venv "$T/pw" && "$T/pw/bin/pip" install -q playwright && "$T/pw/bin/playwright" install-deps chromium \
    || echo "Couldn't add the browser's libraries; the headless browser may not start (orbit doctor will say)."
  rm -rf "$T"
fi

echo
echo "Done. Now, as yourself (no sudo):  $(cd "$(dirname "$0")" && pwd)/install.sh"
