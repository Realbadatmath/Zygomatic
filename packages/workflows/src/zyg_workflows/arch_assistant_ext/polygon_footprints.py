# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""polygon_footprints — buildings whose plan is not a rectangle.

Everything here rests on ONE new kind, `slab_poly`: a floor plate whose
footprint is an arbitrary polygon (`pts`, local [x, z] metres) with optional
`holes`. The walls are ordinary straight `wall` records — one per polygon edge
per storey, positioned and rotated exactly the way arch_assistant.t_draw_wall
does it — so windows and openings still work on them.

Tools: draw_polygon_building (a plan through cells the user names),
draw_l_building (a block minus a notch: L, T or U), draw_regular_building
(hexagons, octagons, round-ish towers), add_polygon_slab (one plate) and
add_atrium (cut a void through the rectangular slabs of a group).
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    MATERIALS,
    MAX_OBJECTS,
    Drawing,
    _num,
    block_bounds,
    cell_centre,
    cell_name,
    parse_cell,
    storey_of,
)

KINDS = {
    'slab_poly': {'pts': [[-3, -2], [3, -2], [3, 2], [-3, 2]], 't': 0.22, 'holes': []},
}
OPENINGS: list = []

PROMPT = (
    'Polygon footprints: draw_polygon_building(cells=[3 or more cells in order], storeys, roof) '
    'builds a plan that is the polygon through those cell centres — one wall per edge per storey plus a '
    'slab_poly floor; use it whenever the footprint is not a rectangle. draw_l_building(cell_from, cell_to, '
    'notch_from, notch_to, storeys) is a rectangular block minus a notch: a notch in a CORNER gives an L '
    '(6 walls per storey), a notch flush against one side gives a T or U (8 walls); a notch floating inside '
    'the block is refused — that is an atrium, not a notch. draw_regular_building(centre, sides, radius, '
    "storeys, roof='pyramid') is a regular hexagon/octagon tower. add_polygon_slab(cells, storey) lays a "
    'single polygon floor. add_atrium(group, cell_from, cell_to) cuts a void through the rectangular slabs of '
    'a group that cover those cells. add_windows works on all these walls.'
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _cells_to_points(cells):
    """['C4', ...] -> [(x, z), ...] cell centres. Raises ValueError on a bad cell."""
    if not isinstance(cells, (list, tuple)):
        raise ValueError('cells must be a list of cell names in order, like ["C4", "L4", "L13"]')
    pts = []
    for c in cells:
        pts.append(cell_centre(*parse_cell(c)))
    out = []
    for p in pts:  # drop a repeated point
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 3 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    return out


def _centroid(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _walls(d: Drawing, pts, storeys, storey_from, mat, H, T, grp):
    """One straight wall per polygon edge per storey. Returns the ids."""
    n = len(pts)
    ids = []
    for k in range(storeys):
        st = storey_from + k
        for i in range(n):
            ax, az = pts[i]
            bx, bz = pts[(i + 1) % n]
            L = math.hypot(bx - ax, bz - az)
            if L < 0.05:
                continue
            ry = math.atan2(-(bz - az), bx - ax)
            w = d.new(
                'wall',
                {'len': round(L, 4), 'h': H, 't': T},
                (ax + bx) / 2,
                (az + bz) / 2,
                st * H,
                ry,
                mat,
                name=f'wall {i + 1} st{st}',
                grp=grp,
            )
            ids.append(w['id'])
    return ids


def _slab(d: Drawing, pts, y, t, mat, name, grp, holes=None):
    cx, cz = _centroid(pts)
    p = {
        'pts': [[round(x - cx, 4), round(z - cz, 4)] for x, z in pts],
        't': round(_num(t, 0.22), 4),
        'holes': [[[round(x - cx, 4), round(z - cz, 4)] for x, z in h] for h in (holes or [])],
    }
    return d.new('slab_poly', p, cx, cz, y, 0.0, mat, name=name, grp=grp)


def _build(d: Drawing, pts, storeys, storey_from, slabs, roof, material, name, grp, what):
    """The shared body of the three draw_* tools. Returns a result string."""
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    H, T = d.storey_h, d.wall_t
    mat = _mat(material)
    need = n * (len(pts) + (1 if slabs else 0)) + (1 if roof == 'flat' else 0)
    if len(d.objs) + need > MAX_OBJECTS:
        return None, f'refused: that is {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    ids = _walls(d, pts, n, s0, mat, H, T, grp)
    if not ids:
        return None, 'refused: those corners are all in one place — a plan needs corners at least 5 cm apart'
    for k in range(n):
        if slabs:
            _slab(d, pts, (s0 + k) * H, 0.22, mat, f'floor st{s0 + k}', grp)
    if roof == 'flat':
        _slab(d, pts, (s0 + n) * H, 0.3, mat, 'flat roof', grp)
    per = len(pts)
    return ids, (
        f'drew group "{grp}": {what}, {per} walls per storey ({ids[0]}..{ids[-1]}), '
        f'storeys {s0}..{s0 + n - 1} ({n * H:g} m tall)'
        + (f', {n} polygon floor(s)' if slabs else '')
        + (', a flat roof' if roof == 'flat' else '')
    )


def _rect_minus(block, notch):
    """block minus notch, both (x0, z0, x1, z1) -> the rectilinear ring of
    corners, or None when the result is not ONE simple ring (a floating notch
    leaves a hole, a covering notch leaves nothing)."""
    bx0, bz0, bx1, bz1 = block
    nx0, nz0, nx1, nz1 = notch

    def clip(v, lo, hi):
        return min(max(v, lo), hi)

    xs = sorted({bx0, bx1, clip(nx0, bx0, bx1), clip(nx1, bx0, bx1)})
    zs = sorted({bz0, bz1, clip(nz0, bz0, bz1), clip(nz1, bz0, bz1)})
    edges: dict = {}
    cells = 0
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            mx, mz = (xs[i] + xs[i + 1]) / 2, (zs[j] + zs[j + 1]) / 2
            if nx0 - 1e-9 < mx < nx1 + 1e-9 and nz0 - 1e-9 < mz < nz1 + 1e-9:
                continue  # eaten by the notch
            cells += 1
            c = [(xs[i], zs[j]), (xs[i + 1], zs[j]), (xs[i + 1], zs[j + 1]), (xs[i], zs[j + 1])]
            for k in range(4):
                a, b = c[k], c[(k + 1) % 4]
                if edges.pop((b, a), None) is None:  # cancel the shared inner edge
                    edges[(a, b)] = True
    if not cells or not edges:
        return None
    nxt = {a: b for a, b in edges}
    start = min(nxt)
    loop, cur = [start], nxt[start]
    while cur != start:
        loop.append(cur)
        cur = nxt.get(cur)
        if cur is None or len(loop) > 64:
            return None
    if len(loop) != len(edges):  # more than one ring
        return None
    out = []
    m = len(loop)
    for k in range(m):
        px, pz = loop[(k - 1) % m]
        cx, cz = loop[k]
        qx, qz = loop[(k + 1) % m]
        if abs((cx - px) * (qz - cz) - (cz - pz) * (qx - cx)) > 1e-9:
            out.append((cx, cz))  # a real corner, not collinear
    return out if len(out) >= 3 else None


# ── the tools ───────────────────────────────────────────────────────────────
def t_draw_polygon_building(
    d: Drawing, a, cells, storeys=1, storey_from=0, slabs=True, roof='none', material='', name=''
):
    pts = _cells_to_points(cells)
    if len(pts) < 3:
        return 'refused: a polygon plan needs at least 3 different cells, in the order you walk round the plan'
    if len(pts) > 60:
        return 'refused: at most 60 corners — that is a curve, use draw_curved_wall'
    grp = name or f'polygon building {cell_name(*parse_cell(cells[0]))}'
    ids, msg = _build(
        d,
        pts,
        storeys,
        storey_from,
        slabs,
        roof,
        material,
        name,
        grp,
        f'{len(pts)}-sided plan through {len(pts)} cells',
    )
    return msg


def t_draw_l_building(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    notch_from,
    notch_to,
    storeys=1,
    storey_from=0,
    slabs=True,
    roof='none',
    material='',
    name='',
):
    bx0, bz0, bx1, bz1 = block_bounds(cell_from, cell_to)
    nx0, nz0, nx1, nz1 = block_bounds(notch_from, notch_to)
    if not (nx1 > bx0 + 1e-9 and nx0 < bx1 - 1e-9 and nz1 > bz0 + 1e-9 and nz0 < bz1 - 1e-9):
        return 'refused: the notch does not overlap the block — give notch cells inside cell_from..cell_to'
    pts = _rect_minus((bx0, bz0, bx1, bz1), (nx0, nz0, nx1, nz1))
    if pts is None:
        return (
            'refused: the notch must sit in a CORNER of the block (an L) or flush against one whole side '
            '(a T or U); this one floats inside it or swallows it — for a void inside a floor use add_atrium'
        )
    if len(pts) < 6:
        return 'refused: that notch takes a whole strip off the block — the result is a plain rectangle, use draw_box'
    shape = 'L' if len(pts) == 6 else 'T/U'
    grp = name or f'{shape} building {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    ids, msg = _build(
        d,
        pts,
        storeys,
        storey_from,
        slabs,
        roof,
        material,
        name,
        grp,
        f'{shape}-shaped plan, {bx1 - bx0:g} x {bz1 - bz0:g} m block minus a '
        f'{nx1 - nx0:g} x {nz1 - nz0:g} m notch, {len(pts)} corners',
    )
    return msg


def t_draw_regular_building(
    d: Drawing,
    a,
    centre,
    sides=6,
    radius=6.0,
    storeys=1,
    storey_from=0,
    slabs=True,
    roof='pyramid',
    material='',
    name='',
):
    cx, cz = cell_centre(*parse_cell(centre))
    n_s = int(_num(sides, 6))
    r = _num(radius, 6.0)
    if n_s < 3 or n_s > 60:
        return 'refused: sides must be between 3 and 60'
    if r < 0.5 or r > 150:
        return 'refused: radius must be between 0.5 and 150 m'
    pts = []
    for k in range(n_s):
        th = 2 * math.pi * k / n_s
        pts.append((cx + r * math.cos(th), cz - r * math.sin(th)))  # 0 deg = +X, 90 deg = -Z
    grp = name or f'{n_s}-sided building {cell_name(*parse_cell(centre))}'
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    ids, msg = _build(
        d,
        pts,
        n,
        s0,
        slabs,
        'flat' if roof == 'flat' else 'none',
        material,
        name,
        grp,
        f'regular {n_s}-gon, radius {r:g} m around {cell_name(*parse_cell(centre))}',
    )
    if ids is None:
        return msg
    if roof == 'pyramid':
        d.new(
            'pyramid',
            {'r': round(r + 0.3, 3), 'h': round(r * 0.6, 3), 'sides': n_s},
            cx,
            cz,
            (s0 + n) * d.storey_h,
            0.0,
            'mat_roof_tile',
            name='pyramid roof',
            grp=grp,
        )
        msg += ', a pyramid roof'
    return msg


def t_add_polygon_slab(d: Drawing, a, cells, storey=0, thickness=0.22, material='', name=''):
    pts = _cells_to_points(cells)
    if len(pts) < 3:
        return 'refused: a polygon slab needs at least 3 different cells, in order round the outline'
    st = int(_num(storey, 0))
    s = _slab(d, pts, st * d.storey_h, _num(thickness, 0.22), _mat(material), name or None, name)
    cx, cz = _centroid(pts)
    return (
        f'polygon slab {s["id"]} through {len(pts)} cells at storey {st}, '
        f"{_num(thickness, 0.22):g} m thick, centred on {cell_name(*parse_cell(cells[0]))}'s block "
        f'({cx:.1f}, {cz:.1f}) m'
    )


def t_add_atrium(d: Drawing, a, group, cell_from, cell_to):
    bx0, bz0, bx1, bz1 = block_bounds(cell_from, cell_to)
    recs = [o for o in d.select(group) if o['kind'] == 'slab']
    hit = []
    for o in recs:
        w, dd = _num(o['p'].get('w'), 0), _num(o['p'].get('d'), 0)
        if w <= 0 or dd <= 0 or abs(o['ry']) > 1e-6:
            continue
        x0, z0, x1, z1 = o['x'] - w / 2, o['z'] - dd / 2, o['x'] + w / 2, o['z'] + dd / 2
        if x0 - 1e-6 <= bx0 and bx1 <= x1 + 1e-6 and z0 - 1e-6 <= bz0 and bz1 <= z1 + 1e-6:
            hit.append((o, w, dd))
    if not hit:
        return (
            f'refused: no rectangular slab in "{group}" covers cells {cell_from}..{cell_to} — '
            'check the group name, or draw the floors first'
        )
    for o, w, dd in hit:
        t = _num(o['p'].get('t'), 0.22)
        o['kind'] = 'slab_poly'
        o['p'] = {
            'pts': [
                [round(-w / 2, 4), round(-dd / 2, 4)],
                [round(w / 2, 4), round(-dd / 2, 4)],
                [round(w / 2, 4), round(dd / 2, 4)],
                [round(-w / 2, 4), round(dd / 2, 4)],
            ],
            't': round(t, 4),
            'holes': [
                [
                    [round(bx0 - o['x'], 4), round(bz0 - o['z'], 4)],
                    [round(bx1 - o['x'], 4), round(bz0 - o['z'], 4)],
                    [round(bx1 - o['x'], 4), round(bz1 - o['z'], 4)],
                    [round(bx0 - o['x'], 4), round(bz1 - o['z'], 4)],
                ]
            ],
        }
    ids = ', '.join(o['id'] for o, _w, _d in hit)
    sts = sorted({storey_of(o['y'], d.storey_h) for o, _w, _d in hit})
    return (
        f'cut a {bx1 - bx0:g} x {bz1 - bz0:g} m atrium ({cell_from}..{cell_to}) through {len(hit)} slab(s) '
        f'{ids} of "{group}" — storeys {sts[0]}..{sts[-1]}; they are polygon slabs with a hole now'
    )


TOOLS = [
    (
        {
            'name': 'draw_polygon_building',
            'description': 'A building whose plan is the polygon through the cells you list, in order round the outline (3 or more): one straight wall per edge per storey, a polygon floor per storey, optionally a flat roof. Use for any footprint that is not a rectangle.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'cell names in order round the plan, e.g. ["C4","L4","L13","C13"]',
                    },
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'slabs': {'type': 'boolean'},
                    'roof': {'type': 'string', 'enum': ['none', 'flat']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_draw_polygon_building,
    ),
    (
        {
            'name': 'draw_l_building',
            'description': 'A rectangular block minus a notch. A notch in a corner of the block gives an L-shaped plan (6 walls per storey); a notch flush against one whole side gives a T or U (8 walls). A notch floating inside the block is refused — use add_atrium for a void.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'notch_from': {'type': 'string'},
                    'notch_to': {'type': 'string'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'slabs': {'type': 'boolean'},
                    'roof': {'type': 'string', 'enum': ['none', 'flat']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'notch_from', 'notch_to'],
            },
        },
        t_draw_l_building,
    ),
    (
        {
            'name': 'draw_regular_building',
            'description': 'A regular polygon building around a centre cell: sides=6 is a hexagon, 8 an octagon, radius is centre-to-corner in metres. roof="pyramid" caps it with a matching pyramid, "flat" with a polygon roof slab.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'sides': {'type': 'integer'},
                    'radius': {'type': 'number'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'slabs': {'type': 'boolean'},
                    'roof': {'type': 'string', 'enum': ['pyramid', 'flat', 'none']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_draw_regular_building,
    ),
    (
        {
            'name': 'add_polygon_slab',
            'description': 'One floor plate through the cells you list, in order round its outline — a terrace, a landing, a canopy deck, a floor of any shape.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'storey': {'type': 'integer'},
                    'thickness': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_polygon_slab,
    ),
    (
        {
            'name': 'add_atrium',
            'description': 'Cut a rectangular void through the floors of a group: every rectangular slab of that group whose footprint covers the cell block becomes a polygon slab with the block as a hole. Use for atriums, light wells and stair voids.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'a group name, "new", "all" or slab ids'},
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                },
                'required': ['group', 'cell_from', 'cell_to'],
            },
        },
        t_add_atrium,
    ),
]

EXAMPLES = [
    {
        'ask': 'an L-shaped house from C4 to L13 with the corner at C4 to E6 cut away, 2 floors, flat roof',
        'calls': [
            {
                'tool': 'draw_l_building',
                'args': {
                    'cell_from': 'C4',
                    'cell_to': 'L13',
                    'notch_from': 'C4',
                    'notch_to': 'E6',
                    'storeys': 2,
                    'roof': 'flat',
                    'material': 'mat_brick',
                },
            }
        ],
    },
    {
        'ask': 'a five-sided block through D10, J10, L15, G19 and B15, 3 storeys',
        'calls': [
            {'tool': 'draw_polygon_building', 'args': {'cells': ['D10', 'J10', 'L15', 'G19', 'B15'], 'storeys': 3}}
        ],
    },
    {
        'ask': 'an octagonal tower on K20, 7 m across, 4 floors, pyramid roof',
        'calls': [
            {
                'tool': 'draw_regular_building',
                'args': {'centre': 'K20', 'sides': 8, 'radius': 3.5, 'storeys': 4, 'roof': 'pyramid'},
            }
        ],
    },
    {
        'ask': 'put an atrium from F7 to H9 through the floors of the block',
        'calls': [{'tool': 'add_atrium', 'args': {'group': 'blok', 'cell_from': 'F7', 'cell_to': 'H9'}}],
    },
    {
        'ask': 'a terrace on the corner cells C14, L14, L16 and C16',
        'calls': [
            {
                'tool': 'add_polygon_slab',
                'args': {'cells': ['C14', 'L14', 'L16', 'C16'], 'storey': 0, 'material': 'mat_timber'},
            }
        ],
    },
]
