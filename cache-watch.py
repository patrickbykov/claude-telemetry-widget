#!/usr/bin/env python3
"""Notifies shortly before a session's prompt cache expires (5 min TTL, or 1 h when 1h writes are used).

Run every 30 s by launchd. Only stats recent transcripts and reads the tail of the few that matter.
A notification fires once per (session, last request) when <= WARN_S seconds remain and a cold restart
would cost at least MIN_USD. Sound: Tink (light, short).
"""
import glob, json, os, subprocess, sys, time
from datetime import datetime, timezone
from urllib.request import pathname2url

D = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, D)
from pricing import parts, family
import sqlite3

with open(os.path.join(D, "config.json")) as fh:
    CFG = json.load(fh)
WARN_S = CFG.get("cache_notify_before_s", 60)
MIN_USD = CFG.get("cache_notify_min_usd", 0.5)
STATE = os.path.join(D, "cache-watch.state.json")
os.umask(0o077)

def scan_tail(lines, now):
    newest, one_h = None, False
    for line in reversed(lines):
        if b'"usage"' in line and b'"assistant"' in line:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") or {}
            if not m.get("usage") or str(m.get("model", "")).startswith("<"):
                continue
            if newest is None:
                newest = d
            elif m.get("model") != newest["message"].get("model"):
                break  # a model switch starts a new cache: older 1 h writes no longer keep it alive
            if datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp() < now - 3600:
                break
            if (m["usage"].get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) > 0:
                one_h = True
                break
    return newest, one_h

def last_request(path, now):
    """Newest assistant request, plus whether a same-model request in the last hour wrote a 1 h cache entry (reads refresh it)."""
    n = 200_000
    while True:
        with open(path, "rb") as fh:
            fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - n))
            lines = fh.read().splitlines()
        newest, one_h = scan_tail(lines, now)
        if newest or n >= size or n >= 16_000_000:  # a huge record can push the newest request out of the tail: read more
            return newest, one_h
        n *= 4

def session_title(sid):
    """Title from usage.db, or None while the plugin has not created the database yet."""
    try:
        db = sqlite3.connect("file:" + pathname2url(os.path.join(D, "usage.db")) + "?mode=ro", uri=True)
        try:
            row = db.execute("SELECT title FROM sessions WHERE session=?", (sid,)).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None

def main():
    now = time.time()
    try:
        with open(STATE) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    for path in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        if now - os.path.getmtime(path) > 3600:
            continue
        d, one_h = last_request(path, now)
        if not d:
            continue
        u, model = d["message"]["usage"], d["message"]["model"]
        cc = u.get("cache_creation") or {}
        c1, c5 = cc.get("ephemeral_1h_input_tokens", 0), cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0))
        ttl = 3600 if one_h else 300
        sent = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
        left = sent + ttl - now
        if not (0 < left <= WARN_S):
            continue
        ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + c5 + c1
        cold = parts(model, 0, 0, 0, ctx, 0)["write"] - parts(model, 0, 0, ctx, 0, 0)["read"]
        sid = os.path.basename(path)[:-6]
        key = f"{sid}:{d['timestamp']}"
        if cold < MIN_USD or state.get(sid) == key:
            continue
        state[sid] = key
        title = (session_title(sid) or os.path.basename(os.path.dirname(path)).split("-")[-1])[:60]
        notify(title, int(left), ctx, cold, ttl, model)
    with open(STATE + ".tmp", "w") as fh:
        json.dump(state, fh)
    os.replace(STATE + ".tmp", STATE)

def notify(title, left, ctx, cold, ttl, model):
    kind = "1 h" if ttl == 3600 else "5 min"
    body = f"Cache expires in {left}s · {ctx//1000}k context · a cold restart would cost ~${cold:.2f}"
    sub = f"Reply now, or /compact · {family(model)} · {kind} TTL"
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(body)}" with title "⏳ Claude cache is cooling" subtitle "{esc(title)} — {esc(sub)}"'
    subprocess.run(["osascript", "-e", script], timeout=10)
    subprocess.Popen(["afplay", "-v", "0.4", "/System/Library/Sounds/Tink.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with open(os.path.join(D, "cache-watch.log"), "a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {e!r}\n")
