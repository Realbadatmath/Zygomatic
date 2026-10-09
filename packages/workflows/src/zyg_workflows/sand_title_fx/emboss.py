# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The deterministic fallback: letters embossed into the plate's own sand — verbatim
sections of the former sand_title_fx.py."""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image
import logging as _zyg_logging
from zyg_workflows.sand_title_fx.constants import (
    FONT,
    EMBOSS_DILATE_PX,
    EMBOSS_RELIEF,
    EMBOSS_FILL,
    EMBOSS_SHADOW,
    EMBOSS_SHADOW_PX,
    EMBOSS_SHADOW_SIGMA,
    EMBOSS_HEIGHT_SIGMA,
    EMBOSS_SAMPLE_PX,
    EMBOSS_GRAIN,
    EMBOSS_TRACK_FRAC,
    EMBOSS_MAX_WIDTH_FRAC,
    EMBOSS_TOP_SCALE,
    _log,
)
from zyg_workflows.sand_title_fx.ocr_gate import (
    judge_lettering,
)
from zyg_workflows.sand_title_fx.letters import (
    write_words_in_sand,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


# ── the deterministic fallback: letters embossed into the plate ─────────────
#
# Qwen-Image-Edit is the only model on this path that can write real words, and
# on a blurred or busy plate it still misspells. When the gate refuses every
# seed there has to be a way to get the words on screen that cannot misspell at
# all, and that still reads as sand rather than as a font dropped on top: the
# letters are cut out of the plate's OWN texture, given a height map, and lit
# by the same low sun as the ground. Nothing here is generative and nothing is
# random except the fine grain, so the same plate always yields the same frame.
def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float32)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise ValueError('light_dir must not be the zero vector')
    return v / n


def _emboss_dilate(mask) -> np.ndarray:
    """The 3x dilated letter mask — where the relief and the grain may go."""
    r = EMBOSS_DILATE_PX
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(mask, k)


def emboss_text_mask(W, H, words, height_frac=0.22, font=FONT) -> np.ndarray:
    """uint8 0/255 letter mask, centred, tracked, lying on the ground plane.

    The cap height is ``height_frac`` of the frame height, letters are tracked
    apart by 8 % of that cap height, and the whole run is shrunk to fit inside
    84 % of the frame width if the tracking pushed it past. A mild perspective
    then pulls the top edge in to 92 % of the bottom edge, so the words read as
    lying ON the floor rather than standing up in it."""
    from PIL import ImageDraw, ImageFont

    text = str(words)
    if not text.strip():
        raise ValueError('nothing to write')
    probe_draw = ImageDraw.Draw(Image.new('L', (8, 8)))

    def _layout(size):
        f = ImageFont.truetype(font, int(size))
        cb = probe_draw.textbbox((0, 0), 'H', font=f)
        cap = float(cb[3] - cb[1])
        track = EMBOSS_TRACK_FRAC * cap
        adv = [float(probe_draw.textlength(c, font=f)) for c in text]
        return f, cap, track, adv, sum(adv) + track * max(0, len(text) - 1)

    probe = 200
    _f, cap0, _t, _a, _w = _layout(probe)
    size = max(8, int(round(probe * (float(height_frac) * H) / max(cap0, 1e-6))))
    f, cap, track, adv, width = _layout(size)
    if width > EMBOSS_MAX_WIDTH_FRAC * W:
        size = max(8, int(size * EMBOSS_MAX_WIDTH_FRAC * W / width))
        f, cap, track, adv, width = _layout(size)

    # Drawn into a padded canvas at a nominal position, then translated so the
    # ink's own bounding box is centred: PIL's text origin is the ascender box,
    # which is not where the letters are.
    pad = int(round(cap)) + 8
    im = Image.new('L', (W + 2 * pad, H + 2 * pad), 0)
    d = ImageDraw.Draw(im)
    x = float(pad)
    for c, a in zip(text, adv):
        d.text((x, float(pad)), c, font=f, fill=255)
        x += a + track
    m = np.asarray(im, np.uint8)
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        raise ValueError(f'{words!r} drew no ink at size {size}')
    M = np.float32(
        [
            [1, 0, (pad + W / 2.0) - (float(xs.min()) + float(xs.max())) / 2.0],
            [0, 1, (pad + H / 2.0) - (float(ys.min()) + float(ys.max())) / 2.0],
        ]
    )
    m = cv2.warpAffine(m, M, (W + 2 * pad, H + 2 * pad), flags=cv2.INTER_NEAREST)[pad : pad + H, pad : pad + W]

    ys, xs = np.nonzero(m)
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    cx, half = (x0 + x1) / 2.0, (x1 - x0) / 2.0 * EMBOSS_TOP_SCALE
    P = cv2.getPerspectiveTransform(
        np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]),
        np.float32([[cx - half, y0], [cx + half, y0], [x1, y1], [x0, y1]]),
    )
    m = cv2.warpPerspective(m, P, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return (m > 127).astype(np.uint8) * 255


def emboss_cache(plate_f, mask, seed=7, light_dir=(-1.0, -0.6)) -> dict:
    """Everything in the emboss that does NOT depend on `strength`.

    Split out so a reveal can re-render the same letters at a hundred
    different strengths without recomputing the mask, the shadow field, the
    displaced sand or the height map's gradient once per frame."""
    H, W = plate_f.shape[:2]
    mf = mask.astype(np.float32) / 255.0
    dilf = _emboss_dilate(mask).astype(np.float32) / 255.0
    L = _unit(light_dir)

    # cast shadow: the mask thrown away from the sun, outside the letters only
    sx = int(round(-L[0] * EMBOSS_SHADOW_PX))
    sy = int(round(-L[1] * EMBOSS_SHADOW_PX))
    sh = np.roll(np.roll(mf, sy, axis=0), sx, axis=1)
    sh = cv2.GaussianBlur(sh, (0, 0), EMBOSS_SHADOW_SIGMA) * (1.0 - mf)

    # letter fill: the plate's own sand from 6 px up-left, darker and denser
    s = EMBOSS_SAMPLE_PX
    fill = np.roll(np.roll(plate_f, s, axis=0), s, axis=1)
    cover = cv2.GaussianBlur(mf, (0, 0), 0.8)[..., None]

    # relief: the height map's gradient lit by the same low sun
    hm = cv2.GaussianBlur(mf, (0, 0), EMBOSS_HEIGHT_SIGMA)
    dot = cv2.Sobel(hm, cv2.CV_32F, 1, 0, ksize=3) * L[0] + cv2.Sobel(hm, cv2.CV_32F, 0, 1, ksize=3) * L[1]
    peak = float(np.abs(dot).max())
    relief = (dot / peak) * dilf if peak > 1e-6 else np.zeros_like(dot)

    # fine grain, inside the dilated mask only
    rng = np.random.default_rng(seed)
    g = rng.integers(-EMBOSS_GRAIN, EMBOSS_GRAIN + 1, (H, W)).astype(np.float32)
    return {
        'mask': mask,
        'mf': mf,
        'dilf': dilf,
        'shadow': sh,
        'fill': fill,
        'cover': cover,
        'relief': relief,
        'grain': (g * dilf)[..., None],
    }


def emboss_apply(plate_f, cache, strength=1.0) -> np.ndarray:
    """The embossed plate at `strength`: 0 = bare sand, 1 = the full relief.

    `strength` scales the three things that make a letter read — the relief
    shading, how much darker the letter fill is than the sand around it, and
    the cast shadow — so ramping it from 0 to 1 raises the words OUT of the
    ground instead of cross-fading a picture of them over it."""
    s = float(np.clip(strength, 0.0, 1.0))
    out = plate_f * (1.0 - cache['shadow'] * (1.0 - EMBOSS_SHADOW) * s)[..., None]
    a = cache['cover'] * s
    out = out * (1.0 - a) + (cache['fill'] * (1.0 - (1.0 - EMBOSS_FILL) * s)) * a
    out = out + (cache['relief'] * (EMBOSS_RELIEF * s))[..., None]
    return out + cache['grain']


def emboss_words(
    plate_png, words, out_png, height_frac=0.22, font=FONT, light_dir=(-1.0, -0.6), seed=7, strength=1.0
) -> dict:
    """Write the words into the plate as raised sand. Deterministic, no GPU.

    Returns the same shape of verdict the generative path returns, read back by
    the same two-reader gate — the fallback is measured, not trusted."""
    plate = cv2.imread(plate_png, cv2.IMREAD_COLOR)
    if plate is None:
        raise FileNotFoundError(plate_png)
    H, W = plate.shape[:2]
    mask = emboss_text_mask(W, H, words, height_frac=height_frac, font=font)
    plate_f = plate.astype(np.float32)
    cache = emboss_cache(plate_f, mask, seed=seed, light_dir=light_dir)
    out = emboss_apply(plate_f, cache, strength)

    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    cv2.imwrite(out_png, np.clip(out, 0, 255).astype(np.uint8))

    ys, xs = np.nonzero(mask)
    v = judge_lettering(out_png, words, mask=mask)
    matched = (
        v.get('vlm_quote')
        if v.get('by') == 'vlm'
        else v.get('ocr_crop')
        if v.get('by') == 'ocr_crop'
        else v.get('ocr_full')
    )
    return {
        'out': os.path.abspath(out_png),
        'mask_bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        'ocr_text': matched,
        'exact': bool(v['exact']),
        'ocr_full': v.get('ocr_full'),
        'ocr_crop': v.get('ocr_crop'),
        'vlm_quote': v.get('vlm_quote'),
        'read_by': v.get('by'),
        'height_frac': float(height_frac),
        'strength': float(np.clip(strength, 0.0, 1.0)),
        'seed': int(seed),
        'method': 'emboss',
    }


def write_words_any(plate_png, words, out_png, seeds=8, log=None) -> dict:
    """The words on the plate, whatever it takes: Qwen first, emboss after.

    The generative path is tried for its own sake — sand Qwen wrote looks like
    sand nothing else can — but it is never allowed to ship a misspelling, so
    anything short of an exact read from the gate falls through to the
    deterministic emboss. The receipt says which one you got in ``method``."""
    rec = None
    try:
        rec = write_words_in_sand(plate_png, words, out_png, seeds=seeds, log=log)
    except Exception as e:  # noqa: BLE001
        _log(log, f'generative path unavailable ({e}) — embossing instead')
    if rec and rec.get('exact'):
        _log(log, f'write_words_any: qwen spelled it (seed {rec.get("seed")})')
        return dict(rec, method='qwen')
    _log(log, 'write_words_any: the gate refused every seed — embossing the words deterministically')
    out = emboss_words(plate_png, words, out_png)
    if rec:
        out['qwen'] = {k: rec.get(k) for k in ('exact', 'ocr_full', 'ocr_crop', 'seed', 'tried')}
    return out
