# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, right-hand rail — SCENE, CAMERA, MOTION.

Moved verbatim (lines 59-576 of the old single-file spec.py). What the shot
shows: the prompt, the framing, the movement.
"""

_RACKS_RAIL_SHOT = [
    # ══════════════════════════════════════════════ RAIL — the shot itself
    {
        'id': 'scene',
        'title': 'SCENE',
        'icon': 'ic-script',
        'place': 'rail',
        'sub': 'What happens in the shot. Feeds the same Wan prompt builder the storyteller pipeline uses.',
        'params': [
            {
                'key': 'scene_prompt',
                'type': 'text',
                'label': 'Scene description',
                'def': '',
                'icon': 'ic-script',
                'hint': "What the subject is doing in this shot. Left blank, the clip's name is the whole prompt.",
            },
            {
                'key': 'link_prompts',
                'type': 'longtext',
                'label': 'Prompt per link',
                'def': '',
                'icon': 'ic-script',
                'hint': 'One prompt per chained sub-clip, separated by " || ". Link i '
                'uses prompt i; a missing or empty piece falls back to Scene '
                'description. Every link still gets the camera/motion/look '
                'phrases that compose_prompt appends.',
            },
            {
                'key': 'prompt_mode',
                'type': 'select',
                'label': 'Prompt mode',
                'def': 'auto',
                'icon': 'ic-wand',
                'options': [
                    {'v': 'auto', 'l': 'auto — builder adds camera + style'},
                    {'v': 'verbatim', 'l': 'verbatim — send my text as-is'},
                ],
                'hint': 'auto runs your text through _build_prompt (camera grammar, '
                'style suffix, motion vocabulary). verbatim sends exactly what '
                'you typed — nothing appended except the suffix below.',
            },
            {
                'key': 'prompt_suffix',
                'type': 'text',
                'label': 'Prompt suffix',
                'def': '',
                'icon': 'ic-plustext',
                'hint': 'Raw text appended last, after every builder token. Your '
                'escape hatch when a token you need has no dial.',
            },
            {
                'key': 'negative_prompt',
                'type': 'text',
                'label': 'Negative prompt',
                'def': '',
                'icon': 'ic-ban',
                'hint': 'Overrides the graph template negative. Blank keeps the '
                'template (anti-static motion tokens) — or the curated '
                'static-shot negative when Locked camera is on.',
            },
            {
                'key': 'setting',
                'type': 'text',
                'label': 'Setting / location',
                'def': '',
                'icon': 'ic-place',
                'hint': 'Where the shot happens — "a rain-wet harbour quay at dusk". '
                'Appended as its own prompt clause so it survives the '
                "builder's camera grammar.",
            },
            {
                'key': 'wardrobe',
                'type': 'text',
                'label': 'Wardrobe',
                'def': '',
                'icon': 'ic-shirt',
                'hint': 'What the subject is wearing. Worth pinning on a chained '
                'render — Wan drifts clothing across sub-clips faster than '
                'it drifts faces.',
            },
            {
                'key': 'props',
                'type': 'text',
                'label': 'Props / held objects',
                'def': '',
                'icon': 'ic-prop',
                'hint': 'Objects in frame or in hand. Naming a held object is the '
                'cheapest way to stop Wan dissolving it mid-clip.',
            },
            {
                'key': 'emotion_beat',
                'type': 'select',
                'label': 'Expression',
                'def': 'auto',
                'icon': 'ic-face',
                'options': [
                    {'v': 'auto', 'l': 'auto — follow Motion / mood'},
                    {'v': 'neutral expression', 'l': 'neutral'},
                    {'v': 'a faint smile', 'l': 'faint smile'},
                    {'v': 'laughing openly', 'l': 'laughing'},
                    {'v': 'a hard, set jaw', 'l': 'hardened'},
                    {'v': 'wide-eyed alarm', 'l': 'alarmed'},
                    {'v': 'weary, heavy-lidded', 'l': 'weary'},
                    {'v': 'tears in the eyes', 'l': 'tearful'},
                    {'v': 'a slow dawning realisation', 'l': 'realising'},
                    {'v': 'suppressed anger', 'l': 'suppressed anger'},
                ],
                'hint': "The face, separate from the shot's overall mood. Motion / "
                'mood also drives the camera; this only drives the face.',
            },
            {
                'key': 'background_action',
                'type': 'select',
                'label': 'Background life',
                'def': 'auto',
                'icon': 'ic-crowd',
                'options': [
                    {'v': 'auto', 'l': 'auto — say nothing'},
                    {'v': 'an empty, still background', 'l': 'empty / still'},
                    {'v': 'people passing in the background', 'l': 'passers-by'},
                    {'v': 'a busy crowd behind', 'l': 'busy crowd'},
                    {'v': 'traffic moving behind', 'l': 'traffic'},
                    {'v': 'birds crossing the sky behind', 'l': 'birds'},
                    {'v': 'water moving behind', 'l': 'water'},
                    {'v': 'smoke drifting behind', 'l': 'smoke'},
                ],
                'hint': 'Background motion is what sells a shot as filmed rather '
                'than photographed — and it also raises the motion score, '
                'so a frozen-subject clip can still pass the gate. Watch for '
                'that when you use it.',
            },
        ],
    },
    {
        'id': 'camera',
        'title': 'CAMERA',
        'icon': 'ic-camera',
        'place': 'rail',
        'sub': 'Framing and camera behaviour. Every dial here is a prompt token — '
        'Wan has no camera rig, it has camera vocabulary.',
        'params': [
            {
                'key': 'shot_type',
                'type': 'select',
                'label': 'Shot type',
                'def': 'medium shot',
                'icon': 'ic-frame',
                'options': [
                    {'v': 'extreme close-up', 'l': 'extreme close-up'},
                    {'v': 'close-up', 'l': 'close-up'},
                    {'v': 'medium close-up', 'l': 'medium close-up'},
                    {'v': 'medium shot', 'l': 'medium shot'},
                    {'v': 'medium wide shot', 'l': 'medium wide'},
                    {'v': 'wide shot', 'l': 'wide shot'},
                    {'v': 'extreme wide shot', 'l': 'extreme wide'},
                    {'v': 'over-the-shoulder shot', 'l': 'over the shoulder'},
                    {'v': 'two shot', 'l': 'two shot'},
                    {'v': 'insert shot', 'l': 'insert'},
                ],
                'hint': 'On the cinematic route this ALSO picks the camera move — '
                '_build_prompt maps shot type to motion. Set Camera move off '
                'auto to break that link.',
            },
            {
                'key': 'camera_move',
                'type': 'select',
                'label': 'Camera move',
                'def': 'auto',
                'icon': 'ic-dolly',
                'options': [
                    {'v': 'auto', 'l': 'auto — from shot type / mood'},
                    {'v': 'slow push in', 'l': 'push in'},
                    {'v': 'slow pull back', 'l': 'pull back'},
                    {'v': 'slow pan left', 'l': 'pan left'},
                    {'v': 'slow pan right', 'l': 'pan right'},
                    {'v': 'slow tilt up', 'l': 'tilt up'},
                    {'v': 'slow tilt down', 'l': 'tilt down'},
                    {'v': 'tracking alongside', 'l': 'tracking'},
                    {'v': 'orbiting around the subject', 'l': 'orbit'},
                    {'v': 'crane up and back', 'l': 'crane'},
                    {'v': 'handheld follow', 'l': 'handheld follow'},
                    {'v': 'a slow dolly zoom', 'l': 'dolly zoom'},
                    {'v': 'a whip pan', 'l': 'whip pan'},
                ],
                'hint': 'Anything but auto forces the wan_prompt route — the '
                'heuristic route would overwrite it with the shot-type map.',
            },
            {
                'key': 'lens',
                'type': 'select',
                'label': 'Lens',
                'def': 'auto',
                'icon': 'ic-lens',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'shot on a 14mm ultra-wide lens', 'l': '14mm ultra-wide'},
                    {'v': 'shot on a 24mm wide lens', 'l': '24mm wide'},
                    {'v': 'shot on a 35mm lens', 'l': '35mm'},
                    {'v': 'shot on a 50mm lens', 'l': '50mm normal'},
                    {'v': 'shot on an 85mm portrait lens', 'l': '85mm portrait'},
                    {'v': 'shot on a 135mm telephoto lens', 'l': '135mm tele'},
                    {'v': 'shot on a 200mm long lens, compressed perspective', 'l': '200mm compressed'},
                    {'v': 'shot on an anamorphic lens', 'l': 'anamorphic'},
                    {'v': 'shot through a macro lens', 'l': 'macro'},
                    {'v': 'shot on a fisheye lens', 'l': 'fisheye'},
                ],
                'hint': 'Focal length is the strongest single lever on how a face '
                'reads — wide distorts, long flattens.',
            },
            {
                'key': 'depth_of_field',
                'type': 'select',
                'label': 'Depth of field',
                'def': 'auto',
                'icon': 'ic-aperture',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'razor-thin depth of field, background fully melted', 'l': 'razor thin'},
                    {'v': 'shallow depth of field, soft background', 'l': 'shallow'},
                    {'v': 'moderate depth of field', 'l': 'moderate'},
                    {'v': 'deep focus, everything sharp', 'l': 'deep focus'},
                ],
                'hint': 'A shallow field also hides background instability — the '
                'cheapest fix for a background that boils.',
            },
            {
                'key': 'static_shot',
                'type': 'toggle',
                'label': 'Locked camera',
                'def': False,
                'icon': 'ic-tripod',
                'hint': 'Locked-off tripod grammar plus the curated static negative. '
                'Forces the wan_prompt route — the heuristic route always '
                'writes a camera move in.',
            },
            {
                'key': 'camera_rig',
                'type': 'select',
                'label': 'Camera rig',
                'def': 'auto',
                'icon': 'ic-rig',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'locked-off tripod', 'l': 'tripod'},
                    {'v': 'handheld camera, subtle operator sway', 'l': 'handheld'},
                    {'v': 'smooth steadicam move', 'l': 'steadicam'},
                    {'v': 'gimbal-smooth glide', 'l': 'gimbal'},
                    {'v': 'dolly on track', 'l': 'dolly track'},
                    {'v': 'jib arm move', 'l': 'jib / crane'},
                    {'v': 'aerial drone shot', 'l': 'drone'},
                    {'v': 'shoulder-mounted documentary camera', 'l': 'shoulder rig'},
                ],
                'hint': 'How the move is CARRIED, as distinct from what the move is. '
                'Handheld is the single most effective anti-frozen token '
                'there is; it also makes the stabiliser worth turning on.',
            },
            {
                'key': 'camera_height',
                'type': 'select',
                'label': 'Camera height',
                'def': 'auto',
                'icon': 'ic-height',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'ground-level camera', 'l': 'ground level'},
                    {'v': 'low angle looking up', 'l': 'low angle'},
                    {'v': 'eye-level camera', 'l': 'eye level'},
                    {'v': 'slightly high angle looking down', 'l': 'high angle'},
                    {'v': 'overhead shot looking straight down', 'l': 'overhead'},
                    {'v': "a bird's-eye view far above", 'l': "bird's eye"},
                ],
                'hint': 'Height reads as status: low makes the subject tower, high '
                'makes them small. Independent of the shot size.',
            },
            {
                'key': 'camera_angle',
                'type': 'select',
                'label': 'Camera angle',
                'def': 'auto',
                'icon': 'ic-angle',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'straight-on frontal angle', 'l': 'frontal'},
                    {'v': 'three-quarter angle', 'l': 'three-quarter'},
                    {'v': 'profile angle', 'l': 'profile'},
                    {'v': 'from behind the subject', 'l': 'from behind'},
                    {'v': 'a dutch tilt, canted horizon', 'l': 'dutch tilt'},
                ],
                'hint': 'Where the camera stands relative to the subject. A dutch '
                'tilt is the only one here that also changes the horizon.',
            },
            {
                'key': 'camera_speed',
                'type': 'select',
                'label': 'Move speed',
                'def': 'auto',
                'icon': 'ic-camspeed',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'an almost imperceptible camera move', 'l': 'imperceptible'},
                    {'v': 'a slow deliberate camera move', 'l': 'slow'},
                    {'v': 'a steady camera move', 'l': 'steady'},
                    {'v': 'a brisk camera move', 'l': 'brisk'},
                    {'v': 'a fast aggressive camera move', 'l': 'fast'},
                ],
                'hint': 'How fast the move goes. Ignored when Locked camera is on — a locked shot has no move to pace.',
            },
            {
                'key': 'focus_pull',
                'type': 'select',
                'label': 'Focus',
                'def': 'auto',
                'icon': 'ic-focus',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'focus held on the subject throughout', 'l': 'held'},
                    {'v': 'a rack focus onto the subject', 'l': 'rack to subject'},
                    {'v': 'a rack focus off the subject to the background', 'l': 'rack to background'},
                    {'v': 'follow focus tracking the subject', 'l': 'follow focus'},
                    {'v': 'the shot drifts gently out of focus', 'l': 'drift soft'},
                ],
                'hint': 'A rack focus is one of the few genuinely temporal camera '
                'ideas Wan renders convincingly — worth spending a shot on.',
            },
            {
                'key': 'framing_rule',
                'type': 'select',
                'label': 'Framing',
                'def': 'auto',
                'icon': 'ic-thirds',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'subject centred in frame', 'l': 'centred'},
                    {'v': 'subject on a third, looking into the space', 'l': 'rule of thirds'},
                    {'v': 'symmetrical composition', 'l': 'symmetrical'},
                    {'v': 'a lot of negative space around the subject', 'l': 'negative space'},
                    {'v': 'tightly cropped, subject filling the frame', 'l': 'tight crop'},
                    {'v': 'framed through a foreground element', 'l': 'framed through'},
                ],
                'hint': 'Where the subject sits in the rectangle. Pairs with shot '
                'type, which decides only how big they are.',
            },
        ],
    },
    {
        'id': 'motion',
        'title': 'MOTION',
        'icon': 'ic-motion',
        'place': 'rail',
        'sub': 'What actually moves, and how much. The single most common cause of '
        'a rejected clip is a prompt that never asked for movement.',
        'params': [
            {
                'key': 'motion_style',
                'type': 'select',
                'label': 'Motion / mood',
                'def': 'neutral',
                'icon': 'ic-mask',
                'options': [
                    {'v': 'neutral', 'l': 'neutral'},
                    {'v': 'calm', 'l': 'calm'},
                    {'v': 'tense', 'l': 'tense'},
                    {'v': 'joyful', 'l': 'joyful'},
                    {'v': 'sad', 'l': 'sad'},
                    {'v': 'angry', 'l': 'angry'},
                    {'v': 'fearful', 'l': 'fearful'},
                    {'v': 'triumphant', 'l': 'triumphant'},
                    {'v': 'contemplative', 'l': 'contemplative'},
                ],
                'hint': "Drives _build_prompt's emotion→camera-motion map when "
                'Camera move is on auto, and colours the whole prompt.',
            },
            {
                'key': 'motion_amount',
                'type': 'select',
                'label': 'Motion amount',
                'def': 'auto',
                'icon': 'ic-speed',
                'options': [
                    {'v': 'auto', 'l': 'auto — from the mood'},
                    {'v': 'subtle', 'l': 'subtle'},
                    {'v': 'moderate', 'l': 'moderate'},
                    {'v': 'dynamic', 'l': 'dynamic'},
                    {'v': 'frenetic', 'l': 'frenetic'},
                ],
                'hint': 'The blunt lever when a clip comes back frozen. Raise this before you touch the sampler.',
            },
            {
                'key': 'motion_subject',
                'type': 'select',
                'label': 'What moves',
                'def': 'auto',
                'icon': 'ic-runner',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'camera', 'l': 'camera only'},
                    {'v': 'subject', 'l': 'subject only'},
                    {'v': 'both', 'l': 'both'},
                ],
                'hint': '"Subject only" plus Locked camera is the combination that produces a usable performance take.',
            },
            {
                'key': 'body_motion',
                'type': 'select',
                'label': 'Body',
                'def': 'auto',
                'icon': 'ic-body',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'standing still, breathing', 'l': 'still, breathing'},
                    {'v': 'shifting weight slightly', 'l': 'weight shift'},
                    {'v': 'gesturing while speaking', 'l': 'gesturing'},
                    {'v': 'walking toward the camera', 'l': 'walking toward'},
                    {'v': 'walking away from the camera', 'l': 'walking away'},
                    {'v': 'turning to face the camera', 'l': 'turning to camera'},
                    {'v': 'sitting down', 'l': 'sitting down'},
                    {'v': 'standing up', 'l': 'standing up'},
                    {'v': 'reaching out a hand', 'l': 'reaching'},
                    {'v': 'leaning in', 'l': 'leaning in'},
                    {'v': 'recoiling back', 'l': 'recoiling'},
                ],
                'hint': 'A named body action beats any amount of "dynamic movement" '
                'phrasing — the model has a verb to render.',
            },
            {
                'key': 'head_motion',
                'type': 'select',
                'label': 'Head',
                'def': 'auto',
                'icon': 'ic-head',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'head held still', 'l': 'still'},
                    {'v': 'turning the head slowly', 'l': 'turning'},
                    {'v': 'nodding', 'l': 'nodding'},
                    {'v': 'shaking the head', 'l': 'shaking'},
                    {'v': 'tilting the head', 'l': 'tilting'},
                    {'v': 'looking down then up', 'l': 'down then up'},
                    {'v': 'glancing over the shoulder', 'l': 'glance back'},
                ],
                'hint': 'Head motion is what most reliably survives a chained '
                'sub-clip hand-off; limbs drift far sooner.',
            },
            {
                'key': 'eye_motion',
                'type': 'select',
                'label': 'Eyes',
                'def': 'auto',
                'icon': 'ic-gaze',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': "holding the camera's gaze", 'l': 'to camera'},
                    {'v': 'looking off past the camera', 'l': 'off camera'},
                    {'v': 'eyes scanning the scene', 'l': 'scanning'},
                    {'v': 'blinking naturally', 'l': 'blinking'},
                    {'v': 'eyes closing slowly', 'l': 'closing'},
                    {'v': 'eyes widening', 'l': 'widening'},
                ],
                'hint': 'Blink is the cheapest liveness tell there is. A clip with '
                'no blink in 5s reads as a still with a moving camera.',
            },
            {
                'key': 'mouth_motion',
                'type': 'select',
                'label': 'Mouth',
                'def': 'auto',
                'icon': 'ic-mouth',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'mouth closed, not speaking', 'l': 'closed / silent'},
                    {'v': 'speaking', 'l': 'speaking'},
                    {'v': 'mid-sentence, mouth moving', 'l': 'mid-sentence'},
                    {'v': 'breaking into a smile', 'l': 'breaking into a smile'},
                    {'v': 'taking a breath', 'l': 'taking a breath'},
                    {'v': 'shouting', 'l': 'shouting'},
                ],
                'hint': 'There is no audio here and no lip-sync model — "speaking" '
                'buys plausible mouth movement, never matched dialogue.',
            },
            {
                'key': 'secondary_motion',
                'type': 'select',
                'label': 'Hair / cloth',
                'def': 'auto',
                'icon': 'ic-cloth',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'hair and clothing hanging still', 'l': 'still'},
                    {'v': 'hair stirring in a light breeze', 'l': 'light breeze'},
                    {'v': 'hair and coat whipping in wind', 'l': 'strong wind'},
                    {'v': 'fabric settling as the subject moves', 'l': 'fabric settle'},
                    {'v': 'wet hair and clothing clinging', 'l': 'wet cling'},
                ],
                'hint': 'Secondary motion is the difference between a puppet and a '
                'person. It costs nothing in the sampler.',
            },
            {
                'key': 'env_motion',
                'type': 'select',
                'label': 'Environment',
                'def': 'auto',
                'icon': 'ic-leaves',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'a completely still environment', 'l': 'still'},
                    {'v': 'leaves moving in the wind', 'l': 'leaves'},
                    {'v': 'rain falling through the frame', 'l': 'rain'},
                    {'v': 'snow drifting down', 'l': 'snow'},
                    {'v': 'dust motes in the light', 'l': 'dust motes'},
                    {'v': 'water rippling', 'l': 'water'},
                    {'v': 'flames flickering', 'l': 'flame'},
                    {'v': 'steam rising', 'l': 'steam'},
                ],
                'hint': 'Like Background life, this raises the motion score without '
                'the subject moving — read the gate result with that in mind.',
            },
        ],
    },
]
