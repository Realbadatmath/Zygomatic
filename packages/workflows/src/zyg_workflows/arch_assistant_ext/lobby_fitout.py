# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lobby_fitout — the pieces a lobby is actually made of.

Job 94f5813b built the operator's 20-storey tower and its "double-height
lobby" came out as four plaster partitions with nothing inside: add_room is
the only lobby tool the programme names, and add_room draws walls. So the
programme's lobby item passed on an empty room. furnish_lobby fills that
block — a reception desk at the far end facing the door, a seating group on
the entrance axis, planters in the corners, ceiling lights on a 4 m grid —
and building_program's lobby item now asks for them on a luxury job.

NO NEW KINDS. desk / sofa / armchair / coffee_table / rug come from
furniture_living, the ceiling lights are light_lamps_env's light_point, and a
planter is whichever planting kind the loaded families offer (site_landscape's
shrub today). Kinds are read from arch_assistant.KINDS at CALL time, because
extensions load alphabetically and a sibling may not be in yet at import.

FRAME. Everything is laid out in (u, v): v = metres inward from the ENTRANCE
wall, u = metres across it, +u being the inward direction turned a quarter
turn. Both become world x/z through one unit-vector pair per side, so the
four entrance sides are one layout, not four. Rotations follow
furniture_living: ry = 0 faces north (-Z), +pi/2 west, pi south, -pi/2 east.

2026-09-16 — REAL MODELS ON A LUXURY JOB. The acceptance render showed the
tower lobby as an empty concrete room: the seating was parametric boxes and
the planters were mat_timber ellipsoids. On style="luxury" the seating group
and the planters are now PACK MODELS placed through place_asset (polyhaven
sofa/armchair/potted plant, and a chandelier over the group); the desk, the
coffee table, the rug and the ceiling lights stay parametric. style="standard"
is untouched — it is still the all-parametric layout. When a pack id is
missing or over the triangle budget place_asset refuses and the kind is drawn
parametrically instead; the reply says which ones fell back.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import Drawing, MATERIALS, MAX_OBJECTS, _num, block_bounds, place_height

KINDS: dict = {}  # no new kinds — that is the point
OPENINGS: list = []

SIDES = ('north', 'east', 'south', 'west')
MIN_SIDE = 6.0  # a lobby under 6 x 6 m is a corridor with a desk
CLEAR = 1.2  # circulation kept clear off the entrance wall
EDGE = 0.15  # nothing closer than this to a wall
LIGHT_GRID = 4.0  # metres between ceiling lights
LIGHT_H = 3.0  # ... and how high, when no wall height is known
LIGHT_CAP = 32  # light_lamps_env's lamp budget, both engines
LIGHT_KIND = 'light_point'
DESK_TOP = 'acg_Marble021'  # the luxury finish's own marble
SEAT_MAT = 'mat_timber'
CORE_KINDS = ('desk', 'sofa', 'armchair', 'coffee_table', 'rug')
PLANT_KINDS = ('planter', 'plant_pot', 'pot_plant', 'shrub')

# ── the luxury fit-out: real models, and the finishes around them ───────────
ASSET_SOFA = 'polyhaven_arch|sofa_03_2k'  # 2.73 x 1.12 x 0.93 m, 8.0k tris
ASSET_ARMCHAIR = 'polyhaven_arch|ArmChair_01_2k'  # 0.85 x 1.07 x 0.77 m, 5.6k tris
ASSET_PLANT = 'polyhaven_arch|potted_plant_01_2k'  # 0.59 x 1.35 x 0.63 m, 176k tris
ASSET_CHANDELIER = 'polyhaven_arch|Chandelier_01_2k'
LUX_WALL = 'acg_Plaster001'  # = finish_schedule.SCHEDULE['luxury']['partition'] (lum 212),
#                                  not the grey-reading Plaster005 the lobby used to get
LUX_PANEL = 'pht_black_oak_veneer'  # the reception counter front
LUX_SEAT = 'pht_fabric_leather_01'
LUX_RUG = 'acg_Carpet003'
ASSET_MIN_ACROSS = 8.0  # under this the group has no room and stays parametric
CHANDELIER_CLEAR = 2.2  # metres of head clearance under it
CHANDELIER_DROP = 0.798  # measured: the GLB hangs BELOW its own origin

# ROTATION OF THE PACK SEATS, measured 2026-09-16 and NOT the parametric
# convention. furniture_living's sofa faces NORTH at ry = 0. The polyhaven
# seats do not: built at ry = 0, the tall geometry (the BACK) sits at blender
# +y, and arch_blender_build maps blender (x, y, z) = (studio x, -studio z,
# studio y), so blender +y is studio -Z = north. The back faces north, which
# means the SEAT faces south — half a turn from the parametric convention.
# Every pack seat is therefore turned by the parametric ry PLUS pi, which is
# what makes the two sofas below face each other across the coffee table.
ASSET_RY = math.pi

# inward unit vector F and across unit vector U = F turned a quarter turn,
# per entrance side. north = zmin, south = zmax, west = xmin, east = xmax.
_AXES = {
    'south': ((0.0, -1.0), (1.0, 0.0)),
    'north': ((0.0, 1.0), (-1.0, 0.0)),
    'west': ((1.0, 0.0), (0.0, 1.0)),
    'east': ((-1.0, 0.0), (0.0, -1.0)),
}

PROMPT = (
    'Lobby fit-out: furnish_lobby(cell_from, cell_to, storey, entrance_side, style, name) puts the '
    'pieces INSIDE a lobby that add_room only drew the walls of — a reception desk (two desks end to '
    'end, marble on dark oak) facing the door, a seating group on the entrance axis (2 sofas facing '
    'each other, 2 armchairs, table, rug), corner planters and ceiling lights on a 4 m grid — 1.2 m '
    'of circulation clear off the entrance wall. style="luxury" places the seating, planters and '
    'chandelier as REAL pack models and repaints the partitions light; "standard" is parametric. At '
    'least 6 x 6 m. Call it after add_room(name="Lobby"): an empty room does not answer the '
    "checklist's lobby item. furnish_room does a flat's rooms, this one the entrance hall."
)


def _mat(m, default=SEAT_MAT):
    return m if m in MATERIALS else default


def _ry(dx, dz) -> float:
    """The ry of a piece whose FRONT looks along the plan direction (dx, dz)."""
    return round(math.atan2(-dx, -dz), 6)


def _wrap(ry) -> float:
    """An angle back inside (-pi, pi] — ASSET_RY can push a pi round to 2 pi."""
    return round((float(ry) + math.pi) % (2 * math.pi) - math.pi, 6)


def _p(kind) -> dict:
    return dict(_A.KINDS.get(kind) or {})


def _plant_kind():
    for k in PLANT_KINDS:
        if k in _A.KINDS:
            return k
    return ''


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _walls_here(d: Drawing, xmin, zmin, xmax, zmax, y) -> list:
    """The partitions/zones/walls standing on this block and storey."""
    out = []
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in ('partition', 'zone', 'wall'):
            continue
        if abs(_num(o.get('y'), 0.0) - y) > 0.35:
            continue
        x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
        if not (xmin - 0.2 <= x <= xmax + 0.2 and zmin - 0.2 <= z <= zmax + 0.2):
            continue
        out.append(o)
    return out


def _wall_h(d: Drawing, xmin, zmin, xmax, zmax, y) -> float:
    """The height of the partitions/zones standing on this block and storey,
    when there are any — add_room's default is storey_h - 0.2, not 3 m."""
    return max([_num((o.get('p') or {}).get('h'), 0.0) for o in _walls_here(d, xmin, zmin, xmax, zmax, y)] or [0.0])


def _lights(d: Drawing) -> int:
    return sum(1 for o in d.objs if str(o.get('kind') or '').startswith('light_'))


def _layout(depth, across, plant):
    """(kind, u, v, facing, name) for the whole fit-out, entrance at v = 0."""
    far, mid = depth - 0.85, depth / 2.0
    out = [
        ('desk', -0.7, far, 'out', 'reception desk left'),
        ('desk', 0.7, far, 'out', 'reception desk right'),
        ('sofa', 0.0, mid - 1.2, 'in', 'sofa, entrance side'),
        ('sofa', 0.0, mid + 1.2, 'out', 'sofa, desk side'),
        ('armchair', -1.8, mid, '+u', 'armchair left'),
        ('armchair', 1.8, mid, '-u', 'armchair right'),
        ('coffee_table', 0.0, mid, 'out', 'coffee table'),
        ('rug', 0.0, mid, 'out', 'rug'),
    ]
    if plant:
        cu = max(0.9, across / 2.0 - 0.9)
        for i, (u, v) in enumerate(((-cu, CLEAR + 0.6), (cu, CLEAR + 0.6), (-cu, depth - 0.9), (cu, depth - 0.9))):
            out.append((plant, u, v, 'out', f'planter {i + 1}'))
    return out


def _lux_layout(depth, across):
    """The luxury fit-out: (parametric items, pack-model items, group centre v).

    Item tuples are (kind, u, v, facing, name, material, p-overrides) for the
    parametric half and (pack id, fallback kind, u, v, facing, name) for the
    models. The seating group's offsets are worked out from the free depth so
    that object_specs' coffee-table clearance (1 m all round) stays SILENT:
    the group sits between the 1.2 m entrance circulation and the counter.
    """
    far = depth - 0.85  # the reception counter
    top = far - 0.85  # ... with 0.5 m of circulation in front of it
    gc = (CLEAR + top) / 2.0  # the seating group's centre
    so = _clamp((top - CLEAR) / 2.0 - 0.60, 1.2, 2.0)  # sofa centre off the table
    ao = _clamp(across / 2.0 - 1.6, 1.6, 2.3)  # armchair centre off the table
    pu = max(0.9, across / 2.0 - 0.9)  # the corner planters
    para = [
        ('desk', -0.7, far, 'out', 'reception desk left', DESK_TOP, None),
        ('desk', 0.7, far, 'out', 'reception desk right', DESK_TOP, None),
        ('coffee_table', 0.0, gc, 'out', 'coffee table', SEAT_MAT, {'w': 1.2, 'd': 0.8, 'h': 0.42}),
        (
            'rug',
            0.0,
            gc,
            'out',
            'rug',
            _mat(LUX_RUG),
            {
                't': 0.02,
                'w': round(min(2 * ao + 1.0, across - 1.0), 3),
                'd': round(min(2 * so + 1.4, max(1.0, top - CLEAR)), 3),
            },
        ),
    ]
    # 2026-09-16: the four parametric 'waiting chairs' are gone — they were box
    # armchairs beside real leather ones (4K lobby frame, job 5e7eb915e1f9) and
    # existed only so building_program could count seats; the programme now
    # counts pack-model seats (building_program._seat_kind).
    if 'box' in _A.KINDS:  # the counter front, in dark oak
        para.insert(
            2,
            ('box', 0.0, far - 0.4, 'out', 'reception counter front', _mat(LUX_PANEL), {'w': 2.9, 'd': 0.1, 'h': 1.1}),
        )
    models = [
        (ASSET_SOFA, 'sofa', 0.0, gc - so, 'in', 'sofa, entrance side'),
        (ASSET_SOFA, 'sofa', 0.0, gc + so, 'out', 'sofa, desk side'),
        (ASSET_ARMCHAIR, 'armchair', -ao, gc, '+u', 'armchair left'),
        (ASSET_ARMCHAIR, 'armchair', ao, gc, '-u', 'armchair right'),
    ]
    for i, (u, v) in enumerate(((-pu, CLEAR + 0.6), (pu, CLEAR + 0.6), (-pu, depth - 0.9), (pu, depth - 0.9))):
        models.append((ASSET_PLANT, _plant_kind(), u, v, 'out', f'planter {i + 1}'))
    return para, models, gc


def _grid(depth, across):
    """Ceiling light positions on a LIGHT_GRID grid, centred on the block."""
    nv = max(1, int(math.ceil(depth / LIGHT_GRID)))
    nu = max(1, int(math.ceil(across / LIGHT_GRID)))
    return [(across * ((j + 0.5) / nu - 0.5), depth * (i + 0.5) / nv) for i in range(nv) for j in range(nu)]


def _place_model(d: Drawing, aid, x, z, y, ry, nm, grp, st, scale=1.0):
    """One pack model through place_asset. That tool addresses a CELL and lands
    on its centre, and it has no sub-cell argument — so the record it made is
    moved onto the exact (x, z, y) and into the fit-out group afterwards.
    Returns (record, '') or (None, why it refused)."""
    first = len(d.added)
    txt = _A.call_tool(
        d,
        'place_asset',
        {
            'query_or_id': aid,
            'cell': _A.cell_of(x, z),
            'storey': int(st),
            'rotation_deg': round(math.degrees(ry), 4),
            'scale': round(float(scale), 4),
            'name': nm,
        },
    )
    ids = d.added[first:]
    rec = d.find(ids[-1]) if ids else None
    if rec is None:
        return None, str(txt or 'place_asset refused').replace('refused: ', '')[:110]
    rec['x'], rec['z'], rec['y'] = round(x, 4), round(z, 4), round(y, 4)
    rec['grp'] = grp
    return rec, ''


def t_furnish_lobby(d: Drawing, a, cell_from, cell_to, storey=0, entrance_side='south', style='luxury', name='Lobby'):
    side = str(entrance_side or 'south').strip().lower()
    if side not in SIDES:
        return 'refused: entrance_side must be north, east, south or west'
    try:
        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    except ValueError as e:
        return f'refused: {e}'
    W, D = xmax - xmin, zmax - zmin
    if min(W, D) < MIN_SIDE - 1e-9:
        return (
            f'refused: a lobby needs at least {MIN_SIDE:g} x {MIN_SIDE:g} m — that block is '
            f'{W:g} x {D:g} m; a smaller entrance is a corridor with a desk'
        )
    gone = [k for k in CORE_KINDS if k not in _A.KINDS]
    if gone:
        return f'refused: the furniture family is not loaded (no {", ".join(gone)})'

    (fx, fz), (ux, uz) = _AXES[side]
    ox = (xmin + xmax) / 2 - fx * W / 2  # the centre of the ENTRANCE wall
    oz = (zmin + zmax) / 2 - fz * D / 2
    depth, across = (D, W) if fz else (W, D)
    facing = {'out': _ry(-fx, -fz), 'in': _ry(fx, fz), '+u': _ry(ux, uz), '-u': _ry(-ux, -uz)}

    st = int(_num(storey, 0))
    floor = st * d.storey_h
    grp = f'{str(name or "Lobby").strip() or "Lobby"} fit-out'
    lux = str(style or 'luxury').strip().lower() == 'luxury'
    top = _mat(DESK_TOP) if lux else SEAT_MAT

    # luxury gets the pack models; standard is the all-parametric layout, unchanged
    models_ok = lux and across >= ASSET_MIN_ACROSS and 'place_asset' in getattr(_A, 'TOOL_FN', {})
    if models_ok:
        items, models, gc = _lux_layout(depth, across)
        sofa_gap = 2 * _clamp((depth - 1.7 - CLEAR) / 2.0 - 0.60, 1.2, 2.0)
    else:
        items = [
            (k, u, v, f, nm, top if k == 'desk' else SEAT_MAT, None)
            for k, u, v, f, nm in _layout(depth, across, _plant_kind())
        ]
        models, gc, sofa_gap = [], depth / 2.0, 2.4
    wh = _wall_h(d, xmin, zmin, xmax, zmax, floor)
    lit = LIGHT_KIND in _A.KINDS
    spots = _grid(depth, across)[: max(0, LIGHT_CAP - _lights(d))] if lit else []
    n_new = len(items) + len(models) + len(spots) + 1
    if len(d.objs) + n_new > MAX_OBJECTS:
        return f'refused: that is {n_new} objects past the {MAX_OBJECTS} ceiling'

    def _xz(u, v):
        return (
            _clamp(ox + fx * v + ux * u, xmin + EDGE, xmax - EDGE),
            _clamp(oz + fz * v + uz * u, zmin + EDGE, zmax - EDGE),
        )

    made: dict = {}
    first = len(d.added)
    for kind, u, v, face, nm, mat, extra in items:
        x, z = _xz(u, v)
        p = _p(kind)
        p.update(extra or {})
        d.new(kind, p, x, z, place_height(d, x, z, floor), facing[face], _mat(mat), name=nm, grp=grp)
        made[kind] = made.get(kind, 0) + 1

    # the models. A pack seat is turned by ASSET_RY on top of the parametric ry
    # (see the note by the constant) — that is what makes the sofas face each other.
    fell: list = []
    for aid, kind, u, v, face, nm in models:
        x, z = _xz(u, v)
        y = place_height(d, x, z, floor)
        rec, why = _place_model(d, aid, x, z, y, _wrap(facing[face] + ASSET_RY), nm, grp, st)
        if rec is None:
            fell.append(nm)
            if kind and kind in _A.KINDS:
                d.new(kind, _p(kind), x, z, y, facing[face], SEAT_MAT, name=nm, grp=grp)
                made[kind] = made.get(kind, 0) + 1
    hang = ''
    if models_ok:
        ceil = floor + (wh if wh > 0 else LIGHT_H)
        # floored to the 4 decimals place_asset keeps, never rounded: rounding UP
        # lengthens the drop and eats the head clearance by a few hundredths of a mm
        sc = math.floor(_clamp((ceil - floor - CHANDELIER_CLEAR) / CHANDELIER_DROP, 0.0, 1.0) * 10000.0) / 10000.0
        if sc < 0.3:
            hang = (
                f' No chandelier: the ceiling is {ceil - floor:.2f} m and the model would hang '
                f'below {CHANDELIER_CLEAR:g} m of head clearance.'
            )
        else:
            x, z = _xz(0.0, gc)
            # the record's y is the HANG POINT, not the base: this GLB is modelled
            # hanging below its own origin (measured drop CHANDELIER_DROP m at scale 1)
            rec, why = _place_model(d, ASSET_CHANDELIER, x, z, ceil, 0.0, 'chandelier', grp, st, sc)
            if rec is None:
                fell.append('chandelier')
                hang = f' No chandelier ({why}).'
            else:
                rec['meta'] = dict(rec.get('meta') or {}, hung=True)
                hang = (
                    f' A chandelier hangs from the {ceil - floor:.2f} m ceiling at scale {sc:.2f}, '
                    f'its base {ceil - CHANDELIER_DROP * sc - floor:.2f} m clear of the floor.'
                )

    ly = floor + (wh - 0.6 if wh > 0 else LIGHT_H)
    for n, (u, v) in enumerate(spots):
        x, z = _xz(u, v)
        d.new(LIGHT_KIND, _p(LIGHT_KIND), x, z, ly, 0.0, 'mat_plaster', name=f'ceiling light {n + 1}', grp=grp)

    painted = 0
    if lux and LUX_WALL in MATERIALS:
        for o in _walls_here(d, xmin, zmin, xmax, zmax, floor):
            # PARTITIONS only. A 'wall' on this block is the shell, which carries the
            # schedule's own concrete — repainting it plaster made a shell wall read as
            # an interior one and broke test_finish_schedule.
            if o.get('kind') == 'partition' and o.get('mat') != LUX_WALL:
                o['mat'] = LUX_WALL
                painted += 1

    ids = d.added[first:]
    d.selected = list(ids)
    if models_ok:
        n_sofa = sum(1 for m in models if m[1] == 'sofa')
        n_arm = sum(1 for m in models if m[1] == 'armchair')
        plants = sum(1 for m in models if m[0] == ASSET_PLANT)
        wait = sum(1 for it in items if it[0] == 'armchair')
    else:
        n_sofa, n_arm = made.get('sofa', 0), made.get('armchair', 0)
        plants = sum(v for k, v in made.items() if k in PLANT_KINDS)
        wait = 0
    return (
        f'"{grp}": reception of {made.get("desk", 0)} desks at the far end facing the {side} entrance, '
        f'top in {top}'
        + (f' over a {_mat(LUX_PANEL)} front panel' if models_ok and 'box' in _A.KINDS else '')
        + f'. Seating on the axis: {n_sofa + n_arm} seats '
        f'({n_sofa} sofas {sofa_gap:.1f} m apart, {n_arm} armchairs), '
        f'1 coffee table on 1 rug. {plants} planters in the corners. '
        + (f'{wait} waiting chairs at the counter. ' if wait else '')
        + ('The seating and the planters are real pack models, not boxes. ' if models_ok else '')
        + (
            f'The room is only {across:.1f} m across, under the {ASSET_MIN_ACROSS:g} m the seating '
            'models need, so the whole fit-out stayed parametric. '
            if lux and not models_ok
            else ''
        )
        + (f'FELL BACK to the parametric kind for {len(fell)}: {", ".join(fell)}. ' if fell else '')
        + hang.strip()
        + (' ' if hang else '')
        + (f'Partitions repainted {LUX_WALL} ({painted}). ' if painted else '')
        + f'{len(spots)} ceiling lights on a {LIGHT_GRID:g} m grid at y {ly:.2f} m. '
        f'{len(ids)} records in the {W:g} x {D:g} m block on storey {st}, {CLEAR:g} m clear to the '
        f'entrance wall; ids {ids[0]}..{ids[-1]}'
    )


TOOLS = [
    (
        {
            'name': 'furnish_lobby',
            'description': 'Furnish an entrance lobby a block of cells already holds: a reception desk at the far '
            'end facing the entrance, a seating group (two sofas facing each other, armchairs, '
            'coffee table, rug) on the entrance axis, planters in the corners and ceiling lights on '
            'a 4 m grid, with 1.2 m of circulation clear off the entrance wall. Needs at least '
            '6 x 6 m. Call it after add_room(name="Lobby") — an empty lobby does not answer the '
            'build checklist on a luxury job.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'entrance_side': {
                        'type': 'string',
                        'enum': list(SIDES),
                        'description': 'the wall people come in through; the desk goes opposite it',
                    },
                    'style': {
                        'type': 'string',
                        'enum': ['luxury', 'standard'],
                        'description': 'luxury: a marble-on-oak desk, and real pack models for the '
                        'seating, planters and chandelier',
                    },
                    'name': {'type': 'string', 'description': 'the room name, e.g. "Lobby"'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_furnish_lobby,
    ),
]

EXAMPLES = [
    {
        'ask': 'the lobby is bare — put a reception desk and some seating in it',
        'calls': [
            {
                'tool': 'furnish_lobby',
                'args': {'cell_from': 'EY91', 'cell_to': 'FH100', 'storey': 0, 'entrance_side': 'south'},
            }
        ],
    },
    {
        'ask': 'make the double-height entrance hall from C4 to N12, people come in from the west',
        'calls': [
            {
                'tool': 'add_room',
                'args': {'cell_from': 'C4', 'cell_to': 'N12', 'storey': 0, 'name': 'Lobby', 'door_side': 'west'},
            },
            {
                'tool': 'furnish_lobby',
                'args': {'cell_from': 'C4', 'cell_to': 'N12', 'storey': 0, 'entrance_side': 'west', 'style': 'luxury'},
            },
        ],
    },
    {
        'ask': 'furnish the office foyer on the first floor, K10 to S18',
        'calls': [
            {
                'tool': 'furnish_lobby',
                'args': {'cell_from': 'K10', 'cell_to': 'S18', 'storey': 1, 'style': 'standard', 'name': 'Foyer'},
            }
        ],
    },
]

if len(PROMPT) > 900:
    raise RuntimeError(len(PROMPT))
