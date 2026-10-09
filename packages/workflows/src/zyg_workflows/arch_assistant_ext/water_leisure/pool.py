# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.pool — add_pool, and the rooftop-infinity constants plus its geometry/deck-contents helpers.

Moved verbatim out of water_leisure.py (lines 280-706); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.water_leisure.base import (
    A,
    DECK_CLEAR,
    Drawing,
    INF_INSET,
    INF_REACH,
    SIDES,
    _INF,
    _deck_at,
    _deck_extent,
    _label,
    _level_check,
    _mat,
    _num,
    _parapet_along,
    _room,
    _storey_deck,
    block_bounds,
    cell_name,
    cell_of,
    cell_size,
    deck_tops,
    math,
    parse_cell,
)


# ── water ───────────────────────────────────────────────────────────────────
def _storey_base(d: Drawing, storey, base_height):
    """2026-09-10: storey=20 on a 20-storey box means the roof deck. The model
    passed storey= to every rooftop tool and was refused ("bad arguments"), then
    computed 20 x 2.7 + 0.3 by hand. A storey becomes a base_height here; the
    deck lift in _level_check / place_height does the rest (54 -> 54.3)."""
    if base_height in (None, '') and storey not in (None, ''):
        return _num(storey, 0) * (d.storey_h or 2.7)
    return base_height


def t_add_pool(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    depth=1.5,
    coping=0.4,
    base_height=None,
    raised=None,
    sunk=False,
    infinity='none',
    material='',
    name='',
    storey=None,
    steps='none',
):
    base_height = _storey_base(d, storey, base_height)
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    dep = _num(depth, 1.5)
    if dep < 0.3 or dep > 6:
        return 'refused: a pool must be between 0.3 and 6 m deep'
    if W < 2 or D < 2:
        return 'refused: a pool needs a block of at least 2 x 2 cells'
    inf = _INF.get(str(infinity if infinity is not None else 'none').strip().lower())
    if inf is None:
        return 'refused: infinity must be none, north, south, east or west (the overflow edge)'
    stp = _INF.get(str(steps if steps is not None else 'none').strip().lower())
    if stp is None:
        return 'refused: steps must be none, north, south, east or west (the side the entry steps descend from)'
    if stp and inf and stp == inf:
        return (
            f'refused: the entry steps cannot be on the {SIDES[inf]} side — that is the infinity edge (no coping, '
            f'no rail, a drop into the trough); put them on the deck side, steps="{SIDES[_OPP[inf]]}"'
        )
    full = _room(d, 1)
    if full:
        return full
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    y, bad, deck, note = _level_check(d, f'the pool {cf}..{ct}', cx, cz, W, D, 0.0, base_height)
    if bad:
        return bad
    notes = [note] if note else []
    glass = []
    if deck is not None:
        ext = _deck_extent(deck)
        if inf:
            # the overflow edge must BE the deck edge: close → moved onto it, else refuse with the cell
            edge = {'n': zmin, 's': zmax, 'e': xmax, 'w': xmin}[inf]
            dedge = {'n': ext[1], 's': ext[3], 'e': ext[2], 'w': ext[0]}[inf]
            gap = abs(dedge - edge)
            if gap > INF_REACH + 1e-6:
                m = cell_size()
                if inf in 'ns':
                    cell = cell_of(cx, dedge + (m / 2 if inf == 'n' else -m / 2))
                    fix = f'cell_{"from" if inf == "n" else "to"} must be row {parse_cell(cell)[1] + 1}'
                else:
                    cell = cell_of(dedge + (m / 2 if inf == 'w' else -m / 2), cz)
                    fix = f'cell_{"from" if inf == "w" else "to"} must be column {cell.rstrip("0123456789")}'
                return (
                    f"refused: an infinity edge is the deck edge, and the pool's {SIDES[inf]} edge is {gap:.1f} m "
                    f'inside the {SIDES[inf]} edge of {deck["id"]} ({_label(deck["kind"])}) — '
                    f'for a {SIDES[inf]} infinity edge {fix}'
                )
            new = dedge + (INF_INSET if inf in 'nw' else -INF_INSET)
            if abs(new - edge) > 1e-6:
                if inf == 'n':
                    zmin = new
                elif inf == 's':
                    zmax = new
                elif inf == 'e':
                    xmax = new
                else:
                    xmin = new
                notes.append(
                    f'{SIDES[inf]} edge moved {abs(new - edge):.1f} m '
                    f'{"out" if abs(new - dedge) < abs(edge - dedge) else "in"} to {INF_INSET:g} m inside '
                    f'the deck edge; '
                )
            W, D = xmax - xmin, zmax - zmin
            cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
            if W < 1 or D < 1:
                return 'refused: moving the infinity edge onto the deck edge leaves no pool — use a bigger block'
        over = max(ext[0] - xmin, ext[1] - zmin, xmax - ext[2], zmax - ext[3])
        if over > 0.01:
            return (
                f'refused: the pool {cf}..{ct} hangs {over:.1f} m over the edge of {deck["id"]} '
                f'({_label(deck["kind"])}, {ext[0]:g}..{ext[2]:g} x {ext[1]:g}..{ext[3]:g} m) — keep it on the deck'
            )
    # raised: how far the rim stands above the level it sits on. Ground → 0, a sunk
    # basin (today's geometry). Deck → depth: the basin stands ON the deck, walls
    # exposed, unless sunk=true lets it cut into the storey below (a plant storey).
    auto = raised is None or str(raised).strip().lower() in ('', 'auto')
    if deck is None:
        R = 0.0 if auto else max(0.0, _num(raised, 0.0))
        if R > 0:
            notes.append(f'raised {R:g} m above the ground; ')
    elif auto:
        R = dep
        notes.append(f'raised {R:g} m — the basin stands on the deck with its walls showing; ')
    else:
        R = max(0.0, _num(raised, dep))
        if R < dep - 1e-6 and not sunk:
            notes.append(
                f'raised {R:g} m would cut {dep - R:g} m into the storey below — clamped to {dep:g} m '
                f'(pass sunk=true for a plant storey); '
            )
            R = dep
        elif R < dep - 1e-6:
            notes.append(f'sunk {dep - R:g} m into the storey below, rim {R:g} m above the deck; ')
        else:
            notes.append(f'raised {R:g} m above the deck; ')
    if inf and deck is not None:
        for wrec in _parapet_along(d, deck, inf, _deck_extent(deck)):
            wrec['mat'] = 'mat_glass'
            glass.append(wrec['id'])
    cop = round(max(0.0, _num(coping, 0.4)), 3)
    p = {'w': round(W, 4), 'd': round(D, 4), 'depth': round(dep, 3), 'coping': cop, 'raised': round(R, 3)}
    if inf:
        p['inf'] = inf
    if stp:
        p['steps'] = stp
    if deck is not None and sunk and R < dep - 1e-6:
        p['sunk'] = True  # 2026-09-12: design_check reads p.sunk; it was never written before
    o = d.new('pool', p, cx, cz, y, 0.0, _mat(material, 'pool'), name=name or 'swimming pool', grp=name or 'pool')
    if glass:
        d.selected = [o['id']] + glass
    water = round(y + R - 0.1, 3)
    txt = (
        f'pool {o["id"]}: {W:g} x {D:g} m over cells {cf}..{ct}, {dep:g} m deep, coping {cop:g} m; '
        + ''.join(notes)
        + f'water level {water:g} m'
        + (f' ({water - y:.1f} m above the deck)' if deck is not None else '')
    )
    if inf:
        txt += (
            f'; infinity edge {SIDES[inf]}: the {SIDES[inf]} wall is a glass weir at water level '
            f'with a 0.5 m catch trough outside it'
        )
        if glass:
            txt += f', parapet {", ".join(glass)} is now a glass balustrade'
        elif deck is not None:
            txt += (
                ' — NO guard on that roof edge yet: a glass balustrade >= 1.1 m must stand outboard of the '
                'trough (add_infinity_pool builds it, or add_parapet(group, height=1.1, material="mat_glass"))'
            )
    if stp:
        txt += f'; entry steps on the {SIDES[stp]} side ({_n_treads(dep)} treads, 0.3 m rise)'
    return txt


# ── the rooftop infinity pool as ONE call (2026-09-12) ───────────────────────
# The operator's five reference pictures (Marina Bay Sands, One GT Grand Cayman,
# Noa Rooftop Alanya and two stock renders) agree on what a rooftop infinity
# pool needs before it reads as correct and luxurious: DECK-LEVEL water (the
# tank hangs into the storey below, the walking surface meets the water), the
# weir on the view side ONLY, a catch trough under it, a GLASS guard >= 1.1 m
# OUTBOARD of the trough (the weir is never the building edge), entry steps on
# the deck side, loungers in a row facing the view with parasols, palms at the
# ends, a fire-pit lounge, warm light under the water, a dark small-format tile.
# One tool, because the model never assembled it from add_pool alone (the tower
# runs of 09-07..09-12: a raised plaster tub, no guard, no steps, loungers on
# storey 0). explain("infinity pool") is the 23-rule sheet; spec("pool") the
# short one; check_infinity_pools below is what done() enforces.
_OPP = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}
_DIR = {'n': (0.0, -1.0), 's': (0.0, 1.0), 'e': (1.0, 0.0), 'w': (-1.0, 0.0)}  # outward unit vectors
# a record's local +x turned to face `side` (world = x + lx cos ry + lz sin ry, z - lx sin ry + lz cos ry)
_FACE_X = {'n': math.pi / 2, 's': -math.pi / 2, 'e': 0.0, 'w': math.pi}
# ...and its local -z (a sofa's front) turned to face `side`
_FACE_NZ = {'n': 0.0, 's': math.pi, 'e': -math.pi / 2, 'w': math.pi / 2}
INF_TILE = 'acg_Tiles135A'  # deep-blue small-format tile (map luminance 73, CC0): the "glass mosaic" of the pictures
INF_TILES = {'blue': 'acg_Tiles135A', 'turquoise': 'acg_Tiles132A', 'charcoal': 'acg_Tiles052'}
INF_RIM = 0.12  # deck level: the rim stands 0.12 m proud, the water 0.02 m above the deck
INF_COPING = 0.03
GUARD_H = 1.1  # the guard outboard of the weir — finish_rules.DECK_GUARD_H is the same number
GUARD_T = 0.03
GUARD_IN = 0.05  # the balustrade's outer face this far inside the deck edge (the trough ends at 0.1)
GUARD_WORDS = ('parapet', 'balustrade', 'railing', 'rail')
LOUNGER_OFF = 1.2  # deck between the coping and a lounger (spec clear_r)
LOUNGER_STEP = 2.4
LOUNGER_MAX = 12
PARASOL_OFF = 1.3  # a parasol this far behind its lounger, away from the pool
DECK_MARGIN = 0.5  # nothing placed closer than this to a deck edge
PALM_IN = 1.2  # a 6 m palm keeps this much deck inboard of every deck edge...
PALM_GUARD = 1.0  # ...and this much of the parapet line (GUARD_IN + GUARD_T inside the edge)
PALM_R = 0.3  # the palm record's own plan half-extent (envelope_rules default)
SWIM_DEPTH = (1.0, 2.0)  # the rule says 1.2-1.5; a plunge pool or a diving tank is add_pool
POOL_MIN_SIDE = 4.0  # the short side of an infinity pool
LIGHT_CAP = 32  # light_lamps_env.CAP — the tab renders this many lamps
LIGHT_N = 4
CORE_CLEAR = 1.5  # m of deck that must go round a lift shaft / stair / head house
WALK_MIN = 1.2  # m of walkway on every pool side that is not the weir
PLANT_KINDS = ('hvac_unit', 'water_tank', 'antenna', 'satellite_dish', 'solar_panel', 'chimney')


def _n_treads(dep: float) -> int:
    """Treads descending 0.3 m each from the water level until within 0.35 m of
    the floor — the same arithmetic as the tab and Blender builders."""
    return max(1, min(5, int(math.floor((dep - 0.15) / 0.3))))


def _guards_along(d: Drawing, deck: dict, side: str, ext: tuple, lo: float, hi: float) -> list:
    """Guard records that run along `side` of the deck within 0.8 m of its edge
    and overlap the span [lo, hi] along that edge: walls named parapet /
    balustrade / railing, or a railing kind, standing on the deck."""
    xmin, zmin, xmax, zmax = ext
    top = deck['y'] + _num((deck.get('p') or {}).get('t'), 0.3)
    out = []
    for o in d.objs:
        if o.get('hidden'):
            continue
        k = o.get('kind')
        nm = str(o.get('name') or '').lower()
        if k == 'railing' or k == 'balustrade':
            pass
        elif k == 'wall' and any(w in nm for w in GUARD_WORDS):
            pass
        else:
            continue
        if abs(_num(o.get('y'), 0.0) - top) > 0.6:
            continue
        ry = o.get('ry') or 0.0
        L = _num((o.get('p') or {}).get('len'), 0.0)
        if side in 'ns':
            along = abs(math.sin(ry)) < 0.02
            near = abs(o['z'] - (zmin if side == 'n' else zmax)) < 0.8
            a0, a1 = o['x'] - L / 2, o['x'] + L / 2
        else:
            along = abs(math.cos(ry)) < 0.02
            near = abs(o['x'] - (xmin if side == 'w' else xmax)) < 0.8
            a0, a1 = o['z'] - L / 2, o['z'] + L / 2
        if along and near and a1 > lo + 0.05 and a0 < hi - 0.05:
            out.append(o)
    return out


def _coverage(guards: list, side: str, lo: float, hi: float) -> float:
    """Metres of [lo, hi] that the guards cover (union of their extents)."""
    spans = []
    for o in guards:
        L = _num((o.get('p') or {}).get('len'), 0.0)
        c = o['x'] if side in 'ns' else o['z']
        spans.append((max(lo, c - L / 2), min(hi, c + L / 2)))
    spans.sort()
    total, cur = 0.0, None
    for a, b in spans:
        if b <= a:
            continue
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        total += cur[1] - cur[0]
    return total


def _pool_span(o: dict, side: str) -> tuple:
    p = o.get('p') or {}
    w, dd = _num(p.get('w'), 8.0), _num(p.get('d'), 4.0)
    return (o['x'] - w / 2, o['x'] + w / 2) if side in 'ns' else (o['z'] - dd / 2, o['z'] + dd / 2)


def _pool_deck(d: Drawing, o: dict):
    """The storey deck an infinity pool stands on, else None (a garden pool)."""
    return _storey_deck(d, _deck_at(d, o['x'], o['z'], o['y']), o['x'], o['z'])


def _inside(ext: tuple, x: float, z: float, m: float = DECK_MARGIN) -> bool:
    return ext[0] + m <= x <= ext[2] - m and ext[1] + m <= z <= ext[3] - m


# ── what the deck already holds, worked out BEFORE a record is made ─────────
# A pool that lands 0.6 m off a lift shaft is not a pool that needs editing, it
# is a pool that should never have been drawn: these three helpers let
# add_infinity_pool refuse without spending a draw call.
def _rect_gap(a: tuple, b: tuple) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dz = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dz)


def _would_deck(d: Drawing, cell_from, cell_to, storey, base_height):
    """The deck an infinity pool over this block WOULD stand on, else None (the
    ground, or a block the tool will refuse for its own reasons). storey=20 asks
    for 54.0 and _level_check delivers 54.3, so a deck a little above counts."""
    bh = _storey_base(d, storey, base_height)
    if bh in (None, ''):
        return None
    try:
        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    except Exception:  # noqa: BLE001 — t_add_pool owns bad cells
        return None
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    y = _num(bh, 0.0)
    for top, o in deck_tops(d, cx, cz):
        if -0.01 <= top - y <= DECK_CLEAR:
            return _storey_deck(d, o, cx, cz)
    return None


def _deck_cores(d: Drawing, ext: tuple, top: float) -> list:
    """[{'what','id','bb'}] — every core reaching this deck. deck_rules owns the
    "what reaches the deck" rule (_cores); [] when that family is not loaded."""
    DK = A.EXT_MODULES.get('deck_rules')
    if DK is None:
        return []
    env = {'xmin': ext[0], 'zmin': ext[1], 'xmax': ext[2], 'zmax': ext[3]}
    try:
        return list(DK._cores(d, env, top, d.storey_h or 2.7))
    except Exception:  # noqa: BLE001 — never block a draw on a helper
        return []


def _block_cells(cell_from, cell_to):
    """(c0, r0, c1, r1, cell_size) for a cell block."""
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    xmin, _zmin, xmax, _zmax = block_bounds(cell_from, cell_to)
    return c0, r0, c1, r1, (xmax - xmin) / max(1, c1 - c0 + 1)


def _move_suggestion(cell_from, cell_to, rect, blk, need, ext):
    """The nearest whole-cell shift of the block that puts `need` metres between
    it and rectangle `blk` without leaving the deck — as the operator would say
    it ('use rows >= 99, e.g. FD99..FM104'), or '' when there is no way out."""
    c0, r0, c1, r1, cs = _block_cells(cell_from, cell_to)
    if cs <= 0:
        return ''
    W, D = rect[2] - rect[0], rect[3] - rect[1]
    best = None
    for axis, sign, want in (
        ('z', +1, blk[3] + need - rect[1]),
        ('z', -1, rect[3] - (blk[1] - need)),
        ('x', +1, blk[2] + need - rect[0]),
        ('x', -1, rect[2] - (blk[0] - need)),
    ):
        if want <= 1e-9:
            continue
        n = int(math.ceil(want / cs - 1e-9))
        if axis == 'z':
            lo = rect[1] + sign * n * cs
            if lo < ext[1] - 1e-9 or lo + D > ext[3] + 1e-9:
                continue
        else:
            lo = rect[0] + sign * n * cs
            if lo < ext[0] - 1e-9 or lo + W > ext[2] + 1e-9:
                continue
        if best is None or n < best[0]:
            best = (n, axis, sign)
    if best is None:
        return ''
    n, axis, sign = best
    dc, dr = (n * sign, 0) if axis == 'x' else (0, n * sign)
    nf, nt = cell_name(c0 + dc, r0 + dr), cell_name(c1 + dc, r1 + dr)
    if axis == 'z':
        row = ''.join(ch for ch in (nf if sign > 0 else nt) if ch.isdigit())
        edge = f'rows >= {row}' if sign > 0 else f'rows <= {row}'
    else:
        col = ''.join(ch for ch in (nf if sign > 0 else nt) if ch.isalpha())
        edge = f'columns from {col}' if sign > 0 else f'columns up to {col}'
    return f'use {edge}, e.g. {nf}..{nt}'


def _walk_short(rect: tuple, ext: tuple, inf: str, coping: float) -> list:
    """[(side, clear)] — every side that is not the weir with less than WALK_MIN
    metres of deck outside the coping, worst first."""
    pad = coping
    clear = {
        'n': (rect[1] - pad) - ext[1],
        's': ext[3] - (rect[3] + pad),
        'w': (rect[0] - pad) - ext[0],
        'e': ext[2] - (rect[2] + pad),
    }
    out = [(s, v) for s, v in clear.items() if s != inf and v < WALK_MIN - 1e-9]
    out.sort(key=lambda q: q[1])
    return out


def _walk_suggestion(cell_from, cell_to, rect, ext, inf, side):
    """A whole-cell block on the same deck that DOES leave WALK_MIN on both sides
    of the offending axis, or '' when the deck is simply not wide enough. The
    tool must never refuse a placement it cannot better."""
    c0, r0, c1, r1, cs = _block_cells(cell_from, cell_to)
    if cs <= 0:
        return ''
    pad = int(math.ceil(WALK_MIN / cs - 1e-9))  # whole cells of walkway
    if side in 'ew':
        span, lo_e, hi_e, lo_r, hi_r = 'x', ext[0], ext[2], rect[0], rect[2]
    else:
        span, lo_e, hi_e, lo_r, hi_r = 'z', ext[1], ext[3], rect[1], rect[3]
    free = int(round(((hi_e - lo_e) - (hi_r - lo_r)) / cs))
    if (inf in 'ew') == (span == 'x'):
        # the weir is on this axis, so the pool is flush with that deck edge and
        # no shift is open to it: the block itself has to be shorter.
        want = pad - free
        if want <= 0:
            return ''
        dc, dr = (-want, 0) if span == 'x' else (0, -want)
        if inf in ('e', 's'):  # the weir end stays put
            return (
                f'e.g. {cell_name(c0 - dc, r0 - dr)}..{cell_name(c1, r1)}, {want} cell{"s" if want > 1 else ""} shorter'
            )
        return f'e.g. {cell_name(c0, r0)}..{cell_name(c1 + dc, r1 + dr)}, {want} cell{"s" if want > 1 else ""} shorter'
    if free < 2 * pad:
        return ''
    n = pad - int(round((lo_r - lo_e) / cs))  # pad whole cells off the low edge
    if n == 0:
        return ''
    dc, dr = (n, 0) if span == 'x' else (0, n)
    return (
        f'e.g. {cell_name(c0 + dc, r0 + dr)}..{cell_name(c1 + dc, r1 + dr)}, which leaves {pad * cs:g} m on that side'
    )
