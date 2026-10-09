# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.tools.plans_convert_houses`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.tools.plans_convert_houses` still reaches.
"""

import argparse
import json
import os
import sys

from zyg_workflows.tools.plans_convert_houses import (
    PLANS_OUT,
    convert_procthor,
    convert_resplan,
    write_fixtures,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', default='all', choices=['all', 'resplan', 'procthor10k'])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out', default=PLANS_OUT)
    ap.add_argument('--no-fixtures', action='store_true')
    ap.add_argument(
        '--fixtures-only', action='store_true', help='rebuild the test fixtures from an already converted pack'
    )
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for pack in ['resplan', 'procthor10k'] if a.pack == 'all' else [a.pack]:
        if a.fixtures_only:
            ix = json.load(open(os.path.join(a.out, pack, 'index.json')))
            manifest, rows = ix['pack'], ix['rows']
            print('%-12s index %d rows' % (pack, len(rows)))
        else:
            fn = convert_resplan if pack == 'resplan' else convert_procthor
            manifest, rows, stats = fn(a.out, a.limit)
            print('%-12s kept %d  dropped %s' % (pack, len(rows), dict(stats)))
        if not a.no_fixtures and rows:
            picked = write_fixtures(a.out, pack, manifest, rows)
            print('%-12s fixtures %s' % (pack, [x['id'] for x in picked]))


if __name__ == '__main__':
    sys.exit(main())
