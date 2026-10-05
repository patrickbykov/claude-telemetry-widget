#!/bin/sh
# Copies "claude --resume <session id>" to the clipboard.
printf 'claude --resume %s' "$1" | pbcopy
