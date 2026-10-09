# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Wall booleans and the build itself — drawing JSON to .blend (+ optional .glb).

Moved verbatim out of the old single-file arch_blender_build.py (lines 868-1112).
"""

import os

import bpy
import bmesh
from mathutils import Matrix
import logging as _zyg_logging

# Bound by assignment rather than `from … import` on purpose: CPython emits the
# LOAD_METHOD form for `X.method()` only when X was not bound by an import
# statement, and the moved lines below were compiled against a plain global.
from zyg_workflows.arch_blender_build import kinds as _kinds
from zyg_workflows.arch_blender_build import materials as _materials

KIND_DEFAULT_MAT = _materials.KIND_DEFAULT_MAT
VCOL_ATTR = _materials.VCOL_ATTR
_MATERIALS = _materials._MATERIALS
get_material = _materials.get_material
get_material_vc = _materials.get_material_vc
add_box = _kinds.add_box
build_kind = _kinds.build_kind
num = _kinds.num

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_blender_build')


# ── walls: cut the holes with a boolean, evaluated without operators ──────
def cut_holes(obj, holes, L, t, h, coll):
    cutters = []
    for i, hole in enumerate(holes or []):
        if not isinstance(hole, dict):
            continue
        u, w = num(hole, 'u', -1), num(hole, 'w', 0)
        hh, sill = num(hole, 'h', 0), max(0.0, num(hole, 'sill', 0))
        if w <= 0 or hh <= 0:
            continue
        a, b = max(-L / 2, -L / 2 + u - w / 2), min(L / 2, -L / 2 + u + w / 2)
        if b <= a:
            continue
        bm = bmesh.new()
        add_box(bm, a, b, -t / 2 - 0.05, t / 2 + 0.05, sill, min(h, sill + hh) + (0.05 if sill + hh >= h else 0.0))
        me = bpy.data.meshes.new(f'{obj.name} cutter {i}')
        bm.to_mesh(me)
        bm.free()
        cut = bpy.data.objects.new(me.name, me)
        # the boolean works in WORLD space: the cutter must ride the wall's transform
        cut.location = obj.location
        cut.rotation_mode = obj.rotation_mode
        cut.rotation_euler = obj.rotation_euler
        cut.scale = obj.scale
        coll.objects.link(cut)
        cutters.append(cut)
    if not cutters:
        return 0
    for cut in cutters:
        mod = obj.modifiers.new('hole', 'BOOLEAN')
        mod.operation = 'DIFFERENCE'
        mod.solver = 'EXACT'
        mod.object = cut
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    new_me = bpy.data.meshes.new_from_object(ev)
    new_me.name = obj.data.name + ' cut'
    old = obj.data
    obj.modifiers.clear()
    obj.data = new_me
    bpy.data.meshes.remove(old)
    new_me.name = obj.name
    for cut in cutters:
        me = cut.data
        bpy.data.objects.remove(cut)
        bpy.data.meshes.remove(me)
    return len(cutters)


# ── the build ──────────────────────────────────────────────────────────────
def import_asset(rec, p, coll):
    """Import the catalogued GLB for one 'asset' record under an empty placed in
    the studio frame. Returns True when the model was imported."""
    try:
        from zyg_workflows import architecture_assets as AA

        path = AA.resolve(str(p.get('pack') or ''), str(p.get('item') or ''))
    except Exception as e:  # noqa: BLE001
        _zyg_log.warning(f'[asset] catalogue unavailable: {e!r}')
        path = None
    if not path:
        return False
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=path, import_shading='NORMALS')
    except Exception as e:  # noqa: BLE001
        _zyg_log.warning(f'[asset] import failed {path}: {e!r}')
        return False
    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        return False
    rid = str(rec.get('id') or 'asset')
    root = bpy.data.objects.new(f'asset {rid}', None)
    coll.objects.link(root)
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        if o.parent is None:
            o.parent = root
    x, y, z = num(rec, 'x', 0), num(rec, 'y', 0), num(rec, 'z', 0)
    root.location = (x, -z, y)
    root.rotation_mode = 'XYZ'
    root.rotation_euler = (num(rec, 'rx', 0), -num(rec, 'rz', 0), num(rec, 'ry', 0))
    sc = num(rec, 's', 1) or 1.0
    root.scale = (sc, sc, sc)
    root['studio_id'] = rid
    root['studio_kind'] = 'asset'
    root['studio_pack'] = f'{p.get("pack")}|{p.get("item")}'
    return True


def adopt_builder_objects(obj, before, rid, kind):
    """Give the record's transform to whatever the BUILDER made itself.

    A kind builder is handed only `bm` and `p`, so an object it creates on its
    own — light_lamps_env._lamp's real POINT/SPOT/AREA lamp — is never touched
    by the record loop below and lands at the DRAWING ORIGIN: sixteen lobby
    downlights all firing from (0, 0, 0) while their fittings hang from the
    ceiling twenty metres away. Every object born during the builder call is
    parented to the record's mesh object with an identity parent-inverse, so the
    record's x/y/z, ry and scale carry it exactly where its marker is, and it
    keeps the LOCAL offset the builder gave it.

    The fitting itself then stops casting shadows (Cycles): a lamp sitting in
    its own 0.25 m disc or inside a spot's cone would otherwise light nothing at
    all — every shadow ray to it hits the shell it hangs in.

    `before` is the set of bpy.data.objects keys taken before the builder ran.
    Returns the number of objects adopted."""
    n = 0
    for name in sorted(set(bpy.data.objects.keys()) - before):
        child = bpy.data.objects.get(name)
        if child is None or child is obj or child.parent is not None:
            continue
        child.parent = obj
        child.matrix_parent_inverse = Matrix.Identity(4)
        child['studio_id'] = rid
        child['studio_kind'] = kind
        child['studio_note'] = 'parented to the record object: it carries the record transform'
        n += 1
    if n:
        try:
            obj.visible_shadow = False
        except AttributeError as _exc:
            _zyg_log.debug('visible_shadow not settable: %s', _exc)
    return n


# plan annotations never reach the render: a layout_floor zone is a 0.05 m prism
# sitting INSIDE the storey slab whose bottom face z-fought the ceiling in Cycles
# as a black band across every lobby frame (jobs 5e7eb915e1f9, ead3aacacf55).
RENDER_SKIP_KINDS = frozenset({'opening', 'zone', 'gridline'})  # measure_annotations' pins DO render


def build(drawing, blend_path, glb_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'METERS'
    name = str(drawing.get('name') or 'drawing')
    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)

    objects = drawing.get('objects') or []
    if not isinstance(objects, list):
        raise ValueError('"objects" is not a list')
    built = skipped = holes_cut = adopted = 0
    for i, rec in enumerate(objects):
        if not isinstance(rec, dict):
            skipped += 1
            continue
        kind = str(rec.get('kind') or 'box')
        if rec.get('hidden') or kind in RENDER_SKIP_KINDS:
            skipped += 1
            continue
        rid = str(rec.get('id') or f'o{i}')
        p = rec.get('p') if isinstance(rec.get('p'), dict) else {}

        if kind == 'asset':
            # 2026-09-07: a pack asset renders as its real GLB when this machine
            # has the pack; only an unresolved one falls through to the crate.
            if import_asset(rec, p, coll):
                built += 1
                continue
        bm = bmesh.new()
        before_objs = set(bpy.data.objects.keys())  # anything the builder makes itself
        built_r = build_kind(bm, kind, p, objects)
        prefix, extra = built_r[0], built_r[1]
        vcolors = built_r[2] if len(built_r) > 2 else None
        # remove_doubles MERGES vertices, which would break the one-colour-per-
        # vertex correspondence the builder just handed us; a vertex-coloured
        # builder owns its own topology (a heightfield lattice has no doubles).
        if not vcolors:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        oname = f'{prefix}{kind} {rid}'
        me = bpy.data.meshes.new(oname)
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(oname, me)
        coll.objects.link(obj)

        # materials: slot 0 = the record's, further slots per kind (tree canopy)
        mat_id = rec.get('mat')
        if not isinstance(mat_id, str) or not mat_id:
            mat_id = 'mat_timber' if kind == 'tree' else KIND_DEFAULT_MAT.get(kind, 'mat_concrete')
        if vcolors:
            ca = me.color_attributes.new(VCOL_ATTR, 'FLOAT_COLOR', 'POINT')
            for vi, c in enumerate(vcolors[: len(me.vertices)]):
                ca.data[vi].color = (float(c[0]), float(c[1]), float(c[2]), float(c[3]) if len(c) > 3 else 1.0)
            me.materials.append(get_material_vc(mat_id))
        else:
            me.materials.append(get_material(mat_id, kind))
        for mid in extra:
            me.materials.append(get_material(mid, kind))

        # frame: blender (x, y, z) = (studio x, -studio z, studio y)
        x, y, z = num(rec, 'x', 0), num(rec, 'y', 0), num(rec, 'z', 0)
        obj.location = (x, -z, y)
        rx, ry, rz = num(rec, 'rx', 0), num(rec, 'ry', 0), num(rec, 'rz', 0)
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = (rx, -rz, ry)
        s = num(rec, 's', 1) or 1.0
        obj.scale = (s, s, s)
        obj['studio_id'] = rid
        obj['studio_kind'] = kind
        if isinstance(rec.get('name'), str):
            obj['studio_name'] = rec['name']
        adopted += adopt_builder_objects(obj, before_objs, rid, kind)

        if kind in ('wall', 'partition') and p.get('holes'):
            holes_cut += cut_holes(
                obj,
                p.get('holes'),
                num(p, 'len', 4),
                num(p, 't', 0.10 if kind == 'partition' else 0.24),
                num(p, 'h', 2.7),
                coll,
            )
        built += 1

    bpy.context.view_layer.update()
    os.makedirs(os.path.dirname(os.path.abspath(blend_path)) or '.', exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(blend_path))
    out_glb = None
    if glb_path:
        os.makedirs(os.path.dirname(os.path.abspath(glb_path)) or '.', exist_ok=True)
        bpy.ops.export_scene.gltf(
            filepath=os.path.abspath(glb_path), export_format='GLB', export_apply=True, export_yup=True
        )
        out_glb = os.path.abspath(glb_path)
    return {
        'ok': True,
        'objects': built,
        'skipped': skipped,
        'holes': holes_cut,
        'adopted': adopted,
        'materials': len(_MATERIALS),
        'blend': os.path.abspath(blend_path),
        'glb': out_glb,
    }
