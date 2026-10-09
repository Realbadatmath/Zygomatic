# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import bpy

from zyg_workflows.blender_scripts import skeleton_bind
from zyg_workflows.blender_scripts.proxy_actor.args_scene import evaluated_bbox
from zyg_workflows.blender_scripts.proxy_actor.body import bake_pose_as_rest
from zyg_workflows.blender_scripts.proxy_actor.constants import FIT_GROUPS, FIT_MAX, FIT_MIN, FIT_TOL

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ----------------------------------------------------------------------- fit


def measure_fit(arm, body):
    """The five fitted proportions, as fractions of the CURRENT standing height.

    leg        hip joint -> ankle          LeftUpLeg.head -> LeftFoot.head
    arm        shoulder -> wrist           LeftArm.head -> LeftHand.head
    torso      mid-shoulders -> mid-hips   mid(L,R Arm.head) -> Hips.head
    head_neck  crown -> mid-shoulders      mesh max z - mid(L,R Arm.head).z
    shoulder   shoulder to shoulder        |LeftArm.head - RightArm.head|
    Read from the POSED rig and the evaluated mesh, so the solver below can
    measure a trial pose without applying it."""
    bpy.context.view_layer.update()
    lo, hi = evaluated_bbox(body)
    height = hi.z - lo.z
    mat = arm.matrix_world

    def head(name):
        return mat @ arm.pose.bones[name].head

    mid_sh = (head('LeftArm') + head('RightArm')) * 0.5
    raw = {
        'leg': (head('LeftUpLeg') - head('LeftFoot')).length,
        'arm': (head('LeftArm') - head('LeftHand')).length,
        'torso': (mid_sh - head('Hips')).length,
        'head_neck': hi.z - mid_sh.z,
        'shoulder': (head('LeftArm') - head('RightArm')).length,
    }
    return height, {key: value / height for key, value in raw.items()}


def load_fit_spec(path):
    with open(path, 'r', encoding='utf-8') as fh:
        spec = json.load(fh)
    want = spec.get('fractions') or {}
    unknown = sorted(set(want) - set(FIT_GROUPS))
    if unknown:
        raise SystemExit('--fit %s: unknown groups %s (known: %s)' % (path, unknown, sorted(FIT_GROUPS)))
    if not want:
        raise SystemExit('--fit %s carries no "fractions"' % path)
    return spec, want


def fit_rig(arm, body, want, iterations=20, tol=0.005, damping=0.7):
    """Scale each bone group along its own length until the measured fractions match.

    A one-shot factor = target / rig_fraction would miss: every group that grows
    or shrinks also moves the standing height the fractions are measured against,
    and the groups move each other's landmarks too (a shorter torso lowers the
    mid-shoulder point the head_neck span is measured from). So the clamped
    one-shot factor is only the STARTING point of a damped fixed-point solve on
    the live pose; the best pass is kept and only that pose is applied as rest.
    The remaining coupling is why the solve is damped and why the best iterate,
    not the last, is the answer — undamped it drifts into a slow limit cycle."""
    height0, frac0 = measure_fit(arm, body)
    requested, clamped, goal, active, skipped = {}, {}, {}, {}, {}
    for group in FIT_GROUPS:
        if group not in want:
            continue
        requested[group] = want[group] / frac0[group]
        clamped[group] = min(FIT_MAX, max(FIT_MIN, requested[group]))
        goal[group] = frac0[group] * clamped[group]
        if abs(clamped[group] - 1.0) <= 0.01:
            skipped[group] = True
        else:
            active[group] = clamped[group]

    inherit0 = {bone.name: bone.inherit_scale for bone in arm.data.bones}
    for bone in arm.data.bones:
        # A scaled parent must lengthen the chain below it without also
        # stretching the bones in it (a scaled thigh moves the knee, it does not
        # scale the shin twice).
        bone.inherit_scale = 'NONE'

    def pose(factors):
        for group, factor in factors.items():
            for name in FIT_GROUPS[group]:
                arm.pose.bones[name].scale.y = factor
        return measure_fit(arm, body)[1]

    used, frac, best = 0, frac0, None
    for used in range(1, iterations + 1):
        frac = pose(active)
        worst = max(abs(frac[g] / goal[g] - 1.0) for g in goal)
        _zyg_log.info(
            '[proxy]   fit pass %d: %s (worst %+.3f%%)'
            % (used, ' '.join('%s=%.4f' % (g, frac[g]) for g in sorted(goal)), 100.0 * worst)
        )
        if best is None or worst < best[0]:
            best = (worst, dict(active))
        if worst < tol or not active:
            break
        for group in active:
            step = (goal[group] / frac[group]) ** damping
            active[group] = min(FIT_MAX, max(FIT_MIN, active[group] * step))
    if best is not None and active != best[1]:
        active = best[1]
        frac = pose(active)
        _zyg_log.info('[proxy]   fit keeping the best pass (worst %+.3f%%)' % (100.0 * best[0]))

    if active:
        bake_pose_as_rest(arm, body)
    for bone in arm.data.bones:
        bone.inherit_scale = inherit0.get(bone.name, 'FULL')

    height1, frac1 = measure_fit(arm, body)
    report = {
        'clamp': [FIT_MIN, FIT_MAX],
        'tolerance': FIT_TOL,
        'passes': used,
        'height_before_m': round(height0, 4),
        'height_after_m': round(height1, 4),
        'groups': {},
    }
    worst = 0.0
    hit_clamp = []
    for group in sorted(goal):
        error = frac1[group] / goal[group] - 1.0
        worst = max(worst, abs(error))
        limited = not (FIT_MIN - 1e-9 <= requested[group] <= FIT_MAX + 1e-9)
        if limited:
            hit_clamp.append(group)
        report['groups'][group] = {
            'target': round(want[group], 4),
            'rig_fraction': round(frac0[group], 4),
            'requested': round(requested[group], 4),
            'clamped': round(clamped[group], 4),
            'clamped_target': round(goal[group], 4),
            'applied': round(active.get(group, 1.0), 4),
            'measured': round(frac1[group], 4),
            'rel_error': round(error, 4),
            'skipped': bool(skipped.get(group)),
            'hit_clamp': bool(limited),
        }
    report['worst_rel_error'] = round(worst, 4)
    report['ok'] = bool(worst <= FIT_TOL)
    report['clamped_groups'] = hit_clamp
    # A fit is never fatal: the build continues with whatever the clamp allowed.
    # 'clamped' means a group asked for more reshaping than [FIT_MIN, FIT_MAX]
    # permits (the clamped target was still met); 'off' means the solve missed
    # its clamped target for some other reason. Both leave report['ok'] False-y
    # only when the tolerance itself was missed — 'ok' stays the truthful flag.
    if hit_clamp:
        report['status'] = 'clamped'
    elif report['ok']:
        report['status'] = 'exact'
    else:
        report['status'] = 'off'

    _zyg_log.info(
        '[proxy] fit  %-10s %8s %8s %8s %8s %8s %8s'
        % ('group', 'target', 'rig', 'request', 'clamped', 'measured', 'err')
    )
    for group in sorted(report['groups']):
        row = report['groups'][group]
        _zyg_log.info(
            '[proxy]      %-10s %8.4f %8.4f %8.4f %8.4f %8.4f %+7.2f%%%s'
            % (
                group,
                row['target'],
                row['rig_fraction'],
                row['requested'],
                row['clamped_target'],
                row['measured'],
                100.0 * row['rel_error'],
                '  (skipped)' if row['skipped'] else '',
            )
        )
    _zyg_log.info(
        '[proxy] fit  height %.4f -> %.4f m in %d passes, worst error %.2f%%' % (height0, height1, used, 100.0 * worst)
    )
    _zyg_log.info(
        '[proxy] fit  status %s%s (ok=%s)'
        % (
            report['status'],
            (
                ' ['
                + ' '.join(
                    '%s wanted x%.3f, applied x%.3f'
                    % (g, report['groups'][g]['requested'], report['groups'][g]['applied'])
                    for g in hit_clamp
                )
                + ']'
            )
            if hit_clamp
            else '',
            report['ok'],
        )
    )
    return report


def scale_actor(arm, body, factor):
    """Uniform scale of rest geometry: mesh vertices and edit bones by the same factor.

    Done on the data, not on the object transforms, so armature deformation stays
    exact and both objects keep an identity matrix."""
    for mesh in [body] + [m for m in skeleton_bind.EXTRA_MESHES if m.name in bpy.data.objects]:
        for vert in mesh.data.vertices:
            vert.co *= factor
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in arm.data.edit_bones:
        roll = bone.roll
        bone.head = bone.head * factor
        bone.tail = bone.tail * factor
        bone.roll = roll
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
