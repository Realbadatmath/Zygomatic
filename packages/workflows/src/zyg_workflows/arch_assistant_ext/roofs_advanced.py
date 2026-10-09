# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""roofs_advanced — the assistant's advanced-roof tools.

Tools: add_roof_special (one of ten roof shapes over a block of cells, sitting
on top of the walls at storey*2.7) and add_skylights (glazed boxes let into a
roof's top surface). The base add_roof tool keeps its six shapes; this family
adds mansard, gambrel, butterfly, sawtooth, pyramid, cone, onion, half-hip,
barrel and a flat deck with a glazed strip. Nothing in arch_assistant.py is
touched — add_roof_special is a separate tool, not a wider add_roof.

Every kind's local origin is the footprint centre with the eave at y=0, so the
record's y is simply storey * d.storey_h. `over` is the overhang on all four
sides: the bounding box is (w+2*over) x h x (d+2*over).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    block_bounds,
    cell_name,
    parse_cell,
    storey_of,
)

KINDS = {
    'roof_mansard': {'w': 8, 'd': 6, 'h': 3, 'over': 0.4, 'break': 0.6},
    'roof_gambrel': {'w': 8, 'd': 6, 'h': 3, 'over': 0.4, 'break': 0.6},
    'roof_butterfly': {'w': 8, 'd': 6, 'h': 1.2, 'over': 0.4},
    'roof_sawtooth': {'w': 12, 'd': 8, 'h': 1.8, 'bays': 4},
    'roof_pyramid': {'w': 6, 'd': 6, 'h': 3, 'over': 0.4},
    'roof_cone': {'r': 3, 'h': 3, 'over': 0.3},
    'roof_onion': {'r': 2.5, 'h': 3.5, 'spire': 2},
    'roof_half_hip': {'w': 8, 'd': 6, 'h': 2.8, 'over': 0.4, 'clip': 0.5},
    'roof_curved': {'w': 8, 'd': 6, 'h': 2, 'over': 0.3},
    'roof_skylight_strip': {'w': 8, 'd': 6, 'h': 0.3},
}
OPENINGS: list = []

# the tool's `kind` argument: the short name the model says -> the record kind
SHAPES = {k[len('roof_') :]: k for k in KINDS}
ZINC = ('roof_curved', 'roof_onion')

PROMPT = (
    'Advanced roofs: add_roof_special(cell_from, cell_to, storey, kind) puts one roof over the inclusive '
    'cell block, sitting on the walls at that storey. kind is mansard or gambrel (two pitches, attic '
    'storey), butterfly (falls inward to a valley), sawtooth (north-light bays along the width, set bays), '
    'pyramid or half_hip (tower caps and jerkinhead ends), cone or onion (round towers, church and '
    'campanile caps — pass the block that encloses the circle), curved (a barrel along the width) or '
    'skylight_strip (a flat deck with a glazed band). Use it instead of add_roof whenever the user names '
    'one of those shapes; add_roof still covers flat/gable/hip/shed/dome/vault. height defaults to '
    '40% of the shorter side, overhang to 0.4 m. add_skylights(roof, count, w, d) then lets glazed boxes '
    'into that roof id or group near its ridge.'
)


def _mat(m, kind):
    if m in MATERIALS:
        return m
    return 'mat_zinc' if kind in ZINC else 'mat_roof_tile'


def t_add_roof_special(
    d: Drawing, a, cell_from, cell_to, storey=1, kind='mansard', height=None, overhang=0.4, bays=4, material='', name=''
):
    key = str(kind or '').strip().lower().replace(' ', '_').replace('-', '_')
    kk = key if key in KINDS else SHAPES.get(key)
    if not kk:
        return 'refused: kind must be one of ' + ', '.join(sorted(SHAPES))
    try:
        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    except ValueError as e:
        return f'refused: {e}'
    W, D = xmax - xmin, zmax - zmin
    st = int(_num(storey, 1))
    y = st * d.storey_h
    o = max(0.0, min(5.0, _num(overhang, 0.4)))
    H = _num(height, None)
    if H is None or H <= 0:
        H = min(W, D) * (0.25 if kk == 'roof_butterfly' else 0.4)
    H = round(max(0.1, H), 3)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    if kk in ('roof_cone', 'roof_onion'):
        p = {'r': round(min(W, D) / 2, 3), 'h': H}
        p['spire' if kk == 'roof_onion' else 'over'] = round(H * 0.6, 3) if kk == 'roof_onion' else round(o, 3)
    else:
        p = {'w': round(W, 4), 'd': round(D, 4), 'h': H}
        if kk == 'roof_sawtooth':
            p['bays'] = max(1, min(60, int(_num(bays, 4))))
        elif kk != 'roof_skylight_strip':
            p['over'] = round(o, 3)
            if kk in ('roof_mansard', 'roof_gambrel'):
                p['break'] = 0.6
            elif kk == 'roof_half_hip':
                p['clip'] = 0.5
    r = d.new(kk, p, (xmin + xmax) / 2, (zmin + zmax) / 2, y, 0.0, _mat(material, kk), name=name or None, grp=name)
    return (
        f'{key} roof {r["id"]} over {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
        f'({W:g} x {D:g} m), {H:g} m tall, sitting at storey {st} ({y:g} m), {r["mat"]}'
    )


def t_add_skylights(dr: Drawing, a, roof, count=2, w=1.2, d=1.2, name=''):
    """`roof` is a roof id or a group name; d here is the skylight's depth — the
    drawing is `dr` so that the tool can keep the w/d argument names."""
    recs = [o for o in dr.select(roof) if str(o['kind']).startswith('roof_')]
    if not recs:
        return f'refused: {roof} is not a roof (or a group holding one) — pass a roof id or its group name'
    n = max(1, min(50, int(_num(count, 2))))
    ww, dd = max(0.2, _num(w, 1.2)), max(0.2, _num(d, 1.2))
    if len(dr.objs) + n * len(recs) > MAX_OBJECTS:
        return f'refused: that is {n * len(recs)} objects past the {MAX_OBJECTS} ceiling'
    made = []
    for o in recs:
        p = o['p']
        h = _num(p.get('h'), _num(p.get('t'), 0.3))
        span = _num(p.get('w'), 2 * _num(p.get('r'), 3.0)) * 0.7
        y = o['y'] + h - 0.05
        for i in range(n):
            x = o['x'] + span * ((i + 0.5) / n - 0.5)
            s = dr.new(
                'box',
                {'w': round(ww, 3), 'd': round(dd, 3), 'h': 0.1},
                x,
                o['z'],
                y,
                0.0,
                'mat_glass',
                name=name or f'skylight {i + 1}',
                grp=o['grp'] or (name or 'skylights'),
            )
            made.append(s['id'])
    return (
        f'added {len(made)} skylights {made[0]}..{made[-1]} ({ww:g} x {dd:g} m) on '
        f'{len(recs)} roof(s) {", ".join(o["id"] for o in recs[:6])} at storey '
        f'{storey_of(recs[0]["y"], dr.storey_h)}'
    )


TOOLS = [
    (
        {
            'name': 'add_roof_special',
            'description': 'One advanced roof over the INCLUSIVE block of cells, sitting on top of the walls at `storey`: mansard, gambrel, butterfly, sawtooth, pyramid, cone, onion, half_hip, curved (barrel) or skylight_strip. Use this instead of add_roof whenever the user names one of those shapes. height defaults to 40% of the shorter side (25% for butterfly, where it is the valley depth).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'kind': {'type': 'string', 'enum': sorted(SHAPES)},
                    'height': {'type': 'number'},
                    'overhang': {'type': 'number'},
                    'bays': {
                        'type': 'integer',
                        'description': 'sawtooth only: how many north-light bays along the width',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'kind'],
            },
        },
        t_add_roof_special,
    ),
    (
        {
            'name': 'add_skylights',
            'description': "Glazed skylight boxes let into a roof's top surface, spread along its width. `roof` is a roof id or the group name of the roof; count is how many per roof. Refused on anything that is not a roof.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'roof': {'type': 'string', 'description': 'a roof object id (o12) or a group name'},
                    'count': {'type': 'integer'},
                    'w': {'type': 'number'},
                    'd': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['roof'],
            },
        },
        t_add_skylights,
    ),
]

EXAMPLES = [
    {
        'ask': 'a mansard roof on the house from C4 to J9, two storeys up',
        'calls': [
            {'tool': 'add_roof_special', 'args': {'cell_from': 'C4', 'cell_to': 'J9', 'storey': 2, 'kind': 'mansard'}}
        ],
    },
    {
        'ask': 'put a sawtooth roof with 6 bays over the workshop D10 to R21',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {'cell_from': 'D10', 'cell_to': 'R21', 'storey': 1, 'kind': 'sawtooth', 'bays': 6},
            }
        ],
    },
    {
        'ask': 'a conical cap on the round tower at K20, 8 m across, 5 storeys up',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {'cell_from': 'H17', 'cell_to': 'O24', 'storey': 5, 'kind': 'cone', 'height': 5},
            }
        ],
    },
    {
        'ask': 'an onion dome on the church tower F6 to J10, at 12 m',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {'cell_from': 'F6', 'cell_to': 'J10', 'storey': 4, 'kind': 'onion', 'height': 4},
            }
        ],
    },
    {
        'ask': 'flat deck with a rooflight strip over the extension B2 to F5, then three skylights in it',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {
                    'cell_from': 'B2',
                    'cell_to': 'F5',
                    'storey': 1,
                    'kind': 'skylight_strip',
                    'name': 'extension roof',
                },
            },
            {'tool': 'add_skylights', 'args': {'roof': 'extension roof', 'count': 3, 'w': 1.2, 'd': 1.2}},
        ],
    },
    {
        'ask': 'give the barn a gambrel roof, C8 to L15, one storey up, with a butterfly roof on the lean-to M8 to P11',
        'calls': [
            {'tool': 'add_roof_special', 'args': {'cell_from': 'C8', 'cell_to': 'L15', 'storey': 1, 'kind': 'gambrel'}},
            {
                'tool': 'add_roof_special',
                'args': {'cell_from': 'M8', 'cell_to': 'P11', 'storey': 1, 'kind': 'butterfly'},
            },
        ],
    },
]
