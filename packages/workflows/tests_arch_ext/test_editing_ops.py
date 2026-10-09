# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_editing_ops.py — the editing_ops family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_editing_ops.py

editing_ops adds NO kinds, so there is nothing for Blender to build and nothing
new in the rail: the proof is the assistant's arithmetic (positions, rotations,
counts, refusals) plus one browser call that shows the tab is alive and still
builds a wall through arGeom.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, browser_kinds, rail_has, tool_names  # noqa: E402

TOOLS = (
    'move',
    'move_to',
    'rotate',
    'mirror',
    'array',
    'copy_to',
    'scale',
    'set_param',
    'set_height',
    'set_thickness',
    'rename',
    'group',
    'hide',
    'show',
    'stack',
    'duplicate_storey',
    'select_objects',
    'replace_kind',
)
BOX = {'cell_from': 'C4', 'cell_to': 'F7'}  # 4 x 4 m: 4 walls + 1 slab, storey 0
H = 2.7


def box(**kw):
    """A fresh drawing holding one 4x4 box (5 records, all storey 0)."""
    args = dict(BOX)
    args.update(kw)
    _, d = assistant('draw_box', args)
    return d


def walls(d):
    return [o for o in d.objs if o['kind'] in ('wall', 'partition')]


def named(d, prefix):
    return next(o for o in d.objs if o['name'].startswith(prefix))


def foot(recs):
    return (min(o['x'] for o in recs), max(o['x'] for o in recs), min(o['z'] for o in recs), max(o['z'] for o in recs))


# ── registration ──────────────────────────────────────────────────────────────
print('registration')
names = tool_names()
missing = [t for t in TOOLS if t not in names]
check('all 18 editing tools registered', not missing, missing)
check(
    'the family adds no kinds to the rail and does not break it',
    rail_has(['wall', 'partition', 'slab']) == [],
    rail_has(['wall', 'partition', 'slab']),
)

# ── move / move_to ────────────────────────────────────────────────────────────
print('move')
d = box()
check('draw_box gave 4 walls + 1 slab', kinds_of(d) == {'wall': 4, 'slab': 1}, kinds_of(d))
before = [(o['x'], o['y'], o['z']) for o in d.objs]
txt, d = assistant('move', {'which': 'new', 'dx_cells': 2, 'dz_cells': -3, 'dy_storeys': 1}, drawing=d)
after = [(o['x'], o['y'], o['z']) for o in d.objs]
check(
    'move shifts 2 cells east, 3 north, one storey up',
    all(
        abs(b[0] + 2 - a[0]) < 1e-6 and abs(b[1] + H - a[1]) < 1e-6 and abs(b[2] - 3 - a[2]) < 1e-6
        for b, a in zip(before, after)
    ),
    (before[0], after[0], txt),
)
txt, d = assistant('move', {'which': 'new', 'dx_cells': 0, 'dz_cells': 0}, drawing=d)
check('a zero move is refused', txt.startswith('refused'), txt)
txt, d = assistant('move', {'which': 'no such group', 'dx_cells': 1}, drawing=d)
check('an empty selection is refused', txt.startswith('refused'), txt)

d = box()
txt, d = assistant('move_to', {'which': 'new', 'cell': 'K20', 'storey': 2}, drawing=d)
cx = sum(o['x'] for o in d.objs) / len(d.objs)
cz = sum(o['z'] for o in d.objs) / len(d.objs)
check(
    'move_to puts the centroid on K20 and the base on storey 2',
    abs(cx - -139.5) < 1e-6 and abs(cz - -130.5) < 1e-6 and abs(min(o['y'] for o in d.objs) - 2 * H) < 1e-6,
    (cx, cz, min(o['y'] for o in d.objs), txt),
)

# ── rotate ────────────────────────────────────────────────────────────────────
print('rotate')
d = box()
ry0 = {o['id']: o['ry'] for o in d.objs}
f0 = foot(d.objs)
txt, d = assistant('rotate', {'which': 'new', 'degrees': 90, 'about': 'centre'}, drawing=d)
check(
    'every wall gained exactly pi/2 of ry',
    all(abs((o['ry'] - ry0[o['id']]) - math.pi / 2) < 1e-5 for o in walls(d)),
    [(o['id'], ry0[o['id']], o['ry']) for o in walls(d)],
)
check(
    'the 4 x 4 footprint bbox is unchanged by the quarter turn',
    all(abs(a - b) < 1e-6 for a, b in zip(foot(d.objs), f0)),
    (f0, foot(d.objs)),
)
check(
    '...and the walls really moved (north is where west was)',
    abs(named(d, 'north')['x'] - -148.0) < 1e-6 and abs(named(d, 'north')['z'] - -145.0) < 1e-6,
    (named(d, 'north')['x'], named(d, 'north')['z'], txt),
)
txt, d = assistant('rotate', {'which': 'new', 'degrees': 45, 'about': 'ZZ9'}, drawing=d)
check('rotating about an off-grid cell is refused', txt.startswith('refused'), txt)
txt, d = assistant('rotate', {'which': 'new', 'degrees': 360}, drawing=d)
check('a full turn is refused', txt.startswith('refused'), txt)

# ── mirror ────────────────────────────────────────────────────────────────────
print('mirror')
d = box()
west_x, east_x = named(d, 'west')['x'], named(d, 'east')['x']
txt, d = assistant('mirror', {'which': 'new', 'axis': 'x'}, drawing=d)
check(
    'mirror x swaps west onto the old east x',
    abs(named(d, 'west')['x'] - east_x) < 1e-6 and abs(named(d, 'east')['x'] - west_x) < 1e-6,
    (west_x, east_x, named(d, 'west')['x'], txt),
)
check(
    'mirror x maps ry to pi - ry (the west wall kept its line)',
    abs(named(d, 'west')['ry'] - (math.pi - math.pi / 2)) < 1e-5,
    named(d, 'west')['ry'],
)
d2 = box()
z_before = [o['z'] for o in d2.objs]
txt, d2 = assistant('mirror', {'which': 'new', 'axis': 'z'}, drawing=d2)
check(
    'mirror z flips z and negates ry',
    sorted(round(v, 4) for v in z_before) == sorted(round(o['z'], 4) for o in d2.objs)
    and abs(named(d2, 'west')['ry'] + math.pi / 2) < 1e-5,
    (z_before, [o['z'] for o in d2.objs], named(d2, 'west')['ry']),
)
txt, d2 = assistant('mirror', {'which': 'new', 'axis': 'y'}, drawing=d2)
check('mirror refuses an axis that is not x or z', txt.startswith('refused'), txt)

# ── array / stack / copy_to / duplicate_storey ────────────────────────────────
print('repeat')
d = box()
txt, d = assistant('array', {'which': 'new', 'count': 3, 'step_x_cells': 6}, drawing=d)
check('array count 3 gives three times the objects', len(d.objs) == 15, (len(d.objs), txt))
check(
    '...spaced 6 m apart in x, groups kept',
    sorted({round(o['x'], 3) for o in d.objs if o['name'].startswith('west')}) == [-148.0, -142.0, -136.0]
    and len({o['grp'] for o in d.objs}) == 1,
    sorted({round(o['x'], 3) for o in d.objs if o['name'].startswith('west')}),
)
txt, d = assistant('array', {'which': 'all', 'count': 3}, drawing=d)
check('an array with no step is refused', txt.startswith('refused'), txt)

d = box()
txt, d = assistant('stack', {'which': 'new', 'count': 2}, drawing=d)
check(
    'stack 2 makes two more storeys, top at 2 x 2.7 m',
    len(d.objs) == 15 and abs(max(o['y'] for o in d.objs) - 2 * H) < 1e-9,
    (len(d.objs), max(o['y'] for o in d.objs), txt),
)
check(
    'stacked copies are renumbered in the outliner',
    sum(1 for o in d.objs if o['name'].endswith('st2')) == 5,
    [o['name'] for o in d.objs][-5:],
)

d = box()
txt, d = assistant('copy_to', {'which': 'new', 'cell': 'K20'}, drawing=d)
new = d.objs[5:]
check(
    'copy_to leaves the original and drops one copy on K20',
    len(d.objs) == 10
    and abs(sum(o['x'] for o in new) / 5 - -139.5) < 1e-6
    and abs(sum(o['z'] for o in new) / 5 - -130.5) < 1e-6,
    (len(d.objs), txt),
)

d = box(name='huis')
txt, d = assistant('duplicate_storey', {'group': 'huis', 'storey': 0, 'to_storeys': [1, 2]}, drawing=d)
check(
    'duplicate_storey 0 -> 1,2 gives three identical floors',
    len(d.objs) == 15 and sorted({round(o['y'], 4) for o in d.objs}) == [0.0, 2.7, 5.4],
    (len(d.objs), txt),
)
txt, d = assistant('duplicate_storey', {'group': 'huis', 'storey': 9, 'to_storeys': [1]}, drawing=d)
check('duplicating an empty storey is refused', txt.startswith('refused'), txt)

# ── numbers ───────────────────────────────────────────────────────────────────
print('numbers')
d = box()
txt, d = assistant('set_height', {'which': 'wall', 'metres': 3.5}, drawing=d)
check(
    'set_height metres 3.5 sets p.h on all four walls',
    [o['p']['h'] for o in walls(d)] == [3.5] * 4,
    (txt, [o['p']['h'] for o in walls(d)]),
)
txt, d = assistant('set_height', {'which': 'slab', 'metres': 3.5}, drawing=d)
check('set_height on a slab (t, no h) is refused', txt.startswith('refused') and 't' in txt, txt)
txt, d = assistant('set_height', {'which': 'wall', 'storeys': 2}, drawing=d)
check('set_height storeys 2 = 5.4 m', [o['p']['h'] for o in walls(d)] == [5.4] * 4, txt)
txt, d = assistant('set_thickness', {'which': 'wall', 't': 0.3}, drawing=d)
check('set_thickness sets p.t', [o['p']['t'] for o in walls(d)] == [0.3] * 4, txt)
txt, d = assistant('set_param', {'which': 'wall', 'key': 'len', 'value': 5}, drawing=d)
check('set_param sets one number', [o['p']['len'] for o in walls(d)] == [5] * 4, txt)
txt, d = assistant('set_param', {'which': 'wall', 'key': 'radius', 'value': 5}, drawing=d)
check('set_param refuses a parameter the kind has not got', txt.startswith('refused'), txt)

d = box()
txt, d = assistant('scale', {'which': 'new', 'factor': 2}, drawing=d)
check(
    'scale 2 doubles the wall lengths and spreads the positions from the centre',
    [o['p']['len'] for o in walls(d)] == [8.0] * 4
    and abs(named(d, 'west')['x'] - -150.0) < 1e-6
    and abs(named(d, 'east')['x'] - -142.0) < 1e-6,
    (txt, [o['p']['len'] for o in walls(d)], named(d, 'west')['x']),
)
txt, d = assistant('scale', {'which': 'new', 'factor': 0}, drawing=d)
check('scale 0 is refused', txt.startswith('refused'), txt)

d = box()
w0 = {o['id']: (o['x'], o['z'], o['ry']) for o in walls(d)}
txt, d = assistant('replace_kind', {'which': 'wall', 'kind': 'partition'}, drawing=d)
check(
    'replace_kind wall -> partition keeps x, z and ry',
    kinds_of(d) == {'partition': 4, 'slab': 1} and all(w0[o['id']] == (o['x'], o['z'], o['ry']) for o in walls(d)),
    (kinds_of(d), txt),
)
check(
    '...and carries the shared numbers over',
    walls(d)[0]['p']['len'] == 4.0 and walls(d)[0]['p']['t'] == 0.24,
    walls(d)[0]['p'],
)
txt, d = assistant('replace_kind', {'which': 'partition', 'kind': 'not_a_kind'}, drawing=d)
check('replace_kind refuses an unknown kind', txt.startswith('refused'), txt)

# ── outliner and viewport ─────────────────────────────────────────────────────
print('outliner')
d = box()
txt, d = assistant('group', {'which': 'new', 'name': 'blok A'}, drawing=d)
check('group renames the outliner group', {o['grp'] for o in d.objs} == {'blok A'}, txt)
txt, d = assistant('rename', {'which': 'slab', 'name': 'begane grond'}, drawing=d)
check('rename names a single object', named(d, 'begane grond')['kind'] == 'slab', txt)
txt, d = assistant('rename', {'which': 'wall', 'name': 'gevel'}, drawing=d)
check(
    'rename numbers several objects',
    [o['name'] for o in walls(d)] == ['gevel 1', 'gevel 2', 'gevel 3', 'gevel 4'],
    [o['name'] for o in walls(d)],
)
txt, d = assistant('hide', {'which': 'blok A'}, drawing=d)
check(
    'hide sets hidden and sends the ui command',
    all(o['hidden'] for o in d.objs) and d.ui[-1]['cmd'] == 'hide' and d.ui[-1]['args']['hidden'] is True,
    (txt, d.ui[-1:]),
)
txt, d = assistant('show', {'which': 'all'}, drawing=d)
check('show clears it again', not any(o['hidden'] for o in d.objs) and d.ui[-1]['args']['hidden'] is False, txt)
txt, d = assistant('select_objects', {'which': 'wall'}, drawing=d)
check(
    'select_objects sets d.selected and appends a ui focus',
    d.selected == [o['id'] for o in walls(d)] and d.ui[-1]['cmd'] == 'focus' and d.ui[-1]['args']['ids'] == d.selected,
    (txt, d.selected, d.ui[-1:]),
)
txt, d = assistant('select_objects', {'which': 'nothing at all'}, drawing=d)
check('select_objects refuses an empty selection', txt.startswith('refused'), txt)

# ── the grid scale is per DRAWING (2026-09-07) ────────────────────────────────
# Every cell-to-metre conversion must read cell_size() at USE time. On a 5 m
# drawing (origin -750) one cell is 5 m, so move(dx_cells=2) is 10 m, not 2.
print('grid scale')
FIVE = {'cell_m': 5, 'objects': []}
txt, d5 = assistant('draw_box', dict(BOX), doc=FIVE)
check(
    'a 5 m drawing keeps cell_m and draws a 20 x 20 m box on C4..F7',
    d5.cell_m == 5.0 and kinds_of(d5) == {'wall': 4, 'slab': 1} and abs(named(d5, 'north')['p']['len'] - 20.0) < 1e-6,
    (d5.cell_m, kinds_of(d5), named(d5, 'north')['p']),
)
b5 = [(o['x'], o['z']) for o in d5.objs]
txt, d5 = assistant('move', {'which': 'new', 'dx_cells': 2, 'dz_cells': -3}, drawing=d5)
a5 = [(o['x'], o['z']) for o in d5.objs]
check(
    'move(dx_cells=2, dz_cells=-3) on a 5 m drawing is 10 m east and 15 m north',
    all(abs(b[0] + 10.0 - a[0]) < 1e-6 and abs(b[1] - 15.0 - a[1]) < 1e-6 for b, a in zip(b5, a5)),
    (b5[0], a5[0], txt),
)
check('...and the answer says 10 m east, 15 m south (not 2 and -3)', '10 m east' in txt and '-15 m south' in txt, txt)
txt, d5 = assistant('array', {'which': 'new', 'count': 3, 'step_x_cells': 6}, drawing=d5)
xs5 = sorted({round(o['x'], 3) for o in d5.objs if o['name'].startswith('west')})
check(
    'array step_x_cells=6 on a 5 m drawing steps 30 m, not 6',
    len(xs5) == 3 and abs(xs5[1] - xs5[0] - 30.0) < 1e-6 and abs(xs5[2] - xs5[1] - 30.0) < 1e-6,
    (xs5, txt),
)
check('...and the answer says 30 m x', 'step 30 m x' in txt, txt)
# the same two tools on a 1 m drawing are byte-for-byte what they always were
d1 = box()
b1 = [(o['x'], o['z']) for o in d1.objs]
txt, d1 = assistant('move', {'which': 'new', 'dx_cells': 2, 'dz_cells': -3}, drawing=d1)
check(
    'a drawing without cell_m still moves 2 m east and 3 m north',
    d1.cell_m == 1.0
    and all(
        abs(b[0] + 2.0 - a[0]) < 1e-6 and abs(b[1] - 3.0 - a[1]) < 1e-6
        for b, a in zip(b1, [(o['x'], o['z']) for o in d1.objs])
    )
    and '2 m east' in txt,
    (b1[0], d1.objs[0]['x'], txt),
)
# the OTHER three cell-to-metre paths in this family go through parse_cell +
# cell_centre, which read the same live values. On the 5 m grid the A1 corner is
# -750 and a cell centre is -750 + (index + 0.5) * 5, so K20 (col 10, row 19) is
# (-697.5, -652.5) and M22 (col 12, row 21) is (-687.5, -642.5). A 1 m drawing
# would put them at -139.5 / -130.5 and -137.5 / -128.5.
_, dc = assistant('draw_box', dict(BOX), doc={'cell_m': 5, 'objects': []})
txt, dc = assistant('move_to', {'which': 'new', 'cell': 'K20'}, drawing=dc)
cx5 = sum(o['x'] for o in dc.objs) / len(dc.objs)
cz5 = sum(o['z'] for o in dc.objs) / len(dc.objs)
check(
    'move_to lands the centroid on the 5 m K20 (-697.5, -652.5), not the 1 m one',
    abs(cx5 - -697.5) < 1e-6 and abs(cz5 - -652.5) < 1e-6,
    (cx5, cz5, txt),
)
txt, dc = assistant('copy_to', {'which': 'wall', 'cell': 'M22'}, drawing=dc)
new5 = dc.objs[5:]
check(
    'copy_to drops the four walls on the 5 m M22 (-687.5, -642.5)',
    len(new5) == 4
    and abs(sum(o['x'] for o in new5) / 4 - -687.5) < 1e-6
    and abs(sum(o['z'] for o in new5) / 4 - -642.5) < 1e-6,
    (len(new5), sum(o['x'] for o in new5) / 4, sum(o['z'] for o in new5) / 4, txt),
)

# rotate/mirror about a NAMED cell use that cell's 5 m centre as the pivot.
# The C4..F7 box's centroid is (-730, -725); A1's centre is (-747.5, -747.5).
# 90 deg: x' = px + dz = -747.5 + 22.5 = -725, z' = pz - dx = -747.5 - 17.5 = -765.
# mirror x: x' = 2*px - x = -1495 + 730 = -765, z unchanged.
_, dr = assistant('draw_box', dict(BOX), doc={'cell_m': 5, 'objects': []})
check(
    'the 5 m C4..F7 box is centred on (-730, -725)',
    abs(sum(o['x'] for o in dr.objs) / 5 - -730.0) < 1e-6 and abs(sum(o['z'] for o in dr.objs) / 5 - -725.0) < 1e-6,
    (sum(o['x'] for o in dr.objs) / 5, sum(o['z'] for o in dr.objs) / 5),
)
txt, dr = assistant('rotate', {'which': 'new', 'degrees': 90, 'about': 'A1'}, drawing=dr)
check(
    'rotate about A1 pivots on the 5 m A1 centre (-747.5): centroid -> (-725, -765)',
    abs(sum(o['x'] for o in dr.objs) / 5 - -725.0) < 1e-6 and abs(sum(o['z'] for o in dr.objs) / 5 - -765.0) < 1e-6,
    (sum(o['x'] for o in dr.objs) / 5, sum(o['z'] for o in dr.objs) / 5, txt),
)
_, dm = assistant('draw_box', dict(BOX), doc={'cell_m': 5, 'objects': []})
txt, dm = assistant('mirror', {'which': 'new', 'axis': 'x', 'about': 'A1'}, drawing=dm)
check(
    'mirror x about A1 reflects in the 5 m A1 centre: centroid x -730 -> -765',
    abs(sum(o['x'] for o in dm.objs) / 5 - -765.0) < 1e-6 and abs(sum(o['z'] for o in dm.objs) / 5 - -725.0) < 1e-6,
    (sum(o['x'] for o in dm.objs) / 5, sum(o['z'] for o in dm.objs) / 5, txt),
)

from zyg_workflows.arch_assistant import cell_size as _cs, cell_origin as _co, _Scale as _Sc  # noqa: E402

with _Sc(5):
    check(
        'inside a 5 m drawing cell_size() is 5.0 and cell_origin() is -750.0',
        _cs() == 5.0 and _co() == -750.0,
        (_cs(), _co()),
    )
check('and back outside: cell_size() 1.0, cell_origin() -150.0', _cs() == 1.0 and _co() == -150.0, (_cs(), _co()))

import zyg_workflows.arch_assistant_ext.editing_ops as E  # noqa: E402

check('editing_ops imports no frozen CELL_M', not hasattr(E, 'CELL_M'), getattr(E, 'CELL_M', None))
check('the module is back at 1 m after every call', E._A._CELL == {'m': 1.0, 'origin': -150.0}, E._A._CELL)

# ── the tab is alive ──────────────────────────────────────────────────────────
print('tab')
b = browser_kinds([{'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}}])
w = b[0]
check('no page errors', not w.get('page_errors'), w.get('page_errors'))
check(
    'the tab still builds a 4 x 2.7 x 0.24 m wall through arGeom',
    w['ok'] and abs(w['size'][0] - 4) < 0.05 and abs(w['size'][1] - 2.7) < 0.05 and abs(w['size'][2] - 0.24) < 0.05,
    w,
)

finish()
