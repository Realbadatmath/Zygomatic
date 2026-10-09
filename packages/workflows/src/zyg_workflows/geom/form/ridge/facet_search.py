# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""facet_flatness() — the DOTTED-line primitive — and the candidate-curve search over a pool of skin.

Moved verbatim out of the old single-file ridge.py (lines 1290-1633).
"""

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    RIDGE_MIN_STATIONS,
    RIDGE_N_STATIONS,
    SEARCH_N_DIRECTIONS,
    SEARCH_N_OFFSETS,
    STATION_MIN_CONTRAST,
    STATION_MIN_FRAC_STATURE,
    _zyg_log,
)
from zyg_workflows.geom.form.ridge.primitive import ridge_relief


# ---------------------------------------------------------------------------------
# facet — the DOTTED-line landmarks of HeadNeck p.80
# ---------------------------------------------------------------------------------
def facet_flatness(
    v,
    faces,
    group,
    stature_m=None,
    areas=None,
    normals=None,
    curv=None,
    gap_frac=CV.COLLAR_GAP_FRAC,
    width_frac=CV.COLLAR_WIDTH_FRAC,
    max_tilt_deg=CV.COLLAR_MAX_TILT_DEG,
    min_frac_stature=STATION_MIN_FRAC_STATURE,
    min_contrast=STATION_MIN_CONTRAST,
):
    """Is this patch a PLANE rather than a bump? — HeadNeck p.80's dotted-line landmarks.

    Frontal eminence, glabella/superciliary arch, parietal eminence, malar eminence and
    mastoid are drawn with a DOTTED outline in that book, meaning a flat facet: a broad
    plane whose edges are where the head changes direction. Asserting relief on one of them
    is a category error — a correctly modelled frontal eminence has NO bump to find.

    So the assertion has three parts and two of them have no free parameter:
      1. NOT A BUMP. |relief| against the isotropic collar must be BELOW the cage's own
         relief p99. This reuses curvature.region_relief unchanged; the threshold is the
         same measured one everything else here uses, read in the opposite direction.
      2. FLATTER THAN ITS SURROUND. area-weighted mean curvedness over the patch must be
         lower than over its collar. A pure ORDERING test, nothing to tune. It is also weak
         on its own — under a null of ordinary skin it is true about half the time by
         symmetry — so `curvedness_ratio` is reported as the severity, not as the evidence.
      3. PLANARITY. rms residual to the patch's own best-fit PLANE divided by the patch's
         radius in its tangent plane. Dimensionless and scale-free: for a spherical cap of
         radius R over a patch of half-width a it is proportional to a/R, i.e. it is
         curvature x patch size. Reported, not thresholded — there is no printed number for
         "how flat a frontal eminence is" and inventing one on our own mesh is exactly what
         the calibration policy forbids.

    Verdict: 'bump' / 'pit' when part 1 fails, 'not_flatter' when part 2 fails, 'facet' when
    both hold, 'unmeasurable' when curvature.region_relief refuses the patch and says why.
    """
    v = np.asarray(v, np.float64)
    g = np.unique(np.asarray(group, np.int64).ravel())
    if g.size == 0:
        raise ValueError('facet_flatness needs a non-empty group')
    if g.min() < 0 or g.max() >= len(v):
        raise ValueError('group indexes vertices outside the mesh (0..%d)' % (len(v) - 1))
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    ar = CV.mixed_voronoi_area(v, faces) if areas is None else np.asarray(areas, np.float64)
    nv = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals, np.float64)

    out = {'n_group': int(len(g)), 'stature_m': S, 'centroid_frac_stature': float((v[g, 2].mean() - v[:, 2].min()) / S)}

    # part 3 first: it needs nothing but the patch itself, so it survives a collar refusal.
    P = v[g]
    c = P.mean(0)
    if len(g) >= 3:
        _, sv, vt = np.linalg.svd(P - c, full_matrices=False)
        h = (P - c).dot(vt[2])
        rad = float(np.linalg.norm(np.stack([(P - c).dot(vt[0]), (P - c).dot(vt[1])], 1), axis=1).max())
        rms = float(np.sqrt(np.average(h**2, weights=ar[g])))
        out['plane_rms_mm'] = rms * 1000.0
        out['patch_radius_mm'] = rad * 1000.0
        out['planarity_ratio'] = rms / rad if rad > 0 else float('nan')
    else:
        out['plane_rms_mm'] = out['patch_radius_mm'] = out['planarity_ratio'] = float('nan')

    try:
        col, cdet = CV.collar(
            v,
            faces,
            g,
            gap_frac=gap_frac,
            width_frac=width_frac,
            stature_m=S,
            normals=nv,
            max_tilt_deg=max_tilt_deg,
            return_detail=True,
        )
    except ValueError as e:
        out.update(verdict='unmeasurable', why=str(e), n_collar=0)
        return out

    cu = CV.curvature(v, faces, stature_m=S, normals=nv) if curv is None else curv
    cvn = cu['curvedness_norm']
    si = cu['shape_index']

    def _wstat(idx, f):
        w = ar[idx]
        x = f[idx]
        m = np.isfinite(x)
        if not m.any():
            return float('nan'), float('nan')
        w = w[m]
        x = x[m]
        mu = float(np.average(x, weights=w))
        return mu, float(np.average((x - mu) ** 2, weights=w))

    cv_p, cv_var_p = _wstat(g, cvn)
    cv_c, _ = _wstat(col, cvn)
    si_p, si_var_p = _wstat(g, si)
    out.update(
        {
            'n_collar': int(len(col)),
            'curvedness_norm_patch': cv_p,
            'curvedness_norm_collar': cv_c,
            'curvedness_ratio': (cv_p / cv_c) if cv_c > 0 else float('inf'),
            'curvedness_norm_var_patch': cv_var_p,
            'shape_index_mean_patch': si_p,
            'shape_index_var_patch': si_var_p,
            'collar_spec': cdet,
        }
    )

    try:
        r = CV.region_relief(
            v,
            faces,
            g,
            gap_frac=gap_frac,
            width_frac=width_frac,
            max_tilt_deg=max_tilt_deg,
            stature_m=S,
            areas=ar,
            normals=nv,
            min_frac_stature=min_frac_stature,
            min_contrast=min_contrast,
        )
    except ValueError as e:
        out.update(verdict='unmeasurable', why=str(e))
        return out
    out.update(
        {
            'relief_mm': r['relief_mm'],
            'relief_frac_stature': r['relief_frac_stature'],
            'contrast': r['contrast'],
            'collar_fit_rms_mm': r['collar_fit_rms_mm'],
            'relief_verdict': r['verdict'],
        }
    )

    is_relief = abs(r['relief_frac_stature']) >= min_frac_stature and abs(r['contrast']) >= min_contrast
    if is_relief:
        out['verdict'] = 'bump' if r['relief_mm'] > 0 else 'pit'
    elif not np.isfinite(out['curvedness_ratio']) or out['curvedness_ratio'] >= 1.0:
        out['verdict'] = 'not_flatter'
    else:
        out['verdict'] = 'facet'
    out['thresholds'] = {
        'min_frac_stature': float(min_frac_stature),
        'min_contrast': float(min_contrast),
        'flatter_test': 'curvedness_patch < curvedness_collar (ordering, no free parameter; ~50% under a skin null)',
        'provenance': 'MEASURED-NULL + ORDERING',
    }
    return out


# ---------------------------------------------------------------------------------
# candidate curves over a pool of skin
# ---------------------------------------------------------------------------------
def _tangent_frame(P):
    """Deterministic PCA frame of a point set. The SVD's sign is arbitrary, so e1 and e2 are
    oriented by their own largest component — otherwise the candidate directions below would
    differ between two runs on identical input and this module would not be reproducible."""
    c = P.mean(0)
    _, sv, vt = np.linalg.svd(P - c, full_matrices=False)
    e = []
    for k in range(2):
        a = vt[k]
        if a[int(np.argmax(np.abs(a)))] < 0:
            a = -a
        e.append(a)
    return c, e[0], e[1], sv


def curve_candidates(
    v,
    pool,
    n_directions=SEARCH_N_DIRECTIONS,
    n_offsets=SEARCH_N_OFFSETS,
    n_stations=RIDGE_N_STATIONS,
    min_stations=RIDGE_MIN_STATIONS,
):
    """Candidate polylines through a pool of skin: `n_directions` orientations in the pool's
    own tangent plane x `n_offsets` parallel offsets, each sampled at `n_stations` and
    snapped to the nearest pool vertex.

    WHY A SEARCH AND NOT ONE CURVE. We do not know where a bone's crest lies on the cage —
    that is the question. Committing to one curve would answer it by assumption. So the
    window is swept, and the MULTIPLICITY of the sweep is carried into ridge_null(), which
    runs the identical 6 x 7 search on random skin: the run threshold therefore already
    prices in the fact that we took a maximum over 42 tries.

    Offsets are taken at percentiles of the cross coordinate rather than at fixed metric
    steps so that every candidate stays inside the pool. A candidate that walks off the pool
    snaps back onto its edge and degenerates into the neighbouring candidate; deduplication
    would then silently reduce the multiplicity the null was measured at.
    """
    pool = np.unique(np.asarray(pool, np.int64).ravel())
    if pool.size < min_stations:
        return []
    P = np.asarray(v, np.float64)[pool]
    c, e1, e2, _ = _tangent_frame(P)
    out = []
    for theta in np.linspace(0.0, np.pi, int(n_directions), endpoint=False):
        d1 = np.cos(theta) * e1 + np.sin(theta) * e2
        d2 = -np.sin(theta) * e1 + np.cos(theta) * e2
        su = (P - c).dot(d1)
        sw = (P - c).dot(d2)
        lo, hi = np.percentile(su, 3), np.percentile(su, 97)
        if hi - lo <= 0:
            continue
        ts = np.linspace(lo, hi, int(n_stations))
        for q in np.linspace(15.0, 85.0, int(n_offsets)):
            off = np.percentile(sw, q)
            st, seen = [], set()
            for t in ts:
                i = int(pool[np.argmin((su - t) ** 2 + (sw - off) ** 2)])
                if i not in seen:
                    seen.add(i)
                    st.append(i)
            if len(st) >= min_stations:
                out.append({'theta_rad': float(theta), 'offset_pct': float(q), 'stations': st})
    return out


def _score(res):
    """Rank order for candidate curves: run length first, then the arc it spans, then the
    peak relief. Run length is the claim; magnitude is only the severity."""
    return (res['longest_run'], res['run_span_frac_stature'], abs(res['peak_relief_mm'] or 0.0))


def ridge_search(
    v,
    faces,
    pool,
    polarity='either',
    stature_m=None,
    areas=None,
    normals=None,
    graph=None,
    mode=None,
    min_run=None,
    min_run_any=None,
    point_cache=None,
    n_directions=SEARCH_N_DIRECTIONS,
    n_offsets=SEARCH_N_OFFSETS,
    n_stations=RIDGE_N_STATIONS,
    collect=False,
    **kw,
):
    """Best ridge/furrow over every candidate curve through `pool`. Returns the winning
    profile plus the search's own bookkeeping, so a negative result is checkable.

    `collect=True` also returns every candidate's raw (relief, contrast, measured) arrays,
    which is what ridge_null re-scores at the cut its own station distribution implies.

    THE RANKING IS BY SAME-SIGN RUN LENGTH (see _score) and is deliberately left that way,
    but it is not identical to "the candidate most likely to resolve": a candidate whose
    ANY-SIGN run clears min_run_any while its same-sign run does not would be a
    'mixed_strip', and a longer-peaked 'point_only' can outrank it. That direction
    UNDER-reports, which is the safe one, and `n_candidates_resolving` makes it visible
    rather than leaving it to be discovered. The ranking is not changed to chase it: the
    selection rule that produced the shipped numbers stays put, and the disclosure is the
    fix."""
    if point_cache is None:
        point_cache = {}
    npool = int(len(np.unique(pool)))
    cands = curve_candidates(v, pool, n_directions, n_offsets, n_stations)
    if not cands:
        why = (
            'the pool holds %d vertices, fewer than the %d stations a profile needs' % (npool, RIDGE_MIN_STATIONS)
            if npool < RIDGE_MIN_STATIONS
            else 'the pool holds %d vertices but no candidate line through it snapped to %d '
            'DISTINCT ones — at this tessellation the window is a cluster, not a curve, '
            'and no primitive can read continuity off it' % (npool, RIDGE_MIN_STATIONS)
        )
        return {'status': 'no_candidates', 'n_pool': npool, 'why': why}
    best, best_res = None, None
    runs, profiles, resolving = [], [], []
    for cd in cands:
        try:
            r = ridge_relief(
                v,
                faces,
                cd['stations'],
                stature_m=stature_m,
                areas=areas,
                normals=normals,
                polarity=polarity,
                graph=graph,
                mode=mode,
                min_run=min_run,
                min_run_any=min_run_any,
                point_cache=point_cache,
                **kw,
            )
        except ValueError as _exc:
            _zyg_log.debug('ridge relief probe skipped: %s', _exc)
            continue
        runs.append(r['longest_run'])
        resolving.append(bool(r['resolves_relief']))
        if collect:
            profiles.append(
                (
                    np.array(
                        [s['relief_frac_stature'] if s['status'] == 'ok' else np.nan for s in r['stations']], float
                    ),
                    np.array([s['contrast'] if s['status'] == 'ok' else np.nan for s in r['stations']], float),
                    np.array([s['status'] == 'ok' for s in r['stations']], bool),
                    np.array(r['hops_m'], float),
                )
            )
        if best_res is None or _score(r) > _score(best_res):
            best, best_res = cd, r
    if best_res is None:
        return {'status': 'all_candidates_refused', 'n_pool': int(len(np.unique(pool))), 'n_candidates': len(cands)}
    out = {
        'status': 'ok',
        'n_pool': int(len(np.unique(pool))),
        'n_candidates': len(cands),
        'n_candidates_measured': len(runs),
        'runs_over_candidates': runs,
        'n_candidates_resolving': int(sum(resolving)),
        'best_theta_rad': best['theta_rad'],
        'best_offset_pct': best['offset_pct'],
        # Hoisted so no consumer has to reach into ['result'] and re-classify a verdict
        # string for itself. This is the field the resolution contract is read from.
        'verdict': best_res['verdict'],
        'resolves_relief': bool(best_res['resolves_relief']),
        'verdict_class': best_res['verdict_class'],
        'result': best_res,
    }
    if sum(resolving) and not best_res['resolves_relief']:
        out['selection_caveat'] = (
            '%d of %d measured candidate curves resolved, but the run-length ranking chose '
            'a candidate that does not. The reported verdict UNDER-states this pool.' % (sum(resolving), len(runs))
        )
    if collect:
        out['candidate_profiles'] = profiles
    return out
