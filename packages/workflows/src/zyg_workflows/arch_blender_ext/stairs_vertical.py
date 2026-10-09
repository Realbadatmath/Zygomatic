# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stairs_vertical — Blender geometry for the vertical-circulation kinds.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom at z=0. A studio plan angle t (0 = +X, 90 = studio -Z)
is the ordinary counter-clockwise angle here: (cos t, sin t).

Every number below matches arch_ext/stairs_vertical.js one for one; the tests
compare the two engines' bounding boxes.
"""

import math


RAIL_H = 1.0  # guarding, exactly as arch_ext/stairs_vertical.js
POST = 0.04
BAR = 0.06
POST_SPACING = 1.0
RAIL_MI = 1  # material slot 1 = RAIL_MAT; slot 0 is the record's (the treads)
RAIL_MAT = 'mat_steel'
DOOR_H = 2.1  # the lift doors, exactly as arch_ext/stairs_vertical.js
DOOR_MARGIN = 0.4
DOOR_DEEP = 0.05
DOOR_GROOVE = 0.04


def _steps(kit, bm, n, rise, run, w, x0, y0, z0, sign=1.0):
    """A straight flight of n boxes run x w x rise, climbing from z0."""
    for i in range(int(n)):
        cx = x0 + sign * (run * i + run / 2)
        kit['add_box_c'](bm, run, w, rise, cx=cx, cy=y0, z0=z0 + rise * i)


def _flight_rail(kit, bm, n, rise, run, x0, sign, cy, z0):
    """The raked 1 m balustrade over a flight: posts about every metre standing
    on the TOP of a step, plus one sloping bar (a prism, so it can be raked).
    Slot 1 (mat_steel) throughout — the record's own material is the treads."""
    every = max(1, int(round(POST_SPACING / max(0.05, run))))
    for i in range(0, int(n), every):
        kit['add_box_c'](
            bm, POST, POST, RAIL_H, cx=x0 + sign * (run * i + run / 2), cy=cy, z0=z0 + rise * (i + 1), mi=RAIL_MI
        )
    xa = x0 + sign * (run / 2)
    xb = x0 + sign * (run * (n - 1) + run / 2)
    za, zb = z0 + rise + RAIL_H, z0 + rise * n + RAIL_H
    lo, hi = (xa, xb) if xa <= xb else (xb, xa)
    ya, yb = (za, zb) if xa <= xb else (zb, za)
    kit['add_prism'](
        bm, [(lo, ya - BAR), (hi, yb - BAR), (hi, yb), (lo, ya)], 'y', cy - BAR / 2, cy + BAR / 2, mi=RAIL_MI
    )


def _bar(bm, a, b, s=BAR, mi=0):
    """A square s x s bar between two 3-D points — the winder's rail cannot be an
    axis-aligned box, so it is built the way the winder treads are."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.sqrt(dx * dx + dy * dy) or 1e-9
    ux, uy = -dy / L, dx / L  # in plan, perpendicular to the run
    lo, hi = [], []
    for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        ox, oy, oz = ux * s / 2 * sx, uy * s / 2 * sx, s / 2 * sz
        lo.append(bm.verts.new((a[0] + ox, a[1] + oy, a[2] + oz)))
        hi.append(bm.verts.new((b[0] + ox, b[1] + oy, b[2] + oz)))
    faces = [bm.faces.new(list(reversed(lo))), bm.faces.new(hi)]
    for j in range(4):
        n = (j + 1) % 4
        faces.append(bm.faces.new((lo[j], lo[n], hi[n], hi[j])))
    for f in faces:
        f.material_index = mi


def _edge_rail(kit, bm, cx, ya, yb, ztop):
    """A level rail along a landing edge, from y=ya to y=yb at x=cx."""
    L = abs(yb - ya)
    n = max(2, int(round(L / POST_SPACING)) + 1)
    for i in range(n):
        kit['add_box_c'](bm, POST, POST, RAIL_H, cx=cx, cy=ya + (yb - ya) * i / (n - 1), z0=ztop, mi=RAIL_MI)
    kit['add_box_c'](bm, BAR, L + BAR, BAR, cx=cx, cy=(ya + yb) / 2, z0=ztop + RAIL_H - BAR, mi=RAIL_MI)


def _edge_rail_x(kit, bm, cy, xa, xb, ztop):
    """The mirror of _edge_rail: a level rail along one END of a landing, from
    x=xa to x=xb at the fixed y=cy."""
    L = abs(xb - xa)
    n = max(2, int(round(L / POST_SPACING)) + 1)
    for i in range(n):
        kit['add_box_c'](bm, POST, POST, RAIL_H, cx=xa + (xb - xa) * i / (n - 1), cy=cy, z0=ztop, mi=RAIL_MI)
    kit['add_box_c'](bm, L + BAR, BAR, BAR, cx=(xa + xb) / 2, cy=cy, z0=ztop + RAIL_H - BAR, mi=RAIL_MI)


def build_stair_u(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    ns = max(2, int(round(N('steps', 16))))
    rise, run, w, gap = N('rise', 0.175), N('run', 0.28), N('w', 1.0), N('gap', 0.2)
    na, nb = ns // 2, ns - ns // 2
    dy = (w + gap) / 2
    x0 = -(na * run + w) / 2
    _steps(kit, bm, na, rise, run, w, x0, -dy, 0.0)
    kit['add_box_c'](bm, w, 2 * w + gap, rise, cx=x0 + na * run + w / 2, cy=0.0, z0=rise * (na - 1))
    xb = x0 + na * run
    for i in range(nb):
        kit['add_box_c'](bm, run, w, rise, cx=xb - run * i - run / 2, cy=dy, z0=rise * (na + i))
    if N('rails', 0.0) > 0.5:
        xl0, xl1 = x0 + na * run, x0 + na * run + w - POST / 2  # the landing's x span
        _flight_rail(kit, bm, na, rise, run, x0, 1.0, -(dy + w / 2 - POST / 2), 0.0)
        _flight_rail(kit, bm, na, rise, run, x0, 1.0, -(gap / 2 + POST / 2), 0.0)  # well edge
        _flight_rail(kit, bm, nb, rise, run, xb, -1.0, dy + w / 2 - POST / 2, rise * na)
        _flight_rail(kit, bm, nb, rise, run, xb, -1.0, gap / 2 + POST / 2, rise * na)  # well edge
        _edge_rail(kit, bm, xl1, -(w + gap / 2), w + gap / 2, rise * na)
        _edge_rail_x(kit, bm, -(w + gap / 2 - POST / 2), xl0, xl1, rise * na)  # the two ends
        _edge_rail_x(kit, bm, w + gap / 2 - POST / 2, xl0, xl1, rise * na)
        return ('', [RAIL_MAT])
    return ('', [])


def build_stair_winder(bm, p, kit):
    """The winder treads are rotated boxes, not true wedges — hence '~'."""
    N = lambda k, d: kit['num'](p, k, d)
    ns = max(3, int(round(N('steps', 16))))
    rise, run, w, turn = N('rise', 0.175), N('run', 0.28), N('w', 1.0), N('turn', 90.0)
    nw = max(1, int(round(ns / 4.0)))
    if nw > ns - 2:
        nw = max(1, ns - 2)
    n1 = (ns - nw) // 2
    n2 = ns - nw - n1
    state = {'x': 0.0, 'y': 0.0, 'i': 0}
    line = []

    def tread(a):
        i = state['i']
        c, s = math.cos(a), math.sin(a)
        cx, cy = state['x'] + c * run / 2, state['y'] + s * run / 2
        z0 = rise * i
        e = w / 2 - POST / 2  # the outer edge of this tread
        line.append((cx - s * e, cy + c * e, rise * (i + 1)))
        corners = [(-run / 2, -w / 2), (run / 2, -w / 2), (run / 2, w / 2), (-run / 2, w / 2)]
        pts = [(cx + u * c - v * s, cy + u * s + v * c) for u, v in corners]
        lo = [bm.verts.new((x, y, z0)) for x, y in pts]
        hi = [bm.verts.new((x, y, z0 + rise)) for x, y in pts]
        bm.faces.new(list(reversed(lo)))
        bm.faces.new(hi)
        for j in range(4):
            n = (j + 1) % 4
            bm.faces.new((lo[j], lo[n], hi[n], hi[j]))
        state['x'] += c * run
        state['y'] += s * run
        state['i'] = i + 1

    ang = 0.0
    for _ in range(n1):
        tread(ang)
    da = math.radians(turn) / nw
    for _ in range(nw):
        ang += da
        tread(ang)
    for _ in range(n2):
        tread(ang)
    railed = N('rails', 0.0) > 0.5
    if railed:
        every = max(1, int(round(POST_SPACING / max(0.05, run))))
        pts = line[::every]
        if pts[-1] != line[-1]:
            pts.append(line[-1])
        for x, y, z in pts:
            kit['add_box_c'](bm, POST, POST, RAIL_H, cx=x, cy=y, z0=z, mi=RAIL_MI)
        for a, b in zip(pts, pts[1:]):
            _bar(bm, (a[0], a[1], a[2] + RAIL_H - BAR), (b[0], b[1], b[2] + RAIL_H - BAR), mi=RAIL_MI)
    bm.normal_update()
    return ('~', [RAIL_MAT] if railed else [])


def build_stair_landing(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('w', 1.2), N('d', 1.2), N('t', 0.15))
    return ('', [])


def build_elevator_shaft(bm, p, kit):
    """Four thin walls, plus a two-leaf door recessed into the door_side face at
    every storey in p['doors'] — the same panels as arch_ext/stairs_vertical.js.
    Studio +Z (south) is blender -Y, studio +X (east) is blender +X."""
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 1.8), N('d', 2.0), N('h', 8.1)
    t = min(N('t', 0.2), min(w, d) / 3)
    kit['add_box_c'](bm, w, t, h, cy=-(d - t) / 2)
    kit['add_box_c'](bm, w, t, h, cy=(d - t) / 2)
    kit['add_box_c'](bm, t, d - 2 * t, h, cx=-(w - t) / 2)
    kit['add_box_c'](bm, t, d - 2 * t, h, cx=(w - t) / 2)
    doors = list(p.get('doors') or [])
    sh = N('sh', 2.7)
    side = str(p.get('door_side') or 'south')
    if doors and sh > 0.1:
        along_x = side in ('south', 'north')
        face = w if along_x else d
        lw = max(0.2, face - DOOR_MARGIN)
        leaf = (lw - DOOR_GROOVE) / 2
        sgn = 1.0 if side in ('south', 'east') else -1.0  # studio sign
        span = d if along_x else w
        inset = max(0.0, min(t - DOOR_DEEP, DOOR_DEEP))
        off = sgn * (span / 2 - inset - DOOR_DEEP / 2)
        s0 = doors[0]
        for s in doors:
            base = (s - s0) * sh
            if base + DOOR_H > h + 0.01:
                continue
            for j in (-1, 1):
                c = j * (leaf + DOOR_GROOVE) / 2
                if along_x:  # studio +Z -> blender -Y
                    kit['add_box_c'](bm, leaf, DOOR_DEEP, DOOR_H, cx=c, cy=-off, z0=base)
                else:  # studio +X -> blender +X
                    kit['add_box_c'](bm, DOOR_DEEP, leaf, DOOR_H, cx=off, cy=-c, z0=base)
    return ('', [])


def build_elevator_car(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, door = N('w', 1.6), N('d', 1.8), N('h', 2.2), N('door', 1.0)
    t = 0.06
    kit['add_box_c'](bm, w, d, t)
    kit['add_box_c'](bm, w, d, t, z0=h - t)
    kit['add_box_c'](bm, t, d, h - 2 * t, cx=-(w - t) / 2, z0=t)
    kit['add_box_c'](bm, w - 2 * t, t, h - 2 * t, cy=-(d - t) / 2, z0=t)
    kit['add_box_c'](bm, w - 2 * t, t, h - 2 * t, cy=(d - t) / 2, z0=t)
    if door < 0.5:
        kit['add_box_c'](bm, t, d, h - 2 * t, cx=(w - t) / 2, z0=t)
    return ('', [])


def build_escalator(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    rise, w, angle, rh = N('rise', 2.7), N('w', 1.0), N('angle', 30.0), N('rail_h', 0.9)
    a = math.radians(max(5.0, min(60.0, angle)))
    L, t = rise / math.tan(a), 0.4
    kit['add_prism'](bm, [(-L / 2, 0.0), (L / 2, rise), (L / 2, rise + t), (-L / 2, t)], 'y', -w / 2, w / 2)
    for cy in (-(w / 2 - 0.04), (w / 2 - 0.04)):
        kit['add_prism'](
            bm, [(-L / 2, t), (L / 2, rise + t), (L / 2, rise + t + rh), (-L / 2, t + rh)], 'y', cy - 0.04, cy + 0.04
        )
    return ('', [])


def build_fire_stair_exterior(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    ns = max(1, int(round(N('storeys', 3))))
    sh, w, run, rise = N('h', 2.7), N('w', 1.2), N('run', 0.28), N('rise', 0.18)
    nst = max(2, int(round(sh / max(0.05, rise))))
    r = sh / nst
    Lf = nst * run
    ox = -Lf / 2
    for s in range(ns):
        up = s % 2 == 0
        for i in range(nst):
            xi = (run * i + run / 2) if up else (Lf - run * i - run / 2)
            kit['add_box_c'](bm, run, w, r, cx=ox + xi, z0=s * sh + r * i)
        lx = (Lf + w / 2) if up else (-w / 2)
        kit['add_box_c'](bm, w, w, 0.15, cx=ox + lx, z0=(s + 1) * sh - 0.15)
    return ('', [])


BUILDERS = {
    'stair_u': build_stair_u,
    'stair_winder': build_stair_winder,
    'stair_landing': build_stair_landing,
    'elevator_shaft': build_elevator_shaft,
    'elevator_car': build_elevator_car,
    'escalator': build_escalator,
    'fire_stair_exterior': build_fire_stair_exterior,
}
