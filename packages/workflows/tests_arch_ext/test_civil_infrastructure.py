# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_civil_infrastructure.py — bridges, tunnels, dams, quays.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_civil_infrastructure.py
"""

# re-verified 2026-09-07 after the harness serialised Blender
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
from zyg_workflows.arch_assistant import cell_centre, parse_cell  # noqa: E402

KINDS = [
    'bridge_deck',
    'bridge_pier',
    'bridge_arch',
    'tunnel',
    'culvert',
    'dam',
    'quay_wall',
    'jetty',
    'embankment',
    'sluice',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('draw_bridge', 'draw_tunnel', 'draw_dam', 'draw_jetty', 'draw_quay', 'draw_embankment')),
    names,
)

# A1 -> A41 is 40 m of line; piers every 20 m means piers at 0, 20 and 40 m.
txt, d = assistant(
    'draw_bridge', {'cell_from': 'A1', 'cell_to': 'A41', 'width': 8, 'deck_height': 8, 'piers_every': 20}
)
k = kinds_of(d)
deck = [o for o in d.objs if o['kind'] == 'bridge_deck']
piers = [o for o in d.objs if o['kind'] == 'bridge_pier']
check(
    'beam bridge: 1 deck + 3 piers',
    k.get('bridge_deck') == 1 and k.get('bridge_pier') == 3 and not k.get('bridge_arch'),
    (k, txt),
)
check('deck is 40 m long at y 8', abs(deck[0]['p']['len'] - 40.0) < 0.01 and abs(deck[0]['y'] - 8.0) < 1e-6, deck[0])
ax, az = cell_centre(*parse_cell('A1'))
want = [(ax, az), (ax, az + 20.0), (ax, az + 40.0)]
got = [(o['x'], o['z']) for o in piers]
check(
    'piers at 0, 20 and 40 m along the line, all at y 0',
    all(abs(g[0] - w[0]) < 0.01 and abs(g[1] - w[1]) < 0.01 for g, w in zip(got, want))
    and all(o['y'] == 0.0 for o in piers)
    and all(abs(o['p']['h'] - 8.0) < 1e-6 for o in piers),
    (got, want),
)
check('bridge result names ids and counts', 'deck' in txt and '3 piers' in txt, txt)

txt, d2 = assistant(
    'draw_bridge',
    {'cell_from': 'A1', 'cell_to': 'A41', 'width': 8, 'deck_height': 8, 'piers_every': 20, 'kind': 'arch'},
)
k2 = kinds_of(d2)
arches = [o for o in d2.objs if o['kind'] == 'bridge_arch']
check(
    'arch bridge adds 2 arches of 20 m span',
    k2.get('bridge_arch') == 2
    and k2.get('bridge_pier') == 3
    and all(abs(o['p']['span'] - 20.0) < 0.01 for o in arches),
    (k2, txt),
)

txt, d = assistant('draw_tunnel', {'cell_from': 'A1', 'cell_to': 'A21', 'width': 8, 'height': 6}, drawing=d)
tun = d.objs[-1]
check(
    'tunnel 20 m long, 8 x 6 section',
    tun['kind'] == 'tunnel'
    and abs(tun['p']['len'] - 20.0) < 0.01
    and tun['p']['w'] == 8
    and tun['p']['h'] == 6
    and tun['y'] == 0.0,
    (tun['p'], txt),
)

txt, d = assistant('draw_dam', {'cell_from': 'A1', 'cell_to': 'A31', 'height': 20}, drawing=d)
dam = d.objs[-1]
check(
    'dam 30 m long, 20 high, base 15 crest 4',
    dam['kind'] == 'dam'
    and abs(dam['p']['len'] - 30.0) < 0.01
    and dam['p']['h'] == 20
    and dam['p']['t_base'] == 15
    and dam['p']['t_top'] == 4,
    (dam['p'], txt),
)

txt, d = assistant('draw_quay', {'cells': ['C10', 'M10', 'M24'], 'height': 3}, drawing=d)
seg = [o for o in d.objs if o['kind'] == 'quay_wall']
check(
    'quay: 2 segments of 10 and 14 m',
    len(seg) == 2
    and abs(seg[0]['p']['len'] - 10.0) < 0.01
    and abs(seg[1]['p']['len'] - 14.0) < 0.01
    and seg[0]['p']['h'] == 3,
    ([s['p'] for s in seg], txt),
)

txt, d = assistant('draw_jetty', {'cell_from': 'M24', 'cell_to': 'Q24', 'width': 2}, drawing=d)
jet = d.objs[-1]
check(
    'jetty 4 m out, 2 m wide',
    jet['kind'] == 'jetty' and abs(jet['p']['len'] - 4.0) < 0.01 and jet['p']['w'] == 2 and jet['p']['posts'] == 3,
    (jet['p'], txt),
)

txt, d = assistant('draw_embankment', {'cell_from': 'A6', 'cell_to': 'A26', 'height': 4}, drawing=d)
emb = d.objs[-1]
check(
    'embankment base defaults to 3x the height',
    emb['kind'] == 'embankment'
    and emb['p']['h'] == 4
    and abs(emb['p']['w'] - 12.0) < 1e-6
    and abs(emb['p']['len'] - 20.0) < 0.01,
    (emb['p'], txt),
)

# refusals
txt, d = assistant('draw_bridge', {'cell_from': 'A1', 'cell_to': 'A1'}, drawing=d)
check('bridge between one cell and itself refused', txt.startswith('refused'), txt)
txt, d = assistant('draw_tunnel', {'cell_from': 'A1', 'cell_to': 'A21', 'width': 8, 'height': 3}, drawing=d)
check('tunnel lower than its own arch refused', txt.startswith('refused'), txt)
txt, d = assistant('draw_quay', {'cells': ['C10'], 'height': 3}, drawing=d)
check('quay of one cell refused', txt.startswith('refused'), txt)
txt, d = assistant('draw_bridge', {'cell_from': 'A1', 'cell_to': 'A41', 'kind': 'suspension'}, drawing=d)
check('unknown bridge kind refused', txt.startswith('refused'), txt)
txt, d = assistant('draw_dam', {'cell_from': 'ZZ9', 'cell_to': 'A31', 'height': 20}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)

txt, d = assistant('add_object', {'kind': 'sluice', 'cell': 'A1', 'params': {'w': 6}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'sluice' and d.objs[-1]['p']['w'] == 6, txt)
check('rail lists every kind', rail_has(KINDS) == [], rail_has(KINDS))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'bridge_deck', 'p': {'len': 20, 'w': 8, 't': 0.8, 'edge': 0.5}},
    {'kind': 'bridge_pier', 'p': {'w': 2, 'd': 6, 'h': 8}},
    {'kind': 'bridge_arch', 'p': {'span': 20, 'rise': 5, 'w': 8, 't': 1.0}},
    {'kind': 'tunnel', 'p': {'len': 20, 'w': 8, 'h': 6, 't': 0.5}},
    {'kind': 'culvert', 'p': {'len': 10, 'r': 1, 't': 0.2}},
    {'kind': 'dam', 'p': {'len': 30, 'h': 20, 't_base': 15, 't_top': 4}},
    {'kind': 'quay_wall', 'p': {'len': 20, 'h': 4, 't': 1.2}},
    {'kind': 'jetty', 'p': {'len': 12, 'w': 2.5, 'h': 1.5, 'posts': 3}},
    {'kind': 'embankment', 'p': {'len': 20, 'w': 9, 'h': 3}},
    {'kind': 'sluice', 'p': {'w': 6, 'h': 5, 'gate_h': 3, 't': 1.0}},
]
WANT = {
    'bridge_deck': (20, 1.3, 8),
    'bridge_pier': (2, 8, 6),
    'bridge_arch': (20, 6, 8),
    'tunnel': (20, 6, 8),
    'culvert': (10, 2.4, 2.4),
    'dam': (30, 20, 15),
    'quay_wall': (20, 4, 1.2),
    'jetty': (12, 1.5, 2.5),
    'embankment': (20, 3, 9),
    'sluice': (8, 5, 2),
}
b = browser_kinds(cases)
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
by = {r['kind']: r for r in b}
for kind in KINDS:
    r = by.get(kind, {})
    w = WANT[kind]
    ok = bool(r.get('ok')) and r.get('size') and all(abs(r['size'][i] - w[i]) < 0.06 for i in range(3))
    check(f'{kind} builds, {w[0]:g} x {w[1]:g} x {w[2]:g} m', ok, r)
check('tunnel is hollow, not a box', by['tunnel'].get('tris', 0) > 24, by['tunnel'])
check('culvert is a pipe, not a box', by['culvert'].get('tris', 0) > 24, by['culvert'])
check(
    'labels',
    by['bridge_deck'].get('label') == 'Bridge deck' and by['quay_wall'].get('label') == 'Quay wall',
    (by['bridge_deck'].get('label'), by['quay_wall'].get('label')),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kind in KINDS:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
finish()
