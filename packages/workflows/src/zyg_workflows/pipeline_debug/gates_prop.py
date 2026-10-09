# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v8b forensic gates, part 1 (2026-07-31 scene20_v8b audit): the measured prop /
border / grain constants, the BGR sampler, the prop blob+ridge primitives and
qc_prop_geometry."""

import os
from .common import _zyg_log
from .gates_v7 import _record_qc


# ── v8b forensic gates (2026-07-31, scene20_v8b defect audit) ────────────────────────
# The v8b deliverable shipped six operator-visible defects that every existing gate
# passed. Three of them are addressed here; the NCC prop gate above is retired in the
# process (see its docstring for the measured evidence).
#
# C1 — qc_prop_geometry replaces qc_prop_consistency with a TRIAD, gated on ALL:
#   (a) 4-DOF similarity-transform scale readout between context-window seam crops.
#       4-DOF ON PURPOSE: a homography (findHomography) has enough freedom to explain a
#       genuine bowl inflation as a perspective change and would hide the defect exactly
#       the way NCC does. Never swap this for findHomography.
#   (b) ABSOLUTE blob geometry sampled every 0.25s — not just at seams. v8b's pipe
#       inflates slowly and monotonically between seams, so any seam-only test misses it.
#   (c) A dark thin-structure (ridge) statistic, which is the only one of the three that
#       sees the ghost "thin black line from hand to pipe" and the stem oscillating
#       between a hairline and a thick dark band.
# Per the v9 plan's CORRECTION 3, (b) and (c) are the load-bearing checks: measured
# linear drift on v8b is only ~1.14x, i.e. below the noise floor of a |log s| <= log(1.12)
# scale gate, so (a) is corroboration and is allowed to come back "unmeasured".
#
# Calibrated on FINAL_scene20_v8b.mp4 (1664x960, 24fps, 479f, sample_every_s=0.25),
# one positive control and two negative controls on the SAME clip:
#   pipe   (0.16,0.30,0.50,0.74)   area p95/p05 2.82  ridge_flicker 2.09  -> FAIL (both)
#   candle (0.444,0.560,0.538,0.878) area p95/p05 1.26  ridge_flicker 0.17 -> PASS
#   book   (0.495,0.700,0.825,0.920) no white blob      ridge_flicker 0.70 -> PASS
# _PROP_AREA_RATIO_MAX is 1.35, RETUNED UP from the plan's proposed 1.25: the candle —
# a genuinely stable prop in the same shot, same lighting — measures 1.264, so 1.25 has
# no headroom at all and would false-FAIL a good render. 1.35 keeps ~7% margin on the
# negative control while the pipe still fails by 2.1x.
_PROP_SCALE_LOG_MAX = 0.11333  # log(1.12); |log s| above this = prop rescaled
_PROP_SCALE_INLIER_MIN = 0.50  # below this the 4-DOF fit is not trusted at all
_PROP_SCALE_MIN_INLIERS = 12  # 3-8 inliers on white clay fits noise; reject it
_PROP_AREA_RATIO_MAX = 1.35  # p95/p05 of the blob-area series (see note above)
_PROP_CANON_TOL = 0.20  # +-20% on absolute bowl width vs canon
_PROP_RIDGE_FLICKER_MAX = 1.20  # v8b pipe 2.09 FAIL | book 0.70, candle 0.17 PASS
_PROP_RIDGE_FLOOR = 0.002  # ridge-area-fraction denominator floor (see below)
_PROP_MIN_BLOB_FRAC = 0.005  # blob smaller than 0.5% of the box = not the prop
_PROP_MIN_COVERAGE = 0.50  # fewer valid samples than this = check inapplicable
# qc_frame_border: v8b carries a persistent vertical seam 30px in from the RIGHT edge
# (832-native x=800; the VACE mask's feather ramp reaches the frame edge there). Measured
# step ratio 10.3 with 0.97 persistence, vs 0.9 at the same column in the anchor still.
_BORDER_EXCESS_MIN = 6.0  # with ref_image: clip step ratio minus anchor's
_BORDER_RATIO_MIN = 8.0  # without ref_image (screening mode, see docstring)
_BORDER_PERSIST_MIN = 0.60  # fraction of sampled frames the step must survive
_BORDER_INSET_PX = 40  # search band, in 832-native px, scaled to the clip
# qc_fx_grain: v8b's 17-20s smoke takeover. Measured window-vs-body: HF noise 0.78x
# (the composite is SMOOTHER, not grainier), frame-to-frame flicker 4.69x, median
# saturation 0.08x (218 -> 18). Two-sided noise band + flicker + colour-collapse.
_FX_NOISE_RATIO_LO = 0.70
_FX_NOISE_RATIO_HI = 1.40
_FX_FLICKER_RATIO_MAX = 2.00
_FX_SAT_RATIO_MIN = 0.60


def _sampled_bgr_frames(clip_path, every_s=None, sample_every=1, max_frames=400):
    """Sequential cv2 decode → ([(t_seconds, bgr_frame), ...], fps).

    every_s (seconds) wins over sample_every (frames) when both are given. Times are in
    SECONDS on purpose: the delivered clip is retimed+upscaled (v8b is 24fps/1664x960
    from a 17fps/832x480 render), so any gate that indexes the decoded clip by frame
    number silently lands on the wrong content."""
    import cv2

    cap = cv2.VideoCapture(clip_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-3:
        fps = 17.0
    step = max(1, int(round(fps * float(every_s)))) if every_s else max(1, int(sample_every))
    out, i = [], 0
    while len(out) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            out.append((i / fps, frame))
        i += 1
    cap.release()
    return out, fps


def _prop_white_blob(crop_bgr, min_frac=_PROP_MIN_BLOB_FRAC):
    """White-clay segmentation: HSV V>185 & S<70, MORPH_OPEN 3x3, largest component.

    Returns (w, h, area, mask_uint8) or None. The V/S pair is the plan's spec and is what
    a white clay pipe / a wax candle read as under this shot's warm key light; a warm
    saturated prop (the ledger page reads S~220) legitimately returns None and the caller
    reports the geometry check INAPPLICABLE rather than inventing a blob."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 2] > 185) & (hsv[..., 1] < 70)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    area = int(st[k, cv2.CC_STAT_AREA])
    if area < min_frac * crop_bgr.shape[0] * crop_bgr.shape[1]:
        return None
    return (int(st[k, cv2.CC_STAT_WIDTH]), int(st[k, cv2.CC_STAT_HEIGHT]), area, (lab == k).astype('uint8'))


def _prop_ridges(crop_bgr, scale):
    """Thin-dark-structure statistic — the (c) leg of the C1 triad.

    STATISTIC, and why this one: morphological BLACK-HAT (closing - image) with an
    elliptical SE of ~13 render-native px. Black-hat responds to dark structures NARROWER
    than the SE and ignores large dark regions, which is the whole problem with a plain
    "dark pixel" threshold here — Cornelis's black coat fills 39-65% of the pipe box at
    any absolute threshold and drowns the stem. Components of the black-hat mask with
    area >= 30 native px and elongation (longest bbox side / shortest) >= 3.0 are counted
    as ridges. Returns (ridge_count, ridge_area_frac, ridge_max_len, dark_frac) where
    dark_frac (V<60) is carried as supporting evidence only — the GATED quantity is the
    temporal flicker of ridge_area_frac, computed by the caller."""
    import cv2
    import numpy as np

    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    k = max(3, int(round(13 * scale)) | 1)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, se)
    rm = (bh > 18).astype(np.uint8)
    rm = cv2.morphologyEx(rm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(rm, 8)
    min_area = max(30, int(30 * scale * scale))
    cnt = 0
    area = 0
    longest = 0
    for i in range(1, n):
        w = int(st[i, cv2.CC_STAT_WIDTH])
        h = int(st[i, cv2.CC_STAT_HEIGHT])
        a = int(st[i, cv2.CC_STAT_AREA])
        if a < min_area:
            continue
        if max(w, h) / max(1, min(w, h)) >= 3.0:
            cnt += 1
            area += a
            longest = max(longest, max(w, h))
    return cnt, float(area) / float(rm.size), longest, float((g < 60).mean())


def _prop_scale_pair(c0, c1, m0, m1, scale):
    """4-DOF similarity scale between two prop crops, restricted to the prop itself.

    MASKED ON PURPOSE. Matching the full box returns s = 1.000 +- 0.005 on every box of
    v8b — including the pipe box the operator can see morphing — because the static coat,
    hand and wall outvote the prop. That is the identical blindness that retired the NCC
    gate, so the SIFT detector is masked to the white blob dilated by ~11 native px.

    OpenCV TRAP (verified on 4.13.0): cv2.estimateAffinePartial2D REJECTS USAC_MAGSAC
    ("Unknown or unsupported robust estimation method"); only estimateAffine2D accepts the
    USAC family. estimateAffine2D is 6-DOF (adds shear + independent axis scale), which is
    exactly the extra freedom we are refusing. So: try USAC_MAGSAC, fall back to RANSAC,
    and keep the 4-DOF estimator either way. Returns
    (status, s|None, inlier_ratio, n_inliers, n_matches, method)."""
    import cv2
    import numpy as np

    if m0 is None or m1 is None:
        return ('no_blob', None, 0.0, 0, 0, '')
    clahe = cv2.createCLAHE(2.0, (8, 8))
    g0 = clahe.apply(cv2.cvtColor(c0, cv2.COLOR_BGR2GRAY))
    g1 = clahe.apply(cv2.cvtColor(c1, cv2.COLOR_BGR2GRAY))
    d = max(3, int(round(11 * scale)) | 1)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    k0 = cv2.dilate(m0, kern) * 255
    k1 = cv2.dilate(m1, kern) * 255
    sift = cv2.SIFT_create(nfeatures=2000, contrastThreshold=0.008, edgeThreshold=16)
    kp0, de0 = sift.detectAndCompute(g0, k0)
    kp1, de1 = sift.detectAndCompute(g1, k1)
    if de0 is None or de1 is None or len(kp0) < 8 or len(kp1) < 8:
        return ('few_keypoints', None, 0.0, 0, 0, '')
    good = [a for a, b in cv2.BFMatcher().knnMatch(de0, de1, k=2) if a.distance < 0.75 * b.distance]
    if len(good) < 8:
        return ('few_matches', None, 0.0, 0, len(good), '')
    src = np.float32([kp0[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp1[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M = inl = None
    used = ''
    for name in ('USAC_MAGSAC', 'RANSAC'):
        meth = getattr(cv2, name, None)
        if meth is None:
            continue
        try:
            M, inl = cv2.estimateAffinePartial2D(
                src, dst, method=meth, ransacReprojThreshold=3.0, maxIters=5000, confidence=0.995
            )
            used = name
            break
        except cv2.error as _exc:
            _zyg_log.debug('affine estimate via %s failed, trying the next method: %s', name, _exc)
            continue
    if M is None or inl is None:
        return ('no_model', None, 0.0, 0, len(good), used)
    ni = int(inl.sum())
    ratio = ni / float(len(good))
    s = float(np.sqrt(M[0, 0] ** 2 + M[1, 0] ** 2))
    if ratio < _PROP_SCALE_INLIER_MIN or ni < _PROP_SCALE_MIN_INLIERS:
        return ('low_support', s, ratio, ni, len(good), used)
    return ('ok', s, ratio, ni, len(good), used)


def qc_prop_geometry(
    clip_path,
    box_frac,
    canon=None,
    sample_every_s=0.25,
    log_fn=None,
    seam_times=None,
    seam_fps=17.0,
    seam_stride=None,
    area_ratio_max=None,
    ridge_flicker_max=None,
    canon_tol=None,
    fail_open=False,
):
    """Prop-geometry triad — the replacement for the retired qc_prop_consistency
    (2026-07-31, scene20_v8b "three different pipes" audit). Gates on ALL THREE:

      (a) SCALE  — 4-DOF similarity transform (cv2.estimateAffinePartial2D, USAC_MAGSAC
          where the OpenCV build allows it, else RANSAC) between the prop crops at
          consecutive context-window seams, masked to the prop blob.
          s = sqrt(M[0,0]^2 + M[1,0]^2); a pair passes when |log s| <= log(1.12) with
          inlier ratio >= 0.50 and >= 12 inliers. NEVER findHomography: 8 DOF can
          re-describe a bowl inflating as the camera moving, which is precisely how the
          old gate hid this defect. A pair with too little support is reported
          'unmeasured' and does NOT count as a pass — white clay is nearly textureless
          and on v8b every masked seam pair returns only 3-8 inliers at ratio <= 0.38,
          so this leg abstains and the verdict falls to (b) and (c) by design.
          Each pair also carries blob_scale = sqrt(area_t1/area_t0), a 1-DOF fallback
          scale readout that needs no texture; it is gated on the same |log s| bound
          whenever the feature fit abstains.

      (b) GEOMETRY vs CANON — every sample_every_s (default 0.25s, NOT only at seams,
          because v8b's bowl inflates monotonically between seams): white-blob
          segmentation, largest component, bbox w/h + area logged as a series. Fails when
          p95/p05 of the area series > area_ratio_max (default _PROP_AREA_RATIO_MAX=1.35)
          or, when canon is supplied, when the median bbox width sits outside +-tol of it.
          canon: a number (bowl width in px) or {'bowl_w_px': .., 'ref_width': 832,
          'tol': 0.20}; ref_width rescales the canon to the clip's actual width, so a
          canon measured on the 832px render still applies to the 1664px deliverable.
          If the box holds no white blob at all (a warm saturated prop, e.g. the ledger
          page at S~220) this leg reports applicable=False with a reason — it does not
          fabricate a pass; the verdict then rests on (a) and (c).

      (c) RIDGE — thin dark structure inside the box, via morphological black-hat (see
          _prop_ridges for the full definition and why a plain dark-pixel threshold is
          useless here). The GATED statistic is
              ridge_flicker = p90(|diff(ridge_area_frac series)|)
                              / max(median(ridge_area_frac), 0.002)
          i.e. how violently the thin-dark-structure content jumps between samples,
          normalised by its own level with an absolute floor so a prop with no dark
          detail at all cannot divide by ~0. This is deliberately NOT "ridge count <= 1":
          a count gate flags any prop that legitimately owns thin dark features (the
          inked ledger carries 5-9 ink strokes per frame and would fail forever), while
          the actual defect is a stem that oscillates hairline<->thick-band and a ghost
          line that blinks in and out. dark_frac (V<60) is reported as evidence only.

    Fail-CLOSED (plan item C6): an internal error returns ok=False, unlike the advisory
    gates above which pass on error. Pass fail_open=True to restore the old behaviour.

    Returns {'ok', 'scale': {...}, 'geometry': {...}, 'ridge': {...}, 'series': [...],
    'reasons': [...]}; also appended to the active DebugRun's qc (report-compatible).

    MEASURED on output/multichar_seated/scene20_v8/FINAL_scene20_v8b.mp4:
      pipe   (0.16,0.30,0.50,0.74)     FAIL — area p95/p05 2.820, ridge_flicker 2.09
      candle (0.444,0.560,0.538,0.878) PASS — area p95/p05 1.264, ridge_flicker 0.17
      book   (0.495,0.700,0.825,0.920) PASS — geometry inapplicable, ridge_flicker 0.70
    """
    # Deferred on purpose: gates_prop_triad imports the primitives and constants above,
    # so importing it at module level would be a cycle. See its docstring for the legs.
    from . import gates_prop_triad as triad

    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'prop_geometry:{os.path.basename(clip_path)}',
        'kind': 'prop_geometry',
        'path': clip_path,
        'box': list(box_frac),
        'ok': False,
        'scale': {},
        'geometry': {},
        'ridge': {},
        'series': [],
        'reasons': [],
        'checks': [],
    }
    try:
        import cv2  # noqa: F401  (kept for symmetry / early ImportError)

        arr_max = float(area_ratio_max) if area_ratio_max is not None else _PROP_AREA_RATIO_MAX
        flick_max = float(ridge_flicker_max) if ridge_flicker_max is not None else _PROP_RIDGE_FLICKER_MAX
        tol = float(canon_tol) if canon_tol is not None else _PROP_CANON_TOL

        frames, _fps = _sampled_bgr_frames(clip_path, every_s=sample_every_s)
        if len(frames) >= 400:
            out['reasons'].append(
                f'sample cap (400) hit — only the first {400 * sample_every_s:.0f}s of the clip was measured'
            )
        if len(frames) < 6:
            out['reasons'].append(f'only {len(frames)} samples — too short to measure')
            out['ok'] = bool(fail_open)  # unmeasurable is a FAIL unless told otherwise
            _record_qc(out)
            return out
        H, W = frames[0][1].shape[:2]
        scale = W / 832.0  # render-native reference width
        fx0, fy0, fx1, fy1 = box_frac
        ys = slice(int(H * fy0), int(H * fy1))
        xs = slice(int(W * fx0), int(W * fx1))
        box_area = max(1, (ys.stop - ys.start) * (xs.stop - xs.start))

        samples = triad.sample_prop_series(frames, ys, xs, scale)
        out['series'] = samples.series
        frames = None  # release the full-res decode; only crops are needed now

        # ── (b) absolute geometry vs canon ────────────────────────────────────────
        geo, blob_floor = triad.geometry_leg(samples, box_area, W, canon, tol, arr_max, out['reasons'])
        out['geometry'] = geo

        # ── (c) dark-ridge / thin-structure ───────────────────────────────────────
        ridge = triad.ridge_leg(samples, flick_max, out['reasons'])
        out['ridge'] = ridge

        # ── (a) similarity-transform scale readout at the seams ───────────────────
        pairs = triad.seam_pair_times(seam_times, samples.dur, seam_stride, seam_fps)
        sc = triad.scale_leg(samples, scale, blob_floor, pairs, out['reasons'])
        out['scale'] = sc

        # ── verdict: ALL measurable legs must pass, and at least one must exist ───
        triad.record_verdict(out, geo, ridge, sc)
        log(
            f'[qc_prop_geometry] {os.path.basename(clip_path)} box {list(box_frac)}: '
            f'scale {sc["ok"]} ({sc["measured"]}/{len(sc["pairs"])} measured) | '
            f'geometry {geo["ok"]} (p95/p05 {geo.get("area_ratio_p95_p05")}, '
            f'w {geo.get("bowl_w_med")}px) | ridge {ridge["ok"]} '
            f'(flicker {ridge["ridge_flicker"]}) -> {"PASS" if out["ok"] else "FAIL"}'
        )
        for r in out['reasons']:
            log(f'[qc_prop_geometry]   reason: {r}')
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)  # C6: geometry gates fail CLOSED
        out['reasons'].append(f'gate error: {str(e)[:160]}')
        log(f'[qc_prop_geometry] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out
