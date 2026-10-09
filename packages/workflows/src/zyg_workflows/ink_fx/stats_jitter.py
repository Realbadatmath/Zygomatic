# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.ink_fx.tunables import (
    BLUR_SIGMA_RANGE,
    GRAIN_ADD_SIGMA,
    GRAIN_MUL_SIGMA,
    JITTER_CORR_FRAMES,
    JITTER_PX,
    JITTER_SCALE,
    SHARPNESS_TARGET,
    TEMPORAL_TARGET,
)
from zyg_workflows.ink_fx.write_on import _log_noop, _reveal_lines_mask

import numpy as np


# ── v3 helpers: statistics, smooth jitter, alpha grain (2026-07-31) ─────────────


def _gray(rgb_f32):
    """Rec.601 luma of an HxWx3 float array — matches cv2.cvtColor(BGR2GRAY)."""
    return (0.299 * rgb_f32[:, :, 0] + 0.587 * rgb_f32[:, :, 1] + 0.114 * rgb_f32[:, :, 2]).astype(np.float32)


def _lap_var(gray, region_bool):
    """Laplacian variance inside a boolean region — the sharpness statistic the
    v8b forensics used (raw page 222.4, inked page 728.2)."""
    import cv2

    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    v = lap[region_bool]
    return float(v.var()) if v.size else 0.0


def _smooth_series(n, rng, corr=JITTER_CORR_FRAMES):
    """Unit-variance 1-D noise with ~corr frames of correlation length.

    WHY not white noise: a +-0.35px white-noise offset buzzes at the frame rate and
    reads as a vibrating sticker — exactly the artefact we are removing. Smooth noise
    at ~6 frames reads as a breathing page / hand-held camera."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    k = max(3, (int(round(corr * 3)) | 1))
    x = np.arange(k, dtype=np.float64) - k // 2
    g = np.exp(-0.5 * (x / max(float(corr), 1e-3)) ** 2)
    g /= g.sum()
    w = rng.normal(0.0, 1.0, n + 2 * k)
    s = np.convolve(w, g, mode='same')[k : k + n]
    sd = float(s.std())
    return (s / sd).astype(np.float32) if sd > 1e-6 else s.astype(np.float32)


def _jitter_warp(base_m, ctr, dx, dy, ds):
    """Similarity (scale about ctr + translation) pre-multiplied onto the page
    homography, so the whole rectified page breathes instead of individual strokes."""
    s = 1.0 + float(ds)
    a = np.array(
        [[s, 0.0, ctr[0] * (1.0 - s) + float(dx)], [0.0, s, ctr[1] * (1.0 - s) + float(dy)], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return a @ base_m


def _build_alpha(st, i, prog, sigma):
    """One frame's ink alpha in FRAME space.

    Order matters: warp -> blur -> polygon clip/gain -> grain -> occlusion matte.
    The matte goes LAST so grain can never re-deposit ink on the hand, and the grain
    is applied to the alpha (never the frame) so the paper is not noised twice."""
    import cv2

    m = st['warp_m']
    if st['jitter'] and st['jx'] is not None:
        m = _jitter_warp(m, st['ctr'], st['jx'][i] * JITTER_PX, st['jy'][i] * JITTER_PX, st['js'][i] * JITTER_SCALE)
    a = cv2.warpPerspective(
        st['ink'] * _reveal_lines_mask(st['tw'], st['th'], st['lines'], prog),
        m,
        (st['W'], st['H']),
        flags=cv2.INTER_LINEAR,
    )
    a = cv2.GaussianBlur(a, (0, 0), float(sigma)) * st['pmask'] * st['gain']
    if st['grain'] and st['grain_scale'] > 0:
        y0, y1, x0, x1 = st['bb']
        sub = a[y0:y1, x0:x1]
        gs = float(st['grain_scale'])
        rng = np.random.default_rng((int(st['seed']) * 1000003 + i) & 0x7FFFFFFF)
        mul = rng.normal(0.0, GRAIN_MUL_SIGMA * gs, sub.shape).astype(np.float32)
        add = rng.normal(0.0, GRAIN_ADD_SIGMA * gs, sub.shape).astype(np.float32)
        if st['grain_smooth'] > 0:
            mul = cv2.GaussianBlur(mul, (0, 0), st['grain_smooth'])
            add = cv2.GaussianBlur(add, (0, 0), st['grain_smooth'])
            mul *= (GRAIN_MUL_SIGMA * gs) / max(float(mul.std()), 1e-6)
            add *= (GRAIN_ADD_SIGMA * gs) / max(float(add.std()), 1e-6)
        a[y0:y1, x0:x1] = sub * (1.0 + mul) + add * (sub > 0.02)
    if st['matte'] is not None:
        a = a * (1.0 - st['matte'][i])
    return np.clip(a, 0.0, 1.0)


def _blend(st, rgb, a):
    a3 = a[:, :, None]
    if st['luma_adapt']:
        return rgb * (1.0 - a3 * (1.0 - st['tint']))  # = page*(1-a) + page*tint*a
    return rgb * (1.0 - a3) + st['col'] * a3


def _auto_blur_sigma(st, samples, raw_lapvar, log=_log_noop):
    """Bisect the frame-space blur so lapvar(inked)/lapvar(raw) lands in
    SHARPNESS_TARGET. The ratio is monotonically decreasing in sigma (blur only ever
    removes high frequency), so plain bisection on log-sigma converges in ~10 steps.

    WHY auto rather than the plan's fixed sigma~1.15: the required blur depends on the
    render's own softness, which changes with shot scale, model and upscaler. Gate on
    the RATIO, never an absolute number."""
    lo, hi = BLUR_SIGMA_RANGE

    def ratio(sig):
        if raw_lapvar <= 1e-6:
            return 1.0
        acc = 0.0
        for i, prog, rgb in samples:
            a = _build_alpha(st, i, prog, sig)
            acc += _lap_var(_gray(_blend(st, rgb, a)), st['poly_bool'])
        return (acc / max(len(samples), 1)) / raw_lapvar

    r_lo, r_hi = ratio(lo), ratio(hi)
    if r_lo <= SHARPNESS_TARGET[1]:
        log(f'[ink] auto-blur: sigma {lo} already gives ratio {r_lo:.2f} — using it')
        return lo, r_lo
    if r_hi > SHARPNESS_TARGET[1]:
        log(
            f'[ink] auto-blur: even sigma {hi} gives ratio {r_hi:.2f} '
            f'(> {SHARPNESS_TARGET[1]}) — clamping (strokes would go mushy past this)'
        )
        return hi, r_hi
    a_lo, b_hi, r = lo, hi, r_hi
    mid = hi
    for _ in range(12):
        mid = float(np.sqrt(a_lo * b_hi))
        r = ratio(mid)
        if SHARPNESS_TARGET[0] <= r <= SHARPNESS_TARGET[1]:
            break
        if r > SHARPNESS_TARGET[1]:
            a_lo = mid
        else:
            b_hi = mid
    log(
        f'[ink] auto-blur: sigma {mid:.3f} -> sharpness ratio {r:.2f} '
        f'(target {SHARPNESS_TARGET[0]}-{SHARPNESS_TARGET[1]})'
    )
    return mid, r


def _temporal_ratio(st, block, sigma):
    """Per-pixel temporal sigma of the composite vs the raw render, measured over a
    CONSECUTIVE block of frames and restricted to pixels that actually carry ink."""
    alphas = [_build_alpha(st, i, prog, sigma) for (i, prog, _rgb) in block]
    inked = (np.mean([a for a in alphas], axis=0) > 0.05) & st['poly_bool']
    if not inked.any():
        return 1.0
    raw = np.stack([_gray(rgb)[inked] for (_i, _p, rgb) in block])
    ink = np.stack([_gray(_blend(st, rgb, a))[inked] for (_i, _p, rgb), a in zip(block, alphas)])
    s_raw = float(raw.std(axis=0).mean())
    return float(ink.std(axis=0).mean()) / max(s_raw, 1e-6)


def _auto_grain_scale(st, block, sigma, log=_log_noop):
    """Bisect a scalar on (GRAIN_MUL_SIGMA, GRAIN_ADD_SIGMA) until the ink's temporal
    sigma MATCHES the render's own (ratio ~1.0) instead of merely clearing the 0.60
    floor.

    WHY: the plan's grain constants were calibrated against a 3.94-sigma reference.
    Applied unchanged to a render whose on-ink sigma is 2.9 they overshoot to 1.55,
    and ink that boils harder than the paper it sits on is its own sticker tell —
    'crawling ink' instead of 'frozen ink'. Scale 1.0 reproduces the plan exactly."""
    lo, hi = 0.0, 2.5
    r_lo = _temporal_ratio(st, block, sigma)  # st['grain_scale'] is set by caller
    if r_lo >= TEMPORAL_TARGET[0]:
        log(f'[ink] auto-grain: base scale already gives temporal ratio {r_lo:.2f}')
    st_gs = st['grain_scale']
    try:
        st['grain_scale'] = hi
        if _temporal_ratio(st, block, sigma) < TEMPORAL_TARGET[0]:
            log(f'[ink] auto-grain: clamped at {hi} (render is noisier than the grain)')
            return hi
        st['grain_scale'] = lo
        if _temporal_ratio(st, block, sigma) > TEMPORAL_TARGET[1]:
            log('[ink] auto-grain: 0 — the blend alone already matches the render')
            return 0.0
        mid, r = st_gs, 0.0
        for _ in range(10):
            mid = 0.5 * (lo + hi)
            st['grain_scale'] = mid
            r = _temporal_ratio(st, block, sigma)
            if TEMPORAL_TARGET[0] <= r <= TEMPORAL_TARGET[1]:
                break
            if r > TEMPORAL_TARGET[1]:
                hi = mid
            else:
                lo = mid
        log(
            f'[ink] auto-grain: scale {mid:.3f} -> temporal sigma ratio {r:.2f} '
            f'(target {TEMPORAL_TARGET[0]}-{TEMPORAL_TARGET[1]})'
        )
        return mid
    finally:
        st['grain_scale'] = st_gs
