# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_design_rules.py — proof for the design rules (2026-09-08).

    /usr/bin/python3 tests_arch_ext/test_design_rules.py

The 2026-09-07 tower is replayed from its ledger: the checks must NAME each of
its four defects (pool water inside the roof, columns through the canopy, trees
merged into blobs on the entrance axis, placeholder trees), the tools must no
longer be able to make them, and `done` must refuse while errors remain.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
DR = A.EXT_MODULES['design_rules']
names = tool_names()
check('design_check registered', 'design_check' in names)
check(
    'done has NO force flag (2026-09-11: the author does not hold the gate)',
    'force' not in [t for t in A.TOOL_DEFS if t['name'] == 'done'][0]['input_schema']['properties'],
)

# ── the 2026-09-07 tower, as the ledger recorded it (old tool semantics) ──────
d = A.Drawing(None)
A.call_tool(
    d,
    'draw_box',
    dict(cell_from='EX141', cell_to='FQ160', storeys=20, material='pht_rough_concrete', roof='flat', name='tower'),
)
A.call_tool(d, 'add_opening', dict(wall_id='o2', kind='double_door', at='middle', width=3, height=2.6))
A.call_tool(d, 'add_canopy', dict(wall_id='o2', at='middle', width=10, depth=3.5, kind='canopy', material='mat_glass'))
A.call_tool(d, 'add_colonnade', dict(cell_from='FD163', cell_to='FJ163', spacing=2, height=3.5, kind='column_round'))
# the old pool/loungers/trees, written straight into the records (the tools refuse or lift them now)
pool = d.new(
    'pool',
    {'w': 13.0, 'd': 14.0, 'depth': 1.5, 'coping': 0.3},
    13.5,
    1.0,
    54.0,
    0.0,
    'mat_plaster',
    name='Infinity Pool',
    grp='pool',
)
d.new('sun_lounger', {'l': 1.9, 'w': 0.7, 'h': 0.4}, 20.5, 0.5, 54.0, 0.0, 'mat_timber', name='lounger 1', grp='b')
for i, (x, z) in enumerate([(7.4, 18.0), (6.4, 16.6), (8.3, 19.2), (17.8, 18.4), (16.7, 17.0), (18.7, 19.6)]):
    d.new(
        'tree_deciduous',
        {'h': 8.0, 'r_can': 3.36, 'r_trunk': 0.25},
        x,
        z,
        0.0,
        0.0,
        'mat_grass',
        name=f'tree {i + 1}',
        grp='trees',
    )
d.new('lamp_post', {'h': 5.0, 'r': 0.06}, 9.5, 13.5, 0.0, 0.0, 'mat_steel', name='lamp 1', grp='lamps')

f = DR.run_checks(d)
codes = {x['code']: x for x in f}
errs = [x for x in f if x['sev'] == 'error']
check(
    'old tower: pool water below the deck is an ERROR',
    codes.get('pool_water', {}).get('sev') == 'error',
    codes.get('pool_water'),
)
check(
    'old tower: pool + lounger buried in the roof is an ERROR naming o101',
    codes.get('buried', {}).get('sev') == 'error' and 'o101' in codes.get('buried', {}).get('text', ''),
    codes.get('buried'),
)
check(
    'old tower: colonnade pierces the canopy (ERROR, 4 columns)',
    sum(1 for x in errs if x['code'] == 'pierce') == 4,
    [x['text'][:60] for x in errs if x['code'] == 'pierce'],
)
check(
    'old tower: tree crowding is a WARN naming 6 pairs',
    codes.get('crowding', {}).get('sev') == 'warn' and '6 tree pairs' in codes['crowding']['text'],
    codes.get('crowding'),
)
check(
    'old tower: trees on the entrance axis (WARN)', 'axis' in codes, [x['text'][:80] for x in f if x['code'] == 'axis']
)
check(
    'old tower: placeholders named (7)',
    'placeholder' in codes and '7 parametric' in codes['placeholder']['text'],
    codes.get('placeholder'),
)
check('old tower: floors present (no floors finding)', 'floors' not in codes)

# ── the done gate ─────────────────────────────────────────────────────────────
job = {'log': [], '_gate': 0}
log = lambda line: job['log'].append(str(line))  # noqa: E731
# 2026-09-10: design_gate also holds the PRESENT gate (done is refused until present()
# has shown THIS drawing, and that refusal counts against GATE_MAX too). Store the
# signature present() stores, so the three calls below test the DESIGN-ERROR gate.
d.ext['presented'] = {'sig': A.EXT_MODULES['blender_power'].present_sig(d)}
r1 = A.design_gate(job, d, {'summary': 'x'}, log)
r2 = A.design_gate(job, d, {'summary': 'x'}, log)
r3 = A.design_gate(job, d, {'summary': 'x'}, log)
check(
    'done refused twice with the findings, accepted the third time',
    r1.startswith('done REFUSED') and 'pool' in r1.lower() and r2.startswith('done REFUSED') and r3 == '',
    (r1[:80], r2[:40], r3),
)
job2 = {'log': [], '_gate': 0}
check(
    'done(force=true) from the model is REFUSED (the flag is dead)',
    A.design_gate(job2, d, {'summary': 'x', 'force': True}, log).startswith('done REFUSED'),
)
job4 = {'log': [], '_gate': 0, 'operator_force': True}
check('operator_force on the JOB (a panel action) passes at once', A.design_gate(job4, d, {'summary': 'x'}, log) == '')
check(
    'the summary carries the outstanding findings',
    'Design check:' in A.design_note(job2) and 'pool' in A.design_note(job2).lower(),
)

# ── floors rule: walls without slabs ──────────────────────────────────────────
d2 = A.Drawing(None)
A.call_tool(d2, 'draw_box', dict(cell_from='C4', cell_to='L13', storeys=4, slabs=False, name='hollow'))
f2 = {x['code']: x for x in DR.run_checks(d2)}
check(
    'a 4-storey box drawn with slabs=false is a floors ERROR naming the storeys',
    f2.get('floors', {}).get('sev') == 'error' and '0, 1, 2, 3' in f2['floors']['text'],
    f2.get('floors'),
)

# ── the tools can no longer make the defects ──────────────────────────────────
d3 = A.Drawing(None)
A.call_tool(d3, 'draw_box', dict(cell_from='EX141', cell_to='FQ160', storeys=20, roof='flat', name='tower'))
txt = A.call_tool(d3, 'add_beach_set', dict(cells=['FO149'], base_height=54))
lo = [o for o in d3.objs if o['kind'] == 'sun_lounger'][0]
check('base_height=54 on a 20-storey roof lands on the deck at 54.3', abs(lo['y'] - 54.3) < 1e-6, (txt, lo['y']))
txt = A.call_tool(d3, 'draw_box', dict(cell_from='FE141', cell_to='FJ143', storeys=1, storey_from=20, name='pav'))
pav = [o for o in d3.objs if o.get('grp') == 'pav' and o['kind'] == 'wall'][0]
check(
    'draw_box storey_from=20 stands on the deck (54.3) and says so',
    abs(pav['y'] - 54.3) < 1e-6 and 'deck' in txt,
    (txt[:90], pav['y']),
)
txt = A.call_tool(d3, 'add_object', dict(kind='umbrella', cell='FG150', storey=20))
um = [o for o in d3.objs if o['kind'] == 'umbrella'][-1]
check('add_object storey=20 stands on the deck', abs(um['y'] - 54.3) < 1e-6, (txt[:80], um['y']))

txt = A.call_tool(d3, 'plant_trees', dict(cell_from='FA167', cell_to='FC170', count=3, kind='tree_deciduous', height=8))
check(
    '3 x 8 m trees in a 3 x 4 m block are REFUSED with the block size that fits',
    txt.startswith('refused') and 'cells' in txt,
    txt[:120],
)
txt = A.call_tool(
    d3, 'plant_trees', dict(cell_from='EW162', cell_to='FC176', count=3, kind='tree_deciduous', height=8, seed=42)
)
trees = [o for o in d3.objs if o['kind'] == 'asset' and 'tree' in (o.get('name') or '').lower()]
check(
    'plant_trees places REAL pack trees by default, scaled to 8 m',
    len(trees) == 3 and 'real model' in txt and all(abs(t['p']['bh'] * t['s'] - 8.0) < 0.2 for t in trees),
    (txt[:120], [(t['p']['item'], t['s']) for t in trees]),
)
import math  # noqa: E402

gaps = [math.hypot(a['x'] - b['x'], a['z'] - b['z']) for i, a in enumerate(trees) for b in trees[i + 1 :]]
check('the three trunks stand >= 5 m apart', min(gaps) >= 5.0, gaps)
txt = A.call_tool(
    d3,
    'plant_trees',
    dict(cell_from='EW162', cell_to='FC176', count=2, kind='tree_deciduous', height=8, model='parametric'),
)
check(
    'model="parametric" still gives the placeholder',
    'placeholder' in txt and any(o['kind'] == 'tree_deciduous' for o in d3.objs),
    txt[:100],
)

txt = A.call_tool(d3, 'add_street_furniture', dict(cells=['FD164', 'FJ164'], kind='lamp_post', height=5))
lamps = [o for o in d3.objs if o['kind'] == 'asset' and 'lamp' in (o.get('name') or '').lower()]
check(
    'lamp posts are the real Poly Haven street lamp, scaled to 5 m',
    len(lamps) == 2 and 'street_lamp_01' in txt and abs(lamps[0]['p']['bh'] * lamps[0]['s'] - 5.0) < 0.1,
    (txt[:100], [(l['p']['item'], l['s']) for l in lamps]),
)

txt = A.call_tool(d3, 'add_canopy', dict(wall_id='o2', width=10, depth=3.5, height=4, columns=4, material='mat_glass'))
cols = [o for o in d3.objs if o['kind'] == 'column_round']
can = [o for o in d3.objs if o['kind'] == 'canopy'][0]
check(
    'add_canopy(columns=4, height=4): 4 columns exactly 4 m tall under the outer edge',
    len(cols) == 4
    and all(abs(c['p']['h'] - 4.0) < 1e-6 for c in cols)
    and abs(can['y'] - 4.0) < 1e-6
    and all(abs(c['z'] - (can['z'] + 3.5 - 0.35)) < 0.05 for c in cols),
    (txt[:120], [(round(c['x'], 2), round(c['z'], 2)) for c in cols]),
)
check('no pierce finding for the canopy-carried columns', not [x for x in DR.run_checks(d3) if x['code'] == 'pierce'])
check('a 2 m soffit is refused', A.call_tool(d3, 'add_canopy', dict(wall_id='o2', height=1.5)).startswith('refused'))

# ── a tree LINE is real too (the live run routed around plant_trees into it) ──
txt = A.call_tool(d3, 'plant_tree_line', dict(cells=['FA185', 'FA163'], kind='deciduous', height=10, spacing=7))
line_trees = [o for o in d3.objs if o['kind'] == 'asset' and o.get('grp') == 'tree line FA185-FA163']
check(
    'plant_tree_line places real oaks every 7 m (4 over 22 m)', len(line_trees) == 4 and 'real model' in txt, txt[:120]
)
txt = A.call_tool(d3, 'plant_tree_line', dict(cells=['FL185', 'FL163'], kind='deciduous', height=10, spacing=2))
check('a 2 m row of 10 m trees is refused as a hedge', txt.startswith('refused') and 'spacing >=' in txt, txt[:120])
d4 = A.Drawing(None)
A.call_tool(
    d4, 'plant_tree_line', dict(cells=['FL185', 'FL163'], kind='poplar', height=18, spacing=6, model='parametric')
)
check(
    'a parametric tree_line counts as a placeholder in design_check',
    any(x['code'] == 'placeholder' for x in DR.run_checks(d4)),
)

# ── search ranks life-size models first and tags the toys ─────────────────────
t = A.call_tool(d3, 'search_assets', {'query': 'tree', 'limit': 6})
lines = t.split('\n')[1:]
check(
    'search "tree": every top-6 hit is a real life-size model, none a toy kit',
    all('[real' in ln for ln in lines) and not any('kenney' in ln for ln in lines),
    lines[:3],
)
t2 = A.call_tool(d3, 'search_assets', {'query': 'tree', 'limit': 40})
check('toy-kit hits are tagged when they do appear', '[toy kit' in t2, t2.count('[toy kit'))
check(
    '"column" no longer surfaces "street rat"',
    'rat' not in A.call_tool(d3, 'search_assets', {'query': 'tree', 'limit': 12}).lower(),
)

# ── the prompt carries the rules, core examples first ─────────────────────────
sp = A.system_prompt(2.7)
check('DESIGN RULES in the system prompt', 'DESIGN RULES' in sp and 'A COLUMN CARRIES WHAT IT MEETS' in sp)
check('core worked examples come first', 'design_check' in sp.split('WORKED EXAMPLES')[1][:6000])
check('prompt under 95k chars', len(sp) < 95000, len(sp))

# ── a parapet is guarding, not a storey (2026-09-08) ─────────────────────────
# add_parapet writes plain `wall` records 1.1 m tall in the building's OWN group
# one storey above the top slab; before PARAPET_H they read as "a storey with
# walls and no floor" and refused the done gate on every correctly-built roof.
_t, _d = assistant('draw_box', {'cell_from': 'K20', 'cell_to': 'X34', 'storeys': 6})
check('a plain box has no floor findings', not DR.check_floors(_d), DR.check_floors(_d))
assistant('add_parapet', {'group': 'box K20-X34', 'height': 1.1}, drawing=_d)
check('a parapet does not invent a storey', not DR.check_floors(_d), DR.check_floors(_d))
_t, _d2 = assistant('draw_box', {'cell_from': 'K20', 'cell_to': 'X34', 'storeys': 3, 'slabs': False})
check(
    'a genuinely missing slab is still an error',
    any(f['sev'] == 'error' for f in DR.check_floors(_d2)),
    DR.check_floors(_d2),
)


# ── check_floors counts a group's storeys from ONE base (job 71e9d42e559f, 2026-09-16) ──
d5 = A.Drawing(None)
A.call_tool(d5, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=3, roof='flat', name='tower'))
H5 = d5.storey_h
top5 = 3 * H5 + 0.3  # the deck: roof y + 0.3
sl0 = [o for o in d5.objs if o['kind'] == 'slab'][0]
cx5, cz5 = sl0['x'], sl0['z']
hw = d5.new('wall', {'len': 4.6, 'h': 2.7, 't': 0.24, 'base': top5}, cx5, cz5 - 2.0, top5, 0.0, grp='tower head house')
hc = d5.new(
    'curtain_wall', {'len': 4.6, 'h': 2.7, 't': 0.15}, cx5, cz5 + 2.0, top5, 0.0, grp='tower head house'
)  # NO base
hr = d5.new(
    'roof_flat', {'w': 4.6, 'd': 4.0, 't': 0.2, 'base': top5}, cx5, cz5, top5 + 2.7, 0.0, grp='tower head house'
)
DRm = A.EXT_MODULES['design_rules']
f5 = [f for f in DRm.check_floors(d5) if 'head house' in f['text']]
check(
    'a head house whose curtain wall lost its base level is ONE storey, not a phantom storey 0 without a slab',
    f5 == [],
    [f['text'] for f in f5],
)
hw2 = d5.new(
    'wall', {'len': 4.6, 'h': 2.7, 't': 0.24, 'base': top5}, cx5, cz5 - 2.0, top5 + 5.4, 0.0, grp='tower head house'
)  # nothing under it
f5b = [f for f in DRm.check_floors(d5) if 'head house' in f['text']]
check(
    '... but a second head-house storey with walls and no floor still fires',
    len(f5b) == 1 and 'storey 2' in f5b[0]['text'],
    [f['text'] for f in f5b],
)

finish()
