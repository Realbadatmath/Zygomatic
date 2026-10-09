# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_furniture_kitchen_bath.py — the proof for the kitchen,
bathroom and utility family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_furniture_kitchen_bath.py
"""

import math
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
from zyg_workflows.arch_assistant import block_bounds  # noqa: E402

KINDS = [
    'kitchen_counter',
    'kitchen_island',
    'wall_cabinet',
    'sink',
    'stove',
    'fridge',
    'dishwasher',
    'washing_machine',
    'toilet',
    'bathtub',
    'shower',
    'washbasin',
    'mirror',
    'towel_rail',
    'boiler',
]

# kind -> the (along local X, along local Z) footprint, and the expected browser
# bounding box (x, y, z) at the family's default parameters.
FOOT = {
    'kitchen_counter': lambda p: (p['len'], p['d']),
    'kitchen_island': lambda p: (p['w'], p['d']),
    'wall_cabinet': lambda p: (p['len'], p['d']),
    'sink': lambda p: (p['w'], p['d']),
    'stove': lambda p: (p['w'], p['d']),
    'fridge': lambda p: (p['w'], p['d']),
    'dishwasher': lambda p: (p['w'], p['d']),
    'washing_machine': lambda p: (p['w'], p['d']),
    'toilet': lambda p: (p['w'], p['d']),
    'bathtub': lambda p: (p['l'], p['w']),
    'shower': lambda p: (p['w'], p['d']),
    'washbasin': lambda p: (p['w'], p['d']),
    'mirror': lambda p: (p['w'], p['t']),
    'towel_rail': lambda p: (p['len'], 0.10),
    'boiler': lambda p: (2 * p['r'], 2 * p['r']),
}
SIZE = {
    'kitchen_counter': (2.0, 0.9, 0.6),
    'kitchen_island': (2.0, 0.9, 0.9),
    'wall_cabinet': (1.2, 0.7, 0.35),
    'sink': (0.6, 0.9, 0.5),
    'stove': (0.6, 0.9, 0.6),
    'fridge': (0.7, 1.8, 0.7),
    'dishwasher': (0.6, 0.85, 0.6),
    'washing_machine': (0.6, 0.85, 0.6),
    'toilet': (0.4, 0.8, 0.7),
    'bathtub': (1.7, 0.55, 0.75),
    'shower': (0.9, 2.0, 0.9),
    'washbasin': (0.6, 0.85, 0.45),
    'mirror': (0.6, 0.8, 0.02),
    'towel_rail': (0.6, 0.06, 0.10),
    'boiler': (0.6, 1.2, 0.6),
}
DEFAULTS = {
    'kitchen_counter': {'len': 2.0, 'd': 0.6, 'h': 0.9, 'top': 0.04},
    'kitchen_island': {'w': 2.0, 'd': 0.9, 'h': 0.9},
    'wall_cabinet': {'len': 1.2, 'd': 0.35, 'h': 0.7},
    'sink': {'w': 0.6, 'd': 0.5, 'h': 0.9},
    'stove': {'w': 0.6, 'd': 0.6, 'h': 0.9},
    'fridge': {'w': 0.7, 'd': 0.7, 'h': 1.8},
    'dishwasher': {'w': 0.6, 'd': 0.6, 'h': 0.85},
    'washing_machine': {'w': 0.6, 'd': 0.6, 'h': 0.85},
    'toilet': {'w': 0.4, 'd': 0.7, 'h': 0.8},
    'bathtub': {'w': 0.75, 'l': 1.7, 'h': 0.55},
    'shower': {'w': 0.9, 'd': 0.9, 'h': 2.0, 'tray': 0.05},
    'washbasin': {'w': 0.6, 'd': 0.45, 'h': 0.85},
    'mirror': {'w': 0.6, 'h': 0.8, 't': 0.02},
    'towel_rail': {'len': 0.6},
    'boiler': {'r': 0.3, 'h': 1.2},
}


def outside(objs, cell_from, cell_to, tol=0.01):
    """Records whose plan footprint leaves the cell block."""
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    bad = []
    for o in objs:
        f = FOOT.get(o['kind'])
        if not f:
            continue
        p = dict(DEFAULTS.get(o['kind'], {}))
        p.update(o['p'])
        ax, az = f(p)
        if abs(math.sin(o['ry'])) > 0.5:  # turned a quarter: along and depth swap
            ax, az = az, ax
        if (
            o['x'] - ax / 2 < xmin - tol
            or o['x'] + ax / 2 > xmax + tol
            or o['z'] - az / 2 < zmin - tol
            or o['z'] + az / 2 > zmax + tol
        ):
            bad.append((o['id'], o['kind'], round(o['x'], 2), round(o['z'], 2)))
    return bad


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in ('furnish_kitchen', 'furnish_bathroom', 'add_utility')), names)

import zyg_workflows.arch_assistant_ext.furniture_kitchen_bath as F  # noqa: E402

check('KINDS declares all 15 kinds', sorted(F.KINDS) == sorted(KINDS), sorted(F.KINDS))
check(
    'defaults match the rail/JS defaults',
    all(F.KINDS[k] == DEFAULTS[k] for k in KINDS),
    [k for k in KINDS if F.KINDS[k] != DEFAULTS[k]],
)
check('PROMPT is one paragraph under 900 chars', 0 < len(F.PROMPT) <= 900 and '\n' not in F.PROMPT, len(F.PROMPT))
check('3-6 worked examples', 3 <= len(F.EXAMPLES) <= 6, len(F.EXAMPLES))

# a 4 x 3 block, kitchen on the north wall
txt, d = assistant('furnish_kitchen', {'cell_from': 'D10', 'cell_to': 'G12', 'side': 'north'})
k = kinds_of(d)
counters = [o for o in d.objs if o['kind'] == 'kitchen_counter']
apps = [o for o in d.objs if o['kind'] in ('fridge', 'dishwasher', 'sink', 'stove')]
cabs = [o for o in d.objs if o['kind'] == 'wall_cabinet']
check(
    'one counter run, len 3.8 on a 4 m wall',
    len(counters) == 1 and abs(counters[0]['p']['len'] - 3.8) < 1e-6,
    (len(counters), counters and counters[0]['p']),
)
check('at least 4 appliances inline', len(apps) >= 4, k)
check(
    'appliances are fridge, dishwasher, sink, stove',
    sorted(o['kind'] for o in apps) == ['dishwasher', 'fridge', 'sink', 'stove'],
    sorted(o['kind'] for o in apps),
)
check(
    'wall cabinets at y = storey*2.7 + 1.5',
    bool(cabs) and all(abs(o['y'] - 1.5) < 1e-9 for o in cabs),
    [(o['id'], o['y']) for o in cabs],
)
check('everything is inside the block', outside(d.objs, 'D10', 'G12') == [], outside(d.objs, 'D10', 'G12'))
check(
    'the run faces back into the room (ry = pi on the north wall)',
    all(abs(o['ry'] - math.pi) < 1e-6 for o in d.objs),
    [(o['kind'], o['ry']) for o in d.objs],
)
check('the result names the counter and the count', 'counter' in txt and '3.8' in txt, txt)
check('no island on a 3 m deep room', kinds_of(d).get('kitchen_island') is None, kinds_of(d))

txt, d2 = assistant('furnish_kitchen', {'cell_from': 'D10', 'cell_to': 'G12', 'side': 'north', 'island': True})
check(
    'island asked for but the room is too shallow -> a note, not an island',
    kinds_of(d2).get('kitchen_island') is None and 'no island' in txt,
    txt,
)

txt, d3 = assistant(
    'furnish_kitchen', {'cell_from': 'D10', 'cell_to': 'G14', 'side': 'north', 'island': True, 'storey': 1}
)
isl = [o for o in d3.objs if o['kind'] == 'kitchen_island']
check('island on a 5 m deep room, storey 1', len(isl) == 1 and abs(isl[0]['y'] - 2.7) < 1e-9, txt)
check(
    'storey 1 cabinets at 2.7 + 1.5', all(abs(o['y'] - 4.2) < 1e-9 for o in d3.objs if o['kind'] == 'wall_cabinet'), txt
)
check('island block still inside the cells', outside(d3.objs, 'D10', 'G14') == [], outside(d3.objs, 'D10', 'G14'))

txt, d4 = assistant('furnish_kitchen', {'cell_from': 'D10', 'cell_to': 'G12', 'side': 'east'})
c4 = [o for o in d4.objs if o['kind'] == 'kitchen_counter'][0]
check('east wall run is the 3 m side minus 0.2', abs(c4['p']['len'] - 2.8) < 1e-6, c4['p'])
check('east wall run faces -x (ry = pi/2)', abs(c4['ry'] - math.pi / 2) < 1e-6, c4['ry'])
check('east kitchen inside the block', outside(d4.objs, 'D10', 'G12') == [], outside(d4.objs, 'D10', 'G12'))

# refusals
txt, _ = assistant('furnish_kitchen', {'cell_from': 'D10', 'cell_to': 'G12', 'side': 'up'})
check('bad side refused', txt.startswith('refused'), txt)
txt, _ = assistant('furnish_kitchen', {'cell_from': 'A1', 'cell_to': 'A1'})
check('a one-cell room refused', txt.startswith('refused'), txt)
txt, _ = assistant('furnish_kitchen', {'cell_from': 'ZZ9', 'cell_to': 'G12'})
check('off-grid cell refused', txt.startswith('refused'), txt)

# a 3 x 3 bathroom
txt, b = assistant('furnish_bathroom', {'cell_from': 'P6', 'cell_to': 'R8', 'door_side': 'south'})
kb = kinds_of(b)
check(
    'bathroom has toilet, washbasin, mirror, bath and shower',
    all(kb.get(x) == 1 for x in ('toilet', 'washbasin', 'mirror', 'bathtub', 'shower')),
    kb,
)
mir = [o for o in b.objs if o['kind'] == 'mirror'][0]
bas = [o for o in b.objs if o['kind'] == 'washbasin'][0]
check(
    'the mirror hangs at 1.2 m over the basin',
    abs(mir['y'] - 1.2) < 1e-9 and abs(mir['x'] - bas['x']) < 0.3 and abs(mir['z'] - bas['z']) < 0.05,
    (mir['y'], mir['x'], bas['x']),
)
tub = [o for o in b.objs if o['kind'] == 'bathtub'][0]
check('the bath is 1.7 m along the longest wall', abs(tub['p']['l'] - 1.7) < 1e-6, tub['p'])
check('every fixture is inside the block', outside(b.objs, 'P6', 'R8') == [], outside(b.objs, 'P6', 'R8'))
check('the towel rail came too', kb.get('towel_rail') == 1, kb)
check('the result names the walls used', 'bath on the' in txt and 'door on the south' in txt, txt)

txt, b2 = assistant(
    'furnish_bathroom', {'cell_from': 'P6', 'cell_to': 'Q7', 'door_side': 'north', 'bath': False, 'storey': 2}
)
k2 = kinds_of(b2)
check(
    'a 2 x 2 room: no bath when asked, and no room for the shower',
    k2.get('bathtub') is None and k2.get('shower') is None and k2.get('toilet') == 1,
    k2,
)
check(
    'storey 2 fixtures sit at 5.4 m',
    all(abs(o['y'] - 5.4) < 1e-9 for o in b2.objs if o['kind'] in ('toilet', 'washbasin')),
    k2,
)
txt, _ = assistant('furnish_bathroom', {'cell_from': 'P6', 'cell_to': 'P6'})
check('a one-cell bathroom refused', txt.startswith('refused'), txt)
txt, _ = assistant('furnish_bathroom', {'cell_from': 'P6', 'cell_to': 'R8', 'door_side': 'sideways'})
check('bad door_side refused', txt.startswith('refused'), txt)

# utility
txt, u = assistant('add_utility', {'cell_from': 'K2', 'cell_to': 'L3'})
ku = kinds_of(u)
check(
    'utility: washing machine, boiler and a counter',
    ku.get('washing_machine') == 1 and ku.get('boiler') == 1 and ku.get('kitchen_counter') == 1,
    ku,
)
bo = [o for o in u.objs if o['kind'] == 'boiler'][0]
check('the boiler is hung at 0.8 m', abs(bo['y'] - 0.8) < 1e-9, bo['y'])
check('utility fits the 2 x 2 room', outside(u.objs, 'K2', 'L3') == [], outside(u.objs, 'K2', 'L3'))
check(
    'every utility record carries the group',
    all(o['grp'].startswith('utility') for o in u.objs),
    [o['grp'] for o in u.objs],
)
txt, _ = assistant('add_utility', {'cell_from': 'K2', 'cell_to': 'K2'})
check('a one-cell utility refused', txt.startswith('refused'), txt)

txt, _ = assistant('add_object', {'kind': 'bathtub', 'cell': 'A1', 'params': {'l': 1.9}})
check('add_object knows the new kinds', txt and 'refused' not in txt and 'unknown' not in txt, txt)
check('rail lists all 15 kinds', rail_has(KINDS) == [], rail_has(KINDS))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [{'kind': k, 'p': dict(DEFAULTS[k])} for k in KINDS]
bb = browser_kinds(cases)
check('no page errors', not any(x.get('page_errors') for x in bb), [x.get('page_errors') for x in bb][:1])
by = {x['kind']: x for x in bb}
for k in KINDS:
    r = by.get(k) or {}
    want = SIZE[k]
    got = r.get('size') or [0, 0, 0]
    ok = bool(r.get('ok')) and r.get('registered') and all(abs(got[i] - want[i]) < 0.03 for i in range(3))
    check(f'tab builds {k} at {want[0]:g} x {want[1]:g} x {want[2]:g} m', ok, (got, r.get('err'), r.get('tris')))
check(
    'every piece stands on y = 0',
    all(abs((by[k].get('min') or [0, 9, 0])[1]) < 1e-3 for k in KINDS),
    [(k, by[k].get('min')) for k in KINDS if abs((by[k].get('min') or [0, 9, 0])[1]) >= 1e-3],
)
check(
    'labels read well in the outliner',
    by['fridge']['label'] == 'Fridge'
    and by['bathtub']['label'] == 'Bath'
    and by['kitchen_counter']['label'] == 'Kitchen counter',
    (by['fridge']['label'], by['bathtub']['label'], by['kitchen_counter']['label']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for k in KINDS:
    check(f'blender builds {k}', bl.get(k, {}).get('polys', 0) > 0, bl.get(k))
finish()
