# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""curved_walls — the assistant's curved-wall tools (worked example family).

Tools: draw_curved_wall (centre cell + radius + angles), draw_wall_through
(the arc through three cells), draw_round_wall (a full ring), draw_round_tower
(ring per storey + optional roof). Openings cannot be cut into arcs — the
studio's hole model is per straight wall — so the prompt says so.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, parse_cell, cell_centre, cell_name, MATERIALS, _num, MAX_OBJECTS

KINDS = {
    'wall_arc': {'r': 5, 'a0': 0, 'a1': 90, 'h': 2.7, 't': 0.24, 'seg': 24},
    'wall_ring': {'r': 5, 'h': 2.7, 't': 0.24, 'seg': 48},
}
OPENINGS: list = []

PROMPT = (
    'Curved walls: draw_curved_wall(centre, radius, start_deg, end_deg, storeys) draws an arc of wall '
    'around the centre cell (angles on the plan: 0 = east/+X, 90 = north/up in the top view, counter-clockwise); '
    'draw_wall_through(cell_a, cell_b, cell_c) draws the arc that passes through three cells (a to c via b); '
    'draw_round_wall(centre, radius) is a full circle; draw_round_tower(centre, radius, storeys, roof) stacks rings '
    'with slabs and a cone/dome/flat cap. Windows cannot be cut into curved walls (holes exist only on straight walls) — '
    'for a glazed round tower use draw_round_wall with material mat_glass on the glass storeys instead.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _arc(d: Drawing, cx, cz, r, a0, a1, storeys, storey_from, mat, h, t, name, grp):
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    H = _num(h, d.storey_h) or d.storey_h
    ids = []
    if len(d.objs) + n > MAX_OBJECTS:
        raise ValueError(f'that is {n} objects past the {MAX_OBJECTS} ceiling')
    for k in range(n):
        o = d.new(
            'wall_arc',
            {
                'r': round(r, 3),
                'a0': round(a0, 2),
                'a1': round(a1, 2),
                'h': H,
                't': _num(t, d.wall_t) or d.wall_t,
                'seg': max(8, int(abs(a1 - a0) / 6) + 4),
            },
            cx,
            cz,
            (s0 + k) * H,
            0.0,
            mat,
            name=name or f'curved wall st{s0 + k}',
            grp=grp,
        )
        ids.append(o['id'])
    return ids, n, H


def t_draw_curved_wall(
    d: Drawing,
    a,
    centre,
    radius=5.0,
    start_deg=0.0,
    end_deg=90.0,
    storeys=1,
    storey_from=0,
    material='',
    wall_h=None,
    wall_t=None,
    name='',
):
    cx, cz = cell_centre(*parse_cell(centre))
    r = _num(radius, 5.0)
    if r < 0.5 or r > 150:
        return 'refused: radius must be between 0.5 and 150 m'
    a0, a1 = _num(start_deg, 0.0), _num(end_deg, 90.0)
    if abs(a1 - a0) < 1:
        return 'refused: the arc needs at least 1 degree between start_deg and end_deg'
    ids, n, H = _arc(d, cx, cz, r, a0, a1, storeys, storey_from, _mat(material), wall_h, wall_t, name, name)
    return (
        f'drew {n} curved wall(s) {ids[0]}..{ids[-1]} around {cell_name(*parse_cell(centre))}: radius {r:g} m, '
        f'{a0:g}° to {a1:g}°, storeys {int(_num(storey_from, 0))}..{int(_num(storey_from, 0)) + n - 1} ({H:g} m each)'
    )


def t_draw_wall_through(
    d: Drawing, a, cell_a, cell_b, cell_c, storeys=1, storey_from=0, material='', wall_h=None, wall_t=None, name=''
):
    """The circle through three points; the arc runs a -> b -> c."""
    A = cell_centre(*parse_cell(cell_a))
    B = cell_centre(*parse_cell(cell_b))
    C = cell_centre(*parse_cell(cell_c))
    ax, az = A
    bx, bz = B
    cx_, cz_ = C
    det = 2 * (ax * (bz - cz_) + bx * (cz_ - az) + cx_ * (az - bz))
    if abs(det) < 1e-6:
        return 'refused: the three cells are in a straight line — use draw_wall for that'
    ux = (
        (ax * ax + az * az) * (bz - cz_) + (bx * bx + bz * bz) * (cz_ - az) + (cx_ * cx_ + cz_ * cz_) * (az - bz)
    ) / det
    uz = (
        (ax * ax + az * az) * (cx_ - bx) + (bx * bx + bz * bz) * (ax - cx_) + (cx_ * cx_ + cz_ * cz_) * (bx - ax)
    ) / det
    r = math.hypot(ax - ux, az - uz)
    if r > 200:
        return 'refused: those cells lie almost on a line (radius over 200 m) — use draw_wall'

    def ang(px, pz):
        return math.degrees(math.atan2(-(pz - uz), px - ux)) % 360

    ta, tb, tc = ang(ax, az), ang(bx, bz), ang(cx_, cz_)
    # go from a to c in the direction that passes b
    ccw = (tb - ta) % 360 < (tc - ta) % 360
    if ccw:
        a0, a1 = ta, ta + (tc - ta) % 360
    else:
        a0, a1 = ta, ta - (ta - tc) % 360
    ids, n, H = _arc(d, ux, uz, r, a0, a1, storeys, storey_from, _mat(material), wall_h, wall_t, name, name)
    return (
        f'drew {n} curved wall(s) {ids[0]}..{ids[-1]} through {cell_a}, {cell_b}, {cell_c}: centre near '
        f'{cell_name(*parse_cell(cell_a)) if False else ""}({ux:.1f}, {uz:.1f}) m, radius {r:.2f} m, {a0:.0f}° to {a1:.0f}°'
    )


def t_draw_round_wall(
    d: Drawing, a, centre, radius=5.0, storeys=1, storey_from=0, material='', wall_h=None, wall_t=None, name=''
):
    cx, cz = cell_centre(*parse_cell(centre))
    r = _num(radius, 5.0)
    if r < 0.5 or r > 150:
        return 'refused: radius must be between 0.5 and 150 m'
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    H = _num(wall_h, d.storey_h) or d.storey_h
    ids = []
    for k in range(n):
        o = d.new(
            'wall_ring',
            {'r': round(r, 3), 'h': H, 't': _num(wall_t, d.wall_t) or d.wall_t, 'seg': 48},
            cx,
            cz,
            (s0 + k) * H,
            0.0,
            _mat(material),
            name=name or f'round wall st{s0 + k}',
            grp=name,
        )
        ids.append(o['id'])
    return f'drew {n} round wall(s) {ids[0]}..{ids[-1]} around {cell_name(*parse_cell(centre))}, radius {r:g} m'


def t_draw_round_tower(
    d: Drawing,
    a,
    centre,
    radius=5.0,
    storeys=3,
    storey_from=0,
    roof='cone',
    material='',
    slabs=True,
    glass_every=0,
    name='',
):
    cx, cz = cell_centre(*parse_cell(centre))
    r = _num(radius, 5.0)
    if r < 0.5 or r > 150:
        return 'refused: radius must be between 0.5 and 150 m'
    n = max(1, min(400, int(_num(storeys, 3))))
    s0 = int(_num(storey_from, 0))
    H = d.storey_h
    grp = name or f'round tower {cell_name(*parse_cell(centre))}'
    ge = int(_num(glass_every, 0))
    need = n * (2 if slabs else 1) + 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    for k in range(n):
        st = s0 + k
        glass = ge > 0 and (st - s0) % ge == 0
        d.new(
            'wall_ring',
            {'r': round(r, 3), 'h': H, 't': d.wall_t, 'seg': 48},
            cx,
            cz,
            st * H,
            0.0,
            'mat_glass' if glass else _mat(material),
            name=f'shell st{st}',
            grp=grp,
        )
        if slabs:
            d.new(
                'disc',
                {'r': round(r, 3), 'seg': 48},
                cx,
                cz,
                st * H + 0.001,
                0.0,
                _mat(material),
                name=f'floor st{st}',
                grp=grp,
            )
    top = (s0 + n) * H
    if roof == 'cone':
        d.new(
            'cone',
            {'r': round(r + 0.3, 3), 'h': round(max(1.5, r * 0.9), 3), 'seg': 48},
            cx,
            cz,
            top,
            0.0,
            'mat_roof_tile',
            name='cone roof',
            grp=grp,
        )
    elif roof == 'dome':
        d.new(
            'roof_dome',
            {'r': round(r + 0.1, 3), 'h': round(r * 0.8, 3)},
            cx,
            cz,
            top,
            0.0,
            'mat_zinc',
            name='dome',
            grp=grp,
        )
    elif roof == 'flat':
        d.new('disc', {'r': round(r + 0.15, 3), 'seg': 48}, cx, cz, top, 0.0, _mat(material), name='flat roof', grp=grp)
    return f'drew round tower "{grp}": radius {r:g} m, {n} storeys ({n * H:g} m), {roof} roof' + (
        f', glass every {ge} storeys' if ge else ''
    )


TOOLS = [
    (
        {
            'name': 'draw_curved_wall',
            'description': 'An arc of wall around a centre cell: radius in metres, start and end angle in degrees on the plan (0 = east, 90 = north, counter-clockwise), repeated per storey. Use for curved facades, bay fronts, apses.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'start_deg': {'type': 'number'},
                    'end_deg': {'type': 'number'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'wall_h': {'type': 'number'},
                    'wall_t': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_draw_curved_wall,
    ),
    (
        {
            'name': 'draw_wall_through',
            'description': 'The curved wall that passes through three cells, from cell_a to cell_c via cell_b. Use when the user names points the curve must touch.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_a': {'type': 'string'},
                    'cell_b': {'type': 'string'},
                    'cell_c': {'type': 'string'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'wall_h': {'type': 'number'},
                    'wall_t': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_a', 'cell_b', 'cell_c'],
            },
        },
        t_draw_wall_through,
    ),
    (
        {
            'name': 'draw_round_wall',
            'description': 'A full circle of wall around a centre cell (a silo, a well, a round room), repeated per storey.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'wall_h': {'type': 'number'},
                    'wall_t': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_draw_round_wall,
    ),
    (
        {
            'name': 'draw_round_tower',
            'description': 'A round tower: a ring of wall per storey with a floor disc each, capped with a cone, dome or flat roof. glass_every=2 makes every second storey a glass ring.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'storeys': {'type': 'integer'},
                    'storey_from': {'type': 'integer'},
                    'roof': {'type': 'string', 'enum': ['cone', 'dome', 'flat', 'none']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'slabs': {'type': 'boolean'},
                    'glass_every': {'type': 'integer'},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_draw_round_tower,
    ),
]

EXAMPLES = [
    {
        'ask': 'a curved wall around C4, radius 6, a quarter circle facing north-east',
        'calls': [{'tool': 'draw_curved_wall', 'args': {'centre': 'C4', 'radius': 6, 'start_deg': 0, 'end_deg': 90}}],
    },
    {
        'ask': 'a round tower on K20, 8 m across, 5 floors, glass every 2 floors, cone roof',
        'calls': [
            {
                'tool': 'draw_round_tower',
                'args': {'centre': 'K20', 'radius': 4, 'storeys': 5, 'glass_every': 2, 'roof': 'cone'},
            }
        ],
    },
    {
        'ask': 'a wall curving from D10 through F8 to H10',
        'calls': [{'tool': 'draw_wall_through', 'args': {'cell_a': 'D10', 'cell_b': 'F8', 'cell_c': 'H10'}}],
    },
]
