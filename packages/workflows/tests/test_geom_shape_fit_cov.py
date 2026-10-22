# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`geom.shape_fit` — the bounded body-shape solve, exercised without torch.

torch is not installed in this repo's venv and will not be on the CI runner, and every
torch-using function in `shape_fit` imports it INSIDE its body. So a numpy-backed
stand-in goes into `sys.modules` for the duration of each test that needs it (via
`monkeypatch.setitem`, so nothing leaks into the rest of the suite). The shim computes
the FORWARD math for real — Rodrigues, the pinhole projection, the bilinear
distance-field sample, smooth-L1 — so the assertions are about the module's own
arithmetic, not about a mock agreeing with itself. What it has no business having is
autograd: `backward()` leaves zero gradients, so the optimiser loops in
`_solve_nuisance` are proved to RUN and to keep their contract (f pinned, every arm
scored alike), never to descend.
"""

import contextlib
import operator
import os
import sys
import types

import cv2
import numpy as np
import pytest

from zyg_workflows.geom import anny_animate as AA
from zyg_workflows.geom import anny_fit as AF
from zyg_workflows.geom import keypoints as K
from zyg_workflows.geom import shape_fit as SF
from zyg_workflows.geom import shape_fit_stages as ST


# ── the torch stand-in ───────────────────────────────────────────────────────
def _arr(x):
    return x.a if isinstance(x, _T) else np.asarray(x)


def _zero(x):
    return np.zeros_like(_arr(x), dtype=np.float64)


class _T:
    """A numpy array wearing the slice of torch.Tensor's surface `shape_fit` uses."""

    def __init__(self, a, requires_grad=False):
        self.a = np.asarray(a)
        self.requires_grad = bool(requires_grad)
        self._grad = _zero(self.a)

    grad = property(lambda s: s._grad)
    dtype = property(lambda s: s.a.dtype)
    T = property(lambda s: _T(s.a.T))


for _n, _fn in (
    ('backward', lambda s: setattr(s, '_grad', _zero(s))),
    ('detach', lambda s: _T(s.a)),
    ('numpy', lambda s: s.a),
    ('to', lambda s, dtype=None, **_k: s if dtype is None else _T(s.a.astype(dtype))),
    ('clamp', lambda s, min=None, max=None: s if (min, max) == (None, None) else _T(np.clip(s.a, min, max))),
    ('mean', lambda s: _T(s.a.mean())),
    ('__array__', lambda s, dtype=None, copy=None: s.a if dtype is None else s.a.astype(dtype)),
    ('__float__', lambda s: float(s.a)),
    ('__len__', lambda s: len(s.a)),
    ('__neg__', lambda s: _T(-s.a)),
    ('__getitem__', lambda s, k: _T(s.a[k])),
    ('__setitem__', lambda s, k, v: s.a.__setitem__(k, _arr(v))),
):
    setattr(_T, _n, _fn)

for _n in ('add', 'sub', 'mul', 'truediv', 'matmul'):
    _op = getattr(operator, _n)
    setattr(_T, '__%s__' % _n, (lambda f: lambda s, o: _T(f(s.a, _arr(o))))(_op))
    setattr(_T, '__r%s__' % _n, (lambda f: lambda s, o: _T(f(_arr(o), s.a)))(_op))


class _Adam:
    """Zero-gradient Adam: the step is real, the descent is not (the shim has no graph)."""

    def __init__(self, params, lr=1e-3):
        self.params, self.lr, self.steps = list(params), lr, 0

    def zero_grad(self):
        for p in self.params:
            p._grad = _zero(p)

    def step(self):
        self.steps += 1
        for p in self.params:
            p.a = p.a - self.lr * p.grad


def _smooth_l1(a, b, beta=1.0):
    d = np.abs(_arr(a).astype(np.float64) - _arr(b).astype(np.float64))
    return _T(np.where(d < beta, 0.5 * d * d / beta, d - 0.5 * beta).mean())


def _grid_sample(inp, grid, mode='bilinear', padding_mode='zeros', align_corners=False):
    """Bilinear sample of a (1,1,H,W) field at a (1,1,N,2) grid, border-padded."""
    im, g = _arr(inp)[0, 0].astype(np.float64), _arr(grid)[0, 0].astype(np.float64)
    h, w = im.shape
    x = np.clip((g[:, 0] + 1) * 0.5 * (w - 1), 0, w - 1)
    y = np.clip((g[:, 1] + 1) * 0.5 * (h - 1), 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[None], (y - y0)[None]
    corners = np.stack([im[y0, x0], im[y0, x1], im[y1, x0], im[y1, x1]])
    weights = np.concatenate([(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy])
    return _T((corners * weights).sum(axis=0)[None, None, None])


def _np_rotmat(axis_angle):
    """Rodrigues in numpy — the same formula `anny_fit._rotmat` writes in torch."""
    v = np.asarray(_arr(axis_angle), np.float64)
    single = v.ndim == 1
    v = v.reshape(-1, 3)
    th = np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-8)
    k = v / th
    km = np.zeros(v.shape[:-1] + (3, 3))
    km[..., 0, 1], km[..., 0, 2] = -k[..., 2], k[..., 1]
    km[..., 1, 0], km[..., 1, 2] = k[..., 2], -k[..., 0]
    km[..., 2, 0], km[..., 2, 1] = -k[..., 1], k[..., 0]
    s, c = np.sin(th)[..., None], np.cos(th)[..., None]
    r = np.eye(3) + s * km + (1 - c) * (km @ km)
    return _T(r[0] if single else r)


def _make_torch():
    ns = types.SimpleNamespace
    t = types.ModuleType('torch')
    t.float32, t.float64, t.Tensor, t.no_grad = np.float32, np.float64, _T, contextlib.nullcontext
    t.tensor = lambda data, dtype=None, requires_grad=False: _T(
        np.asarray(data, dtype if dtype is not None else np.float64), requires_grad
    )
    t.sigmoid = lambda x: _T(1.0 / (1.0 + np.exp(-_arr(x).astype(np.float64))))
    t.zeros = lambda shape, dtype=np.float64: _T(np.zeros(shape, dtype))
    t.zeros_like = lambda x: _T(_zero(x))
    t.eye = lambda n, dtype=np.float64: _T(np.eye(n, dtype=dtype))
    t.stack = lambda xs, dim=0: _T(np.stack([_arr(x) for x in xs], axis=dim))
    t.cat = lambda xs, dim=0: _T(np.concatenate([_arr(x) for x in xs], axis=dim))
    t.manual_seed = lambda _s: None
    t.linalg = ns(norm=lambda x, dim=None, keepdim=False: _T(np.linalg.norm(_arr(x), axis=dim, keepdims=keepdim)))
    t.optim = ns(Adam=_Adam)
    t.nn = ns(functional=ns(smooth_l1_loss=_smooth_l1, grid_sample=_grid_sample))
    return t


@pytest.fixture
def torch_stub(monkeypatch):
    """Install the stand-in for this test's lifetime and nothing longer."""
    mod = _make_torch()
    monkeypatch.setitem(sys.modules, 'torch', mod)
    monkeypatch.setattr(AF, '_rotmat', _np_rotmat)
    monkeypatch.setattr(AF, '_pose44', lambda _pose: _T(np.tile(np.eye(4), (1, 2, 1, 1))))
    return mod


# ── stand-ins for the body model and one cell ────────────────────────────────
class _Model:
    """A fixed cloud of vertices with quad faces, ignoring the body it is handed."""

    def __init__(self, verts=None, faces=None):
        if verts is None:
            a = np.linspace(0, 2 * np.pi, 400, endpoint=False)
            verts = np.stack([20 * np.cos(a), np.zeros_like(a), -20 - 20 * np.sin(a)], -1)
        self.verts = np.asarray(verts, np.float64)
        self.faces = _T(np.asarray([[0, 1, 2, 3]] if faces is None else faces, np.int32))
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return {'vertices': _T(self.verts[None])}


def _out(model):
    return {'vertices': _T(model.verts[None])}


def _regressor(out):
    """The first four vertices stand in for a keypoint regressor's output."""
    return _T(_arr(out['vertices'])[:, :4])


def _cam(f=1.0, tz=1.0, cx=0.0, cy=0.0):
    return _T(np.array([f, tz, cx, cy]))


def _g0(yaw=0.0):
    return _T(np.array([0.0, 0.0, yaw]))


def _box_mask(box=(16, 48, 16, 48)):
    m = np.zeros((64, 64), np.uint8)
    y0, y1, x0, x1 = box
    m[y0:y1, x0:x1] = 255
    return m


def _cell(name='cell_00', sdf=None, mask=None, y_limit=None):
    sdf_t = None if sdf is None else _T(np.asarray(sdf, np.float32))
    base = dict(cell=name, W=64, H=64, cam0=[1.0, 1.0, 0.0, 0.0], gaa0=[0.0, 0.0, 0.0])
    return dict(base, tgt_t=_T(np.zeros((4, 2))), mask=mask, sdf_t=sdf_t, y_limit=y_limit)


def _arm(**kw):
    return SF._Arm('fit', _Model(), {'muscle': 0.5, 'age': 30.0}, {'measure-waist-circ-incr': 0.1}, None, **kw)


# ── bounded parameters ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    'declared,bound,rng,want',
    [
        (0.5, 0.3, (0.0, 1.0), (-0.3, 0.3)),  # room on both sides
        (0.1, 0.3, (0.0, 1.0), (-0.1, 0.3)),  # the floor bites
        (0.95, 0.3, (0.0, 1.0), (-0.3, 0.05)),  # the ceiling bites
        (0.0, 0.8, (-1.0, 1.0), (-0.8, 0.8)),
        (1.4, 0.3, (0.0, 1.0), (0.0, 0.0)),  # declared outside its own range: frozen
        (-2.0, 0.8, (-1.0, 1.0), (0.0, 0.0)),
    ],
)
def test_the_delta_interval_is_the_bound_clipped_to_the_axis_range(declared, bound, rng, want):
    assert SF._bounds(declared, bound, rng) == pytest.approx(want)


def test_u0_is_the_raw_value_whose_delta_is_zero(torch_stub):
    for lo, hi in ((-0.3, 0.3), (-0.1, 0.3), (-0.3, 0.05), (-0.8, 0.8)):
        assert float(SF._delta(_T(SF._u0(lo, hi)), lo, hi)) == pytest.approx(0.0, abs=2e-4)
    assert SF._u0(0.0, 0.0) == 0.0  # a frozen interval has no raw value to find
    assert SF._u0(0.3, -0.3) == 0.0


def test_delta_is_monotonic_and_stays_inside_its_interval(torch_stub):
    lo, hi = -0.3, 0.3
    got = [float(SF._delta(_T(u), lo, hi)) for u in (-20.0, -1.0, 0.0, 1.0, 20.0)]
    assert got == sorted(got)
    assert lo <= got[0] and got[-1] <= hi


# ── the distance field ───────────────────────────────────────────────────────
def test_the_sdf_is_negative_inside_zero_on_the_edge_and_positive_outside():
    sdf = SF._sdf(_box_mask())
    assert sdf.shape == (32, 32)  # sampled at half resolution
    assert sdf[16, 16] < -8  # deep inside the box
    assert sdf[2, 2] > 8  # far outside it
    assert abs(sdf[8, 16]) <= SF.SDF_SCALE  # on the boundary
    assert SF._sdf(_box_mask(), y_limit=24)[16, 16] > 0  # the lower half of the box is gone


def test_a_mask_with_nothing_left_to_measure_has_no_distance_field():
    thin = np.zeros((4, 4), np.uint8)
    thin[1, 1] = 255  # dropped by the nearest-neighbour downsample
    assert SF._sdf(np.zeros((32, 32), np.uint8)) is None
    assert SF._sdf(_box_mask(), y_limit=-5) is None  # the draw limit cut everything
    assert SF._sdf(thin) is None


# ── per-cell evidence ────────────────────────────────────────────────────────
_SEEN = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder')


def _landmarks(visible=_SEEN, dx=0.0):
    b = np.zeros((33, 3), np.float32)
    for i, n in enumerate(visible):
        b[K.P[n]] = (8 + 4 * i + dx, 8 + 2 * i, 0.9)
    return {'size': (64, 64), 'body_landmarks': b.tolist()}


def test_a_cell_contributes_its_confident_on_canvas_keypoints(tmp_path):
    cv2.imwrite(str(tmp_path / 'regions.png'), _box_mask())
    tgt, labels, mask, sdf, y_limit = SF._cell_evidence(str(tmp_path), {'fit_mode': 'full'}, _landmarks())
    assert tgt.shape == (7, 2) and labels[0] == 'nose'
    assert mask.max() == 1 and sdf is not None
    assert y_limit is None  # a full-mode fit is not cropped


def test_an_upper_mode_cell_is_cropped_at_its_draw_limit(tmp_path):
    cv2.imwrite(str(tmp_path / 'regions.png'), _box_mask())
    fit = {'fit_mode': 'upper', 'draw_limit_y': 24}
    _tgt, _labels, _mask, sdf, y_limit = SF._cell_evidence(str(tmp_path), fit, _landmarks())
    assert y_limit == 24
    assert sdf[16, 16] > 0  # the cut reached the distance field


def test_a_cell_with_no_mask_on_disk_still_carries_its_keypoints(tmp_path):
    tgt, _labels, mask, sdf, _y = SF._cell_evidence(str(tmp_path), {'fit_mode': 'full'}, _landmarks())
    assert len(tgt) == 7
    assert mask is None and sdf is None


def test_too_few_usable_keypoints_is_no_evidence_at_all(tmp_path):
    full = {'fit_mode': 'full'}
    assert SF._cell_evidence(str(tmp_path), full, _landmarks(visible=_SEEN[:3])) is None
    assert SF._cell_evidence(str(tmp_path), full, _landmarks(dx=500.0)) is None  # all off canvas


# ── the outline correspondence ───────────────────────────────────────────────
def test_the_outline_keeps_the_farthest_point_of_each_angular_bin():
    a = np.linspace(0, 2 * np.pi, 36, endpoint=False)
    near = np.stack([np.cos(a), np.sin(a)], -1)
    xy = np.concatenate([near, 3 * near]).astype(np.float32)
    idx = SF._outline_idx(xy, n_bins=36)
    d = xy - xy.mean(axis=0)
    r = np.hypot(d[:, 0], d[:, 1])
    bins = np.clip(((np.arctan2(d[:, 1], d[:, 0]) + np.pi) / (2 * np.pi) * 36).astype(np.int32), 0, 35)
    assert len(idx) == len(set(bins[idx].tolist()))  # one winner per occupied bin
    for i in idx:
        assert r[i] == pytest.approx(r[bins == bins[i]].max())  # and it is the farthest in it
    assert sum(1 for i in idx if i >= 36) >= 30  # the far ring wins almost everywhere
    sparse = SF._outline_idx(np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]], np.float32), n_bins=8)
    assert len(sparse) < 8 and (sparse >= 0).all()  # empty bins are dropped, never reported as -1


# ── projection and sampling ──────────────────────────────────────────────────
def test_the_pinhole_projection_divides_by_depth_and_flips_z(torch_stub):
    kp3 = _T(np.array([[2.0, 0.0, -4.0], [0.0, 3.0, 0.0]]))
    xy = _arr(SF._project(kp3, _g0(), _cam(f=10.0, cx=100.0, cy=50.0), _np_rotmat))
    assert xy[0] == pytest.approx([2.0 * 10 / 1 + 100, 4.0 * 10 / 1 + 50])
    assert xy[1] == pytest.approx([100.0, 50.0])  # depth is y, so x=z=0 lands on the centre
    behind = _arr(SF._project(_T(np.array([[1.0, -50.0, 0.0]])), _g0(), _cam(tz=0.0), _np_rotmat))
    assert behind[0, 0] == pytest.approx(1.0 / 0.25)  # a body behind the camera cannot explode
    side = _T(np.array([[1.0, 0.0, 0.0]]))
    assert _arr(SF._project(side, _g0(), _cam(), _np_rotmat))[0, 0] == pytest.approx(1.0)
    turned = _arr(SF._project(side, _g0(np.pi / 2), _cam(), _np_rotmat))
    assert turned[0, 0] == pytest.approx(0.0, abs=1e-9)  # and it turns with the global yaw


def test_the_distance_field_is_sampled_in_original_pixel_coordinates(torch_stub):
    sdf = np.tile(np.arange(32, dtype=np.float32), (32, 1))  # value == x at half resolution
    got = _arr(SF._sample_sdf(_T(sdf), _T(np.array([[0.0, 0.0], [63.0, 0.0], [31.5, 31.5]])), 64, 64))
    assert got[0] == pytest.approx(0.0)
    assert got[1] == pytest.approx(31.0)
    assert got[2] == pytest.approx(15.5, abs=0.6)


# ── one hypothesis ───────────────────────────────────────────────────────────
def test_an_arm_opens_exactly_the_macro_and_local_axes_the_module_declares(torch_stub):
    arm = _arm()
    assert len(arm.u_macro) == len(SF.MACRO_AXES) == 3
    assert len(arm.u_local) == len(SF.LOCAL_AXES) == 8
    assert len(arm.params()) == 11
    phen, loc = arm.body_kwargs()
    assert float(phen['age']) == 30.0  # declared, never fitted
    assert float(phen['muscle']) == pytest.approx(0.5, abs=2e-4)
    assert float(loc['measure-waist-circ-incr']) == pytest.approx(0.1, abs=2e-4)
    assert _arm(free_macro=False, free_local=False).params() == []  # a frozen arm offers nothing
    assert len(_arm(free_local=False).params()) == 3


def test_an_overridden_arm_is_a_fixed_body_with_no_free_shape(torch_stub):
    arm = SF._Arm('null', _Model(), {}, {}, None, override=({'muscle': 0.5}, {'measure-waist-circ-incr': 0.0}))
    assert arm.u_macro == [] and arm.u_local == [] and arm.params() == []
    phen, loc = arm.body_kwargs()
    assert float(phen['muscle']) == 0.5 and float(loc['measure-waist-circ-incr']) == 0.0


def test_a_readable_arm_reports_every_axis_and_its_delta_from_the_declaration(torch_stub):
    r = _arm().readable()
    assert set(r) == {'phenotype', 'local_changes', 'delta_macro', 'delta_local'}
    assert set(r['delta_macro']) == set(SF.MACRO_AXES)
    assert set(r['delta_local']) == set(SF.LOCAL_AXES)
    assert all(abs(v) < 1e-3 for v in r['delta_macro'].values())  # a fresh arm has moved nothing
    assert r['phenotype']['age'] == 30.0
    moved = _arm()
    moved.u_macro[0].a = np.asarray(40.0)  # saturate muscle upward
    assert moved.readable()['delta_macro']['muscle'] == pytest.approx(SF.MACRO_BOUND, abs=1e-3)


# ── the forward pass ─────────────────────────────────────────────────────────
def test_the_forward_pass_evaluates_the_shared_body_once_per_cell(torch_stub):
    arm = _arm()
    pose = {'cell_00': _T(np.zeros((2, 3))), 'cell_07': _T(np.zeros((2, 3)))}
    outs = SF._forward(arm, [{'cell': 'cell_00'}, {'cell': 'cell_07'}], pose, None, None, {})
    assert set(outs) == {'cell_00', 'cell_07'}
    assert _arr(outs['cell_00']['vertices']).shape == (1, 400, 3)
    kw = arm.m.calls[0]
    assert 'phenotype_kwargs' in kw and 'local_changes_kwargs' in kw
    assert _arr(kw['pose_parameters']).shape == (1, 2, 4, 4)  # the pose, unscaled


def test_a_bone_scale_matrix_is_folded_into_the_pose_rotation(torch_stub):
    arm = _arm()
    s44 = _T(np.tile(np.diag([2.0, 2.0, 2.0, 1.0]), (1, 2, 1, 1)))
    SF._forward(arm, [{'cell': 'c'}], {'c': _T(np.zeros((2, 3)))}, s44, None, {})
    pp = _arr(arm.m.calls[0]['pose_parameters'])
    assert pp.shape == (1, 2, 4, 4)
    assert pp[0, 0, 0, 0] == pytest.approx(2.0)  # the scale survived the fold
    assert pp[0, 0, 3] == pytest.approx([0.0, 0.0, 0.0, 1.0])  # the bottom row is untouched


# ── the per-cell loss ────────────────────────────────────────────────────────
def _loss(model, cell, **kw):
    return SF._cell_loss(_out(model), cell, _cam(), _g0(), _regressor, _np_rotmat, **kw)


def test_a_cell_without_a_distance_field_is_graded_on_keypoints_alone(torch_stub):
    cell = _cell()
    total, err_px, sil = _loss(_Model(), cell)
    assert sil == 0.0 and err_px > 0.0 and float(total) > 0.0
    assert '_outline_idx' not in cell  # no silhouette, no correspondence to keep


def test_the_silhouette_term_is_added_and_the_outline_is_remembered(torch_stub):
    m = _Model()
    cell = _cell(sdf=np.full((32, 32), 5.0, np.float32))
    total, _err, sil = _loss(m, cell)
    assert sil > 0.0  # a body 5px outside the drawn outline is penalised
    assert float(total) > 0.0
    idx = cell['_outline_idx']
    assert len(idx) > 10
    _loss(m, cell, step=3)
    assert cell['_outline_idx'] is idx  # reused between refreshes
    _loss(m, cell, step=SF.OUTLINE_EVERY)
    assert cell['_outline_idx'] is not idx  # and recomputed on one
    cropped = _cell(sdf=_arr(cell['sdf_t']), y_limit=10.0)
    _loss(m, cropped)
    assert len(cropped['_outline_idx']) < len(cell['_outline_idx'])  # the draw limit crops it


def test_switching_the_silhouette_off_leaves_the_keypoint_loss_alone(torch_stub):
    m, sdf = _Model(), np.full((32, 32), 5.0, np.float32)
    on, _e, sil_on = _loss(m, _cell(sdf=sdf))
    off, _e2, sil_off = _loss(m, _cell(sdf=sdf), use_sil=False)
    assert sil_off == 0.0 and sil_on > 0.0
    assert float(off) == pytest.approx(float(on) - SF.SIL_WEIGHT * sil_on)


def test_too_few_candidate_vertices_to_bin_are_used_as_they_are(torch_stub):
    m = _Model(verts=np.stack([np.arange(8.0), np.zeros(8), -np.arange(8.0)], -1))
    cell = _cell(sdf=np.zeros((32, 32), np.float32))
    _t, _e, sil = _loss(m, cell)
    assert len(cell['_outline_idx']) == 4  # stride 2 over 8 vertices, no angular binning
    assert sil == 0.0  # and fewer than ten points earns no silhouette term


# ── the nuisance re-solve and the held-out score ─────────────────────────────
def _solve_fixture(n=2, with_mask=True):
    sdf = np.full((32, 32), 3.0, np.float32)
    cells = [_cell('cell_%02d' % i, sdf=sdf, mask=_box_mask() if with_mask else None) for i in range(n)]
    pose = {c['cell']: _T(np.zeros((2, 3))) for c in cells}
    return _arm(), cells, pose, {c['cell']: _regressor for c in cells}


def test_the_nuisance_resolve_gives_every_cell_its_own_camera_and_yaw(torch_stub):
    arm, cells, pose, regressors = _solve_fixture()
    outs = SF._solve_nuisance(arm, cells, pose, None, regressors, iters=3, lr=0.01)
    assert set(outs) == {'cell_00', 'cell_01'}
    for c in cells:
        assert c['cam'].requires_grad and c['gaa'].requires_grad
        assert _arr(c['cam']).shape == (4,) and _arr(c['gaa']).shape == (3,)
        assert float(_arr(c['cam'])[0]) == pytest.approx(c['cam0'][0])  # f is pinned by anny_fit
        assert c['cam'].grad[0] == 0.0  # and its gradient is zeroed every step
    arm, one, pose, regressors = _solve_fixture(n=1)
    SF._solve_nuisance(arm, one, pose, None, regressors, iters=0)
    assert 'cam' in one[0] and 'gaa' in one[0]  # zero iterations still arms the parameters


def test_a_held_out_score_reports_reprojection_and_iou_per_cell(torch_stub):
    arm, cells, pose, regressors = _solve_fixture(n=3)
    s = SF._score(arm, cells, pose, None, regressors, nuisance_iters=1)
    assert s['n_cells'] == 3 and s['n_iou_cells'] == 3
    assert set(s['per_cell']) == {'cell_00', 'cell_01', 'cell_02'}
    assert s['median_err_px'] > 0 and s['mean_err_px'] > 0
    assert 0.0 <= s['median_iou'] <= 1.0 and 0.0 <= s['mean_iou'] <= 1.0
    assert all(c['iou'] is not None for c in s['per_cell'].values())


def test_a_score_with_no_measurable_silhouette_says_so_rather_than_inventing_one(torch_stub):
    arm, cells, pose, regressors = _solve_fixture(n=2, with_mask=False)
    s = SF._score(arm, cells, pose, None, regressors, nuisance_iters=1)
    assert s['n_iou_cells'] == 0
    assert s['median_iou'] is None and s['mean_iou'] is None
    assert s['median_err_px'] is not None


# ── the measured IoU ─────────────────────────────────────────────────────────
def _quad_model(offset=0.0):
    """Four vertices that project to the square (10,10)-(30,30) under cam [1,1,0,0]."""
    v = np.array([[10.0, 0.0, -10.0], [30.0, 0.0, -10.0], [30.0, 0.0, -30.0], [10.0, 0.0, -30.0]])
    return _Model(verts=v + offset, faces=[[0, 1, 2, 3]])


def _iou(model, cell):
    return SF._iou(_out(model), cell, _cam(), _g0(), _np_rotmat, model)


def test_the_iou_is_a_real_rasterisation_against_the_drawn_mask(torch_stub):
    assert _iou(_quad_model(), _cell(mask=_box_mask((10, 31, 10, 31)))) == pytest.approx(1.0, abs=0.05)
    assert _iou(_quad_model(), _cell(mask=_box_mask((40, 60, 40, 60)))) == 0.0  # a total miss
    plain = _quad_model()
    plain.faces = _arr(plain.faces)  # faces handed over as a plain array, with no .numpy()
    assert _iou(plain, _cell(mask=_box_mask((10, 31, 10, 31)))) == pytest.approx(1.0, abs=0.05)


def test_the_iou_crops_both_the_mesh_and_the_mask_at_the_draw_limit(torch_stub):
    mask = _box_mask((10, 31, 10, 31))
    assert _iou(_quad_model(), _cell(mask=mask, y_limit=20)) == pytest.approx(1.0, abs=0.08)
    assert mask[30, 20] == 255  # the caller's mask was copied, not cut in place


def test_a_cell_with_no_mask_has_no_iou_and_an_empty_union_is_not_a_zero(torch_stub):
    assert _iou(_quad_model(), _cell(mask=None)) is None
    blank = _cell(mask=np.zeros((64, 64), np.uint8))
    for off in (np.array([900.0, 0.0, 0.0]), np.array([0.0, 0.0, -900.0])):
        assert _iou(_quad_model(off), blank) is None  # off canvas sideways, then downward


# ── the receipt renders ──────────────────────────────────────────────────────
def test_the_receipt_renders_front_and_side_side_by_side(torch_stub, monkeypatch, tmp_path):
    seen = []

    def _depth(v, faces, _cam3, _r, w, h, camera_model='ortho'):
        seen.append((len(v), len(faces), camera_model))
        return np.full((h, w), 90, np.uint8)

    monkeypatch.setattr(AA, 'render_depth', _depth)
    out = tmp_path / 'fit.png'
    assert SF._render_views(_arm(), _Model(), None, str(out), 'fit') == str(out)
    assert cv2.imread(str(out)).shape == (520, 1040, 3)  # two 520px tiles
    assert len(seen) == 2 and {s[2] for s in seen} == {'ortho'}
    model, s44 = _Model(), _T(np.tile(np.eye(4), (1, 2, 1, 1)))
    SF._render_views(_arm(), model, s44, str(tmp_path / 'null.png'), 'null_declared')
    assert model.calls[-1]['pose_parameters'] is s44  # a bone-scale pose is rendered as given


# ── the orchestrator ─────────────────────────────────────────────────────────
_STAGES = tuple(
    'resolve_body collect_cells qualify_silhouettes split_cells build_arms '
    'train_fit_arm score_arms build_gate finish_gate write_candidate'.split()
)


def test_run_drives_the_stages_in_the_order_the_docstring_claims(torch_stub, monkeypatch, tmp_path):
    calls = []
    ctx = types.SimpleNamespace(name='abel', scores={}, arms={'fit': types.SimpleNamespace(readable=dict)})
    rets = {'resolve_body': ctx, 'build_gate': {'state': 'found'}, 'write_candidate': {'gate': {'state': 'found'}}}

    def rec(name):
        def f(*_a, **_kw):
            calls.append(name)
            return rets.get(name)

        return f

    for n in _STAGES:
        monkeypatch.setattr(ST, n, rec(n))
    doc = SF.run('abel', 'abel', out_dir=str(tmp_path), iters=1, nuisance_iters=1, log=lambda _m: None)
    assert doc == {'gate': {'state': 'found'}}
    assert calls == list(_STAGES)


# ── the command line ─────────────────────────────────────────────────────────
@pytest.fixture
def captured_run(monkeypatch):
    seen = {}

    def _run(char_id, body, **kw):
        seen['char_id'], seen['body'] = char_id, body
        seen.update(kw)
        return {'gate': {'state': 'found'}}

    monkeypatch.setattr(SF, 'run', _run)
    return seen


def test_the_defaults_the_cli_hands_the_solver_are_the_documented_ones(captured_run):
    assert SF.main(['abel']) == 0
    assert captured_run['char_id'] == 'abel' and captured_run['body'] == ''
    assert captured_run['cells'] is None  # an empty --cells means "all of them"
    assert (captured_run['holdout'], captured_run['iters']) == (3, 400)
    assert (captured_run['nuisance_iters'], captured_run['batch']) == (150, 10)
    assert captured_run['seed'] == 0 and captured_run['lr'] == pytest.approx(0.05)


def test_every_flag_reaches_the_solver(captured_run):
    argv = ['abel', '--body', 'abel_v2', '--cells', 'cell_00,cell_08', '--holdout', '4', '--iters', '7']
    argv += ['--nuisance-iters', '9', '--batch', '0', '--seed', '11', '--lr', '0.5']
    assert SF.main(argv) == 0
    assert captured_run['body'] == 'abel_v2'
    assert captured_run['cells'] == 'cell_00,cell_08'
    assert (captured_run['holdout'], captured_run['iters']) == (4, 7)
    assert (captured_run['nuisance_iters'], captured_run['batch']) == (9, 0)
    assert captured_run['seed'] == 11 and captured_run['lr'] == pytest.approx(0.5)


@pytest.mark.parametrize('state,code', [('found', 0), ('not_detectable', 0), ('unmeasurable', 1)])
def test_not_beating_the_nulls_is_a_result_and_an_unmeasurable_sheet_is_not(monkeypatch, state, code):
    monkeypatch.setattr(SF, 'run', lambda *_a, **_kw: {'gate': {'state': state}})
    assert SF.main(['abel']) == code


def test_the_module_refuses_to_fit_age_height_or_gender():
    assert set(SF.MACRO_AXES).isdisjoint({'age', 'height', 'gender'})
    assert all(ax.startswith('measure-') for ax in SF.LOCAL_AXES)
    assert SF.LOCAL_BOUND > SF.MACRO_BOUND  # locals move further, inside a narrower range
    assert SF.OUT_ROOT == ST.SF.OUT_ROOT  # the cell root is re-exported for the stages module
    assert os.path.isabs(str(SF.OUT_ROOT))
