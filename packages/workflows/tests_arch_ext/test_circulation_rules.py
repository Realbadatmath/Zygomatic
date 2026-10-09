# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_circulation_rules — can a person get to every floor of the building?

No new kinds, so no browser/Blender pass: this family is pure geometry over the
records add_stair / add_elevator / draw_box make. The proof is job 71ac02b0's
own tower — the 285-step stair, the half-height lift, the pool on a deck no
stair reaches — measured by the checks that were silent on the day.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
C = A.EXT_MODULES['circulation_rules']
E = A.EXT_MODULES['envelope_rules']
DR = A.EXT_MODULES['design_rules']


def tower(storeys=20):
    d = A.Drawing(None)
    txt = A.call_tool(
        d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower')
    )
    return d, txt


def findings(d):
    out = []
    for fn in C.DESIGN_CHECKS:
        out.extend(fn(d))
    return out


def codes(d):
    return [f['code'] for f in findings(d)]


def texts(d):
    return ' | '.join(f['text'] for f in findings(d))


# ── the drawing the whole family is about ────────────────────────────────────
d0, txt0 = tower()
env0 = E.group_envelope(d0, 'tower')
check('draw_box drew the 20-storey tower', 'drew group "tower"' in txt0 and env0['storeys'] == 20, txt0[:120])
check('its roof deck is at 54.3 m', abs(env0['top_deck'] - 54.3) < 1e-6, env0)

# ── (a) the 285-step record job 71ac02b0 actually made ───────────────────────
da, _ = tower()
cx, cz = A.cell_centre(*A.parse_cell('FH96'))
giant = da.new(
    'stair_u',
    {'steps': 285, 'rise': 0.18, 'run': 0.28, 'w': 1.2, 'gap': 0.2},
    cx,
    cz,
    0,
    0,
    'mat_concrete',
    grp='tower',
)
ca, ta = codes(da), texts(da)
check('the 285-step stair is a flight-length error', 'circ_flight' in ca, ca)
check('the finding names the 285 steps', '285 steps' in ta, ta)
check('the finding names the 39.8 m flight', '39.8 m' in ta, ta)
check('the finding names the 19 storeys it spans', 'over 19 storeys' in ta, ta)
check('the finding names the record', giant['id'] in ta, ta)
check('a record with no rails is a guarding error', 'circ_stair_guard' in ca and 'has no rails' in ta, ta)
check('one record crossing every storey still counts as reaching them', 'circ_no_stair' not in ca, ca)
check(
    'circulation does NOT repeat the slab_voids crossing check',
    'void_missing' not in ca and 'void_missing' in {f['code'] for f in DR.run_checks(da)},
    (ca, {f['code'] for f in DR.run_checks(da)}),
)

# ── (b) the same tower built by the tools that cannot produce the wrong thing ─
db, _ = tower()
sb = A.call_tool(db, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
# FD96 / FK96: a 1.2 m u stair at FH96 is 3.44 x 2.60 m in plan and needs 1.2 m
# of floor at its foot, so FF96 / FJ96 — the cells live run 038ca075c052 used —
# are refused by add_elevator now. These are the cells it names instead.
lb1 = A.call_tool(db, 'add_elevator', dict(cell='FD96', from_storey=0, to_storey=20))
A.call_tool(db, 'add_elevator', dict(cell='FK96', from_storey=0, to_storey=20))
cb = codes(db)
check('add_stair drew one record per storey', '20 record(s)' in sb, sb[:160])
check('add_elevator serves storeys 0..20', 'storeys 0..20' in lb1, lb1[:160])
check(
    'a stair + two lifts to the deck: continuity is silent',
    'circ_no_stair' not in cb and 'circ_lift_partial' not in cb and 'circ_no_lift' not in cb,
    texts(db),
)
check('per-storey records are never a flight-length error', 'circ_flight' not in cb, texts(db))
check('add_stair draws rails, so guarding is silent', 'circ_stair_guard' not in cb, texts(db))
check('add_stair built the head house, so that is silent', 'circ_head_house' not in cb, texts(db))
check('nothing at all is reported', cb == [], texts(db))

# ── (c) the infinity pool on a deck no stair reaches ─────────────────────────
dc, _ = tower()
A.call_tool(dc, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=19, kind='u'))
pool = A.call_tool(dc, 'add_pool', dict(cell_from='FC104', cell_to='FN108', storey=20, depth=1.5))
cc, tc = codes(dc), texts(dc)
check('add_pool put the pool on the deck', 'pool o' in pool, pool[:120])
check('a stair that stops at storey 19 leaves the occupied deck unreached', 'circ_deck_no_stair' in cc, cc)
check('the deck finding names the pool and the tower', 'carries a pool' in tc and '"tower"' in tc, tc)
check(
    'deck_occupants() sees the pool and not the head house',
    [o['kind'] for o in C.deck_occupants(dc, E, E.group_envelope(dc, 'tower'))] == ['pool'],
    [o['kind'] for o in C.deck_occupants(dc, E, E.group_envelope(dc, 'tower'))],
)
dc2, _ = tower()
A.call_tool(dc2, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
A.call_tool(dc2, 'add_pool', dict(cell_from='FC104', cell_to='FN108', storey=20, depth=1.5))
check('the same pool with a stair to the deck is silent', 'circ_deck_no_stair' not in codes(dc2), texts(dc2))
check('an empty deck needs no stair', 'circ_deck_no_stair' not in codes(db), texts(db))

# ── (d) a shaft that serves half the building ───────────────────────────────
dd, _ = tower()
A.call_tool(dd, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
A.call_tool(dd, 'add_elevator', dict(cell='FD96', from_storey=0, to_storey=10))
cd, td = codes(dd), texts(dd)
check('a lift to storey 10 of a 20-storey tower is an error', 'circ_lift_partial' in cd, cd)
check('the lift finding names what it serves and what it does not', 'serves storeys 0..10' in td and '11..19' in td, td)
de, _ = tower()
A.call_tool(de, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
check(
    'a 20-storey tower with no lift at all is a WARNING, not a second error',
    [f['sev'] for f in findings(de) if f['code'] == 'circ_no_lift'] == ['warn'],
    texts(de),
)
check('and no stair error with it', 'circ_no_stair' not in codes(de), texts(de))

# ── (e) rails switched off on one per-storey record ─────────────────────────
df, _ = tower()
A.call_tool(df, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
victim = [o for o in df.objs if o['kind'] == 'stair_u'][7]
victim['p']['rails'] = 0
cf, tf = codes(df), texts(df)
check('rails=0 on one record is a guarding error', 'circ_stair_guard' in cf, cf)
check('the guarding finding names that record and the fix', victim['id'] in tf and 'rails=1' in tf, tf)

# ── the head house the stair must arrive in ────────────────────────────────
dg, _ = tower()
A.call_tool(dg, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u'))
dg.remove([o for o in dg.objs if o.get('grp') == 'tower head house'])
cg, tg = codes(dg), texts(dg)
check('a stair arriving on the deck with the head house gone is an error', 'circ_head_house' in cg, cg)
check('the head house finding says it arrives in the open', 'in the open' in tg, tg)
check('a stair that stops below the deck needs no head house', 'circ_head_house' not in codes(dc), texts(dc))

# ── (f) a one-storey house, and an empty drawing ───────────────────────────
dh = A.Drawing(None)
A.call_tool(dh, 'draw_box', dict(centre='M20', width=10, depth=8, storeys=1, roof='flat', name='house'))
check('a 1-storey house reports nothing at all', findings(dh) == [], texts(dh))
check('an empty drawing reports nothing at all', findings(A.Drawing(None)) == [], texts(A.Drawing(None)))

# ── the relations, read directly ───────────────────────────────────────────
per = [o for o in db.objs if o['kind'] == 'stair_u']
check(
    'stair_reach of a per-storey record is its own storey and the one above',
    list(C.stair_reach(per[5], 0.0, 2.7)) == [5, 6],
    list(C.stair_reach(per[5], 0.0, 2.7)),
)
check(
    'stair_reach of the 285-step record is every storey 0..19',
    list(C.stair_reach(giant, 0.0, 2.7)) == list(range(0, 20)),
    list(C.stair_reach(giant, 0.0, 2.7)),
)
check('stair_height is steps x rise', abs(C.stair_height(giant) - 51.3) < 1e-6, C.stair_height(giant))
shaft = [o for o in db.objs if o['kind'] == 'elevator_shaft'][0]
check(
    'lift_reach reads the door list', C.lift_reach(shaft, 0.0, 2.7) == list(range(0, 21)), C.lift_reach(shaft, 0.0, 2.7)
)
legacy_shaft = {
    'id': 'oZ',
    'kind': 'elevator_shaft',
    'name': 'shaft',
    'x': 0.0,
    'z': 0.0,
    'y': 0.0,
    'ry': 0.0,
    's': 1,
    'p': {'w': 1.8, 'd': 2.0, 'h': 54.0, 't': 0.2},
}
check(
    'a legacy shaft with no doors counts every storey it crosses',
    C.lift_reach(legacy_shaft, 0.0, 2.7) == list(range(0, 21)),
    C.lift_reach(legacy_shaft, 0.0, 2.7),
)
check(
    '_ranges says contiguous storeys the way a person does',
    C._ranges([5, 6, 7, 11, 12, 19]) == '5..7, 11..12, 19',
    C._ranges([5, 6, 7, 11, 12, 19]),
)

# ── (g) two cores in one plan: the core of live run 038ca075c052, rebuilt ───
# The run put a 1.2 m u stair at FH93 and then sank lift shafts at FF93 and FJ93.
# The flight that climbs to the roof deck is 17 steps, so its plan is 3.44 x 2.60 m
# (x 11.78..15.22) and each 1.8 m shaft (10.6..12.4 / 14.6..16.4) ends up 0.62 m
# inside it. d.new is used deliberately: add_elevator refuses these cells now, so
# the only way to measure the drawing the run actually made is to make it by hand.
STAIR_P = {'steps': 17, 'rise': 0.18, 'run': 0.28, 'w': 1.2, 'gap': 0.2, 'rails': 1}
SHAFT_P = {'w': 1.8, 'd': 2.0, 'h': 55.8, 't': 0.2, 'doors': [0, 1], 'door_side': 'south', 'sh': 2.7}
di, _ = tower()
ui = di.new('stair_u', dict(STAIR_P), 13.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
wi = di.new('elevator_shaft', dict(SHAFT_P), 11.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
ei = di.new('elevator_shaft', dict(SHAFT_P), 15.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
ci, ti = codes(di), texts(di)
check(
    "the run's stair really is 3.44 x 2.60 m in plan",
    [round(v, 2) for v in E.bbox_of(ui)] == [11.78, -58.8, 15.22, -56.2],
    [round(v, 2) for v in E.bbox_of(ui)],
)
check('a stair with a shaft inside it either side is two core clashes', ci.count('circ_core_clash') == 2, ci)
check('the finding measures the 0.62 m the run drew', '0.62 x 2.00 m overlap' in ti, ti)
check(
    'the finding names both records and calls them two cores',
    ui['id'] in ti and wi['id'] in ti and ei['id'] in ti and 'two cores' in ti,
    ti,
)
check('and says the tool refuses it now', 'add_elevator refuses this now' in ti, ti)
check(
    'both clashes are errors',
    [f['sev'] for f in findings(di) if f['code'] == 'circ_core_clash'] == ['error', 'error'],
    ti,
)
check(
    'the west shaft also blocks the floor at the stair foot',
    [f['text'] for f in findings(di) if f['code'] == 'circ_stair_approach']
    and wi['id'] in [f['text'] for f in findings(di) if f['code'] == 'circ_stair_approach'][0],
    ti,
)
check('the east shaft does not: the foot is on the -X side only', ci.count('circ_stair_approach') == 1, ci)

# a partition standing 0.78 m west of the same foot — no shaft, just a wall
dj, _ = tower()
uj = dj.new('stair_u', dict(STAIR_P), 13.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
pj = dj.new('partition', {'len': 3, 'h': 2.5, 't': 0.15}, 11.0, -57.5, 0, 1.5708, 'mat_plaster', grp='tower')
cj, tj = codes(dj), texts(dj)
check('a partition across the stair foot leaves nothing to step onto', 'circ_stair_approach' in cj, cj)
check(
    'the approach finding names the stair, the partition and the 1.2 m',
    uj['id'] in tj and pj['id'] in tj and '1.2 m of floor at its foot' in tj,
    tj,
)
check('a partition is not a core, so no clash is reported with it', 'circ_core_clash' not in cj, cj)
check(
    'the partition really does stand in the zone stairs_vertical names',
    len(A.EXT_MODULES['stairs_vertical'].approach_bboxes(uj)) == 1
    and [round(v, 3) for v in A.EXT_MODULES['stairs_vertical'].approach_bboxes(uj)[0]] == [10.58, -58.8, 11.78, -56.2],
    [round(v, 3) for v in A.EXT_MODULES['stairs_vertical'].approach_bboxes(uj)[0]],
)

# and the tower the tools build: a stair at FH96 with lifts at FD96 / FK96
check(
    'the tool-built tower has neither new finding',
    'circ_core_clash' not in cb and 'circ_stair_approach' not in cb,
    texts(db),
)
check(
    'nor does the one whose stair climbs to a pool deck',
    'circ_core_clash' not in cc and 'circ_stair_approach' not in cc,
    tc,
)
dk, _ = tower()
dk.new('stair_u', dict(STAIR_P), 13.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
dk.new('stair_spiral', {'steps': 16, 'rise': 0.18, 'r': 1.4, 'w': 1.0}, 13.5, -57.5, 0, 0, 'mat_concrete', grp='tower')
check('a stair and a spiral sharing one well is not a core clash', 'circ_core_clash' not in codes(dk), texts(dk))

# ── (h) the floor at the head of the flight (2026-09-16) ───────────────────
# The 09-12 run cut the floor opening as the whole stair bbox + 5 cm on EVERY
# storey, so the only floor at the stair was the treads: every flight arrived
# over the void of the flight below. The tools do not do that — the opening is
# the flights, and the 1.2 m arrival zone beyond the well's -X edge keeps its
# floor — so the defect has to be cut by hand to be measured.
S = A.EXT_MODULES['stairs_vertical']
V = A.EXT_MODULES['slab_voids']


def tools_tower():
    """The brief's drawing: tower + a u stair at FH93 + a lift at FD93. FD is
    clear of the FH93 stair's plan AND of the 1.2 m at its foot; FF93 is not."""
    d, _ = tower()
    A.call_tool(d, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=20, kind='u', width=1.2))
    A.call_tool(d, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=20, w=1.8, depth=2.0, door_side='south'))
    return d


NEW_CODES = (
    'circ_landing_floor',
    'circ_headroom',
    'circ_enclosure',
    'circ_overrun',
    'circ_shaft_in_water',
    'circ_lift_landing',
)

dm = tools_tower()
cm = codes(dm)
check('the tool-built tower + lift reports nothing at all', cm == [], texts(dm))
check('none of the six new codes fires on what the tools build', [k for k in NEW_CODES if k in cm] == [], cm)

m0 = [o for o in dm.objs if o['kind'] == 'stair_u'][0]
hb = S.head_bboxes(m0)
check(
    'head_bboxes gives a u stair ONE zone, on the same -X side as its foot',
    len(hb) == 1 and [round(v, 2) for v in hb[0]] == [round(v, 2) for v in S.approach_bboxes(m0)[0]],
    [[round(v, 2) for v in b] for b in hb],
)
check(
    'and that zone is 1.2 m deep over the well width',
    abs((hb[0][2] - hb[0][0]) - 1.2) < 1e-6 and abs((hb[0][3] - hb[0][1]) - 2.6) < 1e-6,
    [round(v, 3) for v in hb[0]],
)
mstr = dm.new(
    'stair_straight',
    {'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2, 'rails': 1},
    13.5,
    -48.0,
    0,
    0,
    'mat_concrete',
    grp='tower',
)
check(
    'a straight flight climbs AWAY from its foot: head at +X, foot at -X',
    len(S.head_bboxes(mstr)) == 1
    and len(S.approach_bboxes(mstr)) == 2
    and S.head_bboxes(mstr)[0][0] > S.approach_bboxes(mstr)[0][0],
    ([round(v, 2) for v in S.head_bboxes(mstr)[0]], [[round(v, 2) for v in b] for b in S.approach_bboxes(mstr)]),
)
check(
    'a spiral arrives on its own turn — no head zone',
    S.head_bboxes({'kind': 'stair_spiral', 'p': {'r_out': 1.1}, 'x': 0, 'z': 0, 'ry': 0}) == [],
)

dn = tools_tower()
n0 = [o for o in dn.objs if o['kind'] == 'stair_u'][0]
nz = S.head_bboxes(n0)[0]
_ids, _note = V.cut_slab_void(dn, 'tower', 1, nz[0], nz[1], nz[2], nz[3], 'stair')
cn, tn = codes(dn), texts(dn)
check(
    'the void cut over the head landing merged into the stair opening',
    len(V.voids_at(dn, 'tower', 1)) == 2 and 'cut a 4.55 x 2.70 m stair void' in _note,
    _note[:120],
)
check('a flight arriving over the void is a landing error', 'circ_landing_floor' in cn, cn)
check(
    'the landing finding names the record, the storey and the void it lands on',
    n0['id'] in tn and 'storey 1' in tn and '1.2 x 2.6 m of void, no landing' in tn,
    tn,
)
check('and names the tool that cuts the opening', 'cut_floor_opening only over the flights' in tn, tn)
check('only the record that arrives there is named, not the whole stack', cn.count('circ_landing_floor') == 1, cn)
check("the same stair with the tools' own opening is silent", 'circ_landing_floor' not in cm, cm)

# ── (i) a slab left over the flight: headroom 0 ────────────────────────────
do = tools_tower()
o0 = [o for o in do.objs if o['kind'] == 'stair_u'][0]
slab_over = do.new('slab', {'w': 4, 'd': 3, 't': 0.2}, o0['x'], o0['z'], 2.7, 0, 'mat_concrete', grp='tower')
co, to = codes(do), texts(do)
check('a slab written over the flight is a headroom error', 'circ_headroom' in co, co)
check(
    'the headroom finding names the stair, the slab and the overlap',
    o0['id'] in to and slab_over['id'] in to and 'covers 3.2 x 2.6 m of the flight' in to,
    to,
)
check('it names headroom 0 and the cut that fixes it', 'headroom 0' in to and 'cut_floor_opening("tower", 1,' in to, to)
check('the slab under the NEXT flight up is not a headroom error either way', co.count('circ_headroom') == 1, co)
check("the tools' own floors leave every flight open", 'circ_headroom' not in cm, cm)

# ── (j) a shaft that stops level with the deck it serves ───────────────────
dp = tools_tower()
shaft_p = [o for o in dp.objs if o['kind'] == 'elevator_shaft'][0]
check('add_elevator drew 55.8 m of shaft over a 54.3 m deck', shaft_p['p']['h'] == 55.8, shaft_p['p']['h'])
check('so the overrun check is silent on it', 'circ_overrun' not in cm, cm)
shaft_p['p']['h'] = 54.0
cp, tp = codes(dp), texts(dp)
check('a 54.0 m shaft serving a 54.3 m deck is an overrun error', 'circ_overrun' in cp, cp)
check(
    'the overrun finding names the shaft, the deck and how much more it needs',
    shaft_p['id'] in tp and '54.3 m' in tp and 'has to reach 55.5 m (1.5 m more)' in tp,
    tp,
)
check('and names add_elevator as the fix', 'add_elevator(cell, 0, 20)' in tp, tp)

# ── (k) a partition parked in front of the lift doors ──────────────────────
dq = tools_tower()
sq = [o for o in dq.objs if o['kind'] == 'elevator_shaft'][0]
qbb = E.bbox_of(sq)
block = dq.new(
    'partition',
    {'len': 3, 'h': 2.5, 't': 0.15},
    (qbb[0] + qbb[2]) / 2,
    qbb[3] + 0.375,
    7 * 2.7,
    0,
    'mat_plaster',
    grp='tower',
)
cq, tq = codes(dq), texts(dq)
check('a partition 0.3 m in front of the doors is a lift-landing error', 'circ_lift_landing' in cq, cq)
check(
    'the landing finding names the shaft, the storey, the partition and the gap',
    sq['id'] in tq and 'storey 7' in tq and block['id'] in tq and 'stands 0.3 m in front of the doors' in tq,
    tq,
)
check('and names layout_floor as the fix', 'layout_floor(core_from, core_to) leaves the landing free' in tq, tq)
dq.remove([block])
check('removing the partition makes it silent again', codes(dq) == [], texts(dq))
dv_ = tools_tower()
V.cut_slab_void(dv_, 'tower', 7, qbb[0], qbb[3], qbb[2], qbb[3] + 1.8, 'lift')
check('a landing with no floor under it at all is the same code', 'circ_lift_landing' in codes(dv_), texts(dv_))

# ── (l) a stair well open to a fitted-out floor ────────────────────────────
dr_ = tools_tower()
check('a bare shell has no floor for the stair to be open to', 'circ_enclosure' not in cm, cm)
A.call_tool(dr_, 'add_room', dict(cell_from='FD104', cell_to='FM108', storey=3, name='flat'))
cr, tr = codes(dr_), texts(dr_)
check(
    'a stair well open on four sides of a fitted-out floor is a warning',
    [f['sev'] for f in findings(dr_) if f['code'] == 'circ_enclosure'] == ['warn'],
    tr,
)
check(
    'the enclosure finding names the storey, the open sides and the fix',
    'storey 3' in tr and '4 of its 4 plan sides' in tr and 'add_room around it or accept (fire separation)' in tr,
    tr,
)
check('only the fitted-out storey is measured', cr.count('circ_enclosure') == 1, cr)
ds_ = tools_tower()
st3 = [o for o in ds_.objs if o['kind'] == 'stair_u' and abs(o['y'] - 3 * 2.7) < 1e-6][0]
sbb = E.bbox_of(st3)
for wx, wz, wry in (
    (sbb[0] - 0.1, (sbb[1] + sbb[3]) / 2, 1.5708),
    (sbb[2] + 0.1, (sbb[1] + sbb[3]) / 2, 1.5708),
    ((sbb[0] + sbb[2]) / 2, sbb[1] - 0.1, 0.0),
    ((sbb[0] + sbb[2]) / 2, sbb[3] + 0.1, 0.0),
):
    ds_.new('partition', {'len': 4, 'h': 2.7, 't': 0.15}, wx, wz, 3 * 2.7, wry, 'mat_plaster', grp='tower')
check('the same stair walled on four sides is silent', 'circ_enclosure' not in codes(ds_), texts(ds_))

# ── (m) a core coming up through the pool ──────────────────────────────────
dt_ = tools_tower()
A.call_tool(dt_, 'add_pool', dict(cell_from='FB92', cell_to='FG96', storey=20, depth=1.5))
ct, tt = codes(dt_), texts(dt_)
check('a lift shaft under the water is an error', 'circ_shaft_in_water' in ct, ct)
check(
    'the water finding names the shaft, the pool and the overlap',
    'lift shaft stands in the water' in tt and '1.80 x 2.00 m of overlap' in tt,
    tt,
)
check(
    'the stair of the same deck is left to deck_rules: one voice per pair',
    ct.count('circ_shaft_in_water') == 1
    and any(f['code'] == 'deck_pool_core' for f in A.EXT_MODULES['deck_rules'].check_roof_deck(dt_)),
    ct,
)
check('a pool clear of both cores is silent', 'circ_shaft_in_water' not in codes(dc2), texts(dc2))

# ── (n) the live tower the run actually made ───────────────────────────────
import json  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')
dfix = A.Drawing(json.load(open(FIX)))
cfix = codes(dfix)
# 20 stair records, each arriving over the opening cut for the flight below —
# the defect this whole section is about, capped to 8 + the "and N more" line.
check(
    'the live tower reports the arrival landing of every flight',
    cfix.count('circ_landing_floor') == 8 and 'circ_more' in cfix,
    [c for c in cfix if c.startswith('circ_')],
)
check(
    'both of its lift shafts have something in front of the deck doors',
    cfix.count('circ_lift_landing') == 2,
    [f['text'] for f in findings(dfix) if f['code'] == 'circ_lift_landing'],
)
check('its stair well IS enclosed — it stands between the two shafts', 'circ_enclosure' not in cfix, cfix)
check(
    'its shafts have their overrun, and nothing stands in the pool',
    'circ_overrun' not in cfix and 'circ_shaft_in_water' not in cfix,
    cfix,
)
check('no headroom error: the openings really are cut over the flights', 'circ_headroom' not in cfix, cfix)
check(
    'the collapsed core clash still reads as two pairs over a storey range',
    cfix.count('circ_core_clash') == 2
    and 'storeys' in [f['text'] for f in findings(dfix) if f['code'] == 'circ_core_clash'][0],
    [f['text'] for f in findings(dfix) if f['code'] == 'circ_core_clash'],
)

# ── the family contract ────────────────────────────────────────────────────
check(
    'DESIGN_CHECKS exports the twelve checks',
    [f.__name__ for f in C.DESIGN_CHECKS]
    == [
        'check_continuity',
        'check_flights',
        'check_stair_guarding',
        'check_head_house',
        'check_core_clash',
        'check_stair_approach',
        'check_landing_floor',
        'check_headroom',
        'check_enclosure',
        'check_overrun',
        'check_shaft_in_water',
        'check_lift_landing',
    ],
    [f.__name__ for f in C.DESIGN_CHECKS],
)
check(
    'every check caps itself at 8 findings plus one "and N more"',
    all(len([f for f in fn(dfix) if f['code'] != 'circ_more']) <= 8 for fn in C.DESIGN_CHECKS),
    {fn.__name__: len(fn(dfix)) for fn in C.DESIGN_CHECKS},
)
check('no check raises on a drawing with no envelope at all', all(fn(A.Drawing(None)) == [] for fn in C.DESIGN_CHECKS))
check('design_rules collects all twelve', all(f in DR.contributed() for f in C.DESIGN_CHECKS))
check(
    'run_checks reports the deck error of the pool tower',
    'circ_deck_no_stair' in {f['code'] for f in DR.run_checks(dc)},
    {f['code'] for f in DR.run_checks(dc)},
)
check(
    'the tool-built tower passes run_checks with no circulation finding',
    [f for f in DR.run_checks(db) if f['code'].startswith('circ_')] == [],
    [f['text'] for f in DR.run_checks(db) if f['code'].startswith('circ_')],
)
check('PROMPT is one paragraph under 500 chars', 0 < len(C.PROMPT) <= 500 and '\n' not in C.PROMPT, len(C.PROMPT))
check('two worked examples', len(C.EXAMPLES) >= 2 and all(x.get('ask') and x.get('calls') for x in C.EXAMPLES))
check('the family owns no kinds and no tools', C.KINDS == {} and C.TOOLS == [] and C.OPENINGS == [])

finish()
