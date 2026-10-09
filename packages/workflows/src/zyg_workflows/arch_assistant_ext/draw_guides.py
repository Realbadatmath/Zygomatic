# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""draw_guides — the assistant half of the three drafting guide modes.

The tab's Arc, Polygon and Freehand icons are POINTER MODES: they need a
pointer, and the model has no pointer. So there are no BUTTONS here — pressing
a mode from the assistant would arm a tool nobody can click. Instead each mode
gets a server-side TWIN that draws the same record from cells the user names,
so "put a guide arc through F8, K8 and H5" works in words as well as in clicks.

Three kinds, all of them VOID (line-only in the tab, no geometry in Blender):
    guide_arc   p {x1, z1, x2, z2, x3, z3}  three points, metres, local to the
                record — the record sits on the FIRST point, so x1 = z1 = 0,
                and the circle through the three is derived by the geometry.
    guide_poly  p {pts: [[x, z], ...]}      a closed ring, local to pts[0].
    guide_path  p {pts: [[x, z], ...]}      an open polyline, local to pts[0].

Only the standard library is used.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import MAX_OBJECTS, Drawing, _num, cell_centre, cell_name, parse_cell

KINDS = {
    'guide_arc': {'x1': 0.0, 'z1': 0.0, 'x2': -3.0, 'z2': -3.0, 'x3': -0.8787, 'z3': -2.1213},
    'guide_poly': {'pts': [[0, 0], [4, 0], [4, 4], [0, 4]]},
    'guide_path': {'pts': [[0, 0], [2, 1], [4, 0]]},
}
OPENINGS: list = []

# A guide is drawn, never built: the tab shows a cyan line and Blender skips it.
# tests_arch_ext/test_all.py's sweep unions this into its own VOID_KINDS.
VOID_KINDS = ['guide_arc', 'guide_poly', 'guide_path']

# Modes cannot be pressed usefully from a chat — there is no pointer to click.
BUTTONS: list = []

PROMPT = (
    'Drafting guides (line-only, nothing is built from them): draw_guide_arc(cells=[start, end, '
    'a cell the arc passes through]) lays a three-point arc; draw_guide_polygon(cells=[3 or more '
    'cells in order]) lays a closed ring through those cell centres, and with sides=3..12 plus a '
    'single centre cell and radius it lays a regular polygon instead; draw_guide_path(cells=[2 or '
    'more cells in order]) lays an open polyline. Use them for setting-out lines, sight lines, '
    'sweep radii and site outlines — for a wall that curves use draw_curved_wall, for a floor plate '
    "use add_polygon_slab. At the pointer the same three guides are the side bar's Arc, Polygon "
    'and Freehand tools.'
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _points(cells, least, what):
    """['C4', ...] -> [(x, z), ...] cell centres, repeats dropped."""
    if not isinstance(cells, (list, tuple)):
        raise ValueError('cells must be a list of cell names in order, like ["C4", "L4", "L13"]')
    out: list = []
    for c in cells:
        x, z = cell_centre(*parse_cell(c))
        if not out or math.hypot(x - out[-1][0], z - out[-1][1]) > 1e-6:
            out.append((x, z))
    if len(out) < least:
        raise ValueError(f'{what} needs at least {least} different cells — got {len(out)}')
    if len(out) > 400:
        raise ValueError('at most 400 points in one guide')
    return out


def _local(pts):
    ax, az = pts[0]
    return [[round(x - ax, 4), round(z - az, 4)] for x, z in pts]


def _arc_radius(p1, p2, p3):
    """(radius, arc length) of the circle through three plan points, or
    (None, chord length) when they are collinear. Reporting only — the drawn
    geometry is derived in arch_ext/draw_guides.js from the same three points."""
    (x1, z1), (x2, z2), (x3, z3) = p1, p2, p3
    d = 2 * (x1 * (z2 - z3) + x2 * (z3 - z1) + x3 * (z1 - z2))
    if abs(d) < 1e-9:
        return None, math.hypot(x2 - x1, z2 - z1)
    s1, s2, s3 = x1 * x1 + z1 * z1, x2 * x2 + z2 * z2, x3 * x3 + z3 * z3
    cx = (s1 * (z2 - z3) + s2 * (z3 - z1) + s3 * (z1 - z2)) / d
    cz = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = math.hypot(x1 - cx, z1 - cz)
    tau = 2 * math.pi
    a1 = math.atan2(z1 - cz, x1 - cx)

    def wrap(a):
        return (a - a1) % tau

    da, d3 = wrap(math.atan2(z2 - cz, x2 - cx)), wrap(math.atan2(z3 - cz, x3 - cx))
    sweep = da if d3 <= da else da - tau
    return r, abs(sweep) * r


def _room(d: Drawing):
    if len(d.objs) >= MAX_OBJECTS:
        raise ValueError(f'the drawing already holds {MAX_OBJECTS} objects — that is the ceiling')


# ── the tools ───────────────────────────────────────────────────────────────
def t_draw_guide_arc(d: Drawing, a, cells, storey=0, name=''):
    _room(d)
    pts = _points(cells, 3, 'a three-point arc')[:3]
    if len(pts) < 3:
        return 'refused: a three-point arc needs three different cells: start, end, and one the arc passes through'
    lp = _local(pts)
    p = {'x1': lp[0][0], 'z1': lp[0][1], 'x2': lp[1][0], 'z2': lp[1][1], 'x3': lp[2][0], 'z3': lp[2][1]}
    st = int(_num(storey, 0))
    rec = d.new('guide_arc', p, pts[0][0], pts[0][1], st * d.storey_h, 0.0, 'mat_glass', name=name or None, grp=name)
    r, L = _arc_radius((0.0, 0.0), (p['x2'], p['z2']), (p['x3'], p['z3']))
    shape = f'radius {r:.2f} m' if r is not None else 'straight (the three cells are in line)'
    return (
        f'guide arc {rec["id"]} from {cell_name(*parse_cell(cells[0]))} to {cell_name(*parse_cell(cells[1]))} '
        f'through {cell_name(*parse_cell(cells[2]))} at storey {st}: {shape}, {L:.2f} m long. '
        'It is a guide — a line to draw to, nothing is built from it.'
    )


def t_draw_guide_polygon(d: Drawing, a, cells, sides=0, radius=6.0, storey=0, name=''):
    _room(d)
    n = int(_num(sides, 0))
    st = int(_num(storey, 0))
    if n:
        if n < 3 or n > 12:
            return 'refused: a regular guide polygon has 3 to 12 sides — for more corners list the cells instead'
        r = _num(radius, 6.0)
        if r < 0.05 or r > 500:
            return 'refused: radius must be between 0.05 and 500 m'
        centre = cells[0] if isinstance(cells, (list, tuple)) and cells else cells
        cx, cz = cell_centre(*parse_cell(centre))
        pts = [(cx + r * math.cos(2 * math.pi * k / n), cz - r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        what = f'regular {n}-gon, radius {r:g} m around {cell_name(*parse_cell(centre))}'
    else:
        pts = _points(cells, 3, 'a guide polygon')
        what = f'{len(pts)} corners through {len(pts)} cells'
    rec = d.new(
        'guide_poly',
        {'pts': _local(pts)},
        pts[0][0],
        pts[0][1],
        st * d.storey_h,
        0.0,
        'mat_glass',
        name=name or None,
        grp=name,
    )
    per = 0.0
    for i in range(len(pts)):
        bx, bz = pts[(i + 1) % len(pts)]
        per += math.hypot(bx - pts[i][0], bz - pts[i][1])
    return (
        f'guide polygon {rec["id"]} at storey {st}: {what}, {per:.2f} m round. '
        'It is a closed guide ring — a line to draw to, nothing is built from it.'
    )


def t_draw_guide_path(d: Drawing, a, cells, storey=0, name=''):
    _room(d)
    pts = _points(cells, 2, 'a guide path')
    st = int(_num(storey, 0))
    rec = d.new(
        'guide_path',
        {'pts': _local(pts)},
        pts[0][0],
        pts[0][1],
        st * d.storey_h,
        0.0,
        'mat_glass',
        name=name or None,
        grp=name,
    )
    L = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    return (
        f'guide path {rec["id"]} at storey {st}: {len(pts)} points, {L:.2f} m long, '
        f'from {cell_name(*parse_cell(cells[0]))}. '
        'It is an open guide line — a line to draw to, nothing is built from it.'
    )


TOOLS = [
    (
        {
            'name': 'draw_guide_arc',
            'description': 'A three-point guide arc: give exactly three cells — where the arc starts, where it ends, '
            'and one cell it passes through. Line only, nothing is built from it. The pointer twin is '
            "the side bar's Arc tool.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '[start, end, a cell on the arc], e.g. ["F8","K8","H5"]',
                    },
                    'storey': {'type': 'integer'},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_draw_guide_arc,
    ),
    (
        {
            'name': 'draw_guide_polygon',
            'description': 'A closed guide ring through the cells you list, in order round the outline (3 or more). '
            'With sides=3..12 give ONE centre cell and a radius instead and it lays a regular polygon. '
            "Line only, nothing is built from it. The pointer twin is the side bar's Polygon tool.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'corners in order, or a single centre cell when sides is given',
                    },
                    'sides': {'type': 'integer', 'description': '3..12 for a regular polygon around cells[0]'},
                    'radius': {'type': 'number', 'description': 'centre-to-corner metres, with sides'},
                    'storey': {'type': 'integer'},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_draw_guide_polygon,
    ),
    (
        {
            'name': 'draw_guide_path',
            'description': 'An open guide polyline through the cells you list, in order (2 or more) — a sight line, a '
            'route, a setting-out run. Line only, nothing is built from it. The pointer twin is the side '
            "bar's Freehand tool.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'storey': {'type': 'integer'},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_draw_guide_path,
    ),
]

EXAMPLES = [
    {
        'ask': 'draw a guide arc from F8 round through H5 to K8',
        'calls': [{'tool': 'draw_guide_arc', 'args': {'cells': ['F8', 'K8', 'H5']}}],
    },
    {
        'ask': 'set out a hexagon guide 5 m across around K12',
        'calls': [{'tool': 'draw_guide_polygon', 'args': {'cells': ['K12'], 'sides': 6, 'radius': 2.5}}],
    },
    {
        'ask': 'a guide outline through C4, L4, L13 and C13',
        'calls': [{'tool': 'draw_guide_polygon', 'args': {'cells': ['C4', 'L4', 'L13', 'C13']}}],
    },
    {
        'ask': 'sketch a guide line for the path from B2 to F6 to K5',
        'calls': [{'tool': 'draw_guide_path', 'args': {'cells': ['B2', 'F6', 'K5']}}],
    },
]
