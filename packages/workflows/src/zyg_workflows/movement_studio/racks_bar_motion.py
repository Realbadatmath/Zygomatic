# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.racks_bar_motion — PARAMETER SPEC header and the first
three bar racks (motion, space, body)."""

# ══════════════════════════════════════════════════════════════════════════
# PARAMETER SPEC
# place: 'bar'  → bottom icon bar       (what the movement IS — with the library)
#        'rail' → right-hand icon rail  (how it is computed and finished)
# Swapped 2026-09-02 on request: the movement dials went to the foot, the
# engine/finish/gate dials to the right-hand rail.
# Every param carries its own `icon` (a symbol id in the page's mv- sprite).
# `lb` is the SHORT caption printed under that icon; `label` is the full name the
# popover header and the hover card use. They are separate because a 58px cell
# ellipsises anything past ~12 characters, and "Shift (motion amount)" rendered
# as "Shift (moti…" is a worse label than "Shift" with the full name one hover
# away. A param with no `lb` has a label that already fits.
# ══════════════════════════════════════════════════════════════════════════
_RACKS_BAR_MOTION = [
    # ══════════════════════════════════ BAR — the movement itself
    {
        'id': 'motion',
        'title': 'MOTION',
        'icon': 'mv-motion',
        'place': 'bar',
        'sub': 'How the chosen action is performed. Every dial here becomes a clause '
        'in the motion sentence compose_prompt() builds.',
        'params': [
            {
                'key': 'speed',
                'type': 'select',
                'label': 'Speed',
                'def': 'natural',
                'icon': 'mv-speed',
                'options': [{'v': k, 'l': k} for k in ('natural', 'very slow', 'slow', 'brisk', 'fast', 'frantic')],
                'hint': 'How fast the action runs. This is a PROMPT token — the frame count '
                'is unchanged, so a faster action simply completes earlier in the clip.',
            },
            {
                'key': 'intensity',
                'type': 'select',
                'label': 'Intensity',
                'def': 'natural',
                'icon': 'mv-intensity',
                'options': [{'v': k, 'l': k} for k in ('natural', 'minimal', 'subtle', 'strong', 'extreme')],
                'hint': 'How hard the movement is committed to. Pair with Shift on the bottom '
                'bar — this changes what is asked for, Shift changes how much the '
                'model is willing to move at all.',
            },
            {
                'key': 'amplitude',
                'type': 'select',
                'label': 'Range of motion',
                'lb': 'Range',
                'def': 'natural',
                'icon': 'mv-amplitude',
                'options': [
                    {'v': k, 'l': k} for k in ('natural', 'tight and contained', 'wide and open', 'exaggerated')
                ],
                'hint': 'How far the limbs travel through the action, independent of speed.',
            },
            {
                'key': 'style',
                'type': 'select',
                'label': 'Motion style',
                'def': 'natural',
                'icon': 'mv-style',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'graceful',
                        'heavy and weighted',
                        'light and floating',
                        'mechanical',
                        'jerky',
                        'fluid',
                        'animated and exaggerated',
                    )
                ],
                'hint': 'The character of the movement — the difference between a walk and '
                'the same walk performed by something heavy.',
            },
            {
                'key': 'easing',
                'type': 'select',
                'label': 'Easing',
                'def': 'none',
                'icon': 'mv-easing',
                'options': [
                    {'v': 'none', 'l': 'none — even throughout'},
                    {'v': 'in', 'l': 'ease in — starts slow, builds'},
                    {'v': 'out', 'l': 'ease out — decelerates into the end'},
                    {'v': 'both', 'l': 'ease both — slow at both ends'},
                    {'v': 'snap', 'l': 'snap — sudden, then settles'},
                ],
                'hint': 'The speed curve across the clip.',
            },
            {
                'key': 'repeat',
                'type': 'select',
                'label': 'Repetition',
                'def': 'once',
                'icon': 'mv-repeat',
                'options': [
                    {'v': 'once', 'l': 'once'},
                    {'v': 'twice', 'l': 'twice'},
                    {'v': 'three', 'l': 'three times'},
                    {'v': 'loop', 'l': 'continuously, cyclically'},
                ],
                'hint': 'How many times the action runs inside the clip. "continuously" is what '
                'a walk or a wave wants; a fall wants "once".',
            },
            {
                'key': 'hold_start',
                'type': 'select',
                'label': 'Hold before',
                'def': 'none',
                'icon': 'mv-holdstart',
                'options': [
                    {'v': 'none', 'l': 'none — starts immediately'},
                    {'v': 'beat', 'l': 'a beat of stillness first'},
                    {'v': 'long', 'l': 'holds still, then moves'},
                ],
                'hint': 'Dead air at the head of the clip. Useful when the clip has to be cut '
                'to land on a narration cue rather than on frame 1.',
            },
            {
                'key': 'hold_end',
                'type': 'select',
                'label': 'Hold after',
                'def': 'none',
                'icon': 'mv-holdend',
                'options': [
                    {'v': 'none', 'l': 'none — ends on the motion'},
                    {'v': 'beat', 'l': 'settles and holds a beat'},
                    {'v': 'long', 'l': 'holds the final pose'},
                ],
                'hint': 'Whether the clip ends on the action or on a held pose. A held pose is '
                'what makes a clip cuttable at the tail.',
            },
            {
                'key': 'anticipation',
                'type': 'toggle',
                'label': 'Anticipation',
                'def': False,
                'icon': 'mv-antic',
                'hint': 'Adds a small wind-up in the opposite direction before the action — the '
                'animation principle. Reads as intent rather than teleporting.',
            },
            {
                'key': 'follow_through',
                'type': 'toggle',
                'label': 'Follow through',
                'lb': 'Follow-thru',
                'def': False,
                'icon': 'mv-follow',
                'hint': 'Lets the limbs and loose parts overshoot and settle after the action '
                'stops, instead of everything arriving at once.',
            },
            {
                'key': 'idle_layer',
                'type': 'toggle',
                'label': 'Idle layer',
                'def': True,
                'icon': 'mv-idlelayer',
                'hint': 'Keeps breathing and small weight shifts running underneath the action. '
                'Off, a subject that finishes its action goes completely dead.',
            },
            {
                'key': 'secondary',
                'type': 'toggle',
                'label': 'Secondary motion',
                'lb': 'Secondary',
                'def': True,
                'icon': 'mv-secondary',
                'hint': 'Hair, cloth, tails and loose parts trailing the body. The single '
                'cheapest token for making a clip stop looking like a moving photo.',
            },
        ],
    },
    {
        'id': 'space',
        'title': 'SPACE',
        'icon': 'mv-space',
        'place': 'bar',
        'sub': 'Where the movement goes. The camera is locked off by construction — '
        'these move the SUBJECT through a fixed frame.',
        'params': [
            {
                'key': 'direction',
                'type': 'select',
                'label': 'Direction',
                'def': 'in place',
                'icon': 'mv-direction',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'in place',
                        'toward the camera',
                        'away from the camera',
                        'to the left',
                        'to the right',
                        'diagonally forward-left',
                        'diagonally forward-right',
                        'in a circle',
                        'upward',
                        'downward',
                    )
                ],
                'hint': 'Where the subject travels within the locked frame.',
            },
            {
                'key': 'distance',
                'type': 'select',
                'label': 'Distance',
                'def': 'natural',
                'icon': 'mv-distance',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'on the spot',
                        'a single step',
                        'a few steps',
                        'across the frame',
                        'out of frame',
                    )
                ],
                'hint': 'How far it gets. "out of frame" is the one that gives you a clean exit to cut on.',
            },
            {
                'key': 'facing',
                'type': 'select',
                'label': 'Facing',
                'def': 'unchanged',
                'icon': 'mv-facing',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'unchanged',
                        'facing the camera',
                        'turning to profile',
                        'turning three-quarter',
                        'turning away from the camera',
                    )
                ],
                'hint': 'Which way the body ends up pointing. A change of facing is the most '
                'expensive thing to ask of a single still — check it on a probe first.',
            },
            {
                'key': 'scale_change',
                'type': 'select',
                'label': 'Scale in frame',
                'lb': 'Scale',
                'def': 'unchanged',
                'icon': 'mv-scale',
                'options': [
                    {'v': 'unchanged', 'l': 'unchanged — holds its size'},
                    {'v': 'larger', 'l': 'grows larger in frame'},
                    {'v': 'smaller', 'l': 'shrinks in frame'},
                ],
                'hint': 'Perspective change from the subject moving, not from a zoom. The '
                'camera cannot move here, so this is the only route to a size change.',
            },
            {
                'key': 'ground',
                'type': 'select',
                'label': 'Ground contact',
                'lb': 'Ground',
                'def': 'natural',
                'icon': 'mv-ground',
                'options': [
                    {'v': k, 'l': k}
                    for k in ('natural', 'feet planted', 'full walking cycle', 'one foot lifted', 'airborne', 'sliding')
                ],
                'hint': 'What the feet do. "feet planted" is the fix for a subject that slides '
                'across the ground instead of walking on it.',
            },
            {
                'key': 'environment',
                'type': 'text',
                'label': 'Environment note',
                'lb': 'Environment',
                'def': '',
                'icon': 'mv-environ',
                'hint': 'Free text about what the subject is moving through — "waist-deep in '
                'snow", "on a heaving deck". The set itself comes from the still and '
                'is pinned; this only changes how the subject moves within it.',
            },
        ],
    },
    {
        'id': 'body',
        'title': 'BODY',
        'icon': 'mv-body',
        'place': 'bar',
        'sub': 'Which parts move and what they do. Every one of these is a clause appended to the motion sentence.',
        'params': [
            {
                'key': 'lead',
                'type': 'select',
                'label': 'Leading part',
                'def': 'natural',
                'icon': 'mv-lead',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'the head',
                        'the chest',
                        'the hips',
                        'the left arm',
                        'the right arm',
                        'both arms',
                        'the left leg',
                        'the right leg',
                        'the tail',
                        'the wings',
                    )
                ],
                'hint': 'Which part initiates the movement and the rest follows.',
            },
            {
                'key': 'head',
                'type': 'select',
                'label': 'Head',
                'def': 'natural',
                'icon': 'mv-head',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'held still',
                        'turning',
                        'nodding',
                        'shaking',
                        'tilting',
                        'tracking something',
                        'thrown back',
                    )
                ],
                'hint': 'What the head does independently of the body.',
            },
            {
                'key': 'gaze',
                'type': 'select',
                'label': 'Gaze',
                'def': 'natural',
                'icon': 'mv-gaze',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'straight at the camera',
                        'off to the left',
                        'off to the right',
                        'upward',
                        'downward',
                        'following the movement',
                        'eyes closed',
                        'eyes wide open',
                    )
                ],
                'hint': 'Where the eyes go. The eyelid metric this project measures is governed '
                'by the control plate, not by this — but the gaze direction is real.',
            },
            {
                'key': 'expression',
                'type': 'select',
                'label': 'Expression',
                'def': 'unchanged',
                'icon': 'mv-expr',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'unchanged',
                        'neutral',
                        'smiling',
                        'laughing',
                        'worried',
                        'afraid',
                        'angry',
                        'sad',
                        'surprised',
                        'determined',
                        'exhausted',
                        'disgusted',
                    )
                ],
                'hint': '"unchanged" keeps whatever the still already shows — which is the safe '
                'answer, because asking for a new expression asks the model to redraw '
                'the face and identity drift starts there.',
            },
            {
                'key': 'mouth',
                'type': 'select',
                'label': 'Mouth',
                'def': 'unchanged',
                'icon': 'mv-mouth',
                'options': [
                    {'v': k, 'l': k} for k in ('unchanged', 'closed', 'speaking', 'open', 'breathing hard', 'shouting')
                ],
                'hint': 'Separate from expression because a talking clip needs the mouth moving '
                'and the expression left exactly as it was.',
            },
            {
                'key': 'hands',
                'type': 'select',
                'label': 'Hands',
                'def': 'natural',
                'icon': 'mv-hands',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'relaxed at the sides',
                        'gesturing',
                        'clenched',
                        'open palms',
                        'holding something',
                        'hidden from view',
                    )
                ],
                'hint': '"hidden from view" is the honest fix when hands come out melted — this '
                'project measured that the VLM hand judge scores melted hands as fine, '
                'so not drawing them beats trusting a gate to catch them.',
            },
            {
                'key': 'posture',
                'type': 'select',
                'label': 'Posture',
                'def': 'natural',
                'icon': 'mv-posture',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'natural',
                        'upright',
                        'hunched',
                        'leaning forward',
                        'leaning back',
                        'slouched',
                        'coiled and ready',
                        'sagging',
                    )
                ],
                'hint': 'The line of the spine through the whole action.',
            },
            {
                'key': 'breathing',
                'type': 'select',
                'label': 'Breathing',
                'def': 'natural',
                'icon': 'mv-breath',
                'options': [
                    {'v': k, 'l': k} for k in ('natural', 'none visible', 'subtle', 'visible', 'heavy', 'ragged')
                ],
                'hint': 'The chest movement underneath everything else.',
            },
            {
                'key': 'weight',
                'type': 'select',
                'label': 'Weight',
                'def': 'natural',
                'icon': 'mv-weight',
                'options': [
                    {'v': k, 'l': k}
                    for k in ('natural', 'light-footed', 'heavy and grounded', 'top-heavy', 'weightless')
                ],
                'hint': 'How much mass the movement reads as carrying.',
            },
            {
                'key': 'mood',
                'type': 'select',
                'label': 'Mood',
                'def': 'unchanged',
                'icon': 'mv-mood',
                'options': [
                    {'v': k, 'l': k}
                    for k in (
                        'unchanged',
                        'calm',
                        'cheerful',
                        'tense',
                        'urgent',
                        'weary',
                        'menacing',
                        'playful',
                        'grief-stricken',
                        'triumphant',
                    )
                ],
                'hint': 'The emotional read of the whole performance, as distinct from the expression on the face.',
            },
        ],
    },
]
