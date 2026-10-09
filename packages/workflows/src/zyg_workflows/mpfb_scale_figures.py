# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mpfb_scale_figures.py — generate a pack of CC0 human scale figures with MPFB.

    blender -b --python mpfb_scale_figures.py -- --out <pack_dir> [--count 20]

Why: no CC0 source of scanned people with usable quality exists; MPFB's base
mesh is CC0 and its LICENSE.md disclaims any claim over exports, so figures
generated here can ship in a pack. Each figure is a different combination of
gender, age, height, weight and build at true height (MPFB's default adult is
1.659 m; `height` 0..1 spans roughly 1.45 .. 1.95 m). Untextured, one matte
skin material, A-pose: a scale figure, not a portrait.

MPFB is an EXTENSION in Blender 4.3: import bl_ext.user_default.mpfb.*, never
`mpfb` (project memory). Sizes are re-measured from the exported GLB by
mesh_pack_dims.py afterwards; the cached `dimensions` box in background
Blender is not trusted.
"""

import bpy
import json
import os
import sys
import time

argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
OUT = argv[argv.index('--out') + 1] if '--out' in argv else None
COUNT = int(argv[argv.index('--count') + 1]) if '--count' in argv else 20

if not OUT:
    raise SystemExit('need --out')

from bl_ext.user_default.mpfb.services.humanservice import HumanService  # noqa: E402
from bl_ext.user_default.mpfb.services.targetservice import TargetService  # noqa: E402

# name, gender (0 f .. 1 m), age (0.5 = 25 y; 0.19 ≈ 11 y; 1 = 90 y), height, weight, muscle
FIGURES = [
    ('woman_average', 0.0, 0.5, 0.5, 0.5, 0.5),
    ('man_average', 1.0, 0.5, 0.5, 0.5, 0.5),
    ('woman_tall_slim', 0.0, 0.45, 0.8, 0.35, 0.5),
    ('man_tall', 1.0, 0.45, 0.85, 0.5, 0.6),
    ('woman_short', 0.0, 0.5, 0.2, 0.5, 0.5),
    ('man_short_stocky', 1.0, 0.55, 0.25, 0.75, 0.6),
    ('woman_heavy', 0.0, 0.55, 0.5, 0.85, 0.4),
    ('man_heavy', 1.0, 0.55, 0.55, 0.9, 0.4),
    ('woman_athletic', 0.0, 0.4, 0.6, 0.45, 0.85),
    ('man_athletic', 1.0, 0.4, 0.65, 0.5, 0.9),
    ('woman_elderly', 0.0, 0.85, 0.4, 0.5, 0.3),
    ('man_elderly', 1.0, 0.85, 0.45, 0.55, 0.3),
    ('teen_girl', 0.0, 0.3, 0.45, 0.4, 0.5),
    ('teen_boy', 1.0, 0.3, 0.55, 0.4, 0.55),
    ('child_girl_8', 0.0, 0.16, 0.5, 0.5, 0.5),
    ('child_boy_10', 1.0, 0.19, 0.5, 0.5, 0.5),
    ('toddler', 0.5, 0.06, 0.5, 0.6, 0.4),
    ('woman_young', 0.0, 0.35, 0.55, 0.45, 0.55),
    ('man_young', 1.0, 0.35, 0.6, 0.5, 0.6),
    ('person_neutral', 0.5, 0.5, 0.5, 0.5, 0.5),
][:COUNT]


def skin_material():
    m = bpy.data.materials.get('scale_figure_skin')
    if m:
        return m
    m = bpy.data.materials.new('scale_figure_skin')
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.62, 0.55, 0.50, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.7
    return m


def world_height(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    zs = [(mw @ v.co).z for v in me.vertices]
    xs = [(mw @ v.co).x for v in me.vertices]
    ys = [(mw @ v.co).y for v in me.vertices]
    ev.to_mesh_clear()
    return (round(max(xs) - min(xs), 4), round(max(zs) - min(zs), 4), round(max(ys) - min(ys), 4))


def main():
    os.makedirs(OUT, exist_ok=True)
    dims = {}
    made = []
    for name, gender, age, height, weight, muscle in FIGURES:
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        macro = TargetService.get_default_macro_info_dict()
        macro.update({'gender': gender, 'age': age, 'height': height, 'weight': weight, 'muscle': muscle})
        t0 = time.time()
        try:
            body = HumanService.create_human(
                mask_helpers=True,
                detailed_helpers=False,
                extra_vertex_groups=False,
                feet_on_ground=True,
                scale=0.1,
                macro_detail_dict=macro,
            )
        except Exception as e:  # noqa: BLE001
            print(f'   FAIL {name}: {e!r}')
            continue
        body.name = name
        body.data.materials.clear()
        body.data.materials.append(skin_material())
        bpy.context.view_layer.update()
        ext = world_height(body)
        out = os.path.join(OUT, name + '.glb')
        bpy.ops.object.select_all(action='DESELECT')
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.export_scene.gltf(
            filepath=out,
            export_format='GLB',
            use_selection=True,
            export_apply=True,
            export_materials='EXPORT',
            export_yup=True,
            export_animations=False,
            export_skins=False,
            export_morph=False,
            export_lights=False,
            export_cameras=False,
        )
        dims[name + '.glb'] = list(ext)
        made.append((name, ext))
        print(f'   ok {name}: {ext[1]:.3f} m tall ({time.time() - t0:.1f}s)')
    with open(os.path.join(OUT, 'DIMENSIONS.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'unit': 'm',
                'axes': 'x width, y height, z depth (glTF Y-up)',
                'measured': time.strftime('%Y-%m-%d'),
                'method': 'world-space vertex extents in Blender before export',
                'dims': dims,
            },
            fh,
            indent=0,
        )
    with open(os.path.join(OUT, 'NOTES.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'notes': {
                    n: f'person human figure people scale entourage {n.replace("_", " ")} {ext[1]:.2f} m tall'
                    for n, ext in made
                }
            },
            fh,
            indent=0,
        )
    print(f'made {len(made)} of {len(FIGURES)}')


main()
