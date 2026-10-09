# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The authored actions: registered in the library, built onto real actors.

No Blender here — the .blend files and their <name>.json receipts are built by
``blender_scripts/proxy_actor.py --motion auth/<id>`` and this pins what they
must contain.  ``motion_authored`` itself imports without bpy (metadata only),
so the spec it declares can be checked against what actually landed on disk.
"""

import json
import os

import pytest

from zyg_workflows import motion_library as ML
from zyg_workflows import paths
from zyg_workflows.blender_scripts import motion_authored as MA

ACTORS = str(paths.ZYG_DATA_ROOT / 'architecture' / 'actors')

if not os.path.isdir(ML.ROOT):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

AUTHORED_IDS = ['auth/fly', 'auth/drive', 'auth/scream']

# actor name -> (motion id, frames)
BUILT = {
    'abel_fly': ('auth/fly', 96),
    'cornelis_drive': ('auth/drive', 48),
    'abel_scream': ('auth/scream', 72),
}


@pytest.fixture(scope='module')
def library():
    with open(ML.LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def receipt(name):
    with open(os.path.join(ACTORS, name, name + '.json'), 'r', encoding='utf-8') as fh:
        return json.load(fh)


# ------------------------------------------------------------------ library


def test_library_lists_the_three_authored_ids(library):
    assert [rec['id'] for rec in library['authored']] == AUTHORED_IDS
    for rec in library['authored']:
        assert rec['licence'] == 'in-house'
        assert rec['source'] == 'motion_authored.py'
        assert rec['fps'] == 24
        assert rec['frames'] > 0
        assert rec['label'] and rec['tags'] and rec['index_text']
        assert 'file' not in rec  # authored motions are code, not data


def test_clips_lists_both_sources(library):
    # clips() is the union of every bucket; the capture and edit buckets came
    # later, so pin the sum rather than a number that ages.
    assert len(ML.clips()) == (
        len(ML.bvh_clips()) + len(ML.authored_clips()) + len(ML.capture_clips()) + len(ML.edit_clips())
    )
    assert len(ML.bvh_clips()) == 15
    assert len(ML.authored_clips()) == 3
    assert set(AUTHORED_IDS) <= {clip['id'] for clip in ML.clips()}
    for clip_id in AUTHORED_IDS:
        assert ML.clip(clip_id)['id'] == clip_id
        assert ML.clip_path(clip_id) is None  # nothing to load off disk
    assert ML.clip('auth/nope') is None


def test_module_spec_matches_the_library(library):
    assert list(MA.MOTION_IDS) == AUTHORED_IDS
    assert MA.library_records() == library['authored']
    for clip_id in AUTHORED_IDS:
        assert MA.is_authored(clip_id)
    assert not MA.is_authored('cmu/02_01')


def test_root_offset_rules():
    # flight height is 1.2 x the actor's standing height; a driver sits at the
    # seat height; a screaming actor stands on the path like any mocap clip.
    assert MA.root_offset_z('auth/fly', 1.52) == pytest.approx(1.824)
    assert MA.root_offset_z('auth/drive', 1.80) == pytest.approx(0.45)
    assert MA.root_offset_z('auth/scream', 1.80) == pytest.approx(0.0)


# ------------------------------------------------------------------- actors


@pytest.mark.parametrize('name', sorted(BUILT))
def test_actor_files_exist(name):
    for suffix in ('.blend', '.json', '_strip.png'):
        path = os.path.join(ACTORS, name, name + suffix)
        assert os.path.isfile(path), path
        assert os.path.getsize(path) > 1024, path


@pytest.mark.parametrize('name', sorted(BUILT))
def test_actor_receipt(name):
    motion_id, frames = BUILT[name]
    rec = receipt(name)
    assert rec['name'] == name
    assert rec['motion'] == motion_id
    assert rec['motion_source'] == 'authored'
    assert rec['frames'] == frames
    assert rec['fps'] == 24
    assert rec['mapping'] == 'cmu_mb'
    assert rec['licence'] == 'in-house'
    assert rec['bvh_global_scale'] is None  # nothing was retargeted
    assert rec['rest_aligned_deg'] == {}  # the MPFB rest pose is untouched
    assert len(rec['bones']) == 31
    assert rec['root_offset_z'] == pytest.approx(MA.root_offset_z(motion_id, rec['height_m']), abs=1e-3)


def test_fly_numbers():
    got = receipt('abel_fly')['checks']['authored']
    assert got['hips_pitch_deg_frame48'] == pytest.approx(MA.FLY_PITCH_DEG, abs=1.0)
    assert got['hips_pitch_ok'] is True
    assert got['root_offset_z_set'] is True
    assert got['root_offset_z_prop'] == pytest.approx(1.824, abs=1e-3)
    # 2.0 m/s for 95 frames at 24 fps
    assert got['root_travel_m'] == pytest.approx(7.917, abs=0.3)
    assert got['root_travel_ok'] is True


def test_drive_numbers():
    rec = receipt('cornelis_drive')
    got = rec['checks']['authored']
    assert got['leftupleg_angle_deg'] == pytest.approx(MA.DRIVE_THIGH_DEG, abs=1.0)
    assert got['rightupleg_angle_deg'] == pytest.approx(MA.DRIVE_THIGH_DEG, abs=1.0)
    assert got['upleg_angle_ok'] is True
    # a thigh's rest direction points DOWN, so swinging it forward is negative about X
    assert got['leftupleg_pitch_deg'] == pytest.approx(-MA.DRIVE_THIGH_DEG, abs=1.0)
    assert rec['vehicle_kind'] == 'car'
    assert rec['seat_offset'] == MA.DRIVE_SEAT_OFFSET
    assert rec['root_offset_z'] == pytest.approx(MA.DRIVE_SEAT_Z_M)


def test_scream_numbers():
    got = receipt('abel_scream')['checks']['authored']
    assert got['head_pitch_deg_frame1'] == pytest.approx(0.0, abs=0.5)
    assert got['head_pitch_deg_frame12'] == pytest.approx(MA.SCREAM_HEAD_DEG, abs=1.0)
    assert got['head_pitch_ok'] is True
    # +-1.5 deg of tremor on Spine1 across frames 13..48
    assert got['spine1_tremor_span_deg'] == pytest.approx(2 * MA.SCREAM_TREMOR_DEG, abs=0.2)
    assert got['fist_finger_vs_hand_deg'] == pytest.approx(MA.SCREAM_FIST_DEG, abs=1.0)


def test_actors_face_forward_in_armature_space():
    for name in BUILT:
        got = receipt(name)['checks']['authored']
        assert got['facing_armature_space'] == [0.0, -1.0, 0.0], name
        assert got['left_axis'] == [1.0, 0.0, 0.0], name
