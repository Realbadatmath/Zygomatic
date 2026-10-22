# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh.test_sheet_render`, moved out of the library
module so that library code never prints; `python -m zyg_workflows.prop_mesh.test_sheet_render`
still reaches it.
"""

import sys

from zyg_workflows.prop_mesh.test_sheet_render import (
    CHECKS,
    FAILS,
    check_asset,
    check_creature_op,
    check_licence_resolution,
)


def main(argv=None):
    from zyg_workflows import prop_mesh_library as PML

    argv = sys.argv[1:] if argv is None else argv
    check_licence_resolution()
    check_creature_op()
    ids = list(argv) or [
        r['id'] for r in PML.list_assets() if (r.get('provenance') or {}).get('renderer') == 'prop_mesh/sheet_render.py'
    ]
    if not ids:
        FAILS.append('no asset was built by prop_mesh/sheet_render.py — nothing to check')
    for aid in ids:
        check_asset(aid)
    print('assets checked: %s' % (', '.join(ids) or '(none)'))
    print('%d checks, %d failures' % (CHECKS[0], len(FAILS)))
    for f in FAILS:
        print('  FAIL %s' % f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
