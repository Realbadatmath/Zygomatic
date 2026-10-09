# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Loading the 135 CC0 skeleton pieces out of the bundle .blend."""

import bpy

from .constants import PIECE_PREFIX, SKELETON_BLEND, SUBSURF_LEVELS

# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _link(obj):
    coll = bpy.context.scene.collection
    if obj.name not in coll.objects:
        coll.objects.link(obj)


def load_skeleton_pieces():
    """Append the 135 pieces, freeze their hierarchy, bake their modifiers."""
    with bpy.data.libraries.load(SKELETON_BLEND, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith(PIECE_PREFIX)]

    pieces = {}
    for obj in bpy.data.objects:
        if obj.name.startswith(PIECE_PREFIX) and obj.type == 'MESH':
            _link(obj)
            pieces[obj.name[len(PIECE_PREFIX) :]] = obj
    bpy.context.view_layer.update()

    # freeze the parent hierarchy -- every piece keeps its world placement but
    # can now be moved on its own.
    for obj in pieces.values():
        mw = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mw
    bpy.context.view_layer.update()

    # bake MIRROR (midline bones are modelled as halves) + SUBSURF.
    for obj in pieces.values():
        for mod in obj.modifiers:
            if mod.type == 'SUBSURF':
                mod.levels = SUBSURF_LEVELS
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    for obj in pieces.values():
        baked = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        old = obj.data
        obj.data = baked
        obj.modifiers.clear()
        if old.users == 0:
            bpy.data.meshes.remove(old)
        obj.data.materials.clear()
    bpy.context.view_layer.update()
    return pieces


def _origins(pieces):
    return {k: v.matrix_world.translation.copy() for k, v in pieces.items()}


def _mesh_height(obj):
    zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
    return max(zs) - min(zs)
