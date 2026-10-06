# Claude Code telemetry widget

A macOS menu bar plugin ([SwiftBar](https://github.com/swiftbar/SwiftBar)) that shows Claude Code cost, context size, plan limits and prompt-cache state, read from your local transcripts in `~/.claude/projects`. Nothing leaves your machine.

- **Menu bar:** 5h/7d plan usage, active sessions, items needing attention (oversized context, cold cache).
- **Session report:** `session-report.py <session-id>` writes a self-contained HTML cost review.
- **Cache watch:** a launchd job notifies shortly before a session's prompt cache expires.
- **Compaction saver:** a `PostCompact` hook saves each compaction summary to `~/.claude/compactions/`.

## Requirements

macOS, [SwiftBar](https://github.com/swiftbar/SwiftBar), Python 3.12+.

## Install

One line:

```sh
curl -fsSL https://raw.githubusercontent.com/patrickbykov/claude-telemetry-widget/main/install.sh | sh
```

Or from a clone:

```sh
git clone https://github.com/patrickbykov/claude-telemetry-widget.git
cd claude-telemetry-widget
./install.sh
```

The script is safe to re-run. It first checks the prerequisites (SwiftBar, Python 3.12+; it only warns if the Claude Code CLI is missing) and lists what is absent. It then offers to install the missing ones with Homebrew, and to install Homebrew itself if needed. Pass `-y` to accept without prompts (`... | sh -s -- -y`). After that it:

- creates a venv with Pillow (scripts re-exec under it via `use_venv.py`, so the system Python also works);
- links the plugin into `~/swiftbar-plugins` (override with `SWIFTBAR_PLUGINS=<dir>`) and points SwiftBar at it;
- starts the cache-watch launchd job;
- adds the `statusLine` and `PostCompact` entries to `~/.claude/settings.json` (backup in `settings.json.bak`; an existing, different `statusLine` is left alone);
- adds SwiftBar to your login items and launches it.

When run through `curl`, it clones the repo to `~/.claude-telemetry-widget` (override with `INSTALL_DIR`). The Claude usage item appears in the menu bar; plan limits show after the next Claude Code status update.

To uninstall: `launchctl bootout gui/$(id -u)/local.claude-cache-watch`, then delete `~/Library/LaunchAgents/local.claude-cache-watch.plist`, the plugin symlink, and the two `settings.json` entries.

## Configure

- `config.json`: thresholds and menu bar layout (`bar` section, see `_help`).
- `prices.json`: USD per million tokens. Values are assumptions; check them against the current Anthropic pricing.

`open-session.sh` expects the CLI at `~/.local/bin/claude`.

## License

MIT
