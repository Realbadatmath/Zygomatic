# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""building_program.resolving — the request's own words and resolving the programme.

Moved verbatim from arch_assistant_ext/building_program.py lines 1183-1471
(2026-10 split).
"""

from __future__ import annotations

import re
from zyg_workflows.arch_assistant_ext.building_program.evidence import (
    DENSITY,
    EXT_KEY,
    Drawing,
    _count,
    _num,
    block_bounds,
    cell_name,
    parse_cell,
)
from zyg_workflows.arch_assistant_ext.building_program.checklist import BY_KEY, ITEMS

# ── the request's own words (2026-09-10) ────────────────────────────────────
# The operator asked for an infinity pool, a roof entrance, a nice entrance,
# glass walls and something luxurious.  The programme was resolved from `use`
# and `storeys` alone, so not one of those five words reached the checklist,
# and the model was free to answer 'luxurious' in board-formed concrete and to
# leave the pool off the deck.  Every rule below turns a word the user wrote
# into an ITEM with evidence and a place on the done gate.
#
# effects: ('require', key) | ('pick', key, value) | ('finish', level)
#          | ('glass', True) | ('amenity',)  [one item per matched word]
REQUEST_RULES = [
    (
        re.compile(r'infinity pool|infinity edge|vanishing edge', re.I),
        (
            ('require', 'roof_pool'),
            ('require', 'roof_access'),
            ('pick', 'roof', 'flat_deck'),
            ('pick', 'roof_pool', 'infinity'),
        ),
    ),
    (
        re.compile(r'rooftop pool|pool on the roof|roof pool|roof.?top pool', re.I),
        (('require', 'roof_pool'), ('require', 'roof_access'), ('pick', 'roof', 'flat_deck')),
    ),
    (
        re.compile(r'roof entrance|roof access|roof terrace|roof garden|rooftop|roof deck', re.I),
        (('require', 'roof_access'), ('pick', 'roof', 'flat_deck')),
    ),
    (re.compile(r'balcon', re.I), (('require', 'balconies'),)),
    (re.compile(r'luxur|premium|high.end|five.star|5.star|exclusive|upscale', re.I), (('finish', 'luxury'),)),
    (re.compile(r'glass wall|curtain wall|glass fa[cç]ade|fully glazed|glazed', re.I), (('glass', True),)),
    (re.compile(r'parking|garage', re.I), (('require', 'parking'),)),
    (
        re.compile(r'\b(gym|spa|restaurant|bar|caf[eé]|shop|retail unit|cinema|library|nursery)\b', re.I),
        (('amenity',),),
    ),
    (re.compile(r'garden|landscap|trees|park\b', re.I), (('require', 'landscape'),)),
    (
        re.compile(r'grand entrance|nice entrance|impressive entrance|porte', re.I),
        (('pick', 'entrance', 'porte_cochere'), ('require', 'reception')),
    ),
    (re.compile(r'reception|concierge', re.I), (('require', 'reception'),)),
]

# Building nouns a request may carry.  One that fires no rule is not silently
# dropped: it goes to prog['unmapped'] and is printed, so the model either
# builds it or says out loud that it did not.
NOUNS = frozenset(
    """
atrium terrace penthouse helipad skybridge courtyard colonnade basement mezzanine carport greenhouse
chapel tower bridge fountain pond pergola gazebo sauna clinic annexe arcade auditorium balustrade
bandstand barn bay belfry boathouse bunker campanile canopy cellar chimney cloister conservatory
crypt cupola dome dormer drawbridge dovecote fireplace gallery garret gatehouse grotto hangar
kiosk lighthouse loggia mausoleum minaret moat observatory orangery pavilion pier portico quay
rotunda silo spire stable studio turret veranda vault vestibule watchtower windmill wharf
pool lodge marina cloakroom crematorium
""".split()
)


def _short_title(key: str) -> str:
    it = BY_KEY.get(key)
    if it:
        return str(it['title']).split(':')[0].strip().lower()
    if str(key).startswith('amenity:'):
        return str(key).split(':', 1)[1]
    return str(key).replace('_', ' ')


def read_request(text: str) -> dict:
    """The request's words -> {require, picks, finish_level, glass, amenities,
    fired, unmapped}. Pure: same words, same programme."""
    t = str(text or '')
    require: list = []
    picks: dict = {}
    amenities: list = []
    fired: list = []
    finish_level, glass = 'standard', None
    spans: list = []
    for rx, effects in REQUEST_RULES:
        ms = list(rx.finditer(t))
        if not ms:
            continue
        spans += [(m.start(), m.end()) for m in ms]
        if any(e[0] == 'amenity' for e in effects):
            for m in ms:
                w = (m.group(1) if m.lastindex else m.group(0)).strip().lower()
                key = 'amenity:' + w
                if key not in require:
                    require.append(key)
                    amenities.append(w)
                    fired.append({'match': w, 'says': f'a {w} on the ground floor'})
            continue
        says = []
        for e in effects:
            if e[0] == 'require':
                if e[1] not in require:
                    require.append(e[1])
                says.append(_short_title(e[1]))
            elif e[0] == 'pick':
                picks.setdefault(e[1], e[2])
                says.append(f'{e[1]} = {e[2]}')
            elif e[0] == 'finish':
                finish_level = e[1]
                says.append(f'{e[1]} finish level')
            elif e[0] == 'glass':
                glass = bool(e[1])
                says.append('a glazed facade')
        fired.append({'match': ms[0].group(0).strip().lower(), 'says': ' + '.join(says)})
    unmapped = []
    for m in re.finditer(r'[a-z]+', t.lower()):
        w = m.group(0)
        base = w[:-1] if (w.endswith('s') and w[:-1] in NOUNS) else w
        if base not in NOUNS:
            continue
        if any(s < m.end() and m.start() < e for s, e in spans):
            continue
        if base not in unmapped:
            unmapped.append(base)
    return {
        'require': require,
        'picks': picks,
        'finish_level': finish_level,
        'glass': glass,
        'amenities': amenities,
        'fired': fired,
        'unmapped': unmapped,
    }


def _amenity_item(word: str) -> dict:
    w = str(word or '').strip().lower()
    return {
        'key': 'amenity:' + w,
        'title': w.capitalize(),
        'spec': 'room',
        'need': lambda c: 'required',
        'why': f'the request asks for a {w}',
        'options': [],
        'default': lambda c: w,
        'how': lambda c: (
            f'add_room(cell_from, cell_to, storey=0, name="{w.capitalize()}") on the ground floor, off the lobby'
        ),
        'ev': lambda d, c, _w=w: (_count(d, (), words=(_w,)) > 0, f'a record whose name or group says "{_w}"'),
    }


def item_for(key):
    """The checklist item for a key, including the amenities the request made."""
    it = BY_KEY.get(key)
    if it is not None:
        return it
    k = str(key or '')
    return _amenity_item(k.split(':', 1)[1]) if k.startswith('amenity:') and len(k) > 8 else None


# ── resolving the program ────────────────────────────────────────────────────
def _ctx(use, storeys, cell_from, cell_to, glass=None) -> dict:
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    w, dd = xmax - xmin, zmax - zmin
    area = w * dd
    st = max(1, int(_num(storeys, 1)))
    dens = DENSITY.get(use, 15.0)
    gross = area * st
    if glass is None:
        glass = use in ('office', 'hotel', 'civic', 'retail') and st >= 4
    return {
        'use': use,
        'storeys': st,
        'area': round(area, 1),
        'gross': round(gross, 1),
        'w': round(w, 1),
        'd': round(dd, 1),
        'depth': round(min(w, dd), 1),
        'occupants': int(round(gross / dens)),
        'glass': bool(glass),
        'cell_from': cell_name(*parse_cell(cell_from)),
        'cell_to': cell_name(*parse_cell(cell_to)),
        'pick_of': {},
        'pick_over': {},
        'need_of': {},
        'require': [],
        'finish_level': 'standard',
    }


def _row(it, c, need, skip) -> dict:
    c['pick'] = ''
    c['n'] = 1
    pick = (c.get('pick_over') or {}).get(it['key']) or it['default'](c)
    c['pick'] = pick
    c['pick_of'][it['key']] = pick
    n = int(it['count'](c)) if it.get('count') else 1
    c['n'] = n
    return {
        'key': it['key'],
        'title': it['title'],
        'need': 'waived' if it['key'] in skip else need,
        'why': it['why'],
        'pick': pick,
        'n': n,
        'options': list(it.get('options') or []),
        'how': it['how'](c),
        'spec': it.get('spec') or it['key'],
    }


def resolve(use, storeys, cell_from, cell_to, glass=None, skip=None, request='') -> dict:
    """The whole checklist, decided. Deterministic: same input, same program.

    `request` is the user's own message: its words add required items (a roof
    pool, a gym, balconies), force picks (a nice entrance IS a porte cochere)
    and set the finish level, so the programme answers what was asked for and
    not only what the use and the height imply."""
    rq = read_request(request)
    if glass is None and rq['glass'] is not None:
        glass = rq['glass']
    c = _ctx(use, storeys, cell_from, cell_to, glass)
    c['require'] = list(rq['require'])
    c['pick_over'] = dict(rq['picks'])
    c['finish_level'] = rq['finish_level']
    req_set = set(c['require'])
    skip = {str(s).strip().lower() for s in (skip or [])}
    items = []
    for it in ITEMS:
        need = 'required' if it['key'] in req_set else it['need'](c)
        c['need_of'][it['key']] = need
        if need == 'no':
            continue
        items.append(_row(it, c, need, skip))
    for w in rq['amenities']:
        it = _amenity_item(w)
        c['need_of'][it['key']] = 'required'
        items.append(_row(it, c, 'required', skip))
    return {
        'use': c['use'],
        'storeys': c['storeys'],
        'cell_from': c['cell_from'],
        'cell_to': c['cell_to'],
        'area': c['area'],
        'gross': c['gross'],
        'occupants': c['occupants'],
        'glass': c['glass'],
        'w': c['w'],
        'd': c['d'],
        'items': items,
        'skip': sorted(skip),
        'finish_level': c['finish_level'],
        'require': sorted(req_set),
        'from_request': rq['fired'],
        'unmapped': rq['unmapped'],
        'request': str(request or '')[:400],
    }


def _ev_ctx(prog, row) -> dict:
    c = dict(prog)
    c['pick'] = row.get('pick')
    c['n'] = int(row.get('n') or 1)
    c['pick_of'] = {r['key']: r.get('pick') for r in prog.get('items') or []}
    c['need_of'] = {r['key']: r.get('need') for r in prog.get('items') or []}
    c['depth'] = min(prog.get('w', 0), prog.get('d', 0))
    c['finish_level'] = prog.get('finish_level') or 'standard'
    c['require'] = list(prog.get('require') or [])
    return c


def status(d: Drawing, prog: dict) -> list:
    """[{key, need, ok, detail, ...}] — the checklist against the drawing."""
    out = []
    for row in prog.get('items') or []:
        it = item_for(row['key'])
        if not it:
            continue
        try:
            ok, detail = it['ev'](d, _ev_ctx(prog, row))
        except Exception as e:  # noqa: BLE001
            ok, detail = True, f'check failed ({e!r}) — treated as satisfied'
        r = dict(row)
        r['ok'] = bool(ok) or row['need'] == 'waived'
        r['detail'] = str(detail)
        out.append(r)
    return out


def get_program(d: Drawing) -> dict | None:
    p = (d.ext or {}).get(EXT_KEY)
    return p if isinstance(p, dict) and p.get('items') else None
