# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""furniture_living — Blender geometry for the 14 furniture kinds.

Local frame (arch_blender_build.build_kind): X along the width, Y = the
studio's -Z (so the studio's FRONT, local -Z, is Blender +Y), Z up with the
bottom at z=0. Every piece is boxes plus a couple of cylinders, mirroring
arch_ext/furniture_living.js part for part so the tab and a render agree.

Because the studio's -Z maps to Blender +Y, a part the JS puts at z = -l/2
belongs at y = +l/2 here; the sign flip is applied where it matters (head
boards, backs, doors, screens).
"""


def _bed(bm, p, kit, dw, dl, dh, dhead):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, l, h = N('w', dw), N('l', dl), N('h', dh)
    head = max(N('head', dhead), h + 0.15)
    box(bm, w, l, h * 0.62, 0.0, 0.0, 0.0)  # base frame
    box(bm, w - 0.08, l - 0.08, h * 0.38, 0.0, 0.0, h * 0.62)  # mattress
    box(bm, w, 0.06, head, 0.0, l / 2 - 0.03, 0.0)  # head board (studio -Z)
    pw = (w / 2 - 0.10) if w > 1.2 else (w - 0.16)
    px = (pw / 2 + 0.05) if w > 1.2 else 0.0
    box(bm, pw, 0.34, 0.12, px, l / 2 - 0.30, h)
    if w > 1.2:
        box(bm, pw, 0.34, 0.12, -px, l / 2 - 0.30, h)
    return ('', [])


def build_bed_single(bm, p, kit):
    return _bed(bm, p, kit, 0.9, 2.0, 0.5, 0.9)


def build_bed_double(bm, p, kit):
    return _bed(bm, p, kit, 1.6, 2.0, 0.5, 1.0)


def _carcass(bm, p, kit, dw, dd, dh, fronts):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', dw), N('d', dd), N('h', dh)
    box(bm, w, d, h, 0.0, 0.0, 0.0)
    fw = (w - 0.06) / fronts
    fh = (h - 0.12) / fronts
    for i in range(fronts):
        if dh >= 1.0:
            box(bm, fw - 0.01, 0.025, h - 0.10, -w / 2 + 0.03 + fw * (i + 0.5), d / 2 - 0.013, 0.05)
            box(bm, 0.02, 0.03, 0.14, -0.05 if i == 0 else 0.05, d / 2 - 0.028, h * 0.55 - 0.07)
        else:
            box(bm, w - 0.06, 0.02, fh - 0.02, 0.0, d / 2 - 0.011, 0.06 + fh * i + 0.01)
            box(bm, 0.02, 0.03, 0.02, 0.0, d / 2 - 0.028, 0.06 + fh * (i + 0.5) - 0.01)
    return ('', [])


def build_wardrobe(bm, p, kit):
    return _carcass(bm, p, kit, 1.2, 0.6, 2.1, 2)


def build_nightstand(bm, p, kit):
    return _carcass(bm, p, kit, 0.45, 0.4, 0.55, 2)


def _seating(bm, p, kit, dw, dd, dh, dseat):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', dw), N('d', dd), N('h', dh)
    seat = min(N('seat', dseat), h - 0.15)
    box(bm, w, d, seat * 0.4, 0.0, 0.0, 0.0)  # plinth
    box(bm, w - 0.30, d - 0.22, seat * 0.6, 0.0, 0.11, seat * 0.4)  # cushion (towards the front)
    box(bm, w, 0.22, h, 0.0, -(d / 2 - 0.11), 0.0)  # back (studio +Z)
    for s in (-1.0, 1.0):
        box(bm, 0.15, d, seat + 0.22, s * (w / 2 - 0.075), 0.0, 0.0)  # arms
    return ('', [])


def build_sofa(bm, p, kit):
    return _seating(bm, p, kit, 2.2, 0.9, 0.85, 0.45)


def build_armchair(bm, p, kit):
    return _seating(bm, p, kit, 0.9, 0.9, 0.85, 0.45)


def _table(bm, p, kit, dw, dd, dh, top_t):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', dw), N('d', dd), N('h', dh)
    t = min(top_t, h * 0.4)
    lh = h - t
    box(bm, w, d, t, 0.0, 0.0, h - t)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            box(bm, 0.06, 0.06, lh, sx * (w / 2 - 0.06), sy * (d / 2 - 0.06), 0.0)
    return ('', [])


def build_coffee_table(bm, p, kit):
    return _table(bm, p, kit, 1.1, 0.6, 0.42, 0.05)


def build_dining_table(bm, p, kit):
    return _table(bm, p, kit, 1.8, 0.9, 0.75, 0.06)


def build_chair(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', 0.45), N('d', 0.45), N('h', 0.9)
    seat = min(N('seat', 0.45), h - 0.2)
    box(bm, w, d, 0.05, 0.0, 0.0, seat - 0.05)
    box(bm, w, 0.05, h - seat, 0.0, -(d / 2 - 0.025), seat)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            box(bm, 0.04, 0.04, seat - 0.05, sx * (w / 2 - 0.04), sy * (d / 2 - 0.04), 0.0)
    return ('', [])


def build_desk(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', 1.4), N('d', 0.7), N('h', 0.75)
    box(bm, w, d, 0.04, 0.0, 0.0, h - 0.04)
    for sx in (-1.0, 1.0):
        box(bm, 0.04, d - 0.06, h - 0.04, sx * (w / 2 - 0.02), 0.0, 0.0)
    box(bm, w - 0.12, 0.03, 0.35, 0.0, -(d / 2 - 0.02), h - 0.04 - 0.35)
    return ('', [])


def build_bookcase(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, d, h = N('w', 0.9), N('d', 0.35), N('h', 2.0)
    n = max(1, min(20, int(round(N('shelves', 5)))))
    for sx in (-1.0, 1.0):
        box(bm, 0.03, d, h, sx * (w / 2 - 0.015), 0.0, 0.0)
    box(bm, w, d, 0.03, 0.0, 0.0, 0.0)
    box(bm, w, d, 0.03, 0.0, 0.0, h - 0.03)
    box(bm, w - 0.06, 0.015, h - 0.06, 0.0, -(d / 2 - 0.008), 0.03)
    for i in range(1, n):
        box(bm, w - 0.06, d - 0.02, 0.02, 0.0, 0.0, h * i / n - 0.01)
    return ('', [])


def build_tv_unit(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    math = kit['math']
    w, d, h = N('w', 1.6), N('d', 0.45), N('h', 0.5)
    diag = N('screen', 1.2)
    den = math.sqrt(16 * 16 + 9 * 9)
    sw, sh = diag * 16 / den, diag * 9 / den
    if sw > w:
        sh *= w / sw
        sw = w
    box(bm, w, d, h, 0.0, 0.0, 0.0)
    for sx in (-1.0, 1.0):
        box(bm, w / 2 - 0.04, 0.02, h - 0.10, sx * w / 4, d / 2 - 0.011, 0.05)
    box(bm, 0.30, 0.20, 0.06, 0.0, -(d / 2 - 0.12), h)
    box(bm, sw, 0.04, sh, 0.0, -(d / 2 - 0.12), h + 0.06)
    return ('', [])


def build_rug(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('w', 2.4), N('d', 1.7), max(N('t', 0.02), 0.005), 0.0, 0.0, 0.0)
    return ('', [])


def build_lamp_floor(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    cyl = kit['add_cylinder']
    h, r = N('h', 1.6), N('r', 0.2)
    shade = min(0.30, h * 0.3)
    cyl(bm, r * 0.55, 0.03, 0.0, 24)
    cyl(bm, 0.018, h - shade, 0.03, 12)
    cyl(bm, r, shade, h - shade, 24, 0.0, 0.0, r * 0.7)
    return ('', [])


BUILDERS = {
    'bed_single': build_bed_single,
    'bed_double': build_bed_double,
    'wardrobe': build_wardrobe,
    'nightstand': build_nightstand,
    'sofa': build_sofa,
    'armchair': build_armchair,
    'coffee_table': build_coffee_table,
    'dining_table': build_dining_table,
    'chair': build_chair,
    'desk': build_desk,
    'bookcase': build_bookcase,
    'tv_unit': build_tv_unit,
    'rug': build_rug,
    'lamp_floor': build_lamp_floor,
}
