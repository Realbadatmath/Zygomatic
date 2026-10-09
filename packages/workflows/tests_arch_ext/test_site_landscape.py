# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_site_landscape.py — the site_landscape family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_site_landscape.py

Three engines must agree: the assistant's tools produce the records claimed, the
tab builds every kind at the size its parameters say, and Blender meshes it.

2026-09-07 — THE GROUND. Nothing here lands at y = 0 any more. A slope drawn with
the terrain family's add_slope is the fixture: six trees on it get six different
heights, a fence chain running down it leans and descends, a car park on it is
refused, a flower bed on it is sheared onto the plane (gz = 0.1). The shear is
proved in BOTH engines: a draped slab is exactly as much taller in Blender as it
is in the tab.
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

NEW_KINDS = [
    'fence',
    'hedge',
    'tree_conifer',
    'tree_deciduous',
    'tree_palm',
    'shrub',
    'flowerbed',
    'lamp_post',
    'bench',
    'bin',
    'kerb',
    'sidewalk',
    'parking_bay',
    'road_curved',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(
        t in names
        for t in (
            'plant_trees',
            'add_fence',
            'add_parking',
            'add_road',
            'add_curved_road',
            'add_street_furniture',
            'add_garden_bed',
        )
    ),
    names,
)

# C10..N21 is 12 x 12 cells = 12 x 12 m; at 6 m that is a 3 x 3 grid.
# (2026-09-08: trees and lamp posts are REAL pack models by default — these
# checks ask for model='parametric' to prove the placeholder geometry; the real
# path is proven in test_design_rules.py.)
txt, d = assistant(
    'plant_trees',
    {
        'model': 'parametric',
        'cell_from': 'C10',
        'cell_to': 'N21',
        'spacing': 6,
        'jitter': 0,
        'kind': 'tree_deciduous',
        'height': 7,
    },
)
check('12x12 block at 6 m spacing = 9 trees', kinds_of(d).get('tree_deciduous') == 9, (txt, kinds_of(d)))
check('trees are 7 m with a 2.94 m crown', d.objs[0]['p'] == {'h': 7, 'r_can': 2.94, 'r_trunk': 0.25}, d.objs[0]['p'])
pos_a = [(o['x'], o['z']) for o in d.objs]
check(
    'grid is 6 m apart and inside the block',
    abs(pos_a[1][0] - pos_a[0][0] - 6) < 1e-6 and abs(pos_a[3][1] - pos_a[0][1] - 6) < 1e-6,
    pos_a[:4],
)

txt, d2 = assistant(
    'plant_trees',
    {
        'model': 'parametric',
        'cell_from': 'C10',
        'cell_to': 'N21',
        'count': 12,
        'seed': 7,
        'kind': 'tree_conifer',
        'height': 8,
    },
)
txt3, d3 = assistant(
    'plant_trees',
    {
        'model': 'parametric',
        'cell_from': 'C10',
        'cell_to': 'N21',
        'count': 12,
        'seed': 7,
        'kind': 'tree_conifer',
        'height': 8,
    },
)
p2 = [(o['x'], o['z']) for o in d2.objs]
p3 = [(o['x'], o['z']) for o in d3.objs]
check('count places 12 trees', len(p2) == 12 and kinds_of(d2).get('tree_conifer') == 12, txt)
check('same seed twice = identical positions', p2 == p3, (p2[:3], p3[:3]))
check('...and they are not all the same point', len(set(p2)) == 12, p2[:3])
# twelve 12 m conifers (6 m crowns) need ~280 m2: a 12 x 12 block is refused
# by the crowding rule (2026-09-08), so this scatter gets an 18 x 18 block
txt, dj = assistant(
    'plant_trees',
    {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'N21', 'count': 12, 'seed': 8, 'kind': 'tree_conifer'},
)
check(
    '12 default conifers in 12 x 12 m are refused for crowding, naming a bigger block',
    txt.startswith('refused') and 'cells' in txt,
    txt[:120],
)
txt, dj = assistant(
    'plant_trees',
    {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'T27', 'count': 12, 'seed': 8, 'kind': 'tree_conifer'},
)
check('a different seed moves them', [(o['x'], o['z']) for o in dj.objs] != p2)
check('a conifer with no height asked for gets a real 12 m one', dj.objs[0]['p']['h'] == 12, dj.objs[0]['p'])
txt, _ = assistant('plant_trees', {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'N21', 'kind': 'oak'})
check('unknown tree kind refused', txt.startswith('refused'), txt)

# R7 — real sizes are absolute
txt, _ = assistant(
    'plant_trees', {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'N21', 'kind': 'tree_conifer', 'height': 4}
)
check('a 4 m conifer is refused, with the real range', txt.startswith('refused') and '8-25 m' in txt, txt)
txt, _ = assistant(
    'plant_trees', {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'N21', 'kind': 'tree_deciduous', 'height': 25}
)
check('a 25 m deciduous tree is refused (6-20 m)', txt.startswith('refused') and '6-20 m' in txt, txt)
txt, _ = assistant(
    'plant_trees', {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'N21', 'kind': 'tree_palm', 'height': 30}
)
check('a 30 m palm is refused (5-15 m)', txt.startswith('refused') and '5-15 m' in txt, txt)
txt, dbig = assistant(
    'plant_trees',
    {'model': 'parametric', 'cell_from': 'C10', 'cell_to': 'E12', 'count': 1, 'kind': 'tree_deciduous', 'height': 20},
)
check('a 20 m tree keeps its crown inside the real 3-8 m', dbig.objs[-1]['p']['r_can'] == 4.0, dbig.objs[-1]['p'])

txt, d = assistant('add_fence', {'cells': ['B4', 'B20', 'R20'], 'kind': 'fence', 'height': 1.8}, drawing=d)
f = [o for o in d.objs if o['kind'] == 'fence']
check('3 cells = 2 fence segments', len(f) == 2 and kinds_of(d).get('fence') == 2, txt)
check('segments are 16 m long and 1.8 m high', abs(f[0]['p']['len'] - 16) < 1e-6 and f[0]['p']['h'] == 1.8, f[0]['p'])
check('a 16 m fence gets 7 posts (2.5 m spacing)', f[0]['p']['posts'] == 7, f[0]['p'])
check(
    'B4->B20 runs north-south (ry 90 deg), B20->R20 east-west (ry 0)',
    abs(abs(f[0]['ry']) - 1.5707963) < 1e-4 and abs(f[1]['ry']) < 1e-6,
    (f[0]['ry'], f[1]['ry']),
)
check(
    'on flat ground a fence is level: y 0, no lean',
    all(o['y'] == 0.0 and o['rz'] == 0.0 for o in f),
    [(o['y'], o['rz']) for o in f],
)
txt, _ = assistant('add_fence', {'cells': ['B4']})
check('one cell refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_fence', {'cells': ['B4', 'B20'], 'kind': 'wall'})
check('bad fence kind refused', txt.startswith('refused'), txt)

# F30..O39 is 10 x 10 m: 4 bays across x 2 rows deep = 8.
txt, dp = assistant('add_parking', {'cell_from': 'F30', 'cell_to': 'O39', 'bay_w': 2.5, 'bay_d': 5, 'direction': 'x'})
check('10x10 m, 2.5 x 5 bays along x = 8 bays', kinds_of(dp).get('parking_bay') == 8, (txt, kinds_of(dp)))
check(
    'bays carry their size, a flat ground plane and storey 0',
    dp.objs[0]['p'] == {'w': 2.5, 'd': 5.0, 't': 0.02, 'gx': 0.0, 'gz': 0.0} and dp.objs[0]['y'] == 0.0,
    dp.objs[0],
)
check('the count is in the result text', '8 parking bays' in txt, txt)
txt, _ = assistant('add_parking', {'cell_from': 'F30', 'cell_to': 'G31', 'bay_w': 2.5, 'bay_d': 5})
check('a block too small for one bay is refused', txt.startswith('refused'), txt)

txt, d = assistant('add_road', {'cells': ['A25', 'Z25', 'Z40'], 'width': 6}, drawing=d)
r = [o for o in d.objs if o['kind'] == 'road']
check('3 cells = 2 road pieces, 6 m wide', len(r) == 2 and r[0]['p']['w'] == 6, txt)
txt, d = assistant(
    'add_curved_road', {'centre': 'AB25', 'radius': 12, 'start_deg': 0, 'end_deg': 90, 'width': 6}, drawing=d
)
rc = d.objs[-1]
check(
    'one curved road record', rc['kind'] == 'road_curved' and rc['p']['r'] == 12 and rc['p']['w'] == 6, (txt, rc['p'])
)
check('on flat ground it is not tilted', rc['rx'] == 0.0 and rc['rz'] == 0.0 and rc['y'] == 0.0, rc)
txt, _ = assistant('add_curved_road', {'centre': 'AB25', 'radius': 2, 'width': 6})
check('a road wider than the bend is refused', txt.startswith('refused'), txt)

# 2026-09-11: row 26 is 1 m off the centreline of the 6 m road laid above, and a
# lamp post in the carriageway is now refused — these three stand on row 21, 4 m off.
txt, d = assistant(
    'add_street_furniture', {'model': 'parametric', 'cells': ['D21', 'J21', 'P21'], 'kind': 'lamp_post'}, drawing=d
)
check('3 lamp posts', kinds_of(d).get('lamp_post') == 3 and d.objs[-1]['p']['h'] == 4, txt)
txt, d = assistant(
    'add_street_furniture', {'model': 'parametric', 'cells': ['G26'], 'kind': 'bench', 'rotation_deg': 90}, drawing=d
)
check('a bench turned 90 degrees', d.objs[-1]['kind'] == 'bench' and abs(d.objs[-1]['ry'] - 1.5707963) < 1e-4, txt)
txt, _ = assistant('add_street_furniture', {'model': 'parametric', 'cells': ['G26'], 'kind': 'statue'})
check('unknown furniture refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_street_furniture', {'model': 'parametric', 'cells': ['G26'], 'kind': 'lamp_post', 'height': 9})
check('a 9 m lamp post is refused (3-6 m)', txt.startswith('refused') and '3-6 m' in txt, txt)

txt, dg = assistant('add_garden_bed', {'cell_from': 'E12', 'cell_to': 'K13', 'kind': 'flowerbed'})
check(
    'flower bed sized to the block (7 x 2 m)',
    dg.objs[-1]['kind'] == 'flowerbed' and dg.objs[-1]['p']['w'] == 7.0 and dg.objs[-1]['p']['d'] == 2.0,
    (txt, dg.objs[-1]['p']),
)
check(
    'on flat ground the bed is flat (gx = gz = 0)',
    dg.objs[-1]['p']['gx'] == 0.0 and dg.objs[-1]['p']['gz'] == 0.0,
    dg.objs[-1]['p'],
)
txt, dg = assistant('add_garden_bed', {'cell_from': 'E12', 'cell_to': 'K13', 'kind': 'hedge'}, drawing=dg)
check(
    'hedge runs along the longer side',
    dg.objs[-1]['kind'] == 'hedge' and dg.objs[-1]['p']['len'] == 7.0 and dg.objs[-1]['ry'] == 0.0,
    (txt, dg.objs[-1]['p']),
)
txt, dg = assistant('add_garden_bed', {'cell_from': 'E12', 'cell_to': 'K13', 'kind': 'shrubs'}, drawing=dg)
check('shrubs on a 1.5 m grid = 4 x 1', kinds_of(dg).get('shrub') == 4, (txt, kinds_of(dg)))
txt, _ = assistant('add_garden_bed', {'cell_from': 'E12', 'cell_to': 'K13', 'kind': 'lawn'})
check('unknown bed kind refused', txt.startswith('refused'), txt)

txt, d = assistant('add_object', {'kind': 'road_curved', 'cell': 'A1', 'params': {'r': 8}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'road_curved' and d.objs[-1]['p']['r'] == 8, txt)
check('rail lists every new kind', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
import zyg_workflows.arch_assistant_ext.site_landscape as SL  # noqa: E402

check(
    'the PROMPT is one paragraph under 1100 chars and says the rule',
    len(SL.PROMPT) <= 1100
    and '\n' not in SL.PROMPT
    and 'site things land on the ground under them' in SL.PROMPT.lower(),
    len(SL.PROMPT),
)
check(
    'nothing in this family is GROUND (it stands on it)',
    not any(k in A.EXT_HEIGHTS for k in NEW_KINDS),
    [k for k in NEW_KINDS if k in A.EXT_HEIGHTS],
)

# ── the ground (2026-09-07) ───────────────────────────────────────────────────
# A 40 x 100 m slope climbing 10 m to the south: gz = +0.10 everywhere on it.
print('ground')
txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'AN100', 'height': 10, 'direction': 'z'})
check('fixture: a 10 m rise over 100 m is drawn', g.objs[-1]['kind'] == 'slope', txt)
y0, glx, glz, spread = A.ground_plane(g, -130.5, -100.0, 8, 8, 0.0)
check(
    'fixture: the ground there is planar and falls 10% along z',
    abs(glz - 0.1) < 1e-6 and abs(glx) < 1e-9 and spread < 1e-6,
    (y0, glx, glz, spread),
)

# R5 — six trees, six heights, each exactly the ground under its own trunk
txt, g = assistant(
    'plant_trees',
    {
        'model': 'parametric',
        'cell_from': 'C40',
        'cell_to': 'P60',
        'count': 6,
        'seed': 3,
        'kind': 'tree_conifer',
        'height': 14,
    },
    drawing=g,
)
tr = [o for o in g.objs if o['kind'] == 'tree_conifer']
check(
    'R5: six trees on the slope get six DIFFERENT heights',
    len(tr) == 6 and len({o['y'] for o in tr}) == 6,
    [o['y'] for o in tr],
)
check(
    'R5: every tree y IS the ground under its own x/z',
    all(abs(o['y'] - A.ground_height(g, o['x'], o['z'])) < 1e-3 for o in tr),
    [(o['y'], round(A.ground_height(g, o['x'], o['z']), 4)) for o in tr],
)
check('R5: trees stay vertical (no rx/rz)', all(o['rx'] == 0.0 and o['rz'] == 0.0 for o in tr))
check('the reply says the ground range', ' on the ground under it (y ' in txt, txt)
txt, gb = assistant(
    'plant_trees',
    {
        'model': 'parametric',
        'cell_from': 'C40',
        'cell_to': 'P60',
        'count': 3,
        'seed': 3,
        'kind': 'tree_conifer',
        'height': 14,
        'base_height': 0,
    },
    drawing=g,
)
check('base_height overrides the ground', all(o['y'] == 0.0 for o in gb.objs[-3:]), [o['y'] for o in gb.objs[-3:]])

# R5 — street furniture
txt, g = assistant(
    'add_street_furniture', {'model': 'parametric', 'cells': ['J20', 'J60', 'J95'], 'kind': 'lamp_post'}, drawing=g
)
lp = [o for o in g.objs if o['kind'] == 'lamp_post']
check(
    'R5: three lamp posts up the slope stand at three ground heights',
    len({o['y'] for o in lp}) == 3 and all(abs(o['y'] - A.ground_height(g, o['x'], o['z'])) < 1e-3 for o in lp),
    [o['y'] for o in lp],
)

# R4 — a fence chain running DOWN the slope
txt, g = assistant('add_fence', {'cells': ['C90', 'C80', 'C70'], 'kind': 'fence'}, drawing=g)
fs = [o for o in g.objs if o['kind'] == 'fence']
check('R4: the 3-cell chain is still 2 segments on a 10% slope', len(fs) == 2, txt)
check('R4: running downhill gives rz < 0', all(o['rz'] < -0.05 for o in fs), [o['rz'] for o in fs])
check(
    'R4: rz is atan of the fall over the run',
    all(abs(o['rz'] + math.atan(0.1)) < 1e-4 for o in fs),
    [o['rz'] for o in fs],
)
check('R4: the ys descend down the slope', fs[0]['y'] > fs[1]['y'], [o['y'] for o in fs])
check(
    'R4: each segment sits at the ground under its own centre',
    all(abs(o['y'] - A.ground_height(g, o['x'], o['z'])) < 1e-3 for o in fs),
    [o['y'] for o in fs],
)
check('the reply says how far it drops', 'dropping 1.0 m down the ground' in txt, txt)

# R4 — a steep leg is cut into 5 m pieces (a second slope, 5 m over 20 m = 25 %)
txt, gs = assistant('add_slope', {'cell_from': 'A150', 'cell_to': 'T169', 'height': 5, 'direction': 'z'})
txt, gs = assistant('add_fence', {'cells': ['C169', 'C150'], 'kind': 'fence'}, drawing=gs)
sp = [o for o in gs.objs if o['kind'] == 'fence']
check(
    'R4: a 19 m leg on a 25% slope is cut into 4 pieces of 5 m or less',
    len(sp) == 4 and all(o['p']['len'] <= 5.0 + 1e-6 for o in sp),
    (txt, [o['p']['len'] for o in sp]),
)
check(
    'R4: every piece sits at its own ground height, all different',
    len({o['y'] for o in sp}) == 4 and all(abs(o['y'] - A.ground_height(gs, o['x'], o['z'])) < 1e-3 for o in sp),
    [o['y'] for o in sp],
)
check('the reply says it was cut up', 'cut into 5 m pieces' in txt, txt)

# R4 — a road piece
txt, g = assistant('add_road', {'cells': ['P90', 'P70'], 'width': 6}, drawing=g)
rd = [o for o in g.objs if o['kind'] == 'road']
check(
    'R4: a road piece leans down the slope and sits on the ground',
    len(rd) == 1 and rd[0]['rz'] < -0.05 and abs(rd[0]['y'] - A.ground_height(g, rd[0]['x'], rd[0]['z'])) < 1e-3,
    (txt, rd[0]['rz'], rd[0]['y']),
)

# the arc: y at the centre point + a record tilt (an arc cannot be sheared as a quad)
txt, g = assistant('add_curved_road', {'centre': 'T50', 'radius': 12, 'width': 6}, drawing=g)
ar = g.objs[-1]
want_rx, want_rz = A.ground_tilt(0.0, 0.1)
check(
    'R2/arc: the arc takes the ground height at its centre',
    abs(ar['y'] - A.ground_height(g, ar['x'], ar['z'])) < 1e-3,
    (txt, ar['y']),
)
check(
    'R2/arc: it is laid on the ground plane with rx = -atan(0.1), rz = 0',
    abs(ar['rx'] - want_rx) < 1e-3 and abs(ar['rz'] - want_rz) < 1e-3,
    (ar['rx'], ar['rz'], want_rx, want_rz),
)

# R2 — the car park refuses the slope, and tilts on ground it accepts
txt, _ = assistant('add_parking', {'cell_from': 'F40', 'cell_to': 'O49', 'bay_w': 2.5, 'bay_d': 5}, drawing=g)
check(
    'R2: a car park on a 10% slope is refused, and says flatten_pad',
    txt.startswith('refused') and 'flatten_pad first' in txt and 'near-level' in txt,
    txt,
)
txt, gp = assistant('add_slope', {'cell_from': 'A200', 'cell_to': 'T249', 'height': 2.5, 'direction': 'z'})
txt, gp = assistant(
    'add_parking', {'cell_from': 'F210', 'cell_to': 'O219', 'bay_w': 2.5, 'bay_d': 5, 'direction': 'x'}, drawing=gp
)
bays = [o for o in gp.objs if o['kind'] == 'parking_bay']
check('R2: on a 5% slope the park is laid — 8 bays', len(bays) == 8, txt)
check(
    'R2: every bay carries the ground plane (gz = 0.05) and stays upright',
    all(
        abs(o['p']['gz'] - 0.05) < 1e-3 and abs(o['p']['gx']) < 1e-6 and o['rx'] == 0.0 and o['rz'] == 0.0 for o in bays
    ),
    [bays[0]['p'], bays[0]['rx'], bays[0]['rz']],
)
check(
    'R2: the bays sit at the ground under themselves, at several heights',
    len({o['y'] for o in bays}) > 1 and all(abs(o['y'] - A.ground_height(gp, o['x'], o['z'])) < 1e-3 for o in bays),
    [o['y'] for o in bays],
)
txt, gz2 = assistant(
    'add_parking',
    {'cell_from': 'F210', 'cell_to': 'O219', 'bay_w': 2.5, 'bay_d': 5, 'direction': 'z'},
    drawing=A.Drawing({'objects': [dict(gp.objs[0])]}),
)
bz = [o for o in gz2.objs if o['kind'] == 'parking_bay']
# Turned 90 deg the bay's local +x points at world -z, so the ground that RISES
# along +z FALLS along the bay's own x: gx = -0.05, and its z is now level.
check(
    'R2: turned bays get the slope in their OWN frame (gx = -0.05, gz = 0)',
    abs(bz[0]['p']['gx'] + 0.05) < 1e-3 and abs(bz[0]['p']['gz']) < 1e-6,
    bz[0]['p'],
)


def _corner_lands(o, d):
    """Every corner of a sheared slab is at the real ground under that corner."""
    c, s = math.cos(o['ry']), math.sin(o['ry'])
    w, dd = o['p'].get('w', o['p'].get('len', 0)), o['p'].get('d', o['p'].get('w', 0))
    for lx in (-w / 2, w / 2):
        for lz in (-dd / 2, dd / 2):
            wx, wz = o['x'] + lx * c + lz * s, o['z'] - lx * s + lz * c
            if abs(o['y'] + o['p']['gx'] * lx + o['p']['gz'] * lz - A.ground_height(d, wx, wz)) > 1e-3:
                return False
    return True


check(
    'R2: the sheared bay puts all four corners ON the ground, turned or not',
    _corner_lands(bays[0], gp) and _corner_lands(bz[0], gz2),
    [bays[0]['p'], bz[0]['p']],
)

# R2 — the garden bed
txt, gd = assistant(
    'add_garden_bed',
    {'cell_from': 'E40', 'cell_to': 'K41', 'kind': 'flowerbed'},
    drawing=A.Drawing({'objects': [dict(g.objs[0])]}),
)
bed = gd.objs[-1]
check(
    'R2: a bed on the slope carries gz == 0.1 and gx == 0',
    bed['p']['gz'] == 0.1 and bed['p']['gx'] == 0.0,
    (txt, bed['p']),
)
check(
    'R2: the bed record stays upright and sits at the plane height',
    bed['rx'] == 0.0 and bed['rz'] == 0.0 and abs(bed['y'] - A.ground_height(gd, bed['x'], bed['z'])) < 1e-3,
    (bed['y'], bed['rx'], bed['rz']),
)
txt, gh = assistant('add_hill', {'centre': 'P200', 'radius': 14, 'height': 6})
txt, gh = assistant('add_garden_bed', {'cell_from': 'J194', 'cell_to': 'W207', 'kind': 'flowerbed'}, drawing=gh)
tiles = [o for o in gh.objs if o['kind'] == 'flowerbed']
check('R2: a bed over a hill is TILED into one record per tile', len(tiles) > 1 and len(tiles) <= 64, (txt, len(tiles)))
check('R2: the reply says how many tiles', 'tiles over the ground' in txt, txt)
check(
    'R2: every tile sits on the ground under it',
    all(abs(o['y'] - A.ground_height(gh, o['x'], o['z'])) < 1.0 for o in tiles),
    [o['y'] for o in tiles],
)
txt, gsh = assistant(
    'add_garden_bed',
    {'cell_from': 'E40', 'cell_to': 'K45', 'kind': 'shrubs'},
    drawing=A.Drawing({'objects': [dict(g.objs[0])]}),
)
sh = [o for o in gsh.objs if o['kind'] == 'shrub']
check(
    'R2: shrubs stand UPRIGHT, each at the ground under it, at several heights',
    len(sh) >= 4
    and len({o['y'] for o in sh}) > 1
    and all(
        o['rx'] == 0.0 and o['rz'] == 0.0 and abs(o['y'] - A.ground_height(gsh, o['x'], o['z'])) < 1e-3 for o in sh
    ),
    [(o['y'], o['rx'], o['rz']) for o in sh[:4]],
)
txt, ghd = assistant(
    'add_garden_bed',
    {'cell_from': 'E40', 'cell_to': 'F60', 'kind': 'hedge'},
    drawing=A.Drawing({'objects': [dict(g.objs[0])]}),
)
hd = ghd.objs[-1]
check(
    'R4: a bed hedge running up the slope leans with it',
    hd['kind'] == 'hedge'
    and abs(hd['rz'] - math.atan(0.1)) < 1e-3
    and abs(hd['y'] - A.ground_height(ghd, hd['x'], hd['z'])) < 1e-3,
    (txt, hd['rz'], hd['y']),
)

# ── site defaults (2026-09-11, live job 94f5813b) ─────────────────────────────
# The operator's own 20-storey tower came back with six 5.0 m lamp posts under a
# 4.2 m porte-cochere soffit — two of them 1.4 m in front of the plate beside a
# canopy column — and four of them inside the 8 m drive. Three rules now hold:
# nothing stands under a canopy (or within 1 m of its edge), a lamp within 6 m of
# one is clamped to 0.5 m under the soffit, and nothing stands in a carriageway.
print('site defaults')
import zyg_workflows.arch_assistant_ext.site_landscape as SL2  # noqa: E402

txt, sd = assistant('draw_box', {'cell_from': 'A50', 'cell_to': 'T69', 'storeys': 3, 'name': 'tower'})
txt, sd = assistant(
    'add_canopy', {'group': 'tower', 'side': 'south', 'width': 14, 'depth': 5, 'height': 4.2, 'columns': 4}, drawing=sd
)
check(
    'fixture: a 14 x 5 m porte-cochere with a 4.2 m soffit on 4 columns',
    'soffit at y 4.2 m' in txt and len([o for o in sd.objs if o['kind'] == 'column_round']) == 4,
    txt,
)
txt, sd = assistant('add_road', {'cells': ['J95', 'J76'], 'width': 8}, drawing=sd)
check('fixture: an 8 m drive up the axis to the canopy', '8 m carriageway' in txt, txt)

# the footprint the rules are measured against: p.w along the facade, p.d out
# from it, so the plate covers x -147..-133, z -80.88..-75.88
cnp, fp = SL2._canopies(sd)[0]
cols = [o for o in sd.objs if o['kind'] == 'column_round']
check(
    'the canopy footprint is 14 x 5 m out from the wall face',
    abs(fp['w'] - 14) < 1e-9 and abs(fp['d'] - 5) < 1e-9 and abs(fp['ox']) < 1e-6 and abs(fp['oz'] - 1) < 1e-6,
    (fp['w'], fp['d'], fp['ox'], fp['oz']),
)
check(
    'all 4 canopy columns stand INSIDE the footprint, 0.35 m in from its outer edge',
    all(SL2._canopy_dist(fp, c['x'], c['z']) == 0.0 for c in cols)
    and all(abs((c['z'] - fp['z']) - (fp['d'] - 0.35)) < 1e-6 for c in cols),
    [(c['id'], round(SL2._canopy_dist(fp, c['x'], c['z']), 3), round(c['z'] - fp['z'], 3)) for c in cols],
)

# 1) nothing under the plate. D75/E75 are 0.38 m in front of the outer edge (the
# nearest a 1 m cell grid comes to it) and E73 is under the plate itself.
txt, _ = assistant('add_street_furniture', {'cells': ['D75', 'E75'], 'kind': 'lamp_post', 'height': 5}, drawing=sd)
check(
    'lamps in front of the canopy inside its width are refused, naming the cells and where to move them',
    txt.startswith('refused') and 'D75' in txt and 'E75' in txt and 'D75 -> D76' in txt and 'E75 -> E76' in txt,
    txt,
)
txt, _ = assistant('add_street_furniture', {'cells': ['E73'], 'kind': 'lamp_post', 'height': 5}, drawing=sd)
check(
    'a lamp UNDER the plate is refused too, and the soffit is in the reason',
    txt.startswith('refused') and 'soffit 4.2 m' in txt,
    txt,
)

# 2) 1.5 m outside the width and 2.4 m in front of the outer edge: 2.8 m from the
# footprint, so inside the 6 m band -> the 5 m lamp is clamped to 3.7 m.
txt, sc = assistant('add_street_furniture', {'cells': ['B77', 'S77'], 'kind': 'lamp_post', 'height': 5}, drawing=sd)
near = [o for o in sc.objs if o['kind'] == 'asset']
check('lamps beside the canopy are placed, not refused', len(near) == 2 and not txt.startswith('refused'), txt)
check(
    '...their real height s x p.bh is 3.70 m, not 5 m',
    all(abs(o['s'] * o['p']['bh'] - 3.7) < 0.02 for o in near),
    [(o['s'], o['p']['bh'], round(o['s'] * o['p']['bh'], 3)) for o in near],
)
check('...and the reply says why', 'lamp height 5 m clamped to 3.7 m: the canopy soffit is 4.2 m' in txt, txt)

# 3) the carriageway
txt, _ = assistant('add_street_furniture', {'cells': ['J85'], 'kind': 'lamp_post', 'height': 5}, drawing=sd)
check(
    'a lamp on the road centreline is refused, naming the 4.50 m offset to use',
    txt.startswith('refused') and 'carriageway' in txt and 'offset of 4.50 m' in txt,
    txt,
)
txt, _ = assistant(
    'plant_trees',
    {'model': 'parametric', 'cell_from': 'F80', 'cell_to': 'N90', 'spacing': 6, 'kind': 'tree_deciduous', 'height': 7},
    drawing=sd,
)
check(
    'a tree line across the drive is refused by the same rule',
    txt.startswith('refused') and 'carriageway' in txt and 'offset of 4.50 m' in txt,
    txt,
)

# 4) far enough away, nothing is changed: S87 is 12.5 m from the plate and 9 m
# off the centreline
txt, sf = assistant('add_street_furniture', {'cells': ['S87'], 'kind': 'lamp_post', 'height': 5}, drawing=sd)
far = sf.objs[-1]
check(
    'a lamp 12 m clear of the canopy keeps the 5 m it was asked for',
    not txt.startswith('refused') and abs(far['s'] * far['p']['bh'] - 5.0) < 0.02 and 'clamped' not in txt,
    (txt, round(far['s'] * far['p']['bh'], 3)),
)
txt, sg = assistant('add_street_furniture', {'cells': ['S87'], 'kind': 'lamp_post'}, drawing=sd)
check(
    'a lamp with no height asked for is 4 m now, not 4.5',
    abs(sg.objs[-1]['s'] * sg.objs[-1]['p']['bh'] - 4.0) < 0.02,
    round(sg.objs[-1]['s'] * sg.objs[-1]['p']['bh'], 3),
)
txt, sp0 = assistant('add_street_furniture', {'model': 'parametric', 'cells': ['S87'], 'kind': 'lamp_post'}, drawing=sd)
check('...the placeholder pole is 4 m too', sp0.objs[-1]['p']['h'] == 4.0, sp0.objs[-1]['p'])
txt, sb = assistant('add_street_furniture', {'cells': ['E75'], 'kind': 'bench'}, drawing=sd)
check(
    'a bench is not a lamp post: the canopy rule leaves it alone',
    sb.objs[-1]['kind'] == 'bench' and not txt.startswith('refused'),
    txt,
)

# the tool descriptions carry the rules
sfd = [t for t, _ in SL2.TOOLS if t['name'] == 'add_street_furniture'][0]['description']
ptd = [t for t, _ in SL2.TOOLS if t['name'] == 'plant_trees'][0]['description']
check(
    'add_street_furniture says the canopy, soffit and carriageway rules',
    'canopy' in sfd and 'soffit' in sfd and 'carriageway' in sfd and '4 m by default' in sfd,
    sfd[:120],
)
check('plant_trees says the carriageway rule', 'carriageway' in ptd, ptd[:120])

# the live drawing the rules came from: job 94f5813b, 336 records
LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')
if os.path.exists(LIVE):
    import json

    live = A.Drawing(json.load(open(LIVE)))
    check('live fixture: job 94f5813b has 336 records', len(live.objs) == 336, len(live.objs))
    lf = SL2._canopies(live)[0][1]
    lr = SL2._roads(live)[0][1]
    lamps = [o for o in live.objs if 'lamp post' in str(o.get('name', ''))]
    check(
        'live: all 6 lamp posts were built 5.0 m tall under a 4.2 m soffit',
        len(lamps) == 6 and all(abs(o['s'] * o['p']['bh'] - 5.0) < 0.01 for o in lamps) and lf['soffit'] == 4.2,
        [(o['id'], round(o['s'] * o['p']['bh'], 2)) for o in lamps],
    )
    check(
        'live: two of them stand 1.38 m in front of the canopy, all six inside the 6 m band',
        sorted(round(SL2._canopy_dist(lf, o['x'], o['z']), 2) for o in lamps)[:2] == [1.38, 1.38],
        [round(SL2._canopy_dist(lf, o['x'], o['z']), 2) for o in lamps],
    )
    check(
        'live: three of them stand 4.0 m from the centreline of the 8 m drive — inside it',
        sum(1 for o in lamps if SL2._road_dist(lr, o['x'], o['z']) < lr['w'] / 2 + SL2.ROAD_CLEAR) == 3,
        [round(SL2._road_dist(lr, o['x'], o['z']), 2) for o in lamps],
    )
    cells = [A.cell_of(o['x'], o['z']) for o in lamps]
    pts = [(o['x'], o['z']) for o in lamps]
    check(
        'live: asked for again, the drive lamps are refused',
        SL2._carriageway_refusal(live, cells, pts, 'lamp post').startswith('refused'),
        SL2._carriageway_refusal(live, cells, pts, 'lamp post'),
    )
    check(
        'live: and the ones that survive are capped at 3.7 m',
        SL2._soffit_cap(live, pts) == (3.7, 4.2),
        SL2._soffit_cap(live, pts),
    )
else:
    check('live fixture present', False, LIVE)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
FLAT_BED = {'w': 3, 'd': 1.5, 't': 0.15, 'gx': 0, 'gz': 0}
BED_GX = {'w': 3, 'd': 1.5, 't': 0.15, 'gx': 0.4, 'gz': 0}
BED_GZ = {'w': 3, 'd': 1.5, 't': 0.15, 'gx': 0, 'gz': 0.5}
BAY_GZ = {'w': 2.5, 'd': 5, 't': 0.02, 'gx': 0, 'gz': 0.3}
cases = [
    {'kind': 'fence', 'p': {'len': 5, 'h': 1.2, 'posts': 3, 'rails': 3, 't': 0.04}},
    {'kind': 'hedge', 'p': {'len': 5, 'h': 1.2, 'w': 0.6}},
    {'kind': 'tree_conifer', 'p': {'h': 8, 'r': 2}},
    {'kind': 'tree_deciduous', 'p': {'h': 7, 'r_can': 3, 'r_trunk': 0.25}},
    {'kind': 'tree_palm', 'p': {'h': 7, 'fronds': 7}},
    {'kind': 'shrub', 'p': {'r': 0.6, 'h': 0.8}},
    {'kind': 'flowerbed', 'p': FLAT_BED},
    {'kind': 'lamp_post', 'p': {'h': 4, 'r': 0.06}},
    {'kind': 'bench', 'p': {'len': 1.8, 'h': 0.45}},
    {'kind': 'bin', 'p': {'r': 0.25, 'h': 0.9}},
    {'kind': 'kerb', 'p': {'len': 5, 'h': 0.12, 'w': 0.15}},
    {'kind': 'sidewalk', 'p': {'len': 10, 'w': 2, 't': 0.06, 'gx': 0, 'gz': 0}},
    {'kind': 'parking_bay', 'p': {'w': 2.5, 'd': 5, 't': 0.02, 'gx': 0, 'gz': 0}},
    {'kind': 'road_curved', 'p': {'r': 10, 'a0': 0, 'a1': 90, 'w': 6, 't': 0.08, 'seg': 24}},
]
b = browser_kinds(cases)
by = {x['kind']: x for x in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind builds real geometry',
    all(x['ok'] and x['registered'] for x in b),
    [(x['kind'], x['ok'], x['registered'], x['err']) for x in b if not (x['ok'] and x['registered'])],
)


def sized(kind, want, tol=0.06):
    x = by.get(kind) or {}
    s = x.get('size') or [0, 0, 0]
    ok = all(abs(s[i] - want[i]) < tol for i in range(3))
    check(f'{kind} is {want[0]:g} x {want[1]:g} x {want[2]:g} m', ok, (s, x.get('err')))


sized('fence', [5.04, 1.2, 0.04])
sized('hedge', [5.0, 1.2, 0.6])
sized('tree_conifer', [4.0, 8.0, 4.0])  # h 8, r 2 -> 4 x 8 x 4
sized('tree_deciduous', [6.0, 7.0, 6.0])
sized('shrub', [1.2, 0.8, 1.2])
sized('flowerbed', [3.0, 0.15, 1.5])
sized('lamp_post', [0.36, 4.0, 0.36])
sized('bench', [1.8, 0.45, 0.45])
sized('bin', [0.5, 0.9, 0.5])
sized('kerb', [5.0, 0.12, 0.15])
sized('sidewalk', [10.0, 0.06, 2.0])
sized('parking_bay', [2.5, 0.02, 5.0])
pal = by.get('tree_palm', {}).get('size') or [0, 0, 0]
check('tree_palm is 7 m tall and its fronds spread 3-6 m', abs(pal[1] - 7.0) < 0.06 and 3.0 < pal[0] < 6.0, pal)
rcv = by.get('road_curved', {})
check(
    'road_curved r 10 w 6 quarter turn spans 13 m in x and z, 0.08 thick',
    abs((rcv.get('size') or [0, 0, 0])[0] - 13.0) < 0.08
    and abs((rcv.get('size') or [0, 0, 0])[2] - 13.0) < 0.08
    and abs((rcv.get('size') or [0, 0, 0])[1] - 0.08) < 1e-3,
    rcv.get('size'),
)
check(
    'road_curved sits in the north-east quadrant (+x / -z)',
    (rcv.get('min') or [9, 9, 9])[0] > -0.01 and (rcv.get('min') or [0, 0, 0])[2] < -12.9,
    rcv.get('min'),
)
check(
    'labels',
    by['tree_conifer']['label'] == 'Conifer'
    and by['parking_bay']['label'] == 'Parking bay'
    and by['sidewalk']['label'] == 'Pavement',
    [by[k]['label'] for k in ('tree_conifer', 'parking_bay', 'sidewalk')],
)

# the shear: gx/gz drape the slab, they do NOT change its plan footprint
drape_cases = [
    {'kind': 'flowerbed', 'p': BED_GX},
    {'kind': 'flowerbed', 'p': BED_GZ},
    {'kind': 'parking_bay', 'p': BAY_GZ},
    {
        'kind': 'road_curved',
        'p': {'r': 10, 'a0': 0, 'a1': 90, 'w': 6, 't': 0.08, 'seg': 24},
        'rx': A.ground_tilt(0.0, 0.1)[0],
    },
]
db = browser_kinds(drape_cases)
bed_gx, bed_gz, bay_gz, arc_rx = db[0], db[1], db[2], db[3]
WANT_BED_GX = 0.15 + 3 * 0.4  # 1.35 m: the 3 m run rises 0.4 per metre
WANT_BED_GZ = 0.15 + 1.5 * 0.5  # 0.90 m
WANT_BAY_GZ = 0.02 + 5 * 0.3  # 1.52 m
check(
    'tab: gx 0.4 lifts the 3 m bed to %.2f m and keeps its 3 x 1.5 m plan' % WANT_BED_GX,
    abs(bed_gx['size'][1] - WANT_BED_GX) < 0.02
    and abs(bed_gx['size'][0] - 3) < 0.02
    and abs(bed_gx['size'][2] - 1.5) < 0.02,
    bed_gx['size'],
)
check(
    'tab: gz 0.5 lifts the 1.5 m bed to %.2f m' % WANT_BED_GZ,
    abs(bed_gz['size'][1] - WANT_BED_GZ) < 0.02,
    bed_gz['size'],
)
check(
    'tab: gz 0.3 lifts the 5 m bay to %.2f m, markings and all' % WANT_BAY_GZ,
    abs(bay_gz['size'][1] - WANT_BAY_GZ) < 0.02 and bay_gz['parts'] == 4,
    (bay_gz['size'], bay_gz['parts']),
)
WANT_ARC = 13.0 * math.sin(math.atan(0.1))
check(
    'tab: an rx tilt lifts the 13 m arc by about %.2f m' % WANT_ARC,
    abs(arc_rx['size'][1] - (WANT_ARC + 0.08 * math.cos(math.atan(0.1)))) < 0.06,
    arc_rx['size'],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
missing = [k for k in NEW_KINDS if bl.get(k, {}).get('polys', 0) <= 0]
check('blender meshes every kind with faces', not missing, {k: bl.get(k) for k in missing} or bl.get('_info'))
check(
    'blender tree_conifer is a trunk + a cone', bl.get('tree_conifer', {}).get('polys', 0) > 20, bl.get('tree_conifer')
)
check('blender road_curved is a real arc', bl.get('road_curved', {}).get('polys', 0) >= 4 * 8, bl.get('road_curved'))
check('blender fence has posts and rails', bl.get('fence', {}).get('polys', 0) >= 6 * 5, bl.get('fence'))

# the same shear, the same numbers, in the other engine
bd = blender_kinds([{'kind': 'flowerbed', 'p': BED_GX}])['flowerbed']
check(
    'blender: gx 0.4 gives the SAME %.2f m as the tab, plan untouched' % WANT_BED_GX,
    abs(bd['size'][1] - bed_gx['size'][1]) < 0.02 and abs(bd['size'][0] - 3) < 0.02 and abs(bd['size'][2] - 1.5) < 0.02,
    (bd['size'], bed_gx['size']),
)
bd = blender_kinds([{'kind': 'flowerbed', 'p': BED_GZ}])['flowerbed']
check(
    'blender: gz 0.5 gives the SAME %.2f m as the tab' % WANT_BED_GZ,
    abs(bd['size'][1] - bed_gz['size'][1]) < 0.02,
    (bd['size'], bed_gz['size']),
)
bd = blender_kinds([{'kind': 'parking_bay', 'p': BAY_GZ}])['parking_bay']
check(
    'blender: the draped bay is the SAME %.2f m as the tab' % WANT_BAY_GZ,
    abs(bd['size'][1] - bay_gz['size'][1]) < 0.02,
    (bd['size'], bay_gz['size']),
)
bd = blender_kinds([drape_cases[3]])['road_curved']
check(
    'blender: the rx-tilted arc is the SAME height as the tab',
    abs(bd['size'][1] - arc_rx['size'][1]) < 0.06,
    (bd['size'], arc_rx['size']),
)
finish()
# re-verified 2026-09-07 after the ground seam
