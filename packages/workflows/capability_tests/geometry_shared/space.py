# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.space — Space & relation: measured in the BUILD's own frame, from bounding boxes.

Verbatim from the former geometry_shared.py, lines 1613-1831.
"""

from __future__ import annotations

from .builds_capacity import PROBES, _op, _probe

# ── Space & relation: measured in the BUILD's own frame, from bounding boxes ────────────────
# Not from a picture. "Left" is -X with the subject's front facing -Z, which the export contract
# fixes; a build that comes out mirrored fails, and that is the honest answer.
SPACE_NOTE = (
    "Every relation is read off the exported GLB's bounding boxes with the export contract's "
    "axes (+Y up, front towards -Z, so the viewer's left is -X). No render is consulted: a "
    "picture can be flipped, a GLB cannot. The operator's blind question is a second opinion on "
    'the same sheet and both must pass. A build whose objects fused into one shell cannot answer a '
    'relation at all and is a no.'
)


def _space(pid, col, prompt, relation_checks, question, shells=(2, 12)):
    return _probe(
        pid,
        f'space: {col[3:].replace("_", " ")}',
        [col],
        [{'check': 'mesh_shell_count', 'min': shells[0], 'max': shells[1], 'when': 'glb'}]
        + relation_checks
        + [_op(question)],
        {'prompt': prompt},
        space_note=SPACE_NOTE,
    )


PROBES += [
    _space(
        'geo_sp_left_right',
        'sp_left_right',
        'A wooden door standing upright with one oak barrel on the ground to the left of it, one '
        'metre away. Door and barrel separate, nothing else.',
        [
            {
                'check': 'bbox_relation',
                'a': 'barrel',
                'b': 'door',
                'relation': 'left_of',
                'tolerance': 0.05,
                'when': 'glb',
            }
        ],
        'Is the barrel to the LEFT of the door as you face the front view? yes/no',
    ),
    _space(
        'geo_sp_front_behind',
        'sp_front_behind',
        'A wooden door standing upright with one oak barrel one metre in front of it, on the side '
        'the door opens towards. Door and barrel separate, nothing else.',
        [
            {
                'check': 'bbox_relation',
                'a': 'barrel',
                'b': 'door',
                'relation': 'in_front_of',
                'tolerance': 0.05,
                'when': 'glb',
            }
        ],
        'Is the barrel IN FRONT OF the door, between the door and the viewer? yes/no',
    ),
    _space(
        'geo_sp_on_under',
        'sp_on_under',
        'An oak table with one pewter plate standing on the tabletop and one leather boot on the '
        'floor under the table. Table, plate and boot separate, nothing else.',
        [
            {
                'check': 'bbox_relation',
                'a': 'plate',
                'b': 'table',
                'relation': 'above',
                'tolerance': 0.02,
                'when': 'glb',
            },
            {
                'check': 'bbox_relation',
                'a': 'boot',
                'b': 'table',
                'relation': 'below',
                'tolerance': 0.02,
                'when': 'glb',
            },
        ],
        'Is the plate ON the tabletop and the boot UNDER the table? Both must be true. yes/no',
        shells=(3, 30),
    ),
    _space(
        'geo_sp_inside',
        'sp_inside',
        'An open wooden crate with three apples lying inside it, below the rim, and nothing outside '
        'the crate. Crate and each apple separate.',
        [
            {
                'check': 'bbox_relation',
                'a': 'apple',
                'b': 'crate',
                'relation': 'inside',
                'tolerance': 0.01,
                'when': 'glb',
            }
        ],
        'Are all three apples INSIDE the crate, below its rim? yes/no',
        shells=(4, 20),
    ),
    _space(
        'geo_sp_near_far',
        'sp_near_far',
        'A stone bollard with one oak barrel touching its side and a second oak barrel five metres '
        'away on the same flat ground. Bollard and both barrels separate.',
        [
            {
                'check': 'bbox_relation',
                'a': 'barrel_near',
                'b': 'bollard',
                'relation': 'touching',
                'tolerance': 0.03,
                'when': 'glb',
            },
            {
                'check': 'bbox_relation',
                'a': 'barrel_far',
                'b': 'bollard',
                'relation': 'apart',
                'tolerance': 4.0,
                'when': 'glb',
            },
        ],
        'Is one barrel right against the bollard and the other several metres away? yes/no',
        shells=(3, 30),
    ),
    _space(
        'geo_sp_touching',
        'sp_touching',
        'Two oak barrels standing upright on flat ground with their sides pressed together, '
        'touching along one line. Two separate barrels, nothing else.',
        [
            {
                'check': 'bbox_relation',
                'a': 'barrel_a',
                'b': 'barrel_b',
                'relation': 'touching',
                'tolerance': 0.02,
                'when': 'glb',
            },
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
        ],
        'Are the two barrels touching each other, and still two whole barrels rather than one merged lump? yes/no',
        shells=(2, 30),
    ),
    _space(
        'geo_sp_holding_who',
        'sp_holding_who',
        'Two standing adults one metre apart, the LEFT one holding a lantern in her hand and the '
        'right one holding nothing. Figures and lantern separate.',
        [
            {
                'check': 'bbox_relation',
                'a': 'lantern',
                'b': 'figure_left',
                'relation': 'touching',
                'tolerance': 0.05,
                'when': 'glb',
            },
            {
                'check': 'bbox_relation',
                'a': 'lantern',
                'b': 'figure_right',
                'relation': 'apart',
                'tolerance': 0.3,
                'when': 'glb',
            },
        ],
        'Is the lantern in the hand of the LEFT figure, and is the right figure empty-handed? yes/no',
        shells=(3, 30),
    ),
    _space(
        'geo_sp_relative_size',
        'sp_relative_size',
        "One standing adult beside one oak barrel, the barrel reaching the adult's waist. Figure "
        'and barrel separate, nothing else.',
        [
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 1.55, 'max': 2.00, 'when': 'glb'},
            {'check': 'shell_volume_ratio', 'a': 'figure', 'b': 'barrel', 'min': 0.5, 'max': 4.0, 'when': 'glb'},
        ],
        "Does the barrel come up to about the person's waist — neither a toy nor taller than they are? yes/no",
        shells=(2, 20),
    ),
    _space(
        'geo_sp_occlusion',
        'sp_occlusion',
        'A brick wall two metres tall with one standing adult directly behind it, only the head and '
        'shoulders above the wall. Wall and figure separate.',
        [
            {
                'check': 'bbox_relation',
                'a': 'figure',
                'b': 'wall',
                'relation': 'behind',
                'tolerance': 0.05,
                'when': 'glb',
            },
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
        ],
        'Is the person standing BEHIND the wall with only head and shoulders showing — and is the '
        'whole body still built, not cut off where the wall hides it? yes/no',
        shells=(2, 200),
    ),
    _space(
        'geo_sp_direction',
        'sp_direction',
        'One horse standing on flat ground facing left, seen from its right side, all four legs on '
        'the ground. One animal, nothing else.',
        [{'check': 'bbox_facing', 'heading': 270, 'tolerance': 25, 'when': 'glb'}],
        'Is the horse facing to the LEFT? yes/no',
        shells=(1, 20),
    ),
]
