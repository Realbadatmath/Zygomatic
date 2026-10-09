# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_fields_meadows.py — the fields_meadows family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_fields_meadows.py

Four kinds — crop_field, meadow, marsh, vineyard — have to mean the same thing
in the assistant, in the tab and in Blender. Three things are written out three
times and are therefore checked here against the tab's own geometry:

  · THE ROW ARITHMETIC. floor(d/spacing)+1 rows, spread so the outer edges land
    on the plot edge, each 0.6 x spacing wide so the soil shows between them.
    The Python copy predicts the tab's triangle count exactly.
  · THE SCATTER HASH. frac(sin(i*127.1 + j*311.7 + seed*74.7) * 43758.5453),
    the same generator as terrain. It decides which of the three flower colours
    each head takes, and the tab merges one part per colour — so the Python
    copy predicts the record's PART count, colour for colour.
  · THE DRAPE (2026-09-07). p.gx / p.gz are the ground plane's rise per metre
    along the record's own x and z. Every solid drops its four base corners onto
    that plane and keeps its sides vertical, so the crop stands up on a hillside
    instead of leaning over. `draped_height` predicts the record's whole
    bounding-box height from gx, gz, w, d and dir — and the tab and Blender are
    both held to it, to the centimetre.

The ground rules this family answers to: R1 base_height None means the ground;
R2 field/meadow/vineyard drape and tile; R3 marsh and the polder's ditches are
LEVEL water and refuse uneven ground; R4 the pasture fences take an rz per
segment; R7 real crop, vine and reed heights.
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
from zyg_workflows.arch_assistant_ext.fields_meadows import (
    KINDS,
    PROMPT,
    row_count,
    post_count,
    flower_colours,  # noqa: E402
    crop_field_tris,
    meadow_tris,
    marsh_tris,
    vineyard_tris,
    row_band,
    draped_height,
    ROW_FRAC,
    VINE_H,
    REED_H,
)
from zyg_workflows import arch_assistant as A  # noqa: E402

NEW_KINDS = ['crop_field', 'meadow', 'marsh', 'vineyard']

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('add_field', 'add_meadow', 'add_marsh', 'add_vineyard', 'add_pasture', 'make_polder')),
    names,
)
check('prompt is one paragraph under 1100 chars', 0 < len(PROMPT) <= 1100 and '\n' not in PROMPT, len(PROMPT))
check(
    'prompt names the Dutch words',
    all(w in PROMPT for w in ('akker', 'bollenveld', 'sloten', 'weiland', 'moeras')),
    PROMPT,
)
check(
    'prompt says the rows follow the contour and the field drapes',
    'contour' in PROMPT and 'DRAPED' in PROMPT and 'terrace' in PROMPT,
    PROMPT,
)

# A1..BH40 is exactly 60 x 40 m on the 1 m grid.
txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'BH40', 'crop': 'tulips'})
f0 = d.objs[-1]
check(
    'add_field drew ONE crop_field 60 x 40',
    kinds_of(d).get('crop_field') == 1 and f0['p']['w'] == 60 and f0['p']['d'] == 40,
    (txt, f0['p']),
)
check(
    'tulips are crop 4, 0.3 m tall, rows 0.75 m apart along x',
    f0['p']['crop'] == 4 and f0['p']['h'] == 0.3 and f0['p']['spacing'] == 0.75 and f0['p']['dir'] == 0,
    f0['p'],
)
check('54 rows over 40 m at 0.75 m (floor(40/0.75)+1)', row_count(40, 0.75) == 54 and '54 rows' in txt, txt)
check(
    'field sits on the ground, grouped, id reported',
    f0['y'] == 0.0 and f0['grp'] == 'fields' and f0['id'] in txt,
    (f0, txt),
)
check('flat ground: the drape is zero on both axes', f0['p']['gx'] == 0 and f0['p']['gz'] == 0, f0['p'])
check(
    'R7: a row is %g x spacing wide (0.45 m at 0.75), so 54 rows cover 24.3 of 40 m and soil shows' % ROW_FRAC,
    abs(row_band(0.75) - 0.45) < 1e-9 and row_count(40, 0.75) * row_band(0.75) < 40,
    row_band(0.75),
)

txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'BH40', 'crop': 'corn', 'direction': 'z'}, drawing=d)
f1 = d.objs[-1]
check(
    "direction 'z' turns the field a quarter and swaps w/d",
    f1['p']['w'] == 40 and f1['p']['d'] == 60 and f1['p']['dir'] == 90,
    (txt, f1['p']),
)
check('corn is crop 1 and 2.2 m tall', f1['p']['crop'] == 1 and f1['p']['h'] == 2.2, f1['p'])

txt, d = assistant('add_field', {'cell_from': 'C4', 'cell_to': 'L13', 'crop': 'wheat', 'base_height': 3}, drawing=d)
check('base_height puts the field on a terrace', d.objs[-1]['y'] == 3.0 and d.objs[-1]['p']['crop'] == 0, txt)

txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'BH40', 'crop': 'rice'}, drawing=d)
check('unknown crop refused', txt.startswith('refused'), txt)
txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'BH40', 'direction': 'up'}, drawing=d)
check('bad direction refused', txt.startswith('refused'), txt)
txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'BH40', 'spacing': 0.1}, drawing=d)
check('401 rows refused (over 400)', txt.startswith('refused') and '401' in txt, txt)
txt, d = assistant('add_field', {'cell_from': 'A1', 'cell_to': 'ZZ9'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused'), txt)

txt, d = assistant('add_meadow', {'cell_from': 'C4', 'cell_to': 'L13', 'flowers': 300, 'seed': 4}, drawing=d)
m0 = d.objs[-1]
check(
    'add_meadow drew one 10 x 10 meadow with 300 flowers',
    m0['kind'] == 'meadow'
    and m0['p']['w'] == 10
    and m0['p']['d'] == 10
    and m0['p']['flowers'] == 300
    and m0['p']['seed'] == 4,
    (txt, m0['p']),
)
txt, d = assistant('add_meadow', {'cell_from': 'C4', 'cell_to': 'L13', 'flowers': 2500}, drawing=d)
check('2500 flowers refused (cap 2000)', txt.startswith('refused'), txt)

txt, d = assistant('add_marsh', {'cell_from': 'C4', 'cell_to': 'L13', 'reeds': 200, 'depth': 0.5}, drawing=d)
r0 = d.objs[-1]
check(
    'add_marsh drew one marsh 0.5 m deep with 200 reeds',
    r0['kind'] == 'marsh' and r0['p']['reeds'] == 200 and r0['p']['depth'] == 0.5 and r0['p']['reed_h'] == 1.8,
    (txt, r0['p']),
)
check(
    'a marsh is never draped: it carries no gx/gz and says it lies level',
    'gx' not in r0['p'] and 'gz' not in r0['p'] and 'lying level' in txt,
    (r0['p'], txt),
)
txt, d = assistant('add_marsh', {'cell_from': 'C4', 'cell_to': 'L13', 'reeds': 1600}, drawing=d)
check('1600 reeds refused (cap 1500)', txt.startswith('refused'), txt)
txt, d = assistant('add_marsh', {'cell_from': 'C4', 'cell_to': 'L13', 'depth': 9}, drawing=d)
check('a 9 m "marsh" refused — that is a pond', txt.startswith('refused'), txt)
txt, d = assistant('add_marsh', {'cell_from': 'C4', 'cell_to': 'L13', 'reed_height': 3.4}, drawing=d)
check(
    'R7: 3.4 m reeds refused — reeds are %g-%g m' % REED_H,
    txt.startswith('refused') and '1.5' in txt and '2.5' in txt,
    txt,
)

txt, d = assistant('add_vineyard', {'cell_from': 'A1', 'cell_to': 'BH40', 'row_spacing': 2.5}, drawing=d)
v0 = d.objs[-1]
check(
    'add_vineyard drew one vineyard, 17 rows of 11 posts',
    v0['kind'] == 'vineyard'
    and v0['p']['w'] == 60
    and v0['p']['d'] == 40
    and v0['p']['row_spacing'] == 2.5
    and row_count(40, 2.5) == 17
    and post_count(60) == 11,
    (txt, v0['p']),
)
check('R7: a vine row is 1.8 m tall by default', v0['p']['h'] == 1.8, v0['p'])
txt, d = assistant(
    'add_vineyard', {'cell_from': 'A1', 'cell_to': 'BH40', 'direction': 'z', 'base_height': 2}, drawing=d
)
check(
    "vineyard direction 'z' swaps w/d and base_height lifts it",
    d.objs[-1]['p']['w'] == 40
    and d.objs[-1]['p']['d'] == 60
    and d.objs[-1]['p']['dir'] == 90
    and d.objs[-1]['y'] == 2.0,
    d.objs[-1],
)
check(
    'a terrace is level: base_height leaves the drape at zero',
    d.objs[-1]['p']['gx'] == 0 and d.objs[-1]['p']['gz'] == 0,
    d.objs[-1]['p'],
)
txt, d = assistant('add_vineyard', {'cell_from': 'A1', 'cell_to': 'BH40', 'row_spacing': 0.2}, drawing=d)
check('vine rows 0.2 m apart refused', txt.startswith('refused'), txt)
txt, d = assistant('add_vineyard', {'cell_from': 'A1', 'cell_to': 'BH40', 'height': 3.0}, drawing=d)
check(
    'R7: a 3 m "vine row" refused — a vineyard is %g-%g m' % VINE_H,
    txt.startswith('refused') and '1.6' in txt and '2' in txt,
    txt,
)

# make_polder: C4..L13 is a 10 x 10 m block
before = dict(kinds_of(d))
txt, d = assistant('make_polder', {'cell_from': 'C4', 'cell_to': 'L13', 'ditch_width': 3, 'crop': 'grass'}, drawing=d)
made = d.objs[-5:]
check(
    'make_polder drew 1 crop_field + 4 canals',
    kinds_of(d).get('crop_field', 0) - before.get('crop_field', 0) == 1
    and kinds_of(d).get('canal', 0) - before.get('canal', 0) == 4,
    (txt, [o['kind'] for o in made]),
)
check(
    'the field is the block inset by the ditch (10 - 2x3 = 4 m)',
    made[0]['kind'] == 'crop_field' and made[0]['p']['w'] == 4 and made[0]['p']['d'] == 4 and made[0]['p']['crop'] == 3,
    made[0]['p'],
)
ditches = made[1:]
check(
    'four ditches, each as long as its block side (10 m), 3 m wide, 1.2 m deep',
    all(o['kind'] == 'canal' and o['p']['len'] == 10 and o['p']['w'] == 3 and o['p']['depth'] == 1.2 for o in ditches),
    [o['p'] for o in ditches],
)
check(
    'the ditch centres sit on the four block edges',
    sorted(round(o['x'], 3) for o in ditches) == [-148.0, -143.0, -143.0, -138.0]
    and sorted(round(o['z'], 3) for o in ditches) == [-147.0, -142.0, -142.0, -137.0],
    [(o['x'], o['z']) for o in ditches],
)
check(
    'the polder is one group and every id is reported',
    len({o['grp'] for o in made}) == 1 and all(o['id'] in txt for o in (made[0], made[-1])),
    txt,
)
check(
    'on flat ground the polder is unchanged: level ditches, field at y = 0, no drape',
    all(o['y'] == 0.0 for o in made) and made[0]['p']['gx'] == 0 and made[0]['p']['gz'] == 0 and 'level ditches' in txt,
    (txt, [o['y'] for o in made]),
)
txt, d = assistant('make_polder', {'cell_from': 'C4', 'cell_to': 'L13', 'ditch_width': 6}, drawing=d)
check('ditches wider than the block refused', txt.startswith('refused'), txt)

# add_pasture: the same 10 x 10 block, a flowerless meadow inside a ring of fences
before = dict(kinds_of(d))
txt, d = assistant('add_pasture', {'cell_from': 'C4', 'cell_to': 'L13', 'fence_height': 1.4}, drawing=d)
made = d.objs[-5:]
check(
    'add_pasture drew 1 meadow + 4 fences',
    kinds_of(d).get('meadow', 0) - before.get('meadow', 0) == 1
    and kinds_of(d).get('fence', 0) - before.get('fence', 0) == 4,
    (txt, [o['kind'] for o in made]),
)
check(
    'the pasture grass is the whole block and carries NO flowers',
    made[0]['kind'] == 'meadow'
    and made[0]['p']['w'] == 10
    and made[0]['p']['d'] == 10
    and made[0]['p']['flowers'] == 0,
    made[0]['p'],
)
fences = made[1:]
check(
    'four fences, each as long as its block side (10 m), 1.4 m tall, 5 posts',
    all(o['kind'] == 'fence' and o['p']['len'] == 10 and o['p']['h'] == 1.4 and o['p']['posts'] == 5 for o in fences),
    [o['p'] for o in fences],
)
check(
    'the fences sit on the four block edges, one group, ids reported',
    sorted(round(o['x'], 3) for o in fences) == [-148.0, -143.0, -143.0, -138.0]
    and sorted(round(o['z'], 3) for o in fences) == [-147.0, -142.0, -142.0, -137.0]
    and len({o['grp'] for o in made}) == 1
    and made[0]['id'] in txt,
    (txt, [(o['x'], o['z']) for o in fences]),
)
check('on flat ground every fence is level (rz = 0)', all(o['rz'] == 0 for o in fences), [o['rz'] for o in fences])
txt, d = assistant('add_pasture', {'cell_from': 'C4', 'cell_to': 'L13', 'fence_height': 9}, drawing=d)
check('a 9 m stock fence refused', txt.startswith('refused'), txt)

txt, d = assistant(
    'add_object', {'kind': 'crop_field', 'cell': 'A1', 'params': {'w': 30, 'd': 20, 'crop': 4}}, drawing=d
)
check(
    'add_object knows crop_field',
    d.objs[-1]['kind'] == 'crop_field' and d.objs[-1]['p']['w'] == 30 and d.objs[-1]['p']['crop'] == 4,
    txt,
)
txt, d = assistant('add_object', {'kind': 'marsh', 'cell': 'A1', 'params': {'reeds': 40}}, drawing=d)
check('add_object knows marsh', d.objs[-1]['kind'] == 'marsh' and d.objs[-1]['p']['reeds'] == 40, txt)

check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('KINDS declares all four', sorted(KINDS) == sorted(NEW_KINDS), sorted(KINDS))
check(
    'KINDS gives gx/gz to the three draped kinds and to no other',
    all('gx' in KINDS[k] and 'gz' in KINDS[k] for k in ('crop_field', 'meadow', 'vineyard'))
    and 'gx' not in KINDS['marsh'],
    {k: sorted(v) for k, v in KINDS.items()},
)

# ── the ground (R1-R4, R7) ────────────────────────────────────────────────────
print('ground')
# A1..CV100 is 100 x 100 m; a 10 m rise along z is a 1:10 slope, gz = 0.1 everywhere.
g = A.Drawing({'objects': []})
txt, g = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 10, 'direction': 'z'}, drawing=g)
check(
    'the terrain family drew a 100 x 100 slope rising 10 m along z',
    abs(A.ground_height(g, -100, -110) - 4.0) < 1e-9 and abs(A.ground_height(g, -100, -90) - 6.0) < 1e-9,
    (A.ground_height(g, -100, -110), A.ground_height(g, -100, -90)),
)

# U21..CB60 is 60 x 40 m centred on (-100, -110), well inside the slope.
before = dict(kinds_of(g))
txt, g = assistant('add_field', {'cell_from': 'U21', 'cell_to': 'CB60', 'crop': 'wheat'}, drawing=g)
sf = g.objs[-1]
check(
    'R2: a field on a planar slope is ONE record, not tiled',
    kinds_of(g).get('crop_field', 0) - before.get('crop_field', 0) == 1 and 'tiles' not in txt,
    txt,
)
check(
    'R2: it carries the plane, gz = 0.1 and gx = 0 (rows run along x)',
    sf['p']['gz'] == 0.1 and sf['p']['gx'] == 0.0 and sf['p']['dir'] == 0,
    sf['p'],
)
check(
    'R1: y is the ground at the centre of the footprint (4.0 m), and it says so',
    sf['y'] == 4.0 and 'draped on the ground at 4.00 m' in txt,
    (sf['y'], txt),
)
check(
    'the record is NOT tilted — the crop stands up, the geometry drapes',
    sf['rx'] == 0 and sf['rz'] == 0 and sf['ry'] == 0,
    (sf['rx'], sf['ry'], sf['rz']),
)
check(
    'contour rows: with no direction the rows run east-west, across the steeper gradient',
    'rows run east-west along the contour of the slope' in txt,
    txt,
)

txt, g = assistant('add_field', {'cell_from': 'U21', 'cell_to': 'CB60', 'crop': 'wheat', 'direction': 'z'}, drawing=g)
check(
    'an explicit direction wins over the contour',
    g.objs[-1]['p']['dir'] == 90 and 'running along z' in txt and 'contour' not in txt,
    txt,
)

txt, g = assistant('add_field', {'cell_from': 'U21', 'cell_to': 'CB60', 'crop': 'wheat', 'base_height': 7}, drawing=g)
check(
    'R1: base_height still wins — a level terrace at 7 m with no drape',
    g.objs[-1]['y'] == 7.0 and g.objs[-1]['p']['gx'] == 0 and g.objs[-1]['p']['gz'] == 0,
    g.objs[-1],
)

# a slope climbing east: the contour now runs north-south
gx_d = A.Drawing({'objects': []})
txt, gx_d = assistant(
    'add_slope', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 10, 'direction': 'x'}, drawing=gx_d
)
txt, gx_d = assistant('add_vineyard', {'cell_from': 'U21', 'cell_to': 'CB60'}, drawing=gx_d)
vg = gx_d.objs[-1]
check(
    'contour rows on an east-facing slope run north-south, and the vineyard drapes with gx = 0.1',
    vg['p']['gx'] == 0.1
    and vg['p']['gz'] == 0.0
    and vg['p']['dir'] == 90
    and 'rows run north-south along the contour of the slope' in txt,
    (txt, vg['p']),
)
check('the vineyard sits on the ground at the centre (5.0 m)', vg['y'] == 5.0, vg['y'])

# R3: water lies level
txt, g = assistant('add_marsh', {'cell_from': 'U21', 'cell_to': 'CB60'}, drawing=g)
check(
    'R3: a marsh refuses the slope, names the rise and offers a way out',
    txt.startswith('refused') and 'rises 3.2 m' in txt and 'water lies level' in txt and 'flatten_pad' in txt,
    txt,
)
txt, g = assistant('make_polder', {'cell_from': 'U21', 'cell_to': 'CB60', 'ditch_width': 3}, drawing=g)
check(
    'R3: make_polder refuses the same ground — its four canals are level water too',
    txt.startswith('refused') and 'water lies level' in txt,
    txt,
)
n_before = len(g.objs)
txt, g = assistant('add_marsh', {'cell_from': 'U21', 'cell_to': 'CB60', 'base_height': 2}, drawing=g)
check(
    'R3: base_height accepts it anyway, level at 2 m',
    len(g.objs) == n_before + 1 and g.objs[-1]['y'] == 2.0 and g.objs[-1]['kind'] == 'marsh',
    txt,
)

# R4: the pasture fences follow the ground, one rz a segment
before = dict(kinds_of(g))
txt, g = assistant('add_pasture', {'cell_from': 'U21', 'cell_to': 'CB60'}, drawing=g)
pf = [o for o in g.objs[-4:]]
check(
    'R4: the two fences running across the slope are level, the two running down it tilt',
    sorted(round(o['rz'], 4) for o in pf) == [round(-math.atan(4.0 / 40), 4), round(-math.atan(4.0 / 40), 4), 0.0, 0.0],
    [o['rz'] for o in pf],
)
check(
    'R4: each fence sits on the ground at its own centre, and the reply says two run downhill',
    all(abs(o['y'] - A.ground_height(g, o['x'], o['z'])) < 1e-6 for o in pf) and '2 of them running downhill' in txt,
    (txt, [(o['y'], o['x'], o['z']) for o in pf]),
)

# R2 tiling: a hill is not planar, so an 80 x 80 meadow breaks into patches
hl = A.Drawing({'objects': []})
txt, hl = assistant('add_hill', {'centre': 'AP40', 'radius': 20, 'height': 6}, drawing=hl)
txt, hl = assistant('add_meadow', {'cell_from': 'A1', 'cell_to': 'CB80', 'flowers': 400}, drawing=hl)
mt = [o for o in hl.objs if o['kind'] == 'meadow']
check('R2: an 80 x 80 meadow over a hill tiles into %d records (>= 4)' % len(mt), len(mt) >= 4, len(mt))
check(
    'R2: the tiles cover the footprint edge to edge, one group, and it says so',
    abs(min(o['x'] - o['p']['w'] / 2 for o in mt) + 150) < 1e-6
    and abs(max(o['x'] + o['p']['w'] / 2 for o in mt) + 70) < 1e-6
    and len({o['grp'] for o in mt}) == 1
    and ('in %d tiles over the uneven ground' % len(mt)) in txt,
    txt,
)
check(
    'R2: every tile takes its own ground and its own plane — the tiles on the hill are tilted, the rest flat',
    all(abs(o['y'] - A.ground_height(hl, o['x'], o['z'])) < 0.5 for o in mt)  # the fitted plane, not the apex
    and 4 <= sum(1 for o in mt if abs(o['p']['gx']) > 0.05 or abs(o['p']['gz']) > 0.05) < len(mt)
    and max(o['y'] for o in mt) > 3.0,
    sorted(round(abs(o['y'] - A.ground_height(hl, o['x'], o['z'])), 3) for o in mt)[-3:],
)
check(
    'R2: the flowers are shared out over the tiles, not repeated 64 times',
    abs(sum(o['p']['flowers'] for o in mt) - 400) <= len(mt),
    sum(o['p']['flowers'] for o in mt),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'crop_field', 'p': {'w': 60, 'd': 40, 'crop': 4, 'spacing': 0.75, 'h': 0.3, 'dir': 0}},
    {'kind': 'crop_field', 'p': {'w': 60, 'd': 40, 'crop': 0, 'spacing': 0.75, 'h': 0.6, 'dir': 0}},
    {'kind': 'meadow', 'p': {'w': 30, 'd': 20, 'flowers': 200, 'seed': 1, 'h': 0.25}},
    {'kind': 'meadow', 'p': {'w': 10, 'd': 10, 'flowers': 2, 'seed': 7, 'h': 0.25}},
    {'kind': 'meadow', 'p': {'w': 10, 'd': 10, 'flowers': 0, 'seed': 1, 'h': 0.25}},
    {'kind': 'marsh', 'p': {'w': 30, 'd': 20, 'depth': 0.4, 'reeds': 120, 'seed': 1, 'reed_h': 1.8}},
    {'kind': 'vineyard', 'p': {'w': 60, 'd': 40, 'row_spacing': 2.5, 'h': 1.8, 'dir': 0}},
    # the drape: the same three kinds on the 1:10 slope the assistant just drew
    {'kind': 'crop_field', 'p': {'w': 60, 'd': 40, 'crop': 4, 'spacing': 0.75, 'h': 0.3, 'dir': 0, 'gx': 0, 'gz': 0.1}},
    {'kind': 'meadow', 'p': {'w': 30, 'd': 20, 'flowers': 200, 'seed': 1, 'h': 0.25, 'gx': 0.05, 'gz': 0}},
    {'kind': 'vineyard', 'p': {'w': 40, 'd': 60, 'row_spacing': 2.5, 'h': 1.8, 'dir': 90, 'gx': 0.1, 'gz': 0}},
]
b = browser_kinds(cases)
tulip, wheat, mead, mead2, bare, marsh, vine, dcrop, dmead, dvine = b
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
check('every kind builds real geometry', all(r['ok'] for r in b), [(r['kind'], r['ok'], r['err']) for r in b])

check('tulip field is 4 parts: soil + red + white + yellow', tulip['parts'] == 4, tulip)
check('wheat field is 2 parts: soil + the crop', wheat['parts'] == 2, wheat)
check(
    'crop field is 60 x (h + 0.05 soil) x 40',
    abs(tulip['size'][0] - 60) < 0.6 and abs(tulip['size'][1] - 0.35) < 0.006 and abs(tulip['size'][2] - 40) < 0.4,
    tulip['size'],
)
check('crop field digs nothing: it stands on the ground', abs(tulip['min'][1]) < 1e-6, tulip['min'])
check(
    'crop field tris = plate + 12 per row, %d rows -> %d' % (row_count(40, 0.75), crop_field_tris(40, 0.75)),
    tulip['tris'] == crop_field_tris(40, 0.75) and wheat['tris'] == crop_field_tris(40, 0.75),
    (tulip['tris'], wheat['tris']),
)

check('meadow tris = plate + 12 per flower (%d)' % meadow_tris(200), mead['tris'] == meadow_tris(200), mead['tris'])
cols = flower_colours(200, 1)
check('200 flowers reach all three colours in the Python copy: %r' % (cols,), min(cols) > 0 and sum(cols) == 200, cols)
check('...so the tab merges them into 1 + 3 parts', mead['parts'] == 1 + sum(1 for c in cols if c), mead)
cols2 = flower_colours(2, 7)
check(
    '2 flowers, seed 7: the Python hash says %d colour(s) — the tab agrees' % sum(1 for c in cols2 if c),
    mead2['parts'] == 1 + sum(1 for c in cols2 if c) and mead2['tris'] == meadow_tris(2),
    (mead2, cols2),
)
check(
    "the pasture's flowerless meadow is the bare plate: 1 part, 12 tris, 0.08 m thick",
    bare['parts'] == 1 and bare['tris'] == meadow_tris(0) and abs(bare['size'][1] - 0.08) < 0.002,
    bare,
)
check(
    'meadow is 30 x (h + 0.15 flower) x 20',
    abs(mead['size'][0] - 30) < 0.3 and abs(mead['size'][1] - 0.4) < 0.005 and abs(mead['size'][2] - 20) < 0.2,
    mead['size'],
)

check(
    'marsh is 30 x (depth + reed_h) x 20',
    abs(marsh['size'][0] - 30) < 0.3 and abs(marsh['size'][1] - 2.2) < 0.03 and abs(marsh['size'][2] - 20) < 0.2,
    marsh['size'],
)
check('the marsh basin digs to -depth', abs(marsh['min'][1] + 0.4) < 0.005, marsh['min'])
check('marsh is 4 parts (rim, bed, water, reeds)', marsh['parts'] == 4, marsh)
check(
    'marsh tris = rim + bed + water + 12 per reed (%d)' % marsh_tris(120),
    marsh['tris'] == marsh_tris(120),
    marsh['tris'],
)

check(
    'vineyard is 60 x 1.8 x 40',
    abs(vine['size'][0] - 60) < 0.6 and abs(vine['size'][1] - 1.8) < 0.02 and abs(vine['size'][2] - 40) < 0.4,
    vine['size'],
)
check('vineyard is 2 parts: posts + vines', vine['parts'] == 2, vine)
check(
    'vineyard tris = %d rows x (vine + %d posts) x 12 = %d'
    % (row_count(40, 2.5), post_count(60), vineyard_tris(60, 40, 2.5)),
    vine['tris'] == vineyard_tris(60, 40, 2.5),
    vine['tris'],
)
check(
    'labels',
    [r['label'] for r in (tulip, mead, marsh, vine)] == ['Crop field', 'Meadow', 'Marsh', 'Vineyard'],
    [r['label'] for r in b],
)

# the drape, in the tab
want_crop = draped_height(60, 40, 0, 0.1, 0.35, 0)
check(
    'draped crop field is %.2f m tall: 0.1 x 40 m of rise + the 0.35 m plate and rows' % want_crop,
    abs(dcrop['size'][1] - want_crop) < 0.01 and abs(dcrop['size'][0] - 60) < 0.6 and abs(dcrop['size'][2] - 40) < 0.4,
    (dcrop['size'], want_crop),
)
check(
    'draping moves vertices, it never adds any: the tris and parts are unchanged',
    dcrop['tris'] == tulip['tris'] and dcrop['parts'] == tulip['parts'],
    (dcrop['tris'], dcrop['parts']),
)
check(
    'the draped record straddles its plane — the low corner sits at -rise/2',
    abs(dcrop['min'][1] + (want_crop - 0.35) / 2) < 0.01,
    dcrop['min'],
)
want_mead = draped_height(30, 20, 0.05, 0, 0.40, 0)
check(
    'draped meadow is %.2f m tall and still %d tris' % (want_mead, meadow_tris(200)),
    abs(dmead['size'][1] - want_mead) < 0.01 and dmead['tris'] == meadow_tris(200),
    (dmead['size'], want_mead),
)
want_vine = draped_height(40, 60, 0.1, 0, 1.8, 90)
check(
    'a TURNED draped vineyard is %.2f m tall — dir turns the footprint before the plane is read' % want_vine,
    abs(dvine['size'][1] - want_vine) < 0.03 and abs(dvine['size'][0] - 60) < 0.6 and abs(dvine['size'][2] - 40) < 0.4,
    (dvine['size'], want_vine),
)
check(
    'the turned vineyard still builds %d tris' % vineyard_tris(40, 60, 2.5),
    dvine['tris'] == vineyard_tris(40, 60, 2.5),
    dvine['tris'],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(
    [
        {'kind': 'crop_field', 'p': {'w': 30, 'd': 20, 'crop': 4, 'spacing': 0.75, 'h': 0.3, 'dir': 0}},
        {'kind': 'meadow', 'p': {'w': 30, 'd': 20, 'flowers': 120, 'seed': 1, 'h': 0.25}},
        {'kind': 'marsh', 'p': {'w': 30, 'd': 20, 'depth': 0.4, 'reeds': 80, 'seed': 1, 'reed_h': 1.8}},
        {'kind': 'vineyard', 'p': {'w': 30, 'd': 20, 'row_spacing': 2.5, 'h': 1.8, 'dir': 45}},
    ]
)
check(
    'blender builds the crop field (soil + %d rows of faces)' % row_count(20, 0.75),
    bl.get('crop_field', {}).get('polys', 0) >= 6 * (1 + row_count(20, 0.75)),
    bl.get('crop_field'),
)
check(
    'blender builds the meadow with its 120 flowers', bl.get('meadow', {}).get('polys', 0) >= 6 * 121, bl.get('meadow')
)
check(
    'blender builds the marsh with its 80 reeds', bl.get('marsh', {}).get('polys', 0) >= 6 * 6 + 6 * 80, bl.get('marsh')
)
check(
    'blender builds the turned vineyard',
    bl.get('vineyard', {}).get('polys', 0) >= 6 * row_count(20, 2.5) * (1 + post_count(30)),
    bl.get('vineyard'),
)

dbl = blender_kinds(
    [
        {
            'kind': 'crop_field',
            'p': {'w': 30, 'd': 20, 'crop': 4, 'spacing': 0.75, 'h': 0.3, 'dir': 0, 'gx': 0, 'gz': 0.1},
        },
        {'kind': 'meadow', 'p': {'w': 30, 'd': 20, 'flowers': 120, 'seed': 1, 'h': 0.25, 'gx': 0.05, 'gz': 0}},
        {'kind': 'vineyard', 'p': {'w': 30, 'd': 20, 'row_spacing': 2.5, 'h': 1.8, 'dir': 45, 'gx': 0.1, 'gz': 0}},
    ]
)
bw = draped_height(30, 20, 0, 0.1, 0.35, 0)
check(
    'blender drapes the crop field to %.2f m — the same height the tab and the Python copy give' % bw,
    abs(dbl.get('crop_field', {}).get('size', [0, 0, 0])[1] - bw) < 0.01,
    dbl.get('crop_field'),
)
check(
    'blender: the draped field straddles its plane (min_y = -rise/2 = %.2f)' % (-(bw - 0.35) / 2),
    abs(dbl.get('crop_field', {}).get('min_y', 9) + (bw - 0.35) / 2) < 0.01,
    dbl.get('crop_field'),
)
check(
    'blender: draping adds no faces — %d before, the same after' % bl['crop_field']['polys'],
    dbl['crop_field']['polys'] == bl['crop_field']['polys']
    and dbl['meadow']['polys'] == bl['meadow']['polys']
    and dbl['vineyard']['polys'] == bl['vineyard']['polys'],
    (dbl['crop_field']['polys'], dbl['meadow']['polys'], dbl['vineyard']['polys']),
)
mw = draped_height(30, 20, 0.05, 0, 0.40, 0)
check(
    'blender drapes the meadow to %.2f m' % mw, abs(dbl['meadow']['size'][1] - mw) < 0.02, (dbl['meadow']['size'], mw)
)
vw = draped_height(30, 20, 0.1, 0.0, 1.8, 45)
check(
    'blender drapes the vineyard turned 45 deg to %.2f m — dir turns the footprint first' % vw,
    abs(dbl['vineyard']['size'][1] - vw) < 0.03,
    (dbl['vineyard']['size'], vw),
)
finish()
