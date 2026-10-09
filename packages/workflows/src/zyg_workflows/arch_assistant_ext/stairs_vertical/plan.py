# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stairs_vertical.plan — the plan geometry two cores are refused on, and the head house.

Verbatim sections of the original stairs_vertical.py (lines 157-423): the approach /
head zones, the plan-clash predicates, the group material / centre / floor readers
and _head_house.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.stairs_vertical.constants import (
    A,
    Drawing,
    HEAD_MARGIN,
    _envelope,
    _num,
    _probe,
    _zyg_log,
    math,
)


# ── two cores may not occupy one plan (2026-09-12) ───────────────────────────
# Live run 038ca075c052: add_stair(FH93, u, 1.2) drew a 3.44 x 2.60 m plan
# (x 11.78..15.22) and add_elevator then sank shafts at FF93 (x 10.6..12.4) and
# FJ93 (14.6..16.4) — 0.62 m inside BOTH of them. Worse, the stair's foot and
# head both sit on its local -X edge (flight A starts and flight B returns
# there) and had nothing but shaft wall to step onto. Neither tool looked at the
# other's records, so both refusals live here.
APPROACH_M = 1.2  # m of floor a person needs at a stair's foot / head
CLASH_TOL = 0.05  # plan overlap under this is a rounding artefact
CORE_STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')


def approach_bboxes(o: dict) -> list:
    """The plan bboxes of the floor a person needs to step onto at the ends of a
    stair stack. A u stair turns back on itself, so BOTH its foot and its head
    are beyond its local -X edge: one zone. A straight flight has one end each
    side: two. A winder or a spiral arrives on its own turn — no zone."""
    E = _envelope()
    k = str(o.get('kind') or '')
    if E is None or k not in ('stair_u', 'stair_straight'):
        return []
    L, W = E._plan_size(o)
    ry = _num(o.get('ry'), 0.0)
    ux, uz = math.cos(ry), -math.sin(ry)  # local +X in world
    off = L / 2 + APPROACH_M / 2
    out = []
    for sign in (-1,) if k == 'stair_u' else (-1, 1):
        zx = _num(o.get('x'), 0.0) + sign * ux * off
        zz = _num(o.get('z'), 0.0) + sign * uz * off
        out.append(E.bbox_of(_probe('stair_landing', {'w': APPROACH_M, 'd': W, 't': 0.15}, zx, zz, ry)))
    return out


def head_bboxes(o: dict) -> list:
    """The plan bboxes of the floor a person steps ONTO at the TOP of a stair
    record — the arrival landing, one storey (steps x rise) above o['y'].

    A u stair turns back on itself, so flight B returns over flight A and its
    head is beyond the SAME local -X edge as its foot: approach_bboxes' one zone,
    read one storey higher. A straight flight climbs away from its foot, so its
    head is the +X zone alone. A winder or a spiral arrives on its own turn, and
    a landing inside the plan is not a zone outside it — no bbox.

    The 09-12 run's floor opening was the whole stair bbox + 5 cm on every
    storey, so this zone was the only floor at the stair and it was cut away:
    circulation_rules.check_landing_floor measures exactly these rectangles."""
    E = _envelope()
    k = str(o.get('kind') or '')
    if E is None or k not in ('stair_u', 'stair_straight'):
        return []
    L, W = E._plan_size(o)
    ry = _num(o.get('ry'), 0.0)
    ux, uz = math.cos(ry), -math.sin(ry)  # local +X in world
    off = L / 2 + APPROACH_M / 2
    sign = -1 if k == 'stair_u' else 1
    zx = _num(o.get('x'), 0.0) + sign * ux * off
    zz = _num(o.get('z'), 0.0) + sign * uz * off
    return [E.bbox_of(_probe('stair_landing', {'w': APPROACH_M, 'd': W, 't': 0.15}, zx, zz, ry))]


def plan_overlap(a, b) -> tuple:
    """(ox, oz): how far two axis-aligned plan bboxes overlap on each axis.
    Negative on an axis means they are clear of each other on it."""
    return (min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1]))


def plan_clash(a, b, tol: float = CLASH_TOL) -> bool:
    ox, oz = plan_overlap(a, b)
    return ox > tol and oz > tol


def y_overlap(y0a: float, y1a: float, y0b: float, y1b: float) -> bool:
    """Do two height spans share any storey? A stair record spans y .. y +
    steps * rise, a shaft y .. y + p.h."""
    return y0a < y1b - 0.05 and y0b < y1a - 0.05


def _clear_cell(sx: float, sz: float, dist: float, sign: int) -> str:
    """The nearest cell whose CENTRE is at least `dist` from sx in direction sign.
    cell_of() returns the cell that contains a point, and that cell's centre can
    be nearer the stair than the point asked for — so the named cell is walked
    outward until it really is clear. Advice that still gets refused is worse
    than no advice."""
    cell = A.cell_of(sx + sign * dist, sz)
    for _ in range(4):
        cx, cz = A.cell_centre(*A.parse_cell(cell))
        if sign * (cx - sx) >= dist - 1e-6:
            break
        cell = A.cell_offset(cell, east=sign)
    return cell


def _spacing_note(word: str, L: float, W: float, sx: float, sz: float, shaft_w: float) -> str:
    """The clause that says where the lift CAN go: a lift is clear of a stair
    when it is past the approach zone on the foot side, and past the plan on the
    other. Both cells are named, so the next call needs no arithmetic."""
    west = L / 2 + APPROACH_M + shaft_w / 2
    east = L / 2 + shaft_w / 2
    return (
        f' — a {L:.1f} x {W:.1f} m {word} stair keeps lift centres >= {west:.1f} m west or '
        f'>= {east:.1f} m east of its cell; the nearest clear cells are '
        f'{_clear_cell(sx, sz, west, -1)} / {_clear_cell(sx, sz, east, 1)}'
    )


def _stack_plan(d: Drawing, o: dict) -> tuple:
    """(L, W) of the LARGEST record of the stack `o` belongs to. The flight that
    climbs to a roof deck is longer than a typical storey (3.44 m against 3.16 m
    for a 1.2 m u stair), so advice measured off one record would name a cell the
    top flight still reaches."""
    E = _envelope()
    x, z, k = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), o.get('kind')
    L, W = E._plan_size(o)
    for q in d.objs:
        if q.get('kind') != k or q.get('hidden'):
            continue
        if abs(_num(q.get('x'), 0.0) - x) > 0.05 or abs(_num(q.get('z'), 0.0) - z) > 0.05:
            continue
        ql, qw = E._plan_size(q)
        L, W = max(L, ql), max(W, qw)
    return L, W


def _core_span(o: dict) -> tuple:
    """(y0, y1) of a core record: a shaft is p.h tall, a stair climbs its own
    steps x rise."""
    y = _num(o.get('y'), 0.0)
    p = o.get('p') or {}
    if str(o.get('kind') or '') == 'elevator_shaft':
        return y, y + _num(p.get('h'), 0.0)
    return y, y + _num(p.get('steps'), 0.0) * _num(p.get('rise'), 0.0)


def _group_mat(d: Drawing, group: str, kinds: tuple, default: str) -> str:
    """The group's finish for the first of `kinds` it actually has — in order, so
    a roof deck's own material beats the slabs that come before it in d.objs."""
    for k in kinds:
        for o in d.objs:
            if o.get('grp') == group and o.get('kind') == k:
                return o.get('mat') or default
    return default


def _group_centre(d: Drawing, E, group: str, env) -> tuple:
    """The plan centre a facade's OUTWARD normal is measured against."""
    if env:
        return (env['xmin'] + env['xmax']) / 2, (env['zmin'] + env['zmax']) / 2
    recs = [o for o in d.objs if o.get('grp') == group] or list(d.objs)
    return (sum(o['x'] for o in recs) / len(recs), sum(o['z'] for o in recs) / len(recs))


def _outward(w: dict, cx: float, cz: float) -> tuple:
    """(ry, nx, nz): the wall's own ry turned so its local -Z points AWAY from
    (cx, cz), and that unit vector in world x/z. Local -Z in world is
    (-sin ry, -cos ry). The same rule as balconies_facade._outward — a facade
    tool that guesses the sign hangs its element inside the building."""
    ry = _num(w.get('ry'), 0.0)
    nx, nz = -math.sin(ry), -math.cos(ry)
    if (w['x'] - cx) * nx + (w['z'] - cz) * nz < 0:
        ry += math.pi
        nx, nz = -nx, -nz
    return ry, nx, nz


def _group_floors(d: Drawing, group: str, H: float) -> dict:
    """{storey: (y, kind)} for every slab / flat roof of the group — read off the
    records themselves, so the storeys a shaft asks to be cut are exactly the
    ones slab_voids.check_voids will measure it against."""
    out: dict = {}
    for o in d.objs:
        if o.get('grp') != group or o.get('kind') not in ('slab', 'roof_flat') or o.get('hidden'):
            continue
        try:
            st = int(A.storey_index(d, o, H))
        except Exception:  # noqa: BLE001 — never block a draw
            st = A.storey_of(_num(o.get('y'), 0.0), H)
        out.setdefault(st, (_num(o.get('y'), 0.0), o['kind']))
    return out


def _door_leaf_mat(d: Drawing, wall_mat):
    """The material a door LEAF takes when the caller named none.

    A leaf never inherits the wall it sits in — the head house borrowed the
    tower's wall material and shipped a board-formed CONCRETE door on the
    2026-09-16 luxury tower. The leaf is the finish schedule's own answer for
    the kind (oak on a luxury job, timber on a standard one). The single
    exception is a glass leaf in a glass wall: a door in a curtain wall reads
    as glazing, and turning it opaque is the porte-cochere bug again.
    """
    if str(wall_mat or '') == 'mat_glass':
        return wall_mat
    FS = A.EXT_MODULES.get('finish_schedule')
    if FS is not None:
        try:
            m = FS.default_mat(d, 'door', None)
            if m:
                return m
        except Exception as _exc:  # noqa: BLE001 — a finish never blocks a draw
            _zyg_log.debug('finish-schedule door material lookup failed: %s', _exc)
    return 'mat_timber'


def _head_house(d: Drawing, E, group: str, bb, deck_y: float, env: dict) -> tuple:
    """The little house that roofs a stair arriving on a roof deck: four walls
    around bb + HEAD_MARGIN, a flat roof over them and a door facing the middle
    of the deck. The wall records have the shape t_draw_box makes."""
    m = HEAD_MARGIN
    x0, z0, x1, z1 = bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    W, D = round(x1 - x0, 4), round(z1 - z0, 4)
    H = d.storey_h
    T = d.wall_t
    grp = f'{group} head house'
    w_mat = _group_mat(d, group, ('wall', 'curtain_wall'), 'mat_concrete')
    r_mat = _group_mat(d, group, ('roof_flat', 'roof_shed', 'slab'), w_mat)
    # the door goes in the wall that faces the middle of the deck
    dx, dz = (env['xmin'] + env['xmax']) / 2 - cx, (env['zmin'] + env['zmax']) / 2 - cz
    if abs(dx) > abs(dz):
        door_side = 'east' if dx > 0 else 'west'
    else:
        door_side = 'south' if dz >= 0 else 'north'
    sides = {
        'north': (cx, z0, W, 0.0),
        'south': (cx, z1, W, 0.0),
        'west': (x0, cz, D, math.pi / 2),
        'east': (x1, cz, D, math.pi / 2),
    }
    ids = []
    for side, (x, z, L, ry) in sides.items():
        o = d.new(
            'wall',
            {'len': round(L, 4), 'h': H, 't': T, 'base': round(deck_y, 4)},
            x,
            z,
            deck_y,
            ry,
            w_mat,
            name=f'{side} wall head house',
            grp=grp,
        )
        ids.append(o['id'])
    roof = d.new(
        'roof_flat',
        {'w': W, 'd': D, 't': 0.2, 'base': round(deck_y, 4)},
        cx,
        cz,
        deck_y + H,
        0.0,
        r_mat,
        name='head house roof',
        grp=grp,
    )
    dx_, dz_, _L, dry = sides[door_side]
    door = d.new(
        'door',
        {'w': 0.9, 'h': 2.1, 'base': round(deck_y, 4)},
        dx_,
        dz_,
        deck_y,
        dry,
        _door_leaf_mat(d, w_mat),
        name=f'head house door ({door_side})',
        grp=grp,
    )
    return grp, ids + [roof['id'], door['id']], door_side
