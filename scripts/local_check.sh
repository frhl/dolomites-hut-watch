#!/bin/bash
# Booking Suedtirol check (Fanes, Lavarella, Pederue, Fodara Vedla) from this Mac.
# Started hourly by launchd (see scripts/install_launchd.sh). Same honest request as the
# GitHub checker; alerts go to ntfy only (no GitHub token on this machine, no issues).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/hutwatch"
STATE="$HOME/Library/Application Support/hutwatch"
PY="${HUTWATCH_PYTHON:-python3}"
mkdir -p "$STATE"

# At most once an hour, whatever launchd does (wake from sleep, reloads).
now=$(date +%s)
last=$(cat "$STATE/last_run" 2>/dev/null || echo 0)
if [ $((now - last)) -lt 3540 ]; then
  echo "Dolomites Hut Watch $(date -u +%FT%TZ): skipped, last run $((now - last)) s ago"
  exit 0
fi
echo "$now" > "$STATE/last_run"
echo "=== Dolomites Hut Watch (Booking Suedtirol check) $(date -u +%FT%TZ)"

# Pick up code (public repo) and tracker (private state repo, ./private) updates, but only
# if a clone has no local edits.
for d in "$REPO" "$REPO/private"; do
  [ -d "$d/.git" ] || continue
  if [ -z "$(git -C "$d" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    git -C "$d" pull -q --ff-only 2>&1 || echo "warn: git pull failed in $d; using the local copy"
  fi
done

NTFY_TOPIC="$(cat "$CONF/ntfy_topic" 2>/dev/null || true)"
if [ -z "$NTFY_TOPIC" ]; then
  echo "error: no ntfy topic in $CONF/ntfy_topic (run scripts/install_launchd.sh)"
  exit 1
fi
export NTFY_TOPIC HUTWATCH_STATE_DIR="$STATE" HUTWATCH_ISSUES=off
export HUTWATCH_TRACKER="$REPO/private/AV1-booking-tracker.xlsx"
DRY=()
[ -n "${HUTWATCH_DRY_RUN:-}" ] && DRY=(--dry-run)
cd "$REPO" && exec "$PY" -m hutwatch fast ${DRY[@]+"${DRY[@]}"} --only fanes lavarella pederue fodara_vedla
