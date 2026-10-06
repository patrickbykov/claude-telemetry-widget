# Claude Code telemetry widget

A macOS menu bar plugin ([SwiftBar](https://github.com/swiftbar/SwiftBar)) that shows Claude Code cost, context size, plan limits and prompt-cache state, read from your local transcripts in `~/.claude/projects`. Nothing leaves your machine.

- **Menu bar:** 5h/7d plan usage, active sessions, items needing attention (oversized context, cold cache).
- **Session report:** `session-report.py <session-id>` writes a self-contained HTML cost review.
- **Cache watch:** a launchd job notifies shortly before a session's prompt cache expires.
- **Compaction saver:** a `PostCompact` hook saves each compaction summary to `~/.claude/compactions/`.

## Requirements

macOS, [SwiftBar](https://github.com/swiftbar/SwiftBar), Python 3.9+.

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

The script is safe to re-run. It first checks the prerequisites (SwiftBar, Python 3.9+; Homebrew Python 3.12 is installed only if the system one is older; it only warns if the Claude Code CLI is missing) and lists what is absent. It then offers to install the missing ones with Homebrew, and to install Homebrew itself if needed. Pass `-y` to accept without prompts (`... | sh -s -- -y`). After that it:

- creates a venv with Pillow (scripts re-exec under it via `use_venv.py`, so the system Python also works);
- links the plugin into your existing SwiftBar plugin folder, or `~/swiftbar-plugins` if none is set (override with `SWIFTBAR_PLUGINS=<dir>`);
- starts the cache-watch launchd job;
- adds the `statusLine` and `PostCompact` entries to `~/.claude/settings.json` (the original is kept once as `settings.json.bak`; an existing, different `statusLine` is left alone);
- adds SwiftBar to your login items and launches it.

When run through `curl`, it clones the repo to `~/.claude-telemetry-widget` (override with `INSTALL_DIR`). The Claude usage item appears in the menu bar; plan limits show after the next Claude Code status update.

To uninstall: `launchctl bootout gui/$(id -u)/local.claude-cache-watch`, then delete `~/Library/LaunchAgents/local.claude-cache-watch.plist`, the plugin symlink, and the two `settings.json` entries.

## Configure

- `config.json`: thresholds and menu bar layout (`bar` section, see `_help`).
- `prices.json`: USD per million tokens per model (matched by substring of the model id), including the cache-read price. Checked against the Anthropic pricing page on 2026-10-06; re-check when new models ship.

`open-session.sh` finds the CLI on your `PATH`, falling back to `~/.local/bin/claude`.

## License

MIT
