#!/usr/bin/env bash
# Commit changed state files and push, rebasing over concurrent pushes from the other workflow.
set -euo pipefail
msg="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for f in "$@"; do if [ -e "$f" ]; then git add -- "$f"; fi; done
if git diff --cached --quiet; then
  echo "No state change to commit."
  exit 0
fi
git commit -q -m "$msg"
for i in 1 2 3; do
  if git push -q; then exit 0; fi
  echo "Push rejected (attempt $i); rebasing."
  git pull -q --rebase
done
echo "Could not push state after 3 attempts." >&2
exit 1
