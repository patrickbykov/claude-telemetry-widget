#!/bin/sh
# Saves the statusline JSON (contains rate_limits) for the menu bar plugin.
# Each invocation works on a private snapshot, so concurrent sessions never see each other's input.
D="$(cd "$(dirname "$0")" && pwd)"
T=$(mktemp "$D/statusline.XXXXXX") || exit 1
trap 'rm -f "$T" "$T.pub"' EXIT
cat > "$T"

# Record this session's context window (200k or 1m) for the smart-zone/1M threshold lookup.
# Best-effort: never let a slow or missing sqlite3 break or delay the statusline write.
SID=$(sed -n 's/.*"session_id" *: *"\([^"]*\)".*/\1/p' "$T" | head -1 | tr -cd 'A-Za-z0-9-')
WIN=$(sed -n 's/.*"context_window_size" *: *\([0-9]*\).*/\1/p' "$T" | head -1)
if [ -n "$SID" ] && [ -n "$WIN" ]; then
  sqlite3 -cmd ".timeout 2000" "$D/usage.db" \
    "CREATE TABLE IF NOT EXISTS session_window(session TEXT PRIMARY KEY, window INTEGER, ts TEXT);
     INSERT OR REPLACE INTO session_window(session, window, ts) VALUES ('$SID', $WIN, datetime('now'));" \
    >/dev/null 2>&1 &
fi

cp "$T" "$T.pub" && mv "$T.pub" "$D/statusline.json"
