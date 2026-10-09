# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the report helpers split out of ``measure.selftest.main``.

``main`` is now the orchestrator of the report only. The pure arithmetic
(``_age_years``, ``_fmt``) and the arm-mask one-liner are tested on plain
inputs; the two ``report_*`` sections that need only a record and a reference
pack are driven by stubs through ``capsys``. ``report_case``,
``report_convention_comparison`` and ``report_ratios_vs_ansur`` are not covered:
they print a measured record that only a built and sculpted mesh produces.
"""

import pytest

from zyg_workflows.geom.anthro.main_ops.selftest_steps import (
    failure_roster,
    out_spec_and_supersession,
)
from zyg_workflows.geom.anthro.main_ops.selftest import _check
from zyg_workflows.geom.anthro.measure.constants import ARM_SKIN_WEIGHT_THRESHOLD
from zyg_workflows.geom.anthro.measure.selftest import (
    _age_years,
    _arm_mask_summary,
    _fmt,
    report_joint_plausibility,
    report_population_outliers,
)
from zyg_workflows.geom.form.ridge.constants import (
    FAT_INVARIANT_PROBES,
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_P99,
    RIDGE_NULL_SEED_PANEL,
)
from zyg_workflows.geom.form.ridge.selftest import (
    _check_null_mode,
    _ridge_grid,
    check_census_controls,
    check_null_derivation,
    check_resolution_contract,
    check_ridge_polarity,
    check_roster_and_summary,
)


# ── _age_years ────────────────────────────────────────────────────────────────


def test_the_three_anchors_of_makehumans_age_mapping():
    assert _age_years(0.0) == pytest.approx(1.0)
    assert _age_years(0.5) == pytest.approx(25.0)
    assert _age_years(1.0) == pytest.approx(90.0)


def test_the_registrys_two_derived_characters_come_out_at_their_declared_ages():
    # the reason this mapping is verified rather than assumed
    assert _age_years(0.229167) == pytest.approx(12.0, abs=5e-3)
    assert _age_years(0.638462) == pytest.approx(43.0, abs=5e-3)


def test_the_mapping_is_piecewise_and_steeper_above_the_midpoint():
    below = _age_years(0.5) - _age_years(0.4)
    above = _age_years(0.6) - _age_years(0.5)
    assert above > below


def test_the_mapping_is_monotonic_and_accepts_a_string():
    xs = [i / 20.0 for i in range(21)]
    ys = [_age_years(x) for x in xs]
    assert ys == sorted(ys)
    assert _age_years('0.5') == pytest.approx(25.0)


def test_the_seventeen_year_adult_cut_falls_where_the_report_splits_cases():
    # report_joint_plausibility and report_population_outliers both gate on < 17.0
    assert _age_years(0.229167) < 17.0
    assert _age_years(0.4) > 17.0


# ── _fmt ──────────────────────────────────────────────────────────────────────


def test_a_number_is_right_aligned_in_the_default_field():
    assert _fmt(12.345) == '    12.3'
    assert len(_fmt(12.345)) == 8


def test_none_is_a_right_aligned_dash_of_the_same_width():
    assert _fmt(None) == '       -'
    assert len(_fmt(None)) == len(_fmt(1.0))


def test_the_width_and_the_precision_are_honoured():
    assert _fmt(12.345, 10, 3) == '    12.345'
    assert _fmt(None, 4) == '   -'
    assert _fmt(1.0, 6, 0) == '     1'


def test_a_value_wider_than_the_field_is_not_truncated():
    assert _fmt(123456789.5, 4, 1) == '123456789.5'


# ── _arm_mask_summary ─────────────────────────────────────────────────────────


def test_a_record_with_no_arm_mask_block_says_so_rather_than_claiming_a_clean_run():
    assert _arm_mask_summary({}) == 'no sliced measurement carried an arm_mask block'
    assert _arm_mask_summary({'chest': {'hull_mm': 1.0}}) == 'no sliced measurement carried an arm_mask block'


def test_an_unavailable_mask_reports_the_reason_and_the_count():
    M = {
        'chest': {'arm_mask': {'available': False, 'unavailable_because': 'no skinning weights'}},
        'waist': {'arm_mask': {'available': False, 'unavailable_because': 'no skinning weights'}},
    }
    s = _arm_mask_summary(M)
    assert s.startswith('UNAVAILABLE on 2 of 2 sliced sites')
    assert 'no skinning weights' in s


def test_a_mask_that_changed_nothing_still_says_what_it_did():
    M = {
        'chest': {
            'arm_mask': {
                'available': True,
                'applied': True,
                'contour_points_dropped': 4,
                'changed_the_value': False,
                'max_arm_weight_on_section': 0.123,
            }
        },
    }
    s = _arm_mask_summary(M)
    assert 'ran on 1 torso/head sites' in s
    assert 'dropped 4 contour points' in s
    assert 'changed 0 values' in s
    assert '%.2f' % ARM_SKIN_WEIGHT_THRESHOLD in s
    assert '0.123' in s
    assert 'CHANGED' not in s


def test_a_mask_that_changed_a_value_names_the_site_and_the_old_number():
    M = {
        'chest': {
            'arm_mask': {
                'available': True,
                'applied': True,
                'contour_points_dropped': 6,
                'changed_the_value': True,
                'max_arm_weight_on_section': 0.4,
                'hull_without_mask_mm': 1012.5,
            }
        },
    }
    s = _arm_mask_summary(M)
    assert 'changed 1 values' in s
    assert 'CHANGED: chest (-6 pts, was 1012.50 mm)' in s


def test_a_site_whose_definition_is_the_arm_is_reported_as_measured_but_not_applied():
    M = {
        'chest': {'arm_mask': {'available': True, 'applied': True, 'contour_points_dropped': 0}},
        'upperarm': {'arm_mask': {'available': True, 'applied': False}},
    }
    s = _arm_mask_summary(M)
    assert 'NOT applied on 1 sites' in s
    assert 'upperarm' in s


# ── report_joint_plausibility / report_population_outliers ────────────────────


class _StubRef:
    """The slice of the reference pack the two report sections actually call."""

    def __init__(self, order, bands=None, result=None):
        self.doc = {'mahalanobis': {'order': list(order)}}
        self._bands = bands or {}
        self._result = result or {}

    def mahalanobis(self, supply, _sex):
        return dict(
            self._result,
            k=len(supply),
            used=sorted(supply),
            missing=sorted(set(self.doc['mahalanobis']['order']) - set(supply)),
        )

    def band(self, key, _sex):
        return self._bands[key]


def _case(sex='f', age_frac=0.5):
    return {'sex': sex, 'age_frac': age_frac}


def _result(ratios):
    return (_case(), {'ratios': ratios}, None, None)


def test_the_mahalanobis_line_names_the_supplied_and_the_missing_ratios(capsys):
    ref = _StubRef(
        ['a', 'b', 'c'],
        result={'d2': 1.25, 'pass_': True, 'warn': False, 'thresholds': {'p95': 7.8, 'p99': 11.3}},
    )
    results = {'anny': _result({'a': {'value': 1.0}, 'c': {'value': 2.0}})}
    report_joint_plausibility(ref, results)
    out = capsys.readouterr().out
    assert 'k=2/3' in out
    assert 'd2=1.250' in out
    assert 'pass=True warn=False' in out
    assert 'thr p95=7.800 p99=11.300' in out
    assert 'supplied: a, c' in out
    assert 'MISSING : b' in out


def test_a_child_is_out_of_scope_for_the_adult_joint_model(capsys):
    ref = _StubRef(['a'])
    results = {'abel': (_case(age_frac=0.229167), {'ratios': {'a': {'value': 1.0}}}, None, None)}
    report_joint_plausibility(ref, results)
    out = capsys.readouterr().out
    assert 'CHILD — the adult joint model does not apply' in out
    assert 'd2=' not in out


def test_only_ratios_at_two_sigma_or_worse_are_printed_worst_first(capsys):
    bands = {
        'mild': {'mean': 1.0, 'sd': 1.0},  # z = +1.0, dropped
        'big': {'mean': 1.0, 'sd': 1.0},  # z = +3.0
        'huge': {'mean': 1.0, 'sd': 1.0},  # z = -4.0
    }
    ratios = {
        'mild': {'value': 2.0},
        'big': {'value': 4.0},
        'huge': {'value': -3.0},
    }
    report_population_outliers(_StubRef([], bands=bands), {'anny': _result(ratios)})
    out = capsys.readouterr().out
    assert 'mild' not in out
    assert out.index('huge') < out.index('big')
    assert 'z=-4.00' in out
    assert 'z=+3.00' in out


def test_a_case_with_no_outlier_prints_none_rather_than_nothing(capsys):
    bands = {'quiet': {'mean': 1.0, 'sd': 1.0}}
    report_population_outliers(_StubRef([], bands=bands), {'anny': _result({'quiet': {'value': 1.1}})})
    assert 'none' in capsys.readouterr().out


def test_a_ratio_the_pack_has_no_band_for_is_skipped_not_fatal(capsys):
    bands = {'known': {'mean': 1.0, 'sd': 1.0}}
    ratios = {'known': {'value': 5.0}, 'unknown': {'value': 99.0}}
    report_population_outliers(_StubRef([], bands=bands), {'anny': _result(ratios)})
    out = capsys.readouterr().out
    assert 'known' in out
    assert 'unknown' not in out


def test_a_band_with_zero_spread_is_skipped_rather_than_dividing_by_zero(capsys):
    bands = {'flat': {'mean': 1.0, 'sd': 0.0}}
    report_population_outliers(_StubRef([], bands=bands), {'anny': _result({'flat': {'value': 9.0}})})
    assert 'none' in capsys.readouterr().out


def test_a_ratio_marked_not_survey_comparable_is_never_scored(capsys):
    bands = {'internal': {'mean': 1.0, 'sd': 1.0}}
    ratios = {'internal': {'value': 9.0, 'survey_comparable': False}}
    report_population_outliers(_StubRef([], bands=bands), {'anny': _result(ratios)})
    assert 'none' in capsys.readouterr().out


def test_children_are_left_out_of_the_population_comparison_entirely(capsys):
    bands = {'big': {'mean': 1.0, 'sd': 1.0}}
    results = {'abel': (_case(age_frac=0.229167), {'ratios': {'big': {'value': 9.0}}}, None, None)}
    report_population_outliers(_StubRef([], bands=bands), results)
    out = capsys.readouterr().out
    assert 'abel' not in out
    assert 'big' not in out


# ══════════════════════════════════════════════════════════════════════════════
# form.ridge.selftest — the checks split out of the 409-line ``self_test``
#
# ``self_test`` is now an orchestrator that calls ``check_*`` in the old order.
# Each check used to be a section of one body, so none of this logic had ever
# been run on its own: the fixtures below are the first inputs it ever saw that
# a mesh did not produce. ``check_flat_controls``, ``check_scale_invariance``
# and ``check_facet_gate`` are covered only through ``self_test`` itself — they
# take no record, so there is nothing to feed them that the grid does not.
# ══════════════════════════════════════════════════════════════════════════════

RIDGE_GRID_KW = dict(core_frac=0.03, gap_frac=0.06, width_frac=0.12, along_stations=3)


# ── _ridge_grid ───────────────────────────────────────────────────────────────


def test_the_grid_is_a_quad_mesh_whose_index_map_addresses_every_vertex():
    V, F, idx = _ridge_grid(5, 7, 0.05, 0.12)
    assert V.shape == (35, 3)
    assert F.shape == (24, 4)  # (5-1) * (7-1) quads
    assert idx.shape == (5, 7)
    assert sorted(idx.ravel().tolist()) == list(range(35))


def test_the_ridge_runs_along_y_with_its_crest_at_x_zero():
    V, F, idx = _ridge_grid(5, 7, 0.05, 0.12)
    crest = [V[int(idx[2, j]), 2] for j in range(7)]
    assert crest == pytest.approx([0.05] * 7)  # flat along +y
    assert V[:, 2].max() == pytest.approx(0.05)  # and nowhere higher
    assert V[int(idx[0, 0]), 2] < 0.05  # the flanks fall away


def test_a_negative_amplitude_is_the_exact_mirror_of_the_ridge():
    up = _ridge_grid(5, 7, 0.05, 0.12)[0]
    down = _ridge_grid(5, 7, -0.05, 0.12)[0]
    assert down[:, 2].tolist() == pytest.approx((-up[:, 2]).tolist())
    assert down[:, :2].tolist() == up[:, :2].tolist()


def test_tilt_adds_a_first_order_trend_and_scale_multiplies_every_vertex():
    flat = _ridge_grid(5, 7, 0.0, 0.12)[0]
    assert flat[:, 2].tolist() == pytest.approx([0.0] * 35)
    tilted = _ridge_grid(5, 7, 0.0, 0.12, tilt=0.25)[0]
    assert tilted[:, 2].tolist() == pytest.approx((0.25 * tilted[:, 0]).tolist())
    scaled = _ridge_grid(5, 7, 0.05, 0.12, scale=0.5)[0]
    nominal = _ridge_grid(5, 7, 0.05, 0.12)[0]
    assert scaled.ravel().tolist() == pytest.approx((0.5 * nominal).ravel().tolist())


# ── check_ridge_polarity ──────────────────────────────────────────────────────


def test_a_gaussian_ridge_and_its_mirror_are_recorded_under_three_keys():
    out = {}
    r = check_ridge_polarity(out, 41, 41, RIDGE_GRID_KW)
    assert sorted(out) == ['furrow', 'polarity_agnostic', 'ridge']
    assert out['ridge']['verdict'] == 'ridge'
    assert out['furrow']['verdict'] == 'furrow'
    assert r['verdict'] == 'ridge'
    assert r['resolves_relief'] is True


def test_the_mirror_pair_score_the_same_relief_with_opposite_sign():
    out = {}
    check_ridge_polarity(out, 41, 41, RIDGE_GRID_KW)
    pa = out['polarity_agnostic']
    assert pa['rel_diff'] < 1e-9
    assert pa['ridge_run'] == pa['furrow_run']
    assert pa['ridge_sign'] == -pa['furrow_sign']


# ── check_resolution_contract ─────────────────────────────────────────────────


def _resolving(verdict='ridge'):
    return {'verdict': verdict, 'resolves_relief': True, 'verdict_class': 'resolved'}


def _not_resolving(verdict='flat'):
    return {'verdict': verdict, 'resolves_relief': False, 'verdict_class': 'below_null'}


def test_the_contract_records_the_three_verdict_classes_and_the_null_rates():
    out = {}
    check_resolution_contract(out, _resolving(), _not_resolving(), _not_resolving(), _not_resolving('point_only'))
    c = out['resolution_contract']
    assert 'ridge' in c['resolved']
    assert 'point_only' in c['below_null'] and 'flat' in c['below_null']
    assert c['resolved_null_rate_ridge_mode'] <= c['point_only_null_rate_ridge_mode']


def test_a_ridge_that_does_not_report_itself_as_resolving_is_refused():
    with pytest.raises(RuntimeError, match='does not report itself as resolving'):
        check_resolution_contract({}, _not_resolving('ridge'), _not_resolving(), _not_resolving(), _not_resolving())


def test_a_plane_that_claims_to_resolve_relief_is_refused():
    with pytest.raises(RuntimeError, match='a plane reports itself as resolving relief'):
        check_resolution_contract({}, _resolving(), _resolving('flat'), _not_resolving(), _not_resolving())


def test_a_below_floor_control_that_claims_to_resolve_relief_is_refused():
    with pytest.raises(RuntimeError, match='below-floor control reports resolves_relief=True'):
        check_resolution_contract({}, _resolving(), _not_resolving(), _not_resolving(), _resolving('point_only'))


# ── _check_null_mode / check_null_derivation ──────────────────────────────────


@pytest.mark.parametrize('mode', ['ridge', 'point'])
def test_each_shipped_mode_re_derives_from_the_histograms_shipped_beside_it(mode):
    _check_null_mode(mode)  # raises RuntimeError on any disagreement


def _with_ridge(monkeypatch, **changes):
    tampered = dict(RIDGE_NULL_P99, ridge=dict(RIDGE_NULL_P99['ridge'], **changes))
    monkeypatch.setattr('zyg_workflows.geom.form.ridge.selftest.RIDGE_NULL_P99', tampered)


def test_a_min_run_nudged_below_the_pooled_estimate_is_refused(monkeypatch):
    _with_ridge(monkeypatch, min_run=1)
    with pytest.raises(RuntimeError, match='BELOW the pooled estimate'):
        _check_null_mode('ridge')


def test_a_min_run_above_the_panel_upper_bound_is_refused(monkeypatch):
    _with_ridge(monkeypatch, min_run=RIDGE_NULL_P99['ridge']['min_run'] + 1)
    with pytest.raises(RuntimeError, match='panel upper bound'):
        _check_null_mode('ridge')


def test_a_station_cut_below_the_isotropic_floor_is_refused(monkeypatch):
    _with_ridge(monkeypatch, panel_cut_frac_min_median_max=(0.0, 0.0, 0.0), station_min_frac_stature=0.0)
    with pytest.raises(RuntimeError, match='BELOW curvature.RELIEF_NULL_P99'):
        _check_null_mode('ridge')


def test_the_derivation_record_carries_the_panel_the_rule_and_the_superseded_value():
    out = {}
    check_null_derivation(out)
    d = out['null_derivation']
    assert d['seeds'] == len(RIDGE_NULL_SEED_PANEL)
    assert d['pools_scored'] == RIDGE_NULL_P99['derivation']['pools_scored']
    assert d['ridge_fpr'] <= RIDGE_NULL_ALPHA
    assert d['superseded_ridge_min_run'] < d['ridge_min_run']
    assert d['superseded_fpr'] > RIDGE_NULL_ALPHA


# ── check_roster_and_summary ──────────────────────────────────────────────────


def test_the_p63_denominator_stays_whole_and_names_its_unprobed_regions():
    out = {}
    check_roster_and_summary(out)
    assert out['afs_p63']['n_page_regions'] == 8
    assert out['afs_p63']['unprobed_on_body'] == ['facial_mask', 'nape', 'spine_midline']
    assert out['afs_p63']['n_body_probes'] == len(FAT_INVARIANT_PROBES)


def test_a_never_probed_window_is_counted_apart_from_a_window_found_flat():
    out = {}
    check_roster_and_summary(out)
    c = out['summary_sentence_control']
    assert c == {'n_resolved': 0, 'n_never_probed': 1, 'names_the_empty_window': True}


# ── check_census_controls ─────────────────────────────────────────────────────


def test_two_windows_sharing_a_vertex_are_one_independent_observation():
    out = {}
    check_census_controls(out)
    assert out['independence_control'] == {'n_windows': 3, 'clusters': 2, 'max_disjoint': 2}


def test_a_census_missing_every_probe_but_one_declares_itself_incomplete():
    out = {}
    check_census_controls(out)
    c = out['fat_invariant_incomplete_control']
    assert c['absent'] == len(FAT_INVARIANT_PROBES) - 1
    assert c['declared'] == 'CENSUS INCOMPLETE'


# ── main_ops.selftest: _check and the host-independent steps ──────────────────


def _recorder():
    """Return ``(check, records)``: the reporter the steps take, and what it recorded."""
    records = []

    def check(label, cond, detail=''):
        records.append((label, bool(cond), detail))

    return check, records


def test_a_passing_check_prints_ok_and_records_no_failure(capsys):
    fails = []
    _check(fails, 'the pack loads', True, '42 ratios')
    out = capsys.readouterr().out
    assert out.startswith('  the pack loads')
    assert out.rstrip().endswith('ok  42 ratios')
    assert fails == []


def test_a_failing_check_prints_FAIL_and_records_the_label(capsys):
    fails = []
    _check(fails, 'the pack loads', False)
    assert 'FAIL' in capsys.readouterr().out
    assert fails == ['the pack loads']


def test_the_label_column_is_padded_so_the_verdicts_line_up(capsys):
    fails = []
    _check(fails, 'short', True)
    _check(fails, 'a much longer label than the first one', True)
    first, second = capsys.readouterr().out.splitlines()
    assert first.index('ok') == second.index('ok')


def test_the_failure_roster_step_passes_every_one_of_its_checks():
    # step 8's first half is pure: F7's exit-code ladder and the roster rendering,
    # which is why it can run here with no mesh, no reference pack and no gates
    check, records = _recorder()
    failure_roster(check)
    assert [label for label, ok, _ in records if not ok] == []
    assert len(records) == 11


def test_the_out_spec_step_passes_every_check_and_leaves_no_file_behind(tmp_path):
    check, records = _recorder()
    out_spec_and_supersession(check, str(tmp_path), 'selftest_probe')
    assert [label for label, ok, _ in records if not ok] == []
    assert len(records) == 17
    assert list(tmp_path.iterdir()) == []
