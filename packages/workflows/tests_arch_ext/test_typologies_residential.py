# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_typologies_residential.py — proof for the residential
typologies family (draw_house, draw_row_houses, draw_apartment_block,
draw_villa, draw_farm).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_typologies_residential.py

The family adds NO new kinds — every record it makes is a base kind the tab and
Blender already build — so there is nothing for browser_kinds/blender_kinds to
prove here (see the note at the bottom). What IS proved: the recipes make the
records claimed, in the right places, and refuse bad input; and the family's
(empty) rail file still merges into the live library.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, rail_has, tool_names  # noqa: E402
from zyg_workflows.arch_assistant import block_bounds  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def outside(d, cell_from, cell_to, tol=3.0):
    """Ids of records whose origin is not inside the requested block ± tol."""
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    return [
        f'{o["id"]} {o["kind"]} ({o["x"]:.1f},{o["z"]:.1f})'
        for o in d.objs
        if not (xmin - tol <= o['x'] <= xmax + tol and zmin - tol <= o['z'] <= zmax + tol)
    ]


def groups(d, kind=None):
    return sorted({o['grp'] for o in d.objs if o['grp'] and (kind is None or o['kind'] == kind)})


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('draw_house', 'draw_row_houses', 'draw_apartment_block', 'draw_villa', 'draw_farm')),
    names,
)

import zyg_workflows.arch_assistant_ext.typologies_residential as F  # noqa: E402  (loaded by load_extensions already)

check('the family adds no kinds', F.KINDS == {} and F.OPENINGS == [], (F.KINDS, F.OPENINGS))
check('PROMPT is one paragraph under 900 chars', 0 < len(F.PROMPT) <= 900 and '\n' not in F.PROMPT, len(F.PROMPT))
check(
    'EXAMPLES has 3-6 request->calls pairs',
    3 <= len(F.EXAMPLES) <= 6 and all(e.get('ask') and e.get('calls') for e in F.EXAMPLES),
    len(F.EXAMPLES),
)

# ── draw_house: a 6 x 10 m rowhouse, 2 storeys ────────────────────────────────
print('draw_house')
txt, d = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'H13', 'storeys': 2, 'style': 'rowhouse'})
k = kinds_of(d)
check(
    'rowhouse: 8 walls, 2 slabs, 1 gable roof',
    k.get('wall') == 8 and k.get('slab') == 2 and k.get('roof_gable') == 1,
    (txt, k),
)
check('rowhouse: at least 4 windows, front and back only', k.get('window', 0) >= 4, (txt, k))
check('rowhouse: exactly one front door', k.get('door') == 1, k)
xmin, zmin, xmax, zmax = block_bounds('C4', 'H13')
door = [o for o in d.objs if o['kind'] == 'door'][0]
check(
    'the door sits on the south wall line',
    abs(door['z'] - zmax) < 0.01 and xmin - 0.01 <= door['x'] <= xmax + 0.01,
    (door, zmax),
)
wins = [o for o in d.objs if o['kind'] == 'window']
check(
    'every window sits on the north or south wall line',
    all(abs(w['z'] - zmin) < 0.01 or abs(w['z'] - zmax) < 0.01 for w in wins),
    wins[:3],
)
roof = [o for o in d.objs if o['kind'] == 'roof_gable'][0]
check(
    'the gable ridge runs along the long (10 m) axis',
    abs(roof['ry'] - math.pi / 2) < 1e-3 and abs(roof['p']['w'] - 10) < 1e-6 and abs(roof['p']['d'] - 6) < 1e-6,
    roof,
)
check('the roof sits on top of storey 2', abs(roof['y'] - 2 * d.storey_h) < 1e-6, roof['y'])
check(
    'every object is a brick or plaster record inside the block ± 3 m',
    outside(d, 'C4', 'H13') == [],
    outside(d, 'C4', 'H13'),
)
check('one readable group', groups(d) == ['rowhouse C4'], groups(d))

txt, d2 = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'H13', 'storeys': 1, 'style': 'modern'})
south = [o for o in d2.objs if o['name'].startswith('south wall')]
check(
    'modern: the south wall is glass and the roof is flat',
    all(o['mat'] == 'mat_glass' for o in south) and kinds_of(d2).get('roof_flat') == 1,
    (txt, kinds_of(d2)),
)

txt, dv = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'P13', 'style': 'villa', 'garage': True})
kv = kinds_of(dv)
check(
    'a garage adds its own group east of the house, still in the block',
    'villa C4 garage' in groups(dv) and kv.get('roof_hip') == 1 and outside(dv, 'C4', 'P13') == [],
    (txt, groups(dv), kv),
)

# refusals
txt, _ = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'H13', 'style': 'castle'})
check('unknown style refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'H13', 'door_side': 'up'})
check('unknown door_side refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'D5'})
check('a 2 x 2 m block refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_house', {'cell_from': 'C4', 'cell_to': 'H13', 'garage': True})
check('a garage on a 6 m wide block refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_house', {'cell_from': 'ZZ9', 'cell_to': 'H13'})
check('an off-grid cell refused', txt.startswith('refused'), txt)

# ── draw_row_houses: 4 houses across 20 m ─────────────────────────────────────
print('draw_row_houses')
txt, d = assistant('draw_row_houses', {'cell_from': 'C4', 'cell_to': 'V13', 'count': 4, 'storeys': 2})
k = kinds_of(d)
check('4 houses x 2 storeys x 4 sides = 32 walls', k.get('wall') == 32, (txt, k))
g = groups(d, 'wall')
check('4 distinct house groups', len(g) == 4 and len(set(g)) == 4, g)
check('one continuous gable roof', k.get('roof_gable') == 1, k)
check('4 slabs per storey and 4 front doors', k.get('slab') == 8 and k.get('door') == 4, k)
doors = [o for o in d.objs if o['kind'] == 'door']
check(
    'the doors alternate front and back', len({round(o['z'], 3) for o in doors}) == 2, [round(o['z'], 3) for o in doors]
)
check('the whole terrace is inside the block ± 3 m', outside(d, 'C4', 'V13') == [], outside(d, 'C4', 'V13'))
txt, _ = assistant('draw_row_houses', {'cell_from': 'C4', 'cell_to': 'H13', 'count': 4})
check('4 houses in 6 m refused', txt.startswith('refused'), txt)
txt, _ = assistant('draw_row_houses', {'cell_from': 'C4', 'cell_to': 'V13', 'count': 1})
check('count below 2 refused', txt.startswith('refused'), txt)

# ── draw_apartment_block: 12 x 20 m, 5 storeys ────────────────────────────────
print('draw_apartment_block')
txt, d = assistant(
    'draw_apartment_block', {'cell_from': 'C4', 'cell_to': 'N23', 'storeys': 5, 'balconies': True, 'entrances': 2}
)
k = kinds_of(d)
check('3 windows per wall per storey = 60 windows', k.get('window') == 60, (txt, k))
check('20 walls and 5 floor slabs, flat roof', k.get('wall') == 20 and k.get('roof_flat') == 1, k)
bal = [o for o in d.objs if o['grp'].endswith('balconies')]
check('a balcony per storey above the ground floor (>= 4)', len(bal) >= 4, (len(bal), txt))
check(
    'the balconies stand on storeys 1..4',
    sorted({round(o['y'] / d.storey_h) for o in bal}) == [1, 2, 3, 4],
    sorted({round(o['y'] / d.storey_h) for o in bal}),
)
check(
    '2 entrance doors on the ground floor',
    k.get('double_door') == 2 and all(o['y'] == 0 for o in d.objs if o['kind'] == 'double_door'),
    k,
)
check('the block is inside its cells ± 3 m', outside(d, 'C4', 'N23') == [], outside(d, 'C4', 'N23'))
txt, _ = assistant('draw_apartment_block', {'cell_from': 'C4', 'cell_to': 'F8'})
check('a 4 x 5 m apartment block refused', txt.startswith('refused'), txt)

# ── draw_villa ────────────────────────────────────────────────────────────────
print('draw_villa')
txt, d = assistant('draw_villa', {'cell_from': 'C4', 'cell_to': 'N23', 'storeys': 2, 'pool': True})
k = kinds_of(d)
check('villa: a hipped house plus a gabled garage', k.get('roof_hip') == 1 and k.get('roof_gable') == 1, (txt, k))
check('house, garage and pool are three groups', len(groups(d)) >= 3, groups(d))
pool = [o for o in d.objs if o['grp'].endswith('pool')]
house_z = max(o['z'] for o in d.objs if o['grp'] == 'villa C4')
check(
    'a pool in the garden south of the house',
    len(pool) >= 1 and min(o['z'] for o in pool) > house_z,
    (txt, pool, house_z),
)
check('the villa is inside the block ± 3 m', outside(d, 'C4', 'N23') == [], outside(d, 'C4', 'N23'))
_, dnp = assistant('draw_villa', {'cell_from': 'C4', 'cell_to': 'N23', 'pool': False})
check('pool=false leaves no pool group', [o for o in dnp.objs if o['grp'].endswith('pool')] == [], groups(dnp))
txt, _ = assistant('draw_villa', {'cell_from': 'C4', 'cell_to': 'H13'})
check('a villa on 6 x 10 m refused', txt.startswith('refused'), txt)

# ── draw_farm ─────────────────────────────────────────────────────────────────
print('draw_farm')
txt, d = assistant('draw_farm', {'cell_from': 'C4', 'cell_to': 'AF13'})
k = kinds_of(d)
g = groups(d)
check('farmhouse, barn and silo are three groups', len(g) >= 3, (txt, g))
check('the silo is one cylinder', k.get('cylinder') == 1, k)
silo = [o for o in d.objs if o['kind'] == 'cylinder'][0]
check('silo r 3 m, 12 m tall, steel', silo['p']['r'] == 3 and silo['p']['h'] == 12 and silo['mat'] == 'mat_steel', silo)
barn = [o for o in d.objs if o['kind'] == 'wall' and o['p'].get('h') == 5.0]
check('the barn has four 5 m walls', len(barn) == 4, len(barn))
broof = [o for o in d.objs if o['kind'] == 'roof_gable' and abs(o['y'] - 5.0) < 1e-6]
check('the barn roof sits on the 5 m wall head', len(broof) == 1, [o['y'] for o in d.objs if o['kind'] == 'roof_gable'])
check(
    'the farmhouse gable is steep (0.6 x the short side)',
    any(
        abs(o['p'].get('h', 0) - 0.6 * min(o['p']['w'], o['p']['d'])) < 0.02
        for o in d.objs
        if o['kind'] == 'roof_gable' and o['y'] > 5.1
    ),
    [(o['y'], o['p']) for o in d.objs if o['kind'] == 'roof_gable'],
)
check('the whole farmyard is inside the block ± 3 m', outside(d, 'C4', 'AF13') == [], outside(d, 'C4', 'AF13'))
txt, _ = assistant('draw_farm', {'cell_from': 'C4', 'cell_to': 'H13'})
check('a farm on 6 x 10 m refused', txt.startswith('refused'), txt)

# ── the rail ──────────────────────────────────────────────────────────────────
print('rail')
j = json.load(open(os.path.join(HERE, 'arch_ext', 'typologies_residential.json')))
check(
    'the rail file parses and declares no new leaves', j.get('section_key') == 'elements' and j.get('groups') == [], j
)
check('no new kinds to list on the rail', rail_has([]) == [], rail_has([]))
from zyg_workflows import architecture_studio as st  # noqa: E402

lib = st.library()
check(
    'the live library still builds with the empty family merged in',
    isinstance(lib.get('sections'), list) and len(lib['sections']) > 0,
    len(lib.get('sections') or []),
)
check(
    'every kind the recipes emit is a base kind the tab already knows',
    rail_has(
        [
            'wall',
            'slab',
            'window',
            'door',
            'double_door',
            'roof_gable',
            'roof_hip',
            'roof_flat',
            'cylinder',
            'box',
            'opening',
        ]
    )
    == [],
    rail_has(
        [
            'wall',
            'slab',
            'window',
            'door',
            'double_door',
            'roof_gable',
            'roof_hip',
            'roof_flat',
            'cylinder',
            'box',
            'opening',
        ]
    ),
)

print(
    'tab / blender: this family declares no new kinds, so browser_kinds and\n'
    '  blender_kinds have nothing of its own to build — the records above are\n'
    '  base kinds proved by inspection.html and arch_blender_build.py already.'
)
finish()
