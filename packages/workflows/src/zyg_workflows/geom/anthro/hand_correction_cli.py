# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.geom.anthro.hand_correction`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.geom.anthro.hand_correction` still reaches.
"""

import json
import math
import sys

from zyg_workflows.geom.anthro.hand_correction import (
    CORRECTED_DIGITS,
    GATE_Z_BEFORE_SIGFIGS,
    GATE_Z_CORRECTED_MAX,
    _anisotropy,
    _close_sigfigs,
    _hand_length_sd_mm,
    _hands,
    _scales_equal,
    _zyg_log,
    effective_scales,
    merge,
    solve,
)


def self_test(phenotype=None, local_changes=None, verbose=True):
    """Prove the correction on evidence the solver did not use.

    Five checks, and the third is the only one that is not circular:
      1. every corrected ratio lands inside the published band (it lands on the centre,
         so this is a sanity check on the plumbing, not a test)
      2. the finger ray is unchanged, and so is hand length
      3. HELD OUT — the corrected ABSOLUTE segment lengths, which the solver never saw
         (it only ever used two ratios), against BK2010's published millimetres scaled by
         this hand's own size. A correction fitted to ratios has no way to make this pass
         unless the ratios are right AND the hand is the size it claims to be.
      4. finger girth is untouched: this is a length edit, not a thickness edit
      5. every chain join still closes to 0 mm — the fingers did not come apart
    """
    H = _hands()
    phen = phenotype or {'gender': 0.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5}
    rec = solve(phen, local_changes)
    sc = rec['scales']
    sk0 = H.skeleton(phen, local_changes, None, apply_hand_correction=False)
    sk1 = H.skeleton(phen, local_changes, sc, apply_hand_correction=False)
    fails = []

    def say(*a):
        if verbose:
            _zyg_log.info(' '.join(str(x) for x in a))

    say('=== 1. corrected ratios against the published bands ===')
    say('  %-8s %10s %10s %10s   %-22s' % ('finger', 'before', 'after', 'centre', 'band'))
    for d in CORRECTED_DIGITS:
        b = H._ratio_band(d, 'mid_over_prox')
        lo, hi = b['centre'] - b['half_width'], b['centre'] + b['half_width']
        a0 = rec['before'][d]['mid_over_prox']
        a1 = rec['after'][d]['mid_over_prox']
        ok = lo <= a1 <= hi
        if not ok:
            fails.append('%s mid/prox %.4f outside [%.4f, %.4f]' % (d, a1, lo, hi))
        say('  %-8s %10.4f %10.4f %10.4f   [%.4f, %.4f] %s' % (d, a0, a1, b['centre'], lo, hi, 'ok' if ok else 'FAIL'))

    say('=== 2. ray held exactly; hand CHORD moves, and by how much matters ===')
    worst = max(abs(v) for v in rec['ray_length_change_mm'].values())
    say('  worst finger ray (arc) change: %.3e mm' % worst)
    if worst > 1e-6:
        fails.append('ray moved by %.3e mm' % worst)
    ix = sk0['index']
    h0 = float(((sk0['tail'][ix['finger3-3.L']] - sk0['head'][ix['metacarpal2.L']]) ** 2).sum() ** 0.5) * 1000
    h1 = float(((sk1['tail'][ix['finger3-3.L']] - sk1['head'][ix['metacarpal2.L']]) ** 2).sum() ** 0.5) * 1000
    # The ARC along the bone chain is held by construction. The CHORD is not, and cannot
    # be: anny's rest finger is curled (consecutive bone axes differ by 7.6-25.6 deg), so
    # moving length from the distal end to the proximal end straightens the chain slightly
    # and lengthens the straight-line distance. This is a real consequence of the fix, not
    # a rounding error, so it is measured against an EXTERNAL bar rather than against a
    # tolerance chosen to make it pass: one tenth of the ANSUR II population SD for hand
    # length. A shift that small cannot move any population gate.
    sd_mm = _hand_length_sd_mm(phen)
    d_mm = h1 - h0
    say('  hand chord (metacarpal2 head -> middle fingertip): %.4f -> %.4f mm (%+.4f)' % (h0, h1, d_mm))
    if sd_mm:
        say('  that is %.3f ANSUR II population SD (1 SD = %.2f mm)' % (abs(d_mm) / sd_mm, sd_mm))
        if abs(d_mm) > 0.1 * sd_mm:
            fails.append('hand chord moved %.4f mm = %.3f population SD (bar is 0.1)' % (d_mm, abs(d_mm) / sd_mm))
    elif abs(d_mm) > 1.0:
        fails.append('hand chord moved %.4f mm and no population SD was readable' % d_mm)

    say('=== 3. HELD OUT: absolute mm vs BK2010, which the solver never read ===')
    say('  %-8s %-9s %9s %9s %9s' % ('finger', 'segment', 'corrected', 'BK scaled', 'error'))
    # scale BK's published lengths by this hand's size, measured on the ray total
    for d in CORRECTED_DIGITS:
        bk = H.BK2010[d]
        bk_seg = [bk['proximal'][0], bk['middle'][0], bk['distal'][0] + bk['tip'][0]]
        bk_ray = sum(bk_seg)
        ray = rec['after'][d]['ray_mm']
        got = [rec['after'][d][k] for k in ('proximal_mm', 'middle_mm', 'distal_mm')]
        for nm, g, b in zip(('proximal', 'middle', 'distal'), got, bk_seg):
            exp = b * ray / bk_ray
            err = 100.0 * (g / exp - 1.0)
            # 3 SD of BK's own published SD on that segment, as a percentage of its mean
            i = {'proximal': 'proximal', 'middle': 'middle', 'distal': 'distal'}[nm]
            sd = bk[i][1] if i != 'distal' else math.hypot(bk['distal'][1], bk['tip'][1])
            tol = 300.0 * sd / b
            ok = abs(err) <= tol
            if not ok:
                fails.append('%s %s off by %.1f%% (3 SD is %.1f%%)' % (d, nm, err, tol))
            say(
                '  %-8s %-9s %9.2f %9.2f %+8.1f%%  (3 SD = %.1f%%) %s'
                % (d, nm, g, exp, err, tol, 'ok' if ok else 'FAIL')
            )

    say('=== 4. girth untouched (this is a length edit) ===')
    import numpy as np

    from zyg_workflows.geom import mesh_skeletons as MS

    v0, _f, _a = MS._build_mesh(phen, local_changes, None)
    v1, _f, _a = MS._build_mesh(phen, local_changes, sc)
    W = H.rig()['weights']
    for d in CORRECTED_DIGITS:
        _b, prox, _m, _dd = H.DIGIT_BONES[d]
        for sk, v, tag in ((sk0, v0, 'before'), (sk1, v1, 'after')):
            j = sk['index']['%s.L' % prox]
            hh, tt = sk['head'][j], sk['tail'][j]
            ax = (tt - hh) / np.linalg.norm(tt - hh)
            sel = np.where(W['%s.L' % prox] >= 0.5)[0]
            P = v[sel] - hh
            g = float(np.linalg.norm(P - np.outer(P @ ax, ax), axis=1).mean()) * 1000
            if tag == 'before':
                g0 = g
            else:
                d_pct = 100.0 * (g / g0 - 1.0)
                ok = abs(d_pct) <= 2.0
                if not ok:
                    fails.append('%s girth moved %.1f%%' % (d, d_pct))
                say('  %-8s proximal girth %.3f -> %.3f mm (%+.2f%%) %s' % (d, g0, g, d_pct, 'ok' if ok else 'FAIL'))

    say('=== 5. chain joins still close ===')

    def _worst_gap(sk):
        g = 0.0
        for dd in CORRECTED_DIGITS:
            bones = [b for b in H.DIGIT_BONES[dd] if b]
            for a, b in zip(bones[:-1], bones[1:]):
                for s in ('L', 'R'):
                    ja, jb = sk['index']['%s.%s' % (a, s)], sk['index']['%s.%s' % (b, s)]
                    g = max(g, float(((sk['head'][jb] - sk['tail'][ja]) ** 2).sum() ** 0.5) * 1000)
        return g

    # Compared against the UNCORRECTED chain, not against zero. Both numbers are float64
    # accumulation through four 4x4 products at metre scale, so the question is never "is
    # it zero" — it is "did the correction pull the chain apart", and only the baseline
    # can answer that.
    g0, g1 = _worst_gap(sk0), _worst_gap(sk1)
    say('  worst chain gap: %.3e mm uncorrected -> %.3e mm corrected' % (g0, g1))
    if g1 > max(1e-4, 50.0 * max(g0, 1e-12)):
        fails.append('chain gap grew from %.3e to %.3e mm' % (g0, g1))

    say('=== 6. no shear: cross-sections stay as round as they were ===')
    # A Y-ONLY scale is anisotropic, so unlike the uniform scale in
    # hands.phalanx_scale_recipe it can shear a child bone's frame. Girth (check 4) is a
    # MEAN radius and would not notice a circle becoming an ellipse of the same
    # circumference, so the two principal cross-section axes are compared directly.
    for d in CORRECTED_DIGITS:
        _b, prox, mid, dist = H.DIGIT_BONES[d]
        for bone in (prox, mid, dist):
            r0 = _anisotropy(v0, sk0, bone, W)
            r1 = _anisotropy(v1, sk1, bone, W)
            if r0 is None or r1 is None:
                continue
            ch = 100.0 * (r1 / r0 - 1.0)
            ok = abs(ch) <= 5.0
            if not ok:
                fails.append('%s cross-section anisotropy moved %.1f%%' % (bone, ch))
            say('  %-12s anisotropy %.4f -> %.4f (%+.2f%%) %s' % (bone, r0, r1, ch, 'ok' if ok else 'FAIL'))

    say('')
    if fails:
        say('SELF-TEST FAILED (%d):' % len(fails))
        for f in fails:
            say('  - %s' % f)
    else:
        say('self-test passed: %d iterations, residual %.2e' % (rec['iterations'], rec['residual']))
    return fails


def gate_self_test(verbose=True):
    """THE SPLIT-BRAIN REGRESSION TEST: does t5_phalanx_ratio measure the DELIVERED hand?

    The failure this catches is not a wrong number, it is a right number about the wrong
    body. `skeleton()` and `mesh_skeletons._build_mesh` are two doors onto one cage, and
    both compose the correction through `effective_scales(..., params)`. Reach either one
    with params=None and it takes the FRESH-BUILD branch: it re-solves a correction from
    the phenotype rather than reusing the one the body was issued with. For a body issued
    under the current solver those two answers agree to ~1e-14, so the omission is
    invisible on today's roster and becomes a silent lie the moment the solver, the
    library or the recorded version moves.

    So the test asserts the three-state contract from both directions, per body:

      1. WITH its recorded hand_correction, every one of the 8 gated ratios (4 fingers x
         mid/prox and dist/mid) reports |z| <= GATE_Z_CORRECTED_MAX. This is the claim
         "the gate is reading the corrected chain".
      2. WITHOUT one (params carrying hand_correction=None, the pre-correction body
         contract), the worst mid/prox z reproduces the body's OWN recorded `before`
         value to GATE_Z_BEFORE_SIGFIGS. This is the null: it proves 1 is a measurement
         of the correction and not of a gate that reports ~0 no matter what it is given.
      3. The two doors return the same effective scales for the same recipe, which is
         what makes 1 a statement about the cage that shipped rather than about the rig
         alone.

    A gate that passed 1 while failing 2 would be measuring nothing.
    """
    import glob as _glob
    import json as _json
    import os as _os

    H = _hands()

    def say(*a):
        if verbose:
            _zyg_log.info(' '.join(str(x) for x in a))

    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    root = _os.path.join(_os.path.dirname(here), 'data', 'assets', 'mesh_skeletons')
    bodies = {}
    for p in sorted(_glob.glob(_os.path.join(root, '*', '*', 'params.json'))):
        bodies[_os.path.basename(_os.path.dirname(p))] = _json.load(open(p))
    if not bodies:
        _zyg_log.info(
            'NO REGISTERED BODIES under %s — this test measures nothing, so it FAILS '
            'rather than passing vacuously.' % root
        )
        return False

    fails, n_ratio = [], 0
    say('=== t5_phalanx_ratio measures the DELIVERED hand (%d bodies) ===' % len(bodies))
    for name in sorted(bodies):
        P = bodies[name]
        phen = P['phenotype']
        loc = P.get('local_changes') or None
        bs = P.get('bone_scales') or None
        hc = P.get('hand_correction')
        if not hc or not hc.get('applied'):
            say('  %-14s no recorded correction — pre-fix body, skipped by contract' % name)
            continue

        # 1. corrected: every gated ratio on the band centre
        r = H.check_phalanx_ratio(phen, loc, bs, 'L', None, None, params={'hand_correction': hc})
        det = r.get('detail') or {}
        worst_ratio = 0.0
        for d in CORRECTED_DIGITS:
            row = (det.get('fingers') or {}).get(d) or {}
            for kind in ('mid_over_prox', 'dist_over_mid'):
                cell = row.get(kind)
                if not cell or 'z_conservative' not in cell:
                    fails.append('%s: no z for %s.%s' % (name, d, kind))
                    continue
                n_ratio += 1
                z = abs(float(cell['z_conservative']))
                worst_ratio = max(worst_ratio, z)
                if z > GATE_Z_CORRECTED_MAX:
                    fails.append('%s %s.%s corrected |z|=%.3e > %.0e' % (name, d, kind, z, GATE_Z_CORRECTED_MAX))

        # 2. the null: uncorrected must reproduce this body's own recorded `before`
        r0 = H.check_phalanx_ratio(phen, loc, bs, 'L', None, None, params={'hand_correction': None})
        got = float(r0['observed'])
        zs = [
            abs(
                (rec['mid_over_prox'] - H._ratio_band(d, 'mid_over_prox')['centre'])
                / H._ratio_band(d, 'mid_over_prox')['sd_propagated']
            )
            for d, rec in (hc.get('before') or {}).items()
            if 'mid_over_prox' in rec
        ]
        if not zs:
            fails.append(
                '%s: hand_correction records no `before` block, so the '
                'uncorrected reading has nothing to be checked against' % name
            )
            want = float('nan')
        else:
            want = max(zs)
            if not _close_sigfigs(got, want, GATE_Z_BEFORE_SIGFIGS):
                fails.append('%s uncorrected z=%.17g != recorded before %.17g' % (name, got, want))
            if r0['status'] != 'fail':
                fails.append(
                    '%s uncorrected chain reports %r, not fail — the gate no '
                    'longer detects the defect it exists for' % (name, r0['status'])
                )

        # 3. one door
        s_mesh, _hc_m = effective_scales(phen, loc, bs, {'hand_correction': hc})
        sk = H.skeleton(phen, loc, bs, params={'hand_correction': hc})
        s_skel = (sk.get('hand_correction') or {}).get('scales')
        if (s_skel or {}) != (hc.get('scales') or {}):
            fails.append('%s: skeleton() did not reuse the RECORDED scales' % name)
        if not _scales_equal(s_mesh, merge(bs, hc.get('scales'))):
            fails.append('%s: _build_mesh door and the record disagree on scales' % name)

        say(
            '  %-14s corrected worst |z| = %.2e over 8 ratios | uncorrected %.15g '
            '(recorded before %.15g) | one door: %s'
            % (name, worst_ratio, got, want, 'yes' if (s_skel or {}) == (hc.get('scales') or {}) else 'NO')
        )

    say('  %d gated ratios checked on the corrected chain' % n_ratio)
    if fails:
        _zyg_log.info('FAIL (%d):' % len(fails))
        for f in fails:
            _zyg_log.info(' '.join(str(a) for a in ('  -', f)))
        return False
    say('OK — the gate reads the corrected chain, and reads the shipped one when there is no correction to read.')
    return True


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        prog='python3 -m zyg_workflows.geom.anthro.hand_correction', description=__doc__.split('\n')[0]
    )
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument(
        '--gate-self-test',
        action='store_true',
        help='the split-brain regression test: t5_phalanx_ratio must read '
        'the delivered hand, and the uncorrected chain must still '
        'reproduce each body`s recorded `before` value',
    )
    ap.add_argument('--solve', action='store_true', help='solve and print the correction for every registered body')
    a = ap.parse_args(argv)
    did = False
    if a.self_test:
        did = True
        return 1 if self_test() else 0
    if a.gate_self_test:
        did = True
        return 0 if gate_self_test() else 1
    if a.solve:
        did = True
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = json.load(open(MS.REGISTRY))
        bodies = [
            (
                'anny-neutral(control)',
                {
                    'phenotype': {
                        'gender': 0.0,
                        'age': 0.5,
                        'muscle': 0.5,
                        'weight': 0.5,
                        'height': 0.5,
                        'proportions': 0.5,
                    }
                },
            )
        ]
        for grp in ('originals', 'derived'):
            for n, e in (reg.get(grp) or {}).items():
                bodies.append(('%s/%s' % (grp, n), e['params']))
        for name, p in bodies:
            rec = solve(p['phenotype'], p.get('local_changes') or None)
            print('%-24s iters %d residual %.1e' % (name, rec['iterations'], rec['residual']))
            for b, s in sorted(rec['scales'].items()):
                print('    %-12s Y=%.6f' % (b, s[1]))
    if not did:
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
