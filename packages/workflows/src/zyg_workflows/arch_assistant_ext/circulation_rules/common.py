# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations


from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []

STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')
SHAFT_KIND = 'elevator_shaft'
DECK_KINDS = ('slab', 'roof_flat')
WALL_KINDS = ('wall', 'curtain_wall')

MAX_FLIGHT = 18  # steps in one flight (Bouwbesluit: a landing every 18)
MAX_TURNED = 36  # a u / l / winder record is TWO flights round a landing
MAX_SPAN = 1.2  # storeys one stair record may climb
LIFT_FROM = 3  # storeys at which a building needs a lift at all
START_TOL = 0.3  # m of slop when a stair start is matched to a storey
DECK_BAND = 0.5  # m above the deck a record still "stands on" it
GUARD_H = 2.0  # m of wall that makes a head house a house
HEAD_MARGIN = 0.8  # m round the stair's top footprint the head house may use
LANDING_TOL = 0.3  # m from a landing edge a guard still guards it
LANDING_DROP = 0.6  # m of drop under a landing before it needs guarding
MAX_FINDINGS = 8

WORD = {
    'stair_straight': 'straight stair',
    'stair_u': 'u stair',
    'stair_l': 'l stair',
    'stair_winder': 'winder stair',
    'stair_spiral': 'spiral stair',
}

# What may stand on a roof deck without making it a place people go. Everything
# else — a pool, a lounger, a planter, a parasol, a table, a room's wall — means
# the deck is a storey and needs a stair like any other.
ROOF_PLANT = frozenset({'hvac_unit', 'water_tank', 'antenna', 'solar_panel', 'chimney'})
NOT_OCCUPANTS = frozenset(DECK_KINDS) | {'door', 'window', 'elevator_shaft', 'elevator_car'}


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _env_mod():
    return A.EXT_MODULES.get('envelope_rules')


def _geom():
    return A.EXT_MODULES.get('analyse_geometry')


def _is_guard(o) -> bool:
    """A wall, railing, balustrade, parapet or balcony — analyse_geometry owns
    the vocabulary (is_guard_kind, L262-267); fall back to the wall kinds when
    that family is not loaded."""
    g = _geom()
    fn = getattr(g, 'is_guard_kind', None) if g is not None else None
    if callable(fn):
        try:
            return bool(fn(o))
        except Exception as _exc:  # noqa: BLE001 — never block a check
            _zyg_log.debug('is_guard_kind failed, falling back to the wall kinds: %s', _exc)
    return str(o.get('kind') or '') in WALL_KINDS + ('railing', 'balustrade', 'parapet', 'balcony')


def _ranges(nums) -> str:
    """[5, 6, 7, 11] -> '5..7, 11' — the storeys, said the way a person says them."""
    ns = sorted({int(n) for n in nums})
    out, i = [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[i]) if i == j else f'{ns[i]}..{ns[j]}')
        i = j + 1
    return ', '.join(out)


def _steps(o) -> float:
    p = o.get('p') or {}
    n = _num(p.get('steps'), 0.0)
    if n <= 0:
        n = _num(p.get('steps_a'), 0.0) + _num(p.get('steps_b'), 0.0)
    return n


def stair_height(o) -> float:
    """The height one stair record climbs: steps x rise, the same product the
    tab and Blender draw. A record with no rise climbs nothing."""
    return _steps(o) * _num((o.get('p') or {}).get('rise'), 0.0)


def stair_reach(o, base: float, H: float) -> range:
    """The storeys a stair record connects, counted from `base`: the one it
    starts on up to the one its top tread lands on. A per-storey record answers
    two consecutive storeys; job 71ac02b0's 285-step record answers 0..19."""
    y = _num(o.get('y'), 0.0)
    lo = int(round((y - base) / H)) if H else 0
    hi = int(round((y + stair_height(o) - base) / H)) if H else lo
    return range(min(lo, hi), max(lo, hi) + 1)


def lift_reach(o, base: float, H: float) -> list:
    """The storeys a shaft opens onto: its own door list, or — for a legacy
    shaft drawn before doors existed — every storey its height crosses."""
    doors = (o.get('p') or {}).get('doors')
    if isinstance(doors, (list, tuple)) and doors:
        return sorted({int(_num(s, 0)) for s in doors})
    y = _num(o.get('y'), 0.0)
    h = _p(o, 'h', 0.0)
    lo = int(round((y - base) / H)) if H else 0
    hi = int(round((y + h - base) / H)) if H else lo
    return list(range(min(lo, hi), max(lo, hi) + 1))


def _in_env(E, env, o) -> bool:
    return bool(E.inside(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)))


def _group_records(d: Drawing, E, env: dict, kinds) -> list:
    return [o for o in d.objs if o.get('kind') in kinds and not o.get('hidden') and _in_env(E, env, o)]


def _floors(d: Drawing, env: dict, H: float) -> dict:
    """{storey: kind} for the group's own slabs and flat roofs, keyed off the
    group's base so a levelled building counts the same as one at y = 0."""
    base = _num(env.get('y0'), 0.0)
    out: dict = {}
    for o in d.objs:
        if o.get('grp') != env['group'] or o.get('hidden') or o.get('kind') not in DECK_KINDS:
            continue
        s = int(round((_num(o.get('y'), 0.0) - base) / H)) if H else 0
        out.setdefault(s, o['kind'])
    return out


def deck_occupants(d: Drawing, E, env: dict) -> list:
    """Everything standing ON the roof deck that is not roof plant. The head
    house a stair builds is excluded — it is the arrival, not a reason to
    arrive — and so are the deck records themselves."""
    top = env.get('top_deck')
    if top is None:
        return []
    head = f'{env["group"]} head house'
    out = []
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden') or k in ROOF_PLANT or k in NOT_OCCUPANTS:
            continue
        if str(o.get('grp') or '') == head:
            continue
        y = _num(o.get('y'), 0.0)
        if not (top - 0.1 <= y <= top + DECK_BAND):
            continue
        if not _in_env(E, env, o):
            continue
        out.append(o)
    return out


def _cap(out: list) -> list:
    if len(out) <= MAX_FINDINGS:
        return out
    rest = len(out) - MAX_FINDINGS
    return out[:MAX_FINDINGS] + [
        {
            'sev': 'info',
            'code': 'circ_more',
            'text': f'... and {rest} more circulation finding{"s" if rest > 1 else ""}',
        }
    ]
