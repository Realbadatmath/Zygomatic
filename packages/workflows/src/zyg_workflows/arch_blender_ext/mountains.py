# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains — Blender geometry for mountain, mountain_range, ridge, volcano,
mesa and valley.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. A studio point (x, y, z) is therefore (x, -z, y) here, and a
studio plan angle theta is the ordinary counter-clockwise angle about Z.

The noise is the third copy of the contract in arch_ext/mountains.js and
arch_assistant_ext/mountains.py — the same arithmetic (itself a verbatim copy
of the terrain family's value_noise), so one record is the same mountain in the
tab, in the assistant and here.

Snow: faces whose centroid stands above snow*h take material_index 1, which the
builder fills with 'mat_snow'; everything else keeps the record's material.
The mesa's table top and the valley's soil floor strip use the same slot 1 for
'mat_grass' and 'mat_soil' — the two parts the tab returns with a `sub`.
"""

import math


def _hash(ix, iy, seed):
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u, v, seed):
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def _normalise(H, res, h):
    mx = max(max(row) for row in H)
    s = h / mx if mx > 1e-9 else 0.0
    for j in range(res + 1):
        for i in range(res + 1):
            H[j][i] *= s
    return s


def _lattice_faces(bm, verts, H, res, line):
    """Same triangle split as AR_EXT.geom: (a,c,b) and (b,c,e) per quad, snow
    where the centroid stands above `line`."""
    for j in range(res):
        for i in range(res):
            c1 = (H[j][i] + H[j + 1][i] + H[j][i + 1]) / 3
            c2 = (H[j][i + 1] + H[j + 1][i] + H[j + 1][i + 1]) / 3
            f = bm.faces.new((verts[j][i], verts[j + 1][i], verts[j][i + 1]))
            f.material_index = 1 if c1 > line else 0
            f = bm.faces.new((verts[j][i + 1], verts[j + 1][i], verts[j + 1][i + 1]))
            f.material_index = 1 if c2 > line else 0
    bm.normal_update()


def build_mountain(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(0.5, N('r', 60.0)), max(0.01, N('h', 40.0))
    rug, seed, snow = N('rug', 0.45), N('seed', 1.0), N('snow', 0.7)
    res = max(4, min(96, int(round(N('res', 48.0)))))
    H = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            x = -r + i / res * 2 * r
            sz = -r + j / res * 2 * r
            dist = math.sqrt(x * x + sz * sz)
            f = 0.0 if dist >= r else 0.5 * (1 + math.cos(math.pi * dist / r))
            v = f * (1 - rug * value_noise(i / res * 6, j / res * 6, seed))
            row.append(v if v > 0 else 0.0)
        H.append(row)
    _normalise(H, res, h)
    verts = [
        [bm.verts.new((-r + i / res * 2 * r, -(-r + j / res * 2 * r), H[j][i])) for i in range(res + 1)]
        for j in range(res + 1)
    ]
    _lattice_faces(bm, verts, H, res, snow * h)
    return ('', ['mat_snow'])


def build_mountain_range(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, w = max(1.0, N('len', 200.0)), max(1.0, N('w', 80.0))
    h = max(0.01, N('h', 50.0))
    peaks = max(1, min(40, int(round(N('peaks', 4.0)))))
    rug, seed, snow = N('rug', 0.45), N('seed', 1.0), N('snow', 0.75)
    res = max(4, min(96, int(round(N('res', 64.0)))))
    pk = [
        (-ln / 2 + (m + 0.5) * ln / peaks, 0.65 * ln / peaks, 1 + 0.5 * (_hash(m, 0, seed) - 0.5)) for m in range(peaks)
    ]
    H = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            x = -ln / 2 + i / res * ln
            sz = -w / 2 + j / res * w
            base = 0.0
            for px, pr, ph in pk:
                dist = math.sqrt((x - px) ** 2 + sz * sz)
                if dist < pr:
                    f = ph * 0.5 * (1 + math.cos(math.pi * dist / pr))
                    if f > base:
                        base = f
            v = base * (1 - rug * value_noise(i / res * 6, j / res * 6, seed))
            row.append(v if v > 0 else 0.0)
        H.append(row)
    _normalise(H, res, h)
    verts = [
        [bm.verts.new((-ln / 2 + i / res * ln, -(-w / 2 + j / res * w), H[j][i])) for i in range(res + 1)]
        for j in range(res + 1)
    ]
    _lattice_faces(bm, verts, H, res, snow * h)
    return ('', ['mat_snow'])


def build_ridge(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, w = max(0.5, N('len', 80.0)), max(0.2, N('w', 20.0))
    h, rug, seed = max(0.01, N('h', 15.0)), N('rug', 0.3), N('seed', 1.0)
    res = max(2, min(96, int(round(N('res', 32.0)))))
    raw = []
    for i in range(res + 1):
        v = 1 - rug * value_noise(i / res * 6, 0.5, seed)
        raw.append(v if v > 0 else 0.0)
    mx = max(raw)
    s = h / mx if mx > 1e-9 else 0.0
    L, C, R = [], [], []
    for i in range(res + 1):
        x = -ln / 2 + i / res * ln
        L.append(bm.verts.new((x, w / 2, 0.0)))  # studio z = -w/2
        C.append(bm.verts.new((x, 0.0, raw[i] * s)))
        R.append(bm.verts.new((x, -w / 2, 0.0)))  # studio z = +w/2
    for i in range(res):
        bm.faces.new((L[i], C[i], C[i + 1], L[i + 1]))
        bm.faces.new((R[i], R[i + 1], C[i + 1], C[i]))
        bm.faces.new((L[i], L[i + 1], R[i + 1], R[i]))
    bm.faces.new((L[0], C[0], R[0]))
    bm.faces.new((R[res], C[res], L[res]))
    bm.normal_update()
    return ('', [])


def build_volcano(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(0.5, N('r', 50.0)), max(0.05, N('h', 35.0))
    cr = max(0.05, min(N('crater_r', 10.0), 0.9 * r))
    cd = max(0.05, min(N('crater_d', 8.0), 0.9 * h))
    seg = max(8, min(128, int(round(N('seg', 48.0)))))
    rings = max(2, min(48, int(round(N('rings', 16.0)))))
    crings = max(3, int(round(rings / 2)))
    out = []
    for k in range(rings + 1):
        t = k / rings
        rad, z = r + (cr - r) * t, h * t
        out.append(
            [
                bm.verts.new((math.cos(2 * math.pi * i / seg) * rad, -math.sin(2 * math.pi * i / seg) * rad, z))
                for i in range(seg)
            ]
        )
    crater = [out[rings]]
    for m in range(1, crings):
        crad = cr * (1 - m / crings)
        cz = h - cd * 0.5 * (1 + math.cos(math.pi * crad / cr))
        crater.append(
            [
                bm.verts.new((math.cos(2 * math.pi * i / seg) * crad, -math.sin(2 * math.pi * i / seg) * crad, cz))
                for i in range(seg)
            ]
        )
    bot = bm.verts.new((0.0, 0.0, h - cd))
    base = bm.verts.new((0.0, 0.0, 0.0))
    for k in range(rings):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((out[k][i], out[k + 1][i], out[k + 1][j], out[k][j]))
    for m in range(crings - 1):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((crater[m][i], crater[m + 1][i], crater[m + 1][j], crater[m][j]))
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((crater[-1][i], bot, crater[-1][j]))
        bm.faces.new((base, out[0][i], out[0][j]))
    bm.normal_update()
    return ('', [])


def build_mesa(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(0.5, N('r', 40.0)), max(0.05, N('h', 25.0))
    tr, rug, seed = max(0.2, N('top_r', 30.0)), N('rug', 0.25), N('seed', 1.0)
    seg = max(8, min(128, int(round(N('seg', 48.0)))))
    rings = 8
    top = [tr * (1 - rug * value_noise(i / seg * 6, 0.5, seed)) for i in range(seg)]
    expo = [1 + 0.6 * value_noise(i / seg * 6, 3.5, seed) for i in range(seg)]
    ring = []
    for k in range(rings + 1):
        t, z = k / rings, h * k / rings
        row = []
        for i in range(seg):
            an = 2 * math.pi * i / seg
            rad = r + (top[i] - r) * (t ** expo[i])
            row.append(bm.verts.new((math.cos(an) * rad, -math.sin(an) * rad, z)))
        ring.append(row)
    apex = bm.verts.new((0.0, 0.0, h))
    base = bm.verts.new((0.0, 0.0, 0.0))
    for k in range(rings):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((ring[k][i], ring[k + 1][i], ring[k + 1][j], ring[k][j]))
    for i in range(seg):
        j = (i + 1) % seg
        f = bm.faces.new((apex, ring[rings][j], ring[rings][i]))
        f.material_index = 1  # the table top is grass
        bm.faces.new((base, ring[0][i], ring[0][j]))
    bm.normal_update()
    return ('', ['mat_grass'])


def build_valley(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d = max(1.0, N('w', 120.0)), max(1.0, N('d', 80.0))
    h = max(0.01, N('h', 30.0))
    fw = max(0.0, min(N('floor_w', 20.0), w - 0.2))
    prof = int(round(N('profile', 0.0)))
    res = max(4, min(96, int(round(N('res', 32.0)))))
    run = max(1e-6, w / 2 - fw / 2)
    col = []
    for i in range(res + 1):
        x = -w / 2 + i / res * w
        t = (abs(x) - fw / 2) / run
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        col.append(h * 0.5 * (1 - math.cos(math.pi * t)) if prof == 1 else h * t)
    rows = []
    for j in range(res + 1):
        sz = -d / 2 + j / res * d
        rows.append([bm.verts.new((-w / 2 + i / res * w, -sz, col[i])) for i in range(res + 1)])
    for j in range(res):
        for i in range(res):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    # the sides are the record's material (grass by default); the floor the river
    # runs on is a soil strip floor_w wide, 20 mm over the flat floor so it does
    # not z-fight. Inside the trough, so the bounding box is unchanged.
    if fw > 0.05:
        fz, hw, hd = 0.02, fw / 2, d / 2
        strip = [
            bm.verts.new((-hw, hd, fz)),
            bm.verts.new((hw, hd, fz)),
            bm.verts.new((hw, -hd, fz)),
            bm.verts.new((-hw, -hd, fz)),
        ]
        f = bm.faces.new(strip)
        f.material_index = 1
    bm.normal_update()
    return ('', ['mat_soil'])


BUILDERS = {
    'mountain': build_mountain,
    'mountain_range': build_mountain_range,
    'ridge': build_ridge,
    'volcano': build_volcano,
    'mesa': build_mesa,
    'valley': build_valley,
}
