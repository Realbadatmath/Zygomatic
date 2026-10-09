# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""roofs_advanced — Blender geometry for the ten advanced roof kinds.

Local frame (see arch_blender_build.build_kind): X along (the studio's w), Y =
studio -Z (the depth d), Z up, bottom at z=0. kit['add_prism'](bm, profile,
axis, a0, a1) mirrors arPrismG in the tab: with axis 'x' the profile is (Y, Z)
— the section ACROSS the depth — swept from X=a0 to X=a1, which is exactly what
`arPrismG(profile, w+2*over)` + `rotateY(PI/2)` does there. roof_sawtooth's
teeth run along X, so its profile is (X, Z) swept along Y.

Butterfly and sawtooth are several convex prisms, not one concave profile —
bmesh.faces.new needs a planar convex ring, the same reason the tab splits them.
"""

import math

# the onion's silhouette as (radius factor, height factor); widest ring = 1.0
ONION = [(0.72, 0.00), (0.90, 0.12), (1.00, 0.30), (0.93, 0.50), (0.72, 0.68), (0.44, 0.83), (0.18, 0.93), (0.00, 1.00)]


def _revolve(bm, prof, seg=48, mi=0):
    """Surface of revolution about Z through `prof` = [(radius, z), ...] from
    bottom to top; a radius of 0 becomes a single apex vertex. The bottom ring
    is capped so the solid is closed."""
    rings = []
    for r, z in prof:
        if r <= 1e-6:
            rings.append([bm.verts.new((0.0, 0.0, z))])
        else:
            rings.append(
                [
                    bm.verts.new((r * math.cos(2 * math.pi * i / seg), r * math.sin(2 * math.pi * i / seg), z))
                    for i in range(seg)
                ]
            )
    faces = []
    for k in range(len(rings) - 1):
        a, b = rings[k], rings[k + 1]
        for i in range(seg):
            j = (i + 1) % seg
            if len(b) == 1:
                faces.append(bm.faces.new((a[i], a[j], b[0])))
            elif len(a) == 1:
                faces.append(bm.faces.new((a[0], b[j], b[i])))
            else:
                faces.append(bm.faces.new((a[i], a[j], b[j], b[i])))
    if len(rings[0]) > 1:
        faces.append(bm.faces.new(list(reversed(rings[0]))))
    for f in faces:
        f.material_index = mi


def _tent(bm, verts, faces, mi=0):
    v = [bm.verts.new(pt) for pt in verts]
    for idx in faces:
        f = bm.faces.new([v[i] for i in idx])
        f.material_index = mi


def build_roof_mansard(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 8), N('d', 6), N('h', 3), N('over', 0.4)
    br = min(0.9, max(0.1, N('break', 0.6)))
    De, yb = d / 2 + o, h * min(0.9, max(0.1, br))
    Db, Dr = De * 0.72, De * 0.16
    kit['add_prism'](bm, [(-De, 0.0), (De, 0.0), (Db, yb), (Dr, h), (-Dr, h), (-Db, yb)], 'x', -(w / 2 + o), w / 2 + o)
    return ('', [])


def build_roof_gambrel(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 8), N('d', 6), N('h', 3), N('over', 0.4)
    br = min(0.9, max(0.1, N('break', 0.6)))
    De, yb = d / 2 + o, h * br
    Db = De * 0.55
    kit['add_prism'](bm, [(-De, 0.0), (De, 0.0), (Db, yb), (0.0, h), (-Db, yb)], 'x', -(w / 2 + o), w / 2 + o)
    return ('', [])


def build_roof_butterfly(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 8), N('d', 6), N('h', 1.2), N('over', 0.4)
    De = d / 2 + o
    t = min(0.2, max(0.02, h * 0.35))
    x0, x1 = -(w / 2 + o), w / 2 + o
    kit['add_prism'](bm, [(-De, h - t), (0.0, 0.0), (0.0, t), (-De, h)], 'x', x0, x1)
    kit['add_prism'](bm, [(0.0, 0.0), (De, h - t), (De, h), (0.0, t)], 'x', x0, x1)
    return ('', [])


def build_roof_sawtooth(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 12), N('d', 8), N('h', 1.8)
    nb = max(1, int(round(N('bays', 4))))
    bw, x0 = w / nb, -w / 2
    low = min(0.1, h * 0.1)
    for i in range(nb):
        xa, xb = x0 + bw * i, x0 + bw * (i + 1)
        kit['add_prism'](bm, [(xa, 0.0), (xb, 0.0), (xb, h), (xa, low)], 'y', -d / 2, d / 2)
    return ('', [])


def build_roof_pyramid(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 6), N('d', 6), N('h', 3), N('over', 0.4)
    W, D = w / 2 + o, d / 2 + o
    _tent(
        bm,
        [(-W, -D, 0.0), (W, -D, 0.0), (W, D, 0.0), (-W, D, 0.0), (0.0, 0.0, h)],
        [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 3, 2, 1)],
    )
    return ('', [])


def build_roof_half_hip(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 8), N('d', 6), N('h', 2.8), N('over', 0.4)
    clip = min(1.0, max(0.0, N('clip', 0.5)))
    W, D = w / 2 + o, d / 2 + o
    rxh = max(0.001, W - D)
    rx = W - clip * (W - rxh)  # clip 0 = gable, clip 1 = full hip
    _tent(
        bm,
        [(-W, -D, 0.0), (W, -D, 0.0), (W, D, 0.0), (-W, D, 0.0), (-rx, 0.0, h), (rx, 0.0, h)],
        [(0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4), (0, 3, 2, 1)],
    )
    return ('', [])


def build_roof_curved(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h, o = N('w', 8), N('d', 6), N('h', 2), N('over', 0.3)
    D = d / 2 + o
    arc = []
    for i in range(29):
        t = -1 + 2 * i / 28
        arc.append((D * t, h * math.sqrt(max(0.0, 1 - t * t))))
    kit['add_prism'](bm, arc, 'x', -(w / 2 + o), w / 2 + o)
    return ('', [])


def build_roof_cone(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, o = N('r', 3), N('h', 3), N('over', 0.3)
    _revolve(bm, [(max(0.05, r + o), 0.0), (0.0, h)], 48)
    return ('', [])


def build_roof_onion(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, sp = N('r', 2.5), N('h', 3.5), max(0.0, N('spire', 2))
    _revolve(bm, [(fr * r, fh * h) for fr, fh in ONION], 48)
    if sp > 0.01:
        _revolve(bm, [(max(0.02, r * 0.08), h), (0.0, h + sp)], 16)
    return ('', [])


def build_roof_skylight_strip(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = N('w', 8), N('d', 6), N('h', 0.3)
    gt = min(0.08, h * 0.5)
    kit['add_box_c'](bm, w, d, h)
    kit['add_box_c'](bm, w * 0.8, d * 0.3, gt, z0=h - gt, mi=1)
    return ('', ['mat_glass'])


BUILDERS = {
    'roof_mansard': build_roof_mansard,
    'roof_gambrel': build_roof_gambrel,
    'roof_butterfly': build_roof_butterfly,
    'roof_sawtooth': build_roof_sawtooth,
    'roof_pyramid': build_roof_pyramid,
    'roof_half_hip': build_roof_half_hip,
    'roof_curved': build_roof_curved,
    'roof_cone': build_roof_cone,
    'roof_onion': build_roof_onion,
    'roof_skylight_strip': build_roof_skylight_strip,
}
