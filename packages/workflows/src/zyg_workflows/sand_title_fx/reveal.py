# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The reveal: grains swirling in, the haze envelope, the streak tails and the encoder —
verbatim sections of the former sand_title_fx.py."""

from __future__ import annotations

import os
import subprocess

import cv2
import numpy as np
from zyg_workflows.bin import exe
import logging as _zyg_logging
from zyg_workflows.sand_title_fx.constants import (
    BAND_FRAC,
    N_PARTICLES,
    STREAK_PX,
    GRAIN,
    FONT,
    RAMP_PARTICLES,
    RAMP_BAND_FRAC,
    RAMP_STREAK_PX,
    RAMP_GRAIN_PX,
    RAMP_GRAIN_MUL,
    RAMP_HAZE_PEAK,
    RAMP_HAZE_AT,
    RAMP_RELIEF_START,
    _log,
)
from zyg_workflows.sand_title_fx.letters import (
    letters_mask,
)
from zyg_workflows.sand_title_fx.emboss import (
    emboss_text_mask,
    emboss_cache,
    emboss_apply,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


# ── the reveal ──────────────────────────────────────────────────────────────
def _smoothstep(x):
    x = float(np.clip(x, 0.0, 1.0))
    return x * x * (3.0 - 2.0 * x)


def _ease_io(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _band(mask, radius):
    """Everything within `radius` px of the lettering."""
    dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    return dist <= radius


def _haze_env(u):
    """0 → 1 → 0, peaking at RAMP_HAZE_AT: the haze gathers, then settles."""
    u = float(np.clip(u, 0.0, 1.0))
    if u <= RAMP_HAZE_AT:
        return _smoothstep(u / RAMP_HAZE_AT)
    return 1.0 - _smoothstep((u - RAMP_HAZE_AT) / (1.0 - RAMP_HAZE_AT))


def _haze_field(rng, H, W, dilf, u):
    """A noise cloud confined to the dilated mask, condensing as `u` grows.

    The cell size shrinks with time, so the haze starts as a soft cloud over
    the words and ends as fine grain sitting in them."""
    cell = max(3, int(round(min(H, W) / (12.0 + 40.0 * float(u)))))
    n = rng.random((max(2, H // cell), max(2, W // cell)), dtype=np.float32)
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_CUBIC)
    return np.clip(0.45 + 0.55 * n, 0.0, 1.0) * dilf


def _grain_layer(pos, prev, col, thick, H, W):
    """(colour, coverage) for the grains in flight.

    Drawn as premultiplied colour + its own alpha so the caller can composite
    ``frame*(1-cov) + colour``: the grains REPLACE the sand under them (they
    are 0.62x its brightness) instead of being added to it, which is what
    makes them visible against a bright plate."""
    colour = np.zeros((H, W, 3), np.float32)
    cov = np.zeros((H, W), np.float32)
    v = pos - prev
    n = np.linalg.norm(v, axis=1, keepdims=True)
    unit = np.divide(v, np.maximum(n, 1e-6))
    tail = pos - unit * RAMP_STREAK_PX
    for j in range(pos.shape[0]):
        x1, y1 = pos[j]
        if not (-RAMP_STREAK_PX <= x1 < W + RAMP_STREAK_PX and -RAMP_STREAK_PX <= y1 < H + RAMP_STREAK_PX):
            continue
        p0 = (int(tail[j, 0]), int(tail[j, 1]))
        p1 = (int(x1), int(y1))
        k = int(thick[j])
        c = col[j]
        cv2.line(colour, p0, p1, (float(c[0]), float(c[1]), float(c[2])), k, cv2.LINE_AA)
        cv2.line(cov, p0, p1, 1.0, k, cv2.LINE_AA)
    return colour, cov[..., None]


def swirl_in(
    src_png,
    words_png,
    out_mp4,
    fps=24,
    dur_s=1.5,
    hold_s=0.0,
    seed=7,
    log=None,
    words_text=None,
    relief_ramp=True,
    height_frac=0.22,
    font=FONT,
    light_dir=(-1.0, -0.6),
) -> int:
    """Sand blows in and settles into the words. Returns the frame count.

    Two reveals live here.

    The ORIGINAL one crossfades the plate to `words_png` INSIDE the dilated
    letter mask only — the plate around the words never dissolves, because
    nothing about it changed — with a thin additive spray of grains over it.
    It is what you get when no `words_text` is supplied, and it is unchanged.

    The RELIEF RAMP (`relief_ramp=True` *and* a `words_text`) does not
    crossfade at all: the words frame is rebuilt every output frame by
    `emboss_apply` at a strength that smoothsteps from 0 over the last 65 % of
    the run, so the letters RISE out of the sand, and the grains are
    composited OVER the plate at 0.62x its brightness instead of being added
    to it, so they actually read.  A condensing sand haze inside the dilated
    mask carries the middle of the shot, where the letters are still too low
    to see.  `words_text` is required because the relief is rebuilt from the
    letter mask, and only the text can regenerate that mask."""
    src = cv2.imread(src_png, cv2.IMREAD_COLOR)
    words = cv2.imread(words_png, cv2.IMREAD_COLOR)
    if src is None or words is None:
        raise FileNotFoundError(src_png if src is None else words_png)
    H, W = src.shape[:2]
    if words.shape[:2] != (H, W):
        words = cv2.resize(words, (W, H), interpolation=cv2.INTER_LANCZOS4)
    srcf = src.astype(np.float32)

    ramp = bool(relief_ramp) and bool(words_text)
    cache = None
    if ramp:
        mask = emboss_text_mask(W, H, words_text, height_frac=height_frac, font=font)
        cache = emboss_cache(srcf, mask, seed=seed, light_dir=light_dir)
        words = np.clip(emboss_apply(srcf, cache, 1.0), 0, 255).astype(np.uint8)
    else:
        mask = letters_mask(src_png, words_png)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        raise ValueError('no lettering found between the plate and the words frame — nothing to swirl in')

    n_part = RAMP_PARTICLES if ramp else N_PARTICLES
    band_frac = RAMP_BAND_FRAC if ramp else BAND_FRAC
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(ys), n_part)
    tgt = np.stack([xs[pick], ys[pick]], 1).astype(np.float32)
    off = np.stack(
        [rng.uniform(-band_frac * W, band_frac * W, n_part), rng.uniform(-band_frac * H, band_frac * H, n_part)], 1
    )
    start = tgt + off.astype(np.float32)
    col = src[tgt[:, 1].astype(int), tgt[:, 0].astype(int)].astype(np.float32)
    thick = None
    if ramp:
        # drawn only on this path, so the legacy reveal's rng stream -- and
        # therefore its grain -- is bit-identical to what it always was
        thick = rng.integers(RAMP_GRAIN_PX[0], RAMP_GRAIN_PX[1], n_part)
        col = col * RAMP_GRAIN_MUL

    band = _band(mask, band_frac * min(W, H))
    soft = (cv2.GaussianBlur(mask, (5, 5), 0).astype(np.float32) / 255.0)[..., None]
    wordf = words.astype(np.float32)
    haze_col = srcf * RAMP_GRAIN_MUL

    n_anim = max(2, int(round(dur_s * fps)))
    n_hold = int(round(hold_s * fps))
    proc = _ffmpeg(out_mp4, W, H, fps)
    try:
        for i in range(n_anim):
            u = i / (n_anim - 1)
            t = u * dur_s
            e = _ease_io(u)
            e0 = _ease_io(max(0.0, u - 1.0 / (n_anim - 1)))
            pos = start + (tgt - start) * e
            prev = start + (tgt - start) * e0
            alpha = 1.0 if u < 0.8 else max(0.0, (1.0 - u) / 0.2)
            if ramp:
                # the letters rise out of the ground over the last 65 %
                s = _smoothstep((t - RAMP_RELIEF_START * dur_s) / ((1.0 - RAMP_RELIEF_START) * dur_s))
                frame = emboss_apply(srcf, cache, s)
                ah = RAMP_HAZE_PEAK * _haze_env(u)
                if ah > 1e-4:
                    a = (_haze_field(rng, H, W, cache['dilf'], u) * ah)[..., None]
                    frame = frame * (1.0 - a) + haze_col * a
                if alpha > 0:
                    gc, gcov = _grain_layer(pos, prev, col, thick, H, W)
                    frame = frame * (1.0 - gcov * alpha) + gc * alpha
            else:
                # base: src → words, inside the mask only
                s = _smoothstep((t - 0.6 * dur_s) / (0.9 * dur_s - 0.6 * dur_s))
                a = soft * s
                frame = srcf * (1 - a) + wordf * a
                if alpha > 0:
                    frame += _streaks(pos, prev, col, H, W) * alpha
                g = rng.integers(-GRAIN, GRAIN + 1, (H, W), dtype=np.int16)
                frame += (g * band).astype(np.float32)[..., None]
            proc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        for _ in range(n_hold):
            proc.stdin.write(words.tobytes())
        proc.stdin.close()
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if rc != 0:
        raise RuntimeError(f'ffmpeg exited {rc} writing {out_mp4}')
    total = n_anim + n_hold
    _log(log, f'swirl{" (relief ramp)" if ramp else ""}: {total} frames @ {fps} fps → {out_mp4}')
    return total


def _streaks(pos, prev, col, H, W):
    """Additive motion-blurred grains: a 3 px tail behind each particle."""
    layer = np.zeros((H, W, 3), np.float32)
    v = pos - prev
    n = np.linalg.norm(v, axis=1, keepdims=True)
    unit = np.divide(v, np.maximum(n, 1e-6))
    tail = pos - unit * STREAK_PX
    for j in range(pos.shape[0]):
        x1, y1 = pos[j]
        if not (-STREAK_PX <= x1 < W + STREAK_PX and -STREAK_PX <= y1 < H + STREAK_PX):
            continue
        c = col[j]
        cv2.line(
            layer,
            (int(tail[j, 0]), int(tail[j, 1])),
            (int(x1), int(y1)),
            (float(c[0]), float(c[1]), float(c[2])),
            1,
            cv2.LINE_AA,
        )
    return layer * 0.55


def _ffmpeg(out_mp4, W, H, fps):
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    cmd = [
        exe('ffmpeg'),
        '-y',
        '-loglevel',
        'error',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'bgr24',
        '-s',
        f'{W}x{H}',
        '-r',
        str(fps),
        '-i',
        '-',
        '-an',
        '-c:v',
        'libx264',
        '-crf',
        '14',
        '-preset',
        'medium',
        '-pix_fmt',
        'yuv420p',
        out_mp4,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)
