# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The three proxy actors built by blender_scripts/proxy_actor.py.

Pure stdlib: the .blend files are only checked for existence and size, the facts
about them live in the sidecar <name>.json the build script writes.
"""

import json
import os

import pytest

from tests import _tree

ACTORS = _tree.data('architecture', 'actors')
SCRIPT = _tree.pkg('blender_scripts', 'proxy_actor', '__main__.py')  # a package since 2026-10

ACTOR_NAMES = ('abel', 'cornelis', 'generic_woman')
EXPECTED = {
    'abel': {'height_m': 1.52, 'motion': 'cmu/02_01'},
    'cornelis': {'height_m': 1.80, 'motion': 'cmu/07_01'},
    'generic_woman': {'height_m': 1.62, 'motion': 'cmu/02_01'},
}
MAX_BLEND_BYTES = 40 * 1000 * 1000


def meta(name):
    with open(os.path.join(ACTORS, name, name + '.json'), 'r', encoding='utf-8') as fh:
        return json.load(fh)


def test_build_script_exists():
    assert os.path.isfile(SCRIPT)


@pytest.mark.parametrize('name', ACTOR_NAMES)
def test_blend_exists_and_is_small(name):
    path = os.path.join(ACTORS, name, name + '.blend')
    assert os.path.isfile(path), path
    size = os.path.getsize(path)
    assert size > 100_000, (path, size)
    assert size < MAX_BLEND_BYTES, (path, size)


@pytest.mark.parametrize('name', ACTOR_NAMES)
def test_json_describes_the_actor(name):
    data = meta(name)
    assert data['name'] == name
    assert data['mapping'] == 'cmu_mb'
    assert data['motion'] == EXPECTED[name]['motion']
    assert abs(data['height_m'] - EXPECTED[name]['height_m']) < 0.01
    assert data['frames'] > 100
    assert data['fps'] > 0
    assert len(data['bones']) == 31
    assert data['bones'][0] == 'Hips'
    assert data['unmapped_bones'] == []


@pytest.mark.parametrize('name', ACTOR_NAMES)
def test_strip_png(name):
    path = os.path.join(ACTORS, name, name + '_strip.png')
    assert os.path.isfile(path), path
    assert os.path.getsize(path) > 20_000, os.path.getsize(path)
    with open(path, 'rb') as fh:
        assert fh.read(8) == b'\x89PNG\r\n\x1a\n'


@pytest.mark.parametrize('name', ACTOR_NAMES)
def test_checks_passed(name):
    checks = meta(name)['checks']
    assert checks['leftfoot_travel_frame1_to_mid_m'] > 0.2
    assert checks['leftfoot_travel_ok']
    assert checks['mesh_min_z_max_abs_dev_m'] <= 0.08
    assert checks['feet_on_ground_ok']
    # The mesh-follows-the-rig measure moved from the bbox centre to the
    # centroid of the root-chain vertices (2026-09-23). These three sidecars
    # predate the rename, so read whichever key they carry.
    bbox = checks.get('mesh_bbox_centre_to_hips_max_m', checks.get('mesh_centre_to_hips_max_m'))
    assert bbox is not None and bbox <= 0.3, checks
    torso = checks.get('mesh_torso_centroid_to_hips_max_m')
    assert torso is None or torso <= 0.25, checks
    assert checks['mesh_tracks_rig_ok']
