# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.tools — the model-facing tools: search_plans, plan_info, place_plan
and core_from_plan. Moved verbatim out of floor_plans.py (2026-10-06)."""

from __future__ import annotations

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    block_bounds,
    _num,
)
import logging as _zyg_logging

from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    EXT_KEY,
    KINDS_OK,
    SCALE_MAX,
    SCALE_MIN,
    SIDES_CW,
    _best_rot,
    _core_rects,
    _fit_scale,
    _group_plate,
    _group_slab,
    _poly_centre,
    _slab_rect,
    attribution_of,
    load_plan,
    packs,
    plans_dir,
)
from zyg_workflows.arch_assistant_ext.floor_plans.placing import (
    _place,
    _plan_transform,
    record_attribution,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.floor_plans')


# ── search ───────────────────────────────────────────────────────────────────
def _types_text(types: str) -> str:
    seen: list = []
    n: dict = {}
    for t in [x.strip() for x in str(types or '').split(',') if x.strip()]:
        if t not in n:
            seen.append(t)
        n[t] = n.get(t, 0) + 1
    return ', '.join((f'{n[t]} {t}' if n[t] > 1 else t) for t in seen)


def _target(d: Drawing, value, storey=0) -> tuple:
    """(metres, metres_or_None, note) from a number of cells or a group name."""
    if value in (None, ''):
        return None, None, ''
    try:
        return float(value) * d.cell_m, None, ''
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('target %r is not a number, treating it as a group name: %s', value, _exc)
    slab, err = _group_slab(d, str(value), storey)
    if err:
        return None, None, err
    x0, z0, x1, z1 = _slab_rect(slab)
    return x1 - x0, z1 - z0, ''


def t_search_plans(
    d: Drawing, a, kind='unit', width=None, depth=None, rooms=None, types='', pack='', limit=8, storey=0
):
    pk = packs()
    if not pk:
        return (
            f'refused: no plan packs under {plans_dir()} — the converters write them to '
            f'data/architecture/plans/<pack>/; set ZYG_PLANS_DIR to point elsewhere'
        )
    k = str(kind or 'unit').strip().lower()
    if k not in KINDS_OK:
        return f'refused: kind must be {", ".join(KINDS_OK)}'
    if pack and pack not in pk:
        return f'refused: no pack "{pack}" — the packs here are {", ".join(sorted(pk))}'

    W, D, note = _target(d, width, storey)
    if note:
        return note
    if W is not None and D is None:
        D2, _u, note = _target(d, depth, storey)
        if note:
            return note
        D = D2 if D2 is not None else W
    want = [t.strip().lower() for t in str(types or '').replace(';', ',').split(',') if t.strip()]
    n_rooms = None
    if rooms not in (None, ''):
        n_rooms = int(_num(rooms, 0))

    scored = []
    for name, p in sorted(pk.items()):
        if pack and name != pack:
            continue
        for r in p['rows']:
            if str(r.get('kind')) != k:
                continue
            if n_rooms is not None and int(_num(r.get('n_rooms'), 0)) != n_rooms:
                continue
            have = [t.strip().lower() for t in str(r.get('types') or '').split(',') if t.strip()]
            missing = [t for t in want if t not in have]
            score = 0.15 * len(missing) - 0.05 * _num(r.get('fill'), 0.0)
            rot, rw, rd = 0, _num(r.get('w'), 0.0), _num(r.get('d'), 0.0)
            s = 0.0
            if W:
                rot, rw, rd = _best_rot(W, D, _num(r.get('w'), 0.0), _num(r.get('d'), 0.0))
                score += abs(rw - W) / max(W, 1e-6) + abs(rd - D) / max(D, 1e-6)
                s = _fit_scale(W, D, rw, rd)
            scored.append((score, name, r, rot, s))
    if not scored:
        return f'no {k} plans match in {", ".join(sorted(pk)) if not pack else pack} — the packs hold ' + ', '.join(
            f'{n}: ' + ', '.join(f'{c} {kk}' for kk, c in sorted((p['manifest'].get('count') or {}).items()) if c)
            for n, p in sorted(pk.items())
        )
    scored.sort(key=lambda t: t[0])
    lim = max(1, min(30, int(_num(limit, 8))))
    lines = []
    for _score, _name, r, rot, s in scored[:lim]:
        line = (
            f'{r["id"]}: {_num(r.get("w"), 0):g} x {_num(r.get("d"), 0):g} m, '
            f'{_num(r.get("area"), 0):.0f} m², {int(_num(r.get("n_rooms"), 0))} rooms '
            f'({_types_text(r.get("types"))}), entrance {r.get("entrance") or "unknown"}'
        )
        if W:
            if SCALE_MIN - 1e-9 <= s <= SCALE_MAX + 1e-9:
                line += f' — fits at scale {s:.2f}'
                if rot:
                    line += f' rotated {rot}°'
            else:
                line += f' — does not fit (scale {s:.2f}, past ±12 %)'
        lines.append(line)
    head = f'{len(scored)} {k} plan(s)' + (f' for a {W:g} x {D:g} m bay' if W else '') + f', best {len(lines)}:'
    return (
        head
        + '\n'
        + '\n'.join(lines)
        + '\n(place_plan(plan_id, group=…, storey=…) draws one; plan_info(id) shows its rooms '
        'and its attribution.)'
    )


def t_plan_info(d: Drawing, a, plan_id=''):
    plan = load_plan(plan_id)
    if not plan:
        pk = packs()
        if not pk:
            return f'refused: no plan packs under {plans_dir()}'
        return f'refused: no plan "{plan_id}" in {", ".join(sorted(pk))} — search_plans(kind="unit") lists the ids'
    rooms = plan.get('rooms') or []
    by = {}
    for r in rooms:
        t = str(r.get('type') or 'other')
        by[t] = by.get(t, 0) + 1
    ent = plan.get('entrance') or {}
    core = plan.get('core') or {}
    src = plan.get('source') or {}
    return (
        f'{plan["id"]} ({plan.get("pack")}, {plan.get("kind")}): {_num(plan.get("w"), 0):g} x '
        f'{_num(plan.get("d"), 0):g} m, {_num(plan.get("area"), 0):.0f} m², storey height '
        f'{_num(plan.get("storey_h"), 2.7):g} m.\n'
        f'{len(rooms)} rooms: '
        + ', '.join(f'{v} {kk}' for kk, v in sorted(by.items(), key=lambda kv: -kv[1]))
        + f'\n{len(plan.get("walls") or [])} wall segments, {len(plan.get("doors") or [])} doors, '
        f'{len(plan.get("windows") or [])} windows, {len(plan.get("fixtures") or [])} fixtures'
        + (
            f'\ncore: {len(core.get("stairs") or [])} stair(s), {len(core.get("lifts") or [])} lift(s)'
            if core.get('stairs') or core.get('lifts')
            else ''
        )
        + f'\nentrance: {ent.get("side") or "unknown"}'
        + (f' at {_num(ent.get("x"), 0):g}, {_num(ent.get("z"), 0):g} m in the plan' if ent.get('side') else '')
        + ('\nsource: ' + ', '.join(f'{kk} {vv}' for kk, vv in sorted(src.items())) if src else '')
        + f'\nattribution (goes in the credits): {attribution_of(str(plan.get("pack")))}'
    )


# ── the tool that draws ──────────────────────────────────────────────────────
def _plan_errors(d: Drawing) -> list:
    """[(code, text)] of the walkability and corridor ERRORS on the drawing —
    what place_plan compares before and after to decide a plan made a storey
    worse. Never raises: a missing family judges nothing."""
    out = []
    for fam, fn in (('walk_rules', 'check_walkable'), ('floor_rules', 'check_typical_floors')):
        M = A.EXT_MODULES.get(fam)
        f = getattr(M, fn, None) if M is not None else None
        if not callable(f):
            continue
        try:
            for r in f(d) or []:
                if r.get('sev') == 'error':
                    out.append((str(r.get('code') or ''), str(r.get('text') or '')))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('%s.%s failed: %s', fam, fn, _exc)
            continue
    return out


def t_place_plan(
    d: Drawing,
    a,
    plan_id='',
    group='',
    cell_from='',
    cell_to='',
    storey=0,
    align='centre',
    entrance_side='',
    mirror=False,
    rotate_deg=0,
    scale='fit',
    snap=0.25,
    doors=True,
    windows=True,
    zones=True,
    fixtures=True,
    shell=False,
    name='',
):
    plan = load_plan(plan_id)
    if not plan:
        if not packs():
            return (
                f'refused: no plan packs under {plans_dir()} — nothing to place; the converters write '
                f'them to data/architecture/plans/<pack>/'
            )
        return f'refused: no plan "{plan_id}" — search_plans(kind="unit") lists the ids'
    st = int(_num(storey, 0))
    al = str(align or 'centre').strip().lower()
    if al not in ('centre', 'center', 'core', 'entrance'):
        return 'refused: align must be "centre", "core" or "entrance"'
    al = 'centre' if al == 'center' else al

    y = None
    if group:
        # 2026-09-11: the WHOLE plate — add_stair cuts the slab into pieces, and the
        # first piece alone read as "20 x 5.15 m" and refused every floor plan
        rect, y, err = _group_plate(d, str(group), st)
        if err:
            return err
    elif cell_from and cell_to:
        try:
            rect = block_bounds(cell_from, cell_to)
        except ValueError as e:
            return f'refused: {e}'
        y = st * d.storey_h
    else:
        return (
            'refused: say where — group="<the name draw_box returned>" puts the plan on that box\'s slab, '
            'or cell_from/cell_to puts it on a block of cells'
        )

    opts = {
        'y': y,
        'grp': str(name or '') or f'plan {plan["id"]} st{st}',
        'group': str(group or ''),
        'mirror': mirror,
        'rotate_deg': rotate_deg,
        'scale': scale,
        'align': al,
        'entrance_side': entrance_side,
        'snap': snap,
        'doors': doors,
        'windows': windows,
        'zones': zones,
        'fixtures': fixtures,
        'shell': bool(shell),
    }
    before = _plan_errors(d)  # (C) the walk / corridor errors the drawing already had
    res = _place(d, plan, rect, st, opts)
    if res['error']:
        return res['error']
    ids = res['ids']
    if not ids:
        return f'refused: {plan["id"]} produced no records in that rectangle — check the storey and the group name'
    # (B) 2026-09-16 (job 944061f70863): a 19.74 m plan aligned to the core in a
    # 20 m plate hung 1 m over the north edge and its kitchen counters and
    # toilets stood outside the building (envelope_outside x8 per storey, x19
    # storeys). Nothing of a plan stands outside the plate it was placed on.
    outside = [
        o
        for o in (d.find(i) for i in ids)
        if o is not None
        and not (
            rect[0] - 0.05 <= _num(o.get('x'), 0.0) <= rect[2] + 0.05
            and rect[1] - 0.05 <= _num(o.get('z'), 0.0) <= rect[3] + 0.05
        )
    ]
    if outside:
        d.remove(outside)
        gone = {o['id'] for o in outside}
        ids = [i for i in ids if i not in gone]
        res['notes'].append(f'{len(outside)} record(s) of the plan fell outside the plate and were dropped')

    store = d.ext.get(EXT_KEY)
    if not isinstance(store, dict):
        store = {}
    x0, z0, x1, z1 = res['rect']
    with A._Scale(d.cell_m):
        cf, ct = A.cell_of(x0, z0), A.cell_of(x1 - 1e-6, z1 - 1e-6)
    store[str(st)] = {
        'use': 'plan',
        'ids': ids,
        'cell_from': cf,
        'cell_to': ct,
        'plan': plan['id'],
        'pack': plan.get('pack'),
        'plate': res['grp'],
        'units': 1,
        'corridor_w': 0.0,
        'unit_w': round(x1 - x0, 2),
        'depth': round(z1 - z0, 2),
        'scale': res['scale'],
        'rotate_deg': res['rot'],
        'mirror': bool(mirror),
    }
    d.ext[EXT_KEY] = store
    # (C) 2026-09-16 (job 944061f70863): a plan whose rooms enclose the core that
    # add_core drew left the stair landing unreachable and the corridor '0.00 m
    # clear' on 19 storeys; the model then spent 31 calls deleting partitions.
    # A plan that makes the storey unwalkable is UNDONE and refused here, the
    # way the macros undo an inner refusal — layout_floor is the tool for a
    # plate with a drawn core, core_from_plan the way to a plan's own core.
    new_err = [f for f in _plan_errors(d) if f not in before]
    if new_err:
        d.remove([o for o in (d.find(i) for i in ids) if o is not None])
        store.pop(str(st), None)
        d.ext[EXT_KEY] = store
        d.selected = []
        why = '; '.join(t for _c, t in new_err[:2])
        return (
            f'refused: {plan["id"]} on storey {st} would leave the storey unwalkable — {why[:300]} — '
            f'nothing was placed. On a plate with a core drawn by add_core use layout_floor(cell_from, '
            f'cell_to, use=..., storey={st}, core_from, core_to); a plan fits only its OWN core '
            f'(core_from_plan(plan_id) first, then place_plan(align="core"))'
        )
    attr = record_attribution(d, str(plan.get('pack')), plan['id'])
    d.selected = ids[:200]

    counts = ', '.join(
        f'{v} {k}' + ('s' if v > 1 and not k.endswith('s') else '')
        for k, v in sorted(res['counts'].items(), key=lambda kv: -kv[1])
    )
    return (
        f'placed {plan["id"]} ({plan.get("kind")}, {_num(plan.get("w"), 0):g} x '
        f'{_num(plan.get("d"), 0):g} m) on storey {st} of '
        f'{group or (cf + ".." + ct)} at y {res["y"]:g} m: {counts} in group "{res["grp"]}" '
        f'({len(ids)} records). Scale {res["scale"]:.2f}'
        + (f', rotated {res["rot"]}°' if res['rot'] else '')
        + (', mirrored' if mirror else '')
        + f', aligned {al}.'
        + (f' {res["dropped"]} record(s) dropped where the plan crossed the existing core.' if res['dropped'] else '')
        + (' ' + ' '.join(n.rstrip('.') + '.' for n in res['notes']) if res['notes'] else '')
        + f' repeat_floor(from_storey, to_storey, source_storey={st}) carries it up.'
        + f' CREDIT: {attr}'
    )


# ── drawing the core the plan already has ────────────────────────────────────
# align="core" snaps a plan onto the stair that is ALREADY drawn, so whoever put
# that stair there decided the core. Guessing a cell by hand is how a tower ends
# up with its stair in the middle of a bedroom. A surveyed floor plan carries its
# own core (plan['core']['stairs'|'lifts'], polygons in plan metres); drawing the
# stair and the lifts FROM it first, through the same transform place_plan will
# use, makes the two agree by construction.
def _slab_storeys(d: Drawing, group: str) -> list:
    return sorted({A.storey_index(d, o) for o in d.select(group) if o['kind'] == 'slab' and not o.get('hidden')})


def t_core_from_plan(
    d: Drawing,
    a,
    plan_id='',
    group='',
    storeys=None,
    stair_kind='u',
    width=1.2,
    lift_w=1.8,
    lift_d=2.0,
    mirror=False,
    rotate_deg=0,
):
    plan = load_plan(plan_id)
    if not plan:
        if not packs():
            return (
                f'refused: no plan packs under {plans_dir()} — there is no plan to read a core from; '
                f'the converters write them to data/architecture/plans/<pack>/'
            )
        return f'refused: no plan "{plan_id}" — search_plans(kind="floor") lists the ids'
    core = plan.get('core') or {}
    stairs = [p for p in (core.get('stairs') or []) if len(p or []) >= 3]
    lifts = [p for p in (core.get('lifts') or []) if len(p or []) >= 3]
    if not (stairs or lifts):
        return (
            f'refused: {plan["id"]} has no core on record — no stair and no lift polygon, so there is '
            f'nothing to draw from it. plan_info("{plan["id"]}") shows what it carries, and '
            f'search_plans(kind="floor") finds floor plans that kept their core'
        )
    if not group:
        return (
            'refused: say which box the core goes in — group="<the name draw_box returned>"; its slab '
            'is the plate the plan is fitted to'
        )
    grp = str(group)
    sts = _slab_storeys(d, grp)
    st0 = sts[0] if sts else 0
    rect, _y, err = _group_plate(d, grp, st0)
    if err:
        return err
    T, err = _plan_transform(plan, rect, mirror, rotate_deg)
    if err:
        return err
    x0, z0, x1, z1 = rect
    had = _core_rects(d, grp, st0, rect, ('stair',))
    if had:
        return (
            f'refused: "{grp}" already has a stair on storey {st0} — a second one drawn from the plan '
            f'would stand beside it, not replace it. place_plan(plan_id, group, align="core") lands the '
            f'plan on the stair that is there'
        )

    n = int(_num(storeys, 0))
    if n <= 0:
        ER = A.EXT_MODULES.get('envelope_rules')
        try:
            n = int(((ER.group_envelope(d, grp) if ER is not None else None) or {}).get('storeys') or 0)
        except Exception:  # noqa: BLE001 — fall back on the slabs
            n = 0
        n = n or len(sts)
    if n <= 0:
        return f'refused: "{grp}" has no storeys — draw_box it first, then draw the core'

    # every centroid resolved BEFORE anything is drawn, so a refusal draws nothing
    want: list = []
    for kind, poly in ([('stair', stairs[0])] if stairs else []) + [('lift', p) for p in lifts]:
        wx, wz = T.pt(*_poly_centre(poly))
        if not (x0 - 0.05 <= wx <= x1 + 0.05 and z0 - 0.05 <= wz <= z1 + 0.05):
            return (
                f'refused: the {kind} of {plan["id"]} maps to {wx:.2f}, {wz:.2f} m, outside the plate of '
                f'"{grp}" ({x0:g}..{x1:g} by {z0:g}..{z1:g} m) — mirror/rotate_deg turn the plan, or pick '
                f'a plan whose core sits inside this bay'
            )
        with A._Scale(d.cell_m):
            want.append((kind, A.cell_of(wx, wz)))

    ent = str((plan.get('entrance') or {}).get('side') or '')
    face = T.side(ent) if ent in SIDES_CW else 'south'

    out = []
    for kind, cell in want:
        if kind == 'stair':
            out.append(
                A.call_tool(
                    d, 'add_stair', {'cell': cell, 'from_storey': 0, 'to_storey': n, 'kind': stair_kind, 'width': width}
                )
            )
        else:
            out.append(
                A.call_tool(
                    d,
                    'add_elevator',
                    {'cell': cell, 'from_storey': 0, 'to_storey': n, 'w': lift_w, 'depth': lift_d, 'door_side': face},
                )
            )
    n_st = sum(1 for k, _c in want if k == 'stair')
    n_lift = len(want) - n_st
    return (
        f'{plan["id"]} puts its core at '
        + ', '.join(f'{k} {c}' for k, c in want)
        + f' on the plate of "{grp}" ({n_st} stair, {n_lift} lift(s), storeys 0..{n}, lift doors '
        f'facing {face}). '
        + ' '.join(t.rstrip('.') + '.' for t in out)
        + f' Now place_plan("{plan["id"]}", group="{grp}", storey=1, align="core") — the plan will snap '
        f'to this core, because it is the core the plan itself asked for.'
    )
