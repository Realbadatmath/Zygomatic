# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""structure_frames — the assistant's structural-skeleton tools.

Six tools that lay out the load-bearing frame over the cell grid:
add_column_grid (a column at every grid intersection of a block, per storey),
add_colonnade (a run of columns with an I-beam over them), add_beam_grid
(I-beams under a storey's slab), add_portal_frames (a shed's frames across a
block), add_pergola (one pergola sized to a block) and add_bracing (an X brace
on an existing wall). Eight new kinds come with them — see KINDS.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MATERIALS,
    _num,
    MAX_OBJECTS,
)

KINDS = {
    'beam_i': {'len': 5, 'h': 0.4, 'w': 0.2, 'tf': 0.02, 'tw': 0.012},
    'column_h': {'h': 3, 'w': 0.3, 'd': 0.3, 'tf': 0.02, 'tw': 0.012},
    'portal_frame': {'span': 12, 'h': 6, 'rise': 1.5, 'w': 0.25, 'd': 0.5},
    'arch_beam': {'span': 6, 'rise': 1.5, 'w': 0.25, 'd': 0.5, 'seg': 16},
    'buttress': {'h': 3, 'w': 0.6, 'd': 1.2, 'top': 0.3},
    'bracing_x': {'w': 4, 'h': 2.7, 't': 0.08},
    'pergola': {'w': 4, 'd': 3, 'h': 2.4, 'post': 0.12, 'beams': 6},
    'cantilever': {'len': 3, 'w': 0.3, 'h': 0.5},
}
OPENINGS: list = []

COLUMN_KINDS = ('column_rect', 'column_round', 'column_h')
COLUMN_H = 2.7  # a grid column is one storey tall

PROMPT = (
    'Structural frames: add_column_grid(cell_from, cell_to, spacing_x, spacing_z, storeys, kind, size) drops a '
    'column on every grid intersection of a block (edges included) per storey — halls, car parks, floor plates; '
    'add_colonnade(cell_from, cell_to, spacing, kind, height, beam) runs columns every few metres along the line '
    'between two cell centres with an I-beam over them (porch, arcade); '
    'add_beam_grid(cell_from, cell_to, storey, spacing, direction) hangs I-beams under a storey slab, in x, z or '
    'both; add_portal_frames(cell_from, cell_to, count, direction, eaves, rise) fills a block with evenly spaced '
    'portal frames — the skeleton of a shed or barn; add_pergola(cell_from, cell_to, height) sizes one '
    'pergola to a block; add_bracing(wall_id) puts an X brace on an existing wall. add_object also takes beam_i, '
    'column_h, portal_frame, arch_beam, buttress, bracing_x, pergola and cantilever.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _beam_p(length, depth=0.4, width=0.2):
    return {
        'len': round(length, 4),
        'h': round(_num(depth, 0.4), 4),
        'w': round(_num(width, 0.2), 4),
        'tf': 0.02,
        'tw': 0.012,
    }


def _col_p(kind, size, h):
    s = max(0.08, _num(size, 0.4))
    if kind == 'column_round':
        return {'r': round(s / 2, 4), 'h': round(h, 4)}
    if kind == 'column_h':
        return {'h': round(h, 4), 'w': round(s, 4), 'd': round(s, 4), 'tf': 0.02, 'tw': 0.012}
    return {'w': round(s, 4), 'd': round(s, 4), 'h': round(h, 4)}


def _stations(a, b, spacing):
    """Positions from a to b inclusive, as close to `spacing` apart as divides evenly."""
    span = b - a
    if abs(span) < 1e-6:
        return [a]
    sp = max(0.5, _num(spacing, 6))
    n = max(1, int(round(abs(span) / sp)))
    return [a + span * i / n for i in range(n + 1)]


def _room(d: Drawing, need: int):
    return len(d.objs) + need <= MAX_OBJECTS


# ── tools ─────────────────────────────────────────────────────────────────────
def t_add_column_grid(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    spacing_x=6.0,
    spacing_z=6.0,
    storeys=1,
    storey_from=0,
    kind='column_rect',
    size=0.4,
    material='',
    name='',
):
    if kind not in COLUMN_KINDS:
        return 'refused: kind must be column_rect, column_round or column_h'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    xs = _stations(xmin, xmax, spacing_x)
    zs = _stations(zmin, zmax, spacing_z)
    n = max(1, min(200, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    need = len(xs) * len(zs) * n
    if not _room(d, need):
        return f'refused: that is {need} columns and the drawing may hold {MAX_OBJECTS} objects in total'
    grp = name or f'column grid {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mat = _mat(material, 'mat_concrete')
    ids = []
    for k in range(n):
        st = s0 + k
        for zi, z in enumerate(zs):
            for xi, x in enumerate(xs):
                o = d.new(
                    kind,
                    _col_p(kind, size, COLUMN_H),
                    x,
                    z,
                    st * d.storey_h,
                    0.0,
                    mat,
                    name=f'col {chr(65 + xi % 26)}{zi + 1} st{st}',
                    grp=grp,
                )
                ids.append(o['id'])
    return (
        f'grid "{grp}": {len(xs)} x {len(zs)} = {len(xs) * len(zs)} {kind}s per storey on {n} storeys '
        f'({s0}..{s0 + n - 1}) = {need} columns {ids[0]}..{ids[-1]}, '
        f'{(xmax - xmin) / (len(xs) - 1) if len(xs) > 1 else 0:.2f} m apart in x, '
        f'{(zmax - zmin) / (len(zs) - 1) if len(zs) > 1 else 0:.2f} m in z'
    )


def t_add_colonnade(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    spacing=3.0,
    kind='column_round',
    height=3.0,
    beam=True,
    size=0.4,
    material='',
    name='',
):
    if kind not in COLUMN_KINDS:
        return 'refused: kind must be column_rect, column_round or column_h'
    x0, z0 = cell_centre(*parse_cell(cell_from))
    x1, z1 = cell_centre(*parse_cell(cell_to))
    dist = math.hypot(x1 - x0, z1 - z0)
    if dist < 0.5:
        return 'refused: the two cells are the same — a colonnade needs two different cells'
    H = max(0.5, _num(height, 3.0))
    sp = max(0.5, _num(spacing, 3.0))
    steps = max(1, int(round(dist / sp)))
    need = steps + 1 + (1 if beam else 0)
    if not _room(d, need):
        return f'refused: that is {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    ry = math.atan2(-(z1 - z0), x1 - x0)
    grp = name or f'colonnade {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mat = _mat(material, 'mat_concrete')
    ids = []
    for i in range(steps + 1):
        t = i / steps
        o = d.new(
            kind,
            _col_p(kind, size, H),
            x0 + (x1 - x0) * t,
            z0 + (z1 - z0) * t,
            0.0,
            0.0,
            mat,
            name=f'column {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
    bid = ''
    if beam:
        b = d.new(
            'beam_i',
            _beam_p(dist),
            (x0 + x1) / 2,
            (z0 + z1) / 2,
            H,
            ry,
            _mat(material, 'mat_steel'),
            name='colonnade beam',
            grp=grp,
        )
        bid = b['id']
    return (
        f'colonnade "{grp}": {steps + 1} {kind}s {ids[0]}..{ids[-1]} every {dist / steps:.2f} m along '
        f'{dist:.2f} m, {H:g} m tall' + (f', beam_i {bid} spanning {dist:.2f} m over them' if beam else ', no beam')
    )


def t_add_beam_grid(
    d: Drawing, a, cell_from, cell_to, storey=1, spacing=6.0, direction='x', depth=0.4, width=0.2, material='', name=''
):
    dirn = str(direction or 'x').lower()
    if dirn not in ('x', 'z', 'both'):
        return "refused: direction must be 'x', 'z' or 'both'"
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    dep = max(0.05, _num(depth, 0.4))
    st = int(_num(storey, 1))
    y = st * d.storey_h - dep
    lines = []
    if dirn in ('x', 'both'):
        lines += [('x', cx, z, W, 0.0) for z in _stations(zmin, zmax, spacing)]
    if dirn in ('z', 'both'):
        lines += [('z', x, cz, D, -math.pi / 2) for x in _stations(xmin, xmax, spacing)]
    if not _room(d, len(lines)):
        return f'refused: that is {len(lines)} beams and the drawing may hold {MAX_OBJECTS} objects in total'
    grp = name or f'beams st{st} {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mat = _mat(material, 'mat_steel')
    ids = []
    for i, (ax, x, z, L, ry) in enumerate(lines):
        o = d.new('beam_i', _beam_p(L, dep, width), x, z, y, ry, mat, name=f'beam {ax}{i + 1}', grp=grp)
        ids.append(o['id'])
    return (
        f'"{grp}": {len(lines)} beam_i {ids[0]}..{ids[-1]} at y {y:g} m (under the storey-{st} slab), '
        f'{dep:g} m deep, direction {dirn}, over a {W:g} x {D:g} m block'
    )


def t_add_portal_frames(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    count=5,
    direction='x',
    eaves=6.0,
    rise=1.5,
    member_w=0.25,
    member_d=0.5,
    material='',
    name='',
):
    dirn = str(direction or 'x').lower()
    if dirn not in ('x', 'z'):
        return "refused: direction must be 'x' (frames span east-west) or 'z' (north-south)"
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    n = max(1, min(200, int(_num(count, 5))))
    if not _room(d, n):
        return f'refused: that is {n} frames and the drawing may hold {MAX_OBJECTS} objects in total'
    span = W if dirn == 'x' else D
    H = max(0.5, _num(eaves, 6.0))
    p = {
        'span': round(span, 4),
        'h': round(H, 4),
        'rise': round(_num(rise, 1.5), 4),
        'w': round(_num(member_w, 0.25), 4),
        'd': round(_num(member_d, 0.5), 4),
    }
    grp = name or f'portal frames {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mat = _mat(material, 'mat_steel')
    a0, a1 = (zmin, zmax) if dirn == 'x' else (xmin, xmax)
    ry = 0.0 if dirn == 'x' else -math.pi / 2
    ids = []
    for i in range(n):
        t = 0.5 if n == 1 else i / (n - 1)
        u = a0 + (a1 - a0) * t
        x, z = (cx, u) if dirn == 'x' else (u, cz)
        o = d.new('portal_frame', dict(p), x, z, 0.0, ry, mat, name=f'frame {i + 1}', grp=grp)
        ids.append(o['id'])
    step = (a1 - a0) / (n - 1) if n > 1 else 0.0
    return (
        f'"{grp}": {n} portal_frame {ids[0]}..{ids[-1]} spanning {span:g} m along {dirn}, eaves {H:g} m, '
        f'apex {H + p["rise"]:g} m, {step:.2f} m apart over a {W:g} x {D:g} m block'
    )


def t_add_pergola(d: Drawing, a, cell_from, cell_to, height=2.4, post=0.12, material='', name=''):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W < 1 or D < 1:
        return 'refused: a pergola needs a block at least 1 x 1 m'
    H = max(1.0, _num(height, 2.4))
    beams = max(2, min(60, int(round(W / 1.0)) + 1))
    if not _room(d, 1):
        return f'refused: the drawing already holds {MAX_OBJECTS} objects'
    o = d.new(
        'pergola',
        {
            'w': round(W, 4),
            'd': round(D, 4),
            'h': round(H, 4),
            'post': round(max(0.04, _num(post, 0.12)), 4),
            'beams': beams,
        },
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        0.0,
        0.0,
        _mat(material, 'mat_timber'),
        name=name or 'pergola',
        grp=name or 'pergola',
    )
    return (
        f'pergola {o["id"]} over cells {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
        f'{W:g} x {D:g} m, {H:g} m to the rafters, {beams} rafters'
    )


def t_add_bracing(d: Drawing, a, wall_id, thickness=0.08, material='', name=''):
    w = d.find(str(wall_id))
    if not w or w['kind'] not in ('wall', 'partition'):
        return f'refused: {wall_id} is not a wall'
    L = _num(w['p'].get('len'), 4)
    H = _num(w['p'].get('h'), d.storey_h)
    if L < 0.5 or H < 0.5:
        return f'refused: wall {wall_id} is too small to brace ({L:g} x {H:g} m)'
    o = d.new(
        'bracing_x',
        {'w': round(L, 4), 'h': round(H, 4), 't': round(max(0.02, _num(thickness, 0.08)), 4)},
        w['x'],
        w['z'],
        w['y'],
        w['ry'],
        _mat(material, 'mat_steel'),
        name=name or f'bracing {wall_id}',
        grp=w['grp'] or (name or ''),
    )
    return f"bracing_x {o['id']} on wall {wall_id}: {L:.2f} m wide x {H:g} m high, on the wall's line at y {w['y']:g} m"


_CELLS = {'cell_from': {'type': 'string'}, 'cell_to': {'type': 'string'}}
_MAT = {'type': 'string', 'enum': MATERIALS}

TOOLS = [
    (
        {
            'name': 'add_column_grid',
            'description': 'A column at every intersection of a structural grid over a block of cells (both edges included), repeated per storey. Use for halls, car parks, framed floor plates.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'spacing_x': {'type': 'number'},
                        'spacing_z': {'type': 'number'},
                        'storeys': {'type': 'integer'},
                        'storey_from': {'type': 'integer'},
                        'kind': {'type': 'string', 'enum': list(COLUMN_KINDS)},
                        'size': {'type': 'number'},
                        'material': _MAT,
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_column_grid,
    ),
    (
        {
            'name': 'add_colonnade',
            'description': 'A row of columns along the line between two cell centres, every `spacing` metres with both ends included, and an I-beam over them. Use for porches, arcades, loggias, covered walks.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'spacing': {'type': 'number'},
                        'kind': {'type': 'string', 'enum': list(COLUMN_KINDS)},
                        'height': {'type': 'number'},
                        'beam': {'type': 'boolean'},
                        'size': {'type': 'number'},
                        'material': _MAT,
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_colonnade,
    ),
    (
        {
            'name': 'add_beam_grid',
            'description': 'I-beams under a storey slab across a block, spanning in x, in z or both, spaced `spacing` metres apart. Use when the user asks for a steel floor structure or exposed beams.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'spacing': {'type': 'number'},
                        'direction': {'type': 'string', 'enum': ['x', 'z', 'both']},
                        'depth': {'type': 'number'},
                        'width': {'type': 'number'},
                        'material': _MAT,
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_beam_grid,
    ),
    (
        {
            'name': 'add_portal_frames',
            'description': 'Evenly spaced portal frames (two columns and two rafters) across a block — the skeleton of a shed, warehouse, barn or hangar. The span is the block width in the frame direction.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'count': {'type': 'integer'},
                        'direction': {'type': 'string', 'enum': ['x', 'z']},
                        'eaves': {'type': 'number'},
                        'rise': {'type': 'number'},
                        'member_w': {'type': 'number'},
                        'member_d': {'type': 'number'},
                        'material': _MAT,
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_portal_frames,
    ),
    (
        {
            'name': 'add_pergola',
            'description': 'One pergola (four posts, edge beams and rafters) sized to a block of cells. Use for a garden pergola, a shaded terrace or a covered walk.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'height': {'type': 'number'},
                        'post': {'type': 'number'},
                        'material': _MAT,
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_pergola,
    ),
    (
        {
            'name': 'add_bracing',
            'description': 'An X brace sized to an existing wall and placed on its line. Use for wind bracing in a frame, a braced gable or an exposed steel facade.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'wall_id': {'type': 'string'},
                    'thickness': {'type': 'number'},
                    'material': _MAT,
                    'name': {'type': 'string'},
                },
                'required': ['wall_id'],
            },
        },
        t_add_bracing,
    ),
]

EXAMPLES = [
    {
        'ask': 'a column grid over C4 to N15, 6 m apart, three floors',
        'calls': [
            {
                'tool': 'add_column_grid',
                'args': {'cell_from': 'C4', 'cell_to': 'N15', 'spacing_x': 6, 'spacing_z': 6, 'storeys': 3},
            }
        ],
    },
    {
        'ask': 'a colonnade along the front from C4 to O4, columns every 3 m with a beam over them',
        'calls': [{'tool': 'add_colonnade', 'args': {'cell_from': 'C4', 'cell_to': 'O4', 'spacing': 3, 'height': 3.0}}],
    },
    {
        'ask': 'a warehouse frame over D10 to X33, five portal frames, 6 m to the eaves',
        'calls': [
            {
                'tool': 'add_portal_frames',
                'args': {'cell_from': 'D10', 'cell_to': 'X33', 'count': 5, 'eaves': 6, 'rise': 1.5},
            }
        ],
    },
    {
        'ask': 'steel beams under the first floor of C4..N15, both directions, 6 m apart',
        'calls': [
            {
                'tool': 'add_beam_grid',
                'args': {'cell_from': 'C4', 'cell_to': 'N15', 'storey': 1, 'spacing': 6, 'direction': 'both'},
            }
        ],
    },
    {
        'ask': 'a pergola over the terrace F20 to J24, 2.4 m high',
        'calls': [{'tool': 'add_pergola', 'args': {'cell_from': 'F20', 'cell_to': 'J24', 'height': 2.4}}],
    },
    {'ask': 'brace the back wall o12', 'calls': [{'tool': 'add_bracing', 'args': {'wall_id': 'o12'}}]},
]
