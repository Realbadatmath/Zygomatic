# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers ``pose_track.build_track`` was split into.

``jitter3``, ``jitter2``, ``rmse3`` and ``rmse2`` used to be closures inside the
302-line ``build_track``, and ``_stack`` a fifth; ``frame_ledger``,
``shape_lock`` and ``reproj_error`` were inline blocks. None of them could be
called on a hand-made array before, so the ledger's four states and the
reprojection self-check are tested here for the first time. No GPU and no
services: every helper below is arithmetic over numpy arrays and dicts.
"""

from __future__ import annotations

import numpy as np
import pytest

from zyg_workflows.geom.pose_track.constants import FOUND, NOT_DETECTABLE, NOT_FOUND, UNMEASURABLE
from zyg_workflows.geom.pose_track.track_build import (
    FitRun,
    Ledger,
    RawSeries,
    Smoothed,
    TrackCtx,
    frame_ledger,
    jitter2,
    jitter3,
    reproj_error,
    rmse2,
    rmse3,
    shape_lock,
    stack_series,
    track_dirs,
    track_metrics,
)


def _ctx(frames, res, *, subject='', boxes=None, sub_info=None, **over):
    """A TrackCtx carrying only what the pure stages read."""
    ctx = TrackCtx(
        clip='/nonexistent/clip.mp4',
        out_dir='/nonexistent/out',
        subject=subject,
        fps=17,
        smooth='savgol',
        window=9,
        dirs=track_dirs('/nonexistent/out'),
        log=lambda *_a: None,
        **over,
    )
    ctx.frames = list(frames)
    ctx.fit = FitRun(
        res=res,
        meta={},
        boxes=dict(boxes or {}),
        smasks={},
        sub_info=dict(sub_info or {'ok': False, 'reason': 'none'}),
        dec_ok=False,
        dec_why='pymomentum absent',
    )
    return ctx


def _rec(i):
    """One detected frame's record, with .npy side-cars left out."""
    return {
        'detected': True,
        'bbox': [0.0, 0.0, 10.0, 20.0],
        'pred_keypoints_3d': [[float(i), 1.0, 2.0]],
        'pred_keypoints_2d': [[float(i), 3.0]],
        'pred_cam_t': [0.0, 0.0, 4.0],
        'focal_length': 900.0 + i,
        'global_rot': [0.0, 0.0, 0.0],
        'shape_params': [float(i), 0.0],
        'scale_params': [1.0, 1.0],
        'body_pose_params': [0.0] * 7,
    }


# ---------------------------------------------------------------- track_dirs


def test_track_dirs_names_the_four_subdirectories():
    """Pure path arithmetic — nothing is created."""
    d = track_dirs('/tmp/zyg-nonexistent')
    assert d.frames.endswith('/frames')
    assert d.arrays.endswith('/arrays')
    assert d.sam3_masks.endswith('/_sam3_masks')
    assert d.masks.endswith('/masks')
    assert len({d.frames, d.arrays, d.sam3_masks, d.masks}) == 4


# ---------------------------------------------------------------- frame_ledger


def test_frame_ledger_sorts_every_frame_into_one_of_the_four_states():
    """Missing, errored, undetected and fitted — one state per frame, in order."""
    frames = ['f0', 'f1', 'f2', 'f3', 'f4']
    res = {'f0': _rec(0), 'f1': {'error': 'worker blew up'}, 'f2': {'detected': False}, 'f4': _rec(4)}
    led = frame_ledger(_ctx(frames, res))
    assert led.ledger == [FOUND, UNMEASURABLE, NOT_FOUND, UNMEASURABLE, FOUND]
    assert led.idx == [0, 4]
    assert [r is None for r in led.recs] == [False, True, True, True, False]


def test_frame_ledger_calls_an_unboxed_miss_not_detectable():
    """With a subject, a frame SAM 3 never boxed is a different failure."""
    frames = ['f0', 'f1', 'f2']
    res = {'f0': {'detected': False}, 'f1': {'detected': False}, 'f2': _rec(2)}
    boxes = {'f1': [0, 0, 1, 1], 'f2': [0, 0, 1, 1]}
    led = frame_ledger(_ctx(frames, res, subject='the woman in red', boxes=boxes))
    assert led.ledger == [NOT_DETECTABLE, NOT_FOUND, FOUND]


def test_frame_ledger_records_whether_each_frame_was_steered():
    """``boxed`` false is the flag that says SAM 3D Body ran whole-image."""
    frames = ['f0', 'f1', 'f2']
    res = {f: _rec(i) for i, f in enumerate(frames)}
    led = frame_ledger(
        _ctx(
            frames,
            res,
            subject='the woman in red',
            boxes={'f0': [0, 0, 1, 1], 'f2': [0, 0, 1, 1]},
            sub_info={'ok': True, 'box_source': {'f0': 'sam3', 'f2': 'held'}},
        )
    )
    assert led.boxed == [True, False, True]
    assert led.box_src == ['sam3', 'none', 'held']


def test_frame_ledger_without_a_subject_says_whole_image():
    """No --subject is not a failure, and every frame is honestly whole-image."""
    frames = ['f0']
    led = frame_ledger(_ctx(frames, {'f0': _rec(0)}))
    assert led.box_src == ['whole_image']
    assert led.boxed == [False]


def test_frame_ledger_refuses_a_track_with_no_fitted_frame():
    """Nothing fitted means there is nothing to track, and it says so."""
    frames = ['f0', 'f1']
    res = {'f0': {'detected': False}, 'f1': {'error': 'boom'}}
    with pytest.raises(RuntimeError, match='nothing to track'):
        frame_ledger(_ctx(frames, res))


# ---------------------------------------------------------------- stack_series


def test_stack_series_stacks_only_the_fitted_frames():
    """The gap frames are skipped, so every array is (len(idx), ...)."""
    frames = ['f0', 'f1', 'f2']
    res = {'f0': _rec(0), 'f1': {'detected': False}, 'f2': _rec(2)}
    led = frame_ledger(_ctx(frames, res))
    led = Ledger(ledger=led.ledger, recs=led.recs, boxed=led.boxed, box_src=led.box_src, idx=led.idx)
    raw = _stack_without_npy(led)
    assert raw.kp3.shape == (2, 1, 3)
    assert raw.kp3[:, 0, 0].tolist() == [0.0, 2.0]
    assert raw.focal.tolist() == [900.0, 902.0]
    assert raw.kp3.dtype == np.float64


def _stack_without_npy(led):
    """``stack_series`` minus the three .npy loads, which need a worker's files."""
    recs, idx = led.recs, led.idx
    return RawSeries(
        kp3=np.array([np.asarray(recs[i]['pred_keypoints_3d'], np.float64) for i in idx]),
        kp2=np.array([np.asarray(recs[i]['pred_keypoints_2d'], np.float64) for i in idx]),
        cam_t=np.array([np.asarray(recs[i]['pred_cam_t'], np.float64) for i in idx]),
        focal=np.array([float(recs[i]['focal_length']) for i in idx]),
        grot=np.array([np.asarray(recs[i]['global_rot'], np.float64) for i in idx]),
        shape=np.array([np.asarray(recs[i]['shape_params'], np.float64) for i in idx]),
        scale=np.array([np.asarray(recs[i]['scale_params'], np.float64) for i in idx]),
        body_pose=np.array([np.asarray(recs[i]['body_pose_params'], np.float64) for i in idx]),
        verts=np.zeros((len(idx), 4, 3), np.float32),
        jrot=np.broadcast_to(np.eye(3), (len(idx), 2, 3, 3)).copy(),
        jcoord=np.zeros((len(idx), 2, 3), np.float64),
    )


def test_stack_series_loads_the_npy_side_cars(tmp_path):
    """The three big arrays come off disk, and keep the worker's dtypes."""
    verts = np.arange(6, dtype=np.float32).reshape(2, 3)
    rots = np.broadcast_to(np.eye(3), (2, 3, 3)).copy()
    coords = np.arange(6, dtype=np.float64).reshape(2, 3)
    paths = {}
    for name, arr in (('pred_vertices', verts), ('pred_global_rots', rots), ('pred_joint_coords', coords)):
        p = tmp_path / f'{name}.npy'
        np.save(p, arr)
        paths[name] = str(p)
    rec = _rec(0)
    rec['npy'] = paths
    led = Ledger(ledger=[FOUND], recs=[rec], boxed=[False], box_src=['whole_image'], idx=[0])
    raw = stack_series(led)
    assert raw.verts.shape == (1, 2, 3) and raw.verts.dtype == np.float32
    assert raw.jrot.shape == (1, 2, 3, 3) and raw.jrot.dtype == np.float64
    assert raw.jcoord.shape == (1, 2, 3)


# ---------------------------------------------------------------- shape_lock


def test_shape_lock_takes_the_median_and_the_drift_from_it():
    """Recorded, not applied: the median identity plus how far frames stray."""
    raw = _stack_without_npy(Ledger(ledger=[], recs=[_rec(0), _rec(2), _rec(10)], boxed=[], box_src=[], idx=[0, 1, 2]))
    lock = shape_lock(raw)
    assert lock.med.tolist() == [2.0, 0.0]  # median of 0, 2, 10
    assert lock.scale_med.tolist() == [1.0, 1.0]
    assert lock.dev == pytest.approx((2 + 0 + 8) / 6.0)
    assert lock.dev_max == pytest.approx(8.0)
    assert lock.std > 0.0


def test_shape_lock_on_a_rock_steady_track_reports_zero_drift():
    """One frame, or an unvarying identity, drifts by nothing at all."""
    raw = _stack_without_npy(Ledger(ledger=[], recs=[_rec(3), _rec(3)], boxed=[], box_src=[], idx=[0, 1]))
    lock = shape_lock(raw)
    assert (lock.dev, lock.dev_max, lock.std) == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------- jitter / rmse


def test_jitter3_is_the_mean_step_in_millimetres():
    """A 1 mm-per-frame slide over three frames averages 1 mm of jitter."""
    a = np.array([[[0.0, 0.0, 0.0]], [[0.001, 0.0, 0.0]], [[0.002, 0.0, 0.0]]])
    assert jitter3(a) == pytest.approx(1.0)


def test_jitter2_is_the_mean_step_in_pixels():
    """The 2D twin, in the estimator's own pixel units — no 1000x."""
    a = np.array([[[0.0, 0.0]], [[3.0, 4.0]]])
    assert jitter2(a) == pytest.approx(5.0)


@pytest.mark.parametrize('fn', [jitter3, jitter2])
def test_jitter_of_a_single_frame_is_none_not_zero(fn):
    """One frame has no frame-to-frame step, and None says so honestly."""
    assert fn(np.zeros((1, 4, 3))) is None


def test_rmse3_and_rmse2_are_mean_euclidean_distance():
    """Same arithmetic, two units: mm for 3D, px for 2D."""
    a = np.zeros((2, 1, 3))
    b = np.zeros((2, 1, 3))
    b[:, 0, 0] = 0.003
    assert rmse3(a, b) == pytest.approx(3.0)
    c = np.zeros((2, 1, 2))
    d = np.zeros((2, 1, 2))
    d[:, 0, 1] = 4.0
    assert rmse2(c, d) == pytest.approx(4.0)


def test_rmse_of_a_series_against_itself_is_zero():
    """The degenerate null: a perfect prediction scores 0."""
    a = np.arange(24, dtype=np.float64).reshape(2, 4, 3)
    assert rmse3(a, a) == 0.0
    assert rmse2(a[:, :, :2], a[:, :, :2]) == 0.0


# ---------------------------------------------------------------- track_metrics


def test_track_metrics_scores_the_two_nulls_a_still_track_cannot_beat():
    """A track that never moves ties both nulls at 0 — which is the point."""
    kp3 = np.zeros((4, 2, 3))
    kp2 = np.zeros((4, 2, 2))
    ctx = _ctx(['f0'], {'f0': _rec(0)})
    ctx.raw = RawSeries(kp3, kp2, None, None, None, None, None, None, None, None, None)
    ctx.sm = Smoothed(kp3=kp3, kp2=kp2, cam=None, grot=None, jrv=None, verts=None, jco=None)
    m = track_metrics(ctx)
    assert m['frames_fitted'] == 4
    assert m['motion_mm_total'] == 0.0
    assert m['null_held_first_frame'] == {'joint_err_mm': 0.0, 'kp2_err_px': 0.0}
    assert m['null_two_pose_lerp'] == {'joint_err_mm': 0.0, 'kp2_err_px': 0.0}
    assert (m['smoothing'], m['window']) == ('savgol', 9)


def test_track_metrics_lerp_null_beats_the_held_null_on_a_straight_slide():
    """A constant-velocity slide IS the lerp, so null 2 scores 0 and null 1 does not."""
    n = 5
    kp3 = np.zeros((n, 1, 3))
    kp3[:, 0, 0] = np.linspace(0.0, 0.004, n)
    kp2 = np.zeros((n, 1, 2))
    kp2[:, 0, 0] = np.linspace(0.0, 4.0, n)
    ctx = _ctx(['f0'], {'f0': _rec(0)})
    ctx.raw = RawSeries(kp3, kp2, None, None, None, None, None, None, None, None, None)
    ctx.sm = Smoothed(kp3=kp3, kp2=kp2, cam=None, grot=None, jrv=None, verts=None, jco=None)
    m = track_metrics(ctx)
    assert m['null_two_pose_lerp']['joint_err_mm'] == pytest.approx(0.0)
    assert m['null_held_first_frame']['joint_err_mm'] > 1.0
    assert m['motion_mm_total'] == pytest.approx(4.0)
    assert m['jitter_mm_raw'] == pytest.approx(1.0)


# ---------------------------------------------------------------- reproj_error


def test_reproj_error_is_zero_when_the_pinhole_model_agrees():
    """2D keypoints built with the documented model must reproduce exactly."""
    W, H = 640, 480
    kp3 = np.array([[[0.1, -0.2, 0.0], [0.0, 0.0, 0.0]]])
    cam_t = np.array([[0.0, 0.0, 5.0]])
    focal = np.array([900.0])
    p = kp3[0] + cam_t[0]
    kp2 = np.stack([focal[0] * p[:, 0] / p[:, 2] + W / 2.0, focal[0] * p[:, 1] / p[:, 2] + H / 2.0], -1)[None]
    raw = RawSeries(kp3, kp2, cam_t, focal, None, None, None, None, None, None, None)
    assert reproj_error(raw, W, H) == pytest.approx(0.0)


def test_reproj_error_reports_the_worst_keypoint_not_the_mean():
    """One keypoint off by 7 px makes the whole frame's self-check 7 px."""
    W, H = 640, 480
    kp3 = np.array([[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]])
    cam_t = np.array([[0.0, 0.0, 5.0]])
    focal = np.array([900.0])
    kp2 = np.array([[[W / 2.0, H / 2.0], [W / 2.0 + 7.0, H / 2.0]]])
    raw = RawSeries(kp3, kp2, cam_t, focal, None, None, None, None, None, None, None)
    assert reproj_error(raw, W, H) == pytest.approx(7.0)
