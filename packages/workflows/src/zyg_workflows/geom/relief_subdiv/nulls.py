# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The null, at the level being probed: the seed panel, the level cut and the probe.

Moved verbatim out of the old single-file relief_subdiv.py (lines 706-1151).
"""

import time

import numpy as np

from zyg_workflows.geom.relief_subdiv.constants import (
    CAGE_NULL_TARGET_SIZES,
    LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST,
    LEVEL_CUT_ABSOLUTE_FLOOR_FRAC,
    LEVEL_NULL_SEED_PANEL,
    NULL_POOLS_BY_LEVEL,
    POINT_NULL_N_BY_LEVEL,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)
# ---------------------------------------------------------------------------------
# the null, at the level being probed
# ---------------------------------------------------------------------------------


def _pooled_runs_at(profiles_by_pool, polarity, cut_f, cut_c):
    """Longest same-sign and any-sign qualifying run of every pool, at an EXPLICIT cut.

    Re-scores stored candidate profiles rather than re-running the search, which is exact:
    the profile IS the per-station relief/contrast array the classifier reads. This is what
    lets several seeds' pools be scored at one common cut so their histograms can be pooled
    — counts are additive across seeds, percentiles are not.
    """
    from zyg_workflows.geom.form import ridge as RD

    runs, anys = [], []
    for profs in profiles_by_pool:
        best, bestany = 0, 0
        for rl, cn, okk, _hp in profs:
            _q, _s, run_len, _c, _lo, _hi, any_len = RD._score_profile(rl, cn, okk, polarity, cut_f, cut_c)
            best = max(best, int(run_len))
            bestany = max(bestany, int(any_len))
        runs.append(best)
        anys.append(bestany)
    return runs, anys


def _panel_cut(seed_nulls, mode, polarity='either'):
    """The level cut for one mode, derived from a PANEL of null draws rather than from one.

    Three numbers, and each is the conservative reading of the panel:
      station cut   the panel UPPER BOUND — max over seeds of that seed's own p99. Taking
                    the median or the shipped draw would ship whichever seed happened to be
                    permissive, which is the defect this replaces.
      min_run       from the POOLED run histogram over every pool of every seed, scored at
                    the station cut above, floored at ridge.RIDGE_NULL_P99[mode]['min_run']
                    (the 24-seed, 23,040-pool panel value). Never lowered by a level draw.
      chance rate   measured by re-scoring every pool of every seed AT THAT SAME CUT. This
                    is the number a resolution at this cut may be quoted beside, and it is
                    the one thing the previous implementation got wrong: it copied the rate
                    ridge_null measured at the FLOORED cage cut, which on a subdivided mesh
                    is 22-34% stricter than the level cut, so the rate printed beside a
                    level-cut resolution was the chance rate of a test nobody ran.
    """
    import numpy as _np
    from zyg_workflows.geom.form import ridge as RD

    shipped = RD.RIDGE_NULL_P99[mode]
    per_seed = []
    for n in seed_nulls:
        m = n['by_mode'][mode]
        per_seed.append(
            {
                'seed': int(n['seed']),
                'p99_frac': float((m.get('abs_station_relief_frac') or {}).get('p99', 0.0)),
                'p99_contrast': float((m.get('abs_station_contrast') or {}).get('p99', 0.0)),
                'n_pools': int(m.get('n_pools') or 0),
                'n_stations_scored': int(m.get('n_stations_scored') or 0),
                'discrete_min_run_at_own_p99': ((m.get('rates_at_unfloored_p99_cut') or {}).get('discrete_min_run')),
            }
        )
    fr = [r['p99_frac'] for r in per_seed]
    co = [r['p99_contrast'] for r in per_seed]
    cut_f, cut_c = max(fr), max(co)
    runs, anys = [], []
    for n in seed_nulls:
        m = n['by_mode'][mode]
        prof = m.get('_profiles')
        if prof is None:
            raise ValueError(
                'level null seed %s was measured without collect_profiles, so '
                'its pools cannot be re-scored at the panel cut. The panel cut '
                'is not derivable and no rate may be quoted.' % n.get('seed')
            )
        r, a = _pooled_runs_at(prof, polarity, cut_f, cut_c)
        runs += r
        anys += a
    hist, anyhist = RD._hist(runs), RD._hist(anys)
    d_mr = RD._discrete_min_run(hist)
    d_ma = RD._discrete_min_run(anyhist)
    mr = max(int(shipped['min_run']), int(d_mr or 0))
    mra = max(int(shipped.get('min_run_any_sign') or mr), int(d_ma or 0), mr)
    ra, aa = _np.asarray(runs, float), _np.asarray(anys, float)
    return {
        'mode': mode,
        'n_seeds': len(seed_nulls),
        'seeds': [int(n['seed']) for n in seed_nulls],
        'per_seed': per_seed,
        'n_pools_pooled': int(len(runs)),
        'station_p99_frac': {
            'min': min(fr),
            'max': max(fr),
            'median': float(_np.median(fr)),
            'spread_frac': ((max(fr) - min(fr)) / min(fr) if min(fr) > 0 else None),
        },
        'station_p99_contrast': {'min': min(co), 'max': max(co), 'median': float(_np.median(co))},
        'cut': {
            'min_frac_stature': cut_f,
            'min_contrast': cut_c,
            'rule': "panel upper bound (max over seeds of that seed's own p99)",
        },
        'pooled_run_hist_at_cut': hist,
        'pooled_run_any_sign_hist_at_cut': anyhist,
        'discrete_min_run_at_cut': d_mr,
        'discrete_min_run_any_sign_at_cut': d_ma,
        'min_run': mr,
        'min_run_any_sign': mra,
        'shipped_panel_min_run': int(shipped['min_run']),
        'null_rate_any_run_at_cut': float(_np.mean(ra > 0)) if runs else 0.0,
        'null_rate_resolved_at_cut': (float(_np.mean((ra >= mr) | (aa >= mra))) if runs else 0.0),
        'null_rate_point_only_or_better_at_cut': (float(_np.mean(ra > 0)) if runs else 0.0),
        'rate_provenance': 'MEASURED BY RE-SCORING EVERY PANEL POOL AT THIS EXACT CUT',
    }


def level_null(
    v,
    faces,
    level,
    stature_m=None,
    n_point=None,
    n_pools=None,
    seed=20260806,
    seeds=LEVEL_NULL_SEED_PANEL,
    verbose=True,
):
    """Both nulls, measured on the mesh that is about to be probed.

    Returns {'point_null': curvature.relief_null(...), 'ridge_null': ridge.ridge_null(...),
             'headline': ...}. `point_null` is the estimator that produced the standing
     figure the cage-level result was judged against (p99 of |relief|/stature over random
     geodesic balls, and the p99 of |contrast|); `ridge_null` is the anisotropic-collar
     null the ridge primitive is scored on, and its target sizes are scaled by 4**level so
     the pools are the same PHYSICAL size as the cage's.

    NOTHING HERE IS ALLOWED TO SEE A LANDMARK. Both estimators sample the torso-and-limb
    skin mask, which excludes head, hands, feet and perineum, and neither is given any
    probe pool. That is what makes the number a false-positive calibration rather than a
    fit; if it were fitted, the direction of the fit would be to make our own bodies pass.
    """
    from zyg_workflows.geom.form import curvature as CV
    from zyg_workflows.geom.form import ridge as RD

    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    n_point = POINT_NULL_N_BY_LEVEL.get(int(level), 150) if n_point is None else n_point
    n_pools = NULL_POOLS_BY_LEVEL.get(int(level), 8) if n_pools is None else n_pools
    scale = 4 ** int(level)
    sizes = tuple(int(s * scale) for s in CAGE_NULL_TARGET_SIZES)

    t0 = time.time()
    pn = CV.relief_null(v, faces, n=int(n_point), stature_m=S, seed=seed)
    t_point = time.time() - t0
    if verbose:
        _zyg_log.info(
            '    point null  n=%d  %.0fs  p99 |relief|/S = %.4e   p99 |contrast| = %.3f'
            % (pn['n'], t_point, pn['abs_relief_frac']['p99'], pn['abs_contrast']['p99'])
        )

    # THE RIDGE NULL, OVER A SEED PANEL. See LEVEL_NULL_SEED_PANEL for why one draw is
    # not admissible here. `seed` stays in the signature and is kept as the panel's
    # REFERENCE draw (it is a member of the panel), so the single-draw number the previous
    # build reported is still visible beside the bound that supersedes it.
    panel_seeds = tuple(int(x) for x in (seeds if seeds else (seed,)))
    if int(seed) not in panel_seeds:
        panel_seeds = (int(seed),) + panel_seeds
    t0 = time.time()
    seed_nulls = []
    for sd in panel_seeds:
        rn_i = RD.ridge_null(
            v, faces, target_sizes=sizes, n_pools=int(n_pools), seed=int(sd), stature_m=S, collect_profiles=True
        )
        seed_nulls.append(rn_i)
        if verbose:
            for mode in ('ridge', 'point'):
                r = rn_i['by_mode'][mode]
                _zyg_log.info(
                    '    ridge null seed %-8d [%s] pools=%d  station p99 %.4e / %.3f'
                    % (sd, mode, r['n_pools'], r['abs_station_relief_frac']['p99'], r['abs_station_contrast']['p99'])
                )
    t_ridge = time.time() - t0
    rn = seed_nulls[panel_seeds.index(int(seed))]
    panel = {m: _panel_cut(seed_nulls, m) for m in ('ridge', 'point')}
    for n in seed_nulls:  # profiles are not serialisable and not needed
        for m in ('ridge', 'point'):
            n['by_mode'][m].pop('_profiles', None)
    if verbose:
        for mode in ('ridge', 'point'):
            pm = panel[mode]
            _zyg_log.info(
                '    LEVEL CUT [%s] panel of %d seeds, %d pools pooled: %.4e / %.3f '
                '(spread %.1f%%), min_run %d, null rate resolved AT THIS CUT %.3f'
                % (
                    mode,
                    pm['n_seeds'],
                    pm['n_pools_pooled'],
                    pm['cut']['min_frac_stature'],
                    pm['cut']['min_contrast'],
                    100.0 * (pm['station_p99_frac']['spread_frac'] or 0.0),
                    pm['min_run'],
                    pm['null_rate_resolved_at_cut'],
                )
            )
    return {
        'level': int(level),
        'stature_m': S,
        'seed': int(seed),
        'seeds': list(panel_seeds),
        'ridge_panel': panel,
        'target_sizes': list(sizes),
        'target_size_rule': 'ridge.RIDGE_NULL_P99["target_sizes"] * 4**level — matched '
        'by PHYSICAL patch size, not by vertex count',
        'n_pools_per_size': int(n_pools),
        'under_powered_vs_shipped_panel': bool(int(n_pools) < 320),
        'point_null': pn,
        'ridge_null': rn,
        'ridge_null_per_seed': seed_nulls,
        'point_null_is_one_draw': {
            'seed': int(seed),
            'note': 'the ISOTROPIC ball null is drawn ONCE, at the reference seed. It '
            'sets no threshold — the level cut comes from the ridge panel above '
            '— and it is reported as a diagnostic headline only. Its p99 is the '
            '3rd largest of a few hundred patches and does not fall '
            'monotonically with resolution; read the station cut, not this.',
        },
        'headline': {
            'abs_relief_frac_p99': pn['abs_relief_frac']['p99'],
            'abs_contrast_p99': pn['abs_contrast']['p99'],
            'n_patches': pn['n'],
            'radius_frac': pn['radius_frac'],
        },
        'seconds': {'point': t_point, 'ridge': t_ridge},
    }


def cuts_for(null, which='shipped'):
    """The per-mode cut a probe run is scored at. Two, and neither is tuned.

    'shipped' reproduces ridge.probe_pools exactly: ridge.station_cut() (the published
    isotropic p99 raised, never lowered, to the mode's own measured p99) with min_run
    floored at ridge.RIDGE_NULL_P99[mode]['min_run'] — the 24-seed, 23,040-pool panel
    value. This is the cut the published "0 of 20" was taken at.

    'level' uses the per-station p99 measured on landmark-free skin OF THIS MESH, without
    the cage floor. That floor is a property of the 13,718-vertex tessellation; carrying it
    onto a 219,368-vertex surface would score a different mesh at another mesh's noise
    level, which is not conservatism, it is a category error in the direction that happens
    to look safe. The RUN threshold keeps the panel floor and may only be raised by the
    level's own discrete estimate, because a smoother surface can plausibly carry LONGER
    chance runs and the level draws here are too thin to rule that out.

    TWO THINGS THE LEVEL BRANCH DOES THAT THE FIRST VERSION OF THIS FUNCTION DID NOT, both
    because a reviewer found the first version wrong:

      * IT IS A PANEL, NOT A DRAW. The station cut is the UPPER BOUND over
        LEVEL_NULL_SEED_PANEL, not one seed's p99. One draw at seed 20260806 — the seed
        ridge.py itself records as the uniquely most permissive of its 24 — moved 41% across
        seeds at level 2, which is more than enough to move a verdict.
      * THE CHANCE RATE IS MEASURED AT THE CUT THE PROBES ARE SCORED AT. It used to be
        copied from ridge_null's own frac_pools_resolved, which is measured at the cut
        FLOORED at the cage constants — i.e. 22% stricter on relief and 34% on contrast than
        the level cut whenever the level cut is the lower one, which is the entire premise
        of having a level cut. A resolution was therefore printed beside the chance rate of
        a test nobody ran. It is now re-scored over every panel pool at this exact cut.

    Both floors are enforced: LEVEL_CUT_ABSOLUTE_FLOOR_FRAC on relief and
    LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST on contrast. A station has to clear both axes, so
    guarding only one leaves half the test ungated.
    """
    from zyg_workflows.geom.form import ridge as RD

    out = {}
    rn = (null or {}).get('ridge_null') or {}
    for mode in ('ridge', 'point'):
        shipped = RD.RIDGE_NULL_P99[mode]
        c = RD.station_cut(rn or None, mode)
        nm = (rn.get('by_mode') or {}).get(mode) or {}
        live_run = nm.get('discrete_min_run')
        if live_run is None:
            live_run = nm.get('implied_min_run')
        live_any = nm.get('discrete_min_run_any_sign')
        if live_any is None:
            live_any = nm.get('implied_min_run_any_sign')
        min_run = max(int(shipped['min_run']), int(live_run or 0))
        min_any = max(int(shipped.get('min_run_any_sign') or shipped['min_run']), int(live_any or 0), min_run)
        if which == 'shipped':
            rec = {
                'min_frac_stature': c['min_frac_stature'],
                'min_contrast': c['min_contrast'],
                'source': c['source'] + ' | min_run from the 24-seed panel',
            }
        else:
            pm = ((null or {}).get('ridge_panel') or {}).get(mode)
            if not pm:
                raise ValueError(
                    'no seed panel in this null, so no level cut can be derived for mode '
                    '%r. A level cut taken from ONE draw is not admissible (see '
                    'LEVEL_NULL_SEED_PANEL); re-measure with level_null(), which draws the '
                    'panel and re-scores every pool at the resulting cut.' % mode
                )
            f = float(pm['cut']['min_frac_stature'])
            k = float(pm['cut']['min_contrast'])
            if f < LEVEL_CUT_ABSOLUTE_FLOOR_FRAC:
                raise ValueError(
                    'the level null for mode %r measured a per-station p99 of %.3e of '
                    'stature, below the %.1e refusal floor. That is not a noise floor, it '
                    'is a broken measurement — a mesh whose landmark-free skin reads under '
                    '0.2 mm of relief at the 99th percentile has either collapsed or been '
                    'sampled somewhere with no surface. Fix the measurement; do not score '
                    'a landmark against it.' % (mode, f, LEVEL_CUT_ABSOLUTE_FLOOR_FRAC)
                )
            if k < LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST:
                raise ValueError(
                    'the level null for mode %r measured a per-station CONTRAST p99 of '
                    '%.3e, below the %.1f refusal floor. A station must clear both axes, so '
                    'a collapsed contrast null would gate on relief alone at half the '
                    'intended test while still calling itself MEASURED-NULL. The lowest '
                    'contrast p99 ever measured on either body at any level is 2.148. Fix '
                    'the measurement; do not score a landmark against it.'
                    % (mode, k, LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST)
                )
            min_run = max(int(shipped['min_run']), int(pm['min_run'] or 0))
            min_any = max(
                int(shipped.get('min_run_any_sign') or shipped['min_run']), int(pm['min_run_any_sign'] or 0), min_run
            )
            rec = {
                'min_frac_stature': f,
                'min_contrast': k,
                'source': 'ridge.ridge_null measured AT THIS LEVEL (level %s), mode=%r, '
                '%d pools/size x %d seeds = %d pools pooled; station cut is '
                'the PANEL UPPER BOUND over seeds %s (per-seed p99 spread '
                '%.1f%%) — NOT floored at the cage constant and NOT one draw'
                % (
                    (null or {}).get('level'),
                    mode,
                    (null or {}).get('n_pools_per_size', 0),
                    pm['n_seeds'],
                    pm['n_pools_pooled'],
                    pm['seeds'],
                    100.0 * (pm['station_p99_frac']['spread_frac'] or 0.0),
                ),
            }
        if which == 'shipped':
            rate_res = nm.get('frac_pools_resolved', shipped.get('null_rate_resolved'))
            rate_pt = nm.get('frac_pools_point_only_or_better', shipped.get('null_rate_point_only_or_better'))
            rate_src = (
                'ridge.ridge_null frac_pools_* measured at the SHIPPED cut, which is the cut these probes are scored at'
            )
        else:
            rate_res = pm['null_rate_resolved_at_cut']
            rate_pt = pm['null_rate_point_only_or_better_at_cut']
            rate_src = pm['rate_provenance']
        rec.update(
            min_run=min_run,
            min_run_any_sign=min_any,
            provenance='MEASURED-NULL',
            null_rate_resolved=rate_res,
            null_rate_point_only_or_better=rate_pt,
            null_rate_measured_at={
                'min_frac_stature': rec['min_frac_stature'],
                'min_contrast': rec['min_contrast'],
                'min_run': int(min_run),
                'min_run_any_sign': int(min_any),
                'provenance': rate_src,
            },
            shipped_min_frac_stature=shipped['station_min_frac_stature'],
            shipped_min_contrast=shipped['station_min_contrast'],
            shipped_min_run=int(shipped['min_run']),
        )
        out[mode] = rec
    out['_which'] = which
    return out


def probe_at_cut(v, faces, pools, cuts, stature_m=None, areas=None, normals=None, curv=None, modes=('ridge', 'point')):
    """ridge.probe_pools, run at an EXPLICIT cut instead of at the shipped-floored one.

    Same primitives, same classifier, same records: ridge.ridge_search per mode and
    ridge._classify_probe for the verdict. The only thing this does not inherit is
    probe_pools' one-way floor on the station cut, which is the entire reason it exists —
    see cuts_for(). Everything that decides a verdict still comes from geom/form/ridge.py,
    so a change there changes this too and the two cannot silently diverge.
    """
    from zyg_workflows.geom.form import curvature as CV
    from zyg_workflows.geom.form import ridge as RD

    v = np.asarray(v, np.float64)
    pools = list(pools)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    ar = CV.mixed_voronoi_area(v, faces) if areas is None else np.asarray(areas)
    nv = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals)
    G = RD.build_graph(v, faces)
    out = {'_cuts': cuts}
    pcache = {}
    for name, kind, pol, pool, prov, ev in pools:
        rec = {
            'name': name,
            'kind': kind,
            'polarity': pol,
            'n_pool': int(len(pool)),
            'provenance': prov,
            'cuts': cuts,
            'resolves_relief': False,
            'resolution_class': 'empty_window',
        }
        if not len(pool):
            rec.update(
                status='EMPTY_WINDOW',
                empty_evidence=ev,
                resolution_why='NEVER PROBED: the window holds no vertex on this '
                'mesh. Not a flat reading and never counted as one.',
            )
            out[name] = rec
            continue
        for mode in modes:
            c = cuts[mode]
            rec[mode] = RD.ridge_search(
                v,
                faces,
                pool,
                polarity=pol,
                stature_m=S,
                areas=ar,
                normals=nv,
                graph=G,
                mode=mode,
                min_run=c['min_run'],
                min_run_any=c['min_run_any_sign'],
                point_cache=pcache,
                min_frac_stature=c['min_frac_stature'],
                min_contrast=c['min_contrast'],
            )
        if kind == 'facet':
            # ridge.body_pools emits kind='ridge' for all 20 body regions, so this cannot
            # fire today. It is a refusal rather than a silent omission because a facet
            # pool scored on the ridge primitive alone is UNDER-probed, and an under-probed
            # probe reported as 'below_null' is a false negative wearing a verdict.
            raise NotImplementedError(
                'probe_at_cut has no facet primitive; pool %r is kind=facet and would be '
                'scored on the curve primitives only. Use ridge.probe_pools, or add '
                'facet_flatness here at the same explicit cut.' % name
            )
        rec['status'] = 'ok'
        rec.update(RD._classify_probe(rec, modes))
        out[name] = rec
    return out
