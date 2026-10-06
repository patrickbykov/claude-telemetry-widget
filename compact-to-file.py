#!/usr/bin/env python3
"""PostCompact hook: saves the compaction summary to ~/.claude/compactions/<project>/<date>-<session>.md.

Reads the hook JSON from stdin and saves its compact_summary; falls back to the newest isCompactSummary message in the transcript.
Never fails the compaction: any problem is logged to ~/.claude/compactions/hook.log and exit code is 0.
"""
import json, os, sys, time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
os.umask(0o077)  # compaction summaries contain session content; keep them owner-only
OUT = os.path.join(HOME, ".claude", "compactions")
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

def log(msg):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "hook.log"), "a") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")

LEDGER = os.path.join(OUT, ".saved-uuids")

def saved_ids():
    try:
        return set(open(LEDGER).read().split())
    except OSError:
        return set()

def latest_summary(path):
    best, seen = None, saved_ids()
    with open(path, "rb") as fh:
        for line in fh:
            if b'"isCompactSummary"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("isCompactSummary") and d.get("uuid") not in seen:  # skip summaries an earlier compaction already saved
                    best = d
    return best

def wait_for_summary(path, sid, raw, retry):
    """The transcript is flushed seconds after the hook fires: wait for it, or hand over to a detached retry."""
    for _ in range(150 if retry else 6):
        d = latest_summary(path)
        if d:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))).total_seconds()
            if age < float(os.environ.get("COMPACT_MAX_AGE", 180)):
                return d
        time.sleep(1)
    if retry:
        log(f"{sid}: gave up waiting for the compact summary")
    else:
        import subprocess  # keep waiting in a detached process so compaction is not blocked
        subprocess.Popen([sys.executable, os.path.realpath(__file__), "--retry"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True).stdin.write(raw.encode())
        log(f"{sid}: summary not in transcript yet, retrying in background")

def write_new(folder, stem, body):
    """Never overwrites an existing backup: a clash gets a -2, -3, ... suffix."""
    for n in range(1, 100):
        out = os.path.join(folder, f"{stem}{'' if n == 1 else f'-{n}'}.md")
        try:
            with open(out, "x") as fh:
                fh.write(body)
            return out
        except FileExistsError:
            continue
    raise OSError(f"no free file name for {stem}")

def main():
    raw = sys.stdin.read()
    hook = json.loads(raw)
    sid = hook.get("session_id", "unknown")
    d, text = {}, hook.get("compact_summary")  # the hook payload carries the summary; the transcript is the fallback
    if not text:
        path = hook.get("transcript_path")
        if not path or not os.path.exists(path):
            return log(f"no transcript for {sid}")
        d = wait_for_summary(path, sid, raw, "--retry" in sys.argv)
        if not d:
            return
        c = d["message"]["content"]
        text = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    import ingest
    project = ingest.root_project(hook.get("cwd") or d.get("cwd") or "")
    ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone() if d else datetime.now().astimezone()
    folder = os.path.join(OUT, project)
    os.makedirs(folder, exist_ok=True)
    uid = d.get("uuid", "")[:8]
    out = write_new(folder, f"{ts.strftime('%Y-%m-%d_%H%M%S')}-{sid[:8]}" + (f"-{uid}" if uid else ""),
                    f"# Compaction summary\n\n- session: {sid}\n- project: {project}\n- cwd: {hook.get('cwd')}\n"
                    f"- trigger: {hook.get('trigger')}\n- time: {ts.isoformat(timespec='seconds')}\n\n---\n\n{text}\n")
    if d:
        with open(LEDGER, "a") as fh:
            fh.write(d.get("uuid", "") + "\n")
    log(f"{sid}: saved {out}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a hook must never break compaction
        log(f"error: {e!r}")
    sys.exit(0)
