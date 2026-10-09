# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_rules — the TYPICAL floor, read back after it was generated (2026-09-16).

Why this family exists: a 20-storey tower's interior is one `layout_floor` call
and one `repeat_floor` call. Storey 1 is drawn once and stamped onto eighteen
more storeys, so a wrong storey 1 becomes eighteen wrong storeys — and until
now nothing read the result back. layout_floor's own refusals fire BEFORE the
floor exists (corridor width, unit depth); they cannot see the stair and the
lift shafts that are already standing in the plate, and repeat_floor copies
whatever it is given.

This module owns no kinds and no tools. It measures eight relations on every
storey 1..N-1 of every building envelope:

  floor_corridor_core     the corridor actually REACHES the lift landing and the
                          stair foot — a core in a sealed pocket is not a core.
  floor_unit_door         every unit has a door on its own boundary.
  floor_unit_daylight     every habitable unit touches an external wall.
  floor_unit_narrow       nothing under 3.0 m across is a room.
  floor_corridor_width    the corridor stayed over 1.2 m clear.
  floor_partition_core    no partition is drawn through a stair or a shaft.
  floor_empty             a typical storey that is a bare slab.
  floor_repeat_mismatch   one storey laid out unlike its eighteen neighbours.

THE CORRIDOR. When the plan carries a corridor/circulation `zone` record (that
is what floor_plans.tile_units writes) those rects ARE the corridor. When it
does not (floor_layouts.layout_floor writes only the two corridor walls) the
corridor is derived: the storey is cut into a sweep grid on the edges of every
unit, core, wall and partition rect; a cell is free when its centre is in no
unit and no core, and in no wall unless a door opening carves it; the free
cells are grouped into connected components, and the component that the most
unit doors open onto is the corridor. That derivation is what makes
"a partition written across the corridor" measurable at all: it splits the
component, and the half with the doors no longer reaches the core.

Findings fold by storey — nineteen identical copies of one mistake are one
line, 'storeys 1..19: …', because the model that reads them has 28 calls.
"""

from __future__ import annotations

import math
import re

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
EXAMPLES: list = []
# A check-only family: every word it has to say is said in a finding, where the
# model reads it with the record id and the number beside it.
PROMPT = ''

TOUCH_TOL = 0.3
REACH_MIN = 0.05  # m — "the corridor reaches it"
CORRIDOR_MIN = 1.2  # spec("corridor"): two people pass, a wheelchair turns
UNIT_MIN = 3.0  # floor_layouts.UNIT_MIN — under it, a cupboard
CLASH_TOL = 0.05  # plan overlap under this is a rounding artefact
REPEAT_TOL = 0.30  # 30 % off the median partition count
MIN_CORRIDOR_AREA = 1.0  # m2 — under it the free area is a gap, not a corridor
MAX_CELLS = 6000  # sweep-grid ceiling; past it the derivation is skipped
MAX_FINDINGS = 8

STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')
SHAFT_KIND = 'elevator_shaft'
CORE_KINDS = STAIR_KINDS + (SHAFT_KIND,)
WALL_KINDS = ('wall', 'curtain_wall', 'wall_arc', 'partition')
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'door_french')
SLAB_KINDS = ('slab', 'slab_poly')

CORRIDOR_USES = ('corridor', 'circulation')
# zone uses that are not a unit of accommodation
NOT_UNIT_USES = frozenset(
    {
        'corridor',
        'circulation',
        'hall',
        'lobby',
        'foyer',
        'stair',
        'stairs',
        'stairwell',
        'shaft',
        'duct',
        'riser',
        'plant',
        'void',
        'core',
        'lift',
        'elevator',
        'balcony',
        'terrace',
        'garden',
        'parking',
        'roof',
        'other',
    }
)
# rooms that legitimately have no window — no daylight finding for them
NO_WINDOW_USES = frozenset(
    {
        'bathroom',
        'toilet',
        'wc',
        'shower',
        'kitchen',
        'storage',
        'storeroom',
        'store',
        'utility',
        'laundry',
        'closet',
        'pantry',
        'wardrobe',
        'technical',
        'cloakroom',
        'ensuite',
        'en_suite',
        'dressing',
        'server',
        'switchroom',
    }
)
# a unit somebody sleeps or lives in: no window is an error, not a warning
DAYLIGHT_ERROR_USES = frozenset(
    {
        'living',
        'living_dining',
        'bedroom',
        'apartment',
        'residential',
        'hotel',
        'dwelling',
        'studio',
        'flat',
    }
)
# floor_layouts / floor_plans write the provenance of every laid-out storey to
# d.ext['floor_layouts'][<storey>]['use']. These two values mean the zones on that
# storey came off a SURVEYED PLAN, so each one is a ROOM inside a dwelling — a
# kitchen, a bathroom, a bedroom off an internal hall — and not a unit of
# accommodation. layout_floor's own zones are the unit: one rectangle per flat,
# named "Apartment 1.03", with its front door on the corridor.
PLAN_LAYOUT_USES = frozenset({'plan', 'plan_tiles'})


# ── sibling families, fetched lazily (extensions load alphabetically) ────────
def _env():
    return A.EXT_MODULES.get('envelope_rules')


def _stairs():
    return A.EXT_MODULES.get('stairs_vertical')


def _loaded(name: str) -> bool:
    return A.EXT_MODULES.get(name) is not None


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _use(o) -> str:
    return str((o.get('p') or {}).get('use') or '').strip().lower()


def _zone_name(o) -> str:
    return str((o.get('p') or {}).get('name') or o.get('name') or o.get('id') or '')


def _is_corridor_zone(o) -> bool:
    txt = f'{_use(o)} {_zone_name(o)}'.lower()
    return any(w in txt for w in CORRIDOR_USES)


def zone_rect(o):
    """The plan rect of a `zone` record, read off its own p.pts. envelope_rules
    ._plan_size has no polygon branch — it answers 0.5 x 0.5 m for every zone —
    so a zone is the one record whose footprint must be read here."""
    pts = (o.get('p') or {}).get('pts')
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    if isinstance(pts, (list, tuple)) and len(pts) >= 3:
        xs = [x + _num(p[0], 0.0) for p in pts if len(p) >= 2]
        zs = [z + _num(p[1], 0.0) for p in pts if len(p) >= 2]
        if xs and zs:
            return (min(xs), min(zs), max(xs), max(zs))
    E = _env()
    return E.bbox_of(o) if E is not None else (x - 0.25, z - 0.25, x + 0.25, z + 0.25)


def rect_of(o):
    if str(o.get('kind') or '') == 'zone':
        return zone_rect(o)
    E = _env()
    return E.bbox_of(o) if E is not None else (o['x'] - 0.25, o['z'] - 0.25, o['x'] + 0.25, o['z'] + 0.25)


def _overlap(a, b) -> tuple:
    return (min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1]))


def _rect_gap(a, b) -> float:
    """Metres between two plan rects; 0.0 when they touch or overlap."""
    ox, oz = _overlap(a, b)
    return math.hypot(max(-ox, 0.0), max(-oz, 0.0))


def _edge_dist(px: float, pz: float, r) -> float:
    """Distance from a plan point to the BOUNDARY of a rect (0 on the edge)."""
    if r[0] <= px <= r[2] and r[1] <= pz <= r[3]:
        return min(px - r[0], r[2] - px, pz - r[1], r[3] - pz)
    dx = max(r[0] - px, 0.0, px - r[2])
    dz = max(r[1] - pz, 0.0, pz - r[3])
    return math.hypot(dx, dz)


def _in_rect(px: float, pz: float, r) -> bool:
    return r[0] <= px <= r[2] and r[1] <= pz <= r[3]


def _ranges(nums) -> str:
    """[2, 3, 4, 19] -> '2..4, 19' — the storeys, said the way a person says them."""
    ns = sorted({int(n) for n in nums})
    out, i = [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[i]) if i == j else f'{ns[i]}..{ns[j]}')
        i = j + 1
    return ', '.join(out)


_LABEL_RE = re.compile(r'\b(\d+)\.(\d+)\b')


def _generic(name: str) -> str:
    """'Apartment 7.02' -> 'Apartment n.02': the same unit of eighteen storeys,
    so eighteen renumbered copies of one mistake fold into one line.

    Only ever applied to a zone NAME. Run over a whole sentence it eats the
    measurements too ('the 1.2 m of floor' -> 'the n.2 m of floor')."""
    return _LABEL_RE.sub(lambda m: f'n.{m.group(2)}', str(name or ''))


# ── the storey model ────────────────────────────────────────────────────────
def _storey_of(o, base: float, H: float) -> int:
    y = _num(o.get('y'), 0.0) - _num((o.get('p') or {}).get('base'), 0.0)
    return int(round((y - base) / H)) if H else 0


def _core_span(o) -> tuple:
    y = _num(o.get('y'), 0.0)
    if str(o.get('kind') or '') == SHAFT_KIND:
        return y, y + _p(o, 'h', 0.0)
    steps = _p(o, 'steps', 0.0) or (_p(o, 'steps_a', 0.0) + _p(o, 'steps_b', 0.0))
    return y, y + steps * _p(o, 'rise', 0.0)


def landing_rect(o, reach: float):
    """The floor a lift's doors open onto: a `reach` m strip off the shaft's own
    p.door_side. A lift with no landing is a lift nobody can walk into."""
    E = _env()
    bb = E.bbox_of(o) if E is not None else rect_of(o)
    side = str((o.get('p') or {}).get('door_side') or 'south').strip().lower()
    if side == 'north':
        return (bb[0], bb[1] - reach, bb[2], bb[1])
    if side == 'south':
        return (bb[0], bb[3], bb[2], bb[3] + reach)
    if side == 'west':
        return (bb[0] - reach, bb[1], bb[0], bb[3])
    return (bb[2], bb[1], bb[2] + reach, bb[3])


def approach_rects(o) -> list:
    S = _stairs()
    fn = getattr(S, 'approach_bboxes', None) if S is not None else None
    if not callable(fn):
        return []
    try:
        return list(fn(o) or [])
    except Exception:  # noqa: BLE001 — never block a check
        return []


# ── the derived corridor: a sweep grid of the free floor ────────────────────
def _axis(lo: float, hi: float, rects, idx0: int, idx1: int) -> list:
    vals = {round(lo, 3), round(hi, 3)}
    for r in rects:
        for v in (r[idx0], r[idx1]):
            if lo < v < hi:
                vals.add(round(v, 3))
    return sorted(vals)


def free_components(env: dict, solids: list, walls: list, openings: list):
    """Connected components of the free floor of one storey.

    Returns (cells, comp) where cells is [(x0, z0, x1, z1), ...] and comp is the
    component index per cell (-1 = blocked), or None when the grid would be too
    big to be worth it. A cell is blocked when its centre stands in a unit or a
    core (`solids`), or in a wall/partition (`walls`) that no door opening
    (`openings`) carves through."""
    # the door rects are cut into the grid too, or a 0.9 m opening would carve the
    # whole 20 m wall cell it happens to sit in
    rects = list(solids) + list(walls) + list(openings)
    xs = _axis(env['xmin'], env['xmax'], rects, 0, 2)
    zs = _axis(env['zmin'], env['zmax'], rects, 1, 3)
    nx, nz = len(xs) - 1, len(zs) - 1
    if nx < 1 or nz < 1 or nx * nz > MAX_CELLS:
        return None
    cells, free = [], []
    for j in range(nz):
        for i in range(nx):
            x0, x1, z0, z1 = xs[i], xs[i + 1], zs[j], zs[j + 1]
            cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
            cells.append((x0, z0, x1, z1))
            if any(_in_rect(cx, cz, r) for r in solids):
                free.append(False)
                continue
            if any(_in_rect(cx, cz, r) for r in walls) and not any(_in_rect(cx, cz, r) for r in openings):
                free.append(False)
                continue
            free.append(True)
    comp = [-1] * len(cells)
    n = 0
    for start in range(len(cells)):
        if not free[start] or comp[start] >= 0:
            continue
        stack = [start]
        comp[start] = n
        while stack:
            k = stack.pop()
            i, j = k % nx, k // nx
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < nz:
                    m = b * nx + a
                    if free[m] and comp[m] < 0:
                        comp[m] = n
                        stack.append(m)
        n += 1
    return cells, comp, nx, nz


def _component_width(cells, comp, nx, nz, which: int, skip) -> float:
    """The narrowest passage of one component: per cell, the contiguous free run
    through its centre along X and along Z — the smaller of the two — and the
    minimum of that over the component. Cells inside a door opening are skipped:
    a 0.9 m doorway is a doorway, not a pinched corridor."""
    best = None
    for k in range(len(cells)):
        if comp[k] != which:
            continue
        c = cells[k]
        cx, cz = (c[0] + c[2]) / 2.0, (c[1] + c[3]) / 2.0
        if any(_in_rect(cx, cz, r) for r in skip):
            continue
        i, j = k % nx, k // nx
        a = i
        while a > 0 and comp[j * nx + a - 1] == which:
            a -= 1
        b = i
        while b < nx - 1 and comp[j * nx + b + 1] == which:
            b += 1
        wx = cells[j * nx + b][2] - cells[j * nx + a][0]
        a = j
        while a > 0 and comp[(a - 1) * nx + i] == which:
            a -= 1
        b = j
        while b < nz - 1 and comp[(b + 1) * nx + i] == which:
            b += 1
        wz = cells[b * nx + i][3] - cells[a * nx + i][1]
        w = min(wx, wz)
        best = w if best is None else min(best, w)
    return best if best is not None else 0.0


# ── the check ───────────────────────────────────────────────────────────────
def _emit(raw, sev, code, st, key, msg):
    """`key` says which MISTAKE this is; the storey and the ids are not part of
    it. repeat_floor renumbers every record it copies, so the same fault on
    nineteen storeys carries nineteen different ids — fold on the key and keep
    the first storey's sentence, ids and all, as the example."""
    raw.append({'sev': sev, 'code': code, 'st': int(st), 'key': key, 'msg': msg})


def _fold(raw: list) -> list:
    """One line per mistake, not one per storey."""
    order, groups = [], {}
    for f in raw:
        key = (f['code'], f['sev'], f['key'])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    out = []
    for key in order:
        fs = groups[key]
        sts = sorted({f['st'] for f in fs})
        where = f'storey {sts[0]}' if len(sts) == 1 else f'storeys {_ranges(sts)}'
        out.append({'sev': key[1], 'code': key[0], 'text': f'{where}: {fs[0]["msg"]}'})
    if len(out) > MAX_FINDINGS:
        rest = len(out) - MAX_FINDINGS
        out = out[:MAX_FINDINGS] + [
            {'sev': 'info', 'code': 'floor_more', 'text': f'... and {rest} more floor finding{"s" if rest > 1 else ""}'}
        ]
    return out


def plan_storeys(d: Drawing) -> set:
    """The storeys whose zones came off a surveyed plan, not out of layout_floor.

    2026-09-16: floor_unit_door and floor_unit_daylight are layout_floor's rules —
    they judge the UNIT OF ACCOMMODATION, which layout_floor draws as one zone per
    flat with its front door on the corridor. place_plan and tile_units draw the
    plan's own ROOM schedule instead: on one replayed Swiss floor that is 21 zones
    per storey named Kitchen, Bathroom, Bedroom, Living Dining, Corridor, Loggia.
    Judged as units they gave five hard errors that are all category mistakes — a
    kitchen open to the living room "has no door", a bedroom off an internal hall
    "has no external wall" (its zone box stops 0.75 m short of the facade, past the
    0.6 m envelope_rules.touches_facade allows) — on a floor that is a real
    building, surveyed as built. The finding is still WORTH SAYING, because the
    replay can genuinely lose a door; it is said as a warning, and it names the
    room as a room."""
    store = d.ext.get('floor_layouts')
    if not isinstance(store, dict):
        return set()
    out = set()
    for k, rec in store.items():
        try:
            if isinstance(rec, dict) and str(rec.get('use') or '') in PLAN_LAYOUT_USES:
                out.add(int(k))
        except Exception as _exc:  # noqa: BLE001 — a check never raises
            _zyg_log.debug('non-integer floor_layouts key %r ignored: %s', k, _exc)
            continue
    return out


def _storey_records(d: Drawing, env: dict, base: float, H: float) -> dict:
    """{storey: {...}} for one envelope. Records are placed by plan position, so
    a partition drawn into the tower answers for the tower whatever group string
    the tool happened to give it."""
    E = _env()
    by: dict = {}

    def slot(s):
        return by.setdefault(s, {'zones': [], 'walls': [], 'doors': [], 'slabs': []})

    for o in d.objs:
        if o.get('hidden'):
            continue
        k = str(o.get('kind') or '')
        if k not in ('zone',) + WALL_KINDS + DOOR_KINDS + SLAB_KINDS:
            continue
        if not E.inside(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), 0.35):
            continue
        s = _storey_of(o, base, H)
        if k == 'zone':
            slot(s)['zones'].append(o)
        elif k in DOOR_KINDS:
            slot(s)['doors'].append(o)
        elif k in SLAB_KINDS:
            slot(s)['slabs'].append(o)
        else:
            slot(s)['walls'].append(o)
    return by


def _cores_on(d: Drawing, env: dict, base: float, H: float) -> dict:
    """{storey: [core records]} — a shaft is one record for the whole stack, a
    stair one per storey, so both are placed by the height span they occupy."""
    E = _env()
    out: dict = {}
    for o in d.objs:
        if o.get('hidden') or str(o.get('kind') or '') not in CORE_KINDS:
            continue
        if not E.inside(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)):
            continue
        y0, y1 = _core_span(o)
        lo = int(math.floor((y0 - base) / H + 0.2)) if H else 0
        hi = int(math.ceil((y1 - base) / H - 0.2)) if H else 0
        for s in range(min(lo, hi), max(lo, hi) + 1):
            out.setdefault(s, []).append(o)
    return out


def _check_floors(d: Drawing) -> list:
    E = _env()
    if E is None:
        return []
    H = getattr(d, 'storey_h', 0.0) or 2.7
    S = _stairs()
    reach = _num(getattr(S, 'APPROACH_M', 1.2), 1.2) if S is not None else 1.2
    # walk_rules measures reachability across the whole storey; when it is loaded
    # the corridor-to-core relation is its finding, not ours — never two lines for
    # one mistake. clash_rules owns core x partition in general, likewise.
    skip_corridor_core = _loaded('walk_rules')
    skip_partition_core = _loaded('clash_rules')
    from_plan = plan_storeys(d)
    # building_program's 'typical_floors' item already errors when a storey that
    # was asked for has no plan; only speak when that family is absent.
    skip_empty = _loaded('building_program')

    raw = []
    for g, env in E.envelopes(d).items():
        storeys = int(env.get('storeys') or 0)
        if storeys < 2:
            continue
        base = _num(env.get('y0'), 0.0)
        by = _storey_records(d, env, base, H)
        cores = _cores_on(d, env, base, H)
        part_count = {}

        for s in range(1, storeys):
            is_plan = s in from_plan
            rec = by.get(s) or {'zones': [], 'walls': [], 'doors': [], 'slabs': []}
            walls = rec['walls']
            part_count[s] = sum(1 for w in walls if w.get('kind') == 'partition')
            zones = rec['zones']
            corridor_zones = [z for z in zones if _is_corridor_zone(z)]
            units = [z for z in zones if z not in corridor_zones and _use(z) not in NOT_UNIT_USES]
            core_recs = cores.get(s) or []

            # (7) a typical storey that is a bare slab. draw_box gives every
            # storey the envelope's own four walls, so 'no walls' would never be
            # true — only a wall standing INSIDE the plate is a fitout.
            inside_walls = [w for w in walls if not E.touches_facade(env, _num(w.get('x'), 0.0), _num(w.get('z'), 0.0))]
            if not zones and not inside_walls:
                if rec['slabs'] and not skip_empty:
                    _emit(
                        raw,
                        'warn',
                        'floor_empty',
                        s,
                        ('empty', g),
                        f'a bare slab in "{g}" — no rooms, no partitions; '
                        f'layout_floor(cell_from, cell_to, use, storey={s}) cuts the whole floor '
                        f'and repeat_floor carries it up',
                    )
                continue

            # (6) a partition drawn through a stair or a lift shaft
            if not skip_partition_core:
                for w in walls:
                    if w.get('kind') != 'partition':
                        continue
                    wb = rect_of(w)
                    for c in core_recs:
                        cb = E.bbox_of(c)
                        ox, oz = _overlap(wb, cb)
                        if ox > CLASH_TOL and oz > CLASH_TOL:
                            _emit(
                                raw,
                                'error',
                                'floor_partition_core',
                                s,
                                ('part_core', g, str(c.get('kind') or ''), _generic(w.get('name'))),
                                f'partition {w["id"]} {w.get("name") or ""}'.rstrip() + f' is drawn through {c["id"]} '
                                f'{str(c.get("kind") or "").replace("_", " ")} '
                                f'({ox:.2f} x {oz:.2f} m overlap) — move the partition, '
                                f'or pass core_from/core_to to layout_floor so the core block '
                                f'is left empty',
                            )
                            break

            if not units:
                continue

            unit_rects = [(u, zone_rect(u)) for u in units]
            core_rects = [E.bbox_of(c) for c in core_recs]
            door_rects = [(o, rect_of(o)) for o in rec['doors']]

            # (2) every unit has a door on its own boundary, and (3)(4) its shape
            unit_doors = []
            for u, ur in unit_rects:
                mine = [
                    o
                    for o, dr in door_rects
                    if _edge_dist(_num(o.get('x'), 0.0), _num(o.get('z'), 0.0), ur) <= TOUCH_TOL
                ]
                unit_doors.extend(mine)
                nm = _zone_name(u)
                gn = _generic(nm)
                if not mine:
                    _emit(
                        raw,
                        'error' if not is_plan else 'warn',
                        'floor_unit_door',
                        s,
                        ('door', g, gn),
                        f'unit "{nm}" ({u["id"]}) has no door — nothing opens onto it; '
                        f'layout_floor draws one door per unit into the corridor '
                        f'(doors=true), or add a door record on its boundary'
                        if not is_plan
                        else f'room "{nm}" ({u["id"]}) has no door on its boundary — this storey '
                        f'came off a surveyed plan, so it may be open to the next room; if '
                        f"it should have one, place_plan draws it from the plan's own "
                        f'door schedule (doors=true)',
                    )
                w_m, d_m = ur[2] - ur[0], ur[3] - ur[1]
                if min(w_m, d_m) < UNIT_MIN:
                    _emit(
                        raw,
                        'warn',
                        'floor_unit_narrow',
                        s,
                        ('narrow', g, gn),
                        f'unit "{nm}" ({u["id"]}) is {w_m:.1f} x {d_m:.1f} m — under the '
                        f'{UNIT_MIN:g} m a room needs; widen the plate or pass a bigger unit_w '
                        f'to layout_floor',
                    )
                use = _use(u)
                if use in NO_WINDOW_USES:
                    continue
                mids = [
                    ((ur[0] + ur[2]) / 2.0, ur[1]),
                    ((ur[0] + ur[2]) / 2.0, ur[3]),
                    (ur[0], (ur[1] + ur[3]) / 2.0),
                    (ur[2], (ur[1] + ur[3]) / 2.0),
                ]
                if any(E.touches_facade(env, mx, mz) for mx, mz in mids):
                    continue
                _emit(
                    raw,
                    'error' if (use in DAYLIGHT_ERROR_USES and not is_plan) else 'warn',
                    'floor_unit_daylight',
                    s,
                    ('daylight', g, gn),
                    f'unit "{nm}" ({u["id"]}) has no external wall — no window is possible; '
                    f'move it to the perimeter, or lay the floor out with layout_floor so '
                    f'every unit reaches a facade'
                    if not is_plan
                    else f'room "{nm}" ({u["id"]}) has no external wall — this storey came off a '
                    f'surveyed plan, so it is a room inside a dwelling, not a unit; check the '
                    f'plan is the right way round (place_plan rotate_deg) if it should face out',
                )

            # the corridor, declared or derived
            solids = [r for _, r in unit_rects] + core_rects
            grid = None
            if corridor_zones:
                corr_rects = [zone_rect(z) for z in corridor_zones]
                width = min(min(r[2] - r[0], r[3] - r[1]) for r in corr_rects)
                area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in corr_rects)
                touch = lambda t, _cr=corr_rects: any(_rect_gap(r, t) <= TOUCH_TOL for r in _cr)  # noqa: E731
            else:
                grid = free_components(env, solids, [rect_of(w) for w in walls], [dr for _, dr in door_rects])
                if grid is None:
                    continue
                cells, comp, nx, nz = grid
                door_ids = {o['id'] for o in unit_doors}
                score, area_of = {}, {}
                for k in range(len(cells)):
                    c = comp[k]
                    if c < 0:
                        continue
                    r = cells[k]
                    area_of[c] = area_of.get(c, 0.0) + (r[2] - r[0]) * (r[3] - r[1])
                for o, dr in door_rects:
                    if o['id'] not in door_ids:
                        continue
                    seen = set()
                    for k in range(len(cells)):
                        if comp[k] < 0 or comp[k] in seen:
                            continue
                        ox, oz = _overlap(cells[k], dr)
                        if ox > 1e-9 and oz > 1e-9:
                            seen.add(comp[k])
                    for c in seen:
                        score[c] = score.get(c, 0) + 1
                if not area_of:
                    continue
                which = (
                    max(score, key=lambda c: (score[c], area_of.get(c, 0.0)))
                    if score
                    else max(area_of, key=lambda c: area_of[c])
                )
                area = area_of[which]
                width = _component_width(cells, comp, nx, nz, which, [dr for _, dr in door_rects])
                corr_cells = [cells[k] for k in range(len(cells)) if comp[k] == which]
                # A landing is floor, so when it is reachable it IS part of the
                # corridor's own free component. Ask for overlap, not nearness:
                # at a 0.3 m tolerance a 0.1 m partition sealing the landing off
                # reads as touching, and the whole rule goes quiet.
                touch = lambda t, _cc=corr_cells: any(
                    min(_overlap(r, t)) > REACH_MIN  # noqa: E731
                    for r in _cc
                )

            if area < MIN_CORRIDOR_AREA:
                continue

            # (5) the corridor stayed walkable
            if width < CORRIDOR_MIN - 1e-6:
                _emit(
                    raw,
                    'error',
                    'floor_corridor_width',
                    s,
                    ('corr_w', g),
                    f'the corridor is {width:.2f} m clear at its narrowest — under the '
                    f'{CORRIDOR_MIN:g} m two people need to pass; lay the floor out with '
                    f'layout_floor(corridor_w=1.5) or move what pinches it',
                )

            # (1) the corridor reaches the core
            if not skip_corridor_core:
                lifts = [c for c in core_recs if str(c.get('kind') or '') == SHAFT_KIND]
                stairs = [c for c in core_recs if str(c.get('kind') or '') in STAIR_KINDS]
                if lifts and not any(touch(landing_rect(c, reach)) for c in lifts):
                    ids = ', '.join(c['id'] for c in lifts[:3])
                    _emit(
                        raw,
                        'error',
                        'floor_corridor_core',
                        s,
                        ('lift', g),
                        f'the corridor does not reach the lifts ({ids}) — the landing at the '
                        f'shaft doors is walled off from it; put the corridor along the core '
                        f'(layout_floor core_from/core_to, or tile_units which moves the '
                        f'corridor beside the core) or open a door into it',
                    )
                appr = [r for c in stairs for r in approach_rects(c)]
                if appr and not any(touch(r) for r in appr):
                    ids = ', '.join(c['id'] for c in stairs[:3])
                    _emit(
                        raw,
                        'error',
                        'floor_corridor_core',
                        s,
                        ('stair', g),
                        f'the corridor does not reach the stair ({ids}) — the {reach:g} m of '
                        f'floor at its foot is walled off from it; put the corridor along the '
                        f'core (layout_floor core_from/core_to) or open a door into it',
                    )

        # (8) one storey laid out unlike its neighbours
        mid = [part_count.get(s, 0) for s in range(2, max(2, storeys - 1))]
        if len(mid) >= 3:
            srt = sorted(mid)
            med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2.0
            if med > 0:
                for s in range(1, storeys):
                    n = part_count.get(s, 0)
                    if abs(n - med) / med > REPEAT_TOL:
                        _emit(
                            raw,
                            'warn',
                            'floor_repeat_mismatch',
                            s,
                            ('repeat', g, n),
                            f'{n} partitions against {med:g} on the typical floors of "{g}" — '
                            f'this storey was laid out differently; repeat_floor(from_storey='
                            f'{s}, to_storey={s}, source_storey=2) re-stamps the typical plan',
                        )
    return _fold(raw)


def check_typical_floors(d: Drawing) -> list:
    """Every relation this family owns, in one pass over the storeys."""
    try:
        return _check_floors(d)
    except Exception as e:  # noqa: BLE001 — a check never raises
        return [
            {
                'sev': 'info',
                'code': 'floor_rules_error',
                'text': f'floor_rules could not read the floor plans ({type(e).__name__}: {e}) — '
                f'the typical-floor checks were skipped',
            }
        ]


PART_HEAD_GAP_M = 0.10  # an open strip above a partition wider than this is a defect


def check_partition_head(d: Drawing) -> list:
    """part_head_gap: a partition that stops short of the slab above leaves an
    open strip the eye reads at once (job 5e7eb915e1f9: 2.5 m lobby partitions
    under a 2.7 m storey, the curtain wall visible over them in the 4K lobby
    frame). Fires only where a slab really sits over the partition's midpoint,
    so a low screen on an open roof or a top-storey parapet stays silent."""
    out = []
    try:
        H = float(getattr(d, 'storey_h', 0.0) or 0.0)
        if H <= 0.0:
            return out
        parts = [o for o in d.objs if o.get('kind') == 'partition' and not o.get('hidden')]
        if not parts:
            return out
        slabs = [o for o in d.objs if o.get('kind') in ('slab', 'slab_poly') and not o.get('hidden')]
        if not slabs:
            return out
        by_st: dict = {}
        for o in parts:
            y = _num(o.get('y'), 0.0)
            h = _num((o.get('p') or {}).get('h'), 0.0)
            if h <= 0.0:
                continue
            top = y + h
            # the slab that is the ceiling: its base on the next storey line (within a tolerance),
            # its plan rectangle over the partition's midpoint
            px, pz = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
            ceiling = None
            for s in slabs:
                sy = _num(s.get('y'), 0.0)
                if not (top - PART_HEAD_GAP_M - 1.0 <= sy <= y + H + 0.3) or sy <= y + 0.5:
                    continue
                r = rect_of(s)
                if r is None or not _in_rect(px, pz, r):
                    continue
                ceiling = sy if ceiling is None else min(ceiling, sy)
            if ceiling is None:
                continue
            gap = ceiling - top
            if gap > PART_HEAD_GAP_M:
                st = int(round(y / H))
                by_st.setdefault(st, []).append((o['id'], round(gap, 2), round(ceiling - y, 2)))
        # one line for the whole building (repeat_floor makes nineteen identical storeys)
        if by_st:
            rows = [r for st in sorted(by_st) for r in by_st[st]]
            gap = max(g for _i, g, _h in rows)
            want = max(hh for _i, _g, hh in rows)
            ids = ', '.join(i for i, _g, _h in rows[:6]) + (' …' if len(rows) > 6 else '')
            out.append(
                {
                    'sev': 'warn',
                    'code': 'part_head_gap',
                    'text': (
                        f'{len(rows)} partition(s) on storey{"s" if len(by_st) > 1 else ""} '
                        f'{_ranges(sorted(by_st))} stop up to {gap:g} m below the slab '
                        f'above ({ids}) — an open strip the eye reads at once: draw rooms with '
                        f'add_room(..., wall_h={want:g}) / layout_floor(..., wall_h={want:g}) '
                        f'(the defaults now run to the slab), or delete and redraw the short ones'
                    ),
                }
            )
    except Exception:  # noqa: BLE001
        return out
    return out


DESIGN_CHECKS = [check_typical_floors, check_partition_head]
