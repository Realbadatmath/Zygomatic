# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""plan_solver — generate a dwelling plan from a room programme.

No new kinds: this family writes PLAN JSON (the pack schema every floor-plan
task reads and writes) into the `generated` pack under the plans directory,
and hands the id to `place_plan` (arch_assistant_ext/floor_plans.py) which
draws it.

The generator is a guillotine subdivision with a randomised search: a hall
band runs inward from the entrance, rooms sit in one or two rows either side
of it, and the far end of the plan holds the living room (plus up to two
neighbours). 300 candidates are laid out per call, the ones that break a hard
constraint are dropped, and the best-scoring survivor is emitted. The score is
the mean relative area error against the swiss_dwellings medians (scaled to
the unit), less a small bonus for the adjacencies that pack reports most often
and for bedrooms far from the front door.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import random
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


ASPECT = 2.6
TOUCH = 0.9  # shortest shared edge a door may sit in
WIN_W = 1.2
WIN_SILL = 0.9
WIN_H = 1.4

MIN_W = {
    'living': 3.2,
    'kitchen': 2.2,
    'bedroom': 2.7,
    'bathroom': 1.7,
    'wc': 1.1,
    'hall': 1.1,
    'corridor': 1.1,
    'storage': 1.1,
    'balcony': 1.2,
    'other': 1.1,
}
HABITABLE = ('living', 'kitchen', 'bedroom')
DOOR_W = {'bathroom': 0.8, 'wc': 0.8, 'storage': 0.8}
SIDES = ('north', 'south', 'east', 'west')

# medians of the swiss_dwellings pack — used only when stats.json is absent
FALLBACK_MEDIAN = {
    'living': 23.983,
    'kitchen': 8.127,
    'bedroom': 13.781,
    'bathroom': 3.718,
    'hall': 7.501,
    'storage': 2.171,
    'balcony': 7.471,
    'wc': 1.7,
    'corridor': 7.501,
    'other': 6.0,
}
FALLBACK_ADJ = {
    'bedroom|hall': 49601,
    'bathroom|hall': 41234,
    'hall|living': 23932,
    'hall|kitchen': 19203,
    'kitchen|living': 10993,
    'hall|storage': 8188,
}

HOUSE_ROOMS = ['hall', 'living', 'kitchen', 'bedroom', 'bedroom', 'bedroom', 'bathroom', 'wc', 'storage']

_STATS_CACHE: dict = {}


# ── paths ─────────────────────────────────────────────────────────────────────
def plans_root() -> str:
    """The plan-pack root — ZYG_PLANS_DIR when set, else data/architecture/plans."""
    return os.environ.get('ZYG_PLANS_DIR') or paths.ZYG_PLANS_DIR


def pack_dir() -> str:
    return os.path.join(plans_root(), 'generated')


def stats() -> dict:
    """swiss_dwellings stats.json (room medians, adjacency), cached per path."""
    p = os.path.join(plans_root(), 'swiss_dwellings', 'stats.json')
    if p in _STATS_CACHE:
        return _STATS_CACHE[p]
    st = {'rooms': {}, 'adjacency': dict(FALLBACK_ADJ)}
    try:
        with open(p) as fh:
            st = json.load(fh)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('swiss_dwellings stats unreadable, using the fallback adjacency: %s', _exc)
    _STATS_CACHE[p] = st
    return st


def median_area(kind: str) -> float:
    r = (stats().get('rooms') or {}).get(kind) or {}
    v = (r.get('area') or {}).get('median')
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    return FALLBACK_MEDIAN.get(kind, 6.0)


def default_rooms(area: float) -> list:
    """The room programme the pack's size classes report for a unit this big."""
    if area < 50:
        return ['hall', 'living', 'kitchen', 'bathroom']
    if area < 80:
        return ['hall', 'living', 'kitchen', 'bedroom', 'bathroom']
    if area < 120:
        return ['hall', 'living', 'kitchen', 'bedroom', 'bedroom', 'bathroom', 'storage']
    return list(HOUSE_ROOMS)


def _minw(t: str) -> float:
    return MIN_W.get(t, 1.1)


# ── rectangle helpers (plan frame: +x east, +z south) ─────────────────────────
def _shared(r1: dict, r2: dict):
    """The segment two room rectangles share, or None.

    Returns (axis, coord, lo, hi): axis 'x' = a vertical line at x = coord
    spanning z in [lo, hi]; axis 'z' = a horizontal line at z = coord."""
    for a, b in ((r1, r2), (r2, r1)):
        if abs(a['x1'] - b['x0']) < 1e-6:
            lo, hi = max(a['z0'], b['z0']), min(a['z1'], b['z1'])
            if hi - lo > 1e-6:
                return ('x', a['x1'], lo, hi)
        if abs(a['z1'] - b['z0']) < 1e-6:
            lo, hi = max(a['x0'], b['x0']), min(a['x1'], b['x1'])
            if hi - lo > 1e-6:
                return ('z', a['z1'], lo, hi)
    return None


def _ext_edges(r: dict, w: float, d: float) -> list:
    """The room's edges that lie on the outer boundary: (side, axis, coord, lo, hi)."""
    out = []
    if abs(r['z0']) < 1e-6:
        out.append(('north', 'z', 0.0, r['x0'], r['x1']))
    if abs(r['z1'] - d) < 1e-6:
        out.append(('south', 'z', d, r['x0'], r['x1']))
    if abs(r['x0']) < 1e-6:
        out.append(('west', 'x', 0.0, r['z0'], r['z1']))
    if abs(r['x1'] - w) < 1e-6:
        out.append(('east', 'x', w, r['z0'], r['z1']))
    return out


def _lens(types: list, total: float, width: float, targets: dict):
    """Leaf lengths along a row of the given cross `width`, summing to `total`.

    Every leaf gets at least its type's minimum width and at least
    width/ASPECT, and at most width*ASPECT, so the aspect and min-width hard
    constraints hold by construction. The slack is shared out in proportion to
    how much more each type wants to reach its target area."""
    n = len(types)
    if n == 0:
        return []
    lo = [max(_minw(t), width / ASPECT) for t in types]
    hi = [width * ASPECT for _ in types]
    if sum(lo) > total + 1e-9 or sum(hi) < total - 1e-9:
        return None
    out = list(lo)
    extra = total - sum(lo)
    want = [max(0.02, targets.get(t, 6.0) / width - lo[i]) for i, t in enumerate(types)]
    for _ in range(12):
        if extra <= 1e-9:
            break
        act = [i for i in range(n) if hi[i] - out[i] > 1e-9]
        if not act:
            break
        sw = sum(want[i] for i in act)
        moved = 0.0
        for i in act:
            share = extra * (want[i] / sw if sw > 1e-9 else 1.0 / len(act))
            g = min(share, hi[i] - out[i])
            out[i] += g
            moved += g
        extra -= moved
        if moved <= 1e-12:
            break
    if extra > 1e-6:
        return None
    return out


# ── the search ────────────────────────────────────────────────────────────────
def _uv_to_xz(u0, u1, v0, v1, w, d, entrance):
    """A rectangle in the hall frame (u = inward from the entrance edge,
    v = across it) as x0/x1/z0/z1 in the plan frame."""
    if entrance == 'north':
        return v0, v1, u0, u1
    if entrance == 'south':
        return v0, v1, d - u1, d - u0
    if entrance == 'west':
        return u0, u1, v0, v1
    return w - u1, w - u0, v0, v1  # east


def _candidate(rng, w, d, prog, entrance, targets):
    """One randomised guillotine layout, or None when the draw is infeasible."""
    across_z = entrance in ('north', 'south')
    LU, LV = (d, w) if across_z else (w, d)
    hw = rng.uniform(1.2, 1.8)
    if LV - hw < 1.1:
        return None
    others = [t for t in prog if t != 'hall']
    if not others:
        return None
    rng.shuffle(others)
    n_end = rng.choice([0, 1, 1, 2, 2, 3])
    end_types, rest, hl = [], others, LU
    if n_end:
        if 'living' not in others:
            return None
        pool = [t for t in others if t != 'living']
        if len(pool) < n_end - 1:
            return None
        end_types = ['living'] + pool[: n_end - 1]
        rest = pool[n_end - 1 :]
        hl = rng.uniform(0.28, 0.78) * LU
        if LU - hl < 3.2 or hl < 1.6:
            return None
    if not rest:
        return None

    k = rng.randint(0, len(rest))
    rows = [rest[:k], rest[k:]]
    need = [max([_minw(t) for t in r], default=0.0) for r in rows]
    avail = LV - hw
    if rows[0] and rows[1]:
        if need[0] + need[1] > avail:
            return None
        a = rng.uniform(need[0], avail - need[1])
    elif rows[0]:
        a = avail
    elif rows[1]:
        a = 0.0
    else:
        return None
    b = avail - a
    if (rows[0] and a < need[0] - 1e-9) or (rows[1] and b < need[1] - 1e-9):
        return None

    rects = []

    def add(t, u0, u1, v0, v1):
        x0, x1, z0, z1 = _uv_to_xz(u0, u1, v0, v1, w, d, entrance)
        rects.append(
            {
                'type': t,
                'x0': round(x0, 3),
                'x1': round(x1, 3),
                'z0': round(z0, 3),
                'z1': round(z1, 3),
                'u': 0.5 * (u0 + u1) / LU,
            }
        )

    add('hall', 0.0, hl, a, a + hw)
    for row, v_lo, v_hi in ((rows[0], 0.0, a), (rows[1], a + hw, LV)):
        if not row:
            continue
        lens = _lens(row, hl, v_hi - v_lo, targets)
        if lens is None:
            return None
        u = 0.0
        for t, ln in zip(row, lens):
            add(t, u, u + ln, v_lo, v_hi)
            u += ln
    if end_types:
        depth = LU - hl
        best = None
        for i in range(len(end_types)):
            order = list(end_types[1:])
            order.insert(i, 'living')
            lens = _lens(order, LV, depth, targets)
            if lens is None:
                continue
            v = 0.0
            span = None
            for t, ln in zip(order, lens):
                if t == 'living':
                    span = (v, v + ln)
                v += ln
            ov = min(span[1], a + hw) - max(span[0], a)
            if ov >= TOUCH:
                best = (order, lens)
                break
        if best is None:
            return None
        v = 0.0
        for t, ln in zip(best[0], best[1]):
            add(t, hl, LU, v, v + ln)
            v += ln
    for r in rects:
        r['area'] = round((r['x1'] - r['x0']) * (r['z1'] - r['z0']), 4)
    return rects


def _candidate_t(rng, w, d, prog, entrance, targets):
    """A T-shaped hall: a short leg in from the front door, then an arm across
    the whole plan. Front pockets either side of the leg and a back row all open
    onto the arm, so wide shallow plans (which a straight spine cannot serve)
    still give every room a hall edge and an outside wall."""
    across_z = entrance in ('north', 'south')
    LU, LV = (d, w) if across_z else (w, d)
    hw = rng.uniform(1.2, 1.8)  # the arm's depth
    hl = rng.uniform(1.2, max(1.3, 0.4 * LU))  # the leg's depth
    hwl = rng.uniform(1.2, 1.8)  # the leg's width
    back_d = LU - hl - hw
    if back_d < 3.2 or LV - hwl < 1.2:
        return None
    others = [t for t in prog if t != 'hall']
    if 'living' not in others:
        return None
    rng.shuffle(others)
    pool = [t for t in others if t != 'living']
    nb = rng.randint(0, min(len(pool), 4))
    back = ['living'] + pool[:nb]
    rng.shuffle(back)
    rest = pool[nb:]
    k = rng.randint(0, len(rest))
    left, right = rest[:k], rest[k:]
    avail = LV - hwl
    if left and right:
        lo_l = sum(max(_minw(t), hl / ASPECT) for t in left)
        lo_r = sum(max(_minw(t), hl / ASPECT) for t in right)
        if lo_l + lo_r > avail:
            return None
        v0 = rng.uniform(lo_l, avail - lo_r)
    elif left:
        v0 = avail
    elif right:
        v0 = 0.0
    else:
        v0 = rng.uniform(0.0, avail)

    rects = []

    def add(t, u0, u1, v0_, v1_, **kw):
        x0, x1, z0, z1 = _uv_to_xz(u0, u1, v0_, v1_, w, d, entrance)
        r = {
            'type': t,
            'x0': round(x0, 3),
            'x1': round(x1, 3),
            'z0': round(z0, 3),
            'z1': round(z1, 3),
            'u': 0.5 * (u0 + u1) / LU,
        }
        r.update(kw)
        rects.append(r)

    poly_uv = [(v0, 0.0), (v0 + hwl, 0.0), (v0 + hwl, hl), (LV, hl), (LV, hl + hw), (0.0, hl + hw), (0.0, hl), (v0, hl)]
    poly = []
    for v, u in poly_uv:
        x0, _x1, z0, _z1 = _uv_to_xz(u, u, v, v, w, d, entrance)
        p = [round(x0, 3), round(z0, 3)]
        if not poly or p != poly[-1]:
            poly.append(p)
    if len(poly) > 1 and poly[0] == poly[-1]:
        poly.pop()
    add('hall', 0.0, hl, v0, v0 + hwl, poly=poly, front=True)
    add('hall', hl, hl + hw, 0.0, LV, skip_room=True)
    for row, v_lo, v_hi in ((left, 0.0, v0), (right, v0 + hwl, LV)):
        if not row:
            continue
        lens = _lens(row, v_hi - v_lo, hl, targets)
        if lens is None:
            return None
        v = v_lo
        for t, ln in zip(row, lens):
            add(t, 0.0, hl, v, v + ln)
            v += ln
    lens = _lens(back, LV, back_d, targets)
    if lens is None:
        return None
    v = 0.0
    for t, ln in zip(back, lens):
        add(t, hl + hw, LU, v, v + ln)
        v += ln
    for r in rects:
        r['area'] = round((r['x1'] - r['x0']) * (r['z1'] - r['z0']), 4)
    return rects


def _room_areas(rects: list) -> list:
    """(type, area) per emitted room — the hall's two T parts count once."""
    out, hall = [], 0.0
    for r in rects:
        if r['type'] == 'hall':
            hall += r['area']
        else:
            out.append((r['type'], r['area']))
    if hall:
        out.append(('hall', hall))
    return out


def _doors_of(rects: list):
    """{room index -> (host index, shared segment)} with every door on an edge
    the room shares with the hall or the living room, or None when some room
    cannot be reached from the hall that way."""
    hall = [i for i, r in enumerate(rects) if r['type'] == 'hall']
    if not hall:
        return None
    out = {}
    for i, r in enumerate(rects):
        if r['type'] == 'hall':
            continue
        best = None
        for j, o in enumerate(rects):
            if i == j or o['type'] not in ('hall', 'living'):
                continue
            sh = _shared(r, o)
            if sh and sh[3] - sh[2] >= TOUCH:
                rank = (0 if o['type'] == 'hall' else 1, -(sh[3] - sh[2]))
                if best is None or rank < best[0]:
                    best = (rank, j, sh)
        if best is None:
            return None
        out[i] = (best[1], best[2])
    seen, stack = set(hall), list(hall)
    while stack:
        cur = stack.pop()
        for i, (host, _sh) in out.items():
            if host == cur and i not in seen:
                seen.add(i)
                stack.append(i)
    if len(seen) != len(rects):
        return None
    return out


def _hard_ok(rects, w, d, doors):
    for r in rects:
        dx, dz = r['x1'] - r['x0'], r['z1'] - r['z0']
        if min(dx, dz) < _minw(r['type']) - 1e-6:
            return False
        if r['type'] != 'hall' and max(dx, dz) > ASPECT * min(dx, dz) + 1e-6:
            return False
        if r['type'] in HABITABLE:
            if max([hi - lo for _s, _a, _c, lo, hi in _ext_edges(r, w, d)], default=0.0) < WIN_W:
                return False
    ks = [r for r in rects if r['type'] == 'kitchen']
    lv = [r for r in rects if r['type'] == 'living']
    for kr in ks:
        if lv and not any(_shared(kr, lr) and _shared(kr, lr)[3] - _shared(kr, lr)[2] >= TOUCH for lr in lv):
            return False
    return doors is not None


def _score(rects, targets, adj):
    err = sorted(abs(a - targets.get(t, 6.0)) / max(0.5, targets.get(t, 6.0)) for t, a in _room_areas(rects))
    n = len(err)
    med = err[n // 2] if n % 2 else 0.5 * (err[n // 2 - 1] + err[n // 2])
    # the median is the headline term; the mean only breaks ties between
    # candidates whose medians match.
    s = med + 0.05 * sum(err) / n
    top = max(adj.values()) if adj else 1.0
    bonus = 0.0
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            sh = _shared(rects[i], rects[j])
            if sh and sh[3] - sh[2] >= TOUCH:
                key = '|'.join(sorted((rects[i]['type'], rects[j]['type'])))
                bonus += adj.get(key, 0) / top
    # soft preferences, deliberately small: a good adjacency map must never buy
    # its way past a worse fit to the stats medians.
    s -= 0.06 * bonus / len(rects)
    beds = [r['u'] for r in rects if r['type'] == 'bedroom']
    if beds:
        s -= 0.04 * sum(beds) / len(beds)
    return s


# ── emitting the plan ─────────────────────────────────────────────────────────
def _merge(iv: list) -> list:
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _walls(polys, w, d):
    """Boundary walls (t 0.24, ext) then the deduped internal cut lines (t 0.1),
    taken from the edges of the emitted room polygons."""
    walls = [
        {'a': [0.0, 0.0], 'b': [round(w, 3), 0.0], 't': 0.24, 'ext': True},
        {'a': [round(w, 3), 0.0], 'b': [round(w, 3), round(d, 3)], 't': 0.24, 'ext': True},
        {'a': [round(w, 3), round(d, 3)], 'b': [0.0, round(d, 3)], 't': 0.24, 'ext': True},
        {'a': [0.0, round(d, 3)], 'b': [0.0, 0.0], 't': 0.24, 'ext': True},
    ]
    lines: dict = {}
    for pts in polys:
        for i, (ax, az) in enumerate(pts):
            bx, bz = pts[(i + 1) % len(pts)]
            if abs(ax - bx) < 1e-6 and 1e-6 < ax < w - 1e-6:
                lines.setdefault(('x', round(ax, 3)), []).append(sorted([az, bz]))
            elif abs(az - bz) < 1e-6 and 1e-6 < az < d - 1e-6:
                lines.setdefault(('z', round(az, 3)), []).append(sorted([ax, bx]))
    for (axis, c), iv in sorted(lines.items()):
        for lo, hi in _merge(iv):
            if axis == 'x':
                walls.append({'a': [c, round(lo, 3)], 'b': [c, round(hi, 3)], 't': 0.1, 'ext': False})
            else:
                walls.append({'a': [round(lo, 3), c], 'b': [round(hi, 3), c], 't': 0.1, 'ext': False})
    return walls


def _wall_at(walls, x, z) -> int:
    for i, wl in enumerate(walls):
        (ax, az), (bx, bz) = wl['a'], wl['b']
        if abs(ax - bx) < 1e-6 and abs(x - ax) < 0.02:
            if min(az, bz) - 0.02 <= z <= max(az, bz) + 0.02:
                return i
        if abs(az - bz) < 1e-6 and abs(z - az) < 0.02:
            if min(ax, bx) - 0.02 <= x <= max(ax, bx) + 0.02:
                return i
    return 0


def _spread(lo, hi, n, width):
    """n window centres along [lo, hi], evenly, none closer than 0.2 to an end."""
    span = hi - lo
    n = max(1, min(n, int((span - 0.2) // (width + 0.3)) or 1))
    step = span / n
    return [lo + step * (i + 0.5) for i in range(n)]


def _emit(rects, w, d, entrance, storey_h, doors, plan_id, kind):
    hall_area = sum(r['area'] for r in rects if r['type'] == 'hall')
    rooms, out_doors, out_win, out_fix = [], [], [], []
    for r in rects:
        if r.get('skip_room'):
            continue
        pts = r.get('poly') or [
            [round(r['x0'], 3), round(r['z0'], 3)],
            [round(r['x1'], 3), round(r['z0'], 3)],
            [round(r['x1'], 3), round(r['z1'], 3)],
            [round(r['x0'], 3), round(r['z1'], 3)],
        ]
        rooms.append(
            {
                'type': r['type'],
                'pts': pts,
                'area': round(hall_area if r['type'] == 'hall' else r['area'], 3),
                'name': r['type'].capitalize(),
            }
        )
    walls = _walls([r['pts'] for r in rooms], w, d)
    for i, (_host, sh) in sorted(doors.items()):
        axis, c, lo, hi = sh
        mid = 0.5 * (lo + hi)
        x, z = (c, mid) if axis == 'x' else (mid, c)
        out_doors.append(
            {
                'x': round(x, 3),
                'z': round(z, 3),
                'w': DOOR_W.get(rects[i]['type'], 0.9),
                'wall': _wall_at(walls, x, z),
                'kind': 'door',
            }
        )
    # the front door: the middle of the hall's edge on the entrance side
    halls = [r for r in rects if r['type'] == 'hall']
    hall = next((r for r in halls if r.get('front')), halls[0])
    side = {'north': ('z', 0.0), 'south': ('z', d), 'west': ('x', 0.0), 'east': ('x', w)}[entrance]
    if side[0] == 'z':
        ex, ez = 0.5 * (hall['x0'] + hall['x1']), side[1]
    else:
        ex, ez = side[1], 0.5 * (hall['z0'] + hall['z1'])
    out_doors.append(
        {'x': round(ex, 3), 'z': round(ez, 3), 'w': 0.95, 'wall': _wall_at(walls, ex, ez), 'kind': 'entrance'}
    )
    ent = {'side': entrance, 'x': round(ex, 3), 'z': round(ez, 3)}

    for r in rects:
        if r['type'] not in HABITABLE and r['type'] != 'bathroom':
            continue
        ww = WIN_W if r['type'] in HABITABLE else 0.6
        for _s, axis, c, lo, hi in _ext_edges(r, w, d):
            if hi - lo < ww + 0.2:
                continue
            n = max(1, int((hi - lo) // 4)) if r['type'] in HABITABLE else 1
            for t in _spread(lo, hi, n, ww):
                x, z = (c, t) if axis == 'x' else (t, c)
                out_win.append(
                    {
                        'x': round(x, 3),
                        'z': round(z, 3),
                        'w': ww,
                        'wall': _wall_at(walls, x, z),
                        'sill': WIN_SILL,
                        'h': WIN_H,
                    }
                )
            if r['type'] == 'bathroom':
                break

    for r in rects:
        if r['type'] in ('bathroom', 'wc'):
            dx, dz = r['x1'] - r['x0'], r['z1'] - r['z0']
            along_x = dx >= dz
            span = dx if along_x else dz
            fix = ['toilet', 'washbasin']
            if r['type'] == 'bathroom' and r['area'] >= 4.0:
                fix.append('bathtub' if r['area'] >= 5.5 else 'shower')
            for n, kindf in enumerate(fix):
                t = (n + 0.5) / len(fix) * span
                if along_x:
                    x, z = r['x0'] + t, r['z0'] + min(0.45, dz / 3.0)
                else:
                    x, z = r['x0'] + min(0.45, dx / 3.0), r['z0'] + t
                out_fix.append(
                    {'kind': kindf, 'x': round(x, 3), 'z': round(z, 3), 'ry': 0.0 if along_x else round(math.pi / 2, 4)}
                )
        if r['type'] == 'kitchen':
            best = None
            for axis, c, lo, hi, inward in (
                ('x', r['x0'], r['z0'], r['z1'], 1),
                ('x', r['x1'], r['z0'], r['z1'], -1),
                ('z', r['z0'], r['x0'], r['x1'], 1),
                ('z', r['z1'], r['x0'], r['x1'], -1),
            ):
                on_edge = abs(c) < 1e-6 or abs(c - (w if axis == 'x' else d)) < 1e-6
                if on_edge:
                    continue
                if best is None or hi - lo > best[2] - best[1]:
                    best = (axis, lo, hi, c, inward)
            if best:
                axis, lo, hi, c, inward = best
                t = 0.5 * (lo + hi)
                if axis == 'x':
                    x, z = c + 0.3 * inward, t
                    ry = round(math.pi / 2, 4)
                else:
                    x, z = t, c + 0.3 * inward
                    ry = 0.0
                out_fix.append({'kind': 'kitchen', 'x': round(x, 3), 'z': round(z, 3), 'ry': ry})

    area = round(sum(r['area'] for r in rects), 3)
    return {
        'id': plan_id,
        'pack': 'generated',
        'kind': kind,
        'w': round(w, 3),
        'd': round(d, 3),
        'area': area,
        'storey_h': round(storey_h, 3),
        'boundary': [[0.0, 0.0], [round(w, 3), 0.0], [round(w, 3), round(d, 3)], [0.0, round(d, 3)]],
        'rooms': rooms,
        'walls': walls,
        'doors': out_doors,
        'windows': out_win,
        'fixtures': out_fix,
        'entrance': ent,
        'core': {'stairs': [], 'lifts': []},
        'units': [],
        'source': {'generator': 'plan_solver', 'stats': 'swiss_dwellings'},
        'mirror_ok': True,
    }


def _plan_id(w, d, rooms, entrance, seed, kind) -> str:
    key = json.dumps([round(float(w), 3), round(float(d), 3), list(rooms), entrance, int(seed), kind], sort_keys=True)
    return 'gen_' + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]


def generate_unit(w, d, rooms=None, entrance='north', seed=0, storey_h=2.7, kind='unit', candidates=300) -> dict:
    """A dwelling plan in the pack schema, laid out inside a w x d rectangle."""
    w, d = float(w), float(d)
    if entrance not in SIDES:
        raise ValueError('entrance must be one of ' + ', '.join(SIDES))
    if w < 4.0 or d < 4.0:
        raise ValueError('a unit needs at least 4 x 4 m')
    prog = list(rooms) if rooms else default_rooms(w * d)
    if 'hall' not in prog:
        prog = ['hall'] + prog
    scale = (w * d) / max(1e-6, sum(median_area(t) for t in prog))
    targets = {t: median_area(t) * scale for t in set(prog)}
    adj = {k: v for k, v in (stats().get('adjacency') or FALLBACK_ADJ).items()}
    rng = random.Random(_plan_id(w, d, prog, entrance, seed, kind))
    best, best_s = None, None
    for n in range(int(candidates)):
        maker = _candidate if n % 2 == 0 else _candidate_t
        rects = maker(rng, w, d, prog, entrance, targets)
        if rects is None:
            continue
        doors = _doors_of(rects)
        if not _hard_ok(rects, w, d, doors):
            continue
        s = _score(rects, targets, adj)
        if best_s is None or s < best_s:
            best, best_s = (rects, doors), s
    if best is None:
        raise ValueError(
            f'no layout satisfies the programme {prog} inside {w:g} x {d:g} m with the entrance on the {entrance}'
        )
    return _emit(best[0], w, d, entrance, float(storey_h), best[1], _plan_id(w, d, prog, entrance, seed, kind), kind)


def generate_house(w, d, rooms=None, entrance='south', seed=0, storey_h=2.7, candidates=300) -> dict:
    """The same solver with a house programme and the front door on `entrance`."""
    return generate_unit(
        w, d, rooms or list(HOUSE_ROOMS), entrance, seed, storey_h, kind='house', candidates=candidates
    )


# ── the generated pack on disk ────────────────────────────────────────────────
MANIFEST = {
    'pack': 'generated',
    'title': 'Generated plans (plan_solver)',
    'source_url': '',
    'version': '1',
    # generated in-house: no third-party plan geometry enters this pack, only
    # the swiss_dwellings room-size medians steer the solver. CC0 is the open
    # licence that says exactly that, and keeps the pack contract happy.
    'licence': 'CC0 1.0 (generated in-house)',
    'attribution': 'Plans generated in-house by the Zygomatic plan_solver; '
    'room sizes calibrated on Swiss Dwellings (Archilyse AG, CC BY 4.0).',
    'doi': '',
    'count': {'unit': 0, 'floor': 0, 'house': 0},
    'converted': '',
    'notes': 'Synthetic guillotine layouts. No plan geometry is copied from any pack.',
}


def _row(plan: dict) -> dict:
    return {
        'id': plan['id'],
        'kind': plan['kind'],
        'w': plan['w'],
        'd': plan['d'],
        'area': plan['area'],
        'n_rooms': len(plan['rooms']),
        'types': ','.join(r['type'] for r in plan['rooms']),
        'entrance': (plan.get('entrance') or {}).get('side'),
        'fill': round(plan['area'] / max(1e-6, plan['w'] * plan['d']), 3),
    }


def write_plan(plan: dict) -> str:
    """Write one plan into the `generated` pack and refresh index.json/pack.json.
    Returns the path of the plan file."""
    pdir = pack_dir()
    os.makedirs(os.path.join(pdir, 'plans'), exist_ok=True)
    path = os.path.join(pdir, 'plans', plan['id'] + '.json')
    with open(path, 'w') as fh:
        json.dump(plan, fh, separators=(',', ':'), sort_keys=True)
    rows = {}
    try:
        with open(os.path.join(pdir, 'index.json')) as fh:
            for r in json.load(fh).get('rows') or []:
                rows[r.get('id')] = r
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('plan index unreadable, rebuilding it from disk: %s', _exc)
    rows[plan['id']] = _row(plan)
    on_disk = {f[:-5] for f in os.listdir(os.path.join(pdir, 'plans')) if f.endswith('.json')}
    rows = {k: v for k, v in rows.items() if k in on_disk}
    for missing in sorted(on_disk - set(rows)):
        try:
            with open(os.path.join(pdir, 'plans', missing + '.json')) as fh:
                rows[missing] = _row(json.load(fh))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('plan %s unreadable, left out of the index: %s', missing, _exc)
    ordered = [rows[k] for k in sorted(rows)]
    man = dict(MANIFEST)
    man['count'] = {k: sum(1 for r in ordered if r.get('kind') == k) for k in ('unit', 'floor', 'house')}
    man['converted'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    with open(os.path.join(pdir, 'pack.json'), 'w') as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    with open(os.path.join(pdir, 'index.json'), 'w') as fh:
        json.dump({'pack': man, 'rows': ordered}, fh, separators=(',', ':'), sort_keys=True)
    return path


# ── the assistant's tools ─────────────────────────────────────────────────────
KINDS: dict = {}
OPENINGS: list = []

PROMPT = (
    'Plan solver: plan_unit(width, depth, rooms, entrance, seed) invents an apartment plan '
    'inside a width x depth rectangle — a hall from the front door, rooms either side, the '
    'living room at the far end — with room sizes calibrated on the Swiss Dwellings medians; '
    'plan_house(...) does the same with a house programme (3 bedrooms, wc). rooms is a comma '
    'list ("living,kitchen,bedroom,bedroom,bathroom"), empty picks the programme by area; '
    'entrance is the side the front door sits on; change seed for another layout. Each writes '
    'a plan file and answers with its id — draw it with place_plan(id, group=..., storey=...).'
)


def _refuse(msg: str) -> str:
    return 'refused: ' + msg


def _plan_tool(d, a, kind, width, depth, rooms='', entrance=None, seed=0, storey_h=2.7, group='', storey=0):
    try:
        width, depth, seed = float(width), float(depth), int(seed)
    except Exception:  # noqa: BLE001
        return _refuse(f'width, depth and seed must be numbers — plan_{kind}(width=9, depth=11, seed=0)')
    side = (entrance or ('north' if kind == 'unit' else 'south')).strip().lower()
    if side not in SIDES:
        return _refuse(
            f'entrance {side!r} is not a side — plan_{kind}(width={width:g}, depth={depth:g}, entrance="north")'
        )
    prog = [t.strip().lower() for t in str(rooms or '').replace(';', ',').split(',') if t.strip()]
    bad = [t for t in prog if t not in MIN_W]
    if bad:
        return _refuse(
            f'unknown room type(s) {", ".join(bad)} — '
            f'plan_{kind}(width={width:g}, depth={depth:g}, '
            f'rooms="living,kitchen,bedroom,bathroom")'
        )
    try:
        gen = generate_unit if kind == 'unit' else generate_house
        plan = gen(width, depth, prog or None, side, seed, float(storey_h))
        path = write_plan(plan)
    except ValueError as exc:
        return _refuse(f'{exc} — try plan_{kind}(width={max(width, 6):g}, depth={max(depth, 9):g}, seed={seed + 1})')
    listing = ', '.join(f'{r["name"].lower()} {r["area"]:g}' for r in plan['rooms'])
    placed = ''
    if group:
        try:
            from zyg_workflows import arch_assistant as A

            mod = (A.EXT_MODULES or {}).get('floor_plans')
            if mod is not None and hasattr(mod, '_place'):
                placed = ' ' + str(mod._place(d, plan, group=group, storey=int(storey)))
        except Exception as exc:  # noqa: BLE001
            placed = f' (not placed: {exc})'
    return (
        f'{plan["id"]} — {kind} {plan["w"]:g} x {plan["d"]:g} m, {plan["area"]:g} m2, '
        f'{len(plan["rooms"])} rooms ({listing} m2), entrance {side}, '
        f'{len(plan["doors"])} doors, {len(plan["windows"])} windows. '
        f'Saved to {os.path.relpath(path, plans_root())}. '
        f'Place it with place_plan(id, group=..., storey=...).' + placed
    )


def t_plan_unit(d, a, width, depth, rooms='', entrance='north', seed=0, storey_h=2.7, group='', storey=0):
    return _plan_tool(d, a, 'unit', width, depth, rooms, entrance, seed, storey_h, group, storey)


def t_plan_house(d, a, width, depth, rooms='', entrance='south', seed=0, storey_h=2.7, group='', storey=0):
    return _plan_tool(d, a, 'house', width, depth, rooms, entrance, seed, storey_h, group, storey)


_ARGS = {
    'width': {'type': 'number'},
    'depth': {'type': 'number'},
    'rooms': {'type': 'string'},
    'entrance': {'type': 'string', 'enum': list(SIDES)},
    'seed': {'type': 'integer'},
    'storey_h': {'type': 'number'},
    'group': {'type': 'string'},
    'storey': {'type': 'integer'},
}

TOOLS = [
    (
        {
            'name': 'plan_unit',
            'description': 'Invent an apartment plan inside a width x depth rectangle: a hall from the '
            'front door, rooms either side, the living room at the far end, with room '
            'sizes calibrated on the Swiss Dwellings medians. rooms is a comma list '
            '("living,kitchen,bedroom,bedroom,bathroom"); leave it empty to take the '
            'programme from the area. Writes the plan and answers with its id for '
            'place_plan. Use when the user asks for a flat/apartment layout.',
            'input_schema': {'type': 'object', 'properties': dict(_ARGS), 'required': ['width', 'depth']},
        },
        t_plan_unit,
    ),
    (
        {
            'name': 'plan_house',
            'description': 'The same solver with a house programme (living, kitchen, three bedrooms, '
            'bathroom, wc, hall, storage) and the front door on `entrance`. Writes the '
            'plan and answers with its id for place_plan.',
            'input_schema': {'type': 'object', 'properties': dict(_ARGS), 'required': ['width', 'depth']},
        },
        t_plan_house,
    ),
]

EXAMPLES = [
    {
        'ask': 'design me a 9 by 11 m two-bedroom flat with the front door on the north',
        'calls': [
            {
                'tool': 'plan_unit',
                'args': {
                    'width': 9,
                    'depth': 11,
                    'rooms': 'living,kitchen,bedroom,bedroom,bathroom,storage',
                    'entrance': 'north',
                },
            }
        ],
    },
    {
        'ask': 'another layout for that flat',
        'calls': [{'tool': 'plan_unit', 'args': {'width': 9, 'depth': 11, 'seed': 1}}],
    },
    {
        'ask': 'a 12 by 10 m family house plan, front door on the south',
        'calls': [{'tool': 'plan_house', 'args': {'width': 12, 'depth': 10, 'entrance': 'south'}}],
    },
]
