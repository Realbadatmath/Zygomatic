# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / POSE — what the creature is DOING, and what its body does with the ground.

Moved verbatim out of the old single-file creature_fx.py (lines 2243-2499).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _edit, _pick, b, e, s


# ══ SIDE · POSE ═════════════════════════════════════════════════════════════
# What the creature is DOING. Pose is the op most likely to fight the framing:
# a leaping creature does not fit a portrait crop, so several of these say what
# the body does with the ground as well.

_edit(
    'cp_stance',
    'Stance',
    'Pose',
    'Stance — the resting pose. This is the one a reference sheet should be in: a '
    'standing creature is measurable, a leaping one is a drawing.',
    '<circle cx="12" cy="4.6" r="2.2"/><path d="M12 6.8v6.6"/>'
    '<path d="M12 13.4l-3.4 6.6M12 13.4l3.4 6.6"/><path d="M8.6 9.4h6.8"/>',
    [
        e(
            'v',
            'Stance',
            'standing',
            [
                'standing square',
                'sitting',
                'crouched',
                'lying down',
                'curled up',
                'rearing',
                'coiled',
                'perched',
                'hanging',
                'floating',
            ],
        )
    ],
    fn=lambda p, x: f'the creature is {p["v"]}, whole body in frame, feet included',
)

_edit(
    'cp_action',
    'Action',
    'Pose',
    'Action — mid-motion. Costs you the clean silhouette a sheet wants, which is why '
    'it is a separate op from Stance rather than another word in the same list.',
    '<circle cx="8.6" cy="4.6" r="2.2"/><path d="M8.6 6.8l3 4 4.4 1"/>'
    '<path d="M11.6 10.8l-1.4 4.4 3.4 4.8M10.2 15.2l-4.6 1.4"/>',
    [
        e(
            'v',
            'Action',
            'none',
            [
                'none',
                'walking',
                'running',
                'leaping',
                'flying',
                'swimming',
                'digging',
                'climbing',
                'striking',
                'eating',
                'calling out',
                'shaking itself off',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'the creature is {p["v"]}',
)

_edit(
    'cp_head',
    'Head turn',
    'Pose',
    'Head turn — where the head points relative to the body. Independent of the camera '
    'angle, and the difference between a creature looking AT you and one that happens '
    'to be facing you.',
    '<circle cx="12" cy="12" r="3.4"/><path d="M12 8.6V4.4"/>'
    '<path d="M15.4 12h4.2M8.6 12H4.4"/><path d="M17.4 9.6l2.2 2.4-2.2 2.4"/>',
    [
        e(
            'v',
            'Head',
            'forward',
            [
                'forward',
                'turned to one side',
                'looking back over the shoulder',
                'raised',
                'lowered',
                'cocked to one side',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'forward' else f'the head is {p["v"]}',
)

_edit(
    'cp_gaze',
    'Gaze',
    'Pose',
    'Gaze — where the eyes go. Straight to camera is a portrait; away is a scene. It '
    'also decides whether the eyes catch the key light at all.',
    '<path d="M2.6 12s3.4-5.4 9.4-5.4S21.4 12 21.4 12s-3.4 5.4-9.4 5.4S2.6 12 2.6 12z"/>'
    '<circle cx="14" cy="12" r="2.6"/>',
    [
        e(
            'v',
            'Looking',
            'at the camera',
            [
                'at the camera',
                'away from the camera',
                'off to one side',
                'upward',
                'downward',
                'at something out of frame',
            ],
        )
    ],
    fn=lambda p, x: f'looking {p["v"]}',
)

_edit(
    'cp_tailpose',
    'Tail pose',
    'Pose',
    'Tail pose — where the tail is held. On the animals that have one this carries as '
    'much mood as the face, and a sheet that never fixes it gets a different tail per '
    'cell.',
    '<path d="M4.6 18.6c4.4 0 6.8-2 8-5.4"/><path d="M12.6 13.2c1-3 3.4-4.6 6.8-4.6"/>'
    '<path d="M19.4 8.6l-2.4-2M19.4 8.6l-2.6 2"/>',
    [
        e(
            'v',
            'Tail',
            'relaxed',
            [
                'relaxed',
                'raised high',
                'tucked under',
                'curled over the back',
                'lashing',
                'wrapped around the feet',
                'straight out behind',
            ],
        )
    ],
    fn=lambda p, x: f'the tail is {p["v"]}',
)

_edit(
    'cp_limbpose',
    'Limb pose',
    'Pose',
    'Limb pose — what the front limbs are doing while the body does something else. The '
    'op that keeps a standing creature from looking like a taxidermy mount.',
    '<circle cx="12" cy="4.6" r="2"/><path d="M12 6.6v6"/>'
    '<path d="M12 8.6L6.6 6.4M12 8.6l5.4-2.2"/><path d="M12 12.6l-2.6 7.4M12 12.6l2.6 7.4"/>',
    [
        e(
            'v',
            'Front limbs',
            'at rest',
            [
                'at rest',
                'one raised',
                'both reaching forward',
                'crossed',
                'gripping something',
                'braced wide',
                'tucked against the chest',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'at rest' else f'the front limbs are {p["v"]}',
)

_edit(
    'cp_weight',
    'Weight',
    'Pose',
    'Weight — how the mass sits over the feet. A creature that reads weightless is the '
    'commonest tell that an image was generated rather than observed.',
    '<path d="M12 3.6v3.4"/><path d="M4.4 7h15.2"/><path d="M7.4 7l-3 6.4h6z"/>'
    '<path d="M16.6 7l-3 6.4h6z"/><path d="M9.4 20.4h5.2"/><path d="M12 7v13.4"/>',
    [
        e(
            'v',
            'Weight',
            'even',
            [
                'even',
                'shifted onto the front limbs',
                'shifted back',
                'on one side',
                'lifted, barely touching the ground',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'even' else f'its weight is {p["v"]}',
)

_edit(
    'cp_ground',
    'Ground contact',
    'Pose',
    'Ground contact — whether the feet actually meet a surface, and what that surface '
    'does about it. Contact shadows and depressed ground are what sell the weight.',
    '<path d="M3.6 17.4h16.8"/><path d="M8 17.4c0-1.6 1.4-2.6 4-2.6s4 1 4 2.6"/><path d="M6 20.4c2.4-1 9.6-1 12 0"/>',
    [
        e(
            'v',
            'Contact',
            'standing on the ground',
            [
                'standing on the ground',
                'floating just above it',
                'sunk into soft ground',
                'gripping a branch',
                'half in water',
                'on a rock',
            ],
        ),
        b('shadow', 'Contact shadow', True),
    ],
    fn=lambda p, x: f'{p["v"]}' + (', with a contact shadow where it touches' if p['shadow'] else ''),
)

_edit(
    'cp_interact',
    'Interaction',
    'Pose',
    'Interaction — a prop it is touching. One object only: a second creature or a '
    'person makes the cell a two-subject frame and the judge fails it by design.',
    '<circle cx="8" cy="8.6" r="3.4"/><rect x="13.4" y="12.4" width="7" height="7" rx="1.6"/>'
    '<path d="M10.4 11l3.4 2.4"/>',
    [s('v', 'Touching', '', 'e.g. holding a glowing fruit in both front paws')],
    fn=lambda p, x: f'{p["v"]}, and nothing else in frame' if _pick(p) else '',
    neg='people, second creature',
)

_edit(
    'cp_sym',
    'Pose symmetry',
    'Pose',
    'Pose symmetry — a locked-off symmetrical pose for a reference plate, or a natural '
    'asymmetric one for a beauty shot. A sheet wants the first; a poster wants the '
    'second.',
    '<path d="M12 3.6v16.8" stroke-dasharray="2.4 2.4"/>'
    '<path d="M9.6 7.4L5.4 12l4.2 4.6"/><path d="M14.4 7.4L18.6 12l-4.2 4.6"/>',
    [b('sym', 'Locked symmetrical', True)],
    fn=lambda p, x: (
        'a locked-off symmetrical reference pose, square to the camera'
        if p['sym']
        else 'a natural, relaxed asymmetric pose'
    ),
)
