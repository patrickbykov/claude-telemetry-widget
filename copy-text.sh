#!/bin/sh
# Copies text to the clipboard. Keys avoid quoting trouble in SwiftBar params; anything else is copied literally.
case "$1" in
  compact) printf '%s' '/compact' | pbcopy ;;
  handoff) printf '%s' 'Write a handoff note to ~/.claude/handoff/<topic>.md (goal, decisions, files touched, next step; under 40 lines), then I will /clear.' | pbcopy ;;
  *) printf '%s' "$1" | pbcopy ;;
esac
