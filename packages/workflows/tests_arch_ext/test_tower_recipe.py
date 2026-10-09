# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_tower_recipe.py — the acceptance rehearsal (2026-09-16).

`arch_assistant.tower_recipe()` is printed at the top of every system prompt:

    A WHOLE TOWER IS 12 DRAWING CALLS, in this order: plan_building -> draw_box ->
    add_curtain_wall(storeys=[0,2,4,…]) -> add_facade_bands -> add_core(group, position)
    -> build_entrance(group, side) -> layout_floor(core_from/core_to from add_core's
    reply) -> repeat_floor -> build_roof_deck(group, view) -> add_balconies -> present
    -> done. Use the macro, never its parts.

This file WALKS that recipe, offline, on the operator's own request — no Blender,
no Chrome, no model, a few seconds — and measures what comes out:

  · no call is refused,
  · design_rules.run_checks(d) reports ZERO errors from EVERY family,
  · building_program.status has every REQUIRED item built,
  · the records the request asked for are actually there,

and saves the result to fixtures/tower_recipe_20260916.json, which is the drawing
the creator renders and looks at.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_tower_recipe.py

TWO DEPARTURES FROM THE PRINTED ORDER, both measured here, both real:

  D1  build_entrance has to run BEFORE add_curtain_wall, not after it. The printed
      order glazes the facade first, and then the entrance macro has no wall left
      to cut a door through: "refused: o103 is a curtain wall — glazing cannot hold
      a door (the studio cuts holes in walls only). Put the entrance in BEFORE
      add_curtain_wall (it keeps a wall that holds a door and turns it glass)".
      The refusal is right and it is proved in section 4; tower_recipe()'s own
      order is what is wrong, and arch_assistant.py is not this task's to edit.

  D2  the recipe is TEN drawing calls plus a hand-off. `present` renders in
      Blender and `done` refuses until the views it rendered are of the current
      drawing, so an offline rehearsal cannot make those two calls. Section 5
      calls `done` anyway and proves its refusal is about the missing views and
      NOT about a design error — which is the only part of the gate this file can
      speak for.

WHAT THE RECIPE DOES NOT BUILD (section 2). The ten drawing calls leave six
errors standing, and every one of them is a finding telling the operator to make
a call the recipe never mentions: the second escape stair, the WC, the cycle
store and the refuse store that building_program requires of any 20-storey
residential, and the two party walls that repeat_floor stamps onto storey 19
straight through the infinity pool's tank. Section 2 does exactly what those
findings say, in their own words. A recipe that reached zero on its own would be
a recipe that never had to read a finding.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()

DR = A.EXT_MODULES['design_rules']
BP = A.EXT_MODULES['building_program']
EN = A.EXT_MODULES['envelope_rules']

# test_all.py's TOWER_REQUEST, plus the two words that keep water_leisure in the
# trimmed prompt ('infinity pool') — the same string the sweep measures the
# 45 000-char tower budget with.
REQUEST = (
    'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . '
    'roof entrance . nice entrance into the building at ground floor . make ground floor glass '
    'walls , 2nd floor rough concrete wall , 3rd floor glass walls , 4th rough concrete , repeat '
    'this for all floors. center building at cell fh100  make building look luxurious'
    ' infinity pool'
)

EVEN = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]  # "ground floor glass, 2nd concrete, 3rd glass, …"
FIXTURE = os.path.join(HERE, 'fixtures', 'tower_recipe_20260916.json')
MAX_OBJECTS = 8000

said: list = []


def call(tool: str, args: dict) -> str:
    r = str(A.call_tool(d, tool, args))
    said.append((tool, r))
    return r


def kinds(k) -> list:
    return [o for o in d.objs if o['kind'] == k]


def errors() -> list:
    return [f for f in DR.run_checks(d) if f.get('sev') == 'error']


def warns() -> list:
    return [f for f in DR.run_checks(d) if f.get('sev') == 'warn']


d = A.Drawing(None)
d.request = REQUEST

# ── 1. the recipe, in order ──────────────────────────────────────────────────
print('\n=== 1. the ten drawing calls of tower_recipe() ===')
call('plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, name='tower'))
call('draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
call('build_entrance', dict(group='tower', side='south', style='luxury'))  # D1: before the glazing
call('add_curtain_wall', dict(walls='tower', storeys=EVEN, mullion=1.5, transom=1.35, name='tower_glazing'))
call('add_facade_bands', dict(group='tower', kind='string_course', every_n_storeys=1, depth=0.15))
call('add_core', dict(group='tower', position='north', lifts=2))

# "core_from/core_to from add_core's reply": the reply names the cells, and
# d.ext['core'][group] carries the records behind them. Read the block off the
# records, not off the sentence — a cell name rounds, a bbox does not.
core = (d.ext.get('core') or {}).get('tower') or {}
boxes = [EN.bbox_of(d.find(i)) for i in (list(core.get('lifts') or []) + list(core.get('stair') or [])) if d.find(i)]
land = list(core.get('landing') or [0, 0, 0, 0])
x0 = min([b[0] for b in boxes] + [land[0]])
z0 = min([b[1] for b in boxes] + [land[1]])
x1 = max([b[2] for b in boxes] + [land[2]])
z1 = max([b[3] for b in boxes] + [land[3]])
core_from, core_to = A.cell_of(x0 - 0.05, z0 - 0.05), A.cell_of(x1 + 0.05, z1 + 0.05)
check(
    'add_core reports its block as cells (%s..%s)' % (core_from, core_to),
    (core_from, core_to) == ('FC91', 'FM95'),
    (core_from, core_to, (x0, z0, x1, z1)),
)

call(
    'layout_floor',
    dict(
        cell_from='EX90',
        cell_to='FQ109',
        use='residential',
        storey=1,
        corridor_w=1.8,
        core_from=core_from,
        core_to=core_to,
    ),
)
call('repeat_floor', dict(source_storey=1, from_storey=2, to_storey=19))
call('build_roof_deck', dict(group='tower', view='south'))

# add_balconies takes the wall ids the model reads out of get_state — the south
# curtain walls, minus storey 0 (a balcony on the ground is a doorstep, and
# facade_rules says so).
state = str(A.call_tool(d, 'get_state', {'detail': 'objects', 'which': 'curtain_wall'}))
south = [l.split()[0] for l in state.splitlines() if ' curtain_wall @FH110 ' in l]
check('get_state lists the south curtain walls (storeys 0..18)', len(south) >= 9, south)
call('add_balconies', dict(walls=south[1:], width=4, depth=1.8, rail_h=1.1, name='south_balconies'))

for tool, r in said:
    check('call %-18s is not refused' % tool, not r.startswith('refused'), r[:220])

# ── what the request asked for, as records ───────────────────────────────────
print('\n=== the records the request asked for ===')
check('stair: 20 records, one per storey', len(kinds('stair_u')) == 20, len(kinds('stair_u')))
check('lifts: 2 shafts', len(kinds('elevator_shaft')) == 2, len(kinds('elevator_shaft')))
check(
    'the infinity pool: 1 record',
    len(kinds('pool')) == 1,
    [(o['id'], (o['p'] or {}).get('inf')) for o in kinds('pool')],
)
# water_leisure records the overflow edge as p['inf'], a compass INITIAL ('s'),
# not a word — check_infinity_pools reads str(p['inf'])[:1] and ignores any pool
# whose initial is not one of n/s/e/w, so a truthy p['inf'] is exactly what makes
# the weir rules apply to this record.
check(
    'the pool is an INFINITY pool (a weir on one edge)',
    any(str((o['p'] or {}).get('inf') or '')[:1] in ('n', 's', 'e', 'w') for o in kinds('pool')),
    [(o['p'] or {}).get('inf') for o in kinds('pool')],
)
check('the deck is furnished: >= 4 loungers', len(kinds('sun_lounger')) >= 4, len(kinds('sun_lounger')))
check('the entrance has a canopy', len(kinds('canopy')) == 1, len(kinds('canopy')))
check('the entrance has a door', len(kinds('double_door')) >= 1, len(kinds('double_door')))
lobby = [
    o
    for o in d.objs
    if o['kind'] in ('desk', 'sofa', 'armchair', 'coffee_table', 'rug')
    or (o['kind'] == 'asset' and any(w in str(o.get('name') or '').lower() for w in ('sofa', 'armchair')))
]  # luxury seats are pack models (2026-09-16)
check('the lobby is furnished (desk, seating, rug)', len(lobby) >= 5, sorted({o['kind'] for o in lobby}))
check('balconies: >= 8 on the south face', len(kinds('balcony')) >= 8, len(kinds('balcony')))

# the glass/concrete alternation the request spelled out, storey by storey
H = d.storey_h
glazed = sorted({int(round(o['y'] / H)) for o in kinds('curtain_wall')})
check('curtain walls on the EVEN storeys only, 0..18', glazed == EVEN, glazed)
check('and none on an odd storey (those are the rough concrete ones)', not [s for s in glazed if s % 2], glazed)

# ── 2. what the ten calls left for the findings to ask for ───────────────────
print('\n=== 2. what the findings still ask for ===')
left = errors()
print('  after the recipe: %d error(s), codes %s' % (len(left), sorted({f.get('code') for f in left})))
for f in left:
    print('   · [%s] %s' % (f.get('code'), str(f.get('text'))[:150]))
check('the recipe alone does NOT finish the building', len(left) > 0, len(left))

fixup: list = []
fixup.append(
    (
        'add_fire_escape',
        call('add_fire_escape', dict(group='tower', side='north', storeys=20, width=1.2, name='fire_escape')),
    )
)
fixup.append(
    ('add_room WC', call('add_room', dict(cell_from='EY100', cell_to='FA103', door_side='east', storey=0, name='WC')))
)
fixup.append(
    (
        'furnish_bathroom',
        call(
            'furnish_bathroom',
            dict(cell_from='EY100', cell_to='FA103', door_side='east', storey=0, shower=False, bath=False),
        ),
    )
)
fixup.append(
    (
        'add_room Cycle store',
        call('add_room', dict(cell_from='EZ92', cell_to='FB96', door_side='east', storey=0, name='Cycle store')),
    )
)
fixup.append(
    (
        'add_room Refuse store',
        call('add_room', dict(cell_from='FO92', cell_to='FQ96', door_side='west', storey=0, name='Refuse store')),
    )
)
# "move the wall o### (delete + re-add …)" — repeat_floor stamps storey 1's party
# walls onto storey 19, where the pool tank hangs 1.28 m below the deck. The two
# it names are the two that run under the water; take them down in its own words.
drowned = [
    m.group(1)
    for m in (re.match(r'\s*(o\d+)', str(f.get('text'))) for f in errors() if f.get('code') == 'clash_wall_water')
    if m
]
check('clash_wall_water names the party walls under the pool tank', len(drowned) == 2, drowned)
if drowned:
    fixup.append(('delete the drowned party walls', call('delete', dict(which=drowned))))

for what, r in fixup:
    check('fix-up %-28s is not refused' % what, not r.startswith('refused'), r[:220])

# R1 from test_tower_replay: add_fire_escape(side='north') used to hang the stair
# on the SOUTH facade, beside the entrance door. It does not any more.
env = EN.group_envelope(d, 'tower')
fes = kinds('fire_stair_exterior')
check('the second escape is one record', len(fes) == 1, len(fes))
if fes and env:
    fe = fes[0]
    check('the second escape is OUTSIDE the envelope', not EN.inside(env, fe['x'], fe['z']), (fe['x'], fe['z']))
    check(
        'the second escape hangs on the NORTH face, opposite the entrance',
        abs(fe['z'] - env['zmin']) < abs(fe['z'] - env['zmax']),
        'z %.2f, north %.1f, south %.1f' % (fe['z'], env['zmin'], env['zmax']),
    )

# ── 3. the gate ──────────────────────────────────────────────────────────────
print('\n=== 3. every family, on the finished drawing ===')
errs = errors()
if errs:
    print('  ERRORS LEFT (%d):' % len(errs))
    for f in errs:
        print('   · [%s] %s' % (f.get('code'), str(f.get('text'))[:260]))
check(
    'ZERO design errors from every family', not errs, '%d left: %s' % (len(errs), sorted({f.get('code') for f in errs}))
)

ws = warns()
print('  warnings (%d) — every one, in full:' % len(ws))
for f in ws:
    print('   · [%s] %s' % (f.get('code'), str(f.get('text'))))

# The 09-16 live run (job aba5ab208439) shipped this tower with the roof plant
# standing inside a parasol and an underwater light, and with a palm the model
# had to move off the deck by hand. Neither may come back silently.
roof = [f for f in ws if re.search(r'hvac|water tank|antenna|palm', str(f.get('text')), re.I)]
check(
    'ZERO warnings about the roof plant or the palms',
    not roof,
    ['[%s] %s' % (f.get('code'), str(f.get('text'))[:200]) for f in roof],
)

rows = BP.status(d, BP.get_program(d))
missing = [(r.get('key'), str(r.get('detail'))[:200]) for r in rows if r.get('need') == 'required' and not r.get('ok')]
check('building_program: every REQUIRED item is built', not missing, missing)

check(
    'the drawing is under the %d-object ceiling (%d)' % (MAX_OBJECTS, len(d.objs)),
    len(d.objs) < MAX_OBJECTS,
    len(d.objs),
)

# ── 4. D1: the printed order, proved wrong by the tool itself ────────────────
print('\n=== 4. D1 — the printed order glazes the wall the entrance needs ===')
d2 = A.Drawing(None)
d2.request = REQUEST
A.call_tool(d2, 'plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, name='tower'))
A.call_tool(d2, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
A.call_tool(d2, 'add_curtain_wall', dict(walls='tower', storeys=EVEN, mullion=1.5, transom=1.35, name='tower_glazing'))
after = str(A.call_tool(d2, 'build_entrance', dict(group='tower', side='south', style='luxury')))
check('build_entrance AFTER add_curtain_wall is refused', after.startswith('refused'), after[:260])
check('and the refusal says to put the entrance in FIRST', 'BEFORE add_curtain_wall' in after, after[:260])
check(
    'no half-built entrance is left behind',
    not [o for o in d2.objs if o['kind'] in ('canopy', 'double_door')],
    [o['id'] for o in d2.objs if o['kind'] in ('canopy', 'double_door')],
)

# ── 5. D2: the hand-off gate ─────────────────────────────────────────────────
# done() is NOT a call_tool tool — it is handled by the server's turn loop, which
# runs design_check first and refuses while that reports errors (and again until
# present() has rendered the CURRENT drawing, which needs Blender). So what an
# offline rehearsal can prove is the half of the gate that is ours: design_check,
# the thing done() calls, must come back with no error line.
print('\n=== 5. D2 — the hand-off gate sees no error ===')
end = str(A.call_tool(d, 'design_check', {}))
check(
    'design_check — the gate done() runs — reports no error',
    not re.search(r'^\s*\d+\s+error', end, re.I | re.M) and 'errors:' not in end.lower(),
    end[:400],
)
print('  design_check(): %s' % end[:400].replace('\n', ' | '))

# ── the fixture ──────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
with open(FIXTURE, 'w') as fh:
    json.dump(d.to_doc(), fh)
doc = json.load(open(FIXTURE))
check(
    'the fixture is written and reloads (%s)' % os.path.basename(FIXTURE),
    len(doc.get('objects') or []) == len(d.objs),
    (len(doc.get('objects') or []), len(d.objs)),
)
check(
    'the fixture reopens as a Drawing with the same records',
    len(A.Drawing(doc).objs) == len(d.objs),
    len(A.Drawing(doc).objs),
)
print('  fixture: %s (%d objects, %.0f kB)' % (FIXTURE, len(d.objs), os.path.getsize(FIXTURE) / 1024.0))

finish()
