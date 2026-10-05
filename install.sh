#!/bin/sh
# One-step installer: prerequisites, venv, SwiftBar plugin, cache-watch job, Claude Code settings. Safe to re-run.
# One line: curl -fsSL https://raw.githubusercontent.com/patrickbykov/claude-telemetry-widget/main/install.sh | sh
# Flags: -y / --yes installs missing prerequisites without asking.
set -e
REPO="patrickbykov/claude-telemetry-widget"
YES=0; [ "$1" = "-y" ] || [ "$1" = "--yes" ] && YES=1

[ "$(uname)" = Darwin ] || { echo "macOS only"; exit 1; }

# piped from curl there is no checkout next to the script: clone one and run its installer
SRC="$(dirname "$0")"
if [ ! -f "$SRC/claude-usage.2m.py" ]; then
  command -v git >/dev/null || { echo "git is required: run 'xcode-select --install' and retry"; exit 1; }
  DEST="${INSTALL_DIR:-$HOME/.claude-telemetry-widget}"
  [ -d "$DEST/.git" ] && git -C "$DEST" pull -q --ff-only || git clone -q "https://github.com/$REPO.git" "$DEST"
  exec sh "$DEST/install.sh" "$@"
fi

D="$(cd "$SRC" && pwd)"
PLUGINS="${SWIFTBAR_PLUGINS:-$HOME/swiftbar-plugins}"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
PY="$D/.venv/bin/python3"

# ---- prerequisites: report everything first, then offer to install what is missing ----
MISSING=""
[ -d /Applications/SwiftBar.app ] || MISSING="$MISSING swiftbar"
command -v npx >/dev/null || MISSING="$MISSING node"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null || command -v python3.12 >/dev/null || MISSING="$MISSING python@3.12"
for p in swiftbar node python@3.12; do
  case "$MISSING" in *"$p"*) echo "missing: $p" ;; *) echo "ok:      $p" ;; esac
done
command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ] || echo "warning: Claude Code CLI not found (https://claude.com/claude-code); the plugin needs it to have data"

if [ -n "$MISSING" ]; then
  if ! command -v brew >/dev/null; then
    echo "Homebrew is needed to install:$MISSING"
    ASK="Install Homebrew (runs the official script from brew.sh)? [y/N] "
    if [ "$YES" = 1 ]; then A=y; else printf '%s' "$ASK"; read A </dev/tty || A=n; fi
    case "$A" in y|Y) /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                      eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)" ;;
                  *) echo "Install the missing prerequisites and re-run."; exit 1 ;; esac
  fi
  if [ "$YES" = 1 ]; then A=y; else printf 'Install with brew:%s? [y/N] ' "$MISSING"; read A </dev/tty || A=n; fi
  case "$A" in
    y|Y) for p in $MISSING; do
           if [ "$p" = swiftbar ]; then brew install --cask swiftbar; else brew install "$p"; fi
         done ;;
    *) echo "Install the missing prerequisites and re-run."; exit 1 ;;
  esac
fi
PYBIN="$(command -v python3.12 || command -v python3)"

"$PYBIN" -m venv "$D/.venv"
"$D/.venv/bin/pip" install -q pillow

# the repo ships a portable shebang; the local copy points at the venv (hidden from git status)
for f in claude-usage.2m.py cache-watch.py compact-to-file.py session-report.py; do
  sed -i '' "1s|.*|#!$PY|" "$D/$f"
  chmod +x "$D/$f"
  git -C "$D" update-index --assume-unchanged "$f" 2>/dev/null || true
done

mkdir -p "$PLUGINS"
ln -sf "$D/claude-usage.2m.py" "$PLUGINS/claude-usage.2m.py"
defaults write com.ameba.SwiftBar PluginDirectory "$PLUGINS"

PLIST="$HOME/Library/LaunchAgents/local.claude-cache-watch.plist"
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>local.claude-cache-watch</string>
<key>ProgramArguments</key><array><string>$D/cache-watch.py</string></array>
<key>StartInterval</key><integer>30</integer>
<key>RunAtLoad</key><true/>
<key>ProcessType</key><string>Background</string>
<key>LowPriorityIO</key><true/>
</dict></plist>
P
launchctl bootout "gui/$(id -u)/local.claude-cache-watch" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# merge into Claude Code settings; an existing, different statusLine is left alone
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak"
"$PY" - "$SETTINGS" "$D" <<'PYE'
import json, os, sys
path, d = sys.argv[1:3]
s = json.load(open(path)) if os.path.exists(path) else {}
wrap, hook = f"{d}/statusline-wrap.sh", f"{d}/compact-to-file.py"
cur = s.get("statusLine", {}).get("command")
if cur in (None, wrap):
    s["statusLine"] = {"type": "command", "command": wrap, "padding": 0}
else:
    print(f"statusLine already set to {cur!r}; not changed. Point it at {wrap} to get plan limits.")
groups = s.setdefault("hooks", {}).setdefault("PostCompact", [])
if not any(h.get("command") == hook for g in groups for h in g.get("hooks", [])):
    groups.append({"hooks": [{"type": "command", "command": hook}]})
json.dump(s, open(path, "w"), indent=2)
PYE

# start at login, then (re)launch so the plugin appears now
osascript -e 'tell application "System Events" to if not (exists login item "SwiftBar") then make login item at end with properties {path:"/Applications/SwiftBar.app", hidden:true}' >/dev/null 2>&1 || true
pkill -x SwiftBar 2>/dev/null || true
open -a SwiftBar
echo "Installed. The Claude usage item is in the menu bar; plan limits appear after the next Claude Code status update."
echo "Settings backup: $SETTINGS.bak"
