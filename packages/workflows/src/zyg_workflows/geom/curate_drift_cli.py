# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.curate_drift`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.curate_drift` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.curate_drift import apply, plan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    quarantine, warn, evidence = plan(a.char_id)
    print('%s: quarantine %d cells %s' % (a.char_id, len(quarantine), quarantine))
    print('  warnings (kept): %d cells %s' % (len(warn), warn[:10]))
    for c in quarantine:
        ev = ', '.join('%s/%s' % (e['region'], e['axis']) for e in evidence[c])
        print('    %-9s %s' % (c, ev))
    if a.apply:
        apply(a.char_id, quarantine, evidence)
    else:
        print('  DRY RUN — pass --apply to move files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
