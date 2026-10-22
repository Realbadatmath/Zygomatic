# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stairs_vertical — the assistant's vertical-circulation tools.

Tools: add_stair (straight / U / winder / spiral between two storeys),
add_elevator (shaft + car), add_fire_escape (external switchback),
add_escalator (one sloping flight).

The one number that matters is the RISE. A stair between two storeys must land
exactly on the upper floor, so the tools never take a rise: they take the two
storeys, divide the height into the fewest steps whose rise is at most the
Dutch comfort limit (0.18 m, always <= 0.19) and hand the exact quotient to the
record. steps * rise is therefore the storey height to the last bit, which is
what the tab and Blender then draw.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.stairs_vertical.constants import (
    annotations,
    math,
    A,
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    MATERIALS,
    _num,
    MAX_OBJECTS,
    _zyg_logging,
    _zyg_log,
    KINDS,
    OPENINGS,
    MAX_RISE,
    RISE_LIMIT,
    STAIR_KINDS,
    MAX_STOREYS,
    VOID_MARGIN,
    HEAD_MARGIN,
    HEAD_HOUSE_OBJS,
    OVERRUN,
    DOOR_H,
    DOOR_MARGIN,
    DOOR_DEEP,
    FACADE_GAP,
    PROMPT,
    _mat,
    _rise_for,
    _envelope,
    _voids,
    _stack_params,
    _probe,
    _overhang,
)
from zyg_workflows.arch_assistant_ext.stairs_vertical.plan import (
    APPROACH_M,
    CLASH_TOL,
    CORE_STAIR_KINDS,
    approach_bboxes,
    head_bboxes,
    plan_overlap,
    plan_clash,
    y_overlap,
    _clear_cell,
    _spacing_note,
    _stack_plan,
    _core_span,
    _group_mat,
    _group_centre,
    _outward,
    _group_floors,
    _door_leaf_mat,
    _head_house,
)
from zyg_workflows.arch_assistant_ext.stairs_vertical.tools import (
    t_add_stair,
    t_add_elevator,
    t_add_fire_escape,
    t_add_escalator,
)
from zyg_workflows.arch_assistant_ext.stairs_vertical.registry import (
    TOOLS,
    EXAMPLES,
)

__all__ = [
    'annotations',
    'math',
    'A',
    'Drawing',
    'parse_cell',
    'cell_centre',
    'cell_name',
    'MATERIALS',
    '_num',
    'MAX_OBJECTS',
    '_zyg_logging',
    '_zyg_log',
    'KINDS',
    'OPENINGS',
    'MAX_RISE',
    'RISE_LIMIT',
    'STAIR_KINDS',
    'MAX_STOREYS',
    'VOID_MARGIN',
    'HEAD_MARGIN',
    'HEAD_HOUSE_OBJS',
    'OVERRUN',
    'DOOR_H',
    'DOOR_MARGIN',
    'DOOR_DEEP',
    'FACADE_GAP',
    'PROMPT',
    '_mat',
    '_rise_for',
    '_envelope',
    '_voids',
    '_stack_params',
    '_probe',
    '_overhang',
    'APPROACH_M',
    'CLASH_TOL',
    'CORE_STAIR_KINDS',
    'approach_bboxes',
    'head_bboxes',
    'plan_overlap',
    'plan_clash',
    'y_overlap',
    '_clear_cell',
    '_spacing_note',
    '_stack_plan',
    '_core_span',
    '_group_mat',
    '_group_centre',
    '_outward',
    '_group_floors',
    '_door_leaf_mat',
    '_head_house',
    't_add_stair',
    't_add_elevator',
    't_add_fire_escape',
    't_add_escalator',
    'TOOLS',
    'EXAMPLES',
]
