# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .grid import (
    A,
    BODY_HI,
    BODY_LO,
    CELL,
    DECK_KINDS,
    DOOR_KINDS,
    DOOR_REACH,
    Drawing,
    ERODE,
    FLOOR_TOL,
    LANDING_M,
    MAX_CELLS,
    OBJ_REACH,
    PAD,
    POLE_KINDS,
    POLE_M,
    ROOF_PLANT,
    SHAFT_KIND,
    SIDE_SHORT,
    STAIR_KINDS,
    _Grid,
    _mod,
    _num,
    _p,
    _zyg_log,
    block_kinds,
    math,
)


# ── reading the drawing once ─────────────────────────────────────────────────
def _rot_rect(E, x, z, w, dd, ry) -> tuple:
    return E._rot_bbox(float(x), float(z), abs(float(w)), abs(float(dd)), float(ry or 0.0))


SQUARE_TOL = math.radians(1.0)  # off-grid by less than this and the bbox IS the wall
OBB_MAX_CELLS = 120_000  # an oblique record whose bbox is bigger is rastered flat


def _obb_of(E, o):
    """(cx, cz, w, d, ry) when the record is turned OFF the grid, else None.

    A record square to the grid is its own bbox, so the cheap slice-wise
    `block` is exact and nothing is gained by walking its cells. A record
    turned by anything else is not: see `_Grid.block_obb` for the tower that
    lost thirteen doors to it."""
    try:
        ry = float(_num(o.get('ry'), 0.0))
        off = abs(((ry + math.pi / 4) % (math.pi / 2)) - math.pi / 4)
        if off <= SQUARE_TOL:
            return None
        w, dd = E._plan_size(o)
        sc = _num(o.get('s'), 1.0) or 1.0
        w, dd = abs(float(w)) * sc, abs(float(dd)) * sc
        if w <= 0 or dd <= 0:
            return None
        c, s = abs(math.cos(ry)), abs(math.sin(ry))
        if ((w * c + dd * s) / CELL) * ((w * s + dd * c) / CELL) > OBB_MAX_CELLS:
            return None
        return (_num(o.get('x'), 0.0), _num(o.get('z'), 0.0), w, dd, ry)
    except Exception:  # noqa: BLE001 — a check never raises
        return None


def _stair_height(o) -> float:
    C = _mod('circulation_rules')
    fn = getattr(C, 'stair_height', None) if C is not None else None
    if callable(fn):
        try:
            return float(fn(o))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('circulation_rules stair height failed: %s', _exc)
    p = o.get('p') or {}
    n = _num(p.get('steps'), 0.0) or (_num(p.get('steps_a'), 0.0) + _num(p.get('steps_b'), 0.0))
    return n * _num(p.get('rise'), 0.0)


def _vspan(o) -> tuple:
    """(y0, y1) the record occupies. A stair climbs its own steps; everything
    else is p.h / p.height / p.t, and a record with no height at all is given a
    0.9 m body so a table is not walked through."""
    y = _num(o.get('y'), 0.0)
    k = str(o.get('kind') or '')
    if k in STAIR_KINDS:
        return y, y + max(_stair_height(o), 0.3)
    p = o.get('p') or {}
    h = _num(p.get('h'), 0.0) or _num(p.get('height'), 0.0) or _num(p.get('t'), 0.0)
    if h <= 0:
        h = 0.9
    return y, y + h * (_num(o.get('s'), 1.0) or 1.0)


def _host_of(d: Drawing, door: dict):
    hid = str((door.get('meta') or {}).get('host') or '')
    if hid:
        h = d.find(hid)
        if h is not None:
            return h
    DR = _mod('design_rules')
    fn = getattr(DR, '_host_wall', None) if DR is not None else None
    if callable(fn):
        try:
            return fn(d, door)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('design_rules host wall lookup failed: %s', _exc)
    return None


def _door_rects(E, door: dict, host) -> tuple:
    """(free tunnel, wide tunnel) of one door: p.w along the host wall, across
    it by half its thickness plus DOOR_REACH — and, for the wide grid, by the
    erosion radius on top, so the tunnel meets the eroded floor either side."""
    ry = _num((host or door).get('ry'), 0.0)
    t = _p(host, 't', 0.2) if host is not None else 0.2
    w = _p(door, 'w', 0.9) or 0.9
    x, z = _num(door.get('x'), 0.0), _num(door.get('z'), 0.0)
    near = t + 2 * DOOR_REACH
    far = t + 2 * (DOOR_REACH + ERODE * CELL)
    return _rot_rect(E, x, z, w, near, ry), _rot_rect(E, x, z, w, far, ry)


def _landing_rect(E, shaft: dict) -> tuple:
    """The LANDING_M of lobby in front of a shaft's door face."""
    bb = E.bbox_of(shaft)
    side = str(_p_str(shaft, 'door_side') or 'south').strip().lower()
    side = SIDE_SHORT.get(side[:1], 'south') if side else 'south'
    if side == 'south':
        return (bb[0], bb[3], bb[2], bb[3] + LANDING_M)
    if side == 'north':
        return (bb[0], bb[1] - LANDING_M, bb[2], bb[1])
    if side == 'east':
        return (bb[2], bb[1], bb[2] + LANDING_M, bb[3])
    return (bb[0] - LANDING_M, bb[1], bb[0], bb[3])


def _p_str(o, k) -> str:
    return str(((o.get('p') or {}).get(k)) or '')


def _grow(bb: tuple, m: float) -> tuple:
    return (bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m)


def _ground_fn(d: Drawing):
    """A cached ground sampler on a 1 m lattice. When the drawing carries no
    ground, terrain or pad record at all the answer is the base plane and no
    sampling is done — that is the common case and it costs nothing."""
    heights = set(getattr(A, 'EXT_HEIGHTS', {}) or {})
    live = any((o.get('kind') in heights or o.get('kind') == 'pad') and not o.get('hidden') for o in d.objs)
    if not live:
        return lambda x, z: 0.0
    cache: dict = {}

    def g(x, z):  # noqa: E306
        key = (int(round(x)), int(round(z)))
        v = cache.get(key)
        if v is None:
            try:
                v = _num(A.ground_height(d, float(key[0]), float(key[1])), 0.0)
            except Exception:  # noqa: BLE001
                v = 0.0
            cache[key] = v
        return v

    return g


class _Building:
    """Everything the walk needs from one group's drawing, read once."""

    def __init__(self, d: Drawing, E, g: str, env: dict, H: float):
        self.d, self.E, self.g, self.env, self.H = d, E, g, env, H
        self.base = _num(env.get('y0'), 0.0)
        self.storeys = int(env.get('storeys') or 0)
        self.rect = (env['xmin'] - PAD, env['zmin'] - PAD, env['xmax'] + PAD, env['zmax'] + PAD)
        blocks = block_kinds()
        self.decks, self.solids, self.doors, self.stairs, self.shafts, self.deck_objs = [], [], [], [], [], []
        self.pools, self.plan, self.obb = [], {}, {}
        for o in d.objs:
            if o.get('hidden'):
                continue
            k = str(o.get('kind') or '')
            try:
                bb = E.bbox_of(o)
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('record bbox unavailable, record skipped: %s', _exc)
                continue
            if bb[2] < self.rect[0] or bb[0] > self.rect[2] or bb[3] < self.rect[1] or bb[1] > self.rect[3]:
                continue
            y0, y1 = _vspan(o)
            if k in DECK_KINDS:
                self.decks.append((bb, y0 + _p(o, 't', 0.22)))
            if k in DOOR_KINDS:
                self.doors.append(o)
            if k in STAIR_KINDS:
                self.stairs.append((o, bb, y0, y1))
            if k == SHAFT_KIND:
                self.shafts.append((o, bb, y0, y1))
            if k == 'pool':
                self.pools.append((o, bb))
            if k in blocks:
                if k in POLE_KINDS:
                    cx, cz = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
                    bb = (cx - POLE_M / 2, cz - POLE_M / 2, cx + POLE_M / 2, cz + POLE_M / 2)
                else:
                    ob = _obb_of(E, o)
                    if ob is not None:
                        self.obb[o['id']] = ob
                self.solids.append((o['id'], bb, y0, y1, o))
                self.plan[o['id']] = bb
        self.ground = _ground_fn(d)

    def storey_of(self, o) -> int:
        return int(round((_num(o.get('y'), 0.0) - self.base) / self.H)) if self.H else 0

    def floor_y(self, s: int) -> float:
        return self.base + s * self.H


# ── the raster of one storey ─────────────────────────────────────────────────
def _storey_grid(B: _Building, s: int) -> _Grid:
    E, d = B.E, B.d
    env, fy = B.env, B.floor_y(s)
    grid = _Grid(*B.rect)
    if grid.cells() > MAX_CELLS:
        raise MemoryError(f'{grid.nx} x {grid.nz} cells')

    # 1. floor — decks whose top sits at this storey, plus the ground outside
    for bb, top in B.decks:
        if abs(top - fy) <= FLOOR_TOL:
            grid.paint(bb, 1, touch=True)
    if s == 0:
        step = max(1, int(round(1.0 / CELL)))
        for iz in range(0, grid.nz, step):
            zc = grid.z0 + (iz + 0.5) * CELL
            for ix in range(0, grid.nx, step):
                xc = grid.x0 + (ix + 0.5) * CELL
                if E.inside(env, xc, zc):
                    continue
                if abs(B.ground(xc, zc) - fy) <= FLOOR_TOL:
                    grid.paint((xc - CELL / 2, zc - CELL / 2, xc + (step - 0.5) * CELL, zc + (step - 0.5) * CELL), 1)

    # 2. registered slab voids are holes in that floor
    V = _mod('slab_voids')
    at = getattr(V, 'voids_at', None) if V is not None else None
    if callable(at):
        try:
            for e in at(d, B.g, s):
                grid.paint(
                    (
                        _num(e.get('xmin'), 0.0),
                        _num(e.get('zmin'), 0.0),
                        _num(e.get('xmax'), 0.0),
                        _num(e.get('zmax'), 0.0),
                    ),
                    0,
                )
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('slab void paint skipped: %s', _exc)

    # 3. solids whose body band crosses this storey
    lo, hi = fy + BODY_LO, fy + BODY_HI
    for rid, bb, y0, y1, _o in B.solids:
        if y1 <= lo + 1e-6 or y0 >= hi - 1e-6:
            continue
        ob = B.obb.get(rid)
        if ob is None:
            grid.block(bb, rid)
        else:
            grid.block_obb(*ob, rid)

    # 4. doors cut through them
    S = _mod('stairs_vertical')
    zones_of = getattr(S, 'approach_bboxes', None) if S is not None else None
    wides = []
    for o in B.doors:
        if B.storey_of(o) != s:
            continue
        near, far = _door_rects(B.E, o, _host_of(d, o))
        grid.unblock(near)
        wides.append(far)

    # 5. a stair's own approach is floor, whatever stands in it elsewhere
    if callable(zones_of):
        for o, _bb, _y0, _y1 in B.stairs:
            if B.storey_of(o) not in (s, s - 1):
                continue
            try:
                for zb in zones_of(o):
                    grid.unblock(zb, only=o['id'])
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('stair approach unblock skipped: %s', _exc)

    grid.erode()
    for far in wides:
        grid.widen(far)
    return grid


# ── what a person walks from, and to ─────────────────────────────────────────
def _entrance_doors(d: Drawing, B: _Building) -> list:
    """Storey-0 doors in an exterior wall, widest first. blender_power owns the
    'which door is the entrance' question; this widens it to every exterior
    door, because a person may come in by any of them."""
    out = []
    for o in B.doors:
        if B.storey_of(o) != 0:
            continue
        host = _host_of(d, o)
        if host is not None and str(host.get('kind') or '') == 'partition':
            continue
        out.append(o)
    out.sort(key=lambda o: (-_p(o, 'w', 0.9), o['id']))
    return out


def _cores(B: _Building, s: int) -> list:
    """[(word, record, rect)] — the stair feet and lift landings of one storey."""
    S = _mod('stairs_vertical')
    zones_of = getattr(S, 'approach_bboxes', None) if S is not None else None
    out = []
    for o, bb, _y0, _y1 in B.stairs:
        if B.storey_of(o) != s:
            continue
        zones = []
        if callable(zones_of):
            try:
                zones = zones_of(o)
            except Exception:  # noqa: BLE001
                zones = []
        out.append(('stair', o, zones[0] if zones else _grow(bb, OBJ_REACH)))
    for o, _bb, y0, y1 in B.shafts:
        doors = (o.get('p') or {}).get('doors')
        if isinstance(doors, (list, tuple)) and doors:
            if s not in {int(_num(v, -1)) for v in doors}:
                continue
        elif not (y0 - 0.1 <= B.floor_y(s) <= y1 + 0.1):
            continue
        out.append(('lift', o, _landing_rect(B.E, o)))
    return out


def _room_doors(d: Drawing, B: _Building, s: int) -> list:
    out = []
    for o in B.doors:
        if B.storey_of(o) != s:
            continue
        host = _host_of(d, o)
        if host is None or str(host.get('kind') or '') != 'partition':
            continue
        near, _far = _door_rects(B.E, o, host)
        out.append((o, near))
    return out


def _deck_targets(B: _Building) -> list:
    """[(word, record, rect)] on the roof deck: the pool's entry steps, every
    lounger, the fire-pit lounge."""
    top = B.env.get('top_deck')
    if top is None:
        return []
    out = []
    for o, bb in B.pools:
        if abs(_num(o.get('y'), 0.0) - top) > B.H:
            continue
        side = SIDE_SHORT.get(_p_str(o, 'steps')[:1].lower() or 'x')
        if side == 'south':
            r = (bb[0], bb[3], bb[2], bb[3] + OBJ_REACH + 0.4)
        elif side == 'north':
            r = (bb[0], bb[1] - OBJ_REACH - 0.4, bb[2], bb[1])
        elif side == 'east':
            r = (bb[2], bb[1], bb[2] + OBJ_REACH + 0.4, bb[3])
        elif side == 'west':
            r = (bb[0] - OBJ_REACH - 0.4, bb[1], bb[0], bb[3])
        else:
            continue
        out.append(('pool steps', o, r))
    for _rid, bb, _y0, _y1, o in B.solids:
        k = str(o.get('kind') or '')
        if abs(_num(o.get('y'), 0.0) - top) > 1.0:
            continue
        if k == 'sun_lounger':
            out.append(('lounger', o, _grow(bb, OBJ_REACH)))
        elif k == 'fire_pit' or 'fire pit' in str(o.get('name') or '').lower():
            out.append(('fire pit', o, _grow(bb, OBJ_REACH)))
    return out


def _deck_is_used(d: Drawing, B: _Building) -> bool:
    C = _mod('circulation_rules')
    fn = getattr(C, 'deck_occupants', None) if C is not None else None
    if callable(fn):
        try:
            return bool(fn(d, B.E, B.env))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('circulation_rules deck occupants failed: %s', _exc)
    top = B.env.get('top_deck')
    return bool(
        top is not None
        and [
            o
            for _r, _b, _y0, _y1, o in B.solids
            if str(o.get('kind') or '') not in ROOF_PLANT and abs(_num(o.get('y'), 0.0) - top) < 0.6
        ]
    )


def _head_house_door(B: _Building):
    for o in B.doors:
        if str(o.get('grp') or '').lower().endswith('head house'):
            return o
    return None
