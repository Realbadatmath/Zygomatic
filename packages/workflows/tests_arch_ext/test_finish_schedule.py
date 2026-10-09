# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_finish_schedule — the finish schedule arrives by construction.

Proves the table is real (every id exists in the material catalogue and is
light enough to stand on), that ONE apply_finishes call silences
finish_rules.check_luxury_finishes and building_program's 'finishes' item on a
freshly drawn luxury tower, that a library material somebody chose is never
repainted, that a standard job stays a standard job, and that
check_dark_finishes names a black floor and is silent on a white one.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['finish_schedule']
FR = A.EXT_MODULES['finish_rules']
BP = A.EXT_MODULES['building_program']

from zyg_workflows import architecture_materials as AM  # noqa: E402

DEFS = AM.catalogue()['defs']
IDS = set(DEFS)
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')

# The surfaces a person stands on or faces: a dark one turns the model into a
# grey box, so the schedule's ids for them must measure lum >= 60.
LIT_KINDS = ('slab', 'slab_poly', 'balcony', 'roof_flat', 'wall', 'wall_arc', 'curtain_wall', 'parapet', 'partition')


def texts(fn, d):
    return ' | '.join(f['text'] for f in fn(d))


def codes(fn, d):
    return [f['code'] for f in fn(d)]


def presets(d):
    return [o for o in d.objs if not o.get('hidden') and M.is_preset(o.get('mat'))]


def scheduled_presets(d):
    """Flat presets left on a kind THIS drawing's schedule has an opinion about
    — the records 'finishes by construction' promises there will be none of.
    mat_glass on a thing that IS glass is exempt, exactly as it is in
    finish_rules.check_luxury_finishes: a glazed wall is a finish, not a hole
    in the schedule."""
    sched = M.schedule_for(d)
    out = []
    for o in presets(d):
        k = str(o.get('kind') or '')
        if k not in sched and k not in M.GROUP_WALL_KINDS:
            continue
        if str(o.get('mat')) == 'mat_glass' and (k in FR.GLASS_KINDS or 'glass' in str(o.get('name') or '').lower()):
            continue
        out.append(o)
    return out


def arriving_presets(d, kind, n, mat='mat_concrete', p=None, grp='tower'):
    """Write n records that ARRIVE carrying a flat preset.

    Since 2026-09-16 a luxury drawing is born finished — Drawing.new asks
    default_mat for every record — so the tools cannot make this defect any
    more. It still arrives: an older drawing reopened, or a hand edit in the
    tab. The programme is lifted for the write and put back straight after
    (the standard schedule has no opinion about a stair or a partition), which
    is the order those drawings were really made in.
    """
    prog = (d.ext or {}).pop('building_program', None)
    try:
        made = [
            d.new(kind, dict(p or {}), 0.0, 0.0, i * d.storey_h, 0.0, mat, name=f'{kind} st{i}', grp=grp)
            for i in range(n)
        ]
    finally:
        if prog is not None:
            d.ext['building_program'] = prog
    return made


# ── (a) the table is real ───────────────────────────────────────────────────
print('\n-- (a) every id in the schedule exists and is light enough --')
check(
    'the module is check-only in the prompt (PROMPT == "", KINDS == {})',
    M.PROMPT == '' and M.KINDS == {} and M.OPENINGS == [],
    f'{M.PROMPT!r} {M.KINDS!r}',
)

missing = []
for lvl, sched in M.SCHEDULE.items():
    for kind, mid in sched.items():
        if str(mid).startswith('mat_'):
            if mid not in A.MATERIALS:
                missing.append(f'{lvl}/{kind}={mid} (not a preset)')
        elif mid not in IDS:
            missing.append(f'{lvl}/{kind}={mid}')
check('every material id in SCHEDULE exists (library id or flat preset)', not missing, missing)

dark = [
    (k, m, DEFS[m].get('lum'))
    for k, m in M.SCHEDULE['luxury'].items()
    if k in LIT_KINDS and m in DEFS and (DEFS[m].get('lum') or 0) < 60
]
check('every luxury floor/wall/partition id measures lum >= 60', not dark, dark)
# The light plasters the partition id was picked from (acg_Plaster*, lum > 150).
# 2026-09-16: 'white' is in the net as well as 'light'. A partition is the surface a
# visitor stands AMONG, and the lobby render showed Plaster005 (lum 165, tone light)
# reading as grey concrete, so the schedule moved to Plaster001 (lum 212, tone white)
# — brighter than every 'light' plaster in the catalogue. The lift shaft keeps 005.
plasters = sorted(
    (
        k
        for k, v in DEFS.items()
        if k.startswith('acg_Plaster') and (v.get('lum') or 0) > 150 and v.get('tone') in ('light', 'white')
    ),
    key=lambda k: -(DEFS[k].get('lum') or 0),
)
check(
    'the partition id is one of the light acg_Plaster* candidates',
    M.SCHEDULE['luxury']['partition'] in plasters,
    f'{M.SCHEDULE["luxury"]["partition"]} not in {plasters}',
)
check(
    'Marble006 is never in the schedule (it is BLACK, lum 25/255)',
    all('acg_Marble006' not in s.values() for s in M.SCHEDULE.values()),
    DEFS['acg_Marble006'].get('lum'),
)
check(
    'the luxury floor is A.FINISHES["luxury"]["floor"] and the roof deck its roof',
    M.SCHEDULE['luxury']['slab'] == A.FINISHES['luxury']['floor']
    and M.SCHEDULE['luxury']['roof_flat'] == A.FINISHES['luxury']['roof'],
    (M.SCHEDULE['luxury']['slab'], M.SCHEDULE['luxury']['roof_flat']),
)
check(
    'the stair id is a light stone (lum > 90)',
    (DEFS[M.SCHEDULE['luxury']['stair_u']].get('lum') or 0) > 90,
    (M.SCHEDULE['luxury']['stair_u'], DEFS[M.SCHEDULE['luxury']['stair_u']].get('lum')),
)
check(
    'doors are oak, the pool is deep blue tile, lifts and railings are brushed metal',
    M.SCHEDULE['luxury']['double_door'] == 'pht_oak_veneer_01'
    and M.SCHEDULE['luxury']['pool'] == 'acg_Tiles135A'
    and M.SCHEDULE['luxury']['elevator_car'] == 'acg_Metal032'
    and M.SCHEDULE['luxury']['railing'] == 'acg_Metal032',
    {k: M.SCHEDULE['luxury'][k] for k in ('double_door', 'pool', 'elevator_car', 'railing')},
)
check(
    'the standard schedule keeps A.FINISHES["standard"] and maps only door + pool',
    M.SCHEDULE['standard']['slab'] == A.FINISHES['standard']['floor']
    and M.SCHEDULE['standard']['roof_flat'] == A.FINISHES['standard']['roof']
    and set(M.SCHEDULE['standard'])
    == {'slab', 'slab_poly', 'roof_flat', 'door', 'double_door', 'door_sliding', 'door_french', 'pool'},
    sorted(M.SCHEDULE['standard']),
)
check(
    'the tool is apply_finishes and its description names the one call',
    len(M.TOOLS) == 1
    and M.TOOLS[0][0]['name'] == 'apply_finishes'
    and 'ONE call' in M.TOOLS[0][0]['description']
    and 'Never repaints a library material you chose.' in M.TOOLS[0][0]['description'],
    M.TOOLS[0][0]['name'] if M.TOOLS else 'no tool',
)


# ── (b) one call finishes a freshly drawn luxury tower ──────────────────────
print('\n-- (b) a luxury tower is finished in one call --')
d = A.Drawing(None)
d.request = 'a luxurious 20-storey residential tower with a rooftop infinity pool'
STEPS = [
    ('plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, name='tower')),
    ('draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower')),
    ('add_stair', dict(cell='FH93', from_storey=0, to_storey=20, kind='u', width=1.2)),
    ('add_elevator', dict(cell='FD93', from_storey=0, to_storey=20, w=1.8, depth=2.0, door_side='south')),
    ('add_room', dict(cell_from='FD104', cell_to='FM108', storey=0, name='Lobby')),
    ('furnish_lobby', dict(cell_from='FD102', cell_to='FM109', storey=0, entrance_side='south')),
    ('add_infinity_pool', dict(cell_from='FD100', cell_to='FM109', view='south', storey=20)),
    ('add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0)),
    ('add_curtain_wall', dict(walls='tower', storeys=[2, 4, 6, 8])),
]
refused = []
for tool, args in STEPS:
    r = A.call_tool(d, tool, args)
    if str(r).startswith('refused:'):
        refused.append(f'{tool}: {r[:120]}')
check('the tower drew without a refusal', not refused, refused)
check(
    'the programme is a luxury one',
    FR.finish_level(d) == 'luxury' and M.finish_level(d) == 'luxury',
    FR.finish_level(d),
)

# 2026-09-16: the schedule is a CONSTRUCTOR, not a repaint pass. Drawing.new
# asks default_mat for every record, so the tower above never held a flat
# preset on a kind the schedule covers — there is nothing left for
# apply_finishes to do, and check_luxury_finishes was silent from the start.
open_presets = scheduled_presets(d)
check(
    'the freshly drawn luxury tower carries NO flat preset on a scheduled kind',
    open_presets == [],
    sorted({(o['kind'], o['mat']) for o in open_presets})[:8],
)
check(
    'check_luxury_finishes is silent before any repaint call at all',
    FR.check_luxury_finishes(d) == [],
    texts(FR.check_luxury_finishes, d)[:300],
)

reply = A.call_tool(d, 'apply_finishes', {})
check(
    'apply_finishes on a born-finished tower reports nothing to do',
    'nothing to finish' in reply and 'already carry a library material' in reply,
    reply[:300],
)
check(
    'check_luxury_finishes is still SILENT after apply_finishes',
    FR.check_luxury_finishes(d) == [],
    texts(FR.check_luxury_finishes, d)[:400],
)

prog = (d.ext or {}).get('building_program') or {}
rows = {r['key']: r for r in BP.status(d, prog)}
check(
    "building_program's 'finishes' item is ok after apply_finishes",
    bool(rows.get('finishes', {}).get('ok')),
    rows.get('finishes', {}).get('detail', 'no row'),
)

walls = [o for o in d.objs if o['kind'] == 'wall' and o.get('mat') != 'mat_glass']
check(
    'the shell walls carry the library concrete, not mat_concrete',
    walls and all(o['mat'] == M.SCHEDULE['luxury']['wall'] for o in walls),
    sorted({o['mat'] for o in walls}),
)
stairs = [o for o in d.objs if o['kind'] == 'stair_u']
doors = [o for o in d.objs if o['kind'] in ('door', 'double_door')]
check(
    'the stairs are stone and every door leaf is oak',
    all(o['mat'] == M.SCHEDULE['luxury']['stair_u'] for o in stairs)
    and all(o['mat'] == 'pht_oak_veneer_01' for o in doors),
    (sorted({o['mat'] for o in stairs}), sorted({o['mat'] for o in doors})),
)
check(
    'a second apply_finishes has nothing left to do',
    'nothing to finish' in A.call_tool(d, 'apply_finishes', {}),
    A.call_tool(d, 'apply_finishes', {})[:160],
)


# ── (b2) the macro route, and the door leaf that is never a wall ────────────
print('\n-- (b2) the macros build a finished tower, and no door is a wall --')
dm = A.Drawing(None)
dm.request = 'a luxurious 20-storey residential tower with a rooftop infinity pool'
MACROS = [
    ('plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, name='tower')),
    ('draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower')),
    ('add_core', dict(group='tower', position='north')),
    ('build_entrance', dict(group='tower', side='south')),
    ('layout_floor', dict(cell_from='EX90', cell_to='FQ109', use='residential', storey=1)),
    ('build_roof_deck', dict(group='tower')),
]
refused_m = []
for tool, args in MACROS:
    r = A.call_tool(dm, tool, args)
    if str(r).startswith('refused:') or str(r).startswith('bad arguments'):
        refused_m.append(f'{tool}: {str(r)[:120]}')
check('the macro tower drew without a refusal', not refused_m, refused_m)
open_m = scheduled_presets(dm)
check(
    'add_core / build_entrance / layout_floor / build_roof_deck leave ZERO presets',
    open_m == [],
    sorted({(o['kind'], o['mat']) for o in open_m})[:8],
)
check(
    'check_luxury_finishes is silent on the macro tower too',
    FR.check_luxury_finishes(dm) == [],
    texts(FR.check_luxury_finishes, dm)[:300],
)

# A door LEAF never inherits the wall it sits in: the head house borrowed the
# tower's board-formed concrete and shipped a CONCRETE door (o511, 2026-09-16).
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'door_french')
leaves = [o for o in dm.objs if o['kind'] in DOOR_KINDS]
LEAF_OK = (
    'pht_oak_veneer_01',
    'mat_glass',
    getattr(A.EXT_MODULES.get('entrance_kit'), 'SOLID_DOOR_MAT', 'pht_black_oak_veneer'),
)  # tree 3: dark oak entrance leaf in a solid wall
bad_leaves = [(o['id'], o['kind'], o['mat'], o.get('name')) for o in leaves if o['mat'] not in LEAF_OK]
check('the macro tower really has door leaves to judge', len(leaves) >= 4, len(leaves))
check('every door leaf is oak, dark oak or glass — none carries a wall material', not bad_leaves, bad_leaves)
heads = [o for o in leaves if 'head house' in str(o.get('name') or '')]
check(
    'the head house door is oak, not the concrete of its own wall',
    heads and all(o['mat'] == 'pht_oak_veneer_01' for o in heads),
    [(o['id'], o['mat']) for o in heads],
)
SV = A.EXT_MODULES['stairs_vertical']
check(
    'a glass leaf in a glass wall is the one exception',
    SV._door_leaf_mat(dm, 'mat_glass') == 'mat_glass'
    and SV._door_leaf_mat(dm, 'acg_Concrete033') == 'pht_oak_veneer_01',
    (SV._door_leaf_mat(dm, 'mat_glass'), SV._door_leaf_mat(dm, 'acg_Concrete033')),
)


# ── (b3) the repaint pass still works on a drawing that ARRIVES with presets ─
print('\n-- (b3) apply_finishes / autofinish on an older drawing --')
da = A.Drawing(None)
da.request = 'a luxurious 20-storey residential tower'
A.call_tool(da, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
arriving_presets(da, 'stair_u', 20, p={'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2})
arriving_presets(da, 'partition', 6, mat='mat_plaster', p={'len': 4, 'h': 2.7, 't': 0.1})
# the dict shape plan_building writes (building_program.py ~1010-1030), luxury
da.ext['building_program'] = {
    'use': 'residential',
    'storeys': 20,
    'cell_from': 'EX90',
    'cell_to': 'FQ109',
    'area': 400.0,
    'gross': 8000.0,
    'occupants': 267,
    'glass': False,
    'w': 20.0,
    'd': 20.0,
    'items': [],
    'skip': [],
    'finish_level': 'luxury',
    'require': [],
    'from_request': [],
    'unmapped': [],
    'request': da.request,
    'name': 'tower',
}
n_arrived = len(scheduled_presets(da))
check(
    'the arrived drawing is a luxury job full of flat presets',
    M.finish_level(da) == 'luxury' and n_arrived == 126,  # 80 wall + 20 slab + 20 stair_u + 6 partition
    (M.finish_level(da), n_arrived),
)
check(
    'check_luxury_finishes errors on it before the schedule is applied',
    [f['code'] for f in FR.check_luxury_finishes(da)] == ['finish_preset'],
    texts(FR.check_luxury_finishes, da)[:200],
)
n_a, by_kind_a = M.apply(da)
check(
    'apply() painted every arrived preset and counted them per kind',
    n_a == n_arrived
    and set(by_kind_a) == {'wall', 'slab', 'stair_u', 'partition'}
    and by_kind_a['stair_u'] == {'n': 20, 'mat': M.SCHEDULE['luxury']['stair_u']}
    and by_kind_a['partition'] == {'n': 6, 'mat': M.SCHEDULE['luxury']['partition']}
    and by_kind_a['slab'] == {'n': 20, 'mat': M.SCHEDULE['luxury']['slab']},
    (n_a, by_kind_a),
)
check(
    'one pass removed the presets and silenced check_luxury_finishes',
    scheduled_presets(da) == [] and FR.check_luxury_finishes(da) == [],
    texts(FR.check_luxury_finishes, da)[:200],
)

da2 = A.Drawing(None)
da2.request = 'a luxurious tower'
A.call_tool(da2, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=4, roof='flat', name='tower'))
arriving_presets(da2, 'stair_u', 4, p={'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2})
da2.ext['building_program'] = dict(da.ext['building_program'], storeys=4, request=da2.request)
reply_a = A.call_tool(da2, 'apply_finishes', {})
check(
    'the tool reports the counts per kind and what it left alone',
    'records finished' in reply_a
    and ' -> ' in reply_a
    and 'left (user-named library materials are never touched)' in reply_a,
    reply_a[:300],
)


# ── (c) a material somebody chose is never repainted ────────────────────────
print('\n-- (c) library materials and glass are left alone --')
d2 = A.Drawing(None)
d2.request = 'a luxurious tower'
A.call_tool(d2, 'plan_building', dict(use='residential', storeys=4, centre='FH100', width=20, depth=20, name='tower'))
A.call_tool(d2, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=4, roof='flat', name='tower'))
A.call_tool(d2, 'add_curtain_wall', dict(walls='tower', storeys=[0, 2]))
chosen = [o for o in d2.objs if o['kind'] == 'wall' and o.get('mat') != 'mat_glass'][:3]
chosen[0]['mat'] = 'acg_Concrete033'
chosen[1]['mat'] = 'pht_rough_concrete'
chosen[2]['mat'] = 'acg_Bricks075A' if 'acg_Bricks075A' in IDS else sorted(IDS)[0]
keep = {o['id']: o['mat'] for o in chosen}
glass = [o for o in d2.objs if o.get('mat') == 'mat_glass']
check('the drawing has glass curtain walls to protect', len(glass) > 0, len(glass))
A.call_tool(d2, 'apply_finishes', {})
kept = {o['id']: o['mat'] for o in d2.objs if o['id'] in keep}
check('every user-named library material survived apply_finishes', kept == keep, (keep, kept))
check(
    'mat_glass on a glass kind survived apply_finishes',
    all(o['mat'] == 'mat_glass' for o in glass),
    sorted({o['mat'] for o in glass}),
)
check(
    'material_for returns None for a glass curtain wall',
    M.material_for(d2, glass[0]) is None,
    M.material_for(d2, glass[0]),
)
check(
    'material_for returns None for a kind the schedule has no opinion about',
    M.material_for(d2, {'kind': 'road', 'mat': 'mat_asphalt', 'grp': ''}) is None,
    M.material_for(d2, {'kind': 'road', 'mat': 'mat_asphalt', 'grp': ''}),
)


# ── (d) a standard job stays a standard job ─────────────────────────────────
print('\n-- (d) standard level: only the door and the pool are repainted --')
d3 = A.Drawing(None)
d3.request = 'a plain 4-storey office block'
A.call_tool(d3, 'plan_building', dict(use='office', storeys=4, centre='FH100', width=20, depth=20, name='block'))
A.call_tool(d3, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=4, roof='flat', name='block'))
A.call_tool(d3, 'add_opening', dict(group='block', side='south', storey=0, kind='double_door', width=2.8, height=2.4))
d3.new('pool', {'w': 6, 'd': 3, 'h': 1.4}, 0.0, 0.0, 0.0, 0.0, 'mat_plaster', 'Pool', 'block')
check('the programme is a standard one', M.finish_level(d3) == 'standard', M.finish_level(d3))
before3 = {o['id']: o.get('mat') for o in d3.objs}
n3, by_kind3 = M.apply(d3)
moved = {o['kind'] for o in d3.objs if before3.get(o['id']) != o.get('mat')}
check(
    'a standard job repaints nothing but door leaves and the pool',
    moved <= {'door', 'double_door', 'pool'} and moved,
    sorted(moved),
)
# and that is a property of the TABLE, not of this one drawing: every other
# kind the standard schedule names is mapped back to the preset the tool would
# have stamped anyway (A.FINISHES['standard'] / DEFAULT_MAT / TOOL_BLANKS), so
# there is nothing for apply() to change.
noop_std = {
    k: v
    for k, v in M.SCHEDULE['standard'].items()
    if k not in ('door', 'double_door', 'door_sliding', 'door_french', 'pool')
}
check(
    'every other kind in the standard table is the preset the tools already stamp',
    all(
        v == A.DEFAULT_MAT.get(k)
        or v == M.TOOL_BLANKS.get(k)
        or v in (A.FINISHES['standard']['floor'], A.FINISHES['standard']['roof'])
        for k, v in noop_std.items()
    ),
    noop_std,
)
check(
    'standard walls, slabs, stairs and roof are untouched',
    all(before3[o['id']] == o['mat'] for o in d3.objs if o['kind'] in ('wall', 'slab', 'stair_u', 'roof_flat')),
    sorted({o['kind'] for o in d3.objs if before3[o['id']] != o['mat']}),
)
check(
    'the standard pool is the blue tile and the door is oak',
    all(o['mat'] == 'acg_Tiles135A' for o in d3.objs if o['kind'] == 'pool')
    and all(o['mat'] == 'pht_oak_veneer_01' for o in d3.objs if o['kind'] in ('door', 'double_door')),
    [(o['kind'], o['mat']) for o in d3.objs if o['kind'] in ('pool', 'door', 'double_door')],
)
check(
    'apply returns (n_changed, by_kind) with a count and an id per kind',
    n3 == sum(r['n'] for r in by_kind3.values())
    and all(set(r) == {'n', 'mat'} and r['n'] > 0 for r in by_kind3.values()),
    (n3, by_kind3),
)
check(
    'apply_finishes(level="luxury") overrides the level for that call only',
    'records finished' in A.call_tool(d3, 'apply_finishes', dict(level='luxury')) and M.finish_level(d3) == 'standard',
    M.finish_level(d3),
)
check(
    'apply_finishes refuses a level it does not know',
    A.call_tool(d3, 'apply_finishes', dict(level='palatial')).startswith('refused:'),
    A.call_tool(d3, 'apply_finishes', dict(level='palatial'))[:120],
)
check(
    'apply_finishes refuses a group that is not in the drawing',
    A.call_tool(d3, 'apply_finishes', dict(group='nowhere')).startswith('refused:'),
    A.call_tool(d3, 'apply_finishes', dict(group='nowhere'))[:120],
)


# ── the two hooks arch_assistant will call ──────────────────────────────────
print('\n-- the Drawing.new / done() hooks --')
check(
    'default_mat answers the schedule for a preset on a luxury job',
    M.default_mat(d, 'stair_u', 'mat_concrete') == M.SCHEDULE['luxury']['stair_u']
    and M.default_mat(d, 'door', None) == 'pht_oak_veneer_01',
    M.default_mat(d, 'stair_u', 'mat_concrete'),
)
check(
    'default_mat leaves a library id the caller named alone',
    M.default_mat(d, 'slab', 'pht_rough_concrete') == 'pht_rough_concrete',
    M.default_mat(d, 'slab', 'pht_rough_concrete'),
)
check(
    'default_mat leaves mat_glass on a glass kind and unknown kinds alone',
    M.default_mat(d, 'curtain_wall', 'mat_glass') == 'mat_glass'
    and M.default_mat(d, 'road', 'mat_asphalt') == 'mat_asphalt',
    (M.default_mat(d, 'curtain_wall', 'mat_glass'), M.default_mat(d, 'road', 'mat_asphalt')),
)
d4 = A.Drawing(None)
d4.request = 'a luxurious tower'
A.call_tool(d4, 'plan_building', dict(use='residential', storeys=4, centre='FH100', width=20, depth=20, name='tower'))
A.call_tool(d4, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=4, roof='flat', name='tower'))
check('autofinish(d) has nothing to paint on a tower the tools built', M.autofinish(d4) == 0, M.autofinish(d4))
arriving_presets(d4, 'stair_u', 4, p={'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2})
check(
    'autofinish(d) paints the arrived presets and returns the count',
    M.autofinish(d4) == 4 and M.autofinish(d4) == 0,
    [(o['id'], o['mat']) for o in d4.objs if o['kind'] == 'stair_u'],
)


# ── (e) the fixture, and the dark-finish check ──────────────────────────────
print('\n-- (e) the live tower fixture and check_dark_finishes --')
fx = A.Drawing(json.load(open(FIX)))
base = codes(M.check_dark_finishes, fx)
check(
    'the fixture is a luxury job with acg_Marble006 floors',
    FR.finish_level(fx) == 'luxury' and any(o['kind'] == 'slab' and o.get('mat') == 'acg_Marble006' for o in fx.objs),
    FR.finish_level(fx),
)
check(
    'check_dark_finishes names the black marble floor of the fixture',
    base and set(base) == {'finish_dark'} and len(base) <= 8,
    (len(base), base[:3]),
)
first = M.check_dark_finishes(fx)[0]
check(
    'the finding names the record, the luminance and ONE tool call',
    first['sev'] == 'warn'
    and 'acg_Marble006' in first['text']
    and 'lum 25/255' in first['text']
    and 'set_finish(' in first['text']
    and M.SCHEDULE['luxury']['slab'] in first['text'],
    first['text'],
)

n_fx, by_kind_fx = M.apply(fx)
check(
    'apply on the fixture only touches the preset deck furniture',
    set(by_kind_fx) == {'sun_lounger', 'umbrella'} and n_fx == 8,
    (n_fx, by_kind_fx),
)
check(
    'the fixture keeps its own library finishes (walls, doors, string courses)',
    all(o['mat'] == 'pht_rough_concrete' for o in fx.objs if o['kind'] == 'string_course')
    and all(o['mat'] == 'pht_black_oak_veneer' for o in fx.objs if o['kind'] in ('door', 'double_door'))
    and all(o['mat'] == 'mat_glass' for o in fx.objs if o['kind'] == 'curtain_wall'),
    sorted({(o['kind'], o['mat']) for o in fx.objs if o['kind'] in ('string_course', 'door', 'curtain_wall')}),
)

for o in fx.objs:
    if o.get('mat') == 'acg_Marble006':
        o['mat'] = 'acg_Marble021'
check(
    'check_dark_finishes is SILENT once the floors are acg_Marble021',
    M.check_dark_finishes(fx) == [],
    texts(M.check_dark_finishes, fx)[:300],
)
check(
    'check_dark_finishes never raises on an empty or broken drawing',
    M.check_dark_finishes(A.Drawing(None)) == [],
    texts(M.check_dark_finishes, A.Drawing(None)),
)
check(
    'a tower finished by the schedule raises no finish_dark',
    M.check_dark_finishes(d) == [],
    texts(M.check_dark_finishes, d)[:300],
)

finish()
