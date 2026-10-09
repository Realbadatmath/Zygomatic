# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_tower_replay.py — job 71ac02b0, replayed through the new tools.

Task 16 of the "five layers" tree. On 2026-09-10 a Sonnet run built the operator's
20-storey luxury tower and the tools let it produce: ONE stair_u record of 285 steps
(two 39.8 m flights through 19 slabs and out through the east wall); two 54 m lift
shafts with no doors, no overrun and no floor openings; a fire escape INSIDE the plan;
stair and lifts stopping at storey 19 while the infinity pool sits on storey 20; every
surface in mat_concrete on a request that said "luxurious"; and `design_check` calling
all of that "0 errors" three times.

This file replays that job's 27 calls IN ORDER against the CURRENT tools and measures
the result. It is offline: no Blender, no Chrome, no model — the Drawing and the
design checks only. Runs in a few seconds.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_tower_replay.py

TWO DEPARTURES FROM THE LEDGER, both deliberate and both marked in CALLS below:
  · call 3 passes name='tower'. The ledger's later calls all say group='tower', so the
    run named the group; draw_box otherwise calls it "box EX90-FQ109" and every facade
    call is refused. Passing the name is what makes the replay faithful, not what makes
    it pass.
  · calls 8-11 pass the CORRECTED arguments (to_storey=20, group+side for the fire
    escape) rather than the ledger's to_storey=19 / cell='FH91'. The ledger's own
    arguments are replayed separately in `old_calls()`, which proves they are now
    refused or caught.

WHAT THIS TEST FOUND (2026-09-11) — three relations the tools still get wrong. They are
checked here as failures on purpose, so they cannot be forgotten:

  R1  add_fire_escape(group='tower', side='north') hangs the stair on the SOUTH facade.
      The record lands at z = -40.23; the tower envelope is zmin -61 (north, row 90) ..
      zmax -41 (south, row 109), so it is 0.77 m outside the SOUTH face — the same
      facade as the entrance door and the canopy, and the side plan_building's own
      checklist calls "the side OPPOSITE the entrance". The reply text says "on the
      north facade of "tower" (wall o2)" and o2 is the south wall of storey 0.

  R2  add_stair(cell, from_storey=0, to_storey=20) does not reach the roof deck.
      20 flights * 2.7 m = 54.0 m, the structural top of storey 19; the deck surface is
      54.3 m. building_program._ev_roof_access and circulation_rules both call that an
      error ("0.3 m short"), while stairs_vertical's PROMPT, its EXAMPLES and the
      checklist plan_building prints all say to_storey=20 for a 20-storey tower.
      to_storey=21 clears both errors. One of the two has to move.

  R3  the sightline check judges INTERNAL room doors against the site drive. The WC,
      the cycle store and the refuse store each raise "entrance <id> door <room> is
      hidden from the drive". A WC door is not an entrance.

  R4  building_program counts mat_glass as an unfinished preset, so the programme's
      "finishes" item can never clear. With every other surface repainted in a library
      material the row still reads "6 of 148 shell record(s) are still flat presets
      (mat_glass x6)" — those six are the curtain walls add_curtain_wall deliberately
      set to glass. design_rules.finish_preset gets this right (it reports 0 errors on
      the same drawing); the two families disagree about what a finish is.

  R5  (2026-09-12, now GREEN) add_street_furniture put the lamp posts under the
      porte-cochère. It refuses those cells and names the clear ones.

WHAT THE MACROS FOUND IN THE OLD CALLS (2026-09-16). Section 2 used to finish the
building the way the ledger built it — a raw call per part with the cells picked by
hand — and that left 13 errors no amount of re-picking cleared. Each one is a
by-hand siting mistake the matching kit does not make, so section 2 now deletes
what the hand-made call left and calls the macro. All five are GREEN below:

  R6  the core, sited cell by cell (add_stair FH96 + add_elevator FD96/FK96), puts
      the stair's head house across a lift shaft on the deck (clash_core_wall
      "o512 lift shaft st0-20 passes through o327 east wall head house") and stands
      the stair in the ground corridor. add_core(group, position, lifts) lays the
      flight, both shafts, the shared landing and the head house out together and
      says so: "design_check: 0 error(s) on the core records".

  R7  the ledger's entrance is a 10 x 2 m strip called "Lobby" plus an add_corridor
      across the door axis. Four errors: ent_axis_blocked (a corridor wall 3.0 m
      inside the door, across the 2 m lobby axis), ent_lobby_behind (the lobby rect
      starts another 1.0 m in), open_overlap (the corridor door and the lobby door
      cut the same piece of wall), and clash_furniture_wall x4 (the reception desk
      and both sofas through those corridor walls). build_entrance re-uses the door
      o102 and the canopy o103 the ledger ALREADY drew — it does not cut a second
      hole — and lays a 10 x 9 m lobby on the door's own axis.

  R8  add_beach_set on hand-picked cells put all four loungers IN the water
      (clash_furniture_water, 0.70 x 1.05 m overlap each). build_roof_deck derives
      the pool band, the guard, the plant and the loungers from the envelope.

  R9  ONE clash no macro settles: build_roof_deck hangs the pool's tank BELOW the
      deck, into storey 19, where layout_floor has already run its party walls
      (clash_wall_water x2). Neither family moves the other's records, so the fix
      is delete() on the two walls the finding itself names. test_tower_recipe.py
      hits exactly the same pair — it is the tank/plate seam, not this replay.

Everything else the tree built is proved green below.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()

REQUEST = (
    'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . '
    'roof entrance . nice entrance into the building at ground floor . make ground floor glass walls , '
    '2nd floor rough concrete wall , 3rd floor glass walls , 4th rough concrete , repeat this for all '
    'floors. center building at cell fh100  make building look luxurious'
)

H = 2.7  # d.storey_h
DECK = 54.3  # the roof deck of a 20-storey box: 20 * 2.7 + a 0.3 m slab

# the 24 calls of the job, in order. [ledger: ...] marks what the original run sent.
CALLS = [
    ('plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, skip=['parking'])),
    ('search_materials', dict(query='board-formed rough concrete', limit=3)),
    (
        'draw_box',
        dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', material='pht_rough_concrete', name='tower'),
    ),  # name: see the docstring
    ('add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.4, height=3)),
    ('add_canopy', dict(group='tower', side='south', storey=0, width=12, depth=5, height=4.2)),
    (
        'add_curtain_wall',
        dict(
            walls='tower', storeys=[0, 2, 4, 6, 8, 10, 12, 14, 16, 18], mullion=1.5, transom=1.35, name='tower_glazing'
        ),
    ),
    (
        'add_facade_bands',
        dict(group='tower', kind='string_course', every_n_storeys=1, depth=0.15, material='pht_rough_concrete'),
    ),
    (
        'add_stair',
        dict(cell='FH96', from_storey=0, to_storey=20, kind='u', width=1.2, material='mat_concrete'),
    ),  # [ledger: to_storey=19]
    # 2026-09-12: the old run's FF96/FJ96 land 0.62 m inside the stair's 3.44 x 2.60 m plan,
    # and FF96 also sits in the 1.2 m of floor at its foot — both refused now.  FD96/FK96
    # are the clear cells the refusal itself names: >= 4 cells west / >= 3 cells east.
    (
        'add_elevator',
        dict(cell='FD96', from_storey=0, to_storey=20, w=1.8, depth=2, material='mat_concrete'),
    ),  # [ledger: cell='FF96', 19]
    (
        'add_elevator',
        dict(cell='FK96', from_storey=0, to_storey=20, w=1.8, depth=2, material='mat_concrete'),
    ),  # [ledger: cell='FJ96']
    (
        'add_fire_escape',
        dict(group='tower', side='north', storeys=20, width=1.2, material='mat_concrete', name='fire_escape'),
    ),  # [ledger: cell='FH91']
    ('add_parapet', dict(group='tower', height=1.1, thickness=0.2, cap=True, material='pht_rough_concrete')),
    (
        'add_pool',
        dict(cell_from='FC104', cell_to='FN108', storey=20, depth=1.5, infinity='south', name='rooftop_infinity_pool'),
    ),
    ('add_rooftop_plant', dict(group='tower', kinds=['hvac_unit', 'water_tank', 'antenna'], name='rooftop_plant')),
    ('add_road', dict(cells=['FH135', 'FH112'], width=8, name='approach_drive')),
    (
        'plant_tree_line',
        dict(cells=['FA135', 'FA123'], kind='deciduous', height=12, spacing=8, model='real', name='west_avenue'),
    ),
    (
        'plant_tree_line',
        dict(cells=['FP135', 'FP123'], kind='deciduous', height=12, spacing=8, model='real', name='east_avenue'),
    ),
    # 2026-09-12: the old run's FD114/FM114 sit under the canopy and FD1xx is 4.0 m off the 8 m drive's centreline
    # (its edge) — both refused now (checked below); FC is 5 m off, clear of the carriageway
    (
        'add_street_furniture',
        dict(
            cells=['FC116', 'FC122', 'FC130', 'FM116', 'FM122', 'FM130'],
            kind='lamp_post',
            height=5,
            model='real',
            name='approach_lighting',
        ),
    ),
    ('add_room', dict(cell_from='FD107', cell_to='FM108', door_side='south', storey=0, name='Lobby', wall_h=5.4)),
    ('add_room', dict(cell_from='EY100', cell_to='FA103', door_side='east', storey=0, name='WC')),
    (
        'add_room',
        dict(cell_from='EZ92', cell_to='FB96', door_side='east', storey=0, name='Cycle store'),
    ),  # [ledger: EZ92..EC96, outside]
    ('add_room', dict(cell_from='FO92', cell_to='FQ96', door_side='west', storey=0, name='Refuse store')),
    (
        'add_corridor',
        dict(cell_from='FE106', cell_to='FL97', direction='z', width=1.8, storey=0, name='ground_corridor'),
    ),
    (
        'furnish_bathroom',
        dict(cell_from='EY100', cell_to='FA103', door_side='east', storey=0, shower=False, bath=False),
    ),
]


def _errors(d) -> list:
    return [f for f in A.EXT_MODULES['design_rules'].run_checks(d) if f.get('sev') == 'error']


def _warns(d) -> list:
    return [f for f in A.EXT_MODULES['design_rules'].run_checks(d) if f.get('sev') == 'warn']


def _of_kind(d, kind) -> list:
    return [o for o in d.objs if o['kind'] == kind]


# ── the replay ───────────────────────────────────────────────────────────────
print('\n=== 1. the 24 calls, in order ===')
d = A.Drawing(None)
d.request = REQUEST
said = {}
for i, (tool, args) in enumerate(CALLS, 1):
    said[i] = str(A.call_tool(d, tool, args))
    refused = said[i].startswith('refused')
    check('call %2d %s' % (i, tool), not refused, said[i][:200])

# 18 — 2026-09-12 site defaults: the old run's lamp cells FD114/FM114 stood under the porte-cochère;
# the tool now refuses them and names the clear cells (FD116/FM116), which the replay uses above.
under = str(
    A.call_tool(
        d,
        'add_street_furniture',
        dict(cells=['FD114', 'FM114'], kind='lamp_post', height=5, model='real', name='lamps under the canopy'),
    )
)
check(
    'R5 lamps under the canopy are refused naming the clear cells',
    under.startswith('refused') and 'FD116' in under and 'FM116' in under,
    under[:200],
)

# 1 — the programme carries the request's own words
plan = said[1]
for word in ('roof access', 'FROM THE REQUEST', 'luxury'):
    check('plan_building names %r' % word, word in plan, plan[:200])

# 8 — the stair is one record per storey, not one 285-step flight
stairs = _of_kind(d, 'stair_u')
check('stair: 20 records (one per storey)', len(stairs) == 20, len(stairs))
worst = max((int((o['p'] or {}).get('steps') or 0) for o in stairs), default=0)
check('stair: every flight <= 18 steps', worst and worst <= 18, 'worst flight %d steps' % worst)
check(
    'stair: rails on every record',
    all(int((o['p'] or {}).get('rails') or 0) == 1 for o in stairs),
    sorted({(o['p'] or {}).get('rails') for o in stairs}),
)
ys = sorted(round(o['y'], 3) for o in stairs)
check('stair: y steps by 2.7 m from 0', ys == [round(n * H, 3) for n in range(20)], ys[:4])

# 9, 10 — the shafts have doors and an overrun
shafts = _of_kind(d, 'elevator_shaft')
check('lifts: 2 shafts', len(shafts) == 2, len(shafts))
check(
    'lifts: 21 doors each (storeys 0..20)',
    all(len((o['p'] or {}).get('doors') or []) == 21 for o in shafts),
    [len((o['p'] or {}).get('doors') or []) for o in shafts],
)
check(
    'lifts: overrun above the top deck',
    all(float((o['p'] or {}).get('overrun') or 0) > 0 for o in shafts),
    [(o['p'] or {}).get('overrun') for o in shafts],
)

# the voids the old run never cut
voids = (d.ext or {}).get('slab_voids') or []
check('slab_voids: >= 20 openings recorded', len(voids) >= 20, len(voids))

# the head house the old run never built
groups = {o.get('grp') or '' for o in d.objs}
heads = [g for g in groups if g.endswith('head house')]
check('a head house group exists', bool(heads), sorted(groups))
if heads:
    hy = [o['y'] for o in d.objs if (o.get('grp') or '') == heads[0]]
    check('head house stands on the deck', hy and min(hy) >= DECK - 0.6, min(hy) if hy else None)

# 11 — the fire escape is outside the envelope
E = A.EXT_MODULES['envelope_rules']
env = E.group_envelope(d, 'tower')
fes = _of_kind(d, 'fire_stair_exterior')
check('fire escape: one record', len(fes) == 1, len(fes))
if fes and env:
    fe = fes[0]
    check(
        'fire escape is OUTSIDE the tower envelope',
        not E.inside(env, fe['x'], fe['z']),
        (fe['x'], fe['z'], env.get('zmin'), env.get('zmax')),
    )
    # north = -Z = the SMALL rows = env['zmin']; south = env['zmax'].
    d_north, d_south = abs(fe['z'] - env['zmin']), abs(fe['z'] - env['zmax'])
    check(
        'R1 fire escape hangs on the NORTH facade, as asked',
        d_north < d_south,
        'z %.2f is %.2f m from the north face (%.1f) and %.2f m from the south face (%.1f)'
        % (fe['z'], d_north, env['zmin'], d_south, env['zmax']),
    )

# 25, 26 — the balconies the old run answered "added 0" to
state = str(A.call_tool(d, 'get_state', {'detail': 'objects', 'which': 'curtain_wall'}))
south_cw = [l.split()[0] for l in state.splitlines() if ' curtain_wall @FH110 ' in l]
check('get_state lists the south curtain walls (storeys 2..18)', len(south_cw) >= 9, south_cw)
before = len(_of_kind(d, 'balcony')) + len([o for o in d.objs if 'balcon' in o['kind']])
said[26] = str(
    A.call_tool(
        d,
        'add_balconies',
        dict(walls=south_cw, width=4, depth=1.8, rail_h=1.1, material='pht_rough_concrete', name='south_balconies'),
    )
)
made = len([o for o in d.objs if 'balcon' in o['kind']]) - before
check('call 26 add_balconies adds >= 9 balconies', made >= 9, '%s -> %d records' % (said[26][:120], made))

# 27 — the design check no longer says "0 errors"
said[27] = str(A.call_tool(d, 'design_check', {}))
errs = _errors(d)
check('call 27 design_check does NOT say 0 errors', len(errs) > 0, said[27][:160])

print('\n=== 2. finishing the building: the three MACROS ===')
codes = sorted({f.get('code') for f in errs})
print('  error codes after the replay: %s' % codes)
# 2026-09-16: this phase used to repeat the ledger's habit — a raw call per part,
# with the cells worked out by hand. Every error left after the replay came from
# that habit (R6, R7, R8 in the docstring). The three kits each do one of those
# jobs in ONE call and derive their own cells from the envelope, so the fix-up is
# now: delete what the hand-made call left behind, then call the macro.


def _grp_ids(*names) -> list:
    return [o['id'] for o in d.objs if (o.get('grp') or '') in names]


def _kind_ids(*kinds) -> list:
    return [o['id'] for o in d.objs if o['kind'] in kinds]


def _fix(label, tool, args, n=260):
    said = str(A.call_tool(d, tool, args))
    check('fix-up %-28s is not refused' % ('%s %s' % (tool, label)).strip(), not said.startswith('refused'), said[:n])
    return said


# ── R6: the core, as ONE call ────────────────────────────────────────────────
# The ledger sited the stair and the two lifts cell by cell. That leaves the
# stair's head house across a lift shaft on the deck (clash_core_wall) and a
# stair standing in the ground corridor. add_core lays the flight, the shafts,
# the shared landing and the head house out together off the envelope.
_fix(
    'the by-cell core',
    'delete',
    dict(which=_kind_ids('stair_u', 'elevator_shaft', 'elevator_car') + _grp_ids('tower head house')),
    120,
)
said_core = _fix('', 'add_core', dict(group='tower', position='north', lifts=2), 400)
check(
    'R6 add_core reports its own records clean',
    'design_check: 0 error(s) on the core records' in said_core,
    said_core[:300],
)
core = (d.ext.get('core') or {}).get('tower') or {}
_bbs = [E.bbox_of(d.find(i)) for i in (list(core.get('lifts') or []) + list(core.get('stair') or [])) if d.find(i)]
_land = core.get('landing') or [0, 0, 0, 0]
CORE_FROM = A.cell_of(min([b[0] for b in _bbs] + [_land[0]]) - 0.05, min([b[1] for b in _bbs] + [_land[1]]) - 0.05)
CORE_TO = A.cell_of(max([b[2] for b in _bbs] + [_land[2]]) + 0.05, max([b[3] for b in _bbs] + [_land[3]]) + 0.05)
check('the core block add_core built is one addressable rect', bool(CORE_FROM and CORE_TO), (CORE_FROM, CORE_TO))

# ── R7: the entrance, as ONE call ────────────────────────────────────────────
# The ledger drew a 10 x 2 m strip called "Lobby" and then an add_corridor across
# the door axis. build_entrance RE-USES the door (o102) and the canopy (o103) the
# ledger already put in the south wall and lays the lobby on the door's own axis.
_fix('the hand-built lobby + ground corridor', 'delete', dict(which=_grp_ids('Lobby', 'ground_corridor')), 120)
said_ent = _fix('', 'build_entrance', dict(group='tower', side='south', style='luxury'), 500)
check(
    'R7 build_entrance re-uses the door the ledger drew, it does not cut a second one',
    're-used the existing double_door' in said_ent,
    said_ent[:400],
)
check('and it re-uses the canopy too', 're-used the canopy' in said_ent, said_ent[:400])

# ── R8: the roof deck, as ONE call ───────────────────────────────────────────
# add_beach_set on hand-picked cells put all four loungers IN the water.
# build_roof_deck sets the pool band, the guard, the plant and the loungers from
# the envelope in one go, each clear of the others.
_fix('the hand-placed pool + plant', 'delete', dict(which=_grp_ids('rooftop_infinity_pool', 'rooftop_plant')), 120)
said_deck = _fix('', 'build_roof_deck', dict(group='tower', view='south'), 400)
check(
    'R8 build_roof_deck puts the loungers on dry deck',
    not [f for f in _errors(d) if f.get('code') == 'clash_furniture_water'],
    [str(f.get('text'))[:120] for f in _errors(d) if f.get('code') == 'clash_furniture_water'],
)

# ── the typical floors, on the block add_core just reported ──────────────────
said_layout = _fix(
    'storey 1',
    'layout_floor',
    dict(
        cell_from='EX90',
        cell_to='FQ109',
        use='residential',
        storey=1,
        corridor_w=1.8,
        core_from=CORE_FROM,
        core_to=CORE_TO,
    ),
    300,
)
said_rep = _fix('2..19', 'repeat_floor', dict(from_storey=2, to_storey=19, source_storey=1), 200)

# ── R9: the one clash no macro can settle ────────────────────────────────────
# The roof deck hangs the pool's tank BELOW the deck, into storey 19, where
# layout_floor has already run its party walls. Neither family moves the other's
# records; delete on the two walls the finding names is the whole fix, and it is
# what clash_wall_water's own text asks for.
drowned = []
for f in _errors(d):
    if f.get('code') == 'clash_wall_water':
        m = re.match(r'\s*(o\d+)', str(f.get('text') or ''))
        if m:
            drowned.append(m.group(1))
check(
    'R9 clash_wall_water names the storey-19 party walls under the pool tank',
    len(drowned) >= 1,
    [str(f.get('text'))[:150] for f in _errors(d) if f.get('code') == 'clash_wall_water'],
)
if drowned:
    _fix('the drowned party walls', 'delete', dict(which=sorted(set(drowned))), 120)

# ── the finishes the request asked for ───────────────────────────────────────
A.call_tool(d, 'set_finish', dict(group='tower', floor_material=A.FINISHES['luxury']['floor']))
presets = [o['id'] for o in d.objs if str(o.get('mat') or '').startswith('mat_') and o.get('mat') != 'mat_glass']
A.call_tool(d, 'set_material', dict(which=presets, material=A.FINISHES['luxury']['floor']))

BP = A.EXT_MODULES['building_program']
rows = BP.status(d, BP.get_program(d))
missing = [r.get('key') for r in rows if r.get('need') == 'required' and not r.get('ok')]
check('deck furniture clears the programme (build_roof_deck)', 'deck_furniture' not in missing, missing)
check('the reception desk clears the programme (build_entrance)', 'reception' not in missing, missing)
check('typical floors clear the programme', 'typical_floors' not in missing, missing)
check(
    'every REQUIRED programme item is built',
    not missing,
    [(r.get('key'), str(r.get('detail'))[:160]) for r in rows if r.get('need') == 'required' and not r.get('ok')],
)
lobby_row = next((r for r in rows if r.get('key') == 'lobby'), {})
check('the furnished lobby clears the programme', 'lobby' not in missing, (missing, str(lobby_row.get('detail'))[:300]))
fin = [r for r in rows if r.get('key') == 'finishes']
check(
    'R4 the finishes clear the programme once nothing but glass is a preset',
    'finishes' not in missing,
    str(fin[0].get('detail')) if fin else missing,
)
check(
    'R2 to_storey=20 reaches the roof deck',
    'roof_access' not in missing,
    'roof_access still missing: 20 flights * %.1f m = %.1f m, deck %.1f m — to_storey=21 clears it' % (H, 20 * H, DECK),
)

errs = _errors(d)
left = sorted({f.get('code') for f in errs})
check('no envelope error survives', 'envelope_poke' not in left and 'envelope_outside' not in left, left)
check('no void error survives', not any(str(c).startswith('void_') for c in left), left)
check('no stair-flight error survives', 'circ_flight' not in left and 'circ_stair_guard' not in left, left)
check('no finish error survives', 'finish_preset' not in left, left)
sight = [f for f in errs if f.get('code') == 'sightline']
rooms_only = all(
    any(w in str(f.get('text') or '') for w in ('WC', 'Cycle store', 'Refuse store', 'Lobby', 'head house'))
    for f in sight
)
check(
    'R3 the sightline check leaves internal room doors alone',
    not sight,
    '%d sightline error(s), all on internal doors: %s'
    % (len(sight), '; '.join(str(f.get('text'))[:90] for f in sight[:3]))
    if rooms_only
    else sight,
)
check('no clash error survives', not any(str(c).startswith('clash_') for c in left), left)
check('no entrance error survives', not any(str(c).startswith('ent_') for c in left), left)
# the whole point of the file: every family, silent. On a failure print the
# findings in full — a bare code list is not enough to fix anything by.
check(
    'the drawing reaches 0 errors — from EVERY family',
    not errs,
    '\n      ' + '\n      '.join('[%s] %s' % (f.get('code'), f.get('text')) for f in errs),
)
print('  warnings left: %d' % len(_warns(d)))
for f in _warns(d):
    print('   · [%s] %s' % (f.get('code'), str(f.get('text'))[:150]))

# ── the OLD calls: they must now be refused or caught ────────────────────────
print("\n=== 3. the ledger's own arguments ===")
d2 = A.Drawing(None)
d2.request = REQUEST
A.call_tool(
    d2, 'plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, skip=['parking'])
)
A.call_tool(
    d2,
    'draw_box',
    dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', material='pht_rough_concrete', name='tower'),
)
cx, cz = A.cell_centre(*A.parse_cell('FH96'))
old = d2.new(
    'stair_u',
    {'steps': 285, 'rise': 0.18, 'run': 0.28, 'w': 1.2, 'gap': 0.2},
    cx,
    cz,
    0,
    0,
    'mat_concrete',
    grp='tower',
)
f2 = _errors(d2)
flight = [x for x in f2 if x.get('code') == 'circ_flight']
check(
    'the 285-step stair is caught, and the flight length named',
    flight and '39.8' in str(flight[0].get('text')),
    flight[0].get('text')[:200] if flight else f2[:1],
)
crossings = [x for x in f2 if str(x.get('code') or '').startswith('void_missing')]
check(
    'the 285-step stair is caught crossing the slabs',
    len(crossings) >= 2,
    crossings[0].get('text')[:180] if crossings else [x.get('code') for x in f2],
)
check(
    'the 285-step stair is caught leaving the plan',
    any(x.get('code') == 'envelope_poke' for x in f2),
    [x.get('code') for x in f2],
)
check(
    'the 285-step stair is caught with no rails',
    any(x.get('code') == 'circ_stair_guard' for x in f2),
    [x.get('code') for x in f2],
)

fe_old = str(A.call_tool(d2, 'add_fire_escape', {'cell': 'FH91', 'storeys': 20}))
check(
    'add_fire_escape(cell="FH91") is refused for being inside',
    fe_old.startswith('refused') and 'inside' in fe_old,
    fe_old[:200],
)

room_old = str(
    A.call_tool(
        d2, 'add_room', {'cell_from': 'EZ100', 'cell_to': 'EB103', 'door_side': 'east', 'storey': 0, 'name': 'WC'}
    )
)
wc = [x for x in _errors(d2) if x.get('code') == 'envelope_outside' and 'WC' in str(x.get('text'))]
check(
    'a room outside every building is refused or caught',
    room_old.startswith('refused') or bool(wc),
    (room_old[:120], [x.get('text')[:140] for x in wc]),
)

# 2026-09-12: the two defects the prevention tasks closed, asked with the ledger's own
# arguments on a clean tower — the tools must refuse them, and say where to go instead.
d3 = A.Drawing(None)
d3.request = REQUEST
A.call_tool(
    d3, 'plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, skip=['parking'])
)
A.call_tool(
    d3,
    'draw_box',
    dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', material='pht_rough_concrete', name='tower'),
)
A.call_tool(
    d3, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u', width=1.2, material='mat_concrete')
)
A.call_tool(
    d3,
    'add_curtain_wall',
    dict(walls='tower', storeys=[0, 2, 4, 6, 8, 10, 12, 14, 16, 18], mullion=1.5, transom=1.35, name='tower_glazing'),
)
for old_cell in ('FF96', 'FJ96'):
    lift_old = str(
        A.call_tool(
            d3,
            'add_elevator',
            dict(cell=old_cell, from_storey=0, to_storey=20, w=1.8, depth=2, material='mat_concrete'),
        )
    )
    check(
        'add_elevator(cell="%s") is refused: it is inside the FH96 stair' % old_cell,
        lift_old.startswith('refused') and 'u stair at FH96' in lift_old,
        lift_old[:220],
    )
    check(
        'and the refusal names the clear cells the replay now uses (%s)' % old_cell,
        'FD96' in lift_old and 'FK96' in lift_old,
        lift_old[:220],
    )
check(
    'neither refused lift left a shaft behind',
    not [o for o in d3.objs if o.get('kind') == 'elevator_shaft'],
    [o.get('id') for o in d3.objs if o.get('kind') == 'elevator_shaft'],
)

# the lobby the model actually drew: cell_to on row 109 IS the south facade line
lobby_old = str(
    A.call_tool(
        d3, 'add_room', dict(cell_from='FD107', cell_to='FM109', door_side='south', storey=0, name='Lobby', wall_h=5.4)
    )
)
check(
    'add_room with its door on the glazed facade is refused, not drawn',
    lobby_old.startswith('refused') and 'facade' in lobby_old,
    lobby_old[:260],
)
check(
    'and the refusal offers the sides that face the core',
    all(w in lobby_old for w in ('north', 'east', 'west')),
    lobby_old[:260],
)
lobby_in = str(
    A.call_tool(
        d3, 'add_room', dict(cell_from='FD107', cell_to='FM109', door_side='north', storey=0, name='Lobby', wall_h=5.4)
    )
)
check(
    'the same room with an inward door keeps the glass as its outer wall',
    'no south partition' in lobby_in and 'curtain wall' in lobby_in,
    lobby_in[:300],
)
check(
    'so it draws 3 partitions, not 4 — nothing doubles the facade',
    '3 partitions' in lobby_in and not [f for f in _errors(d3) if f.get('code') == 'env_facade_partition'],
    (lobby_in[:200], [f.get('text')[:140] for f in _errors(d3) if f.get('code') == 'env_facade_partition']),
)

summary = A.server_summary({'usage': {'turns': 28}, 'steps': 28}, d2)
check('server_summary says UNFINISHED', 'UNFINISHED' in summary, summary[:160])
check('server_summary carries a real error text', 'errors' in summary and 'requires' in summary, summary[:400])
print('  server_summary: %s' % summary[:300])

finish()
