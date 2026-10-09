# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_massing_morph.py — proof for the massing_morph family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_massing_morph.py

Three engines have to agree: the assistant's tools make the records claimed,
the tab builds each mass_* kind at exactly the size its parameters say, and
Blender builds a mesh with faces for every one of them.
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

MASSES = [
    'mass_taper',
    'mass_twist',
    'mass_setback',
    'mass_loft',
    'mass_ellipse',
    'mass_arc',
    'mass_chamfer',
    'mass_round',
    'mass_shear',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in ('draw_massing', 'morph', 'stack_storeys')), names)

# C4..L13 is a 10 x 10 m block; 20 storeys = 54 m; amount 0.5 = half at the top
txt, d = assistant(
    'draw_massing', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 20, 'style': 'taper', 'amount': 0.5}
)
o = d.objs[-1]
check('taper: ONE record, not a stack', kinds_of(d) == {'mass_taper': 1}, kinds_of(d))
check(
    'taper: h 54 from 20 storeys, w_top 5 from amount 0.5',
    o['p']['h'] == 54 and o['p']['w_top'] == 5 and o['p']['w'] == 10 and o['p']['d'] == 10 and o['y'] == 0,
    o['p'],
)
check('taper: result names the id and the size', o['id'] in txt and '54' in txt, txt)

txt, d2 = assistant(
    'draw_massing',
    {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 4, 'style': 'ellipse', 'slabs': True, 'material': 'mat_glass'},
)
k = kinds_of(d2)
check('ellipse + slabs: 1 mass, 4 slabs', k.get('mass_ellipse') == 1 and k.get('slab') == 4, k)
check(
    'ellipse: rx/rz are half the block, glass',
    d2.objs[0]['p']['rx'] == 5 and d2.objs[0]['p']['rz'] == 5 and d2.objs[0]['mat'] == 'mat_glass',
    d2.objs[0],
)

txt, _ = assistant('draw_massing', {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'blob'}, drawing=d2)
check('unknown style refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_massing', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 0}, drawing=d2)
check('zero storeys refused', txt.startswith('refused'), txt)

# morph
txt, dm = assistant('draw_massing', {'cell_from': 'A1', 'cell_to': 'J10', 'storeys': 10, 'style': 'box'})
check('style box makes a plain box', dm.objs[-1]['kind'] == 'box' and dm.objs[-1]['p']['h'] == 27, dm.objs[-1])
txt, dm = assistant('morph', {'which': 'new', 'op': 'taper', 'amount': 0.4}, drawing=dm)
o = dm.objs[-1]
check(
    'morph box -> taper keeps the footprint',
    o['kind'] == 'mass_taper' and o['p']['w'] == 10 and o['p']['w_top'] == 4 and o['p']['h'] == 27,
    (txt, o['p']),
)
txt, dm = assistant('morph', {'which': 'new', 'op': 'height', 'amount': 40}, drawing=dm)
check('morph op height sets h', dm.objs[-1]['p']['h'] == 40, (txt, dm.objs[-1]['p']))
txt, dm = assistant('morph', {'which': 'new', 'op': 'scale', 'amount': 2}, drawing=dm)
check(
    'morph op scale doubles the footprint',
    dm.objs[-1]['p']['w'] == 20 and dm.objs[-1]['p']['w_top'] == 8,
    (txt, dm.objs[-1]['p']),
)
txt, dm = assistant('morph', {'which': 'new', 'op': 'round', 'amount': 3}, drawing=dm)
check('morph -> round', dm.objs[-1]['kind'] == 'mass_round' and dm.objs[-1]['p']['r'] == 3, (txt, dm.objs[-1]['p']))

txt, dw = assistant('draw_wall', {'cell_from': 'A1', 'cell_to': 'A9'})
txt, dw = assistant('morph', {'which': 'new', 'op': 'taper'}, drawing=dw)
check('morph refuses a wall', txt.startswith('refused') and 'wall' in txt, txt)
txt, dw = assistant('morph', {'which': 'new', 'op': 'melt'}, drawing=dw)
check('unknown op refused', txt.startswith('refused'), txt)
txt, dw = assistant('morph', {'which': 'nothing_here', 'op': 'taper'}, drawing=dw)
check('empty selection refused', txt.startswith('refused'), txt)

# stack_storeys: a one-storey box is 4 walls + 1 slab = 5 objects
txt, ds = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'H9', 'storeys': 1, 'slabs': True, 'name': 'gf'})
before = len(ds.objs)
check('the ground floor is 5 objects', before == 5, kinds_of(ds))
txt, ds = assistant('stack_storeys', {'which': 'gf', 'count': 3}, drawing=ds)
made = ds.objs[before:]
ys = sorted({round(r['y'], 4) for r in made})
check('stack x3 of 5 objects adds 15', len(ds.objs) - before == 15 and '15' in txt, (len(ds.objs) - before, txt))
check(
    '...at 2.7 m steps, same group', ys == [2.7, 5.4, 8.1] and all(r['grp'] == 'gf' for r in made), (ys, made[0]['grp'])
)
txt, ds = assistant('stack_storeys', {'which': 'gf', 'count': 0}, drawing=ds)
check('count 0 refused', txt.startswith('refused'), txt)

txt, ds = assistant('add_object', {'kind': 'mass_twist', 'cell': 'A1', 'params': {'twist': 120}}, drawing=ds)
check('add_object knows the new kinds', ds.objs[-1]['kind'] == 'mass_twist' and ds.objs[-1]['p']['twist'] == 120, txt)
check('rail lists all nine kinds', rail_has(MASSES) == [], rail_has(MASSES))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'mass_taper', 'p': {'w': 10, 'd': 10, 'h': 54, 'w_top': 5, 'd_top': 5}},
    {'kind': 'mass_twist', 'p': {'w': 10, 'd': 10, 'h': 27, 'twist': 90, 'seg': 10}},
    {'kind': 'mass_setback', 'p': {'w': 12, 'd': 12, 'h': 27, 'steps': 3, 'step_in': 2}},
    {'kind': 'mass_loft', 'p': {'w': 10, 'd': 10, 'h': 27, 'seg': 24}},
    {'kind': 'mass_ellipse', 'p': {'rx': 6, 'rz': 4, 'h': 27, 'seg': 48}},
    {'kind': 'mass_arc', 'p': {'r': 20, 'a0': 0, 'a1': 90, 'w': 12, 'h': 27, 'seg': 32}},
    {'kind': 'mass_chamfer', 'p': {'w': 10, 'd': 10, 'h': 27, 'c': 1.0}},
    {'kind': 'mass_round', 'p': {'w': 10, 'd': 10, 'h': 27, 'r': 2}},
    {'kind': 'mass_shear', 'p': {'w': 10, 'd': 10, 'h': 27, 'shear_x': 3, 'shear_z': 0}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(r.get('page_errors') for r in b), [r.get('page_errors') for r in b])
check(
    'every kind is registered and builds real geometry',
    all(by.get(k, {}).get('ok') and by[k]['registered'] for k in MASSES),
    {k: (by.get(k, {}).get('ok'), by.get(k, {}).get('err')) for k in MASSES},
)


def size(k):
    return by[k]['size']


def near(a, b_, tol=0.05):
    return abs(a - b_) < tol


check(
    'mass_taper: 10 x 54 x 10 (the base wins)',
    near(size('mass_taper')[0], 10) and near(size('mass_taper')[1], 54) and near(size('mass_taper')[2], 10),
    size('mass_taper'),
)
check(
    'mass_twist: 27 tall, plan span between 10 and 14.2 (90 deg of turn)',
    near(size('mass_twist')[1], 27) and 10.0 < size('mass_twist')[0] < 14.2 and 10.0 < size('mass_twist')[2] < 14.2,
    size('mass_twist'),
)
check(
    'mass_setback: 12 x 27 x 12',
    near(size('mass_setback')[0], 12) and near(size('mass_setback')[1], 27) and near(size('mass_setback')[2], 12),
    size('mass_setback'),
)
check(
    'mass_loft: 10 x 27 x 10',
    near(size('mass_loft')[0], 10) and near(size('mass_loft')[1], 27) and near(size('mass_loft')[2], 10),
    size('mass_loft'),
)
check(
    'mass_ellipse: 12 x 27 x 8 (2rx by 2rz)',
    near(size('mass_ellipse')[0], 12) and near(size('mass_ellipse')[1], 27) and near(size('mass_ellipse')[2], 8),
    size('mass_ellipse'),
)
check(
    'mass_arc: 27 tall, quarter arc reaching r + w/2 = 26',
    near(size('mass_arc')[1], 27) and near(size('mass_arc')[0], 26, 0.3) and near(size('mass_arc')[2], 26, 0.3),
    size('mass_arc'),
)
check(
    'mass_chamfer: 10 x 27 x 10',
    near(size('mass_chamfer')[0], 10) and near(size('mass_chamfer')[1], 27) and near(size('mass_chamfer')[2], 10),
    size('mass_chamfer'),
)
check(
    'mass_round: 10 x 27 x 10 (r 2 does not shrink the box)',
    near(size('mass_round')[0], 10) and near(size('mass_round')[1], 27) and near(size('mass_round')[2], 10),
    size('mass_round'),
)
check(
    'mass_shear: 13 x 27 x 10 (top slid 3 m in x)',
    near(size('mass_shear')[0], 13) and near(size('mass_shear')[1], 27) and near(size('mass_shear')[2], 10),
    size('mass_shear'),
)
check(
    'mass_round is rounder than mass_chamfer is chamfered',
    by['mass_round']['tris'] > by['mass_chamfer']['tris'] > 12,
    (by['mass_round']['tris'], by['mass_chamfer']['tris']),
)
check(
    'labels',
    by['mass_taper']['label'] == 'Tapered mass' and by['mass_arc']['label'] == 'Arc mass',
    (by['mass_taper']['label'], by['mass_arc']['label']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
# Blender on this machine sometimes dies on startup inside an unrelated add-on
# (ifcopenshell -> "No module named 'shapely'", then SIGBUS), which leaves the
# harness's poly count empty and would fail every kind at once for a reason
# that has nothing to do with this family. Two more attempts, then believe it.
print('blender')
bl = {}
for _try in range(3):
    try:
        bl = blender_kinds(cases)
    except RuntimeError as e:
        print(f'  .. blender attempt {_try + 1} died: {str(e)[-120:]}', flush=True)
        continue
    if any(bl.get(k, {}).get('polys', 0) > 0 for k in MASSES):
        break
    print(f'  .. blender attempt {_try + 1} returned no meshes, retrying', flush=True)
for kind in MASSES:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
check(
    'blender: the twist really is a stack of segments',
    bl.get('mass_twist', {}).get('polys', 0) >= 10 * 4,
    bl.get('mass_twist'),
)
finish()
