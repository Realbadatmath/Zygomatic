# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""edit_ops — the assistant half of Edit ▸ Align, Distribute, History, Purge.

Two things live here.

1. BUTTONS: the four icons `arch_ext/edit_ops.js` wired (e_align, e_dist,
   e_history, e_purge) may be pressed by the model through
   view_scene_ops.press_button(id, args) — the JS registrations all carry
   `assist: 1`, so both sides agree.

2. TOOLS: server-side twins of the two geometric ones, `align_objects` and
   `distribute_objects`. The tab measures the world bounding box of the built
   THREE node; here there is no node, so the same box is computed from the
   record's own parameters — `arch_assistant._p_footprint` for the plan
   rectangle, rotated by `ry` into an axis-aligned box, and the h/t parameter
   for the height. For every kind whose geometry fills its declared footprint
   (slabs, walls, boxes, footings, columns) the two answers agree to well under
   a centimetre; a lathe or a truss can differ by its own tolerance.

Licence: part of the Zygomatic repository. Standard library only.
"""

import math

from zyg_workflows.arch_assistant import Drawing, _num, _p_footprint

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['e_align', 'e_dist', 'e_history', 'e_purge']

PROMPT = (
    'Edit operations (Align / Distribute / History / Purge). press_button("e_align", {"mode":"left","to":"last"}) '
    '— mode left, right, centerx, back, front, centerz, top, bottom or face; to "last", "first" or "selection". '
    '"e_dist" {"axis":"auto"} spreads 3+ objects with equal gaps between EDGES; "e_history" opens the undo list; '
    '"e_purge" reports what nothing refers to any more. For the NUMBERS use align_objects(which, mode, to) and '
    'distribute_objects(which, axis). explain("align") has the detail.'
)


# ── the same box the tab measures, from the parameters ──────────────────────
def _p_height(p: dict) -> float:
    for k in ('h', 'height', 't', 'rise', 'thick'):
        if k in p:
            return abs(_num(p[k], 0.0))
    if 'r' in p:
        return abs(_num(p['r'], 0.0))
    return 0.0


def _box(o: dict) -> dict:
    """Axis-aligned world box of a record, in metres: {x0,x1,y0,y1,z0,z1}."""
    p = o.get('p') or {}
    w, d = _p_footprint(p)
    s = _num(o.get('s'), 1.0) or 1.0
    ry = _num(o.get('ry'), 0.0)
    c, sn = abs(math.cos(ry)), abs(math.sin(ry))
    bw = (w * c + d * sn) * s
    bd = (w * sn + d * c) * s
    bh = _p_height(p) * s
    x, y, z = _num(o.get('x'), 0.0), _num(o.get('y'), 0.0), _num(o.get('z'), 0.0)
    return {'x0': x - bw / 2, 'x1': x + bw / 2, 'y0': y, 'y1': y + bh, 'z0': z - bd / 2, 'z1': z + bd / 2}


_AXIS_OF = {
    'left': 'x',
    'right': 'x',
    'centerx': 'x',
    'back': 'z',
    'front': 'z',
    'centerz': 'z',
    'bottom': 'y',
    'top': 'y',
    'face': '*',
}
_LO = {'x': 'x0', 'y': 'y0', 'z': 'z0'}
_HI = {'x': 'x1', 'y': 'y1', 'z': 'z1'}


def _lo(b, a):
    return b[_LO[a]]


def _hi(b, a):
    return b[_HI[a]]


def _mid(b, a):
    return (b[_LO[a]] + b[_HI[a]]) / 2.0


def _move(o: dict, a: str, dv: float) -> None:
    o[a] = round(_num(o.get(a), 0.0) + dv, 4)


def t_align_objects(d: Drawing, a, which='all', mode='left', to='last'):
    recs = d.select(which)
    if len(recs) < 2:
        return 'refused: align needs at least two objects — ' + str(len(recs)) + ' matched'
    mode = str(mode or 'left').strip().lower()
    if mode not in _AXIS_OF:
        return 'refused: mode must be one of ' + ', '.join(_AXIS_OF)
    to = str(to or 'last').strip().lower()
    if to not in ('last', 'first', 'selection'):
        to = 'last'

    boxes = {o['id']: _box(o) for o in recs}
    ref = None
    if to == 'selection':
        rb = {
            'x0': min(b['x0'] for b in boxes.values()),
            'x1': max(b['x1'] for b in boxes.values()),
            'y0': min(b['y0'] for b in boxes.values()),
            'y1': max(b['y1'] for b in boxes.values()),
            'z0': min(b['z0'] for b in boxes.values()),
            'z1': max(b['z1'] for b in boxes.values()),
        }
    else:
        ref = recs[0] if to == 'first' else recs[-1]
        rb = boxes[ref['id']]

    moved = []
    for o in recs:
        if ref is not None and o['id'] == ref['id']:
            continue
        b, ax = boxes[o['id']], _AXIS_OF[mode]
        if mode == 'face':
            ax = max(('x', 'y', 'z'), key=lambda k: abs(_mid(b, k) - _mid(rb, k)))
            dv = (_hi(rb, ax) - _lo(b, ax)) if _mid(b, ax) >= _mid(rb, ax) else (_lo(rb, ax) - _hi(b, ax))
        elif mode in ('left', 'back', 'bottom'):
            dv = _lo(rb, ax) - _lo(b, ax)
        elif mode in ('right', 'front', 'top'):
            dv = _hi(rb, ax) - _hi(b, ax)
        else:
            dv = _mid(rb, ax) - _mid(b, ax)
        if abs(dv) > 1e-9:
            _move(o, ax, dv)
            moved.append('%s %s%+.3f' % (o['id'], ax, dv))
    if not moved:
        return 'already aligned %s: nothing moved' % mode
    d.selected = [o['id'] for o in recs]
    return ('aligned %d of %d objects %s to the %s: ' % (len(moved), len(recs), mode, to)) + ', '.join(moved)


def t_distribute_objects(d: Drawing, a, which='all', axis='auto'):
    recs = d.select(which)
    if len(recs) < 3:
        return 'refused: distribute needs at least three objects — ' + str(len(recs)) + ' matched'
    boxes = {o['id']: _box(o) for o in recs}
    ax = str(axis or 'auto').strip().lower()
    if ax not in ('x', 'z'):
        cx = [_mid(boxes[o['id']], 'x') for o in recs]
        cz = [_mid(boxes[o['id']], 'z') for o in recs]
        ax = 'z' if (max(cz) - min(cz)) > (max(cx) - min(cx)) else 'x'

    order = sorted(recs, key=lambda o: _mid(boxes[o['id']], ax))
    n = len(order)
    span = _lo(boxes[order[-1]['id']], ax) - _hi(boxes[order[0]['id']], ax)
    bulk = sum(_hi(boxes[o['id']], ax) - _lo(boxes[o['id']], ax) for o in order[1:-1])
    gap = (span - bulk) / (n - 1)

    moved, cursor = [], _hi(boxes[order[0]['id']], ax)
    for o in order[1:-1]:
        b = boxes[o['id']]
        want = cursor + gap
        dv = want - _lo(b, ax)
        if abs(dv) > 1e-9:
            _move(o, ax, dv)
            moved.append('%s %s%+.3f' % (o['id'], ax, dv))
        cursor = want + (_hi(b, ax) - _lo(b, ax))
    d.selected = [o['id'] for o in recs]
    if not moved:
        return 'already evenly spaced along %s (gap %.3f m): nothing moved' % (ax, gap)
    return (
        'distributed %d objects along %s with an equal %.3f m gap between edges%s: '
        % (n, ax, gap, ' (NEGATIVE — they overlap)' if gap < 0 else '')
    ) + ', '.join(moved)


_WHICH = {
    'oneOf': [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}],
    'description': '"all", "new", a kind, a group name, an id, or a list of ids',
}

TOOLS = [
    (
        {
            'name': 'align_objects',
            'description': 'Align objects already in the drawing: mode left/right/centerx moves them along X, '
            'back/front/centerz along Z, top/bottom along Y, and face butts each one against the '
            'nearest face of the reference. The reference is the last object of the set ("last"), '
            'the first ("first"), or the union box of all of them ("selection"). Same arithmetic as '
            "the studio's Align icon.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'mode': {'type': 'string', 'enum': list(_AXIS_OF)},
                    'to': {'type': 'string', 'enum': ['last', 'first', 'selection']},
                },
                'required': ['which', 'mode'],
            },
        },
        t_align_objects,
    ),
    (
        {
            'name': 'distribute_objects',
            'description': 'Spread three or more objects evenly between the two outermost of them: the outer two '
            'stay put and the rest are moved so the GAPS BETWEEN THEIR EDGES are equal — the CAD '
            'convention, not equal centre spacing. axis "x", "z", or "auto" for the direction they '
            'are most spread out in.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'axis': {'type': 'string', 'enum': ['x', 'z', 'auto']}},
                'required': ['which'],
            },
        },
        t_distribute_objects,
    ),
]

EXAMPLES = [
    {
        'ask': 'line the columns up on the left',
        'calls': [{'tool': 'align_objects', 'args': {'which': 'column', 'mode': 'left', 'to': 'first'}}],
    },
    {
        'ask': 'space those five trees out evenly',
        'calls': [{'tool': 'distribute_objects', 'args': {'which': 'tree', 'axis': 'auto'}}],
    },
    {
        'ask': 'align the selection to the bottom of the last one I picked',
        'calls': [{'tool': 'press_button', 'args': {'id': 'e_align', 'args': {'mode': 'bottom', 'to': 'last'}}}],
    },
    {'ask': 'show me the undo history', 'calls': [{'tool': 'press_button', 'args': {'id': 'e_history'}}]},
    {
        'ask': 'undo the last two things',
        'calls': [{'tool': 'press_button', 'args': {'id': 'e_history', 'args': {'back': 2}}}],
    },
    {
        'ask': 'clean out the materials and definitions nothing uses',
        'calls': [{'tool': 'press_button', 'args': {'id': 'e_purge'}}],
    },
]
