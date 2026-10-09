# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_human_base_library.py — index the human-base packs for the Asset Browser.

    blender -b --python build_human_base_library.py

WHY A SECOND BUILDER. build_asset_library.py drives off
architecture_assets.catalogue() and imports glTF only. The human bases arrived
in three other shapes — Meta's MHR ships FBX LODs, Anny is exported to OBJ from
the PyTorch model, SOMA-X ships plain OBJ, MPFB generates its mesh at call time
— so none of them are reachable through that path. Everything else here follows
the same conventions: same LIB_ROOT, same merging catalogue sidecar, licence as
a tag on every asset.

WHAT IS DELIBERATELY NOT IN HERE.

  * The CharMorph characters. Their char.blend files are the addon's own data;
    CharMorph builds the body from morph targets at import time, so a snapshot
    of the rest mesh would be a worse copy of what the addon already gives you.

  * The Blender Studio character rigs. They ship as production .blend files
    meant to be File > Link'ed, and marking an asset requires local data, so
    the directory is registered as an asset library path instead (see
    register_human_base_libraries.py) rather than copied into one.

  * soma_x/_quarantine_smpl. SOMA topology wrapped onto SMPL/SMPL-X, whose
    upstream licence is non-commercial whatever NVIDIA's Apache header says.
"""

import os
import uuid

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
PACKS_ROOT = os.path.join(CREWS, 'data', 'assets', 'mesh_packs')
HB_ROOT = os.path.join(PACKS_ROOT, 'human_bases')
LIB_ROOT = os.path.join(CREWS, 'data', 'assets', 'blender_library')
OUT_DIR = os.path.join(LIB_ROOT, 'human_bases')

# (catalog leaf, licence, asset name, loader, source path relative to HB_ROOT, opts)
#
# `opts` exists because the three vendors disagree about which way is up and
# how big a metre is, and the OBJ importer's DEFAULT is a Y-up conversion:
#   Anny's exporter writes Z-up, so it must be imported with the conversion OFF
#     (without this every Anny body lands on its back — caught in a thumbnail),
#   SOMA-X writes Y-up, so the default is right,
#   SOMA-X's MHR meshes are in CENTIMETRES (172.68 units tall), so 0.01.
# Nothing here is guessed: each value was measured off the raw vertex data.
#
# MHR's FBX is Y-up too and the FBX importer already handles that. Forcing it
# with use_manual_orientation was tried and REVERTED: the manual path also
# discards the file's unit scale, and a 1.73 m man came in 173 m tall.
OBJ_ZUP = {'up_axis': 'Z', 'forward_axis': 'Y'}
OBJ_YUP_CM = {'global_scale': 0.01}

SOURCES = (
    [('mhr', 'Apache-2.0', f'mhr_lod{i}', 'fbx', f'mhr/assets/lod{i}.fbx', {}) for i in range(7)]
    + [
        ('anny', 'CC0-1.0', n, 'obj', f'anny/obj/{n}.obj', OBJ_ZUP)
        for n in (
            'anny_neutral',
            'anny_gender0.0',
            'anny_gender1.0',
            'anny_child_age0.20',
            'anny_baby_age0.0',
            'anny_old_age1.0',
        )
    ]
    + [
        ('soma_x', 'Apache-2.0', 'soma_x_anny_base_body', 'obj', 'soma_x/Anny/base_body.obj', {}),
        ('soma_x', 'Apache-2.0', 'soma_x_anny_wrap', 'obj', 'soma_x/Anny/SOMA_wrap.obj', {}),
        ('soma_x', 'Apache-2.0', 'soma_x_mhr_base_body_lod1', 'obj', 'soma_x/MHR/base_body_lod1.obj', OBJ_YUP_CM),
        ('soma_x', 'Apache-2.0', 'soma_x_mhr_base_body_lod6', 'obj', 'soma_x/MHR/base_body_lod6.obj', OBJ_YUP_CM),
        ('soma_x', 'Apache-2.0', 'soma_x_mhr_wrap_lod1', 'obj', 'soma_x/MHR/SOMA_wrap_lod1.obj', OBJ_YUP_CM),
        ('soma_x', 'Apache-2.0', 'soma_x_garment_mean', 'obj', 'soma_x/GarmentMeasurements/mean.obj', {}),
    ]
)

# A body that imports lying down, or a hundred times too big, still counts as a
# successful import — so the import is not what gets checked. These are.
STANDING_MIN = 0.40  # a newborn is ~0.5 m; below this something is wrong
STANDING_MAX = 2.30


def import_one(kind, path, opts=None):
    before = set(bpy.data.objects)
    opts = dict(opts or {})
    if kind == 'fbx':
        bpy.ops.import_scene.fbx(filepath=path, **opts)
    elif kind == 'obj':
        bpy.ops.wm.obj_import(filepath=path, **opts)
    else:
        raise ValueError(kind)
    # matrix_world is evaluated lazily off the parent chain. Read it straight
    # after an import and it is still identity, which is how MHR's 0.01 scale
    # and Y-up fix — both of which live on the parent armature — got baked away
    # to nothing and every LOD ended up 172 units tall on its side.
    bpy.context.view_layer.update()
    return [o for o in bpy.data.objects if o not in before]


def bake_transform(obj, mw=None):
    """Freeze the importer's axis fix into the mesh, leaving identity on the object.

    Both importers express "this file is Y-up" as a ROTATION ON THE OBJECT, not
    as rotated vertex data. So obj.dimensions — which is local — reports the
    body lying down while the viewport shows it standing, and an asset dragged
    out of the browser carries a 90-degree rotation nobody asked for. Baking it
    makes the object honest and makes check_standing mean something."""
    mw = (mw or obj.matrix_world).copy()
    obj.data.transform(mw)
    obj.matrix_world.identity()
    obj.data.update()


def world_extents(obj):
    """Measure the geometry, not obj.dimensions.

    obj.dimensions reads a cached bounding box that a mesh-data transform does
    NOT invalidate in background mode: after baking MHR to metres the vertices
    were right and dimensions still reported the old 172-unit box, so the check
    below failed on correct meshes for three rebuilds. Vertices never lie."""
    mw = obj.matrix_world
    pts = [mw @ v.co for v in obj.data.vertices]
    if not pts:
        return None
    return tuple(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))


def check_standing(obj):
    """Return None when the body stands upright at human scale, else why not."""
    e = world_extents(obj)
    if e is None:
        return 'no vertices'
    x, y, z = e
    if not (z >= x and z >= y):
        return (
            f'not upright: extents x={x:.3f} y={y:.3f} z={z:.3f} '
            f'(tallest axis is {"XYZ"[max(range(3), key=lambda i: e[i])]})'
        )
    if not STANDING_MIN <= z <= STANDING_MAX:
        return f'height {z:.3f} m outside {STANDING_MIN}-{STANDING_MAX} m'
    return None


def consolidate(objs, name):
    """Keep the biggest mesh, drop everything else the importer brought in.

    MHR's FBX carries a 126-bone armature; an armature cannot be marked as an
    asset alongside its mesh without the mesh arriving posed-but-unrigged in
    every drag-and-drop, so the reference body is the mesh alone. The rig stays
    available by importing the FBX directly."""
    meshes = [o for o in objs if o.type == 'MESH']
    if not meshes:
        for o in objs:
            bpy.data.objects.remove(o, do_unlink=True)
        return None
    keep = max(meshes, key=lambda o: len(o.data.vertices))
    keep_name = keep.name
    # Snapshot the world matrix BEFORE the siblings go. MHR's FBX parents its
    # mesh to the armature and puts the centimetre-to-metre scale (0.01) and
    # the Y-up fix on THAT armature, so deleting it first silently threw both
    # away and every LOD came out 172 units tall and lying down.
    keep_mw = keep.matrix_world.copy()
    for o in list(objs):
        if o.name != keep_name:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except (ReferenceError, RuntimeError) as _exc:
                _zyg_log.debug('leftover object removal skipped: %s', _exc)
    obj = bpy.data.objects.get(keep_name)
    if obj is None:
        return None
    obj.parent = None
    obj.matrix_world.identity()
    # Bake here, with the matrix snapshotted while the parent still existed.
    # Re-reading obj.matrix_world after the reparent gave identity back and the
    # scale silently vanished, so the value is passed in rather than fetched.
    bake_transform(obj, keep_mw)
    # Strip ONLY the modifiers whose target we just deleted. Stripping the lot
    # was wrong: MPFB hides its helper cage (hair/clothes fitting geometry) with
    # a Mask modifier, and without it the asset — and its thumbnail — is a body
    # wearing a grey cone. The mask cannot be applied instead, because the base
    # mesh carries shape keys and Blender refuses.
    for m in list(obj.modifiers):
        if m.type == 'ARMATURE':
            obj.modifiers.remove(m)
    obj.name = name
    if obj.data:
        obj.data.name = name
    return obj


def write_catalogs(out_dir, cats):
    """Merging sidecar writer — same contract as build_asset_library.py's."""
    p = os.path.join(out_dir, 'blender_assets.cats.txt')
    merged = {}
    if os.path.isfile(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(('VERSION', '#')):
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    merged[parts[1]] = parts[0]
    merged.update(cats)
    lines = ['VERSION 1', '']
    for path, cid in sorted(merged.items()):
        lines.append(f'{cid}:{path}:{path.replace("/", "-")}')
    with open(p, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return p


def add_mpfb_default(cats):
    """One MPFB body so the CC0 base topology is browsable next to the others.

    MPFB is a Blender extension, so the import path is the extension module
    name, not `mpfb`; that rename is the single reason a headless MPFB script
    fails with ModuleNotFoundError."""
    try:
        import addon_utils

        addon_utils.enable('bl_ext.user_default.mpfb', default_set=False, persistent=True)
        from bl_ext.user_default.mpfb.services.humanservice import HumanService
    except Exception as e:  # noqa: BLE001
        return None, f'mpfb unavailable: {type(e).__name__}: {e}'
    before = set(bpy.data.objects)
    HumanService.create_human()
    objs = [o for o in bpy.data.objects if o not in before]
    obj = consolidate(objs, 'mpfb_default_human')
    if obj is None:
        return None, 'mpfb produced no mesh'
    mark(
        obj,
        'mpfb',
        'CC0-1.0',
        cats,
        'MPFB / MakeHuman base mesh at default macros (gender .5, age .5). '
        'Assets CC0; the addon generates any age from infant to elderly on the same topology.',
    )
    return obj, None


def mark(obj, leaf, licence, cats, description):
    cid = cats.setdefault(
        f'human_bases/{leaf}', str(uuid.uuid5(uuid.NAMESPACE_URL, f'zygomatic:asset-cat:human_bases/{leaf}'))
    )
    obj.asset_mark()
    ad = obj.asset_data
    ad.catalog_id = cid
    ad.description = description
    ad.tags.new('human_base')
    ad.tags.new(leaf)
    ad.tags.new(licence)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cats, made, skipped, problems = {}, 0, 0, []

    for leaf, licence, name, kind, rel, opts in SOURCES:
        src = os.path.join(HB_ROOT, rel)
        if not os.path.isfile(src):
            skipped += 1
            problems.append(f'missing: {rel}')
            continue
        try:
            obj = consolidate(import_one(kind, src, opts), name)
        except Exception as e:  # noqa: BLE001
            skipped += 1
            problems.append(f'{rel}: {type(e).__name__}: {e}')
            continue
        if obj is None:
            skipped += 1
            problems.append(f'{rel}: no mesh')
            continue
        bpy.context.view_layer.update()
        bad = check_standing(obj)
        if bad:
            problems.append(f'{rel}: {bad}')
        e = world_extents(obj) or (0, 0, 0)
        mark(
            obj,
            leaf,
            licence,
            cats,
            f'{name} — human_bases/{leaf} ({licence}) — {len(obj.data.vertices)} verts, {e[2]:.3f} m tall',
        )
        made += 1

    obj, err = add_mpfb_default(cats)
    if obj is not None:
        bake_transform(obj)
        bpy.context.view_layer.update()
        bad = check_standing(obj)
        if bad:
            problems.append(f'mpfb_default_human: {bad}')
        made += 1
    else:
        skipped += 1
        problems.append(err)

    os.makedirs(OUT_DIR, exist_ok=True)
    write_catalogs(LIB_ROOT, cats)
    out = os.path.join(OUT_DIR, 'human_bases.blend')
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print(
        '@@RESULT@@ '
        + repr(
            {
                'assets': made,
                'skipped': skipped,
                'blend': out,
                'bytes': os.path.getsize(out) if os.path.isfile(out) else 0,
                'catalogs': sorted(cats),
                'problems': problems,
            }
        )
    )


if __name__ == '__main__':
    main()
