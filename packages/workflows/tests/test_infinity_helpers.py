# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages add_infinity_pool runs through (infinity_build).

The pure ones — reading the tool's arguments, measuring the deck round the basin
and placing a point out from one of its edges — are exercised with plain values.
The three that draw are driven with a stand-in Drawing that only records what
`new` was asked for, so nothing here needs Blender, a renderer or a service.

`zyg_workflows.arch_assistant` does not import at this commit: its prompts.py
calls _relax_material_enums() at line 278, which reads MATERIALS, which that
module imports at line 352 — a module-scope use-before-bind that raises
NameError as soon as any extension registers a tool with an enum (water_leisure
does). It is nobody's fault here and is reported as a pre-existing break; until
it is fixed, the two names water_leisure's constants are actually built from are
taken from the real config submodule behind a stub parent package.
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

    for _name in ('MATERIALS', 'MAX_OBJECTS', '_num'):
        setattr(_stub, _name, getattr(_config, _name))
    # the rest of water_leisure's import block is not reached by anything tested
    # here; a name is enough for `from zyg_workflows.arch_assistant import ...`
    _stub.__getattr__ = lambda name: name

from zyg_workflows.arch_assistant_ext.water_leisure import infinity_build as ib


class FakeDrawing:
    """Just enough Drawing for the stages that draw: an object list and `new`."""

    def __init__(self, objs=()):
        self.objs = [dict(o) for o in objs]
        self.storey_h = 3.0
        self._n = 0

    def new(self, kind, p, x, z, y, ry, mat, name='', grp=''):
        self._n += 1
        o = {
            'id': f'n{self._n}',
            'kind': kind,
            'p': dict(p),
            'x': x,
            'z': z,
            'y': y,
            'ry': ry,
            'mat': mat,
            'name': name,
            'grp': grp,
        }
        self.objs.append(o)
        return o


def _frame(**over):
    """An 8 x 8 m basin centred on a 40 x 40 m deck, 9.3 m up."""
    pool = {
        'id': 'p1',
        'kind': 'pool',
        'x': 20.0,
        'z': 20.0,
        'y': 9.3,
        'p': {'w': 8.0, 'd': 8.0, 'depth': 1.4, 'raised': ib.INF_RIM, 'coping': ib.INF_COPING},
    }
    f = dict(
        inf='s',
        dep=1.4,
        lv='deck',
        mat=ib.INF_TILE,
        grp='infinity pool',
        pool=pool,
        p=pool['p'],
        W=8.0,
        D=8.0,
        xmin=16.0,
        xmax=24.0,
        zmin=16.0,
        zmax=24.0,
        y=9.3,
        water=9.32,
        deck={'id': 'slab1', 'kind': 'slab', 'x': 20.0, 'z': 20.0, 'y': 9.3, 'p': {'t': 0.3}, 'grp': 'roof deck'},
        ext=(0.0, 0.0, 40.0, 40.0),
        lines=[],
    )
    f.update(over)
    return ib.InfinityFrame(**f)


@pytest.fixture
def quiet_leaves(monkeypatch):
    """The drawing-wide helpers the drawing stages call, answered flatly: room to
    spare, everything inside the deck and every surface at the deck top."""
    monkeypatch.setattr(ib, '_room', lambda d, n: '')
    monkeypatch.setattr(ib, '_inside', lambda ext, x, z, *a: True)
    monkeypatch.setattr(ib, 'surface_top', lambda d, x, z: 9.3)
    monkeypatch.setattr(ib, 'deck_tops', lambda d, x, z: [])
    monkeypatch.setattr(ib, '_pool_span', lambda o, inf: (16.0, 24.0))
    monkeypatch.setattr(ib, '_guards_along', lambda d, dk, inf, ext, lo, hi: [])


# ── pool_options ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('view', 'inf'),
    [('south', 's'), ('north', 'n'), ('east', 'e'), ('west', 'w'), ('  SOUTH ', 's'), (None, 's')],
)
def test_pool_options_reads_the_view_as_the_side_the_water_falls_away_towards(view, inf):
    opts, refused = ib.pool_options(view, 1.4, 'deck', '', '')
    assert refused == ''
    assert opts.inf == inf


def test_pool_options_at_the_defaults_is_a_deck_level_blue_tiled_pool():
    opts, refused = ib.pool_options('south', 1.4, 'deck', '', '')
    assert refused == ''
    assert (opts.dep, opts.lv, opts.mat, opts.grp) == (1.4, 'deck', ib.INF_TILE, 'infinity pool')


def test_pool_options_refuses_a_view_that_is_not_a_compass_side():
    opts, refused = ib.pool_options('up', 1.4, 'deck', '', '')
    assert opts is None
    assert refused.startswith('refused: view must be north, south, east or west')


@pytest.mark.parametrize('depth', [0.4, 3.0])
def test_pool_options_refuses_a_depth_that_is_not_a_swimming_pool(depth):
    opts, refused = ib.pool_options('south', depth, 'deck', '', '')
    assert opts is None
    assert 'a plunge pool or a diving tank is add_pool' in refused


def test_pool_options_refuses_a_level_that_is_neither_deck_nor_raised():
    opts, refused = ib.pool_options('south', 1.4, 'floating', '', '')
    assert opts is None
    assert refused.startswith('refused: level must be "deck"')
    assert 'the basin stands on the deck' in refused, 'the refusal names the other choice'


def test_pool_options_takes_the_level_case_insensitively():
    assert ib.pool_options('south', 1.4, ' RAISED ', '', '')[0].lv == 'raised'


@pytest.mark.parametrize(
    ('material', 'mat'),
    [
        ('', ib.INF_TILE),
        ('blue', 'acg_Tiles135A'),
        ('Turquoise', 'acg_Tiles132A'),
        ('charcoal', 'acg_Tiles052'),
        ('mat_glass', 'mat_glass'),
        ('acg_SomethingElse', ib.INF_TILE),
    ],
)
def test_pool_options_takes_a_tile_name_a_preset_or_falls_back_to_the_blue_tile(material, mat):
    assert ib.pool_options('south', 1.4, 'deck', material, '')[0].mat == mat


def test_pool_options_files_everything_under_the_name_it_was_given():
    assert ib.pool_options('south', 1.4, 'deck', '', 'sky pool')[0].grp == 'sky pool'


# ── _side_free and _at ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('side', 'free', 'run'),
    [('n', 16.0, 8.0), ('s', 16.0, 8.0), ('e', 16.0, 8.0), ('w', 16.0, 8.0)],
)
def test_side_free_measures_the_deck_between_the_basin_and_that_edge(side, free, run):
    assert ib._side_free(_frame(), side) == (free, run)


def test_side_free_reports_the_run_across_the_other_axis():
    f = _frame(W=20.0, D=4.0, xmin=10.0, xmax=30.0, zmin=18.0, zmax=22.0)
    assert ib._side_free(f, 'n') == (18.0, 20.0), 'a north/south side runs the pool width'
    assert ib._side_free(f, 'e') == (10.0, 4.0), 'an east/west side runs its depth'


def test_side_free_measures_nothing_on_the_ground():
    assert ib._side_free(_frame(deck=None, ext=None), 'n') == (0.0, 0.0)


@pytest.mark.parametrize(
    ('side', 'ox', 'oz', 'point'),
    [('n', 0, -1, (20.0, 13.6)), ('s', 0, 1, (20.0, 26.4)), ('e', 1, 0, (26.4, 20.0)), ('w', -1, 0, (13.6, 20.0))],
)
def test_at_steps_out_from_the_edge_on_the_axis_that_side_faces(side, ox, oz, point):
    edge = {'n': 16.0, 's': 24.0, 'e': 24.0, 'w': 16.0}[side]
    assert ib._at(2.4, 20.0, side, edge, ox, oz) == point


def test_at_runs_along_the_edge_on_the_other_axis():
    assert ib._at(2.4, 17.0, 'n', 16.0, 0, -1) == (17.0, 13.6)
    assert ib._at(2.4, 17.0, 'w', 16.0, -1, 0) == (13.6, 17.0)


# ── deck_works ────────────────────────────────────────────────────────────


def test_deck_works_on_the_ground_needs_no_guard_and_no_tank(quiet_leaves):
    f = _frame(deck=None, ext=None)
    d = FakeDrawing()
    ib.deck_works(d, f)
    assert f.lines == ['on the ground: no roof guard needed']
    assert d.objs == [], 'nothing is drawn where there is no deck to drop off'


def test_deck_works_builds_a_glass_balustrade_along_the_whole_weir_edge(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.deck_works(d, f)
    wall = [o for o in d.objs if o['kind'] == 'wall']
    assert len(wall) == 1
    assert wall[0]['p'] == {'len': 40.0, 'h': ib.GUARD_H, 't': ib.GUARD_T}
    assert wall[0]['mat'] == 'mat_glass'
    assert wall[0]['z'] == 40.0 - ib.GUARD_IN - ib.GUARD_T / 2, 'outboard, just inside the south edge'
    assert wall[0]['ry'] == 0.0, 'a north/south edge runs across x'
    assert wall[0]['grp'] == 'roof deck', "the guard belongs to the deck's group, not the pool's"
    assert 'the weir is never the building edge' in f.lines[0]


def test_deck_works_turns_an_east_edge_guard_through_a_right_angle(quiet_leaves):
    f = _frame(inf='e')
    d = FakeDrawing()
    ib.deck_works(d, f)
    wall = next(o for o in d.objs if o['kind'] == 'wall')
    assert wall['p']['len'] == 40.0
    assert wall['x'] == 40.0 - ib.GUARD_IN - ib.GUARD_T / 2
    assert round(wall['ry'], 5) == round(ib.math.pi / 2, 5)


def test_deck_works_raises_and_glazes_a_guard_that_is_already_there(monkeypatch, quiet_leaves):
    low = {'id': 'w1', 'kind': 'wall', 'p': {'h': 0.9}, 'mat': 'mat_concrete'}
    tall = {'id': 'w2', 'kind': 'wall', 'p': {'h': 1.4}, 'mat': 'mat_concrete'}
    monkeypatch.setattr(ib, '_guards_along', lambda *a: [low, tall])
    f = _frame()
    d = FakeDrawing()
    ib.deck_works(d, f)
    assert low['p']['h'] == ib.GUARD_H, 'a low parapet is lifted to the guard height'
    assert tall['p']['h'] == 1.4, 'a taller one is left alone'
    assert low['mat'] == tall['mat'] == 'mat_glass'
    assert [o['kind'] for o in d.objs] == ['zone'], 'no second guard is built where one exists'
    assert f.lines[0] == 'guard: w1, w2 on the south deck edge is glass, 1.1 m (raised from lower: w1)'


def test_deck_works_hangs_the_tank_into_the_storey_below(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.deck_works(d, f)
    zone = next(o for o in d.objs if o['kind'] == 'zone')
    assert zone['p']['use'] == 'plant'
    assert zone['p']['name'] == 'pool tank + balance tank + plant'
    assert zone['y'] == 9.3 - 3.0, 'one storey down, there being no deck under it'
    assert zone['grp'] == 'infinity pool'
    # the zone reaches 2.5 m past the basin on the side away from the weir
    assert zone['z'] == (16.0 - 2.5 + 24.0) / 2
    assert 'no rooms there' in f.lines[1]


def test_deck_works_puts_the_tank_on_the_deck_it_finds_below(monkeypatch, quiet_leaves):
    monkeypatch.setattr(ib, 'deck_tops', lambda d, x, z: [(6.3, None), (9.3, None)])
    f = _frame()
    d = FakeDrawing()
    ib.deck_works(d, f)
    assert next(o for o in d.objs if o['kind'] == 'zone')['y'] == 6.3
    assert 'into storey 2' in f.lines[1]


def test_deck_works_digs_no_tank_for_a_raised_basin(quiet_leaves):
    f = _frame(lv='raised')
    d = FakeDrawing()
    ib.deck_works(d, f)
    assert [o['kind'] for o in d.objs] == ['wall']
    assert f.lines[1] == f'raised {ib.INF_RIM:g} m: the basin stands on the deck, walls in {ib.INF_TILE}'


# ── lounger_row ───────────────────────────────────────────────────────────


def test_lounger_row_lies_the_row_along_the_side_opposite_the_weir(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    row_side, full = ib.lounger_row(d, f, True, True, True)
    assert (row_side, full) == ('n', '')
    kinds = [o['kind'] for o in d.objs]
    # 8 m of pool at a 2.4 m step is two loungers: floor((8 - 1) / 2.4)
    assert kinds.count('sun_lounger') == 2
    assert kinds.count('umbrella') == 1, 'one parasol behind every other lounger'
    assert kinds.count('tree_palm') == 2, 'one at each end of the row'
    assert f.lines == [
        '2 loungers on the north side facing south, 1 parasols behind them, 2 palms at the ends of the row'
    ]


def test_lounger_row_puts_the_loungers_clear_of_the_coping_facing_the_view(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.lounger_row(d, f, True, False, False)
    lounger = next(o for o in d.objs if o['kind'] == 'sun_lounger')
    assert lounger['z'] == 16.0 - (ib.LOUNGER_OFF + 0.95), 'north of the basin by the lounger clearance'
    assert lounger['ry'] == ib._FACE_X['s']
    assert lounger['y'] == 9.3
    # two loungers, centred on the basin: 20 +/- LOUNGER_STEP / 2
    assert [o['x'] for o in d.objs if o['kind'] == 'sun_lounger'] == [18.8, 21.2]


def test_lounger_row_takes_a_flank_when_the_opposite_side_is_too_shallow(quiet_leaves):
    # 1.5 m of deck north of the basin, 16 m east and west of it
    f = _frame(ext=(0.0, 14.5, 40.0, 40.0))
    d = FakeDrawing()
    row_side, _full = ib.lounger_row(d, f, True, True, True)
    assert row_side in 'ew', 'a flank, not the weir side and not the shallow one'
    assert f.lines[0].startswith('2 loungers on the ')


def test_lounger_row_says_so_when_the_pool_fills_the_deck(quiet_leaves):
    f = _frame(ext=(16.0, 16.0, 24.0, 24.0))
    d = FakeDrawing()
    assert ib.lounger_row(d, f, True, True, True) == ('', '')
    assert f.lines == ['no deck room for loungers: the pool fills the deck (use a smaller block)']
    assert d.objs == []


def test_lounger_row_draws_nothing_when_the_loungers_were_turned_off(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    assert ib.lounger_row(d, f, False, True, True) == ('', '')
    assert (f.lines, d.objs) == ([], [])


def test_lounger_row_hands_back_the_room_refusal_before_it_draws_anything(monkeypatch, quiet_leaves):
    monkeypatch.setattr(ib, '_room', lambda d, n: f'no room: {n} more objects')
    f = _frame()
    d = FakeDrawing()
    row_side, full = ib.lounger_row(d, f, True, True, True)
    assert row_side == 'n'
    assert full == 'no room: 6 more objects', '2 loungers + 2 parasols + 2 palms'
    assert (f.lines, d.objs) == ([], []), 'the row is all-or-nothing'


def test_lounger_row_pulls_a_palm_in_to_the_deck_margin(quiet_leaves):
    # the deck stops at the basin's west wall, so the west palm's point (16.6)
    # is short of PALM_IN and is pulled in rather than dropped (2026-09-16)
    f = _frame(ext=(16.0, 0.0, 40.0, 40.0))
    d = FakeDrawing()
    ib.lounger_row(d, f, True, False, True)
    palms = [o for o in d.objs if o['kind'] == 'tree_palm']
    assert [o['x'] for o in palms] == [17.2, 23.4], 'the west end clamped to ext[0] + PALM_IN'
    assert all(o['z'] == 16.0 - (ib.LOUNGER_OFF + 0.95) for o in palms), 'on the lounger line'
    assert [o['name'] for o in palms] == ['palm 1', 'palm 2']
    assert f.lines[0].endswith('2 palms at the ends of the row')


def test_lounger_row_plants_no_palm_on_a_deck_narrower_than_its_margins(quiet_leaves):
    # 2 m of deck across cannot hold PALM_IN on both sides of a palm
    f = _frame(ext=(19.0, 0.0, 21.0, 40.0))
    d = FakeDrawing()
    ib.lounger_row(d, f, True, False, True)
    assert [o['kind'] for o in d.objs].count('tree_palm') == 0
    assert 'palms' not in f.lines[0]


# ── underwater_lights ─────────────────────────────────────────────────────


def test_underwater_lights_lines_the_deck_side_wall_and_never_the_weir(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.underwater_lights(d, f, True)
    lamps = [o for o in d.objs if o['kind'] == 'light_point']
    assert len(lamps) == ib.LIGHT_N
    assert all(o['z'] == 16.0 + 0.5 for o in lamps), 'just inside the north wall, away from the weir'
    assert [o['x'] for o in lamps] == [17.0, 19.0, 21.0, 23.0]
    assert f.lines == ['4 warm underwater lights along the north wall (none on the weir side)']


def test_underwater_lights_stay_above_the_deck_top_so_they_are_not_buried(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.underwater_lights(d, f, True)
    # 0.25 m under a water line 0.02 m above the deck would be inside the slab
    assert all(o['y'] == 9.32 for o in d.objs)


def test_underwater_lights_hang_under_the_water_of_a_raised_basin(quiet_leaves):
    f = _frame(lv='raised', water=10.6)
    d = FakeDrawing()
    ib.underwater_lights(d, f, True)
    assert all(o['y'] == 10.35 for o in d.objs)


def test_underwater_lights_say_how_many_lamps_the_drawing_already_holds(quiet_leaves):
    f = _frame()
    d = FakeDrawing([{'kind': 'light_point'}] * ib.LIGHT_CAP)
    ib.underwater_lights(d, f, True)
    assert f.lines == [f'no underwater lights: the drawing already holds {ib.LIGHT_CAP} of {ib.LIGHT_CAP} lamps']
    assert len([o for o in d.objs if o['kind'] == 'light_point']) == ib.LIGHT_CAP


def test_underwater_lights_say_so_when_the_drawing_is_full(monkeypatch, quiet_leaves):
    monkeypatch.setattr(ib, '_room', lambda d, n: 'no room')
    f = _frame()
    d = FakeDrawing()
    ib.underwater_lights(d, f, True)
    assert f.lines == ['no underwater lights: the drawing is full']
    assert d.objs == []


def test_underwater_lights_turned_off_say_nothing_at_all(quiet_leaves):
    f = _frame()
    d = FakeDrawing()
    ib.underwater_lights(d, f, False)
    assert (f.lines, d.objs) == ([], [])
