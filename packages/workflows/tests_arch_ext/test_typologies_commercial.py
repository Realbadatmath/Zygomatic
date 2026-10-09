# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_typologies_commercial.py — the typologies_commercial proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_typologies_commercial.py

The family adds NO new kinds: every record its seven tools write is a built-in
kind. So the rail check is `rail_has([]) == []` (nothing to list) and the tab /
Blender checks run over the kinds the tools actually emit — they must build real
geometry, not the 0.5 m unknown-kind marker cube.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    assistant,
    kinds_of,
    browser_kinds,  # noqa: E402
    blender_kinds,
    rail_has,
    tool_names,
)

from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows.arch_assistant import block_bounds  # noqa: E402
import zyg_workflows.arch_assistant_ext.typologies_commercial as F  # noqa: E402  (loaded by load_extensions; re-imported for PROMPT)

TOOLS = (
    'draw_office_tower',
    'draw_warehouse',
    'draw_shop',
    'draw_school',
    'draw_church',
    'draw_parking_garage',
    'draw_stadium',
)

# ── the family's shape ───────────────────────────────────────────────────────
print('family')
names = tool_names()
check('the seven tools are registered', all(t in names for t in TOOLS), [t for t in TOOLS if t not in names])
check('no new kinds', F.KINDS == {} and F.OPENINGS == [], (F.KINDS, F.OPENINGS))
check('prompt is one paragraph under 900 chars', 200 < len(F.PROMPT) <= 900 and '\n' not in F.PROMPT, len(F.PROMPT))
check(
    "3-6 worked examples, all naming this family's tools",
    3 <= len(F.EXAMPLES) <= 6 and all(c['tool'] in TOOLS for e in F.EXAMPLES for c in e['calls']),
    len(F.EXAMPLES),
)
check('rail: nothing new to list', rail_has([]) == [])

# ── the assistant ────────────────────────────────────────────────────────────
print('assistant')
# office tower: 20 x 20 cells, 12 storeys. Unglazed first, so the wall counts are exact
# whichever way the glazing goes (add_curtain_wall, when that family is loaded, CONSUMES
# the shell walls and leaves curtain_wall records in their place).
txt, d = assistant('draw_office_tower', {'cell_from': 'C4', 'cell_to': 'V23', 'storeys': 12, 'glass': False})
k = kinds_of(d)
core_walls = [o for o in d.objs if o['kind'] == 'wall' and o['grp'].endswith('core')]
shell_walls = [o for o in d.objs if o['kind'] == 'wall' and not o['grp'].endswith('core')]
check(
    'office tower: 48 shell walls + 48 core walls',
    len(shell_walls) == 48 and len(core_walls) == 48,
    (len(shell_walls), len(core_walls), txt),
)
check('office tower: 12 floor slabs and one flat roof', k.get('slab') == 12 and k.get('roof_flat') == 1, k)
plant = [o for o in d.objs if o['kind'] == 'box']
check(
    'office tower: one 3x3x2 steel plant box on the roof',
    len(plant) == 1
    and plant[0]['p'] == {'w': 3.0, 'd': 3.0, 'h': 2.0}
    and plant[0]['mat'] == 'mat_steel'
    and abs(plant[0]['y'] - (12 * 2.7 + 0.3)) < 1e-6,
    plant,
)
check(
    'office tower: the core is 4 x 4 cells, all 12 storeys',
    sorted({round(o['p']['len'], 3) for o in core_walls}) == [4.0] and len({o['y'] for o in core_walls}) == 12,
    sorted({o['p']['len'] for o in core_walls}),
)
check(
    'office tower: unglazed means no windows and no curtain walls', not k.get('window') and not k.get('curtain_wall'), k
)

txt, d = assistant('draw_office_tower', {'cell_from': 'C4', 'cell_to': 'V23', 'storeys': 12, 'glass': True})
k = kinds_of(d)
check(
    'office tower glazed: 192 windows (4 per wall per storey) or 48 curtain walls',
    k.get('window') == 192 or k.get('curtain_wall') == 48,
    (k, txt),
)
check(
    'office tower glazed: the core is still 48 walls',
    len([o for o in d.objs if o['kind'] == 'wall' and o['grp'].endswith('core')]) == 48,
    k,
)

# warehouse: 20 x 20 cells, 8 m tall, 3 doors
txt, d = assistant('draw_warehouse', {'cell_from': 'C40', 'cell_to': 'V59', 'height_m': 8, 'doors': 3})
k = kinds_of(d)
walls = [o for o in d.objs if o['kind'] == 'wall']
check(
    'warehouse: 4 walls, all 8 m high',
    len(walls) == 4 and all(w['p']['h'] == 8 for w in walls),
    [(w['name'], w['p']['h']) for w in walls],
)
doors = [o for o in d.objs if o['kind'] in ('door_garage', 'double_door')]
zmax = block_bounds('C40', 'V59')[3]
check(
    'warehouse: 3 doors, all on the south line',
    len(doors) == 3 and all(abs(o['z'] - zmax) < 1e-6 for o in doors),
    [(o['kind'], o['z'], zmax) for o in doors],
)
check(
    'warehouse: a low gable roof (2 m rise) at 8 m',
    k.get('roof_gable') == 1
    and [o for o in d.objs if o['kind'] == 'roof_gable'][0]['p']['h'] == 2.0
    and [o for o in d.objs if o['kind'] == 'roof_gable'][0]['y'] == 8.0,
    k,
)
check(
    'warehouse: 3 glass skylights above the roof',
    len([o for o in d.objs if o['kind'] == 'box' and o['mat'] == 'mat_glass']) == 3,
    k,
)

# shop
txt, d = assistant('draw_shop', {'cell_from': 'C70', 'cell_to': 'N75'})
k = kinds_of(d)
win = [o for o in d.objs if o['kind'] == 'window']
check(
    'shop: one 6 m glass strip, h 2.4, sill 0.3',
    len(win) == 1
    and win[0]['p']['w'] == 6.0
    and win[0]['p']['h'] == 2.4
    and win[0]['p']['sill'] == 0.3
    and win[0]['mat'] == 'mat_glass',
    win,
)
check(
    'shop: a double door and a canopy over it, flat roof',
    k.get('double_door') == 1 and k.get('box') == 1 and k.get('roof_flat') == 1,
    k,
)
txt, d2 = assistant('draw_shop', {'cell_from': 'C70', 'cell_to': 'F75'})
check('shop refuses a front under 8 m', txt.startswith('refused'), txt)

# school
txt, d = assistant('draw_school', {'cell_from': 'C80', 'cell_to': 'V99', 'wings': 2, 'storeys': 2})
grps = sorted({o['grp'] for o in d.objs if o['grp']})
k = kinds_of(d)
check('school: 3 groups (main + 2 wings)', len(grps) == 3, grps)
check(
    'school: 3 blocks x 2 storeys x 4 walls = 24 walls, 3 flat roofs',
    k.get('wall') == 24 and k.get('roof_flat') == 3 and k.get('slab') == 6,
    k,
)
check(
    'school: windows on both storeys of every block',
    k.get('window', 0) >= 24 and len({o['y'] for o in d.objs if o['kind'] == 'window'}) == 2,
    k,
)
txt, d2 = assistant('draw_school', {'cell_from': 'C80', 'cell_to': 'F83'})
check('school refuses a plot under 8 x 8 cells', txt.startswith('refused'), txt)

# church
txt, d = assistant('draw_church', {'cell_from': 'C160', 'cell_to': 'V179', 'tower': True})
k = kinds_of(d)
nave_walls = [o for o in d.objs if o['kind'] == 'wall' and o['p']['h'] == 9]
tower_walls = [o for o in d.objs if o['kind'] == 'wall' and o['p']['h'] == 18]
check('church: 4 nave walls 9 m high', len(nave_walls) == 4, [(o['name'], o['p']['h']) for o in nave_walls])
check('church: 4 tower walls 18 m high', len(tower_walls) == 4, len(tower_walls))
check(
    'church: at least 6 tall windows (1.2 x 4, sill 2.5)',
    k.get('window', 0) >= 6
    and all(
        o['p']['w'] == 1.2 and o['p']['h'] == 4.0 and o['p']['sill'] == 2.5 for o in d.objs if o['kind'] == 'window'
    ),
    k,
)
check(
    'church: one pyramid spire at 18 m and a gable roof at 9 m',
    k.get('pyramid') == 1
    and [o for o in d.objs if o['kind'] == 'pyramid'][0]['y'] == 18.0
    and k.get('roof_gable') == 1
    and [o for o in d.objs if o['kind'] == 'roof_gable'][0]['y'] == 9.0,
    k,
)
check('church: one west door', k.get('double_door') == 1, k)

# parking garage
txt, d = assistant('draw_parking_garage', {'cell_from': 'C200', 'cell_to': 'V219', 'decks': 3})
k = kinds_of(d)
cols = [o for o in d.objs if o['kind'] == 'column_rect']
check('parking: at least 9 columns per deck on 3 decks', len(cols) >= 27, len(cols))
check(
    'parking: the columns sit on the 3.0 m decks',
    sorted({o['y'] for o in cols}) == [0.0, 3.0, 6.0],
    sorted({o['y'] for o in cols}),
)
check(
    'parking: 3 ramp openings, 3 m wide, one per deck',
    k.get('opening') == 3 and all(o['p']['w'] == 3.0 for o in d.objs if o['kind'] == 'opening'),
    k,
)
check(
    'parking: 12 walls of 3.0 m, no windows',
    k.get('wall') == 12 and all(o['p']['h'] == 3.0 for o in d.objs if o['kind'] == 'wall') and not k.get('window'),
    k,
)

# stadium
txt, d = assistant('draw_stadium', {'cell_from': 'C240', 'cell_to': 'AP279', 'tiers': 3})
k = kinds_of(d)
check(
    'stadium: one ring, or 4 stands (16 walls) of 4 m per tier',
    k.get('stadium_ring') == 1
    or (k.get('wall') == 16 and all(o['p']['h'] == 12.0 for o in d.objs if o['kind'] == 'wall')),
    k,
)
check(
    'stadium: a grass pitch pad in the middle',
    k.get('stadium_ring') == 1
    or (k.get('pad') == 1 and [o for o in d.objs if o['kind'] == 'pad'][0]['mat'] == 'mat_grass'),
    k,
)
txt, d2 = assistant('draw_stadium', {'cell_from': 'C240', 'cell_to': 'L249'})
check('stadium refuses a plot under 12 x 12 cells', txt.startswith('refused'), txt)

# off the grid
txt, d2 = assistant('draw_office_tower', {'cell_from': 'ZZ400', 'cell_to': 'V23'})
check('off-grid cells refused', txt.startswith('refused'), txt)

# ── the kinds the family emits ───────────────────────────────────────────────
EMITTED = [
    'wall',
    'slab',
    'roof_flat',
    'roof_gable',
    'window',
    'double_door',
    'opening',
    'column_rect',
    'pyramid',
    'box',
    'pad',
]
check(
    'every emitted kind is a known kind',
    [x for x in EMITTED if x not in A.KINDS] == [],
    [x for x in EMITTED if x not in A.KINDS],
)

cases = [
    {'kind': 'wall', 'p': {'len': 20, 'h': 8, 't': 0.24}},
    {'kind': 'slab', 'p': {'w': 20, 'd': 20, 't': 0.22}},
    {'kind': 'roof_flat', 'p': {'w': 20, 'd': 20, 't': 0.3}},
    {'kind': 'roof_gable', 'p': {'w': 20, 'd': 20, 'h': 2, 'over': 0.4}},
    {'kind': 'window', 'p': {'w': 6, 'h': 2.4, 'sill': 0.3}},
    {'kind': 'double_door', 'p': {'w': 1.8, 'h': 2.4}},
    {'kind': 'opening', 'p': {'w': 3, 'h': 2.4, 'sill': 0}},
    {'kind': 'column_rect', 'p': {'w': 0.3, 'd': 0.3, 'h': 3}},
    {'kind': 'pyramid', 'p': {'r': 2.121, 'h': 5, 'sides': 4}},
    {'kind': 'box', 'p': {'w': 3, 'd': 3, 'h': 2}},
    {'kind': 'pad', 'p': {'w': 24, 'd': 24, 't': 0.2}},
]

SOLID = [c['kind'] for c in cases if c['kind'] != 'opening']  # 'opening' is a pure hole: no mesh of its own

print('tab')
b = {r['kind']: r for r in browser_kinds(cases)}
check(
    'no page errors',
    not any(r.get('page_errors') for r in b.values()),
    [r.get('page_errors') for r in b.values() if r.get('page_errors')],
)
for kind in SOLID:
    check(f'tab builds {kind}', b.get(kind, {}).get('ok'), b.get(kind))
check(
    'tab: the ramp opening is a hole, not a mesh (and not the unknown-kind marker)',
    b['opening']['tris'] == 0 and b['opening']['label'] == 'Opening' and not b['opening']['err'],
    b['opening'],
)
check(
    'tab: the 20 m wall is 20 x 8 x 0.24 m',
    abs(b['wall']['size'][0] - 20) < 0.02
    and abs(b['wall']['size'][1] - 8) < 0.02
    and abs(b['wall']['size'][2] - 0.24) < 0.02,
    b['wall']['size'],
)
check(
    'tab: the plant box is 3 x 2 x 3 m',
    abs(b['box']['size'][0] - 3) < 0.02 and abs(b['box']['size'][1] - 2) < 0.02 and abs(b['box']['size'][2] - 3) < 0.02,
    b['box']['size'],
)
check(
    'tab: the pitch pad is 24 x 0.2 x 24 m',
    abs(b['pad']['size'][0] - 24) < 0.02
    and abs(b['pad']['size'][1] - 0.2) < 0.02
    and abs(b['pad']['size'][2] - 24) < 0.02,
    b['pad']['size'],
)
check(
    'tab: the column is 0.3 x 3 x 0.3 m',
    abs(b['column_rect']['size'][0] - 0.3) < 0.02 and abs(b['column_rect']['size'][1] - 3) < 0.02,
    b['column_rect']['size'],
)
check('tab: the 3 m ramp opening is 3 m wide', abs(b['opening']['size'][0] - 3) < 0.05, b['opening']['size'])
check('tab: the spire is 5 m tall', abs(b['pyramid']['size'][1] - 5) < 0.05, b['pyramid']['size'])
check('tab: the gable roof rises 2 m', abs(b['roof_gable']['size'][1] - 2) < 0.35, b['roof_gable']['size'])

print('blender')
bl = blender_kinds(cases)
for kind in SOLID:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
check('blender: the ramp opening builds no mesh (it is a hole)', 'opening' not in bl, bl.get('opening'))

finish()
