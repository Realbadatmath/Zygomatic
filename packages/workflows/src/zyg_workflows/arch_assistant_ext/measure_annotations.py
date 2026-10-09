# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_annotations — the assistant's twins of Measure ▸ Dimension, Protractor
and Label (arch_ext/measure_annotations.js).

The model cannot click the canvas, so the three pointer modes get three ordinary
tools that name CELLS instead of points, and one read-only report,
list_annotations(), that hands back every annotation with the value it measures
— the same arithmetic the tab prints in the sprite, so the model reads the
drawing's own numbers instead of guessing them.

The three kinds are VOID_KINDS: the tab draws them as lines plus a text sprite
and Blender builds nothing (arch_blender_ext/measure_annotations.py). A
dimension is a statement about the building, not part of it.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, _num, cell_centre, cell_of, parse_cell

KINDS = {
    'dim_linear': {'x2': 5.0, 'z2': 0.0, 'off': 0.6, 'txt': ''},
    'dim_angle': {'x1': 2.0, 'z1': 0.0, 'x2': 0.0, 'z2': -2.0, 'r': 1.0},
    'label_text': {'txt': 'Note', 'size': 0.35},
}
OPENINGS: list = []
# Nothing to build in Blender: annotations live on the drawing, not in the model.
# tests_arch_ext/test_all.py keeps its own VOID_KINDS set; it unions the families
# that export this name (that file is not ours to edit).
VOID_KINDS = ['dim_linear', 'dim_angle', 'label_text']
BUTTONS: list = []

PROMPT = (
    'Annotations that stay on the drawing: add_dimension(cell_from, cell_to, offset) writes a linear '
    'dimension between the centres of two cells (offset = how far the dimension line sits off the measured '
    'span, metres); add_angle(vertex_cell, cell_a, cell_b) writes a three-point angle at a vertex cell; '
    'add_label(cell, text) pins a text note to a cell. list_annotations() reports every annotation already '
    'on the drawing with the length or angle it measures — read it before answering "how wide is…". '
    'These three kinds (dim_linear, dim_angle, label_text) are drawing marks: they carry text, they are not '
    'built in Blender, and they never count as building fabric.'
)


def _value(o: dict) -> float:
    """Metres for a dim_linear, degrees for a dim_angle — the same arithmetic the
    tab's sprite prints (arch_ext/measure_annotations.js `value`)."""
    p = o.get('p') or {}
    if o.get('kind') == 'dim_linear':
        return math.hypot(_num(p.get('x2'), 0.0), _num(p.get('z2'), 0.0))
    if o.get('kind') == 'dim_angle':
        a1 = math.atan2(_num(p.get('z1'), 0.0), _num(p.get('x1'), 1.0))
        a2 = math.atan2(_num(p.get('z2'), 0.0), _num(p.get('x2'), 1.0))
        d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        return abs(math.degrees(d))
    return 0.0


def t_add_dimension(d: Drawing, a, cell_from, cell_to, offset=0.6, text='', storey=0):
    ax, az = cell_centre(*parse_cell(cell_from))
    bx, bz = cell_centre(*parse_cell(cell_to))
    dx, dz = bx - ax, bz - az
    length = math.hypot(dx, dz)
    if length < 1e-3:
        return 'refused: cell_from and cell_to are the same cell — a dimension needs two points'
    off = _num(offset, 0.6)
    if abs(off) > 100:
        return 'refused: offset must be within 100 m of the measured span'
    o = d.new(
        'dim_linear',
        {'x2': round(dx, 4), 'z2': round(dz, 4), 'off': round(off, 4), 'txt': str(text or '')},
        ax,
        az,
        int(_num(storey, 0)) * d.storey_h,
        name=f'Dimension {length:.3f} m',
    )
    return f'dimension {o["id"]} from {cell_from} to {cell_to}: {length:.3f} m, dimension line offset {off:g} m' + (
        f', text "{text}"' if text else ''
    )


def t_add_angle(d: Drawing, a, vertex_cell, cell_a, cell_b, radius=1.0, storey=0):
    vx, vz = cell_centre(*parse_cell(vertex_cell))
    ax, az = cell_centre(*parse_cell(cell_a))
    bx, bz = cell_centre(*parse_cell(cell_b))
    x1, z1, x2, z2 = ax - vx, az - vz, bx - vx, bz - vz
    if math.hypot(x1, z1) < 1e-3 or math.hypot(x2, z2) < 1e-3:
        return 'refused: cell_a and cell_b must both be different from vertex_cell'
    r = _num(radius, 1.0)
    if r < 0.05 or r > 100:
        return 'refused: radius must be between 0.05 and 100 m'
    o = d.new(
        'dim_angle',
        {'x1': round(x1, 4), 'z1': round(z1, 4), 'x2': round(x2, 4), 'z2': round(z2, 4), 'r': round(r, 4)},
        vx,
        vz,
        int(_num(storey, 0)) * d.storey_h,
    )
    deg = _value(o)
    o['name'] = f'Angle {deg:.1f}\u00b0'
    return f'angle {o["id"]} at {vertex_cell} between {cell_a} and {cell_b}: {deg:.2f} degrees, arc radius {r:g} m'


def t_add_label(d: Drawing, a, cell, text, size=0.35, storey=0):
    txt = str(text or '').strip()
    if not txt:
        return 'refused: a label needs some text'
    if len(txt) > 200:
        return 'refused: a label is a note, not a paragraph — keep it under 200 characters'
    s = _num(size, 0.35)
    if s < 0.05 or s > 20:
        return 'refused: size (the text height in metres) must be between 0.05 and 20'
    x, z = cell_centre(*parse_cell(cell))
    o = d.new(
        'label_text',
        {'txt': txt, 'size': round(s, 4)},
        x,
        z,
        int(_num(storey, 0)) * d.storey_h,
        name='Label: ' + txt[:40],
    )
    return f'label {o["id"]} at {cell}: "{txt}" ({s:g} m tall)'


def t_list_annotations(d: Drawing, a):
    rows = [o for o in d.objs if o['kind'] in KINDS]
    if not rows:
        return 'no annotations on the drawing'
    out = [f'{len(rows)} annotation(s):']
    for o in rows:
        cell = cell_of(o['x'], o['z'])
        st = int(round(o['y'] / (d.storey_h or 2.7)))
        p = o.get('p') or {}
        if o['kind'] == 'dim_linear':
            what = f'{_value(o):.3f} m' + (f' — "{p["txt"]}"' if p.get('txt') else '')
        elif o['kind'] == 'dim_angle':
            what = f'{_value(o):.2f} degrees'
        else:
            what = f'"{p.get("txt", "")}" ({_num(p.get("size"), 0.35):g} m tall)'
        out.append(f'  {o["id"]} {o["kind"]} at {cell} storey {st}: {what}')
    return '\n'.join(out)


TOOLS = [
    (
        {
            'name': 'add_dimension',
            'description': 'A linear dimension that stays on the drawing: the measured span runs between the centres '
            'of two cells, with the dimension line offset to one side. The label is the length in metres '
            'unless you pass text. Use to annotate a plan the user asked to be dimensioned.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'offset': {'type': 'number'},
                    'text': {'type': 'string'},
                    'storey': {'type': 'integer'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_dimension,
    ),
    (
        {
            'name': 'add_angle',
            'description': 'A three-point angle annotation: the vertex cell plus the two cells the arms point at. '
            'The label is the angle in degrees. Use for a splayed corner, a roof pitch on plan, a junction.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vertex_cell': {'type': 'string'},
                    'cell_a': {'type': 'string'},
                    'cell_b': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'storey': {'type': 'integer'},
                },
                'required': ['vertex_cell', 'cell_a', 'cell_b'],
            },
        },
        t_add_angle,
    ),
    (
        {
            'name': 'add_label',
            'description': 'A text note pinned to a cell — a room name, a level, a "new opening here". '
            'size is the text height in metres.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'text': {'type': 'string'},
                    'size': {'type': 'number'},
                    'storey': {'type': 'integer'},
                },
                'required': ['cell', 'text'],
            },
        },
        t_add_label,
    ),
    (
        {
            'name': 'list_annotations',
            'description': 'Every dimension, angle and label already on the drawing, with the value it measures '
            '(metres or degrees) and the cell it sits on. Read-only.',
            'input_schema': {'type': 'object', 'properties': {}},
        },
        t_list_annotations,
    ),
]

EXAMPLES = [
    {
        'ask': 'dimension the front wall from C4 to K4',
        'calls': [{'tool': 'add_dimension', 'args': {'cell_from': 'C4', 'cell_to': 'K4'}}],
    },
    {
        'ask': 'mark the angle of the corner at F6 between D6 and F10',
        'calls': [{'tool': 'add_angle', 'args': {'vertex_cell': 'F6', 'cell_a': 'D6', 'cell_b': 'F10'}}],
    },
    {'ask': 'label the kitchen', 'calls': [{'tool': 'add_label', 'args': {'cell': 'E5', 'text': 'Kitchen'}}]},
    {'ask': 'what do the dimensions on this drawing say?', 'calls': [{'tool': 'list_annotations', 'args': {}}]},
]
