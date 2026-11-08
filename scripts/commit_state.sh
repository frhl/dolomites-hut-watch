#!/usr/bin/env bash
# Commit changed files in a repo checkout and push, rebasing over concurrent pushes.
#   scripts/commit_state.sh <repo-dir> "<message>" <path>...
# Used for the private state repo (./private) and, by page-watch only, for the public
# STATUS.md keep-alive commit.
set -euo pipefail
dir="$1"; msg="$2"; shift 2
cd "$dir"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for f in "$@"; do if [ -e "$f" ]; then git add -- "$f"; fi; done
# Silent either way: in a public log, "nothing changed" vs "committed" would itself be a signal.
if git diff --cached --quiet; then
  exit 0
fi
git commit -q -m "$msg"
for i in 1 2 3; do
  if git push -q; then exit 0; fi
  git pull -q --rebase
done
echo "Could not push after 3 attempts." >&2
exit 1
