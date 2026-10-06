#!/usr/bin/env python3
# <xbar.title>Claude Code usage</xbar.title>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""Menu bar report over usage.db (SwiftBar plugin). Ingests new transcript lines, then renders text + PNG charts."""
import glob, json, os, re, sqlite3, sys, time
from datetime import datetime, timedelta, timezone

D = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, D)
import use_venv  # noqa: F401  re-runs under the venv (Pillow)
import ingest
try:
    import charts
except ImportError:  # Pillow missing: the venv is gone or broken
    print("Claude: run install.sh again (Pillow missing) | color=red")
    sys.exit(0)

ingest.run()
C = json.load(open(os.path.join(D, "config.json")))
from pricing import family, price, parts, big

def clean(s):
    # '|' starts SwiftBar parameters (bash=, param1=...) and ESC recolours ansi rows, so transcript-derived text must carry neither
    return re.sub(r"[|\x00-\x1f\x7f]+", " ", s or "")

def q(v):
    return '"' + clean(str(v)).replace('"', "") + '"'

# ---- load last 30 days, enriched ----
db = sqlite3.connect(ingest.DB)
titles = {k: clean(v) for k, v in db.execute("SELECT session, title FROM sessions")}
now = datetime.now(timezone.utc)
tz_now = datetime.now().astimezone()
midnight = tz_now.replace(hour=0, minute=0, second=0, microsecond=0)
cut30 = (now - timedelta(days=35)).strftime("%Y-%m-%dT%H:%M:%S")
raw = db.execute("SELECT ts, session, project, model, inp, out, cache_read, cc_5m, cc_1h, subagent "
                 "FROM requests WHERE ts >= ? OR session IN (SELECT session FROM requests WHERE ts >= ?) "
                 "ORDER BY session, ts", (cut30, cut30)).fetchall()  # whole history of recent sessions, so their totals are complete
R, prev = [], (None, None, 0, None)  # session, time, context, model of the previous main-thread request
BIG = C["ctx_big_tokens"]
ttl_state, ttl_model = {}, {}  # per-session TTL policy, forward-filled from the last write (c1/c5); c1==0 on a cache-hit read does NOT mean 5m
for ts, ses, proj, model, inp, out, cr, c5, c1, sub in raw:
    proj = clean(proj)
    t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    pt = parts(model, inp, out, cr, c5, c1)
    ctx = inp + cr + c5 + c1
    # a rewrite of the same-size context on the same model is a cache miss; a /clear, compaction or model switch rewrites legitimately
    cold = (not sub and prev[0] == ses and ctx > 20_000 and cr < 0.1 * ctx and model == prev[3] and ctx >= 0.8 * prev[2])
    over = (pt["write"] - (c5 + c1) * price(model)["read"] / 1e6) if cold else 0.0
    if ttl_model.get(ses) != model:  # a model switch invalidates the cache, so any earlier TTL evidence no longer applies
        ttl_state[ses] = None
        ttl_model[ses] = model
    if c1:
        ttl_state[ses] = "1h"
    elif c5:
        ttl_state[ses] = "5m"
    R.append(dict(t=t, ses=ses, proj=proj, model=model, fam=family(model), inp=inp, out=out, cr=cr,
                  cc=c5 + c1, c1=c1, ctx=ctx, bigt=big(model), pt=pt, cost=sum(pt.values()), cold=cold, over=over, sub=sub,
                  ttl=ttl_state.get(ses) or "5m"))
    if not sub:
        prev = (ses, t, ctx, model)

def scope(since):
    return [r for r in R if r["t"] >= since]

def summ(rs):
    s = dict(cost=sum(r["cost"] for r in rs), n=len(rs), out=sum(r["out"] for r in rs))
    den = sum(r["inp"] + r["cr"] + r["cc"] for r in rs)
    s["hit"] = sum(r["cr"] for r in rs) / den if den else None
    s["big"] = sum(r["cost"] for r in rs if r["ctx"] > r["bigt"])
    s["bigshare"] = s["big"] / s["cost"] if s["cost"] else 0
    s["cold"] = sum(1 for r in rs if r["cold"])
    s["over"] = sum(r["over"] for r in rs)
    return s

today, w7 = scope(midnight), scope(tz_now - timedelta(days=7))
w30 = scope(tz_now - timedelta(days=30))
wm = scope(midnight.replace(day=1))
S = {"today": summ(today), "7d": summ(w7), "30d": summ(w30), "month": summ(wm)}

def problems(s, label, judge=True):
    out = []
    if not judge:
        return out
    if s["hit"] is not None and s["hit"] < C["warn_cache_hit_below"]:
        out.append(f"{label}: cache hit {s['hit']*100:.0f}% (target >{C['warn_cache_hit_below']*100:.0f}%)")
    if s["cold"] >= C["warn_cold_restarts_at_least"]:
        out.append(f"{label}: {s['cold']} cold-cache restarts, ~${s['over']:.2f} overspend")
    if s["bigshare"] > C["warn_big_ctx_share_above"]:
        out.append(f"{label}: {s['bigshare']*100:.0f}% of spend above the cost threshold (${s['big']:.2f})")
    return out

# ---- plan limits (statusline snapshot) ----
lim_rows, lim_note = [], None
try:
    sl = json.load(open(os.path.join(D, "statusline.json")))
    age = time.time() - os.path.getmtime(os.path.join(D, "statusline.json"))
    rl = sl.get("rate_limits") or {}
    for key, label in (("five_hour", "5-hour limit"), ("seven_day", "Weekly limit")):
        e = rl.get(key)
        if not e:
            if key == "five_hour" and rl:  # Claude Code omits the 5-hour window until the next message after a reset
                lim_rows.append((label, 0.0, "no active window, starts with your next message"))
            continue
        pct = float(e.get("used_percentage", 0))
        ra = e.get("resets_at")
        if isinstance(ra, (int, float)):
            rt = datetime.fromtimestamp(ra).astimezone()
            if rt < tz_now:
                pct = 0.0
            when = rt.strftime("%H:%M") if rt.date() == tz_now.date() else rt.strftime("%a %H:%M")
            right = f"resets {when}"
        else:
            right = "reset time n/a"
        if age > 900:
            right += f" · as of {datetime.fromtimestamp(os.path.getmtime(os.path.join(D, 'statusline.json'))).strftime('%H:%M')}"
        lim_rows.append((label, pct, right))
    if not lim_rows:
        lim_note = "Plan limits not reported (API-key billing, or old version)"
except (OSError, ValueError):
    lim_note = "Plan limits: waiting for first statusline update"

judge_today = S["today"]["n"] >= C["min_today_requests_to_judge"]
pt_today = problems(S["today"], "Today", judge_today)
lim_hot = [r for r in lim_rows if r[1] >= C["warn_limit_pct_at_least"]]
pt_7d = problems(S["7d"], "7 days")
last_main, last_any = {}, {}
for r in R:  # last non-subagent request per session, and last activity of any kind
    last_any[r["ses"]] = max(last_any.get(r["ses"], r["t"]), r["t"])
    if not r["sub"] and (r["ses"] not in last_main or r["t"] >= last_main[r["ses"]]["t"]):
        last_main[r["ses"]] = r
HANDOFF = "handoff"
att = []  # (severity, title, fix, text to copy)
n_active = 0
dots = []
for sid_, r in sorted(last_main.items(), key=lambda x: -x[1]["t"].timestamp()):
    if (tz_now - last_any[sid_]).total_seconds() > C["active_window_minutes"] * 60:  # same activity rule as the dropdown: subagents count
        continue
    n_active += 1
    nm = (titles.get(sid_) or r["proj"])[:26]
    idle_min = (tz_now - r["t"]).total_seconds() / 60
    ttl_ = "1 hour" if r["ttl"] == "1h" else "5 min"
    ttl_min = 60 if r["ttl"] == "1h" else 5
    cold_now = idle_min > ttl_min  # cache warmth right now (idle vs TTL), not r["cold"] which only flags a past cache-miss rewrite
    dots.append("bad" if r["ctx"] > 2 * r["bigt"] else "warn" if r["ctx"] > r["bigt"] or cold_now else "ok")
    lim_ = r["bigt"] // 1000
    if r["ctx"] > 2 * r["bigt"] and cold_now:
        att.append(("bad", f"“{nm}” · {r['ctx']//1000}k context, cold cache", f"Over twice the {lim_}k cost threshold and the cache has expired: summarising this much costs more than restarting. Write a handoff note, then /clear.", HANDOFF))
    elif r["ctx"] > 2 * r["bigt"]:
        att.append(("bad", f"“{nm}” · {r['ctx']//1000}k context", f"Over twice the {lim_}k cost threshold, cache still warm. Run /compact with a focus note rather than restarting cold.", "compact"))
    elif r["ctx"] > r["bigt"] and cold_now:
        att.append(("warn", f"“{nm}” · {r['ctx']//1000}k context, cold cache", f"Over the {lim_}k cost threshold and the cache has already expired ({idle_min:.0f}m idle, TTL {ttl_}): compacting now still reprocesses the whole context. Reply sooner next time, or /clear and resume from a summary.", "compact"))
    elif r["ctx"] > r["bigt"]:
        att.append(("warn", f"“{nm}” · {r['ctx']//1000}k context", f"Over the {lim_}k cost threshold. Run /compact at the next task boundary while the cache is warm.", "compact"))
    elif cold_now:
        att.append(("warn", f"“{nm}” · cache cold ({idle_min:.0f}m idle)", f"Idle past the {ttl_} cache window: resuming now reprocesses the whole context. Reply sooner next time, or /compact before stepping away.", "compact"))
for r_ in lim_hot:
    att.append(("bad" if r_[1] >= 90 else "warn", f"{r_[0]} at {r_[1]:.0f}%", "Move routine work to sonnet or haiku, and delegate noisy commands to subagents.", ""))
TODAY_FIX = (("cache hit", "Avoid editing CLAUDE.md or switching models mid-session: both invalidate the cache."),
             ("cold-cache", "Reply before the cache expires (5 min on API-key usage, 1h on subscription plans), or /compact before stepping away."),
             ("of spend", "One session per task, and /clear between topics."))
for p_ in pt_today:
    att.append(("warn", p_, next(f for k_, f in TODAY_FIX if k_ in p_), ""))
warn = bool(att)

usd = lambda v: f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"
pct = lambda v: "-" if v is None else f"{v*100:.0f}%"
tok = lambda x: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}k"
def bar(frac, n=18):
    k = round(max(0.0, min(frac, 1.0)) * n)
    return "█" * k + "░" * (n - k)

M = "font=Menlo size=12"                       # monospaced: number columns only
OK = "bash=/usr/bin/true terminal=false"       # makes info rows enabled (not greyed out)
H = "size=11 color=#6e6e73,#98989d"            # section headers (light,dark pair)
SPARK = "▁▂▃▄▅▆▇█"
rgb = lambda c, t: f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m{t}\x1b[0m"
DOTC = {"ok": (52, 199, 89), "warn": (255, 149, 0), "bad": (255, 59, 48)}  # Apple systemGreen / systemOrange / systemRed
SHAPE = {"ok": "●", "warn": "▲", "bad": "◆"}   # status readable without colour
mark = lambda d_: rgb(DOTC[d_], SHAPE[d_])
SEV = {"bad": ("exclamationmark.octagon.fill", "#ff453a", "#c62828,#ff453a"),
       "warn": ("exclamationmark.triangle.fill", "#ffb800", "#b45309,#fbbf24")}
COPY = f"bash={D}/copy-text.sh terminal=false"

def wrap(text, n=72):
    out, line = [], ""
    for w_ in text.split():
        if line and len(line) + 1 + len(w_) > n:
            out.append(line); line = w_
        else:
            line = f"{line} {w_}".strip()
    return out + [line] if line else out

# ---- menu bar title: shapes (max 3) + price + battery ----
td = S["today"]
h5 = next((r[1] for r in lim_rows if r[0].lower().startswith("5")), None)
# ---- menu bar title: built from config.json -> "bar" (what to show + colour rules) ----
BAR = C.get("bar", {})
NAMED = {"red": (255, 59, 48), "orange": (255, 149, 0), "yellow": (255, 204, 0), "green": (52, 199, 89),
         "blue": (0, 122, 255), "purple": (175, 82, 222), "gray": (142, 142, 147)}
def to_rgb(v):
    if not v: return None
    if v in NAMED: return NAMED[v]
    v = v.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9a-fA-F]{6}", v) else None
h7 = next((r[1] for r in lim_rows if r[0].lower().startswith("week")), None)
worst = "bad" if any(a_[0] == "bad" for a_ in att) else "warn" if att else "ok"
M_ = {"severity": {"ok": 0, "warn": 1, "bad": 2}[worst], "5h": h5 or 0, "7d": h7 or 0, "today": td["cost"],
      "active": n_active, "attention": len(att), "cold": sum(1 for a_ in att if "cold" in a_[1]),
      "ctx_k": max([r["ctx"] for r in last_main.values()] + [0]) / 1000}
OPS = {">=": lambda x, y: x >= y, ">": lambda x, y: x > y, "<=": lambda x, y: x <= y, "<": lambda x, y: x < y, "==": lambda x, y: x == y}
bar_rgb = to_rgb(BAR.get("default_color"))
for rule in BAR.get("color_rules", []):
    try:
        if OPS[rule.get("op", ">=")](M_[rule["if"]], float(rule["value"])):
            bar_rgb = to_rgb(rule.get("color")); break
    except (KeyError, ValueError, TypeError):
        continue
FILL = {"5h": h5, "7d": h7, "none": 0}.get(BAR.get("fill", "5h"), h5)
CNT = {"active": n_active, "attention": len(att), "cold": M_["cold"], "none": None}.get(BAR.get("count", "active"), n_active)
txt = (BAR.get("text") or "").replace("{today}", usd(M_["today"])).replace("{5h}", f"{h5 or 0:.0f}").replace("{7d}", f"{h7 or 0:.0f}")
if os.path.exists(os.path.join(D, "bar-test")):  # test mode: every battery state in a row. Remove the file bar-test to turn off
    G = (142, 142, 147)
    strip = charts.battery_strip([(0, 0, G), (20, 1, G), (50, 2, NAMED["orange"]), (80, 3, NAMED["red"]), (100, 12, NAMED["orange"])])
    print(f"{txt} | image={strip}" if txt else f"| image={strip}")
else:
    img = charts.battery(FILL or 0, count=CNT, color=bar_rgb)
    kind = "image" if bar_rgb else "templateImage"
    print(f"{txt} | {kind}={img}" if txt else f"| {kind}={img}")
print("---")

# ---- Now: plan limits ----
if lim_rows:
    print(f"Plan limits | {H}")
    for label, p_, right in lim_rows:
        col = "#34c759" if p_ < 70 else "#ffb800" if p_ < 90 else "#ff453a"
        print(f"{label:<13}{bar(p_/100, 20)} {p_:>3.0f}% · {right} | {M} color={col} {OK}")
else:
    print(f"{lim_note} | {H}")

# ---- Now: needs attention (items with a submenu: fix + copy action) ----
print("---")
if att:
    att.sort(key=lambda a: a[0] != "bad")
    print(f"Needs attention | {H}")
    for sev, title, fix, copy in att[:5]:
        sym, sfc, txtc = SEV[sev]
        print(f"{title} | sfimage={sym} sfcolor={sfc} color={txtc} size=13")
        for ln in wrap(fix):
            print(f"--{ln} | size=12 {OK}")
        if copy:
            print("-----")
            print(f"--Copy {'/compact' if copy == 'compact' else 'handoff prompt'} | sfimage=doc.on.clipboard size=12 {COPY} param1={copy}")
    if len(att) > 5:
        print(f"+{len(att) - 5} more | {H}")
else:
    print("All calm | sfimage=checkmark.circle sfcolor=#34c759 size=13 " + OK)

# ---- sessions ----
ss = {}
for r in R:  # every loaded request, so sessions that started before the 7-day window are complete
    s_ = ss.setdefault(r["ses"], dict(cost=0, proj=r["proj"], first=r["t"], last=r["t"], n=0, cr=0, tot=0,
                                      maxctx=0, curctx=0, cold=0, cost7=0, bigt=big(r['model']), model=r['model']))
    s_["cost"] += r["cost"]; s_["n"] += 1; s_["cr"] += r["cr"]; s_["tot"] += r["inp"] + r["cr"] + r["cc"]
    s_["first"] = min(s_["first"], r["t"]); s_["cold"] += r["cold"]
    if r["t"] >= tz_now - timedelta(days=7):
        s_["cost7"] += r["cost"]
    if r["t"] >= s_["last"]:
        s_["last"] = r["t"]
        if not r["sub"]:
            s_["curctx"] = r["ctx"]; s_["bigt"] = r["bigt"]; s_["model"] = r["model"]
    if not r["sub"]:
        s_["maxctx"] = max(s_["maxctx"], r["ctx"])

def session_rows(sid, s, head):
    name = titles.get(sid) or f"Untitled · {s['first'].strftime('%b %d %H:%M')}"
    name = name if len(name) <= 44 else name[:43] + "…"
    print(f"{head}{name} | {M} ansi=true {OK}")
    print(f"--Project: {s['proj']} | size=12 {OK}")
    print(f"--{s['first'].strftime('%b %d %H:%M')} → {s['last'].strftime('%b %d %H:%M')} · {s['n']} requests · total {usd(s['cost'])} | size=12 {OK}")
    print(f"--Cache hit {pct(s['cr']/s['tot'] if s['tot'] else None)} · context now {tok(s['curctx'])} · peak {tok(s['maxctx'])} · {s['cold']} cache misses | size=12 {OK}")
    if s["curctx"] > s["bigt"]:
        print(f"--Context is {tok(s['curctx'])} (cost threshold {tok(s['bigt'])}): run /compact (or /clear) in that session | sfimage=exclamationmark.triangle.fill sfcolor=#ffb800 size=12 color=#b45309,#fbbf24 {OK}")
    print("-----")
    tr = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    cwd_ = ""
    if tr:
        with open(tr[0], "rb") as fh:
            for ln in fh:
                if b'"cwd"' in ln:
                    cwd_ = json.loads(ln).get("cwd", "")
                    break
    print(f"--Review session (HTML report) | size=12 bash={D}/session-report.py param1={q(sid)} terminal=false")
    print(f"--Copy prompt to optimize this session | size=12 bash={D}/session-report.py param1=--copy-prompt param2={q(sid)} terminal=false")
    print(f"--Open in terminal (iTerm) | size=12 bash={D}/open-session.sh param1={q(cwd_ or '~')} param2={q(sid)} terminal=false")
    print(f"--Copy resume command (claude --resume {sid[:8]}…) | size=12 bash={D}/copy-resume.sh param1={q(sid)} terminal=false")
    if tr:
        print(f"--Reveal transcript in Finder | size=12 bash=/usr/bin/open param1=-R param2={q(tr[0])} terminal=false")

EMOJI = {"ok": "🟢", "warn": "🟡", "bad": "🔴"}
ctx_state = lambda c, b: "bad" if c > 2 * b else "warn" if c > b else "ok"
active = sorted(((sid, s_) for sid, s_ in ss.items()
                 if (tz_now - s_["last"]).total_seconds() <= C["active_window_minutes"] * 60),
                key=lambda x: -x[1]["last"].timestamp())
print("---")
print(f"Active sessions · last {C['active_window_minutes']} min · cost, context now, last activity | {H}")
if not active:
    print(f"No active sessions | {H}")
for sid, s_ in active[:6]:
    ago = int((tz_now - s_["last"]).total_seconds() // 60)
    st = ctx_state(s_["curctx"], s_["bigt"])
    session_rows(sid, s_, f"{EMOJI[st]} {usd(s_['cost']):>7} {tok(s_['curctx']):>5} {('now' if ago < 1 else str(ago) + 'm'):>4}  ")

# ---- summaries ----
print("---")
print(f"Spend · estimate from prices.json | {H}")
for lbl, k in (("Today", "today"), ("7 days", "7d"), ("30 days", "30d"), (tz_now.strftime("%B"), "month")):
    s = S[k]
    print(f"{lbl:<9}{usd(s['cost']):>8}  cache {pct(s['hit']):>4}  {s['n']:>5} req  out {tok(s['out']):>5} | {M} {OK}")

# ---- Insights submenu ----
print("Insights | sfimage=chart.bar.xaxis")
print(f"--Daily cost, 7 days | {H}")
dcost = []
for i in range(6, -1, -1):
    day = (midnight - timedelta(days=i)).date()
    dcost.append((day, sum(r["cost"] for r in R if r["t"].date() == day)))
dmax = max(v for _, v in dcost) or 1
for day, v in dcost:
    print(f"--{day.strftime('%a %d'):<7}{bar(v/dmax, 22)} {usd(v):>7} | {M} color=#d97757 {OK}")

print("-----")
print(f"--Today by hour (00 → 23) | {H}")
hv = [0.0] * 24
for r in today:
    hv[r["t"].hour] += r["cost"]
hmax = max(hv) or 1
print(f"--{''.join(SPARK[min(7, int(v / hmax * 7.999))] if v > 0 else '·' for v in hv)}  peak {usd(hmax)}/h | {M} color=#6a9bcc {OK}")

print("-----")
print(f"--Where the money goes, 7 days | {H}")
tot = {"read": 0, "write": 0, "fresh": 0, "out": 0}
for r in w7:
    for k, v in r["pt"].items():
        tot[k] += v
t7 = sum(tot.values()) or 1
for k, name, col in (("read", "Cache read", "#34c759"), ("write", "Cache write", "#ffb800"),
                     ("fresh", "Fresh input", "#6a9bcc"), ("out", "Output", "#d97757")):
    print(f"--{name:<12}{bar(tot[k]/t7, 18)} {usd(tot[k]):>7} {tot[k]/t7*100:>3.0f}% | {M} color={col} {OK}")

print("-----")
print(f"--Spend by context size, 7 days | {H}")
total7 = S["7d"]["cost"] or 1
for name, lo, hi, col in (("< 50k", 0, 50_000, "#8fb573"), ("50–150k", 50_000, 150_000, "#6a9bcc"),
                          ("150–400k", 150_000, 400_000, "#ffb800"), ("> 400k", 400_000, 10**12, "#ff453a")):
    v = sum(r["cost"] for r in w7 if lo <= r["ctx"] < hi)
    print(f"--{name:<9}{bar(v/total7, 20)} {usd(v):>7} {v/total7*100:>3.0f}% | {M} color={col} {OK}")

print("-----")
print(f"--Projects, 7 days · \x1b[38;5;173m█\x1b[0m Opus  \x1b[38;5;74m█\x1b[0m Sonnet  \x1b[38;5;108m█\x1b[0m Other | size=11 ansi=true {OK}")
FAM_ANSI = {"opus": 173, "sonnet": 74, "other": 108}
bp = {}
for r in w7:
    d_ = bp.setdefault(r["proj"], {})
    d_[r["fam"]] = d_.get(r["fam"], 0) + r["cost"]
W_ = 16
for k, fams in sorted(bp.items(), key=lambda x: -sum(x[1].values()))[:6]:
    v = sum(fams.values())
    cells = round(v / total7 * W_)
    cells = max(cells, 1) if v > 0 else 0
    segs, used = "", 0
    for fam in ("opus", "sonnet", "other"):
        n = round(fams.get(fam, 0) / v * cells) if v else 0
        n = min(n, cells - used)
        if n:
            segs += f"\x1b[38;5;{FAM_ANSI[fam]}m" + "█" * n + "\x1b[0m"
            used += n
    if used < cells:  # rounding remainder goes to the largest family
        top_f = max(fams, key=fams.get)
        segs += f"\x1b[38;5;{FAM_ANSI[top_f]}m" + "█" * (cells - used) + "\x1b[0m"
    segs += "\x1b[38;5;240m" + "░" * (W_ - cells) + "\x1b[0m"
    print(f"--{k[:16]:<17}{segs} {usd(v):>7} {v/total7*100:>3.0f}% | {M} ansi=true {OK}")

print("---")
print(f"Costliest sessions, 7 days | {H}")
for sid, s_ in sorted(ss.items(), key=lambda x: -x[1]["cost7"])[:6]:
    session_rows(sid, s_, f"{usd(s_['cost7']):>7}  ")

print("---")
try:
    with open(os.path.join(D, "update.json")) as fh:
        behind = json.load(fh).get("behind", 0)
except (OSError, ValueError):
    behind = 0
if behind:
    print(f"Update available ({behind} new) | sfimage=arrow.down.circle color=orange bash={D}/update.sh terminal=true")
print("Refresh now | sfimage=arrow.clockwise refresh=true shortcut=CMD+R")
print(f"Edit prices | shell=/usr/bin/open param1=-t param2={D}/prices.json terminal=false")
print(f"Customize status bar | shell=/usr/bin/open param1=-t param2={D}/config.json terminal=false")
print(f"Edit thresholds | shell=/usr/bin/open param1=-t param2={D}/config.json terminal=false")
print(f"Update | sfimage=arrow.triangle.2.circlepath bash={D}/update.sh terminal=true")
