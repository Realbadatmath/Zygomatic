#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tools/plans_convert_houses.py — convert ResPlan and ProcTHOR-10K into house
plan packs under data/architecture/plans/<pack>/ using the shared plan schema.

    python tools/plans_convert_houses.py --pack all
    ... --pack resplan --limit 50 --out /tmp/try        # smoke run
    ... --fixtures-only                                 # rebuild the test fixtures

Both packs write plans/<id>.json + index.json + pack.json, and 6 varied plans
are copied into tests_arch_ext/fixtures/plans/<pack>/ with the same layout.

Coordinate rule (schema): source x = east, source y = NORTH, so plan z = -y;
then the bbox min corner is translated to (0, 0) and everything is rounded to
3 decimals. ResPlan's pickle does not document which way its y axis points, so
the flip is applied as the rule states (see pack.json notes). ProcTHOR's z is
its own 'north', so plan z = -z_thor and object rotations negate with it.

Licences: ResPlan CC BY 4.0 (data) / MIT (code); ProcTHOR-10K Apache 2.0.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import pickle
import shutil
import zipfile
from collections import Counter

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.prepared import prep

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
ASSETS = os.path.join(CREWS, 'data', 'assets', 'floor_plans')
PLANS_OUT = os.path.join(CREWS, 'data', 'architecture', 'plans')
FIXTURES = os.path.join(CREWS, 'tests_arch_ext', 'fixtures', 'plans')

ROOM_TYPES = (
    'living',
    'kitchen',
    'bedroom',
    'bathroom',
    'wc',
    'hall',
    'corridor',
    'storage',
    'balcony',
    'stair',
    'lift',
    'shaft',
    'other',
)
R3 = 3


def r(v):
    return round(float(v), R3)


def pt(x, z):
    return [r(x), r(z)]


# ── rectilinear helpers ───────────────────────────────────────────────────────
def rect_decompose(poly: Polygon, max_cells=6000):
    """Split an axis-aligned rectilinear polygon into maximal rectangles.

    Grid-partitions on every vertex x and y, keeps the cells inside the
    polygon, then merges runs along x and identical runs along y. Falls back to
    the minimum rotated rectangle's bbox when the grid would be too large or
    the polygon is not rectilinear enough.
    """
    if poly.is_empty or poly.area <= 0:
        return []
    xs = sorted({r(c[0]) for c in poly.exterior.coords})
    ys = sorted({r(c[1]) for c in poly.exterior.coords})
    if len(xs) < 2 or len(ys) < 2 or (len(xs) - 1) * (len(ys) - 1) > max_cells:
        b = poly.minimum_rotated_rectangle.bounds
        return [(b[0], b[1], b[2], b[3])]
    pp = prep(poly)
    nx, ny = len(xs) - 1, len(ys) - 1
    grid = [[False] * nx for _ in range(ny)]
    for j in range(ny):
        cy = (ys[j] + ys[j + 1]) / 2.0
        for i in range(nx):
            cx = (xs[i] + xs[i + 1]) / 2.0
            grid[j][i] = pp.contains(
                Polygon(
                    [(cx - 1e-9, cy - 1e-9), (cx + 1e-9, cy - 1e-9), (cx + 1e-9, cy + 1e-9), (cx - 1e-9, cy + 1e-9)]
                )
            )
    runs = []  # (row, i0, i1) maximal x-runs
    for j in range(ny):
        i = 0
        while i < nx:
            if not grid[j][i]:
                i += 1
                continue
            i0 = i
            while i < nx and grid[j][i]:
                i += 1
            runs.append([j, i0, i])
    used = [False] * len(runs)
    out = []
    by_row = {}
    for k, (j, _i0, _i1) in enumerate(runs):
        by_row.setdefault(j, []).append(k)
    for k, (j, i0, i1) in enumerate(runs):
        if used[k]:
            continue
        used[k] = True
        j1 = j
        while True:
            nxt = None
            for k2 in by_row.get(j1 + 1, ()):
                if not used[k2] and runs[k2][1] == i0 and runs[k2][2] == i1:
                    nxt = k2
                    break
            if nxt is None:
                break
            used[nxt] = True
            j1 += 1
        out.append((xs[i0], ys[j], xs[i1], ys[j1 + 1]))
    return out


def rect_to_seg(rect, min_len=0.25):
    """A wall rectangle -> (a, b, thickness) along its long axis."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    if w >= h:
        if w < min_len:
            return None
        cy = (y0 + y1) / 2.0
        return ((x0, cy), (x1, cy), h)
    if h < min_len:
        return None
    cx = (x0 + x1) / 2.0
    return ((cx, y0), (cx, y1), w)


def merge_collinear(segs, tol=0.02):
    """Join touching/overlapping axis-aligned segments that share a line."""
    groups = {}
    for a, b, t in segs:
        horiz = abs(a[1] - b[1]) <= tol
        key = ('h' if horiz else 'v', round(a[1] if horiz else a[0], 2), round(t, 2))
        groups.setdefault(key, []).append((a, b, t))
    out = []
    for (o, fixed, _tk), items in groups.items():
        spans = []
        for a, b, t in items:
            lo, hi = (a[0], b[0]) if o == 'h' else (a[1], b[1])
            if lo > hi:
                lo, hi = hi, lo
            spans.append([lo, hi, t])
        spans.sort()
        merged = [spans[0]]
        for s in spans[1:]:
            cur = merged[-1]
            if s[0] <= cur[1] + tol:
                cur[1] = max(cur[1], s[1])
                cur[2] = max(cur[2], s[2])
            else:
                merged.append(s)
        for lo, hi, t in merged:
            if o == 'h':
                out.append(((lo, fixed), (hi, fixed), t))
            else:
                out.append(((fixed, lo), (fixed, hi), t))
    return out


def walls_from_polys(geom, min_len=0.25):
    """Wall polygons -> centreline segments [(a, b, t)]."""
    parts = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    segs = []
    for g in parts:
        if g.is_empty or g.area <= 0:
            continue
        for rect in rect_decompose(g):
            s = rect_to_seg(rect, min_len)
            if s:
                segs.append(s)
    return merge_collinear(segs)


def opening_from_poly(g):
    """A door/window rectangle -> (centre_x, centre_z, width), or None when the
    source part is degenerate (a line or an empty sliver)."""
    if not isinstance(g, Polygon) or g.is_empty or g.area <= 0:
        return None
    b = g.minimum_rotated_rectangle
    if not isinstance(b, Polygon):
        return None
    e = []
    cs = list(b.exterior.coords[:-1])
    for i in range(len(cs)):
        ax, ay = cs[i]
        bx, by = cs[(i + 1) % len(cs)]
        e.append(math.hypot(bx - ax, by - ay))
    width = max(e) if e else 0.0
    c = g.centroid
    return (c.x, c.y, width)


def nearest_wall(walls, x, z):
    """Index of the wall centreline nearest (x, z), plus the projected point."""
    best, bi, bp = 1e18, -1, (x, z)
    for i, (a, b, _t) in enumerate(walls):
        ln = LineString([a, b])
        d = ln.distance(Point(x, z))
        if d < best:
            p = ln.interpolate(ln.project(Point(x, z)))
            best, bi, bp = d, i, (p.x, p.y)
    return bi, bp, best


def ring(poly, limit=400):
    """Exterior ring of a polygon as [[x, z], ...] CCW, no repeated last point."""
    if not isinstance(poly, Polygon) or poly.is_empty:
        return []
    poly = orient(Polygon(poly.exterior).simplify(0.01, preserve_topology=True), sign=1.0)
    cs = list(poly.exterior.coords)[:-1]
    if len(cs) > limit:
        poly = orient(Polygon(poly.exterior).simplify(0.02), sign=1.0)
        cs = list(poly.exterior.coords)[:-1]
    return [pt(x, y) for x, y in cs]


def biggest(geom):
    if geom.is_empty:
        return None
    if hasattr(geom, 'geoms'):
        gs = [g for g in geom.geoms if isinstance(g, Polygon) and g.area > 0]
        if not gs:
            return None
        return max(gs, key=lambda g: g.area)
    return geom if geom.area > 0 else None


def _clipped_area(g, body):
    """area of g inside body, tolerant of the source's degenerate rings."""
    try:
        return g.intersection(body).area
    except Exception:  # noqa: BLE001
        try:
            return g.intersection(body, grid_size=0.001).area
        except Exception:  # noqa: BLE001
            return min(g.area, body.area)


def in_bbox(rec, tol=0.02):
    """True when every emitted point lies inside the plan's own w x d bbox.
    The schema puts the bbox min at (0, 0), so anything negative is a stray
    island the boundary does not cover."""
    w, d = rec['w'], rec['d']
    pts = list(rec['boundary'])
    for x in rec['rooms']:
        pts += x['pts']
    for x in rec['walls']:
        pts += [x['a'], x['b']]
    for grp in ('doors', 'windows', 'fixtures'):
        pts += [[o['x'], o['z']] for o in rec[grp]]
    return all(-tol <= q[0] <= w + tol and -tol <= q[1] <= d + tol for q in pts)


def side_of(x, z, w, d):
    dists = {'west': x, 'east': w - x, 'north': z, 'south': d - z}
    return min(dists, key=dists.get)


# ── ResPlan ───────────────────────────────────────────────────────────────────
RESPLAN_ROOMS = {  # pickle key -> schema room type ('inner' is NOT a room:
    'living': 'living',
    'kitchen': 'kitchen',
    'bedroom': 'bedroom',  # it is the whole
    'bathroom': 'bathroom',
    'balcony': 'balcony',  # interior footprint)
    'storage': 'storage',
    'stair': 'stair',
}
RESPLAN_COUNTED = ('living', 'kitchen', 'bedroom', 'bathroom', 'storage', 'stair')
RESPLAN_NAMES = {
    'living': 'Living',
    'kitchen': 'Kitchen',
    'bedroom': 'Bedroom',
    'bathroom': 'Bathroom',
    'balcony': 'Balcony',
    'corridor': 'Hall',
    'storage': 'Storage',
    'stair': 'Stair',
}


def resplan_pickle():
    """Path to ResPlan.pkl, unzipped into the package scratch directory on first use."""
    direct = os.path.join(ASSETS, 'resplan', 'ResPlan.pkl')
    if os.path.exists(direct):
        return direct
    tmp = str(paths.tmp_dir('resplan') / 'ResPlan.pkl')
    if os.path.exists(tmp):
        return tmp
    with zipfile.ZipFile(os.path.join(ASSETS, 'resplan', 'ResPlan.zip')) as z:
        z.extract('ResPlan.pkl', os.path.dirname(tmp))
    return tmp


def resplan_scale(p):
    """Source units -> metres. `area` (m²) is the area of the `inner` footprint,
    so the scale is sqrt(area / inner.area); the room union is the fallback."""
    inner = p.get('inner')
    if inner is not None and not inner.is_empty and inner.area > 0:
        return math.sqrt(float(p['area']) / inner.area)
    gs = [p[k] for k in RESPLAN_ROOMS if p.get(k) is not None and not p[k].is_empty]
    if not gs:
        return 0.0
    u = unary_union(gs)
    return math.sqrt(float(p['area']) / u.area) if u.area > 0 else 0.0


def convert_resplan_plan(p, stats):
    if p.get('area_change_sqft') is not None:
        stats['augmented'] += 1
        return None
    area = float(p.get('area') or 0.0)
    if not (30.0 <= area <= 400.0):
        stats['area'] += 1
        return None
    s = resplan_scale(p)
    if s <= 0:
        stats['no_scale'] += 1
        return None

    def tf(g):
        g = affinity.scale(g, xfact=s, yfact=-s, origin=(0, 0))
        return g if g.is_valid else g.buffer(0)

    room_geo = {}
    n_rooms = 0
    for key, typ in RESPLAN_ROOMS.items():
        g = p.get(key)
        if g is None or g.is_empty:
            continue
        room_geo[typ] = tf(g)
        if key in RESPLAN_COUNTED:
            n_rooms += len(g.geoms) if hasattr(g, 'geoms') else 1
    if not (2 <= n_rooms <= 12):
        stats['rooms'] += 1
        return None
    inner_g = tf(p['inner']) if p.get('inner') is not None and not p['inner'].is_empty else None
    walls_g = p.get('wall')
    if walls_g is None or walls_g.is_empty:
        stats['no_walls'] += 1
        return None
    walls_g = tf(walls_g)
    doors_g = tf(p['door']) if p.get('door') is not None and not p['door'].is_empty else None
    wins_g = tf(p['window']) if p.get('window') is not None and not p['window'].is_empty else None
    fd_g = tf(p['front_door']) if p.get('front_door') is not None and not p['front_door'].is_empty else None

    shell = unary_union([g for g in list(room_geo.values()) + [walls_g, inner_g] if g is not None])
    body = biggest(shell)
    if body is None:
        stats['no_body'] += 1
        return None
    if body.area < 0.6 * shell.area:  # the plan falls apart into islands
        stats['fragmented'] += 1
        return None
    minx, minz, maxx, maxz = body.bounds
    w, d = maxx - minx, maxz - minz
    if w <= 0 or d <= 0:
        stats['no_body'] += 1
        return None

    def mv(g):
        return affinity.translate(g, xoff=-minx, yoff=-minz)

    body = mv(body)
    net = (
        _clipped_area(mv(inner_g), body)
        if inner_g is not None
        else sum(_clipped_area(mv(g), body) for g in room_geo.values())
    )
    if net <= 1.0:
        stats['no_body'] += 1
        return None
    rooms = []
    for typ, g in room_geo.items():
        g = mv(g)
        for part in g.geoms if hasattr(g, 'geoms') else [g]:
            if part.is_empty or part.area < 0.5:
                continue
            if _clipped_area(part, body) < 0.5 * part.area:  # island off the main body
                continue
            rooms.append(
                {'type': typ, 'pts': ring(part), 'area': r(part.area), 'name': RESPLAN_NAMES.get(typ, typ.title())}
            )
    if len(rooms) < 2:
        stats['rooms'] += 1
        return None
    if inner_g is not None:  # hall = interior footprint minus the rooms
        try:
            named = unary_union([mv(g) for g in room_geo.values()])
            hall = mv(inner_g).difference(named.buffer(0.01))
        except Exception:  # noqa: BLE001 — degenerate source rings
            hall = Polygon()
        for part in hall.geoms if hasattr(hall, 'geoms') else [hall]:
            if isinstance(part, Polygon) and part.area >= 1.5:
                part = part.buffer(0.02).buffer(-0.02)
                part = biggest(part) if part is not None else None
                if part is None or part.area < 1.5:
                    continue
                rooms.append({'type': 'corridor', 'pts': ring(part), 'area': r(part.area), 'name': 'Hall'})
    segs = walls_from_polys(mv(walls_g))
    if not segs:
        stats['no_walls'] += 1
        return None
    skin = LineString(body.exterior.coords).buffer(max(0.05, float(p.get('wall_depth', 0)) * s * 0.75))
    walls, kept_segs = [], []
    for a, b, t in segs:
        ln = LineString([a, b])
        if body.distance(ln) > 0.5:  # wall of an island we dropped
            continue
        ext = ln.length > 0 and skin.intersection(ln).length >= 0.7 * ln.length
        walls.append({'a': pt(*a), 'b': pt(*b), 't': r(max(t, 0.05)), 'ext': bool(ext)})
        kept_segs.append((a, b, t))
    segs = kept_segs
    if not walls:
        stats['no_walls'] += 1
        return None

    doors = []
    if doors_g is not None:
        for g in mv(doors_g).geoms if hasattr(mv(doors_g), 'geoms') else [mv(doors_g)]:
            o = opening_from_poly(g)
            if o is None:
                continue
            cx, cz, wid = o
            wi, (px, pz), dist = nearest_wall(segs, cx, cz)
            if wi < 0 or dist > 1.5:
                continue
            doors.append({'x': r(px), 'z': r(pz), 'w': r(max(0.6, min(2.4, wid))), 'wall': wi, 'kind': 'door'})
    windows = []
    if wins_g is not None:
        for g in mv(wins_g).geoms if hasattr(mv(wins_g), 'geoms') else [mv(wins_g)]:
            o = opening_from_poly(g)
            if o is None:
                continue
            cx, cz, wid = o
            wi, (px, pz), dist = nearest_wall(segs, cx, cz)
            if wi < 0 or dist > 1.5:
                continue
            windows.append({'x': r(px), 'z': r(pz), 'w': r(max(0.4, min(4.0, wid))), 'wall': wi, 'sill': 0.9, 'h': 1.4})
    entrance = None
    fd_o = opening_from_poly(mv(fd_g)) if fd_g is not None else None
    if fd_o is not None:
        cx, cz, wid = fd_o
        wi, (px, pz), dist = nearest_wall(segs, cx, cz)
        if wi >= 0:
            hit = None
            for dr in doors:
                if math.hypot(dr['x'] - px, dr['z'] - pz) < 0.5:
                    hit = dr
                    break
            if hit is None:
                hit = {'x': r(px), 'z': r(pz), 'w': r(max(0.6, min(2.4, wid))), 'wall': wi, 'kind': 'entrance'}
                doors.append(hit)
            else:
                hit['kind'] = 'entrance'
            entrance = {'side': side_of(hit['x'], hit['z'], w, d), 'x': hit['x'], 'z': hit['z']}

    return {
        'id': 'rp_%d' % int(p['id']),
        'pack': 'resplan',
        'kind': 'house',
        'w': r(w),
        'd': r(d),
        'area': r(net),
        'storey_h': 2.7,
        'boundary': ring(body),
        'rooms': rooms,
        'walls': walls,
        'doors': doors,
        'windows': windows,
        'fixtures': [],
        'entrance': entrance,
        'core': {'stairs': [], 'lifts': []},
        'units': [],
        'source': {
            'resplan_id': int(p['id']),
            'scale_m_per_unit': round(s, 6),
            'wall_depth_m': r(float(p.get('wall_depth', 0.0)) * s),
        },
        'mirror_ok': True,
    }


def convert_resplan(out_root, limit=0):
    # The ResPlan research dataset ships as a pickle of shapely geometry; it has no JSON form.
    # The only file read here is the one resplan_pickle() unzips out of this package's own
    # assets, so nothing untrusted is ever deserialised.
    with open(resplan_pickle(), 'rb') as fh:
        plans = pickle.load(fh)  # noqa: S301  shipped dataset, see the comment above  # nosec B301
    stats = Counter()
    stats['input'] = len(plans)
    rows, kept = [], 0
    pdir = os.path.join(out_root, 'resplan', 'plans')
    os.makedirs(pdir, exist_ok=True)
    for p in plans:
        try:
            rec = convert_resplan_plan(p, stats)
        except Exception as exc:  # noqa: BLE001
            stats['error'] += 1
            if stats['error'] < 4:
                _zyg_log.warning('  resplan %s: %s' % (p.get('id'), exc))
            continue
        if rec is None:
            continue
        if not in_bbox(rec):
            stats['outside_bbox'] += 1
            continue
        write_plan(pdir, rec)
        rows.append(index_row(rec))
        kept += 1
        if limit and kept >= limit:
            break
    manifest = {
        'pack': 'resplan',
        'title': 'ResPlan residential floor plans',
        'source_url': 'https://github.com/m-agour/ResPlan',
        'version': '1.0',
        'licence': 'CC BY 4.0 (data), MIT (code)',
        'attribution': 'Floor plans: ResPlan (Agour et al. 2025), CC BY 4.0, https://github.com/m-agour/ResPlan',
        'doi': '',
        'count': {'unit': 0, 'floor': 0, 'house': kept},
        'converted': iso_now(),
        'notes': (
            'geometry recovered from real-estate listing renderings; provenance withheld '
            'by the authors; takedown policy applies — treat as lower-trust than Swiss '
            "Dwellings. Metres come from each plan's own area field "
            '(scale = sqrt(area_m2 / sum(room polygon areas))); wall thickness from '
            'wall_depth x that scale. The 683 augmented plans (area_change_sqft set) are '
            'excluded. The pickle does not document its y axis, so the schema flip '
            'z = -y is applied as written and plans may be mirrored north/south; '
            'mirror_ok is true.'
        ),
    }
    write_pack(out_root, 'resplan', manifest, rows)
    return manifest, rows, stats


# ── ProcTHOR-10K ──────────────────────────────────────────────────────────────
THOR_ROOMS = {'LivingRoom': 'living', 'Kitchen': 'kitchen', 'Bedroom': 'bedroom', 'Bathroom': 'bathroom'}
THOR_FIXTURES = [
    ('toilet', 'toilet'),
    ('bathtub', 'bathtub'),
    ('shower', 'shower'),
    ('countertop', 'kitchen'),
    ('sinkbasin', 'washbasin'),
    ('sink', 'sink'),
]


def _wall_ends(w):
    """The two y=0 endpoints of a THOR wall quad, in polygon order."""
    poly = w.get('polygon') or []
    lo = min(q['y'] for q in poly) if poly else 0.0
    ends = [(q['x'], q['z']) for q in poly if abs(q['y'] - lo) < 1e-6]
    if len(ends) < 2:
        return None
    return ends[0], ends[-1]


def _wkey(a, b):
    p, q = (round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))
    return (p, q) if p <= q else (q, p)


def convert_thor_house(h, hid, stats):
    rooms_src = [rm for rm in h.get('rooms', []) if rm.get('floorPolygon')]
    if len(rooms_src) < 1:
        stats['no_rooms'] += 1
        return None
    polys, rtypes = [], {}
    for rm in rooms_src:
        cs = [(q['x'], -q['z']) for q in rm['floorPolygon']]
        if len(cs) < 3:
            continue
        g = Polygon(cs)
        if not g.is_valid:
            g = g.buffer(0)
        g = biggest(g) if hasattr(g, 'geoms') else g
        if g is None or g.area <= 0:
            continue
        polys.append((rm, g))
        rtypes[rm['id']] = THOR_ROOMS.get(rm.get('roomType', ''), 'other')
    if not polys:
        stats['no_rooms'] += 1
        return None
    u = unary_union([g for _rm, g in polys])
    body = biggest(u)
    if body is None or (hasattr(u, 'geoms') and len(u.geoms) > 1):
        body = biggest(u.buffer(0.02).buffer(-0.02)) or body
    if body is None:
        stats['no_body'] += 1
        return None
    minx, minz, maxx, maxz = body.bounds
    w, d = maxx - minx, maxz - minz

    def mvx(x):
        return x - minx

    def mvz(z):
        return -z - minz

    body = affinity.translate(body, xoff=-minx, yoff=-minz)
    rooms = []
    for rm, g in polys:
        g = affinity.translate(g, xoff=-minx, yoff=-minz)
        typ = rtypes[rm['id']]
        rooms.append({'type': typ, 'pts': ring(g), 'area': r(g.area), 'name': rm.get('roomType', typ.title())})
    area = sum(x['area'] for x in rooms)

    seen, walls, wall_ix = {}, [], {}
    heights = []
    for wl in h.get('walls', []):
        ends = _wall_ends(wl)
        if ends is None:
            continue
        a, b = ends
        heights += [q['y'] for q in wl.get('polygon', [])]
        k = _wkey(a, b)
        if k in seen:
            if '|exterior|' in wl.get('id', ''):
                walls[seen[k]]['ext'] = True
            wall_ix[wl['id']] = seen[k]
            continue
        pa = (mvx(a[0]), mvz(a[1]))
        pb = (mvx(b[0]), mvz(b[1]))
        if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) < 0.05:
            continue
        seen[k] = len(walls)
        wall_ix[wl['id']] = len(walls)
        walls.append({'a': pt(*pa), 'b': pt(*pb), 't': 0.1, 'ext': '|exterior|' in wl.get('id', '')})
    if not walls:
        stats['no_walls'] += 1
        return None
    ends_by_id = {}
    for wl in h.get('walls', []):
        e = _wall_ends(wl)
        if e:
            ends_by_id[wl['id']] = e

    def hole(o):
        hp = o.get('holePolygon') or []
        if len(hp) < 2:
            return None
        wid = abs(hp[1]['x'] - hp[0]['x'])
        sill, top = hp[0]['y'], hp[1]['y']
        along = o.get('assetPosition', {}).get('x')
        if along is None:
            along = (hp[0]['x'] + hp[1]['x']) / 2.0
        wl = o.get('wall0') or o.get('wall1')
        if wl not in ends_by_id or wl not in wall_ix:
            wl = o.get('wall1') if wl == o.get('wall0') else o.get('wall0')
        if wl not in ends_by_id or wl not in wall_ix:
            return None
        a, b = ends_by_id[wl]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if ln <= 0:
            return None
        ux, uz = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
        wx, wz = a[0] + ux * along, a[1] + uz * along
        return (mvx(wx), mvz(wz), wid, sill, top - sill, wall_ix[wl])

    doors, entrance = [], None
    for dr in h.get('doors', []):
        v = hole(dr)
        if v is None:
            continue
        x, z, wid, _s, _hh, wi = v
        ext = 'exterior' in (dr.get('wall0', '') + dr.get('wall1', '')) or dr.get('room0') == dr.get('room1')
        kind = 'entrance' if ext else 'door'
        doors.append({'x': r(x), 'z': r(z), 'w': r(max(0.6, min(2.6, wid))), 'wall': wi, 'kind': kind})
        if ext and entrance is None:
            entrance = {'side': side_of(x, z, w, d), 'x': r(x), 'z': r(z)}
    windows = []
    for wn in h.get('windows', []):
        v = hole(wn)
        if v is None:
            continue
        x, z, wid, sill, hh, wi = v
        windows.append(
            {'x': r(x), 'z': r(z), 'w': r(max(0.3, min(4.0, wid))), 'wall': wi, 'sill': r(sill), 'h': r(max(0.2, hh))}
        )

    fixtures = []
    for ob in h.get('objects', []):
        aid = (ob.get('assetId') or '').lower()
        kind = None
        for pre, k in THOR_FIXTURES:
            if aid.startswith(pre):
                kind = k
                break
        if kind is None:
            continue
        if kind in ('sink', 'washbasin'):
            bits = (ob.get('id') or '').split('|')
            rid = 'room|' + bits[1] if len(bits) > 1 else ''
            kind = 'washbasin' if rtypes.get(rid) == 'bathroom' else 'sink'
        pos = ob.get('position') or {}
        if 'x' not in pos or 'z' not in pos:
            continue
        ry = -math.radians(float((ob.get('rotation') or {}).get('y', 0.0)))
        fixtures.append({'kind': kind, 'x': r(mvx(pos['x'])), 'z': r(mvz(pos['z'])), 'ry': r(ry)})

    sh = 2.7
    if heights:
        mh = max(heights)
        if 2.0 <= mh <= 4.0:
            sh = r(mh)
    return {
        'id': hid,
        'pack': 'procthor10k',
        'kind': 'house',
        'w': r(w),
        'd': r(d),
        'area': r(area),
        'storey_h': sh,
        'boundary': ring(body),
        'rooms': rooms,
        'walls': walls,
        'doors': doors,
        'windows': windows,
        'fixtures': fixtures,
        'entrance': entrance,
        'core': {'stairs': [], 'lifts': []},
        'units': [],
        'source': {
            'split': hid.split('_')[1],
            'line': int(hid.rsplit('_', 1)[1]),
            'room_spec': (h.get('metadata') or {}).get('roomSpecId', ''),
        },
        'mirror_ok': True,
    }


def convert_procthor(out_root, limit=0):
    stats = Counter()
    rows, kept = [], 0
    pdir = os.path.join(out_root, 'procthor10k', 'plans')
    os.makedirs(pdir, exist_ok=True)
    for split in ('train', 'val', 'test'):
        path = os.path.join(ASSETS, 'procthor10k', '%s.jsonl.gz' % split)
        if not os.path.exists(path):
            continue
        with gzip.open(path, 'rt') as fh:
            for n, line in enumerate(fh):
                stats['input'] += 1
                try:
                    h = json.loads(line)
                    rec = convert_thor_house(h, 'pt_%s_%d' % (split, n), stats)
                except Exception as exc:  # noqa: BLE001
                    stats['error'] += 1
                    if stats['error'] < 4:
                        _zyg_log.warning('  procthor %s#%d: %s' % (split, n, exc))
                    continue
                if rec is None:
                    continue
                if not in_bbox(rec):
                    stats['outside_bbox'] += 1
                    continue
                write_plan(pdir, rec)
                rows.append(index_row(rec))
                kept += 1
                if limit and kept >= limit:
                    break
        if limit and kept >= limit:
            break
    manifest = {
        'pack': 'procthor10k',
        'title': 'ProcTHOR-10K procedurally generated houses',
        'source_url': 'https://procthor.allenai.org/',
        'version': '10K',
        'licence': 'Apache 2.0',
        'attribution': 'House layouts: ProcTHOR-10K (Allen Institute for AI), Apache 2.0',
        'doi': '',
        'count': {'unit': 0, 'floor': 0, 'house': kept},
        'converted': iso_now(),
        'notes': (
            'AI2-THOR house JSON. THOR y is up and its z grows north, so plan z = -z_thor '
            'per the schema rule and fixture rotations negate with the flip; x is '
            'unchanged. Walls are the deduplicated thin quads (t = 0.1) and ext comes '
            "from THOR's own wall|exterior records. Layouts are procedural, not surveyed "
            'buildings — use them for circulation and furnishing tests, not for realism.'
        ),
    }
    write_pack(out_root, 'procthor10k', manifest, rows)
    return manifest, rows, stats


# ── writing ───────────────────────────────────────────────────────────────────
def iso_now():
    import datetime

    return datetime.datetime.now().replace(microsecond=0).isoformat()


def index_row(rec):
    types = [x['type'] for x in rec['rooms']]
    wd = rec['w'] * rec['d']
    return {
        'id': rec['id'],
        'kind': rec['kind'],
        'w': rec['w'],
        'd': rec['d'],
        'area': rec['area'],
        'n_rooms': len(rec['rooms']),
        'types': ','.join(types),
        'entrance': (rec['entrance'] or {}).get('side'),
        'fill': round(rec['area'] / wd, 3) if wd > 0 else 0.0,
    }


def write_plan(pdir, rec):
    with open(os.path.join(pdir, rec['id'] + '.json'), 'w') as fh:
        json.dump(rec, fh, separators=(',', ':'))


def write_pack(out_root, pack, manifest, rows):
    root = os.path.join(out_root, pack)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'pack.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    with open(os.path.join(root, 'index.json'), 'w') as fh:
        json.dump({'pack': manifest, 'rows': rows}, fh, separators=(',', ':'))


def pick_fixtures(rows, n=6):
    """n varied plans: spread over area, then widened for room count and
    entrance side so the fixture set is not six copies of the same shape."""
    ok = sorted([x for x in rows if x['n_rooms'] >= 2] or rows, key=lambda x: (x['area'], x['id']))
    picked, seen, shapes = [], set(), set()
    for b in range(n):  # one plan out of each n-th of the area range
        lo = (b * len(ok)) // n
        hi = max(lo + 1, ((b + 1) * len(ok)) // n)
        band = ok[lo:hi]
        take = None
        for x in band:  # prefer an unseen (n_rooms, entrance) shape
            if (x['n_rooms'], x['entrance']) not in shapes and x['id'] not in seen:
                take = x
                break
        if take is None:
            take = band[len(band) // 2]
        if take['id'] in seen:
            continue
        picked.append(take)
        seen.add(take['id'])
        shapes.add((take['n_rooms'], take['entrance']))
    for x in ok:  # top up if a band collided
        if len(picked) >= n:
            break
        if x['id'] not in seen:
            picked.append(x)
            seen.add(x['id'])
    return sorted(picked, key=lambda x: x['area'])[:n]


def write_fixtures(out_root, pack, manifest, rows, n=6):
    src = os.path.join(out_root, pack)
    dst = os.path.join(FIXTURES, pack)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.join(dst, 'plans'), exist_ok=True)
    picked = pick_fixtures(rows, n)
    for x in picked:
        shutil.copyfile(os.path.join(src, 'plans', x['id'] + '.json'), os.path.join(dst, 'plans', x['id'] + '.json'))
    m = dict(manifest)
    m['count'] = {'unit': 0, 'floor': 0, 'house': len(picked)}
    m['notes'] = 'TEST FIXTURE — %d plans copied from the %s pack. %s' % (len(picked), pack, manifest['notes'])
    write_pack(FIXTURES, pack, m, picked)
    return picked


# ── main ──────────────────────────────────────────────────────────────────────


if __name__ == '__main__':  # the CLI lives in plans_convert_houses_cli
    from zyg_workflows.tools.plans_convert_houses_cli import main as _cli_main

    raise SystemExit(_cli_main())
