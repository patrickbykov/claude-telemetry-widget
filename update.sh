#!/bin/sh
# Update to the latest version: pull, then re-run the installer (rebuilds venv, relinks, reloads the launchd job).
set -e
D="$(cd "$(dirname "$0")" && pwd)"
command -v git >/dev/null || { echo "git is required"; exit 1; }
[ -d "$D/.git" ] || { echo "not a git checkout; re-run the one-line installer instead"; exit 1; }
OLD="$(git -C "$D" rev-parse --short HEAD)"
git -C "$D" pull -q --ff-only || { echo "could not update (no network, or local edits to tracked files). To keep your edits: git -C $D stash && $D/update.sh && git -C $D stash pop. To drop them: git -C $D checkout -- ."; exit 1; }
NEW="$(git -C "$D" rev-parse --short HEAD)"
rm -f "$D/update.json"
if [ "$OLD" = "$NEW" ]; then echo "Already up to date ($NEW)."; else echo "Updated $OLD -> $NEW"; git -C "$D" log --oneline "$OLD..$NEW" | head -10; fi
exec sh "$D/install.sh" "$@"
