# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""modify_ops — the assistant's half of the Modify icons Offset, Fillet and
Follow me (arch_ext/modify_ops.js).

The three icons are POINTER MODES: they need a click on the canvas, which the
model cannot do, so BUTTONS is empty and every one of them gets a server-side
TWIN here that does the same arithmetic on ids instead of on picks:

    offset_wall(which, distance)                  <- the Offset mode
    fillet_walls(wall_a, wall_b, radius)          <- the Fillet mode
    sweep_profile(cells, width, height, closed)   <- the Follow me mode

One new kind, `sweep`: a profile w x h carried along p.pts ([x, z] metres
around the record's origin), one box per leg, butt-jointed. Its geometry lives
in arch_ext/modify_ops.js (tab) and arch_blender_ext/modify_ops.py (Blender).

THE FRAME (the same three lines the JS carries, verified against
arch_assistant._wall_world): a wall of rotation ry runs along
(cos ry, -sin ry) and its normal — the direction an offset moves it — is
(sin ry, cos ry).
"""

from __future__ import annotations

import copy
import math

from zyg_workflows.arch_assistant import (
    MAX_OBJECTS,
    Drawing,
    MATERIALS,
    _num,
    cell_centre,  # noqa: F401
    cell_of,
    parse_cell,
)

KINDS = {'sweep': {'pts': [[-3, -2], [3, -2], [3, 2]], 'w': 0.3, 'h': 0.3, 'closed': 0}}
OPENINGS: list = []
BUTTONS: list = []  # Offset/Fillet/Follow me are pointer modes: no press_button

PROMPT = (
    'Modify (offset / fillet / follow me), the twins of the three Modify icons: '
    'offset_wall(which, distance) drops ONE parallel copy of each wall, partition, guide line, guide circle or '
    'point-list record at that distance in metres (a negative distance offsets the other way; a circle grows or '
    'shrinks its radius, a polygon is inset or outset). '
    'fillet_walls(wall_a, wall_b, radius) trims or extends two walls until their centre lines meet — the far end '
    'of each stays put — and with radius > 0 pulls both back by the tangent length and adds one wall_arc of that '
    'radius, so the corner reads as a round. radius 0 is a sharp corner. '
    'sweep_profile(cells, width, height, closed) carries a width x height profile along the path through those '
    'cells and adds ONE `sweep` record — a cornice, a skirting, a kerb, a coping, a handrail.'
)

_WALLS = ('wall', 'partition')
_LINEAR = _WALLS + ('guide_line', 'beam')


# ── geometry, shared by the three tools ──────────────────────────────────────
def _dir(r):
    return math.cos(r['ry']), -math.sin(r['ry'])


def _nrm(r):
    return math.sin(r['ry']), math.cos(r['ry'])


def _ends(r):
    half = _num(r['p'].get('len'), 4) / 2.0
    dx, dz = _dir(r)
    return ((r['x'] - dx * half, r['z'] - dz * half), (r['x'] + dx * half, r['z'] + dz * half))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def _ry_of(a, b):
    return math.atan2(-(b[1] - a[1]), b[0] - a[0])


def _ring(v):
    out = []
    if isinstance(v, (list, tuple)):
        for a in v:
            if isinstance(a, (list, tuple)) and len(a) >= 2:
                x, z = _num(a[0], None), _num(a[1], None)
                if x is not None and z is not None:
                    out.append([x, z])
    return out if len(out) >= 2 else None


def _offset_pts(pts, d, closed):
    """Every edge moved d along its left normal; a vertex is where its two
    moved edges meet. The same arithmetic as offsetPts() in modify_ops.js."""
    n = len(pts)
    segs = []
    for i in range(n if closed else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        ex, ez = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(ex, ez)
        if ln < 1e-9:
            segs.append(None)
            continue
        ex, ez = ex / ln, ez / ln
        segs.append(((a[0] + ez * d, a[1] - ex * d), (ex, ez), ln))
    out = []
    for i in range(n):
        prev = segs[(i - 1) % len(segs)] if closed else (segs[i - 1] if i > 0 else None)
        nxt = segs[i % len(segs)] if closed else (segs[i] if i < len(segs) else None)
        if prev is None and nxt is not None:
            out.append([nxt[0][0], nxt[0][1]])
        elif prev is not None and nxt is None:
            out.append([prev[0][0] + prev[1][0] * prev[2], prev[0][1] + prev[1][1] * prev[2]])
        elif prev is None and nxt is None:
            out.append(list(pts[i]))
        else:
            den = _cross(prev[1], nxt[1])
            if abs(den) < 1e-7:
                out.append([nxt[0][0], nxt[0][1]])
            else:
                w = (nxt[0][0] - prev[0][0], nxt[0][1] - prev[0][1])
                t = _cross(w, nxt[1]) / den
                out.append([prev[0][0] + prev[1][0] * t, prev[0][1] + prev[1][1] * t])
    return [[round(p[0], 6), round(p[1], 6)] for p in out]


def _copy(d: Drawing, r, x, z):
    o = d.new(
        r['kind'],
        dict(r['p']),
        x,
        z,
        r['y'],
        r['ry'],
        r['mat'],
        name=(r['name'] or r['kind']) + ' offset',
        grp=r['grp'],
    )
    o['rx'], o['rz'], o['s'] = r['rx'], r['rz'], r['s']
    # rec.meta is the per-record user data (layer, tag, zone…): a parallel copy
    # that dropped it would silently fall off its layer. Same as clone() in the JS.
    o['meta'] = copy.deepcopy(r.get('meta') or {})
    return o


# ── offset ───────────────────────────────────────────────────────────────────
def t_offset_wall(d: Drawing, a: dict, which='new', distance=1.0):
    recs = d.select(which if which is not None else 'new')
    if not recs:
        return f'refused: nothing matches {which!r} — pass "new", "all", a kind, a group name or a list of ids'
    dd = _num(distance, 1.0)
    if abs(dd) < 1e-4:
        return 'refused: an offset of 0 m would land on top of the original'
    if len(d.objs) + len(recs) > MAX_OBJECTS:
        return f'refused: that would take the drawing past {MAX_OBJECTS} objects'
    made, skipped = [], 0
    for r in recs:
        pts = _ring(r['p'].get('pts'))
        if r['kind'] == 'guide_circle':
            o = _copy(d, r, r['x'], r['z'])
            o['p']['r'] = max(0.01, _num(r['p'].get('r'), 1) + dd)
        elif pts is not None:
            o = _copy(d, r, r['x'], r['z'])
            o['p']['pts'] = _offset_pts(pts, dd, bool(r['p'].get('closed')))
        elif r['kind'] in _LINEAR:
            nx, nz = _nrm(r)
            o = _copy(d, r, r['x'] + nx * dd, r['z'] + nz * dd)
        else:
            skipped += 1
            continue
        made.append(o['id'])
    if not made:
        return (
            'refused: nothing in that selection has an edge to offset — offset works on walls, partitions, '
            'guide lines, guide circles and point-list records'
        )
    d.selected = made
    tail = f' ({skipped} with no edge were skipped)' if skipped else ''
    return f'Offset {len(made)} object(s) by {dd:g} m: {", ".join(made)}{tail}.'


# ── fillet ───────────────────────────────────────────────────────────────────
def _one_wall(d: Drawing, which, label):
    recs = [r for r in d.select(which) if r['kind'] in _WALLS]
    if len(recs) != 1:
        return None, (f'refused: {label}={which!r} must name exactly ONE wall or partition (it matched {len(recs)})')
    return recs[0], ''


def _trim_plan(r, corner):
    """What trimming r onto `corner` would do — WITHOUT doing it. The far end
    stays put, so the plan is (far end, new length, unit far->corner). None when
    the corner sits on the far end and the wall would collapse.

    Planning both walls before either is touched is what keeps a refusal honest:
    computing and applying in one step moved wall A and only then discovered
    that wall B could not be trimmed. Same shape as trimPlan() in the JS."""
    e0, e1 = _ends(r)
    far = e1 if _dist(e0, corner) <= _dist(e1, corner) else e0
    ln = _dist(far, corner)
    if ln < 1e-4:
        return None
    return far, ln, ((corner[0] - far[0]) / ln, (corner[1] - far[1]) / ln)


def _apply_trim(r, far, end):
    """Put r between `far` and `end`."""
    ln = _dist(far, end)
    r['p']['len'] = round(ln, 6)
    r['x'], r['z'] = round((far[0] + end[0]) / 2, 6), round((far[1] + end[1]) / 2, 6)
    r['ry'] = round(_ry_of(far, end), 6)


def _pull_back(plan, t):
    """The point t back from the corner along the plan's own direction."""
    far, ln, u = plan
    nl = ln - t
    return (far[0] + u[0] * nl, far[1] + u[1] * nl)


def _plan_deg(c, p):
    return math.degrees(math.atan2(-(p[1] - c[1]), p[0] - c[0]))


def t_fillet_walls(d: Drawing, a: dict, wall_a, wall_b, radius=0.0):
    A, err = _one_wall(d, wall_a, 'wall_a')
    if err:
        return err
    B, err = _one_wall(d, wall_b, 'wall_b')
    if err:
        return err
    if A['id'] == B['id']:
        return 'refused: wall_a and wall_b are the same wall'
    da, db = _dir(A), _dir(B)
    den = _cross(da, db)
    if abs(den) < 1e-6:
        return 'refused: those two walls are parallel — there is no corner to fillet'
    ea0, _ = _ends(A)
    eb0, _ = _ends(B)
    t = _cross((eb0[0] - ea0[0], eb0[1] - ea0[1]), db) / den
    X = (ea0[0] + da[0] * t, ea0[1] + da[1] * t)
    # plan both trims first: a refusal below must leave the drawing untouched
    pl_a, pl_b = _trim_plan(A, X), _trim_plan(B, X)
    if pl_a is None or pl_b is None:
        return 'refused: one of the walls would collapse onto the corner'
    uA, uB = (-pl_a[2][0], -pl_a[2][1]), (-pl_b[2][0], -pl_b[2][1])
    theta = math.acos(max(-1.0, min(1.0, uA[0] * uB[0] + uA[1] * uB[1])))
    rad = max(0.0, _num(radius, 0.0))
    note = ''
    arc_id = ''
    _apply_trim(A, pl_a[0], X)
    _apply_trim(B, pl_b[0], X)
    if rad > 1e-4 and 1e-3 < theta < math.pi - 1e-3:
        # tangent length of a fillet of radius rad on an interior angle theta
        T = rad / math.tan(theta / 2)
        if pl_a[1] - T < 0.05 or pl_b[1] - T < 0.05:
            # neither wall was shortened: the sharp corner just applied stands
            note = f' Radius {rad:g} m is bigger than the walls, so the corner was left sharp.'
        else:
            pa, pb = _pull_back(pl_a, T), _pull_back(pl_b, T)
            _apply_trim(A, pl_a[0], pa)
            _apply_trim(B, pl_b[0], pb)
            bis = (uA[0] + uB[0], uA[1] + uB[1])
            bl = math.hypot(*bis)
            bis = (bis[0] / bl, bis[1] / bl)
            cd = rad / math.sin(theta / 2)
            C = (X[0] + bis[0] * cd, X[1] + bis[1] * cd)
            a0, a1 = _plan_deg(C, pa), _plan_deg(C, pb)
            span = ((a1 - a0) % 360 + 540) % 360 - 180  # the short way round
            arc = d.new(
                'wall_arc',
                {
                    'r': round(rad, 6),
                    'a0': round(a0, 4),
                    'a1': round(a0 + span, 4),
                    'h': (_num(A['p'].get('h'), 2.7) + _num(B['p'].get('h'), 2.7)) / 2,
                    't': (_num(A['p'].get('t'), 0.24) + _num(B['p'].get('t'), 0.24)) / 2,
                    'seg': 24,
                },
                round(C[0], 6),
                round(C[1], 6),
                A['y'],
                0.0,
                A['mat'],
                name='Fillet',
                grp=A['grp'],
            )
            arc_id = arc['id']
            note = f' Rounded with a {rad:g} m wall_arc ({arc_id}).'
    d.selected = [A['id'], B['id']] + ([arc_id] if arc_id else [])
    return (
        f'Joined {A["id"]} and {B["id"]} at {X[0]:.3f}, {X[1]:.3f} '
        f'(interior angle {math.degrees(theta):.1f} deg).{note}'
    )


# ── follow me ────────────────────────────────────────────────────────────────
def t_sweep_profile(d: Drawing, a: dict, cells, width=0.3, height=0.3, closed=False, storey=0, material='', name=''):
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: cells must be a list of 2 or more cell names in path order, e.g. ["C4","L4","L13"]'
    world = []
    for c in cells:
        try:
            col, row = parse_cell(c)
        except ValueError:
            return f'refused: {c!r} is not a cell name (like C4)'
        world.append(cell_centre(col, row))
    w, h = max(0.005, abs(_num(width, 0.3))), max(0.005, abs(_num(height, 0.3)))
    cl = 1 if closed else 0
    if len(world) > 2 and _dist(world[0], world[-1]) <= 0.01:
        world.pop()
        cl = 1
    if len(world) < 2:
        return 'refused: that path has no length to sweep along'
    cx = round(sum(p[0] for p in world) / len(world), 6)
    cz = round(sum(p[1] for p in world) / len(world), 6)
    pts = [[round(p[0] - cx, 6), round(p[1] - cz, 6)] for p in world]
    o = d.new(
        'sweep',
        {'pts': pts, 'w': round(w, 6), 'h': round(h, 6), 'closed': cl},
        cx,
        cz,
        _num(storey, 0) * d.storey_h,
        0.0,
        material or 'mat_timber',
        name=name or 'Sweep',
    )
    d.selected = [o['id']]
    legs = len(pts) - 1 + cl
    return (
        f'Swept a {w:g} x {h:g} m profile along {legs} leg(s) through {len(pts)} point(s) '
        f'as {o["id"]} at {cell_of(cx, cz)}.'
    )


TOOLS = [
    (
        {
            'name': 'offset_wall',
            'description': 'A parallel copy at a distance: one new record beside each wall, partition, guide line, guide '
            'circle or point-list record in the selection. A negative distance offsets the other way; a '
            'guide circle grows or shrinks its radius; a polygon is inset or outset.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {'type': 'string', 'description': '"new", "all", a kind, a group name or ids'},
                    'distance': {'type': 'number', 'description': 'metres; the sign picks the side'},
                },
                'required': ['distance'],
            },
        },
        t_offset_wall,
    ),
    (
        {
            'name': 'fillet_walls',
            'description': 'Join two walls at a corner: each is trimmed or extended until their centre lines meet (the far '
            'end of each stays put). With radius > 0 both are pulled back by the tangent length and one '
            'wall_arc of that radius is added, so the corner reads as a round. radius 0 leaves it sharp.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'wall_a': {'type': 'string', 'description': 'the id of the first wall'},
                    'wall_b': {'type': 'string', 'description': 'the id of the second wall'},
                    'radius': {'type': 'number', 'description': 'fillet radius in metres; 0 = a sharp corner'},
                },
                'required': ['wall_a', 'wall_b'],
            },
        },
        t_fillet_walls,
    ),
    (
        {
            'name': 'sweep_profile',
            'description': 'Follow me: carry a width x height profile along the path through those cells and add ONE swept '
            'record — a cornice, a skirting, a kerb, a coping, a handrail, a plinth.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'cell names in path order, e.g. ["C4","L4","L13"]',
                    },
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'closed': {'type': 'boolean', 'description': 'join the last point back to the first'},
                    'storey': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_sweep_profile,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a second wall one and a half metres inside that one',
        'calls': [{'tool': 'offset_wall', 'args': {'which': 'new', 'distance': -1.5}}],
    },
    {
        'ask': 'round the corner where those two walls meet, radius 1 m',
        'calls': [{'tool': 'fillet_walls', 'args': {'wall_a': 'o1', 'wall_b': 'o2', 'radius': 1}}],
    },
    {
        'ask': 'run a 300 mm kerb along C4 to L4 to L13',
        'calls': [{'tool': 'sweep_profile', 'args': {'cells': ['C4', 'L4', 'L13'], 'width': 0.3, 'height': 0.15}}],
    },
]
