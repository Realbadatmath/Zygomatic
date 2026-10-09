# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.base — top imports, KINDS/PROMPT, the ground rules (R1/R3/R5) and the deck helpers.

Moved verbatim out of water_leisure.py (lines 37-277); zero logic changes.
"""

# ruff: noqa: F401  # the original module-level import block lands here
# verbatim; several of its names are consumed by the sibling modules rather
# than by this one, and deleting them would also change how CPython compiles
# the moved calls (import-originated globals use a different LOAD_ATTR form).
from __future__ import annotations


import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _label,
    _num,
    block_bounds,
    cell_centre,
    cell_name,
    cell_of,
    cell_size,
    deck_top,
    deck_tops,
    ground_height,
    ground_plane,
    parse_cell,
    place_height,
    surface_top,
)

KINDS = {
    'pool': {'w': 8, 'd': 4, 'depth': 1.5, 'coping': 0.4, 'raised': 0},
    'pond': {'rx': 4, 'rz': 3, 'depth': 0.6},
    'canal': {'len': 20, 'w': 6, 'depth': 1.5},
    'fountain': {'r': 2, 'tiers': 3, 'h': 2.5},
    'playground_slide': {'h': 2, 'l': 4, 'w': 0.6},
    'swing': {'w': 3, 'h': 2.4, 'seats': 2},
    'sandpit': {'w': 4, 'd': 4, 't': 0.3},
    'sports_court': {'w': 28, 'd': 15, 'lines': 1},
    'goal_posts': {'w': 7.32, 'h': 2.44, 'd': 2},
    'tennis_net': {'w': 12.8, 'h': 1.07},
    'sun_lounger': {'l': 1.9, 'w': 0.7, 'h': 0.4},
    'umbrella': {'r': 1.5, 'h': 2.3},
}
OPENINGS: list = []

PROMPT = (
    # 2026-09-16: the rooftop recipe moved to roof_kit.build_roof_deck, which lays the whole deck out to
    # deck_rules; the inventory this paragraph used to spell out is still in explain("infinity pool").
    # The saving pays for roof_kit's own paragraph — the tower prompt is 15 chars SHORTER than before it.
    'Water and leisure: a WHOLE roof deck — pool, loungers, plant, guard, door — is build_roof_deck(group, view). '
    'add_infinity_pool(cell_from, cell_to, view, storey=<top>) is the pool alone: water + tank zone below, glass '
    'weir + trough on the view edge, a glass balustrade 1.1 m OUTBOARD, steps, loungers, lights. '
    'add_pool(cell_from, cell_to, depth, steps=side) is the plain basin (RAISED on a deck unless sunk=true). '
    'add_pond, add_canal, add_fountain refuse ground over 0.5 m out of level (flatten_pad first); flowing water '
    'is the rivers family. Dry: add_sports_court, add_playground, add_beach_set. explain("water leisure") has '
    'the detail.'
)

SPORTS = ('football', 'tennis', 'basketball')
_DEFAULT_MAT = {
    'pool': 'mat_plaster',
    'pond': 'mat_stone',
    'canal': 'mat_concrete',
    'fountain': 'mat_stone',
    'playground_slide': 'mat_steel',
    'swing': 'mat_steel',
    'sandpit': 'mat_timber',
    'sports_court': 'mat_asphalt',
    'goal_posts': 'mat_paint_white',
    'tennis_net': 'mat_paint_dark',
    'sun_lounger': 'mat_timber',
    'umbrella': 'mat_paint_white',
}


def _mat(m, kind):
    return m if m in MATERIALS else _DEFAULT_MAT.get(kind, 'mat_concrete')


def _room(d: Drawing, n: int):
    """None if n more objects fit, else the refusal string."""
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} more objects and the drawing may hold {MAX_OBJECTS} in total'
    return None


def _cells(cells):
    """['D10','H10'] -> [(x, z), ...] world centres, or raise ValueError."""
    if isinstance(cells, str):
        cells = [c for c in cells.replace(';', ',').split(',') if c.strip()]
    if not isinstance(cells, (list, tuple)) or not cells:
        raise ValueError('pass a list of cells, like ["D10", "H10", "H14"]')
    return [cell_centre(*parse_cell(c)) for c in cells]


# ── the ground (R1/R3/R5, 2026-09-07) ───────────────────────────────────────
LEVEL_TOL = 0.5  # R3: the most a level-water footprint may vary, in metres
COURT_SLOPE = 0.03  # R2: the steepest ground a paved court will accept (3 %)
COURT_SPREAD = 0.3  # R2: the most a court's footprint may depart from a plane


def _ground_span(d: Drawing, cx, cz, w, dd, ry=0.0, n=5):
    """(y_centre, lo, hi): the ground at (cx, cz) and its lowest/highest sample on
    an n x n lattice covering the w x dd footprint centred there and turned by ry
    (edges included, so a footprint's corners really are measured)."""
    c, s = math.cos(ry), math.sin(ry)
    lo = hi = None
    for j in range(n):
        for i in range(n):
            lx = -w / 2 + (w * i / (n - 1) if n > 1 else 0.0)
            lz = -dd / 2 + (dd * j / (n - 1) if n > 1 else 0.0)
            g = ground_height(d, cx + lx * c + lz * s, cz - lx * s + lz * c)
            lo = g if lo is None else min(lo, g)
            hi = g if hi is None else max(hi, g)
    return ground_height(d, cx, cz), lo, hi


def _line_span(d: Drawing, x0, z0, x1, z1, n=9):
    """(lo, hi) of the ground along the line from (x0, z0) to (x1, z1). A canal is
    level ALONG its length; a cross slope under its banks is normal (a channel cut
    into a hillside), so only the water line itself is measured — a reach running
    along the contour of a slope is level water and is accepted."""
    lo = hi = None
    for i in range(n):
        f = i / (n - 1) if n > 1 else 0.5
        g = ground_height(d, x0 + (x1 - x0) * f, z0 + (z1 - z0) * f)
        lo = g if lo is None else min(lo, g)
        hi = g if hi is None else max(hi, g)
    return lo, hi


DECK_CLEAR = 0.5  # a deck needs this much air under it to count as a deck (else it is a terrace slab)


def _storey_deck(d: Drawing, deck, cx, cz):
    """The deck, if a storey lies under it — a slab whose underside rests on the
    ground is a terrace: a pool there is sunk into the earth like any garden
    pool, so for raising and infinity edges it counts as ground (None)."""
    if deck is None or deck['y'] <= ground_height(d, cx, cz) + DECK_CLEAR:
        return None
    return deck


def _deck_at(d: Drawing, cx, cz, y, tol=0.01):
    """The slab / flat roof whose TOP is y at (cx, cz) — a record standing exactly
    on a deck — else None."""
    for top, o in deck_tops(d, cx, cz):
        if abs(top - y) < tol:
            return o
    return None


def _level_check(d: Drawing, what, cx, cz, w, dd, ry=0.0, base_height=None):
    """(y, refusal, deck, note): the y a LEVEL WATER record should get, None, the
    deck (slab / flat roof) it stands on or None, and a note for the reply; or
    (0, text, None, '') when the ground under the footprint is too uneven for
    water to lie on it. An explicit base_height is the operator overruling the
    ground: no level check — but a base that lies INSIDE a covering deck (54 on
    a roof whose deck is 54.3) is lifted to the deck's top, as place_height does.
    With no base_height a deck above the ground under the centre wins over the
    ground: a rooftop pool lands on the roof, not in the basement."""
    if base_height is not None and base_height != '':
        y0 = _num(base_height, 0.0)
        y, deck = deck_top(d, cx, cz, y0)
        if deck is not None and abs(y - y0) > 1e-6:
            return (
                round(y, 4),
                None,
                _storey_deck(d, deck, cx, cz),
                (f'base {y0:g} m lay inside {deck["id"]} ({_label(deck["kind"])}) — lifted to its deck at {y:g} m; '),
            )
        deck = _storey_deck(d, _deck_at(d, cx, cz, y), cx, cz)
        return round(y, 4), None, deck, (f'on the deck of {deck["id"]} at {y:g} m; ' if deck else '')
    tops = deck_tops(d, cx, cz)
    if tops and tops[0][0] > ground_height(d, cx, cz) + 1e-6:
        top = surface_top(d, cx, cz)
        deck = _deck_at(d, cx, cz, top) or tops[0][1]
        return top, None, _storey_deck(d, deck, cx, cz), f'deck at {top:g} m ({deck["id"]}, {_label(deck["kind"])}); '
    y, lo, hi = _ground_span(d, cx, cz, w, dd, ry)
    if hi - lo > LEVEL_TOL:
        return (
            0.0,
            (
                f'refused: the ground under {what} rises {hi - lo:.2f} m — water lies level; '
                'flatten_pad it, put it lower on the slope, or use add_stream/add_river '
                'for water that flows'
            ),
            None,
            '',
        )
    return round(y, 4), None, None, ''


# ── decks: a rooftop pool (2026-09-08) ───────────────────────────────────────
INF_REACH = 1.5  # an infinity edge this close to the deck edge is MOVED onto it
INF_INSET = 0.6  # ...to this far inside the deck edge: the 0.5 m trough outside the weir must end INSIDE the facade line (2026-09-11: at 0.3 it overhung by 0.2 m)
SIDES = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west'}
_INF = {
    'none': '',
    '': '',
    'no': '',
    'false': '',
    'north': 'n',
    'south': 's',
    'east': 'e',
    'west': 'w',
    'n': 'n',
    's': 's',
    'e': 'e',
    'w': 'w',
}


def _deck_extent(o: dict) -> tuple:
    """(xmin, zmin, xmax, zmax): the world bounding box of a deck record's
    footprint, its ry and scale applied (exact for any quarter turn)."""
    p = o.get('p') or {}
    sc = o.get('s') or 1.0
    w, dd = _num(p.get('w'), 0.0) * sc / 2, _num(p.get('d'), 0.0) * sc / 2
    c, s = math.cos(o.get('ry') or 0.0), math.sin(o.get('ry') or 0.0)
    xs, zs = [], []
    for lx, lz in ((-w, -dd), (w, -dd), (w, dd), (-w, dd)):
        xs.append(o['x'] + lx * c + lz * s)
        zs.append(o['z'] - lx * s + lz * c)
    return min(xs), min(zs), max(xs), max(zs)


def _parapet_along(d: Drawing, deck: dict, side: str, ext: tuple):
    """The add_parapet wall (kind wall, name containing 'parapet', the deck's
    group) that runs along `side` of the deck, else None."""
    xmin, zmin, xmax, zmax = ext
    out = []
    for o in d.objs:
        if o.get('kind') != 'wall' or 'parapet' not in str(o.get('name') or '').lower():
            continue
        if (o.get('grp') or '') != (deck.get('grp') or '') or o.get('hidden'):
            continue
        ry = o.get('ry') or 0.0
        if side in 'ns':
            along = abs(math.sin(ry)) < 0.02
            near = abs(o['z'] - (zmin if side == 'n' else zmax)) < 0.6
        else:
            along = abs(math.cos(ry)) < 0.02
            near = abs(o['x'] - (xmin if side == 'w' else xmax)) < 0.6
        if along and near:
            out.append(o)
    return out
