# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v3probe — the assistant half of the v3 seam's test fixture.

No tools of its own: this family exists only so that tests_arch_ext/test_v3_seam.py
can prove the seam it needs, in the same three engines every real family is proved
in. It does carry a PROMPT paragraph and worked examples, because the model has to
be told what it is for — a probe is not scenery and belongs in no drawing a user
asked for — and reached through the generic add_object.

The one kind, `v3probe`, has a HEIGHTS function that reads the OTHER records
through arch_assistant.current_drawing() — exactly what a `ground` record's
height function has to do to be the sum of the drawing's sculpts. Its height is
the number of `box` records in the drawing, inside a 2 m x 2 m footprint and
None outside it, matching arch_ext/v3probe.js and arch_blender_ext/v3probe.py.
"""

from zyg_workflows.arch_assistant import current_drawing

PROMPT = (
    'v3probe is the seam\'s TEST FIXTURE, not scenery: add_object kind "v3probe" drops a '
    '2 x 2 m quad, coloured per vertex, as tall as the number of box records in the drawing, '
    'so a test can prove that a height function reads the rest of the drawing the same way in '
    'the tab, in Blender and in Python — never put one in a drawing a user asked for.'
)

KINDS = {'v3probe': {}}
OPENINGS = []
TOOLS = []
EXAMPLES = [
    {
        'ask': 'drop a v3 seam probe on E5 so I can see whether the height function reads the drawing',
        'calls': [
            {
                'tool': 'add_object',
                'args': {'kind': 'v3probe', 'cell': 'E5', 'material': 'mat_paint_white', 'name': 'seam probe'},
            }
        ],
    },
    {
        'ask': 'put a probe next to two boxes on H8 — it should come out 2 m tall',
        'calls': [
            {'tool': 'add_object', 'args': {'kind': 'box', 'cell': 'H8', 'params': {'w': 1, 'd': 1, 'h': 1}}},
            {'tool': 'add_object', 'args': {'kind': 'box', 'cell': 'H9', 'params': {'w': 1, 'd': 1, 'h': 1}}},
            {'tool': 'add_object', 'args': {'kind': 'v3probe', 'cell': 'H10', 'name': 'probe reads 2'}},
        ],
    },
]


def h_v3probe(p, lx, lz):
    if abs(lx) > 1.0 or abs(lz) > 1.0:
        return None
    d = current_drawing()
    if d is None:
        return 0.0
    return float(len([r for r in d.objs if r['kind'] == 'box']))


HEIGHTS = {'v3probe': h_v3probe}
