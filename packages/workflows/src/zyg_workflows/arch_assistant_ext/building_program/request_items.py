# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""building_program.request_items — the evidence for the items the REQUEST adds.

Moved verbatim from arch_assistant_ext/building_program.py lines 360-682
(2026-10 split).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.building_program.evidence import (
    STAIRS,
    _A,
    _groups,
    _hit,
    _num,
    _top_deck,
    block_bounds,
)


# ── evidence for the items the REQUEST adds (2026-09-10) ────────────────────
def _ev_roof_pool(d, c) -> tuple:
    """The pool the request asked for, ON the deck. Job 71ac02b0's infinity pool
    was the whole point of the brief and the checklist never mentioned it."""
    deck = _top_deck(d)
    if deck < 0:
        return False, 'no roof record yet, so there is no deck to put the pool on'
    pools = [o for o in d.objs if o.get('kind') == 'pool' and not o.get('hidden')]
    up = [o for o in pools if (o.get('y') or 0.0) >= deck - 0.5]
    if up:
        # 2026-09-12: "infinity pool" is the pick, and a pick is only satisfied by the
        # thing itself — a plain basin on the deck used to pass this item.
        want_inf = (
            (c.get('pick_over') or {}).get('roof_pool') or (c.get('pick_of') or {}).get('roof_pool')
        ) == 'infinity'
        weirs = [o for o in up if (o.get('p') or {}).get('inf')]
        if want_inf and not weirs:
            return False, (
                f'{len(up)} pool record(s) on the {deck:.1f} m deck but none has an infinity edge (p.inf) — '
                f'the request asked for one: add_infinity_pool(cell_from, cell_to, view=<side>, storey=N), '
                f'or add_pool(..., infinity=<side>)'
            )
        return True, (
            f'{len(up)} pool record(s) on the {deck:.1f} m deck'
            + (f', {len(weirs)} with an infinity edge' if weirs else '')
        )
    if pools:
        hi = max((o.get('y') or 0.0) for o in pools)
        return False, (
            f'{len(pools)} pool record(s), the highest at {hi:.1f} m — none on the '
            f'{deck:.1f} m deck the request put it on'
        )
    return False, f'no pool record on the {deck:.1f} m deck'


DECK_FURNITURE = ('sun_lounger', 'umbrella', 'parasol', 'planter', 'table', 'deck_chair')


def _ev_deck_furniture(d, c) -> tuple:
    deck = _top_deck(d)
    if deck < 0:
        return False, 'no roof record yet, so there is no deck to furnish'
    n = 0
    for o in d.objs:
        if o.get('hidden') or (o.get('y') or 0.0) < deck - 0.6:
            continue
        if o.get('kind') in DECK_FURNITURE or _hit(o, ('lounger', 'parasol', 'umbrella', 'planter', 'table')):
            n += 1
    if n >= 4:
        return True, f'{n} piece(s) of furniture on the {deck:.1f} m deck'
    return False, f'{n} piece(s) of deck furniture on the {deck:.1f} m deck (need 4)'


BALCONY_WORDS = ('balcony', 'balconies')


def _ev_balconies(d, c) -> tuple:
    """Balconies are measured by the STOREYS they are on, not by the record count.

    Counting records answered the wrong question twice. A four-sided tower with
    forty balconies all on storey 3 passed, because forty is more than half of
    twenty; and the tower recipe's own south facade — eight balconies running
    every second storey from 4 to 18, which is exactly the rhythm the item
    exists to ask for — FAILED, because a one-facade design can never reach one
    record per two storeys times four sides. Ten records was above the maximum
    the drawing could hold, and a gate that cannot be satisfied is not a gate.

    So: a balcony run has to CARRY at least a quarter of the storeys (every
    second storey over half the height) and SPREAD over at least half of them.
    """
    try:
        storeys = max(1, int(_num(c.get('storeys'), 1)))
        H = d.storey_h or 2.7
        on = set()
        n = 0
        for o in d.objs:
            if o.get('hidden'):
                continue
            if o.get('kind') != 'balcony' and not _hit(o, BALCONY_WORDS):
                continue
            n += 1
            on.add(int(round((o.get('y') or 0.0) / H)))
        need_on = max(1, storeys // 4)
        need_span = max(1, storeys // 2)
        span = (max(on) - min(on) + 1) if on else 0
        where = f'{n} balcony record(s) on {len(on)} storey(s), spread over {span} of {storeys}'
        if len(on) >= need_on and span >= need_span:
            return True, where
        return False, (f'{where} — need {need_span} storeys of spread and {need_on} balconied storeys')
    except Exception as e:  # noqa: BLE001
        return False, f'the balcony count could not be read ({e!r})'


# the shell surfaces a person sees.  A 'luxurious' request answered in
# mat_concrete + mat_steel — which is what job 71ac02b0 delivered — is a grey
# massing model, so the finish is an ITEM with evidence, not a hope.
FINISH_KINDS = ('slab', 'wall', 'elevator_shaft') + STAIRS
FLAT_PRESETS = frozenset(list(_A.MATERIALS))  # the 21 mat_* presets, without the library
# glass on these kinds is glazing, not an unfinished preset (finish_rules exempts the same set)
GLASS_OK_KINDS = ('curtain_wall', 'wall', 'door', 'double_door', 'window', 'parapet', 'parapet_cap', 'canopy')


def _shell_records(d, c) -> list:
    """The building's own slabs, walls, stairs and shafts: everything of those
    kinds standing on the footprint the programme was resolved for."""
    try:
        xmin, zmin, xmax, zmax = block_bounds(c.get('cell_from') or '', c.get('cell_to') or '')
    except Exception:  # noqa: BLE001
        return []
    out = []
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in FINISH_KINDS:
            continue
        x, z = (o.get('x') or 0.0), (o.get('z') or 0.0)
        if xmin - 2.0 <= x <= xmax + 2.0 and zmin - 2.0 <= z <= zmax + 2.0:
            out.append(o)
    return out


def _ev_finishes(d, c) -> tuple:
    recs = _shell_records(d, c)
    if not recs:
        return False, 'no slab, wall, stair or shaft on the footprint yet — nothing is finished'
    lib = _A.MATERIALS._library()
    bad = {}
    for o in recs:
        m = str(o.get('mat') or '')
        if m == 'mat_glass' and o.get('kind') in GLASS_OK_KINDS:  # 2026-09-11: glazing IS the finish
            continue
        if m in FLAT_PRESETS and m not in lib:
            bad[m] = bad.get(m, 0) + 1
    if bad:
        worst = ', '.join(f'{k} x{v}' for k, v in sorted(bad.items(), key=lambda kv: -kv[1])[:4])
        return False, (
            f'{sum(bad.values())} of {len(recs)} shell record(s) are still flat presets '
            f'({worst}) — a luxury request answered in mat_concrete is a grey massing model'
        )
    return True, f'all {len(recs)} shell record(s) carry a material-library finish'


INTERIOR_KINDS = ('partition', 'zone', 'door')


def _laid_out(d, N) -> list:
    """The upper storeys with no plan on them. A storey counts as laid out when
    the floor-plan registry claims it (place_plan / layout_floor / repeat_floor
    all write d.ext['floor_layouts'][str(storey)]) or when the storey carries at
    least four interior records of its own."""
    H = d.storey_h or 2.7
    store = (d.ext or {}).get('floor_layouts')
    store = store if isinstance(store, dict) else {}
    per: dict = {}
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in INTERIOR_KINDS:
            continue
        y = o.get('y') or 0.0
        s = int(round(y / H))
        if abs(y - s * H) <= 0.35:
            per[s] = per.get(s, 0) + 1
    return [s for s in range(1, max(1, int(N))) if str(s) not in store and per.get(s, 0) < 4]


def _ev_typical_floors(d, c) -> tuple:
    """Job 94f5813b's tower: storeys 1-19 held nothing but slab and facade, and
    the programme gate passed, because no item ever asked what was ON them."""
    N = max(1, int(c['storeys']))
    if N < 2:
        return True, 'a single-storey building has no upper floors'
    empty = _laid_out(d, N)
    if empty:
        return False, 'EMPTY storeys: ' + ', '.join(str(s) for s in empty)
    return True, f'storeys 1-{N - 1} laid out'


def _ev_corridor(d, c) -> tuple:
    grps = _groups(d, ('corridor', 'circulation', 'hallway'))
    if grps:
        return True, f'a group or zone named {sorted(grps)[0]}'
    store = (d.ext or {}).get('floor_layouts')
    if isinstance(store, dict) and store:
        return True, f'{len(store)} laid-out storey(s) — a placed floor plan carries its own halls'
    return False, 'a group or zone named corridor/circulation'


def _how_typical_floors(c) -> str:
    top = max(1, int(c['storeys'])) - 1
    up = f'repeat_floor(from_storey=2, to_storey={top}, source_storey=1)'
    if c['pick'] == 'real_plan':
        return (
            f'search_plans(kind="floor", width={c["w"]:g}, depth={c["d"]:g}) for a real floor, then '
            f'place_plan(plan_id=<id>, group=<group>, storey=1, align="core"), then {up} — '
            f'one plan, carried up the tower'
        )
    if c['pick'] == 'tiled_units':
        cw = (c.get('pick_of') or {}).get('corridor') or '1.5'
        return f'tile_units(<group>, storey=1, corridor_w={cw}) packs real flats either side of the corridor, then {up}'
    return f'layout_floor(cell_from, cell_to, use="{c["use"]}", storey=1) cuts storey 1, then {up}'


def _room_span(d, grp) -> float:
    """How far a room reaches: add_room draws four `partition` records at the
    mid-point of each side, so the bounding box of that group's records IS the
    room. The larger of the two spans is what 'double height, 8 m deep' means."""
    pts = [
        ((o.get('x') or 0.0), (o.get('z') or 0.0))
        for o in d.objs
        if (o.get('grp') or '') == grp and not o.get('hidden')
    ]
    if len(pts) < 2:
        return 0.0
    return round(
        max(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts)), 1
    )


def _room_spans(d, grp) -> tuple:
    """(long, short) spans of a room group in metres. 2026-09-12: _room_span alone let
    job 94f5813b's 10 x 3 m 'Lobby' (a corridor with a desk) pass the 8 m luxury test."""
    pts = [
        ((o.get('x') or 0.0), (o.get('z') or 0.0))
        for o in d.objs
        if (o.get('grp') or '') == grp and not o.get('hidden')
    ]
    if len(pts) < 2:
        return 0.0, 0.0
    a = max(p[0] for p in pts) - min(p[0] for p in pts)
    b = max(p[1] for p in pts) - min(p[1] for p in pts)
    return round(max(a, b), 1), round(min(a, b), 1)


LOBBY_ACROSS_M = 8.0
LOBBY_DEEP_M = 6.0


LOBBY_WORDS = ('lobby', 'foyer', 'entrance hall', 'reception')
SEATS = ('sofa', 'armchair')
SEAT_WORDS = ('sofa', 'armchair', 'settee', 'couch', 'lounge chair')  # a pack model (kind 'asset') that is a seat


def _seat_kind(o) -> str:
    """'sofa' / 'armchair' for a pack-model record that is a seat (its name or
    asset id says so), '' otherwise. furnish_lobby(style='luxury') places
    polyhaven sofas and armchairs as kind 'asset' (2026-09-16), and the lobby
    item must count them or the fit-out needs four box chairs beside them."""
    if o.get('kind') != 'asset':
        return ''
    p = o.get('p') or {}
    txt = ' '.join(
        str(v) for v in (o.get('name'), p.get('asset'), p.get('id'), p.get('query'), p.get('model')) if v
    ).lower()
    if not any(w in txt for w in SEAT_WORDS):
        return ''
    return 'sofa' if ('sofa' in txt or 'settee' in txt or 'couch' in txt) else 'armchair'


LIGHT_KINDS = ('light_point', 'light_spot', 'light_area', 'lamp_floor', 'lamp_post')


def _room_rect(d, grps) -> tuple:
    """The bounding rectangle of every record in the lobby's groups."""
    pts = [
        ((o.get('x') or 0.0), (o.get('z') or 0.0))
        for o in d.objs
        if (o.get('grp') or '') in grps and not o.get('hidden')
    ]
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _lobby_contents(d, grps) -> dict:
    """What stands in the lobby: its own groups, plus anything of the right kind
    standing inside the block those groups draw (a fit-out group of its own,
    or furniture placed by hand)."""
    rect = _room_rect(d, grps)
    want = set(('desk',) + SEATS + LIGHT_KINDS)
    out: dict = {}
    for o in d.objs:
        kind = _seat_kind(o) or o.get('kind')
        if o.get('hidden') or kind not in want:
            continue
        if (o.get('grp') or '') not in grps:
            if rect is None:
                continue
            x, z = (o.get('x') or 0.0), (o.get('z') or 0.0)
            if not (rect[0] - 0.3 <= x <= rect[2] + 0.3 and rect[1] - 0.3 <= z <= rect[3] + 0.3):
                continue
        out[kind] = out.get(kind, 0) + 1
    return out


def _ev_lobby(d, c) -> tuple:
    grps = _groups(d, LOBBY_WORDS)
    if not grps:
        return False, 'no group or zone named lobby/foyer/reception'
    if str(c.get('finish_level') or 'standard') != 'luxury':
        return True, f'a group or zone named {sorted(grps)[0]}'
    best, deep, where = 0.0, 0.0, ''
    for g in sorted(grps):
        s, t = _room_spans(d, g)
        # the room that qualifies on width first, then the DEEPEST — two rooms named
        # 'Lobby' of equal width must not resolve to the corridor drawn first
        if (s >= LOBBY_ACROSS_M, t, s) > (best >= LOBBY_ACROSS_M, deep, best):
            best, deep, where = s, t, g
    if best < LOBBY_ACROSS_M or deep < LOBBY_DEEP_M:
        return False, (
            f'the largest room named lobby/foyer is {best:g} x {deep:g} m, and a luxury lobby is at least '
            f'{LOBBY_ACROSS_M:g} m across AND {LOBBY_DEEP_M:g} m deep — add_room over a block at least 8 x 6 cells '
            f'(a 10 x 3 m room is a corridor with a desk)'
        )
    # Job 94f5813b: four plaster partitions and nothing inside passed this item.
    have = _lobby_contents(d, grps)
    desks = have.get('desk', 0)
    seats = sum(have.get(k, 0) for k in SEATS)
    lights = sum(have.get(k, 0) for k in LIGHT_KINDS)
    if desks >= 1 and seats >= 2 and lights >= 1:
        return True, (f'"{where}" is {best:g} m across and furnished: {desks} desks, {seats} seats, {lights} lights')
    return False, (
        f'"{where}" is {best:g} m across but a luxury lobby is EMPTY — it holds {desks} desks, '
        f'{seats} seats, {lights} lights and needs a reception desk, two seats and a light: '
        f'furnish_lobby(cell_from, cell_to, storey=0, entrance_side=<side>)'
    )
