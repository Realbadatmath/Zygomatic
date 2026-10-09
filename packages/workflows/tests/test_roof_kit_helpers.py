# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the five stages `t_build_roof_deck` was split into.

`t_build_roof_deck` was 321 lines — argument resolution, the guard, the pool,
the plant with its two placements, the head-house door and the receipt in one
body — so none of the arithmetic the refusals quote had ever been reachable on
its own: the strip depth, the even spread of plant units along the deck, the
head-house row with its edge and core clearances, and the two refusal sentences
that name the numbers.

They are `roof_kit_deck` functions now. `deck_plant_spots`,
`head_house_plant_spots`, `plant_line` and `_plant_short` are pure;
`deck_plan` and `move_plant` are driven with a stand-in Drawing and a stubbed
`roof_kit.A`, so nothing here needs Blender, a renderer or a service.

`zyg_workflows.arch_assistant` does not import at this commit: its prompts.py
calls `_relax_material_enums()` at line 278, which reads `MATERIALS`, which the
module imports at line 352 — a module-scope use-before-bind that raises
NameError as soon as any extension registers a tool with an enum. It is a
pre-existing break, reported as such; until it is fixed the two names roof_kit
is actually built from are taken from the real submodules behind a stub parent
package, exactly as `test_infinity_helpers.py` already does.
"""

import os
import sys
from types import ModuleType

import pytest

try:
    import zyg_workflows.arch_assistant  # noqa: F401
except NameError:
    import zyg_workflows

    _stub = ModuleType('zyg_workflows.arch_assistant')
    _stub.__path__ = [os.path.join(zyg_workflows.__path__[0], 'arch_assistant')]
    sys.modules['zyg_workflows.arch_assistant'] = _stub
    from zyg_workflows.arch_assistant import config as _config
    from zyg_workflows.arch_assistant import walls as _walls

    for _name in ('MATERIALS', 'MAX_OBJECTS', '_num'):
        setattr(_stub, _name, getattr(_config, _name))
    _stub.SIDE_WORDS = _walls.SIDE_WORDS
    # the rest of roof_kit's import block is not reached by anything tested
    # here; a name is enough for `from zyg_workflows.arch_assistant import ...`
    _stub.__getattr__ = lambda name: name

from zyg_workflows.arch_assistant_ext import roof_kit as RK
from zyg_workflows.arch_assistant_ext import roof_kit_deck as RD


class FakeDrawing:
    """Just enough Drawing for the stages tested here: `objs`, `find`, `ext`."""

    def __init__(self, objs=(), ext=None):
        self.objs = [dict(o) for o in objs]
        self.ext = dict(ext or {})
        self.selected: list = []

    def find(self, oid):
        for o in self.objs:
            if o['id'] == oid:
                return o
        return None


def _env(**over):
    """A 40 x 40 m plate, 20 storeys, deck 54.3 m up."""
    env = {'xmin': 0.0, 'xmax': 40.0, 'zmin': 0.0, 'zmax': 40.0, 'top_deck': 54.3, 'storeys': 20}
    env.update(over)
    return env


def _fit(**over):
    """A 6 m deep away-strip (30.0 .. 36.0) with a deep tank and a shallow AHU."""
    kw = dict(
        lo=30.0,
        hi=36.0,
        deep={'a': 1.0, 'b': 0.4},
        wide={'a': 1.5, 'b': 0.8},
        on_deck=['a', 'b'],
        off_deck=[],
    )
    kw.update(over)
    return RD.PlantFit(**kw)


# ── deck_plant_spots: the even spread along the strip ────────────────────────


def test_the_on_deck_units_are_spread_evenly_inboard_of_a_one_metre_margin():
    placed = RD.deck_plant_spots(_env(), 'n', _fit())
    assert [oid for oid, _xz in placed] == ['a', 'b']
    # the plate runs 1.0 .. 39.0 after the margin; two units sit at 1/3 and 2/3
    assert placed[0][1][0] == pytest.approx(1.0 + 38.0 / 3)
    assert placed[1][1][0] == pytest.approx(1.0 + 2 * 38.0 / 3)


def test_a_north_strip_pushes_each_unit_hard_against_its_near_edge():
    placed = RD.deck_plant_spots(_env(), 'n', _fit())
    # away='n' measures from `lo`: the half-depth is the whole offset
    assert placed[0][1][1] == pytest.approx(31.0)
    assert placed[1][1][1] == pytest.approx(30.4)


def test_a_south_strip_measures_the_same_offsets_from_the_far_edge_instead():
    placed = RD.deck_plant_spots(_env(), 's', _fit())
    assert placed[0][1][1] == pytest.approx(35.0)
    assert placed[1][1][1] == pytest.approx(35.6)


def test_an_east_or_west_strip_swaps_which_axis_runs_along_the_strip():
    placed = RD.deck_plant_spots(_env(), 'w', _fit())
    # along z now, fixed in x — the spot tuple is still (x, z)
    assert placed[0][1][0] == pytest.approx(31.0)
    assert placed[0][1][1] == pytest.approx(1.0 + 38.0 / 3)


def test_a_strip_that_holds_nothing_places_nothing():
    assert RD.deck_plant_spots(_env(), 'n', _fit(on_deck=[], off_deck=['a', 'b'])) == []


# ── head_house_plant_spots: the row on the head-house roof ───────────────────


def _hh(x0=0.0, x1=10.0, z0=10.0, z1=16.0, y=57.3):
    return ((x0, z0, x1, z1), y)


def test_the_head_house_row_keeps_the_edge_and_core_clearances():
    fit = _fit(on_deck=[], off_deck=['a', 'b'])
    ok, placed, need, span = RD.head_house_plant_spots(_hh(), 'n', fit)
    assert ok is True
    # 2*(1.5 + 0.8) widths + 1.0 between the two + 2*0.6 at the ends
    assert need == pytest.approx(6.8)
    assert span == pytest.approx(10.0)
    slack = (10.0 - 6.8) / 3
    assert placed[0][0] == 'a' and placed[0][1][0] == pytest.approx(0.6 + slack + 1.5)
    assert placed[1][0] == 'b' and placed[1][1][0] == pytest.approx(0.6 + slack + 1.5 + 1.5 + 1.0 + slack + 0.8)
    # both sit on the head house's own centre line across the row
    assert placed[0][1][1] == placed[1][1][1] == pytest.approx(13.0)


def test_a_head_house_roof_too_short_for_the_row_refuses_with_both_numbers():
    fit = _fit(on_deck=[], off_deck=['a', 'b'])
    ok, placed, need, span = RD.head_house_plant_spots(_hh(x1=5.0), 'n', fit)
    assert ok is False
    assert placed == []
    assert (round(need, 2), span) == (6.8, pytest.approx(5.0))


def test_a_single_unit_needs_only_the_two_edge_clearances():
    fit = _fit(on_deck=[], off_deck=['a'])
    ok, placed, need, _span = RD.head_house_plant_spots(_hh(), 'n', fit)
    # no PLANT_CORE gap with nothing to keep clear of
    assert ok is True
    assert need == pytest.approx(2 * 1.5 + 2 * 0.6)
    assert len(placed) == 1


def test_an_east_facing_row_runs_along_z_and_fixes_x():
    fit = _fit(on_deck=[], off_deck=['a'])
    ok, placed, _need, span = RD.head_house_plant_spots(_hh(z0=0.0, z1=20.0), 'e', fit)
    assert ok is True
    assert span == pytest.approx(20.0)
    assert placed[0][1][0] == pytest.approx(5.0)  # (hx0 + hx1) / 2
    assert placed[0][1][1] == pytest.approx(0.6 + (20.0 - 4.2) / 2 + 1.5)


# ── the two sentences the refusals and the receipt are built from ────────────


def test_the_refusal_clause_quotes_the_real_depth_of_the_strip():
    assert RD._plant_short('Tower', 'n', _fit()) == (
        'the north strip of "Tower" is 6.0 m deep once 1.5 m is kept clear of the pool and its '
        'loungers, parasols, palms and lights and 1 m clear of the core'
    )


def test_a_strip_measured_inside_out_is_reported_as_zero_deep_not_negative():
    assert '0.0 m deep' in RD._plant_short('Tower', 's', _fit(lo=36.0, hi=30.0))


def test_the_plant_line_names_every_unit_and_where_each_one_went():
    line = RD.plant_line('Tower', 'n', _fit(), ['a', 'b'], 0)
    assert line == (
        'plant: 2 unit(s) a, b — 2 on the north strip, 1.5 m clear of the pool group and 1 m clear of the core'
    )


def test_the_plant_line_says_how_many_records_had_to_be_moved_off_the_centre_line():
    line = RD.plant_line('Tower', 'n', _fit(), ['a', 'b'], 2)
    assert line.endswith(
        ' — add_rooftop_plant takes no side argument (mep_services.py:329), so 2 record(s) '
        'were moved there off the centre line'
    )


def test_the_plant_line_reports_the_units_banished_to_the_head_house():
    fit = _fit(on_deck=['b'], off_deck=['a'])
    line = RD.plant_line('Tower', 'n', fit, ['a', 'b'], 0)
    assert '1 on the north strip' in line
    assert '; a on the head-house roof instead, the north strip being only 6.0 m deep' in line


def test_a_plant_line_with_an_empty_deck_says_so_in_words():
    fit = _fit(on_deck=[], off_deck=['a', 'b'])
    line = RD.plant_line('Tower', 'n', fit, ['a', 'b'], 0)
    assert 'none left on the deck' in line
    assert '; a, b on the head-house roof instead' in line


# ── move_plant ───────────────────────────────────────────────────────────────


def test_moving_the_plant_rounds_each_spot_and_drops_it_on_the_surface(monkeypatch):
    monkeypatch.setattr(RK.A, 'surface_top', lambda d, x, z: 54.3, raising=False)
    d = FakeDrawing([{'id': 'a', 'x': 20.0, 'z': 20.0, 'y': 0.0}, {'id': 'b', 'x': 5.0, 'z': 31.0, 'y': 0.0}])
    moved = RD.move_plant(d, [('a', (13.666666, 31.0)), ('b', (5.0, 31.0))])
    # only 'a' actually changed position; 'b' was already on its spot
    assert moved == 1
    assert (d.find('a')['x'], d.find('a')['z'], d.find('a')['y']) == (13.6667, 31.0, 54.3)
    assert (d.find('b')['x'], d.find('b')['z'], d.find('b')['y']) == (5.0, 31.0, 54.3)


# ── deck_plan: the refusals, by name, with the fix ───────────────────────────


class FakeEnvelopeRules:
    """The two `envelope_rules` entry points `deck_plan` calls."""

    def __init__(self, envs):
        self._envs = envs

    def envelopes(self, d):
        return dict(self._envs)

    def group_envelope(self, d, g):
        return self._envs.get(g)


def _with_envelopes(monkeypatch, envs):
    monkeypatch.setattr(RK, '_m', lambda name: FakeEnvelopeRules(envs) if name == 'envelope_rules' else None)


def test_a_deck_refuses_outright_without_the_envelope_rules_family(monkeypatch):
    monkeypatch.setattr(RK, '_m', lambda name: None)
    plan, why = RD.deck_plan(FakeDrawing(), '', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert why == 'refused: build_roof_deck needs the envelope_rules family'


def test_two_buildings_and_no_group_refuses_and_names_both(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env(), 'Annex': _env()})
    plan, why = RD.deck_plan(FakeDrawing(), '', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert 'name the building the roof belongs to (group=...)' in why
    assert '"Tower"' in why and '"Annex"' in why


def test_the_only_building_is_taken_when_no_group_is_named(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env(), 'Tower head house': _env()})
    plan, why = RD.deck_plan(FakeDrawing(), '', 'infinity', 'south', 'glass', 'penthouse pool')
    assert why == ''
    # the head house is not a candidate building, so 'Tower' is unambiguous
    assert (plan.g, plan.v, plan.pk, plan.gk) == ('Tower', 's', 'infinity', 'glass')
    assert (plan.N, plan.top, plan.nm) == (20, 54.3, 'penthouse pool')


def test_an_unknown_group_refuses_with_the_draw_box_call_that_makes_one(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    plan, why = RD.deck_plan(FakeDrawing(), 'Villa', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert why.startswith('refused: no building called "Villa"')
    assert 'draw_box(centre=..., width=..., depth=..., storeys=...)' in why


def test_a_building_with_no_roof_deck_refuses_before_anything_is_drawn(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env(top_deck=None)})
    plan, why = RD.deck_plan(FakeDrawing(), 'Tower', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert 'refused: "Tower" has no roof deck' in why


def test_no_and_false_read_as_none_for_both_the_pool_and_the_guard(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    # '' itself never gets here — it falls back to the 'infinity'/'glass'
    # defaults before the test — but whitespace survives the `or` and does
    plan, why = RD.deck_plan(FakeDrawing(), 'Tower', '', 'south', '', '')
    assert (why, plan.pk, plan.gk) == ('', 'infinity', 'glass')
    for word in ('no', 'false', 'NO', '  '):
        plan, why = RD.deck_plan(FakeDrawing(), 'Tower', word, 'south', word, '')
        assert why == ''
        assert (plan.pk, plan.gk) == ('none', 'none')


def test_a_kind_that_is_not_ours_refuses_and_lists_the_ones_that_are(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    plan, why = RD.deck_plan(FakeDrawing(), 'Tower', 'lagoon', 'south', 'glass', '')
    assert plan is None
    assert why == 'refused: pool="lagoon" is not a kind of water here — pool must be infinity, plain, none'
    plan, why = RD.deck_plan(FakeDrawing(), 'Tower', 'infinity', 'south', 'hedge', '')
    assert plan is None
    assert why == 'refused: guard="hedge" is not a kind of guard here — guard must be glass, solid, none'


def test_a_view_that_is_not_a_compass_side_refuses(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    plan, why = RD.deck_plan(FakeDrawing(), 'Tower', 'infinity', 'up', 'glass', '')
    assert plan is None
    assert why == 'refused: view must be north, south, east or west — the side the water falls away towards'


def test_the_view_is_resolved_through_the_assistant_side_words(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    for word, letter in (('front', 's'), ('rear', 'n'), ('EAST', 'e'), ('w', 'w')):
        plan, why = RD.deck_plan(FakeDrawing(), 'Tower', 'infinity', word, 'glass', '')
        assert why == ''
        assert plan.v == letter


def test_a_deck_already_laid_out_refuses_rather_than_stacking_a_second_pool(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    d = FakeDrawing(
        [{'id': 'p1', 'kind': 'pool'}],
        ext={'roof_deck': {'Tower': {'view': 'south', 'pool': 'p1'}}},
    )
    plan, why = RD.deck_plan(d, 'Tower', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert 'already laid out facing south (pool p1)' in why
    assert 'add_infinity_pool / add_rooftop_plant directly' in why


def test_a_recorded_deck_whose_pool_was_deleted_may_be_laid_out_again(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    d = FakeDrawing([], ext={'roof_deck': {'Tower': {'view': 'south', 'pool': 'p1'}}})
    plan, why = RD.deck_plan(d, 'Tower', 'infinity', 'south', 'glass', '')
    assert why == ''
    assert plan.g == 'Tower'


def test_a_recorded_deck_that_never_had_a_pool_still_refuses(monkeypatch):
    _with_envelopes(monkeypatch, {'Tower': _env()})
    d = FakeDrawing([], ext={'roof_deck': {'Tower': {'view': 'north', 'pool': ''}}})
    plan, why = RD.deck_plan(d, 'Tower', 'infinity', 'south', 'glass', '')
    assert plan is None
    assert 'already laid out facing north (no pool)' in why


# ── the records the stages hand each other ───────────────────────────────────


def test_a_fresh_deck_build_starts_with_nothing_on_the_deck():
    b = RD.DeckBuild()
    assert (b.guard_ids, b.plant_ids, b.door_ids, b.lines) == ([], [], [], [])
    assert (b.pool_id, b.pool_rect, b.cells) == ('', None, None)
    # each DeckBuild gets its own lists, or two decks in one drawing would share
    b.lines.append('x')
    assert RD.DeckBuild().lines == []


def test_the_plan_is_mutable_because_the_guard_changes_the_envelope():
    plan = RD.DeckPlan(env=_env(), g='Tower', v='s', pk='infinity', gk='glass', N=20, top=54.3, nm='')
    plan.env = _env(zmax=39.9)
    assert plan.env['zmax'] == 39.9
