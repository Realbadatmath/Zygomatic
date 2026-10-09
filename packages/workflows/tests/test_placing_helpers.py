# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages `floor_plans.placing._place` is now an orchestrator over.

Six of them decide things on numbers alone — which edge a point is nearest, what
rotation an align="entrance" request works out to, whether a plan would push the
drawing past the object ceiling, which wall an opening lands on, what glass a
window can actually have on the wall it landed on, and whether a fixture's
rotated footprint reaches into the core. Those are the places a mistake would put
a partition inside a lift shaft or a window head through a roof, so they are
tested here on plain dictionaries.

IMPORTING placing_steps NEEDS A STUB, and the fault is not this module's.
`zyg_workflows.arch_assistant.prompts` has raised NameError: MATERIALS at import
since 2026-10-06 (`_relax_material_enums()` runs at line 278, `MATERIALS` is
imported at line 352), so `import zyg_workflows.arch_assistant` fails for every
caller. The fixture below stands that ONE submodule in, exercises the real
arch_assistant for everything else, and puts sys.modules back as it found it.
"""

import math
import sys
import types

import pytest


@pytest.fixture(scope='module')
def steps():
    """placing_steps, imported past the pre-existing arch_assistant.prompts fault.

    Only `prompts` is stubbed: `_num`, `MATERIALS`, `KINDS`, `Drawing` and the
    plan_packs primitives the stages use are all the real ones.
    """
    key = 'zyg_workflows.arch_assistant.prompts'
    saved = {k: v for k, v in sys.modules.items() if k.startswith('zyg_workflows.arch_assistant')}
    stub = types.ModuleType(key)
    stub.__getattr__ = lambda n: object()
    sys.modules[key] = stub
    try:
        from zyg_workflows.arch_assistant_ext.floor_plans import placing_steps

        yield placing_steps
    finally:
        for k in [k for k in sys.modules if k.startswith('zyg_workflows.arch_assistant')]:
            del sys.modules[k]
        sys.modules.update(saved)


# ── side_of ──────────────────────────────────────────────────────────────────
def test_each_edge_of_the_bbox_is_named_from_a_point_against_it(steps):
    # a 10 x 6 m plan, west/east on x and north/south on z
    assert steps.side_of(0.1, 3.0, 10.0, 6.0) == 'west'
    assert steps.side_of(9.9, 3.0, 10.0, 6.0) == 'east'
    assert steps.side_of(5.0, 0.1, 10.0, 6.0) == 'north'
    assert steps.side_of(5.0, 5.9, 10.0, 6.0) == 'south'


def test_a_tie_resolves_to_the_first_edge_in_the_clockwise_order(steps):
    """The order the candidates are built in IS the tiebreak, and it must not
    drift: an entrance exactly on a corner has to resolve the same way twice."""
    assert steps.side_of(0.0, 0.0, 10.0, 6.0) == 'west'
    assert steps.side_of(3.0, 3.0, 6.0, 6.0) == 'west'


# ── resolve_rotation ─────────────────────────────────────────────────────────
def test_an_off_grid_rotation_is_refused_with_the_number_it_was_given(steps):
    rot, err = steps.resolve_rotation({'id': 'p1'}, {'rotate_deg': 45}, False)
    assert rot == 45
    assert err == 'refused: rotate_deg must be 0, 90, 180 or 270 (got 45)'


def test_a_plain_request_passes_its_rotation_through_modulo_a_turn(steps):
    assert steps.resolve_rotation({'id': 'p1'}, {}, False) == (0, '')
    assert steps.resolve_rotation({'id': 'p1'}, {'rotate_deg': 270}, False) == (270, '')
    assert steps.resolve_rotation({'id': 'p1'}, {'rotate_deg': 450}, False) == (90, '')


@pytest.mark.parametrize(
    ('want', 'expect'),
    [('north', 0), ('east', 90), ('south', 180), ('west', 270)],
)
def test_align_entrance_derives_the_rotation_from_the_two_sides(steps, want, expect):
    """With align="entrance" the rotation is NOT a free choice: it is the quarter
    turns from the side the plan's entrance is on to the side the caller wants."""
    plan = {'id': 'p1', 'entrance': {'side': 'north'}}
    assert steps.resolve_rotation(plan, {'align': 'entrance', 'entrance_side': want}, False) == (expect, '')


def test_mirroring_flips_the_entrance_side_before_the_turn_is_counted(steps):
    plan = {'id': 'p1', 'entrance': {'side': 'east'}}
    opts = {'align': 'entrance', 'entrance_side': 'east'}
    assert steps.resolve_rotation(plan, opts, False) == (0, '')
    # mirrored, the plan's own east door comes out on the west, so it needs a half turn
    assert steps.resolve_rotation(plan, opts, True) == (180, '')


def test_align_entrance_refuses_without_a_side_to_align_to(steps):
    _rot, err = steps.resolve_rotation({'id': 'p1', 'entrance': {'side': 'north'}}, {'align': 'entrance'}, False)
    assert err.startswith('refused: align="entrance" needs entrance_side=')


def test_align_entrance_refuses_a_plan_with_no_entrance_on_record(steps):
    opts = {'align': 'entrance', 'entrance_side': 'north'}
    _rot, err = steps.resolve_rotation({'id': 'hall_02'}, opts, False)
    assert 'hall_02 has no entrance side on record' in err
    assert 'use align="centre"' in err


# ── capacity_error ───────────────────────────────────────────────────────────
class _Objs:
    """A drawing that is only its object count, which is all capacity_error reads."""

    def __init__(self, n):
        self.objs = [None] * n


def test_a_plan_that_fits_under_the_ceiling_is_not_refused(steps):
    plan = {'id': 'p1', 'walls': [1, 2, 3], 'rooms': [1], 'doors': [1], 'windows': [], 'fixtures': []}
    assert steps.capacity_error(_Objs(10), plan) == ''


def test_a_plan_that_would_breach_the_ceiling_is_refused_before_anything_is_drawn(steps):
    d = _Objs(steps.MAX_OBJECTS - 3)
    plan = {'id': 'tower_floor', 'walls': [1, 2, 3, 4], 'rooms': [1, 2]}
    err = steps.capacity_error(d, plan)
    assert err.startswith('refused: tower_floor is about 8 records')
    assert str(steps.MAX_OBJECTS) in err
    assert len(d.objs) == steps.MAX_OBJECTS - 3  # counted, not drawn


def test_the_count_allows_two_records_the_plan_does_not_list(steps):
    """The shell and the plate: `_place` draws two records of its own, so the
    capacity test has to reserve them or a plan lands one short of the ceiling."""
    d = _Objs(steps.MAX_OBJECTS - 2)
    assert steps.capacity_error(d, {'id': 'p1'}) == ''
    assert steps.capacity_error(_Objs(steps.MAX_OBJECTS - 1), {'id': 'p1'}) != ''


# ── nearest_seg ──────────────────────────────────────────────────────────────
def test_the_host_wall_is_the_segment_the_opening_is_closest_to(steps):
    north = ({'id': 'n'}, 0.0, 0.0, 6.0, 0.0)
    south = ({'id': 's'}, 0.0, 4.0, 6.0, 4.0)
    pool = [north, south]
    assert steps.nearest_seg(3.0, 0.2, pool)['id'] == 'n'
    assert steps.nearest_seg(3.0, 3.8, pool)['id'] == 's'


def test_distance_is_to_the_segment_not_to_its_centre(steps):
    """A door at the far end of a long wall belongs to that wall, even when a
    short wall's midpoint is nearer the door than the long wall's midpoint is."""
    long_wall = ({'id': 'long'}, 0.0, 0.0, 20.0, 0.0)
    stub = ({'id': 'stub'}, 19.0, 3.0, 20.0, 3.0)
    assert steps.nearest_seg(19.5, 0.1, [long_wall, stub])['id'] == 'long'


def test_an_empty_pool_hosts_nothing(steps):
    assert steps.nearest_seg(1.0, 1.0, []) is None


# ── window_opening ───────────────────────────────────────────────────────────
def test_a_window_that_fits_its_wall_keeps_its_surveyed_sill_and_height(steps):
    w_h, sill, ok = steps.window_opening({'h': 1.4, 'sill': 0.9}, {'p': {'h': 2.7}})
    assert (w_h, sill, ok) == (1.4, 0.9, True)


def test_a_sash_that_would_stand_through_the_wall_top_drops_its_sill(steps):
    """0.9 m sill + 1.9 m sash wants 2.80 m of wall and a storey wall is 2.70 m.
    Keep HEAD_LINTEL of wall over the head and lower the sill to keep the glass."""
    w_h, sill, ok = steps.window_opening({'h': 1.9, 'sill': 0.9}, {'p': {'h': 2.7}})
    assert ok is True
    assert w_h == pytest.approx(1.9)
    assert sill == pytest.approx(2.7 - steps.HEAD_LINTEL - 1.9)
    assert sill + w_h == pytest.approx(2.7 - steps.HEAD_LINTEL)


def test_a_wall_too_low_to_be_a_window_wall_refuses_the_opening(steps):
    w_h, _sill, ok = steps.window_opening({'h': 1.4, 'sill': 0.9}, {'p': {'h': 0.35}})
    assert ok is False
    assert w_h < steps.MIN_GLASS


def test_a_wall_of_unknown_height_is_not_second_guessed(steps):
    assert steps.window_opening({'h': 1.4, 'sill': 0.9}, {}) == (1.4, 0.9, True)
    assert steps.window_opening({'h': 1.4, 'sill': 0.9}, {'p': {'h': 0.0}}) == (1.4, 0.9, True)


def test_a_window_with_nothing_on_record_gets_the_house_defaults(steps):
    assert steps.window_opening({}, {'p': {'h': 2.7}}) == (1.4, 0.9, True)
    # and a negative sill is floored, never trusted
    assert steps.window_opening({'sill': -3.0}, {'p': {'h': 2.7}})[1] == 0.0


# ── fixture_hits_core ────────────────────────────────────────────────────────
def test_a_fixture_clear_of_every_keep_out_rectangle_does_not_hit(steps):
    assert steps.fixture_hits_core('unknown_kind', 0.0, 0.0, 0.0, [(5.0, 5.0, 7.0, 7.0)]) is False


def test_a_fixture_standing_in_the_stair_well_hits_it(steps):
    assert steps.fixture_hits_core('unknown_kind', 6.0, 6.0, 0.0, [(5.0, 5.0, 7.0, 7.0)]) is True


def test_a_fixture_is_tested_by_its_footprint_not_by_its_centre(steps):
    """2026-09-11: a 2 m kitchen counter whose centre stood 0.45 m outside the
    stair well reached 0.6 m into it. An unknown kind falls back to 0.6 m square,
    so a centre 0.2 m clear of the edge still overlaps."""
    well = [(0.0, 0.0, 2.0, 2.0)]
    assert steps.fixture_hits_core('unknown_kind', 2.2, 1.0, 0.0, well) is True
    assert steps.fixture_hits_core('unknown_kind', 3.0, 1.0, 0.0, well) is False


def test_rotation_turns_the_footprint_the_tested_rectangle_follows(steps):
    """A quarter turn swaps the half-extents, so a footprint's reach changes with
    its rotation and the overlap test has to see the turned box."""
    half = steps.fixture_hits_core('unknown_kind', 2.2, 1.0, 0.0, [(0.0, 0.0, 2.0, 2.0)])
    turned = steps.fixture_hits_core('unknown_kind', 2.2, 1.0, math.pi / 2, [(0.0, 0.0, 2.0, 2.0)])
    assert half == turned  # a square kind is symmetric under a quarter turn
    assert steps.fixture_hits_core('unknown_kind', 2.2, 1.0, math.pi / 4, [(0.0, 0.0, 2.0, 2.0)]) is True


def test_nothing_to_keep_clear_means_nothing_to_hit(steps):
    assert steps.fixture_hits_core('unknown_kind', 1.0, 1.0, 0.0, []) is False
