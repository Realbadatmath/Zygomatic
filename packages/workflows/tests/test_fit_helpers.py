# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages lifted out of `fit_sex()`.

Everything exercised here used to be a closure inside the 435-line solve, so
this is the first time the lever-box damping, the outer-target table, the
contract assertions and the verbose trace are checked in isolation. No torch, no
MakeHuman model, no reference GLB: these helpers take plain numbers and dicts.
"""

import logging

import numpy as np
import pytest

from zyg_workflows.geom.fit_proportions import fit_sex_stages as ST
from zyg_workflows.geom.fit_proportions.core import HOLD, PRIMARY
from zyg_workflows.geom.fit_proportions.fit import band_regressions


class _FakeRef:
    """A reference pack stand-in: `band()` returns whatever the test declared per ratio."""

    def __init__(self, bands):
        self._bands = bands

    def band(self, name, sex):
        """The declared band for `name`; `sex` is accepted and ignored."""
        return self._bands[name]


def _band(lo, hi, mean=0.5, sd=0.02):
    """One band row shaped like the reference pack's."""
    return {'lo': lo, 'hi': hi, 'mean': mean, 'sd': sd, 'source': 'test'}


# ---------------------------------------------------------------------------
# outer_targets — which ratios the least squares solves, and in which role
# ---------------------------------------------------------------------------


def test_outer_targets_is_empty_when_no_lever_was_released():
    """No released lever means no outer solve at all — not even the HOLD ratios."""
    assert ST.outer_targets('female', ['chest_breadth_over_stature'], []) == []
    assert ST.outer_targets('male', [], []) == []


def test_outer_targets_puts_steered_ratios_first_as_primary_then_this_sex_hold_set():
    """The steered ratios drive (PRIMARY); the sex's own hold set rides along (HOLD)."""
    tgts = ST.outer_targets('female', ['chest_breadth_over_stature'], ['torso-vshape-incr'])
    assert tgts == [
        ('chest_breadth_over_stature', PRIMARY),
        ('chest_circumference_over_stature', HOLD),
        ('chest_depth_over_stature', HOLD),
    ]


def test_outer_targets_for_the_male_has_no_hold_ratios():
    """The male's OUTER table declares an empty hold set, so only the steered ratio appears."""
    tgts = ST.outer_targets('male', ['suprasternale_height_over_stature'], ['head-scale-vert-incr'])
    assert tgts == [('suprasternale_height_over_stature', PRIMARY)]


# ---------------------------------------------------------------------------
# damp_factor — the uniform scaling that keeps every lever inside +/-lb
# ---------------------------------------------------------------------------


def test_damp_factor_is_one_when_every_lever_lands_inside_the_box():
    """A step that needs no damping must not be scaled at all."""
    assert ST.damp_factor(np.array([0.1, -0.2]), [0.0, 0.3], 0.8) == 1.0


def test_damp_factor_scales_the_whole_step_by_the_worst_lever():
    """One lever hitting the cap damps every lever, so the step still solves the system."""
    # lever 0 wants 0.0 -> 1.6 (cap 0.8, so 0.5 of its step); lever 1 wants 0.0 -> 0.2 (fine)
    damp = ST.damp_factor(np.array([1.6, 0.2]), [0.0, 0.0], 0.8)
    assert damp == pytest.approx(0.5)


def test_damp_factor_respects_the_sign_of_the_cap_it_is_heading_for():
    """A negative overshoot is damped against -lb, not +lb."""
    damp = ST.damp_factor(np.array([-1.2]), [0.0], 0.8)
    assert damp == pytest.approx(0.8 / 1.2)


def test_damp_factor_is_zero_for_a_lever_already_pinned_at_the_cap():
    """A lever sitting on the cap and pushing further gets no step rather than a negative one."""
    assert ST.damp_factor(np.array([0.3]), [0.8], 0.8) == 0.0


def test_damp_factor_ignores_a_lever_with_a_zero_step():
    """A zero step can never leave the box and must not divide by zero."""
    assert ST.damp_factor(np.array([0.0]), [0.8], 0.8) == 1.0


# ---------------------------------------------------------------------------
# apply_lever_step — writing the damped step back into local_changes
# ---------------------------------------------------------------------------


def test_apply_lever_step_mutates_local_changes_in_place_and_rounds_to_four_decimals():
    """The live local_changes dict is what the next inner fit reads, so it is updated in place."""
    locs = {'torso-vshape-incr': 0.1}
    out = ST.apply_lever_step(locs, ['torso-vshape-incr'], np.array([0.123456]), 1.0, 0.8)
    assert out is locs
    assert locs['torso-vshape-incr'] == 0.2235


def test_apply_lever_step_treats_an_absent_lever_as_zero():
    """A lever with no issued value starts from 0.0 rather than raising."""
    locs = {}
    ST.apply_lever_step(locs, ['head-scale-vert-incr'], np.array([0.25]), 1.0, 0.8)
    assert locs['head-scale-vert-incr'] == 0.25


def test_apply_lever_step_clamps_to_the_box_even_at_full_damping():
    """The clamp is the belt to damp_factor's braces: nothing may land outside +/-lb."""
    locs = {'a': 0.0, 'b': 0.0}
    ST.apply_lever_step(locs, ['a', 'b'], np.array([5.0, -5.0]), 1.0, 0.8)
    assert locs == {'a': 0.8, 'b': -0.8}


def test_damp_factor_and_apply_lever_step_together_keep_the_step_direction():
    """Damped then applied, the two levers keep their ratio — the point of uniform damping."""
    locs = {'a': 0.0, 'b': 0.0}
    step = np.array([1.6, 0.8])
    damp = ST.damp_factor(step, [0.0, 0.0], 0.8)
    ST.apply_lever_step(locs, ['a', 'b'], step, damp, 0.8)
    assert locs == {'a': 0.8, 'b': 0.4}


# ---------------------------------------------------------------------------
# result_problems — the contract the record is only written under
# ---------------------------------------------------------------------------


def test_result_problems_is_empty_when_primary_reached_the_mean_and_hold_stayed_in_band():
    """The passing case: no message at all, which is what lets the recipe be written."""
    ref = _FakeRef({'p': _band(0.1, 0.9), 'h': _band(0.1, 0.9)})
    after = {'ratios': {'h': {'value': 0.5}}}
    problems = ST.result_problems(
        'female', after, [('p', PRIMARY), ('h', HOLD)], np.array([0.01, 9.0]), np.array([0.05, 0.05]), ref
    )
    assert problems == []


def test_result_problems_reports_a_primary_that_did_not_reach_the_mean():
    """r is TARGET_Z - z, so a residual past the tolerance is a PRIMARY failure."""
    ref = _FakeRef({'p': _band(0.1, 0.9)})
    problems = ST.result_problems('male', {'ratios': {}}, [('p', PRIMARY)], np.array([0.4]), np.array([0.05]), ref)
    assert len(problems) == 1
    assert problems[0] == 'p is PRIMARY and did not reach the mean: z -0.400, tol 0.050'


def test_result_problems_reports_a_hold_that_left_its_band():
    """A HOLD target is judged on its measured value against p5-p95, not on its z."""
    ref = _FakeRef({'h': _band(0.1, 0.2)})
    after = {'ratios': {'h': {'value': 0.2500}}}
    problems = ST.result_problems('female', after, [('h', HOLD)], np.array([0.0]), np.array([0.05]), ref)
    assert problems == ['h is a HOLD target and left the p5-p95 band: 0.2500 not in 0.1000..0.2000']


def test_result_problems_collects_every_failure_rather_than_the_first():
    """The caller joins them into one message, so all of them have to be there."""
    ref = _FakeRef({'p': _band(0.1, 0.9), 'h': _band(0.1, 0.2)})
    after = {'ratios': {'h': {'value': 0.9}}}
    problems = ST.result_problems(
        'female', after, [('p', PRIMARY), ('h', HOLD)], np.array([0.4, 0.0]), np.array([0.05, 0.05]), ref
    )
    assert len(problems) == 2
    assert 'PRIMARY' in problems[0]
    assert 'HOLD' in problems[1]


def test_result_problems_accepts_a_hold_exactly_on_a_band_edge():
    """The band test is inclusive, so a value sitting on p95 is still held."""
    ref = _FakeRef({'h': _band(0.1, 0.2)})
    after = {'ratios': {'h': {'value': 0.2}}}
    assert ST.result_problems('f', after, [('h', HOLD)], np.array([0.0]), np.array([0.05]), ref) == []


# ---------------------------------------------------------------------------
# the verbose trace
# ---------------------------------------------------------------------------


def test_print_round_names_each_target_by_its_numerator_and_shows_its_tolerance(caplog):
    """The round line shortens `x_over_stature` to `x` and prints the signed z, not the residual."""
    mid = {
        'crotch_z': -0.004,
        'chamfer_upper_fwd_mm': 9.1,
        'chamfer_upper_rev_mm': 8.2,
        'chamfer_full_fwd_mm': 11.3,
        'chamfer_full_rev_mm': 10.4,
    }
    with caplog.at_level(logging.INFO, logger=ST.__name__):
        ST.print_round(2, mid, [('chest_breadth_over_stature', PRIMARY)], np.array([0.25]), np.array([0.05]))
    assert caplog.messages == [
        '    round 2: crotch z -0.004 | chest_breadth z -0.250 (tol 0.050) | chamfer upper 9.10/8.20 full 11.30/10.40 mm'
    ]


def test_print_round_says_no_outer_target_when_the_target_list_is_empty(caplog):
    """A body with no released lever still gets a round line, with a placeholder."""
    mid = dict.fromkeys(
        ('chamfer_upper_fwd_mm', 'chamfer_upper_rev_mm', 'chamfer_full_fwd_mm', 'chamfer_full_rev_mm'), 0.0
    )
    mid['crotch_z'] = 0.0
    with caplog.at_level(logging.INFO, logger=ST.__name__):
        ST.print_round(0, mid, [], np.array([]), np.array([]))
    assert 'no outer target' in '\n'.join(caplog.messages)


def test_print_levers_only_mentions_the_cap_when_the_step_was_damped(caplog):
    """An undamped step logs the landed values and nothing else."""
    with caplog.at_level(logging.INFO, logger=ST.__name__):
        ST.print_levers({'torso-vshape-incr': 0.4321}, ['torso-vshape-incr'], 1.0, 0.8)
        assert caplog.messages == ['      levers -> torso-vshape-incr 0.4321']

        caplog.clear()
        ST.print_levers({'torso-vshape-incr': 0.8}, ['torso-vshape-incr'], 0.5, 0.8)
        assert '(step damped x0.500 by the +/-0.8 cap)' in '\n'.join(caplog.messages)


def test_print_regressions_prints_one_guard_line_per_ratio_that_left_its_band(caplog):
    """The GUARD lines are the operator's record of a declined improvement."""
    with caplog.at_level(logging.INFO, logger=ST.__name__):
        ST.print_regressions(
            [
                {
                    'ratio': 'foot_length_over_stature',
                    'before': 0.1463,
                    'after': 0.1489,
                    'percentile_before': 9.1,
                    'percentile_after': 96.4,
                    'band': [0.1400, 0.1480],
                }
            ]
        )
    assert caplog.messages == [
        '    GUARD: foot_length_over_stature left its band, 0.1463 (p9.1) -> 0.1489 (p96.4), band 0.1400..0.1480'
    ]


def test_print_regressions_on_a_clean_fit_prints_nothing(caplog):
    """No regression, no line — the orchestrator guards on `verbose and regressions` too."""
    with caplog.at_level(logging.INFO, logger=ST.__name__):
        ST.print_regressions([])
    assert caplog.messages == []


# ---------------------------------------------------------------------------
# band_regressions — the do-no-harm guard the orchestrator still calls
# ---------------------------------------------------------------------------


def _row(value, outside, z=0.0, percentile=50.0, survey=True):
    """One report_ratios row, as band_regressions reads it."""
    return {
        'value': value,
        'outside_band': outside,
        'z': z,
        'percentile': percentile,
        'p5': 0.14,
        'p95': 0.148,
        'survey_comparable': survey,
    }


def test_band_regressions_flags_only_a_ratio_that_crossed_out_of_its_band():
    """In-band before and out-of-band after is the one thing a repair pass may not do."""
    before = {'a': _row(0.146, False), 'b': _row(0.200, True)}
    after = {'a': _row(0.149, True), 'b': _row(0.210, True)}
    out = band_regressions(before, after)
    assert [g['ratio'] for g in out] == ['a']
    assert out[0]['band'] == [0.14, 0.148]


def test_band_regressions_ignores_ratios_that_are_not_survey_comparable():
    """A ratio the measurement layer refuses to compare cannot carry the guard."""
    before = {'a': _row(0.146, False, survey=False)}
    after = {'a': _row(0.149, True, survey=False)}
    assert band_regressions(before, after) == []


def test_band_regressions_ignores_a_ratio_with_no_before_row():
    """A ratio that only resolved after the fit has no baseline to have crossed."""
    assert band_regressions({}, {'a': _row(0.149, True)}) == []
