# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""headframe.py — the head frame of a body mesh, measured the SAME way
char_hair.js measures it (headMetrics): headH = 0.13 * total height, the head
band is everything above the chin, and the forward axis is the sign of the nose.

A groom is stored relative to this frame, so fitting it to another body is a
translate + uniform scale and never a guess."""

import sys


def read_obj_verts(path, only_groups=None):
    """Vertices of an OBJ; with only_groups, only those a face in one of those
    groups uses.

    MakeHuman's hm08 base mesh is 19,158 vertices of which about a third are
    the HELPER cage and the joint cubes: a loose shell that stands well clear
    of the body so clothes can be fitted to it. Measured whole, its crown sits
    about 1 unit above the real scalp, and every groom fitted to that frame
    floats above the head. The body group is the body."""
    V, want, used = [], None, set()
    if only_groups is not None:
        want = {str(g).lower() for g in only_groups}
    cur = None
    with open(path, 'r', errors='replace') as fh:
        for ln in fh:
            if ln.startswith('v '):
                p = ln.split()
                V.append((float(p[1]), float(p[2]), float(p[3])))
            elif want is not None and ln.startswith('g '):
                cur = ln[2:].strip().lower()
            elif want is not None and ln.startswith('f ') and cur in want:
                for tok in ln.split()[1:]:
                    i = int(tok.split('/')[0])
                    used.add(i - 1 if i > 0 else len(V) + i)
    if want is None:
        return V
    return [V[i] for i in sorted(used) if 0 <= i < len(V)]


def head_frame(V):
    ys = [p[1] for p in V]
    yTop, minY = max(ys), min(ys)
    H = yTop - minY
    headH = 0.13 * H
    chinY = yTop - headH
    band = [p for p in V if p[1] > chinY]
    if not band:
        return None
    xs = [p[0] for p in band]
    zs = [p[2] for p in band]
    xmin, xmax, zmin, zmax = min(xs), max(xs), min(zs), max(zs)
    headW = max(1e-4, xmax - xmin)
    cx = (xmin + xmax) * 0.5
    zc = (zmin + zmax) * 0.5
    browY = yTop - 0.42 * headH
    pos = neg = 0.0
    for x, y, z in V:
        if y < chinY + 0.22 * headH or y > browY:
            continue
        if abs(x - cx) > 0.10 * headW:
            continue
        d = z - zc
        if d > pos:
            pos = d
        if d < neg:
            neg = d
    fwd = 1 if pos >= -neg else -1
    fmin, fmax = float('inf'), float('-inf')
    for _x, y, z in V:
        if y <= chinY:
            continue
        f = fwd * (z - zc)
        if f < fmin:
            fmin = f
        if f > fmax:
            fmax = f
    return {
        'yTop': yTop,
        'minY': minY,
        'H': H,
        'headH': headH,
        'headW': headW,
        'cx': cx,
        'zc': zc,
        'fwd': fwd,
        'chinY': chinY,
        'fmin': fmin,
        'fmax': fmax,
        'depth': max(1e-4, fmax - fmin),
        'verts': len(V),
    }


if __name__ == '__main__':
    import json

    for p in sys.argv[1:]:
        f = head_frame(read_obj_verts(p))
        print(p)
        print(' ', json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()}))
