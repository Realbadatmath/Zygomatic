# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""analyse_geometry — the assistant's half of Analyse ▸ Clash, Headroom,
Guarding and Stair rule (icons a_clash, a_headroom, a_guard, a_stair).

FOUR CHECKS, ONE ARITHMETIC. Every function below is a transliteration of the
matching one in arch_ext/analyse_geometry.js — same constants, same rectangle
model, same separating-axis test, same excuses — so the model reading a table
here and the person reading the sheet in the tab are quoting the SAME numbers.
tests_arch_ext/test_analyse_geometry.py runs both on one fixture and fails if
the issue counts ever drift apart.

Everything is computed from the RECORDS' PARAMETERS, never from geometry. A
record's plan shape is the rectangle its size parameters imply (the same one
arch_assistant._p_footprint builds), rotated by ry; its vertical extent is
o['y'] .. o['y'] + h, because every kind builds upward from its own y — a
slab's base is y and its top y + t, a beam's underside is y, a flight climbs
steps * rise.

Nothing here writes: these four tools only read the drawing, so an answer is
never an edit and there is nothing to undo.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, _label, _num, is_opening

KINDS: dict = {}
OPENINGS: list = []
BUTTONS = ['a_clash', 'a_headroom', 'a_guard', 'a_stair']

PROMPT = (
    'Analyse (these four only read — they never change the drawing, and each has a dock icon of the same name): '
    'clash_check(which) reports every pair of solids that occupy the same space, with the shared volume — corner '
    'joints between walls, openings in their host wall and things bearing on a slab are excused. '
    'headroom_check(min) is the clear height under every slab, flat roof and beam and over every stair tread, '
    'against 2.3 m (the Dutch new-build value; 2.0 m is the absolute Bouwbesluit floor). '
    'guarding_check(min_h, max_gap) finds every deck edge with more than a metre of drop that has no wall, railing, '
    'balustrade or parapet along it, and any railing whose members are further apart than the 100 mm sphere rule. '
    'stair_check() reports every flight against Blondel (2 x rise + run between 0.60 and 0.65 m), rise <= 0.185 m, '
    'run >= 0.22 m, width >= 0.80 m, and whether it actually lands on the next storey. '
    'press_button("a_clash" / "a_headroom" / "a_guard" / "a_stair") shows the same findings to the person as a sheet '
    'with a select button per finding.'
)

# ── the constants every rule is measured against (identical to the JS C) ─────
CLASH_EPS = 0.02  # a pair must interpenetrate by more than 2 cm on all three axes
SLAB_BEAR = 0.05  # extra y a wall may share with the slab it stands on
CORNER_PAD = 0.05  # how close two wall ends must be to read as one corner joint
HEAD_MIN = 2.3  # Bouwbesluit new-build clear height (NL)
HEAD_ABS = 2.0  # the absolute floor
HEAD_BEARS = 0.05  # under this a "soffit" is a floor on its own storey plane
GUARD_H = 1.0
GUARD_GAP = 0.10  # the 100 mm sphere rule
GUARD_DROP = 1.0
EDGE_TOL = 0.15
EDGE_COVER = 0.80
GUARD_BAND = 0.35
GUARD_NOTCH = 0.40  # a stretch of edge shorter than this beside a guard is a notch, not an opening
BLONDEL_LO = 0.60
BLONDEL_HI = 0.65
RISE_MAX = 0.185
RUN_MIN = 0.22
WIDTH_MIN = 0.80
STOREY = 2.7
STOREY_TOL = 0.02
MAX_ISSUES = 300

SLABISH = ('slab', 'slab_poly', 'roof_flat')
SOFFIT = ('slab', 'slab_poly', 'roof_flat', 'beam')
DECK = ('slab', 'slab_poly', 'roof_flat', 'balcony')
WALLS = ('wall', 'partition')
# closed boxes of walls: the record is a ring in plan, so it guards on all four faces
GUARD_BOXES = ('elevator_shaft', 'stair_core', 'service_core', 'lift_core', 'shaft')
NON_SOLID = (
    'opening',
    'annotation',
    'dimension',
    'guide_line',
    'guide_circle',
    'plane',
    'disc',
    'ground',
    'water',
    'person',
)
SIDES = ('north', 'east', 'south', 'west')


# ── what a record occupies, from its parameters alone ───────────────────────
def _stair_dims(p, run_d=0.28, rise_d=0.175, w_d=1.0):
    n = max(1, int(round(_num(p.get('steps'), 16))))
    return [n * _num(p.get('run'), run_d), _num(p.get('w'), w_d), n * _num(p.get('rise'), rise_d)]


DIMS = {
    'wall': lambda p: [_num(p.get('len'), 4), _num(p.get('t'), 0.24), _num(p.get('h'), 2.7)],
    'partition': lambda p: [_num(p.get('len'), 4), _num(p.get('t'), 0.10), _num(p.get('h'), 2.7)],
    'slab': lambda p: [_num(p.get('w'), 6), _num(p.get('d'), 4), _num(p.get('t'), 0.22)],
    'roof_flat': lambda p: [_num(p.get('w'), 8), _num(p.get('d'), 6), _num(p.get('t'), 0.3)],
    'beam': lambda p: [_num(p.get('len'), 5), _num(p.get('w'), 0.2), _num(p.get('h'), 0.4)],
    'column_rect': lambda p: [_num(p.get('w'), 0.3), _num(p.get('d'), 0.3), _num(p.get('h'), 3)],
    'column_round': lambda p: [2 * _num(p.get('r'), 0.18), 2 * _num(p.get('r'), 0.18), _num(p.get('h'), 3)],
    'footing': lambda p: [_num(p.get('w'), 1), _num(p.get('d'), 1), _num(p.get('t'), 0.35)],
    'railing': lambda p: [_num(p.get('len'), 3), _num(p.get('t'), 0.04), _num(p.get('h'), 1.0)],
    'ladder': lambda p: [_num(p.get('w'), 0.5), _num(p.get('t'), 0.04), _num(p.get('h'), 3)],
    'ramp': lambda p: [_num(p.get('len'), 6), _num(p.get('w'), 1.5), _num(p.get('rise'), 0.5) + _num(p.get('t'), 0.15)],
    'box': lambda p: [_num(p.get('w'), 1), _num(p.get('d'), 1), _num(p.get('h'), 1)],
    'balcony': lambda p: [
        _num(p.get('w'), 2.4),
        _num(p.get('d'), 1.2),
        _num(p.get('t'), 0.18) + _num(p.get('rail_h'), 1.0),
    ],
    'parapet_cap': lambda p: [_num(p.get('len'), 4), _num(p.get('w'), 0.36), _num(p.get('t'), 0.08)],
    'stair_straight': _stair_dims,
    'stair_u': lambda p: [
        (max(2, int(round(_num(p.get('steps'), 16)))) // 2) * _num(p.get('run'), 0.28) + _num(p.get('w'), 1.0),
        2 * _num(p.get('w'), 1.0) + _num(p.get('gap'), 0.2),
        max(2, int(round(_num(p.get('steps'), 16)))) * _num(p.get('rise'), 0.175),
    ],
    'stair_winder': lambda p: [
        max(3, int(round(_num(p.get('steps'), 16)))) * _num(p.get('run'), 0.28),
        max(_num(p.get('w'), 1.0), max(3, int(round(_num(p.get('steps'), 16)))) * _num(p.get('run'), 0.28) / 2),
        max(3, int(round(_num(p.get('steps'), 16)))) * _num(p.get('rise'), 0.175),
    ],
    'stair_landing': lambda p: [_num(p.get('w'), 1.2), _num(p.get('d'), 1.2), _num(p.get('t'), 0.2)],
    'fire_stair_exterior': lambda p: _stair_dims(p, 0.26, 0.19),
}


def dims(o: dict) -> tuple:
    """(w along local +X, d along local +Z, h upward from o['y'], cu, cv)."""
    p = o.get('p') or {}
    f = DIMS.get(o.get('kind'))
    if f:
        t = f(p)
        return abs(t[0]), abs(t[1]), abs(t[2]), 0.0, 0.0
    cu = cv = 0.0
    pts = p.get('pts')
    if isinstance(pts, list) and len(pts) >= 3:
        xs = [_num(q[0], 0.0) for q in pts]
        zs = [_num(q[1], 0.0) for q in pts]
        w, dd = max(xs) - min(xs), max(zs) - min(zs)
        cu, cv = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
    elif 'len' in p:
        w, dd = abs(_num(p['len'], 0.0)), abs(_num(p.get('w'), _num(p.get('t'), 0.2)))
    elif 'span' in p:
        w, dd = abs(_num(p['span'], 0.0)), abs(_num(p.get('w'), 0.2))
    elif 'w' in p and 'd' in p:
        w, dd = abs(_num(p['w'], 0.0)), abs(_num(p['d'], 0.0))
    elif 'rx' in p and 'rz' in p:
        w, dd = 2 * abs(_num(p['rx'], 0.0)), 2 * abs(_num(p['rz'], 0.0))
    elif 'r_out' in p:
        w = dd = 2 * abs(_num(p['r_out'], 0.0))
    elif 'r' in p:
        w = dd = 2 * abs(_num(p['r'], 0.0))
    elif 'w' in p:
        w = dd = abs(_num(p['w'], 0.0))
    else:
        w = dd = 0.0
    h = _num(p.get('h'), _num(p.get('t'), 0.0))
    if 'steps' in p and 'rise' in p:
        h = max(1, int(round(_num(p['steps'], 1)))) * _num(p['rise'], 0.175)
    return (w if w > 0 else 0.5), (dd if dd > 0 else 0.5), (abs(h) if h else 0.5), cu, cv


def rect_of(x, z, ry, cu, cv, w, d) -> list:
    """The four world corners of a local rectangle. THREE rotation.y = ry maps
    local +X to (cos ry, -sin ry) and local +Z to (sin ry, cos ry) on the plan."""
    c, s = math.cos(ry or 0.0), math.sin(ry or 0.0)
    hw, hd = w / 2.0, d / 2.0
    loc = ((cu - hw, cv - hd), (cu + hw, cv - hd), (cu + hw, cv + hd), (cu - hw, cv + hd))
    return [(x + u * c + v * s, z - u * s + v * c) for u, v in loc]


def corners(o: dict) -> list:
    w, d, _h, cu, cv = dims(o)
    return rect_of(o.get('x') or 0.0, o.get('z') or 0.0, o.get('ry') or 0.0, cu, cv, w, d)


def aabb(pts):
    xs = [q[0] for q in pts]
    zs = [q[1] for q in pts]
    return min(xs), min(zs), max(xs), max(zs)


def sat_depth(a: list, b: list) -> float:
    """The smallest penetration depth of two convex quads in metres, or -1 when
    an axis separates them. Exact for rectangles."""
    best = float('inf')
    for poly in (a, b):
        for i in range(4):
            ax = poly[(i + 1) % 4][0] - poly[i][0]
            az = poly[(i + 1) % 4][1] - poly[i][1]
            nx, nz = -az, ax
            L = math.hypot(nx, nz)
            if L < 1e-9:
                continue
            nx, nz = nx / L, nz / L
            pa = [q[0] * nx + q[1] * nz for q in a]
            pb = [q[0] * nx + q[1] * nz for q in b]
            ov = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if ov <= 0:
                return -1.0
            best = min(best, ov)
    return -1.0 if best == float('inf') else best


def overlaps(a, b) -> bool:
    return sat_depth(a, b) > 0


def clip_area(a: list, b: list) -> float:
    """Area of a ∩ b (Sutherland–Hodgman clip of a by b's four half-planes)."""

    def cut(p, q, e0, e1):
        r1, r2 = q[0] - p[0], q[1] - p[1]
        s1, s2 = e1[0] - e0[0], e1[1] - e0[1]
        den = r1 * s2 - r2 * s1
        if abs(den) < 1e-12:
            return p
        t = ((e0[0] - p[0]) * s2 - (e0[1] - p[1]) * s1) / den
        return (p[0] + r1 * t, p[1] + r2 * t)

    out = list(a)
    for i in range(4):
        if not out:
            break
        e0, e1 = b[i], b[(i + 1) % 4]
        ex, ez = e1[0] - e0[0], e1[1] - e0[1]
        inp = []
        for j, cur in enumerate(out):
            prv = out[j - 1]
            dc = ex * (cur[1] - e0[1]) - ez * (cur[0] - e0[0])
            dp = ex * (prv[1] - e0[1]) - ez * (prv[0] - e0[0])
            if dc >= 0:
                if dp < 0:
                    inp.append(cut(prv, cur, e0, e1))
                inp.append(cur)
            elif dp >= 0:
                inp.append(cut(prv, cur, e0, e1))
        out = inp
    if len(out) < 3:
        return 0.0
    s = 0.0
    for i, q in enumerate(out):
        n = out[(i + 1) % len(out)]
        s += q[0] * n[1] - n[0] * q[1]
    return abs(s) / 2.0


# ── which records are solids the rules care about ───────────────────────────
def is_void(kind: str) -> bool:
    k = str(kind or '')
    if k in NON_SOLID:
        return True
    if k.startswith('sculpt_') or k.startswith('zone') or k.startswith('guide'):
        return True
    return is_opening(k)


def solids(d: Drawing) -> list:
    return [o for o in d.objs if not o.get('hidden') and not is_void(o.get('kind'))]


def is_wall(kind: str) -> bool:
    return kind in WALLS


def _lb(o) -> str:
    k = str(o.get('kind') or '')
    return _label(k) + ' ' + k


def is_stair(o: dict) -> bool:
    p = o.get('p') or {}
    if 'rise' not in p or 'run' not in p or 'steps' not in p:
        return False
    return 'stair' in _lb(o).lower()


def is_guard_box(o: dict) -> bool:
    """A record that is a closed ring of walls in plan — a lift shaft, a stair
    core. Its FOUR faces guard, not one line along its length."""
    k = str(o.get('kind') or '')
    if k not in GUARD_BOXES:
        return False
    p = o.get('p') or {}
    return 'w' in p and 'd' in p


def is_guard_kind(o: dict) -> bool:
    k = str(o.get('kind') or '')
    if is_wall(k) or k == 'balcony' or is_guard_box(o):
        return True
    lb = _lb(o).lower()
    return 'rail' in lb or 'balustrade' in lb or 'parapet' in lb


def guard_segments(g: dict) -> list:
    """The lines a guard offers, as (p0, p1, thickness across the line).

    A wall, railing or parapet is ONE segment along its length — the way this
    check has always read it. A shaft or core box is a closed ring, so it
    offers its four faces: the east face of a lift shaft guards the deck edge
    beside it exactly as a wall would, and that is what closes the edge of the
    slab void it stands in."""
    gw, gd, _gh, cu, cv = dims(g)
    x, z, ry = (g.get('x') or 0.0), (g.get('z') or 0.0), (g.get('ry') or 0.0)
    c, s = math.cos(ry), math.sin(ry)

    def world(u, v):
        return (x + u * c + v * s, z - u * s + v * c)

    if not is_guard_box(g):
        half = gw / 2.0
        return [((x - half * c, z + half * s), (x + half * c, z - half * s), gd)]
    t = abs(_num((g.get('p') or {}).get('t'), 0.0)) or min(gw, gd) / 8.0
    t = min(t, min(gw, gd) / 3.0)
    hw, hd = gw / 2.0, gd / 2.0
    return [
        (world(cu - hw, cv - hd), world(cu + hw, cv - hd), t),  # local north face
        (world(cu - hw, cv + hd), world(cu + hw, cv + hd), t),  # local south face
        (world(cu - hw, cv - hd), world(cu - hw, cv + hd), t),  # local west face
        (world(cu + hw, cv - hd), world(cu + hw, cv + hd), t),
    ]  # local east face


def name_of(o: dict) -> str:
    return _label(str(o.get('kind') or '')) + ' ' + str(o.get('id'))


def deck_top(o: dict) -> float:
    p = o.get('p') or {}
    if o.get('kind') == 'balcony':
        return (o.get('y') or 0.0) + _num(p.get('t'), 0.18)
    return (o.get('y') or 0.0) + dims(o)[2]


# ── 1. clash ────────────────────────────────────────────────────────────────
def wall_ends(o: dict) -> list:
    w = dims(o)[0]
    c, s = math.cos(o.get('ry') or 0.0), math.sin(o.get('ry') or 0.0)
    x, z, h = (o.get('x') or 0.0), (o.get('z') or 0.0), w / 2.0
    return [(x - h * c, z + h * s), (x + h * c, z - h * s)]


def excused(a: dict, b: dict, yov: float, depth: float) -> str:
    if is_wall(a.get('kind')) and is_wall(b.get('kind')):
        ea, eb = wall_ends(a), wall_ends(b)
        ta, tb = dims(a)[1], dims(b)[1]
        near = 0.5 * (ta + tb) + CORNER_PAD
        for pa in ea:
            for pb in eb:
                if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= near and depth <= max(ta, tb) + 1e-9:
                    return 'corner joint'
    if (a.get('kind') in SLABISH) != (b.get('kind') in SLABISH):
        s = a if a.get('kind') in SLABISH else b
        if yov <= dims(s)[2] + SLAB_BEAR + 1e-9:
            return 'bears on the slab'
    return ''


def run_clash(d: Drawing, which='all') -> dict:
    """Every pair of visible solids whose volumes interpenetrate by more than
    CLASH_EPS on all three axes. Sort-and-sweep on x, then SAT on the two plan
    rectangles plus the y interval."""
    recs = solids(d)
    if which not in ('all', '', None):
        keep = {o['id'] for o in d.select(which)}
        recs = [o for o in recs if o['id'] in keep]
    items = []
    for o in recs:
        c = corners(o)
        x0, z0, x1, z1 = aabb(c)
        h = dims(o)[2]
        items.append(
            {
                'o': o,
                'c': c,
                'x0': x0,
                'z0': z0,
                'x1': x1,
                'z1': z1,
                'y0': o.get('y') or 0.0,
                'y1': (o.get('y') or 0.0) + h,
            }
        )
    items.sort(key=lambda it: it['x0'])
    issues, tested, n_excused, act = [], 0, 0, []
    for a in items:
        act = [e for e in act if e['x1'] > a['x0'] + CLASH_EPS]
        for b in act:
            if min(a['z1'], b['z1']) - max(a['z0'], b['z0']) <= CLASH_EPS:
                continue
            yov = min(a['y1'], b['y1']) - max(a['y0'], b['y0'])
            if yov <= CLASH_EPS:
                continue
            tested += 1
            dep = sat_depth(a['c'], b['c'])
            if dep <= CLASH_EPS:
                continue
            if excused(a['o'], b['o'], yov, dep):
                n_excused += 1
                continue
            if len(issues) < MAX_ISSUES:
                vol = clip_area(a['c'], b['c']) * yov
                issues.append(
                    {
                        'ids': [a['o']['id'], b['o']['id']],
                        'severity': 'error',
                        'text': (
                            f'{name_of(a["o"])} <-> {name_of(b["o"])} — about {vol:.3f} m3 shared '
                            f'({dep:.2f} m into each other on the plan, {yov:.2f} m of common height)'
                        ),
                    }
                )
        act.append(a)
    rows = [
        ('solids tested', len(items)),
        ('pairs that share a bounding box', tested),
        ('pairs excused (corner joints, bearing on a slab)', n_excused),
        ('clashes', len(issues)),
        ('tolerance', f'{CLASH_EPS} m on every axis; openings and their host walls are never a clash'),
    ]
    return {'ok': not issues, 'issues': issues, 'rows': rows}


# ── 2. headroom ─────────────────────────────────────────────────────────────
def run_headroom(d: Drawing, min_h=HEAD_MIN) -> dict:
    """The clear height under every slab, flat roof and beam, and over every
    tread of every stair. A soffit's underside is o['y']; the floor below it is
    the highest slab TOP under it whose footprint it overlaps, else the storey
    plane floor(y / 2.7) * 2.7."""
    recs = solids(d)
    slabs = [o for o in recs if o.get('kind') in SLABISH]
    soffits = [o for o in recs if o.get('kind') in SOFFIT]
    issues, rows, worst = [], [], None

    def floor_under(under, rect, self_id):
        best = None
        for s in slabs:
            if s['id'] == self_id:
                continue
            top = (s.get('y') or 0.0) + dims(s)[2]
            if top > under + 1e-6:
                continue
            if not overlaps(rect, corners(s)):
                continue
            if best is None or top > best:
                best = top
        return math.floor(under / STOREY + 1e-6) * STOREY if best is None else best

    for o in soffits:
        under = o.get('y') or 0.0
        rect = corners(o)
        fl = floor_under(under, rect, o['id'])
        gap = under - fl
        if gap < HEAD_BEARS:  # it is a floor, not a ceiling
            continue
        if worst is None or gap < worst[0]:
            worst = (gap, o)
        if gap < min_h - 1e-9:
            issues.append(
                {
                    'ids': [o['id']],
                    'severity': 'error' if gap < HEAD_ABS else 'warn',
                    'text': (
                        f'{name_of(o)} — {gap:.2f} m clear under it (floor at {fl:.2f} m, '
                        f'soffit at {under:.2f} m); {min_h} m required'
                    ),
                }
            )

    stairs = [o for o in recs if is_stair(o)]
    for st in stairs:
        p = st.get('p') or {}
        n = max(1, int(round(_num(p.get('steps'), 16))))
        rise, run, wd = _num(p.get('rise'), 0.175), _num(p.get('run'), 0.28), _num(p.get('w'), 1.0)
        low, low_step = None, 0
        for k in range(n):
            tread_top = (st.get('y') or 0.0) + rise * (k + 1)
            tr = rect_of(
                st.get('x') or 0.0,
                st.get('z') or 0.0,
                st.get('ry') or 0.0,
                -(n * run) / 2 + run * k + run / 2,
                0.0,
                run,
                wd,
            )
            for s2 in soffits:
                if s2['id'] == st['id']:
                    continue
                sy = s2.get('y') or 0.0
                if sy < tread_top + 1e-6:
                    continue
                if not overlaps(tr, corners(s2)):
                    continue
                if low is None or sy - tread_top < low:
                    low, low_step = sy - tread_top, k + 1
        if low is None:
            rows.append((f'stair {st["id"]}', 'nothing built over the flight — no soffit to measure against'))
            continue
        rows.append((f'stair {st["id"]} (worst at tread {low_step})', f'{low:.2f} m'))
        if low < min_h - 1e-9:
            issues.append(
                {
                    'ids': [st['id']],
                    'severity': 'error' if low < HEAD_ABS else 'warn',
                    'text': f'{name_of(st)} — only {low:.2f} m over tread {low_step}; {min_h} m required',
                }
            )

    rows[0:0] = [
        ('minimum used', f'{min_h} m — the Dutch new-build value; {HEAD_ABS} m is the absolute Bouwbesluit floor'),
        ('soffits measured (slabs, flat roofs, beams)', len(soffits)),
        ('stairs measured', len(stairs)),
        ('lowest ceiling', f'{worst[0]:.2f} m under {name_of(worst[1])}' if worst else 'nothing spans a space yet'),
        ('too low', len(issues)),
    ]
    return {'ok': not issues, 'issues': issues, 'rows': rows}


# ── 3. guarding ─────────────────────────────────────────────────────────────
def coverage(p0, p1, guards, top, min_h) -> tuple:
    """(fraction of the edge p0..p1 a guard stands along, the guards' ids)."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 1e-6:
        return 1.0, []
    ux, uz = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    nx, nz = -uz, ux
    iv, ids = [], []
    for g in guards:
        gh = dims(g)[2]
        gy = g.get('y') or 0.0
        if gy > top + GUARD_BAND:  # it starts above the walking surface
            continue
        if gy + gh - top < min_h - 1e-9:  # it does not rise min_h over it
            continue
        hit = False
        for g0, g1, gd in guard_segments(g):
            tol = EDGE_TOL + gd / 2.0
            d0 = (g0[0] - p0[0]) * nx + (g0[1] - p0[1]) * nz
            d1 = (g1[0] - p0[0]) * nx + (g1[1] - p0[1]) * nz
            lo, hi = 0.0, 1.0
            if abs(d1 - d0) < 1e-9:
                if abs(d0) > tol:
                    continue
            else:
                sa, sb = (tol - d0) / (d1 - d0), (-tol - d0) / (d1 - d0)
                lo, hi = max(0.0, min(sa, sb)), min(1.0, max(sa, sb))
                if hi <= lo:
                    continue
            t0 = ((g0[0] - p0[0]) * ux + (g0[1] - p0[1]) * uz) / L
            t1 = ((g1[0] - p0[0]) * ux + (g1[1] - p0[1]) * uz) / L
            a, b = t0 + (t1 - t0) * lo, t0 + (t1 - t0) * hi
            lo2, hi2 = max(0.0, min(a, b)), min(1.0, max(a, b))
            if hi2 - lo2 > 1e-6:
                iv.append((lo2, hi2))
                hit = True
        if hit:
            ids.append(g['id'])
    iv.sort()
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if not merged:
        return 0.0, ids
    notch = GUARD_NOTCH / L  # a slot too narrow to fall through
    if merged[0][0] <= notch:
        merged[0][0] = 0.0
    if 1.0 - merged[-1][1] <= notch:
        merged[-1][1] = 1.0
    cov, cur = 0.0, None
    for a, b in merged:
        if cur is None:
            cur = [a, b]
        elif a - cur[1] <= notch:  # a gap between two guards, same rule
            cur[1] = max(cur[1], b)
        else:
            cov += cur[1] - cur[0]
            cur = [a, b]
    if cur:
        cov += cur[1] - cur[0]
    return min(1.0, cov), ids


def run_guard(d: Drawing, min_h=GUARD_H, max_gap=GUARD_GAP) -> dict:
    """Every deck edge with more than a metre of drop must have a wall, railing,
    balustrade or parapet within EDGE_TOL of it, covering EDGE_COVER of its
    length and rising min_h above the walking surface; and no railing may have
    a gap a max_gap sphere passes through."""
    recs = solids(d)
    decks = [o for o in recs if o.get('kind') in DECK]
    slabs = [o for o in recs if o.get('kind') in SLABISH]
    guards = [o for o in recs if is_guard_kind(o)]
    issues, rows, edges, drops = [], [], 0, 0

    for o in decks:
        top, rect = deck_top(o), corners(o)
        lower = 0.0  # the ground, unless a slab is nearer
        for s in slabs:
            if s['id'] == o['id']:
                continue
            st = (s.get('y') or 0.0) + dims(s)[2]
            if st > top - HEAD_BEARS or not overlaps(rect, corners(s)):
                continue
            lower = max(lower, st)
        drop = top - lower
        if drop <= GUARD_DROP:
            continue
        drops += 1
        if o.get('kind') == 'balcony':  # a balcony carries its own balustrade
            rh = _num((o.get('p') or {}).get('rail_h'), 1.0)
            rows.append((name_of(o), f'own balustrade {rh:.2f} m, {drop:.2f} m drop'))
            if rh < min_h - 1e-9:
                issues.append(
                    {
                        'ids': [o['id']],
                        'severity': 'error',
                        'text': (
                            f'{name_of(o)} — its balustrade is {rh:.2f} m over a {drop:.2f} m drop; {min_h} m required'
                        ),
                    }
                )
            continue
        for k in range(4):
            p0, p1 = rect[k], rect[(k + 1) % 4]
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < 0.2:
                continue
            mx, mz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            ex, ez = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            probe = [
                (mx + ez * 0.05 - ex * L * 0.45, mz - ex * 0.05 - ez * L * 0.45),
                (mx + ez * 0.05 + ex * L * 0.45, mz - ex * 0.05 + ez * L * 0.45),
                (mx + ez * 0.6 + ex * L * 0.45, mz - ex * 0.6 + ez * L * 0.45),
                (mx + ez * 0.6 - ex * L * 0.45, mz - ex * 0.6 - ez * L * 0.45),
            ]
            abuts = False
            for e in decks:
                if e['id'] == o['id'] or abs(deck_top(e) - top) > HEAD_BEARS:
                    continue
                if overlaps(probe, corners(e)):
                    abuts = True
                    break
            if abuts:
                continue
            edges += 1
            frac, ids = coverage(p0, p1, guards, top, min_h)
            if frac < EDGE_COVER - 1e-9:
                issues.append(
                    {
                        'ids': [o['id']] + ids,
                        'severity': 'error',
                        'text': (
                            f'{name_of(o)} {SIDES[k]} edge — {L:.2f} m long over a {drop:.2f} m drop, '
                            f'guarded over {round(frac * 100)}% of it ({min_h} m guard needed)'
                        ),
                    }
                )

    gaps = 0
    for g in guards:
        gp = g.get('p') or {}
        if 'gap' not in gp and 'spacing' not in gp:
            continue
        gv = _num(gp.get('gap'), _num(gp.get('spacing'), 0.0))
        if gv > max_gap + 1e-9:
            gaps += 1
            issues.append(
                {
                    'ids': [g['id']],
                    'severity': 'warn',
                    'text': (
                        f'{name_of(g)} — {round(gv * 1000)} mm between members; a '
                        f'{round(max_gap * 1000)} mm sphere must not pass through'
                    ),
                }
            )

    rows[0:0] = [
        ('guard height / gap used', f'{min_h} m, {round(max_gap * 1000)} mm'),
        (f'decks with more than {GUARD_DROP} m of drop', drops),
        ('open edges checked', edges),
        ('unguarded edges', len(issues) - gaps),
        ('gap rule failures', gaps),
    ]
    rows.append(
        (
            'guards found',
            f'{len(guards)} (walls, railings, balustrades, parapets, balconies, '
            f'and shaft / core boxes, which guard on all four faces)',
        )
    )
    rows.append(
        (
            'rule',
            f'a guard must stand within {EDGE_TOL} m of the edge and cover '
            f'{round(EDGE_COVER * 100)}% of it; a stretch shorter than {GUARD_NOTCH} m '
            f'beside a guard is a notch, not an opening',
        )
    )
    return {'ok': not issues, 'issues': issues, 'rows': rows}


# ── 4. stair rule ───────────────────────────────────────────────────────────
def run_stair(d: Drawing, storey_h=STOREY) -> dict:
    """Blondel, rise, run, width and whether the flight lands on the next
    storey. The parameters make every riser equal by construction."""
    recs = [o for o in solids(d) if is_stair(o)]
    issues, rows = [], []
    for o in recs:
        p = o.get('p') or {}
        n = max(1, int(round(_num(p.get('steps'), 16))))
        rise, run, wd = _num(p.get('rise'), 0.175), _num(p.get('run'), 0.28), _num(p.get('w'), 1.0)
        bl, climb = 2 * rise + run, n * rise
        over = climb - storey_h
        bad = []
        if bl < BLONDEL_LO - 1e-9 or bl > BLONDEL_HI + 1e-9:
            bad.append(f'2 x rise + run is {bl:.3f} m, outside {BLONDEL_LO}-{BLONDEL_HI} m')
        if rise > RISE_MAX + 1e-9:
            bad.append(f'rise {rise:.3f} m is over {RISE_MAX} m')
        if run < RUN_MIN - 1e-9:
            bad.append(f'run {run:.3f} m is under {RUN_MIN} m')
        if wd < WIDTH_MIN - 1e-9:
            bad.append(f'width {wd:.2f} m is under {WIDTH_MIN} m')
        if abs(over) <= STOREY_TOL:
            land = 'lands on the next storey'
        elif over > 0:
            land = f'does not reach: over by {over:.2f} m'
        else:
            land = f'does not reach: {-over:.2f} m short'
        if abs(over) > STOREY_TOL:
            bad.append(land)
        rows.append(
            (
                name_of(o),
                f'{n} x {rise:.3f} / {run:.3f} m, {wd:.2f} m wide — 2R+G {bl:.3f} m, '
                f'climbs {climb:.2f} m, {land}; every riser equal by construction',
            )
        )
        if bad:
            issues.append(
                {
                    'ids': [o['id']],
                    'severity': 'error' if len(bad) > 1 else 'warn',
                    'text': f'{name_of(o)} — ' + '; '.join(bad),
                }
            )
    rows[0:0] = [
        (
            'rule',
            f'Blondel {BLONDEL_LO}-{BLONDEL_HI} m, rise <= {RISE_MAX} m, run >= {RUN_MIN} m, '
            f'width >= {WIDTH_MIN} m, storey {storey_h} m +/- {STOREY_TOL} m',
        ),
        ('flights checked', len(recs)),
        ('flights flagged', len(issues)),
    ]
    if not recs:
        rows.append(('note', 'no stair in the drawing — draw one and press a_stair again'))
    return {'ok': not issues, 'issues': issues, 'rows': rows}


# ── the four tools: a text table of the same result ─────────────────────────
def _table(title: str, res: dict) -> str:
    out = [
        title
        + ': '
        + (
            'passed — nothing to report.'
            if res['ok']
            else f'{len(res["issues"])} finding{"" if len(res["issues"]) == 1 else "s"}.'
        )
    ]
    for k, v in res['rows']:
        out.append(f'  {k}: {v}')
    for it in res['issues']:
        out.append(f'  [{it["severity"]}] {it["text"]}  (ids: {", ".join(it["ids"])})')
    return '\n'.join(out)


def t_clash_check(d: Drawing, a, which='all'):
    return _table('Clash detection', run_clash(d, which))


def t_headroom_check(d: Drawing, a, min=None):  # noqa: A002 — the brief's argument name
    return _table('Headroom', run_headroom(d, _num(min, HEAD_MIN)))


def t_guarding_check(d: Drawing, a, min_h=None, max_gap=None):
    return _table('Guarding and handrails', run_guard(d, _num(min_h, GUARD_H), _num(max_gap, GUARD_GAP)))


def t_stair_check(d: Drawing, a, storey_h=None):
    return _table('Stair rule', run_stair(d, _num(storey_h, STOREY)))


TOOLS = [
    (
        {
            'name': 'clash_check',
            'description': (
                'Every pair of solids that occupy the same space, with the shared volume and how far they run '
                'into each other. Corner joints between walls, openings in their host wall and anything bearing '
                'on a slab are excused. Reads only — it never changes the drawing.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {
                        'type': 'string',
                        'description': '"all" (default), "new", a kind, a group name, or an object id',
                    }
                },
                'required': [],
            },
        },
        t_clash_check,
    ),
    (
        {
            'name': 'headroom_check',
            'description': (
                'The clear height under every slab, flat roof and beam and over every stair tread. Default '
                '2.3 m, the Dutch new-build value; 2.0 m is the absolute Bouwbesluit floor. Reads only.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'min': {'type': 'number', 'description': 'Minimum clear height in metres (default 2.3)'}
                },
                'required': [],
            },
        },
        t_headroom_check,
    ),
    (
        {
            'name': 'guarding_check',
            'description': (
                'Every slab, roof or balcony edge more than a metre above what is under it that has no wall, '
                'railing, balustrade or parapet along it, plus any railing whose members are further apart '
                'than the 100 mm sphere rule. Reads only.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'min_h': {
                        'type': 'number',
                        'description': 'Minimum guard height above the walking surface (default 1.0)',
                    },
                    'max_gap': {'type': 'number', 'description': 'Largest gap between members in metres (default 0.1)'},
                },
                'required': [],
            },
        },
        t_guarding_check,
    ),
    (
        {
            'name': 'stair_check',
            'description': (
                'Every flight against Blondel (2 x rise + run between 0.60 and 0.65 m), rise <= 0.185 m, '
                'run >= 0.22 m, width >= 0.80 m, and whether steps x rise actually lands on the next storey. '
                'Reads only.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'storey_h': {
                        'type': 'number',
                        'description': 'The storey height the flight must climb (default 2.7)',
                    }
                },
                'required': [],
            },
        },
        t_stair_check,
    ),
]

EXAMPLES = [
    {'ask': 'is anything clashing in this model?', 'calls': [{'tool': 'clash_check', 'args': {'which': 'all'}}]},
    {
        'ask': 'check the headroom and the stairs before I send this out',
        'calls': [{'tool': 'headroom_check', 'args': {'min': 2.3}}, {'tool': 'stair_check', 'args': {}}],
    },
    {
        'ask': 'does the roof terrace have a railing high enough?',
        'calls': [{'tool': 'guarding_check', 'args': {'min_h': 1.0, 'max_gap': 0.1}}],
    },
    {'ask': 'show me the clashes on screen', 'calls': [{'tool': 'press_button', 'args': {'id': 'a_clash'}}]},
]
