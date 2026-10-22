# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.verify_refs`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.verify_refs` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.verify_refs import (
    _zyg_log,
    verify_manifest,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', default=None)
    ap.add_argument('--redo', action='store_true')
    ap.add_argument('--no-siglip', action='store_true')
    a = ap.parse_args(argv)
    changed, results = verify_manifest(a.asset, a.redo, not a.no_siglip)
    npass = sum(1 for r in results if r[1] == 'PASS')
    nfail = sum(1 for r in results if r[1] == 'FAIL')
    nun = sum(1 for r in results if r[1] == 'UNVERIFIED')
    for aid, st, msg in results:
        print('  %-8s %-20s %s' % (st, aid, msg))
    print('verified %d refs: %d show their subject, %d do NOT, %d could not be judged' % (changed, npass, nfail, nun))
    try:
        from zyg_workflows import vlm_inspector as V

        V.shutdown_workers()
    except Exception as _exc:
        _zyg_log.warning('vlm worker shutdown failed, judge vram may stay held: %s', _exc)
    return 0 if nun == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
