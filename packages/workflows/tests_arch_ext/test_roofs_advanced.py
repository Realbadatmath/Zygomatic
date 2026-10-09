# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_roofs_advanced.py — proof for the roofs_advanced family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_roofs_advanced.py

Three engines must agree about the ten new roof kinds: the assistant's two
tools produce the records claimed, the tab builds each kind at the size its
parameters say, and Blender builds a mesh with faces for each.
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

TEN = [
    'roof_mansard',
    'roof_gambrel',
    'roof_butterfly',
    'roof_sawtooth',
    'roof_pyramid',
    'roof_cone',
    'roof_onion',
    'roof_half_hip',
    'roof_curved',
    'roof_skylight_strip',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', 'add_roof_special' in names and 'add_skylights' in names, names)

import zyg_workflows.arch_assistant_ext.roofs_advanced as RA  # noqa: E402

check('prompt is one paragraph under 900 chars', len(RA.PROMPT) <= 900 and '\n' not in RA.PROMPT, len(RA.PROMPT))
check('3-6 worked examples', 3 <= len(RA.EXAMPLES) <= 6, len(RA.EXAMPLES))
check('all ten kinds declared', sorted(RA.KINDS) == sorted(TEN), sorted(RA.KINDS))

# C4..J9 is 8 cells along x and 6 along z
txt, d = assistant('add_roof_special', {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 2, 'kind': 'mansard'})
r = d.objs[-1]
check(
    'mansard: one record, 8x6 footprint, on storey 2',
    kinds_of(d).get('roof_mansard') == 1 and r['p']['w'] == 8 and r['p']['d'] == 6 and abs(r['y'] - 5.4) < 1e-6,
    (txt, r),
)
check(
    'mansard: default height = 40% of the shorter side, overhang 0.4, break 0.6',
    r['p']['h'] == 2.4 and r['p']['over'] == 0.4 and r['p']['break'] == 0.6,
    r['p'],
)
check(
    'mansard: tiles by default and the id is in the result',
    r['mat'] == 'mat_roof_tile' and r['id'] in txt,
    (r['mat'], txt),
)

txt, d = assistant(
    'add_roof_special', {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 2, 'kind': 'butterfly'}, drawing=d
)
check('butterfly: valley depth defaults to 25% of the shorter side', d.objs[-1]['p']['h'] == 1.5, d.objs[-1]['p'])

txt, d = assistant('add_roof_special', {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 2, 'kind': 'curved'}, drawing=d)
check('curved roof is zinc, not tile', d.objs[-1]['mat'] == 'mat_zinc', d.objs[-1]['mat'])

txt, d = assistant(
    'add_roof_special', {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 3, 'kind': 'cone', 'height': 5}, drawing=d
)
check(
    'cone: radius from the block, height as asked',
    d.objs[-1]['kind'] == 'roof_cone' and d.objs[-1]['p']['r'] == 3.0 and d.objs[-1]['p']['h'] == 5,
    d.objs[-1]['p'],
)

txt, d = assistant(
    'add_roof_special', {'cell_from': 'D10', 'cell_to': 'R21', 'storey': 1, 'kind': 'sawtooth', 'bays': 6}, drawing=d
)
check('sawtooth carries its bay count', d.objs[-1]['p']['bays'] == 6, d.objs[-1]['p'])

txt, d = assistant('add_roof_special', {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 2, 'kind': 'wobbly'}, drawing=d)
check('a bad kind is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_roof_special', {'cell_from': 'ZZ9', 'cell_to': 'J9', 'storey': 2, 'kind': 'mansard'}, drawing=d)
check('an off-grid cell is refused', txt.startswith('refused'), txt)

n_before = len(d.objs)
txt, d = assistant('add_skylights', {'roof': d.objs[0]['id'], 'count': 3}, drawing=d)
sky = d.objs[n_before:]
check(
    '3 skylights added as glass boxes 0.1 thick',
    len(sky) == 3 and all(o['kind'] == 'box' and o['mat'] == 'mat_glass' and o['p']['h'] == 0.1 for o in sky),
    txt,
)
check(
    'skylights sit on the mansard ridge and spread along x',
    all(abs(o['y'] - (5.4 + 2.4 - 0.05)) < 1e-6 for o in sky) and sky[0]['x'] < sky[1]['x'] < sky[2]['x'],
    [(o['x'], o['y']) for o in sky],
)

txt, d = assistant('draw_wall', {'cell_from': 'A1', 'cell_to': 'A6'}, drawing=d)
txt, d = assistant('add_skylights', {'roof': d.objs[-1]['id'], 'count': 2}, drawing=d)
check('skylights on a wall are refused', txt.startswith('refused'), txt)

txt, d = assistant('add_object', {'kind': 'roof_onion', 'cell': 'A1', 'params': {'r': 2, 'spire': 3}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'roof_onion' and d.objs[-1]['p']['spire'] == 3, txt)
check('rail lists all ten kinds', rail_has(TEN) == [], rail_has(TEN))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'roof_mansard', 'p': {'w': 8, 'd': 6, 'h': 3, 'over': 0.4, 'break': 0.6}},
    {'kind': 'roof_gambrel', 'p': {'w': 8, 'd': 6, 'h': 3, 'over': 0.4, 'break': 0.6}},
    {'kind': 'roof_butterfly', 'p': {'w': 8, 'd': 6, 'h': 1.2, 'over': 0.4}},
    {'kind': 'roof_sawtooth', 'p': {'w': 12, 'd': 8, 'h': 1.8, 'bays': 4}},
    {'kind': 'roof_pyramid', 'p': {'w': 6, 'd': 6, 'h': 3, 'over': 0.4}},
    {'kind': 'roof_cone', 'p': {'r': 4, 'h': 3, 'over': 0.3}},
    {'kind': 'roof_onion', 'p': {'r': 2.5, 'h': 3.5, 'spire': 2}},
    {'kind': 'roof_half_hip', 'p': {'w': 8, 'd': 6, 'h': 2.8, 'over': 0.4, 'clip': 0.5}},
    {'kind': 'roof_curved', 'p': {'w': 8, 'd': 6, 'h': 2, 'over': 0.3}},
    {'kind': 'roof_skylight_strip', 'p': {'w': 8, 'd': 6, 'h': 0.3}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every kind is registered and builds real geometry',
    all(by[k]['registered'] and by[k]['ok'] for k in TEN),
    {k: (by[k]['registered'], by[k]['ok'], by[k]['err']) for k in TEN},
)


def size_is(kind, want, tol=0.03):
    r = by[kind]
    got = r['size']
    ok = all(w is None or abs(g - w) < tol for g, w in zip(got, want))
    check(f'{kind} bbox {want}', ok and abs(r['min'][1]) < 1e-3, (got, r['min']))


size_is('roof_mansard', [8.8, 3, 6.8])  # w+2*over x h x d+2*over
size_is('roof_gambrel', [8.8, 3, 6.8])
size_is('roof_butterfly', [8.8, 1.2, 6.8])
size_is('roof_sawtooth', [12, 1.8, 8])  # no overhang on this one
size_is('roof_pyramid', [6.8, 3, 6.8])
size_is('roof_cone', [8.6, 3, 8.6])  # 2*(r+over) across, h tall
size_is('roof_onion', [5, 5.5, 5])  # 2r across, bulb h + spire tall
size_is('roof_half_hip', [8.8, 2.8, 6.8])
size_is('roof_curved', [8.6, 2, 6.6])
size_is('roof_skylight_strip', [8, 0.3, 6])

check('sawtooth with 4 bays is 4 prisms, not one', by['roof_sawtooth']['parts'] == 4, by['roof_sawtooth'])
check(
    'sawtooth carries at least 4*2 triangles more than a plain prism roof',
    by['roof_sawtooth']['tris'] >= by['roof_gambrel']['tris'] + 8,
    (by['roof_sawtooth']['tris'], by['roof_gambrel']['tris']),
)
check(
    'the rooflight deck has a separate glass part', by['roof_skylight_strip']['parts'] == 2, by['roof_skylight_strip']
)
check(
    'labels',
    by['roof_mansard']['label'] == 'Mansard roof' and by['roof_onion']['label'] == 'Onion dome',
    (by['roof_mansard']['label'], by['roof_onion']['label']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kind in TEN:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
finish()
