# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""quantities — the assistant's half of the Quantities dock family (2026-09-07).

Seven icons live in arch_ext/quantities.js (q_volume, q_cost, q_doors, q_rooms,
q_csv, q_units, q_prec); BUTTONS lets the model press them. Because the model
cannot read a sheet, the three TOOLS below are server-side TWINS that return the
same tables as text.

The twin's arithmetic is PARAMETRIC, not meshed: a wall is len*h*t minus its
openings, a slab w*d*t, a column w*d*h or pi*r^2*h, a pitched roof a prism.
Anything else is approximated as half its bounding box and SAID to be approx, so
the model never quotes a guess as a survey. The tab integrates the real mesh
instead, which is why the two agree to a couple of per cent on the shapes that
are boxes and differ honestly on the ones that are not.

Standard library only.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, storey_of, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['q_volume', 'q_cost', 'q_doors', 'q_rooms', 'q_csv', 'q_units', 'q_prec']

PROMPT = (
    'Quantities: quantities(report, which) is the take-off as text — report "volume" (m3 and mass t per '
    'material), "cost" (the rate card against those quantities, itemised, EUR), "doors" (every opening with '
    'its size, host wall and storey) or "rooms" (zone records when the drawing has them, otherwise closed '
    'wall loops). Zones, grid lines, dimensions and guides are drawn but are not material: they are counted '
    'and left out of the volume and the cost, and the report says how many. set_units("m"|'
    '"mm"|"ft") changes how the page DISPLAYS lengths (the model itself is always metres; the properties '
    'panel keeps writing metres) and set_rates({"per_m3":{...},"per_m2":{...},"per_item":{...}}) writes the '
    'cost rate card into the drawing. The same seven icons can be pressed: press_button("q_volume"), '
    'press_button("q_cost", {"rates":{"per_m3":{"concrete":200}}}), press_button("q_doors"), '
    'press_button("q_rooms"), press_button("q_csv", {"report":"doors"}) to download a CSV, '
    'press_button("q_units", {"units":"mm"}) and press_button("q_prec", {"decimals":1}). Press an icon when '
    'the user wants the sheet on screen or the file; call the tool when YOU need the numbers.'
)

WALLS = ('wall', 'partition')
DENSITY = {
    'concrete': 2400,
    'brick': 1800,
    'timber': 600,
    'glass': 2500,
    'plaster': 1200,
    'steel': 7850,
    'asphalt': 2300,
    'soil': 1500,
    'tile': 2000,
    'other': 1000,
}
DEFAULT_RATES = {
    'per_m3': {'concrete': 180, 'brick': 220, 'timber': 650, 'steel': 2400, 'asphalt': 120, 'tile': 900, 'soil': 45},
    'per_m2': {'glass': 350, 'plaster': 25},
    'per_item': {'door': 450, 'window': 600, 'column': 300},
}
UNITS = ('m', 'mm', 'ft')
SNAP = 0.05  # 5 cm: how close two wall ends must be to be one corner

# A DIAGRAM is not a material. A zone is a 5 cm slab drawn over the floor it
# labels, a grid line and a dimension are drawn so you can see them: all of them
# build closed meshes the tab could integrate, none of them is stuff you buy.
# arch_ext/quantities.js excludes exactly this set, which is why the tab's meshed
# take-off and this parametric twin still agree on a drawing that has zones.
DIAGRAM = {'zone', 'gridline', 'annotation', 'dimension', 'label_text', 'markup_note', 'site_boundary'}
DIAGRAM_PREFIXES = ('guide_', 'dim_', 'sculpt_')


def is_diagram(kind: str) -> bool:
    k = str(kind or '')
    return k in DIAGRAM or k.startswith(DIAGRAM_PREFIXES)


_WORDS = (
    ('concrete', ('concrete', 'cement', 'screed')),
    ('brick', ('brick', 'blockwork', 'masonry')),
    ('timber', ('timber', 'wood', 'plank', 'oak', 'pine', 'birch', 'bamboo')),
    ('glass', ('glass', 'glazing', 'glaz')),
    ('plaster', ('plaster', 'render', 'stucco', 'paint')),
    ('steel', ('steel', 'metal', 'iron', 'alu', 'copper', 'brass', 'zinc')),
    ('asphalt', ('asphalt', 'tarmac', 'bitumen')),
    ('soil', ('grass', 'soil', 'earth', 'dirt', 'gravel', 'sand', 'mud')),
    ('tile', ('tile', 'ceramic', 'terracotta', 'slate')),
)


def mat_word(mat: str) -> str:
    """The category word of a material id — the same table the tab uses, so the
    460 acg_* surfaces price themselves by their category."""
    s = str(mat or '').lower()
    for word, needles in _WORDS:
        for n in needles:
            if n in s:
                return word
    return 'other'


def _p(o: dict, key: str, default: float = 0.0) -> float:
    return _num((o.get('p') or {}).get(key), default)


def _is_opening(kind: str) -> bool:
    return kind in ('door', 'double_door', 'window', 'opening') or kind.startswith('window')


def volume_of(o: dict) -> tuple[float, bool]:
    """(m3, approx) from the record's PARAMETERS. approx=True means the number
    came from half a bounding box rather than from the shape itself."""
    k, p = o['kind'], (o.get('p') or {})
    s = _num(o.get('s'), 1.0) or 1.0
    s3 = s**3
    if _is_opening(k) or is_diagram(k):
        return 0.0, False  # a hole and a label are not material
    if k in WALLS:
        len_, h, t = _p(o, 'len', 4), _p(o, 'h', 2.7), _p(o, 't', 0.24 if k == 'wall' else 0.10)
        holes = 0.0
        for hole in p.get('holes') or []:
            holes += _num(hole.get('w'), 0.0) * _num(hole.get('h'), 0.0) * t
        return max(0.0, len_ * h * t - holes) * s3, False
    if k in ('slab', 'pad', 'roof_flat', 'footing'):
        return _p(o, 'w', 0) * _p(o, 'd', 0) * _p(o, 't', 0.2) * s3, False
    if k == 'column_rect':
        return _p(o, 'w', 0.3) * _p(o, 'd', 0.3) * _p(o, 'h', 3) * s3, False
    if k == 'column_round':
        return math.pi * _p(o, 'r', 0.18) ** 2 * _p(o, 'h', 3) * s3, False
    if k == 'beam':
        return _p(o, 'len', 5) * _p(o, 'w', 0.2) * _p(o, 'h', 0.4) * s3, False
    if k.startswith('roof_'):  # a pitched roof is a prism: half its box
        return _p(o, 'w', 6) * _p(o, 'd', 6) * _p(o, 'h', 2) * 0.5 * s3, False
    if 'w' in p and 'd' in p and ('h' in p or 't' in p):
        return _p(o, 'w', 0) * _p(o, 'd', 0) * (_p(o, 'h', 0.0) or _p(o, 't', 0.0)) * s3, False
    # anything else: half its bounding box, and say so
    w = _p(o, 'w', 0.0) or _p(o, 'len', 0.0) or (2 * _p(o, 'r', 0.0))
    d = _p(o, 'd', 0.0) or _p(o, 't', 0.0) or (2 * _p(o, 'r', 0.0)) or w
    h = _p(o, 'h', 0.0) or _p(o, 't', 0.0)
    if w <= 0 or d <= 0 or h <= 0:
        return 0.0, False
    return w * d * h * 0.5 * s3, True


def area_of(o: dict) -> float:
    """Vertical face area in m2 — a wall's len*h net of its openings, a pane's w*h."""
    k, p = o['kind'], (o.get('p') or {})
    s = _num(o.get('s'), 1.0) or 1.0
    if is_diagram(k):
        return 0.0
    if k in WALLS:
        a = _p(o, 'len', 4) * _p(o, 'h', 2.7)
        for hole in p.get('holes') or []:
            a -= _num(hole.get('w'), 0.0) * _num(hole.get('h'), 0.0)
        return max(0.0, a) * s * s
    if 'w' in p and 'h' in p and 'd' not in p:
        return _p(o, 'w', 0) * _p(o, 'h', 0) * s * s
    return 0.0


def take_off(recs: list, storey_h: float) -> dict:
    by_mat: dict = {}
    approx = 0
    diagram = 0
    for o in recs:
        if o.get('hidden'):
            continue
        if is_diagram(o['kind']):
            diagram += 1
            continue
        v, ap = volume_of(o)
        if ap and v > 0:
            approx += 1
        a = area_of(o)
        if v <= 0 and a <= 0:
            continue
        w = mat_word(o.get('mat'))
        e = by_mat.setdefault(w, {'n': 0, 'vol': 0.0, 'area': 0.0, 'mass': 0.0})
        e['n'] += 1
        e['vol'] += v
        e['area'] += a
        e['mass'] += v * DENSITY.get(w, 1000)
    return {
        'by_mat': by_mat,
        'approx': approx,
        'diagram': diagram,
        'vol': sum(e['vol'] for e in by_mat.values()),
        'mass': sum(e['mass'] for e in by_mat.values()),
    }


def _ext(d: Drawing) -> dict:
    e = d.ext.get('quantities')
    if not isinstance(e, dict):
        e = {}
        d.ext['quantities'] = e
    return e


def rates_of(d: Drawing) -> dict:
    out = {g: dict(v) for g, v in DEFAULT_RATES.items()}
    stored = _ext(d).get('rates')
    if isinstance(stored, dict):
        for g in ('per_m3', 'per_m2', 'per_item'):
            if isinstance(stored.get(g), dict):
                for k, v in stored[g].items():
                    try:
                        out[g][str(k)] = float(v)
                    except (TypeError, ValueError) as _exc:
                        _zyg_log.warning('ignoring non-numeric stored rate %s/%s=%r: %s', g, k, v, _exc)
                        continue
    return out


def _shoelace(pts) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        s += ax * by - bx * ay
    return s / 2.0


def _perimeter(pts) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        s += math.hypot(bx - ax, by - ay)
    return s


def rooms_of(recs: list, storey_h: float) -> tuple[str, list]:
    """(method, rooms). Zones when the drawing declares them, otherwise the
    bounded faces of the wall graph — the same walk the tab does: snap the wall
    ends onto a 5 cm grid, sort the edges round each node by angle and always
    take the next edge clockwise from the one we arrived on. In (x, -z) that
    gives every enclosed face a positive area and the outside a negative one."""
    zones = [o for o in recs if o['kind'] == 'zone' and not o.get('hidden')]
    if zones:
        out = []
        for o in zones:
            pts = (o.get('p') or {}).get('pts') or []
            if not isinstance(pts, list) or len(pts) < 3:
                continue
            q = [(_num(p[0], 0.0), -_num(p[1], 0.0)) for p in pts]
            out.append(
                {
                    'name': o.get('name') or '',
                    'storey': storey_of(o['y'], storey_h),
                    'area': abs(_shoelace(q)),
                    'perim': _perimeter(q),
                    'use': str((o.get('p') or {}).get('use') or ''),
                }
            )
        out.sort(key=lambda r: (r['storey'], -r['area']))
        return 'zone records', out

    by_storey: dict = {}
    for o in recs:
        if o.get('hidden') or o['kind'] not in WALLS:
            continue
        s = _num(o.get('s'), 1.0) or 1.0
        L = _p(o, 'len', 4) * s
        if L < 0.01:
            continue
        ry = _num(o.get('ry'), 0.0)
        dx, dz = (L / 2) * math.cos(ry), -(L / 2) * math.sin(ry)
        by_storey.setdefault(storey_of(o['y'], storey_h), []).append(
            ((o['x'] - dx, o['z'] - dz), (o['x'] + dx, o['z'] + dz))
        )

    out = []
    for st, segs in sorted(by_storey.items()):
        nodes: dict = {}
        adj: dict = {}
        for a, b in segs:
            ka = (round(a[0] / SNAP), round(a[1] / SNAP))
            kb = (round(b[0] / SNAP), round(b[1] / SNAP))
            if ka == kb:
                continue
            nodes[ka] = (ka[0] * SNAP, ka[1] * SNAP)
            nodes[kb] = (kb[0] * SNAP, kb[1] * SNAP)
            adj.setdefault(ka, set()).add(kb)
            adj.setdefault(kb, set()).add(ka)
        order = {
            k: sorted(v, key=lambda n, k=k: math.atan2(-(nodes[n][1] - nodes[k][1]), nodes[n][0] - nodes[k][0]))
            for k, v in adj.items()
        }
        seen: set = set()
        for u in adj:
            for v0 in adj[u]:
                if (u, v0) in seen:
                    continue
                loop = []
                a, b, guard = u, v0, 0
                while guard < 4000:
                    guard += 1
                    if (a, b) in seen:
                        break
                    seen.add((a, b))
                    loop.append(a)
                    ring = order[b]
                    if a not in ring:
                        break
                    nxt = ring[(ring.index(a) - 1) % len(ring)]
                    a, b = b, nxt
                    if a == u and b == v0:
                        break
                if len(loop) >= 3:
                    pts = [(nodes[k][0], -nodes[k][1]) for k in loop]
                    A = _shoelace(pts)
                    if A > 0.05:
                        out.append({'name': '', 'storey': st, 'area': A, 'perim': _perimeter(pts), 'use': ''})
    out.sort(key=lambda r: (r['storey'], -r['area']))
    return 'closed wall loops', out


# ── the tools ───────────────────────────────────────────────────────────────
def t_quantities(d: Drawing, a, report='volume', which='all'):
    rep = str(report or 'volume').strip().lower()
    recs = d.select(which if which not in (None, '') else 'all')
    if not recs:
        return f'nothing matches "{which}" — pass "all", "new", a kind, a group name or ids'

    if rep == 'volume':
        t = take_off(recs, d.storey_h)
        if not t['by_mat']:
            return f'volume of {len(recs)} objects: 0.00 m3 — none of them is a solid with thickness'
        lines = [
            f'volume and mass by material, {len(recs)} objects (parametric, from the records):',
            '  material     count      m3        t',
        ]
        for w, e in sorted(t['by_mat'].items(), key=lambda kv: -kv[1]['vol']):
            lines.append(f'  {w:<12} {e["n"]:>5} {e["vol"]:>9.3f} {e["mass"] / 1000:>8.3f}')
        counted = sum(e['n'] for e in t['by_mat'].values())
        lines.append(f'  {"total":<12} {counted:>5} {t["vol"]:>9.3f} {t["mass"] / 1000:>8.3f}')
        if t['approx']:
            lines.append(f'  ({t["approx"]} objects are approx: half their bounding box)')
        if t['diagram']:
            lines.append(
                f'  ({t["diagram"]} diagram objects — zones, grid lines, dimensions, guides — '
                'are drawn but not material, so they are left out)'
            )
        return '\n'.join(lines)

    if rep == 'cost':
        t = take_off(recs, d.storey_h)
        R = rates_of(d)
        lines, total = ['cost estimate (EUR, rate card in doc.ext.quantities.rates):'], 0.0
        for w, e in sorted(t['by_mat'].items()):
            r3, r2 = R['per_m3'].get(w), R['per_m2'].get(w)
            if r3 and e['vol'] > 1e-9:
                amt = e['vol'] * r3
                total += amt
                lines.append(f'  {w:<12} {e["vol"]:>9.3f} m3 x {r3:>8.2f} = {amt:>12.2f}')
            if r2 and e['area'] > 1e-9:
                amt = e['area'] * r2
                total += amt
                lines.append(f'  {w:<12} {e["area"]:>9.2f} m2 x {r2:>8.2f} = {amt:>12.2f}')
        items = {'door': 0, 'window': 0, 'column': 0}
        for o in recs:
            if o.get('hidden'):
                continue
            if o['kind'] in ('door', 'double_door'):
                items['door'] += 1
            elif o['kind'].startswith('window'):
                items['window'] += 1
            elif o['kind'].startswith('column'):
                items['column'] += 1
        for k, n in items.items():
            r = R['per_item'].get(k)
            if n and r:
                amt = n * r
                total += amt
                lines.append(f'  {k:<12} {n:>9} it x {r:>8.2f} = {amt:>12.2f}')
        lines.append(f'  {"TOTAL":<12} {"":>9}    {"":>8}   {total:>12.2f}')
        if t['approx']:
            lines.append(f'  ({t["approx"]} objects priced off an approximate volume)')
        return '\n'.join(lines)

    if rep in ('doors', 'openings'):
        rows = [o for o in recs if _is_opening(o['kind']) and not o.get('hidden')]
        if not rows:
            return 'door and window schedule: no openings in this selection'
        rows.sort(key=lambda o: (storey_of(o['y'], d.storey_h), str((o.get('p') or {}).get('host') or '')))
        lines = [f'door and window schedule, {len(rows)} openings (id, kind, w x h, sill, host, storey, material):']
        for o in rows[:120]:
            p = o.get('p') or {}
            lines.append(
                f'  {o["id"]:<6} {o["kind"]:<12} {_p(o, "w", 0):.2f} x {_p(o, "h", 0):.2f} m  '
                f'sill {_p(o, "sill", 0):.2f}  host {str(p.get("host") or "-"):<6} '
                f'st{storey_of(o["y"], d.storey_h)}  {o.get("mat") or "-"}'
            )
        if len(rows) > 120:
            lines.append(f'  ... and {len(rows) - 120} more')
        return '\n'.join(lines)

    if rep == 'rooms':
        method, rms = rooms_of(recs, d.storey_h)
        if not rms:
            return (
                f'room schedule: no enclosed rooms found by {method} — rooms come from zone records if the '
                'drawing has them, otherwise from walls whose ends meet within 5 cm'
            )
        lines = [f'room schedule, {len(rms)} rooms by {method}:']
        for i, r in enumerate(rms[:120], 1):
            lines.append(
                f'  {r["name"] or ("Room " + str(i)):<12} st{r["storey"]}  '
                f'{r["area"]:>8.2f} m2  perimeter {r["perim"]:>7.2f} m  '
                f'{r["use"] or "-"}'
            )
        lines.append(f'  total {sum(r["area"] for r in rms):.2f} m2')
        return '\n'.join(lines)

    return 'refused: report must be one of volume, cost, doors, rooms'


def t_set_units(d: Drawing, a, units='m', decimals=None):
    u = str(units or 'm').strip().lower()
    if u not in UNITS:
        return 'refused: units must be "m", "mm" or "ft"'
    e = _ext(d)
    e['units'] = u
    msg = f'display units set to {u}'
    if decimals is not None:
        try:
            dec = max(0, min(3, int(decimals)))
        except (TypeError, ValueError):
            return 'refused: decimals must be 0, 1, 2 or 3'
        e['decimals'] = dec
        msg += f', {dec} decimals'
    d.ui.append({'cmd': 'toast', 'args': {'text': msg + ' (the model itself stays in metres)'}})
    return (
        msg + ' — this only changes how the page SHOWS lengths; the drawing and the properties '
        'panel are always metres. Saved in doc.ext.quantities.'
    )


def t_set_rates(d: Drawing, a, rates=None):
    if not isinstance(rates, dict):
        return (
            'refused: pass rates like {"per_m3": {"concrete": 200}, "per_m2": {"glass": 400}, '
            '"per_item": {"door": 500}}'
        )
    R = rates_of(d)
    n = 0
    for g in ('per_m3', 'per_m2', 'per_item'):
        if isinstance(rates.get(g), dict):
            for k, v in rates[g].items():
                try:
                    R[g][str(k)] = float(v)
                except (TypeError, ValueError) as _exc:
                    _zyg_log.warning('ignoring non-numeric rate %s/%s=%r: %s', g, k, v, _exc)
                    continue
                n += 1
    if not n:
        return 'refused: none of the rates parsed as numbers — keys are per_m3, per_m2, per_item'
    _ext(d)['rates'] = R
    return (
        f'{n} rates written into the drawing (doc.ext.quantities.rates). '
        f'per_m3: {", ".join(f"{k} {v:g}" for k, v in sorted(R["per_m3"].items()))}. '
        'Call quantities("cost") to price the model with them.'
    )


TOOLS = [
    (
        {
            'name': 'quantities',
            'description': 'The quantity take-off as text: report "volume" (m3 and mass per material), "cost" '
            '(the rate card against those quantities), "doors" (the opening schedule) or "rooms" '
            '(enclosed rooms with area and perimeter). Use it when you need the numbers yourself; '
            'press_button("q_volume") when the user wants the sheet on screen.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'report': {'type': 'string', 'enum': ['volume', 'cost', 'doors', 'rooms']},
                    'which': {
                        'type': 'string',
                        'description': '"all" (default), "new", a kind, a group name, or an object id',
                    },
                },
                'required': [],
            },
        },
        t_quantities,
    ),
    (
        {
            'name': 'set_units',
            'description': 'Set how the page DISPLAYS lengths: "m", "mm" or "ft" (feet and inches), optionally with '
            'a number of decimals 0-3. The model itself is always metres and the properties panel '
            'keeps writing metres. Saved with the drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {'units': {'type': 'string', 'enum': list(UNITS)}, 'decimals': {'type': 'integer'}},
                'required': ['units'],
            },
        },
        t_set_units,
    ),
    (
        {
            'name': 'set_rates',
            'description': 'Write the cost rate card into the drawing: {"per_m3": {"concrete": 180, ...}, '
            '"per_m2": {"glass": 350, ...}, "per_item": {"door": 450, ...}} in EUR. Use it before '
            'quantities("cost") when the user gives you prices.',
            'input_schema': {'type': 'object', 'properties': {'rates': {'type': 'object'}}, 'required': ['rates']},
        },
        t_set_rates,
    ),
]

EXAMPLES = [
    {
        'ask': 'how much concrete is in this and what does it weigh?',
        'calls': [{'tool': 'quantities', 'args': {'report': 'volume'}}],
    },
    {'ask': 'what would this cost to build?', 'calls': [{'tool': 'quantities', 'args': {'report': 'cost'}}]},
    {
        'ask': 'concrete is 200 a cube here — re-price it and show me the sheet',
        'calls': [
            {'tool': 'set_rates', 'args': {'rates': {'per_m3': {'concrete': 200}}}},
            {'tool': 'press_button', 'args': {'id': 'q_cost'}},
        ],
    },
    {
        'ask': 'list every door and window with its size',
        'calls': [
            {'tool': 'quantities', 'args': {'report': 'doors'}},
            {'tool': 'press_button', 'args': {'id': 'q_doors'}},
        ],
    },
    {
        'ask': 'how big are the rooms on the ground floor?',
        'calls': [{'tool': 'quantities', 'args': {'report': 'rooms'}}],
    },
    {
        'ask': 'give me the door schedule as a spreadsheet',
        'calls': [{'tool': 'press_button', 'args': {'id': 'q_csv', 'args': {'report': 'doors'}}}],
    },
    {
        'ask': 'show everything in millimetres',
        'calls': [
            {'tool': 'set_units', 'args': {'units': 'mm'}},
            {'tool': 'press_button', 'args': {'id': 'q_units', 'args': {'units': 'mm'}}},
        ],
    },
    {
        'ask': 'one decimal place is enough',
        'calls': [{'tool': 'press_button', 'args': {'id': 'q_prec', 'args': {'decimals': 1}}}],
    },
]
