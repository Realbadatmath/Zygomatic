# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``build()`` and ``main()`` — base_body_rig section 13 (pipeline.py).

Named pipeline.py, not build.py: a submodule called ``build`` would be set as a
package attribute and collide with the original module's own ``build()``.

Imported last by the package __init__, exactly as this section stood last in
the single file: the bare ``main()`` call at the bottom is the original
module-level side effect and still runs when the module is imported.
"""

import json
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .rig import (
    bind,
    bone_table,
    is_inside,
    nudge_inside,
    pin_eyes,
    rename_bones,
    render_rest,
    run_checks,
    surface_distance,
    symmetrise,
    unweighted,
    write_bones,
)
from .scene import (
    BODIES,
    BONE_RENAME,
    CLUSTER_GAP,
    CREWS,
    MAX_BLEND_MB,
    SLICE_BAND,
    SRC_BLEND,
    clear_scene,
    local_verts,
    parse_args,
    prepare_base,
)
from .transfer import (
    ZIndex,
    arm_side,
    build_arm_axes,
    build_donor,
    transfer_point,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ----------------------------------------------------------------------- main


def build(args):
    started = time.time()
    body_id = args.body
    clear_scene()

    base, height, mesh_stats = prepare_base(body_id)
    donor, arm = build_donor(BODIES[body_id]['gender'], height)
    rename_bones(arm)  # before anything keys a dict on a bone name

    donor_index = ZIndex(local_verts(donor))
    base_index = ZIndex(local_verts(base))
    table = bone_table(arm)

    arm_axes, arm_report = build_arm_axes(donor_index, base_index, table)

    heads, tails, notes = {}, {}, {}
    for name, (head, tail) in table.items():
        for kind, point, out in (('head', head, heads), ('tail', tail, tails)):
            axis = arm_axes.get(arm_side(name, kind))
            if axis is not None:
                out[name], notes['%s.%s' % (name, kind)] = axis.transfer(point)
            else:
                out[name], notes['%s.%s' % (name, kind)] = transfer_point(point, donor_index, base_index)
    symmetrise(heads, tails)

    bpy.data.objects.remove(donor, do_unlink=True)
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(base, depsgraph)

    def axis_at(z):
        """The body's own centre line at this height — where a stray head is pulled."""
        band = base_index.band(z, 0.02) or base_index.band(base_index.zmax - 0.02, 0.02)
        return Vector((0.0, sum(p.y for p in band) / float(len(band)), z))

    nudged = {}
    for table_ref, kind in ((heads, 'head'), (tails, 'tail')):
        for name in list(table_ref):
            # pull a stray head to the centre line, a stray tail to its own head
            anchor = axis_at(table_ref[name].z) if kind == 'head' else heads[name]
            fixed, moved = nudge_inside(tree, table_ref[name], anchor)
            table_ref[name] = fixed
            if moved > 1e-6:
                nudged['%s.%s' % (name, kind)] = round(moved, 5)
    symmetrise(heads, tails)

    write_bones(arm, heads, tails)
    arm.name = arm.data.name = body_id + '_rig'
    arm.matrix_world = Matrix.Identity(4)
    base.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()

    outside = {}
    for bone in arm.data.bones:
        for kind, point in (('head', bone.head_local), ('tail', bone.tail_local)):
            key = '%s.%s' % (bone.name, kind)
            outside[key] = 0.0 if is_inside(tree, point) else surface_distance(tree, point)

    bind(base, arm)
    eye_verts = pin_eyes(base)
    unweighted_count = unweighted(base)
    _zyg_log.info(
        '[rig] bone heat bound: %d verts, %d groups, %d eye verts pinned to Head, '
        '%d unweighted' % (len(base.data.vertices), len(base.vertex_groups), eye_verts, unweighted_count)
    )

    wanted = sorted(table)
    checks, measures = run_checks(base, arm, height, wanted, outside, unweighted_count)

    out_dir = os.path.join(args.out, body_id)
    os.makedirs(out_dir, exist_ok=True)
    blend_path = os.path.join(out_dir, body_id + '.blend')
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info('[rig] orphan purge skipped: %r' % (exc,))
    # No .blend1 sidecar: a 12 MB backup of a file we can rebuild is litter.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    size_mb = os.path.getsize(blend_path) / 1e6
    checks['blend_under_40mb'] = size_mb < MAX_BLEND_MB

    meta = {
        'schema': 'zyg.base_body_rig/1',
        'id': body_id,
        'source_blend': os.path.relpath(SRC_BLEND, CREWS),
        'source_object': BODIES[body_id]['object'],
        'licence': 'CC0-1.0',
        'height_m': round(height, 4),
        'vertices': len(base.data.vertices),
        'mesh': mesh_stats,
        'placement': {
            'method': 'mpfb donor joints; arms by fraction along the arm axis, '
            'the rest by slice-cluster (u,v) transfer with z preserved',
            'slice_band_m': SLICE_BAND,
            'cluster_gap_m': CLUSTER_GAP,
            'bone_rename': BONE_RENAME,
            'arm_axes': arm_report,
            'transfer': notes,
            'nudged_inside_m': nudged,
            'symmetrised': True,
        },
        'bones': [
            {
                'name': b.name,
                'parent': b.parent.name if b.parent else None,
                'head': [round(v, 5) for v in b.head_local],
                'tail': [round(v, 5) for v in b.tail_local],
            }
            for b in arm.data.bones
        ],
        'weights': {
            'verts_total': len(base.data.vertices),
            'verts_unweighted': unweighted_count,
            'bone_heat_failed': bool(unweighted_count > 0),
            'eye_verts_pinned_to_head': eye_verts,
        },
        'measures': measures,
        'blend_mb': round(size_mb, 2),
        'checks': checks,
        'built': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(os.path.join(out_dir, body_id + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=1)

    if not args.no_render:
        render_rest(base, arm, os.path.join(out_dir, body_id + '_rest.png'), height)

    _zyg_log.info('[rig] wrote %s (%.2f MB) in %.1fs' % (blend_path, size_mb, time.time() - started))
    return checks, measures


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    args = parse_args(argv)
    checks, measures = build(args)
    print('MEASURES ' + json.dumps(measures, sort_keys=True))
    print('CHECKS ' + json.dumps(checks, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit('checks failed: %s' % [k for k, v in checks.items() if not v])


main()
