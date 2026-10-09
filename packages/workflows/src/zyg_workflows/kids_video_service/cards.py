# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Drawn fallback cards — the flat PIL cartoon that ships when ComfyUI is down.

Moved verbatim out of the old single-file kids_video_service.py (lines 1755-2009).
"""

from __future__ import annotations

import math
import re

from zyg_workflows.kids_video_service.constants import (
    RENDER_H,
    RENDER_W,
)
from zyg_workflows.kids_video_service.motifs import (
    _COLOUR_RGB,
    _COUNT_WORDS,
)


# ── Drawn fallback cards ─────────────────────────────────────────────────────
#
# When ComfyUI is unavailable every slot still gets a picture.  This is the same
# design claim the audio side makes with the score render: the workflow must
# deliver something when the GPU is busy, and it must SAY which leg delivered it.

_PALETTE = [
    (255, 92, 92),
    (255, 183, 61),
    (255, 231, 87),
    (108, 214, 122),
    (91, 190, 240),
    (140, 130, 235),
    (255, 140, 190),
]
_INK = (34, 34, 40)


def _sky(d, W, H, ground=0.72, ground_rgb=(126, 214, 96)):
    """Soft sky gradient with a ground band and one dark horizon line."""
    gy = int(H * ground)
    for y in range(gy):
        f = y / max(1.0, gy)
        d.line([(0, y), (W, y)], fill=(int(170 + 66 * f), int(220 + 28 * f), int(255 - 8 * f)))
    if ground_rgb:
        d.rectangle([0, gy, W, H], fill=ground_rgb)
        d.line([(0, gy), (W, gy)], fill=_INK, width=5)
    return gy


def _draw_balloon(d, cx, cy, r, col):
    d.ellipse([cx - r, cy - r * 1.18, cx + r, cy + r * 1.18], fill=col, outline=_INK, width=7)
    d.polygon(
        [(cx - r * 0.16, cy + r * 1.12), (cx + r * 0.16, cy + r * 1.12), (cx, cy + r * 1.36)], fill=col, outline=_INK
    )
    d.ellipse([cx - r * 0.62, cy - r * 0.86, cx - r * 0.26, cy - r * 0.26], fill=_lighten(col))
    # A smooth hanging string, sampled off a sine — the earlier zigzag read as a
    # spring rather than as string.
    pts = []
    for k in range(24):
        f = k / 23.0
        pts.append((cx + math.sin(f * 5.2) * r * 0.24, cy + r * (1.36 + f * 1.5)))
    d.line(pts, fill=_INK, width=4, joint='curve')


def _lighten(col, f=0.42):
    return tuple(int(c + (255 - c) * f) for c in col)


def _draw_block(d, cx, base, s, col):
    """A FLAT toy block, deliberately not an isometric cube.

    Measured: the first version drew shaded left/top/right faces, and CLIP
    scored a single one of them 0.446 on the cartoon contrast — it reads as "a
    realistic 3d rendered image", which for a shaded cube is a fair reading and
    exactly what this workflow must not produce.  Flat face, rounded corners, one
    printed inner square: unmistakably a toy, unmistakably a drawing.
    """
    top = base - s
    d.rounded_rectangle([cx - s / 2, top, cx + s / 2, base], radius=s * 0.14, fill=col, outline=_INK, width=7)
    d.rounded_rectangle(
        [cx - s * 0.30, top + s * 0.20, cx + s * 0.30, base - s * 0.20],
        radius=s * 0.08,
        outline=_lighten(col, 0.55),
        width=6,
    )
    d.line([(cx - s * 0.34, top + s * 0.10), (cx + s * 0.34, top + s * 0.10)], fill=_lighten(col, 0.5), width=6)


def _draw_apple(d, cx, cy, r, col):
    d.ellipse([cx - r, cy - r * 0.92, cx + r, cy + r], fill=col, outline=_INK, width=6)
    d.line([(cx, cy - r * 0.86), (cx + r * 0.1, cy - r * 1.35)], fill=_INK, width=7)
    d.ellipse([cx + r * 0.06, cy - r * 1.5, cx + r * 0.85, cy - r * 1.05], fill=(108, 205, 96), outline=_INK, width=5)
    d.ellipse([cx - r * 0.58, cy - r * 0.55, cx - r * 0.2, cy - r * 0.1], fill=_lighten(col))


def _draw_ball(d, cx, cy, r, col):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=_INK, width=6)
    for dx, dy, rr in ((-0.42, 0.12, 0.19), (0.30, -0.30, 0.16), (0.18, 0.42, 0.13)):
        d.ellipse(
            [cx + (dx - rr) * r, cy + (dy - rr) * r, cx + (dx + rr) * r, cy + (dy + rr) * r], fill=_lighten(col, 0.55)
        )


def _draw_star(d, cx, cy, r, col):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rad = r if k % 2 == 0 else r * 0.44
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    d.polygon(pts, fill=col, outline=_INK)
    d.line(pts + [pts[0]], fill=_INK, width=6, joint='curve')


def _draw_flower(d, cx, cy, r, col):
    d.line([(cx, cy + r * 0.7), (cx, cy + r * 2.4)], fill=(70, 160, 70), width=9)
    for k in range(6):
        a = k * math.pi / 3
        px, py = cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72
        d.ellipse([px - r * 0.46, py - r * 0.46, px + r * 0.46, py + r * 0.46], fill=col, outline=_INK, width=5)
    d.ellipse([cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4], fill=(255, 214, 66), outline=_INK, width=5)
    d.ellipse([cx - r * 0.19, cy - r * 0.14, cx - r * 0.07, cy + r * 0.02], fill=_INK)
    d.ellipse([cx + r * 0.07, cy - r * 0.14, cx + r * 0.19, cy + r * 0.02], fill=_INK)
    d.arc([cx - r * 0.2, cy - r * 0.05, cx + r * 0.2, cy + r * 0.25], 20, 160, fill=_INK, width=5)


_COUNT_DRAW = {
    'balloon': ('float', _draw_balloon),
    'apple': ('rest', _draw_apple),
    'ball': ('rest', _draw_ball),
    'star': ('float', _draw_star),
    'flower': ('rest', _draw_flower),
    'block': ('block', _draw_block),
}


def draw_count_card(spec, path, rng):
    """Exactly ``spec['n']`` objects, in ``spec['colours']``, on a plain ground.

    Same visual language as the generated frames — flat fills, one dark outline,
    plain background — but the number is a fact rather than a request.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H = RENDER_W, RENDER_H
    img = Image.new('RGB', (W, H), (176, 226, 255))
    d = ImageDraw.Draw(img)
    item = str(spec.get('item') or 'balloon')
    mode, fn = _COUNT_DRAW.get(item, _COUNT_DRAW['balloon'])
    n = max(1, min(10, int(spec.get('n') or 1)))
    cols = [_COLOUR_RGB.get(c, (238, 63, 63)) for c in (spec.get('colours') or [])]
    while len(cols) < n:
        cols.append(_PALETTE[len(cols) % len(_PALETTE)])

    ground = (126, 214, 96) if item in ('flower',) else (232, 208, 172) if item in ('block', 'apple', 'ball') else None
    gy = _sky(d, W, H, ground=0.74, ground_rgb=ground)
    # ALWAYS a sky with something in it.  A single object on an empty gradient is
    # the weakest card there is — measured, a lone ball scored 0.753 on the
    # cartoon contrast against 0.99 for four of them, because an empty frame
    # gives CLIP nothing picture-book to read. Clouds and a smiling sun cost
    # nothing and make every card unambiguously a drawing.
    u = W * 0.042
    for bx, by, sc in ((W * 0.14, H * 0.15, 1.0), (W * 0.70, H * 0.13, 0.72)):
        for dx, s in ((-1.2, 0.78), (0.0, 1.05), (1.25, 0.74)):
            rr = s * u * sc
            cx2 = bx + dx * u * sc
            d.ellipse([cx2 - rr, by - rr, cx2 + rr, by + rr], fill=(255, 255, 255), outline=_INK, width=5)
    sx, sy, sr = W * 0.90, H * 0.14, W * 0.052
    for k in range(12):
        a = k * math.pi / 6.0
        d.line(
            [
                (sx + math.cos(a) * sr * 1.18, sy + math.sin(a) * sr * 1.18),
                (sx + math.cos(a) * sr * 1.55, sy + math.sin(a) * sr * 1.55),
            ],
            fill=_INK,
            width=6,
        )
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 214, 66), outline=_INK, width=6)
    d.ellipse([sx - sr * 0.42, sy - sr * 0.3, sx - sr * 0.20, sy - sr * 0.02], fill=_INK)
    d.ellipse([sx + sr * 0.20, sy - sr * 0.3, sx + sr * 0.42, sy - sr * 0.02], fill=_INK)
    d.arc([sx - sr * 0.46, sy - sr * 0.08, sx + sr * 0.46, sy + sr * 0.52], 20, 160, fill=_INK, width=6)

    # One row, centred.  Sized GENEROUSLY: a burst frame is on screen for half a
    # second, so the objects have to be countable at a glance — the first version
    # drew them at 15 % of the frame width and three balloons read as confetti.
    slot_w = min(W * 0.30, (W * 0.90) / n)
    r = slot_w * 0.40
    x0 = (W - slot_w * n) / 2.0 + slot_w / 2.0
    for k in range(n):
        cx = x0 + k * slot_w
        col = cols[k]
        if mode == 'block':
            fn(d, cx, gy + slot_w * 0.05, min(slot_w * 0.74, H * 0.42), col)
        elif mode == 'float':
            cy = H * 0.36 + (slot_w * 0.08 if k % 2 else -slot_w * 0.08)
            fn(d, cx, cy, min(r, H * 0.20), col)
        else:
            rr = min(r, H * 0.22)
            fn(d, cx, gy - rr * 0.94, rr, col)
    try:
        img.save(path)
        return True
    except OSError:
        return False


def _draw_card(slot, path, rng):
    """A flat cartoon card drawn with PIL — sky, ground, sun, and the slot's own
    count of friendly shapes.  Deliberately the same visual language as the
    generated frames: flat fills, dark outlines, nothing photographic.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H = RENDER_W, RENDER_H
    img = Image.new('RGB', (W, H), (176, 226, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, int(H * 0.68)):
        f = y / max(1.0, H * 0.68)
        d.line([(0, y), (W, y)], fill=(int(168 + 60 * f), int(222 + 26 * f), int(255 - 10 * f)))
    gy = int(H * 0.68)
    d.rectangle([0, gy, W, H], fill=(126, 214, 96))
    d.line([(0, gy), (W, gy)], fill=(30, 30, 30), width=5)
    # sun
    cx, cy, r = int(W * 0.84), int(H * 0.17), int(H * 0.09)
    for k in range(12):
        a = k * math.pi / 6.0
        d.line(
            [
                (cx + math.cos(a) * r * 1.15, cy + math.sin(a) * r * 1.15),
                (cx + math.cos(a) * r * 1.55, cy + math.sin(a) * r * 1.55),
            ],
            fill=(30, 30, 30),
            width=6,
        )
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 214, 66), outline=(30, 30, 30), width=6)
    d.ellipse([cx - r * 0.4, cy - r * 0.3, cx - r * 0.2, cy - r * 0.05], fill=(30, 30, 30))
    d.ellipse([cx + r * 0.2, cy - r * 0.3, cx + r * 0.4, cy - r * 0.05], fill=(30, 30, 30))
    d.arc([cx - r * 0.45, cy - r * 0.1, cx + r * 0.45, cy + r * 0.5], 20, 160, fill=(30, 30, 30), width=6)
    # clouds
    for k in range(2):
        bx = int(W * (0.12 + 0.28 * k)) + rng.randrange(-40, 40)
        by = int(H * (0.13 + 0.06 * k))
        for dx, s in ((0, 46), (52, 62), (110, 44)):
            d.ellipse([bx + dx - s, by - s, bx + dx + s, by + s], fill=(255, 255, 255), outline=(30, 30, 30), width=5)
    # the slot's own subject count: 1..6 friendly shapes on the ground
    n = 1
    m = re.match(r'^(one|two|three|four|five|six|seven|eight|nine|ten)\b', str(slot.get('idea') or '').lower())
    if m:
        n = _COUNT_WORDS.index(m.group(1)) + 1
    else:
        n = 1 + (slot.get('i', 0) % 4)
    n = max(1, min(6, n))
    bw = int(W * 0.11)
    gap = int(bw * 0.35)
    total = n * bw + (n - 1) * gap
    x0 = (W - total) // 2
    base = int(H * 0.82)
    for k in range(n):
        col = _PALETTE[(slot.get('i', 0) + k) % len(_PALETTE)]
        x = x0 + k * (bw + gap)
        d.rounded_rectangle(
            [x, base - bw, x + bw, base], radius=int(bw * 0.18), fill=col, outline=(30, 30, 30), width=6
        )
    try:
        img.save(path)
        return True
    except OSError:
        return False
