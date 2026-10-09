# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / CAMERA — where the camera moves, the 16 mesh views and the words for them.

Moved verbatim out of the old single-file creature_fx.py (lines 2500-2765).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, e, f


# ══ SIDE · CAMERA ═══════════════════════════════════════════════════════════
# Phrasing here follows what the sheet pipeline learned the hard way: say where
# the CAMERA MOVES, pin the subject upright, and never say "tilt" -- frames came
# back upside down. Camera ops are also the only ops the multiple-angles LoRA is
# for, so they raise its strength for the render ([[creature_sheet_service]]).

_edit(
    'cm_view',
    'View angle',
    'Camera',
    'View angle — where the camera stands. The angles LoRA runs at full strength for '
    'this op because creatures measurably UNDER-rotate: "side profile" came back as '
    'three-quarter on 6 of 16 pufferball cells at the graph default.',
    '<circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="8.6" stroke-dasharray="2.6 3"/>'
    '<path d="M12 3.4l2 2.2-2 2.2"/>',
    [
        e(
            'v',
            'Camera',
            'front',
            [
                'front',
                'three-quarter left',
                'three-quarter right',
                'left profile',
                'right profile',
                'rear three-quarter',
                'directly behind',
                'from above',
                'from below',
            ],
        )
    ],
    fn=lambda p, x: (
        (
            'move the camera to a front view of the creature, facing the camera'
            if p['v'] == 'front'
            else f'move the camera to a {p["v"]} view of the creature'
        )
        + ', the creature standing upright, whole body in frame'
    ),
)

# The 16 view ids prop_mesh/sheet_render.py writes, and the only ones a registered
# mesh can supply a depth map for. Kept as the RAW ids rather than prose labels so the
# picker and the sheet cannot drift: the value chosen here is looked up in the asset's
# own view list, and a pretty synonym would fail that lookup silently.
_MESH_VIEWS = [
    'front_full',
    'q45_left',
    'q45_right',
    'side_left',
    'side_right',
    'back_q_left',
    'back_q_right',
    'back',
    'high_front',
    'low_front',
    'top_down',
    'close_front',
    'close_q_left',
    'close_q_right',
    'wide',
    'detail',
]

# The same viewpoint said in English. The depth map carries the geometry, but the
# instruction is still read: a text that says nothing about the camera while the
# control image says "from directly above" is two conditioning signals, one of which
# is silent, and the silent one is the text encoder's prior.
_MESH_VIEW_WORDS = {
    'front_full': 'a front view of the creature, facing the camera',
    'q45_left': "a three-quarter view from the creature's left",
    'q45_right': "a three-quarter view from the creature's right",
    'side_left': 'a left profile view',
    'side_right': 'a right profile view',
    'back_q_left': "a rear three-quarter view from the creature's left",
    'back_q_right': "a rear three-quarter view from the creature's right",
    'back': 'a view from directly behind the creature',
    'high_front': 'a high front view, the camera looking down at the creature',
    'low_front': 'a low front view, the camera looking up at the creature',
    'top_down': 'a view from directly above, looking straight down',
    'close_front': 'a close front view of the head',
    'close_q_left': "a close three-quarter view of the head from the creature's left",
    'close_q_right': "a close three-quarter view of the head from the creature's right",
    'wide': 'a wide view with the creature small in frame',
    'detail': 'a tight detail view of the creature',
}


_edit(
    'cm_mesh',
    'Mesh view',
    'Camera',
    'Mesh view — the ONE op in this toolbox whose viewpoint is measured rather than '
    'described. When this creature has a registered 3D mesh, the chosen angle is '
    'taken from that mesh as a TRUE Cycles depth pass and handed to the model as '
    'image2, so the geometry is conditioned instead of suggested. The angles LoRA is '
    'forced to 0 for the render: a depth map and a camera-rotation adapter are two '
    'signals fighting over the same thing. Without a registered mesh this op is a '
    'plain wording change and the job log says so — it does not silently pretend.',
    '<path d="M12 3.4l7.4 4.3v8.6L12 20.6l-7.4-4.3V7.7z"/><path d="M12 3.4v17.2M4.6 7.7L12 12l7.4-4.3"/>',
    [
        e(
            'v',
            'Angle',
            'front_full',
            _MESH_VIEWS,
            "A view id from the registered sheet. It is looked up in the asset's own "
            'view list, so an angle the mesh was never rendered at is refused with the '
            'list of the ones it has.',
        )
    ],
    fn=lambda p, x: (
        'move the camera to '
        + _MESH_VIEW_WORDS.get(p['v'], p['v'].replace('_', ' '))
        + ', matching the supplied depth reference exactly, '
        'the creature standing upright'
    ),
)

_edit(
    'cm_elev',
    'Elevation',
    'Camera',
    'Elevation — camera height. Low reads heroic and large; high reads small and '
    'vulnerable. Said as a camera move, never as "tilt".',
    '<path d="M3.6 19.4h16.8"/><path d="M6.6 19.4L17 6.6"/>'
    '<circle cx="18" cy="5.4" r="2.4"/><path d="M11 12.4l1.4 3"/>',
    [
        e(
            'v',
            'Height',
            'eye level',
            [
                'eye level',
                'slightly low',
                'low, looking up',
                'slightly high',
                'high, looking down',
                'directly overhead',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'eye level' else f'move the camera to {p["v"]}',
)

_edit(
    'cm_dist',
    'Framing',
    'Camera',
    'Framing — how much of the creature is in shot. A close framing is the only way to '
    'get face detail at 1024, and the only framing where the body plan cannot be '
    'checked. The sheet uses both for that reason.',
    '<path d="M4.4 4.4h5M4.4 4.4v5M19.6 4.4h-5M19.6 4.4v5M4.4 19.6h5M4.4 19.6v-5'
    'M19.6 19.6h-5M19.6 19.6v-5"/><circle cx="12" cy="12" r="3"/>',
    [
        e(
            'v',
            'Shot',
            'full body',
            [
                'full body',
                'wide, creature small in frame',
                'three-quarter length',
                'head and shoulders',
                'head only',
                'macro detail',
            ],
        )
    ],
    fn=lambda p, x: f'frame it as a {p["v"]} shot',
)

_edit(
    'cm_lens',
    'Lens',
    'Camera',
    'Lens — focal length, which decides how much the near end of the creature is '
    'exaggerated. A 24mm muzzle and a 135mm muzzle are different shapes on the same '
    'skull.',
    '<circle cx="12" cy="12" r="7.6"/><circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 4.4v2.6M12 17v2.6M4.4 12H7M17 12h2.6"/>',
    [e('v', 'Lens', '85mm', ['24mm wide', '35mm', '50mm', '85mm', '135mm', '200mm long'])],
    fn=lambda p, x: f'shot on a {p["v"]} lens',
)

_edit(
    'cm_roll',
    'Roll',
    'Camera',
    'Roll — the horizon angle. Deliberately not called tilt: the sheet pipeline '
    'measured "tilt" coming back as an upside-down frame, so the word is banned from '
    'every instruction this studio writes.',
    '<path d="M4.4 15.6l15.2-7.2"/><circle cx="12" cy="12" r="8.6" stroke-dasharray="2.6 3"/>',
    [f('a', 'Degrees', 0, -45, 45, 1)],
    fn=lambda p, x: (
        f'roll the camera {abs(int(p["a"]))} degrees {"clockwise" if p["a"] > 0 else "anticlockwise"}'
        if abs(p['a']) >= 3
        else ''
    ),
)

_edit(
    'cm_centre',
    'Placement',
    'Camera',
    'Placement — where the creature sits in the frame. Centred is what a reference '
    'plate needs; off-centre is what a poster needs, and cropping later loses '
    'resolution the render could have spent on the subject.',
    '<rect x="3.6" y="5.4" width="16.8" height="13.2" rx="1.6"/>'
    '<circle cx="8.6" cy="12" r="2.6"/><path d="M12 5.4v13.2" stroke-dasharray="2 2.4"/>',
    [e('v', 'Placed', 'centred', ['centred', 'left of frame', 'right of frame', 'low in frame', 'high in frame'])],
    fn=lambda p, x: f'the creature {p["v"]} in the image',
)

_edit(
    'cm_margin',
    'Margin',
    'Camera',
    'Margin — how much empty space is left around the creature. Too little and the sheet '
    'cells clip feet and tail tips; the judge calls that "cut off" and it is the '
    'commonest false failure on an otherwise perfect cell.',
    '<rect x="2.6" y="4.4" width="18.8" height="15.2" rx="1.6" stroke-dasharray="2.4 2.4"/>'
    '<rect x="7" y="8.4" width="10" height="7.2" rx="1.2"/>',
    [f('v', 'Space around', 40, 0, 100, 1)],
    fn=lambda p, x: (
        f'leave {_amt(p["v"], ("a little", "clear", "generous", "a lot of"))} '
        f'empty space around the creature, nothing cropped'
        if _amt(p['v'])
        else 'fill the frame with the creature'
    ),
)

_edit(
    'cm_aspect',
    'Aspect',
    'Camera',
    'Aspect — the shape of the frame the model paints into. Square is what the sheet '
    'and the trainer buckets want; wide is what a scene plate wants.',
    '<rect x="3.4" y="7.4" width="17.2" height="9.2" rx="1.4"/>'
    '<rect x="7.4" y="4.4" width="9.2" height="15.2" rx="1.4" opacity=".55"/>',
    [e('v', 'Frame', 'square', ['square', 'portrait 3:4', 'landscape 4:3', 'widescreen 16:9', 'tall 9:16'])],
    fn=lambda p, x: f'compose it for a {p["v"]} frame',
)

_edit(
    'cm_dof',
    'Depth of field',
    'Camera',
    'Depth of field — how much falls out of focus behind the subject. A shallow one '
    'hides a background you did not want to design; it also softens the tail tip on a '
    'long creature, which the judge reads as missing.',
    '<circle cx="9" cy="12" r="5.4"/><circle cx="17" cy="12" r="3.4" stroke-dasharray="2 2.2"/>',
    [
        e(
            'v',
            'Depth',
            'deep, all sharp',
            ['deep, all sharp', 'slightly shallow', 'shallow, background soft', 'very shallow, only the eyes sharp'],
        )
    ],
    fn=lambda p, x: '' if p['v'].startswith('deep') else f'{p["v"]} depth of field',
)
