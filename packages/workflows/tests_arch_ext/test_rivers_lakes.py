# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_rivers_lakes.py — proof for the rivers_lakes family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_rivers_lakes.py

Three engines must agree. The assistant's four tools produce the records
claimed and refuse the silly numbers; the tab builds every kind at the size its
parameters name — and because these are NATURAL water they DIG, so the bbox
minimum in Y is negative; Blender builds a mesh with faces for each of them.

The meander offset and the lake rim factor are written out three times (the
tab's JS, the assistant's Python, Blender's Python). That is the one thing a
bounding box can prove across engines: the Python copy is evaluated here and
the numbers it predicts are compared with the box the tab actually built.

2026-09-07 — the GROUND seam. The section 'ground' below proves the placement
rules on a real slope drawn with the terrain family's add_slope (10 m over
100 m): every reach takes the ground at its centre, tilts DOWNHILL (rz < 0 by
construction: local +X runs from cell i to cell i+1 and a positive rz lifts
+X), never climbs, a lake refuses ground that is not level, and a waterfall
stands on the ground — or hangs its lip on a cliff/plateau top with at_edge_of.
The tab then proves the tilt is real: a reach turned by rz stands
depth + len*|sin rz| tall, and Blender agrees with the tab about that height.
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
import zyg_workflows.arch_assistant_ext.rivers_lakes as RL  # noqa: E402

NEW_KINDS = ['river', 'lake', 'waterfall']
NEW_TOOLS = ['add_river', 'add_stream', 'add_lake', 'add_waterfall']

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in NEW_TOOLS), [t for t in NEW_TOOLS if t not in names])
check('prompt is one paragraph under 1100 characters', len(RL.PROMPT) <= 1100 and '\n' not in RL.PROMPT, len(RL.PROMPT))
check(
    'the prompt says water lands on the ground, rivers run downhill and lakes must be level',
    'ground' in RL.PROMPT and 'downhill' in RL.PROMPT and 'LEVEL' in RL.PROMPT,
    RL.PROMPT[:120],
)
check('KINDS is exactly the family', sorted(RL.KINDS) == sorted(NEW_KINDS), sorted(RL.KINDS))
check('no openings', RL.OPENINGS == [], RL.OPENINGS)
check(
    'water is NOT ground: the family exports no HEIGHTS',
    getattr(RL, 'HEIGHTS', None) is None and not any(k in A.EXT_HEIGHTS for k in NEW_KINDS),
    [k for k in NEW_KINDS if k in A.EXT_HEIGHTS],
)
check(
    'a lake defaults to a 1 m sand rim inside its shore band',
    RL.KINDS['lake']['rim'] == 1 and abs(RL.lake_rim(30, 20, 0.25, 3, 1) - 1.0) < 1e-9,
    (RL.KINDS['lake'], RL.lake_rim(30, 20, 0.25, 3, 1)),
)
sec = RL.channel_section(12, 2, 2)
check(
    'the channel section is 6 points: grass over the top 40 % of each bank, gravel below',
    len(sec) == 6
    and sec[0] == (-8.0, 0.0)
    and abs(sec[1][0] + 7.2) < 1e-9
    and abs(sec[1][1] + 0.8) < 1e-9
    and sec[2] == (-6.0, -2.0)
    and sec[5] == (8.0, 0.0),
    sec,
)

# a river through three cells = two reaches
txt, d = assistant('add_river', {'cells': ['C4', 'H4', 'H9'], 'width': 12, 'depth': 2, 'meander': 6})
reaches = [o for o in d.objs if o['kind'] == 'river']
check('river through 3 cells -> 2 reaches', kinds_of(d).get('river') == 2 and len(reaches) == 2, txt)
check(
    'each reach is 5 m long, 12 m wide, 2 m deep, 6 m of wander',
    all(
        abs(r['p']['len'] - 5.0) < 1e-6
        and r['p']['w'] == 12
        and r['p']['depth'] == 2
        and r['p']['meander'] == 6
        and r['p']['bank'] == 2
        and r['p']['seg'] == 24
        for r in reaches
    ),
    [r['p'] for r in reaches],
)
check(
    'consecutive reaches carry different seeds',
    [r['p']['seed'] for r in reaches] == [1, 2],
    [r['p']['seed'] for r in reaches],
)
check(
    'on flat ground the river sits on the base plane, untilted',
    all(r['y'] == 0.0 and r['rz'] == 0.0 for r in reaches),
    [(r['y'], r['rz']) for r in reaches],
)
check('both reaches share one group', reaches[0]['grp'] == reaches[1]['grp'] == 'river', [r['grp'] for r in reaches])


def reach_ends(r):
    """(start, end) of a reach in world x/z — local +X turned by ry."""
    L, c, s = r['p']['len'], math.cos(r['ry']), math.sin(r['ry'])
    return ((r['x'] - L / 2 * c, r['z'] + L / 2 * s), (r['x'] + L / 2 * c, r['z'] - L / 2 * s))


e0, s1 = reach_ends(reaches[0])[1], reach_ends(reaches[1])[0]
check('reach 1 ends exactly where reach 2 starts', abs(e0[0] - s1[0]) < 1e-6 and abs(e0[1] - s1[1]) < 1e-6, (e0, s1))
check(
    'the meander envelope is zero at both ends, so the reaches truly join',
    abs(RL.meander_offset(0.0, 6, 1)) < 1e-12 and abs(RL.meander_offset(1.0, 6, 1)) < 1e-12,
    (RL.meander_offset(0.0, 6, 1), RL.meander_offset(1.0, 6, 1)),
)

txt, d = assistant('add_river', {'cells': ['B8', 'N8'], 'width': 10, 'base_height': 4}, drawing=d)
check('base_height lifts the river onto the valley floor', d.objs[-1]['y'] == 4.0, (txt, d.objs[-1]))

# refusals — the REAL ranges (R7): river 3-30 m wide, 0.5-4 m deep
for args, want in (
    ({'cells': ['C4', 'H4'], 'width': 0.3}, 'wide'),
    ({'cells': ['C4', 'H4'], 'width': 300}, 'wide'),
    ({'cells': ['C4', 'H4'], 'depth': 0.1}, 'deep'),
    ({'cells': ['C4', 'H4'], 'depth': 60}, 'deep'),
    ({'cells': ['C4', 'H4'], 'width': 4, 'meander': 9}, 'fold'),
    ({'cells': ['C4']}, 'two cells'),
):
    txt, _ = assistant('add_river', args, drawing=d)
    check('refused: river ' + want, txt.startswith('refused') and want in txt, (args, txt))
txt, _ = assistant('add_river', {'cells': ['C4', 'H4'], 'width': 2}, drawing=d)
check(
    'refused: a 2 m river, and the refusal quotes the real range 3-30 m',
    txt.startswith('refused') and '3 and 30 m wide' in txt,
    txt,
)
txt, _ = assistant('add_river', {'cells': ['C4', 'H4'], 'depth': 5}, drawing=d)
check(
    'refused: a 5 m deep river, and the refusal quotes 0.5-4 m',
    txt.startswith('refused') and '0.5 and 4 m deep' in txt,
    txt,
)

# a stream is a river with small numbers, and its own range
txt, d2 = assistant('add_stream', {'cells': ['D20', 'J20', 'J26']})
st = [o for o in d2.objs if o['kind'] == 'river']
check(
    'a stream is a river record 2 m wide and 0.5 m deep',
    len(st) == 2
    and all(
        s['p']['w'] == 2 and s['p']['depth'] == 0.5 and s['p']['meander'] == 2 and s['p']['bank'] == 0.8 for s in st
    ),
    (txt, [s['p'] for s in st]),
)
check('the stream gets its own group', st[0]['grp'] == 'stream', st[0]['grp'])
txt, _ = assistant('add_stream', {'cells': ['D20', 'J20'], 'width': 6}, drawing=d2)
check(
    'refused: a 6 m stream is a river, and the refusal says 1-3 m',
    txt.startswith('refused') and '1 and 3 m wide' in txt,
    txt,
)
txt, _ = assistant('add_stream', {'cells': ['D20', 'J20'], 'depth': 2}, drawing=d2)
check(
    'refused: a 2 m deep stream, and the refusal says 0.3-1 m',
    txt.startswith('refused') and '0.3 and 1 m deep' in txt,
    txt,
)

# a lake
txt, d3 = assistant('add_lake', {'centre': 'P30', 'radius': 30, 'radius_z': 20, 'depth': 3, 'irregularity': 0.25})
lake = d3.objs[-1]
check(
    'lake: one record, 30 x 20 m radii, 3 m deep, wobble 0.25',
    kinds_of(d3).get('lake') == 1
    and lake['p']['rx'] == 30
    and lake['p']['rz'] == 20
    and lake['p']['depth'] == 3
    and lake['p']['wobble'] == 0.25,
    (txt, lake['p']),
)
check(
    'the lake has a sandy shore band, a 1 m rim and sits on the ground plane',
    lake['p']['shore'] > 0 and lake['p']['rim'] == 1 and lake['y'] == 0.0,
    lake,
)
for args, want in (
    ({'centre': 'P30', 'radius': 1}, 'radius'),
    ({'centre': 'P30', 'radius': 500}, 'radius'),
    ({'centre': 'P30', 'radius': 30, 'depth': 0.1}, 'deep'),
):
    txt, _ = assistant('add_lake', args, drawing=d3)
    check('refused: lake ' + want, txt.startswith('refused') and want in txt, (args, txt))
txt, _ = assistant('add_lake', {'centre': 'P30', 'radius': 4}, drawing=d3)
check(
    'refused: a 4 m lake, and the refusal quotes the real range 5-120 m',
    txt.startswith('refused') and 'between 5 and 120 m' in txt,
    txt,
)
txt, _ = assistant('add_lake', {'centre': 'P30', 'radius': 30, 'depth': 20}, drawing=d3)
check(
    'refused: a 20 m deep lake, and the refusal quotes 1-15 m',
    txt.startswith('refused') and 'between 1 and 15 m deep' in txt,
    txt,
)

# a waterfall
txt, d4 = assistant('add_waterfall', {'cell': 'K12', 'height': 15, 'width': 8, 'direction_deg': 90})
fall = d4.objs[-1]
check(
    'waterfall: one record, 15 m drop, 8 m wide, with a plunge pool',
    kinds_of(d4).get('waterfall') == 1
    and fall['p']['h'] == 15
    and fall['p']['w'] == 8
    and fall['p']['pool_r'] >= 4
    and fall['p']['depth'] > 0,
    (txt, fall['p']),
)
check('the water falls toward direction_deg', abs(fall['ry'] - math.pi / 2) < 1e-5, fall['ry'])
for args, want in (
    ({'cell': 'K12', 'height': 0.5}, 'drop'),
    ({'cell': 'K12', 'height': 400}, 'drop'),
    ({'cell': 'K12', 'height': 12, 'width': 0.2}, 'wide'),
):
    txt, _ = assistant('add_waterfall', args, drawing=d4)
    check('refused: waterfall ' + want, txt.startswith('refused') and want in txt, (args, txt))
txt, _ = assistant('add_waterfall', {'cell': 'K12', 'height': 1.5}, drawing=d4)
check(
    'refused: a 1.5 m waterfall, and the refusal quotes the real range 2-60 m',
    txt.startswith('refused') and 'between 2 and 60 m' in txt,
    txt,
)

txt, d4 = assistant('add_object', {'kind': 'river', 'cell': 'B7', 'params': {'len': 30, 'w': 5}}, drawing=d4)
check('add_object knows river', d4.objs[-1]['kind'] == 'river' and d4.objs[-1]['p']['w'] == 5, txt)
txt, d4 = assistant('add_object', {'kind': 'waterfall', 'cell': 'C7', 'params': {'h': 9}}, drawing=d4)
check('add_object knows waterfall', d4.objs[-1]['kind'] == 'waterfall' and d4.objs[-1]['p']['h'] == 9, txt)
check('rail lists all three kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))

# ── the ground seam ───────────────────────────────────────────────────────────
print('ground')
# the terrain family's slope: 10 m of rise over 100 m along z, so 1:10 southward
g = A.Drawing({'objects': []})
txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T100', 'height': 10, 'direction': 'z'}, drawing=g)
slope = g.objs[-1]
check(
    'the slope is the ground: 10 m over 100 m along z',
    abs(A.ground_height(g, slope['x'], slope['z'] + 40) - 9.0) < 1e-6
    and abs(A.ground_height(g, slope['x'], slope['z'] - 40) - 1.0) < 1e-6,
    [A.ground_height(g, slope['x'], slope['z'] + q) for q in (-40, 0, 40)],
)

# K80 -> K50 -> K20 runs NORTH, which is DOWN this slope
txt, g = assistant('add_river', {'cells': ['K80', 'K50', 'K20'], 'width': 12, 'depth': 2}, drawing=g)
dn = [o for o in g.objs if o['kind'] == 'river']
check(
    'a 3-cell chain down the slope gives 2 reaches, 30 m each',
    len(dn) == 2 and all(abs(r['p']['len'] - 30) < 1e-6 for r in dn),
    (txt, [r['p']['len'] for r in dn]),
)
check(
    'R1/R4: each reach sits on the ground at its own centre, not at y = 0',
    all(abs(r['y'] - A.ground_height(g, r['x'], r['z'])) < 1e-4 and r['y'] > 0 for r in dn),
    [(r['y'], A.ground_height(g, r['x'], r['z'])) for r in dn],
)
check(
    'R4 sign: a reach running downhill has rz < 0 (local +X is downstream, +rz lifts +X)',
    all(r['rz'] < -0.01 for r in dn),
    [r['rz'] for r in dn],
)
ok_rz = True
for r in dn:
    (x0, z0), (x1, z1) = reach_ends(r)
    want = math.atan2(A.ground_height(g, x1, z1) - A.ground_height(g, x0, z0), r['p']['len'])
    ok_rz = ok_rz and abs(r['rz'] - want) < 1e-4
check(
    'R4: rz is exactly atan((ground at the far cell - ground at the near cell) / len) = %.6f' % math.atan2(-3.0, 30.0),
    ok_rz,
    [r['rz'] for r in dn],
)
check(
    'the chain never climbs: each reach starts no higher than the last one ended',
    dn[1]['y'] <= dn[0]['y'] + (dn[0]['p']['len'] / 2) * math.sin(dn[0]['rz']) + 1e-6,
    (dn[0]['y'], dn[0]['rz'], dn[1]['y']),
)
check(
    'the reply says the total fall (7.95 m at the head to 1.95 m at the foot = 6.0 m)',
    'running downhill 6.0 m over 60 m' in txt,
    txt,
)

# the same cells the wrong way round: the water may NOT climb the slope
txt, gu = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T100', 'height': 10, 'direction': 'z'})
txt, gu = assistant('add_river', {'cells': ['K20', 'K50', 'K80'], 'width': 12}, drawing=gu)
up = [o for o in gu.objs if o['kind'] == 'river']
check(
    'a chain sent UPHILL is laid level instead of climbing 3 m a reach',
    all(r['rz'] == 0.0 for r in up) and up[1]['y'] <= up[0]['y'] + 1e-6,
    [(r['y'], r['rz']) for r in up],
)
check(
    '...and the reply says so instead of claiming a fall',
    'level ground' in txt and 'downhill' not in txt.split('level ground')[0],
    txt,
)

txt, gb = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T100', 'height': 10, 'direction': 'z'})
txt, gb = assistant('add_river', {'cells': ['K80', 'K50'], 'width': 12, 'base_height': 1.5}, drawing=gb)
check(
    'base_height still overrides the ground on a slope',
    gb.objs[-1]['y'] == 1.5 and 'base_height' in txt,
    (txt, gb.objs[-1]['y']),
)

txt, g = assistant('add_stream', {'cells': ['M80', 'M50']}, drawing=g)
check(
    'a stream tilts downhill on the same slope',
    g.objs[-1]['rz'] < -0.01 and abs(g.objs[-1]['y'] - A.ground_height(g, g.objs[-1]['x'], g.objs[-1]['z'])) < 1e-4,
    (txt, g.objs[-1]['y'], g.objs[-1]['rz']),
)

# R3 — a lake is level water and refuses a slope
txt, _ = assistant('add_lake', {'centre': 'K50', 'radius': 20}, drawing=g)
check(
    'R3: a lake on the slope is refused, and the refusal quotes the rise',
    txt.startswith('refused: the ground under') and 'rises 6.5 m' in txt,
    txt,
)
check(
    '...and the refusal offers the three ways out (flatten_pad / lower / a river)',
    'flatten_pad' in txt and 'lower on the slope' in txt and 'add_stream/add_river' in txt,
    txt,
)
txt, _ = assistant('add_lake', {'centre': 'K50', 'radius': 20, 'base_height': 4.95}, drawing=g)
check(
    'base_height overrides the level refusal (the operator says where the water lies)',
    not txt.startswith('refused') and abs(g.objs[-1]['y'] - 4.95) < 1e-9,
    txt,
)

# a plateau top is level ground: the lake is allowed and takes the plateau's height
p = A.Drawing({'objects': []})
p.new('plateau', {'w': 60, 'd': 60, 'h': 2, 'batter': 0.5}, 0.0, 0.0, 0.0, 0.0, 'mat_grass')
mid = A.cell_of(0.0, 0.0)
txt, p = assistant('add_lake', {'centre': mid, 'radius': 10}, drawing=p)
check(
    'R3: on the level top of a plateau the lake is allowed and floats its water at 2 m',
    not txt.startswith('refused') and p.objs[-1]['y'] == 2.0,
    (txt, p.objs[-1]['y']),
)

# R5 — the waterfall
txt, g = assistant('add_waterfall', {'cell': 'K50', 'height': 12}, drawing=g)
wf = g.objs[-1]
check(
    'R5: the waterfall stands on the ground at its cell and its lip is y + h',
    abs(wf['y'] - A.ground_height(g, wf['x'], wf['z'])) < 1e-4
    and abs(wf['y'] - 4.95) < 1e-4
    and 'the lip at 16.95 m' in txt,
    (txt, wf['y']),
)
txt, p = assistant('add_waterfall', {'cell': mid, 'width': 8, 'at_edge_of': 'o1'}, drawing=p)
wf2 = p.objs[-1]
check(
    'at_edge_of hangs the lip on the plateau top (2 m) with the pool on the ground under it (0 m)',
    wf2['y'] == 0.0 and abs(wf2['p']['h'] - 2.0) < 1e-6,
    (txt, wf2['y'], wf2['p']),
)
txt, _ = assistant('add_waterfall', {'cell': mid, 'at_edge_of': 'o99'}, drawing=p)
check('refused: at_edge_of names a record that is not there', txt.startswith('refused') and 'no record o99' in txt, txt)
txt, _ = assistant('add_waterfall', {'cell': mid, 'at_edge_of': wf2['id']}, drawing=p)
check(
    'refused: at_edge_of names something with no top surface to fall from',
    txt.startswith('refused') and 'no top surface' in txt,
    txt,
)
txt, _ = assistant('add_waterfall', {'cell': 'A1', 'at_edge_of': 'o1'}, drawing=p)
check(
    'refused: the cell is not on the record the lip was to hang from',
    txt.startswith('refused') and 'is not on o1' in txt,
    txt,
)

# ── the v3 sculpted ground ────────────────────────────────────────────────────
# With a `ground` record the water is the LAND, cut: add_river/add_stream hand
# the job to water_v3's carve_river and add_lake to fill_lake, so a valley is a
# valley instead of a trough standing on one. add_waterfall keeps its solid.
print('sculpted ground (v3)')
txt, v = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'CV60', 'style': 'rolling'})
gr = v.objs[-1]
check(
    'v3: make_ground laid one ground record for the water to be cut from',
    gr['kind'] == 'ground' and RL.the_ground(v) is gr,
    (txt, gr['kind']),
)
check(
    'v3: the water_v3 tools are reachable at CALL time (EXT_MODULES loads alphabetically)',
    RL._water_tool('t_carve_river') is not None and RL._water_tool('t_fill_lake') is not None,
    sorted(A.EXT_MODULES),
)

before = A.ground_height(v, *A.cell_centre(*A.parse_cell('K25')))
txt, v = assistant('add_river', {'cells': ['K10', 'K40', 'K55'], 'width': 12, 'depth': 2}, drawing=v)
K = kinds_of(v)
check('v3: a river on a sculpted ground cuts one sculpt_channel per reach', K.get('sculpt_channel') == 2, (txt, K))
check('v3: ...and floats one water_path per reach', K.get('water_path') == 2, K)
check('v3: ...and draws NO solid `river` record', K.get('river') is None, K)
beds = [o for o in v.objs if o['kind'] == 'sculpt_channel']
check(
    'v3: the beds carry the width and depth the tool was given',
    all(b['p']['w'] == 12 and b['p']['depth'] == 2 for b in beds),
    [b['p'] for b in beds],
)
check(
    'v3: consecutive beds carry different seeds, so the two reaches wander differently',
    [b['p']['seed'] for b in beds] == [1, 2],
    [b['p']['seed'] for b in beds],
)
check(
    'v3: every bed sits at y = 0 — field_at adds the record y to the land, so a bed at ground '
    'height would LIFT it before cutting',
    all(b['y'] == 0.0 for b in beds),
    [b['y'] for b in beds],
)
check(
    'v3: the beds are grouped as ground sculpts, not as a river',
    all(b['grp'] == 'ground sculpts' for b in beds),
    [b['grp'] for b in beds],
)
paths = [o for o in v.objs if o['kind'] == 'water_path']
check(
    'v3: the water never climbs — each reach lies no higher than the one above it',
    paths[1]['y'] <= paths[0]['y'] + 1e-9,
    [p['y'] for p in paths],
)
check(
    'v3: the cut is REAL — the ground on the centreline is now lower than it was',
    A.ground_height(v, *A.cell_centre(*A.parse_cell('K25'))) < before - 0.5,
    (before, A.ground_height(v, *A.cell_centre(*A.parse_cell('K25')))),
)
check(
    'v3: the reply says which path it took (the land cut open, no solid river record)',
    'sculpted' in txt and 'sculpt_channel' in txt and 'no solid `river` record' in txt,
    txt,
)

txt, _ = assistant('add_river', {'cells': ['K10', 'K40'], 'width': 2}, drawing=v)
check(
    "v3: this family's REAL ranges are still checked FIRST — a 2 m river is refused on a "
    'sculpted ground too (carve_river alone would take it)',
    txt.startswith('refused') and '3 and 30 m wide' in txt,
    txt,
)
txt, _ = assistant('add_stream', {'cells': ['M10', 'M40'], 'width': 6}, drawing=v)
check(
    'v3: and a 6 m stream is still a river, sculpted ground or not',
    txt.startswith('refused') and '1 and 3 m wide' in txt,
    txt,
)
txt, _ = assistant('add_river', {'cells': ['K10', 'K40'], 'width': 12, 'base_height': 4}, drawing=v)
check(
    'v3: base_height does not apply to a sculpted ground, and the reply says so',
    'base_height does not apply' in txt,
    txt,
)

txt, vs = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'CV60', 'style': 'rolling'})
txt, vs = assistant('add_stream', {'cells': ['M10', 'M40']}, drawing=vs)
KS = kinds_of(vs)
check(
    'v3: a stream is cut the same way — sculpt_channel + water_path, no solid',
    KS.get('sculpt_channel') == 1 and KS.get('water_path') == 1 and KS.get('river') is None,
    (txt, KS),
)
check(
    'v3: the stream keeps its own 2 m bed and 0.5 m depth through the delegation',
    [o for o in vs.objs if o['kind'] == 'sculpt_channel'][0]['p']['w'] == 2
    and [o for o in vs.objs if o['kind'] == 'sculpt_channel'][0]['p']['depth'] == 0.5,
    [o['p'] for o in vs.objs if o['kind'] == 'sculpt_channel'],
)

txt, vl = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'CV60', 'style': 'rolling'})
txt, vl = assistant('add_lake', {'centre': 'AK30', 'radius': 20, 'radius_z': 15, 'depth': 3}, drawing=vl)
KL = kinds_of(vl)
check(
    'v3: a lake on a sculpted ground digs one sculpt_basin under one water_body',
    KL.get('sculpt_basin') == 1 and KL.get('water_body') == 1,
    (txt, KL),
)
check('v3: ...and draws NO solid `lake` record', KL.get('lake') is None, KL)
basin = [o for o in vl.objs if o['kind'] == 'sculpt_basin'][0]
body = [o for o in vl.objs if o['kind'] == 'water_body'][0]
check(
    'v3: the basin carries the radii and depth asked for and sits at y = 0',
    basin['p']['rx'] == 20 and basin['p']['rz'] == 15 and basin['p']['depth'] == 3 and basin['y'] == 0.0,
    basin,
)
check(
    'v3: the water surface lies BELOW the land it was cut from (freeboard), not on top of it',
    body['y'] < A.ground_height(A.Drawing({'objects': [vl.objs[0]]}), body['x'], body['z']),
    (body['y'], A.ground_height(A.Drawing({'objects': [vl.objs[0]]}), body['x'], body['z'])),
)
check(
    'v3: the R3 level refusal does NOT apply on a sculpted ground — the bed is dug flat',
    not txt.startswith('refused') and 'no level check is needed' in txt,
    txt,
)
txt, _ = assistant('add_lake', {'centre': 'AK30', 'radius': 4}, drawing=vl)
check(
    "v3: but a 4 m lake is still refused with this family's own 5-120 m range",
    txt.startswith('refused') and 'between 5 and 120 m' in txt,
    txt,
)

txt, vw = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'CV60', 'style': 'rolling'})
txt, vw = assistant('add_waterfall', {'cell': 'AK30', 'height': 12}, drawing=vw)
check(
    'v3: a waterfall KEEPS its solid on a sculpted ground — a falling sheet is not a heightfield',
    kinds_of(vw).get('waterfall') == 1 and not any(o['kind'].startswith('sculpt_') for o in vw.objs),
    (txt, kinds_of(vw)),
)
check('v3: ...and the reply says so', 'keeps its solid' in txt, txt)

# hiding the ground is the escape hatch back to the old records
txt, vh = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'CV60', 'style': 'rolling'})
vh.objs[-1]['hidden'] = True
txt, vh = assistant('add_river', {'cells': ['K10', 'K40'], 'width': 12}, drawing=vh)
check(
    'v3: a HIDDEN ground is no ground — the old solid `river` record comes back',
    kinds_of(vh).get('river') == 1 and kinds_of(vh).get('sculpt_channel') is None,
    (txt, kinds_of(vh)),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
RIVER = {'len': 60, 'w': 12, 'depth': 2, 'meander': 6, 'seed': 1, 'bank': 2, 'seg': 24}
LAKE = {'rx': 30, 'rz': 20, 'depth': 3, 'wobble': 0.25, 'seed': 1, 'seg': 48, 'shore': 3, 'rim': 1}
FALL = {'w': 8, 'h': 12, 'depth': 2, 'pool_r': 8}
REACH = {'len': 30, 'w': 12, 'depth': 2, 'meander': 6, 'seed': 1, 'bank': 2, 'seg': 24}
RZ = math.atan2(-3.0, 30.0)  # the slope above: 3 m down over a 30 m reach
CASES = [{'kind': 'river', 'p': RIVER}, {'kind': 'lake', 'p': LAKE}, {'kind': 'waterfall', 'p': FALL}]
b = browser_kinds(CASES + [{'kind': 'river', 'p': REACH, 'rz': RZ}])
B = {r['kind']: r for r in b[:3]}
tilted = b[3]
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind builds real geometry',
    all(r['ok'] and r['registered'] for r in b),
    [(r['kind'], r['ok'], r['registered'], r.get('err')) for r in b if not (r['ok'] and r['registered'])],
)

riv, lak, wat = B['river'], B['lake'], B['waterfall']
check('river runs the full 60 m of its reach', abs(riv['size'][0] - 60) < 0.6, riv)
check('river is 2 m from bank top to bed', abs(riv['size'][1] - 2) < 0.02, riv)
check('the river digs: bbox floor 2 m under the ground plane', abs(riv['min'][1] + 2) < 0.02, riv)
check('river spans bed + banks + the wander, and no more', 12 + 2 * 2 <= riv['size'][2] <= 12 + 2 * 2 + 2 * 6, riv)
zpy = RL.river_z_extent(12, 2, 6, 1, 24)
check(
    'the tab wanders exactly as the assistant says it does (%.3f m)' % zpy,
    abs(riv['size'][2] - zpy) < zpy * 0.02,
    (riv['size'][2], zpy),
)
check(
    'the river is built in three parts: the gravel channel, the grass bank tops, the water',
    riv['parts'] == 3,
    riv['parts'],
)
want_h = REACH['depth'] + REACH['len'] * abs(math.sin(RZ))
check(
    'a reach turned by rz = %.4f stands depth + len*|sin rz| = %.3f m tall' % (RZ, want_h),
    abs(tilted['size'][1] - want_h) < want_h * 0.02,
    (tilted['size'], want_h),
)
check(
    'the tilted reach still runs its full 30 m in plan (rz only lifts one end)',
    abs(tilted['size'][0] - 30 * math.cos(RZ)) < 0.6,
    tilted,
)

check('lake is 3 m deep', abs(lak['size'][1] - 3) < 3 * 0.01, lak)
check('the lake digs: bbox floor 3 m under the ground plane', abs(lak['min'][1] + 3) < 0.03, lak)
check(
    'lake rim strays inside the irregularity it was given',
    2 * 30 * (1 - 0.25) <= lak['size'][0] <= 2 * 30 * (1 + 0.25),
    lak,
)
xpy = RL.lake_x_extent(30, 0.25, 1, 48)
check(
    'the tab wobbles exactly as the assistant says it does (%.3f m)' % xpy,
    abs(lak['size'][0] - xpy) < xpy * 0.02,
    (lak['size'][0], xpy),
)
check('lake is narrower across z than across x (rz 20 < rx 30)', lak['size'][2] < lak['size'][0], lak)

check(
    'waterfall reaches 12 m up to its lip (12 of drop + 1 of rock)',
    abs((wat['min'][1] + wat['size'][1]) - 13) < 0.13,
    wat,
)
check('the plunge pool is 2 x pool_r across', abs(wat['size'][2] - 16) < 0.16, wat)
check('the plunge pool digs 2 m below the ground plane', abs(wat['min'][1] + 2) < 0.03, wat)
check('waterfall is 12 + 1 m of drop and lip plus a 2 m pool', abs(wat['size'][1] - (12 + 1 + 2)) < 15 * 0.01, wat)
check('waterfall reaches out to its plunge pool', wat['size'][0] >= 8, wat)
check(
    'labels read well',
    riv['label'] == 'River' and lak['label'] == 'Lake' and wat['label'] == 'Waterfall',
    [riv['label'], lak['label'], wat['label']],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(CASES)
FLOOR = {'river': 90, 'lake': 200, 'waterfall': 20}
for kind in NEW_KINDS:
    check(f'blender builds {kind} ({FLOOR[kind]}+ faces)', bl.get(kind, {}).get('polys', 0) > FLOOR[kind], bl.get(kind))
check(
    'blender agrees with the tab about the flat reach (2 m deep, 60 m long)',
    abs(bl['river']['size'][0] - riv['size'][0]) < 0.6 and abs(bl['river']['size'][1] - riv['size'][1]) < 0.05,
    (bl['river']['size'], riv['size']),
)
blt = blender_kinds([{'kind': 'river', 'p': REACH, 'rz': RZ}])
check(
    'blender lifts the rz-tilted reach to the SAME height as the tab (%.3f m)' % tilted['size'][1],
    abs(blt['river']['size'][1] - tilted['size'][1]) < 0.05,
    (blt['river']['size'], tilted['size']),
)

finish()
