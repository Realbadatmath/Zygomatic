# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The per-mesh geodesic graph, and ridge_relief() — the curve primitive itself.

Moved verbatim out of the old single-file ridge.py (lines 767-1289).
"""

import hashlib
import os

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    POINT_PROBE_RADIUS_FRAC,
    RIDGE_ALONG_STATIONS,
    RIDGE_CORE_FRAC,
    RIDGE_GAP_FRAC,
    RIDGE_NULL_P99,
    RIDGE_WIDTH_FRAC,
)


# ---------------------------------------------------------------------------------
# graph — built once per mesh, because a polyline needs PER-STATION distances and
# curvature.surface_distance only offers the min over the seed set.
# ---------------------------------------------------------------------------------
_GRAPH_CACHE = {}


def _mesh_key(v, faces):
    h = hashlib.sha1(usedforsecurity=False)
    h.update(np.ascontiguousarray(v, np.float64).tobytes())
    h.update(np.ascontiguousarray(faces, np.int64).tobytes())
    return h.hexdigest()


def build_graph(v, faces):
    """CSR edge graph over the CAGE's own edges, weighted by edge length.

    Deliberately built from curvature._face_edges, not from a fresh edge extraction: the
    grouping convention on this cage is the quad edge set, NOT the delivered triangles'
    (curvature.py explains why — adding the 13,710 export diagonals would make "2 rings"
    mean different things on the two sides of the body). This is the same graph
    curvature.surface_distance builds; it is materialised here only because a polyline needs
    the distance from EACH station separately and that function returns the min over seeds.
    """
    from scipy.sparse import coo_matrix

    v = np.asarray(v, np.float64)
    key = _mesh_key(v, faces)
    hit = _GRAPH_CACHE.get(key)
    if hit is not None:
        return hit
    e = CV._face_edges(faces)
    w = np.linalg.norm(v[e[:, 0]] - v[e[:, 1]], axis=1)
    if (w <= 0).any():
        raise ValueError('%d cage edges have zero length' % int((w <= 0).sum()))
    n = len(v)
    G = coo_matrix(
        (np.concatenate([w, w]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(n, n)
    ).tocsr()
    if len(_GRAPH_CACHE) > 8:
        _GRAPH_CACHE.clear()
    _GRAPH_CACHE[key] = G
    return G


def _station_distances(v, faces, stations, graph=None, limit=None):
    """(N, V) geodesic distance from each station. Rows, not the min: the min alone cannot
    say which part of the curve a vertex belongs to, and the arc-band that makes the collar
    exist is defined by exactly that.

    `limit` truncates the search — MEASURED, 13.6 ms unlimited vs 2.2 ms at 0.06 of stature
    on this cage for 14 sources. Truncation is safe here because every vertex beyond it has
    d_curve = inf, which excludes it from both the crest and the collar band by construction
    rather than by a guard; the caller re-runs unlimited if the truncation lost an
    inter-station distance the arc length needs.
    """
    from scipy.sparse.csgraph import dijkstra

    G = build_graph(v, faces) if graph is None else graph
    return dijkstra(
        G,
        directed=False,
        indices=np.asarray(stations, np.int64),
        min_only=False,
        limit=np.inf if limit is None else float(limit),
    )


def _group_distance(v, faces, group, graph=None, limit=None):
    """Geodesic distance from a vertex GROUP, over the cached graph.

    Identical in meaning to curvature.surface_distance; it exists only because that function
    rebuilds the edge graph on every call — MEASURED 22.1 ms against 2-3 ms here — and the
    point-mode control below needs two of them per station over tens of thousands of
    stations."""
    from scipy.sparse.csgraph import dijkstra

    G = build_graph(v, faces) if graph is None else graph
    return dijkstra(
        G,
        directed=False,
        indices=np.asarray(group, np.int64).ravel(),
        min_only=True,
        limit=np.inf if limit is None else float(limit),
    )


def polyline_arc_length(D, stations):
    """Along-surface length of the polyline, in metres, from the station distance rows."""
    return float(sum(D[k, stations[k + 1]] for k in range(len(stations) - 1)))


def _score_profile(rel, con, ok, polarity, min_frac_stature, min_contrast):
    """Qualification and RUN structure of one profile, given a cut.

    Split out of ridge_relief because ridge_null has to re-score a profile it has already
    measured, at the cut its own measurement implies. Doing that by re-measuring would make
    the run threshold depend on the cut it is supposed to be derived alongside.

    A run is CONSECUTIVE, QUALIFYING and SAME-SIGN. An unmeasurable station breaks it: a
    feature whose continuity is only demonstrated across a hole is not a demonstrated
    continuous feature.
    """
    rel = np.asarray(rel, float)
    con = np.asarray(con, float)
    ok = np.asarray(ok, bool)
    if polarity == 'protrusion':
        score, cscore = rel, con
    elif polarity == 'depression':
        score, cscore = -rel, -con
    else:
        score, cscore = np.abs(rel), np.abs(con)
    qual = (
        ok
        & (np.nan_to_num(score, nan=-np.inf) >= min_frac_stature)
        & (np.nan_to_num(cscore, nan=-np.inf) >= min_contrast)
    )
    sgn = np.where(ok, np.sign(np.nan_to_num(rel)), 0).astype(int)
    run_len, run_sign, run_hi, cur = 0, 0, -1, 0
    for j in range(len(rel)):
        if qual[j] and cur > 0 and sgn[j] == sgn[j - 1]:
            cur += 1
        elif qual[j]:
            cur = 1
        else:
            cur = 0
        if cur > run_len:
            run_len, run_sign, run_hi = cur, int(sgn[j]), j
    run_lo = run_hi - run_len + 1 if run_len else -1
    any_len, cur = 0, 0
    for j in range(len(rel)):
        cur = cur + 1 if qual[j] else 0
        any_len = max(any_len, cur)
    return qual, sgn, run_len, run_sign, run_lo, run_hi, any_len


def _anisotropic_enabled():
    """ZYG_RIDGE_ANISOTROPIC_COLLAR — default 1 (on). Set 0 and every station reverts to
    regions.py's isotropic point probe (a 0.012-of-stature geodesic ball against the default
    collar), which is the rollback AND the before/after control."""
    return os.environ.get('ZYG_RIDGE_ANISOTROPIC_COLLAR', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')


# ---------------------------------------------------------------------------------
# the primitive
# ---------------------------------------------------------------------------------
def ridge_relief(
    v,
    faces,
    polyline,
    stature_m=None,
    areas=None,
    normals=None,
    core_frac=RIDGE_CORE_FRAC,
    gap_frac=RIDGE_GAP_FRAC,
    width_frac=RIDGE_WIDTH_FRAC,
    along_stations=RIDGE_ALONG_STATIONS,
    max_tilt_deg=CV.COLLAR_MAX_TILT_DEG,
    polarity='either',
    min_frac_stature=None,
    min_contrast=None,
    min_run=None,
    min_run_any=None,
    mode=None,
    point_radius_frac=POINT_PROBE_RADIUS_FRAC,
    graph=None,
    distances=None,
    point_cache=None,
):
    """Signed relief sampled along a CURVE, station by station, each against its own collar.

    `polyline` is an ORDERED sequence of vertex indices. Order is load-bearing: it defines
    the arc coordinate, and therefore which stations are neighbours, and therefore what a
    "run" is. A shuffled polyline is not a curve and will return a profile that means
    nothing.

    `polarity`:
      'protrusion'  score = +relief   (a ridge)
      'depression'  score = -relief   (a furrow, a pit, a fossa)
      'either'      score = |relief|, sign reported — AFS p.171's rule for the ulnar border,
                    where continuity is the gate and polarity is not.

    RETURNS the full profile, never a patch mean. The fields a caller should read first:
      stations[]            per-station relief_mm / contrast / status, in curve order
      longest_run           consecutive MEASURED, QUALIFYING, SAME-SIGN stations. An
                            unmeasurable station breaks a run, because continuity across a
                            gap has not been demonstrated.
      run_span_frac_stature the arc length that run covers. A run of 3 stations spanning
                            4 mm is not a whole-bone landmark; the count alone cannot say so.
      sign_changes          over all measured stations. AFS p.10 says the clavicle is an
                            S-curve with one A-P sign change; a straight-line clavicle is a
                            defect a mean would hide.
      verdict               'ridge' | 'furrow' | 'mixed_strip' | 'point_only' | 'flat' |
                            'unmeasurable'. 'point_only' means stations qualified but never
                            `min_run` of them in a row: a point probe would have found this
                            too, so the curve primitive adds nothing here and no whole-bone
                            claim may be made from it.
      resolves_relief       THE FIELD TO READ. True only for a verdict outside the measured
                            null (RESOLVED_VERDICTS). Do not re-derive this from `verdict`
                            in a consumer: `point_only` is INSIDE the null — it occurs on
                            33% of landmark-free skin pools in ridge mode — and a consumer
                            that lists verdict names for itself is one typo away from
                            counting the null as a result. That has already happened once.
      verdict_class         'resolved' | 'below_null' | 'no_verdict'.
      null_rate             the measured false-positive rate of THIS verdict's class in
                            THIS mode, carried beside the verdict so a reader never has to
                            go and look it up.

    `min_run`, `min_run_any`, `min_frac_stature` and `min_contrast` all default PER MODE
    from RIDGE_NULL_P99, which is measured by ridge_null(). Pass your own if the search
    multiplicity differs from this module's — the run threshold is only valid for the
    multiplicity it was measured at. `min_run_any` governs 'mixed_strip' and is read off the
    ANY-SIGN run null, which is a different distribution from the same-sign one.
    """
    # Deferred on purpose: primitive_profile imports the graph helpers and _score_profile
    # from this module, so importing it at module level would be a cycle.
    from zyg_workflows.geom.form.ridge import primitive_profile as pp

    v, st, S = pp.validate_polyline(v, polyline, polarity, stature_m)
    if mode is None:
        mode = 'ridge' if _anisotropic_enabled() else 'point'
    if mode not in ('ridge', 'point'):
        raise ValueError("mode must be 'ridge' or 'point', got %r" % mode)
    # Defaults are PER MODE, from the measured null for that mode — see RIDGE_NULL_P99. The
    # anisotropic collar does not inherit the isotropic probe's cut; it is a different
    # estimator with a measurably wider null.
    _d = RIDGE_NULL_P99[mode]
    if min_run is None:
        min_run = _d['min_run']
    if min_run_any is None:
        # 'mixed_strip' is the ANY-SIGN run clearing its own null. Defaulting it to min_run
        # would score one statistic at another statistic's threshold; they happen to be
        # equal on this cage, and the default still comes from the right measurement.
        min_run_any = _d.get('min_run_any_sign', min_run)
    if min_frac_stature is None:
        min_frac_stature = _d['station_min_frac_stature']
    if min_contrast is None:
        min_contrast = _d['station_min_contrast']

    G = build_graph(v, faces) if graph is None else graph
    probe = pp.RidgeProbe(
        v=v,
        faces=faces,
        st=st,
        S=S,
        areas=CV.mixed_voronoi_area(v, faces) if areas is None else np.asarray(areas, np.float64),
        normals=CV.vertex_normals(v, faces) if normals is None else np.asarray(normals, np.float64),
        graph=G,
        mode=mode,
        polarity=polarity,
        core_frac=core_frac,
        gap_frac=gap_frac,
        width_frac=width_frac,
        along_stations=along_stations,
        max_tilt_deg=max_tilt_deg,
        min_frac_stature=min_frac_stature,
        min_contrast=min_contrast,
        point_radius_frac=point_radius_frac,
        point_cache=point_cache,
    )
    D, hops = pp.curve_distances(v, faces, st, S, G, distances, gap_frac, width_frac)
    probe.d_curve = D.min(0)
    probe.owner = D.argmin(0)

    rows = pp.station_rows(probe)
    prof = pp.profile_summary(rows, D, st, S, polarity, min_frac_stature, min_contrast)
    verdict, vclass, null_rate = pp.classify(prof, _d, min_run, min_run_any)
    return pp.build_result(probe, rows, prof, hops, verdict, vclass, null_rate, min_run, min_run_any)
