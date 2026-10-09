# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reporting — the before/after table — and the module CLI.

Moved verbatim out of the old single-file ridge.py (lines 3519-4074).
"""

import sys

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    RESOLVED_VERDICTS,
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_P99,
    RIDGE_NULL_PANEL_N_POOLS,
    RIDGE_NULL_SEED_PANEL,
    SEARCH_N_DIRECTIONS,
    SEARCH_N_OFFSETS,
    _zyg_log,
)
from zyg_workflows.geom.form.ridge.null import ridge_null, ridge_null_sweep
from zyg_workflows.geom.form.ridge.probes import body_pools, head_pools
from zyg_workflows.geom.form.ridge.summary import probe_pools, relief_summary
from zyg_workflows.geom.form.ridge.selftest import self_test


# ---------------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------------
def _fmt_res(r):
    if r is None or r.get('status') != 'ok':
        return '%-13s %5s %6s %8s %8s' % ((r or {}).get('status', '-'), '-', '-', '-', '-')
    x = r['result']
    # A trailing '*' marks a verdict INSIDE the measured null. Nothing carrying it may be
    # counted as a resolution, and the table says so on the row rather than in a legend
    # nobody reads.
    return '%-13s %5d %6.3f %+8.2f %+8.2f' % (
        x['verdict'] + ('' if x['resolves_relief'] else '*'),
        x['longest_run'],
        x['run_span_frac_stature'],
        x['peak_relief_mm'] if x['peak_relief_mm'] is not None else float('nan'),
        x['peak_contrast'] if x['peak_contrast'] is not None else float('nan'),
    )


def report_table(recs, title='', show_canon=True):
    """One line per probe: the point primitive, then the ridge primitive, then the verdict
    change. This is the before/after the whole exercise exists to produce."""
    lines = []
    hdr = '%-32s %5s | %-13s %5s %6s %8s %8s | %-13s %5s %6s %8s %8s | %s' % (
        'probe',
        'pool',
        'POINT verdict',
        'run',
        'span',
        'peak_mm',
        'contr',
        'RIDGE verdict',
        'run',
        'span',
        'peak_mm',
        'contr',
        'change',
    )
    if title:
        lines.append(title)
    cuts = recs.get('_cuts')
    span_p99 = None
    if cuts:
        for mode in sorted(k for k in cuts if not k.startswith('_')):
            c = cuts[mode]
            lines.append(
                '  cut in force for %-6s |relief| >= %.3e of stature, |contrast| '
                '>= %.2f, run >= %d (any-sign run >= %d)   [%s]'
                % (
                    mode,
                    c['min_frac_stature'],
                    c['min_contrast'],
                    c['min_run'],
                    c.get('min_run_any_sign', c['min_run']),
                    c['source'],
                )
            )
            lines.append(
                '    measured chance rate on landmark-free skin: %s reaches a '
                'RESOLVING run, %s reaches point_only or better'
                % (_pct(c.get('null_rate_resolved')), _pct(c.get('null_rate_point_only_or_better')))
            )
        contract = cuts.get('_resolution_contract') or {}
        lines.append(
            '  RESOLVES = verdict in %s. point_only and flat are INSIDE the null '
            'and resolve nothing (marked * below); EMPTY_WINDOW was never probed. '
            'Scored under %d modes, so the union chance rate of a resolution is '
            '%s and of "resolution or point_only" is %s.'
            % (
                sorted(RESOLVED_VERDICTS),
                len(contract.get('modes_tried') or ()),
                _pct(contract.get('null_rate_resolved_either_mode')),
                _pct(contract.get('null_rate_point_only_or_better_either_mode')),
            )
        )
        span_p99 = (cuts.get('ridge') or {}).get('null_run_span_p99')
        if span_p99:
            lines.append(
                '  a run whose ARC is at or below %.4f of stature (the null p99 '
                'of run span) is flagged SHORT-ARC: its stations are adjacent '
                'vertices, i.e. a cluster rather than a whole-bone curve' % span_p99
            )
        elif span_p99 is not None:
            lines.append(
                '  null p99 of run span is 0.0000 of stature — random skin under '
                'this search almost never produced a run of 2 stations at all, so '
                'no span threshold can be derived from it and the span column '
                'must be read by eye: a 2 mm "run" is two adjacent vertices, not '
                'a whole-bone curve, whatever its run count says'
            )
    lines.append(hdr)
    lines.append('-' * len(hdr))
    gained, lost, same, unmeasurable, stronger = [], [], [], [], []
    for name in recs:
        if name.startswith('_'):
            continue
        r = recs[name]
        if r['status'] != 'ok':
            unmeasurable.append(name)
            lines.append(
                '%-32s %5d | %-18s %s'
                % (name, r['n_pool'], r['status'], 'UNMEASURABLE — no vertex of this cage satisfies the window')
            )
            ev = r.get('empty_evidence') or {}
            if ev:
                lines.append(
                    '%-32s       per-constraint survivors %s'
                    % ('', {k[10:]: v for k, v in ev.items() if k.startswith('n_passing_')})
                )
                if 'cage_x_frac_in_band' in ev:
                    lines.append(
                        '%-32s       in the fz band the cage spans x %s, y %s of '
                        'stature; the window asks for x %s, y %s'
                        % (
                            '',
                            ev['cage_x_frac_in_band'],
                            ev['cage_y_frac_in_band'],
                            ev['window_x_frac'],
                            ev['window_y_frac'],
                        )
                    )
            continue
        p, g = r.get('point'), r.get('ridge')
        pv = p['result']['verdict'] if p and p.get('status') == 'ok' else '-'
        gv = g['result']['verdict'] if g and g.get('status') == 'ok' else '-'
        if (p or {}).get('status') == 'no_candidates':
            lines.append('%-32s %5d | UNMEASURABLE — %s' % (name, r['n_pool'], p.get('why')))
            unmeasurable.append(name)
            continue
        # THE resolution set, read from the module constant. Never re-listed here: this
        # line is the exact one an adapter got wrong by adding 'point_only' to it.
        strong = RESOLVED_VERDICTS
        pr = p['result']['longest_run'] if p and p.get('status') == 'ok' else 0
        gr = g['result']['longest_run'] if g and g.get('status') == 'ok' else 0
        short = (
            gv in strong
            and span_p99 is not None
            and g
            and g.get('status') == 'ok'
            and g['result']['run_span_frac_stature'] <= span_p99
        )
        if gv in strong and pv not in strong:
            change, tgt = 'GAINED' + (' SHORT-ARC' if short else ''), gained
        elif pv in strong and gv not in strong:
            change, tgt = 'lost', lost
        elif gv in strong and pv in strong and gr > pr:
            change, tgt = ('stronger (run %d->%d)%s' % (pr, gr, ' SHORT-ARC' if short else ''), stronger)
        else:
            change, tgt = '', same
        tgt.append(name)
        lines.append('%-32s %5d | %s | %s | %s' % (name, r['n_pool'], _fmt_res(p), _fmt_res(g), change))
        if gv in strong and g and g.get('status') == 'ok':
            x = g['result']
            lines.append(
                '%-32s       the run that carries it: %s  (weakest station '
                '%.2f mm at contrast %.2f; arc %.1f mm; %d sign changes over the '
                'whole curve)'
                % (
                    '',
                    ' '.join(
                        '[v%d %+.2fmm c%+.2f]' % (s['vertex'], s['relief_mm'], s['contrast']) for s in x['run_stations']
                    ),
                    x['run_min_abs_relief_mm'],
                    x['run_min_abs_contrast'],
                    x['run_span_m'] * 1000.0,
                    x['sign_changes'],
                )
            )
        if show_canon and r.get('canon'):
            c = r['canon']
            lines.append(
                '%-32s       canon target %s %+0.1e of stature (%s) — REPORT ONLY'
                % ('', c['kind'], c['sign'] * c['frac'], c['src'])
            )
        if r.get('facet'):
            f = r['facet']
            lines.append(
                '%-32s       facet: %-13s relief %s mm (contrast %s)  curvedness '
                'patch/collar %s [skin-null pct %s]  planarity %s'
                % (
                    '',
                    f.get('verdict'),
                    _n(f.get('relief_mm')),
                    _n(f.get('contrast')),
                    _n(f.get('curvedness_ratio'), 3),
                    f.get('null_percentile', '-'),
                    _n(f.get('planarity_ratio'), 4),
                )
            )
    lines.append(
        'resolved as RIDGE/FURROW/STRIP by the curve primitive but not by the '
        'point primitive: %d %s' % (len(gained), sorted(gained))
    )
    lines.append('resolved by both, longer run under the curve primitive: %d %s' % (len(stronger), sorted(stronger)))
    lines.append(
        'UNMEASURABLE by either primitive (empty or untessellated window): %d %s'
        % (len(unmeasurable), sorted(unmeasurable))
    )

    # THE HEADLINE, from the module's own classification rather than from this function's
    # local bookkeeping — and always split out by class, so a never-probed window can never
    # be silently folded into a flat one.
    summ = recs.get('_summary') or relief_summary(recs)
    lines.append('')
    lines.append('  ' + summ['sentence'])
    if summ['point_only']:
        lines.append('  point_only (INSIDE the null, resolves nothing): %s' % ', '.join(summ['point_only']))
    if summ['never_probed']:
        lines.append(
            '  NEVER PROBED — no vertex of this cage falls in the window, so no '
            'primitive ran and there is no reading of any kind: %s' % ', '.join(summ['never_probed'])
        )
    ind = recs.get('_independence')
    if ind:
        lines.append('  INDEPENDENCE: %s' % ind['note'])
        for pr in ind['pairs'][:8]:
            lines.append(
                '     %-24s n %-24s shared %4d = %.1f%% of the smaller'
                % (pr['a'], pr['b'], pr['n_shared'], 100.0 * pr['frac_of_smaller'])
            )
        for sp in ind.get('shared_peak_vertices') or ():
            lines.append(
                '     SAME PEAK VERTEX v%d in mode %s: %s — one bump credited to '
                '%d landmarks' % (sp['vertex'], sp['mode'], ', '.join(sp['probes']), len(sp['probes']))
            )
    fi = recs.get('_fat_invariant')
    if fi:
        lines.append('  AFS p.63: ' + fi['sentence'])
        for row in fi['regions']:
            if not row['probed_on_body']:
                lines.append('     %-18s %s' % (row['page_region'], row['note']))
            else:
                lines.append(
                    '     %-18s %d/%d resolve  [%s]%s'
                    % (
                        row['page_region'],
                        row['n_resolved'],
                        len(row['probes']),
                        ', '.join('%s:%s' % (x['probe'], x['verdict'] or x['class']) for x in row['probes']),
                        ('  ' + row['note']) if row['note'] else '',
                    )
                )
    return '\n'.join(lines), {
        'gained': gained,
        'lost': lost,
        'same': same,
        'stronger': stronger,
        'unmeasurable': unmeasurable,
        'summary': summ,
        'fat_invariant': fi,
        'independence': ind,
    }


def _n(x, nd=2):
    return '%.*f' % (nd, x) if isinstance(x, float) and np.isfinite(x) else '-'


def _pct(x):
    return '-' if x is None else '%.2f%%' % (100.0 * float(x))


def main(argv=None):
    try:
        import torch

        torch.set_num_threads(4)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('torch thread cap skipped: %s', _exc)
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'probe'

    print('=== ridge self-test on primitives (and the controls that must fail) ===')
    self_test()
    if cmd == 'selftest':
        return 0

    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import landmarks as LM
    from zyg_workflows.geom.form import regions as RG

    v0, f0, _ = MS._build_mesh(LM.REF_MALE, None)
    v0 = np.asarray(v0, np.float64)
    S0 = float(v0[:, 2].max() - v0[:, 2].min())

    if cmd == 'sweep':
        # THE EXACT COMMAND THAT DERIVED THE SHIPPED RIDGE_NULL_P99. Re-runnable:
        #     python -m zyg_workflows.geom.form.ridge sweep [n_pools]
        # It prints the per-seed spread, the pooled histogram and the panel upper bound, so
        # the shipped numbers can be checked against a fresh run rather than believed.
        npl = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else RIDGE_NULL_PANEL_N_POOLS
        print(
            '\n=== ridge_null_sweep: %d seeds x %d pools per target size %s ===\n'
            '    alpha %.3f; shipped rule = PANEL UPPER BOUND (max over this fixed panel)'
            % (len(RIDGE_NULL_SEED_PANEL), npl, (30, 100, 300), RIDGE_NULL_ALPHA)
        )
        if npl < RIDGE_NULL_PANEL_N_POOLS:
            # A small run is a PLUMBING CHECK, not a derivation. Its panel maximum is
            # dominated by whichever seed drew the roughest handful of pools, so it comes out
            # far ABOVE the converged value — as misleading in the strict direction as the
            # single draw it replaced was in the permissive one. Measured: the per-seed
            # spread of the station cut is cv 4.18% at n_pools=40 against 1.27% at 320.
            print(
                "    *** n_pools=%d < the panel's %d. THESE NUMBERS MAY NOT BE SHIPPED. "
                'At this size the panel maximum is set by one lucky pool, not by the '
                'cage. Re-derive with no argument. ***' % (npl, RIDGE_NULL_PANEL_N_POOLS)
            )
        sw = ridge_null_sweep(v0, f0, n_pools=npl, stature_m=S0)
        for m in ('ridge', 'point'):
            p, s = sw['pooled'][m], sw['shipped_candidate'][m]
            print('\n  --- mode %s ---' % m)
            print(
                '    pooled over %d landmark-free pools: run hist %s'
                % (p['n_pools_total'], dict(sorted(p['run_hist'].items())))
            )
            print('    P(run >= r): %s' % {r: round(x, 5) for r, x in sorted(p['exceedance'].items())})
            print(
                '    pooled min_run %s | panel median %s | PANEL UPPER BOUND %s  <-- ships'
                % (p['min_run'], s['panel_median_min_run'], s['min_run'])
            )
            print(
                '    station cut e-3: panel min %.4f median %.4f MAX %.4f  <-- ships %.4f'
                % (
                    s['panel_min_cut_frac'] * 1e3,
                    s['panel_median_cut_frac'] * 1e3,
                    s['panel_max_cut_frac'] * 1e3,
                    s['station_min_frac_stature'] * 1e3,
                )
            )
            print(
                '    SHIPPED vs LIVE: min_run %d vs %d, cut %.6e vs %.6e, contrast '
                '%.4f vs %.4f'
                % (
                    RIDGE_NULL_P99[m]['min_run'],
                    s['min_run'],
                    RIDGE_NULL_P99[m]['station_min_frac_stature'],
                    s['station_min_frac_stature'],
                    RIDGE_NULL_P99[m]['station_min_contrast'],
                    s['station_min_contrast'],
                )
            )
        return 0

    n_null = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 40
    print(
        '\n=== ridge_null on the anny neutral: %d pools per target size %s, %d candidate '
        'curves each ===' % (n_null, (30, 100, 300), SEARCH_N_DIRECTIONS * SEARCH_N_OFFSETS)
    )
    nul = ridge_null(v0, f0, n_pools=n_null, stature_m=S0)
    for mode in ('point', 'ridge'):
        r = nul['by_mode'][mode]
        print(
            '  mode %-6s pools %d (skipped %d, sizes %d..%d median %.0f), stations '
            'scored %d'
            % (
                mode,
                r['n_pools'],
                r['skipped'],
                r['pool_size']['min'],
                r['pool_size']['max'],
                r['pool_size']['median'],
                r['n_stations_scored'],
            )
        )
        for k in (
            'abs_station_relief_frac',
            'abs_station_contrast',
            'best_longest_run',
            'best_longest_run_any_sign',
            'best_continuity',
            'best_run_span_frac_stature',
        ):
            a = r[k]
            if a:
                print(
                    '     %-26s median %.4g p90 %.4g p95 %.4g p99 %.4g max %.4g'
                    % (k, a['median'], a['p90'], a['p95'], a['p99'], a['max'])
                )
        print('     station cut used %s' % r['station_cut_used'])
        print(
            '     implied min_run (p99+1) = %s   [shipped RIDGE_NULL_P99[%r] min_run = '
            '%d];  implied min_run_any_sign = %s   [shipped %s]'
            % (
                r['implied_min_run'],
                mode,
                RIDGE_NULL_P99[mode]['min_run'],
                r['implied_min_run_any_sign'],
                RIDGE_NULL_P99[mode].get('min_run_any_sign'),
            )
        )
        print(
            '     FALSE-POSITIVE RATES ON LANDMARK-FREE SKIN — a RESOLVING run (verdict '
            'in %s) on %.2f%% of pools; point_only OR BETTER on %.2f%% of pools. The '
            'second number is why point_only may never be counted as a resolution: it is '
            'what this primitive does to blank skin.'
            % (
                sorted(RESOLVED_VERDICTS),
                100.0 * r['frac_pools_resolved'],
                100.0 * r['frac_pools_point_only_or_better'],
            )
        )
    fn = nul['facet']
    print(
        '  facet null over the same %d pools: %.0f%% of ORDINARY SKIN patches are '
        '"flatter than their collar", so that ordering test alone is close to a coin '
        'flip and a facet verdict must be read with its percentile'
        % (fn['n'], 100.0 * (fn['frac_flatter_than_collar'] or 0.0))
    )
    print(
        '     curvedness_ratio  p1 %.3f  p5 %.3f  p10 %.3f  median %.3f  p90 %.3f'
        % tuple(fn['curvedness_ratio'][k] for k in ('p1', 'p5', 'p10', 'p50', 'p90'))
    )
    print(
        '     planarity_ratio   p1 %.4f  p5 %.4f  p10 %.4f  median %.4f  p90 %.4f'
        % tuple(fn['planarity_ratio'][k] for k in ('p1', 'p5', 'p10', 'p50', 'p90'))
    )
    print(
        '     CAVEAT: this null, like curvature.relief_null, is taken on TORSO AND LIMB '
        'skin. There is no featureless head skin on this cage to build a head null from, '
        'so head percentiles below are read against torso skin and are indicative, not '
        'exact.'
    )
    if cmd == 'null':
        return 0

    # THE CENSUS RUNS AT THE SHIPPED CONSTANTS, NOT AT THIS ONE LIVE DRAW.
    # `nul` above is a SINGLE seed. Feeding it to probe_pools made every count in the tables
    # below a function of that seed: the run threshold was taken from the draw outright, and
    # the per-station cut from max(shipped, draw), so two seeds of the same experiment
    # produced different resolved counts on the same cage. RIDGE_NULL_P99 is now derived
    # from a 24-seed panel (see its header and `ridge sweep`), so the panel value is the
    # better estimate and the census uses it. The live draw is still passed for the FACET
    # PERCENTILE, which is a report-only severity and not a threshold.
    nul_facet = {'facet': nul['facet']}
    print(
        '\n  CENSUS THRESHOLDS: shipped RIDGE_NULL_P99 (24-seed panel upper bound), not '
        'the single draw above. ridge min_run %d, cut %.4fe-3 / %.3f; point min_run %d, '
        'cut %.4fe-3 / %.3f.'
        % (
            RIDGE_NULL_P99['ridge']['min_run'],
            RIDGE_NULL_P99['ridge']['station_min_frac_stature'] * 1e3,
            RIDGE_NULL_P99['ridge']['station_min_contrast'],
            RIDGE_NULL_P99['point']['min_run'],
            RIDGE_NULL_P99['point']['station_min_frac_stature'] * 1e3,
            RIDGE_NULL_P99['point']['station_min_contrast'],
        )
    )

    doc = RG.load_regions(len(v0))
    reg = MS._registry()
    bodies = [('anny-neutral (CONTROL)', v0, f0)]
    for sec in ('originals', 'derived'):
        for name in reg.get(sec, {}):
            p = reg[sec][name]['params']
            v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
            v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})
            bodies.append((name, np.asarray(v, np.float64), faces))

    summary, matrix = {}, {}
    for name, v, faces in bodies:
        S = float(v[:, 2].max() - v[:, 2].min())
        ar = CV.mixed_voronoi_area(v, faces)
        nv = CV.vertex_normals(v, faces)
        cu = CV.curvature(v, faces, stature_m=S, normals=nv)
        print('\n\n############ %s  (stature %.4f m) ############' % (name, S))
        bp = probe_pools(
            v, faces, body_pools(v, faces, S, nv, doc), stature_m=S, areas=ar, normals=nv, curv=cu, null=nul_facet
        )
        txt, chg = report_table(bp, '\n--- 20 BODY regions (regions.REGION_SPEC) ---')
        print(txt)
        hp = probe_pools(
            v, faces, head_pools(v, faces, S, nv), stature_m=S, areas=ar, normals=nv, curv=cu, null=nul_facet
        )
        txt2, chg2 = report_table(hp, '\n--- 12 HEAD/NECK windows (probe_head.py) ---')
        print(txt2)
        summary[name] = {'body': chg, 'head': chg2}
        matrix[name] = {}
        for src in (bp, hp):
            for k, r in src.items():
                if k.startswith('_'):
                    continue
                if r['status'] != 'ok':
                    matrix[name][k] = ('EMPTY', 0, None)
                elif (r.get('ridge') or {}).get('status') != 'ok':
                    matrix[name][k] = ('UNMEAS', 0, None)
                else:
                    x = r['ridge']['result']
                    matrix[name][k] = (x['verdict'], x['longest_run'], x['peak_relief_mm'])

    names = [b[0] for b in bodies]
    probes = list(matrix[names[0]].keys())
    print('\n\n=== MEASURED TABLE: ridge-primitive verdict per probe per body (verdict/run, peak mm) ===')
    hdr = '%-32s' % 'probe' + ''.join('%-26s' % n[:25] for n in names)
    print(hdr)
    print('-' * len(hdr))
    for pr in probes:
        row = '%-32s' % pr
        for n in names:
            vd, run, pk = matrix[n][pr]
            row += '%-26s' % ('%s/%d %s' % (vd, run, _n(pk) if pk is not None else '-'))
        print(row)

    print('\n\n=== SUMMARY: probes that the CURVE primitive resolves and the POINT primitive does not ===')
    for name, s in summary.items():
        print(
            '  %-26s body %2d gained %2d stronger %2d lost %2d unmeasurable | head %2d '
            'gained %2d stronger %2d lost %2d unmeasurable'
            % (
                name,
                len(s['body']['gained']),
                len(s['body']['stronger']),
                len(s['body']['lost']),
                len(s['body']['unmeasurable']),
                len(s['head']['gained']),
                len(s['head']['stronger']),
                len(s['head']['lost']),
                len(s['head']['unmeasurable']),
            )
        )
        for k in ('body', 'head'):
            for lab in ('gained', 'stronger', 'lost'):
                if s[k][lab]:
                    print('      %s %-9s %s' % (k, lab.upper(), sorted(s[k][lab])))

    # HEAD AND BODY ARE COUNTED SEPARATELY AND PRINTED SEPARATELY. They are different
    # regimes — the head windows run at a cut calibrated on torso and limb skin — and a
    # single merged count would let a real zygomatic arch stand in for an absent clavicle.
    print('\n\n=== RESOLUTION CENSUS — BODY and HEAD kept apart, never summed ===')
    for k, lab in (
        ('body', 'BODY (20 regions.REGION_SPEC probes)'),
        ('head', 'HEAD/NECK (12 windows, REPORT ONLY — body-calibrated cut)'),
    ):
        print('  --- %s ---' % lab)
        for name, s in summary.items():
            su = s[k]['summary']
            print(
                '    %-26s resolved %2d/%-2d | below-null %2d (point_only %2d, flat %2d) '
                '| unmeasurable %2d | NEVER PROBED %2d %s'
                % (
                    name,
                    su['n_resolved'],
                    su['n_probes'],
                    su['n_below_null'],
                    len(su['point_only']),
                    len(su['flat']),
                    su['n_unmeasurable'],
                    su['n_never_probed'],
                    su['never_probed'] or '',
                )
            )
    print('\n  --- AFS p.63 fat-invariant census (BODY only, denominator intact) ---')
    for name, s in summary.items():
        fi = s['body']['fat_invariant']
        if fi:
            print('    %-26s %s' % (name, fi['sentence']))
    return 0
