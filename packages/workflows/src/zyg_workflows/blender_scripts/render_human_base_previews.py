# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_human_base_previews.py — thumbnails for the human-base asset library.

    blender -b --factory-startup --python render_human_base_previews.py

render_asset_previews.py imports glTF and nothing else, and not one human base
arrived as glTF (MHR is FBX, Anny and SOMA-X are OBJ, MPFB is generated). So
this renders straight out of the built library instead of out of a pack: open
blender_library/human_bases/human_bases.blend, render each marked asset on its
own, load the PNG back as that asset's custom preview, save.

It reuses render_asset_previews' world and framing verbatim — same sun, same
orthographic 3/4 vector, same bounding-box solve — so a human base and a road
tile are lit and framed identically in the browser.

It does NOT correct orientation. It used to, and that was the wrong place for
it: MHR is Y-up, Anny is Z-up, SOMA-X's MHR meshes are in centimetres, and
straightening those only for the thumbnail would leave the asset itself lying
down when dragged into a scene. build_human_base_library.py now bakes each
import to upright metres and refuses to finish quietly if one is not, so by the
time a body reaches this script it is already standing.

PNGs go to data/assets/mesh_packs/_generated_previews/human_bases/, the same
outside-the-pack location and for the same reason.
"""

import importlib.util
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
LIB = os.path.join(CREWS, 'data', 'assets', 'blender_library', 'human_bases', 'human_bases.blend')
OUT = os.path.join(CREWS, 'data', 'assets', 'mesh_packs', '_generated_previews', 'human_bases')


def load_sibling(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    rap = load_sibling('render_asset_previews')
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=LIB)

    assets = [o for o in bpy.data.objects if o.asset_data and o.type == 'MESH']
    scene = bpy.context.scene
    cam = rap.setup_world()
    made, failed = 0, []

    for obj in assets:
        try:
            for other in assets:
                other.hide_render = other is not obj
            rap.frame(cam, [obj])
            png = os.path.join(OUT, obj.name + '.png')
            scene.render.filepath = png
            scene.render.resolution_x = rap.RES
            scene.render.resolution_y = rap.RES
            scene.render.film_transparent = True
            bpy.ops.render.render(write_still=True)
            if os.path.isfile(png):
                with bpy.context.temp_override(id=obj):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=png)
                made += 1
            else:
                failed.append(obj.name + ': no png')
        except Exception as e:  # noqa: BLE001
            failed.append(f'{obj.name}: {type(e).__name__}: {e}')

    for other in assets:
        other.hide_render = False
    bpy.ops.wm.save_mainfile(compress=True)
    print('@@RESULT@@ ' + repr({'assets': len(assets), 'previews': made, 'failed': failed, 'out': OUT}))


if __name__ == '__main__':
    main()
