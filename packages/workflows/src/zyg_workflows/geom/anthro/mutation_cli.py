# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.geom.anthro.mutation`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.geom.anthro.mutation` still reaches.
"""

import argparse
import json
import os
import sys

from zyg_workflows.geom.anthro.mutation import (
    ARTEFACT,
    DEFAULT_SUBJECT,
    PANEL,
    _jsonable,
    run,
)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='geom.anthro.mutation')
    ap.add_argument('--subject', default=DEFAULT_SUBJECT)
    ap.add_argument('--mutations', nargs='*', default=None)
    ap.add_argument('--tiers', nargs='*', type=int, default=None)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--out', default=ARTEFACT)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)

    if a.list:
        for n, _fn, breaks in PANEL:
            print('%-26s breaks: %s' % (n, breaks))
        return 0

    rec = run(subject=a.subject, mutations=a.mutations, tiers=a.tiers)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fh:
        json.dump(_jsonable(rec), fh, indent=2, sort_keys=True)

    if a.json:
        print(json.dumps(_jsonable(rec), indent=2, sort_keys=True))
    else:
        print()
        print('FINDINGS (%d) — artefact: %s' % (len(rec['findings']), a.out))
        for f in rec['findings']:
            print(
                '  [%s] %-30s %s  via %s'
                % (
                    f['severity'],
                    f['gate'],
                    f['kind'],
                    ', '.join(f['mutations'][:3])
                    + (' +%d' % (len(f['mutations']) - 3) if len(f['mutations']) > 3 else ''),
                )
            )
        if not rec['findings']:
            print(
                '  none — every gate that passed the clean body reacted to at least one '
                'deliberate break, and none crashed or ducked.'
            )
    return 0


if __name__ == '__main__':
    sys.exit(main())
