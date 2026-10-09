# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for scene_shot.py — the shot record contract of the scene bridge."""

import copy
import json
import math
import os

import pytest

from tests import _tree
from zyg_workflows import scene_shot as S

FIXTURE = _tree.require(os.path.join(S.SHOTS_DIR, 'fixture_house', 'shot.json'))


@pytest.fixture()
def shot():
    with open(FIXTURE, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def test_fixture_is_valid(shot):
    warnings = []
    assert S.validate(shot, warnings) == []
    assert warnings == []
    assert shot['schema'] == S.SCHEMA
    assert shot['id'] == 'fixture_house'


def test_load_returns_the_fixture():
    loaded = S.load(FIXTURE)
    assert loaded['id'] == 'fixture_house'
    assert S.shot_dir(loaded) == os.path.join(S.SHOTS_DIR, 'fixture_house')
    assert S.shot_dir('fixture_house') == os.path.join(S.SHOTS_DIR, 'fixture_house')


def test_missing_drawing_is_an_error(shot):
    bad = copy.deepcopy(shot)
    bad['drawing'] = '/nonexistent/drawing.json'
    errs = S.validate(bad)
    assert any('drawing does not exist' in e for e in errs), errs


def test_bad_id_and_bad_resolution_are_errors(shot):
    bad = copy.deepcopy(shot)
    bad['id'] = 'Not A Slug'
    bad['resolution'] = [833, 480]
    errs = S.validate(bad)
    assert any('id' in e for e in errs), errs
    assert any('multiple of 16' in e for e in errs), errs


def test_unknown_vdb_pack_is_an_error(shot):
    bad = copy.deepcopy(shot)
    bad['effects'][0]['pack'] = 'NoSuchPackVDB.zip'
    errs = S.validate(bad)
    assert any('not found in' in e for e in errs), errs


def test_rel_to_unknown_anchor_is_an_error(shot):
    bad = copy.deepcopy(shot)
    bad['effects'][0]['rel']['to'] = 'nobody'
    errs = S.validate(bad)
    assert any('rel.to' in e for e in errs), errs


def test_non_4n_plus_1_frames_is_a_warning_not_an_error(shot):
    odd = copy.deepcopy(shot)
    odd['frames'] = 50
    warnings = []
    assert S.validate(odd, warnings) == []
    assert len(warnings) == 1
    assert '4n+1' in warnings[0]

    # and 49 = 4*12 + 1 warns about nothing
    warnings = []
    assert S.validate(shot, warnings) == []
    assert warnings == []


def test_camera_at_interpolates_halfway(shot):
    two = copy.deepcopy(shot)
    two['camera']['keys'] = [
        {'f': 1, 'p': [0.0, 0.0, 0.0], 't': [0.0, 0.0, -10.0], 'fov': 40.0},
        {'f': 11, 'p': [10.0, 2.0, -4.0], 't': [4.0, 1.0, -20.0], 'fov': 60.0},
    ]
    mid = S.camera_at(two, 6)
    assert mid['p'] == pytest.approx([5.0, 1.0, -2.0])
    assert mid['t'] == pytest.approx([2.0, 0.5, -15.0])
    assert mid['fov'] == pytest.approx(50.0)

    # held outside the key range
    assert S.camera_at(two, 0)['p'] == pytest.approx([0.0, 0.0, 0.0])
    assert S.camera_at(two, 99)['p'] == pytest.approx([10.0, 2.0, -4.0])


def test_actor_at_interpolates_and_holds(shot):
    mid = S.actor_at(shot, 'abel', 25)
    assert mid['p'] == pytest.approx([6.0, 0.0, 8.0])
    assert mid['ry'] == pytest.approx(180.0)
    assert S.actor_at(shot, 'abel', 1)['p'] == pytest.approx([6.0, 0.0, 10.0])
    assert S.actor_at(shot, 'abel', 500)['p'] == pytest.approx([6.0, 0.0, 6.0])


def test_heading_forward_conventions():
    assert S.heading_forward(0) == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)
    assert S.heading_forward(180) == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)


def test_resolve_positions_matches_the_hand_computation(shot):
    # Hand computation for fire1, done here in longhand rather than by calling
    # the module's own helpers.
    #
    #   anchor  = abel at his start_frame (f = 1) = (6, 0, 10), ry = 180
    #   forward = Ry(180) * (0, 0, -1) = (0, 0, +1)     (he faces the camera)
    #   back    = -forward             = (0, 0, -1)
    #   up      = (0, 1, 0)
    #   right   = up x back = (1*-1 - 0*0, 0*0 - 0*-1, 0*0 - 1*0) = (-1, 0, 0)
    #   p = anchor + dx*right + dy*up + dz*back
    #     = (6,0,10) + 1.0*(-1,0,0) + 0.0*(0,1,0) + 2.0*(0,0,-1)
    #     = (5, 0, 8)
    #
    # i.e. one metre to Abel's own right and two metres behind him, which — as
    # he is facing the camera — is two metres deeper into the shot.
    expected = (6.0 + 1.0 * -1.0, 0.0 + 0.0 * 1.0, 10.0 + 2.0 * -1.0)
    assert expected == (5.0, 0.0, 8.0)

    out = S.resolve_positions(shot)
    fx = out['effects'][0]
    assert fx['id'] == 'fire1'
    assert 'rel' not in fx
    for got, want in zip(fx['p'], expected):
        assert abs(got - want) < 1e-6, (fx['p'], expected)

    # the input is untouched
    assert 'rel' in shot['effects'][0]
    assert 'p' not in shot['effects'][0]

    # and the resolved shot is still valid
    assert S.validate(out) == []


def test_resolve_positions_camera_anchor_goes_deeper_into_the_shot(shot):
    cam = copy.deepcopy(shot)
    cam['camera']['keys'] = [{'f': 1, 'p': [0.0, 2.0, 10.0], 't': [0.0, 2.0, 0.0], 'fov': 50.0}]
    cam['effects'] = [
        {
            'id': 'fire1',
            'pack': 'SmallCampfireVDB.zip',
            'size_m': 1.5,
            'start_frame': 1,
            'loop': True,
            'rel': {'to': 'camera', 'dx': 1.0, 'dy': 0.5, 'dz': 2.0},
        }
    ]
    # camera at (0,2,10) looking towards -Z: forward = (0,0,-1),
    # right = forward x up = (1,0,0), up = (0,1,0).
    # dz = 2 is two metres deeper into the shot -> z = 10 - 2 = 8.
    out = S.resolve_positions(cam)
    assert out['effects'][0]['p'] == pytest.approx([1.0, 2.5, 8.0], abs=1e-9)


def test_to_blender_round_trip():
    for v in [(1.0, 2.0, 3.0), (-4.5, 0.0, 7.25), (0.0, 0.0, 0.0), (6.0, 0.0, 10.0), (14.0, 1.7, 18.0)]:
        b = S.to_blender(v)
        back = S.from_blender(b)
        assert back == pytest.approx(v, abs=1e-12)
    # the documented swap itself
    assert S.to_blender((1.0, 2.0, 3.0)) == pytest.approx((1.0, -3.0, 2.0))
    assert S.from_blender((1.0, -3.0, 2.0)) == pytest.approx((1.0, 2.0, 3.0))


def test_new_shot_is_valid_and_saves_atomically(tmp_path):
    drawing = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data',
        'architecture',
        'projects',
        'first-building-attempt.json',
    )
    s = S.new_shot('tmp-shot', drawing)
    assert S.validate(s) == []
    out = tmp_path / 'shot.json'
    S.save(s, str(out))
    assert json.loads(out.read_text())['id'] == 'tmp-shot'
    assert not [p for p in os.listdir(str(tmp_path)) if p.startswith('.shot-')]


def test_fixture_camera_frames_the_building(shot):
    """The chosen camera keeps the building's plan centre inside the frame."""
    cam = S.camera_at(shot, 1)
    right, up, forward = S.camera_basis(cam)
    with open(shot['drawing'], 'r', encoding='utf-8') as fh:
        objs = [o for o in json.load(fh)['objects'] if not o.get('hidden')]
    cx = (min(o['x'] for o in objs) + max(o['x'] for o in objs)) / 2.0
    cz = (min(o['z'] for o in objs) + max(o['z'] for o in objs)) / 2.0
    v = S._norm(S._sub((cx, 1.5, cz), tuple(cam['p'])))
    ang = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(v, forward))))))
    w, h = shot['resolution']
    half_h = math.degrees(math.atan(math.tan(math.radians(cam['fov'] / 2.0)) * w / h))
    assert ang < half_h, (ang, half_h)
