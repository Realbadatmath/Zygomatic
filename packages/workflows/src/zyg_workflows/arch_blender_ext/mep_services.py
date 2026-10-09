# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mep_services — Blender geometry for the services family.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z (depth),
Z up, bottom at z=0. Horizontal runs (duct, pipe, cable_tray, gutter) lie along
local +X, exactly as in arch_ext/mep_services.js, so the record's ry aims them
the same way in both engines.

The studio's -Z is Blender's +Y, so the solar panel's rising edge — the one the
tab puts at studio -Z (north) — is the +Y edge here: rotating (y, z) by +tilt
about X raises +Y, which is the same board pointing the same way in the world.
"""

import math


# ── helpers the kit does not have ───────────────────────────────────────────
def _tube_x(bm, r, length, cy=0.0, cz=0.0, seg=16):
    """A cylinder lying along local X, centred on (cy, cz), length `length`."""
    a, b = -length / 2.0, length / 2.0
    ring0, ring1 = [], []
    for i in range(seg):
        th = 2.0 * math.pi * i / seg
        y, z = cy + r * math.cos(th), cz + r * math.sin(th)
        ring0.append(bm.verts.new((a, y, z)))
        ring1.append(bm.verts.new((b, y, z)))
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((ring0[i], ring0[j], ring1[j], ring1[i]))
    bm.faces.new(list(reversed(ring0)))
    bm.faces.new(ring1)


def _tilted_board(bm, w, d, t, tilt_deg, z0, mi=0):
    """A w x d board of thickness t, rotated `tilt_deg` about X (the +Y edge
    rises), sitting with its lowest corner at z = z0."""
    a = math.radians(tilt_deg)
    ca, sa = math.cos(a), math.sin(a)
    lift = z0 + d / 2.0 * sa + t / 2.0 * ca
    quad = ((-d / 2, -t / 2), (d / 2, -t / 2), (d / 2, t / 2), (-d / 2, t / 2))
    cols = []
    for sx in (-w / 2.0, w / 2.0):
        col = []
        for y, z in quad:
            col.append(bm.verts.new((sx, y * ca - z * sa, y * sa + z * ca + lift)))
        cols.append(col)
    v0, v1 = cols
    faces = [bm.faces.new(v0), bm.faces.new(list(reversed(v1)))]
    for i in range(4):
        j = (i + 1) % 4
        faces.append(bm.faces.new((v0[i], v0[j], v1[j], v1[i])))
    for f in faces:
        f.material_index = mi


# ── horizontal runs ─────────────────────────────────────────────────────────
def build_duct(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('len', 4), N('w', 0.4), N('h', 0.3))
    return ('', [])


def build_pipe(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r = N('r', 0.05)
    _tube_x(bm, r, N('len', 4), cz=r)
    return ('', [])


def build_cable_tray(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, h, t = N('len', 4), N('w', 0.3), N('h', 0.05), 0.008
    kit['add_box_c'](bm, L, w, 0.01)
    kit['add_box_c'](bm, L, t, h, cy=(w / 2 - t / 2))
    kit['add_box_c'](bm, L, t, h, cy=-(w / 2 - t / 2))
    return ('', [])


def build_gutter(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, r, t = N('len', 4), N('r', 0.08), 0.012
    kit['add_box_c'](bm, L, 2 * r, t)
    kit['add_box_c'](bm, L, t, r, cy=(r - t / 2))
    kit['add_box_c'](bm, L, t, r, cy=-(r - t / 2))
    return ('', [])


# ── vertical runs ───────────────────────────────────────────────────────────
def build_downpipe(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_cylinder'](bm, N('r', 0.05), N('h', 2.7), seg=12)
    return ('', [])


def build_antenna(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, r = N('h', 3), N('r', 0.03)
    kit['add_cylinder'](bm, r, h, seg=12)
    for i in range(3):
        kit['add_box_c'](bm, 0.03, 0.6, 0.03, z0=h * (0.55 + 0.2 * i) - 0.015)
    return ('', [])


def build_satellite_dish(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h = N('r', 0.4), N('h', 0.5)
    kit['add_cylinder'](bm, 0.04, h, seg=12)
    kit['add_cylinder'](bm, 0.08, 0.4 * r, z0=h, seg=24, r_top=r)
    return ('', [])


# ── plant & fittings ────────────────────────────────────────────────────────
def build_hvac_unit(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 1.2), N('d', 0.8), N('h', 1.0)
    kit['add_box_c'](bm, w, d, h)
    kit['add_cylinder'](bm, min(w, d) * 0.3, 0.06, z0=h - 0.06, seg=16)
    return ('', [])


def build_water_tank(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_cylinder'](bm, N('r', 1.0), N('h', 2.0), seg=24)
    return ('', [])


def build_chimney(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, cap = N('w', 0.6), N('d', 0.6), N('h', 1.5), N('cap', 0.1)
    kit['add_box_c'](bm, w, d, h)
    kit['add_box_c'](bm, w + 0.1, d + 0.1, cap, z0=h)
    return ('', [])


def build_radiator(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('w', 1.0), N('t', 0.1), N('h', 0.6))
    return ('', [])


def build_solar_panel(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, tilt = N('w', 1.7), N('d', 1.0), N('tilt', 30)
    t, leg = N('t', 0.04), N('leg', 0.3)
    _tilted_board(bm, w, d, t, tilt, leg)
    ca = math.cos(math.radians(tilt))
    lx, ly = max(0.05, w / 2 - 0.15), max(0.05, d * ca / 2 - 0.15)
    for sx in (-lx, lx):
        for sy in (-ly, ly):
            kit['add_box_c'](bm, 0.05, 0.05, leg, cx=sx, cy=sy)
    return ('', [])


BUILDERS = {
    'duct': build_duct,
    'pipe': build_pipe,
    'cable_tray': build_cable_tray,
    'gutter': build_gutter,
    'downpipe': build_downpipe,
    'antenna': build_antenna,
    'satellite_dish': build_satellite_dish,
    'hvac_unit': build_hvac_unit,
    'water_tank': build_water_tank,
    'chimney': build_chimney,
    'radiator': build_radiator,
    'solar_panel': build_solar_panel,
}
