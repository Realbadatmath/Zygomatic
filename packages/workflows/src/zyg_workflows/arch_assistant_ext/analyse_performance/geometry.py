# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This module inherits the original file's top import block verbatim; some of those
# imports are used only by its sibling modules, which import them from here, so F401
# must not strip them out of a range that is promised byte-for-byte; __all__ below
# names the ones this module does not use itself.

"""analyse_performance — the assistant half of Analyse ▸ Daylight, Energy,
U-value, Structure, Code check.

Five Python twins of the five icons of arch_ext/analyse_performance.js, run on
the Drawing instead of the live scene: the same room finder (closed wall loops,
or `zone` records with a point list), the same BRE average daylight factor, the
same U = 1/(Rsi + Σ d/λ + Rse), the same H = Σ U·A + ventilation, and the same
structural rules of thumb — so a number the model quotes matches the number the
sheet shows.

code_check() runs its own four checks and, in addition, whatever OTHER analysis
family is installed: it imports arch_assistant_ext/<name>.py BY FILE PATH inside
try/except (analyse_geometry, analyse_planning, light_studies) and calls the
`ANALYSES` mapping that family exports (see below), reporting which were
available and which were not. Every family here exports the same convention:

    ANALYSES = {'<icon id>': ('Human name', fn(Drawing) -> {'issues': [...],
                                                            'summary': str})}
    an issue is {'severity': 'error'|'warning'|'info', 'text': str, 'ids': []}

Standard library only.
"""

import math
import os
import re
import logging as _zyg_logging

from zyg_workflows import paths

# re-exported for the package __init__, which imports these two from here
__all__ = [
    'os',
    're',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.analyse_performance')


KINDS: dict = {}
OPENINGS: list = []
BUTTONS = ['a_daylight', 'a_energy', 'a_uvalue', 'a_struct', 'a_code']

#: The extension directory the sibling analysis families are loaded from by file path.
HERE = str(paths.PKG_DIR / 'arch_assistant_ext')
FAM = 'analyse_performance'

WALLS = ('wall', 'partition')
OPENING_KINDS = ('door', 'double_door', 'window', 'opening')

# ── geometry helpers ─────────────────────────────────────────────────────────


def _n(v, d=0.0):
    try:
        f = float(v)
        return f if f == f and abs(f) != float('inf') else d
    except (TypeError, ValueError):
        return d


def _storey_h(d):
    return _n(getattr(d, 'storey_h', 2.7), 2.7) or 2.7


def _storey_of(d, o):
    return int(round(_n(o.get('y'), 0.0) / _storey_h(d)))


def _live(d):
    return [o for o in d.objs if not o.get('hidden')]


def _is_wall(o):
    return o.get('kind') in WALLS


def _is_opening(k):
    return k in OPENING_KINDS


def _is_roof(o):
    return str(o.get('kind', '')).startswith('roof_')


def _wall_ends(w):
    """THREE rotation.y = ry sends local +X to (cos ry, -sin ry)."""
    L = _n(w['p'].get('len'), 4.0)
    c, s = math.cos(_n(w.get('ry'), 0.0)), math.sin(_n(w.get('ry'), 0.0))
    return [(w['x'] + L / 2 * c, w['z'] - L / 2 * s), (w['x'] - L / 2 * c, w['z'] + L / 2 * s)]


def _shoelace(pts):
    a = 0.0
    for i, (x, z) in enumerate(pts):
        qx, qz = pts[(i + 1) % len(pts)]
        a += x * qz - qx * z
    return a / 2


def _perimeter(pts):
    L = 0.0
    for i, (x, z) in enumerate(pts):
        qx, qz = pts[(i + 1) % len(pts)]
        L += math.hypot(x - qx, z - qz)
    return L


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _pt_in_poly(pts, x, z):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        ax, az = pts[i]
        bx, bz = pts[j]
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            inside = not inside
        j = i
    return inside


def _dist_to_seg(x, z, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dz * dz
    t = ((x - a[0]) * dx + (z - a[1]) * dz) / l2 if l2 > 1e-9 else 0.0
    t = max(0.0, min(1.0, t))
    return math.hypot(x - (a[0] + t * dx), z - (a[1] + t * dz))


def _dist_to_poly(pts, x, z):
    return min(_dist_to_seg(x, z, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))


# ── rooms: zone records, else our own planar face finder ─────────────────────
def _norm_pts(raw, rec):
    out = []
    for p in raw or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            lx, lz = _n(p[0], None), _n(p[1], None)
        elif isinstance(p, dict):
            lx = _n(p.get('x'), None)
            lz = _n(p.get('z') if p.get('z') is not None else p.get('y'), None)
        else:
            continue
        if lx is None or lz is None:
            continue
        if rec:
            c, s = math.cos(_n(rec.get('ry'), 0.0)), math.sin(_n(rec.get('ry'), 0.0))
            out.append((rec['x'] + lx * c + lz * s, rec['z'] - lx * s + lz * c))
        else:
            out.append((lx, lz))
    return out


def _zone_rooms(d):
    out = []
    walls = [o for o in _live(d) if _is_wall(o)]
    for o in _live(d):
        if not str(o.get('kind', '')).startswith('zone'):
            continue
        pts = _norm_pts(o['p'].get('pts') or o['p'].get('points'), o)
        if len(pts) < 3:
            continue
        if _shoelace(pts) < 0:
            pts = list(reversed(pts))
        st = _storey_of(d, o)
        out.append(
            {
                'id': o['id'],
                'name': str(o.get('name') or 'Zone'),
                'pts': pts,
                'area': abs(_shoelace(pts)),
                'perim': _perimeter(pts),
                'storey': st,
                'y': _n(o.get('y'), 0.0),
                'walls': [w for w in walls if _storey_of(d, w) == st and _dist_to_poly(pts, w['x'], w['z']) < 1.0],
            }
        )
    return out


def _loops_of(d, walls, storey):
    """Planar face traversal. The successor of a half-edge is the edge BEFORE
    its twin in the ascending-angle order around the twin's node, so a bounded
    face is walked with its interior on the left and has a POSITIVE shoelace."""
    TOL = 0.35
    nodes = []

    def node_at(p):
        for i, q in enumerate(nodes):
            if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 < TOL * TOL:
                return i
        nodes.append(p)
        return len(nodes) - 1

    half = []
    for w in walls:
        e = _wall_ends(w)
        a, b = node_at(e[0]), node_at(e[1])
        if a == b:
            continue
        i = len(half)
        half.append({'from': a, 'to': b, 'w': w, 'twin': i + 1})
        half.append({'from': b, 'to': a, 'w': w, 'twin': i})
    if not half:
        return []
    for h in half:
        h['ang'] = math.atan2(nodes[h['to']][1] - nodes[h['from']][1], nodes[h['to']][0] - nodes[h['from']][0])
    around: dict = {}
    for i, h in enumerate(half):
        around.setdefault(h['from'], []).append(i)
    for k in around:
        around[k].sort(key=lambda i: half[i]['ang'])
        for pos, i in enumerate(around[k]):
            half[i]['pos'] = pos

    def nxt(i):
        t = half[i]['twin']
        ring = around[half[t]['from']]
        return ring[(half[t]['pos'] - 1) % len(ring)]

    seen, rooms, n = set(), [], 0
    for s in range(len(half)):
        if s in seen:
            continue
        cyc, i, guard = [], s, 0
        while i not in seen and guard < 4000:
            guard += 1
            seen.add(i)
            cyc.append(i)
            i = nxt(i)
        if i != s or len(cyc) < 3:
            continue
        pts = [nodes[half[h]['from']] for h in cyc]
        a = _shoelace(pts)
        if a < 0.5:
            continue
        n += 1
        rooms.append(
            {
                'id': 'room%d_%d' % (storey, n),
                'name': 'Room %d' % n,
                'pts': pts,
                'area': a,
                'perim': _perimeter(pts),
                'storey': storey,
                'y': storey * _storey_h(d),
                'walls': [half[h]['w'] for h in cyc],
            }
        )
    return rooms


def rooms(d):
    """(list of rooms, where the list came from) — the same three-source order
    as the tab, minus the browser-only analyse_planning hook."""
    zr = _zone_rooms(d)
    if zr:
        return zr, 'zone records (p.pts)'
    walls = [o for o in _live(d) if _is_wall(o) and _n(o['p'].get('len'), 0.0) > 0.05]
    by: dict = {}
    for w in walls:
        by.setdefault(_storey_of(d, w), []).append(w)
    out = []
    for k in sorted(by):
        out += _loops_of(d, by[k], k)
    return out, 'closed wall loops per storey (own loop finder)'


def _wall_room_count(rms):
    c: dict = {}
    for r in rms:
        for w in r['walls']:
            c[w['id']] = c.get(w['id'], 0) + 1
    return c


def _openings_of(d, walls):
    """The host test arSyncHoles uses, read-only."""
    m = {w['id']: [] for w in walls}
    for o in _live(d):
        if not _is_opening(o['kind']):
            continue
        best, bd = None, 1e9
        for w in walls:
            ln, t = _n(w['p'].get('len'), 4.0), _n(w['p'].get('t'), 0.24)
            h = _n(w['p'].get('h'), _storey_h(d))
            if o['y'] < w['y'] - 0.05 or o['y'] > w['y'] + h - 0.05:
                continue
            c, s = math.cos(-_n(w.get('ry'), 0.0)), math.sin(-_n(w.get('ry'), 0.0))
            dx, dz = o['x'] - w['x'], o['z'] - w['z']
            lx, lz = dx * c - dz * s, dx * s + dz * c
            if abs(lx) > ln / 2 + 0.001:
                continue
            if abs(lz) > t / 2 + 0.45:
                continue
            if abs(lz) < bd:
                bd, best = abs(lz), w
        if best:
            m[best['id']].append(o)
    return m
