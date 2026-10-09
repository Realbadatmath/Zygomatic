# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_animate_service replacement mode — graph-level, no ComfyUI, no GPU.

_comfy.submit is monkeypatched to CAPTURE the built graph (and the overrides applied on
top of it) instead of posting it. Two things are proved:

  * with background_dir/mask_dir the graph grows exactly three nodes (two folder loaders
    and one ImageToMask) and node 30's background_video / character_mask point at them;
  * with neither kwarg the graph is byte-identical to the generation-mode graph that
    shipped before replacement mode existed — the regression this feature could cause.

The plate-set entry is exercised on a synthetic plates/ directory (six frames of every
prefix + a plateset.json), so the path arithmetic is checked without a Blender render.
"""

import copy
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .venv-test is deliberately minimal (numpy/cv2/PIL/scipy only). wan_animate_service ->
# _comfy_client imports `requests` at module scope for the HTTP calls this test never
# makes: every submission goes through the monkeypatched _comfy.submit. A stub keeps the
# import graph satisfied and would fail loudly if any code path actually reached the wire.
if 'requests' not in sys.modules:
    try:
        import requests  # noqa: F401
    except ImportError:
        _stub = types.ModuleType('requests')
        _stub.Session = _stub.get = _stub.post = _stub.delete = None
        _stub.exceptions = types.ModuleType('requests.exceptions')
        _stub.exceptions.RequestException = Exception
        _stub.RequestException = Exception
        sys.modules['requests'] = _stub
        sys.modules['requests.exceptions'] = _stub.exceptions

from zyg_workflows import wan_animate_service as WA  # noqa: E402

W, H, N = 320, 192, 6


class _Capture:
    """Stands in for _comfy.submit: records the graph, returns fake PNG paths."""

    def __init__(self, tmpdir):
        self.calls = []
        self._tmp = tmpdir

    def __call__(self, wf, overrides=None, timeout_s=0, **kw):
        merged = copy.deepcopy(wf)
        for nid, ins in (overrides or {}).items():
            merged.setdefault(nid, {'class_type': '?', 'inputs': {}})
            merged[nid].setdefault('inputs', {}).update(ins)
        self.calls.append({'wf': copy.deepcopy(wf), 'overrides': copy.deepcopy(overrides), 'merged': merged})
        d = os.path.join(self._tmp, 'sub_%02d' % len(self.calls))
        os.makedirs(d, exist_ok=True)
        out = []
        for i in range(3):
            p = os.path.join(d, 'out_%05d.png' % i)
            with open(p, 'wb') as fh:
                fh.write(b'\x89PNG\r\n\x1a\n')
            out.append(p)
        return out


@pytest.fixture
def cap(tmp_path, monkeypatch):
    c = _Capture(str(tmp_path / 'comfy'))
    monkeypatch.setattr(WA._comfy, 'submit', c)
    monkeypatch.setattr(WA._comfy, 'stage_input_image', lambda p: os.path.basename(p))
    return c


def _dirs(tmp_path):
    made = {}
    for k in ('pose', 'face', 'bg', 'mask', 'out'):
        d = tmp_path / k
        d.mkdir()
        made[k] = str(d)
    return made


def d_bg(tmp_path):
    return str(tmp_path / 'bg')


def d_mask(tmp_path):
    return str(tmp_path / 'mask')


def _chunk(tmp_path, **kw):
    d = _dirs(tmp_path)
    return WA.submit_animate_chunk(
        str(tmp_path / 'ref.png'), d['pose'], d['face'], d['out'], width=W, height=H, **kw
    ), d


# ----------------------------------------------------------------- the graph


def test_no_kwargs_graph_is_the_shipped_generation_graph(cap, tmp_path):
    """Byte-identical to the template + the pre-existing overrides. This is the
    'keep the existing behaviour' assertion."""
    _chunk(tmp_path)
    wf = cap.calls[0]['wf']
    assert wf == WA._comfy.load_workflow('wan22_animate')
    assert 'background_video' not in wf['30']['inputs']
    assert 'character_mask' not in wf['30']['inputs']
    assert set(cap.calls[0]['overrides']) == {'10', '11', '12', '20', '21', '30', '40', '6', '51', '60'}


def test_background_and_mask_wire_node_30(cap, tmp_path):
    _out, d = _chunk(tmp_path, background_dir=d_bg(tmp_path), mask_dir=d_mask(tmp_path))
    wf = cap.calls[0]['wf']
    assert wf['30']['inputs']['background_video'] == ['15', 0]
    assert wf['30']['inputs']['character_mask'] == ['17', 0]
    assert wf['15']['class_type'] == 'LoadImagesFromFolderKJ'
    assert wf['16']['class_type'] == 'LoadImagesFromFolderKJ'
    assert wf['17']['class_type'] == 'ImageToMask'
    assert wf['17']['inputs'] == {'image': ['16', 0], 'channel': 'red'}
    assert wf['15']['inputs']['folder'] == os.path.abspath(d_bg(tmp_path))
    assert wf['16']['inputs']['folder'] == os.path.abspath(d_mask(tmp_path))
    for nid in ('15', '16'):
        assert (wf[nid]['inputs']['width'], wf[nid]['inputs']['height']) == (W, H)
        assert wf[nid]['inputs']['include_subfolders'] is False
    # exactly three new nodes, nothing else moved
    base = WA._comfy.load_workflow('wan22_animate')
    assert set(wf) - set(base) == {'15', '16', '17'}
    for nid in base:
        if nid != '30':
            assert wf[nid] == base[nid], nid
    assert {k: v for k, v in wf['30']['inputs'].items() if k not in ('background_video', 'character_mask')} == base[
        '30'
    ]['inputs']


def test_background_alone_and_mask_alone_are_independent(cap, tmp_path):
    _chunk(tmp_path, background_dir=d_bg(tmp_path))
    wf = cap.calls[0]['wf']
    assert '15' in wf and '16' not in wf and '17' not in wf
    assert wf['30']['inputs']['background_video'] == ['15', 0]
    assert 'character_mask' not in wf['30']['inputs']

    cap.calls.clear()
    t2 = tmp_path / 'b'
    t2.mkdir()
    _chunk(t2, mask_dir=str(t2 / 'mask'))
    wf = cap.calls[0]['wf']
    assert '15' not in wf and '16' in wf and '17' in wf
    assert wf['30']['inputs']['character_mask'] == ['17', 0]
    assert 'background_video' not in wf['30']['inputs']


def test_replacement_coexists_with_lora_and_continue_motion(cap, tmp_path):
    d = _dirs(tmp_path)
    tail = tmp_path / 'tail'
    tail.mkdir()
    WA.submit_animate_chunk(
        str(tmp_path / 'ref.png'),
        d['pose'],
        d['face'],
        d['out'],
        width=W,
        height=H,
        background_dir=d['bg'],
        mask_dir=d['mask'],
        continue_motion_dir=str(tail),
        lora='x.safetensors',
        lora_strength=0.8,
    )
    wf = cap.calls[0]['wf']
    assert wf['30']['inputs']['continue_motion'] == ['13', 0]
    assert wf['30']['inputs']['background_video'] == ['15', 0]
    assert wf['30']['inputs']['character_mask'] == ['17', 0]
    assert wf['6']['inputs']['model'] == ['5', 0]


def test_every_chunk_gets_the_full_unsliced_sequences(cap, tmp_path, monkeypatch):
    """The native node seeks background_video/character_mask with the same
    video_frame_offset it applies to pose (nodes_wan.py L1211-1213, L1223-1227), so the
    folders handed to chunk k must be the SAME folders chunk 0 got."""
    monkeypatch.setattr(WA.subprocess, 'run', lambda *a, **k: None)
    d = _dirs(tmp_path)
    WA.generate_animate_clips(
        str(tmp_path / 'ref.png'),
        d['pose'],
        d['face'],
        d['out'],
        width=W,
        height=H,
        n_chunks=3,
        background_dir=d['bg'],
        mask_dir=d['mask'],
    )
    assert len(cap.calls) == 3
    folders = {(c['wf']['15']['inputs']['folder'], c['wf']['16']['inputs']['folder']) for c in cap.calls}
    assert folders == {(os.path.abspath(d['bg']), os.path.abspath(d['mask']))}
    offs = [c['overrides']['30']['video_frame_offset'] for c in cap.calls]
    assert offs[0] == 0 and offs[1] > 0 and offs[2] > offs[1]


# ----------------------------------------------------------------- the plate-set entry


def _synth_plateset(root, n=N, face=True):
    plates = os.path.join(str(root), 'plates')
    os.makedirs(plates, exist_ok=True)
    pats = ['bg_%05d.png', 'ctrl_%05d.png', 'pose_%05d.png', 'm_%05d.png', 'depth_%05d.png'] + (
        ['face_%05d.png'] if face else []
    )
    for i in range(1, n + 1):
        for p in pats:
            with open(os.path.join(plates, p % i), 'wb') as fh:
                fh.write(b'\x89PNG\r\n\x1a\n')
    ps = {
        'schema': 'zyg.plateset/1',
        'shot': 'synth',
        'frames': n,
        'fps': 24,
        'width': W,
        'height': H,
        'actors': [{'id': 'abel', 'char_id': 'abel'}],
        'face_source': 'canon_static' if face else 'none',
        'ctrl': 'ctrl_%05d.png',
        'mask': 'm_%05d.png',
        'pose': 'pose_%05d.png',
        'face': 'face_%05d.png',
        'bg': 'bg_%05d.png',
        'depth': 'depth_%05d.png',
        'still': 'still.png',
    }
    with open(os.path.join(plates, 'plateset.json'), 'w', encoding='utf-8') as fh:
        json.dump(ps, fh)
    return plates


@pytest.fixture
def plated(tmp_path, cap, monkeypatch):
    monkeypatch.setattr(WA.subprocess, 'run', lambda *a, **k: None)
    ref = tmp_path / 'cell_00.png'
    ref.write_bytes(b'\x89PNG\r\n\x1a\n')
    from zyg_workflows import canon_service

    monkeypatch.setattr(canon_service, 'canon_portrait', lambda cid: str(ref))
    return tmp_path, cap, str(ref)


def test_animate_from_plateset_builds_the_paths(plated):
    tmp_path, cap, ref = plated
    shot = tmp_path / 'shot'
    _synth_plateset(shot)
    out = WA.animate_from_plateset(str(shot), 'abel', seed=7, prompt='abel walks')

    take = os.path.join(str(shot), 'video', 'animate_take1')
    assert out['take_dir'] == take
    assert out['mp4'] == os.path.join(take, 'animate.mp4')
    assert out['reference'] == ref
    assert out['n_chunks'] == 1  # 6 frames -> ceil(6/81) == 1
    assert out['staged'] == {'pose': N, 'face': N, 'bg': N, 'mask': N}
    for k in ('pose', 'face', 'bg', 'mask'):
        assert out['inputs'][k] == os.path.join(take, 'in', k)
        assert sorted(os.listdir(out['inputs'][k])) == ['%05d.png' % i for i in range(1, N + 1)]

    wf = cap.calls[0]['wf']
    assert wf['15']['inputs']['folder'] == out['inputs']['bg']
    assert wf['16']['inputs']['folder'] == out['inputs']['mask']
    assert wf['30']['inputs']['character_mask'] == ['17', 0]
    ov = cap.calls[0]['overrides']
    assert ov['11']['folder'] == out['inputs']['pose']
    assert ov['12']['folder'] == out['inputs']['face']
    assert (ov['30']['width'], ov['30']['height']) == (W, H)
    assert ov['40']['seed'] == 7
    assert ov['20']['text'] == 'abel walks'


def test_takes_do_not_overwrite_each_other(plated):
    tmp_path, _cap, _ref = plated
    shot = tmp_path / 'shot'
    _synth_plateset(shot)
    a = WA.animate_from_plateset(str(shot), 'abel')
    b = WA.animate_from_plateset(str(shot), 'abel')
    assert a['take_dir'].endswith('animate_take1')
    assert b['take_dir'].endswith('animate_take2')


def test_chunk_count_is_ceil_frames_over_chunk_frames(plated):
    """82 frames is one frame past a single 81-frame chunk, so it must submit twice —
    and the second submission must carry the continue_motion tail, not restart cold."""
    tmp_path, cap, _ref = plated
    shot = tmp_path / 'long'
    _synth_plateset(shot, n=WA.CHUNK_FRAMES + 1)
    out = WA.animate_from_plateset(str(shot), 'abel')
    assert out['n_chunks'] == 2
    assert len(cap.calls) == 2
    assert '13' not in cap.calls[0]['wf']
    assert cap.calls[1]['wf']['30']['inputs']['continue_motion'] == ['13', 0]
    assert out['staged']['bg'] == WA.CHUNK_FRAMES + 1


def test_plateset_without_faces_falls_back_and_says_so(plated):
    tmp_path, cap, _ref = plated
    shot = tmp_path / 'noface'
    _synth_plateset(shot, face=False)
    seen = []
    out = WA.animate_from_plateset(str(shot), 'abel', log_fn=seen.append)
    assert out['staged']['face'] == 0
    assert cap.calls[0]['overrides']['12']['folder'] == out['inputs']['pose']
    assert any('no face sequence' in m for m in seen)


def test_missing_canon_portrait_is_refused(tmp_path, cap, monkeypatch):
    shot = tmp_path / 'shot'
    _synth_plateset(shot)
    from zyg_workflows import canon_service

    monkeypatch.setattr(canon_service, 'canon_portrait', lambda cid: None)
    with pytest.raises(FileNotFoundError, match='canon portrait'):
        WA.animate_from_plateset(str(shot), 'nobody')


def test_missing_plateset_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match='plateset.json'):
        WA.animate_from_plateset(str(tmp_path), 'abel')
