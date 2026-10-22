# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# The original top import block is kept verbatim here and its names are
# re-exported (see __all__ below), so building_program._A / .math / .re still resolve.
#
# Moved verbatim from arch_assistant_ext/building_program.py lines 5-358
# (2026-10 split): the module docstring below, the top import block, and the
# evidence helpers every later section is built from.

"""building_program — the BUILD CHECKLIST, resolved in one call (2026-09-08).

The operator's rule: "a building of 3+ storeys has elevators — build elevators?
yes — select elevator type. A building always has an entrance."  That is a
checklist, and the obvious way to run it is to ask the user each question in
turn.  It is also the one way that cannot work here:

  · `ask_user` PARKS the whole job and injects nothing until the answer comes
    back, so ten questions are ten round trips;
  · the job has 28 turns total (MAX_CALLS) and the last 20-storey tower already
    spent 27 of them, 784 s and 1.26M cached tokens.

So the checklist is not a conversation.  `plan_building()` resolves the whole
program deterministically in ONE call — every required item with its default
already chosen — and hands back a build order.  The genuine either/ors come
back as one DECIDE block with defaults marked, to be batched into a single
ask_user only when the request asked to be consulted.  "Just build it" costs
zero questions.

The program is then STATE: it lives in `doc.ext.building_program`, so it
survives the job, the injection and the save, and a later request continues the
same checklist instead of guessing again.  `check_program` is a design check,
so `done` refuses while a REQUIRED item is missing — a rule the model can read
and skip is not a rule (measured: it routed around plant_trees the moment
plant_trees refused).

Numbers here are conventional practice, not code citations; each item names the
`spec()` sheet that carries the detail and the sources.
No new kinds.  Two tools.
"""

from __future__ import annotations

import math
import re

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
    block_bounds,
    parse_cell,
    cell_name,
    resolve_block,
)

# re-exported for the siblings and for importers of the building_program package
__all__ = [
    'Drawing',
    'block_bounds',
    'parse_cell',
    'cell_name',
    'resolve_block',
]

KINDS: dict = {}
OPENINGS: list = []

EXT_KEY = 'building_program'

# m2 per person — the coarse occupancy that decides lift count, WC count, exits
DENSITY = {
    'house': 30.0,
    'residential': 30.0,
    'office': 10.0,
    'hotel': 20.0,
    'school': 4.0,
    'retail': 5.0,
    'warehouse': 50.0,
    'civic': 8.0,
    'mixed': 15.0,
}
USES = tuple(sorted(DENSITY))

DOORS = ('door', 'double_door', 'door_sliding', 'door_french')
STAIRS = ('stair_straight', 'stair_l', 'stair_u', 'stair_spiral', 'stair_winder')
LIFTS = ('elevator_car', 'elevator_shaft')
ROOFS = (
    'roof_flat',
    'roof_gable',
    'roof_hip',
    'roof_shed',
    'roof_mansard',
    'roof_pyramid',
    'roof_curved',
    'roof_butterfly',
    'roof_gambrel',
    'roof_half_hip',
    'roof_sawtooth',
    'roof_vault',
)
TREES = ('tree_deciduous', 'tree', 'tree_conifer', 'tree_palm', 'tree_line', 'forest', 'orchard')


# ── evidence: is an item actually in the drawing? ────────────────────────────
def _names(o) -> str:
    """Everything a record can be recognised BY, as a padded WORD string.

    Two traps this closes. First, the tools place REAL models by default, so a
    lamp post is an `asset` record whose kind says nothing and whose p.item is
    'street_lamp_01_2k' — matching on kind alone made the approach item
    unsatisfiable by the very tool meant to satisfy it. Second, substring
    matching is wrong here: 'street' CONTAINS 'tree', so every lamp post
    counted as planting (the same trap that once matched "tree" to "street rat"
    in search_assets). Tokens, padded with spaces, so a word matches a word.
    """
    p = o.get('p') or {}
    raw = ' '.join(
        str(x or '') for x in (o.get('name'), o.get('grp'), p.get('name'), p.get('use'), p.get('item'), p.get('query'))
    )
    return ' ' + ' '.join(re.split(r'[^a-z0-9]+', raw.lower())) + ' '


def _hit(o, words) -> bool:
    """True when any word or phrase appears as whole words in the record."""
    n = _names(o)
    return any((' ' + str(w).strip().lower() + ' ') in n for w in words)


def _count(d, kinds=(), words=(), storey=None, use_words=()) -> int:
    """Records matching any kind, or any word in their name/group/zone use."""
    H = d.storey_h or 2.7
    n = 0
    for o in d.objs:
        if o.get('hidden'):
            continue
        if storey is not None and abs((o.get('y') or 0) - storey * H) > H * 0.6:
            continue
        if o.get('kind') in kinds:
            n += 1
            continue
        if words and _hit(o, words):
            n += 1
    return n


def _groups(d, words) -> set:
    return {o.get('grp') for o in d.objs if o.get('grp') and _hit(o, words)}


def _reach_y(d, kinds) -> float:
    """The highest y a vertical element reaches. A lift is ONE elevator_shaft
    record at the bottom storey with p.h = the whole shaft, and a stair ONE
    record with steps x rise — counting distinct record heights would say
    'one storey' for a 20-storey core, which is the bug this replaces."""
    best = -1.0
    for o in d.objs:
        if o.get('kind') not in kinds or o.get('hidden'):
            continue
        p = o.get('p') or {}
        h = _num(p.get('h'), 0.0)
        if h <= 0 and p.get('steps'):
            h = _num(p.get('steps'), 0.0) * _num(p.get('rise'), 0.0)
        best = max(best, (o.get('y') or 0.0) + h)
    return best


def _reaches_top(d, storeys, kinds) -> bool:
    H = d.storey_h or 2.7
    return _reach_y(d, kinds) >= (max(1, int(storeys)) - 1) * H - 0.1


def _storeys_reached(d, kinds) -> float:
    H = d.storey_h or 2.7
    r = _reach_y(d, kinds)
    return round(r / H, 1) if r > 0 else 0.0


def _far_apart(d, kinds, min_m) -> bool:
    pts = [(o['x'], o['z']) for o in d.objs if o.get('kind') in kinds and not o.get('hidden')]
    for i, a in enumerate(pts):
        for b in pts[i + 1 :]:
            if math.hypot(a[0] - b[0], a[1] - b[1]) >= min_m:
                return True
    return False


# ── how far up the core has to go ────────────────────────────────────────────
def _top_storey(c) -> int:
    """The storey the CORE must serve. Not `storeys - 1`: when the roof is an
    accessible deck the deck IS a storey people stand on, and a core that stops
    at storey 19 under a storey-20 infinity pool is the tower job 71ac02b0 built.

    `roof` is decided after `stair` in ITEMS, so during resolve() the pick is not
    in pick_of yet — the roof default is a pure function of use and storeys, so
    ask it directly.  A pick the REQUEST forced ("infinity pool on the roof" ->
    flat_deck) outranks both: it is already known before the first item runs."""
    from zyg_workflows.arch_assistant_ext.building_program.checklist import (
        BY_KEY,  # function-local: checklist imports this module
    )

    roof = (
        (c.get('pick_over') or {}).get('roof') or (c.get('pick_of') or {}).get('roof') or BY_KEY['roof']['default'](c)
    )
    st = max(1, int(c['storeys']))
    return st if roof == 'flat_deck' else st - 1


def _stair_stack(d, N) -> tuple:
    """(storeys started by the biggest stair group, that group). A stair built
    one record per storey — the only shape that can cut a floor opening per slab
    and hand a rail to each flight — is a STACK: distinct records at y ~= s*H."""
    H = d.storey_h or 2.7
    by: dict = {}
    for o in d.objs:
        if o.get('kind') not in STAIRS or o.get('hidden'):
            continue
        y = o.get('y') or 0.0
        s = int(round(y / H))
        if s < 0 or s >= max(1, int(N)) or abs(y - s * H) > 0.35:
            continue
        by.setdefault(o.get('grp') or o.get('id') or '?', set()).add(s)
    if not by:
        return 0, ''
    g = max(by, key=lambda k: len(by[k]))
    return len(by[g]), g


def _ev_stair(d, c) -> tuple:
    N = _top_storey(c)
    started, grp = _stair_stack(d, N)
    if started >= N:
        return True, f'stairs start on storeys 0..{N - 1} of 0..{N - 1}'
    if _reaches_top(d, N + 1, STAIRS):
        return True, (
            f'one stair record reaching storey {_storeys_reached(d, STAIRS)} of {N} — '
            f'legacy single record: no floor opening is cut per slab and no landing is guarded'
        )
    if started:
        return False, (
            f'stairs start on {started} of storeys 0..{N - 1} '
            f'(group "{grp}", the highest reaches storey {_storeys_reached(d, STAIRS)})'
        )
    return False, f'no stair reaching storey {N} (highest reaches storey {_storeys_reached(d, STAIRS)})'


def _shafts_to_top(d, N) -> list:
    """Lift shafts whose top actually arrives at storey N."""
    H = d.storey_h or 2.7
    out = []
    for o in d.objs:
        if o.get('kind') != 'elevator_shaft' or o.get('hidden'):
            continue
        if (o.get('y') or 0.0) + _num((o.get('p') or {}).get('h'), 0.0) >= N * H - 0.1:
            out.append(o)
    return out


def _ev_lift(d, c) -> tuple:
    N = _top_storey(c)
    n = max(1, int(c.get('n') or 1))
    tall = _shafts_to_top(d, N)
    total = _count(d, ('elevator_shaft',))
    if len(tall) < n:
        return False, (
            f'{len(tall)} of {total} shaft(s) reach storey {N} — need {n} '
            f'(the highest lift reaches storey {_storeys_reached(d, LIFTS)})'
        )
    doored = [o for o in tall if isinstance((o.get('p') or {}).get('doors'), (list, tuple))]
    if not doored:
        return True, f'{len(tall)} shaft(s) reaching storey {N} — no doors (legacy)'
    served = min(len((o['p'].get('doors')) or ()) for o in doored)
    if len(doored) < n or served < N + 1:
        return False, (
            f'{len(doored)} of {n} shaft(s) have doors, and the poorest serves {served} '
            f'of the {N + 1} storeys 0..{N} — a shaft with no door on a floor does not stop there'
        )
    return True, f'{n} shaft(s) reaching storey {N}, doors on {served} storeys'


def _ev_second_escape(d, c) -> tuple:
    ext = [o for o in d.objs if o.get('kind') == 'fire_stair_exterior' and not o.get('hidden')]
    if not ext:
        if _far_apart(d, STAIRS, 8.0):
            return True, 'a second stair 8 m or more from the first'
        return False, 'no second escape found'
    at = getattr(_A.EXT_MODULES.get('envelope_rules'), 'group_at', None)
    if at is None:
        return True, f'{len(ext)} external escape stair(s)'
    inside = [o for o in ext if at(d, o.get('x') or 0.0, o.get('z') or 0.0) is not None]
    if inside:
        return False, (
            f'{len(inside)} of {len(ext)} external escape stair(s) stand inside the plan — '
            f'an escape stair inside the envelope is a stair in a room, not a second way out'
        )
    return True, f'{len(ext)} external escape stair(s), all outside the envelope'


# A head house, a lift overrun and a plant screen all carry their own little
# roof ABOVE the deck.  Counting one of them as "the deck" moved the surface
# people stand on up by the height of the stair enclosure, and then the stair
# that reaches the real deck reads as 2.9 m short of it.
ANCILLARY_ROOF = ('head house', 'headhouse', 'overrun', 'motor room', 'plant', 'screen', 'lift motor')


def _top_deck(d) -> float:
    """The top of the BUILDING's highest deck: the roof record names the group,
    and inside it the highest slab / flat roof top is the surface people stand
    on. -1 when nothing has been roofed yet."""
    grp, best = '', -1.0
    for o in d.objs:
        if o.get('kind') in ROOFS and not o.get('hidden') and (o.get('y') or 0.0) > best:
            if _hit(o, ANCILLARY_ROOF):
                continue
            best, grp = (o.get('y') or 0.0), (o.get('grp') or '')
    if best < 0:
        return -1.0
    top = -1.0
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in ('slab', 'roof_flat'):
            continue
        if grp and (o.get('grp') or '') != grp:
            continue
        top = max(top, (o.get('y') or 0.0) + _num((o.get('p') or {}).get('t'), 0.22))
    return top if top > 0 else best


def _ev_roof_access(d, c) -> tuple:
    deck = _top_deck(d)
    if deck < 0:
        return False, 'no roof record, so there is no deck to reach'
    reach = _reach_y(d, STAIRS)
    walls = [
        o
        for o in d.objs
        if not o.get('hidden')
        and 'wall' in str(o.get('kind') or '')
        and _hit(o, ('head house', 'headhouse', 'roof access'))
        and _num((o.get('p') or {}).get('h'), 0.0) >= 2.0
        and (o.get('y') or 0.0) >= deck - 0.6
    ]
    miss = []
    if reach < deck - 0.1:
        miss.append(
            f'the stair stops at {reach:.1f} m, {deck - reach:.1f} m short of the {deck:.1f} m deck'
            if reach > 0
            else f'no stair reaches the {deck:.1f} m deck'
        )
    if len(walls) < 2:
        miss.append(
            f'{len(walls)} head-house wall(s) 2 m or taller on the deck (need 2) — the stair surfaces in the open'
        )
    if miss:
        return False, '; '.join(miss)
    return True, f'the stair reaches the {deck:.1f} m deck and {len(walls)} head-house walls cover the landing'


def _ev_plant(d, c) -> tuple:
    plant = _count(
        d, ('hvac_unit', 'water_tank', 'silo', 'antenna', 'duct', 'boiler'), words=('plant', 'chiller', 'ahu')
    )
    over = any(
        (
            (o.get('kind') == 'elevator_shaft' and _num((o.get('p') or {}).get('overrun'), 0.0) > 0)
            or _hit(o, ('overrun', 'motor', 'motor room'))
        )
        for o in d.objs
        if not o.get('hidden')
    )
    if plant and over:
        return True, f'{plant} plant record(s) and a lift overrun'
    if plant:
        return False, 'plant present, no lift overrun'
    if over:
        return False, 'a lift overrun, but no plant or tank on the roof'
    return False, 'no plant, tank or lift overrun on the roof'
