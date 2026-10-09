# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_mountains.py — the mountains family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_mountains.py

Three engines have to agree about the same six kinds. The interesting one is
`mountain`: its lattice is NORMALISED, so "h tall" means the summit in the tab,
in Blender and in the assistant's own arithmetic — a bounding box therefore
cannot betray a drifted noise copy. The snow cap can: the highest triangle
centroid of the lattice is a purely noise-dependent number, and the tab reports
how many parts it built. snow_ceiling() computes that number in Python and the
test asks the tab for two parts just under it and one part just over it.

Since 2026-09-07 there is a FOURTH engine to agree with: HEIGHTS, the ground
seam. Every kind exports the height of its own top surface at a local plan
point, and the maximum of that field over a fine lattice must be the tab's
bounding-box height — so nothing placed on a mountain is buried in it. The
tools follow the placement rules too: base_height defaults to the ground under
the record, and the real-world proportions (a mountain is 0.25 to 1.0 x its
radius, a mesa 0.8, a ridge 0.8 x its width, a valley 0.4 x its width deep,
snow only above 60 m of summit) are refusals, not advice.

Since v3 (2026-09-07) there are TWO MODES, and the last section proves both. On a
drawing that carries a `ground` record the same four tools write SCULPTS of that
one heightfield instead of solids standing on it — so a peak raises the land
under its centre by exactly its height, and a valley LOWERS it by exactly its
depth, which is the thing the old raised-plinth valley could never do. On a
drawing without one, every old kind, every old refusal and every old sentence is
still exactly what it was: the checks above are the same checks, unedited.
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
from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows.arch_assistant_ext.mountains import (
    PROMPT,
    KINDS,
    HEIGHTS,
    peak_scale,
    snow_ceiling,  # noqa: E402
    peak_radius,
    SNOW_MIN_SUMMIT,
    SNOW_AUTO_LINE,
    has_ground,
    ground_of,
    sculpt_y,
    SCULPT_FEATHER,
    RANGE_SPREAD,
    SCULPT_WORDS,
    SOLID_WORDS,
)
import zyg_workflows.arch_assistant_ext.ground_v3 as G  # noqa: E402

NEW_KINDS = ['mountain', 'mountain_range', 'ridge', 'volcano', 'mesa', 'valley']


def near(a, b, pct=1.5):
    return abs(a - b) <= abs(b) * pct / 100.0 + 1e-9


def field_max(fn, p, w, dd, n=192):
    """The highest point of a HEIGHTS field over a fine lattice of the record's
    own footprint. n is chosen a multiple of the record's res so the lattice
    vertices themselves are sampled."""
    best = 0.0
    for j in range(n + 1):
        lz = -dd / 2 + j / n * dd
        for i in range(n + 1):
            v = fn(p, -w / 2 + i / n * w, lz)
            if v is not None and v > best:
                best = v
    return best


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('add_mountain', 'add_mountain_range', 'add_ridge', 'add_valley')),
    names,
)
check('prompt is one paragraph under 1500 chars', 0 < len(PROMPT) <= 1500 and '\n' not in PROMPT, len(PROMPT))
check(
    'prompt says mountains are ground and names the river tool',
    'before any building' in PROMPT and 'river tool' in PROMPT and 'base_height' in PROMPT and 'berg' in PROMPT,
    PROMPT[:120],
)
check(
    'prompt states the auto snow line and the proportion rule',
    "'auto'" in PROMPT and '60 m' in PROMPT and '0.25 to 1.0 x radius' in PROMPT and 'ground under it' in PROMPT,
    PROMPT,
)

# add_mountain — one peak
txt, d = assistant('add_mountain', {'centre': 'F40', 'radius': 60, 'height': 40})
m = d.objs[-1]
check(
    'add_mountain drew one mountain, r60 h40',
    kinds_of(d).get('mountain') == 1 and m['p']['r'] == 60 and m['p']['h'] == 40,
    (txt, m['p']),
)
check(
    'snow_line auto leaves a 40 m summit BARE (under the %g m line): snow >= 1' % SNOW_MIN_SUMMIT,
    m['p']['snow'] >= 1.0 and 'no snow' in txt,
    (txt, m['p']['snow']),
)
check(
    'mountain sits on the ground, grouped, id reported',
    m['y'] == 0.0 and m['grp'] == 'mountains' and m['mat'] == 'mat_rock' and m['id'] in txt,
    (m, txt),
)
txt, d = assistant(
    'add_mountain', {'centre': 'M50', 'radius': 50, 'height': 35, 'style': 'volcano', 'base_height': 20}, drawing=d
)
v = d.objs[-1]
check(
    'style volcano makes a volcano with a crater, lifted onto the plateau',
    v['kind'] == 'volcano'
    and v['p']['r'] == 50
    and v['p']['h'] == 35
    and v['p']['crater_r'] == 10
    and v['p']['crater_d'] > 0
    and v['y'] == 20.0,
    (txt, v['p'], v['y']),
)
txt, d = assistant('add_mountain', {'centre': 'T50', 'radius': 40, 'height': 25, 'style': 'mesa'}, drawing=d)
ms = d.objs[-1]
check(
    'style mesa makes a flat-topped mesa, top_r inside r, grass on top',
    ms['kind'] == 'mesa'
    and ms['p']['r'] == 40
    and ms['p']['h'] == 25
    and 0 < ms['p']['top_r'] < 40
    and 'grass top' in txt,
    (txt, ms['p']),
)
for args, why in (
    ({'centre': 'F40', 'radius': 2}, 'radius under 5 m'),
    ({'centre': 'F40', 'radius': 500}, 'radius over 400 m'),
    ({'centre': 'F40', 'height': 0}, 'zero height'),
    ({'centre': 'F40', 'height': 4000}, 'height over 3000 m'),
    ({'centre': 'F40', 'style': 'crag'}, 'unknown style'),
    ({'centre': 'ZZ9', 'radius': 60}, 'off-grid cell'),
):
    txt2, d = assistant('add_mountain', args, drawing=d)
    check('add_mountain refuses %s' % why, txt2.startswith('refused'), txt2)

# R7 — the proportions of a real mountain
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 20, 'height': 60}, drawing=d)
check(
    'R7 needle refused: 60 m on a 20 m radius, with the real range in the words',
    txt2
    == (
        'refused: 60 m on a 20 m radius is a needle — a mountain is at most as tall as its radius; '
        'use radius 60 or height 20'
    ),
    txt2,
)
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 60, 'height': 10}, drawing=d)
check(
    'R7 too flat refused and sent to add_hill',
    txt2.startswith('refused') and 'add_hill' in txt2 and '0.25' in txt2,
    txt2,
)
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 40, 'height': 36, 'style': 'mesa'}, drawing=d)
check('R7 a mesa is at most 0.8 x its radius', txt2.startswith('refused') and '0.8' in txt2, txt2)

# snow_line: 'auto', a number, 'none'
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 100, 'height': 80}, drawing=d)
check(
    'auto caps an %g m summit at %g' % (80, SNOW_AUTO_LINE),
    d.objs[-1]['p']['snow'] == SNOW_AUTO_LINE and 'snow above' in txt2,
    (txt2, d.objs[-1]['p']),
)
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 100, 'height': 80, 'snow_line': 0.6}, drawing=d)
check('an explicit snow_line still works', d.objs[-1]['p']['snow'] == 0.6, d.objs[-1]['p'])
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 100, 'height': 80, 'snow_line': 'none'}, drawing=d)
check("snow_line 'none' leaves the summit bare", d.objs[-1]['p']['snow'] >= 1.0, d.objs[-1]['p'])
txt2, d = assistant('add_mountain', {'centre': 'F40', 'radius': 100, 'height': 80, 'snow_line': 'plenty'}, drawing=d)
check('junk snow_line refused', txt2.startswith('refused') and 'auto' in txt2, txt2)

# add_mountain_range — sized to the block, turned when the block is deeper than wide
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'height': 3, 'peaks': 4}, drawing=d)
rg = d.objs[-1]
check(
    'range over a 20x10 block: 20 long, 10 deep, 4 peaks, unturned',
    rg['kind'] == 'mountain_range'
    and rg['p']['len'] == 20
    and rg['p']['w'] == 10
    and rg['p']['peaks'] == 4
    and rg['p']['h'] == 3
    and rg['ry'] == 0.0,
    (txt, rg['p']),
)
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'J20', 'height': 3}, drawing=d)
rt = d.objs[-1]
check(
    'a block deeper than wide is turned a quarter, len still the longer side',
    rt['p']['len'] == 20 and rt['p']['w'] == 10 and abs(rt['ry'] - math.pi / 2) < 1e-5,
    (txt, rt['p'], rt['ry']),
)
PR = peak_radius(20, 4)
check('peak_radius(20, 4) is 0.65 x len / peaks = %.2f m' % PR, abs(PR - 3.25) < 1e-9, PR)
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'peaks': 4}, drawing=d)
check(
    'R7 no height given: the range takes 0.7 x the peak radius = %.3f m' % (0.7 * PR),
    abs(d.objs[-1]['p']['h'] - round(0.7 * PR, 3)) < 1e-9,
    d.objs[-1]['p'],
)
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'height': 50, 'peaks': 4}, drawing=d)
check(
    'R7 50 m over a 20 m block refused, and the real cap is in the words',
    txt.startswith('refused') and '3.2' in txt and 'needles' in txt,
    txt,
)
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'peaks': 0}, drawing=d)
check('range with no peaks refused', txt.startswith('refused'), txt)
txt, d = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'height': -5}, drawing=d)
check('range with negative height refused', txt.startswith('refused'), txt)

# add_ridge — one per consecutive pair, turned by atan2
before = kinds_of(d).get('ridge', 0)
txt, d = assistant('add_ridge', {'cells': ['E20', 'K20', 'K34'], 'height': 15, 'base_height': 5}, drawing=d)
ridges = [o for o in d.objs if o['kind'] == 'ridge']
check('3 cells give 2 ridges', kinds_of(d).get('ridge', 0) - before == 2, txt)
check(
    '...6 m and 14 m of crest, 15 m tall, second one turned to run north',
    ridges[0]['p']['len'] == 6
    and ridges[1]['p']['len'] == 14
    and ridges[0]['p']['h'] == 15
    and ridges[0]['ry'] == 0.0
    and abs(ridges[1]['ry'] + math.pi / 2) < 1e-5,
    [(r['p'], r['ry']) for r in ridges],
)
check('base_height lifts the ridges onto the plateau', all(r['y'] == 5.0 for r in ridges), [r['y'] for r in ridges])
check('a ridge is GRASS by default', all(r['mat'] == 'mat_grass' for r in ridges), [r['mat'] for r in ridges])
txt, d = assistant('add_ridge', {'cells': ['E20']}, drawing=d)
check('one cell refused — a ridge needs two', txt.startswith('refused'), txt)
txt, d = assistant('add_ridge', {'cells': ['E20', 'K20'], 'height': 0}, drawing=d)
check('zero height ridge refused', txt.startswith('refused'), txt)
txt, d = assistant('add_ridge', {'cells': ['E20', 'K20'], 'height': 30, 'width': 20}, drawing=d)
check(
    'R7 a 30 m crest on a 20 m foot is a blade: refused at 0.8 x width',
    txt.startswith('refused') and '0.8' in txt and '16' in txt,
    txt,
)

# add_valley — the trough a river runs down
txt, d = assistant(
    'add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 18, 'direction': 'z', 'floor_width': 25}, drawing=d
)
va = d.objs[-1]
check(
    'valley along z: 47 across, 61 along, 18 deep, 25 m floor, V profile, unturned',
    va['kind'] == 'valley'
    and va['p']['w'] == 47
    and va['p']['d'] == 61
    and va['p']['h'] == 18
    and va['p']['floor_w'] == 25
    and va['p']['profile'] == 0
    and va['ry'] == 0.0,
    (txt, va['p']),
)
check(
    'the valley is GRASS with a soil floor, and sends the model to a river tool',
    va['mat'] == 'mat_grass' and 'soil floor' in txt and 'river' in txt and va['id'] in txt,
    (txt, va['mat']),
)
txt, d = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'direction': 'x', 'profile': 'u'}, drawing=d)
vx = d.objs[-1]
check(
    "direction 'x' swaps across/along and turns the record a quarter, profile u = 1",
    vx['p']['w'] == 61 and vx['p']['d'] == 47 and vx['p']['profile'] == 1 and abs(vx['ry'] - math.pi / 2) < 1e-5,
    (txt, vx['p'], vx['ry']),
)
check(
    'no depth given: 0.35 x the 61 m across = %.2f m' % (0.35 * 61),
    abs(vx['p']['h'] - round(0.35 * 61, 3)) < 1e-9,
    vx['p'],
)
txt, d = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'direction': 'up'}, drawing=d)
check('bad direction refused', txt.startswith('refused'), txt)
txt, d = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'profile': 'w'}, drawing=d)
check('bad profile refused', txt.startswith('refused'), txt)
txt, d = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'floor_width': 200}, drawing=d)
check('a floor wider than the valley refused', txt.startswith('refused'), txt)
txt, d = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 40}, drawing=d)
check(
    'R7 40 m deep across 47 m is a canyon: refused at 0.4 x the width',
    txt.startswith('refused') and '0.4' in txt and '18.8' in txt,
    txt,
)

# add_object must accept the kinds directly
txt, d = assistant('add_object', {'kind': 'mesa', 'cell': 'A1', 'params': {'r': 30, 'h': 18, 'top_r': 20}}, drawing=d)
check('add_object knows mesa', d.objs[-1]['kind'] == 'mesa' and d.objs[-1]['p']['r'] == 30, txt)
txt, d = assistant('add_object', {'kind': 'valley', 'cell': 'A1', 'params': {'w': 90, 'd': 60, 'h': 20}}, drawing=d)
check('add_object knows valley', d.objs[-1]['kind'] == 'valley' and d.objs[-1]['p']['h'] == 20, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all six', sorted(KINDS) == sorted(NEW_KINDS), sorted(KINDS))

# ── R1/R6: the ground under the record ────────────────────────────────────────
print('ground')
check('all six kinds export HEIGHTS into the seam', all(k in A.EXT_HEIGHTS for k in NEW_KINDS), sorted(A.EXT_HEIGHTS))
dg = A.Drawing({'objects': []})
txt, dg = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'}, drawing=dg)
gx, gz = A.cell_centre(*A.parse_cell('E5'))
want = A.ground_height(dg, gx, gz)
check('the terrain slope really stands 2.025 m under E5', abs(want - 2.025) < 1e-6, want)
txt, dg = assistant('add_mountain', {'centre': 'E5', 'radius': 20, 'height': 15}, drawing=dg)
check(
    'R1 add_mountain with no base_height lands ON the slope, not at y=0',
    abs(dg.objs[-1]['y'] - want) < 1e-3 and dg.objs[-1]['y'] > 2.0,
    (dg.objs[-1]['y'], want),
)
txt, dg = assistant('add_mountain', {'centre': 'E5', 'radius': 20, 'height': 15, 'base_height': 12}, drawing=dg)
check('R1 an explicit base_height still overrides the ground', dg.objs[-1]['y'] == 12.0, dg.objs[-1]['y'])

dr = A.Drawing({'objects': []})
txt, dr = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'}, drawing=dr)
rx, rz = (
    (A.cell_centre(*A.parse_cell('C3'))[0] + A.cell_centre(*A.parse_cell('H8'))[0]) / 2,
    (A.cell_centre(*A.parse_cell('C3'))[1] + A.cell_centre(*A.parse_cell('H8'))[1]) / 2,
)
rwant = A.ground_height(dr, rx, rz)
txt, dr = assistant('add_ridge', {'cells': ['C3', 'H8'], 'height': 3, 'width': 6}, drawing=dr)
check(
    'R1 a ridge with no base_height lands on the slope under its own centre',
    abs(dr.objs[-1]['y'] - rwant) < 1e-3 and rwant > 1.0,
    (dr.objs[-1]['y'], rwant),
)

dv = A.Drawing({'objects': []})
txt, dv = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'}, drawing=dv)
vb = A.block_bounds('A1', 'J10')
vwant = A.ground_height(dv, (vb[0] + vb[2]) / 2, (vb[1] + vb[3]) / 2)
txt, dv = assistant('add_valley', {'cell_from': 'A1', 'cell_to': 'J10', 'depth': 3, 'floor_width': 4}, drawing=dv)
check(
    'R1 a valley with no base_height lands on the ground under its centre',
    dv.objs[-1]['kind'] == 'valley' and abs(dv.objs[-1]['y'] - vwant) < 1e-3 and vwant > 2.0,
    (txt, dv.objs[-1]['y'], vwant),
)

ds = A.Drawing({'objects': []})
txt, ds = assistant('add_mountain', {'centre': 'F40', 'radius': 60, 'height': 40}, drawing=ds)
big = ds.objs[-1]
stack = A.ground_height(ds, big['x'], big['z'])
txt, ds = assistant('add_mountain', {'centre': 'F40', 'radius': 20, 'height': 15}, drawing=ds)
check(
    'R6 a mountain stacks on a mountain: its own HEIGHTS is the ground (%.2f m)' % stack,
    stack > 10 and abs(ds.objs[-1]['y'] - stack) < 1e-3,
    (ds.objs[-1]['y'], stack),
)

# ── the Python arithmetic the tab has to match ────────────────────────────────
check(
    'peak_scale of a smooth cone is h itself (raw maximum 1)',
    peak_scale(60, 40, 0, 1, 48) == 40.0,
    peak_scale(60, 40, 0, 1, 48),
)
PS = peak_scale(60, 40, 0.45, 1, 48)
check('a rugged lattice needs scaling UP to reach h: %.4f > 40' % PS, 40 < PS < 80, PS)
CEIL = snow_ceiling(60, 40, 0.45, 3, 8)
check('snow_ceiling is a real noise number, well under 1: %.5f' % CEIL, 0.5 < CEIL < 0.99, CEIL)
check(
    'snow_ceiling moves with the seed',
    len({round(snow_ceiling(60, 40, 0.45, s, 8), 6) for s in (1, 2, 3, 4)}) == 4,
    [round(snow_ceiling(60, 40, 0.45, s, 8), 6) for s in (1, 2, 3, 4)],
)

# HEIGHTS: the named points of the shapes with an exact answer
VP = {'r': 50, 'h': 35, 'crater_r': 10, 'crater_d': 8, 'seg': 48, 'rings': 16}
check(
    'volcano HEIGHTS: the rim (r = crater_r) is h, the crater centre is h - crater_d',
    abs(HEIGHTS['volcano'](VP, 10, 0) - 35) < 1e-9 and abs(HEIGHTS['volcano'](VP, 0, 0) - 27) < 1e-9,
    (HEIGHTS['volcano'](VP, 10, 0), HEIGHTS['volcano'](VP, 0, 0)),
)
check(
    'volcano HEIGHTS: the foot is 0 and outside the foot is None',
    abs(HEIGHTS['volcano'](VP, 50, 0)) < 1e-9 and HEIGHTS['volcano'](VP, 51, 0) is None,
    (HEIGHTS['volcano'](VP, 50, 0), HEIGHTS['volcano'](VP, 51, 0)),
)
VL = {'w': 120, 'd': 80, 'h': 30, 'floor_w': 20, 'profile': 0, 'res': 32}
check(
    'valley HEIGHTS: the floor is 0 at the centre and h at the rim',
    HEIGHTS['valley'](VL, 0, 0) == 0.0 and abs(HEIGHTS['valley'](VL, 60, 0) - 30) < 1e-9,
    (HEIGHTS['valley'](VL, 0, 0), HEIGHTS['valley'](VL, 60, 0)),
)
check(
    'valley HEIGHTS: still 0 anywhere on the flat floor, None off the block',
    HEIGHTS['valley'](VL, 9.9, 30) == 0.0 and HEIGHTS['valley'](VL, 0, 41) is None,
    (HEIGHTS['valley'](VL, 9.9, 30), HEIGHTS['valley'](VL, 0, 41)),
)
ME = {'r': 40, 'h': 25, 'top_r': 30, 'rug': 0.25, 'seed': 1, 'seg': 48}
check(
    'mesa HEIGHTS: the table top is flat at h, the foot is 0',
    abs(HEIGHTS['mesa'](ME, 0, 0) - 25) < 1e-9 and abs(HEIGHTS['mesa'](ME, 40, 0)) < 1e-9,
    (HEIGHTS['mesa'](ME, 0, 0), HEIGHTS['mesa'](ME, 40, 0)),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
MT = {'r': 60, 'h': 40, 'rug': 0.45, 'seed': 1, 'res': 48, 'snow': 0.7}
LOW = dict(MT, seed=3, res=8, snow=round(CEIL - 0.02, 6))
HIGH = dict(MT, seed=3, res=8, snow=round(CEIL + 0.02, 6))
RANGE_P = {'len': 200, 'w': 80, 'h': 50, 'peaks': 4, 'rug': 0.45, 'seed': 1, 'res': 64, 'snow': 0.75}
RIDGE_P = {'len': 80, 'w': 20, 'h': 15, 'rug': 0.3, 'seed': 1, 'res': 32}
MESA_P = {'r': 40, 'h': 25, 'top_r': 30, 'rug': 0.25, 'seed': 1, 'seg': 48}
cases = [
    {'kind': 'mountain', 'p': dict(MT)},  # 0
    {'kind': 'mountain', 'p': dict(MT, snow=2.0)},  # 1
    {'kind': 'mountain', 'p': LOW},  # 2
    {'kind': 'mountain', 'p': HIGH},  # 3
    {'kind': 'mountain_range', 'p': dict(RANGE_P)},  # 4
    {'kind': 'ridge', 'p': dict(RIDGE_P)},  # 5
    {'kind': 'volcano', 'p': dict(VP)},  # 6
    {'kind': 'mesa', 'p': dict(MESA_P)},  # 7
    {'kind': 'mesa', 'p': {'r': 40, 'h': 25, 'top_r': 30, 'rug': 0.9, 'seed': 5, 'seg': 48}},  # 8
    {'kind': 'valley', 'p': dict(VL)},  # 9
    {'kind': 'valley', 'p': dict(VL, profile=1)},  # 10
    {'kind': 'valley', 'p': dict(VL, floor_w=0)},  # 11
]
b = browser_kinds(cases)
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check(
    'every case builds real geometry',
    all(r['ok'] for r in b),
    [(i, r['kind'], r['ok'], r['err']) for i, r in enumerate(b)],
)
check(
    'every kind is registered in AR_EXT.geom',
    all(r['registered'] for r in b),
    [(r['kind'], r['registered']) for r in b],
)

mt = b[0]
check(
    'mountain r60 h40 is 120 x 40 x 120',
    near(mt['size'][0], 120) and near(mt['size'][1], 40) and near(mt['size'][2], 120),
    mt['size'],
)
check('the mountain foot is flat on the ground (box starts at y=0)', abs(mt['min'][1]) < 0.01, mt['min'])
check(
    'h IS the summit: the tab agrees with the normalised Python lattice within 1%',
    near(mt['size'][1], 40, 1.0),
    (mt['size'][1], 40),
)
check('mountain is a 49x49 lattice of triangles', mt['tris'] == 2 * 48 * 48, mt['tris'])
check('snow 0.7 builds a rock part AND a snow part', mt['parts'] == 2, mt)
check('snow 2.0 leaves one part and no cap', b[1]['parts'] == 1 and b[1]['tris'] == 2 * 48 * 48, b[1])
check('snow just UNDER the Python snow_ceiling (%.5f) still caps: 2 parts' % CEIL, b[2]['parts'] == 2, b[2])
check('snow just OVER it does not: 1 part — the three noise copies agree', b[3]['parts'] == 1, b[3])

rgb = b[4]
check(
    'mountain_range len200 w80 h50 is 200 x 50 x 80',
    near(rgb['size'][0], 200) and near(rgb['size'][1], 50) and near(rgb['size'][2], 80),
    rgb['size'],
)
check('the range has a snow cap too', rgb['parts'] == 2, rgb)
rd = b[5]
check(
    'ridge len80 w20 h15 is 80 x 15 x 20',
    near(rd['size'][0], 80) and near(rd['size'][1], 15) and near(rd['size'][2], 20),
    rd['size'],
)
vo = b[6]
check(
    'volcano r50 h35 is 100 x 35 x 100',
    near(vo['size'][0], 100) and near(vo['size'][1], 35) and near(vo['size'][2], 100),
    vo['size'],
)
check('the volcano rim is the top of the box — the crater digs down inside it', abs(vo['min'][1]) < 0.01, vo['min'])
me = b[7]
check(
    'mesa r40 h25 top_r30 is 80 x 25 x 80',
    near(me['size'][0], 80) and near(me['size'][1], 25) and near(me['size'][2], 80),
    me['size'],
)
check('the mesa top is flat at h: max y = 25', near(me['min'][1] + me['size'][1], 25, 1.0), (me['min'], me['size']))
check('the mesa is TWO parts: rock cliffs and a grass table top', me['parts'] == 2, me)
check(
    'heavy erosion (rug 0.9) neither lifts the top nor eats the foot',
    near(b[8]['size'][0], 80) and near(b[8]['size'][1], 25) and near(b[8]['size'][2], 80),
    b[8]['size'],
)
vl = b[9]
check(
    'valley w120 d80 h30 is 120 x 30 x 80',
    near(vl['size'][0], 120) and near(vl['size'][1], 30) and near(vl['size'][2], 80),
    vl['size'],
)
check('the valley floor is at y=0 and the sides rise to h', abs(vl['min'][1]) < 0.01, vl['min'])
check('the valley is TWO parts: grass sides and a soil floor strip', vl['parts'] == 2, vl)
check(
    'a valley with no floor (floor_w 0) is one part and the SAME box',
    b[11]['parts'] == 1 and near(b[11]['size'][0], 120) and near(b[11]['size'][1], 30) and near(b[11]['size'][2], 80),
    b[11],
)
check(
    'the U profile is the same box as the V one',
    near(b[10]['size'][0], 120) and near(b[10]['size'][1], 30) and near(b[10]['size'][2], 80),
    b[10]['size'],
)
labels = [b[i]['label'] for i in (0, 4, 5, 6, 7, 9)]
check('labels', labels == ['Mountain', 'Mountain range', 'Ridge', 'Volcano', 'Mesa', 'Valley'], labels)

# ── HEIGHTS is the field the tab draws ────────────────────────────────────────
# max over a fine lattice of the ground fn == the tab's bounding-box height.
for kind, p, fw, fd, n, tab_y in (
    ('mountain', MT, 120, 120, 192, b[0]['size'][1]),
    ('mountain_range', RANGE_P, 200, 80, 192, b[4]['size'][1]),
    ('ridge', RIDGE_P, 80, 20, 192, b[5]['size'][1]),
    ('volcano', VP, 100, 100, 400, b[6]['size'][1]),
    ('mesa', MESA_P, 80, 80, 192, b[7]['size'][1]),
    ('valley', VL, 120, 80, 192, b[9]['size'][1]),
):
    got = field_max(HEIGHTS[kind], p, fw, fd, n)
    check(
        'HEIGHTS[%s] tops out at %.3f m — the tab draws %.3f (within 1%%)' % (kind, got, tab_y),
        near(got, tab_y, 1.0),
        (got, tab_y),
    )

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl_cases = [cases[0], cases[4], cases[5], cases[6], cases[7], cases[9]]
bl = blender_kinds(bl_cases)
for k, floor in (
    ('mountain', 2 * 48 * 48 - 1),
    ('mountain_range', 2 * 64 * 64 - 1),
    ('ridge', 32 * 3),
    ('volcano', 48 * 16),
    ('mesa', 48 * 8),
    ('valley', 32 * 32 - 1),
):
    check('blender builds %s' % k, bl.get(k, {}).get('polys', 0) > floor, bl.get(k))
check(
    'blender gives the valley its soil strip too: res*res quads + 1',
    bl.get('valley', {}).get('polys') == 32 * 32 + 1,
    bl.get('valley'),
)
check(
    'blender: the valley box is still 120 x 30 x 80 with the strip inside it',
    near(bl['valley']['size'][0], 120) and near(bl['valley']['size'][1], 30) and near(bl['valley']['size'][2], 80),
    bl.get('valley'),
)
check(
    'blender: the mesa box is still 80 x 25 x 80 with the grass top split off',
    near(bl['mesa']['size'][0], 80) and near(bl['mesa']['size'][1], 25) and near(bl['mesa']['size'][2], 80),
    bl.get('mesa'),
)
check(
    'blender: the mountain summit is h, as the tab and HEIGHTS both say',
    near(bl['mountain']['size'][1], b[0]['size'][1], 1.0),
    (bl['mountain']['size'], b[0]['size']),
)

# ── v3: the same four tools on a sculpted ground ──────────────────────────────
# A drawing that carries a `ground` record has ONE surface, and everything this
# family draws is a TERM in that surface's height instead of a solid standing on
# it. Same tool names, same refusals, same proportions — a different record kind
# and a different sentence. The proof is arithmetic: a peak must raise the ground
# under its centre by exactly its height, and a valley must LOWER it by exactly
# its depth (the thing the old raised-plinth valley could never do).
print('v3 sculpts')


def g3rec(kind, p, x=0.0, z=0.0, y=0.0, ry=0.0):
    return {
        'id': 'r',
        'kind': kind,
        'name': kind,
        'p': p,
        'x': x,
        'y': y,
        'z': z,
        'rx': 0,
        'ry': ry,
        'rz': 0,
        's': 1,
        'mat': 'mat_soil',
        'hidden': False,
        'grp': '',
    }


def g3relief(p, recs):
    hs, _sand = G.lattice(p, recs)
    flat = [v for row in hs for v in row]
    return max(flat) - min(flat)


def gh(d, g, x, z):
    """The ground's honest height at a world point — H itself, without
    arch_assistant.ground_height's floor at the y=0 base plane."""
    return G.height_at(g['p'], *A.world_to_local(g, x, z), d.objs, g['x'], g['z'], 0.0)


txt, d3 = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'GR200'})
GR = d3.objs[0]


def bare_at(x, z):
    """The ground with NO sculpt in it — what the land would be without us."""
    return G.height_at(GR['p'], *A.world_to_local(GR, x, z), [GR], GR['x'], GR['z'], 0.0)


check(
    'the v3 ground is one 200 x 200 m record at res 100',
    GR['kind'] == 'ground' and GR['p']['w'] == 200 and GR['p']['d'] == 200 and GR['p']['res'] == 100,
    (txt[:80], GR['p']),
)
check(
    'has_ground/ground_of see it, and see nothing on a bare drawing',
    has_ground(d3)
    and ground_of(d3) is GR
    and not has_ground(A.Drawing({'objects': []}))
    and ground_of(A.Drawing({'objects': []})) is None,
    (has_ground(d3), ground_of(d3) is GR),
)
check(
    'sculpt_y is 0 for a raise (the contribution is ADDITIVE) and base_height still overrides',
    sculpt_y(None) == 0.0 and sculpt_y('') == 0.0 and sculpt_y(7) == 7.0,
    (sculpt_y(None), sculpt_y(7)),
)

KX, KZ = A.cell_centre(*A.parse_cell('K20'))
K_BASE = gh(d3, GR, KX, KZ)
txt, d3 = assistant('add_mountain', {'centre': 'K20', 'radius': 40, 'height': 30}, drawing=d3)
pk = d3.objs[-1]
check(
    'add_mountain on a ground draws ONE sculpt_peak and no solid mountain',
    kinds_of(d3).get('sculpt_peak') == 1 and kinds_of(d3).get('mountain') is None,
    kinds_of(d3),
)
check(
    'the sculpt carries r, h and a %d %% rim feather, at the cell centre' % (SCULPT_FEATHER * 100),
    pk['p']['r'] == 40
    and pk['p']['h'] == 30
    and pk['p']['feather'] == 8
    and abs(pk['x'] - KX) < 1e-9
    and abs(pk['z'] - KZ) < 1e-9,
    (pk['p'], pk['x'], pk['z']),
)
check('y is 0: a sculpt is ADDED to the land, so it must not carry the land twice', pk['y'] == 0.0, pk['y'])
K_TOP = gh(d3, GR, KX, KZ)
check(
    'the ground under K20 rose by exactly 30 m: %.4f -> %.4f (within 0.5)' % (K_BASE, K_TOP),
    abs(K_TOP - (K_BASE + 30)) < 0.5,
    (K_BASE, K_TOP),
)
check(
    '...and arch_assistant.ground_height reads that same summit through the seam',
    abs(A.ground_height(d3, KX, KZ) - K_TOP) < 1e-6,
    (A.ground_height(d3, KX, KZ), K_TOP),
)
check(
    'the peak feathers to NOTHING past its rim: 60 m out the land is the bare roll again',
    abs(gh(d3, GR, KX + 60, KZ) - bare_at(KX + 60, KZ)) < 1e-9,
    gh(d3, GR, KX + 60, KZ),
)
check(
    "the reply says '%s' and never claims a solid" % SCULPT_WORDS,
    SCULPT_WORDS in txt and SOLID_WORDS not in txt and pk['id'] in txt,
    txt,
)
check(
    'the reply hands snow to the ground: "snow follows the ground\'s snow height (60 m)"',
    "snow follows the ground's snow height (60 m)" in txt and 'snow_line sets nothing' in txt,
    txt,
)
txt2, d3 = assistant('add_mountain', {'centre': 'F44', 'radius': 100, 'height': 80, 'snow_line': 0.6}, drawing=d3)
check(
    'snow_line on a v3 ground sets NOTHING: the sculpt has no snow parameter at all',
    d3.objs[-1]['kind'] == 'sculpt_peak' and 'snow' not in d3.objs[-1]['p'] and 'snow_line sets nothing' in txt2,
    (txt2, d3.objs[-1]['p']),
)
txt2, d3 = assistant('add_mountain', {'centre': 'F40', 'radius': 60, 'height': 40, 'base_height': 7}, drawing=d3)
check(
    'an explicit base_height still lifts the whole feature',
    d3.objs[-1]['y'] == 7.0 and 'lifted 7 m by base_height' in txt2,
    (txt2, d3.objs[-1]['y']),
)
txt2, d3 = assistant('add_mountain', {'centre': 'T50', 'radius': 40, 'height': 25, 'style': 'mesa'}, drawing=d3)
mv = d3.objs[-1]
check(
    'style mesa becomes a sculpt_mesa with its table top inside the flank',
    mv['kind'] == 'sculpt_mesa'
    and mv['p']['r'] == 40
    and mv['p']['h'] == 25
    and 0 < mv['p']['top_r'] < 40
    and SCULPT_WORDS in txt2,
    (txt2, mv['p']),
)
MX, MZ = A.cell_centre(*A.parse_cell('M50'))
M_GROUND = A.ground_height(d3, MX, MZ)
txt2, d3 = assistant('add_mountain', {'centre': 'M50', 'radius': 50, 'height': 35, 'style': 'volcano'}, drawing=d3)
vv = d3.objs[-1]
check(
    'a volcano stays a SOLID even here — and the reply says why (no crater sculpt yet)',
    vv['kind'] == 'volcano'
    and vv['p']['crater_r'] == 10
    and 'a crater is not a sculpt yet' in txt2
    and SCULPT_WORDS not in txt2,
    (txt2, vv['kind']),
)
check(
    '...and it stands ON the sculpted ground under it (%.2f m up a sculpted flank), not at y=0' % M_GROUND,
    abs(vv['y'] - M_GROUND) < 1e-3 and vv['y'] > 1.0,
    (vv['y'], M_GROUND),
)
txt2, d3 = assistant('add_mountain', {'centre': 'F40', 'radius': 20, 'height': 60}, drawing=d3)
check(
    'R7 still refuses a needle on a v3 ground — the proportions come first',
    txt2
    == (
        'refused: 60 m on a 20 m radius is a needle — a mountain is at most as tall as its radius; '
        'use radius 60 or height 20'
    ),
    txt2,
)

# a valley is a HOLLOW now, not a plinth. On its OWN ground: the peaks above have
# piled 100 m of land over half the field, and a hollow can only be measured
# against the land it is actually cut into.
_t, dv3 = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'GR200'})
VB = A.block_bounds('D10', 'AX70')
VCX, VCZ = (VB[0] + VB[2]) / 2, (VB[1] + VB[3]) / 2
V_BASE = gh(dv3, GR, VCX, VCZ)
txt2, dv3 = assistant(
    'add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 18, 'direction': 'z', 'floor_width': 25}, drawing=dv3
)
cut = dv3.objs[-1]
check(
    'add_valley on a ground draws a sculpt_cut: 61 along, 47 across, 18 deep, 25 m floor, V',
    cut['kind'] == 'sculpt_cut'
    and cut['p']['len'] == 61
    and cut['p']['w'] == 47
    and cut['p']['depth'] == 18
    and cut['p']['floor_w'] == 25
    and cut['p']['profile'] == 0,
    (txt2, cut['p']),
)
V_FLOOR = gh(dv3, GR, VCX, VCZ)
check(
    'the ground under the floor DROPPED by exactly 18 m: %.4f -> %.4f' % (V_BASE, V_FLOOR),
    abs(V_FLOOR - (V_BASE - 18)) < 1e-9,
    (V_BASE, V_FLOOR),
)
check(
    'a hollow is a hollow, not a plinth: the floor is below sea level AND 10 m under the land beside it',
    V_FLOOR < -17 and V_FLOOR < gh(dv3, GR, VCX + 40, VCZ) - 10,
    (V_FLOOR, gh(dv3, GR, VCX + 40, VCZ)),
)
check(
    'arch_assistant.ground_height no longer floors at the y=0 base plane: in a deep hollow it '
    'reads the same negative H as ground_v3.height_at',
    abs(A.ground_height(dv3, VCX, VCZ) - V_FLOOR) < 1e-6 and A.ground_height(dv3, VCX, VCZ) < -17,
    (A.ground_height(dv3, VCX, VCZ), V_FLOOR),
)
_t, dl3 = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'GR200'})
txt3, dl3 = assistant(
    'add_valley',
    {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 4, 'direction': 'z', 'floor_width': 25, 'base_height': 30},
    drawing=dl3,
)
lifted = dl3.objs[-1]
check(
    'a cut lifted by base_height 30 leaves 26 m of ground the seam CAN read',
    lifted['y'] == 30.0
    and abs(A.ground_height(dl3, VCX, VCZ) - gh(dl3, GR, VCX, VCZ)) < 1e-6
    and A.ground_height(dl3, VCX, VCZ) > 25.0,
    (lifted['y'], A.ground_height(dl3, VCX, VCZ)),
)
check(
    'the reply calls it a cut into the land and still sends the model to a river',
    SCULPT_WORDS in txt2 and 'DOWN into the land' in txt2 and 'river' in txt2,
    txt2,
)
check(
    'sculpt_cut runs along its LOCAL +X, so the quarter turn is the OTHER way round '
    "from the solid valley: 'z' turns it, 'x' does not",
    abs(cut['ry'] - math.pi / 2) < 1e-5 and cut['p']['len'] == 61,
    (cut['ry'], cut['p']['len']),
)
txt2, dv3 = assistant(
    'add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'direction': 'x', 'profile': 'u'}, drawing=dv3
)
cx2 = dv3.objs[-1]
check(
    "...direction 'x' runs it the other way, unturned, 47 m of trough, profile u = 1",
    cx2['ry'] == 0.0 and cx2['p']['profile'] == 1 and cx2['p']['len'] == 47 and cx2['p']['w'] == 61,
    (cx2['ry'], cx2['p']),
)
txt2, dv3 = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 40}, drawing=dv3)
check('R7 still refuses a canyon on a v3 ground', txt2.startswith('refused') and '0.4' in txt2 and '18.8' in txt2, txt2)

# a range is a CHAIN OF SUMMITS, not one range solid
n_before = kinds_of(d3).get('sculpt_peak', 0)
txt2, d3 = assistant(
    'add_mountain_range', {'cell_from': 'A150', 'cell_to': 'CV190', 'height': 16, 'peaks': 4}, drawing=d3
)
sums = [o for o in d3.objs if o['kind'] == 'sculpt_peak'][-4:]
check(
    'add_mountain_range on a ground draws 4 sculpt_peaks and NO mountain_range solid',
    kinds_of(d3).get('sculpt_peak', 0) - n_before == 4 and kinds_of(d3).get('mountain_range') is None,
    (txt2, kinds_of(d3)),
)
check(
    'the summits are spaced len/peaks = 25 m along the block, all on peak_radius(100, 4)',
    all(abs(s['p']['r'] - peak_radius(100, 4)) < 1e-9 for s in sums)
    and all(abs(abs(sums[i + 1]['x'] - sums[i]['x']) - 25) < 1e-6 for i in range(3)),
    [(s['x'], s['p']['r']) for s in sums],
)
hs = [s['p']['h'] for s in sums]
check(
    'heights vary +-%d %% by hash and the TALLEST is exactly the height asked for' % (RANGE_SPREAD * 50),
    abs(max(hs) - 16) < 1e-9 and len(set(hs)) == 4 and min(hs) > 16 * (1 - RANGE_SPREAD),
    hs,
)
check(
    'every summit really rises its OWN declared height out of the bare land',
    all(abs(gh(d3, GR, s['x'], s['z']) - bare_at(s['x'], s['z']) - s['p']['h']) < 0.6 for s in sums),
    [(round(gh(d3, GR, s['x'], s['z']) - bare_at(s['x'], s['z']), 3), s['p']['h']) for s in sums],
)
check('range summits sit at y=0 too', all(s['y'] == 0.0 for s in sums), [s['y'] for s in sums])
check(
    'the range reply is sculpted and hands snow to the ground',
    SCULPT_WORDS in txt2 and "snow follows the ground's snow height (60 m)" in txt2,
    txt2,
)
txt2, d3 = assistant('add_mountain_range', {'cell_from': 'A1', 'cell_to': 'T10', 'height': 50, 'peaks': 4}, drawing=d3)
check('R7 needles are still refused for a range on a v3 ground', txt2.startswith('refused') and 'needles' in txt2, txt2)

# a ridge is one sculpt_ridge per consecutive pair
r_before = kinds_of(d3).get('sculpt_ridge', 0)
txt2, d3 = assistant('add_ridge', {'cells': ['E20', 'K20', 'K34'], 'height': 15}, drawing=d3)
crests = [o for o in d3.objs if o['kind'] == 'sculpt_ridge']
check(
    '3 cells give 2 sculpt_ridges and no solid ridge',
    kinds_of(d3).get('sculpt_ridge', 0) - r_before == 2 and kinds_of(d3).get('ridge') is None,
    (txt2, kinds_of(d3)),
)
check(
    '...6 m and 14 m of crest, 15 m out of the land, each feathered over 0.2 x half its length',
    crests[0]['p']['len'] == 6
    and crests[1]['p']['len'] == 14
    and crests[0]['p']['h'] == 15
    and crests[0]['p']['feather'] == 0.6
    and crests[1]['p']['feather'] == 1.4,
    [c['p'] for c in crests],
)
check(
    'crests sit at y=0 and the reply is sculpted',
    all(c['y'] == 0.0 for c in crests) and SCULPT_WORDS in txt2,
    (txt2, [c['y'] for c in crests]),
)

# and with NO ground, nothing at all has changed
dsolid = A.Drawing({'objects': []})
tS, dsolid = assistant('add_mountain', {'centre': 'K20', 'radius': 40, 'height': 30}, drawing=dsolid)
check(
    'no ground: add_mountain is the old solid `mountain` again, and says so',
    dsolid.objs[-1]['kind'] == 'mountain' and SOLID_WORDS in tS and SCULPT_WORDS not in tS,
    (tS, dsolid.objs[-1]['kind']),
)
tS, dsolid = assistant('add_valley', {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 18}, drawing=dsolid)
tR, dsolid = assistant('add_ridge', {'cells': ['E20', 'K20', 'K34'], 'height': 15}, drawing=dsolid)
tG, dsolid = assistant(
    'add_mountain_range', {'cell_from': 'A150', 'cell_to': 'CV190', 'height': 16, 'peaks': 4}, drawing=dsolid
)
check(
    'no ground: valley, ridge and range are the old solids, all saying `%s`' % SOLID_WORDS,
    kinds_of(dsolid).get('valley') == 1
    and kinds_of(dsolid).get('ridge') == 2
    and kinds_of(dsolid).get('mountain_range') == 1
    and all(SOLID_WORDS in t for t in (tS, tR, tG)),
    (kinds_of(dsolid), tS, tR, tG),
)
check(
    'no ground: no sculpt of any kind leaked into the old path',
    not any(o['kind'].startswith('sculpt_') for o in dsolid.objs),
    kinds_of(dsolid),
)
check(
    'the PROMPT names both modes in one sentence',
    'TWO MODES' in PROMPT
    and 'make_ground' in PROMPT
    and 'sculpted into that one heightfield' in PROMPT
    and 'without a ground they are drawn as solids' in PROMPT,
    PROMPT[-320:],
)

# the tab draws that sum
print('v3 tab')
PY_BARE = g3relief(GR['p'], [])
PY_PEAK = g3relief(GR['p'], [g3rec('sculpt_peak', dict(pk['p']), pk['x'] - GR['x'], pk['z'] - GR['z'])])
b3 = browser_kinds(
    [
        {'kind': 'ground', 'p': dict(GR['p'])},
        {
            'kind': 'ground',
            'p': dict(GR['p']),
            'others': [{'kind': 'sculpt_peak', 'p': dict(pk['p']), 'x': pk['x'] - GR['x'], 'z': pk['z'] - GR['z']}],
        },
    ]
)
check(
    'tab: no page errors and both grounds build',
    not any(x.get('page_errors') for x in b3) and all(x['ok'] and x['registered'] for x in b3),
    b3,
)
check(
    'tab: the bare ground is only the %.2f m base roll' % PY_BARE,
    near(b3[0]['size'][1], PY_BARE, 1.5),
    (b3[0]['size'][1], PY_BARE),
)
check(
    "tab: add_mountain's own sculpt grows the ground's bbox by ~30 m (%.3f -> %.3f)"
    % (b3[0]['size'][1], b3[1]['size'][1]),
    b3[1]['size'][1] - b3[0]['size'][1] > 28.0 and b3[1]['size'][1] - b3[0]['size'][1] < 32.0,
    (b3[0]['size'][1], b3[1]['size'][1]),
)
check(
    'tab: and that mesh is the Python lattice to 1.5 %% (%.3f vs %.3f) — three engines, one sum'
    % (b3[1]['size'][1], PY_PEAK),
    near(b3[1]['size'][1], PY_PEAK, 1.5),
    (b3[1]['size'][1], PY_PEAK),
)
check(
    'tab: the sculpted ground is still ONE vertex-coloured mesh, w x d in plan',
    b3[1]['parts'] == 1 and b3[1]['vcolors'] is True and near(b3[1]['size'][0], 200) and near(b3[1]['size'][2], 200),
    b3[1],
)
finish()
