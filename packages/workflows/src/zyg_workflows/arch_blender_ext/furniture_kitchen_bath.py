# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""furniture_kitchen_bath — Blender geometry for the kitchen, bathroom and
utility kinds. Mirrors arch_ext/furniture_kitchen_bath.js part for part.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z (so a part
the tab puts at studio z = -0.3, i.e. toward the front, sits at Blender y =
+0.3), Z up, bottom at z = 0. `_box` does that flip so the two files can be
read side by side with the same (w, h, d, cx, cy, cz) arguments as the JS.

Material slots: 0 = the record's own, then EXTRA below — 1 steel, 2 glass,
3 stone, 4 dark paint, 5 white paint.
"""

import math

EXTRA = ['mat_steel', 'mat_glass', 'mat_stone', 'mat_paint_dark', 'mat_paint_white']
STEEL, GLASS, STONE, DARK, WHITE = 1, 2, 3, 4, 5


def _box(kit, bm, w, h, d, cx=0.0, cy=0.0, cz=0.0, mi=0):
    """A box of studio size w (X) x h (up) x d (Z) centred at studio (cx, cy, cz)."""
    kit['add_box_c'](bm, max(w, 1e-4), max(d, 1e-4), max(h, 1e-4), cx, -cz, cy - h / 2, mi)


def _cyl(kit, bm, r, h, seg, cx=0.0, cy=0.0, cz=0.0, axis='y', mi=0):
    """A cylinder of radius r, length h, centred at studio (cx, cy, cz), whose
    axis runs along the studio Y (up), Z (depth) or X axis."""
    r, h, seg = max(r, 1e-4), max(h, 1e-4), max(6, int(seg))
    if axis == 'y':
        kit['add_cylinder'](bm, r, h, z0=cy - h / 2, seg=seg, cx=cx, cy=-cz, mi=mi)
        return
    prof = [(math.cos(2 * math.pi * i / seg) * r, math.sin(2 * math.pi * i / seg) * r) for i in range(seg)]
    if axis == 'z':  # studio Z -> blender Y
        kit['add_prism'](bm, [(cx + u, cy + v) for u, v in prof], 'y', -cz - h / 2, -cz + h / 2, mi)
    else:  # studio X -> blender X
        kit['add_prism'](bm, [(-cz + u, cy + v) for u, v in prof], 'x', cx - h / 2, cx + h / 2, mi)


def _rim(kit, bm, w, d, y0, hh, t, mi):
    cy = y0 + hh / 2
    _box(kit, bm, w, hh, t, 0, cy, d / 2 - t / 2, mi)
    _box(kit, bm, w, hh, t, 0, cy, -d / 2 + t / 2, mi)
    _box(kit, bm, t, hh, d - 2 * t, -w / 2 + t / 2, cy, 0, mi)
    _box(kit, bm, t, hh, d - 2 * t, w / 2 - t / 2, cy, 0, mi)


# ── kitchen ─────────────────────────────────────────────────────────────────
def build_kitchen_counter(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    L, d, h = N('len', 2.0), N('d', 0.6), N('h', 0.9)
    top = min(N('top', 0.04), h * 0.5)
    _box(kit, bm, L, h - top, d, 0, (h - top) / 2, 0)
    _box(kit, bm, L, top, d, 0, h - top / 2, 0, STONE)
    _box(kit, bm, max(L - 0.1, 0.05), 0.02, 0.02, 0, h - top - 0.08, -d / 2 + 0.01, STEEL)
    return ('', EXTRA)


def build_kitchen_island(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h, top = N('w', 2.0), N('d', 0.9), N('h', 0.9), 0.04
    _box(kit, bm, w - 0.04, h - top, d - 0.04, 0, (h - top) / 2, 0)
    _box(kit, bm, w, top, d, 0, h - top / 2, 0, STONE)
    _box(kit, bm, max(w - 0.3, 0.05), 0.02, 0.02, 0, h - top - 0.1, -d / 2 + 0.03, STEEL)
    return ('', EXTRA)


def build_wall_cabinet(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    L, d, h = N('len', 1.2), N('d', 0.35), N('h', 0.7)
    _box(kit, bm, L, h, d, 0, h / 2, 0)
    _box(kit, bm, 0.02, h - 0.06, 0.01, 0, h / 2, -d / 2 + 0.005, DARK)
    _box(kit, bm, max(L - 0.12, 0.05), 0.02, 0.02, 0, 0.06, -d / 2 + 0.01, STEEL)
    return ('', EXTRA)


def build_sink(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h = N('w', 0.6), N('d', 0.5), N('h', 0.9)
    t, rimh = 0.07, 0.24
    _box(kit, bm, w, h - rimh, d, 0, (h - rimh) / 2, 0)
    _rim(kit, bm, w, d, h - rimh, rimh, t, STEEL)
    _box(kit, bm, w - 2 * t, 0.02, d - 2 * t, 0, h - rimh + 0.01, 0, STEEL)
    _cyl(kit, bm, 0.02, 0.18, 12, 0, h - 0.09, d / 2 - 0.05, 'y', STEEL)
    return ('', EXTRA)


def build_stove(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h, hob = N('w', 0.6), N('d', 0.6), N('h', 0.9), 0.03
    _box(kit, bm, w, h - hob, d, 0, (h - hob) / 2, 0)
    _box(kit, bm, w, hob, d, 0, h - hob / 2, 0, STEEL)
    _box(kit, bm, w - 0.06, (h - hob) * 0.5, 0.02, 0, (h - hob) * 0.4, -d / 2 + 0.01, GLASS)
    for i in range(4):
        _cyl(
            kit,
            bm,
            0.075,
            0.006,
            14,
            (1 if i % 2 else -1) * w * 0.22,
            h - 0.003,
            (1 if i < 2 else -1) * d * 0.2,
            'y',
            DARK,
        )
    return ('', EXTRA)


def build_fridge(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h = N('w', 0.7), N('d', 0.7), N('h', 1.8)
    _box(kit, bm, w, h, d, 0, h / 2, 0)
    _box(kit, bm, w, 0.02, 0.01, 0, h * 0.62, -d / 2 + 0.005, DARK)
    _box(kit, bm, 0.03, min(0.5, h * 0.3), 0.04, w / 2 - 0.09, h * 0.78, -d / 2 + 0.02, STEEL)
    _box(kit, bm, 0.03, min(0.5, h * 0.3), 0.04, w / 2 - 0.09, h * 0.42, -d / 2 + 0.02, STEEL)
    return ('', EXTRA)


def build_dishwasher(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h = N('w', 0.6), N('d', 0.6), N('h', 0.85)
    _box(kit, bm, w, h, d, 0, h / 2, 0)
    _box(kit, bm, w - 0.06, h - 0.12, 0.02, 0, h / 2 - 0.02, -d / 2 + 0.01, STEEL)
    _box(kit, bm, w - 0.12, 0.03, 0.03, 0, h - 0.07, -d / 2 + 0.015, STEEL)
    return ('', EXTRA)


def build_washing_machine(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h = N('w', 0.6), N('d', 0.6), N('h', 0.85)
    _box(kit, bm, w, h, d, 0, h / 2, 0)
    _cyl(kit, bm, min(0.22, w * 0.38), 0.03, 20, 0, h * 0.5, -d / 2 + 0.015, 'z', GLASS)
    _box(kit, bm, w - 0.08, 0.08, 0.02, 0, h - 0.08, -d / 2 + 0.01, DARK)
    return ('', EXTRA)


# ── bathroom ────────────────────────────────────────────────────────────────
def build_toilet(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h, cist = N('w', 0.4), N('d', 0.7), N('h', 0.8), 0.2
    pan = min(0.4, h - 0.1)
    pd = max(d - cist, 0.1)
    _box(kit, bm, w, pan, pd, 0, pan / 2, -d / 2 + pd / 2)
    _box(kit, bm, w, 0.04, pd - 0.04, 0, pan + 0.02, -d / 2 + pd / 2, WHITE)
    _box(kit, bm, w, h - pan, cist, 0, pan + (h - pan) / 2, d / 2 - cist / 2)
    return ('', EXTRA)


def build_bathtub(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    L, w, h = N('l', 1.7), N('w', 0.75), N('h', 0.55)
    t, base = 0.06, 0.12
    _box(kit, bm, L, base, w, 0, base / 2, 0)
    _box(kit, bm, L, h - base, t, 0, base + (h - base) / 2, w / 2 - t / 2)
    _box(kit, bm, L, h - base, t, 0, base + (h - base) / 2, -w / 2 + t / 2)
    _box(kit, bm, t, h - base, w - 2 * t, -L / 2 + t / 2, base + (h - base) / 2, 0)
    _box(kit, bm, t, h - base, w - 2 * t, L / 2 - t / 2, base + (h - base) / 2, 0)
    _cyl(kit, bm, 0.02, min(0.14, h - base - 0.02), 12, -L / 2 + 0.12, h - 0.09, 0, 'y', STEEL)
    return ('', EXTRA)


def build_shower(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h = N('w', 0.9), N('d', 0.9), N('h', 2.0)
    tray, g = min(N('tray', 0.05), h * 0.5), 0.02
    _box(kit, bm, w, tray, d, 0, tray / 2, 0)
    _box(kit, bm, g, h - tray, d, w / 2 - g / 2, tray + (h - tray) / 2, 0, GLASS)
    _box(kit, bm, w, h - tray, g, 0, tray + (h - tray) / 2, -d / 2 + g / 2, GLASS)
    _box(kit, bm, 0.06, 0.30, 0.06, -w / 2 + 0.06, h - 0.55, d / 2 - 0.06, STEEL)
    _cyl(kit, bm, 0.09, 0.03, 16, -w / 2 + 0.16, h - 0.28, d / 2 - 0.16, 'y', STEEL)
    return ('', EXTRA)


def build_washbasin(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, d, h, bowl = N('w', 0.6), N('d', 0.45), N('h', 0.85), 0.13
    _box(kit, bm, min(0.25, w * 0.5), h - 0.15, min(0.25, d * 0.6), 0, (h - 0.15) / 2, 0)
    _box(kit, bm, w, bowl, d, 0, h - 0.02 - bowl / 2, 0)
    _box(kit, bm, w - 0.14, 0.02, d - 0.14, 0, h - 0.03, -0.02, WHITE)
    _cyl(kit, bm, 0.02, 0.10, 12, 0, h - 0.05, d / 2 - 0.05, 'y', STEEL)
    return ('', EXTRA)


def build_mirror(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    w, h, t = N('w', 0.6), N('h', 0.8), N('t', 0.02)
    _box(kit, bm, w, h, t / 2, 0, h / 2, t / 4)
    _box(kit, bm, w - 0.04, h - 0.04, t / 2, 0, h / 2, -t / 4, GLASS)
    return ('', EXTRA)


def build_towel_rail(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    L = N('len', 0.6)
    _box(kit, bm, 0.02, 0.06, 0.10, -L / 2 + 0.01, 0.03, 0, STEEL)
    _box(kit, bm, 0.02, 0.06, 0.10, L / 2 - 0.01, 0.03, 0, STEEL)
    _cyl(kit, bm, 0.015, L, 12, 0, 0.03, -0.035, 'x', STEEL)
    return ('', EXTRA)


def build_boiler(bm, p, kit):
    N = lambda k, v: kit['num'](p, k, v)
    r, h = N('r', 0.3), N('h', 1.2)
    _cyl(kit, bm, r, h * 0.92, 24, 0, h * 0.46, 0, 'y', 0)
    _cyl(kit, bm, r * 0.6, h * 0.08, 20, 0, h * 0.96, 0, 'y', STEEL)
    _box(kit, bm, r * 1.2, 0.10, 0.02, 0, h * 0.6, -r + 0.01, DARK)
    return ('', EXTRA)


BUILDERS = {
    'kitchen_counter': build_kitchen_counter,
    'kitchen_island': build_kitchen_island,
    'wall_cabinet': build_wall_cabinet,
    'sink': build_sink,
    'stove': build_stove,
    'fridge': build_fridge,
    'dishwasher': build_dishwasher,
    'washing_machine': build_washing_machine,
    'toilet': build_toilet,
    'bathtub': build_bathtub,
    'shower': build_shower,
    'washbasin': build_washbasin,
    'mirror': build_mirror,
    'towel_rail': build_towel_rail,
    'boiler': build_boiler,
}
