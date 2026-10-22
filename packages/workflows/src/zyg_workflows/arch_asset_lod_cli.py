# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.arch_asset_lod`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.arch_asset_lod` still reaches it.

The `--blender` dispatch that used to sit in the module's `if __name__` block lives in
`main()` here: `make_lod` re-invokes the LIBRARY file through `blender --python`, whose
`__main__` connector lands back on this `main()`.
"""

from __future__ import annotations

import os
import sys

from zyg_workflows.arch_asset_lod import (
    _blender_main,
    make_lod,
    over_budget,
)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        if '--blender' in sys.argv:
            rest = sys.argv[sys.argv.index('--blender') + 1 :]
            return _blender_main(rest)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        argv = sys.argv[1:]

    from zyg_workflows import mesh_pack_dims  # noqa: PLC0415

    flags = [a for a in argv if a.startswith('--')]
    args = [a for a in argv if not a.startswith('--')]
    trees = '--trees' in flags
    pack_filter = args[0] if (trees and args) else ''

    if '--list' in flags:
        for r in over_budget(pack_filter, trees):
            print(f'{r["tris"]:>12,}  {r["id"]}' + ('  [lod1 exists]' if r['has_lod'] else ''))
        return 0

    if trees:
        todo = [r for r in over_budget(pack_filter, True) if not r['has_lod']]
    else:
        todo = []
        for a in args:
            pack, _, item = a.partition('|')
            hit = [r for r in over_budget(pack) if r['item'] == item]
            if not hit:
                print(f'{a}: not over the budget (or not catalogued) — nothing to do')
                continue
            todo.append(hit[0])
    if not todo:
        print('nothing to decimate')
        return 0

    packs, bad = set(), 0
    for r in todo:
        res = make_lod(r['pack'], r['item'], r['tris'])
        print(('OK   ' if res['ok'] else 'FAIL ') + res['id'] + ' -> ' + (res.get('lod') or res.get('why') or ''))
        if res['ok']:
            packs.add(r['pack'])
        else:
            bad += 1
    if packs:
        # the new files must be measured and counted or the catalogue lists
        # them with no size and the budget cannot see them either
        print(mesh_pack_dims.run(sorted(packs), False))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
