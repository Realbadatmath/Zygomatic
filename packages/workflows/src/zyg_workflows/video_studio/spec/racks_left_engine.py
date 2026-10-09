# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, left rail — SOURCE, MEMORY, ACCELERATE.

Moved verbatim (lines 1076-1510 of the old single-file spec.py). The head of
the left rail: what goes in, the memory it runs in, the accelerators.
"""

_RACKS_LEFT_ENGINE = [
    # ═══════════════════════════════ LEFT RAIL — how the model computes it
    # In pipeline order down the rail: what goes in, the memory it runs in, the
    # accelerators, the guidance, the long-clip window, and the decode that turns
    # latents into frames. SAMPLER left for the RIGHT rail on 2026-09-06 — it is
    # dialled per shot, not set once with the engine. Everything AFTER the frames
    # exist lives in the bottom bar — as do EXPERIMENTAL and, since 2026-09-06,
    # ENGINE (which model / which LoRA), at the far right of the dock.
    {
        'id': 'source',
        'title': 'SOURCE',
        'icon': 'ic-inject',
        'place': 'left',
        'sub': 'Which frames of the injected clip seed the render, and how hard '
        'they constrain it (graph nodes 10 / 11 / 12 / 13).',
        'params': [
            {
                'key': 'start_from',
                'type': 'select',
                'label': 'Start frame',
                'def': 'last',
                'icon': 'ic-firstlast',
                'options': [
                    {'v': 'last', 'l': 'last frame — continue the clip'},
                    {'v': 'first', 'l': 'first frame — re-take the clip'},
                    {'v': 'time', 'l': 'at timestamp…'},
                ],
                'hint': 'Continuing off the last frame extends the shot; off the '
                'first frame re-rolls the same shot with new settings.',
            },
            {
                'key': 'start_at_s',
                'type': 'knob',
                'label': 'Timestamp',
                'def': 0.0,
                'min': 0.0,
                'max': 60.0,
                'step': 0.1,
                'unit': 's',
                'icon': 'ic-marker',
                'hint': 'Only used when Start frame is "at timestamp". Seconds into the injected clip.',
            },
            {
                'key': 'noise_aug',
                'type': 'knob',
                'label': 'Start-frame noise',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-noise',
                'hint': 'node 11 noise_aug_strength. Above 0 loosens the grip of the '
                'starting frame — more invention, more drift. 0.05–0.15 '
                'unfreezes a clip that keeps coming back static.',
            },
            {
                'key': 'start_latent_strength',
                'type': 'knob',
                'label': 'Start latent',
                'def': 1.0,
                'min': 0.0,
                'max': 2.0,
                'step': 0.05,
                'icon': 'ic-anchor',
                'hint': 'node 11 start_latent_strength. How strongly frame 1 is '
                'pinned to the injected image. Below 1 lets the opening '
                'reinterpret; above 1 hard-locks it.',
            },
            {
                'key': 'end_latent_strength',
                'type': 'knob',
                'label': 'End latent',
                'def': 1.0,
                'min': 0.0,
                'max': 2.0,
                'step': 0.05,
                'icon': 'ic-anchorend',
                'hint': 'node 11 end_latent_strength — the tail-end conditioning '
                'weight. Lower it when chained sub-clips stiffen up.',
            },
            {
                'key': 'end_frame',
                'type': 'select',
                'label': 'End frame (FLF2V)',
                'def': 'off',
                'icon': 'ic-endframe',
                'options': [
                    {'v': 'off', 'l': 'off — the model decides the ending'},
                    {'v': 'first', 'l': 'first frame of the source clip'},
                    {'v': 'last', 'l': 'last frame of the source clip'},
                    {'v': 'start', 'l': 'same as the start frame (loop)'},
                    {'v': 'time', 'l': 'at timestamp…'},
                ],
                'hint': 'First-last-frame conditioning: node 11 end_image. Give the '
                'shot a destination and Wan interpolates toward it. "Same as '
                'start" is the honest way to build a seamless loop — the '
                'Loop dial in FINISH only crossfades one.',
            },
            {
                'key': 'end_at_s',
                'type': 'knob',
                'label': 'End-frame timestamp',
                'def': 0.0,
                'min': 0.0,
                'max': 60.0,
                'step': 0.1,
                'unit': 's',
                'icon': 'ic-endmarker',
                'hint': 'Only used when End frame is "at timestamp".',
            },
            {
                'key': 'fl2v_model',
                'type': 'toggle',
                'label': 'FL2V conditioning',
                'def': True,
                'icon': 'ic-fl2v',
                'hint': 'node 11 fun_or_fl2v_model. Leave on for the Fun/FLF2V '
                'conditioning layout; turn it off only if an end frame '
                'produces a hard cut instead of an interpolation.',
            },
            {
                'key': 'augment_empty',
                'type': 'knob',
                'label': 'Augment empty frames',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-augment',
                'hint': 'node 11 augment_empty_frames. Noises the un-conditioned '
                'middle of an FLF2V run so it invents rather than '
                'cross-dissolving between the two ends.',
            },
            {
                'key': 'encode_tiled_vae',
                'type': 'toggle',
                'label': 'Tiled VAE encode',
                'def': False,
                'icon': 'ic-tilesenc',
                'hint': 'node 11 tiled_vae. Encodes the conditioning image in tiles. '
                'Only matters at 720p and above, where the encode alone can '
                'spike VRAM before a single step has run.',
            },
            {
                'key': 'resize_mode',
                'type': 'select',
                'label': 'Source fit',
                'def': 'off',
                'icon': 'ic-fit',
                'options': [
                    {'v': 'off', 'l': 'off — pass the frame through as-is'},
                    {'v': 'keep_input', 'l': 'keep input aspect'},
                    {'v': 'stretch_to_new', 'l': 'stretch to the render size'},
                    {'v': 'crop_to_new', 'l': 'crop to the render size'},
                ],
                'hint': 'Inserts WanVideoImageResizeToClosest between the loader and '
                'the encoder. Use it when the injected clip is a different '
                'shape from the Resolution you are rendering at — otherwise '
                'the encoder squashes it silently.',
            },
            {
                'key': 'clip_strength',
                'type': 'knob',
                'label': 'CLIP-vision strength',
                'def': 1.0,
                'min': 0.0,
                'max': 3.0,
                'step': 0.05,
                'icon': 'ic-clipvis',
                'hint': 'node 12 strength_1 — Wan2.1 pathways only (the 2.2 dual-'
                'expert graph has no CLIP vision encoder). Lower it to let '
                'the prompt overrule the look of the source frame.',
            },
            {
                'key': 'clip_crop',
                'type': 'select',
                'label': 'CLIP crop',
                'def': 'center',
                'icon': 'ic-cropcenter',
                'options': [{'v': 'center', 'l': 'centre crop'}, {'v': 'disabled', 'l': 'no crop — squash to square'}],
                'hint': 'node 12 crop, Wan2.1 only. A centre crop throws away the '
                'edges of a wide frame before the vision encoder sees it.',
            },
            {
                'key': 'clip_combine',
                'type': 'select',
                'label': 'CLIP combine',
                'def': 'average',
                'icon': 'ic-combine',
                'options': [
                    {'v': 'average', 'l': 'average'},
                    {'v': 'sum', 'l': 'sum'},
                    {'v': 'concat', 'l': 'concat'},
                    {'v': 'batch', 'l': 'batch'},
                ],
                'hint': 'node 12 combine_embeds, Wan2.1 only. Only meaningful with '
                'more than one vision image; kept exposed because the node '
                'default silently changes the single-image path too.',
            },
        ],
    },
    {
        'id': 'memory',
        'title': 'MEMORY',
        'icon': 'ic-ram',
        'place': 'left',
        'sub': 'Where the weights live during the render, and whether the graph is '
        'compiled. None of this changes the picture — it changes whether '
        'the picture fits.',
        'params': [
            {
                'key': 'force_offload',
                'type': 'toggle',
                'label': 'Force offload',
                'def': True,
                'icon': 'ic-ram',
                'hint': 'Push each stage back to system RAM as soon as it is done. '
                'On by default; turning it off is faster and is the first '
                'thing to blame for an out-of-memory error.',
            },
            {
                'key': 'vae_tiling',
                'type': 'toggle',
                'label': 'VAE tiling',
                'def': False,
                'icon': 'ic-tiles',
                'hint': 'node 40 enable_vae_tiling. Decodes in tiles — much less '
                'VRAM at the decode spike, and a faint seam risk. The DECODE '
                'rack sets the tile geometry.',
            },
            {
                'key': 'block_swap',
                'type': 'int',
                'label': 'Block swap',
                'def': 0,
                'min': 0,
                'max': 48,
                'step': 1,
                'icon': 'ic-swap',
                'hint': 'How many transformer blocks live in system RAM and are '
                'swapped in per step. 0 = off. This is THE lever that makes '
                '720p fit on a 24GB card; every swapped block costs time.',
            },
            {
                'key': 'swap_img_emb',
                'type': 'toggle',
                'label': 'Offload image embeds',
                'def': False,
                'icon': 'ic-swapimg',
                'hint': 'Keeps the image conditioning off the card too. Only useful once Block swap is already on.',
            },
            {
                'key': 'swap_txt_emb',
                'type': 'toggle',
                'label': 'Offload text embeds',
                'def': False,
                'icon': 'ic-swaptxt',
                'hint': 'Same for the text conditioning. Small, but free.',
            },
            {
                'key': 'prefetch_blocks',
                'type': 'int',
                'label': 'Prefetch blocks',
                'def': 0,
                'min': 0,
                'max': 40,
                'step': 1,
                'icon': 'ic-prefetch',
                'hint': 'Pull the next N blocks across while the current one '
                'computes. Recovers much of the speed block swap costs, at '
                'the price of holding N extra blocks in VRAM.',
            },
            {
                'key': 'nonblocking_swap',
                'type': 'toggle',
                'label': 'Async transfers',
                'def': False,
                'icon': 'ic-async',
                'hint': 'Non-blocking host-to-device copies. Pairs with prefetch; on its own it does very little.',
            },
            {
                'key': 'vram_offload',
                'type': 'select',
                'label': 'VRAM management',
                'def': 'off',
                'icon': 'ic-vram',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': '0.25', 'l': 'offload 25%'},
                    {'v': '0.5', 'l': 'offload 50%'},
                    {'v': '0.75', 'l': 'offload 75%'},
                    {'v': '1.0', 'l': 'offload 100%'},
                ],
                'hint': 'WanVideoVRAMManagement — a blunter, whole-model version of '
                'block swap. Use one or the other, not both.',
            },
            {
                'key': 'torch_compile',
                'type': 'select',
                'label': 'torch.compile',
                'def': 'off',
                'icon': 'ic-compile',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': 'default', 'l': 'default'},
                    {'v': 'reduce-overhead', 'l': 'reduce overhead'},
                    {'v': 'max-autotune', 'l': 'max autotune'},
                    {'v': 'max-autotune-no-cudagraphs', 'l': 'max autotune, no graphs'},
                ],
                'hint': 'Compiles the transformer blocks. The FIRST render after '
                'turning this on pays a long one-off compile; every render '
                'after it is faster until anything about the shape changes.',
            },
            {
                'key': 'compile_backend',
                'type': 'select',
                'label': 'Compile backend',
                'def': 'inductor',
                'icon': 'ic-backend',
                'options': [{'v': 'inductor', 'l': 'inductor'}, {'v': 'cudagraphs', 'l': 'cudagraphs'}],
                'hint': 'Only read when torch.compile is on.',
            },
            {
                'key': 'compile_blocks_only',
                'type': 'toggle',
                'label': 'Compile blocks only',
                'def': True,
                'icon': 'ic-blocksonly',
                'hint': 'Compile the transformer blocks rather than the whole model. '
                'Leave on — the full-graph path recompiles constantly and '
                'is where compile times go from minutes to tens of minutes.',
            },
        ],
    },
    {
        'id': 'accel',
        'title': 'ACCELERATE',
        'icon': 'ic-rocket',
        'place': 'left',
        'sub': 'Step caching — skip transformer evaluations whose result barely '
        "changes. All three feed the sampler's one cache_args input, so "
        'exactly one can be active.',
        'params': [
            {
                'key': 'cache_mode',
                'type': 'select',
                'label': 'Cache',
                'def': 'off',
                'icon': 'ic-cache',
                'options': [
                    {'v': 'off', 'l': 'off — evaluate every step'},
                    {'v': 'teacache', 'l': 'TeaCache'},
                    {'v': 'magcache', 'l': 'MagCache'},
                    {'v': 'easycache', 'l': 'EasyCache'},
                ],
                'hint': 'Roughly 1.5–2x faster for a measurable loss of small motion '
                '— caching is exactly the thing that suppresses the detail '
                'the frozen-clip gate measures. Never benchmark motion with '
                'a cache on.',
            },
            {
                'key': 'cache_thresh',
                'type': 'knob',
                'label': 'Cache threshold',
                'def': 0.3,
                'min': 0.0,
                'max': 1.0,
                'step': 0.005,
                'icon': 'ic-cachethresh',
                'hint': 'How different a step has to be to be recomputed. Sensible '
                'ranges differ per cache: TeaCache ~0.3, MagCache ~0.02, '
                'EasyCache ~0.015 — the value is clamped to each.',
            },
            {
                'key': 'cache_start',
                'type': 'int',
                'label': 'Cache from step',
                'def': 1,
                'min': 0,
                'max': 60,
                'step': 1,
                'icon': 'ic-cachestart',
                'hint': 'Never cache step 0 — the first step sets the composition for the whole clip.',
            },
            {
                'key': 'cache_end',
                'type': 'int',
                'label': 'Cache to step',
                'def': -1,
                'min': -1,
                'max': 60,
                'step': 1,
                'icon': 'ic-cacheend',
                'hint': '-1 = to the last step.',
            },
            {
                'key': 'cache_device',
                'type': 'select',
                'label': 'Cache device',
                'def': 'offload_device',
                'icon': 'ic-cachedev',
                'options': [{'v': 'offload_device', 'l': 'system RAM'}, {'v': 'main_device', 'l': 'VRAM — faster'}],
                'hint': 'The cache holds residuals the size of a latent; in VRAM it '
                'is faster and competes with the model for room.',
            },
            {
                'key': 'teacache_coeff',
                'type': 'toggle',
                'label': 'TeaCache coefficients',
                'def': True,
                'icon': 'ic-coeff',
                'hint': 'Use the fitted per-model rescaling polynomial. Off is the '
                'raw L1 distance, which mis-triggers badly on Wan.',
            },
            {
                'key': 'teacache_mode',
                'type': 'select',
                'label': 'TeaCache mode',
                'def': 'e',
                'icon': 'ic-teamode',
                'options': [{'v': 'e', 'l': 'e — modulated input'}, {'v': 'e0', 'l': 'e0 — raw input'}],
                'hint': 'Which tensor the distance is measured on.',
            },
            {
                'key': 'magcache_k',
                'type': 'int',
                'label': 'MagCache K',
                'def': 4,
                'min': 0,
                'max': 6,
                'step': 1,
                'icon': 'ic-magk',
                'hint': 'How many consecutive steps MagCache may skip before it is forced to recompute one.',
            },
        ],
    },
]
