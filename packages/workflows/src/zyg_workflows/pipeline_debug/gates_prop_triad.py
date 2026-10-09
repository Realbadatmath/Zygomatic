# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The three legs of `qc_prop_geometry`, one function each, plus the verdict roll-up.

Extracted from gates_prop.py so each leg can be read and unit-tested on its own: the
sampler that walks the decoded clip once (`sample_prop_series`), the absolute-geometry
leg (b) (`geometry_leg`), the thin-dark-structure leg (c) (`ridge_leg`), the
seam-to-seam scale leg (a) (`scale_leg`), and `record_verdict`, which decides the gate
from the legs that were measurable. The calibration, the constants and the primitives
all stay in gates_prop.py; nothing here changes what the gate decides.
"""

from dataclasses import dataclass, field
from typing import Any

from .gates_prop import (
    _PROP_MIN_BLOB_FRAC,
    _PROP_MIN_COVERAGE,
    _PROP_RIDGE_FLOOR,
    _PROP_SCALE_LOG_MAX,
    _prop_ridges,
    _prop_scale_pair,
    _prop_white_blob,
)
from .gates_v7 import _CONTEXT_STRIDE_FRAMES


@dataclass
class PropSamples:
    """One pass over the decoded clip, in decode order — the input of all three legs.

    `crops` are (t_seconds, bgr_crop) pairs of the prop box; `blobs` the white-clay
    segmentation of each crop (None where there is none); `series` the per-sample
    report rows; `areas`/`widths`/`rfrac`/`dfrac` the same measurements as float
    arrays, `heights`/`rcnt`/`rlen` as lists; `dur` the time of the last sample.
    """

    crops: list = field(default_factory=list)
    blobs: list = field(default_factory=list)
    series: list = field(default_factory=list)
    areas: Any = None
    widths: Any = None
    heights: list = field(default_factory=list)
    rcnt: list = field(default_factory=list)
    rfrac: Any = None
    rlen: list = field(default_factory=list)
    dfrac: Any = None
    dur: float = 0.0


def sample_prop_series(frames, ys, xs, scale):
    """Measure the prop box in every sampled frame exactly once → PropSamples.

    `frames` is the [(t_seconds, bgr_frame), ...] decode, `ys`/`xs` the box slices and
    `scale` the clip's width over the 832px render-native reference. Walks the frames
    in order, keeping only the crops (the full-res frames are the caller's to release),
    and records per sample: the white-clay blob's bbox and area, and the four ridge
    statistics. A frame with no blob contributes zeros, not a gap, because the series is
    read positionally against the sample times.
    """
    import numpy as np

    s = PropSamples()
    areas, widths, rfrac, dfrac = [], [], [], []
    for t, f in frames:
        c = f[ys, xs]
        s.crops.append((t, c))
        b = _prop_white_blob(c)
        s.blobs.append(b)
        areas.append(float(b[2]) if b else 0.0)
        widths.append(float(b[0]) if b else 0.0)
        s.heights.append(float(b[1]) if b else 0.0)
        cn, af, ml, df = _prop_ridges(c, scale)
        s.rcnt.append(cn)
        rfrac.append(af)
        s.rlen.append(ml)
        dfrac.append(df)
        s.series.append(
            {
                't': round(float(t), 2),
                'area': int(areas[-1]),
                'w': int(widths[-1]),
                'h': int(s.heights[-1]),
                'ridges': cn,
                'ridge_area_frac': round(af, 5),
                'ridge_len': int(ml),
                'dark_frac': round(df, 4),
            }
        )
    s.dur = float(frames[-1][0])
    s.areas = np.array(areas, float)
    s.widths = np.array(widths, float)
    s.rfrac = np.array(rfrac, float)
    s.dfrac = np.array(dfrac, float)
    return s


def geometry_leg(samples, box_area, clip_w, canon, tol, arr_max, reasons):
    """Leg (b) — absolute blob geometry across the whole clip → (geo, blob_floor).

    Fails when p95/p05 of the blob-area series exceeds `arr_max` (the prop changes
    size) or, with a `canon` (a bowl width in px, or a dict with 'bowl_w_px' and
    optionally 'ref_width' / 'tol'), when the median bbox width sits outside +-`tol`
    of the canon rescaled to this clip's width. Reports applicable=False with a reason
    — never a pass — when the box holds no white blob at `_PROP_MIN_COVERAGE` of the
    samples. The returned `blob_floor` is the minimum blob area a sample must show to
    count, which the scale leg reuses to reject occluded seam frames. Appends every
    failure and abstention to `reasons`.
    """
    import numpy as np

    areas, widths = samples.areas, samples.widths
    found = areas[areas > 0]
    med = float(np.median(found)) if len(found) else 0.0
    floor = max(_PROP_MIN_BLOB_FRAC * box_area, 0.35 * med)
    valid = areas >= floor
    cov = float(valid.mean())
    geo = {
        'applicable': False,
        'coverage': round(cov, 3),
        'n': int(valid.sum()),
        'box_area_px': int(box_area),
        'min_blob_px': int(floor),
        'ok': None,
    }
    if med >= _PROP_MIN_BLOB_FRAC * box_area and cov >= _PROP_MIN_COVERAGE:
        va = areas[valid]
        vw = widths[valid]
        p05, p50, p95 = (float(np.percentile(va, 5)), float(np.median(va)), float(np.percentile(va, 95)))
        p10, p90 = float(np.percentile(va, 10)), float(np.percentile(va, 90))
        geo.update(
            {
                'applicable': True,
                'area_p05': round(p05, 1),
                'area_p50': round(p50, 1),
                'area_p95': round(p95, 1),
                'area_ratio_p95_p05': round(p95 / max(p05, 1.0), 3),
                'area_ratio_p90_p10': round(p90 / max(p10, 1.0), 3),
                'bowl_w_p05': round(float(np.percentile(vw, 5)), 1),
                'bowl_w_med': round(float(np.median(vw)), 1),
                'bowl_w_p95': round(float(np.percentile(vw, 95)), 1),
                'area_ratio_max': arr_max,
            }
        )
        ok_b = geo['area_ratio_p95_p05'] <= arr_max
        if not ok_b:
            reasons.append(
                f'blob area p95/p05 {geo["area_ratio_p95_p05"]} > {arr_max} — prop '
                f'changes SIZE across the clip ({p05:.0f}->{p95:.0f} px2)'
            )
        ok_b = _canon_width_check(geo, canon, tol, clip_w, ok_b, reasons)
        geo['ok'] = bool(ok_b)
    else:
        reasons.append(
            f'geometry INAPPLICABLE: no white-clay blob in box (median blob '
            f'{med:.0f}px2, coverage {cov:.2f}) — verdict rests on scale + ridge'
        )
    return geo, floor


def _canon_width_check(geo, canon, tol, clip_w, ok_b, reasons):
    """The absolute-width half of leg (b): median bowl width vs the canon → ok_b.

    `canon` is None (nothing to check), a number (a bowl width in px measured at
    `clip_w`), or a dict {'bowl_w_px', 'ref_width', 'tol'}; `ref_width` rescales the
    canon to this clip's width so a canon measured on the 832px render still applies to
    a 1664px deliverable. Writes canon_bowl_w_px / canon_ratio / canon_tol into `geo`
    and returns `ok_b` unchanged unless the ratio leaves +-tol, in which case it
    returns False and appends the reason.
    """
    cw = None
    if isinstance(canon, dict):
        cw = canon.get('bowl_w_px')
        if cw is None:
            reasons.append("canon dict has no 'bowl_w_px' — absolute-width check skipped")
    elif canon is not None:
        cw = canon
    if cw is None:
        return ok_b
    cw = float(cw)
    ref_w = float(canon.get('ref_width', clip_w)) if isinstance(canon, dict) else clip_w
    if isinstance(canon, dict) and canon.get('tol') is not None:
        tol = float(canon['tol'])
    cw_scaled = cw * (clip_w / max(ref_w, 1.0))
    ratio = geo['bowl_w_med'] / max(cw_scaled, 1e-6)
    geo['canon_bowl_w_px'] = round(cw_scaled, 1)
    geo['canon_ratio'] = round(ratio, 3)
    geo['canon_tol'] = tol
    if abs(ratio - 1.0) > tol:
        reasons.append(
            f'bowl width {geo["bowl_w_med"]:.0f}px vs canon {cw_scaled:.0f}px = {ratio:.2f}x — outside +-{tol:.0%}'
        )
        return False
    return ok_b


def ridge_leg(samples, flick_max, reasons):
    """Leg (c) — thin dark structure, gated on its temporal flicker → the ridge dict.

    ridge_flicker = p90(|diff(ridge_area_frac)|) / max(median(ridge_area_frac), floor);
    i.e. how violently the thin-dark-structure content jumps between samples,
    normalised by its own level with `_PROP_RIDGE_FLOOR` as an absolute denominator
    floor so a prop with no dark detail cannot divide by ~0. Fails above `flick_max`
    and appends the reason. dark_frac percentiles ride along as evidence only.
    """
    import numpy as np

    rfrac, dfrac = samples.rfrac, samples.dfrac
    diffs = np.abs(np.diff(rfrac)) if len(rfrac) > 1 else np.array([0.0])
    denom = max(float(np.median(rfrac)), _PROP_RIDGE_FLOOR)
    flicker = float(np.percentile(diffs, 90)) / denom
    ridge = {
        'ridge_count_med': float(np.median(samples.rcnt)),
        'ridge_count_p90': round(float(np.percentile(samples.rcnt, 90)), 2),
        'ridge_area_frac_med': round(float(np.median(rfrac)), 5),
        'ridge_len_med': float(np.median(samples.rlen)),
        'ridge_flicker': round(flicker, 3),
        'ridge_flicker_max': flick_max,
        'dark_frac_p05': round(float(np.percentile(dfrac, 5)), 4),
        'dark_frac_med': round(float(np.median(dfrac)), 4),
        'dark_frac_p95': round(float(np.percentile(dfrac, 95)), 4),
        'dark_frac_swing': round(float(np.percentile(dfrac, 95) - np.percentile(dfrac, 5)), 4),
    }
    ridge['ok'] = bool(flicker <= flick_max)
    if not ridge['ok']:
        reasons.append(
            f'ridge_flicker {flicker:.2f} > {flick_max} — thin dark structure '
            f'(stem / ghost line) appears, thickens and vanishes between samples'
        )
    return ridge


def seam_pair_times(seam_times, dur, seam_stride, seam_fps):
    """The consecutive seam-time pairs leg (a) compares → [(t0, t1), ...].

    When `seam_times` is None the seams are derived from the RENDER-native recipe
    (context 81 - overlap 24 = 57 frames at `seam_fps`), in SECONDS, not from the
    decoded clip's frame numbering: the deliverable is retimed, so frame 57 of the mp4
    is not a seam. Capped at 512 seams and at the clip's own duration `dur`.
    """
    stride = max(1, int(seam_stride) if seam_stride else _CONTEXT_STRIDE_FRAMES)
    sfps = max(1e-3, float(seam_fps))
    if seam_times is None:
        seam_times = []
        k = 0
        while k * stride / sfps <= dur + 1e-6 and k < 512:
            seam_times.append(k * stride / sfps)
            k += 1
    return [(seam_times[i], seam_times[i + 1]) for i in range(len(seam_times) - 1)]


def scale_leg(samples, scale, blob_floor, pairs, reasons):
    """Leg (a) — the 4-DOF similarity scale between seam crops → the scale dict.

    For each (t0, t1) of `pairs` the nearest sampled crops are fitted by
    `_prop_scale_pair`, masked to the prop blob. A pair passes when |log s| is within
    `_PROP_SCALE_LOG_MAX`. When the feature fit abstains (low-texture white clay) the
    1-DOF blob-area fallback sqrt(area_t1/area_t0) is gated on the same bound, but only
    when BOTH seam frames show a blob of at least `blob_floor` px — a hand crossing the
    prop is an occlusion, not a rescale. A pair that cannot be measured either way is
    reported with ok=None and never counts as a pass; the leg's own 'ok' is False on
    any failing pair, True when something was measured, None when nothing was.
    """
    import math

    import numpy as np

    sc = {'pairs': [], 'measured': 0, 'method': '', 'ok': None, 'log_max': _PROP_SCALE_LOG_MAX}
    ts = np.array([t for t, _ in samples.crops], float)
    any_fail = False
    for t0, t1 in pairs:
        i0 = int(np.argmin(np.abs(ts - t0)))
        i1 = int(np.argmin(np.abs(ts - t1)))
        b0, b1 = samples.blobs[i0], samples.blobs[i1]
        st, s, ir, ni, nm, meth = _prop_scale_pair(
            samples.crops[i0][1], samples.crops[i1][1], b0[3] if b0 else None, b1[3] if b1 else None, scale
        )
        if meth:
            sc['method'] = meth
        rec = {
            't0': round(float(ts[i0]), 2),
            't1': round(float(ts[i1]), 2),
            'status': st,
            's': round(s, 4) if s else None,
            'inlier_ratio': round(ir, 2),
            'inliers': ni,
            'matches': nm,
        }
        if b0 and b1 and b0[2] >= blob_floor and b1[2] >= blob_floor:
            bs = float(np.sqrt(b1[2] / float(b0[2])))
            rec['blob_scale'] = round(bs, 3)
        if st == 'ok' and s and s > 0:
            rec['log_s'] = round(float(np.log(s)), 4)
            rec['ok'] = abs(rec['log_s']) <= _PROP_SCALE_LOG_MAX
            sc['measured'] += 1
        elif 'blob_scale' in rec and rec['blob_scale'] > 0:
            rec['log_s'] = round(float(np.log(rec['blob_scale'])), 4)
            rec['ok'] = abs(rec['log_s']) <= _PROP_SCALE_LOG_MAX
            rec['status'] = st + '->blob_scale'
            sc['measured'] += 1
        else:
            rec['ok'] = None  # unmeasured: never counts as a pass
        if rec['ok'] is False:
            any_fail = True
            src = (
                '4-DOF fit'
                if rec['status'] == 'ok'
                else f'blob-area fallback, feature fit {rec["status"].split("->")[0]}'
            )
            reasons.append(
                f'scale {rec["t0"]}s->{rec["t1"]}s: s={math.exp(rec["log_s"]):.3f} '
                f'({src}) — |log s| {abs(rec["log_s"]):.3f} > '
                f'{_PROP_SCALE_LOG_MAX:.3f}'
            )
        sc['pairs'].append(rec)
    if sc['pairs'] and sc['measured'] == 0:
        reasons.append(
            'scale UNMEASURED on every seam pair (low-texture prop / no blob) — '
            'not a pass; verdict rests on geometry + ridge'
        )
    sc['ok'] = False if any_fail else (True if sc['measured'] else None)
    return sc


def record_verdict(out, geo, ridge, sc):
    """Decide the gate from the measurable legs and write out['ok'] and out['checks'].

    ALL measurable legs must pass and at least one must exist; no measurable leg at all
    is fail-closed. DebugRun.finish() counts any check whose 'ok' is falsy as a FAILED
    check, so a leg that abstained (ok=None) must NOT appear as a check — it would read
    as a failure the gate itself did not declare. Abstentions live in out['reasons'] and
    in the per-leg dicts; only measured legs are recorded, plus one boolean roll-up.
    """
    legs = []
    if geo['ok'] is not None:
        legs.append(bool(geo['ok']))
    if ridge['ok'] is not None:
        legs.append(bool(ridge['ok']))
    if sc['ok'] is not None:
        legs.append(bool(sc['ok']))
    if not legs:
        out['ok'] = False
        out['reasons'].append('no leg of the triad was measurable — fail-closed')
    else:
        out['ok'] = all(legs)
    out['checks'] = [
        {
            'check': 'prop_triad',
            'ok': bool(out['ok']),
            'ridge_flicker': ridge['ridge_flicker'],
            'legs_measured': len(legs),
            'note': '; '.join(out['reasons'])[:400],
        }
    ]
    if sc['ok'] is not None:
        out['checks'].append(
            {
                'check': 'prop_scale',
                'ok': bool(sc['ok']),
                'measured': sc['measured'],
                'pairs': len(sc['pairs']),
                'method': sc['method'],
                'note': '' if sc['ok'] else '; '.join(r for r in out['reasons'] if r.startswith('scale ')),
            }
        )
    if geo['ok'] is not None:
        out['checks'].append(
            {
                'check': 'prop_geometry',
                'ok': bool(geo['ok']),
                'area_ratio_p95_p05': geo.get('area_ratio_p95_p05'),
                'bowl_w_med': geo.get('bowl_w_med'),
                'canon_ratio': geo.get('canon_ratio'),
                'note': '' if geo['ok'] else 'blob area / bowl width drift',
            }
        )
    out['checks'].append(
        {
            'check': 'prop_ridge',
            'ok': bool(ridge['ok']),
            'ridge_flicker': ridge['ridge_flicker'],
            'ridge_count_p90': ridge['ridge_count_p90'],
            'note': '' if ridge['ok'] else 'thin dark structure unstable',
        }
    )
    return out
