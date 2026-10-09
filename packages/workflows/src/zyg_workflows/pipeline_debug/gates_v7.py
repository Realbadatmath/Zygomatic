# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v7 forensic gates (2026-07-30 scene20_v7 incident): dense-flow region motion
and prop NCC across context-window seams, plus the shared threshold resolver,
grayscale sampler and `_record_qc` writer the later gate generations reuse."""

import os
from .common import _zyg_log
from .run_report import DebugRun, get_active


# ── v7 forensic gates (2026-07-30 scene20_v7 incident) ───────────────────────────────
# Frame-by-frame forensics on scene20_v7 caught two defect classes the existing gates
# missed: (1) Abel's writing hand was FROZEN (Farneback flow 0.07 px/sample) yet the
# track: gate PASSED him at 44px path — candle flicker moves point APPEARANCE, so PyrLK
# tracks drift on shimmer; the metric is gameable. (2) the pipe MORPHED at the context-
# window seam (frames 233/234, 13.2-13.9s) — bowl inflates, stem kinks, grip flips —
# which no whole-clip average can see. These gates measure exactly what the forensics
# measured: dense-flow magnitude per region (shimmer-proof: flow needs real edges to
# move) and prop appearance NCC across context-window boundaries.
#
# Calibrated on scene20_v7/pasted17.mp4 (832x480, 17fps, 341f), sample_every=4:
#   flow px/sample : a_hand 0.069 FROZEN | c_hands 0.211, pipe 0.292 alive
#                    heads: a_head 0.130, c_head 0.311 (calm heads → gate lower)
#   churn p95      : all regions 0.02-0.34 on v7 (no boil) → 0.55 has headroom
#   pipe NCC       : morph-window pairs 0.511/0.666/0.677 vs clean 0.745-0.961
_REGION_FLOW_MIN = 0.12  # hands/props: frozen 0.069 vs alive 0.211+ → mid-gap
_REGION_FLOW_MIN_HEAD = 0.06  # suggested for head regions (calm heads move less)
_REGION_CHURN_MAX = 0.55  # p95 of (1 - edge-map corrcoef); morph/boil re-draws edges
_PROP_NCC_MIN = 0.70  # in the measured gap: morphed ≤0.677 < 0.70 < clean ≥0.745
_CONTEXT_STRIDE_FRAMES = 57  # context_frames 81 - context_overlap 24 (v7 render recipe)


def _gate_thr(spec, name, default):
    """Threshold resolver: None → calibrated default, scalar → same for all regions,
    {name: value} → per-region (missing names fall back to the default)."""
    if spec is None:
        return default
    if isinstance(spec, dict):
        return spec.get(name, default)
    return spec


def _sampled_gray_frames(clip_path, sample_every=1):
    """Sequential cv2 decode → (list of grayscale uint8 frames every Nth, fps)."""
    import cv2

    cap = cv2.VideoCapture(clip_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-3:
        fps = 17.0  # pipeline-native pre-interp rate; only used for note text
    frames = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % max(1, int(sample_every)) == 0:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        i += 1
    cap.release()
    return frames, fps


def _record_qc(out):
    """Append a qc record to the active DebugRun (if a real one exists) — same shape
    the qc_* methods write, so report.json/report.html render it unchanged."""
    try:
        dbg = get_active()
        if isinstance(dbg, DebugRun):
            dbg.doc['qc'].append(out)
            dbg._save()
    except Exception as _exc:
        _zyg_log.warning('qc record not appended to the active debug run: %s', _exc)


def qc_region_flow(clip_path, regions, min_flow=None, max_churn=None, sample_every=4, log_fn=None):
    """Shimmer-proof per-region motion + morph gate (2026-07-30, scene20_v7 frozen-Abel).

    regions: {name: (fx0, fy0, fx1, fy1)} fractional boxes. Per region, on every
    sample_every-th frame (grayscale, native res — the forensic method):
      flow  : Farneback dense optical flow between consecutive samples, mean magnitude
              in px/sample. Dense flow needs real structure to move — candle flicker
              re-lighting a static hand reads ~0, unlike PyrLK point drift.
      churn : Sobel gradient-magnitude maps of consecutive samples, 1 - corrcoef.
              Stable structure ≈ 0 even under light-play; morphing/boiling re-draws
              edges and spikes it.
    min_flow / max_churn: scalar or {name: value}; None → calibrated defaults
    (_REGION_FLOW_MIN=0.12 for hands/props — pass ~_REGION_FLOW_MIN_HEAD=0.06 for calm
    head regions; _REGION_CHURN_MAX=0.55 on churn p95). Gate: flow_mean >= min_flow
    AND churn_p95 <= max_churn.

    Returns {'ok', 'regions': {name: {'flow_mean','flow_p95','churn_mean','churn_p95',
    'ok'}}}; also appended to the active DebugRun's qc (report-compatible). Fail-safe:
    any internal error returns {'ok': True, 'error': ...} — QC breakage never blocks."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'region_flow:{os.path.basename(clip_path)}',
        'kind': 'region_flow',
        'path': clip_path,
        'ok': True,
        'regions': {},
        'checks': [],
    }
    try:
        import cv2
        import numpy as np

        arrs, _fps = _sampled_gray_frames(clip_path, sample_every)
        if len(arrs) < 3:
            out['error'] = f'only {len(arrs)} sampled frames — too short to measure'
            _record_qc(out)
            return out
        H, W = arrs[0].shape
        for name, (fx0, fy0, fx1, fy1) in (regions or {}).items():
            ys = slice(int(H * fy0), int(H * fy1))
            xs = slice(int(W * fx0), int(W * fx1))
            crops = [a[ys, xs] for a in arrs]
            flows, churns = [], []
            for i in range(len(crops) - 1):
                fl = cv2.calcOpticalFlowFarneback(crops[i], crops[i + 1], None, 0.5, 3, 15, 3, 5, 1.2, 0)
                flows.append(float(np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2).mean()))
                ga = cv2.Sobel(crops[i].astype('float32'), cv2.CV_32F, 1, 0, ksize=3)
                gb = cv2.Sobel(crops[i].astype('float32'), cv2.CV_32F, 0, 1, ksize=3)
                g0 = np.sqrt(ga * ga + gb * gb).ravel()
                ga = cv2.Sobel(crops[i + 1].astype('float32'), cv2.CV_32F, 1, 0, ksize=3)
                gb = cv2.Sobel(crops[i + 1].astype('float32'), cv2.CV_32F, 0, 1, ksize=3)
                g1 = np.sqrt(ga * ga + gb * gb).ravel()
                if g0.std() < 1e-6 or g1.std() < 1e-6:
                    churns.append(0.0)  # featureless crop — no structure to churn
                else:
                    churns.append(float(1.0 - np.corrcoef(g0, g1)[0, 1]))
            r = {
                'flow_mean': round(float(np.mean(flows)), 3),
                'flow_p95': round(float(np.percentile(flows, 95)), 3),
                'churn_mean': round(float(np.mean(churns)), 3),
                'churn_p95': round(float(np.percentile(churns, 95)), 3),
            }
            mn = _gate_thr(min_flow, name, _REGION_FLOW_MIN)
            mx = _gate_thr(max_churn, name, _REGION_CHURN_MAX)
            flow_ok = r['flow_mean'] >= mn
            churn_ok = r['churn_p95'] <= mx
            r['ok'] = bool(flow_ok and churn_ok)
            out['regions'][name] = r
            # fail_kind splits the two DIFFERENT defect classes this one check
            # conflates: 'frozen' (frozen-motion) and 'churn' (set-churn/boiling).
            # They have different remedies and different calibration maturity —
            # the frozen half separates 4.5x across its threshold (v8a 0.080 vs
            # v8b 0.364) and blocks; the churn half fires at 0.553 against a 0.55
            # floor on known-good runs and only warns. qc_contract routes on this.
            r['fail_kind'] = '' if r['ok'] else ('frozen' if not flow_ok else 'churn')
            note = ''
            if not flow_ok:
                note = (
                    f'flow {r["flow_mean"]:.2f} px/sample < {mn} — region FROZEN '
                    f'(appearance shimmer does not count as motion)'
                )
            elif not churn_ok:
                note = f'edge churn p95 {r["churn_p95"]:.2f} > {mx} — structure re-drawn (morph/boil), not just re-lit'
            out['checks'].append({'check': f'region_flow:{name}', **r, 'note': note})
            log(
                f'[qc_region_flow] {name}: flow {r["flow_mean"]:.3f} '
                f'(p95 {r["flow_p95"]:.3f}) churn {r["churn_mean"]:.3f} '
                f'(p95 {r["churn_p95"]:.3f}) → {"PASS" if r["ok"] else "FAIL"}'
            )
        out['ok'] = all(r['ok'] for r in out['regions'].values()) if out['regions'] else True
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = True  # fail-safe: broken QC never blocks generation
        log(f'[qc_region_flow] ERROR (fail-safe pass): {e}')
    _record_qc(out)
    return out


def qc_prop_consistency(clip_path, box_frac, pairs=None, ncc_min=None, log_fn=None):
    """DEPRECATED 2026-07-31 — RETIRED as a gate; kept callable for back-compat only.
    Use qc_prop_geometry() instead. Do not add new callers; do not re-enable this as a
    blocking check.

    WHY it was retired (all measured on the real deliverable
    output/multichar_seated/scene20_v8/FINAL_scene20_v8b.mp4, pipe box
    (0.16,0.30,0.50,0.74) — the shot where the operator can see three different pipes):

      * IT PASSES THE DEFECT. All-pairs NCC at this gate's own box scored the operator's
        three-distinct-pipe pairs 5.0s↔12.5s = 0.809, 5.0s↔16.0s = 0.821,
        12.5s↔16.0s = 0.895 — every one of them ABOVE _PROP_NCC_MIN=0.70, i.e. PASS.
      * IT FAILS A NON-DEFECT. A same-object pair, 2.0s↔8.0s, scored 0.676 — a false
        FAIL below the same threshold. Morph and non-morph distributions OVERLAP, so no
        threshold on this statistic works; it is not a calibration problem.
      * NO SCALE SEARCH. cv2.matchTemplate slides a template but never rescales it, so a
        bowl that inflates is simply matched at its best-fitting offset.
      * MEAN/VARIANCE NORMALISED. TM_CCOEFF_NORMED subtracts the mean and divides by the
        s.d. of each patch, so it absorbs a white→black polarity swap and any global
        brightness/contrast change — exactly the appearance changes a morph produces.
      * BOX DOMINATED BY STATIC PIXELS. The prop occupies ~20% of the box; the coat,
        hand and wall behind it are static, so the score is mostly a measurement of the
        background agreeing with itself.
      * SEAM-ONLY SAMPLING. It only compares context-window boundary pairs, so slow
        monotonic inflation between seams is invisible to it by construction.

    Original behaviour, unchanged (2026-07-30, scene20_v7 pipe morph at the
    context-window seam). A rigid prop must look like ITSELF across chain boundaries —
    the seam frames are where VACE re-imagines it (bowl inflates, grip flips).

    box_frac: (fx0, fy0, fx1, fy1) prop box. pairs: explicit [(t0, t1), ...] seconds;
    None → consecutive context-window boundaries at the render recipe's 57-frame stride
    (context 81 - overlap 24), i.e. frames 0,57,114,... paired consecutively. Per pair,
    the grayscale prop crops at t0/t1 are compared by (a) NCC template match — the
    center-inset of the t1 crop searched over the t0 crop (TM_CCOEFF_NORMED max), so a
    prop that merely SHIFTS still scores high while one that MORPHS does not — and
    (b) edge-map IoU (Canny, 3x3-dilated), reported for evidence. A pair fails when
    ncc < ncc_min (None → calibrated _PROP_NCC_MIN=0.70).

    Returns {'ok', 'pairs': [{'t0','t1','ncc','edge_iou','ok'}]}; appended to the
    active DebugRun's qc. Fail-safe: internal error → {'ok': True, 'error': ...}."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'prop_consistency:{os.path.basename(clip_path)}',
        'kind': 'prop_consistency',
        'path': clip_path,
        'ok': True,
        'pairs': [],
        'checks': [],
    }
    try:
        import cv2
        import numpy as np

        arrs, fps = _sampled_gray_frames(clip_path, 1)
        n = len(arrs)
        if n < 2:
            out['error'] = f'only {n} frames decoded'
            _record_qc(out)
            return out
        if pairs is None:
            bounds = list(range(0, n, _CONTEXT_STRIDE_FRAMES))
            pairs = [(bounds[i] / fps, bounds[i + 1] / fps) for i in range(len(bounds) - 1)]
        thr = _PROP_NCC_MIN if ncc_min is None else float(ncc_min)
        H, W = arrs[0].shape
        fx0, fy0, fx1, fy1 = box_frac
        ys = slice(int(H * fy0), int(H * fy1))
        xs = slice(int(W * fx0), int(W * fx1))
        for t0, t1 in pairs:
            i0 = min(max(int(round(t0 * fps)), 0), n - 1)
            i1 = min(max(int(round(t1 * fps)), 0), n - 1)
            c0, c1 = arrs[i0][ys, xs], arrs[i1][ys, xs]
            ch, cw = c1.shape
            my, mx_ = max(4, ch // 10), max(4, cw // 10)  # translation tolerance inset
            tmpl = c1[my : ch - my, mx_ : cw - mx_]
            if tmpl.size == 0 or tmpl.std() < 1e-6 or c0.std() < 1e-6:
                ncc = 0.0
            else:
                res = cv2.matchTemplate(c0, tmpl, cv2.TM_CCOEFF_NORMED)
                ncc = float(np.nan_to_num(res).max())
            k = np.ones((3, 3), np.uint8)
            e0 = cv2.dilate(cv2.Canny(c0, 60, 140), k) > 0
            e1 = cv2.dilate(cv2.Canny(c1, 60, 140), k) > 0
            union = int((e0 | e1).sum())
            iou = float((e0 & e1).sum()) / union if union else 1.0
            ok = ncc >= thr
            rec = {
                't0': round(float(t0), 2),
                't1': round(float(t1), 2),
                'ncc': round(ncc, 3),
                'edge_iou': round(iou, 3),
                'ok': bool(ok),
            }
            out['pairs'].append(rec)
            out['checks'].append(
                {
                    'check': f'prop_ncc:{rec["t0"]}s→{rec["t1"]}s',
                    **rec,
                    'note': ''
                    if ok
                    else f'prop NCC {ncc:.2f} < {thr} — prop MORPHED across this boundary (edge IoU {iou:.2f})',
                }
            )
            log(
                f'[qc_prop_consistency] {rec["t0"]}s→{rec["t1"]}s: ncc {ncc:.3f} '
                f'iou {iou:.3f} → {"PASS" if ok else "FAIL"}'
            )
        out['ok'] = all(p['ok'] for p in out['pairs']) if out['pairs'] else True
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = True  # fail-safe: broken QC never blocks generation
        log(f'[qc_prop_consistency] ERROR (fail-safe pass): {e}')
    _record_qc(out)
    return out
