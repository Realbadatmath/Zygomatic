# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_measure_analyse.py — proof for the measure_analyse family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_measure_analyse.py

The reference drawing is one draw_box C4..L13 (10 x 10 m, cells col 2..11 row
3..12), 3 storeys: 12 walls (len 10, h 2.7, t 0.24) and 3 slabs (10 x 10 x
0.22). Every number below is arithmetic on those records.
"""

import os
import re
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


def num(txt, pat=r'([-\d.]+) m'):
    m = re.search(pat, txt or '')
    return float(m.group(1)) if m else None


TOOLS = (
    'measure',
    'area',
    'floor_area',
    'volume',
    'count',
    'bom',
    'list_storeys',
    'find_free_cells',
    'bounds',
    'what_is_at',
    'annotate',
    'dimension',
)

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('all 12 tools registered', all(t in names for t in TOOLS), [t for t in TOOLS if t not in names])
import zyg_workflows.arch_assistant_ext.measure_analyse as M  # noqa: E402

check('PROMPT is one paragraph under 900 chars', 0 < len(M.PROMPT) <= 900 and '\n' not in M.PROMPT, len(M.PROMPT))
check('3-6 examples', 3 <= len(M.EXAMPLES) <= 6, len(M.EXAMPLES))

txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3})
k = kinds_of(d)
check('reference box: 12 walls, 3 slabs', k.get('wall') == 12 and k.get('slab') == 3, k)

txt, d = assistant('measure', {'cell_a': 'C4', 'cell_b': 'C13'}, drawing=d)
check('measure C4..C13 = 9.00 m', abs((num(txt) or 0) - 9.0) < 0.01, txt)

txt, d = assistant('area', {'which': 'all'}, drawing=d)
ar = num(txt, r'([\d.]+) m²')
# 100 m2 of slab, plus the OUTER half of each 0.24 m wall, which is centred on
# the footprint line: 4 x 10 x 0.12 = 4.8 m2. Exactly 104.80, ~100 as promised.
check(
    'area of the 10x10 box is about 100 m² (104.80 with the wall thickness)',
    ar is not None and abs(ar - 104.80) < 0.05 and abs(ar - 100.0) <= 5.0,
    txt,
)
check('...and area says rotation is ignored', 'rotation is ignored' in txt, txt)

txt, d = assistant('floor_area', {}, drawing=d)
fa = num(txt, r'([\d.]+) m²')
check(
    'gross floor area 300 m², 100 per storey',
    fa is not None and abs(fa - 300.0) < 0.01 and 'st0 100.00' in txt and 'st2 100.00' in txt,
    txt,
)

txt, d = assistant('volume', {'which': 'wall'}, drawing=d)
vo = num(txt, r'([\d.]+) m³')
check('wall volume = 12 x 10 x 2.7 x 0.24 = 77.76 m³', vo is not None and abs(vo - 77.76) < 0.01, txt)

txt, d = assistant('count', {}, drawing=d)
check('count reports wall 12 and slab 3', 'wall 12' in txt and 'slab 3' in txt, txt)

txt, d = assistant('list_storeys', {}, drawing=d)
check('3 storeys, 5 objects each', '3 storeys' in txt and txt.count('5 objects') == 3, txt)

txt, d = assistant('bounds', {}, drawing=d)
from zyg_workflows.arch_assistant import parse_cell  # noqa: E402

mb = re.search(r'cells ([A-Z]+\d+)\.\.([A-Z]+\d+)', txt)
bc0, bc1 = (parse_cell(mb.group(1)), parse_cell(mb.group(2))) if mb else ((99, 99), (0, 0))
# the box is cols 2..11, rows 3..12; the span must contain it, be 10.24 m deep
# (10 m + the two 0.24 m walls' outer halves) and name storeys 0..2. It is
# 20 m WIDE, not 10: ry is ignored, so the east and west walls read unrotated.
check(
    'bounds contains the box, 10.24 m deep, storeys 0..2',
    bool(mb)
    and bc0[0] <= 2
    and bc0[1] <= 3
    and bc1[0] >= 11
    and bc1[1] >= 12
    and '10.24 m' in txt
    and 'storeys 0..2' in txt
    and 'ignore rotation' in txt,
    txt,
)

txt, d = assistant('bom', {}, drawing=d)
check('bom: 324 m² wall face, 143.76 m³ concrete', '324.00 m²' in txt and '143.76 m³' in txt and 'wall 12' in txt, txt)

txt, d = assistant('what_is_at', {'cell': 'F9'}, drawing=d)
check('what_is_at F9 (inside the box) lists the slab', 'slab' in txt and 'records cover F9' in txt, txt)
txt2, d = assistant('what_is_at', {'cell': 'A1'}, drawing=d)
check('what_is_at A1 (far outside) finds nothing', txt2.startswith('nothing at A1'), txt2)

txt, d = assistant(
    'find_free_cells', {'cell_from': 'A1', 'cell_to': 'AD30', 'min_w_cells': 4, 'min_d_cells': 4}, drawing=d
)
m = re.search(r'free rectangle ([A-Z]+\d+)\.\.([A-Z]+\d+)', txt)
check('find_free_cells returns a rectangle in the 30x30 block', bool(m), txt)
if m:
    (fc0, fr0), (fc1, fr1) = parse_cell(m.group(1)), parse_cell(m.group(2))
    overlap = fc0 <= 11 and fc1 >= 2 and fr0 <= 12 and fr1 >= 3  # the box is cols 2..11, rows 3..12
    check(
        '...4 x 4 cells and clear of the box',
        fc1 - fc0 == 3 and fr1 - fr0 == 3 and not overlap,
        (m.group(1), m.group(2)),
    )
txt, d = assistant('find_free_cells', {'cell_from': 'A1', 'cell_to': 'C3', 'min_w_cells': 9}, drawing=d)
check('too-big rectangle refused', txt.startswith('refused'), txt)

txt, d = assistant('annotate', {'cell': 'F9', 'text': 'meter cupboard'}, drawing=d)
an = d.objs[-1]
check(
    'annotate makes an annotation named by the text',
    an['kind'] == 'annotation' and an['name'] == 'meter cupboard' and an['p']['h'] == 1.5 and an['grp'] == 'notes',
    (an['kind'], an['name'], an['p']),
)
txt, d = assistant('annotate', {'cell': 'F9', 'text': '   '}, drawing=d)
check('empty note refused', txt.startswith('refused'), txt)

txt, d = assistant('dimension', {'cell_a': 'C4', 'cell_b': 'H4'}, drawing=d)
dm = d.objs[-1]
check(
    'dimension is 5 m long, named with its length, along +X',
    dm['kind'] == 'dimension'
    and abs(dm['p']['len'] - 5.0) < 1e-6
    and dm['name'] == '5.00 m'
    and abs(dm['ry']) < 1e-6
    and dm['p']['tick'] == 0.3,
    (dm['name'], dm['p'], dm['ry']),
)
txt, d = assistant('dimension', {'cell_a': 'C4', 'cell_b': 'C4'}, drawing=d)
check('zero-length dimension refused', txt.startswith('refused'), txt)
txt, d = assistant('measure', {'cell_a': 'ZZ9', 'cell_b': 'C4'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)

txt, d = assistant('add_object', {'kind': 'annotation', 'cell': 'B2', 'params': {'h': 2.5}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'annotation' and d.objs[-1]['p']['h'] == 2.5, txt)
check('rail lists the kinds', rail_has(['annotation', 'dimension']) == [], rail_has(['annotation', 'dimension']))

# ── the grid scale is per DRAWING (2026-09-07) ────────────────────────────────
# find_free_cells built its occupancy map from the module CELL_M / ORIGIN, so on
# a 5 m drawing every footprint fell off the map. cell_size() / cell_origin() are
# read at USE time now: 5 m cells, A1's corner at -750.
print('grid scale')
FIVE = {'cell_m': 5, 'objects': []}
txt, d5 = assistant('measure', {'cell_a': 'A1', 'cell_b': 'K11'}, doc=FIVE)
check(
    'a 5 m drawing measures A1..K11 as 70.71 m (10 cells of 5 m each way)',
    d5.cell_m == 5.0 and abs((num(txt) or 0) - 70.71) < 0.01,
    (d5.cell_m, txt),
)
# one 20 x 20 m pad centred on C4 = (-737.5, -732.5) spans x -747.5..-727.5,
# z -742.5..-722.5 — cols 0..4, rows 1..5 of the A1 corner at -750: 25 cells.
txt, d5 = assistant('add_object', {'kind': 'pad', 'cell': 'C4', 'params': {'w': 20, 'd': 20}}, drawing=d5)
pad = d5.objs[-1]
check(
    'the pad sits on the centre of a 5 m C4 (-737.5, -732.5)',
    abs(pad['x'] + 737.5) < 1e-6 and abs(pad['z'] + 732.5) < 1e-6,
    (pad['x'], pad['z']),
)
check(
    'its footprint is the 20 x 20 m rectangle x -747.5..-727.5, z -742.5..-722.5',
    tuple(round(v, 4) for v in M.footprint(pad)) == (-747.5, -742.5, -727.5, -722.5),
    M.footprint(pad),
)
txt, d5 = assistant(
    'find_free_cells', {'cell_from': 'A1', 'cell_to': 'J10', 'min_w_cells': 4, 'min_d_cells': 4}, drawing=d5
)
check(
    'find_free_cells marks the 5 x 5 cells the pad covers on the 5 m grid — 25 of 100',
    '25 of 100 cells are occupied' in txt,
    txt,
)
check('...and the first clear 4 x 4 block is F1..I4, east of the pad', 'free rectangle F1..I4' in txt, txt)
txt, d5 = assistant(
    'find_free_cells', {'cell_from': 'A1', 'cell_to': 'E5', 'min_w_cells': 5, 'min_d_cells': 5}, drawing=d5
)
check(
    'a 5 x 5 block the pad covers 20 cells of has no free 5 x 5 rectangle',
    txt.startswith('none:') and '20 of 25 cells are occupied' in txt,
    txt,
)
# the same call on a drawing with no cell_m is what it always was
txt, d1 = assistant('add_object', {'kind': 'pad', 'cell': 'C4', 'params': {'w': 4, 'd': 4}}, doc={'objects': []})
p1 = d1.objs[-1]
check(
    'a 1 m drawing still puts the pad on (-147.5, -146.5) with a 4 m footprint',
    d1.cell_m == 1.0
    and abs(p1['x'] + 147.5) < 1e-6
    and abs(p1['z'] + 146.5) < 1e-6
    and tuple(round(v, 4) for v in M.footprint(p1)) == (-149.5, -148.5, -145.5, -144.5),
    (p1['x'], p1['z'], M.footprint(p1)),
)
txt, d1 = assistant(
    'find_free_cells', {'cell_from': 'A1', 'cell_to': 'J10', 'min_w_cells': 4, 'min_d_cells': 4}, drawing=d1
)
check(
    '...and marks the SAME 25 of 100 cells at 1 m, the same free block F1..I4 — the cell arithmetic is scale-invariant',
    '25 of 100 cells are occupied' in txt and 'free rectangle F1..I4' in txt,
    txt,
)
# the READ tools take the same grid. On the 5 m drawing the pad spans
# x -747.5..-727.5, z -742.5..-722.5, which is cells A2..E6 (A1's corner -750).
txt, d5 = assistant('what_is_at', {'cell': 'A3'}, drawing=d5)
check(
    'what_is_at A3 finds the pad — A3 is a 5 m cell inside its footprint',
    'records cover A3' in txt and 'pad' in txt,
    txt,
)
txt, d5 = assistant('what_is_at', {'cell': 'A1'}, drawing=d5)
check('what_is_at A1 finds nothing — the pad starts one 5 m row south', txt.startswith('nothing at A1'), txt)
txt, d5 = assistant('bounds', {}, drawing=d5)
check(
    'bounds reads the pad as 20 x 20 m over cells A2..E6 on the 5 m grid',
    'cells A2..E6' in txt and '20.00 x 20.00 m' in txt,
    txt,
)
txt, d5 = assistant('dimension', {'cell_a': 'A1', 'cell_b': 'C1'}, drawing=d5)
check(
    'dimension A1..C1 is 10.00 m on a 5 m drawing (2 cells), not 2.00 m',
    abs(d5.objs[-1]['p']['len'] - 10.0) < 1e-6 and d5.objs[-1]['name'] == '10.00 m',
    (d5.objs[-1]['p'], d5.objs[-1]['name'], txt),
)

# footprint's fallback for a record with no size parameter is half a LIVE cell,
# so it still occupies its cell: 0.5 m across at 1 m cells, 2.5 m at 5 m.
pt = {'kind': 'annotation', 'p': {}, 'x': 0.0, 'z': 0.0}
check(
    'a record with no size parameter reads as a 0.5 m box at 1 m cells',
    tuple(round(v, 4) for v in M.footprint(pt)) == (-0.25, -0.25, 0.25, 0.25),
    M.footprint(pt),
)
from zyg_workflows.arch_assistant import _Scale, cell_size, cell_origin  # noqa: E402

with _Scale(5):
    check(
        '...and a 2.5 m box at 5 m cells — half a cell either way',
        tuple(round(v, 4) for v in M.footprint(pt)) == (-1.25, -1.25, 1.25, 1.25),
        M.footprint(pt),
    )
    check(
        'inside a 5 m drawing cell_size() is 5.0 and cell_origin() is -750.0',
        cell_size() == 5.0 and cell_origin() == -750.0,
        (cell_size(), cell_origin()),
    )
check(
    'and back outside: cell_size() 1.0, cell_origin() -150.0',
    cell_size() == 1.0 and cell_origin() == -150.0,
    (cell_size(), cell_origin()),
)

check(
    'measure_analyse imports no frozen CELL_M / ORIGIN',
    not hasattr(M, 'CELL_M') and not hasattr(M, 'ORIGIN'),
    (getattr(M, 'CELL_M', None), getattr(M, 'ORIGIN', None)),
)
from zyg_workflows import arch_assistant as _A  # noqa: E402

check('the module is back at 1 m after every call', _A._CELL == {'m': 1.0, 'origin': -150.0}, _A._CELL)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [{'kind': 'annotation', 'p': {'h': 1.5, 'r': 0.15}}, {'kind': 'dimension', 'p': {'len': 5.0, 'tick': 0.3}}]
b = browser_kinds(cases)
pin, dim = b
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'annotation builds, 1.65 m tall (pole 1.5 + ball r 0.15) and 0.30 m wide',
    pin['ok'] and abs(pin['size'][1] - 1.65) < 0.01 and abs(pin['size'][0] - 0.30) < 0.01,
    pin,
)
check('annotation stands on y=0', abs(pin['min'][1]) < 1e-3, pin)
check(
    'dimension builds 5 m long with 0.3 m ticks',
    dim['ok'] and abs(dim['size'][0] - 5.03) < 0.02 and abs(dim['size'][2] - 0.30) < 0.01,
    dim,
)
check('labels', pin['label'] == 'Annotation pin' and dim['label'] == 'Dimension line', (pin['label'], dim['label']))

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
check('blender builds the annotation pin', bl.get('annotation', {}).get('polys', 0) > 0, bl.get('annotation'))
check('blender builds the dimension line', bl.get('dimension', {}).get('polys', 0) > 0, bl.get('dimension'))
finish()
