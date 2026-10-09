# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_balconies_facade.py — the balconies_facade family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_balconies_facade.py
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

KINDS9 = [
    'balcony',
    'canopy',
    'awning',
    'cornice',
    'pilaster',
    'louvre_fins',
    'sunshade',
    'string_course',
    'parapet_cap',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(
        t in names
        for t in ('add_balconies', 'add_parapet', 'add_canopy', 'add_louvres', 'add_facade_bands', 'add_pilasters')
    ),
    names,
)

# a 6 x 9 m box, three storeys — 12 walls, 3 slabs, group "tower"
txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'H12', 'storeys': 3, 'name': 'tower'})
check('the test box: 12 walls, 3 slabs', kinds_of(d).get('wall') == 12 and kinds_of(d).get('slab') == 3, txt)

txt, d = assistant('add_balconies', {'walls': 'tower'}, drawing=d)
check('balconies on 4 walls x 2 storeys (storey 0 skipped)', kinds_of(d).get('balcony') == 8, txt)
bals = [o for o in d.objs if o['kind'] == 'balcony']
check(
    'balcony params are the defaults asked for',
    bals[0]['p']['w'] == 2.4 and bals[0]['p']['d'] == 1.2 and bals[0]['p']['rail_h'] == 1.0,
    bals[0]['p'],
)
check(
    'balconies sit on the storey base, none on storey 0',
    sorted({o['y'] for o in bals}) == [2.7, 5.4],
    sorted({o['y'] for o in bals}),
)

# THE OUTWARD RULE: a north-wall balcony must hang on the far side of the wall
nwall = [o for o in d.objs if o['kind'] == 'wall' and o['name'] == 'north wall st1'][0]
nbal = [o for o in bals if o['name'] == 'balcony on north wall st1'][0]
check(
    'north-wall balcony hangs outward (z smaller than its wall)', nbal['z'] < nwall['z'] - 0.05, (nbal['z'], nwall['z'])
)
check(
    '...and keeps the wall ry (north is not flipped)', abs(nbal['ry'] - nwall['ry']) < 1e-6, (nbal['ry'], nwall['ry'])
)
swall = [o for o in d.objs if o['kind'] == 'wall' and o['name'] == 'south wall st1'][0]
sbal = [o for o in bals if o['name'] == 'balcony on south wall st1'][0]
check(
    'south-wall balcony hangs outward too (z larger, ry flipped by PI)',
    sbal['z'] > swall['z'] + 0.05 and abs(abs(sbal['ry'] - swall['ry']) - 3.141593) < 1e-4,
    (sbal['z'], swall['z'], sbal['ry']),
)
ewall = [o for o in d.objs if o['kind'] == 'wall' and o['name'] == 'east wall st2'][0]
ebal = [o for o in bals if o['name'] == 'balcony on east wall st2'][0]
check('east-wall balcony hangs outward (x larger)', ebal['x'] > ewall['x'] + 0.05, (ebal['x'], ewall['x']))

txt, d = assistant('add_parapet', {'group': 'tower', 'height': 1.0, 'thickness': 0.2}, drawing=d)
para = [o for o in d.objs if o['name'] == 'parapet']
check('parapet: 4 walls at y = 3 x 2.7 = 8.1', len(para) == 4 and all(abs(o['y'] - 8.1) < 1e-6 for o in para), txt)
check(
    'parapet copies len/x/z/ry of the top-storey walls',
    all(
        any(
            abs(p['x'] - w['x']) < 1e-6 and abs(p['z'] - w['z']) < 1e-6 and p['p']['len'] == w['p']['len']
            for w in d.objs
            if w['kind'] == 'wall' and w['name'].endswith('st2')
        )
        for p in para
    )
    and para[0]['p']['h'] == 1.0
    and para[0]['p']['t'] == 0.2,
    [p['p'] for p in para],
)

txt, d = assistant('add_canopy', {'wall_id': nwall['id'], 'width': 4, 'depth': 1.8}, drawing=d)
can = [o for o in d.objs if o['kind'] == 'canopy'][-1]  # objs[-1] is now its edge beam
check(
    'canopy on the wall at y = wall.y + 2.4',
    can['kind'] == 'canopy'
    and abs(can['y'] - (nwall['y'] + 2.4)) < 1e-6
    and can['p']['w'] == 4
    and can['p']['d'] == 1.8,
    txt,
)
check('canopy hangs outward too', can['z'] < nwall['z'] - 0.05, (can['z'], nwall['z']))
txt, d = assistant('add_canopy', {'wall_id': nwall['id'], 'kind': 'awning', 'angle': 25}, drawing=d)
awn = d.objs[-1]
check(
    'awning at y = wall.y + h - 0.3',
    awn['kind'] == 'awning' and abs(awn['y'] - (nwall['y'] + 2.7 - 0.3)) < 1e-6 and awn['p']['angle'] == 25,
    txt,
)

txt, d = assistant('add_louvres', {'walls': [ewall['id']], 'spacing': 0.4}, drawing=d)
lou = d.objs[-1]
check(
    'one louvre panel covering the wall len x h',
    kinds_of(d).get('louvre_fins') == 1
    and lou['p']['w'] == ewall['p']['len']
    and lou['p']['h'] == 2.7
    and lou['p']['spacing'] == 0.4,
    txt,
)

txt, d = assistant('add_facade_bands', {'group': 'tower', 'kind': 'cornice', 'depth': 0.25}, drawing=d)
corn = [o for o in d.objs if o['kind'] == 'cornice']
# one band per wall of the group at that wall's top: the 12 storey walls (tops 2.7/5.4/8.1)
# plus the 4 parapet walls added above (h 1.0 on 8.1, so their top is 9.1).
check(
    'a cornice on every wall of the group, at its own top',
    len(corn) == 16 and sorted({o['y'] for o in corn}) == [2.7, 5.4, 8.1, 9.1],
    (len(corn), sorted({o['y'] for o in corn}), txt),
)
txt, d = assistant('add_pilasters', {'walls': [nwall['id']], 'spacing': 3}, drawing=d)
pil = [o for o in d.objs if o['kind'] == 'pilaster']
check('pilasters every 3 m on a 6 m wall -> 3', len(pil) == 3 and pil[0]['p']['w'] == 0.4, txt)

# refusals
txt, d = assistant('add_balconies', {'walls': 'no-such-group'}, drawing=d)
check('no walls -> refused', txt.startswith('refused'), txt)
txt, d = assistant('add_balconies', {'walls': 'tower', 'width': 40}, drawing=d)
check('absurd width -> refused', txt.startswith('refused'), txt)
txt, d = assistant('add_canopy', {'wall_id': bals[0]['id']}, drawing=d)
check('a canopy on a non-wall -> refused', txt.startswith('refused'), txt)
txt, d = assistant('add_canopy', {'wall_id': nwall['id'], 'kind': 'pergola'}, drawing=d)
check('unknown canopy kind -> refused', txt.startswith('refused'), txt)
txt, d = assistant('add_facade_bands', {'group': 'tower', 'kind': 'gutter'}, drawing=d)
check('unknown band kind -> refused', txt.startswith('refused'), txt)
txt, d = assistant('add_louvres', {'walls': 'tower', 'spacing': 0.001}, drawing=d)
check('absurd fin spacing -> refused', txt.startswith('refused'), txt)

# ── job 71ac02b0 replayed: the three calls that answered "added 0 balconies" ──
# The operator's 20-storey tower, its even storeys glazed, then the ledger's own
# three add_balconies calls in order. The third one — nine south curtain walls
# passed BY ID — hung nothing, because _walls dropped every non-wall kind and the
# storey rule was re-applied to a hand-picked list. See the module docstring.
print('the 20-storey tower (job 71ac02b0)')
txt, t = assistant(
    'draw_box',
    {
        'centre': 'FH100',
        'width': 20,
        'depth': 20,
        'storeys': 20,
        'roof': 'flat',
        'material': 'pht_rough_concrete',
        'name': 'tower',
    },
)
check('tower: 80 walls, 20 slabs', kinds_of(t).get('wall') == 80 and kinds_of(t).get('slab') == 20, txt)
txt, t = assistant(
    'add_curtain_wall',
    {
        'walls': 'tower',
        'storeys': [0, 2, 4, 6, 8, 10, 12, 14, 16, 18],
        'mullion': 1.5,
        'transom': 1.35,
        'name': 'tower_glazing',
    },
    drawing=t,
)
check('40 walls became curtain walls', kinds_of(t).get('curtain_wall') == 40, txt)

one, t = assistant(
    'add_balconies',
    {'walls': 'tower', 'sides': ['south'], 'storey_offset': 2, 'every_n_storeys': 2, 'width': 3.5, 'depth': 1.8},
    drawing=t,
)
check(
    'call 1 (walls="tower", every 2 from 2, but only ODD storeys are still walls) refuses, saying storey',
    one.startswith('refused') and ('storey' in one or 'curtain_wall' in one),
    one,
)
two, t = assistant(
    'add_balconies',
    {
        'walls': 'tower_glazing',
        'sides': ['south'],
        'storey_offset': 2,
        'every_n_storeys': 2,
        'width': 3.5,
        'depth': 1.8,
    },
    drawing=t,
)
check(
    'call 2 (walls="tower_glazing") adds balconies or refuses, saying storey/curtain_wall',
    two.startswith('refused') and ('storey' in two or 'curtain_wall' in two),
    two,
)
check(
    'neither call 1 nor call 2 opens with "added 0"',
    not one.startswith('added 0') and not two.startswith('added 0'),
    (one, two),
)

cw = [o for o in t.objs if o['kind'] == 'curtain_wall']
zmax = max(o['z'] for o in cw)
south = sorted([o for o in cw if abs(o['z'] - zmax) < 0.01], key=lambda o: o['y'])
south = [o for o in south if o['y'] > 2.6]  # the ledger's o112..o144: storeys 2..18
check(
    'nine south curtain walls, storeys 2..18',
    len(south) == 9 and [round(o['y'] / 2.7) for o in south] == [2, 4, 6, 8, 10, 12, 14, 16, 18],
    [o['id'] for o in south],
)

three, t = assistant(
    'add_balconies',
    {
        'walls': [o['id'] for o in south],
        'width': 4,
        'depth': 1.8,
        'rail_h': 1.1,
        'material': 'pht_rough_concrete',
        'name': 'south_balconies',
    },
    drawing=t,
)
bal3 = [o for o in t.objs if o['kind'] == 'balcony']
check(
    'call 3 (nine curtain walls by id) adds 9 balconies — was "added 0 ... skipped 11 walls"',
    len(bal3) == 9 and three.startswith('added 9'),
    three,
)
check('the message reports the width that was PASSED (4, not 3.5)', '4 x 1.8' in three, three)
check(
    'one balcony per storey at y = 2x2.7 .. 18x2.7',
    sorted(round(o['y'], 3) for o in bal3) == [round(s * 2.7, 3) for s in range(2, 19, 2)],
    sorted(o['y'] for o in bal3),
)
check(
    'each balcony carries the width, depth and rail it was given',
    all(o['p']['w'] == 4 and o['p']['d'] == 1.8 and o['p']['rail_h'] == 1.1 for o in bal3),
    bal3[0]['p'],
)
pairs = list(zip(south, sorted(bal3, key=lambda o: o['y'])))
check(
    'every balcony hangs OUTSIDE the south face (z greater than its curtain wall)',
    all(b['z'] > w['z'] + 0.01 for w, b in pairs),
    [(w['z'], b['z']) for w, b in pairs[:3]],
)
check(
    '...and is turned to project outward (ry flipped by PI from the south wall)',
    all(abs(abs(b['ry'] - w['ry']) - 3.141593) < 1e-4 for w, b in pairs),
    [(w['ry'], b['ry']) for w, b in pairs[:3]],
)

# THE RULE: a tool that made 0 records refuses — it never answers "added 0" / "placed 0".
print('nothing made -> refused (never "added 0" / "placed 0")')
NOTHING = [
    ('add_balconies', {'walls': 'no-such-group'}),
    ('add_balconies', {'walls': 'tower', 'sides': ['north'], 'storey_offset': 40}),
    ('add_louvres', {'walls': 'no-such-group'}),
    ('add_facade_bands', {'group': 'no-such-group', 'kind': 'cornice'}),
    # "wall" selects the kind: after glazing, only the ODD storeys are still
    # walls, and no odd storey is divisible by 97 — so nothing can be banded.
    ('add_facade_bands', {'group': 'wall', 'kind': 'cornice', 'every_n_storeys': 97}),
    ('add_pilasters', {'walls': 'no-such-group'}),
    ('add_parapet', {'group': 'no-such-group'}),
    ('add_special_openings', {'walls': 'no-such-group', 'kind': 'window_arch'}),
    ('add_special_openings', {'walls': 'tower', 'kind': 'window_arch', 'storey_offset': 40}),
    ('add_special_openings', {'walls': 'tower', 'kind': 'window_strip', 'width': 19.5, 'per_wall': 2}),
    ('add_curtain_wall', {'walls': 'no-such-group'}),
    ('add_curtain_wall', {'walls': 'tower', 'storeys': [77]}),
    ('add_vehicles', {'cell_from': 'A1', 'cell_to': 'A2', 'kind': 'bus', 'count': 2}),
    ('park_cars', {'cells': ['not-a-cell', '???']}),
    ('add_construction_site', {'cell_from': 'A1', 'cell_to': 'B2'}),
    (
        'add_construction_site',
        {
            'cell_from': 'A1',
            'cell_to': 'T20',
            'crane': False,
            'containers': 0,
            'pallets': 0,
            'skip': False,
            'scaffold_group': 'no-such-group',
        },
    ),
]
for i, (tool, args) in enumerate(NOTHING):
    r, t = assistant(tool, args, drawing=t)
    k = list(args)[0]
    check(
        f'{i + 1}. {tool}({k}={args[k]}) -> refused, never "added 0"/"placed 0"',
        r.startswith('refused') and not r.startswith('added') and not r.startswith('placed'),
        r,
    )
    check(f'   ...and that refusal names a cause and a call that works ({tool})', len(r) > 60 and ' — ' in r, r)

# ── the porte-cochere joint (job 71ac02b0): the plate ran into the facade ─────
# with no joint at all. add_canopy now lands an edge beam along the wall face.
print('canopy edge beam')
txt, c = assistant(
    'draw_box',
    {
        'centre': 'FH100',
        'width': 20,
        'depth': 20,
        'storeys': 20,
        'roof': 'flat',
        'material': 'pht_rough_concrete',
        'name': 'tower',
    },
)
txt, c = assistant(
    'add_opening',
    {'group': 'tower', 'side': 'south', 'storey': 0, 'kind': 'double_door', 'width': 2.4, 'height': 3},
    drawing=c,
)
cn, c = assistant(
    'add_canopy',
    {'group': 'tower', 'side': 'south', 'storey': 0, 'width': 12, 'depth': 5, 'height': 4.2, 'columns': 4},
    drawing=c,
)
hostw = [o for o in c.objs if o['kind'] == 'wall' and o['name'] == 'south wall st0'][0]
plate = [o for o in c.objs if o['kind'] == 'canopy']
beams = [o for o in c.objs if o['name'] == 'canopy beam']
cols = [o for o in c.objs if o['kind'] == 'column_round' and o['name'].startswith('canopy column')]
check('one canopy plate and exactly one edge beam', len(plate) == 1 and len(beams) == 1, (cn, len(plate), len(beams)))
check('the canopy still has 4 columns', len(cols) == 4, [o['id'] for o in cols])
beam, plate = beams[0], plate[0]
check("the edge beam is a kind the tab and Blender both draw ('beam')", beam['kind'] == 'beam', beam)
check(
    'the beam spans the canopy width (len 12) and is 0.35 m deep, 0.4 m thick',
    beam['p'] == {'len': 12.0, 'w': 0.4, 'h': 0.35},
    beam['p'],
)
# the wall's OUTER face: the wall line pushed out by t/2, away from the tower centre
gx = sum(o['x'] for o in c.objs if o['grp'] == 'tower') / sum(1 for o in c.objs if o['grp'] == 'tower')
gz = sum(o['z'] for o in c.objs if o['grp'] == 'tower') / sum(1 for o in c.objs if o['grp'] == 'tower')
sgn = 1.0 if hostw['z'] > gz else -1.0
facex, facez = hostw['x'], hostw['z'] + sgn * hostw['p']['t'] / 2
check(
    'the plate starts on that outer face',
    abs(plate['x'] - facex) < 1e-6 and abs(plate['z'] - facez) < 1e-6,
    (plate['x'], plate['z'], facex, facez),
)
dist = ((beam['x'] - facex) ** 2 + (beam['z'] - facez) ** 2) ** 0.5
check('the beam is within 0.2 m of the wall face (its inner side flush against it)', dist <= 0.201, dist)
check(
    '...on the outward side of that face, not inside the building',
    (beam['z'] - facez) * sgn > 0,
    (beam['z'], facez, sgn),
)
check(
    'the beam sits at the soffit (same y as the plate, 4.2 m)',
    abs(beam['y'] - plate['y']) < 1e-9 and abs(beam['y'] - 4.2) < 1e-9,
    (beam['y'], plate['y']),
)
check(
    'the beam is turned with the plate and lives in the canopy group',
    abs(beam['ry'] - plate['ry']) < 1e-9 and beam['grp'] == plate['grp'] == hostw['grp'],
    (beam['ry'], plate['ry'], beam['grp'], plate['grp']),
)
check(
    'the reply says the canopy is joined to the wall with a 0.35 m edge beam',
    f'joined to wall {hostw["id"]} with a 0.35 m edge beam' in cn,
    cn,
)
check(
    'the columns still stand under the outer edge, not at the wall',
    all((o['z'] - facez) * sgn > 4.0 for o in cols),
    [(o['id'], o['z']) for o in cols],
)
aw, c = assistant(
    'add_canopy',
    {'group': 'tower', 'side': 'north', 'storey': 0, 'kind': 'awning', 'width': 3, 'depth': 1.2},
    drawing=c,
)
check(
    'an awning gets no edge beam (it is a sloped bracket, not a plate)',
    not aw.startswith('refused') and len([o for o in c.objs if o['name'] == 'canopy beam']) == 1,
    aw,
)

txt, d = assistant('add_object', {'kind': 'sunshade', 'cell': 'A1', 'params': {'w': 4}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'sunshade' and d.objs[-1]['p']['w'] == 4, txt)
check('rail lists all nine kinds', rail_has(KINDS9) == [], rail_has(KINDS9))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'balcony', 'p': {'w': 2.4, 'd': 1.2, 't': 0.18, 'rail_h': 1.0, 'post': 0.04}},
    {'kind': 'canopy', 'p': {'w': 3, 'd': 1.5, 't': 0.12, 'h_drop': 0}},
    {'kind': 'awning', 'p': {'w': 3, 'd': 1.2, 'angle': 20}},
    {'kind': 'cornice', 'p': {'len': 4, 'h': 0.3, 'd': 0.25}},
    {'kind': 'pilaster', 'p': {'h': 2.7, 'w': 0.4, 'd': 0.12}},
    {'kind': 'louvre_fins', 'p': {'w': 6, 'h': 2.7, 'fin': 0.3, 'spacing': 0.4, 't': 0.03}},
    {'kind': 'sunshade', 'p': {'w': 3, 'd': 0.8, 't': 0.05, 'slats': 8}},
    {'kind': 'string_course', 'p': {'len': 4, 'h': 0.12, 'd': 0.08}},
    {'kind': 'parapet_cap', 'p': {'len': 4, 'w': 0.3, 't': 0.06}},
]
b = browser_kinds(cases)
byk = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])


def sized(kind, sx, sy, sz, tol=0.02):
    r = byk.get(kind) or {}
    ok = bool(r.get('ok')) and r.get('size') and all(abs(r['size'][i] - v) < tol for i, v in enumerate((sx, sy, sz)))
    return check(f'{kind} builds, {sx} x {sy} x {sz} m', ok, r)


sized('balcony', 2.4, 1.18, 1.2)  # slab t 0.18 + rail 1.0 tall, w x d in plan
sized('canopy', 3.0, 0.12, 1.5)
sized('awning', 3.0, 1.2 * 0.36397 + 0.04, 1.2, 0.03)  # d*tan(20) drop + 0.04 plate
sized('cornice', 4.0, 0.3, 0.25)
sized('pilaster', 0.4, 2.7, 0.12)
sized('louvre_fins', 6.0, 2.7, 0.3)
sized('sunshade', 3.0, 0.05, 0.8)
sized('string_course', 4.0, 0.12, 0.08)
sized('parapet_cap', 4.0, 0.06, 0.3)
lf = byk.get('louvre_fins') or {}
check('louvre_fins w 6 spacing 0.4 -> a fin every 0.4 m', lf.get('parts', 0) >= 14 or lf.get('tris', 0) >= 14 * 12, lf)
check(
    'the balcony projects to -z (away from the wall) and stands on y=0',
    byk['balcony']['min'][2] < -1.19 and abs(byk['balcony']['min'][1]) < 1e-3,
    byk['balcony'],
)
check(
    'labels',
    byk['balcony']['label'] == 'Balcony' and byk['louvre_fins']['label'] == 'Louvre fins',
    (byk['balcony']['label'], byk['louvre_fins']['label']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kind in KINDS9:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
check('blender balcony is more than one box', bl.get('balcony', {}).get('polys', 0) > 6, bl.get('balcony'))
finish()
