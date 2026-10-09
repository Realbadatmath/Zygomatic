# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_curved_walls.py — the worked-example family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_curved_walls.py
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

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('draw_curved_wall', 'draw_wall_through', 'draw_round_wall', 'draw_round_tower')),
    names,
)
txt, d = assistant('draw_curved_wall', {'centre': 'C4', 'radius': 6, 'start_deg': 0, 'end_deg': 90, 'storeys': 2})
check(
    'quarter arc x2 storeys',
    kinds_of(d).get('wall_arc') == 2 and d.objs[1]['y'] == 2.7 and d.objs[0]['p']['r'] == 6,
    txt,
)
txt, d = assistant('draw_wall_through', {'cell_a': 'D10', 'cell_b': 'F8', 'cell_c': 'H10'}, drawing=d)
arc = d.objs[-1]
r = arc['p']['r']
check('arc through three cells has the right radius', abs(r - 2.0) < 0.05 and 'radius' in txt, (r, txt))
# the arc must pass through the middle cell: F8's centre lies at distance r from the record's centre
from zyg_workflows.arch_assistant import cell_centre, parse_cell  # noqa: E402

fx, fz = cell_centre(*parse_cell('F8'))
check(
    '...and passes through F8',
    abs(math.hypot(fx - arc['x'], fz - arc['z']) - r) < 0.02,
    (fx, fz, arc['x'], arc['z'], r),
)
txt, d = assistant(
    'draw_round_tower', {'centre': 'K20', 'radius': 4, 'storeys': 5, 'glass_every': 2, 'roof': 'cone'}, drawing=d
)
k = kinds_of(d)
check(
    'round tower: 5 rings, 5 floors, a cone', k.get('wall_ring') == 5 and k.get('disc') == 5 and k.get('cone') == 1, k
)
check(
    'glass on storeys 0,2,4',
    [o['mat'] for o in d.objs if o['kind'] == 'wall_ring']
    == ['mat_glass', 'mat_concrete', 'mat_glass', 'mat_concrete', 'mat_glass'],
)
txt, d = assistant('draw_curved_wall', {'centre': 'ZZ9', 'radius': 6}, drawing=d)
check('off-grid refused', txt.startswith('refused'), txt)
txt, d = assistant('add_object', {'kind': 'wall_ring', 'cell': 'A1', 'params': {'r': 3}}, drawing=d)
check('add_object knows the new kind', d.objs[-1]['kind'] == 'wall_ring' and d.objs[-1]['p']['r'] == 3, txt)
check('rail lists the kinds', rail_has(['wall_arc', 'wall_ring']) == [], rail_has(['wall_arc', 'wall_ring']))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'wall_arc', 'p': {'r': 5, 'a0': 0, 'a1': 90, 'h': 2.7, 't': 0.24}},
    {'kind': 'wall_arc', 'p': {'r': 5, 'a0': 0, 'a1': 180, 'h': 3, 't': 0.3}},
    {'kind': 'wall_ring', 'p': {'r': 4, 'h': 2.7, 't': 0.24}},
]
b = browser_kinds(cases)
q, h, ring = b
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'quarter arc builds, spans r+t/2 in x and z, h tall',
    q['ok'] and abs(q['size'][0] - 5.12) < 0.06 and abs(q['size'][2] - 5.12) < 0.06 and abs(q['size'][1] - 2.7) < 1e-3,
    q,
)
check('quarter arc sits in +x / -z (north-east quadrant)', q['min'][0] > -0.01 and q['min'][2] < -5.0, q)
check(
    'half arc spans the full diameter',
    h['ok'] and abs(h['size'][0] - 10.3) < 0.06 and abs(h['size'][1] - 3.0) < 1e-3,
    h,
)
check(
    'ring is a full circle',
    ring['ok'] and abs(ring['size'][0] - 8.24) < 0.06 and abs(ring['size'][2] - 8.24) < 0.06,
    ring,
)
check('labels', q['label'] == 'Curved wall' and ring['label'] == 'Round wall', (q['label'], ring['label']))

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
check('blender builds the arc (faces)', bl.get('wall_arc', {}).get('polys', 0) >= 4 * 8 + 2, bl.get('wall_arc'))
check('blender builds the ring', bl.get('wall_ring', {}).get('polys', 0) >= 4 * 8, bl.get('wall_ring'))
finish()
