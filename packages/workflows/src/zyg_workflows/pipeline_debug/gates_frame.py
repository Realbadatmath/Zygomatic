# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v8b forensic gates, part 2: qc_frame_border (letterbox/pillarbox persistence)
and qc_fx_grain (noise, flicker and saturation ratios)."""

import os
from .gates_prop import (
    _BORDER_EXCESS_MIN,
    _BORDER_INSET_PX,
    _BORDER_PERSIST_MIN,
    _BORDER_RATIO_MIN,
    _FX_FLICKER_RATIO_MAX,
    _FX_NOISE_RATIO_HI,
    _FX_NOISE_RATIO_LO,
    _FX_SAT_RATIO_MIN,
)
from .gates_v7 import _record_qc


def qc_frame_border(
    clip_path,
    band_px=4,
    ref_image=None,
    inset_px=None,
    sample_every=4,
    seam_ratio_min=None,
    persist_min=None,
    log_fn=None,
    fail_open=True,
):
    """Frame-edge seam gate (2026-07-31, scene20_v8b right-edge artifact).

    v8b carries a hard vertical seam ~30 render-native px in from the RIGHT edge, running
    the full height of the frame: the VACE mask's feather ramp reaches the frame border
    (mask_v8.png's right columns decay 225->84 over the last ~30px), so everything beyond
    that column is composited differently from the rest of the plate. Nothing in the QC
    battery looked at the frame edge at all.

    METHOD. Per sampled frame, in CIELab: column-mean and row-mean profiles, first
    difference, L1 across channels, normalised by that frame's own median step. A seam is
    an index inside the border band whose median normalised step is large AND persists
    across frames. band_px (hard zone, the literal outermost pixels — a mask ramp that
    runs off the edge) and inset_px (default 40) are given in 832-native px and are scaled
    to the clip's actual width, because the deliverable is 2x upscaled.

    ref_image (STRONGLY RECOMMENDED — the anchor still, e.g. anchor_480.png): the same
    profile is computed on the reference and SUBTRACTED, so real scene edges that happen
    to sit near the frame border cancel out and only generated seams survive. Clip frames
    are downscaled to the reference's resolution for this comparison; upscaling the
    reference instead smears its own edges and produces false positives. Measured on
    FINAL_scene20_v8b.mp4 against anchor_480.png:
        right  x=800 (30px in): clip 10.28, ref 0.90, EXCESS 9.38, persistence 0.97 -> FAIL
        bottom y=453 (25px in): clip  5.16, ref 0.50, excess 4.66, persistence 0.78 -> pass
        left / top: excess 0.73 -> pass
    Without ref_image the gate still runs (threshold _BORDER_RATIO_MIN=8.0) but is a
    SCREENING check: on this clip the un-referenced statistic scores the table's front
    edge at 7.11, i.e. content edges near the border are a known false-positive class.

    Advisory: fail-open on internal error (pass fail_open=False to invert)."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'frame_border:{os.path.basename(clip_path)}',
        'kind': 'frame_border',
        'path': clip_path,
        'ok': True,
        'edges': {},
        'reasons': [],
        'checks': [],
        'mode': 'screening',
        'threshold': _BORDER_RATIO_MIN,
    }
    try:
        import cv2
        import numpy as np

        inset = int(inset_px) if inset_px is not None else _BORDER_INSET_PX
        persist_thr = float(persist_min) if persist_min is not None else _BORDER_PERSIST_MIN

        ref = None
        if ref_image:
            ref = cv2.imread(ref_image) if isinstance(ref_image, str) else ref_image
            if ref is None:
                out['reasons'].append(f'ref_image unreadable: {ref_image}')
        thr = (
            float(seam_ratio_min)
            if seam_ratio_min is not None
            else (_BORDER_EXCESS_MIN if ref is not None else _BORDER_RATIO_MIN)
        )
        out['mode'] = 'ref-differenced' if ref is not None else 'screening'
        out['threshold'] = thr

        cap = cv2.VideoCapture(clip_path)
        cols, rows = [], []
        i = 0
        tgt = (ref.shape[1], ref.shape[0]) if ref is not None else None
        while True:
            ok, f = cap.read()
            if not ok:
                break
            if i % max(1, int(sample_every)) == 0:
                if tgt and (f.shape[1], f.shape[0]) != tgt:
                    f = cv2.resize(f, tgt, interpolation=cv2.INTER_AREA)
                lab = cv2.cvtColor(f, cv2.COLOR_BGR2LAB).astype(np.float32)
                dc = np.abs(np.diff(lab.mean(axis=0), axis=0)).sum(axis=1)
                dr = np.abs(np.diff(lab.mean(axis=1), axis=0)).sum(axis=1)
                cols.append(dc / max(float(np.median(dc)), 0.1))
                rows.append(dr / max(float(np.median(dr)), 0.1))
            i += 1
        cap.release()
        if len(cols) < 3:
            out['reasons'].append(f'only {len(cols)} sampled frames')
            _record_qc(out)
            return out
        cols = np.stack(cols)
        rows = np.stack(rows)
        W = cols.shape[1] + 1
        scale = W / 832.0
        band = max(1, int(round(band_px * scale)))
        zone = max(band, int(round(inset * scale)))

        rc = np.zeros(cols.shape[1], np.float32)
        rr = np.zeros(rows.shape[1], np.float32)
        if ref is not None:
            rlab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
            d = np.abs(np.diff(rlab.mean(axis=0), axis=0)).sum(axis=1)
            rc = d / max(float(np.median(d)), 0.1)
            d = np.abs(np.diff(rlab.mean(axis=1), axis=0)).sum(axis=1)
            rr = d / max(float(np.median(d)), 0.1)

        for label, prof, refprof, far in (
            ('left', cols, rc, 0),
            ('right', cols, rc, 1),
            ('top', rows, rr, 0),
            ('bottom', rows, rr, 1),
        ):
            n = prof.shape[1]
            lo, hi = (0, min(zone, n)) if far == 0 else (max(0, n - zone), n)
            med = np.median(prof[:, lo:hi], axis=0) - refprof[lo:hi]
            k = int(np.argmax(med))
            idx = lo + k
            score = float(med[k])
            pers = float((prof[:, idx] - refprof[idx] >= max(3.0, 0.5 * thr)).mean())
            dist = int(min(idx, n - 1 - idx))
            # 'score' first: DebugRun._check_score trends the first numeric field it
            # finds, and the seam score is the one worth a 14-day trend line.
            rec = {
                'score': round(score, 2),
                'persistence': round(pers, 2),
                'index': idx,
                'dist_from_edge_px': dist,
                'dist_native_px': round(dist / scale, 1),
                'clip_ratio': round(float(np.median(prof[:, idx])), 2),
                'ref_ratio': round(float(refprof[idx]), 2),
                'in_hard_band': bool(dist < band),
            }
            rec['ok'] = not (score >= thr and pers >= persist_thr)
            out['edges'][label] = rec
            if not rec['ok']:
                out['reasons'].append(
                    f'{label} edge: persistent seam at index {idx} '
                    f'({rec["dist_native_px"]} native px from the edge), step score '
                    f'{score:.2f} >= {thr} on {pers:.0%} of frames'
                )
            out['checks'].append({'check': f'frame_border:{label}', **rec, 'note': '' if rec['ok'] else 'border seam'})
            log(
                f'[qc_frame_border] {label}: idx {idx} ({rec["dist_native_px"]} native px '
                f'in) score {score:.2f} persist {pers:.2f} -> '
                f'{"PASS" if rec["ok"] else "FAIL"}'
            )
        out['ok'] = all(r['ok'] for r in out['edges'].values())
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_frame_border] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out


def qc_fx_grain(
    clip_path,
    t0,
    t1,
    box_frac=None,
    sample_every=2,
    guard_s=0.5,
    noise_lo=None,
    noise_hi=None,
    flicker_max=None,
    sat_min=None,
    log_fn=None,
    fail_open=True,
):
    """FX-window composite-integrity gate (2026-07-31, scene20_v8b smoke takeover).

    From ~17s v8b's smoke FX stops being an overlay and becomes the image: the last three
    seconds are a flat grey wash in which the candle, the pipe and the ledger all vanish.
    No gate covered the FX window, and the whole-clip averages the other gates use hide it.

    Compares the window [t0, t1] against the BODY of the clip (everything outside the
    window plus a guard_s margin), on three statistics:
      noise    — Immerkaer high-frequency sigma (|I * [[1,-2,1],[-2,4,-2],[1,-2,1]]|),
                 the standard fast estimator. Gated TWO-SIDED: a grain/dither composite
                 pushes it up, a smooth haze composite pushes it down. Both mean the FX
                 window does not match the body of the clip.
      flicker  — median frame-to-frame mean |delta| within each set: a composite that
                 boils or strobes rises here even when its spatial noise falls.
      sat      — median HSV saturation ratio: colour collapse is the single most
                 unambiguous signature of a haze/smoke takeover.

    box_frac optionally scopes all three to a region. Measured on FINAL_scene20_v8b.mp4
    over 17.0-20.0s: noise 0.409 vs 0.528 = 0.78x (SMOOTHER, not grainier), flicker 2.706
    vs 0.577 = 4.69x, saturation 18 vs 219 = 0.08x -> FAIL on flicker and saturation.

    Advisory: fail-open on internal error (pass fail_open=False to invert)."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'fx_grain:{os.path.basename(clip_path)}',
        'kind': 'fx_grain',
        'path': clip_path,
        'window': [float(t0), float(t1)],
        'ok': True,
        'reasons': [],
        'checks': [],
    }
    try:
        import math
        import cv2
        import numpy as np

        lo_n = float(noise_lo) if noise_lo is not None else _FX_NOISE_RATIO_LO
        hi_n = float(noise_hi) if noise_hi is not None else _FX_NOISE_RATIO_HI
        fl_max = float(flicker_max) if flicker_max is not None else _FX_FLICKER_RATIO_MAX
        st_min = float(sat_min) if sat_min is not None else _FX_SAT_RATIO_MIN
        kern = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)

        cap = cv2.VideoCapture(clip_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 17.0
        win_n, win_f, win_s, bod_n, bod_f, bod_s = [], [], [], [], [], []
        prev = None
        i = 0
        while True:
            ok, f = cap.read()
            if not ok:
                break
            if i % max(1, int(sample_every)) == 0:
                t = i / fps
                if box_frac:
                    Hh, Ww = f.shape[:2]
                    f = f[int(Hh * box_frac[1]) : int(Hh * box_frac[3]), int(Ww * box_frac[0]) : int(Ww * box_frac[2])]
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
                h, w = g.shape
                sig = (
                    float(np.abs(cv2.filter2D(g, -1, kern)[1:-1, 1:-1]).sum())
                    * math.sqrt(math.pi / 2)
                    / (6.0 * max(1, (w - 2)) * max(1, (h - 2)))
                )
                sat = float(np.median(cv2.cvtColor(f, cv2.COLOR_BGR2HSV)[..., 1]))
                fl = float(np.abs(g - prev).mean()) if prev is not None else None
                prev = g
                inside = t0 <= t <= t1
                outside = (t < t0 - guard_s) or (t > t1 + guard_s)
                if inside:
                    win_n.append(sig)
                    win_s.append(sat)
                    if fl is not None:
                        win_f.append(fl)
                elif outside:
                    bod_n.append(sig)
                    bod_s.append(sat)
                    if fl is not None:
                        bod_f.append(fl)
            i += 1
        cap.release()
        if len(win_n) < 3 or len(bod_n) < 3:
            out['reasons'].append(f'not enough samples (window {len(win_n)}, body {len(bod_n)})')
            _record_qc(out)
            return out

        def _r(a, b):
            if not len(a) or not len(b):
                return None  # unmeasurable → the check is dropped, never faked
            return float(np.median(a)) / max(float(np.median(b)), 1e-6)

        nr, fr, sr = _r(win_n, bod_n), _r(win_f, bod_f), _r(win_s, bod_s)
        if nr is None or sr is None:
            out['reasons'].append('window/body sample sets empty — nothing to compare')
            _record_qc(out)
            return out
        out.update(
            {
                'n_window': len(win_n),
                'n_body': len(bod_n),
                'noise_window': round(float(np.median(win_n)), 3),
                'noise_body': round(float(np.median(bod_n)), 3),
                'noise_ratio': round(nr, 3),
                'sat_window': round(float(np.median(win_s)), 1),
                'sat_body': round(float(np.median(bod_s)), 1),
                'sat_ratio': round(sr, 3),
                'bounds': {'noise': [lo_n, hi_n], 'flicker_max': fl_max, 'sat_min': st_min},
            }
        )
        checks = []
        if not (lo_n <= nr <= hi_n):
            out['reasons'].append(
                f'HF noise ratio {nr:.2f} outside [{lo_n}, {hi_n}] — the FX window '
                f'{"is grainier than" if nr > hi_n else "is smoother/washed out vs"} '
                f'the body of the clip'
            )
        checks.append({'check': 'fx_noise', 'ok': bool(lo_n <= nr <= hi_n), 'ratio': round(nr, 3)})
        if fr is not None:
            out.update(
                {
                    'flicker_window': round(float(np.median(win_f)), 3),
                    'flicker_body': round(float(np.median(bod_f)), 3),
                    'flicker_ratio': round(fr, 3),
                }
            )
            if fr > fl_max:
                out['reasons'].append(
                    f'frame-to-frame flicker {fr:.2f}x the body (> {fl_max}) — composite boils/strobes'
                )
            checks.append({'check': 'fx_flicker', 'ok': bool(fr <= fl_max), 'ratio': round(fr, 3)})
        if sr < st_min:
            out['reasons'].append(
                f'saturation collapses to {sr:.2f}x the body (< {st_min}) — haze/smoke '
                f'has taken over the image, not overlaid it'
            )
        checks.append({'check': 'fx_saturation', 'ok': bool(sr >= st_min), 'ratio': round(sr, 3)})
        out['checks'] = checks
        out['ok'] = all(c['ok'] for c in checks)
        log(
            f'[qc_fx_grain] {t0}-{t1}s: noise {nr:.2f}x '
            f'flicker {"n/a" if fr is None else format(fr, ".2f") + "x"} '
            f'sat {sr:.2f}x -> {"PASS" if out["ok"] else "FAIL"}'
        )
        for r in out['reasons']:
            log(f'[qc_fx_grain]   reason: {r}')
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_fx_grain] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out
