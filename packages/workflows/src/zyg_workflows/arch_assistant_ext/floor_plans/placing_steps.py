# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.placing_steps — the stages `placing._place` is made of (2026-10-09).

`_place` was one 357-line function with three closures in it. It is now an
orchestrator that calls, in the order the drawing always happened:

    resolve_rotation -> (placing._plan_transform) -> build_context
    -> draw_walls -> draw_zones -> draw_doors -> draw_windows -> draw_fixtures
    -> closing_notes

Nothing was retuned. The three closures became a `PlaceFrame` (the snap-and-clamp
of one plan point, which read six enclosing locals), `nearest_seg` and
`PlaceCtx.bump`; every tally, note and refusal message is the one that was there,
and the order of the `d.new` / `IR._partition` / `IR._door` calls is unchanged.
`PlaceCtx` is the one object the drawing steps share, so each stage can be run on
its own — which is what tests/test_placing_helpers.py does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MAX_OBJECTS,
    _num,
)

from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    FIXTURE_KIND,
    HEAD_LINTEL,
    MIN_GLASS,
    SIDES_CW,
    _approach_rects,
    _claim,
    _clamp,
    _clip_segment,
    _core_centre,
    _core_rects,
    _facade,
    _group_wall_mat,
    _in_rects,
    _landing_rects,
    _mirror_side,
    _on_wall,
    _poly_centre,
    _snap,
)


def side_of(x, z, w, d) -> str:
    """Which edge of the plan's bbox a point lies nearest."""
    cand = (('west', abs(x)), ('east', abs(w - x)), ('north', abs(z)), ('south', abs(d - z)))
    return min(cand, key=lambda c: c[1])[0]


@dataclass
class PlaceFrame:
    """The plan -> world point map: the `_T` transform, then the snap to the grid,
    then the clamp into the bay. Was the `P(x, z)` closure inside `_place`, which
    read the transform, the snap step and all four bay edges from its scope."""

    T: object
    snap: float
    x0: float
    z0: float
    x1: float
    z1: float

    def pt(self, x, z) -> tuple:
        """One plan-space point as a snapped, clamped world (x, z)."""
        wx, wz = self.T.pt(x, z)
        return (_clamp(_snap(wx, self.snap), self.x0, self.x1), _clamp(_snap(wz, self.snap), self.z0, self.z1))


@dataclass
class PlaceCtx:
    """Everything the drawing stages of `_place` read and write: the drawing, the
    plan, the resolved frame and options, and the running tallies. One object
    instead of twelve locals shared by five closures."""

    d: Drawing
    plan: dict
    opts: dict
    st: int
    T: object
    frame: PlaceFrame
    y: float
    H: float
    grp: str
    group: str
    s: float
    with_shell: bool  # draw the exterior (shell) walls too
    wall_mat: str
    keep_out: object
    IR: object
    core_note: str = ''
    ids: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    dropped: int = 0
    too_short: int = 0  # openings whose host wall is shorter than their leaf
    too_low: int = 0  # windows whose host wall is lower than their glass
    doubled: int = 0  # openings on a piece of wall another opening already has
    placed: dict = field(default_factory=dict)  # host id -> [(along0, along1)] of the holes cut in it
    segs: list = field(default_factory=list)  # (record, ax, az, bx, bz) for door hosting
    ext_segs: list = field(default_factory=list)  # the shell walls, for windows when shell=True

    def P(self, x, z) -> tuple:
        """A plan point in world coordinates, snapped and clamped to the bay."""
        return self.frame.pt(x, z)

    def bump(self, k) -> None:
        """One more record of kind `k` in the per-kind counts."""
        self.counts[k] = self.counts.get(k, 0) + 1


def resolve_rotation(plan: dict, opts: dict, mirror: bool) -> tuple:
    """(rotation in degrees, error). A multiple of 90 or a refusal; with
    align="entrance" the rotation is DERIVED from the side the plan's own entrance
    is on and the side the caller wants it on, which is why it is not a free
    choice."""
    rot = int(_num(opts.get('rotate_deg'), 0)) % 360
    if rot % 90:
        return rot, f'refused: rotate_deg must be 0, 90, 180 or 270 (got {rot})'
    align = str(opts.get('align') or 'centre').strip().lower()
    if align == 'entrance':
        want = str(opts.get('entrance_side') or '').strip().lower()
        ent = plan.get('entrance') or {}
        es = str((ent or {}).get('side') or '')
        if want not in SIDES_CW:
            return rot, (
                'refused: align="entrance" needs entrance_side=north, south, east or west — or use align="centre"'
            )
        if es not in SIDES_CW:
            return rot, (
                f'refused: {plan.get("id")} has no entrance side on record, so it cannot be '
                f'aligned by it — use align="centre"'
            )
        base = _mirror_side(es) if mirror else es
        rot = 90 * ((SIDES_CW.index(want) - SIDES_CW.index(base)) % 4)
    return rot, ''


def align_core(d: Drawing, plan: dict, group: str, st: int, bounds: tuple, T) -> str:
    """align="core": shift `T` so the plan's own stair lands on the stair the
    drawing already has. Returns the note that says why it did not, if it did not —
    the plate is passed so a stair drawn by add_stair in its own group, named after
    the cell, is still the thing the plan lands on."""
    stairs = (plan.get('core') or {}).get('stairs') or []
    tgt = _core_centre(d, group, st, bounds)
    if stairs and tgt:
        cx, cz = _poly_centre(stairs[0])
        px, pz = T.pt(cx, cz)
        T.ox += tgt[0] - px
        T.oz += tgt[1] - pz
        return ''
    if not stairs:
        return f'{plan.get("id")} has no stair polygon, so it was centred instead'
    return f'"{group}" has no stair on storey {st}, so the plan was centred instead'


def keep_out_zones(d: Drawing, group: str, st: int, rect: tuple, opts: dict) -> tuple:
    """(rectangles the plan may not draw into, note). The core wells plus the floor
    in FRONT of the stair and lift doors.

    2026-09-11: the plate is passed so a core drawn in its OWN group (add_stair
    names its group after the cell) is still found — without it 80 partitions
    landed inside the stair and the lifts. 2026-09-16: the shaft WELL was kept
    clear and the floor in front of its doors was not, so a surveyed plan's own
    partition stood 0.4 m in front of the lift doors on every storey of a replayed
    tower (circ_lift_landing — and it was right, you cannot walk out of a lift into
    a wall).
    """
    keep_out = opts.get('keep_out')
    if keep_out is not None:
        return keep_out, ''
    keep_out = _core_rects(d, group, st, rect) if group else _core_rects(d, '', st, rect)
    feet = _approach_rects(d, group, st, rect) if group else _approach_rects(d, '', st, rect)
    feet = list(feet) + (_landing_rects(d, group, st, rect) if group else _landing_rects(d, '', st, rect))
    if not feet:
        return keep_out, ''
    return (
        list(keep_out) + feet,
        f'{len(feet)} stair/lift approach zone(s) kept clear of plan walls and fixtures',
    )


def capacity_error(d: Drawing, plan: dict) -> str:
    """The refusal when the plan's records would push the drawing past the object
    ceiling, or '' when there is room. Counted before anything is drawn, so a
    refusal leaves the drawing untouched."""
    need = (
        len(plan.get('walls') or [])
        + len(plan.get('rooms') or [])
        + len(plan.get('doors') or [])
        + len(plan.get('windows') or [])
        + len(plan.get('fixtures') or [])
        + 2
    )
    if len(d.objs) + need > MAX_OBJECTS:
        return (
            f'refused: {plan.get("id")} is about {need} records and the drawing is at '
            f'{len(d.objs)} of the {MAX_OBJECTS} ceiling'
        )
    return ''


def nearest_seg(px, pz, pool):
    """The record in `pool` whose segment passes closest to (px, pz), or None on an
    empty pool. The host wall an opening is cut into."""
    best = None
    for rec, ax, az, bx, bz in pool:
        vx, vz = bx - ax, bz - az
        L2 = vx * vx + vz * vz or 1e-9
        u = _clamp(((px - ax) * vx + (pz - az) * vz) / L2, 0.0, 1.0)
        dist = math.hypot(px - (ax + u * vx), pz - (az + u * vz))
        if best is None or dist < best[0]:
            best = (dist, rec)
    return best[1] if best else None


def build_context(d: Drawing, plan: dict, rect: tuple, bounds: tuple, storey: int, opts: dict, T) -> tuple:
    """(PlaceCtx, error) for a plan whose transform is already solved: the frame,
    the keep-out zones, the group, height and material of the walls to come, and
    the empty tallies. A non-empty error means nothing can be drawn and nothing
    has been."""
    x0, z0, x1, z1 = bounds
    st = int(storey)
    group = str(opts.get('group') or '')
    align = str(opts.get('align') or 'centre').strip().lower()
    core_note = align_core(d, plan, group, st, bounds, T) if align == 'core' else ''
    keep_out, approach_note = keep_out_zones(d, group, st, rect, opts)
    err = capacity_error(d, plan)
    if err:
        return None, err
    IR = A.EXT_MODULES.get('interior_rooms')
    if IR is None:
        return None, 'refused: the interior_rooms family is not loaded, so partitions cannot be drawn'
    ctx = PlaceCtx(
        d=d,
        plan=plan,
        opts=opts,
        st=st,
        T=T,
        frame=PlaceFrame(T, _num(opts.get('snap'), 0.25), x0, z0, x1, z1),
        y=_num(opts.get('y'), st * d.storey_h),
        H=max(0.5, d.storey_h - 0.3),
        grp=str(opts.get('grp') or f'plan {plan.get("id")} st{st}'),
        group=group,
        s=T.s,
        with_shell=bool(opts.get('shell')),
        wall_mat=str(opts.get('wall_mat') or '') or (_group_wall_mat(d, group) if group else 'mat_concrete'),
        keep_out=keep_out,
        IR=IR,
        core_note=core_note,
    )
    if approach_note:
        ctx.notes.append(approach_note)
    return ctx, ''


def draw_walls(ctx: PlaceCtx) -> None:
    """The plan's walls: an `ext` wall is drawn only with shell=True (the box
    already has its facade), every other wall becomes partitions clipped out of the
    core. A wall wholly inside the core is dropped, a clipped one counts as dropped
    too."""
    for w in ctx.plan.get('walls') or []:
        ax, az = ctx.P(*(w.get('a') or [0, 0]))
        bx, bz = ctx.P(*(w.get('b') or [0, 0]))
        if math.hypot(bx - ax, bz - az) < 0.2:
            continue
        t = max(0.05, _num(w.get('t'), 0.1) * ctx.s)
        if w.get('ext'):
            if not ctx.with_shell:
                continue  # the box already has its facade
            L = math.hypot(bx - ax, bz - az)
            rec = ctx.d.new(
                'wall',
                {'len': round(L, 4), 'h': ctx.d.storey_h, 't': round(t, 4)},
                (ax + bx) / 2,
                (az + bz) / 2,
                ctx.y,
                math.atan2(-(bz - az), bx - ax),
                ctx.wall_mat,
                name='plan wall',
                grp=ctx.grp,
            )
            ctx.ext_segs.append((rec, ax, az, bx, bz))
            ctx.ids.append(rec['id'])
            ctx.bump('wall')
            continue
        pieces = _clip_segment(ax, az, bx, bz, ctx.keep_out) if ctx.keep_out else [(ax, az, bx, bz)]
        if not pieces:
            ctx.dropped += 1  # wholly inside the core
            continue
        if len(pieces) > 1 or pieces[0] != (ax, az, bx, bz):
            ctx.dropped += 1  # the part inside the core is gone
        for qax, qaz, qbx, qbz in pieces:
            rec = ctx.IR._partition(
                ctx.d, qax, qaz, qbx, qbz, ctx.y, ctx.H, t, 'mat_plaster', 'plan partition', ctx.grp
            )
            ctx.segs.append((rec, qax, qaz, qbx, qbz))
            ctx.ids.append(rec['id'])
            ctx.bump('partition')


def draw_zones(ctx: PlaceCtx) -> None:
    """The plan's rooms as zone records, unless zones=False. A room whose centre
    falls in the core is dropped."""
    if not ctx.opts.get('zones', True):
        return
    for r in ctx.plan.get('rooms') or []:
        pts = [ctx.P(*p) for p in (r.get('pts') or []) if len(p) >= 2]
        if len(pts) < 3:
            continue
        cx, cz = _poly_centre(pts)
        if ctx.keep_out and _in_rects(cx, cz, ctx.keep_out):
            ctx.dropped += 1
            continue
        local = [[round(p[0] - cx, 4), round(p[1] - cz, 4)] for p in pts]
        nm = str(r.get('name') or (r.get('type') or 'Room')).strip() or 'Room'
        rec = ctx.d.new(
            'zone',
            {'pts': local, 'name': nm, 'use': str(r.get('type') or 'other'), 'h': 0.05},
            cx,
            cz,
            ctx.y,
            0.0,
            None,
            name=nm,
            grp=ctx.grp,
        )
        ctx.ids.append(rec['id'])
        ctx.bump('zone')


def draw_doors(ctx: PlaceCtx) -> None:
    """The plan's doors and then its entrance, unless doors=False. A door lands on
    the nearest partition (or shell wall); the entrance lands on the facade the
    caller names, because a unit's front door opens onto the corridor and never
    onto the block's own facade."""
    if not ctx.opts.get('doors', True):
        return
    for dr in ctx.plan.get('doors') or []:
        px, pz = ctx.P(_num(dr.get('x'), 0.0), _num(dr.get('z'), 0.0))
        if ctx.keep_out and _in_rects(px, pz, ctx.keep_out):
            ctx.dropped += 1
            continue
        host = nearest_seg(px, pz, ctx.segs or ctx.ext_segs)
        if host is None:
            continue
        leaf = _num(dr.get('w'), 0.9) * ctx.s
        wx, wz = _on_wall(host, px, pz, leaf)
        if wx is None:
            ctx.too_short += 1
            continue
        if not _claim(ctx.placed, host, wx, wz, leaf):
            ctx.doubled += 1
            continue
        rec = ctx.IR._door(ctx.d, host, wx, wz, leaf, None, 'plan door', ctx.grp)
        ctx.ids.append(rec['id'])
        ctx.bump('door')
    draw_entrance(ctx)


def draw_entrance(ctx: PlaceCtx) -> None:
    """The plan's own entrance door, on the wall the tiler hands in or on the
    facade of its side. Nothing happens when the plan records no entrance point."""
    ent = ctx.plan.get('entrance') or {}
    if not (ent and _num(ent.get('x'), None) is not None):
        return
    ex, ez = ctx.P(_num(ent.get('x'), 0.0), _num(ent.get('z'), 0.0))
    side = ctx.T.side(str(ent.get('side') or ''))
    # the tiler hands in the corridor wall: a unit's front door opens onto
    # the corridor, never onto the block's own facade
    ent_wall = ctx.opts.get('entrance_wall')
    if ent_wall is not None:
        host, err = ent_wall, ''
    else:
        host, err = _facade(ctx.d, ctx.group, side, ctx.st) if ctx.group else (None, 'no group')
    if host is None and ctx.with_shell and ctx.ext_segs:
        host = nearest_seg(ex, ez, ctx.ext_segs)
    if host is not None:
        wx, wz = _on_wall(host, ex, ez, 1.1)
        if wx is None:
            ctx.too_short += 1
            host = None
        elif not _claim(ctx.placed, host, wx, wz, 1.1):
            ctx.doubled += 1
            host = None
    if host is not None:
        rec = ctx.IR._door(ctx.d, host, wx, wz, 1.1, None, 'plan entrance', ctx.grp)
        ctx.ids.append(rec['id'])
        ctx.bump('door')
        if host['kind'] == 'curtain_wall':
            ctx.notes.append('entrance on a curtain wall: the studio does not cut it')
    elif err and not err.startswith('no group'):
        ctx.notes.append(f'no entrance door: {err.replace("refused: ", "")}')


def draw_windows(ctx: PlaceCtx) -> None:
    """The plan's windows, unless windows=False. A window on a curtain wall is
    skipped (the glazing already is the window), and one whose host wall is too low
    has its sill dropped to keep the glass or is not drawn at all."""
    if not ctx.opts.get('windows', True):
        return
    glazed = set()
    allow_sides = ctx.opts.get('window_sides')  # the tiler: only the outer face
    pw, pd = _num(ctx.plan.get('w'), 0.0), _num(ctx.plan.get('d'), 0.0)
    for wd in ctx.plan.get('windows') or []:
        wx0, wz0 = _num(wd.get('x'), 0.0), _num(wd.get('z'), 0.0)
        side = ctx.T.side(side_of(wx0, wz0, pw, pd))
        if allow_sides is not None and side not in allow_sides:
            continue
        px, pz = ctx.P(wx0, wz0)
        host = None
        if ctx.with_shell and ctx.ext_segs:
            host = nearest_seg(px, pz, ctx.ext_segs)
        elif ctx.group:
            host, _err = _facade(ctx.d, ctx.group, side, ctx.st)
            if host is not None and host['kind'] == 'curtain_wall':
                glazed.add(side)
                continue
        if host is None:
            continue
        leaf = max(0.3, _num(wd.get('w'), 1.2) * ctx.s)
        hx, hz = _on_wall(host, px, pz, leaf)
        if hx is None:
            ctx.too_short += 1
            continue
        if not _claim(ctx.placed, host, hx, hz, leaf):
            ctx.doubled += 1
            continue
        w_h, sill, ok = window_opening(wd, host)
        if not ok:
            ctx.too_low += 1
            continue
        p = {'w': round(leaf, 3), 'h': round(w_h, 3), 'sill': round(sill, 3)}
        rec = ctx.d.new(
            'window', p, hx, hz, host['y'], host['ry'], 'mat_plaster', name=f'plan window st{ctx.st}', grp=ctx.grp
        )
        rec['meta']['host'] = host['id']  # delete the wall, the window goes with it
        ctx.ids.append(rec['id'])
        ctx.bump('window')
    if glazed:
        ctx.notes.append(
            f'windows on the {", ".join(sorted(glazed))} curtain wall were skipped (the glazing is already the window)'
        )


def window_opening(wd: dict, host: dict) -> tuple:
    """(glass height, sill, drawable) for one window on the wall it landed on.

    The plan's own sill and head were surveyed against the storey the plan came
    from; the wall they land on is the studio's. A 0.9 m sill under a 1.9 m sash
    wants 2.80 m of wall and a storey wall is 2.7 m, so the head stood 0.10 m above
    the wall top — not a window, a notch in the roof (open_off_wall, eight of them
    on one replayed tower). Keep HEAD_LINTEL of wall over the head and drop the sill
    to keep the glass; when even that leaves under MIN_GLASS the wall is too low to
    be a window wall and the opening is not drawn.
    """
    w_h = max(0.3, _num(wd.get('h'), 1.4))
    sill = max(0.0, _num(wd.get('sill'), 0.9))
    hh = _num((host.get('p') or {}).get('h'), 0.0)
    if hh > 0 and sill + w_h > hh - HEAD_LINTEL:
        head = hh - HEAD_LINTEL
        sill = min(sill, max(0.0, head - w_h))
        w_h = head - sill
        if w_h < MIN_GLASS:
            return w_h, sill, False
    return w_h, sill, True


def draw_fixtures(ctx: PlaceCtx) -> None:
    """The plan's fixtures, unless fixtures=False. A fixture is tested against the
    core BY ITS FOOTPRINT, not its centre — 2026-09-11: a 2 m kitchen counter whose
    centre stood 0.45 m outside the stair well reached 0.6 m into it."""
    if not ctx.opts.get('fixtures', True):
        return
    for fx in ctx.plan.get('fixtures') or []:
        kind = FIXTURE_KIND.get(str(fx.get('kind') or ''))
        if not kind or kind not in A.KINDS:
            continue
        px, pz = ctx.P(_num(fx.get('x'), 0.0), _num(fx.get('z'), 0.0))
        fry = ctx.T.ang(_num(fx.get('ry'), 0.0))
        if ctx.keep_out and fixture_hits_core(kind, px, pz, fry, ctx.keep_out):
            ctx.dropped += 1
            continue
        rec = ctx.d.new(
            kind, dict(A.KINDS[kind]), px, pz, ctx.y, fry, None, name=f'plan {kind.replace("_", " ")}', grp=ctx.grp
        )
        ctx.ids.append(rec['id'])
        ctx.bump(kind)


def fixture_hits_core(kind: str, px: float, pz: float, fry: float, keep_out) -> bool:
    """Whether the fixture's rotated footprint overlaps any keep-out rectangle. The
    half-extents come from the kind's own footprint, turned by its rotation, with a
    50 mm tolerance on every edge."""
    try:
        fw, fd = A._p_footprint(dict(A.KINDS[kind]))
    except Exception:  # noqa: BLE001
        fw = fd = 0.6
    hx = (abs(fw * math.cos(fry)) + abs(fd * math.sin(fry))) / 2
    hz = (abs(fw * math.sin(fry)) + abs(fd * math.cos(fry))) / 2
    fbb = (px - hx, pz - hz, px + hx, pz + hz)
    return any(
        not (fbb[2] <= r[0] + 0.05 or r[2] <= fbb[0] + 0.05 or fbb[3] <= r[1] + 0.05 or r[3] <= fbb[1] + 0.05)
        for r in keep_out
    )


def closing_notes(ctx: PlaceCtx) -> None:
    """The notes that can only be written once everything is drawn: the core
    fallback, and the three tallies of openings that were refused."""
    if ctx.core_note:
        ctx.notes.append(ctx.core_note)
    if ctx.too_short:
        ctx.notes.append(
            f'{ctx.too_short} opening(s) not drawn: the wall they landed on is shorter than their own leaf'
        )
    if ctx.too_low:
        ctx.notes.append(
            f'{ctx.too_low} window(s) not drawn: the wall they landed on is under {MIN_GLASS + HEAD_LINTEL:g} m tall'
        )
    if ctx.doubled:
        ctx.notes.append(
            f'{ctx.doubled} opening(s) not drawn: another opening already has that '
            f'piece of wall (the plan lists a shared door once per room)'
        )
