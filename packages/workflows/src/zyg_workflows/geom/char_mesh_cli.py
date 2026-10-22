# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.char_mesh`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.char_mesh` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.char_mesh import run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--images', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(argv)
    s = run(a.char_id, a.images, a.out, a.limit)
    for k, v in s.items():
        if k != 'region_presence':
            print('  %-22s %s' % (k, v))
    print('  regions present in N cells:')
    for k, v in sorted(s['region_presence'].items(), key=lambda kv: -kv[1]):
        print('    %-18s %d' % (k, v))
    return 0


if __name__ == '__main__':
    sys.exit(main())
