# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.circulation_rules.common import (
    SHAFT_KIND,
    STAIR_KINDS,
    _cap,
    _env_mod,
    _group_records,
    _in_env,
    _p,
    lift_reach,
    stair_height,
)
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import (
    CLASH_TOL,
    CORE_KINDS,
    _core_span,
    _overlap,
    _stairs_mod,
    _word,
)
import re

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num


# ── 6. the floor at the OTHER end: landings, headroom, enclosure, lift lobbies ─
# The 09-12 run drew a stair that was, on paper, correct: one record per storey,
# rails, a head house, an opening in every floor it passed. What it could not be
# asked was where a person STANDS when the flight ends. The opening cut for the
# stair was the whole stair bbox + 5 cm on every storey, so the only floor at the
# stair was the treads themselves: every flight arrived over the void of the
# flight below. The same blindness gives a slab over a flight (headroom 0), a
# stair well open to the office on four sides, a shaft that stops level with the
# deck it serves (no motor room) or a shaft coming up through the pool, and a
# partition parked in front of the lift doors.
LANDING_TOL_Y = 0.35  # m a deck top may sit off the storey it serves
LANDING_VOID = 0.5  # fraction of the arrival zone a void may eat
HEADROOM_MIN = 0.3  # m of slab over a flight, both axes, before headroom is gone
ENCLOSE_M = 0.4  # m within which a wall / shaft encloses a stair side
ENCLOSE_RUN = 0.3  # m of that wall along the side before it counts
ENCLOSE_OPEN = 2  # open sides before the well is "open to the floor"
ENCLOSE_TALL = 5  # storeys at which an open well stops being a warning
ENCLOSE_FITTED = 3  # partitions on a storey before it counts as fitted out
OVERRUN_MIN = 1.2  # m of shaft above the top served deck: the motor room
LIFT_LANDING_M = 1.8  # m of floor in front of the lift doors
LANDING_BLOCK = 0.15  # m a wall may intrude into that landing
LIFT_CLEAR_W = 0.9  # m of the door width that must stay walkable
ENCLOSE_KINDS = ('wall', 'partition', 'curtain_wall', 'wall_arc', SHAFT_KIND)
SLAB_KINDS = ('slab', 'slab_poly', 'roof_flat')
POOL_KINDS = ('pool',)


def _voids_mod():
    return A.EXT_MODULES.get('slab_voids')


def _rect_inter(a, b) -> list:
    return [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]


def _rect_area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _storey_of(o, base: float, H: float) -> int:
    return int(round((_num(o.get('y'), 0.0) - base) / H)) if H else 0


def _group_env(E, d: Drawing, o):
    """(group, env) of the building a record stands in, or (None, None)."""
    g = E.group_at(d, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0))
    if not g:
        return None, None
    try:
        return g, E.group_envelope(d, g)
    except Exception:  # noqa: BLE001 — never block a check
        return None, None


def _biggest_void(d: Drawing, group: str, storey: int, zone) -> list:
    """The registered opening of that floor that eats most of `zone`."""
    V = _voids_mod()
    if V is None:
        return [0.0, 0.0, 0.0, 0.0]
    best = [0.0, 0.0, 0.0, 0.0]
    for e in V.voids_at(d, group, storey):
        r = _rect_inter(
            zone,
            [_num(e.get('xmin'), 0.0), _num(e.get('zmin'), 0.0), _num(e.get('xmax'), 0.0), _num(e.get('zmax'), 0.0)],
        )
        if _rect_area(r) > _rect_area(best):
            best = r
    return best


def _cells_of(bb) -> tuple:
    return A.cell_of(bb[0] + 0.01, bb[1] + 0.01), A.cell_of(bb[2] - 0.01, bb[3] - 0.01)


def check_landing_floor(d: Drawing) -> list:
    """Every flight arrives on a LANDING, not on the hole it climbed through.

    stairs_vertical owns where that floor is — approach_bboxes at the foot,
    head_bboxes at the head — because it is the tool that cuts the opening."""
    out = []
    try:
        E, S = _env_mod(), _stairs_mod()
        heads_of = getattr(S, 'head_bboxes', None) if S is not None else None
        if E is None or not callable(heads_of):
            return []
        H = getattr(d, 'storey_h', 0.0) or 2.7
        for o in d.objs:
            if o.get('hidden') or str(o.get('kind') or '') not in STAIR_KINDS:
                continue
            zones = heads_of(o)
            if not zones:
                continue
            g, env = _group_env(E, d, o)
            if env is None:
                continue
            base = _num(env.get('y0'), 0.0)
            head_y = _num(o.get('y'), 0.0) + (stair_height(o) or H)
            st = int(round((head_y - base) / H)) if H else 0
            for zb in zones:
                zx, zz = (zb[0] + zb[2]) / 2, (zb[1] + zb[3]) / 2
                floor = any(abs(t - head_y) <= LANDING_TOL_Y for t, _r in A.deck_tops(d, zx, zz))
                hole = _biggest_void(d, g, st, zb)
                eaten = _rect_area(hole) / max(_rect_area(zb), 1e-9)
                if floor and eaten < LANDING_VOID:
                    continue
                if _rect_area(hole) > 0:
                    why = (
                        f'arrives on {hole[2] - hole[0]:.1f} x {hole[3] - hole[1]:.1f} m of void, no landing '
                        f'— the floor opening cut for the stair is too big'
                    )
                else:
                    why = (
                        f'arrives {zb[2] - zb[0]:.1f} x {zb[3] - zb[1]:.1f} m off its top tread where storey '
                        f'{st} has no floor at {head_y:.1f} m, no landing'
                    )
                out.append(
                    {
                        'sev': 'error',
                        'code': 'circ_landing_floor',
                        'text': f'{o["id"]} {_word(str(o.get("kind") or ""))} storey {st}: {why}: '
                        f'cut_floor_opening only over the flights',
                    }
                )
                break  # one finding per record
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'circ_landing_floor',
                'text': f'the arrival-landing check could not read this drawing ({exc})',
            }
        ]
    return _cap(out)


def check_headroom(d: Drawing) -> list:
    """The floor above a flight is a void over the WHOLE flight, or the person
    on the seventh step walks into it."""
    out = []
    try:
        E, S = _env_mod(), _stairs_mod()
        if E is None:
            return []
        heads_of = getattr(S, 'head_bboxes', None) if S is not None else None
        H = getattr(d, 'storey_h', 0.0) or 2.7
        slabs = [s for s in d.objs if str(s.get('kind') or '') in SLAB_KINDS and not s.get('hidden')]
        for o in d.objs:
            if o.get('hidden') or str(o.get('kind') or '') not in STAIR_KINDS:
                continue
            g, env = _group_env(E, d, o)
            if env is None:
                continue
            base = _num(env.get('y0'), 0.0)
            bb = E.bbox_of(o)
            want = _num(o.get('y'), 0.0) + H
            heads = heads_of(o) if callable(heads_of) else []
            for s in slabs:
                if abs(_num(s.get('y'), 0.0) - want) > LANDING_TOL_Y:
                    continue
                sb = E.bbox_of(s)
                ox, oz = _overlap(bb, sb)
                if ox <= HEADROOM_MIN or oz <= HEADROOM_MIN:
                    continue
                r = _rect_inter(bb, sb)
                cx, cz = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                if any(h[0] <= cx <= h[2] and h[1] <= cz <= h[3] for h in heads):
                    continue  # that piece IS the arrival landing
                c0, c1 = _cells_of(bb)
                out.append(
                    {
                        'sev': 'error',
                        'code': 'circ_headroom',
                        'text': f'{o["id"]} {_word(str(o.get("kind") or ""))}: '
                        f'{"flat roof" if s.get("kind") == "roof_flat" else "slab"} {s["id"]} covers '
                        f'{ox:.1f} x {oz:.1f} m of the flight — headroom 0; '
                        f'cut_floor_opening("{g}", {_storey_of(s, base, H)}, "{c0}", "{c1}")',
                    }
                )
                break  # one finding per stair record
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {'sev': 'info', 'code': 'circ_headroom', 'text': f'the headroom check could not read this drawing ({exc})'}
        ]
    return _cap(out)


def _open_sides(d: Drawing, E, bb, base: float, H: float, storey: int) -> int:
    """How many of a stair's four plan sides have no wall, partition or shaft
    within ENCLOSE_M of them on its own storey."""
    bands = {
        'west': [bb[0] - ENCLOSE_M, bb[1], bb[0] + 0.05, bb[3]],
        'east': [bb[2] - 0.05, bb[1], bb[2] + ENCLOSE_M, bb[3]],
        'north': [bb[0], bb[1] - ENCLOSE_M, bb[2], bb[1] + 0.05],
        'south': [bb[0], bb[3] - 0.05, bb[2], bb[3] + ENCLOSE_M],
    }
    walls = []
    for w in d.objs:
        if w.get('hidden') or str(w.get('kind') or '') not in ENCLOSE_KINDS:
            continue
        wy = _num(w.get('y'), 0.0)
        wh = _p(w, 'h', H)
        if str(w.get('kind') or '') == SHAFT_KIND:
            if not (wy - 0.05 <= base + storey * H <= wy + wh + 0.05):
                continue
        elif _storey_of(w, base, H) != storey:
            continue
        walls.append(E.bbox_of(w))
    n = 0
    for side, band in bands.items():
        along_z = side in ('west', 'east')  # the side runs along Z, so measure Z
        hit = False
        for wb in walls:
            ox, oz = _overlap(band, wb)
            if ox <= 0 or oz <= 0:
                continue
            if (oz if along_z else ox) >= ENCLOSE_RUN:
                hit = True
                break
        if not hit:
            n += 1
    return n


def check_enclosure(d: Drawing) -> list:
    """A stair well on an occupied floor is a room, not a sculpture: an open
    well is the shaft a fire climbs. Only a floor that has been FITTED OUT is
    measured — a bare shell has no floor for the stair to be open to."""
    out = []
    try:
        E = _env_mod()
        if E is None:
            return []
        FR = A.EXT_MODULES.get('finish_rules')
        lux = False
        try:
            lux = str(FR.finish_level(d)) == 'luxury' if FR is not None else False
        except Exception:  # noqa: BLE001
            lux = False
        H = getattr(d, 'storey_h', 0.0) or 2.7
        for _g, env in E.envelopes(d).items():
            storeys = int(env.get('storeys') or 0)
            if storeys < 2:
                continue
            base = _num(env.get('y0'), 0.0)
            seen: dict = {}
            for q in d.objs:
                if str(q.get('kind') or '') != 'partition' or q.get('hidden') or not _in_env(E, env, q):
                    continue
                s = _storey_of(q, base, H)
                seen[s] = seen.get(s, 0) + 1
            # a room is four partitions: one stray partition does not make a floor
            fitted = {s for s, n in seen.items() if n >= ENCLOSE_FITTED}
            if not fitted:
                continue
            for o in _group_records(d, E, env, STAIR_KINDS):
                st = _storey_of(o, base, H)
                if st < 1 or st > storeys - 1 or st not in fitted:
                    continue
                n = _open_sides(d, E, E.bbox_of(o), base, H, st)
                if n < ENCLOSE_OPEN:
                    continue
                sev = 'error' if (storeys >= ENCLOSE_TALL and lux) else 'warn'
                out.append(
                    {
                        'sev': sev,
                        'code': 'circ_enclosure',
                        'text': f'{o["id"]} {_word(str(o.get("kind") or ""))} storey {st}: {n} of its 4 '
                        f'plan sides have no wall within {ENCLOSE_M:g} m — the stair is open to the '
                        f'floor: add_room around it or accept (fire separation)',
                    }
                )
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'circ_enclosure',
                'text': f'the stair-enclosure check could not read this drawing ({exc})',
            }
        ]
    return _cap(out)


def check_overrun(d: Drawing) -> list:
    """A lift that serves the top deck needs the motor room ABOVE it. A shaft
    that stops level with the deck it serves has nowhere for the machine and no
    run-by for the car."""
    out = []
    try:
        E = _env_mod()
        if E is None:
            return []
        H = getattr(d, 'storey_h', 0.0) or 2.7
        for o in d.objs:
            if o.get('hidden') or str(o.get('kind') or '') != SHAFT_KIND:
                continue
            g, env = _group_env(E, d, o)
            if env is None:
                continue
            storeys = int(env.get('storeys') or 0)
            top_deck = env.get('top_deck')
            if storeys < 1 or top_deck is None:
                continue
            base = _num(env.get('y0'), 0.0)
            if storeys not in lift_reach(o, base, H):
                continue  # it does not serve the deck
            top = _num(o.get('y'), 0.0) + _p(o, 'h', 0.0)
            need = _num(top_deck, 0.0) + OVERRUN_MIN - top
            if need <= 1e-6:
                continue
            out.append(
                {
                    'sev': 'error',
                    'code': 'circ_overrun',
                    'text': f'{o["id"]} lift shaft serves the deck of "{g}" at {_num(top_deck, 0.0):g} m but '
                    f'stops at {top:g} m — the motor room wants {OVERRUN_MIN:g} m of overrun above the '
                    f'top served deck, so the shaft has to reach '
                    f'{_num(top_deck, 0.0) + OVERRUN_MIN:g} m ({need:.1f} m more); '
                    f'add_elevator(cell, 0, {storeys}) draws it 1.5 m over the deck',
                }
            )
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'circ_overrun',
                'text': f'the lift-overrun check could not read this drawing ({exc})',
            }
        ]
    return _cap(out)


def _deck_reported(d: Drawing) -> list:
    """The record ids of every (pool, core) pair deck_rules.check_roof_deck has
    already named, one set per deck_pool_core finding. Two families may measure
    the same two records; only one of them says it."""
    K = A.EXT_MODULES.get('deck_rules')
    fn = getattr(K, 'check_roof_deck', None) if K is not None else None
    if not callable(fn):
        return []
    try:
        return [set(re.findall(r'\bo\d+\b', f.get('text') or '')) for f in fn(d) if f.get('code') == 'deck_pool_core']
    except Exception:  # noqa: BLE001
        return []


def _core_ids(d: Drawing, o) -> set:
    """Every record id of the core `o` belongs to. deck_rules names a core by
    its TOPMOST record (the stair is one record per storey), so a pair is the
    same pair when any record of the run is named."""
    grp = str(o.get('grp') or '')
    if not grp:
        return {o['id']}
    return {q['id'] for q in d.objs if str(q.get('grp') or '') == grp} | {o['id']}


def check_shaft_in_water(d: Drawing) -> list:
    """A core does not come up through the water. deck_rules measures the 1.5 m
    of walking room round a core (deck_pool_core); this is the hard overlap, and
    it stays silent on any pair that family has already named."""
    out = []
    try:
        E = _env_mod()
        if E is None:
            return []
        H = getattr(d, 'storey_h', 0.0) or 2.7
        pools = [o for o in d.objs if str(o.get('kind') or '') in POOL_KINDS and not o.get('hidden')]
        if not pools:
            return []
        said = _deck_reported(d)
        for o in d.objs:
            k = str(o.get('kind') or '')
            if o.get('hidden') or k not in CORE_KINDS:
                continue
            mine = _core_ids(d, o)
            g, env = _group_env(E, d, o)
            if env is None:
                continue
            top_deck = env.get('top_deck')
            if top_deck is None:
                continue
            y0, y1 = _core_span(o)
            if y1 < _num(top_deck, 0.0) - H - LANDING_TOL_Y:
                continue  # it stops well below the deck
            bb = E.bbox_of(o)
            for w in pools:
                if abs(_num(w.get('y'), 0.0) - _num(top_deck, 0.0)) > H:
                    continue
                ox, oz = _overlap(bb, E.bbox_of(w))
                if ox <= CLASH_TOL or oz <= CLASH_TOL:
                    continue
                if any(w['id'] in ids and (ids & mine) for ids in said):
                    continue  # deck_rules says this pair
                out.append(
                    {
                        'sev': 'error',
                        'code': 'circ_shaft_in_water',
                        'text': f'{o["id"]} {_word(k)} stands in the water of pool {w["id"]}: '
                        f'{ox:.2f} x {oz:.2f} m of overlap — a core comes up THROUGH the deck, so '
                        f'the pool goes elsewhere: add_infinity_pool(cell_from, cell_to) clear of it',
                    }
                )
                break  # one finding per core
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'circ_shaft_in_water',
                'text': f'the core-in-water check could not read this drawing ({exc})',
            }
        ]
    return _cap(out)


def _landing_rect(bb, face: str) -> list:
    """The LIFT_LANDING_M of floor in front of the doors, over the whole shaft
    width. north is -Z, south +Z, as everywhere in the studio."""
    if face == 'north':
        return [bb[0], bb[1] - LIFT_LANDING_M, bb[2], bb[1]]
    if face == 'south':
        return [bb[0], bb[3], bb[2], bb[3] + LIFT_LANDING_M]
    if face == 'west':
        return [bb[0] - LIFT_LANDING_M, bb[1], bb[0], bb[3]]
    return [bb[2], bb[1], bb[2] + LIFT_LANDING_M, bb[3]]


def _landing_gap(bb, face: str, wb) -> float:
    """How far in front of the doors a blocker's near edge stands."""
    if face == 'north':
        return max(0.0, bb[1] - wb[3])
    if face == 'south':
        return max(0.0, wb[1] - bb[3])
    if face == 'west':
        return max(0.0, bb[0] - wb[2])
    return max(0.0, wb[0] - bb[2])


def check_lift_landing(d: Drawing) -> list:
    """A lift door opens onto a lobby. On EVERY served storey the floor in front
    of the doors has to be there and has to be empty."""
    out = []
    try:
        E = _env_mod()
        if E is None:
            return []
        H = getattr(d, 'storey_h', 0.0) or 2.7
        blockers = ('wall', 'partition', 'curtain_wall', 'wall_arc')
        for o in d.objs:
            if o.get('hidden') or str(o.get('kind') or '') != SHAFT_KIND:
                continue
            g, env = _group_env(E, d, o)
            if env is None:
                continue
            base = _num(env.get('y0'), 0.0)
            face = str((o.get('p') or {}).get('door_side') or 'south').strip().lower()
            bb = E.bbox_of(o)
            zone = _landing_rect(bb, face)
            zx, zz = (zone[0] + zone[2]) / 2, (zone[1] + zone[3]) / 2
            hit = None
            for s in lift_reach(o, base, H):
                ys = base + s * H
                if not any(abs(t - ys) <= LANDING_TOL_Y for t, _r in A.deck_tops(d, zx, zz)):
                    hit = (s, None)
                    break
                for w in d.objs:
                    if w.get('hidden') or str(w.get('kind') or '') not in blockers:
                        continue
                    if _storey_of(w, base, H) != s:
                        continue
                    ox, oz = _overlap(zone, E.bbox_of(w))
                    if ox <= LANDING_BLOCK or oz <= LANDING_BLOCK:
                        continue
                    # A wall that only grazes one edge of the landing is the
                    # flank of the lobby, not an obstruction. What decides it is
                    # how much of the door width a person is left to walk on.
                    along_x = face in ('south', 'north')
                    wide = (zone[2] - zone[0]) if along_x else (zone[3] - zone[1])
                    if wide - (ox if along_x else oz) >= LIFT_CLEAR_W:
                        continue
                    hit = (s, w)
                    break
                if hit:
                    break
            if hit is None:
                continue
            s, w = hit
            if w is None:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'circ_lift_landing',
                        'text': f'{o["id"]} lift shaft storey {s}: the {LIFT_LANDING_M:g} m of floor in '
                        f'front of the {face} doors is not there — the doors open onto a void; '
                        f'cut_floor_opening only over the shaft',
                    }
                )
            else:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'circ_lift_landing',
                        'text': f'{o["id"]} lift shaft storey {s}: {w.get("kind")} {w["id"]} stands '
                        f'{_landing_gap(bb, face, E.bbox_of(w)):.1f} m in front of the doors — '
                        f'layout_floor(core_from, core_to) leaves the landing free',
                    }
                )
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'circ_lift_landing',
                'text': f'the lift-landing check could not read this drawing ({exc})',
            }
        ]
    return _cap(out)
