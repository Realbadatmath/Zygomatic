# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.anthro.landmarks.validation`, moved out of the library module
so that library code never prints; `python -m zyg_workflows.geom.anthro.landmarks.validation` still
reaches it.
"""

import json
import sys

from zyg_workflows.geom.anthro.landmarks.constants import (
    MS,
    REFERENCE_FRACTIONS,
    frame_report,
)
from zyg_workflows.geom.anthro.landmarks.table import resolve_landmarks, warm_cache
from zyg_workflows.geom.anthro.landmarks.validation import _ansur_check, _cases


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print('warming anchors ...', flush=True)
    print('  %d cached anchors' % warm_cache())

    print('\n=== ANSUR REFERENCE TABLE, recomputed from the microdata ===')
    chk = _ansur_check()
    if not chk:
        print('  microdata absent — table NOT verified this run')
    bad = 0
    for sex, key, wm, ws, gm, gs, n in chk:
        flag = '' if abs(wm - gm) < 5e-5 else '   <<< TABLE DRIFT'
        bad += bool(flag)
        if sex == 'male':
            print('  %-16s M shipped %.4f/%.4f  recomputed %.4f/%.4f n=%d%s' % (key, wm, ws, gm, gs, n, flag))
    print('  table drift rows: %d' % bad)

    grid = {}
    for name, phen, locs, anat, sex in _cases():
        v, faces, _ = MS._build_mesh(phen, locs)
        v = MS._apply_anatomy(v, faces, anat)
        H = float(v[:, 2].max() - v[:, 2].min())
        print('\n=== %s  (stature %.4f m, ANSUR reference sex=%s) ===' % (name, H, sex))
        if name == 'anny-neutral':
            fr = frame_report(v, faces)
            for k in (
                'up_axis',
                'anterior_axis',
                'subject_left_axis',
                'convention',
                'handedness',
                'ground_plane',
                'bilateral_symmetry_max_residual_mm',
                'mirror_map_involutive',
                'outward_normals',
                'pose',
            ):
                print('   %-34s %s' % (k, fr[k]))
        lm = resolve_landmarks(v, faces, phen, locs)
        print(
            '   %-18s %8s %8s %8s %8s  %-9s %s' % ('landmark', 'height_m', 'frac', 'ANSUR', 'z-score', 'conf', 'kind')
        )
        for k in sorted(lm):
            r = lm[k]
            if r['frac_stature'] is None:
                print('   %-18s %8s %8s %8s %8s  %-9s %s' % (k, '-', '-', '-', '-', r['confidence'], r['anchor_kind']))
                continue
            ref = REFERENCE_FRACTIONS.get(r['ansur_key'] or '')
            if ref:
                mu, sd = ref[0] if sex == 'male' else ref[1]
                zs = (r['frac_stature'] - mu) / sd
                grid.setdefault(k, {})[name] = (r['frac_stature'], mu, zs)
                print(
                    '   %-18s %8.4f %8.4f %8.4f %+8.2f  %-9s %s'
                    % (k, r['height_m'], r['frac_stature'], mu, zs, r['confidence'], r['anchor_kind'])
                )
            else:
                print(
                    '   %-18s %8.4f %8.4f %8s %8s  %-9s %s'
                    % (k, r['height_m'], r['frac_stature'], '-', '-', r['confidence'], r['anchor_kind'])
                )
        # head count is a HOUSE number; print it labelled as one, never as a citation
        if lm['menton']['frac_stature'] is not None:
            hh = 1.0 - lm['menton']['frac_stature']
            print(
                '   HOUSE head height (vertex-menton) %.1f mm = %.4f of stature '
                '-> %.2f heads tall  [no survey source exists]' % (hh * H * 1000, hh, 1.0 / hh)
            )

    names = [c[0] for c in _cases()]
    print('\n=== SUMMARY: (mesh fraction - ANSUR mean) / ANSUR SD, per landmark ===')
    print('    the neutral column is RESOLVER bias (a stock anny body); the others mix')
    print("    resolver bias with the character's own deliberate proportion morphs")
    print('   %-18s %s' % ('landmark', ' '.join('%11s' % n[:11] for n in names)))
    for k in sorted(grid):
        cells = []
        for n in names:
            cells.append('%+11.2f' % grid[k][n][2] if n in grid[k] else '%11s' % '-')
        print('   %-18s %s' % (k, ' '.join(cells)))
    print('\n   resolver bias on the stock anny body, |z| worst first:')
    worst = sorted(((abs(grid[k]['anny-neutral'][2]), k) for k in grid if 'anny-neutral' in grid[k]), reverse=True)
    for z, k in worst:
        f, mu, _ = grid[k]['anny-neutral']
        print('      %-18s %+.4f of stature vs ANSUR %.4f  (|z|=%.2f)' % (k, f - mu, mu, z))

    if '--json' in argv:
        name, phen, locs, anat, _sex = _cases()[1]
        v, faces, _ = MS._build_mesh(phen, locs)
        v = MS._apply_anatomy(v, faces, anat)
        print('\n=== full record, %s ===' % name)
        print(json.dumps(resolve_landmarks(v, faces, phen, locs), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
