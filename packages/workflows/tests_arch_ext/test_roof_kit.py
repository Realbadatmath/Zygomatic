# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_roof_kit — one call has to leave a roof that every deck check passes.

The 09-12 live run spent five drawing calls on the roof and still shipped a
plain basin beside the air-handling plant. build_roof_deck is only worth a tool
slot if ONE call lands a deck that deck_rules.check_roof_deck,
water_leisure.check_infinity_pools, finish_rules.check_deck_guarding and
circulation_rules.check_head_house are all silent about — so that is what is
measured here, on the same 20-storey reference tower the deck checks use, with
core_kit's own core on it.

No new kinds (KINDS == {}), so no browser / Blender pass: every record comes
from add_parapet / add_infinity_pool / add_rooftop_plant / add_opening, which
their own families already prove.
"""

import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['roof_kit']
DK = A.EXT_MODULES['deck_rules']
W = A.EXT_MODULES['water_leisure']
FR = A.EXT_MODULES['finish_rules']
CR = A.EXT_MODULES['circulation_rules']
E = A.EXT_MODULES['envelope_rules']

PLANT_KINDS = ('hvac_unit', 'water_tank', 'antenna', 'chiller', 'cooling_tower', 'plant_unit')


def tower():
    """20 x 20 m, 20 storeys, with core_kit's core on the NORTH side: two lift
    shafts, a U-stair and a head house on the deck — the exact obstacle the
    pool has to be laid out around."""
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
    A.call_tool(d, 'add_core', dict(group='tower', position='north'))
    return d


def errors(findings):
    return [f['code'] for f in findings if f.get('sev') == 'error']


def dump(d):
    return json.dumps(d.objs, sort_keys=True, default=str)


def loungers(d):
    return [o for o in d.objs if 'lounger' in str(o.get('name') or '')]


def pools(d):
    return [o for o in d.objs if o['kind'] == 'pool']


def plant(d):
    return [o for o in d.objs if o['kind'] in PLANT_KINDS and o['y'] > 50]


# ── (a) one call, south view: every deck check silent ────────────────────────
d = tower()
say = A.call_tool(d, 'build_roof_deck', dict(group='tower', view='south'))
check('build_roof_deck(view="south") is not refused', not say.startswith('refused'), say[:300])
check('the reply names the pool and its cells', ' pool o' in say and '..' in say, say.split('\n')[0])

rd = DK.check_roof_deck(d)
check(
    'deck_rules.check_roof_deck finds no error',
    errors(rd) == [],
    ' | '.join(f['code'] + ': ' + f['text'] for f in rd if f.get('sev') == 'error'),
)
check('deck_rules.check_roof_deck is silent altogether', rd == [], [f['code'] for f in rd])

inf = W.check_infinity_pools(d)
check(
    'water_leisure.check_infinity_pools finds no error',
    errors(inf) == [],
    ' | '.join(f['code'] + ': ' + f['text'] for f in inf if f.get('sev') == 'error'),
)

fg = FR.check_deck_guarding(d)
check('finish_rules.check_deck_guarding is silent', fg == [], [f['code'] for f in fg])

hh = CR.check_head_house(d)
check('circulation_rules.check_head_house is silent', hh == [], [f['code'] for f in hh])

check(
    'the reply prints the roof check count', re.search(r'roof check: \d+ error', say) is not None, say.split('\n')[-1]
)
check(
    'the printed count agrees with design_rules',
    'roof check: 0 error(s)' in say and M.roof_findings(d)[0] == [],
    M.roof_findings(d),
)

# the nine rules, read off the records rather than off the checks
env = E.group_envelope(d, 'tower')
pool = pools(d)[0]
px0, pz0, px1, pz1 = M._bbox(pool)
check(
    'the pool reaches the south (view) edge', abs(env['zmax'] - pz1) <= M.EDGE_TOL + 0.05, (round(pz1, 2), env['zmax'])
)
check(
    '1.2 m of walkway on the east, west and north sides of the pool',
    min(px0 - env['xmin'], env['xmax'] - px1, pz0 - env['zmin']) >= M.WALK_MIN - 1e-6,
    (round(px0 - env['xmin'], 2), round(env['xmax'] - px1, 2), round(pz0 - env['zmin'], 2)),
)
gaps = [(oid, round(M._gap((px0, pz0, px1, pz1), tuple(bb)), 2)) for _w, oid, bb in M.core_rects(d, env, 'tower')]
check(
    '1.5 m of deck round every core, lift-shaft overruns included',
    all(g >= M.CORE_CLEAR - 1e-6 for _o, g in gaps),
    gaps,
)
check(
    'the pool is at least 4 x 3 m',
    min(px1 - px0, pz1 - pz0) >= M.POOL_MIN_BAND - 1e-6 and max(px1 - px0, pz1 - pz0) >= M.POOL_MIN_SIDE - 1e-6,
    (px1 - px0, pz1 - pz0),
)
check('the long side runs parallel to the view facade', px1 - px0 >= pz1 - pz0, (px1 - px0, pz1 - pz0))
check('the pool is no deeper into the plate than 6 m', pz1 - pz0 <= M.POOL_MAX_DEPTH + 1e-6, pz1 - pz0)

# ── (d) counts: loungers, one pool, plant on the far side ────────────────────
check('at least 4 loungers', len(loungers(d)) >= 4, len(loungers(d)))
check('exactly one pool', len(pools(d)) == 1, [o['id'] for o in pools(d)])
check(
    'the loungers sit north of the weir strip and face south',
    loungers(d) and all(o['z'] < pz1 - 0.5 for o in loungers(d)),
    [(o['id'], round(o['z'], 2)) for o in loungers(d)],
)

pl = plant(d)
check('the rooftop plant is placed', len(pl) >= 1, len(pl))
check(
    'every plant record sits on the north strip, off the centre line',
    pl and all(o['z'] < (env['zmin'] + env['zmax']) / 2 for o in pl),
    [(o['id'], round(o['z'], 2)) for o in pl],
)
check(
    'every plant record is 2 m clear of the water',
    pl and all(pz0 - M._bbox(o)[3] >= M.PLANT_CLEAR - 1e-6 for o in pl),
    [(o['id'], round(pz0 - M._bbox(o)[3], 2)) for o in pl],
)
check(
    'the plant is inside the plate',
    pl and all(E.inside(env, o['x'], o['z'], 0.0) for o in pl),
    [(o['id'], round(o['x'], 2), round(o['z'], 2)) for o in pl],
)

guards = M.guard_sides(d, env, 'tower')
check('a guard on all four deck edges', sorted(guards) == ['e', 'n', 's', 'w'], sorted(guards))

doors = [o for o in d.objs if o['kind'] in M.DOOR_KINDS and o['y'] > 50]
check('the head house has a door on the deck', len(doors) >= 1, [o['id'] for o in doors])

# ── (a2) the 09-16 live defect: plant clearance and floating palms ───────────
# Job aba5ab208439 built this very tower and design_check answered
#   'o1332 hvac unit needs 1 m clear — o1318 parasol 1 stands 0.86 m inside it'
#   'o1333 water tank needs 1 m clear — o1328 underwater light stands 1.00 m inside it'
# and the model had to hand-move a palm 'off the deck', where it floated and was
# deleted. The strip is now set out against the WHOLE pool group (parasols reach
# 4.95 m past the basin; an underwater light's p.r = 5 makes its bbox a 10 m
# square) and palms are pulled inside the edge instead of being dropped.
DR = A.EXT_MODULES['design_rules']
all_f = DR.run_checks(d)
palm_ids = {o['id'] for o in d.objs if o['kind'] == 'tree_palm'}
plant_ids = {o['id'] for o in pl}


def names(f, ids):
    return any(re.search(r'\b' + i + r'\b', f['text']) for i in ids)


clr = [
    f
    for f in all_f
    if f.get('code') == 'clearance' and (names(f, plant_ids) or re.search(r'hvac|water tank|antenna', f['text'], re.I))
]
check(
    'design_rules.run_checks raises no clearance warning naming hvac, tank or antenna',
    clr == [],
    [f['sev'] + ' ' + f['text'] for f in clr],
)
unsup = [f for f in all_f if f.get('code') == 'unsupported' and (names(f, palm_ids) or 'palm' in f['text'].lower())]
check(
    'design_rules.run_checks raises no unsupported finding naming a palm',
    unsup == [],
    [f['sev'] + ' ' + f['text'] for f in unsup],
)
check(
    'the only findings left on the finished deck are info',
    [f for f in all_f if f.get('sev') != 'info'] == [],
    [f['sev'] + ' ' + f['code'] + ': ' + f['text'] for f in all_f if f.get('sev') != 'info'],
)

palms = [o for o in d.objs if o['kind'] == 'tree_palm' and o['y'] > 50]
check('the pool group brought palms onto the deck', len(palms) >= 1, len(palms))
insets = [
    (o['id'], round(min(o['x'] - env['xmin'], env['xmax'] - o['x'], o['z'] - env['zmin'], env['zmax'] - o['z']), 2))
    for o in palms
]
check(
    f'every palm stands at least {W.PALM_IN} m inside every deck edge',
    all(g >= W.PALM_IN - 1e-6 for _i, g in insets),
    insets,
)
check(
    'every palm stands on the deck, not in mid-air',
    all(abs(o['y'] - A.surface_top(d, o['x'], o['z'])) <= 0.01 for o in palms),
    [(o['id'], round(o['y'], 2), round(A.surface_top(d, o['x'], o['z']), 2)) for o in palms],
)
check(
    'no palm stands in the water',
    all(not (px0 - 0.3 < o['x'] < px1 + 0.3 and pz0 - 0.3 < o['z'] < pz1 + 0.3) for o in palms),
    [(o['id'], round(o['x'], 2), round(o['z'], 2)) for o in palms],
)

# every plant unit is PLANT_POOL clear of the whole pool group, not just the water
gbb = M.pool_group_bbox(d, env, max(o['y'] for o in pl))
check(
    'the pool group bbox reaches further than the basin', gbb is not None and gbb[1] < pz0 - 1e-6, (gbb, round(pz0, 2))
)
pool_gaps = [(o['id'], round(M._gap(M._bbox(o), gbb), 2)) for o in pl]
check(
    f'every plant unit is {M.PLANT_POOL} m clear of the whole pool group',
    all(g >= M.PLANT_POOL - 1e-6 for _i, g in pool_gaps),
    pool_gaps,
)
core_gaps = [
    (o['id'], w, round(M._gap(M._bbox(o), tuple(bb)), 2)) for o in pl for w, _oid, bb in M.core_rects(d, env, 'tower')
]
check(
    f'every plant unit is {M.PLANT_CORE} m clear of every core and head house',
    all(g >= M.PLANT_CORE - 1e-6 for _i, _w, g in core_gaps),
    core_gaps,
)

# a plate too short for the plant strip: head-house roof, or a refusal that says why
ds = A.Drawing(None)
A.call_tool(ds, 'draw_box', dict(centre='FH100', width=12, depth=12, storeys=20, roof='flat', name='tower'))
A.call_tool(ds, 'add_core', dict(group='tower', position='north'))
before_s = dump(ds)
ss = A.call_tool(ds, 'build_roof_deck', dict(group='tower', view='south'))
if ss.startswith('refused'):
    check(
        'a 12 x 12 plate refuses, naming the strip that is too short and what to do',
        re.search(r'strip of "tower" is [\d.]+ m deep', ss) is not None
        and re.search(r'hvac|water tank|antenna', ss, re.I) is not None
        and 'plant=false' in ss,
        ss[:400],
    )
    check('the refused 12 x 12 call leaves the drawing untouched', dump(ds) == before_s, len(ds.objs))
else:
    check('a 12 x 12 plate says it put the plant on the head-house roof', 'head-house roof' in ss, ss[:400])
    check(
        '12 x 12: no clearance warning names hvac, tank or antenna',
        [
            f
            for f in DR.run_checks(ds)
            if f.get('code') == 'clearance' and re.search(r'hvac|water tank|antenna', f['text'], re.I)
        ]
        == [],
        [f['text'] for f in DR.run_checks(ds) if f.get('code') == 'clearance'],
    )

# 19 x 19 is the plate where the strip takes some of the plant but not all of it,
# so it is the one that proves the head-house fallback is reachable at all.
dh = A.Drawing(None)
A.call_tool(dh, 'draw_box', dict(centre='FH100', width=19, depth=19, storeys=20, roof='flat', name='tower'))
A.call_tool(dh, 'add_core', dict(group='tower', position='north'))
sh = A.call_tool(dh, 'build_roof_deck', dict(group='tower', view='south'))
check(
    'a 19 x 19 plate builds and says it stood plant on the head-house roof',
    not sh.startswith('refused') and 'head-house roof' in sh,
    next((ln for ln in sh.splitlines() if ln.startswith('plant:')), sh[:300]),
)
hb = M.head_house_top(dh, E.group_envelope(dh, 'tower'), min(o['y'] for o in plant(dh)))
raised = [o for o in plant(dh) if hb and abs(o['y'] - hb[1]) <= 0.01]
check(
    'the raised units stand on the head-house roof surface, not in mid-air',
    len(raised) >= 1 and all(hb[0][0] <= o['x'] <= hb[0][2] and hb[0][1] <= o['z'] <= hb[0][3] for o in raised),
    [(o['id'], round(o['y'], 2)) for o in plant(dh)],
)
check(
    '19 x 19: no clearance warning names hvac, tank or antenna',
    [
        f
        for f in DR.run_checks(dh)
        if f.get('code') == 'clearance' and re.search(r'hvac|water tank|antenna', f['text'], re.I)
    ]
    == [],
    [f['text'] for f in DR.run_checks(dh) if f.get('code') == 'clearance'],
)

# ── (b) the other three views ────────────────────────────────────────────────
for view, _axis in (('east', 'x'), ('west', 'x')):
    dv = tower()
    sv = A.call_tool(dv, 'build_roof_deck', dict(group='tower', view=view))
    check(f'build_roof_deck(view="{view}") is not refused', not sv.startswith('refused'), sv[:300])
    check(
        f'{view}: check_roof_deck finds no error',
        errors(DK.check_roof_deck(dv)) == [],
        ' | '.join(f['code'] + ': ' + f['text'] for f in DK.check_roof_deck(dv) if f.get('sev') == 'error'),
    )
    check(
        f'{view}: check_infinity_pools finds no error',
        errors(W.check_infinity_pools(dv)) == [],
        errors(W.check_infinity_pools(dv)),
    )
    check(
        f'{view}: check_deck_guarding and check_head_house are silent',
        FR.check_deck_guarding(dv) == [] and CR.check_head_house(dv) == [],
        (FR.check_deck_guarding(dv), CR.check_head_house(dv)),
    )
    check(
        f'{view}: at least 4 loungers and exactly one pool',
        len(loungers(dv)) >= 4 and len(pools(dv)) == 1,
        (len(loungers(dv)), len(pools(dv))),
    )
    pv = pools(dv)[0]
    bx0, bz0, bx1, bz1 = M._bbox(pv)
    check(f'{view}: the long side runs parallel to the {view} facade', bz1 - bz0 >= bx1 - bx0, (bx1 - bx0, bz1 - bz0))
    ev = E.group_envelope(dv, 'tower')
    want = ev['xmax'] if view == 'east' else ev['xmin']
    near = bx1 if view == 'east' else bx0
    check(f'{view}: the weir reaches the {view} edge', abs(want - near) <= M.EDGE_TOL + 0.05, (round(near, 2), want))

# the north side is where the core stands: DOCUMENTED CHOICE — refuse, naming it
dn = tower()
before_n = dump(dn)
sn = A.call_tool(dn, 'build_roof_deck', dict(group='tower', view='north'))
check('build_roof_deck(view="north") refuses — the core is on the north', sn.startswith('refused'), sn[:300])
check(
    'the refusal names the north side and the core record',
    'north' in sn and re.search(r'\bo\d+\b', sn) is not None,
    sn[:300],
)
check('the refusal offers the view that does work', 'view="south"' in sn, sn[:300])
check('a refused north call leaves the drawing untouched', dump(dn) == before_n, len(dn.objs))

# ── (c) undo on an inner refusal ─────────────────────────────────────────────
d3 = tower()
before = dump(d3)
n_before = len(d3.objs)
real = A.TOOL_FN['add_infinity_pool']
A.TOOL_FN['add_infinity_pool'] = lambda dd, aa, **kw: 'refused: no pool today'
try:
    r3 = A.call_tool(d3, 'build_roof_deck', dict(group='tower', view='south'))
finally:
    A.TOOL_FN['add_infinity_pool'] = real
check('an inner refusal is passed on as a refusal', r3.startswith('refused'), r3[:200])
check('the inner refusal text is carried', 'no pool today' in r3 or 'add_infinity_pool' in r3, r3[:200])
check('the guard added before the pool is rolled back too', len(d3.objs) == n_before, (n_before, len(d3.objs)))
check('the drawing is byte-identical to the one before the call', dump(d3) == before)

# the same, one step later: add_rooftop_plant refuses after the pool is in
d4 = tower()
before4 = dump(d4)
n4 = len(d4.objs)
realp = A.TOOL_FN['add_rooftop_plant']
A.TOOL_FN['add_rooftop_plant'] = lambda dd, aa, **kw: 'refused: no plant today'
try:
    r4 = A.call_tool(d4, 'build_roof_deck', dict(group='tower', view='south'))
finally:
    A.TOOL_FN['add_rooftop_plant'] = realp
check(
    'a refusal after the pool is drawn also undoes the pool',
    r4.startswith('refused') and dump(d4) == before4,
    (r4[:160], n4, len(d4.objs)),
)

# call_tool turns a TypeError into 'bad arguments for ...', which does NOT start
# with 'refused' — a macro that only tests for 'refused' reports a roof it never built
d4b = tower()
before4b = dump(d4b)
A.TOOL_FN['add_rooftop_plant'] = lambda dd: 'never called'
try:
    r4b = A.call_tool(d4b, 'build_roof_deck', dict(group='tower', view='south'))
finally:
    A.TOOL_FN['add_rooftop_plant'] = realp
check(
    'a "bad arguments" inner result is a failure, not a success',
    r4b.startswith('refused') and dump(d4b) == before4b,
    r4b[:200],
)

# ── options ──────────────────────────────────────────────────────────────────
d5 = tower()
r5 = A.call_tool(d5, 'build_roof_deck', dict(group='tower', view='south', pool='none'))
check(
    'pool="none" lays the deck out with no water',
    not r5.startswith('refused') and pools(d5) == [] and errors(DK.check_roof_deck(d5)) == [],
    (r5.split('\n')[0], len(pools(d5))),
)

d6 = tower()
r6 = A.call_tool(d6, 'build_roof_deck', dict(group='tower', view='south', pool='plain'))
check(
    'pool="plain" keeps a 1.2 m walkway on the view side too',
    not r6.startswith('refused')
    and len(pools(d6)) == 1
    and E.group_envelope(d6, 'tower')['zmax'] - M._bbox(pools(d6)[0])[3] >= M.WALK_MIN - 1e-6,
    (r6.split('\n')[0]),
)
check('pool="plain" still passes the deck checks', errors(DK.check_roof_deck(d6)) == [], errors(DK.check_roof_deck(d6)))

d7 = tower()
r7 = A.call_tool(d7, 'build_roof_deck', dict(group='tower', view='south', pool='rockery'))
check('an unknown pool kind is refused, not guessed', r7.startswith('refused') and 'rockery' in r7, r7[:200])

d8 = tower()
r8 = A.call_tool(d8, 'build_roof_deck', dict(group='nowhere', view='south'))
check('an unknown group is refused', r8.startswith('refused'), r8[:200])

# a second call on a deck that is already built must not double the records
d9 = tower()
A.call_tool(d9, 'build_roof_deck', dict(group='tower', view='south'))
n9 = len(pools(d9))
r9 = A.call_tool(d9, 'build_roof_deck', dict(group='tower', view='south'))
check(
    'a second call does not leave two pools on one deck',
    r9.startswith('refused') or len(pools(d9)) == n9,
    (r9.split('\n')[0][:160], n9, len(pools(d9))),
)

# ── (e) the contract and the prompt budget ───────────────────────────────────
check(
    'roof_kit adds one tool and no kinds',
    [t[0]['name'] for t in M.TOOLS] == ['build_roof_deck'] and M.KINDS == {} and M.DESIGN_CHECKS == [],
    ([t[0]['name'] for t in M.TOOLS], M.KINDS, M.DESIGN_CHECKS),
)
check('the tool is reachable through call_tool', 'build_roof_deck' in A.TOOL_FN)
check(
    'two examples, and both call build_roof_deck',
    len(M.EXAMPLES) == 2 and all(e['calls'][0]['tool'] == 'build_roof_deck' for e in M.EXAMPLES),
    M.EXAMPLES,
)

R = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_all.py')).read()
req = ast.literal_eval(re.search(r'TOWER_REQUEST = (\(.*?\))\n', R, re.S).group(1))
bare, tow = len(A.system_prompt(2.7)), len(A.system_prompt(2.7, req))
print(f'  prompt budget: PROMPT {len(M.PROMPT)} chars, bare {bare}, tower {tow}')
check('roof_kit PROMPT is within its 200-char budget', len(M.PROMPT) <= 200, len(M.PROMPT))
check('the bare system prompt is under 90 000 chars', bare < 90000, bare)
check('the tower system prompt is under 45 000 chars', tow < 45000, tow)

finish()
