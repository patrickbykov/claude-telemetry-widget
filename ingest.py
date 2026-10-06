#!/usr/bin/env python3
"""Incrementally ingest Claude Code transcripts into usage.db next to this file."""
import json, os, sqlite3, glob, re

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".claude", "projects")
os.umask(0o077)  # usage.db holds prompt titles; keep it owner-only
DB = os.path.join(os.path.dirname(os.path.realpath(__file__)), "usage.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, off INTEGER NOT NULL, project TEXT);
CREATE TABLE IF NOT EXISTS sessions(session TEXT PRIMARY KEY, title TEXT, custom INTEGER);
CREATE TABLE IF NOT EXISTS requests(
  request_id TEXT PRIMARY KEY, ts TEXT, session TEXT, project TEXT, model TEXT,
  inp INTEGER, out INTEGER, cache_read INTEGER, cc_5m INTEGER, cc_1h INTEGER, subagent INTEGER);
CREATE INDEX IF NOT EXISTS r_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS r_sess ON requests(session, ts);
"""

_WT = re.compile(r"/\.claude/worktrees/.*$")

def root_project(cwd):
    """Name of the repo/dir a session was launched from, ignoring worktrees and sub-folders."""
    cwd = _WT.sub("", cwd.rstrip("/")) or "/"
    p, first_existing = cwd, None
    while p and p != "/":
        if os.path.isdir(p):
            first_existing = first_existing or p
            if os.path.exists(os.path.join(p, ".git")):
                return os.path.basename(p)
        p = os.path.dirname(p)
    # no git root found: the launch dir itself (or its nearest existing ancestor if it is gone)
    return os.path.basename(cwd) or "~"

def ingest_file(db, path, off, project):
    size = os.path.getsize(path)
    if size == off:
        return
    if size < off:
        off = 0
    sub = 1 if "/subagents/" in path else 0
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    end = data.rfind(b"\n") + 1  # ignore a partially written last line
    rows, titles, prompts = [], {}, {}
    for line in data[:end].split(b"\n"):
        if project is None and b'"cwd"' in line:
            try:
                project = root_project(json.loads(line)["cwd"])
            except (ValueError, KeyError):
                pass
        if not sub and b'"type":"user"' in line and b'"isMeta"' not in line and b'tool_result' not in line:
            try:
                d = json.loads(line)
                c = d["message"]["content"]
                if isinstance(c, list):
                    c = next((x.get("text", "") for x in c if x.get("type") == "text"), "")
                c = " ".join(c.split())
                if c and not c.startswith("<") and d.get("sessionId") not in prompts:
                    prompts[d["sessionId"]] = c[:90]
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            continue
        if b'-title"' in line:
            try:
                d = json.loads(line)
                if d.get("type") == "ai-title":
                    titles.setdefault(d["sessionId"], [d["aiTitle"], 0])
                    if not titles[d["sessionId"]][1]:
                        titles[d["sessionId"]] = [d["aiTitle"], 0]
                elif d.get("type") == "custom-title":
                    titles[d["sessionId"]] = [d["customTitle"], 1]
            except (ValueError, KeyError):
                pass
            continue
        if b'"usage"' not in line or b'"requestId"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message")
        if d.get("type") != "assistant" or not isinstance(m, dict):
            continue
        u, model = m.get("usage"), m.get("model")
        if not u or not model or model.startswith("<"):
            continue
        cc = u.get("cache_creation") or {}
        c1 = cc.get("ephemeral_1h_input_tokens", 0)
        c5 = cc.get("ephemeral_5m_input_tokens", 0) if cc else u.get("cache_creation_input_tokens", 0)
        rows.append([d["requestId"], d.get("timestamp"), d.get("sessionId"), None, model,
                     u.get("input_tokens", 0), u.get("output_tokens", 0),
                     u.get("cache_read_input_tokens", 0), c5, c1, sub])
    for r in rows:
        r[3] = project or os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))) if sub else os.path.dirname(path))
    db.executemany("INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    for sid, (t, custom) in titles.items():
        old = db.execute("SELECT custom FROM sessions WHERE session=?", (sid,)).fetchone()
        if old is None or custom or old[0] <= 0:
            db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)", (sid, t, custom))
    for sid, t in prompts.items():  # fallback name for untitled sessions: first prompt (custom=-1)
        db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,-1)", (sid, t))
    db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (path, off + end, project))

def run():
    db = sqlite3.connect(DB, timeout=30)
    db.executescript(SCHEMA)
    known = {p: (o, pr) for p, o, pr in db.execute("SELECT path, off, project FROM files")}
    for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
        off, project = known.get(path, (0, None))
        try:
            ingest_file(db, path, off, project)
        except OSError:
            pass
    db.commit()
    db.close()

if __name__ == "__main__":
    run()
