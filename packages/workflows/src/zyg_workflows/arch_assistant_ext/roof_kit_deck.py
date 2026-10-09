# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The five stages of `build_roof_deck`, one function each.

`t_build_roof_deck` was 321 lines — argument resolution, the guard, the pool,
the plant and its two placements, the head-house door and the receipt all in
one body. Each of those is a stage here, called in the same order by the
orchestrator in `roof_kit`, with every refusal string, every `A.call_tool`
argument and every report line unchanged.

Two records carry what used to be the body's locals: `DeckPlan` (the resolved
arguments — the envelope, the group, the view letter, the pool and guard kinds,
the storey, the deck level and the name) and `DeckBuild` (what each stage left
behind — the ids, the pool rect, the cells and the report lines). A stage
returns `''` when it worked and the refusal text when it did not; the
orchestrator owns the single `_restore` that undoes the drawing, exactly as the
one body did.

The pure ones are the arithmetic the refusals quote: `plant_fit`,
`deck_plant_spots`, `head_house_plant_spots`, `plant_line` and `_plant_short`.
They were all inline before, so the unit tests beside this module are the first
time any of them ran on their own.

Import direction: this module imports `roof_kit` at module level and reaches
everything through `RK.` — so a `monkeypatch.setattr(roof_kit, 'A', …)` or a
rebound constant is still seen here. `roof_kit` therefore defers
`from . import roof_kit_deck as RD` into `t_build_roof_deck`, which keeps the
pair acyclic and makes the orchestrator the only deferral site.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field

from zyg_workflows.arch_assistant_ext import roof_kit as RK


@dataclass
class DeckPlan:
    """The arguments of one `build_roof_deck` call, resolved against the drawing.

    `env` is re-read by the orchestrator after the guard goes up (a parapet
    changes the envelope), which is why this record is not frozen.
    """

    env: dict
    g: str
    v: str
    pk: str
    gk: str
    N: int
    top: float
    nm: str


@dataclass
class DeckBuild:
    """What each stage left on the deck — for `d.ext['roof_deck']` and the reply."""

    guard_ids: list = field(default_factory=list)
    pool_id: str = ''
    pool_rect: tuple | None = None
    cells: tuple | None = None
    plant_ids: list = field(default_factory=list)
    door_ids: list = field(default_factory=list)
    lines: list = field(default_factory=list)


@dataclass(frozen=True)
class PlantFit:
    """Which plant units the `away` deck strip can hold, and how big each one is.

    `lo`/`hi` are the run of the away axis a unit's block may occupy; `deep` and
    `wide` are each unit's half-extents across and along the strip; `on_deck` and
    `off_deck` split the units by whether the strip is deep enough for them.
    """

    lo: float
    hi: float
    deep: dict
    wide: dict
    on_deck: list
    off_deck: list


def deck_plan(d, group, pool, view, guard, name) -> tuple:
    """(DeckPlan, '') when the call can be built, (None, refusal) when it cannot.

    Resolves the building group (the drawing's only non-head-house envelope when
    `group` is blank), the view letter, the pool kind and the guard kind, and
    refuses — by name, with the fix — when the envelope_rules family is absent,
    when the group is ambiguous or unknown, when it has no roof deck, when a
    kind is not one of ours, or when that roof is already laid out.
    """
    E = RK._m('envelope_rules')
    if E is None:
        return None, 'refused: build_roof_deck needs the envelope_rules family'
    g = str(group or '').strip()
    if not g:
        envs = {k: v for k, v in (E.envelopes(d) or {}).items() if not k.endswith(RK.HEAD_HOUSE)}
        if len(envs) != 1:
            return None, (
                'refused: name the building the roof belongs to (group=...) — draw_box prints it; '
                'this drawing has ' + (', '.join(f'"{k}"' for k in envs) if envs else 'none')
            )
        g = next(iter(envs))
    env = E.group_envelope(d, g)
    if env is None:
        return None, (
            f'refused: no building called "{g}" — draw the shell first '
            f'(draw_box(centre=..., width=..., depth=..., storeys=...)) and use the group name it prints'
        )
    if env.get('top_deck') is None:
        return None, (
            f'refused: "{g}" has no roof deck — draw_box(..., roof="flat") or add_roof first; a roof deck is '
            f'what everything here stands on'
        )
    v = RK.LETTER.get(RK.A.SIDE_WORDS.get(str(view or 'south').strip().lower()) or '')
    if not v:
        return None, 'refused: view must be north, south, east or west — the side the water falls away towards'
    pk = str(pool or 'infinity').strip().lower()
    if pk in ('', 'no', 'false'):
        pk = 'none'
    if pk not in RK.POOLS:
        return None, f'refused: pool="{pool}" is not a kind of water here — pool must be ' + ', '.join(RK.POOLS)
    gk = str(guard or 'glass').strip().lower()
    if gk in ('', 'no', 'false'):
        gk = 'none'
    if gk not in RK.GUARDS:
        return None, f'refused: guard="{guard}" is not a kind of guard here — guard must be ' + ', '.join(RK.GUARDS)
    # a deck is laid out once: a second call would stack a second pool on the
    # first and every walkway rule would then read off the wrong basin
    done = ((getattr(d, 'ext', None) or {}).get('roof_deck') or {}).get(g)
    if done and (not done.get('pool') or d.find(done['pool'])):
        return None, (
            f'refused: the roof of "{g}" is already laid out facing {done.get("view")} '
            f'{"(pool " + done["pool"] + ")" if done.get("pool") else "(no pool)"} — delete what is there '
            f'first, or change it with add_infinity_pool / add_rooftop_plant directly'
        )
    return (
        DeckPlan(
            env=env,
            g=g,
            v=v,
            pk=pk,
            gk=gk,
            N=int(env.get('storeys') or 0),
            top=RK._num(env['top_deck'], 0.0),
            nm=str(name or '').strip(),
        ),
        '',
    )


def build_guard(d, plan: DeckPlan, b: DeckBuild) -> str:
    """Stage 1 — a guard on every deck edge, BEFORE the water.

    add_parapet goes first so add_infinity_pool finds the view-side guard and
    turns it glass; any edge the parapet tool could not reach is given a wall
    record here. Returns '' or the refusal.
    """
    env, g, gk = plan.env, plan.g, plan.gk
    guard_ids, had = [], RK.guard_sides(d, env, g)
    if gk == 'none':
        return ''
    if not any(had.values()):
        was = {o['id'] for o in d.objs}
        r = str(
            RK.A.call_tool(
                d,
                'add_parapet',
                dict(
                    group=g,
                    height=RK.GUARD_H,
                    thickness=RK.GUARD_T,
                    material=('mat_glass' if gk == 'glass' else ''),
                    cap=False,
                ),
            )
        )
        if RK._failed(r):
            return f'refused: the deck guard could not be built — {RK._why(r)}'
        guard_ids = RK._new(d, was, ('wall',))
        had = RK.guard_sides(d, env, g)
    missing = [s for s in ('n', 'e', 's', 'w') if not had[s]]
    for s in missing:  # a side add_parapet could not reach
        if s in 'ns':
            L, gx = env['xmax'] - env['xmin'], (env['xmin'] + env['xmax']) / 2
            gz = RK._edge(env, s) + (RK.GUARD_IN + RK.GUARD_T / 2) * (1 if s == 'n' else -1)
            ry = 0.0
        else:
            L, gz = env['zmax'] - env['zmin'], (env['zmin'] + env['zmax']) / 2
            gx = RK._edge(env, s) + (RK.GUARD_IN + RK.GUARD_T / 2) * (1 if s == 'w' else -1)
            ry = math.pi / 2
        o = d.new(
            'wall',
            {'len': round(L, 4), 'h': RK.GUARD_H, 't': RK.GUARD_T},
            gx,
            gz,
            plan.top,
            ry,
            'mat_glass' if gk == 'glass' else 'mat_concrete',
            name='glass balustrade parapet' if gk == 'glass' else 'parapet',
            grp=g,
        )
        guard_ids.append(o['id'])
    had = RK.guard_sides(d, env, g)
    b.guard_ids = guard_ids
    b.lines.append(
        f'guard: {RK.GUARD_H:g} m {gk} on the '
        + ', '.join(RK.SIDES[s] for s in ('n', 'e', 's', 'w') if had[s])
        + ' edges'
        + (f' ({len(guard_ids)} new: {guard_ids[0]}..{guard_ids[-1]})' if guard_ids else ' (already there)')
    )
    return ''


def build_pool(d, plan: DeckPlan, cores: list, b: DeckBuild, depth, loungers, lounge) -> str:
    """Stage 2 — the pool in a band along the view facade.

    `pool_band` solves the block on whole cells; add_infinity_pool or add_pool
    draws it. Sets `b.cells`, `b.pool_id` and `b.pool_rect`. Returns '' or the
    refusal — which names the side that does work when this one does not.
    """
    env, v, pk, nm, N = plan.env, plan.v, plan.pk, plan.nm, plan.N
    if pk == 'none':
        return ''
    cells, rect, why = RK.pool_band(d, env, v, cores, 0.0 if pk == 'infinity' else RK.WALK_MIN)
    if cells is None:
        return f'refused: {why}'
    was = {o['id'] for o in d.objs}
    if pk == 'infinity':
        r = str(
            RK.A.call_tool(
                d,
                'add_infinity_pool',
                dict(
                    cell_from=cells[0],
                    cell_to=cells[1],
                    view=RK.SIDES[v],
                    storey=N,
                    depth=RK._num(depth, 1.4),
                    loungers=bool(loungers),
                    lounge=bool(lounge),
                    name=nm or 'infinity pool',
                ),
            )
        )
    else:
        r = str(
            RK.A.call_tool(
                d,
                'add_pool',
                dict(
                    cell_from=cells[0],
                    cell_to=cells[1],
                    storey=N,
                    depth=RK._num(depth, 1.4),
                    steps=RK.SIDES[RK.OPP[v]],
                    name=nm or 'roof pool',
                ),
            )
        )
    if RK._failed(r):
        return (
            f'refused: the pool over {cells[0]}..{cells[1]} was rejected by '
            f'add_{"infinity_" if pk == "infinity" else ""}pool — {RK._why(r)}'
        )
    made = RK._new(d, was, ('pool',))
    if not made:
        return f'refused: add_{"infinity_" if pk == "infinity" else ""}pool drew no pool — {RK._why(r)}'
    b.cells = cells
    b.pool_id = made[0]
    b.pool_rect = RK._bbox(d.find(b.pool_id))
    b.lines.append(r.strip())
    return ''


def plant_fit(d, env: dict, cores: list, top: float, away: str, plant_ids: list) -> PlantFit:
    """Measure the `away` strip and every plant unit against it.

    Each unit is measured on its own: the 2 m water tank may not fit the
    strip the 0.8 m air handler fits, and one strip sized for the deepest
    of them would send all three onto a 4.6 m head-house roof, where they
    would stand inside each other's maintenance clearance instead.
    """
    group_bb = RK.pool_group_bbox(d, env, top)
    lo, hi = RK.plant_band(env, cores, group_bb, away)
    deep = {i: RK._half(d.find(i), 'z' if away in 'ns' else 'x') for i in plant_ids}
    wide = {i: RK._half(d.find(i), 'x' if away in 'ns' else 'z') for i in plant_ids}
    on_deck = [i for i in plant_ids if hi - lo >= 2 * deep[i]]
    off_deck = [i for i in plant_ids if i not in on_deck]
    return PlantFit(lo=lo, hi=hi, deep=deep, wide=wide, on_deck=on_deck, off_deck=off_deck)


def deck_plant_spots(env: dict, away: str, fit: PlantFit) -> list:
    """[(id, (x, z))] — the on-deck units spread evenly along the `away` strip.

    Pure: one spot per `fit.on_deck` id, at `(i + 1) / (n + 1)` of the plate
    inboard of a 1 m margin along the strip, and hard against the strip's near
    edge across it.
    """
    s0, s1 = (env['xmin'] + 1.0, env['xmax'] - 1.0) if away in 'ns' else (env['zmin'] + 1.0, env['zmax'] - 1.0)
    placed = []
    for i, oid in enumerate(fit.on_deck):
        along = s0 + (s1 - s0) * (i + 1) / (len(fit.on_deck) + 1)
        fixed = (fit.lo + fit.deep[oid]) if away in ('n', 'w') else (fit.hi - fit.deep[oid])
        placed.append((oid, (along, fixed) if away in 'ns' else (fixed, along)))
    return placed


def head_house_plant_spots(hh: tuple, away: str, fit: PlantFit) -> tuple:
    """(ok, [(id, (x, z))], needed_m, span_m) for the units the deck cannot hold.

    Pure. They go in a row on the head-house roof, PLANT_EDGE in from each end
    and PLANT_CORE apart, with the slack shared out evenly. `ok` is False — and
    the spots empty — when the roof's run is shorter than `needed_m`, which the
    caller turns into the refusal that quotes both numbers.
    """
    (hx0, hz0, hx1, hz1), _hy = hh
    r0, r1 = (hx0, hx1) if away in 'ns' else (hz0, hz1)
    off_deck, wide = fit.off_deck, fit.wide
    need = 2 * sum(wide[i] for i in off_deck) + RK.PLANT_CORE * (len(off_deck) - 1) + 2 * RK.PLANT_EDGE
    if need > r1 - r0 + 1e-9:
        return False, [], need, r1 - r0
    fixed = (hz0 + hz1) / 2 if away in 'ns' else (hx0 + hx1) / 2
    slack = (r1 - r0 - need) / (len(off_deck) + 1)
    run = r0 + RK.PLANT_EDGE
    placed = []
    for oid in off_deck:
        run += slack + wide[oid]
        placed.append((oid, (run, fixed) if away in 'ns' else (fixed, run)))
        run += wide[oid] + RK.PLANT_CORE
    return True, placed, need, r1 - r0


def move_plant(d, placed: list) -> int:
    """Set each unit's x/z to its spot and its y to the surface under it.

    Returns how many records actually moved — the number the report line quotes,
    because add_rooftop_plant has no side argument and drops its units on the
    centre line.
    """
    moved = 0
    for oid, (x, z) in placed:
        o = d.find(oid)
        if abs(o['x'] - x) > 1e-6 or abs(o['z'] - z) > 1e-6:
            moved += 1
        o['x'], o['z'] = round(x, 4), round(z, 4)
        o['y'] = round(RK.A.surface_top(d, x, z), 4)
    return moved


def _plant_short(g: str, away: str, fit: PlantFit) -> str:
    """The clause both plant refusals open with: how deep the strip really is. Pure."""
    return (
        f'the {RK.SIDES[away]} strip of "{g}" is {max(fit.hi - fit.lo, 0.0):.1f} m deep once '
        f'{RK.PLANT_POOL:g} m is '
        f'kept clear of the pool and its loungers, parasols, palms and lights and {RK.PLANT_CORE:g} m '
        f'clear of the core'
    )


def plant_line(g: str, away: str, fit: PlantFit, plant_ids: list, moved: int) -> str:
    """The `plant: …` report line — how many units, where they went, how many moved. Pure."""
    on_deck, off_deck = fit.on_deck, fit.off_deck
    return (
        f'plant: {len(plant_ids)} unit(s) {", ".join(plant_ids)} — '
        + (
            f'{len(on_deck)} on the {RK.SIDES[away]} strip, {RK.PLANT_POOL:g} m clear of the pool group '
            f'and {RK.PLANT_CORE:g} m clear of the core'
            if on_deck
            else 'none left on the deck'
        )
        + (
            f'; {", ".join(off_deck)} on the head-house roof instead, the {RK.SIDES[away]} strip '
            f'being only {max(fit.hi - fit.lo, 0.0):.1f} m deep'
            if off_deck
            else ''
        )
        + (
            f' — add_rooftop_plant takes no side argument (mep_services.py:329), so {moved} '
            f'record(s) were moved there off the centre line'
            if moved
            else ''
        )
    )


def build_plant(d, plan: DeckPlan, cores: list, b: DeckBuild) -> str:
    """Stage 3 — the rooftop plant, MOVED to the strip on the side away from the view.

    add_rooftop_plant has no placement argument (mep_services.py:329 spreads one
    unit per kind along x on the centre line, in the view), so the units are
    placed, measured one by one, and then moved into the away strip — or onto the
    head-house roof when the strip is too shallow for them. Returns '' or the
    refusal.
    """
    env, g, v, nm, top = plan.env, plan.g, plan.v, plan.nm, plan.top
    was = {o['id'] for o in d.objs}
    r = str(RK.A.call_tool(d, 'add_rooftop_plant', dict(group=g, name=nm and f'{nm} plant' or '')))
    if RK._failed(r):
        return f'refused: the rooftop plant was rejected — {RK._why(r)}'
    plant_ids = RK._new(d, was)
    if not plant_ids:
        return f'refused: add_rooftop_plant placed no units on "{g}" — {RK._why(r)}'
    b.plant_ids = plant_ids
    away = RK.OPP[v]
    fit = plant_fit(d, env, cores, top, away, plant_ids)
    hh = RK.head_house_top(d, env, top) if fit.off_deck else None
    short = _plant_short(g, away, fit)
    named = {i: str(d.find(i).get('name') or i) for i in fit.off_deck}
    if fit.off_deck and hh is None:
        return (
            'refused: '
            + short
            + ' — '
            + ', '.join(f'{named[i]} is {2 * fit.deep[i]:.1f} m deep' for i in fit.off_deck)
            + ', and there is no head house to stand '
            + ('them' if len(fit.off_deck) > 1 else 'it')
            + ' on: build_roof_deck(..., plant=false) and place the plant by hand, or a bigger plate'
        )
    placed = deck_plant_spots(env, away, fit)
    if fit.off_deck:
        ok, more, need, span = head_house_plant_spots(hh, away, fit)
        if not ok:
            return (
                'refused: '
                + short
                + ' — too short for '
                + ', '.join(named[i] for i in fit.off_deck)
                + f', and the {span:.1f} m head-house roof needs {need:.1f} m to stand '
                + ('them' if len(fit.off_deck) > 1 else 'it')
                + f' there {RK.PLANT_CORE:g} m apart: build_roof_deck(..., plant=false) and place the '
                f'plant by hand, or a bigger plate'
            )
        placed += more
    b.lines.append(plant_line(g, away, fit, plant_ids, move_plant(d, placed)))
    return ''


def build_doors(d, plan: DeckPlan, b: DeckBuild) -> str:
    """Stage 4 — a head house you can get out of.

    A head house on this deck with walls but no door gets one, on the side
    facing the pool (or opposite the view when there is no pool). Returns '' or
    the refusal.
    """
    env, v = plan.env, plan.v
    door_ids = []
    for hg, h in RK.head_houses(d, env).items():
        if h['doors'] or not h['walls']:
            continue
        if b.pool_rect is not None:
            hx, hz = (h['bb'][0] + h['bb'][2]) / 2, (h['bb'][1] + h['bb'][3]) / 2
            px, pz = (b.pool_rect[0] + b.pool_rect[2]) / 2, (b.pool_rect[1] + b.pool_rect[3]) / 2
            side = ('e' if px > hx else 'w') if abs(px - hx) >= abs(pz - hz) else ('s' if pz > hz else 'n')
        else:
            side = RK.OPP[v]
        # a head house on the 54.3 m deck is storey 0 OF THE HEAD HOUSE, not
        # storey 20 of the tower: add_opening resolves the storey from the
        # record's own base (arch_assistant.storey_index), and naming the deck
        # storey gets the call refused.
        st = min(RK.A.storey_index(d, w) for w in h['walls'])
        was = {o['id'] for o in d.objs}
        r = str(
            RK.A.call_tool(d, 'add_opening', dict(group=hg, side=RK.SIDES[side], storey=st, kind='door', width=1.0))
        )
        if RK._failed(r):
            b.door_ids = door_ids
            return (
                f'refused: the head house "{hg}" could not be given a door on its {RK.SIDES[side]} side — {RK._why(r)}'
            )
        got = RK._new(d, was, tuple(RK.DOOR_KINDS))
        door_ids += got
        b.lines.append(
            f'head house "{hg}": door {", ".join(got) or "?"} on the {RK.SIDES[side]} side, towards the pool'
        )
    b.door_ids = door_ids
    return ''


def deck_receipt(d, plan: DeckPlan, before: set, b: DeckBuild) -> str:
    """Stage 5 — the `d.ext['roof_deck']` record, the selection, and the reply.

    The reply's head counts the new records and names the pool's cells; the body
    is the stages' own lines; the tail is what `roof_findings` makes of the deck,
    with the first three findings quoted.
    """
    g, v, N, top = plan.g, plan.v, plan.N, plan.top
    made = RK._new(d, before)
    d.selected = [i for i in ([b.pool_id] if b.pool_id else []) + b.plant_ids + b.door_ids if i]
    d.ext.setdefault('roof_deck', {})[g] = {
        'view': RK.SIDES[v],
        'pool': b.pool_id,
        'cells': list(b.cells) if b.cells else [],
        'guards': b.guard_ids,
        'plant': b.plant_ids,
        'doors': b.door_ids,
        'storey': N,
    }
    errs, warns = RK.roof_findings(d)
    head = f'roof deck of "{g}" facing {RK.SIDES[v]} (storey {N}, deck {top:g} m): {len(made)} new records' + (
        f', pool {b.pool_id} over {b.cells[0]}..{b.cells[1]}' if b.pool_id else ', no pool'
    )
    return (
        head
        + '\n'
        + '\n'.join(b.lines)
        + f'\nroof check: {len(errs)} error(s), {len(warns)} warning(s)'
        + (' — ' + '; '.join(f['text'] for f in (errs + warns)[:3]) if (errs or warns) else '')
    )
