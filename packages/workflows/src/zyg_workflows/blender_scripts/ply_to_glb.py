# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ply_to_glb.py — one Smithsonian PLY scan into one catalogue-ready GLB.

    blender -b --factory-startup --python ply_to_glb.py -- \
        --in scan.ply --out scan.glb --target-tris 100000 --units mm

WHY THIS EXISTS. 718 of the Smithsonian's 3D records — every one of them a
mammal specimen, mostly primate crania, mandibles and limb bones — publish a
FULL-RESOLUTION ASCII PLY and nothing else. No GLB, no usdz. At ~150 MB and
750k faces each they are not something either consumer can open: the studio
loads glTF over HTTP and Blender's Asset Browser would be carrying 500M
triangles. So each one is decimated once, on the way in, and the master is
discarded — the ingest keeps the derived GLB, not 79 GB of ASCII.

THREE THINGS THAT ARE EASY TO GET WRONG.

  * SCALE. These are published in MILLIMETRES with no unit declared in the
    file. Imported as-is a gibbon cranium is 100 units across, which the
    catalogue reads as 100 METRES and reports as a building. The mesh is
    scaled by --units on import and the scale is APPLIED, so the GLB carries
    true metres like every other pack.

  * The decimate ratio is computed from the mesh's OWN face count, not
    assumed. A ratio picked for a 750k mesh applied to a 40k one destroys it,
    and these scans range over an order of magnitude.

  * Custom split normals do not survive decimation. They are cleared before
    the modifier rather than left to be silently dropped, and the result is
    shade-smooth with an angle — which is what a scan should look like anyway.
"""

import argparse
import os
import sys

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def argv_after_dashes():
    return sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


UNIT_SCALE = {'m': 1.0, 'cm': 0.01, 'mm': 0.001}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    ap.add_argument('--target-tris', type=int, default=100000)
    ap.add_argument('--units', default='mm', choices=sorted(UNIT_SCALE))
    ap.add_argument('--probe', action='store_true', help='report the mesh and its size, write nothing')
    a = ap.parse_args(argv_after_dashes())

    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = set(bpy.data.objects)
    bpy.ops.wm.ply_import(filepath=a.src)
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not new:
        print('@@RESULT@@ ' + repr({'error': 'no mesh imported', 'src': a.src}))
        return
    obj = new[0]
    if len(new) > 1:  # a PLY is one mesh, but be explicit
        bpy.ops.object.select_all(action='DESELECT')
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()

    faces_in = len(obj.data.polygons)
    raw_dim = tuple(round(d, 4) for d in obj.dimensions)

    if a.probe:
        print(
            '@@RESULT@@ '
            + repr(
                {
                    'faces': faces_in,
                    'verts': len(obj.data.vertices),
                    'raw_dim': raw_dim,
                    'has_color': bool(obj.data.color_attributes),
                    'materials': len(obj.data.materials),
                }
            )
        )
        return

    # Scale FIRST, then decimate: the modifier is topological and does not care,
    # but applying a transform after a modifier is one more thing to get wrong.
    s = UNIT_SCALE[a.units]
    obj.scale = (s, s, s)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    decimated = False
    if faces_in > a.target_tris:
        # Custom split normals are not carried through Decimate; drop them
        # deliberately rather than let them be discarded quietly.
        try:
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('custom split normals clear skipped: %s', _exc)
        m = obj.modifiers.new('decimate', 'DECIMATE')
        m.ratio = max(0.001, a.target_tris / float(faces_in))
        bpy.ops.object.modifier_apply(modifier=m.name)
        decimated = True
    bpy.ops.object.shade_smooth()

    os.makedirs(os.path.dirname(a.dst), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=a.dst, export_format='GLB', use_selection=True, export_apply=True, export_yup=True
    )
    print(
        '@@RESULT@@ '
        + repr(
            {
                'src': os.path.basename(a.src),
                'out': a.dst,
                'faces_in': faces_in,
                'faces_out': len(obj.data.polygons),
                'decimated': decimated,
                'units': a.units,
                'size_m': tuple(round(d, 4) for d in obj.dimensions),
                'bytes': os.path.getsize(a.dst) if os.path.isfile(a.dst) else 0,
            }
        )
    )


if __name__ == '__main__':
    main()
