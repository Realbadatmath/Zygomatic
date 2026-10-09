# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fields_meadows — Blender geometry for crop_field, meadow, marsh and vineyard.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z (depth),
Z up, bottom at z=0. A studio plan angle theta is the ordinary counter-clockwise
angle in Blender's XY plane, so a studio local point (x, y, z_studio) is placed
at Blender (x, -z_studio, y) and then turned `dir` degrees CCW about Z.

THE DRAPE (2026-09-07): gx and gz are the ground plane's slopes along the
record's LOCAL x and z. Every solid is dropped onto that plane — its four base
corners take y = gx*X + gz*Z (X, Z the corner's plan position AFTER the `dir`
turn) and its side edges stay vertical, so the field follows the hillside while
its rows, posts and flowers still stand up. gx = gz = 0 rebuilds the flat boxes
exactly. A marsh is water and is never draped.

The row arithmetic and the scatter hash are the third copy of the contract in
arch_ext/fields_meadows.js and arch_assistant_ext/fields_meadows.py — the same
field, the same meadow, the same marsh in all three engines.

Material slots: 0 is the record's own material; the ids returned as `extra` fill
slots 1, 2, ... in that order, matching the `sub` overrides in the .js.
"""

import math

CROP_SUB = [['mat_sand'], ['mat_foliage'], ['mat_foliage'], ['mat_grass'], ['mat_brick', 'mat_paint_white', 'mat_sand']]
FLOWER_SUB = ['mat_paint_white', 'mat_brick', 'mat_sand']
ROW_FRAC = 0.6  # a row is 0.6 x spacing wide: a stripe, not a pipe


def _hash(ix, iy, seed):
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def _rows(d, spacing, band):
    n = max(2, min(2000, int(math.floor(d / max(0.05, spacing))) + 1))
    span = max(0.0, d - band)
    step = span / (n - 1)
    return [-span / 2 + j * step for j in range(n)]


def _box(bm, w, h, dd, cx, cy, cz, deg=0.0, mi=0, gx=0.0, gz=0.0):
    """A studio-frame box w (x) x h (up) x dd (studio z), centred at (cx, cz)
    in the PRE-turn plan with its base at cy, turned `deg` on the plan and
    DRAPED onto the ground plane (gx, gz) — vertical sides, corners on the
    plane. gx = gz = 0 and deg = 0 is the plain axis-aligned box."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x0, x1 = cx - w / 2, cx + w / 2
    z0, z1 = cz - dd / 2, cz + dd / 2
    lo, hi = [], []
    for px, pz in ((x0, z0), (x1, z0), (x1, z1), (x0, z1)):
        # studio local plan point after the turn
        bigx = px * c + pz * s
        bigz = -px * s + pz * c
        y = cy + gx * bigx + gz * bigz
        # studio (x, z) -> Blender (x, -z)
        lo.append(bm.verts.new((bigx, -bigz, y)))
        hi.append(bm.verts.new((bigx, -bigz, y + h)))
    faces = [bm.faces.new(list(reversed(lo))), bm.faces.new(hi)]
    for i in range(4):
        j = (i + 1) % 4
        faces.append(bm.faces.new((lo[i], lo[j], hi[j], hi[i])))
    for f in faces:
        f.material_index = mi


def _reed(bm, r, h, seg, cx, cz, mi=0):
    """A seg-sided stem standing on z=0 at the studio plan point (cx, cz)."""
    bx, by = cx, -cz
    lo, hi = [], []
    for i in range(seg):
        an = 2 * math.pi * i / seg
        x, y = bx + math.cos(an) * r, by + math.sin(an) * r
        lo.append(bm.verts.new((x, y, 0.0)))
        hi.append(bm.verts.new((x, y, h)))
    faces = [bm.faces.new(list(reversed(lo))), bm.faces.new(hi)]
    for i in range(seg):
        j = (i + 1) % seg
        faces.append(bm.faces.new((lo[i], lo[j], hi[j], hi[i])))
    for f in faces:
        f.material_index = mi


def build_crop_field(bm, p, kit):
    N = lambda k, dflt: kit['num'](p, k, dflt)  # noqa: E731
    w, d = max(0.5, N('w', 60.0)), max(0.5, N('d', 40.0))
    crop = max(0, min(4, int(round(N('crop', 0.0)))))
    sp, h = max(0.05, N('spacing', 0.75)), max(0.05, N('h', 0.3))
    deg = N('dir', 0.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    band = max(0.05, ROW_FRAC * sp)
    subs = CROP_SUB[crop]
    _box(bm, w, 0.05, d, 0.0, 0.0, 0.0, deg, mi=1, gx=gx, gz=gz)  # the soil plate
    for j, z in enumerate(_rows(d, sp, band)):
        _box(bm, w, h, band, 0.0, 0.05, z, deg, mi=2 + (j % len(subs)), gx=gx, gz=gz)
    bm.normal_update()
    return ('', ['mat_soil'] + list(subs))


def build_meadow(bm, p, kit):
    N = lambda k, dflt: kit['num'](p, k, dflt)  # noqa: E731
    w, d = max(0.5, N('w', 60.0)), max(0.5, N('d', 40.0))
    nf = max(0, min(2000, int(round(N('flowers', 200.0)))))
    seed, h = N('seed', 1.0), max(0.05, N('h', 0.25))
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    _box(bm, w, 0.08, d, 0.0, 0.0, 0.0, 0.0, mi=1, gx=gx, gz=gz)  # the grass plate
    iw, idp = max(0.01, w - 0.15), max(0.01, d - 0.15)
    for i in range(nf):
        x = -iw / 2 + _hash(i, 1, seed) * iw
        z = -idp / 2 + _hash(i, 2, seed) * idp
        c = int(_hash(i, 3, seed) * 3) % 3
        _box(bm, 0.15, 0.15, 0.15, x, h, z, 0.0, mi=2 + c, gx=gx, gz=gz)
    bm.normal_update()
    return ('', ['mat_grass'] + FLOWER_SUB)


def build_marsh(bm, p, kit):
    """Water lies LEVEL: a marsh is never draped (the assistant refuses uneven
    ground for it), so no gx/gz here."""
    N = lambda k, dflt: kit['num'](p, k, dflt)  # noqa: E731
    w, d = max(0.5, N('w', 60.0)), max(0.5, N('d', 40.0))
    dep = max(0.1, N('depth', 0.4))
    nr = max(0, min(1500, int(round(N('reeds', 150.0)))))
    seed, rh = N('seed', 1.0), max(0.2, N('reed_h', 1.8))
    t = 0.12
    iw, idp = max(0.02, w - 2 * t), max(0.02, d - 2 * t)
    _box(bm, w, dep, t, 0.0, -dep, -(d / 2 - t / 2))  # the rim
    _box(bm, w, dep, t, 0.0, -dep, (d / 2 - t / 2))
    _box(bm, t, dep, idp, -(w / 2 - t / 2), -dep, 0.0)
    _box(bm, t, dep, idp, (w / 2 - t / 2), -dep, 0.0)
    _box(bm, iw, max(0.02, dep - 0.25), idp, 0.0, -dep, 0.0, 0.0, mi=1)  # the bed
    _box(bm, iw, 0.04, idp, 0.0, -0.14, 0.0, 0.0, mi=2)  # water at -0.10
    sw, sd = max(0.01, w - 0.2), max(0.01, d - 0.2)
    for i in range(nr):
        _reed(bm, 0.05, rh, 4, -sw / 2 + _hash(i, 1, seed) * sw, -sd / 2 + _hash(i, 2, seed) * sd, mi=3)
    bm.normal_update()
    return ('', ['mat_soil', 'mat_water', 'mat_foliage'])


def build_vineyard(bm, p, kit):
    N = lambda k, dflt: kit['num'](p, k, dflt)  # noqa: E731
    w, d = max(0.5, N('w', 60.0)), max(0.5, N('d', 40.0))
    rs, h = max(0.3, N('row_spacing', 2.5)), max(0.2, N('h', 1.8))
    deg = N('dir', 0.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    npost = max(2, min(400, int(math.floor(w / 6.0)) + 1))
    pspan = max(0.0, w - 0.1)
    pstep = pspan / (npost - 1)
    for z in _rows(d, rs, 0.5):
        _box(bm, w, h * 0.6, 0.5, 0.0, h * 0.4, z, deg, mi=2, gx=gx, gz=gz)  # the vine mass
        for i in range(npost):
            _box(bm, 0.1, h, 0.1, -pspan / 2 + i * pstep, 0.0, z, deg, mi=1, gx=gx, gz=gz)
    bm.normal_update()
    return ('', ['mat_timber', 'mat_foliage'])


BUILDERS = {'crop_field': build_crop_field, 'meadow': build_meadow, 'marsh': build_marsh, 'vineyard': build_vineyard}
