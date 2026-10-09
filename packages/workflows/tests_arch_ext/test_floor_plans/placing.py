# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
#   the original top-level import block lives here verbatim; its siblings
#   re-import from it, so nothing in it is unused.

import math
import os
import sys
import tempfile

# The section moved one directory deeper; __file__ is re-anchored on the
# original module so every path and name derived from it is unchanged.
__file__ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_floor_plans.py')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('ZYG_PLANS_DIR', os.path.join(HERE, 'fixtures', 'plans'))

A.load_extensions()
FP = A.EXT_MODULES['floor_plans']

check(
    'all four tools are registered',
    {'search_plans', 'plan_info', 'place_plan', 'tile_units'} <= set(tool_names()),
    sorted(set(tool_names()) & {'search_plans', 'plan_info', 'place_plan', 'tile_units'}),
)
check(
    'the family exposes _place and credits_text for the tiler',
    callable(getattr(FP, '_place', None)) and callable(getattr(FP, 'credits_text', None)),
)
check(
    'PROMPT is inside the contract and says what it is',
    len(FP.PROMPT) <= 900 and 'attribution' in FP.PROMPT.lower(),
    len(FP.PROMPT),
)
check('at least three EXAMPLES', len(FP.EXAMPLES) >= 3, len(FP.EXAMPLES))
check(
    'an EXAMPLE shows tile_units followed by repeat_floor',
    any([c['tool'] for c in e['calls']][:2] == ['tile_units', 'repeat_floor'] for e in FP.EXAMPLES),
    [[c['tool'] for c in e['calls']] for e in FP.EXAMPLES],
)
check('the family is registered in PROMPT_FAMILIES', 'floor_plans' in A.PROMPT_FAMILIES)
check(
    'a request about apartments keeps the family in the prompt',
    'floor_plans' in A.prompt_families('lay real apartments into the tower')[0],
)
check(
    'a request that is nothing to do with plans drops it',
    'floor_plans' in A.prompt_families('a steel footbridge over the river')[1],
)

# ── the packs ────────────────────────────────────────────────────────────────
PK = FP.packs(force=True)
check(
    'the fixture packs load from ZYG_PLANS_DIR',
    len(PK) >= 1,
    (
        sorted(PK),
        FP.plans_dir(),
        os.environ.get('ZYG_PLANS_DIR'),
        sorted(os.listdir(FP.plans_dir())) if os.path.isdir(FP.plans_dir()) else 'NO SUCH DIR',
    ),
)
check(
    'every pack names a licence and an attribution line',
    all(p['manifest'].get('licence') and p['manifest'].get('attribution') for p in PK.values()),
    {n: p['manifest'].get('licence') for n, p in PK.items()},
)


def rows(kind, pack=None):
    out = []
    for n, p in sorted(PK.items()):
        if pack and n != pack:
            continue
        out += [r for r in p['rows'] if r.get('kind') == kind]
    return out


def cells(w_m, d_m, c0=4, r0=4):
    """A cell block of ceil(w) x ceil(d) metres — so 'fit' always lands in band."""
    w, dd = int(math.ceil(w_m - 1e-6)), int(math.ceil(d_m - 1e-6))
    return A.cell_name(c0, r0), A.cell_name(c0 + w - 1, r0 + dd - 1)


FLOORS = sorted(rows('floor'), key=lambda r: r['area'])
UNITS = sorted(rows('unit'), key=lambda r: r['area'])
HOUSES = sorted(rows('house'), key=lambda r: r['area'])
check(
    'the fixtures hold a floor, a unit and a house plan',
    bool(FLOORS) and bool(UNITS) and bool(HOUSES),
    f'{len(FLOORS)} floors, {len(UNITS)} units, {len(HOUSES)} houses',
)
if not (FLOORS and UNITS and HOUSES):
    finish()

FLOOR = FLOORS[0]  # the smallest floor: ~20 x 20 m with a core
UNIT = max(UNITS, key=lambda r: r['n_rooms'])
SMALL = min(UNITS, key=lambda r: max(r['w'], r['d']))  # will not scale into a 20 x 20 bay
HOUSE = HOUSES[0]
TW, TD = int(math.ceil(FLOOR['w'])), int(math.ceil(FLOOR['d']))

# ── the tower, and search against its slab ───────────────────────────────────
txt, d = assistant(
    'draw_box', {'centre': 'FH100', 'width': TW, 'depth': TD, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
)
check('the tower is drawn', 'tower' in txt and 'refused' not in txt, txt[:80])
walls_before = kinds_of(d).get('wall', 0)

txt = A.call_tool(d, 'search_plans', {'kind': 'floor', 'width': 'tower'})
check('search_plans takes a GROUP name as the bay', not txt.startswith('refused'), txt[:120])
check('the smallest fixture floor is offered and fits', FLOOR['id'] in txt and 'fits at scale' in txt, txt[:200])
check(
    'a plan that needs more than ±12 % is marked as not fitting', ('does not fit' in txt) or len(FLOORS) == 1, txt[:400]
)
check('the reply points at the tool that draws it', 'place_plan' in txt, txt[-120:])

t = A.call_tool(d, 'search_plans', {'kind': 'unit', 'types': 'bedroom,bathroom', 'limit': 3})
check('search_plans without a bay still ranks rows', not t.startswith('refused') and ':' in t, t[:120])
t = A.call_tool(d, 'search_plans', {'kind': 'bunker'})
check('an unknown kind is refused', t.startswith('refused:') and 'unit' in t, t[:90])

# ── plan_info ────────────────────────────────────────────────────────────────
t = A.call_tool(d, 'plan_info', {'plan_id': FLOOR['id']})
check(
    'plan_info names the rooms, the entrance and the attribution',
    'rooms' in t and 'entrance' in t and 'attribution' in t,
    t[:160],
)
check(
    'plan_info quotes the pack attribution line in full',
    FP.attribution_of(FLOOR.get('pack') or 'swiss_dwellings') in t or 'CC BY' in t,
    t[-160:],
)
t = A.call_tool(d, 'plan_info', {'plan_id': 'nope_1'})
check(
    'an unknown plan id is refused with the search that lists them',
    t.startswith('refused:') and 'search_plans' in t,
    t[:120],
)

# ── placing a floor into the tower ───────────────────────────────────────────
txt = A.call_tool(d, 'place_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 1, 'align': 'centre'})
check('the floor plan is placed', not txt.startswith('refused'), txt[:200])
k = kinds_of(d)
check(
    'partitions, zones and doors all came with it',
    k.get('partition', 0) > 4 and k.get('zone', 0) > 2 and k.get('door', 0) > 2,
    k,
)
check(
    'the box keeps its own facade — no new wall records',
    k.get('wall', 0) == walls_before,
    (k.get('wall'), walls_before),
)

slab = [o for o in d.select('tower') if o['kind'] == 'slab' and A.storey_index(d, o) == 1][0]
YTOP = slab['y'] + slab['p']['t']
x0, z0 = slab['x'] - slab['p']['w'] / 2, slab['z'] - slab['p']['d'] / 2
x1, z1 = slab['x'] + slab['p']['w'] / 2, slab['z'] + slab['p']['d'] / 2
placed = [o for o in d.objs if (o.get('grp') or '').startswith('plan ')]
# Openings cut into the tower's OWN facade are children of that wall and take the
# wall's frame (y = the wall base), exactly as add_opening does; everything the
# plan draws itself stands on the slab.
facade_op = [o for o in placed if o['kind'] == 'window' or o['name'] == 'plan entrance']
own = [o for o in placed if o not in facade_op]
check(
    'every record the plan draws itself sits on the slab top of storey 1',
    own and all(abs(o['y'] - YTOP) < 0.02 for o in own),
    sorted({round(o['y'], 3) for o in own}),
)
wall_y = YTOP - slab['p']['t']
check(
    'facade openings sit in the host wall frame, not on the slab',
    facade_op and all(abs(o['y'] - wall_y) < 0.02 for o in facade_op),
    sorted({round(o['y'], 3) for o in facade_op}),
)


def inside(o):
    if not (x0 - 0.01 <= o['x'] <= x1 + 0.01 and z0 - 0.01 <= o['z'] <= z1 + 0.01):
        return False
    if o['kind'] in ('partition', 'wall'):
        L = o['p'].get('len', 0)
        for u in (0.0, L):
            px, pz = A._wall_world(o, u)
            if not (x0 - 0.05 <= px <= x1 + 0.05 and z0 - 0.05 <= pz <= z1 + 0.05):
                return False
    return True


check(
    'every placed record is inside the tower envelope',
    all(inside(o) for o in placed),
    [o['id'] for o in placed if not inside(o)][:5],
)
zpts = [p for o in placed if o['kind'] == 'zone' for p in o['p']['pts']]
check('zone outlines are LOCAL to their record', zpts and max(abs(v) for p in zpts for v in p) < 60)
check(
    'zones carry the plan room type as their use',
    all(o['p'].get('use') and o['p'].get('name') for o in placed if o['kind'] == 'zone'),
)

rec = (d.ext.get('floor_layouts') or {}).get('1') or {}
check(
    'the placement is registered where repeat_floor looks',
    rec.get('use') == 'plan' and rec.get('plan') == FLOOR['id'] and len(rec.get('ids') or []) == len(placed),
    {kk: rec.get(kk) for kk in ('use', 'plan')},
)
attrs = d.ext.get('attributions') or []
check(
    'the pack attribution is recorded on the drawing',
    len(attrs) == 1 and FLOOR['id'] in attrs[0]['plans'] and 'CC BY' in attrs[0]['text'],
    attrs,
)
check('credits_text prints that line', 'CC BY' in FP.credits_text(d), FP.credits_text(d)[:100])
A.call_tool(d, 'place_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 2})
a2 = d.ext.get('attributions') or []
check(
    'a second plan from the same pack adds no second attribution entry',
    len(a2) == 1 and a2[0]['plans'].count(FLOOR['id']) == 1,
    a2,
)
A.call_tool(d, 'undo', {})
ent = [o for o in placed if o['name'] == 'plan entrance']
check(
    'the entrance door landed on the tower facade, not on an interior partition',
    len(ent) == 1
    and min(abs(ent[0]['x'] - x0), abs(ent[0]['x'] - x1), abs(ent[0]['z'] - z0), abs(ent[0]['z'] - z1)) < 0.35,
    [(o['x'], o['z']) for o in ent],
)

# ── repeat_floor carries a real plan up ──────────────────────────────────────
n_before = len(d.objs)
txt = A.call_tool(d, 'repeat_floor', {'from_storey': 2, 'to_storey': 2, 'source_storey': 1})
check('repeat_floor accepts a placed plan', not txt.startswith('refused:'), txt[:140])
copies = [o for o in d.objs[n_before:]]
check('it copied every record of the plan', len(copies) == len(placed), (len(copies), len(placed)))
check(
    'the copies sit one storey up',
    copies and all(abs(o['y'] - (o0['y'] + d.storey_h)) < 0.02 for o0, o in zip(placed, copies)),
    sorted({round(o['y'], 3) for o in copies})[:4],
)

# ── a unit into a cell block ─────────────────────────────────────────────────
cf, ct = cells(UNIT['w'], UNIT['d'], 4, 4)
txt, d2 = assistant('place_plan', {'plan_id': UNIT['id'], 'cell_from': cf, 'cell_to': ct, 'storey': 0})
check('a unit places onto a plain cell block', not txt.startswith('refused'), txt[:160])
k2 = kinds_of(d2)
check('the unit brought partitions and zones', k2.get('partition', 0) > 2 and k2.get('zone', 0) > 2, k2)
check('no shell walls without shell=true', k2.get('wall', 0) == 0, k2)
bx0, bz0, bx1, bz1 = A.block_bounds(cf, ct)
check(
    'the unit is inside the block',
    all(bx0 - 0.01 <= o['x'] <= bx1 + 0.01 and bz0 - 0.01 <= o['z'] <= bz1 + 0.01 for o in d2.objs),
    len(d2.objs),
)

# ── the ±12 % gate ───────────────────────────────────────────────────────────
_t, d3 = assistant(
    'draw_box', {'centre': 'K100', 'width': 20, 'depth': 20, 'storeys': 1, 'roof': 'flat', 'name': 'bay'}
)
txt = A.call_tool(d3, 'place_plan', {'plan_id': SMALL['id'], 'group': 'bay', 'storey': 0})
check('a plan that would have to grow past +12 % is REFUSED', txt.startswith('refused:') and '12 %' in txt, txt[:180])
check(
    'the refusal names both sizes and the search that finds a plan that fits',
    f'{SMALL["w"]:g} x {SMALL["d"]:g} m' in txt and 'search_plans(width=20' in txt,
    txt[:200],
)
check('nothing was drawn by the refusal', kinds_of(d3).get('partition', 0) == 0, kinds_of(d3))

# ── mirror and rotate ────────────────────────────────────────────────────────
sq = max(UNIT['w'], UNIT['d'])
cf2, ct2 = cells(sq, sq, 40, 40)
qx0, qz0, qx1, qz1 = A.block_bounds(cf2, ct2)
cx = (qx0 + qx1) / 2


def doors_of(mirror):
    _t, dd = assistant(
        'place_plan',
        {
            'plan_id': UNIT['id'],
            'cell_from': cf2,
            'cell_to': ct2,
            'storey': 0,
            'snap': 0,
            'mirror': mirror,
            'fixtures': False,
            'zones': False,
        },
    )
    return sorted(round(o['x'], 3) for o in dd.objs if o['kind'] == 'door'), dd


plain, _d = doors_of(False)
mirrored, _d = doors_of(True)
back = sorted(2 * cx - v for v in mirrored)
check(
    'mirroring reflects every door about the rectangle centre',
    len(plain) == len(mirrored) and all(abs(a - b) < 0.01 for a, b in zip(plain, back)),
    (plain[:4], back[:4], cx),
)

_t, dr0 = assistant(
    'place_plan', {'plan_id': UNIT['id'], 'cell_from': cf2, 'cell_to': ct2, 'storey': 0, 'snap': 0, 'rotate_deg': 0}
)
_t, dr9 = assistant(
    'place_plan', {'plan_id': UNIT['id'], 'cell_from': cf2, 'cell_to': ct2, 'storey': 0, 'snap': 0, 'rotate_deg': 90}
)


def span(dd):
    zs = [o for o in dd.objs if o['kind'] == 'zone']
    xs = [o['x'] + p[0] for o in zs for p in o['p']['pts']]
    ps = [o['z'] + p[1] for o in zs for p in o['p']['pts']]
    return max(xs) - min(xs), max(ps) - min(ps)


w0, d0 = span(dr0)
w9, d9 = span(dr9)
check(
    'rotate_deg=90 swaps the plan bbox',
    abs(w0 - d9) < 0.25 and abs(d0 - w9) < 0.25,
    (round(w0, 2), round(d0, 2), round(w9, 2), round(d9, 2)),
)
t = A.call_tool(
    A.Drawing(None), 'place_plan', {'plan_id': UNIT['id'], 'cell_from': cf2, 'cell_to': ct2, 'rotate_deg': 45}
)
check('a rotation that is not a quarter turn is refused', t.startswith('refused:') and '90' in t, t[:90])

# ── a house on empty cells, with its own shell ───────────────────────────────
hf, ht = cells(HOUSE['w'], HOUSE['d'], 60, 60)
txt, dh = assistant('place_plan', {'plan_id': HOUSE['id'], 'cell_from': hf, 'cell_to': ht, 'storey': 0, 'shell': True})
check('a house places on empty cells with shell=true', not txt.startswith('refused'), txt[:160])
kh = kinds_of(dh)
check("shell=true draws the plan's OUTER walls as wall records", kh.get('wall', 0) > 0, kh)
check('and hangs its windows on them', kh.get('window', 0) > 0, kh)
check(
    'the shell walls are full storey height',
    all(abs(o['p']['h'] - dh.storey_h) < 0.01 for o in dh.objs if o['kind'] == 'wall'),
    [o['p'].get('h') for o in dh.objs if o['kind'] == 'wall'][:3],
)
check(
    "the house attribution is its own pack's line",
    any(e['pack'] == (HOUSE.get('pack') or dh.ext['attributions'][0]['pack']) for e in dh.ext['attributions']),
    dh.ext.get('attributions'),
)

# align='entrance' turns the plan so its front door lands on the side asked for
txt, de = assistant(
    'place_plan',
    {
        'plan_id': HOUSE['id'],
        'cell_from': hf,
        'cell_to': ht,
        'storey': 0,
        'shell': True,
        'align': 'entrance',
        'entrance_side': 'south',
    },
)
ex0, ez0, ex1, ez1 = A.block_bounds(hf, ht)
ed = [o for o in de.objs if o['name'] == 'plan entrance']
check(
    'align="entrance" puts the front door on the side asked for',
    not txt.startswith('refused') and len(ed) == 1 and ed[0]['z'] > (ez0 + ez1) / 2,
    (txt[:90], [(o['x'], o['z']) for o in ed], (ez0 + ez1) / 2),
)
t = A.call_tool(
    A.Drawing(None), 'place_plan', {'plan_id': HOUSE['id'], 'cell_from': hf, 'cell_to': ht, 'align': 'entrance'}
)
check('align="entrance" without a side is refused', t.startswith('refused:') and 'entrance_side' in t, t[:110])

# ── align='core' lands the plan's stair on the stair that is already there ───
plan = FP.load_plan(FLOOR['id'])
stairs = (plan.get('core') or {}).get('stairs') or []
SCX, SCZ = FP._poly_centre(stairs[0]) if stairs else (0.0, 0.0)
BX = min(p[0] for p in plan['boundary'])
BZ = min(p[1] for p in plan['boundary'])


def core_run(align):
    """Place the floor in a bay 4 m larger than the plan (so alignment has room to
    move it) and report where the plan's own stair polygon ended up in the world."""
    _t, dd = assistant(
        'draw_box', {'centre': 'FH100', 'width': TW + 4, 'depth': TD + 4, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
    )
    cs = [o for o in dd.select('tower') if o['kind'] == 'slab' and A.storey_index(dd, o) == 1][0]
    dd.new(
        'stair_u',
        dict(A.KINDS['stair_u']),
        cs['x'] + 3.0,
        cs['z'] - 2.0,
        cs['y'],
        0.0,
        'mat_concrete',
        name='core stair st1',
        grp='tower',
    )
    t = A.call_tool(
        dd,
        'place_plan',
        {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 1, 'align': align, 'snap': 0, 'scale': 1.0},
    )
    ends = []
    for o in dd.objs:
        if (o.get('grp') or '').startswith('plan ') and o['kind'] in ('partition', 'wall'):
            ends += [A._wall_world(o, 0.0), A._wall_world(o, o['p'].get('len', 0))]
    s = ((dd.ext.get('floor_layouts') or {}).get('1') or {}).get('scale', 1.0)
    # the walls start a hair inside the plan boundary, so correct by that corner
    ox = min(p[0] for p in ends) - BX * s
    oz = min(p[1] for p in ends) - BZ * s
    return t, dd, (ox + SCX * s, oz + SCZ * s), FP._core_centre(dd, 'tower', 1)


check('the fixture floor carries a stair polygon for align="core"', bool(stairs), plan['id'])
txt, dc, at_core, tgt = core_run('core')
check('align="core" places the floor plan', not txt.startswith('refused'), txt[:160])
check(
    "the plan's own stair polygon lands on the stair the group already has",
    math.hypot(at_core[0] - tgt[0], at_core[1] - tgt[1]) < 0.35,
    (tuple(round(v, 2) for v in at_core), tgt),
)
check(
    'records that crossed the existing stair were dropped',
    'dropped' in txt and 'crossed the existing core' in txt,
    txt[-160:],
)

_t2, _d2, at_centre, tgt2 = core_run('centre')
check(
    'align="core" is what moved it — centring leaves the stair somewhere else',
    math.hypot(at_centre[0] - tgt2[0], at_centre[1] - tgt2[1]) > 1.0,
    (tuple(round(v, 2) for v in at_centre), tgt2),
)
rec_c = (dc.ext.get('floor_layouts') or {}).get('1') or {}
check(
    'the core placement is registered as a plan at the scale asked for',
    rec_c.get('use') == 'plan' and abs(rec_c.get('scale', 0) - 1.0) < 1e-6,
    rec_c.get('scale'),
)

# 2026-09-14: the placer trimmed plan walls out of the stair WELL only; a real Swiss floor
# placed with align="core" walled the stair's FOOT shut (8 circ_stair_approach errors in
# the plans replay). The approach zone is stairs_vertical's, and place_plan keeps it clear.
_S, _E = A.EXT_MODULES['stairs_vertical'], A.EXT_MODULES['envelope_rules']
_core_st = [o for o in dc.objs if o['kind'] == 'stair_u' and o.get('name') == 'core stair st1'][0]
_zones = _S.approach_bboxes(_core_st)
_blockers = [
    o
    for o in dc.objs
    if (o.get('grp') or '').startswith('plan ')
    and o['kind'] in ('partition', 'wall')
    and any(_S.plan_clash(_E.bbox_of(o), z) for z in _zones)
]
check(
    'R6 no plan partition stands in the stair approach zone',
    bool(_zones) and not _blockers,
    ([o['id'] for o in _blockers][:6], _zones),
)
check('R6 the reply says the approach zone was kept clear', 'approach zone' in txt, txt[-200:])
