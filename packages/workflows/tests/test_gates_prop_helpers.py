# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the three legs `qc_prop_geometry` was split into.

The legs used to be inline blocks of the 381-line gate, reachable only by decoding a
clip, so these are the first tests that exercise them on plain arrays: the sampler, the
absolute-geometry leg (b) and its canon check, the ridge-flicker leg (c), the seam-pair
derivation and the verdict roll-up. Nothing here needs a GPU, a service or a real clip.
"""

import numpy as np
import pytest

from zyg_workflows.pipeline_debug import gates_prop_triad as triad
from zyg_workflows.pipeline_debug.gates_prop import (
    _PROP_AREA_RATIO_MAX,
    _PROP_RIDGE_FLICKER_MAX,
    _PROP_RIDGE_FLOOR,
    _PROP_SCALE_LOG_MAX,
)

BOX_AREA = 10000
CLIP_W = 832


def _samples(areas=None, widths=None, rfrac=None, dfrac=None, n=8):
    s = triad.PropSamples()
    s.areas = np.array([500.0] * n if areas is None else areas, float)
    s.widths = np.array([40.0] * n if widths is None else widths, float)
    s.rfrac = np.array([0.01] * n if rfrac is None else rfrac, float)
    s.dfrac = np.array([0.2] * n if dfrac is None else dfrac, float)
    s.rcnt = [2] * len(s.rfrac)
    s.rlen = [30] * len(s.rfrac)
    s.heights = [20.0] * len(s.areas)
    return s


# ── the sampler ───────────────────────────────────────────────────────────────────
def _frame(radius):
    f = np.full((60, 80, 3), 40, np.uint8)
    yy, xx = np.mgrid[0:60, 0:80]
    f[(yy - 30) ** 2 + (xx - 40) ** 2 <= radius**2] = 240
    return f


def test_sample_prop_series_records_one_row_per_frame_in_decode_order():
    frames = [(0.0, _frame(14)), (0.25, _frame(20))]
    s = triad.sample_prop_series(frames, slice(0, 60), slice(0, 80), 1.0)
    assert [r['t'] for r in s.series] == [0.0, 0.25]
    assert s.dur == 0.25
    assert len(s.crops) == len(s.blobs) == 2
    assert s.areas[1] > s.areas[0] > 0  # the blob grew between the two samples
    assert s.series[0]['area'] == int(s.areas[0])
    assert set(s.series[0]) == {'t', 'area', 'w', 'h', 'ridges', 'ridge_area_frac', 'ridge_len', 'dark_frac'}


def test_sample_prop_series_scores_a_frame_without_a_blob_as_zero_not_as_a_gap():
    frames = [(0.0, np.full((60, 80, 3), 40, np.uint8)), (0.5, _frame(18))]
    s = triad.sample_prop_series(frames, slice(0, 60), slice(0, 80), 1.0)
    assert s.blobs[0] is None
    assert (s.areas[0], s.widths[0], s.heights[0]) == (0.0, 0.0, 0.0)
    assert len(s.series) == 2


# ── leg (b): absolute geometry ────────────────────────────────────────────────────
def test_geometry_leg_passes_a_stable_blob_and_returns_the_sample_floor():
    reasons = []
    geo, floor = triad.geometry_leg(_samples(), BOX_AREA, CLIP_W, None, 0.2, _PROP_AREA_RATIO_MAX, reasons)
    assert geo['applicable'] is True
    assert geo['ok'] is True
    assert geo['coverage'] == 1.0
    assert geo['area_ratio_p95_p05'] == 1.0
    assert reasons == []
    assert floor == pytest.approx(0.35 * 500.0)  # 0.35 x the median beats the 0.5%-of-box floor


def test_geometry_leg_fails_a_blob_that_changes_size():
    reasons = []
    areas = [300.0, 320.0, 340.0, 600.0, 700.0, 800.0, 850.0, 900.0]
    geo, _ = triad.geometry_leg(_samples(areas=areas), BOX_AREA, CLIP_W, None, 0.2, 1.35, reasons)
    assert geo['ok'] is False
    assert geo['area_ratio_p95_p05'] > 1.35
    assert any('changes SIZE across the clip' in r for r in reasons)


def test_geometry_leg_abstains_when_the_box_holds_no_white_blob():
    reasons = []
    geo, floor = triad.geometry_leg(_samples(areas=[0.0] * 8), BOX_AREA, CLIP_W, None, 0.2, 1.35, reasons)
    assert geo['ok'] is None  # abstention, never a pass
    assert geo['applicable'] is False
    assert floor == 0.5 * BOX_AREA * 0.01  # _PROP_MIN_BLOB_FRAC of the box
    assert any('geometry INAPPLICABLE' in r for r in reasons)


def test_geometry_leg_abstains_below_the_coverage_floor():
    reasons = []
    areas = [900.0, 900.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # one in four samples shows the prop
    geo, _ = triad.geometry_leg(_samples(areas=areas), BOX_AREA, CLIP_W, None, 0.2, 1.35, reasons)
    assert geo['ok'] is None
    assert geo['coverage'] < 0.5
    assert any('coverage' in r for r in reasons)


def test_geometry_leg_checks_a_plain_number_canon_against_the_median_width():
    reasons = []
    geo, _ = triad.geometry_leg(_samples(), BOX_AREA, CLIP_W, 40.0, 0.2, _PROP_AREA_RATIO_MAX, reasons)
    assert geo['canon_ratio'] == 1.0
    assert geo['canon_bowl_w_px'] == 40.0
    assert geo['ok'] is True
    assert reasons == []


def test_geometry_leg_rescales_a_canon_measured_on_the_render_native_width():
    reasons = []
    canon = {'bowl_w_px': 20.0, 'ref_width': 416}  # half the clip's width: the canon doubles
    geo, _ = triad.geometry_leg(_samples(), BOX_AREA, CLIP_W, canon, 0.2, _PROP_AREA_RATIO_MAX, reasons)
    assert geo['canon_bowl_w_px'] == 40.0
    assert geo['canon_ratio'] == 1.0
    assert geo['canon_tol'] == 0.2


def test_geometry_leg_fails_a_bowl_width_outside_the_canon_tolerance():
    reasons = []
    canon = {'bowl_w_px': 40.0, 'tol': 0.05}
    geo, _ = triad.geometry_leg(_samples(widths=[60.0] * 8), BOX_AREA, CLIP_W, canon, 0.2, 9.0, reasons)
    assert geo['canon_ratio'] == 1.5
    assert geo['canon_tol'] == 0.05  # the dict's own tol wins over the argument
    assert geo['ok'] is False
    assert any('outside +-5%' in r for r in reasons)


def test_geometry_leg_skips_the_width_check_when_the_canon_dict_has_no_width():
    reasons = []
    geo, _ = triad.geometry_leg(_samples(), BOX_AREA, CLIP_W, {'ref_width': 832}, 0.2, 9.0, reasons)
    assert 'canon_ratio' not in geo
    assert geo['ok'] is True
    assert reasons == ["canon dict has no 'bowl_w_px' — absolute-width check skipped"]


# ── leg (c): thin dark structure ──────────────────────────────────────────────────
def test_ridge_leg_passes_a_steady_ridge_series():
    reasons = []
    ridge = triad.ridge_leg(_samples(), _PROP_RIDGE_FLICKER_MAX, reasons)
    assert ridge['ok'] is True
    assert ridge['ridge_flicker'] == 0.0
    assert ridge['ridge_area_frac_med'] == 0.01
    assert reasons == []


def test_ridge_leg_fails_a_ridge_that_blinks_and_says_so():
    reasons = []
    rfrac = [0.002, 0.05, 0.002, 0.05, 0.002, 0.05, 0.002, 0.05]
    ridge = triad.ridge_leg(_samples(rfrac=rfrac), 1.2, reasons)
    assert ridge['ok'] is False
    assert ridge['ridge_flicker'] > 1.2
    assert any('thin dark structure' in r for r in reasons)


def test_ridge_leg_divides_by_the_floor_when_the_prop_has_no_dark_detail():
    ridge = triad.ridge_leg(_samples(rfrac=[0.0] * 8), 1.2, [])
    assert ridge['ridge_flicker'] == 0.0  # 0 / floor, not 0 / 0
    expected = 0.001 / _PROP_RIDGE_FLOOR
    flat = triad.ridge_leg(_samples(rfrac=[0.0, 0.001] * 4), 9.0, [])
    assert flat['ridge_flicker'] == pytest.approx(round(expected, 3), rel=0.05)


def test_ridge_leg_reports_the_dark_fraction_swing_as_evidence():
    ridge = triad.ridge_leg(_samples(dfrac=[0.1] * 4 + [0.5] * 4), 9.0, [])
    assert ridge['dark_frac_swing'] == pytest.approx(0.4, abs=1e-6)  # p90 0.5 − p10 0.1
    assert ridge['ok'] is True  # dark_frac is evidence only, it never gates


def test_ridge_leg_handles_a_single_sample():
    ridge = triad.ridge_leg(_samples(rfrac=[0.01], n=1), 1.2, [])
    assert ridge['ridge_flicker'] == 0.0


# ── the seam pairs ────────────────────────────────────────────────────────────────
def test_seam_pair_times_uses_the_given_seams_verbatim():
    assert triad.seam_pair_times([0.0, 1.0, 2.5], 10.0, None, 17.0) == [(0.0, 1.0), (1.0, 2.5)]


def test_seam_pair_times_derives_render_native_seams_in_seconds():
    pairs = triad.seam_pair_times(None, 7.0, 57, 17.0)
    assert pairs[0] == (0.0, 57 / 17.0)
    assert pairs[-1][1] <= 7.0  # never past the clip's own duration
    assert len(pairs) == 2  # 7 s / (57 / 17) s per stride, floor'd


def test_seam_pair_times_of_a_clip_shorter_than_one_stride_has_no_pairs():
    assert triad.seam_pair_times(None, 1.0, 57, 17.0) == []


def test_seam_pair_times_guards_a_zero_fps():
    assert triad.seam_pair_times(None, 0.0, 1, 0.0) == []


# ── the verdict ───────────────────────────────────────────────────────────────────
def _legs(geo_ok, ridge_ok, scale_ok):
    geo = {'ok': geo_ok, 'area_ratio_p95_p05': 1.1, 'bowl_w_med': 40.0, 'canon_ratio': None}
    ridge = {'ok': ridge_ok, 'ridge_flicker': 0.3, 'ridge_count_p90': 2.0}
    sc = {'ok': scale_ok, 'measured': 2, 'pairs': [1, 2], 'method': 'RANSAC'}
    return geo, ridge, sc


def _out(reasons=None):
    return {'ok': False, 'reasons': list(reasons or []), 'checks': []}


def test_record_verdict_passes_only_when_every_measured_leg_passes():
    out = _out()
    triad.record_verdict(out, *_legs(True, True, True))
    assert out['ok'] is True
    assert [c['check'] for c in out['checks']] == ['prop_triad', 'prop_scale', 'prop_geometry', 'prop_ridge']
    assert out['checks'][0]['legs_measured'] == 3


def test_record_verdict_fails_when_one_leg_fails():
    out = _out(['ridge_flicker 2.09 > 1.2 — thin dark structure'])
    triad.record_verdict(out, *_legs(True, False, True))
    assert out['ok'] is False
    assert out['checks'][0]['ok'] is False
    assert 'thin dark structure' in out['checks'][0]['note']


def test_record_verdict_never_records_an_abstained_leg_as_a_check():
    out = _out()
    triad.record_verdict(out, *_legs(None, True, None))
    assert out['ok'] is True
    assert [c['check'] for c in out['checks']] == ['prop_triad', 'prop_ridge']
    assert out['checks'][0]['legs_measured'] == 1


def test_record_verdict_is_fail_closed_when_no_leg_was_measurable():
    out = _out()
    triad.record_verdict(out, *_legs(None, None, None))
    assert out['ok'] is False
    assert 'no leg of the triad was measurable — fail-closed' in out['reasons']
    assert out['checks'][0]['legs_measured'] == 0


def test_record_verdict_quotes_only_the_scale_reasons_on_the_scale_check():
    out = _out(['scale 0.0s->3.4s: s=1.400 (4-DOF fit)', 'blob area p95/p05 2.8 > 1.35'])
    triad.record_verdict(out, *_legs(True, True, False))
    scale_check = next(c for c in out['checks'] if c['check'] == 'prop_scale')
    assert scale_check['note'] == 'scale 0.0s->3.4s: s=1.400 (4-DOF fit)'
    assert scale_check['method'] == 'RANSAC'


def test_the_scale_bound_is_the_published_twelve_percent():
    assert _PROP_SCALE_LOG_MAX == pytest.approx(np.log(1.12), abs=1e-5)
