# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage helpers of the v3 quad write-on compositor.

Extracted on 2026-10-09 from ``compositor.composite_write_on_quad``, which was 327
lines long and therefore untestable: the reveal schedule, the rectified page geometry
and the statistics block could only ever be exercised by decoding a real clip. Every
helper keeps the original log lines, numeric constants and their order.
"""

import glob
import os
import subprocess
from dataclasses import dataclass

import numpy as np
from PIL import Image

from zyg_workflows.bin import exe
from zyg_workflows.ink_fx.occlusion import occlusion_matte
from zyg_workflows.ink_fx.stats_jitter import (
    _auto_blur_sigma,
    _auto_grain_scale,
    _blend,
    _build_alpha,
    _gray,
    _lap_var,
    _smooth_series,
)
from zyg_workflows.ink_fx.tunables import INK_AUTO_BLUR
from zyg_workflows.ink_fx.write_on import _ink_tint, make_script_texture


@dataclass
class _PageGeometry:
    """The rectified page space of one clip: quad, script texture and clip masks.

    ``quad`` are the frame-space corners, ``tw``/``th`` the 2x supersampled rectified
    page size, ``ink`` the script texture (0..1), ``warp_m`` the rect → frame
    homography, ``ctr`` the quad centroid, ``pmask``/``poly_bool`` the 2%-inset page
    polygon as float and bool, and ``bb`` that polygon's padded bounding box.
    """

    quad: object
    tw: int
    th: int
    ink: object
    warp_m: object
    ctr: tuple
    pmask: object
    poly_bool: object
    bb: tuple


@dataclass
class _RevealPlan:
    """Which frames carry a finished reveal, and the samples the calibration uses.

    ``full_idx`` are the frames whose reveal progress has reached 1.0, ``samp`` up to
    four spread-out sample frames, ``raw_lapvar`` their mean page sharpness,
    ``samples`` the ``(i, prog, rgb)`` triples for the sharpness bisection and
    ``block`` a CONSECUTIVE run of up to twelve frames — temporal sigma is
    meaningless on non-adjacent frames.
    """

    full_idx: list
    samp: list
    raw_lapvar: float
    samples: list
    block: list


@dataclass
class _LoopTotals:
    """What the per-frame composite loop accumulated, for the statistics block.

    ``raw_series``/``ink_series`` hold, per finished frame, the page pixels of the raw
    and inked greyscale; ``alpha_acc`` the summed alpha per page pixel; ``ink_lapvar``
    the mean inked sharpness over the sample frames; ``viol_num``/``viol_den`` the
    alpha landing on the occluder versus all alpha.
    """

    raw_series: object
    ink_series: object
    alpha_acc: object
    ink_lapvar: float
    viol_num: float
    viol_den: float


def _reveal_progress(i, fps, start_s, end_s):
    """Reveal progress of frame *i*, or ``None`` before the write-on starts.

    0.0 at ``start_s`` rising to 1.0 at ``end_s``; clamped at 1.0 afterwards.
    """
    t = i / float(fps)
    if t <= start_s:
        return None
    return min((t - start_s) / max(end_s - start_s, 1e-3), 1.0)


def _decode_clip_frames(clip_path, tmp, log):
    """Decode *clip_path* to RGB frames via ffmpeg into *tmp*.

    Returns the frame list, or ``None`` when ffmpeg failed or the clip is shorter
    than the eight frames the temporal statistics need.
    """
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            clip_path,
            '-vsync',
            '0',
            os.path.join(tmp, 'f_%05d.png'),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        log(f'[ink] v2 decode failed: {r.stderr[-200:]}')
        return None
    paths = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
    if len(paths) < 8:
        return None
    return [np.asarray(Image.open(p).convert('RGB'), dtype=np.uint8) for p in paths]


def _build_page_geometry(cv2, frames, page_quad, lines, seed, log):
    """Build the rectified page space and the script texture for *page_quad*.

    *page_quad* is the frame-fraction ``[(fx,fy) TL, TR, BR, BL]``; the rectified page
    is 2x supersampled from the quad's longest edges so strokes keep their detail, and
    the clip polygon is inset 2% toward the centroid so no stroke crosses the page
    edge. *cv2* is passed in because the caller owns the one lazy OpenCV import.
    Returns a ``_PageGeometry``, or ``None`` on a degenerate quad.
    """
    H, W = frames[0].shape[:2]
    quad = np.array([(fx * W, fy * H) for fx, fy in page_quad], dtype=np.float32)
    if abs(cv2.contourArea(quad)) < 64:
        log('[ink] v2 degenerate page_quad — abort')
        return None
    w_top = float(np.linalg.norm(quad[1] - quad[0]))
    w_bot = float(np.linalg.norm(quad[2] - quad[3]))
    h_lft = float(np.linalg.norm(quad[3] - quad[0]))
    h_rgt = float(np.linalg.norm(quad[2] - quad[1]))
    tw = max(int(round(2.0 * max(w_top, w_bot))), 32)
    th = max(int(round(2.0 * max(h_lft, h_rgt))), 32)
    ink = np.asarray(make_script_texture(tw, th, lines=lines, seed=seed), dtype=np.float32) / 255.0
    src = np.array([(0, 0), (tw, 0), (tw, th), (0, th)], dtype=np.float32)
    warp_m = cv2.getPerspectiveTransform(src, quad).astype(np.float64)
    ctr = quad.mean(axis=0)
    inset = np.round(ctr + (quad - ctr) * 0.98).astype(np.int32)
    pmask_u8 = np.zeros((H, W), dtype=np.uint8)
    cv2.fillConvexPoly(pmask_u8, inset, 255)
    poly_bool = pmask_u8 > 0
    ys, xs = np.where(poly_bool)
    bb = (
        max(0, int(ys.min()) - 4),
        min(H, int(ys.max()) + 5),
        max(0, int(xs.min()) - 4),
        min(W, int(xs.max()) + 5),
    )
    return _PageGeometry(
        quad=quad,
        tw=tw,
        th=th,
        ink=ink,
        warp_m=warp_m,
        ctr=(float(ctr[0]), float(ctr[1])),
        pmask=pmask_u8.astype(np.float32) / 255.0,
        poly_bool=poly_bool,
        bb=bb,
    )


def _resolve_occlusion_matte(clip_path, frames, quad, *, occlude, matte_cache, out_path, occluder_boxes, log):
    """Compute the hand/arm occlusion matte before anything else touches the frames.

    ``occlude='measure'`` computes the matte and lets the caller REPORT the violation
    without applying it — that is how the un-occluded v8 baseline number is produced
    through this very code path instead of a second, drifting measurement script.
    Returns ``(soft_matte, hard_matte)``, both ``None`` when no matte was produced.
    """
    if occlude in ('sam2', 'measure'):
        cache = matte_cache
        if cache == 'auto':
            cache = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'ink_matte.npz')
        got = occlusion_matte(
            clip_path, frames, quad, cache_path=cache, log_fn=log, seed_boxes=occluder_boxes, return_hard=True
        )
        if got is not None:
            return got
    elif occlude:
        log(f"[ink] unknown occlude mode '{occlude}' — no occlusion matte")
    return None, None


def _build_ink_state(
    geo, n, *, lines, gain, grain, grain_smooth, grain_scale, jitter, seed, matte, luma_adapt, ink_color
):
    """Assemble the state dict ``_build_alpha`` / ``_blend`` read for every frame.

    *matte* is already the APPLIED matte (``None`` under ``occlude='measure'``), and
    *grain_scale* may still be the string ``'auto'``, in which case the provisional
    value 1.0 — the plan's constants — goes in and the calibration replaces it.
    """
    jrng = np.random.default_rng(int(seed) + 991)
    return {
        'ink': geo.ink,
        'tw': geo.tw,
        'th': geo.th,
        'lines': lines,
        'W': geo.pmask.shape[1],
        'H': geo.pmask.shape[0],
        'warp_m': geo.warp_m,
        'ctr': geo.ctr,
        'pmask': geo.pmask,
        'poly_bool': geo.poly_bool,
        'bb': geo.bb,
        'gain': float(gain),
        'grain': bool(grain),
        'grain_smooth': float(grain_smooth),
        'grain_scale': (1.0 if isinstance(grain_scale, str) else float(grain_scale)),
        'jitter': bool(jitter),
        'seed': int(seed),
        'matte': matte,
        'luma_adapt': bool(luma_adapt),
        'tint': _ink_tint(ink_color)[None, None, :],
        'col': np.array(ink_color, dtype=np.float32),
        'jx': _smooth_series(n, jrng) if jitter else None,
        'jy': _smooth_series(n, jrng) if jitter else None,
        'js': _smooth_series(n, jrng) if jitter else None,
    }


def _build_reveal_plan(n, prog, frames, poly_bool):
    """Choose the calibration frames and measure the raw page sharpness on them.

    *prog* is the one-argument reveal-progress function. When the reveal never
    completes within the clip the tail is used instead, so the calibration always has
    frames with a full page of ink on them. Returns a ``_RevealPlan``.
    """
    full_idx = [i for i in range(n) if (prog(i) or 0.0) >= 1.0]
    if not full_idx:  # reveal never completes — use the tail
        full_idx = [i for i in range(n) if prog(i) is not None][-8:] or [n - 1]
    samp = [full_idx[int(round(k))] for k in np.linspace(0, len(full_idx) - 1, min(4, len(full_idx)))]
    samp = sorted(set(samp))
    raw_lapvar = float(np.mean([_lap_var(_gray(frames[i].astype(np.float32)), poly_bool) for i in samp]))
    samples = [(i, prog(i) or 1.0, frames[i].astype(np.float32)) for i in samp]
    b0 = max(0, len(full_idx) // 2 - 6)
    block = [(i, prog(i) or 1.0, frames[i].astype(np.float32)) for i in full_idx[b0 : b0 + 12]]
    return _RevealPlan(full_idx=full_idx, samp=samp, raw_lapvar=raw_lapvar, samples=samples, block=block)


def _calibrate_blur_and_grain(st, plan, *, blur_sigma, grain, grain_scale, log):
    """Bisect the blur sigma and the grain scale against the render's own statistics.

    Grain and blur are coupled (grain rides on the blurred alpha), so the grain scale
    is calibrated at the provisional sigma and the blur is then re-bisected once.
    Mutates ``st['grain_scale']`` exactly as the monolith did and returns the sigma.
    """
    sigma = blur_sigma
    auto = isinstance(blur_sigma, str)
    if auto and blur_sigma != 'auto':
        log(f"[ink] unknown blur_sigma '{blur_sigma}' — using 'auto'")
    if auto and not INK_AUTO_BLUR:
        sigma, auto = 1.15, False
        log('[ink] auto-blur disabled by ZYG_INK_AUTO_BLUR=0 — sigma 1.15')
    if auto:
        sigma, _ = _auto_blur_sigma(st, plan.samples, plan.raw_lapvar, log=log)
    sigma = float(sigma)
    if grain and isinstance(grain_scale, str) and len(plan.block) > 3:
        if grain_scale != 'auto':
            log(f"[ink] unknown grain_scale '{grain_scale}' — using 'auto'")
        st['grain_scale'] = _auto_grain_scale(st, plan.block, sigma, log=log)
        if auto:
            sigma, _ = _auto_blur_sigma(st, plan.samples, plan.raw_lapvar, log=log)
            sigma = float(sigma)
    return sigma


def _composite_frames(st, frames, plan, *, prog, sigma, hard, outdir):
    """Blend the ink into every frame, write the PNGs and accumulate the statistics.

    Frames before ``start_s`` are written through untouched. Returns a
    ``_LoopTotals``; ``ink_lapvar`` is already averaged over the sample frames.
    """
    poly_bool = st['poly_bool']
    npx = int(poly_bool.sum())
    full_pos = {fi: j for j, fi in enumerate(plan.full_idx)}
    samp_set = set(plan.samp)
    raw_series = np.empty((len(plan.full_idx), npx), dtype=np.float32)
    ink_series = np.empty((len(plan.full_idx), npx), dtype=np.float32)
    alpha_acc = np.zeros((npx,), dtype=np.float64)
    ink_lapvar, viol_num, viol_den, k = 0.0, 0.0, 0.0, 0
    for i in range(len(frames)):
        rgb = frames[i].astype(np.float32)
        progress = prog(i)
        if progress is None:
            out = rgb
            a = None
        else:
            a = _build_alpha(st, i, progress, sigma)
            out = _blend(st, rgb, a)
        j = full_pos.get(i)
        if j is not None:
            raw_series[j] = _gray(rgb)[poly_bool]
            ink_series[j] = _gray(out)[poly_bool]
            if a is not None:
                alpha_acc += a[poly_bool]
        if i in samp_set:
            ink_lapvar += _lap_var(_gray(out), poly_bool)
            k += 1
        if a is not None and hard is not None:
            viol_num += float((a * hard[i]).sum())
            viol_den += float(a.sum())
        Image.fromarray(np.clip(out, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
    return _LoopTotals(
        raw_series=raw_series,
        ink_series=ink_series,
        alpha_acc=alpha_acc,
        ink_lapvar=ink_lapvar / max(k, 1),
        viol_num=viol_num,
        viol_den=viol_den,
    )


def _encode_frames(outdir, out_path, fps, log):
    """Encode ``o_%05d.png`` from *outdir* to *out_path* with x264 crf 16.

    Returns True on success; on failure the ffmpeg tail is logged and False returned.
    """
    enc = subprocess.run(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-framerate',
            str(fps),
            '-i',
            os.path.join(outdir, 'o_%05d.png'),
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-crf',
            '16',
            out_path,
        ],
        capture_output=True,
        text=True,
    )
    if enc.returncode != 0:
        log(f'[ink] v2 encode failed: {enc.stderr[-200:]}')
        return False
    return True


def _build_composite_stats(st, plan, totals, *, sigma, grain, matte, hard, drift, n):
    """Assemble the QC statistics dict the caller's gate reads.

    The polygon-wide temporal sigma is diluted by bare paper that never carried ink;
    the ON-INK sigma is where the "frozen sticker" actually lives, so both are
    reported. Gate on the RATIOS, not on the absolute numbers.
    """
    full_n = len(plan.full_idx)
    s_raw = float(totals.raw_series.std(axis=0).mean()) if full_n > 1 else 0.0
    s_ink = float(totals.ink_series.std(axis=0).mean()) if full_n > 1 else 0.0
    inked_px = (totals.alpha_acc / max(full_n, 1)) > 0.05
    if inked_px.any() and full_n > 1:
        s_raw_i = float(totals.raw_series[:, inked_px].std(axis=0).mean())
        s_ink_i = float(totals.ink_series[:, inked_px].std(axis=0).mean())
    else:
        s_raw_i = s_ink_i = 0.0
    return {
        'blur_sigma': round(sigma, 3),
        'grain_scale': round(float(st['grain_scale']), 3) if grain else 0.0,
        'raw_lapvar': round(plan.raw_lapvar, 1),
        'ink_lapvar': round(totals.ink_lapvar, 1),
        'sharpness_ratio': round(totals.ink_lapvar / max(plan.raw_lapvar, 1e-6), 3),
        'raw_temporal_sigma': round(s_raw, 3),
        'ink_temporal_sigma': round(s_ink, 3),
        'temporal_sigma_ratio': round(s_ink / max(s_raw, 1e-6), 3),
        'raw_temporal_sigma_on_ink': round(s_raw_i, 3),
        'ink_temporal_sigma_on_ink': round(s_ink_i, 3),
        'temporal_sigma_ratio_on_ink': round(s_ink_i / max(s_raw_i, 1e-6), 3),
        'ink_coverage_of_page': round(float(inked_px.mean()), 3),
        'matte_violation': (round(totals.viol_num / max(totals.viol_den, 1e-6), 4) if hard is not None else None),
        'occluded': st['matte'] is not None,
        'matte_measured_only': bool(matte is not None and st['matte'] is None),
        'page_drift_px': drift,
        'frames': n,
        'sample_frames': [int(v) for v in plan.samp],
    }
