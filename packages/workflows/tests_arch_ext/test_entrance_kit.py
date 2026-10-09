# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_entrance_kit — one call has to produce an arrival that every other
family already agrees with.

The 09-12 run's entrance failed four different checks at once (orphan door,
facade-line partition, WC in front of the lift doors, lamps under the canopy),
so the proof here is not "records exist" but "design_rules.run_checks has no
entrance error left, and building_program's entrance/lobby/reception/approach
rows all read ok". The full error list is printed as the check detail so a red
line names its own cause.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['entrance_kit']
ER = A.EXT_MODULES['envelope_rules']
DR = A.EXT_MODULES['design_rules']
BP = A.EXT_MODULES['building_program']

# the sibling gate families the brief says to honour "if loaded"
LOADED = set(A.EXT_MODULES)
BAD_PREFIX = ['sight', 'circ_', 'walk_']
for fam, pre in (('clash_rules', 'clash_'), ('entrance_rules', 'ent_'), ('opening_rules', 'open_')):
    if fam in LOADED:
        BAD_PREFIX.append(pre)
BAD_CODE = {'env_facade_partition', 'approach'}


def tower(core='cells', storeys=20, request='luxurious nice entrance'):
    """The brief's defect drawing: a 20 x 20 x 20 tower with a real core on it."""
    d = A.Drawing(None)
    d.request = request
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    A.call_tool(
        d, 'plan_building', dict(use='residential', storeys=storeys, centre='FH100', width=20, depth=20, name='tower')
    )
    if core == 'core' and 'core_kit' in LOADED:
        A.call_tool(d, 'add_core', dict(group='tower', position='north', lifts=2))
    else:
        A.call_tool(d, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=storeys, kind='u', width=1.2))
        A.call_tool(
            d, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=storeys, w=1.8, depth=2.0, door_side='south')
        )
    return d


def errors(d):
    return [f for f in DR.run_checks(d) if f.get('sev') == 'error']


def entrance_errors(d):
    """Every error the entrance is answerable for — program rows are handled
    separately because the tower is missing nineteen other programme items."""
    out = []
    for f in errors(d):
        code = str(f.get('code') or '')
        if code in BAD_CODE or any(code.startswith(p) for p in BAD_PREFIX):
            out.append(f'{code}: {f["text"]}')
    return out


def rows(d, keys=('entrance', 'lobby', 'reception', 'approach')):
    prog = BP.get_program(d)
    return {r['key']: r for r in BP.status(d, prog) if r['key'] in keys}


def lamps(d):
    return [o for o in d.objs if str(o.get('grp') or '') == 'lamp posts']


def canopy_rect(d):
    for o in d.objs:
        if o.get('kind') == 'canopy':
            return ER.bbox_of(o)
    return None


# ── (a) the whole arrival on a defect tower ─────────────────────────────────
da = tower('core')
ra = A.call_tool(da, 'build_entrance', dict(group='tower', side='south'))
check('build_entrance does not refuse on the brief tower', not str(ra).startswith('refused'), ra[:300])
check(
    'the reply names the door, the canopy, the lobby, the drive and the trees',
    all(w in ra for w in ('door', 'canopy', 'lobby', 'drive', 'trees')),
    ra[:300],
)
check(
    "the reply appends the model's own 'entrance check: N errors' line",
    'entrance check:' in ra,
    ra.splitlines()[-1] if ra else '',
)

row_a = rows(da)
for key in ('entrance', 'lobby', 'reception', 'approach'):
    r = row_a.get(key) or {}
    check(f'building_program row "{key}" reads ok', bool(r.get('ok')), str(r.get('detail'))[:220])

check(
    'no entrance-related error is left in design_rules.run_checks',
    entrance_errors(da) == [],
    'checked '
    + '/'.join(BAD_PREFIX + sorted(BAD_CODE))
    + ' | full error list: '
    + ' || '.join(f'{f["code"]}: {f["text"][:110]}' for f in errors(da)),
)
check(
    'the program errors that remain are not the entrance ones',
    all('entrance' not in (row_a[k]['detail'] or '').lower() or row_a[k]['ok'] for k in row_a),
    {k: row_a[k]['ok'] for k in row_a},
)

ext_a = (da.ext.get('entrance') or {}).get('tower') or {}
check(
    "d.ext['entrance'][group] records side, door, canopy and the lobby rect",
    ext_a.get('side') == 'south' and ext_a.get('door') and ext_a.get('canopy') and len(ext_a.get('lobby') or []) == 4,
    ext_a,
)
check(
    'the recorded door and canopy ids are real records',
    da.find(ext_a.get('door')) is not None and da.find(ext_a.get('canopy')) is not None,
    ext_a,
)

# ── (b) idempotence ─────────────────────────────────────────────────────────
before = [o['id'] for o in da.objs if o.get('kind') == 'canopy']
rb = A.call_tool(da, 'build_entrance', dict(group='tower', side='south'))
after = [o['id'] for o in da.objs if o.get('kind') == 'canopy']
check('a second build_entrance does not refuse', not str(rb).startswith('refused'), rb[:200])
check(
    'the second call says it re-used the door',
    're-used the existing' in rb,
    [ln for ln in rb.splitlines() if 'door' in ln],
)
check('the second call adds no second canopy', before == after, (before, after))
check(
    'the second call adds no second lobby',
    len({o['id'] for o in da.objs if o.get('grp') == 'Lobby' and o.get('kind') == 'partition'}) <= 3,
    [o['id'] for o in da.objs if o.get('grp') == 'Lobby'],
)
check(
    'the drawing is still free of entrance errors after the second call', entrance_errors(da) == [], entrance_errors(da)
)

# ── (c) every side of the 20 x 20 plate ─────────────────────────────────────
for side in ('south', 'north', 'east', 'west'):
    ds = tower()
    rs = A.call_tool(ds, 'build_entrance', dict(group='tower', side=side))
    check(f'build_entrance works on the {side} side', not str(rs).startswith('refused'), rs[:260])
    check(
        f'the {side} entrance leaves no entrance error',
        entrance_errors(ds) == [],
        ' || '.join(entrance_errors(ds))
        or 'full error list: ' + ' || '.join(f'{f["code"]}: {f["text"][:90]}' for f in errors(ds)),
    )

# the north side of this plate is the side the core stands on: the lobby has to
# open toward it rather than wall it off
dn = tower()
rn = A.call_tool(dn, 'build_entrance', dict(group='tower', side='north'))
check(
    'with the core on the north the north lobby opens toward it',
    'left OPEN' in rn or 'open plan' in rn,
    [ln for ln in rn.splitlines() if 'lobby' in ln],
)
check(
    'the north lobby clashes with nothing',
    [f for f in errors(dn) if str(f['code']).startswith(('clash_', 'circ_', 'walk_'))] == [],
    [f['text'][:110] for f in errors(dn) if str(f['code']).startswith(('clash_', 'circ_', 'walk_'))],
)

# ── (d) undo on an inner refusal ────────────────────────────────────────────
dd = tower()
n_before = len(dd.objs)
# add_stair gives its head house a door of its own; only a NEW one is our doing
doors_before = {o['id'] for o in dd.objs if o.get('kind') in ('door', 'double_door')}
real = A.TOOL_FN['add_canopy']
A.TOOL_FN['add_canopy'] = lambda d, a, **kw: 'refused: (test) no canopy today'
try:
    rd = A.call_tool(dd, 'build_entrance', dict(group='tower', side='south'))
finally:
    A.TOOL_FN['add_canopy'] = real
check('an inner refusal is returned unchanged', rd == 'refused: (test) no canopy today', rd[:200])
left = [
    (o['id'], o['kind'], o['name'])
    for o in dd.objs
    if o.get('kind') in ('door', 'double_door') and o['id'] not in doors_before
]
check('the undo leaves no entrance door behind', left == [], left)
check('the undo leaves the record count where it started', len(dd.objs) == n_before, (n_before, len(dd.objs)))
check("the undo leaves no d.ext['entrance'] entry", not (dd.ext.get('entrance') or {}), dd.ext.get('entrance'))

# ── (e) the lamps and the trees ─────────────────────────────────────────────
de = tower()
re_ = A.call_tool(de, 'build_entrance', dict(group='tower', side='south', canopy_height=4.2))
env_e = ER.group_envelope(de, 'tower')
can = canopy_rect(de)
lam = lamps(de)
check('four lamp posts were placed', len(lam) == 4, [o['name'] for o in lam])
inside = [o['id'] for o in lam if can and can[0] <= o['x'] <= can[2] and can[1] <= o['z'] <= can[3]]
check('every lamp post stands outside the canopy plan', inside == [], (inside, [round(v, 2) for v in (can or [])]))
tall = [
    (o['id'], round(o['p']['bh'] * float(o.get('s') or 1), 2))
    for o in lam
    if o['p'].get('bh') and o['p']['bh'] * float(o.get('s') or 1) >= 4.2
]
check(
    'every lamp post is shorter than the 4.2 m soffit',
    tall == [],
    tall or [round(o['p']['bh'] * float(o.get('s') or 1), 2) for o in lam],
)

trees = [o for o in de.objs if str(o.get('grp') or '').startswith('tree line')]
axis_x = (env_e['xmin'] + env_e['xmax']) / 2.0
near_trees = [(o['id'], round(abs(o['x'] - axis_x), 2)) for o in trees if abs(o['x'] - axis_x) < 7.0]
check('trees were planted', len(trees) >= 2, len(trees))
check('every tree stands at least 7 m off the entrance axis', near_trees == [], near_trees)

dnt = tower()
A.call_tool(dnt, 'build_entrance', dict(group='tower', side='south', drive=False, trees=False))
check(
    'drive=False, trees=False plants nothing on the site',
    [
        o
        for o in dnt.objs
        if str(o.get('grp') or '') in ('lamp posts', 'Approach Drive')
        or str(o.get('grp') or '').startswith('tree line')
    ]
    == [],
    [o['grp'] for o in dnt.objs if o.get('grp') not in ('tower', 'Lobby', 'Lobby fit-out')],
)

# ── refusals that must stay refusals ────────────────────────────────────────
dr = tower()
check(
    'an unknown group refuses',
    A.call_tool(dr, 'build_entrance', dict(group='nope')).startswith('refused'),
    A.call_tool(dr, 'build_entrance', dict(group='nope'))[:160],
)
check(
    'a bad side refuses',
    A.call_tool(dr, 'build_entrance', dict(group='tower', side='up')).startswith('refused'),
    A.call_tool(dr, 'build_entrance', dict(group='tower', side='up'))[:160],
)

# ── (f) the family contract and the prompt budget ───────────────────────────
# the brief budgets 220, but the tower prompt ceiling forces this family under 120
check(
    'PROMPT is one paragraph inside the 120-char budget',
    0 < len(M.PROMPT) <= 120 and '\n' not in M.PROMPT,
    len(M.PROMPT),
)
check(
    'PROMPT still names the tool and its trigger',
    'build_entrance' in M.PROMPT and 'nice entrance' in M.PROMPT,
    M.PROMPT,
)
# 2026-09-16: the glossary rule asks every family WITH tools for 2+ worked
# examples, so the single one became two. The second is not 'core', so
# system_prompt() — core examples first, cut at 40 — does not pay for it.
check(
    '2+ worked examples, each with an ask and calls',
    len(M.EXAMPLES) >= 2 and all(x.get('ask') and x.get('calls') for x in M.EXAMPLES),
    M.EXAMPLES,
)
check(
    'every example calls build_entrance and none of them is core',
    all(c['tool'] == 'build_entrance' for x in M.EXAMPLES for c in x['calls'])
    and not [x for x in M.EXAMPLES if x.get('core')],
    [(x['calls'][0]['tool'], x.get('core')) for x in M.EXAMPLES],
)
check(
    'the family owns no kinds, no openings and no checks',
    M.KINDS == {} and M.OPENINGS == [] and M.DESIGN_CHECKS == [],
    (M.KINDS, M.OPENINGS, M.DESIGN_CHECKS),
)
check(
    'it exports exactly one tool, build_entrance',
    len(M.TOOLS) == 1 and M.TOOLS[0][0]['name'] == 'build_entrance',
    [t[0]['name'] for t in M.TOOLS],
)
check('build_entrance is wired into the assistant', 'build_entrance' in A.TOOL_FN, sorted(A.TOOL_FN)[:3])

bare = len(A.system_prompt(2.7))
check('the bare system prompt is under 90 000 chars', bare < 90000, bare)


# ── (g) the arrival: glass door, soffit downlights, flanking planters ───────
# The 09-16 acceptance renders showed a 2.8 x 2.7 m oak leaf in a glass shopfront
# under a white slab: "nothing marks it as a luxury arrival". These are the A/B
# pairs for the three things that now mark it.
def arrival(d, group='tower'):
    ids = set(((d.ext.get('entrance') or {}).get(group) or {}).get('arrival') or [])
    return [o for o in d.objs if o['id'] in ids]


def spots(d):
    return [o for o in d.objs if o.get('kind') == 'light_spot']


def potted(d):
    """The entrance's OWN planters. site_landscape plants potted_plant_01 round the
    lobby too, so match the name _presence gives, not the asset family."""
    return [o for o in d.objs if o.get('kind') == 'asset' and o.get('name') == 'entrance planter']


def canopy_of(d):
    return next((o for o in d.objs if o.get('kind') == 'canopy'), None)


def glazed_tower(side='south'):
    """The live fixture: a ground-floor wall turned mat_glass by add_curtain_wall.
    add_opening REFUSES a curtain_wall host, so the only reachable "glass ground
    floor" is the wall add_curtain_wall keeps because it holds a door — exactly
    what job aba5ab208439 had (door o102 in wall o2, kind 'wall', mat 'mat_glass').
    The temp door is only the lever that makes the tool keep the wall."""
    d = tower('core')
    w, _e = A.wall_on_side(d, 'tower', side, 0, ('wall', 'partition'))
    tmp = A.call_tool(d, 'add_opening', dict(wall_id=w['id'], kind='door', at='middle', width=0.9, height=2.1)).split()[
        1
    ]
    A.call_tool(d, 'add_curtain_wall', dict(walls=w['id'], storeys=[0]))
    d.remove([d.find(tmp)])
    return d, w


# (g1) BEFORE: the wall is plain concrete -> the leaf is timber, as it always was
dg0 = tower('core')
A.call_tool(dg0, 'build_entrance', dict(group='tower', side='south'))
door0 = dg0.find((dg0.ext['entrance']['tower'] or {}).get('door'))
check(
    'in a SOLID wall the luxury door is dark timber, not glass',
    door0['kind'] == 'double_door' and door0['mat'] == M.SOLID_DOOR_MAT,
    (door0['kind'], door0['mat']),
)

# (g2) AFTER: the same call on a glazed ground floor gives a GLASS door
dg, wg = glazed_tower()
check(
    'the fixture really is a glass-hosting wall, not a curtain wall',
    wg['kind'] == 'wall' and wg['mat'] == 'mat_glass',
    (wg['kind'], wg['mat']),
)
rg = A.call_tool(dg, 'build_entrance', dict(group='tower', side='south'))
check('build_entrance does not refuse on a glazed ground floor', not str(rg).startswith('refused'), rg[:200])
doorg = dg.find((dg.ext['entrance']['tower'] or {}).get('door'))
check(
    'the door in a glazed ground floor is a mat_glass double_door',
    doorg['kind'] == 'double_door' and doorg['mat'] == 'mat_glass',
    (doorg['kind'], doorg['mat']),
)
check('the reply says the wall is glazed', 'the wall is glazed' in rg, [ln for ln in rg.splitlines() if 'door' in ln])
# add_opening clamps a door to its wall: 3.0 m is asked for, 2.7 m is a storey
wall_h = round(float((wg['p'] or {}).get('h') or dg.storey_h), 3)
check(
    'the door is 2.8 m wide and as tall as the wall allows (3.0 m asked, wall clamps)',
    abs(doorg['p']['w'] - 2.8) < 1e-6 and abs(doorg['p']['h'] - min(M.DOOR_H, wall_h)) < 1e-6,
    (doorg['p'], 'wall h', wall_h, 'DOOR_H', M.DOOR_H),
)

# the six downlights, under the soffit and inside the canopy plan
cang = canopy_of(dg)
sp = spots(dg)
soffit = float(cang['y'])
check(
    'six spot downlights were placed under the canopy',
    len(sp) == M.SPOTS == 6,
    [(o['id'], round(o['x'], 2), round(o['z'], 2), o['y']) for o in sp],
)
check(
    'every downlight hangs BELOW the canopy soffit',
    all(o['y'] < soffit - 1e-9 for o in sp),
    (soffit, sorted({o['y'] for o in sp})),
)
check(
    'every downlight sits inside the canopy plan',
    all(DR._covers(cang, o['x'], o['z'], loose=True) for o in sp),
    [(o['id'], round(o['x'], 2), round(o['z'], 2)) for o in sp if not DR._covers(cang, o['x'], o['z'], loose=True)],
)
check(
    'the downlights stand on TWO rows',
    len({round(o['z'], 2) for o in sp}) == M.SPOT_ROWS == 2,
    sorted({round(o['z'], 2) for o in sp}),
)
check(
    'the downlights point down (a spot with a penumbra, not a bare lamp)',
    all(o['p'].get('angle') and o['p'].get('pen') for o in sp),
    [o['p'] for o in sp[:1]],
)

# the two flanking planters, outside the door swing and outside the axis strip
pots = potted(dg)
env_g = ER.group_envelope(dg, 'tower')
axis_xg = (env_g['xmin'] + env_g['xmax']) / 2.0
check(
    'two potted plants flank the door',
    len(pots) == 2,
    [(o['id'], o['p'].get('item'), round(o['x'], 2), round(o['z'], 2)) for o in pots],
)
check(
    'both planters are the polyhaven potted_plant_02 asset',
    all(o['p'].get('pack') == 'polyhaven_arch' and o['p'].get('item') == 'potted_plant_02_2k' for o in pots),
    [(o['p'].get('pack'), o['p'].get('item')) for o in pots],
)
check(
    'both planters stand OUTSIDE the facade, under the canopy',
    all(o['z'] > env_g['zmax'] and DR._covers(cang, o['x'], o['z'], loose=True) for o in pots),
    [(o['id'], round(o['z'], 2), env_g['zmax'], DR._covers(cang, o['x'], o['z'], loose=True)) for o in pots],
)
off = [round(abs(o['x'] - axis_xg), 2) for o in pots]
check(
    f'both planters clear the {2 * M.AXIS_HALF:g} m axis strip in front of the door',
    all(v >= M.AXIS_HALF for v in off),
    (off, M.AXIS_HALF),
)
check(
    'one planter either side of the axis', len({o['x'] > axis_xg for o in pots}) == 2, [round(o['x'], 2) for o in pots]
)

# nothing the arrival adds may wake a gate
check(
    'the glazed-ground-floor entrance leaves no entrance error',
    entrance_errors(dg) == [],
    ' || '.join(entrance_errors(dg))
    or 'full error list: ' + ' || '.join(f'{f["code"]}: {f["text"][:90]}' for f in errors(dg)),
)
check(
    'the arrival adds no envelope error either',
    [f for f in errors(dg) if str(f['code']).startswith('env')] == [],
    [f'{f["code"]}: {f["text"][:110]}' for f in errors(dg) if str(f['code']).startswith('env')],
)
check(
    "d.ext['entrance'][group] lists the arrival records",
    len((dg.ext['entrance']['tower'] or {}).get('arrival') or []) == len(sp) + len(pots),
    (dg.ext['entrance']['tower'] or {}).get('arrival'),
)
check(
    'no arrival record carries a group of its own (that reads as a room outside)',
    [o['id'] for o in arrival(dg) if str(o.get('grp') or '') not in ('', 'tower', 'assets')] == [],
    [(o['id'], o.get('grp')) for o in arrival(dg)],
)

# (g3) a second call re-uses them — six lamps, not twelve
rg2 = A.call_tool(dg, 'build_entrance', dict(group='tower', side='south'))
check('a second call on the glazed tower does not refuse', not str(rg2).startswith('refused'), rg2[:200])
check(
    'the second call adds no second set of downlights or planters',
    len(spots(dg)) == 6 and len(potted(dg)) == 2,
    (len(spots(dg)), len(potted(dg))),
)
check(
    'the second call says it re-used the arrival',
    're-used the downlights' in rg2,
    [ln for ln in rg2.splitlines() if 'arrival' in ln],
)

# (g4) the A/B that matters most: style='standard' is UNCHANGED
dst = tower('core')
rst = A.call_tool(dst, 'build_entrance', dict(group='tower', side='south', style='standard'))
door_st = dst.find((dst.ext['entrance']['tower'] or {}).get('door'))
check('a standard entrance does not refuse', not str(rst).startswith('refused'), rst[:200])
check(
    'a standard entrance keeps the studio default door leaf (no forced material)',
    door_st['mat'] not in (M.SOLID_DOOR_MAT, M.GLASS_MAT),
    door_st['mat'],
)
check('a standard entrance places NO downlights', spots(dst) == [], [(o['id'], round(o['x'], 2)) for o in spots(dst)])
check('a standard entrance places NO planters', potted(dst) == [], [(o['id'], o['p'].get('item')) for o in potted(dst)])
check(
    'the standard reply says so in one line', 'no downlights' in rst, [ln for ln in rst.splitlines() if 'arrival' in ln]
)
check(
    'a standard entrance leaves no entrance error either', entrance_errors(dst) == [], ' || '.join(entrance_errors(dst))
)

# (g5) the threshold mat: placed when it is legal, skipped (never refused) when not
check(
    'the mat is reported as skipped, not refused, while a rug outdoors is an error',
    'threshold mat' in rg and not rg.startswith('refused'),
    [ln for ln in rg.splitlines() if 'arrival' in ln],
)
check(
    'no rug was smuggled outside the facade',
    [o['id'] for o in dg.objs if o.get('kind') == 'rug' and o['z'] > env_g['zmax']] == [],
    [(o['id'], round(o['z'], 2)) for o in dg.objs if o.get('kind') == 'rug'],
)

# (g6) the tool description still tells the model what it gets
desc = M.TOOLS[0][0]['description']
check(
    'the tool description names the downlights, the planters and the mat',
    all(w in desc for w in ('downlight', 'planter', 'threshold mat')),
    desc[:200],
)
check('the tool description stays inside its budget', len(desc) <= 900, len(desc))

finish()
