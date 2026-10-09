# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.racks_rail — the right-hand rail racks
(engine, windows, finish, gates)."""

from zyg_workflows.movement_studio.options import RESOLUTIONS

_RACKS_RAIL = [
    # ══════════════════════════════════ RAIL — how it is computed
    {
        'id': 'engine',
        'title': 'ENGINE',
        'icon': 'mv-engine',
        'place': 'rail',
        'sub': 'The sampler. These reach WanVideoSampler node 30 directly.',
        'params': [
            {
                'key': 'shift',
                'type': 'float',
                'label': 'Shift (motion amount)',
                'lb': 'Shift',
                'def': 5.0,
                'min': 1.0,
                'max': 12.0,
                'step': 0.25,
                'icon': 'mv-shift',
                'hint': "THE motion lever of this pipeline. The function's own default of 2.0 "
                'renders a frozen clip; 5.0 is the measured alive setting. Raise it for '
                'more movement, and expect identity to loosen as you do.',
            },
            {
                'key': 'steps',
                'type': 'int',
                'label': 'Steps',
                'def': 30,
                'min': 8,
                'max': 60,
                'step': 1,
                'icon': 'mv-steps',
                'hint': 'Denoise steps. Below ~20 the motion stops resolving; above ~40 you are '
                'paying GPU minutes for very little.',
            },
            {
                'key': 'cfg',
                'type': 'float',
                'label': 'CFG',
                'def': 6.0,
                'min': 1.0,
                'max': 12.0,
                'step': 0.25,
                'icon': 'mv-cfg',
                'hint': 'Prompt adherence. High CFG on a VACE graph fights the pin and produces '
                'the scorched over-contrast look before it produces obedience.',
            },
            {
                'key': 'seed',
                'type': 'int',
                'label': 'Seed',
                'def': 7,
                'min': 0,
                'max': 2147483647,
                'step': 1,
                'icon': 'mv-seed',
                'hint': 'Fixed by default so two renders differ only by what you changed. Use '
                'the dice in this bar to hunt a take.',
            },
            {
                'key': 'num_frames',
                'type': 'select',
                'label': 'Length',
                'def': '65',
                'icon': 'mv-length',
                'options': [
                    {'v': '17', 'l': '17 frames — ~1s probe'},
                    {'v': '33', 'l': '33 frames — ~2s preview'},
                    {'v': '49', 'l': '49 frames — ~3s'},
                    {'v': '65', 'l': '65 frames — ~4s (shippable)'},
                    {'v': '81', 'l': '81 frames — ~5s'},
                    {'v': '97', 'l': '97 frames — ~6s (needs windows)'},
                    {'v': '129', 'l': '129 frames — ~7.5s (needs windows)'},
                ],
                'hint': 'Every option is 4n+1: WanVideoVACEEncode builds ((n-1)//4)+1 latent '
                'frames and a count that is not 4n+1 silently truncates. Past ~81 '
                'frames turn Context windows on or the clip degrades at the tail.',
            },
            {
                'key': 'resolution',
                'type': 'select',
                'label': 'Resolution',
                'def': '832x480',
                'icon': 'mv-res',
                'options': [{'v': r, 'l': r} for r in RESOLUTIONS],
                'hint': 'The still is CROPPED to this aspect and resized — never letterboxed — '
                'so changing the aspect re-frames the shot. Sizes divisible by 16 are '
                'also the only ones the graded pin can run on.',
            },
            {
                'key': 'attention',
                'type': 'select',
                'label': 'Attention',
                'def': 'sdpa',
                'icon': 'mv-attn',
                'options': [
                    {'v': 'sdpa', 'l': 'sdpa — always available'},
                    {'v': 'sageattn', 'l': 'sageattn — faster if installed'},
                    {'v': 'flash_attn', 'l': 'flash_attn — if installed'},
                ],
                'hint': 'Sets ZYG_WAN_ATTENTION for this render only. A mode the box does not '
                'have installed fails at submit, not silently — check the log.',
            },
            {
                'key': 'timeout_s',
                'type': 'int',
                'label': 'Timeout',
                'def': 2400,
                'min': 300,
                'max': 10800,
                'step': 60,
                'icon': 'mv-timeout',
                'unit': 's',
                'hint': 'Sets ZYG_WAN_TIMEOUT_S for this render. A 129-frame windowed clip can '
                'genuinely need more than the 40-minute default.',
            },
        ],
    },
    {
        'id': 'windows',
        'title': 'LONG CLIPS',
        'icon': 'mv-windows',
        'place': 'rail',
        'sub': 'Overlapping context windows over one noise field. Off for short clips; '
        'mandatory past ~81 frames and for any beat schedule.',
        'params': [
            {
                'key': 'context_windows',
                'type': 'toggle',
                'label': 'Context windows',
                'lb': 'Windows',
                'def': False,
                'icon': 'mv-ctxon',
                'hint': 'Single-stream long video (FreeNoise): no segment boundaries, no '
                're-derivation. Also the only thing that makes a " | " beat schedule '
                'reachable — the wrapper picks a sub-prompt per window.',
            },
            {
                'key': 'context_frames',
                'type': 'int',
                'label': 'Window size',
                'def': 81,
                'min': 33,
                'max': 129,
                'step': 4,
                'icon': 'mv-ctxframes',
                'hint': 'Frames per window. Ignored while Context windows is off.',
            },
            {
                'key': 'context_overlap',
                'type': 'int',
                'label': 'Overlap',
                'def': 24,
                'min': 4,
                'max': 48,
                'step': 4,
                'icon': 'mv-ctxoverlap',
                'hint': 'Frames shared between neighbouring windows. Two research findings '
                'recommended opposite directions for this — the shipped value is the '
                'one that has actually rendered.',
            },
            {
                'key': 'context_stride',
                'type': 'int',
                'label': 'Stride',
                'def': 4,
                'min': 1,
                'max': 16,
                'step': 1,
                'icon': 'mv-ctxstride',
                'hint': 'Window advance. Floors to latent 1 inside the sampler, so small values '
                'here are not as different as they look.',
            },
            {
                'key': 'fuse_method',
                'type': 'select',
                'label': 'Fuse method',
                'def': 'pyramid',
                'icon': 'mv-fuse',
                'options': [
                    {'v': 'pyramid', 'l': 'pyramid — ramps across the whole overlap'},
                    {'v': 'linear', 'l': 'linear — the wrapper default'},
                ],
                'hint': 'linear ramps only at window edges, so a thin object placed 2-3px apart '
                'by two windows averages into a doubled edge. pyramid is passed '
                'explicitly because the wrapper default is silently linear.',
            },
        ],
    },
    {
        'id': 'finish',
        'title': 'FINISH',
        'icon': 'mv-finish',
        'place': 'rail',
        'sub': 'What happens to the clip after the sampler.',
        'params': [
            {
                'key': 'interpolate',
                'type': 'toggle',
                'label': 'Interpolate to 24fps',
                'lb': 'Interpolate',
                'def': True,
                'icon': 'mv-interp',
                'hint': 'RIFE pass over the 17fps render. Off leaves the native 17fps file, '
                'which is what you want when the clip is going into a pipeline that '
                'will retime it anyway.',
            },
        ],
    },
    {
        'id': 'gates',
        'title': 'GATES',
        'icon': 'mv-gates',
        'place': 'rail',
        'sub': 'The preflight checks. Every one of these is ON by default and each has '
        'a run behind it that it would have saved.',
        'params': [
            {
                'key': 'mask_gate',
                'type': 'toggle',
                'label': 'Mask preflight',
                'lb': 'Mask gate',
                'def': True,
                'icon': 'mv-maskgate',
                'hint': 'Blocks the submit when the mask fails its C3 checks. The mask this '
                'gate was written for would have been blocked here and saved 4.5 GPU '
                'hours. Off only to reproduce that.',
            },
            {
                'key': 'beat_gate',
                'type': 'toggle',
                'label': 'Beat-map gate',
                'lb': 'Beat gate',
                'def': True,
                'icon': 'mv-beatgate',
                'hint': 'Refuses a beat schedule whose beats are not all reachable by a context '
                'window. Off downgrades it to a loud warning and renders anyway.',
            },
            {
                'key': 'attest',
                'type': 'select',
                'label': 'Model attestation',
                'lb': 'Attestation',
                'def': 'warn',
                'icon': 'mv-attest',
                'options': [
                    {'v': 'warn', 'l': 'warn — log a mismatch, render on'},
                    {'v': 'strict', 'l': 'strict — refuse to submit'},
                ],
                'hint': 'Hash-verifies the LoRA chain, the T2V checkpoint, the VACE module and '
                'the VAE before any frame renders.',
            },
            {
                'key': 'beat_chars',
                'type': 'int',
                'label': 'Beat char cap',
                'lb': 'Beat chars',
                'def': 1500,
                'min': 200,
                'max': 4000,
                'step': 50,
                'icon': 'mv-beatchars',
                'hint': 'Per-beat prompt clipping, in characters. Raise it only if you know the '
                'beat still fits inside 512 umt5 tokens — past that the tail of your '
                'prompt is silently not read.',
            },
        ],
    },
]
