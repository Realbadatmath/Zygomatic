# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_vehicles_props.py — proof for the vehicles_props family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_vehicles_props.py

Three engines must agree about the 14 new kinds: the assistant's four tools
produce the records claimed, the tab builds each kind at exactly the size its
parameters name (length along X, height along Y, width along Z), and Blender
builds a mesh with faces for each.
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
from zyg_workflows import arch_assistant as A  # noqa: E402

KINDS = [
    'car',
    'van',
    'bus',
    'truck',
    'bicycle',
    'motorcycle',
    'boat',
    'tractor',
    'crane_tower',
    'scaffold',
    'container',
    'dumpster',
    'pallet',
    'forklift',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('add_vehicles', 'add_construction_site', 'park_cars', 'add_scaffold')),
    names,
)

# a 20 x 10 m block: columns C..V (20), rows 4..13 (10)
from zyg_workflows.arch_assistant import block_bounds  # noqa: E402

xmin, zmin, xmax, zmax = block_bounds('C4', 'V13')
check(
    'the test block really is 20 x 10 m',
    abs(xmax - xmin - 20) < 1e-6 and abs(zmax - zmin - 10) < 1e-6,
    (xmin, zmin, xmax, zmax),
)
txt, d = assistant('add_vehicles', {'cell_from': 'C4', 'cell_to': 'V13', 'kind': 'car', 'count': 6, 'spacing': 3})
check('add_vehicles drew 6 cars', kinds_of(d).get('car') == 6, txt)
cars = [o for o in d.objs if o['kind'] == 'car']
inside = all(
    xmin - 1e-6 <= o['x'] - o['p']['l'] / 2
    and o['x'] + o['p']['l'] / 2 <= xmax + 1e-6
    and zmin - 1e-6 <= o['z'] - o['p']['w'] / 2
    and o['z'] + o['p']['w'] / 2 <= zmax + 1e-6
    for o in cars
)
check('every car sits inside the block', inside, [(o['x'], o['z']) for o in cars])
check(
    'cars are 3 m apart and carry the catalogue size',
    abs(cars[1]['x'] - cars[0]['x'] - 3.0) < 1e-6 and cars[0]['p'] == {'l': 4.5, 'w': 1.8, 'h': 1.5},
    cars[0],
)
txt, d = assistant('add_vehicles', {'cell_from': 'C4', 'cell_to': 'V13', 'kind': 'hovercraft'}, drawing=d)
check('unknown vehicle kind refused', txt.startswith('refused'), txt)
txt, d = assistant('add_vehicles', {'cell_from': 'C4', 'cell_to': 'C5', 'kind': 'bus'}, drawing=d)
check('a 12 m bus in a 1 x 2 m block refused', txt.startswith('refused'), txt)

txt, d = assistant('park_cars', {'cells': ['C20', 'F20', 'I20']}, drawing=d)
check('park_cars parked 3', kinds_of(d).get('car') == 9 and '3 car' in txt, txt)
parked = [o for o in d.objs if o['grp'] == 'parked cars']
check('one car per cell, turned 90 degrees', len(parked) == 3 and abs(parked[0]['ry'] - 1.5707963) < 1e-4, txt)
txt, d = assistant('park_cars', {'cells': []}, drawing=d)
check('park_cars with no cells refused', txt.startswith('refused'), txt)

txt, d = assistant('add_construction_site', {'cell_from': 'B20', 'cell_to': 'X34', 'containers': 2}, drawing=d)
k = kinds_of(d)
check(
    'construction site: a crane, 2 containers, a skip, pallets',
    k.get('crane_tower') == 1 and k.get('container') == 2 and k.get('dumpster') == 1 and k.get('pallet') == 4,
    k,
)
crane = next(o for o in d.objs if o['kind'] == 'crane_tower')
check(
    'the crane stands at the block corner with a 30 m mast and a 25 m jib',
    crane['p'] == {'h': 30.0, 'jib': 25.0, 'mast': 1.6} and abs(crane['x'] - (-150 + 1 + 1.6)) < 1e-6,
    crane,
)
txt, d = assistant('add_construction_site', {'cell_from': 'B20', 'cell_to': 'C21'}, drawing=d)
check('a 2 x 2 m building site refused', txt.startswith('refused'), txt)

# a box whose north/south walls are 10 m long (columns C..L = 10, rows 4..9 = 6)
txt, d2 = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L9', 'name': 'house'})
w10 = next(o for o in d2.objs if o['kind'] == 'wall' and abs(o['p']['len'] - 10) < 1e-6)
txt, d2 = assistant('add_scaffold', {'wall_id': w10['id']}, drawing=d2)
sc = d2.objs[-1]
check('scaffold on a 10 m wall is 10 m long', sc['kind'] == 'scaffold' and sc['p']['w'] == 10.0, (txt, sc['p']))
check(
    'scaffold is as tall as the wall, one lift per 2 m, 1.2 m deep',
    sc['p']['h'] == 2.7 and sc['p']['lifts'] == 1 and sc['p']['d'] == 1.2 and sc['p']['bays'] == 5,
    sc['p'],
)
check(
    'scaffold stands clear of the wall, on its outside face',
    abs(abs(sc['z'] - w10['z']) - (0.24 / 2 + 1.2 / 2 + 0.06)) < 1e-6,
    (sc['z'], w10['z']),
)
txt, d2 = assistant('add_scaffold', {'wall_id': 'o999'}, drawing=d2)
check('scaffold on a non-wall refused', txt.startswith('refused'), txt)
txt, d2 = assistant(
    'add_construction_site', {'cell_from': 'A2', 'cell_to': 'P20', 'scaffold_group': 'house'}, drawing=d2
)
check('scaffold_group scaffolds the four outside walls of the group', kinds_of(d2).get('scaffold') == 5, kinds_of(d2))
grp_sc = [o for o in d2.objs if o['kind'] == 'scaffold' and o['grp'] != 'scaffold ' + w10['id']]
check(
    'those scaffolds are as long as their walls (2 x 10 m, 2 x 6 m)',
    sorted(round(o['p']['w'], 2) for o in grp_sc) == [6.0, 6.0, 10.0, 10.0],
    [o['p']['w'] for o in grp_sc],
)
txt, d2 = assistant(
    'add_construction_site', {'cell_from': 'A2', 'cell_to': 'P20', 'scaffold_group': 'nothing'}, drawing=d2
)
check('an unknown scaffold_group refused', txt.startswith('refused'), txt)

txt, d3 = assistant('add_object', {'kind': 'forklift', 'cell': 'A1', 'params': {'l': 3.4}})
check('add_object knows the new kinds', d3.objs[-1]['kind'] == 'forklift' and d3.objs[-1]['p']['l'] == 3.4, txt)
check('rail lists all 14 kinds', rail_has(KINDS) == [], rail_has(KINDS))

# ── R5: everything stands on the ground under its own centre (2026-09-07) ─────
print('R5 ground placement')
check(
    'on flat ground nothing moved: the six cars are still at y 0 with no lean',
    all(o['y'] == 0.0 and o['rz'] == 0.0 for o in cars),
    [(o['y'], o['rz']) for o in cars],
)

# a 10 x 10 m slope over A1..J10 climbing 4.5 m to the south (+z): 0.45 per metre
txt, ds = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'})
txt, ds = assistant('park_cars', {'cells': ['C2', 'C5', 'C8'], 'rotation_deg': 90}, drawing=ds)
up = [o for o in ds.objs if o['kind'] == 'car']
ys = [o['y'] for o in up]
check(
    'three cars up the slope get three ASCENDING y values',
    len(ys) == 3 and ys[0] < ys[1] < ys[2] and abs(ys[0] - 0.675) < 1e-6 and abs(ys[2] - 3.375) < 1e-6,
    ys,
)
check(
    '...and every one of them equals the ground under its own centre',
    all(abs(o['y'] - A.ground_height(ds, o['x'], o['z'])) < 1e-9 for o in up),
    [(o['y'], A.ground_height(ds, o['x'], o['z'])) for o in up],
)
want_rz = math.atan(0.45)
check(
    'a car pointing north (ry 90) down a slope that climbs south leans nose-down by atan(0.45)',
    all(abs(o['rz'] + want_rz) < 1e-4 for o in up),
    [(o['ry'], o['rz'], -want_rz) for o in up],
)
check('the reply says it followed the ground', 'following the ground' in txt, txt)

txt, dx = assistant('add_slope', {'cell_from': 'A20', 'cell_to': 'J29', 'height': 4.5, 'direction': 'x'})
txt, dx = assistant(
    'add_vehicles',
    {'cell_from': 'B21', 'cell_to': 'J28', 'kind': 'car', 'count': 3, 'spacing': 2.0, 'rotation_deg': 0},
    drawing=dx,
)
east = [o for o in dx.objs if o['kind'] == 'car']
check(
    'cars nose-east up an east-climbing slope lean nose-UP by +atan(0.45)',
    len(east) == 3 and all(abs(o['rz'] - want_rz) < 1e-4 for o in east),
    [(o['rz'], want_rz) for o in east],
)
check(
    '...each at its own ground height, ascending eastward',
    east[0]['y'] < east[1]['y'] < east[2]['y']
    and all(abs(o['y'] - A.ground_height(dx, o['x'], o['z'])) < 1e-9 for o in east),
    [o['y'] for o in east],
)
txt, dx = assistant(
    'add_vehicles',
    {'cell_from': 'B21', 'cell_to': 'J28', 'kind': 'container', 'count': 2, 'base_height': 0},
    drawing=dx,
)
cont = [o for o in dx.objs if o['kind'] == 'container']
check(
    'base_height overrides the ground and cancels the lean',
    len(cont) == 2 and all(o['y'] == 0.0 and o['rz'] == 0.0 for o in cont),
    [(o['y'], o['rz']) for o in cont],
)
txt, dx = assistant(
    'add_vehicles', {'cell_from': 'B21', 'cell_to': 'J28', 'kind': 'van', 'count': 1, 'storey': 1}, drawing=dx
)
van = dx.objs[-1]
check(
    'a storey lift adds ON TOP of the ground, it does not replace it',
    abs(van['y'] - (A.ground_height(dx, van['x'], van['z']) + 2.7)) < 1e-6,
    van['y'],
)

# the site plant: on the ground, but never leaning
txt, dc = assistant('add_hill', {'centre': 'P60', 'radius': 14, 'height': 5})
txt, dc = assistant('add_construction_site', {'cell_from': 'H52', 'cell_to': 'X68', 'containers': 2}, drawing=dc)
plant = [o for o in dc.objs if o['kind'] in ('crane_tower', 'container', 'pallet', 'dumpster')]
check(
    'every building-site piece stands on the ground under itself',
    len(plant) == 8 and all(abs(o['y'] - A.ground_height(dc, o['x'], o['z'])) < 1e-3 for o in plant),
    [(o['kind'], o['y'], round(A.ground_height(dc, o['x'], o['z']), 3)) for o in plant],
)
check(
    'the hill really varies under the site, so that was not eight zeroes',
    max(o['y'] for o in plant) - min(o['y'] for o in plant) > 1.0,
    sorted(round(o['y'], 3) for o in plant),
)
check(
    'site plant never leans (a crane and a skip stand plumb)',
    all(o['rz'] == 0.0 and o['rx'] == 0.0 for o in plant),
    [(o['kind'], o['rz']) for o in plant],
)
check(
    'R8 nothing buried, nothing floating: every record on the site matches its ground within 0.3 m',
    all(abs(o['y'] - A.ground_height(dc, o['x'], o['z'])) < 0.3 for o in plant),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
# kind -> (params, expected bounding box [x = length, y = height, z = width])
SIZES = {
    'car': ({'l': 4.5, 'w': 1.8, 'h': 1.5}, [4.5, 1.5, 1.8]),
    'van': ({'l': 5.5, 'w': 2.0, 'h': 2.4}, [5.5, 2.4, 2.0]),
    'bus': ({'l': 12, 'w': 2.5, 'h': 3.2}, [12.0, 3.2, 2.5]),
    'truck': ({'l': 9, 'w': 2.5, 'h': 3.6}, [9.0, 3.6, 2.5]),
    'bicycle': ({'l': 1.8, 'h': 1.0}, [1.8, 1.0, 0.55]),
    'motorcycle': ({'l': 2.1, 'h': 1.1}, [2.1, 1.1, 0.8]),
    'boat': ({'l': 6, 'w': 2.2, 'h': 1.5}, [6.0, 1.5, 2.2]),
    'tractor': ({'l': 4, 'w': 2.2, 'h': 2.8}, [4.0, 2.8, 2.2]),
    'scaffold': ({'w': 6, 'h': 6, 'd': 1.2, 'bays': 3, 'lifts': 3}, [6.0, 6.0, 1.2]),
    'container': ({'l': 6.06, 'w': 2.44, 'h': 2.59}, [6.06, 2.59, 2.44]),
    'dumpster': ({'l': 3, 'w': 1.8, 'h': 1.4}, [3.0, 1.4, 1.8]),
    'pallet': ({'l': 1.2, 'w': 0.8, 'h': 0.15}, [1.2, 0.15, 0.8]),
    'forklift': ({'l': 3, 'w': 1.2, 'h': 2.1}, [3.0, 2.1, 1.2]),
}
LEAN = math.atan(0.45)  # the lean park_cars gives a car on a 1:2.2 slope
cases = [{'kind': k, 'p': SIZES[k][0]} for k in SIZES] + [
    {'kind': 'crane_tower', 'p': {'h': 30, 'jib': 25, 'mast': 1.6}}
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
for k, (_p, want) in SIZES.items():
    r = by.get(k) or {}
    ok = bool(r.get('ok')) and r.get('size') and all(abs(r['size'][i] - want[i]) < 0.02 for i in range(3))
    check(f'{k} builds, {want[0]:g} long x {want[1]:g} high x {want[2]:g} wide', ok, r)
cr = by.get('crane_tower') or {}
check(
    'crane_tower builds: 30 m mast, a jib reaching at least 25 m',
    bool(cr.get('ok')) and abs(cr['size'][1] - 30) < 1.0 and cr['size'][0] >= 25.0 and abs(cr['size'][2] - 1.6) < 0.02,
    cr,
)
check(
    'all 14 kinds registered in the tab',
    all((by.get(k) or {}).get('registered') for k in KINDS),
    [k for k in KINDS if not (by.get(k) or {}).get('registered')],
)
check(
    'labels read well',
    (by['car']['label'], by['crane_tower']['label'], by['dumpster']['label']) == ('Car', 'Tower crane', 'Skip'),
    (by['car']['label'], by['crane_tower']['label'], by['dumpster']['label']),
)

# the lean is a REAL rotation both engines apply: a leaning car is taller
tilt_case = {'kind': 'car', 'p': SIZES['car'][0], 'rz': LEAN}
tb = browser_kinds([tilt_case])[0]
flat_h = by['car']['size'][1]
rise = 4.5 * math.sin(LEAN)  # at most 1.85 m of nose lift across the 4.5 m body
check(
    'tab: a car leaning by atan(0.45) is visibly taller than a flat one, by at most its nose lift',
    bool(tb.get('ok')) and flat_h + 0.5 < tb['size'][1] <= flat_h + rise + 0.01,
    (flat_h, tb.get('size'), rise),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for k in KINDS:
    check(f'blender builds {k}', bl.get(k, {}).get('polys', 0) > 0, bl.get(k))
blt = blender_kinds([tilt_case])
check(
    'blender: the leaning car has the SAME height as in the tab (%.2f m)' % tb['size'][1],
    abs(blt.get('car', {}).get('size', [0, 0, 0])[1] - tb['size'][1]) < 0.05,
    (blt.get('car', {}).get('size'), tb['size']),
)
finish()
