# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for motion_capture: the BVH parser, forward kinematics, the SOMA -> cmu_mb
retarget, the library record and the whole GEM-X capture chain with every subprocess monkeypatched
away.  The sibling tests/test_motion_capture.py skips itself when data/assets/motion_library is
absent (it is, in a bare checkout), so every BVH here is synthesised under tmp_path."""

import json
import os
import types

import numpy as np
import pytest

pytest.importorskip('scipy', reason='motion_capture needs scipy.spatial.transform')

from zyg_workflows import motion_capture as MC  # noqa: E402
from zyg_workflows import motion_library as ML  # noqa: E402

_CHAN = ('Xposition', 'Yposition', 'Zposition', 'Zrotation', 'Yrotation', 'Xrotation')
_SPIN = ['Zrotation', 'Yrotation', 'Xrotation']

# A SOMA body in the USD spelling GEM-X exports, as `name parent x y z` quintuples ('.' = the
# root's parent).  A Y-up T-pose, so the rest skeleton the retarget lifts out of frame 0 is readable.
_SOMA_TABLE = """
Hips . 0 0 0   Spine1 Hips 0 8 0   Spine2 Spine1 0 9 0   Chest Spine2 0 9 0
Neck1 Chest 0 22 0   Neck2 Neck1 0 4 0   Head Neck2 0 6 0   HeadEnd Head 0 14 0
LeftShoulder Chest 4 4 0   LeftArm LeftShoulder 12 0 0   LeftForeArm LeftArm 27 0 0
LeftHand LeftForeArm 24 0 0   LeftHandThumb1 LeftHand 3 0 3   LeftHandThumb2 LeftHandThumb1 3 0 2
LeftHandIndex1 LeftHand 6 0 1.5   LeftHandIndex2 LeftHandIndex1 4 0 0   LeftHandMiddle1 LeftHand 6.5 0 -0.5
RightShoulder Chest -4 4 0   RightArm RightShoulder -12 0 0   RightForeArm RightArm -27 0 0
RightHand RightForeArm -24 0 0   RightHandThumb1 RightHand -3 0 3   RightHandThumb2 RightHandThumb1 -3 0 2
RightHandIndex1 RightHand -6 0 1.5   RightHandIndex2 RightHandIndex1 -4 0 0   RightHandMiddle1 RightHand -6.5 0 -0.5
LeftLeg Hips 8 -4 0   LeftShin LeftLeg 0 -42 0   LeftFoot LeftShin 0 -41 0
LeftToeBase LeftFoot 0 -5 12   LeftToeEnd LeftToeBase 0 0 6
RightLeg Hips -8 -4 0   RightShin RightLeg 0 -42 0   RightFoot RightShin 0 -41 0
RightToeBase RightFoot 0 -5 12   RightToeEnd RightToeBase 0 0 6
"""
_WORDS = _SOMA_TABLE.split()
_SOMA = [(_WORDS[i], _WORDS[i + 1], tuple(float(v) for v in _WORDS[i + 2 : i + 5])) for i in range(0, len(_WORDS), 5)]

# A three-joint BVH with a mixed channel layout and an End Site, no library behind it.
_MINI = (
    'HIERARCHY\nROOT Hips\n{\n\tOFFSET 0.0 0.0 0.0\n\tCHANNELS 6 ' + ' '.join(_CHAN) + '\n\n\tJOINT Spine\n\t{\n'
    '\t\tOFFSET 0.0 10.0 0.0\n\t\tCHANNELS 3 Zrotation Yrotation Xrotation\n\t\tJOINT Head\n\t\t{\n'
    '\t\t\tOFFSET 0.0 5.0 0.0\n\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation\n\t\t\tEnd Site\n\t\t\t{\n'
    '\t\t\t\tOFFSET 0.0 3.0 0.0\n\t\t\t}\n\t\t}\n\t}\n}\nMOTION\nFrames: 2\nFrame Time: 0.033333\n\n'
    '0 100 0 0 0 0 0 0 0 0 0 0\n1 101 2 0 0 0 0 0 0 0 0 90\n'
)


def _write_soma(path, hips, rots, drop=(), frame_time='0.041667', frames=True):  # a SOMA-shaped BVH
    rows = [r for r in _SOMA if r[0] not in drop]
    off = {name: offset for name, _p, offset in rows}
    kids = {}
    for name, parent, _offset in rows:
        kids.setdefault(parent, []).append(name)
    lines, order = ['HIERARCHY'], []

    def emit(name, depth):
        order.append(name)
        pad = '\t' * depth
        lines.append('%s%s %s' % (pad, 'ROOT' if depth == 0 else 'JOINT', name))
        lines.append(pad + '{')
        lines.append('%s\tOFFSET %.6f %.6f %.6f' % ((pad,) + off[name]))
        lines.append(pad + '\tCHANNELS 6 ' + ' '.join(_CHAN))
        for kid in kids.get(name, ()):
            emit(kid, depth + 1)
        if name not in kids:
            lines.extend([pad + '\tEnd Site', pad + '\t{', pad + '\t\tOFFSET 0.0 0.0 5.0', pad + '\t}'])
        lines.append(pad + '}')

    emit(kids['.'][0], 0)
    lines.append('MOTION')
    if frames:
        lines.append('Frames: %d' % len(rots))
    if frame_time:
        lines.append('Frame Time: ' + frame_time)
    for index, per_joint in enumerate(rots):
        row = []
        for slot, name in enumerate(order):
            pos = hips[index] if slot == 0 else off[name]
            row.extend(list(pos) + list(per_joint.get(name, (0.0, 0.0, 0.0))))
        lines.append(' '.join('%.6f' % v for v in row))
    with open(str(path), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    return order


def _soma_src(tmp_path, name='synth_soma.bvh', **kw):  # the two-frame clip: LeftArm swings 30 deg
    src = tmp_path / name
    _write_soma(src, [(0.0, 95.0, 0.0), (1.0, 94.0, 2.0)], [{}, {'LeftArm': (30.0, 0.0, 0.0)}], **kw)
    return str(src)


def _converted(tmp_path, name):  # a converted cmu_mb clip from the default SOMA source
    dst = tmp_path / name
    if not dst.is_file():
        MC.soma_bvh_to_cmu_mb(_soma_src(tmp_path), str(dst))
    return str(dst)


def _mini(tmp_path, name='mini.bvh'):
    (tmp_path / name).write_text(_MINI, encoding='utf-8')
    return str(tmp_path / name)


class _Run:  # stands in for subprocess.run: scripted stdout per call, or an exception
    def __init__(self, outs=(), boom=None, stderr='', returncode=0):
        self.outs, self.boom, self.stderr, self.returncode = list(outs), boom, stderr, returncode
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.boom is not None:
            raise self.boom
        out = self.outs[min(len(self.calls) - 1, len(self.outs) - 1)] if self.outs else ''
        return types.SimpleNamespace(stdout=out, stderr=self.stderr, returncode=self.returncode)


class _Halt:  # a threading.Event stand-in whose is_set() goes True after n polls
    def __init__(self, n=0):
        self.n, self.waits = n, []

    def is_set(self):
        self.n -= 1
        return self.n < 0

    def set(self):
        self.n = -1

    def wait(self, timeout=None):
        self.waits.append(timeout)


class _Popen:  # stands in for subprocess.Popen in _run_logged
    def __init__(self, text='hello\n', rc=0):
        self.text, self.rc, self.calls = text, rc, []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        return types.SimpleNamespace(pid=4242, returncode=self.rc, communicate=lambda: (self.text, None))


def _sampler(log_path, interval=2.0):  # stands in for _VramSampler: no thread, no nvidia-smi
    return types.SimpleNamespace(
        log_path=log_path, interval=interval, pid=None, baseline_mib=11, peak_mib=2222,
        start=lambda: None, stop=lambda: None,
    )  # fmt: skip


@pytest.fixture
def no_gpu(monkeypatch):  # nvidia-smi resolves and answers nothing by default
    monkeypatch.setattr(MC, 'exe', lambda name, **kw: '/usr/bin/' + name)
    run = _Run()
    monkeypatch.setattr(MC.subprocess, 'run', run)
    return run


@pytest.fixture
def library(tmp_path, monkeypatch):  # an empty library.json and a cmu_mb clip under a tmp ROOT
    root = tmp_path / 'motion_library'
    (root / 'capture').mkdir(parents=True)
    book = root / 'library.json'
    book.write_text('{}\n', encoding='utf-8')
    monkeypatch.setattr(MC, 'ROOT', str(root))
    monkeypatch.setattr(MC, 'LIBRARY_JSON', str(book))
    MC.soma_bvh_to_cmu_mb(_soma_src(tmp_path), str(root / 'capture' / 'synth.bvh'), fps=30)
    return types.SimpleNamespace(root=root, book=book, rel='capture/synth.bvh')


@pytest.fixture
def chain(tmp_path, monkeypatch, library):  # the whole GEM-X chain, every subprocess replaced
    monkeypatch.setattr(MC, 'CAPTURE_WORK_ROOT', str(tmp_path / 'work'))
    monkeypatch.setattr(MC, '_VramSampler', _sampler)
    monkeypatch.setattr(MC, 'video_fps', lambda path: 25.0)
    monkeypatch.setattr(MC, '_visual_odometry_state', lambda gem_dir, log=None: 'ran')
    video = tmp_path / 'footage' / 'Lunge Take 1.mp4'
    video.parent.mkdir()
    video.write_bytes(b'\x00' * 32)
    lab = types.SimpleNamespace(video=str(video), lines=[], runs=[], where='slug', tmp=tmp_path, library=library)

    def run_logged(args, cwd=None, log_path=None, sampler=None):
        lab.runs.append(list(args))
        if len(lab.runs) > 1:  # the gem_capture.py export: write the SOMA BVH it would have made
            _write_soma(args[args.index('--out') + 1], [(0.0, 95.0, 0.0), (1.0, 94.0, 2.0)], [{}, {}])
            return 3.25, 'export ok\n'
        gem_root = args[args.index('--output_root') + 1]
        slug = os.path.basename(os.path.dirname(gem_root))
        holder = {'slug': os.path.join(gem_root, slug), 'preprocess': os.path.join(gem_root, 'preprocess')}
        if lab.where in holder:
            os.makedirs(holder[lab.where], exist_ok=True)
            open(os.path.join(holder[lab.where], 'hpe_results.pt'), 'wb').close()
        return 12.5, 'demo ok\n'

    monkeypatch.setattr(MC, '_run_logged', run_logged)
    lab.log = lab.lines.append
    return lab


def test_cmu_mb_skeleton_matches_the_library_joint_order():
    joints, parents = MC.cmu_mb_skeleton()
    assert joints == ML.CMU_MB_JOINTS and len(joints) == 31
    assert parents[0] == -1 and parents.count(-1) == 1
    index = {name: i for i, name in enumerate(joints)}
    for child, parent in (('LeftUpLeg', 'LHipJoint'), ('Head', 'Neck1'), ('LeftHandIndex1', 'LeftFingerBase')):
        assert parents[index[child]] == index[parent], child
    assert all(parents[i] < i for i in range(1, len(joints)))  # depth-first pre-order
    table = {'b': 1, 'c': 2}
    assert MC._resolve(('a', 'b', 'c'), table) == 1 and MC._resolve(('c',), table) == 2
    assert MC._resolve(('a', 'z'), table) is None and MC._resolve((), table) is None
    rows = [(1.0, '1.000000'), (-0.0, '0.000000'), (0.0, '0.000000'), (-2.5, '-2.500000')]
    rows += [(1.0 / 3.0, '0.333333'), (np.float64(7.25), '7.250000')]
    for value, want in rows:
        assert MC._format(value) == want, value


def test_parse_bvh_reads_hierarchy_channels_and_motion(tmp_path):
    bvh = MC.parse_bvh(_mini(tmp_path))
    assert bvh['joints'] == ['Hips', 'Spine', 'Head'] and bvh['parents'] == [-1, 0, 1]
    assert bvh['channels'] == [list(_CHAN), _SPIN, _SPIN] and bvh['base'] == [0, 6, 9]
    assert bvh['frames'] == 2 and bvh['frame_time'] == pytest.approx(0.033333)
    assert bvh['motion'].shape == (2, 12)
    # the End Site OFFSET is not a joint offset
    assert bvh['offsets'].tolist() == [[0.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 5.0, 0.0]]


def test_parse_bvh_header_fallbacks_and_a_whole_soma_file(tmp_path):
    bare = tmp_path / 'headerless.bvh'
    bare.write_text(_MINI.replace('Frames: 2\n', '').replace('Frame Time: 0.033333\n', ''), encoding='utf-8')
    without = MC.parse_bvh(str(bare))
    assert without['frames'] == 2 and without['frame_time'] is None  # the rows are counted instead
    twice = tmp_path / 'twice.bvh'
    body = 'HIERARCHY\nROOT Hips\n{\n\tOFFSET 1 2 3\n\tOFFSET 9 9 9\n\tCHANNELS 3 ' + ' '.join(_SPIN) + '\n}\n'
    twice.write_text(body + 'MOTION\nFrames: 1\nFrame Time: 0.04\n0 0 0\n', encoding='utf-8')
    assert MC.parse_bvh(str(twice))['offsets'].tolist() == [[1.0, 2.0, 3.0]]  # the first OFFSET wins
    order = _write_soma(tmp_path / 'soma.bvh', [(0.0, 95.0, 0.0)], [{}])
    soma = MC.parse_bvh(str(tmp_path / 'soma.bvh'))
    assert soma['joints'] == order and len(order) == 36
    assert soma['base'] == [6 * i for i in range(36)] and soma['motion'].shape == (1, 6 * 36)
    assert all(names == list(_CHAN) for names in soma['channels'])


def test_forward_kinematics_chains_offsets_and_every_channel(tmp_path):
    pos, rot = MC.forward_kinematics(MC.parse_bvh(_mini(tmp_path)))
    assert pos.shape == (2, 3, 3) and rot.shape == (2, 3, 3, 3)
    assert pos[0].tolist() == [[0.0, 100.0, 0.0], [0.0, 110.0, 0.0], [0.0, 115.0, 0.0]]
    # the hips translation moves the whole chain; Head's own Xrotation moves nothing above it
    assert pos[1] == pytest.approx(np.array([[1.0, 101.0, 2.0], [1.0, 111.0, 2.0], [1.0, 116.0, 2.0]]))
    assert rot[1, 0] == pytest.approx(np.eye(3)) and rot[1, 1] == pytest.approx(np.eye(3))
    assert rot[1, 2] == pytest.approx(np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]), abs=1e-12)
    six = tmp_path / 'sixch.bvh'
    head = 'HIERARCHY\nROOT Hips\n{\n\tOFFSET 0 0 0\n\tCHANNELS 6 ' + ' '.join(_CHAN) + '\n}\n'
    six.write_text(head + 'MOTION\nFrames: 1\nFrame Time: 0.04\n4 5 6 0 90 0\n', encoding='utf-8')
    one_pos, one_rot = MC.forward_kinematics(MC.parse_bvh(str(six)))
    assert one_pos[0, 0].tolist() == [4.0, 5.0, 6.0]  # all three position channels land
    assert one_rot[0, 0] == pytest.approx(np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]), abs=1e-12)


def test_soma_bvh_to_cmu_mb_writes_a_cmu_mb_file_and_reports_it(tmp_path):
    src = _soma_src(tmp_path)
    dst = tmp_path / 'out' / 'synth.bvh'  # the nested dir is created by the converter
    info = MC.soma_bvh_to_cmu_mb(src, str(dst))
    assert info['frames'] == 3 and info['source_frames'] == 2 and info['joints'] == 31
    assert info['fps'] == 24 and info['frame_time'] == pytest.approx(1.0 / 24, abs=1e-6)
    assert info['rest_frame'] == 1 and info['reference_frame'] == 0
    assert info['unmapped'] == ['LHipJoint', 'RHipJoint']
    assert len(info['mapped']) == 29 and 'Hips' in info['mapped']
    assert info['height_units'] == pytest.approx(95.0)
    out = MC.parse_bvh(str(dst))
    assert out['joints'] == ML.CMU_MB_JOINTS and out['channels'][0] == list(_CHAN)
    assert all(ch == _SPIN for ch in out['channels'][1:])
    assert out['motion'].shape == (3, 6 + 30 * 3)
    assert np.abs(out['motion'][0, 3:]).max() == 0.0  # frame 1 is the reference pose
    assert out['motion'][0, :3].tolist() == [0.0, 95.0, 0.0]
    assert out['motion'][1, :3].tolist() == [0.0, 95.0, 0.0]
    assert out['motion'][2, :3] == pytest.approx(np.array([1.0, 94.0, 2.0]))


def test_the_rest_skeleton_and_the_end_sites_come_from_the_reference_frame(tmp_path):
    out = MC.parse_bvh(_converted(tmp_path, 'rest.bvh'))
    text = (tmp_path / 'rest.bvh').read_text(encoding='utf-8')
    index = {name: i for i, name in enumerate(out['joints'])}
    offsets = out['offsets']
    assert offsets[0].tolist() == [0.0, 0.0, 0.0]
    # the two hip connectors borrow the Hips source, so their bone is zero-length
    assert offsets[index['LHipJoint']] == pytest.approx(np.zeros(3))
    assert offsets[index['RHipJoint']] == pytest.approx(np.zeros(3))
    # LeftUpLeg hangs off LHipJoint, whose source is Hips: the whole Hips->LeftLeg vector
    assert offsets[index['LeftUpLeg']] == pytest.approx(np.array([8.0, -4.0, 0.0]))
    assert offsets[index['LeftLeg']] == pytest.approx(np.array([0.0, -42.0, 0.0]))
    assert offsets[index['Head']] == pytest.approx(np.array([0.0, 6.0, 0.0]))
    # LowerBack -> Spine -> Spine1 is Spine1 -> Spine2 -> Chest in SOMA
    assert offsets[index['Spine']] == pytest.approx(np.array([0.0, 9.0, 0.0]))
    # HeadEnd is in the SOMA tree, so Head's End Site is the real Head->HeadEnd tip
    assert text.count('End Site') == 7 and 'OFFSET 0.000000 14.000000 0.000000' in text
    notip = tmp_path / 'notip.bvh'  # drop it: the tip becomes a third of Head's bone (6 / 3)
    MC.soma_bvh_to_cmu_mb(_soma_src(tmp_path, name='notip_soma.bvh', drop=('HeadEnd',)), str(notip))
    assert 'OFFSET 0.000000 2.000000 0.000000' in notip.read_text(encoding='utf-8')


def test_the_retarget_carries_the_source_rotation_and_positions_through(tmp_path):
    source = MC.parse_bvh(_soma_src(tmp_path))
    out = MC.parse_bvh(_converted(tmp_path, 'carry.bvh'))
    src_pos, src_rot = MC.forward_kinematics(source)
    out_pos, out_rot = MC.forward_kinematics(out)
    s_index = {n: i for i, n in enumerate(source['joints'])}
    o_index = {n: i for i, n in enumerate(out['joints'])}
    pairs = [('Head', 'Head'), ('LeftHand', 'LeftHand'), ('LeftFoot', 'LeftFoot'), ('Neck', 'Neck1')]
    pairs += [('Spine1', 'Chest'), ('LeftUpLeg', 'LeftLeg'), ('RightToeBase', 'RightToeBase')]
    for frame in range(src_pos.shape[0]):
        hips_src = src_pos[frame, s_index['Hips']]
        hips_out = out_pos[frame + 1, o_index['Hips']]
        assert hips_src == pytest.approx(hips_out, abs=1e-3)
        for cmu, soma in pairs:
            got = out_pos[frame + 1, o_index[cmu]] - hips_out
            assert got == pytest.approx(src_pos[frame, s_index[soma]] - hips_src, abs=1e-3), (frame, cmu)
    # the 30 degree LeftArm swing survives as a world rotation, relative to frame 0
    delta = src_rot[1, s_index['LeftArm']] @ src_rot[0, s_index['LeftArm']].T
    assert out_rot[2, o_index['LeftArm']] == pytest.approx(delta, abs=1e-6)
    assert np.abs(delta - np.eye(3)).max() > 0.1


def test_fps_comes_from_the_frame_time_or_the_override(tmp_path):
    cases = [(None, '0.041667', 24), (60, '0.041667', 60), (None, '0.020000', 50), (30.0, None, 30)]
    cases += [(None, None, 24)]  # no Frame Time line at all -> the 24 fps default
    for index, (fps, frame_time, want) in enumerate(cases):
        src = _soma_src(tmp_path, name='fps%d_soma.bvh' % index, frame_time=frame_time)
        info = MC.soma_bvh_to_cmu_mb(src, str(tmp_path / ('fps%d.bvh' % index)), fps=fps)
        assert info['fps'] == want, (fps, frame_time)
        assert info['frame_time'] == pytest.approx(round(1.0 / want, 6))
        assert info['frames'] == 3  # the frame count never changes


def test_the_retarget_refuses_a_source_it_cannot_use(tmp_path, monkeypatch):
    src = _soma_src(tmp_path)
    dead = str(tmp_path / 'never.bvh')
    with monkeypatch.context() as mp:
        mp.setattr(MC, 'forward_kinematics', lambda bvh: (np.zeros((0, 3, 3)), np.zeros((0, 3, 3, 3))))
        with pytest.raises(ValueError, match='no motion frames'):
            MC.soma_bvh_to_cmu_mb(src, dead)
    with monkeypatch.context() as mp:
        mp.setattr(ML, 'CMU_MB_JOINTS', ['Hips'])
        with pytest.raises(AssertionError, match='HIERARCHY drifted'):
            MC.soma_bvh_to_cmu_mb(src, dead)
    nohips = tmp_path / 'nohips.bvh'
    head = 'HIERARCHY\nROOT Torso\n{\n\tOFFSET 0 0 0\n\tCHANNELS 6 ' + ' '.join(_CHAN) + '\n}\n'
    nohips.write_text(head + 'MOTION\nFrames: 1\nFrame Time: 0.04\n0 90 0 0 0 0\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no joint this converter recognises as the hips'):
        MC.soma_bvh_to_cmu_mb(str(nohips), dead)
    assert not os.path.exists(dead)  # nothing is written on any of the three refusals


def test_register_capture_reads_the_numbers_back_out_of_the_bvh(library):
    tags, licence = ('qa', 'synthetic'), 'internal test only'
    record = MC.register_capture('capture/synth', library.rel, 'A synthetic lunge', tags, 'source.mp4', licence)
    assert record['id'] == 'capture/synth' and record['file'] == library.rel
    assert record['label'] == 'A synthetic lunge' and record['tags'] == ['qa', 'synthetic']
    assert record['frames'] == 3 and record['joints'] == 31 and record['root'] == 'Hips'
    assert record['fps'] == 30 and record['frame_time'] == pytest.approx(1.0 / 30, abs=1e-6)
    assert record['height_units'] == pytest.approx(95.0) and record['licence'] == licence
    assert record['rest_frame'] == 1 and record['engine'] == 'gem-x'
    assert record['publishable'] is False and record['may_train'] is False
    assert 'provenance' not in record
    assert len(record['captured']) == 10 and record['captured'][4] == '-'  # today, ISO
    assert json.loads(library.book.read_text(encoding='utf-8'))['capture'] == [record]


def test_register_capture_replaces_the_clip_of_the_same_id(library):
    library.book.write_text(json.dumps({'capture': [{'id': 'capture/synth', 'file': 'old'}, {'id': 'other'}]}))
    extra = {'publishable': 1, 'may_train': 1, 'captured': '2026-01-02', 'engine': 'gem-x-next'}
    extra['provenance'] = {'engine': 'gem-x', 'vo': 'ran'}
    record = MC.register_capture('capture/synth', library.rel, 'Lunge', [], 'source.mp4', 'cc0', **extra)
    assert record['publishable'] is True and record['may_train'] is True
    assert record['captured'] == '2026-01-02' and record['engine'] == 'gem-x-next'
    assert record['provenance'] == {'engine': 'gem-x', 'vo': 'ran'}
    capture = json.loads(library.book.read_text(encoding='utf-8'))['capture']
    assert [rec['id'] for rec in capture] == ['other', 'capture/synth'] and capture[-1] == record
    (library.root / 'capture' / 'mini.bvh').write_text(_MINI, encoding='utf-8')
    with pytest.raises(ValueError, match='is not a cmu_mb skeleton'):
        MC.register_capture('capture/mini', 'capture/mini.bvh', 'Mini', (), 'x.mp4', 'cc0')


def test_slug_and_the_gemx_environment(monkeypatch):
    cases = {'capture/qa_sword_short': 'qa_sword_short', 'QA Sword!': 'qa_sword', 'a/b/C-9': 'c_9'}
    cases.update({'  Spaced Out  ': 'spaced_out', '___': '', '!!!': '', 'plain': 'plain', 'x/': ''})
    for clip_id, want in cases.items():
        assert MC._slug(clip_id) == want, clip_id
    monkeypatch.setenv('PATH', '/usr/bin')
    env = MC._gemx_env()
    assert env['PYOPENGL_PLATFORM'] == 'egl' and env['EGL_PLATFORM'] == 'surfaceless'
    assert env['VIRTUAL_ENV'] == os.path.join(MC.GEMX_ROOT, '.venv')
    assert env['PATH'] == os.path.join(MC.GEMX_ROOT, '.venv', 'bin') + os.pathsep + '/usr/bin'
    assert env is not os.environ


def test_video_fps_parses_ffprobes_rational_rate(monkeypatch):
    monkeypatch.setattr(MC, 'exe', lambda name, **kw: '/usr/bin/' + name)
    for out, want in [('30000/1001\n', 29.97002997), ('25\n', 25.0), ('24/1', 24.0), ('12/2\n', 6.0)]:
        run = _Run([out])
        monkeypatch.setattr(MC.subprocess, 'run', run)
        assert MC.video_fps('/clip.mp4') == pytest.approx(want), out
        cmd, kw = run.calls[0]
        assert cmd[0] == '/usr/bin/ffprobe' and cmd[-1] == '/clip.mp4'
        assert 'stream=r_frame_rate' in cmd and kw['check'] is True and kw['text'] is True


def test_vram_sampler_reads_the_device_total_or_nothing_at_all(no_gpu):
    no_gpu.outs[:] = ['4096 2048\n']
    sampler = MC._VramSampler('')
    assert sampler.baseline_mib == 4096 and sampler.total_peak_mib == 4096
    assert sampler.process_peak_mib == 0 and sampler.pid is None
    cmd, kw = no_gpu.calls[0]
    assert cmd == ['/usr/bin/nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits']
    assert kw['timeout'] == 20
    assert sampler.peak_mib == 4096  # no process figure yet: the device total is reported
    no_gpu.boom = FileNotFoundError('nvidia-smi')
    assert MC._VramSampler('').baseline_mib == 0
    no_gpu.boom = MC.subprocess.TimeoutExpired('nvidia-smi', 20)
    assert MC._VramSampler('')._query([]) == ''
    no_gpu.boom = None
    no_gpu.outs[:] = ['no numbers here\n']
    assert MC._VramSampler('').baseline_mib == 0


def test_vram_sampler_records_the_total_and_the_childs_own_peak(no_gpu, tmp_path):
    no_gpu.outs[:] = ['1000\n', '5000\n', '123, 777\njunk\n4, 8\nbad, x\n']
    sampler = MC._VramSampler(str(tmp_path / 'logs' / 'vram.log'))
    sampler.pid = 123
    sampler._sample()
    assert sampler.total_peak_mib == 5000 and sampler.process_peak_mib == 777
    assert sampler.peak_mib == 777  # the process figure wins once there is one
    assert [line.split()[0] for line in sampler._lines] == ['T', 'P', 'P']
    assert sampler._lines[1] == 'P 123, 777' and sampler._lines[2] == 'P 4, 8'
    assert sampler._lines[0].endswith(' 5000')


def test_vram_sampler_polls_until_halted_and_writes_its_log(no_gpu, tmp_path, monkeypatch):
    sampler = MC._VramSampler('', interval=0.25)
    monkeypatch.setattr(sampler, '_halt', _Halt(2))
    monkeypatch.setattr(sampler, '_sample', lambda: sampler._lines.append('S'))
    sampler.run()
    assert sampler._lines == ['S', 'S'] and sampler._halt.waits == [0.25, 0.25]
    log = tmp_path / 'deep' / 'vram.log'
    keeper = MC._VramSampler(str(log))
    monkeypatch.setattr(keeper, 'join', lambda timeout=None: None)
    monkeypatch.setattr(keeper, '_halt', _Halt(5))
    keeper._lines[:] = ['T 1 10', 'P 7, 20']
    keeper.stop()
    assert keeper._halt.n == -1 and log.read_text(encoding='utf-8') == 'T 1 10\nP 7, 20\n'
    quiet = MC._VramSampler('')
    monkeypatch.setattr(quiet, 'join', lambda timeout=None: None)
    quiet.stop()  # no log_path: nothing is written and nothing raises


def test_run_logged_tees_the_output_and_times_the_child(tmp_path, monkeypatch):
    popen = _Popen(text='line one\nline two\n')
    monkeypatch.setattr(MC.subprocess, 'Popen', popen)
    sampler = types.SimpleNamespace(pid=None)
    log = tmp_path / 'logs' / 'demo.log'
    seconds, text = MC._run_logged(['/py', '/demo.py', '--x'], cwd='/gemx', log_path=str(log), sampler=sampler)
    assert text == 'line one\nline two\n' and seconds >= 0.0 and sampler.pid == 4242
    assert log.read_text(encoding='utf-8') == text
    args, kw = popen.calls[0]
    assert args == ['/py', '/demo.py', '--x'] and kw['cwd'] == '/gemx'
    assert kw['stderr'] is MC.subprocess.STDOUT and kw['text'] is True and kw['errors'] == 'replace'
    assert kw['env']['PYOPENGL_PLATFORM'] == 'egl'
    monkeypatch.setattr(MC.subprocess, 'Popen', _Popen(text='quiet\n'))
    assert MC._run_logged(['/py'], cwd=None, log_path='')[1] == 'quiet\n'  # no log path, no sampler


def test_run_logged_raises_with_the_tail_of_a_failed_child(monkeypatch):
    monkeypatch.setattr(MC.subprocess, 'Popen', _Popen(text='\n'.join('row %d' % i for i in range(40)), rc=3))
    with pytest.raises(RuntimeError) as caught:
        MC._run_logged(['/py', '/opt/gemx/demo_soma.py'], cwd=None, log_path=None)
    message = str(caught.value)
    assert message.startswith('demo_soma.py exited 3')
    assert 'row 39' in message and 'row 15' in message and 'row 14' not in message
    monkeypatch.setattr(MC.subprocess, 'Popen', _Popen(text='boom', rc=1))
    with pytest.raises(RuntimeError, match=r'^py exited 1'):  # a one-element argv names args[0]
        MC._run_logged(['/usr/bin/py'], cwd=None, log_path=None)


def test_visual_odometry_state_reads_the_probes_verdict(tmp_path, monkeypatch):
    assert MC._visual_odometry_state(str(tmp_path), log=lambda _m: None) == 'unknown'  # no camera.pt
    camera = tmp_path / 'preprocess' / 'camera.pt'
    camera.parent.mkdir()
    camera.write_bytes(b'not really a tensor')
    cases = [('ran\n', 'ran', 0), ('noise\nfallback_static\n', 'fallback_static', 0), ('weird\n', 'unknown', 1)]
    cases += [('', 'unknown', 1), ('   \n', 'unknown', 1)]
    for out, want, logged in cases:
        lines = []
        run = _Run([out], stderr='traceback' * 50)
        monkeypatch.setattr(MC.subprocess, 'run', run)
        assert MC._visual_odometry_state(str(tmp_path), log=lines.append) == want, out
        assert len(lines) == logged, out
        cmd, kw = run.calls[0]
        assert cmd[0] == MC.GEMX_PYTHON and cmd[1] == '-c' and cmd[3] == str(camera)
        assert kw['cwd'] == MC.GEMX_ROOT and kw['timeout'] == 300
    assert len(lines[0]) < 260  # the stderr tail is clipped to 200 characters
    for boom in (OSError('no such python'), MC.subprocess.TimeoutExpired('py', 300)):
        lines = []
        monkeypatch.setattr(MC.subprocess, 'run', _Run(boom=boom))
        assert MC._visual_odometry_state(str(tmp_path), log=lines.append) == 'unknown'
        assert lines and lines[0].startswith('visual odometry probe failed:')


def test_capture_from_video_runs_the_whole_chain_and_registers_the_clip(chain):
    out = MC.capture_from_video(
        chain.video, 'capture/Lunge Take 1', 'Lunge take one', tags=['qa'], licence='cc0', log=chain.log
    )
    assert out['record']['id'] == 'capture/Lunge Take 1'
    assert out['record']['file'] == 'capture/lunge_take_1.bvh'
    assert out['fps'] == 25.0 and out['visual_odometry'] == 'ran' and out['vram_peak_mib'] == 2222
    assert out['seconds'] == {'demo': 12.5, 'export': 3.25, 'total': 15.75}
    assert out['retarget']['frames'] == 3 and out['retarget']['joints'] == 31
    assert out['work_root'].endswith(os.path.join('work', 'lunge_take_1'))
    assert os.path.isfile(out['clip_path']) and os.path.isfile(out['soma_bvh'])
    assert os.path.isfile(os.path.join(out['work_root'], 'lunge_take_1.mp4'))  # the renamed copy
    prov = out['provenance']
    assert prov['engine'] == 'gem-x' and prov['visual_odometry'] == 'ran' and prov['fps'] == 25.0
    assert prov['demo_seconds'] == 12.5 and prov['export_seconds'] == 3.25
    assert prov['vram_peak_mib'] == 2222 and prov['vram_baseline_mib'] == 11
    assert prov['soma_frames'] == 2 and prov['unmapped_joints'] == ['LHipJoint', 'RHipJoint']
    assert prov['gem_dir'].endswith('lunge_take_1') and prov['work_root'] == out['work_root']
    assert out['record']['provenance'] == prov
    assert out['record']['source_clip'] == chain.video  # outside CREWS: the absolute path is kept
    assert chain.runs[0][1] == MC.GEMX_DEMO and chain.runs[0][-1] == '--verbose'
    assert chain.runs[0][chain.runs[0].index('--ckpt') + 1] == MC.GEMX_CKPT
    export = chain.runs[1]
    assert export[1] == MC.GEM_CAPTURE and export[export.index('--fps') + 1] == '25.000000'
    assert export[export.index('--wall-seconds') + 1] == '12.500'
    assert export[export.index('--vram-peak-mib') + 1] == '2222'
    assert export[export.index('--vram-baseline-mib') + 1] == '11'
    assert export[export.index('--vo') + 1] == 'ran'
    assert len(chain.lines) == 5 and chain.lines[0].startswith('capture capture/Lunge Take 1:')
    assert 'VRAM peak 2222 MiB (baseline 11 MiB)' in chain.lines[1]
    assert 'visual odometry: ran' in chain.lines[2]
    assert chain.lines[3] == '  retarget: 3 frames, 31 joints, rest_frame 1'
    assert chain.lines[4] == '  registered capture/Lunge Take 1 (capture/lunge_take_1.bvh)'


def test_capture_from_video_takes_the_fps_override_and_a_relative_source_clip(chain, monkeypatch):
    monkeypatch.setattr(MC, 'video_fps', lambda path: pytest.fail('video_fps must not run with an explicit fps'))
    monkeypatch.setattr(MC, 'CREWS', str(chain.tmp))
    out = MC.capture_from_video(chain.video, 'capture/vid', 'Vid', fps=48, work_root=None, log=lambda _m: None)
    assert out['fps'] == 48.0 and out['retarget']['fps'] == 48
    assert out['record']['source_clip'] == os.path.join('footage', 'Lunge Take 1.mp4')
    assert chain.runs[1][chain.runs[1].index('--fps') + 1] == '48.000000'


def test_capture_from_video_accepts_the_gem_outputs_beside_a_given_work_root(chain, tmp_path):
    chain.where = 'preprocess'
    work = tmp_path / 'chosen'
    work.mkdir()
    video = work / 'lunge_take_1.mp4'  # the copy would land on the video: copyfile is skipped
    video.write_bytes(b'\x00' * 8)
    out = MC.capture_from_video(str(video), 'capture/lunge_take_1', 'Lunge', work_root=str(work), log=lambda _m: None)
    assert out['work_root'] == str(work) and out['soma_bvh'].startswith(str(work))
    assert out['provenance']['source_copy'] == str(video)
    assert out['provenance']['gem_dir'] == os.path.join(str(work), 'gem')


def test_capture_from_video_refuses_bad_input_and_a_barren_gem_run(chain, tmp_path):
    with pytest.raises(FileNotFoundError):
        MC.capture_from_video(str(tmp_path / 'nope.mp4'), 'capture/x', 'X')
    with pytest.raises(ValueError, match='has no usable name'):
        MC.capture_from_video(chain.video, 'capture/___', 'X')
    chain.where = 'nothing'
    with pytest.raises(RuntimeError, match='no hpe_results.pt under'):
        MC.capture_from_video(chain.video, 'capture/vid', 'Vid', log=lambda _m: None)


def test_main_captures_and_prints_the_record(monkeypatch, capsys):
    seen = {}

    def fake(video, clip_id, label, **kw):
        seen.update(kw, video=video, clip_id=clip_id, label=label)
        return {'record': {'id': clip_id, 'file': 'capture/x.bvh'}}

    monkeypatch.setattr(MC, 'capture_from_video', fake)
    argv = ['capture', 'clip.mp4', '--id', 'capture/x', '--label', 'A lunge', '--tags', 'qa, sword,,']
    argv += ['--licence', 'cc0', '--publishable', '--may-train', '--fps', '30', '--work-root', '/tmp/w']
    assert MC.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == {'id': 'capture/x', 'file': 'capture/x.bvh'}
    assert seen['video'] == 'clip.mp4' and seen['clip_id'] == 'capture/x' and seen['label'] == 'A lunge'
    assert seen['tags'] == ['qa', 'sword'] and seen['licence'] == 'cc0'
    assert seen['publishable'] is True and seen['may_train'] is True
    assert seen['fps'] == 30.0 and seen['work_root'] == '/tmp/w'
    monkeypatch.setattr(MC, 'capture_from_video', lambda *a, **kw: {'record': dict(kw, label=a[2])})
    assert MC.main(['capture', 'c.mp4', '--id', 'capture/y', '--label', 'Y']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['tags'] == [] and record['licence'] == '' and record['fps'] is None
    assert record['publishable'] is False and record['may_train'] is False and record['work_root'] is None
    with pytest.raises(SystemExit) as caught:
        MC.main([])
    assert caught.value.code == 2
