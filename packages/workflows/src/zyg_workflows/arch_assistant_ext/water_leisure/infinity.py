# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.infinity — add_infinity_pool as one call, and check_infinity_pools / DESIGN_CHECKS.

Moved verbatim out of water_leisure.py (lines 709-1259); zero logic changes.
The stages the one call runs through live in infinity_build; t_add_infinity_pool
here is the order they run in and the report they build.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.water_leisure import infinity_build as _build

from zyg_workflows.arch_assistant_ext.water_leisure.base import (
    Drawing,
    SIDES,
    _deck_extent,
    _num,
)

from zyg_workflows.arch_assistant_ext.water_leisure.pool import (
    GUARD_H,
    INF_TILE,
    POOL_MIN_SIDE,
    SWIM_DEPTH,
    WALK_MIN,
    _OPP,
    _coverage,
    _guards_along,
    _n_treads,
    _pool_deck,
    _pool_span,
)


def t_add_infinity_pool(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    view='south',
    storey=None,
    base_height=None,
    depth=1.4,
    level='deck',
    loungers=True,
    parasols=True,
    palms=True,
    lounge=True,
    lights=True,
    material='',
    name='',
):
    """A rooftop infinity pool as ONE call: the basin with its glass weir, the
    guard outboard of it, the plant zone under it, loungers with their parasols
    and palms, a lounge set and the underwater lights.

    Every stage lives in infinity_build; what is left here is the order they run
    in and the report they build, which is the part that must not change. The
    position is refused BEFORE anything is drawn — the core clearance and the
    walkways round the coping — so a refusal never leaves half a pool behind.
    """
    opts, refused = _build.pool_options(view, depth, level, material, name)
    if refused:
        return refused
    # ── the deck as it already is: refuse a bad position before drawing it ──
    refused, plant_in_view, walk_tight = _build.position_notes(d, cell_from, cell_to, storey, base_height, opts)
    if refused:
        return refused
    f, txt = _build.draw_basin(d, a, cell_from, cell_to, storey, base_height, opts)
    if f is None:
        return txt  # add_pool refused the block, or drew something that is not a pool
    lines, inf = f.lines, f.inf
    _build.deck_works(d, f)
    lines.append(f'entry steps on the {SIDES[_OPP[inf]]} side ({_n_treads(f.dep)} treads), never on the weir')
    for side, clear in walk_tight:
        lines.append(
            f'NOTE: only {clear:.2f} m of deck on the {SIDES[side]} side — a walkway is {WALK_MIN:g} m '
            f'and this deck has no room for one; design_check reports it as deck_walkway'
        )
    if plant_in_view:
        ids = ', '.join(f'{o["id"]} {o["kind"]}' for o in plant_in_view[:4])
        lines.append(
            f'NOTE: {ids} stand{"" if len(plant_in_view) == 1 else ""} on the {SIDES[inf]} side, in the '
            f'view the pool was made for — rooftop plant belongs {SIDES[_OPP[inf]]} of the water: '
            f'move() them, or delete() and add_rooftop_plant(group=...) again'
        )

    # ── the deck contents, in the order they take their room out of it ──────
    row_side, full = _build.lounger_row(d, f, loungers, parasols, palms)
    if full:
        return '\n'.join(lines) + '\n' + full
    _build.lounge_set(d, f, row_side, lounge)
    _build.underwater_lights(d, f, lights)
    lines.append(
        f'tile {f.mat}'
        + (' (deep blue; material="turquoise"/"charcoal" or any id changes it)' if f.mat == INF_TILE else '')
    )
    todo = []
    if f.deck:
        todo.append('parapets 1.1 m on the other roof edges if none (add_parapet(group, height=1.1))')
        todo.append('the deck finish (set_finish(group, roof_material="pht_wood_floor_deck") for timber)')
    todo.append('design_check() before done')
    lines.append('still yours: ' + '; '.join(todo))
    return '\n'.join(lines)


def check_infinity_pools(d: Drawing) -> list:
    """What an infinity pool must have (2026-09-12, from the operator's pictures):
    a glass guard >= 1.1 m outboard of the weir, entry steps off the weir side,
    swimming depth, a short side of 4 m, and — deck-level — the tank zone under
    it. Plain pools are not looked at; check_pools (design_rules) does the water
    level for every pool."""
    out = []
    for o in d.objs:
        if o.get('kind') != 'pool' or o.get('hidden'):
            continue
        p = o.get('p') or {}
        inf = str(p.get('inf') or '')[:1]
        if inf not in _OPP:
            continue
        lbl = f'{o["id"]} {o.get("name") or "pool"}'
        dep = _num(p.get('depth'), 1.5)
        stp = str(p.get('steps') or '')[:1]
        if stp == inf:
            out.append(
                {
                    'sev': 'error',
                    'code': 'inf_steps',
                    'text': f'{lbl}: the entry steps are on the {SIDES[inf]} side, which is the infinity edge — '
                    f'steps="{SIDES[_OPP[inf]]}" (the deck side)',
                }
            )
        elif not stp:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'pool_entry',
                    'text': f'{lbl}: no entry steps — add_pool(..., steps="{SIDES[_OPP[inf]]}") or '
                    f'add_infinity_pool builds them on the deck side with a handrail',
                }
            )
        if dep < SWIM_DEPTH[0] - 1e-6 or dep > SWIM_DEPTH[1] + 1e-6:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'pool_depth',
                    'text': f'{lbl}: {dep:g} m deep — a swimming pool is 1.2-1.5 m uniform',
                }
            )
        if min(_num(p.get('w'), 8.0), _num(p.get('d'), 4.0)) < POOL_MIN_SIDE - 1e-6:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'pool_narrow',
                    'text': f'{lbl}: {_num(p.get("w"), 8):g} x {_num(p.get("d"), 4):g} m — an infinity pool is '
                    f'{POOL_MIN_SIDE:g} m or more across its short side',
                }
            )
        deck = _pool_deck(d, o)
        if deck is None:
            continue
        ext = _deck_extent(deck)
        lo, hi = _pool_span(o, inf)
        guards = _guards_along(d, deck, inf, ext, lo, hi)
        cov = _coverage(guards, inf, lo, hi)
        grp = deck.get('grp') or deck.get('name') or deck['id']
        fix = (
            f'add_infinity_pool builds it; or add_parapet("{grp}", height={GUARD_H:g}, material="mat_glass") '
            f'then add_pool turns that side to glass'
        )
        if cov < (hi - lo) * 0.9:
            out.append(
                {
                    'sev': 'error',
                    'code': 'inf_guard',
                    'text': f'{lbl}: its {SIDES[inf]} infinity edge is an OPEN roof edge — {hi - lo - cov:.1f} m of '
                    f'the weir has no guard; a glass balustrade >= {GUARD_H:g} m must stand OUTBOARD of the '
                    f'trough, the weir is never the building edge ({fix})',
                }
            )
        else:
            low = [g for g in guards if _num(g['p'].get('h'), 0.0) < GUARD_H - 1e-6]
            if low:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'inf_guard_low',
                        'text': f'{lbl}: the guard on the {SIDES[inf]} infinity edge is '
                        f'{min(_num(g["p"].get("h"), 0.0) for g in low):g} m — {GUARD_H:g} m is the rule '
                        f'above a roof drop ({", ".join(g["id"] for g in low)}: set p.h or rebuild it)',
                    }
                )
            solid = [g for g in guards if g.get('kind') == 'wall' and g.get('mat') != 'mat_glass']
            if solid:
                out.append(
                    {
                        'sev': 'warn',
                        'code': 'inf_view',
                        'text': f'{lbl}: the guard on the {SIDES[inf]} infinity edge is solid '
                        f'({", ".join(g["id"] + " " + str(g.get("mat")) for g in solid)}) — it hides the view '
                        f"the weir exists for; set_material(ids, 'mat_glass')",
                    }
                )
        raised = _num(p.get('raised'), 0.0)
        if raised < dep - 1e-6:
            tank = [
                z
                for z in d.objs
                if z.get('kind') == 'zone'
                and not z.get('hidden')
                and 'tank' in str(z.get('name') or (z.get('p') or {}).get('name') or '').lower()
                and abs(z['x'] - o['x']) < _num(p.get('w'), 8.0)
                and abs(z['z'] - o['z']) < _num(p.get('d'), 4.0)
                and o['y'] - (d.storey_h or 2.7) - 0.6 < z['y'] < o['y']
            ]
            if not tank:
                out.append(
                    {
                        'sev': 'warn',
                        'code': 'pool_tank',
                        'text': f'{lbl}: the basin hangs {dep - raised:.2f} m into the storey below with no plant '
                        f'zone under it — the balance tank, filtration and edge pumps live there '
                        f'(add_infinity_pool registers "pool tank + balance tank + plant")',
                    }
                )
    return out


DESIGN_CHECKS = [check_infinity_pools]
