# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.char_control`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.char_control` still reaches it.
"""

import argparse
import glob
import os
import sys

from zyg_workflows.geom.char_control import build_cell
from zyg_workflows.geom.char_mesh import OUT_ROOT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--cells', default='')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-o', '--out', default=None)
    a = ap.parse_args(argv)

    root = os.path.join(OUT_ROOT, a.char_id)
    if a.cells:
        dirs = [os.path.join(root, c.strip()) for c in a.cells.split(',')]
    else:
        dirs = sorted(d for d in glob.glob(os.path.join(root, 'cell_*')) if os.path.isdir(d))
    done = 0
    for d in dirs:
        if not os.path.exists(os.path.join(d, 'mesh.json')):
            continue
        paths = build_cell(d)
        done += 1
        if done <= 4:
            print('  %s: %s' % (os.path.basename(d), ', '.join(sorted(paths))))
    print('  control maps for %d cells' % done)

    if a.frames and dirs:
        from . import vace_control

        src = os.path.join(dirs[0], 'control', 'seg.png')
        out = a.out or os.path.join(root, 'vace_ctrl')
        r = vace_control.build(src, out, frames=a.frames)
        print('  VACE ctrl: %s (%d frames, grey %.4f%%)' % (r['ctrl_dir'], r['frames'], r['grey_fraction_mean'] * 100))
    return 0


if __name__ == '__main__':
    sys.exit(main())
