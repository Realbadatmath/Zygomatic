# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_interior_rooms.py — the interior_rooms family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_interior_rooms.py
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

KINDS = ['ceiling', 'floor_finish', 'skirting', 'raised_floor', 'suspended_ceiling']
TOOLS = ['subdivide_floor', 'add_room', 'add_corridor', 'add_ceiling', 'add_floor_finish', 'add_skirting']


def on_partition(door, parts, tol=1e-6):
    """True if the door's point lies ON one of the partition segments — the
    perpendicular distance to the line is 0 and the projection is inside it."""
    for w in parts:
        L = float(w['p']['len'])
        ux, uz = math.cos(w['ry']), -math.sin(w['ry'])  # the wall's own +X in world
        dx, dz = door['x'] - w['x'], door['z'] - w['z']
        along = dx * ux + dz * uz
        perp = abs(dx * (-uz) + dz * ux)
        if perp < 1e-4 and -L / 2 - tol <= along <= L / 2 + tol and abs(door['y'] - w['y']) < 1e-9:
            return True
    return False


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in TOOLS), [t for t in TOOLS if t not in names])

# a 10 x 10 m block (cells C4..L13) into 2 x 2 rooms
txt, d = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'cols': 2, 'rows': 2, 'storey': 0})
k = kinds_of(d)
check('2x2 subdivision = 2 full-length partitions', k.get('partition') == 2, (k, txt))
check('...and 4 doors, one per room boundary', k.get('door') == 4, (k, txt))
parts = [o for o in d.objs if o['kind'] == 'partition']
doors = [o for o in d.objs if o['kind'] == 'door']
check('both partitions are 10 m long', all(abs(p['p']['len'] - 10.0) < 1e-6 for p in parts), [p['p'] for p in parts])
check(
    'partitions are h 2.7 (to the slab underside, 2026-09-16), t 0.1 at y 0',
    all(abs(p['p']['h'] - 2.7) < 1e-9 and abs(p['p']['t'] - 0.1) < 1e-9 and p['y'] == 0.0 for p in parts),
    [(p['p'], p['y']) for p in parts],
)
check(
    'one partition runs along X, one along Z',
    sorted(round(abs(p['ry']), 6) for p in parts) == [0.0, round(math.pi / 2, 6)],
    [p['ry'] for p in parts],
)
check(
    'every door lies on a partition line', all(on_partition(o, parts) for o in doors), [(o['x'], o['z']) for o in doors]
)
check(
    'doors inherit their partition ry',
    all(any(abs(o['ry'] - p['ry']) < 1e-9 for p in parts) for o in doors),
    [o['ry'] for o in doors],
)
check('rooms go in one readable group', {o['grp'] for o in d.objs} == {'rooms st0'}, {o['grp'] for o in d.objs})
check('the result names counts and ids', 'partitions' in txt and 'doors' in txt and '4 rooms' in txt, txt)

# storey 2, doors off, 3 x 1
txt, d2 = assistant(
    'subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'cols': 3, 'rows': 1, 'storey': 2, 'doors': False}
)
k2 = kinds_of(d2)
check('3x1 without doors = 2 partitions, 0 doors', k2.get('partition') == 2 and not k2.get('door'), (k2, txt))
check('storey 2 sits at y = 5.4', all(o['y'] == 5.4 for o in d2.objs), [o['y'] for o in d2.objs])

# corridor
txt, d3 = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'cols': 3, 'corridor': 'x'})
k3 = kinds_of(d3)
cparts = [o for o in d3.objs if o['kind'] == 'partition']
cdoors = [o for o in d3.objs if o['kind'] == 'door']
check('corridor x: 2 corridor walls + 2x2 cross partitions', k3.get('partition') == 6, (k3, txt))
check('corridor x: one door per room onto the corridor', k3.get('door') == 6, (k3, txt))
check(
    'corridor doors lie on the corridor walls',
    all(on_partition(o, cparts) for o in cdoors),
    [(o['x'], o['z']) for o in cdoors],
)
check(
    'the corridor walls are 1.5 m apart',
    abs(max(o['z'] for o in cparts) - min(o['z'] for o in cparts)) >= 1.5 - 1e-9,
    [o['z'] for o in cparts],
)

# add_room
txt, d4 = assistant('add_room', {'cell_from': 'C4', 'cell_to': 'L13', 'name': 'living room', 'door_side': 'south'})
k4 = kinds_of(d4)
check('add_room draws 4 partitions and 1 door', k4.get('partition') == 4 and k4.get('door') == 1, (k4, txt))
rp = [o for o in d4.objs if o['kind'] == 'partition']
rd = [o for o in d4.objs if o['kind'] == 'door'][0]
south = [o for o in rp if o['name'].startswith('south')][0]
check(
    'the door sits on the south partition (same z)',
    abs(rd['z'] - south['z']) < 1e-9 and abs(rd['x'] - south['x']) < 1e-9,
    (rd['x'], rd['z'], south['x'], south['z']),
)
check('...and on a partition line', on_partition(rd, rp), (rd['x'], rd['z']))
check('room group is the room name', {o['grp'] for o in d4.objs} == {'living room'}, {o['grp'] for o in d4.objs})
txt, d4 = assistant(
    'add_room',
    {'cell_from': 'C4', 'cell_to': 'F6', 'name': 'wc', 'door_side': 'north', 'sides': ['north', 'west']},
    drawing=d4,
)
check('sides= draws only those partitions', kinds_of(d4).get('partition') == 6, (kinds_of(d4), txt))

# add_corridor
txt, d5 = assistant('add_corridor', {'cell_from': 'C4', 'cell_to': 'L13', 'width': 2.0, 'direction': 'z'})
cp = [o for o in d5.objs if o['kind'] == 'partition']
check('add_corridor draws exactly 2 partitions', len(cp) == 2 and len(d5.objs) == 2, kinds_of(d5))
check(
    '...2 m apart, running along Z, 10 m long',
    abs(abs(cp[0]['x'] - cp[1]['x']) - 2.0) < 1e-9
    and all(abs(o['p']['len'] - 10.0) < 1e-6 for o in cp)
    and all(abs(abs(o['ry']) - math.pi / 2) < 1e-6 for o in cp),
    [(o['x'], o['ry'], o['p']) for o in cp],
)

# finishes
txt, d6 = assistant('add_ceiling', {'cell_from': 'C4', 'cell_to': 'H7', 'kind': 'suspended_ceiling'})
c = d6.objs[-1]
check(
    'suspended ceiling is 6 x 4 m, t 0.05, tiles 0.6',
    c['kind'] == 'suspended_ceiling' and c['p'] == {'w': 6.0, 'd': 4.0, 't': 0.05, 'tiles': 0.6},
    c['p'],
)
check('...hung at storey top - t (2.65 m)', abs(c['y'] - 2.65) < 1e-9, c['y'])
txt, d6 = assistant('add_ceiling', {'cell_from': 'C4', 'cell_to': 'H7', 'storey': 1}, drawing=d6)
check(
    'plaster ceiling at storey 1 sits at 5.3 m',
    d6.objs[-1]['kind'] == 'ceiling' and abs(d6.objs[-1]['y'] - 5.3) < 1e-9,
    (d6.objs[-1]['kind'], d6.objs[-1]['y']),
)
txt, d6 = assistant('add_floor_finish', {'cell_from': 'C4', 'cell_to': 'H7', 'material': 'mat_timber'}, drawing=d6)
f = d6.objs[-1]
check(
    'floor finish 6 x 4 x 0.02 at y 0, timber',
    f['kind'] == 'floor_finish'
    and f['p'] == {'w': 6.0, 'd': 4.0, 't': 0.02}
    and f['y'] == 0.0
    and f['mat'] == 'mat_timber',
    (f['p'], f['y'], f['mat']),
)
txt, d6 = assistant('add_skirting', {'cell_from': 'C4', 'cell_to': 'H7'}, drawing=d6)
sk = [o for o in d6.objs if o['kind'] == 'skirting']
check(
    'skirting = 4 runs, 2 x 6 m and 2 x 4 m',
    len(sk) == 4 and sorted(round(o['p']['len'], 4) for o in sk) == [4.0, 4.0, 6.0, 6.0],
    [o['p'] for o in sk],
)
check(
    'skirting is 0.1 high, 0.015 proud',
    all(o['p']['h'] == 0.1 and o['p']['t'] == 0.015 for o in sk),
    [o['p'] for o in sk],
)

# refusals
txt, _ = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'cols': 1, 'rows': 1})
check('1x1 subdivision refused', txt.startswith('refused'), txt)
txt, _ = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'cols': 99})
check('99 columns refused', txt.startswith('refused'), txt)
txt, _ = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'C5', 'cols': 2, 'corridor': 'x'})
check('corridor in a 1 m deep block refused', txt.startswith('refused'), txt)
txt, _ = assistant('subdivide_floor', {'cell_from': 'C4', 'cell_to': 'L13', 'corridor': 'diagonal'})
check('bad corridor axis refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_room', {'cell_from': 'C4', 'cell_to': 'L13', 'door_side': 'up'})
check('bad door_side refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_room', {'cell_from': 'ZZ9', 'cell_to': 'L13'})
check('off-grid cell refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_ceiling', {'cell_from': 'C4', 'cell_to': 'H7', 'kind': 'roof_flat'})
check('a roof is not a ceiling — refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_corridor', {'cell_from': 'C4', 'cell_to': 'H7', 'width': 12})
check('a 12 m corridor refused', txt.startswith('refused'), txt)
txt, _ = assistant('add_skirting', {'cell_from': 'C4', 'cell_to': 'H7', 'sides': ['up']})
check('bad skirting side refused', txt.startswith('refused'), txt)

# add_object must know the new kinds, and the rail must list them
txt, d7 = assistant('add_object', {'kind': 'raised_floor', 'cell': 'A1', 'params': {'h': 0.45}})
check('add_object knows raised_floor', d7.objs[-1]['kind'] == 'raised_floor' and d7.objs[-1]['p']['h'] == 0.45, txt)
check('rail lists the kinds', rail_has(KINDS) == [], rail_has(KINDS))

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'ceiling', 'p': {'w': 6, 'd': 4, 't': 0.1}},
    {'kind': 'floor_finish', 'p': {'w': 6, 'd': 4, 't': 0.02}},
    {'kind': 'skirting', 'p': {'len': 4, 'h': 0.1, 't': 0.015}},
    {'kind': 'raised_floor', 'p': {'w': 6, 'd': 4, 'h': 0.3, 'pedestals': 0.6}},
    {'kind': 'suspended_ceiling', 'p': {'w': 6, 'd': 4, 't': 0.05, 'tiles': 0.6}},
]
b = browser_kinds(cases)
by = {r['kind']: r for r in b}
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])


def sized(kind, w, h, d, tol=0.002):
    r = by.get(kind) or {}
    s = r.get('size') or [0, 0, 0]
    ok = bool(r.get('ok')) and abs(s[0] - w) < tol and abs(s[1] - h) < tol and abs(s[2] - d) < tol
    check(f'{kind} builds, {w:g} x {h:g} x {d:g} m', ok, r)


sized('ceiling', 6, 0.1, 4)
sized('floor_finish', 6, 0.02, 4)
sized('skirting', 4, 0.1, 0.015)
sized('raised_floor', 6, 0.3, 4)
sized('suspended_ceiling', 6, 0.05, 4)
check('ceiling sits on y = 0 upward', abs((by['ceiling']['min'][1]) - 0.0) < 1e-3, by['ceiling'])
check(
    'raised floor has a deck plus a pedestal grid',
    by['raised_floor']['parts'] >= 1 + 10 * 7,
    by['raised_floor']['parts'],
)
check(
    'suspended ceiling has bars and tiles',
    by['suspended_ceiling']['parts'] >= 10 + 7 + 60,
    by['suspended_ceiling']['parts'],
)
check(
    'labels',
    [by[k]['label'] for k in KINDS] == ['Ceiling', 'Floor finish', 'Skirting', 'Raised floor', 'Suspended ceiling'],
    [by[k]['label'] for k in KINDS],
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for kind in KINDS:
    check(f'blender builds {kind}', bl.get(kind, {}).get('polys', 0) > 0, bl.get(kind))
check(
    'blender raised_floor is more than one box', bl.get('raised_floor', {}).get('polys', 0) > 6, bl.get('raised_floor')
)
check(
    'blender suspended_ceiling is a grid',
    bl.get('suspended_ceiling', {}).get('polys', 0) > 6 * 17,
    bl.get('suspended_ceiling'),
)

# ── a room inside a shell: the facade is never doubled ────────────────────────
# job 038ca075c052 drew the lobby's south partition ON the facade line with its
# own door a metre beside the entrance. A side on the envelope edge is the
# facade (glass on a glazed storey): no partition, no door.
print('facade')
SHELL = {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 3, 'roof': 'flat', 'name': 'shell'}


def shell():
    _, dd = assistant('draw_box', dict(SHELL))
    return dd


def room_parts(dd, grp):
    return [o for o in dd.objs if o['kind'] == 'partition' and o['grp'] == grp]


ds = shell()
txt, ds = assistant('add_room', {'cell_from': 'FD104', 'cell_to': 'FM109', 'name': 'Lobby'}, drawing=ds)
lp = room_parts(ds, 'Lobby')
ld = [o for o in ds.objs if o['kind'] == 'door' and o['grp'] == 'Lobby']
check(
    'a room on the south facade draws 3 partitions, not 4',
    len(lp) == 3 and not any(o['name'].startswith('south') for o in lp),
    (txt, [o['name'] for o in lp]),
)
check('...and says which line it left alone', 'no south partition' in txt and 'south facade' in txt, txt)
north = [o for o in lp if o['name'].startswith('north')]
check(
    '...and the automatic door faces the plan centre (the north partition)',
    len(ld) == 1 and on_partition(ld[0], north),
    (txt, [(o['x'], o['z']) for o in ld]),
)

txt, _ = assistant(
    'add_room', {'cell_from': 'FD104', 'cell_to': 'FM109', 'name': 'Lobby', 'door_side': 'south'}, drawing=shell()
)
check('door_side on the facade is refused', txt.startswith('refused'), txt)
check('...and the refusal names an interior side', 'north' in txt, txt)

txt, dc = assistant(
    'add_room', {'cell_from': 'EX90', 'cell_to': 'FD97', 'name': 'Cycle', 'door_side': 'east'}, drawing=shell()
)
cp = room_parts(dc, 'Cycle')
check(
    'a corner room drops BOTH facade sides',
    len(cp) == 2 and sorted(o['name'].split()[0] for o in cp) == ['east', 'south'],
    (txt, [o['name'] for o in cp]),
)

txt, di = assistant(
    'add_room', {'cell_from': 'FF96', 'cell_to': 'FJ99', 'name': 'Store', 'door_side': 'south'}, drawing=shell()
)
ip = room_parts(di, 'Store')
idoor = [o for o in di.objs if o['kind'] == 'door' and o['grp'] == 'Store']
check(
    'a room clear of the facade still gets 4 partitions and its door',
    len(ip) == 4 and len(idoor) == 1 and 'no south partition' not in txt,
    (txt, len(ip)),
)

dg = shell()
txt, dg = assistant('add_curtain_wall', {'walls': 'shell', 'storeys': [0]}, drawing=dg)
txt, dg = assistant('add_room', {'cell_from': 'FD104', 'cell_to': 'FM109', 'name': 'Lobby', 'storey': 0}, drawing=dg)
check('on a glazed storey the note names the curtain wall', 'curtain wall' in txt, txt)

# ── delete cascades into the openings the wall carried ────────────────────────
print('delete cascade')
host = idoor[0].get('meta', {}).get('host')
check(
    'a room door names its partition in meta.host',
    host == [o for o in ip if o['name'].startswith('south')][0]['id'],
    (host, [o['id'] for o in ip]),
)
txt, di = assistant('delete', {'which': [host]}, drawing=di)
check('deleting the partition takes its door with it', di.find(idoor[0]['id']) is None, txt)
check('...and the reply says so', 'door' in txt and idoor[0]['id'] in txt, txt)

dl = shell()
txt, dl = assistant(
    'add_room', {'cell_from': 'FF96', 'cell_to': 'FJ99', 'name': 'Store', 'door_side': 'none'}, drawing=dl
)
lw = [o for o in room_parts(dl, 'Store') if o['name'].startswith('south')][0]
legacy = dl.new('door', {'w': 0.9, 'h': 2.1}, lw['x'], lw['z'], lw['y'], lw['ry'], 'mat_timber', name='legacy door')
legacy['meta'].pop('host', None)
txt, dl = assistant('delete', {'which': [lw['id']]}, drawing=dl)
check('a legacy door with no host still goes with its wall', dl.find(legacy['id']) is None, txt)

dsh = shell()
env = __import__('zyg_workflows.arch_assistant').EXT_MODULES['envelope_rules'].envelopes(dsh)['shell']
dup = dsh.new(
    'partition',
    {'len': 10.0, 'h': 2.5, 't': 0.1},
    13.0,
    env['zmax'],
    0.0,
    0.0,
    'mat_plaster',
    name='south partition dup',
    grp='dup',
)
shared = dsh.new('door', {'w': 0.9, 'h': 2.1}, 13.0, env['zmax'], 0.0, 0.0, 'mat_timber', name='legacy door')
shared['meta'].pop('host', None)
txt, dsh = assistant('delete', {'which': [dup['id']]}, drawing=dsh)
check('a hostless door on a line the facade also holds survives that delete', dsh.find(shared['id']) is not None, txt)
finish()
