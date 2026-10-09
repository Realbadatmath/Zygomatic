# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_coast_dunes.py — the coast_dunes family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_coast_dunes.py

Three engines have to agree about the same five kinds. Three of them are
noise-driven, so the test evaluates the Python copies of the arithmetic and
asserts the tab's bounding box matches:

  sea_span()    the wave crest over the bed — the sea's height
  dune_scale()  the factor that puts the tallest dune crest exactly on h
  island_span() the outer edge of the wandering shoreline plus its beach ring

If a copy of the noise ever drifts, the coast silently changes shape in one
engine only; these three numbers are what catches it.

GROUND (2026-09-07). The family also exports HEIGHTS, so the last section asks
the fourth question: does the height field the assistant places things on
actually agree with the geometry the tab draws? `fn_max` walks the SAME lattice
the two builders walk and the answer has to be the tab's bounding box, to
within 1.5 %. The sea is the deliberate exception — water is not ground.
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
from zyg_workflows.arch_assistant_ext.coast_dunes import (
    sea_span,
    dune_scale,
    island_span,
    PROMPT,
    KINDS,
    HEIGHTS,
    BX,
    BZ,
    WET_ROWS,
    MARRAM,
    DUNE_H,
    BEACH_H,
    ISLAND_H,
    BREAKWATER_H,
    h_beach,
    h_breakwater,
    the_ground,
    water_level_of,
    BEACH_RISE,
    BEACH_FEATHER,
    _water_tool,
)

NEW_KINDS = ['sea', 'beach', 'dune_field', 'island', 'breakwater']
GROUND_KINDS = ['beach', 'dune_field', 'island', 'breakwater']


def fn_max(kind, p, W, D, nx, nz):
    """The top of a kind's height field, sampled on the (nx+1) x (nz+1) lattice
    its two geometry builders walk — so this is the number the tab's bounding
    box has to report."""
    fn = A.EXT_HEIGHTS[kind]
    best = 0.0
    for j in range(nz + 1):
        for i in range(nx + 1):
            v = fn(p, -W / 2 + i / nx * W, -D / 2 + j / nz * D)
            if v is not None and v > best:
                best = v
    return best


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('add_sea', 'add_beach', 'add_dunes', 'add_island', 'add_breakwater', 'make_coast')),
    names,
)
check('prompt is one paragraph under 1100 chars', 0 < len(PROMPT) <= 1100 and '\n' not in PROMPT, len(PROMPT))
check(
    'prompt states the sea comes first and the sea is on the left',
    'FIRST' in PROMPT and 'LEFT' in PROMPT and 'duin' in PROMPT and '8-15' in PROMPT and 'base_height' in PROMPT,
    PROMPT[:120],
)

# add_sea: one record sized to the block
txt, d = assistant('add_sea', {'cell_from': 'C4', 'cell_to': 'BZ43', 'depth': 8, 'wave': 0.2})
s0 = d.objs[-1]
check(
    'add_sea drew one sea sized to the 76x40 block',
    kinds_of(d).get('sea') == 1
    and s0['p']['w'] == 76
    and s0['p']['d'] == 40
    and s0['p']['depth'] == 8
    and s0['p']['wave'] == 0.2,
    (txt, s0['p']),
)
check(
    'sea sits on the ground with a group and its id in the text',
    s0['y'] == 0.0 and s0['grp'] == 'coast' and s0['id'] in txt and s0['mat'] == 'mat_water',
    (s0, txt),
)
txt, d = assistant('add_sea', {'cell_from': 'C4', 'cell_to': 'BZ43', 'depth': 0}, drawing=d)
check('zero depth refused', txt.startswith('refused'), txt)
txt, d = assistant('add_sea', {'cell_from': 'C4', 'cell_to': 'BZ43', 'wave': -1}, drawing=d)
check('negative wave refused', txt.startswith('refused'), txt)
txt, d = assistant('add_sea', {'cell_from': 'A1', 'cell_to': 'ZZ9'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)
txt, d = assistant('add_sea', {'cell_from': 'C4', 'cell_to': 'F8', 'base_height': 3}, drawing=d)
check('base_height lifts the sea onto a plateau', d.objs[-1]['y'] == 3.0, (txt, d.objs[-1]['y']))

# add_beach: 3 cells -> 2 records, sea on the left of the walk
txt, d = assistant('add_beach', {'cells': ['B10', 'K10', 'K16'], 'width': 30, 'height': 2.5}, drawing=d)
beaches = [o for o in d.objs if o['kind'] == 'beach']
check('3 cells give 2 beach strips', kinds_of(d).get('beach') == 2, txt)
check(
    '...9 m and 6 m long, 30 m wide, 2.5 m tall',
    abs(beaches[0]['p']['len'] - 9) < 1e-6
    and abs(beaches[1]['p']['len'] - 6) < 1e-6
    and beaches[0]['p']['w'] == 30
    and beaches[0]['p']['h'] == 2.5,
    [b['p'] for b in beaches],
)
check(
    'walking east leaves ry 0 (the sea is then to the north, on the left)',
    abs(beaches[0]['ry']) < 1e-9 and abs(beaches[1]['ry'] + math.pi / 2) < 1e-6,
    [b['ry'] for b in beaches],
)
check('the result text says which side the sea is on', 'LEFT' in txt, txt)
txt, d = assistant('add_beach', {'cells': ['B10']}, drawing=d)
check('one cell refused', txt.startswith('refused'), txt)
txt, d = assistant('add_beach', {'cells': ['B10', 'K10'], 'height': 0}, drawing=d)
check('zero height refused', txt.startswith('refused'), txt)
txt, d = assistant('add_beach', {'cells': ['B10', 'K10'], 'width': 1}, drawing=d)
check('1 m wide beach refused', txt.startswith('refused'), txt)

# add_dunes: the ridges lie across the SHORTER side, so a deep block turns 90
txt, d = assistant('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 12}, drawing=d)
dn = d.objs[-1]
check(
    'wide block: 16 x 20 m... deeper than wide, so turned 90 deg',
    dn['kind'] == 'dune_field'
    and dn['p']['w'] == 20
    and dn['p']['d'] == 16
    and dn['p']['dir'] == 90
    and dn['p']['h'] == 12,
    (txt, dn['p']),
)
txt, d = assistant('add_dunes', {'cell_from': 'D20', 'cell_to': 'AD29', 'height': 10}, drawing=d)
dn2 = d.objs[-1]
check(
    'block wider than deep stays unturned, 27 x 10 m',
    dn2['p']['w'] == 27 and dn2['p']['d'] == 10 and dn2['p']['dir'] == 0,
    (txt, dn2['p']),
)
txt, d = assistant('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 0}, drawing=d)
check('zero dune height refused', txt.startswith('refused'), txt)
txt, d = assistant('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 140}, drawing=d)
check('140 m dunes refused', txt.startswith('refused'), txt)

# add_island
txt, d = assistant('add_island', {'centre': 'P30', 'radius': 25, 'height': 5, 'beach': 8}, drawing=d)
isl = d.objs[-1]
check(
    'add_island drew one island',
    isl['kind'] == 'island' and isl['p']['r'] == 25 and isl['p']['h'] == 5 and isl['p']['beach'] == 8,
    (txt, isl['p']),
)
txt, d = assistant('add_island', {'centre': 'P30', 'radius': 1}, drawing=d)
check('radius under 2 m refused', txt.startswith('refused'), txt)
txt, d = assistant('add_island', {'centre': 'P30', 'radius': 25, 'height': 150}, drawing=d)
check('150 m island refused', txt.startswith('refused'), txt)
txt, d = assistant('add_island', {'centre': 'P30', 'radius': 25, 'wobble': 2}, drawing=d)
check('wobble over 0.9 refused', txt.startswith('refused'), txt)

# add_breakwater
txt, d = assistant('add_breakwater', {'cells': ['H45', 'H33'], 'height': 2.5, 'width': 6}, drawing=d)
bw = d.objs[-1]
check(
    'add_breakwater drew one 12 m mound in rock',
    bw['kind'] == 'breakwater'
    and abs(bw['p']['len'] - 12) < 1e-6
    and bw['p']['h'] == 2.5
    and bw['p']['w'] == 6
    and bw['mat'] == 'mat_rock',
    (txt, bw['p']),
)
txt, d = assistant('add_breakwater', {'cells': ['H45']}, drawing=d)
check('one cell refused', txt.startswith('refused'), txt)
txt, d = assistant('add_breakwater', {'cells': ['H45', 'H33'], 'height': 0}, drawing=d)
check('zero height refused', txt.startswith('refused'), txt)

# make_coast: the recipe, on a 200 x 100 block with the sea to the north
txt, c = assistant('make_coast', {'cell_from': 'A1', 'cell_to': 'GR100', 'sea_side': 'north'})
check('make_coast laid exactly 3 records', len(c.objs) == 3, (txt, [o['kind'] for o in c.objs]))
sea, bch, dun = c.objs
check(
    '...sea, beach, dune_field in that order',
    [o['kind'] for o in c.objs] == ['sea', 'beach', 'dune_field'],
    [o['kind'] for o in c.objs],
)
check(
    '...their centres run north to south (smaller z is north)', sea['z'] < bch['z'] < dun['z'], [o['z'] for o in c.objs]
)
band_sum = sea['p']['d'] + bch['p']['w'] + dun['p']['d']
check(
    '...and their sizes sum to the 100 m block depth within 1%%: got %.1f' % band_sum,
    abs(band_sum - 100) <= 1.0,
    band_sum,
)
check(
    '...40 / 20 / 40 per cent of the block, full width',
    sea['p']['d'] == 40 and bch['p']['w'] == 20 and dun['p']['d'] == 40 and sea['p']['w'] == 200,
    [sea['p'], bch['p'], dun['p']],
)
check(
    '...all three ids are in the result text and share one group',
    all(o['id'] in txt for o in c.objs) and {o['grp'] for o in c.objs} == {'coast'},
    txt,
)
txt, c2 = assistant('make_coast', {'cell_from': 'A1', 'cell_to': 'GR100', 'sea_side': 'east', 'base_height': 4})
check(
    'sea to the east: the beach walks south so the water stays on its left',
    abs(c2.objs[1]['ry'] + math.pi / 2) < 1e-6 and c2.objs[0]['x'] > c2.objs[1]['x'] > c2.objs[2]['x'],
    [(o['kind'], o['x'], o['ry']) for o in c2.objs],
)
check('base_height reaches all three pieces', all(o['y'] == 4.0 for o in c2.objs), [o['y'] for o in c2.objs])
txt, c3 = assistant('make_coast', {'cell_from': 'A1', 'cell_to': 'GR100', 'sea_side': 'up'})
check('bad sea_side refused', txt.startswith('refused'), txt)
txt, c3 = assistant('make_coast', {'cell_from': 'A1', 'cell_to': 'GR2', 'sea_side': 'north'})
check('a 2-cell-deep block refused', txt.startswith('refused'), txt)
txt, c3 = assistant('make_coast', {'cell_from': 'A1', 'cell_to': 'GR100', 'sea_side': 'north', 'dune_height': 0})
check('zero dune_height refused', txt.startswith('refused'), txt)

# ── the ground seam ───────────────────────────────────────────────────────────
print('ground')
check(
    'the four things you can stand on are in the seam, and the sea is NOT',
    all(callable(A.EXT_HEIGHTS.get(k)) for k in GROUND_KINDS)
    and 'sea' in A.EXT_HEIGHTS
    and A.EXT_HEIGHTS['sea'] is None
    and HEIGHTS['sea'] is None,
    {k: A.EXT_HEIGHTS.get(k) for k in NEW_KINDS},
)

# a 20 x 20 m slope rising 4 m to the south: ground at its centre is 2 m
txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 4, 'direction': 'z'})
sl = g.objs[-1]
gx, gz = sl['x'], sl['z']
check(
    'the test slope reads 2 m at its centre', abs(A.ground_height(g, gx, gz) - 2.0) < 1e-9, A.ground_height(g, gx, gz)
)

# R3: water lies level
txt = assistant('add_sea', {'cell_from': 'A1', 'cell_to': 'T20', 'depth': 5}, drawing=g)[0]
check(
    'R3: a sea over 4 m of slope is refused because water lies level',
    txt.startswith('refused') and 'level' in txt and 'flatten_pad' in txt,
    txt,
)
txt = assistant('add_sea', {'cell_from': 'A40', 'cell_to': 'T60', 'depth': 5}, drawing=g)[0]
check(
    'R3: the same sea on level ground clear of the slope is allowed',
    not txt.startswith('refused') and g.objs[-1]['kind'] == 'sea' and g.objs[-1]['y'] == 0.0,
    txt,
)

# R1: the dunes land on the slope; R6: the ground then stacks on top of them
txt, g = assistant('add_dunes', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 6}, drawing=g)
dn0 = g.objs[-1]
check(
    'R1: dunes over the slope stand at y=2, the ground under their centre',
    dn0['kind'] == 'dune_field' and abs(dn0['y'] - 2.0) < 1e-9,
    (txt, dn0['y']),
)
crest = A.EXT_HEIGHTS['dune_field'](dn0['p'], 0.0, 0.0)
check(
    'R6: the ground at that point is now the slope PLUS the dune on it (%.3f m)' % (2.0 + crest),
    abs(A.ground_height(g, gx, gz) - (2.0 + crest)) < 1e-9 and crest > 0.0,
    (A.ground_height(g, gx, gz), crest),
)
y, ggx, ggz = A.ground_at(g, gx, gz)
check('...and the gradient there is a real dune face, not a flat plane', abs(ggz) > 1e-3 or abs(ggx) > 1e-3, (ggx, ggz))

# R4: a beach chain crossing the same slope tilts with rz and sits on the fall
txt, g2 = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 4, 'direction': 'z'})
txt, g2 = assistant('add_beach', {'cells': ['C2', 'C19'], 'width': 6, 'height': 2}, drawing=g2)
bo = g2.objs[-1]
check(
    'R4: a beach strip up a 1:5 fall tilts rz = atan(0.2) and centres on the mean ground',
    abs(bo['rz'] - math.atan(0.2)) < 1e-4 and abs(bo['y'] - 2.0) < 1e-4 and 'fall' in txt,
    (bo['rz'], bo['y'], txt),
)
txt, g3 = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 4, 'direction': 'z'})
txt, g3 = assistant('add_breakwater', {'cells': ['C2', 'C19'], 'height': 3, 'width': 6}, drawing=g3)
check(
    'R4: a breakwater over the same fall tilts by the same angle',
    abs(g3.objs[-1]['rz'] - math.atan(0.2)) < 1e-4,
    g3.objs[-1]['rz'],
)
txt, g4 = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'T20', 'height': 4, 'direction': 'z'})
txt, g4 = assistant('add_beach', {'cells': ['C2', 'C19'], 'width': 6, 'height': 2, 'base_height': 9}, drawing=g4)
check(
    '...base_height overrides the ground and lays the strip flat',
    g4.objs[-1]['y'] == 9.0 and g4.objs[-1]['rz'] == 0.0,
    (g4.objs[-1]['y'], g4.objs[-1]['rz']),
)

# the sea is not ground: an island dropped in one still rises from the bed
txt, w = assistant('add_sea', {'cell_from': 'A1', 'cell_to': 'BX40', 'depth': 9})
check(
    'a sea contributes nothing to the ground under it',
    A.ground_height(w, w.objs[-1]['x'], w.objs[-1]['z']) == 0.0,
    A.ground_height(w, 0, 0),
)
txt, w = assistant('add_island', {'centre': 'AK20', 'radius': 20, 'height': 7, 'beach': 5}, drawing=w)
iso = w.objs[-1]
check(
    'an island in a 9 m sea still stands at y=0 — water is not a surface',
    iso['kind'] == 'island' and iso['y'] == 0.0,
    (txt, iso['y']),
)
check(
    '...and the island IS ground: 7 m at its middle, 0 outside the sand ring',
    abs(A.ground_height(w, iso['x'], iso['z']) - 7.0) < 1e-9 and A.ground_height(w, iso['x'] + 400, iso['z']) == 0.0,
    A.ground_height(w, iso['x'], iso['z']),
)

# R7: real sizes, in metres, whatever the block
for tool, args, key, rng in (
    ('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39'}, 'height', DUNE_H),
    ('add_beach', {'cells': ['B10', 'K10']}, 'height', BEACH_H),
    ('add_island', {'centre': 'P30', 'radius': 25}, 'height', ISLAND_H),
    ('add_breakwater', {'cells': ['H45', 'H33']}, 'height', BREAKWATER_H),
):
    lo = assistant(tool, dict(args, **{key: round(rng[0] - 0.1, 3)}))[0]
    hi = assistant(tool, dict(args, **{key: round(rng[1] + 0.1, 3)}))[0]
    ok = assistant(tool, dict(args, **{key: rng[0]}))[0]
    check(
        'R7: %s takes %g-%g m and refuses either side of it' % (tool, rng[0], rng[1]),
        lo.startswith('refused') and hi.startswith('refused') and not ok.startswith('refused'),
        (lo[:80], hi[:80], ok[:60]),
    )

# the recipe's beach really is the wedge the seam reports
q = [-9.95, 0.0, 9.95]
got = [A.ground_height(c, bch['x'], bch['z'] + t) for t in q]
want = [h_beach(bch['p'], 0.0, t) for t in q]
check(
    'make_coast: the ground on the beach strip is the wedge at all three points',
    all(abs(a - b) < 1e-9 for a, b in zip(got, want)),
    (got, want),
)
check(
    '...0 at the water edge, half way up in the middle, h at the back crest: %.3f / %.3f / %.3f' % tuple(got),
    got[0] < 0.01 < got[1] < got[2] <= bch['p']['h'] + 1e-9 and abs(got[1] / got[2] - 0.5) < 0.01,
    got,
)

# the two looks, in numbers
check(
    'the wet band is exactly 15%% of the beach width (%d of %d rows)' % (WET_ROWS, BZ),
    abs(WET_ROWS / BZ - 0.15) < 1e-12 and BX == 24 and BZ == 20,
    (WET_ROWS, BX, BZ),
)
check('marram grass starts at 70% of a dune height', abs(MARRAM - 0.70) < 1e-12, MARRAM)
check(
    'the breakwater crest is flat at h and its flank falls away by half at half the batter',
    abs(h_breakwater({'len': 60, 'w': 8, 'h': 3}, 0, 0) - 3) < 1e-9
    and abs(h_breakwater({'len': 60, 'w': 8, 'h': 3}, 0, 8 / 6) - 3) < 1e-9
    and abs(h_breakwater({'len': 60, 'w': 8, 'h': 3}, 0, (8 / 6 + 4) / 2) - 1.5) < 1e-9
    and h_breakwater({'len': 60, 'w': 8, 'h': 3}, 0, 4.1) is None,
    [h_breakwater({'len': 60, 'w': 8, 'h': 3}, 0, t) for t in (0, 8 / 6, 2.667, 4.1)],
)

# add_object must accept the new kinds (they are in KINDS)
txt, d = assistant('add_object', {'kind': 'breakwater', 'cell': 'A1', 'params': {'len': 40, 'w': 6, 'h': 2}}, drawing=d)
check('add_object knows breakwater', d.objs[-1]['kind'] == 'breakwater' and d.objs[-1]['p']['len'] == 40, txt)
txt, d = assistant('add_object', {'kind': 'island', 'cell': 'A1', 'params': {'r': 20, 'h': 4}}, drawing=d)
check('add_object knows island', d.objs[-1]['kind'] == 'island' and d.objs[-1]['p']['r'] == 20, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all five', sorted(KINDS) == sorted(NEW_KINDS), sorted(KINDS))

# ── the v3 sculpted ground ────────────────────────────────────────────────────
# With a `ground` record the coast IS the land: the sea is dished out of it by
# water_v3, the dunes are one sculpt, the beach is a flat pad plus a depth-0
# shelf that only paints sand, and the island is a low peak with the same mask.
# The breakwater is the exception — a rubble mound is an object, not a landform.
print('sculpted ground (v3)')


def sculpt_ground(*calls):
    """A fresh drawing with a ground, then the calls, then (text, drawing)."""
    txt, dd = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'GR100', 'style': 'rolling'})
    for tool, args in calls:
        txt, dd = assistant(tool, args, drawing=dd)
    return txt, dd


def bare_ground(dd):
    """The same drawing with the ground alone — the land before the sculpts."""
    return A.Drawing({'objects': [o for o in dd.objs if o['kind'] == 'ground']})


txt, v = sculpt_ground()
check(
    'v3: make_ground laid the one ground the coast is cut from',
    v.objs[-1]['kind'] == 'ground' and the_ground(v) is v.objs[-1],
    (txt, v.objs[-1]['kind']),
)
check(
    'v3: water_v3 is reachable at CALL time (EXT_MODULES loads alphabetically, so not at import)',
    _water_tool('t_fill_sea') is not None,
    sorted(A.EXT_MODULES),
)

txt, vs = sculpt_ground(('add_sea', {'cell_from': 'A1', 'cell_to': 'GR40', 'depth': 8, 'wave': 0.2}))
KS = kinds_of(vs)
check(
    'v3: add_sea dishes a sculpt_shelf bed and floats one water_plane',
    KS.get('sculpt_shelf') == 1 and KS.get('water_plane') == 1,
    (txt, KS),
)
check('v3: ...and draws NO solid `sea` record', KS.get('sea') is None, KS)
shelf = [o for o in vs.objs if o['kind'] == 'sculpt_shelf'][0]
check(
    'v3: the shelf is the 200 x 40 m block, 8 m deep, and sits at y = 0 (field_at adds y to the land)',
    shelf['p']['w'] == 200 and shelf['p']['d'] == 40 and shelf['p']['depth'] == 8 and shelf['y'] == 0.0,
    shelf,
)
check(
    'v3: no R3 level check on a sculpted ground — a rolling seabed is fine, and the reply says so',
    not txt.startswith('refused') and 'no level check is needed' in txt,
    txt,
)

txt, vd = sculpt_ground(('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 12}))
KD = kinds_of(vd)
check(
    'v3: add_dunes sculpts the land — one sculpt_dunes, no solid `dune_field`',
    KD.get('sculpt_dunes') == 1 and KD.get('dune_field') is None,
    (txt, KD),
)
dsc = [o for o in vd.objs if o['kind'] == 'sculpt_dunes'][0]
check(
    'v3: the sculpt keeps the orientation swap — a deeper-than-wide block turns the ridges 90 deg',
    dsc['p']['w'] == 20 and dsc['p']['d'] == 16 and dsc['p']['dir'] == 90 and dsc['p']['h'] == 12,
    dsc['p'],
)
bare = bare_ground(vd)
crest = max(A.ground_height(vd, dsc['x'] + i * 0.5 - 10, dsc['z'] + j * 0.5 - 8) for i in range(41) for j in range(33))
flat = A.ground_height(bare, dsc['x'], dsc['z'])
check(
    'v3: ground_height on the dune crest (%.2f m) is well above the land it grew from (%.2f m)' % (crest, flat),
    crest > flat + 6.0,
    (crest, flat),
)
check(
    'v3: the dune sculpt sits at y = 0 and joins the ground-sculpt group',
    dsc['y'] == 0.0 and dsc['grp'] == 'ground sculpts',
    (dsc['y'], dsc['grp']),
)

txt, vb = sculpt_ground(('add_beach', {'cells': ['B10', 'K10', 'K16'], 'width': 30, 'height': 2.5}))
KB = kinds_of(vb)
check(
    'v3: add_beach over 3 cells sculpts 2 pads and 2 sand masks, and no solid `beach`',
    KB.get('sculpt_flat') == 2 and KB.get('sculpt_shelf') == 2 and KB.get('beach') is None,
    (txt, KB),
)
pad = [o for o in vb.objs if o['kind'] == 'sculpt_flat'][0]
mask = [o for o in vb.objs if o['kind'] == 'sculpt_shelf'][0]
wl = water_level_of(the_ground(vb))
check(
    'v3: the pad is set to the ground water line + %g m (%.3f m), so the strip reads as a beach'
    % (BEACH_RISE, wl + BEACH_RISE),
    abs(pad['p']['level'] - (wl + BEACH_RISE)) < 1e-6,
    (pad['p']['level'], wl),
)
check(
    'v3: the pad feathers over %g x the strip width = %g m toward the land' % (BEACH_FEATHER, BEACH_FEATHER * 30),
    abs(pad['p']['feather'] - BEACH_FEATHER * 30) < 1e-6,
    pad['p']['feather'],
)
check(
    'v3: the pad is len x width, laid along the walk (9 m of shore, 30 m across)',
    abs(pad['p']['w'] - 9) < 1e-6 and abs(pad['p']['d'] - 30) < 1e-6,
    pad['p'],
)
check(
    'v3: the sand mask covers exactly the same strip at depth 0 — a shelf footprint is SAND',
    mask['p']['depth'] == 0
    and mask['p']['w'] == pad['p']['w']
    and mask['p']['d'] == pad['p']['d']
    and abs(mask['ry'] - pad['ry']) < 1e-12,
    (mask['p'], pad['p']),
)
only_mask = A.Drawing({'objects': [o for o in vb.objs if o['kind'] in ('ground', 'sculpt_shelf')]})
check(
    'v3: ...and a depth-0 shelf moves NO height — it is a colour, not a landform',
    abs(A.ground_height(only_mask, mask['x'], mask['z']) - A.ground_height(bare_ground(vb), mask['x'], mask['z']))
    < 1e-9,
    (A.ground_height(only_mask, mask['x'], mask['z']), A.ground_height(bare_ground(vb), mask['x'], mask['z'])),
)
check(
    'v3: the reply still says which side the sea is on, and that nothing solid was drawn',
    'LEFT' in txt and 'No solid `beach` record' in txt,
    txt,
)

txt, vi = sculpt_ground(('add_island', {'centre': 'AK30', 'radius': 25, 'height': 5, 'beach': 8}))
KI = kinds_of(vi)
check(
    'v3: add_island sculpts a low wide peak with a sand shelf round it, and no solid `island`',
    KI.get('sculpt_peak') == 1 and KI.get('sculpt_shelf') == 1 and KI.get('island') is None,
    (txt, KI),
)
peak = [o for o in vi.objs if o['kind'] == 'sculpt_peak'][0]
ring = [o for o in vi.objs if o['kind'] == 'sculpt_shelf'][0]
check(
    'v3: the peak reaches radius + beach = 33 m and stands 5 m over the land',
    peak['p']['r'] == 33 and peak['p']['h'] == 5 and peak['y'] == 0.0,
    peak['p'],
)
check(
    'v3: the sand shelf is 2(r + beach) = 66 m square at depth 0',
    ring['p']['w'] == 66 and ring['p']['d'] == 66 and ring['p']['depth'] == 0,
    ring['p'],
)
check(
    'v3: the island really rises — the ground at its middle is above the land it grew from',
    A.ground_height(vi, peak['x'], peak['z']) > A.ground_height(bare_ground(vi), peak['x'], peak['z']) + 4.0,
    (A.ground_height(vi, peak['x'], peak['z']), A.ground_height(bare_ground(vi), peak['x'], peak['z'])),
)

txt, vw = sculpt_ground(('add_breakwater', {'cells': ['H45', 'H33'], 'height': 2.5, 'width': 6}))
check(
    'v3: a breakwater KEEPS its solid on a sculpted ground — a mound is an object, not a landform',
    kinds_of(vw).get('breakwater') == 1 and not any(o['kind'].startswith('sculpt_') for o in vw.objs),
    (txt, kinds_of(vw)),
)
check('v3: ...and the reply says so', 'keeps its solid' in txt, txt)

txt, vc = sculpt_ground(('make_coast', {'cell_from': 'A1', 'cell_to': 'GR100', 'sea_side': 'north'}))
KC = kinds_of(vc)
check(
    'v3: make_coast on a sculpted ground yields NO solid sea, beach or dune_field',
    not any(KC.get(k) for k in ('sea', 'beach', 'dune_field')),
    (txt, KC),
)
check(
    'v3: ...it lays the five sculpts instead — shelf + water_plane, flat + shelf, dunes',
    KC.get('sculpt_shelf') == 2
    and KC.get('water_plane') == 1
    and KC.get('sculpt_flat') == 1
    and KC.get('sculpt_dunes') == 1
    and len(vc.objs) == 6,
    KC,
)
check(
    'v3: ...and the reply says the whole shore was cut into the one ground',
    'cut into the one sculpted ground' in txt,
    txt,
)

# R7 still bites on the sculpted path — the family's own ranges are checked FIRST
txt, _ = sculpt_ground(('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 140}))
check(
    'v3: R7 first — 140 m dunes are still refused on a sculpted ground',
    txt.startswith('refused') and '3 to 25 m' in txt,
    txt,
)
txt, _ = sculpt_ground(('add_beach', {'cells': ['B10', 'K10'], 'height': 0}))
check(
    'v3: R7 first — a 0 m beach is still refused on a sculpted ground',
    txt.startswith('refused') and 'not a beach' in txt,
    txt,
)
txt, _ = sculpt_ground(('add_sea', {'cell_from': 'A1', 'cell_to': 'GR40', 'depth': 0}))
check('v3: R7 first — a 0 m deep sea is still refused on a sculpted ground', txt.startswith('refused'), txt)

# hiding the ground is the escape hatch back to the old solids
txt, vh = assistant('make_ground', {'cell_from': 'A1', 'cell_to': 'GR100', 'style': 'rolling'})
vh.objs[-1]['hidden'] = True
txt, vh = assistant('add_dunes', {'cell_from': 'D20', 'cell_to': 'S39', 'height': 12}, drawing=vh)
check(
    'v3: a HIDDEN ground is no ground — the old solid `dune_field` comes back',
    kinds_of(vh).get('dune_field') == 1 and kinds_of(vh).get('sculpt_dunes') is None,
    (txt, kinds_of(vh)),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
SEA_P = {'w': 120, 'd': 80, 'depth': 6, 'wave': 0.15, 'seed': 1, 'res': 24}
DUNE_P = {'w': 120, 'd': 60, 'h': 8, 'seed': 1, 'res': 40, 'dir': 0}
ISL_P = {'r': 40, 'h': 6, 'wobble': 0.3, 'beach': 6, 'seed': 1, 'seg': 48, 'rings': 10}
cases = [
    {'kind': 'sea', 'p': SEA_P},
    {'kind': 'beach', 'p': {'len': 60, 'w': 25, 'h': 2, 'seed': 1}},
    {'kind': 'dune_field', 'p': DUNE_P},
    {'kind': 'island', 'p': ISL_P},
    {'kind': 'breakwater', 'p': {'len': 60, 'w': 8, 'h': 3}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check('every kind builds real geometry', all(r['ok'] for r in b), [(r['kind'], r['ok'], r['err']) for r in b])

# sea: the plan is exact, the height is the Python noise's
sea_r = by['sea']
check(
    'sea spans 120 x 80 m on the plan',
    abs(sea_r['size'][0] - 120) <= 1.2 and abs(sea_r['size'][2] - 80) <= 0.8,
    sea_r['size'],
)
want_sea = sea_span(6, 0.15, 24, 1)
check(
    'sea height matches the Python wave arithmetic within 1.5%%: want %.3f m' % want_sea,
    abs(sea_r['size'][1] - want_sea) <= 0.015 * want_sea,
    (sea_r['size'], want_sea),
)
check(
    'sea height sits between depth-0.3-wave and depth+wave',
    6 - 0.3 - 0.15 <= sea_r['size'][1] <= 6 + 0.15,
    sea_r['size'][1],
)
check('sea digs: its lowest point is the bed under y=0', sea_r['min'][1] <= -6.0, sea_r['min'])
check('sea is a 25x25 water lattice over a box', sea_r['tris'] == 2 * 24 * 24 + 12, sea_r['tris'])

# beach: len x h x w, the water edge flat on the ground at -Z
bch_r = by['beach']
check(
    'beach is 60 long, 2 tall, 25 wide',
    abs(bch_r['size'][0] - 60) <= 0.6 and abs(bch_r['size'][1] - 2) <= 0.02 and abs(bch_r['size'][2] - 25) <= 0.25,
    bch_r['size'],
)
check('beach sits on the ground (water edge at y=0)', abs(bch_r['min'][1]) < 1e-6, bch_r['min'])

# dune_field: the peak is exactly h because of the Python normalisation
dun_r = by['dune_field']
sc = dune_scale(40, 1)
raw_max = 1.0 / sc
want_dune = 8 * raw_max * sc
check(
    'dune field is 120 x 60 m on the plan',
    abs(dun_r['size'][0] - 120) <= 1.8 and abs(dun_r['size'][2] - 60) <= 0.9,
    dun_r['size'],
)
check(
    'dune crest matches the Python normalisation within 1.5%%: want %.3f m (raw max %.4f)' % (want_dune, raw_max),
    abs(dun_r['size'][1] - want_dune) <= 0.015 * want_dune,
    (dun_r['size'], want_dune),
)
check('dune field is a solid body standing on the ground', abs(dun_r['min'][1]) < 1e-6, dun_r['min'])
# res^2 lattice quads, a skirt of 4*res quads down to y=0, and one floor quad
check('dune lattice plus skirt and floor', dun_r['tris'] == 2 * (40 * 40 + 4 * 40 + 1), dun_r['tris'])

# island: the plan size is the wandering shoreline plus the beach ring
isl_r = by['island']
wx, wz = island_span(40, 0.3, 6, 1, 48)
check(
    'island plan matches the Python shoreline within 1.5%%: want %.1f x %.1f m' % (wx, wz),
    abs(isl_r['size'][0] - wx) <= 0.015 * wx and abs(isl_r['size'][2] - wz) <= 0.015 * wz,
    (isl_r['size'], wx, wz),
)
lo, hi = 2 * (40 + 6) * (1 - 0.3), 2 * (40 + 6) * (1 + 0.3)
check(
    'island plan stays inside 2(r+beach)(1 +- wobble) = %.1f..%.1f m' % (lo, hi),
    lo <= isl_r['size'][0] <= hi and lo <= isl_r['size'][2] <= hi,
    isl_r['size'],
)
check(
    'island is 6 m tall, standing on the ground',
    abs(isl_r['size'][1] - 6) <= 0.06 and abs(isl_r['min'][1]) < 1e-6,
    isl_r,
)

check(
    'breakwater is 60 long, 3 tall, 8 wide at the base',
    abs(by['breakwater']['size'][0] - 60) <= 0.6
    and abs(by['breakwater']['size'][1] - 3) <= 0.03
    and abs(by['breakwater']['size'][2] - 8) <= 0.08,
    by['breakwater']['size'],
)
check(
    'labels',
    [by[k]['label'] for k in NEW_KINDS] == ['Sea', 'Beach', 'Dune field', 'Island', 'Breakwater'],
    [by[k]['label'] for k in NEW_KINDS],
)

# ── the height field IS the geometry ─────────────────────────────────────────
# The number the assistant stands a house on has to be the number the tab draws.
BCH_P = {'len': 60, 'w': 25, 'h': 2, 'seed': 1}
ISL_W = 2 * (40 * 1.3 + 6)
for kind, p, W, D, nx, nz, box in (
    ('beach', BCH_P, 60, 25, BX, BZ, bch_r['size'][1]),
    ('dune_field', DUNE_P, 120, 60, 40, 40, dun_r['size'][1]),
    ('island', ISL_P, ISL_W, ISL_W, 40, 40, isl_r['size'][1]),
):
    top = fn_max(kind, p, W, D, nx, nz)
    check(
        '%s: the height field tops out at %.3f m — the tab draws %.3f (within 1.5%%)' % (kind, top, box),
        top > 0 and abs(top - box) <= 0.015 * box,
        (top, box),
    )

check('the beach is two materials over one vertex array (dry sand + the wet band)', bch_r['parts'] == 2, bch_r['parts'])
check(
    'the dune field is two materials over one vertex array (sand + marram crests)', dun_r['parts'] == 2, dun_r['parts']
)
# splitting an index array cannot lose a triangle: lattice + scarp + 2 ends + floor
check(
    'the wet band cost the beach nothing: %d triangles across both parts' % (2 * (BX * BZ + BX + 2 * BZ + 1)),
    bch_r['tris'] == 2 * (BX * BZ + BX + 2 * BZ + 1),
    bch_r['tris'],
)

# a turned dune field keeps the block it was sized to
t = browser_kinds([{'kind': 'dune_field', 'p': dict(DUNE_P, dir=90)}])[0]
check(
    'dir 90 turns the dune field a quarter on the plan',
    t['ok']
    and abs(t['size'][0] - 60) <= 0.9
    and abs(t['size'][2] - 120) <= 1.8
    and abs(t['size'][1] - want_dune) <= 0.015 * want_dune,
    t,
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases + [{'kind': 'dune_field', 'p': dict(DUNE_P, dir=90)}])
for k, floor in (('sea', 400), ('beach', 300), ('dune_field', 1000), ('island', 200), ('breakwater', 4)):
    check('blender builds %s' % k, bl.get(k, {}).get('polys', 0) > floor, bl.get(k))
finish()
