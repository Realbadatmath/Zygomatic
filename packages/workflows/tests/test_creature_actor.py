# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The creature proxy actor exists and declares a usable creature mapping.

No bpy here — the .blend's own pose maths is proved by
``blender_scripts/build_pufferball_actor.py -- --check``.  This test guards the
seam task 9's exporter consumes: the files on disk, the sidecar's declared
mapping, and the joint_map's shape against the shared resolver's tables.
"""

import json
import os

import pytest

from zyg_workflows import paths
from zyg_workflows.blender_scripts import actor_joints as AJ

ACTOR_DIR = str(paths.ZYG_DATA_ROOT / 'architecture' / 'actors' / 'pufferball')
BLEND = os.path.join(ACTOR_DIR, 'pufferball.blend')
META = os.path.join(ACTOR_DIR, 'pufferball.json')
STRIP = os.path.join(ACTOR_DIR, 'pufferball_strip.png')

if not os.path.isdir(ACTOR_DIR):
    pytest.skip('the pufferball actor is not in this checkout: %s' % ACTOR_DIR, allow_module_level=True)


@pytest.fixture(scope='module')
def meta():
    with open(META, encoding='utf-8') as fh:
        return json.load(fh)


@pytest.mark.parametrize('path', [BLEND, META, STRIP])
def test_actor_files_exist(path):
    assert os.path.isfile(path), '%s is missing' % path
    assert os.path.getsize(path) > 1024, '%s is suspiciously small' % path


def test_mapping_is_creature(meta):
    assert meta['mapping'] == 'creature'
    assert meta['name'] == 'pufferball'
    assert meta['height_m'] == pytest.approx(0.30)


def test_at_least_ten_mapped_joints(meta):
    mapped = AJ.mapped_names(meta['joint_map'])
    assert len(mapped) >= 10, 'only %d joints mapped: %s' % (len(mapped), mapped)
    assert mapped == meta['mapped_joints']


def test_mapped_names_are_real_mediapipe_landmarks(meta):
    for name in meta['joint_map']:
        assert name in AJ.POSE_INDEX, '%r is not a MediaPipe landmark' % name


def test_every_mapped_bone_is_in_the_rig(meta):
    bones = set(meta['bone_names'])
    assert len(bones) == 59
    for name, entry in meta['joint_map'].items():
        bone, at, _off = AJ.normalise_entry(entry)
        assert bone in bones, '%s -> %r is not a bone of this rig' % (name, bone)
        assert at in ('head', 'tail')


def test_creature_required_joints_are_all_present(meta):
    mapped = set(meta['mapped_joints'])
    missing = [n for n in AJ.CREATURE_REQUIRED if n not in mapped]
    assert not missing, 'creature map is missing %s' % missing


def test_both_motions_declared(meta):
    assert meta['motions'] == ['hop', 'idle']
    assert meta['motion_default'] == 'hop'
    assert meta['frames'] == 48
    assert meta['fps'] == 24


def test_resolver_tables():
    assert len(AJ.POSE_NAMES) == 33
    assert len(set(AJ.POSE_NAMES)) == 33
    # the human table task 9 shares with this module fills every landmark
    assert AJ.mapped_names(AJ.CMU_MB_JOINT_MAP) == AJ.POSE_NAMES
