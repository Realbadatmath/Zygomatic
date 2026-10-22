#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_asset_lod.py — decimate a pack model that is too heavy to place.

Why (2026-09-11): the live 20-storey job 94f5813b came out at 15.66 M triangles.
15.5 M of those were four copies of polyhaven_arch|jacaranda_tree_2k, which is
3,863,832 triangles on its own — a photoscan meant to be looked at, not planted
in an avenue. The catalogue now counts triangles (mesh_pack_dims.py 'tris') and
the placement tools hold anything they place to architecture_assets.TRI_BUDGET,
so a model over the budget is only placeable once a stand-in exists. This makes
the stand-in.

    python3 arch_asset_lod.py --list                       what is over budget
    python3 arch_asset_lod.py polyhaven_arch|jacaranda_tree_2k
    python3 arch_asset_lod.py --trees polyhaven_arch       every tree over it

The stand-in is `<same dir>/<architecture_assets.lod_stem(item)>.glb` — a GLB
beside the original, so it is catalogued by the ordinary pack scan and served by
the ordinary asset route. Blender does the collapse (a Decimate modifier keeps
UVs and materials, which is the whole point of using it rather than a script);
this file is also the script Blender runs, re-entered behind `--blender`.
"""

from __future__ import annotations

import os
import subprocess
import sys

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')

# Aim under the budget rather than at it: the Decimate ratio is on the input
# triangles and collapse rarely lands exactly. 0.02 is the floor — below that a
# canopy stops reading as leaves at any distance.
TARGET_FRACTION = 0.8
MIN_RATIO = 0.02

# --trees: what counts as a tree in a pack with no vendor categories. The other
# heavy polyhaven families are cliffs and coastal rocks, which nothing plants.
TREE_WORDS = ('tree', 'sapling', 'palm', 'shrub', 'searsia', 'bush')


# ── the Blender side ────────────────────────────────────────────────────────
def _blender_main(argv: list[str]) -> int:
    import bpy  # noqa: PLC0415 (Blender only)

    src, dst, ratio = argv[0], argv[1], float(argv[2])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if src.lower().endswith('.glb') or src.lower().endswith('.gltf'):
        bpy.ops.import_scene.gltf(filepath=src)
    else:
        raise SystemExit(f'arch_asset_lod: {src} is not a glTF/GLB')

    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise SystemExit(f'arch_asset_lod: nothing to decimate in {src}')
    before = sum(len(o.data.loop_triangles) or _tri_estimate(o) for o in meshes)
    for o in meshes:
        m = o.modifiers.new(name='lod1', type='DECIMATE')
        m.decimate_type = 'COLLAPSE'
        m.ratio = ratio
        m.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=m.name)
    after = 0
    for o in meshes:
        o.data.calc_loop_triangles()
        after += len(o.data.loop_triangles)

    bpy.ops.export_scene.gltf(
        filepath=dst,
        export_format='GLB',
        export_materials='EXPORT',
        export_texcoords=True,
        export_normals=True,
        use_selection=False,
    )
    _zyg_log.info(f'arch_asset_lod: {os.path.basename(src)} {before} -> {after} tris (ratio {ratio:.4f}) -> {dst}')
    return 0


def _tri_estimate(o) -> int:
    o.data.calc_loop_triangles()
    return len(o.data.loop_triangles)


# ── the driver side ─────────────────────────────────────────────────────────
def over_budget(pack_filter: str = '', trees_only: bool = False) -> list[dict]:
    """Catalogue items above the triangle budget, heaviest first."""
    from zyg_workflows import architecture_assets as AA  # noqa: PLC0415 (not needed in Blender)

    cat = AA.catalogue()
    have = set()
    out = []
    for g in cat.get('groups') or []:
        for it in g.get('items') or []:
            p = it.get('p') or {}
            have.add(str(it.get('id') or ''))
            n = p.get('tris')
            if not isinstance(n, int) or n <= AA.TRI_BUDGET:
                continue
            pack, item = str(p.get('pack') or ''), str(p.get('item') or '')
            if pack_filter and pack != pack_filter:
                continue
            if trees_only and not any(w in item.lower() for w in TREE_WORDS):
                continue
            out.append({'id': str(it.get('id')), 'pack': pack, 'item': item, 'tris': n, 'lod': AA.lod_stem(item)})
    out.sort(key=lambda r: -r['tris'])
    for r in out:
        r['has_lod'] = f'{r["pack"]}|{r["lod"]}' in have
    return out


def make_lod(pack: str, item: str, tris: int) -> dict:
    from zyg_workflows import architecture_assets as AA  # noqa: PLC0415

    src = AA.resolve(pack, item)
    if not src:
        return {'ok': False, 'id': f'{pack}|{item}', 'why': 'not in the catalogue'}
    dst = os.path.join(os.path.dirname(src), AA.lod_stem(item) + '.glb')
    ratio = max(MIN_RATIO, AA.TRI_BUDGET * TARGET_FRACTION / max(1, tris))
    cmd = [
        BLENDER,
        '-b',
        '--factory-startup',
        '--python',
        os.path.abspath(__file__),
        '--',
        '--blender',
        src,
        dst,
        f'{ratio:.6f}',
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = '\n'.join((r.stdout + r.stderr).strip().splitlines()[-4:])
    if r.returncode != 0 or not os.path.isfile(dst):
        return {'ok': False, 'id': f'{pack}|{item}', 'why': tail or f'blender exit {r.returncode}'}
    return {
        'ok': True,
        'id': f'{pack}|{item}',
        'lod': os.path.basename(dst),
        'ratio': round(ratio, 6),
        'bytes': os.path.getsize(dst),
        'blender': tail,
    }


if __name__ == '__main__':  # the CLI lives in arch_asset_lod_cli
    try:
        from zyg_workflows.arch_asset_lod_cli import main as _cli_main
    except ImportError:  # inside Blender's python, which has no zyg_workflows installed
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from zyg_workflows.arch_asset_lod_cli import main as _cli_main

    raise SystemExit(_cli_main())
