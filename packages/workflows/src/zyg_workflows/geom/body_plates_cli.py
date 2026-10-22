# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.body_plates`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.body_plates` still reaches it.
"""

from __future__ import annotations

import sys

from zyg_workflows.geom.body_plates import build, registered_names


def _main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('names', nargs='*', default=None, help='default: every registered body')
    ap.add_argument('--views', nargs='*', default=None)
    ap.add_argument('--size', type=int, default=768)
    ap.add_argument('--samples', type=int, default=24)
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    names = a.names or registered_names()
    rc = 0
    for n in names:
        try:
            man = build(n, views=a.views, size=a.size, samples=a.samples, force=a.force, log_fn=print)
        except Exception as exc:  # noqa: BLE001
            print(f'{n}: FAILED — {type(exc).__name__}: {exc}')
            rc = 1
            continue
        for vid, st in (man.get('ledger') or {}).items():
            print('  %-6s %s' % (vid, '  '.join('%s=%s' % (k, v['state']) for k, v in sorted(st.items()))))
    return rc


if __name__ == '__main__':
    sys.exit(_main())
