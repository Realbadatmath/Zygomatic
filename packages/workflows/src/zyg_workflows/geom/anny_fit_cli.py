# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.anny_fit`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.geom.anny_fit` still reaches it.
"""

import argparse
import glob
import os
import sys

import numpy as np

from zyg_workflows.geom.anny_fit import fit_cell
from zyg_workflows.geom.char_mesh import OUT_ROOT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--cells', default='')
    ap.add_argument('--char-asset', default='')
    ap.add_argument(
        '--body',
        default='',
        help='registered body to fit WITH (registry name, char_id or asset '
        'name). Rebuilds the issued recipe — phenotype, local morphs, '
        'bone scales and the recorded phalanx correction — and refuses '
        'if the rebuilt cage does not hash to the registry value.',
    )
    ap.add_argument(
        '--legacy-phenotype',
        action='store_true',
        help='the pre-2026-09-02 path: height-only calibration of the '
        'declared age from --char-asset, no locals, no bone scales. '
        'Kept for the A/B comparison only.',
    )
    ap.add_argument(
        '--out-name',
        default='anny_fit.json',
        help='report filename inside each cell dir; use this to keep a '
        'legacy run beside a registry run instead of replacing it',
    )
    a = ap.parse_args(argv)
    if a.body and a.legacy_phenotype:
        raise SystemExit(
            '--body and --legacy-phenotype are two different bodies; pick '
            'one. Run twice with different --out-name to compare them.'
        )
    root = os.path.join(OUT_ROOT, a.char_id)
    dirs = [os.path.join(root, c.strip()) for c in a.cells.split(',') if c.strip()] or sorted(
        glob.glob(os.path.join(root, 'cell_*'))
    )
    from zyg_workflows.geom import phenotype as P

    body = a.body
    if not body and not a.legacy_phenotype:
        # DEFAULT CHANGED 2026-09-02: a char_id that names a registered body now fits
        # with that body. The old default built a three-number calibration (or, when
        # --char-asset was omitted, the anny DEFAULT ADULT FEMALE) and called it the
        # character. Falling back is still allowed, but it is announced.
        body = P.resolve_body_name(a.char_id) or P.resolve_body_name(a.char_asset)
        if body:
            print(
                'body: %r resolved from %s; pass --legacy-phenotype for the old path'
                % (body, a.char_id if P.resolve_body_name(a.char_id) else a.char_asset)
            )
    spec = None
    if body:
        spec = P.registry_body(P.resolve_body_name(body))
    elif a.char_asset:
        spec = P.spec_for(char_asset=a.char_asset)
        print('body: LEGACY declared-build calibration — %s' % P.describe(spec))
    else:
        print(
            'body: none given — the anny DEFAULT body. This is almost certainly not '
            'the character; pass --body <registry name>.'
        )
    reps = []
    for d in dirs:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, 'mesh.json')):
            r = fit_cell(d, body=spec)
            if a.out_name != 'anny_fit.json':
                import shutil

                shutil.move(os.path.join(d, 'anny_fit.json'), os.path.join(d, a.out_name))
            reps.append(r)
    ok = [r for r in reps if r.get('ok')]
    good = [r for r in ok if r.get('fit_ok')]
    full = [r['mean_err_px'] for r in good if r['fit_mode'] == 'full']
    upper = [r['mean_err_px'] for r in good if r['fit_mode'] == 'upper']
    print(
        'fitted %d/%d | PASSED GATE %d (full n=%d med %.1fpx | upper n=%d med %.1fpx)'
        ' | gated %d | declined %d'
        % (
            len(ok),
            len(reps),
            len(good),
            len(full),
            np.median(full) if full else -1,
            len(upper),
            np.median(upper) if upper else -1,
            len(ok) - len(good),
            len(reps) - len(ok),
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
