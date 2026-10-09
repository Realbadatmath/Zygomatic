# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""analyse_planning — the assistant's half of Analyse ▸ Escape route,
Accessibility, Occupancy and Compartments (icons a_egress, a_access,
a_occupancy, a_fire).

BUTTONS lets the model press the four icons in the tab; TOOLS are the
server-side twins of exactly the same four analyses, so the model can READ the
numbers without a browser. Both halves are ONE rule book: arch_ext/analyse_planning.js
does the same arithmetic with the same 5 cm snap tolerance, the same
m²-per-person table, the same 0.05 m door frame and the same honest
approximations. Change one and you have two rule books.

THE ROOM FINDER (written once here, reused by all four tools):
  · zone records first — kind 'zone', p.pts a LOCAL polygon [[x, z], ...] around
    the record's x/z, with p.name / p.use;
  · otherwise closed loops of 'wall' and 'partition' CENTRE-LINES per storey,
    snapped to 5 cm and noded with shapely (shapely.ops.unary_union then
    polygonize). Areas are therefore to wall centre-lines, not to the clear
    internal face — every answer says so.
A room's name, use and compartment come from the zone record, or from any
record standing inside the loop that carries meta.room / meta.use /
meta.compartment (an annotation pin is the natural one), or from
doc.ext.analyse_planning.

Licences: shapely 2.x (BSD-3-Clause) — already in the GUI venv. Nothing else is
imported beyond the standard library and arch_assistant itself.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, storey_of, _num

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['a_egress', 'a_access', 'a_occupancy', 'a_fire']

PROMPT = (
    'Planning analyses — they READ the drawing; rooms come from zone records, else from closed loops of wall and '
    'partition centre-lines. egress_check(max=30) is the travel distance to the nearest exit door; '
    'accessibility_check(turn=1.5, door_w=0.85) the turning circle and clear door widths; occupancy(rates=None) '
    'persons per room and the exit width they need; fire_compartments(max_area=1000, max_len=60) area, longest '
    'travel and weak compartment walls. Icons a_egress, a_access, a_occupancy, a_fire. explain("planning") has '
    'the detail.'
)

# ── constants shared with arch_ext/analyse_planning.js ────────────────────────
SNAP = 0.05  # wall endpoint / crossing snap, metres
MIN_AREA = 0.5  # a face under this is a noding sliver, not a room
GRID = 0.1  # inscribed-circle sample grid, metres
SIDE = 0.15  # how far past a wall face a side sample sits
FRAME = 0.05  # a door leaf loses this much to its frame
MAX_WALLS = 600

WALL_KINDS = ('wall', 'partition')
DOOR_KINDS = ('door', 'double_door')

RATES = {
    'office': 10.0,
    'meeting': 2.0,
    'retail': 3.0,
    'residential': 20.0,
    'bedroom': 12.0,
    'bedrooms': 12.0,
    'classroom': 2.0,
    'corridor': 0.0,
    'circulation': 0.0,
    'assembly': 1.0,
    'storage': 30.0,
}
RATE_DEFAULT = 10.0

_bmax, _bmin = max, min  # the tool signatures shadow the builtins


# ── small maths (the JS twin's arithmetic, line for line) ────────────────────
def _snap(v: float) -> float:
    return round(round(v / SNAP) * SNAP, 6)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _shoelace(poly) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        s += ax * bz - bx * az
    return s / 2.0


def _in_poly(x, z, poly) -> bool:
    hit = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[j]
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            hit = not hit
        j = i
    return hit


def _dist_seg(x, z, a, b) -> float:
    dx, dz = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dz * dz
    t = 0.0 if l2 <= 1e-12 else ((x - a[0]) * dx + (z - a[1]) * dz) / l2
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return math.hypot(x - (a[0] + t * dx), z - (a[1] + t * dz))


def _dist_edges(x, z, poly) -> float:
    n = len(poly)
    return _bmin(_dist_seg(x, z, poly[i], poly[(i + 1) % n]) for i in range(n))


def in_circle(poly):
    """Largest circle inside the polygon clear of every edge: a 0.1 m grid of the
    interior, then four halving hill-climb rounds. Returns (x, z, radius)."""
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    x0, x1, z0, z1 = _bmin(xs), _bmax(xs), _bmin(zs), _bmax(zs)
    step = GRID
    nx, nz = _bmax(1, int((x1 - x0) / step)), _bmax(1, int((z1 - z0) / step))
    if nx * nz > 400000:
        step = math.sqrt((x1 - x0) * (z1 - z0) / 400000.0)
        nx, nz = _bmax(1, int((x1 - x0) / step)), _bmax(1, int((z1 - z0) / step))
    best = ((x0 + x1) / 2.0, (z0 + z1) / 2.0, 0.0)
    for i in range(nx):
        px = x0 + (i + 0.5) * step
        for j in range(nz):
            pz = z0 + (j + 0.5) * step
            if not _in_poly(px, pz, poly):
                continue
            dd = _dist_edges(px, pz, poly)
            if dd > best[2]:
                best = (px, pz, dd)
    s = step
    for _ in range(4):
        s /= 2.0
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                if not a and not b:
                    continue
                qx, qz = best[0] + a * s, best[1] + b * s
                if not _in_poly(qx, qz, poly):
                    continue
                dd = _dist_edges(qx, qz, poly)
                if dd > best[2]:
                    best = (qx, qz, dd)
    return best


# ── records ──────────────────────────────────────────────────────────────────
def _p(o, key, default=0.0):
    return _num((o.get('p') or {}).get(key), default)


def _storey(o, d: Drawing) -> int:
    return storey_of(o.get('y') or 0.0, d.storey_h)


def _is_door(o) -> bool:
    return o['kind'] in DOOR_KINDS or 'door' in o['kind']


def wall_seg(w):
    """The wall's centre-line. Local +X maps to world (cos ry, -sin ry): the
    studio builds a wall from two clicks with ry = atan2(-(bz - az), bx - ax)."""
    length = _p(w, 'len', 4.0)
    ry = _num(w.get('ry'), 0.0)
    c, s = math.cos(ry), math.sin(ry)
    return {
        'rec': w,
        'id': w['id'],
        't': _p(w, 't', 0.24),
        'h': _p(w, 'h', 2.7),
        'a': (w['x'] - length / 2 * c, w['z'] + length / 2 * s),
        'b': (w['x'] + length / 2 * c, w['z'] - length / 2 * s),
        'dir': (c, -s),
        'nrm': (s, c),
        'len': length,
    }


def walls_on(d: Drawing, storey=None):
    out = []
    for o in d.objs:
        if o['kind'] not in WALL_KINDS or o.get('hidden'):
            continue
        if storey is not None and _storey(o, d) != storey:
            continue
        if _p(o, 'len', 0.0) <= 0:
            continue
        out.append(wall_seg(o))
    return out


# ── the room finder ──────────────────────────────────────────────────────────
def _loop_rooms(d: Drawing, storey):
    """Closed faces of the wall centre-line graph, noded with shapely."""
    segs = walls_on(d, storey)
    if not segs or len(segs) > MAX_WALLS:
        return []
    try:
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union
    except ImportError as _exc:  # pragma: no cover
        raise RuntimeError('the wall-loop room finder needs shapely (BSD-3-Clause) in the GUI venv') from _exc
    lines = []
    for s in segs:
        a = (_snap(s['a'][0]), _snap(s['a'][1]))
        b = (_snap(s['b'][0]), _snap(s['b'][1]))
        if _dist(a, b) >= SNAP:
            lines.append(LineString([a, b]))
    if not lines:
        return []
    out = []
    for poly in polygonize(unary_union(lines)):
        if poly.area <= MIN_AREA:
            continue
        ring = list(poly.exterior.coords)[:-1]
        out.append({'poly': [(round(x, 6), round(z, 6)) for x, z in ring], 'area': poly.area, 'rec': None})
    out.sort(key=lambda r: (round(_bmin(p[0] for p in r['poly']), 3), round(_bmin(p[1] for p in r['poly']), 3)))
    return out


def _zone_rooms(d: Drawing, storey):
    out = []
    for o in d.objs:
        if o['kind'] != 'zone' or o.get('hidden'):
            continue
        if storey is not None and _storey(o, d) != storey:
            continue
        pts = (o.get('p') or {}).get('pts')
        if not isinstance(pts, list) or len(pts) < 3:
            continue
        ry = _num(o.get('ry'), 0.0)
        c, s = math.cos(ry), math.sin(ry)
        poly = [
            (o['x'] + _num(q[0], 0.0) * c + _num(q[1], 0.0) * s, o['z'] - _num(q[0], 0.0) * s + _num(q[1], 0.0) * c)
            for q in pts
        ]
        out.append({'poly': poly, 'area': abs(_shoelace(poly)), 'rec': o})
    return out


def _tag_comp(meta):
    if not meta:
        return None
    if meta.get('compartment'):
        return str(meta['compartment'])
    tags = meta.get('tags')
    if isinstance(tags, str):
        tags = [t for t in tags.replace(',', ' ').split() if t]
    if isinstance(tags, list):
        for t in tags:
            if str(t).lower().startswith('comp:'):
                return str(t)[5:]
    return None


def _is_exit_tagged(o) -> bool:
    meta = o.get('meta') or {}
    tags = meta.get('tags')
    if isinstance(tags, str):
        tags = [t for t in tags.replace(',', ' ').split() if t]
    if isinstance(tags, list) and any(str(t).strip().lower() == 'exit' for t in tags):
        return True
    text = (str(o.get('name') or '') + ' ' + str(meta.get('role') or '')).lower()
    return 'exit' in text or 'uitgang' in text


def _marker_in(d: Drawing, room, storey):
    for o in d.objs:
        if o.get('hidden') or o['kind'] in WALL_KINDS or o['kind'] == 'zone' or _is_door(o):
            continue
        if storey is not None and _storey(o, d) != storey:
            continue
        meta = o.get('meta') or {}
        if not (meta.get('use') or meta.get('room') or meta.get('compartment') or meta.get('tags')):
            continue
        if _in_poly(o['x'], o['z'], room['poly']):
            return o
    return None


def rooms(d: Drawing, storey=None):
    """THE room finder. [{key, name, use, storey, y, poly, area, doors, compartment, rec, source}]"""
    ext = dict(d.ext.get('analyse_planning') or {}) if isinstance(d.ext, dict) else {}
    if storey is None:
        sts = sorted(
            {_storey(o, d) for o in d.objs if not o.get('hidden') and (o['kind'] in WALL_KINDS or o['kind'] == 'zone')}
        )
    else:
        sts = [int(storey)]
    out = []
    for st in sts:
        zs = _zone_rooms(d, st)
        found = zs if zs else _loop_rooms(d, st)
        for f in found:
            rec = f.get('rec') or _marker_in(d, f, st)
            meta = (rec.get('meta') or {}) if rec else {}
            pp = (f['rec'].get('p') or {}) if f.get('rec') else {}
            name = (
                pp.get('name')
                or meta.get('room')
                or (f['rec'].get('name') if f.get('rec') else (rec.get('name') if rec else ''))
                or f'Room {len(out) + 1}'
            )
            use = str(pp.get('use') or meta.get('use') or ext.get('default_use') or 'office').lower()
            out.append(
                {
                    'key': f'r{len(out)}',
                    'name': str(name),
                    'use': use,
                    'storey': st,
                    'y': st * d.storey_h,
                    'poly': f['poly'],
                    'area': abs(f['area']),
                    'doors': [],
                    'compartment': _tag_comp(meta),
                    'rec': rec,
                    'source': 'zone' if zs else 'wall loop',
                }
            )
    attach_doors(d, out)
    return out


# ── doors ────────────────────────────────────────────────────────────────────
def _host_wall(d: Drawing, door):
    best, best_d = None, 1e9
    for w in walls_on(d, _storey(door, d)):
        wy = w['rec'].get('y') or 0.0
        if door['y'] < wy - 0.05 or door['y'] > wy + w['h'] - 0.05:
            continue
        dx, dz = door['x'] - w['rec']['x'], door['z'] - w['rec']['z']
        ry = _num(w['rec'].get('ry'), 0.0)
        c, s = math.cos(ry), math.sin(ry)
        lx, lz = dx * c - dz * s, dx * s + dz * c
        if abs(lx) > w['len'] / 2 + 0.001:
            continue
        if abs(lz) > w['t'] / 2 + 0.45:
            continue
        if abs(lz) < best_d:
            best, best_d = w, abs(lz)
    return best


def _sides_of(pt, wall, room_list):
    off = wall['t'] / 2 + SIDE
    out = []
    for sgn in (1, -1):
        x = pt[0] + sgn * off * wall['nrm'][0]
        z = pt[1] + sgn * off * wall['nrm'][1]
        hit = None
        for r in room_list:
            if _in_poly(x, z, r['poly']):
                hit = r
                break
        out.append(hit)
    return out


def attach_doors(d: Drawing, room_list):
    out = []
    for o in d.objs:
        if not _is_door(o) or o.get('hidden'):
            continue
        w = _host_wall(d, o)
        if not w:
            continue
        st = _storey(o, d)
        mine = [r for r in room_list if r['storey'] == st]
        sides = _sides_of((o['x'], o['z']), w, mine)
        rs = []
        if sides[0] is not None:
            rs.append(sides[0])
        if sides[1] is not None and sides[1] is not sides[0]:
            rs.append(sides[1])
        leaf = _p(o, 'w', 0.9)
        door = {
            'id': o['id'],
            'rec': o,
            'mid': (o['x'], o['z']),
            'wall': w,
            'storey': st,
            'rooms': rs,
            'w': leaf,
            'clear': _bmax(0.0, leaf - FRAME),
            'exterior': len(rs) <= 1,
        }
        door['exit'] = door['exterior'] or _is_exit_tagged(o)
        for r in rs:
            r['doors'].append(door)
        out.append(door)
    return out


# ── the four analyses ────────────────────────────────────────────────────────
def _far_corner(room, pt):
    best, bd = room['poly'][0], -1.0
    for v in room['poly']:
        dd = _dist(v, pt)
        if dd > bd:
            best, bd = v, dd
    return best, bd


def _doors_of(room_list):
    """The doors of the rooms in hand, deduplicated by RECORD id.

    attach_doors appends one dict to both of a door's rooms, so identity
    deduplication happens to work today — but a caller that merges room lists
    from two rooms() passes would double-count. The record id is unique in a
    drawing, and the JS twin's doorsOf() dedupes on the same key.
    """
    seen, out = set(), []
    for r in room_list:
        for dd in r['doors']:
            if dd['id'] in seen:
                continue
            seen.add(dd['id'])
            out.append(dd)
    return out


def egress(d: Drawing, limit=30.0, storey=None, room_list=None):
    rl = room_list if room_list is not None else rooms(d, storey)
    dl = _doors_of(rl)
    # Dijkstra over the doors: a leg between two doors of one room is the
    # straight line between their midpoints; every exit door starts at 0.
    D = {dd['id']: (0.0 if dd['exit'] else math.inf) for dd in dl}
    todo = list(dl)
    while todo:
        todo.sort(key=lambda x: D[x['id']])
        cur = todo.pop(0)
        if not math.isfinite(D[cur['id']]):
            break
        for r in cur['rooms']:
            for o in r['doors']:
                if o['id'] == cur['id']:
                    continue
                nd = D[cur['id']] + _dist(cur['mid'], o['mid'])
                if nd < D[o['id']] - 1e-9:
                    D[o['id']] = nd
    issues, worst = [], None
    for r in rl:
        best = None
        for dd in r['doors']:
            if not math.isfinite(D[dd['id']]):
                continue
            _, first = _far_corner(r, dd['mid'])
            tot = first + D[dd['id']]
            if best is None or tot < best[1]:
                best = (dd, tot)
        r['travel'] = best[1] if best else None
        r['exit_door'] = best[0]['id'] if best else None
        if best is None:
            issues.append(f'{r["name"]} has no route to an exit')
        else:
            if worst is None or best[1] > worst[1]:
                worst = (r, best[1])
            if best[1] > limit:
                issues.append(f'{r["name"]}: {best[1]:.2f} m to an exit, over the {limit:g} m limit')
    return {
        'rooms': rl,
        'doors': dl,
        'limit': limit,
        'issues': issues,
        'exits': [dd['id'] for dd in dl if dd['exit']],
        'worst': (worst[0]['name'], worst[1]) if worst else None,
    }


def _rates(over=None):
    r = dict(RATES)
    if isinstance(over, dict):
        for k, v in over.items():
            r[str(k).lower()] = _num(v, RATE_DEFAULT)
    return r


def _src_note(rl):
    if not rl:
        return ''
    src = rl[0]['source']
    return (
        'rooms from zone records'
        if src == 'zone'
        else 'rooms from closed wall/partition loops, so areas are to CENTRE-LINES not to the clear face'
    )


# ── the tools the model calls ────────────────────────────────────────────────
def t_egress_check(d: Drawing, a, max=30, storey=None):  # noqa: A002
    limit = _num(max, 30.0)
    res = egress(d, limit, storey)
    rl = res['rooms']
    if not rl:
        return (
            'no rooms found — rooms come from zone records (p.pts) or from closed loops of wall and '
            'partition centre-lines; draw a closed room first'
        )
    lines = [
        f'escape routes for {len(rl)} rooms, {len(res["exits"])} exit door(s) '
        f"({_src_note(rl)}; door-to-door legs are straight lines and the first leg is the room's "
        f'farthest corner to its door — an approximation, not a routed walk):'
    ]
    for r in rl:
        lines.append(
            f'  {r["name"]:<16} st{r["storey"]} {r["area"]:8.2f} m²  '
            + (f'{r["travel"]:6.2f} m to {r["exit_door"]}' if r['travel'] is not None else '   no exit reachable')
            + ('  OVER LIMIT' if r['travel'] is not None and r['travel'] > limit else '')
        )
    if res['worst']:
        lines.append(f'  worst: {res["worst"][0]} at {res["worst"][1]:.2f} m (limit {limit:g} m)')
    lines.append(f'  {len(res["issues"])} issue(s)' + (': ' + '; '.join(res['issues']) if res['issues'] else ''))
    return '\n'.join(lines)


def t_accessibility_check(d: Drawing, a, turn=1.5, door_w=0.85, storey=None):
    t = _num(turn, 1.5)
    dw = _num(door_w, 0.85)
    rl = rooms(d, storey)
    if not rl:
        return 'no rooms found — draw a closed room or a zone record first'
    doors = _doors_of(rl)
    issues, lines = (
        [],
        [
            f'wheelchair check on {len(rl)} rooms and {len(doors)} doors ({_src_note(rl)}; the turning circle is '
            f"the largest circle inside the room clear of every wall, a door's clear width is its leaf less a "
            f'{FRAME:g} m frame):'
        ],
    )
    for r in rl:
        dia = 2 * in_circle(r['poly'])[2]
        r['turn'] = dia
        bad = dia + 1e-9 < t
        lines.append(f'  {r["name"]:<16} st{r["storey"]} turning circle {dia:5.2f} m' + ('  TOO SMALL' if bad else ''))
        if bad:
            issues.append(f'{r["name"]}: {dia:.2f} m turning circle, under {t:g} m')
    for dd in doors:
        bad = dd['clear'] <= dw
        lines.append(
            f'  {dd["id"]:<16} clear width {dd["clear"]:5.2f} m ({dd["w"]:.2f} m leaf)'
            + ('  TOO NARROW' if bad else '')
        )
        if bad:
            issues.append(f'{dd["id"]}: {dd["clear"]:.2f} m clear, not over {dw:g} m')
    ramps = [o for o in d.objs if 'ramp' in o['kind'] and not o.get('hidden')]
    for dd in doors:
        if len(dd['rooms']) < 2:
            continue
        dy = abs(dd['rooms'][0]['y'] - dd['rooms'][1]['y'])
        if dy <= 0.02:
            continue
        if any(_dist((o['x'], o['z']), dd['mid']) <= 3.0 for o in ramps):
            continue
        issues.append(
            f'{dd["rooms"][0]["name"]} and {dd["rooms"][1]["name"]} differ by {dy:.3f} m '
            f'at {dd["id"]} with no ramp within 3 m'
        )
        lines.append(f'  {dd["id"]:<16} level change {dy:.3f} m, no ramp  FLAGGED')
    lines.append(f'  {len(issues)} issue(s)' + (': ' + '; '.join(issues) if issues else ''))
    return '\n'.join(lines)


def t_occupancy(d: Drawing, a, rates=None, storey=None):
    tab = _rates(rates)
    rl = rooms(d, storey)
    if not rl:
        return 'no rooms found — draw a closed room or a zone record first'
    per, total, issues = {}, 0, []
    lines = [
        f'occupancy of {len(rl)} rooms ({_src_note(rl)}; persons = ceil(area / m² per person). '
        f'ASSUMED exit width 10 mm per person overall, 6 mm per person for corridors):'
    ]
    for r in rl:
        rate = tab.get(r['use'], RATE_DEFAULT)
        persons = math.ceil(r['area'] / rate) if rate > 0 else 0
        r['persons'], r['rate'] = persons, rate
        total += persons
        per[r['storey']] = per.get(r['storey'], 0) + persons
        mm = 0.006 if r['use'] in ('corridor', 'circulation') else 0.010
        need = persons * mm
        clear = sum(dd['clear'] for dd in r['doors'])
        r['exit_width'], r['exit_width_needed'] = clear, need
        lines.append(
            f'  {r["name"]:<16} st{r["storey"]} {r["use"]:<12} {r["area"]:8.2f} m² / '
            + (
                f'{rate:g} = {persons:4d} persons  doors {clear:5.2f} m clear, needs {need:.3f} m'
                if rate > 0
                else '   n/a (circulation)'
            )
        )
        if persons > 0 and clear < need - 1e-9:
            issues.append(f'{r["name"]}: {persons} persons need {need:.3f} m of clear door width, has {clear:.2f} m')
    for s in sorted(per):
        lines.append(f'  storey {s}: {per[s]} persons')
    lines.append(f'  building total: {total} persons')
    lines.append(f'  {len(issues)} issue(s)' + (': ' + '; '.join(issues) if issues else ''))
    return '\n'.join(lines)


def t_fire_compartments(d: Drawing, a, max_area=1000, max_len=60, storey=None):
    ma = _num(max_area, 1000.0)
    ml = _num(max_len, 60.0)
    rl = rooms(d, storey)
    if not rl:
        return 'no rooms found — draw a closed room or a zone record first'
    res = egress(d, ml, storey, room_list=rl)
    comps, order = {}, []
    for r in rl:
        c = r['compartment'] or f'storey {r["storey"]}'
        r['comp'] = c
        if c not in comps:
            comps[c] = {'id': c, 'area': 0.0, 'rooms': [], 'travel': 0.0}
            order.append(c)
        comps[c]['area'] += r['area']
        comps[c]['rooms'].append(r)
        if r.get('travel') and r['travel'] > comps[c]['travel']:
            comps[c]['travel'] = r['travel']
    issues = []
    lines = [
        f'{len(order)} fire compartment(s) over {len(rl)} rooms ({_src_note(rl)}; rooms are grouped by '
        f'meta.compartment or a "comp:X" tag, else one compartment per storey. ASSUMED a compartment '
        f'wall is at least 100 mm thick and not glazed):'
    ]
    for c in order:
        C = comps[c]
        lines.append(
            f'  compartment {c:<10} {len(C["rooms"]):2d} rooms {C["area"]:9.2f} m² '
            f'(max {ma:g})  longest travel {C["travel"]:6.2f} m (max {ml:g})'
        )
        if C['area'] > ma:
            issues.append(f'compartment {c} is {C["area"]:.2f} m², over {ma:g} m²')
        if C['travel'] > ml:
            issues.append(f'compartment {c}: longest travel {C["travel"]:.2f} m, over {ml:g} m')
    by_storey: dict = {}
    for r in rl:
        by_storey.setdefault(r['storey'], []).append(r)
    comp_walls = []
    for st, mine in sorted(by_storey.items()):
        for w in walls_on(d, st):
            mid = ((w['a'][0] + w['b'][0]) / 2, (w['a'][1] + w['b'][1]) / 2)
            sides = _sides_of(mid, w, mine)
            if sides[0] is None or sides[1] is None or sides[0]['comp'] == sides[1]['comp']:
                continue
            thin, glass = w['t'] < 0.1, w['rec'].get('mat') == 'mat_glass'
            comp_walls.append(w['id'])
            lines.append(
                f'  wall {w["id"]:<10} compartment line {sides[0]["comp"]}|{sides[1]["comp"]}, '
                f'{w["t"] * 1000:.0f} mm {w["rec"].get("mat")}' + ('  TOO LIGHT' if thin or glass else '')
            )
            if thin or glass:
                issues.append(
                    f'wall {w["id"]} carries the {sides[0]["comp"]}|{sides[1]["comp"]} compartment '
                    f'line but is ' + ('glass' if glass else f'{w["t"] * 1000:.0f} mm thick')
                )
    fire_doors = []
    for dd in res['doors']:
        if len(dd['rooms']) < 2 or dd['rooms'][0]['comp'] == dd['rooms'][1]['comp']:
            continue
        fire_doors.append(dd['id'])
        lines.append(
            f'  door {dd["id"]:<10} between {dd["rooms"][0]["comp"]} and {dd["rooms"][1]["comp"]} — FIRE DOOR NEEDED'
        )
    lines.append(f'  {len(fire_doors)} fire door(s) needed, {len(comp_walls)} compartment wall(s)')
    lines.append(f'  {len(issues)} issue(s)' + (': ' + '; '.join(issues) if issues else ''))
    return '\n'.join(lines)


_STOREY = {'type': 'integer', 'description': 'only this storey (default: every storey that has walls or zones)'}

TOOLS = [
    (
        {
            'name': 'egress_check',
            'description': 'Travel distance from every room to the nearest exit door, and which rooms are over the '
            'limit. Rooms come from zone records or from closed wall/partition loops; exits are doors '
            'on an exterior wall or tagged "exit". Use it when asked about escape routes or fire safety.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'max': {
                        'type': 'number',
                        'description': 'the travel-distance limit in metres (default 30, the NL '
                        'figure for a compartment exit)',
                    },
                    'storey': _STOREY,
                },
                'required': [],
            },
        },
        t_egress_check,
    ),
    (
        {
            'name': 'accessibility_check',
            'description': 'Wheelchair check: the largest turning circle that fits in each room clear of the walls, '
            'the clear width of every door, and level changes between rooms with no ramp. Use it when '
            'asked whether the plan is accessible or wheelchair friendly.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'turn': {'type': 'number', 'description': 'turning circle diameter in metres (default 1.5)'},
                    'door_w': {'type': 'number', 'description': 'minimum clear door width in metres (default 0.85)'},
                    'storey': _STOREY,
                },
                'required': [],
            },
        },
        t_accessibility_check,
    ),
    (
        {
            'name': 'occupancy',
            'description': 'How many people each room holds, from its use and a m2-per-person table, with the totals '
            'per storey and for the building and the exit width those people need. Use it when asked '
            'how many people fit, or before sizing exits.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rates': {
                        'type': 'object',
                        'description': 'override m2 per person per use, e.g. {"office": 8}; '
                        '0 means circulation and counts nobody',
                    },
                    'storey': _STOREY,
                },
                'required': [],
            },
        },
        t_occupancy,
    ),
    (
        {
            'name': 'fire_compartments',
            'description': "Fire compartments: each compartment's floor area and longest travel distance, the walls "
            'that carry a compartment line but are glass or under 100 mm, and the doors that need to '
            'be fire doors. Rooms are grouped by meta.compartment or a "comp:X" tag.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'max_area': {
                        'type': 'number',
                        'description': 'largest compartment floor area in m2 (default 1000)',
                    },
                    'max_len': {
                        'type': 'number',
                        'description': 'longest travel distance in a compartment in metres (default 60)',
                    },
                    'storey': _STOREY,
                },
                'required': [],
            },
        },
        t_fire_compartments,
    ),
]

EXAMPLES = [
    {'ask': 'how far is it to an exit from each room?', 'calls': [{'tool': 'egress_check', 'args': {'max': 30}}]},
    {
        'ask': 'is this plan wheelchair accessible?',
        'calls': [{'tool': 'accessibility_check', 'args': {'turn': 1.5, 'door_w': 0.85}}],
    },
    {'ask': 'how many people can this office floor hold?', 'calls': [{'tool': 'occupancy', 'args': {}}]},
    {
        'ask': 'check the fire compartments and show me the escape routes on screen',
        'calls': [
            {'tool': 'fire_compartments', 'args': {'max_area': 1000}},
            {'tool': 'press_button', 'args': {'id': 'a_egress', 'args': {'max': 30}}},
        ],
    },
    {
        'ask': 'run the accessibility check in the studio so I can see the sheet',
        'calls': [{'tool': 'press_button', 'args': {'id': 'a_access', 'args': {'turn': 1.5, 'door_w': 0.85}}}],
    },
]
