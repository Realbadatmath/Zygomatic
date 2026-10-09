# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.circulation_rules.cores import (
    check_continuity,
    check_core_clash,
    check_flights,
    check_head_house,
    check_stair_approach,
    check_stair_guarding,
)
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import (
    check_enclosure,
    check_headroom,
    check_landing_floor,
    check_lift_landing,
    check_overrun,
    check_shaft_in_water,
)


DESIGN_CHECKS = [
    check_continuity,
    check_flights,
    check_stair_guarding,
    check_head_house,
    check_core_clash,
    check_stair_approach,
    check_landing_floor,
    check_headroom,
    check_enclosure,
    check_overrun,
    check_shaft_in_water,
    check_lift_landing,
]

PROMPT = (
    'CIRCULATION: every floor with a slab must be reached by a stair, and by a lift from 3 storeys up '
    '(a shaft has a door on every served storey); the roof deck counts as a floor when anything but '
    'roof plant stands on it. One stair record climbs ONE storey — a flight is at most 18 steps — it '
    'carries rails, and a stair arriving on a deck arrives inside a head house. add_stair(cell, 0, '
    '<storeys>) and add_elevator(cell, 0, <storeys>) do all of that; design_check names what is missing.'
)

EXAMPLES = [
    {
        'ask': 'run the stair and two lifts of the 20-storey tower all the way to the roof deck',
        'calls': [
            {
                'tool': 'add_stair',
                'args': {'cell': 'FH96', 'from_storey': 0, 'to_storey': 20, 'kind': 'u', 'width': 1.2},
            },
            {'tool': 'add_elevator', 'args': {'cell': 'FD96', 'from_storey': 0, 'to_storey': 20}},
            {'tool': 'add_elevator', 'args': {'cell': 'FK96', 'from_storey': 0, 'to_storey': 20}},
            {'tool': 'design_check', 'args': {}},
        ],
    },
    {'ask': 'can you actually get to the pool on the roof?', 'calls': [{'tool': 'design_check', 'args': {}}]},
]
