# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_analyse_planning.py — proves the four planning analyses
(a_egress, a_access, a_occupancy, a_fire) on ONE hand-computed fixture, in the
live tab AND in the assistant's Python twin.

THE FIXTURE (all storey 0, every number below worked out by hand first):

      z=8  +--------+--+---------------+
           |        |  |               |
           | Room A |c |    Room B     |     c = corridor, 1.2 m wide
    D0 ===>+   40   |o |     46.4      |     D0 exterior door in the W wall
           |   m2   |r |      m2       |     D1 in the A|corridor partition
           |        |r |               |     D2 in the corridor|B partition
      z=0  +--------+--+---------------+       (0.08 m thin, and the only
          x=0      x=5 x=6.2         x=12       compartment line on the plan)

  · rooms are the closed loops of the wall/partition centre-lines: 5x8 = 40 m2,
    1.2x8 = 9.6 m2, 5.8x8 = 46.4 m2;
  · egress: Room B has only D2, so its way out runs through the corridor and
    Room A to D0 — 7.0456 (its far corner (12,0) to D2) + 1.2 (D2 to D1) + 5.0
    (D1 to D0) = 13.2456 m; Room A 6.4031 m; corridor 9.1761 m;
  · access: the corridor's largest inscribed circle is 1.2 m across, under the
    1.5 m turn; D2's 0.7 m leaf is 0.65 m clear, under 0.85 m; the other two
    doors (0.95 / 0.90 m clear) and the other two rooms (5.0 / 5.8 m) pass;
  · occupancy: Room A office 40 / 10 = 4 persons, Room B 46.4 / 10 -> 5, the
    corridor is circulation and counts nobody: 9 in the building;
  · fire: compartment A (Room A + corridor, 49.6 m2) and compartment B
    (46.4 m2) come from a "comp:A" tag and a meta.compartment; the partition
    between them carries the line at 80 mm, and D2 is the fire door.

Budget: exactly TWO browser opens — icon_state for the four ids, and one
browser_eval that presses all four icons and reads every number back.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['a_egress', 'a_access', 'a_occupancy', 'a_fire']
RY = -math.pi / 2  # a wall drawn from (x, 0) to (x, 8)


def wall(oid, kind, x, z, ry, ln, t, mat='mat_concrete'):
    return {
        'id': oid,
        'kind': kind,
        'name': oid,
        'x': x,
        'y': 0,
        'z': z,
        'ry': ry,
        'p': {'len': ln, 't': t, 'h': 2.7},
        'mat': mat,
    }


def door(oid, x, z, w):
    return {'id': oid, 'kind': 'door', 'name': 'Door', 'x': x, 'y': 0, 'z': z, 'ry': RY, 'p': {'w': w, 'h': 2.1}}


def pin(oid, x, z, meta):
    return {
        'id': oid,
        'kind': 'column',
        'name': oid,
        'x': x,
        'y': 0,
        'z': z,
        'ry': 0,
        'p': {'w': 0.2, 'd': 0.2, 'h': 2.7},
        'meta': meta,
    }


DOC = {
    'name': 'planning fixture',
    'units': 'm',
    'schema': 1,
    'ext': {},
    'objects': [
        wall('o1', 'wall', 6, 0, 0, 12, 0.24),  # south
        wall('o2', 'wall', 6, 8, 0, 12, 0.24),  # north
        wall('o3', 'wall', 0, 4, RY, 8, 0.24),  # west  (D0 is in this one)
        wall('o4', 'wall', 12, 4, RY, 8, 0.24),  # east
        wall('o5', 'partition', 5, 4, RY, 8, 0.20),  # Room A | corridor
        wall('o6', 'partition', 6.2, 4, RY, 8, 0.08),  # corridor | Room B — 80 mm, too light
        door('o7', 0, 4, 1.00),  # D0, exterior -> an exit
        door('o8', 5, 4, 0.95),  # D1
        door('o9', 6.2, 4, 0.70),  # D2, 0.65 m clear -> too narrow
        pin('o10', 2.5, 4, {'room': 'Room A', 'use': 'office', 'tags': ['comp:A']}),
        pin('o11', 5.6, 4, {'room': 'Corridor', 'use': 'corridor', 'tags': ['comp:A']}),
        pin('o12', 9.0, 4, {'room': 'Room B', 'use': 'office', 'compartment': 'B'}),
    ],
}

EGRESS = {'Room A': 6.4031, 'Corridor': 9.1761, 'Room B': 13.2456}  # hand-computed, metres

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is a wired icon in the dock (no stub flag, no dashed class, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. one browser_eval: press all four and read every number back ───────────
JS = r"""() => {
  const out = {errors: []};
  const sheet = () => { const el = document.getElementById('ar-sheet');
                        return {shown: el && el.style.display === 'flex',
                                title: el ? (el.querySelector('.hd span') || {}).textContent : '',
                                body: el ? (el.querySelector('.bd') || {}).innerHTML || '' : ''}; };
  const byName = (rows) => { const m = {}; rows.forEach(r => { m[r.name] = r; }); return m; };

  out.registry = AR_EXT.analyses.filter(a => /^a_(egress|access|occupancy|fire)$/.test(a.id))
                                .map(a => a.id).sort();
  out.finder = typeof window.analyse_planning.rooms === 'function';

  /* the room finder, once — every analysis below reuses it */
  const rooms = analyse_planning.rooms(0);
  out.rooms = rooms.map(r => ({name: r.name, use: r.use, area: +r.area.toFixed(4),
                               comp: r.compartment, src: r.source, doors: r.doors.length}));

  /* a_egress ------------------------------------------------------------- */
  arTool('a_egress', {max: 30});
  const s1 = sheet();
  out.egress_sheet = {title: s1.title, shown: s1.shown, has_note: /approximation/.test(s1.body)};
  out.route_drawn = !!AR.scene.getObjectByName('analyse_planning:route');
  out.route_pts = analyse_planning._route ?
      analyse_planning._route.geometry.attributes.position.count : 0;
  const eg = AR_EXT.analyses.find(a => a.id === 'a_egress').run({max: 30});
  out.egress = byName(eg.rooms ? [] : []);   /* run() reports, the rooms carry the numbers */
  out.travel = {}; analyse_planning.rooms(0).forEach(r => { out.travel[r.name] = null; });
  const eg2 = analyse_planning.egress({max: 30});
  out.egress_rows = eg2.rows.length; out.egress_exits = eg2.exits; out.egress_ok = eg2.ok;
  out.egress_worst = eg2.worst;
  /* the travel distance per room, off the same pass */
  out.travel = {};
  analyse_planning.egress({max: 30, rooms: (() => { const rs = analyse_planning.rooms(0); out._rs = rs; return rs; })()});
  out._rs.forEach(r => { out.travel[r.name] = r.travel === null ? null : +r.travel.toFixed(4); });
  /* a low limit must flag Room B */
  const tight = analyse_planning.egress({max: 10});
  out.tight_fail = tight.issues.filter(i => /Room B/.test(i.text)).length;
  out.tight_ok = tight.ok;

  /* the drawn route belongs to the sheet: closing it takes the line away */
  arSheetClose();
  out.route_after_close = !!AR.scene.getObjectByName('analyse_planning:route');

  /* a_access ------------------------------------------------------------- */
  arTool('a_access', {turn: 1.5, door_w: 0.85});
  const s2 = sheet();
  out.access_sheet = {title: s2.title, shown: s2.shown};
  const ac = analyse_planning.access({turn: 1.5, door_w: 0.85});
  out.access_ok = ac.ok;
  out.turns = {}; ac.rooms || 0;
  analyse_planning.rooms(0).forEach(() => {});
  out.access_issues = ac.issues.map(i => i.text);
  out.access_doors = ac.doors;
  const rs2 = analyse_planning.rooms(0);
  analyse_planning.access({turn: 1.5, door_w: 0.85, rooms: rs2});
  rs2.forEach(r => { out.turns[r.name] = +r.turn.toFixed(2); });
  /* classify by the RECORD an issue points at, not by words in its prose: a
     door issue names a door record, a turning-circle issue names the room's. */
  const isDoor = (id) => { const o = arFind(id); return !!o && o.kind === 'door'; };
  out.narrow = ac.issues.filter(i => isDoor(i.ids[0])).map(i => i.ids[0]);
  out.small_turn = ac.issues.filter(i => !isDoor(i.ids[0])).map(i => i.text);
  /* a 1.0 m turn is satisfied by the same corridor */
  out.access_wide_ok = analyse_planning.access({turn: 1.0, door_w: 0.6}).ok;

  /* a_occupancy ---------------------------------------------------------- */
  arTool('a_occupancy', {});
  const s3 = sheet();
  out.occ_sheet = {title: s3.title, shown: s3.shown, has_rate_input: /setRate/.test(s3.body)};
  const oc = analyse_planning.occupancy({});
  out.occ_total = oc.total; out.occ_per_storey = oc.per_storey;
  out.persons = {}; oc.rooms || 0;
  const rs3 = analyse_planning.rooms(0);
  analyse_planning.occupancy({rooms: rs3});
  rs3.forEach(r => { out.persons[r.name] = r.persons; out.persons[r.name + '/rate'] = r.rate; });
  /* the table is editable and is kept with the drawing */
  const oc2 = analyse_planning.occupancy({rates: {office: 5}});
  out.occ_total_dense = oc2.total;
  analyse_planning.setRate('office', 20);
  out.saved_rate = AR.doc.ext.analyse_planning.rates.office;
  out.occ_total_saved = analyse_planning.occupancy({}).total;
  analyse_planning.setRate('office', 10);

  /* a_fire --------------------------------------------------------------- */
  arTool('a_fire', {max_area: 1000, max_len: 60});
  const s4 = sheet();
  out.fire_sheet = {title: s4.title, shown: s4.shown};
  const fi = analyse_planning.fire({max_area: 1000, max_len: 60});
  out.comps = fi.compartments.map(c => ({id: c.id, rooms: c.rooms, area: +c.area.toFixed(4),
                                         travel: +c.travel.toFixed(4)})).sort((a, b) => a.id < b.id ? -1 : 1);
  out.fire_doors = fi.fire_doors;
  out.comp_walls = fi.compartment_walls.map(w => ({id: w.id, t: w.t, weak: w.weak}));
  out.fire_issues = fi.issues.map(i => i.severity + ' ' + i.text);
  out.fire_rows = fi.rows.length;
  /* a 40 m2 cap must flag both compartments */
  out.fire_small = analyse_planning.fire({max_area: 40, max_len: 60})
                     .issues.filter(i => /over the 40/.test(i.text)).length;

  arSheetClose();
  return out;
}"""

r = browser_eval(JS, doc=DOC)
v = r['value'] or {}
check('no page errors while the four analyses run', not r['errors'], r['errors'])

check(
    'all four are on the shared AR_EXT.analyses registry so Code check can call them',
    v.get('registry') == sorted(IDS),
    v.get('registry'),
)
check('the room finder is published once as window.analyse_planning.rooms()', v.get('finder'), v.get('finder'))

rooms = {x['name']: x for x in (v.get('rooms') or [])}
check(
    'the wall loops give three rooms of 40.0 / 9.6 / 46.4 m² named from the pins inside them',
    len(rooms) == 3
    and abs(rooms['Room A']['area'] - 40.0) < 0.01
    and abs(rooms['Corridor']['area'] - 9.6) < 0.01
    and abs(rooms['Room B']['area'] - 46.4) < 0.01,
    v.get('rooms'),
)
check(
    'each room knows its doors and its use (Room A office/2 doors, corridor circulation, Room B office/1 door)',
    rooms['Room A']['doors'] == 2
    and rooms['Room A']['use'] == 'office'
    and rooms['Corridor']['use'] == 'corridor'
    and rooms['Room B']['doors'] == 1,
    v.get('rooms'),
)

# a_egress
check(
    'a_egress opens its Escape route sheet and says its legs are an approximation',
    (v.get('egress_sheet') or {}).get('shown')
    and (v.get('egress_sheet') or {}).get('title') == 'Escape route'
    and (v.get('egress_sheet') or {}).get('has_note'),
    v.get('egress_sheet'),
)
tr = v.get('travel') or {}
for name, want in EGRESS.items():
    got = tr.get(name)
    check(
        '%s travels %.2f m to an exit (hand-computed %.4f m, ±0.5 m)' % (name, want, want),
        got is not None and abs(got - want) <= 0.5,
        {'got': got, 'want': want},
    )
check(
    "Room B's route runs through the corridor and Room A: 13.25 m is longer than either of them",
    tr.get('Room B') and tr['Room B'] > tr.get('Corridor', 0) > tr.get('Room A', 0),
    tr,
)
check(
    'one exit door is found (D0, the only one on an exterior wall) and 30 m clears every room',
    v.get('egress_exits') == 1 and v.get('egress_ok') and v.get('egress_rows') == 3,
    {'exits': v.get('egress_exits'), 'ok': v.get('egress_ok'), 'rows': v.get('egress_rows')},
)
check(
    'the worst room is Room B at 13.25 m',
    (v.get('egress_worst') or {}).get('room') == 'Room B'
    and abs((v.get('egress_worst') or {}).get('m', 0) - 13.2456) <= 0.5,
    v.get('egress_worst'),
)
check(
    'a 10 m limit flags Room B and fails the analysis',
    v.get('tight_fail') == 1 and not v.get('tight_ok'),
    {'flagged': v.get('tight_fail'), 'ok': v.get('tight_ok')},
)
check(
    'the worst route is drawn in the viewport as a polyline (4 points: corner, D2, D1, D0)',
    v.get('route_drawn') and v.get('route_pts') == 4,
    {'drawn': v.get('route_drawn'), 'pts': v.get('route_pts')},
)
check(
    'closing the sheet takes the drawn route away again',
    v.get('route_after_close') is False,
    v.get('route_after_close'),
)

# a_access
check(
    'a_access opens its Accessibility sheet',
    (v.get('access_sheet') or {}).get('shown') and (v.get('access_sheet') or {}).get('title') == 'Accessibility',
    v.get('access_sheet'),
)
turns = v.get('turns') or {}
check(
    'the 1.2 m corridor fits a 1.20 m circle and fails the 1.5 m turn, the two rooms pass',
    abs(turns.get('Corridor', 0) - 1.2) < 0.06
    and turns.get('Room A', 0) >= 1.5
    and turns.get('Room B', 0) >= 1.5
    and len(v.get('small_turn') or []) == 1,
    turns,
)
check(
    'exactly one door is too narrow — o9, the 0.70 m leaf that is 0.65 m clear',
    v.get('narrow') == ['o9'] and v.get('access_doors') == 3 and not v.get('access_ok'),
    {'narrow': v.get('narrow'), 'doors': v.get('access_doors')},
)
check(
    'relaxing the check to a 1.0 m turn and a 0.6 m door passes the same plan',
    v.get('access_wide_ok'),
    v.get('access_wide_ok'),
)

# a_occupancy
check(
    'a_occupancy opens its Occupancy sheet with the editable m² per person table',
    (v.get('occ_sheet') or {}).get('shown')
    and (v.get('occ_sheet') or {}).get('title') == 'Occupancy'
    and (v.get('occ_sheet') or {}).get('has_rate_input'),
    v.get('occ_sheet'),
)
pp = v.get('persons') or {}
check('the 40 m² office holds 4 persons at 10 m² each', pp.get('Room A') == 4 and pp.get('Room A/rate') == 10, pp)
check(
    'the corridor is circulation at 0 m²/person and counts nobody',
    pp.get('Corridor') == 0 and pp.get('Corridor/rate') == 0,
    pp,
)
check('the 46.4 m² office rounds up to 5 persons', pp.get('Room B') == 5, pp)
check(
    'the storey and building totals are 9 persons',
    v.get('occ_total') == 9 and (v.get('occ_per_storey') or {}).get('0') == 9,
    {'total': v.get('occ_total'), 'per_storey': v.get('occ_per_storey')},
)
check(
    'an override rate of 5 m²/person doubles the load to 18', v.get('occ_total_dense') == 18, v.get('occ_total_dense')
)
check(
    'editing a rate in the sheet is kept with the drawing in doc.ext.analyse_planning.rates',
    v.get('saved_rate') == 20 and v.get('occ_total_saved') == 5,
    {'saved': v.get('saved_rate'), 'total': v.get('occ_total_saved')},
)

# a_fire
check(
    'a_fire opens its Compartments sheet',
    (v.get('fire_sheet') or {}).get('shown') and (v.get('fire_sheet') or {}).get('title') == 'Compartments',
    v.get('fire_sheet'),
)
comps = v.get('comps') or []
check(
    'the "comp:A" tag and the meta.compartment give two compartment rows: A 49.6 m² over 2 rooms, B 46.4 m²',
    len(comps) == 2
    and comps[0]['id'] == 'A'
    and comps[0]['rooms'] == 2
    and abs(comps[0]['area'] - 49.6) < 0.01
    and comps[1]['id'] == 'B'
    and comps[1]['rooms'] == 1
    and abs(comps[1]['area'] - 46.4) < 0.01,
    comps,
)
check(
    'each compartment carries its longest travel distance from a_egress (A 9.18 m, B 13.25 m)',
    abs(comps[0]['travel'] - 9.1761) <= 0.5 and abs(comps[1]['travel'] - 13.2456) <= 0.5,
    comps,
)
check(
    'the partition door o9 is listed as the fire door between the two compartments',
    v.get('fire_doors') == ['o9'],
    v.get('fire_doors'),
)
check(
    'the 80 mm partition that carries the compartment line is flagged as too light',
    (v.get('comp_walls') or []) == [{'id': 'o6', 't': 0.08, 'weak': True}]
    and any('80 mm thick' in t for t in (v.get('fire_issues') or [])),
    {'walls': v.get('comp_walls'), 'issues': v.get('fire_issues')},
)
check('a 40 m² compartment cap flags both compartments', v.get('fire_small') == 2, v.get('fire_small'))

# ── 3. the assistant twins agree ─────────────────────────────────────────────
t1, _ = assistant('egress_check', {'max': 30}, doc=DOC)
check(
    'egress_check finds the same three rooms and the same single exit',
    'escape routes for 3 rooms, 1 exit door' in t1,
    t1,
)
py_b = None
for line in t1.splitlines():
    if line.strip().startswith('Room B'):
        py_b = float(line.split('m²')[1].split('m to')[0])
check(
    'the Python twin walks Room B out in %.2f m too (±0.5 m of the tab and of the hand figure)' % EGRESS['Room B'],
    py_b is not None and abs(py_b - EGRESS['Room B']) <= 0.5 and abs(py_b - (tr.get('Room B') or 0)) <= 0.5,
    {'python': py_b, 'tab': tr.get('Room B')},
)
check(
    'egress_check says the worst is Room B and reports no issue at 30 m',
    'worst: Room B' in t1 and '0 issue(s)' in t1,
    t1,
)
t1b, _ = assistant('egress_check', {'max': 10}, doc=DOC)
check('egress_check at 10 m flags Room B OVER LIMIT, like the tab', 'OVER LIMIT' in t1b and '1 issue(s)' in t1b, t1b)

t2, _ = assistant('accessibility_check', {'turn': 1.5, 'door_w': 0.85}, doc=DOC)
check(
    'accessibility_check agrees on the counts: 3 rooms, 3 doors, 2 issues',
    'on 3 rooms and 3 doors' in t2 and '2 issue(s)' in t2,
    t2,
)
check(
    'accessibility_check flags the same corridor turning circle and the same 0.65 m door o9',
    'Corridor: 1.20 m turning circle' in t2 and 'o9: 0.65 m clear' in t2,
    t2,
)

t3, _ = assistant('occupancy', {}, doc=DOC)
check(
    'occupancy agrees: Room A 4 persons, Room B 5, corridor n/a, 9 in the building',
    '= ' in t3
    and '4 persons' in t3
    and '5 persons' in t3
    and 'n/a (circulation)' in t3
    and 'building total: 9 persons' in t3,
    t3,
)
t3b, _ = assistant('occupancy', {'rates': {'office': 5}}, doc=DOC)
check('occupancy takes a rates override, like the sheet does', 'building total: 18 persons' in t3b, t3b)

t4, _ = assistant('fire_compartments', {'max_area': 1000, 'max_len': 60}, doc=DOC)
check(
    'fire_compartments agrees: 2 compartments over 3 rooms, 1 fire door, 1 compartment wall',
    '2 fire compartment(s) over 3 rooms' in t4 and '1 fire door(s) needed, 1 compartment wall(s)' in t4,
    t4,
)
check(
    'fire_compartments names o9 as the fire door and o6 as the 80 mm compartment wall',
    'door o9' in t4 and 'FIRE DOOR NEEDED' in t4 and 'wall o6' in t4 and '80 mm' in t4,
    t4,
)
t4b, _ = assistant('fire_compartments', {'max_area': 40}, doc=DOC)
check('fire_compartments at a 40 m² cap flags both compartments, like the tab', t4b.count('over 40 m²') == 2, t4b)

# ── 4. the assistant may press all four icons ────────────────────────────────
for i in IDS:
    txt, d = assistant('press_button', {'id': i, 'args': {'max': 30}}, doc=DOC)
    check(
        'the assistant may press %s and the args ride along to the tab' % i,
        txt.startswith('pressed') and d.ui[-1]['args']['id'] == i and d.ui[-1]['args'].get('args') == {'max': 30},
        (txt, d.ui[-1:]),
    )

import zyg_workflows.arch_assistant_ext.analyse_planning as AP  # noqa: E402

check(
    'BUTTONS lists all four icons and TOOLS the four twins',
    AP.BUTTONS == IDS
    and [t[0]['name'] for t in AP.TOOLS] == ['egress_check', 'accessibility_check', 'occupancy', 'fire_compartments'],
    AP.BUTTONS,
)
check(
    'PROMPT names every default in one line each (30, 1.5, 0.85, the rate table, 1000/60)',
    all(
        s in AP.PROMPT
        for s in (
            'egress_check(max=30)',
            'accessibility_check(turn=1.5, door_w=0.85)',
            'occupancy(rates=None)',
            'fire_compartments(max_area=1000, max_len=60)',
        )
    ),
    AP.PROMPT,
)

finish()
