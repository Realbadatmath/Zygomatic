# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.racks_bar_language — the remaining bar racks
(language, identity, pin, plates, ctrlpath)."""

from zyg_workflows.movement_studio.options import (
    _lora2_options,
    _lora_options,
    _object_options,
    _plate_view_options,
    _plateset_options,
)

_RACKS_BAR_LANGUAGE = [
    {
        'id': 'language',
        'title': 'LANGUAGE',
        'icon': 'mv-language',
        'place': 'bar',
        'sub': 'The exact text that reaches umt5. Nothing here is decorative — what '
        'you see in the prompt preview is byte-for-byte what is submitted.',
        'params': [
            {
                'key': 'custom_prompt',
                'type': 'text',
                'label': 'Custom motion text',
                'lb': 'Custom text',
                'def': '',
                'icon': 'mv-custom',
                'hint': 'Used as the base action when the action library is set to Custom. '
                'Every other dial still modifies it.',
            },
            {
                'key': 'prompt_mode',
                'type': 'select',
                'label': 'Prompt mode',
                'def': 'composed',
                'icon': 'mv-promptmode',
                'options': [
                    {'v': 'composed', 'l': 'composed — dials build the sentence'},
                    {'v': 'verbatim', 'l': 'verbatim — send my text alone'},
                ],
                'hint': 'verbatim sends the base action text and NOTHING else from this rail — '
                'the escape hatch when a phrasing matters more than the dials. The '
                'locked-camera prefix and the subject binding are still added by the '
                'render itself; they are not optional.',
            },
            {
                'key': 'prompt_suffix',
                'type': 'text',
                'label': 'Prompt suffix',
                'lb': 'Suffix',
                'def': '',
                'icon': 'mv-suffix',
                'hint': 'Raw text appended last, after every composed clause. Your escape hatch '
                'when a token you need has no dial.',
            },
            {
                'key': 'negative_prompt',
                'type': 'text',
                'label': 'Extra negative',
                'lb': 'Negative',
                'def': '',
                'icon': 'mv-negative',
                'hint': "PREPENDED to the recipe's own static-shot negative, never replacing "
                'it — that negative is what holds the camera still, and a clip that '
                'loses it drifts. Blank is the normal state.',
            },
            {
                'key': 'beat_schedule',
                'type': 'text',
                'label': 'Beat schedule',
                'lb': 'Beats',
                'def': '',
                'icon': 'mv-beats',
                'hint': 'Multi-beat motion, beats separated by " | " — "raises the lantern | '
                'turns toward the door | steps through". REQUIRES Context windows on '
                '(bottom bar): the wrapper only picks a per-window sub-prompt inside '
                'the context loop, so without windows every beat after the first is '
                'silently never selected. The render refuses rather than shipping that.',
            },
        ],
    },
    {
        'id': 'identity',
        'title': 'IDENTITY',
        'icon': 'mv-identity',
        'place': 'bar',
        'sub': 'What keeps the subject looking like itself across 65 frames.',
        'params': [
            {
                'key': 'lora',
                'type': 'select',
                'label': 'Subject LoRA',
                'def': 'auto',
                'icon': 'mv-lora',
                'options': _lora_options(),
                'hint': 'auto uses the wan_chars/wan_props LoRA bp_movement found for this '
                'subject, or none if it has not been trained yet.',
            },
            {
                'key': 'lora_strength',
                'type': 'float',
                'label': 'LoRA strength',
                'lb': 'LoRA str',
                'def': 0.5,
                'min': 0.0,
                'max': 1.5,
                'step': 0.05,
                'icon': 'mv-lorastr',
                'hint': 'Wan LoRA weight. 0.5 is the shipped default. Above ~0.9 a character '
                'LoRA starts fighting the VACE pin and the pose stops responding.',
            },
            {
                'key': 'lora2',
                'type': 'select',
                'label': 'Second LoRA',
                'def': '',
                'icon': 'mv-lora2',
                'options': _lora2_options(),
                'hint': 'Chained after the subject LoRA — a style or motion LoRA. Put its '
                'trigger token in the prompt suffix yourself; nothing here does that '
                'for you.',
            },
            {
                'key': 'lora2_strength',
                'type': 'float',
                'label': 'Second strength',
                'lb': '2nd str',
                'def': 0.4,
                'min': 0.0,
                'max': 1.5,
                'step': 0.05,
                'icon': 'mv-lora2str',
                'hint': 'Weight for the second LoRA. Ignored while that slot is none.',
            },
            {
                'key': 'binding',
                'type': 'toggle',
                'label': 'Canon binding',
                'lb': 'Binding',
                'def': True,
                'icon': 'mv-binding',
                'hint': "Prepends the subject's canon prompt binding (the trigger phrase "
                'wan_face_restore uses). Off, the LoRA has nothing to fire on — turn it '
                'off only to measure what the LoRA is doing by itself.',
            },
            {
                'key': 'identity_refs',
                'type': 'int',
                'label': 'Identity refs',
                'lb': 'Refs',
                'def': 1,
                'min': 0,
                'max': 3,
                'step': 1,
                'icon': 'mv-refs',
                'hint': "How many stills go into VACE's ref_images seat — its STRONGEST "
                'identity channel (refs enter as keep-unchanged latent frames under '
                "full attention). 1 = the subject's canon portrait alone, which is the "
                "fix for the 2026-07-29 drift. Extra refs come from the subject's own "
                'folder. 0 falls back to the fitted still.',
            },
        ],
    },
    {
        'id': 'pin',
        'title': 'VACE PIN',
        'icon': 'mv-pin',
        'place': 'bar',
        'sub': 'How hard the still is held. This is the set of levers the frozen-clip '
        'work of 2026-07-29 landed on; the defaults here are the measured ones.',
        'params': [
            {
                'key': 'vace_strength',
                'type': 'float',
                'label': 'Pin strength',
                'def': 0.7,
                'min': 0.1,
                'max': 1.0,
                'step': 0.05,
                'icon': 'mv-pinstr',
                'hint': 'VACE embed strength over the whole frame. 1.0 for 100% of steps is '
                'literally what made the first build render the still 65 times.',
            },
            {
                'key': 'vace_start_percent',
                'type': 'float',
                'label': 'Pin start %',
                'def': 0.0,
                'min': 0.0,
                'max': 0.5,
                'step': 0.01,
                'icon': 'mv-pinstart',
                'hint': 'Fraction of the denoise before the pin engages. 0 is normal; raising '
                'it lets the first steps compose freely before the set is imposed.',
            },
            {
                'key': 'vace_end_percent',
                'type': 'float',
                'label': 'Pin end %',
                'def': 0.35,
                'min': 0.05,
                'max': 1.0,
                'step': 0.01,
                'icon': 'mv-pinend',
                'hint': 'Fraction of the denoise the pin holds for. THE motion lever after '
                'Shift: 0.35 releases the subject for the last two-thirds of the '
                'denoise, which is where the movement is actually synthesised.',
            },
            {
                'key': 'neutral_control',
                'type': 'toggle',
                'label': 'Neutral control',
                'lb': 'Neutral',
                'def': True,
                'icon': 'mv-neutral',
                'hint': "Grey-fills the control frames under the subject mask so the still's "
                'own pixels stop leaking in as per-frame guidance. Off restores the '
                'pre-fix inpaint semantics and the clip freezes — kept only so the '
                'failure can be reproduced deliberately.',
            },
            {
                'key': 'n_regions',
                'type': 'int',
                'label': 'Mask regions',
                'def': 2,
                'min': 1,
                'max': 4,
                'step': 1,
                'icon': 'mv-regions',
                'hint': 'How many subject blobs build_char_mask keeps. 1 for a single figure; '
                'raise it when a subject and a held prop must both be free to move.',
            },
            {
                'key': 'char_geom',
                'type': 'toggle',
                'label': 'Skeleton guide',
                'lb': 'Skeleton',
                'def': True,
                'icon': 'mv-skeleton',
                'hint': 'Paints the detected skeleton and face mesh back into the greyed region '
                'as a GUIDE (released at pin end, not pasted). Off is the measured '
                'failure: identity and pose re-invented per context window.',
            },
            {
                'key': 'graded_pin',
                'type': 'toggle',
                'label': 'Graded pin',
                'def': False,
                'icon': 'mv-graded',
                'hint': 'Differential-diffusion pin over ONE box, so a prop or a flame can be '
                'held still while the faces stay free. The whole-mask version of this '
                'measured a face from 0.70 aliveness down to 0.33 — hence one box, not '
                'the mask. Needs a box below.',
            },
            {
                'key': 'pin_box',
                'type': 'text',
                'label': 'Pin box',
                'def': '',
                'icon': 'mv-pinbox',
                'hint': 'x0,y0,x1,y1 as fractions of the frame, e.g. 0.44,0.56,0.54,0.88. '
                'Ignored unless Graded pin is on; with the pin on and this blank, the '
                'pin stays off and the graph is byte-identical to having never asked.',
            },
            {
                'key': 'pin_level',
                'type': 'float',
                'label': 'Pin level',
                'def': 0.65,
                'min': 0.1,
                'max': 1.0,
                'step': 0.05,
                'icon': 'mv-pinlevel',
                'hint': 'A pinned box is held for this fraction of the steps, then freed.',
            },
        ],
    },
    {
        'id': 'plates',
        'title': 'PROP PLATES',
        'icon': 'mv-plates',
        'place': 'bar',
        'sub': 'Rendered rigid geometry painted into the control frame where the grey '
        'fill would otherwise hand VACE a constant. A GUIDE released at Pin end % '
        '— never a paste onto the output.',
        'params': [
            {
                'key': 'plate_object',
                'type': 'select',
                'label': 'Plate object',
                'lb': 'Object',
                'def': 'none',
                'icon': 'mv-plateobj',
                'options': _object_options(),
                'hint': 'A registered prop_mesh_library asset. Its mesh_control depth map is '
                'warped into the box below and composited into the control frame by '
                'prop_control.composite_into_control. "none" emits prop_plates=None '
                'and the graph is byte-identical to never having asked.',
            },
            {
                'key': 'plate_view',
                'type': 'select',
                'label': 'Plate view',
                'lb': 'View',
                'def': 'auto',
                'icon': 'mv-plateview',
                'options': _plate_view_options(),
                'hint': 'Which rendered camera of that asset to use — the pose the plate '
                'asserts. Pick the one that matches how the object sits in the still; '
                'a front plate warped into a profile box is a wrong assertion, not a '
                'weak one.',
            },
            {
                'key': 'plate_kind',
                'type': 'select',
                'label': 'Plate channel',
                'lb': 'Channel',
                'def': 'depth',
                'icon': 'mv-platekind',
                'options': [
                    {'v': 'depth', 'l': 'depth — near=white, the shape only'},
                    {'v': 'normal', 'l': 'normal — camera-space surface direction'},
                    {'v': 'lineart', 'l': 'lineart — edges only'},
                ],
                'hint': 'Which mesh_control map is painted in. depth is the measured default: '
                'it states form without stating colour, which is what the control '
                'channel is for.',
            },
            {
                'key': 'plate_box',
                'type': 'text',
                'label': 'In-frame box',
                'lb': 'Box',
                'def': '',
                'icon': 'mv-platebox',
                'hint': 'x,y,w,h as fractions of the frame, e.g. 0.36,0.42,0.22,0.30 — where '
                'the object sits in THIS still. Blank with an object chosen and no '
                'auto phrase leaves the plate off rather than guessing a placement.',
            },
            {
                'key': 'plate_auto',
                'type': 'toggle',
                'label': 'Auto box from SAM 3',
                'lb': 'Auto box',
                'def': False,
                'icon': 'mv-plateauto',
                'hint': 'Ask sam3_service.segment for the phrase below and use the returned '
                'box instead of the typed one. Falls back to the typed box when the '
                'segmenter finds nothing — never to a guess.',
            },
            {
                'key': 'plate_phrase',
                'type': 'text',
                'label': 'Auto box phrase',
                'lb': 'Phrase',
                'def': '',
                'icon': 'mv-platephrase',
                'hint': 'The noun phrase SAM 3 is asked to find in the still, e.g. "the round '
                'furry creature". Ignored while Auto box is off.',
            },
            {
                'key': 'plate_strength',
                'type': 'float',
                'label': 'Plate strength',
                'lb': 'Plate str',
                'def': 0.6,
                'min': 0.05,
                'max': 1.0,
                'step': 0.05,
                'icon': 'mv-platestr',
                'hint': 'Per-plate alpha into the control frame — prop_control reads it off '
                'the plate dict. A world-static prop can take 1.0; a prop in a MOVING '
                'HAND must not (v21 measured pipe churn_p95 0.384 -> 0.014 and the '
                'face down to 0.058: the hand froze with the prop). 0.6 is the held-'
                'prop default.',
            },
        ],
    },
    {
        'id': 'ctrlpath',
        'title': 'CONTROL PATH',
        'icon': 'mv-ctrlpath',
        'place': 'rail',
        'sub': 'Drive the per-frame control and mask channels from folders on disk '
        'instead of from the single still. Both are OFF unless a folder is given.',
        'params': [
            {
                'key': 'scene_plateset',
                'type': 'select',
                'label': 'Scene plate set',
                'lb': 'Scene',
                'def': 'none',
                'icon': 'mv-scene',
                'options': _plateset_options(),
                'hint': 'A Blender shot exported by scene_plates.py (data/architecture/shots/'
                '<id>/plates). Sets control_dir, mask_dir, raw control blend, the '
                'still, the frame count and the resolution from plateset.json; the '
                'character still comes from the Subject rack as usual. An explicit '
                "Control frames folder below WINS over the scene's own — set both "
                "and you get the typed folder with the scene's masks.",
            },
            {
                'key': 'control_dir',
                'type': 'text',
                'label': 'Control frames folder',
                'lb': 'Ctrl dir',
                'def': '',
                'icon': 'mv-ctrldir',
                'hint': 'A folder of per-frame control PNGs (a pose/depth driver). Passed as '
                "control_dir= to generate_vace_static_clip. That argument is S01's "
                'build: while the installed signature has no control_dir the job '
                'REFUSES rather than silently rendering from the still.',
            },
            {
                'key': 'mask_dir',
                'type': 'text',
                'label': 'Mask frames folder',
                'lb': 'Mask dir',
                'def': '',
                'icon': 'mv-maskdir',
                'hint': 'A folder of per-frame mask PNGs, passed as mask_path=. The per-frame '
                'path is live behind ZYG_VACE_MASK_SEQ, which this field sets for the '
                'job (wan_vace_service.py:1490 refuses to guess without it).',
            },
            {
                'key': 'driver_clip',
                'type': 'text',
                'label': 'Driver clip',
                'lb': 'Driver',
                'def': '',
                'icon': 'mv-driver',
                'hint': 'A video to extract a per-frame body track from. The Extract track '
                'button asks for a SUBJECT DESCRIPTION — the phrase SAM 3 looks for, '
                'like "the young man in the red coat" — then runs geom.pose_track over '
                'the clip and rasterises that track with geom.track_plates, filling '
                'BOTH fields above: Control frames with the composite (depth + '
                'skeleton over the tracked body) plate folder, and Mask frames with '
                'the per-frame subject masks. The description is what produces the '
                'masks at all: pose_track only segments a subject it was given a '
                'phrase to find, so a vague phrase (or one SAM 3 cannot match) comes '
                'back with no masks and the sheet says so. Left empty it falls back to '
                'the loaded subject\'s name, then to "the person". It is a background '
                'job on the GPU — the sheet shows its log while it runs.',
            },
        ],
    },
]
