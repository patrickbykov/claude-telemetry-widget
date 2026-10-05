#!/bin/sh
# Usage: open-session.sh <cwd> <session-id> — resumes the session in a new iTerm window (falls back to Terminal).
CWD="$1"; SID="$2"
[ -d "$CWD" ] || CWD="$HOME"
case "$SID" in *[!A-Za-z0-9-]*|"") exit 1 ;; esac
Q=$(printf '%s' "$CWD" | sed "s/'/'\\\\''/g")   # POSIX single-quote escaping
CMD="cd '$Q' && ~/.local/bin/claude --resume $SID"
# the command travels as an osascript argument, never as part of the script text
if [ -d /Applications/iTerm.app ]; then
  osascript - "$CMD" <<'OSA'
on run argv
  tell application "iTerm"
    activate
    create window with default profile command ("/bin/zsh -lic " & quoted form of (item 1 of argv))
  end tell
end run
OSA
else
  osascript - "$CMD" <<'OSA'
on run argv
  tell application "Terminal"
    activate
    do script (item 1 of argv)
  end tell
end run
OSA
fi
