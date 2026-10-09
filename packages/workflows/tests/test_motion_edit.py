# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""motion_edit: trim / speed / mirror / loop on the cmu_mb clips, and the
``edit`` bucket of the motion library.

The mirror test is the load-bearing one: it re-runs forward kinematics on the
mirrored clip and demands the world joint positions equal the source's with x
negated and the left/right names swapped.  Everything else (channel swaps, the
sign of each Euler channel, the mirrored rest skeleton) is machinery serving
that identity, so proving the identity proves the machinery.

Every test that *writes* works against a throwaway copy of the library
(``ML.ROOT`` / ``ML.LIBRARY_JSON`` monkeypatched at ``tmp_path``), so the real
``library.json`` only ever holds the one demonstration clip, ``edit/walk_mirror``.
"""

import json
import os

import numpy as np
import pytest

pytest.importorskip('scipy', reason='motion_capture needs scipy.spatial.transform')

from zyg_workflows import motion_capture as MC  # noqa: E402
from zyg_workflows import motion_edit as ME  # noqa: E402
from zyg_workflows import motion_library as ML  # noqa: E402

if not os.path.isdir(ML.ROOT):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

SOURCE = 'cmu/02_01'
CAPTURE = 'capture/qa_sword'
DEMO = 'edit/walk_mirror'

REAL_ROOT = ML.ROOT
REAL_LIBRARY_JSON = ML.LIBRARY_JSON

FLIP = np.array([-1.0, 1.0, 1.0])


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A writable library that shares the real BVH files by symlink.

    The ``edit`` bucket starts empty, so these tests see the library as it was
    before anything was derived — the demonstration clip the real one ships is
    checked separately, at the bottom of this file.
    """
    root = tmp_path / 'motion_library'
    root.mkdir()
    with open(REAL_LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        library = json.load(fh)
    library.pop('edit', None)
    (root / 'library.json').write_text(json.dumps(library, indent=2) + '\n')
    for bucket in ('cmu', 'capture'):
        os.symlink(os.path.join(REAL_ROOT, bucket), root / bucket)
    monkeypatch.setattr(ML, 'ROOT', str(root))
    monkeypatch.setattr(ML, 'LIBRARY_JSON', str(root / 'library.json'))
    return root


def source_clip():
    return ME.load_clip(os.path.join(REAL_ROOT, 'cmu', '02_01.bvh'))


def mirror_permutation(clip):
    index_of = {name: i for i, name in enumerate(clip['joints'])}
    return [index_of[ME.mirror_name(name)] for name in clip['joints']]


def wrapped(degrees):
    """Euler differences into (-180, 180]: 359 and 1 are two degrees apart."""
    return (np.asarray(degrees) + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------- mirror


def test_mirror_name_pairs_every_side_of_the_cmu_mb_rig():
    swapped = [ME.mirror_name(name) for name in ML.CMU_MB_JOINTS]
    assert sorted(swapped) == sorted(ML.CMU_MB_JOINTS)
    assert [ME.mirror_name(name) for name in swapped] == ML.CMU_MB_JOINTS
    assert ME.mirror_name('LeftUpLeg') == 'RightUpLeg'
    assert ME.mirror_name('LHipJoint') == 'RHipJoint'
    assert ME.mirror_name('LThumb') == 'RThumb'
    assert ME.mirror_name('LeftHandIndex1') == 'RightHandIndex1'
    # Central joints keep their name — LowerBack must not read as "Left*".
    for name in ('Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'Head'):
        assert ME.mirror_name(name) == name


def test_mirror_reflects_world_positions_through_x_zero():
    clip = source_clip()
    mirrored = ME.mirror(clip)
    assert mirrored['joints'] == clip['joints']
    assert mirrored['rows'].shape == clip['rows'].shape

    positions, _ = MC.forward_kinematics(ME.as_bvh(clip))
    mirror_positions, _ = MC.forward_kinematics(ME.as_bvh(mirrored))

    partner = mirror_permutation(clip)
    frames = np.linspace(0, positions.shape[0] - 1, 10).astype(int)
    error = np.abs(mirror_positions[frames] - positions[frames][:, partner] * FLIP).max()
    assert error <= 1e-3, error

    # The rest skeleton is mirrored too — cmu_mb is not exactly symmetric
    # (LeftUpLeg x = +1.65674, RightUpLeg x = -1.61070), so channel swapping
    # alone would leave a residual.  Without this the FK test above fails.
    assert mirrored['offsets'] == pytest.approx(clip['offsets'][partner] * FLIP)
    assert mirrored['ends']['LeftToeBase'] == pytest.approx(np.array(clip['ends']['RightToeBase']) * FLIP)


def test_mirror_is_an_involution():
    clip = source_clip()
    assert ME.mirror(ME.mirror(clip))['rows'] == pytest.approx(clip['rows'])


# ------------------------------------------------------------------------ trim


def test_trim_keeps_exactly_the_requested_range():
    clip = source_clip()
    trimmed = ME.trim(clip, 40, 120)
    assert trimmed['rows'].shape[0] == 120 - 40 + 1
    assert trimmed['rows'][0] == pytest.approx(clip['rows'][39])
    assert trimmed['rows'][-1] == pytest.approx(clip['rows'][119])
    with pytest.raises(ValueError):
        ME.trim(clip, 0, 10)
    with pytest.raises(ValueError):
        ME.trim(clip, 10, clip['rows'].shape[0] + 1)


def test_trim_re_prepends_a_captures_rest_frame():
    clip = ME.load_clip(os.path.join(REAL_ROOT, 'capture', 'qa_sword.bvh'))
    trimmed = ME.trim(clip, 50, 80, rest_frame=1)
    assert trimmed['rows'].shape[0] == 80 - 50 + 1 + 1
    assert trimmed['rows'][0] == pytest.approx(clip['rows'][0])
    assert trimmed['rows'][1] == pytest.approx(clip['rows'][49])
    # Inside the range it is already there and must not be duplicated.
    assert ME.trim(clip, 1, 30, rest_frame=1)['rows'].shape[0] == 30


def test_trim_registers_rest_frame_one(sandbox):
    record = ME.edit(CAPTURE, [{'op': 'trim', 'first': 50, 'last': 80}], 'edit/sword_trim', label='sword (trimmed)')
    assert record['frames'] == 32
    assert record['rest_frame'] == 1


# ----------------------------------------------------------------------- speed


def test_speed_two_halves_the_frame_count():
    clip = source_clip()
    total = clip['rows'].shape[0]
    fast = ME.speed(clip, 2.0)
    assert abs(fast['rows'].shape[0] - total / 2.0) <= 1
    assert fast['frame_time'] == clip['frame_time']
    assert fast['rows'][0] == pytest.approx(clip['rows'][0])
    assert fast['rows'][5] == pytest.approx(clip['rows'][10])

    slow = ME.speed(clip, 0.5)
    assert abs(slow['rows'].shape[0] - total * 2.0) <= 2
    # A half-step is the midpoint of its neighbours.
    assert slow['rows'][1] == pytest.approx((clip['rows'][0] + clip['rows'][1]) / 2.0)

    assert ME.speed(clip, 1.0)['rows'] == pytest.approx(clip['rows'])
    with pytest.raises(ValueError):
        ME.speed(clip, 0.0)


# ------------------------------------------------------------------------ loop


def test_loop_closes_the_cycle_without_a_cut():
    clip = source_clip()
    total = clip['rows'].shape[0]
    blend = 24
    looped = ME.loop(clip, blend)
    assert looped['rows'].shape[0] == total - blend

    rotations = ME.rotation_columns(clip)
    seam = np.abs(wrapped(looped['rows'][-1, rotations] - looped['rows'][0, rotations])).max()
    steps = np.abs(wrapped(np.diff(looped['rows'][:, rotations], axis=0)))
    typical = np.median(steps.max(axis=1))
    # The wrap must be an ordinary frame step, not a cut: the first output
    # frame is the source frame right after the last one.
    assert seam <= 2.0 * typical, (seam, typical)
    assert seam < 4.0, seam

    # Root translation is offset-corrected, so the crossfade introduces no
    # positional jump: the looped clip's worst root step is the source's.
    root = [ME.column_of(clip, 0, name) for name in ('Xposition', 'Yposition', 'Zposition')]
    source_step = np.abs(np.diff(clip['rows'][:, root], axis=0)).max()
    looped_step = np.abs(np.diff(looped['rows'][:, root], axis=0)).max()
    assert looped_step <= source_step + 1e-6, (looped_step, source_step)

    with pytest.raises(ValueError):
        ME.loop(clip, 1)
    with pytest.raises(ValueError):
        ME.loop(clip, total)


# ------------------------------------------------------------- save / register


def test_registered_edit_clip_round_trips_through_the_library(sandbox):
    record = ME.edit(
        SOURCE,
        [
            {'op': 'trim', 'first': 20, 'last': 180},
            {'op': 'speed', 'factor': 2.0},
            {'op': 'mirror'},
            {'op': 'loop', 'frames': 16},
        ],
        'edit/walk_fast_loop',
        label='walk, fast, mirrored, looping',
    )

    assert record['id'] == 'edit/walk_fast_loop'
    assert record['source_clip'] == SOURCE
    assert [spec['op'] for spec in record['ops']] == ['trim', 'speed', 'mirror', 'loop']
    assert 'rest_frame' not in record  # a loop blends frame 1 away

    assert ML.edit_clips() == [record]
    assert ML.clip('edit/walk_fast_loop') == record
    assert ML.clips()[-1] == record

    path = ML.clip_path('edit/walk_fast_loop')
    assert os.path.isfile(path)
    assert path == os.path.join(str(sandbox), 'edit', 'walk_fast_loop.bvh')

    header = ML.parse_bvh_header(path)
    assert header['joints'] == ML.CMU_MB_JOINTS
    assert header['channels']['Hips'] == ME.ROOT_CHANNELS
    assert header['channels']['LeftArm'] == ME.JOINT_CHANNELS
    assert header['frames'] == record['frames']
    assert header['frame_time'] == record['frame_time']
    assert record['fps'] == round(1.0 / header['frame_time'])
    assert record['root'] == 'Hips'
    assert record['joints'] == 31
    assert record['height_units'] == pytest.approx(ML.root_height(header))

    # trim 20..180 = 161 frames, 2x speed = 81, loop 16 = 65.
    assert record['frames'] == 65


def test_edit_inherits_the_parents_licence_and_flags(sandbox):
    from_cmu = ME.edit(SOURCE, [{'op': 'mirror'}], 'edit/a', label='a')
    from_capture = ME.edit(CAPTURE, [{'op': 'mirror'}], 'edit/b', label='b')

    library = json.loads((sandbox / 'library.json').read_text())
    assert from_cmu['licence'] == library['licence']
    assert from_cmu['publishable'] is True and from_cmu['may_train'] is True

    parent = ML.clip(CAPTURE)
    assert from_capture['licence'] == parent['licence']
    assert from_capture['publishable'] is False
    assert from_capture['may_train'] is False
    assert from_capture['rest_frame'] == 1

    assert [rec['id'] for rec in ML.edit_clips()] == ['edit/a', 'edit/b']
    # Re-saving the same slug replaces its record instead of duplicating it.
    ME.edit(SOURCE, [{'op': 'speed', 'factor': 2.0}], 'edit/a', label='a2')
    ids = [rec['id'] for rec in ML.edit_clips()]
    assert ids == ['edit/b', 'edit/a']
    assert ML.clip('edit/a')['label'] == 'a2'


def test_edit_refuses_unknown_and_file_less_sources(sandbox):
    with pytest.raises(ValueError):
        ME.edit('cmu/nope', [{'op': 'mirror'}], 'edit/x')
    with pytest.raises(ValueError):
        ME.edit('auth/fly', [{'op': 'mirror'}], 'edit/x')
    with pytest.raises(ValueError):
        ME.apply_ops(source_clip(), [{'op': 'reverse'}])


def test_cli_writes_and_registers(sandbox, capsys):
    assert (
        ME.main(
            [SOURCE, '--mirror', '--save', 'edit/cli_mirror', '--label', 'walk (mirrored)', '--tags', 'walk', 'mirror']
        )
        == 0
    )
    record = json.loads(capsys.readouterr().out)
    assert record['id'] == 'edit/cli_mirror'
    assert record['tags'] == ['walk', 'mirror']
    assert record['ops'] == [{'op': 'mirror'}]
    assert os.path.isfile(ML.clip_path('edit/cli_mirror'))
    with pytest.raises(SystemExit):
        ME.main([SOURCE, '--save', 'edit/nothing'])


# --------------------------------------------------- the one clip we ship live


def test_demonstration_clip_is_in_the_real_library():
    record = ML.clip(DEMO)
    assert record is not None, 'edit/walk_mirror is missing from library.json'
    assert record['source_clip'] == SOURCE
    assert record['ops'] == [{'op': 'mirror'}]
    assert record['label'] == 'walk (mirrored)'
    assert record['publishable'] is True and record['may_train'] is True

    path = ML.clip_path(DEMO)
    assert os.path.isfile(path)
    header = ML.parse_bvh_header(path)
    assert header['joints'] == ML.CMU_MB_JOINTS
    assert header['frames'] == record['frames'] == ML.clip(SOURCE)['frames']

    positions, _ = MC.forward_kinematics(ME.as_bvh(ME.load_clip(path)))
    origin, _ = MC.forward_kinematics(ME.as_bvh(ME.load_clip(ML.clip_path(SOURCE))))
    partner = mirror_permutation(ME.load_clip(path))
    frames = np.linspace(0, positions.shape[0] - 1, 10).astype(int)
    assert np.abs(positions[frames] - origin[frames][:, partner] * FLIP).max() <= 1e-3
