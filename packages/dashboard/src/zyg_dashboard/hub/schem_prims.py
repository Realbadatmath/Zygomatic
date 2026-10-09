#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Parametric primitives — the Creator's authoring engine.

A schematic's SOURCE is a recipe: an ordered list of ops, each a named primitive
plus params. Ops emit blocks; later ops overwrite earlier ones at the same cell
(so you can carve a doorway out of a wall by painting air over it), and the whole
list bakes down to a flat block list the compiler then proves.

Why a recipe rather than raw voxels: most invalid designs become *unexpressible*.
A hollow_box always walks one continuous circuit per floor, a stair_ring always
rises at most one block per cell, a pyramid always grows inward from a supported
eave. That is cheaper and kinder than letting someone paint a floating castle and
then explaining why it cannot be built.

Ops are pure functions of their params — no I/O, no globals — so the same recipe
always bakes to the same blocks, and a stored recipe stays editable forever.
"""

import math

AIR = '__air__'  # sentinel: an op may erase cells painted by earlier ops


def _blk(x, y, z, mat, kind, state=None):
    b = {'x': int(x), 'y': int(y), 'z': int(z), 'mat': mat, 'kind': kind}
    if state:
        b['state'] = state
    return b


# ── helpers ─────────────────────────────────────────────────────────────
def _rect_cells(x0, x1, z0, z1, hollow=True):
    x0, x1 = min(x0, x1), max(x0, x1)
    z0, z1 = min(z0, z1), max(z0, z1)
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if hollow and x not in (x0, x1) and z not in (z0, z1):
                continue
            yield x, z


def _ring_clockwise(x0, x1, z0, z1):
    """Interior-perimeter cells, clockwise from the SW corner — the order a
    circuit is laid in, so each block is laterally adjacent to the last."""
    cells = []
    for x in range(x0, x1 + 1):
        cells.append((x, z1))
    for z in range(z1 - 1, z0 - 1, -1):
        cells.append((x1, z))
    for x in range(x1 - 1, x0 - 1, -1):
        cells.append((x, z0))
    for z in range(z0 + 1, z1):
        cells.append((x0, z))
    return cells


def _pattern_mat(p, x, y, z, mats):
    """Deterministic material pick — no RNG, so a recipe always bakes identically."""
    if not mats:
        return None
    if len(mats) == 1 or p in (None, 'solid'):
        return mats[0]
    if p == 'bands':
        return mats[y % len(mats)]
    if p == 'checker':
        return mats[(x + z) % len(mats)]
    if p == 'noise':
        h = (x * 73856093) ^ (y * 19349663) ^ (z * 83492791)
        return mats[((h >> 3) % len(mats) + len(mats)) % len(mats)]
    if p == 'gradient':
        return mats[min(len(mats) - 1, max(0, (y - 65) * len(mats) // 8))]
    return mats[0]


# ── primitives ──────────────────────────────────────────────────────────
def op_box(p):
    """Rectangular walls: hollow shell or solid block."""
    x0, x1 = int(p['x0']), int(p['x1'])
    z0, z1 = int(p['z0']), int(p['z1'])
    y0, y1 = int(p['y0']), int(p['y1'])
    mats = p.get('mats') or [p.get('mat', 'stone_bricks')]
    hollow = bool(p.get('hollow', True))
    corner = p.get('corner_mat')
    pattern = p.get('pattern', 'solid')
    kind = p.get('kind', 'wall')

    out = []
    for y in range(min(y0, y1), max(y0, y1) + 1):
        # One circuit per floor, in ring order: every block lands laterally
        # adjacent to the previous one, which is what keeps it placeable.
        cells = (
            _ring_clockwise(min(x0, x1), max(x0, x1), min(z0, z1), max(z0, z1))
            if hollow
            else list(_rect_cells(x0, x1, z0, z1, hollow=False))
        )
        for x, z in cells:
            is_corner = x in (x0, x1) and z in (z0, z1)
            mat = corner if (is_corner and corner) else _pattern_mat(pattern, x, y, z, mats)
            if mat:
                out.append(_blk(x, y, z, mat, kind))
    return out


def op_fill(p):
    """Solid cuboid — also the eraser when mat is air."""
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    y0, y1 = sorted((int(p['y0']), int(p['y1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    mat = p.get('mat', 'stone_bricks')
    kind = p.get('kind', 'fill')
    out = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                out.append(_blk(x, y, z, mat, kind))
    return out


def op_erase(p):
    """Carve cells painted by earlier ops — doorways, windows, arches."""
    q = dict(p)
    q['mat'] = AIR
    q['kind'] = 'erase'
    return op_fill(q)


def op_cylinder(p):
    """Circular tower wall (or solid disc stack)."""
    cx, cz = int(p['cx']), int(p['cz'])
    r = max(1, int(p.get('r', 3)))
    y0, y1 = sorted((int(p['y0']), int(p['y1'])))
    mats = p.get('mats') or [p.get('mat', 'stone_bricks')]
    hollow = bool(p.get('hollow', True))
    pattern = p.get('pattern', 'solid')
    kind = p.get('kind', 'wall')

    out = []
    for y in range(y0, y1 + 1):
        cells = []
        for x in range(cx - r, cx + r + 1):
            for z in range(cz - r, cz + r + 1):
                d = math.dist((x, z), (cx, cz))
                if d > r + 0.5:
                    continue
                if hollow and d < r - 0.5:
                    continue
                cells.append((x, z))
        # Lay each ring in angular order so consecutive blocks touch.
        cells.sort(key=lambda c: math.atan2(c[1] - cz, c[0] - cx))
        for x, z in cells:
            mat = _pattern_mat(pattern, x, y, z, mats)
            if mat:
                out.append(_blk(x, y, z, mat, kind))
    return out


def op_pyramid(p):
    """Stepped pyramid — each tier is inset by one and rests on the tier below."""
    cx, cz = int(p['cx']), int(p['cz'])
    half = max(1, int(p.get('half', 4)))
    y0 = int(p.get('y0', 65))
    mats = p.get('mats') or [p.get('mat', 'sandstone')]
    hollow = bool(p.get('hollow', False))
    out = []
    for lvl in range(half + 1):
        h = half - lvl
        y = y0 + lvl
        mat = mats[lvl % len(mats)]
        for x in range(cx - h, cx + h + 1):
            for z in range(cz - h, cz + h + 1):
                if hollow and h > 0 and abs(x - cx) != h and abs(z - cz) != h:
                    continue
                out.append(_blk(x, y, z, mat, 'core'))
    return out


def op_gable_roof(p):
    """Stepped gable roof rising to a ridge, with optional overhang.

    Each course rests on the one below, so the bot walks up its own roof.
    """
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    y0 = int(p['y0'])
    mat = p.get('mat', 'spruce_planks')
    overhang = int(p.get('overhang', 1))
    out = []
    span = (x1 - x0) // 2
    for lvl in range(span + 1):
        y = y0 + lvl
        xs = [x0 + lvl, x1 - lvl]
        if xs[0] > xs[1]:
            break
        if xs[0] == xs[1]:
            xs = [xs[0]]
        for z in range(z0 - overhang, z1 + overhang + 1):
            for x in xs:
                out.append(_blk(x, y, z, mat, 'roof'))
    return out


def op_stair_ring(p):
    """Interior spiral staircase hugging a wall — the classic way up.

    Rises at most one block per cell by construction, which is exactly the bot's
    step limit, so a ring is always climbable.
    """
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    ybase, ytop = int(p['ybase']), int(p['ytop'])
    mat = p.get('mat', 'cobblestone')
    inset = int(p.get('inset', 1))
    cells = _ring_clockwise(x0 + inset, x1 - inset, z0 + inset, z1 - inset)
    if not cells:
        return []
    n = max(len(cells) - 1, 1)
    out = []
    for i, (x, z) in enumerate(cells):
        top = ybase + round(i * (ytop - ybase) / n)
        for y in range(ybase, top + 1):
            out.append(_blk(x, y, z, mat, 'stair'))
    out.sort(key=lambda b: b['y'])  # layer by layer, always self-supporting
    return out


def op_battlements(p):
    """Alternating merlons around a wall top."""
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    y = int(p['y'])
    mat = p.get('mat', 'chiseled_stone_bricks')
    every = max(1, int(p.get('every', 2)))
    out = []
    for x, z in _ring_clockwise(x0, x1, z0, z1):
        if (x + z) % every == 0:
            out.append(_blk(x, y, z, mat, 'battlement'))
    return out


def op_stairs_line(p):
    """A run of real oriented stair blocks (eaves, parapets, railings).

    Emits a `state` so the bot places the block and then straightens its facing
    via RCON — see minecraft_build_fp/blockstates.js.
    """
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    y = int(p['y'])
    mat = p.get('mat', 'stone_brick_stairs')
    facing = p.get('facing', 'north')
    half = p.get('half', 'bottom')
    out = []
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            out.append(_blk(x, y, z, mat, 'trim', {'facing': facing, 'half': half}))
    return out


def op_slab_deck(p):
    """A slab floor/roof deck."""
    x0, x1 = sorted((int(p['x0']), int(p['x1'])))
    z0, z1 = sorted((int(p['z0']), int(p['z1'])))
    y = int(p['y'])
    mat = p.get('mat', 'stone_brick_slab')
    typ = p.get('type', 'bottom')
    return [_blk(x, y, z, mat, 'deck', {'type': typ}) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)]


def op_door(p):
    """A door — both halves, correctly stated."""
    x, y, z = int(p['x']), int(p['y']), int(p['z'])
    mat = p.get('mat', 'oak_door')
    facing = p.get('facing', 'south')
    hinge = p.get('hinge', 'left')
    return [
        _blk(x, y, z, mat, 'door', {'facing': facing, 'hinge': hinge, 'half': 'lower'}),
        _blk(x, y + 1, z, mat, 'door', {'facing': facing, 'hinge': hinge, 'half': 'upper'}),
    ]


def op_windows(p):
    """Punch glass into a wall at given cells/heights."""
    mat = p.get('mat', 'glass')
    ys = p.get('ys') or [int(p.get('y', 67))]
    cells = p.get('cells') or []
    return [_blk(int(c[0]), int(y), int(c[1]), mat, 'window') for c in cells for y in ys]


def op_voxels(p):
    """Raw cells — the escape hatch for the layer painter, capture and import."""
    out = []
    for b in p.get('blocks') or []:
        state = b.get('state') or None
        out.append(_blk(b['x'], b['y'], b['z'], b.get('mat', 'stone_bricks'), b.get('kind', 'voxel'), state))
    return out


OPS = {
    'box': op_box,
    'fill': op_fill,
    'erase': op_erase,
    'cylinder': op_cylinder,
    'pyramid': op_pyramid,
    'gable_roof': op_gable_roof,
    'stair_ring': op_stair_ring,
    'battlements': op_battlements,
    'stairs_line': op_stairs_line,
    'slab_deck': op_slab_deck,
    'door': op_door,
    'windows': op_windows,
    'voxels': op_voxels,
}

# Parameter schema for the UI: the Creator generates its forms from this, so a
# new primitive shows up in the tab without touching any JavaScript.
OP_SCHEMA = {
    'box': {
        'label': 'Walls / Box',
        'kindHint': 'wall',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -3},
            {'k': 'x1', 't': 'int', 'd': 3},
            {'k': 'z0', 't': 'int', 'd': -9},
            {'k': 'z1', 't': 'int', 'd': -3},
            {'k': 'y0', 't': 'int', 'd': 65},
            {'k': 'y1', 't': 'int', 'd': 70},
            {'k': 'hollow', 't': 'bool', 'd': True},
            {'k': 'mats', 't': 'mats', 'd': ['stone_bricks', 'mossy_stone_bricks']},
            {'k': 'corner_mat', 't': 'mat', 'd': 'dark_oak_log', 'opt': True},
            {'k': 'pattern', 't': 'enum', 'd': 'noise', 'opts': ['solid', 'bands', 'checker', 'noise', 'gradient']},
        ],
    },
    'fill': {
        'label': 'Solid Fill',
        'kindHint': 'fill',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -2},
            {'k': 'x1', 't': 'int', 'd': 2},
            {'k': 'y0', 't': 'int', 'd': 65},
            {'k': 'y1', 't': 'int', 'd': 65},
            {'k': 'z0', 't': 'int', 'd': -8},
            {'k': 'z1', 't': 'int', 'd': -4},
            {'k': 'mat', 't': 'mat', 'd': 'cobblestone'},
        ],
    },
    'erase': {
        'label': 'Erase (doorways, windows)',
        'kindHint': 'erase',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -1},
            {'k': 'x1', 't': 'int', 'd': 1},
            {'k': 'y0', 't': 'int', 'd': 65},
            {'k': 'y1', 't': 'int', 'd': 66},
            {'k': 'z0', 't': 'int', 'd': -3},
            {'k': 'z1', 't': 'int', 'd': -3},
        ],
    },
    'cylinder': {
        'label': 'Round Tower',
        'kindHint': 'wall',
        'params': [
            {'k': 'cx', 't': 'int', 'd': 0},
            {'k': 'cz', 't': 'int', 'd': -6},
            {'k': 'r', 't': 'int', 'd': 3},
            {'k': 'y0', 't': 'int', 'd': 65},
            {'k': 'y1', 't': 'int', 'd': 71},
            {'k': 'hollow', 't': 'bool', 'd': True},
            {'k': 'mats', 't': 'mats', 'd': ['stone_bricks', 'cobblestone']},
            {'k': 'pattern', 't': 'enum', 'd': 'noise', 'opts': ['solid', 'bands', 'checker', 'noise', 'gradient']},
        ],
    },
    'pyramid': {
        'label': 'Stepped Pyramid',
        'kindHint': 'core',
        'params': [
            {'k': 'cx', 't': 'int', 'd': 0},
            {'k': 'cz', 't': 'int', 'd': -7},
            {'k': 'half', 't': 'int', 'd': 4},
            {'k': 'y0', 't': 'int', 'd': 65},
            {'k': 'mats', 't': 'mats', 'd': ['sandstone', 'cut_sandstone']},
            {'k': 'hollow', 't': 'bool', 'd': False},
        ],
    },
    'gable_roof': {
        'label': 'Gable Roof',
        'kindHint': 'roof',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -3},
            {'k': 'x1', 't': 'int', 'd': 3},
            {'k': 'z0', 't': 'int', 'd': -9},
            {'k': 'z1', 't': 'int', 'd': -4},
            {'k': 'y0', 't': 'int', 'd': 68},
            {'k': 'mat', 't': 'mat', 'd': 'spruce_planks'},
            {'k': 'overhang', 't': 'int', 'd': 1},
        ],
    },
    'stair_ring': {
        'label': 'Interior Staircase',
        'kindHint': 'stair',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -3},
            {'k': 'x1', 't': 'int', 'd': 3},
            {'k': 'z0', 't': 'int', 'd': -9},
            {'k': 'z1', 't': 'int', 'd': -3},
            {'k': 'ybase', 't': 'int', 'd': 65},
            {'k': 'ytop', 't': 'int', 'd': 70},
            {'k': 'mat', 't': 'mat', 'd': 'cobblestone'},
            {'k': 'inset', 't': 'int', 'd': 1},
        ],
    },
    'battlements': {
        'label': 'Battlements',
        'kindHint': 'battlement',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -3},
            {'k': 'x1', 't': 'int', 'd': 3},
            {'k': 'z0', 't': 'int', 'd': -9},
            {'k': 'z1', 't': 'int', 'd': -3},
            {'k': 'y', 't': 'int', 'd': 71},
            {'k': 'mat', 't': 'mat', 'd': 'chiseled_stone_bricks'},
            {'k': 'every', 't': 'int', 'd': 2},
        ],
    },
    'stairs_line': {
        'label': 'Stair Trim (oriented)',
        'kindHint': 'trim',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -3},
            {'k': 'x1', 't': 'int', 'd': 3},
            {'k': 'z0', 't': 'int', 'd': -3},
            {'k': 'z1', 't': 'int', 'd': -3},
            {'k': 'y', 't': 'int', 'd': 71},
            {'k': 'mat', 't': 'mat', 'd': 'stone_brick_stairs'},
            {'k': 'facing', 't': 'enum', 'd': 'south', 'opts': ['north', 'south', 'east', 'west']},
            {'k': 'half', 't': 'enum', 'd': 'top', 'opts': ['bottom', 'top']},
        ],
    },
    'slab_deck': {
        'label': 'Slab Deck',
        'kindHint': 'deck',
        'params': [
            {'k': 'x0', 't': 'int', 'd': -2},
            {'k': 'x1', 't': 'int', 'd': 2},
            {'k': 'z0', 't': 'int', 'd': -8},
            {'k': 'z1', 't': 'int', 'd': -4},
            {'k': 'y', 't': 'int', 'd': 71},
            {'k': 'mat', 't': 'mat', 'd': 'stone_brick_slab'},
            {'k': 'type', 't': 'enum', 'd': 'bottom', 'opts': ['bottom', 'top']},
        ],
    },
    'door': {
        'label': 'Door',
        'kindHint': 'door',
        'params': [
            {'k': 'x', 't': 'int', 'd': 0},
            {'k': 'y', 't': 'int', 'd': 65},
            {'k': 'z', 't': 'int', 'd': -3},
            {'k': 'mat', 't': 'mat', 'd': 'oak_door'},
            {'k': 'facing', 't': 'enum', 'd': 'south', 'opts': ['north', 'south', 'east', 'west']},
            {'k': 'hinge', 't': 'enum', 'd': 'left', 'opts': ['left', 'right']},
        ],
    },
    'windows': {
        'label': 'Windows',
        'kindHint': 'window',
        'params': [
            {'k': 'cells', 't': 'cells', 'd': [[-3, -6], [3, -6]]},
            {'k': 'ys', 't': 'ints', 'd': [67]},
            {'k': 'mat', 't': 'mat', 'd': 'glass'},
        ],
    },
    'voxels': {
        'label': 'Painted Cells',
        'kindHint': 'voxel',
        'hidden': True,
        'params': [{'k': 'blocks', 't': 'blocks', 'd': []}],
    },
}


def bake(ops):
    """Recipe → flat block list.

    Later ops overwrite earlier ones at the same cell, and `erase` removes them —
    which is what makes "wall, then punch a doorway through it" expressible.
    Emission order is preserved, giving the compiler a sensible starting order.
    """
    # dict insertion order IS the build order: overwriting a cell keeps its
    # original position, while re-painting an erased cell moves it to the end
    # (correct — it now depends on whatever was built in between).
    cells = {}
    for op in ops or []:
        name = op.get('op')
        fn = OPS.get(name)
        if not fn or op.get('muted'):
            continue
        try:
            produced = fn(op.get('params') or {})
        except Exception as exc:
            raise ValueError(f"op '{name}' failed: {exc}") from exc
        for b in produced:
            k = (b['x'], b['y'], b['z'])
            if b['mat'] == AIR:
                cells.pop(k, None)
                continue
            cells[k] = b
    return list(cells.values())


def describe():
    """The op catalogue the Creator tab builds its forms from."""
    return {name: {**meta, 'name': name} for name, meta in OP_SCHEMA.items() if not meta.get('hidden')}
