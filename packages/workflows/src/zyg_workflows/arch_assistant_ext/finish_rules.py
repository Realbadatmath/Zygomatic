# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""finish_rules — what a LUXURY job is allowed to be made of, and what an
occupied roof deck must be guarded by (2026-09-10).

Why this family exists: on 2026-09-10 the assistant answered a "luxurious"
20-storey request with `mat_concrete` and `mat_steel` on every surface — 285
steps of stair, two lift shafts, twenty floor slabs — put an infinity pool on
the roof deck with no guarding at all, and `design_check` said "0 errors"
three times. Every one of those is a RELATION between a record and the
programme or the deck it stands on, so no single drawing tool could see it.

This module owns no kinds and no tools. It exports DESIGN_CHECKS only:

1. `check_luxury_finishes` — on a luxury programme, every visible record on a
   finish-bearing kind whose material is one of the 21 flat presets
   (`arch_assistant.MATERIALS` minus `MATERIALS._library()`), grouped by kind
   into ONE error that names the counts and the two tools that repaint them.
   `mat_glass` is exempt on the kinds that are made of glass.
2. `check_unknown_materials` — any material id that is in neither list at all.
3. `check_deck_guarding` — a roof deck that CARRIES something (a pool, deck
   furniture, roof rooms) is occupied, so `analyse_geometry.run_guard`'s rows
   about that roof are raised to errors at 1.1 m, not the 1.0 m default.
4. `check_deck_furniture` — a bare luxury deck, but only when no real
   programme exists; building_program's `deck_furniture` item owns that case.
5. `check_canopy_materials` — an info when a canopy's plate and its columns
   come from different worlds (a library fascia on preset columns).

Plan axes, as everywhere in the studio: NORTH is -Z (small rows), SOUTH +Z,
WEST -X, EAST +X — the same naming `analyse_geometry.SIDES` uses.
"""

from __future__ import annotations

import re

from zyg_workflows.arch_assistant import Drawing, MATERIALS, _num, EXT_MODULES, cell_of as _cell_of
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []

# The kinds a person sees the finish of. `column_rect` is the built-in square
# column (the checklist calls it column_square); `parapet` is a name add_parapet
# gives a `wall`, and `parapet_cap` is the coping kind above it.
FINISH_KINDS = frozenset(
    {
        'wall',
        'curtain_wall',
        'partition',
        'slab',
        'roof_flat',
        'stair_straight',
        'stair_u',
        'stair_l',
        'stair_winder',
        'stair_spiral',
        'stair_landing',
        'elevator_shaft',
        'elevator_car',
        'canopy',
        'column_round',
        'column_square',
        'column_rect',
        'parapet',
        'parapet_cap',
        'balcony',
        'door',
        'double_door',
        'pool',
    }
)
# glass is glass: a preset id is the right answer on the kinds made of it.
# 2026-09-11: keep EQUAL to building_program.GLASS_OK_KINDS — the two lists diverged and
# 'canopy x1 (mat_glass) is a flat preset' made the model turn a glass porte-cochère into concrete.
GLASS_KINDS = frozenset(
    {
        'curtain_wall',
        'wall',
        'door',
        'double_door',
        'window',
        'parapet',
        'parapet_cap',
        'canopy',
        'skylight',
        'roof_glass',
        'balustrade',
        'railing',
    }
)

# What makes a roof deck OCCUPIED rather than a plant deck.
DECK_FURNITURE = frozenset(
    {'pool', 'sun_lounger', 'deck_chair', 'chair', 'planter', 'parasol', 'umbrella', 'table', 'pergola', 'hot_tub'}
)
DECK_ROOM_KINDS = frozenset({'wall', 'curtain_wall', 'partition'})
# what makes a deck FURNISHED (check 4): a pool alone is a pool, not a terrace
LOUNGE_KINDS = frozenset({'sun_lounger', 'deck_chair', 'chair', 'planter', 'parasol', 'umbrella', 'table', 'pergola'})
PLANT_KINDS = frozenset(
    {'tree', 'shrub', 'hedge', 'bush', 'palm', 'plant', 'flower', 'grass_patch', 'planting', 'foliage'}
)
GUARD_NAMES = ('parapet', 'railing', 'balustrade', 'rail', 'coping')
HEAD_HOUSE_SUFFIX = ' head house'

DECK_BAND_DOWN = 0.6  # how far below a deck top a record may sit and still be ON it
DECK_BAND_UP = 1.6  # and how far above (a pool basin stands 1.4 m proud)
DECK_GUARD_H = 1.1  # an occupied deck is guarded at 1.1 m, not the 1.0 m default
VOID_EDGE_TOL = 0.3  # how near a registered slab void's boundary an edge must be to BE that edge
VOID_STOREY_TOL = 0.5  # and how near the void's cut slab top must be to the deck top
MAX_KINDS = 6  # kinds named in the preset error before the '...'
MAX_IDS = 6  # ids named in the unknown-material error


def _lib() -> set:
    try:
        return MATERIALS._library()
    except Exception:  # noqa: BLE001 — a check never blocks the drawing
        return set()


def is_preset(mat) -> bool:
    """A FLAT preset: a valid material that the PBR library does not hold."""
    m = str(mat or '')
    return bool(m) and m in MATERIALS and m not in _lib()


def is_library(mat) -> bool:
    m = str(mat or '')
    return bool(m) and m in _lib()


def finish_level(d: Drawing) -> str:
    prog = (getattr(d, 'ext', None) or {}).get('building_program') or {}
    return str(prog.get('finish_level') or 'standard')


def has_programme(d: Drawing) -> bool:
    """A REAL programme — one that carries the checklist, not just a level."""
    prog = (getattr(d, 'ext', None) or {}).get('building_program') or {}
    return bool(prog.get('items'))


def _name(o) -> str:
    return str(o.get('name') or '')


def _is_guard(o) -> bool:
    lb = (_name(o) + ' ' + str(o.get('kind') or '')).lower()
    return any(w in lb for w in GUARD_NAMES)


def _main_group(recs) -> str:
    counts: dict = {}
    for o in recs:
        g = o.get('grp') or ''
        if g:
            counts[g] = counts.get(g, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else 'the group'


# ── 1. flat presets on a luxury programme ───────────────────────────────────
def check_luxury_finishes(d: Drawing) -> list:
    if finish_level(d) != 'luxury':
        return []
    bad = []
    for o in d.objs:
        if o.get('hidden'):
            continue
        k = str(o.get('kind') or '')
        if k not in FINISH_KINDS:
            continue
        m = str(o.get('mat') or '')
        if not is_preset(m):
            continue
        if m == 'mat_glass' and (k in GLASS_KINDS or 'glass' in _name(o).lower()):
            continue
        bad.append(o)
    if not bad:
        return []

    per: dict = {}
    for o in bad:
        per.setdefault(o['kind'], {}).setdefault(str(o['mat']), 0)
        per[o['kind']][str(o['mat'])] += 1
    rows = sorted(per.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    shown = ', '.join(f'{kind} x{sum(mats.values())} ({", ".join(sorted(mats))})' for kind, mats in rows[:MAX_KINDS])
    more = ' ...' if len(rows) > MAX_KINDS else ''
    grp = _main_group(bad)
    return [
        {
            'sev': 'error',
            'code': 'finish_preset',
            'text': (
                f'{len(bad)} records use flat presets on a luxury job: {shown}{more} — '
                f'apply_finishes() paints all of them in one call; '
                f'set_material(ids, "<id>") for a specific choice, '
                f'set_finish("{grp}", floor_material="<id>") for one group\'s three shell surfaces; '
                f'search_materials("marble") / ("travertine") list ids'
            ),
        }
    ]


# ── 2. a material id that does not exist at all ─────────────────────────────
def check_unknown_materials(d: Drawing) -> list:
    bad = [o for o in d.objs if not o.get('hidden') and str(o.get('mat') or '') and str(o['mat']) not in MATERIALS]
    if not bad:
        return []
    ids = ', '.join(f'{o["id"]} ("{o["mat"]}")' for o in bad[:MAX_IDS])
    more = f' and {len(bad) - MAX_IDS} more' if len(bad) > MAX_IDS else ''
    return [
        {
            'sev': 'error',
            'code': 'finish_unknown_material',
            'text': (
                f'{len(bad)} record(s) name a material that does not exist: {ids}{more} — '
                f'search_materials(query="stone") lists the library ids, or use a preset: ' + ', '.join(MATERIALS[:8])
            ),
        }
    ]


# ── 3. an OCCUPIED roof deck is guarded at 1.1 m ────────────────────────────
def _geom():
    return EXT_MODULES.get('analyse_geometry')


def deck_occupants(d: Drawing, roof: dict) -> list:
    """The records standing ON this flat roof's deck — furniture, a pool or the
    walls of a roof room. Plants and the stair's head house do not count: a
    plant deck needs no guarding and a head house is a lid, not a use."""
    G = _geom()
    if G is None:
        return []
    top = G.deck_top(roof)
    rect = G.corners(roof)
    out = []
    for o in d.objs:
        if o.get('hidden') or o['id'] == roof['id']:
            continue
        k = str(o.get('kind') or '')
        if k in PLANT_KINDS:
            continue
        if str(o.get('grp') or '').endswith(HEAD_HOUSE_SUFFIX):
            continue
        if k in DECK_ROOM_KINDS and _is_guard(o):
            continue
        if k not in DECK_FURNITURE and k not in DECK_ROOM_KINDS:
            continue
        y = _num(o.get('y'), 0.0)
        if y < top - DECK_BAND_DOWN or y > top + DECK_BAND_UP:
            continue
        if G.overlaps(rect, G.corners(o)):
            out.append(o)
    return out


def _carries(recs) -> str:
    counts: dict = {}
    for o in recs:
        counts[o['kind']] = counts.get(o['kind'], 0) + 1
    if 'pool' in counts:
        return 'a pool'
    for k in ('hot_tub', 'sun_lounger', 'deck_chair', 'chair', 'table', 'parasol', 'umbrella', 'planter'):
        if k in counts:
            word = k.replace('_', ' ')
            return f'{counts[k]} {word}' + ('' if counts[k] == 1 else 's')
    return 'roof rooms'


def _edge_mid(G, roof, side) -> tuple:
    """The midpoint of that side of the roof piece, in world metres."""
    try:
        k = list(G.SIDES).index(side)
    except ValueError:
        return None
    rect = G.corners(roof)
    p0, p1 = rect[k], rect[(k + 1) % 4]
    return (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0


def _void_at(d: Drawing, x: float, z: float, top: float):
    """The registered slab void whose boundary the point (x, z) lies on, at the
    storey whose cut slab top is this deck. `d.ext['slab_voids']` carries the
    original slab in 'orig', so the storey is the slab it was cut out of."""
    best = None
    for v in (getattr(d, 'ext', None) or {}).get('slab_voids') or []:
        try:
            x0, z0, x1, z1 = (
                _num(v.get('xmin'), 0.0),
                _num(v.get('zmin'), 0.0),
                _num(v.get('xmax'), 0.0),
                _num(v.get('zmax'), 0.0),
            )
        except Exception as _exc:  # noqa: BLE001 — a check never blocks the drawing
            _zyg_log.debug('malformed slab void skipped: %s', _exc)
            continue
        orig = v.get('orig') or {}
        if orig:
            o_top = _num(orig.get('y'), 0.0) + _num(orig.get('t'), 0.0)
            if abs(o_top - top) > VOID_STOREY_TOL:
                continue
        if x < x0 - VOID_EDGE_TOL or x > x1 + VOID_EDGE_TOL:
            continue
        if z < z0 - VOID_EDGE_TOL or z > z1 + VOID_EDGE_TOL:
            continue
        near = min(abs(x - x0), abs(x - x1), abs(z - z0), abs(z - z1))
        if near > VOID_EDGE_TOL:  # inside the void, not on its boundary
            continue
        if best is None or near < best[0]:
            best = (near, v)
    return None if best is None else best[1]


def check_deck_guarding(d: Drawing) -> list:
    G = _geom()
    if G is None:
        return []
    roofs = [o for o in d.objs if o.get('kind') == 'roof_flat' and not o.get('hidden')]
    occupied = [(r, deck_occupants(d, r)) for r in roofs]
    occupied = [(r, recs) for r, recs in occupied if recs]
    if not occupied:
        return []
    res = G.run_guard(d, min_h=DECK_GUARD_H)
    out = []
    for roof, recs in occupied:
        grp = str(roof.get('grp') or roof.get('name') or roof['id'])
        piece = str(roof.get('name') or roof.get('grp') or roof['id'])
        what = _carries(recs)
        top = G.deck_top(roof)
        for iss in res.get('issues') or []:
            if roof['id'] not in (iss.get('ids') or []):
                continue
            text = iss.get('text', '')
            side = next((s for s in G.SIDES if f' {s} edge' in text), '')
            m = re.search(r'over a ([0-9.]+) m drop, guarded over ([0-9]+)%', text)
            drop = f'{m.group(1)} m' if m else 'more than a metre'
            cov = f'{m.group(2)}%' if m else '0%'
            mid = _edge_mid(G, roof, side) if side else None
            where = f'its {side} edge' if side else 'its open edge'
            if mid:
                where += f' (midpoint x {mid[0]:.2f} z {mid[1]:.2f} m, cell {_cell_of(*mid)})'
            void = _void_at(d, mid[0], mid[1], top) if mid else None
            if void is not None:
                reason = str(void.get('reason') or 'core')
                fix = (
                    f'this is the {reason} opening edge, not the outside of the building: guard it with the '
                    f'shaft overrun / head-house walls (add_elevator(..., overrun=...) carries the shaft past '
                    f'the deck, add_stair(..., to_storey=storeys) builds the head house) — not a parapet'
                )
            else:
                fix = f'add_parapet("{grp}", height={DECK_GUARD_H})'
            out.append(
                {
                    'sev': 'error',
                    'code': 'finish_deck_guard',
                    'text': (
                        f'"{piece}" carries {what} but {where} is guarded over only {cov} of its length '
                        f'above a {drop} drop — guarding >= {DECK_GUARD_H} m is required: {fix}'
                    ),
                }
            )
    return out


# ── 4. a bare luxury deck, when nothing else is watching ────────────────────
def check_deck_furniture(d: Drawing) -> list:
    if finish_level(d) != 'luxury' or has_programme(d):
        return []  # building_program's deck_furniture item owns that case
    # the head house's own lid is 2.7 m above the deck and is not the deck
    roofs = [
        o
        for o in d.objs
        if o.get('kind') == 'roof_flat'
        and not o.get('hidden')
        and not str(o.get('grp') or '').endswith(HEAD_HOUSE_SUFFIX)
    ]
    if not roofs:
        return []
    G = _geom()
    if G is None:
        return []
    top = max(G.deck_top(r) for r in roofs)
    deck = [r for r in roofs if abs(G.deck_top(r) - top) < 0.05]
    for roof in deck:
        for o in deck_occupants(d, roof):
            if o['kind'] in LOUNGE_KINDS:
                return []
    return [
        {
            'sev': 'warn',
            'code': 'finish_deck_bare',
            'text': (
                f'the {top:.1f} m roof deck of a luxury job has no loungers, parasols or planters — '
                f'an empty deck reads as a plant deck; add_beach_set(cells=[four deck cells], '
                f'storey={int(round(top / (d.storey_h or 2.7)))})'
            ),
        }
    ]


# ── 5. a canopy whose plate and columns come from different worlds ──────────
def _canopy_columns(d: Drawing, canopy: dict) -> list:
    """The columns that carry this plate: same group, and their top is the
    canopy's soffit (add_canopy builds each one exactly y - ground tall)."""
    y = _num(canopy.get('y'), 0.0)
    out = []
    for o in d.objs:
        if o.get('hidden') or o.get('grp') != canopy.get('grp'):
            continue
        if o.get('kind') not in ('column_round', 'column_rect', 'column_square'):
            continue
        top = _num(o.get('y'), 0.0) + _num((o.get('p') or {}).get('h'), 0.0)
        if abs(top - y) <= 0.2:
            out.append(o)
    return out


def check_canopy_materials(d: Drawing) -> list:
    out = []
    for c in d.objs:
        if c.get('kind') != 'canopy' or c.get('hidden'):
            continue
        cols = _canopy_columns(d, c)
        if not cols:
            continue
        fascia = str(c.get('mat') or '')
        mixed = [o for o in cols if is_library(o.get('mat')) != is_library(fascia)]
        if not mixed:
            continue
        a, b = ('a library material', 'presets') if is_library(fascia) else ('a preset', 'library materials')
        out.append(
            {
                'sev': 'info',
                'code': 'finish_canopy_mixed',
                'text': (
                    f'canopy {c["id"]} is {a} ({fascia}) while {len(mixed)} of its columns are {b} '
                    f'({", ".join(sorted({str(o.get("mat") or "") for o in mixed}))}) — '
                    f'add_canopy(..., material=, column_material=) sets both'
                ),
            }
        )
    return out


DESIGN_CHECKS = [
    check_luxury_finishes,
    check_unknown_materials,
    check_deck_guarding,
    check_deck_furniture,
    check_canopy_materials,
]

PROMPT = (
    'FINISHES: luxury = library materials only (search_materials ids), never the mat_* presets — '
    'design_check names every preset left on a luxury job, grouped by kind, and every material id '
    'that does not exist. A roof deck that carries a pool or furniture is OCCUPIED: its open edges '
    'need guarding 1.1 m high, not 1.0 m.'
)

EXAMPLES = [
    {
        'ask': 'finish the luxury tower properly and check it',
        'calls': [
            {'tool': 'search_materials', 'args': {'query': 'marble'}},
            {'tool': 'set_finish', 'args': {'group': 'tower', 'floor_material': 'acg_Marble021'}},
            {'tool': 'design_check', 'args': {}},
        ],
    },
    {
        'ask': 'the rooftop pool deck — is it safe?',
        'calls': [
            {'tool': 'add_parapet', 'args': {'group': 'tower', 'height': 1.1}},
            {'tool': 'design_check', 'args': {}},
        ],
    },
]
