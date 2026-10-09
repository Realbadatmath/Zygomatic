# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_cliffs_rocks.py — the cliffs_rocks family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_cliffs_rocks.py

Three engines have to agree about the same six kinds. Five of them are shaped
by a noise formula written out three times (JS, Blender, Python), so the test
evaluates the Python copy and asserts the tab's bounding boxes match it — if
the copies ever drift the rock silently changes shape.

Since 2026-09-07 it also proves the GROUND seam for this family: every tool
lands its record on the ground under it, a cliff/scree chain steps down a
falling run, a rock field drapes over the slope in tiles, the four ground kinds
export HEIGHTS whose maximum IS the tab's bounding-box height, and the real
sizes of R7 (boulder 0.3-4 m across, cliff 3-60 m, escarpment 3-80 m) are
refused outside their range.
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
from zyg_workflows.arch_assistant_ext.cliffs_rocks import (
    PROMPT,
    KINDS,
    HEIGHTS,
    cliff_z_size,
    boulder_bbox,  # noqa: E402
    rock_field_bbox,
    sea_stack_bbox,
    field_radius,
    field_is_stone,
)

NEW_KINDS = ['cliff', 'escarpment', 'boulder', 'rock_field', 'scree', 'sea_stack']

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(
        t in names
        for t in ('add_cliff', 'add_escarpment', 'add_boulder', 'scatter_rocks', 'add_scree', 'add_sea_stack')
    ),
    names,
)
check('prompt is one paragraph under 1100 chars', 0 < len(PROMPT) <= 1100 and '\n' not in PROMPT, len(PROMPT))
check('prompt says the drop is on the left', 'on your left' in PROMPT, PROMPT[:120])
check('prompt explains base_height', 'base_height' in PROMPT, PROMPT[:120])
check(
    'prompt says everything lands on the ground under it and base_height overrides',
    'lands on the ground under it' in PROMPT and 'base_height overrides' in PROMPT,
    PROMPT[:200],
)
check(
    'prompt says a cliff line is drawn ON the plateau edge',
    'plateau edge' in PROMPT and 'draw the plateau' in PROMPT,
    PROMPT[:400],
)
check('prompt gives the real ranges', '3-60' in PROMPT and '3-80' in PROMPT and '0.3-4' in PROMPT, PROMPT)

# add_cliff: 3 cells -> 2 records, turned so the face is on the left of the walk
txt, d = assistant('add_cliff', {'cells': ['E10', 'E16', 'J16'], 'height': 20, 'depth': 14})
cl = [o for o in d.objs if o['kind'] == 'cliff']
check('3 cells give 2 cliffs', kinds_of(d).get('cliff') == 2 and cl[0]['id'] in txt, txt)
check(
    '...6 m and 5 m long, 20 m tall, 14 m deep',
    abs(cl[0]['p']['len'] - 6) < 1e-6
    and abs(cl[1]['p']['len'] - 5) < 1e-6
    and cl[0]['p']['h'] == 20
    and cl[0]['p']['d'] == 14,
    [o['p'] for o in cl],
)
check(
    'ry puts the face on the left of the walk',
    abs(cl[0]['ry'] - (-math.pi / 2)) < 1e-6 and abs(cl[1]['ry']) < 1e-6,
    [o['ry'] for o in cl],
)
check('cliffs sit on the ground in a group', cl[0]['y'] == 0.0 and cl[0]['grp'] == 'cliffs', cl[0])
check(
    'a chain never climbs onto itself at the corner (both cliffs at 0)',
    cl[1]['y'] == 0.0 and cl[1]['rz'] == 0.0,
    [(o['y'], o['rz']) for o in cl],
)

txt, d = assistant('add_cliff', {'cells': ['H5', 'H12'], 'height': 12, 'base_height': 4}, drawing=d)
check('base_height lifts the cliff onto a plateau', d.objs[-1]['y'] == 4.0 and d.objs[-1]['p']['h'] == 12, txt)
txt, d = assistant('add_cliff', {'cells': ['E10', 'E16'], 'height': 0}, drawing=d)
check('zero height refused', txt.startswith('refused'), txt)
txt, d = assistant('add_cliff', {'cells': ['E10', 'E16'], 'height': 61}, drawing=d)
check('R7: a cliff over 60 m is refused with the real range', txt.startswith('refused') and '3 to 60' in txt, txt)
txt, d = assistant('add_cliff', {'cells': ['E10', 'E16'], 'height': 2}, drawing=d)
check('R7: a cliff under 3 m is refused with the real range', txt.startswith('refused') and '3 to 60' in txt, txt)
txt, d = assistant('add_cliff', {'cells': ['E10', 'E16'], 'depth': 0.5}, drawing=d)
check('depth under 1 m refused', txt.startswith('refused'), txt)
txt, d = assistant('add_cliff', {'cells': ['E10']}, drawing=d)
check('one cell refused', txt.startswith('refused'), txt)

# ── R1/R4/R5: the ground seam, on a slope drawn with the terrain tool ─────────
g = A.Drawing({'objects': []})
txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 10, 'direction': 'z'}, drawing=g)
sl = g.objs[-1]
check(
    'a 20 x 20 m slope rising 10 m southward is the ground to stand on',
    sl['kind'] == 'slope' and abs(A.ground_height(g, sl['x'], sl['z']) - 5.0) < 1e-6,
    txt,
)

txt, g = assistant('add_cliff', {'cells': ['E5', 'E15'], 'height': 20}, drawing=g)
cf = g.objs[-1]
check(
    'R4: the cliff sits at the ground under its reach CENTRE (4.75 m), not at 0',
    abs(cf['y'] - 4.75) < 1e-4,
    (txt, cf['y']),
)
check(
    'R4: rz = atan(rise / run) so the cliff steps with the slope',
    abs(cf['rz'] - math.atan2(5.0, 10.0)) < 1e-5 and 'over 10 m' in txt,
    (cf['rz'], txt),
)

txt, g = assistant('add_scree', {'cells': ['E5', 'E15'], 'height': 6}, drawing=g)
sr = g.objs[-1]
check(
    'scree lies at the cliff FOOT (same ground), never on its 20 m ledge',
    abs(sr['y'] - 4.75) < 1e-4 and abs(sr['rz'] - cf['rz']) < 1e-5,
    (txt, sr['y']),
)

txt, g = assistant('add_boulder', {'centre': 'E10', 'size': 2}, drawing=g)
check(
    'R5 + HEIGHTS: a boulder on the cliff edge stands on the cliff TOP (4.75 + 20)',
    abs(g.objs[-1]['y'] - 24.75) < 1e-3,
    (txt, g.objs[-1]['y']),
)
txt, g = assistant('add_sea_stack', {'centre': 'B3', 'radius': 4, 'height': 20}, drawing=g)
check(
    'R5: a sea stack lands on the ground, not at 0',
    g.objs[-1]['y'] > 0.5 and g.objs[-1]['rx'] == 0.0 and g.objs[-1]['rz'] == 0.0,
    (txt, g.objs[-1]['y']),
)

# add_escarpment: the block D20..K23 is 8 (x) by 4 (z)
txt, d = assistant(
    'add_escarpment', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 15, 'direction': 'north'}, drawing=d
)
en = d.objs[-1]
check(
    'escarpment north: 8 m of face, 4 m back, unturned, 1 m grass ledge',
    en['kind'] == 'escarpment'
    and en['p']['len'] == 8
    and en['p']['d'] == 4
    and en['ry'] == 0.0
    and en['p']['h'] == 15
    and en['p']['ledge'] == 1.0,
    (txt, en['p'], en['ry']),
)
txt, d = assistant(
    'add_escarpment', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 15, 'direction': 'east'}, drawing=d
)
ee = d.objs[-1]
check(
    'escarpment east: 4 m of face, 8 m back, turned -90 deg',
    ee['p']['len'] == 4 and ee['p']['d'] == 8 and abs(ee['ry'] - (-math.pi / 2)) < 1e-6,
    (txt, ee['p'], ee['ry']),
)
txt, d = assistant('add_escarpment', {'cell_from': 'D20', 'cell_to': 'K23', 'direction': 'up'}, drawing=d)
check('bad direction refused', txt.startswith('refused'), txt)
txt, d = assistant('add_escarpment', {'cell_from': 'D20', 'cell_to': 'K23', 'height': -3}, drawing=d)
check('negative height refused', txt.startswith('refused'), txt)
txt, d = assistant('add_escarpment', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 90}, drawing=d)
check('R7: an escarpment over 80 m is refused with the real range', txt.startswith('refused') and '3 to 80' in txt, txt)

# add_boulder / scatter_rocks — R7: size is the DIAMETER now
txt, d = assistant('add_boulder', {'centre': 'P30', 'size': 2.5, 'base_height': 3}, drawing=d)
bo = d.objs[-1]
check(
    'R7: add_boulder size 2.5 is 2.5 m ACROSS (record radius 1.25) at 3 m',
    bo['kind'] == 'boulder' and bo['p']['r'] == 1.25 and bo['y'] == 3.0 and bo['id'] in txt,
    (txt, bo['p']),
)
txt, d = assistant('add_boulder', {'centre': 'P30', 'size': 0.05}, drawing=d)
check('R7: under 0.3 m across refused', txt.startswith('refused') and '0.3 to 4' in txt, txt)
txt, d = assistant('add_boulder', {'centre': 'P30', 'size': 6}, drawing=d)
check(
    'R7: over 4 m across refused as a rock outcrop',
    txt.startswith('refused') and 'rock outcrop' in txt and 'add_sea_stack' in txt,
    txt,
)

f = A.Drawing({'objects': []})  # bare ground: d already holds two escarpments on D20..K23
txt, f = assistant('scatter_rocks', {'cell_from': 'D20', 'cell_to': 'K23', 'count': 40}, drawing=f)
rf = f.objs[-1]
check(
    'scatter_rocks lays ONE 8x4 field of 40 rocks, flat ground: gx = gz = 0, no tiling',
    rf['kind'] == 'rock_field'
    and rf['p']['w'] == 8
    and rf['p']['d'] == 4
    and rf['p']['count'] == 40
    and rf['p']['gx'] == 0
    and rf['p']['gz'] == 0
    and len(f.objs) == 1
    and rf['y'] == 0.0,
    (txt, rf['p']),
)
txt, d = assistant('scatter_rocks', {'cell_from': 'D20', 'cell_to': 'K23', 'count': 500}, drawing=d)
check('more than 400 rocks refused', txt.startswith('refused'), txt)
txt, d = assistant('scatter_rocks', {'cell_from': 'D20', 'cell_to': 'K23', 'size': 6}, drawing=d)
check(
    'R7: a rock field whose largest boulder is over 4 m is refused',
    txt.startswith('refused') and '0.3 to 4' in txt,
    txt,
)

# M5..T12 is bare slope — clear of the cliff, the scree and the sea stack drawn above
txt, g = assistant('scatter_rocks', {'cell_from': 'M5', 'cell_to': 'T12', 'count': 40}, drawing=g)
dr = [o for o in g.objs if o['kind'] == 'rock_field'][-1]
check(
    'R2: on the 1:2 slope the field drapes — gz = 0.5, gx = 0, record NOT rotated',
    abs(dr['p']['gz'] - 0.5) < 1e-4
    and abs(dr['p']['gx']) < 1e-6
    and dr['rx'] == 0.0
    and dr['rz'] == 0.0
    and dr['y'] > 0.5,
    (txt, dr['p'], dr['y']),
)

h = A.Drawing({'objects': []})
txt, h = assistant('add_hill', {'centre': 'M13', 'radius': 30, 'height': 20}, drawing=h)
# C3..U18 sits off-centre on the hill, so no two tiles are mirror images
txt, h = assistant('scatter_rocks', {'cell_from': 'C3', 'cell_to': 'U18', 'count': 60}, drawing=h)
tiles = [o for o in h.objs if o['kind'] == 'rock_field']
check(
    'R2: a 19 x 16 m field over a 20 m hill is TILED, in ONE group, keeping all 60 rocks',
    len(tiles) > 1
    and 'tile' in txt
    and len({o['grp'] for o in tiles}) == 1
    and sum(o['p']['count'] for o in tiles) == 60,
    (txt, len(tiles)),
)
check(
    'R2: each tile has its own plane and its own seat on the hill',
    len({(o['p']['gx'], o['p']['gz']) for o in tiles}) == len(tiles)
    and len({o['y'] for o in tiles}) == len(tiles)
    and all(o['y'] > 0 for o in tiles),
    [(o['y'], o['p']['gx'], o['p']['gz']) for o in tiles],
)

# add_scree: one per pair, leaning the same way as the cliff
txt, d = assistant('add_scree', {'cells': ['E10', 'E16'], 'height': 6, 'width': 12}, drawing=d)
sc = d.objs[-1]
check(
    'add_scree drew one 6 m pile 6 m tall spreading 12 m',
    sc['kind'] == 'scree' and abs(sc['p']['len'] - 6) < 1e-6 and sc['p']['h'] == 6 and sc['p']['w'] == 12,
    (txt, sc['p']),
)
check('scree leans the same way as the cliff', abs(sc['ry'] - (-math.pi / 2)) < 1e-6, sc['ry'])
txt, d = assistant('add_scree', {'cells': ['E10']}, drawing=d)
check('scree with one cell refused', txt.startswith('refused'), txt)
txt, d = assistant('add_scree', {'cells': ['E10', 'E16'], 'height': 0}, drawing=d)
check('scree with no height refused with its range', txt.startswith('refused') and '0.5 to 40' in txt, txt)

# add_sea_stack
txt, d = assistant('add_sea_stack', {'centre': 'B20', 'radius': 6, 'height': 30}, drawing=d)
ss = d.objs[-1]
check(
    'add_sea_stack stood one 12 m x 30 m column',
    ss['kind'] == 'sea_stack' and ss['p']['r'] == 6 and ss['p']['h'] == 30 and ss['mat'] == 'mat_rock',
    (txt, ss['p']),
)
txt, d = assistant('add_sea_stack', {'centre': 'B20', 'height': 0}, drawing=d)
check('sea stack with no height refused', txt.startswith('refused'), txt)

# add_object must accept the new kinds
txt, d = assistant('add_object', {'kind': 'boulder', 'cell': 'A1', 'params': {'r': 3, 'seg': 16}}, drawing=d)
check('add_object knows boulder', d.objs[-1]['kind'] == 'boulder' and d.objs[-1]['p']['r'] == 3, txt)
txt, d = assistant('add_object', {'kind': 'sea_stack', 'cell': 'A1', 'params': {'r': 4, 'h': 18}}, drawing=d)
check('add_object knows sea_stack', d.objs[-1]['kind'] == 'sea_stack' and d.objs[-1]['p']['h'] == 18, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all six', sorted(KINDS) == sorted(NEW_KINDS), sorted(KINDS))
check(
    'KINDS carries the new params (escarpment ledge, rock_field gx/gz)',
    KINDS['escarpment'].get('ledge') == 1 and KINDS['rock_field'].get('gx') == 0 and KINDS['rock_field'].get('gz') == 0,
    (KINDS['escarpment'], KINDS['rock_field']),
)
check('the seam loaded HEIGHTS for all six kinds', all(k in A.EXT_HEIGHTS for k in NEW_KINDS), sorted(A.EXT_HEIGHTS))
check(
    'R6: you do not stand on loose rock — boulder and rock_field return None',
    HEIGHTS['boulder']({'r': 2}, 0, 0) is None and HEIGHTS['rock_field']({'w': 9, 'd': 9}, 0, 0) is None,
)

# R7 arithmetic: the field's `size` is its LARGEST boulder's DIAMETER
big = max(2 * field_radius(n, 3.0, 1) for n in range(40))
old = max(
    2 * 3.0 * (0.5 + (lambda v: v - math.floor(v))(math.sin(n * 127.1 + 3 * 311.7 + 1 * 74.7) * 43758.5453))
    for n in range(40)
)
check(
    'R7: a size-3 field tops out at 3 m across (the old formula gave %.1f m)' % old,
    big <= 3.0 + 1e-9 and big > 2.7 and old > 8.0,
    (big, old),
)
check(
    'R7: and its smallest boulder is still 0.4 x size',
    min(2 * field_radius(n, 3.0, 1) for n in range(40)) >= 3.0 * 0.4 - 1e-9,
    min(2 * field_radius(n, 3.0, 1) for n in range(40)),
)
check(
    'a field is not one grey: about 30 % of the boulders are mat_stone',
    0.15 < sum(field_is_stone(n, 1) for n in range(200)) / 200.0 < 0.45,
    sum(field_is_stone(n, 1) for n in range(200)),
)

# ── the sculpted ground (v3): cliff and escarpment step THE GROUND ────────────
# With a `ground` record in the drawing add_cliff / add_escarpment stop standing
# a solid on the land and sculpt the land itself, one `sculpt_step` per pair.
# Everything loose — boulders, rock fields, scree, sea stacks — stays a solid.
print('sculpted ground')


def sculpted():
    """A drawing whose only record is a v3 ground, with the noise switched off so
    a height reading is the sculpt's own contribution and nothing else."""
    dd = A.Drawing({'objects': []})
    A.call_tool(dd, 'make_ground', {'cell_from': 'C4', 'cell_to': 'CV200', 'style': 'flat'})
    for o in dd.objs:
        if o['kind'] == 'ground':
            o['p']['amp'] = 0.0
    return dd


def walk_frame(c0, c1):
    """(mid x, mid z, left x, left z, length) for the walk from cell c0 to c1."""
    x0, z0 = A.cell_centre(*A.parse_cell(c0))
    x1, z1 = A.cell_centre(*A.parse_cell(c1))
    ln = math.hypot(x1 - x0, z1 - z0)
    return (x0 + x1) / 2, (z0 + z1) / 2, (z1 - z0) / ln, -(x1 - x0) / ln, ln


s = sculpted()
check(
    'the fixture is one v3 ground and it reads flat',
    kinds_of(s) == {'ground': 1} and abs(A.ground_height(s, -145.5, -140.5)) < 1e-9,
    kinds_of(s),
)

txt, s = assistant('add_cliff', {'cells': ['E10', 'E20'], 'height': 15, 'depth': 10, 'ruggedness': 0}, drawing=s)
st = s.objs[-1]
check(
    'a cliff on a sculpted ground is a sculpt_step, NOT a cliff solid',
    kinds_of(s) == {'ground': 1, 'sculpt_step': 1} and st['id'] in txt and 'not a solid on it' in txt,
    (txt, kinds_of(s)),
)
check(
    'the step is len = run + feather, d = 2 x depth, the ruggedness carried, seated at 0',
    st['p']['len'] == 12.5
    and st['p']['d'] == 20.0
    and st['p']['feather'] == 2.5
    and st['p']['h'] == 15.0
    and st['p']['rug'] == 0.0
    and st['y'] == 0.0
    and st['mat'] == 'mat_rock'
    and st['grp'] == 'cliffs',
    (st['p'], st['y'], st['grp']),
)
check(
    'ry turns the OLD solid cliff by pi, so the HIGH ground is on the walk LEFT',
    abs(st['ry'] - math.pi / 2) < 1e-6 and abs(((st['ry'] - (-math.pi / 2)) % (2 * math.pi)) - math.pi) < 1e-6,
    st['ry'],
)

mx, mz, lx, lz, run = walk_frame('E10', 'E20')


def across(dd, t):
    return round(A.ground_height(dd, mx + lx * t, mz + lz * t), 3)


check(
    'the ground itself steps: 0 on your right, 15 m on your left',
    across(s, -4) == 0.0
    and across(s, -1) < 0.05
    and across(s, 1) == 15.0
    and across(s, 3) == 15.0
    and across(s, 5) == 15.0,
    [(t, across(s, t)) for t in (-4, -1, 1, 3, 5)],
)
check(
    'the lifted bench runs back exactly `depth` (10 m) and the land beyond is untouched',
    across(s, 8) > 10.0 and across(s, 9.9) < 0.2 and across(s, 10.5) == 0.0 and across(s, 20) == 0.0,
    [(t, across(s, t)) for t in (8, 9.9, 10.5, 20)],
)

c = sculpted()
txt, c = assistant('add_cliff', {'cells': ['E10', 'E20', 'E30'], 'height': 15, 'depth': 10, 'ruggedness': 0}, drawing=c)
jx, jz = A.cell_centre(*A.parse_cell('E20'))
z10 = A.cell_centre(*A.parse_cell('E10'))[1]
along = [round(A.ground_height(c, jx + 3, z10 + 3 + i * 0.5), 4) for i in range(29)]
check(
    '3 cells give 2 steps in one group, 20 m of face',
    kinds_of(c) == {'ground': 1, 'sculpt_step': 2}
    and '20.0 m of rock face' in txt
    and len({o['grp'] for o in c.objs if o['kind'] == 'sculpt_step'}) == 1,
    (txt, kinds_of(c)),
)
check(
    'R: raises ADD, so a straight chain reads exactly 15 m over the joint — never 30',
    A.ground_height(c, jx + 3, jz) == 15.0 and max(along) == 15.0 and min(along) == 15.0,
    (A.ground_height(c, jx + 3, jz), min(along), max(along)),
)
check(
    '...and the fall side of the joint is still 0',
    A.ground_height(c, jx - 3, jz) == 0.0,
    A.ground_height(c, jx - 3, jz),
)

for args, why in (
    (({'cells': ['E10'], 'height': 15}), 'one cell'),
    (({'cells': ['E10', 'E10'], 'height': 15}), 'the same cell twice'),
    (({'cells': ['E10', 'E20'], 'height': 61}), 'over 60 m'),
    (({'cells': ['E10', 'E20'], 'height': 15, 'depth': 0.5}), 'under 1 m deep'),
):
    t, _ = assistant('add_cliff', args, drawing=sculpted())
    check('the sculpt path still refuses %s' % why, t.startswith('refused'), t)

e = sculpted()
txt, e = assistant(
    'add_escarpment',
    {'cell_from': 'D20', 'cell_to': 'K30', 'height': 20, 'direction': 'north', 'ruggedness': 0},
    drawing=e,
)
es = e.objs[-1]
exmin, ezmin, exmax, ezmax = A.block_bounds('D20', 'K30')
ecx = (exmin + exmax) / 2
check(
    'an escarpment on a sculpted ground is ONE sculpt_step with a feather the whole depth',
    kinds_of(e) == {'ground': 1, 'sculpt_step': 1}
    and es['p']['feather'] == 11.0
    and es['p']['d'] == 22.0
    and es['p']['len'] == 30.0
    and es['p']['h'] == 20.0
    and es['ry'] == 0.0
    and es['y'] == 0.0
    and es['z'] == ezmin,
    (txt, es['p'], es['z']),
)


def behind(q):
    return round(A.ground_height(e, ecx, ezmin + q), 3)


check(
    'R: the escarpment face is at the block edge — nothing lifted in front of it',
    behind(-2) == 0.0 and behind(-6) == 0.0,
    [(q, behind(q)) for q in (-2, -6)],
)
check(
    'R: and behind it the land falls from 20 m at the face to 0 over the whole 11 m depth',
    behind(1) > 19.0
    and behind(3) < behind(1)
    and behind(8) < behind(5) < behind(3)
    and behind(11) == 0.0
    and behind(13) == 0.0,
    [(q, behind(q)) for q in (1, 3, 5, 8, 11, 13)],
)
ew = sculpted()
txt, ew = assistant(
    'add_escarpment', {'cell_from': 'D20', 'cell_to': 'K30', 'height': 20, 'direction': 'east'}, drawing=ew
)
check(
    'escarpment east swaps the face and the depth and turns -90 deg',
    ew.objs[-1]['p']['len'] == 27.0
    and ew.objs[-1]['p']['d'] == 16.0
    and ew.objs[-1]['p']['feather'] == 8.0
    and abs(ew.objs[-1]['ry'] - (-math.pi / 2)) < 1e-6,
    (ew.objs[-1]['p'], ew.objs[-1]['ry']),
)

r = sculpted()
for tool, args in (
    ('add_boulder', {'centre': 'E10', 'size': 2}),
    ('scatter_rocks', {'cell_from': 'D20', 'cell_to': 'K23', 'count': 40}),
    ('add_scree', {'cells': ['E10', 'E16'], 'height': 6}),
    ('add_sea_stack', {'centre': 'B20', 'radius': 4, 'height': 20}),
):
    txt, r = assistant(tool, args, drawing=r)
check(
    'loose rock is still loose: boulder, rock_field, scree and sea_stack stay SOLIDS',
    kinds_of(r) == {'ground': 1, 'boulder': 1, 'rock_field': 1, 'scree': 1, 'sea_stack': 1},
    kinds_of(r),
)

txt, s = assistant('add_boulder', {'centre': 'F15', 'size': 2}, drawing=s)
check(
    'a boulder on the sculpted bench asks the FULL ground and stands on it at 15 m',
    abs(s.objs[-1]['y'] - 15.0) < 1e-6,
    (txt, s.objs[-1]['y']),
)
txt, s = assistant('add_scree', {'cells': ['E10', 'E20'], 'height': 6}, drawing=s)
check(
    'scree still lies at the FOOT: the sculpted face is hidden while it is seated',
    s.objs[-1]['kind'] == 'scree' and s.objs[-1]['y'] == 0.0,
    (txt, s.objs[-1]['y']),
)

hid = sculpted()
for o in hid.objs:
    if o['kind'] == 'ground':
        o['hidden'] = True
txt, hid = assistant('add_cliff', {'cells': ['E10', 'E20'], 'height': 15}, drawing=hid)
check(
    'hide the ground and add_cliff draws the old solid cliff again',
    hid.objs[-1]['kind'] == 'cliff' and abs(hid.objs[-1]['ry'] - (-math.pi / 2)) < 1e-6,
    txt,
)
txt, hid = assistant(
    'add_escarpment', {'cell_from': 'D20', 'cell_to': 'K30', 'height': 20, 'direction': 'north'}, drawing=hid
)
check(
    '...and add_escarpment draws the old solid escarpment, grass ledge and all',
    hid.objs[-1]['kind'] == 'escarpment' and hid.objs[-1]['p']['ledge'] == 1.0,
    txt,
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
P_CLIFF = {'len': 40, 'h': 15, 'd': 12, 'rug': 0.35, 'seed': 1, 'res': 24, 'ledge': 1}
P_ESC = {'len': 60, 'h': 20, 'd': 40, 'rug': 0.3, 'seed': 1, 'res': 24, 'ledge': 1}
P_BOU = {'r': 1.5, 'rug': 0.35, 'seed': 1, 'seg': 12}
P_RF = {'w': 30, 'd': 30, 'count': 20, 'size': 1.2, 'seed': 1, 'rug': 0.35, 'gx': 0, 'gz': 0}
P_SCR = {'len': 30, 'w': 12, 'h': 6}
P_SS = {'r': 6, 'h': 25, 'rug': 0.3, 'seed': 1, 'seg': 24, 'rings': 10}
P_RF_DRAPE = dict(P_RF, gx=0.3, gz=-0.2)
TILT = math.atan2(5.0, 10.0)
cases = [
    {'kind': 'cliff', 'p': P_CLIFF},
    {'kind': 'escarpment', 'p': P_ESC},
    {'kind': 'boulder', 'p': P_BOU},
    {'kind': 'rock_field', 'p': P_RF},
    {'kind': 'scree', 'p': P_SCR},
    {'kind': 'sea_stack', 'p': P_SS},
]
extra = [{'kind': 'rock_field', 'p': P_RF_DRAPE}, {'kind': 'cliff', 'p': P_CLIFF, 'rz': TILT}]
b = browser_kinds(cases + extra)
by = {r['kind']: r for r in b[: len(cases)]}
b_drape, b_tilt = b[len(cases)], b[len(cases) + 1]
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check('every kind builds real geometry', all(r['ok'] for r in b), [(r['kind'], r['ok'], r['err']) for r in b])

cl = by['cliff']
check(
    'cliff spans 40 m along and 15 m up', abs(cl['size'][0] - 40) < 0.4 and abs(cl['size'][1] - 15) < 0.15, cl['size']
)
want = cliff_z_size(12, 0.35, 24, 1)
check(
    'cliff depth matches the Python noise within 2%%: want %.3f m' % want,
    abs(cl['size'][2] - want) <= 0.02 * want and 12 <= cl['size'][2] <= 12 + 2 * 0.35 + 0.01,
    (cl['size'], want),
)
check(
    'cliff sits on the ground and carries the grass ledge as a second part',
    abs(cl['min'][1]) < 1e-3 and cl['parts'] == 2,
    cl,
)

es = by['escarpment']
want_e = cliff_z_size(40, 0.3, 24, 1)
check(
    'escarpment is 60 x 20 and %.2f m deep' % want_e,
    abs(es['size'][0] - 60) < 0.6 and abs(es['size'][1] - 20) < 0.2 and abs(es['size'][2] - want_e) <= 0.02 * want_e,
    (es['size'], want_e),
)
check(
    'escarpment now carries a grass strip on its top edge: two parts, bbox unchanged',
    es['parts'] == 2 and abs(es['min'][1]) < 1e-3,
    (es['parts'], es['min']),
)

bo, wb = by['boulder'], boulder_bbox(1.5, 0.35, 1, 12)
check(
    'boulder bbox matches the Python noise within 2%%: want %s' % (tuple(round(v, 3) for v in wb),),
    all(abs(bo['size'][i] - wb[i]) <= 0.02 * wb[i] for i in range(3)),
    (bo['size'], wb),
)
check(
    'boulder is a 1.5 m rock roughened +/-35%',
    all(2 * 1.5 * 0.65 * 0.95 <= bo['size'][i] <= 2 * 1.5 * 1.35 * 1.05 for i in range(3)),
    bo['size'],
)
check('boulder sits on the ground (min y == 0)', abs(bo['min'][1]) < 1e-3, bo['min'])

rf, wr = by['rock_field'], rock_field_bbox(30, 30, 20, 1.2, 1, 0.35)
check(
    'rock field bbox matches the Python noise within 2%%: want %s' % (tuple(round(v, 2) for v in wr),),
    all(abs(rf['size'][i] - wr[i]) <= 0.02 * wr[i] for i in range(3)),
    (rf['size'], wr),
)
check('rock field is 20 boulders of real geometry', rf['tris'] > 20 * 30 and abs(rf['min'][1]) < 1e-3, rf)
check('rock field is two material bands (rock + the lighter mat_stone)', rf['parts'] == 2, rf['parts'])
check(
    'R7: no boulder in a size-1.2 field is over 1.2 m across x 1.35 roughness',
    rf['size'][1] <= 1.2 * 1.35 + 1e-6,
    rf['size'],
)

wd = rock_field_bbox(30, 30, 20, 1.2, 1, 0.35, 0.3, -0.2)
check(
    'R2: the draped field matches the Python prediction within 2%%: want %s' % (tuple(round(v, 2) for v in wd),),
    all(abs(b_drape['size'][i] - wd[i]) <= 0.02 * wd[i] for i in range(3)),
    (b_drape['size'], wd),
)
check(
    'R2: draping lifts the field %.1f m up the plane and leaves the PLAN size untouched — '
    'the rocks climb, the record is not rotated' % (wd[1] - wr[1]),
    b_drape['size'][1] > rf['size'][1] + 5.0
    and abs(b_drape['size'][0] - rf['size'][0]) < 0.02 * rf['size'][0]
    and abs(b_drape['size'][2] - rf['size'][2]) < 0.02 * rf['size'][2],
    (b_drape['size'], rf['size']),
)

sc = by['scree']
check(
    'scree is 30 long, 6 tall, 12 wide within 1%',
    abs(sc['size'][0] - 30) < 0.3 and abs(sc['size'][1] - 6) < 0.06 and abs(sc['size'][2] - 12) < 0.12,
    sc['size'],
)
check('scree carries its boulders as a second part', sc['parts'] == 2 and abs(sc['min'][1]) < 1e-3, sc)

ss, ws = by['sea_stack'], sea_stack_bbox(6, 25, 0.3, 1, 24, 10)
check('sea stack is exactly 25 m tall, base at 0', abs(ss['size'][1] - 25) < 1e-3 and abs(ss['min'][1]) < 1e-3, ss)
check(
    'sea stack plan size matches the Python noise within 2%%: want %.2f x %.2f' % (ws[0], ws[2]),
    abs(ss['size'][0] - ws[0]) <= 0.02 * ws[0] and abs(ss['size'][2] - ws[2]) <= 0.02 * ws[2],
    (ss['size'], ws),
)

check(
    'labels',
    [by[k]['label'] for k in NEW_KINDS] == ['Cliff', 'Escarpment', 'Boulder', 'Rock field', 'Scree slope', 'Sea stack'],
    [by[k]['label'] for k in NEW_KINDS],
)


# ── HEIGHTS agree with the tab's bounding box ────────────────────────────────
def hmax(kind, p, sx, sz, n=41):
    """The highest point of a kind's height function over the footprint the tab
    actually built (its bounding box in plan)."""
    best = None
    for j in range(n):
        for i in range(n):
            v = HEIGHTS[kind](p, -sx / 2 + i * sx / (n - 1), -sz / 2 + j * sz / (n - 1))
            if v is not None and (best is None or v > best):
                best = v
    return best


for kind, p in (('cliff', P_CLIFF), ('escarpment', P_ESC), ('scree', P_SCR), ('sea_stack', P_SS)):
    r = by[kind]
    hm = hmax(kind, p, r['size'][0], r['size'][2])
    check(
        'HEIGHTS[%s] tops out at %s m = the tab bbox height %.3f within 1%%'
        % (kind, 'None' if hm is None else round(hm, 3), r['size'][1]),
        hm is not None and abs(hm - r['size'][1]) <= 0.01 * r['size'][1],
        (hm, r['size']),
    )
check(
    'HEIGHTS say None off the footprint (a cliff 100 m to the side is not ground)',
    HEIGHTS['cliff'](P_CLIFF, 100, 0) is None
    and HEIGHTS['scree'](P_SCR, 0, 100) is None
    and HEIGHTS['sea_stack'](P_SS, 100, 100) is None,
)
check(
    'escarpment HEIGHTS fall linearly from h at the face to 0 at the back',
    abs(HEIGHTS['escarpment'](P_ESC, 0, -20) - 20) < 1e-9
    and abs(HEIGHTS['escarpment'](P_ESC, 0, 0) - 10) < 1e-9
    and abs(HEIGHTS['escarpment'](P_ESC, 0, 20)) < 1e-9,
    [HEIGHTS['escarpment'](P_ESC, 0, q) for q in (-20, 0, 20)],
)
check(
    'cliff HEIGHTS are h over the whole top, face band included',
    HEIGHTS['cliff'](P_CLIFF, 0, -6.2) == 15
    and HEIGHTS['cliff'](P_CLIFF, 0, 6) == 15
    and HEIGHTS['cliff'](P_CLIFF, 0, 6.2) is None,
    [HEIGHTS['cliff'](P_CLIFF, 0, q) for q in (-6.2, 6, 6.2)],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for k, floor in (
    ('cliff', 400),
    ('escarpment', 400),
    ('boulder', 40),
    ('rock_field', 400),
    ('scree', 100),
    ('sea_stack', 150),
):
    check('blender builds %s (> %d polys)' % (k, floor), bl.get(k, {}).get('polys', 0) > floor, bl.get(k))
for k in ('cliff', 'escarpment', 'scree', 'sea_stack'):
    check(
        'blender %s is the same height as the tab (%.2f m)' % (k, by[k]['size'][1]),
        abs(bl[k]['size'][1] - by[k]['size'][1]) < 0.03,
        (bl[k]['size'], by[k]['size']),
    )

bl2 = blender_kinds(extra)
check(
    'blender: the DRAPED rock field is the same height in both engines (%.2f m)' % b_drape['size'][1],
    abs(bl2['rock_field']['size'][1] - b_drape['size'][1]) < 0.03,
    (bl2['rock_field']['size'], b_drape['size']),
)
check(
    'blender: the rz-TILTED cliff is the same height in both engines (%.2f m)' % b_tilt['size'][1],
    abs(bl2['cliff']['size'][1] - b_tilt['size'][1]) < 0.05,
    (bl2['cliff']['size'], b_tilt['size']),
)
check(
    'a cliff tilted down a 1:2 run is taller in bbox than the flat one',
    b_tilt['size'][1] > cl['size'][1] + 5.0,
    (b_tilt['size'], cl['size']),
)
finish()
