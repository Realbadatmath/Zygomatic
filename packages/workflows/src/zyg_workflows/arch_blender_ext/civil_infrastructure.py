# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""civil_infrastructure — Blender geometry for the civil-works kinds.

Local frame (see arch_blender_build.build_kind): X along the record's length,
Y = studio -Z (across), Z up, bottom at z=0. The sizes are the same contract
the tab's arch_ext/civil_infrastructure.js keeps: the bbox is exactly what the
parameters say.

tunnel and culvert are OPEN tubes (side faces only, no end caps) — you can see
through them, which is the whole point of a bore.
"""

import math


def _tube(bm, loop, x0, x1):
    """`loop` = a CLOSED profile [(across, up), ...] swept from X=x0 to X=x1."""
    n = len(loop)
    a = [bm.verts.new((x0, u, v)) for u, v in loop]
    b = [bm.verts.new((x1, u, v)) for u, v in loop]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.normal_update()


def _circle(r, cz, seg):
    return [(math.cos(2 * math.pi * i / seg) * r, cz + math.sin(2 * math.pi * i / seg) * r) for i in range(int(seg))]


def _tunnel_loop(w, h, t, seg):
    ro = w / 2.0
    ri = max(0.05, ro - t)
    zc = max(0.0, h - ro)
    pts = [(-ro, 0.0)]
    for i in range(seg + 1):
        a = math.pi * (1 - i / seg)
        pts.append((math.cos(a) * ro, zc + math.sin(a) * ro))
    pts.append((ro, 0.0))
    pts.append((ri, 0.0))
    for i in range(seg, -1, -1):
        a = math.pi * (1 - i / seg)
        pts.append((math.cos(a) * ri, zc + math.sin(a) * ri))
    pts.append((-ri, 0.0))
    return pts


def build_bridge_deck(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, t, e = N('len', 20.0), N('w', 8.0), N('t', 0.8), N('edge', 0.5)
    kit['add_box_c'](bm, L, w, t)
    if e > 0.01:
        kit['add_box_c'](bm, L, 0.3, e, cy=-(w / 2 - 0.15), z0=t)
        kit['add_box_c'](bm, L, 0.3, e, cy=(w / 2 - 0.15), z0=t)
    return ('', [])


def build_bridge_pier(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('w', 2.0), N('d', 6.0), N('h', 8.0))
    return ('', [])


def build_bridge_arch(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    span, rise, w, t = N('span', 20.0), N('rise', 5.0), N('w', 8.0), N('t', 1.0)
    seg = max(4, int(N('seg', 20)))
    outer, inner = [], []
    for i in range(seg + 1):
        x = -span / 2 + span * i / seg
        u = 2 * x / span
        y = rise * (1 - u * u)
        inner.append((x, y))
        outer.append((x, y + t))
    kit['add_prism'](bm, outer + list(reversed(inner)), 'y', -w / 2, w / 2)
    return ('', [])


def build_tunnel(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, t = N('len', 20.0), N('w', 8.0), N('t', 0.5)
    h = max(N('h', 6.0), w / 2 + 0.05)
    _tube(bm, _tunnel_loop(w, h, t, max(4, int(N('seg', 12)))), -L / 2, L / 2)
    return ('', [])


def build_culvert(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, r, t = N('len', 10.0), N('r', 1.0), N('t', 0.2)
    seg = max(6, int(N('seg', 24)))
    _tube(bm, _circle(r + t, r + t, seg), -L / 2, L / 2)
    _tube(bm, _circle(r, r + t, seg), -L / 2, L / 2)
    return ('', [])


def build_dam(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h, tb = N('len', 40.0), N('h', 20.0), N('t_base', 15.0)
    tt = min(N('t_top', 4.0), tb)
    kit['add_prism'](bm, [(-tb / 2, 0.0), (tb / 2, 0.0), (-tb / 2 + tt, h), (-tb / 2, h)], 'x', -L / 2, L / 2)
    return ('', [])


def build_quay_wall(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('len', 20.0), N('t', 1.2), N('h', 4.0))
    return ('', [])


def build_jetty(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, h = N('len', 12.0), N('w', 2.5), N('h', 1.5)
    sp = max(1.0, N('posts', 3.0))
    dt = min(0.2, h / 3)
    kit['add_box_c'](bm, L, w, dt, z0=h - dt)
    n = max(1, int(round(L / sp)))
    for i in range(n + 1):
        x = -L / 2 + L * i / n
        x = max(-L / 2 + 0.12, min(L / 2 - 0.12, x))
        for cy in (-(w / 2 - 0.2), (w / 2 - 0.2)):
            kit['add_cylinder'](bm, 0.12, h - dt, z0=0.0, seg=10, cx=x, cy=cy)
    return ('', [])


def build_embankment(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, h = N('len', 20.0), N('w', 9.0), N('h', 3.0)
    kit['add_prism'](bm, [(-w / 2, 0.0), (w / 2, 0.0), (0.0, h)], 'x', -L / 2, L / 2)
    return ('', [])


def build_sluice(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, t = N('w', 6.0), N('h', 5.0), N('t', 1.0)
    gh = min(N('gate_h', 3.0), h)
    kit['add_box_c'](bm, t, 2 * t, h, cx=-(w / 2 + t / 2))
    kit['add_box_c'](bm, t, 2 * t, h, cx=(w / 2 + t / 2))
    kit['add_box_c'](bm, w, t / 2, gh)
    return ('', [])


BUILDERS = {
    'bridge_deck': build_bridge_deck,
    'bridge_pier': build_bridge_pier,
    'bridge_arch': build_bridge_arch,
    'tunnel': build_tunnel,
    'culvert': build_culvert,
    'dam': build_dam,
    'quay_wall': build_quay_wall,
    'jetty': build_jetty,
    'embankment': build_embankment,
    'sluice': build_sluice,
}
