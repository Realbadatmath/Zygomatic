# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The self-test, the case table and the command-line report.

Moved verbatim out of the old single-file measure.py (lines 3450-3945).

``main`` is the orchestrator of the report only: each printed section — the
per-case block, the convention comparison, the ratios, the Mahalanobis supply
and the population outliers — is a `report_*` function below, callable and
testable on a record alone. They stay here rather than in a sibling because the
ratchet's print allowlist is keyed on the file name.
"""

import json
import sys
import time

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure.constants import (
    ARM_SKIN_WEIGHT_THRESHOLD,
    ISO_20685_1_TABLE4_MM,
    _zyg_log,
)
from zyg_workflows.geom.anthro.measure.topology import (
    _topology,
    _vendor_triangles,
)
from zyg_workflows.geom.anthro.measure.mesh import measure_mesh
from zyg_workflows.geom.anthro.measure.conventions import compare_conventions


# ---------------------------------------------------------------------------------
# self-test / report
# ---------------------------------------------------------------------------------
def _selftest_topology():
    """Show that the triangulation in use is the vendor's, and by how much a naive fixed
    diagonal would have differed."""
    v, f, _ = MS._build_mesh(LMK.REF_MALE, None)
    q = np.asarray(f)
    topo = _topology(f)
    vend = _vendor_triangles(q)
    naive = np.vstack([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    same_as_naive = (
        (np.unique(np.sort(vend, axis=1), axis=0) == np.unique(np.sort(naive, axis=1), axis=0)).all()
        if vend is not None
        else None
    )
    t0 = vend[0::2] if vend is not None else None
    d02 = None
    if t0 is not None:
        d02 = int(
            sum(
                1
                for i in range(len(q))
                if set(int(x) for x in t0[i])
                in (set(int(x) for x in q[i][[0, 1, 2]]), set(int(x) for x in q[i][[0, 2, 3]]))
            )
        )
    vv = v.astype(np.float64)
    a, b, c, d = vv[q[:, 0]], vv[q[:, 1]], vv[q[:, 2]], vv[q[:, 3]]
    n = np.cross(b - a, c - a)
    n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-15)[:, None]
    flat = np.abs(((d - a) * n).sum(1)) * 1000
    return {
        'triangulation': topo['triangulation'],
        'triangles': int(len(topo['tri'])),
        'quads_on_the_0_2_diagonal': d02,
        'quads_on_the_1_3_diagonal': None if d02 is None else len(q) - d02,
        'a_fixed_0_2_split_would_be_identical': bool(same_as_naive),
        'quad_nonplanarity_mm_mean_max': [round(float(flat.mean()), 4), round(float(flat.max()), 4)],
        'shells': topo['shell_note'],
        'arm_mask': {
            k: topo['arm_mask_provenance'].get(k)
            for k in (
                'available',
                'reason',
                'threshold',
                'bones_total',
                'bones_masked',
                'bones_kept_names',
                'vertices_total',
                'vertices_arm',
            )
            if k in topo['arm_mask_provenance']
        },
    }


def _cases():
    """The four issued characters, plus the stock anny body as a CONTROL.

    The control is what makes the deltas readable: without it there is no way to tell a
    property of the base cage from a property of a character's morphs. Measured, that
    distinction is real — wrist circumference is 4 SD below the ANSUR mean on the stock
    body and stays 3-4 SD below on every character, so it is anny's wrist, not ours, while
    chest breadth is 1.4 SD high on the stock body and 9.5 SD high on the male original,
    which is the male's own torso morphs.
    """
    reg = MS._registry()
    out = [
        {
            'name': 'anny-neutral(control)',
            'phenotype': dict(LMK.REF_MALE),
            'local_changes': None,
            'anatomy': None,
            'sex': 'male',
            'age_frac': LMK.REF_MALE['age'],
        }
    ]
    for sec in ('originals', 'derived'):
        for k in reg.get(sec, {}):
            p = reg[sec][k]['params']
            sex = p.get('sex') or ('female' if p['phenotype'].get('gender', 0) > 0.5 else 'male')
            age_frac = p['phenotype'].get('age')
            out.append(
                {
                    'name': k,
                    'phenotype': p['phenotype'],
                    'local_changes': p['local_changes'],
                    'anatomy': p.get('anatomy_layer'),
                    'sex': sex,
                    'age_frac': age_frac,
                }
            )
    return out


def _age_years(age_frac):
    """MakeHuman's macro age parameter in years.

    The piecewise mapping (0.0 -> 1 y, 0.5 -> 25 y, 1.0 -> 90 y) is MakeHuman's, and it is
    VERIFIED rather than assumed here: it reproduces the ages the registry declares for
    the two derived characters exactly — abel 0.229167 -> 12.00 y and cornelis 0.638462 ->
    43.00 y. Needed because a 12-year-old must be scored against CDC growth curves, never
    against ANSUR II's 17-58 year old soldiers.
    """
    a = float(age_frac)
    return 1.0 + a * 48.0 if a <= 0.5 else 25.0 + (a - 0.5) * 130.0


def _fmt(x, w=8, p=1):
    """`x` in a fixed-width field, or a right-aligned dash when it is None."""
    return ('%*.*f' % (w, p, x)) if x is not None else ('%*s' % (w, '-'))


def _arm_mask_summary(M):
    """One line saying whether the skinning-weight arm mask ran and what it did.

    A mask that changed nothing has to SAY it changed nothing, with the count and the
    closest approach, or it is indistinguishable from a mask that never ran.
    """
    rows = [(k, r['arm_mask']) for k, r in M.items() if isinstance(r.get('arm_mask'), dict)]
    if not rows:
        return 'no sliced measurement carried an arm_mask block'
    unavail = [a.get('unavailable_because') for _k, a in rows if a.get('available') is False]
    if unavail:
        return 'UNAVAILABLE on %d of %d sliced sites — %s' % (len(unavail), len(rows), unavail[0])
    off = [k for k, a in rows if not a.get('applied')]
    applied = [(k, a) for k, a in rows if a.get('applied')]
    changed = [(k, a) for k, a in applied if a.get('changed_the_value')]
    close = max((a.get('max_arm_weight_on_section') or 0.0) for _k, a in applied) if applied else 0.0
    s = (
        'ran on %d torso/head sites, dropped %d contour points in total, changed %d '
        'values; closest any surviving trunk point came to the %.2f threshold was %.3f'
        % (
            len(applied),
            sum(a.get('contour_points_dropped') or 0 for _k, a in applied),
            len(changed),
            ARM_SKIN_WEIGHT_THRESHOLD,
            close,
        )
    )
    if changed:
        s += ' | CHANGED: %s' % ', '.join(
            '%s (-%d pts, was %.2f mm)'
            % (
                k,
                a['contour_points_dropped'],
                a.get('x_extent_without_mask_mm') or a.get('hull_without_mask_mm') or float('nan'),
            )
            for k, a in changed
        )
    if off:
        s += ' | measured but NOT applied on %d sites whose definition is the arm or the limb (%s)' % (
            len(off),
            ', '.join(off),
        )
    return s


def report_case(case, out, seconds):
    """Print one character's measurement block.

    `out` is measure_mesh's record and `seconds` the wall time it took. Prints the
    per-site table (value, fraction of stature, contour, polyline, where on the body it
    was found, the ISO class), then what was REFUSED and what is UNMEASURABLE on this
    cage, then the pose advisories, the arm-mask line, the A-pose bias table and the
    limb-girth plane convention — every one of them a section that would otherwise have
    to be read out of the JSON record by hand.
    """
    M = out['measurements']
    print('\n' + '=' * 100)
    print('%s   sex=%s  stature=%.4f m  (%.1fs)' % (case['name'], case['sex'], out['meta']['stature_m'], seconds))
    print('  pose: %s' % out['meta']['pose'])
    print('  frame: %s ; %s' % (out['meta']['axis_convention'], out['meta']['handedness']))
    print(
        '  %-42s %9s %9s %9s %9s %7s  %s'
        % ('measurement', 'value_mm', 'frac_H', 'contour', 'polyline', 'at_frac', 'iso_class')
    )
    for k in sorted(M):
        r = M[k]
        if r['provenance'] in ('UNMEASURABLE', 'REFUSED'):
            continue
        val = r.get('value_mm')
        if val is None and r.get('value') is not None:
            print(
                '  %-42s %9.3f %9s %9s %9s %7s  %s (%s)'
                % (k, r['value'], '-', '-', '-', '-', r.get('units', ''), r['provenance'])
            )
            continue
        at = r.get('found_at_frac_stature')
        if at is None and isinstance(r.get('scan'), dict):
            at = r['scan'].get('found_at_frac_stature')
        marks = ''
        if r['provenance'] != 'MEASURED':
            marks += '  [%s]' % r['provenance']
        if r.get('survey_comparable') is False:
            marks += '  [NOT SURVEY-COMPARABLE]'
        if r.get('endpoint_warning') or (isinstance(r.get('scan'), dict) and r['scan'].get('at_window_endpoint')):
            marks += '  [BAND-EDGE]'
        print(
            '  %-42s %s %s %s %s %s  %s%s'
            % (
                k,
                _fmt(val, 9, 2),
                _fmt(r.get('frac_stature'), 9, 4),
                _fmt(r.get('contour_mm'), 9, 2),
                _fmt(r.get('polyline_mm'), 9, 2),
                _fmt(at, 7, 4),
                r.get('iso_class') or '-',
                marks,
            )
        )
    refused = [k for k in sorted(M) if M[k]['provenance'] == 'REFUSED']
    if refused:
        print('  REFUSED (measurable in principle, not on this mesh):')
        for k in refused:
            print('    %-40s %s' % (k, (M[k].get('reason') or '')[:130]))
    print('  UNMEASURABLE ON THIS CAGE: %s' % ', '.join(k for k in sorted(M) if M[k]['provenance'] == 'UNMEASURABLE'))

    if out['meta']['pose_check']['advisories']:
        print('  ADVISORY: %s' % ' | '.join(out['meta']['pose_check']['advisories']))

    ab = out['meta']['a_pose_bias']
    print('  ARM MASK: %s' % _arm_mask_summary(M))
    if not ab.get('available'):
        print('  A-POSE BIAS: UNAVAILABLE — %s' % ab.get('reason'))
    else:
        print(
            '  A-POSE BIAS (arms-down minus as-issued; UPPER BOUND on the magnitude '
            '— a genuine re-pose moves 79-97%% as far on the trunk; reported, NOT '
            'applied; humerus %s deg):' % ab.get('humerus_abduction_deg')
        )
        rows = [(k, M[k]) for k in sorted(M) if M[k].get('a_pose_bias_mm') not in (None, 0.0)]
        for k, r in rows:
            iso = ISO_20685_1_TABLE4_MM.get(r.get('iso_class'))
            print(
                '    %-40s %9.2f -> %9.2f  bias %+8.2f mm  (%+.1f%%, ISO %s class tolerance %s mm)%s'
                % (
                    k,
                    r['value_mm'],
                    r['value_mm'] + r['a_pose_bias_mm'],
                    r['a_pose_bias_mm'],
                    100 * r['a_pose_bias_mm'] / r['value_mm'],
                    r.get('iso_class'),
                    iso,
                    '' if iso is None or abs(r['a_pose_bias_mm']) <= iso else '  [EXCEEDS THE ISO CLASS TOLERANCE]',
                )
            )
        zeros = [k for k in sorted(M) if M[k].get('a_pose_bias_mm') == 0.0]
        print('    exactly zero (no arm skinning weight anywhere on the section): %s' % (', '.join(zeros) or 'none'))
    lim = [(k, M[k]) for k in sorted(M) if M[k].get('horizontal_minus_perpendicular_mm') is not None]
    if lim:
        print(
            '  LIMB GIRTH PLANE CONVENTION (ISO 18825-2 perpendicular vs ANSUR '
            'horizontal tape, only where a survey uses a horizontal tape):'
        )
        for k, r in lim:
            print(
                '    %-40s perp %8.2f  horiz %8.2f  diff %+7.2f mm (%+.1f%%)'
                % (
                    k,
                    r['value_mm'],
                    r['horizontal_mm'],
                    r['horizontal_minus_perpendicular_mm'],
                    100 * r['horizontal_minus_perpendicular_mm'] / r['value_mm'],
                )
            )


def report_convention_comparison(results):
    """Print hull (taut tape) vs contour vs inscribed polyline, per case and per site.

    `results` is the {name: (case, out, v, f)} table main() built. Re-slices every case
    through compare_conventions and prints the three orderings the conventions are
    claimed to satisfy — hull >= polyline in 3D, hull >= the same ring flattened, hull <=
    contour — as measured statements rather than as assertions, plus anny's own vendor
    chord-sum waist beside our hull at the same ring where that site exists.
    """
    print('\n' + '=' * 100)
    print('CONVENTION COMPARISON — hull (taut tape) vs contour vs inscribed polyline')
    for nm in results:
        case, _out, v, f = results[nm]
        cc = compare_conventions(v, f, phenotype=case['phenotype'], local_changes=case['local_changes'])
        s = cc['summary']
        print('\n  %s' % nm)
        print(
            '    %-40s %9s %9s %9s %9s %8s %8s %7s'
            % ('site', 'hull', 'contour', 'poly3d', 'poly_flat', 'hull-p3d', 'hull-pfl', 'ring_dz')
        )
        for k in sorted(cc['sites']):
            r = cc['sites'][k]
            if r.get('hull_minus_polyline_mm') is None:
                print(
                    '    %-40s %9s %9s %9s   %s'
                    % (
                        k,
                        _fmt(r.get('hull_mm'), 9, 2),
                        _fmt(r.get('contour_mm'), 9, 2),
                        _fmt(r.get('polyline_mm'), 9, 2),
                        r.get('reason', '')[:40],
                    )
                )
                continue
            print(
                '    %-40s %9.2f %9.2f %9.2f %9.2f %+8.2f %+8.2f %7.1f'
                % (
                    k,
                    r['hull_mm'],
                    r['contour_mm'],
                    r['polyline_mm'],
                    r['polyline_planar_mm'],
                    r['hull_minus_polyline_mm'],
                    r['hull_minus_polyline_planar_mm'],
                    r['ring_out_of_plane_mm'],
                )
            )
        print(
            '    hull >= polyline (3D vertex ring) everywhere: %s   delta min/mean/max = %.2f / %.2f / %.2f mm over %d sites'
            % (
                s['hull_ge_polyline_everywhere'],
                s['hull_minus_polyline_mm']['min'],
                s['hull_minus_polyline_mm']['mean'],
                s['hull_minus_polyline_mm']['max'],
                s['n_sites'],
            )
        )
        print(
            '    hull >= polyline (same ring FLATTENED into the plane) everywhere: %s   '
            'delta min/mean/max = %.2f / %.2f / %.2f mm'
            % (
                s['hull_ge_polyline_planar_everywhere'],
                s['hull_minus_polyline_planar_mm']['min'],
                s['hull_minus_polyline_planar_mm']['mean'],
                s['hull_minus_polyline_planar_mm']['max'],
            )
        )
        print(
            '    hull <= contour everywhere: %s   (hull-contour min/mean/max = %.2f / %.2f / %.2f mm)'
            % (
                s['hull_le_contour_everywhere'],
                s['hull_minus_contour_mm']['min'],
                s['hull_minus_contour_mm']['mean'],
                s['hull_minus_contour_mm']['max'],
            )
        )
        if 'anny_native_waist_polyline_mm' in s:
            print(
                "    anny's own waist_circumference (vendor chord sum) = %.2f mm; "
                'our hull at the same ring = %.2f mm; gap %+.2f mm'
                % (
                    s['anny_native_waist_polyline_mm'],
                    cc['sites']['waist_circumference_anny_ring']['hull_mm'],
                    s['anny_native_vs_our_hull_mm'],
                )
            )


def report_ratios_vs_ansur(ref, results):
    """Print every case's ratios against the ANSUR II reference pack.

    ADULTS ONLY: ANSUR II is 17-58 year old US Army personnel, so a case whose
    MakeHuman age maps under 17 years is printed without a band and is scored instead
    against the CDC 2000 growth reference (stature z, BMI percentile) with the
    foot-over-hand distal-proximal check beside the adult male meshes of the same run.
    """
    print('\n' + '=' * 100)
    print('RATIOS vs the ANSUR II reference pack (pooled, no ancestry declared)')
    print('  ADULTS ONLY. ANSUR II is 17-58 year old US Army personnel; a 12-year-old')
    print('  has no business being compared to it and is printed without a band.')
    for nm in results:
        case, out, _v, _f = results[nm]
        years = _age_years(case['age_frac'] or 0.5)
        adult = years >= 17.0
        print(
            '\n  %s (sex=%s, age %.1f y%s)' % (nm, case['sex'], years, '' if adult else ', CHILD — NO ANSUR COMPARISON')
        )
        if not adult:
            H_cm = out['meta']['stature_m'] * 100.0
            bmi = out['measurements']['derived_bmi']['value']
            z = ref.stature_z(H_cm, years * 12.0, case['sex'])
            bp = ref.bmi_percentile(bmi, years * 12.0, case['sex'])
            print('    CDC 2000 growth reference (the RIGHT reference for this age):')
            print(
                '      stature %.1f cm at %.0f months -> z=%+.3f, %.1fth percentile'
                % (H_cm, years * 12, z['z'], z['percentile'])
            )
            print(
                '      BMI %.2f (density-assumption derived) -> z=%+.3f, %.1fth percentile'
                % (bmi, bp['z'], bp['percentile'])
            )
            print(
                '      distal-proximal check foot/hand = %.4f (adult male meshes '
                'here: %s) — growth is distal-to-proximal, so a child should run '
                'HIGH'
                % (
                    out['ratios']['foot_over_hand_length']['value'],
                    ', '.join(
                        '%.4f' % results[o][1]['ratios']['foot_over_hand_length']['value']
                        for o in results
                        if _age_years(results[o][0]['age_frac'] or 0.5) >= 17 and results[o][0]['sex'] == 'male'
                    ),
                )
            )
        print('    %-48s %9s %9s %9s %8s %7s' % ('ratio', 'mesh', 'ansur_mu', 'delta', 'z', 'pctile'))
        for k in sorted(out['ratios']):
            r = out['ratios'][k]
            if not adult:
                print('    %-48s %9.4f %9s %9s %8s %7s' % (k, r['value'], '-', '-', '-', '-'))
                continue
            try:
                b = ref.band(k, case['sex'])
                p = ref.percentile(k, r['value'], case['sex'])
            except Exception:  # noqa: BLE001
                print('    %-48s %9.4f %9s %9s %8s %7s   [not in pack]' % (k, r['value'], '-', '-', '-', '-'))
                continue
            z = (r['value'] - b['mean']) / b['sd'] if b['sd'] else float('nan')
            print(
                '    %-48s %9.4f %9.4f %+9.4f %+8.2f %7.1f%s'
                % (
                    k,
                    r['value'],
                    b['mean'],
                    r['value'] - b['mean'],
                    z,
                    p,
                    '' if r.get('survey_comparable', True) else '  NOT SURVEY-COMPARABLE',
                )
            )


def report_joint_plausibility(ref, results):
    """Print what each case can and cannot feed the Mahalanobis gate.

    One line per adult case: how many of the pack's ordered ratios were supplied, the
    squared distance, the pass/warn verdict and the p95/p99 thresholds, then the names
    supplied and the names MISSING — a d2 computed on a subset says so out loud. A child
    is printed as out of scope instead, the adult joint model not applying to it.
    """
    print('\n' + '=' * 100)
    print('JOINT PLAUSIBILITY — what we can and cannot feed the Mahalanobis gate')
    order = ref.doc['mahalanobis']['order']
    for nm in results:
        case, out, _v, _f = results[nm]
        if _age_years(case['age_frac'] or 0.5) < 17.0:
            print('  %-10s CHILD — the adult joint model does not apply' % nm)
            continue
        supply = {k: out['ratios'][k]['value'] for k in order if k in out['ratios']}
        r = ref.mahalanobis(supply, case['sex'])
        print(
            '  %-10s k=%d/%d  d2=%.3f  pass=%s warn=%s  thr p95=%.3f p99=%.3f'
            % (
                nm,
                r['k'],
                len(order),
                r['d2'],
                r['pass_'],
                r['warn'],
                r['thresholds']['p95'],
                r['thresholds']['p99'],
            )
        )
        print('             supplied: %s' % ', '.join(r['used']))
        print('             MISSING : %s' % ', '.join(r['missing']))


def report_population_outliers(ref, results):
    """Print every survey-comparable ratio at |z| >= 2, adults only, worst first.

    These are findings about the assets, not slicer errors: a ratio the pack has no band
    for is logged to the debug channel and skipped, a band with zero spread is skipped,
    and a case with no hit prints `none` rather than nothing at all.
    """
    print('\n' + '=' * 100)
    print('WHERE THE ASSETS SIT AGAINST THE POPULATION — |z| >= 2 on a')
    print('survey-comparable ratio, adults only. These are findings about the assets,')
    print('not slicer errors.')
    for nm in results:
        case, out, _v, _f = results[nm]
        if _age_years(case['age_frac'] or 0.5) < 17.0:
            continue
        hits = []
        for k in sorted(out['ratios']):
            r = out['ratios'][k]
            if not r.get('survey_comparable', True):
                continue
            try:
                b = ref.band(k, case['sex'])
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('no reference band for ratio %s: %s', k, _exc)
                continue
            if not b['sd']:
                continue
            z = (r['value'] - b['mean']) / b['sd']
            if abs(z) >= 2.0:
                hits.append((z, k, r['value'], b['mean']))
        print('  %s:' % nm)
        for z, k, mv, mu in sorted(hits, key=lambda t: -abs(t[0])):
            print('    %-46s %.4f vs %.4f   z=%+.2f' % (k, mv, mu, z))
        if not hits:
            print('    none')


def _load_reference_pack():
    """The ANSUR II / CDC reference pack, or None when it is not installed.

    Mirrors the pack's ISO 20685-1 table 4 tolerances into the module constant so the
    A-pose bias report scores against the pack rather than against a hardcoded copy, and
    prints one line either way: a self-test that silently dropped the survey comparison
    would read as a self-test that found nothing to compare.
    """
    try:
        from zyg_workflows.geom.anthro.reference import reference

        ref = reference()
        ISO_20685_1_TABLE4_MM.update(ref.doc['iso_20685_1_table4_mm'])
        print('reference pack: %d ratios, ISO table mirrored from the pack' % len(ref.ratios()))
        return ref
    except Exception as e:  # noqa: BLE001
        print('reference pack UNAVAILABLE (%s) — running without survey comparison' % e)
        return None


def _measure_cases():
    """Build, sculpt and measure every self-test case, printing each one's block.

    Returns the {name: (case, out, vertices, faces)} table the later sections re-slice:
    the convention comparison needs the very mesh that was measured, not a rebuild of it.
    """
    results = {}
    for case in _cases():
        v, f, _ = MS._build_mesh(case['phenotype'], case['local_changes'])
        v = MS._apply_anatomy(v, f, case['anatomy']).astype(np.float64)
        t0 = time.time()
        out = measure_mesh(
            v, f, sex=case['sex'], phenotype=case['phenotype'], local_changes=case['local_changes'], name=case['name']
        )
        results[case['name']] = (case, out, v, f)
        report_case(case, out, time.time() - t0)
    return results


def main(argv=None):
    """Measure every case and print the whole self-test report; returns 0.

    `--json <name>` appends that case's full measure_mesh record. The reference pack is
    loaded before anything is measured so the ISO table is already mirrored when the
    first case prints, and the three pack-dependent sections are skipped entirely when
    it is unavailable.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    print('topology self-test:', _selftest_topology())
    ref = _load_reference_pack()
    results = _measure_cases()
    report_convention_comparison(results)
    if ref is not None:
        report_ratios_vs_ansur(ref, results)
        report_joint_plausibility(ref, results)
        report_population_outliers(ref, results)
    if '--json' in argv:
        nm = argv[argv.index('--json') + 1] if len(argv) > argv.index('--json') + 1 else 'male'
        _case, out, _v, _f = results[nm]
        print('\n=== full record, %s ===' % nm)
        print(json.dumps(out, indent=1, default=float))
    return 0
