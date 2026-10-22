# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

#   the original top-level import block lives here verbatim; its siblings
#   re-import from it, so nothing in it is unused.

from __future__ import annotations

import math
from collections import deque

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: the sibling
# modules of the 2026-10 split re-import them from here, which is why the
# verbatim import block was kept. Declaring them makes the re-export deliberate
# rather than an unused import; nothing does ``import *`` from here, so __all__
# changes no behaviour.
__all__ = [
    'Drawing',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.walk_rules')


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
PROMPT = ''

CELL = 0.25  # m per grid cell
PAD = 3.0  # m of ground kept round the envelope (the approach)
BODY_LO, BODY_HI = 0.2, 1.9  # the height band a walking body occupies
FLOOR_TOL = 0.35  # m a deck top may differ from the storey floor
ERODE = 2  # cells of the erosion window each side of a cell
SLACK = 1  # blocked cells the window tolerates (see _Grid.erode)
SQUEEZE_SLACK = 2  # …and the slacker window a squeeze still passes
BODY_M = (2 * ERODE + 1 - SLACK) * CELL  # 1.00 m: comfortable
SQUEEZE_M = (2 * ERODE + 1 - SQUEEZE_SLACK) * CELL  # 0.75 m: turn sideways
DOOR_REACH = 0.3  # m of free floor a door opening cuts each side of its wall
LANDING_M = 1.8  # m of lobby in front of a lift door
OBJ_REACH = 0.8  # m round a solid target a person must reach
MAX_FINDINGS = 8
MAX_CELLS = 600_000  # a grid bigger than this is refused, not crawled

STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')
SHAFT_KIND = 'elevator_shaft'
DECK_KINDS = ('slab', 'slab_poly', 'roof_flat')
WALL_KINDS = ('wall', 'curtain_wall', 'wall_arc', 'partition')
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'door_french')

# What stands in a person's way. The floor/deck-hosted specs of object_specs are
# added to this at run time (that is where "a desk is furniture" is written);
# these are the kinds the brief names outright plus the ones no spec covers.
BLOCK_KINDS = frozenset(
    set(WALL_KINDS)
    | set(STAIR_KINDS)
    | {
        SHAFT_KIND,
        'elevator_car',
        'escalator',
        'stair_landing',
        'column_round',
        'column_rect',
        'column_h',
        'buttress',
        'portal_frame',
        'sofa',
        'armchair',
        'chair',
        'desk',
        'table',
        'dining_table',
        'coffee_table',
        'bed',
        'bed_single',
        'bed_double',
        'wardrobe',
        'bookcase',
        'tv_unit',
        'nightstand',
        'kitchen_counter',
        'kitchen_island',
        'fridge',
        'stove',
        'washing_machine',
        'dishwasher',
        'toilet',
        'washbasin',
        'shower',
        'bathtub',
        'boiler',
        'planter',
        'flowerbed',
        'hedge',
        'reception_desk',
        'sun_lounger',
        'umbrella',
        'hvac_unit',
        'water_tank',
        'parapet',
        'parapet_cap',
        'balustrade',
        'railing',
        'pool',
        'pond',
        'fountain',
        'fire_pit',
        'sandpit',
        'bench',
        'dumpster',
    }
)
# …and what must never block, whatever a spec says: the floor itself, and the
# vocabulary object_specs already knows is not a solid.
NEVER_BLOCK = frozenset(
    set(DECK_KINDS)
    | set(DOOR_KINDS)
    | {
        'window',
        'window_bay',
        'window_ribbon',
        'skylight',
        'opening',
        'zone',
        'asset',
        'string_course',
        'canopy',
        'balcony',
        'awning',
        'porch',
        'beam',
        'road',
        'path',
    }
)

# A parasol is a 3 m canopy on a 60 mm pole and a palm is a crown on a trunk:
# their plan rect is what they shade, not what they stand on, and rasterising
# it walls a sun terrace off from its own loungers. Only the stem blocks.
POLE_KINDS = frozenset(
    {'umbrella', 'parasol', 'palm', 'tree', 'shrub', 'lamp_post', 'street_lamp', 'flagpole', 'bollard', 'sign'}
)
POLE_M = 0.3  # m of stem a pole-like record really occupies

# Roof plant does not make a deck a place people go — circulation_rules owns
# that vocabulary; it is repeated here only as a fallback.
ROOF_PLANT = frozenset({'hvac_unit', 'water_tank', 'antenna', 'solar_panel', 'chimney'})

SIDE_SHORT = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west'}


def _mod(name):
    return A.EXT_MODULES.get(name)


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or str(o.get("kind") or "").replace("_", " ")}'


def _cap(out: list) -> list:
    if len(out) <= MAX_FINDINGS:
        return out
    rest = len(out) - MAX_FINDINGS
    return out[:MAX_FINDINGS] + [
        {
            'sev': 'info',
            'code': 'walk_more',
            'text': f'... and {rest} more storey{"s" if rest > 1 else ""} with the same walking problem',
        }
    ]


def block_kinds() -> frozenset:
    """BLOCK_KINDS plus every kind object_specs says stands on a floor or a
    deck. Resolved lazily: extensions load alphabetically and a drawing may run
    with object_specs absent altogether."""
    out = set(BLOCK_KINDS)
    O = _mod('object_specs')
    try:
        specs = O.load_specs() if O is not None else {}
        for spec in specs.values():
            if ((spec.get('space') or {}).get('host')) not in ('floor', 'deck'):
                continue
            for k in spec.get('kinds') or []:
                out.add(str(k))
        out -= set(getattr(O, 'SOLID_SKIP', ()) or ())
    except Exception as _exc:  # noqa: BLE001 — a check never raises
        _zyg_log.debug('object spec kinds unavailable: %s', _exc)
    return frozenset(out - NEVER_BLOCK)


# ── the grid ─────────────────────────────────────────────────────────────────
class _Grid:
    """A 0.25 m occupancy raster of one storey. `free` is floor a foot can be
    put on, `wide` is floor a body fits through, `owner` names the record that
    blocked a cell (the first one that did — that is the one to move)."""

    __slots__ = ('x0', 'z0', 'nx', 'nz', 'free', 'wide', 'squeeze', 'owner')

    def __init__(self, xmin, zmin, xmax, zmax):
        self.x0, self.z0 = float(xmin), float(zmin)
        self.nx = max(1, int(math.ceil((xmax - xmin) / CELL)))
        self.nz = max(1, int(math.ceil((zmax - zmin) / CELL)))
        self.free = bytearray(self.nx * self.nz)
        self.wide = bytearray(self.nx * self.nz)
        self.squeeze = bytearray(self.nx * self.nz)
        self.owner: dict = {}

    def cells(self) -> int:
        return self.nx * self.nz

    def span(self, rect, touch: bool = False) -> tuple:
        """(ix0, ix1, iz0, iz1) half-open, clipped to the grid; empty when the
        rect misses it.

        A SOLID owns a cell when the cell's CENTRE is inside it: rounding a
        wall outward grows it by up to half a cell each side, which turns an
        honest 1.2 m corridor into a 0.7 m one and invents a width finding.

        FLOOR is the other way round (`touch=True`): a slab owns every cell it
        reaches at all. `add_stair` cuts its plate into pieces that stop 0.05 m
        short of each other, and a 0.1 m joint between two slabs is not a hole
        anyone can fall through — with centre containment it read as a bare
        row right across the storey and cut the building in two."""
        if touch:
            ix0 = max(0, int(math.floor((rect[0] - self.x0) / CELL)))
            iz0 = max(0, int(math.floor((rect[1] - self.z0) / CELL)))
            ix1 = min(self.nx, int(math.ceil((rect[2] - self.x0) / CELL)))
            iz1 = min(self.nz, int(math.ceil((rect[3] - self.z0) / CELL)))
            return ix0, max(ix0, ix1), iz0, max(iz0, iz1)
        ix0 = max(0, int(math.ceil((rect[0] - self.x0) / CELL - 0.5)))
        iz0 = max(0, int(math.ceil((rect[1] - self.z0) / CELL - 0.5)))
        ix1 = min(self.nx, int(math.floor((rect[2] - self.x0) / CELL - 0.5)) + 1)
        iz1 = min(self.nz, int(math.floor((rect[3] - self.z0) / CELL - 0.5)) + 1)
        return ix0, max(ix0, ix1), iz0, max(iz0, iz1)

    def span_solid(self, rect) -> tuple:
        """span() for a solid, but never empty: a 0.1 m partition is thinner
        than a cell and falls between two centres about half the time, and a
        wall you can walk straight through is a worse error than a wall half a
        cell too thick. When an axis comes back empty it keeps ONE line of
        cells — the first the rect touches — so the wall is 0.25 m, not 0."""
        ix0, ix1, iz0, iz1 = self.span(rect)
        tx0, tx1, tz0, tz1 = self.span(rect, touch=True)
        if ix1 <= ix0:
            ix0, ix1 = tx0, min(tx1, tx0 + 1)
        if iz1 <= iz0:
            iz0, iz1 = tz0, min(tz1, tz0 + 1)
        return ix0, max(ix0, ix1), iz0, max(iz0, iz1)

    def paint(self, rect, val: int, touch: bool = False):
        ix0, ix1, iz0, iz1 = self.span(rect, touch)
        if ix1 <= ix0:
            return
        row = bytes([val]) * (ix1 - ix0)
        for iz in range(iz0, iz1):
            b = iz * self.nx
            self.free[b + ix0 : b + ix1] = row

    def block(self, rect, rid: str):
        ix0, ix1, iz0, iz1 = self.span_solid(rect)
        if ix1 <= ix0:
            return
        blank = bytes(ix1 - ix0)
        own = self.owner
        for iz in range(iz0, iz1):
            b = iz * self.nx
            self.free[b + ix0 : b + ix1] = blank
            for ix in range(ix0, ix1):
                own.setdefault(b + ix, rid)

    def block_obb(self, cx, cz, w, dd, ry, rid: str):
        """Block the cells an ORIENTED rectangle really covers.

        2026-09-16: `block` takes a record's AXIS-ALIGNED bbox, which is the
        truth only for a wall square to the grid. A surveyed floor plan is full
        of walls that are not: on the replayed Swiss tower a 4.98 x 0.18 m
        partition turned 17.5 degrees blocked its 4.81 x 1.66 m bbox — 8.0 m2
        for a wall of 0.90 m2, fifty times its own area — and eleven such
        partitions rastered one storey into a solid mass. Thirteen of the
        twenty room doors then read as unreachable, and the finding blamed the
        lift shaft, which was standing innocently three metres away. A cell
        belongs to the wall when its centre is inside the TURNED rectangle. The
        leaf is then walked over on half-cell steps as well, because a 0.09 m
        partition is thinner than a cell and would otherwise be a dotted line
        the flood fill leaks straight through — the same reason `span_solid`
        exists for the axis-aligned path."""
        c, s = math.cos(ry or 0.0), math.sin(ry or 0.0)
        hw, hd = abs(w) / 2.0, abs(dd) / 2.0
        ex, ez = hw * abs(c) + hd * abs(s), hw * abs(s) + hd * abs(c)
        own, free, nx = self.owner, self.free, self.nx
        ix0, ix1, iz0, iz1 = self.span((cx - ex, cz - ez, cx + ex, cz + ez), touch=True)
        for iz in range(iz0, iz1):
            b = iz * nx
            wz = self.z0 + (iz + 0.5) * CELL
            for ix in range(ix0, ix1):
                wx = self.x0 + (ix + 0.5) * CELL
                dx, dz = wx - cx, wz - cz
                if abs(dx * c - dz * s) <= hw and abs(dx * s + dz * c) <= hd:
                    free[b + ix] = 0
                    own.setdefault(b + ix, rid)
        step = CELL / 2.0
        nu = max(2, int(math.ceil(2 * hw / step)) + 1)
        nv = max(2, int(math.ceil(2 * hd / step)) + 1)
        for iu in range(nu):
            lx = -hw + (2 * hw) * iu / (nu - 1)
            for iv in range(nv):
                lz = -hd + (2 * hd) * iv / (nv - 1)
                i = self.at(cx + lx * c + lz * s, cz - lx * s + lz * c)
                if i is not None:
                    free[i] = 0
                    own.setdefault(i, rid)

    def unblock(self, rect, only: str = ''):
        """Free every cell of the rect — or, with `only`, just the cells that
        this one record blocked. A door opens whatever is in its wall; a stair's
        approach opens only the stair's own footprint, so a shaft wall standing
        in that approach still stops the walk (which is the whole point)."""
        ix0, ix1, iz0, iz1 = self.span_solid(rect)
        if ix1 <= ix0:
            return
        row = b'\x01' * (ix1 - ix0)
        own = self.owner
        for iz in range(iz0, iz1):
            b = iz * self.nx
            if not only:
                self.free[b + ix0 : b + ix1] = row
                for ix in range(ix0, ix1):
                    own.pop(b + ix, None)
                continue
            for ix in range(ix0, ix1):
                if own.get(b + ix) == only:
                    own.pop(b + ix, None)
                    self.free[b + ix] = 1

    def widen(self, rect):
        """Mark a rect wide wherever it is free — a door leaf is a door, not a
        pinch point, so erosion does not close it."""
        ix0, ix1, iz0, iz1 = self.span(rect)
        for iz in range(iz0, iz1):
            b = iz * self.nx
            for ix in range(ix0, ix1):
                if self.free[b + ix]:
                    self.wide[b + ix] = 1
                    self.squeeze[b + ix] = 1

    def centre(self, i: int) -> tuple:
        return (self.x0 + (i % self.nx + 0.5) * CELL, self.z0 + (i // self.nx + 0.5) * CELL)

    def at(self, x: float, z: float):
        ix = int(math.floor((x - self.x0) / CELL))
        iz = int(math.floor((z - self.z0) / CELL))
        if 0 <= ix < self.nx and 0 <= iz < self.nz:
            return iz * self.nx + ix
        return None

    def indices(self, rect) -> list:
        ix0, ix1, iz0, iz1 = self.span(rect)
        out = []
        for iz in range(iz0, iz1):
            b = iz * self.nx
            out.extend(range(b + ix0, b + ix1))
        if not out:  # a rect narrower than a cell still has a place
            i = self.at((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
            if i is not None:
                out = [i]
        return out

    def erode(self, r: int = ERODE):
        """The two width grids. `free` eroded by a 2r+1 window that tolerates
        SLACK blocked cells is 'wide' (1.0 m, comfortable); the same window
        tolerating SQUEEZE_SLACK is 'squeeze' (0.75 m, sideways).

        Plain erosion on a 0.25 m grid can only threshold at 0.75, 1.25, 1.75 m;
        one cell of slack in a five-cell window puts the threshold where a
        person is — a run of 4 free cells (1.0 m) keeps its middle, a run of 3
        (0.9 m) keeps nothing. Two tiers because the difference between "you
        have to turn sideways" and "you cannot get there" is the difference
        between a warning and an error."""
        self.wide = self._eroded(r, 2 * r + 1 - max(0, int(SLACK)))
        self.squeeze = self._eroded(r, 2 * r + 1 - max(0, int(SQUEEZE_SLACK)))

    def _eroded(self, r: int, need: int) -> bytearray:
        """`free` eroded by a 2r+1 window that keeps a cell when at least
        `need` of the window's cells are free — separable, two linear passes
        over prefix sums, so it costs O(cells) whatever r is."""
        nx, nz, free = self.nx, self.nz, self.free
        tmp = bytearray(nx * nz)
        for iz in range(nz):
            b = iz * nx
            pre, acc = [0] * (nx + 1), 0
            for i in range(nx):
                acc += free[b + i]
                pre[i + 1] = acc
            for i in range(r, nx - r):
                if free[b + i] and pre[i + r + 1] - pre[i - r] >= need:
                    tmp[b + i] = 1
        out = bytearray(nx * nz)
        for ix in range(nx):
            col = tmp[ix::nx]
            pre, acc = [0] * (nz + 1), 0
            for i in range(nz):
                acc += col[i]
                pre[i + 1] = acc
            for i in range(r, nz - r):
                if col[i] and pre[i + r + 1] - pre[i - r] >= need:
                    out[i * nx + ix] = 1
        return out


def _fill(grid: _Grid, starts, grid_kind: str = 'wide') -> bytearray:
    """Breadth-first flood fill from every start index over one of the three
    grids: 'wide' (1.0 m), 'squeeze' (0.75 m) or 'free' (any floor at all)."""
    passable = getattr(grid, grid_kind)
    nx, nz = grid.nx, grid.nz
    seen = bytearray(nx * nz)
    q = deque()
    for i in starts:
        if passable[i] and not seen[i]:
            seen[i] = 1
            q.append(i)
    while q:
        i = q.popleft()
        ix = i % nx
        if ix > 0 and passable[i - 1] and not seen[i - 1]:
            seen[i - 1] = 1
            q.append(i - 1)
        if ix + 1 < nx and passable[i + 1] and not seen[i + 1]:
            seen[i + 1] = 1
            q.append(i + 1)
        if i >= nx and passable[i - nx] and not seen[i - nx]:
            seen[i - nx] = 1
            q.append(i - nx)
        j = i + nx
        if j < nx * nz and passable[j] and not seen[j]:
            seen[j] = 1
            q.append(j)
    return seen
