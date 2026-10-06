#!/bin/sh
# Removes what install.sh set up: launchd job, plugin symlink, settings.json entries. Leaves SwiftBar and this folder alone.
# Flag: --purge also deletes the generated data (usage.db, reports/, state/logs) in this folder.
set -e
D="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
PLUGINS="${SWIFTBAR_PLUGINS:-$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/swiftbar-plugins")}"
PLIST="$HOME/Library/LaunchAgents/local.claude-cache-watch.plist"

launchctl bootout "gui/$(id -u)/local.claude-cache-watch" 2>/dev/null || true
rm -f "$PLIST"
echo "removed launchd job"

LINK="$PLUGINS/claude-usage.2m.py"
if [ -L "$LINK" ]; then rm "$LINK"; echo "removed $LINK"; fi

if [ -f "$SETTINGS" ]; then
  python3 - "$SETTINGS" "$D" <<'PYE'
import json, shlex, sys
path, d = sys.argv[1:3]
s = json.load(open(path))
wrap, hook = shlex.quote(f"{d}/statusline-wrap.sh"), shlex.quote(f"{d}/compact-to-file.py")
if s.get("statusLine", {}).get("command") == wrap:
    del s["statusLine"]
hooks = s.get("hooks", {})
groups = hooks.get("PostCompact", [])
for g in groups:
    g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != hook]
hooks["PostCompact"] = [g for g in groups if g.get("hooks")]
if not hooks["PostCompact"]:
    del hooks["PostCompact"]
if not hooks:
    s.pop("hooks", None)
json.dump(s, open(path, "w"), indent=2)
PYE
  echo "removed settings.json entries (a pre-install backup, if any, is $SETTINGS.bak)"
fi

if [ "$1" = "--purge" ]; then
  rm -rf "$D/usage.db" "$D/reports" "$D/.venv" "$D/statusline.json" "$D"/statusline.* "$D/cache-watch.state.json" "$D"/cache-watch.log "$D"/cache-watch.err "$D/update.json"
  echo "deleted generated data"
fi
pkill -x SwiftBar 2>/dev/null || true
open -a SwiftBar 2>/dev/null || true
echo "Uninstalled. To remove the code too: rm -rf $D"
