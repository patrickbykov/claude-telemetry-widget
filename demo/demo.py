#!/usr/bin/env python3
"""Fake data for README screenshots. Never touches your real transcripts or usage.db.

  demo.py on   build fake data in ~/.claude-telemetry-demo and point your SwiftBar plugin link at it
  demo.py off  restore the real plugin link and delete the fake data
Shown in the menu within ~2 minutes, or click Refresh now.
"""
import json, os, random, shutil, subprocess, sys, time, uuid
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROOT = os.path.expanduser("~/.claude-telemetry-demo")
HOME, APP = os.path.join(ROOT, "home"), os.path.join(ROOT, "app")
random.seed(7)

# (project, title, model, requests, start ctx, ctx growth/request, hours ago it started, ttl)
SESSIONS = [
    ("checkout-api",   "Fix flaky payment webhook retries",   "claude-opus-5-5",   60, 40_000, 5_500, 0.8, "1h"),
    ("web-dashboard",  "Migrate charts to the new design system", "claude-sonnet-5-5", 45, 30_000, 4_200, 5, "5m"),
    ("data-pipeline",  "Debug slow nightly aggregation job",  "claude-fable-5-1",  30, 60_000, 7_000, 27, "1h"),
    ("mobile-app",     "Add offline mode to the sync layer",  "claude-opus-5-5",   55, 35_000, 6_000, 30, "1h"),
    ("docs-site",      "Rewrite the getting-started guide",   "claude-haiku-4-5",  25, 10_000, 1_500, 52, "5m"),
    ("checkout-api",   "Review the refund endpoint PR",       "claude-sonnet-5-5", 35, 25_000, 3_800, 75, "5m"),
    ("infra-terraform","Split the VPC module per environment","claude-opus-5-5",   40, 45_000, 5_000, 100, "1h"),
    ("web-dashboard",  "Add keyboard navigation to tables",   "claude-sonnet-5-5", 28, 20_000, 3_000, 125, "5m"),
    ("data-pipeline",  "Backfill missing events for March",   "claude-sonnet-5-5", 50, 50_000, 6_500, 150, "1h"),
]

def build():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(os.path.join(HOME, ".claude", "projects"))
    shutil.copytree(REPO, APP, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "usage.db", "reports", "demo", "statusline.*", "update.json", "cache-watch.*"))
    now = datetime.now(timezone.utc)
    for proj, title, model, n, ctx, grow, ago, ttl in SESSIONS:
        sid = str(uuid.UUID(int=random.getrandbits(128)))
        d = os.path.join(HOME, ".claude", "projects", "-demo-" + proj)
        os.makedirs(d, exist_ok=True)
        t = now - timedelta(hours=ago)
        lines = [{"type": "user", "sessionId": sid, "cwd": f"/demo/{proj}", "timestamp": t.isoformat(),
                  "message": {"role": "user", "content": [{"type": "text", "text": title}]}},
                 {"type": "ai-title", "sessionId": sid, "aiTitle": title}]
        for i in range(n):
            t += timedelta(seconds=random.choice([25, 40, 70, 110, 200, 330 if i % 9 == 8 else 90]))
            if t > now - timedelta(seconds=20):
                break
            gap_cold = i % 14 == 13  # an occasional idle gap: the next request rebuilds the cache
            read = 0 if gap_cold else int(ctx * random.uniform(0.9, 0.98))
            new = ctx - read if gap_cold else ctx - read + random.randint(500, 3000)
            cc = {"ephemeral_1h_input_tokens": new, "ephemeral_5m_input_tokens": 0} if ttl == "1h" else \
                 {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": new}
            lines.append({"type": "assistant", "sessionId": sid, "requestId": "req_" + uuid.uuid4().hex[:20],
                          "timestamp": t.isoformat(), "cwd": f"/demo/{proj}",
                          "message": {"model": model, "role": "assistant", "content": [],
                                      "usage": {"input_tokens": random.randint(2, 6), "output_tokens": random.randint(150, 1800),
                                                "cache_read_input_tokens": read, "cache_creation_input_tokens": new, "cache_creation": cc}}})
            ctx += grow + random.randint(-800, 800)
        with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(x) for x in lines) + "\n")
    touch()

def touch():
    """Fresh plan-limit snapshot so the menu does not show an 'as of' note."""
    now = time.time()
    sl = {"session_name": "Fix flaky payment webhook retries", "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
          "rate_limits": {"five_hour": {"used_percentage": 62, "resets_at": int(now + 2.4 * 3600)},
                          "seven_day": {"used_percentage": 41, "resets_at": int(now + 3.2 * 86400)}}}
    with open(os.path.join(APP, "statusline.json"), "w") as fh:
        json.dump(sl, fh)

def plugin_link():
    cur = subprocess.run(["defaults", "read", "com.ameba.SwiftBar", "PluginDirectory"], capture_output=True, text=True).stdout.strip()
    return os.path.join(cur or os.path.expanduser("~/swiftbar-plugins"), "claude-usage.2m.py")

def on():
    build()
    link = plugin_link()
    wrapper = f'#!/bin/sh\n{sys.executable} {os.path.realpath(__file__)} touch\n' \
              f'HOME="{HOME}" exec "{REPO}/.venv/bin/python3" "{APP}/claude-usage.2m.py"\n'
    if os.path.islink(link):
        os.remove(link)
    with open(link, "w") as fh:
        fh.write(wrapper)
    os.chmod(link, 0o755)
    print(f"Demo on. Plugin {link} now shows fake data. Restore with: {os.path.realpath(__file__)} off")

def off():
    link, real = plugin_link(), os.path.join(REPO, "claude-usage.2m.py")
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(real, link)
    shutil.rmtree(ROOT, ignore_errors=True)
    print("Demo off. Real plugin link restored.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "touch":
        APP = os.path.join(ROOT, "app"); touch()
    elif cmd in ("on", "off"):
        {"on": on, "off": off}[cmd]()
    else:
        print(__doc__)
