# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_polygon_footprints.py — proof for the polygon_footprints family.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_polygon_footprints.py
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

SQUARE = [[-3, -2], [3, -2], [3, 2], [-3, 2]]  # 6 x 4 m
HOLE = [[[-1, -1], [1, -1], [1, 1], [-1, 1]]]  # 2 x 2 m void

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(
        t in names
        for t in ('draw_polygon_building', 'draw_l_building', 'draw_regular_building', 'add_polygon_slab', 'add_atrium')
    ),
    names,
)

# a four-cell plan: C4 L4 L13 C13 -> a 9 x 9 m square through the cell centres
txt, d = assistant('draw_polygon_building', {'cells': ['C4', 'L4', 'L13', 'C13'], 'storeys': 2})
k = kinds_of(d)
check('4-cell plan: 4 walls + 1 slab per storey', k.get('wall') == 8 and k.get('slab_poly') == 2, (k, txt))
slab = [o for o in d.objs if o['kind'] == 'slab_poly'][0]
check(
    'slab sits on the centroid of the cell centres',
    abs(slab['x'] - (-143.0)) < 1e-6 and abs(slab['z'] - (-142.0)) < 1e-6,
    (slab['x'], slab['z']),
)
check(
    'slab pts are the cell centres relative to it',
    sorted(tuple(p) for p in slab['p']['pts']) == [(-4.5, -4.5), (-4.5, 4.5), (4.5, -4.5), (4.5, 4.5)],
    slab['p']['pts'],
)
w0 = [o for o in d.objs if o['kind'] == 'wall'][0]
check('edge walls are 9 m long and on the storey base', abs(w0['p']['len'] - 9.0) < 1e-6 and w0['y'] == 0.0, w0)
check('second storey at 2.7 m', [o for o in d.objs if o['kind'] == 'wall'][4]['y'] == 2.7)
txt, d2 = assistant('draw_polygon_building', {'cells': ['C4', 'L4'], 'storeys': 1})
check('two cells refused', txt.startswith('refused'), txt)

# L: the C4..L13 block (10 x 10 m) minus the C4..E6 corner notch (3 x 3 m)
txt, d = assistant(
    'draw_l_building',
    {'cell_from': 'C4', 'cell_to': 'L13', 'notch_from': 'C4', 'notch_to': 'E6', 'storeys': 2, 'roof': 'flat'},
)
k = kinds_of(d)
check('L building: 6 walls per storey', k.get('wall') == 12, (k, txt))
check('L building: 2 floors + 1 flat roof slab', k.get('slab_poly') == 3, k)
ls = sorted(round(o['p']['len'], 3) for o in d.objs if o['kind'] == 'wall' and o['y'] == 0.0)
check('L edge lengths are 3,3,7,7,10,10', ls == [3.0, 3.0, 7.0, 7.0, 10.0, 10.0], ls)
roof = [o for o in d.objs if o['kind'] == 'slab_poly'][-1]
check('flat roof is 0.3 thick and sits on top (2 x 2.7 m)', roof['p']['t'] == 0.3 and roof['y'] == 5.4, roof)
txt, d3 = assistant('draw_l_building', {'cell_from': 'C4', 'cell_to': 'L13', 'notch_from': 'F7', 'notch_to': 'H9'})
check('floating notch refused', txt.startswith('refused') and 'add_atrium' in txt, txt)

# a regular hexagon
txt, d = assistant('draw_regular_building', {'centre': 'K20', 'sides': 6, 'radius': 6, 'storeys': 1, 'roof': 'pyramid'})
k = kinds_of(d)
check(
    'hexagon: 6 walls, 1 slab, 1 pyramid',
    k.get('wall') == 6 and k.get('slab_poly') == 1 and k.get('pyramid') == 1,
    (k, txt),
)
py = [o for o in d.objs if o['kind'] == 'pyramid'][0]
check(
    'pyramid roof r=radius+0.3, sides=6, h=radius*0.6',
    py['p'] == {'r': 6.3, 'h': 3.6, 'sides': 6} and py['y'] == 2.7,
    py,
)
txt, d4 = assistant('draw_regular_building', {'centre': 'K20', 'sides': 2})
check('2 sides refused', txt.startswith('refused'), txt)

# a single polygon slab
txt, d = assistant('add_polygon_slab', {'cells': ['C14', 'L14', 'L16', 'C16'], 'storey': 1, 'thickness': 0.18})
s = d.objs[-1]
check(
    'polygon slab at storey 1, 0.18 thick, 4 corners',
    s['kind'] == 'slab_poly' and s['y'] == 2.7 and s['p']['t'] == 0.18 and len(s['p']['pts']) == 4,
    (s, txt),
)

# an atrium through a draw_box's slabs
txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'name': 'blok'})
txt, d = assistant('add_atrium', {'group': 'blok', 'cell_from': 'F7', 'cell_to': 'H9'}, drawing=d)
k = kinds_of(d)
check('3 slabs became polygon slabs', k.get('slab_poly') == 3 and 'slab' not in k, (k, txt))
sp = [o for o in d.objs if o['kind'] == 'slab_poly'][0]
check(
    'atrium: 10 x 10 plate with one 3 x 3 hole',
    len(sp['p']['holes']) == 1
    and sp['p']['pts'][2] == [5.0, 5.0]
    and sp['p']['holes'][0] == [[-2.0, -2.0], [1.0, -2.0], [1.0, 1.0], [-2.0, 1.0]],
    sp['p'],
)
check('the group and materials survived', sp['grp'] == 'blok' and sp['mat'] == 'mat_concrete', sp)
txt, d = assistant('add_atrium', {'group': 'blok', 'cell_from': 'A1', 'cell_to': 'B2'}, drawing=d)
check('an atrium no slab covers is refused', txt.startswith('refused'), txt)

txt, d = assistant('add_object', {'kind': 'slab_poly', 'cell': 'A1', 'params': {'pts': SQUARE, 't': 0.3}})
check('add_object knows slab_poly', d.objs[-1]['kind'] == 'slab_poly' and d.objs[-1]['p']['t'] == 0.3, txt)
check('rail lists the kind', rail_has(['slab_poly']) == [], rail_has(['slab_poly']))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'slab_poly', 'p': {'pts': SQUARE, 't': 0.22, 'holes': []}},
    {'kind': 'slab_poly', 'p': {'pts': SQUARE, 't': 0.22, 'holes': HOLE}},
    {'kind': 'slab_poly', 'p': {'pts': [[-4.5, -4.5], [4.5, -4.5], [4.5, 2], [0, 4.5], [-4.5, 2]], 't': 0.3}},
]
b = browser_kinds(cases)
plain, holed, poly = b
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'square slab_poly builds 6 x 0.22 x 4',
    plain['ok']
    and abs(plain['size'][0] - 6.0) < 1e-3
    and abs(plain['size'][1] - 0.22) < 1e-3
    and abs(plain['size'][2] - 4.0) < 1e-3,
    plain,
)
check('bottom sits at y=0', abs(plain['min'][1]) < 1e-3, plain)
check(
    'the hole version still builds, same size and more triangles',
    holed['ok']
    and abs(holed['size'][0] - 6.0) < 1e-3
    and abs(holed['size'][2] - 4.0) < 1e-3
    and holed['tris'] > plain['tris'],
    (plain['tris'], holed),
)
check(
    'a 5-corner pentagon plate builds 9 x 0.3 x 9',
    poly['ok']
    and abs(poly['size'][0] - 9.0) < 1e-3
    and abs(poly['size'][1] - 0.3) < 1e-3
    and abs(poly['size'][2] - 9.0) < 1e-3,
    poly,
)
check('label', plain['label'] == 'Polygon slab', plain['label'])

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds([cases[0]])
check('blender builds slab_poly', bl.get('slab_poly', {}).get('polys', 0) > 0, bl.get('slab_poly'))
blh = blender_kinds([cases[1]])
check('blender builds slab_poly with a hole', blh.get('slab_poly', {}).get('polys', 0) > 0, blh.get('slab_poly'))
finish()
