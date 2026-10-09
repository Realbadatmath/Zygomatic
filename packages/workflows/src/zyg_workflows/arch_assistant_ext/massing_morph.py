# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""massing_morph — the assistant's study-model tools.

Massing is the stage before there are any walls: one record IS the whole
volume (h = storeys * 2.7), so a 30-storey tower is ONE object instead of 120
walls. That is the point of this family — the model can put up, look at and
throw away a dozen shapes without ever coming near the object ceiling.

Tools: draw_massing (a block of cells -> one mass volume, optionally with a
slab per storey so floor-area reports still work), morph (turn an existing
mass or box into another shape, or just change its height/footprint) and
stack_storeys (copy a selection upward, the plain way to make a one-storey
plan into a tower).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_name,
    block_bounds,
    MATERIALS,
    _num,
    MAX_OBJECTS,
    storey_of,
)

KINDS = {
    'mass_taper': {'w': 10, 'd': 10, 'h': 27, 'w_top': 6, 'd_top': 6},
    'mass_twist': {'w': 10, 'd': 10, 'h': 27, 'twist': 45, 'seg': 10},
    'mass_setback': {'w': 12, 'd': 12, 'h': 27, 'steps': 3, 'step_in': 2},
    'mass_loft': {'w': 10, 'd': 10, 'h': 27, 'seg': 24},
    'mass_ellipse': {'rx': 6, 'rz': 4, 'h': 27, 'seg': 48},
    'mass_arc': {'r': 20, 'a0': 0, 'a1': 90, 'w': 12, 'h': 27, 'seg': 32},
    'mass_chamfer': {'w': 10, 'd': 10, 'h': 27, 'c': 1.0},
    'mass_round': {'w': 10, 'd': 10, 'h': 27, 'r': 2},
    'mass_shear': {'w': 10, 'd': 10, 'h': 27, 'shear_x': 3, 'shear_z': 0},
}
OPENINGS: list = []

STYLES = ('box', 'taper', 'twist', 'setback', 'loft', 'ellipse', 'chamfer', 'round', 'shear')
STYLE_KIND = {
    'box': 'box',
    'taper': 'mass_taper',
    'twist': 'mass_twist',
    'setback': 'mass_setback',
    'loft': 'mass_loft',
    'ellipse': 'mass_ellipse',
    'chamfer': 'mass_chamfer',
    'round': 'mass_round',
    'shear': 'mass_shear',
}
MORPHABLE = ('box',) + tuple(KINDS)
OPS = ('taper', 'twist', 'setback', 'chamfer', 'round', 'shear', 'scale', 'height')

PROMPT = (
    'Massing (study models — one record IS a whole volume, no walls): draw_massing(cell_from, cell_to, storeys, '
    'style, amount) fills a block of cells with ONE solid; style box, taper, twist, setback, loft, ellipse, '
    "chamfer, round or shear, amount being that style's number (taper top scale 0.6, twist degrees, setback "
    'steps, chamfer/round metres, shear metres the top slides). Use it for towers, blocks and "show me three '
    'shapes": far cheaper than draw_box, and slabs=true if floor areas must be countable. morph(which, op, '
    'amount) reshapes what is already drawn — op taper/twist/setback/chamfer/round/shear converts, op height '
    'sets metres, op scale multiplies the footprint. stack_storeys(which, count) copies the selection up one '
    'storey per copy. Openings cannot be cut into a mass: for real walls and windows use draw_box.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _wd(o):
    """(w, d) footprint of a morphable record, or None if it has no rectangular one."""
    p = o['p']
    if o['kind'] == 'mass_ellipse':
        return _num(p.get('rx'), 6) * 2, _num(p.get('rz'), 4) * 2
    if o['kind'] == 'mass_arc':
        return None
    return _num(p.get('w'), 10), _num(p.get('d'), 10)


def _shape_p(kind, w, d, h, amount):
    """The parameters for `kind` sized to a w x d x h envelope."""
    if kind == 'box':
        return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4)}
    if kind == 'mass_taper':
        f = _num(amount, 0.6)
        f = min(3.0, max(0.02, f))
        return {
            'w': round(w, 4),
            'd': round(d, 4),
            'h': round(h, 4),
            'w_top': round(w * f, 4),
            'd_top': round(d * f, 4),
        }
    if kind == 'mass_twist':
        return {
            'w': round(w, 4),
            'd': round(d, 4),
            'h': round(h, 4),
            'twist': round(_num(amount, 45.0), 2),
            'seg': max(2, min(60, int(round(h / 2.7)))),
        }
    if kind == 'mass_setback':
        steps = max(2, min(20, int(_num(amount, 3))))
        step_in = min(2.0, max(0.3, min(w, d) / (2.0 * steps + 2)))
        return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4), 'steps': steps, 'step_in': round(step_in, 3)}
    if kind == 'mass_loft':
        return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4), 'seg': 24}
    if kind == 'mass_ellipse':
        return {'rx': round(w / 2, 4), 'rz': round(d / 2, 4), 'h': round(h, 4), 'seg': 48}
    if kind == 'mass_chamfer':
        c = min(_num(amount, min(w, d) / 4), min(w, d) / 2 - 0.05)
        return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4), 'c': round(max(0.05, c), 3)}
    if kind == 'mass_round':
        r = min(_num(amount, min(w, d) / 4), min(w, d) / 2 - 0.05)
        return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4), 'r': round(max(0.05, r), 3)}
    if kind == 'mass_shear':
        return {
            'w': round(w, 4),
            'd': round(d, 4),
            'h': round(h, 4),
            'shear_x': round(_num(amount, 3.0), 3),
            'shear_z': 0.0,
        }
    return {'w': round(w, 4), 'd': round(d, 4), 'h': round(h, 4)}


def t_draw_massing(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storeys=10,
    style='box',
    amount=None,
    material='mat_concrete',
    slabs=False,
    name='',
):
    style = str(style or 'box').strip().lower()
    if style not in STYLES:
        return 'refused: style must be one of ' + ', '.join(STYLES)
    n = int(_num(storeys, 10))
    if n < 1 or n > 400:
        return 'refused: storeys must be between 1 and 400'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    H = d.storey_h
    h = n * H
    need = 1 + (n if slabs else 0)
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    kind = STYLE_KIND[style]
    ca, cb = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    grp = name or f'massing {ca}-{cb}'
    mat = _mat(material)
    o = d.new(kind, _shape_p(kind, W, D, h, amount), cx, cz, 0.0, 0.0, mat, name=name or f'{style} mass', grp=grp)
    for k in range(n if slabs else 0):
        d.new(
            'slab',
            {'w': round(W, 4), 'd': round(D, 4), 't': 0.22},
            cx,
            cz,
            k * H,
            0.0,
            mat,
            name=f'floor st{k}',
            grp=grp,
        )
    return (
        f'drew {o["id"]} {kind} "{grp}": {W:g} x {D:g} m footprint (cells {ca}..{cb}), '
        f'{n} storeys = {h:g} m tall, style {style}' + (f', {n} floor slabs' if slabs else '') + f', {mat}'
    )


def t_morph(d: Drawing, a, which='new', op='taper', amount=None):
    op = str(op or 'taper').strip().lower()
    if op not in OPS:
        return 'refused: op must be one of ' + ', '.join(OPS)
    recs = d.select(which)
    if not recs:
        return 'refused: nothing matches — pass "new", a group name or object ids'
    good = [o for o in recs if o['kind'] in MORPHABLE]
    if not good:
        bad = sorted({o['kind'] for o in recs})
        return (
            'refused: morph only reshapes massing volumes and boxes, not '
            + ', '.join(bad)
            + ' — use set_height or scale for those'
        )
    done, skipped = [], []
    for o in good:
        wd = _wd(o)
        h = _num(o['p'].get('h'), 27)
        if op == 'height':
            hh = _num(amount, h)
            if hh <= 0:
                return 'refused: op height needs a positive amount in metres'
            o['p']['h'] = round(hh, 4)
            done.append(o['id'])
            continue
        if op == 'scale':
            f = _num(amount, 1.0)
            if f <= 0:
                return 'refused: op scale needs a positive factor'
            for key in ('w', 'd', 'w_top', 'd_top', 'rx', 'rz', 'r'):
                if key in o['p']:
                    o['p'][key] = round(_num(o['p'][key], 0) * f, 4)
            done.append(o['id'])
            continue
        if wd is None:
            skipped.append(o['id'])
            continue
        kind = STYLE_KIND[op]
        o['kind'] = kind
        o['p'] = _shape_p(kind, wd[0], wd[1], h, amount)
        o['name'] = f'{op} mass'
        done.append(o['id'])
    if not done:
        return f'refused: none of those records can be morphed with op {op}'
    tail = f' ({len(skipped)} left alone: {", ".join(skipped[:6])})' if skipped else ''
    return (
        f'morphed {len(done)} object(s) with op {op}: {", ".join(done[:12])}'
        + (f' and {len(done) - 12} more' if len(done) > 12 else '')
        + tail
    )


def t_stack_storeys(d: Drawing, a, which='new', count=1):
    recs = list(d.select(which))
    if not recs:
        return 'refused: nothing matches — pass "new", a group name or object ids'
    n = int(_num(count, 1))
    if n < 1 or n > 200:
        return 'refused: count must be between 1 and 200'
    H = d.storey_h
    if len(d.objs) + n * len(recs) > MAX_OBJECTS:
        return f'refused: that is {n * len(recs)} objects past the {MAX_OBJECTS} ceiling'
    base_top = max(storey_of(o['y'], H) for o in recs)
    made = 0
    for k in range(1, n + 1):
        for o in recs:
            d.new(
                o['kind'],
                o['p'],
                o['x'],
                o['z'],
                o['y'] + k * H,
                o['ry'],
                o['mat'],
                name=f'{o["name"]} +{k}',
                grp=o['grp'],
            )
            made += 1
    return (
        f'stacked {len(recs)} object(s) upward {n} time(s): {made} new objects, '
        f'{H:g} m apart, storeys {base_top + 1}..{base_top + n}'
    )


TOOLS = [
    (
        {
            'name': 'draw_massing',
            'description': 'A study-model volume filling a block of cells: ONE solid record, not walls. style box, taper, '
            "twist, setback, loft, ellipse, chamfer, round or shear; amount is that style's main number "
            '(taper top scale 0.6, twist degrees, setback steps, chamfer/round metres, shear metres). Use for '
            'towers, blocks and "show me some shapes"; slabs=true adds a floor slab per storey.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storeys': {'type': 'integer'},
                    'style': {'type': 'string', 'enum': list(STYLES)},
                    'amount': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'slabs': {'type': 'boolean'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_massing,
    ),
    (
        {
            'name': 'morph',
            'description': 'Reshape massing volumes (and plain boxes) that are already drawn: op taper, twist, setback, '
            'chamfer, round or shear converts the record to that shape keeping its footprint; op height sets '
            'the height in metres; op scale multiplies the footprint. Refuses on walls, roofs and furniture.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {'type': 'string'},
                    'op': {'type': 'string', 'enum': list(OPS)},
                    'amount': {'type': 'number'},
                },
                'required': ['op'],
            },
        },
        t_morph,
    ),
    (
        {
            'name': 'stack_storeys',
            'description': 'Copy every object in the selection upward `count` times, one storey (2.7 m) each time, keeping '
            'the group. The plain way to turn a drawn ground-floor plan into a tower.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': {'type': 'string'}, 'count': {'type': 'integer'}},
                'required': ['count'],
            },
        },
        t_stack_storeys,
    ),
]

EXAMPLES = [
    {
        'ask': 'a 24-storey tower on C4 to L13 that tapers to about half at the top',
        'calls': [
            {
                'tool': 'draw_massing',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 24, 'style': 'taper', 'amount': 0.5},
            }
        ],
    },
    {
        'ask': 'put a twisting glass block on E10..N19, 30 floors, 90 degrees of twist',
        'calls': [
            {
                'tool': 'draw_massing',
                'args': {
                    'cell_from': 'E10',
                    'cell_to': 'N19',
                    'storeys': 30,
                    'style': 'twist',
                    'amount': 90,
                    'material': 'mat_glass',
                },
            }
        ],
    },
    {
        'ask': 'a stepped brick block from A1 to L12, 9 storeys, and I want the floor areas',
        'calls': [
            {
                'tool': 'draw_massing',
                'args': {
                    'cell_from': 'A1',
                    'cell_to': 'L12',
                    'storeys': 9,
                    'style': 'setback',
                    'amount': 3,
                    'material': 'mat_brick',
                    'slabs': True,
                },
            }
        ],
    },
    {
        'ask': 'make that one taper instead',
        'calls': [{'tool': 'morph', 'args': {'which': 'new', 'op': 'taper', 'amount': 0.6}}],
    },
    {'ask': 'make it 40 m tall', 'calls': [{'tool': 'morph', 'args': {'which': 'new', 'op': 'height', 'amount': 40}}]},
    {
        'ask': 'copy this ground floor up 5 more storeys',
        'calls': [{'tool': 'stack_storeys', 'args': {'which': 'new', 'count': 5}}],
    },
]
