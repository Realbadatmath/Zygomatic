# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measured null: what random curves on ordinary skin do under the identical search.

Moved verbatim out of the old single-file ridge.py (lines 1634-2224).
"""

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    RIDGE_N_STATIONS,
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_P99,
    RIDGE_NULL_PANEL_N_POOLS,
    RIDGE_NULL_SEED_PANEL,
    SEARCH_N_DIRECTIONS,
    SEARCH_N_OFFSETS,
    STATION_MIN_CONTRAST,
    STATION_MIN_FRAC_STATURE,
)
from zyg_workflows.geom.form.ridge.primitive import _group_distance, _mesh_key, build_graph

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# the null — what random curves on ordinary skin do under the identical search
# ---------------------------------------------------------------------------------
_SHELL_CACHE = {}


def shell_mask(v, faces):
    """The largest connected component — the body shell.

    This mesh is not one surface: the eyeballs and the tongue are separate closed
    components. A window written as a box in fractions of stature picks them up (MEASURED:
    the orbital_margin window of probe_head.py holds 286 vertices on the neutral, of which
    the eyeball shells contribute a substantial share), and a "ridge" found on an eyeball rim
    would be a statement about a prop, not about the face. Every pool below is intersected
    with this mask and the number dropped is reported rather than silently absorbed.
    """
    from scipy.sparse.csgraph import connected_components

    key = _mesh_key(np.asarray(v, np.float64), faces)
    hit = _SHELL_CACHE.get(key)
    if hit is not None:
        return hit
    _, lab = connected_components(CV.vertex_adjacency(faces, len(v)), directed=False)
    m = lab == np.bincount(lab).argmax()
    if len(_SHELL_CACHE) > 8:
        _SHELL_CACHE.clear()
    _SHELL_CACHE[key] = m
    return m


def _skin_mask(v, faces, stature_m=None):
    """curvature.relief_null's own torso-and-limb mask, reproduced so the two nulls are
    taken over the same skin. Head, hands, feet and perineum are out: relief there is
    dominated by real features and a null measured through them is not a null."""
    from scipy.sparse.csgraph import connected_components

    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    fz = (v[:, 2] - v[:, 2].min()) / S
    _, lab = connected_components(CV.vertex_adjacency(faces, len(v)), directed=False)
    m = lab == np.bincount(lab).argmax()
    m &= (fz > 0.075) & (fz < 0.855) & (np.abs(v[:, 0]) < 0.25 * S)
    m &= ~((fz > 0.44) & (fz < 0.53) & (np.abs(v[:, 0]) < 0.036 * S))
    return m


def _pool_of_size(v, faces, seed, target_n, stature_m, mask=None, rmax=0.30):
    """A geodesic ball around `seed` grown until it holds about `target_n` vertices.

    Matched in SIZE because the search multiplicity that the null has to price in scales
    with the pool: a bigger window offers more distinct candidate curves and therefore more
    chances at a long run. A null taken on 26-vertex balls and applied to a 356-vertex
    window would be anti-conservative, which is the one direction that is not allowed.
    """
    d = _group_distance(v, faces, [int(seed)])
    if mask is not None:
        d = np.where(mask, d, np.inf)
    order = np.sort(d[np.isfinite(d)])
    if len(order) < target_n:
        return None
    r = float(order[int(target_n) - 1])
    if r > rmax * stature_m:
        return None
    return np.nonzero(d <= r)[0]


def _hist(vals):
    """Integer histogram as {value: count} — additive across seeds, unlike a percentile."""
    a = np.asarray(list(vals), int)
    if not len(a):
        return {}
    u, c = np.unique(a, return_counts=True)
    return {int(k): int(n) for k, n in zip(u, c)}


def merge_hists(hists):
    """Sum {value: count} histograms. Pooling the COUNTS of k independent seed draws is the
    same experiment as one draw with k times the pools; averaging their percentiles is not."""
    out = {}
    for h in hists:
        for k, n in (h or {}).items():
            out[int(k)] = out.get(int(k), 0) + int(n)
    return out


def _discrete_min_run(hist, alpha=RIDGE_NULL_ALPHA):
    """Smallest run length whose exceedance probability on landmark-free skin is <= alpha.

    min_run = min{ r : P(best_longest_run >= r) <= alpha }.

    This is what "p99 + 1" was reaching for, computed on the integer the statistic actually
    is. ceil(np.percentile(runs, 99)) + 1 interpolates between order statistics of a discrete
    variable, so on a 120-pool draw it is decided by whichever one or two pools happen to sit
    in the top 1% — which is how seven seeds of the SAME experiment returned min_run 2, 3, 3,
    3, 3, 3 and 5. The exceedance form is a step function of counts: it can only change when
    the tail mass genuinely crosses alpha, and it converges as pools are added.
    """
    tot = sum((hist or {}).values())
    if not tot:
        return None
    for r in range(0, max(hist) + 2):
        tail = sum(n for k, n in hist.items() if k >= r)
        if tail / float(tot) <= alpha:
            return int(r)
    return int(max(hist) + 1)


def exceedance(hist, r):
    """P(best_longest_run >= r) under a null histogram — the FPR a min_run of `r` buys."""
    tot = sum((hist or {}).values())
    if not tot:
        return None
    return sum(n for k, n in hist.items() if k >= r) / float(tot)


def ridge_null(
    v,
    faces,
    target_sizes=(30, 100, 300),
    n_pools=40,
    seed=20260806,
    polarity='either',
    modes=('ridge', 'point'),
    stature_m=None,
    verbose=False,
    collect_profiles=False,
):
    """The distribution of ridge_search's statistics over RANDOM curves on ordinary skin.

    This is the reference RIDGE_NULL_P99 is calibrated against, and it exists as code so
    that constant can be re-derived rather than believed — the same contract
    curvature.relief_null holds for RELIEF_MIN_*.

    It is a FALSE-POSITIVE calibration, not a fit: the pools contain no landmark anyone
    asked about, so whatever these curves produce is what the cage's tessellation gives for
    free. Raising a threshold to sit outside that distribution can only make a ridge claim
    harder. Nothing here can ever LOWER the per-station cut inherited from
    curvature.RELIEF_NULL_P99; it can only raise it, and on this cage it does — see below.

    IT IS SELF-CALIBRATING AND MUST BE. The anisotropic collar is a different estimator from
    the isotropic one, so the isotropic p99 is not its 1% point: MEASURED over the 24-seed
    panel on the neutral (~397k ridge stations and ~393k point stations per seed), the
    anisotropic collar's per-station p99 runs 1.42x the isotropic one on |relief|
    (3.184e-3 against 2.249e-3) and 1.43x on |contrast| (4.233 against 2.967), because the
    crest patch is a handful of vertices and the reference surface is a pair of flanking
    bands rather than a closed ring. Scoring the anisotropic primitive at the isotropic cut
    would therefore run it at several times the advertised false-positive rate and
    manufacture "gained" landmarks. So each mode is scored at ITS OWN measured p99 (floored
    at the published isotropic one), and the run distribution is computed at that cut —
    which is why every candidate's raw profile is collected and re-scored rather than
    re-measured.

    `collect_profiles=True` additionally returns every candidate's raw per-station arrays
    under by_mode[mode]['_profiles'], so a caller measuring a DIFFERENT tessellation can
    pool several seeds and re-score all of them at one common cut. Re-scoring stored
    profiles is exact; re-running the search is not necessary and would not be identical.

    ONE CALL IS ONE DRAW AND MUST NOT BE SHIPPED AS A CONSTANT. Everything this returns is
    conditional on `seed`. The run threshold in particular is a 1% tail of a few hundred
    integers and moves with the seed; see RIDGE_NULL_P99's header for what that cost. Use
    ridge_null_sweep() to derive a threshold, and this for a single diagnostic draw.
    """
    from zyg_workflows.geom.form.ridge import null_stages as ST

    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    ar = CV.mixed_voronoi_area(v, faces)
    nv = CV.vertex_normals(v, faces)
    G = build_graph(v, faces)
    mask = _skin_mask(v, faces, S)
    pool = np.nonzero(mask)[0]
    rng = np.random.default_rng(int(seed))
    out = {
        'seed': int(seed),
        'stature_m': S,
        'polarity': polarity,
        'target_sizes': list(target_sizes),
        'n_candidates_per_pool': SEARCH_N_DIRECTIONS * SEARCH_N_OFFSETS,
        'n_stations': RIDGE_N_STATIONS,
        'skin_pool': int(len(pool)),
        'published_station_cut': {
            'min_frac_stature': STATION_MIN_FRAC_STATURE,
            'min_contrast': STATION_MIN_CONTRAST,
            'source': 'curvature.RELIEF_NULL_P99',
        },
        'by_mode': {},
    }
    seeds = rng.choice(pool, size=(len(target_sizes), int(n_pools)), replace=False)
    q = (50, 75, 90, 95, 99)
    for mode in modes:
        per_pool, frac, cons, sizes, skipped = ST.collect_mode_profiles(
            v, faces, seeds, target_sizes, n_pools, mask, S, ar, nv, G, polarity, mode, verbose
        )
        rec, cut_f, cut_c = ST.station_record(per_pool, skipped, sizes, frac, cons, q)
        runs, cont, spans, anys = ST.score_pools_at(per_pool, cut_f, cut_c, polarity, S)
        ST.run_distributions(rec, runs, cont, spans, anys, q)
        mr, mra = ST.pool_rates(rec, mode, runs, anys, cut_f, cut_c)
        rec['rates_at_unfloored_p99_cut'] = ST.unfloored_rates(rec, per_pool, mode, cut_f, cut_c, mr, mra, polarity, S)
        if collect_profiles:
            # The raw per-station (relief, contrast, valid, arc-length) arrays of every
            # candidate of every pool, so a CALLER can re-score this null at a cut it
            # chooses — e.g. pooling several seeds and scoring them all at the panel's
            # upper bound. Not JSON-serialisable and deliberately underscore-named; nothing
            # in this module reads it back.
            rec['_profiles'] = per_pool
        out['by_mode'][mode] = rec

    out['facet'] = ST.facet_null(v, faces, seeds, target_sizes, n_pools, mask, S, ar, nv)
    return out


def ridge_null_sweep(
    v,
    faces,
    seeds=RIDGE_NULL_SEED_PANEL,
    n_pools=RIDGE_NULL_PANEL_N_POOLS,
    target_sizes=(30, 100, 300),
    modes=('ridge', 'point'),
    stature_m=None,
    verbose=True,
):
    """Re-derive RIDGE_NULL_P99 over the WHOLE SEED PANEL. This is what shipped.

    WHY THIS EXISTS. ridge_null() is one draw. Its `implied_min_run` is ceil(p99)+1 of a
    120-sample discrete distribution, i.e. it is decided by the one or two most extreme
    pools, so it is not a measurement of the cage — it is a measurement of the seed. Measured
    on this cage, seven seeds of the identical experiment returned min_run 2, 3, 3, 3, 3, 3
    and 5, and the seed that shipped returned the unique minimum of the seven on BOTH axes.
    A threshold that is the most permissive of seven draws is indistinguishable from a
    threshold tuned until our own bodies passed, whatever the intent was.

    So the constant is derived from the panel, two ways, and both are reported:
      PER-SEED    every seed's own estimate, giving the spread the single draw hid.
      POOLED      the seed histograms summed — one experiment of len(seeds)*3*n_pools pools.
                  Counts are additive; percentiles are not. This is the point estimate.

    and the SHIPPED value is the panel UPPER BOUND (see RIDGE_NULL_P99's header for why that
    direction and not the median).

    Returns {'per_seed': [...], 'pooled': {...}, 'shipped_candidate': {...}}.
    """
    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    per_seed, hists, anyhists = [], {m: [] for m in modes}, {m: [] for m in modes}
    for _i, sd in enumerate(seeds):
        n = ridge_null(v, faces, target_sizes=target_sizes, n_pools=n_pools, seed=int(sd), modes=modes, stature_m=S)
        row = {'seed': int(sd)}
        for m in modes:
            r = n['by_mode'][m]
            hists[m].append(r['best_longest_run_hist'])
            anyhists[m].append(r['best_longest_run_any_sign_hist'])
            row[m] = {
                'implied_min_run': r['implied_min_run'],
                'discrete_min_run': r['discrete_min_run'],
                'discrete_min_run_any_sign': r['discrete_min_run_any_sign'],
                'cut_frac': r['station_cut_used']['min_frac_stature'],
                'cut_contrast': r['station_cut_used']['min_contrast'],
                'n_pools': r['n_pools'],
            }
        per_seed.append(row)
        if verbose:
            _zyg_log.info(
                '  seed %-9d %s'
                % (
                    sd,
                    '  '.join(
                        '%s: min_run %s (interp %s) cut %.4fe-3'
                        % (m, row[m]['discrete_min_run'], row[m]['implied_min_run'], row[m]['cut_frac'] * 1e3)
                        for m in modes
                    ),
                )
            )
    pooled, shipped = {}, {}
    for m in modes:
        H = merge_hists(hists[m])
        HA = merge_hists(anyhists[m])
        cf = [r[m]['cut_frac'] for r in per_seed]
        cc = [r[m]['cut_contrast'] for r in per_seed]
        dm = [r[m]['discrete_min_run'] for r in per_seed]
        dma = [r[m]['discrete_min_run_any_sign'] for r in per_seed]
        pooled[m] = {
            'n_pools_total': sum(H.values()),
            'run_hist': H,
            'run_hist_any_sign': HA,
            'min_run': _discrete_min_run(H),
            'min_run_any_sign': _discrete_min_run(HA),
            'exceedance': {r: exceedance(H, r) for r in range(1, max(H) + 2)},
            'exceedance_any_sign': {r: exceedance(HA, r) for r in range(1, max(HA) + 2)},
        }
        shipped[m] = {
            # PANEL UPPER BOUND on every axis. max() over a FIXED panel, so it is
            # reproducible; and it can only make a ridge claim harder, never easier.
            'min_run': max([x for x in dm if x is not None] + [pooled[m]['min_run']]),
            'min_run_any_sign': max([x for x in dma if x is not None] + [pooled[m]['min_run_any_sign']]),
            'station_min_frac_stature': max(cf),
            'station_min_contrast': max(cc),
            'panel_median_min_run': float(np.median(dm)),
            'panel_median_cut_frac': float(np.median(cf)),
            'panel_min_cut_frac': float(min(cf)),
            'panel_max_cut_frac': float(max(cf)),
        }
    return {
        'per_seed': per_seed,
        'pooled': pooled,
        'shipped_candidate': shipped,
        'seeds': [int(s) for s in seeds],
        'n_pools': int(n_pools),
        'target_sizes': list(target_sizes),
        'alpha': RIDGE_NULL_ALPHA,
        'stature_m': S,
    }


def facet_percentile(null, ratio):
    """Where a measured curvedness ratio sits in the skin null — the severity of a facet
    claim, never its threshold."""
    f = (null or {}).get('facet') or {}
    q = f.get('curvedness_ratio')
    if not q or not np.isfinite(ratio):
        return None
    pts = [(1, q['p1']), (5, q['p5']), (10, q['p10']), (50, q['p50']), (90, q['p90'])]
    below = [p for p, x in pts if ratio <= x]
    return min(below) if below else 100


def station_cut(null=None, mode='ridge'):
    """The per-station cut actually to be used for `mode`: the published isotropic p99,
    RAISED to that mode's own measured p99 where that is stricter, never lowered.

    With no null in hand it returns the published cut, which is correct for mode='point'
    (that IS the primitive the published null was measured with) and OPTIMISTIC for
    mode='ridge'. ridge_relief therefore defaults to the published cut and the callers that
    make claims — probe_pools, report_table — pass the measured one in."""
    d = RIDGE_NULL_P99.get(mode, RIDGE_NULL_P99['ridge'])
    frac, con = d['station_min_frac_stature'], d['station_min_contrast']
    src = (
        'curvature.RELIEF_NULL_P99 (isotropic point probe)'
        if mode == 'point'
        else 'ridge.RIDGE_NULL_P99[%r] (shipped, measured)' % mode
    )
    if null:
        r = (null.get('by_mode') or {}).get(mode) or {}
        u = r.get('station_cut_used') or {}
        if u.get('min_frac_stature', 0) > frac:
            frac, src = float(u['min_frac_stature']), 'ridge.ridge_null mode=%r p99' % mode
        if u.get('min_contrast', 0) > con:
            con, src = float(u['min_contrast']), 'ridge.ridge_null mode=%r p99' % mode
    return {'min_frac_stature': frac, 'min_contrast': con, 'provenance': 'MEASURED-NULL', 'source': src}
