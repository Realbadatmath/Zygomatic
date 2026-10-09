# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.infinity_build — the stages add_infinity_pool runs.

One tool call draws a dozen things: the basin, the glass guard outboard of its
weir, the plant zone under it, a row of loungers with parasols and palms, a
lounge set and the underwater lights. Each of those is a stage here; `infinity.
t_add_infinity_pool` keeps the running order and the report it returns, because
the order is the part that must not change.

The stages talk to each other through `InfinityFrame`: the basin as drawn, read
back out of the drawing once, plus the report lines they append to. Nothing in
this module reads the drawing twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from zyg_workflows.arch_assistant_ext.water_leisure.base import (
    Drawing,
    MATERIALS,
    SIDES,
    _INF,
    _deck_extent,
    _num,
    _room,
    block_bounds,
    cell_name,
    cell_of,
    deck_tops,
    math,
    parse_cell,
    surface_top,
)

from zyg_workflows.arch_assistant_ext.water_leisure.pool import (
    CORE_CLEAR,
    DECK_MARGIN,
    GUARD_H,
    GUARD_IN,
    GUARD_T,
    INF_COPING,
    INF_RIM,
    INF_TILE,
    INF_TILES,
    LIGHT_CAP,
    LIGHT_N,
    LOUNGER_MAX,
    LOUNGER_OFF,
    LOUNGER_STEP,
    PALM_GUARD,
    PALM_IN,
    PALM_R,
    PARASOL_OFF,
    PLANT_KINDS,
    SWIM_DEPTH,
    WALK_MIN,
    _DIR,
    _FACE_NZ,
    _FACE_X,
    _OPP,
    _deck_cores,
    _guards_along,
    _inside,
    _move_suggestion,
    _pool_deck,
    _pool_span,
    _rect_gap,
    _walk_short,
    _walk_suggestion,
    _would_deck,
    t_add_pool,
)


@dataclass
class InfinityOpts:
    """The tool's four free-text arguments, read once into the five values every
    stage needs: the infinity side, the depth, the level mode, the tile material
    and the group name everything this call draws is filed under."""

    inf: str
    dep: float
    lv: str
    mat: str
    grp: str


@dataclass
class InfinityFrame:
    """The basin as add_pool actually drew it, measured once.

    `ext` is the deck extent (None on the ground) and `lines` is the report the
    stages append to — in the order the tool returns them.
    """

    inf: str
    dep: float
    lv: str
    mat: str
    grp: str
    pool: dict
    p: dict
    W: float
    D: float
    xmin: float
    xmax: float
    zmin: float
    zmax: float
    y: float
    water: float
    deck: dict | None
    ext: tuple | None
    lines: list = field(default_factory=list)


@dataclass
class LoungerRow:
    """Where the row of loungers runs: which side of the basin, how far along it
    is centred, how long the run is and which way the loungers face."""

    side: str
    kind: str
    ox: float
    oz: float
    half: float
    edge: float
    c_along: float
    L: float
    ry: float


def pool_options(view, depth, level, material, name) -> tuple:
    """Read the tool's arguments into an InfinityOpts, or refuse them.

    Returns `(opts, '')` when they are usable and `(None, refusal)` when they are
    not, so the tool answers with the refusal unchanged.
    """
    inf = _INF.get(str(view if view is not None else 'south').strip().lower())
    if not inf:
        return None, 'refused: view must be north, south, east or west — the side the water falls away towards'
    dep = _num(depth, 1.4)
    if dep < SWIM_DEPTH[0] or dep > SWIM_DEPTH[1]:
        return None, (
            f'refused: a swimming pool is {SWIM_DEPTH[0]:.1f}-{SWIM_DEPTH[1]:.1f} m deep (1.2-1.5 m is the rule); '
            f'a plunge pool or a diving tank is add_pool'
        )
    lv = str(level or 'deck').strip().lower()
    if lv not in ('deck', 'raised'):
        return None, (
            'refused: level must be "deck" (the water meets the walking surface, the tank hangs into the '
            'storey below) or "raised" (the basin stands on the deck with its walls showing)'
        )
    m = str(material or '').strip()
    mat = INF_TILES.get(m.lower()) or (m if m in MATERIALS else INF_TILE)
    return InfinityOpts(inf=inf, dep=dep, lv=lv, mat=mat, grp=name or 'infinity pool'), ''


def position_notes(d: Drawing, cell_from, cell_to, storey, base_height, opts: InfinityOpts) -> tuple:
    """What the deck as it ALREADY is says about this position, before anything
    is drawn: the core clearance, the walkways round the coping and the rooftop
    plant standing in the view the pool is being made for.

    Returns `(refusal, plant_in_view, walk_tight)`. A non-empty refusal means the
    pool must not be drawn at all; the two lists are things that will be drawn
    anyway and reported as NOTEs at the end.
    """
    inf, lv = opts.inf, opts.lv
    pre_deck = _would_deck(d, cell_from, cell_to, storey, base_height)
    plant_in_view, walk_tight = [], []
    if pre_deck is not None:
        pre_ext = _deck_extent(pre_deck)
        rect = tuple(block_bounds(cell_from, cell_to))
        cop = INF_COPING if lv == 'deck' else 0.3
        top = _num(pre_deck.get('y'), 0.0) + _num((pre_deck.get('p') or {}).get('t'), 0.3)
        worst = None
        for c in _deck_cores(d, pre_ext, top):
            g = _rect_gap(rect, tuple(c['bb']))
            if g < CORE_CLEAR - 1e-9 and (worst is None or g < worst[0]):
                worst = (g, c)
        if worst is not None:
            g, c = worst
            bb = tuple(c['bb'])
            where = cell_of((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
            fix = _move_suggestion(cell_from, cell_to, rect, bb, CORE_CLEAR, pre_ext)
            return (
                (
                    f'refused: the pool {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
                    f'comes within {g:.2f} m of {c["what"]} {c["id"]} at {where} — {CORE_CLEAR:g} m of deck must '
                    f'go round a core you have to walk past; '
                    + (
                        fix
                        if fix
                        else 'no position on this deck clears it: put the pool on another deck, or move the core'
                    )
                ),
                plant_in_view,
                walk_tight,
            )
        for side, clear in _walk_short(rect, pre_ext, inf, cop):
            if clear < 0:
                break  # off the deck entirely: t_add_pool owns that refusal
            fix = _walk_suggestion(cell_from, cell_to, rect, pre_ext, inf, side)
            if not fix:
                walk_tight.append((side, clear))  # this deck cannot do better — draw it and say so
                continue
            return (
                (
                    f'refused: the pool {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
                    f'leaves {clear:.2f} m between its coping and the {SIDES[side]} deck edge — a walkway is '
                    f'{WALK_MIN:g} m and only the {SIDES[inf]} (weir) side is exempt; {fix}'
                ),
                plant_in_view,
                walk_tight,
            )
        for o in d.objs:
            if o.get('hidden') or o.get('kind') not in PLANT_KINDS:
                continue
            if abs(_num(o.get('y'), 0.0) - top) > 0.35:
                continue
            ox, oz = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
            # deck_rules.check_roof_deck's rule, said before the pool exists:
            # plant is out of the way only when it is beyond the pool's FAR edge.
            away = _OPP[inf]
            behind = {'n': oz < rect[1], 's': oz > rect[3], 'w': ox < rect[0], 'e': ox > rect[2]}[away]
            if not behind and _inside(pre_ext, ox, oz, 0.0):
                plant_in_view.append(o)
    return '', plant_in_view, walk_tight


def draw_basin(d: Drawing, a, cell_from, cell_to, storey, base_height, opts: InfinityOpts) -> tuple:
    """Hand the block to add_pool with the infinity keywords, then read the basin
    it drew back out as the frame every stage below measures against.

    Returns `(None, txt)` when add_pool refused or drew no pool — its own words
    are the tool's answer — and `(frame, '')` once the basin exists.
    """
    inf, dep, lv, mat, grp = opts.inf, opts.dep, opts.lv, opts.mat, opts.grp
    kw = dict(
        depth=dep,
        infinity=SIDES[inf],
        steps=SIDES[_OPP[inf]],
        material=mat,
        name=grp,
        storey=storey,
        base_height=base_height,
    )
    if lv == 'deck':
        kw.update(raised=INF_RIM, coping=INF_COPING, sunk=True)
    else:
        kw.update(coping=0.3)
    n0 = len(d.objs)
    txt = t_add_pool(d, a, cell_from, cell_to, **kw)
    if txt.startswith('refused') or len(d.objs) == n0 or d.objs[-1].get('kind') != 'pool':
        return None, txt
    pool = d.objs[-1]
    pool['grp'] = grp
    p = pool['p']
    W, D = p['w'], p['d']
    xmin, xmax, zmin, zmax = pool['x'] - W / 2, pool['x'] + W / 2, pool['z'] - D / 2, pool['z'] + D / 2
    y = pool['y']
    water = round(y + p['raised'] - 0.1, 3)
    deck = _pool_deck(d, pool)
    lines = [
        f'infinity pool {pool["id"]}: {W:g} x {D:g} m ({dep:g} m deep) over '
        f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}'
        + (f' on the {y:g} m deck of {deck["id"]}' if deck else f' at {y:g} m (ground)')
        + f', water at {water:g} m'
        + (f' ({water - y:+.2f} m to the deck)' if deck else '')
    ]
    lines.append(f'{SIDES[inf]} edge: glass weir at water level, 0.5 x 0.4 m trough outside it')
    frame = InfinityFrame(
        inf=inf,
        dep=dep,
        lv=lv,
        mat=mat,
        grp=grp,
        pool=pool,
        p=p,
        W=W,
        D=D,
        xmin=xmin,
        xmax=xmax,
        zmin=zmin,
        zmax=zmax,
        y=y,
        water=water,
        deck=deck,
        ext=_deck_extent(deck) if deck else None,
        lines=lines,
    )
    return frame, ''


def deck_works(d: Drawing, f: InfinityFrame) -> None:
    """What the deck under the basin owes it: the guard outboard of the weir, and
    the plant zone in the storey the tank hangs into.

    The guard comes first because the weir is never the building edge — an
    existing parapet along that deck edge is raised to GUARD_H and turned to
    glass, and where there is none, one is built along the whole edge. Then the
    balance tank, the filtration and the edge pumps are registered as a zone
    below, so no rooms are put there.
    """
    deck, ext, inf, grp, y, lines = f.deck, f.ext, f.inf, f.grp, f.y, f.lines
    if deck:
        lo, hi = _pool_span(f.pool, inf)
        had = _guards_along(d, deck, inf, ext, lo, hi)
        raised_ids = []
        for g in had:
            if _num(g['p'].get('h'), 0.0) < GUARD_H - 1e-6:
                g['p']['h'] = GUARD_H
                raised_ids.append(g['id'])
            if g.get('kind') == 'wall':
                g['mat'] = 'mat_glass'
        if had:
            lines.append(
                f'guard: {", ".join(o["id"] for o in had)} on the {SIDES[inf]} deck edge is glass, '
                f'{GUARD_H:g} m' + (f' (raised from lower: {", ".join(raised_ids)})' if raised_ids else '')
            )
        else:
            if inf in 'ns':
                L = ext[2] - ext[0]
                gx, gz, ry = (
                    (ext[0] + ext[2]) / 2,
                    (ext[1] + GUARD_IN + GUARD_T / 2 if inf == 'n' else ext[3] - GUARD_IN - GUARD_T / 2),
                    0.0,
                )
            else:
                L = ext[3] - ext[1]
                gx, gz, ry = (
                    (ext[0] + GUARD_IN + GUARD_T / 2) if inf == 'w' else (ext[2] - GUARD_IN - GUARD_T / 2),
                    (ext[1] + ext[3]) / 2,
                    math.pi / 2,
                )
            g = d.new(
                'wall',
                {'len': round(L, 4), 'h': GUARD_H, 't': GUARD_T},
                gx,
                gz,
                y,
                ry,
                'mat_glass',
                name='glass balustrade parapet',
                grp=deck.get('grp') or grp,
            )
            lines.append(
                f'guard: glass balustrade {g["id"]} {GUARD_H:g} m along the whole {SIDES[inf]} deck edge, '
                f'outboard of the trough (the weir is never the building edge)'
            )
    else:
        lines.append('on the ground: no roof guard needed')
    # ── the tank + plant zone under a deck-level pool ────────────────────────
    xmin, xmax, zmin, zmax = f.xmin, f.xmax, f.zmin, f.zmax
    if deck and f.lv == 'deck':
        below = [t for t, _r in deck_tops(d, f.pool['x'], f.pool['z']) if t < y - 0.5]
        yf = max(below) if below else y - (d.storey_h or 2.7)
        ox, oz = _DIR[_OPP[inf]]
        zx0, zx1, zz0, zz1 = xmin, xmax, zmin, zmax
        if ox < 0:
            zx0 = max(ext[0], xmin - 2.5)
        elif ox > 0:
            zx1 = min(ext[2], xmax + 2.5)
        if oz < 0:
            zz0 = max(ext[1], zmin - 2.5)
        elif oz > 0:
            zz1 = min(ext[3], zmax + 2.5)
        cx, cz = (zx0 + zx1) / 2, (zz0 + zz1) / 2
        pts = [
            [round(zx0 - cx, 4), round(zz0 - cz, 4)],
            [round(zx1 - cx, 4), round(zz0 - cz, 4)],
            [round(zx1 - cx, 4), round(zz1 - cz, 4)],
            [round(zx0 - cx, 4), round(zz1 - cz, 4)],
        ]
        nm = 'pool tank + balance tank + plant'
        zn = d.new('zone', {'pts': pts, 'name': nm, 'use': 'plant', 'h': 0.05}, cx, cz, yf, 0.0, None, name=nm, grp=grp)
        st = int(round(yf / (d.storey_h or 2.7)))
        lines.append(
            f'tank: the basin hangs {f.dep - f.p["raised"]:.2f} m into storey {st}; zone {zn["id"]} '
            f'"{nm}" ({zx1 - zx0:g} x {zz1 - zz0:g} m at {yf:g} m) is the balance tank, filtration and '
            f'the edge pumps — no rooms there'
        )
    elif deck:
        lines.append(f'raised {f.p["raised"]:g} m: the basin stands on the deck, walls in {f.mat}')


def _side_free(f: InfinityFrame, s: str) -> tuple:
    """How much clear deck lies on side `s` of the basin, and how long that side
    of it runs. (0.0, 0.0) on the ground, where there is no deck to measure."""
    ext = f.ext
    if not ext:
        return 0.0, 0.0
    if s == 'n':
        return f.zmin - ext[1], f.W
    if s == 's':
        return ext[3] - f.zmax, f.W
    if s == 'e':
        return ext[2] - f.xmax, f.D
    return f.xmin - ext[0], f.D


def palm_ends(d: Drawing, f: InfinityFrame, row: LoungerRow, n_l: int) -> int:
    """A palm at each end of the lounger row, PULLED IN to the deck's margins.

    2026-09-16 (live job aba5ab208439): a palm whose point fell short of the
    margin used to be DROPPED silently, the row then read lopsided, and the model
    hand-moved one — onto the deck edge, where it floated and had to be deleted.
    It is PULLED IN instead: PALM_IN of deck inboard of every edge, PALM_GUARD
    clear of the parapet line, never over the water, never on top of the palm at
    the other end.
    """
    ext, grp = f.ext, f.grp
    xmin, xmax, zmin, zmax = f.xmin, f.xmax, f.zmin, f.zmax
    row_side, half, edge, c_along, L = row.side, row.half, row.edge, row.c_along, row.L
    ox, oz = row.ox, row.oz
    n_p = 0
    m = max(PALM_IN, GUARD_IN + GUARD_T + PALM_GUARD)
    put = []
    for sgn in (-1, 1):
        al = c_along + sgn * (min(L / 2, (n_l - 1) * LOUNGER_STEP / 2 + 2.2))
        off = LOUNGER_OFF + half
        if row_side in 'ns':
            px, pz = al, edge + oz * off
        else:
            px, pz = edge + ox * off, al
        if min(ext[2] - ext[0], ext[3] - ext[1]) < 2 * m:
            break  # the deck is narrower than the margins
        px = min(max(px, ext[0] + m), ext[2] - m)
        pz = min(max(pz, ext[1] + m), ext[3] - m)
        if (xmin - PALM_R < px < xmax + PALM_R) and (zmin - PALM_R < pz < zmax + PALM_R):
            continue  # pulling it in put it over the water
        if any(math.hypot(px - qx, pz - qz) < 1.0 for qx, qz in put):
            continue  # both ends clamped to the same corner
        put.append((px, pz))
        d.new(
            'tree_palm',
            {'h': 6.0, 'fronds': 7},
            px,
            pz,
            round(surface_top(d, px, pz), 4),
            0.0,
            'mat_foliage',
            name=f'palm {n_p + 1}',
            grp=grp,
        )
        n_p += 1
    return n_p


def lounger_row(d: Drawing, f: InfinityFrame, loungers: bool, parasols: bool, palms: bool) -> tuple:
    """The row of loungers, facing the weir, with a parasol behind every other
    one and a palm at each end.

    The row goes on the side opposite the weir when there is depth enough to lie
    down there, otherwise on the longest flank that fits; the weir side never
    takes it. Returns `(row_side, full)`: `row_side` is '' when no side would
    have it (the lounge set then gets first refusal of every side), and `full` is
    the `_room` refusal when the drawing cannot hold the row, which the caller
    answers with after the report so far.
    """
    ext, grp, lines = f.ext, f.grp, f.lines
    row_side, row_kind = '', ''
    if f.deck and loungers:
        opp = _OPP[f.inf]
        free, L = _side_free(f, opp)
        if free >= LOUNGER_OFF + 1.9 + DECK_MARGIN and L >= 3.0:
            row_side, row_kind = opp, 'opposite'
        else:
            best = None
            for s in (x for x in 'nsew' if x not in (f.inf, opp)):
                free, L = _side_free(f, s)
                if free >= LOUNGER_OFF + 0.7 + DECK_MARGIN and L >= 3.0 and (best is None or L > best[1]):
                    best = (s, L)
            if best:
                row_side, row_kind = best[0], 'flank'
    n_l = n_u = n_p = 0
    if row_side:
        ox, oz = _DIR[row_side]
        half = 0.95 if row_kind == 'opposite' else 0.35  # the lounger's half extent across the row
        free, L = _side_free(f, row_side)
        edge = {'n': f.zmin, 's': f.zmax, 'e': f.xmax, 'w': f.xmin}[row_side]
        c_along = f.pool['x'] if row_side in 'ns' else f.pool['z']
        n_l = max(1, min(LOUNGER_MAX, int(math.floor((L - 1.0) / LOUNGER_STEP))))
        start = c_along - (n_l - 1) * LOUNGER_STEP / 2
        ry = _FACE_X[f.inf]
        para_fits = free >= LOUNGER_OFF + 2 * half + PARASOL_OFF + DECK_MARGIN
        full = _room(d, n_l * (2 if parasols and para_fits else 1) + (2 if palms else 0))
        if full:
            return row_side, full
        for i in range(n_l):
            al = start + i * LOUNGER_STEP
            off = LOUNGER_OFF + half
            if row_side in 'ns':
                lx, lz = al, edge + oz * off
            else:
                lx, lz = edge + ox * off, al
            if not _inside(ext, lx, lz):
                continue
            d.new(
                'sun_lounger',
                {'l': 1.9, 'w': 0.7, 'h': 0.4},
                lx,
                lz,
                round(surface_top(d, lx, lz), 4),
                ry,
                'mat_timber',
                name=f'lounger {i + 1}',
                grp=grp,
            )
            if parasols and para_fits and i % 2 == 0:
                ux, uz = lx + ox * PARASOL_OFF, lz + oz * PARASOL_OFF
                if _inside(ext, ux, uz):
                    d.new(
                        'umbrella',
                        {'r': 1.5, 'h': 2.3},
                        ux,
                        uz,
                        round(surface_top(d, ux, uz), 4),
                        0.0,
                        'mat_paint_white',
                        name=f'parasol {i // 2 + 1}',
                        grp=grp,
                    )
                    n_u += 1
        n_l = len([o for o in d.objs if o.get('grp') == grp and o.get('kind') == 'sun_lounger'])
        if palms:
            row = LoungerRow(
                side=row_side, kind=row_kind, ox=ox, oz=oz, half=half, edge=edge, c_along=c_along, L=L, ry=ry
            )
            n_p = palm_ends(d, f, row, n_l)
        lines.append(
            f'{n_l} loungers on the {SIDES[row_side]} side facing {SIDES[f.inf]}'
            + (f', {n_u} parasols behind them' if n_u else (', no room for parasols behind them' if parasols else ''))
            + (f', {n_p} palms at the ends of the row' if n_p else '')
        )
    elif f.deck and loungers:
        lines.append('no deck room for loungers: the pool fills the deck (use a smaller block)')
    return row_side, ''


def _at(off: float, al: float, s: str, edge: float, ox: float, oz: float) -> tuple:
    """A point `off` out from the basin's `s` edge and `al` along it."""
    return (al, edge + oz * off) if s in 'ns' else (edge + ox * off, al)


def lounge_set(d: Drawing, f: InfinityFrame, row_side: str, lounge: bool) -> None:
    """A fire pit, a sofa facing the view and two armchairs, on the first side
    with 4.6 m of deck to spare that the lounger row is not already using."""
    ext, grp, lines = f.ext, f.grp, f.lines
    inf = f.inf
    if f.deck and lounge:
        for s in ([_OPP[inf]] if row_side != _OPP[inf] else []) + [
            x for x in 'nsew' if x not in (inf, _OPP[inf], row_side)
        ]:
            free, L = _side_free(f, s)
            if free < 4.6 or L < 5.0:
                continue
            ox, oz = _DIR[s]
            edge = {'n': f.zmin, 's': f.zmax, 'e': f.xmax, 'w': f.xmin}[s]
            c_along = f.pool['x'] if s in 'ns' else f.pool['z']
            fx, fz = _at(2.4, c_along, s, edge, ox, oz)
            sx, sz = _at(3.8, c_along, s, edge, ox, oz)
            pts = [
                (fx, fz),
                (sx, sz),
                _at(2.4, c_along - 1.7, s, edge, ox, oz),
                _at(2.4, c_along + 1.7, s, edge, ox, oz),
            ]
            if not all(_inside(ext, px, pz) for px, pz in pts):
                continue
            if _room(d, 4):
                break
            yl = round(surface_top(d, fx, fz), 4)
            d.new('cylinder', {'r': 0.5, 'h': 0.35}, fx, fz, yl, 0.0, 'mat_stone', name='fire pit', grp=grp)
            d.new(
                'sofa',
                {'w': 2.2, 'd': 0.9, 'h': 0.85, 'seat': 0.45},
                sx,
                sz,
                yl,
                _FACE_NZ[inf],
                'mat_timber',
                name='outdoor sofa',
                grp=grp,
            )
            for j, (ax, az) in enumerate(pts[2:]):
                d.new(
                    'armchair',
                    {'w': 0.9, 'd': 0.9, 'h': 0.85},
                    ax,
                    az,
                    yl,
                    _FACE_NZ[inf],
                    'mat_timber',
                    name=f'armchair {j + 1}',
                    grp=grp,
                )
            lines.append(f'lounge on the {SIDES[s]} side: fire pit, sofa and 2 armchairs facing {SIDES[inf]}')
            break


def underwater_lights(d: Drawing, f: InfinityFrame, lights: bool) -> None:
    """Warm light under the water along the deck-side wall, never on the weir
    side. Says so instead when the drawing is already at the lamp cap."""
    grp, lines, y = f.grp, f.lines, f.y
    inf = f.inf
    n_li = 0
    if lights:
        have = len([o for o in d.objs if str(o.get('kind') or '').startswith('light_')])
        if have + LIGHT_N <= LIGHT_CAP and not _room(d, LIGHT_N):
            s = _OPP[inf]
            ox, oz = _DIR[s]
            edge = {'n': f.zmin, 's': f.zmax, 'e': f.xmax, 'w': f.xmin}[s]
            c_along = f.pool['x'] if s in 'ns' else f.pool['z']
            L = f.W if s in 'ns' else f.D
            # deck-level water sits 0.02 m over the deck, so a lamp 0.25 m under it would
            # be INSIDE the roof slab for check_buried: keep it just above the deck top
            ly = round(max(f.water - 0.25, y + 0.02), 3)
            for i in range(LIGHT_N):
                al = c_along - L / 2 + L * (i + 0.5) / LIGHT_N
                lx, lz = (al, edge - oz * 0.5) if s in 'ns' else (edge - ox * 0.5, al)
                d.new(
                    'light_point',
                    {'w': 10, 'r': 5, 'col': '#ffd2a0'},
                    lx,
                    lz,
                    ly,
                    0.0,
                    'mat_plaster',
                    name='underwater light',
                    grp=grp,
                )
                n_li += 1
            lines.append(f'{n_li} warm underwater lights along the {SIDES[s]} wall (none on the weir side)')
        else:
            lines.append(
                f'no underwater lights: the drawing already holds {have} of {LIGHT_CAP} lamps'
                if have + LIGHT_N > LIGHT_CAP
                else 'no underwater lights: the drawing is full'
            )
