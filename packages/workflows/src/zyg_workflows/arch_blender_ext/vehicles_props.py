# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vehicles_props — Blender geometry for the vehicles and site plant.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z (the
depth/width), Z up, bottom at z=0. It mirrors arch_ext/vehicles_props.js part
for part, so a record has the same bounding box in the tab and in Blender:
length l along X, width w along Y, height h along Z, front toward +X.

Wheels are cylinders with their axis along Y, drawn in the second material
slot (mat_paint_dark) — every builder that has wheels returns
('', ['mat_paint_dark']).
"""

WHEEL_MI = 1
DARK = ['mat_paint_dark']


def _slab(kit, bm, sx, sy, z0, z1, cx=0.0, cy=0.0, mi=0):
    kit['add_box_c'](bm, max(sx, 1e-3), max(sy, 1e-3), max(z1 - z0, 1e-3), cx, cy, z0, mi)


def _wheel(kit, bm, r, tw, x, y, seg=14):
    """A cylinder of radius r, thickness tw, axis along Y, resting on z=0.
    Built by hand rather than with add_cylinder (whose axis is Z) so no
    rotation op is needed."""
    math = kit['math']
    r, tw = max(r, 1e-3), max(tw, 1e-3)
    y0, y1 = y - tw / 2, y + tw / 2
    a = [(x + math.cos(2 * math.pi * i / seg) * r, r + math.sin(2 * math.pi * i / seg) * r) for i in range(seg)]
    v0 = [bm.verts.new((px, y0, pz)) for px, pz in a]
    v1 = [bm.verts.new((px, y1, pz)) for px, pz in a]
    faces = [bm.faces.new(list(reversed(v0))), bm.faces.new(v1)]
    for i in range(seg):
        j = (i + 1) % seg
        faces.append(bm.faces.new((v0[i], v0[j], v1[j], v1[i])))
    for f in faces:
        f.material_index = WHEEL_MI


def _axle(kit, bm, x, r, tw, w):
    yc = max(tw / 2, (w - tw) / 2)
    _wheel(kit, bm, r, tw, x, yc)
    _wheel(kit, bm, r, tw, x, -yc)


# ── road vehicles ───────────────────────────────────────────────────────────
def build_car(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 4.5), N('w', 1.8), N('h', 1.5)
    r, tw = min(0.34, h * 0.24, l * 0.09), min(0.2, w * 0.14)
    _slab(kit, bm, l, w, r * 0.55, h * 0.62)
    _slab(kit, bm, l * 0.5, w * 0.86, h * 0.62, h, -l * 0.04)
    _axle(kit, bm, l * 0.34, r, tw, w)
    _axle(kit, bm, -l * 0.32, r, tw, w)
    return ('', DARK)


def build_van(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 5.5), N('w', 2.0), N('h', 2.4)
    r, tw = min(0.38, h * 0.18, l * 0.09), min(0.24, w * 0.14)
    _slab(kit, bm, l * 0.72, w, r * 0.55, h, -l * 0.14)
    _slab(kit, bm, l * 0.34, w, r * 0.55, h * 0.74, l * 0.33)
    _axle(kit, bm, l * 0.32, r, tw, w)
    _axle(kit, bm, -l * 0.30, r, tw, w)
    return ('', DARK)


def build_bus(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 12), N('w', 2.5), N('h', 3.2)
    r, tw = min(0.5, h * 0.17), min(0.3, w * 0.13)
    _slab(kit, bm, l, w, r * 0.6, h * 0.42)
    _slab(kit, bm, l * 0.94, w, h * 0.42, h * 0.80)
    _slab(kit, bm, l, w, h * 0.80, h)
    _axle(kit, bm, l * 0.34, r, tw, w)
    _axle(kit, bm, -l * 0.30, r, tw, w)
    return ('', DARK)


def build_truck(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 9), N('w', 2.5), N('h', 3.6)
    r, tw = min(0.52, h * 0.16), min(0.3, w * 0.13)
    _slab(kit, bm, l, w * 0.8, h * 0.22, h * 0.30)
    _slab(kit, bm, l * 0.68, w, h * 0.30, h, -l * 0.16)
    _slab(kit, bm, l * 0.26, w, r * 0.6, h * 0.72, l * 0.37)
    _axle(kit, bm, l * 0.36, r, tw, w)
    _axle(kit, bm, -l * 0.26, r, tw, w)
    return ('', DARK)


def build_tractor(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 4), N('w', 2.2), N('h', 2.8)
    rr = min(0.75, h * 0.28, l * 0.20)
    rf, tw = rr * 0.56, min(0.45, w * 0.22)
    _slab(kit, bm, l, w * 0.5, h * 0.16, h * 0.26)
    _slab(kit, bm, l * 0.5, w * 0.55, h * 0.20, h * 0.56, l * 0.24)
    _slab(kit, bm, l * 0.42, w * 0.72, h * 0.20, h, -l * 0.20)
    _axle(kit, bm, -l * 0.22, rr, tw, w)
    _axle(kit, bm, l * 0.33, rf, tw * 0.7, w * 0.82)
    return ('', DARK)


def build_forklift(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 3), N('w', 1.2), N('h', 2.1)
    r, tw = min(0.3, h * 0.16), min(0.2, w * 0.17)
    _slab(kit, bm, l * 0.66, w, r * 0.6, h * 0.60, -l * 0.17)
    _slab(kit, bm, 0.1, w * 0.18, 0.04, h, l * 0.42, w * 0.28)
    _slab(kit, bm, 0.1, w * 0.18, 0.04, h, l * 0.42, -w * 0.28)
    _slab(kit, bm, l * 0.24, w * 0.62, 0.02, 0.09, l * 0.38)
    _axle(kit, bm, l * 0.28, r, tw, w)
    _axle(kit, bm, -l * 0.30, r, tw, w)
    return ('', DARK)


# ── two-wheelers ────────────────────────────────────────────────────────────
def _two_wheeler(kit, bm, l, h, w, r_frac):
    r = min(h * r_frac, l * 0.24)
    tw = max(0.05, r * 0.16)
    _wheel(kit, bm, r, tw, l / 2 - r, 0.0)
    _wheel(kit, bm, r, tw, -(l / 2 - r), 0.0)
    _slab(kit, bm, l * 0.5, w * 0.22, h * 0.42, h * 0.62, -l * 0.02)
    _slab(kit, bm, l * 0.14, w * 0.30, h * 0.66, h * 0.80, -l * 0.16)
    _slab(kit, bm, l * 0.10, w, h * 0.80, h, l * 0.30)
    _slab(kit, bm, 0.06, w * 0.16, r, h * 0.86, l / 2 - r)
    return ('', DARK)


def build_bicycle(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    return _two_wheeler(kit, bm, N('l', 1.8), N('h', 1.0), 0.55, 0.35)


def build_motorcycle(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    return _two_wheeler(kit, bm, N('l', 2.1), N('h', 1.1), 0.8, 0.30)


# ── boat ────────────────────────────────────────────────────────────────────
def build_boat(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 6), N('w', 2.2), N('h', 1.5)
    hh = h * 0.55
    profile = [(-l / 2, hh), (-l / 2, hh * 0.32), (-l * 0.30, 0.0), (l * 0.26, 0.0), (l / 2, hh * 0.45), (l / 2, hh)]
    kit['add_prism'](bm, profile, 'y', -w / 2, w / 2)  # (u, v) = (X, Z), swept along Y
    _slab(kit, bm, l * 0.34, w * 0.70, hh, h, -l * 0.06)
    return ('', [])


# ── site plant ──────────────────────────────────────────────────────────────
def build_crane_tower(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, jib, m = N('h', 30), N('jib', 25), N('mast', 1.6)
    cj, jh = jib * 0.35, m * 0.55
    _slab(kit, bm, m, m, 0.0, h)
    _slab(kit, bm, jib + cj, m * 0.6, h - jh, h, (jib - cj) / 2)
    _slab(kit, bm, cj * 0.34, m * 0.8, h - jh - jh * 1.4, h - jh, -cj * 0.78)
    _slab(kit, bm, m * 1.2, m * 0.9, h - jh - m * 1.1, h - jh, m * 0.9)
    _slab(kit, bm, m * 0.5, m * 0.5, h - jh - m * 1.6, h - jh, jib * 0.86, 0.0, WHEEL_MI)
    return ('', DARK)


def build_scaffold(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, dp = N('w', 6), N('h', 6), N('d', 1.2)
    bays = max(1, int(round(N('bays', 3))))
    lifts = max(1, int(round(N('lifts', 3))))
    t = 0.06
    yc = max(t / 2, (dp - t) / 2)
    for i in range(bays + 1):
        px = -(w - t) / 2 + (w - t) * i / bays
        _slab(kit, bm, t, t, 0.0, h, px, yc)
        _slab(kit, bm, t, t, 0.0, h, px, -yc)
        _slab(kit, bm, t, dp, h - t, h, px, 0.0)
    for i in range(1, lifts + 1):
        pz = h * i / lifts
        _slab(kit, bm, w, t, pz - t, pz, 0.0, yc)
        _slab(kit, bm, w, t, pz - t, pz, 0.0, -yc)
        _slab(kit, bm, w - t, dp - t, pz - t - 0.04, pz - t, 0.0, 0.0, WHEEL_MI)
    return ('', ['mat_timber'])


def build_container(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 6.06), N('w', 2.44), N('h', 2.59)
    _slab(kit, bm, l, w, 0.0, h)
    _slab(kit, bm, 0.05, w * 0.9, h * 0.05, h * 0.95, l / 2 - 0.04, 0.0, WHEEL_MI)
    return ('', DARK)


def build_dumpster(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 3), N('w', 1.8), N('h', 1.4)
    _slab(kit, bm, l, w, 0.0, h * 0.82)
    _slab(kit, bm, l, w, h * 0.82, h, 0.0, 0.0, WHEEL_MI)
    return ('', DARK)


def build_pallet(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    l, w, h = N('l', 1.2), N('w', 0.8), N('h', 0.15)
    b = min(0.022, h * 0.16)
    _slab(kit, bm, l, w, h - b, h)
    _slab(kit, bm, l, w, 0.0, b)
    for cx in (-l * 0.45, 0.0, l * 0.45):
        _slab(kit, bm, l * 0.1, w, b, h - b, cx)
    return ('', [])


BUILDERS = {
    'car': build_car,
    'van': build_van,
    'bus': build_bus,
    'truck': build_truck,
    'tractor': build_tractor,
    'forklift': build_forklift,
    'bicycle': build_bicycle,
    'motorcycle': build_motorcycle,
    'boat': build_boat,
    'crane_tower': build_crane_tower,
    'scaffold': build_scaffold,
    'container': build_container,
    'dumpster': build_dumpster,
    'pallet': build_pallet,
}
