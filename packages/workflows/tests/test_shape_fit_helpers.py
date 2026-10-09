# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The pure stages `shape_fit.run` is now an orchestrator over.

The judgement in a shape solve is in four functions that touch no body model, no
torch and no GPU — `beats`, `build_gate`, `gate_verdict`, `saturated_axes` — plus
`cell_refusal`, which decides whether a cell's fit report may be used at all, and
`split_pool`, which holds a reproducible third of the pool out. Those are exactly
the places a mistake would silently change a verdict, so they are tested on plain
dictionaries here.
"""

import numpy as np

from zyg_workflows.geom import shape_fit_stages as ST


def _scores(fit_px, fit_iou, a_px=10.0, a_iou=0.50, b_px=10.0, b_iou=0.50):
    """Three arms' held-out scores, as `build_gate` reads them."""
    return {
        'fit': {'median_err_px': fit_px, 'median_iou': fit_iou},
        'null_declared': {'median_err_px': a_px, 'median_iou': a_iou},
        'null_mean_anny': {'median_err_px': b_px, 'median_iou': b_iou},
    }


# ── beats ────────────────────────────────────────────────────────────────────
def test_beats_reads_the_direction_it_is_given():
    assert ST.beats(3.0, 9.0, True) is True
    assert ST.beats(9.0, 3.0, True) is False
    assert ST.beats(0.9, 0.5, False) is True
    assert ST.beats(0.5, 0.9, False) is False


def test_a_missing_number_is_not_a_won_comparison():
    assert ST.beats(None, 0.5, False) is None
    assert ST.beats(0.5, None, False) is None


# ── build_gate ───────────────────────────────────────────────────────────────
def test_the_gate_is_found_only_when_both_nulls_lose_on_both_measures():
    gate = ST.build_gate(_scores(4.0, 0.80))
    assert gate['beats_both_on_reprojection'] is True
    assert gate['beats_both_on_iou'] is True
    assert gate['state'] == 'found'


def test_winning_on_px_alone_is_not_detectable_not_found():
    gate = ST.build_gate(_scores(4.0, 0.40))
    assert gate['beats_both_on_reprojection'] is True
    assert gate['beats_both_on_iou'] is False
    assert gate['state'] == 'not_detectable'


def test_losing_to_one_null_is_enough_to_fail_the_gate():
    gate = ST.build_gate(_scores(4.0, 0.80, b_px=2.0))
    assert gate['beats_both_on_reprojection'] is False
    assert gate['state'] == 'not_detectable'


def test_an_absent_iou_is_unmeasurable_never_found():
    gate = ST.build_gate(_scores(4.0, None))
    assert gate['beats_both_on_iou'] is None
    assert gate['state'] == 'unmeasurable'
    assert 'silhouette IoU was unavailable' in ST.gate_verdict(gate['state'])


def test_the_gate_states_each_have_their_own_verdict():
    said = {ST.gate_verdict(s) for s in ('found', 'not_detectable', 'unmeasurable')}
    assert len(said) == 3
    assert ST.gate_verdict('found').startswith('the sheet carries shape information')
    assert 'should be baked' in ST.gate_verdict('not_detectable')


# ── saturated_axes ───────────────────────────────────────────────────────────
def test_only_the_axes_on_their_own_cap_are_reported_saturated():
    mb, lb = ST.SF.MACRO_BOUND, ST.SF.LOCAL_BOUND
    sat = ST.saturated_axes(
        {
            'delta_macro': {'muscle': mb, 'weight': -mb, 'proportions': 0.1 * mb},
            'delta_local': {'nose': 0.5 * lb, 'chin': -lb},
        }
    )
    assert set(sat) == {'muscle', 'weight', 'chin'}
    assert sat['weight'] == -mb


def test_a_solve_that_moved_nothing_saturates_nothing():
    assert ST.saturated_axes({'delta_macro': {'muscle': 0.0}, 'delta_local': {}}) == {}


# ── cell_refusal ─────────────────────────────────────────────────────────────
def _fit(**kw):
    """A usable pinhole fit of the body `abel`, overridable key by key."""
    base = {
        'fit_ok': True,
        'pose_aa': [[0.0, 0.0, 0.0]],
        'body': {'source': 'registry', 'name': 'abel'},
        'camera_model': 'pinhole',
        'camera': [1.0, 2.0, 3.0, 4.0],
    }
    base.update(kw)
    return base


def test_a_pinhole_fit_of_this_body_is_not_refused():
    assert ST.cell_refusal(_fit(), 'abel') == ''


def test_a_gated_or_poseless_fit_is_refused():
    assert ST.cell_refusal(_fit(fit_ok=False), 'abel') == 'fit gated or poseless'
    poseless = _fit()
    del poseless['pose_aa']
    assert ST.cell_refusal(poseless, 'abel') == 'fit gated or poseless'


def test_a_pose_solved_against_another_body_is_refused_by_name():
    why = ST.cell_refusal(_fit(body={'source': 'registry', 'name': 'someone_else'}), 'abel')
    assert "'someone_else'" in why and "'abel'" in why
    assert ST.cell_refusal(_fit(body={}), 'abel').startswith("fit carries body 'none'")


def test_a_pre_pinhole_orthographic_fit_is_refused():
    assert ST.cell_refusal(_fit(camera_model='ortho'), 'abel') == 'not a pinhole fit'
    assert ST.cell_refusal(_fit(camera=[1.0, 2.0, 3.0]), 'abel') == 'not a pinhole fit'


# ── split_pool ───────────────────────────────────────────────────────────────
def test_the_split_is_a_partition_of_the_pool():
    pool = [{'cell': 'cell_%02d' % i} for i in range(12)]
    train, hold = ST.split_pool(pool, np.random.RandomState(0), 3)
    assert len(hold) == 4 and len(train) == 8
    assert sorted(c['cell'] for c in train + hold) == sorted(c['cell'] for c in pool)


def test_at_least_two_cells_are_always_held_out():
    pool = [{'cell': 'cell_%02d' % i} for i in range(6)]
    _train, hold = ST.split_pool(pool, np.random.RandomState(0), 9)
    assert len(hold) == 2


def test_the_same_seed_gives_the_same_split_and_another_seed_does_not():
    pool = [{'cell': 'cell_%02d' % i} for i in range(20)]
    a = ST.split_pool(pool, np.random.RandomState(7), 3)[1]
    b = ST.split_pool(pool, np.random.RandomState(7), 3)[1]
    c = ST.split_pool(pool, np.random.RandomState(8), 3)[1]
    assert [x['cell'] for x in a] == [x['cell'] for x in b]
    assert [x['cell'] for x in a] != [x['cell'] for x in c]
