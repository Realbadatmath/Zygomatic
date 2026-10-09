# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, right-hand rail — LOOK and SAMPLER.

Moved verbatim (lines 577-1075 of the old single-file spec.py). The grade
vocabulary, and the per-shot sampler dials that joined the right rail on
2026-09-06.
"""

from zyg_workflows import wan_video_service as _wan

from ..options import RESOLUTIONS

_RACKS_RAIL_LOOK = [
    {
        'id': 'look',
        'title': 'LOOK',
        'icon': 'ic-palette',
        'place': 'rail',
        'sub': 'The picture. Everything here is a prompt token EXCEPT Grade, which '
        'is an ffmpeg filter applied after the render.',
        'params': [
            {
                'key': 'visual_style',
                'type': 'select',
                'label': 'Visual style',
                'def': 'cinematic',
                'icon': 'ic-film',
                'options': [
                    {'v': 'cinematic', 'l': 'cinematic (photoreal)'},
                    {'v': 'documentary', 'l': 'documentary'},
                    {'v': 'animated', 'l': 'animated / cel'},
                    {'v': 'painterly', 'l': 'painterly'},
                ],
                'hint': 'Anything but cinematic takes the wan_prompt route — the '
                'heuristic route hard-codes a "Photorealistic" tail that '
                'fights an animated or painterly look.',
            },
            {
                'key': 'lighting',
                'type': 'select',
                'label': 'Lighting',
                'def': 'auto',
                'icon': 'ic-bulb',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'soft diffused light', 'l': 'soft diffused'},
                    {'v': 'hard directional light, deep shadows', 'l': 'hard key'},
                    {'v': 'rim lighting from behind', 'l': 'rim / backlit'},
                    {'v': 'low-key lighting, mostly shadow', 'l': 'low key'},
                    {'v': 'high-key lighting, bright and even', 'l': 'high key'},
                    {'v': 'lit by a single practical lamp', 'l': 'practical lamp'},
                    {'v': 'firelight', 'l': 'firelight'},
                    {'v': 'candlelight', 'l': 'candlelight'},
                    {'v': 'harsh overhead fluorescent light', 'l': 'fluorescent'},
                    {'v': 'moonlight', 'l': 'moonlight'},
                    {'v': 'neon light spill', 'l': 'neon'},
                ],
                'hint': 'Named lighting is worth more than any grade — a grade can '
                'only tint what the model already lit.',
            },
            {
                'key': 'time_of_day',
                'type': 'select',
                'label': 'Time of day',
                'def': 'auto',
                'icon': 'ic-sun',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'at dawn', 'l': 'dawn'},
                    {'v': 'in early morning light', 'l': 'morning'},
                    {'v': 'at midday', 'l': 'midday'},
                    {'v': 'in the afternoon', 'l': 'afternoon'},
                    {'v': 'in golden hour light', 'l': 'golden hour'},
                    {'v': 'at dusk', 'l': 'dusk'},
                    {'v': 'in blue hour twilight', 'l': 'blue hour'},
                    {'v': 'at night', 'l': 'night'},
                ],
                'hint': 'Sets both the colour of the light and its direction.',
            },
            {
                'key': 'weather',
                'type': 'select',
                'label': 'Weather / air',
                'def': 'auto',
                'icon': 'ic-cloud',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'clear air', 'l': 'clear'},
                    {'v': 'overcast', 'l': 'overcast'},
                    {'v': 'in the rain', 'l': 'rain'},
                    {'v': 'in heavy rain', 'l': 'heavy rain'},
                    {'v': 'in falling snow', 'l': 'snow'},
                    {'v': 'in fog', 'l': 'fog'},
                    {'v': 'in a dust-filled haze', 'l': 'dusty haze'},
                    {'v': 'in a storm', 'l': 'storm'},
                ],
                'hint': 'Weather brings free environmental motion with it, which is '
                'why a rainy prompt so rarely trips the frozen-clip gate.',
            },
            {
                'key': 'palette',
                'type': 'select',
                'label': 'Palette',
                'def': 'auto',
                'icon': 'ic-swatch',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'a warm amber palette', 'l': 'warm amber'},
                    {'v': 'a cool blue palette', 'l': 'cool blue'},
                    {'v': 'a teal and orange palette', 'l': 'teal / orange'},
                    {'v': 'a desaturated palette', 'l': 'desaturated'},
                    {'v': 'a monochrome palette', 'l': 'monochrome'},
                    {'v': 'a high-contrast palette', 'l': 'high contrast'},
                    {'v': 'a pastel palette', 'l': 'pastel'},
                    {'v': 'an earthy muted palette', 'l': 'earthy'},
                ],
                'hint': 'Asking the model for a palette beats grading one on — the '
                'model can put the colour in the light, ffmpeg cannot.',
            },
            {
                'key': 'grade',
                'type': 'select',
                'label': 'Grade (post)',
                'def': 'none',
                'icon': 'ic-grade',
                'options': [
                    {'v': 'none', 'l': 'none'},
                    {'v': 'teal_orange', 'l': 'teal / orange'},
                    {'v': 'bleach', 'l': 'bleach bypass'},
                    {'v': 'warm', 'l': 'warm'},
                    {'v': 'cool', 'l': 'cool'},
                    {'v': 'sepia', 'l': 'sepia'},
                    {'v': 'mono', 'l': 'monochrome'},
                    {'v': 'contrast', 'l': 'punchy contrast'},
                    {'v': 'faded', 'l': 'faded film'},
                ],
                'hint': 'A real ffmpeg filter applied after the render, so it is '
                'reversible only by re-rendering. The GRADE rack in the '
                'bottom bar gives you the same controls one at a time.',
            },
            {
                'key': 'film_stock',
                'type': 'select',
                'label': 'Film stock',
                'def': 'auto',
                'icon': 'ic-stock',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'shot on 35mm film', 'l': '35mm film'},
                    {'v': 'shot on 16mm film, visible grain', 'l': '16mm'},
                    {'v': 'shot on Super 8, heavy grain', 'l': 'Super 8'},
                    {'v': 'shot on 65mm large format', 'l': '65mm'},
                    {'v': 'shot on a modern digital cinema camera', 'l': 'digital'},
                    {'v': 'shot on VHS video, tape artefacts', 'l': 'VHS'},
                    {'v': 'shot on a security camera', 'l': 'CCTV'},
                    {'v': 'shot on a phone camera', 'l': 'phone'},
                ],
                'hint': 'Format carries grain, gate weave and colour response with '
                'it — far more than the Grain dial in FINISH can fake.',
            },
            {
                'key': 'light_temp',
                'type': 'select',
                'label': 'Light temperature',
                'def': 'auto',
                'icon': 'ic-kelvin',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'very warm tungsten light', 'l': 'tungsten (warm)'},
                    {'v': 'warm light', 'l': 'warm'},
                    {'v': 'neutral daylight-balanced light', 'l': 'neutral'},
                    {'v': 'cool light', 'l': 'cool'},
                    {'v': 'very cold blue light', 'l': 'cold blue'},
                    {'v': 'mixed colour temperature light', 'l': 'mixed'},
                ],
                'hint': 'The colour of the light in the scene, asked of the model. '
                'The Colour temp dial in GRADE tints the finished pixels '
                'instead — this one changes what was lit.',
            },
            {
                'key': 'contrast_look',
                'type': 'select',
                'label': 'Contrast look',
                'def': 'auto',
                'icon': 'ic-contrastlook',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'flat low-contrast log-like image', 'l': 'flat / log'},
                    {'v': 'natural contrast', 'l': 'natural'},
                    {'v': 'punchy contrast, crushed blacks', 'l': 'punchy'},
                    {'v': 'lifted milky blacks', 'l': 'lifted blacks'},
                    {'v': 'silhouetted against the light', 'l': 'silhouette'},
                ],
                'hint': 'Asking for flat and grading afterwards gives you more room '
                'than asking for punchy and trying to pull it back.',
            },
            {
                'key': 'atmosphere',
                'type': 'select',
                'label': 'Atmosphere',
                'def': 'auto',
                'icon': 'ic-fog',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'clean air, no haze', 'l': 'clean'},
                    {'v': 'atmospheric haze', 'l': 'haze'},
                    {'v': 'thick fog', 'l': 'fog'},
                    {'v': 'smoke in the air', 'l': 'smoke'},
                    {'v': 'dust hanging in the air', 'l': 'dust'},
                    {'v': 'visible god rays through the air', 'l': 'god rays'},
                    {'v': 'underwater', 'l': 'underwater'},
                ],
                'hint': 'Atmosphere gives depth cues a flat render lacks, and it '
                'moves — a double win against the frozen-clip gate.',
            },
            {
                'key': 'lens_flare',
                'type': 'select',
                'label': 'Flare / bloom',
                'def': 'auto',
                'icon': 'ic-flare',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'no lens flare', 'l': 'none'},
                    {'v': 'subtle lens bloom', 'l': 'subtle bloom'},
                    {'v': 'an anamorphic lens flare', 'l': 'anamorphic streak'},
                    {'v': 'strong lens flare across the frame', 'l': 'strong flare'},
                    {'v': 'halation around the highlights', 'l': 'halation'},
                ],
                'hint': 'Prompt-side flare sits behind the subject correctly; the '
                'Bloom dial in GRADE can only glow what is already bright.',
            },
            {
                'key': 'texture_look',
                'type': 'select',
                'label': 'Texture',
                'def': 'auto',
                'icon': 'ic-texture',
                'options': [
                    {'v': 'auto', 'l': 'auto'},
                    {'v': 'clean crisp digital texture', 'l': 'clean'},
                    {'v': 'fine film grain', 'l': 'fine grain'},
                    {'v': 'heavy grain', 'l': 'heavy grain'},
                    {'v': 'soft diffusion filter over the lens', 'l': 'diffusion'},
                    {'v': 'razor-sharp micro-detail', 'l': 'razor sharp'},
                    {'v': 'slightly soft, gentle focus', 'l': 'gentle soft'},
                ],
                'hint': 'Skin reads waxy when the prompt asks for nothing here — a '
                'texture token is the documented fix for that.',
            },
            {
                'key': 'style_ref',
                'type': 'text',
                'label': 'Style reference',
                'def': '',
                'icon': 'ic-styleref',
                'hint': 'Free style text — "in the style of a Roger Deakins night '
                'exterior". Appended as its own clause. There is no image '
                'style reference in this graph; this is words only.',
            },
        ],
    },
    # 2026-09-06: SAMPLER moved off the LEFT rail to the RIGHT one. Duration,
    # frames, steps and the noise schedule are dialled per shot alongside SCENE /
    # CAMERA / MOTION / LOOK, not set once with the engine — and the right rail
    # went to FIVE columns the same day, which is where the 18 icons fit without
    # pushing the creative dials into a scroll — and matches the left rail, so
    # the two margins either side of the picture are the same width.
    {
        'id': 'sampler',
        'title': 'SAMPLER',
        'icon': 'ic-sliders',
        'place': 'rail',
        'sub': 'Length, step budget and the noise schedule (nodes 30 / 31 / 45).',
        'params': [
            {
                'key': 'duration_s',
                'type': 'select',
                'label': 'Duration',
                'def': '3.4',
                'icon': 'ic-hourglass',
                'options': [
                    {'v': '1.7', 'l': '1.7s'},
                    {'v': '3.4', 'l': '3.4s'},
                    {'v': '5.1', 'l': '5.1s (chained)'},
                    {'v': '6.8', 'l': '6.8s (chained)'},
                    {'v': '10.2', 'l': '10.2s (chained)'},
                ],
                'hint': 'Anything past one sub-clip is CHAINED: the last frame of '
                'each becomes the seed of the next, so identity drifts and '
                'render time is linear in duration.',
            },
            {
                'key': 'frames',
                'type': 'int',
                'label': 'Frames / sub-clip',
                'def': 81,
                'min': 17,
                'max': 161,
                'step': 4,
                'icon': 'ic-filmframes',
                'hint': 'Must be 4n+1 — the VAE has a temporal stride of 4. 81 at '
                '24fps is the ~3.4s the models were trained on; longer '
                'sub-clips degrade rather than fail.',
            },
            {
                'key': 'fps',
                'type': 'knob',
                'label': 'Render fps',
                'def': float(_wan._CLIP_FPS),
                'min': 8.0,
                'max': 60.0,
                'step': 1.0,
                'unit': 'fps',
                'icon': 'ic-fps',
                'hint': 'node 45 fps — the rate the frames are ASSEMBLED at, not a '
                'rate the model renders to. Lower it and the same 81 frames '
                'become a longer, slower clip.',
            },
            {
                'key': 'steps',
                'type': 'int',
                'label': 'Steps',
                'def': 20,
                'min': 4,
                'max': 60,
                'step': 1,
                'icon': 'ic-stairs',
                'hint': 'Denoise steps. Below ~15 without Lightning the motion goes '
                'mushy; above ~35 buys almost nothing on I2V.',
            },
            {
                'key': 'guidance',
                'type': 'knob',
                'label': 'Guidance (CFG)',
                'def': 6.0,
                'min': 1.0,
                'max': 15.0,
                'step': 0.1,
                'icon': 'ic-target',
                'hint': 'Prompt adherence. High CFG on Wan burns contrast and '
                'freezes motion long before it improves the prompt match.',
            },
            {
                'key': 'flow_shift',
                'type': 'knob',
                'label': 'Flow shift',
                'def': 5.0,
                'min': 1.0,
                'max': 12.0,
                'step': 0.1,
                'icon': 'ic-wave',
                'hint': 'The timestep-schedule shift, and the strongest motion lever '
                'in the sampler. Low values render a nearly frozen clip — '
                'that is the documented 2026-07-29 bug.',
            },
            {
                'key': 'scheduler',
                'type': 'select',
                'label': 'Scheduler',
                'def': 'unipc',
                'icon': 'ic-metronome',
                'options': [
                    {'v': 'unipc', 'l': 'unipc'},
                    {'v': 'unipc/beta', 'l': 'unipc/beta'},
                    {'v': 'dpm++', 'l': 'dpm++'},
                    {'v': 'dpm++/beta', 'l': 'dpm++/beta'},
                    {'v': 'dpm++_sde', 'l': 'dpm++ sde'},
                    {'v': 'euler', 'l': 'euler'},
                    {'v': 'euler/beta', 'l': 'euler/beta'},
                    {'v': 'deis', 'l': 'deis'},
                    {'v': 'lcm', 'l': 'lcm'},
                    {'v': 'res_multistep', 'l': 'res multistep'},
                    {'v': 'er_sde', 'l': 'er sde'},
                ],
                'hint': 'unipc is the trained default. The /beta variants shift the '
                'sigma schedule toward the low-noise end — more detail, less '
                'large motion.',
            },
            {
                'key': 'riflex',
                'type': 'int',
                'label': 'RIFLEx index',
                'def': 0,
                'min': 0,
                'max': 10,
                'step': 1,
                'icon': 'ic-extend',
                'hint': 'Rotary-position extrapolation for clips longer than the '
                'training length. 0 = off. Only worth touching above ~120 '
                'frames in a single sub-clip.',
            },
            {
                'key': 'seed',
                'type': 'int',
                'label': 'Seed',
                'def': 0,
                'min': 0,
                'max': 999999,
                'step': 1,
                'icon': 'ic-dice',
                'hint': '0 = a fresh seed per render. Pin it to compare one dial against another honestly.',
            },
            {
                'key': 'seed_mode',
                'type': 'select',
                'label': 'Seed across sub-clips',
                'def': 'increment',
                'icon': 'ic-link',
                'options': [
                    {'v': 'increment', 'l': 'increment per sub-clip'},
                    {'v': 'fixed', 'l': 'same seed for every sub-clip'},
                ],
                'hint': 'A fixed seed across a chain makes the sub-clips rhyme with '
                'each other, which can read as a repeating loop.',
            },
            {
                'key': 'variants',
                'type': 'int',
                'label': 'Variants',
                'def': 1,
                'min': 1,
                'max': 4,
                'step': 1,
                'icon': 'ic-stack',
                'hint': 'Render N clips at spaced seeds and keep them all. Cost is '
                'exactly linear — 4 variants is 4 renders.',
            },
            {
                'key': 'resolution',
                'type': 'select',
                'label': 'Resolution',
                'def': '832x480',
                'icon': 'ic-ratio',
                'options': [{'v': r, 'l': r} for r in RESOLUTIONS],
                'hint': 'The 2.1 pathways are trained per resolution — a 480P model '
                'at 720p is worse, not bigger. 2.2 handles both.',
            },
            {
                'key': 'denoise_strength',
                'type': 'knob',
                'label': 'Denoise strength',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-denoisestr',
                'hint': 'nodes 30/31 denoise_strength. Below 1 starts partway down '
                'the schedule. On a from-scratch I2V render this mostly '
                'produces a soft, under-cooked clip — it exists for '
                'latent-input workflows.',
            },
            {
                'key': 'batched_cfg',
                'type': 'toggle',
                'label': 'Batched CFG',
                'def': False,
                'icon': 'ic-batchcfg',
                'hint': 'Run the conditional and unconditional passes as one batch: '
                'faster, and roughly doubles the activation memory. Free '
                'speed when CFG is 1.0 — there is no second pass to batch.',
            },
            {
                'key': 'rope_function',
                'type': 'select',
                'label': 'RoPE function',
                'def': 'comfy',
                'icon': 'ic-rope',
                'options': [
                    {'v': 'comfy', 'l': 'comfy'},
                    {'v': 'comfy_chunked', 'l': 'comfy chunked — less VRAM'},
                    {'v': 'default', 'l': 'wrapper default'},
                ],
                'hint': 'How rotary embeddings are computed. Chunked trades a little '
                'speed for a real VRAM saving at long frame counts.',
            },
            {
                'key': 'add_noise_samples',
                'type': 'toggle',
                'label': 'Add noise to samples',
                'def': False,
                'icon': 'ic-addnoise',
                'hint': 'Re-noises an incoming latent before sampling. Meaningless '
                'without a latent input; exposed because it silently changes '
                'what Denoise strength does.',
            },
            {
                'key': 'sampler_start_step',
                'type': 'int',
                'label': 'Start step',
                'def': 0,
                'min': 0,
                'max': 60,
                'step': 1,
                'icon': 'ic-startstep',
                'hint': 'Wan2.1 pathways only — on Wan2.2 the expert boundary owns '
                'start/end step and this is ignored (and logged).',
            },
            {
                'key': 'sampler_end_step',
                'type': 'int',
                'label': 'End step',
                'def': -1,
                'min': -1,
                'max': 60,
                'step': 1,
                'icon': 'ic-endstep',
                'hint': '-1 = run to the end. Stopping early leaves the clip noisy; '
                'it is a debugging window, not a look.',
            },
        ],
    },
]
