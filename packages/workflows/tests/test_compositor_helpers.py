# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stage helpers split out of ``composite_write_on_quad``.

Everything here is pure: the reveal schedule, the calibration-frame choice, the ink
state dict and the statistics block never decode a clip, never touch OpenCV and never
shell out to ffmpeg. That is the whole point of the 2026-10-09 split — these stages
were unreachable while they lived inside a 327-line function.
"""

import functools

import numpy as np

from zyg_workflows.ink_fx.compositor_stages import (
    _LoopTotals,
    _build_composite_stats,
    _build_ink_state,
    _build_reveal_plan,
    _PageGeometry,
    _resolve_occlusion_matte,
    _reveal_progress,
)


def _prog(fps=10, start_s=1.0, end_s=3.0):
    return functools.partial(_reveal_progress, fps=fps, start_s=start_s, end_s=end_s)


def _geometry(h=12, w=16, tw=32, th=24):
    pmask = np.zeros((h, w), dtype=np.float32)
    pmask[2:-2, 2:-2] = 1.0
    return _PageGeometry(
        quad=np.array([(2, 2), (w - 2, 2), (w - 2, h - 2), (2, h - 2)], dtype=np.float32),
        tw=tw,
        th=th,
        ink=np.zeros((th, tw), dtype=np.float32),
        warp_m=np.eye(3, dtype=np.float64),
        ctr=(w / 2.0, h / 2.0),
        pmask=pmask,
        poly_bool=pmask > 0,
        bb=(0, h, 0, w),
    )


# ── _reveal_progress ──────────────────────────────────────────────────────────


def test_reveal_progress_is_none_before_the_write_on_starts():
    p = _prog(fps=10, start_s=1.0, end_s=3.0)
    assert p(0) is None
    assert p(10) is None  # t == start_s is still untouched paper
    assert p(11) is not None


def test_reveal_progress_rises_to_one_and_clamps():
    p = _prog(fps=10, start_s=1.0, end_s=3.0)
    assert p(20) == 0.5
    assert p(30) == 1.0
    assert p(90) == 1.0  # clamped, never above 1.0


def test_reveal_progress_survives_a_zero_length_window():
    """``max(end_s - start_s, 1e-3)`` is what keeps this from dividing by zero."""
    p = _prog(fps=10, start_s=1.0, end_s=1.0)
    assert p(11) == 1.0


# ── _build_reveal_plan ────────────────────────────────────────────────────────


def test_build_reveal_plan_picks_four_spread_out_finished_frames():
    n = 40
    frames = [np.full((12, 16, 3), 100, dtype=np.uint8) for _ in range(n)]
    geo = _geometry()
    plan = _build_reveal_plan(n, _prog(fps=10, start_s=1.0, end_s=2.0), frames, geo.poly_bool)
    assert plan.full_idx == list(range(20, 40))
    assert plan.samp == [20, 26, 33, 39]
    assert len(plan.samples) == 4
    assert plan.raw_lapvar == 0.0  # a flat page has no laplacian energy


def test_build_reveal_plan_falls_back_to_the_tail_when_the_reveal_never_completes():
    n = 20
    frames = [np.zeros((12, 16, 3), dtype=np.uint8) for _ in range(n)]
    geo = _geometry()
    # end_s far beyond the clip: progress never reaches 1.0
    plan = _build_reveal_plan(n, _prog(fps=10, start_s=0.5, end_s=100.0), frames, geo.poly_bool)
    assert plan.full_idx == list(range(12, 20))
    assert plan.samp[0] == 12 and plan.samp[-1] == 19


def test_build_reveal_plan_block_is_a_consecutive_run():
    n = 60
    frames = [np.zeros((12, 16, 3), dtype=np.uint8) for _ in range(n)]
    geo = _geometry()
    plan = _build_reveal_plan(n, _prog(fps=10, start_s=0.0, end_s=1.0), frames, geo.poly_bool)
    idx = [i for i, _p, _r in plan.block]
    assert len(idx) == 12
    assert idx == list(range(idx[0], idx[0] + 12)), 'temporal sigma needs ADJACENT frames'


# ── _build_ink_state ──────────────────────────────────────────────────────────


def test_build_ink_state_takes_its_frame_size_from_the_page_mask():
    geo = _geometry(h=12, w=16)
    st = _build_ink_state(
        geo,
        8,
        lines=5,
        gain=0.85,
        grain=True,
        grain_smooth=0.0,
        grain_scale=1.0,
        jitter=False,
        seed=7,
        matte=None,
        luma_adapt=True,
        ink_color=(48, 38, 30),
    )
    assert (st['H'], st['W']) == (12, 16)
    assert st['gain'] == 0.85
    assert st['jx'] is None and st['jy'] is None and st['js'] is None


def test_build_ink_state_defers_an_auto_grain_scale_to_the_calibration():
    geo = _geometry()
    st = _build_ink_state(
        geo,
        8,
        lines=5,
        gain=0.85,
        grain=True,
        grain_smooth=0.0,
        grain_scale='auto',
        jitter=True,
        seed=7,
        matte=None,
        luma_adapt=False,
        ink_color=(48, 38, 30),
    )
    assert st['grain_scale'] == 1.0, "'auto' goes in as the plan's constants"
    assert st['jx'] is not None and len(st['jx']) == 8


def test_build_ink_state_jitter_series_are_three_independent_draws():
    geo = _geometry()
    kw = dict(
        lines=5,
        gain=0.85,
        grain=True,
        grain_smooth=0.0,
        grain_scale=1.0,
        jitter=True,
        seed=7,
        matte=None,
        luma_adapt=True,
        ink_color=(48, 38, 30),
    )
    st = _build_ink_state(geo, 16, **kw)
    assert not np.allclose(st['jx'], st['jy'])
    assert not np.allclose(st['jy'], st['js'])
    # deterministic in the seed
    assert np.allclose(st['jx'], _build_ink_state(geo, 16, **kw)['jx'])


# ── _resolve_occlusion_matte ──────────────────────────────────────────────────


def test_resolve_occlusion_matte_returns_nothing_when_occlusion_is_off():
    logs = []
    got = _resolve_occlusion_matte(
        'clip.mp4',
        [np.zeros((4, 4, 3), dtype=np.uint8)],
        np.zeros((4, 2), dtype=np.float32),
        occlude=None,
        matte_cache=None,
        out_path='/tmp/x.mp4',
        occluder_boxes=None,
        log=logs.append,
    )
    assert got == (None, None)
    assert logs == []


def test_resolve_occlusion_matte_warns_on_an_unknown_mode():
    logs = []
    got = _resolve_occlusion_matte(
        'clip.mp4',
        [np.zeros((4, 4, 3), dtype=np.uint8)],
        np.zeros((4, 2), dtype=np.float32),
        occlude='rotoscope',
        matte_cache=None,
        out_path='/tmp/x.mp4',
        occluder_boxes=None,
        log=logs.append,
    )
    assert got == (None, None)
    assert logs == ["[ink] unknown occlude mode 'rotoscope' — no occlusion matte"]


# ── _build_composite_stats ────────────────────────────────────────────────────


def _plan_stub(full_n=4, raw_lapvar=100.0):
    class _P:
        full_idx = list(range(full_n))
        samp = list(range(min(4, full_n)))

    p = _P()
    p.raw_lapvar = raw_lapvar
    return p


def test_build_composite_stats_reports_the_ratios_the_gate_reads():
    rng = np.random.default_rng(3)
    raw = rng.normal(120, 4.0, size=(6, 50)).astype(np.float32)
    ink = rng.normal(100, 2.0, size=(6, 50)).astype(np.float32)
    totals = _LoopTotals(
        raw_series=raw,
        ink_series=ink,
        alpha_acc=np.full((50,), 3.0),
        ink_lapvar=130.0,
        viol_num=1.0,
        viol_den=50.0,
    )
    st = {'grain_scale': 1.25, 'matte': object()}
    stats = _build_composite_stats(
        st,
        _plan_stub(full_n=6, raw_lapvar=100.0),
        totals,
        sigma=1.5789,
        grain=True,
        matte=object(),
        hard=np.zeros((6, 4, 4)),
        drift={'max_px': 2.0},
        n=6,
    )
    assert stats['blur_sigma'] == 1.579
    assert stats['grain_scale'] == 1.25
    assert stats['sharpness_ratio'] == 1.3  # 130 / 100
    assert stats['matte_violation'] == 0.02  # 1 / 50
    assert stats['occluded'] is True
    assert stats['matte_measured_only'] is False
    assert stats['ink_coverage_of_page'] == 1.0  # alpha 3/6 == 0.5 > 0.05
    assert stats['frames'] == 6
    assert stats['page_drift_px'] == {'max_px': 2.0}
    assert 0.0 < stats['temporal_sigma_ratio'] < 1.0


def test_build_composite_stats_flags_a_measured_only_matte_and_no_violation():
    totals = _LoopTotals(
        raw_series=np.zeros((1, 10), dtype=np.float32),
        ink_series=np.zeros((1, 10), dtype=np.float32),
        alpha_acc=np.zeros((10,)),
        ink_lapvar=0.0,
        viol_num=0.0,
        viol_den=0.0,
    )
    stats = _build_composite_stats(
        {'grain_scale': 1.0, 'matte': None},
        _plan_stub(full_n=1),
        totals,
        sigma=1.0,
        grain=False,
        matte=object(),
        hard=None,
        drift=None,
        n=1,
    )
    assert stats['matte_measured_only'] is True, "occlude='measure' must still be visible"
    assert stats['occluded'] is False
    assert stats['matte_violation'] is None
    assert stats['grain_scale'] == 0.0, 'grain off reports a zero scale, not the dict value'
    # a single finished frame has no temporal spread to measure
    assert stats['raw_temporal_sigma'] == 0.0
    assert stats['temporal_sigma_ratio_on_ink'] == 0.0
