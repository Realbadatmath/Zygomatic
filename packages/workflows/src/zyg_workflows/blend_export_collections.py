# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blend_export_collections.py — export named collections of a .blend as
individual GLBs for the mesh-pack catalogue, with measured sizes.

    blender -b <file.blend> --python blend_export_collections.py -- \
        --out <pack_dir> --match "<regex on collection names>" [--exclude "<regex>"] \
        [--min-meshes 1] [--max-polys 3000000] [--name-prefix ""] [--list]

For every matching collection: a scratch scene is built with that collection
linked, collection instances are made real (Sprite Fright's trees are
instanced empties), and the selection is exported to <pack_dir>/<slug>.glb
with modifiers applied and textures embedded. The size written to
DIMENSIONS.json is measured from the vertices in world space (the cached
`dimensions` box lies in background Blender — see project memory), in the
glTF axis order: x width, y height (Blender Z), z depth (Blender Y).
"""

import bpy
import json
import os
import re
import sys
import time
from mathutils import Vector
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


def arg(name, default=None):
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else default
    return default


OUT = arg('--out')
MATCH = re.compile(arg('--match', '.*'))
EXCLUDE = re.compile(arg('--exclude', '^$'))
MIN_MESHES = int(arg('--min-meshes', '1'))
MAX_POLYS = int(arg('--max-polys', '3000000'))
PREFIX = arg('--name-prefix', '')
LIST_ONLY = '--list' in argv
FLAT_MATS = '--flat-materials' in argv


def _tree_ok(tree, depth=0):
    """False when a node group in the tree has no Group Output — the glTF
    exporter indexes [0] on that list and dies (Sprite Fright's shading)."""
    if tree is None or depth > 8:
        return True
    for n in tree.nodes:
        if n.type == 'GROUP':
            if n.node_tree is None or not any(x.type == 'GROUP_OUTPUT' for x in n.node_tree.nodes):
                return False
            if not _tree_ok(n.node_tree, depth + 1):
                return False
    return True


def sanitise_materials(objs, force_flat=False):
    """Replace materials the exporter cannot walk (or all of them with
    --flat-materials) by a Principled BSDF in the material's viewport colour."""
    swapped = 0
    for o in objs:
        if o.type != 'MESH' or not o.data:
            continue
        for i, m in enumerate(o.data.materials):
            if m is None:
                continue
            bad = force_flat or (m.use_nodes and not _tree_ok(m.node_tree))
            if not bad:
                continue
            name = m.name + '__flat'
            f = bpy.data.materials.get(name)
            if f is None:
                f = bpy.data.materials.new(name)
                f.use_nodes = True
                bsdf = f.node_tree.nodes.get('Principled BSDF')
                col = tuple(m.diffuse_color)
                if bsdf:
                    bsdf.inputs['Base Color'].default_value = (col[0], col[1], col[2], 1.0)
                    bsdf.inputs['Roughness'].default_value = max(0.35, float(m.roughness))
                f.diffuse_color = col
            o.data.materials[i] = f
            swapped += 1
    return swapped


def slug(s):
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    return s[:60] or 'item'


def mesh_count(coll):
    return sum(1 for o in coll.all_objects if o.type == 'MESH')


def poly_count(coll):
    return sum(len(o.data.polygons) for o in coll.all_objects if o.type == 'MESH' and o.data)


def world_extents(objs):
    lo = Vector((1e30, 1e30, 1e30))
    hi = Vector((-1e30, -1e30, -1e30))
    n = 0
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != 'MESH':
            continue
        try:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object bounds skipped, not evaluable: %s', _exc)
            continue
        mw = ev.matrix_world
        for v in me.vertices:
            p = mw @ v.co
            n += 1
            for i in range(3):
                if p[i] < lo[i]:
                    lo[i] = p[i]
                if p[i] > hi[i]:
                    hi[i] = p[i]
        ev.to_mesh_clear()
    if not n:
        return None
    ext = hi - lo
    return [round(ext.x, 4), round(ext.z, 4), round(ext.y, 4)], [round(lo.x, 4), round(lo.z, 4), round(lo.y, 4)]


def export_collection(coll, out_path):
    src_scene = bpy.context.scene
    sc = bpy.data.scenes.new('__export__')
    bpy.context.window.scene = sc
    sc.collection.children.link(coll)
    bpy.context.view_layer.update()
    # make instanced collections real so the exporter sees geometry
    bpy.ops.object.select_all(action='DESELECT')
    empties = [o for o in coll.all_objects if o.type == 'EMPTY' and o.instance_collection]
    for o in empties:
        o.hide_viewport = False
        o.hide_set(False)
        o.select_set(True)
    if empties:
        bpy.context.view_layer.objects.active = empties[0]
        try:
            bpy.ops.object.duplicates_make_real(use_base_parent=False, use_hierarchy=True)
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(' '.join(str(a) for a in ('   duplicates_make_real failed:', e)))
    bpy.ops.object.select_all(action='DESELECT')
    objs = [o for o in sc.collection.all_objects if o.type in ('MESH', 'CURVE', 'FONT', 'SURFACE')]
    for o in objs:
        o.hide_viewport = False
        o.hide_render = False
        try:
            o.hide_set(False)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('unhiding the object failed: %s', _exc)
        o.select_set(True)
    if not objs:
        bpy.context.window.scene = src_scene
        bpy.data.scenes.remove(sc)
        return None
    bpy.context.view_layer.objects.active = objs[0]
    sw = sanitise_materials(objs, FLAT_MATS)
    if sw:
        _zyg_log.info(f'   ({sw} material slot(s) flattened to viewport colour)')
    ext = world_extents(objs)
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format='GLB',
        use_selection=True,
        export_apply=True,
        export_image_format='AUTO',
        export_texcoords=True,
        export_normals=True,
        export_materials='EXPORT',
        export_yup=True,
        export_animations=False,
        export_skins=False,
        export_morph=False,
        export_lights=False,
        export_cameras=False,
    )
    bpy.context.window.scene = src_scene
    bpy.data.scenes.remove(sc)
    return ext


def main():
    if not OUT and not LIST_ONLY:
        print('need --out')
        return
    cands = []
    for c in bpy.data.collections:
        if not MATCH.search(c.name) or EXCLUDE.search(c.name):
            continue
        m = mesh_count(c)
        if m < MIN_MESHES:
            continue
        cands.append((c, m, poly_count(c)))
    print(f'{len(cands)} collections match')
    for c, m, p in cands:
        print(f'   {c.name}: {m} meshes, {p} polys')
    if LIST_ONLY:
        return
    os.makedirs(OUT, exist_ok=True)
    dims = {}
    dpath = os.path.join(OUT, 'DIMENSIONS.json')
    if os.path.exists(dpath):
        try:
            dims = json.load(open(dpath)).get('dims') or {}
        except Exception:  # noqa: BLE001
            dims = {}
    done = 0
    for c, _m, p in cands:
        if p > MAX_POLYS:
            print(f'   skip {c.name}: {p} polys > {MAX_POLYS}')
            continue
        name = slug(PREFIX + c.name) + '.glb'
        out = os.path.join(OUT, name)
        t0 = time.time()
        try:
            ext = export_collection(c, out)
        except Exception as e:  # noqa: BLE001
            print(f'   FAIL {c.name}: {e}')
            continue
        if ext and os.path.exists(out):
            dims[name] = ext[0]
            done += 1
            print(f'   ok {name} {ext[0]} m  ({os.path.getsize(out) // 1024} KB, {time.time() - t0:.1f}s)')
        else:
            print(f'   empty {c.name}')
    with open(dpath, 'w', encoding='utf-8') as fh:
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
    print(f'exported {done} of {len(cands)} into {OUT}')


main()
