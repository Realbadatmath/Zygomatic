# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `ridge_relief`: distances, per-station measurement, run structure, verdict.

Extracted from primitive.py so each stage can be read and unit-tested on its own.
`RidgeProbe` carries what every station measurement needs and does not change between
stations; `station_rows` walks the curve once (in `point` mode exactly regions.py's
isotropic probe, in `ridge` mode the anisotropic collar with the widening loop);
`profile_summary` turns the station records into the run structure the verdict rests on;
`classify` names the verdict and its measured null; `build_result` assembles the profile
the caller reads. Nothing here changes what is measured or decided — the stages are the
sections of the old single function, in the same order.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    RIDGE_ALONG_WIDENING,
    RIDGE_MIN_STATIONS,
    VERDICT_CLASS,
    _VERDICT_MEANING,
    resolves_relief,
)
from zyg_workflows.geom.form.ridge.primitive import (
    _group_distance,
    _score_profile,
    _station_distances,
    polyline_arc_length,
)


@dataclass
class RidgeProbe:
    """What a station measurement needs and what does not change between stations.

    `st` is the polyline in curve order, `S` the stature in metres, `areas`/`normals`
    the per-vertex mixed-Voronoi areas and normals, `graph` the cached CSR edge graph.
    `d_curve` and `owner` are the min and argmin over the station distance rows — the
    distance to the whole curve and which station owns each vertex — and only `ridge`
    mode reads them. The rest are the geometry and threshold arguments of the primitive.
    """

    v: Any
    faces: Any
    st: list
    S: float
    areas: Any
    normals: Any
    graph: Any
    mode: str
    polarity: str
    core_frac: float
    gap_frac: float
    width_frac: float
    along_stations: int
    max_tilt_deg: float
    min_frac_stature: float
    min_contrast: float
    point_radius_frac: float
    point_cache: Any = None
    d_curve: Any = None
    owner: Any = None


@dataclass
class Profile:
    """The run structure of a measured profile — the evidence the verdict rests on.

    `ok` marks the measured stations, `rel`/`con` their relief (as a fraction of
    stature) and contrast with NaN where unmeasurable, `qual` the stations that clear
    both cuts. `run_*` describe the longest CONSECUTIVE, QUALIFYING, SAME-SIGN run;
    `any_len` the longest any-sign one. `arc` is the polyline's own length in metres and
    `run_span` the arc length the run covers.
    """

    ok: Any
    rel: Any
    con: Any
    qual: Any
    sgn: Any
    meas: Any
    run_len: int
    run_sign: int
    run_lo: int
    run_hi: int
    any_len: int
    sign_changes: int
    sign_changes_q: int
    arc: float
    run_span: float
    peak: int
    absrel: Any
    run_rows: list = field(default_factory=list)
    run_min_abs_relief_mm: Any = None
    run_min_abs_contrast: Any = None


def validate_polyline(v, polyline, polarity, stature_m):
    """Check the primitive's arguments and return (v, stations, stature_m).

    A polyline needs at least 2 DISTINCT in-range vertices: a repeated vertex makes the
    arc coordinate non-monotone, and "consecutive stations" — the thing a run is defined
    on — then means nothing. The stature defaults to the mesh's own z extent.
    """
    v = np.asarray(v, np.float64)
    st = [int(i) for i in np.asarray(polyline).ravel()]
    if len(st) < 2:
        raise ValueError('a polyline needs at least 2 stations, got %d' % len(st))
    if len(set(st)) != len(st):
        raise ValueError(
            'polyline repeats a vertex; the arc coordinate is then not monotone and "consecutive stations" is undefined'
        )
    if min(st) < 0 or max(st) >= len(v):
        raise ValueError('polyline indexes vertices outside the mesh (0..%d)' % (len(v) - 1))
    if polarity not in ('protrusion', 'depression', 'either'):
        raise ValueError('polarity must be protrusion|depression|either, got %r' % polarity)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    if S <= 0:
        raise ValueError('stature must be positive, got %r' % (S,))
    return v, st, S


def curve_distances(v, faces, st, S, graph, distances, gap_frac, width_frac):
    """The (N, V) station distance rows, truncated when that is safe → (D, hops).

    The limit is far enough to hold the widest collar the widening loop can ask for plus
    room for the inter-station hops the arc length is summed from; when the truncation
    loses a hop the search is re-run unlimited. A non-finite hop in the UNtruncated rows
    is not a truncation artefact but two different connected surfaces (a head window
    drawn in fractions of stature picks up eyeball vertices), so the arc coordinate the
    run structure is defined on does not exist and that is a ValueError.
    """
    if distances is None:
        step = float(np.linalg.norm(v[st[1:]] - v[st[:-1]], axis=1).max())
        lim = max((gap_frac + 4.0 * width_frac) * S, 3.0 * step)
        D = _station_distances(v, faces, st, graph, limit=lim)
        hops = np.array([D[k, st[k + 1]] for k in range(len(st) - 1)])
        if not np.isfinite(hops).all():
            D = _station_distances(v, faces, st, graph)  # truncation lost a hop
    else:
        D = np.asarray(distances)
    if D.shape != (len(st), len(v)):
        raise ValueError('distance rows are %s, expected %s' % ((D.shape,), ((len(st), len(v)),)))
    hops = np.array([D[k, st[k + 1]] for k in range(len(st) - 1)])
    if not np.isfinite(hops).all():
        j = int(np.argmax(~np.isfinite(hops)))
        raise ValueError(
            'polyline is not connected on this surface: stations %d (vertex %d) and %d '
            '(vertex %d) lie in different connected components, so the arc coordinate the '
            'run structure is defined on does not exist' % (j, st[j], j + 1, st[j + 1])
        )
    return D, hops


def _blank_row(k, s, v, S):
    """The per-station record before anything is measured: unmeasurable, nothing known."""
    return {
        'i': k,
        'vertex': int(s),
        'frac_stature': float((v[s, 2] - v[:, 2].min()) / S),
        'status': 'unmeasurable',
        'why': None,
        'relief_mm': None,
        'relief_frac_stature': None,
        'contrast': None,
        'collar_fit_rms_mm': None,
        'n_group': None,
        'n_collar': None,
        'along_stations_used': None,
    }


def _point_probe(p, s):
    """regions.py's isotropic probe at one vertex → {'ok': True, ...} or {'ok': False, 'why'}.

    A geodesic ball of `point_radius_frac` of stature around the vertex against the
    default collar. Memoised on (vertex, radius) in `p.point_cache` when there is one,
    because the candidate sweep re-visits the same station dozens of times and the probe
    depends on nothing else — measured, that is the difference between 26 s and 1.7 s for
    one 300-vertex pool.
    """
    key = (int(s), float(p.point_radius_frac))
    hit = p.point_cache.get(key) if p.point_cache is not None else None
    if hit is not None:
        return hit
    try:
        d0 = _group_distance(p.v, p.faces, [s], p.graph, limit=p.point_radius_frac * p.S * 1.001)
        grp = np.nonzero(d0 <= p.point_radius_frac * p.S)[0]
        if grp.size == 0:
            raise ValueError('geodesic ball of %.4f stature around vertex %d is empty' % (p.point_radius_frac, s))
        dg = _group_distance(p.v, p.faces, grp, p.graph, limit=(CV.COLLAR_GAP_FRAC + 4.0 * CV.COLLAR_WIDTH_FRAC) * p.S)
        r = CV.region_relief(
            p.v,
            p.faces,
            grp,
            stature_m=p.S,
            areas=p.areas,
            normals=p.normals,
            max_tilt_deg=p.max_tilt_deg,
            distances=dg,
            min_frac_stature=p.min_frac_stature,
            min_contrast=p.min_contrast,
        )
        hit = {
            'ok': True,
            'relief_mm': r['relief_mm'],
            'relief_frac_stature': r['relief_frac_stature'],
            'contrast': r['contrast'],
            'collar_fit_rms_mm': r['collar_fit_rms_mm'],
            'n_group': r['n_group'],
            'n_collar': r['n_collar'],
        }
    except ValueError as e:
        hit = {'ok': False, 'why': str(e)}
    if p.point_cache is not None:
        p.point_cache[key] = hit
    return hit


def _measure_point_station(p, s, rec):
    """Fill `rec` from the memoised isotropic point probe at vertex `s`."""
    hit = _point_probe(p, s)
    if hit['ok']:
        rec.update(
            status='ok',
            **{
                k: hit[k]
                for k in ('relief_mm', 'relief_frac_stature', 'contrast', 'collar_fit_rms_mm', 'n_group', 'n_collar')
            },
        )
    else:
        rec['why'] = hit['why']


def _measure_ridge_station(p, k, s, rec):
    """Fill `rec` from the anisotropic collar of station `k`, widening until it resolves.

    The crest is this station's own share of the curve core (`owner == k` within
    `core_frac` of stature); an empty crest falls back to the station vertex itself. The
    collar is restricted to an arc band of +-m stations and m grows through
    RIDGE_ALONG_WIDENING until region_relief accepts the band; the last refusal is kept
    as the station's 'why' if none of them does.
    """
    crest = np.nonzero((p.d_curve <= p.core_frac * p.S) & (p.owner == k))[0]
    if crest.size == 0:
        crest = np.array([s], np.int64)
    last = None
    for m in [p.along_stations] + [x for x in RIDGE_ALONG_WIDENING if x > p.along_stations]:
        band = np.where(np.abs(p.owner - k) <= m, p.d_curve, np.inf)
        try:
            r = CV.region_relief(
                p.v,
                p.faces,
                crest,
                gap_frac=p.gap_frac,
                width_frac=p.width_frac,
                max_tilt_deg=p.max_tilt_deg,
                stature_m=p.S,
                areas=p.areas,
                normals=p.normals,
                distances=band,
                min_frac_stature=p.min_frac_stature,
                min_contrast=p.min_contrast,
            )
        except ValueError as e:
            last = str(e)
            continue
        rec.update(
            status='ok',
            relief_mm=r['relief_mm'],
            relief_frac_stature=r['relief_frac_stature'],
            contrast=r['contrast'],
            collar_fit_rms_mm=r['collar_fit_rms_mm'],
            n_group=r['n_group'],
            n_collar=r['n_collar'],
            along_stations_used=int(m),
        )
        return
    rec['why'] = last


def station_rows(p):
    """Measure every station of the curve, in curve order → one record each.

    `point` mode is EXACTLY regions.py's probe — an isotropic geodesic ball, which is
    both the rollback and the before/after control; `ridge` mode is the anisotropic
    collar. A station that cannot be measured is kept in place with status
    'unmeasurable' and a 'why', because a run may not be claimed across a hole.
    """
    rows = []
    for k, s in enumerate(p.st):
        rec = _blank_row(k, s, p.v, p.S)
        if p.mode == 'point':
            _measure_point_station(p, s, rec)
        else:
            _measure_ridge_station(p, k, s, rec)
        rows.append(rec)
    return rows


def profile_summary(rows, D, st, S, polarity, min_frac_stature, min_contrast):
    """Run structure and arc geometry of the measured stations → a Profile.

    `sign_changes` counts over all measured stations and `sign_changes_qualifying` over
    the qualifying ones only. `run_stations` are the stations that actually carry the
    claim: peak_* is an argmax over |relief| and is NOT necessarily one of them —
    measured on the male zygomatic arch, the strongest station reads contrast 3.16 while
    every station of the qualifying run is above the 4.16 cut. Reporting only the peak
    would understate the evidence and, on another body, could overstate it; the run's own
    weakest station is the number the verdict rests on.
    """
    ok = np.array([r['status'] == 'ok' for r in rows])
    rel = np.array([r['relief_frac_stature'] if r['status'] == 'ok' else np.nan for r in rows])
    con = np.array([r['contrast'] if r['status'] == 'ok' else np.nan for r in rows])

    qual, sgn, run_len, run_sign, run_lo, run_hi, any_len = _score_profile(
        rel, con, ok, polarity, min_frac_stature, min_contrast
    )
    meas = np.nonzero(ok)[0]
    s_meas = sgn[meas]
    sign_changes = int((s_meas[1:] * s_meas[:-1] < 0).sum()) if len(s_meas) > 1 else 0
    q_idx = np.nonzero(qual)[0]
    s_q = sgn[q_idx]
    sign_changes_q = int((s_q[1:] * s_q[:-1] < 0).sum()) if len(s_q) > 1 else 0

    arc = polyline_arc_length(D, st)
    run_span = 0.0
    if run_len >= 2:
        run_span = float(sum(D[j, st[j + 1]] for j in range(run_lo, run_hi)))
    run_rows = (
        [
            {'i': j, 'vertex': int(st[j]), 'relief_mm': float(rel[j] * S * 1000.0), 'contrast': float(con[j])}
            for j in range(run_lo, run_hi + 1)
        ]
        if run_len
        else []
    )
    return Profile(
        ok=ok,
        rel=rel,
        con=con,
        qual=qual,
        sgn=sgn,
        meas=meas,
        run_len=run_len,
        run_sign=run_sign,
        run_lo=run_lo,
        run_hi=run_hi,
        any_len=any_len,
        sign_changes=sign_changes,
        sign_changes_q=sign_changes_q,
        arc=arc,
        run_span=run_span,
        peak=int(meas[np.argmax(np.abs(np.nan_to_num(rel[meas])))]) if len(meas) else -1,
        absrel=np.abs(rel[ok]) if ok.any() else np.array([np.nan, np.nan]),
        run_rows=run_rows,
        run_min_abs_relief_mm=min((abs(r['relief_mm']) for r in run_rows), default=None),
        run_min_abs_contrast=min((abs(r['contrast']) for r in run_rows), default=None),
    )


def classify(prof, nulls, min_run, min_run_any):
    """Name the verdict, its class and the measured null rate → (verdict, class, rate).

    'point_only' means stations qualified but never `min_run` of them in a row: a point
    probe would have found this too, so the curve primitive adds nothing there and no
    whole-bone claim may be made from it. Fewer than RIDGE_MIN_STATIONS measured stations
    is 'unmeasurable' however the few that were measured read. `nulls` is this mode's
    RIDGE_NULL_P99 entry, so the false-positive rate of the verdict's class travels
    beside the verdict and a reader never has to go and look it up.
    """
    if not prof.ok.any():
        verdict = 'unmeasurable'
    elif int(prof.ok.sum()) < RIDGE_MIN_STATIONS:
        verdict = 'unmeasurable'
    elif prof.run_len >= min_run:
        verdict = 'ridge' if prof.run_sign > 0 else 'furrow'
    elif prof.any_len >= min_run_any:
        verdict = 'mixed_strip'
    elif prof.qual.any():
        verdict = 'point_only'
    else:
        verdict = 'flat'
    vclass = VERDICT_CLASS[verdict]
    null_rate = (
        nulls.get('null_rate_resolved')
        if vclass == 'resolved'
        else nulls.get('null_rate_point_only_or_better')
        if verdict == 'point_only'
        else None
    )
    return verdict, vclass, null_rate


def build_result(p, rows, prof, hops, verdict, vclass, null_rate, min_run, min_run_any):
    """The profile the caller reads — never a patch mean.

    THE FIELD TO READ is `resolves_relief`: a consumer does not re-list verdict names,
    because 'point_only' is INSIDE the measured null and a consumer that lists names for
    itself is one typo away from counting the null as a result. `peak_vertex` carries the
    VERTEX the peak sits on, not just its index along this curve: two probe windows that
    overlap can peak on the same vertex — one bump credited twice — and without that
    field the collision is undetectable downstream (see pool_overlaps()).
    """
    peak, rel, con, S = prof.peak, prof.rel, prof.con, p.S
    return {
        'mode': p.mode,
        'polarity': p.polarity,
        'stature_m': S,
        'n_stations': len(rows),
        'n_measured': int(prof.ok.sum()),
        'n_unmeasurable': int((~prof.ok).sum()),
        'n_qualifying': int(prof.qual.sum()),
        'stations': rows,
        'arc_length_m': prof.arc,
        'arc_length_frac_stature': prof.arc / S,
        'hops_m': [float(x) for x in hops],
        'continuity': float(prof.qual.sum()) / float(max(int(prof.ok.sum()), 1)),
        'longest_run': int(prof.run_len),
        'longest_run_any_sign': int(prof.any_len),
        'run_sign': int(prof.run_sign),
        'run_span_m': prof.run_span,
        'run_span_frac_stature': prof.run_span / S,
        'run_station_range': [int(prof.run_lo), int(prof.run_hi)] if prof.run_len else None,
        'run_stations': prof.run_rows,
        'run_min_abs_relief_mm': prof.run_min_abs_relief_mm,
        'run_min_abs_contrast': prof.run_min_abs_contrast,
        'sign_changes': prof.sign_changes,
        'sign_changes_qualifying': prof.sign_changes_q,
        'dominant_sign': int(np.sign(np.nansum(rel))) if prof.ok.any() else 0,
        'peak_station': peak,
        'peak_vertex': int(p.st[peak]) if peak >= 0 else None,
        'peak_relief_mm': float(rel[peak] * S * 1000.0) if peak >= 0 else None,
        'peak_contrast': float(con[peak]) if peak >= 0 else None,
        'median_abs_relief_mm': (
            float(np.median(prof.absrel[np.isfinite(prof.absrel)]) * S * 1000.0)
            if np.isfinite(prof.absrel).any()
            else None
        ),
        'verdict': verdict,
        'resolves_relief': bool(resolves_relief(verdict)),
        'verdict_class': vclass,
        'null_rate': null_rate,
        'verdict_meaning': _VERDICT_MEANING[verdict]
        % {
            'min_run': min_run,
            'min_run_any': min_run_any,
            'min_stations': RIDGE_MIN_STATIONS,
            'rate': (100.0 * null_rate) if null_rate is not None else 0.0,
        },
        'thresholds': {
            'min_frac_stature': float(p.min_frac_stature),
            'min_contrast': float(p.min_contrast),
            'min_run': int(min_run),
            'min_run_any_sign': int(min_run_any),
            'station_provenance': (
                'MEASURED-NULL curvature.RELIEF_NULL_P99' if p.mode == 'point' else 'MEASURED-NULL ridge.ridge_null p99'
            ),
            'run_provenance': 'MEASURED-NULL ridge.ridge_null',
        },
        'geometry': {
            'core_frac': p.core_frac,
            'gap_frac': p.gap_frac,
            'width_frac': p.width_frac,
            'along_stations': p.along_stations,
            'point_radius_frac': p.point_radius_frac,
        },
    }
