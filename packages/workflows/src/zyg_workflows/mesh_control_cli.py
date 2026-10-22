# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.mesh_control`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.mesh_control` still reaches it.
"""

import sys

from zyg_workflows.mesh_control import __doc__ as _LIB_DOC
from zyg_workflows.mesh_control import (
    DEFAULT_EXCLUDE,
    DEFAULT_KINDS,
    build,
)


def _main():
    import argparse

    ap = argparse.ArgumentParser(description=_LIB_DOC.split('\n')[0])
    ap.add_argument('asset_id')
    ap.add_argument('--views', nargs='*', default=None)
    ap.add_argument('--exclude', nargs='*', default=list(DEFAULT_EXCLUDE))
    ap.add_argument('--kinds', nargs='*', default=list(DEFAULT_KINDS))
    ap.add_argument('--normalize', choices=('view', 'asset'), default='view')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    man = build(
        a.asset_id,
        a.views,
        exclude=tuple(a.exclude),
        kinds=tuple(a.kinds),
        normalize=a.normalize,
        force=a.force,
        log_fn=print,
    )
    for vid, e in man['views'].items():
        got = [k for k in a.kinds if e.get(k)]
        print(
            '  %-14s near %.4f far %.4f  %5.2f%% of frame  %s%s'
            % (
                vid,
                e.get('near_m', 0),
                e.get('far_m', 0),
                100 * e.get('coverage', 0),
                ','.join(got),
                '  UNAVAILABLE: %s' % ','.join(e['unavailable']) if e.get('unavailable') else '',
            )
        )
    if man['skipped']:
        print('  skipped:', man['skipped'])


if __name__ == '__main__':
    sys.exit(_main())
