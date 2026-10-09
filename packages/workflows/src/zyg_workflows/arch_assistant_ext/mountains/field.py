# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains, the field: the shared value noise, the three lattices and the
six HEIGHTS functions the ground seam reads."""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    _num,
)


# ── the shared noise (identical in the JS and the Blender copies) ────────────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u: float, v: float, seed: float) -> float:
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def mountain_lattice(r: float = 60, h: float = 40, rug: float = 0.45, seed: float = 1, res: int = 48):
    """The normalised (res+1)^2 height lattice of a `mountain` record, and the
    scale factor that normalised it. Same arithmetic as AR_EXT.geom.mountain."""
    r = max(0.5, float(r))
    h = max(0.01, float(h))
    res = max(4, min(96, int(round(res))))
    rows = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            x = -r + i / res * 2 * r
            z = -r + j / res * 2 * r
            dist = math.sqrt(x * x + z * z)
            f = 0.0 if dist >= r else 0.5 * (1 + math.cos(math.pi * dist / r))
            v = f * (1 - rug * value_noise(i / res * 6, j / res * 6, seed))
            row.append(v if v > 0 else 0.0)
        rows.append(row)
    mx = max(max(row) for row in rows)
    s = h / mx if mx > 1e-9 else 0.0
    return [[v * s for v in row] for row in rows], s


def range_lattice(
    ln: float = 200, w: float = 80, h: float = 50, peaks: int = 4, rug: float = 0.45, seed: float = 1, res: int = 64
):
    """The normalised (res+1)^2 lattice of a `mountain_range` record, and its
    scale factor. Same arithmetic as AR_EXT.geom.mountain_range."""
    ln = max(1.0, float(ln))
    w = max(1.0, float(w))
    h = max(0.01, float(h))
    peaks = max(1, min(40, int(round(peaks))))
    res = max(4, min(96, int(round(res))))
    pk = [
        (-ln / 2 + (m + 0.5) * ln / peaks, peak_radius(ln, peaks), 1 + 0.5 * (_hash(m, 0, seed) - 0.5))
        for m in range(peaks)
    ]
    rows = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            x = -ln / 2 + i / res * ln
            z = -w / 2 + j / res * w
            base = 0.0
            for px, pr, ph in pk:
                dist = math.sqrt((x - px) ** 2 + z * z)
                if dist < pr:
                    f = ph * 0.5 * (1 + math.cos(math.pi * dist / pr))
                    if f > base:
                        base = f
            v = base * (1 - rug * value_noise(i / res * 6, j / res * 6, seed))
            row.append(v if v > 0 else 0.0)
        rows.append(row)
    mx = max(max(row) for row in rows)
    s = h / mx if mx > 1e-9 else 0.0
    return [[v * s for v in row] for row in rows], s


def ridge_crest(ln: float = 80, h: float = 15, rug: float = 0.3, seed: float = 1, res: int = 32) -> list:
    """The normalised crest profile of a `ridge` record, res+1 samples along its
    length. Same arithmetic as AR_EXT.geom.ridge."""
    res = max(2, min(96, int(round(res))))
    raw = []
    for i in range(res + 1):
        v = 1 - rug * value_noise(i / res * 6, 0.5, seed)
        raw.append(v if v > 0 else 0.0)
    mx = max(raw)
    s = h / mx if mx > 1e-9 else 0.0
    return [v * s for v in raw]


def peak_scale(r: float = 60, h: float = 40, rug: float = 0.45, seed: float = 1, res: int = 48) -> float:
    """h / max(raw lattice) — what the un-normalised mountain is multiplied by."""
    return mountain_lattice(r, h, rug, seed, res)[1]


def snow_ceiling(r: float = 60, h: float = 40, rug: float = 0.45, seed: float = 1, res: int = 48) -> float:
    """The highest triangle centroid of the lattice, as a fraction of h. A
    mountain with snow < this has a snow part; with snow > this it has none."""
    H, _ = mountain_lattice(r, h, rug, seed, res)
    res = max(4, min(96, int(round(res))))
    top = 0.0
    for j in range(res):
        for i in range(res):
            c1 = (H[j][i] + H[j + 1][i] + H[j][i + 1]) / 3
            c2 = (H[j][i + 1] + H[j + 1][i] + H[j + 1][i + 1]) / 3
            top = max(top, c1, c2)
    return top / max(1e-9, float(h))


def peak_radius(ln: float, peaks: int) -> float:
    """The plan radius each summit of a range stands on — 0.65 x len/peaks, the
    falloff radius AR_EXT.geom.mountain_range uses. It caps the range's height:
    a summit taller than its own radius is a needle, not a mountain."""
    return 0.65 * max(1.0, float(ln)) / max(1, int(round(peaks)))


# ── ground heights (the seam, 2026-09-07) ────────────────────────────────────
# fn(p, lx, lz) -> metres above the record's base at a LOCAL plan point, None
# outside the footprint. The lattice kinds interpolate the SAME lattice the
# geometry builds, so max(field) is the record's bounding-box height exactly.
_LAT_CACHE: dict = {}


def _cached(key, make):
    got = _LAT_CACHE.get(key)
    if got is None:
        if len(_LAT_CACHE) > 48:
            _LAT_CACHE.clear()
        got = make()
        _LAT_CACHE[key] = got
    return got


def _bilinear(H: list, res: int, u: float, v: float) -> float:
    """Sample a (res+1)^2 lattice at lattice coordinates u, v in 0..res."""
    i = int(math.floor(u))
    j = int(math.floor(v))
    i = 0 if i < 0 else (res - 1 if i > res - 1 else i)
    j = 0 if j < 0 else (res - 1 if j > res - 1 else j)
    fx = u - i
    fy = v - j
    fx = 0.0 if fx < 0 else (1.0 if fx > 1 else fx)
    fy = 0.0 if fy < 0 else (1.0 if fy > 1 else fy)
    a, b = H[j][i], H[j][i + 1]
    c, e = H[j + 1][i], H[j + 1][i + 1]
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def h_mountain(p, lx, lz):
    r = max(0.5, _num(p.get('r'), 60.0))
    if abs(lx) > r + 1e-9 or abs(lz) > r + 1e-9:
        return None
    h = max(0.01, _num(p.get('h'), 40.0))
    rug, seed = _num(p.get('rug'), 0.45), _num(p.get('seed'), 1)
    res = max(4, min(96, int(round(_num(p.get('res'), 48)))))
    H = _cached(('m', r, h, rug, seed, res), lambda: mountain_lattice(r, h, rug, seed, res)[0])
    return _bilinear(H, res, (lx + r) / (2 * r) * res, (lz + r) / (2 * r) * res)


def h_mountain_range(p, lx, lz):
    ln = max(1.0, _num(p.get('len'), 200.0))
    w = max(1.0, _num(p.get('w'), 80.0))
    if abs(lx) > ln / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    h = max(0.01, _num(p.get('h'), 50.0))
    peaks = max(1, min(40, int(round(_num(p.get('peaks'), 4)))))
    rug, seed = _num(p.get('rug'), 0.45), _num(p.get('seed'), 1)
    res = max(4, min(96, int(round(_num(p.get('res'), 64)))))
    H = _cached(('r', ln, w, h, peaks, rug, seed, res), lambda: range_lattice(ln, w, h, peaks, rug, seed, res)[0])
    return _bilinear(H, res, (lx + ln / 2) / ln * res, (lz + w / 2) / w * res)


def h_ridge(p, lx, lz):
    ln = max(0.5, _num(p.get('len'), 80.0))
    w = max(0.2, _num(p.get('w'), 20.0))
    if abs(lx) > ln / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    h = max(0.01, _num(p.get('h'), 15.0))
    rug, seed = _num(p.get('rug'), 0.3), _num(p.get('seed'), 1)
    res = max(2, min(96, int(round(_num(p.get('res'), 32)))))
    crest = _cached(('c', ln, h, rug, seed, res), lambda: ridge_crest(ln, h, rug, seed, res))
    u = (lx + ln / 2) / ln * res
    i = int(math.floor(u))
    i = 0 if i < 0 else (res - 1 if i > res - 1 else i)
    fx = u - i
    fx = 0.0 if fx < 0 else (1.0 if fx > 1 else fx)
    c = crest[i] + (crest[i + 1] - crest[i]) * fx
    return c * (1.0 - 2.0 * abs(lz) / w)  # triangular section: 0 at both feet


def h_volcano(p, lx, lz):
    r = max(0.5, _num(p.get('r'), 50.0))
    dist = math.hypot(lx, lz)
    if dist > r + 1e-9:
        return None
    h = max(0.05, _num(p.get('h'), 35.0))
    cr = max(0.05, min(_num(p.get('crater_r'), 10.0), 0.9 * r))
    cd = max(0.05, min(_num(p.get('crater_d'), 8.0), 0.9 * h))
    if dist >= cr:
        return h * (r - dist) / (r - cr)  # the flank: 0 at the foot, h at the rim
    return h - cd * 0.5 * (1 + math.cos(math.pi * dist / cr))  # the bowl inside the rim


def h_mesa(p, lx, lz):
    r = max(0.5, _num(p.get('r'), 40.0))
    dist = math.hypot(lx, lz)
    if dist > r + 1e-9:
        return None
    h = max(0.05, _num(p.get('h'), 25.0))
    tr = max(0.2, _num(p.get('top_r'), 30.0))
    rug, seed = _num(p.get('rug'), 0.25), _num(p.get('seed'), 1)
    seg = max(8, min(128, int(round(_num(p.get('seg'), 48)))))
    u = (math.atan2(lz, lx) % (2 * math.pi)) / (2 * math.pi) * seg
    i = int(math.floor(u)) % seg
    fx = u - math.floor(u)
    i2 = (i + 1) % seg
    t0 = tr * (1 - rug * value_noise(i / seg * 6, 0.5, seed))
    t1 = tr * (1 - rug * value_noise(i2 / seg * 6, 0.5, seed))
    e0 = 1 + 0.6 * value_noise(i / seg * 6, 3.5, seed)
    e1 = 1 + 0.6 * value_noise(i2 / seg * 6, 3.5, seed)
    top = t0 + (t1 - t0) * fx
    expo = max(0.05, e0 + (e1 - e0) * fx)
    if top >= r - 1e-9:
        return h
    if dist <= top:
        return h  # the flat table top
    q = (dist - r) / (top - r)  # 0 at the foot, 1 at the rim
    q = 0.0 if q < 0 else (1.0 if q > 1 else q)
    return h * (q ** (1.0 / expo))


def h_valley(p, lx, lz):
    w = max(1.0, _num(p.get('w'), 120.0))
    dd = max(1.0, _num(p.get('d'), 80.0))
    if abs(lx) > w / 2 + 1e-9 or abs(lz) > dd / 2 + 1e-9:
        return None
    h = max(0.01, _num(p.get('h'), 30.0))
    fw = max(0.0, min(_num(p.get('floor_w'), 20.0), w - 0.2))
    prof = int(round(_num(p.get('profile'), 0)))
    run = max(1e-6, w / 2 - fw / 2)
    t = (abs(lx) - fw / 2) / run
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return h * 0.5 * (1 - math.cos(math.pi * t)) if prof == 1 else h * t


HEIGHTS = {
    'mountain': h_mountain,
    'mountain_range': h_mountain_range,
    'ridge': h_ridge,
    'volcano': h_volcano,
    'mesa': h_mesa,
    'valley': h_valley,
}
