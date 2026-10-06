"""Shared price table and cost helpers (prices.json = USD per million tokens)."""
import json, os

_D = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(_D, "prices.json")) as fh:
    P = json.load(fh)

def family(model):
    for k in ("opus", "sonnet"):
        if k in model:
            return k
    return "other"

def price(model):
    for key, p in P["models"].items():
        if key in model:
            return p
    return P["default"]

def parts(model, inp, out, cr, c5, c1):
    p = price(model)
    return {"fresh": inp * p["in"] / 1e6, "out": out * p["out"] / 1e6, "read": cr * p["read"] / 1e6,
            "write": (c5 * 1.25 + c1 * 2.0) * p["in"] / 1e6}

_C = json.load(open(os.path.join(_D, "config.json")))

def big(model):
    """Context size above which a session on this model should be compacted (config: ctx_big_by_family)."""
    f = "haiku" if "haiku" in model else family(model)
    return _C.get("ctx_big_by_family", {}).get(f, _C["ctx_big_tokens"])
