# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""rivers_lakes — the assistant's NATURAL water tools.

Rivers and streams that meander, irregular lakes, waterfalls. Unlike
water_leisure's canal and pond (built water, quay walls, coping) these are
landscape: they DIG, so the record's `y` is the ground the water starts from
and the hole is in the parameters.

2026-09-07, the GROUND seam. Nothing lands at y=0 any more:
  R1  base_height defaults to None = "the ground under it" (place_height).
  R4  a river/stream reach takes the ground at its CENTRE and tilts by
      rz = atan((ground at the far cell - ground at the near cell) / len), so
      it visibly runs downhill; the chain never climbs (y = min(ground, the
      previous reach's downstream level)) and the reply says the total fall.
  R3  a lake is LEVEL water: y = the ground at its centre, and it is refused
      where the ground under the footprint varies more than 0.5 m.
  R5  a waterfall stands on the ground at its cell; `at_edge_of` names a
      cliff/plateau/escarpment record and puts the lip on ITS top with the
      pool on the ground below.
  R7  the real ranges: stream 1-3 m wide / 0.3-1 m deep, river 3-30 m /
      0.5-4 m, lake radius 5-120 m / 1-15 m deep, waterfall drop 2-60 m.

2026-09-07, the v3 SCULPTED ground. When the drawing has a `ground` record the
water is no longer a solid standing on the land — it is the land, cut:
  add_river / add_stream -> water_v3's carve_river (a sculpt_channel + a
      water_path per reach), so the valley is a valley and not a trough on top.
  add_lake              -> water_v3's fill_lake (a sculpt_basin + a water_body).
  add_waterfall          keeps its solid: a falling sheet is not a heightfield.
The R7 ranges below are checked FIRST on both paths, so a 2 m "river" is still
refused even though carve_river itself would take it. base_height does not apply
on a sculpted ground (the bed is cut into the ground) and the reply says so.
Without a ground every tool keeps the old solid behaviour, unchanged.

The meander offset, the lake rim factor and the bank/bed split below are the
SAME arithmetic as arch_ext/rivers_lakes.js and arch_blender_ext/rivers_lakes.py
— the value noise itself is the copy from terrain.py. The test evaluates these
functions and compares the numbers with the geometry the tab builds.
"""

from __future__ import annotations

import math
import types

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    cell_centre,
    cell_name,
    cell_of,
    ground_height,
    ground_plane,
    parse_cell,
    place_height,
    world_to_local,
)

KINDS = {
    'river': {'len': 60, 'w': 12, 'depth': 2, 'meander': 6, 'seed': 1, 'bank': 2, 'seg': 24},
    'lake': {'rx': 30, 'rz': 20, 'depth': 3, 'wobble': 0.25, 'seed': 1, 'seg': 48, 'shore': 3, 'rim': 1},
    'waterfall': {'w': 8, 'h': 12, 'depth': 2, 'pool_r': 8},
}
OPENINGS: list = []

PROMPT = (
    'Natural water (rivier, beek, meer, waterval) lands on the GROUND under it and digs below that; '
    'base_height only overrides. With a sculpted ground add_river/add_stream/add_lake cut the land ITSELF '
    '— a channel or basin plus a water surface — so a valley stays a valley and base_height does not '
    'apply; without one, the old solid. add_river(cells, width, depth, meander, seed) draws one '
    'meandering reach per pair of consecutive cells (three cells = two reaches, joined end to end); each '
    'reach runs downhill and the chain never climbs, so list the cells going downhill. Width is bank to '
    'bank: a river is 3-30 m wide and up to 4 m deep, add_stream(cells) the same 1-3 m and 0.3-1 m; '
    'meander is the sideways wander (never over twice the width). add_lake(centre, radius, radius_z, '
    'depth, irregularity) digs one irregular basin — LEVEL water, so on unsculpted land it is refused '
    'where the ground varies over 0.5 m: flatten_pad it first, put it lower, or use a river. '
    'add_waterfall(cell, height, width, direction_deg) always keeps its solid; at_edge_of takes a cliff '
    'or plateau id and hangs the lip on its top.'
)

_DEFAULT_MAT = {'river': 'mat_gravel', 'lake': 'mat_soil', 'waterfall': 'mat_rock'}

# ── the real-world ranges (R7) — the same numbers the refusals quote ─────────
CHANNEL = {'river': (3.0, 30.0, 0.5, 4.0), 'stream': (1.0, 3.0, 0.3, 1.0)}
MIN_LAKE_R, MAX_LAKE_R = 5.0, 120.0
MIN_LAKE_DEPTH, MAX_LAKE_DEPTH = 1.0, 15.0
MIN_FALL_H, MAX_FALL_H = 2.0, 60.0
MIN_FALL_W, MAX_FALL_W = 0.5, 60.0
# R3: how much the ground may vary under level water before it is refused
LEVEL_TOL = 0.5
# R4: a reach may not run uphill by more than this — past it the water pools level
UPHILL_TOL = 0.5
# the top of the bank slope that reads as grass; the rest of the bank and the
# whole bed are gravel (the JS and the Blender copies use the same fraction)
BANK_GRASS = 0.4


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


def meander_offset(t: float, meander: float, seed: float) -> float:
    """The river centreline's sideways offset in metres at t along the reach.
    sin(pi*t) is the envelope, so the offset is exactly 0 at t=0 and t=1 —
    that is what makes consecutive reaches meet."""
    return (
        meander
        * math.sin(math.pi * t)
        * (0.6 * math.sin(2 * math.pi * t * 1.5) + 0.4 * (2 * value_noise(t * 4, seed, seed) - 1))
    )


def channel_section(w: float, dep: float, bank: float) -> list:
    """The channel's cross-section, outer bank to outer bank: [(z, y), ...].
    Six points, so the top BANK_GRASS of each bank slope is its own strip
    (grass) and the rest of the bank plus the bed is one strip (gravel).
    The JS and the Blender copies build exactly these points."""
    g = BANK_GRASS
    return [
        (-(w / 2 + bank), 0.0),
        (-(w / 2 + bank * (1 - g)), -g * dep),
        (-w / 2, -dep),
        (w / 2, -dep),
        (w / 2 + bank * (1 - g), -g * dep),
        (w / 2 + bank, 0.0),
    ]


def lake_factor(a: float, wobble: float, seed: float) -> float:
    """The lake rim's radius multiplier at plan angle a (radians)."""
    return 1 + wobble * (2 * value_noise(math.cos(a) * 2 + 2, math.sin(a) * 2 + 2, seed) - 1)


def lake_shore(rx: float, rz: float, wobble: float, shore: float) -> float:
    """The shore band, clamped so the bed keeps a positive radius."""
    return max(0.05, min(shore, min(rx, rz) * (1 - wobble) * 0.4))


def lake_rim(rx: float, rz: float, wobble: float, shore: float, rim: float) -> float:
    """The SAND band: the outermost `rim` metres of the shore, never wider than
    the shore itself. 1 m by default — a wide sand ring reads as a beach."""
    return max(0.05, min(max(0.05, rim), lake_shore(rx, rz, wobble, shore)))


def river_z_extent(w: float, bank: float, meander: float, seed: float, seg: int = 24) -> float:
    """How wide the reach is across z once the wander is counted — the number
    the tab's bounding box must agree with."""
    offs = [meander_offset(i / seg, meander, seed) for i in range(seg + 1)]
    return (max(offs) - min(offs)) + w + 2 * bank


def lake_x_extent(rx: float, wobble: float, seed: float, seg: int = 48) -> float:
    """The lake's span across x (the sand rim's outer edge)."""
    xs = [rx * math.cos(2 * math.pi * i / seg) * lake_factor(2 * math.pi * i / seg, wobble, seed) for i in range(seg)]
    return max(xs) - min(xs)


# ── the v3 seam ─────────────────────────────────────────────────────────────
def the_ground(d):
    """The drawing's one `ground` record, or None. A hidden ground is no ground:
    hiding it in the outliner puts every tool back on the old solid path."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') == 'ground' and not o.get('hidden'):
            return o
    return None


def _water_tool(name: str):
    """water_v3's tool function, or None if that family is not installed.

    load_extensions() walks arch_assistant_ext/ alphabetically, so water_v3 is
    NOT in EXT_MODULES while this module is being imported — the lookup has to
    happen at call time."""
    mod = A.EXT_MODULES.get('water_v3')
    return getattr(mod, name, None) if mod else None


def _given(base_height) -> bool:
    return not (base_height is None or base_height == '')


def _bh_note(base_height) -> str:
    return ' (base_height does not apply to a sculpted ground)' if _given(base_height) else ''


# ── helpers ─────────────────────────────────────────────────────────────────
def _mat(m, kind):
    return m if m in MATERIALS else _DEFAULT_MAT.get(kind, 'mat_soil')


def _room(d: Drawing, n: int):
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} more objects and the drawing may hold {MAX_OBJECTS} in total'
    return None


def _cells(cells):
    """['C4','H4'] -> [(x, z), ...] world centres, or raise ValueError."""
    if isinstance(cells, str):
        cells = [c for c in cells.replace(';', ',').split(',') if c.strip()]
    if not isinstance(cells, (list, tuple)) or not cells:
        raise ValueError('pass a list of cells, like ["C4", "H4", "H9"]')
    return [cell_centre(*parse_cell(c)) for c in cells]


def ground_without(d, x: float, z: float, skip_id: str) -> float:
    """The ground under (x, z) ignoring ONE record — the ground at the foot of a
    cliff is the ground the cliff stands on, not the cliff's own top."""
    return ground_height(types.SimpleNamespace(objs=[o for o in d.objs if o['id'] != skip_id]), x, z)


def ground_variation(d, cx: float, cz: float, w: float, dd: float, n: int = 5) -> float:
    """max - min of the ground sampled on an n x n lattice over a w x dd
    footprint centred on (cx, cz). The second half of the R3 level test."""
    hs = [
        ground_height(d, cx - w / 2 + (i + 0.5) * w / n, cz - dd / 2 + (j + 0.5) * dd / n)
        for j in range(n)
        for i in range(n)
    ]
    return max(hs) - min(hs)


def _channel_refusal(w, dep, mea, what):
    lo, hi, dlo, dhi = CHANNEL[what]
    if w < lo or w > hi:
        return f'refused: a real {what} is between {lo:g} and {hi:g} m wide, so {w:g} m is not one'
    if dep < dlo or dep > dhi:
        return f'refused: a real {what} is between {dlo:g} and {dhi:g} m deep, so {dep:g} m is not one'
    if mea < 0:
        return 'refused: meander is a distance in metres, so it cannot be negative'
    if mea > w * 2:
        return (
            f'refused: a meander of {mea:g} m on a {w:g} m {what} would fold the channel back over '
            f'itself — keep it under {w * 2:g} m'
        )
    return None


def _run_channel(d: Drawing, cells, w, dep, mea, seed, bank, base_height, material, name, what):
    """One record per pair of consecutive cells. Shared by add_river/add_stream.

    R4: y = the ground at the reach centre, rz = atan(fall / len) so the reach
    runs downhill (local +X points from cell i to cell i+1, and a positive rz
    lifts +X, so a reach going down has rz < 0), and the water never climbs:
    a reach the ground carries uphill by more than UPHILL_TOL is laid level
    instead, and no reach starts higher than the last one's downstream end."""
    try:
        pts = _cells(cells)
    except ValueError as e:
        return f'refused: {e}'
    if len(pts) < 2:
        return f'refused: a {what} needs at least two cells — one reach is drawn between each pair'
    bad = _channel_refusal(w, dep, mea, what)
    if bad:
        return bad
    # v3: the ranges above are checked FIRST (carve_river's own are looser), then
    # the cut is handed to water_v3 so the channel is the ground, not a trough on it
    if the_ground(d) is not None:
        carve = _water_tool('t_carve_river')
        if carve is not None:
            txt = carve(d, {}, cells=cells, width=w, depth=dep, meander=mea, seed=seed, name=name or what)
            if txt.startswith('refused'):
                return txt
            return (
                txt + f' The ground is sculpted, so this {what} is the land cut open — a '
                'sculpt_channel bed and a water_path surface per reach, no solid `river` record'
                + _bh_note(base_height)
                + ('; material does not apply to a cut bed' if material else '')
                + '.'
            )
    full = _room(d, len(pts) - 1)
    if full:
        return full
    grp = name or what
    ids, total = [], 0.0
    top, prev_down = None, None
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: cells {i + 1} and {i + 2} are the same — every reach needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        rise = ground_height(d, x1, z1) - ground_height(d, x0, z0)
        # rz = atan(fall / len); a reach the ground carries UPHILL is laid level instead
        rz = math.atan2(rise, L) if rise <= UPHILL_TOL else 0.0
        y = place_height(d, cx, cz, base_height)
        if prev_down is not None:
            y = min(y, prev_down)  # a river never runs uphill
        o = d.new(
            'river',
            {
                'len': round(L, 4),
                'w': round(w, 3),
                'depth': round(dep, 3),
                'meander': round(mea, 3),
                'seed': _num(seed, 1) + i,
                'bank': round(bank, 3),
                'seg': 24,
            },
            cx,
            cz,
            y,
            ry,
            _mat(material, 'river'),
            name=f'{what} reach {i + 1}',
            grp=grp,
        )
        o['rz'] = round(rz, 6)
        half = L / 2 * math.sin(rz)
        if top is None:
            top = y - half
        prev_down = y + half
        ids.append(o['id'])
        total += L
    fall = top - prev_down
    flow = (
        f'running downhill {fall:.1f} m over {total:.0f} m'
        if fall > 0.05
        else 'over level ground, so it barely flows — send the cells downhill'
    )
    return (
        f'cut {what} "{grp}": {len(ids)} reach(es) {ids[0]}..{ids[-1]}, {total:.1f} m in all, '
        f'{w:g} m wide, {dep:g} m deep, grass banks over a gravel bed, wandering up to {mea:g} m '
        f'sideways, {flow}'
        + (f'; base_height held it at {_num(base_height, 0):g} m' if base_height is not None else '')
    )


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_river(
    d: Drawing, a, cells, width=12.0, depth=2.0, meander=6.0, seed=1, base_height=None, material='', name=''
):
    return _run_channel(
        d,
        cells,
        _num(width, 12.0),
        _num(depth, 2.0),
        _num(meander, 6.0),
        seed,
        2.0,
        base_height,
        material,
        name,
        'river',
    )


def t_add_stream(
    d: Drawing, a, cells, width=2.0, depth=0.5, meander=2.0, seed=1, base_height=None, material='', name=''
):
    return _run_channel(
        d,
        cells,
        _num(width, 2.0),
        _num(depth, 0.5),
        _num(meander, 2.0),
        seed,
        0.8,
        base_height,
        material,
        name,
        'stream',
    )


def t_add_lake(
    d: Drawing,
    a,
    centre,
    radius=30.0,
    radius_z=None,
    depth=3.0,
    irregularity=0.25,
    seed=1,
    base_height=None,
    material='',
    name='',
):
    rx = _num(radius, 30.0)
    rz = _num(radius_z, rx) if radius_z is not None else rx
    for r in (rx, rz):
        if r < MIN_LAKE_R or r > MAX_LAKE_R:
            return (
                f'refused: a lake radius is between {MIN_LAKE_R:g} and {MAX_LAKE_R:g} m '
                f'({r:g} m is a puddle or an inland sea) — use add_pond for something smaller'
            )
    dep = _num(depth, 3.0)
    if dep < MIN_LAKE_DEPTH or dep > MAX_LAKE_DEPTH:
        return f'refused: a lake is between {MIN_LAKE_DEPTH:g} and {MAX_LAKE_DEPTH:g} m deep'
    wob = max(0.0, min(0.9, _num(irregularity, 0.25)))
    # v3: the basin is dug into the one ground, so there is nothing to level-check
    if the_ground(d) is not None:
        fill = _water_tool('t_fill_lake')
        if fill is not None:
            txt = fill(
                d,
                {},
                centre=centre,
                radius=rx,
                radius_z=rz,
                depth=dep,
                irregularity=wob,
                seed=seed,
                name=name or 'lake',
            )
            if txt.startswith('refused'):
                return txt
            return (
                txt + ' The ground is sculpted, so this lake is a sculpt_basin cut into the land '
                'under a water_body, not a solid lake record, and no level check is needed — the '
                'bed is dug flat wherever the land was'
                + _bh_note(base_height)
                + ('; material does not apply to a cut basin' if material else '')
                + '.'
            )
    full = _room(d, 1)
    if full:
        return full
    cx, cz = cell_centre(*parse_cell(centre))
    # R3 — a lake is LEVEL water: refuse a footprint the ground does not lie flat under
    if base_height is None:
        _y0, _gx, _gz, spread = ground_plane(d, cx, cz, 2 * rx, 2 * rz, 0.0, n=5)
        var = ground_variation(d, cx, cz, 2 * rx, 2 * rz, 5)
        if spread > LEVEL_TOL or var > LEVEL_TOL:
            return (
                f'refused: the ground under {cell_of(cx - rx, cz - rz)}..{cell_of(cx + rx, cz + rz)} '
                f'rises {max(spread, var):.1f} m — water lies level; flatten_pad it, put it lower on '
                'the slope, or use add_stream/add_river for water that flows'
            )
    y = place_height(d, cx, cz, base_height)
    shore = round(max(1.0, min(8.0, min(rx, rz) * 0.15)), 3)
    o = d.new(
        'lake',
        {
            'rx': round(rx, 3),
            'rz': round(rz, 3),
            'depth': round(dep, 3),
            'wobble': round(wob, 4),
            'seed': _num(seed, 1),
            'seg': 48,
            'shore': shore,
            'rim': 1,
        },
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'lake'),
        name=name or 'lake',
        grp=name or 'lake',
    )
    return (
        f'lake {o["id"]} at {cell_name(*parse_cell(centre))}: about {2 * rx:g} x {2 * rz:g} m across, '
        f'{dep:g} m deep, a 1 m sand rim on {shore:g} m of shore, irregularity {wob:g}, '
        f'water level at {y:g} m'
    )


def t_add_waterfall(
    d: Drawing, a, cell, height=None, width=8.0, direction_deg=0, base_height=None, at_edge_of='', material='', name=''
):
    w = _num(width, 8.0)
    if w < MIN_FALL_W or w > MAX_FALL_W:
        return f'refused: a waterfall is between {MIN_FALL_W:g} and {MAX_FALL_W:g} m wide'
    cx, cz = cell_centre(*parse_cell(cell))
    lip = None
    if at_edge_of:
        rec = d.find(str(at_edge_of))
        if rec is None:
            return f'refused: there is no record {at_edge_of} in the drawing to hang the waterfall on'
        fn = A.EXT_HEIGHTS.get(rec['kind'])
        if fn is None:
            return (
                f'refused: {at_edge_of} is a {rec["kind"]}, which has no top surface to fall from — '
                'name a cliff, a plateau or an escarpment'
            )
        sc = rec.get('s') or 1.0
        lx, lz = world_to_local(rec, cx, cz)
        top = fn(rec['p'], lx / sc, lz / sc)
        if top is None:
            return (
                f'refused: {cell_name(*parse_cell(cell))} is not on {at_edge_of} — put the waterfall '
                'on a cell the cliff actually covers'
            )
        lip = rec['y'] + top * sc
        base = ground_without(d, cx, cz, rec['id'])
        h = _num(height, lip - base) if height is not None else lip - base
        y = base if base_height is None else _num(base_height, base)
    else:
        h = _num(height, 12.0)
        y = place_height(d, cx, cz, base_height)
    if h < MIN_FALL_H or h > MAX_FALL_H:
        return f'refused: a waterfall drops between {MIN_FALL_H:g} and {MAX_FALL_H:g} m' + (
            f', and {at_edge_of} stands {h:.1f} m over the ground here' if lip is not None else ''
        )
    full = _room(d, 1)
    if full:
        return full
    pool_r = round(max(4.0, w), 3)
    o = d.new(
        'waterfall',
        {'w': round(w, 3), 'h': round(h, 3), 'depth': 2, 'pool_r': pool_r},
        cx,
        cz,
        y,
        math.radians(_num(direction_deg, 0)),
        _mat(material, 'waterfall'),
        name=name or 'waterfall',
        grp=name or 'waterfall',
    )
    return (
        f'waterfall {o["id"]} at {cell_name(*parse_cell(cell))}: {h:g} m drop, {w:g} m wide, '
        f'falling toward {_num(direction_deg, 0):g} deg into a {2 * pool_r:g} m plunge pool; '
        f'the pool sits at {y:g} m and the lip at {y + h:g} m'
        + (f' on {at_edge_of}' if lip is not None else '')
        + (
            '. A falling sheet is not a heightfield, so a waterfall keeps its solid even on a sculpted ground.'
            if the_ground(d) is not None
            else ''
        )
    )


TOOLS = [
    (
        {
            'name': 'add_river',
            'description': 'A meandering natural river along a chain of cells: one reach between each pair of consecutive cells, so three cells give two reaches that meet exactly. Each reach lands on the ground under it and tilts to run downhill, and the chain never climbs — list the cells going downhill. The channel is cut into the ground: a gravel bed `width` wide at -depth, grass banks sloping up to ground level, water just under it. With a sculpted ground it cuts the land itself instead (a sculpt_channel bed and a water_path surface per reach) and base_height does not apply. A real river is 3-30 m wide and 0.5-4 m deep.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'meander': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'metres; leave it out and every reach sits on the ground under it',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_river,
    ),
    (
        {
            'name': 'add_stream',
            'description': 'A small brook along a chain of cells — add_river with a 2 m bed, 0.5 m deep and a 2 m wander, on the ground and running downhill. Use for a garden stream, a ditch, a mountain beck. With a sculpted ground it cuts the land itself instead. A real stream is 1-3 m wide and 0.3-1 m deep.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'meander': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'metres; leave it out and every reach sits on the ground under it',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_stream,
    ),
    (
        {
            'name': 'add_lake',
            'description': 'One irregular lake basin around a centre cell: radius is the half-width across x, radius_z across z (leave it out for a round one), irregularity is how far the rim strays from that ellipse. A sloping shore with a 1 m sand rim, water at the ground level of the centre. Lake water is LEVEL: on unsculpted land the call is refused where the ground under the footprint varies more than 0.5 m — flatten_pad it first or use add_river. With a sculpted ground the basin is dug into the land instead (a sculpt_basin under a water_body), so no level check applies and neither does base_height. A lake radius is 5-120 m and it is 1-15 m deep.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'radius_z': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'irregularity': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'metres; leave it out and the lake takes the ground under its centre (and is level-checked)',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_lake,
    ),
    (
        {
            'name': 'add_waterfall',
            'description': "A waterfall on one cell: a rock lip, a sheet of water `height` metres tall and `width` wide, and a round plunge pool at the foot. The pool sits on the ground under the cell and the lip stands height metres over it. The water falls toward direction_deg (0 = east, 90 = north). at_edge_of takes the id of a cliff, plateau or escarpment: the lip is then hung on that record's top at this cell and the height is the real drop to the ground below. A waterfall always keeps its solid, sculpted ground or not — a falling sheet is not a heightfield. A waterfall drops 2-60 m.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'direction_deg': {'type': 'number'},
                    'at_edge_of': {
                        'type': 'string',
                        'description': 'record id of a cliff / plateau / escarpment to hang the lip on',
                    },
                    'base_height': {
                        'type': 'number',
                        'description': 'metres; leave it out and the plunge pool sits on the ground',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_add_waterfall,
    ),
]

EXAMPLES = [
    {
        'ask': 'run a river through the site from C4 east to H4 and then south to H9, about 12 m wide',
        'calls': [{'tool': 'add_river', 'args': {'cells': ['C4', 'H4', 'H9'], 'width': 12, 'depth': 2, 'meander': 6}}],
    },
    {
        'ask': 'a little stream winding down the hillside, D20 to J20 to J26',
        'calls': [{'tool': 'add_stream', 'args': {'cells': ['D20', 'J20', 'J26']}}],
    },
    {
        'ask': 'a lake about 60 by 40 metres around P30, 3 m deep, with a really ragged shoreline',
        'calls': [
            {'tool': 'flatten_pad', 'args': {'cell_from': 'M27', 'cell_to': 'S33'}},
            {
                'tool': 'add_lake',
                'args': {'centre': 'P30', 'radius': 30, 'radius_z': 20, 'depth': 3, 'irregularity': 0.45},
            },
        ],
    },
    {
        'ask': 'a waterfall off the escarpment at K12 pouring east, and a river carrying the water away to R12',
        'calls': [
            {'tool': 'add_waterfall', 'args': {'cell': 'K12', 'width': 8, 'direction_deg': 0, 'at_edge_of': 'o7'}},
            {'tool': 'add_river', 'args': {'cells': ['K12', 'R12'], 'width': 8, 'depth': 1.5}},
        ],
    },
    {
        'ask': 'the valley floor is 4 m above the site datum — put the river along it from B8 to N8',
        'calls': [{'tool': 'add_river', 'args': {'cells': ['B8', 'N8'], 'width': 10, 'base_height': 4}}],
    },
]
