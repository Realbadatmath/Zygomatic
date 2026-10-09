# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.cli — the command line interface.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import contextlib
import json
import os
import sys

import numpy as np

from .constants import (
    ENV_FLAG,
    ENV_FLAG_DEFAULT,
    FAIL,
    HEXAGON_CIRCULARITY,
    LMK,
    MEA,
    MS,
    NOT_APPLICABLE,
    PASS,
    RELIEF_NULL_FRAC,
    REPORT,
    SCHEMA,
    UNMEASURABLE,
    WARN,
    enabled,
)

from .primitives import (
    frame_check,
)

from .neck import (
    neck_taper_dimorphism,
)

from .entry import (
    evaluate,
    self_test,
)


# =================================================================================
# CLI
# =================================================================================
def _mark(s):
    return {PASS: 'PASS', FAIL: 'FAIL', WARN: 'WARN', REPORT: 'rep ', UNMEASURABLE: 'UNRE', NOT_APPLICABLE: ' n/a'}.get(
        s, s
    )


@contextlib.contextmanager
def _stdout_to_stderr():
    """Point FILE DESCRIPTOR 1 at descriptor 2 for the duration.

    contextlib.redirect_stdout is not enough here and it was tried first: it rebinds the
    Python-level sys.stdout, and the two banners that pollute the JSON — anny's
    'Loading cached model data' and warp's device table — are written below Python, so they
    go straight to fd 1 and land in the middle of the document anyway. Duplicating the
    descriptor catches everything, whoever wrote it.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    want = [a for a in argv if not a.startswith('-')]
    as_json = '--json' in argv

    # --json must emit JSON AND NOTHING ELSE on stdout: a caller parsing it is a script, and
    # a banner in front of the document is a parse error, not a nicety. Suppressing OUR OWN
    # prose is not enough — anny and warp print a model-cache line and a device banner to
    # stdout when the model is first built, and those land in the middle of the document.
    # So the entire computation runs with stdout redirected to stderr and only the finished
    # document is written to the real stdout.
    def say(*a):
        if not as_json:
            print(*a)

    quiet = _stdout_to_stderr() if as_json else contextlib.nullcontext()

    with quiet:
        rc, st, frame_ok, reports, cases = _run(want, say)
    if rc:
        return rc
    if as_json:
        print(json.dumps({'self_test': st, 'frame_valid': frame_ok, 'reports': reports}, indent=1, default=float))
        return 0
    return _print_report(st, reports, cases)


def _run(want, say):
    """Everything that computes. Returns (exit_code, self_test, frame_ok, reports, cases)."""
    say(
        'geom.form.sections %s   flag %s=%s (enabled=%s)'
        % (SCHEMA, ENV_FLAG, os.environ.get(ENV_FLAG, ENV_FLAG_DEFAULT), enabled())
    )
    say(
        'relief null %.3e of stature (MEASURED, curvature.relief_null); hexagon '
        'circularity ceiling %.6f (GEOMETRY)' % (RELIEF_NULL_FRAC, HEXAGON_CIRCULARITY)
    )
    say('\nSELF TEST (deliberately broken controls)')
    st = self_test(verbose=True)
    if not st['ALL']:
        sys.stderr.write(
            'SELF TEST FAILED — refusing to report character verdicts from '
            'predicates that cannot separate a circle from a hexagon: %s\n' % json.dumps(st, default=float)
        )
        return 1, st, None, {}, []

    reports = {}
    cases = [c for c in MEA._cases() if not want or c['name'] in want]
    frame_ok = None
    for case in cases:
        v, f, _ = MS._build_mesh(case['phenotype'], case['local_changes'])
        v = MS._apply_anatomy(v, f, case['anatomy']).astype(np.float64)
        if frame_ok is None:
            frame_ok, frep = frame_check(v, f)
            say(
                '\nFRAME (landmarks.frame_report, not re-derived here): %s | %s | '
                'mirror residual %.4f mm -> sign verdicts %s'
                % (
                    frep['convention'],
                    frep['handedness'],
                    frep['bilateral_symmetry_max_residual_mm'],
                    'VALID'
                    if frame_ok
                    else 'VOID (the frame is not the one this module '
                    'assumes; every anterior/posterior and '
                    'medial/lateral sign would be inverted)',
                )
            )
            if not frame_ok:
                sys.stderr.write('FRAME VOID: %s\n' % frep['convention'])
                return 1, st, frame_ok, {}, cases
        lm = LMK.resolve_landmarks(v, f, case['phenotype'], case['local_changes'])
        rep = evaluate(
            v,
            f,
            lm=lm,
            phenotype=case['phenotype'],
            local_changes=case['local_changes'],
            sex=case['sex'],
            name=case['name'],
        )
        reports[case['name']] = rep
    return 0, st, frame_ok, reports, cases


def _print_report(st, reports, cases):
    """Everything that prints the human table. No computation, so it can sit outside the
    stdout redirection that keeps --json parseable."""
    if not enabled():
        print('\n%s=0: every gate returned %s and no geometry was measured.' % (ENV_FLAG, NOT_APPLICABLE))
        return 0

    rows = [
        ('t5_torso_sections', 'width_gt_depth'),
        ('t5_torso_sections', 'front_flatter_than_back'),
        ('t5_torso_sections', 'gluteal_concavity'),
        ('t5_neck_section', 'hexagonality'),
        ('t5_neck_section', 'circularity'),
        ('t5_neck_section', 'front_flatter_than_back'),
        ('t5_neck_section', 'spine_posterior_to_centroid'),
        ('t5_neck_section', 'taper'),
        ('t5_leg_counter_curve', 'counter_curve'),
        ('t5_calf_asymmetry', 'medial_lower_and_larger'),
    ]
    names = [c['name'] for c in cases]
    print('\n' + '=' * 118)
    print('%-46s %s' % ('claim', ' '.join('%-13s' % n[:13] for n in names)))
    print('-' * 118)
    for gate, claim in rows:
        cells = []
        for n in names:
            c = reports[n]['gates'][gate].get('claims', {}).get(claim)
            cells.append('%-13s' % (_mark(c['status']) if c else '  - '))
        print('%-46s %s' % ('%s / %s' % (gate.replace('t5_', ''), claim), ' '.join(cells)))
    print('-' * 118)

    for n in names:
        rep = reports[n]
        print(
            '\n%s   stature %.4f m   relief null %.2f mm   roll-up %s'
            % (n, rep['meta']['stature_m'], rep['meta']['relief_null_mm'], rep['meta']['status'])
        )
        t = rep['gates']['t5_torso_sections']
        print('  torso levels:')
        for L in t['levels']:
            if L.get('status') == UNMEASURABLE:
                print('    %-14s %-8s %s' % (L['level'], 'UNRES', L['why'][:92]))
            else:
                print(
                    '    %-14s fr=%.4f  W=%7.1f D=%7.1f W/D=%.3f  curv F/B=%.3f/%.3f  '
                    'camb F/B=%.3f/%.3f  full F/B=%.3f/%.3f  concav=%d(max %.1fmm%s)  %s'
                    % (
                        L['level'],
                        L['frac_stature'],
                        L['width_mm'],
                        L['depth_mm'],
                        L['width_over_depth'],
                        L['front_median_curv'],
                        L['back_median_curv'],
                        L['front_camber'],
                        L['back_camber'],
                        L['front_fullness'],
                        L['back_fullness'],
                        L.get('concavities_resolved', -1),
                        L.get('deepest_concavity_mm', 0.0),
                        ''
                        if 'deepest_concavity_posterior' not in L
                        else (', posterior' if L['deepest_concavity_posterior'] else ', ANTERIOR'),
                        L.get('section_kind', ''),
                    )
                )
        nk = rep['gates']['t5_neck_section']
        d = nk.get('detail', {})
        if 'station' in d:
            s = d['station']
            fam = nk['claims']['hexagonality'].get('evidence', {})
            print(
                '  neck: t=%.3f on the cervical chain, lean %.1f deg, %d contour pts, '
                'hull %.1f mm, circularity %.4f'
                % (
                    s['t_along_cervical_axis'],
                    d['cervical_axis']['forward_lean_deg'],
                    s['contour_points'],
                    s['hull_mm'] or float('nan'),
                    s.get('circularity') or float('nan'),
                )
            )
            if fam:
                print(
                    '        shape family: circle %.4f | hexagon %.4f | best order %s '
                    '(%.4f)  -> %s'
                    % (
                        fam.get('residual_circle', float('nan')),
                        fam.get('hexagon_residual', float('nan')),
                        fam.get('best_order'),
                        fam.get('best_residual', float('nan')),
                        'hexagon' if fam.get('hexagon_beats_circle') else 'CIRCLE',
                    )
                )
            sp = nk['claims']['spine_posterior_to_centroid'].get('evidence', {})
            print('        spine offset %+.1f mm (positive = posterior)' % sp.get('offset_mm', float('nan')))
        tp = d.get('taper', {})
        if tp and not tp.get('error'):
            print(
                '        taper: base r %.1f mm -> top r %.1f mm over %.1f mm, ratio '
                '%.4f, slope %.4f/stature, %d vertices, fit rms %.2f mm'
                % (
                    tp['radius_base_mm'],
                    tp['radius_top_mm'],
                    tp['span_mm'],
                    tp['taper_ratio'],
                    tp['slope_per_stature'],
                    tp['vertices'],
                    tp['residual_rms_mm'],
                )
            )
        lg = rep['gates']['t5_leg_counter_curve']
        for side in ('l', 'r'):
            r = lg['sides'].get(side, {})
            if r.get('status') in (PASS, FAIL):
                print(
                    '  leg %s: %d/%d stations, max |residual| %.1f mm (floor %.2f), '
                    '%d above floor, %d sign changes -> %s'
                    % (
                        side,
                        r['stations_used'],
                        r['stations_declared'],
                        r['max_abs_residual_mm'],
                        r['floor_mm'],
                        r['stations_above_floor'],
                        r['sign_changes'],
                        r['status'],
                    )
                )
            else:
                print('  leg %s: UNRESOLVED — %s' % (side, r.get('why', '')[:90]))
        cf = rep['gates']['t5_calf_asymmetry']
        for side in ('l', 'r'):
            r = cf['sides'].get(side, {})
            if r.get('status') in (PASS, FAIL):
                print(
                    '  calf %s: bulge  medial apex fr %.4f %5.1f mm | lateral apex fr '
                    '%.4f %5.1f mm | lower=%s larger=%s -> %s'
                    % (
                        side,
                        r['medial_apex_frac_stature'],
                        r['medial_bulge_mm'],
                        r['lateral_apex_frac_stature'],
                        r['lateral_bulge_mm'],
                        r['medial_lower'],
                        r['medial_larger'],
                        r['status'],
                    )
                )
                print(
                    '          raw half-width  medial apex fr %.4f %5.1f mm | lateral '
                    'apex fr %.4f %5.1f mm  (reported so the endpoint-chord correction '
                    'is auditable)'
                    % (
                        r['medial_halfwidth_apex_frac'],
                        r['medial_halfwidth_max_mm'],
                        r['lateral_halfwidth_apex_frac'],
                        r['lateral_halfwidth_max_mm'],
                    )
                )
            else:
                print('  calf %s: UNRESOLVED — %s' % (side, r.get('why', '')[:90]))

    print('\nPAIRED SEX-FLIP DIRECTION TEST (neck taper, HeadNeck p.172 vs p.173)')
    dm = neck_taper_dimorphism()
    print('  %s — %s' % (_mark(dm['status']), dm['explain']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
