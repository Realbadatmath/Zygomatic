# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The two base body rigs built by blender_scripts/base_body_rig.py.

Reads the sidecars only — no Blender, no bpy. The build script itself already
refuses to save when a check is false, so this suite is the standing proof that
the artefacts on disk are the ones that passed.
"""

import json
import os

import pytest

from tests import _tree
from zyg_workflows import motion_library

ROOT = _tree.data('assets', 'base_body_rig')
BODIES = ['male_realistic', 'female_realistic']
MAX_BLEND_MB = 40.0

CMU_MB = set(motion_library.CMU_MB_JOINTS)


def sidecar(body_id):
    path = os.path.join(ROOT, body_id, body_id + '.json')
    assert os.path.isfile(path), 'missing sidecar %s' % path
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


@pytest.fixture(scope='module', params=BODIES)
def rig(request):
    return request.param, sidecar(request.param)


def test_cmu_mb_joints_are_31():
    assert len(motion_library.CMU_MB_JOINTS) == 31
    assert len(CMU_MB) == 31


def test_blend_exists_and_is_small(rig):
    body_id, _meta = rig
    path = os.path.join(ROOT, body_id, body_id + '.blend')
    assert os.path.isfile(path), 'missing blend %s' % path
    mb = os.path.getsize(path) / (1024.0 * 1024.0)
    assert mb < MAX_BLEND_MB, '%s is %.2f MB' % (path, mb)


def test_rest_render_exists(rig):
    body_id, _meta = rig
    path = os.path.join(ROOT, body_id, body_id + '_rest.png')
    assert os.path.isfile(path), 'missing render %s' % path
    assert os.path.getsize(path) > 1024


def test_sidecar_header(rig):
    body_id, meta = rig
    assert meta['schema'] == 'zyg.base_body_rig/1'
    assert meta['id'] == body_id
    assert meta['source_blend'].endswith('.blend')
    assert meta['source_object'] == 'GEO-body_%s' % body_id
    assert 1.0 < meta['height_m'] < 2.5
    assert meta['vertices'] > 0
    assert meta['built']


def test_bone_names_match_cmu_mb(rig):
    _body_id, meta = rig
    names = [b['name'] for b in meta['bones']]
    assert len(names) == 31
    assert len(set(names)) == 31
    assert set(names) == CMU_MB


def test_bone_hierarchy(rig):
    _body_id, meta = rig
    by_name = {b['name']: b for b in meta['bones']}
    assert by_name['Hips']['parent'] is None
    for bone in meta['bones']:
        if bone['name'] == 'Hips':
            continue
        assert bone['parent'] in CMU_MB, '%s has parent %r' % (bone['name'], bone['parent'])


def test_bones_have_head_and_tail(rig):
    _body_id, meta = rig
    for bone in meta['bones']:
        for key in ('head', 'tail'):
            point = bone[key]
            assert len(point) == 3
            assert all(isinstance(c, float) for c in point), '%s.%s' % (bone['name'], key)


def test_weights_complete(rig):
    _body_id, meta = rig
    weights = meta['weights']
    assert weights['verts_unweighted'] == 0
    assert weights['verts_total'] > 0
    assert weights['bone_heat_failed'] is False


def test_arm_checks_are_recorded(rig):
    _body_id, meta = rig
    for name in ('arm_length_ok', 'arm_segments_ok', 'forearm_ratio_ok', 'elbow_height_ok', 'wrist_height_ok'):
        assert name in meta['checks'], 'no %s check in the sidecar' % name


def test_arm_is_the_length_of_a_human_arm(rig):
    """Shoulder to wrist, the defect this file's arm-axis transfer fixed.

    The z-preserving transfer used to park the wrist near the elbow and left the
    arm at 0.21 of standing height. A standing human measured with the arm
    STRAIGHT is 0.30-0.36; these bodies stand in an A-pose with a bent elbow, so
    the straight-line chord is a little under that while the two bone segments
    summed — the pose-independent length, and the one --fit scales — is 0.29-0.30.
    Both bands come from the meshes themselves, see base_body_rig.ARM_FRACTION."""
    _body_id, meta = rig
    arm = meta['measures']['arm']
    assert 0.27 <= arm['arm_fraction'] <= 0.33, arm
    assert 0.27 <= arm['arm_length_fraction'] <= 0.34, arm
    assert 0.75 <= arm['forearm_ratio'] <= 1.05, arm
    assert arm['shoulder_to_wrist_m'] == pytest.approx(arm['upper_arm_m'] + arm['forearm_m'], abs=0.05), arm
    assert arm['arm_fraction'] > 0.25, 'regressed to the z-preserving transfer'


def test_arm_joints_hang_down_the_a_pose(rig):
    """Shoulder above elbow above wrist, each in the band measured off the mesh."""
    _body_id, meta = rig
    arm = meta['measures']['arm']
    assert 0.61 <= arm['elbow_fraction'] <= 0.69, arm
    assert 0.50 <= arm['wrist_fraction'] <= 0.57, arm
    assert arm['shoulder_fraction'] > arm['elbow_fraction'] > arm['wrist_fraction'], arm


def test_arms_were_carried_along_the_arm_axis(rig):
    """Both arms isolated: a fallback to the old slice transfer is the defect."""
    _body_id, meta = rig
    axes = meta['placement']['arm_axes']
    assert set(axes) == {'LeftArm', 'RightArm'}, axes
    for bone, note in axes.items():
        assert note.startswith('donor '), '%s fell back: %s' % (bone, note)
    for bone in ('LeftForeArm', 'LeftHand', 'RightForeArm', 'RightHand'):
        assert meta['placement']['transfer']['%s.head' % bone].startswith('arm axis')


def test_every_check_passed(rig):
    _body_id, meta = rig
    checks = meta['checks']
    assert checks, 'no checks recorded'
    failed = sorted(name for name, ok in checks.items() if not ok)
    assert not failed, 'failed checks: %s' % failed
