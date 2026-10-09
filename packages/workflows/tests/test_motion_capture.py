# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The capture source: SOMA BVH -> cmu_mb BVH, and the library record it gets.

The QA clip (data/assets/motion_library/capture/_raw/qa_sword/) was produced by
NVIDIA GEM-X and retargeted by motion_capture.soma_bvh_to_cmu_mb.  These tests
pin the shape of the converted file, its library entry, and — on a synthetic
three-frame source built here — that the retarget carries a known joint rotation
through unchanged.
"""

import json
import math
import os

import numpy as np
import pytest

pytest.importorskip('scipy', reason='motion_capture needs scipy.spatial.transform')

from zyg_workflows import motion_capture as MC  # noqa: E402
from zyg_workflows import motion_library as ML  # noqa: E402

if not os.path.isdir(ML.ROOT):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

CLIP_ID = 'capture/qa_sword'
SOMA_BVH = os.path.join(ML.ROOT, 'capture', '_raw', 'qa_sword', 'qa_sword_soma.bvh')


@pytest.fixture(scope='module')
def record():
    rec = ML.clip(CLIP_ID)
    assert rec is not None, '%s is not registered in library.json' % CLIP_ID
    return rec


@pytest.fixture(scope='module')
def header(record):
    return ML.parse_bvh_header(ML.clip_path(CLIP_ID))


# ------------------------------------------------------- the converted clip


def test_clip_file_parses_as_cmu_mb(record, header):
    path = ML.clip_path(CLIP_ID)
    assert os.path.isfile(path), path

    assert header['joints'] == ML.CMU_MB_JOINTS
    assert len(header['joints']) == 31
    assert header['joints'][0] == 'Hips'
    assert header['channels']['Hips'] == [
        'Xposition',
        'Yposition',
        'Zposition',
        'Zrotation',
        'Yrotation',
        'Xrotation',
    ]
    for name in ML.CMU_MB_JOINTS[1:]:
        assert header['channels'][name] == ['Zrotation', 'Yrotation', 'Xrotation'], name

    assert header['frames'] == record['frames']
    assert header['frame_time'] == record['frame_time']
    assert record['fps'] == round(1.0 / header['frame_time'])
    assert record['root'] == 'Hips'
    assert record['joints'] == 31
    assert record['height_units'] == pytest.approx(ML.root_height(header))
    assert record['height_units'] > 0
    assert record['label'] and record['tags']


def test_frames_are_the_soma_frames_plus_the_rest_frame(record):
    assert os.path.isfile(SOMA_BVH), SOMA_BVH
    soma = MC.parse_bvh(SOMA_BVH)
    assert record['frames'] == soma['frames'] + 1
    assert record['rest_frame'] == 1
    assert record['fps'] == round(1.0 / soma['frame_time'])


def test_rest_frame_has_no_rotation_and_a_standing_hips(record):
    out = MC.parse_bvh(ML.clip_path(CLIP_ID))
    motion = out['motion']
    assert motion.shape[0] == record['frames']

    # Frame 1 is the reference pose: every rotation channel is zero, so the
    # skeleton stands exactly in its own rest pose (what proxy_actor's
    # align_rest() turns the MPFB bones to, and what retarget() measures from).
    assert np.abs(motion[0, 3:]).max() == 0.0

    hips_y = motion[:, 1]
    assert hips_y[0] == pytest.approx(record['height_units'])
    # The rest frame is the first video frame, where the actor stands; the clip
    # then crouches and lunges, so the rest hips sit above the clip's mean.
    # 20 percent is the band a mostly-upright clip keeps to; this one runs to
    # 28 percent, hence the wider bound here (see the task report).
    ratio = hips_y[0] / hips_y[1:].mean()
    assert 0.6 <= ratio <= 1.45, ratio


def test_library_and_licence_flags(record):
    ids = [c['id'] for c in ML.clips()]
    assert CLIP_ID in ids
    assert CLIP_ID in [c['id'] for c in ML.capture_clips()]
    assert CLIP_ID not in [c['id'] for c in ML.bvh_clips()]
    assert ML.clip_path(CLIP_ID).endswith('capture/qa_sword.bvh')
    assert os.path.isfile(ML.clip_path(CLIP_ID))

    assert record['publishable'] is False
    assert record['may_train'] is False
    assert record['engine'] == 'gem-x'
    assert record['source_clip']
    assert 'internal test only' in record['licence']


def test_provenance_carries_the_hash_of_the_converted_file():
    prov_path = os.path.join(ML.ROOT, 'capture', 'PROVENANCE.json')
    with open(prov_path, 'r', encoding='utf-8') as fh:
        prov = json.load(fh)
    entries = [c for c in prov['clips'] if c['file'] == 'capture/qa_sword.bvh']
    assert len(entries) == 1
    entry = entries[0]
    assert len(entry['sha256'] or '') == 64
    assert entry['bytes'] == os.path.getsize(ML.clip_path(CLIP_ID))
    assert 'pending' not in (entry.get('note') or '')
    assert entry['publishable'] is False and entry['may_train'] is False


def test_every_cmu_mb_joint_has_a_map_entry():
    assert list(MC.NAME_MAP) == ML.CMU_MB_JOINTS
    joints, parents = MC.cmu_mb_skeleton()
    assert joints == ML.CMU_MB_JOINTS
    assert parents[0] == -1
    # Only the two hip connectors have no SOMA source.
    assert [n for n in ML.CMU_MB_JOINTS if not MC.NAME_MAP[n]] == ['LHipJoint', 'RHipJoint']


# ------------------------------------------------- synthetic round-trip

# A small SOMA skeleton in the USD spelling GEM-X exports, laid out as a T-pose
# so the whole thing is readable: (name, offset from parent, children).
SOMA_TREE = (
    'Hips',
    (0.0, 0.0, 0.0),
    [
        (
            'Spine1',
            (0.0, 8.0, 0.0),
            [
                (
                    'Spine2',
                    (0.0, 9.0, 0.0),
                    [
                        (
                            'Chest',
                            (0.0, 9.0, 0.0),
                            [
                                (
                                    'Neck1',
                                    (0.0, 22.0, 0.0),
                                    [
                                        (
                                            'Neck2',
                                            (0.0, 4.0, 0.0),
                                            [('Head', (0.0, 6.0, 0.0), [('HeadEnd', (0.0, 14.0, 0.0), [])])],
                                        )
                                    ],
                                ),
                                (
                                    'LeftShoulder',
                                    (4.0, 4.0, 0.0),
                                    [
                                        (
                                            'LeftArm',
                                            (12.0, 0.0, 0.0),
                                            [
                                                (
                                                    'LeftForeArm',
                                                    (27.0, 0.0, 0.0),
                                                    [
                                                        (
                                                            'LeftHand',
                                                            (24.0, 0.0, 0.0),
                                                            [
                                                                (
                                                                    'LeftHandThumb1',
                                                                    (3.0, 0.0, 3.0),
                                                                    [('LeftHandThumb2', (3.0, 0.0, 2.0), [])],
                                                                ),
                                                                (
                                                                    'LeftHandIndex1',
                                                                    (6.0, 0.0, 1.5),
                                                                    [('LeftHandIndex2', (4.0, 0.0, 0.0), [])],
                                                                ),
                                                                ('LeftHandMiddle1', (6.5, 0.0, -0.5), []),
                                                            ],
                                                        )
                                                    ],
                                                )
                                            ],
                                        )
                                    ],
                                ),
                                (
                                    'RightShoulder',
                                    (-4.0, 4.0, 0.0),
                                    [
                                        (
                                            'RightArm',
                                            (-12.0, 0.0, 0.0),
                                            [
                                                (
                                                    'RightForeArm',
                                                    (-27.0, 0.0, 0.0),
                                                    [
                                                        (
                                                            'RightHand',
                                                            (-24.0, 0.0, 0.0),
                                                            [
                                                                (
                                                                    'RightHandThumb1',
                                                                    (-3.0, 0.0, 3.0),
                                                                    [('RightHandThumb2', (-3.0, 0.0, 2.0), [])],
                                                                ),
                                                                (
                                                                    'RightHandIndex1',
                                                                    (-6.0, 0.0, 1.5),
                                                                    [('RightHandIndex2', (-4.0, 0.0, 0.0), [])],
                                                                ),
                                                                ('RightHandMiddle1', (-6.5, 0.0, -0.5), []),
                                                            ],
                                                        )
                                                    ],
                                                )
                                            ],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                )
            ],
        ),
        (
            'LeftLeg',
            (8.0, -4.0, 0.0),
            [
                (
                    'LeftShin',
                    (0.0, -42.0, 0.0),
                    [
                        (
                            'LeftFoot',
                            (0.0, -41.0, 0.0),
                            [('LeftToeBase', (0.0, -5.0, 12.0), [('LeftToeEnd', (0.0, 0.0, 6.0), [])])],
                        )
                    ],
                )
            ],
        ),
        (
            'RightLeg',
            (-8.0, -4.0, 0.0),
            [
                (
                    'RightShin',
                    (0.0, -42.0, 0.0),
                    [
                        (
                            'RightFoot',
                            (0.0, -41.0, 0.0),
                            [('RightToeBase', (0.0, -5.0, 12.0), [('RightToeEnd', (0.0, 0.0, 6.0), [])])],
                        )
                    ],
                )
            ],
        ),
    ],
)

SOMA_CHANNELS = ('Xposition', 'Yposition', 'Zposition', 'Zrotation', 'Yrotation', 'Xrotation')


def _flatten_tree(node, parent, out):
    name, offset, kids = node
    index = len(out)
    out.append((name, parent, offset))
    for kid in kids:
        _flatten_tree(kid, index, out)
    return out


def _write_soma_bvh(path, hips_positions, rotations):
    """A SOMA-shaped BVH: six channels everywhere, positions repeating OFFSET."""
    flat = _flatten_tree(SOMA_TREE, -1, [])
    lines = ['HIERARCHY']

    def emit(node, depth):
        name, offset, kids = node
        pad = '\t' * depth
        lines.append('%s%s %s' % (pad, 'ROOT' if depth == 0 else 'JOINT', name))
        lines.append(pad + '{')
        lines.append('%s\tOFFSET %.6f %.6f %.6f' % ((pad,) + offset))
        lines.append(pad + '\tCHANNELS 6 ' + ' '.join(SOMA_CHANNELS))
        for kid in kids:
            emit(kid, depth + 1)
        if not kids:
            lines.append(pad + '\tEnd Site')
            lines.append(pad + '\t{')
            lines.append(pad + '\t\tOFFSET 0.000000 0.000000 5.000000')
            lines.append(pad + '\t}')
        lines.append(pad + '}')

    emit(SOMA_TREE, 0)
    lines.append('MOTION')
    lines.append('Frames: %d' % len(rotations))
    lines.append('Frame Time: 0.041667')
    for frame, per_joint in enumerate(rotations):
        row = []
        for index, (name, _parent, offset) in enumerate(flat):
            pos = hips_positions[frame] if index == 0 else offset
            rot = per_joint.get(name, (0.0, 0.0, 0.0))
            row.extend(list(pos) + list(rot))
        lines.append(' '.join('%.6f' % v for v in row))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    return [n for n, _p, _o in flat]


def _world_rotation(bvh, joint_name, frame):
    index = bvh['joints'].index(joint_name)
    _pos, rot = MC.forward_kinematics(bvh)
    return rot[frame, index]


def _angle_between(a, b):
    trace = np.clip((np.trace(a.T @ b) - 1.0) / 2.0, -1.0, 1.0)
    return math.degrees(math.acos(trace))


def test_synthetic_roundtrip_carries_a_known_rotation(tmp_path):
    src = str(tmp_path / 'synth_soma.bvh')
    dst = str(tmp_path / 'synth_cmu_mb.bvh')
    hips = [(0.0, 95.0, 0.0), (1.0, 95.0, 2.0), (2.0, 95.0, 4.0)]
    rotations = [
        {},  # frame 0: the reference pose
        {'LeftArm': (30.0, 0.0, 0.0)},  # frame 1: LeftArm Z += 30 deg
        {},  # frame 2: back to the reference
    ]
    names = _write_soma_bvh(src, hips, rotations)
    assert 'LeftArm' in names

    info = MC.soma_bvh_to_cmu_mb(src, dst)
    assert info['frames'] == 4  # 3 source frames + the rest frame
    assert info['source_frames'] == 3
    assert info['joints'] == 31
    assert info['unmapped'] == ['LHipJoint', 'RHipJoint']

    source = MC.parse_bvh(src)
    out = MC.parse_bvh(dst)
    assert out['joints'] == ML.CMU_MB_JOINTS

    want = _world_rotation(source, 'LeftArm', 1)
    got = _world_rotation(out, 'LeftArm', 2)  # source frame 1 -> output frame 3
    assert _angle_between(want, got) < 0.5, _angle_between(want, got)

    # and the rotation really is the 30 degrees we asked for, not a no-op
    rest = _world_rotation(source, 'LeftArm', 0)
    assert _angle_between(rest, want) == pytest.approx(30.0, abs=1e-6)

    # every other frame agrees too, and the reference frame is the identity
    for frame in (0, 2):
        assert (
            _angle_between(_world_rotation(source, 'LeftArm', frame), _world_rotation(out, 'LeftArm', frame + 1)) < 0.5
        )
    assert np.abs(out['motion'][0, 3:]).max() == 0.0


def test_qa_clip_reproduces_the_soma_joint_positions():
    """The retarget is exact: every mapped joint lands where SOMA put it."""
    source = MC.parse_bvh(SOMA_BVH)
    out = MC.parse_bvh(ML.clip_path(CLIP_ID))
    src_pos, _ = MC.forward_kinematics(source)
    out_pos, _ = MC.forward_kinematics(out)
    src_index = {n: i for i, n in enumerate(source['joints'])}
    out_index = {n: i for i, n in enumerate(out['joints'])}

    pairs = [
        ('Head', 'Head'),
        ('LeftHand', 'LeftHand'),
        ('RightHand', 'RightHand'),
        ('LeftFoot', 'LeftFoot'),
        ('RightToeBase', 'RightToeBase'),
        ('LeftUpLeg', 'LeftLeg'),
        ('Neck', 'Neck1'),
        ('Spine1', 'Chest'),
    ]
    worst = 0.0
    for frame in range(src_pos.shape[0]):
        hips_src = src_pos[frame, src_index['Hips']]
        hips_out = out_pos[frame + 1, out_index['Hips']]
        assert np.abs(hips_src - hips_out).max() < 1e-3
        for cmu_name, soma_name in pairs:
            delta = (out_pos[frame + 1, out_index[cmu_name]] - hips_out) - (
                src_pos[frame, src_index[soma_name]] - hips_src
            )
            worst = max(worst, float(np.abs(delta).max()))
    assert worst < 1e-3, worst
