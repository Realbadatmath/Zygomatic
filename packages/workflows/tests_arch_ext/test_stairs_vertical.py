# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_stairs_vertical.py — proof for the stairs_vertical family.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_stairs_vertical.py
"""

# re-verified 2026-09-07 after the harness serialised Blender
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

NEW_KINDS = [
    'stair_u',
    'stair_winder',
    'stair_landing',
    'elevator_shaft',
    'elevator_car',
    'escalator',
    'fire_stair_exterior',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('add_stair', 'add_elevator', 'add_fire_escape', 'add_escalator')),
    names,
)

# A stair is a piece of a building now: it needs a shell to stand in, one record
# per storey, and a hole through every floor it passes. The shell comes first.
txt, d = assistant(
    'draw_box', {'centre': 'H12', 'width': 20, 'depth': 20, 'storeys': 4, 'roof': 'flat', 'name': 'block'}
)
check('a shell for the stairs to stand in', kinds_of(d).get('slab') == 4, txt)

txt, d = assistant('add_stair', {'cell': 'H12', 'from_storey': 0, 'to_storey': 2, 'kind': 'u'}, drawing=d)
us = [x for x in d.objs if x['kind'] == 'stair_u']
p = us[0]['p']
check('add_stair u drew one stair_u per storey', len(us) == 2 and [x['y'] for x in us] == [0.0, 2.7], txt)
check(
    'steps * rise == 2.7 exactly, one storey per record',
    all(abs(x['p']['steps'] * x['p']['rise'] - 2.7) < 1e-6 for x in us),
    (p, txt),
)
check('rise within the 0.19 limit', p['rise'] <= 0.19, p)

txt, d = assistant(
    'add_stair',
    {'cell': 'H12', 'from_storey': 1, 'to_storey': 2, 'kind': 'spiral', 'width': 1.1, 'direction_deg': 90},
    drawing=d,
)
sp = [x for x in d.objs if x['kind'] == 'stair_spiral'][-1]
check(
    'spiral uses stair_spiral, r_out = width + 0.2, y = storey 1',
    sp['kind'] == 'stair_spiral'
    and abs(sp['p']['r_out'] - 1.3) < 1e-9
    and abs(sp['y'] - 2.7) < 1e-9
    and abs(sp['ry'] - 1.5707963) < 1e-5,
    (sp, txt),
)
check('spiral rise lands on the floor', abs(sp['p']['steps'] * sp['p']['rise'] - 2.7) < 1e-6, sp['p'])

txt, d = assistant('add_stair', {'cell': 'H12', 'from_storey': 0, 'to_storey': 1, 'kind': 'straight'}, drawing=d)
check('straight uses the built-in kind', kinds_of(d).get('stair_straight') == 1, txt)

txt, d = assistant('add_stair', {'cell': 'H12', 'from_storey': 2, 'to_storey': 2}, drawing=d)
check('a stair that does not climb is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_stair', {'cell': 'H12', 'kind': 'helical'}, drawing=d)
check('an unknown stair kind is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_stair', {'cell': 'ZZ9'}, drawing=d)
check('an off-grid cell is refused', txt.startswith('refused'), txt)

txt, d = assistant('add_elevator', {'cell': 'K18', 'from_storey': 0, 'to_storey': 2}, drawing=d)
shaft = [x for x in d.objs if x['kind'] == 'elevator_shaft'][-1]
car = [x for x in d.objs if x['kind'] == 'elevator_car'][-1]
check('add_elevator drew a shaft and a car', shaft['kind'] == 'elevator_shaft' and car['kind'] == 'elevator_car', txt)
# 3 served storeys reach 3 * 2.7 = 8.1 m, and the motor room's 1.5 m sits on top
check(
    'shaft = (to - from + 1) * 2.7 + the 1.5 m overrun = 9.6',
    abs(shaft['p']['h'] - 9.6) < 1e-6
    and shaft['p']['overrun'] == 1.5
    and shaft['p']['w'] == 1.8
    and shaft['p']['d'] == 2.0,
    shaft['p'],
)
check(
    'a door on every served storey, on the south face by default',
    shaft['p']['doors'] == [0, 1, 2] and shaft['p']['door_side'] == 'south' and abs(shaft['p']['sh'] - 2.7) < 1e-9,
    shaft['p'],
)
check('the reply counts the doors and the overrun', '3 doors' in txt and 'south' in txt and 'overrun 1.5' in txt, txt)
check(
    'car sits at the bottom storey, inside the shaft',
    car['y'] == 0.0 and car['p']['w'] < shaft['p']['w'] and car['p']['d'] < shaft['p']['d'],
    (car['p'], shaft['p']),
)
lift_v = [v for v in (d.ext.get('slab_voids') or []) if v['reason'] == 'lift']
check(
    'a floor opening in every slab the shaft passes, 1..3',
    sorted(v['storey'] for v in lift_v) == [1, 2, 3],
    [(v['storey'], v['reason']) for v in lift_v],
)
txt, d = assistant('add_elevator', {'cell': 'K18', 'from_storey': 3, 'to_storey': 1}, drawing=d)
check('a lift that runs downwards is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_elevator', {'cell': 'K18', 'w': 0.2}, drawing=d)
check('a 0.2 m shaft is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_elevator', {'cell': 'K18', 'door_side': 'up'}, drawing=d)
check('a door_side that is not a compass side is refused', txt.startswith('refused') and 'north' in txt, txt)
txt, _ = assistant('add_elevator', {'cell': 'A1', 'from_storey': 0, 'to_storey': 2}, drawing=d)
check(
    'a lift outside every building is refused, and says to draw the shell',
    txt.startswith('refused') and 'draw_box' in txt,
    txt,
)

txt, d = assistant('add_fire_escape', {'cell': 'B44', 'storeys': 4, 'direction_deg': 180, 'width': 1.2}, drawing=d)
fe = d.objs[-1]
check(
    'a fire escape on open ground still draws, 4 storeys',
    fe['kind'] == 'fire_stair_exterior'
    and fe['p']['storeys'] == 4
    and fe['p']['h'] == 2.7
    and fe['y'] == 0.0
    and abs(fe['ry'] - 3.14159265) < 1e-5,
    (fe, txt),
)
txt, d = assistant('add_fire_escape', {'cell': 'B44', 'storeys': 0}, drawing=d)
check('a 0-storey fire escape is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_fire_escape', {}, drawing=d)
check(
    'a fire escape with no facade and no cell is refused, naming group + side',
    txt.startswith('refused') and 'group=' in txt and 'side=' in txt,
    txt,
)

txt, d = assistant('add_escalator', {'cell': 'F9', 'from_storey': 0, 'to_storey': 1, 'direction_deg': 90}, drawing=d)
es = d.objs[-1]
check(
    'add_escalator drew one escalator, rise = one storey',
    es['kind'] == 'escalator' and abs(es['p']['rise'] - 2.7) < 1e-6 and es['p']['angle'] == 30,
    (es, txt),
)
txt, d = assistant('add_escalator', {'cell': 'F9', 'from_storey': 1, 'to_storey': 0}, drawing=d)
check('a descending escalator is refused', txt.startswith('refused'), txt)
txt, d = assistant('add_escalator', {'cell': 'F9', 'angle': 70}, drawing=d)
check('a 70 degree escalator is refused', txt.startswith('refused'), txt)
# a span of storeys is a BANK of one-storey flights, not one 14 m ramp
n_before = len(d.objs)
txt, d = assistant('add_escalator', {'cell': 'F9', 'from_storey': 0, 'to_storey': 4}, drawing=d)
bank = d.objs[n_before:]
check(
    'a 4-storey escalator is 4 flights of one storey, stacked',
    len(bank) == 4
    and all(abs(x['p']['rise'] - 2.7) < 1e-6 for x in bank)
    and [round(x['y'], 4) for x in bank] == [0.0, 2.7, 5.4, 8.1],
    (len(bank), [x['y'] for x in bank], txt),
)
check(
    'the flights reverse storey by storey, so the bank keeps one footprint',
    len({(x['x'], x['z']) for x in bank}) == 1
    and all(abs(abs(bank[i + 1]['ry'] - bank[i]['ry']) - math.pi) < 1e-6 for i in range(3)),
    [(x['x'], x['z'], round(x['ry'], 4)) for x in bank],
)

txt, d = assistant('add_object', {'kind': 'stair_landing', 'cell': 'A1', 'params': {'w': 1.4, 'd': 1.6}}, drawing=d)
check('add_object knows the new kinds', d.objs[-1]['kind'] == 'stair_landing' and d.objs[-1]['p']['w'] == 1.4, txt)
check('rail lists the kinds', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))

# ── the stack: one record per storey, openings, head house ───────────────────
# The bug this proves gone: add_stair(FH96, 0 -> 19) drew ONE 39.8 m flight of
# 285 steps straight through 19 slabs and out through the east wall.
print('stair stack')
from zyg_workflows import arch_assistant as A  # noqa: E402  (extensions are loaded by the first assistant() call)

E, V = A.EXT_MODULES['envelope_rules'], A.EXT_MODULES['slab_voids']


def tower():
    return assistant(
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
    )[1]


txt, t20 = assistant(
    'add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 20, 'kind': 'u', 'width': 1.2}, drawing=tower()
)
st = [x for x in t20.objs if x['kind'] == 'stair_u']
check('to the deck: 20 stair_u records, not one 54 m flight', len(st) == 20, txt)
check(
    'one per storey at y = 0, 2.7 .. 51.3',
    all(abs(x['y'] - i * 2.7) < 0.01 for i, x in enumerate(st)),
    [x['y'] for x in st],
)
check(
    'every record is one storey of flight, never 285 steps (the top one climbs to the 54.3 m deck)',
    all(x['p']['steps'] <= 18 and 2.7 - 1e-6 <= x['p']['steps'] * x['p']['rise'] <= 3.0 + 1e-6 for x in st),
    [(x['p']['steps'], x['p']['rise']) for x in st[:3]] + [(st[-1]['p']['steps'], st[-1]['p']['rise'])],
)
check(
    'the top record lands on the deck: 51.3 + its climb = 54.3',
    abs(st[-1]['y'] + st[-1]['p']['steps'] * st[-1]['p']['rise'] - 54.3) < 0.01,
    st[-1]['y'] + st[-1]['p']['steps'] * st[-1]['p']['rise'],
)
check('every record carries rails', all(x['p']['rails'] == 1 for x in st), [x['p'].get('rails') for x in st])
check(
    'the whole stack shares one group and one plan position',
    len({x['grp'] for x in st}) == 1 and len({(x['x'], x['z']) for x in st}) == 1,
    sorted({x['grp'] for x in st}),
)
check(
    'the reply names the record range and the head house',
    'o' in txt and 'head house' in txt and 'floor opening' in txt,
    txt,
)

voids = t20.ext.get('slab_voids') or []
check(
    'a floor opening per storey climbed to, 1..20',
    len(voids) == 20 and sorted(v['storey'] for v in voids) == list(range(1, 21)),
    [v['storey'] for v in voids],
)
check(
    'every opening is cut for the stair, in the tower',
    all(v['reason'] == 'stair' and v['group'] == 'tower' for v in voids),
    voids[:1],
)
# 2026-09-11: the top flight climbs to the deck (3.0 m, 17 steps) and is the longest
# record, so the opening and the head house follow the UNION of first and last
_b0, _bt = E.bbox_of(st[0]), E.bbox_of(st[-1])
bb0 = (min(_b0[0], _bt[0]), min(_b0[1], _bt[1]), max(_b0[2], _bt[2]), max(_b0[3], _bt[3]))
check(
    'the opening is the stair plan + 0.05 m all round',
    all(
        abs(v['xmin'] - (bb0[0] - 0.05)) < 1e-6
        and abs(v['xmax'] - (bb0[2] + 0.05)) < 1e-6
        and abs(v['zmin'] - (bb0[1] - 0.05)) < 1e-6
        and abs(v['zmax'] - (bb0[3] + 0.05)) < 1e-6
        for v in voids
    ),
    (voids[0]['xmin'], voids[0]['xmax'], bb0),
)
check(
    'the last opening goes through the roof deck itself',
    voids[-1]['orig']['kind'] == 'roof_flat',
    voids[-1]['orig']['kind'],
)
check('the voids register is consistent', V.check_voids(t20) == [], V.check_voids(t20))
check('nothing pokes out of the envelope', E.check_envelope(t20) == [], E.check_envelope(t20))

hh = [x for x in t20.objs if x['grp'].endswith('head house')]
hk = {k: sum(1 for x in hh if x['kind'] == k) for k in {x['kind'] for x in hh}}
check('the head house is 4 walls, a roof and a door', hk == {'wall': 4, 'roof_flat': 1, 'door': 1}, hk)
check(
    'the head house stands on the deck at 54.3 m',
    hh and all(x['y'] >= 54.3 - 0.01 for x in hh),
    [(x['kind'], x['y']) for x in hh],
)
check(
    'the head house is 2.7 m of headroom with a 2.1 m door',
    all(x['p']['h'] == 2.7 for x in hh if x['kind'] == 'wall')
    and [x['p'] for x in hh if x['kind'] == 'door'][0]['h'] == 2.1,
    [x['p'] for x in hh],
)
check(
    'the head house encloses the stair plan + 0.6 m',
    all(abs(x['p']['len'] - (bb0[2] - bb0[0] + 1.2)) < 1e-3 for x in hh if x['kind'] == 'wall' and x['ry'] == 0.0),
    [x['p']['len'] for x in hh if x['kind'] == 'wall'],
)
check(
    'the head house takes the tower finishes, walls and roof apart',
    all(x['mat'] == 'pht_rough_concrete' for x in hh if x['kind'] == 'wall')
    and [x['mat'] for x in hh if x['kind'] == 'roof_flat'] == ['pht_bitumen'],
    [(x['kind'], x['mat']) for x in hh],
)

# the call the ledger actually made — one storey short of the deck
txt, t19 = assistant(
    'add_stair',
    {'cell': 'FH96', 'from_storey': 0, 'to_storey': 19, 'kind': 'u', 'width': 1.2, 'material': 'mat_concrete'},
    drawing=tower(),
)
st19 = [x for x in t19.objs if x['kind'] == 'stair_u']
check("the ledger's own call draws 19 records, one per storey", len(st19) == 19, txt)
check(
    'none of the 19 is more than 5 m across in plan',
    all(max(E.bbox_of(x)[2] - E.bbox_of(x)[0], E.bbox_of(x)[3] - E.bbox_of(x)[1]) <= 5.0 for x in st19),
    [round(E.bbox_of(st19[0])[2] - E.bbox_of(st19[0])[0], 2)],
)
check(
    'a stair that stops at the top floor builds no head house',
    not any(x['grp'].endswith('head house') for x in t19.objs),
    txt,
)
check(
    'it still cuts 19 floors and leaves the roof whole',
    len(t19.ext.get('slab_voids') or []) == 19 and all(v['orig']['kind'] == 'slab' for v in t19.ext['slab_voids']),
    [v['storey'] for v in t19.ext.get('slab_voids') or []],
)

txt, _ = assistant('add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 3, 'kind': 'straight'}, drawing=tower())
check(
    'a straight flight over 3 storeys is refused, and says which kind works',
    txt.startswith('refused') and 'kind="u"' in txt,
    txt,
)
txt, _ = assistant(
    'add_stair',
    {'cell': 'FP100', 'from_storey': 0, 'to_storey': 2, 'kind': 'u', 'width': 1.2, 'direction_deg': 0},
    drawing=tower(),
)
check(
    'a stair 1 m off the east wall is refused, naming the facade and a direction that fits',
    txt.startswith('refused') and 'east' in txt and 'direction_deg=90' in txt,
    txt,
)
txt, _ = assistant('add_stair', {'cell': 'A1', 'from_storey': 0, 'to_storey': 2, 'kind': 'u'}, drawing=tower())
check(
    'a stair outside every building is refused, and says to draw the shell',
    txt.startswith('refused') and 'draw_box' in txt,
    txt,
)
txt, _ = assistant('add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 21, 'kind': 'u'}, drawing=tower())
check(
    'to_storey above the roof deck is refused, naming the storey count',
    txt.startswith('refused') and '20 storeys' in txt,
    txt,
)
txt, _ = assistant('add_stair', {'cell': 'FH96', 'from_storey': 20, 'to_storey': 21, 'kind': 'u'}, drawing=tower())
check('from_storey above the top floor is refused', txt.startswith('refused'), txt)

# ── the lifts: doors, overrun, floor openings ────────────────────────────────
# The bug this proves gone: two 54 m shafts of solid concrete, no door on any
# storey, no overrun for the motor room, and not one hole cut in a floor.
print('lifts')
txt, lift = assistant(
    'add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 20, 'kind': 'u', 'width': 1.2}, drawing=tower()
)
# FD96 / FK96, not FF96 / FJ96: a 1.2 m u stair at FH96 is 3.44 m across in plan
# and needs 1.2 m of floor at its foot, so those two cells are now refused (the
# defect live run 038ca075c052 drew). The clear cells the refusal names are these.
txt, lift = assistant('add_elevator', {'cell': 'FD96', 'from_storey': 0, 'to_storey': 20}, drawing=lift)
sh1 = [x for x in lift.objs if x['kind'] == 'elevator_shaft'][-1]
check(
    'a lift to the deck has a door on all 21 served storeys',
    len(sh1['p']['doors']) == 21 and sh1['p']['doors'] == list(range(0, 21)),
    sh1['p']['doors'],
)
check('the overrun is 1.5 m of motor room', sh1['p']['overrun'] == 1.5, sh1['p'])
check(
    'the shaft clears the 54.3 m deck by the overrun',
    sh1['y'] + sh1['p']['h'] >= 54.3 + 1.5 - 0.01,
    (sh1['y'], sh1['p']['h']),
)
check(
    'the reply names the deck, the door count, the face and the overrun',
    '21 doors' in txt and '(deck)' in txt and 'south face' in txt and 'overrun 1.5' in txt and 'the roof' in txt,
    txt,
)
lv = [v for v in (lift.ext.get('slab_voids') or []) if v['reason'] == 'lift']
check(
    "a 'lift' opening in every floor storeys 1..20, the roof included",
    sorted(v['storey'] for v in lv) == list(range(1, 21)),
    [v['storey'] for v in lv],
)
check(
    'the top opening goes through the roof deck itself, for the motor room',
    [v for v in lv if v['storey'] == 20][0]['orig']['kind'] == 'roof_flat',
    [v['orig']['kind'] for v in lv if v['storey'] == 20],
)
check('the deck is opened for the shaft', V.voids_at(lift, 'tower', 20) != [], V.voids_at(lift, 'tower', 20))
txt, lift = assistant('add_elevator', {'cell': 'FK96', 'from_storey': 0, 'to_storey': 20}, drawing=lift)
check('a stair and two lifts leave the voids register consistent', V.check_voids(lift) == [], V.check_voids(lift))
check('a stair and two lifts poke out of nothing', E.check_envelope(lift) == [], E.check_envelope(lift))
txt, _ = assistant('add_elevator', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 21}, drawing=tower())
check(
    'a lift above the roof deck is refused, naming the storey count',
    txt.startswith('refused') and '20 storeys' in txt,
    txt,
)
txt, _ = assistant(
    'add_elevator', {'cell': 'FP100', 'from_storey': 0, 'to_storey': 2, 'w': 4, 'depth': 4}, drawing=tower()
)
check('a shaft crossing a facade is refused, naming the side', txt.startswith('refused') and 'east' in txt, txt)

# ── the fire escape hangs on a FACADE ────────────────────────────────────────
# The bug this proves gone: add_fire_escape(cell='FH91') put a steel escape stair
# in the middle of the offices, on the plan, inside the tower.
print('fire escape')
env20 = E.group_envelope(lift, 'tower')
txt, fesc = assistant('add_fire_escape', {'group': 'tower', 'side': 'north', 'storeys': 20}, drawing=lift)
fe20 = [x for x in fesc.objs if x['kind'] == 'fire_stair_exterior'][-1]
check('the escape covers the whole tower', fe20['p']['storeys'] == 20 and fe20['y'] == 0.0, (fe20['p'], fe20['y']))
check(
    'it stands OUTSIDE the envelope',
    E.inside(env20, fe20['x'], fe20['z']) is False,
    (fe20['x'], fe20['z'], env20['zmin']),
)
fbb = E.bbox_of(fe20)
check(
    'and against the north facade',
    E.touches_facade(env20, fe20['x'], fbb[3]) == 'north',
    (fbb, E.touches_facade(env20, fe20['x'], fbb[3])),
)
check('its flights run ALONG the facade, not out of it', fbb[2] - fbb[0] > fbb[3] - fbb[1], fbb)
check(
    'the reply names the facade wall and the side',
    'north' in txt and ('wall o' in txt) and str(fe20['p']['w']) in txt,
    txt,
)
check('an outside stair on a facade breaks no envelope rule', E.check_envelope(fesc) == [], E.check_envelope(fesc))
txt, _ = assistant('add_fire_escape', {'cell': 'FH91', 'storeys': 20}, drawing=lift)
check(
    "the ledger's own call is refused because FH91 is INSIDE the tower",
    txt.startswith('refused') and 'inside' in txt and 'add_fire_escape(group="tower"' in txt,
    txt,
)
txt, _ = assistant('add_fire_escape', {'group': 'tower', 'side': 'up'}, drawing=lift)
check('a side that is not a compass side is refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_fire_escape', {'group': 'no such block', 'side': 'north'}, drawing=lift)
check('a group with no wall is refused', txt.startswith('refused'), txt)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'stair_u', 'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'gap': 0.2}},
    {'kind': 'stair_winder', 'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'turn': 90}},
    {'kind': 'stair_landing', 'p': {'w': 1.2, 'd': 1.6, 't': 0.15}},
    {'kind': 'elevator_shaft', 'p': {'w': 1.8, 'd': 2.0, 'h': 8.1, 't': 0.2}},
    {'kind': 'elevator_car', 'p': {'w': 1.6, 'd': 1.8, 'h': 2.2, 'door': 1}},
    {'kind': 'escalator', 'p': {'rise': 2.7, 'w': 1.0, 'angle': 30, 'rail_h': 0.9}},
    {'kind': 'fire_stair_exterior', 'p': {'storeys': 3, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18}},
]
# the same two stairs again with rails on — an open flight edge is a fall
RAILED = [
    {'kind': 'stair_u', 'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'gap': 0.2, 'rails': 1}},
    {'kind': 'stair_winder', 'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'turn': 90, 'rails': 1}},
]
# and the same shaft with the doors the tool now writes — the shaft above is the
# one job 71ac02b0 built: a tube with no way in
DOORED = [
    {
        'kind': 'elevator_shaft',
        'p': {'w': 1.8, 'd': 2.0, 'h': 8.1, 't': 0.2, 'doors': [0, 1, 2], 'door_side': 'south', 'sh': 2.7},
    },
    {
        'kind': 'elevator_shaft',
        'p': {'w': 1.8, 'd': 2.0, 'h': 8.1, 't': 0.2, 'doors': [0, 1, 2], 'door_side': 'east', 'sh': 2.7},
    },
]
b_all = browser_kinds(cases + RAILED + DOORED)
b, b_rail, b_door = b_all[: len(cases)], b_all[len(cases) : len(cases) + len(RAILED)], b_all[len(cases) + len(RAILED) :]
by = {c['kind']: r for c, r in zip(cases, b)}
check('no page errors', not any(x.get('page_errors') for x in b_all), [x.get('page_errors') for x in b_all])
check(
    'every kind builds real geometry',
    all(x['ok'] and x['registered'] for x in b_all),
    [(x['kind'], x['ok'], x['registered'], x['err']) for x in b_all],
)

u = by['stair_u']
check(
    'stair_u is steps*rise tall and 2w+gap across',
    abs(u['size'][1] - 16 * 0.175) < 1e-3 and abs(u['size'][2] - 2.2) < 1e-3,
    u,
)
w_ = by['stair_winder']
check(
    'stair_winder is steps*rise tall and turns out of the X axis',
    abs(w_['size'][1] - 16 * 0.175) < 1e-3 and w_['size'][2] > 1.2,
    w_,
)
la = by['stair_landing']
check(
    'stair_landing is w x t x d',
    abs(la['size'][0] - 1.2) < 1e-3 and abs(la['size'][1] - 0.15) < 1e-3 and abs(la['size'][2] - 1.6) < 1e-3,
    la,
)
sh = by['elevator_shaft']
check(
    'elevator_shaft bbox is 1.8 x 8.1 x 2',
    abs(sh['size'][0] - 1.8) < 1e-3 and abs(sh['size'][1] - 8.1) < 1e-3 and abs(sh['size'][2] - 2.0) < 1e-3,
    sh,
)
ca = by['elevator_car']
check(
    'elevator_car bbox is w x h x d',
    abs(ca['size'][0] - 1.6) < 1e-3 and abs(ca['size'][1] - 2.2) < 1e-3 and abs(ca['size'][2] - 1.8) < 1e-3,
    ca,
)
es_b = by['escalator']
check(
    'escalator run = rise/tan(30) = 4.68 m, w wide',
    abs(es_b['size'][0] - 2.7 / math.tan(math.radians(30))) < 0.02 and abs(es_b['size'][2] - 1.0) < 1e-3,
    es_b,
)
fs = by['fire_stair_exterior']
check(
    'fire escape is storeys*h tall, w deep', abs(fs['size'][1] - 3 * 2.7) < 1e-3 and abs(fs['size'][2] - 1.2) < 1e-3, fs
)
check(
    'labels',
    u['label'] == 'U stair' and sh['label'] == 'Lift shaft' and es_b['label'] == 'Escalator',
    (u['label'], sh['label'], es_b['label']),
)

ru, rw = b_rail
check(
    'rails stand 1 m over the top step of a U stair', ru['size'][1] >= 16 * 0.175 + 1.0 - 1e-3, (ru['size'], u['size'])
)
check('rails are real posts and a bar, not a taller box', ru['tris'] > u['tris'], (ru['tris'], u['tris']))
check(
    'rails stand 1 m over the top step of a winder', rw['size'][1] >= 16 * 0.175 + 1.0 - 1e-3, (rw['size'], w_['size'])
)
check('the winder rail follows the turn', rw['tris'] > w_['tris'], (rw['tris'], w_['tris']))

ds, de = b_door
check(
    'three lift doors are real geometry the doorless shaft has not', ds['tris'] > sh['tris'], (sh['tris'], ds['tris'])
)
check(
    'the doors are recessed, so the shaft bbox is still 1.8 x 8.1 x 2',
    abs(ds['size'][0] - 1.8) < 1e-3 and abs(ds['size'][1] - 8.1) < 1e-3 and abs(ds['size'][2] - 2.0) < 1e-3,
    ds['size'],
)
check(
    'doors on the east face build the same count on the other axis',
    de['tris'] == ds['tris'] and de['parts'] == ds['parts'],
    (ds['parts'], de['parts']),
)
check('a doored shaft is 4 walls + 2 leaves per storey', ds['parts'] == 4 + 6, ds['parts'])

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for k in NEW_KINDS:
    check(f'blender builds {k}', bl.get(k, {}).get('polys', 0) > 0, bl.get(k))
bl_door = blender_kinds(DOORED[:1])
check(
    'blender builds the lift doors too, same recessed bbox',
    bl_door.get('elevator_shaft', {}).get('polys', 0) > bl['elevator_shaft']['polys']
    and abs(bl_door['elevator_shaft']['size'][0] - 1.8) < 1e-3
    and abs(bl_door['elevator_shaft']['size'][2] - 2.0) < 1e-3,
    (bl_door.get('elevator_shaft'), bl['elevator_shaft']),
)
bl_rail = blender_kinds(RAILED)
check(
    'blender builds the U stair rail too',
    bl_rail.get('stair_u', {}).get('polys', 0) > bl['stair_u']['polys']
    and bl_rail['stair_u']['size'][1] >= 16 * 0.175 + 1.0 - 1e-3,
    (bl_rail.get('stair_u'), bl['stair_u']),
)
check(
    'blender builds the winder rail too',
    bl_rail.get('stair_winder', {}).get('polys', 0) > bl['stair_winder']['polys']
    and bl_rail['stair_winder']['size'][1] >= 16 * 0.175 + 1.0 - 1e-3,
    (bl_rail.get('stair_winder'), bl['stair_winder']),
)

# ── two cores may not occupy one plan (2026-09-12) ───────────────────────────
# Live run 038ca075c052: add_stair(FH93, u, 1.2) = 3.44 x 2.60 m in plan
# (x 11.78..15.22), then add_elevator at FF93 (x 10.6..12.4) and FJ93
# (14.6..16.4) — 0.62 m inside BOTH shafts — and the stair's foot, on its own
# -X edge where flight A starts and flight B returns, opened onto shaft wall.
print('core clash')
txt, dc = assistant(
    'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 4, 'roof': 'flat', 'name': 'core test'}
)
txt, dc = assistant(
    'add_stair', {'cell': 'FH93', 'from_storey': 0, 'to_storey': 4, 'kind': 'u', 'width': 1.2}, drawing=dc
)
stair_ids = [x['id'] for x in dc.objs if x['kind'] == 'stair_u']
check('the stair stack stands at FH93', len(stair_ids) == 4, txt[:120])

txt, dc = assistant('add_elevator', {'cell': 'FF93', 'from_storey': 0, 'to_storey': 4}, drawing=dc)
check(
    "the live run's own lift at FF93 is refused, naming the stair it sits in",
    txt.startswith('refused') and 'overlaps' in txt and any(i in txt for i in stair_ids),
    txt,
)
check(
    'and the refusal names the two cells that ARE clear', 'FD93' in txt and 'FK93' in txt and 'lift centres' in txt, txt
)
txt, dc = assistant('add_elevator', {'cell': 'FE93', 'from_storey': 0, 'to_storey': 4}, drawing=dc)
check(
    'a lift clear of the plan but in front of the foot is refused too',
    txt.startswith('refused') and 'foot' in txt and '1.2 m of floor' in txt,
    txt,
)
check(
    'nothing was drawn by either refusal',
    not any(x['kind'] == 'elevator_shaft' for x in dc.objs),
    [x['kind'] for x in dc.objs[-3:]],
)

txt, dc = assistant('add_elevator', {'cell': 'FD93', 'from_storey': 0, 'to_storey': 4}, drawing=dc)
check('the cell the refusal named to the west draws', 'lift shaft' in txt and not txt.startswith('refused'), txt)
txt, dc = assistant('add_elevator', {'cell': 'FK93', 'from_storey': 0, 'to_storey': 4}, drawing=dc)
check('and so does the one to the east', 'lift shaft' in txt and not txt.startswith('refused'), txt)
lift_ids = [x['id'] for x in dc.objs if x['kind'] == 'elevator_shaft']
check('two shafts stand beside the stair', len(lift_ids) == 2, lift_ids)
txt, dc = assistant('add_elevator', {'cell': 'FK93', 'from_storey': 0, 'to_storey': 4}, drawing=dc)
check(
    'a second shaft in the same cell is refused: two shafts are two cores',
    txt.startswith('refused') and lift_ids[-1] in txt and 'two shafts' in txt,
    txt,
)
check('still only two shafts', len([x for x in dc.objs if x['kind'] == 'elevator_shaft']) == 2, txt)

# a stair and a spiral may share one well — stair-vs-stair is NOT a clash
n_before = len([x for x in dc.objs if x['kind'] == 'stair_u'])
txt, dc = assistant(
    'add_stair', {'cell': 'FH93', 'from_storey': 0, 'to_storey': 2, 'kind': 'u', 'width': 1.2}, drawing=dc
)
check(
    'a second stair in the same well is allowed — two stairs are one core',
    not txt.startswith('refused') and len([x for x in dc.objs if x['kind'] == 'stair_u']) == n_before + 2,
    txt,
)
txt, dc = assistant(
    'add_stair', {'cell': 'FK93', 'from_storey': 0, 'to_storey': 2, 'kind': 'u', 'width': 1.2}, drawing=dc
)
check(
    'but a stair drawn over a lift shaft is refused, from the stair side',
    txt.startswith('refused') and 'overlaps lift shaft' in txt and lift_ids[-1] in txt,
    txt,
)
check('and that refusal names clear cells too', 'the nearest clear cells are' in txt, txt)

S = A.EXT_MODULES['stairs_vertical']
u0 = [x for x in dc.objs if x['kind'] == 'stair_u'][0]
zones = S.approach_bboxes(u0)
ubb = E.bbox_of(u0)
check(
    'a u stair has ONE approach zone, beyond its local -X edge',
    len(zones) == 1 and abs(zones[0][2] - ubb[0]) < 1e-6 and abs(zones[0][0] - (ubb[0] - S.APPROACH_M)) < 1e-6,
    (zones, ubb),
)
check(
    'the zone is as wide across as the stair itself',
    abs((zones[0][3] - zones[0][1]) - (ubb[3] - ubb[1])) < 1e-6,
    (zones[0], ubb),
)
straight = {
    'kind': 'stair_straight',
    'p': {'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2},
    'x': 0.0,
    'z': 0.0,
    'ry': 0.0,
}
check(
    'a straight flight has a zone at BOTH ends, one per end',
    len(S.approach_bboxes(straight)) == 2 and [round(b[0], 3) for b in S.approach_bboxes(straight)] == [-3.3, 2.1],
    S.approach_bboxes(straight),
)
check(
    'a spiral arrives on its own turn, so it has no zone',
    S.approach_bboxes({'kind': 'stair_spiral', 'p': {'r_out': 1.3}, 'x': 0.0, 'z': 0.0, 'ry': 0.0}) == [],
)
check(
    'the tool descriptions say the two cores are refused',
    all('lift shaft' in t['description'] for t, _fn in S.TOOLS if t['name'] == 'add_stair')
    and all('4 cells west' in t['description'] for t, _fn in S.TOOLS if t['name'] == 'add_elevator'),
    [t['name'] for t, _fn in S.TOOLS],
)

finish()
