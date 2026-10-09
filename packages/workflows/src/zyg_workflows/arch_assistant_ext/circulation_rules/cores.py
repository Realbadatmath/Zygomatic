# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.circulation_rules.common import (
    DECK_BAND,
    GUARD_H,
    HEAD_MARGIN,
    LANDING_DROP,
    LANDING_TOL,
    LIFT_FROM,
    MAX_FLIGHT,
    MAX_SPAN,
    MAX_TURNED,
    SHAFT_KIND,
    STAIR_KINDS,
    WALL_KINDS,
    WORD,
    _cap,
    _env_mod,
    _floors,
    _group_records,
    _is_guard,
    _p,
    _ranges,
    _steps,
    deck_occupants,
    lift_reach,
    stair_height,
    stair_reach,
)

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num


# ── 1. continuity: every floor reached, and the deck when people use it ──────
def check_continuity(d: Drawing) -> list:
    E = _env_mod()
    if E is None:
        return []
    H = getattr(d, 'storey_h', 0.0) or 2.7
    out = []
    for g, env in E.envelopes(d).items():
        storeys = int(env.get('storeys') or 0)
        if storeys < 2:
            continue
        base = _num(env.get('y0'), 0.0)
        floors = _floors(d, env, H)
        slab_storeys = sorted(s for s in floors if 0 <= s < storeys)
        if not slab_storeys:
            continue

        stairs = _group_records(d, E, env, STAIR_KINDS)
        reached = set()
        for o in stairs:
            reached.update(stair_reach(o, base, H))
        # storey 0 is walked into, so only the floors above it need a stair
        gaps = [s for s in slab_storeys if s >= 1 and s not in reached]
        if gaps:
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_no_stair',
                    'text': f'group "{g}": storeys {_ranges(gaps)} have no stair — '
                    f'add_stair(cell, from_storey=0, to_storey={storeys}, kind="u")',
                }
            )

        occ = deck_occupants(d, E, env)
        if occ and storeys not in reached:
            what = str(occ[0].get('kind') or 'something').replace('_', ' ')
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_deck_no_stair',
                    'text': f'the roof deck of "{g}" carries a {what} but no stair reaches it — '
                    f'add_stair(cell, from_storey=0, to_storey={storeys}) climbs to the deck '
                    f'and builds the head house',
                }
            )

        if storeys < LIFT_FROM:
            continue
        shafts = _group_records(d, E, env, (SHAFT_KIND,))
        if not shafts:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'circ_no_lift',
                    'text': f'"{g}" is {storeys} storeys and has no lift — '
                    f'add_elevator(cell, from_storey=0, to_storey={storeys}) sinks a shaft with '
                    f'a door on every floor',
                }
            )
            continue
        want = set(slab_storeys)
        served_all: set = set()
        for o in shafts:
            served_all.update(lift_reach(o, base, H))
        if want <= served_all:
            continue
        for o in shafts:
            served = lift_reach(o, base, H)
            missing = sorted(want - set(served))
            if not missing:
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_lift_partial',
                    'text': f'lift {o["id"]} serves storeys {served[0]}..{served[-1]} of '
                    f'{slab_storeys[0]}..{slab_storeys[-1]} — storeys {_ranges(missing)} have no '
                    f'lift; add_elevator(cell, from_storey=0, to_storey={storeys})',
                }
            )
    return _cap(out)


# ── 2. flight length: 18 steps, one storey, one record ──────────────────────
def _flight_phrase(o) -> str:
    k = str(o.get('kind') or '')
    run = _p(o, 'run', 0.28)
    n = int(_steps(o))
    if k == 'stair_u':
        a = (n // 2) * run
        return f'two {a:.1f} m flights'
    if k == 'stair_l':
        return f'flights of {_p(o, "steps_a", 0.0) * run:.1f} and {_p(o, "steps_b", 0.0) * run:.1f} m'
    if k == 'stair_spiral':
        return f'{n} treads in one turn'
    return f'one {n * run:.1f} m flight'


def check_flights(d: Drawing) -> list:
    H = getattr(d, 'storey_h', 0.0) or 2.7
    limit = {'stair_straight': MAX_FLIGHT, 'stair_u': MAX_TURNED, 'stair_l': MAX_TURNED, 'stair_winder': MAX_TURNED}
    out = []
    for o in d.objs:
        k = str(o.get('kind') or '')
        if k not in STAIR_KINDS or o.get('hidden'):
            continue
        n = _steps(o)
        span = round(stair_height(o) / H, 3) if H else 0.0
        too_many = n > limit.get(k, 1e9)
        if not too_many and span <= MAX_SPAN:
            continue
        out.append(
            {
                'sev': 'error',
                'code': 'circ_flight',
                'text': f'{o["id"]} {WORD.get(k, k)}: {int(n)} steps = {_flight_phrase(o)} over '
                f'{round(span, 1):g} storeys — a flight is <= {MAX_FLIGHT} steps and a record '
                f'climbs one storey; add_stair draws one per storey',
            }
        )
    return _cap(out)


# ── 3. guarding: rails on a flight, something along a landing edge ──────────
def _landing_open_edges(d: Drawing, o) -> int:
    """How many of a landing's four plan edges have no guard within LANDING_TOL."""
    w, dd = _p(o, 'w', 1.2), _p(o, 'd', 1.2)
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    x0, z0, x1, z1 = x - w / 2, z - dd / 2, x + w / 2, z + dd / 2
    top = _num(o.get('y'), 0.0) + _p(o, 't', 0.15)
    guards = [
        g
        for g in d.objs
        if g['id'] != o['id'] and not g.get('hidden') and _is_guard(g) and abs(_num(g.get('y'), 0.0) - top) <= 1.0
    ]
    open_n = 0
    edges = [
        (x0 - LANDING_TOL, z0 - LANDING_TOL, x1 + LANDING_TOL, z0 + LANDING_TOL),
        (x0 - LANDING_TOL, z1 - LANDING_TOL, x1 + LANDING_TOL, z1 + LANDING_TOL),
        (x0 - LANDING_TOL, z0 - LANDING_TOL, x0 + LANDING_TOL, z1 + LANDING_TOL),
        (x1 - LANDING_TOL, z0 - LANDING_TOL, x1 + LANDING_TOL, z1 + LANDING_TOL),
    ]
    for ex0, ez0, ex1, ez1 in edges:
        gx = [g for g in guards if ex0 <= _num(g.get('x'), 0.0) <= ex1 and ez0 <= _num(g.get('z'), 0.0) <= ez1]
        if not gx:
            open_n += 1
    return open_n


def check_stair_guarding(d: Drawing) -> list:
    out = []
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden'):
            continue
        if k in STAIR_KINDS:
            if _num((o.get('p') or {}).get('rails'), 0.0) > 0:
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_stair_guard',
                    'text': f'{o["id"]} {WORD.get(k, k)} has no rails — add_stair draws them (rails=1) / '
                    f'set p.rails on the record',
                }
            )
        elif k == 'stair_landing':
            base = _num((o.get('p') or {}).get('base'), 0.0)
            if _num(o.get('y'), 0.0) - base < LANDING_DROP:
                continue  # no drop under it, nothing to fall off
            if _landing_open_edges(d, o) < 4:
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_landing_guard',
                    'text': f'{o["id"]} stair landing at {_num(o.get("y"), 0.0):.1f} m has no wall, '
                    f'railing or parapet within {LANDING_TOL:g} m of any of its four edges — '
                    f'draw a railing along the open edges',
                }
            )
    return _cap(out)


# ── 4. head house: a stair arrives on the deck INSIDE something ─────────────
def check_head_house(d: Drawing) -> list:
    E = _env_mod()
    if E is None:
        return []
    H = getattr(d, 'storey_h', 0.0) or 2.7
    out = []
    for g, env in E.envelopes(d).items():
        storeys = int(env.get('storeys') or 0)
        top_deck = env.get('top_deck')
        if storeys < 2 or top_deck is None:
            continue
        base = _num(env.get('y0'), 0.0)
        walls = [
            o
            for o in d.objs
            if o.get('kind') in WALL_KINDS
            and not o.get('hidden')
            and _p(o, 'h', 0.0) >= GUARD_H
            and abs(_num(o.get('y'), 0.0) - top_deck) <= DECK_BAND
        ]
        for o in _group_records(d, E, env, STAIR_KINDS):
            top = _num(o.get('y'), 0.0) + stair_height(o)
            if top < top_deck - 0.1 and (top - base) / H < storeys - 0.2:
                continue  # it never gets to the deck
            bb = E.bbox_of(o)
            m = HEAD_MARGIN
            near = [
                w
                for w in walls
                if bb[0] - m <= _num(w.get('x'), 0.0) <= bb[2] + m and bb[1] - m <= _num(w.get('z'), 0.0) <= bb[3] + m
            ]
            if len(near) >= 3:
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_head_house',
                    'text': f'{o["id"]}: the stair to the deck of "{g}" has no head house — it arrives in '
                    f'the open at {top_deck:g} m; add_stair(cell, from_storey=0, '
                    f'to_storey={storeys}) builds one over it',
                }
            )
            break  # one finding per group
    return _cap(out)


# ── 5. two cores in one plan, and a stair with nothing at its foot ──────────
# Live run 038ca075c052: a 3.44 x 2.60 m u stair at FH93 with lift shafts 0.62 m
# inside it either side, and its foot — where flight A starts and flight B
# returns, on its own -X edge — opening onto shaft wall. No check saw either.
CORE_KINDS = STAIR_KINDS + (SHAFT_KIND,)
APPROACH_BLOCKERS = ('wall', 'partition', 'curtain_wall', SHAFT_KIND)
CLASH_TOL = 0.05


def _stairs_mod():
    return A.EXT_MODULES.get('stairs_vertical')


def _word(k: str) -> str:
    return WORD.get(k, 'lift shaft' if k == SHAFT_KIND else str(k))


def _core_span(o) -> tuple:
    """(y0, y1) a core record occupies: a shaft is p.h tall, a stair climbs its
    own steps x rise."""
    y = _num(o.get('y'), 0.0)
    if str(o.get('kind') or '') == SHAFT_KIND:
        return y, y + _p(o, 'h', 0.0)
    return y, y + stair_height(o)


def _overlap(a, b) -> tuple:
    return (min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1]))


def _clash_key(o) -> str:
    """How a core is NAMED in a collapsed finding. A shaft is one record for the
    whole tower, so it is itself; a stair is one record PER STOREY, so the run of
    them is its group (add_stair's own group name), or its name."""
    if str(o.get('kind') or '') == SHAFT_KIND:
        return o['id']
    return str(o.get('grp') or o.get('name') or o['id'])


def check_core_clash(d: Drawing) -> list:
    """A stair and a lift shaft are two cores: neither stands in the other's plan.

    2026-09-16: ONE line per clashing pair of cores, not per record. A stair is
    drawn one record per storey, so the live tower's single mistake — the stair
    well sunk 0.48 m into both lift shafts — filled the whole 8-finding budget
    with forty copies of itself and pushed every other circulation finding out.
    The findings are grouped by (stair group, shaft id) and the storeys they span
    are named in the text instead."""
    E = _env_mod()
    if E is None:
        return []
    H = getattr(d, 'storey_h', 0.0) or 2.7
    cores = [o for o in d.objs if not o.get('hidden') and str(o.get('kind') or '') in CORE_KINDS]
    groups: dict = {}
    order: list = []
    for i, a in enumerate(cores):
        ka = str(a.get('kind') or '')
        for b in cores[i + 1 :]:
            kb = str(b.get('kind') or '')
            if ka != SHAFT_KIND and kb != SHAFT_KIND:
                continue  # two stairs may share one well
            ay0, ay1 = _core_span(a)
            by0, by1 = _core_span(b)
            if not (ay0 < by1 - 0.05 and by0 < ay1 - 0.05):
                continue
            ox, oz = _overlap(E.bbox_of(a), E.bbox_of(b))
            if ox <= CLASH_TOL or oz <= CLASH_TOL:
                continue
            key = (_clash_key(a), ka, _clash_key(b), kb)
            e = groups.get(key)
            if e is None:
                e = groups[key] = {'a': a, 'b': b, 'ox': ox, 'oz': oz, 'storeys': set(), 'n': 0}
                order.append(key)
            e['n'] += 1
            if min(ox, oz) > min(e['ox'], e['oz']):
                e['ox'], e['oz'] = ox, oz
            for o in (a, b):
                if str(o.get('kind') or '') != SHAFT_KIND:
                    e['storeys'].add(int(round((_num(o.get('y'), 0.0) - _p(o, 'base', 0.0)) / H)) if H else 0)
    out = []
    for key in order:
        e = groups[key]
        a, b = e['a'], e['b']
        ka, kb = str(a.get('kind') or ''), str(b.get('kind') or '')
        where = f'storeys {_ranges(e["storeys"])}' if e['storeys'] else 'the whole height'
        many = f' ({e["n"]} stair records)' if e['n'] > 1 else ''
        out.append(
            {
                'sev': 'error',
                'code': 'circ_core_clash',
                'text': f'{key[0]} {_word(ka)} and {key[2]} {_word(kb)} occupy the same plan on {where}'
                f'{many}: {e["ox"]:.2f} x {e["oz"]:.2f} m overlap — a stair and a lift shaft are '
                f'two cores; move one (add_elevator refuses this now)',
            }
        )
    return _cap(out)


def check_stair_approach(d: Drawing) -> list:
    """A stair's foot needs floor to step onto. stairs_vertical owns where that
    floor is (approach_bboxes), because it is the tool that refuses the same
    thing before anything is drawn."""
    E, S = _env_mod(), _stairs_mod()
    zones_of = getattr(S, 'approach_bboxes', None) if S is not None else None
    if E is None or not callable(zones_of):
        return []
    reach = _num(getattr(S, 'APPROACH_M', 1.2), 1.2)
    H = getattr(d, 'storey_h', 0.0) or 2.7
    out = []
    for o in d.objs:
        if o.get('hidden') or str(o.get('kind') or '') not in STAIR_KINDS:
            continue
        zones = zones_of(o)
        if not zones:
            continue
        y = _num(o.get('y'), 0.0)
        for w in d.objs:
            if w.get('hidden') or w['id'] == o['id'] or str(w.get('kind') or '') not in APPROACH_BLOCKERS:
                continue
            if not (y - 0.05 <= _num(w.get('y'), 0.0) <= y + H - 0.05):
                continue
            wbb = E.bbox_of(w)
            if not any(
                min(z[2], wbb[2]) - max(z[0], wbb[0]) > CLASH_TOL and min(z[3], wbb[3]) - max(z[1], wbb[1]) > CLASH_TOL
                for z in zones
            ):
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_stair_approach',
                    'text': f'{o["id"]} {_word(str(o.get("kind") or ""))}: {w["id"]} '
                    f'{w.get("name") or w.get("kind")} stands in the {reach:g} m of floor at its '
                    f'foot — nothing to step onto; move it or the stair',
                }
            )
    return _cap(out)
