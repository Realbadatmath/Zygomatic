# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_buildings_on_ground.py — buildings stand ON the ground (2026-09-07).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_buildings_on_ground.py

Storey 0 used to be y = 0 for every drawing tool, so a box on a hillside floated
over the valley and sank into the hill. It is now the GROUND under the middle of
the footprint, and when that ground is more than LEVEL_TOL out of level the tool
levels it first — one `sculpt_flat` (the v3 void record that pulls the single
heightfield toward `level`, feathered to nothing across the batter) plus one
visible `pad`, exactly what flatten_pad lays — and says so in its reply.

Proves, in Python only (no tab, no Blender — this is the assistant seam):
  · FLAT GROUND IS BYTE-IDENTICAL: every old number, no pad, no `base` key.
  · ON A PEAK: the pad appears, the walls sit on it, the ground under the box is
    level, the ground outside the feather is the untouched hill.
  · storey_index counts from the record's own base, so add_windows, listing and
    summary still say storey 0 for the ground floor of a building at 5.4 m.
  · base_height overrules the ground and never levels anything.

The peak here is a terrain-family `hill` record, not a v3 `sculpt_peak`: the v3
`ground` family (tree B task 1) was not on disk when this was written. The seam
is the same one either way — arch_assistant.ground_height over EXT_HEIGHTS.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402


def newdoc():
    return A.Drawing({'objects': []})


def kinds(d):
    out = {}
    for o in d.objs:
        out[o['kind']] = out.get(o['kind'], 0) + 1
    return out


def walls(d, grp=None):
    return [o for o in d.objs if o['kind'] == 'wall' and (grp is None or o['grp'] == grp)]


def lattice(d, cx, cz, w, dd, n=5):
    return [
        A.ground_height(d, cx - w / 2 + (i + 0.5) * w / n, cz - dd / 2 + (j + 0.5) * dd / n)
        for j in range(n)
        for i in range(n)
    ]


H = A.STOREY_M  # 2.7

# ── 1. flat ground: nothing at all changed ──────────────────────────────────
print('flat ground (the old numbers)')
d = newdoc()
check('an empty drawing has no ground', A.has_ground(d) is False)
txt = A.call_tool(d, 'draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'gable'})
check(
    'flat: draw_box drew 12 walls, 3 slabs, 1 roof and nothing else',
    kinds(d) == {'wall': 12, 'slab': 3, 'roof_gable': 1},
    kinds(d),
)
check('flat: no pad and no sculpt_flat were laid', 'pad' not in kinds(d) and 'sculpt_flat' not in kinds(d), kinds(d))
check('flat: the reply says nothing about levelling', 'levelled' not in txt, txt[:90])
ys = sorted({round(o['y'], 6) for o in walls(d)})
check('flat: wall storeys are exactly 0, 2.7, 5.4', ys == [0.0, round(H, 6), round(2 * H, 6)], ys)
check(
    'flat: no record carries a `base` key',
    all('base' not in o['p'] for o in d.objs),
    [o['p'] for o in d.objs if 'base' in o['p']][:2],
)
check(
    'flat: the gable roof still sits at 3 x 2.7 = 8.1 m',
    abs([o for o in d.objs if o['kind'] == 'roof_gable'][0]['y'] - 3 * H) < 1e-9,
)
check(
    'flat: storey_index equals the old storey_of for every record',
    all(A.storey_index(d, o) == A.storey_of(o['y'], H) for o in d.objs),
)
check('flat: summary still reads storeys 0..3', 'storeys 0..3' in d.summary(), d.summary())
check(
    'flat: listing still labels the top walls st2',
    d.listing([walls(d)[-1]['id']]).split()[3] == 'st2',
    d.listing([walls(d)[-1]['id']]),
)
nw = A.call_tool(d, 'add_windows', {'walls': 'new', 'per_wall': 2})
check('flat: add_windows put 2 windows on each of the 12 walls', kinds(d).get('window') == 24, nw)
A.call_tool(d, 'add_slab', {'cell_from': 'C4', 'cell_to': 'L13', 'storey': 2})
check('flat: add_slab storey 2 -> y 5.4', abs(d.objs[-1]['y'] - 2 * H) < 1e-9, d.objs[-1]['y'])
A.call_tool(d, 'add_roof', {'cell_from': 'C4', 'cell_to': 'L13', 'storey': 4, 'kind': 'flat'})
check('flat: add_roof storey 4 -> y 10.8', abs(d.objs[-1]['y'] - 4 * H) < 1e-9, d.objs[-1]['y'])
A.call_tool(d, 'add_object', {'kind': 'tree', 'cell': 'C4'})
check('flat: add_object tree -> y 0, no base key', d.objs[-1]['y'] == 0.0 and 'base' not in d.objs[-1]['p'], d.objs[-1])
A.call_tool(d, 'draw_wall', {'cell_from': 'P4', 'cell_to': 'P9', 'storeys': 2})
check(
    'flat: draw_wall storeys 0 and 1 -> y 0 and 2.7',
    abs(d.objs[-2]['y']) < 1e-9 and abs(d.objs[-1]['y'] - H) < 1e-9,
    (d.objs[-2]['y'], d.objs[-1]['y']),
)

# ── 2. a box on the flank of a peak ─────────────────────────────────────────
print('a box on the flank of a peak')
g = newdoc()
A.call_tool(g, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
hx, hz = g.objs[-1]['x'], g.objs[-1]['z']
check('the ground has a peak: 12 m at the summit', abs(A.ground_height(g, hx, hz) - 12) < 1e-9)
check('has_ground now sees ground', A.has_ground(g) is True)
c0, c1 = A.cell_of(hx + 8, hz - 2), A.cell_of(hx + 13, hz + 3)
xmin, zmin, xmax, zmax = A.block_bounds(c0, c1)
bcx, bcz = (xmin + xmax) / 2, (zmin + zmax) / 2
W, D = xmax - xmin, zmax - zmin
lvl0, off0 = A.footprint_level(g, bcx, bcz, W, D)
check('the flank under that footprint is more than LEVEL_TOL out of level', off0 > A.LEVEL_TOL, (lvl0, off0))
txt = A.call_tool(g, 'draw_box', {'cell_from': c0, 'cell_to': c1, 'storeys': 2, 'roof': 'gable'})
check(
    'the reply says it levelled the ground first, with the height',
    txt.startswith('levelled the ground at %.1f m first' % lvl0),
    txt[:70],
)
check(
    'exactly one sculpt_flat and one pad were added',
    kinds(g).get('sculpt_flat') == 1 and kinds(g).get('pad') == 1,
    kinds(g),
)
sf = [o for o in g.objs if o['kind'] == 'sculpt_flat'][0]
pad = [o for o in g.objs if o['kind'] == 'pad'][0]
check(
    'sculpt_flat carries w, d, level, feather and nothing else',
    sorted(sf['p']) == ['d', 'feather', 'level', 'w'],
    sf['p'],
)
check(
    'its level is the MEAN ground height under the footprint',
    abs(sf['p']['level'] - lvl0) < 1e-4,
    (sf['p']['level'], lvl0),
)
check(
    'its feather is 20 % of the short side (min 0.5 m)',
    abs(sf['p']['feather'] - max(0.5, 0.2 * min(W, D))) < 1e-3,
    sf['p']['feather'],
)
check(
    'the flat part covers the whole footprint: w = W + 2 x feather',
    abs(sf['p']['w'] - (W + 2 * sf['p']['feather'])) < 1e-4 and abs(sf['p']['d'] - (D + 2 * sf['p']['feather'])) < 1e-4,
    sf['p'],
)
check(
    'the visible pad is exactly the footprint, at the level',
    abs(pad['p']['w'] - W) < 1e-4 and abs(pad['p']['d'] - D) < 1e-4 and abs(pad['y'] - sf['p']['level']) < 1e-9,
    (pad['p'], pad['y']),
)
lv = sf['p']['level']
b = [o for o in g.objs if o['grp'].startswith('box ')]
st0 = [o for o in b if abs(o['y'] - lv) < 1e-6]
check(
    'all four storey-0 walls and its slab sit at the pad level, not at 0',
    len([o for o in st0 if o['kind'] == 'wall']) == 4 and len([o for o in st0 if o['kind'] == 'slab']) == 1,
    sorted({round(o['y'], 4) for o in b}),
)
check(
    'storey 1 sits at the pad level + 2.7',
    len([o for o in b if abs(o['y'] - (lv + H)) < 1e-6 and o['kind'] == 'wall']) == 4,
    sorted({round(o['y'], 4) for o in b}),
)
check(
    'the gable roof sits at the pad level + 2 x 2.7',
    abs([o for o in b if o['kind'] == 'roof_gable'][0]['y'] - (lv + 2 * H)) < 1e-6,
)
samples = lattice(g, bcx, bcz, W, D, 5)
check(
    'the ground under the box is level within 0.05 m', max(samples) - min(samples) < 0.05, (min(samples), max(samples))
)
check('and it is level AT the pad level', abs(sum(samples) / len(samples) - lv) < 0.01, sum(samples) / len(samples))
check(
    'the corners of the footprint are on the pad too',
    all(
        abs(A.ground_height(g, bcx + sx * (W / 2 - 0.01), bcz + sz * (D / 2 - 0.01)) - lv) < 0.05
        for sx in (-1, 1)
        for sz in (-1, 1)
    ),
)
far = hx + 8 + W / 2 + sf['p']['feather'] + 3
check(
    'the hill outside the sculpt_flat is untouched',
    abs(A.ground_height(g, far, bcz) - 12 * 0.5 * (1 + math.cos(math.pi * math.hypot(far - hx, bcz - hz) / 20))) < 1e-9,
    A.ground_height(g, far, bcz),
)
mid = bcx + W / 2 + sf['p']['feather'] / 2
check(
    'the batter is a real ramp: half-way out it is between the pad and the hill',
    min(lv, A.ground_height(g, far, bcz)) - 1e-6
    < A.ground_height(g, mid, bcz)
    < max(lv, A.ground_height(g, far, bcz)) + 1e-6
    and abs(A.ground_height(g, mid, bcz) - lv) > 1e-6,
    A.ground_height(g, mid, bcz),
)
check(
    'hiding the sculpt_flat gives the hill back',
    abs(
        A.ground_height(
            A.Drawing({'objects': [dict(o, hidden=True) if o['kind'] == 'sculpt_flat' else o for o in g.objs]}),
            bcx,
            bcz,
        )
        - 12 * 0.5 * (1 + math.cos(math.pi * math.hypot(bcx - hx, bcz - hz) / 20))
    )
    < 1e-9,
)

# ── 3. storeys are counted from the building's own base ─────────────────────
print('storey_index')
check(
    'every storey-0 wall carries base = the pad level',
    all(abs(o['p']['base'] - lv) < 1e-9 for o in st0),
    [o['p'] for o in st0][:1],
)
check(
    'storey_index says 0 for them, not 2',
    all(A.storey_index(g, o) == 0 for o in st0),
    [A.storey_index(g, o) for o in st0],
)
check(
    'the old storey_of would have said 2 (this is the bug being fixed)',
    A.storey_of(st0[0]['y'], H) == round(lv / H),
    A.storey_of(st0[0]['y'], H),
)
check(
    'storey_index says 1 for the storey above',
    all(A.storey_index(g, o) == 1 for o in b if abs(o['y'] - (lv + H)) < 1e-6),
)
check(
    'a ground record keeps its raw storey (it IS the ground)',
    A.storey_index(g, [o for o in g.objs if o['kind'] == 'hill'][0]) == 0,
)
check(
    'listing labels the ground floor st0',
    ' st0 ' in d.listing([st0[0]['id']]) or g.listing([st0[0]['id']]).split()[3] == 'st0',
    g.listing([st0[0]['id']]),
)
check('summary reads storeys 0..2 on the hill, not 2..4', 'storeys 0..2' in g.summary(), g.summary())
nw = A.call_tool(g, 'add_windows', {'walls': 'new', 'per_wall': 2})
check('add_windows works on the levelled box: 2 x 8 walls', kinds(g).get('window') == 16, nw)
check(
    'the windows are at the walls own y, and carry the same base',
    all(abs(o['p']['base'] - lv) < 1e-9 for o in g.objs if o['kind'] == 'window'),
)
g2 = A.Drawing(g.to_doc())
nw = A.call_tool(
    g2, 'add_windows', {'walls': [o['id'] for o in b if o['kind'] == 'wall'], 'every_n_storeys': 2, 'per_wall': 1}
)
check(
    'every_n_storeys=2 counts from the buildings base: only the 4 ground-floor walls',
    kinds(g2).get('window') == 16 + 4,
    nw,
)

# ── 4. base_height overrules the ground ─────────────────────────────────────
print('base_height')
e = newdoc()
A.call_tool(e, 'draw_box', {'cell_from': 'C4', 'cell_to': 'F7', 'storeys': 2, 'base_height': 3})
check(
    'base_height 3 on flat ground: storey 0 at y 3',
    all(abs(o['y'] - 3.0) < 1e-9 for o in walls(e)[:4]),
    sorted({o['y'] for o in walls(e)}),
)
check('base_height did NOT lay a pad', 'pad' not in kinds(e) and 'sculpt_flat' not in kinds(e), kinds(e))
check('the walls carry base = 3', all(o['p']['base'] == 3.0 for o in walls(e)))
check(
    'storey_index reads 0 and 1 from y - base',
    sorted({A.storey_index(e, o) for o in walls(e)}) == [0, 1],
    sorted({A.storey_index(e, o) for o in walls(e)}),
)
nw = A.call_tool(e, 'add_windows', {'walls': 'new', 'per_wall': 1, 'every_n_storeys': 2})
check(
    'add_windows every_n_storeys=2 on a base_height box hits its ground floor (4 windows)',
    kinds(e).get('window') == 4,
    nw,
)
e2 = newdoc()
A.call_tool(e2, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
A.call_tool(e2, 'draw_box', {'cell_from': c0, 'cell_to': c1, 'base_height': 0})
check(
    'base_height 0 pins a box to the base plane through a hill, and levels nothing',
    all(o['y'] == 0.0 for o in walls(e2)) and 'pad' not in kinds(e2),
    kinds(e2),
)
check('base_height 0 leaves no base key behind either', all('base' not in o['p'] for o in walls(e2)))

# ── 5. a planar hillside, the other tools, and the props that must NOT level ─
print('slopes, walls, objects')
s = newdoc()
A.call_tool(s, 'add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'})
sx, sz = s.objs[-1]['x'], s.objs[-1]['z']
y0, glx, glz, spread = A.ground_plane(s, sx, sz, 6, 6, 0.0)
lvl, off = A.footprint_level(s, sx, sz, 6, 6)
check(
    'a planar hillside: ground_plane spread is 0 but footprint_level says 1.08 m out of level',
    spread < 1e-6 and abs(off - 1.08) < 1e-6,
    (spread, off),
)
A.call_tool(s, 'draw_box', {'cell_from': A.cell_of(sx - 3, sz - 3), 'cell_to': A.cell_of(sx + 2, sz + 2), 'storeys': 1})
check('draw_box levels a planar hillside too (a tilted plane is not level)', kinds(s).get('sculpt_flat') == 1, kinds(s))
lat = lattice(s, sx, sz, 6, 6, 5)
check('the ground under it is level within 0.05', max(lat) - min(lat) < 0.05, (min(lat), max(lat)))
w0 = walls(s)[0]
check('the walls sit on that level', abs(w0['y'] - lvl) < 0.05, (w0['y'], lvl))
s2 = newdoc()
A.call_tool(s2, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
txt = A.call_tool(
    s2, 'draw_wall', {'cell_from': A.cell_of(hx + 6, hz), 'cell_to': A.cell_of(hx + 16, hz), 'storeys': 1}
)
wl = [o for o in s2.objs if o['kind'] == 'wall'][0]
check(
    'draw_wall on the flank levels its own strip and stands on it',
    'levelled the ground at' in txt and abs(wl['y'] - wl['p']['base']) < 1e-9 and wl['y'] > 1.0,
    (txt[:50], wl['y']),
)
s3 = newdoc()
A.call_tool(s3, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
A.call_tool(s3, 'add_object', {'kind': 'tree', 'cell': A.cell_of(hx + 10, hz)})
tr = s3.objs[-1]
check(
    'a tree on the flank stands ON the ground and levels nothing (its footprint is 4 m)',
    abs(tr['y'] - A.ground_height(s3, tr['x'], tr['z'])) < 1e-4 and 'sculpt_flat' not in kinds(s3),
    (tr['y'], kinds(s3)),
)
check('and it carries that ground as its base', abs(tr['p']['base'] - tr['y']) < 1e-9, tr['p'])
A.call_tool(s3, 'add_object', {'kind': 'terrain', 'cell': 'C4', 'params': {'w': 40, 'd': 40, 'amp': 3}})
tn = s3.objs[-1]
check(
    'a GROUND kind added through add_object keeps the old base plane and its own `base` param',
    tn['y'] == 0.0 and tn['p']['base'] == 0,
    (tn['y'], tn['p'].get('base')),
)
check(
    'pad_level is idempotent: a point already at the level does not move',
    abs(A.pad_level(g, bcx, bcz, lv) - lv) < 1e-12,
)
check(
    'pad_level cuts as well as fills: a point below the level is lifted to it',
    abs(A.pad_level(g, bcx, bcz, lv - 5.0) - lv) < 1e-9,
)

# ── 6. the ground, and the water lying on it, never level THEMSELVES ────────
# A sculpt IS the one heightfield's parameters, so a sculpt_flat + pad laid
# under a sculpt_peak would flatten the very mountain it carves. A water surface
# takes the bed's height but must not pad it either. Everything else — including
# the elliptical plans that _p_footprint used to read as a zero footprint — does
# stand on levelled ground.
print('sculpts, water and elliptical plans')
SCULPTS = (
    'sculpt_peak',
    'sculpt_ridge',
    'sculpt_mesa',
    'sculpt_cut',
    'sculpt_channel',
    'sculpt_basin',
    'sculpt_flat',
    'sculpt_step',
    'sculpt_dunes',
    'sculpt_shelf',
)
check('is_sculpt knows all 10 void ground kinds', all(A.is_sculpt(k) for k in SCULPTS))
check(
    'is_sculpt says no to the ground record, a pad and a wall',
    not any(A.is_sculpt(k) for k in ('ground', 'pad', 'wall', 'hill', None)),
)
check(
    'the water SURFACES are the three v3 ones plus the old lake and pond',
    A.WATER_SURFACES == ('water_body', 'water_path', 'water_plane', 'lake', 'pond'),
)
check(
    'a water_tower is NOT a water surface — it is a building on the ground',
    'water_tower' not in A.WATER_SURFACES and 'waterfall' not in A.WATER_SURFACES,
)

check('_p_footprint reads an elliptical plan from rx/rz', A._p_footprint({'rx': 60, 'rz': 45}) == (120.0, 90.0))
check('_p_footprint still reads w/d first', A._p_footprint({'w': 8, 'd': 5, 'rx': 60, 'rz': 45}) == (8.0, 5.0))
check(
    '_p_footprint still reads len and r',
    A._p_footprint({'len': 9, 't': 0.3}) == (9.0, 0.3) and A._p_footprint({'r': 120}) == (240.0, 240.0),
)

flank = A.cell_of(hx + 8, hz)
v = newdoc()
A.call_tool(v, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
gh_flank = A.ground_height(v, *A.cell_centre(*A.parse_cell(flank)))
check('the flank of the hill is 7.85 m up', abs(gh_flank - 7.8541) < 1e-3, gh_flank)

sp = newdoc()
A.call_tool(sp, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
n0 = len(sp.objs)
A.call_tool(sp, 'add_object', {'kind': 'sculpt_peak', 'cell': flank, 'params': {'r': 120, 'h': 80}})
pk = sp.objs[-1]
check(
    'a sculpt through add_object adds ONE record — no sculpt_flat, no pad',
    len(sp.objs) - n0 == 1 and 'pad' not in kinds(sp) and 'sculpt_flat' not in kinds(sp),
    kinds(sp),
)
check(
    'and its 240 m footprint WOULD have levelled, had it been a building',
    A._p_footprint(pk['p'])[0] == 240.0 and A.footprint_level(sp, pk['x'], pk['z'], 240, 240)[1] > A.LEVEL_TOL,
)
check('the sculpt keeps the base plane', pk['y'] == 0.0, pk['y'])
check('and carries no `base` key (it is the ground, not a thing on it)', 'base' not in pk['p'], pk['p'])
A.call_tool(sp, 'add_object', {'kind': 'sculpt_cut', 'cell': flank, 'params': {'len': 200, 'w': 60, 'depth': 20}})
check(
    'a second sculpt on the first one is just as flat-footed',
    kinds(sp).get('sculpt_cut') == 1 and 'pad' not in kinds(sp),
    kinds(sp),
)
check(
    'a sculpt is on no storey at all, whatever its y',
    A.storey_index(sp, pk) == 0 and A.storey_index(sp, {'kind': 'sculpt_flat', 'y': 59.4, 'p': {}}) == 0,
)
check('listing labels a sculpt st0', ' st0 ' in sp.listing('sculpt_peak'), sp.listing('sculpt_peak'))

for kind, params in (('lake', {'rx': 40, 'rz': 25, 'depth': 4}), ('water_body', {'rx': 30, 'rz': 20})):
    wdoc = newdoc()
    A.call_tool(wdoc, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
    n0 = len(wdoc.objs)
    A.call_tool(wdoc, 'add_object', {'kind': kind, 'cell': flank, 'params': params})
    wo = wdoc.objs[-1]
    check(
        f'a {kind} lies ON the bed and lays no pad under itself',
        len(wdoc.objs) - n0 == 1 and 'pad' not in kinds(wdoc) and 'sculpt_flat' not in kinds(wdoc),
        kinds(wdoc),
    )
    check(
        f'the {kind} sits at the ground height, not at 0',
        abs(wo['y'] - gh_flank) < 1e-4 and abs(wo['p']['base'] - wo['y']) < 1e-9,
        (wo['y'], gh_flank),
    )

for kind, params, w_m in (('stadium_ring', {'rx': 60, 'rz': 45}, 120.0), ('mass_ellipse', None, 12.0)):
    edoc = newdoc()
    A.call_tool(edoc, 'add_hill', {'centre': 'P30', 'radius': 20, 'height': 12})
    txt = A.call_tool(edoc, 'add_object', {'kind': kind, 'cell': flank, 'params': params or {}})
    eo = edoc.objs[-1]
    padr = [o for o in edoc.objs if o['kind'] == 'pad'][0]
    check(
        f'an elliptical {kind} on the flank levels its own footprint first',
        kinds(edoc).get('sculpt_flat') == 1 and 'levelled the ground at' in txt,
        (kinds(edoc), txt[:40]),
    )
    check(
        f'the {kind} pad is {w_m:g} m across — the rx/rz plan, not a zero footprint',
        abs(padr['p']['w'] - w_m) < 1e-6,
        padr['p'],
    )
    check(
        f'the {kind} stands on that pad, and storey_index still reads 0',
        abs(eo['y'] - padr['y']) < 1e-9 and A.storey_index(edoc, eo) == 0,
        (eo['y'], padr['y']),
    )
    lat = lattice(edoc, eo['x'], eo['z'], w_m, w_m * 0.75, 5)
    check(f'the ground under the {kind} is level within 0.05', max(lat) - min(lat) < 0.05, (min(lat), max(lat)))

f = newdoc()
for kind, params in (
    ('sculpt_peak', {'r': 40, 'h': 9}),
    ('lake', {'rx': 20, 'rz': 12}),
    ('stadium_ring', {'rx': 60, 'rz': 45}),
):
    A.call_tool(f, 'add_object', {'kind': kind, 'cell': 'M15', 'params': params})
check(
    'on FLAT ground none of them levelled anything or grew a base key',
    'pad' not in kinds(f)
    and 'sculpt_flat' not in kinds(f)
    and all('base' not in o['p'] for o in f.objs)
    and all(o['y'] == 0.0 for o in f.objs),
    kinds(f),
)

finish()
