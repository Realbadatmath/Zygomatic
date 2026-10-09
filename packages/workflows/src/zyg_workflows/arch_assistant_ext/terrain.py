# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""terrain — ground before buildings: heightfields, hills, slopes, terraces.

The noise below is the SAME arithmetic as arch_ext/terrain.js and
arch_blender_ext/terrain.py. It lives here as well so the assistant (and the
test) can say how tall a terrain record actually is without rendering it:
`terrain_range(res, seed)` returns the (min, max) of the unit heightfield, so
the built height is `amp * (max - min)`.

SCULPTED GROUND (v3, 2026-09-07). A drawing has at most ONE ground. When it has
a `ground` record the shaping tools stop laying solids on the land and start
being the land:

  · make_terrain REFUSES — there is already a heightfield; raise_ground /
    lower_ground shape it.
  · add_hill lays a `sculpt_peak` with rug 0, which is the old smooth mound
    arithmetic exactly: h at the centre, h/2 at r/2, 0 at the rim.
  · add_slope lays ONE `sculpt_step` turned so its local +Z runs DOWNHILL, with
    d = 3 * run and feather = run, so the step's back feather IS the ramp. That
    profile is the bare smoothstep, whose worst departure from the straight line
    between its ends is 9.62 % of the rise — inside the 10 % the brief asks for.
    The `sculpt_flat` alternative measures 27.6 % through ground_height and is
    NOT used; slope_linearity() below reproduces both numbers.
  · flatten_pad cuts AND fills through arch_assistant.level_ground: a
    `sculpt_flat` at the MEAN ground height over the block (so the pad is a
    cutting on the high side and an embankment on the low side) plus the visible
    `pad` record at that same level for buildings to sit on.

add_retaining_wall and berm stay solids — a wall is a wall. With no `ground`
record every tool draws exactly what it drew yesterday.
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
    MAX_OBJECTS,
    _num,
    ground_height,
    level_ground,
)

KINDS = {
    'terrain': {'w': 20, 'd': 20, 'amp': 2, 'seed': 1, 'res': 24, 'base': 0},
    'hill': {'r': 8, 'h': 3},
    'slope': {'w': 10, 'd': 10, 'h': 2, 'dir': 0},
    'plateau': {'w': 20, 'd': 20, 'h': 1.5, 'batter': 0.5},
    'retaining_wall': {'len': 10, 'h': 1.5, 't': 0.3, 'batter': 0.1},
    'berm': {'len': 20, 'w': 4, 'h': 1.2},
}
OPENINGS: list = []

PROMPT = (
    'Terrain: with a sculpted ground (make_ground) these tools shape the LAND itself and make_terrain is '
    'refused — use raise_ground/lower_ground. Without one they lay solids. '
    'make_terrain(cell_from, cell_to, style, amplitude, seed) lays ONE rolling heightfield over a block — '
    "style 'hills' (amp 3), 'gentle' (1) or 'flat' (0.2); ground first, then the buildings. "
    'add_hill(centre, radius, height) is a single smooth mound (a dune, a mound in a park). '
    "add_slope(cell_from, cell_to, height, direction) ramps a block, direction 'x' or 'z' naming the axis it "
    'climbs. add_retaining_wall(cells, height) walls a cut: one battered concrete wall between each pair of '
    'cells, so 3 cells give 2 walls. flatten_pad(cell_from, cell_to) levels a block at its MEAN ground, '
    'cutting the high side and filling the low — call it for every footprint before you build on it. '
    'plateau and berm are reachable through add_object.'
)

_STYLE_AMP = {'hills': 3.0, 'gentle': 1.0, 'flat': 0.2}


# ── the shared noise (identical in the JS and the Blender copies) ────────────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u: float, v: float, seed: float) -> float:
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def terrain_range(res: int = 24, seed: float = 1) -> tuple:
    """(min, max) of the unit heightfield a `terrain` record samples."""
    res = max(2, min(96, int(res)))
    vals = [value_noise(i / res * 4, j / res * 4, seed) for j in range(res + 1) for i in range(res + 1)]
    return min(vals), max(vals)


def _mat(m, default='mat_grass'):
    return m if m in MATERIALS else default


def _res_for(w: float, d: float) -> int:
    return max(8, min(64, int(round(max(w, d) / 2.0))))


# ── the v3 ground seam ──────────────────────────────────────────────────────
SLOPE_D = 3.0  # a slope step is 3 runs deep …
SLOPE_FEATHER = 1.0  # … and its back feather, the ramp itself, is 1 run


def the_ground(d):
    """The drawing's one `ground` record, or None. A hidden ground is no ground:
    hiding it in the outliner puts every tool back on the old solid path."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') == 'ground' and not o.get('hidden'):
            return o
    return None


def slope_step(W: float, D: float, h: float, dr: str, xmin: float, zmin: float, xmax: float, zmax: float) -> tuple:
    """(params, x, z, ry, run) for the sculpt_step that ramps a block.

    The step's raised side is its local +Z, so the record is turned to point +Z
    DOWNHILL and pushed back until the block's LOW edge lands on lz = +d/2 and
    its HIGH edge on lz = +d/2 - feather. Everything between is the back band's
    smoothstep — the ramp. `len` is the width across the run plus a feather at
    each end, so the block's full width sits at mask 1."""
    if dr == 'x':  # climbs east: downhill is west
        run, across, ux, uz = W, D, -1.0, 0.0
        lowx, lowz = xmin, (zmin + zmax) / 2
    else:  # climbs south: downhill is north
        run, across, ux, uz = D, W, 0.0, -1.0
        lowx, lowz = (xmin + xmax) / 2, zmin
    dd = SLOPE_D * run
    fe = SLOPE_FEATHER * run
    p = {
        'len': round(across + 2 * fe, 4),
        'h': round(h, 3),
        'd': round(dd, 4),
        'rug': 0,
        'seed': 1,
        'feather': round(fe, 4),
    }
    return p, lowx - dd / 2 * ux, lowz - dd / 2 * uz, math.atan2(ux, uz), run


def flat_ground(cell_from: str = 'C4', cell_to: str = 'CV200'):
    """A drawing whose only record is a v3 ground with the noise turned OFF, so
    a profile through it measures the sculpt and nothing else."""
    from zyg_workflows.arch_assistant import Drawing as _D, call_tool as _ct

    d = _D({'objects': []})
    _ct(d, 'make_ground', {'cell_from': cell_from, 'cell_to': cell_to, 'style': 'flat'})
    for o in d.objs:
        if o['kind'] == 'ground':
            o['p']['amp'] = 0.0
    return d


def slope_linearity(cell_from: str = 'D20', cell_to: str = 'M35', h: float = 4.0, n: int = 41) -> dict:
    """Both candidate ramps for add_slope, measured the same way through
    ground_height on a flat sculpted ground: {'step': pct, 'flat': pct} — the
    worst departure from the straight line between the profile's ends, as a
    percentage of the rise achieved. The numbers are 9.6 (sculpt_step, the one
    add_slope uses: the bare smoothstep) and 27.61 (sculpt_flat, rejected)."""

    def worst(ys):
        rise = ys[-1] - ys[0]
        if abs(rise) < 1e-9:
            return 100.0
        w = max(abs(y - (ys[0] + rise * i / (len(ys) - 1))) for i, y in enumerate(ys))
        return round(w / abs(rise) * 100.0, 2)

    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx = (xmin + xmax) / 2
    out = {}
    for which in ('step', 'flat'):
        d = flat_ground()
        if which == 'step':
            p, sx, sz, ry, _ = slope_step(W, D, h, 'z', xmin, zmin, xmax, zmax)
            d.new('sculpt_step', p, sx, sz, 0.0, ry, 'mat_soil', name='ramp', grp='terrain')
        else:
            d.new(
                'sculpt_flat',
                {'w': W + 2 * D, 'd': 2 * D, 'level': h, 'feather': D},
                cx,
                zmin,
                h,
                0.0,
                'mat_soil',
                name='ramp',
                grp='terrain',
            )
        out[which] = worst([ground_height(d, cx, zmin + i / (n - 1) * D) for i in range(n)])
    return out


# ── tools ───────────────────────────────────────────────────────────────────
def t_make_terrain(d: Drawing, a, cell_from, cell_to, style='hills', amplitude=None, seed=1, material='', name=''):
    if the_ground(d) is not None:
        return (
            'refused: the drawing has a sculpted ground; use raise_ground/lower_ground '
            'to shape it (a drawing has only one ground, and make_terrain would lay a '
            'second heightfield on top of it)'
        )
    st = str(style or 'hills').strip().lower()
    if st not in _STYLE_AMP:
        return "refused: style must be 'hills', 'gentle' or 'flat'"
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 400 or D > 400:
        return f'refused: {W:g} x {D:g} m is too big for one terrain — 400 m a side is the limit'
    amp = _STYLE_AMP[st] if amplitude is None else _num(amplitude, _STYLE_AMP[st])
    if amp < 0 or amp > 100:
        return 'refused: amplitude must be between 0 and 100 m'
    res = _res_for(W, D)
    sd = _num(seed, 1)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    lo, hi = terrain_range(res, sd)
    o = d.new(
        'terrain',
        {'w': round(W, 4), 'd': round(D, 4), 'amp': round(amp, 3), 'seed': sd, 'res': res, 'base': 0},
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        0.0,
        0.0,
        _mat(material),
        name=name or f'terrain {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}',
        grp=name or 'terrain',
    )
    return (
        f'laid terrain {o["id"]} over {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
        f'{W:g} x {D:g} m, {st}, amplitude {amp:g} m, {res}x{res} cells, seed {sd:g} — '
        f'relief {amp * (hi - lo):.2f} m from low to high'
    )


def t_add_hill(d: Drawing, a, centre, radius=8.0, height=3.0, material='', name=''):
    r = _num(radius, 8.0)
    h = _num(height, 3.0)
    if r < 0.5 or r > 200:
        return 'refused: radius must be between 0.5 and 200 m'
    if h <= 0 or h > 100:
        return 'refused: height must be between 0 and 100 m'
    cx, cz = cell_centre(*parse_cell(centre))
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cn = cell_name(*parse_cell(centre))
    if the_ground(d) is not None:
        o = d.new(
            'sculpt_peak',
            {'r': round(r, 3), 'h': round(h, 3), 'rug': 0, 'seed': 1, 'feather': 0},
            cx,
            cz,
            0.0,
            0.0,
            _mat(material),
            name=name or f'hill {cn}',
            grp=name or 'terrain',
        )
        return (
            f'raised hill {o["id"]} out of the ground at {cn}: {2 * r:g} m across, {h:g} m tall, '
            f'half height {r / 2:g} m out and meeting the land flat at its foot — a sculpt_peak '
            f'with no ruggedness, so it is the one ground bulging, not a mound sitting on it'
        )
    o = d.new(
        'hill',
        {'r': round(r, 3), 'h': round(h, 3)},
        cx,
        cz,
        0.0,
        0.0,
        _mat(material),
        name=name or f'hill {cn}',
        grp=name or 'terrain',
    )
    return f'drew hill {o["id"]} on {cn}: {2 * r:g} m across, {h:g} m tall'


def t_add_slope(d: Drawing, a, cell_from, cell_to, height=2.0, direction='z', material='', name=''):
    dr = str(direction or 'z').strip().lower()
    if dr not in ('x', 'z'):
        return "refused: direction must be 'x' (climbs east) or 'z' (climbs south)"
    h = _num(height, 2.0)
    if h <= 0 or h > 100:
        return 'refused: height must be between 0 and 100 m'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    # the record's local run is always its own d; turning it 90 deg puts that
    # run along world X, which swaps which block dimension is w and which is d.
    w, dd, ang = (D, W, 90) if dr == 'x' else (W, D, 0)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    if the_ground(d) is not None:
        p, sx, sz, ry, run = slope_step(W, D, h, dr, xmin, zmin, xmax, zmax)
        o = d.new(
            'sculpt_step',
            p,
            sx,
            sz,
            0.0,
            ry,
            _mat(material),
            name=name or f'slope {cell_name(*parse_cell(cell_from))}',
            grp=name or 'terrain',
        )
        return (
            f'ramped the ground {o["id"]} over {cell_name(*parse_cell(cell_from))}..'
            f'{cell_name(*parse_cell(cell_to))}: {W:g} x {D:g} m, rising {h:g} m along {dr} '
            f'over {run:g} m (1:{run / h:.1f}) — one sculpt_step turned +Z downhill, its back '
            f'feather spanning the whole run, so the land itself ramps within 10 % of straight'
        )
    o = d.new(
        'slope',
        {'w': round(w, 4), 'd': round(dd, 4), 'h': round(h, 3), 'dir': ang},
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        0.0,
        0.0,
        _mat(material),
        name=name or f'slope {cell_name(*parse_cell(cell_from))}',
        grp=name or 'terrain',
    )
    run = dd
    return (
        f'drew slope {o["id"]} over {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
        f'{W:g} x {D:g} m, rising {h:g} m along {dr} over {run:g} m (1:{run / h:.1f})'
    )


def t_add_retaining_wall(d: Drawing, a, cells, height=1.5, thickness=0.3, batter=0.1, material='', name=''):
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: give a list of at least two cells — one wall is drawn between each pair'
    h = _num(height, 1.5)
    if h <= 0 or h > 20:
        return 'refused: height must be between 0 and 20 m'
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    t = _num(thickness, 0.3)
    b = _num(batter, 0.1)
    grp = name or 'retaining walls'
    ids = []
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a wall needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        o = d.new(
            'retaining_wall',
            {'len': round(L, 4), 'h': round(h, 3), 't': round(t, 3), 'batter': round(b, 3)},
            (x0 + x1) / 2,
            (z0 + z1) / 2,
            0.0,
            ry,
            _mat(material, 'mat_concrete'),
            name=f'retaining wall {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
    total = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(need))
    return (
        f'drew {need} retaining wall(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m in total, {h:g} m tall, {t:g} m thick at the top'
    )


def t_flatten_pad(d: Drawing, a, cell_from, cell_to, material='', name=''):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    if the_ground(d) is not None:
        if len(d.objs) + 2 > MAX_OBJECTS:
            return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
        cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
        before = [ground_height(d, x, z) for x in (xmin + 0.1, cx, xmax - 0.1) for z in (zmin + 0.1, cz, zmax - 0.1)]
        lvl, _note = level_ground(d, cx, cz, W, D, 0.0, None, _mat(material, 'mat_gravel'), name or 'terrain')
        pad = d.objs[-1]
        cut = max(before) - lvl
        fill = lvl - min(before)
        return (
            f'levelled pad {pad["id"]} over {cf}..{ct}: {W:g} x {D:g} m at {lvl:.2f} m, the MEAN '
            f'ground there — the sculpt_flat beside it cuts up to {max(cut, 0):.2f} m off the high '
            f'side and fills up to {max(fill, 0):.2f} m on the low side, so the ground under the '
            f'pad really is level and a building can sit flat on it'
        )
    o = d.new(
        'pad',
        {'w': round(W, 4), 'd': round(D, 4), 't': 0.2},
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        0.0,
        0.0,
        _mat(material, 'mat_gravel'),
        name=name or f'pad {cf}-{ct}',
        grp=name or 'terrain',
    )
    return f'levelled pad {o["id"]} over {cf}..{ct}: {W:g} x {D:g} m — build on it flat'


# ── ground heights (the seam's worked example, 2026-09-07) ───────────────────
# fn(p, lx, lz) -> metres above the record's base at a LOCAL plan point, or None
# outside the footprint. Same arithmetic as the geometry in arch_ext/terrain.js.
def h_terrain(p, lx, lz):
    w, dd = _num(p.get('w'), 20.0), _num(p.get('d'), 20.0)
    if abs(lx) > w / 2 + 1e-9 or abs(lz) > dd / 2 + 1e-9:
        return None
    u = (lx + w / 2) / w * 4.0
    v = (lz + dd / 2) / dd * 4.0
    return _num(p.get('base'), 0.0) + _num(p.get('amp'), 2.0) * value_noise(u, v, _num(p.get('seed'), 1))


def h_hill(p, lx, lz):
    r, h = max(0.2, _num(p.get('r'), 8.0)), _num(p.get('h'), 3.0)
    rad = math.hypot(lx, lz)
    if rad > r:
        return None
    return h * 0.5 * (1 + math.cos(math.pi * rad / r))


def h_slope(p, lx, lz):
    w, dd, h = _num(p.get('w'), 10.0), _num(p.get('d'), 10.0), _num(p.get('h'), 2.0)
    a = math.radians(_num(p.get('dir'), 0.0))
    # the geometry is the dir=0 wedge turned by +dir about Y: undo that turn
    c, s = math.cos(a), math.sin(a)
    x0 = lx * c - lz * s
    z0 = lx * s + lz * c
    if abs(x0) > w / 2 + 1e-9 or abs(z0) > dd / 2 + 1e-9:
        return None
    return h * (z0 + dd / 2) / dd  # low edge at z0 = -d/2, high edge at +d/2


def h_plateau(p, lx, lz):
    w, dd, h = _num(p.get('w'), 20.0), _num(p.get('d'), 20.0), _num(p.get('h'), 1.5)
    batter = _num(p.get('batter'), 0.5)
    if abs(lx) > w / 2 + 1e-9 or abs(lz) > dd / 2 + 1e-9:
        return None
    b = max(0.0, min(batter * h, w / 2 - 0.05, dd / 2 - 0.05))
    if b <= 1e-9:
        return h
    tw, td = w / 2 - b, dd / 2 - b
    t = max((abs(lx) - tw) / b, (abs(lz) - td) / b, 0.0)
    return h * (1.0 - min(t, 1.0))


def h_berm(p, lx, lz):
    ln, w, h = _num(p.get('len'), 20.0), _num(p.get('w'), 4.0), _num(p.get('h'), 1.2)
    if abs(lx) > ln / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    return h * (1.0 - 2.0 * abs(lz) / w)


HEIGHTS = {'terrain': h_terrain, 'hill': h_hill, 'slope': h_slope, 'plateau': h_plateau, 'berm': h_berm}


TOOLS = [
    (
        {
            'name': 'make_terrain',
            'description': "One rolling ground surface over a block of cells. style 'hills' is a real landscape (3 m of relief), 'gentle' is a garden (1 m), 'flat' is almost level (0.2 m). Draw the ground before the buildings; change seed for a different landscape. REFUSED when the drawing already has a sculpted ground (make_ground) — there is only ever one ground; shape it with raise_ground and lower_ground.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'style': {'type': 'string', 'enum': ['hills', 'gentle', 'flat']},
                    'amplitude': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_make_terrain,
    ),
    (
        {
            'name': 'add_hill',
            'description': 'A single smooth mound centred on a cell: 2 x radius across, height tall, meeting the ground flat at its foot. On a sculpted ground it is the LAND that bulges (a sculpt_peak with no ruggedness), not a mound placed on it. Use for a dune, a mound in a park, a burial mound.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_hill,
    ),
    (
        {
            'name': 'add_slope',
            'description': "Ground rising across a block of cells: direction 'x' climbs east, 'z' climbs south. On a sculpted ground the LAND itself ramps, straight to within 10 %, and blends into the country around it. Use for a sloping garden, an embanked approach, the earth beside a ramp.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height': {'type': 'number'},
                    'direction': {'type': 'string', 'enum': ['x', 'z']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'height'],
            },
        },
        t_add_slope,
    ),
    (
        {
            'name': 'add_retaining_wall',
            'description': 'Battered concrete walls holding back a cut, one between each pair of cells in the list (3 cells = 2 walls). Use where a terrace, a sunken garden or a ramp meets higher ground.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'thickness': {'type': 'number'},
                    'batter': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_retaining_wall,
    ),
    (
        {
            'name': 'flatten_pad',
            'description': 'A level ground pad over a block of cells so a building sits flat on sloping terrain. On a sculpted ground it levels the LAND at the mean height there — cutting the high side and filling the low — and lays the pad on it. Call it for each footprint before drawing the building.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_flatten_pad,
    ),
]

EXAMPLES = [
    {
        'ask': 'give the site from C4 to L13 some rolling ground first',
        'calls': [{'tool': 'make_terrain', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'hills'}}],
    },
    {
        'ask': 'a gentle garden slope from D20 to K27 rising 1.5 m to the east, with a level pad for the house on F22..I25',
        'calls': [
            {'tool': 'add_slope', 'args': {'cell_from': 'D20', 'cell_to': 'K27', 'height': 1.5, 'direction': 'x'}},
            {'tool': 'flatten_pad', 'args': {'cell_from': 'F22', 'cell_to': 'I25'}},
        ],
    },
    {
        'ask': 'a mound in the park at P30, 12 m across and 2 m high',
        'calls': [{'tool': 'add_hill', 'args': {'centre': 'P30', 'radius': 6, 'height': 2}}],
    },
    {
        'ask': 'hold the terrace back along E10, E16 and J16 with a 1.2 m retaining wall',
        'calls': [{'tool': 'add_retaining_wall', 'args': {'cells': ['E10', 'E16', 'J16'], 'height': 1.2}}],
    },
    {
        'ask': 'flatten the ground under the warehouse, B5 to N18',
        'calls': [{'tool': 'flatten_pad', 'args': {'cell_from': 'B5', 'cell_to': 'N18'}}],
    },
]
