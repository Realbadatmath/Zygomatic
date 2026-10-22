# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.review_gallery`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.review_gallery` still reaches it.
"""

import argparse
import os
import sys

from zyg_workflows.geom.review_gallery import (
    ROOT,
    collect,
    default_items,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', default=os.path.join(ROOT, 'output/axe_forest/tree'))
    ap.add_argument('-o', '--out', default=os.path.join(ROOT, 'output/axe_forest/REVIEW'))
    ap.add_argument('--extra', nargs='*', default=[])
    a = ap.parse_args(argv)
    items = default_items(a.scene) + [(p, os.path.basename(p)) for p in a.extra]
    got = collect(a.out, items)
    print('  %d images -> %s/gallery.html' % (len(got), a.out))
    for g in got:
        print('    %s' % g['file'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
