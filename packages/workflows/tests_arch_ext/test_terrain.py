# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_terrain.py — the terrain family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_terrain.py

Three engines have to agree about the same six kinds. The interesting one is
`terrain`: its height is a noise formula written out three times (JS, Blender,
Python), so the test evaluates the Python copy and asserts the tab's bounding
box matches — if the copies ever drift the landscape silently changes shape.
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
from zyg_workflows.arch_assistant_ext.terrain import (
    terrain_range,
    PROMPT,
    KINDS,  # noqa: E402
    slope_linearity,
    flat_ground,
)
from zyg_workflows import arch_assistant as A  # noqa: E402

NEW_KINDS = ['terrain', 'hill', 'slope', 'plateau', 'retaining_wall', 'berm']


def profile(d, x0, z0, x1, z1, n=41):
    return [A.ground_height(d, x0 + (x1 - x0) * i / (n - 1), z0 + (z1 - z0) * i / (n - 1)) for i in range(n)]


def off_line_pct(ys):
    """Worst departure from the straight line between the ends, as a percentage
    of the rise the profile achieved."""
    rise = ys[-1] - ys[0]
    if abs(rise) < 1e-9:
        return 100.0
    w = max(abs(y - (ys[0] + rise * i / (len(ys) - 1))) for i, y in enumerate(ys))
    return round(w / abs(rise) * 100.0, 2)


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('make_terrain', 'add_hill', 'add_slope', 'add_retaining_wall', 'flatten_pad')),
    names,
)
check('prompt is one paragraph under 900 chars', 0 < len(PROMPT) <= 900 and '\n' not in PROMPT, len(PROMPT))

# make_terrain: one record, sized to the block, amp by style
txt, d = assistant('make_terrain', {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'hills'})
t0 = d.objs[-1]
check(
    'make_terrain drew one terrain sized to the 10x10 block',
    kinds_of(d).get('terrain') == 1 and t0['p']['w'] == 10 and t0['p']['d'] == 10 and t0['p']['amp'] == 3,
    (txt, t0['p']),
)
check(
    'terrain sits on the ground with a group', t0['y'] == 0.0 and t0['grp'] == 'terrain' and t0['id'] in txt, (t0, txt)
)
txt, d = assistant('make_terrain', {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'flat'}, drawing=d)
check("style 'flat' is almost level", d.objs[-1]['p']['amp'] == 0.2, txt)
txt, d = assistant('make_terrain', {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'lunar'}, drawing=d)
check('unknown style refused', txt.startswith('refused'), txt)
txt, d = assistant('make_terrain', {'cell_from': 'A1', 'cell_to': 'ZZ9'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)

# add_hill
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 6, 'height': 2}, drawing=d)
check(
    'add_hill drew one hill',
    kinds_of(d).get('hill') == 1 and d.objs[-1]['p']['r'] == 6 and d.objs[-1]['p']['h'] == 2,
    txt,
)
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 0.1}, drawing=d)
check('silly radius refused', txt.startswith('refused'), txt)
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 6, 'height': 0}, drawing=d)
check('zero height refused', txt.startswith('refused'), txt)

# add_slope: the block is 8 (x) by 4 (z); climbing along x swaps w and d
txt, d = assistant('add_slope', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 1.5, 'direction': 'x'}, drawing=d)
sx = d.objs[-1]
check(
    'slope along x: run 8 m, width 4 m, turned 90 deg',
    sx['kind'] == 'slope' and sx['p']['d'] == 8 and sx['p']['w'] == 4 and sx['p']['dir'] == 90 and sx['p']['h'] == 1.5,
    (txt, sx['p']),
)
txt, d = assistant('add_slope', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 1.5, 'direction': 'z'}, drawing=d)
sz = d.objs[-1]
check(
    'slope along z: run 4 m, width 8 m, unturned',
    sz['p']['d'] == 4 and sz['p']['w'] == 8 and sz['p']['dir'] == 0,
    (txt, sz['p']),
)
txt, d = assistant('add_slope', {'cell_from': 'D20', 'cell_to': 'K23', 'height': 1.5, 'direction': 'up'}, drawing=d)
check('bad direction refused', txt.startswith('refused'), txt)

# add_retaining_wall: 3 cells -> 2 records
before = kinds_of(d).get('retaining_wall', 0)
txt, d = assistant('add_retaining_wall', {'cells': ['E10', 'E16', 'J16'], 'height': 1.2}, drawing=d)
walls = [o for o in d.objs if o['kind'] == 'retaining_wall']
check('3 cells give 2 retaining walls', kinds_of(d).get('retaining_wall', 0) - before == 2, txt)
check(
    '...6 m and 5 m long, 1.2 m tall',
    abs(walls[0]['p']['len'] - 6) < 1e-6 and abs(walls[1]['p']['len'] - 5) < 1e-6 and walls[0]['p']['h'] == 1.2,
    [w['p'] for w in walls],
)
txt, d = assistant('add_retaining_wall', {'cells': ['E10']}, drawing=d)
check('one cell refused', txt.startswith('refused'), txt)

# flatten_pad uses the built-in 'pad' kind
txt, d = assistant('flatten_pad', {'cell_from': 'F22', 'cell_to': 'I25'}, drawing=d)
pad = d.objs[-1]
check('flatten_pad lays a 4x4 pad', pad['kind'] == 'pad' and pad['p']['w'] == 4 and pad['p']['d'] == 4, (txt, pad['p']))

# add_object must accept every new kind (they are in KINDS)
txt, d = assistant('add_object', {'kind': 'berm', 'cell': 'A1', 'params': {'len': 30, 'w': 5, 'h': 1.5}}, drawing=d)
check('add_object knows berm', d.objs[-1]['kind'] == 'berm' and d.objs[-1]['p']['len'] == 30, txt)
txt, d = assistant('add_object', {'kind': 'plateau', 'cell': 'A1', 'params': {'w': 30, 'd': 20, 'h': 2}}, drawing=d)
check('add_object knows plateau', d.objs[-1]['kind'] == 'plateau' and d.objs[-1]['p']['h'] == 2, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all six', sorted(KINDS) == sorted(NEW_KINDS), sorted(KINDS))

# ── the same five tools on a v3 SCULPTED ground ───────────────────────────────
# `flat_ground()` is a drawing whose only record is a `ground` with amp 0, so a
# profile through it measures the sculpt and nothing else.
print('sculpted ground')
XMIN, ZMIN, XMAX, ZMAX = A.block_bounds('D20', 'M35')
CX, CZ = (XMIN + XMAX) / 2, (ZMIN + ZMAX) / 2
W, D = XMAX - XMIN, ZMAX - ZMIN

g = flat_ground()
check(
    'the fixture really is a sculpted ground, and flat',
    kinds_of(g) == {'ground': 1} and abs(A.ground_height(g, CX, CZ)) < 1e-9,
    kinds_of(g),
)

# 1. make_terrain is refused — a drawing has only ONE ground
txt, _ = assistant('make_terrain', {'cell_from': 'D20', 'cell_to': 'M35'}, drawing=flat_ground())
check(
    'make_terrain refused on a sculpted ground, naming the way out',
    txt.startswith('refused') and 'raise_ground' in txt and 'lower_ground' in txt,
    txt,
)
check('...and nothing was drawn', kinds_of(flat_ground()).get('terrain') is None, txt)

# 2. add_hill -> sculpt_peak with rug 0, and the OLD hill profile exactly
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 10, 'height': 4}, drawing=flat_ground())
hp = d.objs[-1]
check(
    'add_hill lays a sculpt_peak, not a hill solid',
    kinds_of(d) == {'ground': 1, 'sculpt_peak': 1} and hp['y'] == 0.0,
    (txt, kinds_of(d)),
)
check(
    '...with ruggedness 0, so it is the old smooth mound',
    hp['p']['rug'] == 0 and hp['p']['r'] == 10 and hp['p']['h'] == 4,
    hp['p'],
)
hx, hz = A.cell_centre(*A.parse_cell('P30'))
check(
    'hill ground_height: 4 m at the centre, 2 m at r/2, 0 at the rim (h*0.5*(1+cos(pi*rho/r)))',
    abs(A.ground_height(d, hx, hz) - 4.0) < 1e-6
    and abs(A.ground_height(d, hx + 5, hz) - 2.0) < 1e-6
    and abs(A.ground_height(d, hx + 10, hz)) < 1e-6,
    [round(A.ground_height(d, hx + q, hz), 4) for q in (0, 5, 10, 12)],
)
check(
    'the hill does not leak past its own radius',
    abs(A.ground_height(d, hx + 10.5, hz)) < 1e-9 and abs(A.ground_height(d, hx, hz - 14)) < 1e-9,
)

# 3. add_slope -> ONE sculpt_step whose ground_height profile is linear within 10 %
lin = slope_linearity()
check(
    'add_slope picked the ramp that measures linear: sculpt_step %.2f %% vs sculpt_flat %.2f %%'
    % (lin['step'], lin['flat']),
    lin['step'] < 10.0 and lin['flat'] > 10.0 and lin['step'] < lin['flat'],
    lin,
)

txt, d = assistant(
    'add_slope', {'cell_from': 'D20', 'cell_to': 'M35', 'height': 4, 'direction': 'z'}, drawing=flat_ground()
)
sp = d.objs[-1]
check(
    'add_slope lays one sculpt_step, not a slope solid',
    kinds_of(d) == {'ground': 1, 'sculpt_step': 1} and sp['y'] == 0.0,
    (txt, kinds_of(d)),
)
check(
    '...3 runs deep, feather = the whole run, rug 0 (the back feather IS the ramp)',
    sp['p']['d'] == 3 * D and sp['p']['feather'] == D and sp['p']['rug'] == 0 and sp['p']['h'] == 4,
    (sp['p'], D),
)
zs = profile(d, CX, ZMIN, CX, ZMAX)
check(
    "direction 'z' climbs south: 0 m at the north edge, the full 4 m at the south edge",
    abs(zs[0]) < 1e-6 and abs(zs[-1] - 4.0) < 1e-6,
    (round(zs[0], 4), round(zs[-1], 4)),
)
check(
    '...and that profile is straight within 10 %% (measured %.2f %%)' % off_line_pct(zs),
    off_line_pct(zs) < 10.0,
    off_line_pct(zs),
)
check(
    '...level across the run: the same height right across the block at the top',
    max(abs(A.ground_height(d, x, ZMAX) - 4.0) for x in (XMIN + 0.05, CX, XMAX - 0.05)) < 1e-6,
    [round(A.ground_height(d, x, ZMAX), 4) for x in (XMIN + 0.05, CX, XMAX - 0.05)],
)

txt, d = assistant(
    'add_slope', {'cell_from': 'D20', 'cell_to': 'M35', 'height': 4, 'direction': 'x'}, drawing=flat_ground()
)
xs2 = profile(d, XMIN, CZ, XMAX, CZ)
check(
    "direction 'x' climbs east, straight within 10 %% too (%.2f %%)" % off_line_pct(xs2),
    abs(xs2[0]) < 1e-6 and abs(xs2[-1] - 4.0) < 1e-6 and off_line_pct(xs2) < 10.0,
    (round(xs2[0], 4), round(xs2[-1], 4), off_line_pct(xs2)),
)

# 4. flatten_pad -> sculpt_flat at the MEAN ground height: cut AND fill
d = flat_ground()
assistant('add_slope', {'cell_from': 'D20', 'cell_to': 'M35', 'height': 4, 'direction': 'z'}, drawing=d)
pxmin, pzmin, pxmax, pzmax = A.block_bounds('F22', 'K30')
before = [
    A.ground_height(d, pxmin + 0.05 + i / 6 * (pxmax - pxmin - 0.1), pzmin + 0.05 + j / 6 * (pzmax - pzmin - 0.1))
    for i in range(7)
    for j in range(7)
]
txt, d = assistant('flatten_pad', {'cell_from': 'F22', 'cell_to': 'K30'}, drawing=d)
pad = d.objs[-1]
flat = [o for o in d.objs if o['kind'] == 'sculpt_flat']
after = [
    A.ground_height(d, pxmin + 0.05 + i / 6 * (pxmax - pxmin - 0.1), pzmin + 0.05 + j / 6 * (pzmax - pzmin - 0.1))
    for i in range(7)
    for j in range(7)
]
check(
    'flatten_pad lays a sculpt_flat AND the pad record',
    len(flat) == 1 and pad['kind'] == 'pad' and pad['p']['w'] == 6 and pad['p']['d'] == 9,
    (txt, kinds_of(d), pad['p']),
)
check(
    'the pad is AT the level the sculpt_flat sets',
    abs(pad['y'] - flat[0]['p']['level']) < 1e-9 and abs(pad['y'] - flat[0]['y']) < 1e-9,
    (pad['y'], flat[0]['p']['level']),
)
check(
    'the ground under the pad is level within 0.05 m afterwards (spread %.4f m)' % (max(after) - min(after)),
    max(after) - min(after) <= 0.05,
    (round(min(after), 4), round(max(after), 4)),
)
check(
    '...at the MEAN of the ground that was there',
    abs(pad['y'] - sum(before) / len(before)) <= 0.05,
    (pad['y'], round(sum(before) / len(before), 4)),
)
check(
    'it CUT the high side and FILLED the low side (was %.2f..%.2f m, now %.2f m)'
    % (min(before), max(before), after[0]),
    max(before) - pad['y'] > 0.5 and pad['y'] - min(before) > 0.5,
    (round(max(before) - pad['y'], 3), round(pad['y'] - min(before), 3)),
)

# 5. the solids that STAY solids
txt, d = assistant('add_retaining_wall', {'cells': ['E10', 'E16', 'J16'], 'height': 1.2}, drawing=flat_ground())
check(
    'add_retaining_wall still draws 2 solid walls on a sculpted ground',
    kinds_of(d).get('retaining_wall') == 2 and kinds_of(d).get('sculpt_step') is None,
    txt,
)
txt, d = assistant(
    'add_object', {'kind': 'berm', 'cell': 'P30', 'params': {'len': 30, 'w': 5, 'h': 1.5}}, drawing=flat_ground()
)
check('a berm is still a berm on a sculpted ground', d.objs[-1]['kind'] == 'berm', txt)

# 6. a HIDDEN ground is no ground — every tool goes straight back to the old path
d = flat_ground()
[o for o in d.objs if o['kind'] == 'ground'][0]['hidden'] = True
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 10, 'height': 4}, drawing=d)
check('hide the ground and add_hill draws the old solid hill again', d.objs[-1]['kind'] == 'hill', (txt, kinds_of(d)))
txt, d = assistant('make_terrain', {'cell_from': 'D20', 'cell_to': 'M35'}, drawing=d)
check('...and make_terrain is allowed again', not txt.startswith('refused'), txt)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'terrain', 'p': {'w': 20, 'd': 20, 'amp': 2, 'seed': 1, 'res': 16, 'base': 0}},
    {'kind': 'hill', 'p': {'r': 8, 'h': 3}},
    {'kind': 'slope', 'p': {'w': 12, 'd': 8, 'h': 2, 'dir': 0}},
    {'kind': 'plateau', 'p': {'w': 20, 'd': 14, 'h': 2, 'batter': 0.5}},
    {'kind': 'retaining_wall', 'p': {'len': 10, 'h': 2, 't': 0.3, 'batter': 0.1}},
    {'kind': 'berm', 'p': {'len': 24, 'w': 4, 'h': 1.2}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check('every kind builds real geometry', all(r['ok'] for r in b), [(r['kind'], r['ok'], r['err']) for r in b])

lo, hi = terrain_range(16, 1)
want_y = 2 * (hi - lo)
tr = by['terrain']
check('terrain spans 20 x 20 m on the plan', abs(tr['size'][0] - 20) < 0.01 and abs(tr['size'][2] - 20) < 0.01, tr)
check(
    'terrain height matches the Python noise within 5%%: want %.3f m' % want_y,
    abs(tr['size'][1] - want_y) <= 0.05 * want_y,
    (tr['size'], want_y),
)
check(
    'hill r8 h3 is 16 x 3 x 16',
    abs(by['hill']['size'][0] - 16) < 0.02
    and abs(by['hill']['size'][1] - 3) < 0.02
    and abs(by['hill']['size'][2] - 16) < 0.02,
    by['hill'],
)
check(
    'slope w12 d8 h2 is 12 x 2 x 8',
    abs(by['slope']['size'][0] - 12) < 0.01
    and abs(by['slope']['size'][1] - 2) < 0.01
    and abs(by['slope']['size'][2] - 8) < 0.01,
    by['slope'],
)
check(
    'plateau base is 20 x 14, 2 m tall',
    abs(by['plateau']['size'][0] - 20) < 0.01
    and abs(by['plateau']['size'][1] - 2) < 0.01
    and abs(by['plateau']['size'][2] - 14) < 0.01,
    by['plateau'],
)
check(
    'retaining wall is 10 long, 2 tall, 0.5 thick at the base (t + batter*h)',
    abs(by['retaining_wall']['size'][0] - 10) < 0.01
    and abs(by['retaining_wall']['size'][1] - 2) < 0.01
    and abs(by['retaining_wall']['size'][2] - 0.5) < 0.01,
    by['retaining_wall'],
)
check(
    'berm is 24 long, 1.2 tall, 4 wide',
    abs(by['berm']['size'][0] - 24) < 0.01
    and abs(by['berm']['size'][1] - 1.2) < 0.01
    and abs(by['berm']['size'][2] - 4) < 0.01,
    by['berm'],
)
check('terrain is a 17x17 lattice of triangles', by['terrain']['tris'] == 2 * 16 * 16, by['terrain']['tris'])
check(
    'labels',
    [by[k]['label'] for k in NEW_KINDS] == ['Terrain', 'Hill', 'Slope', 'Plateau', 'Retaining wall', 'Berm'],
    [by[k]['label'] for k in NEW_KINDS],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
check('blender builds the terrain lattice', bl.get('terrain', {}).get('polys', 0) > 16 * 16 / 2, bl.get('terrain'))
check('blender builds the hill', bl.get('hill', {}).get('polys', 0) > 32, bl.get('hill'))
for k, floor in (('slope', 0), ('plateau', 0), ('retaining_wall', 0), ('berm', 0)):
    check('blender builds %s' % k, bl.get(k, {}).get('polys', 0) > floor, bl.get(k))
finish()
