# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The drawing tools — boxes, walls, slabs, roofs, windows.

Moved verbatim out of the old single-file arch_assistant.py (lines 768-1073).
"""

from __future__ import annotations

import math


# ── the tools ───────────────────────────────────────────────────────────────
def _wall_world(w: dict, u: float) -> tuple:
    """A point at distance u along a wall (0 = its -X end) in world x, z."""
    L = _num(w['p'].get('len'), 4)
    lx = u - L / 2
    return w['x'] + lx * math.cos(w['ry']), w['z'] - lx * math.sin(w['ry'])


def t_draw_box(
    d: Drawing,
    a,
    cell_from='',
    cell_to='',
    storeys=1,
    storey_from=0,
    slabs=True,
    roof='none',
    material='',
    wall_h=None,
    wall_t=None,
    name='',
    base_height=None,
    centre=None,
    width=None,
    depth=None,
    floor_material='',
    roof_material='',
):
    cell_from, cell_to = resolve_block(cell_from, cell_to, centre, width, depth)  # ValueError -> refused
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    H = _num(wall_h, d.storey_h) or d.storey_h
    T = _num(wall_t, d.wall_t) or d.wall_t
    mat = material if material in MATERIALS else 'mat_concrete'
    # 2026-09-10: walls, floors and the roof deck are three finishes, not one.
    f_mat = finish_mat(d, 'floor', floor_material)
    r_mat = finish_mat(d, 'roof', roof_material)
    grp = name or f'box {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    b0, note = footprint_base(d, cx, cz, W, D, 0.0, base_height)
    if s0 > 0 and base_height in (None, ''):
        # "storey 20 on a 20-storey box" is the ROOF DECK (roof y + thickness), not roof y
        y0 = b0 + s0 * H
        top, deck = deck_top(d, cx, cz, y0)
        if deck is not None and top > y0 + 1e-6:
            b0 += top - y0
            note += f'storey {s0} is the deck of {deck["id"]} at {top:g} m (lifted {top - y0:g} m). '
    need = n * (4 + (1 if slabs else 0)) + (1 if roof != 'none' else 0)
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    sides = {}
    for k in range(n):
        y = b0 + (s0 + k) * H
        for side, (x, z, L, ry) in {
            'north': (cx, zmin, W, 0.0),
            'south': (cx, zmax, W, 0.0),
            'west': (xmin, cz, D, math.pi / 2),
            'east': (xmax, cz, D, math.pi / 2),
        }.items():
            w = d.new(
                'wall',
                _with_base({'len': round(L, 4), 'h': H, 't': T}, b0),
                x,
                z,
                y,
                ry,
                mat,
                name=f'{side} wall st{s0 + k}',
                grp=grp,
            )
            sides.setdefault(side, []).append(w['id'])
        if slabs:
            d.new(
                'slab',
                _with_base({'w': round(W, 4), 'd': round(D, 4), 't': 0.22}, b0),
                cx,
                cz,
                y,
                0,
                f_mat,
                name=f'floor st{s0 + k}',
                grp=grp,
            )
    top = b0 + (s0 + n) * H
    if roof in ('flat', 'gable', 'hip', 'shed'):
        kind = 'roof_' + roof
        p = {'w': round(W, 4), 'd': round(D, 4)}
        if roof == 'flat':
            p['t'] = 0.3
        else:
            p['h'] = round(min(W, D) * 0.4, 3)
            p['over'] = 0.4
        # a pitched roof is tiled unless the caller (or the level) named a finish
        d.new(
            kind,
            _with_base(p, b0),
            cx,
            cz,
            top,
            0,
            r_mat if roof == 'flat' or roof_material in MATERIALS else 'mat_roof_tile',
            name=f'{roof} roof',
            grp=grp,
        )
    return (
        note + f'drew group "{grp}": {W:g} x {D:g} m footprint (cells {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))}), {n} storeys from storey {s0} ({n * H:g} m tall), '
        f'{4 * n} walls'
        + (f', {n} slabs' if slabs else '')
        + (f', a {roof} roof' if roof != 'none' else '')
        + (f'. Storey {s0} sits at {b0:g} m' if b0 else '')
        + (
            f'. Finishes ({finish_level(d)}): walls {mat}'
            + (f', floors {f_mat}' if slabs else '')
            + (
                f', roof {r_mat}'
                if roof == 'flat' or roof_material in MATERIALS
                else (', roof mat_roof_tile' if roof != 'none' else '')
            )
        )
        + (
            f'. Roof deck at {top + 0.3:g} m (storey {s0 + n}); rooftop tools take storey={s0 + n}'
            if roof == 'flat'
            else ''
        )
        + f'. Wall ids per side, one per storey from storey {s0} up: '
        + '; '.join(f'{s}: ' + ', '.join(v[:3]) + (f' … {v[-1]}' if len(v) > 3 else '') for s, v in sides.items())
        + '. add_opening / add_canopy also take group + side + storey instead of a wall id.'
    )


def t_draw_wall(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storeys=1,
    storey_from=0,
    material='',
    wall_h=None,
    wall_t=None,
    partition=False,
    name='',
    base_height=None,
):
    c0 = cell_centre(*parse_cell(cell_from))
    c1 = cell_centre(*parse_cell(cell_to))
    L = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    if L < 0.5:
        return 'refused: the two cells are the same — a wall needs two different cells'
    ry = math.atan2(-(c1[1] - c0[1]), (c1[0] - c0[0]))
    n = max(1, min(400, int(_num(storeys, 1))))
    s0 = int(_num(storey_from, 0))
    H = _num(wall_h, d.storey_h) or d.storey_h
    kind = 'partition' if partition else 'wall'
    T = _num(wall_t, 0.10 if partition else d.wall_t)
    mat = material if material in MATERIALS else 'mat_concrete'
    mx, mz = (c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2
    b0, note = footprint_base(d, mx, mz, L, max(T, 1.0), ry, base_height)
    ids = []
    for k in range(n):
        w = d.new(
            kind,
            _with_base({'len': round(L, 4), 'h': H, 't': T}, b0),
            mx,
            mz,
            b0 + (s0 + k) * H,
            ry,
            mat,
            name=name or None,
            grp=name,
        )
        ids.append(w['id'])
    return (
        note + f'drew {n} {kind}(s) {ids[0]}..{ids[-1]}, {L:.2f} m long from the centre of {cell_from} '
        f'to {cell_to}, storeys {s0}..{s0 + n - 1}' + (f' from {b0:g} m' if b0 else '')
    )


def t_add_slab(d: Drawing, a, cell_from, cell_to, storey=0, thickness=0.22, material='', name='', base_height=None):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    b0, note = footprint_base(d, cx, cz, xmax - xmin, zmax - zmin, 0.0, base_height)
    y = b0 + int(_num(storey, 0)) * d.storey_h
    s = d.new(
        'slab',
        _with_base({'w': round(xmax - xmin, 4), 'd': round(zmax - zmin, 4), 't': _num(thickness, 0.22)}, b0),
        cx,
        cz,
        y,
        0,
        material if material in MATERIALS else 'mat_concrete',
        name=name or None,
        grp=name,
    )
    return (
        note + f'slab {s["id"]} {xmax - xmin:g} x {zmax - zmin:g} m at storey '
        f'{int(_num(storey, 0))}' + (f' ({y:g} m)' if b0 else '')
    )


def t_add_roof(
    d: Drawing, a, cell_from, cell_to, storey=1, kind='gable', height=None, overhang=0.4, material='', base_height=None
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if kind not in ('flat', 'gable', 'hip', 'shed', 'dome', 'vault'):
        return 'refused: roof kind must be flat, gable, hip, shed, dome or vault'
    b0, note = footprint_base(d, (xmin + xmax) / 2, (zmin + zmax) / 2, W, D, 0.0, base_height)
    y = b0 + int(_num(storey, 1)) * d.storey_h
    p = {'w': round(W, 4), 'd': round(D, 4)}
    if kind == 'flat':
        p['t'] = 0.3
    elif kind == 'dome':
        p = {'r': round(min(W, D) / 2, 3), 'h': _num(height, min(W, D) * 0.4)}
    else:
        p['h'] = _num(height, min(W, D) * 0.4)
        if kind != 'vault':
            p['over'] = _num(overhang, 0.4)
    r = d.new(
        'roof_' + kind,
        _with_base(p, b0),
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        y,
        0,
        material if material in MATERIALS else ('mat_concrete' if kind == 'flat' else 'mat_roof_tile'),
    )
    return (
        note
        + f'{kind} roof {r["id"]} over cells {cell_from}..{cell_to}, sitting at storey {int(_num(storey, 1))} ({y:g} m)'
    )


def t_add_windows(
    d: Drawing,
    a,
    walls='new',
    every_n_storeys=1,
    storey_offset=0,
    per_wall=0,
    spacing=0.0,
    width=1.2,
    height=1.4,
    sill=0.9,
    margin=0.6,
    material='mat_plaster',
    sides=None,
):
    recs = [o for o in d.select(walls) if o['kind'] in ('wall', 'partition')]
    if sides:
        want = {str(s).lower() for s in sides}
        recs = [o for o in recs if any(o['name'].lower().startswith(s) for s in want)]
    if not recs:
        return 'no walls match — pass "new", "all", a group name, or wall ids'
    n = max(1, int(_num(every_n_storeys, 1)))
    off = int(_num(storey_offset, 0))
    ww, wh, ws = _num(width, 1.2), _num(height, 1.4), _num(sill, 0.9)
    mg = _num(margin, 0.6)
    mat = material if material in MATERIALS else 'mat_plaster'
    made, skipped_storey, skipped_fit = 0, 0, 0
    for w in recs:
        st = storey_index(d, w, d.storey_h)
        if st < off or (st - off) % n:
            skipped_storey += 1
            continue
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        usable = L - 2 * mg
        cnt = int(_num(per_wall, 0))
        if cnt <= 0:
            sp = _num(spacing, 0) or 3.0
            cnt = max(1, int(usable // sp))
        while cnt > 0 and cnt * (ww + 0.14) > usable:
            cnt -= 1
        if cnt <= 0:
            skipped_fit += 1
            continue
        if len(d.objs) + cnt > MAX_OBJECTS:
            return f'stopped at {made} windows: the drawing hit its {MAX_OBJECTS}-object ceiling'
        h_here = min(wh, max(0.3, H - ws - 0.15))
        for i in range(cnt):
            u = mg + usable * (i + 0.5) / cnt
            x, z = _wall_world(w, u)
            o = d.new(
                'window',
                _with_base({'w': ww, 'h': round(h_here, 3), 'sill': ws}, _num(w['p'].get('base'), 0.0)),
                x,
                z,
                w['y'],
                w['ry'],
                mat,
                name=f'window st{st}',
                grp=w['grp'],
            )
            o['meta']['host'] = w['id']  # delete the wall, the window goes with it
            made += 1
    return (
        f'added {made} windows on {len(recs) - skipped_storey - skipped_fit} walls'
        + (f' (skipped {skipped_storey} walls on other storeys)' if skipped_storey else '')
        + (f' (skipped {skipped_fit} walls too short for a window)' if skipped_fit else '')
    )


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    MATERIALS,
    MAX_OBJECTS,
    _num,
    block_bounds,
    cell_centre,
    cell_name,
    finish_level,
    finish_mat,
    parse_cell,
    resolve_block,
)
from zyg_workflows.arch_assistant.drawing import Drawing  # noqa: E402
from zyg_workflows.arch_assistant.ground import (  # noqa: E402
    _with_base,
    deck_top,
    footprint_base,
    storey_index,
)
