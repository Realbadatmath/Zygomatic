# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""civil_infrastructure — the assistant's civil-works tools.

Everything here is LINEAR: the work runs between two cells (or along a chain
of them), so `len` is the distance between the cell centres, `ry` comes from
the line exactly as draw_wall computes it, and the record sits at the
midpoint. Heights are metres above the ground, not storeys — a bridge deck 8 m
over a canal is `deck_height=8`, not "storey 3" — except draw_tunnel, which
takes a storey because a tunnel usually sits in the ground plane the rest of
the drawing uses.

Tools: draw_bridge, draw_tunnel, draw_dam, draw_jetty, draw_quay,
draw_embankment.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, parse_cell, cell_centre, cell_name, MATERIALS, _num, MAX_OBJECTS

KINDS = {
    'bridge_deck': {'len': 20, 'w': 8, 't': 0.8, 'edge': 0.5},
    'bridge_pier': {'w': 2, 'd': 6, 'h': 8},
    'bridge_arch': {'span': 20, 'rise': 5, 'w': 8, 't': 1.0, 'seg': 20},
    'tunnel': {'len': 20, 'w': 8, 'h': 6, 't': 0.5, 'seg': 12},
    'culvert': {'len': 10, 'r': 1, 't': 0.2, 'seg': 24},
    'dam': {'len': 40, 'h': 20, 't_base': 15, 't_top': 4},
    'quay_wall': {'len': 20, 'h': 4, 't': 1.2},
    'jetty': {'len': 12, 'w': 2.5, 'h': 1.5, 'posts': 3},
    'embankment': {'len': 20, 'w': 9, 'h': 3},
    'sluice': {'w': 6, 'h': 5, 'gate_h': 3, 't': 1.0},
}
OPENINGS: list = []

PROMPT = (
    'Civil works (infrastructure, never buildings): draw_bridge(cell_from, cell_to, width, deck_height, '
    'piers_every, kind) spans water or a road — one deck at deck_height with a pier every piers_every metres '
    'down to the ground, and kind="arch" adds an arch between each pair of piers; draw_tunnel(cell_from, '
    'cell_to, width, height, storey) bores an arched tunnel, open at both ends; draw_dam(cell_from, cell_to, '
    'height) sets a trapezoid gravity dam across a valley (base 0.75x the height); draw_quay(cells, height) '
    'walls a waterfront along a chain of cells, one segment per pair; draw_jetty(cell_from, cell_to, width) '
    'runs a jetty on posts out over water; draw_embankment(cell_from, cell_to, height, width) raises a '
    'triangular dyke (base 3x the height unless you give one). Use draw_wall or draw_box for buildings.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _line(cell_from, cell_to):
    """(start, end, length, ry) in world metres — the same convention as draw_wall."""
    c0 = cell_centre(*parse_cell(cell_from))
    c1 = cell_centre(*parse_cell(cell_to))
    L = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    ry = math.atan2(-(c1[1] - c0[1]), c1[0] - c0[0])
    return c0, c1, L, ry


def _at(c0, c1, L, u):
    """The world point u metres from c0 along the line."""
    if L < 1e-6:
        return c0
    return c0[0] + (c1[0] - c0[0]) * u / L, c0[1] + (c1[1] - c0[1]) * u / L


def _room_for(d: Drawing, n: int):
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} objects and the drawing may hold {MAX_OBJECTS} in total'
    return ''


def t_draw_bridge(
    d: Drawing, a, cell_from, cell_to, width=8.0, deck_height=8.0, piers_every=20.0, kind='beam', material='', name=''
):
    c0, c1, L, ry = _line(cell_from, cell_to)
    if L < 3:
        return 'refused: a bridge needs at least 3 m between the two cells'
    W = _num(width, 8.0)
    if W < 1 or W > 60:
        return 'refused: width must be between 1 and 60 m'
    H = _num(deck_height, 8.0)
    if H <= 0 or H > 200:
        return 'refused: deck_height must be between 0 and 200 m'
    if kind not in ('beam', 'arch'):
        return 'refused: kind must be "beam" or "arch"'
    every = max(4.0, _num(piers_every, 20.0))
    bays = max(1, int(round(L / every)))
    need = 1 + (bays + 1) + (bays if kind == 'arch' else 0)
    full = _room_for(d, need)
    if full:
        return full
    mat = _mat(material)
    grp = name or f'bridge {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mid = ((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2)
    deck = d.new(
        'bridge_deck',
        {'len': round(L, 4), 'w': round(W, 3), 't': 0.8, 'edge': 0.5},
        mid[0],
        mid[1],
        H,
        ry,
        mat,
        name='deck',
        grp=grp,
    )
    piers = []
    for i in range(bays + 1):
        px, pz = _at(c0, c1, L, L * i / bays)
        p = d.new(
            'bridge_pier',
            {'w': 2, 'd': round(max(1.0, W * 0.8), 3), 'h': round(H, 3)},
            px,
            pz,
            0.0,
            ry,
            mat,
            name=f'pier {i + 1}',
            grp=grp,
        )
        piers.append(p['id'])
    arches = []
    if kind == 'arch':
        span = L / bays
        rise = max(1.0, H - 1.0)
        for i in range(bays):
            ax, az = _at(c0, c1, L, span * (i + 0.5))
            o = d.new(
                'bridge_arch',
                {'span': round(span, 4), 'rise': round(rise, 3), 'w': round(W, 3), 't': 1.0, 'seg': 20},
                ax,
                az,
                0.0,
                ry,
                mat,
                name=f'arch {i + 1}',
                grp=grp,
            )
            arches.append(o['id'])
    return (
        f'drew {kind} bridge "{grp}": deck {deck["id"]} {L:.2f} m x {W:g} m at {H:g} m over '
        f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}, '
        f'{len(piers)} piers {piers[0]}..{piers[-1]} every {L / bays:.1f} m'
        + (f', {len(arches)} arches {arches[0]}..{arches[-1]}' if arches else '')
    )


def t_draw_tunnel(d: Drawing, a, cell_from, cell_to, width=8.0, height=6.0, storey=0, wall_t=0.5, material='', name=''):
    c0, c1, L, ry = _line(cell_from, cell_to)
    if L < 2:
        return 'refused: a tunnel needs at least 2 m between the two cells'
    W = _num(width, 8.0)
    H = _num(height, 6.0)
    if W < 1 or W > 40:
        return 'refused: width must be between 1 and 40 m'
    if H < W / 2 + 0.05 or H > 40:
        return f'refused: height must be between {W / 2 + 0.05:g} m (half the width, the arch) and 40 m'
    full = _room_for(d, 1)
    if full:
        return full
    y = int(_num(storey, 0)) * d.storey_h
    o = d.new(
        'tunnel',
        {'len': round(L, 4), 'w': round(W, 3), 'h': round(H, 3), 't': max(0.05, _num(wall_t, 0.5)), 'seg': 12},
        (c0[0] + c1[0]) / 2,
        (c0[1] + c1[1]) / 2,
        y,
        ry,
        _mat(material),
        name=name or 'tunnel',
        grp=name,
    )
    return (
        f'drew tunnel {o["id"]} {L:.2f} m long, {W:g} x {H:g} m section, from '
        f'{cell_name(*parse_cell(cell_from))} to {cell_name(*parse_cell(cell_to))} at storey '
        f'{int(_num(storey, 0))} (y {y:g} m), open at both ends'
    )


def t_draw_dam(d: Drawing, a, cell_from, cell_to, height=20.0, material='', name=''):
    c0, c1, L, ry = _line(cell_from, cell_to)
    if L < 3:
        return 'refused: a dam needs at least 3 m between the two cells'
    H = _num(height, 20.0)
    if H < 1 or H > 200:
        return 'refused: height must be between 1 and 200 m'
    full = _room_for(d, 1)
    if full:
        return full
    tb = round(H * 0.75, 3)
    tt = round(max(3.0, H * 0.2), 3)
    o = d.new(
        'dam',
        {'len': round(L, 4), 'h': round(H, 3), 't_base': tb, 't_top': tt},
        (c0[0] + c1[0]) / 2,
        (c0[1] + c1[1]) / 2,
        0.0,
        ry,
        _mat(material),
        name=name or 'dam',
        grp=name,
    )
    return (
        f'drew dam {o["id"]} {L:.2f} m long and {H:g} m high across '
        f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}, '
        f'{tb:g} m thick at the base and {tt:g} m at the crest'
    )


def t_draw_quay(d: Drawing, a, cells, height=4.0, thickness=1.2, material='', name=''):
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: draw_quay needs a list of at least two cells, like ["C10", "M10", "M20"]'
    if len(cells) > 60:
        return 'refused: at most 60 cells in one quay'
    H = _num(height, 4.0)
    if H < 0.5 or H > 40:
        return 'refused: height must be between 0.5 and 40 m'
    T = max(0.2, _num(thickness, 1.2))
    full = _room_for(d, len(cells) - 1)
    if full:
        return full
    grp = name or f'quay {cell_name(*parse_cell(cells[0]))}-{cell_name(*parse_cell(cells[-1]))}'
    mat = _mat(material)
    ids, total = [], 0.0
    for i in range(len(cells) - 1):
        c0, c1, L, ry = _line(cells[i], cells[i + 1])
        if L < 0.5:
            continue
        o = d.new(
            'quay_wall',
            {'len': round(L, 4), 'h': round(H, 3), 't': round(T, 3)},
            (c0[0] + c1[0]) / 2,
            (c0[1] + c1[1]) / 2,
            0.0,
            ry,
            mat,
            name=f'quay segment {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
        total += L
    if not ids:
        return 'refused: every pair of cells was the same cell — a quay needs cells that are apart'
    return (
        f'drew quay "{grp}": {len(ids)} segments {ids[0]}..{ids[-1]}, {total:.1f} m of wall '
        f'{H:g} m high and {T:g} m thick'
    )


def t_draw_jetty(d: Drawing, a, cell_from, cell_to, width=2.5, height=1.5, post_spacing=3.0, material='', name=''):
    c0, c1, L, ry = _line(cell_from, cell_to)
    if L < 2:
        return 'refused: a jetty needs at least 2 m between the two cells'
    W = _num(width, 2.5)
    if W < 0.6 or W > 20:
        return 'refused: width must be between 0.6 and 20 m'
    H = _num(height, 1.5)
    if H < 0.3 or H > 15:
        return 'refused: height must be between 0.3 and 15 m'
    full = _room_for(d, 1)
    if full:
        return full
    sp = max(1.0, _num(post_spacing, 3.0))
    o = d.new(
        'jetty',
        {'len': round(L, 4), 'w': round(W, 3), 'h': round(H, 3), 'posts': round(sp, 2)},
        (c0[0] + c1[0]) / 2,
        (c0[1] + c1[1]) / 2,
        0.0,
        ry,
        _mat(material, 'mat_timber'),
        name=name or 'jetty',
        grp=name,
    )
    return (
        f'drew jetty {o["id"]} {L:.2f} m out from {cell_name(*parse_cell(cell_from))} to '
        f'{cell_name(*parse_cell(cell_to))}, {W:g} m wide, deck {H:g} m up, posts every {sp:g} m'
    )


def t_draw_embankment(d: Drawing, a, cell_from, cell_to, height=3.0, width=None, material='', name=''):
    c0, c1, L, ry = _line(cell_from, cell_to)
    if L < 2:
        return 'refused: an embankment needs at least 2 m between the two cells'
    H = _num(height, 3.0)
    if H < 0.3 or H > 60:
        return 'refused: height must be between 0.3 and 60 m'
    W = _num(width, H * 3.0)
    if W < H:
        return f'refused: the base ({W:g} m) must be at least as wide as the embankment is high ({H:g} m)'
    full = _room_for(d, 1)
    if full:
        return full
    o = d.new(
        'embankment',
        {'len': round(L, 4), 'w': round(W, 3), 'h': round(H, 3)},
        (c0[0] + c1[0]) / 2,
        (c0[1] + c1[1]) / 2,
        0.0,
        ry,
        _mat(material, 'mat_grass'),
        name=name or 'embankment',
        grp=name,
    )
    return (
        f'drew embankment {o["id"]} {L:.2f} m long from {cell_name(*parse_cell(cell_from))} to '
        f'{cell_name(*parse_cell(cell_to))}, {H:g} m high on a {W:g} m base'
    )


_CELL = {'type': 'string'}
TOOLS = [
    (
        {
            'name': 'draw_bridge',
            'description': 'A bridge from one cell to another: one deck at deck_height metres with a pier every piers_every metres down to the ground. kind="arch" adds an arch between each pair of piers. Use for road, rail and foot bridges over water, roads or a valley.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'width': {'type': 'number'},
                    'deck_height': {'type': 'number'},
                    'piers_every': {'type': 'number'},
                    'kind': {'type': 'string', 'enum': ['beam', 'arch']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_bridge,
    ),
    (
        {
            'name': 'draw_tunnel',
            'description': "An arched tunnel bore between two cells, open at both ends: width and height are the outside section. storey places it in the drawing's storey plane (0 = ground).",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'wall_t': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_tunnel,
    ),
    (
        {
            'name': 'draw_dam',
            'description': 'A gravity dam across a valley or a river between two cells: trapezoid section, base 0.75x the height, crest the greater of 3 m and a fifth of the height.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_dam,
    ),
    (
        {
            'name': 'draw_quay',
            'description': 'A waterfront wall along a chain of cells — one straight segment between each pair. Use for canal sides, docks and harbour edges.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'thickness': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_draw_quay,
    ),
    (
        {
            'name': 'draw_jetty',
            'description': 'A jetty or landing stage on posts running from one cell out over the water to another.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'post_spacing': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_jetty,
    ),
    (
        {
            'name': 'draw_embankment',
            'description': 'A triangular embankment, dyke or bund between two cells: height at the crest, base 3x the height unless width is given.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_embankment,
    ),
]

EXAMPLES = [
    {
        'ask': 'a bridge over the canal from D20 to D44, 7 m wide, 6 m above the water',
        'calls': [
            {
                'tool': 'draw_bridge',
                'args': {'cell_from': 'D20', 'cell_to': 'D44', 'width': 7, 'deck_height': 6, 'piers_every': 12},
            }
        ],
    },
    {
        'ask': 'make it a brick arch bridge instead',
        'calls': [
            {
                'tool': 'draw_bridge',
                'args': {
                    'cell_from': 'D20',
                    'cell_to': 'D44',
                    'width': 7,
                    'deck_height': 6,
                    'piers_every': 12,
                    'kind': 'arch',
                    'material': 'mat_brick',
                },
            }
        ],
    },
    {
        'ask': 'a road tunnel under the dyke from A30 to N30, 9 m wide and 6 m high',
        'calls': [{'tool': 'draw_tunnel', 'args': {'cell_from': 'A30', 'cell_to': 'N30', 'width': 9, 'height': 6}}],
    },
    {
        'ask': 'quay walls 3 m high along the canal from C10 to M10 and on to M24',
        'calls': [{'tool': 'draw_quay', 'args': {'cells': ['C10', 'M10', 'M24'], 'height': 3}}],
    },
    {
        'ask': 'a little wooden jetty from M24 out to Q24',
        'calls': [
            {'tool': 'draw_jetty', 'args': {'cell_from': 'M24', 'cell_to': 'Q24', 'width': 2, 'material': 'mat_timber'}}
        ],
    },
    {
        'ask': 'a 4 m dyke along the north edge from A6 to AZ6',
        'calls': [{'tool': 'draw_embankment', 'args': {'cell_from': 'A6', 'cell_to': 'AZ6', 'height': 4}}],
    },
]
