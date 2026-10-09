# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_context — the assistant half of the Site context family (2026-09-07).

The five icons of arch_ext/site_context.js are st_bound (site boundary),
st_sat (aerial underlay), st_veg (planting), st_road (roads) and f_img (image
underlay). The model cannot click a canvas, so the three that DRAW get a
server-side twin here — set_site_boundary, plant_site_trees, draw_road — which does
the same arithmetic on the Drawing and returns the numbers in words. The two
that only change what is UNDER the drawing (st_sat, f_img) have no twin worth
having: their result is a picture, and the model presses the icon instead.

ONE new kind, `site_boundary` {pts, closed}: the survey line. It is VOID — the
tab draws a line loop with a peg every 5 m and an area label, and Blender
builds nothing at all. VOID_KINDS is exported for tests_arch_ext/test_all.py's
sweep to union in (that file is not ours to edit).

PLANTING IS THE SAME ARITHMETIC ON BOTH SIDES. `plant_site_trees` and the st_veg
icon place trees by the same three rules and in the same order, so a model that
asks for ten trees and an operator who presses the icon get plans that read
alike: at least 3 m between trunks, at least 1 m inside the boundary, and clear
of every building footprint by 1 m. The seed makes it repeatable.

GEOLOCATION IS THE DRAWING'S, NOT THE ICON'S. The latitude and longitude the
aerial needs live in doc.ext.light_sun, which is where the sun family keeps
them: whichever of the two is asked first writes them, and the other reads
them. set_geolocation() is here so the model can put them there in words.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, parse_cell, cell_centre, cell_name, cell_of, MAX_OBJECTS, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── the one new kind ─────────────────────────────────────────────────────────
KINDS = {
    'site_boundary': {'pts': [[-10, -10], [10, -10], [10, 10], [-10, 10]], 'closed': 1},
}
OPENINGS: list = []
# no solid in the tab, no mesh in Blender: tests_arch_ext/test_all.py's sweep
# must union this into its own VOID_KINDS.
VOID_KINDS = ['site_boundary']

MIN_TREE_SPACING = 3.0  # metres between trunks
EDGE_CLEAR = 1.0  # metres inside the boundary
BUILDING_CLEAR = 1.0  # metres round a building footprint

BUTTONS = ['st_bound', 'st_sat', 'st_veg', 'st_road', 'f_img']

PROMPT = (
    'SITE CONTEXT: set_site_boundary(cells, setback) draws the legal edge through the centres of 3 or more cells '
    'and reports the area; setback insets the buildable line. plant_site_trees(count, inside, query, seed) '
    'scatters trees inside "boundary" or "selection". draw_road(cells, width). set_geolocation(lat, lon, north) — '
    'the sun and the aerial read it. Icons st_bound, st_veg, st_road, st_sat {"zoom", "source"} and f_img '
    '{"data_url", "width_m"}. explain("site context") has the detail.'
)


# ── geometry, shared by the twins ────────────────────────────────────────────
def _ring(v):
    out = []
    for a in v or []:
        if isinstance(a, (list, tuple)) and len(a) >= 2:
            try:
                out.append([float(a[0]), float(a[1])])
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('non-numeric ring vertex %r skipped: %s', a, _exc)
                continue
    if len(out) > 3 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def _shoelace(pts):
    a = 0.0
    for i in range(len(pts)):
        j = i - 1
        a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
    return a / 2.0


def _area(pts):
    return abs(_shoelace(pts))


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def in_poly(x, z, pts) -> bool:
    """Ray cast — the same test arch_ext/site_context.js does in the tab."""
    inside = False
    for i in range(len(pts)):
        j = i - 1
        xi, zi = pts[i]
        xj, zj = pts[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            inside = not inside
    return inside


def _dist_to_edges(x, z, pts) -> float:
    best = float('inf')
    for i in range(len(pts)):
        ax, az = pts[i - 1]
        bx, bz = pts[i]
        dx, dz = bx - ax, bz - az
        dd = dx * dx + dz * dz
        t = 0.0 if dd < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / dd))
        best = min(best, math.hypot(x - (ax + dx * t), z - (az + dz * t)))
    return best


def offset_poly(pts, d):
    """Inset by d along each vertex bisector (the tab's offsetPoly, in Python)."""
    sign = 1.0 if _shoelace(pts) > 0 else -1.0
    n = len(pts)
    out = []

    def norm(a, b):
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz) or 1.0
        return (dz / L, -dx / L)

    for i in range(n):
        p, c, q = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        n1, n2 = norm(p, c), norm(c, q)
        bx, bz = n1[0] + n2[0], n1[1] + n2[1]
        L = math.hypot(bx, bz)
        if L < 1e-9:
            bx, bz = n1
            L = math.hypot(bx, bz) or 1.0
        cos_half = max(0.25, (n1[0] * bx + n1[1] * bz) / L)
        out.append([c[0] + sign * bx / L * d / cos_half, c[1] + sign * bz / L * d / cos_half])
    return out


def world_poly(rec) -> list:
    """A site_boundary record's pts in WORLD metres (position and ry applied)."""
    pts = _ring((rec.get('p') or {}).get('pts'))
    c, s = math.cos(rec.get('ry') or 0.0), math.sin(rec.get('ry') or 0.0)
    return [[rec['x'] + q[0] * c + q[1] * s, rec['z'] - q[0] * s + q[1] * c] for q in pts]


def boundary_of(d: Drawing):
    """The drawing's site boundary in world metres, or None. Setback polygons
    (meta.setback) are not the boundary — they are drawn off it."""
    recs = [o for o in d.objs if o['kind'] == 'site_boundary' and not (o.get('meta') or {}).get('setback')]
    return world_poly(recs[-1]) if recs else None


def _fmt_area(m2: float) -> str:
    if m2 >= 10000:
        return f'{m2 / 10000:.3f} ha ({m2:.0f} m2)'
    return f'{m2:.2f} m2' if m2 < 100 else f'{m2:.0f} m2'


def _cells_to_pts(cells):
    """Cell names to [x, z] centres. A name that is not a cell is skipped, so a
    typo shortens the polygon rather than raising at the model."""
    pts = []
    for c in cells or []:
        try:
            col, row = parse_cell(c)
        except ValueError as _exc:
            _zyg_log.debug('unparsable cell name %r skipped: %s', c, _exc)
            continue
        x, z = cell_centre(col, row)
        pts.append([x, z])
    return pts


def _named(cells):
    out = []
    for c in cells or []:
        try:
            out.append(cell_name(*parse_cell(c)))
        except ValueError as _exc:
            _zyg_log.debug('unparsable cell name %r skipped: %s', c, _exc)
            continue
    return out


def _footprints(d: Drawing):
    """Axis-aligned building boxes, grown by 1 m — what a tree must clear."""
    out = []
    for o in d.objs:
        p, kind = o.get('p') or {}, o['kind']
        if kind in ('slab', 'roof_flat', 'box', 'massing'):
            hw, hd = _num(p.get('w'), 0) / 2, _num(p.get('d'), 0) / 2
        elif kind in ('wall', 'partition'):
            L, t = _num(p.get('len'), 0) / 2, _num(p.get('t'), 0.2) / 2
            c, s = abs(math.cos(o.get('ry') or 0)), abs(math.sin(o.get('ry') or 0))
            hw, hd = L * c + t * s, L * s + t * c
        elif kind == 'slab_poly':
            pr = _ring(p.get('pts'))
            if not pr:
                continue
            hw = max(abs(q[0]) for q in pr)
            hd = max(abs(q[1]) for q in pr)
        else:
            continue
        if hw <= 0 and hd <= 0:
            continue
        out.append(
            (
                o['x'] - hw - BUILDING_CLEAR,
                o['z'] - hd - BUILDING_CLEAR,
                o['x'] + hw + BUILDING_CLEAR,
                o['z'] + hd + BUILDING_CLEAR,
            )
        )
    return out


def _mulberry(seed: int):
    """mulberry32, the tab's RNG. Every step is taken modulo 2^32 on the same
    bit patterns JavaScript's Math.imul and >>> work on, so both halves of the
    family draw the same stream for a seed."""
    a = seed & 0xFFFFFFFF or 1

    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rnd


# ── the tools ────────────────────────────────────────────────────────────────
def t_set_site_boundary(d: Drawing, a, cells, setback=None):
    pts = _cells_to_pts(cells)
    if len(pts) < 3:
        return 'refused: a site boundary needs at least three cells, in order round the plot'
    if len(d.objs) >= MAX_OBJECTS:
        return f'refused: the drawing already holds {MAX_OBJECTS} objects'
    cx, cz = _centroid(pts)
    local = [[round(q[0] - cx, 4), round(q[1] - cz, 4)] for q in pts]
    rec = d.new('site_boundary', {'pts': local, 'closed': 1}, cx, cz, grp='site')
    out = [
        f'Site boundary through {len(pts)} corners ({", ".join(_named(cells))}): '
        f'{_fmt_area(_area(pts))}, centred on {cell_of(cx, cz)}.'
    ]
    sb = _num(setback, 0)
    if sb > 0:
        inset = offset_poly(pts, sb)
        if _area(inset) < 0.01 or _area(inset) >= _area(pts):
            out.append(f'A {sb:g} m setback leaves nothing of this site — no setback line drawn.')
        else:
            icx, icz = _centroid(inset)
            sr = d.new(
                'site_boundary',
                {'pts': [[round(q[0] - icx, 4), round(q[1] - icz, 4)] for q in inset], 'closed': 1},
                icx,
                icz,
                grp='site',
                name=f'Setback {sb:g} m',
            )
            sr['meta'] = {'setback': sb}
            out.append(f'Setback {sb:g} m: buildable area {_fmt_area(_area(inset))}.')
    d.selected = [rec['id']]
    return ' '.join(out)


def t_plant_trees(d: Drawing, a, count=20, inside='boundary', query='tree', seed=20260907, species=None):
    count = max(1, min(500, int(_num(count, 20))))
    poly = None
    label = ''
    if str(inside) == 'selection':
        sel = [o for o in d.objs if o['id'] in (a.get('ids') or [])] if isinstance(a, dict) else []
        sel = sel or d.objs
        xs = [o['x'] for o in sel]
        zs = [o['z'] for o in sel]
        if not xs:
            return 'refused: nothing to plant around'
        pad = 5.0
        poly = [
            [min(xs) - pad, min(zs) - pad],
            [max(xs) + pad, min(zs) - pad],
            [max(xs) + pad, max(zs) + pad],
            [min(xs) - pad, max(zs) + pad],
        ]
        label = 'the selection'
    else:
        poly = boundary_of(d)
        label = 'the site boundary'
    if not poly or len(poly) < 3:
        return (
            'refused: there is no site boundary to plant inside — draw one with set_site_boundary first, '
            'or pass inside="selection"'
        )

    kind = 'tree'
    p = {'h': 6.0, 'r_can': 2.0, 'r_trunk': 0.18}
    q = str(species or query or '').lower()
    if 'small' in q or 'shrub' in q:
        p = {'h': 3.0, 'r_can': 1.2, 'r_trunk': 0.1}
    elif 'large' in q or 'oak' in q or 'mature' in q:
        p = {'h': 12.0, 'r_can': 5.0, 'r_trunk': 0.4}

    xs = [q0[0] for q0 in poly]
    zs = [q0[1] for q0 in poly]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    boxes = _footprints(d)
    rnd = _mulberry(int(_num(seed, 20260907)))
    placed = []
    tries = 0
    while len(placed) < count and tries < count * 400:
        tries += 1
        x = x0 + rnd() * (x1 - x0)
        z = z0 + rnd() * (z1 - z0)
        if not in_poly(x, z, poly):
            continue
        if _dist_to_edges(x, z, poly) < EDGE_CLEAR:
            continue
        if any(b[0] <= x <= b[2] and b[1] <= z <= b[3] for b in boxes):
            continue
        if any(math.hypot(x - px, z - pz) < MIN_TREE_SPACING for px, pz in placed):
            continue
        placed.append((x, z))
    if not placed:
        return f'refused: no room for a tree inside {label} that clears the buildings at {MIN_TREE_SPACING:g} m spacing'
    if len(d.objs) + len(placed) > MAX_OBJECTS:
        return f'refused: {len(placed)} more trees would take the drawing past {MAX_OBJECTS} objects'
    ids = []
    for x, z in placed:
        r = d.new(kind, p, round(x, 3), round(z, 3), 0.0, ry=rnd() * math.tau, mat='mat_grass', grp='planting')
        ids.append(r['id'])
    d.selected = ids
    # When fewer trees fit than were asked for, say how big the plot actually is:
    # a model that only hears "would not fit" asks again for the same number,
    # whereas the area tells it whether to plant fewer or widen the boundary.
    short = (
        ''
        if len(placed) == count
        else f' (asked for {count}; the rest would not fit at {MIN_TREE_SPACING:g} m spacing '
        f'inside {_fmt_area(_area(poly))})'
    )
    return (
        f'Planted {len(ids)} trees {p["h"]:g} m tall inside {label}{short}. '
        f'Trunks at least {MIN_TREE_SPACING:g} m apart, {EDGE_CLEAR:g} m inside the edge and clear of '
        f'{len(boxes)} building footprints. Group "planting".'
    )


def t_draw_road(d: Drawing, a, cells, width=6.0):
    pts = _cells_to_pts(cells)
    if len(pts) < 2:
        return 'refused: a road needs at least two cells'
    w = max(0.5, min(60.0, _num(width, 6.0)))
    if len(d.objs) + len(pts) - 1 > MAX_OBJECTS:
        return f'refused: that road would take the drawing past {MAX_OBJECTS} objects'
    ids, total = [], 0.0
    for i in range(1, len(pts)):
        ax, az = pts[i - 1]
        bx, bz = pts[i]
        length = math.hypot(bx - ax, bz - az)
        if length < 1e-3:
            continue
        r = d.new(
            'road',
            {'len': round(length, 4), 'w': w, 't': 0.08},
            (ax + bx) / 2,
            (az + bz) / 2,
            0.0,
            ry=math.atan2(-(bz - az), bx - ax),
            mat='mat_asphalt',
            grp='roads',
        )
        ids.append(r['id'])
        total += length
    if not ids:
        return 'refused: those cells are all the same place'
    d.selected = ids
    return (
        f'Drew {len(ids)} road leg{"" if len(ids) == 1 else "s"}, {total:.2f} m in all at {w:g} m wide '
        f'({total * w:.0f} m2 of carriageway). Group "roads".'
    )


def t_set_geolocation(d: Drawing, a, lat, lon, north=None):
    la, lo = _num(lat, None), _num(lon, None)
    if la is None or lo is None or not (-90 <= la <= 90) or not (-180 <= lo <= 180):
        return 'refused: latitude must be -90..90 and longitude -180..180, in decimal degrees'
    sun = d.ext.get('light_sun')
    sun = dict(sun) if isinstance(sun, dict) else {}
    sun['lat'] = round(la, 6)
    sun['lon'] = round(lo, 6)
    if north is not None:
        sun['north'] = round(_num(north, 0.0) % 360.0, 3)
    d.ext['light_sun'] = sun
    mpp = 156543.03392804097 * math.cos(math.radians(la)) / (2**18)
    return (
        f'Drawing pinned to {la:.5f}, {lo:.5f}'
        + (f' with north at {sun["north"]:g} deg' if north is not None else '')
        + f'. The sun and the aerial underlay both read this. At zoom 18 one map pixel is {mpp:.2f} m here, '
        f'so a 3x3 tile mosaic covers {mpp * 256 * 3:.0f} m across.'
    )


_CELLS = {'type': 'array', 'items': {'type': 'string'}}

TOOLS = [
    (
        {
            'name': 'set_site_boundary',
            'description': 'Draw the site boundary through the centres of the cells named, in order round the plot, '
            'and report its area. setback also insets a second line that many metres in — the '
            'buildable area. This is the polygon plant_site_trees fills.',
            'input_schema': {
                'type': 'object',
                'properties': {'cells': _CELLS, 'setback': {'type': 'number'}},
                'required': ['cells'],
            },
        },
        t_set_site_boundary,
    ),
    (
        {
            'name': 'plant_site_trees',
            'description': 'Scatter trees INSIDE the site boundary or the selection: inside "boundary" fills the '
            'site boundary, "selection" a box round the objects. Trunks are at least 3 m apart, 1 m '
            'inside the edge and 1 m clear of every building. Repeatable for a given seed. For a '
            'rectangular block of cells use plant_trees.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'count': {'type': 'integer'},
                    'inside': {'type': 'string', 'enum': ['boundary', 'selection']},
                    'query': {'type': 'string'},
                    'species': {'type': 'string'},
                    'seed': {'type': 'integer'},
                },
                'required': [],
            },
        },
        t_plant_trees,
    ),
    (
        {
            'name': 'draw_road',
            'description': 'Chain a road through the cells named: one road record per leg, width metres wide '
            '(6 m by default). Use it for an access road, a drive or a lane across the site.',
            'input_schema': {
                'type': 'object',
                'properties': {'cells': _CELLS, 'width': {'type': 'number'}},
                'required': ['cells'],
            },
        },
        t_draw_road,
    ),
    (
        {
            'name': 'set_geolocation',
            'description': 'Pin the drawing to a real latitude and longitude (and optionally the north angle). The '
            'sun and the aerial map underlay both read it. Do this before turning the aerial on.',
            'input_schema': {
                'type': 'object',
                'properties': {'lat': {'type': 'number'}, 'lon': {'type': 'number'}, 'north': {'type': 'number'}},
                'required': ['lat', 'lon'],
            },
        },
        t_set_geolocation,
    ),
]

EXAMPLES = [
    {
        'ask': 'set the site boundary to B2, H2, H8, B8 with a 5 m setback',
        'calls': [{'tool': 'set_site_boundary', 'args': {'cells': ['B2', 'H2', 'H8', 'B8'], 'setback': 5}}],
    },
    {
        'ask': 'plant twenty trees on the site',
        'calls': [{'tool': 'plant_site_trees', 'args': {'count': 20, 'inside': 'boundary'}}],
    },
    {
        'ask': 'run a 6 m access road from A5 across to M5 and up to M12',
        'calls': [{'tool': 'draw_road', 'args': {'cells': ['A5', 'M5', 'M12'], 'width': 6}}],
    },
    {
        'ask': 'the site is in Amsterdam — put an aerial photo under the drawing',
        'calls': [
            {'tool': 'set_geolocation', 'args': {'lat': 52.3702, 'lon': 4.8952}},
            {'tool': 'press_button', 'args': {'id': 'st_sat', 'args': {'source': 'esri', 'zoom': 18}}},
        ],
    },
    {'ask': 'let me trace the survey drawing I scanned', 'calls': [{'tool': 'press_button', 'args': {'id': 'f_img'}}]},
]
