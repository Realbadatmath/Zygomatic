# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_structure_frames.py — proof for the structure_frames family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_structure_frames.py

Three engines must agree: the assistant's six tools produce the records claimed,
the tab builds every one of the eight new kinds at the size its parameters say,
and Blender builds a mesh with faces for each.
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

NEW_KINDS = ['beam_i', 'column_h', 'portal_frame', 'arch_beam', 'buttress', 'bracing_x', 'pergola', 'cantilever']

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(
        t in names
        for t in (
            'add_column_grid',
            'add_colonnade',
            'add_beam_grid',
            'add_portal_frames',
            'add_pergola',
            'add_bracing',
        )
    ),
    names,
)

# C4..N15 is a 12 x 12 m block; spacing 6 -> stations at 0, 6, 12 m = 3 x 3.
txt, d = assistant('add_column_grid', {'cell_from': 'C4', 'cell_to': 'N15', 'spacing_x': 6, 'spacing_z': 6})
check('12x12 block, 6 m grid -> 9 columns', kinds_of(d).get('column_rect') == 9, txt)
xs = sorted({o['x'] for o in d.objs})
zs = sorted({o['z'] for o in d.objs})
check(
    'columns on the block edges and centre line',
    xs == [-148.0, -142.0, -136.0] and zs == [-147.0, -141.0, -135.0],
    (xs, zs),
)
check('column is one storey tall', d.objs[0]['p'] == {'w': 0.4, 'd': 0.4, 'h': 2.7}, d.objs[0]['p'])
txt, d2 = assistant(
    'add_column_grid',
    {'cell_from': 'C4', 'cell_to': 'N15', 'spacing_x': 6, 'spacing_z': 6, 'storeys': 2, 'kind': 'column_h'},
)
check(
    'two storeys -> 18 column_h at y 0 and 2.7',
    kinds_of(d2).get('column_h') == 18 and sorted({o['y'] for o in d2.objs}) == [0.0, 2.7],
    txt,
)
txt, _ = assistant('add_column_grid', {'cell_from': 'C4', 'cell_to': 'N15', 'kind': 'column_blob'})
check('unknown column kind refused', txt.startswith('refused'), txt)

# C4 and O4 centres are exactly 12 m apart; spacing 3 -> 4 bays, 5 columns.
txt, c = assistant('add_colonnade', {'cell_from': 'C4', 'cell_to': 'O4', 'spacing': 3, 'height': 3.0})
k = kinds_of(c)
beam = [o for o in c.objs if o['kind'] == 'beam_i'][0]
check('12 m colonnade at 3 m -> 5 columns + 1 beam', k.get('column_round') == 5 and k.get('beam_i') == 1, (k, txt))
check(
    'the beam spans the whole line at column height',
    abs(beam['p']['len'] - 12.0) < 0.01 and beam['y'] == 3.0 and beam['ry'] == 0.0,
    beam,
)
check(
    'columns 3 m apart, both ends included',
    sorted(round(o['x'], 3) for o in c.objs if o['kind'] == 'column_round') == [-147.5, -144.5, -141.5, -138.5, -135.5],
    [o['x'] for o in c.objs if o['kind'] == 'column_round'],
)
txt, _ = assistant('add_colonnade', {'cell_from': 'C4', 'cell_to': 'C4'})
check('colonnade of one cell refused', txt.startswith('refused'), txt)

txt, bg = assistant(
    'add_beam_grid', {'cell_from': 'C4', 'cell_to': 'N15', 'storey': 1, 'spacing': 6, 'direction': 'both'}
)
bs = [o for o in bg.objs if o['kind'] == 'beam_i']
check('beam grid both ways -> 3 + 3 beams', len(bs) == 6, txt)
check('beams hang under the storey-1 slab', all(abs(o['y'] - (2.7 - 0.4)) < 1e-6 for o in bs), [o['y'] for o in bs])
check(
    'three beams along x (len 12, ry 0) and three along z',
    sorted(round(o['ry'], 4) for o in bs) == sorted([0.0, 0.0, 0.0] + [-1.5708] * 3)
    and all(abs(o['p']['len'] - 12.0) < 1e-6 for o in bs),
    [(o['ry'], o['p']['len']) for o in bs],
)
txt, _ = assistant('add_beam_grid', {'cell_from': 'C4', 'cell_to': 'N15', 'direction': 'diagonal'})
check('bad beam direction refused', txt.startswith('refused'), txt)

# D10..X33 = 21 m (x) by 24 m (z)
txt, pf = assistant('add_portal_frames', {'cell_from': 'D10', 'cell_to': 'X33', 'count': 5, 'eaves': 6, 'rise': 1.5})
fr = [o for o in pf.objs if o['kind'] == 'portal_frame']
check('5 portal frames spanning the block width', len(fr) == 5 and all(o['p']['span'] == 21.0 for o in fr), txt)
check(
    'frames evenly spaced across the depth, both ends included',
    [round(o['z'], 3) for o in fr] == [-141.0, -135.0, -129.0, -123.0, -117.0],
    [o['z'] for o in fr],
)
check('eaves and apex as asked', fr[0]['p']['h'] == 6.0 and fr[0]['p']['rise'] == 1.5, fr[0]['p'])

txt, pg = assistant('add_pergola', {'cell_from': 'F20', 'cell_to': 'J24', 'height': 2.4})
p = [o for o in pg.objs if o['kind'] == 'pergola'][0]
check(
    'one pergola sized to the 5 x 5 block',
    kinds_of(pg) == {'pergola': 1} and p['p']['w'] == 5.0 and p['p']['d'] == 5.0 and p['p']['h'] == 2.4,
    (txt, p['p']),
)

txt, w = assistant('draw_wall', {'cell_from': 'C4', 'cell_to': 'K4'})
wall = w.objs[-1]
txt, w = assistant('add_bracing', {'wall_id': wall['id']}, drawing=w)
br = [o for o in w.objs if o['kind'] == 'bracing_x'][0]
check(
    'brace sized to the wall and on its line',
    abs(br['p']['w'] - wall['p']['len']) < 1e-6
    and br['p']['h'] == wall['p']['h']
    and br['x'] == wall['x']
    and br['ry'] == wall['ry'],
    (txt, br['p']),
)
txt, w = assistant('add_bracing', {'wall_id': br['id']}, drawing=w)
check('bracing a non-wall refused', txt.startswith('refused'), txt)

txt, w = assistant('add_object', {'kind': 'arch_beam', 'cell': 'A1', 'params': {'span': 8, 'rise': 2}}, drawing=w)
check('add_object knows the new kinds', w.objs[-1]['kind'] == 'arch_beam' and w.objs[-1]['p']['span'] == 8, txt)
check('rail lists all eight kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'beam_i', 'p': {'len': 5, 'h': 0.4, 'w': 0.2, 'tf': 0.02, 'tw': 0.012}},
    {'kind': 'column_h', 'p': {'h': 3, 'w': 0.3, 'd': 0.3, 'tf': 0.02, 'tw': 0.012}},
    {'kind': 'portal_frame', 'p': {'span': 12, 'h': 6, 'rise': 1.5, 'w': 0.25, 'd': 0.5}},
    {'kind': 'arch_beam', 'p': {'span': 6, 'rise': 1.5, 'w': 0.25, 'd': 0.5, 'seg': 16}},
    {'kind': 'buttress', 'p': {'h': 3, 'w': 0.6, 'd': 1.2, 'top': 0.3}},
    {'kind': 'bracing_x', 'p': {'w': 4, 'h': 2.7, 't': 0.08}},
    {'kind': 'pergola', 'p': {'w': 4, 'd': 3, 'h': 2.4, 'post': 0.12, 'beams': 6}},
    {'kind': 'cantilever', 'p': {'len': 3, 'w': 0.3, 'h': 0.5}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check('every kind builds real geometry', all(r['ok'] for r in b), [(r['kind'], r['ok'], r.get('err')) for r in b])


def size(kind):
    return by[kind]['size']


def near(kind, want, tol=0.02):
    s = size(kind)
    return all(abs(s[i] - want[i]) < tol for i in range(3))


check('beam_i is len x h x w', near('beam_i', [5, 0.4, 0.2], 1e-3), size('beam_i'))
check('column_h is w x h x d', near('column_h', [0.3, 3, 0.3], 1e-3), size('column_h'))
check(
    'portal_frame span 12 h 6 rise 1.5 -> 12.25 x 7.5 x 0.5',
    near('portal_frame', [12.25, 7.5, 0.5], 0.3),
    size('portal_frame'),
)
check(
    'arch_beam spans 6 m and rises 1.5 m',
    abs(size('arch_beam')[0] - 6.0) < 0.4
    and abs(size('arch_beam')[1] - 1.5) < 0.4
    and abs(size('arch_beam')[2] - 0.5) < 1e-3,
    size('arch_beam'),
)
check('buttress is w x h x d (bottom depth)', near('buttress', [0.6, 3, 1.2], 1e-3), size('buttress'))
check(
    'bracing_x fills the w x h bay',
    abs(size('bracing_x')[0] - 4) < 0.15
    and abs(size('bracing_x')[1] - 2.7) < 0.15
    and abs(size('bracing_x')[2] - 0.08) < 1e-3,
    size('bracing_x'),
)
check('pergola is w x h x d', near('pergola', [4, 2.4, 3], 1e-3), size('pergola'))
check(
    'cantilever is len x h x w and starts at x=0',
    near('cantilever', [3, 0.5, 0.3], 1e-3) and abs(by['cantilever']['min'][0]) < 1e-3,
    (size('cantilever'), by['cantilever']['min']),
)
check(
    'labels',
    by['beam_i']['label'] == 'I-beam'
    and by['portal_frame']['label'] == 'Portal frame'
    and by['pergola']['label'] == 'Pergola',
    [by[k]['label'] for k in NEW_KINDS],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kind in NEW_KINDS:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
finish()
# re-verified 2026-09-07 after the harness serialised Blender
