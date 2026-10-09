# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_studies — the assistant half of the three sun icons (2026-09-08).

Icons wired in arch_ext/light_studies.js and declared pressable here:

  l_study     Light ▸ Sun study    — sweep the day, one captioned contact-sheet PNG
  l_solar     Light ▸ Sun hours    — the sun-hours MAP painted onto the model (a switch)
  a_sunhours  Analyse ▸ Sun hours  — the same numbers as a table + a CSV

The model cannot see the canvas, so it also gets a SERVER-SIDE TWIN of the
analysis: sun_hours() computes direct-sun hours here, in Python, from the
records' numbers alone, and returns a text table it can read.

THE TWIN IS COARSER THAN THE ICON, deliberately, and says so in its own
description. The tab casts a ray per TRIANGLE against the real meshes; this
samples five points per record (the top-face centre and the four side-face
centres of its axis-aligned bounding box) and treats every OTHER record as one
axis-aligned BOX. Record rotation (ry) is ignored, and so is any concavity: a
courtyard reads as a solid block. The ORDER is right — a shaded surface scores
below an open one — but the figures are an estimate, not a survey.

THE SUN. If a light_sun family is installed beside this file its real solar
model (NOAA/Meeus) is used, read through the DRAWING's own site
(ext.light_sun = {date, lat, lon, tz, north}), so both halves of the studio
share one sun; it is imported by file path inside a try/except and nothing here
depends on it. Without it: a plain 06–20 h arc, elevation = 60·sin(pi·(h-6)/14) degrees,
azimuth swinging from due east through due south to due west — the same shape
the tab's built-in arc has (studio frame: +X east, +Y up, +Z south).

No kinds, no drawing: every tool here is read-only.

Standard library only (math, os, importlib) — no new packages.
"""

from __future__ import annotations

import math
import os

from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['l_study', 'l_solar', 'a_sunhours']

PROMPT = (
    'Sun studies: press_button("l_study", {"from":6,"to":20,"step":2,"res":640,"date":"21 Jun"}) sweeps the day and '
    'writes every hour into ONE captioned contact-sheet PNG (downloaded and shown). '
    'press_button("l_solar", {"from":6,"to":20,"step":1,"date":""}) is a SWITCH: it paints the sun-hours map onto the '
    'model (blue = no direct sun, red = the most hours of the sweep), hides the plain model while it is on and shows a '
    'legend and a per-object table; press it again to put the model back. '
    'press_button("a_sunhours", {"which":"all","from":6,"to":20,"step":1}) is the read-only report — a table of average, '
    'minimum and maximum direct-sun hours per record plus a CSV — and paints nothing. '
    'To QUOTE numbers use the tool sun_hours(which, date, from_hour, to_hour) instead: it computes them here and gives '
    'you the table as text (coarser than the icon — five bounding-box points per record, other records as boxes).'
)

EXAMPLES = [
    {'ask': 'how much sun does the garden get?', 'calls': [{'tool': 'sun_hours', 'args': {'which': 'all'}}]},
    {
        'ask': 'paint the sun-hours map on the model',
        'calls': [{'tool': 'press_button', 'args': {'id': 'l_solar', 'args': {'from': 6, 'to': 20, 'step': 1}}}],
    },
    {
        'ask': 'do a sun study from 8 to 16 every two hours',
        'calls': [{'tool': 'press_button', 'args': {'id': 'l_study', 'args': {'from': 8, 'to': 16, 'step': 2}}}],
    },
    {
        'ask': 'how many hours of sun does the roof get on midsummer day?',
        'calls': [{'tool': 'sun_hours', 'args': {'which': 'slab', 'date': '2026-06-21'}}],
    },
    {
        'ask': 'sun hours on the new blocks, office hours only',
        'calls': [{'tool': 'sun_hours', 'args': {'which': 'new', 'from_hour': 9, 'to_hour': 17}}],
    },
]

HORIZON = 0.08  # a normalised sun height below this is under the horizon
EPS = 0.02  # how far a sample point stands off its own surface, in metres


# ── the sun ─────────────────────────────────────────────────────────────────
_SUN_MOD: list = []  # memo: [] not tried yet, [None] tried and absent, [mod] loaded


def _light_sun():
    """The light_sun family's solar model if that family is installed, else None.

    Loaded at most once per process: sun_dir() asks for it on every hour of every
    record, and exec_module()ing a 500-line module that often turned a report into
    seconds of import."""
    if _SUN_MOD:
        return _SUN_MOD[0]
    _SUN_MOD.append(_load_light_sun())
    return _SUN_MOD[0]


def _load_light_sun():
    try:
        import importlib.util

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'light_sun.py')
        if not os.path.exists(path):
            return None
        spec = importlib.util.spec_from_file_location('arch_assistant_ext.light_sun', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ('solar_position', 'direction', 'site', 'DEFAULTS'):
            if getattr(mod, name, None) is None:
                return None
        return mod
    except Exception:  # noqa: BLE001
        return None


def sun_dir(hour: float, date: str = '', d: Drawing = None) -> tuple:
    """Unit vector toward the sun at `hour` in the studio frame (+X east, +Y up,
    +Z south). Below the horizon the y component comes back <= 0.

    With the light_sun family installed this is ITS solar position, taken at the
    drawing's own site, so the table agrees with the sun the viewport draws."""
    mod = _light_sun()
    if mod is not None:
        try:
            st = mod.site(d) if d is not None else dict(mod.DEFAULTS)
            s = mod.solar_position(str(date or '') or st['date'], float(hour), st['lat'], st['lon'], st['tz'])
            x, y, z = mod.direction(s['azimuth'], s['elevation'], st['north'])
            n = math.sqrt(x * x + y * y + z * z) or 1.0
            return (x / n, y / n, z / n)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('light_sun solar position failed, using the crude arc: %s', _exc)
    t = (hour - 6.0) / 14.0  # 0 at 06:00, 1 at 20:00
    if t <= 0.0 or t >= 1.0:
        return (0.0, -1.0, 0.0)
    el = math.radians(60.0 * math.sin(math.pi * t))
    az = math.pi * t  # 0 = east, pi/2 = south, pi = west
    return (math.cos(el) * math.cos(az), math.sin(el), math.cos(el) * math.sin(az))


# ── a record as one box ─────────────────────────────────────────────────────
def _size(o: dict) -> tuple:
    """(width along x, height, depth along z) in metres, from the parameters only."""
    p = o.get('p') or {}
    k = str(o.get('kind') or '')
    if k in ('wall', 'partition'):
        return _num(p.get('len'), 4.0), _num(p.get('h'), 2.7), _num(p.get('t'), 0.24)
    if k in ('slab', 'slab_poly', 'pad', 'road', 'path', 'deck'):
        return _num(p.get('w'), 4.0), _num(p.get('t'), 0.2), _num(p.get('d'), 4.0)
    r = _num(p.get('r'), 0.0)
    w = _num(p.get('w'), 0.0) or (2.0 * r) or _num(p.get('len'), 0.0) or 1.0
    d = _num(p.get('d'), 0.0) or (2.0 * r) or _num(p.get('t'), 0.0) or w
    h = _num(p.get('h'), 0.0) or _num(p.get('t'), 0.0) or 1.0
    return w, h, d


def _aabb(o: dict) -> tuple:
    """(x0, y0, z0, x1, y1, z1) — the axis-aligned box the record's numbers imply.
    Rotation (ry) is ignored: a wall turned 45 degrees reads as its unrotated box."""
    w, h, d = _size(o)
    s = abs(_num(o.get('s'), 1.0)) or 1.0
    w, h, d = abs(w) * s, abs(h) * s, abs(d) * s
    x, y, z = _num(o.get('x'), 0.0), _num(o.get('y'), 0.0), _num(o.get('z'), 0.0)
    return (x - w / 2.0, y, z - d / 2.0, x + w / 2.0, y + h, z + d / 2.0)


def _samples(b: tuple) -> list:
    """The five points the twin measures: the top-face centre and the four
    side-face centres, each standing EPS off its own face with its outward normal."""
    x0, y0, z0, x1, y1, z1 = b
    cx, cy, cz = (x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0
    return [
        ((cx, y1 + EPS, cz), (0.0, 1.0, 0.0)),
        ((x1 + EPS, cy, cz), (1.0, 0.0, 0.0)),
        ((x0 - EPS, cy, cz), (-1.0, 0.0, 0.0)),
        ((cx, cy, z1 + EPS), (0.0, 0.0, 1.0)),
        ((cx, cy, z0 - EPS), (0.0, 0.0, -1.0)),
    ]


def _ray_box(org: tuple, d: tuple, b: tuple) -> bool:
    """Does the ray org + t*d (t > 0) enter the box? The slab test."""
    tmin, tmax = 0.0, 1e12
    for i in range(3):
        oi, di, lo, hi = org[i], d[i], b[i], b[i + 3]
        if abs(di) < 1e-9:
            if oi < lo or oi > hi:
                return False
            continue
        t1, t2 = (lo - oi) / di, (hi - oi) / di
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return False
    return tmax > 1e-6


def _hours(hour_from: float, hour_to: float) -> list:
    a, b = min(hour_from, hour_to), max(hour_from, hour_to)
    a, b = max(0.0, a), min(24.0, b)
    out, h = [], math.floor(a)
    if h < a:
        h += 1
    while h <= b + 1e-9 and len(out) < 25:
        out.append(float(h))
        h += 1
    return out or [12.0]


def direct_sun_hours(objs: list, subject: list, hours: list, date: str = '', d: Drawing = None) -> list:
    """[{id, name, kind, avg, min, max, n}] — the shared arithmetic of the twin.
    `objs` are every occluder (hidden records excluded by the caller)."""
    boxes = [(o['id'], _aabb(o)) for o in objs]
    dirs = [(h, sun_dir(h, date, d)) for h in hours]
    dirs = [(h, v) for h, v in dirs if v[1] > HORIZON]
    out = []
    for o in subject:
        pts = _samples(_aabb(o))
        vals = []
        for org, nrm in pts:
            lit = 0
            for _h, v in dirs:
                if nrm[0] * v[0] + nrm[1] * v[1] + nrm[2] * v[2] <= 1e-4:
                    continue  # the face is turned away
                blocked = False
                for oid, b in boxes:
                    if oid == o['id']:
                        continue  # a record never shades itself
                    if _ray_box(org, v, b):
                        blocked = True
                        break
                if not blocked:
                    lit += 1
            vals.append(lit)
        n = len(vals) or 1
        out.append(
            {
                'id': o['id'],
                'name': o.get('name') or o.get('kind'),
                'kind': o.get('kind'),
                'avg': round(sum(vals) / float(n), 2),
                'min': min(vals) if vals else 0,
                'max': max(vals) if vals else 0,
                'n': len(vals),
                'daylight': len(dirs),
            }
        )
    return out


# ── the tool ────────────────────────────────────────────────────────────────
def t_sun_hours(d: Drawing, a: dict, which='all', date='', from_hour=6, to_hour=20) -> str:
    hours = _hours(_num(from_hour, 6.0), _num(to_hour, 20.0))
    live = [o for o in d.objs if not o.get('hidden')]
    if not live:
        return 'refused: the drawing is empty, so there is nothing for the sun to fall on'
    subject = [o for o in d.select(which) if not o.get('hidden')]
    if not subject:
        return 'refused: nothing matched which=%r' % (which,)
    if len(subject) > 400:
        subject = subject[:400]
    rows = direct_sun_hours(live, subject, hours, str(date or ''), d)
    day = rows[0]['daylight'] if rows else 0
    mod = _light_sun()
    when = str(date or '')
    if not when:
        try:
            when = mod.site(d)['date'] if mod is not None else 'the built-in day'
        except Exception:  # noqa: BLE001
            when = 'the built-in day'
    head = 'direct sun hours, %s (%d of the %d hours %g-%g are above the horizon)%s\n' % (
        when,
        day,
        len(hours),
        hours[0],
        hours[-1],
        '' if len(subject) == len(d.select(which)) else ' [first 400 records]',
    )
    head += 'record  kind        name                      avg   min  max\n'
    for r in rows:
        head += '%-7s %-11s %-25s %5.2f %4d %4d\n' % (
            str(r['id'])[:7],
            str(r['kind'])[:11],
            str(r['name'])[:25],
            r['avg'],
            r['min'],
            r['max'],
        )
    head += (
        'estimate: five bounding-box points per record (top + four sides), every other record as one box, '
        'rotation ignored. The tab icon a_sunhours measures per triangle against the real meshes.'
    )
    return head


TOOLS = [
    (
        {
            'name': 'sun_hours',
            'description': (
                "Average direct-sun HOURS per record across a day, computed here from the records' "
                'numbers. COARSE by design: five points per record (the top-face centre and the four '
                'side-face centres of its bounding box), every other record treated as one axis-aligned '
                'box, record rotation ignored, no concavity — the ORDER is right (an overshadowed surface '
                'scores below an open one) but the figures are an estimate, not a survey. For the exact '
                'per-triangle version press the icon a_sunhours instead.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {'type': 'string', 'description': '"all", "new", a kind, a group name, or a list of ids'},
                    'date': {
                        'type': 'string',
                        'description': "the day as YYYY-MM-DD; blank uses the drawing's own site date",
                    },
                    'from_hour': {'type': 'number', 'description': 'first hour of the sweep (default 6)'},
                    'to_hour': {'type': 'number', 'description': 'last hour of the sweep (default 20)'},
                },
                'required': [],
            },
        },
        t_sun_hours,
    )
]
