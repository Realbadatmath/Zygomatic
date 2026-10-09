# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_opening_rules — a hole is a hole IN something (2026-09-16).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_opening_rules.py

The subject is the 2026-09-12 defect: the lobby's south partition was deleted
and its 2.8 m door stayed behind, standing in the facade plane, overlapping the
glass entrance double door by 1.8 m, and nothing reported it. Every check here
is an A/B pair — the defective drawing names the code, the corrected one is
silent — plus the operator's live tower, on which the whole family must say
nothing at all.

No new kinds and no tools, so there is no browser or Blender pass: this is pure
geometry over the records add_opening / add_windows / add_room already make.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['opening_rules']
E = A.EXT_MODULES['envelope_rules']
DR = A.EXT_MODULES['design_rules']

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')


def findings(d):
    return M.check_openings(d)


def codes(d):
    return [f['code'] for f in findings(d)]


def texts(d):
    return ' | '.join(f['text'] for f in findings(d))


def tower(storeys=20):
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    return d


# ── the family contract ──────────────────────────────────────────────────────
check('opening_rules is loaded as a family', M is not None)
check(
    'it owns no kinds and no tools (check-only)',
    M.KINDS == {} and M.OPENINGS == [] and M.TOOLS == [] and M.PROMPT == '',
    (M.KINDS, M.OPENINGS, M.TOOLS, repr(M.PROMPT)),
)
check('it registers exactly one design check', M.DESIGN_CHECKS == [M.check_openings], M.DESIGN_CHECKS)
check('design_rules.run_checks picks it up', M.check_openings in DR.contributed())
check(
    'the opening kinds are the door kinds plus the window kinds that exist',
    set(M.opening_kinds()) == set(DR.DOOR_KINDS) | {'window', 'window_strip'}
    and all(k in A.KINDS for k in M.opening_kinds()),
    M.opening_kinds(),
)
check(
    'a check never raises: a broken drawing returns one info finding',
    [f['code'] for f in M.check_openings(None)] == ['open_check_error'],
    M.check_openings(None),
)

# ── (a) the 2026-09-12 orphan: a door left standing in the facade plane ──────
da = tower()
A.call_tool(da, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0))
o102 = next(o for o in da.objs if o['kind'] == 'double_door')
check('the entrance alone is silent', codes(da) == [], codes(da))
orphan = da.new('door', {'w': 2.8, 'h': 2.1, 'sill': 0}, o102['x'] + 1.0, o102['z'], 0, 0, 'mat_timber', 'orphan', '')
check('the abandoned door carries no host', (orphan.get('meta') or {}) == {}, orphan.get('meta'))
ca, ta = codes(da), texts(da)
check('(a) the orphan door is an open_orphan ERROR', 'open_orphan' in ca, ca)
check(
    '(a) the orphan finding is an error and names the record',
    any(f['sev'] == 'error' and f['code'] == 'open_orphan' and orphan['id'] in f['text'] for f in findings(da)),
    ta,
)
check('(a) it names the fix by tool', f'delete(which=["{orphan["id"]}"])' in ta, ta)
check('(a) it says which plane it is standing in', f'plane of {o102["meta"]["host"]}' in ta, ta)
check('(a) it also overlaps the entrance door', 'open_overlap' in ca, ca)
check('(a) the overlap is measured at 1.80 m (the 09-12 number)', 'by 1.80 m' in ta, ta)
check('(a) the overlap names both doors', o102['id'] in ta and orphan['id'] in ta, ta)
da.objs.remove(orphan)
check('(a/B) delete the orphan and both codes go silent', codes(da) == [], codes(da))

# ── (b) an opening that runs off the end of its wall ─────────────────────────
db = tower()
A.call_tool(db, 'add_room', dict(cell_from='FD104', cell_to='FH108', storey=0, name='Store'))
w4 = db.new('partition', {'len': 4.0, 'h': 2.5, 't': 0.1}, 14.0, -50.0, 0, 0, 'mat_plaster', 'store wall', 'Store')
wide = db.new('door', {'w': 6.0, 'h': 2.1}, 14.0, -50.0, 0, 0, 'mat_timber', 'big door', 'Store')
wide['meta']['host'] = w4['id']
cb, tb = codes(db), texts(db)
check('(b) a 6 m door in a 4 m partition is an open_off_wall ERROR', 'open_off_wall' in cb, cb)
check('(b) the finding names the overrun in metres', 'runs 1.00 m past its end' in tb, tb)
check('(b) it names the door width and the wall length', '6 m wide' in tb and '4 m long' in tb, tb)
check('(b) it offers add_opening with a width that fits', 'width=3.4' in tb, tb)
wide['p']['w'] = 1.0
check('(b/B) a 1.0 m door in the same partition is silent', codes(db) == [], codes(db))

# a hole taller than the wall it is cut in is the same rule
wide['p']['h'] = 2.8
check(
    '(b) a 2.8 m door in a 2.5 m partition is off-wall too',
    'open_off_wall' in codes(db) and 'above the wall' in texts(db),
    texts(db),
)
wide['p']['h'] = 2.1
check('(b/B) back under the head, silent again', codes(db) == [], codes(db))

# ── (c) two entrance doors on one facade ────────────────────────────────────
dc = tower()
A.call_tool(
    dc, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', at=8.5, width=2.0, height=2.4)
)
A.call_tool(dc, 'add_opening', dict(group='tower', side='south', storey=0, kind='door', at=11.5, width=1.0, height=2.1))
cc, tc = codes(dc), texts(dc)
check('(c) two doors 3 m apart on the south face is open_double_entrance', 'open_double_entrance' in cc, cc)
check('(c) the finding names the gap and the facade', '3.0 m apart' in tc and 'south facade' in tc, tc)
check('(c) it names both doors', 'o102' in tc and 'o103' in tc, tc)
dc2 = tower()
A.call_tool(
    dc2, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', at=6.0, width=2.0, height=2.4)
)
A.call_tool(
    dc2, 'add_opening', dict(group='tower', side='south', storey=0, kind='door', at=14.0, width=1.0, height=2.1)
)
check('(c/B) the same two doors 8 m apart are silent', codes(dc2) == [], codes(dc2))

# ── a door a person cannot walk through ─────────────────────────────────────
dh = tower()
A.call_tool(dh, 'add_opening', dict(group='tower', side='north', storey=0, kind='door', width=0.9, height=1.8))
check(
    'a 1.8 m door is an open_headroom ERROR', 'open_headroom' in codes(dh) and 'only 1.8 m tall' in texts(dh), texts(dh)
)
dh2 = tower()
A.call_tool(dh2, 'add_opening', dict(group='tower', side='north', storey=0, kind='door', width=0.9, height=2.1))
check('a 2.1 m door is silent', codes(dh2) == [], codes(dh2))


# ── a ground-floor door that opens onto nothing ─────────────────────────────
def shed(y):
    """Four walls and a south door, standing `y` metres above the ground plane."""
    d = A.Drawing(None)
    p = {'len': 6.0, 'h': 2.7, 't': 0.24, 'base': y}
    d.new('wall', dict(p), 40.0, 37.0, y, 0, 'mat_concrete', 'north wall', 'shed')
    south = d.new('wall', dict(p), 40.0, 43.0, y, 0, 'mat_concrete', 'south wall', 'shed')
    d.new('wall', dict(p), 43.0, 40.0, y, -math.pi / 2, 'mat_concrete', 'east wall', 'shed')
    d.new('wall', dict(p), 37.0, 40.0, y, -math.pi / 2, 'mat_concrete', 'west wall', 'shed')
    door = d.new('door', {'w': 0.9, 'h': 2.1, 'base': y}, 40.0, 43.0, y, 0, 'mat_timber', 'shed door', 'shed')
    door['meta']['host'] = south['id']
    return d, door


dn, dn_door = shed(1.5)
check('the raised shed still reads as storey 0', M._storey_of(dn, dn_door) == 0, dn_door)
cn, tn = codes(dn), texts(dn)
check(
    'a door 1.5 m above the ground with nothing outside is an open_nowhere WARN',
    cn == ['open_nowhere'] and findings(dn)[0]['sev'] == 'warn',
    [(f['sev'], f['code']) for f in findings(dn)],
)
check('the warning names the facade and the tool that fixes it', 'south facade' in tn and 'add_road' in tn, tn)
dn2, _ = shed(1.5)
dn2.new('pad', {'w': 6.0, 'd': 4.0, 't': 0.2}, 40.0, 45.0, 1.5, 0, 'mat_concrete', 'terrace', 'site')
check('(B) a pad under the approach silences it', codes(dn2) == [], codes(dn2))
dn3, _ = shed(0.0)
check('(B) the same shed on the ground plane is silent', codes(dn3) == [], codes(dn3))

# ── (e) the 2026-09-12 cascade: delete the wall, the door goes with it ───────
de = tower()
room = A.call_tool(de, 'add_room', dict(cell_from='FD104', cell_to='FM108', storey=0, name='Lobby'))
door = next(o for o in de.objs if o['kind'] == 'door')
host = (door.get('meta') or {}).get('host')
check('(e) add_room writes the door with meta.host', bool(host), (room[:80], door.get('meta')))
check('(e) the room drawing is silent before the delete', codes(de) == [], codes(de))
msg = A.call_tool(de, 'delete', dict(which=[host]))
check('(e) delete cascades the door out with its partition', door['id'] in msg and de.find(door['id']) is None, msg)
check('(e) so open_orphan stays silent — the cascade and this check agree', codes(de) == [], codes(de))
# and if the cascade had NOT fired, the check would have caught it
de2 = tower()
A.call_tool(de2, 'add_room', dict(cell_from='FD104', cell_to='FM108', storey=0, name='Lobby'))
door2 = next(o for o in de2.objs if o['kind'] == 'door')
de2.objs.remove(de2.find(door2['meta']['host']))  # the 09-12 hand edit: the wall goes, the door stays
check(
    '(e) without the cascade the same door IS an open_orphan',
    'open_orphan' in codes(de2) and door2['id'] in texts(de2),
    texts(de2),
)

# ── (d) the operator's live tower: silent on what is right ──────────────────
dfx = A.Drawing(json.load(open(FIX)))
fx = findings(dfx)
holes = [o for o in dfx.objs if o['kind'] in M.opening_kinds() and not o.get('hidden')]
check(
    '(d) the fixture holds its 6 openings (5 door + 1 double_door)',
    len(holes) == 6 and sum(1 for o in holes if o['kind'] == 'double_door') == 1,
    [(o['id'], o['kind']) for o in holes],
)
check(
    '(d) every one of them has a host wall',
    all(M._find_host(dfx, o) is not None for o in holes),
    [(o['id'], (M._find_host(dfx, o) or {}).get('id')) for o in holes],
)
check('(d) the whole family is SILENT on the live tower', fx == [], [(f['code'], f['text'][:90]) for f in fx])
fx_door = dfx.find('o102')
check(
    '(d) o102 is the storey-0 double door on the south facade',
    fx_door['kind'] == 'double_door'
    and M._storey_of(dfx, fx_door) == 0
    and E.touches_facade(E.group_envelope(dfx, 'tower'), fx_door['x'], fx_door['z']) == 'south',
    (fx_door['x'], fx_door['z']),
)
check(
    '(d) o102 does NOT raise open_nowhere: the ground plane at y 0 is walkable 0.6 m out',
    M.walkable_at(dfx, fx_door['x'], fx_door['z'] + M.STEP_OUT, fx_door['y'])
    and abs(A.ground_height(dfx, fx_door['x'], fx_door['z'] + M.STEP_OUT) - fx_door['y']) <= M.STEP_DY,
    A.ground_height(dfx, fx_door['x'], fx_door['z'] + M.STEP_OUT),
)
road = next(o for o in dfx.objs if o['kind'] == 'road')
check(
    '(d) the drive o545 in fact stops short of the door — the GROUND is what silences it, '
    'not the road (noted, not a defect: the site is flat at y 0)',
    not M._covers_point(road, fx_door['x'], fx_door['z'] + M.STEP_OUT),
    (road['id'], road['p'], road['x'], road['z']),
)
check(
    '(d) the fixture design check gains no new error from this family',
    not any(f['code'].startswith('open_') for f in DR.run_checks(dfx)),
    [f['code'] for f in DR.run_checks(dfx) if f['code'].startswith('open_')],
)

# ── (f) the tower the tools build — the replay's own drawing ────────────────
df = tower()
A.call_tool(df, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0))
A.call_tool(df, 'add_curtain_wall', dict(walls='tower', storeys=[0, 2, 4, 6, 8, 10, 12, 14, 16, 18]))
A.call_tool(df, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=20, kind='u', width=1.2))
A.call_tool(df, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=20, w=1.8, depth=2.0, door_side='south'))
A.call_tool(
    df,
    'add_canopy',
    dict(group='tower', side='south', storey=0, width=12, depth=5, height=4.2, columns=4, material='mat_glass'),
)
A.call_tool(df, 'add_room', dict(cell_from='FD104', cell_to='FM108', storey=0, name='Lobby'))
A.call_tool(df, 'add_parapet', dict(group='tower', height=1.1, cap=True))
check(
    '(f) the tower the tools build (entrance, glazing, core, lobby, parapet) is SILENT',
    codes(df) == [],
    [(f['code'], f['text'][:110]) for f in findings(df)],
)
check(
    '(f) add_curtain_wall replaced 39 walls, and all 3 openings still find a host',
    sum(1 for o in df.objs if o['kind'] == 'curtain_wall') == 39
    and [o['id'] for o in df.objs if o['kind'] in M.opening_kinds() and M._find_host(df, o) is None] == [],
    (
        sum(1 for o in df.objs if o['kind'] == 'curtain_wall'),
        [(o['id'], o['kind']) for o in df.objs if o['kind'] in M.opening_kinds()],
    ),
)

# add_windows on a wall that already holds the entrance cuts a window ACROSS the
# door: a true finding, and the only one this family makes on a tool-built tower.
dw = tower()
A.call_tool(dw, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0))
A.call_tool(dw, 'add_windows', dict(walls='tower', every_n_storeys=2, per_wall=3))
check(
    'a window cut across the entrance door is reported, once',
    codes(dw) == ['open_overlap'] and 'Double door overlaps' in texts(dw),
    [(f['code'], f['text'][:110]) for f in findings(dw)],
)

# ── the cap ─────────────────────────────────────────────────────────────────
dcap = tower()
south = dcap.find('o2')
for i in range(14):
    dcap.new('door', {'w': 0.9, 'h': 2.1}, 5.0 + i * 0.3, -41.0, 0, 0, 'mat_timber', f'ghost {i}', 'ghosts')
cap = [f for f in findings(dcap) if f['code'] == 'open_orphan']
check(
    'a flood of orphans is capped at 8 + one "and N more" line',
    len(cap) == M.MAX_PER_CODE + 1 and cap[-1]['sev'] == 'info' and 'and 6 more' in cap[-1]['text'],
    [(f['sev'], f['text'][:60]) for f in cap],
)
check(
    'the cap keeps every finding one line and one object',
    all(f['text'].count('—') <= 2 for f in findings(dcap)),
    len(findings(dcap)),
)
check(
    'the south wall is still there — the orphans are orphans by GROUP, not by geometry',
    south is not None and south['kind'] == 'wall',
    south,
)

finish()
