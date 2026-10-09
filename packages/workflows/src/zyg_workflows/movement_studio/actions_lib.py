# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.actions_lib — the movement library and action_prompt()."""

# ══════════════════════════════════════════════════════════════════════════
# THE ACTION LIBRARY — the movements themselves.
#
# Each entry is {id, label, icon, prompt, tags}. `prompt` is the base motion
# sentence; everything in RACKS modifies it. These are written in the third
# person present with no subject noun, because compose_prompt() puts the
# subject's own canon binding in front of them (bp_movement._start does the
# prepend) — "walks forward", never "the character walks forward", so a creature
# with four legs does not get called a character.
# ══════════════════════════════════════════════════════════════════════════
ACTIONS_LIB = [
    # ── stillness ──
    {
        'id': 'idle',
        'label': 'Idle / breathe',
        'lb': 'Idle',
        'icon': 'mv-idle',
        'grp': 'Still',
        'prompt': 'stands in a relaxed idle pose with subtle natural breathing motion '
        'and a small weight shift, otherwise still',
    },
    {
        'id': 'stand_alert',
        'label': 'Alert stand',
        'icon': 'mv-alert',
        'grp': 'Still',
        'prompt': 'stands alert and upright, weight forward, scanning ahead, only small settling movements',
    },
    {
        'id': 'brace',
        'label': 'Brace',
        'icon': 'mv-brace',
        'grp': 'Still',
        'prompt': 'braces, feet planted wide and shoulders set, holding against something',
    },
    {
        'id': 'sway',
        'label': 'Sway',
        'icon': 'mv-sway',
        'grp': 'Still',
        'prompt': 'sways gently from side to side, shifting weight between the feet',
    },
    {
        'id': 'shiver',
        'label': 'Shiver',
        'icon': 'mv-shiver',
        'grp': 'Still',
        'prompt': 'shivers, small rapid trembling through the shoulders and arms',
    },
    # ── locomotion ──
    {
        'id': 'walk',
        'label': 'Walk',
        'icon': 'mv-walk',
        'grp': 'Travel',
        'prompt': 'walks forward at a natural steady pace, a few full strides, arms swinging naturally',
    },
    {
        'id': 'run',
        'label': 'Run',
        'icon': 'mv-run',
        'grp': 'Travel',
        'prompt': 'runs forward at speed, full running gait, arms driving',
    },
    {
        'id': 'sneak',
        'label': 'Sneak',
        'icon': 'mv-sneak',
        'grp': 'Travel',
        'prompt': 'creeps forward slowly and carefully, low and quiet, placing each foot',
    },
    {
        'id': 'approach',
        'label': 'Approach camera',
        'lb': 'Approach',
        'icon': 'mv-approach',
        'grp': 'Travel',
        'prompt': 'walks slowly toward the camera, growing larger in frame, a natural steady gait',
    },
    {
        'id': 'retreat',
        'label': 'Walk away',
        'icon': 'mv-retreat',
        'grp': 'Travel',
        'prompt': 'walks away from the camera into the scene, growing smaller in frame',
    },
    {
        'id': 'pace',
        'label': 'Pace',
        'icon': 'mv-pace',
        'grp': 'Travel',
        'prompt': 'paces back and forth across the frame, turning at each end',
    },
    {
        'id': 'stagger',
        'label': 'Stagger',
        'icon': 'mv-stagger',
        'grp': 'Travel',
        'prompt': 'staggers unsteadily, catching balance between steps',
    },
    {
        'id': 'climb',
        'label': 'Climb',
        'icon': 'mv-climb',
        'grp': 'Travel',
        'prompt': 'climbs upward, reaching hand over hand and pulling the body up',
    },
    {
        'id': 'swim',
        'label': 'Swim',
        'icon': 'mv-swim',
        'grp': 'Travel',
        'prompt': 'swims forward with long alternating strokes, body level in the water',
    },
    {
        'id': 'fly',
        'label': 'Fly / hover',
        'icon': 'mv-fly',
        'grp': 'Travel',
        'prompt': 'beats its wings and holds a hover, body steady, wingtips sweeping',
    },
    # ── turning ──
    {
        'id': 'turn_l',
        'label': 'Look left',
        'icon': 'mv-turnl',
        'grp': 'Turn',
        'prompt': 'turns their head and upper body to look to the left, then holds the new pose',
    },
    {
        'id': 'turn_r',
        'label': 'Look right',
        'icon': 'mv-turnr',
        'grp': 'Turn',
        'prompt': 'turns their head and upper body to look to the right, then holds the new pose',
    },
    {
        'id': 'spin',
        'label': 'Turn around',
        'icon': 'mv-spin',
        'grp': 'Turn',
        'prompt': 'turns the whole body around to face the other way, one continuous turn',
    },
    {
        'id': 'lookover',
        'label': 'Look over shoulder',
        'lb': 'Glance back',
        'icon': 'mv-lookover',
        'grp': 'Turn',
        'prompt': 'glances back over one shoulder, then faces forward again',
    },
    {
        'id': 'lookup',
        'label': 'Look up',
        'icon': 'mv-lookup',
        'grp': 'Turn',
        'prompt': 'tilts the head back to look upward, holding the gaze',
    },
    {
        'id': 'lookdown',
        'label': 'Look down',
        'icon': 'mv-lookdown',
        'grp': 'Turn',
        'prompt': 'lowers the head to look down at the ground in front',
    },
    # ── gesture ──
    {
        'id': 'wave',
        'label': 'Wave',
        'icon': 'mv-wave',
        'grp': 'Gesture',
        'prompt': 'raises one arm and waves in a friendly greeting, a natural relaxed wave',
    },
    {
        'id': 'point',
        'label': 'Point',
        'icon': 'mv-point',
        'grp': 'Gesture',
        'prompt': 'raises an arm and points off to one side, holding the point',
    },
    {
        'id': 'beckon',
        'label': 'Beckon',
        'icon': 'mv-beckon',
        'grp': 'Gesture',
        'prompt': 'beckons with one hand, calling the viewer forward',
    },
    {
        'id': 'reach',
        'label': 'Reach',
        'icon': 'mv-reach',
        'grp': 'Gesture',
        'prompt': 'reaches out with one hand toward something just out of frame, fingers opening',
    },
    {
        'id': 'grab',
        'label': 'Grab / take',
        'icon': 'mv-grab',
        'grp': 'Gesture',
        'prompt': 'reaches out, closes a hand around something and draws it back in',
    },
    {
        'id': 'nod',
        'label': 'Nod',
        'icon': 'mv-nod',
        'grp': 'Gesture',
        'prompt': 'nods the head once, slowly and deliberately, in agreement',
    },
    {
        'id': 'shake_head',
        'label': 'Shake head',
        'icon': 'mv-shakehead',
        'grp': 'Gesture',
        'prompt': 'shakes the head from side to side in refusal',
    },
    {
        'id': 'shrug',
        'label': 'Shrug',
        'icon': 'mv-shrug',
        'grp': 'Gesture',
        'prompt': 'shrugs, lifting both shoulders and opening the palms, then letting them drop',
    },
    {
        'id': 'clap',
        'label': 'Clap',
        'icon': 'mv-clap',
        'grp': 'Gesture',
        'prompt': 'brings both hands together and claps several times',
    },
    {
        'id': 'bow',
        'label': 'Bow',
        'icon': 'mv-bow',
        'grp': 'Gesture',
        'prompt': 'bends forward at the waist into a bow, then straightens up',
    },
    # ── posture change ──
    {
        'id': 'sit',
        'label': 'Sit down',
        'icon': 'mv-sit',
        'grp': 'Posture',
        'prompt': 'lowers into a seated position and settles, weight coming off the legs',
    },
    {
        'id': 'standup',
        'label': 'Stand up',
        'icon': 'mv-standup',
        'grp': 'Posture',
        'prompt': 'pushes up from seated to standing, straightening the legs and back',
    },
    {
        'id': 'crouch',
        'label': 'Crouch',
        'icon': 'mv-crouch',
        'grp': 'Posture',
        'prompt': 'drops into a low crouch, knees bending, head coming down',
    },
    {
        'id': 'kneel',
        'label': 'Kneel',
        'icon': 'mv-kneel',
        'grp': 'Posture',
        'prompt': 'goes down onto one knee and holds there',
    },
    {
        'id': 'lean',
        'label': 'Lean in',
        'icon': 'mv-lean',
        'grp': 'Posture',
        'prompt': 'leans in closer, shifting the upper body forward toward the camera',
    },
    {
        'id': 'recoil',
        'label': 'Recoil',
        'icon': 'mv-recoil',
        'grp': 'Posture',
        'prompt': 'pulls sharply back and away, upper body recoiling from something in front',
    },
    # ── beats and reactions ──
    {
        'id': 'react',
        'label': 'Startle',
        'icon': 'mv-startle',
        'grp': 'React',
        'prompt': 'reacts with a sudden startle, flinching back with wide eyes, a quick startled motion',
    },
    {
        'id': 'laugh',
        'label': 'Laugh',
        'icon': 'mv-laugh',
        'grp': 'React',
        'prompt': 'laughs, head tipping back, shoulders shaking with it',
    },
    {
        'id': 'cry',
        'label': 'Weep',
        'icon': 'mv-cry',
        'grp': 'React',
        'prompt': 'weeps quietly, shoulders drawing in, head lowering',
    },
    {
        'id': 'sigh',
        'label': 'Sigh',
        'icon': 'mv-sigh',
        'grp': 'React',
        'prompt': 'draws a deep breath and lets it out in a long sigh, shoulders dropping',
    },
    {
        'id': 'think',
        'label': 'Think',
        'icon': 'mv-think',
        'grp': 'React',
        'prompt': 'pauses in thought, gaze drifting off, one hand coming toward the chin',
    },
    {
        'id': 'talk',
        'label': 'Speak',
        'icon': 'mv-talk',
        'grp': 'React',
        'prompt': 'speaks, mouth moving naturally, small conversational gestures with the hands',
    },
    {
        'id': 'yawn',
        'label': 'Yawn',
        'icon': 'mv-yawn',
        'grp': 'React',
        'prompt': 'yawns widely, stretching the arms up and out',
    },
    # ── action ──
    {
        'id': 'jump',
        'label': 'Jump',
        'icon': 'mv-jump',
        'grp': 'Action',
        'prompt': 'crouches and springs upward into a jump, then lands and absorbs it',
    },
    {
        'id': 'strike',
        'label': 'Strike',
        'icon': 'mv-strike',
        'grp': 'Action',
        'prompt': 'throws a single committed strike forward, weight rotating behind it',
    },
    {
        'id': 'dodge',
        'label': 'Dodge',
        'icon': 'mv-dodge',
        'grp': 'Action',
        'prompt': 'ducks and slips sharply to one side, avoiding something',
    },
    {
        'id': 'fall',
        'label': 'Fall',
        'icon': 'mv-fall',
        'grp': 'Action',
        'prompt': 'loses balance and falls, going down heavily',
    },
    {
        'id': 'throw',
        'label': 'Throw',
        'icon': 'mv-throw',
        'grp': 'Action',
        'prompt': 'winds up and throws something forward, the arm following through',
    },
    {
        'id': 'dance',
        'label': 'Dance',
        'icon': 'mv-dance',
        'grp': 'Action',
        'prompt': 'dances, moving in rhythm, hips and arms swinging in time',
    },
    {
        'id': 'work',
        'label': 'Work / labour',
        'lb': 'Work',
        'icon': 'mv-work',
        'grp': 'Action',
        'prompt': 'works with the hands at something in front, repeated purposeful movements',
    },
    # ── objects ──
    {
        'id': 'obj_rotate',
        'label': 'Object: rotate',
        'lb': 'Rotate',
        'icon': 'mv-objrot',
        'grp': 'Object',
        'prompt': 'rotates slowly in place, turning to show each side, held level',
    },
    {
        'id': 'obj_bounce',
        'label': 'Object: bounce',
        'lb': 'Bounce',
        'icon': 'mv-objbounce',
        'grp': 'Object',
        'prompt': 'bounces, falling, compressing on impact and springing back up',
    },
    {
        'id': 'obj_float',
        'label': 'Object: float',
        'lb': 'Float',
        'icon': 'mv-objfloat',
        'grp': 'Object',
        'prompt': 'floats and drifts gently, bobbing, turning slightly as it hangs',
    },
    {
        'id': 'obj_topple',
        'label': 'Object: topple',
        'lb': 'Topple',
        'icon': 'mv-objtopple',
        'grp': 'Object',
        'prompt': 'tips past its balance point and topples over, settling on its side',
    },
    # ── the escape hatch ──
    {'id': 'custom', 'label': 'Custom…', 'icon': 'mv-custom', 'grp': 'Custom', 'prompt': ''},
]
_ACTION_BY_ID = {a['id']: a for a in ACTIONS_LIB}


def action_prompt(action_id: str, custom: str = '') -> str:
    if action_id == 'custom':
        return (custom or '').strip()
    a = _ACTION_BY_ID.get(action_id)
    return a['prompt'] if a else ''
