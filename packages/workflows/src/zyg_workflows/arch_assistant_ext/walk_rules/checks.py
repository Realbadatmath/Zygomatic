# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .grid import A, BODY_M, CELL, Drawing, _Grid, _cap, _fill, _lbl, _mod, math
from .reading import (
    _Building,
    _cores,
    _deck_is_used,
    _deck_targets,
    _door_rects,
    _entrance_doors,
    _grow,
    _head_house_door,
    _host_of,
    _room_doors,
    _storey_grid,
)

# ── naming the thing in the way ──────────────────────────────────
MAX_TRY = 6  # records taken down and retried before we stop guessing


def _stop_point(B: _Building, grid: _Grid, seen: bytearray, rect) -> tuple:
    """Where the walk runs out: the source-reachable cell closest to the target.

    Indoor cells win outright. On storey 0 the ground outside is walkable — it
    has to be, or nobody could get round to the front door — and the fill leaks
    out through the entrance tunnel and wraps the whole plan, so the closest
    reachable cell to a stair at the north of the core is a patch of lawn on
    the far side of the north facade. Anchor on that and the answer is the
    facade: true, in that knocking it down does let you in, and useless."""
    cx, cz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    best = None
    for i, v in enumerate(seen):
        if not v:
            continue
        px, pz = grid.centre(i)
        dd = (0 if B.E.inside(B.env, px, pz) else 1, (px - cx) ** 2 + (pz - cz) ** 2)
        if best is None or dd < best[0]:
            best = (dd, px, pz)
    return (best[1], best[2]) if best else (cx, cz)


def _in_front(grid: _Grid, stop: tuple, rect) -> list:
    """Record ids crossed by the straight run from where the walk stopped to the
    target, nearest first — what a person standing there is looking at.

    Distance alone cannot separate the partition thrown across a corridor from
    the corridor's own side wall: both touch the spot the walk stopped at, one
    head on and one alongside. This only ever ORDERS candidates, so a record
    the ray misses is still taken down and retried; it just is not tried
    first."""
    ax, az = stop
    bx, bz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    steps = max(2, int(math.hypot(bx - ax, bz - az) / (CELL / 2)))
    out = []
    for k in range(steps + 1):
        t = k / steps
        i = grid.at(ax + (bx - ax) * t, az + (bz - az) * t)
        rid = grid.owner.get(i) if i is not None else None
        if rid and rid not in out:
            out.append(rid)
    return out


def _skip_ids(B: _Building, rec) -> set:
    """Records that are never the answer for this target: the target itself and,
    for a door, the wall it is cut through.

    A door's rect straddles its own host wall, so the host always reads as
    "reachable floor on both flanks" and taking it down does open a path — round
    through the flats. It is a true answer to the wrong question: the wall with
    the door in it is not what stopped anybody.

    Excluding every record that merely OVERLAPS the target rect is too broad. A
    sun lounger's approach rect is 0.8 m of floor round it, and a screen wall
    dropped across the deck clips that rect while still being exactly the thing
    in the way."""
    out = set()
    if rec is None:
        return out
    rid = str(rec.get('id') or '')
    if rid:
        out.add(rid)
    host = _host_of(B.d, rec)
    if host is not None:
        hid = str(host.get('id') or '')
        if hid:
            out.add(hid)
    return out


def _candidates(B: _Building, grid: _Grid, seen: bytearray, back: bytearray, rect, skip: set) -> list:
    """Records that could be the one in the way, the one met first at the head.

    A record qualifies when the source side and the target side both come up
    against it: floor a person reaches from the door on one flank, floor they
    would reach from the target on the other. That is a cheap filter and it
    over-answers — a long facade runs alongside both regions without dividing
    anything — so it only decides the ORDER in which _blocker takes records
    down and tries the walk again."""
    out = []
    reach = grid.squeeze
    stop = _stop_point(B, grid, seen, rect)
    ahead = _in_front(grid, stop, rect)
    sx, sz = stop
    bx, bz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for rid in set(grid.owner.values()):
        if rid in skip:
            continue
        rec = B.d.find(rid)
        bb = B.plan.get(rid)
        if rec is None or bb is None:
            continue
        if bb[2] - bb[0] < BODY_M and bb[3] - bb[1] < BODY_M:
            continue  # a parasol pole divides nothing: you walk round it
        hit_s = hit_t = False
        for i in grid.indices(_grow(bb, 2 * CELL)):
            if not reach[i]:
                continue
            if seen[i]:
                hit_s = True
            elif back[i]:
                hit_t = True
            if hit_s and hit_t:
                break
        if not (hit_s and hit_t):
            continue
        rank = ahead.index(rid) if rid in ahead else len(ahead)
        hx, hz = max(bb[0], min(sx, bb[2])), max(bb[1], min(sz, bb[3]))
        cx, cz = max(bb[0], min(bx, bb[2])), max(bb[1], min(bz, bb[3]))
        out.append((rank, math.hypot(hx - sx, hz - sz), math.hypot(cx - bx, cz - bz), rid, rec))
    out.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return [(t[2], t[3], t[4]) for t in out]


def _without(grid: _Grid, rid: str) -> _Grid:
    """A copy of the grid with one record taken down — its cells given back to
    the floor and the width grids rebuilt, because erosion is what decides
    whether the space it freed is wide enough to walk."""
    sub = _Grid.__new__(_Grid)
    sub.x0, sub.z0, sub.nx, sub.nz = grid.x0, grid.z0, grid.nx, grid.nz
    sub.free = bytearray(grid.free)
    sub.owner = {}
    for i, owner in grid.owner.items():
        if owner == rid:
            sub.free[i] = 1
    sub.erode()
    return sub


def _blocker(B: _Building, grid: _Grid, seen: bytearray, rect, starts: list, rec=None) -> str:
    """The record that is actually in the way: take a candidate down, rebuild
    the width grids without it and walk again. Whichever one restores the path
    is the one to name.

    Guessing from geometry alone does not work. The straight line from the
    entrance crosses every wall on the way, including the ones with a door in
    them, so it names a wall the person walked through ten metres back; and
    "has reachable floor on both flanks" is true of any long facade that merely
    runs alongside the route. Removing it and re-walking is the only test that
    cannot be argued with — it is also the fix the message then recommends."""
    tgt = grid.indices(rect)
    if not any(grid.free[i] for i in tgt):
        # The target is buried, so no clearing of the route can reach it: name
        # whatever stands on it. This is the "stair inside the lift shaft" case
        # the operator reported — the foot of the flight has nothing to step
        # onto, because the shaft is already standing there.
        own = [grid.owner[i] for i in tgt if i in grid.owner]
        if own:
            on = B.d.find(max(set(own), key=own.count))
            if on is not None:
                return _lbl(on)
        return 'no floor at all'
    back = _fill(grid, tgt, 'squeeze')
    cands = _candidates(B, grid, seen, back, rect, _skip_ids(B, rec))
    best = None
    for _dd, rid, cand in cands[:MAX_TRY]:
        if not _reach(grid, _fill(_without(grid, rid), starts, 'squeeze'), rect):
            continue
        # Several records can each be A cut. On a corridor floor, taking out the
        # 2 m partition thrown across the corridor opens it, and so does taking
        # out the 20 m wall down one side of it — walk through the flats behind
        # and step back in past the partition. Both are true and only one is
        # worth saying, so name the SMALLEST: the least a person has to move.
        bb = B.plan[rid]
        area = (bb[2] - bb[0]) * (bb[3] - bb[1])
        if best is None or area < best[0]:
            best = (area, cand)
    if best is not None:
        return _lbl(best[1])
    if cands:
        return _lbl(cands[0][2])  # nothing alone opens it; name the nearest
    return 'no floor at all'


def _reach(grid: _Grid, seen: bytearray, rect) -> bool:
    return any(seen[i] for i in grid.indices(rect))


def _cell_name(grid: _Grid, rect) -> str:
    x = (rect[0] + rect[2]) / 2
    z = (rect[1] + rect[3]) / 2
    try:
        return str(A.cell_of(x, z))
    except Exception:  # noqa: BLE001
        return f'({x:.1f}, {z:.1f})'


def _pinch(grid: _Grid, squeeze: bytearray, wide: bytearray, rect) -> str:
    """The narrow place itself, not the room beyond it: of the cells a person
    only gets to sideways (squeeze-reachable, not wide-reachable) the one
    nearest the target is the gap to widen."""
    cx, cz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    best = None
    for i, v in enumerate(squeeze):
        if not v or wide[i]:
            continue
        px, pz = grid.centre(i)
        dd = (px - cx) ** 2 + (pz - cz) ** 2
        if best is None or dd < best[0]:
            best = (dd, px, pz)
    if best is None:
        return _cell_name(grid, rect)
    return _cell_name(grid, (best[1], best[2], best[1], best[2]))


# ── the check ────────────────────────────────────────────────────────────────
def _walk_storey(B: _Building, s: int, srcs: list, targets: list) -> list:
    """srcs / targets: [(word, record, rect)]. One finding per target word."""
    grid = _storey_grid(B, s)
    starts = []
    for _w, _o, r in srcs:
        starts.extend(i for i in grid.indices(r) if grid.free[i])
    if not starts:
        # Nobody can set out at all: the thing they step off onto is itself
        # buried. That is the defect the operator reported — a stair whose foot
        # arrives inside a lift shaft — and it is one finding about the SOURCE,
        # not one per target about places that are innocent.
        buried = []
        for _w, _o, r in srcs:
            buried.extend(grid.owner[i] for i in grid.indices(r) if i in grid.owner)
        src_l = _lbl(srcs[0][1]) if srcs[0][1] is not None else srcs[0][0]
        if not buried:
            return [
                {
                    'sev': 'error',
                    'code': '',
                    'word': 'source',
                    'text': f'{src_l} has no floor under it on storey {s} — there is no slab there at all; '
                    f'add one or move it over one (move_object)',
                }
            ]
        rec = B.d.find(max(set(buried), key=buried.count))
        who = _lbl(rec) if rec is not None else 'something'
        return [
            {
                'sev': 'error',
                'code': '',
                'word': 'source',
                'text': f'{src_l} has nowhere to step off onto on storey {s} — {who} stands on the whole '
                f'of its landing; move one clear of the other (move_object)',
            }
        ]
    wide = _fill(grid, starts, 'wide')
    bad = [t for t in targets if not _reach(grid, wide, t[2])]
    if not bad:
        return []
    squeeze = _fill(grid, starts, 'squeeze')
    src_l = _lbl(srcs[0][1]) if srcs[0][1] is not None else srcs[0][0]
    out, seen_word = [], set()
    for word, rec, rect in bad:
        if word in seen_word:
            continue
        seen_word.add(word)
        label = _lbl(rec) if rec is not None else word
        if _reach(grid, squeeze, rect):
            out.append(
                {
                    'sev': 'warn',
                    'code': 'walk_narrow',
                    'word': word,
                    'text': f'storey {s}: {label} is reachable from {src_l} only through a gap under '
                    f'{BODY_M:g} m at {_pinch(grid, squeeze, wide, rect)} — '
                    f'widen it or move what narrows it',
                }
            )
            continue
        who = _blocker(B, grid, squeeze, rect, starts, rec)
        out.append(
            {
                'sev': 'error',
                'code': '',
                'word': word,
                'blocker': who,
                'text': f'from {src_l} no path reaches {label} on storey {s} — {who} stands in the way; '
                f'move it or put a door through it (add_opening)',
            }
        )
    return out


def check_walkable(d: Drawing) -> list:
    """Every storey of every building: from the way in, can a person reach the
    cores, the room doors and — on a used roof deck — the pool and the loungers?"""
    try:
        return _cap(_walkable(d))
    except Exception as exc:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'walk_error',
                'text': f'the walk check could not run on this drawing ({type(exc).__name__}: {exc}) — '
                f'the drawing is still whatever it is; no walking claim is made',
            }
        ]


def _walkable(d: Drawing) -> list:
    E = _mod('envelope_rules')
    if E is None:
        return []
    H = getattr(d, 'storey_h', 0.0) or 2.7
    out = []
    for g, env in E.envelopes(d).items():
        if int(env.get('storeys') or 0) < 2:
            continue
        out.extend(_walk_group(d, E, g, env, H))
    return out


def _walk_group(d: Drawing, E, g: str, env: dict, H: float) -> list:
    B = _Building(d, E, g, env, H)
    out: list = []

    # ── storey 0: in by the entrance, on to the cores and the room doors ────
    doors = _entrance_doors(d, B)
    cores0 = _cores(B, 0)
    if doors and (cores0 or _room_doors(d, B, 0)):
        srcs = [('entrance', doors[0], _door_rects(E, doors[0], _host_of(d, doors[0]))[0])]
        targets = [(w, o, r) for w, o, r in cores0]
        targets += [('room door', o, r) for o, r in _room_doors(d, B, 0)]
        for f in _walk_storey(B, 0, srcs, targets):
            if f['code']:
                out.append(f)
            elif f['word'] in ('stair', 'lift', 'source'):
                f['code'] = 'walk_entrance_core'
                out.append(f)
            else:
                f['code'] = 'walk_storey'
                out.append(f)

    # ── storeys 1..N-1: out of the core, on to every door and the other core ─
    for s in range(1, B.storeys):
        cores = _cores(B, s)
        rooms = _room_doors(d, B, s)
        if not cores or not rooms and len(cores) < 2:
            continue
        srcs = [c for c in cores if c[0] == 'stair'] or cores[:1]
        rest = [c for c in cores if c is not srcs[0]]
        targets = [('room door', o, r) for o, r in rooms] + [('the other core', o, r) for _w, o, r in rest]
        if not targets:
            continue
        for f in _walk_storey(B, s, srcs, targets):
            f['code'] = f['code'] or 'walk_storey'
            out.append(f)

    # ── the roof deck: out of the head house, on to the pool and the loungers ─
    if _deck_is_used(d, B):
        targets = _deck_targets(B)
        head = _head_house_door(B)
        srcs = []
        if head is not None:
            srcs = [('head house door', head, _door_rects(E, head, _host_of(d, head))[0])]
        else:
            tops = _cores(B, B.storeys)
            srcs = [c for c in tops if c[0] == 'stair'][:1] or tops[:1]
        if srcs and targets:
            for f in _walk_storey(B, B.storeys, srcs, targets):
                f['code'] = f['code'] or 'walk_deck'
                out.append(f)
    for f in out:
        f.pop('word', None)
        f.pop('blocker', None)
    return out


DESIGN_CHECKS = [check_walkable]
