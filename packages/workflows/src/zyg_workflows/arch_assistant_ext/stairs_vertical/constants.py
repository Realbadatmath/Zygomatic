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

# ruff: noqa: F401

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, parse_cell, cell_centre, cell_name, MATERIALS, _num, MAX_OBJECTS
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.stairs_vertical')


KINDS = {
    'stair_u': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'gap': 0.2, 'rails': 1},
    'stair_winder': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'turn': 90, 'rails': 1},
    'stair_landing': {'w': 1.2, 'd': 1.2, 't': 0.15},
    'elevator_shaft': {
        'w': 1.8,
        'd': 2.0,
        'h': 8.1,
        't': 0.2,
        'doors': [],
        'door_side': 'south',
        'overrun': 0.0,
        'sh': 2.7,
    },
    'elevator_car': {'w': 1.6, 'd': 1.8, 'h': 2.2, 'door': 1},
    'escalator': {'rise': 2.7, 'w': 1.0, 'angle': 30, 'rail_h': 0.9},
    'fire_stair_exterior': {'storeys': 3, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18},
}
OPENINGS: list = []

MAX_RISE = 0.18  # the rise the step count is solved for
RISE_LIMIT = 0.19  # the rise a finished stair may never exceed
STAIR_KINDS = ('straight', 'u', 'winder', 'spiral')

MAX_STOREYS = 60  # one call's ceiling — past that, call add_stair again
VOID_MARGIN = 0.05  # the floor opening is the stair's plan + this, all round
HEAD_MARGIN = 0.6  # the head house encloses the stair's plan + this
HEAD_HOUSE_OBJS = 6  # 4 walls + roof + door, budgeted before anything is drawn

# ── the lift (2026-09-10) ────────────────────────────────────────────────────
# Job 71ac02b0's two 54 m shafts had no doors, no overrun and no floor openings:
# a solid concrete tube through nineteen slabs that nobody could get into. A
# shaft is now three relations at once — a door on EVERY served storey, the
# motor room's overrun above the top served deck, and a void through every floor
# its span crosses (the same rule slab_voids.check_voids measures).
OVERRUN = 1.5  # m of shaft above the top served deck: the motor room
DOOR_H = 2.1  # a lift door is a 2.1 m opening, like every other door
DOOR_MARGIN = 0.4  # the leaf pair is (shaft w - this) wide: it stays inside the jambs
DOOR_DEEP = 0.05  # how far the recessed panel stands out of the shaft wall
FACADE_GAP = 0.05  # a fire escape hangs this clear of the wall line

PROMPT = (
    'Vertical circulation. add_stair(cell, from_storey, to_storey=<storeys> to reach the roof deck) draws one '
    'stair per storey, cuts the floor openings, adds rails, builds the head house when it reaches the deck; '
    'kind u (flights round a landing), winder or spiral; straight only to 2 storeys; direction_deg turns it '
    '(0 = east, 90 = north). add_elevator(cell, from_storey, to_storey=<storeys> to serve the deck) sinks a '
    'shaft with a door on every served storey (door_side), a 1.5 m overrun above the top deck for the motor '
    'room, and an opening through every floor it passes. add_fire_escape(group, side) hangs an outside '
    'stair on that facade — a fire escape is OUTSIDE the plan, never in a cell inside it. add_escalator over '
    'several storeys stacks one record per storey and needs ~4.7 m of floor each. Stairs and lifts are '
    'refused outside a building or through a facade. Heights are storeys, not metres.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _rise_for(height: float) -> tuple:
    """(steps, rise) — the fewest steps whose rise is at most MAX_RISE, and the
    exact quotient, so steps * rise == height."""
    steps = max(1, math.ceil(height / MAX_RISE - 1e-9))
    return steps, round(height / steps, 9)


# ── the two families this tool cannot draw without ───────────────────────────
# envelope_rules answers "may it stand here", slab_voids cuts the hole it needs
# in every floor it passes. Both are resolved at CALL time: extensions load
# alphabetically, so neither is imported yet when this module is.
def _envelope():
    return A.EXT_MODULES.get('envelope_rules')


def _voids():
    return A.EXT_MODULES.get('slab_voids')


def _stack_params(k: str, steps: int, rise: float, w: float) -> tuple:
    """(record kind, p) for ONE storey of the stack. `rails` is always on: an
    open flight edge is a fall, and the builders read the flag."""
    if k == 'straight':
        return 'stair_straight', {'steps': steps, 'rise': rise, 'run': 0.28, 'w': w, 'rails': 1}
    if k == 'u':
        return 'stair_u', {'steps': steps, 'rise': rise, 'run': 0.28, 'w': w, 'gap': 0.2, 'rails': 1}
    if k == 'winder':
        return 'stair_winder', {'steps': steps, 'rise': rise, 'run': 0.28, 'w': w, 'turn': 90, 'rails': 1}
    return 'stair_spiral', {
        'steps': steps,
        'rise': rise,
        'r_in': 0.15,
        'r_out': round(w + 0.2, 3),
        'sweep': 360,
        'rails': 1,
    }


def _probe(rec_kind: str, p: dict, x: float, z: float, ry: float) -> dict:
    """A record-shaped dict that is NOT in the drawing — what envelope_rules
    measures before anything is drawn."""
    return {
        'id': '?',
        'kind': rec_kind,
        'name': rec_kind,
        'p': dict(p),
        'x': x,
        'y': 0.0,
        'z': z,
        'rx': 0.0,
        'ry': ry,
        'rz': 0.0,
        's': 1,
        'mat': 'mat_concrete',
        'hidden': False,
        'grp': '',
    }


def _overhang(env: dict, bb) -> tuple:
    """(metres, side) the plan bbox leaves the envelope by; <= 0 means it fits."""
    return max(
        (env['xmin'] - bb[0], 'west'),
        (bb[2] - env['xmax'], 'east'),
        (env['zmin'] - bb[1], 'north'),
        (bb[3] - env['zmax'], 'south'),
    )
