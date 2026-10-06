#!/usr/bin/env python3
"""Cost review of one Claude Code session -> self-contained HTML in reports/, then opens it.

Usage: session-report.py <session-id>
Deterministic (no LLM calls): reads the session transcript + its subagent transcripts.
"""
import bisect, glob, html, json, os, re, subprocess, sys
from collections import defaultdict
from datetime import datetime

D = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, D)
from pricing import family, price, parts, big

C = json.load(open(os.path.join(D, "config.json")))
BIG = C["ctx_big_tokens"]
OUT_DIR = os.path.join(D, "reports")
os.umask(0o077)  # reports quote prompts and tool inputs; keep them owner-only
esc = html.escape


def notify(msg):
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Claude usage"'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()


def summarize_input(name, inp):
    if not isinstance(inp, dict):
        return ""
    if isinstance(inp.get("file_path"), str):
        return inp["file_path"]
    for key in ("command", "pattern", "description", "url", "query", "path", "prompt"):
        if isinstance(inp.get(key), str):
            return " ".join(inp[key].split())[:90]
    for v in inp.values():
        if isinstance(v, str):
            return " ".join(v.split())[:90]
    return ""


def result_size(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(x.get("text", "")) for x in content if isinstance(x, dict))
    return 0


def load(sid):
    if not re.fullmatch(r"[A-Za-z0-9-]+", sid):
        sys.exit(f"invalid session id: {sid}")
    mains = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    if not mains:
        sys.exit(f"transcript for {sid} not found")
    subs = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}/subagents/*.jsonl"))
    reqs, tool_of, results, prompts, compactions = {}, {}, [], [], []
    cwd = ""
    for path in mains + subs:
        is_sub = path in subs
        with open(path, "rb") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("type")
                if not cwd and d.get("cwd"):
                    cwd = d["cwd"]
                m = d.get("message") if isinstance(d.get("message"), dict) else {}
                if t == "assistant" and m.get("usage") and d.get("requestId") and not str(m.get("model", "")).startswith("<"):
                    u = m["usage"]
                    cc = u.get("cache_creation") or {}
                    c1 = cc.get("ephemeral_1h_input_tokens", 0)
                    c5 = cc.get("ephemeral_5m_input_tokens", 0) if cc else u.get("cache_creation_input_tokens", 0)
                    r = reqs.setdefault(d["requestId"], {"tools": []})
                    r.update(ts=parse_ts(d["timestamp"]), model=m["model"], inp=u.get("input_tokens", 0),
                             out=u.get("output_tokens", 0), cr=u.get("cache_read_input_tokens", 0),
                             c5=c5, c1=c1, sub=is_sub)
                    for blk in m.get("content", []):
                        if isinstance(blk, dict) and blk.get("type") == "tool_use":
                            summ = summarize_input(blk["name"], blk.get("input"))
                            tool_of[blk["id"]] = (blk["name"], summ)
                            r["tools"].append(blk["name"])
                elif t == "user":
                    c = m.get("content")
                    if isinstance(c, list):
                        for x in c:
                            if isinstance(x, dict) and x.get("type") == "tool_result":
                                results.append((parse_ts(d["timestamp"]), x.get("tool_use_id"),
                                                result_size(x.get("content")), is_sub))
                    if not is_sub and not d.get("isMeta") and not d.get("isCompactSummary"):
                        text = c if isinstance(c, str) else next(
                            (x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text"), "")
                        text = " ".join(text.split())
                        if text and not text.startswith("<"):
                            prompts.append((parse_ts(d["timestamp"]), text))
                elif t == "system" and d.get("subtype") == "compact_boundary":
                    if not is_sub:  # a subagent compacting its own context says nothing about the main one
                        compactions.append(parse_ts(d["timestamp"]))
    rows = []
    for rid, r in reqs.items():
        if "ts" not in r:
            continue
        pt = parts(r["model"], r["inp"], r["out"], r["cr"], r["c5"], r["c1"])
        r.update(pt=pt, cost=sum(pt.values()), ctx=r["inp"] + r["cr"] + r["c5"] + r["c1"], rid=rid)
        rows.append(r)
    rows.sort(key=lambda r: r["ts"])
    prompts.sort()
    return dict(rows=rows, tool_of=tool_of, results=results, prompts=prompts, compactions=compactions,
                cwd=cwd, path=mains[0])


# ---------- svg helpers ----------
def svg_line(points, w=860, h=200, color="var(--accent)", ref=None, fmt=lambda v: f"{v:g}", area=True, xfmt=None):
    """points: [(x, y)] with x numeric (epoch seconds)."""
    if not points:
        return ""
    L, R, T, B = 52, 30, 10, 24
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    ymax = max(ys + ([ref[0]] if ref else [])) * 1.08 or 1
    sx = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (w - L - R)
    sy = lambda y: T + (1 - y / ymax) * (h - T - B)
    pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in points)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i in range(5):
        v = ymax * i / 4
        out.append(f'<line x1="{L}" x2="{w-R}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" class="grid"/>'
                   f'<text x="{L-6}" y="{sy(v)+4:.1f}" class="axis" text-anchor="end">{esc(fmt(v))}</text>')
    if ref:
        out.append(f'<line x1="{L}" x2="{w-R}" y1="{sy(ref[0]):.1f}" y2="{sy(ref[0]):.1f}" class="ref"/>'
                   f'<text x="{w-R}" y="{sy(ref[0])-4:.1f}" class="axis warn" text-anchor="end">{esc(ref[1])}</text>')
    if area:
        out.append(f'<polygon points="{L},{h-B} {pts} {sx(x1):.1f},{h-B}" fill="{color}" opacity=".15"/>')
    out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>')
    for i in range(5):
        x = x0 + (x1 - x0) * i / 4
        out.append(f'<text x="{sx(x):.1f}" y="{h-6}" class="axis" text-anchor="middle">{esc(xfmt(x) if xfmt else "")}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_bars(items, w=860, bar_h=22, color="var(--accent)", fmt=lambda v: f"{v:g}", label_w=210):
    """items: [(label, value, color|None)] horizontal bars."""
    if not items:
        return ""
    top = max(v for _, v, _ in items) or 1
    h = len(items) * (bar_h + 6) + 4
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i, (label, v, col) in enumerate(items):
        y = 2 + i * (bar_h + 6)
        bw = max(2, (w - label_w - 90) * v / top)
        out.append(f'<text x="{label_w-8}" y="{y+bar_h*0.7:.1f}" class="axis" text-anchor="end">{esc(label[:34])}</text>'
                   f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="4" fill="{col or color}"/>'
                   f'<text x="{label_w+bw+8:.1f}" y="{y+bar_h*0.7:.1f}" class="axis">{esc(fmt(v))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_columns(buckets, w=860, h=170, fmt=lambda v: f"{v:g}"):
    """buckets: [(label, {family: value})] stacked columns."""
    colors = {"opus": "var(--opus)", "sonnet": "var(--sonnet)", "other": "var(--other)"}
    L, R, T, B = 52, 30, 10, 24
    totals = [sum(v.values()) for _, v in buckets]
    top = (max(totals) or 1) * 1.08
    n = len(buckets)
    slot = (w - L - R) / max(n, 1)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i in range(5):
        v = top * i / 4
        y = T + (1 - v / top) * (h - T - B)
        out.append(f'<line x1="{L}" x2="{w-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{L-6}" y="{y+4:.1f}" class="axis" text-anchor="end">{esc(fmt(v))}</text>')
    for i, (label, v) in enumerate(buckets):
        x = L + i * slot + slot * 0.12
        y = h - B
        for fam in ("opus", "sonnet", "other"):
            bh = v.get(fam, 0) / top * (h - T - B)
            if bh > 0:
                out.append(f'<rect x="{x:.1f}" y="{y-bh:.1f}" width="{slot*0.76:.1f}" height="{bh:.1f}" fill="{colors[fam]}"/>')
                y -= bh
        if n <= 24 or i % max(1, n // 12) == 0:
            out.append(f'<text x="{x+slot*0.38:.1f}" y="{h-6}" class="axis" text-anchor="middle">{esc(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def short(s, n=70):
    return s if len(s) <= n else "…" + s[-(n - 1):] if s.startswith("/") else s[:n - 1] + "…"


def usd(v):
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def tok(n):
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else str(int(n))


def build(sid):
    S = load(sid)
    rows, prompts = S["rows"], S["prompts"]
    if not rows:
        sys.exit("no usage data in this session")
    main = [r for r in rows if not r["sub"]]
    total = sum(r["cost"] for r in rows)
    sub_cost = sum(r["cost"] for r in rows if r["sub"])
    t0, t1 = rows[0]["ts"], rows[-1]["ts"]

    # token-type split, model split
    split = defaultdict(float)
    by_model = defaultdict(float)
    for r in rows:
        for k, v in r["pt"].items():
            split[k] += v
        by_model[r["model"]] += r["cost"]

    # cold-cache restarts (main thread only)
    cold = []
    prev = None
    for r in main:
        if prev and r["ctx"] > 20_000 and r["cr"] < 0.1 * r["ctx"] and r["model"] == prev["model"] and r["ctx"] >= 0.8 * prev["ctx"]:  # not after a /clear, compaction or model switch
            p = price(r["model"])
            over = ((r["c5"] * 1.25 + r["c1"] * 2.0) * p["in"] - (r["c5"] + r["c1"]) * p["read"]) / 1e6
            cold.append(dict(ts=r["ts"], gap=(r["ts"] - prev["ts"]).total_seconds() / 60, ctx=r["ctx"], over=over))
        prev = r
    cold_over = sum(c["over"] for c in cold)

    # cost above the big-context threshold: share of read/write attributable to tokens beyond BIG
    big_save = 0.0
    big_reqs = [r for r in main if r["ctx"] > big(r["model"])]
    for r in big_reqs:
        big_save += (r["pt"]["read"] + r["pt"]["write"]) * (r["ctx"] - big(r["model"])) / r["ctx"]
    dom = max(by_model, key=by_model.get)  # model that carried most of the cost sets the headline limit
    BIG = big(dom)
    big_cost = sum(r["cost"] for r in big_reqs)
    peak = max(main, key=lambda r: r["ctx"]) if main else rows[0]

    # turns: cost per user prompt
    ptimes = [p[0] for p in prompts]
    turn_cost = defaultdict(float)
    turn_reqs = defaultdict(int)
    for r in rows:
        i = bisect.bisect_right(ptimes, r["ts"]) - 1
        turn_cost[i] += r["cost"]
        turn_reqs[i] += 1
    turns = sorted(((c, i) for i, c in turn_cost.items() if i >= 0), reverse=True)[:10]

    # tool results: context contributors and their carrying cost
    main_ts = [r["ts"] for r in main]
    avg_read = price(peak["model"])["read"]
    by_tool = defaultdict(lambda: [0, 0])
    big_results = []
    reads = defaultdict(int)
    for ts, tid, size, is_sub in S["results"]:
        name, summ = S["tool_of"].get(tid, ("?", ""))
        est = size / 4
        by_tool[name][0] += est
        by_tool[name][1] += 1
        if name == "Read" and summ:
            reads[summ] += 1
        if is_sub:
            continue
        cs = sorted(S["compactions"])
        nc = cs[bisect.bisect_right(cs, ts)] if bisect.bisect_right(cs, ts) < len(cs) else None  # the result leaves context at the next compaction
        later = (bisect.bisect_left(main_ts, nc) if nc is not None else len(main_ts)) - bisect.bisect_right(main_ts, ts)
        carry = est * later * avg_read / 1e6
        big_results.append((carry, est, later, name, summ, ts))
    big_results.sort(reverse=True)
    dup_reads = sorted(((n, f) for f, n in reads.items() if n >= 3), reverse=True)[:8]

    # ---------- findings ----------
    findings = []
    if big_reqs:
        findings.append(("high" if big_save > 0.15 * total else "med",
                         f"{len(big_reqs)} of {len(main)} requests carried more than the {BIG//1000}k cost threshold of context "
                         f"(peak {tok(peak['ctx'])}). Those requests cost {usd(big_cost)} ({big_cost/total*100:.0f}% of the session).",
                         f"Compacting or starting a fresh session at ~{BIG//1000}k would have saved roughly {usd(big_save)}."))
    if cold:
        findings.append(("med" if cold_over > 5 else "low",
                         f"{len(cold)} cold-cache restarts: the whole context was re-written to the cache instead of read from it "
                         f"(typical gap {sorted(c['gap'] for c in cold)[len(cold)//2]:.0f} min).",
                         f"Overspend about {usd(cold_over)}. Long idle pauses expire the cache; resume work sooner or finish a topic before stepping away."))
    if big_results and big_results[0][0] > 0.02 * total:
        c, est, later, name, summ, _ = big_results[0]
        findings.append(("med", f"Largest context passenger: a {name} result (~{tok(est)} tokens, “{summ[:60]}”) stayed in context for {later} more requests.",
                         f"Carrying it cost about {usd(c)}. Prefer targeted reads/greps or offload big outputs to subagents."))
    if dup_reads:
        n, f = dup_reads[0]
        findings.append(("low", f"{sum(n for n, _ in dup_reads)} repeated file reads, e.g. {f.split('/')[-1]} read {n}×.",
                         "Re-reading unchanged files re-adds them to context; keep a note of key facts instead."))
    if sub_cost > 0.25 * total:
        findings.append(("low", f"Subagents account for {usd(sub_cost)} ({sub_cost/total*100:.0f}%) of the session.",
                         "Fine when they isolate noisy work; check that each one needed the largest model."))
    if len(S["compactions"]) == 0 and peak["ctx"] > 2 * BIG:
        findings.append(("low", f"The session never compacted although context passed {peak['ctx']//1000}k.",
                         "Not alarming on a native-1M context window (auto-compact fires near 967k there); on the standard 200k window, run /compact (or /clear between topics) earlier to avoid hitting it mid-task."))
    if not findings:
        findings.append(("ok", "No significant cost problems detected for this session.", ""))

    # ---------- charts ----------
    cum, c_ = [], 0.0
    for r in rows:
        c_ += r["cost"]
        cum.append((r["ts"].timestamp(), c_))
    span = (t1 - t0).total_seconds()
    xfmt = (lambda x: datetime.fromtimestamp(x).strftime("%H:%M")) if span < 86400 * 1.5 else \
           (lambda x: datetime.fromtimestamp(x).strftime("%b %d %H:%M"))
    ctx_pts = [(r["ts"].timestamp(), r["ctx"]) for r in main]
    # time buckets (<= 48)
    nb = 48
    step = max(span / nb, 60)
    buckets = defaultdict(lambda: defaultdict(float))
    for r in rows:
        buckets[int((r["ts"] - t0).total_seconds() // step)][family(r["model"])] += r["cost"]
    last = max(buckets) if buckets else 0
    bcols = [((t0.timestamp() + i * step), buckets.get(i, {})) for i in range(last + 1)]
    bl = [(datetime.fromtimestamp(x).strftime("%H:%M" if span < 86400 * 1.5 else "%d %Hh"), v) for x, v in bcols]

    tool_items = sorted(((n, v[0], None) for n, v in by_tool.items()), key=lambda x: -x[1])[:8]
    split_items = [("Cache read", split["read"], "var(--good)"), ("Cache write", split["write"], "var(--warn)"),
                   ("Fresh input", split["fresh"], "var(--sonnet)"), ("Output", split["out"], "var(--opus)")]
    model_items = sorted(((m, v, None) for m, v in by_model.items()), key=lambda x: -x[1])

    sev_cls = {"high": "bad", "med": "warn", "low": "info", "ok": "good"}
    find_html = "".join(
        f'<li class="{sev_cls[s]}"><b>{esc(t)}</b>{"<br><span>"+esc(a)+"</span>" if a else ""}</li>' for s, t, a in findings)

    turn_rows = "".join(
        f'<tr><td class="num">{usd(c)}</td><td class="num">{turn_reqs[i]}</td>'
        f'<td>{esc(prompts[i][0].strftime("%b %d %H:%M"))}</td><td>{esc(prompts[i][1][:160])}</td></tr>' for c, i in turns)
    res_rows = "".join(
        f'<tr><td class="num">{usd(c)}</td><td class="num">{tok(e)}</td><td class="num">{l}</td><td>{esc(n)}</td><td>{esc(short(s))}</td></tr>'
        for c, e, l, n, s, _ in big_results[:10])
    cold_rows = "".join(
        f'<tr><td>{esc(c["ts"].strftime("%b %d %H:%M"))}</td><td class="num">{c["gap"]:.0f} min</td>'
        f'<td class="num">{tok(c["ctx"])}</td><td class="num">{usd(c["over"])}</td></tr>'
        for c in sorted(cold, key=lambda c: -c["over"])[:8])
    dup_rows = "".join(f'<tr><td class="num">{n}×</td><td>{esc(short(f, 90))}</td></tr>' for n, f in dup_reads)

    title = ""
    try:
        import sqlite3
        r = sqlite3.connect(os.path.join(D, "usage.db")).execute("SELECT title FROM sessions WHERE session=?", (sid,)).fetchone()
        title = r[0] if r else ""
    except Exception:
        pass
    title = title or (prompts[0][1][:80] if prompts else sid[:8])

    top_turns = "\n".join(f"- {usd(c)}: \"{prompts[i][1][:110]}\"" for c, i in turns[:3])
    top_pass = "\n".join(f"- {n} result ~{tok(e)} tokens (\"{short(sm, 60)}\") stayed in context for {l} requests, carry cost {usd(c)}"
                         for c, e, l, n, sm, _ in big_results[:3])
    prompt = f"""Audit the cost of a Claude Code session and recommend how to run the next one cheaper.

Session: "{title}" ({os.path.basename(S['cwd'].rstrip('/'))}), {t0.strftime('%b %d %H:%M')} to {t1.strftime('%b %d %H:%M')}.
Transcript: ~/.claude/projects/*/{sid}.jsonl (verify the findings below against it).
Total estimated cost {usd(total)} over {len(rows)} requests; peak context {tok(peak['ctx'])}; {len(S['compactions'])} compaction(s); subagents {usd(sub_cost)}.

Findings from the usage monitor:
""" + "\n".join(f"- {t} {a}".strip() for _, t, a in findings) + f"""

Costliest prompts:
{top_turns or '- n/a'}

Biggest context passengers:
{top_pass or '- n/a'}

Deliver:
1. Root causes: the working habits behind these costs, each tied to a finding above (long single session, huge tool outputs, repeated reads, idle gaps, wrong model for the job).
2. At most 5 changes, ordered by estimated savings. Each gives the exact text or setting to apply: a CLAUDE.md rule, hook, setting (e.g. earlier auto-compact threshold), or a routine for when to /clear, /compact or use a subagent, plus a handoff file.
Present the changes and wait for my approval before editing any file."""

    kpis = [("Total cost", usd(total)), ("Duration", f"{span/3600:.1f} h"), ("Requests", f"{len(rows):,}"),
            ("Peak context", tok(peak["ctx"])), ("Cache hit", f"{sum(r['cr'] for r in rows)/max(1,sum(r['inp']+r['cr']+r['c5']+r['c1'] for r in rows))*100:.0f}%"),
            ("Subagents", usd(sub_cost)), ("Compactions", str(len(S["compactions"])))]
    kpi_html = "".join(f'<div class="kpi"><span>{k}</span><b>{esc(v)}</b></div>' for k, v in kpis)

    def section(h, body, note=""):
        return f'<section><h2>{h}</h2>{"<p class=note>"+note+"</p>" if note else ""}{body}</section>' if body else ""

    NUMCOLS = {'Cost','Req','Carry cost','Size','Stayed for','Idle gap','Context','Overspend','Reads'}

    def table(head, body):
        ths = "".join('<th class="%s">%s</th>' % ("num" if h in NUMCOLS else "", h) for h in head)
        return f'<table><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table>' if body else ""

    prompt_html = '<textarea id="p" readonly rows="12" style="width:100%;font:12px/1.4 ui-monospace,Menlo,monospace;background:transparent;color:inherit;border:1px solid var(--line);border-radius:8px;padding:10px">'+esc(prompt)+'</textarea><p><button onclick="var t=document.getElementById(\'p\');t.select();document.execCommand(\'copy\');this.textContent=\'Copied ✓\'">Copy prompt</button></p>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Session review · {esc(title[:50])}</title>
<style>
:root{{--bg:#fafaf9;--card:#fff;--ink:#1c1c1e;--mute:#6e6e73;--line:#e5e5ea;--accent:#d97757;--opus:#d97757;--sonnet:#6a9bcc;--other:#8fb573;--good:#34c759;--warn:#ffb800;--bad:#ff453a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141415;--card:#1d1d1f;--ink:#f2f2f7;--mute:#9a9aa0;--line:#2c2c2e}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:960px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:17px;margin:0 0 8px}}.sub{{color:var(--mute);margin:0 0 20px;font-size:13px}}
section,.kpis{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:14px}}
.kpi span{{display:block;color:var(--mute);font-size:12px}}.kpi b{{font-size:22px}}
.note{{color:var(--mute);font-size:13px;margin:0 0 8px}}
.chart{{width:100%;height:auto}}.grid{{stroke:var(--line);stroke-width:1}}.ref{{stroke:var(--warn);stroke-dasharray:5 4}}
.axis{{fill:var(--mute);font-size:11px}}.axis.warn{{fill:var(--warn)}}
ul.find{{list-style:none;margin:0;padding:0}}ul.find li{{padding:10px 12px;border-left:4px solid var(--line);margin-bottom:8px;background:color-mix(in srgb,var(--line) 25%,transparent);border-radius:0 8px 8px 0}}
ul.find li span{{color:var(--mute);font-size:13px}}li.bad{{border-color:var(--bad)}}li.warn{{border-color:var(--warn)}}li.info{{border-color:var(--sonnet)}}li.good{{border-color:var(--good)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th{{text-align:left;color:var(--mute);font-weight:500;border-bottom:1px solid var(--line);padding:6px 8px}}
td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}}th.num,td.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.legend{{display:flex;gap:14px;font-size:12px;color:var(--mute);margin-bottom:4px}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
.foot{{color:var(--mute);font-size:12px;margin-top:20px}}
button{{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}}</style></head><body><main>
<h1>{esc(title)}</h1>
<p class="sub">{esc(os.path.basename(S['cwd'].rstrip('/')) or S['cwd'])} · {t0.strftime('%b %d %H:%M')} → {t1.strftime('%b %d %H:%M')} · session {sid[:8]}</p>
<div class="kpis">{kpi_html}</div>
{section("What to fix", f'<ul class="find">{find_html}</ul>')}
{section("Cumulative cost", svg_line(cum, fmt=usd, xfmt=xfmt), "Steeper = more expensive moments.")}
{section("Context size per request", svg_line(ctx_pts, fmt=tok, ref=(BIG, f"{BIG//1000}k"), color="var(--sonnet)", xfmt=xfmt), "Each request re-sends the whole context; cost grows with it. Drops are compactions or /clear.")}
{section("Spend over time", '<div class="legend"><span><i style="background:var(--opus)"></i>Opus</span><span><i style="background:var(--sonnet)"></i>Sonnet</span><span><i style="background:var(--other)"></i>Other</span></div>' + svg_columns(bl, fmt=usd))}
{section("Where the money went", svg_bars(split_items, fmt=usd, label_w=120) + svg_bars(model_items, fmt=usd, label_w=210), "By token type, then by model.")}
{section("Costliest prompts", table(["Cost","Req","When","Prompt"], turn_rows), "Cost of everything the agent did after each of your prompts, subagents included.")}
{section("What filled the context", svg_bars(tool_items, fmt=lambda v: tok(v) + " tok", label_w=120), "Estimated tokens returned by each tool (chars ÷ 4).")}
{section("Biggest context passengers", table(["Carry cost","Size","Stayed for","Tool","Input"], res_rows), "Carry cost = size × later requests × cache-read price. Large results that linger are the real expense.")}
{section("Cold-cache restarts", table(["When","Idle gap","Context","Overspend"], cold_rows))}
{section("Prompt to optimize this workflow", prompt_html, "Paste into a fresh Claude Code session.")}
{section("Repeated file reads", table(["Reads","File"], dup_rows))}
<p class="foot">Generated {datetime.now().strftime('%b %d %H:%M')} from the local transcript. Costs are estimates from prices.json.</p>
</main></body></html>"""
    os.makedirs(OUT_DIR, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    for f in glob.glob(os.path.join(OUT_DIR, "*.html")):  # reports written before the umask was set
        os.chmod(f, 0o600)
    out = os.path.join(OUT_DIR, f"{sid[:8]}.html")
    with open(out, "w") as fh:
        fh.write(page)
    return out, prompt


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--copy-prompt":
        _, prompt = build(sys.argv[2])
        subprocess.run(["pbcopy"], input=prompt.encode())
        notify("Optimization prompt copied")
    else:
        notify("Generating session report…")
        path, _ = build(sys.argv[1])
        subprocess.run(["open", path])
        print(path)
