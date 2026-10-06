# Calculation methods

How the widget turns raw transcript usage numbers into cost, context size, and cache-state
advice. "D" marks something documented by Anthropic; "H" marks an undocumented heuristic this
project chose.

Source of truth: `pricing.py` (cost), `claude-usage.2m.py` (live menu), `session-report.py`
(per-session HTML report), `ingest.py` (parses `~/.claude/projects/**/*.jsonl` into `usage.db`).

## Cost (D for the price model; the split itself is the raw API fields)

Each request reports four token buckets: fresh input (`inp`), cache read (`cr`), 5-minute cache
write (`c5`), 1-hour cache write (`c1`), plus output (`out`). Cost per bucket, from
`pricing.py:parts()`:

```
fresh = inp * price_in
out   = out * price_out
read  = cr  * price_read
write = (c5 * 1.25 + c1 * 2.0) * price_in
```

`price_in` / `price_out` / `price_read` come from `prices.json`, matched against the model id
(longest matching key wins, e.g. `opus-5-5` over `opus-5`). The 1.25x / 2.0x write multipliers
are Anthropic's documented cache-write premiums for 5-minute and 1-hour TTL cache entries
(platform.claude.com/docs/en/prompt-caching) — paying more up front to read cheaply later.

Total request cost is the sum of all four parts.

## Context size (H: this is what "context" means in this project's UI)

```
ctx = inp + cr + c5 + c1
```

All four buckets together are what occupied the model's context window for that request —
not just the fresh tokens. This is the number shown as "Nk context" in the menu and reports.

## Cost threshold — `ctx_big_tokens` (H)

A single configurable number (`config.json: ctx_big_tokens`, default 150,000) above which a
request is flagged as carrying expensive context. This is **not** Anthropic's actual
auto-compact point (see below) — it's just the line past which this project decides a session's
spend is worth drawing attention to. `>2x` the threshold is treated as the "bad" tier.

It's deliberately set below the real compaction threshold so the warning stays reachable even
on models with a hard 200k context window (Opus 4.6, Bedrock/Foundry, or
`CLAUDE_CODE_DISABLE_1M_CONTEXT=1`) — a 200k-only model could never cross a 200k warning line.

Compare with the real thing (D, from
code.claude.com/docs/en/{costs,prompt-caching,model-config}):
auto-compact fires at ~200k tokens on the standard context window, or ~967k on models with a
native 1M context window. There's no price jump at either point — compaction is about context
capacity, not cost.

## Cold-cache detection (H)

A request is flagged "cold" (a cache-miss rewrite of context that should have been a cache hit)
when, compared to the previous main-thread request in the same session:

```
not sub
and same session as previous
and ctx > 20,000
and cr < 0.1 * ctx          # almost nothing was read from cache
and model == previous model  # not a model switch
and ctx >= 0.8 * previous ctx  # roughly the same size, not a fresh /clear
```

The same-size-same-model check exists to distinguish "the cache silently expired and got
rewritten" from "the user legitimately started over" (`/clear`, `/compact`, or a model switch
all produce a smaller or differently-shaped context by design, not a same-size rewrite).

`over` = write cost minus what a cache *read* of the same tokens would have cost — the
estimated overspend caused by that one cold rewrite.

This detection is backward-looking: it answers "was the *last* request a cache-miss rewrite?",
which is a different question from "is the cache warm *right now*" (see TTL below). The two are
not interchangeable — right after a cold rewrite the cache is freshly warm again, and a session
can go cold from idling without ever producing another request that trips this check.

## Cache TTL (D for the TTL values; tracking them per-request is H)

Claude Code's prompt cache TTL is:
- **1 hour** for the main conversation while within plan/subscription usage
- **5 minutes** for API-key billing, cloud/usage-credit billing, or once plan usage credits are
  exhausted mid-session

The TTL a session is actually using can change mid-session (e.g. plan credits run out). The
`ephemeral_1h_input_tokens` (`c1`) vs `ephemeral_5m_input_tokens` (`c5`) fields on a *write*
request are the only direct evidence of which TTL is in effect — a cache-*hit* request (reading
an existing cache) reports `c1=0`/`c5=0` regardless of which TTL that cache was written under,
so TTL can't be read off a single request in isolation.

`claude-usage.2m.py` tracks TTL per session, forward-filled from the last main-thread write
(`c1` or `c5`), and resets to unknown on a model switch (a different model means a different
cache, so earlier evidence no longer applies). Subagent requests share the parent session ID
in the database but run their own model and cache, so they're excluded from this tracking —
only main-thread writes update the session's TTL evidence.

"Is the cache warm *right now*" (forward-looking, used for live advice) is then:

```
idle_min = now - last_main_request_time
ttl_min  = 60 if ttl == "1h" else 5
cold_now = idle_min > ttl_min
```

## Plan limits (D: values come directly from Claude Code's own statusline snapshot)

5-hour and weekly usage percentages are read as-is from `statusline.json`
(`rate_limits.five_hour` / `rate_limits.seven_day`), which Claude Code itself writes. No
calculation — just staleness-checked (flagged if the snapshot is >15 min old) and formatted.

## Session HTML report specifics

`session-report.py` re-derives cold-cache restarts and the big-context share independently
(same formulas as above, scoped to one session's main-thread rows), and additionally computes:

- **`big_save`**: the portion of read+write cost attributable to tokens beyond the threshold,
  pro-rated by `(ctx - BIG) / ctx` — an estimate of what compacting at the threshold would have
  saved.
- **Never-compacted finding**: fires when a session's peak context exceeded `2 * BIG` and it
  never ran `/compact` — low severity, since this is expected and fine on a native-1M context
  window (compaction isn't due until ~967k there).
