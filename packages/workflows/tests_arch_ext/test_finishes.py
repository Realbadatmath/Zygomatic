# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_finishes.py — proof for the finishes layer.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_finishes.py

Job 71ac02b0 built a 20-storey "luxurious" tower in which every slab, every
wall and the pool deck carried the same mat_concrete, because draw_box had ONE
material argument. This proves the three surfaces are now three finishes:

  * FINISHES[level] holds ids that really exist in A.MATERIALS (the PBR library
    membership, not just the 21 presets),
  * draw_box reads the level from d.ext['building_program']['finish_level'] and
    paints slabs / roof deck from it while the walls keep the caller's word,
  * an explicit floor_material / roof_material beats the level,
  * set_finish repaints one group's three surfaces separately and refuses an id
    that is not a material, naming search_materials.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, tool_names  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
GRP = 'box C4-L13'
BOX = {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat'}


def mats(d, kind):
    return sorted({o['mat'] for o in d.objs if o['kind'] == kind})


def luxury():
    """A fresh drawing whose programme asks for the luxury finish level."""
    d = A.Drawing(None)
    d.ext['building_program'] = {'finish_level': 'luxury'}
    return d


# ── the table ────────────────────────────────────────────────────────────────
print('table')
check(
    'FINISHES has both levels with floor + roof',
    set(A.FINISHES) == {'standard', 'luxury'}
    and all(A.FINISHES[k].get('floor') and A.FINISHES[k].get('roof') for k in A.FINISHES),
    A.FINISHES,
)
missing = [(lvl, s, m) for lvl, f in A.FINISHES.items() for s, m in f.items() if m and m not in A.MATERIALS]
check('every FINISHES id is in A.MATERIALS', missing == [], missing)
check(
    'luxury floor and roof are LIBRARY materials, not mat_* presets',
    A.FINISHES['luxury']['floor'].startswith(('acg_', 'pht_', 'acgd_', 'acga_'))
    and A.FINISHES['luxury']['roof'].startswith(('acg_', 'pht_', 'acgd_', 'acga_')),
    [A.FINISHES['luxury']['floor'], A.FINISHES['luxury']['roof']],
)
check(
    "luxury leaves 'wall' None so the caller's material still wins",
    A.FINISHES['luxury'].get('wall') is None,
    A.FINISHES['luxury'],
)
check('standard floors are mat_concrete', A.FINISHES['standard']['floor'] == 'mat_concrete', A.FINISHES['standard'])
check(
    'DEFAULT_MAT covers slab and roof_flat, and both ids exist',
    A.DEFAULT_MAT.get('slab') in A.MATERIALS and A.DEFAULT_MAT.get('roof_flat') in A.MATERIALS,
    {k: A.DEFAULT_MAT.get(k) for k in ('slab', 'roof_flat')},
)
check(
    'DEFAULT_MAT still carries the old kinds unchanged',
    A.DEFAULT_MAT.get('door') == 'mat_timber'
    and A.DEFAULT_MAT.get('window') == 'mat_plaster'
    and A.DEFAULT_MAT.get('road') == 'mat_asphalt',
    A.DEFAULT_MAT,
)

check(
    'finish_level defaults to standard on a bare drawing',
    A.finish_level(A.Drawing(None)) == 'standard',
    A.finish_level(A.Drawing(None)),
)
check('finish_level reads the programme', A.finish_level(luxury()) == 'luxury')
d_junk = A.Drawing(None)
d_junk.ext['building_program'] = {'finish_level': 'palatial'}
check('an unknown level falls back to standard', A.finish_level(d_junk) == 'standard', A.finish_level(d_junk))

# ── draw_box ─────────────────────────────────────────────────────────────────
print('draw_box')
txt, d = assistant('draw_box', dict(BOX, material='mat_stone'), drawing=luxury())
check(
    'luxury box: every slab carries the luxury floor',
    mats(d, 'slab') == [A.FINISHES['luxury']['floor']] and kinds_of(d).get('slab') == 3,
    mats(d, 'slab'),
)
check(
    '...the flat roof carries the luxury roof deck',
    mats(d, 'roof_flat') == [A.FINISHES['luxury']['roof']],
    mats(d, 'roof_flat'),
)
check("...and the walls keep the caller's material", mats(d, 'wall') == ['mat_stone'], mats(d, 'wall'))
check(
    '...the reply names the finishes it used',
    f'floors {A.FINISHES["luxury"]["floor"]}' in txt and f'roof {A.FINISHES["luxury"]["roof"]}' in txt,
    txt,
)

txt, ds = assistant('draw_box', dict(BOX, material='mat_brick'))
check('standard box: floors are mat_concrete', mats(ds, 'slab') == ['mat_concrete'], mats(ds, 'slab'))
check(
    '...the roof is the standard flat-roof finish',
    mats(ds, 'roof_flat') == [A.FINISHES['standard']['roof']],
    mats(ds, 'roof_flat'),
)
check('...walls are the brick that was asked for', mats(ds, 'wall') == ['mat_brick'], mats(ds, 'wall'))

txt, de = assistant(
    'draw_box', dict(BOX, material='mat_stone', floor_material='mat_timber', roof_material='mat_zinc'), drawing=luxury()
)
check('an explicit floor_material beats the level', mats(de, 'slab') == ['mat_timber'], mats(de, 'slab'))
check('an explicit roof_material beats the level', mats(de, 'roof_flat') == ['mat_zinc'], mats(de, 'roof_flat'))

txt, dg = assistant('draw_box', dict(BOX, roof='gable'), drawing=luxury())
check(
    'a PITCHED roof stays tiled unless a roof_material is named',
    mats(dg, 'roof_gable') == ['mat_roof_tile'],
    mats(dg, 'roof_gable'),
)
txt, dg2 = assistant('draw_box', dict(BOX, roof='gable', roof_material='mat_zinc'))
check('...and takes roof_material when it is given', mats(dg2, 'roof_gable') == ['mat_zinc'], mats(dg2, 'roof_gable'))

txt, db = assistant('draw_box', dict(BOX, material='mat_stone', floor_material='nope'), drawing=luxury())
check(
    'an unusable floor_material falls back to the level, it does not crash',
    mats(db, 'slab') == [A.FINISHES['luxury']['floor']],
    (mats(db, 'slab'), txt),
)

check(
    'draw_box advertises floor_material and roof_material',
    all(
        k in ((next(t for t in A.TOOL_DEFS if t['name'] == 'draw_box')['input_schema'])['properties'])
        for k in ('floor_material', 'roof_material')
    ),
)

# ── set_finish ───────────────────────────────────────────────────────────────
print('set_finish')
check('set_finish is a registered tool', 'set_finish' in tool_names(), 'set_finish' in A.TOOL_FN)

txt, d2 = assistant('draw_box', dict(BOX, material='mat_concrete'))
txt, d2 = assistant(
    'set_finish',
    {
        'group': GRP,
        'floor_material': A.FINISHES['luxury']['floor'],
        'roof_material': A.FINISHES['luxury']['roof'],
        'wall_material': 'mat_stone',
    },
    drawing=d2,
)
check(
    'set_finish repaints floors, roof and walls',
    mats(d2, 'slab') == [A.FINISHES['luxury']['floor']]
    and mats(d2, 'roof_flat') == [A.FINISHES['luxury']['roof']]
    and mats(d2, 'wall') == ['mat_stone'],
    (mats(d2, 'slab'), mats(d2, 'roof_flat'), mats(d2, 'wall')),
)
check('...and counts them per kind', '3 floors' in txt and '1 roof' in txt and '12 walls' in txt, txt)

txt, d3 = assistant('draw_box', dict(BOX))
txt, d3 = assistant('set_finish', {'group': GRP, 'floor_material': 'mat_timber'}, drawing=d3)
check(
    'floor_material alone leaves the walls alone',
    mats(d3, 'slab') == ['mat_timber'] and mats(d3, 'wall') == ['mat_concrete'],
    (mats(d3, 'slab'), mats(d3, 'wall')),
)

txt, _ = assistant('set_finish', {'group': GRP, 'floor_material': 'nope'}, drawing=d3)
check(
    'set_finish refuses an id that is not a material, naming search_materials',
    txt.startswith('refused') and 'search_materials' in txt,
    txt,
)
txt, _ = assistant('set_finish', {'group': 'no such group', 'floor_material': 'mat_timber'}, drawing=d3)
check(
    'set_finish on an unknown group is refused with the call that works',
    txt.startswith('refused') and 'set_finish(' in txt,
    txt,
)
txt, _ = assistant('set_finish', {'group': GRP}, drawing=d3)
check('set_finish with no material at all is refused', txt.startswith('refused'), txt)

# ── set_finish(wall_material=) never repaints a GLASS wall (job 944061f70863, 2026-09-16) ──
d_g = A.Drawing(None)
wg = d_g.new(
    'wall', {'len': 6.0, 'h': 2.7, 't': 0.24}, 0.0, 0.0, 0.0, 0.0, 'mat_glass', name='door wall kept as glass', grp='g'
)
wc = d_g.new('wall', {'len': 6.0, 'h': 2.7, 't': 0.24}, 0.0, 6.0, 0.0, 0.0, 'mat_concrete', name='solid wall', grp='g')
d_g.new('slab', {'w': 6, 'd': 6, 't': 0.22}, 0.0, 3.0, 0.0, 0.0, 'mat_concrete', grp='g')
txt_g = A.call_tool(d_g, 'set_finish', {'group': 'g', 'wall_material': 'mat_brick'})
check('set_finish(wall_material) repaints the solid wall', wc['mat'] == 'mat_brick', (txt_g[:100], wc['mat']))
check(
    '... and leaves the mat_glass door wall as glass (it is glazing, not a wall)', wg['mat'] == 'mat_glass', wg['mat']
)

finish()
