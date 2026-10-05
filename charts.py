"""PNG chart rendering (Pillow) for the SwiftBar dropdown. Transparent background, mid-gray text: fits light and dark menus."""
import base64, io, math
from PIL import Image, ImageDraw, ImageFont

S = 6  # px per design unit; saved at 144 dpi, so 1 unit = 3 pt (3x the original size)
GRAY = (142, 142, 147, 255)
TRACK = (128, 128, 128, 60)
ORANGE, BLUE, SAGE = (217, 119, 87, 255), (106, 155, 204, 255), (143, 181, 115, 255)
GREEN, YELLOW, RED = (52, 199, 89, 255), (255, 184, 0, 255), (255, 69, 58, 255)
FAMILY = {"opus": ORANGE, "sonnet": BLUE, "other": SAGE}

_fonts = {}
def font(pt, bold=False):
    key = (pt, bold)
    if key not in _fonts:
        for path in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"):
            try:
                _fonts[key] = ImageFont.truetype(path, int(pt * S), index=1 if bold else 0)
                break
            except OSError:
                continue
        else:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]

def _new(w, h):
    im = Image.new("RGBA", (int(w * S), int(h * S)), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)

def _b64(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", dpi=(144, 144))
    return base64.b64encode(buf.getvalue()).decode()

def _text(d, x, y, s, pt=9, fill=GRAY, anchor="la", bold=False):
    d.text((x * S, y * S), s, font=font(pt, bold), fill=fill, anchor=anchor)

def _bar(d, x, y, w, h, frac, color):
    r = h * S / 2
    d.rounded_rectangle((x * S, y * S, (x + w) * S, (y + h) * S), r, fill=TRACK)
    if frac > 0:
        d.rounded_rectangle((x * S, y * S, (x + max(h, w * min(frac, 1))) * S, (y + h) * S), r, fill=color)

def _usd(v):
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"

def _trunc(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"

def limits(rows, W=340):
    """rows: [(label, pct 0-100, right_text)]"""
    H = 8 + 30 * len(rows)
    im, d = _new(W, H)
    for i, (label, pct, right) in enumerate(rows):
        y = 6 + i * 30
        col = GREEN if pct < 70 else YELLOW if pct < 90 else RED
        _text(d, 4, y, label, 10, bold=True)
        _text(d, W - 4, y, f"{pct:.0f}%  ·  {right}", 10, anchor="ra")
        _bar(d, 4, y + 16, W - 8, 7, pct / 100, col)
    return _b64(im)

def daily(days, W=340, H=118):
    """days: [(label, {family: usd})] oldest first. Stacked bars."""
    im, d = _new(W, H)
    totals = [sum(v.values()) for _, v in days]
    top = max(totals + [0.01])
    left, bottom, ch = 6, H - 16, H - 16 - 22
    n = len(days)
    slot = (W - left * 2) / n
    bw = slot * 0.66
    for i, (label, v) in enumerate(days):
        x = left + i * slot + (slot - bw) / 2
        y = bottom
        for fam in ("opus", "sonnet", "other"):
            h = v.get(fam, 0) / top * ch
            if h > 0:
                d.rectangle((x * S, (y - h) * S, (x + bw) * S, y * S), fill=FAMILY[fam])
                y -= h
        if totals[i] == max(totals) or i == n - 1:
            _text(d, x + bw / 2, y - 2, _usd(totals[i]), 8, anchor="ms", fill=GRAY)
        _text(d, x + bw / 2, bottom + 3, label, 8, anchor="ma",
              fill=ORANGE if i == n - 1 else GRAY)
    lx = 6
    for fam, name in (("opus", "Opus"), ("sonnet", "Sonnet"), ("other", "Other")):
        d.rectangle((lx * S, 4 * S, (lx + 7) * S, 11 * S), fill=FAMILY[fam])
        _text(d, lx + 10, 3, name, 8)
        lx += 12 + len(name) * 5 + 8
    return _b64(im)

def hourly(vals, now_hour, W=340, H=72):
    im, d = _new(W, H)
    top = max(vals + [0.01])
    left, bottom, ch = 6, H - 14, H - 14 - 10
    slot = (W - left * 2) / 24
    bw = slot * 0.7
    for h, v in enumerate(vals):
        x = left + h * slot + (slot - bw) / 2
        bh = v / top * ch
        col = ORANGE if h == now_hour else BLUE
        if v > 0:
            d.rectangle((x * S, (bottom - bh) * S, (x + bw) * S, bottom * S), fill=col)
        else:
            d.rectangle((x * S, (bottom - 1) * S, (x + bw) * S, bottom * S), fill=TRACK)
        if h % 6 == 0:
            _text(d, x + bw / 2, bottom + 2, f"{h:02d}", 8, anchor="ma")
    _text(d, W - 6, 0, f"peak {_usd(top)}/h", 8, anchor="ra")
    return _b64(im)

def split(parts, W=340):
    """parts: [(name, usd, color)] shown as one stacked bar + legend."""
    total = sum(p[1] for p in parts) or 1
    H = 62
    im, d = _new(W, H)
    x = 6.0
    bw = W - 12
    for name, v, col in parts:
        w = v / total * bw
        if w > 0:
            d.rectangle((x * S, 4 * S, (x + w) * S, 18 * S), fill=col)
        x += w
    for i, (name, v, col) in enumerate(parts):
        cx, cy = 6 + (i % 2) * (W / 2), 26 + (i // 2) * 16
        d.ellipse((cx * S, (cy + 2) * S, (cx + 8) * S, (cy + 10) * S), fill=col)
        _text(d, cx + 12, cy, f"{name}  {_usd(v)} · {v / total * 100:.0f}%", 9)
    return _b64(im)

def hbars(rows, W=340, colors=None, label_w=92):
    """rows: [(label, value, text)] horizontal bars scaled to the max value."""
    H = 8 + 20 * len(rows)
    im, d = _new(W, H)
    top = max([r[1] for r in rows] + [1e-9])
    for i, (label, v, text) in enumerate(rows):
        y = 6 + i * 20
        _text(d, 4, y, _trunc(label, 15), 9)
        right_w = 78
        _bar(d, label_w, y + 2, W - label_w - right_w - 6, 8, v / top,
             colors[i] if colors else ORANGE)
        _text(d, W - 4, y, text, 9, anchor="ra")
    return _b64(im)

def _badge(d, x0, T, color):
    """Draws the starburst badge with its left edge at x0 and side T."""
    d.rounded_rectangle((x0, 0, x0 + T - 1, T - 1), T * 0.26, fill=tuple(color) + (255,))
    c = T / 2
    cx = x0 + c
    ink = (28, 28, 30, 255)
    lens = [1.0, 0.7, 0.92, 0.68, 1.0, 0.74, 0.94, 0.7, 0.98, 0.72, 0.9, 0.68]
    for i, ln in enumerate(lens):
        a = math.pi * 2 * i / len(lens) - math.pi / 2
        r = T * 0.36 * ln
        w = T * 0.07
        x2, y2 = cx + math.cos(a) * r, c + math.sin(a) * r
        d.line((cx, c, x2, y2), fill=ink, width=int(w))
        d.ellipse((x2 - w / 2, y2 - w / 2, x2 + w / 2, y2 + w / 2), fill=ink)
    d.ellipse((cx - T * 0.07, c - T * 0.05, cx + T * 0.05, c + T * 0.07), fill=ink)

def _png(im, w, h):
    buf = io.BytesIO()
    im.resize((w, h), Image.LANCZOS).save(buf, "PNG", dpi=(288, 288))
    return base64.b64encode(buf.getvalue()).decode()

def icon(color, size=18):
    """Menu bar badge: state-colored rounded square with a dark Claude starburst. High contrast on light and dark bars."""
    N, K = size * 4, 6    # 4 px per pt; saved at 288 dpi so it displays `size` pt tall
    im = Image.new("RGBA", (N * K, N * K), (0, 0, 0, 0))
    _badge(ImageDraw.Draw(im), 0, N * K, color)
    return _png(im, N, N)

DOT = {"ok": (52, 199, 89), "warn": (255, 184, 0), "bad": (255, 69, 58)}

def battery(pct, size=24.2, count=None, color=None):
    """Battery drawn as a template image (black + alpha): macOS tints it with the menu bar text colour, like the system battery."""
    K = 6
    H = int(size * 4 * K)
    bw, bh, nub = int(H * 1.265), int(H * 0.66), int(H * 0.1)
    W = bw + nub + 4
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cy, lw, pad = H // 2, max(2, int(H * 0.07)), int(H * 0.05)
    top = cy - bh // 2
    d.rounded_rectangle((0, top, bw, top + bh), bh * 0.28, outline=(0, 0, 0, 115), width=lw)
    d.rounded_rectangle((bw + 2, cy - bh // 5, bw + 2 + nub, cy + bh // 5), nub / 2, fill=(0, 0, 0, 115))
    if pct:
        inner = bw - 2 * lw - 2 * pad
        fw = max(int(H * 0.08), int(inner * min(pct, 100) / 100))
        d.rounded_rectangle((lw + pad, top + lw + pad, lw + pad + fw, top + bh - lw - pad), bh * 0.14, fill=(0, 0, 0, 255))
    if color and not count:
        im = Image.merge("RGBA", (*Image.new("RGBA", (W, H), tuple(color) + (255,)).split()[:3], im.getchannel("A")))
    if count:  # session count, inverted against the fill (XOR on alpha) so it reads on both filled and empty parts
        from PIL import ImageChops
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).text((bw / 2, cy), str(min(count, 99)), font=_bigfont(int(bh * 0.7)), fill=255, anchor="mm")
        a = im.getchannel("A")
        im = Image.merge("RGBA", (*Image.new("RGBA", (W, H), tuple(color or (0, 0, 0)) + (255,)).split()[:3], ImageChops.difference(a, mask)))
    return _png(im, W // K, H // K)

def _bigfont(px):
    for path in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, px, index=1)
        except OSError:
            continue
    return ImageFont.load_default()

def gauge(frac, color, W=72, H=8):
    """Small rounded capsule for the dropdown rows (72 x 8 pt, @2x)."""
    im, d = _new(W, H)
    _bar(d, 0, 0, W, H, frac, color)
    return _png(im, W * 2, H * 2)

def battery_strip(states):
    """Test strip: one image with a battery per (pct, count, color) state."""
    ims = [Image.open(io.BytesIO(base64.b64decode(battery(p, count=c, color=col)))) for p, c, col in states]
    gap = 24
    out = Image.new("RGBA", (sum(i.width for i in ims) + gap * (len(ims) - 1), max(i.height for i in ims)), (0, 0, 0, 0))
    x = 0
    for i in ims:
        out.paste(i, (x, 0)); x += i.width + gap
    buf = io.BytesIO()
    out.save(buf, "PNG", dpi=(288, 288))
    return base64.b64encode(buf.getvalue()).decode()
