# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.conditioning`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.conditioning` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.conditioning import build


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('pass_dir')
    ap.add_argument('-o', '--out', default=None)
    a = ap.parse_args(argv)
    paths = build(a.pass_dir, a.out)
    for k, v in sorted(paths.items()):
        print('  %-8s %s' % (k, v))
    return 0


if __name__ == '__main__':
    sys.exit(main())
