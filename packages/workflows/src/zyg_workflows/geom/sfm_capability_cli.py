# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.sfm_capability`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.sfm_capability` still reaches it.
"""

import json
import sys

from zyg_workflows.geom.sfm_capability import (
    AVAILABLE,
    probe,
    record_baseline,
    summary_lines,
)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog='geom.sfm_capability')
    ap.add_argument(
        '--deep',
        action='store_true',
        help='also execute the dense-stereo entry point (slow; run after any build or driver change)',
    )
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--record-baseline', action='store_true')
    ap.add_argument(
        '--fail-on-broken', action='store_true', help='exit 2 if anything is BROKEN (for CI / preflight use)'
    )
    a = ap.parse_args(argv)

    if a.record_baseline:
        path, rec = record_baseline(deep=a.deep)
        print('baseline written: %s' % path)
        for ln in summary_lines(dict(rec, baseline={'status': AVAILABLE, 'reason': 'just recorded'})):
            print('  ' + ln)
        return 0

    rec = probe(deep=a.deep)
    if a.json:
        print(json.dumps(rec, indent=2, sort_keys=True, default=str))
    else:
        print('SFM / CUDA CAPABILITY  —  overall: %s  (%.2fs)' % (rec['status'], rec['elapsed_s']))
        for ln in summary_lines(rec):
            print('  ' + ln)
        if rec['broken']:
            print()
            print('BROKEN: %s' % ', '.join(rec['broken']))
    return 2 if (a.fail_on_broken and rec['broken']) else 0


if __name__ == '__main__':
    sys.exit(main())
