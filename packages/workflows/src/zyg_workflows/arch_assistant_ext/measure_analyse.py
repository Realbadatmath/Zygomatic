# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_analyse — the assistant's read-the-drawing tools.

Everything here is computed from the RECORDS, never from geometry: a wall's
face area is len*h and its volume len*h*t, a slab's area is w*d (slab_poly:
the shoelace of its pts), a box's footprint is w*d, a window's glass area is
w*h. Nothing is meshed, so the numbers are exact for the parameters and cost
nothing.

FOOTPRINT (the one estimate). For occupancy — what_is_at, find_free_cells and
area — a record's footprint is the AXIS-ALIGNED rectangle its size parameters
imply (len/w/d/r) around its x,z. The record's rotation ry is IGNORED: a wall
turned 45 degrees reads as its unrotated box. Every tool that uses it says so
in its answer, so the model never quotes it as a survey. A record with no size
parameter at all falls back to half a LIVE cell (0.5 m at 1 m cells, 2.5 m at
5 m), so it still occupies its cell whatever the drawing's scale.

Two tools draw: annotate() drops an `annotation` pin whose NAME is the text,
dimension() draws a `dimension` line between two cells. The other ten only
read.

GRID SCALE. A cell is cell_size() metres and the A1 corner sits at
cell_origin() — both are per-DRAWING values that arch_assistant installs for
the length of a tool call, so find_free_cells and footprint read them at USE
time and never cache a module default. At 5 m cells the field runs from -750 m
and one cell of the occupancy map is 25 m². The other cell-to-metre paths here
(measure, what_is_at, bounds, annotate, dimension) go through cell_centre /
cell_of / parse_cell, which read the same live values.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    cell_of,
    storey_of,
    cell_size,
    cell_origin,
    MATERIALS,
    MAX_OBJECTS,
    _num,
)

KINDS = {
    'annotation': {'h': 1.5, 'r': 0.15},
    'dimension': {'len': 5.0, 'tick': 0.3},
}
OPENINGS: list = []

PROMPT = (
    'Measure & analyse (these read the drawing; only the last two add objects): measure(cell_a, cell_b) is the '
    'distance between two cells; bounds(which) the cells and storeys something spans; count(which) how many of each '
    'kind; list_storeys(which) the objects per storey; what_is_at(cell, storey) which records cover a cell. '
    'area(which) is the footprint in m2, floor_area(which) the gross floor area per storey from the slabs, '
    'volume(which) the m3 of solid, bom(which) a short bill of materials (wall m2, glass m2, concrete m3, counts). '
    'find_free_cells(cell_from, cell_to, min_w_cells, min_d_cells) returns the first empty rectangle inside a block — '
    'use it before placing a new building. annotate(cell, text) drops a labelled pin and dimension(cell_a, cell_b) '
    "draws a measured line. All figures come from the records' numbers; footprints ignore rotation."
)

WALLS = ('wall', 'partition')
GLASSY = ('window', 'window_strip', 'window_bay', 'window_round', 'window_arch', 'curtain_wall')
SLABS = ('slab', 'slab_poly')


# ── geometry of a record, from its parameters only ──────────────────────────
def _p(o, key, default=0.0):
    return _num((o.get('p') or {}).get(key), default)


def _shoelace(pts) -> float:
    """Area of a closed polygon given as [[x, z], ...] in m²."""
    try:
        n = len(pts)
    except TypeError:
        return 0.0
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        ax, az = _num(pts[i][0], 0.0), _num(pts[i][1], 0.0)
        bx, bz = _num(pts[(i + 1) % n][0], 0.0), _num(pts[(i + 1) % n][1], 0.0)
        s += ax * bz - bx * az
    return abs(s) / 2.0


def footprint(o: dict):
    """(x0, z0, x1, z1) in metres — the axis-aligned rectangle the record's
    size parameters imply around its x,z. ry is ignored (see the module note).
    Returns None for a record with nothing to measure."""
    p = o.get('p') or {}
    w = d = 0.0
    if o['kind'] == 'slab_poly' and isinstance(p.get('pts'), list) and len(p['pts']) >= 3:
        xs = [_num(q[0], 0.0) for q in p['pts']]
        zs = [_num(q[1], 0.0) for q in p['pts']]
        return (o['x'] + min(xs), o['z'] + min(zs), o['x'] + max(xs), o['z'] + max(zs))
    if 'len' in p:
        w = _p(o, 'len')
        d = _p(o, 't', 0.0) or _p(o, 'w', 0.0) or _p(o, 'tick', 0.0) or 0.2
    elif 'span' in p:
        w, d = _p(o, 'span'), (_p(o, 'w', 0.0) or 0.2)
    elif 'w' in p and 'd' in p:
        w, d = _p(o, 'w'), _p(o, 'd')
    elif 'r' in p:
        w = d = 2 * _p(o, 'r')
    elif 'w' in p:
        w, d = _p(o, 'w'), (_p(o, 't', 0.0) or 0.2)
    if w <= 0 or d <= 0:
        w = d = 0.5 * cell_size()  # half a LIVE cell, so a point-ish record still
        #                                              occupies its cell at 1, 2, 5 or 10 m (0.5 at 1 m)
    return (o['x'] - w / 2, o['z'] - d / 2, o['x'] + w / 2, o['z'] + d / 2)


def plan_area(o: dict) -> float:
    """The record's own footprint area in m² (slab_poly: the true polygon)."""
    p = o.get('p') or {}
    if o['kind'] == 'slab_poly' and isinstance(p.get('pts'), list):
        a = _shoelace(p['pts'])
        if a > 0:
            return a
    r = footprint(o)
    return (r[2] - r[0]) * (r[3] - r[1]) if r else 0.0


def face_area(o: dict) -> float:
    """The vertical face area in m² — a wall's len*h, a window's w*h, 0 for flat things."""
    p = o.get('p') or {}
    if 'len' in p and 'h' in p:
        return _p(o, 'len') * _p(o, 'h')
    if 'w' in p and 'h' in p and 'd' not in p:
        return _p(o, 'w') * _p(o, 'h')
    return 0.0


def solid_volume(o: dict) -> float:
    """m³ of solid, from the parameters. 0 for records that are not a volume."""
    k, p = o['kind'], (o.get('p') or {})
    if k in ('annotation', 'dimension', 'guide_line', 'guide_circle', 'plane', 'disc'):
        return 0.0  # markers and guides are not material
    if k in WALLS or ('len' in p and 'h' in p and ('t' in p or 'w' in p)):
        return _p(o, 'len') * _p(o, 'h') * (_p(o, 't', 0.0) or _p(o, 'w', 0.0))
    if k == 'slab_poly':
        return _shoelace(p.get('pts') or []) * (_p(o, 't', 0.2) or 0.2)
    if 'w' in p and 'd' in p:
        return _p(o, 'w') * _p(o, 'd') * (_p(o, 'h', 0.0) or _p(o, 't', 0.0))
    if 'r' in p and 'h' in p:
        v = math.pi * _p(o, 'r') ** 2 * _p(o, 'h')
        return v / 3.0 if k in ('cone', 'pyramid', 'spire') else v
    if k == 'sphere':
        return 4.0 / 3.0 * math.pi * _p(o, 'r') ** 3
    return 0.0


# ── the union of a set of axis-aligned rectangles ───────────────────────────
def union_area(rects: list) -> float:
    """Exact area of the union, by x-slab sweep with z-interval merging."""
    rects = [r for r in rects if r and r[2] > r[0] and r[3] > r[1]]
    if not rects:
        return 0.0
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    total = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        dx = x1 - x0
        if dx <= 1e-9:
            continue
        spans = sorted((r[1], r[3]) for r in rects if r[0] <= x0 + 1e-9 and r[2] >= x1 - 1e-9)
        cur, cov = None, 0.0
        for a, b in spans:
            if cur is None:
                cur = [a, b]
            elif a <= cur[1]:
                cur[1] = max(cur[1], b)
            else:
                cov += cur[1] - cur[0]
                cur = [a, b]
        if cur:
            cov += cur[1] - cur[0]
        total += dx * cov
    return total


UNION_MAX = 1500  # past this the sweep is O(n^2) and not worth the wait


def _pick(d: Drawing, which):
    recs = d.select(which if which not in (None, '') else 'all')
    return recs


def _kind_tally(recs) -> str:
    t: dict = {}
    for o in recs:
        t[o['kind']] = t.get(o['kind'], 0) + 1
    return ', '.join(f'{k} {v}' for k, v in sorted(t.items(), key=lambda kv: (-kv[1], kv[0])))


def _empty(which):
    return f'nothing matches "{which}" — pass "all", "new", a kind, a group name or ids'


# ── the tools ───────────────────────────────────────────────────────────────
def t_measure(d: Drawing, a, cell_a, cell_b):
    ca, cb = parse_cell(cell_a), parse_cell(cell_b)
    ax, az = cell_centre(*ca)
    bx, bz = cell_centre(*cb)
    dist = math.hypot(bx - ax, bz - az)
    return (
        f'{cell_name(*ca)} to {cell_name(*cb)}: {dist:.2f} m centre to centre '
        f'(dx {abs(bx - ax):.2f} m, dz {abs(bz - az):.2f} m; {abs(cb[0] - ca[0])} columns, '
        f'{abs(cb[1] - ca[1])} rows apart)'
    )


def t_bounds(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    xs0 = min(footprint(o)[0] for o in recs)
    zs0 = min(footprint(o)[1] for o in recs)
    xs1 = max(footprint(o)[2] for o in recs)
    zs1 = max(footprint(o)[3] for o in recs)
    sts = [storey_of(o['y'], d.storey_h) for o in recs]
    ys = [o['y'] for o in recs]
    return (
        f'{len(recs)} objects span cells {cell_of(xs0, zs0)}..{cell_of(xs1 - 1e-6, zs1 - 1e-6)} '
        f'({xs1 - xs0:.2f} x {zs1 - zs0:.2f} m), storeys {min(sts)}..{max(sts)} '
        f'(base y {min(ys):.2f}..{max(ys):.2f} m). Footprints ignore rotation.'
    )


def t_count(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    grps = sorted({o['grp'] for o in recs if o['grp']})
    return f'{len(recs)} objects: {_kind_tally(recs)}' + (f'; groups: {", ".join(grps[:12])}' if grps else '')


def t_list_storeys(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    by: dict = {}
    for o in recs:
        by.setdefault(storey_of(o['y'], d.storey_h), []).append(o)
    parts = [f'st{s} {len(v)} objects ({_kind_tally(v)})' for s, v in sorted(by.items())]
    return f'{len(by)} storeys of {d.storey_h:g} m — ' + '; '.join(parts)


def t_what_is_at(d: Drawing, a, cell, storey=None):
    c, r = parse_cell(cell)
    cx, cz = cell_centre(c, r)
    recs = d.objs if storey is None else [o for o in d.objs if storey_of(o['y'], d.storey_h) == int(_num(storey, 0))]
    hits = []
    for o in recs:
        f = footprint(o)
        if f and f[0] <= cx <= f[2] and f[1] <= cz <= f[3]:
            hits.append(o)
    if not hits:
        return f'nothing at {cell_name(c, r)}' + ('' if storey is None else f' on storey {int(_num(storey, 0))}')
    out = [
        f'{o["id"]} {o["kind"]} st{storey_of(o["y"], d.storey_h)}' + (f' grp:{o["grp"]}' if o['grp'] else '')
        for o in hits[:40]
    ]
    return (
        f'{len(hits)} records cover {cell_name(c, r)}: '
        + '; '.join(out)
        + (f' ... and {len(hits) - 40} more' if len(hits) > 40 else '')
        + ' (footprints ignore rotation)'
    )


def t_area(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    rects = [footprint(o) for o in recs]
    if len(rects) > UNION_MAX:
        tot = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
        return (
            f'footprint of {len(recs)} objects: {tot:.2f} m² — SUM of the footprints, not their union '
            f'(over {UNION_MAX} objects the union is not computed); overlaps are counted twice.'
        )
    tot = union_area(rects)
    return (
        f'footprint of {len(recs)} objects: {tot:.2f} m² (union of their footprints on the ground; '
        f'rotation is ignored, so a turned record reads as its unrotated box)'
    )


def t_floor_area(d: Drawing, a, which='all'):
    recs = [o for o in _pick(d, which) if o['kind'] in SLABS]
    if not recs:
        return 'gross floor area 0.00 m² — no slabs match; floor area is the sum of the slab areas, so add slabs first'
    by: dict = {}
    for o in recs:
        by[storey_of(o['y'], d.storey_h)] = by.get(storey_of(o['y'], d.storey_h), 0.0) + plan_area(o)
    tot = sum(by.values())
    per = ', '.join(f'st{s} {v:.2f}' for s, v in sorted(by.items()))
    return f'gross floor area {tot:.2f} m² over {len(by)} storeys from {len(recs)} slabs — {per} (m² each)'


def t_volume(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    by: dict = {}
    for o in recs:
        v = solid_volume(o)
        if v > 0:
            by[o['kind']] = by.get(o['kind'], 0.0) + v
    tot = sum(by.values())
    if not by:
        return f'volume of {len(recs)} objects: 0.00 m³ — none of them is a solid with thickness'
    per = ', '.join(f'{k} {v:.2f}' for k, v in sorted(by.items(), key=lambda kv: -kv[1]))
    return f'volume of {len(recs)} objects: {tot:.2f} m³ ({per})'


def t_bom(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _empty(which)
    wall_m2 = sum(face_area(o) for o in recs if o['kind'] in WALLS)
    glass_m2 = sum(face_area(o) for o in recs if o['kind'] in GLASSY or o['mat'] == 'mat_glass')
    conc_m3 = sum(solid_volume(o) for o in recs if o['mat'] in ('mat_concrete', 'mat_blockwork') or o['kind'] in SLABS)
    mats: dict = {}
    for o in recs:
        mats[o['mat']] = mats.get(o['mat'], 0) + 1
    lines = [
        f'bill of materials for {len(recs)} objects (from the records, not a survey):',
        f'  wall face      {wall_m2:9.2f} m²',
        f'  glazing        {glass_m2:9.2f} m²',
        f'  concrete       {conc_m3:9.2f} m³',
        f'  total solid    {sum(solid_volume(o) for o in recs):9.2f} m³',
        '  kinds:     ' + _kind_tally(recs),
        '  materials: ' + ', '.join(f'{k} {v}' for k, v in sorted(mats.items(), key=lambda kv: -kv[1])),
    ]
    return '\n'.join(lines)


def t_find_free_cells(d: Drawing, a, cell_from, cell_to, min_w_cells=4, min_d_cells=4):
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    ca, cb = sorted((c0, c1))
    ra, rb = sorted((r0, r1))
    W, D = cb - ca + 1, rb - ra + 1
    mw = max(1, int(_num(min_w_cells, 4)))
    md = max(1, int(_num(min_d_cells, 4)))
    if mw > W or md > D:
        return f'refused: a {mw} x {md} cell rectangle does not fit in the {W} x {D} cell block at all'
    if W * D > 90000:
        return f'refused: the block is {W} x {D} cells — scan at most 300 x 300 at a time'
    occ = [[False] * D for _ in range(W)]
    cm, o0 = cell_size(), cell_origin()
    x0b, z0b = o0 + ca * cm, o0 + ra * cm
    marked = 0
    for o in d.objs:
        if storey_of(o['y'], d.storey_h) != 0:
            continue
        f = footprint(o)
        if not f:
            continue
        i0 = int(math.floor((f[0] - x0b) / cm))
        i1 = int(math.ceil((f[2] - x0b) / cm)) - 1
        j0 = int(math.floor((f[1] - z0b) / cm))
        j1 = int(math.ceil((f[3] - z0b) / cm)) - 1
        for i in range(max(0, i0), min(W - 1, i1) + 1):
            for j in range(max(0, j0), min(D - 1, j1) + 1):
                if not occ[i][j]:
                    occ[i][j] = True
                    marked += 1
    # summed-area table so every candidate rectangle is one lookup
    S = [[0] * (D + 1) for _ in range(W + 1)]
    for i in range(W):
        for j in range(D):
            S[i + 1][j + 1] = (1 if occ[i][j] else 0) + S[i][j + 1] + S[i + 1][j] - S[i][j]
    for j in range(D - md + 1):
        for i in range(W - mw + 1):
            if S[i + mw][j + md] - S[i][j + md] - S[i + mw][j] + S[i][j] == 0:
                fa, fb = cell_name(ca + i, ra + j), cell_name(ca + i + mw - 1, ra + j + md - 1)
                return (
                    f'free rectangle {fa}..{fb} ({mw} x {md} cells) in the block '
                    f'{cell_name(ca, ra)}..{cell_name(cb, rb)}; {marked} of {W * D} cells are occupied '
                    f'at storey 0 (footprints ignore rotation)'
                )
    return (
        f'none: no free {mw} x {md} cell rectangle in {cell_name(ca, ra)}..{cell_name(cb, rb)} — '
        f'{marked} of {W * D} cells are occupied at storey 0'
    )


def t_annotate(d: Drawing, a, cell, text, storey=0, height=None, material=''):
    txt = str(text or '').strip()
    if not txt:
        return 'refused: annotate needs the text of the note'
    if len(txt) > 120:
        return 'refused: keep the note under 120 characters — it is a label, not a paragraph'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    c, r = parse_cell(cell)
    x, z = cell_centre(c, r)
    st = int(_num(storey, 0))
    h = _num(height, 1.5)
    if h < 0.2 or h > 30:
        return 'refused: the pin height must be between 0.2 and 30 m'
    o = d.new(
        'annotation',
        {'h': round(h, 3), 'r': 0.15},
        x,
        z,
        st * d.storey_h,
        0.0,
        material if material in MATERIALS else 'mat_steel',
        name=txt,
        grp='notes',
    )
    return f'annotation {o["id"]} "{txt}" at {cell_name(c, r)} storey {st} ({h:g} m pin)'


def t_dimension(d: Drawing, a, cell_a, cell_b, storey=0, tick=0.3, material=''):
    ca, cb = parse_cell(cell_a), parse_cell(cell_b)
    ax, az = cell_centre(*ca)
    bx, bz = cell_centre(*cb)
    L = math.hypot(bx - ax, bz - az)
    if L < 0.5:
        return 'refused: the two cells are the same — a dimension needs two different cells'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    ry = math.atan2(-(bz - az), bx - ax)
    st = int(_num(storey, 0))
    tk = _num(tick, 0.3)
    o = d.new(
        'dimension',
        {'len': round(L, 3), 'tick': round(tk if 0.02 <= tk <= 5 else 0.3, 3)},
        (ax + bx) / 2,
        (az + bz) / 2,
        st * d.storey_h,
        ry,
        material if material in MATERIALS else 'mat_paint_dark',
        name=f'{L:.2f} m',
        grp='dimensions',
    )
    return (
        f'dimension {o["id"]} from {cell_name(*ca)} to {cell_name(*cb)}: {L:.2f} m, '
        f'at storey {st}, {math.degrees(ry) % 360:.0f}° on the plan'
    )


_WHICH = {'type': 'string', 'description': '"all" (default), "new", a kind, a group name, or an object id'}

TOOLS = [
    (
        {
            'name': 'measure',
            'description': 'The distance in metres between the centres of two cells, with the dx/dz and the column/row gap. Use it to check a span before drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {'cell_a': {'type': 'string'}, 'cell_b': {'type': 'string'}},
                'required': ['cell_a', 'cell_b'],
            },
        },
        t_measure,
    ),
    (
        {
            'name': 'bounds',
            'description': 'The cells and storeys a set of objects spans, and its size in metres. Use it to find out where a group actually sits.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_bounds,
    ),
    (
        {
            'name': 'count',
            'description': 'How many objects of each kind, and the group names. The cheapest way to check what a previous step drew.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_count,
    ),
    (
        {
            'name': 'list_storeys',
            'description': 'The storeys that hold objects, with the object count and kinds on each. Use it to see which floor is missing something.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_list_storeys,
    ),
    (
        {
            'name': 'what_is_at',
            'description': 'Which records cover a given cell (optionally only on one storey). Use it before drawing on a cell the user names, to see if it is taken.',
            'input_schema': {
                'type': 'object',
                'properties': {'cell': {'type': 'string'}, 'storey': {'type': 'integer'}},
                'required': ['cell'],
            },
        },
        t_what_is_at,
    ),
    (
        {
            'name': 'area',
            'description': "The ground footprint in m2: the union of the objects' footprints, so overlapping walls and slabs are not counted twice. Rotation is ignored.",
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_area,
    ),
    (
        {
            'name': 'floor_area',
            'description': 'Gross floor area: the sum of the slab areas, per storey and in total. This is the number a client means by "how many m2 is it".',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_floor_area,
    ),
    (
        {
            'name': 'volume',
            'description': 'The m3 of solid material (walls len*h*t, slabs w*d*t, columns, boxes, massing), broken down per kind.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_volume,
    ),
    (
        {
            'name': 'bom',
            'description': 'A short bill of materials: wall face m2, glazing m2, concrete m3, total solid m3, and the counts per kind and per material.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_bom,
    ),
    (
        {
            'name': 'find_free_cells',
            'description': 'The first empty rectangle of min_w_cells x min_d_cells inside the inclusive cell block, ignoring objects above storey 0. Use it to place a new building without hitting an existing one.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'min_w_cells': {'type': 'integer'},
                    'min_d_cells': {'type': 'integer'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_find_free_cells,
    ),
    (
        {
            'name': 'annotate',
            'description': 'Drop a labelled pin on a cell: a pole with a ball head whose NAME is the text. Use it to mark a spot the user asked about.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'text': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['cell', 'text'],
            },
        },
        t_annotate,
    ),
    (
        {
            'name': 'dimension',
            'description': 'Draw a measured line between two cells, with end ticks, named with its length in metres. Use it when the user wants the distance shown in the model.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_a': {'type': 'string'},
                    'cell_b': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'tick': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['cell_a', 'cell_b'],
            },
        },
        t_dimension,
    ),
]

EXAMPLES = [
    {
        'ask': 'how big is the house I just drew?',
        'calls': [{'tool': 'area', 'args': {'which': 'new'}}, {'tool': 'floor_area', 'args': {'which': 'new'}}],
    },
    {
        'ask': 'how far is it from the front door at C4 to the shed at R18?',
        'calls': [{'tool': 'measure', 'args': {'cell_a': 'C4', 'cell_b': 'R18'}}],
    },
    {'ask': 'how much concrete is in this?', 'calls': [{'tool': 'bom', 'args': {'which': 'all'}}]},
    {
        'ask': 'find me an empty 8 by 10 metre spot between C4 and AH34 for the garage',
        'calls': [
            {
                'tool': 'find_free_cells',
                'args': {'cell_from': 'C4', 'cell_to': 'AH34', 'min_w_cells': 8, 'min_d_cells': 10},
            }
        ],
    },
    {
        'ask': 'is anything already standing on M12?',
        'calls': [{'tool': 'what_is_at', 'args': {'cell': 'M12', 'storey': 0}}],
    },
    {
        'ask': 'mark the meter cupboard at F9 and show the width of the front facade from C4 to L4',
        'calls': [
            {'tool': 'annotate', 'args': {'cell': 'F9', 'text': 'meter cupboard'}},
            {'tool': 'dimension', 'args': {'cell_a': 'C4', 'cell_b': 'L4'}},
        ],
    },
]
