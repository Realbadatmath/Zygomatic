# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `ridge_null` was split into.

`ridge_null` was one 335-line body whose scoring stage was a closure over the pool
profiles, so the station cut, the run distribution, the three pool rates and the
re-scoring at the unfloored p99 had never been exercised without building a mesh first.
Each stage now lives in `zyg_workflows.geom.form.ridge.null_stages` and takes explicit
arguments; these tests drive them with plain lists and small numpy arrays — no mesh, no
geometry, no GPU.
"""

from __future__ import annotations

import numpy as np

from zyg_workflows.geom.form.ridge import null as NU
from zyg_workflows.geom.form.ridge import null_stages as ST
from zyg_workflows.geom.form.ridge.constants import (
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_P99,
    STATION_MIN_CONTRAST,
    STATION_MIN_FRAC_STATURE,
)

Q = (50, 75, 90, 95, 99)


def _profile(rel, con, ok=None, hp=None):
    """One candidate profile tuple as `ridge_search(collect=True)` hands it over."""
    rel = np.asarray(rel, float)
    n = len(rel)
    return (
        rel,
        np.asarray(con, float),
        np.ones(n, bool) if ok is None else np.asarray(ok, bool),
        np.full(n, 0.1) if hp is None else np.asarray(hp, float),
    )


# ── percentile_summary: the one shape every distribution is reported in ────────────


def test_percentile_summary_is_none_for_an_empty_distribution():
    assert ST.percentile_summary([], Q) is None
    assert ST.percentile_summary(np.asarray([]), Q) is None


def test_percentile_summary_reports_median_max_and_the_requested_percentiles():
    out = ST.percentile_summary([1.0, 2.0, 3.0], (50, 99))
    assert list(out) == ['median', 'max', 'p50', 'p99']
    assert (out['median'], out['max'], out['p50']) == (2.0, 3.0, 2.0)


def test_percentile_summary_adds_the_minimum_only_when_asked():
    # The facet ratios are quoted from below, the station magnitudes from above.
    assert 'min' not in ST.percentile_summary([1.0, 2.0], Q)
    out = ST.percentile_summary([1.0, 2.0], (1, 5), with_min=True)
    assert list(out) == ['median', 'min', 'max', 'p1', 'p5']
    assert out['min'] == 1.0


# ── station_record: the cut can only ever be RAISED ───────────────────────────────


def test_a_quiet_mesh_is_scored_at_the_published_cage_cut():
    rec, cut_f, cut_c = ST.station_record([['a'], ['b']], 3, [30, 31], [0.001, 0.002], [1.0, 2.0], Q)
    assert (cut_f, cut_c) == (STATION_MIN_FRAC_STATURE, STATION_MIN_CONTRAST)
    assert rec['station_cut_used']['raised_above_published'] is False
    assert (rec['n_pools'], rec['skipped'], rec['n_stations_scored']) == (2, 3, 2)
    assert rec['pool_size'] == {'median': 30.5, 'min': 30, 'max': 31}


def test_a_noisy_mesh_raises_the_cut_to_its_own_p99():
    rec, cut_f, cut_c = ST.station_record([['a']], 0, [30], [0.01] * 100, [50.0] * 100, Q)
    assert (cut_f, cut_c) == (0.01, 50.0)
    assert cut_f > STATION_MIN_FRAC_STATURE and cut_c > STATION_MIN_CONTRAST
    assert rec['station_cut_used']['raised_above_published'] is True


def test_station_record_keys_are_written_in_the_published_order():
    rec, _, _ = ST.station_record([['a']], 0, [30], [0.001], [1.0], Q)
    assert list(rec) == [
        'n_pools',
        'skipped',
        'pool_size',
        'n_stations_scored',
        'abs_station_relief_frac',
        'abs_station_contrast',
        'station_cut_used',
    ]


def test_a_mesh_with_no_usable_pool_still_yields_the_published_cut():
    rec, cut_f, cut_c = ST.station_record([], 5, [], [], [], Q)
    assert (cut_f, cut_c) == (STATION_MIN_FRAC_STATURE, STATION_MIN_CONTRAST)
    assert rec['abs_station_relief_frac'] is None
    assert (rec['pool_size']['min'], rec['pool_size']['max']) == (0, 0)
    assert np.isnan(rec['pool_size']['median'])


# ── score_pools_at: the closure that was never tested in isolation ────────────────


def test_a_fully_qualifying_same_sign_profile_runs_the_whole_length():
    runs, cont, spans, anys = ST.score_pools_at(
        [[_profile([0.01] * 5, [10.0] * 5, hp=[0.1, 0.2, 0.3, 0.4, 0.5])]], 0.005, 5.0, 'either', 2.0
    )
    assert runs == [5] and anys == [5]
    # The span is the arc BETWEEN the stations of the run: hp[0:4].sum() / stature.
    assert spans == [(0.1 + 0.2 + 0.3 + 0.4) / 2.0]
    assert cont == [1.0]


def test_an_alternating_sign_profile_has_no_same_sign_run_but_a_full_any_sign_one():
    # A run is CONSECUTIVE, QUALIFYING and SAME-SIGN; 'mixed_strip' is scored off the
    # any-sign run, which is >= the same-sign one by construction.
    runs, _cont, spans, anys = ST.score_pools_at(
        [[_profile([0.01, -0.01, 0.01, -0.01, 0.01], [10.0] * 5)]], 0.005, 5.0, 'either', 2.0
    )
    assert (runs, anys) == ([1], [5])
    assert spans == [0.0]


def test_an_unmeasurable_station_breaks_the_run():
    runs, _c, _s, anys = ST.score_pools_at(
        [[_profile([0.01] * 5, [10.0] * 5, ok=[True, True, False, True, True])]], 0.005, 5.0, 'either', 2.0
    )
    assert (runs, anys) == ([2], [2])


def test_a_cut_above_every_station_scores_nothing():
    runs, cont, spans, anys = ST.score_pools_at([[_profile([0.01] * 5, [10.0] * 5)]], 1.0, 1e9, 'either', 2.0)
    assert (runs, cont, spans, anys) == ([0], [0.0], [0.0], [0])


def test_score_pools_at_keeps_the_best_candidate_of_each_pool():
    pool = [_profile([0.01, 0.0, 0.0], [10.0, 0.0, 0.0]), _profile([0.01] * 3, [10.0] * 3)]
    runs, _c, _s, anys = ST.score_pools_at([pool], 0.005, 5.0, 'either', 2.0)
    assert (runs, anys) == ([3], [3])


def test_scoring_no_pools_yields_four_empty_lists():
    assert ST.score_pools_at([], 0.005, 5.0, 'either', 2.0) == ([], [], [], [])


# ── run_distributions: counts are additive, interpolated percentiles are not ──────


def test_run_distributions_writes_the_raw_discrete_histograms():
    rec = {}
    ST.run_distributions(rec, [0, 1, 2, 5, 5, 6], [0.1] * 6, [0.0] * 6, [0, 2, 3, 6, 6, 7], Q)
    assert rec['best_longest_run_hist'] == {0: 1, 1: 1, 2: 1, 5: 2, 6: 1}
    assert rec['best_longest_run_any_sign_hist'] == {0: 1, 2: 1, 3: 1, 6: 2, 7: 1}


def test_run_distributions_writes_both_min_run_estimators():
    rec = {}
    ST.run_distributions(rec, [0, 1, 2, 5, 5, 6], [0.1] * 6, [0.0] * 6, [0, 2, 3, 6, 6, 7], Q)
    # the superseded interpolated reading is kept beside the discrete one for comparison
    assert rec['implied_min_run'] == 7
    assert rec['discrete_min_run'] == 7
    assert rec['discrete_min_run_any_sign'] == 8
    assert rec['implied_min_run_any_sign'] == 8


def test_run_distributions_writes_its_keys_in_the_published_order():
    rec = {}
    ST.run_distributions(rec, [1], [0.1], [0.0], [1], Q)
    assert list(rec) == [
        'best_longest_run',
        'best_continuity',
        'best_run_span_frac_stature',
        'best_longest_run_any_sign',
        'best_longest_run_hist',
        'best_longest_run_any_sign_hist',
        'implied_min_run',
        'discrete_min_run',
        'discrete_min_run_any_sign',
        'implied_min_run_any_sign',
    ]


# ── pool_rates: the three rates a caller has to see ───────────────────────────────


def test_pool_rates_are_quoted_at_the_shipped_threshold_floor():
    rec = {}
    runs, anys = [0, 1, 2], [0, 1, 2]
    ST.run_distributions(rec, runs, [0.1] * 3, [0.0] * 3, anys, Q)
    mr, mra = ST.pool_rates(rec, 'ridge', runs, anys, STATION_MIN_FRAC_STATURE, STATION_MIN_CONTRAST)
    # probe_pools will never run below the shipped constant, so the floor must bind.
    assert mr >= int(RIDGE_NULL_P99['ridge']['min_run'])
    assert mra >= mr
    assert rec['min_run_rates_quoted_at']['min_run'] == mr
    assert rec['min_run_rates_quoted_at']['min_frac_stature'] == float(STATION_MIN_FRAC_STATURE)


def test_the_any_run_rate_is_the_false_positive_rate_of_point_only():
    rec = {}
    runs, anys = [0, 1, 2, 5, 5, 6], [0, 2, 3, 6, 6, 7]
    ST.run_distributions(rec, runs, [0.1] * 6, [0.0] * 6, anys, Q)
    ST.pool_rates(rec, 'ridge', runs, anys, 0.00245, 3.7)
    assert rec['frac_pools_with_any_run'] == 5 / 6.0
    assert rec['frac_pools_point_only_or_better'] == rec['frac_pools_with_any_run']


def test_frac_pools_resolved_is_the_union_and_so_over_counts():
    rec = {}
    # 400 pools: two clear the same-sign threshold, four clear the any-sign one (those two
    # among them). The union is the larger, never less than either part — the only safe
    # direction for a false-positive rate.
    runs = [5, 5] + [0] * 398
    anys = [5, 5, 5, 5] + [0] * 396
    ST.run_distributions(rec, runs, [0.1] * 400, [0.0] * 400, anys, Q)
    ST.pool_rates(rec, 'ridge', runs, anys, 0.00245, 3.7)
    assert rec['frac_pools_at_or_above_min_run'] == 0.005
    assert rec['frac_pools_at_or_above_min_run_any_sign'] == 0.01
    assert rec['frac_pools_resolved'] == 0.01
    assert rec['frac_pools_resolved'] >= rec['frac_pools_at_or_above_min_run']
    assert rec['frac_pools_resolved'] >= rec['frac_pools_at_or_above_min_run_any_sign']


def test_pool_rates_on_no_pools_are_zero_and_not_a_division_by_zero():
    rec = {}
    ST.run_distributions(rec, [], [], [], [], Q)
    ST.pool_rates(rec, 'ridge', [], [], 0.00245, 3.7)
    assert rec['frac_pools_with_any_run'] == 0.0
    assert rec['frac_pools_resolved'] == 0.0


# ── unfloored_rates: additive, and a copy when the unfloored cut IS the cut ───────


def test_the_unfloored_block_copies_the_primary_numbers_when_the_cut_is_the_same():
    rec = {'abs_station_relief_frac': {'p99': 0.01}, 'abs_station_contrast': {'p99': 50.0}}
    runs, anys = [0, 1, 2], [0, 1, 2]
    ST.run_distributions(rec, runs, [0.1] * 3, [0.0] * 3, anys, Q)
    mr, mra = ST.pool_rates(rec, 'ridge', runs, anys, 0.01, 50.0)
    out = ST.unfloored_rates(rec, [], 'ridge', 0.01, 50.0, mr, mra, 'either', 2.0)
    assert out['identical_to_primary'] is True
    assert (out['min_frac_stature'], out['min_contrast']) == (0.01, 50.0)
    assert out['best_longest_run_hist'] == rec['best_longest_run_hist']
    assert out['frac_pools_resolved'] == rec['frac_pools_resolved']
    # a COPY, so a caller mutating the block cannot reach back into the primary record
    out['best_longest_run_hist'][0] = 999
    assert rec['best_longest_run_hist'] != out['best_longest_run_hist']


def test_a_finer_mesh_is_re_scored_at_its_own_lower_p99():
    # On a finer tessellation the mesh's own p99 is BELOW the published cage constant, so
    # the primary rates were measured at a stricter cut than the probes will be.
    rec = {'abs_station_relief_frac': {'p99': 0.001}, 'abs_station_contrast': {'p99': 1.0}}
    runs, anys = [0, 1], [0, 1]
    ST.run_distributions(rec, runs, [0.1] * 2, [0.0] * 2, anys, Q)
    mr, mra = ST.pool_rates(rec, 'ridge', runs, anys, STATION_MIN_FRAC_STATURE, STATION_MIN_CONTRAST)
    per_pool = [[_profile([0.01] * 5, [10.0] * 5)], [_profile([0.0] * 5, [0.0] * 5)]]
    out = ST.unfloored_rates(
        rec, per_pool, 'ridge', STATION_MIN_FRAC_STATURE, STATION_MIN_CONTRAST, mr, mra, 'either', 2.0
    )
    assert out['identical_to_primary'] is False
    assert (out['min_frac_stature'], out['min_contrast']) == (0.001, 1.0)
    # the second pool qualifies at no cut, the first qualifies at this one
    assert out['best_longest_run_hist'] == {0: 1, 5: 1}
    assert out['min_run_used'] >= int(RIDGE_NULL_P99['ridge']['min_run'])


# ── the histogram and threshold helpers the stages call back into ─────────────────


def test_hist_counts_integers_and_is_empty_for_no_values():
    assert NU._hist([0, 1, 1, 3]) == {0: 1, 1: 2, 3: 1}
    assert NU._hist([]) == {}


def test_merge_hists_sums_counts_so_seeds_can_be_pooled():
    # Pooling the COUNTS of k seed draws is the same experiment as one draw with k times
    # the pools; averaging their percentiles is not.
    assert NU.merge_hists([{0: 2, 3: 1}, {3: 4, 5: 1}, None]) == {0: 2, 3: 5, 5: 1}
    assert NU.merge_hists([]) == {}


def test_discrete_min_run_is_the_shortest_run_whose_tail_mass_is_within_alpha():
    # min_run = min{ r : P(best_longest_run >= r) <= alpha }
    hist = {0: 999, 7: 1}
    r = NU._discrete_min_run(hist)
    assert NU.exceedance(hist, r) <= RIDGE_NULL_ALPHA
    assert NU.exceedance(hist, r - 1) > RIDGE_NULL_ALPHA


def test_discrete_min_run_reads_the_same_experiment_run_at_twice_the_pools():
    # Counts are additive: doubling every count is the same distribution and so the same
    # threshold. This is what made pooling seeds possible at all.
    assert NU._discrete_min_run({0: 398, 5: 2}) == NU._discrete_min_run({0: 796, 5: 4})


def test_discrete_min_run_is_an_integer_where_the_interpolated_p99_is_not():
    # The defect it replaced: np.percentile interpolates between order statistics of a
    # discrete variable, so its "p99" lands on values a run length can never take, and
    # ceil() of it flipped on the 1% tail of a single draw.
    runs = [0] * 80 + [1] * 25 + [2] * 14 + [5] * 2
    interpolated = float(np.percentile(runs, 99))
    assert interpolated != int(interpolated)
    discrete = NU._discrete_min_run(NU._hist(runs))
    assert discrete == int(discrete)
    assert NU.exceedance(NU._hist(runs), discrete) <= RIDGE_NULL_ALPHA


def test_discrete_min_run_and_exceedance_are_none_on_an_empty_histogram():
    assert NU._discrete_min_run({}) is None
    assert NU._discrete_min_run(None) is None
    assert NU.exceedance({}, 3) is None


def test_exceedance_is_the_upper_tail_mass():
    hist = {0: 1, 1: 1, 2: 1, 3: 1}
    assert NU.exceedance(hist, 0) == 1.0
    assert NU.exceedance(hist, 2) == 0.5
    assert NU.exceedance(hist, 4) == 0.0


# ── the two readers of a finished null ────────────────────────────────────────────


def test_facet_percentile_places_a_ratio_in_the_skin_null():
    null = {'facet': {'curvedness_ratio': {'p1': 0.1, 'p5': 0.2, 'p10': 0.3, 'p50': 0.5, 'p90': 0.9}}}
    assert NU.facet_percentile(null, 0.05) == 1
    assert NU.facet_percentile(null, 0.25) == 10
    assert NU.facet_percentile(null, 0.6) == 90
    assert NU.facet_percentile(null, 2.0) == 100


def test_facet_percentile_is_none_without_a_measured_null():
    null = {'facet': {'curvedness_ratio': {'p1': 0.1, 'p5': 0.2, 'p10': 0.3, 'p50': 0.5, 'p90': 0.9}}}
    assert NU.facet_percentile(None, 0.5) is None
    assert NU.facet_percentile({}, 0.5) is None
    assert NU.facet_percentile(null, float('nan')) is None


def test_station_cut_without_a_null_returns_the_published_cut():
    cut = NU.station_cut(None, 'point')
    assert cut['min_frac_stature'] == RIDGE_NULL_P99['point']['station_min_frac_stature']
    assert cut['provenance'] == 'MEASURED-NULL'
    assert 'isotropic point probe' in cut['source']


def test_station_cut_is_raised_by_a_measured_null_and_never_lowered():
    high = {'by_mode': {'ridge': {'station_cut_used': {'min_frac_stature': 1.0, 'min_contrast': 999.0}}}}
    raised = NU.station_cut(high, 'ridge')
    assert (raised['min_frac_stature'], raised['min_contrast']) == (1.0, 999.0)
    assert 'ridge_null' in raised['source']

    low = {'by_mode': {'ridge': {'station_cut_used': {'min_frac_stature': 0.0, 'min_contrast': 0.0}}}}
    assert NU.station_cut(low, 'ridge') == NU.station_cut(None, 'ridge')
