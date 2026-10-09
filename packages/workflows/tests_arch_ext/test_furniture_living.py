# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_furniture_living.py — the furniture_living family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_furniture_living.py
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

KINDS = [
    'bed_single',
    'bed_double',
    'wardrobe',
    'nightstand',
    'sofa',
    'armchair',
    'coffee_table',
    'dining_table',
    'chair',
    'desk',
    'bookcase',
    'tv_unit',
    'rug',
    'lamp_floor',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in ('furnish_room', 'place_furniture_set')), names)

from zyg_workflows.arch_assistant import block_bounds  # noqa: E402

XMIN, ZMIN, XMAX, ZMAX = block_bounds('C4', 'F7')  # a 4 x 4 cell room
txt, d = assistant('furnish_room', {'cell_from': 'C4', 'cell_to': 'F7', 'room': 'bedroom', 'door_side': 'south'})
k = kinds_of(d)
check(
    'bedroom: 1 double bed, 2 nightstands, 1 wardrobe',
    k.get('bed_double') == 1 and k.get('nightstand') == 2 and k.get('wardrobe') == 1,
    (k, txt),
)
inside = [
    (o['id'], o['kind'], o['x'], o['z']) for o in d.objs if not (XMIN <= o['x'] <= XMAX and ZMIN <= o['z'] <= ZMAX)
]
check('every piece sits inside the block bounds', inside == [], (inside, (XMIN, ZMIN, XMAX, ZMAX)))
bed = [o for o in d.objs if o['kind'] == 'bed_double'][0]
check(
    'the bed has its head on the north wall',
    bed['z'] - ZMIN < 1.3 and bed['ry'] == 0.0 and bed['p']['w'] == 1.6 and bed['p']['l'] == 2.0,
    bed,
)
check('a group and readable names', bed['grp'].startswith('bedroom ') and bed['name'] == 'double bed', bed)

txt, d = assistant('furnish_room', {'cell_from': 'C4', 'cell_to': 'D5', 'room': 'bedroom'}, drawing=d)
check('a 2x2 room is refused', txt.startswith('refused') and '3x3' in txt, txt)
txt, d = assistant('furnish_room', {'cell_from': 'C4', 'cell_to': 'F7', 'room': 'ballroom'}, drawing=d)
check('an unknown room is refused', txt.startswith('refused'), txt)
txt, d = assistant('furnish_room', {'cell_from': 'ZZ9', 'cell_to': 'F7', 'room': 'living'}, drawing=d)
check('an off-grid cell is refused', txt.startswith('refused'), txt)

txt, d2 = assistant('furnish_room', {'cell_from': 'H10', 'cell_to': 'N16', 'room': 'living', 'storey': 1})
k = kinds_of(d2)
check(
    'living: sofa, tv unit, coffee table, rug',
    k.get('sofa') == 1 and k.get('tv_unit') == 1 and k.get('coffee_table') == 1 and k.get('rug') == 1,
    (k, txt),
)
sofa = [o for o in d2.objs if o['kind'] == 'sofa'][0]
tv = [o for o in d2.objs if o['kind'] == 'tv_unit'][0]
check('storey 1 puts everything at y = 2.7', all(abs(o['y'] - 2.7) < 1e-9 for o in d2.objs), [o['y'] for o in d2.objs])
check('the sofa faces the tv across the room', sofa['z'] > tv['z'] and abs(sofa['ry']) < 1e-9, (sofa['z'], tv['z']))

txt, d3 = assistant('place_furniture_set', {'cell': 'K12', 'set': 'dining_6', 'rotation_deg': 90})
k = kinds_of(d3)
check('dining_6: 1 table + 6 chairs', k.get('dining_table') == 1 and k.get('chair') == 6, (k, txt))
_, d0 = assistant('place_furniture_set', {'cell': 'K12', 'set': 'dining_6'})


def _span(dd):
    return (
        round(max(o['x'] for o in dd.objs) - min(o['x'] for o in dd.objs), 3),
        round(max(o['z'] for o in dd.objs) - min(o['z'] for o in dd.objs), 3),
    )


check(
    "rotation_deg=90 swaps the cluster's x and z spans",
    _span(d3) == _span(d0)[::-1] and _span(d0)[0] > _span(d0)[1],
    (_span(d0), _span(d3)),
)
txt, d3 = assistant('place_furniture_set', {'cell': 'K12', 'set': 'dining_4'}, drawing=d3)
check('dining_4: 1 table + 4 chairs', kinds_of(d3).get('chair') == 10 and kinds_of(d3).get('dining_table') == 2, txt)
txt, d3 = assistant('place_furniture_set', {'cell': 'D20', 'set': 'living_trio'}, drawing=d3)
check(
    'living_trio: sofa + coffee table + tv unit',
    kinds_of(d3).get('sofa') == 1 and kinds_of(d3).get('coffee_table') == 1 and kinds_of(d3).get('tv_unit') == 1,
    txt,
)
txt, d3 = assistant('place_furniture_set', {'cell': 'D20', 'set': 'kitchen_pair'}, drawing=d3)
check('an unknown set is refused', txt.startswith('refused'), txt)

txt, d3 = assistant('add_object', {'kind': 'lamp_floor', 'cell': 'A1', 'params': {'h': 1.8}}, drawing=d3)
check('add_object knows the new kinds', d3.objs[-1]['kind'] == 'lamp_floor' and d3.objs[-1]['p']['h'] == 1.8, txt)
missing = rail_has(KINDS)
check('rail lists all 14 kinds', missing == [], missing)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'bed_single', 'p': {'w': 0.9, 'l': 2.0, 'h': 0.5, 'head': 0.9}},
    {'kind': 'bed_double', 'p': {'w': 1.6, 'l': 2.0, 'h': 0.5, 'head': 1.0}},
    {'kind': 'wardrobe', 'p': {'w': 1.2, 'd': 0.6, 'h': 2.1}},
    {'kind': 'nightstand', 'p': {'w': 0.45, 'd': 0.4, 'h': 0.55}},
    {'kind': 'sofa', 'p': {'w': 2.2, 'd': 0.9, 'h': 0.85, 'seat': 0.45}},
    {'kind': 'armchair', 'p': {'w': 0.9, 'd': 0.9, 'h': 0.85}},
    {'kind': 'coffee_table', 'p': {'w': 1.1, 'd': 0.6, 'h': 0.42}},
    {'kind': 'dining_table', 'p': {'w': 1.8, 'd': 0.9, 'h': 0.75}},
    {'kind': 'chair', 'p': {'w': 0.45, 'd': 0.45, 'h': 0.9, 'seat': 0.45}},
    {'kind': 'desk', 'p': {'w': 1.4, 'd': 0.7, 'h': 0.75}},
    {'kind': 'bookcase', 'p': {'w': 0.9, 'd': 0.35, 'h': 2.0, 'shelves': 5}},
    {'kind': 'tv_unit', 'p': {'w': 1.6, 'd': 0.45, 'h': 0.5, 'screen': 1.2}},
    {'kind': 'rug', 'p': {'w': 2.4, 'd': 1.7, 't': 0.02}},
    {'kind': 'lamp_floor', 'p': {'h': 1.6, 'r': 0.2}},
]
EXPECT = {
    'bed_single': (0.9, 0.9, 2.0),
    'bed_double': (1.6, 1.0, 2.0),
    'wardrobe': (1.2, 2.1, 0.6),
    'nightstand': (0.45, 0.55, 0.4),
    'sofa': (2.2, 0.85, 0.9),
    'armchair': (0.9, 0.85, 0.9),
    'coffee_table': (1.1, 0.42, 0.6),
    'dining_table': (1.8, 0.75, 0.9),
    'chair': (0.45, 0.9, 0.45),
    'desk': (1.4, 0.75, 0.7),
    'bookcase': (0.9, 2.0, 0.35),
    'tv_unit': (1.6, 1.148, 0.45),
    'rug': (2.4, 0.02, 1.7),
    'lamp_floor': (0.4, 1.6, 0.4),
}
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'all 14 kinds build real geometry',
    all(by[kk]['ok'] for kk in KINDS),
    {kk: (by[kk]['ok'], by[kk].get('err')) for kk in KINDS if not by[kk]['ok']},
)
for kk in KINDS:
    e, got = EXPECT[kk], by[kk]['size']
    check(f'{kk} sized {e[0]:g} x {e[1]:g} x {e[2]:g} m', all(abs(got[i] - e[i]) < 0.02 for i in range(3)), (got, e))
check(
    'bottom sits on the floor',
    all(abs(by[kk]['min'][1]) < 1e-3 for kk in KINDS),
    {kk: by[kk]['min'][1] for kk in KINDS},
)
check(
    'labels',
    by['bed_double']['label'] == 'Double bed'
    and by['tv_unit']['label'] == 'TV unit'
    and by['lamp_floor']['label'] == 'Floor lamp',
    (by['bed_double']['label'], by['tv_unit']['label'], by['lamp_floor']['label']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kk in KINDS:
    check(f'blender builds {kk}', bl.get(kk, {}).get('polys', 0) > 0, bl.get(kk))
finish()
