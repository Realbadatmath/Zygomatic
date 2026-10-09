# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""roof_kit — the whole roof deck as ONE call (2026-09-16).

The 09-12 run spent five drawing calls on the roof and still shipped a plain
basin beside the air-handling plant: add_parapet, add_infinity_pool over cells
the model guessed, add_rooftop_plant (which drops its units on the centre line,
straight into the view), and then two moves that never happened because the
budget was gone.

build_roof_deck does the arithmetic once, in the order the deck needs it:

    guard first  — a parapet on every edge BEFORE the water, so
                   add_infinity_pool finds the view-side one and turns it glass
                   (it only ever raises/reglasses a guard that already exists).
    pool         — a band along the `view` facade: long side parallel to that
                   facade, reaching the deck edge so the weir IS the edge,
                   1.2 m of walkway on the other three sides, 1.5 m clear of
                   every core that reaches the deck, whole cells.
    plant        — add_rooftop_plant has no placement argument (mep_services.py
                   :329 spreads one unit per kind along x on the centre line),
                   so the units are placed and then MOVED into the strip on the
                   side opposite the view, clear of the cores and >= 2 m from
                   the water.
    door         — a head house the stair arrives in gets a door facing the pool
                   if it has none.

Every rule it satisfies by construction is a rule deck_rules.check_roof_deck
measures afterwards; the reply prints that count. No new kinds, no new checks:
the records are the ones add_parapet / add_infinity_pool / add_rooftop_plant /
add_opening already make, and if any of them refuses the drawing is put back
exactly the way it was.
"""

from __future__ import annotations

import copy
import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
DESIGN_CHECKS: list = []

POOLS = ('infinity', 'plain', 'none')
GUARDS = ('glass', 'solid', 'none')
SIDES = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west'}
LETTER = {'north': 'n', 'south': 's', 'east': 'e', 'west': 'w'}
OPP = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}

CORE_CLEAR = 1.5  # m of deck between the water and any core — deck_rules.CORE_CLEAR
WALK_MIN = 1.2  # m of walkway on every side that is not the weir — deck_rules.WALK_MIN
LOUNGE_STRIP = 2.0  # m kept behind the pool for the loungers and the fire pit
PLANT_CLEAR = 2.0  # m between the plant and the water — deck_rules.PLANT_CLEAR
POOL_MAX_DEPTH = 6.0  # m: past this a rooftop pool is a reservoir
POOL_MIN_SIDE = 4.0  # m: the long side — water_leisure.POOL_MIN_SIDE
POOL_MIN_BAND = 3.0  # m: the short side (into the plate)
DECK_TOL = 0.35  # m of slop when a record is matched to the deck level
EDGE_TOL = 0.6  # m a guard may sit off the envelope line
GUARD_H = 1.1  # m — finish_rules.DECK_GUARD_H
GUARD_T = 0.03
GUARD_IN = 0.05  # the guard's outer face this far inside the deck edge
PLANT_EDGE = 0.6  # m of deck kept outboard of a plant unit
PLANT_CORE = 1.0  # m between a plant unit and a core — object_specs "plant_room" clear_r
PLANT_POOL = 1.5  # m between a plant unit and ANY pool-group record (see pool_group_bbox)
# Everything add_infinity_pool leaves on the deck around the water. object_specs
# .check_clearances measures the plant's 1 m maintenance clearance against these
# records' OWN plan bboxes — an underwater light_point carries p.r = 5, so its
# bbox is a 10 m square — which is why the plant strip is set out against the
# whole group's bbox and not against the basin alone (2026-09-16: the live tower
# put "o1318 parasol 1" 0.86 m and "o1328 underwater light" 1.00 m inside it).
POOL_GROUP_KINDS = (
    'pool',
    'sun_lounger',
    'umbrella',
    'tree_palm',
    'sofa',
    'armchair',
    'cylinder',
    'light_point',
    'deck_chair',
    'hot_tub',
)
HEAD_HOUSE = ' head house'
GUARD_WORDS = ('parapet', 'balustrade', 'railing', 'rail')
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'sliding_door', 'door_glass', 'doorway')
CODES = ('deck_', 'inf_', 'pool_', 'circ_head_house', 'finish_deck')


# ── the sibling families, fetched at CALL time (alphabetical load order) ─────
def _m(name):
    return A.EXT_MODULES.get(name)


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _bbox(o):
    return _m('envelope_rules').bbox_of(o)


def _half(o, axis: str) -> float:
    """Half the record's plan extent on one world axis."""
    bb = _bbox(o)
    return (bb[2] - bb[0]) / 2 if axis == 'x' else (bb[3] - bb[1]) / 2


def _gap(a, b) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dz = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dz)


def _failed(r: str) -> bool:
    """A.call_tool turns a TypeError into 'bad arguments for <tool>: ...' and an
    unknown name into 'unknown tool <x>' — neither starts with 'refused', and
    both mean the call drew nothing. Treating them as success is how a macro
    ends up reporting a roof it never built."""
    s = str(r or '').lstrip()
    return s.startswith('refused') or s.startswith('bad arguments for') or s.startswith('unknown tool')


def _why(r: str) -> str:
    s = str(r or '').strip()
    return s.split('refused:', 1)[-1].strip() if s.startswith('refused') else s.splitlines()[0]


def _snapshot(d: Drawing) -> tuple:
    """Everything an inner tool may change. add_infinity_pool writes a zone into
    the storey below and reglasses guards that were already there, so an undo
    that only dropped new ids would leave the drawing changed."""
    return (copy.deepcopy(d.objs), copy.deepcopy(getattr(d, 'ext', {}) or {}), list(getattr(d, 'selected', []) or []))


def _restore(d: Drawing, snap: tuple) -> None:
    objs, ext, sel = snap
    d.objs[:] = copy.deepcopy(objs)
    try:
        d.ext.clear()
        d.ext.update(copy.deepcopy(ext))
    except AttributeError as _exc:  # noqa: BLE001 — never block an undo
        _zyg_log.debug('drawing has no ext dict to restore: %s', _exc)
    d.selected = list(sel)


def _new(d: Drawing, before: set, kinds=None) -> list:
    return [o['id'] for o in d.objs if o['id'] not in before and (kinds is None or o.get('kind') in kinds)]


def _edge(env, s) -> float:
    return {'n': env['zmin'], 's': env['zmax'], 'w': env['xmin'], 'e': env['xmax']}[s]


# ── what already stands on the deck ─────────────────────────────────────────
def core_rects(d: Drawing, env: dict, group: str) -> list:
    """[(what, id, bbox)] — every core that reaches this deck.

    deck_rules._cores is the authority (it is the rule check_roof_deck applies
    afterwards) and it keys on a record's BASE y, so a lift shaft whose overrun
    stands 1.5 m proud of the deck from a base at 0 m is invisible to it: the
    shafts named by d.ext['core'] — or, when the core was not built by add_core,
    every elevator_shaft record — are measured by their TOP and added here."""
    E, DK = _m('envelope_rules'), _m('deck_rules')
    top = _num(env.get('top_deck'), 0.0)
    out = []
    if DK is not None:
        try:
            for c in DK._cores(d, env, top, getattr(d, 'storey_h', 2.7) or 2.7):
                out.append((c['what'], c['id'], tuple(c['bb'])))
        except Exception as _exc:  # noqa: BLE001 — a helper never blocks a draw
            _zyg_log.debug('deck_rules core scan failed: %s', _exc)
    ext_core = (getattr(d, 'ext', {}) or {}).get('core') or {}
    named = set(ext_core.get(group, {}).get('lifts') or [])
    for o in d.objs:
        if o.get('hidden') or o.get('kind') != 'elevator_shaft':
            continue
        if named and o['id'] not in named:
            continue
        if _num(o.get('y'), 0.0) + _p(o, 'h', 0.0) <= top + 0.05:
            continue  # stops under the deck: not in the way
        bb = _bbox(o)
        if E.inside(env, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 1.0):
            out.append(('lift shaft overrun', o['id'], bb))
    return out


def guard_sides(d: Drawing, env: dict, group: str) -> dict:
    """{side: [ids]} — the deck-level guards running along each envelope edge."""
    top = _num(env.get('top_deck'), 0.0)
    out = {s: [] for s in SIDES}
    for o in d.objs:
        if o.get('hidden') or o.get('kind') != 'wall':
            continue
        if (o.get('grp') or '') != group:
            continue
        nm = str(o.get('name') or '').lower()
        if not any(w in nm for w in GUARD_WORDS):
            continue
        if abs(_num(o.get('y'), 0.0) - top) > DECK_TOL:
            continue
        ry = _num(o.get('ry'), 0.0)
        for s in ('n', 's', 'e', 'w'):
            along = abs(math.sin(ry)) < 0.02 if s in 'ns' else abs(math.cos(ry)) < 0.02
            near = abs(_num(o.get(('z' if s in 'ns' else 'x')), 0.0) - _edge(env, s)) < EDGE_TOL
            if along and near:
                out[s].append(o['id'])
    return out


def head_houses(d: Drawing, env: dict) -> dict:
    """{group: {'bb', 'doors', 'walls'}} — the head houses standing on this deck."""
    E = _m('envelope_rules')
    out = {}
    for o in d.objs:
        if o.get('hidden'):
            continue
        g = str(o.get('grp') or '')
        if not g.endswith(HEAD_HOUSE):
            continue
        bb = _bbox(o)
        if not E.inside(env, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 1.0):
            continue
        h = out.setdefault(g, {'bb': list(bb), 'doors': 0, 'walls': []})
        h['bb'] = [min(h['bb'][0], bb[0]), min(h['bb'][1], bb[1]), max(h['bb'][2], bb[2]), max(h['bb'][3], bb[3])]
        if str(o.get('kind') or '') in DOOR_KINDS:
            h['doors'] += 1
        if o.get('kind') == 'wall':
            h['walls'].append(o)
    return out


# ── the pool band, solved on whole cells ────────────────────────────────────
def _cells_inside(lo: float, hi: float) -> tuple:
    """(i0, i1) — the whole cell indices completely inside [lo, hi] on one axis,
    or (None, None). A.cell_of/A.cell_centre own the origin and the cell size;
    nothing here does arithmetic on column letters."""
    m = A.cell_size()
    if m <= 0 or hi - lo < m:
        return None, None
    i0 = A.parse_cell(A.cell_of(lo + m / 2, lo + m / 2))[0]
    if A.cell_centre(i0, i0)[0] - m / 2 < lo - 1e-6:
        i0 += 1
    i1 = A.parse_cell(A.cell_of(hi - m / 2, hi - m / 2))[0]
    if A.cell_centre(i1, i1)[0] + m / 2 > hi + 1e-6:
        i1 -= 1
    return (i0, i1) if i1 >= i0 else (None, None)


def pool_band(d: Drawing, env: dict, v: str, cores: list, inset: float) -> tuple:
    """((cell_from, cell_to), rect, why) — the block a pool takes on side `v`.

    `inset` is the deck left between the pool and the view edge: 0 for an
    infinity pool (the weir IS the edge; t_add_pool then pulls it back to
    water_leisure.INF_INSET by itself), WALK_MIN for a plain one."""
    across = 'z' if v in 'ns' else 'x'  # the axis into the plate
    lo_a, hi_a = (env['zmin'], env['zmax']) if across == 'z' else (env['xmin'], env['xmax'])
    lo_b, hi_b = (env['xmin'], env['xmax']) if across == 'z' else (env['zmin'], env['zmax'])
    plate_depth, plate_width = hi_a - lo_a, hi_b - lo_b

    def a_of(bb):  # the core's extent on the view axis
        return (bb[1], bb[3]) if across == 'z' else (bb[0], bb[2])

    def b_of(bb):  # ...and along the facade
        return (bb[0], bb[2]) if across == 'z' else (bb[1], bb[3])

    # A core standing ON the view frontage takes the view: no pool can have it.
    # DOCUMENTED CHOICE (the brief offers either): with the core on the north,
    # view="north" is REFUSED by name rather than quietly swung round to east or
    # west. A caller who asks for north is asking for a view, and the deck it
    # would get instead faces somewhere else — better to say so than to build the
    # wrong roof. The refusal names the core record and the side that does work.
    # (Behind it: add_core's head house fragments the north roof into eight
    # pieces, so add_pool would refuse there anyway, with a worse message.)
    edge = _edge(env, v)
    for what, oid, bb in cores:
        c0, c1 = a_of(bb)
        if min(abs(edge - c0), abs(edge - c1)) < CORE_CLEAR and (
            c0 <= edge <= c1 or min(abs(edge - c0), abs(edge - c1)) < CORE_CLEAR
        ):
            near = min(abs(edge - c0), abs(edge - c1))
            if near < CORE_CLEAR:
                return (
                    None,
                    None,
                    (
                        f'the {what} {oid} stands {near:.2f} m from the {SIDES[v]} edge of '
                        f'"{env["group"]}" — that edge IS the view an infinity pool falls over, and '
                        f'{CORE_CLEAR:g} m of deck has to go round a core: '
                        f'build_roof_deck(view="{SIDES[OPP[v]]}"), or move the core'
                    ),
                )

    # depth into the plate: the core's own reach, the clear round it, the
    # walkway behind the water and the strip the loungers and the fire pit take.
    # "core depth" is the core's OWN extent on the view axis, not its distance
    # from the far edge: read the other way a north core makes 20 - 15.94 - 4.7
    # = -0.64 m and every east/west view is refused on a plate that has 5 m of
    # clear water in it. The clear round the core is then enforced properly by
    # the width shrink below, which is what deck_pool_core actually measures.
    core_depth = 0.0
    for _what, _oid, bb in cores:
        c0, c1 = a_of(bb)
        core_depth = max(core_depth, c1 - c0)
    depth = min(POOL_MAX_DEPTH, plate_depth - core_depth - CORE_CLEAR - WALK_MIN - LOUNGE_STRIP)
    if depth < POOL_MIN_BAND:
        return (
            None,
            None,
            (
                f'the {plate_depth:.1f} x {plate_width:.1f} m deck of "{env["group"]}" leaves '
                f'{max(depth, 0.0):.1f} m for the water on the {SIDES[v]} side once '
                f'{core_depth:.1f} m of core, {CORE_CLEAR:g} m of clearance, a {WALK_MIN:g} m walkway '
                f'and a {LOUNGE_STRIP:g} m lounge strip are taken — a pool is at least '
                f'{POOL_MIN_SIDE:g} x {POOL_MIN_BAND:g} m'
            ),
        )

    # the band, and the width along the facade
    if v in ('n', 'w'):
        a0, a1 = lo_a + inset, lo_a + inset + depth
    else:
        a0, a1 = hi_a - inset - depth, hi_a - inset
    b0, b1 = lo_b + WALK_MIN, hi_b - WALK_MIN
    # a core that intrudes into the band pushes the width away from itself
    blocker = None
    for what, oid, bb in cores:
        ca0, ca1 = a_of(bb)
        if ca1 <= a0 - CORE_CLEAR or ca0 >= a1 + CORE_CLEAR:
            continue
        cb0, cb1 = b_of(bb)
        # the clear counts here too: a core that stops 0.8 m short of the band
        # still has to be walked round, and b0/b1 shrink as we go, so the test
        # must carry CORE_CLEAR or the second core reads as "outside" the band
        # the first one just pushed towards it
        if cb1 <= b0 - CORE_CLEAR or cb0 >= b1 + CORE_CLEAR:
            continue
        blocker = (what, oid)
        if (cb0 + cb1) / 2 <= (b0 + b1) / 2:
            b0 = max(b0, cb1 + CORE_CLEAR)
        else:
            b1 = min(b1, cb0 - CORE_CLEAR)
    if b1 - b0 < POOL_MIN_SIDE:
        extra = f' once {CORE_CLEAR:g} m is kept clear of {blocker[0]} {blocker[1]}' if blocker else ''
        return (
            None,
            None,
            (
                f'the {SIDES[v]} band of "{env["group"]}" is {max(b1 - b0, 0.0):.1f} m wide{extra} — '
                f'a pool is at least {POOL_MIN_SIDE:g} m on its long side: '
                f'build_roof_deck(view="{SIDES[OPP[v]]}"), or a bigger plate'
            ),
        )

    ia0, ia1 = _cells_inside(a0, a1)
    ib0, ib1 = _cells_inside(b0, b1)
    if ia0 is None or ib0 is None:
        return (
            None,
            None,
            (
                f'the {SIDES[v]} band of "{env["group"]}" ({a1 - a0:.1f} x {b1 - b0:.1f} m) holds no '
                f'whole {A.cell_size():g} m cells — place the pool by hand with add_infinity_pool'
            ),
        )
    if across == 'z':
        cf, ct = A.cell_name(ib0, ia0), A.cell_name(ib1, ia1)
    else:
        cf, ct = A.cell_name(ia0, ib0), A.cell_name(ia1, ib1)
    rect = tuple(A.block_bounds(cf, ct))
    if min(rect[2] - rect[0], rect[3] - rect[1]) < POOL_MIN_BAND - 1e-6:
        return (
            None,
            None,
            (
                f'the {SIDES[v]} band of "{env["group"]}" snaps to {rect[2] - rect[0]:.0f} x '
                f'{rect[3] - rect[1]:.0f} m of whole cells — a pool is at least '
                f'{POOL_MIN_SIDE:g} x {POOL_MIN_BAND:g} m'
            ),
        )
    for what, oid, bb in cores:
        g = _gap(rect, tuple(bb))
        if g < CORE_CLEAR - 1e-6:
            return (
                None,
                None,
                (
                    f'the {SIDES[v]} band {cf}..{ct} comes within {g:.2f} m of {what} {oid} — '
                    f'{CORE_CLEAR:g} m of deck must go round a core: '
                    f'build_roof_deck(view="{SIDES[OPP[v]]}"), or move the core'
                ),
            )
    return (cf, ct), rect, ''


# ── the plant strip on the side away from the view ──────────────────────────
def pool_group_bbox(d: Drawing, env: dict, top: float) -> tuple:
    """(xmin, zmin, xmax, zmax) of the water AND everything add_infinity_pool
    leaves on the deck with it — loungers, parasols, palms, the fire-pit lounge
    and the underwater lights — or None when the deck holds no pool group.

    The plant strip is set out against THIS, not against the basin: the checks
    that fire on a rooftop are object_specs.check_clearances, which measures the
    plant's 1 m maintenance clearance against each of these records' own plan
    bbox, one at a time."""
    E = _m('envelope_rules')
    out = None
    for o in d.objs:
        if o.get('hidden') or str(o.get('kind') or '') not in POOL_GROUP_KINDS:
            continue
        if abs(_num(o.get('y'), 0.0) - top) > DECK_TOL:
            continue
        bb = _bbox(o)
        if not E.inside(env, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 0.0):
            continue
        out = bb if out is None else (min(out[0], bb[0]), min(out[1], bb[1]), max(out[2], bb[2]), max(out[3], bb[3]))
    return tuple(out) if out else None


def plant_band(env: dict, cores: list, keep_out, away: str) -> tuple:
    """(lo, hi) — the run of the `away` axis a plant unit's BLOCK may occupy:
    PLANT_EDGE inboard of the deck edge, PLANT_POOL clear of the pool group,
    PLANT_CORE clear of every core. hi <= lo means there is no strip at all."""
    if away in 'ns':
        e0, e1 = env['zmin'], env['zmax']

        def band_of(bb):
            return bb[1], bb[3]
    else:
        e0, e1 = env['xmin'], env['xmax']

        def band_of(bb):
            return bb[0], bb[2]

    if keep_out is None:
        lo, hi = e0 + PLANT_EDGE, e1 - PLANT_EDGE
    elif away in ('n', 'w'):
        lo, hi = e0 + PLANT_EDGE, band_of(keep_out)[0] - PLANT_POOL
    else:
        lo, hi = band_of(keep_out)[1] + PLANT_POOL, e1 - PLANT_EDGE
    for _what, _oid, bb in cores:  # keep the units off the cores
        c0, c1 = band_of(bb)
        if c1 + PLANT_CORE <= lo or c0 - PLANT_CORE >= hi:
            continue
        under, over = (lo, min(hi, c0 - PLANT_CORE)), (max(lo, c1 + PLANT_CORE), hi)
        lo, hi = under if (under[1] - under[0]) >= (over[1] - over[0]) else over
        if hi - lo <= 0:
            break
    return lo, hi


def head_house_top(d: Drawing, env: dict, top: float) -> tuple:
    """(bbox, y) of the head-house roof on this deck — the only other surface a
    roof plant unit can stand on when the deck strip is too short — or None."""
    E = _m('envelope_rules')
    best = None
    for o in d.objs:
        if o.get('hidden') or not str(o.get('grp') or '').endswith(HEAD_HOUSE):
            continue
        if str(o.get('kind') or '') not in A.DECK_KINDS:
            continue
        y = _num(o.get('y'), 0.0) + _p(o, 't', 0.0)
        if y <= top + 0.5:
            continue
        bb = _bbox(o)
        if not E.inside(env, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 0.0):
            continue
        if best is None or y > best[1]:
            best = (tuple(bb), y)
    return best


# ── the tool ────────────────────────────────────────────────────────────────
def t_build_roof_deck(
    d: Drawing,
    a,
    group='',
    pool='infinity',
    view='south',
    depth=1.4,
    loungers=True,
    lounge=True,
    plant=True,
    guard='glass',
    name='',
) -> str:
    """Lay out a whole roof deck: guard, pool, plant, head-house door, receipt.

    Each of the five stages is a function of `roof_kit_deck`, called here in the
    order the one body ran them. A stage returns the refusal text instead of
    `''` when it cannot go on, and this function owns the single `_restore` that
    puts the drawing back before that refusal is returned — so a refused deck
    leaves nothing behind, exactly as before.
    """
    from . import roof_kit_deck as RD  # deferred: roof_kit_deck imports this module

    plan, why = RD.deck_plan(d, group, pool, view, guard, name)
    if plan is None:
        return why

    snap = _snapshot(d)
    before = {o['id'] for o in d.objs}
    b = RD.DeckBuild()

    # ── 1. the guard, BEFORE the water ───────────────────────────────────────
    why = RD.build_guard(d, plan, b)
    if why:
        _restore(d, snap)
        return why
    plan.env = _m('envelope_rules').group_envelope(d, plan.g) or plan.env

    # ── 2. the pool on the view side ─────────────────────────────────────────
    cores = core_rects(d, plan.env, plan.g)
    why = RD.build_pool(d, plan, cores, b, depth, loungers, lounge)
    if why:
        _restore(d, snap)
        return why

    # ── 3. the plant, moved to the side away from the view ───────────────────
    if plant:
        why = RD.build_plant(d, plan, cores, b)
        if why:
            _restore(d, snap)
            return why

    # ── 4. a head house you can get out of ───────────────────────────────────
    why = RD.build_doors(d, plan, b)
    if why:
        _restore(d, snap)
        return why

    # ── 5. what the rules make of it ─────────────────────────────────────────
    return RD.deck_receipt(d, plan, before, b)


def roof_findings(d: Drawing) -> tuple:
    """(errors, warnings) — the deck_rules / water_leisure / head-house / deck
    finish findings of design_rules.run_checks, and nothing else."""
    DR = _m('design_rules')
    if DR is None:
        return [], []
    try:
        found = DR.run_checks(d) or []
    except Exception as exc:  # noqa: BLE001 — never block a draw on a check
        return [{'sev': 'info', 'code': 'roof_check_failed', 'text': f'design_check could not run ({exc!r})'}], []
    mine = [f for f in found if str(f.get('code') or '').startswith(CODES)]
    return ([f for f in mine if f.get('sev') == 'error'], [f for f in mine if f.get('sev') == 'warn'])


TOOLS = [
    (
        {
            'name': 'build_roof_deck',
            'description': (
                'The whole roof deck of a building in ONE call. It puts a 1.1 m guard on every deck edge '
                'FIRST (so the pool tool finds the view-side one and turns it glass), then an infinity pool '
                'in a band along the `view` facade — its long side parallel to that facade, its weir ON the '
                'deck edge, 1.2 m of walkway on the other three sides and 1.5 m of deck clear of every '
                'stair, lift shaft and head house that reaches the deck — with the loungers, parasols, '
                'palms, fire-pit lounge, entry steps and underwater lights add_infinity_pool builds; then '
                'the rooftop plant, MOVED to the strip on the opposite side (add_rooftop_plant has no side '
                'argument and drops its units on the centre line, in the view); then a door in the head '
                'house if the stair arrives in a sealed box. Use this instead of add_parapet + '
                'add_infinity_pool + add_rooftop_plant. It refuses when the core stands on the view edge, '
                'or when the plate leaves less than 4 x 3 m of water, and names the side to use instead; '
                'if an inner call refuses, nothing is left behind.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'the building group draw_box printed'},
                    'pool': {'type': 'string', 'enum': list(POOLS)},
                    'view': {
                        'type': 'string',
                        'enum': ['north', 'south', 'east', 'west'],
                        'description': 'the side the water falls away towards',
                    },
                    'depth': {'type': 'number', 'description': 'water depth, 1.0-2.0 m'},
                    'loungers': {'type': 'boolean'},
                    'lounge': {'type': 'boolean'},
                    'plant': {'type': 'boolean'},
                    'guard': {'type': 'string', 'enum': list(GUARDS)},
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_build_roof_deck,
    ),
]

# Short on purpose: this family is ALWAYS in the prompt (it is not in
# arch_assistant.PROMPT_FAMILIES), and the tower request has ~30 chars of slack
# left in its 45 000 budget. The detail lives in the tool schema, which is never
# trimmed, and water_leisure's paragraph lost the rooftop recipe to pay for this.
PROMPT = 'ROOF: build_roof_deck(group, view) lays the whole roof deck out in one call, to the deck rules.'
if len(PROMPT) > 200:
    raise RuntimeError(f'roof_kit PROMPT is {len(PROMPT)} chars — the budget is 200')

EXAMPLES = [
    {
        'ask': 'finish the roof of the tower: an infinity pool looking south, loungers, the plant out of the view',
        'calls': [{'tool': 'build_roof_deck', 'args': {'group': 'tower', 'view': 'south'}}],
    },
    {
        'ask': 'maak het dakterras van de toren af, met zwembad naar het westen',
        'calls': [{'tool': 'build_roof_deck', 'args': {'group': 'tower', 'view': 'west'}}],
    },
]
