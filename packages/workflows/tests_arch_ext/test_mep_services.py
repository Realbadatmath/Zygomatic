# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_mep_services.py — proof for the services family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_mep_services.py

The reference building is draw_box C4..L13, 3 storeys: a 10 x 10 m footprint
centred on (-143, -142), walls at y = 0 / 2.7 / 5.4 of height 2.7, so the
group's top is y = 8.1 and every wall face sits exactly 5 m from the centroid.
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

NEW_KINDS = [
    'duct',
    'pipe',
    'cable_tray',
    'solar_panel',
    'hvac_unit',
    'water_tank',
    'chimney',
    'gutter',
    'downpipe',
    'antenna',
    'satellite_dish',
    'radiator',
]
GRP = 'box C4-L13'
CX, CZ = -143.0, -142.0
TOP = 8.1


def dist(o):
    return math.hypot(o['x'] - CX, o['z'] - CZ)


def of(d, kind):
    return [o for o in d.objs if o['kind'] == kind]


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
from zyg_workflows import arch_assistant as A  # noqa: E402

names = tool_names()
check(
    'the seven tools are registered',
    all(
        t in names
        for t in (
            'add_solar',
            'add_chimney',
            'add_gutters',
            'add_downpipes',
            'add_radiators',
            'run_pipe',
            'add_rooftop_plant',
        )
    ),
    names,
)
check(
    'KINDS carries all twelve kinds', all(k in A.KINDS for k in NEW_KINDS), [k for k in NEW_KINDS if k not in A.KINDS]
)
check(
    'the prompt paragraph is one paragraph under 900 chars',
    0 < len(A.EXT_MODULES['mep_services'].PROMPT) <= 900 and '\n' not in A.EXT_MODULES['mep_services'].PROMPT,
    len(A.EXT_MODULES['mep_services'].PROMPT),
)

txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3})
check('reference box: 12 walls, 3 slabs', kinds_of(d).get('wall') == 12 and kinds_of(d).get('slab') == 3, txt)

txt, d = assistant('add_solar', {'group': GRP}, drawing=d)
sol = of(d, 'solar_panel')
check('add_solar tiles at least 8 panels', len(sol) >= 8, (len(sol), txt))
check('...all at the group top y = 8.1', all(abs(o['y'] - TOP) < 1e-6 for o in sol), sorted({o['y'] for o in sol}))
check(
    '...all inside the 10 x 10 footprint',
    all(-148.0 <= o['x'] <= -138.0 and -147.0 <= o['z'] <= -137.0 for o in sol),
    [(o['x'], o['z']) for o in sol[:3]],
)
check('...with the tilt in the record', all(o['p']['tilt'] == 30 and o['p']['w'] == 1.7 for o in sol), sol[0]['p'])

txt, d = assistant('add_gutters', {'group': GRP}, drawing=d)
gut = of(d, 'gutter')
check('add_gutters makes one gutter per top-storey wall (4)', len(gut) == 4, (len(gut), txt))
check('...at the group top y = 8.1', all(abs(o['y'] - TOP) < 1e-6 for o in gut), [o['y'] for o in gut])
check(
    '...each OUTSIDE its wall (5.22 m from the centroid, walls are at 5.00)',
    all(dist(o) > 5.0 + 1e-6 for o in gut) and all(abs(dist(o) - 5.22) < 1e-3 for o in gut),
    [round(dist(o), 3) for o in gut],
)
check('...each as long as its wall', all(abs(o['p']['len'] - 10.0) < 1e-6 for o in gut), [o['p'] for o in gut[:1]])

txt, d = assistant('add_radiators', {'walls': GRP}, drawing=d)
rad = of(d, 'radiator')
check('add_radiators: one per wall per storey (12)', len(rad) == 12, (len(rad), txt))
check(
    '...each INSIDE its wall (4.83 m from the centroid)',
    all(dist(o) < 5.0 - 1e-6 for o in rad) and all(abs(dist(o) - 4.83) < 1e-3 for o in rad),
    [round(dist(o), 3) for o in rad],
)
check(
    '...0.15 m above each floor',
    sorted({round(o['y'], 3) for o in rad}) == [0.15, 2.85, 5.55],
    sorted({round(o['y'], 3) for o in rad}),
)

txt, d = assistant('run_pipe', {'cells': ['D6', 'H6', 'H11'], 'storey': 0, 'height': 2.4}, drawing=d)
pip = of(d, 'pipe')
check('run_pipe through 3 cells draws 2 segments', len(pip) == 2, (len(pip), txt))
check(
    '...at y = 2.4 and 4 m / 5 m long',
    all(abs(o['y'] - 2.4) < 1e-6 for o in pip)
    and abs(pip[0]['p']['len'] - 4.0) < 1e-6
    and abs(pip[1]['p']['len'] - 5.0) < 1e-6,
    [(o['y'], o['p']['len']) for o in pip],
)

txt, d = assistant('add_chimney', {'group': GRP, 'side': 'north', 'height': 1.8}, drawing=d)
chi = of(d, 'chimney')
check(
    'add_chimney: one stack on the north wall at the top',
    len(chi) == 1 and abs(chi[0]['y'] - TOP) < 1e-6 and chi[0]['p']['h'] == 1.8,
    (chi, txt),
)
check(
    '...inset 1 m from the wall end (4 m off centre on a 10 m wall)',
    abs(abs(chi[0]['x'] - CX) - 4.0) < 1e-6 and abs(chi[0]['z'] - (-147.0)) < 1e-6,
    chi[0],
)

txt, d = assistant('add_downpipes', {'group': GRP, 'count': 2}, drawing=d)
dpp = of(d, 'downpipe')
check(
    'add_downpipes: 2 pipes, each the full 8.1 m',
    len(dpp) == 2 and all(abs(o['p']['h'] - TOP) < 1e-6 for o in dpp),
    (dpp, txt),
)

txt, d = assistant('add_rooftop_plant', {'group': GRP}, drawing=d)
k = kinds_of(d)
check(
    'add_rooftop_plant: one hvac_unit, one water_tank, one antenna',
    k.get('hvac_unit') == 1 and k.get('water_tank') == 1 and k.get('antenna') == 1,
    (k, txt),
)
check(
    '...all at the group top',
    all(abs(o['y'] - TOP) < 1e-6 for o in d.objs if o['kind'] in ('hvac_unit', 'water_tank', 'antenna')),
    txt,
)

# finishes (2026-09-10): each unit gets its own material, none of them the old
# blanket mat_steel that made the whole roof set render as one black block.
M = A.EXT_MODULES['mep_services']
plant = {o['kind']: o['mat'] for o in d.objs if o['kind'] in ('hvac_unit', 'water_tank', 'antenna')}
check('...hvac and tank materials differ', plant['hvac_unit'] != plant['water_tank'], plant)
check('...and neither is mat_steel', plant['hvac_unit'] != 'mat_steel' and plant['water_tank'] != 'mat_steel', plant)
check('...all three units carry three different finishes', len(set(plant.values())) == 3, plant)
check(
    'every PLANT_MATS id is a real material',
    [k for k, m in M.PLANT_MATS.items() if m not in A.MATERIALS] == [],
    {k: m for k, m in M.PLANT_MATS.items() if m not in A.MATERIALS},
)
check('PLANT_MATS covers every plant kind', all(k in M.PLANT_MATS for k in M._PLANT_KINDS), M._PLANT_KINDS)
check('the reply names the finishes it used', 'Finishes:' in txt and plant['hvac_unit'] in txt, txt)
txt2, d5 = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 1})
txt2, d5 = assistant('add_rooftop_plant', {'group': GRP, 'kinds': ['hvac_unit'], 'material': 'mat_brick'}, drawing=d5)
check(
    'an explicit material still wins over PLANT_MATS',
    [o['mat'] for o in d5.objs if o['kind'] == 'hvac_unit'] == ['mat_brick'],
    txt2,
)

# refusals ---------------------------------------------------------------
txt, _ = assistant('add_solar', {}, drawing=d)
check('add_solar without a group or cells is refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_gutters', {'group': 'no such group'}, drawing=d)
check('add_gutters on an unknown group is refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_chimney', {'group': GRP, 'side': 'up'}, drawing=d)
check('add_chimney with a bad side is refused', txt.startswith('refused'), txt)
txt, _ = assistant('run_pipe', {'cells': ['D6']}, drawing=d)
check('run_pipe with one cell is refused', txt.startswith('refused'), txt)
txt, _ = assistant('run_pipe', {'cells': ['D6', 'H6'], 'kind': 'cheese'}, drawing=d)
check('run_pipe with an unknown kind is refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_rooftop_plant', {'group': GRP, 'kinds': ['tree']}, drawing=d)
check('add_rooftop_plant with a non-service kind is refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_rooftop_plant', {'group': 'no such group'}, drawing=d)
check(
    'add_rooftop_plant on an empty selection is refused, naming the call that works',
    txt.startswith('refused') and 'add_rooftop_plant(' in txt,
    txt,
)
txt, _ = assistant('add_radiators', {'walls': GRP, 'width': 40}, drawing=d)
check(
    'add_radiators that would hang 0 radiators is refused, not "added 0"',
    txt.startswith('refused') and 'add_radiators(' in txt,
    txt,
)
txt, _ = assistant('add_downpipes', {'group': GRP, 'count': 9}, drawing=d)
check('add_downpipes with count 9 is refused', txt.startswith('refused'), txt)

txt, d2 = assistant('add_object', {'kind': 'radiator', 'cell': 'A1', 'params': {'w': 1.4}})
check('add_object accepts the new kinds', d2.objs[-1]['kind'] == 'radiator' and d2.objs[-1]['p']['w'] == 1.4, txt)
check('the rail lists all twelve kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
CASES = [
    {'kind': 'duct', 'p': {'len': 6, 'w': 0.4, 'h': 0.3}},
    {'kind': 'pipe', 'p': {'len': 5, 'r': 0.05}},
    {'kind': 'cable_tray', 'p': {'len': 4, 'w': 0.3, 'h': 0.05}},
    {'kind': 'solar_panel', 'p': {'w': 1.7, 'd': 1.0, 'tilt': 30, 't': 0.04, 'leg': 0.3}},
    {'kind': 'hvac_unit', 'p': {'w': 1.2, 'd': 0.8, 'h': 1.0}},
    {'kind': 'water_tank', 'p': {'r': 1.0, 'h': 2.0}},
    {'kind': 'chimney', 'p': {'w': 0.6, 'd': 0.6, 'h': 1.5, 'cap': 0.1}},
    {'kind': 'gutter', 'p': {'len': 5, 'r': 0.08}},
    {'kind': 'downpipe', 'p': {'h': 3, 'r': 0.05}},
    {'kind': 'antenna', 'p': {'h': 3, 'r': 0.03}},
    {'kind': 'satellite_dish', 'p': {'r': 0.4, 'h': 0.5}},
    {'kind': 'radiator', 'p': {'w': 1.0, 'h': 0.6, 't': 0.1}},
]
b = browser_kinds(CASES)
B = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind builds real geometry',
    all(B[c['kind']]['ok'] for c in CASES),
    [c['kind'] for c in CASES if not B[c['kind']]['ok']],
)


def size(kind, want, tol=0.01):
    r = B[kind]
    ok = r['ok'] and all(abs(r['size'][i] - want[i]) < tol for i in range(3))
    check(f'{kind} is sized {want[0]:g} x {want[1]:g} x {want[2]:g} (x, y, z)', ok, r)


size('duct', (6.0, 0.3, 0.4))
size('pipe', (5.0, 0.1, 0.1))
size('cable_tray', (4.0, 0.05, 0.3))
# leg 0.3 + sin(30) * d 1.0 + cos(30) * t 0.04 = 0.8346 tall; footprint d*cos(30) + t*sin(30) deep
size(
    'solar_panel',
    (
        1.7,
        0.3 + math.sin(math.radians(30)) * 1.0 + math.cos(math.radians(30)) * 0.04,
        math.cos(math.radians(30)) * 1.0 + math.sin(math.radians(30)) * 0.04,
    ),
)
check(
    'solar_panel is ~0.8 m tall as the prompt says (0.3 + sin 30 x 1.0)',
    abs(B['solar_panel']['size'][1] - 0.8) < 0.1,
    B['solar_panel']['size'],
)
size('hvac_unit', (1.2, 1.0, 0.8))
size('water_tank', (2.0, 2.0, 2.0))
size('chimney', (0.7, 1.6, 0.7))
size('gutter', (5.0, 0.08, 0.16))
size('downpipe', (0.1, 3.0, 0.1))
size('antenna', (0.06, 3.0, 0.6))
size('satellite_dish', (0.8, 0.66, 0.8))
size('radiator', (1.0, 0.6, 0.1))
check(
    'every kind sits on y = 0 (base at the record)',
    all(abs(B[c['kind']]['min'][1]) < 1e-3 for c in CASES),
    {c['kind']: B[c['kind']]['min'][1] for c in CASES},
)
check(
    'labels',
    B['solar_panel']['label'] == 'Solar panel'
    and B['cable_tray']['label'] == 'Cable tray'
    and B['hvac_unit']['label'] == 'HVAC unit',
    [B['solar_panel']['label'], B['cable_tray']['label']],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(CASES)
for c in CASES:
    check(f'blender builds {c["kind"]}', bl.get(c['kind'], {}).get('polys', 0) > 0, bl.get(c['kind']))

finish()
