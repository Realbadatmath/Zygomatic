# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the `ridge_relief` stages extracted into `ridge.primitive_profile`.

Every helper here is exercised on hand-written station records and a small synthetic
grid mesh: no GPU, no network, no service. The point is that each stage keeps the
contract the old single function relied on — the argument checks, the station-distance
rows, the run structure, the verdict naming and the assembled profile.
"""

import numpy as np
import pytest

from zyg_workflows.geom.form.ridge.constants import RIDGE_MIN_STATIONS, RIDGE_NULL_P99
from zyg_workflows.geom.form.ridge.primitive import build_graph
from zyg_workflows.geom.form.ridge import primitive_profile as pp

S = 1.7
CUT_REL = 0.003
CUT_CON = 4.0


def _grid(n=8, span=0.4):
    """A flat (n, n) triangulated grid → (vertices, faces, the middle column's stations)."""
    xs, ys = np.meshgrid(np.linspace(0.0, span, n), np.linspace(0.0, span, n), indexing='ij')
    v = np.stack([xs.ravel(), ys.ravel(), np.zeros(n * n)], 1).astype(np.float64)
    faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j
            faces.append([a, b, c])
            faces.append([a, c, d])
    st = [i * n + n // 2 for i in range(n)]
    return v, np.array(faces, np.int64), st


def _rows(rel, con, ok=None):
    """Station records with the given relief fractions and contrasts (None = unmeasurable)."""
    rows = []
    for k, (r, c) in enumerate(zip(rel, con)):
        measured = (ok[k] if ok is not None else r is not None) and r is not None
        rows.append(
            {
                'i': k,
                'vertex': k,
                'status': 'ok' if measured else 'unmeasurable',
                'relief_frac_stature': r if measured else None,
                'contrast': c if measured else None,
            }
        )
    return rows


def _dist(n, hop=0.01):
    """(n, n) station distance rows whose consecutive hops are `hop` and the rest far."""
    D = np.full((n, n), 5.0)
    for j in range(n - 1):
        D[j, j + 1] = hop
    return D


def _probe(st, mode='ridge', polarity='protrusion'):
    """A RidgeProbe carrying only the fields `build_result` reads."""
    return pp.RidgeProbe(
        v=np.zeros((len(st), 3)),
        faces=np.zeros((0, 3), np.int64),
        st=list(st),
        S=S,
        areas=None,
        normals=None,
        graph=None,
        mode=mode,
        polarity=polarity,
        core_frac=0.01,
        gap_frac=0.02,
        width_frac=0.03,
        along_stations=2,
        max_tilt_deg=35.0,
        min_frac_stature=CUT_REL,
        min_contrast=CUT_CON,
        point_radius_frac=0.015,
    )


def _summary(rel, con, polarity='protrusion'):
    """profile_summary over `_rows(rel, con)` with the shared cut and a unit-hop mesh."""
    n = len(rel)
    rows = _rows(rel, con)
    return pp.profile_summary(rows, _dist(n), list(range(n)), S, polarity, CUT_REL, CUT_CON)


# ── validate_polyline ─────────────────────────────────────────────────────────────
def test_validate_polyline_returns_float_vertices_int_stations_and_the_stature():
    v, _faces, _st = _grid(4)
    out_v, st, stature = pp.validate_polyline(v.tolist(), np.array([0.0, 5.0, 10.0]), 'either', 1.9)
    assert out_v.dtype == np.float64
    assert st == [0, 5, 10] and all(isinstance(i, int) for i in st)
    assert stature == 1.9


def test_validate_polyline_defaults_the_stature_to_the_mesh_z_extent():
    v = np.array([[0.0, 0.0, -0.25], [1.0, 0.0, 0.0], [2.0, 0.0, 1.25]])
    _v, _st, stature = pp.validate_polyline(v, [0, 2], 'protrusion', None)
    assert stature == pytest.approx(1.5)


def test_validate_polyline_refuses_fewer_than_two_stations():
    v, _f, _s = _grid(4)
    with pytest.raises(ValueError, match='at least 2 stations'):
        pp.validate_polyline(v, [3], 'either', S)


def test_validate_polyline_refuses_a_repeated_vertex():
    v, _f, _s = _grid(4)
    with pytest.raises(ValueError, match='repeats a vertex'):
        pp.validate_polyline(v, [1, 2, 1], 'either', S)


def test_validate_polyline_refuses_an_out_of_range_vertex():
    v, _f, _s = _grid(4)
    with pytest.raises(ValueError, match='outside the mesh'):
        pp.validate_polyline(v, [0, len(v)], 'either', S)


def test_validate_polyline_refuses_an_unknown_polarity():
    v, _f, _s = _grid(4)
    with pytest.raises(ValueError, match='protrusion\\|depression\\|either'):
        pp.validate_polyline(v, [0, 1], 'sideways', S)


def test_validate_polyline_refuses_a_non_positive_stature():
    v, _f, _s = _grid(4)
    with pytest.raises(ValueError, match='stature must be positive'):
        pp.validate_polyline(v, [0, 1], 'either', 0.0)


# ── curve_distances ───────────────────────────────────────────────────────────────
def test_curve_distances_measures_the_grid_hops_along_the_curve():
    v, faces, st = _grid(8)
    D, hops = pp.curve_distances(v, faces, st, S, build_graph(v, faces), None, 0.02, 0.03)
    assert D.shape == (len(st), len(v))
    assert np.isfinite(hops).all()
    step = 0.4 / 7.0
    assert hops == pytest.approx([step] * (len(st) - 1), rel=1e-6)


def test_curve_distances_takes_given_rows_verbatim():
    v, faces, st = _grid(4)
    given = np.zeros((len(st), len(v)))
    D, hops = pp.curve_distances(v, faces, st, S, None, given, 0.02, 0.03)
    assert D is not given or D.shape == given.shape  # asarray may return the same object
    assert np.array_equal(D, given)
    assert list(hops) == [0.0] * (len(st) - 1)


def test_curve_distances_refuses_rows_of_the_wrong_shape():
    v, faces, st = _grid(4)
    with pytest.raises(ValueError, match='distance rows are'):
        pp.curve_distances(v, faces, st, S, None, np.zeros((2, 2)), 0.02, 0.03)


def test_curve_distances_names_the_disconnected_station_pair():
    v, faces, st = _grid(4)
    given = np.zeros((len(st), len(v)))
    given[1, st[2]] = np.inf
    with pytest.raises(ValueError, match='stations 1 .* and 2 '):
        pp.curve_distances(v, faces, st, S, None, given, 0.02, 0.03)


# ── profile_summary ───────────────────────────────────────────────────────────────
def test_profile_summary_claims_a_whole_same_sign_qualifying_curve():
    prof = _summary([0.01] * 5, [5.0] * 5)
    assert prof.run_len == 5 and prof.run_sign == 1
    assert (prof.run_lo, prof.run_hi) == (0, 4)
    assert prof.any_len == 5
    assert prof.arc == pytest.approx(0.04)
    assert prof.run_span == pytest.approx(0.04)
    assert [r['i'] for r in prof.run_rows] == [0, 1, 2, 3, 4]
    assert prof.run_min_abs_relief_mm == pytest.approx(0.01 * S * 1000.0)
    assert prof.run_min_abs_contrast == pytest.approx(5.0)
    assert prof.peak == 0  # the first argmax of a flat |relief| profile


def test_profile_summary_breaks_the_run_at_an_unmeasurable_station():
    prof = _summary([0.01, 0.01, None, 0.01, 0.01], [5.0, 5.0, None, 5.0, 5.0])
    assert prof.run_len == 2  # never claimed across the hole
    assert list(prof.meas) == [0, 1, 3, 4]
    assert prof.ok.sum() == 4
    assert prof.run_span == pytest.approx(0.01)
    assert np.isnan(prof.rel[2]) and np.isnan(prof.con[2])


def test_profile_summary_drops_a_station_below_either_cut():
    prof = _summary([0.01, 0.0001, 0.01], [5.0, 5.0, 1.0])
    assert list(prof.qual) == [True, False, False]
    assert prof.run_len == 1 and prof.run_rows == [{'i': 0, 'vertex': 0, 'relief_mm': 17.0, 'contrast': 5.0}]


def test_profile_summary_counts_sign_changes_over_measured_and_over_qualifying():
    prof = _summary([0.01, -0.0001, 0.01, -0.01], [5.0, -5.0, 5.0, -5.0], polarity='either')
    assert prof.sign_changes == 3  # +,-,+,- over the four measured stations
    assert prof.sign_changes_q == 1  # the sub-cut station drops out, leaving +,+,-
    assert prof.run_len == 1 and prof.any_len == 2


def test_profile_summary_of_nothing_measured_has_no_run_and_no_peak():
    prof = _summary([None] * 3, [None] * 3)
    assert prof.run_len == 0 and prof.any_len == 0
    assert prof.run_rows == [] and prof.run_span == 0.0
    assert prof.peak == -1
    assert prof.run_min_abs_relief_mm is None and prof.run_min_abs_contrast is None
    assert np.isnan(prof.absrel).all()


# ── classify ──────────────────────────────────────────────────────────────────────
def test_classify_names_a_long_positive_run_a_ridge_with_the_resolved_null():
    nulls = RIDGE_NULL_P99['ridge']
    prof = _summary([0.01] * 5, [5.0] * 5)
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass) == ('ridge', 'resolved')
    assert rate == nulls['null_rate_resolved']


def test_classify_names_a_long_negative_run_a_furrow():
    nulls = RIDGE_NULL_P99['ridge']
    prof = _summary([-0.01] * 5, [-5.0] * 5, polarity='depression')
    verdict, vclass, _rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass) == ('furrow', 'resolved')


def test_classify_names_an_alternating_qualifying_strip_a_mixed_strip():
    nulls = RIDGE_NULL_P99['point']
    prof = _summary([0.01, -0.01, 0.01, -0.01, 0.01], [5.0, -5.0, 5.0, -5.0, 5.0], polarity='either')
    assert prof.run_len == 1 and prof.any_len == 5
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass) == ('mixed_strip', 'resolved')
    assert rate == nulls['null_rate_resolved']


def test_classify_calls_a_short_run_point_only_and_carries_that_null():
    nulls = RIDGE_NULL_P99['ridge']
    prof = _summary([0.01, 0.0001, 0.0001, 0.0001, 0.0001], [5.0] * 5)
    assert prof.qual.any() and prof.run_len == 1
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass) == ('point_only', 'below_null')
    assert rate == nulls['null_rate_point_only_or_better']


def test_classify_calls_a_profile_with_no_qualifying_station_flat_with_no_null():
    nulls = RIDGE_NULL_P99['ridge']
    prof = _summary([0.0001] * 5, [5.0] * 5)
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass, rate) == ('flat', 'below_null', None)


def test_classify_is_unmeasurable_below_the_minimum_station_count():
    nulls = RIDGE_NULL_P99['ridge']
    rel = [0.01] * (RIDGE_MIN_STATIONS - 1) + [None]
    prof = _summary(rel, [5.0] * (RIDGE_MIN_STATIONS - 1) + [None])
    assert prof.run_len >= nulls['min_run']  # a long run is still not enough evidence
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass, rate) == ('unmeasurable', 'no_verdict', None)


def test_classify_is_unmeasurable_when_nothing_was_measured():
    nulls = RIDGE_NULL_P99['ridge']
    prof = _summary([None] * 6, [None] * 6)
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    assert (verdict, vclass, rate) == ('unmeasurable', 'no_verdict', None)


# ── build_result ──────────────────────────────────────────────────────────────────
def test_build_result_assembles_the_profile_a_caller_reads():
    nulls = RIDGE_NULL_P99['ridge']
    rows = _rows([0.01] * 5, [5.0] * 5)
    prof = pp.profile_summary(rows, _dist(5), list(range(5)), S, 'protrusion', CUT_REL, CUT_CON)
    verdict, vclass, rate = pp.classify(prof, nulls, nulls['min_run'], nulls['min_run_any_sign'])
    out = pp.build_result(
        _probe(range(5)), rows, prof, [0.01] * 4, verdict, vclass, rate, nulls['min_run'], nulls['min_run_any_sign']
    )
    assert out['mode'] == 'ridge' and out['polarity'] == 'protrusion'
    assert out['stature_m'] == S
    assert (out['n_stations'], out['n_measured'], out['n_unmeasurable'], out['n_qualifying']) == (5, 5, 0, 5)
    assert out['stations'] is rows
    assert out['arc_length_m'] == pytest.approx(0.04)
    assert out['arc_length_frac_stature'] == pytest.approx(0.04 / S)
    assert out['hops_m'] == [0.01] * 4
    assert out['continuity'] == 1.0
    assert out['longest_run'] == 5 and out['run_sign'] == 1
    assert out['run_station_range'] == [0, 4]
    assert out['dominant_sign'] == 1
    assert out['peak_station'] == 0 and out['peak_vertex'] == 0
    assert out['peak_relief_mm'] == pytest.approx(17.0)
    assert out['median_abs_relief_mm'] == pytest.approx(17.0)
    assert out['verdict'] == 'ridge' and out['resolves_relief'] is True
    assert out['verdict_class'] == 'resolved' and out['null_rate'] == nulls['null_rate_resolved']
    assert '%(' not in out['verdict_meaning'] and out['verdict_meaning']


def test_build_result_reports_the_thresholds_and_the_probe_geometry():
    nulls = RIDGE_NULL_P99['point']
    rows = _rows([0.01] * 3, [5.0] * 3)
    prof = pp.profile_summary(rows, _dist(3), list(range(3)), S, 'either', CUT_REL, CUT_CON)
    out = pp.build_result(
        _probe(range(3), mode='point', polarity='either'),
        rows,
        prof,
        [0.01, 0.01],
        'point_only',
        'below_null',
        None,
        nulls['min_run'],
        nulls['min_run_any_sign'],
    )
    assert out['thresholds'] == {
        'min_frac_stature': CUT_REL,
        'min_contrast': CUT_CON,
        'min_run': nulls['min_run'],
        'min_run_any_sign': nulls['min_run_any_sign'],
        'station_provenance': 'MEASURED-NULL curvature.RELIEF_NULL_P99',
        'run_provenance': 'MEASURED-NULL ridge.ridge_null',
    }
    assert out['geometry'] == {
        'core_frac': 0.01,
        'gap_frac': 0.02,
        'width_frac': 0.03,
        'along_stations': 2,
        'point_radius_frac': 0.015,
    }
    assert out['resolves_relief'] is False


def test_build_result_of_an_unmeasured_curve_reports_no_peak():
    nulls = RIDGE_NULL_P99['ridge']
    rows = _rows([None] * 5, [None] * 5)
    prof = pp.profile_summary(rows, _dist(5), list(range(5)), S, 'protrusion', CUT_REL, CUT_CON)
    out = pp.build_result(
        _probe(range(5)),
        rows,
        prof,
        [0.01] * 4,
        'unmeasurable',
        'no_verdict',
        None,
        nulls['min_run'],
        nulls['min_run_any_sign'],
    )
    assert out['peak_station'] == -1
    assert out['peak_vertex'] is None
    assert out['peak_relief_mm'] is None and out['peak_contrast'] is None
    assert out['median_abs_relief_mm'] is None
    assert out['run_station_range'] is None and out['run_stations'] == []
    assert out['dominant_sign'] == 0
    assert out['continuity'] == 0.0  # divided by max(n_measured, 1), never by zero
