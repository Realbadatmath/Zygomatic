#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""plans_convert_swiss.py — convert Swiss Dwellings v3.0.0 into plan packs.

Source (already on disk, never downloaded here):
    data/assets/floor_plans/swiss_dwellings/swiss-dwellings-v3.0.0.zip
    Swiss Dwellings v3.0.0 (Archilyse AG), CC BY 4.0, doi:10.5281/zenodo.7788422

Writes the plan-pack contract (one JSON per plan + index.json + pack.json +
stats.json) under data/architecture/plans/swiss_dwellings/.

    python tools/plans_convert_swiss.py                    # full convert
    python tools/plans_convert_swiss.py --limit-floors 40   # smoke run
    python tools/plans_convert_swiss.py --fixture           # build the test fixture
    python tools/plans_convert_swiss.py --inspect           # print source vocabulary

Coordinate rule: source x is east, source y is NORTH, so z = -y; every plan is
then translated so its bbox min corner is (0, 0) and rounded to 3 decimals.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import math
import os
import random
import shutil
import sys
import time
import zipfile

import numpy as np
import pandas as pd
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
ZIP = os.path.join(CREWS, 'data', 'assets', 'floor_plans', 'swiss_dwellings', 'swiss-dwellings-v3.0.0.zip')
MEMBER = 'swiss-dwellings-v3.0.0/geometries.csv'
OUT = os.path.join(CREWS, 'data', 'architecture', 'plans', 'swiss_dwellings')
FIXTURE = os.path.join(CREWS, 'tests_arch_ext', 'fixtures', 'plans', 'swiss_dwellings')

PACK = 'swiss_dwellings'
SOURCE_URL = 'https://zenodo.org/records/7788422'
DOI = '10.5281/zenodo.7788422'
LICENCE = 'CC BY 4.0'
ATTRIBUTION = 'Floor plans: Swiss Dwellings v3.0.0 (Archilyse AG), CC BY 4.0, doi:10.5281/zenodo.7788422'

# ── source vocabulary -> schema vocabulary ───────────────────────────────────
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

AREA_MAP = {
    'LIVING_ROOM': 'living',
    'LIVING_DINING': 'living',
    'DINING': 'living',
    'KITCHEN_DINING': 'living',
    'STUDIO': 'living',
    'COMMUNITY_ROOM': 'living',
    'BEDROOM': 'bedroom',
    'KITCHEN': 'kitchen',
    'COMMON_KITCHEN': 'kitchen',
    'BATHROOM': 'bathroom',
    'SANITARY_ROOMS': 'bathroom',
    'CORRIDOR': 'hall',
    'CORRIDORS_AND_HALLS': 'hall',
    'LOBBY': 'hall',
    'FOYER': 'hall',
    'CLOAKROOM': 'hall',
    'RECEPTION_ROOM': 'hall',
    'BALCONY': 'balcony',
    'LOGGIA': 'balcony',
    'TERRACE': 'balcony',
    'WINTERGARTEN': 'balcony',
    'PATIO': 'balcony',
    'GARDEN': 'balcony',
    'ARCADE': 'balcony',
    'STOREROOM': 'storage',
    'BASEMENT_COMPARTMENT': 'storage',
    'BIKE_STORAGE': 'storage',
    'PRAM': 'storage',
    'PRAM_AND_BIKE_STORAGE_ROOM': 'storage',
    'ARCHIVE': 'storage',
    'WAREHOUSE': 'storage',
    'COLD_STORAGE': 'storage',
    'WASH_AND_DRY_ROOM': 'storage',
    'BASEMENT': 'storage',
    'SHELTER': 'storage',
    'GARAGE': 'storage',
    'STAIRCASE': 'stair',
    'ELEVATOR': 'lift',
    'ELEVATOR_FACILITIES': 'lift',
    'TRANSPORT_SHAFT': 'lift',
    'SHAFT': 'shaft',
    'LIGHTWELL': 'shaft',
    'VOID': 'shaft',
    'OUTDOOR_VOID': 'shaft',
    'AIR': 'shaft',
}
# ROOM is resolved per unit (largest -> living when the unit has no living room)
GENERIC_ROOM = 'ROOM'
OUTDOOR = {'balcony'}
FEATURE_MAP = {'TOILET': 'toilet', 'SINK': 'sink', 'BATHTUB': 'bathtub', 'SHOWER': 'shower', 'KITCHEN': 'kitchen'}
KEEP_FEATURES = set(FEATURE_MAP)
KEEP_SUB = {
    'area': None,
    'separator': {'WALL'},
    'opening': {'DOOR', 'ENTRANCE_DOOR', 'WINDOW'},
    'feature': KEEP_FEATURES,
}

MIN_SEG = 0.25  # shorter wall centrelines are dropped
EXT_TOL = 0.15  # a centreline this close to the boundary is external
UNIT_AREA = (25.0, 250.0)
UNIT_FILL = 0.55
UNIT_MAX_WALLS = 60
FLOOR_FILL = 0.60
FLOOR_SIDE = (4.0, 80.0)


# ── geometry helpers ─────────────────────────────────────────────────────────
def _flip(geoms):
    """Source (x, y-north) -> plan (x, z-south)."""
    return shapely.transform(geoms, lambda a: np.column_stack([a[:, 0], -a[:, 1]]))


def _polys(geom):
    """Every Polygon inside a geometry, largest first."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    if geom.geom_type.startswith('Multi') or geom.geom_type == 'GeometryCollection':
        out = []
        for g in geom.geoms:
            out += _polys(g)
        return sorted(out, key=lambda p: -p.area)
    return []


def mrr_axis(poly):
    """(a, b, t, length) of a polygon's minimum rotated rectangle centreline."""
    try:
        mrr = poly.minimum_rotated_rectangle
    except Exception:
        return None
    if mrr is None or mrr.is_empty or mrr.geom_type != 'Polygon':
        return None
    cs = list(mrr.exterior.coords)[:4]
    if len(cs) < 4:
        return None
    edges = [(cs[i], cs[(i + 1) % 4]) for i in range(4)]
    lens = [math.dist(a, b) for a, b in edges]
    i = max(range(4), key=lambda k: lens[k])
    L, t = lens[i], lens[(i + 1) % 4]
    if L <= 1e-9:
        return None
    (ax, az), (bx, bz) = edges[i]
    ux, uz = (bx - ax) / L, (bz - az) / L
    cx, cz = mrr.centroid.x, mrr.centroid.y
    return ((cx - ux * L / 2, cz - uz * L / 2), (cx + ux * L / 2, cz + uz * L / 2), t, L)


def _reflex(poly):
    """Concave vertices of a polygon's exterior ring."""
    p = orient(poly, 1.0)
    cs = list(p.exterior.coords)[:-1]
    n = len(cs)
    out = []
    for i in range(n):
        x0, y0 = cs[i - 1]
        x1, y1 = cs[i]
        x2, y2 = cs[(i + 1) % n]
        if (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1) < -1e-9:
            out.append(cs[i])
    return out


def rect_pieces(poly, depth=0, out=None):
    """Cut a separator polygon into near-rectangles along axis-aligned lines
    through its concave vertices (the brief's rule; depth-capped at 8 pieces)."""
    if out is None:
        out = []
    if poly is None or poly.is_empty or poly.area < 0.004:
        return out
    r = mrr_axis(poly)
    if r is None:
        return out
    mrr_area = r[2] * r[3]
    if depth >= 3 or mrr_area <= 1e-9 or poly.area / mrr_area >= 0.85:
        out.append(poly)
        return out
    minx, miny, maxx, maxy = poly.bounds
    for vx, vy in _reflex(poly):
        for line in (
            LineString([(vx, miny - 1.0), (vx, maxy + 1.0)]),
            LineString([(minx - 1.0, vy), (maxx + 1.0, vy)]),
        ):
            try:
                parts = [q for q in split(poly, line).geoms if q.area > 0.008]
            except Exception as _exc:
                _zyg_log.debug('polygon split skipped: %s', _exc)
                continue
            if len(parts) >= 2:
                for q in parts:
                    rect_pieces(q, depth + 1, out)
                return out
    out.append(poly)
    return out


def wall_segments(polys):
    """WALL separator polygons -> centreline segments [{'a','b','t'}]."""
    segs = []
    for poly in polys:
        for piece in rect_pieces(poly):
            r = mrr_axis(piece)
            if r is None:
                continue
            a, b, t, L = r
            if L < MIN_SEG:
                continue
            segs.append({'a': a, 'b': b, 't': min(max(t, 0.05), 0.8), '_ls': LineString([a, b])})
    return segs


def _boundary(polys):
    """Outer polygon of a set of area polygons (holes dropped)."""
    if not polys:
        return None
    try:
        uni = unary_union(polys)
    except Exception:
        try:
            uni = unary_union([p.buffer(0) for p in polys])
        except Exception:
            return None
    parts = _polys(uni)
    if len(parts) > 1:
        try:
            closed = unary_union([p.buffer(0.2, join_style=2) for p in parts]).buffer(-0.2, join_style=2)
            parts = _polys(closed) or parts
        except Exception as _exc:
            _zyg_log.debug('boundary closing skipped, using the raw parts: %s', _exc)
    if not parts:
        return None
    big = parts[0]
    try:
        b = Polygon(big.exterior).simplify(0.02)
    except Exception:
        return None
    if b.is_empty or not b.is_valid:
        b = b.buffer(0)
        b = _polys(b)[0] if _polys(b) else None
    return b


def _ring(poly):
    """CCW exterior ring as a list of [x, z], first point not repeated."""
    p = orient(poly, 1.0)
    return [[c[0], c[1]] for c in list(p.exterior.coords)[:-1]]


def _side(x, z, minx, minz, maxx, maxz):
    """Which bbox side a point sits nearest (north = -Z)."""
    d = {'west': x - minx, 'east': maxx - x, 'north': z - minz, 'south': maxz - z}
    return min(d, key=d.get)


def _near_wall(segs, pt):
    """Index of the wall segment nearest a point (-1 when there are none)."""
    best, bi = 1e18, -1
    for i, s in enumerate(segs):
        dd = s['_ls'].distance(pt)
        if dd < best:
            best, bi = dd, i
    return bi


def _room_type(sub, unit_has_living, is_biggest_generic):
    if sub == GENERIC_ROOM:
        return 'bedroom' if (unit_has_living or not is_biggest_generic) else 'living'
    return AREA_MAP.get(sub, 'other')


# ── plan assembly ────────────────────────────────────────────────────────────
def _finalise(plan, pts_sources):
    """Translate a plan so its bbox min is (0,0), round, set w/d/area/fill."""
    xs, zs = [], []
    for seq in pts_sources:
        for x, z in seq:
            xs.append(x)
            zs.append(z)
    if not xs:
        return None
    minx, minz, maxx, maxz = min(xs), min(zs), max(xs), max(zs)
    w, d = maxx - minx, maxz - minz
    if w <= 0.5 or d <= 0.5:
        return None

    def T(x, z):
        return [round(x - minx, 3), round(z - minz, 3)]

    plan['boundary'] = [T(x, z) for x, z in plan['boundary']]
    for r in plan['rooms']:
        r['pts'] = [T(x, z) for x, z in r['pts']]
        r['area'] = round(r['area'], 3)
    for wl in plan['walls']:
        wl['a'] = T(*wl['a'])
        wl['b'] = T(*wl['b'])
        wl['t'] = round(wl['t'], 3)
    for o in plan['doors'] + plan['windows'] + plan['fixtures']:
        o['x'], o['z'] = T(o['x'], o['z'])
    if plan.get('entrance'):
        e = plan['entrance']
        e['x'], e['z'] = T(e['x'], e['z'])
    for key in ('stairs', 'lifts'):
        if plan.get('core'):
            plan['core'][key] = [[T(x, z) for x, z in ring] for ring in plan['core'][key]]
    plan['w'] = round(w, 3)
    plan['d'] = round(d, 3)
    plan['area'] = round(plan['area'], 3)
    plan['_off'] = (-minx, -minz)  # raw source coord + _off = plan coord
    return plan


def _row(plan):
    fill = plan['area'] / (plan['w'] * plan['d']) if plan['w'] * plan['d'] > 0 else 0.0
    return {
        'id': plan['id'],
        'kind': plan['kind'],
        'w': plan['w'],
        'd': plan['d'],
        'area': plan['area'],
        'n_rooms': len(plan['rooms']),
        'types': ','.join(r['type'] for r in plan['rooms']),
        'entrance': (plan['entrance'] or {}).get('side'),
        'fill': round(fill, 3),
    }


def build_plan(
    plan_id, kind, area_recs, segs, openings, features, storey_h, core_recs=None, unit_ids=None, source=None
):
    """Assemble one plan dict from already-flipped source geometry."""
    polys = [a['g'] for a in area_recs]
    bnd = _boundary(polys)
    if bnd is None or bnd.area < 4.0:
        return None
    bring = _ring(bnd)
    if len(bring) < 4:
        return None
    bnd_ext = bnd.exterior
    keep = bnd.buffer(0.35)

    # rooms (ROOM resolved per unit group)
    by_unit = collections.defaultdict(list)
    for a in area_recs:
        by_unit[a['unit']].append(a)
    rooms = []
    for _u, recs in by_unit.items():
        has_living = any(AREA_MAP.get(r['sub']) == 'living' for r in recs)
        generics = sorted([r for r in recs if r['sub'] == GENERIC_ROOM], key=lambda r: -r['g'].area)
        biggest = generics[0] if generics else None
        for r in recs:
            g = r['g']
            if g.is_empty or g.area < 0.6:
                continue
            if not keep.intersects(g.representative_point()):
                continue
            for p in _polys(g)[:1]:
                pts = _ring(p)
                if len(pts) < 3:
                    continue
                t = _room_type(r['sub'], has_living, r is biggest)
                rooms.append(
                    {'type': t, 'pts': pts, 'area': p.area, 'name': r['sub'].replace('_', ' ').title(), '_g': p}
                )
    if len(rooms) < 2:
        return None

    # walls that touch this plan
    near = bnd.buffer(0.3)
    walls = []
    for s in segs:
        ls = s['_ls']
        if not near.intersects(ls):
            continue
        # a party wall runs past the unit: keep only the part that serves it
        inter = ls if near.contains(ls) else near.intersection(ls)
        parts = [inter] if inter.geom_type == 'LineString' else list(getattr(inter, 'geoms', []))
        for part in parts:
            if part.is_empty or part.geom_type != 'LineString' or part.length < MIN_SEG:
                continue
            cs = list(part.coords)
            a, b = tuple(cs[0]), tuple(cs[-1])
            mid = part.interpolate(0.5, normalized=True)
            ext = (
                bnd_ext.distance(mid) <= EXT_TOL
                and max(bnd_ext.distance(Point(*a)), bnd_ext.distance(Point(*b))) <= 0.45
            )
            walls.append({'a': a, 'b': b, 't': s['t'], 'ext': bool(ext), '_ls': LineString([a, b])})
    if not walls:
        return None

    minx, minz, maxx, maxz = bnd.bounds
    doors, windows, entrance = [], [], None
    for o in openings:
        pt = o['pt']
        if not near.intersects(pt):
            continue
        wi = _near_wall(walls, pt)
        if wi < 0:
            continue
        if o['sub'] == 'WINDOW':
            windows.append({'x': pt.x, 'z': pt.y, 'w': round(o['w'], 3), 'wall': wi, 'sill': o['sill'], 'h': o['h']})
        else:
            k = 'entrance' if o['sub'] == 'ENTRANCE_DOOR' else 'door'
            doors.append({'x': pt.x, 'z': pt.y, 'w': round(o['w'], 3), 'wall': wi, 'kind': k})
            if k == 'entrance' and entrance is None:
                entrance = {'side': _side(pt.x, pt.y, minx, minz, maxx, maxz), 'x': pt.x, 'z': pt.y}

    bathish = [r['_g'] for r in rooms if r['type'] in ('bathroom', 'wc')]
    fixtures = []
    for f in features:
        pt = f['pt']
        if not keep.intersects(pt):
            continue
        k = FEATURE_MAP.get(f['sub'])
        if k == 'sink' and any(b.buffer(0.2).contains(pt) for b in bathish):
            k = 'washbasin'
        fixtures.append({'kind': k, 'x': pt.x, 'z': pt.y, 'ry': round(f['ry'], 4)})

    core = None
    if core_recs is not None:
        core = {'stairs': [], 'lifts': []}
        for c in core_recs:
            for p in _polys(c['g'])[:1]:
                core['stairs' if c['kind'] == 'stair' else 'lifts'].append(_ring(p))

    plan = {
        'id': plan_id,
        'pack': PACK,
        'kind': kind,
        'w': 0.0,
        'd': 0.0,
        'area': bnd.area,
        'storey_h': storey_h,
        'boundary': bring,
        'rooms': [{'type': r['type'], 'pts': r['pts'], 'area': r['area'], 'name': r['name']} for r in rooms],
        'walls': [{'a': w['a'], 'b': w['b'], 't': w['t'], 'ext': w['ext']} for w in walls],
        'doors': doors,
        'windows': windows,
        'fixtures': fixtures,
        'entrance': entrance,
        'core': core,
        'units': unit_ids,
        'source': source or {},
        'mirror_ok': True,
    }
    srcs = [bring] + [r['pts'] for r in rooms] + [[w['a'], w['b']] for w in walls]
    srcs += [[(o['x'], o['z'])] for o in doors + windows + fixtures]
    if entrance:
        srcs.append([(entrance['x'], entrance['z'])])
    if core:
        srcs += core['stairs'] + core['lifts']
    plan = _finalise(plan, srcs)
    if plan is None:
        return None
    # keep the geometry handles for stats, stripped before writing
    plan['_rooms_g'] = [r['_g'] for r in rooms]
    plan['_bnd'] = bnd
    return plan


# ── stats ────────────────────────────────────────────────────────────────────
class Stats:
    SIZES = ((25, 50), (50, 80), (80, 120), (120, 250))

    def __init__(self):
        self.area = collections.defaultdict(list)
        self.minw = collections.defaultdict(list)
        self.by_size = {
            f'{a}-{b}': {'n': 0, 'rooms': collections.Counter(), 'types': collections.Counter()} for a, b in self.SIZES
        }
        self.adj = collections.Counter()
        self.door_w = collections.defaultdict(list)
        self.win_per_m = collections.defaultdict(list)

    def add_unit(self, plan):
        rg = plan['_rooms_g']
        rooms = plan['rooms']
        for r, g in zip(rooms, rg):
            self.area[r['type']].append(r['area'])
            ax = mrr_axis(g)
            if ax:
                self.minw[r['type']].append(round(ax[2], 3))
        cls = None
        for a, b in self.SIZES:
            if a <= plan['area'] < b:
                cls = f'{a}-{b}'
        if cls:
            s = self.by_size[cls]
            s['n'] += 1
            s['rooms'][len(rooms)] += 1
            for r in rooms:
                s['types'][r['type']] += 1
        # doors: which rooms they touch (room geometry is still in source coords)
        ox, oz = plan['_off']
        for d in plan['doors']:
            p = Point(d['x'] - ox, d['z'] - oz)
            hit = [rooms[i]['type'] for i, g in enumerate(rg) if g.distance(p) <= 0.8]
            hit = sorted(set(hit))
            for t in hit:
                self.door_w[t].append(d['w'])
            for i in range(len(hit)):
                for j in range(i + 1, len(hit)):
                    self.adj[(hit[i], hit[j])] += 1
        # windows per metre of exterior wall, per room
        ext_ls = [LineString([w['a'], w['b']]) for w in plan['walls'] if w['ext']]
        if ext_ls:
            for i, g in enumerate(rg):
                gp = shapely.affinity.translate(g, xoff=ox, yoff=oz)
                near = gp.buffer(0.5)
                L = sum(near.intersection(e).length for e in ext_ls)
                if L < 0.8:
                    continue
                wsum = sum(w['w'] for w in plan['windows'] if near.contains(Point(w['x'], w['z'])))
                self.win_per_m[rooms[i]['type']].append(round(wsum / L, 4))

    @staticmethod
    def _q(v):
        if not v:
            return None
        a = np.asarray(v, dtype=float)
        return {
            'n': int(a.size),
            'median': round(float(np.median(a)), 3),
            'p25': round(float(np.percentile(a, 25)), 3),
            'p75': round(float(np.percentile(a, 75)), 3),
        }

    def dump(self):
        rooms = {}
        for t in sorted(set(list(self.area) + list(self.minw))):
            rooms[t] = {
                'area': self._q(self.area.get(t)),
                'min_width_median': (round(float(np.median(self.minw[t])), 3) if self.minw.get(t) else None),
            }
        sizes = {}
        for k, s in self.by_size.items():
            sizes[k] = {
                'n_units': s['n'],
                'room_count': {str(a): b for a, b in sorted(s['rooms'].items())},
                'type_counts': dict(sorted(s['types'].items(), key=lambda kv: -kv[1])),
            }
        return {
            'pack': PACK,
            'rooms': rooms,
            'unit_size_classes': sizes,
            'adjacency': {f'{a}|{b}': n for (a, b), n in sorted(self.adj.items(), key=lambda kv: -kv[1])},
            'door_width_median': {t: round(float(np.median(v)), 3) for t, v in sorted(self.door_w.items()) if v},
            'window_width_per_m_ext_wall': {
                t: round(float(np.median(v)), 4) for t, v in sorted(self.win_per_m.items()) if v
            },
            'generated': _dt.datetime.now().astimezone().isoformat(timespec='seconds'),
        }


# ── source reading ───────────────────────────────────────────────────────────
COLS = [
    'apartment_id',
    'site_id',
    'building_id',
    'plan_id',
    'floor_id',
    'unit_id',
    'unit_usage',
    'entity_type',
    'entity_subtype',
    'geometry',
    'elevation',
    'height',
]


def load_frame(limit_floors=0, log=print):
    """Stream geometries.csv, keep the rows we convert, return it sorted by floor."""
    t0 = time.time()
    z = zipfile.ZipFile(ZIP)
    keep = []
    rows = 0
    with z.open(MEMBER) as f:
        for ch in pd.read_csv(f, usecols=COLS, chunksize=400_000):
            rows += len(ch)
            et = ch['entity_type'].astype('string')
            sub = ch['entity_subtype'].astype('string')
            m = et == 'area'
            m |= (et == 'separator') & (sub == 'WALL')
            m |= (et == 'opening') & sub.isin(['DOOR', 'ENTRANCE_DOOR', 'WINDOW'])
            m |= (et == 'feature') & sub.isin(sorted(KEEP_FEATURES))
            part = ch[m.fillna(False).to_numpy()]
            if len(part):
                keep.append(part)
            if rows % 2_000_000 < 400_000:
                log(f'  read {rows:,} rows ({time.time() - t0:.0f}s)')
    df = pd.concat(keep, ignore_index=True)
    del keep
    df = df[df['floor_id'].notna()]
    df['floor_id'] = df['floor_id'].astype('int64')
    df = df.sort_values('floor_id', kind='stable').reset_index(drop=True)
    if limit_floors:
        fids = pd.unique(df['floor_id'])[:limit_floors]
        df = df[df['floor_id'].isin(fids)].reset_index(drop=True)
    log(f'  kept {len(df):,} of {rows:,} rows, {df["floor_id"].nunique():,} floors ({time.time() - t0:.0f}s)')
    return df


def floor_groups(df):
    fid = df['floor_id'].to_numpy()
    start = 0
    for i in range(1, len(fid) + 1):
        if i == len(fid) or fid[i] != fid[start]:
            yield int(fid[start]), df.iloc[start:i]
            start = i


def _f(v, lo, hi, dflt):
    try:
        x = float(v)
    except Exception:
        return dflt
    if not math.isfinite(x) or not (lo <= x <= hi):
        return dflt
    return round(x, 3)


def convert(out_dir, limit_floors=0, log=print):
    os.makedirs(os.path.join(out_dir, 'plans'), exist_ok=True)
    df = load_frame(limit_floors, log=log)
    stats = Stats()
    rows, counts = [], collections.Counter()
    apt_units = df[df['entity_type'] == 'area'].groupby('apartment_id')['unit_id'].nunique()
    multi = set(apt_units[apt_units > 1].index)

    n_floor = 0
    t0 = time.time()
    for fid, g in floor_groups(df):
        n_floor += 1
        try:
            geoms = shapely.from_wkt(g['geometry'].to_numpy(dtype=object))
        except Exception as _exc:
            _zyg_log.warning('plan group skipped, its WKT geometry did not parse: %s', _exc)
            continue
        geoms = _flip(geoms)
        et = g['entity_type'].to_numpy()
        sub = g['entity_subtype'].to_numpy()
        uid = g['unit_id'].to_numpy()
        aid = g['apartment_id'].to_numpy()
        use = g['unit_usage'].to_numpy()
        elev = g['elevation'].to_numpy()
        hgt = g['height'].to_numpy()

        areas, wallp, openings, features = [], [], [], []
        heights = []
        for i in range(len(g)):
            geom = geoms[i]
            if geom is None or geom.is_empty:
                continue
            t, s = et[i], sub[i]
            if t == 'area':
                for p in _polys(geom)[:1]:
                    areas.append({'unit': uid[i], 'apt': aid[i], 'use': use[i], 'sub': str(s), 'g': p})
                    hh = _f(hgt[i], 2.0, 4.5, None)
                    if hh:
                        heights.append(hh)
            elif t == 'separator':
                wallp += _polys(geom)
            elif t == 'opening':
                ax = mrr_axis(geom)
                if ax is None:
                    continue
                openings.append(
                    {
                        'sub': str(s),
                        'pt': geom.centroid,
                        'w': ax[3],
                        'sill': _f(elev[i], 0.0, 2.2, 0.9) if s == 'WINDOW' else 0.0,
                        'h': _f(hgt[i], 0.3, 3.2, 1.4) if s == 'WINDOW' else 2.1,
                    }
                )
            elif t == 'feature':
                ax = mrr_axis(geom)
                if ax is None:
                    continue
                (x0, z0), (x1, z1) = ax[0], ax[1]
                features.append({'sub': str(s), 'pt': geom.centroid, 'ry': math.atan2(-(z1 - z0), x1 - x0)})
        if not areas:
            continue
        storey_h = round(float(np.median(heights)) + 0.1, 2) if heights else 2.7
        storey_h = min(max(storey_h, 2.2), 4.2)
        segs = wall_segments(wallp)
        if not segs:
            continue

        src_common = {'floor_id': fid}
        for k in ('site_id', 'building_id', 'plan_id'):
            try:
                src_common[k] = int(g.iloc[0][k])
            except Exception as _exc:
                _zyg_log.debug('source column %s is not an int, omitted: %s', k, _exc)

        # ── units ───────────────────────────────────────────────────────────
        res = collections.defaultdict(list)
        for a in areas:
            if a['use'] == 'RESIDENTIAL' and pd.notna(a['unit']):
                res[a['unit']].append(a)
        floor_unit_ids = []
        for u, recs in res.items():
            apt = next((r['apt'] for r in recs if isinstance(r['apt'], str)), None)
            if not apt:
                continue
            pid = f'sd_u_{apt}' + (f'_{int(u)}' if apt in multi else '')
            plan = build_plan(
                pid,
                'unit',
                recs,
                segs,
                openings,
                features,
                storey_h,
                source=dict(src_common, apartment_id=apt, unit_id=int(u)),
            )
            if plan is None:
                continue
            if not (UNIT_AREA[0] <= plan['area'] <= UNIT_AREA[1]):
                continue
            if len(plan['walls']) > UNIT_MAX_WALLS or len(plan['rooms']) < 2:
                continue
            if not plan['entrance']:
                continue
            fill = plan['area'] / (plan['w'] * plan['d'])
            if fill < UNIT_FILL:
                continue
            stats.add_unit(plan)
            floor_unit_ids.append(pid)
            _write(out_dir, plan)
            rows.append(_row(plan))
            counts['unit'] += 1
            if counts['unit'] % 1000 == 0:
                log(
                    f'  {counts["unit"]:,} units, {counts["floor"]:,} floors, '
                    f'{n_floor:,} source floors ({time.time() - t0:.0f}s)'
                )

        # ── floor ───────────────────────────────────────────────────────────
        if len(res) >= 2:
            core = [
                {'kind': 'stair' if AREA_MAP.get(a['sub']) == 'stair' else 'lift', 'g': a['g']}
                for a in areas
                if AREA_MAP.get(a['sub']) in ('stair', 'lift')
            ]
            plan = build_plan(
                f'sd_f_{fid}',
                'floor',
                areas,
                segs,
                openings,
                features,
                storey_h,
                core_recs=core,
                unit_ids=floor_unit_ids,
                source=dict(src_common),
            )
            if plan is not None:
                fill = plan['area'] / (plan['w'] * plan['d'])
                ok = (
                    fill >= FLOOR_FILL
                    and FLOOR_SIDE[0] <= plan['w'] <= FLOOR_SIDE[1]
                    and FLOOR_SIDE[0] <= plan['d'] <= FLOOR_SIDE[1]
                )
                if ok:
                    _write(out_dir, plan)
                    rows.append(_row(plan))
                    counts['floor'] += 1

    manifest = {
        'pack': PACK,
        'title': 'Swiss Dwellings v3.0.0',
        'source_url': SOURCE_URL,
        'version': '3.0.0',
        'licence': LICENCE,
        'attribution': ATTRIBUTION,
        'doi': DOI,
        'count': {'unit': counts['unit'], 'floor': counts['floor'], 'house': 0},
        'converted': _dt.datetime.now().astimezone().isoformat(timespec='seconds'),
        'notes': (
            'Converted from geometries.csv by tools/plans_convert_swiss.py. '
            'Source y (north) negated so +Z is south, per the studio plan axes. '
            'Wall polygons reduced to centrelines via minimum rotated rectangles.'
        ),
    }
    _dump(os.path.join(out_dir, 'pack.json'), manifest)
    _dump(os.path.join(out_dir, 'index.json'), {'pack': manifest, 'rows': rows})
    _dump(os.path.join(out_dir, 'stats.json'), stats.dump())
    log(f'DONE {counts["unit"]:,} units, {counts["floor"]:,} floors in {time.time() - t0:.0f}s -> {out_dir}')
    return manifest


def _write(out_dir, plan):
    p = {k: v for k, v in plan.items() if not k.startswith('_')}
    _dump(os.path.join(out_dir, 'plans', p['id'] + '.json'), p)


def _dump(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(obj, fh, separators=(',', ':'))
    os.replace(tmp, path)


# ── fixture ──────────────────────────────────────────────────────────────────
def build_fixture(src=OUT, dst=FIXTURE, log=print):
    """Copy 12 varied real units + 3 floors (one near 20x20 m) into the fixture."""
    idx = json.load(open(os.path.join(src, 'index.json')))
    rows = idx['rows']
    units = [r for r in rows if r['kind'] == 'unit']
    floors = [r for r in rows if r['kind'] == 'floor']
    rnd = random.Random(20260910)

    picked, seen = [], set()

    def take(pred, n=1):
        pool = [r for r in units if r['id'] not in seen and pred(r)]
        rnd.shuffle(pool)
        for r in pool[:n]:
            seen.add(r['id'])
            picked.append(r)
        return len(pool[:n])

    # ~20 x 10 m, ~6 x 12 m and its rotated twin
    take(lambda r: 18 <= max(r['w'], r['d']) <= 22 and 8 <= min(r['w'], r['d']) <= 12)
    take(lambda r: r['w'] <= 7.5 and 10 <= r['d'] <= 14)
    take(lambda r: r['d'] <= 7.5 and r['w'] >= 10)
    take(lambda r: r['area'] < 45, 2)
    take(lambda r: 45 <= r['area'] < 70, 2)
    take(lambda r: 70 <= r['area'] < 100, 2)
    take(lambda r: 100 <= r['area'] < 150, 2)
    take(lambda r: r['area'] >= 150, 1)
    while len(picked) < 12:
        if not take(lambda r: True, 12 - len(picked)):
            break

    fl = [r for r in floors if 17 <= r['w'] <= 23 and 17 <= r['d'] <= 23 and r['fill'] >= 0.8]
    fl.sort(key=lambda r: -r['fill'])
    fpick = fl[:1]
    rest = [r for r in floors if r['id'] not in {x['id'] for x in fpick}]
    rnd.shuffle(rest)
    fpick += sorted(rest, key=lambda r: -r['n_rooms'])[:1] + rest[:1]
    fpick = list({r['id']: r for r in fpick}.values())[:3]

    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.join(dst, 'plans'), exist_ok=True)
    keep = picked[:12] + fpick
    for r in keep:
        shutil.copyfile(os.path.join(src, 'plans', r['id'] + '.json'), os.path.join(dst, 'plans', r['id'] + '.json'))
    man = dict(idx['pack'])
    man['count'] = {
        'unit': sum(1 for r in keep if r['kind'] == 'unit'),
        'floor': sum(1 for r in keep if r['kind'] == 'floor'),
        'house': 0,
    }
    man['notes'] = 'Test fixture: real converted plans copied from the full pack. ' + man['notes']
    man['fixture_of'] = PACK
    _dump(os.path.join(dst, 'pack.json'), man)
    _dump(os.path.join(dst, 'index.json'), {'pack': man, 'rows': keep})
    shutil.copyfile(os.path.join(src, 'stats.json'), os.path.join(dst, 'stats.json'))
    log('fixture: ' + ', '.join(f'{r["id"]} {r["kind"]} {r["w"]}x{r["d"]} {r["area"]}m2' for r in keep))
    return man


def inspect(log=print):
    z = zipfile.ZipFile(ZIP)
    log('members:')
    for i in z.infolist():
        log(f'  {i.file_size:>14,}  {i.filename}')
    c = collections.Counter()
    use = collections.Counter()
    with z.open(MEMBER) as f:
        head = f.read(2000).decode('utf-8', 'replace').split('\n')[0]
    log('geometries.csv header: ' + head.strip())
    with z.open(MEMBER) as f:
        for ch in pd.read_csv(f, usecols=['unit_usage', 'entity_type', 'entity_subtype'], chunksize=500_000, dtype=str):
            c.update(zip(ch['entity_type'].fillna('NA'), ch['entity_subtype'].fillna('NA')))
            use.update(ch['unit_usage'].fillna('NA'))
    log('unit_usage: ' + json.dumps(dict(use)))
    for t in sorted({a for a, _ in c}):
        log(f'-- {t}: ' + ', '.join(f'{s}={n}' for (tt, s), n in sorted(c.items()) if tt == t))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--fixture-dir', default=FIXTURE)
    ap.add_argument('--limit-floors', type=int, default=0)
    ap.add_argument('--inspect', action='store_true')
    ap.add_argument('--fixture', action='store_true', help='only rebuild the fixture')
    a = ap.parse_args(argv)
    if a.inspect:
        inspect()
        return 0
    if not a.fixture:
        convert(a.out, a.limit_floors)
    build_fixture(a.out, a.fixture_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
