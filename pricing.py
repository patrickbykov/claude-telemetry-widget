"""Shared price table and cost helpers (prices.json = USD per million tokens)."""
import json, os, re

_D = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(_D, "prices.json")) as fh:
    P = json.load(fh)

def family(model):
    for k in ("opus", "sonnet"):
        if k in model:
            return k
    return "other"

def price(model):
    hits = [k for k in P["models"] if re.search(r"(^|-)" + re.escape(k) + r"(-|$)", model)]
    return P["models"][max(hits, key=len)] if hits else P["default"]  # longest key wins: opus-5-5 beats opus-5

def parts(model, inp, out, cr, c5, c1):
    p = price(model)
    return {"fresh": inp * p["in"] / 1e6, "out": out * p["out"] / 1e6, "read": cr * p["read"] / 1e6,
            "write": (c5 * 1.25 + c1 * 2.0) * p["in"] / 1e6}

_C = json.load(open(os.path.join(_D, "config.json")))

def _window_key(window):
    return "1m" if (window or 200_000) >= 1_000_000 else "200k"

def _resolve(table, model, window):
    """table: scalar (old config, same value everywhere) or {"200k": {...}, "1m": {...}}."""
    if not isinstance(table, dict):
        return table
    wkey = _window_key(window)
    wtab = table.get(wkey) or table.get("200k") or {}
    if not isinstance(wtab, dict):  # per-window scalar, e.g. {"1m": 300000}
        return wtab
    hits = [k for k in wtab if k not in ("default", "_note")
            and re.search(r"(^|-)" + re.escape(k) + r"(-|$)", model)]
    if hits:
        return wtab[max(hits, key=len)]
    return wtab.get("default") or table.get("200k", {}).get("default") or 150_000

def big(model, window=200_000):
    """Cost threshold: an undocumented heuristic above which a session is carrying expensive context,
    not Anthropic's actual compaction point (config: ctx_big_tokens)."""
    return _resolve(_C["ctx_big_tokens"], model, window)

def smart(model, window=200_000):
    """Quality threshold (Horthy/Pocock 'smart zone' heuristic, config: ctx_smart_tokens).
    Falls back to big()'s value when the config has no ctx_smart_tokens key, so the info
    window collapses to empty rather than firing on every request."""
    tbl = _C.get("ctx_smart_tokens")
    return big(model, window) if tbl is None else _resolve(tbl, model, window)
