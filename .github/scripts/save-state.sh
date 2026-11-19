#!/usr/bin/env bash
# Commit and push the given state files. If main moved meanwhile (a manual commit, an overlapping
# run), rebase and retry instead of losing the seen jobs.
set -euo pipefail

MAX_ATTEMPTS=5

git add "$@"
git diff --cached --quiet && exit 0
git config user.name "job-alerts-bot"
git config user.email "job-alerts-bot@users.noreply.github.com"
git commit -q -m "chore: update seen jobs"
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  git pull -q --rebase origin main && git push -q origin HEAD:main && exit 0
  echo "push attempt $attempt failed, retrying" >&2
  sleep $((attempt * 3))
done
echo "could not push state after $MAX_ATTEMPTS attempts" >&2
exit 1
