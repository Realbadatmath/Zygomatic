# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""self_test() — primitives with a known answer, and controls that MUST fail.

Moved verbatim out of the old single-file ridge.py (lines 3093-3518).

`self_test` is the orchestrator; each `check_*` below is one section of the old
409-line body, in the order it ran. Every check writes its own entries into the
shared `out` dict and raises through `_require` exactly where it used to, so the
first failure is still reported at the same point in the sequence. The helpers stay
in this module rather than in a sibling because `selftest.py` is on the ratchet's
`print_calls` allowlist and the verbose dump at the end of `self_test` is the one
print in the file.
"""

import numpy as np

from zyg_workflows.geom.form.ridge.constants import (
    AFS_P63_REGIONS,
    AFS_P63_UNPROBED_ON_BODY,
    BELOW_NULL_VERDICTS,
    FAT_INVARIANT_PROBES,
    NO_VERDICT_VERDICTS,
    RESOLVED_VERDICTS,
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_P99,
    RIDGE_NULL_SEED_PANEL,
    STATION_MIN_CONTRAST,
    STATION_MIN_FRAC_STATURE,
    _require,
    _zyg_log,
    resolves_relief,
)
from zyg_workflows.geom.form.ridge.primitive import ridge_relief
from zyg_workflows.geom.form.ridge.facet_search import facet_flatness
from zyg_workflows.geom.form.ridge.null import _discrete_min_run, exceedance
from zyg_workflows.geom.form.ridge.probes import _resolution_contract, pool_overlaps
from zyg_workflows.geom.form.ridge.summary import fat_invariant_report, relief_summary


# ---------------------------------------------------------------------------------
# self test — primitives with a known answer, and controls that MUST fail
# ---------------------------------------------------------------------------------
def _ridge_grid(nx, ny, amp, sigma, scale=1.0, tilt=0.0):
    """A quad grid carrying a Gaussian ridge along +y, optionally on a tilted plane."""
    xs = np.linspace(-1, 1, nx)
    ys = np.linspace(-1, 1, ny)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    Z = amp * np.exp(-((X / sigma) ** 2)) + tilt * X
    V = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1) * scale
    i = np.arange(nx * ny).reshape(nx, ny)
    F = np.stack([i[:-1, :-1].ravel(), i[1:, :-1].ravel(), i[1:, 1:].ravel(), i[:-1, 1:].ravel()], axis=1)
    return V, F, i


def _ridge_probe(V, F, idx, polarity='either', *, nx, ny, grid_kw, **kw):
    """Run `ridge_relief` down the mid-column of a `_ridge_grid`, every third row a station.

    `nx`/`ny` are the grid's shape, `grid_kw` the cage fractions; a `scale=` keyword
    scales the nominal stature of 2.0 (the grid spans [-1, 1]) the same way
    `_ridge_grid(scale=…)` scales the vertices.
    """
    mid = nx // 2
    st = [int(idx[mid, j]) for j in range(2, ny - 2, 3)]
    S = 2.0 * kw.pop('scale', 1.0)
    return ridge_relief(V, F, st, stature_m=S, polarity=polarity, mode='ridge', **dict(grid_kw, **kw))


def _facet_probe(V, F, idx, nx):
    """Run `facet_flatness` over the 7x7 patch at the centre of an `nx`-square grid."""
    mid = nx // 2
    g = [int(idx[i, j]) for i in range(mid - 3, mid + 4) for j in range(mid - 3, mid + 4)]
    return facet_flatness(V, F, g, stature_m=2.0, gap_frac=0.05, width_frac=0.10)


def check_ridge_polarity(out, nx, ny, grid_kw):
    """A Gaussian ridge must read 'ridge', its mirror 'furrow', and both the same |relief|.

    Writes `ridge`, `furrow` and `polarity_agnostic` into `out` and returns the positive
    ridge's full `ridge_relief` record, which the resolution contract later re-reads.
    """
    V, F, idx = _ridge_grid(nx, ny, 0.05, 0.12)
    r = _ridge_probe(V, F, idx, 'protrusion', nx=nx, ny=ny, grid_kw=grid_kw)
    out['ridge'] = {
        k: r[k] for k in ('verdict', 'longest_run', 'n_measured', 'peak_relief_mm', 'peak_contrast', 'sign_changes')
    }
    _require(r['verdict'] == 'ridge', 'a Gaussian ridge came back %r' % r['verdict'])
    _require(
        r['longest_run'] >= r['n_measured'] - 1,
        'ridge run %d of %d measured stations — the profile is not continuous' % (r['longest_run'], r['n_measured']),
    )

    V2, F2, idx2 = _ridge_grid(nx, ny, -0.05, 0.12)
    r2 = _ridge_probe(V2, F2, idx2, 'depression', nx=nx, ny=ny, grid_kw=grid_kw)
    out['furrow'] = {k: r2[k] for k in ('verdict', 'longest_run', 'peak_relief_mm')}
    _require(r2['verdict'] == 'furrow', 'a Gaussian furrow came back %r' % r2['verdict'])

    ra = _ridge_probe(V, F, idx, 'either', nx=nx, ny=ny, grid_kw=grid_kw)
    rb = _ridge_probe(V2, F2, idx2, 'either', nx=nx, ny=ny, grid_kw=grid_kw)
    out['polarity_agnostic'] = {
        'ridge_abs_peak_mm': abs(ra['peak_relief_mm']),
        'furrow_abs_peak_mm': abs(rb['peak_relief_mm']),
        'rel_diff': abs(abs(ra['peak_relief_mm']) - abs(rb['peak_relief_mm'])) / abs(ra['peak_relief_mm']),
        'ridge_run': ra['longest_run'],
        'furrow_run': rb['longest_run'],
        'ridge_sign': ra['run_sign'],
        'furrow_sign': rb['run_sign'],
    }
    _require(
        out['polarity_agnostic']['rel_diff'] < 1e-9,
        'polarity-agnostic mode scores a furrow differently from the mirror ridge: %.3e'
        % out['polarity_agnostic']['rel_diff'],
    )
    _require(
        ra['longest_run'] == rb['longest_run'] and ra['run_sign'] == -rb['run_sign'],
        'the mirror pair disagree on run length or sign',
    )
    return r


def check_flat_controls(out, nx, ny, grid_kw):
    """The three surfaces that must NOT be claimed: a plane, a tilted plane, a sub-floor ridge.

    Writes `control_plane`, `control_tilted_plane` and `control_below_floor` into `out`
    and returns the three records as `(rp, rt, rw)` for the resolution contract.
    """
    # CONTROLS
    Vp, Fp, idxp = _ridge_grid(nx, ny, 0.0, 0.12)
    rp = _ridge_probe(Vp, Fp, idxp, 'either', nx=nx, ny=ny, grid_kw=grid_kw)
    out['control_plane'] = {k: rp[k] for k in ('verdict', 'longest_run', 'peak_relief_mm', 'peak_contrast')}
    _require(
        rp['verdict'] in ('flat', 'unmeasurable'), 'A PLANE WAS CALLED %r. The gate is not calibrated.' % rp['verdict']
    )

    Vt, Ft, idxt = _ridge_grid(nx, ny, 0.0, 0.12, tilt=0.25)
    rt = _ridge_probe(Vt, Ft, idxt, 'either', nx=nx, ny=ny, grid_kw=grid_kw)
    out['control_tilted_plane'] = {k: rt[k] for k in ('verdict', 'longest_run', 'peak_relief_mm')}
    _require(
        rt['verdict'] in ('flat', 'unmeasurable'),
        'A TILTED PLANE WAS CALLED %r — a first-order trend is leaking into relief.' % rt['verdict'],
    )

    # a ridge one tenth the amplitude: below the cage's own floor, must NOT be claimed
    Vw, Fw, idxw = _ridge_grid(nx, ny, 0.0018, 0.12)  # 0.9e-3 of "stature" 2.0
    rw = _ridge_probe(Vw, Fw, idxw, 'either', nx=nx, ny=ny, grid_kw=grid_kw)
    out['control_below_floor'] = {k: rw[k] for k in ('verdict', 'longest_run', 'peak_relief_mm')}
    _require(
        rw['verdict'] in ('flat', 'point_only', 'unmeasurable'),
        'a ridge at 0.9e-3 of stature (below the measured 2.45e-3 floor) was called %r' % rw['verdict'],
    )
    return rp, rt, rw


def check_scale_invariance(out, nx, ny, grid_kw):
    """Stature-normalised relief must be identical at the two statures that ship.

    Writes `scale` into `out`; the same geometry is measured at 1.52 m and 1.85 m and
    the stature-normalised peaks must agree to 1e-9.
    """
    # scale invariance at the two statures that ship
    a = _ridge_probe(
        *_ridge_grid(nx, ny, 0.05, 0.12, scale=1.52 / 2.0),
        polarity='either',
        nx=nx,
        ny=ny,
        grid_kw=grid_kw,
        scale=1.52 / 2.0,
    )
    b = _ridge_probe(
        *_ridge_grid(nx, ny, 0.05, 0.12, scale=1.85 / 2.0),
        polarity='either',
        nx=nx,
        ny=ny,
        grid_kw=grid_kw,
        scale=1.85 / 2.0,
    )
    fa = a['peak_relief_mm'] / (a['stature_m'] * 1000.0)
    fb = b['peak_relief_mm'] / (b['stature_m'] * 1000.0)
    out['scale'] = {
        'frac_at_1.52': fa,
        'frac_at_1.85': fb,
        'rel_diff': abs(fa - fb) / abs(fb),
        'verdict_1.52': a['verdict'],
        'verdict_1.85': b['verdict'],
        'run_1.52': a['longest_run'],
        'run_1.85': b['longest_run'],
    }
    _require(
        out['scale']['rel_diff'] < 1e-9,
        'stature-normalised ridge relief is not scale invariant: %.3e' % out['scale']['rel_diff'],
    )
    _require(
        a['verdict'] == b['verdict'] == 'ridge' and a['longest_run'] == b['longest_run'],
        "self-check failed: a['verdict'] == b['verdict'] == 'ridge' and a['longest_run'] == b['longest_run']",
    )


def check_facet_gate(out, nx):
    """A flat crown inside a curved surround is a facet; the same crown raised is a bump.

    Writes `facet_flat_crown` and `control_facet_is_bump` into `out`.
    """
    # facet: a flat patch inside a curved surround is a facet; the same patch raised is not
    # A QUARTIC dome, z = a(1 - r^4): curvature is exactly zero at the crown and grows
    # outward, so the crown is a genuine flat facet inside a curved surround and the whole
    # surface is smooth. A dome with a CLIPPED crown was tried first and is wrong — the clip
    # leaves a crease at the facet's edge, the crease lands in the patch, and the test then
    # measures the crease: measured, it returned 'not_flatter' on a surface whose interior
    # is exactly planar.
    xs = np.linspace(-1, 1, nx)
    X, Y = np.meshgrid(xs, xs, indexing='ij')
    R2 = X * X + Y * Y
    Zd = 0.12 * (1.0 - R2 * R2)
    Vd = np.stack([X.ravel(), Y.ravel(), Zd.ravel()], axis=1)
    i = np.arange(nx * nx).reshape(nx, nx)
    Fd = np.stack([i[:-1, :-1].ravel(), i[1:, :-1].ravel(), i[1:, 1:].ravel(), i[:-1, 1:].ravel()], axis=1)
    f1 = _facet_probe(Vd, Fd, i, nx)
    out['facet_flat_crown'] = {
        k: f1.get(k)
        for k in ('verdict', 'relief_mm', 'curvedness_ratio', 'planarity_ratio', 'curvedness_norm_var_patch')
    }
    _require(f1['verdict'] == 'facet', 'a flattened crown came back %r' % f1['verdict'])

    Zb = Zd + 0.05 * np.exp(-R2 / 0.02)
    Vb = np.stack([X.ravel(), Y.ravel(), Zb.ravel()], axis=1)
    f2 = _facet_probe(Vb, Fd, i, nx)
    out['control_facet_is_bump'] = {
        k: f2.get(k) for k in ('verdict', 'relief_mm', 'contrast', 'curvedness_ratio', 'planarity_ratio')
    }
    _require(
        f2['verdict'] == 'bump',
        'A BUMP WAS CALLED %r BY THE FACET TEST. The facet gate is not calibrated.' % f2['verdict'],
    )


def check_resolution_contract(out, r, rp, rt, rw):
    """No below-null verdict may count as resolving, and min_run must sit above the null p99.

    `r`/`rp`/`rt`/`rw` are the records from `check_ridge_polarity` and
    `check_flat_controls`; writes `resolution_contract` into `out`.
    """
    # ---------------------------------------------------------------------------
    # THE RESOLUTION CONTRACT. These assertions exist because the defect they guard
    # against already shipped: a consumer listed the verdict strings itself and included
    # 'point_only', which ridge_relief defines as run_len < min_run and min_run is the
    # null's p99 + 1 — i.e. it included the null in the result.
    # ---------------------------------------------------------------------------
    _require(
        'point_only' not in RESOLVED_VERDICTS and 'flat' not in RESOLVED_VERDICTS,
        'A BELOW-NULL VERDICT IS IN RESOLVED_VERDICTS. min_run is the null p99 + 1, so '
        'every verdict below it is inside the measured null and resolves nothing.',
    )
    _require(
        not resolves_relief('point_only') and not resolves_relief('flat') and not resolves_relief('unmeasurable'),
        'resolves_relief admits a below-null verdict',
    )
    _require(
        all(resolves_relief(x) for x in RESOLVED_VERDICTS),
        'self-check failed: all(resolves_relief(x) for x in RESOLVED_VERDICTS)',
    )
    try:
        resolves_relief('probably_a_clavicle')
        raise AssertionError('resolves_relief accepted an unknown verdict instead of refusing to classify it')
    except ValueError as _exc:
        _zyg_log.debug('resolves_relief refused the unknown verdict, as the control requires: %s', _exc)
    out['resolution_contract'] = {
        'resolved': sorted(RESOLVED_VERDICTS),
        'below_null': sorted(BELOW_NULL_VERDICTS),
        'no_verdict': sorted(NO_VERDICT_VERDICTS),
        'point_only_null_rate_ridge_mode': RIDGE_NULL_P99['ridge']['null_rate_point_only_or_better'],
        'resolved_null_rate_ridge_mode': RIDGE_NULL_P99['ridge']['null_rate_resolved'],
    }
    _require(
        r['resolves_relief'] is True and r['verdict_class'] == 'resolved',
        'the positive Gaussian ridge does not report itself as resolving',
    )
    _require(
        rw['resolves_relief'] is False,
        'the below-floor control reports resolves_relief=True at verdict %r' % rw['verdict'],
    )
    _require(
        rp['resolves_relief'] is False and rt['resolves_relief'] is False, 'a plane reports itself as resolving relief'
    )
    # The null's own support may not be reachable by a resolving verdict: min_run must sit
    # strictly above the measured p99 in every mode, and the any-sign run must be scored
    # against the any-sign null rather than the same-sign one.
    for _m in ('ridge', 'point'):
        _d = RIDGE_NULL_P99[_m]
        _require(
            _d['min_run'] == _d['null_p99_run'] + 1,
            'mode %r min_run %d is not the measured null p99 (%d) + 1'
            % (
                _m,
                _d['min_run'],
                _d['null_p99_run'],
            ),
        )
        _require(
            _d['min_run_any_sign'] == _d['null_p99_run_any_sign'] + 1,
            'mode %r min_run_any_sign is not read off the ANY-SIGN null' % _m,
        )


def _check_null_mode(_m):
    """Re-derive one mode's shipped thresholds from the panel histograms shipped beside them.

    `_m` is 'ridge' or 'point'; raises through `_require` on any disagreement between
    `RIDGE_NULL_P99[_m]`'s constants and its own pooled/panel counts.
    """
    _d = RIDGE_NULL_P99[_m]
    _H, _HA = _d['pooled_run_hist'], _d['pooled_run_hist_any_sign']
    _require(
        sum(_H.values()) == sum(_HA.values()) == RIDGE_NULL_P99['derivation']['pools_scored'],
        'mode %r pooled histogram does not hold the declared pool count' % _m,
    )
    _require(
        _discrete_min_run(_H) == _d['pooled_min_run'],
        'mode %r pooled_min_run %s disagrees with its own histogram (%s)'
        % (_m, _d['pooled_min_run'], _discrete_min_run(_H)),
    )
    _require(
        _discrete_min_run(_HA) == _d['pooled_min_run_any_sign'],
        'mode %r pooled_min_run_any_sign disagrees with its own any-sign histogram' % _m,
    )
    # THE ONE-WAY RULE. The shipped value is the panel upper bound, so it must be at
    # least the pooled point estimate and at least the worst seed on the panel. Being
    # BELOW either is the failure mode this whole re-derivation exists to prevent.
    _require(
        _d['min_run'] >= _d['pooled_min_run'],
        'mode %r ships min_run %d BELOW the pooled estimate %d — that is the permissive '
        'direction and it manufactures landmarks' % (_m, _d['min_run'], _d['pooled_min_run']),
    )
    _require(
        _d['min_run'] == max(_d['panel_min_run_hist']),
        'mode %r ships min_run %d but the panel upper bound is %d' % (_m, _d['min_run'], max(_d['panel_min_run_hist'])),
    )
    _require(
        sum(_d['panel_min_run_hist'].values()) == len(RIDGE_NULL_SEED_PANEL),
        'mode %r panel histogram does not cover all %d seeds' % (_m, len(RIDGE_NULL_SEED_PANEL)),
    )
    # The FPR the shipped threshold actually buys must be inside the advertised alpha,
    # and the rate one step BELOW it must not be, or the threshold is needlessly strict.
    _fpr = exceedance(_HA, _d['min_run'])
    _require(
        _fpr <= RIDGE_NULL_ALPHA,
        'mode %r min_run %d carries a measured FPR of %.4f, above alpha %.3f'
        % (
            _m,
            _d['min_run'],
            _fpr,
            RIDGE_NULL_ALPHA,
        ),
    )
    _require(
        abs(_d['null_rate_resolved'] - _fpr) < 1e-9,
        'mode %r null_rate_resolved does not match its own histogram' % _m,
    )
    _require(
        abs(_d['null_rate_point_only_or_better'] - exceedance(_H, 1)) < 1e-9,
        'mode %r null_rate_point_only_or_better does not match its own histogram' % _m,
    )
    # The station cut ships the panel MAX and may never sit below the isotropic floor.
    _lo, _med, _hi = _d['panel_cut_frac_min_median_max']
    _require(_lo <= _med <= _hi, 'mode %r panel cut triple is not ordered' % _m)
    _require(_d['station_min_frac_stature'] == _hi, 'mode %r ships a station cut that is not the panel maximum' % _m)
    _require(
        _d['station_min_frac_stature'] >= STATION_MIN_FRAC_STATURE,
        'mode %r station cut fell BELOW curvature.RELIEF_NULL_P99, which this module may never do' % _m,
    )
    _require(
        _d['station_min_contrast'] >= STATION_MIN_CONTRAST,
        'mode %r contrast cut fell below the published isotropic floor' % _m,
    )


def check_null_derivation(out):
    """The shipped constants must agree with the evidence shipped beside them.

    Re-derives both modes through `_check_null_mode`, holds the superseded ridge value
    on the record, and writes `null_derivation` into `out`.
    """
    # ---------------------------------------------------------------------------
    # THE SHIPPED CONSTANT MUST AGREE WITH THE EVIDENCE SHIPPED BESIDE IT.
    # RIDGE_NULL_P99 carries the pooled panel histograms it was read off. These assertions
    # recompute the threshold FROM those counts, so a hand-edited min_run or a threshold
    # nudged to keep a landmark alive fails here instead of passing quietly. This is the
    # defect that shipped: a constant nobody could check without re-running 23,040 pools.
    # ---------------------------------------------------------------------------
    for _m in ('ridge', 'point'):
        _check_null_mode(_m)
    # The superseded value must stay on the record with the FPR it really carried, so the
    # comparison cannot quietly disappear the next time this file is edited.
    _sup = RIDGE_NULL_P99['ridge']['superseded']
    _require(
        _sup
        and _sup['min_run'] < RIDGE_NULL_P99['ridge']['min_run']
        and _sup['measured_false_positive_rate'] > RIDGE_NULL_ALPHA,
        'the superseded ridge constant and the rate it actually carried must stay recorded',
    )
    out['null_derivation'] = {
        'seeds': len(RIDGE_NULL_SEED_PANEL),
        'pools_scored': RIDGE_NULL_P99['derivation']['pools_scored'],
        'rule': RIDGE_NULL_P99['derivation']['rule'],
        'ridge_min_run': RIDGE_NULL_P99['ridge']['min_run'],
        'ridge_fpr': exceedance(
            RIDGE_NULL_P99['ridge']['pooled_run_hist_any_sign'], RIDGE_NULL_P99['ridge']['min_run']
        ),
        'superseded_ridge_min_run': _sup['min_run'],
        'superseded_fpr': _sup['measured_false_positive_rate'],
    }


def check_roster_and_summary(out):
    """AFS p.63's denominator must stay whole, and a never-probed window must be visible.

    Writes `afs_p63` and `summary_sentence_control` into `out`.
    """
    # AFS p.63's denominator must stay whole: eight named regions, the unprobed ones named.
    _require(len(AFS_P63_REGIONS) == 8, 'AFS p.63 names eight regions; the roster carries %d' % len(AFS_P63_REGIONS))
    _require(
        AFS_P63_UNPROBED_ON_BODY == ('facial_mask', 'nape', 'spine_midline'),
        'the unprobed p.63 regions changed: %s' % (AFS_P63_UNPROBED_ON_BODY,),
    )
    _require(
        len(FAT_INVARIANT_PROBES) == len(set(FAT_INVARIANT_PROBES)), 'a probe appears twice in the fat-invariant roster'
    )
    _require(
        all(r or n for _reg, r, _h, n in AFS_P63_REGIONS),
        'a p.63 region has neither a probe nor a stated reason for having none',
    )
    out['afs_p63'] = {
        'n_page_regions': len(AFS_P63_REGIONS),
        'n_body_probes': len(FAT_INVARIANT_PROBES),
        'unprobed_on_body': list(AFS_P63_UNPROBED_ON_BODY),
    }

    # A never-probed window must be visible in the summary sentence, and distinct from a
    # window that was probed and found flat. Built as a synthetic record set so the
    # assertion holds without a mesh.
    synth = {
        '_cuts': {'ridge': {}, 'point': {}, '_resolution_contract': _resolution_contract({}, ())},
        'probed_flat': {
            'status': 'ok',
            'resolves_relief': False,
            'resolution_class': 'below_null',
            'resolution_verdict': 'flat',
        },
        'probed_point_only': {
            'status': 'ok',
            'resolves_relief': False,
            'resolution_class': 'below_null',
            'resolution_verdict': 'point_only',
        },
        'never_probed_window': {'status': 'EMPTY_WINDOW', 'resolves_relief': False, 'resolution_class': 'empty_window'},
    }
    su = relief_summary(synth, scope='body')
    _require(
        su['n_resolved'] == 0 and su['n_never_probed'] == 1 and su['n_below_null'] == 2,
        "self-check failed: su['n_resolved'] == 0 and su['n_never_probed'] == 1 and su['n_below_null'] == 2",
    )
    _require(
        'never_probed_window' in su['sentence'], 'the summary sentence does not name the window that was never probed'
    )
    _require(
        'NEVER PROBED' in su['sentence'] and 'point_only' in su['sentence'],
        "self-check failed: 'NEVER PROBED' in su['sentence'] and 'point_only' in su['sentence']",
    )
    out['summary_sentence_control'] = {
        'n_resolved': su['n_resolved'],
        'n_never_probed': su['n_never_probed'],
        'names_the_empty_window': True,
    }


def check_census_controls(out):
    """Overlapping windows are not independent observations, and a census says when it is broken.

    Writes `independence_control` and `fat_invariant_incomplete_control` into `out`.
    """
    # Overlap accounting: three windows, two of which share a vertex, are two separated
    # regions of skin and at most two independent observations — not three.
    fake = [
        ('a', 'ridge', 'either', np.array([1, 2, 3]), '', None),
        ('b', 'ridge', 'either', np.array([3, 4, 5]), '', None),
        ('c', 'ridge', 'either', np.array([9, 10]), '', None),
    ]
    ov = pool_overlaps(fake)
    _require(
        ov['n_windows'] == 3 and ov['n_disjoint_clusters'] == 2 and ov['max_disjoint_windows'] == 2,
        'pool_overlaps miscounted independence: %s' % ov,
    )
    out['independence_control'] = {
        'n_windows': ov['n_windows'],
        'clusters': ov['n_disjoint_clusters'],
        'max_disjoint': ov['max_disjoint_windows'],
    }

    # The body census must refuse a head probe set outright rather than quietly counting
    # report-only head windows towards a body result.
    try:
        fat_invariant_report({'zygomatic_arch': {'status': 'ok'}, 'nasal_bone': {'status': 'ok'}})
        raise AssertionError('fat_invariant_report accepted a HEAD probe set')
    except ValueError as _exc:
        _zyg_log.debug('fat_invariant_report refused the head probe set, as the control requires: %s', _exc)

    # A roster probe missing from the probe set must be declared a broken census, not
    # silently counted as a landmark the cage failed to carry.
    fi = fat_invariant_report(
        {
            'clavicle_shaft': {
                'status': 'ok',
                'resolves_relief': False,
                'resolution_class': 'below_null',
                'resolution_verdict': 'flat',
            }
        }
    )
    _require(
        fi['n_probes_absent_from_set'] == len(FAT_INVARIANT_PROBES) - 1 and 'CENSUS INCOMPLETE' in fi['sentence'],
        'a fat-invariant census with missing probes did not declare itself incomplete',
    )
    out['fat_invariant_incomplete_control'] = {
        'absent': fi['n_probes_absent_from_set'],
        'declared': 'CENSUS INCOMPLETE',
    }


def self_test(verbose=True):
    """Prove the primitive rather than assert it, and prove it REFUSES the controls.

    Positive: a Gaussian ridge must come back 'ridge' with a full-length run; the identical
    surface negated must come back 'furrow' with the SAME |relief| under polarity='either'.
    Controls that must NOT pass, because a gate that has never failed anything is not
    calibrated (plan section 3, calibration policy 3): a PLANE must not be a ridge, a TILTED
    plane must not be a ridge (a first-order trend is what the quadric collar is for), and a
    bump must not be a facet. Scale invariance is checked at the two statures that ship.
    """
    out = {}
    NX, NY = 41, 41
    # geometry in grid units: the grid spans [-1,1], "stature" is 2.0 unless scaled.
    gk = dict(core_frac=0.03, gap_frac=0.06, width_frac=0.12, along_stations=3)

    r = check_ridge_polarity(out, NX, NY, gk)
    rp, rt, rw = check_flat_controls(out, NX, NY, gk)
    check_scale_invariance(out, NX, NY, gk)
    check_facet_gate(out, NX)
    check_resolution_contract(out, r, rp, rt, rw)
    check_null_derivation(out)
    check_roster_and_summary(out)
    check_census_controls(out)

    if verbose:
        for k in sorted(out):
            print(
                '  %-24s %s' % (k, {kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in out[k].items()})
            )
    return out
