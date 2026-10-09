# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""water_leisure — Blender geometry for the water and leisure kinds.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom normally at z=0. The basins are the exception: pool,
canal, pond and sandpit dig, so their meshes reach BELOW z=0, exactly as the
tab's arGeom does — unless a pool is `raised` (a rooftop pool standing on its
deck), when the whole basin is lifted by that much. `_box` translates a studio box (w, h, d) centred at
(x, y, z) into that frame so the two engines stay literally line for line.
"""

import math


def _box(kit, bm, w, h, dp, x, y, z, mi=0):
    kit['add_box_c'](bm, max(w, 1e-4), max(dp, 1e-4), max(h, 1e-4), cx=x, cy=-z, z0=y - max(h, 1e-4) / 2, mi=mi)


def _cyl(kit, bm, r, h, z0, seg=24, r_top=None, mi=0):
    kit['add_cylinder'](
        bm,
        max(r, 1e-4),
        max(h, 1e-4),
        z0=z0,
        seg=max(6, int(seg)),
        r_top=(None if r_top is None else max(r_top, 0.0)),
        mi=mi,
    )


def _dish(kit, bm, rx, rz, h, z0, seg=32, shrink=1.0, mi=0):
    """A cone of unit top radius squashed to rx by rz — the tab's dish()."""
    vs = kit['add_cylinder'](bm, max(shrink, 0.05), max(h, 1e-4), z0=z0, seg=max(8, int(seg)), r_top=1.0, mi=mi)
    kit['bmesh'].ops.scale(bm, verts=vs, vec=(max(rx, 0.05), max(rz, 0.05), 1.0))


# The two bank bands, identical to BANK_TOP in arch_ext/water_leisure.js: the top
# 30 % of a bank is turf (mat_grass), what is under it is the bed (mat_soil).
BANK_TOP = 0.30
WATER_MATS = ['mat_soil', 'mat_grass', 'mat_water']  # slots 1, 2, 3
# A pool's sub-materials, the same order the tab's `sub` names them: the water
# surface and the glass weir of an infinity edge (2026-09-08).
POOL_MATS = ['mat_water', 'mat_glass']  # slots 1, 2


# ── water ───────────────────────────────────────────────────────────────────
def build_pool(bm, p, kit):
    """Line for line the tab's AR_EXT.geom.pool: floor 0.2 thick from
    raised-depth, walls 0.2 thick from raised-depth to raised+coping, water at
    raised-0.1; the p.inf side ('n'|'s'|'e'|'w') is a glass weir that stops at
    the water level, with a 0.5 x 0.4 catch trough outside it from raised-0.5
    to raised-0.1. raised 0 and no inf is the old sunk basin, unchanged."""
    N = lambda k, d: kit['num'](p, k, d)
    w, d = max(0.4, N('w', 8)), max(0.4, N('d', 4))
    dep, cop = max(0.2, N('depth', 1.5)), max(0.0, N('coping', 0.4))
    R = max(0.0, N('raised', 0))
    inf = str(p.get('inf') or '').lower()[:1]
    if inf not in ('n', 's', 'e', 'w'):
        inf = ''
    t, H = 0.2, max(0.2, N('depth', 1.5)) + max(0.0, N('coping', 0.4))
    yc = R + (cop - dep) / 2
    Hw = max(0.05, dep - 0.1)
    yw = R - dep + Hw / 2
    dw = max(0.05, d - 2 * t)
    _box(kit, bm, w, t, d, 0, R - dep + t / 2, 0)
    if inf == 'n':
        _box(kit, bm, w, Hw, t, 0, yw, -(d / 2 - t / 2), mi=2)
    else:
        _box(kit, bm, w, H, t, 0, yc, -(d / 2 - t / 2))
    if inf == 's':
        _box(kit, bm, w, Hw, t, 0, yw, (d / 2 - t / 2), mi=2)
    else:
        _box(kit, bm, w, H, t, 0, yc, (d / 2 - t / 2))
    if inf == 'w':
        _box(kit, bm, t, Hw, dw, -(w / 2 - t / 2), yw, 0, mi=2)
    else:
        _box(kit, bm, t, H, dw, -(w / 2 - t / 2), yc, 0)
    if inf == 'e':
        _box(kit, bm, t, Hw, dw, (w / 2 - t / 2), yw, 0, mi=2)
    else:
        _box(kit, bm, t, H, dw, (w / 2 - t / 2), yc, 0)
    _box(kit, bm, max(0.05, w - 2 * t), 0.04, dw, 0, R - 0.1, 0, mi=1)
    if inf == 'n':
        _box(kit, bm, w, 0.4, 0.5, 0, R - 0.3, -(d / 2 + 0.25))
    elif inf == 's':
        _box(kit, bm, w, 0.4, 0.5, 0, R - 0.3, (d / 2 + 0.25))
    elif inf == 'w':
        _box(kit, bm, 0.5, 0.4, d, -(w / 2 + 0.25), R - 0.3, 0)
    elif inf == 'e':
        _box(kit, bm, 0.5, 0.4, d, (w / 2 + 0.25), R - 0.3, 0)
    # entry steps (2026-09-12): p.steps is the side they descend from, never the
    # weir; n treads of 0.3 rise / 0.35 run from the inner wall face, standing on
    # the basin floor — line for line the tab's AR_EXT.geom.pool.
    st = str(p.get('steps') or '').lower()[:1]
    if st in ('n', 's', 'e', 'w') and st != inf:
        n = max(1, min(5, int(math.floor((dep - 0.15) / 0.3))))
        run = 0.35
        side = w if st in ('n', 's') else d
        sw = max(0.4, min(2.4, side - 2 * t - 0.4))
        y0 = R - dep + t
        for i in range(n):
            top = R - 0.1 - 0.3 * (i + 1)
            hh = max(0.03, top - y0)
            ex = run * (i + 1)
            yc = y0 + hh / 2
            if st == 'n':
                _box(kit, bm, sw, hh, ex, 0, yc, -(d / 2 - t) + ex / 2)
            elif st == 's':
                _box(kit, bm, sw, hh, ex, 0, yc, (d / 2 - t) - ex / 2)
            elif st == 'w':
                _box(kit, bm, ex, hh, sw, -(w / 2 - t) + ex / 2, yc, 0)
            else:
                _box(kit, bm, ex, hh, sw, (w / 2 - t) - ex / 2, yc, 0)
    return ('', list(POOL_MATS))


def build_pond(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    rx, rz, dep = N('rx', 4), N('rz', 3), max(0.15, N('depth', 0.6))
    # the cone runs 0.72 r at the bed to 1.00 r at the rim: at the split, s
    s = 0.72 + 0.28 * (1 - BANK_TOP)
    _dish(kit, bm, rx * s, rz * s, dep * (1 - BANK_TOP), -dep, 32, 0.72 / s, mi=1)
    _dish(kit, bm, rx, rz, dep * BANK_TOP, -dep * BANK_TOP, 32, s, mi=2)
    _dish(kit, bm, max(0.1, rx - 0.15), max(0.1, rz - 0.15), 0.03, -0.12, 32, 1.0, mi=3)
    return ('', list(WATER_MATS))


def build_canal(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, dep = max(0.5, N('len', 20)), max(0.4, N('w', 6)), max(0.2, N('depth', 1.5))
    t, H = 0.3, dep + 0.1
    hb = H * BANK_TOP
    hq = H - hb
    _box(kit, bm, L, t, w, 0, -dep + t / 2, 0, mi=1)
    _box(kit, bm, L, hq, t, 0, -dep + hq / 2, -(w / 2 - t / 2))
    _box(kit, bm, L, hq, t, 0, -dep + hq / 2, (w / 2 - t / 2))
    _box(kit, bm, L, hb, t, 0, -dep + hq + hb / 2, -(w / 2 - t / 2), mi=2)
    _box(kit, bm, L, hb, t, 0, -dep + hq + hb / 2, (w / 2 - t / 2), mi=2)
    _box(kit, bm, L, 0.04, max(0.05, w - 2 * t), 0, -0.1, 0, mi=3)
    return ('', list(WATER_MATS))


def build_fountain(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r = max(0.4, N('r', 2))
    n = max(1, int(round(N('tiers', 3))))
    h = max(1.0, N('h', 2.5))
    _cyl(kit, bm, r, 0.45, 0, 32)
    _cyl(kit, bm, max(0.1, r - 0.12), 0.02, 0.34, 32)
    _cyl(kit, bm, max(0.06, r * 0.10), h, 0, 16)
    for i in range(n):
        f = (i + 1) / n
        yy = 0.45 + (h - 0.75) * f
        rr = max(0.15, r * (0.62 - 0.40 * i / n))
        _cyl(kit, bm, rr, 0.10, yy, 24)
        _cyl(kit, bm, max(0.06, rr - 0.05), 0.02, yy + 0.10, 24)
    return ('', [])


# ── play ────────────────────────────────────────────────────────────────────
def build_playground_slide(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, L, w = max(0.6, N('h', 2)), max(1.2, N('l', 4)), max(0.25, N('w', 0.6))
    x0 = -L / 2
    profile = [(x0 + 0.08, h), (L / 2, 0.12), (L / 2, 0.02), (x0 + 0.08, h - 0.10)]
    kit['add_prism'](bm, profile, 'y', -w / 2, w / 2)
    _box(kit, bm, 0.08, h, 0.08, x0 + 0.04, h / 2, -(w / 2 - 0.04))
    _box(kit, bm, 0.08, h, 0.08, x0 + 0.04, h / 2, (w / 2 - 0.04))
    rungs = max(2, int(round(h / 0.35)))
    for i in range(1, rungs + 1):
        _box(kit, bm, 0.06, 0.05, w - 0.16, x0 + 0.04, h * i / (rungs + 1), 0)
    return ('', [])


def build_swing(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h = max(0.8, N('w', 3)), max(0.8, N('h', 2.4))
    n = max(1, int(round(N('seats', 2))))
    _box(kit, bm, w, 0.12, 0.12, 0, h - 0.06, 0)
    _box(kit, bm, 0.12, h, 0.12, -(w / 2 - 0.06), h / 2, 0)
    _box(kit, bm, 0.12, h, 0.12, (w / 2 - 0.06), h / 2, 0)
    for i in range(n):
        cx = -w / 2 + w * (i + 1) / (n + 1)
        sy = min(0.45, h * 0.22)
        _box(kit, bm, 0.04, h - 0.12 - sy, 0.04, cx - 0.18, (h - 0.12 + sy) / 2, 0)
        _box(kit, bm, 0.04, h - 0.12 - sy, 0.04, cx + 0.18, (h - 0.12 + sy) / 2, 0)
        _box(kit, bm, 0.45, 0.05, 0.35, cx, sy, 0)
    return ('', [])


def build_sandpit(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, t = max(0.6, N('w', 4)), max(0.6, N('d', 4)), max(0.05, N('t', 0.3))
    b, H = 0.2, t + 0.25
    yc = (0.25 - t) / 2
    _box(kit, bm, w - 2 * b, t, d - 2 * b, 0, -t / 2, 0)
    _box(kit, bm, w, H, b, 0, yc, -(d / 2 - b / 2))
    _box(kit, bm, w, H, b, 0, yc, (d / 2 - b / 2))
    _box(kit, bm, b, H, d - 2 * b, -(w / 2 - b / 2), yc, 0)
    _box(kit, bm, b, H, d - 2 * b, (w / 2 - b / 2), yc, 0)
    return ('', [])


# ── sport ───────────────────────────────────────────────────────────────────
def build_sports_court(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, ln = max(2, N('w', 28)), max(2, N('d', 15)), N('lines', 1)
    _box(kit, bm, w, 0.10, d, 0, 0.05, 0)
    if ln > 0.5:
        m = min(0.5, min(w, d) * 0.05)
        t, y = 0.12, 0.105
        W, D = w - 2 * m, d - 2 * m
        _box(kit, bm, W, 0.012, t, 0, y, -(D / 2))
        _box(kit, bm, W, 0.012, t, 0, y, (D / 2))
        _box(kit, bm, t, 0.012, D, -(W / 2), y, 0)
        _box(kit, bm, t, 0.012, D, (W / 2), y, 0)
        _box(kit, bm, t, 0.012, D, 0, y, 0)
    return ('', [])


def build_goal_posts(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, d = max(0.8, N('w', 7.32)), max(0.5, N('h', 2.44)), max(0.3, N('d', 2))
    _box(kit, bm, 0.12, h, 0.12, -(w / 2 - 0.06), h / 2, 0.06)
    _box(kit, bm, 0.12, h, 0.12, (w / 2 - 0.06), h / 2, 0.06)
    _box(kit, bm, w, 0.12, 0.12, 0, h - 0.06, 0.06)
    _box(kit, bm, 0.10, h * 0.45, 0.10, -(w / 2 - 0.05), h * 0.225, d - 0.05)
    _box(kit, bm, 0.10, h * 0.45, 0.10, (w / 2 - 0.05), h * 0.225, d - 0.05)
    _box(kit, bm, w, 0.10, 0.10, 0, 0.05, d - 0.05)
    _box(kit, bm, w - 0.24, 0.02, d - 0.12, 0, h * 0.72, d / 2)
    return ('', [])


def build_tennis_net(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h = max(1.0, N('w', 12.8)), max(0.3, N('h', 1.07))
    _box(kit, bm, 0.10, h, 0.10, -(w / 2 - 0.05), h / 2, 0)
    _box(kit, bm, 0.10, h, 0.10, (w / 2 - 0.05), h / 2, 0)
    _box(kit, bm, w - 0.20, h - 0.08, 0.03, 0, (h - 0.08) / 2, 0)
    _box(kit, bm, w - 0.20, 0.06, 0.04, 0, h - 0.03, 0)
    return ('', [])


# ── poolside ────────────────────────────────────────────────────────────────
def build_sun_lounger(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, h = max(0.6, N('l', 1.9)), max(0.3, N('w', 0.7)), max(0.15, N('h', 0.4))
    xs = (-(L / 2 - 0.08), (L / 2 - 0.08))
    zs = (-(w / 2 - 0.08), (w / 2 - 0.08))
    _box(kit, bm, L, 0.10, w, 0, h - 0.05, 0)
    _box(kit, bm, L * 0.34, 0.06, w - 0.10, -(L / 2 - L * 0.17), h - 0.13, 0)
    for i in range(4):
        _box(kit, bm, 0.06, h - 0.10, 0.06, xs[i % 2], (h - 0.10) / 2, zs[0 if i < 2 else 1])
    return ('', [])


def build_umbrella(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h = max(0.3, N('r', 1.5)), max(0.8, N('h', 2.3))
    _cyl(kit, bm, 0.035, h, 0, 16)
    _cyl(kit, bm, r, 0.50, h - 0.50, 20, r_top=0.0)
    _cyl(kit, bm, 0.09, 0.10, h - 0.60, 12)
    return ('', [])


BUILDERS = {
    'pool': build_pool,
    'pond': build_pond,
    'canal': build_canal,
    'fountain': build_fountain,
    'playground_slide': build_playground_slide,
    'swing': build_swing,
    'sandpit': build_sandpit,
    'sports_court': build_sports_court,
    'goal_posts': build_goal_posts,
    'tennis_net': build_tennis_net,
    'sun_lounger': build_sun_lounger,
    'umbrella': build_umbrella,
}
