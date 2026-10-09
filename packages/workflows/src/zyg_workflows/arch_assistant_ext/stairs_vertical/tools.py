# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stairs_vertical.tools — the four tool entry points.

Verbatim sections of the original stairs_vertical.py (lines 424-892): t_add_stair,
t_add_elevator, t_add_fire_escape and t_add_escalator.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.stairs_vertical.constants import (
    A,
    Drawing,
    FACADE_GAP,
    HEAD_HOUSE_OBJS,
    MAX_OBJECTS,
    MAX_STOREYS,
    OVERRUN,
    RISE_LIMIT,
    STAIR_KINDS,
    VOID_MARGIN,
    _envelope,
    _mat,
    _num,
    _overhang,
    _probe,
    _rise_for,
    _stack_params,
    _voids,
    cell_centre,
    cell_name,
    math,
    parse_cell,
)
from zyg_workflows.arch_assistant_ext.stairs_vertical.plan import (
    APPROACH_M,
    CORE_STAIR_KINDS,
    _core_span,
    _group_centre,
    _group_floors,
    _head_house,
    _outward,
    _spacing_note,
    _stack_plan,
    approach_bboxes,
    plan_clash,
    plan_overlap,
    y_overlap,
)


def t_add_stair(
    d: Drawing, a, cell, from_storey=0, to_storey=1, kind='straight', direction_deg=0.0, width=1.0, material='', name=''
):
    c, r = parse_cell(cell)  # a bad cell raises ValueError -> 'refused: ...'
    cx, cz = cell_centre(c, r)
    here = cell_name(c, r)
    k = str(kind or 'straight').strip().lower()
    if k not in STAIR_KINDS:
        return 'refused: kind must be ' + ', '.join(STAIR_KINDS)
    s0, s1 = int(_num(from_storey, 0)), int(_num(to_storey, 1))
    if s1 <= s0:
        return f'refused: to_storey ({s1}) must be above from_storey ({s0}) — a stair has to climb'
    if s1 - s0 > MAX_STOREYS:
        return (
            f'refused: one call draws at most {MAX_STOREYS} storeys of stair — '
            f'call add_stair again for the storeys above {s0 + MAX_STOREYS}'
        )
    w = _num(width, 1.0)
    if w < 0.5 or w > 4:
        return 'refused: width must be between 0.5 and 4 m'
    if k == 'straight' and s1 - s0 >= 3:
        return f'refused: a straight flight over {s1 - s0} storeys has no landing — kind="u"'

    # ── where it is allowed to stand ─────────────────────────────────────────
    E, V = _envelope(), _voids()
    group = E.group_at(d, cx, cz) if E is not None else None
    if group is None:
        return f'refused: {here} is not inside a building — draw the shell first (draw_box) or pick a cell inside it'
    env = E.group_envelope(d, group)
    storeys = int(env.get('storeys') or 0)
    if s0 >= storeys:
        return (
            f'refused: "{group}" is {storeys} storeys, so from_storey {s0} is above the top floor — '
            f'from_storey must be {storeys - 1} or less'
        )
    if s1 > storeys:
        return (
            f'refused: "{group}" is {storeys} storeys, so to_storey {s1} is above its roof deck — '
            f'to_storey={storeys} reaches the deck, to_storey={storeys - 1} the top floor'
        )

    H = d.storey_h
    steps, rise = _rise_for(H)
    if rise > RISE_LIMIT:
        return f'refused: {steps} steps over {H:g} m would need a {rise:.3f} m rise, past the {RISE_LIMIT} m limit'
    rec_kind, p = _stack_params(k, steps, rise, w)

    # ── the top flight lands on the DECK (2026-09-11) ────────────────────────
    # 20 x 2.7 = 54.0 m stopped 0.3 m under a 54.3 m deck (roof y + t), so
    # roof_access / continuity could never pass from the tools alone. The top
    # record climbs deck - floor; it is the longest flight, so it sets the plan.
    base = _num(env.get('y0'), 0.0)
    deck_y = A.surface_top(d, cx, cz)  # read BEFORE the roof is cut open
    p_top = dict(p)
    if s1 >= storeys:
        last_h = deck_y - (base + (s1 - 1) * H)
        if last_h > H + 0.02:
            ln, lr = _rise_for(last_h)
            if lr <= RISE_LIMIT:
                p_top['steps'], p_top['rise'] = ln, round(lr, 9)
    p_big = p_top if _num(p_top.get('steps'), 0) > _num(p.get('steps'), 0) else p

    # ── which way it may be turned ───────────────────────────────────────────
    want = _num(direction_deg, 0.0)
    ry = math.radians(want)
    bb = E.bbox_of(_probe(rec_kind, p_big, cx, cz, ry))
    over, side = _overhang(env, bb)
    if over > 0:
        fits = [
            deg
            for deg in (0, 90, 180, 270)
            if _overhang(env, E.bbox_of(_probe(rec_kind, p_big, cx, cz, math.radians(deg))))[0] <= 0
        ]
        plan = f'{bb[2] - bb[0]:.2f} x {bb[3] - bb[1]:.2f} m'
        if fits:
            return (
                f'refused: a {plan} {k} stair at {here} turned {want:g}° crosses the {side} facade of '
                f'"{group}" by {over:.2f} m — direction_deg={fits[0]} fits'
            )
        return (
            f'refused: a {plan} {k} stair does not fit anywhere at {here}: it crosses the {side} facade '
            f'of "{group}" by {over:.2f} m at every direction — move it toward the middle of the plan '
            f'or make it narrower (width)'
        )

    # ── and what is already standing there (2026-09-12) ──────────────────────
    # A stair and a lift shaft are two cores: neither may be inside the other's
    # plan, and neither may stand on the floor the other's users step onto.
    probe = _probe(rec_kind, p_big, cx, cz, ry)
    zones = approach_bboxes(probe)
    L, W = E._plan_size(probe)
    plan = f'{bb[2] - bb[0]:.2f} x {bb[3] - bb[1]:.2f} m'
    sy0, sy1 = base + s0 * H, base + s1 * H
    for o in d.objs:
        if o.get('kind') != 'elevator_shaft' or o.get('hidden'):
            continue
        oy0, oy1 = _core_span(o)
        if not y_overlap(sy0, sy1, oy0, oy1):
            continue
        obb = E.bbox_of(o)
        note = _spacing_note(k, L, W, cx, cz, obb[2] - obb[0])
        there = A.cell_of(_num(o.get('x'), 0.0), _num(o.get('z'), 0.0))
        if plan_clash(bb, obb):
            ox, oz = plan_overlap(bb, obb)
            return (
                f'refused: a {plan} {k} stair at {here} overlaps lift shaft {o["id"]} at {there} by '
                f'{ox:.2f} x {oz:.2f} m' + note
            )
        if any(plan_clash(zb, obb) for zb in zones):
            return (
                f'refused: lift shaft {o["id"]} at {there} stands in the {APPROACH_M:g} m of floor a '
                f'person needs at the foot of a {plan} {k} stair at {here} (its west/-X side)' + note
            )

    n = s1 - s0
    if len(d.objs) + n + HEAD_HOUSE_OBJS > MAX_OBJECTS:
        return f'refused: that is {n} stair records and the drawing may hold {MAX_OBJECTS} in total'

    # ── one record per storey, in one stairwell ──────────────────────────────
    grp = name or f'stair {here}'
    recs = []
    for s in range(s0, s1):
        pp = dict(p_top) if (s1 >= storeys and s == s1 - 1) else dict(p)
        if base:
            pp['base'] = round(base, 4)
        recs.append(
            d.new(rec_kind, pp, cx, cz, base + s * H, ry, _mat(material), name=f'{k} stair st{s}-{s + 1}', grp=grp)
        )

    # ── the hole it needs in every floor it passes (the longest flight rules) ─
    bbs = [E.bbox_of(recs[0]), E.bbox_of(recs[-1])]
    ubb = [min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)]
    cut_bb = [b + (-VOID_MARGIN if i < 2 else VOID_MARGIN) for i, b in enumerate(ubb)]
    cut, refused = [], []
    if V is not None:
        for s in range(s0 + 1, s1 + 1):
            ids, note = V.cut_slab_void(d, group, s, cut_bb[0], cut_bb[1], cut_bb[2], cut_bb[3], 'stair')
            (cut if ids else refused).append(s)

    # ── the head house, when the stair arrives on the deck ───────────────────
    head = ''
    if s1 >= storeys:
        hgrp, hids, door_side = _head_house(d, E, group, ubb, deck_y, env)
        head = f'; head house {hids[0]}..{hids[-1]} on the deck at {deck_y:g} m (door facing {door_side})'
        if p_top.get('steps') != steps:
            head = (
                f'; top flight {p_top["steps"]} steps of {p_top["rise"]:.4f} m rise = '
                f'{deck_y - (base + (s1 - 1) * H):g} m, landing on the deck'
            ) + head
    d.selected = [o['id'] for o in recs]
    return (
        f'{k} stair: {n} record(s) {recs[0]["id"]}..{recs[-1]["id"]}, one per storey st{s0}..{s1 - 1}, '
        f'each {steps} steps of {rise:.4f} m rise = {H:g} m'
        + (f' in 2 flights of {steps // 2} and {steps - steps // 2} round a landing' if k == 'u' else '')
        + f', {w:g} m wide, rails both flights; plan {bb[2] - bb[0]:.2f} x {bb[3] - bb[1]:.2f} m at {here} '
        f'in "{group}"'
        + (f', turned {want:g}°' if want else '')
        + (f'; floor openings cut in {len(cut)} floor(s) (storeys {cut[0]}..{cut[-1]})' if cut else '')
        + (f'; {len(refused)} storey(s) had no floor to cut ({refused})' if refused else '')
        + head
    )


def t_add_elevator(
    d: Drawing, a, cell, from_storey=0, to_storey=3, w=1.8, depth=2.0, car=True, material='', name='', door_side='south'
):
    c, r = parse_cell(cell)  # a bad cell raises ValueError -> 'refused: ...'
    cx, cz = cell_centre(c, r)
    here = cell_name(c, r)
    s0, s1 = int(_num(from_storey, 0)), int(_num(to_storey, 3))
    if s1 < s0:
        return f'refused: to_storey ({s1}) is below from_storey ({s0})'
    W = _num(w, 1.8)
    D = _num(depth, 2.0)
    if not (0.8 <= W <= 6) or not (0.8 <= D <= 6):
        return 'refused: a lift shaft must be between 0.8 and 6 m in each direction'
    face = A.SIDE_WORDS.get(str(door_side or 'south').strip().lower())
    if not face:
        return (
            'refused: door_side must be north, south, east or west — the shaft face the doors open onto '
            '(north is -Z, the small rows)'
        )

    # ── where it is allowed to stand, and how high it has to reach ───────────
    E, V = _envelope(), _voids()
    group = E.group_at(d, cx, cz) if E is not None else None
    if group is None:
        return (
            f'refused: {here} is not inside a building — a lift shaft is part of one: draw the shell first '
            f'(draw_box) or pick a cell inside it'
        )
    env = E.group_envelope(d, group)
    storeys = int(env.get('storeys') or 0)
    if s0 >= storeys:
        return (
            f'refused: "{group}" is {storeys} storeys, so from_storey {s0} is above the top floor — '
            f'from_storey must be {storeys - 1} or less'
        )
    if s1 > storeys:
        return (
            f'refused: "{group}" is {storeys} storeys, so to_storey {s1} is above its roof deck — '
            f'to_storey={storeys} serves the deck, to_storey={storeys - 1} the top floor'
        )
    probe_p = {'w': round(W, 3), 'd': round(D, 3), 'h': 1.0, 't': 0.2}
    bb = E.bbox_of(_probe('elevator_shaft', probe_p, cx, cz, 0.0))
    over, oside = _overhang(env, bb)
    if over > 0:
        return (
            f'refused: a {W:g} x {D:g} m lift shaft at {here} crosses the {oside} facade of "{group}" by '
            f'{over:.2f} m — move it toward the middle of the plan, or make it narrower (w, depth)'
        )
    H = d.storey_h
    base = _num(env.get('y0'), 0.0)
    y = base + s0 * H
    serves_deck = s1 >= storeys
    # the top the CAR must reach: the deck's own surface when it serves the deck,
    # else the floor above the top served storey. The overrun (the motor room)
    # sits on top of that, which is why the shaft always breaks the roof.
    top = base + (s1 + 1) * H
    if serves_deck:
        top = _num(env.get('top_deck'), top)
    shaft_h = round(top - y + OVERRUN, 4)

    # ── what is already standing there (2026-09-12) ──────────────────────────
    # The same rule as add_stair, read from the lift's side: a shaft may not be
    # inside a stair's plan, nor on the floor at its foot, nor inside another
    # shaft. Two STAIRS at one cell are allowed — a stair and a spiral may share
    # a well — so only shaft-vs-anything is measured here.
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden') or k not in CORE_STAIR_KINDS + ('elevator_shaft',):
            continue
        oy0, oy1 = _core_span(o)
        if not y_overlap(y, y + shaft_h, oy0, oy1):
            continue
        obb = E.bbox_of(o)
        there = A.cell_of(_num(o.get('x'), 0.0), _num(o.get('z'), 0.0))
        if k == 'elevator_shaft':
            if plan_clash(bb, obb):
                ox, oz = plan_overlap(bb, obb)
                return (
                    f'refused: a {W:g} x {D:g} m lift shaft at {here} overlaps lift shaft {o["id"]} at '
                    f'{there} by {ox:.2f} x {oz:.2f} m — two shafts are two cores, not one'
                )
            continue
        SL, SW = _stack_plan(d, o)
        word = k.replace('stair_', '')
        note = _spacing_note(word, SL, SW, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), W)
        if plan_clash(bb, obb):
            ox, oz = plan_overlap(bb, obb)
            return (
                f'refused: a {W:g} x {D:g} m lift shaft at {here} overlaps {o["id"]} ({word} stair at '
                f'{there}, plan x {obb[0]:.2f}..{obb[2]:.2f}) by {ox:.2f} x {oz:.2f} m' + note
            )
        if any(plan_clash(bb, zb) for zb in approach_bboxes(o)):
            return (
                f'refused: a {W:g} x {D:g} m lift shaft at {here} stands in the {APPROACH_M:g} m of floor '
                f'at the foot of {o["id"]} ({word} stair at {there}) — nothing to step onto' + note
            )

    need = 2 if car else 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    doors = list(range(s0, s1 + 1))
    grp = name or f'lift {here}'
    shaft = d.new(
        'elevator_shaft',
        {
            'w': round(W, 3),
            'd': round(D, 3),
            'h': shaft_h,
            't': 0.2,
            'doors': doors,
            'door_side': face,
            'overrun': OVERRUN,
            'sh': round(H, 4),
        },
        cx,
        cz,
        y,
        0.0,
        _mat(material),
        name=f'lift shaft st{s0}-{s1}',
        grp=grp,
    )
    ids = shaft['id']
    if car:
        car_rec = d.new(
            'elevator_car',
            {'w': round(max(0.6, W - 0.4), 3), 'd': round(max(0.6, D - 0.4), 3), 'h': 2.2, 'door': 1},
            cx,
            cz,
            y,
            0.0,
            _mat(material, 'mat_steel'),
            name=f'lift car st{s0}',
            grp=grp,
        )
        ids += ' + car ' + car_rec['id']

    # ── the hole it needs in every floor its span crosses ────────────────────
    cut_bb = [b + (-VOID_MARGIN if i < 2 else VOID_MARGIN) for i, b in enumerate(E.bbox_of(shaft))]
    floors = _group_floors(d, group, H)
    want = sorted(s for s, (fy, _k) in floors.items() if s > s0 and y + 0.05 < fy < y + shaft_h - 0.05)
    slabs_cut, roofs_cut, refused = [], [], []
    if V is not None:
        for s in want:
            got, _note = V.cut_slab_void(d, group, s, cut_bb[0], cut_bb[1], cut_bb[2], cut_bb[3], 'lift')
            if not got:
                refused.append(s)
            elif floors[s][1] == 'roof_flat':
                roofs_cut.append(s)
            else:
                slabs_cut.append(s)
    d.selected = [shaft['id']]
    return (
        f'lift shaft {ids} at {here}: {W:g} x {D:g} m, storeys {s0}..{s1}'
        + (' (deck)' if serves_deck else '')
        + f', {len(doors)} doors on the {face} face, overrun {OVERRUN:g} m above the '
        + ('deck' if serves_deck else 'top served floor')
        + f' ({shaft_h:g} m of shaft from {y:g} to {y + shaft_h:g} m)'
        + (f'; floor openings cut in {len(slabs_cut)} slab(s)' if slabs_cut else '; no slab to cut')
        + (' + the roof' if roofs_cut else '')
        + (f'; {len(refused)} storey(s) had no floor to cut ({refused})' if refused else '')
        + ('' if car else ', no car')
    )


def t_add_fire_escape(
    d: Drawing, a, group='', side='', storeys=None, cell='', direction_deg=None, width=1.2, material='', name=''
):
    """A fire escape is bolted to a FACADE, so it is addressed by (group, side) —
    job 71ac02b0 asked for one 'on the north side' and got a cell inside the plan
    (FH91), a steel stair in the middle of the offices. The cell form still works
    for a free-standing escape on open ground, but a cell inside a building is now
    refused with the call that does what was meant."""
    n_in = None if storeys is None else int(_num(storeys, 3))
    w = _num(width, 1.2)
    if w < 0.6 or w > 3:
        return 'refused: width must be between 0.6 and 3 m'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    E = _envelope()

    if group:
        face = A.SIDE_WORDS.get(str(side or '').strip().lower())
        if not face:
            return (
                f'refused: side must be north, south, east or west — the facade of "{group}" the escape hangs '
                f'on (north is -Z, the small rows): add_fire_escape(group="{group}", side="north")'
            )
        env = E.group_envelope(d, group) if E is not None else None
        # a glazed ground storey is a curtain_wall record: it is still the facade
        wall, err = A.wall_on_side(d, group, face, 0, ('wall', 'partition', 'curtain_wall'))
        if err:
            return err
        n = n_in if n_in is not None else (int((env or {}).get('storeys') or 0) or 1)
        if n < 1 or n > 40:
            return 'refused: a fire escape covers between 1 and 40 storeys'
        # OUTSIDE the wall line: the wall's midpoint pushed out along its own
        # outward normal by half the escape's plan depth plus a 50 mm gap.
        gcx, gcz = _group_centre(d, E, group, env)
        ry, nx, nz = _outward(wall, gcx, gcz)
        off = w / 2 + FACADE_GAP + _num(wall['p'].get('t'), d.wall_t) / 2
        ox, oz = wall['x'] + nx * off, wall['z'] + nz * off
        y = _num((env or {}).get('y0'), 0.0)
        o = d.new(
            'fire_stair_exterior',
            {'storeys': n, 'h': d.storey_h, 'w': round(w, 3), 'run': 0.28, 'rise': 0.18},
            ox,
            oz,
            y,
            ry,
            _mat(material, 'mat_steel'),
            name=name or f'fire escape {face}',
            grp=name or f'fire escape {group} {face}',
        )
        d.selected = [o['id']]
        return (
            f'fire escape {o["id"]} on the {face} facade of "{group}" (wall {wall["id"]}): {n} storeys of '
            f'{d.storey_h:g} m ({n * d.storey_h:g} m), {w:g} m wide, hung {off:.2f} m outside the wall line, '
            f'flights running along the facade'
        )

    if not cell:
        return (
            'refused: say which facade it hangs on — add_fire_escape(group="<the name draw_box returned>", '
            'side="north")'
        )
    c, r = parse_cell(cell)  # a bad cell raises ValueError -> 'refused: ...'
    cx, cz = cell_centre(c, r)
    here = cell_name(c, r)
    inside = E.group_at(d, cx, cz) if E is not None else None
    if inside:
        return (
            f'refused: {here} is inside "{inside}" — a fire escape hangs OUTSIDE the facade: '
            f'add_fire_escape(group="{inside}", side="north")'
        )
    n = n_in if n_in is not None else 3
    if n < 1 or n > 40:
        return 'refused: a fire escape covers between 1 and 40 storeys'
    o = d.new(
        'fire_stair_exterior',
        {'storeys': n, 'h': d.storey_h, 'w': round(w, 3), 'run': 0.28, 'rise': 0.18},
        cx,
        cz,
        0.0,
        math.radians(_num(direction_deg, 0.0)),
        _mat(material, 'mat_steel'),
        name=name or f'fire escape {here}',
        grp=name or f'fire escape {here}',
    )
    return (
        f'fire escape {o["id"]} at {here}: {n} storeys of {d.storey_h:g} m '
        f'({n * d.storey_h:g} m), {w:g} m wide, facing {_num(direction_deg, 0):g}° — free-standing, '
        f'not attached to a facade'
    )


def t_add_escalator(
    d: Drawing, a, cell, from_storey=0, to_storey=1, direction_deg=0.0, width=1.0, angle=30.0, material='', name=''
):
    c, r = parse_cell(cell)  # a bad cell raises ValueError -> 'refused: ...'
    cx, cz = cell_centre(c, r)
    here = cell_name(c, r)
    s0, s1 = int(_num(from_storey, 0)), int(_num(to_storey, 1))
    if s1 <= s0:
        return f'refused: to_storey ({s1}) must be above from_storey ({s0}) — an escalator has to climb'
    w = _num(width, 1.0)
    if w < 0.6 or w > 2.5:
        return 'refused: width must be between 0.6 and 2.5 m'
    ang = _num(angle, 30.0)
    if ang < 20 or ang > 40:
        return 'refused: an escalator pitch is between 20 and 40 degrees (30 is standard)'
    n = s1 - s0
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} objects past the {MAX_OBJECTS} ceiling'
    # An escalator climbs ONE storey per flight: a single record spanning six
    # storeys would be a 47 m ramp through every slab. A multi-storey run is a
    # stack — flight per storey, each reversed so the pair scissors back on
    # itself and the bank keeps one footprint instead of marching across the plan.
    H = d.storey_h
    rise = H
    run = rise / math.tan(math.radians(ang))
    base = math.radians(_num(direction_deg, 0.0))
    grp = name or f'escalator {here}'
    ids = []
    for i in range(n):
        o = d.new(
            'escalator',
            {'rise': round(rise, 4), 'w': round(w, 3), 'angle': round(ang, 2), 'rail_h': 0.9},
            cx,
            cz,
            (s0 + i) * H,
            base + (math.pi if i % 2 else 0.0),
            _mat(material, 'mat_steel'),
            name=f'escalator st{s0 + i}-{s0 + i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
    d.selected = [ids[0]]
    return (
        f'escalator {ids[0] if n == 1 else ids[0] + ".." + ids[-1]} at {here}: storey {s0} to {s1}, '
        f'{n} flight(s) of one storey ({rise:g} m at {ang:g}° = {run:.2f} m of floor each'
        + (', reversed storey by storey so the bank stays over one footprint' if n > 1 else '')
        + f'), {w:g} m wide'
    )
