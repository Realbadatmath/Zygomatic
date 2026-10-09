# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3: the five tools — make_ground, raise_ground, lower_ground,
level_ground and describe_ground."""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_name,
    cell_of,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    footprint_level,
    sculpts_of,
)

from .constants import (
    RES_MAX,
    RES_MIN,
    FEATHER_FRAC,
    STYLE_AMP,
    PEAK_H_FRAC,
    MESA_H_FRAC,
    TROUGH_FRAC,
    LEVEL_BATTER,
)

from .field import (
    clamp,
    _N,
    lattice,
)


# ── tools ────────────────────────────────────────────────────────────────────
def the_ground(d):
    for o in d.objs:
        if o['kind'] == 'ground':
            return o
    return None


def _mat(m, default='mat_grass'):
    return m if m in MATERIALS else default


def _block(cell_from, cell_to):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    return xmin, zmin, xmax, zmax, xmax - xmin, zmax - zmin, (xmin + xmax) / 2, (zmin + zmax) / 2


def _res_for(w, dd) -> int:
    return int(clamp(round(max(w, dd) / 2.0), 24, RES_MAX))


def t_make_ground(
    d: Drawing, a, cell_from, cell_to, style='gentle', seed=1, snow_height=60.0, water_level=-0.15, material='', name=''
):
    st = str(style or 'gentle').strip().lower()
    if st not in STYLE_AMP:
        return "refused: style must be 'flat', 'gentle' or 'rolling'"
    if the_ground(d) is not None:
        g = the_ground(d)
        return (
            f'refused: this drawing already has a ground ({g["id"]}, {_N(g["p"], "w", 0):g} x '
            f'{_N(g["p"], "d", 0):g} m) — a drawing has exactly one. Shape it with raise_ground, '
            f'lower_ground and level_ground instead.'
        )
    xmin, zmin, xmax, zmax, W, D, cx, cz = _block(cell_from, cell_to)
    if W < 2 or D < 2:
        return f'refused: {W:g} x {D:g} m is not a landscape — give a block at least 2 m a side'
    snow = _num(snow_height, 60.0)
    if snow < -100 or snow > 9000:
        return 'refused: snow_height is an absolute height in metres, between -100 and 9000'
    water = _num(water_level, -0.15)
    if water < -500 or water > 500:
        return 'refused: water_level is an absolute height in metres, between -500 and 500'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    res = _res_for(W, D)
    o = d.new(
        'ground',
        {
            'w': round(W, 4),
            'd': round(D, 4),
            'res': res,
            'seed': _num(seed, 1),
            'base': 0,
            'amp': STYLE_AMP[st],
            'snow_h': round(snow, 3),
            'water_h': round(water, 4),
            'grass_max_slope': 32,
        },
        cx,
        cz,
        0.0,
        0.0,
        _mat(material),
        name=name or f'ground {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}',
        grp=name or 'ground',
    )
    return (
        f'laid the ground {o["id"]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))}: {W:g} x {D:g} m, {st}, {res}x{res} cells '
        f'({(res + 1) ** 2} vertices), seed {_num(seed, 1):g}, snow above {snow:g} m, water at '
        f'{water:g} m. Every landform from here on is a sculpt of THIS surface — '
        f'raise_ground, lower_ground, level_ground.'
    )


def _need_ground(d):
    g = the_ground(d)
    if g is None:
        return None, 'refused: there is no ground yet — call make_ground(cell_from, cell_to) first'
    return g, ''


def _sculpt(d, kind, p, x, z, nm, y=0.0, ry=0.0):
    return d.new(kind, p, x, z, y, ry, 'mat_soil', name=nm, grp='ground sculpts')


def t_raise_ground(d: Drawing, a, cell_from, cell_to, height=30.0, shape='peak', seed=1, name=''):
    g, err = _need_ground(d)
    if err:
        return err
    sh = str(shape or 'peak').strip().lower()
    if sh not in ('peak', 'ridge', 'mesa'):
        return "refused: shape must be 'peak' (a summit), 'ridge' (a crest) or 'mesa' (a flat top)"
    h = _num(height, 30.0)
    if h <= 0 or h > 3000:
        return 'refused: height is metres above the ground around it, between 0 and 3000'
    xmin, zmin, xmax, zmax, W, D, cx, cz = _block(cell_from, cell_to)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    sd = _num(seed, 1)
    at = cell_of(cx, cz)
    if sh == 'peak':
        r = min(W, D) / 2
        lo, hi = PEAK_H_FRAC[0] * r, PEAK_H_FRAC[1] * r
        if h < lo or h > hi:
            return (
                f'refused: a peak on a {2 * r:g} m footprint is {lo:.1f}-{hi:.1f} m tall — {h:g} m is a '
                f'needle above that and a hill below it. Widen the block or use lower_ground/level_ground.'
            )
        o = _sculpt(
            d,
            'sculpt_peak',
            {'r': round(r, 3), 'h': round(h, 3), 'rug': 0.45, 'seed': sd, 'feather': round(FEATHER_FRAC * r, 3)},
            cx,
            cz,
            f'peak {h:g} m at {at}',
        )
        what = f'a summit {2 * r:g} m across'
    elif sh == 'mesa':
        r = min(W, D) / 2
        if h > MESA_H_FRAC * r:
            return (
                f'refused: a mesa on a {2 * r:g} m footprint is at most {MESA_H_FRAC * r:.1f} m tall — '
                f'{h:g} m would be a tower, not a table mountain'
            )
        o = _sculpt(
            d,
            'sculpt_mesa',
            {
                'r': round(r, 3),
                'h': round(h, 3),
                'top_r': round(r * 0.7, 3),
                'rug': 0.25,
                'seed': sd,
                'feather': round(FEATHER_FRAC * r, 3),
            },
            cx,
            cz,
            f'mesa {h:g} m at {at}',
        )
        what = f'a flat top {1.4 * r:g} m across inside a {2 * r:g} m flank'
    else:
        ln, w = (W, D) if W >= D else (D, W)
        ry = 0.0 if W >= D else math.pi / 2
        if h > 0.8 * w:
            return (
                f'refused: a ridge {w:g} m wide is at most {0.8 * w:.1f} m tall — {h:g} m is a wall. '
                f'Widen the block across the crest.'
            )
        o = _sculpt(
            d,
            'sculpt_ridge',
            {
                'len': round(ln, 3),
                'w': round(w, 3),
                'h': round(h, 3),
                'rug': 0.35,
                'seed': sd,
                'feather': round(FEATHER_FRAC * ln / 2, 3),
            },
            cx,
            cz,
            f'ridge {h:g} m at {at}',
            ry=ry,
        )
        what = f'a crest {ln:g} m long and {w:g} m wide'
    if name:
        o['name'] = name
    return (
        f'raised the ground: {o["id"]} {o["kind"]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))} — {what}, {h:g} m above the land around it, feathered into '
        f'it at the rim. The ground {g["id"]} now carries it; nothing new stands on the lawn.'
    )


def t_lower_ground(d: Drawing, a, cell_from, cell_to, depth=8.0, shape='valley', profile=0.0, seed=1, name=''):
    g, err = _need_ground(d)
    if err:
        return err
    sh = str(shape or 'valley').strip().lower()
    if sh not in ('valley', 'basin'):
        return "refused: shape must be 'valley' (a trough a river runs down) or 'basin' (a lake bed)"
    dep = _num(depth, 8.0)
    if dep <= 0 or dep > 2000:
        return 'refused: depth is metres below the ground around it, between 0 and 2000'
    xmin, zmin, xmax, zmax, W, D, cx, cz = _block(cell_from, cell_to)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    sd = _num(seed, 1)
    at = cell_of(cx, cz)
    across = min(W, D)
    if dep > TROUGH_FRAC * across:
        return (
            f'refused: a hollow {across:g} m across is at most {TROUGH_FRAC * across:.1f} m deep — '
            f'{dep:g} m would be a shaft. Widen the block or cut it in two steps.'
        )
    if sh == 'valley':
        ln, w = (W, D) if W >= D else (D, W)
        ry = 0.0 if W >= D else math.pi / 2
        o = _sculpt(
            d,
            'sculpt_cut',
            {
                'len': round(ln, 3),
                'w': round(w, 3),
                'depth': round(dep, 3),
                'floor_w': round(w * 0.25, 3),
                'profile': round(clamp(_num(profile, 0.0), 0.0, 1.0), 3),
                'feather': round(FEATHER_FRAC * ln / 2, 3),
            },
            cx,
            cz,
            f'valley {dep:g} m at {at}',
            ry=ry,
        )
        what = f'a trough {ln:g} m long, {w:g} m wide, floor {w * 0.25:g} m'
    else:
        o = _sculpt(
            d,
            'sculpt_basin',
            {
                'rx': round(W / 2, 3),
                'rz': round(D / 2, 3),
                'depth': round(dep, 3),
                'wobble': 0.25,
                'seed': sd,
                'shore': round(max(0.5, across * 0.12), 3),
                'feather': 0,
            },
            cx,
            cz,
            f'basin {dep:g} m at {at}',
        )
        what = f'a bed {W:g} x {D:g} m with a wobbled shore'
    if name:
        o['name'] = name
    return (
        f'lowered the ground: {o["id"]} {o["kind"]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))} — {what}, {dep:g} m into the land, its walls following the '
        f'ground it cuts through. Put the water on it with a water tool if it should hold any.'
    )


def t_level_ground(d: Drawing, a, cell_from, cell_to, level=None, name=''):
    g, err = _need_ground(d)
    if err:
        return err
    xmin, zmin, xmax, zmax, W, D, cx, cz = _block(cell_from, cell_to)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    if level is None or level == '':
        lvl, off = footprint_level(d, cx, cz, W, D)
        lvl = round(lvl, 4)
        how = f'the mean ground there ({lvl:g} m, {off:.2f} m out of level before)'
    else:
        lvl = round(_num(level, 0.0), 4)
        how = f'{lvl:g} m'
    fe = round(max(0.5, LEVEL_BATTER * min(W, D)), 3)
    o = _sculpt(
        d,
        'sculpt_flat',
        {'w': round(W + 2 * fe, 4), 'd': round(D + 2 * fe, 4), 'level': lvl, 'feather': fe},
        cx,
        cz,
        name or f'level {lvl:g} m at {cell_of(cx, cz)}',
    )
    return (
        f'levelled the ground: {o["id"]} sculpt_flat over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))} — {W:g} x {D:g} m pulled to {how}, cut AND fill, '
        f'battered {fe:g} m into the land around it. Build on it flat.'
    )


def t_describe_ground(d: Drawing, a):
    g = the_ground(d)
    if g is None:
        return 'there is no ground in this drawing — call make_ground(cell_from, cell_to) to lay one'
    p = g['p']
    w, dd = _N(p, 'w', 200.0), _N(p, 'd', 200.0)
    hs, _sd = lattice(p, d.objs, g['x'], g['z'], _num(g.get('ry'), 0.0))
    flat = [v for row in hs for v in row]
    lo, hi = min(flat), max(flat)
    scs = sculpts_of(d)
    lines = [
        f'ground {g["id"]}: {w:g} x {dd:g} m over {cell_of(g["x"] - w / 2, g["z"] - dd / 2)}..'
        f'{cell_of(g["x"] + w / 2 - 1e-6, g["z"] + dd / 2 - 1e-6)}, '
        f'{int(clamp(round(_N(p, "res", 100.0)), RES_MIN, RES_MAX))} cells a side, '
        f'base roll {_N(p, "amp", 1.5):g} m (seed {_N(p, "seed", 1):g})',
        f'height {lo:.2f} m to {hi:.2f} m (relief {hi - lo:.2f} m); water {_N(p, "water_h", -0.15):g} m, '
        f'snow above {_N(p, "snow_h", 60.0):g} m, rock over {_N(p, "grass_max_slope", 32.0):g} deg',
    ]
    if not scs:
        lines.append('no sculpts: this is the bare base roll')
    else:
        lines.append(f'{len(scs)} sculpt(s):')
        for o in scs[:60]:
            lines.append(f'  {o["id"]} {o["kind"]} "{o["name"]}" at {cell_of(o["x"], o["z"])}')
        if len(scs) > 60:
            lines.append(f'  ... and {len(scs) - 60} more')
    return '\n'.join(lines)
