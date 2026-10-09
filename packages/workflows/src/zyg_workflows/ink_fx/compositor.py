# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.ink_fx.compositor_stages import (
    _build_composite_stats,
    _build_ink_state,
    _build_page_geometry,
    _build_reveal_plan,
    _calibrate_blur_and_grain,
    _composite_frames,
    _decode_clip_frames,
    _encode_frames,
    _resolve_occlusion_matte,
    _reveal_progress,
)
from zyg_workflows.ink_fx.write_on import _log_noop
import functools
import os
import shutil
import tempfile

import numpy as np


# ── v3: page-drift tripwire (the cheap, risk-free half of B3) ──────────────────


def page_rigid_drift_px(frames_rgb, quad_px, occluder=None, step=24, log_fn=None):
    """How far the page ACTUALLY moves, in pixels, relative to frame 0.

    This is deliberately a TRIPWIRE, not a tracker. Three independent measurements put
    scene20's page drift at 1-4px and ~96% of the page's frame-to-frame change is
    generative boil that no homography can explain, so a planar tracker + mesh warp is
    not the lever it looks like — it mostly injects wobble. The fixed quad stays; this
    readout exists so that the day an upstream change widens the generate mask and the
    page really starts to move, the run says so instead of silently smearing the ink.

    LK forward-backward (fb error < 1.0px) on paper-only corners; rigid fit with
    estimateAffinePartial2D. Features are taken OUTSIDE the occluder so the writing
    hand cannot masquerade as page motion.

    TRAP (measured on OpenCV 4.13.0): estimateAffinePartial2D does NOT accept
    USAC_MAGSAC — it raises "Unknown or unsupported robust estimation method". The
    USAC family is findHomography/findFundamentalMat only. Use RANSAC here.
    Returns {'max_px','p50_px','tracked'} or None. Never raises."""
    log = log_fn or _log_noop
    try:
        import cv2

        H, W = frames_rgb[0].shape[:2]
        poly = np.zeros((H, W), dtype=np.uint8)
        cv2.fillConvexPoly(poly, np.round(quad_px).astype(np.int32), 255)
        if occluder is not None:
            poly[np.asarray(occluder, dtype=bool)] = 0
        g0 = cv2.cvtColor(frames_rgb[0], cv2.COLOR_RGB2GRAY)
        p0 = cv2.goodFeaturesToTrack(g0, maxCorners=300, qualityLevel=0.005, minDistance=3, mask=poly)
        if p0 is None or len(p0) < 8:
            log('[ink] page drift: too few page features to measure — skipped')
            return None
        lk = dict(winSize=(15, 15), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        drifts = []
        for i in range(step, len(frames_rgb), step):
            g1 = cv2.cvtColor(frames_rgb[i], cv2.COLOR_RGB2GRAY)
            p1, s1, _ = cv2.calcOpticalFlowPyrLK(g0, g1, p0, None, **lk)
            pb, _s2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, None, **lk)
            fb = np.linalg.norm((pb - p0).reshape(-1, 2), axis=1)
            keep = (s1.ravel() == 1) & (fb < 1.0)
            if int(keep.sum()) < 8:
                continue
            M, _ = cv2.estimateAffinePartial2D(p0[keep], p1[keep], method=cv2.RANSAC, ransacReprojThreshold=2.0)
            if M is None:
                continue
            ctr = quad_px.mean(axis=0)
            moved = M[:, :2] @ ctr + M[:, 2]
            drifts.append(float(np.linalg.norm(moved - ctr)))
        if not drifts:
            return None
        out = {
            'max_px': round(float(np.max(drifts)), 2),
            'p50_px': round(float(np.median(drifts)), 2),
            'tracked': len(drifts),
        }
        log(
            f'[ink] page rigid drift vs frame 0: max {out["max_px"]}px '
            f'median {out["p50_px"]}px over {out["tracked"]} samples'
        )
        if out['max_px'] > 3.0:
            log(
                '[ink] !! page drift > 3px — the FIXED page quad is no longer valid; '
                'the ink will smear. Re-derive page_quad per frame before shipping.'
            )
        return out
    except Exception as e:
        log(f'[ink] page drift measurement failed ({e}) — advisory only, continuing')
        return None


# ── v3: the compositor ─────────────────────────────────────────────────────────


def composite_write_on_quad(
    clip_path,
    out_path,
    page_quad,
    start_s=0.0,
    end_s=None,
    fps=17,
    lines=5,
    ink_color=(48, 38, 30),
    seed=7,
    luma_adapt=True,
    reveal='lines',
    log_fn=None,
    blur_sigma='auto',
    grain=True,
    jitter=True,
    occlude='sam2',
    occluder_boxes=None,
    matte_cache='auto',
    gain=0.85,
    grain_scale='auto',
    grain_smooth=0.0,
    stats_out=None,
):
    """2026-07-30 v2 / 2026-07-31 v3 — write-on inside the ACTUAL page quad,
    perspective-correct, occlusion-aware and matched to the render's own statistics.

    page_quad: [(fx,fy) TL, TR, BR, BL] frame-fraction corners of the page.
    The script texture is built in rectified page space (make_script_texture, 2x
    supersampled) and warped into frame space. Alpha is clipped to the page polygon
    minus a 2% inset so strokes never cross the page edge.

    luma_adapt=True (default): multiply-style blend
        out = page*(1-a) + page*ink_tint*a        (ink_tint luma ~0.25)
    so ink darkens the paper proportional to local page luminance — strokes over
    candle-lit paper stay warm/bright-edged, never a flat grey overlay.
    luma_adapt=False falls back to v1's flat ink_color blend.

    reveal='lines' keeps v1's line-by-line left-to-right pacing start_s..end_s
    (unknown values log a warning and use 'lines').

    v3 arguments:
      blur_sigma   'auto' (bisect until lapvar(inked)/lapvar(raw) is in
                   SHARPNESS_TARGET) or a float. v2's frozen 0.5 measured 3.27x too
                   sharp on scene20 v8b.
      grain        per-frame multiplicative+additive noise on the ALPHA only.
      grain_scale  'auto' (bisect until the ON-INK temporal sigma matches the raw
                   render, TEMPORAL_TARGET) or a float; 1.0 = the plan's constants.
      jitter       rebuild the page homography every frame from smooth 1-D noise
                   (+-0.35px, +-0.15% scale). Together with grain this is what
                   restores the temporal sigma the deleted a_done cache destroyed.
      occlude      'sam2' | 'measure' | None. 'sam2' multiplies alpha by (1-matte) so
                   ink lands on paper only; 'measure' computes the matte and reports
                   the violation WITHOUT applying it (how the un-occluded baseline is
                   measured through the same code path).
      occluder_boxes  optional [(label,[x0,y0,x1,y1] px), ...] to skip auto-seeding.
      matte_cache  'auto' -> <out_dir>/ink_matte.npz, a path, or None.
      stats_out    optional dict; receives blur_sigma, grain_scale, sharpness_ratio,
                   temporal_sigma_ratio (+ _on_ink), matte_violation and
                   page_drift_px for the caller's QC gate. Gate on the RATIOS.

    Known knob if the operator wants heavier ink: `gain` (alpha strength) and the
    SHARPNESS_TARGET window. At sigma ~1.58 the auto-calibration is already at the
    480p mushiness ceiling, so darker ink can only come from a wider stroke
    (make_script_texture(stroke_w=...)) — which then no longer matches the render's
    own script width. Measured: v3's ink patch lapvar 179.9 vs the model's OWN
    on-page script 165.9 (1.08x) — it is as dark as this render draws ink.

    Returns out_path or None. Never raises."""
    log = log_fn or _log_noop
    try:
        import cv2  # lazy — CPU-only OpenCV
    except Exception as e:
        log(f'[ink] v2 unavailable (cv2 import failed: {e})')
        return None
    if reveal != 'lines':
        log(f"[ink] unknown reveal mode '{reveal}' — using 'lines'")
    tmp = tempfile.mkdtemp(prefix='inkfx3_')
    try:
        frames = _decode_clip_frames(clip_path, tmp, log)
        if not frames:
            return None
        n = len(frames)
        geo = _build_page_geometry(cv2, frames, page_quad, lines, seed, log)
        if geo is None:
            return None
        end_s = end_s if end_s is not None else n / fps

        matte, hard = _resolve_occlusion_matte(
            clip_path,
            frames,
            geo.quad,
            occlude=occlude,
            matte_cache=matte_cache,
            out_path=out_path,
            occluder_boxes=occluder_boxes,
            log=log,
        )
        st = _build_ink_state(
            geo,
            n,
            lines=lines,
            gain=gain,
            grain=grain,
            grain_smooth=grain_smooth,
            grain_scale=grain_scale,
            jitter=jitter,
            seed=seed,
            matte=matte if occlude == 'sam2' else None,
            luma_adapt=luma_adapt,
            ink_color=ink_color,
        )
        _prog = functools.partial(_reveal_progress, fps=fps, start_s=start_s, end_s=end_s)
        plan = _build_reveal_plan(n, _prog, frames, geo.poly_bool)
        drift = page_rigid_drift_px(
            frames, geo.quad, occluder=(hard.any(axis=0) if hard is not None else None), log_fn=log
        )
        sigma = _calibrate_blur_and_grain(
            st, plan, blur_sigma=blur_sigma, grain=grain, grain_scale=grain_scale, log=log
        )

        # ── main loop ────────────────────────────────────────────────────────
        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        totals = _composite_frames(st, frames, plan, prog=_prog, sigma=sigma, hard=hard, outdir=outdir)
        if not _encode_frames(outdir, out_path, fps, log):
            return None
        stats = _build_composite_stats(
            st, plan, totals, sigma=sigma, grain=grain, matte=matte, hard=hard, drift=drift, n=n
        )
        if isinstance(stats_out, dict):
            stats_out.update(stats)
        log(
            f'[ink] v3 quad write-on composited ({lines} lines, {start_s:.0f}-{end_s:.0f}s, '
            f'rect {geo.tw}x{geo.th}, luma_adapt={luma_adapt}, sigma={sigma:.2f}, '
            f'grain={bool(grain)}, jitter={bool(jitter)}, '
            f'occlude={st["matte"] is not None})'
        )
        log(
            f'[ink] composite integrity: sharpness {stats["sharpness_ratio"]} '
            f'(<=1.30), temporal sigma {stats["temporal_sigma_ratio"]} (>=0.60) '
            f'[on-ink {stats["temporal_sigma_ratio_on_ink"]}], '
            f'matte violation {stats["matte_violation"]} (<=0.005)'
        )
        return out_path
    except Exception as e:
        log(f'[ink] v2 failed: {e}')
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
