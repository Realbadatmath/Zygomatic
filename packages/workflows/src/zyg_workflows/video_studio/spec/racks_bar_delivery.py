# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, bottom bar — AUDIO, OVERLAY, VFX place, SHOTS, OUTPUT.

Moved verbatim (lines 2587-3089 of the old single-file spec.py). What is laid
over the frames and how the file leaves the studio.
"""

from ..options import _ambience_options, _vfx_element_options

_RACKS_BAR_DELIVERY = [
    {
        'id': 'audio',
        'title': 'AUDIO',
        'icon': 'ic-audio',
        'place': 'bar',
        'sub': 'Wan renders silence. This lays an ambience bed and timed cues '
        'under the finished picture and masters the result — '
        "video_audio.build_track, which is the project's ONE loudness "
        'path (audio_mix), not a second mixer. Runs last, after the '
        'grade chain and the overlay, so the mix sits under the '
        'delivered picture.',
        'params': [
            {
                'key': 'audio_bed',
                'type': 'select',
                'label': 'Ambience bed',
                'def': 'off',
                'icon': 'ic-music',
                'options': _ambience_options(),
                'hint': 'A long, flat, loopable sound from the SFX/foley libraries, '
                'looped with crossfades to the length of the clip. Only '
                'files whose licence sidecar says commercial_ok are listed '
                '— the sidecar is the authority, not the filename.',
            },
            {
                'key': 'audio_bed_path',
                'type': 'text',
                'label': 'Bed file override',
                'def': '',
                'icon': 'ic-audiofile',
                'hint': 'An absolute path to a wav/mp3 to use as the bed instead of '
                'a library entry. Wins over the dropdown. For a bed that '
                'is not in the libraries yet — it carries no licence '
                'record, so it is on you.',
            },
            {
                'key': 'audio_bed_gain',
                'type': 'knob',
                'label': 'Bed gain',
                'def': -8.0,
                'min': -30.0,
                'max': 6.0,
                'step': 0.5,
                'unit': 'dB',
                'icon': 'ic-gain',
                'hint': 'Level of the bed before mastering. -8 is a bed you feel '
                'and do not listen to; above 0 it starts to compete with '
                'anything laid over it.',
            },
            {
                'key': 'audio_bed_fade_in',
                'type': 'knob',
                'label': 'Bed fade in',
                'def': 0.5,
                'min': 0.0,
                'max': 5.0,
                'step': 0.1,
                'unit': 's',
                'icon': 'ic-fadein',
                'hint': 'Fade the bed up from silence. A bed that starts at full level on frame 1 reads as a mistake.',
            },
            {
                'key': 'audio_cues',
                'type': 'json',
                'label': 'SFX cues',
                'def': '[]',
                'icon': 'ic-sfx',
                'hint': 'A JSON list of {"file": "sfx/x.wav" or an abs path, '
                '"at_s": 1.0, "gain_db": 0}. Each cue is placed at at_s '
                'and the finished master is MEASURED to prove it landed '
                'there — the receipt carries measured_onset_s per cue.',
            },
            {
                'key': 'audio_target_lufs',
                'type': 'knob',
                'label': 'Loudness target',
                'def': -14.0,
                'min': -24.0,
                'max': -9.0,
                'step': 0.5,
                'unit': 'LUFS',
                'icon': 'ic-lufs',
                'hint': 'Integrated loudness of the finished track. -14 is what the '
                'rest of the project normalises to; move it only for a '
                'delivery that asks for something else.',
            },
            {
                'key': 'audio_fade_out',
                'type': 'knob',
                'label': 'Audio fade out',
                'def': 0.0,
                'min': 0.0,
                'max': 6.0,
                'step': 0.1,
                'unit': 's',
                'icon': 'ic-fadeout',
                'hint': '0 means follow the picture: the audio fades with the '
                'FINISH Fade out. Set it to take the sound down over a '
                'different length than the vision.',
            },
        ],
    },
    {
        'id': 'overlay',
        'title': 'OVERLAY',
        'icon': 'ic-overlay',
        'place': 'bar',
        'sub': 'Alpha VFX elements burned over the finished picture from a '
        'video_overlay PLACEMENT RECORD — the draft the operator '
        'approves and the final render read the same JSON and run the '
        'same maths, so a draft is a real preview and not a guess.',
        'params': [
            {
                'key': 'overlay_record',
                'type': 'json',
                'label': 'Placement record',
                'def': '{}',
                'icon': 'ic-layers',
                'hint': 'The video_overlay record: {"layers": [{"element": '
                '"<abs path to .mov/.webm/PNG dir>", "x": 0.6, "y": 0.5, '
                '"height": 0.1, "start_s": 0, "end_s": null, ...}]}. '
                'Empty, or without a "layers" list, means no overlay pass '
                'runs at all.',
            },
            {
                'key': 'overlay_draft',
                'type': 'toggle',
                'label': 'Draft overlay',
                'def': False,
                'icon': 'ic-draft',
                'hint': "Composite at the record's draft width/fps with an "
                'ultrafast preset. Same placement maths, seconds instead '
                'of minutes — for checking where a layer sits, never for '
                'a delivery.',
            },
        ],
    },
    {
        'id': 'vfx',
        'title': 'VFX place',
        'icon': 'ic-place',
        'place': 'bar',
        'sub': 'Metric placement of a library element. Point at the spot on '
        'the ground where the effect happens, say how far right / up / '
        'back of it the element actually sits IN METRES and how big it '
        'is IN METRES, and VFX draft answers in seconds with a 320p '
        'composite. A render bakes the same numbers at full quality '
        'through the same solver — the draft is a preview, not a guess.',
        'params': [
            {
                'key': 'vfx_element',
                'type': 'select',
                'label': 'Element',
                'def': 'none',
                'icon': 'ic-layers',
                'options': _vfx_element_options(),
                'hint': 'A row of the VFX library. Rows marked "(draft only)" '
                'have no 4K alpha element built yet, so a bake falls back '
                'to their preview; the others composite their real matte. '
                'A DRAFT always uses the preview whatever the row has — '
                'decoding 4K VP9-with-alpha is the whole cost of the '
                'composite, and a draft exists to be instant.',
            },
            {
                'key': 'vfx_anchor',
                'type': 'text',
                'label': 'Ground anchor',
                'def': '0.50,0.85',
                'icon': 'ic-target',
                'hint': 'Where the effect TOUCHES THE GROUND, as fractions of the '
                'frame ("0.50,0.85" is centre, 85% down). Clicking the '
                'player while this rack is open sets it. The camera turns '
                'that pixel into metres on the plane y=0, so an anchor on '
                'the sky (above the horizon) has no distance and the '
                'placement refuses.',
            },
            {
                'key': 'vfx_offset',
                'type': 'text',
                'label': 'Offset (m)',
                'def': '1.0,0.0,2.0',
                'icon': 'ic-compass',
                'hint': 'Right, up, back from the anchor in METRES — "1.0,0.0,2.0" '
                'is one metre to screen right and two metres further from '
                'the camera. Back is what changes the size: the element '
                'shrinks with depth exactly as the lens says it should.',
            },
            {
                'key': 'vfx_size_m',
                'type': 'knob',
                'label': 'Element height',
                'def': 3.0,
                'min': 0.2,
                'max': 200.0,
                'step': 0.1,
                'unit': 'm',
                'icon': 'ic-height',
                'hint': 'How tall the effect is in the world. A person is ~1.8, a '
                'car ~1.5, a house ~8, a dust shockwave over a street 20+. '
                'This and the depth are the only two things that set the '
                'size on screen.',
            },
            {
                'key': 'vfx_cam_fov',
                'type': 'knob',
                'label': 'Camera fov',
                'def': 50.0,
                'min': 20.0,
                'max': 120.0,
                'step': 1.0,
                'unit': '°',
                'icon': 'ic-lens',
                'hint': 'VERTICAL field of view of the lens that shot the plate. '
                'Ignored when the clip came from a scene shot — then the '
                'studio camera on disk wins, because placing against a '
                'guessed lens when the real one is known is just a wrong '
                'answer arrived at carefully.',
            },
            {
                'key': 'vfx_cam_height',
                'type': 'knob',
                'label': 'Camera height',
                'def': 1.6,
                'min': 0.3,
                'max': 50.0,
                'step': 0.1,
                'unit': 'm',
                'icon': 'ic-tripod',
                'hint': 'How far the lens is above the ground. This is the scale '
                'of the whole solve: halve it and every metre in the '
                'frame halves with it.',
            },
            {
                'key': 'vfx_cam_pitch',
                'type': 'knob',
                'label': 'Camera pitch',
                'def': 0.0,
                'min': -45.0,
                'max': 45.0,
                'step': 0.5,
                'unit': '°',
                'icon': 'ic-angle',
                'hint': 'Positive looks DOWN, like a tripod head. At 0 the horizon '
                'is exactly halfway up the frame — if it is not, this dial '
                'is wrong and every distance will be too.',
            },
            {
                'key': 'vfx_start_s',
                'type': 'knob',
                'label': 'Start',
                'def': 0.0,
                'min': 0.0,
                'max': 30.0,
                'step': 0.1,
                'unit': 's',
                'icon': 'ic-timecode',
                'hint': 'When the element fires, measured from the top of the '
                'clip. It loops for the rest of the clip after that.',
            },
            {
                'key': 'vfx_opacity',
                'type': 'knob',
                'label': 'Opacity',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-gauge',
                'hint': 'Strength of the composite. On a real matte it scales the '
                'alpha; on a draft preview it scales the RGB, which is '
                'what a screen blend reads as strength.',
            },
        ],
    },
    {
        'id': 'shots',
        'title': 'SHOTS',
        'icon': 'ic-shots',
        'place': 'bar',
        'sub': 'A multi-shot assembly built from clips this console (or any '
        'other) already rendered — video_assembly.assemble. It is its '
        'own job, started by the Assemble shots action; it does not run '
        'as part of a render.',
        'params': [
            {
                'key': 'shot_list',
                'type': 'json',
                'label': 'Shot list',
                'def': '{}',
                'icon': 'ic-timeline',
                'hint': 'The video_assembly shot list: {"fps": 24, "size": '
                '[1920,1080], "shots": [{"path": "..."}, {"still": '
                '"title.png", "hold_s": 5}]}. A shot path may be given as '
                'a media path ("out/video_studio/<job>/clip.mp4") and is '
                "resolved under this console's output folder.",
            },
            {
                'key': 'shot_xfade',
                'type': 'knob',
                'label': 'Default crossfade',
                'def': 0.18,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'unit': 's',
                'icon': 'ic-xfade',
                'hint': 'The join length used for any shot that does not name its '
                'own xfade_s. Every join EATS this much programme: the '
                'total is the sum of the shots minus the sum of the '
                'crossfades.',
            },
        ],
    },
    {
        'id': 'output',
        'title': 'OUTPUT',
        'icon': 'ic-export',
        'place': 'bar',
        'sub': 'How the finished clip is encoded and what else gets written beside it.',
        'params': [
            {
                'key': 'container',
                'type': 'select',
                'label': 'Container',
                'def': 'mp4',
                'icon': 'ic-container',
                'options': [
                    {'v': 'mp4', 'l': 'mp4'},
                    {'v': 'mov', 'l': 'mov'},
                    {'v': 'mkv', 'l': 'mkv'},
                    {'v': 'webm', 'l': 'webm'},
                ],
                'hint': 'The preview player wants mp4 or webm; mov is for ProRes and '
                'mkv for anything the others refuse to hold.',
            },
            {
                'key': 'codec',
                'type': 'select',
                'label': 'Codec',
                'def': 'h264',
                'icon': 'ic-codec',
                'options': [
                    {'v': 'h264', 'l': 'H.264 — plays anywhere'},
                    {'v': 'h265', 'l': 'H.265 — smaller, slower'},
                    {'v': 'vp9', 'l': 'VP9 — webm'},
                    {'v': 'prores', 'l': 'ProRes 422 HQ — editing'},
                ],
                'hint': 'Anything but H.264/mp4 is written as a SECOND file beside '
                'the mp4, encoded from the finished mp4 so it carries every '
                'finishing step — the mp4 stays the one the preview plays. '
                'A ProRes here is therefore a ProRes of a near-lossless '
                'h264 master, which is right for handing to an editor and '
                'is not an archival original.',
            },
            {
                'key': 'rate_mode',
                'type': 'select',
                'label': 'Rate control',
                'def': 'crf',
                'icon': 'ic-ratemode',
                'options': [{'v': 'crf', 'l': 'quality (CRF)'}, {'v': 'bitrate', 'l': 'target bitrate'}],
                'hint': 'CRF holds quality and lets the size vary. Target bitrate is '
                'for a delivery spec, and only that.',
            },
            {
                'key': 'crf',
                'type': 'int',
                'label': 'Quality (CRF)',
                'def': 20,
                'min': 10,
                'max': 34,
                'step': 1,
                'icon': 'ic-gauge',
                'hint': 'Lower = better and bigger. 18 is visually lossless on this '
                'material, 23 is where grain starts to smear. When a bloom '
                'pass, a loop or a non-mp4 delivery still has to run, the '
                'mp4 master is encoded at CRF 12 regardless, so that the '
                'last encode is the only one that costs anything.',
            },
            {
                'key': 'bitrate',
                'type': 'int',
                'label': 'Target bitrate',
                'def': 8000,
                'min': 500,
                'max': 60000,
                'step': 500,
                'unit': 'kbps',
                'icon': 'ic-bitrate',
                'hint': 'Only read when Rate control is "target bitrate".',
            },
            {
                'key': 'x_preset',
                'type': 'select',
                'label': 'Encoder preset',
                'def': 'veryfast',
                'icon': 'ic-preset',
                'options': [
                    {'v': 'ultrafast', 'l': 'ultrafast'},
                    {'v': 'veryfast', 'l': 'veryfast'},
                    {'v': 'medium', 'l': 'medium'},
                    {'v': 'slow', 'l': 'slow'},
                    {'v': 'veryslow', 'l': 'veryslow'},
                ],
                'hint': 'Encoder effort, not render effort. Against a render measured '
                'in minutes, "slow" costs seconds and is nearly free.',
            },
            {
                'key': 'x_tune',
                'type': 'select',
                'label': 'Encoder tune',
                'def': '',
                'icon': 'ic-tune',
                'options': [
                    {'v': '', 'l': 'none'},
                    {'v': 'film', 'l': 'film'},
                    {'v': 'grain', 'l': 'grain — keeps grain'},
                    {'v': 'animation', 'l': 'animation'},
                    {'v': 'stillimage', 'l': 'still image'},
                ],
                'hint': '"grain" is the one that matters here: without it the '
                'encoder spends its bits smoothing away the grain you just '
                'added. x264/x265 only.',
            },
            {
                'key': 'pix_fmt',
                'type': 'select',
                'label': 'Pixel format',
                'def': 'yuv420p',
                'icon': 'ic-bitdepth',
                'options': [
                    {'v': 'yuv420p', 'l': '8-bit 4:2:0 — universal'},
                    {'v': 'yuv420p10le', 'l': '10-bit 4:2:0'},
                    {'v': 'yuv422p10le', 'l': '10-bit 4:2:2'},
                    {'v': 'yuv444p', 'l': '8-bit 4:4:4'},
                ],
                'hint': '10-bit is what stops banding surviving into the delivery '
                'after a deband. Some players refuse anything but 420p 8-bit.',
            },
            {
                'key': 'faststart',
                'type': 'toggle',
                'label': 'Faststart',
                'def': True,
                'icon': 'ic-faststart',
                'hint': 'Moves the index to the front so the file starts playing '
                'before it has downloaded. mp4/mov only.',
            },
            {
                'key': 'out_fps',
                'type': 'select',
                'label': 'Output fps',
                'def': 'off',
                'icon': 'ic-outfps',
                'options': [
                    {'v': 'off', 'l': 'off — keep the render rate'},
                    {'v': '24', 'l': '24'},
                    {'v': '25', 'l': '25'},
                    {'v': '30', 'l': '30'},
                    {'v': '50', 'l': '50'},
                    {'v': '60', 'l': '60'},
                ],
                'hint': 'Conforms the finished file by dropping or duplicating '
                'frames. To SYNTHESISE frames use Interpolate instead; this '
                'one judders by design. Ignored when Interpolate is on — '
                'that filter already sets the output rate.',
            },
            {
                'key': 'gif_export',
                'type': 'toggle',
                'label': 'Also write a GIF',
                'def': False,
                'icon': 'ic-gif',
                'hint': 'Palette-generated GIF beside the mp4, capped at 480px wide '
                'and 15fps. For pasting into a message, nothing else.',
            },
            {
                'key': 'webp_export',
                'type': 'toggle',
                'label': 'Also write a WebP',
                'def': False,
                'icon': 'ic-webp',
                'hint': 'Animated WebP — much better than the GIF at the same size, and refused by some chat clients.',
            },
            {
                'key': 'poster_frame',
                'type': 'toggle',
                'label': 'Write a poster frame',
                'def': False,
                'icon': 'ic-poster',
                'hint': 'A PNG of the middle frame beside the clip, for a thumbnail or a card.',
            },
            {
                'key': 'contact_sheet',
                'type': 'toggle',
                'label': 'Write a contact sheet',
                'def': False,
                'icon': 'ic-sheet',
                'hint': 'A 5x2 grid of stills across the clip. The fastest way to '
                'see drift across a chained render without scrubbing it.',
            },
        ],
    },
]
