# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.track_plates`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.track_plates` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.track_plates import __doc__ as _LIB_DOC
from zyg_workflows.geom.track_plates import (
    build,
    contact_strip,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=_LIB_DOC.split('\n')[0])
    ap.add_argument('track')
    ap.add_argument('--modes', default='depth,normal,skeleton,seg,composite')
    ap.add_argument('--size', default=None, help='WxH of the render, e.g. 832x480')
    ap.add_argument('--strip', default='composite', help='mode to write a contact strip for, or "" for none')
    a = ap.parse_args(argv)
    size = None
    if a.size:
        w, h = a.size.lower().split('x')
        size = (int(w), int(h))
    rep = build(a.track, modes=tuple(m.strip() for m in a.modes.split(',') if m.strip()), size=size)
    if a.strip:
        p = contact_strip(a.track, mode=a.strip)
        if p:
            print('  strip: %s' % p)
    bad = [m for m, v in rep['modes'].items() if not v['audit_ok']]
    if bad:
        print('  STILL CONSTANT: %s' % ', '.join(bad))
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
