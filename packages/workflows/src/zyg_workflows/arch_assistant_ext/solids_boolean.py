# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""solids_boolean — the assistant half of the Solids ▸ Union / Subtract /
Intersect icons (2026-09-08).

Two ways in, one arithmetic:

  · BUTTONS — the model presses `bool_u`, `bool_s`, `bool_i` in the tab, with
    {"a": id, "b": id} or on whatever is selected. The tab's own BSP kernel
    (arch_ext/solids_boolean.js) does the cutting.
  · TOOLS — `boolean(op, which_a, which_b)` does the same edit server-side, on
    the Drawing, so the model can build a boolean while composing a whole
    document in one turn and read back the ids it made.

Both produce the SAME record: kind 'csg', p = {op, a, b} where a and b are the
operands' full parameter records positioned RELATIVE to the csg record, which
sits at operand a's x/y/z. A drawing stores parameters, never geometry, so a
boolean can be re-cut, re-materialled and undone like any other object.

Standard library only.
"""

from zyg_workflows.arch_assistant import Drawing, _num

# The 'csg' kind, so add_object and the rail agree with the tab. The default is
# a 2 m cube with a 1.2 m bore, the same default arch_ext/solids_boolean.js has.
KINDS = {
    'csg': {
        'op': 'subtract',
        'a': {'kind': 'box', 'p': {'w': 2, 'h': 2, 'd': 2}, 'x': 0, 'y': 0, 'z': 0, 'rx': 0, 'ry': 0, 'rz': 0, 's': 1},
        'b': {
            'kind': 'cylinder',
            'p': {'r': 0.6, 'h': 3, 'seg': 32},
            'x': 0,
            'y': -0.5,
            'z': 0,
            'rx': 0,
            'ry': 0,
            'rz': 0,
            's': 1,
        },
    }
}
OPENINGS: list = []
VOID_KINDS: list = []

BUTTONS = ['bool_u', 'bool_s', 'bool_i']

PROMPT = (
    'Boolean solids: two solids can be cut into one editable object of kind "csg". '
    'boolean(op, which_a, which_b) does it server-side — op is "union" (weld both), '
    '"subtract" (a minus b, ORDER MATTERS) or "intersect" (only the shared volume); '
    'which_a and which_b each name ONE object (an id, or "new"/a kind/a group that '
    'resolves to one). Both operands are replaced by one "csg" record that keeps their '
    'parameters, so it stays editable and undoable. In the tab the same three icons are '
    'press_button("bool_u"|"bool_s"|"bool_i", {"a": id, "b": id}) — without args they use '
    'the current selection, and for subtract the FIRST selected is the one being cut. '
    'An operand of more than 20000 triangles is refused: a BSP boolean is quadratic in '
    'the worst case.'
)

OPS = ('union', 'subtract', 'intersect')
_VERB = {'union': 'Union', 'subtract': 'Subtract', 'intersect': 'Intersect'}
# Kinds the tab draws as lines only (guides, openings): they enclose no volume,
# so a boolean on one would be an empty result dressed up as a solid.
_NO_VOLUME = {'opening', 'guide_line', 'guide_circle'}


def _label(kind):
    return str(kind or '?').replace('_', ' ')


def _one(d: Drawing, which, side: str):
    """Resolve `which` to exactly one record, or raise with a readable reason."""
    recs = d.select(which)
    if not recs:
        raise ValueError('refused: %s (%r) matched no object' % (side, which))
    if len(recs) > 1:
        raise ValueError(
            'refused: %s (%r) matched %d objects — a boolean needs exactly one on each side' % (side, which, len(recs))
        )
    return recs[0]


def _desc(rec: dict, org: dict) -> dict:
    """One operand as a parameter record, positioned relative to `org`."""
    return {
        'kind': rec['kind'],
        'p': dict(rec.get('p') or {}),
        'x': round(_num(rec.get('x'), 0) - org['x'], 6),
        'y': round(_num(rec.get('y'), 0) - org['y'], 6),
        'z': round(_num(rec.get('z'), 0) - org['z'], 6),
        'rx': _num(rec.get('rx'), 0),
        'ry': _num(rec.get('ry'), 0),
        'rz': _num(rec.get('rz'), 0),
        's': _num(rec.get('s'), 1),
    }


def t_boolean(d: Drawing, a: dict, op: str = 'subtract', which_a='', which_b='', name: str = ''):
    op = str(op or 'subtract').strip().lower()
    if op not in OPS:
        return 'refused: op must be one of %s' % ', '.join(OPS)
    try:
        ra = _one(d, which_a, 'which_a')
        rb = _one(d, which_b, 'which_b')
    except ValueError as e:
        return str(e)
    if ra['id'] == rb['id']:
        return 'refused: which_a and which_b are the same object (%s)' % ra['id']
    for r, side in ((ra, 'which_a'), (rb, 'which_b')):
        if r['kind'] in _NO_VOLUME:
            return 'refused: %s is a %s, which encloses no volume' % (side, _label(r['kind']))

    org = {'x': _num(ra.get('x'), 0), 'y': _num(ra.get('y'), 0), 'z': _num(ra.get('z'), 0)}
    p = {'op': op, 'a': _desc(ra, org), 'b': _desc(rb, org)}
    label = name or '%s: %s / %s' % (_VERB[op], _label(ra['kind']), _label(rb['kind']))
    rec = d.new(
        'csg', p, org['x'], org['z'], org['y'], mat=ra.get('mat') or 'mat_concrete', name=label, grp=ra.get('grp') or ''
    )
    d.remove([ra, rb])
    d.selected = [rec['id']]
    return (
        '%s: %s (%s) %s %s (%s) -> one csg solid %s at x=%s z=%s y=%s. '
        'Both operands are gone; their parameters live inside %s, so it stays editable.'
        % (
            _VERB[op],
            ra['id'],
            _label(ra['kind']),
            'plus' if op == 'union' else ('minus' if op == 'subtract' else 'intersected with'),
            rb['id'],
            _label(rb['kind']),
            rec['id'],
            rec['x'],
            rec['z'],
            rec['y'],
            rec['id'],
        )
    )


TOOLS = [
    (
        {
            'name': 'boolean',
            'description': (
                'Cut two solids into ONE editable object of kind "csg": union (weld), '
                'subtract (which_a minus which_b — order matters) or intersect (the shared '
                'volume only). Both operands are removed and replaced by the result, which '
                'keeps their parameters and can be undone or re-cut. The same three icons '
                'exist in the tab as bool_u / bool_s / bool_i.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'op': {
                        'type': 'string',
                        'enum': list(OPS),
                        'description': 'union, subtract (a minus b) or intersect',
                    },
                    'which_a': {
                        'type': 'string',
                        'description': 'the FIRST solid — an object id, or "new"/a kind/a group '
                        'that resolves to exactly one object. In a subtract this '
                        'is the one being cut.',
                    },
                    'which_b': {
                        'type': 'string',
                        'description': 'the SECOND solid, same form. In a subtract this is the one cut away.',
                    },
                    'name': {'type': 'string', 'description': 'optional name for the result'},
                },
                'required': ['op', 'which_a', 'which_b'],
            },
        },
        t_boolean,
    )
]

EXAMPLES = [
    {
        'ask': 'punch that cylinder out of the block',
        'calls': [{'tool': 'boolean', 'args': {'op': 'subtract', 'which_a': 'box', 'which_b': 'cylinder'}}],
    },
    {'ask': 'weld the two selected solids together', 'calls': [{'tool': 'press_button', 'args': {'id': 'bool_u'}}]},
    {
        'ask': 'keep only where o3 and o4 overlap',
        'calls': [{'tool': 'press_button', 'args': {'id': 'bool_i', 'args': {'a': 'o3', 'b': 'o4'}}}],
    },
    {
        'ask': 'join the two towers into one solid called towers',
        'calls': [{'tool': 'boolean', 'args': {'op': 'union', 'which_a': 'o1', 'which_b': 'o2', 'name': 'towers'}}],
    },
    {
        'ask': 'keep only the volume the box and the sphere share',
        'calls': [{'tool': 'boolean', 'args': {'op': 'intersect', 'which_a': 'box', 'which_b': 'sphere'}}],
    },
]
