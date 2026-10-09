# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_terrain — the assistant half of Site ▸ Terrain / Contours / Cut and fill.

Three icons of `arch_ext/site_terrain.js` are declared pressable (BUTTONS), and
each analysis has a server-side twin the model can READ, so the numbers it
quotes and the numbers on screen come out of ONE arithmetic: the v3 heightfield
reached through `arch_assistant.ground_height`, which dispatches to
`arch_assistant_ext/ground_v3.py`'s `h_ground` through the HEIGHTS seam (the
same functions `arch_ext/ground_v3.js` runs in the tab).

No new kinds: the ground and the ten sculpts belong to ground_v3. Standard
library only.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
    cell_of,  # noqa: F401
    ground_height,
)

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['st_terrain', 'st_contour', 'st_cutfill']

PROMPT = (
    'Site terrain icons: press_button("st_terrain") lays the one ground when the drawing has none and otherwise '
    'opens the Terrain sheet; press_button("st_terrain", {"kind": "sculpt_peak", "cell": "C4"}) places one sculpt '
    'straight away (any sculpt_* kind, any cell), and {"size": 300} sets the ground\'s extent when it is created. '
    'press_button("st_contour", {"interval": 2}) draws contour lines every 2 m over the ground and pressing it '
    'again with no arguments takes them off. press_button("st_cutfill", {"which": "all"}) reports the earthwork. '
    'The read-only twins give you the numbers without the tab: ensure_ground(size) makes sure a ground exists, '
    'contours(interval) lists the total length of contour line at each level, and '
    'cut_fill(which, level) gives cut, fill, net and truck loads per slab and in total — cut is ground ABOVE the '
    "slab's base, fill is ground below it, and the balance level is where the two are equal."
)

GROUND_DEF = {
    'w': 200,
    'd': 200,
    'res': 100,
    'seed': 1,
    'base': 0,
    'amp': 1.5,
    'snow_h': 60,
    'water_h': -0.15,
    'grass_max_slope': 32,
}
CUTFILL_CELL = 0.25  # metres — the sampling grid over a slab footprint
TRUCK_M3 = 8.0  # a tipper load
CONTOUR_GRID = 72  # cells a side for the coarse Python contour pass
MAX_LEVELS = 200

# marching squares: the 16 cases as pairs of cell edges
#   e0 = c00→c10 (south)  e1 = c10→c11 (east)  e2 = c11→c01 (north)  e3 = c01→c00 (west)
_MS = [
    [],
    [(3, 0)],
    [(0, 1)],
    [(3, 1)],
    [(1, 2)],
    [(3, 0), (1, 2)],
    [(0, 2)],
    [(3, 2)],
    [(2, 3)],
    [(2, 0)],
    [(0, 1), (2, 3)],
    [(2, 1)],
    [(1, 3)],
    [(1, 0)],
    [(0, 3)],
    [],
]


def _the_ground(d: Drawing):
    for o in d.objs:
        if o['kind'] == 'ground':
            return o
    return None


def _slabs(d: Drawing, which) -> list:
    """The slabs the report covers. 'selection' has no meaning server side — the
    model cannot click — so it falls back to whatever the tab last highlighted,
    then to every slab."""
    w = which if which is not None else 'all'
    if isinstance(w, list):
        return [o for o in d.select(w) if o['kind'] == 'slab']
    w = str(w or 'all').strip()
    if w == 'selection':
        sel = [o for o in d.objs if o['id'] in (getattr(d, 'selected', None) or [])]
        recs = [o for o in sel if o['kind'] == 'slab']
        if recs:
            return recs
        w = 'all'
    if w == 'all':
        return [o for o in d.objs if o['kind'] == 'slab' and not o.get('hidden')]
    return [o for o in d.select(w) if o['kind'] == 'slab']


def _footprint(o: dict):
    """(centre x, centre z, local width, local depth, yaw) of a record that has one."""
    p = o.get('p') or {}
    sc = _num(o.get('s'), 1.0) or 1.0
    if o['kind'] in ('wall', 'partition'):
        w, dd = _num(p.get('len'), 4.0), _num(p.get('t'), 0.24)
    elif o['kind'] in ('slab', 'footing', 'pad'):
        w, dd = _num(p.get('w'), 6.0), _num(p.get('d'), 4.0)
    else:
        return None
    return (_num(o.get('x'), 0.0), _num(o.get('z'), 0.0), abs(w) * sc, abs(dd) * sc, _num(o.get('ry'), 0.0))


def _volumes(d: Drawing, o: dict, base: float) -> dict:
    """Cut and fill between H(x, z) and `base` over the record's own footprint,
    on a CUTFILL_CELL grid — the same sum the tab makes on screen."""
    f = _footprint(o)
    if f is None:
        return {'cut': 0.0, 'fill': 0.0, 'net': 0.0, 'samples': 0}
    x, z, w, dd, ry = f
    nx = max(1, min(200, int(round(w / CUTFILL_CELL))))
    nz = max(1, min(200, int(round(dd / CUTFILL_CELL))))
    sx, sz = w / nx, dd / nz
    a = sx * sz
    c, s = math.cos(ry), math.sin(ry)
    cut = fill = 0.0
    for j in range(nz):
        lz = -dd / 2 + (j + 0.5) * sz
        for i in range(nx):
            lx = -w / 2 + (i + 0.5) * sx
            h = ground_height(d, x + lx * c + lz * s, z - lx * s + lz * c)
            dh = h - base
            if dh > 0:
                cut += dh * a
            else:
                fill += -dh * a
    return {'cut': cut, 'fill': fill, 'net': cut - fill, 'samples': nx * nz}


# ── tools ────────────────────────────────────────────────────────────────────
def t_ensure_ground(d: Drawing, a: dict, size: float = 200.0, name: str = ''):
    """Make sure the drawing has its one ground; report the one it already has."""
    g = _the_ground(d)
    if g is not None:
        p = g['p']
        return (
            f'the drawing already has its ground ({g["id"]}): '
            f'{_num(p.get("w"), 200):g} x {_num(p.get("d"), 200):g} m centred on '
            f'{cell_of(_num(g.get("x"), 0), _num(g.get("z"), 0)) or "the origin"}. '
            'Sculpt it with raise_ground / lower_ground / level_ground — a second ground is refused.'
        )
    sz = max(10.0, _num(size, 200.0))
    p = dict(GROUND_DEF)
    p['w'] = sz
    p['d'] = sz
    solids = [o for o in d.objs if o['kind'] != 'ground' and not str(o['kind']).startswith('sculpt_')]
    if solids:
        cx = sum(_num(o.get('x'), 0.0) for o in solids) / len(solids)
        cz = sum(_num(o.get('z'), 0.0) for o in solids) / len(solids)
    else:
        cx = cz = 0.0
    rec = d.new('ground', p, cx, cz, 0.0, mat='mat_grass', name=name or 'Ground')
    d.selected = [rec['id']]
    return (
        f'laid the ground {rec["id"]}: {sz:g} x {sz:g} m centred on '
        f'{cell_of(cx, cz) or "the origin"}. Every landform from here is a sculpt OF it.'
    )


def t_contours(d: Drawing, a: dict, interval: float = 1.0, which: str = 'all'):
    """Total length of contour line at each level, from the same heightfield."""
    g = _the_ground(d)
    if g is None:
        return 'refused: the drawing has no ground yet — call ensure_ground or make_ground first.'
    iv = _num(interval, 1.0)
    if not iv > 0:
        return 'refused: a contour interval must be greater than zero.'
    p = g['p']
    w = max(1.0, abs(_num(p.get('w'), 200.0)))
    dd = max(1.0, abs(_num(p.get('d'), 200.0)))
    ox, oz = _num(g.get('x'), 0.0), _num(g.get('z'), 0.0)
    ry = _num(g.get('ry'), 0.0)
    c, s = math.cos(ry), math.sin(ry)
    sc = _num(g.get('s'), 1.0) or 1.0
    n = CONTOUR_GRID
    xs: list[float] = []
    zs: list[float] = []
    hs: list[float] = []
    for j in range(n + 1):
        lz = -dd / 2 + j / n * dd
        for i in range(n + 1):
            lx = -w / 2 + i / n * w
            wx = ox + sc * (lx * c + lz * s)
            wz = oz + sc * (-lx * s + lz * c)
            xs.append(wx)
            zs.append(wz)
            hs.append(ground_height(d, wx, wz))
    lo, hi = min(hs), max(hs)
    if hi - lo < 1e-6:
        return f'the ground is level at {lo:.2f} m — no contour crosses it.'

    def _edge(e, x0, x1, z0, z1, h00, h10, h11, h01, lv):
        def t(p0, p1):
            dv = p1 - p0
            return 0.5 if abs(dv) < 1e-12 else (lv - p0) / dv

        if e == 0:
            u = t(h00, h10)
            return (x0 + (x1 - x0) * u, z0)
        if e == 1:
            u = t(h10, h11)
            return (x1, z0 + (z1 - z0) * u)
        if e == 2:
            u = t(h11, h01)
            return (x1 + (x0 - x1) * u, z1)
        u = t(h01, h00)
        return (x0, z1 + (z0 - z1) * u)

    k0, k1 = math.ceil(lo / iv), math.floor(hi / iv)
    if k1 - k0 + 1 > MAX_LEVELS:
        k1 = k0 + MAX_LEVELS - 1
    lines: list[str] = []
    total = 0.0
    for k in range(int(k0), int(k1) + 1):
        lv = k * iv
        length = 0.0
        for j in range(n):
            for i in range(n):
                ia = j * (n + 1) + i
                ib, ic, ie = ia + 1, ia + n + 1, ia + n + 2
                h00, h10, h01, h11 = hs[ia], hs[ib], hs[ic], hs[ie]
                ci = (1 if h00 > lv else 0) | (2 if h10 > lv else 0) | (4 if h11 > lv else 0) | (8 if h01 > lv else 0)
                for e0, e1 in _MS[ci]:
                    pa = _edge(e0, xs[ia], xs[ib], zs[ia], zs[ic], h00, h10, h11, h01, lv)
                    pb = _edge(e1, xs[ia], xs[ib], zs[ia], zs[ic], h00, h10, h11, h01, lv)
                    length += math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        if length <= 0:
            continue
        total += length
        lines.append(f'{lv:g} m{" (major)" if k % 5 == 0 else ""}: {length:.1f} m')
    if not lines:
        return f'no contour crosses this ground at {iv:g} m (it runs {lo:.2f} to {hi:.2f} m).'
    head = (
        f'contours at {iv:g} m over {w:g} x {dd:g} m, ground {lo:.2f} to {hi:.2f} m, '
        f'{len(lines)} level{"" if len(lines) == 1 else "s"}, {total:.0f} m of line in all:'
    )
    return head + ' ' + '; '.join(lines[:60]) + ('; …' if len(lines) > 60 else '')


def t_cut_fill(d: Drawing, a: dict, which: str = 'all', level=None):
    """Cut and fill volumes between the ground and each slab's base."""
    g = _the_ground(d)
    if g is None:
        return 'refused: the drawing has no ground yet — call ensure_ground or make_ground first.'
    recs = _slabs(d, which)
    if not recs:
        return 'refused: there is no slab to measure — draw one first.'
    parts: list[str] = []
    tc = tf = 0.0
    for o in recs:
        base = _num(o.get('y'), 0.0) if level is None else _num(level, _num(o.get('y'), 0.0))
        v = _volumes(d, o, base)
        tc += v['cut']
        tf += v['fill']
        parts.append(
            f'{o["name"]} ({o["id"]}) base {base:.2f} m: cut {v["cut"]:.1f}, '
            f'fill {v["fill"]:.1f}, net {v["net"]:.1f} m3'
        )
    trucks = math.ceil(max(tc, tf) / TRUCK_M3)
    return (
        f'cut and fill over {len(recs)} slab{"" if len(recs) == 1 else "s"} — '
        f'total cut {tc:.1f} m3, total fill {tf:.1f} m3, net {tc - tf:.1f} m3, '
        f'{trucks} truck load{"" if trucks == 1 else "s"} at {TRUCK_M3:g} m3. ' + '; '.join(parts)
    )


TOOLS = [
    (
        {
            'name': 'ensure_ground',
            'description': (
                'Make sure the drawing has its one v3 ground, and say what it is. Safe to call twice: '
                'a second ground is never made. Call it before any terrain question.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'size': {'type': 'number', 'description': 'the square extent in metres (default 200)'},
                    'name': {'type': 'string'},
                },
            },
        },
        t_ensure_ground,
    ),
    (
        {
            'name': 'contours',
            'description': (
                'Contour lines of the ground: the total length of line at every level, at `interval` '
                'metres. Read-only — it draws nothing. Every fifth level is marked (major).'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'interval': {'type': 'number', 'description': 'metres between levels (default 1)'},
                    'which': {'type': 'string', 'description': 'ignored — there is one ground'},
                },
            },
        },
        t_contours,
    ),
    (
        {
            'name': 'cut_fill',
            'description': (
                "Earthwork between the ground and each slab's base: cut (ground above the base), fill "
                '(ground below it), net, and truck loads at 8 m3. Read-only.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {
                        'type': 'string',
                        'description': "'all' (default), 'new', 'selection', a group name or a kind",
                    },
                    'level': {'type': 'number', 'description': "a proposed level to test instead of each slab's own y"},
                },
            },
        },
        t_cut_fill,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a ground down and a hill on C4',
        'calls': [
            {'tool': 'ensure_ground', 'args': {'size': 200}},
            {'tool': 'press_button', 'args': {'id': 'st_terrain', 'args': {'kind': 'sculpt_peak', 'cell': 'C4'}}},
        ],
    },
    {
        'ask': 'show me contours every two metres',
        'calls': [
            {'tool': 'contours', 'args': {'interval': 2}},
            {'tool': 'press_button', 'args': {'id': 'st_contour', 'args': {'interval': 2}}},
        ],
    },
    {
        'ask': 'how much earth do we move for that slab',
        'calls': [
            {'tool': 'cut_fill', 'args': {'which': 'all'}},
            {'tool': 'press_button', 'args': {'id': 'st_cutfill', 'args': {'which': 'all'}}},
        ],
    },
]
