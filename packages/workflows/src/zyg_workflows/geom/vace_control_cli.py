# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.vace_control`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.vace_control` still reaches it.
"""

import argparse
import os
import sys

from zyg_workflows.geom.vace_control import (
    audit,
    build,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--frames', type=int, default=341)
    ap.add_argument('--mask-dir', default=None)
    ap.add_argument('--audit', action='store_true')
    a = ap.parse_args(argv)

    if a.audit:
        r = audit(a.src)
        for k, v in r.items():
            print('  %-20s %s' % (k, v))
        return 0 if r.get('ok') else 2

    out = a.out or os.path.join(a.src, 'vace_ctrl')
    r = build(a.src, out, frames=a.frames, mask_dir=a.mask_dir)
    for k, v in r.items():
        print('  %-20s %s' % (k, v))
    v = audit(out)
    print('  %-20s %s' % ('audit', v['verdict']))
    return 0 if v['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
