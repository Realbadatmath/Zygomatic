# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_water_leisure.py — proof for the water_leisure family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_water_leisure.py

Three engines must agree: the assistant's tools produce the records claimed,
the tab builds every kind at the size its parameters name (basins reach BELOW
the ground plane, so the bbox minimum in Y is negative), and Blender builds a
mesh with faces for each of them. The decks section (2026-09-08) proves a pool
on a roof lands on the DECK, stands raised on it, and can have an infinity edge.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    assistant,
    kinds_of,
    browser_kinds,
    blender_kinds,
    rail_has,
    tool_names,
)  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
WL = A.EXT_MODULES['water_leisure']

NEW_KINDS = [
    'pool',
    'pond',
    'canal',
    'fountain',
    'playground_slide',
    'swing',
    'sandpit',
    'sports_court',
    'goal_posts',
    'tennis_net',
    'sun_lounger',
    'umbrella',
]
NEW_TOOLS = ['add_pool', 'add_pond', 'add_canal', 'add_fountain', 'add_sports_court', 'add_playground', 'add_beach_set']

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in NEW_TOOLS), [t for t in NEW_TOOLS if t not in names])

# a pool over an 8 x 4 cell block
txt, d = assistant('add_pool', {'cell_from': 'C4', 'cell_to': 'J7', 'depth': 1.5})
pool = d.objs[-1]
check(
    'pool: one record, 8 x 4 m, 1.5 m deep',
    kinds_of(d).get('pool') == 1 and pool['p']['w'] == 8 and pool['p']['d'] == 4 and pool['p']['depth'] == 1.5,
    (txt, pool['p']),
)
check('pool sits on the ground plane (the hole is in the parameters)', pool['y'] == 0.0, pool)

# a canal through three cells = two segments
txt, d = assistant('add_canal', {'cells': ['D10', 'H10', 'H14'], 'width': 6, 'depth': 1.5}, drawing=d)
canals = [o for o in d.objs if o['kind'] == 'canal']
check('canal through 3 cells -> 2 segments', kinds_of(d).get('canal') == 2 and len(canals) == 2, txt)
check(
    'canal segments are 4 m long and 6 m wide',
    all(abs(c['p']['len'] - 4.0) < 1e-6 and c['p']['w'] == 6 for c in canals),
    [c['p'] for c in canals],
)

# a football court over a 30 x 16 cell block: court + a goal at each end
txt, d = assistant('add_sports_court', {'cell_from': 'A20', 'cell_to': 'AD35', 'sport': 'football'}, drawing=d)
court = [o for o in d.objs if o['kind'] == 'sports_court']
goals = [o for o in d.objs if o['kind'] == 'goal_posts']
check(
    'football: one 30 x 16 court',
    len(court) == 1 and court[0]['p']['w'] == 30 and court[0]['p']['d'] == 16,
    (txt, court[0]['p'] if court else None),
)
check('football: two goals', len(goals) == 2, txt)
check(
    'goals stand at the two ends, 28 m apart',
    len(goals) == 2
    and abs(abs(goals[0]['x'] - goals[1]['x']) - 28.0) < 0.01
    and abs(goals[0]['z'] - goals[1]['z']) < 1e-6,
    [(g['x'], g['z']) for g in goals],
)

# tennis: a net across the middle
txt, d2 = assistant('add_sports_court', {'cell_from': 'A20', 'cell_to': 'X31', 'sport': 'tennis'})
k2 = kinds_of(d2)
net = [o for o in d2.objs if o['kind'] == 'tennis_net']
check(
    'tennis: a court and one net across the middle',
    k2.get('sports_court') == 1 and k2.get('tennis_net') == 1 and not k2.get('goal_posts'),
    (txt, k2),
)
c2 = [o for o in d2.objs if o['kind'] == 'sports_court']
check(
    'the net sits at the court centre, turned across the long axis',
    len(net) == 1
    and len(c2) == 1
    and abs(net[0]['x'] - c2[0]['x']) < 1e-6
    and abs(net[0]['z'] - c2[0]['z']) < 1e-6
    and abs(net[0]['ry'] - 1.570796) < 1e-4,
    (net, c2),
)
txt, d2 = assistant('add_sports_court', {'cell_from': 'A20', 'cell_to': 'X31', 'sport': 'curling'}, drawing=d2)
check('unknown sport refused', txt.startswith('refused'), txt)

# a playground on an 8 x 8 block: three kinds, all inside the block
from zyg_workflows.arch_assistant import block_bounds  # noqa: E402

txt, d3 = assistant('add_playground', {'cell_from': 'B2', 'cell_to': 'I9'})
k3 = kinds_of(d3)
xmin, zmin, xmax, zmax = block_bounds('B2', 'I9')
check(
    'playground: slide + swing + sandpit',
    k3.get('playground_slide') == 1 and k3.get('swing') == 1 and k3.get('sandpit') == 1,
    (txt, k3),
)
check(
    '...all three inside the block',
    all(xmin <= o['x'] <= xmax and zmin <= o['z'] <= zmax for o in d3.objs),
    [(o['kind'], o['x'], o['z']) for o in d3.objs] + [(xmin, zmin, xmax, zmax)],
)
txt, d3 = assistant('add_playground', {'cell_from': 'B2', 'cell_to': 'E5'}, drawing=d3)
check('playground under 6x6 cells refused', txt.startswith('refused'), txt)

# pond, fountain, beach set
txt, d4 = assistant('add_pond', {'centre': 'K20', 'radius': 4, 'radius_z': 3})
pond = d4.objs[-1]
check(
    'pond rx 4 rz 3', kinds_of(d4).get('pond') == 1 and pond['p']['rx'] == 4 and pond['p']['rz'] == 3, (txt, pond['p'])
)
txt, d4 = assistant('add_pond', {'centre': 'K20', 'radius': 0.1}, drawing=d4)
check('silly pond radius refused', txt.startswith('refused'), txt)
txt, d4 = assistant('add_fountain', {'centre': 'E5', 'radius': 2, 'tiers': 3}, drawing=d4)
check(
    'fountain: one record, 3 tiers',
    kinds_of(d4).get('fountain') == 1 and d4.objs[-1]['p']['tiers'] == 3,
    (txt, d4.objs[-1]['p']),
)
txt, d4 = assistant('add_beach_set', {'cells': ['A1', 'A2', 'A3']}, drawing=d4)
k4 = kinds_of(d4)
check('beach set: a lounger and a parasol per cell', k4.get('sun_lounger') == 3 and k4.get('umbrella') == 3, (txt, k4))
txt, d4 = assistant('add_beach_set', {'cells': []}, drawing=d4)
check('empty beach set refused', txt.startswith('refused'), txt)

txt, d4 = assistant('add_object', {'kind': 'umbrella', 'cell': 'B7', 'params': {'r': 2.2}}, drawing=d4)
check('add_object knows the new kinds', d4.objs[-1]['kind'] == 'umbrella' and d4.objs[-1]['p']['r'] == 2.2, txt)
check('rail lists all twelve kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))

# ── the ground (2026-09-07) ───────────────────────────────────────────────────
# Everything below is measured against ONE slope drawn with the terrain family's
# own tool: A1..T100, 10 m of rise over 100 m along z — a 10 % grade. Level water
# may lie on it only where its footprint stays within 0.5 m; a court needs 3 %.
print('ground')
from zyg_workflows.arch_assistant import cell_centre, ground_height, parse_cell  # noqa: E402
from zyg_workflows.arch_assistant_ext.water_leisure import CANAL_LEVEL_MSG, COURT_SLOPE, LEVEL_TOL  # noqa: E402

txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T100', 'height': 10, 'direction': 'z'})
JX, JZ = cell_centre(*parse_cell('J50'))
G = ground_height(g, JX, JZ)
check('the test slope is 10 m over 100 m: J50 stands at 4.95 m', abs(G - 4.95) < 1e-6, (txt, G))
check(
    'the family declares the tolerances it refuses on',
    abs(LEVEL_TOL - 0.5) < 1e-9 and abs(COURT_SLOPE - 0.03) < 1e-9,
    (LEVEL_TOL, COURT_SLOPE),
)

# R3 — a small pond half-way up the slope lies at the ground, NOT at 0
txt, gp = assistant('add_pond', {'centre': 'J50', 'radius': 2}, drawing=g)
p_ok = gp.objs[-1]
check(
    'R3: a 2 m pond on the slope is accepted and its water is the ground (4.95 m, not 0)',
    p_ok['kind'] == 'pond' and abs(p_ok['y'] - G) < 1e-4 and p_ok['y'] != 0.0,
    (txt, p_ok['y']),
)
check('...and the reply names the water level', ('%g' % round(G, 4)) in txt, txt)

# R3 — a 40 m pond across the same slope cannot: 4 m of rise under it
n_before = len(gp.objs)
txt = assistant('add_pond', {'centre': 'J50', 'radius': 20}, drawing=gp)[0]
check(
    'R3: a 20 m-radius pond across the slope is refused (water lies level)',
    txt.startswith('refused') and 'water lies level' in txt and 'add_stream' in txt,
    txt,
)
check('...and nothing was drawn', len(gp.objs) == n_before, len(gp.objs))

# R3 — a canal ALONG the contour is level water; one running down the slope is not
txt, gc = assistant('add_canal', {'cells': ['E50', 'P50'], 'width': 6, 'depth': 1.5}, drawing=g)
reach = [o for o in gc.objs if o['kind'] == 'canal']
check(
    'R3: an east-west reach follows the contour, so it is accepted at 4.95 m',
    len(reach) == 1 and abs(reach[0]['y'] - G) < 1e-4,
    (txt, [r['y'] for r in reach]),
)
n_before = len(gc.objs)
txt = assistant('add_canal', {'cells': ['J40', 'J60'], 'width': 6, 'depth': 1.5}, drawing=gc)[0]
check(
    'R3: a reach running down the slope is refused with the canal message',
    txt.startswith('refused') and CANAL_LEVEL_MSG in txt,
    txt,
)
txt = assistant('add_canal', {'cells': ['E50', 'P50', 'P60'], 'width': 6, 'depth': 1.5}, drawing=gc)[0]
check(
    'R3: a bend whose SECOND reach falls is refused whole — no half a canal',
    txt.startswith('refused') and 'reach 2' in txt and len(gc.objs) == n_before,
    (txt, len(gc.objs)),
)

# R2/R5 — a court needs level ground
txt = assistant('add_sports_court', {'cell_from': 'C40', 'cell_to': 'R55', 'sport': 'basketball'}, drawing=g)[0]
check('R2: a court on a 10 % slope is refused', txt.startswith('refused') and 'a court needs level ground' in txt, txt)
txt, gs = assistant('add_sports_court', {'cell_from': 'C140', 'cell_to': 'R155', 'sport': 'basketball'}, drawing=g)
crt = [o for o in gs.objs if o['kind'] == 'sports_court']
check(
    'R2: the same court on flat ground beyond the slope is accepted at 0 m',
    len(crt) == 1 and crt[0]['y'] == 0.0,
    (txt, crt),
)

# R5 per piece — a playground and a beach set drape, each piece on its own ground
txt, gy = assistant('add_playground', {'cell_from': 'C40', 'cell_to': 'J47'}, drawing=g)
ys = sorted(round(o['y'], 3) for o in gy.objs if o['kind'] in ('playground_slide', 'swing', 'sandpit'))
check(
    'R5: the slide, the swing and the sandpit each sit on the ground under themselves '
    '(two rows of kit, so two heights over the 0.5 m the block climbs)',
    len(ys) == 3 and len(set(ys)) == 2 and all(3.5 < y < 5.5 for y in ys) and abs((max(ys) - min(ys)) - 0.48) < 0.05,
    (txt, ys),
)
check(
    '...each within 1 mm of ground_height at its own point',
    all(
        abs(o['y'] - ground_height(g, o['x'], o['z'])) < 1e-3
        for o in gy.objs
        if o['kind'] in ('playground_slide', 'swing', 'sandpit')
    ),
    [(o['kind'], o['y'], ground_height(g, o['x'], o['z'])) for o in gy.objs if o['kind'] != 'slope'],
)
txt, gb = assistant('add_beach_set', {'cells': ['E45', 'E46', 'E47']}, drawing=g)
pieces = [o for o in gb.objs if o['kind'] in ('sun_lounger', 'umbrella')]
check(
    'R5: every lounger and parasol lands on the ground under itself',
    len(pieces) == 6 and all(abs(o['y'] - ground_height(g, o['x'], o['z'])) < 1e-3 for o in pieces),
    [(o['kind'], o['y']) for o in pieces],
)
check(
    '...and they step up the slope (a real spread, not one flat height)',
    len({round(o['y'], 2) for o in pieces}) > 1,
    sorted({round(o['y'], 2) for o in pieces}),
)

# R1 — base_height is the operator overruling the ground, refusals included
txt, gh = assistant('add_pond', {'centre': 'J50', 'radius': 20, 'base_height': 12}, drawing=g)
check(
    'R1: an explicit base_height overrides the ground AND the level refusal',
    gh.objs[-1]['kind'] == 'pond' and gh.objs[-1]['y'] == 12.0,
    (txt, gh.objs[-1]['y']),
)
txt, gh = assistant('add_pool', {'cell_from': 'C4', 'cell_to': 'J7', 'depth': 1.5, 'base_height': 0}, drawing=g)
check('R1: base_height 0 is a number, not "unset"', gh.objs[-1]['y'] == 0.0, (txt, gh.objs[-1]['y']))
check(
    'R3: a pool 4 m down the slope (0.4 m of rise) still lies level and is accepted',
    not assistant('add_pool', {'cell_from': 'C40', 'cell_to': 'J43', 'depth': 1.5}, drawing=g)[0].startswith('refused'),
)
check(
    'R3: a pool 10 m down the slope (1.0 m of rise) is refused without a base_height',
    assistant('add_pool', {'cell_from': 'C40', 'cell_to': 'J49', 'depth': 1.5}, drawing=g)[0].startswith('refused'),
)
txt, gf = assistant('add_fountain', {'centre': 'J50', 'radius': 2, 'tiers': 3}, drawing=g)
check(
    'R5: a 4 m fountain fits inside the tolerance and stands on the ground',
    gf.objs[-1]['kind'] == 'fountain' and abs(gf.objs[-1]['y'] - G) < 1e-4,
    (txt, gf.objs[-1]['y']),
)

# ── decks (2026-09-08, design rules) ─────────────────────────────────────────
# The measured defect: a pool told base_height=54 on a 20-storey tower whose flat
# roof is at 54 with t=0.3 landed INSIDE the roof — water at 53.9, coping
# coplanar with the deck, basin hanging into the top storey: "no pool". Here a
# 3-storey box C4..L13 with a flat roof puts the roof record at 8.1 and its DECK
# at 8.4; every pool below must land on 8.4, standing on it, water above it.
print('decks')

txt, dk = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
roof = [o for o in dk.objs if o['kind'] == 'roof_flat']
check(
    'the test box has a flat roof at 8.1 with t 0.3 (deck 8.4)',
    len(roof) == 1 and abs(roof[0]['y'] - 8.1) < 1e-6 and abs(roof[0]['p']['t'] - 0.3) < 1e-6,
    (txt, roof),
)
n0 = len(dk.objs)

# (a) an explicit base INSIDE the roof is lifted to the deck, and the pool stands on it
txt, dk = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5, 'base_height': 8.1}, drawing=dk)
pa = dk.objs[-1]
check(
    '(a) base_height 8.1 (inside the roof) -> y == 8.4, the deck',
    pa['kind'] == 'pool' and abs(pa['y'] - 8.4) < 1e-6,
    (txt, pa['y']),
)
check(
    '(a) on a deck the pool is raised by its depth (walls exposed)', abs(pa['p'].get('raised', 0) - 1.5) < 1e-6, pa['p']
)
check(
    '(a) the water level (y + raised - 0.1) is ABOVE the deck',
    pa['y'] + pa['p']['raised'] - 0.1 > 8.4,
    (pa['y'], pa['p']),
)
check('(a) the reply reports the lift and the deck height', 'lifted' in txt and '8.4 m' in txt, txt)

# (b) no base_height: a deck above the ground wins over the ground under the building
txt, dk = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5}, drawing=dk)
pb = dk.objs[-1]
check(
    '(b) no base_height -> lands on the deck at 8.4, not on the ground at 0',
    pb['kind'] == 'pool' and abs(pb['y'] - 8.4) < 1e-6,
    (txt, pb['y']),
)
check(
    '(b) ...raised 1.5 and the reply says "deck at 8.4 m"',
    abs(pb['p']['raised'] - 1.5) < 1e-6 and 'deck at 8.4 m' in txt,
    (txt, pb['p']),
)

# (c) infinity south: the pool's south edge must be the deck edge (row 13's far side, z of zmax)
xmin_d, zmin_d, xmax_d, zmax_d = block_bounds('C4', 'L13')
txt, dk = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H12', 'depth': 1.5, 'infinity': 'south'}, drawing=dk)
pc = dk.objs[-1]
south_edge = pc['z'] + pc['p']['d'] / 2
check(
    '(c) infinity south with cell_to row 12 (1 m short) -> accepted, p.inf == "s"',
    pc['kind'] == 'pool' and pc['p'].get('inf') == 's',
    (txt, pc['p']),
)
check(
    '(c) ...the south edge MOVED to the deck edge minus INF_INSET (0.6 m since 2026-09-11: the 0.5 m trough stays inside the facade)',
    abs(south_edge - (zmax_d - WL.INF_INSET)) < 1e-3 and WL.INF_INSET >= 0.55,
    (south_edge, zmax_d, WL.INF_INSET),
)
check('(c) ...and the reply says so', 'moved' in txt and 'deck edge' in txt, txt)
n1 = len(dk.objs)
txt = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5, 'infinity': 'south'}, drawing=dk)[0]
check(
    '(c) infinity south with cell_to row 9 (4 m short) -> refused, naming row 13',
    txt.startswith('refused') and 'cell_to must be row 13' in txt and len(dk.objs) == n1,
    txt,
)
txt = assistant('add_pool', {'cell_from': 'E5', 'cell_to': 'H9', 'depth': 1.5, 'infinity': 'west'}, drawing=dk)[0]
check(
    '(c) infinity west 2 m off the west edge -> refused, naming column C',
    txt.startswith('refused') and 'cell_from must be column C' in txt,
    txt,
)
txt = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5, 'infinity': 'up'}, drawing=dk)[0]
check('(c) a nonsense infinity side is refused', txt.startswith('refused'), txt)

# sunk: on a deck raised < depth is clamped unless sunk=true
txt, dk = assistant('add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5, 'raised': 0.5}, drawing=dk)
ps = dk.objs[-1]
check(
    'raised 0.5 on a deck without sunk -> clamped to 1.5 with a note',
    abs(ps['p']['raised'] - 1.5) < 1e-6 and 'clamped' in txt and 'sunk=true' in txt,
    (txt, ps['p']),
)
txt, dk = assistant(
    'add_pool', {'cell_from': 'D5', 'cell_to': 'H9', 'depth': 1.5, 'raised': 0.5, 'sunk': True}, drawing=dk
)
ps = dk.objs[-1]
check(
    'raised 0.5 with sunk=true -> kept (a plant storey), water still above the deck',
    abs(ps['p']['raised'] - 0.5) < 1e-6 and ps['y'] + 0.5 - 0.1 > 8.4,
    (txt, ps['p']),
)

# (d) a parapet on the box: the south parapet wall becomes a glass balustrade
txt, dp = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
txt, dp = assistant('add_parapet', {'group': 'blk', 'height': 1.2, 'thickness': 0.25, 'cap': True}, drawing=dp)
paras = [o for o in dp.objs if o['kind'] == 'wall' and 'parapet' in o['name']]
check(
    '(d) add_parapet put 4 brick parapet walls on the box',
    len(paras) == 4 and all(o['mat'] != 'mat_glass' for o in paras),
    (txt, [(o['id'], o['mat']) for o in paras]),
)
txt, dp = assistant(
    'add_pool', {'cell_from': 'D5', 'cell_to': 'H13', 'depth': 1.5, 'coping': 0.3, 'infinity': 'south'}, drawing=dp
)
south = [o for o in paras if abs(o['ry']) < 1e-6 and abs(o['z'] - zmax_d) < 0.3]
others = [o for o in paras if o not in south]
check(
    '(d) infinity south -> the SOUTH parapet wall is mat_glass',
    len(south) == 1 and south[0]['mat'] == 'mat_glass',
    (txt, [(o['id'], o['mat'], o['z']) for o in paras]),
)
check(
    '(d) ...and the other three parapets are untouched',
    len(others) == 3 and all(o['mat'] != 'mat_glass' for o in others),
    [(o['id'], o['mat']) for o in others],
)
check('(d) the reply names the glass balustrade', 'glass balustrade' in txt and south[0]['id'] in txt, txt)

# (e) a garden pool is exactly what it was
txt, de = assistant('add_pool', {'cell_from': 'C4', 'cell_to': 'J7', 'depth': 1.5})
pe = de.objs[-1]
check(
    '(e) ground pool unchanged: y == 0, raised 0 (or absent), no inf key',
    pe['y'] == 0.0 and not pe['p'].get('raised') and 'inf' not in pe['p'],
    pe,
)
check(
    '(e) a pool hanging over the roof edge is refused',
    assistant('add_pool', {'cell_from': 'H5', 'cell_to': 'N9', 'depth': 1.5}, drawing=dk)[0].startswith('refused'),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
CASES = [
    {'kind': 'pool', 'p': {'w': 8, 'd': 4, 'depth': 1.5, 'coping': 0.4}},
    {'kind': 'pond', 'p': {'rx': 4, 'rz': 3, 'depth': 0.6}},
    {'kind': 'canal', 'p': {'len': 20, 'w': 6, 'depth': 1.5}},
    {'kind': 'fountain', 'p': {'r': 2, 'tiers': 3, 'h': 2.5}},
    {'kind': 'playground_slide', 'p': {'h': 2, 'l': 4, 'w': 0.6}},
    {'kind': 'swing', 'p': {'w': 3, 'h': 2.4, 'seats': 2}},
    {'kind': 'sandpit', 'p': {'w': 4, 'd': 4, 't': 0.3}},
    {'kind': 'sports_court', 'p': {'w': 28, 'd': 15, 'lines': 1}},
    {'kind': 'goal_posts', 'p': {'w': 7.32, 'h': 2.44, 'd': 2}},
    {'kind': 'tennis_net', 'p': {'w': 12.8, 'h': 1.07}},
    {'kind': 'sun_lounger', 'p': {'l': 1.9, 'w': 0.7, 'h': 0.4}},
    {'kind': 'umbrella', 'p': {'r': 1.5, 'h': 2.3}},
]
b = browser_kinds(CASES)
B = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind builds real geometry',
    all(r['ok'] and r['registered'] for r in b),
    [(r['kind'], r['ok'], r['registered'], r.get('err')) for r in b if not (r['ok'] and r['registered'])],
)


def size_is(kind, sx, sy, sz, tol=0.06):
    r = B.get(kind) or {}
    s = r.get('size') or [0, 0, 0]
    return check(
        f'{kind} is {sx:g} x {sy:g} x {sz:g} m',
        abs(s[0] - sx) < tol and abs(s[1] - sy) < tol and abs(s[2] - sz) < tol,
        r,
    )


size_is('pool', 8, 1.9, 4)  # depth 1.5 + coping 0.4
check(
    'the pool digs: bbox floor 1.5 m under the ground plane',
    abs((B['pool']['min'][1]) + 1.5) < 0.02 and abs(B['pool']['min'][1] + B['pool']['size'][1] - 0.4) < 0.02,
    B['pool'],
)
size_is('pond', 8, 0.6, 6)  # rx 4, rz 3 -> 8 x .. x 6
check('the pond digs 0.6 m', abs(B['pond']['min'][1] + 0.6) < 0.02, B['pond'])
size_is('canal', 20, 1.6, 6)
check('the canal digs 1.5 m', abs(B['canal']['min'][1] + 1.5) < 0.02, B['canal'])
# the banks read in two bands: turf over the top 30 %, bed below, water between
check('the pond bank is banded: bed + turf + water = 3 parts', B['pond']['parts'] == 3, B['pond'])
check(
    'the canal has a quay and a turf cap on each side, a bed and water = 6 parts', B['canal']['parts'] == 6, B['canal']
)
size_is('fountain', 4, 2.5, 4)
size_is('playground_slide', 4, 2, 0.6)
size_is('swing', 3, 2.4, 0.35)
size_is('sandpit', 4, 0.55, 4)  # sand t 0.3 down, kerb 0.25 up
b_court = B['sports_court']
check(
    'sports_court is 28 x 15 m and paper-thin',
    abs(b_court['size'][0] - 28) < 0.06 and abs(b_court['size'][2] - 15) < 0.06 and b_court['size'][1] < 0.2,
    b_court,
)
check('sports_court has painted lines (6 parts)', b_court['parts'] >= 6, b_court)
size_is('goal_posts', 7.32, 2.44, 2)
size_is('tennis_net', 12.8, 1.07, 0.1)
size_is('sun_lounger', 1.9, 0.4, 0.7)
size_is('umbrella', 3, 2.3, 3)
check(
    'labels read well',
    B['pool']['label'] == 'Swimming pool'
    and B['goal_posts']['label'] == 'Goal posts'
    and B['umbrella']['label'] == 'Parasol',
    [B[k]['label'] for k in ('pool', 'goal_posts', 'umbrella')],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(CASES)
for kind in NEW_KINDS:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))

# the two engines must draw the SAME banked banks: the bands changed the
# materials, not the shape, so the bounding boxes still agree with the tab's
for kind in ('pond', 'canal'):
    bs, ts = (bl.get(kind) or {}).get('size'), B[kind]['size']
    check(
        f'blender {kind} has the same bounding box as the tab',
        bs is not None and all(abs(bs[i] - ts[i]) < 0.06 for i in range(3)),
        (bs, ts),
    )
check(
    'blender digs the pond 0.6 m and the canal 1.5 m, as the tab does',
    abs((bl['pond'].get('min_y') or 0) + 0.6) < 0.02 and abs((bl['canal'].get('min_y') or 0) + 1.5) < 0.02,
    (bl['pond'].get('min_y'), bl['canal'].get('min_y')),
)

# (f) the raised infinity pool: floor ON the deck (min y 0), rim at raised + coping,
# a glass weir instead of the south wall and a trough outside it — in both engines
print('raised infinity pool')
INF = [{'kind': 'pool', 'p': {'w': 8, 'd': 4, 'depth': 1.5, 'coping': 0.3, 'raised': 1.5, 'inf': 's'}}]
bi = browser_kinds(INF)[0]
check('(f) tab builds the raised infinity pool', bi['ok'] and bi['registered'] and not bi.get('page_errors'), bi)
check(
    '(f) tab: bbox min y >= -0.01 (nothing under the deck) and max y ~ 1.8 (raised 1.5 + coping 0.3)',
    bi['min'][1] >= -0.01 and abs(bi['min'][1] + bi['size'][1] - 1.8) < 0.02,
    bi,
)
check('(f) tab: 7 parts — floor, 3 walls, the weir, water, the trough', bi['parts'] == 7, bi)
check(
    '(f) tab: the trough reaches 0.5 m outside the south wall (depth 4.5 m)',
    abs(bi['size'][2] - 4.5) < 0.02 and abs(bi['min'][2] + 2.0) < 0.02,
    bi,
)
bli = blender_kinds(INF).get('pool') or {}
check('(f) blender builds it with faces', bli.get('polys', 0) > 0, bli)
check(
    '(f) blender agrees with the tab: same bbox and the same floor height',
    bli.get('size') is not None
    and all(abs(bli['size'][i] - bi['size'][i]) < 0.06 for i in range(3))
    and abs((bli.get('min_y') or 0) - bi['min'][1]) < 0.02,
    (bli, bi),
)
# the ground pool must be byte-for-byte what it was: 6 parts, floor at -1.5
check(
    '(e) the tab still draws the plain pool with 6 parts and its floor 1.5 m down',
    B['pool']['parts'] == 6 and abs(B['pool']['min'][1] + 1.5) < 0.02,
    B['pool'],
)

# ── (g) the rooftop infinity pool as one call (2026-09-12) ───────────────────
# The operator's five reference pictures: deck-level water, weir on the view side
# only, a glass guard OUTBOARD of the trough, steps on the deck side, loungers
# facing the view, a tank zone below. add_infinity_pool builds it; the design
# checks refuse the bare weir with no guard.
print('infinity pool ensemble')
import math  # noqa: E402

DR = A.EXT_MODULES['design_rules']


def codes(dd):
    return sorted(f['code'] for f in DR.run_checks(dd))


# a 20 x 20 deck (C4..V23, deck 8.4) with a 10 x 9.4 m pool at its south edge: 10 m of deck
# north of the pool for the lounger row, 6 m east of it for the lounge, 4 m west
xmin_g, zmin_g, xmax_g, zmax_g = block_bounds('C4', 'V23')
txt, di = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'V23', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
n0 = len(di.objs)
txt, di = assistant(
    'add_infinity_pool', {'cell_from': 'G14', 'cell_to': 'P23', 'view': 'south', 'storey': 3}, drawing=di
)
made = di.objs[n0:]
kinds = {}
for o in made:
    kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
pool = [o for o in made if o['kind'] == 'pool']
check(
    '(g) one pool on the 8.4 deck, deck-level: raised 0.12, sunk, weir south, steps north, blue tile',
    len(pool) == 1
    and abs(pool[0]['y'] - 8.4) < 1e-6
    and abs(pool[0]['p']['raised'] - WL.INF_RIM) < 1e-6
    and pool[0]['p'].get('sunk') is True
    and pool[0]['p'].get('inf') == 's'
    and pool[0]['p'].get('steps') == 'n'
    and pool[0]['mat'] == WL.INF_TILE,
    (txt[:300], pool[0]['p'] if pool else None),
)
check(
    '(g) the water is 0.02 m above the deck (deck-level), the basin hangs into the storey below',
    pool
    and abs(pool[0]['y'] + pool[0]['p']['raised'] - 0.1 - 8.42) < 1e-3
    and pool[0]['p']['depth'] > pool[0]['p']['raised'],
    pool[0]['p'] if pool else None,
)
guard = [o for o in made if o['kind'] == 'wall' and 'balustrade' in o['name']]
check(
    '(g) a glass balustrade 1.1 m runs along the whole south deck edge, outboard of the trough',
    len(guard) == 1
    and guard[0]['mat'] == 'mat_glass'
    and abs(guard[0]['p']['h'] - 1.1) < 1e-6
    and abs(guard[0]['p']['len'] - 20.0) < 1e-6
    and abs(guard[0]['z'] - (zmax_g - WL.GUARD_IN - WL.GUARD_T / 2)) < 1e-3
    and abs(guard[0]['y'] - 8.4) < 1e-6
    and abs(guard[0]['ry']) < 1e-6,
    [(o['id'], o['z'], o['p'], o['mat'], o['y']) for o in guard] + [zmax_g],
)
check(
    '(g) ...the guard stands OUTSIDE the trough: trough outer face is 0.1 m inside the deck edge, the glass 0.05',
    pool and (pool[0]['z'] + pool[0]['p']['d'] / 2 + 0.5) < guard[0]['z'] - WL.GUARD_T / 2 + 1e-6 if guard else False,
    (pool[0]['z'] + pool[0]['p']['d'] / 2 + 0.5 if pool else None, guard[0]['z'] if guard else None),
)
zone = [o for o in made if o['kind'] == 'zone']
check(
    '(g) a "pool tank + balance tank + plant" zone lies in the storey below, under the pool',
    len(zone) == 1
    and 'tank' in zone[0]['name']
    and 5.0 < zone[0]['y'] < 8.4 - 0.5
    and abs(zone[0]['x'] - pool[0]['x']) < 0.01,
    [(o['name'], o['y'], o['x']) for o in zone],
)
lg = [o for o in made if o['kind'] == 'sun_lounger']
check(
    '(g) loungers stand ON the deck north of the pool, in a row, all facing south (ry -pi/2)',
    len(lg) >= 3
    and all(abs(o['y'] - 8.4) < 1e-6 for o in lg)
    and all(abs(o['ry'] + math.pi / 2) < 1e-3 for o in lg)
    and all(o['z'] < pool[0]['z'] - pool[0]['p']['d'] / 2 - WL.LOUNGER_OFF for o in lg)
    and len({round(o['z'], 2) for o in lg}) == 1,
    [(o['x'], o['z'], o['y'], o['ry']) for o in lg],
)
check(
    '(g) parasols behind the loungers (further from the pool), palms at the ends, a lounge and 4 lights',
    kinds.get('umbrella', 0) >= 1
    and all(o['z'] < lg[0]['z'] for o in made if o['kind'] == 'umbrella')
    and kinds.get('tree_palm') == 2
    and kinds.get('sofa') == 1
    and kinds.get('armchair') == 2
    and kinds.get('cylinder') == 1
    and kinds.get('light_point') == 4,
    kinds,
)
check(
    '(g) every piece is on the deck (y 8.4) or the zone below; the lights are not inside the roof slab',
    all(abs(o['y'] - 8.4) < 1e-6 for o in made if o['kind'] not in ('zone', 'light_point'))
    and all(o['y'] > 8.4 for o in made if o['kind'] == 'light_point'),
    [(o['kind'], o['y']) for o in made if o['kind'] != 'zone' and abs(o['y'] - 8.4) > 1e-6],
)
check(
    "(g) the reply reports the guard, the tank, the steps, the loungers and what is still the model's",
    all(
        w in txt
        for w in (
            'glass balustrade',
            'pool tank + balance tank + plant',
            'entry steps on the north side',
            'loungers on the north side facing south',
            'still yours',
        )
    ),
    txt[:600],
)
txt_s, ds = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
txt_s, ds = assistant(
    'add_infinity_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'view': 'south', 'storey': 3}, drawing=ds
)
check(
    '(g) on a 10 x 10 deck the pool fills it: no loungers, no lounge, and the reply says "no deck room"',
    not [o for o in ds.objs if o['kind'] in ('sun_lounger', 'sofa', 'tree_palm')]
    and 'no deck room for loungers' in txt_s,
    txt_s[:400],
)
cs = codes(di)
check(
    '(g) design_check has NO infinity finding on the ensemble (guard, steps, tank, depth, width all satisfied)',
    not any(
        c in cs
        for c in (
            'inf_guard',
            'inf_guard_low',
            'inf_view',
            'inf_steps',
            'pool_entry',
            'pool_tank',
            'pool_depth',
            'pool_narrow',
            'pool_basin',
            'pool_water',
            'buried',
        )
    ),
    cs,
)

# the bare weir: add_pool(infinity=) alone on an unguarded roof is an ERROR, and it says so
txt, db = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
txt, db = assistant('add_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'infinity': 'south'}, drawing=db)
check('(g) add_pool with an infinity edge and no parapet says NO guard in its reply', 'NO guard' in txt, txt[-260:])
cb = codes(db)
check('(g) ...design_check: inf_guard ERROR + pool_entry WARN', 'inf_guard' in cb and 'pool_entry' in cb, cb)
errs = [f for f in DR.run_checks(db) if f['code'] == 'inf_guard']
check(
    '(g) ...the error names the fix (add_infinity_pool / add_parapet mat_glass) and the open length',
    errs
    and 'add_infinity_pool' in errs[0]['text']
    and 'mat_glass' in errs[0]['text']
    and '8.0 m of the weir' in errs[0]['text'],
    errs[0]['text'] if errs else None,
)
# a 1.0 m parapet there is too low; 1.1 m brick is a view problem (warn), not a safety one
txt, dl = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
txt, dl = assistant('add_parapet', {'group': 'blk', 'height': 1.0}, drawing=dl)
txt, dl = assistant(
    'add_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'infinity': 'south', 'steps': 'north'}, drawing=dl
)
cl = codes(dl)
check(
    '(g) a 1.0 m parapet on the weir side -> inf_guard_low ERROR, no inf_guard, no pool_entry (steps given)',
    'inf_guard_low' in cl and 'inf_guard' not in cl and 'pool_entry' not in cl,
    cl,
)
check('(g) ...and the reply names the treads', 'entry steps on the north side (4 treads' in txt, txt[-200:])
txt, dm = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
txt, dm = assistant('add_parapet', {'group': 'blk', 'height': 1.1}, drawing=dm)
txt, dm = assistant(
    'add_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'infinity': 'south', 'steps': 'north'}, drawing=dm
)
cm = codes(dm)
check(
    '(g) a 1.1 m parapet on the weir side is turned glass by add_pool: no guard finding at all',
    not any(c.startswith('inf_') for c in cm),
    cm,
)
for o in dm.objs:
    if o['kind'] == 'wall' and 'parapet' in o['name'] and o['mat'] == 'mat_glass':
        o['mat'] = 'mat_brick'
check(
    '(g) ...made solid again by hand -> inf_view WARN (a solid parapet hides the view)',
    'inf_view' in codes(dm) and not any(c in codes(dm) for c in ('inf_guard', 'inf_guard_low')),
    codes(dm),
)
# refusals
r = assistant(
    'add_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'infinity': 'south', 'steps': 'south'}, drawing=dm
)[0]
check(
    '(g) steps on the weir side are refused, naming the deck side', r.startswith('refused') and 'steps="north"' in r, r
)
r = assistant('add_infinity_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'view': 'up'}, drawing=dm)[0]
check('(g) a nonsense view is refused', r.startswith('refused'), r)
r = assistant('add_infinity_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'storey': 3, 'depth': 3.0}, drawing=dm)[0]
check('(g) a 3 m "swimming" depth is refused (1.0-2.0)', r.startswith('refused') and '1.0-2.0 m' in r, r)
# level="raised" keeps the old standing basin and registers no tank zone
txt, dr = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
n1 = len(dr.objs)
txt, dr = assistant(
    'add_infinity_pool',
    {
        'cell_from': 'D7',
        'cell_to': 'K13',
        'storey': 3,
        'view': 'south',
        'level': 'raised',
        'lounge': False,
        'lights': False,
    },
    drawing=dr,
)
pr = [o for o in dr.objs[n1:] if o['kind'] == 'pool']
check(
    '(g) level="raised": raised == depth, no sunk flag, no tank zone, no lounge, no lights',
    pr
    and abs(pr[0]['p']['raised'] - pr[0]['p']['depth']) < 1e-6
    and not pr[0]['p'].get('sunk')
    and not [o for o in dr.objs[n1:] if o['kind'] in ('zone', 'sofa', 'light_point')],
    (txt[:200], pr[0]['p'] if pr else None),
)
# the pool on the ground: no guard, no zone, still steps + weir
txt, dg = assistant('add_infinity_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'view': 'south'})
check(
    '(g) on the ground: weir + steps, no balustrade, no tank zone, the reply says so',
    dg.objs
    and dg.objs[0]['kind'] == 'pool'
    and dg.objs[0]['p'].get('inf') == 's'
    and dg.objs[0]['p'].get('steps') == 'n'
    and not [o for o in dg.objs if o['kind'] in ('zone', 'wall')]
    and 'on the ground' in txt,
    txt[:300],
)

# the two engines draw the treads: 4 boxes inside the basin, the bbox unchanged
print('pool steps in both engines')
STP = [{'kind': 'pool', 'p': {'w': 8, 'd': 4, 'depth': 1.5, 'coping': 0.3, 'raised': 1.5, 'inf': 's', 'steps': 'n'}}]
bs = browser_kinds(STP)[0]
check(
    '(g) tab: the raised infinity pool with north steps has 7 + 4 = 11 parts and the same bbox as (f)',
    bs['ok']
    and bs['parts'] == 11
    and abs(bs['size'][2] - 4.5) < 0.02
    and abs(bs['size'][0] - 8) < 0.02
    and bs['min'][1] >= -0.01
    and abs(bs['min'][1] + bs['size'][1] - 1.8) < 0.02,
    bs,
)
bls = blender_kinds(STP).get('pool') or {}
check(
    '(g) blender builds it with faces and agrees on the bbox',
    bls.get('polys', 0) > 0
    and bls.get('size') is not None
    and all(abs(bls['size'][i] - bs['size'][i]) < 0.06 for i in range(3)),
    (bls, bs),
)
check(
    '(g) steps on the weir side are ignored by the geometry (7 parts), as the tool refuses them',
    browser_kinds(
        [{'kind': 'pool', 'p': {'w': 8, 'd': 4, 'depth': 1.5, 'coping': 0.3, 'raised': 1.5, 'inf': 's', 'steps': 's'}}]
    )[0]['parts']
    == 7,
)
check(
    '(g) a spec sheet for the pool names add_infinity_pool and the guard, under the prose cap',
    'add_infinity_pool' in A.call_tool(di, 'spec', {'of': 'infinity pool'})
    and 'OUTBOARD' in A.call_tool(di, 'spec', {'of': 'infinity pool'}),
    A.call_tool(di, 'spec', {'of': 'infinity pool'})[:200],
)

finish()
