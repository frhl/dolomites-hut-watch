#!/bin/bash
# Install the hourly Mac check (Booking Suedtirol huts: Fanes, Lavarella, Pederue, Fodara
# Vedla - their booking API refuses GitHub's servers, so this one check runs from your Mac).
#
# It shows up as "Dolomites Hut Watch": a small app in ~/Applications whose launcher runs
# scripts/local_check.sh, so System Settings > Login Items and Activity Monitor show that
# name instead of "bash".
#
#   scripts/install_launchd.sh               asks for the ntfy topic once (input hidden), installs, runs once
#   scripts/install_launchd.sh --uninstall   removes the job and the app (keeps ~/.config/hutwatch)
#   scripts/install_launchd.sh --print-plist prints the launchd plist only
set -euo pipefail
NAME="Dolomites Hut Watch"
LABEL="com.frhl.dolomites-hut-watch"
OLD_LABELS=("com.hutwatch.booking-suedtirol")
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/$NAME.app"
EXE="$APP/Contents/MacOS/$NAME"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CONF="$HOME/.config/hutwatch"
LOG="$HOME/Library/Logs/dolomites-hut-watch.log"
DOMAIN="gui/$(id -u)"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

remove_agent() {  # $1 = label
  launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$1.plist"
}

if [ "${1:-}" = "--uninstall" ]; then
  remove_agent "$LABEL"
  for l in "${OLD_LABELS[@]}"; do remove_agent "$l"; done
  [ -d "$APP" ] && "$LSREGISTER" -u "$APP" 2>/dev/null || true
  rm -rf "$APP"
  echo "Removed $NAME ($LABEL)."
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
  <key>Program</key><string>$EXE</string>
  <key>ProgramArguments</key>
  <array><string>$EXE</string><string>$REPO/scripts/local_check.sh</string></array>
  <key>AssociatedBundleIdentifiers</key>
  <array><string>$LABEL</string></array>
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

# The tracker lives in the private state repo.
if [ ! -d "$REPO/private/.git" ]; then
  git clone -q https://github.com/frhl/dolomites-hut-watch-state.git "$REPO/private" \
    || echo "warn: could not clone the private state repo; the tracker will be missing"
fi

# ntfy topic, stored once with owner-only permissions.
mkdir -p "$CONF" "$HOME/Library/LaunchAgents" "$(dirname "$LOG")" "$HOME/Applications"
chmod 700 "$CONF"
if [ ! -s "$CONF/ntfy_topic" ]; then
  T="${NTFY_TOPIC:-}"
  if [ -z "$T" ]; then read -rsp "ntfy topic: " T; echo; fi
  [ -n "$T" ] || { echo "No topic given."; exit 1; }
  ( umask 077; printf '%s' "$T" > "$CONF/ntfy_topic" )
fi
chmod 600 "$CONF/ntfy_topic"

# Build the named app: Contents/MacOS/<NAME> launcher + Info.plist (background-only).
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
clang -O2 -Wall -o "$EXE" -DHUTWATCH_SCRIPT="\"$REPO/scripts/local_check.sh\"" "$REPO/scripts/mac/launcher.c"
cat > "$APP/Contents/Info.plist" <<IP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSBackgroundOnly</key><true/>
  <key>NSHumanReadableCopyright</key><string>Hourly Booking Suedtirol check for the Alta Via 1 hut watch (alert only).</string>
</dict>
</plist>
IP
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "warn: ad-hoc codesign failed (the app still runs)"
"$LSREGISTER" -f "$APP" 2>/dev/null || true

# Replace any older job, then load this one.
for l in "${OLD_LABELS[@]}"; do remove_agent "$l"; done
if [ -f "$HOME/Library/Logs/hutwatch-local.log" ] && [ ! -f "$LOG" ]; then
  mv "$HOME/Library/Logs/hutwatch-local.log" "$LOG"
fi
plist > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed \"$NAME\" ($LABEL): runs hourly (and now). Python: $PY"
echo "App: $APP"
echo "Log: $LOG    Uninstall: $0 --uninstall"
