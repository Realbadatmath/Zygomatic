# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sightline_rules — is the entrance actually VISIBLE from the approach? (2026-09-10)

Why this family exists: in job 71ac02b0 design_rules.check_entrance (a PLAN
test — anything whose crown overlaps a 4 m strip 12 m out) went quiet the
moment the trees were nudged 7-8 cells off the axis, and yet the eye-level
render still had crowns hanging across the door. A plan strip is not a line of
sight: what matters is the SEGMENT from a person's eye on the approach to the
door, in three dimensions, and what that segment passes through.

So this check casts real sightlines. For every ground-floor door: an eye at
1.6 m standing on the entrance axis 30, 15 and 8 m out, looking at the door
at 1.1 m. Anything the segment passes through is named — tree crowns as
spheres, everything else as its own rotated box. The door's own host wall,
the openings, the ground/paving kinds and the entrance group's own overhead
(a canopy soffit) are not obstacles; a hedge, a garden wall, a parked van, a
low spreading tree, a plant room in the forecourt are.

No new kinds, no tools. DESIGN_CHECKS = [check_sightline]; design_rules'
run_checks() picks it up and the `done` gate enforces the errors.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import Drawing, EXT_MODULES, _num, ground_height, is_opening, world_to_local

KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []

EYE_OUT = (30.0, 15.0, 8.0)  # where a person stands on the approach, metres out from the door
EYE_Y = 1.6  # eye height
TARGET_Y = 1.1  # what they look at: the middle of the door leaf
OFF_AXIS = 6.0  # the advice: get the obstacle this far off the axis
OVERHEAD = 2.2  # the entrance group's own stuff above this is soffit, not obstacle
PAVED_LEN = 30.0  # the approach that wants a surface...
PAVED_NEAR = 4.0  # ...and how near the axis it has to come
MAX_NAMED = 4  # obstacles named in one finding

# ground, surfacing and paper: never an obstacle to an eye at 1.6 m
GROUND_KINDS = (
    'ground',
    'terrain',
    'pad',
    'road',
    'road_curved',
    'path',
    'sidewalk',
    'kerb',
    'parking_bay',
    'water_path',
    'water_plane',
    'lawn',
    'grass',
    'site_boundary',
    'zone',
    'gridline',
    'annotation',
    'dimension',
    'dim_linear',
    'dim_angle',
    'label_text',
    'markup_note',
    'guide_arc',
    'guide_path',
    'guide_poly',
    'floor_finish',
    'sun',
    'camera',
    'light_point',
    'light_sun',
)
# a surfaced approach: one of these near the axis and the door is not on bare ground
PAVED_KINDS = ('road', 'road_curved', 'path', 'sidewalk', 'kerb', 'parking_bay', 'pad', 'ramp')
PAVED_WORDS = ('road', 'path', 'driv', 'pav', 'walk', 'forecourt', 'plaza', 'terrace')


# ── the two intersection routines (local, no dependency) ─────────────────────
def seg_sphere(p, q, c, r) -> bool:
    """Does segment p->q come within r of point c? (both are (x, y, z))."""
    dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
    ll = dx * dx + dy * dy + dz * dz
    if ll <= 1e-9:
        return (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2 <= r * r
    t = ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy + (c[2] - p[2]) * dz) / ll
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    ex, ey, ez = p[0] + t * dx - c[0], p[1] + t * dy - c[1], p[2] + t * dz - c[2]
    return ex * ex + ey * ey + ez * ez <= r * r


def seg_aabb(p, q, lo, hi) -> bool:
    """Slab test: does segment p->q enter the axis-aligned box lo..hi?"""
    t0, t1 = 0.0, 1.0
    for i in (0, 1, 2):
        dd = q[i] - p[i]
        if abs(dd) < 1e-9:
            if p[i] < lo[i] - 1e-9 or p[i] > hi[i] + 1e-9:
                return False
            continue
        a, b = (lo[i] - p[i]) / dd, (hi[i] - p[i]) / dd
        if a > b:
            a, b = b, a
        t0 = a if a > t0 else t0
        t1 = b if b < t1 else t1
        if t0 > t1:
            return False
    return True


# ── record geometry ──────────────────────────────────────────────────────────
def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _tree_height(o) -> float:
    """Total height of a tree record: parametric h, else the asset's own."""
    h = _p(o, 'h', 0.0)
    if h > 0:
        return h * (_num(o.get('s'), 1.0) or 1.0) if o.get('kind') == 'asset' else h
    if o.get('kind') == 'asset':
        sm = (o.get('p') or {}).get('size_m')
        if isinstance(sm, (list, tuple)) and len(sm) > 1:
            h = _num(sm[1], 0.0)
        if h <= 0:
            h = _p(o, 'bh', 0.0)
        if h > 0:
            return h * (_num(o.get('s'), 1.0) or 1.0)
    return 8.0


def _box_of(o):
    """(width along local +X, depth along local +Z, height) of a solid record."""
    p = o.get('p') or {}
    sc = _num(o.get('s'), 1.0) or 1.0
    w, dd = _num(p.get('w'), 0.0), _num(p.get('d'), 0.0)
    h = _num(p.get('h'), 0.0)
    if w <= 0 or dd <= 0:
        ln = _num(p.get('len'), 0.0)
        if ln > 0:
            w, dd = ln, (_num(p.get('t'), 0.0) or _num(p.get('w'), 0.0) or 0.2)
    if w <= 0 or dd <= 0:  # a placed asset carries its bounds
        w, dd = _num(p.get('bw'), 0.0), _num(p.get('bd'), 0.0)
        h = h or _num(p.get('bh'), 0.0)
    if w <= 0 or dd <= 0:
        r = _num(p.get('r'), 0.0)
        if r > 0:
            w = dd = 2 * r
    if h <= 0:
        h = _num(p.get('t'), 0.0)  # a slab/plate is as tall as it is thick
    if w <= 0 or dd <= 0 or h <= 0:
        return None
    return w * sc, dd * sc, h * sc


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


def _paved(d: Drawing, x0, z0, nx, nz) -> bool:
    """Is there a surfaced approach within PAVED_NEAR of the axis, 0..PAVED_LEN out?"""
    for o in d.objs:
        if o.get('hidden'):
            continue
        k = str(o.get('kind') or '')
        if k not in PAVED_KINDS and not any(w in k for w in PAVED_WORDS):
            continue
        box = _box_of(o)
        half = max(box[0], box[1]) / 2 if box else 0.0
        dx, dz = o['x'] - x0, o['z'] - z0
        along = dx * nx + dz * nz
        across = abs(dx * -nz + dz * nx)
        if along + half >= -1.0 and along - half <= PAVED_LEN and across - half <= PAVED_NEAR:
            return True
    return False


# ── the check ────────────────────────────────────────────────────────────────
def check_sightline(d: Drawing) -> list:
    DR = EXT_MODULES.get('design_rules')
    if DR is None:  # design_rules owns the door axis
        return []
    # 2026-09-11: an ENTRANCE is a door in an EXTERIOR wall at ground level. Job
    # 71ac02b0's replay flagged every room door on a partition ("door WC is hidden
    # from the drive") and the head-house door on the roof deck.
    doors = []
    for o in d.objs:
        if o.get('kind') not in DR.DOOR_KINDS or o.get('hidden'):
            continue
        if o['y'] - ground_height(d, o['x'], o['z']) > 0.5:
            continue
        host = DR._host_wall(d, o)
        if host is None or host.get('kind') not in ('wall', 'curtain_wall'):
            continue
        doors.append(o)
    if not doors:
        return []
    trees = [(o, DR._crown(o)) for o in d.objs if not o.get('hidden') and DR._crown(o) > 0]
    tree_ids = {t['id'] for t, _ in trees}
    out = []
    for door in doors:
        ax = DR._door_axis(d, door)
        if not ax:
            continue
        x0, z0, nx, nz = ax
        host = DR._host_wall(d, door)
        skip = {door['id']} | ({host['id']} if host else set())
        grp = door.get('grp') or None
        tgt = (x0, TARGET_Y, z0)
        hits: dict = {}
        for out_m in EYE_OUT:
            eye = (x0 + nx * out_m, EYE_Y, z0 + nz * out_m)
            for t, r in trees:
                if t['id'] in hits or t['id'] in skip:
                    continue
                if seg_sphere(eye, tgt, (t['x'], _tree_height(t) - r, t['z']), r):
                    along = (t['x'] - x0) * nx + (t['z'] - z0) * nz
                    hits[t['id']] = (along, f'{_lbl(t)} crosses the sightline {along:.1f} m out (crown {2 * r:.1f} m)')
            for o in d.objs:
                if o['id'] in hits or o['id'] in skip or o['id'] in tree_ids or o.get('hidden'):
                    continue
                k = o.get('kind')
                if k in GROUND_KINDS or is_opening(k):
                    continue
                if grp and o.get('grp') == grp and o['y'] > OVERHEAD:
                    continue  # the entrance's own canopy soffit
                box = _box_of(o)
                if box is None:
                    continue
                w, dd, h = box
                ex, ez = world_to_local(o, eye[0], eye[2])
                tx, tz = world_to_local(o, tgt[0], tgt[2])
                if seg_aabb((ex, eye[1], ez), (tx, tgt[1], tz), (-w / 2, o['y'], -dd / 2), (w / 2, o['y'] + h, dd / 2)):
                    along = (o['x'] - x0) * nx + (o['z'] - z0) * nz
                    hits[o['id']] = (along, f'{_lbl(o)} crosses the sightline {along:.1f} m out ({h:.1f} m tall)')
        if hits:
            named = [txt for _, txt in sorted(hits.values(), key=lambda v: -v[0])][:MAX_NAMED]
            more = len(hits) - len(named)
            out.append(
                {
                    'sev': 'error',
                    'code': 'sightline',
                    'text': f'entrance {_lbl(door)} is hidden from the drive: '
                    + '; '.join(named)
                    + (f'; and {more} more' if more > 0 else '')
                    + f' — move them >= {OFF_AXIS:g} m off the axis or lower the crown',
                }
            )
        elif not _paved(d, x0, z0, nx, nz):
            out.append(
                {
                    'sev': 'warn',
                    'code': 'approach',
                    'text': f'{_lbl(door)}: the door opens onto bare ground — add_road/add_path up to it',
                }
            )
    return out


DESIGN_CHECKS = [check_sightline]

PROMPT = (
    'SIGHTLINE: the entrance must be VISIBLE from the approach. design_check casts a real line of sight '
    'from an eye at 1.6 m standing 30, 15 and 8 m out on the entrance axis to the door at 1.1 m, and '
    'reports as an ERROR anything the line passes through — a tree crown (sphere), a hedge, a garden '
    'wall, a van. Off the plan strip is not the same as out of the way. It also warns when nothing '
    'paved reaches the door. Fix by moving the obstacle >= 6 m off the axis, or add_road up to the door.'
)

EXAMPLES = [
    {'ask': 'can you actually see the front door from the drive?', 'calls': [{'tool': 'design_check', 'args': {}}]},
    {
        'ask': 'the render has a tree over the entrance — check it and give the door a drive',
        'calls': [
            {'tool': 'design_check', 'args': {}},
            {'tool': 'add_road', 'args': {'cells': ['FH70', 'FH99'], 'width': 6}},
            {'tool': 'design_check', 'args': {}},
        ],
    },
]
