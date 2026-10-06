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

def big(model):
    """Cost threshold: an undocumented heuristic above which a session is carrying expensive context,
    not Anthropic's actual compaction point (config: ctx_big_tokens)."""
    return _C["ctx_big_tokens"]
