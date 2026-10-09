# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, left rail — GUIDANCE, LONG CLIP, DECODE.

Moved verbatim (lines 1511-1931 of the old single-file spec.py). The tail of
the left rail: how the sampler is steered, the long-clip window, and the
decode that turns latents into frames.
"""

_RACKS_LEFT_GUIDANCE = [
    {
        'id': 'guidance',
        'title': 'GUIDANCE',
        'icon': 'ic-compass',
        'place': 'left',
        'sub': 'Extra conditioning applied on top of CFG — skip-layer guidance, '
        'Enhance-A-Video and normalised attention guidance.',
        'params': [
            {
                'key': 'slg',
                'type': 'toggle',
                'label': 'Skip-layer guidance',
                'def': False,
                'icon': 'ic-slg',
                'hint': 'Runs the unconditional pass with some blocks skipped, so '
                'guidance pushes away from a deliberately degraded model. '
                'Buys detail and coherence at no extra step cost.',
            },
            {
                'key': 'slg_blocks',
                'type': 'text',
                'label': 'SLG blocks',
                'def': '10',
                'icon': 'ic-slgblocks',
                'hint': 'Comma-separated block indices to skip. "10" is the tested '
                'Wan value; "9,10" is stronger and less stable.',
            },
            {
                'key': 'slg_start',
                'type': 'knob',
                'label': 'SLG start',
                'def': 0.1,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-slgstart',
                'hint': 'Fraction of the schedule to start at. Starting at 0 damages the composition step.',
            },
            {
                'key': 'slg_end',
                'type': 'knob',
                'label': 'SLG end',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-slgend',
                'hint': 'Fraction of the schedule to stop at.',
            },
            {
                'key': 'feta',
                'type': 'toggle',
                'label': 'Enhance-A-Video',
                'def': False,
                'icon': 'ic-feta',
                'hint': 'Boosts the cross-frame attention energy — measurably more '
                'temporal movement. The one accelerator-adjacent option that '
                'pushes the motion score UP rather than down.',
            },
            {
                'key': 'feta_weight',
                'type': 'knob',
                'label': 'Enhance weight',
                'def': 2.0,
                'min': 0.0,
                'max': 10.0,
                'step': 0.1,
                'icon': 'ic-fetaw',
                'hint': 'Past ~4 the extra energy turns into flicker and boiling texture rather than motion.',
            },
            {
                'key': 'feta_start',
                'type': 'knob',
                'label': 'Enhance start',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-fetastart',
                'hint': 'Fraction of the schedule to start at.',
            },
            {
                'key': 'feta_end',
                'type': 'knob',
                'label': 'Enhance end',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-fetaend',
                'hint': 'Fraction of the schedule to stop at. Ending early keeps the '
                'motion and drops the flicker it adds to fine detail.',
            },
            {
                'key': 'nag',
                'type': 'toggle',
                'label': 'NAG',
                'def': False,
                'icon': 'ic-nag',
                'hint': 'Normalised attention guidance: a SECOND prompt is encoded '
                'and pushed away from in attention space rather than in the '
                'CFG pass. It is the only negative that still bites when '
                'CFG is 1.0 — which is exactly the Lightning case.',
            },
            {
                'key': 'nag_prompt',
                'type': 'text',
                'label': 'NAG prompt',
                'def': '',
                'icon': 'ic-nagprompt',
                'hint': 'What to push away from. Blank falls back to the effective '
                'negative prompt. Adds one more text-encode pass.',
            },
            {
                'key': 'nag_scale',
                'type': 'knob',
                'label': 'NAG scale',
                'def': 11.0,
                'min': 0.0,
                'max': 30.0,
                'step': 0.5,
                'icon': 'ic-nagscale',
                'hint': 'How hard to push. 11 is the paper default; the failure mode is a hard, over-sharpened image.',
            },
            {
                'key': 'nag_tau',
                'type': 'knob',
                'label': 'NAG tau',
                'def': 2.5,
                'min': 0.0,
                'max': 10.0,
                'step': 0.1,
                'icon': 'ic-nagtau',
                'hint': 'Clamp on how far a token may be pushed — the safety rail '
                'that keeps a high scale from tearing the image.',
            },
            {
                'key': 'nag_alpha',
                'type': 'knob',
                'label': 'NAG alpha',
                'def': 0.25,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-nagalpha',
                'hint': 'Blend back toward the un-guided attention. Lower is gentler.',
            },
        ],
    },
    {
        'id': 'context',
        'title': 'LONG CLIP',
        'icon': 'ic-window',
        'place': 'left',
        'sub': 'Sliding-window sampling, seam handling and FreeInit. This is the '
        'alternative to chaining sub-clips: one continuous latent, sampled '
        'in overlapping windows, so identity does not hand off.',
        'params': [
            {
                'key': 'context',
                'type': 'toggle',
                'label': 'Context windows',
                'def': False,
                'icon': 'ic-context',
                'hint': 'Sample a long clip as overlapping windows instead of '
                'chaining separate renders. Slower than chaining and far '
                'more consistent — the fix for identity drift at 10s.',
            },
            {
                'key': 'context_schedule',
                'type': 'select',
                'label': 'Window schedule',
                'def': 'uniform_standard',
                'icon': 'ic-ctxsched',
                'options': [
                    {'v': 'uniform_standard', 'l': 'uniform standard'},
                    {'v': 'uniform_looped', 'l': 'uniform looped — seamless loop'},
                    {'v': 'static_standard', 'l': 'static standard'},
                ],
                'hint': '"Looped" wraps the last window onto the first, which is the '
                'only way to get a genuinely seamless loop out of the model '
                'rather than out of a crossfade.',
            },
            {
                'key': 'context_frames',
                'type': 'int',
                'label': 'Window size',
                'def': 81,
                'min': 16,
                'max': 161,
                'step': 1,
                'icon': 'ic-ctxframes',
                'hint': "Frames per window. Keep it at the model's trained length — "
                'this is the number that decides quality, not total length.',
            },
            {
                'key': 'context_stride',
                'type': 'int',
                'label': 'Window stride',
                'def': 4,
                'min': 4,
                'max': 100,
                'step': 1,
                'icon': 'ic-ctxstride',
                'hint': 'How far each window advances. Smaller = more windows, more time, smoother.',
            },
            {
                'key': 'context_overlap',
                'type': 'int',
                'label': 'Window overlap',
                'def': 16,
                'min': 4,
                'max': 100,
                'step': 1,
                'icon': 'ic-ctxoverlap',
                'hint': 'Frames shared between neighbours. Too little and the seams '
                'pulse; too much and the whole clip goes slack.',
            },
            {
                'key': 'freenoise',
                'type': 'toggle',
                'label': 'FreeNoise',
                'def': True,
                'icon': 'ic-freenoise',
                'hint': 'Shuffled, correlated noise across windows. Leave on — off, the windows visibly restart.',
            },
            {
                'key': 'fuse_method',
                'type': 'select',
                'label': 'Window blend',
                'def': 'linear',
                'icon': 'ic-fuse',
                'options': [{'v': 'linear', 'l': 'linear'}, {'v': 'pyramid', 'l': 'pyramid'}],
                'hint': 'How overlapping windows are merged. Pyramid weights the '
                'centre of each window more and hides seams better.',
            },
            {
                'key': 'loop_seam',
                'type': 'toggle',
                'label': 'Loop args',
                'def': False,
                'icon': 'ic-loopseam',
                'hint': 'WanVideoLoopArgs — shifts the latent between steps so the '
                'end meets the beginning. A model-level loop, unlike the '
                'FINISH Loop dial which is an edit.',
            },
            {
                'key': 'loop_shift_skip',
                'type': 'int',
                'label': 'Loop shift',
                'def': 6,
                'min': 0,
                'max': 40,
                'step': 1,
                'icon': 'ic-shiftskip',
                'hint': 'How many frames the latent is rolled by each step.',
            },
            {
                'key': 'loop_start',
                'type': 'knob',
                'label': 'Loop start',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-loopstart',
                'hint': 'Fraction of the schedule to start looping at.',
            },
            {
                'key': 'loop_end',
                'type': 'knob',
                'label': 'Loop end',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-loopend',
                'hint': 'Fraction of the schedule to stop at.',
            },
            {
                'key': 'freeinit',
                'type': 'toggle',
                'label': 'FreeInit',
                'def': False,
                'icon': 'ic-freeinit',
                'hint': 'Re-samples the clip N times, each time re-using the '
                'low-frequency structure of the last. Costs N renders and is '
                'the strongest fix there is for temporal flicker.',
            },
            {
                'key': 'freeinit_iters',
                'type': 'int',
                'label': 'FreeInit passes',
                'def': 3,
                'min': 1,
                'max': 10,
                'step': 1,
                'icon': 'ic-fiiters',
                'hint': 'Render time multiplies by this. 2 is usually enough to see whether it is helping.',
            },
            {
                'key': 'freeinit_method',
                'type': 'select',
                'label': 'FreeInit filter',
                'def': 'ideal',
                'icon': 'ic-fimethod',
                'options': [
                    {'v': 'ideal', 'l': 'ideal'},
                    {'v': 'butterworth', 'l': 'butterworth'},
                    {'v': 'gaussian', 'l': 'gaussian'},
                    {'v': 'none', 'l': 'none'},
                ],
                'hint': 'The low-pass filter used to keep the structure between passes.',
            },
            {
                'key': 'freeinit_n',
                'type': 'int',
                'label': 'FreeInit order',
                'def': 4,
                'min': 1,
                'max': 10,
                'step': 1,
                'icon': 'ic-fin',
                'hint': 'Butterworth filter order. Ignored by the other filters.',
            },
            {
                'key': 'freeinit_ds',
                'type': 'knob',
                'label': 'FreeInit spatial',
                'def': 1.0,
                'min': 0.0,
                'max': 10.0,
                'step': 0.05,
                'icon': 'ic-fids',
                'hint': 'Spatial cut-off. Lower keeps less spatial structure between passes.',
            },
            {
                'key': 'freeinit_dt',
                'type': 'knob',
                'label': 'FreeInit temporal',
                'def': 1.0,
                'min': 0.0,
                'max': 10.0,
                'step': 0.05,
                'icon': 'ic-fidt',
                'hint': 'Temporal cut-off — this is the one that actually suppresses '
                'flicker. Lower it before you touch the spatial one.',
            },
        ],
    },
    {
        'id': 'decode',
        'title': 'DECODE',
        'icon': 'ic-vae',
        'place': 'left',
        'sub': 'How the finished latent becomes pixels (node 40). Only the '
        'normalisation changes the picture; the rest changes the VRAM '
        'spike at the very end of the render.',
        'params': [
            {
                'key': 'vae_norm',
                'type': 'select',
                'label': 'Decode normalisation',
                'def': 'default',
                'icon': 'ic-vaenorm',
                'options': [
                    {'v': 'default', 'l': 'default'},
                    {'v': 'minmax', 'l': 'minmax — rescale to the range'},
                    {'v': 'none', 'l': 'none — raw'},
                ],
                'hint': 'minmax is the fix for a clip that comes back washed out or '
                'clipped; it is also the one that can flatten a deliberately '
                'low-contrast grade.',
            },
            {
                'key': 'tile_x',
                'type': 'int',
                'label': 'Tile width',
                'def': 272,
                'min': 40,
                'max': 2048,
                'step': 8,
                'icon': 'ic-tilex',
                'hint': 'Only read when VAE tiling is on. Bigger tiles = fewer seams and more VRAM.',
            },
            {
                'key': 'tile_y',
                'type': 'int',
                'label': 'Tile height',
                'def': 272,
                'min': 40,
                'max': 2048,
                'step': 8,
                'icon': 'ic-tiley',
                'hint': 'Only read when VAE tiling is on.',
            },
            {
                'key': 'tile_stride_x',
                'type': 'int',
                'label': 'Tile stride X',
                'def': 144,
                'min': 32,
                'max': 2040,
                'step': 8,
                'icon': 'ic-stridex',
                'hint': 'Overlap = tile width minus stride. Too small an overlap is '
                'where visible tile seams come from.',
            },
            {
                'key': 'tile_stride_y',
                'type': 'int',
                'label': 'Tile stride Y',
                'def': 128,
                'min': 32,
                'max': 2040,
                'step': 8,
                'icon': 'ic-stridey',
                'hint': 'Same on the vertical axis.',
            },
        ],
    },
]
