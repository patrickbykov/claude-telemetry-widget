#!/bin/sh
# Saves the statusline JSON (contains rate_limits) for the menu bar plugin.
# Each invocation works on a private snapshot, so concurrent sessions never see each other's input.
D="$(cd "$(dirname "$0")" && pwd)"
T=$(mktemp "$D/statusline.XXXXXX") || exit 1
trap 'rm -f "$T" "$T.pub"' EXIT
cat > "$T"
cp "$T" "$T.pub" && mv "$T.pub" "$D/statusline.json"
