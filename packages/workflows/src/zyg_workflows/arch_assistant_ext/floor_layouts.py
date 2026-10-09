# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_layouts — a WHOLE floor in one call, and the typical floors in a second
(2026-09-08).

Why: the checklist can tell the model to build corridors, apartments and offices
all it likes — inside a 28-turn budget it cannot place them. A 20-storey office
laid out room by room is thousands of tool calls; the job dies at
"stopped after 28 steps without finishing" with an empty shell.

So the layout is generated, not placed. `layout_floor` cuts one double-loaded
floor — corridor down the long axis, units either side, a door from every unit
into the corridor, a `zone` record per unit so egress_check / occupancy /
fire_compartments can read the plan — in ONE call. `repeat_floor` carries that
floor up the typical storeys in a second call, which is what makes a tower's
interior affordable at all.

The rules that decide the geometry are the object specs (spec("corridor"),
spec("apartment"), spec("office_floor")), and they are enforced HERE, at the
tool boundary — a corridor under 1.2 m clear or a unit deeper than its daylight
allows is refused with the number to use, not warned about afterwards. That is
the lesson of plant_tree_line: a rule the model can route around is not a rule.

No new kinds: partitions, doors and zones, exactly as interior_rooms places them.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    KINDS as BASE_KINDS,
    block_bounds,
    cell_name,
    parse_cell,
    _num,
)

KINDS: dict = {}
OPENINGS: list = []

EXT_KEY = 'floor_layouts'

# per use: corridor width, unit width along the corridor, zone use, unit label
USE_RULES = {
    'residential': {'cw': 1.5, 'uw': 7.0, 'zone': 'living', 'label': 'Apartment', 'max_depth': 14.0},
    'mixed': {'cw': 1.5, 'uw': 7.0, 'zone': 'living', 'label': 'Unit', 'max_depth': 14.0},
    'house': {'cw': 1.2, 'uw': 4.0, 'zone': 'living', 'label': 'Room', 'max_depth': 8.0},
    'office': {'cw': 1.5, 'uw': 8.0, 'zone': 'office', 'label': 'Office', 'max_depth': 12.0},
    'hotel': {'cw': 1.8, 'uw': 4.0, 'zone': 'bedroom', 'label': 'Room', 'max_depth': 9.0},
    'school': {'cw': 1.8, 'uw': 8.0, 'zone': 'classroom', 'label': 'Classroom', 'max_depth': 9.0},
    'civic': {'cw': 1.8, 'uw': 8.0, 'zone': 'office', 'label': 'Room', 'max_depth': 12.0},
    'retail': {'cw': 2.4, 'uw': 10.0, 'zone': 'retail', 'label': 'Shop', 'max_depth': 20.0},
    'warehouse': {'cw': 3.0, 'uw': 12.0, 'zone': 'storage', 'label': 'Bay', 'max_depth': 30.0},
}
USES = tuple(sorted(USE_RULES))
CORRIDOR_MIN = 1.2  # spec("corridor"): two people pass, a wheelchair turns
UNIT_MIN = 3.0  # anything shallower is a cupboard, not a room


def _mat(m, default='mat_plaster'):
    return m if m in MATERIALS else default


def _partition(d, x0, z0, x1, z1, y, h, t, mat, name, grp):
    L = math.hypot(x1 - x0, z1 - z0)
    ry = math.atan2(-(z1 - z0), (x1 - x0))
    return d.new(
        'partition', {'len': round(L, 4), 'h': h, 't': t}, (x0 + x1) / 2, (z0 + z1) / 2, y, ry, mat, name=name, grp=grp
    )


def _door(d, w, x, z, width, name, grp):
    p = dict(BASE_KINDS.get('door') or {'w': 0.9, 'h': 2.1})
    p['w'] = _num(width, 0.9)
    p['h'] = min(2.1, _num((w['p'] or {}).get('h'), 2.5) - 0.05)
    o = d.new('door', p, x, z, w['y'], w['ry'], 'mat_timber', name=name, grp=grp)
    o['meta']['host'] = w['id']  # delete the wall, the door goes with it
    return o


def _zone(d, x0, z0, x1, z1, y, nm, use, grp):
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    pts = [
        [round(x0 - cx, 4), round(z0 - cz, 4)],
        [round(x1 - cx, 4), round(z0 - cz, 4)],
        [round(x1 - cx, 4), round(z1 - cz, 4)],
        [round(x0 - cx, 4), round(z1 - cz, 4)],
    ]
    return d.new('zone', {'pts': pts, 'name': nm, 'use': use, 'h': 0.05}, cx, cz, y, 0.0, None, name=nm, grp=grp)


def _rects_overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


CORE_TOL = 0.15  # m of plan overlap before a unit really crosses a core
CORE_CLEAR = 0.30  # m between a stair and the wall that encloses it — outside the
# stair's own slab void (0.19 m), inside the 0.4 m
# circulation_rules.ENCLOSE_M calls "enclosed"


def _core_hit(rect, cores, tol=CORE_TOL):
    """(record, core_rect, ox, oz) of the first core the rectangle crosses by more
    than `tol` in BOTH plan axes, else None."""
    for o, cr in cores:
        ox = min(rect[2], cr[2]) - max(rect[0], cr[0])
        oz = min(rect[3], cr[3]) - max(rect[1], cr[1])
        if ox > tol and oz > tol:
            return o, cr, ox, oz
    return None


def _seg_hits_core(x0, z0, x1, z1, t, cores) -> bool:
    """A partition segment (thin rect, thickness `t`) crossing a core's plan.
    A wall is thinner than CORE_TOL, so the thin axis is measured against the
    wall's own thickness — otherwise no partition could ever be found crossing."""
    rect = (min(x0, x1) - t / 2, min(z0, z1) - t / 2, max(x0, x1) + t / 2, max(z0, z1) + t / 2)
    for _o, cr in cores:
        ox = min(rect[2], cr[2]) - max(rect[0], cr[0])
        oz = min(rect[3], cr[3]) - max(rect[1], cr[1])
        if ox > min(CORE_TOL, 0.8 * (rect[2] - rect[0])) and oz > min(CORE_TOL, 0.8 * (rect[3] - rect[1])):
            return True
    return False


def t_layout_floor(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    use='office',
    storey=0,
    corridor_w=None,
    unit_w=None,
    core_from=None,
    core_to=None,
    wall_h=None,
    wall_t=0.1,
    material='',
    doors=True,
    zones=True,
    name='',
):
    u = str(use or 'office').strip().lower()
    if u not in USE_RULES:
        return f'refused: use must be one of {", ".join(USES)}'
    R = USE_RULES[u]
    try:
        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    except ValueError as e:
        return f'refused: {e}'
    W, D = xmax - xmin, zmax - zmin
    st = int(_num(storey, 0))
    y = st * d.storey_h
    H = _num(
        wall_h, max(0.5, d.storey_h)
    )  # to the slab underside (2026-09-16: was storey_h - 0.2, an open strip on every typical floor)
    T = _num(wall_t, 0.1) or 0.1
    mat = _mat(material)
    cw = _num(corridor_w, R['cw'])
    if cw < CORRIDOR_MIN:
        return (
            f'refused: a {cw:g} m corridor is under the {CORRIDOR_MIN:g} m clear minimum — two people cannot '
            f'pass and a wheelchair cannot turn. Use corridor_w={R["cw"]:g} (spec("corridor"))'
        )
    if cw > 6:
        return 'refused: over 6 m that is a hall, not a corridor'

    along_x = W >= D  # the corridor runs down the LONGER axis
    span = D if along_x else W  # the dimension the corridor and both unit bands share
    run = W if along_x else D  # the length of the corridor
    depth = (span - cw) / 2.0
    if depth < UNIT_MIN:
        need = round(2 * UNIT_MIN + cw, 1)
        return (
            f'refused: a {cw:g} m corridor across a {span:g} m plate leaves {depth:.1f} m of unit depth — '
            f'under the {UNIT_MIN:g} m minimum. The plate has to be at least {need:g} m across, or drop the '
            f'corridor and use add_room for a single-aspect floor'
        )
    uw = _num(unit_w, R['uw'])
    if uw < 2.0:
        return 'refused: unit_w under 2 m is not a room'
    n = max(1, int(round(run / uw)))
    uw = run / n  # even units, exactly filling the run

    core = None
    if core_from and core_to:
        try:
            cx0, cz0, cx1, cz1 = block_bounds(core_from, core_to)
        except ValueError as e:
            return f'refused: core block — {e}'
        core = (cx0, cz0, cx1, cz1)

    # 2026-09-16: the cores that ARE on this storey, as keep-out rectangles.
    # Before today, omitting core_from/core_to meant "keep nothing out" and the
    # layout ran units and party walls straight through the stair well and the
    # lift shaft. Omitted now means "keep the real cores out", and an explicit
    # core block that still leaves one crossed is refused rather than drawn.
    CL = A.EXT_MODULES.get('clash_rules')
    cores = CL.cores_on_storey(d, st) if CL is not None else []
    auto_core = core is None and bool(cores)

    need = 2 + n * 2 * (1 + (1 if doors else 0) + (1 if zones else 0)) + 2
    if len(d.objs) + need > MAX_OBJECTS:
        return (
            f'refused: this floor is about {need} records and the drawing is at '
            f'{len(d.objs)} of the {MAX_OBJECTS} ceiling'
        )

    plate = str(name or f'{u} floor').strip()
    cgrp = f'corridor st{st}'
    ids = []
    # the two corridor walls
    if along_x:
        cz = (zmin + zmax) / 2
        ids.append(
            _partition(d, xmin, cz - cw / 2, xmax, cz - cw / 2, y, H, T, mat, f'corridor wall north st{st}', cgrp)['id']
        )
        ids.append(
            _partition(d, xmin, cz + cw / 2, xmax, cz + cw / 2, y, H, T, mat, f'corridor wall south st{st}', cgrp)['id']
        )
        bands = [('north', zmin, cz - cw / 2), ('south', cz + cw / 2, zmax)]
    else:
        cx = (xmin + xmax) / 2
        ids.append(
            _partition(d, cx - cw / 2, zmin, cx - cw / 2, zmax, y, H, T, mat, f'corridor wall west st{st}', cgrp)['id']
        )
        ids.append(
            _partition(d, cx + cw / 2, zmin, cx + cw / 2, zmax, y, H, T, mat, f'corridor wall east st{st}', cgrp)['id']
        )
        bands = [('west', xmin, cx - cw / 2), ('east', cx + cw / 2, xmax)]

    made, skipped, core_skipped, k = 0, 0, 0, 0
    short: list = []  # cores the operator's own core block does not cover
    for side, b0, b1 in bands:
        for i in range(n):
            a0 = (xmin if along_x else zmin) + i * uw
            a1 = a0 + uw
            rect = (a0, b0, a1, b1) if along_x else (b0, a0, b1, a1)
            if core and _rects_overlap(rect, core):
                skipped += 1
                continue
            hit = _core_hit(rect, cores)
            if hit:
                # A unit is never drawn over a stair or a lift. The operator's own
                # core block may be too small to cover them (job 71ac02b0 gave
                # FF95..FJ97 for a shaft that reaches x 10.4) — leaving the unit out
                # and saying so beats refusing the whole plate or walling the core in.
                if core is not None:
                    short.append(hit)
                core_skipped += 1
                continue
            k += 1
            label = f'{R["label"]} {st}.{k:02d}'
            grp = f'{plate} st{st} {label}'
            # party wall on the low side of every unit but the first of the band
            if i > 0:
                seg = (a0, b0, a0, b1) if along_x else (b0, a0, b1, a0)
                if _seg_hits_core(*seg, T, cores):
                    core_skipped += 1  # its line runs through the core
                else:
                    ids.append(_partition(d, *seg, y, H, T, mat, f'party wall {label}', grp)['id'])
            # the door from the corridor
            if doors:
                if along_x:
                    wall = d.find(ids[0] if side == 'north' else ids[1])
                    dx, dz = a0 + uw / 2, (b1 if side == 'north' else b0)
                else:
                    wall = d.find(ids[0] if side == 'west' else ids[1])
                    dx, dz = (b1 if side == 'west' else b0), a0 + uw / 2
                ids.append(_door(d, wall, dx, dz, 0.9, f'door {label}', grp)['id'])
            if zones:
                ids.append(_zone(d, rect[0], rect[1], rect[2], rect[3], y, label, R['zone'], grp)['id'])
            made += 1

    # 2026-09-16: the corridor is a TUBE unless something opens it to the core.
    # Before today both corridor walls ran the full plate with doors into the units
    # only, so on every laid-out storey walk_rules found no path at all from the
    # stair to any unit door ("corridor wall north st<N> stands in the way") and
    # repeat_floor carried that up the whole tower. One door per core, cut through
    # the corridor wall on the core's own side, is what the finding asks for.
    core_doors = 0
    for _o, cr in cores or []:
        wall = d.find(
            ids[0] if ((cr[1] + cr[3]) / 2 if along_x else (cr[0] + cr[2]) / 2) < (cz if along_x else cx) else ids[1]
        )
        if wall is None:
            continue
        if along_x:
            dx = min(max((cr[0] + cr[2]) / 2, xmin + 0.8), xmax - 0.8)
            dz = wall['z']
        else:
            dx = wall['x']
            dz = min(max((cr[1] + cr[3]) / 2, zmin + 0.8), zmax - 0.8)
        near = [
            q
            for q in d.objs
            if q.get('kind') == 'door'
            and (q.get('meta') or {}).get('host') == wall['id']
            and math.hypot(q['x'] - dx, q['z'] - dz) < 1.6
        ]
        if near:
            continue  # a unit door already opens the wall there
        ids.append(_door(d, wall, dx, dz, 1.1, f'core door st{st}', cgrp)['id'])
        core_doors += 1

    # 2026-09-16: a stair well on a fitted-out floor is a ROOM, not a sculpture.
    # circulation_rules.check_enclosure wants a wall within 0.4 m of each of the
    # stair's four plan sides, and on a luxury tower that is an error, not a note.
    # add_core places the flight off the cell grid (14.92 .. 18.08 m here), so no
    # cell-addressed add_room can ever get a wall inside 0.4 m of it — the tool
    # that keeps the core out of the plate is the one that can enclose it.
    # The door goes in the side facing the corridor, so the walk still gets in.
    SV = A.EXT_MODULES.get('stairs_vertical')
    enclosed = 0
    for co, cr in cores or []:
        if str(co.get('kind') or '') not in CL.STAIR_KINDS:
            continue  # a shaft is its own enclosure
        ex0, ez0, ex1, ez1 = cr[0] - CORE_CLEAR, cr[1] - CORE_CLEAR, cr[2] + CORE_CLEAR, cr[3] + CORE_CLEAR
        segs = [
            ('west', (ex0, ez0, ex0, ez1)),
            ('east', (ex1, ez0, ex1, ez1)),
            ('north', (ex0, ez0, ex1, ez0)),
            ('south', (ex0, ez1, ex1, ez1)),
        ]
        # THREE sides, not four: the way in is the stair's own approach, the 1.2 m
        # of floor at its foot that circ_stair_approach keeps clear. Walling that
        # side and cutting a door through it trades one finding for another, and
        # check_enclosure only speaks at TWO open sides — three walls is enough.
        ccx, ccz = (cr[0] + cr[2]) / 2, (cr[1] + cr[3]) / 2
        appr = SV.approach_bboxes(co) if SV is not None else []
        if appr:
            ax = sum((r[0] + r[2]) / 2 for r in appr) / len(appr)
            az = sum((r[1] + r[3]) / 2 for r in appr) / len(appr)
            gap = (
                ('west' if ax < ccx else 'east')
                if abs(ax - ccx) >= abs(az - ccz)
                else ('north' if az < ccz else 'south')
            )
        else:
            gap = ('north' if ccz > cz else 'south') if along_x else ('west' if ccx > cx else 'east')
        egrp = f'core enclosure st{st}'
        for side, seg in segs:
            if side == gap:
                continue
            ids.append(
                _partition(d, *seg, y, H, T, mat, f'{co.get("kind", "stair")} enclosure {side} st{st}', egrp)['id']
            )
        enclosed += 1

    # 2026-09-16: DECLARE the corridor. Every unit got a zone record and the one
    # space between them got none, so floor_rules had to derive the corridor from
    # the free floor left over — and once the core doors above opened the corridor
    # to the core, "the free component the unit doors open onto" swallowed the
    # whole core band and measured its narrowest nook (the 1.08 m service gap the
    # core's own setback leaves behind the stair) as the corridor's clear width.
    # The corridor is 1.8 m wide and the plan should say so.
    if zones:
        if along_x:
            ids.append(_zone(d, xmin, cz - cw / 2, xmax, cz + cw / 2, y, f'corridor st{st}', 'corridor', cgrp)['id'])
        else:
            ids.append(_zone(d, cx - cw / 2, zmin, cx + cw / 2, zmax, y, f'corridor st{st}', 'corridor', cgrp)['id'])

    store = d.ext.get(EXT_KEY)
    if not isinstance(store, dict):
        store = {}
    store[str(st)] = {
        'use': u,
        'ids': ids,
        'cell_from': cell_name(*parse_cell(cell_from)),
        'cell_to': cell_name(*parse_cell(cell_to)),
        'corridor_w': round(cw, 2),
        'units': made,
        'unit_w': round(uw, 2),
        'depth': round(depth, 2),
        'plate': plate,
    }
    d.ext[EXT_KEY] = store
    d.selected = ids[:200]

    warn = ''
    if depth > R['max_depth']:
        warn = (
            f' NOTE: {depth:.1f} m from facade to corridor is past the {R["max_depth"]:g} m a '
            f'{u} unit can daylight — the back of each unit is dark; consider an atrium or a deeper corridor.'
        )
    if skipped:
        warn += f' {skipped} unit position(s) left out for the core.'
    if core_doors:
        warn += (
            f' {core_doors} door(s) cut through the corridor wall to the core, so the stair and the '
            f'lifts reach the corridor.'
        )
    if enclosed:
        warn += f' {enclosed} stair(s) enclosed in a walled well with a door on the corridor side.'
    if cores:
        what = ', '.join(f'{CL.core_word(o)} {o["id"]}' for o, _cr in cores[:4])
        if auto_core:
            warn += (
                f' The core was kept out automatically: {what} stand on storey {st} and '
                f'{core_skipped} unit position(s)/party wall(s) over them were left out '
                f'(no core_from/core_to was given).'
            )
        elif core_skipped:
            seen, names = set(), []
            for o, cr, _ox, _oz in short:
                if o['id'] not in seen:
                    seen.add(o['id'])
                    names.append(CL.core_phrase(o, cr))
            extra = (
                f' — core_from/core_to does not cover {", ".join(names[:3])}, widen it to keep the plate tidy'
                if names
                else ''
            )
            warn += f' {core_skipped} more unit position(s)/party wall(s) left out where {what} stands{extra}.'
    return (
        f'storey {st} laid out: {made} {R["label"].lower()}s of {uw:.2f} x {depth:.2f} m in two bands of '
        f'{made // 2 if made > 1 else made} either side of a '
        f'{cw:g} m corridor running {"east-west" if along_x else "north-south"} for '
        f'{run:g} m, {len(ids)} records ({made} zones, {made if doors else 0} doors). '
        f'repeat_floor(from_storey, to_storey, source_storey={st}) carries it up.{warn}'
    )


def t_repeat_floor(d: Drawing, a, from_storey, to_storey, source_storey=0, name=''):
    """Copy a laid-out storey to a range of storeys. One call for the typical floors."""
    store = d.ext.get(EXT_KEY)
    src = str(int(_num(source_storey, 0)))
    if not isinstance(store, dict) or src not in store:
        have = ', '.join(sorted(store)) if isinstance(store, dict) and store else 'none'
        return (
            f'refused: storey {src} has no layout to repeat (laid-out storeys: {have}) — call layout_floor on it first'
        )
    s0, s1 = int(_num(from_storey, 1)), int(_num(to_storey, 1))
    if s1 < s0:
        s0, s1 = s1, s0
    targets = [s for s in range(s0, s1 + 1) if s != int(src)]
    if not targets:
        return f'refused: that range is only storey {src}, which is the source'
    rec = store[src]
    srcs = [o for o in (d.find(i) for i in rec['ids']) if o]
    if not srcs:
        return f'refused: the storey {src} layout records are gone — lay it out again'
    total = len(srcs) * len(targets)
    if len(d.objs) + total > MAX_OBJECTS:
        room = MAX_OBJECTS - len(d.objs)
        fits = max(0, room // max(1, len(srcs)))
        return (
            f'refused: {len(targets)} storeys x {len(srcs)} records = {total}, and only {room} objects are '
            f'left under the {MAX_OBJECTS} ceiling. Repeat {fits} storeys at a time, or lay the floor out '
            f'with zones=false'
        )
    H = d.storey_h

    def _renumber(txt, s):
        """'corridor wall north st1' -> 'st5'; 'Apartment 1.03' -> 'Apartment 5.03'.
        A zone's LABEL lives in p.name, not in the record name — renaming only
        the record leaves every floor of the tower reading 'Apartment 1.xx'."""
        t = str(txt or '')
        t = t.replace(f'st{src}', f'st{s}')
        if f' {src}.' in t:
            t = t.replace(f' {src}.', f' {s}.')
        return t

    lift_cache: dict = {}

    def _lift_host(hid, dy):
        """The copy of a host that is NOT itself part of the layout.

        2026-09-16: a plan's windows are cut in the BUILDING's facade wall, and
        that wall is not one of the storey's own layout records, so it is not in
        `was` and the copy kept the storey-1 wall as its host. The facade has a
        per-storey twin of its own (o6..o9 at 2.7 m, o11..o14 at 5.4 m): the
        copy's real host is the twin on the same line one storey up. Without
        this a storey-2 window reads as reaching 5.30 m up a wall that stops at
        5.40 m from a floor at 2.70 m — open_off_wall, "the head is 2.60 m above
        the wall", eight of them on one replayed tower, every one of them an
        artefact of the copy. No twin on that line: keep the old id, because a
        host that is one storey out is still better evidence than none."""
        key = (str(hid), dy)
        if key in lift_cache:
            return lift_cache[key]
        h = d.find(str(hid))
        out = hid
        if h is not None:
            ty = _num(h.get('y'), 0.0) + dy
            # 2026-09-16 (job 944061f70863): on an ALTERNATING facade the twin one
            # storey up is a curtain_wall, not a wall — the old kind test found no
            # twin, kept the storey-1 wall, and every plan window on storeys 2..19
            # read 'reaches 21.50 m up a 2.7 m wall'. A wall's twin may be any
            # facade kind; the copy loop then drops an opening whose twin is glass.
            FACADE = ('wall', 'curtain_wall')
            for w in d.objs:
                if w is h or w.get('hidden'):
                    continue
                if h.get('kind') in FACADE:
                    if w.get('kind') not in FACADE:
                        continue
                elif w.get('kind') != h.get('kind'):
                    continue
                if (w.get('grp') or '') != (h.get('grp') or ''):
                    continue
                if (
                    abs(_num(w.get('y'), 0.0) - ty) > 0.05
                    or abs(_num(w.get('x'), 0.0) - _num(h.get('x'), 0.0)) > 0.05
                    or abs(_num(w.get('z'), 0.0) - _num(h.get('z'), 0.0)) > 0.05
                ):
                    continue
                out = w['id']
                break
        lift_cache[key] = out
        return out

    ids = []
    in_glass = [0]
    per_storey: dict = {}
    for s in targets:
        dy = (s - int(src)) * H
        start = len(ids)
        # 2026-09-16: the copies used to lose `meta`, so every copied door lost the
        # meta.host that names the wall it is cut through. opening_rules then found
        # no host of the door's OWN group (a unit door sits in a `corridor st<N>`
        # wall) and called all 54 of them orphans. Carry meta over, with `host`
        # remapped to THIS storey's copy of the wall.
        was, pairs = {}, []
        for o in srcs:
            # an opening whose facade host becomes a curtain wall one storey up
            # has nothing to be cut in: skip it (windows in glass are nonsense)
            hid0 = str((o.get('meta') or {}).get('host') or '')
            if hid0 and A.is_opening(str(o.get('kind') or '')) and not any(q['id'] == hid0 for q in srcs):
                tw = d.find(str(_lift_host(hid0, dy)))
                if tw is not None and tw.get('kind') == 'curtain_wall':
                    in_glass[0] += 1
                    continue
            g0 = str(o.get('grp') or '')
            g = _renumber(g0, s)
            ng = g if (g and g != g0) else (f'{g0} st{s}' if g0 else f'st{s}')
            nm = _renumber(o.get('name') or '', s)
            pp = dict(o.get('p') or {})
            if pp.get('name'):
                pp['name'] = _renumber(pp['name'], s)
            r = d.new(
                o['kind'],
                pp,
                o['x'],
                o['z'],
                round(o['y'] + dy, 4),
                o.get('ry') or 0.0,
                o.get('mat'),
                name=nm or None,
                grp=ng,
            )
            r['rx'], r['rz'], r['s'] = o.get('rx', 0.0), o.get('rz', 0.0), o.get('s', 1)
            was[o['id']] = r['id']
            pairs.append((o, r))
            ids.append(r['id'])
        for o, r in pairs:
            meta = dict(o.get('meta') or {})
            if not meta:
                continue
            if meta.get('host'):
                hid0 = str(meta['host'])
                meta['host'] = was[hid0] if hid0 in was else _lift_host(hid0, dy)
            r['meta'] = {**(r.get('meta') or {}), **meta}
        store[str(s)] = dict(rec, ids=[], repeated_from=int(src))
        per_storey[s] = ids[start:]
    # the copies of each storey, recorded so a later repeat can chain from them
    per = len(srcs)
    for s in targets:
        store[str(s)]['ids'] = list(per_storey.get(s) or [])
    d.ext[EXT_KEY] = store
    d.selected = ids[:200]
    return (
        f'storey {src} repeated onto storeys {", ".join(str(s) for s in targets[:12])}'
        f'{"…" if len(targets) > 12 else ""}: {len(ids)} records ({per} per storey). '
        + (
            f'{in_glass[0]} facade opening(s) not copied onto glazed storeys (a curtain wall takes no window). '
            if in_glass[0]
            else ''
        )
        + f'The drawing now holds {len(d.objs)} objects.'
    )


TOOLS = [
    (
        {
            'name': 'layout_floor',
            'description': 'Lay out a WHOLE floor in one call: a corridor down the long axis of the block, units either '
            'side, a door from every unit into the corridor and a zone record per unit (so egress_check, '
            'occupancy and fire_compartments can read the plan). Use this instead of placing rooms one by '
            'one — a floor is 30-60 records and you have 28 steps for the whole building. Corridor width '
            'and unit depth come from the object specs and are ENFORCED: a corridor under 1.2 m clear or '
            'a unit under 3 m deep is refused with the number to use. core_from/core_to leaves the core '
            'block empty. Then call repeat_floor for the typical storeys.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string', 'description': 'one corner of the floor plate'},
                    'cell_to': {'type': 'string', 'description': 'the opposite corner'},
                    'use': {
                        'type': 'string',
                        'description': 'residential, office, hotel, school, retail, civic, house, '
                        'mixed or warehouse — it sets the corridor width and unit size',
                    },
                    'storey': {'type': 'integer'},
                    'corridor_w': {
                        'type': 'number',
                        'description': 'clear corridor width in m (default from the use; '
                        '1.2 minimum, 1.5 comfortable, 1.8 for a school/hotel)',
                    },
                    'unit_w': {
                        'type': 'number',
                        'description': 'width of one unit along the corridor in m (default from '
                        'the use); the run is divided evenly into whole units',
                    },
                    'core_from': {
                        'type': 'string',
                        'description': 'optional: one corner of the core block to leave empty',
                    },
                    'core_to': {'type': 'string'},
                    'doors': {'type': 'boolean'},
                    'zones': {'type': 'boolean'},
                    'wall_h': {'type': 'number'},
                    'wall_t': {'type': 'number'},
                    'material': {'type': 'string'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'use', 'storey'],
            },
        },
        t_layout_floor,
    ),
    (
        {
            'name': 'repeat_floor',
            'description': 'Copy a storey laid out by layout_floor onto a range of storeys — the typical floors of a '
            'tower in ONE call instead of one call per floor. Names and groups are renumbered per storey. '
            'It refuses, with the number that does fit, when the copies would pass the object ceiling.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'from_storey': {'type': 'integer'},
                    'to_storey': {'type': 'integer'},
                    'source_storey': {'type': 'integer', 'description': 'the storey that was laid out (default 0)'},
                    'name': {'type': 'string'},
                },
                'required': ['from_storey', 'to_storey'],
            },
        },
        t_repeat_floor,
    ),
]

PROMPT = (
    'FLOOR LAYOUTS: layout_floor(cell_from, cell_to, use, storey) cuts a whole floor in ONE call — '
    'corridor, units both sides, a door and a zone per unit — and repeat_floor(from_storey, to_storey, '
    'source_storey) carries it up the typical storeys in a second. Use them for any interior past a couple '
    'of rooms: placing rooms one at a time does not fit the step budget. Corridor width and unit depth are '
    'enforced from the specs, so a too-narrow corridor is refused with the width to use.'
)
if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')

EXAMPLES = [
    {
        'ask': 'lay out the apartments on every floor of the block',
        'core': True,
        'calls': [
            {
                'tool': 'layout_floor',
                'args': {'cell_from': 'K20', 'cell_to': 'X34', 'use': 'residential', 'storey': 1, 'corridor_w': 1.5},
            },
            {'tool': 'repeat_floor', 'args': {'from_storey': 2, 'to_storey': 5, 'source_storey': 1}},
        ],
    },
    {
        'ask': 'office floors around the core',
        'calls': [
            {
                'tool': 'layout_floor',
                'args': {
                    'cell_from': 'EW140',
                    'cell_to': 'FQ160',
                    'use': 'office',
                    'storey': 1,
                    'core_from': 'FC148',
                    'core_to': 'FJ153',
                },
            },
            {'tool': 'repeat_floor', 'args': {'from_storey': 2, 'to_storey': 18, 'source_storey': 1}},
        ],
    },
]
