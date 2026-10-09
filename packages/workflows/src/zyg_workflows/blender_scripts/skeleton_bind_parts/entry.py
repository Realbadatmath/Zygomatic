# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The public entry point ``attach_skeleton`` and the stand-alone harness.

``LAST_FIT`` lives here because ``attach_skeleton`` REBINDS it (``global
LAST_FIT``) and ``main`` reads it: state and mutator stay in one module, so
no importer can hold a stale copy.  The shim resolves it live."""

import json
import math
import os
import tempfile

import bpy
from mathutils import Matrix

from .body_boxes import (
    _body_boxes,
    _body_bvh,
    _column_overflow,
    _neighbour_box,
    _surface_depth,
)
from .constants import (
    BASE_BODY_RIG_DIR,
    EXTRA_MESHES,
    INSIDE_MARGIN,
    SOURCE_CREDIT,
    TRI_BUDGET_HIGH,
    TRI_BUDGET_TARGET,
    TRI_FLOOR,
)
from .loading import _link, _mesh_height, _origins, load_skeleton_pieces
from .piece_map import bone_for_piece
from .placement import _bone_world, _skin_columns, compute_placement
from .tuck import (
    TUCK_BAND,
    TUCK_MARGIN,
    TUCK_PUSH_UNITS,
    TUCK_UNITS,
    _piece_box,
    _skin_depth_columns,
    _tuck_push,
    _tuck_trunk,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Stats of the most recent attach_skeleton() call; the harness serialises it.
LAST_FIT: dict = {}

# --------------------------------------------------------------------------
# the public entry point
# --------------------------------------------------------------------------


def attach_skeleton(arm, body, name='skeleton'):
    """Fit the CC0 skeleton to ``arm`` inside ``body`` and return the new mesh."""
    global LAST_FIT

    pieces = load_skeleton_pieces()
    origins = _origins(pieces)

    mapping = {}
    unmapped = []
    for short in sorted(pieces):
        bone = bone_for_piece(short)
        if bone is None or bone not in arm.data.bones:
            unmapped.append(short)
        else:
            mapping[short] = bone
    if unmapped:
        _zyg_log.info(' '.join(str(a) for a in ('[skeleton_bind] UNMAPPED PIECES:', unmapped)))

    xs = [o.x for o in origins.values()]
    mid_x = 0.5 * (min(xs) + max(xs))

    zs = [(p.matrix_world @ v.co).z for p in pieces.values() for v in p.data.vertices]
    h_skel = max(zs) - min(zs)
    h_body = _mesh_height(body)
    s = h_body / h_skel

    placement, piece_fix = compute_placement(arm, origins, s, mid_x, pieces, mapping, body)

    # where the trunk block's landmarks end up (reported, per the brief)
    trunk_mat = placement['Hips'][0]
    anchors = {}
    for label, key, bone in (
        ('hip', 'hip', 'LowerBack'),
        ('femur.L', 'leg_femur.L', 'LeftUpLeg'),
        ('femur.R', 'leg_femur.R', 'RightUpLeg'),
    ):
        head_r, _ = _bone_world(arm, bone)
        landed = trunk_mat @ origins[key]
        anchors[label] = {
            'bone': bone,
            'landed': [round(c, 4) for c in landed],
            'bone_head': [round(c, 4) for c in head_r],
            'distance_m': round((landed - head_r).length, 4),
        }

    for short, obj in pieces.items():
        bone = mapping.get(short)
        if bone is None:
            continue
        obj.matrix_world = piece_fix.get(short, Matrix.Identity(4)) @ placement[bone][0] @ obj.matrix_world

    bpy.context.view_layer.update()

    # ---- the tuck: no trunk bone outside the skin (see _tuck_trunk) -------
    tuck = _tuck_trunk(pieces, mapping, _skin_depth_columns(body))
    for unit in sorted(tuck):
        t = tuck[unit]
        _zyg_log.info(
            '[skeleton_bind] tuck %-6s %3d pieces  clearance %+.2f -> %+.2f mm '
            'in %d pass(es)%s'
            % (
                unit,
                t['pieces'],
                t['clearance_before_mm'],
                t['clearance_after_mm'],
                len(t['passes']),
                '' if t['cleared'] else '  NOT CLEARED',
            )
        )
        for i, st in enumerate(t['passes']):
            f = st.get('depth')
            if f:
                _zyg_log.info(
                    '[skeleton_bind]      pass %d %-5s %2d bands x %.0f cm  scale '
                    'x%.4f..1  slide <=%.2f mm%s'
                    % (
                        i + 1,
                        f['axis'],
                        len(f['bands']),
                        100.0 * TUCK_BAND,
                        f['scale_min'],
                        f['slide_mm_max'],
                        '' if f['band_feasible'] else '  (infeasible bands)',
                    )
                )

    # ---- per-group containment against the body's own weighting -----------
    body_boxes = _body_boxes(body, 0.0)
    body_boxes_w50 = _body_boxes(body, 0.5)
    bvh = _body_bvh(body)
    cols = _skin_columns(body)
    groups = {}
    for short, bone in mapping.items():
        groups.setdefault(bone, []).append(short)

    group_report = {}
    for bone in sorted(groups):
        lo = [1e9] * 3
        hi = [-1e9] * 3
        n_out = 0
        n_tot = 0
        worst = 0.0
        worst_piece = None
        worst_at = None
        column = 0.0
        for short in groups[bone]:
            plo, phi = _piece_box(pieces[short])
            for i in range(3):
                lo[i] = min(lo[i], plo[i])
                hi[i] = max(hi[i], phi[i])
            column = max(column, _column_overflow(cols, pieces[short]))
            frac, deep, where = _surface_depth(bvh, pieces[short])
            n = len(pieces[short].data.vertices)
            n_tot += n
            n_out += int(round(frac * n))
            if deep > worst:
                worst, worst_piece, worst_at = deep, short, where
        blo, bhi = _neighbour_box(arm, body_boxes, bone)
        over = [0.0] * 3
        for i in range(3):
            over[i] = max(0.0, (blo[i] - INSIDE_MARGIN) - lo[i], hi[i] - (bhi[i] + INSIDE_MARGIN))
        info = dict(placement[bone][1])
        info['pieces'] = sorted(groups[bone])
        info.setdefault(
            'residual_m',
            round(min((trunk_mat @ origins[p] - _bone_world(arm, bone)[0]).length for p in groups[bone]), 6),
        )
        info['bbox'] = [[round(c, 4) for c in lo], [round(c, 4) for c in hi]]
        info['body_bbox'] = [[round(c, 4) for c in blo], [round(c, 4) for c in bhi]]
        info['body_bbox_w50'] = [[round(c, 4) for c in b] for b in body_boxes_w50.get(bone, ([0, 0, 0], [0, 0, 0]))]
        info['overflow_mm'] = [round(o * 1000.0, 1) for o in over]
        info['column_overflow_mm'] = round(column * 1000.0, 1)
        info['outside_frac'] = round(n_out / float(n_tot or 1), 5)
        info['outside_depth_mm'] = round(worst * 1000.0, 1)
        info['outside_worst_piece'] = worst_piece
        info['outside_worst_at'] = [round(c, 4) for c in worst_at] if worst_at else None
        info['inside'] = max(over) <= 1e-9
        group_report[bone] = info

    # ---- one mesh, rigid weights -----------------------------------------
    for short, obj in pieces.items():
        bone = mapping.get(short)
        if bone is None:
            continue
        vg = obj.vertex_groups.new(name=bone)
        vg.add(list(range(len(obj.data.vertices))), 1.0, 'REPLACE')

    skel = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    _link(skel)
    skel.matrix_world = Matrix.Identity(4)

    joinable = [pieces[s_] for s_ in mapping]
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in joinable:
        obj.select_set(True)
    skel.select_set(True)
    bpy.context.view_layer.objects.active = skel
    bpy.ops.object.join()
    skel.data.name = name

    skel.data.calc_loop_triangles()
    tris_joined = len(skel.data.loop_triangles)
    decimated = None
    if tris_joined > TRI_BUDGET_HIGH:
        ratio = TRI_BUDGET_TARGET / float(tris_joined)
        mod = skel.modifiers.new('Decimate', 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = ratio
        mod.use_symmetry = True
        mod.symmetry_axis = 'X'
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        baked = bpy.data.meshes.new_from_object(skel.evaluated_get(dg))
        old = skel.data
        skel.data = baked
        skel.modifiers.clear()
        if old.users == 0:
            bpy.data.meshes.remove(old)
        skel.data.name = name
        decimated = round(ratio, 4)

    # rigid weights: exactly one group per vertex at 1.0
    _harden_weights(skel)

    # the last line of the tuck, on the mesh as it ships (see TUCK_PUSH_UNITS)
    # to TUCK_MARGIN, not to the pass mark: the bind pose is not the only pose,
    # and the chest skin still travels ~10 mm in the thorax's frame on a walk
    push = _tuck_push(
        skel, bvh, [b for unit, bones in TUCK_UNITS if unit in TUCK_PUSH_UNITS for b in bones], clear=TUCK_MARGIN
    )
    _zyg_log.info(
        '[skeleton_bind] tuck push  %d vertices back under the skin '
        '(worst %.2f mm, skirt %d)' % (push['vertices'], push['worst_mm'], push['skirt'])
    )

    skel.data.calc_loop_triangles()
    tris = len(skel.data.loop_triangles)

    skel.parent = arm
    skel.matrix_parent_inverse = Matrix.Identity(4)
    skel.matrix_world = Matrix.Identity(4)
    mod = skel.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm
    while skel.modifiers.find('Armature') > 0:
        with bpy.context.temp_override(object=skel):
            bpy.ops.object.modifier_move_up(modifier='Armature')

    skel['pieces'] = json.dumps(mapping, sort_keys=True)
    skel['source'] = SOURCE_CREDIT

    if skel not in EXTRA_MESHES:
        EXTRA_MESHES.append(skel)

    LAST_FIT = {
        'pieces': len(mapping),
        'unmapped': sorted(unmapped),
        'groups': group_report,
        'vertices': len(skel.data.vertices),
        'triangles': tris,
        'triangles_joined': tris_joined,
        'decimate_ratio': decimated,
        'height_skeleton': round(h_skel, 5),
        'height_body': round(h_body, 5),
        's': round(s, 6),
        'trunk_anchors': anchors,
        'tuck': tuck,
        'tuck_push': push,
        'source': SOURCE_CREDIT,
    }
    return skel


def _harden_weights(obj):
    """Keep the heaviest vertex group per vertex at 1.0, drop the rest."""
    names = [vg.name for vg in obj.vertex_groups]
    buckets = {n: [] for n in names}
    for v in obj.data.vertices:
        best = None
        for g in v.groups:
            if best is None or g.weight > best.weight:
                best = g
        if best is None:
            continue
        buckets[names[best.group]].append(v.index)
    for vg in list(obj.vertex_groups):
        vg.remove(list(range(len(obj.data.vertices))))
    for n, idx in buckets.items():
        if idx:
            obj.vertex_groups[n].add(idx, 1.0, 'REPLACE')


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


def _render(skel, body, out_dir, rig, height):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1600
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False

    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'OBJECT'
    sh.show_shadows = False
    sh.show_cavity = True
    sh.background_type = 'VIEWPORT'
    sh.background_color = (0.10, 0.11, 0.13)
    scene.display.render_aa = '8'

    skel.color = (0.96, 0.93, 0.84, 1.0)

    # the body as a wireframe cage so the fit can be judged by eye
    body.hide_render = True
    wire = bpy.data.objects.new('body_wire', body.data)
    _link(wire)
    wire.matrix_world = body.matrix_world.copy()
    wmod = wire.modifiers.new('Wireframe', 'WIREFRAME')
    wmod.thickness = 0.0016
    wmod.use_replace = True
    wire.color = (0.20, 0.55, 0.85, 1.0)

    cam_data = bpy.data.cameras.new('fitcam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = height * 1.12
    cam = bpy.data.objects.new('fitcam', cam_data)
    _link(cam)
    scene.camera = cam
    mid = height * 0.5

    paths = {}
    for label, loc, rot in (
        ('front', (0.0, -4.0, mid), (math.pi / 2, 0.0, 0.0)),
        ('side', (4.0, 0.0, mid), (math.pi / 2, 0.0, math.pi / 2)),
    ):
        cam.location = loc
        cam.rotation_euler = rot
        path = os.path.join(out_dir, 'skeleton_fit_%s_%s.png' % (rig, label))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        paths[label] = path
    body.hide_render = False
    return paths


def main(argv):
    rig = 'male_realistic'
    out_dir = os.path.join(tempfile.gettempdir(), 'skelfit')
    i = 0
    while i < len(argv):
        if argv[i] == '--rig':
            rig = argv[i + 1]
            i += 2
        elif argv[i] == '--out':
            out_dir = argv[i + 1]
            i += 2
        else:
            i += 1
    os.makedirs(out_dir, exist_ok=True)

    blend = os.path.join(BASE_BODY_RIG_DIR, rig, rig + '.blend')
    if not os.path.exists(blend):
        raise SystemExit('[skeleton_bind] missing base body rig: %s' % blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    bpy.context.view_layer.update()

    arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    bodies = [o for o in bpy.data.objects if o.type == 'MESH']
    if len(arms) != 1 or not bodies:
        raise SystemExit('[skeleton_bind] expected one armature + one mesh in %s' % blend)
    arm = arms[0]
    body = bodies[0]

    skel = attach_skeleton(arm, body)
    fit = dict(LAST_FIT)

    print('[skeleton_bind] rig=%s pieces=%d unmapped=%d' % (rig, fit['pieces'], len(fit['unmapped'])))
    print(
        '[skeleton_bind] skeleton %.4f m -> body %.4f m  s=%.5f'
        % (fit['height_skeleton'], fit['height_body'], fit['s'])
    )
    print(
        '[skeleton_bind] triangles joined=%d final=%d decimate=%s vertices=%d'
        % (fit['triangles_joined'], fit['triangles'], fit['decimate_ratio'], fit['vertices'])
    )
    for label, a in sorted(fit['trunk_anchors'].items()):
        print('[skeleton_bind] trunk anchor %-8s -> %-14s %.4f m' % (label, a['bone'], a['distance_m']))
    for bone in sorted(fit['groups']):
        g = fit['groups'][bone]
        print(
            '[skeleton_bind] %-16s %-5s n=%-3d resid=%.4f axis=%.3f%s inside=%-5s '
            'over_mm=%-20s column=%4.1fmm  nearest=%.1f%%/%.1fmm  %s%s'
            % (
                bone,
                g['kind'],
                len(g['pieces']),
                g['residual_m'],
                g['axis_scale'],
                '*' if g.get('clamped') else ' ',
                g['inside'],
                g['overflow_mm'],
                g['column_overflow_mm'],
                100.0 * g['outside_frac'],
                g['outside_depth_mm'],
                g.get('anchor', ''),
                (' off=%.3fm' % g['rig_head_offset_m']) if g.get('rig_head_offset_m') else '',
            )
        )

    paths = _render(skel, body, out_dir, rig, fit['height_body'])
    fit['renders'] = paths
    json_path = os.path.join(out_dir, 'fit_%s.json' % rig)
    with open(json_path, 'w') as fh:
        json.dump(fit, fh, indent=1, sort_keys=True)
    print('[skeleton_bind] wrote %s' % json_path)
    print('[skeleton_bind] wrote %s' % paths['front'])
    print('[skeleton_bind] wrote %s' % paths['side'])

    fails = []
    if fit['pieces'] != 135:
        fails.append('pieces=%d != 135' % fit['pieces'])
    if fit['unmapped']:
        fails.append('unmapped=%s' % fit['unmapped'])
    for unit, t in sorted(fit.get('tuck', {}).items()):
        if not t['cleared']:
            fails.append('%s clears the skin by only %.2f mm after the tuck' % (unit, t['clearance_after_mm']))
    for bone, g in sorted(fit['groups'].items()):
        if g['kind'] == 'limb' and g['residual_m'] >= 0.006:
            fails.append('%s residual %.4f' % (bone, g['residual_m']))
        if not g['inside']:
            fails.append('%s outside: bbox %s mm, skin %.1f mm' % (bone, g['overflow_mm'], g['outside_depth_mm']))
    if fit['triangles'] < TRI_FLOOR:
        fails.append('triangles %d < %d' % (fit['triangles'], TRI_FLOOR))

    if fails:
        print('[skeleton_bind] FAIL: ' + '; '.join(fails))
        return 1
    print('[skeleton_bind] OK %s' % rig)
    return 0
