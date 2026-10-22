# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh.sheet_register`, moved out of the library
module so that library code never prints; `python -m zyg_workflows.prop_mesh.sheet_register`
still reaches it.
"""

import argparse
import json
import os
import sys
import time

from zyg_workflows.prop_mesh import sheet_register as _mod
from zyg_workflows.prop_mesh.sheet_register import _ROOT, _load, pack_licence, render


def _main():
    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
    ap.add_argument('--glb', required=True)
    ap.add_argument('--id', required=True, help='asset_id in the prop-mesh registry')
    ap.add_argument('--name', default='')
    ap.add_argument('--kind', default='prop')
    ap.add_argument('--description', default='')
    ap.add_argument('--tags', default='')
    ap.add_argument('--creature-id', default=None)
    ap.add_argument('--build-dir', default=None)
    ap.add_argument('--samples', type=int, default=48)
    ap.add_argument('--res', type=int, default=1024)
    ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--views', nargs='*', default=None)
    ap.add_argument('--blender-arg', action='append', default=[], help='passed straight through to sheet_render.py')
    ap.add_argument('--control', action='store_true', help='run mesh_control.build on the registered asset')
    ap.add_argument('--kinds', nargs='*', default=['depth', 'normal', 'lineart', 'segment', 'matte'])
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--skip-render', action='store_true', help='reuse an existing build dir')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    glb = os.path.abspath(a.glb)
    if not os.path.isfile(glb):
        raise SystemExit('no such GLB: %s' % glb)
    meta = pack_licence(glb)
    if not meta:
        raise SystemExit(
            'REFUSED: %s is not under a mesh pack with a PROVENANCE.json. An asset with '
            'a guessed licence is worse than no asset — add the pack provenance first.' % glb
        )
    print('[licence] %s  (%s)' % (meta['licence']['spdx'], meta['provenance']['pack']))
    print('[licence] evidence: %s' % meta['licence']['evidence_url'])
    if a.dry_run:
        print(json.dumps(meta, indent=2))
        return 0

    build = a.build_dir or os.path.join(_ROOT, 'output', 'prop_sheets', a.id)
    if not a.skip_render:
        rc, _ = render(glb, build, samples=a.samples, res=a.res, scale=a.scale, views=a.views, extra=a.blender_arg)
        if rc != 0:
            raise SystemExit('sheet render failed (rc=%d) — nothing registered' % rc)
    sheet = _load(os.path.join(build, 'sheet.json'))
    if not sheet:
        raise SystemExit('no readable sheet.json in %s' % build)

    # trimesh is what geometry_stats and export_mesh3d are built on, and register()
    # swallows their failure into an {'error': ...} field. Measured: run under the
    # server venv (no trimesh) the record comes back with size_m null and no mesh3d.bin,
    # so the library card has no 3D preview and nothing can read the asset's real-world
    # size — a half-registered asset that verify() still calls ok. Refuse instead.
    try:
        import trimesh  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            'REFUSED: %s has no trimesh, so the record would carry no size_m and no '
            'mesh3d.bin. Re-run under /usr/bin/python3.12.' % sys.executable
        ) from exc

    from zyg_workflows import prop_mesh_library as PML

    rec = PML.register(
        a.id,
        build,
        name=a.name or a.id,
        kind=a.kind,
        creature_id=a.creature_id,
        description=a.description,
        tags=[t for t in a.tags.split(',') if t],
        licence=meta['licence'],
        provenance=dict(
            meta['provenance'],
            sheet_views=len(sheet.get('views') or []),
            samples=sheet.get('samples'),
            res=[sheet.get('w'), sheet.get('h')],
        ),
        registered=time.strftime('%Y-%m-%dT%H:%M:%S'),
        replace=a.replace,
    )
    print(
        '[register] %s  %d files  %.1f MB  views=%d passes=%d'
        % (a.id, len(rec['sha256']), rec['bytes'] / 1e6, rec['views']['beauty'], rec['views']['passes'])
    )
    print('[register] size_m %s' % json.dumps(rec['geometry'].get('size_m')))
    v = PML.verify(a.id)[a.id]
    print('[verify] ok=%s files=%d bad=%s missing=%s' % (v['ok'], v['files'], v['bad'], v['missing']))
    if not v['ok']:
        return 2

    if a.control:
        from zyg_workflows import mesh_control as MC

        man = MC.build(a.id, kinds=tuple(a.kinds), force=True, log_fn=print)
        print('[control] views=%d skipped=%s' % (len(man['views']), man['skipped'] or '{}'))
        if man['skipped']:
            return 4
    return 0


if __name__ == '__main__':
    sys.exit(_main())
