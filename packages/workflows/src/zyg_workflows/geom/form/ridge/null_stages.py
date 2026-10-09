# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `null.ridge_null` — one phase of the measured null per function.

Extracted from null.py so each phase can be exercised on its own: the pool sweep, the
per-station distribution, the re-scoring of stored candidate profiles at an explicit cut,
the run distribution, the three rates a caller has to see, the same null re-scored at the
mesh's own unfloored p99, and the facet null.

IMPORT DIRECTION. This module imports its parent `null` at module level (for the pool
builder and the two histogram helpers, which are part of `null`'s published surface via
`ridge/__init__.py`); `null.ridge_null` defers its import of this module into the
orchestrator, which keeps the pair acyclic.
"""

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge import null as _null
from zyg_workflows.geom.form.ridge.constants import (
    RIDGE_MIN_STATIONS,
    RIDGE_NULL_P99,
    STATION_MIN_CONTRAST,
    STATION_MIN_FRAC_STATURE,
    _zyg_log,
)
from zyg_workflows.geom.form.ridge.primitive import _score_profile
from zyg_workflows.geom.form.ridge.facet_search import facet_flatness, ridge_search


def percentile_summary(values, q, with_min=False):
    """{median, [min], max, p<k> for k in q} of `values`, or None when it is empty.

    The one shape every distribution in this null is reported in. `with_min` adds the
    minimum (the facet ratios are quoted from below, the station magnitudes from above).
    """
    a = np.asarray(values, float)
    if not len(a):
        return None
    out = {'median': float(np.median(a))}
    if with_min:
        out['min'] = float(a.min())
    out['max'] = float(a.max())
    out.update({'p%d' % k: float(np.percentile(a, k)) for k in q})
    return out


def collect_mode_profiles(v, faces, seeds, target_sizes, n_pools, mask, S, ar, nv, G, polarity, mode, verbose):
    """Run `ridge_search` over every pool of every target size for one mode.

    Takes the mesh, the (len(target_sizes), n_pools) seed matrix, the skin mask and the
    pre-computed areas/normals/graph; returns
    (per_pool, frac, cons, sizes, skipped) — the per-pool candidate profiles, the flat
    lists of |station relief| and |station contrast| over every valid station, the pool
    sizes that were kept, and the number of pools that could not be grown or searched.
    """
    per_pool, frac, cons, sizes, skipped = [], [], [], [], 0
    pcache = {}
    for ti, tn in enumerate(target_sizes):
        for j in range(int(n_pools)):
            p = _null._pool_of_size(v, faces, seeds[ti, j], tn, S, mask)
            if p is None or len(p) < RIDGE_MIN_STATIONS:
                skipped += 1
                continue
            r = ridge_search(
                v,
                faces,
                p,
                polarity=polarity,
                stature_m=S,
                areas=ar,
                normals=nv,
                graph=G,
                mode=mode,
                point_cache=pcache,
                collect=True,
            )
            if r['status'] != 'ok':
                skipped += 1
                continue
            sizes.append(len(p))
            per_pool.append(r['candidate_profiles'])
            for rl, cn, okk, _hp in r['candidate_profiles']:
                frac.extend(np.abs(rl[okk]).tolist())
                cons.extend(np.abs(cn[okk]).tolist())
            if verbose:
                _zyg_log.info(
                    '   null %-5s target %3d  pool %4d  cands %d' % (mode, tn, len(p), len(r['candidate_profiles']))
                )
    return per_pool, frac, cons, sizes, skipped


def station_record(per_pool, skipped, sizes, frac, cons, q):
    """The per-mode record up to and including the station cut it will be scored at.

    Returns (rec, cut_f, cut_c): the record carrying the pool counts, the pool-size
    summary, the two per-station magnitude distributions and `station_cut_used`, plus the
    cut itself — each mode's own measured p99, FLOORED at the published cage constant, so
    the cut can only ever be raised and a ridge claim can only ever get harder.
    """
    rec = {
        'n_pools': len(per_pool),
        'skipped': skipped,
        'pool_size': {
            'median': float(np.median(sizes)) if sizes else float('nan'),
            'min': int(min(sizes)) if sizes else 0,
            'max': int(max(sizes)) if sizes else 0,
        },
        'n_stations_scored': len(frac),
    }
    for name, a in (('abs_station_relief_frac', frac), ('abs_station_contrast', cons)):
        rec[name] = percentile_summary(a, q)
    cut_f = max(STATION_MIN_FRAC_STATURE, (rec['abs_station_relief_frac'] or {}).get('p99', STATION_MIN_FRAC_STATURE))
    cut_c = max(STATION_MIN_CONTRAST, (rec['abs_station_contrast'] or {}).get('p99', STATION_MIN_CONTRAST))
    rec['station_cut_used'] = {
        'min_frac_stature': float(cut_f),
        'min_contrast': float(cut_c),
        'raised_above_published': bool(cut_f > STATION_MIN_FRAC_STATURE or cut_c > STATION_MIN_CONTRAST),
    }
    return rec, cut_f, cut_c


def score_pools_at(per_pool, cf, cc, polarity, S):
    """Re-score every collected candidate profile at an EXPLICIT station cut.

    Factored out because the false-positive rate of a verdict is a property of the cut it
    was scored at, and this null is quoted at more than one cut (see
    `rates_at_unfloored_p99_cut`). Re-scoring stored profiles is exact — the profiles are
    the raw per-station relief/contrast arrays — and costs no new geometry.

    Returns (runs, cont, spans, anys): per pool, the longest same-sign run, the mean
    quality of the best candidate, the arc span of that run in fractions of stature, and
    the longest run of either sign.
    """
    runs_, cont_, spans_, anys_ = [], [], [], []
    for profs in per_pool:
        best, bestcont, bestany = (0, 0.0), 0.0, 0
        for rl, cn, okk, hp in profs:
            qual, _, run_len, _, run_lo, run_hi, any_len = _score_profile(rl, cn, okk, polarity, cf, cc)
            span = float(hp[run_lo:run_hi].sum()) / S if run_len >= 2 else 0.0
            best = max(best, (run_len, span))
            bestany = max(bestany, any_len)
            if okk.any():
                bestcont = max(bestcont, float(qual.sum()) / float(okk.sum()))
        runs_.append(best[0])
        spans_.append(best[1])
        cont_.append(bestcont)
        anys_.append(bestany)
    return runs_, cont_, spans_, anys_


def run_distributions(rec, runs, cont, spans, anys, q):
    """Write the four run distributions, the raw histograms and the min_run estimates.

    Mutates `rec` in place, in the original key order.

    THE RAW DISCRETE COUNTS are kept so the next person can POOL SEEDS instead of
    averaging percentiles. A run length is an integer 0..14; np.percentile interpolates
    between order statistics, so its "p99" lands on values the statistic can never take
    (2.31) and ceil() of it flips on the 1% tail of a 120-sample draw. That flip is the
    whole reason the shipped constant was a coin toss. Histograms are additive across
    seeds; interpolated percentiles are not. `discrete_min_run` is the honest discrete
    reading of the same tail: the shortest run whose chance of occurring on landmark-free
    skin is already <= 1%, which is what min_run MEANS. 'mixed_strip' is scored off the
    ANY-SIGN run, which is >= the same-sign run by construction, so its null is a
    DIFFERENT and never-smaller distribution — measured here so it can be enforced.
    """
    for name, a in (
        ('best_longest_run', runs),
        ('best_continuity', cont),
        ('best_run_span_frac_stature', spans),
        ('best_longest_run_any_sign', anys),
    ):
        rec[name] = percentile_summary(a, q)
    rec['best_longest_run_hist'] = _null._hist(runs)
    rec['best_longest_run_any_sign_hist'] = _null._hist(anys)
    rec['implied_min_run'] = int(np.ceil(rec['best_longest_run']['p99'])) + 1 if rec['best_longest_run'] else None
    rec['discrete_min_run'] = _null._discrete_min_run(rec['best_longest_run_hist'])
    rec['discrete_min_run_any_sign'] = _null._discrete_min_run(rec['best_longest_run_any_sign_hist'])
    rec['implied_min_run_any_sign'] = (
        int(np.ceil(rec['best_longest_run_any_sign']['p99'])) + 1 if rec['best_longest_run_any_sign'] else None
    )


def pool_rates(rec, mode, runs, anys, cut_f, cut_c):
    """Write THE THREE RATES A CALLER HAS TO SEE before it calls any verdict a resolution.

    Mutates `rec` in place. `frac_pools_with_any_run` is the chance rate of at least one
    qualifying station on skin that carries no landmark — i.e. the false-positive rate of
    the 'point_only' verdict, which is why point_only may never count as a resolution.
    The thresholds are the DISCRETE estimator floored at the shipped panel value: the
    interpolated one stays in `implied_min_run` for comparison with the superseded
    derivation, but the rates must be quoted at the threshold a caller will actually be
    scored against, and probe_pools will never run below the shipped constant.
    `frac_pools_resolved` is the union of two maxima computed independently over
    candidates, which over-counts rather than under-counts — the only safe direction for a
    false-positive rate.
    """
    r_arr = np.asarray(runs, float)
    a_arr = np.asarray(anys, float)
    rec['frac_pools_with_any_run'] = float(np.mean(r_arr > 0)) if runs else 0.0
    rec['frac_pools_point_only_or_better'] = rec['frac_pools_with_any_run']
    mr = max(int(RIDGE_NULL_P99[mode]['min_run']), int(rec['discrete_min_run'] or rec['implied_min_run'] or 0))
    mra = max(int(RIDGE_NULL_P99[mode].get('min_run_any_sign') or mr), int(rec['discrete_min_run_any_sign'] or 0), mr)
    rec['frac_pools_at_or_above_min_run'] = float(np.mean(r_arr >= mr)) if runs else 0.0
    rec['frac_pools_at_or_above_min_run_any_sign'] = float(np.mean(a_arr >= mra)) if anys else 0.0
    rec['frac_pools_resolved'] = float(np.mean((r_arr >= mr) | (a_arr >= mra))) if runs else 0.0
    rec['min_run_rates_quoted_at'] = {
        'min_frac_stature': float(cut_f),
        'min_contrast': float(cut_c),
        'min_run': int(mr),
        'min_run_any_sign': int(mra),
        'note': 'every frac_pools_* field above is measured at THIS cut. A caller that '
        'scores probes at a different cut may not quote these rates.',
    }
    return mr, mra


def unfloored_rates(rec, per_pool, mode, cut_f, cut_c, mr, mra, polarity, S):
    """THE SAME NULL, SCORED AT THE MODE'S OWN UNFLOORED p99 — returned as a block.

    cut_f/cut_c are floored at the PUBLISHED cage constants, which is what probe_pools
    applies and therefore the cut the primary rates belong to. A caller measuring a
    DIFFERENT tessellation (geom/relief_subdiv.py) is entitled to score at this mesh's own
    p99 instead, and on a finer mesh that p99 is LOWER than the cage constant — so the
    primary rates are then measured at a stricter cut than the probes, and quoting them
    beside a resolution understates its chance rate. That is not a hypothetical: on
    originals/female at subdivision level 2 the ridge p99 is 1.91e-3 against the published
    2.45e-3, a 22% gap on relief and 34% on contrast. So the rates are ALSO measured here
    at the unfloored p99 and returned separately. Nothing about the primary numbers
    changes; this block is additive, and when the unfloored cut is at or above the
    published one it IS the primary cut and the primary numbers are copied over.
    """
    raw_f = float((rec['abs_station_relief_frac'] or {}).get('p99', cut_f))
    raw_c = float((rec['abs_station_contrast'] or {}).get('p99', cut_c))
    if raw_f >= cut_f and raw_c >= cut_c:
        return {
            'min_frac_stature': float(cut_f),
            'min_contrast': float(cut_c),
            'identical_to_primary': True,
            'best_longest_run_hist': dict(rec['best_longest_run_hist']),
            'best_longest_run_any_sign_hist': dict(rec['best_longest_run_any_sign_hist']),
            'discrete_min_run': rec['discrete_min_run'],
            'discrete_min_run_any_sign': rec['discrete_min_run_any_sign'],
            'min_run_used': int(mr),
            'min_run_any_sign_used': int(mra),
            'frac_pools_with_any_run': rec['frac_pools_with_any_run'],
            'frac_pools_at_or_above_min_run': rec['frac_pools_at_or_above_min_run'],
            'frac_pools_resolved': rec['frac_pools_resolved'],
            'note': 'the unfloored p99 is at or above the published constant on '
            'this mesh, so this cut IS the primary cut.',
        }
    rr, _cc2, _ss2, aa = score_pools_at(per_pool, raw_f, raw_c, polarity, S)
    rh, ah = _null._hist(rr), _null._hist(aa)
    d_mr = _null._discrete_min_run(rh)
    d_ma = _null._discrete_min_run(ah)
    mr2 = max(int(RIDGE_NULL_P99[mode]['min_run']), int(d_mr or 0))
    mra2 = max(int(RIDGE_NULL_P99[mode].get('min_run_any_sign') or mr2), int(d_ma or 0), mr2)
    ra, aab = np.asarray(rr, float), np.asarray(aa, float)
    return {
        'min_frac_stature': raw_f,
        'min_contrast': raw_c,
        'identical_to_primary': False,
        'best_longest_run_hist': rh,
        'best_longest_run_any_sign_hist': ah,
        'discrete_min_run': d_mr,
        'discrete_min_run_any_sign': d_ma,
        'min_run_used': int(mr2),
        'min_run_any_sign_used': int(mra2),
        'frac_pools_with_any_run': (float(np.mean(ra > 0)) if rr else 0.0),
        'frac_pools_at_or_above_min_run': (float(np.mean(ra >= mr2)) if rr else 0.0),
        'frac_pools_resolved': (float(np.mean((ra >= mr2) | (aab >= mra2))) if rr else 0.0),
        'note': 'measured by re-scoring the SAME candidate profiles at this '
        "mesh's own p99, unfloored. Use these rates, not the "
        'primary ones, when probes are scored at this cut.',
    }


def facet_null(v, faces, seeds, target_sizes, n_pools, mask, S, ar, nv):
    """THE FACET NULL — where ordinary skin sits on facet_flatness's ordering test.

    `facet_flatness`'s "flatter than its collar" has nothing to tune, and its price is
    that ordinary skin passes it about half the time. Quoting a facet verdict without
    saying where its curvedness ratio sits in this distribution would be reporting a coin
    flip as evidence. Returns the `facet` block: the pool count, the fraction flatter than
    their collar, and the curvedness/planarity ratio distributions quoted from below.
    """
    cu = CV.curvature(v, faces, stature_m=S, normals=nv)
    ratios, plan = [], []
    for ti, tn in enumerate(target_sizes):
        for j in range(int(n_pools)):
            p = _null._pool_of_size(v, faces, seeds[ti, j], tn, S, mask)
            if p is None or len(p) < 3:
                continue
            try:
                f = facet_flatness(v, faces, p, stature_m=S, areas=ar, normals=nv, curv=cu)
            except ValueError as _exc:
                _zyg_log.debug('facet flatness probe skipped: %s', _exc)
                continue
            if np.isfinite(f.get('curvedness_ratio', np.nan)):
                ratios.append(f['curvedness_ratio'])
            if np.isfinite(f.get('planarity_ratio', np.nan)):
                plan.append(f['planarity_ratio'])
    out = {
        'n': len(ratios),
        'frac_flatter_than_collar': (float(np.mean(np.asarray(ratios) < 1.0)) if ratios else None),
    }
    for name, a in (('curvedness_ratio', ratios), ('planarity_ratio', plan)):
        out[name] = percentile_summary(a, (1, 5, 10, 50, 90), with_min=True)
    return out
