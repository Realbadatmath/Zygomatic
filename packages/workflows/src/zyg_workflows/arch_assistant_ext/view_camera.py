# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""view_camera — the assistant half of the camera/animation icons.

No kinds and no drawing tools: this family only declares which icons of
arch_ext/view_camera.js the model may press through
view_scene_ops.press_button, and says in one prompt paragraph what arguments
each of them takes. The tab accepts a press only because every one of those
registrations carries `assist: 1` — both sides must agree.

Icons: v_2pt (two-point perspective), v_turntable (360 degree orbit to WebM),
v_walkpath (record/stop/play a camera route), r_anim (walk path or sun sweep
rendered to one WebM).

Standard library only; no package was added.
"""

from __future__ import annotations

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['v_2pt', 'v_turntable', 'v_walkpath', 'r_anim']

PROMPT = (
    'Camera and animation icons (press_button, viewport effects — they draw nothing): '
    'press_button("v_2pt", {"on": true|false}) switches two-point perspective on or off — the camera '
    'is levelled and the lens shifted, so verticals stay vertical and the framing does not move '
    '(leave the args out to toggle); '
    'press_button("v_turntable", {"seconds": 8, "fps": 24, "res": 1280}) orbits the camera 360 degrees '
    'around what it is looking at and downloads the orbit as one WebM; '
    'press_button("v_walkpath", {"mode": "record"|"stop"|"play"|"clear"}) records a camera route '
    '(a key every 250 ms, up to 600, kept in the drawing), stops it, or flies the camera along it — '
    'leave the args out to cycle record then stop then play; '
    'press_button("r_anim", {"res": 1280, "fps": 24, "seconds": 8, "mode": "path"|"sun"}) renders the '
    'recorded walk path, or without one a 06:00 to 20:00 sun sweep, into one WebM and downloads it '
    '(the settings are remembered in the drawing). Recording takes real time: an 8 second turntable '
    'takes 8 seconds, so say so before you press it.'
)

TOOLS: list = []

EXAMPLES = [
    {
        'ask': 'keep the verticals straight, this is an architectural view',
        'calls': [{'tool': 'press_button', 'args': {'id': 'v_2pt', 'args': {'on': True}}}],
    },
    {
        'ask': 'spin it round for me and give me a video',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'v_iso'}},
            {'tool': 'press_button', 'args': {'id': 'v_turntable', 'args': {'seconds': 8, 'fps': 24, 'res': 1280}}},
        ],
    },
    {
        'ask': 'record a walk through the house',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'v_walkpath', 'args': {'mode': 'record'}}},
            {'tool': 'say', 'args': {'text': 'Recording — move the camera, then tell me to stop.'}},
        ],
    },
    {
        'ask': 'stop recording and play it back',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'v_walkpath', 'args': {'mode': 'stop'}}},
            {'tool': 'press_button', 'args': {'id': 'v_walkpath', 'args': {'mode': 'play'}}},
        ],
    },
    {
        'ask': 'render that walk out as a film, 1920 wide',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_anim', 'args': {'res': 1920, 'fps': 24, 'mode': 'path'}}}],
    },
    {
        'ask': 'show me the light moving across the building through the day',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'r_anim', 'args': {'mode': 'sun', 'seconds': 10, 'res': 1280}}}
        ],
    },
]
