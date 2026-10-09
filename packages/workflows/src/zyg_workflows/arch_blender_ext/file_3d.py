# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_3d — the Blender half of the File ▸ 3D family (2026-09-07).

A record of kind `mesh_file` or `point_cloud` is a POINTER: the drawing carries
an id, and the bytes sit on the server under data/architecture/imports/. So
these builders are the only ones in the extension set that read a file off the
disk. They do it the way Blender wants to — `bpy.ops.import_scene.gltf` and its
siblings put objects in the SCENE, not in a bmesh — and then copy the result
into the bm the record loop handed us and delete what they made.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z, Z up. A
glTF import already converts Y-up to Z-up, which is exactly that mapping, so an
imported mesh lands the same way round it does in the tab. Nothing is bottom
aligned: the tab drops the parsed scene straight on the record's origin, and a
twin that "helpfully" sat it on the ground would not be a twin.

  mesh_file    real geometry, prefix ''   — a crate and prefix '?' if the
                                            import fails or the file is gone
  point_cloud  .ply only, prefix '~'      — the vertices as a loose point mesh;
                                            an .xyz/.pts cloud is a '~' pad
  link         prefix '~'                 — a bbox crate and nothing more: the
                                            linked drawing's own records are
                                            the tab's business, not a mesh's

Standard library plus bpy/bmesh (already in Blender). No new packages.
"""

import os
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_DIR = os.path.join(HERE, 'data', 'architecture', 'imports')

MESH_EXT = ('glb', 'gltf', 'obj', 'stl', 'ply')
CLOUD_EXT = ('ply', 'xyz', 'pts')


def _find(fid, allowed):
    """The file for an id, or None. The id is fenced to the characters the
    server's own _ID_RE allows, so a record cannot walk out of the directory."""
    fid = str(fid or '').strip().lower()
    if not fid or not all(c.isalnum() or c in '_-' for c in fid) or len(fid) > 64:
        return None
    for ext in allowed:
        p = os.path.join(IMPORT_DIR, '%s.%s' % (fid, ext))
        if os.path.isfile(p):
            return p
    return None


def _crate(bm, kit, w, h, d, z0=0.0):
    kit['add_box_c'](bm, w, d, h, z0=z0)


# ── mesh_file ──────────────────────────────────────────────────────────────


def _import_objects(path, ext):
    """Run the right importer and return the objects it added to the scene."""
    import bpy

    before = set(bpy.data.objects)
    if ext in ('glb', 'gltf'):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == 'obj':
        if hasattr(bpy.ops.wm, 'obj_import'):
            bpy.ops.wm.obj_import(filepath=path)
        else:  # Blender < 3.3
            bpy.ops.import_scene.obj(filepath=path)
    elif ext == 'stl':
        if hasattr(bpy.ops.wm, 'stl_import'):
            bpy.ops.wm.stl_import(filepath=path)
        else:
            bpy.ops.import_mesh.stl(filepath=path)
    elif ext == 'ply':
        if hasattr(bpy.ops.wm, 'ply_import'):
            bpy.ops.wm.ply_import(filepath=path)
        else:
            bpy.ops.import_mesh.ply(filepath=path)
    else:
        raise ValueError('no importer for .%s' % ext)
    return [o for o in bpy.data.objects if o not in before]


def _drop(objs):
    """Remove what the importer made, meshes and all — a builder that leaks its
    scratch objects would put the model in the render twice."""
    import bpy

    meshes = [o.data for o in objs if getattr(o, 'type', '') == 'MESH' and o.data is not None]
    for o in objs:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('scratch object removal failed — it may leak into the render: %s', _exc)
    for m in meshes:
        try:
            if m.users == 0:
                bpy.data.meshes.remove(m)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('unused mesh removal skipped: %s', _exc)


def _bake(bm, objs, scale):
    """Copy every imported mesh into bm with its own world transform baked in.
    Returns the number of verts added."""
    import bpy

    n0 = len(bm.verts)
    for o in objs:
        if getattr(o, 'type', '') != 'MESH' or o.data is None or not len(o.data.vertices):
            continue
        me = o.data.copy()
        me.transform(o.matrix_world)
        if scale != 1.0:
            for v in me.vertices:
                v.co *= scale
        bm.from_mesh(me)
        try:
            bpy.data.meshes.remove(me)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('baked mesh copy removal skipped: %s', _exc)
    return len(bm.verts) - n0


def build_mesh_file(bm, p, kit):
    ext = str(p.get('ext') or '').strip().lower().lstrip('.')
    if ext not in MESH_EXT:
        ext = os.path.splitext(str(p.get('name') or ''))[1].lower().lstrip('.')
    path = _find(p.get('id'), (ext,) if ext in MESH_EXT else MESH_EXT)
    s = max(0.001, kit['num'](p, 'sx', 1.0))
    if path is None:
        _crate(bm, kit, 1.0 * s, 1.0 * s, 1.0 * s)  # the file is not on this machine
        return ('?', [])
    ext = os.path.splitext(path)[1].lstrip('.').lower()
    objs = []
    try:
        objs = _import_objects(path, ext)
        added = _bake(bm, objs, s)
    except Exception as e:  # noqa: BLE001
        _zyg_log.info('[file_3d] %s will not import: %r' % (os.path.basename(path), e))
        added = 0
    finally:
        _drop(objs)
    if not added:
        _crate(bm, kit, 1.0 * s, 1.0 * s, 1.0 * s)
        return ('?', [])
    bm.normal_update()
    return ('', [])


# ── point_cloud ────────────────────────────────────────────────────────────


def build_point_cloud(bm, p, kit):
    """A .ply comes in as real vertices — Blender's ply importer reads them and
    a loose-vertex mesh IS a point cloud as far as a bmesh is concerned. An
    .xyz/.pts is text this builder is not going to reimplement a parser for, so
    it is a flat pad the size of the survey, marked '~'."""
    ext = str(p.get('ext') or '').strip().lower().lstrip('.')
    path = _find(p.get('id'), ('ply',)) if ext in ('', 'ply') else None
    if path is not None:
        objs = []
        try:
            objs = _import_objects(path, 'ply')
            added = _bake(bm, objs, 1.0)
        except Exception as e:  # noqa: BLE001
            _zyg_log.info('[file_3d] point cloud %r: %r' % (p.get('id'), e))
            added = 0
        finally:
            _drop(objs)
        if added:
            return ('~', [])
    _crate(bm, kit, 4.0, 0.02, 4.0)
    return ('~', [])


# ── link ───────────────────────────────────────────────────────────────────


def build_link(bm, p, kit):
    """A reference to another drawing. The tab builds the linked records for
    real; a render twin would have to load a second project and recurse, so it
    stands in as a bounding crate and says so with '~'."""
    _crate(bm, kit, kit['num'](p, 'w', 6.0), kit['num'](p, 'h', 3.0), kit['num'](p, 'd', 6.0))
    return ('~', [])


BUILDERS = {'mesh_file': build_mesh_file, 'point_cloud': build_point_cloud, 'link': build_link}
