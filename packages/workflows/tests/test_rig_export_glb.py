# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The actor GLBs Movement Studio plays are skinned, animated and the right size.

Structural proof only — it re-parses the written .glb with the stdlib (no bpy,
no pytest plugin), so a green run means the FILE is good, not that the exporter
believed it was. Regenerate with:

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        --python blender_scripts/rig_export_glb.py -- --actor abel_capture
"""

import json
import os
import struct

import pytest

from tests import _tree

ACTORS = _tree.data('architecture', 'actors')

ACTORS_UNDER_TEST = ['abel_capture', 'abel']
CMU_MB_JOINTS = 31
MAX_BYTES = 30 * 1024 * 1024


def paths(name):
    d = os.path.join(ACTORS, name)
    return (os.path.join(d, '%s.glb' % name), os.path.join(d, '%s.glb.json' % name), os.path.join(d, '%s.json' % name))


@pytest.fixture(scope='module', params=ACTORS_UNDER_TEST)
def actor(request):
    glb, side, meta = paths(request.param)
    for p in (glb, side, meta):
        if not os.path.isfile(p):
            pytest.fail('%s missing — run rig_export_glb.py --actor %s' % (p, request.param))
    with open(side) as fh:
        card = json.load(fh)
    with open(meta) as fh:
        actor_json = json.load(fh)
    return {'name': request.param, 'glb': glb, 'card': card, 'meta': actor_json}


def test_glb_is_a_glb(actor):
    with open(actor['glb'], 'rb') as fh:
        head = fh.read(20)
    assert head[:4] == b'glTF'
    jl = struct.unpack('<I', head[12:16])[0]
    assert 0 < jl < os.path.getsize(actor['glb'])


def test_sidecar_parses_and_names_the_actor(actor):
    assert actor['card']['name'] == actor['name']
    assert actor['card']['bytes'] == os.path.getsize(actor['glb'])


def test_one_skin_with_the_cmu_mb_skeleton(actor):
    assert actor['card']['skins'] == 1
    assert actor['card']['joints'] == CMU_MB_JOINTS


def test_animation_is_the_playable_range(actor):
    anims = actor['card']['animations']
    assert len(anims) >= 1
    expected = actor['card']['expected_duration_s']
    longest = max(a['duration_s'] for a in anims)
    assert abs(longest - expected) <= 0.02 * expected, (longest, expected)


def test_first_frame_skips_the_rest_pose(actor):
    rest = actor['meta'].get('rest_frame')
    assert actor['card']['first_frame'] == (int(rest) + 1 if rest else 1)


def test_height_matches_the_actor_card(actor):
    h = float(actor['meta']['height_m'])
    assert abs(actor['card']['height_y'] - h) <= 0.03 * h, (actor['card']['height_y'], h)


def test_small_enough_for_the_browser(actor):
    assert actor['card']['bytes'] < MAX_BYTES
