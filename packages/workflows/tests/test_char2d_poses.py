# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char2d_poses: the ROM validator must make impossible hands unrepresentable.

No GPU, no Blender: char2d_build is imported with a stub bpy purely to compare
its idle table with the copy in char2d_poses.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types

import pytest

from tests import _tree
from zyg_workflows import char2d_poses as P

GESTURE_DIR = _tree.pkg('data', 'char2d', 'gestures')

#: The CLI is the module's own ``__main__``; it is reached by name, not by file path,
#: because the module is installed rather than sitting next to the test.
CLI = ['-m', 'zyg_workflows.char2d_poses']


def gesture(bones_per_key, hands='R'):
    """A minimal well-formed gesture around the given per-key bone dicts."""
    return {
        'name': 'test',
        'label': 'Test',
        'hands': hands,
        'meaning': 'test fixture',
        'reads_well': ['front'],
        'keys': [{'name': 'k%d' % i, 'hold_frames': 12, 'bones': bones} for i, bones in enumerate(bones_per_key, 1)],
    }


def fist_bones(side='R'):
    bones = {}
    for finger in (2, 3, 4, 5):
        for segment in (1, 2, 3):
            bones['finger%d-%d.%s' % (finger, segment, side)] = [60.0, 0.0, 0.0]
    bones['finger1-2.%s' % side] = [30.0, 0.0, 0.0]
    bones['finger1-3.%s' % side] = [30.0, 0.0, 0.0]
    return bones


# --------------------------------------------------------------- the four gates


def test_fist_validates():
    assert P.validate(gesture([{}, fist_bones()])) == []


def test_mcp_beyond_flexion_limit_fails():
    bad = fist_bones()
    bad['finger2-1.R'] = [95.0, 0.0, 0.0]
    errors = P.validate(gesture([{}, bad]))
    assert errors, 'MCP x=95 must be rejected (limit is 90)'
    assert any('finger2-1.R.x' in e and '[0, 90]' in e for e in errors), errors


def test_abduction_is_blocked_in_flexion():
    bad = fist_bones()
    bad['finger3-1.R'] = [70.0, 15.0, 0.0]
    errors = P.validate(gesture([{}, bad]))
    assert errors, 'MCP x=70 with y=15 must be rejected'
    assert any('abduction' in e and 'finger3-1.R' in e for e in errors), errors
    # ...and the same abduction is fine when the knuckle is not flexed.
    ok = fist_bones()
    ok['finger3-1.R'] = [10.0, 15.0, 0.0]
    assert P.validate(gesture([{}, ok])) == []


def test_five_keys_fail():
    errors = P.validate(gesture([{}, fist_bones(), {}, fist_bones(), {}]))
    assert any('5 keys' in e for e in errors), errors


# ------------------------------------------------------------- schema details


def test_unknown_bone_is_rejected():
    errors = P.validate(gesture([{}, {'forearm.R': [10.0, 0.0, 0.0]}]))
    assert any('unknown bone' in e for e in errors), errors


@pytest.mark.parametrize('hold', [0, 4, 25, 48])
def test_hold_frames_outside_the_band_fail(hold):
    bad = gesture([{}, fist_bones()])
    bad['keys'][1]['hold_frames'] = hold
    assert any('hold_frames' in e for e in P.validate(bad))


def test_hands_must_match_the_sides_used():
    left = P.validate(gesture([{}, fist_bones('L')], hands='R'))
    assert any('hands=R' in e for e in left), left
    both = P.validate(gesture([{}, fist_bones('R')], hands='both'))
    assert any('hands=both' in e for e in both), both
    assert P.validate(gesture([{}, fist_bones('L')], hands='L')) == []


def test_mirror_flips_side_and_negates_y_and_z():
    mirrored = P.mirror({'upperarm01.L': [10.0, 20.0, -40.0], 'head': [5.0, 0.0, 0.0]})
    assert mirrored['upperarm01.R'] == [10.0, -20.0, 40.0]
    assert mirrored['head'] == [5.0, 0.0, 0.0]
    assert P.mirror(P.mirror({'wrist.R': [1.0, 2.0, 3.0]})) == {'wrist.R': [1.0, 2.0, 3.0]}


def test_rig_covers_both_sides_explicitly():
    for name in ('clavicle', 'shoulder01', 'upperarm01', 'upperarm02', 'lowerarm01', 'lowerarm02', 'wrist'):
        assert '%s.L' % name in P.ROM and '%s.R' % name in P.ROM
    for finger in (1, 2, 3, 4, 5):
        for segment in (1, 2, 3):
            for side in ('L', 'R'):
                assert 'finger%d-%d.%s' % (finger, segment, side) in P.ROM
    for name in ('spine01', 'spine05', 'neck01', 'neck03', 'head', 'jaw'):
        assert name in P.ROM


# ---------------------------------------------------- idle agrees with the build


def _load_char2d_build():
    """Import blender_scripts/char2d_build.py with a stub bpy (module level only)."""
    stub_bpy = types.ModuleType('bpy')
    stub_bpy.data = types.SimpleNamespace()
    stub_bpy.ops = types.SimpleNamespace()
    stub_bpy.context = types.SimpleNamespace()
    stub_mathutils = types.ModuleType('mathutils')
    stub_mathutils.Vector = tuple
    stub_extras = types.ModuleType('bpy_extras')
    stub_objutils = types.ModuleType('bpy_extras.object_utils')
    stub_objutils.world_to_camera_view = lambda *a, **k: None
    stub_extras.object_utils = stub_objutils
    saved = {
        name: sys.modules.get(name)
        for name in ('bpy', 'mathutils', 'bpy_extras', 'bpy_extras.object_utils', 'char2d_build')
    }
    sys.modules.update(
        {
            'bpy': stub_bpy,
            'mathutils': stub_mathutils,
            'bpy_extras': stub_extras,
            'bpy_extras.object_utils': stub_objutils,
        }
    )
    try:
        path = _tree.pkg('blender_scripts', 'char2d_build.py')
        spec = importlib.util.spec_from_file_location('char2d_build', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_idle_pose_matches_the_build_script():
    build = _load_char2d_build()
    theirs = {k: tuple(float(a) for a in v) for k, v in build.idle_pose().items()}
    ours = {k: tuple(float(a) for a in v) for k, v in P.IDLE_POSE.items()}
    assert theirs == ours


def test_idle_pose_is_inside_the_rom():
    errors = []
    for name, angles in P.IDLE_POSE.items():
        errors.extend(P.check_bone(name, list(angles)))
    assert errors == []


# ------------------------------------------------------------- shipped gestures


def test_shipped_gestures_validate():
    gestures = P.load_all(GESTURE_DIR)
    assert set(gestures) >= {'00_idle', '01_open_palm'}, sorted(gestures)
    for name, data in gestures.items():
        assert P.validate(data) == [], name


def test_idle_gesture_is_the_build_idle():
    with open(os.path.join(GESTURE_DIR, '00_idle.json'), 'r', encoding='utf-8') as fh:
        idle = json.load(fh)
    assert len(idle['keys']) == 1
    bones = {k: tuple(v) for k, v in idle['keys'][0]['bones'].items()}
    assert bones == {k: tuple(v) for k, v in P.IDLE_POSE.items()}


def test_cli_validate_and_idle():
    paths = sorted(os.path.join(GESTURE_DIR, f) for f in os.listdir(GESTURE_DIR) if f.endswith('.json'))
    done = subprocess.run(
        [sys.executable] + CLI + ['validate'] + paths,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    for path in paths:
        assert os.path.basename(path) in done.stdout

    done = subprocess.run([sys.executable] + CLI + ['idle'], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == P.idle_bones()


def test_cli_validate_rejects_a_broken_gesture(tmp_path):
    bad = gesture([{}, {'finger2-1.R': [95.0, 0.0, 0.0]}])
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(bad), encoding='utf-8')
    done = subprocess.run(
        [sys.executable] + CLI + ['validate', str(path)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1
    assert 'FAIL' in done.stdout
