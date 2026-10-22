# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for zyg_workflows.vfx_landmarks.

MediaPipe is an optional tier here, so every test installs a fake
``mediapipe`` package into ``sys.modules`` and drives the tracker over tiny
synthetic BGR frames. Nothing touches the GPU, the network or the repo's
tracked data directories.
"""

import math
import sys
import types

import numpy as np
import pytest

from zyg_workflows import vfx_landmarks as mod

# ── fake mediapipe ───────────────────────────────────────────────────────────


def _lm(x, y, vis):
    """One landmark: what the module reads off a MediaPipe point."""
    return types.SimpleNamespace(x=x, y=y, z=0.0, visibility=vis)


def _pts(n, x0=0.30, y0=0.20, step=0.0012):
    return [_lm(x0 + step * i, y0 + step * (i % 7) + step * i, 0.5 + 0.01 * (i % 5)) for i in range(n)]


def _cat(name, score):
    return types.SimpleNamespace(category_name=name, score=score)


def _pose_res(n):
    return types.SimpleNamespace(pose_landmarks=[_pts(33) for _ in range(n)])


def _ident():
    """A 4x4 facial transform with a non-zero yaw, pitch and roll."""
    return [[0.9, 0.0, 0.0, 0.0], [0.3, 1.0, 0.0, 0.0], [-0.2, 0.1, 0.95, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _face_res(n, rich=True):
    bs = [[_cat('jawOpen', 0.4), _cat('eyeBlinkLeft', 0.7)] for _ in range(n)] if rich else []
    return types.SimpleNamespace(
        face_landmarks=[_pts(468) for _ in range(n)],
        face_blendshapes=bs,
        facial_transformation_matrixes=[_ident() for _ in range(n)] if rich else [],
    )


def _hand_res(n, handed=True):
    return types.SimpleNamespace(
        hand_landmarks=[_pts(21) for _ in range(n)],
        handedness=[[_cat('Left', 0.9)] for _ in range(n)] if handed else [],
    )


class _Fake:
    """A stand-in landmarker. ``result`` is returned by both entry points."""

    def __init__(self, result=None, detect_exc=None, close_exc=None):
        self.result = result
        self.detect_exc = detect_exc
        self.close_exc = close_exc
        self.closed = 0

    def detect(self, img, ts=None):
        if self.detect_exc is not None:
            raise self.detect_exc
        return self.result

    detect_for_video = detect

    def close(self):
        self.closed += 1
        if self.close_exc is not None:
            raise self.close_exc


class _Maker:
    """Hands out landmarkers per (kind, tier) in the order _build asks."""

    def __init__(self, table):
        self.table = table
        self.seen = []
        self._n = {}

    def __call__(self, kind, kw):
        if kw.get('running_mode') == 'image':
            tier = 'tile'
        else:
            i = self._n.get(kind, 0)
            self._n[kind] = i + 1
            tier = 'weak' if i == 0 else 'strict'
        self.seen.append((kind, tier))
        got = self.table.get((kind, tier), _NOTHING)
        if isinstance(got, BaseException):
            raise got
        return got


_NOTHING = _Fake(result=None)


def _install_mp(monkeypatch, maker):
    mp = types.ModuleType('mediapipe')
    tasks = types.ModuleType('mediapipe.tasks')
    tpy = types.ModuleType('mediapipe.tasks.python')
    vis = types.ModuleType('mediapipe.tasks.python.vision')

    def _base_options(model_asset_path=None, delegate=None):
        return types.SimpleNamespace(path=model_asset_path, delegate=delegate)

    def _opts(**kw):
        return types.SimpleNamespace(kw=kw)

    _base_options.Delegate = types.SimpleNamespace(CPU='cpu')
    tpy.BaseOptions = _base_options
    vis.RunningMode = types.SimpleNamespace(VIDEO='video', IMAGE='image')
    for kind, cname in (('pose', 'Pose'), ('face', 'Face'), ('hand', 'Hand')):

        def _factory(opts, _kind=kind):
            return maker(_kind, opts.kw)

        setattr(vis, f'{cname}Landmarker', types.SimpleNamespace(create_from_options=_factory))
        setattr(vis, f'{cname}LandmarkerOptions', _opts)

    mp.Image = _opts
    mp.ImageFormat = types.SimpleNamespace(SRGB='srgb')
    mp.tasks = tasks
    tasks.python = tpy
    tpy.vision = vis
    for suffix, m in (('', mp), ('.tasks', tasks), ('.tasks.python', tpy), ('.tasks.python.vision', vis)):
        monkeypatch.setitem(sys.modules, 'mediapipe' + suffix, m)
    return mp


@pytest.fixture
def bundles(tmp_path, monkeypatch):
    """A detector dir holding every bundle name the module looks for."""
    monkeypatch.setenv('MEDIAPIPE_DISABLE_GPU', '1')
    det = tmp_path / 'det'
    det.mkdir()
    for names in mod.TASKS.values():
        for n in names:
            (det / n).write_bytes(b'x')
    monkeypatch.setattr(mod, '_DET_DIR', str(det))
    monkeypatch.setattr(mod, '_FALLBACK_DIR', str(tmp_path / 'nope'))
    return det


def _frame(w=640, h=480):
    img = np.zeros((h, w, 3), np.uint8)
    img[h // 4 : h // 2, w // 4 : w // 2] = 200
    return img


def _tracker(monkeypatch, table=None, **kw):
    """Install the fake mediapipe behind *table* and build a tracker over it."""
    _install_mp(monkeypatch, _Maker(table or {}))
    return mod.LandmarkTracker(**kw)


# ── scalar helpers ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('raw', 'want'),
    [(2, 2.0), (-1.5, -1.5), ('3.5', 3.5), ('zz', 0.0), (None, 0.0), (float('nan'), 0.0), (float('inf'), 0.0)],
)
def test_f_coerces_to_finite_float(raw, want):
    assert mod._f(raw) == pytest.approx(want)


def test_angle_right_straight_and_degenerate():
    assert mod._angle((1.0, 0.0), (0.0, 0.0), (0.0, 1.0)) == pytest.approx(90.0)
    assert mod._angle((1.0, 0.0), (0.0, 0.0), (-1.0, 0.0)) == pytest.approx(180.0)
    assert mod._angle((0.0, 0.0), (0.0, 0.0), (0.0, 1.0)) == 0.0
    assert mod._angle((1.0, 0.0), (0.0, 0.0), (0.0, 0.0)) == 0.0
    assert mod._dist((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)


def test_ear_normal_degenerate_and_short():
    pts = [(0.0, 0.0)] * 400
    eye = {33: (0.0, 0.5), 133: (0.4, 0.5), 160: (0.1, 0.6), 144: (0.1, 0.4), 158: (0.3, 0.6), 153: (0.3, 0.4)}
    for i, p in eye.items():
        pts[i] = p
    assert mod._ear(pts, mod.EAR_L) == pytest.approx(0.5)
    assert mod._ear([(0.2, 0.2)] * 400, mod.EAR_L) == 0.0
    assert mod._ear([(0.0, 0.0)], mod.EAR_L) == 0.0


def test_decompose_rt_normal_gimbal_and_garbage():
    yaw, pitch, roll = mod._decompose_rt(_ident())
    assert all(isinstance(v, float) for v in (yaw, pitch, roll))
    assert abs(roll) > 0.0
    y2, p2, r2 = mod._decompose_rt([[0.0] * 4, [0.0, 1.0, -1.0, 0.0], [0.0] * 4, [0.0] * 4])
    assert (y2, r2) == (0.0, 0.0)
    assert p2 == pytest.approx(45.0)
    assert mod._decompose_rt([1.0, 2.0, 3.0]) == (0.0, 0.0, 0.0)


# ── bundle discovery ─────────────────────────────────────────────────────────


def test_task_path_prefers_det_dir_then_fallback(tmp_path, monkeypatch):
    det, fb = tmp_path / 'a', tmp_path / 'b'
    det.mkdir()
    fb.mkdir()
    monkeypatch.setattr(mod, '_DET_DIR', str(det))
    monkeypatch.setattr(mod, '_FALLBACK_DIR', str(fb))
    assert mod._task_path('pose') is None
    (fb / 'pose_landmarker_lite.task').write_bytes(b'x')
    assert mod._task_path('pose') == str(fb / 'pose_landmarker_lite.task')
    (det / 'pose_landmarker_full.task').write_bytes(b'x')
    assert mod._task_path('pose') == str(det / 'pose_landmarker_full.task')


def test_available_reports_every_tier_both_ways(bundles, monkeypatch, tmp_path):
    ok = mod.available()
    assert set(ok) == set(mod.TASKS)
    for kind, rec in ok.items():
        assert rec['ok'] is True
        assert rec['missing'] == ''
        assert rec['path'].startswith(str(bundles)), kind
    monkeypatch.setattr(mod, '_DET_DIR', str(tmp_path / 'gone'))
    bad = mod.available()
    for kind, rec in bad.items():
        assert rec['ok'] is False
        assert rec['path'] == ''
        assert 'no ' in rec['missing'] and kind in rec['missing'] or rec['missing'].endswith('gone')


@pytest.mark.parametrize(('ns', 'nw', 'want'), [(2, 2, 'found'), (1, 0, 'found'), (0, 3, 'weak'), (0, 0, 'none')])
def test_state_tri_state_table(ns, nw, want):
    assert mod.LandmarkTracker._state(ns, nw) == want


def test_tile_boxes_grid_floor_overlap_and_tiny_tiles(monkeypatch):
    assert mod.LandmarkTracker._tile_boxes(200, 200) == []
    boxes = mod.LandmarkTracker._tile_boxes(1000, 800)
    assert boxes
    assert all(0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 800 for x0, y0, x1, y1 in boxes)
    assert boxes[1][0] < boxes[0][2], 'tiles must overlap'
    monkeypatch.setattr(mod, 'TILE_GRIDS', (1, 2))
    monkeypatch.setattr(mod, 'TILE_MIN_PX', 1)
    assert mod.LandmarkTracker._tile_boxes(100, 100) == []


# ── building the tracker ─────────────────────────────────────────────────────


def test_build_without_mediapipe_marks_every_tier_unmeasurable(bundles, monkeypatch):
    for name in ('mediapipe', 'mediapipe.tasks', 'mediapipe.tasks.python'):
        monkeypatch.setitem(sys.modules, name, None)
    seen = []
    tr = mod.LandmarkTracker(log_fn=seen.append)
    assert tr._lm == {}
    assert set(tr._err) == {'pose', 'face', 'hand'}
    assert any('mediapipe unavailable' in m for m in seen)
    _install_mp(monkeypatch, _Maker({}))
    out = tr.step(_frame(), 0)
    for kind in ('pose', 'face', 'hand'):
        assert out[kind]['state'] == 'unmeasurable'
        assert out[kind]['items'] == []
        assert out[kind]['reason']


def test_build_reports_missing_bundles(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, '_DET_DIR', str(tmp_path / 'empty'))
    monkeypatch.setattr(mod, '_FALLBACK_DIR', str(tmp_path / 'empty2'))
    seen = []
    tr = _tracker(monkeypatch, log_fn=seen.append)
    assert tr._lm == {}
    assert all('bundle missing' in v for v in tr._err.values())
    assert len(seen) == 3


def test_build_survives_landmarker_construction_errors(bundles, monkeypatch):
    boom = RuntimeError('no delegate')
    table = {(k, t): boom for k in ('pose', 'face', 'hand') for t in ('weak', 'strict', 'tile')}
    seen = []
    tr = _tracker(monkeypatch, table, log_fn=seen.append)
    assert tr._lm == {}
    assert set(tr._err) == {'pose', 'face', 'hand'}
    assert sum('failed to build' in m for m in seen) == 6
    assert sum('tile unavailable' in m for m in seen) == 3


def test_build_without_tiles_skips_the_image_mode_pass(bundles, monkeypatch):
    maker = _Maker({})
    _install_mp(monkeypatch, maker)
    tr = mod.LandmarkTracker(tiles=False, want=('pose',))
    assert maker.seen == [('pose', 'weak'), ('pose', 'strict')]
    assert tr.tile_hits() == {'pose': 0, 'face': 0, 'hand': 0}


def test_close_swallows_landmarker_errors(bundles, monkeypatch):
    bad = _Fake(close_exc=RuntimeError('already gone'))
    table = {('pose', 'weak'): bad, ('pose', 'strict'): bad, ('pose', 'tile'): bad}
    tr = _tracker(monkeypatch, table, want=('pose',))
    assert tr._lm
    tr.close()
    assert tr._lm == {}
    assert bad.closed == 3


# ── per-frame: pose ──────────────────────────────────────────────────────────


def test_step_pose_strict_derives_the_full_scalar_set(bundles, monkeypatch):
    table = {
        ('pose', 'strict'): _Fake(_pose_res(1)),
        ('pose', 'weak'): _Fake(_pose_res(2)),
        ('pose', 'tile'): _Fake(_pose_res(0)),
    }
    tr = _tracker(monkeypatch, table, want=('pose',))
    out = tr.step(_frame(), 10)
    assert out['ts_ms'] == 10
    pose = out['pose']
    assert pose['state'] == 'found'
    assert (pose['n_strict'], pose['n_weak'], pose['tiled']) == (1, 2, False)
    assert len(pose['items']) == 1
    it = pose['items'][0]
    assert len(it['pts']) == 33
    assert set(it['bbox']) == {'x', 'y', 'w', 'h'}
    for key in ('neck', 'pelvis', 'com', 'wrist_l', 'wrist_r', 'ankle_l', 'ankle_r', 'nose'):
        assert len(it[key]) == 2, key
    assert it['unit'] >= 0.02
    assert isinstance(it['vis_mean'], float)
    # a second frame with a non-increasing timestamp is nudged forward
    assert tr.step(_frame(), 10)['ts_ms'] == 11
    assert tr.step(_frame(), 5)['ts_ms'] == 12


def test_step_pose_weak_only_falls_back_to_the_permissive_pass(bundles, monkeypatch):
    table = {('pose', 'weak'): _Fake(_pose_res(1)), ('pose', 'strict'): _Fake(_pose_res(0))}
    tr = _tracker(monkeypatch, table, want=('pose',), tiles=False)
    pose = tr.step(_frame(), 0)['pose']
    assert pose['state'] == 'weak'
    assert (pose['n_strict'], pose['n_weak']) == (0, 1)
    assert len(pose['items']) == 1


def test_step_pose_escalates_to_tiles_when_whole_frame_is_blind(bundles, monkeypatch):
    table = {
        ('pose', 'weak'): _Fake(_pose_res(0)),
        ('pose', 'strict'): _Fake(_pose_res(0)),
        ('pose', 'tile'): _Fake(_pose_res(1)),
    }
    tr = _tracker(monkeypatch, table, want=('pose',))
    pose = tr.step(_frame(1000, 800), 0)['pose']
    assert pose['tiled'] is True
    assert pose['state'] == 'weak', 'escalation is advisory, never evidence'
    assert pose['n_strict'] == 0
    assert pose['n_weak'] == len(pose['items']) == 1
    assert tr.tile_hits()['pose'] == 1
    assert all(0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0 for p in pose['items'][0]['pts'])


def test_step_marks_a_raising_detector_unmeasurable(bundles, monkeypatch):
    bad = _Fake(detect_exc=ValueError('bad tensor'))
    tr = _tracker(monkeypatch, {('pose', 'weak'): bad, ('pose', 'strict'): bad}, want=('pose',), tiles=False)
    pose = tr.step(_frame(), 0)['pose']
    assert pose['state'] == 'unmeasurable'
    assert 'ValueError' in pose['reason']
    assert pose['items'] == []


def test_run_returns_none_for_a_tier_that_was_never_built(bundles, monkeypatch):
    tr = _tracker(monkeypatch, {('pose', 'weak'): _Fake(_pose_res(1))}, want=('pose',), tiles=False)
    del tr._lm[('pose', 'strict')]
    assert tr._run('pose', 'strict', object()) is None
    assert tr.step(_frame(), 0)['pose']['state'] == 'weak'


# ── per-frame: face ──────────────────────────────────────────────────────────


def test_step_face_strict_reads_blendshapes_and_head_pose(bundles, monkeypatch):
    table = {('face', 'strict'): _Fake(_face_res(1)), ('face', 'weak'): _Fake(_face_res(0))}
    tr = _tracker(monkeypatch, table, want=('face',), tiles=False)
    face = tr.step(_frame(), 0)['face']
    assert face['state'] == 'found'
    it = face['items'][0]
    assert it['has_blendshapes'] == 1.0
    assert it['bs_jaw_open'] == pytest.approx(0.4)
    assert it['bs_blink_l'] == pytest.approx(0.7)
    assert it['blendshapes']['jawOpen'] == pytest.approx(0.4)
    assert it['head_roll_deg'] != 0.0
    for key in ('ear_left', 'ear_right', 'ear_mean', 'ear_asym', 'mar', 'mouth_open_norm', 'mouth_width_norm'):
        assert isinstance(it[key], float), key
    assert it['ear_mean'] == pytest.approx((it['ear_left'] + it['ear_right']) / 2.0)
    assert len(it['centre']) == 2


def test_step_face_without_blendshapes_or_matrices_degrades_quietly(bundles, monkeypatch):
    table = {('face', 'strict'): _Fake(_face_res(0)), ('face', 'weak'): _Fake(_face_res(1, rich=False))}
    tr = _tracker(monkeypatch, table, want=('face',), tiles=False)
    it = tr.step(_frame(), 0)['face']['items'][0]
    assert it['blendshapes'] == {}
    assert it['has_blendshapes'] == 0.0
    assert (it['head_yaw_deg'], it['head_pitch_deg'], it['head_roll_deg']) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize('rich', [True, False])
def test_step_face_escalates_with_and_without_extras(bundles, monkeypatch, rich):
    table = {
        ('face', 'strict'): _Fake(_face_res(0)),
        ('face', 'weak'): _Fake(_face_res(0)),
        ('face', 'tile'): _Fake(_face_res(1, rich=rich)),
    }
    tr = _tracker(monkeypatch, table, want=('face',))
    face = tr.step(_frame(1000, 800), 0)['face']
    assert face['tiled'] is True
    assert face['state'] == 'weak'
    assert face['items'][0]['has_blendshapes'] == (1.0 if rich else 0.0)
    assert tr.tile_hits()['face'] == 1


def test_face_derive_survives_a_truncated_mesh():
    it = mod.LandmarkTracker._face_derive([(0.1, 0.1), (0.2, 0.3)], {}, 1.0, 2.0, 3.0)
    assert it['mar'] == 0.0
    assert it['mouth_width_norm'] == 0.0
    assert it['ear_left'] == 0.0
    assert it['head_yaw_deg'] == 1.0


# ── per-frame: hands ─────────────────────────────────────────────────────────


def test_step_hand_strict_reads_handedness_and_apertures(bundles, monkeypatch):
    table = {('hand', 'strict'): _Fake(_hand_res(2)), ('hand', 'weak'): _Fake(_hand_res(0))}
    tr = _tracker(monkeypatch, table, want=('hand',), tiles=False)
    hand = tr.step(_frame(), 0)['hand']
    assert hand['state'] == 'found'
    assert hand['n_strict'] == 2
    it = hand['items'][0]
    assert it['side'] == 'Left'
    assert len(it['pts']) == 21
    assert len(it['finger_extension']) == 5
    assert it['openness'] == pytest.approx(it['extension_mean'])
    for key in ('palm_len', 'pinch_aperture', 'spread'):
        assert isinstance(it[key], float), key
    for key in ('wrist', 'index_tip', 'thumb_tip'):
        assert len(it[key]) == 2, key


def test_step_hand_without_handedness_leaves_the_side_blank(bundles, monkeypatch):
    table = {('hand', 'strict'): _Fake(_hand_res(0)), ('hand', 'weak'): _Fake(_hand_res(1, handed=False))}
    tr = _tracker(monkeypatch, table, want=('hand',), tiles=False)
    assert tr.step(_frame(), 0)['hand']['items'][0]['side'] == ''


def test_step_hand_escalates_to_tiles(bundles, monkeypatch):
    table = {
        ('hand', 'strict'): _Fake(_hand_res(0)),
        ('hand', 'weak'): _Fake(_hand_res(0)),
        ('hand', 'tile'): _Fake(_hand_res(1, handed=False)),
    }
    tr = _tracker(monkeypatch, table, want=('hand',))
    hand = tr.step(_frame(1000, 800), 0)['hand']
    assert hand['tiled'] is True
    assert hand['items'][0]['side'] == ''
    assert tr.tile_hits()['hand'] == 1


# ── escalation edge cases ────────────────────────────────────────────────────


def test_escalate_declines_when_there_is_no_tile_landmarker(bundles, monkeypatch):
    tr = _tracker(monkeypatch, want=('pose',), tiles=False)
    assert tr._escalate('pose', _frame(1000, 800)) == []
    tr._lm[('pose', 'tile')] = _Fake(_pose_res(1))
    assert tr._escalate('pose', _frame(1000, 800)) == [], 'tiles=False disables escalation'


def test_escalate_declines_on_a_frame_smaller_than_the_detector_floor(bundles, monkeypatch):
    tr = _tracker(monkeypatch, {('pose', 'tile'): _Fake(_pose_res(1))}, want=('pose',))
    assert tr._escalate('pose', _frame(320, 240)) == []
    assert tr.tile_hits()['pose'] == 0


def test_escalate_skips_empty_crops_and_failing_tiles(bundles, monkeypatch):
    oom = _Fake(detect_exc=RuntimeError('tile oom'))
    tr = _tracker(monkeypatch, {('pose', 'tile'): oom}, want=('pose',))
    assert tr._escalate('pose', _frame(1000, 800)) == []
    monkeypatch.setattr(mod.LandmarkTracker, '_tile_boxes', staticmethod(lambda W, H: [(0, 0, 0, 0)]))
    assert tr._escalate('pose', _frame(1000, 800)) == []
    assert tr.tile_hits()['pose'] == 0


def test_escalate_maps_tile_coordinates_back_into_the_full_frame(bundles, monkeypatch):
    tr = _tracker(monkeypatch, {('pose', 'tile'): _Fake(_pose_res(1))}, want=('pose',))
    monkeypatch.setattr(mod.LandmarkTracker, '_tile_boxes', staticmethod(lambda W, H: [(100, 50, 500, 450)]))
    got = tr._escalate('pose', _frame(1000, 800))
    assert len(got) == 1
    pts, vis = got[0]
    assert len(pts) == len(vis) == 33
    assert all(0.1 <= x <= 0.5 and 0.0625 <= y <= 0.5625 for x, y in pts)
    assert tr.tile_hits()['pose'] == 1


def test_step_runs_every_requested_tier_at_once(bundles, monkeypatch):
    table = {
        ('pose', 'strict'): _Fake(_pose_res(1)),
        ('face', 'strict'): _Fake(_face_res(1)),
        ('hand', 'strict'): _Fake(_hand_res(1)),
    }
    tr = _tracker(monkeypatch, table, conf_weak=0.1, conf_strict=0.9, tiles=False)
    out = tr.step(_frame(), 0)
    assert set(out) == {'ts_ms', 'pose', 'face', 'hand'}
    assert all(out[k]['state'] == 'found' for k in ('pose', 'face', 'hand'))
    assert (tr.conf_weak, tr.conf_strict) == (0.1, 0.9)


# ── sequence level ───────────────────────────────────────────────────────────

_POINTS = {'wrist_l': 0.10, 'wrist_r': 0.30, 'ankle_l': 0.12, 'ankle_r': 0.28, 'nose': 0.20, 'com': 0.21}
_ANGLES = ('elbow_l_deg', 'elbow_r_deg', 'knee_l_deg', 'knee_r_deg', 'hip_l_deg', 'hip_r_deg')


def _pose_item(dx=0.0, dy=0.0, bend=0.0, unit=0.1):
    item = {'unit': unit, 'torso_lean_deg': bend / 2.0, 'pelvis': [0.22 + dx, 0.42 + dy]}
    item.update({k: [x + dx, 0.2 + x + dy] for k, x in _POINTS.items()})
    item.update({k: 90.0 + bend for k in _ANGLES})
    item.update(shoulder_l_deg=40.0 + bend, shoulder_r_deg=40.0)
    return item


def _frame_rec(item=None):
    return {'pose': {'state': 'found' if item else 'none', 'items': [item] if item else []}}


def test_velocities_sample_unique_cels_and_derive_accelerations():
    held = _pose_item(dx=0.05, bend=10.0)
    seq = [_frame_rec(_pose_item()), _frame_rec(_pose_item()), _frame_rec(held), _frame_rec(held)]
    seq.append(_frame_rec(_pose_item(dx=0.20, bend=40.0)))
    out = mod.velocities(seq, [0, 2, 4], 24.0)
    assert [r['frame'] for r in out] == [0, 2, 4]
    assert all(r['has_pose'] for r in out)
    assert not any(k.startswith('v_') for k in out[0]), 'the first cel has no predecessor'
    assert out[1]['v_wrist_l'] > 0.0
    assert out[1]['vx_wrist_l'] > 0.0
    assert out[1]['vy_wrist_l'] == 0.0
    assert out[1]['d_elbow_l_deg'] > 0.0
    assert out[1]['d_torso_lean_deg'] > 0.0
    assert not any(k.startswith('a_') for k in out[1]), 'acceleration needs two velocities'
    assert out[2]['a_wrist_l'] > 0.0, 'the move speeds up between cel 2 and cel 4'
    assert set(out[1]) >= {f'v_{k}' for k in ('wrist_l', 'wrist_r', 'ankle_l', 'ankle_r', 'nose', 'com', 'pelvis')}


def test_velocities_tolerate_missing_frames_poseless_cels_and_odd_keys():
    odd = _pose_item(dx=0.05)
    odd['wrist_l'] = 'not a point'
    odd.pop('nose')
    odd.pop('elbow_l_deg')
    seq = [_frame_rec(_pose_item()), {'pose': None}, _frame_rec(odd)]
    out = mod.velocities(seq, [-1, 0, 1, 2, 99], 12.0)
    assert [r['frame'] for r in out] == [-1, 0, 1, 2, 99]
    assert [r['has_pose'] for r in out] == [False, True, False, True, False]
    assert 'v_wrist_l' not in out[3], 'a non-list point is skipped, not crashed on'
    assert 'v_nose' not in out[3]
    assert 'd_elbow_l_deg' not in out[3]
    assert out[3]['v_wrist_r'] > 0.0


def test_velocities_survive_a_zero_fps_and_an_empty_plan():
    seq = [_frame_rec(_pose_item()), _frame_rec(_pose_item(dx=0.1))]
    out = mod.velocities(seq, [0, 1], 0.0)
    assert math.isfinite(out[1]['v_wrist_l'])
    assert mod.velocities(seq, [], 24.0) == []


def test_describe_lists_the_emitted_scalars():
    d = mod.describe()
    assert set(d) == {'pose', 'face', 'hand', 'velocity'}
    assert all(isinstance(v, list) and v for v in d.values())
    assert 'torso_lean_deg' in d['pose']
    assert 'ear_mean' in d['face']
    assert 'pinch_aperture' in d['hand']
    assert 'a_wrist_l' in d['velocity']
    item = mod.LandmarkTracker._pose_derive([(0.1 * i, 0.02 * i) for i in range(33)], [0.5] * 33, 640, 480)
    for name in d['pose']:
        assert name in item, name
