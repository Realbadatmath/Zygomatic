# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""balconies_facade — Blender geometry for the facade-mounted kinds.

Local frame (see arch_blender_build.build_kind): X along the wall, Y = the
studio's -Z (so Y is the OUTWARD projection depth: the assistant has already
turned the record's ry so that studio-local -Z points away from the building),
Z up, bottom at z=0. Every kind here therefore grows in +Y — except
parapet_cap, which straddles the wall centred on Y=0.
"""

import math


def build_balcony(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, dd, t, rh, ps = N('w', 2.4), N('d', 1.2), N('t', 0.18), N('rail_h', 1.0), N('post', 0.04)
    box(bm, w, dd, t, 0.0, dd / 2, 0.0)  # the projecting slab
    top, bar = t + rh, ps * 1.4
    xin = w / 2 - ps / 2
    n = max(2, int(round(w / 0.6)) + 1)
    for i in range(n):
        box(bm, ps, ps, rh, -xin + 2 * xin * i / (n - 1), dd - ps / 2, t)  # outer balusters
    box(bm, ps, ps, rh, -xin, ps / 2, t)  # the returns at the wall
    box(bm, ps, ps, rh, xin, ps / 2, t)
    box(bm, w, bar, bar, 0.0, dd - bar / 2, top - bar)  # hand rail, three sides
    box(bm, bar, dd, bar, -(w / 2 - bar / 2), dd / 2, top - bar)
    box(bm, bar, dd, bar, (w / 2 - bar / 2), dd / 2, top - bar)
    return ('', [])


def build_canopy(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, dd, t, hd = N('w', 3.0), N('d', 1.5), N('t', 0.12), N('h_drop', 0.0)
    kit['add_prism'](bm, [(0.0, 0.0), (dd, -hd), (dd, t - hd), (0.0, t)], 'x', -w / 2, w / 2)
    return ('', [])


def build_awning(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, dd, ang, t = N('w', 3.0), N('d', 1.2), N('angle', 20.0), 0.04
    drop = dd * math.tan(math.radians(max(0.0, min(70.0, ang))))
    kit['add_prism'](bm, [(0.0, -t), (dd, -drop - t), (dd, -drop), (0.0, 0.0)], 'x', -w / 2, w / 2)
    return ('', [])


def build_cornice(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    L, h, dd = N('len', 4.0), N('h', 0.3), N('d', 0.25)
    box(bm, L, dd, h * 0.7, 0.0, dd / 2, 0.0)
    box(bm, L, dd * 0.7, h * 0.3, 0.0, dd * 0.35, h * 0.7)
    return ('', [])


def build_pilaster(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, w, dd = N('h', 2.7), N('w', 0.4), N('d', 0.12)
    kit['add_box_c'](bm, w, dd, h, 0.0, dd / 2, 0.0)
    return ('', [])


def build_louvre_fins(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, fin = N('w', 3.0), N('h', 2.7), N('fin', 0.3)
    sp, t = max(0.05, N('spacing', 0.4)), N('t', 0.03)
    n = max(2, int(round(w / sp)) + 1)
    for i in range(n):
        kit['add_box_c'](bm, t, fin, h, -w / 2 + t / 2 + (w - t) * i / (n - 1), fin / 2, 0.0)
    return ('', [])


def build_sunshade(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    box = kit['add_box_c']
    w, dd, t = N('w', 3.0), N('d', 0.8), N('t', 0.05)
    sl = max(2, int(round(N('slats', 8))))
    db = (dd / sl) * 0.7
    for i in range(sl):
        box(bm, w, db, t, 0.0, db / 2 + (dd - db) * i / (sl - 1), 0.0)
    box(bm, t, dd, t, -(w / 2 - t / 2), dd / 2, 0.0)
    box(bm, t, dd, t, (w / 2 - t / 2), dd / 2, 0.0)
    return ('', [])


def build_string_course(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h, dd = N('len', 4.0), N('h', 0.12), N('d', 0.08)
    kit['add_box_c'](bm, L, dd, h, 0.0, dd / 2, 0.0)
    return ('', [])


def build_parapet_cap(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, t = N('len', 4.0), N('w', 0.3), N('t', 0.06)
    kit['add_box_c'](bm, L, w, t, 0.0, 0.0, 0.0)  # straddles the wall
    return ('', [])


BUILDERS = {
    'balcony': build_balcony,
    'canopy': build_canopy,
    'awning': build_awning,
    'cornice': build_cornice,
    'pilaster': build_pilaster,
    'louvre_fins': build_louvre_fins,
    'sunshade': build_sunshade,
    'string_course': build_string_course,
    'parapet_cap': build_parapet_cap,
}
