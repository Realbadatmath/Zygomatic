# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_landmarks_special.py — the landmarks_special family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_landmarks_special.py
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
    'windmill',
    'lighthouse',
    'water_tower',
    'silo',
    'geodesic_dome',
    'tent',
    'gazebo',
    'obelisk',
    'arch_monument',
    'spire',
    'minaret',
    'stadium_ring',
    'wind_turbine',
    'pyramid_stepped',
    'ferris_wheel',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
check('add_landmark registered', 'add_landmark' in tool_names(), tool_names())

txt, d = assistant('add_landmark', {'kind': 'windmill', 'cell': 'D12'})
o = d.objs[-1]
check(
    'windmill placed, one record, default params',
    kinds_of(d) == {'windmill': 1}
    and o['p'] == {'h': 12, 'r': 3, 'cap': 2, 'sails': 4, 'sail_len': 8}
    and o['y'] == 0
    and o['grp'] == 'landmarks'
    and o['id'] in txt,
    (txt, o),
)
from zyg_workflows.arch_assistant import cell_centre, parse_cell  # noqa: E402

cx, cz = cell_centre(*parse_cell('D12'))
check('...at the centre of D12', abs(o['x'] - cx) < 1e-6 and abs(o['z'] - cz) < 1e-6, (o['x'], o['z'], cx, cz))

txt, d = assistant('add_landmark', {'kind': 'windmill', 'cell': 'E12', 'size': 16}, drawing=d)
p = d.objs[-1]['p']
check(
    'size 16 scales every length, never the counts',
    p['h'] == 16 and abs(p['r'] - 4) < 1e-4 and abs(p['cap'] - 8 / 3) < 1e-3 and p['sails'] == 4,
    p,
)

txt, d = assistant('add_landmark', {'kind': 'geodesic_dome', 'cell': 'F4', 'size': 12}, drawing=d)
p = d.objs[-1]['p']
check('dome size is its RADIUS, detail is a count', p['r'] == 12 and p['detail'] == 1, p)

txt, d = assistant(
    'add_landmark',
    {'kind': 'lighthouse', 'cell': 'G9', 'storey': 2, 'rotation_deg': 90, 'material': 'mat_stone'},
    drawing=d,
)
o = d.objs[-1]
check(
    'storey, rotation and material carried',
    abs(o['y'] - 5.4) < 1e-6 and abs(o['ry'] - math.pi / 2) < 1e-6 and o['mat'] == 'mat_stone',
    o,
)

txt, d = assistant('add_landmark', {'kind': 'stadium_ring', 'cell': 'BB100', 'size': 80}, drawing=d)
p = d.objs[-1]['p']
check(
    'stadium size is rx, rz follows, tiers stay a count',
    p['rx'] == 80 and abs(p['rz'] - 60) < 1e-3 and p['tiers'] == 3 and abs(p['tier_d'] - 10.6667) < 1e-3,
    p,
)

n_before = len(d.objs)
txt, d = assistant('add_landmark', {'kind': 'obelix', 'cell': 'C4'}, drawing=d)
check('unknown kind refused', txt.startswith('refused') and len(d.objs) == n_before, txt)
txt, d = assistant('add_landmark', {'kind': 'silo', 'cell': 'ZZ999'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused') and len(d.objs) == n_before, txt)
txt, d = assistant('add_landmark', {'kind': 'silo', 'cell': 'C4', 'size': 900}, drawing=d)
check('absurd size refused', txt.startswith('refused') and len(d.objs) == n_before, txt)

txt, d = assistant('add_object', {'kind': 'ferris_wheel', 'cell': 'A1', 'params': {'r': 9}}, drawing=d)
check('add_object accepts the new kinds', d.objs[-1]['kind'] == 'ferris_wheel' and d.objs[-1]['p']['r'] == 9, txt)

missing = rail_has(KINDS)
check('rail lists all 15 kinds', missing == [], missing)

# ── R7: real sizes, absolute metres (2026-09-07) ──────────────────────────────
print('R7 real sizes')
txt, dw = assistant('add_landmark', {'kind': 'windmill', 'cell': 'C4', 'size': 12})
check(
    "a windmill's size is the TOWER height: 12 m tower -> 7.8 m sails (0.65 x)",
    dw.objs[-1]['p']['h'] == 12 and abs(dw.objs[-1]['p']['sail_len'] - 7.8) < 1e-4,
    dw.objs[-1]['p'],
)
txt, dw = assistant('add_landmark', {'kind': 'windmill', 'cell': 'C6', 'size': 16}, drawing=dw)
check(
    'a 16 m tower gets 6 m sails: 22 m overall is the ceiling, not 0.65 x 16',
    abs(dw.objs[-1]['p']['sail_len'] - 6.0) < 1e-6,
    dw.objs[-1]['p'],
)
from zyg_workflows.arch_assistant_ext.landmarks_special import sail_len_for  # noqa: E402

over = [(h, sail_len_for(h)) for h in (8, 10, 12, 13.5, 15, 16) if h + sail_len_for(h) > 22.0 + 1e-9]
check(
    'no legal tower (8-16 m) can build a mill over 22 m overall',
    over == [],
    [(h, sail_len_for(h), h + sail_len_for(h)) for h in (8, 10, 12, 13.5, 15, 16)],
)
n0 = len(dw.objs)
txt, dw = assistant('add_landmark', {'kind': 'windmill', 'cell': 'C8', 'size': 7.5}, drawing=dw)
check(
    'a 7.5 m windmill refused, and the refusal says the real range',
    txt.startswith('refused')
    and 'a Dutch windmill tower is 8-16 m; sails are added on top' in txt
    and len(dw.objs) == n0,
    txt,
)
txt, dw = assistant('add_landmark', {'kind': 'windmill', 'cell': 'C8', 'size': 66.7}, drawing=dw)
check('the 66.7 m windmill of the polder drawing is refused', txt.startswith('refused') and len(dw.objs) == n0, txt)

RANGES = {
    'lighthouse': (12, 40),
    'water_tower': (10, 30),
    'silo': (6, 25),
    'wind_turbine': (30, 150),
    'obelisk': (5, 40),
    'ferris_wheel': (8, 40),
}
for k, (lo, hi) in RANGES.items():
    t_lo, dr = assistant('add_landmark', {'kind': k, 'cell': 'C4', 'size': lo * 0.5})
    t_hi, dr = assistant('add_landmark', {'kind': k, 'cell': 'C6', 'size': hi * 1.5}, drawing=dr)
    t_ok, dr = assistant('add_landmark', {'kind': k, 'cell': 'C8', 'size': (lo + hi) / 2}, drawing=dr)
    check(
        f'{k}: {lo}-{hi} m enforced, both refusals name the range, the middle is drawn',
        t_lo.startswith('refused')
        and t_hi.startswith('refused')
        and f'{lo:g}-{hi:g}' in t_lo
        and f'{lo:g}-{hi:g}' in t_hi
        and not t_ok.startswith('refused')
        and len(dr.objs) == 1,
        (t_lo, t_hi, t_ok),
    )

# ── R5: a landmark stands on the ground under it ──────────────────────────────
print('R5 ground placement')
txt, dg = assistant('add_object', {'kind': 'berm', 'cell': 'P30', 'params': {'len': 20, 'w': 4, 'h': 1.2}})
berm = dg.objs[-1]
bx, bz = berm['x'], berm['z']
from zyg_workflows.arch_assistant import cell_of  # noqa: E402

crest, flank, off = cell_of(bx + 5, bz), cell_of(bx + 5, bz + 1), cell_of(bx + 5, bz + 6)
check(
    'the dyke is there: crest 1.2 m, flank 0.6 m, beside it 0 m',
    abs(A.ground_height(dg, bx + 5, bz) - 1.2) < 1e-6
    and abs(A.ground_height(dg, bx + 5, bz + 1) - 0.6) < 1e-6
    and A.ground_height(dg, bx + 5, bz + 6) == 0.0,
    [A.ground_height(dg, bx + 5, bz + q) for q in (0, 1, 6)],
)
txt, dg = assistant('add_landmark', {'kind': 'windmill', 'cell': crest}, drawing=dg)
mill = dg.objs[-1]
check(
    'a windmill on the dyke crest lands ON it (y = 1.2, not 0)',
    abs(mill['y'] - 1.2) < 1e-6 and abs(mill['y'] - A.ground_height(dg, mill['x'], mill['z'])) < 1e-9,
    (mill['y'], A.ground_height(dg, mill['x'], mill['z'])),
)
check('the reply says it is standing on the ground', 'on the ground' in txt, txt)
txt, dg = assistant('add_landmark', {'kind': 'silo', 'cell': flank}, drawing=dg)
check('a silo on the dyke flank lands on the flank (y = 0.6)', abs(dg.objs[-1]['y'] - 0.6) < 1e-6, dg.objs[-1]['y'])
txt, dg = assistant('add_landmark', {'kind': 'silo', 'cell': off}, drawing=dg)
check('beside the dyke it is still on the base plane (y = 0)', dg.objs[-1]['y'] == 0.0, dg.objs[-1]['y'])
txt, dg = assistant('add_landmark', {'kind': 'obelisk', 'cell': crest, 'base_height': 0}, drawing=dg)
check('base_height overrides the ground', dg.objs[-1]['y'] == 0.0, dg.objs[-1]['y'])
txt, dg = assistant('add_landmark', {'kind': 'obelisk', 'cell': crest, 'storey': 1}, drawing=dg)
check('a storey lift adds ON TOP of the ground (1.2 + 2.7)', abs(dg.objs[-1]['y'] - 3.9) < 1e-6, dg.objs[-1]['y'])

txt, dh = assistant('add_hill', {'centre': 'P60', 'radius': 12, 'height': 6})
hx, hz = dh.objs[-1]['x'], dh.objs[-1]['z']
txt, dh = assistant('add_landmark', {'kind': 'lighthouse', 'cell': cell_of(hx + 6, hz)}, drawing=dh)
lh = dh.objs[-1]
check(
    'a lighthouse on a hill flank sits at the hill surface (R8: buried by no more than 0.3 m)',
    abs(lh['y'] - A.ground_height(dh, lh['x'], lh['z'])) < 0.3 and lh['y'] > 2.0,
    (lh['y'], A.ground_height(dh, lh['x'], lh['z'])),
)
txt, dh = assistant('add_landmark', {'kind': 'water_tower', 'cell': cell_of(hx, hz)}, drawing=dh)
txt, dh = assistant('add_landmark', {'kind': 'silo', 'cell': cell_of(hx - 9, hz + 3)}, drawing=dh)
txt, dh = assistant('add_landmark', {'kind': 'obelisk', 'cell': cell_of(hx + 20, hz)}, drawing=dh)
marks = [o for o in dh.objs if o['grp'] == 'landmarks']
check(
    'R8 nothing buried, nothing floating: all 4 landmarks on the hill match their ground within 0.3 m',
    len(marks) == 4 and all(abs(o['y'] - A.ground_height(dh, o['x'], o['z'])) < 0.3 for o in marks),
    [(o['id'], o['y'], round(A.ground_height(dh, o['x'], o['z']), 4)) for o in marks],
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [{'kind': k, 'p': {}} for k in KINDS] + [
    {'kind': 'windmill', 'p': {'h': 16, 'r': 4, 'cap': 2.6667, 'sails': 4, 'sail_len': sail_len_for(16)}}
]
b = browser_kinds(cases)
by = {}
for i, k in enumerate(KINDS):
    by[k] = b[i]
big_mill = b[len(KINDS)]
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b][:1])
check(
    'every kind builds real geometry (not the marker cube)',
    all(by[k]['ok'] and by[k]['registered'] for k in KINDS),
    [(k, by[k]['ok'], by[k]['registered'], by[k].get('err')) for k in KINDS if not by[k]['ok']],
)
check(
    'every kind stays under 40000 triangles',
    all(by[k]['tris'] < 40000 for k in KINDS),
    {k: by[k]['tris'] for k in KINDS},
)

w = by['windmill']['size']
check('windmill h 12 + sails 8: tall enough and 2x sail_len wide', w[1] >= 14 and w[0] >= 8, w)
check(
    'lighthouse h 20 + lantern 2.5 = 22.5 m', abs(by['lighthouse']['size'][1] - 22.5) < 0.05, by['lighthouse']['size']
)
check('water tower total height h = 15', abs(by['water_tower']['size'][1] - 15) < 0.05, by['water_tower']['size'])
check(
    'silo h 12 + cone 2 = 14, 6 m across',
    abs(by['silo']['size'][1] - 14) < 0.05 and abs(by['silo']['size'][0] - 6) < 0.05,
    by['silo']['size'],
)
gd = by['geodesic_dome']['size']
check(
    'geodesic dome r 8 -> 16 x 8 x 16', abs(gd[0] - 16) < 0.05 and abs(gd[1] - 8) < 0.05 and abs(gd[2] - 16) < 0.05, gd
)
check(
    'tent r 6 h 5 -> 5 m tall, 12 m across',
    abs(by['tent']['size'][1] - 5) < 0.05 and by['tent']['size'][0] > 11.0,
    by['tent']['size'],
)
check('gazebo h 2.6 + roof 1.2 = 3.8', abs(by['gazebo']['size'][1] - 3.8) < 0.05, by['gazebo']['size'])
check(
    'obelisk h 10, w 1.2 square',
    abs(by['obelisk']['size'][1] - 10) < 0.05 and abs(by['obelisk']['size'][0] - 1.2) < 0.02,
    by['obelisk']['size'],
)
am = by['arch_monument']['size']
check('arch monument 8 x 10 x 3', abs(am[0] - 8) < 0.02 and abs(am[1] - 10) < 0.02 and abs(am[2] - 3) < 0.02, am)
check('spire h 12', abs(by['spire']['size'][1] - 12) < 0.05, by['spire']['size'])
check('minaret h 25', abs(by['minaret']['size'][1] - 25) < 0.05, by['minaret']['size'])
sr = by['stadium_ring']['size']
check(
    'stadium ring rx 60 rz 45 tiers 3 x 4 -> 120 x 12 x 90',
    abs(sr[0] - 120) < 1 and abs(sr[1] - 12) < 1 and abs(sr[2] - 90) < 1,
    sr,
)
check('wind turbine h 60 + blade 30 -> tip at ~90 m', by['wind_turbine']['size'][1] > 88, by['wind_turbine']['size'])
ps = by['pyramid_stepped']['size']
check('stepped pyramid 30 x 20 x 30', abs(ps[0] - 30) < 0.05 and abs(ps[1] - 20) < 0.05 and abs(ps[2] - 30) < 0.05, ps)
fw = by['ferris_wheel']['size']
check(
    'ferris wheel r 15 -> 30 m rim + cabins across, standing over 30 m tall',
    abs(fw[0] - 31.35) < 0.3 and 30.0 < fw[1] < 34.0,
    fw,
)
check(
    'labels come from the family',
    by['windmill']['label'] == 'Windmill'
    and by['stadium_ring']['label'] == 'Stadium ring'
    and by['arch_monument']['label'] == 'Monumental arch',
    (by['windmill']['label'], by['stadium_ring']['label'], by['arch_monument']['label']),
)
check(
    'the biggest legal windmill (16 m tower, 6 m sails) builds and stops at 22 m',
    big_mill['ok'] and abs(big_mill['size'][1] - 22.0) < 0.3,
    big_mill.get('size'),
)
check(
    'R8: the default windmill (12 m tower + 8 m sails) is under 22 m overall',
    by['windmill']['size'][1] <= 22.0,
    by['windmill']['size'],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds([{'kind': k, 'p': {}} for k in KINDS])
bad = [k for k in KINDS if bl.get(k, {}).get('polys', 0) <= 0]
check('blender builds all 15 kinds with faces', not bad, (bad, {k: bl.get(k) for k in bad}))
check(
    'blender polygon counts are sane (< 20000 each)',
    all(bl[k]['polys'] < 20000 for k in KINDS if k in bl),
    {k: bl.get(k, {}).get('polys') for k in KINDS},
)

finish()
