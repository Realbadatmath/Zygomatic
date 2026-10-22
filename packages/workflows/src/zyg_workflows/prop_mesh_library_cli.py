# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh_library`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.prop_mesh_library` still reaches it.
"""

import json
import sys

from zyg_workflows import prop_mesh_library as _mod
from zyg_workflows.prop_mesh_library import (
    ROOT,
    get,
    list_assets,
    verify,
    views,
)


def _main():
    import argparse

    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verify', nargs='?', const='*', metavar='ASSET_ID')
    ap.add_argument('--show', metavar='ASSET_ID')
    a = ap.parse_args()
    if a.show:
        rec = get(a.show)
        if not rec:
            raise SystemExit('no such asset: %s' % a.show)
        rec = dict(rec)
        rec['sha256'] = '%d files' % len(rec.get('sha256') or {})
        print(json.dumps(rec, indent=2))
        print('\nviews:')
        for v in views(a.show):
            print(
                '  %-14s az %-6s el %-4s  beauty=%s depth=%s'
                % (v['id'], v['azimuth'], v['elevation'], 'y' if v['beauty'] else '-', 'y' if v['depth'] else '-')
            )
        return
    if a.verify:
        res = verify(None if a.verify == '*' else a.verify)
        if not res:
            raise SystemExit('nothing registered')
        for aid, r in sorted(res.items()):
            print(
                '%-20s %s  (%d files)%s'
                % (
                    aid,
                    'VERIFIED' if r['ok'] else 'MISMATCH',
                    r['files'],
                    '' if r['ok'] else '  bad=%s missing=%s' % (r['bad'][:4], r['missing'][:4]),
                )
            )
        raise SystemExit(0 if all(r['ok'] for r in res.values()) else 1)
    rows = list_assets()
    if not rows:
        print('no prop meshes registered (%s)' % ROOT)
        return
    for r in rows:
        g = r.get('geometry') or {}
        sz = g.get('size_m') or {}
        print(
            '%-16s %-26s %s  %s verts / %s tris  %sx%sx%s m  %d views  %s'
            % (
                r['id'],
                r.get('name', '')[:26],
                r.get('kind', ''),
                g.get('vertices', '?'),
                g.get('triangles', '?'),
                sz.get('width', '?'),
                sz.get('depth', '?'),
                sz.get('height', '?'),
                len((r.get('views') or {}).get('ids') or []),
                (r.get('licence') or {}).get('id', 'UNDECLARED'),
            )
        )


if __name__ == '__main__':
    sys.exit(_main())
