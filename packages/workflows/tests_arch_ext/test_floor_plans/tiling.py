# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from .placing import A, FLOOR, FP, TD, TW, UNIT, assistant, cf, check, ct, dc, kinds_of, math, plan, rows, tool_names

# ── core_from_plan: draw the core the plan itself asks for ───────────────────
# align="core" only agrees with the plan if whoever drew the stair put it where
# the plan has one. core_from_plan removes the guess: it maps the plan's own core
# polygons through the SAME transform place_plan will use on that box, and calls
# add_stair / add_elevator on the cells they land on. The box is TW x TD (the
# fixture floor rounded up, 23 x 19 m) and not 20 x 20: 20/22.945 = 0.87, just
# under the ±12 % gate, so a 20 m plate refuses this plan before anything else
# can be proved about it.
check(
    'core_from_plan is registered as a tool of the family',
    'core_from_plan' in tool_names(),
    [t[0]['name'] for t in FP.TOOLS],
)
check(
    'an EXAMPLE shows core_from_plan, then place_plan(align="core"), then repeat_floor',
    any(
        [c['tool'] for c in e['calls']] == ['core_from_plan', 'place_plan', 'repeat_floor']
        and e['calls'][1]['args'].get('align') == 'core'
        for e in FP.EXAMPLES
    ),
    [[c['tool'] for c in e['calls']] for e in FP.EXAMPLES],
)
check(
    'PROMPT names it and stays inside the 900-char ceiling',
    'core_from_plan' in FP.PROMPT and len(FP.PROMPT) <= 900,
    len(FP.PROMPT),
)

CPLAN = FP.load_plan(FLOOR['id'])
CSTAIRS = (CPLAN.get('core') or {}).get('stairs') or []
CLIFTS = (CPLAN.get('core') or {}).get('lifts') or []
check(
    'the fixture floor carries both a stair and at least one lift polygon',
    len(CSTAIRS) == 1 and len(CLIFTS) >= 1,
    (len(CSTAIRS), len(CLIFTS)),
)

NST = 6
_t, dk = assistant(
    'draw_box', {'centre': 'FH100', 'width': TW, 'depth': TD, 'storeys': NST, 'roof': 'flat', 'name': 'tower'}
)
KTXT = A.call_tool(dk, 'core_from_plan', {'plan_id': FLOOR['id'], 'group': 'tower'})
check('core_from_plan draws the core of a floor plan into the box', not KTXT.startswith('refused:'), KTXT[:200])
kk = kinds_of(dk)
check(f'exactly {NST} stair_u records, one per storey — add_stair semantics', kk.get('stair_u', 0) == NST, kk)
check(
    'one elevator_shaft per lift polygon the plan carries',
    kk.get('elevator_shaft', 0) == len(CLIFTS),
    (kk.get('elevator_shaft'), len(CLIFTS)),
)
KPLATE = FP._group_plate(dk, 'tower', 1)[0]


def on_plate(o):
    b = FP._rec_bbox(o)
    return (
        KPLATE[0] - 0.01 <= b[0] and b[2] <= KPLATE[2] + 0.01 and KPLATE[1] - 0.01 <= b[1] and b[3] <= KPLATE[3] + 0.01
    )


KCORE = [o for o in dk.objs if o['kind'] in ('stair_u', 'elevator_shaft')]
check(
    'every stair and lift record it drew stands inside the plate',
    KCORE and all(on_plate(o) for o in KCORE),
    ([(o['id'], o['kind'], FP._rec_bbox(o)) for o in KCORE if not on_plate(o)][:3], KPLATE),
)
check('the reply hands back the call that follows it', 'place_plan(' in KTXT and 'align="core"' in KTXT, KTXT[-160:])

# the whole point: the drawn stair is where the plan's own stair polygon maps to,
# give or take the cell add_stair snaps to
KT, _e = FP._plan_transform(CPLAN, KPLATE, False, 0)
KPX, KPZ = KT.pt(*FP._poly_centre(CSTAIRS[0]))
KTGT = FP._core_centre(dk, 'tower', 1, KPLATE)
check(
    'the stair stands within half a cell of where the plan puts its own',
    KTGT and math.hypot(KPX - KTGT[0], KPZ - KTGT[1]) <= dk.cell_m * 0.71 + 0.01,
    ((round(KPX, 2), round(KPZ, 2)), KTGT),
)

KPLACE = A.call_tool(dk, 'place_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 1, 'align': 'core'})
check(
    'place_plan(align="core") then lands on that core instead of falling back to centring',
    not KPLACE.startswith('refused:') and 'centred instead' not in KPLACE,
    KPLACE[:240],
)
check(
    'and it says it aligned core, having dropped what crossed it',
    'aligned core' in KPLACE and 'crossed the existing core' in KPLACE,
    KPLACE[-260:],
)

# storeys: the box's own count by default, or the number asked for
_t, dk3 = assistant(
    'draw_box', {'centre': 'FH100', 'width': TW, 'depth': TD, 'storeys': NST, 'roof': 'flat', 'name': 'tower'}
)
A.call_tool(dk3, 'core_from_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storeys': 3})
check('storeys=N draws the core only that far up', kinds_of(dk3).get('stair_u', 0) == 3, kinds_of(dk3))

# ── core_from_plan refusals ──────────────────────────────────────────────────
_t, dkn = assistant(
    'draw_box', {'centre': 'FH100', 'width': TW, 'depth': TD, 'storeys': NST, 'roof': 'flat', 'name': 'tower'}
)
t = A.call_tool(dkn, 'core_from_plan', {'plan_id': UNIT['id'], 'group': 'tower'})
check(
    'a plan with no core on record is REFUSED, pointing at plan_info and the search',
    t.startswith('refused:') and 'no core' in t and 'search_plans' in t,
    t[:220],
)
check(
    'the refusal drew nothing at all',
    not [o for o in dkn.objs if o['kind'] in ('stair_u', 'elevator_shaft')],
    kinds_of(dkn),
)
t = A.call_tool(dk, 'core_from_plan', {'plan_id': FLOOR['id'], 'group': 'tower'})
check(
    'a second core in a box that already has a stair is refused',
    t.startswith('refused:') and 'already has a stair' in t,
    t[:180],
)
t = A.call_tool(dkn, 'core_from_plan', {'plan_id': FLOOR['id']})
check(
    'core_from_plan without a group is refused, naming draw_box', t.startswith('refused:') and 'draw_box' in t, t[:150]
)
t = A.call_tool(dkn, 'core_from_plan', {'plan_id': 'nope_1', 'group': 'tower'})
check(
    'an unknown plan id is refused with the search that lists them',
    t.startswith('refused:') and 'search_plans' in t,
    t[:140],
)
t = A.call_tool(dkn, 'core_from_plan', {'plan_id': FLOOR['id'], 'group': 'nosuchbox'})
check('a group that is not there is refused', t.startswith('refused:'), t[:140])

# ── switches ─────────────────────────────────────────────────────────────────
_t, dn = assistant(
    'place_plan',
    {
        'plan_id': UNIT['id'],
        'cell_from': cf,
        'cell_to': ct,
        'storey': 0,
        'zones': False,
        'fixtures': False,
        'doors': False,
        'windows': False,
    },
)
kn = kinds_of(dn)
check(
    'zones/fixtures/doors/windows can each be switched off',
    kn.get('zone', 0) == 0 and kn.get('door', 0) == 0 and kn.get('window', 0) == 0 and kn.get('partition', 0) > 0,
    kn,
)

# ── tile_units: a WHOLE floor of real flats off a corridor ───────────────────
# The rig is the brief's — draw_box at FH100, storeys 3, a u-stair dropped four
# cells off centre with add_stair so the corridor has to move sideways to pick it
# up. The plate is 24 x 24 m rather than 20 x 20: the twelve fixture units stock
# depths 5.8, 6.4, 7.4, 7.6, 9.5, 9.8, 11.1, 11.6, 13.4, 13.6, 14.4 and 16.4 m, and
# once the corridor has shifted onto an off-centre core a 20 m plate leaves one
# band only 5.3 m deep — one unit fits it, which is honest but proves nothing
# about tiling. 24 m gives bands of 7.3 and 14.3 m and a row of five. depth_tol
# stays at its default 0.8.
TX, TZ = 24, 24
_t, dt = assistant(
    'draw_box', {'centre': 'FH100', 'width': TX, 'depth': TZ, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
)
st_txt = A.call_tool(dt, 'add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 3, 'kind': 'u'})
check('a u-stair stands on storey 1 of the tower', not st_txt.startswith('refused:'), st_txt[:120])

TILE = A.call_tool(dt, 'tile_units', {'group': 'tower', 'storey': 1})
check('tile_units fills the floor', not TILE.startswith('refused:'), TILE[:300])
check(
    'the reply has the shape the operator is promised',
    all(s in TILE for s in ('storey 1:', ' units (', 'in two bands of', 'corridor ', 'records')),
    TILE[:260],
)
check(
    'it names the units it used, with their real widths and which were mirrored',
    'sd_u_' in TILE and ' m,' in TILE and 'mirrored' in TILE,
    TILE[:260],
)
check('and it points at the tool that carries the floor up', 'repeat_floor(' in TILE and 'CREDIT:' in TILE, TILE[-200:])

TSTORE = (dt.ext.get('floor_layouts') or {}).get('1') or {}
check(
    'the floor is registered where repeat_floor looks, as plan_tiles',
    TSTORE.get('use') == 'plan_tiles' and len(TSTORE.get('ids') or []) > 20,
    {kk: TSTORE.get(kk) for kk in ('use', 'units', 'corridor_w', 'bands', 'along')},
)
check(
    'at least three units were placed',
    TSTORE.get('units', 0) >= 3 and len(TSTORE.get('plans') or []) == TSTORE.get('units'),
    (TSTORE.get('units'), TSTORE.get('plans')),
)
check(
    'every id in the store is a record that is really there',
    all(dt.find(i) for i in TSTORE['ids']),
    [i for i in TSTORE['ids'] if not dt.find(i)][:5],
)
check(
    'the plans it used all come from the pack it was asked for',
    TSTORE.get('pack') == 'swiss_dwellings'
    and all(p in {r['id'] for r in rows('unit', 'swiss_dwellings')} for p in TSTORE['plans']),
    (TSTORE.get('pack'), TSTORE.get('plans')),
)

PLATE = FP._group_plate(dt, 'tower', 1)[0]
px0, pz0, px1, pz1 = PLATE
ALONG_X = TSTORE['along'] == 'x'
BAND_A, BAND_B = TSTORE['bands']
CW = TSTORE['corridor_w']
C_LO = (pz0 if ALONG_X else px0) + BAND_A
C_HI = C_LO + CW
check(
    'the two bands and the corridor add up to the plate',
    abs(BAND_A + CW + BAND_B - ((pz1 - pz0) if ALONG_X else (px1 - px0))) < 0.02,
    (BAND_A, CW, BAND_B, PLATE),
)


def ends_of(o):
    """The points that decide whether a record is in a rectangle: both ends of a
    wall, the centre of anything else."""
    if o['kind'] in ('partition', 'wall'):
        return [A._wall_world(o, 0.0), A._wall_world(o, (o['p'] or {}).get('len', 0.0))]
    return [(o['x'], o['z'])]


TRECS = [dt.find(i) for i in TSTORE['ids']]
check(
    'every record it drew is inside the tower envelope',
    all(px0 - 0.06 <= p[0] <= px1 + 0.06 and pz0 - 0.06 <= p[1] <= pz1 + 0.06 for o in TRECS for p in ends_of(o)),
    [
        o['id']
        for o in TRECS
        if any(not (px0 - 0.06 <= p[0] <= px1 + 0.06 and pz0 - 0.06 <= p[1] <= pz1 + 0.06) for p in ends_of(o))
    ][:5],
)

crossers = []
for o in TRECS:
    if o['kind'] != 'partition':
        continue
    vs = [p[1 if ALONG_X else 0] for p in ends_of(o)]
    if max(vs) > C_LO + 0.05 and min(vs) < C_HI - 0.05:
        crossers.append((o['id'], o['name'], round(min(vs), 2), round(max(vs), 2)))
check(
    'no partition crosses the corridor band — the run is walkable end to end',
    not crossers,
    (crossers[:4], round(C_LO, 2), round(C_HI, 2)),
)

CORES = FP._core_rects(dt, 'tower', 1, PLATE)
check('the stair is found on the plate even though add_stair gave it its own group', len(CORES) == 1, CORES)
in_core = [
    (o['id'], o['kind'], o['name'])
    for o in TRECS
    for p in ends_of(o)
    if CORES and CORES[0][0] - 0.01 < p[0] < CORES[0][2] + 0.01 and CORES[0][1] - 0.01 < p[1] < CORES[0][3] + 0.01
]
check('no record it drew stands inside the stair bbox', not in_core, (in_core[:5], CORES))
ck0 = min((r[1] if ALONG_X else r[0]) for r in CORES)
ck1 = max((r[3] if ALONG_X else r[2]) for r in CORES)
check(
    'the corridor band CONTAINS the core — the stair is reached off the corridor',
    C_LO - 0.01 <= ck0 and ck1 <= C_HI + 0.01,
    (round(C_LO, 2), ck0, ck1, round(C_HI, 2)),
)
check(
    'and the reply says the corridor was moved (and widened) to do it',
    'core' in TILE and ('moved' in TILE or 'widened' in TILE),
    TILE[TILE.find('corridor was') :][:160],
)
check(
    'the widened corridor is at least as wide as the core is deep', CW >= (ck1 - ck0) + 0.19, (CW, round(ck1 - ck0, 2))
)

ent = [o for o in TRECS if o['kind'] == 'door' and o['name'] == 'plan entrance']
check(
    'every unit has its front door, and it is on a corridor wall not the facade',
    len(ent) == TSTORE['units']
    and all(min(abs(o['z' if ALONG_X else 'x'] - C_LO), abs(o['z' if ALONG_X else 'x'] - C_HI)) < 0.35 for o in ent),
    [(o['x'], o['z']) for o in ent],
)
czones = [o for o in TRECS if o['kind'] == 'zone' and (o['p'] or {}).get('use') == 'corridor']
check('the corridor itself is a zone', czones, [o['p'].get('use') for o in TRECS if o['kind'] == 'zone'][:6])
check(
    'unit rooms came with the units',
    len([o for o in TRECS if o['kind'] == 'zone']) > len(czones) + 4,
    len([o for o in TRECS if o['kind'] == 'zone']),
)
tattr = dt.ext.get('attributions') or []
check(
    'the pack attribution is recorded once, listing the units used',
    len(tattr) == 1 and 'CC BY' in tattr[0]['text'] and set(TSTORE['plans']) <= set(tattr[0]['plans']),
    tattr,
)

n_before_t = len(dt.objs)
txt = A.call_tool(dt, 'repeat_floor', {'from_storey': 2, 'to_storey': 2, 'source_storey': 1})
check('repeat_floor carries a tiled floor up', not txt.startswith('refused:'), txt[:140])
tcopies = dt.objs[n_before_t:]
check('it copied every record of the floor', len(tcopies) == len(TSTORE['ids']), (len(tcopies), len(TSTORE['ids'])))
check(
    'the copies sit one storey up',
    tcopies and all(abs(o['y'] - (o0['y'] + dt.storey_h)) < 0.02 for o0, o in zip(TRECS, tcopies)),
    sorted({round(o['y'], 3) for o in tcopies})[:4],
)

# the brief's own 20 x 20 rig: fewer units, but the corridor must still find the core
_t, d20 = assistant(
    'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
)
A.call_tool(d20, 'add_stair', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 3, 'kind': 'u'})
t20 = A.call_tool(d20, 'tile_units', {'group': 'tower', 'storey': 1})
s20 = (d20.ext.get('floor_layouts') or {}).get('1') or {}
check(
    'a 20 x 20 plate with an off-centre core still tiles, off a shifted corridor',
    not t20.startswith('refused:')
    and s20.get('use') == 'plan_tiles'
    and s20.get('units', 0) >= 1
    and abs(s20['bands'][0] - s20['bands'][1]) > 1.0,
    (t20[:200], s20.get('bands')),
)

# a centred core leaves the corridor centred
_t, dcz = assistant(
    'draw_box', {'centre': 'FH100', 'width': TX, 'depth': TZ, 'storeys': 2, 'roof': 'flat', 'name': 'tower'}
)
tcz = A.call_tool(dcz, 'tile_units', {'group': 'tower', 'storey': 1})
scz = (dcz.ext.get('floor_layouts') or {}).get('1') or {}
check(
    'with no core at all the corridor stays centred and keeps the width asked for',
    not tcz.startswith('refused:')
    and abs(scz['bands'][0] - scz['bands'][1]) < 0.02
    and abs(scz['corridor_w'] - 1.8) < 1e-6,
    (scz.get('bands'), scz.get('corridor_w'), tcz[:120]),
)

# ── the lift LANDING is keep-out, not just the shaft well ────────────────────
# 2026-09-16: the tiler and the plan placer kept records out of the shaft's own
# footprint and out of nothing else, so on a replayed tower a partition stood
# 0.4 m in front of the lift doors on every storey (circ_lift_landing — and it
# was right, you cannot walk out of a lift into a wall). circulation_rules owns
# the geometry: LIFT_LANDING_M of floor over the whole shaft width, on
# p.door_side.
_t, dli = assistant(
    'draw_box', {'centre': 'FH100', 'width': TX, 'depth': TZ, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
)
li_txt = A.call_tool(dli, 'add_elevator', {'cell': 'FH96', 'from_storey': 0, 'to_storey': 3})
check('(landing) a lift shaft stands on storey 1 of the tower', not li_txt.startswith('refused:'), li_txt[:140])
SHAFT = [o for o in dli.objs if o['kind'] == 'elevator_shaft']
LPLATE = FP._group_plate(dli, 'tower', 1)[0]
WELL = FP._core_rects(dli, 'tower', 1, LPLATE)
LAND = FP._landing_rects(dli, 'tower', 1, LPLATE)
CIRC = A.EXT_MODULES.get('circulation_rules')
check(
    '(landing-A) _core_rects gives the shaft WELL and says nothing about the floor in front',
    len(SHAFT) == 1 and len(WELL) >= 1,
    (len(SHAFT), WELL),
)
check(
    '(landing-B) _landing_rects adds one rect per shaft, LIFT_LANDING_M deep',
    len(LAND) == len(SHAFT) and all(abs(min(r[2] - r[0], r[3] - r[1]) - CIRC.LIFT_LANDING_M) < 0.02 for r in LAND),
    (LAND, getattr(CIRC, 'LIFT_LANDING_M', None)),
)
sbb = [o for o in dli.objs if o['kind'] == 'elevator_shaft'][0]
E3 = A.EXT_MODULES['envelope_rules']
SBB = E3.bbox_of(sbb)
check(
    '(landing-B) the landing is IN FRONT of the doors, not inside the well',
    LAND
    and all(min(r[3], SBB[3]) - max(r[1], SBB[1]) < 0.02 or min(r[2], SBB[2]) - max(r[0], SBB[0]) < 0.02 for r in LAND),
    (LAND, SBB, (sbb['p'] or {}).get('door_side')),
)

tli = A.call_tool(dli, 'tile_units', {'group': 'tower', 'storey': 1})
check('(landing-B) the floor still tiles with the landing kept out', not tli.startswith('refused:'), tli[:200])
sli = (dli.ext.get('floor_layouts') or {}).get('1') or {}
in_land = [
    (o['id'], o['kind'], o['name'])
    for o in (dli.find(i) for i in (sli.get('ids') or []))
    if o is not None and o['kind'] in ('partition', 'wall')
    for p in ends_of(o)
    for r in LAND
    if r[0] + 0.01 < p[0] < r[2] - 0.01 and r[1] + 0.01 < p[1] < r[3] - 0.01
]
check('(landing-B) and no wall it drew stands in front of the lift doors', not in_land, (in_land[:5], LAND))

# ── an opening is placed by its CENTRE but it is cut at its JAMBS ────────────
# 2026-09-16: the clamp held the centre 0.3 m off each wall end, which says
# nothing about where the leaf lands. A 0.95 m plan door centred 0.3 m from the
# end of a 2.75 m party wall hangs 0.175 m out over thin air, and opening_rules
# was right to say so (open_off_wall, o31 on the replayed cottage).
JWALL = {'id': 'jw', 'kind': 'wall', 'x': 0.0, 'z': 0.0, 'ry': 0.0, 'p': {'len': 2.75, 't': 0.1, 'h': 2.7}}
LEAF, OLD_END_TOL = 0.95, 0.3
old_over = (JWALL['p']['len'] / 2 - OLD_END_TOL) + LEAF / 2 - JWALL['p']['len'] / 2
check(
    '(jamb-A) the old centre-only clamp let a 0.95 m leaf run past the wall end',
    old_over > 0.05,
    f'{old_over:.3f} m of leaf over thin air on a {JWALL["p"]["len"]} m wall',
)
jx, jz = FP._on_wall(JWALL, 10.0, 0.0, LEAF)  # asked for, far past the east end
jalong = A.world_to_local(JWALL, jx, jz)[0] + JWALL['p']['len'] / 2
check(
    '(jamb-B) _on_wall keeps half a leaf plus JAMB_M of wall each side',
    abs(jalong - (JWALL['p']['len'] - LEAF / 2 - FP.JAMB_M)) < 1e-6 and jalong + LEAF / 2 <= JWALL['p']['len'] + 1e-9,
    f'centre at {jalong:.3f} m, leaf ends at {jalong + LEAF / 2:.3f} m of {JWALL["p"]["len"]} m, JAMB_M = {FP.JAMB_M}',
)
SHORTW = dict(JWALL, p={'len': 0.9, 't': 0.1, 'h': 2.7})
check(
    '(jamb-B) a wall shorter than the leaf itself carries no opening at all',
    FP._on_wall(SHORTW, 0.0, 0.0, LEAF) == (None, None),
    'the caller drops it rather than cut a hole wider than its host',
)

# ── two rooms, one shared door: the wall keeps the FIRST hole ────────────────
# A surveyed plan lists the door between two rooms ONCE PER ROOM, so the placer
# cut the same hole twice (open_overlap, four such pairs on one replayed tower).
reg: dict = {}
check('(dbl-B) the first opening is cut', FP._claim(reg, JWALL, 0.0, 0.0, LEAF) is True, reg)
check('(dbl-B) the same opening asked for twice is refused', FP._claim(reg, JWALL, 0.0, 0.0, LEAF) is False, reg)
check(
    '(dbl-B) and a second opening clear of the first is cut',
    FP._claim(reg, JWALL, 1.05, 0.0, LEAF) is True,
    f'0.95 m leaves centred 1.05 m apart share {max(0.0, LEAF - 1.05):.2f} m, under OVERLAP_M = {FP.OVERLAP_M}',
)

# ── a window's head must stay under the top of the wall it is cut in ─────────
# The plan's sill and head were surveyed against the storey the plan came from;
# the wall they land on is the studio's. A 0.9 m sill under a 1.9 m sash wants
# 2.80 m of wall and a storey wall is 2.70 m, so the head stood 0.10 m above the
# wall top — not a window, a notch in the roof (open_off_wall x8).
_n = FP._num
raw_high = [
    wd
    for wd in (plan.get('windows') or [])
    if _n(wd.get('sill'), 0.9) + _n(wd.get('h'), 1.4) > dc.storey_h - FP.HEAD_LINTEL
]
check(
    '(head-A) the SURVEYED sill+sash of this plan does not fit a storey wall',
    bool(raw_high),
    f'{len(raw_high)} of {len(plan.get("windows") or [])} windows want more than '
    f'{dc.storey_h - FP.HEAD_LINTEL:.2f} m of wall; tallest '
    f'{max([_n(w.get("sill"), 0.9) + _n(w.get("h"), 1.4) for w in (plan.get("windows") or [])] or [0]):.2f} m',
)
heads = []
for o in dc.objs:
    if o['kind'] != 'window' or not (o.get('grp') or '').startswith('plan '):
        continue
    h = dc.find((o.get('meta') or {}).get('host') or '')
    if h is None:
        continue
    heads.append(
        (o['id'], _n((o['p'] or {}).get('sill'), 0) + _n((o['p'] or {}).get('h'), 0), _n((h['p'] or {}).get('h'), 0))
    )
over = [(i, round(t, 3), round(w, 3)) for i, t, w in heads if t > w - FP.HEAD_LINTEL + 1e-6]
check(
    '(head-B) but every window it DREW keeps HEAD_LINTEL of wall over its head',
    bool(heads) and not over,
    over[:5] or f'{len(heads)} windows drawn, tallest head {max([t for _i, t, _w in heads] or [0]):.2f} m',
)

# ── tile_units refusals ──────────────────────────────────────────────────────
_t, dnarrow = assistant(
    'draw_box', {'centre': 'K100', 'width': 6, 'depth': 6, 'storeys': 2, 'roof': 'flat', 'name': 'block'}
)
t = A.call_tool(dnarrow, 'tile_units', {'group': 'block', 'storey': 0})
check(
    'a block narrower than two bands of min_unit_w is REFUSED',
    t.startswith('refused:') and '6 x 6 m' in t and 'place_plan' in t,
    t[:220],
)
check(
    'the narrow refusal drew nothing',
    kinds_of(dnarrow).get('partition', 0) == 0 and not (dnarrow.ext.get('floor_layouts') or {}),
    kinds_of(dnarrow),
)

# 19 m deep, 1.9 m corridor -> bands of 8.55 m, which falls in the fixtures' widest
# depth gap (7.625 -> 9.471). Nothing is within the default 0.8 m.
_t, dgap = assistant(
    'draw_box', {'centre': 'K100', 'width': 20, 'depth': 19, 'storeys': 2, 'roof': 'flat', 'name': 'slab'}
)
t = A.call_tool(dgap, 'tile_units', {'group': 'slab', 'storey': 0, 'corridor_w': 1.9})
check(
    'a band depth no unit matches is REFUSED, naming the nearest depths either side',
    t.startswith('refused:') and 'nearest depths' in t and '7.6' in t and '9.5' in t,
    t[:220],
)
check(
    'and the refusal hands back the two numbers that would make it work',
    'depth_tol=' in t and 'corridor_w=' in t,
    t[t.find('pass') :][:120],
)
alt = float(t.split('corridor_w=')[1].split()[0].rstrip('.,'))
tgap2 = A.call_tool(dgap, 'tile_units', {'group': 'slab', 'storey': 0, 'corridor_w': alt})
check(
    'the corridor_w the refusal names really does tile the slab', not tgap2.startswith('refused:'), (alt, tgap2[:200])
)
_t, dgap2 = assistant(
    'draw_box', {'centre': 'K100', 'width': 20, 'depth': 19, 'storeys': 2, 'roof': 'flat', 'name': 'slab'}
)
tol2 = float(t.split('depth_tol=')[1].split()[0].rstrip('.,'))
check(
    'so does the depth_tol it names',
    not A.call_tool(
        dgap2, 'tile_units', {'group': 'slab', 'storey': 0, 'corridor_w': 1.9, 'depth_tol': tol2}
    ).startswith('refused:'),
    tol2,
)

t = A.call_tool(A.Drawing(None), 'tile_units', {'storey': 1})
check('tile_units without a group is refused, naming draw_box', t.startswith('refused:') and 'draw_box' in t, t[:140])
t = A.call_tool(dt, 'tile_units', {'group': 'tower', 'storey': 1, 'pack': 'nope'})
check(
    'an unknown pack is refused, listing the packs that are there',
    t.startswith('refused:') and 'swiss_dwellings' in t,
    t[:150],
)
t = A.call_tool(dt, 'tile_units', {'group': 'tower', 'storey': 1, 'corridor_w': 0.8})
check(
    'a corridor under the clear minimum is refused with the spec behind it',
    t.startswith('refused:') and 'pass' in t and 'corridor_w=1.8' in t,
    t[:190],
)
t = A.call_tool(dt, 'tile_units', {'group': 'nosuchbox', 'storey': 1})
check('tiling a group that is not there is refused', t.startswith('refused:'), t[:140])
