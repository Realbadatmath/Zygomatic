# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_deck_rules — the top deck read as ONE room.

water_leisure.check_infinity_pools says the pool is a pool. It cannot say the
pool is 0.6 m off a lift shaft, that there is nowhere to walk on its east side,
that its trough hangs past the facade, that an air-handling unit sits in the
view, that the head house has no door or that the stair arrives over a void.
Every check here is an A/B pair: the same drawing, right and then wrong, so a
silent check is proved silent for the right reason.

No new kinds, so no browser / Blender pass — pure geometry over the records
draw_box / add_stair / add_elevator / add_infinity_pool make, plus the live
tower fixture of 2026-09-11.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['deck_rules']
W = A.EXT_MODULES['water_leisure']
E = A.EXT_MODULES['envelope_rules']
FR = A.EXT_MODULES['finish_rules']
DR = A.EXT_MODULES['design_rules']

DECK_Y = 54.3  # the top deck of the 20-storey reference tower
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')


# ── the reference tower: 20 x 20 x 20 storeys, a stair and a lift to the deck ─
def tower(pool=None):
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
    A.call_tool(d, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=20, kind='u', width=1.2))
    A.call_tool(d, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=20, w=1.8, depth=2.0, door_side='south'))
    txt = A.call_tool(d, 'add_infinity_pool', pool) if pool else ''
    return d, txt


def mk_pool(d, x0, z0, x1, z1, inf='s', coping=0.03, depth=1.4, raised=0.12, y=DECK_Y):
    """A deck-level infinity pool placed by hand, so the A/B geometry is exact."""
    opp = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}[inf]
    p = {
        'w': round(x1 - x0, 4),
        'd': round(z1 - z0, 4),
        'depth': depth,
        'coping': coping,
        'raised': raised,
        'inf': inf,
        'steps': opp,
        'sunk': True,
    }
    return d.new('pool', p, (x0 + x1) / 2, (z0 + z1) / 2, y, 0.0, W.INF_TILE, name='infinity pool', grp='infinity pool')


def codes(d):
    return [f['code'] for f in M.check_roof_deck(d)]


def texts(d, code):
    return ' | '.join(f['text'] for f in M.check_roof_deck(d) if f['code'] == code)


# ── the family contract ──────────────────────────────────────────────────────
print('contract')
check(
    '(0) check-only family: no kinds, no openings, no tools, empty PROMPT',
    M.KINDS == {} and M.OPENINGS == [] and M.TOOLS == [] and M.PROMPT == '',
    (M.KINDS, M.OPENINGS, M.TOOLS, repr(M.PROMPT)),
)
check(
    '(0) one design check, named check_roof_deck',
    [f.__name__ for f in M.DESIGN_CHECKS] == ['check_roof_deck'],
    [f.__name__ for f in M.DESIGN_CHECKS],
)
check(
    '(0) it never raises: an empty drawing and a drawing of junk both answer with a list',
    M.check_roof_deck(A.Drawing(None)) == []
    and isinstance(
        M.check_roof_deck(A.Drawing({'objects': [{'id': 'x', 'kind': 'pool', 'p': {}, 'x': 0, 'y': 0, 'z': 0}]})), list
    ),
    M.check_roof_deck(A.Drawing(None)),
)
bad = A.Drawing(None)
bad.objs.append({'id': 'oX', 'kind': 'pool', 'p': None, 'x': 'no', 'y': None, 'z': 0, 'grp': ''})
out_bad = M.check_roof_deck(bad)
check(
    '(0) a malformed record gives at most an info finding, never a traceback',
    isinstance(out_bad, list) and all(f['sev'] in ('error', 'warn', 'info') for f in out_bad),
    out_bad,
)
check(
    '(0) every finding is {sev, code, text} with a deck_ code and a fix in the text',
    all(
        set(f) >= {'sev', 'code', 'text'} and f['code'].startswith('deck_') and '—' in f['text']
        for f in M.check_roof_deck(A.Drawing(json.load(open(FIX))))
    ),
    M.check_roof_deck(A.Drawing(json.load(open(FIX)))),
)


# ── (a) the pool keeps 1.5 m clear of the cores ──────────────────────────────
print('(a) pool vs core')
d_ok, txt_ok = tower(dict(cell_from='FD100', cell_to='FM109', view='south', storey=20))
check(
    '(a) add_infinity_pool FD100..FM109 on the tower with a stair, a lift and a head house is BUILT',
    not txt_ok.startswith('refused') and [o for o in d_ok.objs if o['kind'] == 'pool'],
    txt_ok[:200],
)
check(
    '(a) ...and deck_pool_core is silent: 5.2 m to the stair, 5.5 m to the shaft, 4.4 m to the head house',
    'deck_pool_core' not in codes(d_ok),
    codes(d_ok),
)
d_bad, _ = tower()
mk_pool(d_bad, 9.0, -56.0, 19.0, -50.0)  # FD95..FM100, in the core zone
check(
    '(a) the same pool drawn by hand at FD95..FM100 -> deck_pool_core', 'deck_pool_core' in codes(d_bad), codes(d_bad)
)
check(
    '(a) ...the error gives the gap, names the core and names add_infinity_pool',
    'm from' in texts(d_bad, 'deck_pool_core') and 'add_infinity_pool' in texts(d_bad, 'deck_pool_core'),
    texts(d_bad, 'deck_pool_core'),
)


# ── (b) a walkway on every side that is not the weir ─────────────────────────
print('(b) walkway')
d_w1, _ = tower()
mk_pool(d_w1, 12.47, -51.0, 22.47, -41.6)  # coping 0.03 -> 0.50 m to the east edge (x 23)
check(
    '(b) a pool whose east coping is 0.50 m from the east deck edge -> deck_walkway east',
    'deck_walkway' in codes(d_w1) and 'east' in texts(d_w1, 'deck_walkway') and '0.50 m' in texts(d_w1, 'deck_walkway'),
    texts(d_w1, 'deck_walkway') or codes(d_w1),
)
d_w2, _ = tower()
mk_pool(d_w2, 11.47, -51.0, 21.47, -41.6)  # 1.50 m to the east edge
check(
    '(b) the same pool 1 m further west (1.50 m of walkway) -> silent', 'deck_walkway' not in codes(d_w2), codes(d_w2)
)
check(
    '(b) the west (9.44 m) and north (9.97 m) walkways are never reported, nor the south weir side',
    'west' not in texts(d_w1, 'deck_walkway')
    and 'north' not in texts(d_w1, 'deck_walkway')
    and 'south' not in texts(d_w1, 'deck_walkway'),
    texts(d_w1, 'deck_walkway'),
)


# ── (c) the weir is ON the edge, the trough inside it ────────────────────────
print('(c) weir edge')
d_c1, _ = tower()
mk_pool(d_c1, 9.0, -53.4, 19.0, -44.0)  # 2.97 m back from the south edge
check(
    '(c) a south weir 2.97 m inside the south deck edge -> deck_weir_edge',
    'deck_weir_edge' in codes(d_c1) and '2.97 m' in texts(d_c1, 'deck_weir_edge'),
    texts(d_c1, 'deck_weir_edge') or codes(d_c1),
)
d_c2, _ = tower()
mk_pool(d_c2, 9.0, -51.0, 19.0, -41.6)  # where add_infinity_pool puts it: 0.57 m
check(
    '(c) the weir where add_infinity_pool puts it (0.57 m, INF_INSET) -> silent',
    'deck_weir_edge' not in codes(d_c2),
    codes(d_c2),
)
check('(c) the tool-built pool of (a) is silent too', 'deck_weir_edge' not in codes(d_ok), codes(d_ok))
d_c3, _ = tower()
mk_pool(d_c3, 9.0, -51.0, 19.0, -40.8)  # 0.2 m of trough past the facade (the 09-11 fault)
check(
    '(c) a pool hanging 0.20 m past the facade -> deck_weir_edge naming the overhang',
    'deck_weir_edge' in codes(d_c3) and 'hangs' in texts(d_c3, 'deck_weir_edge'),
    texts(d_c3, 'deck_weir_edge') or codes(d_c3),
)


# ── (d) rooftop plant on the side away from the view ─────────────────────────
print('(d) plant side')
HVAC = {'w': 1.2, 'd': 0.8, 'h': 0.9}
d_p1, _ = tower()
mk_pool(d_p1, 9.0, -51.0, 19.0, -45.0)
d_p1.new('hvac_unit', dict(HVAC), 14.0, -43.0, DECK_Y, 0.0, None, name='ahu', grp='rooftop_plant')
check(
    '(d) an hvac_unit on the south (view) side of the pool -> deck_plant_side',
    'deck_plant_side' in codes(d_p1) and 'view side' in texts(d_p1, 'deck_plant_side'),
    texts(d_p1, 'deck_plant_side') or codes(d_p1),
)
check(
    '(d) ...and it names add_rooftop_plant and says the tool takes no side argument',
    'add_rooftop_plant' in texts(d_p1, 'deck_plant_side') and 'no side argument' in texts(d_p1, 'deck_plant_side'),
    texts(d_p1, 'deck_plant_side'),
)
d_p2, _ = tower()
mk_pool(d_p2, 9.0, -51.0, 19.0, -45.0)
d_p2.new('hvac_unit', dict(HVAC), 14.0, -55.0, DECK_Y, 0.0, None, name='ahu', grp='rooftop_plant')
check('(d) the same unit north of the pool, 3.6 m clear -> silent', 'deck_plant_side' not in codes(d_p2), codes(d_p2))
d_p3, _ = tower()
mk_pool(d_p3, 9.0, -51.0, 19.0, -45.0)
d_p3.new('hvac_unit', dict(HVAC), 14.0, -52.0, DECK_Y, 0.0, None, name='ahu', grp='rooftop_plant')
check(
    '(d) north of the pool but only 0.6 m off the water -> deck_plant_side (2 m clear is the rule)',
    'deck_plant_side' in codes(d_p3) and 'from the water' in texts(d_p3, 'deck_plant_side'),
    texts(d_p3, 'deck_plant_side') or codes(d_p3),
)


# ── (e) a head house you can get out of ──────────────────────────────────────
print('(e) head house door')
check(
    '(e) the tower head house add_stair builds HAS a door -> silent',
    'deck_headhouse_door' not in codes(d_ok),
    codes(d_ok),
)
d_e, _ = tower(dict(cell_from='FD100', cell_to='FM109', view='south', storey=20))
doors = [o for o in d_e.objs if str(o.get('grp') or '').endswith(' head house') and o['kind'] in M.DOOR_KINDS]
for o in doors:
    d_e.objs.remove(o)
check(
    '(e) take the door out of the head house -> deck_headhouse_door',
    doors and 'deck_headhouse_door' in codes(d_e),
    (len(doors), codes(d_e)),
)
# the storey named is the head house's OWN storey (0), not the tower's 20: that is
# what arch_assistant.storey_index counts and what add_opening accepts — the brief's
# "storey=<N>" would be refused with 'has no wall on storey 20 (it has storeys 0..0)'
check(
    '(e) ...the error names add_opening with the group, a side and a storey add_opening takes',
    all(
        w in texts(d_e, 'deck_headhouse_door')
        for w in ('add_opening(group="tower head house"', 'side=', 'storey=0', 'kind="door"')
    ),
    texts(d_e, 'deck_headhouse_door'),
)
back = A.call_tool(d_e, 'add_opening', {'group': 'tower head house', 'side': 'south', 'storey': 0, 'kind': 'door'})
check(
    '(e) add_opening puts a door back and the check falls silent again',
    not back.startswith('refused') and 'deck_headhouse_door' not in codes(d_e),
    (back[:200], codes(d_e)),
)


# ── (f) loungers: off the water, out of the weir strip, facing the view ──────
print('(f) loungers')
LG = {'w': 0.7, 'd': 2.0, 'h': 0.4}
d_f1, _ = tower()
mk_pool(d_f1, 9.0, -51.0, 19.0, -45.0)
d_f1.new('sun_lounger', dict(LG), 14.0, -43.0, DECK_Y, -math.pi / 2, None, name='lounger', grp='deck')
check(
    '(f) a lounger in the south weir strip between the pool and the edge -> deck_lounger_placement',
    'deck_lounger_placement' in codes(d_f1) and 'weir strip' in texts(d_f1, 'deck_lounger_placement'),
    texts(d_f1, 'deck_lounger_placement') or codes(d_f1),
)
d_f2, _ = tower()
mk_pool(d_f2, 9.0, -51.0, 19.0, -45.0)
d_f2.new('sun_lounger', dict(LG), 14.0, -53.0, DECK_Y, -math.pi / 2, None, name='lounger', grp='deck')
check(
    '(f) the same lounger north of the pool, 1 m off the water, facing the south view -> silent',
    'deck_lounger_placement' not in codes(d_f2),
    codes(d_f2),
)
d_f3, _ = tower()
mk_pool(d_f3, 9.0, -51.0, 19.0, -45.0)
d_f3.new('sun_lounger', dict(LG), 14.0, -51.3, DECK_Y, -math.pi / 2, None, name='lounger', grp='deck')
check(
    '(f) a lounger 0.30 m off the water -> deck_lounger_placement (0.5 m of wet deck)',
    'deck_lounger_placement' in codes(d_f3) and 'from the water' in texts(d_f3, 'deck_lounger_placement'),
    texts(d_f3, 'deck_lounger_placement') or codes(d_f3),
)
d_f4, _ = tower()
mk_pool(d_f4, 9.0, -51.0, 19.0, -45.0)
d_f4.new('sun_lounger', dict(LG), 14.0, -53.0, DECK_Y, 0.0, None, name='lounger', grp='deck')
check(
    '(f) the same lounger turned to face east -> one grouped facing warn naming the weir ry',
    'deck_lounger_placement' in codes(d_f4)
    and 'face away from the south view' in texts(d_f4, 'deck_lounger_placement'),
    texts(d_f4, 'deck_lounger_placement') or codes(d_f4),
)
check(
    '(f) ...the facing rule is not put to a parasol, which has no front',
    'umbrella' not in M.FACE_KINDS and 'parasol' not in M.FACE_KINDS,
    sorted(M.FACE_KINDS),
)
check(
    '(f) the tool-built ensemble of (a) places its own loungers correctly -> silent',
    'deck_lounger_placement' not in codes(d_ok),
    codes(d_ok),
)


# ── (g) guarding: reuse, do not repeat ───────────────────────────────────────
print('(g) guarding')
g_ok = codes(d_ok)
fin_sides = M._finish_sides(d_ok)
guard_txt = texts(d_ok, 'deck_guard_all')
check(
    '(g) on the tower finish_rules already names the east and west deck edges',
    fin_sides == {'e', 'w'},
    sorted(fin_sides),
)
check(
    '(g) deck_guard_all says nothing about east or west — no duplicate of finish_deck_guard',
    'east' not in guard_txt and 'west' not in guard_txt,
    guard_txt,
)
check(
    '(g) it DOES name the north edge, which nothing else reports: 20 m, 0% guarded',
    'deck_guard_all' in g_ok and 'north edge' in guard_txt and '20.00 m' in guard_txt,
    guard_txt,
)
check(
    '(g) ...and the south edge is silent: add_infinity_pool built the glass balustrade there',
    guard_txt.count('deck') and 'south edge' not in guard_txt,
    guard_txt,
)
check(
    '(g) the measurement is analyse_geometry.coverage, not a copy: G.coverage is called',
    'coverage' in M._check_guard_all.__code__.co_names and 'check_deck_guarding' in M._finish_sides.__code__.co_names,
    (M._check_guard_all.__code__.co_names, M._finish_sides.__code__.co_names),
)
# add_parapet must be called BEFORE the pool: its own "top storey" is the highest
# wall of the group, and the pool's glass balustrade IS a wall on the deck, so
# after the pool it stacks one parapet on top of the balustrade at 55.4 m
# (balconies_facade.py:246). That is its bug, not this check's — see the report.
d_g, _ = tower(None)
par = A.call_tool(d_g, 'add_parapet', {'group': 'tower', 'height': 1.1})
txt_g = A.call_tool(d_g, 'add_infinity_pool', dict(cell_from='FD100', cell_to='FM109', view='south', storey=20))
check(
    '(g) add_parapet("tower", 1.1) closes every edge -> deck_guard_all silent',
    '4 walls' in par and not txt_g.startswith('refused') and 'deck_guard_all' not in codes(d_g),
    (par[:90], codes(d_g)),
)


# ── (h) the stair arrives on floor ───────────────────────────────────────────
print('(h) stair arrival')
check(
    '(h) on the tower the top stair lands on roof o385 at 54.3 m -> silent',
    'deck_stair_arrival' not in codes(d_ok),
    codes(d_ok),
)


# ── (i) the live tower fixture of 2026-09-11 ─────────────────────────────────
print('(i) fixture live_tower_20260911')
dfx = A.Drawing(json.load(open(FIX)))
fx = M.check_roof_deck(dfx)
fx_codes = sorted(f['code'] for f in fx)
# WHY each of these: the fixture's pool is 4.6 m west / 2.6 m east / 13.6 m north
# of the deck edges (walkway ok), its coping stands 0.1 m off the south facade
# with the basin inside it (weir ok), 6.5 m from the nearest shaft (core ok),
# raised == depth so nothing hangs into storey 19 (tank ok), the plant group is
# 3.0-4.0 m NORTH of the water (plant ok), four 1.1 m parapets run all round
# (guard ok) and the head house carries door o333 (door ok).
check(
    '(i) the fixture raises exactly two findings: the stair arrival and the lounger facing',
    fx_codes == ['deck_lounger_placement', 'deck_stair_arrival'],
    [(f['sev'], f['code']) for f in fx],
)
check(
    '(i) ...one error: stair o247 arrives at 54.30 m over the lift void — o332 is the head-house lid at 57.2',
    [f for f in fx if f['sev'] == 'error']
    and fx[0]['code'] == 'deck_stair_arrival'
    and 'o247' in fx[0]['text']
    and '54.30' in fx[0]['text'],
    [f['text'] for f in fx if f['sev'] == 'error'],
)
check(
    '(i) ...one warn: the four loungers all carry ry 0 (east) while the weir is south (_FACE_X["s"])',
    [f for f in fx if f['sev'] == 'warn' and f['code'] == 'deck_lounger_placement']
    and '4 deck seats' in texts(dfx, 'deck_lounger_placement')
    and all(abs(o.get('ry') or 0.0) < 1e-9 for o in dfx.objs if o['kind'] == 'sun_lounger'),
    texts(dfx, 'deck_lounger_placement'),
)
check(
    '(i) the check is silent on everything the fixture gets right',
    not any(
        c in fx_codes
        for c in (
            'deck_pool_core',
            'deck_walkway',
            'deck_weir_edge',
            'deck_tank_clash',
            'deck_plant_side',
            'deck_guard_all',
            'deck_headhouse_door',
            'deck_check_failed',
        )
    ),
    fx_codes,
)
base = sorted({f['code'] for f in DR.run_checks(dfx)})
check(
    '(i) the 2026-09-11 baseline is untouched: circ_core_clash, circ_stair_approach, env_facade_partition, '
    'the programme error, undersize, unsupported and pool_entry all still there',
    all(c in base for c in ('circ_core_clash', 'circ_stair_approach', 'env_facade_partition', 'pool_entry')),
    base,
)
check(
    '(i) design_check carries the new codes through the registry',
    'deck_stair_arrival' in base and 'deck_lounger_placement' in base,
    base,
)


# ── (j) the cap: never more than 8 findings ──────────────────────────────────
print('(j) cap')
d_j, _ = tower()
mk_pool(d_j, 9.0, -56.0, 19.0, -44.0)  # in the core AND back from the weir
for i in range(14):
    d_j.new('sun_lounger', dict(LG), 5.0 + i * 0.9, -43.0, DECK_Y, 0.0, None, name=f'lg{i}', grp='deck')
j = M.check_roof_deck(d_j)
check(
    '(j) a deck full of faults is capped at 8 findings + one "and N more" info',
    len(j) <= M.MAX_FINDINGS + 1 and j[-1]['code'] == 'deck_more' and 'more deck finding' in j[-1]['text'],
    [(f['sev'], f['code']) for f in j],
)
check(
    '(j) errors are never pushed out of the cap by warns',
    [f['sev'] for f in j] == sorted([f['sev'] for f in j], key=lambda s: M.SEV_RANK[s]),
    [f['sev'] for f in j],
)


# ── (k) add_infinity_pool refuses a bad position, spending no draw call ──────
print('(k) tool-level refusals')
d_k1, _ = tower()
n0 = len(d_k1.objs)
r1 = A.call_tool(d_k1, 'add_infinity_pool', dict(cell_from='FD95', cell_to='FM100', view='south', storey=20))
check(
    '(k) a pool in the core zone is REFUSED, and not one record is made',
    r1.startswith('refused') and len(d_k1.objs) == n0,
    (r1[:260], len(d_k1.objs) - n0),
)
check(
    '(k) ...the refusal gives the block, the gap, the core, its cell and a cell range to use instead',
    all(w in r1 for w in ('FD95..FM100', 'm of', 'FH95', 'use rows >=', 'e.g.')),
    r1,
)
d_k2, _ = tower()
n0 = len(d_k2.objs)
r2 = A.call_tool(d_k2, 'add_infinity_pool', dict(cell_from='FG100', cell_to='FP109', view='south', storey=20))
check(
    '(k) a pool leaving 0.97 m on its east side is REFUSED with a block that does leave 2 m',
    r2.startswith('refused') and 'walkway is 1.2 m' in r2 and 'east' in r2 and 'e.g.' in r2 and len(d_k2.objs) == n0,
    (r2[:280], len(d_k2.objs) - n0),
)
check('(k) ...and only the weir side is exempt from that rule', 'south (weir) side is exempt' in r2, r2)
check('(k) the good position of (a) is NOT refused', not txt_ok.startswith('refused'), txt_ok[:120])

# the deck that cannot do better is drawn anyway, with the shortfall in the reply:
# a 10 x 10 m deck holding an 8 m pool has 1.0 m on each side and no whole-cell
# placement gives 1.2 — refusing there would leave the model nothing to do.
ds = A.Drawing(None)
A.call_tool(ds, 'draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat', 'name': 'blk'})
n0 = len(ds.objs)
txt_s = A.call_tool(ds, 'add_infinity_pool', {'cell_from': 'D7', 'cell_to': 'K13', 'view': 'south', 'storey': 3})
check(
    '(k) a 10 x 10 deck with 1.0 m each side is still BUILT (no whole-cell block does better)',
    not txt_s.startswith('refused') and len(ds.objs) > n0,
    txt_s[:200],
)
check(
    '(k) ...and the reply carries the shortfall, pointing at deck_walkway',
    'NOTE: only 0.97 m of deck on the west side' in txt_s  # 1.0 m less the coping
    and 'NOTE: only 0.97 m of deck on the east side' in txt_s
    and 'deck_walkway' in txt_s,
    txt_s[-400:],
)
check('(k) ...which design_check then reports as an error, so nothing is lost', 'deck_walkway' in codes(ds), codes(ds))

d_k3, _ = tower()
d_k3.new('hvac_unit', dict(HVAC), 5.0, -46.0, DECK_Y, 0.0, None, name='ahu', grp='rooftop_plant')
r3 = A.call_tool(d_k3, 'add_infinity_pool', dict(cell_from='FD100', cell_to='FM109', view='south', storey=20))
check(
    '(k) plant already standing in the view is NOT a refusal — the pool is built and the reply says so',
    not r3.startswith('refused') and 'in the view the pool was made for' in r3 and 'add_rooftop_plant' in r3,
    r3[-320:],
)
check('(k) ...and design_check agrees with the reply', 'deck_plant_side' in codes(d_k3), codes(d_k3))

finish()
