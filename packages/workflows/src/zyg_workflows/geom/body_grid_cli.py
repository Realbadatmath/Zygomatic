# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.body_grid`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.geom.body_grid` still reaches it.
"""

import argparse
import glob
import os
import sys

from zyg_workflows.geom.body_grid import build_cell
from zyg_workflows.geom.char_mesh import OUT_ROOT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--char-asset', default='')
    ap.add_argument('--cells', default='')
    a = ap.parse_args(argv)
    root = os.path.join(OUT_ROOT, a.char_id)
    dirs = [os.path.join(root, c.strip()) for c in a.cells.split(',') if c.strip()] or sorted(
        glob.glob(os.path.join(root, 'cell_*'))
    )
    done = []
    for d in dirs:
        r = build_cell(d, a.char_asset)
        if r:
            done.append(r)
            print(
                '  %s: body=%s wrap=%s %s'
                % (r['cell'], r.get('overlay_body'), r.get('overlay_wrap'), r.get('wrap_skipped', ''))
            )
    print('grids for %d fitted cells' % len(done))
    return 0


if __name__ == '__main__':
    sys.exit(main())
