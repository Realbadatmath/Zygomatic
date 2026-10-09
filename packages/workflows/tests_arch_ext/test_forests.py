# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_forests.py
(2026-09-08: plant_tree_line places REAL pack trees by default; the checks below ask
for model='parametric' to prove the one-object row; the real path is in test_design_rules.py.) — the forests family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_forests.py

The interesting kind is `forest`: one record holding hundreds of trees whose
positions, kinds, heights and crown sizes come out of a hash written three times
(JS, Blender, Python). So the test evaluates the Python copy and asserts

  · the tab's triangle count is EXACTLY sum(tris per tree kind) over the
    Python scatter — which can only hold if both copies place the same number
    of conifers and the same number of deciduous trees, tree for tree, and
  · the tab's bounding box is the one forest_bbox() predicts, INCLUDING the
    rise of the ground plane (gx, gz) across the footprint.

If the copies ever drift the wood silently changes shape and both numbers move.

Since 2026-09-07 it also proves the GROUND rules for this family:
  R2  a forest/orchard/undergrowth drapes on the ground plane under it (gx, gz)
      with every trunk VERTICAL, and tiles the block when that ground is not
      planar — drawn here on a real add_hill and a real add_slope.
  R4  a tree line follows the fall of its reach, but as gx along the row, never
      as an rz on the record: rz would lean every trunk downhill.
  R7  tree heights are refused outside the real ranges (deciduous 6-20 m,
      conifer 8-25, poplar 15-25, fruit 3-5, shrub 0.4-2), never scaled with the
      block, and plant_forest's `height` is the MEAN of a 0.7-1.3 spread.
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
from zyg_workflows.arch_assistant_ext import forests as F  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_KINDS = ['forest', 'tree_line', 'orchard', 'undergrowth']

# the four records the tab and Blender build, with explicit parameters
P_FOREST = {'w': 100, 'd': 100, 'density': 0.04, 'mix': 0.5, 'h': 14, 'seed': 1, 'jitter': 0.45, 'res': 0}
P_LINE = {'len': 60, 'spacing': 6, 'kind': 0, 'h': 10, 'jitter': 0.2, 'seed': 1}
P_ORCHARD = {'w': 40, 'd': 30, 'spacing': 5, 'h': 4}
P_SCRUB = {'w': 40, 'd': 40, 'count': 60, 'seed': 1, 'r': 0.8}

# the same four draped on a ground plane — the brief's forest is gx 0.2, gz 0.1
P_FOREST_G = dict(P_FOREST, gx=0.2, gz=0.1)
P_LINE_G = dict(P_LINE, gx=0.15, gz=0)
P_ORCHARD_G = dict(P_ORCHARD, gx=0.1, gz=0.05)
P_SCRUB_G = dict(P_SCRUB, gx=0.12, gz=-0.08)

# ── what the Python copy of the scatter says the tab must build ──────────────
SPOTS = F.forest_spots(
    P_FOREST['w'],
    P_FOREST['d'],
    P_FOREST['density'],
    P_FOREST['mix'],
    P_FOREST['h'],
    P_FOREST['jitter'],
    P_FOREST['seed'],
)
N_CONIFER = sum(1 for s in SPOTS if s[2])
N_DECID = len(SPOTS) - N_CONIFER
FOREST_TRIS = N_CONIFER * F.TREE_TRIS[F.CONIFER] + N_DECID * F.TREE_TRIS[F.DECIDUOUS]


def _box(items, gx=0.0, gz=0.0):
    """(sx, sy, sz) and the lowest y, from [(x, z, radius, height)] instances that
    stand VERTICALLY on the plane y = gx*x + gz*z."""
    xs, zs, ys = [], [], []
    for x, z, r, h in items:
        base = gx * x + gz * z
        xs += [x - r, x + r]
        zs += [z - r, z + r]
        ys += [base, base + h]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)), min(ys)


def forest_items(p, uniform=False):
    sp = F.forest_spots(p['w'], p['d'], p['density'], p['mix'], p['h'], p['jitter'], p['seed'])
    return [
        (x, z, F.crown_radius(F.CONIFER if con else F.DECIDUOUS, hk, 1.0 if uniform else cf), max(0.5, hk))
        for x, z, con, hk, cf in sp
    ]


def line_items(p):
    sp = F.tree_line_spots(p['len'], p['spacing'], p['h'], p['jitter'], p['seed'])
    return [(x, z, F.crown_radius(p['kind'], hk, cf), max(0.5, hk)) for x, z, hk, cf in sp]


def orchard_items(p):
    rc = min(F.ORCHARD_RC, p['h'] * 0.4)
    return [(x, z, rc, p['h']) for x, z in F.orchard_spots(p['w'], p['d'], p['spacing'])]


def scrub_items(p):
    return [(x, z, r, 1.2 * r) for x, z, r in F.undergrowth_spots(p['w'], p['d'], p['count'], p['seed'], p['r'])]


def near(got, want, tol=0.02):
    return abs(got - want) <= tol * abs(want)


def box_near(got, want, tol=0.02):
    return all(near(got[i], want[i], tol) for i in range(3))


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('plant_forest', 'plant_tree_line', 'plant_orchard', 'add_undergrowth')),
    names,
)
check('prompt is one paragraph under 1100 chars', 0 < len(F.PROMPT) <= 1100 and '\n' not in F.PROMPT, len(F.PROMPT))
check(
    'prompt says a forest is one object with hundreds of trees',
    'ONE object' in F.PROMPT and 'plant_trees' in F.PROMPT and 'bos' in F.PROMPT and 'base_height' in F.PROMPT,
    F.PROMPT[:120],
)
check(
    'prompt says a forest drapes over the ground under it and tiles over a hill',
    'drapes over the ground under it and tiles over a hill' in F.PROMPT
    and 'base_height is None by default' in F.PROMPT
    and 'vertical' in F.PROMPT,
    F.PROMPT[-260:],
)
check(
    'prompt states the real tree sizes',
    all(s in F.PROMPT for s in ('6-20', '8-25', '15-25', '3-5', '0.4-2')),
    F.PROMPT[-260:],
)
check(
    'KINDS declares gx and gz on all four kinds',
    all('gx' in F.KINDS[k] and 'gz' in F.KINDS[k] for k in NEW_KINDS),
    F.KINDS,
)
check(
    'a wood is NOT ground: forests exports no HEIGHTS',
    not getattr(F, 'HEIGHTS', None) and 'forest' not in A.EXT_HEIGHTS,
    sorted(A.EXT_HEIGHTS),
)

# plant_forest on flat ground — A1..CV100 is exactly 100 x 100 m
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100'})
fo = d.objs[-1]
check(
    'plant_forest drew ONE forest record for the whole wood',
    kinds_of(d) == {'forest': 1} and fo['p']['w'] == 100 and fo['p']['d'] == 100,
    (txt, fo['p']),
)
check(
    '...default density 0.04, mixed (mix 0.5), 14 m trees, seed 1, jitter 0.45',
    fo['p']['density'] == 0.04
    and fo['p']['mix'] == 0.5
    and fo['p']['h'] == 14
    and fo['p']['seed'] == 1
    and fo['p']['jitter'] == 0.45
    and fo['p']['res'] == 0,
    fo['p'],
)
check(
    '...reports 400 trees and the 5.0 m spacing, with the id and the group',
    '400' in txt and '5.0 m apart' in txt and fo['id'] in txt and fo['grp'] == 'forest',
    txt,
)
check(
    '...sits on the ground, foliage material, unturned',
    fo['y'] == 0.0 and fo['mat'] == 'mat_foliage' and fo['ry'] == 0.0,
    fo,
)
check(
    '...flat ground means a flat plane: gx = gz = 0, and no record tilt',
    fo['p']['gx'] == 0 and fo['p']['gz'] == 0 and fo['rx'] == 0.0 and fo['rz'] == 0.0,
    fo,
)
check('forest_count agrees with the text', F.forest_count(100, 100, 0.04) == 400, F.forest_count(100, 100, 0.04))

txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'mix': 'conifer'}, drawing=d)
check("mix 'conifer' is mix 1.0", d.objs[-1]['p']['mix'] == 1.0, txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'mix': 'deciduous'}, drawing=d)
check("mix 'deciduous' is mix 0.0", d.objs[-1]['p']['mix'] == 0.0, txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'base_height': 3}, drawing=d)
check('base_height 3 stands the forest on a plateau', d.objs[-1]['y'] == 3.0 and '3 m' in txt, (txt, d.objs[-1]['y']))
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'mix': 'birch'}, drawing=d)
check('unknown mix refused', txt.startswith('refused'), txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'density': 0.5}, drawing=d)
check(
    'density giving 5000 trees refused, and it says how to fix it',
    txt.startswith('refused') and '5000' in txt and '3000' in txt and 'density' in txt,
    txt,
)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'density': 0}, drawing=d)
check('zero density refused', txt.startswith('refused'), txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'ZZZ9'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)

# R7 — the real ranges, quoted in the refusal
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 3}, drawing=d)
check(
    'R7 a 3 m mean is not a wood: refused, and it names the real ranges',
    txt.startswith('refused') and '6-20' in txt and '8-25' in txt,
    txt,
)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 30}, drawing=d)
check('R7 a 30 m mean refused (no 38 m trees beside a 32 m mountain)', txt.startswith('refused') and '8-20' in txt, txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'mix': 'conifer', 'height': 7}, drawing=d)
check('R7 a 7 m conifer wood refused: conifers are 8-25 m', txt.startswith('refused') and '8-25' in txt, txt)
txt, d = assistant('plant_forest', {'cell_from': 'A1', 'cell_to': 'CV100', 'mix': 'conifer', 'height': 24}, drawing=d)
check('R7 a 24 m conifer wood is allowed', not txt.startswith('refused') and d.objs[-1]['p']['h'] == 24, txt)
check(
    'R7 the mean spreads 0.7-1.3, so no tree of a 20 m wood passes 26 m',
    (F.SPREAD_LO, F.SPREAD_HI) == (0.7, 1.3)
    and max(s[3] for s in F.forest_spots(100, 100, 0.04, 0.5, 20, 0.45, 1)) <= 20 * 1.3 + 1e-9,
    max(s[3] for s in F.forest_spots(100, 100, 0.04, 0.5, 20, 0.45, 1)),
)

# ── R2: the ground under the wood ────────────────────────────────────────────
# a real slope drawn by the terrain family: 100 x 100 m rising 10 m along +z
dg = A.Drawing({'objects': []})
txt, dg = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 10, 'direction': 'z'}, drawing=dg)
check('the terrain family drew the slope this family will stand on', dg.objs[-1]['kind'] == 'slope', txt)
n0 = len(dg.objs)
txt, dg = assistant(
    'plant_forest',
    {'cell_from': 'T20', 'cell_to': 'BS70', 'density': 0.02, 'mix': 'deciduous', 'height': 14},
    drawing=dg,
)
sl = dg.objs[n0:]
check('R2 a planar slope needs no tiles: ONE forest record', len(sl) == 1, (txt, len(sl)))
r0 = sl[0]
check(
    "R2 ...carrying the slope's own gradient (gz 0.1 along +z, gx 0)",
    abs(r0['p']['gz'] - 0.1) < 1e-3 and abs(r0['p']['gx']) < 1e-6,
    r0['p'],
)
check(
    'R2 ...with y at the ground height under its centre',
    abs(r0['y'] - A.ground_height(dg, r0['x'], r0['z'])) < 1e-6,
    (r0['y'], A.ground_height(dg, r0['x'], r0['z'])),
)
check('R2 ...and NOT tilted: rx = rz = 0, so every trunk stays vertical', r0['rx'] == 0.0 and r0['rz'] == 0.0, r0)
check('R2 ...the reply says it is draped on a slope', 'draped on a slope' in txt, txt)

# a real hill: radius 40, height 12 — 80 x 80 m of ground that is NOT planar
dh = A.Drawing({'objects': []})
txt, dh = assistant('add_hill', {'centre': 'AN40', 'radius': 40, 'height': 12}, drawing=dh)
check('the terrain family drew the hill this family will tile over', dh.objs[-1]['kind'] == 'hill', txt)
n0 = len(dh.objs)
txt, dh = assistant(
    'plant_forest', {'cell_from': 'A1', 'cell_to': 'CB80', 'density': 0.02, 'mix': 'conifer', 'height': 16}, drawing=dh
)
ti = dh.objs[n0:]
check('R2 an 80 x 80 m wood over a hill becomes 4 or more tiles', len(ti) >= 4, (txt, len(ti)))
check(
    'R2 ...whose y really differ (they follow the hill, they do not all sit at 0)',
    len(set(t['y'] for t in ti)) >= 4 and max(t['y'] for t in ti) > 5,
    sorted({t['y'] for t in ti}),
)
check(
    'R2 ...each with a non-zero ground gradient of its own',
    all(abs(t['p']['gx']) + abs(t['p']['gz']) > 1e-6 for t in ti),
    [(t['p']['gx'], t['p']['gz']) for t in ti],
)
check(
    'R2 ...all in ONE group, none of them tilted',
    len({t['grp'] for t in ti}) == 1 and all(t['rx'] == 0.0 and t['rz'] == 0.0 for t in ti),
    ({t['grp'] for t in ti}, [(t['rx'], t['rz']) for t in ti]),
)
check(
    'R2 ...no tile wider than 25 m, so each is planar enough to drape',
    all(t['p']['w'] <= F.TILE_M + 1e-6 and t['p']['d'] <= F.TILE_M + 1e-6 for t in ti),
    [(t['p']['w'], t['p']['d']) for t in ti],
)
check('R2 ...and the reply says so ("in N tiles")', 'tiles' in txt and 'objects' in txt, txt)
check(
    'R8 no tile is buried or floating: every y matches the ground under it within 0.3 m',
    all(abs(t['y'] - A.ground_height(dh, t['x'], t['z'])) <= 0.3 for t in ti),
    [(t['y'], round(A.ground_height(dh, t['x'], t['z']), 3)) for t in ti],
)
n0 = len(dh.objs)
txt, dh = assistant(
    'plant_forest',
    {'cell_from': 'A1', 'cell_to': 'CB80', 'density': 0.02, 'mix': 'conifer', 'height': 16, 'base_height': 20},
    drawing=dh,
)
bh = dh.objs[n0:]
check(
    'base_height overrides the ground: ONE flat record at 20 m, no tiles, no slope',
    len(bh) == 1 and bh[0]['y'] == 20.0 and bh[0]['p']['gx'] == 0 and bh[0]['p']['gz'] == 0,
    (txt, len(bh)),
)

# undergrowth and orchard drape the same way
n0 = len(dh.objs)
txt, dh = assistant('add_undergrowth', {'cell_from': 'A1', 'cell_to': 'CB80', 'count': 400}, drawing=dh)
ug = dh.objs[n0:]
check(
    'R2 undergrowth tiles over the same hill, each tile with its own gx/gz',
    len(ug) >= 4 and all(abs(t['p']['gx']) + abs(t['p']['gz']) > 1e-6 for t in ug),
    (txt, len(ug)),
)
n0 = len(dg.objs)
txt, dg = assistant('plant_orchard', {'cell_from': 'T20', 'cell_to': 'BS70', 'height': 4}, drawing=dg)
orc_g = dg.objs[n0:]
check(
    'R2 an orchard on the planar slope stays ONE record with the slope gradient',
    len(orc_g) == 1 and abs(orc_g[0]['p']['gz'] - 0.1) < 1e-3 and orc_g[0]['rz'] == 0.0,
    (txt, len(orc_g)),
)

# plant_tree_line — C10..C70 is 60 m, C70..M70 is 10 m
before = kinds_of(d).get('tree_line', 0)
txt, d = assistant(
    'plant_tree_line', {'model': 'parametric', 'cells': ['C10', 'C70'], 'kind': 'poplar', 'height': 16}, drawing=d
)
tl = d.objs[-1]
check(
    'plant_tree_line drew one line, 60 m long, spacing 6, poplar (kind 2)',
    kinds_of(d).get('tree_line', 0) - before == 1
    and tl['p']['len'] == 60
    and tl['p']['spacing'] == 6
    and tl['p']['kind'] == 2
    and tl['p']['h'] == 16,
    (txt, tl['p']),
)
check('...turned to face down the column, like a fence', abs(tl['ry'] + 1.570796) < 1e-4, tl['ry'])
check('...reports 11 trees', '11 trees' in txt and tl['id'] in txt, txt)
check('line_count(60, 6) == 11', F.line_count(60, 6) == 11, F.line_count(60, 6))
before = kinds_of(d).get('tree_line', 0)
txt, d = assistant(
    'plant_tree_line',
    {'model': 'parametric', 'cells': ['C10', 'C70', 'M70'], 'kind': 'conifer', 'spacing': 4},
    drawing=d,
)
check(
    '3 cells give 2 tree lines, kind 1',
    kinds_of(d).get('tree_line', 0) - before == 2 and d.objs[-1]['p']['kind'] == 1 and d.objs[-1]['p']['spacing'] == 4,
    txt,
)
txt, d = assistant('plant_tree_line', {'model': 'parametric', 'cells': ['C10']}, drawing=d)
check('one cell refused', txt.startswith('refused'), txt)
txt, d = assistant('plant_tree_line', {'model': 'parametric', 'cells': ['C10', 'C70'], 'spacing': 0.5}, drawing=d)
check('spacing under 1 m refused', txt.startswith('refused'), txt)
txt, d = assistant('plant_tree_line', {'model': 'parametric', 'cells': ['C10', 'C70'], 'kind': 'baobab'}, drawing=d)
check('unknown tree kind refused', txt.startswith('refused'), txt)
txt, d = assistant(
    'plant_tree_line', {'model': 'parametric', 'cells': ['C10', 'C70'], 'kind': 'poplar', 'height': 8}, drawing=d
)
check('R7 an 8 m poplar refused: poplars are 15-25 m', txt.startswith('refused') and '15-25' in txt, txt)
txt, d = assistant(
    'plant_tree_line', {'model': 'parametric', 'cells': ['C10', 'C70'], 'kind': 'conifer', 'height': 30}, drawing=d
)
check('R7 a 30 m conifer refused: conifers are 8-25 m', txt.startswith('refused') and '8-25' in txt, txt)

# R4 with a twist: the row follows the fall, but as gx — never as an rz that would lean it
n0 = len(dg.objs)
txt, dg = assistant(
    'plant_tree_line',
    {'model': 'parametric', 'cells': ['AN20', 'AN80'], 'kind': 'poplar', 'height': 18, 'spacing': 6},
    drawing=dg,
)
row = dg.objs[-1]
check(
    'R4 the row sits at the ground height under its CENTRE',
    abs(row['y'] - A.ground_height(dg, row['x'], row['z'])) < 1e-6,
    (row['y'], A.ground_height(dg, row['x'], row['z'])),
)
check(
    'R4 the 6 m fall over 60 m becomes gx 0.1 ALONG the row, gz 0',
    abs(row['p']['gx'] - 0.1) < 1e-3 and row['p']['gz'] == 0,
    row['p'],
)
check('R4 ...and NOT an rz, which would lean every poplar downhill', row['rz'] == 0.0 and row['rx'] == 0.0, row)
check('R4 ...the reply says how far it runs downhill', 'running downhill' in txt and '6.0 m over 60 m' in txt, txt)

# plant_orchard — A1..AN30 is 40 x 30 m
txt, d = assistant('plant_orchard', {'cell_from': 'A1', 'cell_to': 'AN30'}, drawing=d)
orc = d.objs[-1]
check(
    'plant_orchard drew one 40 x 30 record at spacing 5, 4 m trees',
    orc['kind'] == 'orchard'
    and orc['p']['w'] == 40
    and orc['p']['d'] == 30
    and orc['p']['spacing'] == 5
    and orc['p']['h'] == 4,
    (txt, orc['p']),
)
check('...reports 9 x 7 = 63 fruit trees', '9 x 7 = 63' in txt and orc['id'] in txt, txt)
check('orchard_grid(40, 30, 5) == (9, 7)', F.orchard_grid(40, 30, 5) == (9, 7), F.orchard_grid(40, 30, 5))
txt, d = assistant('plant_orchard', {'cell_from': 'A1', 'cell_to': 'AN30', 'spacing': 0.5}, drawing=d)
check('orchard spacing under 1 m refused', txt.startswith('refused'), txt)
txt, d = assistant('plant_orchard', {'cell_from': 'A1', 'cell_to': 'AN30', 'height': 12}, drawing=d)
check('R7 a 12 m fruit tree refused: they are 3-5 m', txt.startswith('refused') and '3-5' in txt, txt)

# add_undergrowth — A1..AN40 is 40 x 40 m
txt, d = assistant('add_undergrowth', {'cell_from': 'A1', 'cell_to': 'AN40', 'base_height': 3}, drawing=d)
ug1 = d.objs[-1]
check(
    'add_undergrowth drew one scatter: 40 x 40, 60 bushes, seed 1, r 0.8',
    ug1['kind'] == 'undergrowth'
    and ug1['p']['w'] == 40
    and ug1['p']['d'] == 40
    and ug1['p']['count'] == 60
    and ug1['p']['seed'] == 1
    and ug1['p']['r'] == 0.8,
    (txt, ug1['p']),
)
check('...base_height carried to y', ug1['y'] == 3.0 and ug1['id'] in txt, (txt, ug1['y']))
txt, d = assistant('add_undergrowth', {'cell_from': 'A1', 'cell_to': 'AN40', 'count': 0}, drawing=d)
check('zero bushes refused', txt.startswith('refused'), txt)
txt, d = assistant('add_undergrowth', {'cell_from': 'A1', 'cell_to': 'AN40', 'bush_radius': 40}, drawing=d)
check('a 40 m bush refused', txt.startswith('refused'), txt)
txt, d = assistant('add_undergrowth', {'cell_from': 'A1', 'cell_to': 'AN40', 'bush_radius': 3}, drawing=d)
check(
    'R7 a 3 m radius is a 3.6 m bush: refused, shrubs are 0.4-2 m tall',
    txt.startswith('refused') and '0.4-2' in txt,
    txt,
)

# add_object must reach the kinds directly
txt, d = assistant(
    'add_object', {'kind': 'orchard', 'cell': 'A1', 'params': {'w': 20, 'd': 20, 'spacing': 4, 'h': 5}}, drawing=d
)
check('add_object knows orchard', d.objs[-1]['kind'] == 'orchard' and d.objs[-1]['p']['spacing'] == 4, txt)
txt, d = assistant(
    'add_object', {'kind': 'undergrowth', 'cell': 'A1', 'params': {'w': 12, 'd': 12, 'count': 20}}, drawing=d
)
check('add_object knows undergrowth', d.objs[-1]['kind'] == 'undergrowth' and d.objs[-1]['p']['count'] == 20, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all four', sorted(F.KINDS) == sorted(NEW_KINDS), sorted(F.KINDS))

# ── the looks (step 4): one green, varied crowns, a narrow poplar ────────────
with open(os.path.join(HERE, 'arch_ext', 'forests.js'), encoding='utf-8') as fh:
    JS = fh.read()
check(
    'both crown kinds are mat_foliage — never the brighter mat_grass',
    'mat_grass' not in JS and JS.count("'mat_foliage'") >= 4,
    JS.count("'mat_foliage'"),
)
CFS = [s[4] for s in SPOTS]
check(
    'crown factors run 0.8-1.2 and really vary (not a lawn of identical balls)',
    0.8 <= min(CFS) < 0.85 and 1.15 < max(CFS) <= 1.2 and len(set(CFS)) > len(CFS) // 2,
    (min(CFS), max(CFS), len(set(CFS))),
)
check(
    'the poplar stays narrow: its widest crown is under the deciduous narrowest',
    F.CROWN_F[F.POPLAR] == 0.12 and F.crown_radius(F.POPLAR, 20, 1.2) < F.crown_radius(F.DECIDUOUS, 20, 0.8),
    (F.crown_radius(F.POPLAR, 20, 1.2), F.crown_radius(F.DECIDUOUS, 20, 0.8)),
)
check(
    'the crown factor moves the crown, never the trunk or the tree height',
    max(s[3] for s in SPOTS) == max(s[3] for s in F.forest_spots(100, 100, 0.04, 0.5, 14, 0.45, 1)),
    max(s[3] for s in SPOTS),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
flat_cases = [
    {'kind': 'forest', 'p': P_FOREST},
    {'kind': 'tree_line', 'p': P_LINE},
    {'kind': 'orchard', 'p': P_ORCHARD},
    {'kind': 'undergrowth', 'p': P_SCRUB},
]
drape_cases = [
    {'kind': 'forest', 'p': P_FOREST_G},
    {'kind': 'tree_line', 'p': P_LINE_G},
    {'kind': 'orchard', 'p': P_ORCHARD_G},
    {'kind': 'undergrowth', 'p': P_SCRUB_G},
]
b = browser_kinds(flat_cases + drape_cases)
by = {r['kind']: r for r in b[:4]}
byg = {r['kind']: r for r in b[4:]}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind builds real geometry, flat and draped',
    all(r['ok'] for r in b),
    [(r['kind'], r['ok'], r['err']) for r in b],
)

fo = by['forest']
check('a whole forest is TWO parts: one crown mesh, one trunk mesh', fo['parts'] == 2, fo['parts'])
check(
    'forest triangles are EXACTLY %d conifer x %d + %d deciduous x %d = %d'
    % (N_CONIFER, F.TREE_TRIS[F.CONIFER], N_DECID, F.TREE_TRIS[F.DECIDUOUS], FOREST_TRIS),
    fo['tris'] == FOREST_TRIS,
    (fo['tris'], FOREST_TRIS),
)
check('400 trees stay under 40 000 triangles', fo['tris'] < 40000, fo['tris'])
fb, fmin = _box(forest_items(P_FOREST))
check(
    'forest bbox matches the Python scatter within 2%%: %.2f x %.2f x %.2f m' % fb,
    box_near(fo['size'], fb),
    (fo['size'], fb),
)
check(
    '...which is the 100 x 100 m block plus the crowns, and h*1.3 = 18.2 m tall',
    100 <= fb[0] <= 100 + 2 * 0.36 * 1.2 * 14 * 1.3 + 2 * 0.45 * 5
    and 100 <= fb[2] <= 100 + 2 * 0.36 * 1.2 * 14 * 1.3 + 2 * 0.45 * 5
    and near(fb[1], 14 * 1.3, 0.02),
    fb,
)
check('forest sits on the ground (min y = 0)', abs(fo['min'][1]) < 0.01, fo['min'])
fb_uni, _ = _box(forest_items(P_FOREST, uniform=True))
check(
    'the tab really varies the crowns: the varying prediction beats the uniform one',
    abs(fo['size'][0] - fb[0]) < abs(fo['size'][0] - fb_uni[0]),
    (fo['size'][0], fb[0], fb_uni[0]),
)

# the draped forest — the brief's gx 0.2, gz 0.1
fg = byg['forest']
gb, gmin = _box(forest_items(P_FOREST_G), P_FOREST_G['gx'], P_FOREST_G['gz'])
check(
    'DRAPING costs nothing: gx 0.2 / gz 0.1 leaves the triangle count and the part count alone',
    fg['tris'] == fo['tris'] and fg['parts'] == fo['parts'],
    (fg['tris'], fo['tris']),
)
check(
    'forest_bbox(gx 0.2, gz 0.1) = %.2f x %.2f x %.2f m and the tab matches within 2%%' % F.forest_bbox(P_FOREST_G),
    box_near(fg['size'], F.forest_bbox(P_FOREST_G)),
    (fg['size'], F.forest_bbox(P_FOREST_G)),
)
check(
    '...forest_bbox is the same arithmetic as the test box',
    box_near(F.forest_bbox(P_FOREST_G), gb, 1e-9),
    (F.forest_bbox(P_FOREST_G), gb),
)
check(
    '...the plan stays put: only the y span grew, by the plane rise over the block',
    near(fg['size'][0], fo['size'][0]) and near(fg['size'][2], fo['size'][2]) and fg['size'][1] > fo['size'][1] + 20,
    (fo['size'], fg['size']),
)
check(
    '...and the lowest tree base is where the plane puts it (%.2f m)' % gmin,
    abs(fg['min'][1] - gmin) < 0.05,
    (fg['min'][1], gmin),
)

tl = by['tree_line']
check(
    'tree_line len 60 spacing 6 is 11 deciduous trees: %d triangles' % (11 * F.TREE_TRIS[F.DECIDUOUS]),
    tl['tris'] == 11 * F.TREE_TRIS[F.DECIDUOUS],
    (tl['tris'], 11 * F.TREE_TRIS[F.DECIDUOUS]),
)
lb, _ = _box(line_items(P_LINE))
check(
    'tree_line bbox matches the Python row within 2%%: %.2f x %.2f x %.2f m' % lb,
    box_near(tl['size'], lb),
    (tl['size'], lb),
)
check('...the row is 60 m of trunks plus a crown at each end', 60 < lb[0] < 60 + 2 * 0.36 * 1.2 * 13, lb)
tlg = byg['tree_line']
lbg, lmin = _box(line_items(P_LINE_G), P_LINE_G['gx'], P_LINE_G['gz'])
check(
    'a tree line draped with gx 0.15 matches the Python row within 2%%: %.2f x %.2f x %.2f m' % lbg,
    box_near(tlg['size'], lbg) and tlg['tris'] == tl['tris'],
    (tlg['size'], lbg),
)
check(
    '...the row climbs %.2f m over its 60 m and the trunks stay upright' % (lbg[1] - lb[1]),
    lbg[1] > lb[1] + 7 and abs(tlg['min'][1] - lmin) < 0.05,
    (lbg[1] - lb[1], tlg['min'][1], lmin),
)

orc = by['orchard']
check(
    'orchard 40 x 30 spacing 5 is 9 x 7 = 63 trees: %d triangles' % (63 * F.TREE_TRIS[F.DECIDUOUS]),
    orc['tris'] == 63 * F.TREE_TRIS[F.DECIDUOUS],
    (orc['tris'], 63 * F.TREE_TRIS[F.DECIDUOUS]),
)
check(
    'orchard bbox is 40 + 2 x 1.6 by 4 by 30 + 2 x 1.6',
    near(orc['size'][0], 43.2) and near(orc['size'][1], 4.0) and near(orc['size'][2], 33.2),
    orc['size'],
)
orcg = byg['orchard']
ob, _ = _box(orchard_items(P_ORCHARD_G), P_ORCHARD_G['gx'], P_ORCHARD_G['gz'])
check(
    'a draped orchard matches the Python grid within 2%%: %.2f x %.2f x %.2f m' % ob,
    box_near(orcg['size'], ob) and orcg['tris'] == orc['tris'],
    (orcg['size'], ob),
)

ug = by['undergrowth']
check(
    'undergrowth is 60 bushes of %d triangles = %d' % (F.TREE_TRIS[F.SHRUB], 60 * F.TREE_TRIS[F.SHRUB]),
    ug['tris'] == 60 * F.TREE_TRIS[F.SHRUB],
    (ug['tris'], 60 * F.TREE_TRIS[F.SHRUB]),
)
check('undergrowth is one foliage part', ug['parts'] == 1, ug['parts'])
sb, _ = _box(scrub_items(P_SCRUB))
check(
    'undergrowth bbox matches the Python scatter within 2%%: %.2f x %.2f x %.2f m' % sb,
    box_near(ug['size'], sb),
    (ug['size'], sb),
)
ugg = byg['undergrowth']
sbg, smin = _box(scrub_items(P_SCRUB_G), P_SCRUB_G['gx'], P_SCRUB_G['gz'])
check(
    'draped undergrowth matches the Python scatter within 2%%: %.2f x %.2f x %.2f m' % sbg,
    box_near(ugg['size'], sbg) and ugg['tris'] == ug['tris'],
    (ugg['size'], sbg),
)
check(
    '...and it hugs the plane it was given (lowest bush at %.2f m)' % smin,
    abs(ugg['min'][1] - smin) < 0.05,
    (ugg['min'][1], smin),
)

check(
    'labels',
    [by[k]['label'] for k in NEW_KINDS] == ['Forest', 'Tree line', 'Orchard', 'Undergrowth'],
    [by[k]['label'] for k in NEW_KINDS],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(flat_cases)
check(
    'blender builds the forest: more than 400 x 8 polys',
    bl.get('forest', {}).get('polys', 0) > 400 * 8,
    bl.get('forest'),
)
check('blender builds the tree line', bl.get('tree_line', {}).get('polys', 0) > 11 * 8, bl.get('tree_line'))
check('blender builds the orchard', bl.get('orchard', {}).get('polys', 0) > 63 * 8, bl.get('orchard'))
check('blender builds the undergrowth', bl.get('undergrowth', {}).get('polys', 0) > 60 * 8, bl.get('undergrowth'))
check(
    'blender agrees with the tab about the flat forest box',
    box_near(bl['forest']['size'], fo['size'], 0.02),
    (bl['forest']['size'], fo['size']),
)

blg = blender_kinds(drape_cases)
check(
    'blender builds the DRAPED forest with the same polygon count as the flat one',
    blg.get('forest', {}).get('polys', 0) == bl.get('forest', {}).get('polys', -1),
    (blg.get('forest', {}).get('polys'), bl.get('forest', {}).get('polys')),
)
check(
    'blender agrees with the tab about the draped forest box (both engines drape alike)',
    box_near(blg['forest']['size'], fg['size'], 0.02),
    (blg['forest']['size'], fg['size']),
)
check(
    'blender agrees with the tab about the draped tree line box',
    box_near(blg['tree_line']['size'], tlg['size'], 0.02),
    (blg['tree_line']['size'], tlg['size']),
)
check(
    'blender agrees with the tab about the draped orchard box',
    box_near(blg['orchard']['size'], orcg['size'], 0.02),
    (blg['orchard']['size'], orcg['size']),
)
check(
    'blender agrees with the tab about the draped undergrowth box',
    box_near(blg['undergrowth']['size'], ugg['size'], 0.02),
    (blg['undergrowth']['size'], ugg['size']),
)
check(
    'blender puts the draped forest as low as the tab does (min y %.2f)' % gmin,
    abs(blg['forest']['min_y'] - gmin) < 0.05,
    (blg['forest']['min_y'], gmin),
)
finish()
