# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_clash_rules — nothing solid passes through something else solid.

The operator's words: "avoid any defects like stairs crossing through walls".
Before today the only clash the studio could see was core-vs-core
(circulation_rules.check_core_clash, stair-vs-shaft only), and it said it eight
times for one defect. This file proves the new gate:

  · clash_rules.check_clashes  — a role matrix over every solid record
    (core / wall / column / furniture / water / tree / canopy), one finding per
    record, the worst overlap it is party to.
  · circulation_rules.check_core_clash — ONE line per clashing PAIR of cores
    now, naming the storey range, instead of one per stair record.
  · interior_rooms.t_add_room / floor_layouts.t_layout_floor — refuse (or keep
    out) before the bad records exist, rather than after.

No new kinds, so no browser/Blender pass: this family draws nothing.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_clash_rules.py
"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['clash_rules']
C = A.EXT_MODULES['circulation_rules']
E = A.EXT_MODULES['envelope_rules']

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')


def tower(storeys=20):
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    return d


def clashes(d, code=None):
    out = M.check_clashes(d)
    return [f for f in out if code is None or f['code'] == code]


def texts(fs):
    return ' | '.join(f['text'] for f in fs)


# ── the family contract ──────────────────────────────────────────────────────
check('clash_rules is loaded as a family', M is not None and hasattr(M, 'check_clashes'))
check(
    'it is check-only: no kinds, no tools, no openings, no prompt',
    M.KINDS == {} and M.TOOLS == [] and M.OPENINGS == [] and M.PROMPT == '',
    (len(M.KINDS), len(M.TOOLS), len(M.OPENINGS), len(M.PROMPT)),
)
check('its one design check is registered', M.DESIGN_CHECKS == [M.check_clashes], M.DESIGN_CHECKS)
check(
    'design_rules.run_checks reaches it',
    any(fn is M.check_clashes for fam in A.EXT_MODULES.values() for fn in getattr(fam, 'DESIGN_CHECKS', [])),
)

# a check must NEVER raise, whatever it is handed
for junk in (A.Drawing(None), A.Drawing({'objects': [{'id': 'oX', 'kind': 'wall'}]})):
    try:
        M.check_clashes(junk)
        ok = True
    except Exception as exc:  # pragma: no cover
        ok = str(exc)
    check('check_clashes survives a drawing with %d record(s)' % len(junk.objs), ok is True, ok)


# ── (a) a partition drawn straight through a stair ───────────────────────────
da = tower()
said_stair = A.call_tool(da, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=1, kind='u'))
stair = [o for o in da.objs if o['kind'].startswith('stair_')][-1]
sb = E.bbox_of(stair)
check('add_stair FH93 drew the stair', not said_stair.startswith('refused'), said_stair[:120])
scx, scz = (sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2
bad_part = da.new('partition', {'len': 6, 'h': 2.7, 't': 0.1}, scx, scz, 0, 0, 'mat_plaster', 'wall through stair', 'r')
fa = clashes(da, 'clash_core_wall')
check('(a) a partition across the stair plan is a clash_core_wall', len(fa) == 1, [f['code'] for f in clashes(da)])
ta = texts(fa)
check('(a) the finding names both records', stair['id'] in ta and bad_part['id'] in ta, ta)
check('(a) the finding names the overlap in metres and the storey', ' m overlap on storey 0' in ta, ta)
check('(a) the finding tells the operator what to move', 'move the wall' in ta, ta)
check('(a) it is an error, so done() is blocked', all(f['sev'] == 'error' for f in fa), fa)

# B: the same partition 3 m clear of the stair is silent
bad_part['z'] = scz + (sb[3] - sb[1]) / 2 + 3.0
check(
    '(a-B) moved 3 m clear of the stair, the same partition is silent',
    clashes(da, 'clash_core_wall') == [],
    texts(clashes(da)),
)

# and a wall that merely runs ALONG the core edge is touching, not crossing
edge = da.new(
    'partition', {'len': 6, 'h': 2.7, 't': 0.1}, scx, sb[3], 0, 0, 'mat_plaster', 'wall on the stair edge', 'r'
)
check(
    '(a-C) a wall on the core edge is touching, not a clash', clashes(da, 'clash_core_wall') == [], texts(clashes(da))
)
da.objs.remove(edge)


# ── (b) a sofa straddling the south facade wall ──────────────────────────────
db = tower()
w2 = db.find('o2')
wb = E.bbox_of(w2)
check(
    'o2 is the south facade wall',
    w2['kind'] == 'wall' and 'south' in (w2.get('name') or ''),
    (w2['kind'], w2.get('name')),
)
sofa = db.new(
    'sofa',
    {'w': 2.2, 'd': 0.9, 'h': 0.85},
    (wb[0] + wb[2]) / 2,
    (wb[1] + wb[3]) / 2,
    0,
    0,
    'mat_timber',
    'sofa through the wall',
    'r',
)
fb = clashes(db, 'clash_furniture_wall')
check('(b) a sofa straddling wall o2 is a clash_furniture_wall', len(fb) == 1, [f['code'] for f in clashes(db)])
tb = texts(fb)
check('(b) the finding names the sofa and the wall', sofa['id'] in tb and 'o2' in tb, tb)
check('(b) "sofa" is spelled out by name', 'sofa' in tb, tb)

# B: the same sofa inside the room is silent
sofa['z'] = (wb[1] + wb[3]) / 2 - 4.0
check('(b-B) the same sofa 4 m inside the lobby is silent', clashes(db) == [], texts(clashes(db)))


# ── (b2) FURN_WALL_PEN: a fixture ON a party wall is not a defect ────────────
# The surveyed plan packs lay a bathtub against a 0.10 m party wall and the rim
# lands on the wall line. That is placement noise, not something a person sees;
# a sofa a whole leaf into the wall still is.
db2 = tower()
party = db2.new('partition', {'len': 5.0, 'h': 2.4, 't': 0.10}, 60.0, -40.0, 0, 0, 'mat_plaster', 'party wall', 'r')
pb = E.bbox_of(party)  # runs along X: thin along Z
tub = db2.new('bathtub', {'w': 0.75, 'l': 1.7, 'h': 0.55}, 60.0, -30.0, 0, 0, 'mat_tile', 'plan bathtub', 'r')
tb2 = E.bbox_of(tub)
HALF_Z = (tb2[3] - tb2[1]) / 2  # the tub's own half depth
tub['z'] = pb[1] + HALF_Z  # rim 0.10 m past the far face
ob = E.bbox_of(tub)
oz_tub = min(ob[3], pb[3]) - max(ob[1], pb[1])
check(
    '(b2) the tub reaches exactly the 0.10 m wall thickness into the party wall',
    abs(oz_tub - 0.10) < 0.01,
    round(oz_tub, 3),
)
check(
    '(b2) a tub 0.10 m into a 0.10 m party wall is silent (< FURN_WALL_PEN)',
    clashes(db2, 'clash_furniture_wall') == [],
    texts(clashes(db2)),
)
check('(b2) FURN_WALL_PEN is the documented 0.12 m', M.FURN_WALL_PEN == 0.12, M.FURN_WALL_PEN)

# B: a sofa 0.3 m into a 0.3 m wall still fires
thick = db2.new(
    'partition', {'len': 5.0, 'h': 2.4, 't': 0.30}, 60.0, -35.0, 0, 0, 'mat_plaster', 'thick party wall', 'r'
)
kb = E.bbox_of(thick)
sofa2 = db2.new(
    'sofa', {'w': 2.2, 'd': 0.9, 'h': 0.85}, 60.0, (kb[1] + kb[3]) / 2, 0, 0, 'mat_timber', 'sofa in the wall', 'r'
)
f_b2 = clashes(db2, 'clash_furniture_wall')
check(
    '(b2-B) a sofa a whole 0.30 m leaf into a wall still fires',
    len(f_b2) == 1 and sofa2['id'] in texts(f_b2) and thick['id'] in texts(f_b2),
    texts(clashes(db2)),
)
db2.objs.remove(sofa2)
db2.objs.remove(thick)
tub['z'] = pb[1] - HALF_Z - 0.5  # clear of the wall altogether
check('(b2-C) the tub clear of the wall is silent', clashes(db2) == [], texts(clashes(db2)))


# ── (c) a sun lounger written into the pool water ────────────────────────────
dc = tower()
said_pool = A.call_tool(dc, 'add_infinity_pool', dict(cell_from='FC104', cell_to='FN108', view='south', storey=20))
check('add_infinity_pool built the rooftop pool', not said_pool.startswith('refused'), said_pool[:140])
pool = [o for o in dc.objs if o['kind'] == 'pool'][-1]
water = M.plan_rect(pool, 'water')
wv = M.vspan(pool, 'water')
deck = A.EXT_MODULES['envelope_rules'].group_envelope(dc, 'tower')['top_deck']
check(
    'the water box stands on the deck, not inside the building',
    wv[1] > deck - 0.01,
    (round(wv[0], 2), round(wv[1], 2), deck),
)

base_water = clashes(dc, 'clash_furniture_water')
check('(c-B) the loungers add_infinity_pool puts on the deck are silent', base_water == [], texts(base_water))

lounger = dc.new(
    'sun_lounger',
    {'l': 1.9, 'w': 0.7, 'h': 0.4},
    (water[0] + water[2]) / 2,
    (water[1] + water[3]) / 2,
    deck,
    0,
    'mat_timber',
    'lounger in the water',
    'r',
)
fc = clashes(dc, 'clash_furniture_water')
check(
    '(c) a sun_lounger written into the water rect is a clash_furniture_water',
    len(fc) == 1,
    [f['code'] for f in clashes(dc)],
)
tc = texts(fc)
check('(c) the finding names the lounger and the pool', lounger['id'] in tc and pool['id'] in tc, tc)

# and on the deck beside the water it is silent again
lounger['z'] = water[1] - 2.5
check(
    '(c-B2) moved 2.5 m north of the basin, the lounger is silent',
    clashes(dc, 'clash_furniture_water') == [],
    texts(clashes(dc)),
)


# ── (d) the live tower: the collapse, and every clash it raises ──────────────
dfix = A.Drawing(json.load(open(FIX)))
core_fs = [f for f in C.check_core_clash(dfix) if f['code'] == 'circ_core_clash']
check('(d) the live tower gives exactly 2 circ_core_clash, not 8', len(core_fs) == 2, texts(core_fs))
tf = texts(core_fs)
check('(d) each line names a storey RANGE, not one storey', tf.count('storeys 0..19') == 2, tf)
check('(d) each line says how many stair records it folded', tf.count('(20 stair records)') == 2, tf)
check(
    '(d) the two lines name the two different lift shafts',
    ('o334' in core_fs[0]['text']) != ('o334' in core_fs[1]['text'])
    and ('o416' in core_fs[0]['text']) != ('o416' in core_fs[1]['text']),
    [f['text'][:60] for f in core_fs],
)
check(
    '(d) they are still errors with the old code',
    all(f['code'] == 'circ_core_clash' and f['sev'] == 'error' for f in core_fs),
    core_fs,
)

fix_fs = M.check_clashes(dfix)
counts = collections.Counter(f['code'] for f in fix_fs)
# the check NAME carries the counts so the creator can read them without the detail
check('(d) live tower clash codes: %s' % (dict(counts) or '{}'), True)
for f in fix_fs:
    check('(d) · %s' % f['text'][:150], True)
check(
    '(d) every clash on the live tower is one finding per record',
    len({f['text'].split()[0] for f in fix_fs}) == len(fix_fs),
    [f['text'][:30] for f in fix_fs],
)
check(
    '(d) no role pair exceeds the 8-finding cap',
    all(n <= 8 for c, n in counts.items() if c != 'clash_more'),
    dict(counts),
)


# ── (e) add_room may not be drawn over a core ────────────────────────────────
de = tower()
A.call_tool(de, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=1, kind='u'))
said_over = A.call_tool(de, 'add_room', dict(cell_from='FF91', cell_to='FK95', name='Bad room'))
check('(e) add_room across the FH93 stair is refused', said_over.startswith('refused'), said_over[:200])
check(
    '(e) the refusal names the stair record and the overlap',
    ' m on storey 0' in said_over and ' stair ' in said_over,
    said_over[:200],
)
check('(e) the refusal offers the way out', 'layout_floor' in said_over, said_over[:220])
said_ok = A.call_tool(de, 'add_room', dict(cell_from='FD104', cell_to='FM108', name='Lobby'))
check('(e-B) add_room at FD104..FM108 is not refused', not said_ok.startswith('refused'), said_ok[:200])
check('(e-B) and it really built the room', 'Lobby' in said_ok and 'partition' in said_ok, said_ok[:200])
check('(e-B) the built room does not clash with the stair', clashes(de, 'clash_core_wall') == [], texts(clashes(de)))


# ── (f) layout_floor with no core_from keeps the real cores out ──────────────
df = tower()
A.call_tool(df, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=2, kind='u'))
A.call_tool(df, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=19))
cores1 = M.cores_on_storey(df, 1)
check(
    '(f) storey 1 carries both a stair and a lift shaft',
    {o['kind'] for o, _r in cores1} == {'stair_u', 'elevator_shaft'},
    [(o['id'], o['kind']) for o, _r in cores1],
)

before = len(df.objs)
said_lay = A.call_tool(df, 'layout_floor', dict(cell_from='EX90', cell_to='FQ109', use='residential', storey=1))
check('(f) layout_floor is not refused', not said_lay.startswith('refused'), said_lay[:200])
check('(f) the reply says the core was kept out automatically', 'kept out automatically' in said_lay, said_lay[-260:])
check(
    '(f) the reply names the stair and the lift it kept out',
    all(o['id'] in said_lay for o, _r in cores1),
    said_lay[-260:],
)
check(
    '(f) the reply says no core_from/core_to was given', 'no core_from/core_to was given' in said_lay, said_lay[-260:]
)

new = df.objs[before:]
bad = []
for o in new:
    if o['kind'] not in ('partition', 'wall', 'zone'):
        continue
    r = E.bbox_of(o)
    for co, cr in cores1:
        ox = min(r[2], cr[2]) - max(r[0], cr[0])
        oz = min(r[3], cr[3]) - max(r[1], cr[1])
        if ox > 0.15 and oz > 0.15:
            bad.append((o['id'], o.get('name'), co['id'], round(ox, 2), round(oz, 2)))
check('(f) not one partition or zone it drew overlaps a core rect', bad == [], bad)
check('(f) it still laid a real floor out', 'laid out' in said_lay and ' apartment' in said_lay, said_lay[:160])

# and when the operator DOES name a core block, it is still honoured
dg = tower()
A.call_tool(dg, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=2, kind='u'))
A.call_tool(dg, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=19))
said_core = A.call_tool(
    dg,
    'layout_floor',
    dict(cell_from='EX90', cell_to='FQ109', use='residential', storey=1, core_from='FF95', core_to='FJ97'),
)
check('(f-B) a given core block is still accepted, never refused', not said_core.startswith('refused'), said_core[:200])
check(
    '(f-B) and a core block too small to cover the lift is named, not fatal',
    'kept out automatically' not in said_core,
    said_core[-240:],
)


# ── (g) the replay the whole studio is measured against ──────────────────────
# The replay is NOT all green, and the reason is the point of this task: the new
# gate finds ten REAL defects in the records job 71ac02b0's own tools produce.
# Every one is measured below, so the creator can read the geometry rather than
# take the verdict on trust. The three tool regressions the first cut of this
# work caused (layout_floor refusing the replay's own core block) ARE fixed —
# `layout_floor` keeps the core out and says so instead of refusing.
import subprocess  # noqa: E402

rep = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_tower_replay.py')
r = subprocess.run([sys.executable, rep], capture_output=True, text=True, timeout=600)
out = r.stdout or ''
tail = out.strip().splitlines()[-1] if out.strip() else (r.stderr or '')[-200:]
check('(g) test_tower_replay still runs to the end', 'ALL GREEN' in tail or 'FAILED' in tail, tail)
reds = [] if 'ALL GREEN' in tail else [s.strip() for s in tail.split(':', 1)[1].split(',')]
check(
    '(g) the replay loses no check to a tool REFUSAL or a missing record',
    all(s == 'the drawing reaches 0 errors' for s in reds),
    reds,
)
check('(g) its one red is the new gate: %s' % (tail if reds else 'none'), True)

# every clash the gate raises on the replay, with the geometry behind it
g = {'__name__': '__main__', '__file__': rep}
import contextlib  # noqa: E402
import io  # noqa: E402
from zyg_workflows import arch_ext_harness as _H  # noqa: E402

# the replay shares this module's `check`, so its verdicts would land in OUR
# tally — take the ledger away while it runs and put it back after.
_keep, _n = list(_H.FAILS), _H._N[0]
with contextlib.redirect_stdout(io.StringIO()):
    try:
        exec(compile(open(rep).read(), rep, 'exec'), g)  # nosec B102  # noqa: S102  runs this repo's own sibling test_tower_replay.py in-process so its `d` can be read back out of `g`; `rep` is a literal path, no input reaches it
    except SystemExit:
        pass
_H.FAILS[:] = _keep
_H._N[0] = _n
drep = g['d']
rep_fs = M.check_clashes(drep)
check('(g) the replay raises %s' % dict(collections.Counter(f['code'] for f in rep_fs)), True)
for f in rep_fs:
    a, b = f['text'].split()[0], f['text'].split(' passes through ')[1].split()[0]
    ra, rb = drep.find(a), drep.find(b)
    geo = '%s %s %s   vs   %s %s %s' % (
        a,
        [round(v, 2) for v in E.bbox_of(ra)],
        [round(v, 2) for v in M.vspan(ra, M.role_of(ra, M.furniture_kinds()))],
        b,
        [round(v, 2) for v in E.bbox_of(rb)],
        [round(v, 2) for v in M.vspan(rb, M.role_of(rb, M.furniture_kinds()))],
    )
    check('(g) REAL DEFECT %s' % geo, ra is not None and rb is not None, geo)

finish()
