# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The CLI.

Moved verbatim out of the old single-file hands.py (lines 3589-4078).
"""

import argparse
import glob
import os
import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    PREDICATES,
    UNMEASURABLE,
    DIGITS,
    FINGERS,
    SAMPLE_FILE,
    DIGIT_BONES,
    rig,
    verify_rig,
)
from zyg_workflows.geom.form.hands.mesh import (
    calibration,
    check_hand_mesh,
)
from zyg_workflows.geom.form.hands.unresolved import (
    MESH_UNRESOLVED,
    IMAGE_UNRESOLVED,
    DIGIT_UNRESOLVED,
)
from zyg_workflows.geom.form.hands.image import (
    check_hand_image,
)
from zyg_workflows.geom.form.hands.sample import (
    build_sample,
    LESIONS,
)
from zyg_workflows.geom.form.hands.digits_rig import (
    TOES,
    _ratio_band,
)
from zyg_workflows.geom.form.hands.digit_chains import (
    digit_roster,
    check_digit_chains,
    measure_phalanx_ratio,
    check_phalanx_ratio,
)
from zyg_workflows.geom.form.hands.child_hand import (
    CHILD_AGE_MAX_Y,
    CHILD_HAND_ASSERTIONS,
    check_child_hand,
)
from zyg_workflows.geom.form.hands.digits import (
    phalanx_scale_recipe,
    survey_mean_targets,
)


# ---------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------
def _fmt(x, nd=5):
    return 'None' if x is None else ('%.*f' % (nd, x))


def _report_mesh(name, res):
    p = res['predicates']
    print('  %-10s %s' % (name, res['side']))
    for k in PREDICATES:
        r = p[k]
        print(
            '     %-20s %-12s %-10s band=%s'
            % (
                k,
                r['status'],
                _fmt(r['observed'], 4),
                'None' if not r['band'] else '[%s, %s]' % (_fmt(r['band'][0], 4), _fmt(r['band'][1], 4)),
            )
        )


def _digit_cases():
    """The four issued characters plus the anny-neutral CONTROL.

    Same roster and same control as geom.anthro.measure._cases(), reused rather than
    re-derived so a form table and a metric table always speak about the same bodies;
    bone_scales are picked up from the registry because _cases() does not carry them and
    a scaled bone is exactly what this pack reads.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import measure as ME

    reg = MS._registry()
    out = []
    for c in ME._cases():
        p = (
            (reg['originals'].get(c['name']) or {}).get('params')
            or (reg['derived'].get(c['name']) or {}).get('params')
            or {}
        )
        out.append(dict(c, bone_scales=p.get('bone_scales') or None))
    return out


def _cli_digits():
    from zyg_workflows.geom.anthro import measure as ME

    cases = _digit_cases()
    print('=== t5_digit_chains — integer counts on the %d-bone rig (AFS p.179, p.188) ===' % rig()['n_bones'])
    R = digit_roster()
    print(
        'roster parsed from the rig names: %d finger-bone chains, %d metacarpals/side, '
        '%d toe-bone chains, %d carpal bones, %d tarsal/metatarsal bones'
        % (
            len(R['finger_bones']),
            len(R['metacarpal_bones'].get('L', [])),
            len(R['toe_bones']),
            len(R['carpal_bones']),
            len(R['tarsal_or_metatarsal_bones']),
        )
    )
    hdr = ('character', 'side', 'digits', 'phal/hand', 'mcp', 'phal/foot', 'chain mm', 'counts', 'surface', 'status')
    print('  %-22s %-4s %-6s %-9s %-4s %-9s %-8s %-6s %-7s %s' % hdr)
    for c in cases:
        for S in ('L', 'R'):
            r = check_digit_chains(c['phenotype'], c['local_changes'], c['bone_scales'], S)
            d = r['detail']
            sc = d['subchecks']
            print(
                '  %-22s %-4s %-6d %-9s %-4s %-9s %-8.6f %-6s %-7s %s'
                % (
                    c['name'],
                    S,
                    d['counts']['digits_per_hand'],
                    d['counts']['phalanges_per_hand'],
                    d['counts']['metacarpals_per_hand'],
                    d['counts']['phalanges_per_foot'],
                    d['max_chain_gap_mm'],
                    sc['integer_counts'],
                    sc['surface_resolvable'],
                    r['status'].upper(),
                )
            )
        if c is cases[0]:
            mp = check_digit_chains(c['phenotype'], c['local_changes'], c['bone_scales'], 'L')['detail'][
                'metapodial_test'
            ]
            for part in ('hand', 'foot'):
                x = mp[part]
                print(
                    '     metapodial test %s: %s head sits %.2f mm off the MP joint '
                    'line = %.3f of its own length -> %s'
                    % (part, x['bone'], x['off_mp_line_m'] * 1000, x['off_over_own_length'], x['verdict'].upper())
                )
            ss = check_digit_chains(c['phenotype'], c['local_changes'], c['bone_scales'], 'L')['detail'][
                'surface_support'
            ]
            bad = [r for r in ss if r['n_majority'] == 0]
            thin = [r for r in ss if 0 < r['n_majority'] < 10]
            print(
                '     surface support: %d/%d phalanx bones own ZERO cage vertices '
                'outright%s; %d own fewer than 10%s'
                % (
                    len(bad),
                    len(ss),
                    (' (%s)' % ', '.join('%s/%s' % (r['digit'], r['bone']) for r in bad)) if bad else '',
                    len(thin),
                    (' (%s)' % ', '.join('%s/%s=%d' % (r['digit'], r['bone'], r['n_majority']) for r in thin))
                    if thin
                    else '',
                )
            )

    print('\n=== t5_phalanx_ratio — mid/prox against two radiographic series ===')
    print('  external MEASURED reference, transcribed before any anny number was read:')
    for d in FINGERS:
        ref = _ratio_band(d, 'mid_over_prox')
        print(
            '    %-7s BK2010 %.4f  HD2002 %.4f  (they differ by %.4f)  band '
            '[%.4f, %.4f]  CANON AFS p.178 %.4f'
            % (
                d,
                ref['buryanov_kotiuk_2010'],
                ref['hamilton_dunsmuir_2002'],
                ref['source_spread'],
                ref['band'][0],
                ref['band'][1],
                ref['canon_afs_p178'],
            )
        )
    print('  %-22s %-4s %s' % ('character', 'side', ' '.join('%-16s' % d for d in FINGERS)))
    for c in cases:
        for S in ('L', 'R'):
            r = check_phalanx_ratio(c['phenotype'], c['local_changes'], c['bone_scales'], S)
            f = r['detail']['fingers']
            print(
                '  %-22s %-4s %s   %s'
                % (
                    c['name'],
                    S,
                    ' '.join(
                        '%.4f(z%+.2f)' % (f[d]['mid_over_prox']['measured'], f[d]['mid_over_prox']['z_conservative'])
                        for d in FINGERS
                    ),
                    r['status'].upper(),
                )
            )
    print(
        "\n  dist/mid — DIP joint centre to the FLESHY tip, the convention the rig's "
        'distal tail measured\n  (nearest cage vertex to that tail: 1.07-3.01 mm):'
    )
    for d in FINGERS:
        ref = _ratio_band(d, 'dist_over_mid')
        print(
            '    %-7s BK2010 %.4f  HD2002 %.4f  band [%.4f, %.4f]  CANON %.4f'
            % (
                d,
                ref['buryanov_kotiuk_2010'],
                ref['hamilton_dunsmuir_2002'],
                ref['band'][0],
                ref['band'][1],
                ref['canon_afs_p178'],
            )
        )
    for c in cases:
        r = check_phalanx_ratio(c['phenotype'], c['local_changes'], c['bone_scales'], 'L')
        f = r['detail']['fingers']
        print(
            '  %-22s %-4s %s'
            % (
                c['name'],
                'L',
                ' '.join(
                    '%.4f(%s)' % (f[d]['dist_over_mid']['measured'], f[d]['dist_over_mid']['status'][:4])
                    for d in FINGERS
                ),
            )
        )

    print('\n  joint position along the finger, fraction of MCP->fingertip (convention-free):')
    c0 = cases[0]
    jf = check_phalanx_ratio(c0['phenotype'], c0['local_changes'], c0['bone_scales'], 'L')['detail']['joint_fractions']
    print(
        '    %-7s %-9s %-9s %-9s %-9s | %-9s %-9s %-9s'
        % ('finger', 'rig PIP', 'BK PIP', 'HD PIP', 'canon', 'rig DIP', 'BK DIP', 'HD DIP')
    )
    for d in FINGERS:
        j = jf[d]
        print(
            '    %-7s %-9.4f %-9.4f %-9.4f %-9.4f | %-9.4f %-9.4f %-9.4f'
            % (
                d,
                j['rig_pip_fraction'],
                j['bk2010_pip_fraction'],
                j['hd2002_pip_fraction'],
                j['canon_afs_p178_pip_fraction'],
                j['rig_dip_fraction'],
                j['bk2010_dip_fraction'],
                j['hd2002_dip_fraction'],
            )
        )

    print('\n=== foot ratios — REPORTED, NOT GATED (no external table, see UNRESOLVED) ===')
    print('  %-22s %s' % ('character', ' '.join('%-14s' % t for t in TOES)))
    for c in cases:
        m = measure_phalanx_ratio(c['phenotype'], c['local_changes'], c['bone_scales'], 'L')
        cells = []
        for t in TOES:
            r = m['foot'][t]
            cells.append('%.4f' % (r['dist_over_prox'] if 'dist_over_prox' in r else r['mid_over_prox']))
        print('  %-22s %s' % (c['name'], ' '.join('%-14s' % x for x in cells)))
    print('  (hallux column is distal/proximal — 2 phalanges; toe2-5 are middle/proximal)')

    print('\n=== child-hand directions (AFS p.185, p.178) — bar is the SAME body aged to 25 y ===')
    for c in cases:
        r = check_child_hand(c['phenotype'], c['local_changes'], c['bone_scales'], 'L', c.get('anatomy'))
        d = r['detail']
        if r['status'] == UNMEASURABLE:
            print(
                '  %-22s %-6.1f %s'
                % (
                    c['name'],
                    ME._age_years(c['age_frac']),
                    'UNMEASURABLE — adult (>= %.0f y), no child claim to test' % CHILD_AGE_MAX_Y,
                )
            )
            continue
        print('  %-22s %-6.1f  -> %s' % (c['name'], d['age_years'], r['status'].upper()))
        for key, _want, kind, _why in CHILD_HAND_ASSERTIONS:
            x = d['assertions'][key]
            if kind == 'scalar':
                print(
                    '     %-30s child %-9.4f adult %-9.4f  %s'
                    % (key, x.get('child', float('nan')), x.get('adult', float('nan')), x['status'].upper())
                )
            else:
                print(
                    '     %-30s %d/%d fingers hold, largest relative delta %.1f%%  %s'
                    % (
                        key,
                        x['n_holding'],
                        x['n_fingers'],
                        100.0 * (x['largest_relative_delta'] or 0.0),
                        x['status'].upper(),
                    )
                )
                print(
                    '        %s'
                    % '  '.join(
                        '%s %+.1f%%' % (f, 100.0 * (v['relative_delta'] or 0.0)) for f, v in x['per_finger'].items()
                    )
                )

    print('\nUNRESOLVED in the digit pack:')
    for u in DIGIT_UNRESOLVED:
        print('  %s / %s: %s' % (u['predicate'], u['part'], u['status']))
        print('     %s' % u['evidence'])


def _cli_digit_lesion(character):
    from zyg_workflows.geom import mesh_skeletons as MS

    reg = MS._registry()
    p = (reg['originals'].get(character) or {}).get('params') or (reg['derived'].get(character) or {}).get('params')
    if p is None:
        raise SystemExit('no registered character %r' % character)
    loc = p.get('local_changes') or None
    print('digit lesion on %s, left hand — a gate that never fires is not a gate' % character)
    print(
        "  the lesion slides the interphalangeal joints and leaves the finger's TOTAL "
        'length, its\n  metacarpal and its MCP exactly where they were, which is the '
        'defect class no length\n  gate in geom.anthro can see.'
    )
    tg = survey_mean_targets()
    print(
        '  %-31s %-39s %-9s %-7s %s'
        % ('recipe', 'mid/prox ' + ' '.join('%-9s' % d for d in FINGERS), 'total mm', 'status', 'what fired')
    )
    for label, bs in (
        ('(as issued)', p.get('bone_scales') or None),
        ('driven to the survey means', phalanx_scale_recipe(p['phenotype'], loc, tg)),
        ('survey means x1.45 (lesion)', phalanx_scale_recipe(p['phenotype'], loc, tg, 1.45)),
        ('survey means x0.45 (lesion)', phalanx_scale_recipe(p['phenotype'], loc, tg, 0.45)),
    ):
        r = check_phalanx_ratio(p['phenotype'], loc, bs, 'L')
        mres = measure_phalanx_ratio(p['phenotype'], loc, bs, 'L')
        f = r['detail']['fingers']
        print(
            '  %-31s %-39s %-9.4f %-7s %s'
            % (
                label,
                ' '.join('%-9.4f' % f[d]['mid_over_prox']['measured'] for d in FINGERS),
                sum(mres['hand'][d]['total_m'] for d in FINGERS) * 1000,
                r['status'].upper(),
                ', '.join(r['detail']['failed']) or '-',
            )
        )


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m zyg_workflows.geom.form.hands', description=__doc__.split('\n')[0])
    ap.add_argument('--verify', action='store_true', help='run every predicate on the four issued characters')
    ap.add_argument('--images', nargs='*', default=None, help='image files or glob roots to run the image path on')
    ap.add_argument(
        '--build-sample', type=int, default=0, metavar='N', help='draw N bodies and (re)build the calibration sample'
    )
    ap.add_argument('--seed', type=int, default=20260806)
    ap.add_argument('--rig', action='store_true', help='print the hand bone roster')
    ap.add_argument(
        '--lesions',
        action='store_true',
        help='damage one predicate at a time on a real cage and check that the predicate notices',
    )
    ap.add_argument(
        '--digits',
        action='store_true',
        help='run t5_digit_chains, t5_phalanx_ratio and the child-hand '
        'directions on the four issued characters plus the '
        'anny-neutral control',
    )
    ap.add_argument(
        '--digit-lesion',
        action='store_true',
        help='slide the interphalangeal joints on a real character and check that t5_phalanx_ratio notices',
    )
    ap.add_argument('--character', default='male', help='registered character the lesion test runs on')
    args = ap.parse_args(argv)
    did = False

    if args.rig:
        did = True
        R = rig()
        print('anny rig: %d bones' % R['n_bones'])
        for d in DIGITS:
            print('  %-7s %s' % (d, ' -> '.join(b for b in DIGIT_BONES[d] if b)))
        rows = verify_rig()
        print(
            '  metacarpal->digit mapping verified from the rig, max tail/head gap '
            '%.9f mm over %d joints' % (max(r['gap_mm'] for r in rows), len(rows))
        )

    if args.build_sample:
        did = True
        print('building the form reference sample (%d draws)...' % args.build_sample)
        doc = build_sample(args.build_sample, seed=args.seed)
        pv = doc['provenance']
        print(
            '  accepted %d/%d (%d rejected, %d errors) in %.0f s'
            % (pv['n_accepted'], pv['n_draw'], pv['n_rejected'], pv['n_error'], pv['elapsed_s'])
        )
        for k, b in sorted(doc['predicates'].items()):
            if b['band'] is None:
                print('  %-20s NO BAND (%s)' % (k, b['why']))
            else:
                print(
                    '  %-20s band=[%s, %s] n=%d obs=[%s .. %s] rate=%.4f%% -> %s'
                    % (
                        k,
                        _fmt(b['band'][0]),
                        _fmt(b['band'][1]),
                        b['n'],
                        _fmt(b['observed']['min']),
                        _fmt(b['observed']['max']),
                        100.0 * b['rejection_rate'],
                        b['severity'],
                    )
                )

    if args.verify:
        did = True
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = MS._registry()
        cases = [(n, reg['originals'][n]['params']) for n in sorted(reg['originals'])] + [
            (n, reg['derived'][n]['params']) for n in sorted(reg['derived'])
        ]
        cal = calibration()
        print(
            'calibration: %s'
            % ('loaded from %s' % SAMPLE_FILE if cal else 'NONE — every predicate reports, none gates')
        )
        for nm, p in cases:
            v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
            v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})
            v = np.asarray(v, np.float64)
            for side in ('L', 'R'):
                res = check_hand_mesh(v, faces, side)
                _report_mesh(nm, res)
                if side == 'L':
                    f = res['frame']
                    print(
                        '        hand_length %.4f m  palm planarity %.5f m  '
                        'palmar sign margin %.1fx  finger agreement %.1f deg'
                        % (
                            f['hand_length_m'],
                            f['palm_planarity_m'],
                            f['palmar_sign_margin']['ratio'],
                            res['predicates']['thumb_opposition']['detail']['finger_agreement_deg'],
                        )
                    )
        print('\nmesh-space UNRESOLVED:')
        for u in MESH_UNRESOLVED:
            print('  %s / %s: %s' % (u['predicate'], u['part'], u['status']))
            print('     %s' % u['evidence'])

    if args.lesions:
        did = True
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = MS._registry()
        p = (reg['originals'].get(args.character) or {}).get('params') or (
            reg['derived'].get(args.character) or {}
        ).get('params')
        if p is None:
            raise SystemExit('no registered character %r' % args.character)
        v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
        v = np.asarray(MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {}), np.float64)
        base = check_hand_mesh(v, faces, 'L')['predicates']
        print('lesion test on %s, left hand — a gate that never fires is not a gate' % args.character)
        print('  %-18s %-11s %-11s %-11s %-11s %s' % ('lesion', *[k[:11] for k in PREDICATES]))
        print('  %-18s %-11s %-11s %-11s %-11s %s' % ('(intact)', *[_fmt(base[k]['observed'], 4) for k in PREDICATES]))
        for name, fn, target in LESIONS:
            dv = np.asarray(fn(v, faces, 'L'), np.float64)
            res = check_hand_mesh(dv, faces, 'L')['predicates']
            print('  %-18s %-11s %-11s %-11s %-11s %s' % (name, *[_fmt(res[k]['observed'], 4) for k in PREDICATES]))
            b, a = base[target]['observed'], res[target]['observed']
            print(
                '       -> %s %s -> %s  (%s), status %s -> %s'
                % (
                    target,
                    _fmt(b, 4),
                    _fmt(a, 4),
                    'DETECTED' if (a is None or b is None or a < b) else 'NOT DETECTED',
                    base[target]['status'],
                    res[target]['status'],
                )
            )

    if args.digits:
        did = True
        _cli_digits()

    if args.digit_lesion:
        did = True
        _cli_digit_lesion(args.character)

    if args.images is not None:
        did = True
        files = []
        for spec in args.images or []:
            if os.path.isdir(spec):
                files += sorted(glob.glob(os.path.join(spec, '*.png')))
                files += sorted(glob.glob(os.path.join(spec, '*.jpg')))
            elif any(c in spec for c in '*?['):
                files += sorted(glob.glob(spec))
            else:
                files.append(spec)
        nh = 0
        for path in files:
            res = check_hand_image(path)
            if not res['hands']:
                continue
            for hd in res['hands']:
                nh += 1
                pr = hd['predicates']
                print(
                    '%-14s %-5s via=%-5s span=%4.0fpx  arch2d=%-7s arch3d=%-7s '
                    'mid=%-7s thumb=%-6s [%s]'
                    % (
                        os.path.basename(path),
                        hd['side'] or '?',
                        hd['via'],
                        hd['span_px'],
                        _fmt(pr['knuckle_arch']['observed'], 4),
                        _fmt(pr['knuckle_arch']['detail']['world_arch'], 4),
                        _fmt(pr['middle_finger_ratio']['observed'], 4),
                        _fmt(pr['thumb_opposition']['observed'], 1),
                        ' '.join('%s=%s' % (k[:5], pr[k]['status'][:4]) for k in PREDICATES),
                    )
                )
        print('%d hands over %d files' % (nh, len(files)))
        print('image-space UNRESOLVED:')
        for u in IMAGE_UNRESOLVED:
            print('  %s: %s' % (u['predicate'], u['status']))

    if not did:
        ap.print_help()
    return 0
