# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os

import bpy
from mathutils import Vector

from zyg_workflows.blender_scripts.proxy_actor.constants import DEFAULT_OUT, MOTION_ROOT

# ----------------------------------------------------------------- arguments


def parse_args(argv):
    import argparse

    p = argparse.ArgumentParser(prog='proxy_actor.py')
    p.add_argument('--name')
    p.add_argument(
        '--body',
        choices=('mpfb', 'base'),
        default='mpfb',
        help="'mpfb' generates the mesh from the macros below; 'base' appends "
        'the rigged CC0 base body of data/assets/base_body_rig',
    )
    p.add_argument(
        '--fit',
        default=None,
        metavar='FIT_JSON',
        help='zyg.body_metrics/1 record; bone groups are scaled to its '
        'fractions of standing height before the height scale',
    )
    p.add_argument('--height', type=float, default=1.70, help='standing height in metres')
    p.add_argument('--age', type=float, default=30.0, help='years when > 1.0, raw MPFB macro (0..1) when <= 1.0')
    p.add_argument('--gender', type=float, default=0.5, help='MPFB macro, 0 female .. 1 male')
    p.add_argument('--weight', type=float, default=0.5)
    p.add_argument('--muscle', type=float, default=0.5)
    p.add_argument('--height01', type=float, default=0.5, help='MPFB height macro before scaling')
    p.add_argument('--motion', default='cmu/02_01')
    p.add_argument('--out', default=DEFAULT_OUT)
    p.add_argument('--fps', type=int, default=0, help="scene fps; 0 = the clip's own fps (1:1 frames)")
    p.add_argument('--ground-lock', choices=('auto', 'on', 'off'), default='auto')
    p.add_argument('--no-strip', action='store_true')
    p.add_argument('--list-motions', action='store_true')
    p.add_argument(
        '--check',
        metavar='BLEND',
        nargs='?',
        const='',
        default=None,
        help='measure an existing .blend instead of building',
    )
    return p.parse_args(argv)


def load_library():
    with open(os.path.join(MOTION_ROOT, 'library.json'), 'r', encoding='utf-8') as fh:
        return json.load(fh)


def all_motions(lib):
    """Every source: BVH clips, authored actions, captures, motion_edit derivatives."""
    return list(lib['clips']) + list(lib.get('authored', [])) + list(lib.get('capture', [])) + list(lib.get('edit', []))


def find_clip(lib, motion_id):
    for clip in all_motions(lib):
        if clip['id'] == motion_id:
            return clip
    raise SystemExit('unknown motion %r; --list-motions shows the library' % motion_id)


def age_macro(age):
    """MPFB/MakeHuman age macro: 0.0 = 1 y, 0.5 = 25 y, 1.0 = 90 y."""
    if age <= 1.0:
        return max(0.0, min(1.0, age))
    if age <= 25.0:
        return max(0.0, (age - 1.0) / 24.0 * 0.5)
    return min(1.0, 0.5 + (age - 25.0) / 65.0 * 0.5)


# --------------------------------------------------------------------- scene


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)


def evaluated_points(obj, indices=()):
    """World bbox of the evaluated (posed) mesh + the mean of `indices`.

    Both in one evaluation because the caller wants them on every frame. The
    armature modifier does not change topology, so rest-mesh vertex indices
    address the same vertices here."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    mat = ev.matrix_world
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for vert in mesh.vertices:
        world = mat @ vert.co
        for i in range(3):
            lo[i] = min(lo[i], world[i])
            hi[i] = max(hi[i], world[i])
    centroid = None
    if indices:
        total = Vector((0.0, 0.0, 0.0))
        for index in indices:
            total += mat @ mesh.vertices[index].co
        centroid = total / len(indices)
    ev.to_mesh_clear()
    return lo, hi, centroid


def evaluated_bbox(obj):
    lo, hi, _centroid = evaluated_points(obj)
    return lo, hi


def standing_height(obj):
    lo, hi = evaluated_bbox(obj)
    return hi.z - lo.z
