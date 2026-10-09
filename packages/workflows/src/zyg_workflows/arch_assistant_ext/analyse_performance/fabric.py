# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""analyse_performance.fabric — constructions, orientation/obstruction and the four measured analyses: daylight, u-values, energy, structure.

Moved verbatim from analyse_performance.py (lines 302-817) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

import math
import re
from zyg_workflows.arch_assistant_ext.analyse_performance.geometry import (
    FAM,
    _centroid,
    _is_opening,
    _is_roof,
    _is_wall,
    _live,
    _n,
    _openings_of,
    _pt_in_poly,
    _storey_h,
    _wall_room_count,
    rooms,
)

# ── constructions ────────────────────────────────────────────────────────────
RSI, RSE = 0.13, 0.04
DEFAULT_CONS = {
    'mat_concrete': {
        'label': 'Concrete wall, insulated (default wall)',
        'type': 'wall',
        'layers': [
            {'name': 'plaster', 'd': 0.012, 'lambda': 0.51},
            {'name': 'insulation (mineral wool)', 'd': 0.12, 'lambda': 0.035},
            {'name': 'concrete', 'd': 0.24, 'lambda': 2.0},
        ],
    },
    'mat_brick': {
        'label': 'Brick cavity wall',
        'type': 'wall',
        'layers': [
            {'name': 'plaster', 'd': 0.012, 'lambda': 0.51},
            {'name': 'blockwork', 'd': 0.10, 'lambda': 1.13},
            {'name': 'insulation (cavity fill)', 'd': 0.10, 'lambda': 0.035},
            {'name': 'facing brick', 'd': 0.10, 'lambda': 0.77},
        ],
    },
    'mat_blockwork': {
        'label': 'Blockwork wall',
        'type': 'wall',
        'layers': [
            {'name': 'plaster', 'd': 0.012, 'lambda': 0.51},
            {'name': 'insulation', 'd': 0.10, 'lambda': 0.035},
            {'name': 'blockwork', 'd': 0.20, 'lambda': 1.13},
        ],
    },
    'mat_timber': {
        'label': 'Timber frame wall',
        'type': 'wall',
        'layers': [
            {'name': 'plasterboard', 'd': 0.0125, 'lambda': 0.25},
            {'name': 'insulation between studs', 'd': 0.14, 'lambda': 0.038},
            {'name': 'sheathing', 'd': 0.018, 'lambda': 0.13},
            {'name': 'timber cladding', 'd': 0.022, 'lambda': 0.13},
        ],
    },
    'mat_glass': {
        'label': 'Double glazing unit',
        'type': 'glass',
        'layers': [{'name': 'sealed double glazed unit (argon, low-e)', 'r': 0.739}],
    },
    'roof': {
        'label': 'Warm flat/pitched roof',
        'type': 'roof',
        'layers': [
            {'name': 'roof covering', 'd': 0.01, 'lambda': 0.23},
            {'name': 'insulation (PIR)', 'd': 0.22, 'lambda': 0.035},
            {'name': 'deck', 'd': 0.018, 'lambda': 0.13},
        ],
    },
    'floor': {
        'label': 'Insulated ground slab',
        'type': 'floor',
        'layers': [
            {'name': 'screed', 'd': 0.05, 'lambda': 1.15},
            {'name': 'insulation', 'd': 0.16, 'lambda': 0.035},
            {'name': 'concrete slab', 'd': 0.20, 'lambda': 2.0},
        ],
    },
}
# Bouwbesluit 2021, nieuwbouw (NL) — maximum U per element, W/m2K
NL_LIMIT = {'wall': 0.21, 'roof': 0.16, 'floor': 0.21, 'glass': 1.65}


def _ext_bag(d):
    b = getattr(d, 'ext', {}) or {}
    v = b.get(FAM)
    return v if isinstance(v, dict) else {}


def _norm_layers(v):
    arr = v if isinstance(v, list) else (v.get('layers') if isinstance(v, dict) else None)
    if not isinstance(arr, list):
        return None
    out = []
    for l in arr:
        if not isinstance(l, dict):
            continue
        o = {'name': str(l.get('name') or 'layer')}
        if l.get('d') is not None:
            o['d'] = _n(l['d'], 0.0)
        if l.get('lambda') is not None:
            o['lambda'] = _n(l['lambda'], 1.0)
        if l.get('r') is not None:
            o['r'] = _n(l['r'], 0.0)
        out.append(o)
    return out or None


def u_of(layers):
    r = RSI + RSE
    for l in layers or []:
        if l.get('r') is not None:
            r += max(0.0, l['r'])
        elif l.get('d') is not None and l.get('lambda'):
            r += max(0.0, l['d']) / max(0.001, l['lambda'])
    return 1.0 / max(0.02, r)


def constructions(d):
    """Defaults overridden by the drawing's own build-ups. No write."""
    out = {}
    for k, v in DEFAULT_CONS.items():
        out[k] = {
            'key': k,
            'label': v['label'],
            'type': v['type'],
            'layers': [dict(l) for l in v['layers']],
            'edited': False,
        }
    for k, v in (_ext_bag(d).get('constructions') or {}).items():
        L = _norm_layers(v)
        if not L:
            continue
        base = out.get(k, {})
        lab = (v.get('label') if isinstance(v, dict) else None) or base.get('label') or k
        typ = (v.get('type') if isinstance(v, dict) else None) or base.get('type') or 'wall'
        out[k] = {'key': k, 'label': lab, 'type': typ, 'layers': L, 'edited': True}
    for c in out.values():
        c['u'] = u_of(c['layers'])
    return out


def _cons_key(o, cons):
    if _is_opening(o['kind']):
        return 'mat_glass'
    if _is_roof(o):
        return 'roof'
    if o['kind'] in ('slab', 'pad'):
        return 'floor'
    if o.get('mat') in cons:
        return o['mat']
    return 'mat_concrete'


# ── orientation / obstruction ────────────────────────────────────────────────
def _north(d):
    ls = (getattr(d, 'ext', {}) or {}).get('light_sun')
    deg = _n(ls.get('north'), 0.0) if isinstance(ls, dict) else 0.0
    a = math.radians(deg)
    return math.sin(a), -math.cos(a), deg


def _compass(nx, nz, nrt):
    b = math.degrees(math.atan2(nx * nrt[1] - nz * nrt[0], nx * nrt[0] + nz * nrt[1])) % 360
    return ['N', 'W', 'S', 'E'][int(round(b / 90)) % 4]


def _outward(w, rms, cx, cz):
    n = (math.sin(_n(w.get('ry'), 0.0)), math.cos(_n(w.get('ry'), 0.0)))
    tx, tz = cx, cz
    for r in rms:
        if any(x is w for x in r['walls']):
            tx, tz = _centroid(r['pts'])
            break
    return n if n[0] * (w['x'] - tx) + n[1] * (w['z'] - tz) >= 0 else (-n[0], -n[1])


def _top_y(o):
    p = o.get('p') or {}
    if p.get('h') is not None:
        return _n(o['y'], 0.0) + _n(p['h'], 0.0)
    if p.get('t') is not None:
        return _n(o['y'], 0.0) + _n(p['t'], 0.0)
    if p.get('r') is not None:
        return _n(o['y'], 0.0) + 2 * _n(p['r'], 0.0)
    return _n(o['y'], 0.0)


SKIP_OBS = {'ground', 'pad', 'road', 'path', 'guide_line', 'guide_circle', 'person', 'annotation', 'dimension'}


def _sky_angle(d, room):
    cx, cz = _centroid(room['pts'])
    eye, best, who = room['y'] + 1.2, 65.0, ''
    own = room['walls']
    for o in _live(d):
        if _is_opening(o['kind']) or o['kind'] in SKIP_OBS or str(o['kind']).startswith('sculpt_'):
            continue
        if any(o is w for w in own):
            continue
        if _pt_in_poly(room['pts'], o['x'], o['z']):
            continue
        dist = math.hypot(o['x'] - cx, o['z'] - cz)
        if dist < 0.5 or dist > 20:
            continue
        rise = _top_y(o) - eye
        if rise <= 0.1:
            continue
        th = 90 - math.degrees(math.atan2(rise, dist))
        if th < best:
            best, who = th, '%s %s at %.1f m' % (o['id'], o['kind'], dist)
    return max(5.0, best), who


# ── 1. DAYLIGHT ──────────────────────────────────────────────────────────────
T_GLASS, R_SURF, FRAME = 0.7, 0.5, 0.8
_LIVING = re.compile(r'living|lounge|sitting|bed|kitchen|dining|study|office|family', re.I)


def daylight(d, target=None):
    rms, source = rooms(d)
    walls = [o for o in _live(d) if _is_wall(o)]
    hosted, cnt = _openings_of(d, walls), _wall_room_count(rms)
    forced = _n(target, None) if target not in (None, '') else None
    rows, issues = [], []
    for r in rms:
        ws = r['walls']
        h = max([_n(w['p'].get('h'), _storey_h(d)) for w in ws] or [0]) or _storey_h(d)
        aw, nw, ext = 0.0, 0, 0
        for w in ws:
            if cnt.get(w['id'], 0) >= 2:
                continue
            ext += 1
            for o in hosted.get(w['id'], []):
                if o['kind'] != 'window':
                    continue
                aw += _n(o['p'].get('w'), 1.2) * _n(o['p'].get('h'), 1.4) * FRAME
                nw += 1
        atot = 2 * r['area'] + r['perim'] * h
        theta, obs = _sky_angle(d, r)
        df = (aw * theta * T_GLASS) / (atot * (1 - R_SURF**2)) if atot > 0 else 0.0
        tgt = forced if forced is not None else (2.0 if _LIVING.search(r['name']) else 1.0)
        rows.append(
            {
                'room': r['name'],
                'area': r['area'],
                'windows': nw,
                'ext_walls': ext,
                'Aw': aw,
                'Atotal': atot,
                'theta': theta,
                'obstruction': obs,
                'df': df,
                'target': tgt,
            }
        )
        if df < tgt:
            issues.append(
                {
                    'severity': 'error' if df < tgt / 2 else 'warning',
                    'ids': [w['id'] for w in ws],
                    'text': '%s: average daylight factor %.2f %% is below the %.1f %% target '
                    '(BRE 209)%s' % (r['name'], df, tgt, '' if nw else ' — no window on an exterior wall'),
                }
            )
    return {
        'id': 'a_daylight',
        'name': 'Daylight factor',
        'family': FAM,
        'source': source,
        'rows': rows,
        'issues': issues,
        'summary': '%d room(s) from %s; %d below target' % (len(rms), source, len(issues)),
    }


# ── 2. U-VALUES ──────────────────────────────────────────────────────────────
def uvalues(d):
    cons = constructions(d)
    rows, issues = [], []
    for k in sorted(cons):
        c = cons[k]
        rows.append(c)
        lim = NL_LIMIT.get(c['type'])
        if lim and c['u'] > lim + 1e-6:
            issues.append(
                {
                    'severity': 'error' if c['u'] > lim * 1.5 else 'warning',
                    'ids': [],
                    'text': '%s: U = %.3f W/m2K is above the Bouwbesluit 2021 %s limit of %s'
                    % (c['label'], c['u'], c['type'], lim),
                }
            )
    return {
        'id': 'a_uvalue',
        'name': 'U-values',
        'family': FAM,
        'rows': rows,
        'issues': issues,
        'constructions': cons,
        'summary': '%d constructions, %d above the NL new-build limit' % (len(rows), len(issues)),
    }


# ── 3. ENERGY ────────────────────────────────────────────────────────────────
ACH, C_AIR = 0.5, 0.34


def energy(d, degree_days=None):
    cons = constructions(d)
    rms, source = rooms(d)
    walls = [o for o in _live(d) if _is_wall(o)]
    hosted, cnt, nrt = _openings_of(d, walls), _wall_room_count(rms), _north(d)
    cx = sum(w['x'] for w in walls) / len(walls) if walls else 0.0
    cz = sum(w['z'] for w in walls) / len(walls) if walls else 0.0

    orient = {k: {'wall': 0.0, 'glass': 0.0} for k in 'NESW'}
    wall_gross = wall_net = glass_a = door_a = 0.0
    u_sum, u_n = 0.0, 0
    for w in walls:
        if cnt.get(w['id'], 0) >= 2:
            continue
        a = _n(w['p'].get('len'), 4.0) * _n(w['p'].get('h'), _storey_h(d))
        g = dr = 0.0
        for o in hosted.get(w['id'], []):
            area = _n(o['p'].get('w'), 1.0) * _n(o['p'].get('h'), 2.1)
            if o['kind'] == 'window':
                g += area
            else:
                dr += area
        nx, nz = _outward(w, rms, cx, cz)
        face = _compass(nx, nz, nrt)
        orient[face]['wall'] += a
        orient[face]['glass'] += g
        wall_gross += a
        glass_a += g
        door_a += dr
        wall_net += max(0.0, a - g - dr)
        c = cons.get(_cons_key(w, cons))
        if c:
            u_sum += c['u']
            u_n += 1
    wall_u = u_sum / u_n if u_n else cons['mat_concrete']['u']

    parts = [{'what': 'exterior walls (net of openings)', 'area': wall_net, 'u': wall_u}]
    if glass_a + door_a > 0:
        parts.append({'what': 'windows and doors', 'area': glass_a + door_a, 'u': cons['mat_glass']['u']})
    roof_a = floor_a = 0.0
    for o in _live(d):
        p = o['p']
        if _is_roof(o):
            roof_a += _n(p.get('w'), 8.0) * _n(p.get('d'), 6.0)
        elif o['kind'] in ('slab', 'pad') and _n(o['y'], 0.0) <= 0.05:
            floor_a += _n(p.get('w'), 6.0) * _n(p.get('d'), 4.0)
    if roof_a > 0:
        parts.append({'what': 'roofs', 'area': roof_a, 'u': cons['roof']['u']})
    if floor_a > 0:
        parts.append({'what': 'ground slabs', 'area': floor_a, 'u': cons['floor']['u']})
    ha = 0.0
    for p in parts:
        p['h'] = p['area'] * p['u']
        ha += p['h']

    vol = sum(r['area'] for r in rms) * _storey_h(d) or floor_a * _storey_h(d)
    hv = ACH * vol * C_AIR
    h = ha + hv
    dd = _n(degree_days, _n(_ext_bag(d).get('degree_days'), 2800.0))
    kwh = h * 24 * dd / 1000

    issues = []
    for o in 'NESW':
        a = orient[o]
        if a['wall'] < 1:
            continue
        g = a['glass'] / a['wall']
        if g > 0.40:
            issues.append(
                {
                    'severity': 'warning',
                    'ids': [],
                    'text': 'Glazing ratio %.0f %% on the %s facade is above 40 %%' % (g * 100, o),
                }
            )
        elif g < 0.10:
            issues.append(
                {
                    'severity': 'warning',
                    'ids': [],
                    'text': 'Glazing ratio %.0f %% on the %s facade is below 10 %%' % (g * 100, o),
                }
            )
    if not wall_gross:
        issues.append(
            {'severity': 'error', 'ids': [], 'text': 'No exterior wall found — there is no heated envelope to model'}
        )

    return {
        'id': 'a_energy',
        'name': 'Energy model',
        'family': FAM,
        'source': source,
        'issues': issues,
        'parts': parts,
        'orient': orient,
        'north': nrt[2],
        'wall_gross': wall_gross,
        'wall_net': wall_net,
        'glass': glass_a,
        'doors': door_a,
        'roof_area': roof_a,
        'floor_area': floor_a,
        'volume': vol,
        'HA': ha,
        'Hv': hv,
        'H': h,
        'degree_days': dd,
        'kwh': kwh,
        'rooms': len(rms),
        'glazing_ratio': (glass_a / wall_gross) if wall_gross else 0.0,
        'summary': 'envelope %.0f m2, H = %.1f W/K, %.0f kWh/year' % (wall_gross + roof_a + floor_a, h, kwh),
    }


# ── 4. STRUCTURE ─────────────────────────────────────────────────────────────
SPAN_DEPTH = {'mat_timber': 20, 'mat_concrete': 25, 'mat_steel': 30}


def _supports_under(d, o, y_top):
    out = []
    for s in _live(d):
        if s is o or not (_is_wall(s) or s['kind'] in ('column_rect', 'column_round')):
            continue
        t = _top_y(s)
        if y_top - 1.2 < t < y_top + 0.6:
            out.append(s)
    return out


def _gap_along(coords, lo, hi):
    c = sorted([v for v in coords if lo - 0.01 < v < hi + 0.01] + [lo, hi])
    return max((c[i] - c[i - 1] for i in range(1, len(c))), default=hi - lo)


def structure(d):
    rows, issues = [], []
    for o in _live(d):
        p, k = o['p'], o['kind']
        if k == 'beam':
            span, dep = _n(p.get('len'), 5.0), _n(p.get('h'), 0.4)
            lim = SPAN_DEPTH.get(o.get('mat'), 20)
            ratio = span / dep if dep > 0 else 1e9
            rows.append(
                'Beam %s (%s): span %.2f m / depth %.2f m = %.1f (limit %d)'
                % (o['id'], o.get('mat'), span, dep, ratio, lim)
            )
            if ratio > lim:
                issues.append(
                    {
                        'severity': 'error' if ratio > lim * 1.4 else 'warning',
                        'ids': [o['id']],
                        'text': 'Beam %s: span/depth %.1f exceeds the %d rule of thumb for %s '
                        '(span %.2f m, depth %.2f m)'
                        % (o['id'], ratio, lim, str(o.get('mat')).replace('mat_', ''), span, dep),
                    }
                )
        elif k in ('column_rect', 'column_round'):
            ch = _n(p.get('h'), 3.0)
            least = 2 * _n(p.get('r'), 0.18) if k == 'column_round' else min(_n(p.get('w'), 0.3), _n(p.get('d'), 0.3))
            sl = ch / least if least > 0 else 1e9
            rows.append('Column %s: height %.2f m / least dim %.3f m = %.1f (limit 20)' % (o['id'], ch, least, sl))
            if sl > 20:
                issues.append(
                    {
                        'severity': 'error' if sl > 30 else 'warning',
                        'ids': [o['id']],
                        'text': 'Column %s: slenderness %.1f (unbraced height %.2f m / least dimension '
                        '%.3f m) is over the 20 rule of thumb' % (o['id'], sl, ch, least),
                    }
                )
        elif k == 'slab':
            w, dd_, t = _n(p.get('w'), 6.0), _n(p.get('d'), 4.0), _n(p.get('t'), 0.22)
            sup = _supports_under(d, o, _n(o['y'], 0.0))
            sx = _gap_along([s['x'] for s in sup], o['x'] - w / 2, o['x'] + w / 2)
            sz = _gap_along([s['z'] for s in sup], o['z'] - dd_ / 2, o['z'] + dd_ / 2)
            sp = min(sx, sz)
            rr = sp / t if t > 0 else 1e9
            rows.append(
                'Slab %s: span %.2f m / thickness %.3f m = %.1f (limit 30, %d supports)'
                % (o['id'], sp, t, rr, len(sup))
            )
            if rr > 30:
                issues.append(
                    {
                        'severity': 'error' if rr > 45 else 'warning',
                        'ids': [o['id']],
                        'text': 'Slab %s: span/thickness %.1f exceeds 30 (shorter span %.2f m, '
                        'thickness %.3f m)' % (o['id'], rr, sp, t),
                    }
                )
        elif _is_roof(o):
            rw, rd = _n(p.get('w'), 8.0), _n(p.get('d'), 6.0)
            sp = min(rw, rd)
            inner = [
                s
                for s in _live(d)
                if s is not o
                and (_is_wall(s) or s['kind'] in ('column_rect', 'column_round', 'truss'))
                and abs(s['x'] - o['x']) < rw / 2 - 0.6
                and abs(s['z'] - o['z']) < rd / 2 - 0.6
            ]
            rows.append('Roof %s: span %.2f m, %d internal supports (limit 12 m clear)' % (o['id'], sp, len(inner)))
            if sp > 12 and not inner:
                issues.append(
                    {
                        'severity': 'warning',
                        'ids': [o['id']],
                        'text': 'Roof %s: %.2f m clear span with no internal support — over the '
                        '12 m rule of thumb' % (o['id'], sp),
                    }
                )
    return {
        'id': 'a_struct',
        'name': 'Structure',
        'family': FAM,
        'rows': rows,
        'issues': issues,
        'summary': '%d structural members checked, %d flagged' % (len(rows), len(issues)),
    }
