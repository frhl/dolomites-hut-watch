#!/bin/bash
# Install the hourly Booking Suedtirol check on this Mac (launchd user agent).
#   scripts/install_launchd.sh               asks for the ntfy topic (input hidden), installs, runs once
#   scripts/install_launchd.sh --uninstall   removes it (keeps ~/.config/hutwatch)
#   scripts/install_launchd.sh --print-plist prints the plist only
set -euo pipefail
LABEL="com.hutwatch.booking-suedtirol"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CONF="$HOME/.config/hutwatch"
LOG="$HOME/Library/Logs/hutwatch-local.log"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

PY="${HUTWATCH_PYTHON:-$(command -v python3)}"
if ! "$PY" -c 'import sys, openpyxl; assert sys.version_info >= (3, 10)' 2>/dev/null; then
  echo "Need Python >= 3.10 with openpyxl. Try: $PY -m pip install openpyxl (or set HUTWATCH_PYTHON)."
  exit 1
fi

plist() {
cat <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/scripts/local_check.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HUTWATCH_PYTHON</key><string>$PY</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
}

if [ "${1:-}" = "--print-plist" ]; then plist; exit 0; fi

mkdir -p "$CONF" "$HOME/Library/LaunchAgents" "$(dirname "$LOG")"
chmod 700 "$CONF"
if [ ! -s "$CONF/ntfy_topic" ]; then
  T="${NTFY_TOPIC:-}"
  if [ -z "$T" ]; then read -rsp "ntfy topic: " T; echo; fi
  [ -n "$T" ] || { echo "No topic given."; exit 1; }
  ( umask 077; printf '%s' "$T" > "$CONF/ntfy_topic" )
fi
chmod 600 "$CONF/ntfy_topic"

plist > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $LABEL: runs hourly (and now). Python: $PY"
echo "Log: $LOG    Uninstall: $0 --uninstall"
