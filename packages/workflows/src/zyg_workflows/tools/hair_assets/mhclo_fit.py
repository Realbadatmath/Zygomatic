# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mhclo_fit.py — place a MakeHuman asset on the base mesh the way MakeHuman does.

A MakeHuman hair .obj is NOT modelled in the base mesh's space. Read literally
it lands anywhere: bob01's crown sits 4 cm BELOW hm08's scalp and short01's
1 cm above it, which on the clay head came out as a bob over the face and a
crew cut hovering like a hat. The .obj is raw modelling data, and the .mhclo
beside it is what says where each vertex goes:

    v0 v1 v2  w0 w1 w2  d0 d1 d2

one line per asset vertex — three base-mesh vertices, barycentric weights, and
an offset along the base's own axes. The fitted point is

    w0*B[v0] + w1*B[v1] + w2*B[v2] + (d0*sx, d1*sy, d2*sz)

with sx, sy, sz taken from the x_scale / y_scale / z_scale reference pairs: the
distance between two named base vertices on THIS base, over the distance the
author recorded. Fitting to the same default hm08 they were authored against
puts those ratios at ~1, and the same code fits a reshaped body later.

The hair binds to hm08's `helper-hair` vertices (index 18762 upward), which is
why the helper cage has to be in the base mesh that is read here even though
the head is MEASURED from the body group alone."""

from __future__ import annotations

import os


def read_obj(path):
    """(vertex lines as float triples, all lines) — order preserved."""
    V, lines = [], []
    with open(path, 'r', errors='replace') as fh:
        for ln in fh:
            lines.append(ln)
            if ln.startswith('v '):
                p = ln.split()
                V.append([float(p[1]), float(p[2]), float(p[3])])
    return V, lines


def parse_mhclo(path):
    """{'scales': {'x': (i, j, d), ...}, 'verts': [ ... ]}"""
    out = {'scales': {}, 'verts': [], 'obj_file': '', 'material': ''}
    in_verts = False
    with open(path, 'r', errors='replace') as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith('#'):
                continue
            p = s.split()
            k = p[0].lower()
            if k in ('x_scale', 'y_scale', 'z_scale') and len(p) >= 4:
                out['scales'][k[0]] = (int(p[1]), int(p[2]), float(p[3]))
                continue
            if k == 'obj_file':
                out['obj_file'] = p[1]
                continue
            if k == 'material':
                out['material'] = p[1]
                continue
            if k == 'verts':
                in_verts = True
                continue
            if not in_verts:
                continue
            try:
                if len(p) >= 9:
                    out['verts'].append(
                        (
                            int(p[0]),
                            int(p[1]),
                            int(p[2]),
                            float(p[3]),
                            float(p[4]),
                            float(p[5]),
                            float(p[6]),
                            float(p[7]),
                            float(p[8]),
                        )
                    )
                elif len(p) == 1:
                    out['verts'].append((int(p[0]),))
                else:
                    in_verts = False
            except ValueError:
                in_verts = False
    return out


def scale_factors(clo, base):
    """(sx, sy, sz) for this base mesh, one per axis."""
    out = []
    for axis, i in (('x', 0), ('y', 1), ('z', 2)):
        ref = clo['scales'].get(axis)
        if not ref or ref[2] == 0:
            out.append(1.0)
            continue
        a, b, d = ref
        if a >= len(base) or b >= len(base):
            out.append(1.0)
            continue
        out.append(abs(base[a][i] - base[b][i]) / d)
    return tuple(out)


def fit(clo, base):
    """Fitted asset vertices, in the base mesh's own space."""
    sx, sy, sz = scale_factors(clo, base)
    n = len(base)
    out = []
    for rec in clo['verts']:
        if len(rec) == 1:
            i = rec[0]
            out.append(list(base[i]) if 0 <= i < n else [0.0, 0.0, 0.0])
            continue
        v0, v1, v2, w0, w1, w2, d0, d1, d2 = rec
        if not (0 <= v0 < n and 0 <= v1 < n and 0 <= v2 < n):
            out.append([0.0, 0.0, 0.0])
            continue
        a, b, c = base[v0], base[v1], base[v2]
        out.append(
            [
                a[0] * w0 + b[0] * w1 + c[0] * w2 + d0 * sx,
                a[1] * w0 + b[1] * w1 + c[1] * w2 + d1 * sy,
                a[2] * w0 + b[2] * w1 + c[2] * w2 + d2 * sz,
            ]
        )
    return out, (sx, sy, sz)


def write_fitted_obj(src_obj, fitted, dst_obj):
    """The asset's own .obj with its vertex lines replaced by fitted ones.

    Rewriting the file rather than pushing coordinates into an imported mesh
    keeps faces, UVs and groups exactly as the vendor wrote them, and makes no
    assumption about whether the importer preserves vertex order."""
    _V, lines = read_obj(src_obj)
    if len(_V) != len(fitted):
        return None, f'{len(_V)} obj verts vs {len(fitted)} mhclo verts'
    it = iter(fitted)
    out = []
    for ln in lines:
        if ln.startswith('v '):
            x, y, z = next(it)
            out.append(f'v {x:.6f} {y:.6f} {z:.6f}\n')
        else:
            out.append(ln)
    os.makedirs(os.path.dirname(dst_obj), exist_ok=True)
    with open(dst_obj, 'w') as fh:
        fh.writelines(out)
    return dst_obj, None
