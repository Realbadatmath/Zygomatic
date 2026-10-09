#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""water_v3 — the proof (2026-09-07).

Three engines have to agree that water is a thin two-sided translucent skin that
sits ON the v3 sculpted bed, and the assistant has to put the bed and the skin
down together, at the height the hollow gives them.

Run:  "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_water_v3.py
"""

import copy
import importlib.util
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zyg_workflows.arch_ext_harness import (  # noqa: E402
    check,
    finish,
    assistant,
    kinds_of,
    tool_names,
    rail_has,
    browser_kinds,
    blender_kinds,
)
from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows import architecture_studio as ST  # noqa: E402
import zyg_workflows.arch_assistant_ext.water_v3 as W  # noqa: E402
import zyg_workflows.arch_assistant_ext.ground_v3 as G  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load(os.path.join(ROOT, 'arch_blender_ext', 'water_v3.py'), 'blext_water_v3')
JS = open(os.path.join(ROOT, 'arch_ext', 'water_v3.js'), encoding='utf-8').read()
HTML = open(os.path.join(ROOT, 'inspection.html'), encoding='utf-8').read()

KINDS = ['water_body', 'water_path', 'water_plane']
DOC = {'objects': [], 'cell_m': 10}  # 10 m cells: a landscape, not a room


def flat_ground(base=200.0):
    """A drawing whose ground is EXACTLY `base` metres everywhere — amp 0 takes
    the base noise out, so every height in this test is an exact number and the
    ±1e-6 tolerances below mean what they say. (ground_height() floors at 0, so
    the ground has to be high enough that a lake bed stays above it.)"""
    txt, d = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'Z30'}, doc=dict(DOC))
    g = [o for o in d.objs if o['kind'] == 'ground'][0]
    g['p']['amp'] = 0.0
    g['p']['base'] = base
    return d, g


def recs(d, kind):
    return [o for o in d.objs if o['kind'] == kind]


# ── 1. the family is wired in ────────────────────────────────────────────────
names = tool_names()
for t in ('fill_lake', 'carve_river', 'fill_sea'):
    check(f'assistant offers {t}', t in names, names[-8:])
check('rail lists the three water kinds', rail_has(KINDS) == [], rail_has(KINDS))
check('KINDS declares the three kinds', sorted(W.KINDS) == sorted(KINDS), sorted(W.KINDS))
check('no opening kinds here', W.OPENINGS == [], W.OPENINGS)
check('Blender registers the three kinds', sorted(B.BUILDERS) == sorted(KINDS), sorted(B.BUILDERS))
for k in KINDS:
    check(f'{k} has a tab geometry fn', f'AR_EXT.geom.{k} = function' in JS)
    check(f'{k} has a tab label', f'AR_EXT.label.{k} =' in JS)

# ── 2. the water is a two-sided translucent skin ─────────────────────────────
BLPY = open(os.path.join(ROOT, 'arch_blender_ext', 'water_v3.py'), encoding='utf-8').read()


def js_geom(kind):
    """The body of one AR_EXT.geom fn — the code, not the essay above it."""
    i = JS.index(f'AR_EXT.geom.{kind} = function')
    return JS[i : JS.index('AR_EXT.', i + 20)]


check(
    'every tab part is sub mat_water',
    all("sub: 'mat_water'" in js_geom(k) for k in KINDS),
    {k: "sub: 'mat_water'" in js_geom(k) for k in KINDS},
)
check(
    'every Blender face is on the mat_water slot',
    BLPY.count("return ('', ['mat_water'])") == 3 and 'f.material_index = 1' in BLPY,
    BLPY.count("return ('', ['mat_water'])"),
)
site = dict(ST.MATERIALS)['Site']
water = [m for m in site if m[0] == 'mat_water'][0]
check('mat_water is translucent (op < 1)', 0 < water[2].get('op', 1.0) < 1.0, water[2])
check('arMat makes every preset two-sided', 'side:THREE.DoubleSide' in HTML)
check('arMat makes an op preset transparent', 'transparent:!!d.op' in HTML)
check('a water skin is 0.02 m thick', abs(W.WATER_T - 0.02) < 1e-12 and abs(B.WATER_T - 0.02) < 1e-12)

# ── 3. the shoreline arithmetic is one arithmetic ────────────────────────────
worst_m = max(abs(W.meander_offset(i / 37.0, 6.0, 3.0) - G.meander_offset(i / 37.0, 6.0, 3.0)) for i in range(38))
worst_b = max(abs(B.meander_offset(i / 37.0, 6.0, 3.0) - G.meander_offset(i / 37.0, 6.0, 3.0)) for i in range(38))
check('meander_offset == ground_v3 (assistant)', worst_m == 0.0, worst_m)
check('meander_offset == ground_v3 (Blender)', worst_b == 0.0, worst_b)
worst_l = max(abs(W.lake_factor(i * 0.17, 0.25, 2.0) - G.lake_factor(i * 0.17, 0.25, 2.0)) for i in range(40))
worst_lb = max(abs(B.lake_factor(i * 0.17, 0.25, 2.0) - G.lake_factor(i * 0.17, 0.25, 2.0)) for i in range(40))
check('lake_factor == ground_v3 (assistant)', worst_l == 0.0, worst_l)
check('lake_factor == ground_v3 (Blender)', worst_lb == 0.0, worst_lb)
check('value_noise == ground_v3', W.value_noise(1.7, -2.3, 5) == G.value_noise(1.7, -2.3, 5))
check('the JS keeps the noise verbatim', 'Math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453' in JS)
check(
    'the JS keeps the meander verbatim',
    '0.6 * Math.sin(2 * Math.PI * t * 1.5)' in JS and '0.4 * (2 * vnoise(t * 4, seed, seed) - 1)' in JS,
)
check('the JS keeps the lake rim verbatim', 'vnoise(Math.cos(a) * 2 + 2, Math.sin(a) * 2 + 2, seed)' in JS)
check(
    'water_plane has no -0.3 baseline left in its code',
    '-0.3' not in js_geom('water_plane')
    and '-0.3' not in JS[JS.index('function sheetSkin') : JS.index('/* ── the three kinds')],
    'the sea datum is the record y now, not a hardcoded -0.3',
)
check('the Blender sea has no -0.3 baseline either', '-0.3' not in BLPY.split('def build_water_plane')[1])

# ── 4. all three refuse without a ground ─────────────────────────────────────
txt, _ = assistant('fill_lake', {'centre': 'F6', 'radius': 30, 'depth': 4}, doc=dict(DOC))
check(
    'fill_lake refuses without a ground, in the agreed words',
    txt == 'refused: no sculpted ground — call make_ground first, or use add_lake for the old solid lake',
    txt,
)
txt, _ = assistant('carve_river', {'cells': ['C3', 'J10'], 'width': 10}, doc=dict(DOC))
check('carve_river refuses without a ground', txt.startswith('refused: no sculpted ground'), txt)
check('and points at the old solid river', 'add_river' in txt, txt)
txt, _ = assistant('fill_sea', {'cell_from': 'A1', 'cell_to': 'E30'}, doc=dict(DOC))
check('fill_sea refuses without a ground', txt.startswith('refused: no sculpted ground'), txt)
check('and points at the old solid sea', 'add_sea' in txt, txt)

# ── 5. base_height is NOT an argument: water sits where the hollow puts it ───
for tool, args in (
    ('fill_lake', {'centre': 'F6', 'radius': 30, 'depth': 4}),
    ('carve_river', {'cells': ['C3', 'J10'], 'width': 10}),
    ('fill_sea', {'cell_from': 'A1', 'cell_to': 'E30'}),
):
    d, _g = flat_ground()
    bad = dict(args)
    bad['base_height'] = 3
    txt, _ = assistant(tool, bad, drawing=d)
    check(f'{tool} has no base_height argument', txt.startswith(f'bad arguments for {tool}'), txt)
check('no schema offers base_height', not any('base_height' in str(t[0]['input_schema']) for t in W.TOOLS))

# ── 6. real sizes ────────────────────────────────────────────────────────────
d, _g = flat_ground()
for args, why in (
    ({'centre': 'F6', 'radius': 2, 'depth': 4}, 'a 2 m lake'),
    ({'centre': 'F6', 'radius': 400, 'depth': 4}, 'a 400 m lake'),
    ({'centre': 'F6', 'radius': 30, 'depth': 40}, 'a 40 m deep lake'),
):
    txt, _ = assistant('fill_lake', args, drawing=d)
    check(f'fill_lake refuses {why}', txt.startswith('refused:'), txt)
for args, why in (
    ({'cells': ['C3', 'J10'], 'width': 0.4}, 'a 0.4 m river'),
    ({'cells': ['C3', 'J10'], 'width': 50}, 'a 50 m river'),
    ({'cells': ['C3', 'J10'], 'width': 10, 'depth': 9}, 'a 9 m deep river'),
    ({'cells': ['C3'], 'width': 10}, 'a river with one cell'),
):
    txt, _ = assistant('carve_river', args, drawing=d)
    check(f'carve_river refuses {why}', txt.startswith('refused:'), txt)
for args, why in (
    ({'cell_from': 'A1', 'cell_to': 'E30', 'depth': 900}, 'a 900 m deep sea'),
    ({'cell_from': 'A1', 'cell_to': 'E30', 'level': 9000}, 'a sea 9 km up'),
):
    txt, _ = assistant('fill_sea', args, drawing=d)
    check(f'fill_sea refuses {why}', txt.startswith('refused:'), txt)
check('nothing was drawn by the refusals', kinds_of(d) == {'ground': 1}, kinds_of(d))

# ── 7. fill_lake: one bed, one skin, at bed + 0.8 x depth ───────────────────
d, g = flat_ground(200.0)
with A._Scale(d.cell_m):  # cell_centre is scale-sensitive; this doc is 10 m cells
    cx, cz = A.cell_centre(*A.parse_cell('F6'))
g0 = A.ground_height(d, cx, cz)
check('the test ground is exactly 200 m', abs(g0 - 200.0) < 1e-9, g0)
DEP = 5.0
txt, d = assistant(
    'fill_lake', {'centre': 'F6', 'radius': 30, 'radius_z': 22, 'depth': DEP, 'irregularity': 0.3, 'seed': 7}, drawing=d
)
check('fill_lake drew something', not txt.startswith('refused'), txt)
k = kinds_of(d)
check('exactly one sculpt_basin', k.get('sculpt_basin') == 1, k)
check('exactly one water_body', k.get('water_body') == 1, k)
check('and no old solid lake kind', 'lake' not in k, k)
bed, wat = recs(d, 'sculpt_basin')[0], recs(d, 'water_body')[0]
check('the bed sits at y = 0 (it is a delta, not a plinth)', bed['y'] == 0.0, bed['y'])
check('the water is at ground - 0.2 x depth', abs(wat['y'] - (g0 - 0.2 * DEP)) < 1e-6, (wat['y'], g0 - 0.2 * DEP))
after = A.ground_height(d, cx, cz)
check('the basin cut the ground through the seam: ground - depth', abs(after - (g0 - DEP)) < 1e-6, (after, g0 - DEP))
check('so the water is 0.8 x depth above its bed', abs((wat['y'] - after) - 0.8 * DEP) < 1e-6, wat['y'] - after)
check(
    'bed and skin share a shoreline',
    (bed['p']['rx'], bed['p']['rz'], bed['p']['wobble'], bed['p']['seed'])
    == (wat['p']['rx'], wat['p']['rz'], wat['p']['wobble'], wat['p']['seed']),
    (bed['p'], wat['p']),
)
check('bed and skin share a centre', (bed['x'], bed['z']) == (wat['x'], wat['z']))
check('the skin is water material', wat['mat'] == 'mat_water', wat['mat'])
check('the bed is soil', bed['mat'] == 'mat_soil', bed['mat'])
check('the reply names the level and the bed', '199.000' in txt and '195.000' in txt, txt)
check('hiding the bed puts the land back', True)
bed['hidden'] = True
check('a hidden bed leaves no hollow', abs(A.ground_height(d, cx, cz) - g0) < 1e-6, A.ground_height(d, cx, cz))
bed['hidden'] = False

# ── 8. carve_river: a bed and a reach per leg, and water that never climbs ───
txt, d2 = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'Z30', 'style': 'rolling'}, doc=dict(DOC))
gr = [o for o in d2.objs if o['kind'] == 'ground'][0]
gr['p']['base'] = 60.0  # keep the whole reach above the 0 floor
txt, d2 = assistant('raise_ground', {'cell_from': 'B2', 'cell_to': 'H8', 'height': 25}, drawing=d2)
check('a sculpt_peak stands beside the river', kinds_of(d2).get('sculpt_peak') == 1, txt)
CELLS = ['C3', 'H8', 'M13', 'R18', 'V22']
txt, d2 = assistant('carve_river', {'cells': CELLS, 'width': 10, 'depth': 2, 'seed': 3}, drawing=d2)
check('carve_river drew something', not txt.startswith('refused'), txt)
txt2 = txt  # section 13 reads the fall out of it
d2r = copy.deepcopy(d2)  # the ONE river, before the stream below
k2 = kinds_of(d2)  # joins it and cuts its own bed 0.5 m deeper
check('one sculpt_channel per reach', k2.get('sculpt_channel') == len(CELLS) - 1, k2)
check('one water_path per reach', k2.get('water_path') == len(CELLS) - 1, k2)
beds, paths = recs(d2, 'sculpt_channel'), recs(d2, 'water_path')
check('every bed sits at y = 0', all(b['y'] == 0.0 for b in beds), [b['y'] for b in beds])
lv = [p['y'] for p in paths]
check('the water never climbs', all(lv[i] <= lv[i - 1] + 1e-12 for i in range(1, len(lv))), lv)
check('it does fall somewhere', lv[0] > lv[-1] + 1e-9, lv)
check(
    "every reach's water is 0.8 x depth above its own SET bed at the start",
    all(abs(p['y'] - (G.channel_levels(b['p'])[0] + 0.8 * 2.0)) < 1e-9 for b, p in zip(beds, paths)),
    [(G.channel_levels(b['p']), p['y']) for b, p in zip(beds, paths)],
)
check(
    'bed and reach share a wander',
    all(
        (b['p']['len'], b['p']['meander'], b['p']['seed'], b['p']['w'])
        == (p['p']['len'], p['p']['meander'], p['p']['seed'], p['p']['w'])
        for b, p in zip(beds, paths)
    ),
    [(b['p'], p['p']) for b, p in zip(beds, paths)][:1],
)
check(
    'bed and reach share a centre and a bearing',
    all((b['x'], b['z'], b['ry']) == (p['x'], p['z'], p['ry']) for b, p in zip(beds, paths)),
)
with A._Scale(d2.cell_m):
    p0 = A.cell_centre(*A.parse_cell(CELLS[0]))
    p1 = A.cell_centre(*A.parse_cell(CELLS[1]))
check(
    'a reach spans its two cells',
    abs(beds[0]['p']['len'] - math.hypot(p1[0] - p0[0], p1[1] - p0[1])) < 1e-3,
    beds[0]['p']['len'],
)
check('the reply names the fall', 'falls' in txt and 'never climbs' in txt, txt)
check(
    'a stream is allowed too',
    not assistant('carve_river', {'cells': ['C3', 'H8'], 'width': 2, 'depth': 0.5}, drawing=d2)[0].startswith(
        'refused'
    ),
)

# ── 9. fill_sea ─────────────────────────────────────────────────────────────
d3, _g = flat_ground(20.0)
txt, d3 = assistant('fill_sea', {'cell_from': 'A1', 'cell_to': 'E30', 'depth': 8, 'level': -0.3}, drawing=d3)
check('fill_sea drew something', not txt.startswith('refused'), txt)
k3 = kinds_of(d3)
check('exactly one sculpt_shelf', k3.get('sculpt_shelf') == 1, k3)
check('exactly one water_plane', k3.get('water_plane') == 1, k3)
shelf, sea = recs(d3, 'sculpt_shelf')[0], recs(d3, 'water_plane')[0]
check('the sea bed sits at y = 0', shelf['y'] == 0.0, shelf['y'])
check('the sea is at the level asked for', abs(sea['y'] - (-0.3)) < 1e-9, sea['y'])
check(
    'bed and sea cover the same block',
    (shelf['p']['w'], shelf['p']['d']) == (sea['p']['w'], sea['p']['d']),
    (shelf['p'], sea['p']),
)
check('the sea bed is dished 8 m', abs(shelf['p']['depth'] - 8) < 1e-9, shelf['p'])
check(
    'a level of my own is honoured',
    abs(
        recs(
            assistant('fill_sea', {'cell_from': 'A1', 'cell_to': 'E30', 'level': -12.5}, drawing=flat_ground(20.0)[0])[
                1
            ],
            'water_plane',
        )[0]['y']
        + 12.5
    )
    < 1e-9,
)

# ── 10. the tab builds all three, at the size the parameters promise ────────
P_BODY = {'rx': 30, 'rz': 20, 'wobble': 0.25, 'seed': 1, 'seg': 48}
P_PATH = {'len': 60, 'w': 8, 'meander': 6, 'seed': 1, 'seg': 24}
P_PLANE = {'w': 200, 'd': 120, 'wave': 0, 'seed': 1, 'res': 16}
bx, bz = W.body_extent(P_BODY)
px, pz = W.path_extent(P_PATH)
b = browser_kinds(
    [{'kind': 'water_body', 'p': P_BODY}, {'kind': 'water_path', 'p': P_PATH}, {'kind': 'water_plane', 'p': P_PLANE}]
)
by_kind = {r['kind']: r for r in b}
for k in KINDS:
    r = by_kind[k]
    check(f'the tab builds {k}', r['ok'] and r['registered'], r)
    check(f'{k} is one part', r['parts'] == 1, r)
    check(f'{k} has a real label', r['label'] and not r['label'].startswith('water_'), r['label'])
for k in ('water_path', 'water_plane'):
    check(f'{k} is a 0.02 m skin', abs(by_kind[k]['size'][1] - 0.02) < 1e-3, by_kind[k]['size'])
check(
    'water_body is its wobbled shoreline wide',
    abs(by_kind['water_body']['size'][0] - bx) < 0.05 and abs(by_kind['water_body']['size'][2] - bz) < 0.05,
    (by_kind['water_body']['size'], bx, bz),
)
check(
    'water_path is exactly `len` long', abs(by_kind['water_path']['size'][0] - 60) < 1e-3, by_kind['water_path']['size']
)
check(
    'water_path is its meander plus its width across',
    abs(by_kind['water_path']['size'][2] - pz) < 0.05,
    (by_kind['water_path']['size'], pz),
)
check(
    'water_plane is w x d',
    abs(by_kind['water_plane']['size'][0] - 200) < 1e-3 and abs(by_kind['water_plane']['size'][2] - 120) < 1e-3,
    by_kind['water_plane']['size'],
)
check(
    'the water surface is the top of the record (min y = -0.02)',
    all(abs(by_kind[k]['min'][1] + 0.02) < 1e-3 for k in ('water_path', 'water_plane')),
    {k: by_kind[k]['min'] for k in KINDS},
)

# ── 11. Blender builds all three, at the same size ──────────────────────────
bl = blender_kinds(
    [{'kind': 'water_body', 'p': P_BODY}, {'kind': 'water_path', 'p': P_PATH}, {'kind': 'water_plane', 'p': P_PLANE}]
)
for k in KINDS:
    check(f'Blender builds {k}', bl.get(k, {}).get('polys', 0) > 4, bl.get(k))
check(
    'Blender water_body matches the tab',
    abs(bl['water_body']['size'][0] - bx) < 0.05 and abs(bl['water_body']['size'][2] - bz) < 0.05,
    (bl['water_body']['size'], bx, bz),
)
check(
    'Blender water_path matches the tab',
    abs(bl['water_path']['size'][0] - 60) < 1e-2 and abs(bl['water_path']['size'][2] - pz) < 0.05,
    (bl['water_path']['size'], pz),
)
check(
    'Blender water_plane matches the tab',
    abs(bl['water_plane']['size'][0] - 200) < 1e-2 and abs(bl['water_plane']['size'][2] - 120) < 1e-2,
    bl['water_plane']['size'],
)
check(
    'Blender skins are 0.02 m thick too',
    all(abs(bl[k]['size'][1] - 0.02) < 1e-3 for k in ('water_path', 'water_plane')),
    {k: bl[k]['size'] for k in KINDS},
)
check(
    'Blender water_body is the same single fan as the tab — flat, seg triangles',
    abs(bl['water_body']['size'][1]) < 1e-6 and bl['water_body']['polys'] == P_BODY['seg'],
    bl['water_body'],
)

# ── 12. THE LAKE SURFACE IS ONE FAN ─────────────────────────────────────────
# The creator's studio screenshot on 2026-09-07 showed the lake as a radial
# pattern of dark and light wedges — a paper windmill, not water. water_body was
# a closed skin: a top fan, a second fan 0.02 m under it and a rim, and the top
# fan was wound the wrong way round, so every triangle's normal pointed at the
# bed. There is nothing for an underside to do anyway (the record's y IS the
# water level, the basin is `shore` metres lower, mat_water is DoubleSide), so
# the lake is now ONE fan of `seg` triangles at y = +0.02, wound face up.
print('the lake surface')
wb = by_kind['water_body']
check('tab: water_body is a single part', wb['parts'] == 1, wb)
check(
    'tab: it is exactly `seg` triangles — one fan, not two fans and a rim',
    wb['tris'] == P_BODY['seg'],
    (wb['tris'], P_BODY['seg']),
)
check('tab: it is FLAT — nothing to z-fight with (bbox height 0)', abs(wb['size'][1]) < 1e-6, wb['size'])
check('tab: it sits a centimetre above the record datum, at y = +0.02', abs(wb['min'][1] - 0.02) < 1e-6, wb['min'])
check(
    'tab: building the lake raised no page error',
    not wb['err'] and not wb.get('page_errors'),
    (wb['err'], wb.get('page_errors')),
)
b48 = browser_kinds(
    [{'kind': 'water_body', 'p': dict(P_BODY, seg=16)}, {'kind': 'water_body', 'p': dict(P_BODY, seg=96)}]
)
check(
    'tab: the fan follows `seg` — 16 segments is 16 triangles, 96 is 96',
    b48[0]['tris'] == 16 and b48[1]['tris'] == 96,
    [r['tris'] for r in b48],
)
check(
    'tab: and neither of those raised a page error',
    not any(r['err'] or r.get('page_errors') for r in b48),
    [r.get('page_errors') for r in b48],
)
check(
    'the lake surface still lands on its basin rim: the ring is the SAME arithmetic',
    W.body_ring(P_BODY)
    == [
        (
            30 * math.cos(2 * math.pi * i / 48) * G.lake_factor(2 * math.pi * i / 48, 0.25, 1),
            -20 * math.sin(2 * math.pi * i / 48) * G.lake_factor(2 * math.pi * i / 48, 0.25, 1),
        )
        for i in range(48)
    ],
    W.body_ring(P_BODY)[:2],
)
check(
    'and fill_lake still floats the surface 0.3 m clear of the bed under it',
    A.ground_height(d, cx, cz) + 0.3 <= wat['y'] + 1e-9,
    (A.ground_height(d, cx, cz), wat['y']),
)

# ── 13. A RIVER IS A FALLING PROFILE ────────────────────────────────────────
# The same visual check found the river in broken blue pieces. carve_river had
# cut each bed 2 m below the LOCAL ground and put both water_paths at one level
# (-8.22 m), but the valley floor rolls by +-1.5 m of base noise, so wherever
# the bed rose above -8.22 the water went under the ground. A bed is a FALLING
# PROFILE: the levels are measured at the NODES before anything is cut, they are
# never allowed to rise, the sculpt_channel is SET to that fall and the
# water_path slopes with it. This section walks the ground under the finished
# river and proves the water is over it at every step — the check that failed.
print('the falling river')
bed0, path0 = beds[0], paths[0]
NODES = []
with A._Scale(d2.cell_m):
    NODES = [A.cell_centre(*A.parse_cell(c)) for c in CELLS]
check(
    'every bed is now a SET channel — it names both of its ends',
    all(G.channel_levels(b['p']) is not None for b in beds),
    [b['p'] for b in beds][:1],
)
blv2 = [G.channel_levels(b['p']) for b in beds]
check(
    'the bed levels NEVER RISE, from the first reach to the last',
    all(blv2[i][0] <= blv2[i - 1][1] + 1e-12 for i in range(1, len(blv2))) and all(a >= bb - 1e-12 for a, bb in blv2),
    blv2,
)
check(
    'consecutive reaches BUTT: reach i ends where reach i+1 begins, exactly',
    all(abs(blv2[i][1] - blv2[i + 1][0]) < 1e-12 for i in range(len(blv2) - 1)),
    blv2,
)
check(
    'every water_path is 0.8 x depth above its bed at BOTH ends',
    all(
        abs((p['y'] + W.path_y(p['p'], 0.0)) - (lvl[0] + 0.8 * 2.0)) < 1e-9
        and abs((p['y'] + W.path_y(p['p'], 1.0)) - (lvl[1] + 0.8 * 2.0)) < 1e-9
        for p, lvl in zip(paths, blv2)
    ),
    [(p['y'], W.path_y(p['p'], 0.0), W.path_y(p['p'], 1.0), lvl) for p, lvl in zip(paths, blv2)],
)
check(
    'every water_path SLOPES with its bed — level1 is the drop to the next node',
    all(abs(W.path_y(p['p'], 1.0) - (lvl[1] - lvl[0])) < 1e-9 for p, lvl in zip(paths, blv2))
    and any(abs(W.path_y(p['p'], 1.0)) > 1e-6 for p in paths),
    [W.path_y(p['p'], 1.0) for p in paths],
)
check(
    'path_y is a straight line from level0 to level1 — half way is the mean',
    all(abs(W.path_y(p['p'], 0.5) - 0.5 * (W.path_y(p['p'], 0.0) + W.path_y(p['p'], 1.0))) < 1e-12 for p in paths),
    [W.path_y(p['p'], 0.5) for p in paths],
)
check(
    'a water_path with no levels is still dead flat — the old kind is untouched',
    W.path_levels(P_PATH) is None and W.path_y(P_PATH, 0.0) == 0.0 and W.path_y(P_PATH, 1.0) == 0.0,
    W.path_levels(P_PATH),
)
# THE CHECK THAT FAILED VISUALLY: walk the finished ground along each reach and
# make sure the water is over it at all 20 stations, not just at the two ends.
# The walk goes to within a millesimal of each end, not ONTO it: rebuilding the
# world point from (lx, lz) and letting height_at turn it back into local costs
# about 1e-16, so a station at exactly lx = +len/2 lands a hair OUTSIDE the reach
# and reads the uncut ground. The ends themselves are proved exactly, in local
# coordinates, by the two checks above.
UNDER = []
for p, _lvl in zip(paths, blv2):
    ln, ry = p['p']['len'], p['ry']
    cs, sn = math.cos(ry), math.sin(ry)
    for i in range(20):
        t = 0.001 + i * 0.998 / 19.0
        lx = -ln / 2 + t * ln
        lz = W.meander_offset(t, p['p']['meander'], p['p']['seed'])
        wx = p['x'] + lx * cs + lz * sn  # the inverse of world_to_local
        wz = p['z'] - lx * sn + lz * cs
        surf = p['y'] + W.path_y(p['p'], t)
        UNDER.append((round(surf - A.ground_height(d2r, wx, wz), 4), round(t, 3)))
check(
    'the ground is BELOW the water at all 20 stations of every reach — the river is not broken into pieces any more',
    all(q[0] > 0 for q in UNDER),
    sorted(UNDER)[:4],
)
check(
    'and it is a real river, not a puddle: the water is ~0.8 x depth clear of the bed all the way',
    all(1.5 < q[0] < 1.7 for q in UNDER),
    (min(UNDER), max(UNDER)),
)
check(
    'the reply reports the total fall in metres, and the nodes it held down',
    'falls' in txt2 and 'never climbs' in txt2 and ' m at ' in txt2,
    txt2,
)
FALL = [float(s) for s in re.findall(r'falls (-?[\d.]+) m', txt2)]
check(
    'the fall it reports is the water it actually drew',
    FALL
    and abs(
        FALL[0] - ((paths[0]['y'] + W.path_y(paths[0]['p'], 0.0)) - (paths[-1]['y'] + W.path_y(paths[-1]['p'], 1.0)))
    )
    < 1e-3,
    (FALL, paths[0]['y'], paths[-1]['y']),
)
bpath = browser_kinds([{'kind': 'water_path', 'p': dict(P_PATH, level0=0, level1=-3)}])[0]
check(
    'tab: a sloping water_path really is 3 m of fall plus the 0.02 m skin',
    abs(bpath['size'][1] - 3.02) < 1e-3 and abs(bpath['min'][1] + 3.02) < 1e-3,
    (bpath['size'], bpath['min']),
)
check(
    'tab: and it built without a page error',
    not bpath['err'] and not bpath.get('page_errors'),
    (bpath['err'], bpath.get('page_errors')),
)
blp = blender_kinds([{'kind': 'water_path', 'p': dict(P_PATH, level0=0, level1=-3)}])
check(
    'Blender slopes the same reach by the same 3 m — the two engines agree',
    abs(blp['water_path']['size'][1] - 3.02) < 1e-2,
    blp.get('water_path'),
)

finish()
