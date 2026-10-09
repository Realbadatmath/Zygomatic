# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `stage_residual` (scan_ingest STAGE e).

Each test pins one behaviour the 400-line function used to hide: the Nyquist refusal, the
ZYG_SCAN_FILTER validation, the non-converged-calibration refusal, the coverage-normalised
divide (and the zero-fill audit it is measured against), the probe bookkeeping and the
shape of the emitted document. The probe dispatch was a closure before this split, so
`test_probe_active_umbrella_*` is the first time that logic is exercised on its own.
"""

import math

import numpy as np
import pytest

from zyg_workflows.geom.scan_ingest.constants import (
    SCHEMA,
    SHRINKWRAP_MAX_FRAC,
    SHRINKWRAP_SUPPORT_FRAC,
    ScanIngestError,
)
from zyg_workflows.geom.scan_ingest.residual_lowpass import _adjacency
from zyg_workflows.geom.scan_ingest.residual_steps import (
    ProbeTarget,
    ResidualSurface,
    Shrinkwrap,
    _coverage_hole_report,
    _mean_edge_length,
    _prepare_surface,
    _probe_active,
    _probe_entry,
    _probe_sweep,
    _proportion_leakage,
    _require_calibration_converged,
    _residual_document,
    _residual_fields,
    _resolve_filter_kind,
    _shrinkwrap,
)


def _unit_quad():
    """A single axis-aligned unit quad in the z = 0 plane: four edges of length 1."""
    v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    f = np.array([[0, 1, 2, 3]])
    return v, f


def _grid(n=8, pitch=0.05):
    """An n x n quad grid in the x/z plane, pitch metres apart — a mesh the umbrella
    operator can actually diffuse a z-direction sinusoid over."""
    xs = np.arange(n) * pitch
    v = np.array([[x, 0.0, z] for z in xs for x in xs])
    faces = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            faces.append([a, a + 1, a + n + 1, a + n])
    return v, np.array(faces)


# --- _mean_edge_length ------------------------------------------------------------


def test_mean_edge_length_of_a_unit_quad_is_one():
    v, f = _unit_quad()
    assert _mean_edge_length(v, f) == pytest.approx(1.0)


def test_mean_edge_length_scales_with_the_mesh():
    v, f = _unit_quad()
    assert _mean_edge_length(3.0 * v, f) == pytest.approx(3.0)


def test_mean_edge_length_averages_unequal_edges():
    # a 2 x 1 rectangle: edges 2, 1, 2, 1 -> mean 1.5
    v = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    assert _mean_edge_length(v, np.array([[0, 1, 2, 3]])) == pytest.approx(1.5)


# --- _prepare_surface -------------------------------------------------------------


def test_prepare_surface_derives_the_band_from_stature_and_mean_edge():
    v, f = _grid(n=8, pitch=0.05)  # stature = z-extent = 0.35 m, mean edge = 0.05 m
    s = _prepare_surface(v, f, 0, 0.5, verbose=False)
    assert isinstance(s, ResidualSurface)
    assert s.stature == pytest.approx(0.35)
    assert s.mean_edge == pytest.approx(0.05)
    assert s.nyquist == pytest.approx(0.10)
    assert s.lam_cut == pytest.approx(0.175)
    assert s.lam_cut > s.nyquist
    assert s.normals.shape == v.shape


def test_prepare_surface_refuses_a_cutoff_at_or_below_nyquist():
    v, f = _grid(n=8, pitch=0.05)  # nyquist 0.10 m; 0.08 * 0.35 = 0.028 m
    with pytest.raises(ScanIngestError) as e:
        _prepare_surface(v, f, 0, 0.08, verbose=False)
    assert 'Nyquist limit' in str(e.value)
    assert 'Raise subdiv_level' in str(e.value)


# --- _shrinkwrap ------------------------------------------------------------------


def test_shrinkwrap_measures_displacement_along_the_cage_normal():
    v, f = _unit_quad()
    surface = ResidualSurface(
        sv=v,
        sf=f,
        normals=np.tile([0.0, 0.0, 1.0], (4, 1)),
        mean_edge=1.0,
        nyquist=2.0,
        stature=10.0,
        lam_cut=3.0,
    )
    # the "scan" sits 0.02 m above each cage vertex
    scan = v + np.array([0.0, 0.0, 0.02])
    sw = _shrinkwrap(surface, scan, 'poisson_mesh', verbose=False)
    assert isinstance(sw, Shrinkwrap)
    assert sw.backend == 'nearest_point/poisson_mesh'
    assert sw.d == pytest.approx(np.full(4, 0.02))
    # support 0.02 <= SHRINKWRAP_SUPPORT_FRAC * 10 = 0.1 -> fully covered, nothing beyond max
    assert sw.covered.all()
    assert sw.d_used == pytest.approx(sw.d)
    assert not sw.far.any()
    assert SHRINKWRAP_SUPPORT_FRAC * surface.stature > 0.02


def test_shrinkwrap_marks_unsupported_vertices_uncovered_and_zeroes_them():
    v, f = _unit_quad()
    surface = ResidualSurface(
        sv=v,
        sf=f,
        normals=np.tile([0.0, 0.0, 1.0], (4, 1)),
        mean_edge=1.0,
        nyquist=2.0,
        stature=1.0,
        lam_cut=0.5,
    )
    # support frac * 1.0 = 0.01 m: only the first vertex has a scan sample close enough
    scan = np.array([[0.0, 0.0, 0.005], [0.0, 0.0, 0.04]])
    sw = _shrinkwrap(surface, scan, 'points', verbose=False)
    assert list(sw.covered) == [True, False, False, False]
    assert sw.d_used[1:] == pytest.approx(np.zeros(3))
    assert sw.d_used[0] == pytest.approx(0.005)
    # vertex 1 is 1.0 m away laterally, far beyond SHRINKWRAP_MAX_FRAC * stature
    assert SHRINKWRAP_MAX_FRAC * surface.stature == pytest.approx(0.05)


# --- _resolve_filter_kind ---------------------------------------------------------


def test_resolve_filter_kind_defaults_to_butterworth(monkeypatch):
    monkeypatch.delenv('ZYG_SCAN_FILTER', raising=False)
    assert _resolve_filter_kind() == 'butterworth'


def test_resolve_filter_kind_accepts_the_legacy_umbrella_path(monkeypatch):
    monkeypatch.setenv('ZYG_SCAN_FILTER', '  Umbrella \n')
    assert _resolve_filter_kind() == 'umbrella'


def test_resolve_filter_kind_refuses_an_unknown_separator(monkeypatch):
    monkeypatch.setenv('ZYG_SCAN_FILTER', 'gaussian')
    with pytest.raises(ScanIngestError) as e:
        _resolve_filter_kind()
    assert 'ZYG_SCAN_FILTER' in str(e.value)


# --- _require_calibration_converged ----------------------------------------------


def _cal(converged, hit_ceiling=False):
    return {
        'converged': converged,
        'calibration_rounds': 4,
        'calibrated_response_at_cutoff': 0.6163,
        'target_response_at_cutoff': 0.5,
        'hit_iteration_ceiling': hit_ceiling,
        'iteration_ceiling': 4000,
    }


def test_require_calibration_converged_is_silent_when_the_filter_reached_its_cutoff():
    assert _require_calibration_converged(_cal(True), 2969, 0.1344) is None


def test_require_calibration_converged_refuses_a_filter_short_of_its_cutoff():
    with pytest.raises(ScanIngestError) as e:
        _require_calibration_converged(_cal(False), 4000, 0.1344)
    msg = str(e.value)
    assert 'did not reach its stated cutoff' in msg
    assert '0.6163' in msg
    assert '134.4 mm' in msg
    assert 'ITERATION CEILING' not in msg


def test_require_calibration_converged_names_the_ceiling_when_the_ceiling_bound_it():
    with pytest.raises(ScanIngestError) as e:
        _require_calibration_converged(_cal(False, hit_ceiling=True), 4000, 0.1344)
    assert 'ITERATION CEILING of 4000' in str(e.value)


# --- _residual_fields -------------------------------------------------------------


def _sw(d_used, covered):
    covered = np.asarray(covered, bool)
    return Shrinkwrap(
        backend='nearest_point/test',
        d=np.asarray(d_used, np.float64),
        support=np.zeros(len(covered)),
        covered=covered,
        far=np.zeros(len(covered), bool),
        d_used=np.asarray(d_used, np.float64),
    )


def test_residual_fields_divides_the_field_by_the_smoothed_coverage_weight():
    sw = _sw([1.0, 2.0, 3.0], [True, True, True])
    # a low-pass that halved both the field and the mask: low must come back undivided
    stacked = np.column_stack([np.array([0.5, 1.0, 1.5]), np.full(3, 0.5)])
    fields = _residual_fields(sw, stacked)
    assert fields.low == pytest.approx([1.0, 2.0, 3.0])
    assert fields.resid == pytest.approx([0.0, 0.0, 0.0])


def test_residual_fields_zeroes_the_residual_outside_coverage():
    sw = _sw([1.0, 2.0, 0.0], [True, True, False])
    stacked = np.column_stack([np.array([0.5, 0.5, 0.5]), np.array([1.0, 1.0, 1.0])])
    fields = _residual_fields(sw, stacked)
    assert fields.resid[2] == 0.0
    assert fields.resid[:2] == pytest.approx([0.5, 1.5])


def test_residual_fields_measures_what_the_rejected_zero_fill_would_have_added():
    # weight 0.5 at the hole rim: the normalised low-pass is twice the zero-filled one
    sw = _sw([1.0, 1.0, 0.0], [True, True, False])
    stacked = np.column_stack([np.array([0.4, 0.4, 0.2]), np.array([0.5, 1.0, 0.5])])
    fields = _residual_fields(sw, stacked)
    assert fields.low[0] == pytest.approx(0.8)  # 0.4 / 0.5
    assert fields.resid_zerofill[0] == pytest.approx(0.6)  # 1.0 - 0.4, the old path
    assert fields.hole_delta[0] == pytest.approx(-0.4)
    assert len(fields.hd) == 2  # covered vertices only


def test_residual_fields_guards_the_divide_against_a_zero_weight():
    sw = _sw([1.0, 1.0], [True, True])
    stacked = np.column_stack([np.array([5.0, 0.4]), np.array([0.0, 1.0])])
    fields = _residual_fields(sw, stacked)
    assert fields.low[0] == 0.0
    assert np.isfinite(fields.resid).all()


# --- _probe_entry / _probe_active / _probe_sweep ----------------------------------


def test_probe_entry_reports_the_measurement_beside_the_algebra():
    e = _probe_entry(0.5376, 0.705, 0.549)
    assert e['wavelength_mm'] == pytest.approx(537.6)
    assert e['lowpass_amplitude_ratio'] == pytest.approx(0.705)
    assert e['kept_by_residual'] == pytest.approx(0.549)
    assert e['one_minus_lowpass_ratio'] == pytest.approx(0.295)
    # the whole point of the pair: the algebra is NOT the measurement
    assert e['one_minus_lowpass_ratio'] != pytest.approx(e['kept_by_residual'])
    assert '0.295 vs 0.549' in e['one_minus_lowpass_ratio_is']


def _umbrella_target(iters=40):
    """An umbrella probe target on a tilted grid.

    The grid is tilted out of the x/z plane because `_probe_response` averages the probe
    over all three coordinate directions: on a mesh with a constant y the y column of the
    probe field is flat, its RMS is zero and it contributes a hard 0 to the mean.
    """
    v, f = _grid(n=10, pitch=0.02)
    v = v.copy()
    v[:, 1] = 0.37 * v[:, 0] + 0.11 * v[:, 2]
    return ProbeTarget(kind='umbrella', sv=v, adjacency=_adjacency(len(v), f), iters=iters)


def test_probe_active_umbrella_passes_long_wavelengths_and_rejects_short_ones():
    target = _umbrella_target()
    long_lp, long_res = _probe_active(target, 1.0)
    short_lp, short_res = _probe_active(target, 0.05)
    assert long_lp > short_lp
    assert short_res > long_res
    for x in (long_lp, long_res, short_lp, short_res):
        assert 0.0 <= x <= 1.0 + 1e-9


def test_probe_active_umbrella_at_zero_iterations_is_the_identity():
    target = _umbrella_target(iters=0)
    lp, res = _probe_active(target, 0.1)
    assert lp == pytest.approx(1.0)
    assert res == pytest.approx(0.0, abs=1e-12)


def test_probe_sweep_measures_the_five_published_wavelengths():
    probe = _probe_sweep(_umbrella_target(), 0.2)
    assert set(probe) == {
        'quarter_cutoff',
        'half_cutoff',
        'at_cutoff',
        'double_cutoff',
        'quadruple_cutoff',
    }
    assert probe['at_cutoff']['wavelength_mm'] == pytest.approx(200.0)
    assert probe['quarter_cutoff']['wavelength_mm'] == pytest.approx(50.0)
    assert probe['quadruple_cutoff']['wavelength_mm'] == pytest.approx(800.0)
    # detail is kept, proportion is not
    assert probe['quarter_cutoff']['kept_by_residual'] > probe['quadruple_cutoff']['kept_by_residual']


# --- _proportion_leakage / _coverage_hole_report ----------------------------------


def _probe_stub():
    return {
        tag: _probe_entry(lam, lp, res)
        for tag, lam, lp, res in (
            ('quarter_cutoff', 0.0336, 0.1, 0.9),
            ('half_cutoff', 0.0672, 0.3, 0.7),
            ('at_cutoff', 0.1344, 0.5, 0.5),
            ('double_cutoff', 0.2688, 0.8, 0.3),
            ('quadruple_cutoff', 0.5376, 0.705, 0.1),
        )
    }


def test_proportion_leakage_reports_the_measured_survival_and_its_selectivity():
    pl = _proportion_leakage(_probe_stub())
    assert pl['probe_wavelength_mm'] == pytest.approx(537.6)
    assert pl['fraction_surviving_into_residual'] == pytest.approx(0.1)
    assert pl['detail_probe_wavelength_mm'] == pytest.approx(33.6)
    assert pl['detail_fraction_kept'] == pytest.approx(0.9)
    assert pl['selectivity_detail_over_proportion'] == pytest.approx(9.0)


def test_proportion_leakage_cannot_divide_by_a_zero_leak():
    probe = _probe_stub()
    probe['quadruple_cutoff'] = _probe_entry(0.5376, 1.0, 0.0)
    pl = _proportion_leakage(probe)
    assert math.isfinite(pl['selectivity_detail_over_proportion'])


def test_coverage_hole_report_converts_the_zero_fill_audit_to_millimetres():
    hd = np.array([0.001, -0.002, 0.003])
    r = _coverage_hole_report(0.002, 100, hd)
    assert r['method'].startswith('normalised diffusion')
    assert r['zerofill_would_have_added_max_mm'] == pytest.approx(3.0)
    assert r['zerofill_would_have_added_rms_mm'] == pytest.approx(1e3 * np.sqrt((hd**2).mean()))
    # diffusion length = h * sqrt(2 * alpha * iters), alpha = 0.5 -> 0.002 * 10 m = 20 mm
    assert r['diffusion_length_mm'] == pytest.approx(20.0)


def test_coverage_hole_report_is_zero_when_nothing_is_covered():
    r = _coverage_hole_report(0.002, 100, np.array([]))
    assert r['zerofill_would_have_added_rms_mm'] == 0.0
    assert r['zerofill_would_have_added_p99_mm'] == 0.0
    assert r['zerofill_would_have_added_max_mm'] == 0.0


# --- _residual_document -----------------------------------------------------------


def test_residual_document_has_the_shape_the_stage_has_always_written():
    v, f = _grid(n=4, pitch=0.05)
    surface = ResidualSurface(
        sv=v,
        sf=f,
        normals=np.tile([0.0, 1.0, 0.0], (len(v), 1)),
        mean_edge=0.05,
        nyquist=0.10,
        stature=1.686,
        lam_cut=0.1344,
    )
    sw = _sw([0.001] * len(v), [True] * len(v))
    stacked = np.column_stack([np.full(len(v), 0.0005), np.ones(len(v))])
    fields = _residual_fields(sw, stacked)
    doc = _residual_document(
        surface,
        sw,
        fields,
        _probe_stub(),
        {'kind': 'umbrella', 'iters': 7},
        _cal(True),
        7,
        '/tmp/does-not-need-to-exist/residual.npz',
        target_character='female_default',
        subdiv_level=1,
        cutoff_frac=0.08,
        t0=0.0,
    )
    assert doc['schema'] == SCHEMA
    assert doc['stage'] == 'residual'
    assert doc['status'] == 'ok'
    assert doc['target_character'] == 'female_default'
    assert doc['subdiv_level'] == 1
    assert doc['surface_vertices'] == len(v)
    assert doc['cutoff_wavelength_mm'] == pytest.approx(134.4)
    assert doc['nyquist_wavelength_mm'] == pytest.approx(100.0)
    assert doc['representable_detail_band_mm'] == pytest.approx([100.0, 134.4])
    assert doc['filter']['kind'] == 'umbrella'
    assert doc['lowpass']['iterations'] == 7
    assert doc['lowpass']['measured_filter_response'] is not None
    assert doc['shrinkwrap']['coverage'] == pytest.approx(1.0)
    assert doc['shrinkwrap']['vertices_uncovered'] == 0
    assert doc['residual_mm']['rms'] == pytest.approx(0.5)  # 0.001 - 0.0005 m = 0.5 mm
    assert doc['proportion_leakage']['fraction_surviving_into_residual'] == pytest.approx(0.1)
    assert doc['coverage_hole_handling']['method'].startswith('normalised diffusion')
    assert doc['residual_npz'].endswith('residual.npz')


def test_residual_document_reports_none_for_displacement_when_nothing_is_covered():
    v, f = _grid(n=4, pitch=0.05)
    surface = ResidualSurface(
        sv=v,
        sf=f,
        normals=np.tile([0.0, 1.0, 0.0], (len(v), 1)),
        mean_edge=0.05,
        nyquist=0.10,
        stature=1.686,
        lam_cut=0.1344,
    )
    sw = _sw([0.0] * len(v), [False] * len(v))
    stacked = np.column_stack([np.zeros(len(v)), np.zeros(len(v))])
    fields = _residual_fields(sw, stacked)
    doc = _residual_document(
        surface,
        sw,
        fields,
        _probe_stub(),
        {'kind': 'umbrella'},
        _cal(True),
        7,
        '/tmp/does-not-need-to-exist/residual.npz',
        target_character='female_default',
        subdiv_level=0,
        cutoff_frac=0.08,
        t0=0.0,
    )
    assert doc['raw_displacement_mm']['p50'] is None
    assert doc['raw_displacement_mm']['p99'] is None
    assert doc['residual_mm']['rms'] == 0.0
    assert doc['shrinkwrap']['vertices_uncovered'] == len(v)
