# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""water_v3 — the water that SITS ON the v3 sculpted bed (2026-09-07).

The v1 `lake`, `river` and `sea` kinds each carried their own bed: a lake was a
bowl with a lid, a sea was a sheet with a slab under it. On a v3 drawing that is
wrong twice over — the bed is already there (it is a `sculpt_basin`, a
`sculpt_channel`, a `sculpt_shelf` cut into the ONE ground) and a second bed
parked on top of it reads as a plinth.

So this family draws WATER ONLY. Three kinds, all of them thin (0.02 m)
two-sided translucent surfaces whose parts carry `sub: 'mat_water'`:

    water_body   {rx, rz, wobble, seed, seg}    a lake / pond surface
    water_path   {len, w, meander, seed, seg,   a river / stream reach surface
                  level0, level1}               (the pair makes it SLOPE)
    water_plane  {w, d, wave, seed, res}        the sea surface

and three tools that place a bed sculpt AND its surface together:

    fill_lake    -> sculpt_basin   + water_body
    carve_river  -> sculpt_channel + water_path   (one pair per reach)
    fill_sea     -> sculpt_shelf   + water_plane

THE SHORELINE IS A CONTRACT. `_hash` / `value_noise` are verbatim from
arch_ext/terrain.js and arch_assistant_ext/terrain.py; `meander_offset` and
`lake_factor` are verbatim from arch_assistant_ext/ground_v3.py (which took them
from the v1 river and lake kinds). That is the whole trick: a `water_body` laid
over a `sculpt_basin` of the same rx/rz/wobble/seed has EXACTLY the basin's
shoreline, and a `water_path` over a `sculpt_channel` of the same
len/meander/seed wanders down exactly the same trough. Change one of the four
copies (this file, arch_ext/water_v3.js, arch_blender_ext/water_v3.py,
ground_v3) and the water leaves its bed.

WHY A SCULPT IS CREATED AT y = 0. ground_v3.field_at adds `dh * s + y * mask`
for every sculpt, so a bed record placed at the ground height there would LIFT
the land by that height before cutting into it. The bed sits at y = 0 and the
cut is a pure delta; the WATER carries the height instead, and that is the one
number these tools compute:

    lake  : water y = ground_height(centre) - 0.2 * depth
    river : bed at node k = min(ground_height(node k) - depth, bed at node k-1)
            water y of reach i = bed[i] + 0.8 * depth, sloping to bed[i+1] + 0.8
            * depth at its far end                                # never climbs
    sea   : water y = `level` (default -0.3), the sea is one flat datum

so the water surface is 0.8 * depth above the bed it was fitted to — deep in the
middle, feathering out to the shore where the sculpt's own mask has already
brought the bed back up to meet it. That level is stored UNROUNDED: rounding a
water level to the record grid would leave the surface a visible fraction above
or below the bed it was measured against.

A RIVER IS A FALLING PROFILE, NOT 'GROUND MINUS DEPTH'. carve_river measures the
ground at the NODES (the cell centres) before it cuts anything, walks a bed level
down the chain that is never allowed to rise, and hands each reach BOTH node
levels: the sculpt_channel is SET to that straight fall (ground_v3.channel_levels)
and the water_path slopes with it (path_levels / path_y). Held at one level the
water goes under the valley's own 1.5 m of base noise half way along and the river
shows as broken blue pieces — which is exactly what it did before 2026-09-07.

`base_height` is not an argument to any tool here, and never will be. Water does
not stand on the ground at an offset you choose — it lies in the hollow, at the
height the hollow puts it. Ask for a pond at a height and the answer is a lake
at the ground height there, minus its own depth.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    cell_of,
    block_bounds,
    MAX_OBJECTS,
    _num,
)

# ── kinds ────────────────────────────────────────────────────────────────────
KINDS = {
    'water_body': {'rx': 30, 'rz': 20, 'wobble': 0.25, 'seed': 1, 'seg': 48},
    'water_path': {'len': 60, 'w': 8, 'meander': 6, 'seed': 1, 'seg': 24},
    'water_plane': {'w': 200, 'd': 120, 'wave': 0.15, 'seed': 1, 'res': 24},
}
OPENINGS: list = []

PROMPT = (
    'Water on a sculpted ground (v3): water is a surface, the bed is a sculpt of the ONE ground, and the two are '
    'always placed together — never a solid bowl on a lawn. '
    'fill_lake(centre, radius, radius_z, depth, irregularity, seed) cuts a lake bed and floats its water on it: '
    'the water lands at the ground height under the centre minus a fifth of the depth, so the shore is where the '
    'land comes back up to meet it. Radius 5-120 m, depth 1-15 m. '
    'carve_river(cells, width, depth, meander, seed) runs a river down a chain of cells, one bed and one water '
    'reach per leg, each reach at or below the one before it — water never climbs a hill. Width 3-30 m for a '
    'river, 1-3 m for a stream; depth 0.3-4 m. '
    'fill_sea(cell_from, cell_to, depth, level) drops a sea bed under a block and lays one flat sea over it at '
    '`level` (default -0.3 m). '
    'All three need a ground first (make_ground); without one they refuse and point at the old solid add_lake / '
    'add_river / add_sea kinds. There is no base_height here — water sits at the height its hollow gives it.'
)

# ── real sizes (the same ranges the v1 river/lake tools refuse outside) ───────
MIN_LAKE_R, MAX_LAKE_R = 5.0, 120.0
MIN_LAKE_DEPTH, MAX_LAKE_DEPTH = 1.0, 15.0
MIN_STREAM_W, MAX_STREAM_W = 1.0, 3.0
MIN_RIVER_W, MAX_RIVER_W = 3.0, 30.0
MIN_RIVER_DEPTH, MAX_RIVER_DEPTH = 0.3, 4.0
MAX_SEA_SIDE = 2000.0
MAX_SEA_DEPTH = 200.0
MAX_REACHES = 40

WATER_T = 0.02  # every water surface is this thin — it is a skin, not a solid
FREEBOARD = 0.2  # water sits (1 - FREEBOARD) x depth above the bed


# ── the shared noise (verbatim: terrain.py / ground_v3.py / water_v3.js) ─────
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


def meander_offset(t: float, meander: float, seed: float) -> float:
    """A reach's sideways offset — the SAME line as ground_v3.meander_offset, so
    a water_path lies exactly in the sculpt_channel drawn under it."""
    return (
        meander
        * math.sin(math.pi * t)
        * (0.6 * math.sin(2 * math.pi * t * 1.5) + 0.4 * (2 * value_noise(t * 4, seed, seed) - 1))
    )


def lake_factor(a: float, wobble: float, seed: float) -> float:
    """A shoreline's radius multiplier at plan angle a — the SAME line as
    ground_v3.lake_factor, so a water_body's rim is its sculpt_basin's rim."""
    return 1 + wobble * (2 * value_noise(math.cos(a) * 2 + 2, math.sin(a) * 2 + 2, seed) - 1)


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _N(p, k, d):
    return _num((p or {}).get(k), d)


# ── the plan outlines the three engines all build from ───────────────────────
def body_ring(p) -> list:
    """The water_body's shoreline in its own local plan frame: [(x, z), ...]."""
    rx = max(0.5, _N(p, 'rx', 30.0))
    rz = max(0.5, _N(p, 'rz', 20.0))
    wob = clamp(_N(p, 'wobble', 0.25), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    seg = int(clamp(round(_N(p, 'seg', 48.0)), 8, 256))
    out = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        m = lake_factor(a, wob, seed)
        out.append((rx * math.cos(a) * m, -rz * math.sin(a) * m))
    return out


def path_edges(p):
    """The water_path's two banks: ([(x, z) left], [(x, z) right])."""
    ln = max(1.0, _N(p, 'len', 60.0))
    w = max(0.2, _N(p, 'w', 8.0))
    mea = max(0.0, _N(p, 'meander', 6.0))
    seed = _N(p, 'seed', 1.0)
    seg = int(clamp(round(_N(p, 'seg', 24.0)), 2, 200))
    left, right = [], []
    for i in range(seg + 1):
        t = i / seg
        x = -ln / 2 + t * ln
        zc = meander_offset(t, mea, seed)
        left.append((x, zc - w / 2))
        right.append((x, zc + w / 2))
    return left, right


def path_levels(p):
    """A water_path's FALL, or None.

    (level0, level1) is the surface height at the reach's start (local
    x = -len/2) and end (+len/2), in the RECORD'S OWN frame — the record's y is
    the datum, so carve_river writes level0 = 0 and level1 = the drop down to the
    next node. Without both the surface is flat at local y = 0, which is what
    every water_path was before rivers learnt to fall.

    A river cannot be a chain of flat puddles: the valley floor rolls by metres,
    so a reach held at one level goes under the ground half way along and the
    river reads as broken blue pieces. The bed under it is a SET sculpt_channel
    of the same two levels (ground_v3.channel_levels), so the two fall together.
    """
    p = p or {}
    a, b = p.get('level0'), p.get('level1')
    if a is None or b is None:
        return None
    return _num(a, 0.0), _num(b, 0.0)


def path_y(p, t: float) -> float:
    """The water_path's surface height at station t (0 at the start of the reach,
    1 at its end), in the record's local frame. The same line in all three
    engines — change it here and in water_v3.js and arch_blender_ext."""
    lv = path_levels(p)
    return 0.0 if lv is None else lv[0] + (lv[1] - lv[0]) * t


def plane_height(p, i, j) -> float:
    """The water_plane's swell at lattice (i, j) — the old `sea` surface's wave,
    with the -0.3 baseline taken OUT: the record's own y is the sea level now."""
    wave = _N(p, 'wave', 0.15)
    seed = _N(p, 'seed', 1.0)
    res = int(clamp(round(_N(p, 'res', 24.0)), 2, 200))
    return wave * (2 * value_noise(i / res * 8, j / res * 8, seed) - 1)


def body_extent(p):
    """(x size, z size) of a water_body's plan bbox — what the tab and Blender
    bounding boxes have to agree with."""
    ring = body_ring(p)
    xs = [q[0] for q in ring]
    zs = [q[1] for q in ring]
    return max(xs) - min(xs), max(zs) - min(zs)


def path_extent(p):
    """(x size, z size) of a water_path's plan bbox. x is exactly `len`."""
    left, right = path_edges(p)
    zs = [q[1] for q in left] + [q[1] for q in right]
    return max(1.0, _N(p, 'len', 60.0)), max(zs) - min(zs)


# ── tools ────────────────────────────────────────────────────────────────────
NO_GROUND_LAKE = 'refused: no sculpted ground — call make_ground first, or use add_lake for the old solid lake'
NO_GROUND_RIVER = 'refused: no sculpted ground — call make_ground first, or use add_river for the old solid river'
NO_GROUND_SEA = 'refused: no sculpted ground — call make_ground first, or use add_sea for the old solid sea'


def the_ground(d):
    for o in d.objs:
        if o['kind'] == 'ground' and not o.get('hidden'):
            return o
    return None


def _room(d, n) -> bool:
    return len(d.objs) + n <= MAX_OBJECTS


def _bed(d, kind, p, x, z, nm, ry=0.0):
    """A bed sculpt: ALWAYS at y = 0 — see the module docstring."""
    return d.new(kind, p, x, z, 0.0, ry, 'mat_soil', name=nm, grp='ground sculpts')


def _water(d, kind, p, x, z, y, nm, ry=0.0):
    rec = d.new(kind, p, x, z, 0.0, ry, 'mat_water', name=nm, grp='water')
    rec['y'] = float(y)  # unrounded: the water must not float off its bed
    return rec


def _cell_xz(txt):
    return cell_centre(*parse_cell(txt))


def t_fill_lake(d: Drawing, a, centre, radius=30.0, radius_z=None, depth=3.0, irregularity=0.25, seed=1, name=''):
    if the_ground(d) is None:
        return NO_GROUND_LAKE
    rx = _num(radius, 30.0)
    rz = _num(radius_z, rx) if radius_z is not None else rx
    if rx < MIN_LAKE_R or rx > MAX_LAKE_R or rz < MIN_LAKE_R or rz > MAX_LAKE_R:
        return (
            f'refused: a lake is {MIN_LAKE_R:g}-{MAX_LAKE_R:g} m across the radius — '
            f'{rx:g} x {rz:g} m is a puddle or an inland sea'
        )
    dep = _num(depth, 3.0)
    if dep < MIN_LAKE_DEPTH or dep > MAX_LAKE_DEPTH:
        return f'refused: a lake is {MIN_LAKE_DEPTH:g}-{MAX_LAKE_DEPTH:g} m deep, not {dep:g} m'
    irr = clamp(_num(irregularity, 0.25), 0.0, 0.9)
    try:
        cx, cz = _cell_xz(centre)
    except Exception as e:  # noqa: BLE001
        return f'refused: {e}'
    if not _room(d, 2):
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    sd = _num(seed, 1)
    g0 = A.ground_height(d, cx, cz)  # BEFORE the bed is cut
    shore = max(1.0, 0.15 * min(rx, rz))
    nm = name or f'lake {cell_of(cx, cz)}'
    bed = _bed(
        d,
        'sculpt_basin',
        {
            'rx': round(rx, 4),
            'rz': round(rz, 4),
            'depth': round(dep, 4),
            'wobble': round(irr, 4),
            'seed': sd,
            'shore': round(shore, 4),
            'feather': 0,
        },
        cx,
        cz,
        nm + ' bed',
    )
    wy = g0 - FREEBOARD * dep
    wat = _water(
        d,
        'water_body',
        {'rx': round(rx, 4), 'rz': round(rz, 4), 'wobble': round(irr, 4), 'seed': sd, 'seg': 48},
        cx,
        cz,
        wy,
        nm,
    )
    return (
        f'filled {nm} at {cell_of(cx, cz)}: bed {bed["id"]} (sculpt_basin, {rx:g} x {rz:g} m, '
        f'{dep:g} m deep, cut into the ground) and water {wat["id"]} (water_body) at '
        f'{wy:.3f} m — the ground there was {g0:.3f} m, the bed is now {g0 - dep:.3f} m, '
        f'so the lake is {dep * (1 - FREEBOARD):.3f} m deep at the middle and dries out at the shore.'
    )


def _cells_of(cells) -> list:
    if isinstance(cells, str):
        return [c.strip() for c in cells.replace(';', ',').split(',') if c.strip()]
    return [str(c).strip() for c in (cells or []) if str(c).strip()]


def t_carve_river(d: Drawing, a, cells, width=8.0, depth=1.5, meander=6.0, seed=1, name=''):
    if the_ground(d) is None:
        return NO_GROUND_RIVER
    names = _cells_of(cells)
    if len(names) < 2:
        return 'refused: a river needs at least two cells to run between, e.g. ["B2", "H9"]'
    if len(names) - 1 > MAX_REACHES:
        return f'refused: {len(names) - 1} reaches is more than the {MAX_REACHES} this tool draws in one go'
    w = _num(width, 8.0)
    if w < MIN_STREAM_W or w > MAX_RIVER_W:
        return (
            f'refused: {w:g} m wide is not water — a stream is {MIN_STREAM_W:g}-{MAX_STREAM_W:g} m, '
            f'a river {MIN_RIVER_W:g}-{MAX_RIVER_W:g} m'
        )
    dep = _num(depth, 1.5)
    if dep < MIN_RIVER_DEPTH or dep > MAX_RIVER_DEPTH:
        return f'refused: a river is {MIN_RIVER_DEPTH:g}-{MAX_RIVER_DEPTH:g} m deep, not {dep:g} m'
    mea = max(0.0, _num(meander, 6.0))
    try:
        pts = [_cell_xz(c) for c in names]
    except Exception as e:  # noqa: BLE001
        return f'refused: {e}'
    reaches = []
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        ln = math.hypot(x1 - x0, z1 - z0)
        if ln < 1.0:
            return f'refused: {names[i]} and {names[i + 1]} are {ln:g} m apart — that is not a reach'
        reaches.append((ln, (x0 + x1) / 2, (z0 + z1) / 2, math.atan2(-(z1 - z0), x1 - x0)))
    if not _room(d, 2 * len(reaches)):
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    # THE PROFILE IS THE RIVER. Every datum is read from the UNTOUCHED ground at
    # the NODES (the cell centres), before a single bed is cut, so an upstream cut
    # cannot move the height a downstream node was fitted to. The bed at a node is
    # the ground there less the full depth, but never above the node before it —
    # so where the land rises downstream the river digs in rather than climbing.
    # Each reach is then a bed SET to the straight fall between its two nodes, and
    # the water on it slopes with it. That is what stops the base noise surfacing
    # through a reach held at one level and breaking the river into blue pieces.
    grounds = [A.ground_height(d, nx, nz) for nx, nz in pts]
    beds, prev = [], None
    for g in grounds:
        lvl = g - dep
        lvl = lvl if prev is None else min(lvl, prev)
        beds.append(lvl)
        prev = lvl
    levels = [b + (1 - FREEBOARD) * dep for b in beds]  # the water at each node
    sd = _num(seed, 1)
    bank = max(0.5, 0.25 * w)
    nm = name or f'river {names[0]}-{names[-1]}'
    ids = []
    for i, (ln, cx, cz, ry) in enumerate(reaches):
        drop = levels[i + 1] - levels[i]  # = beds[i+1] - beds[i], <= 0
        _bed(
            d,
            'sculpt_channel',
            {
                'len': round(ln, 4),
                'w': round(w, 4),
                'depth': round(dep, 4),
                'meander': round(mea, 4),
                'seed': sd + i,
                'bank': round(bank, 4),
                'feather': 0,
                'level0': beds[i],
                'level1': beds[i + 1],
            },
            cx,
            cz,
            f'{nm} bed {i + 1}',
            ry,
        )
        rec = _water(
            d,
            'water_path',
            {
                'len': round(ln, 4),
                'w': round(w, 4),
                'meander': round(mea, 4),
                'seed': sd + i,
                'seg': 24,
                'level0': 0.0,
                'level1': drop,
            },
            cx,
            cz,
            levels[i],
            f'{nm} {i + 1}',
            ry,
        )
        ids.append(rec['id'])
    kindw = 'stream' if w <= MAX_STREAM_W else 'river'
    fall = levels[0] - levels[-1]
    held = sum(1 for i in range(1, len(beds)) if beds[i] > grounds[i] - dep + 1e-9)
    return (
        f'carved {nm}: {len(reaches)} reaches ({kindw}, {w:g} m wide, {dep:g} m deep), '
        f'{len(reaches)} sculpt_channel beds SET into the ground and {len(reaches)} water_path '
        f'surfaces ({ids[0]}..{ids[-1]}), each sloping with its bed. It falls {fall:.3f} m, '
        f'from {levels[0]:.3f} m at {names[0]} to {levels[-1]:.3f} m at {names[-1]}; '
        f'{held} node(s) were held down to the level above them so the water never climbs.'
    )


def t_fill_sea(d: Drawing, a, cell_from, cell_to, depth=8.0, level=-0.3, wave=0.15, seed=1, name=''):
    if the_ground(d) is None:
        return NO_GROUND_SEA
    try:
        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    except Exception as e:  # noqa: BLE001
        return f'refused: {e}'
    W, D = xmax - xmin, zmax - zmin
    if W < 2 or D < 2:
        return f'refused: {W:g} x {D:g} m is not a sea — give a block at least 2 m a side'
    if W > MAX_SEA_SIDE or D > MAX_SEA_SIDE:
        return f'refused: a sea is at most {MAX_SEA_SIDE:g} m a side, not {W:g} x {D:g} m'
    dep = _num(depth, 8.0)
    if dep <= 0 or dep > MAX_SEA_DEPTH:
        return f'refused: the sea bed is dug 0-{MAX_SEA_DEPTH:g} m below the land, not {dep:g} m'
    lvl = _num(level, -0.3)
    if lvl < -500 or lvl > 500:
        return 'refused: level is the sea datum in absolute metres, between -500 and 500'
    wv = clamp(_num(wave, 0.15), 0.0, 5.0)
    if not _room(d, 2):
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    sd = _num(seed, 1)
    nm = name or f'sea {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    bed = _bed(
        d,
        'sculpt_shelf',
        {'w': round(W, 4), 'd': round(D, 4), 'depth': round(dep, 4), 'feather': 0},
        cx,
        cz,
        nm + ' bed',
    )
    res = int(clamp(round(max(W, D) / 8.0), 8, 80))
    wat = _water(
        d,
        'water_plane',
        {'w': round(W, 4), 'd': round(D, 4), 'wave': round(wv, 4), 'seed': sd, 'res': res},
        cx,
        cz,
        lvl,
        nm,
    )
    return (
        f'filled {nm}: bed {bed["id"]} (sculpt_shelf, {W:g} x {D:g} m dished {dep:g} m into the '
        f'ground) and one flat sea {wat["id"]} (water_plane) at {lvl:g} m, swell {wv:g} m. '
        f'The shore is wherever the land climbs back through {lvl:g} m.'
    )


TOOLS = [
    (
        {
            'name': 'fill_lake',
            'description': (
                'Cut a lake bed into the sculpted ground and float its water on it: one sculpt_basin '
                '+ one water_body sharing a shoreline. The water lands at the ground height under the '
                'centre minus a fifth of the depth. Needs make_ground first.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string', 'description': 'cell at the middle of the lake, e.g. "F6"'},
                    'radius': {'type': 'number', 'description': 'metres, 5-120 (the x radius)'},
                    'radius_z': {'type': 'number', 'description': 'metres, 5-120; omit for a round lake'},
                    'depth': {'type': 'number', 'description': 'metres, 1-15'},
                    'irregularity': {'type': 'number', 'description': '0 a smooth ellipse, 0.9 a ragged shore'},
                    'seed': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_fill_lake,
    ),
    (
        {
            'name': 'carve_river',
            'description': (
                'Run a river or stream down a chain of cells on the sculpted ground: per leg one '
                'sculpt_channel bed + one water_path surface, each reach at or below the one before '
                'it so the water never climbs. Needs make_ground first.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'the cells it runs through, upstream first, e.g. ["B2","E5","J9"]',
                    },
                    'width': {'type': 'number', 'description': 'metres: a stream is 1-3, a river 3-30'},
                    'depth': {'type': 'number', 'description': 'metres, 0.3-4'},
                    'meander': {'type': 'number', 'description': 'metres of sideways wander per reach'},
                    'seed': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_carve_river,
    ),
    (
        {
            'name': 'fill_sea',
            'description': (
                'Dish a sea bed into the sculpted ground under a block of cells and lay one flat sea '
                'over it: one sculpt_shelf + one water_plane at an absolute level. Needs make_ground '
                'first.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'depth': {'type': 'number', 'description': 'metres the bed is dished below the land, 0-200'},
                    'level': {'type': 'number', 'description': 'the sea datum in absolute metres, default -0.3'},
                    'wave': {'type': 'number', 'description': 'swell in metres, 0-5'},
                    'seed': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_fill_sea,
    ),
]

EXAMPLES = [
    {
        'ask': 'a lake about 60 m across in the middle of the valley, at F6',
        'calls': [{'tool': 'fill_lake', 'args': {'centre': 'F6', 'radius': 30, 'depth': 4}}],
    },
    {
        'ask': 'a river running from B2 through E5 to J9, ten metres wide',
        'calls': [{'tool': 'carve_river', 'args': {'cells': ['B2', 'E5', 'J9'], 'width': 10, 'depth': 2}}],
    },
    {
        'ask': 'the sea along the west edge, A1 to C20',
        'calls': [{'tool': 'fill_sea', 'args': {'cell_from': 'A1', 'cell_to': 'C20', 'depth': 8}}],
    },
]
