# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""massing_morph — Blender geometry for the mass_* study volumes.

The twin of arch_ext/massing_morph.js, ring for ring. Outlines are written in
the STUDIO plan frame (x, z) with the studio's angle convention — a point at
theta is (r cos t, -r sin t) — and `_build` flips them into Blender's local
frame (X along, Y = studio -Z, Z up, bottom at z=0) as it makes the verts, so
the two files can share one set of outline functions verbatim.

A ring is one horizontal level: a closed loop of (x, z) plan points at a
height y. Every ring of a volume holds the same number of points; `_build`
sews quads between consecutive rings and caps the first and the last.
"""

import math
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


CAP_FAN = 'fan'
CAP_BAND = 'band'  # loop whose second half is the first half's inner twin


def _build(bm, rings, cap=CAP_FAN):
    """rings: [(y, [(x, z), ...]), ...] in the studio plan frame."""
    grid = []
    for y, outline in rings:
        grid.append([bm.verts.new((x, -z, y)) for x, z in outline])
    n_l = len(grid[0])
    faces = []
    for i in range(len(grid) - 1):
        a, b = grid[i], grid[i + 1]
        for j in range(n_l):
            m = (j + 1) % n_l
            faces.append((a[j], a[m], b[m], b[j]))
    top = grid[-1]
    bot = grid[0]
    if cap == CAP_BAND:
        half = n_l // 2
        for j in range(half - 1):
            p0, p1, q1, q0 = j, j + 1, n_l - 2 - j, n_l - 1 - j
            faces.append((top[p0], top[p1], top[q1], top[q0]))
            faces.append((bot[p0], bot[q0], bot[q1], bot[p1]))
    else:
        for j in range(1, n_l - 1):
            faces.append((top[0], top[j], top[j + 1]))
            faces.append((bot[0], bot[j + 1], bot[j]))
    for f in faces:
        try:
            bm.faces.new(f)
        except ValueError as _exc:  # a duplicate/degenerate face is not worth losing the mesh over
            _zyg_log.debug('duplicate or degenerate face skipped: %s', _exc)
    bm.normal_update()


# ── outlines (identical arithmetic to the .js) ───────────────────────────────
def _rect(w, d):
    hw, hd = max(w, 0.05) / 2, max(d, 0.05) / 2
    return [(hw, -hd), (-hw, -hd), (-hw, hd), (hw, hd)]


def _ellipse(rx, rz, seg):
    n = max(6, int(round(seg)))
    rx, rz = max(rx, 0.05), max(rz, 0.05)
    return [(rx * math.cos(2 * math.pi * i / n), -rz * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _rect_at(w, d, t):
    ct, st = math.cos(t), math.sin(t)
    sx = 1e9 if abs(ct) < 1e-9 else (max(w, 0.05) / 2) / abs(ct)
    sz = 1e9 if abs(st) < 1e-9 else (max(d, 0.05) / 2) / abs(st)
    s = min(sx, sz)
    return (s * ct, -s * st)


def _spin(outline, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(x * c + z * s, z * c - x * s) for x, z in outline]


# ── the kinds ────────────────────────────────────────────────────────────────
def build_mass_taper(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h = N('h', 27.0)
    _build(bm, [(0.0, _rect(N('w', 10.0), N('d', 10.0))), (h, _rect(N('w_top', 6.0), N('d_top', 6.0)))])
    return ('', [])


def build_mass_twist(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, tw = N('h', 27.0), N('twist', 45.0)
    seg = max(1, min(200, int(round(N('seg', 10.0)))))
    base = _rect(N('w', 10.0), N('d', 10.0))
    _build(bm, [(h * i / seg, _spin(base, tw * i / seg)) for i in range(seg + 1)])
    return ('', [])


def build_mass_setback(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 12.0), N('d', 12.0), N('h', 27.0)
    steps = max(1, min(40, int(round(N('steps', 3.0)))))
    si = N('step_in', 2.0)
    rings = []
    for i in range(steps):
        o = _rect(max(0.5, w - 2 * si * i), max(0.5, d - 2 * si * i))
        rings.append((h * i / steps, o))
        rings.append((h * (i + 1) / steps, o))
    _build(bm, rings)
    return ('', [])


def build_mass_loft(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 10.0), N('d', 10.0), N('h', 27.0)
    seg = max(6, min(240, int(round(N('seg', 24.0)))))
    lev, rings = 8, []
    for i in range(lev):
        f = i / (lev - 1)
        ring = []
        for j in range(seg):
            t = 2 * math.pi * j / seg
            rx, rz = _rect_at(w, d, t)
            ex = max(w, 0.05) / 2 * math.cos(t)
            ez = -max(d, 0.05) / 2 * math.sin(t)
            ring.append((rx + (ex - rx) * f, rz + (ez - rz) * f))
        rings.append((h * f, ring))
    _build(bm, rings)
    return ('', [])


def build_mass_ellipse(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    o, h = _ellipse(N('rx', 6.0), N('rz', 4.0), N('seg', 48.0)), N('h', 27.0)
    _build(bm, [(0.0, o), (h, o)])
    return ('', [])


def build_mass_arc(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, a0, a1 = N('r', 20.0), N('a0', 0.0), N('a1', 90.0)
    w, h = N('w', 12.0), N('h', 27.0)
    seg = max(4, min(360, int(round(N('seg', 32.0)))))
    if abs(a1 - a0) < 0.5:
        a1 = a0 + 0.5
    if abs(a1 - a0) > 355:
        a1 = a0 + (355 if a1 > a0 else -355)
    ri, ro = max(0.1, r - max(w, 0.1) / 2), r + max(w, 0.1) / 2
    outer, inner = [], []
    for i in range(seg + 1):
        t = math.radians(a0 + (a1 - a0) * i / seg)
        c, s = math.cos(t), math.sin(t)
        outer.append((ro * c, -ro * s))
        inner.append((ri * c, -ri * s))
    o = outer + list(reversed(inner))
    _build(bm, [(0.0, o), (h, o)], CAP_BAND)
    return ('', [])


def build_mass_chamfer(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = max(N('w', 10.0), 0.05), max(N('d', 10.0), 0.05), N('h', 27.0)
    c = max(0.01, min(N('c', 1.0), min(w, d) / 2 - 0.01))
    hw, hd = w / 2, d / 2
    o = [
        (hw, -hd + c),
        (hw - c, -hd),
        (-hw + c, -hd),
        (-hw, -hd + c),
        (-hw, hd - c),
        (-hw + c, hd),
        (hw - c, hd),
        (hw, hd - c),
    ]
    _build(bm, [(0.0, o), (h, o)])
    return ('', [])


def build_mass_round(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = max(N('w', 10.0), 0.05), max(N('d', 10.0), 0.05), N('h', 27.0)
    r = max(0.01, min(N('r', 2.0), min(w, d) / 2 - 0.01))
    hw, hd, S = w / 2 - r, d / 2 - r, 6
    cen = [(hw, -hd), (-hw, -hd), (-hw, hd), (hw, hd)]
    o = []
    for q in range(4):
        for i in range(S + 1):
            t = math.radians(q * 90 + 90 * i / S)
            o.append((cen[q][0] + r * math.cos(t), cen[q][1] - r * math.sin(t)))
    _build(bm, [(0.0, o), (h, o)])
    return ('', [])


def build_mass_shear(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, sx, sz = N('h', 27.0), N('shear_x', 3.0), N('shear_z', 0.0)
    base = _rect(N('w', 10.0), N('d', 10.0))
    _build(bm, [(0.0, base), (h, [(x + sx, z + sz) for x, z in base])])
    return ('', [])


BUILDERS = {
    'mass_taper': build_mass_taper,
    'mass_twist': build_mass_twist,
    'mass_setback': build_mass_setback,
    'mass_loft': build_mass_loft,
    'mass_ellipse': build_mass_ellipse,
    'mass_arc': build_mass_arc,
    'mass_chamfer': build_mass_chamfer,
    'mass_round': build_mass_round,
    'mass_shear': build_mass_shear,
}
