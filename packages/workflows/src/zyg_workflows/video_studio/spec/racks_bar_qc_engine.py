# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, bottom bar — QC & DEBUG, NOT BUILT, EXPERIMENTAL, ENGINE.

Moved verbatim (lines 3090-3725 of the old single-file spec.py). The probes,
the marked-absent list, and the two racks that moved off the left rail into
the right-hand end of the dock. ENGINE stays LAST — both strips draw their
racks in list order, so last here is the far-right block of the dock.
"""

from ..options import _DEF_PATHWAY, _lora_options

_RACKS_BAR_QC_ENGINE = [
    {
        'id': 'qc',
        'title': 'QC & DEBUG',
        'icon': 'ic-shield',
        'place': 'bar',
        'sub': 'Gates that can reject a render, measurements written beside it, and what the log tells you.',
        'params': [
            {
                'key': 'motion_gate',
                'type': 'toggle',
                'label': 'Frozen-clip gate',
                'def': True,
                'icon': 'ic-shield',
                'hint': 'Measures mean absolute frame difference on the RAW render, '
                'before any finishing — so a grade or a fade can never be '
                'what makes a frozen clip look like it passed.',
            },
            {
                'key': 'motion_thresh',
                'type': 'knob',
                'label': 'Freeze threshold',
                'def': 0.02,
                'min': 0.0,
                'max': 0.3,
                'step': 0.005,
                'icon': 'ic-threshold',
                'hint': 'How still counts as frozen. Raise it for a deliberately '
                'quiet shot — or the gate will keep rejecting the take you '
                'asked for.',
            },
            {
                'key': 'black_gate',
                'type': 'toggle',
                'label': 'Black-frame gate',
                'def': False,
                'icon': 'ic-blackgate',
                'hint': 'ffmpeg blackdetect. Rejects a render with a run of black '
                'frames — the signature of a VAE decode that fell over '
                'partway rather than failing outright.',
            },
            {
                'key': 'freeze_gate',
                'type': 'toggle',
                'label': 'Duplicate-frame gate',
                'def': False,
                'icon': 'ic-freezegate',
                'hint': 'ffmpeg freezedetect, rejecting on ANY stall of half a '
                'second. The frozen-clip gate reads the same detector but '
                'reduces it to a duration fraction, so a clip that moves '
                'overall and stalls in the middle passes that one and '
                'fails this one. Not an independent measurement — a '
                'second reading of the same one.',
            },
            {
                'key': 'scene_report',
                'type': 'toggle',
                'label': 'Scene-cut report',
                'def': False,
                'icon': 'ic-scenecut',
                'hint': 'ffmpeg scdet, logged not gated. A cut inside a single '
                'generated clip means the model changed its mind — usually '
                'at a chained sub-clip seam.',
            },
            {
                'key': 'scope_export',
                'type': 'select',
                'label': 'Write a scope',
                'def': 'off',
                'icon': 'ic-scope',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': 'waveform', 'l': 'waveform — exposure'},
                    {'v': 'vectorscope', 'l': 'vectorscope — colour'},
                    {'v': 'histogram', 'l': 'histogram'},
                ],
                'hint': 'Renders the scope of the middle frame to a PNG beside the '
                'clip. The only way to say "the blacks are crushed" as a '
                'measurement rather than an impression.',
            },
            {
                'key': 'motion_plot',
                'type': 'toggle',
                'label': 'Per-frame motion log',
                'def': False,
                'icon': 'ic-plot',
                'hint': 'Writes the frame-to-frame difference series as JSON. Turns '
                '"it stalls near the end" into a number you can point at.',
            },
            {
                'key': 'probe_report',
                'type': 'toggle',
                'label': 'Write a probe report',
                'def': False,
                'icon': 'ic-probe',
                'hint': 'ffprobe of the finished file — real duration, real fps, '
                'real bitrate — written beside it. Catches a finishing chain '
                'that silently changed the length.',
            },
            {
                'key': 'save_graph',
                'type': 'toggle',
                'label': 'Save the graph',
                'def': False,
                'icon': 'ic-graphjson',
                'hint': 'Dumps the exact ComfyUI graph and override dict that was '
                'submitted. This is the artefact that proves which node a '
                'dial reached; the log only says what was intended.',
            },
            {
                'key': 'save_params',
                'type': 'toggle',
                'label': 'Save the settings',
                'def': False,
                'icon': 'ic-paramjson',
                'hint': 'Writes every non-default dial beside the clip, so a clip '
                'found on disk months later can still say how it was made.',
            },
            {
                'key': 'retries',
                'type': 'int',
                'label': 'Retries',
                'def': 1,
                'min': 0,
                'max': 4,
                'step': 1,
                'icon': 'ic-refresh',
                'hint': 'Re-rolls at a new seed when a gate rejects the render. Each retry is a full render.',
            },
            {
                'key': 'keep_subclips',
                'type': 'toggle',
                'label': 'Keep sub-clips',
                'def': False,
                'icon': 'ic-savelayers',
                'hint': 'Keeps each chained piece and its hand-off frame instead of '
                'deleting them — how you find which link in a chain drifted.',
            },
            {
                'key': 'debug_trace',
                'type': 'toggle',
                'label': 'Debug trace',
                'def': False,
                'icon': 'ic-bug',
                'hint': 'Logs the full node-override dict per sub-clip.',
            },
            {
                'key': 'dry_run',
                'type': 'toggle',
                'label': 'Dry run',
                'def': False,
                'icon': 'ic-flask',
                'hint': 'Build the prompt and the graph, log both, submit nothing. '
                'The job then ends in error BY DESIGN — that is the dry run '
                'reporting it rendered nothing, not a failure.',
            },
        ],
    },
    {
        'id': 'notbuilt',
        'title': 'NOT BUILT',
        'icon': 'ic-hardhat',
        'place': 'bar',
        'sub': 'Options a video console should have that THIS one does not yet. '
        'Listed so the gap is visible and dated rather than silent — every '
        'cell here is marked and does nothing. 2026-09-14: eight cells '
        'left this rack because they were built — audio bed, SFX layer, '
        'ducking, loudness (AUDIO), AI upscale and AI interpolation '
        '(FINISH), matte/key (OVERLAY) and the multi-shot timeline '
        '(SHOTS). What is left is the character-control family, which '
        'waits on its own tree.',
        'params': [
            {
                'key': 'nb_vace',
                'type': 'toggle',
                'label': 'VACE control',
                'def': False,
                'icon': 'ic-vace',
                'todo': True,
                'hint': 'A different graph (Wan2_1-VACE_module) with its own control-'
                'plate discipline. Movement Studio already has the plate '
                'tooling and the measured defaults.',
            },
            {
                'key': 'nb_pose',
                'type': 'toggle',
                'label': 'Pose control',
                'def': False,
                'icon': 'ic-pose',
                'todo': True,
                'hint': 'Needs a pose plate per frame. Same tooling as VACE.',
            },
            {
                'key': 'nb_depth',
                'type': 'toggle',
                'label': 'Depth control',
                'def': False,
                'icon': 'ic-depth',
                'todo': True,
                'hint': 'Needs a depth plate per frame.',
            },
            {
                'key': 'nb_face_restore',
                'type': 'toggle',
                'label': 'Face restore',
                'def': False,
                'icon': 'ic-facefix',
                'todo': True,
                'hint': 'Per-frame, and it would fight the identity LoRA it is '
                'supposed to be preserving. Needs measuring before it ships.',
            },
            {
                'key': 'nb_prompt_extend',
                'type': 'toggle',
                'label': 'LLM prompt extender',
                'def': False,
                'icon': 'ic-llm',
                'todo': True,
                'hint': 'WanVideoPromptExtender exists in the wrapper but needs a '
                'local LLM configured for it, and every LLM call in this '
                'project has to go through the logged SDK path.',
            },
        ],
    },
    {
        # 2026-09-05: moved off the LEFT rail to the BOTTOM bar. It is the one
        # left-rail rack that is not part of the render path you set up before a
        # take: 14 switches you turn on one at a time against a pinned seed,
        # which is dock work, not pipeline work.
        # 2026-09-06: no longer the last rack — ENGINE followed it into the dock
        # and sits to the RIGHT of it.
        'id': 'experimental',
        'title': 'EXPERIMENTAL',
        'icon': 'ic-atom',
        'place': 'bar',
        'sub': "The wrapper's WanVideoExperimentalArgs node. All of it is real and "
        'none of it is safe to leave on by default — change one at a time '
        'against a pinned seed.',
        'params': [
            {
                'key': 'cfg_zero_star',
                'type': 'toggle',
                'label': 'CFG-Zero*',
                'def': False,
                'icon': 'ic-zerostar',
                'hint': 'Rescales the guidance direction per step. Usually a small '
                'win in colour and contrast stability at higher CFG.',
            },
            {
                'key': 'zero_init',
                'type': 'toggle',
                'label': 'Zero init',
                'def': False,
                'icon': 'ic-zeroinit',
                'hint': 'Zero the first N steps of the guidance term. Only does anything with Zero steps above 0.',
            },
            {
                'key': 'zero_star_steps',
                'type': 'int',
                'label': 'Zero steps',
                'def': 0,
                'min': 0,
                'max': 20,
                'step': 1,
                'icon': 'ic-zerosteps',
                'hint': 'How many opening steps run unguided. 1–2 loosens a stiff '
                'composition; more and the prompt stops arriving.',
            },
            {
                'key': 'fresca',
                'type': 'toggle',
                'label': 'FreSca',
                'def': False,
                'icon': 'ic-fresca',
                'hint': 'Scales guidance differently for low and high spatial '
                'frequencies — more fine detail without more CFG contrast.',
            },
            {
                'key': 'fresca_low',
                'type': 'knob',
                'label': 'FreSca low',
                'def': 1.0,
                'min': 0.0,
                'max': 4.0,
                'step': 0.01,
                'icon': 'ic-frescalow',
                'hint': 'Gain on the low frequencies — the large shapes. Leave at 1.',
            },
            {
                'key': 'fresca_high',
                'type': 'knob',
                'label': 'FreSca high',
                'def': 1.25,
                'min': 0.0,
                'max': 4.0,
                'step': 0.01,
                'icon': 'ic-frescahigh',
                'hint': 'Gain on the high frequencies — detail and texture. 1.2–1.4 '
                'is the useful window; past that it is just sharpening halo.',
            },
            {
                'key': 'fresca_cutoff',
                'type': 'int',
                'label': 'FreSca cutoff',
                'def': 20,
                'min': 0,
                'max': 200,
                'step': 1,
                'icon': 'ic-frescacut',
                'hint': 'Where low stops and high starts, in frequency bins.',
            },
            {
                'key': 'tcfg',
                'type': 'toggle',
                'label': 'Tangential CFG',
                'def': False,
                'icon': 'ic-tcfg',
                'hint': 'Projects the guidance onto the tangent of the denoising '
                'trajectory — less over-saturation at high CFG.',
            },
            {
                'key': 'raag_alpha',
                'type': 'knob',
                'label': 'RAAG alpha',
                'def': 0.0,
                'min': 0.0,
                'max': 10.0,
                'step': 0.05,
                'icon': 'ic-raag',
                'hint': 'Residual-adaptive guidance. 0 = off. Adapts the guidance '
                'weight to how much the residual is still changing.',
            },
            {
                'key': 'tsr',
                'type': 'toggle',
                'label': 'Temporal score rescale',
                'def': False,
                'icon': 'ic-tsr',
                'hint': 'Rescales the score across the time axis. Aimed squarely at '
                'clips that drift brighter or darker over their length.',
            },
            {
                'key': 'tsr_k',
                'type': 'knob',
                'label': 'TSR k',
                'def': 0.95,
                'min': 0.0,
                'max': 4.0,
                'step': 0.01,
                'icon': 'ic-tsrk',
                'hint': 'Rescale strength.',
            },
            {
                'key': 'tsr_sigma',
                'type': 'knob',
                'label': 'TSR sigma',
                'def': 1.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-tsrsigma',
                'hint': 'Which noise levels the rescale applies over.',
            },
            {
                'key': 'bidirectional',
                'type': 'toggle',
                'label': 'Bidirectional sampling',
                'def': False,
                'icon': 'ic-bidir',
                'hint': 'Samples forward and backward in time and merges. Roughly '
                'doubles the render; helps most on a clip whose ending has '
                'to meet a fixed end frame.',
            },
            {
                'key': 'attn_split_steps',
                'type': 'text',
                'label': 'Attention split steps',
                'def': '',
                'icon': 'ic-attnsplit',
                'hint': 'Comma-separated steps at which to split the video attention '
                '— a memory trick for very long clips. Blank = off.',
            },
        ],
    },
    {
        # 2026-09-06: moved off the LEFT rail to the BOTTOM bar, kept LAST in
        # RACKS so it renders to the RIGHT of EXPERIMENTAL — both strips draw
        # their racks in list order, so last here is the far-right block of the
        # dock. The rest of the engine (SOURCE, MEMORY, SAMPLER, ACCELERATE,
        # GUIDANCE, LONG CLIP, DECODE) stays on the left rail.
        'id': 'engine',
        'title': 'ENGINE',
        'icon': 'ic-chip',
        'place': 'bar',
        'sub': 'Which model, which LoRA, which attention and at what precision. '
        'These change the graph itself (nodes 1 / 2 / 4 / 6-9).',
        'params': [
            {
                'key': 'pathway',
                'type': 'select',
                'label': 'Model pathway',
                'def': _DEF_PATHWAY,
                'icon': 'ic-chip',
                'options': [
                    {'v': 'wan22', 'l': 'Wan2.2 A14B — dual expert (best)'},
                    {'v': 'wan21_480p', 'l': 'Wan2.1 I2V 14B — 480P'},
                    {'v': 'wan21_720p', 'l': 'Wan2.1 I2V 14B — 720P'},
                ],
                'hint': 'Wan2.2 splits the step budget across a HIGH-noise and a '
                'LOW-noise expert. The 2.1 pathways are single-model and '
                'the only ones with a CLIP-vision encoder.',
            },
            {
                'key': 'lightning',
                'type': 'toggle',
                'label': 'Lightning 4-step',
                'def': False,
                'icon': 'ic-bolt',
                'hint': 'The A14B distill LoRA pair. Forces steps/cfg/shift to '
                '4 / 1.0 / 5.0 — roughly 6x faster, visibly softer. Wan2.2 '
                'only; ignored (and logged) on a 2.1 pathway.',
            },
            {
                'key': 'lora',
                'type': 'select',
                'label': 'LoRA',
                'def': '',
                'icon': 'ic-layers',
                'options': _lora_options(),
                'hint': 'Every Wan LoRA on disk. Non-Wan LoRAs are filtered out — an '
                'SDXL or FLUX LoRA in a Wan graph is an error, not a look.',
            },
            {
                'key': 'lora_strength',
                'type': 'knob',
                'label': 'LoRA strength',
                'def': 1.0,
                'min': 0.0,
                'max': 2.0,
                'step': 0.05,
                'icon': 'ic-slider',
                'hint': 'Identity LoRAs usually want 0.6–0.9 here; a full 1.0 tends '
                'to freeze the motion along with the face.',
            },
            {
                'key': 'expert_boundary',
                'type': 'knob',
                'label': 'Expert boundary',
                'def': 0.5,
                'min': 0.1,
                'max': 0.9,
                'step': 0.05,
                'icon': 'ic-split',
                'hint': 'Wan2.2 only. The fraction of steps the HIGH-noise expert '
                'runs before the LOW expert takes over. Higher = more '
                'structure and motion, less fine detail.',
            },
            {
                'key': 'attention',
                'type': 'select',
                'label': 'Attention',
                'def': 'sdpa',
                'icon': 'ic-network',
                'options': [
                    {'v': 'sdpa', 'l': 'sdpa — always available'},
                    {'v': 'sageattn', 'l': 'sage — faster, needs sageattention'},
                    {'v': 'flash_attn_2', 'l': 'flash 2'},
                    {'v': 'flash_attn_3', 'l': 'flash 3'},
                    {'v': 'radial_sage_attention', 'l': 'radial sage'},
                    {'v': 'comfy', 'l': 'comfy default'},
                ],
                'hint': 'nodes 1/7 attention_mode. Anything but sdpa fails at load '
                'time if the kernel is not installed — the log says which.',
            },
            {
                'key': 'precision',
                'type': 'select',
                'label': 'Base precision',
                'def': 'bf16',
                'icon': 'ic-bits',
                'options': [
                    {'v': 'bf16', 'l': 'bf16'},
                    {'v': 'fp16', 'l': 'fp16'},
                    {'v': 'fp16_fast', 'l': 'fp16 fast'},
                    {'v': 'fp32', 'l': 'fp32'},
                ],
                'hint': 'Compute precision of the transformer. fp16_fast trades a '
                'little accuracy for tensor-core throughput.',
            },
            {
                'key': 'quantization',
                'type': 'select',
                'label': 'Quantisation',
                'def': '',
                'icon': 'ic-compress',
                'options': [
                    {'v': '', 'l': 'as the graph ships it'},
                    {'v': 'disabled', 'l': 'disabled — full weights'},
                    {'v': 'fp8_e4m3fn', 'l': 'fp8 e4m3fn'},
                    {'v': 'fp8_e4m3fn_fast', 'l': 'fp8 e4m3fn fast'},
                    {'v': 'fp8_e4m3fn_scaled', 'l': 'fp8 e4m3fn scaled'},
                    {'v': 'fp8_e5m2', 'l': 'fp8 e5m2'},
                ],
                'hint': 'The checkpoints on disk are already fp8 — dropping this to '
                '"disabled" does not restore precision that was never there, '
                'it just costs VRAM.',
            },
            {
                'key': 'load_device',
                'type': 'select',
                'label': 'Load device',
                'def': 'offload_device',
                'icon': 'ic-device',
                'options': [
                    {'v': 'offload_device', 'l': 'offload — load to system RAM'},
                    {'v': 'main_device', 'l': 'main — load straight to VRAM'},
                ],
                'hint': 'nodes 1/7 load_device. Loading straight to VRAM saves a '
                "transfer per sub-clip and costs the model's whole footprint "
                'for the length of the job.',
            },
            {
                'key': 'rms_norm',
                'type': 'select',
                'label': 'RMS norm',
                'def': 'default',
                'icon': 'ic-norm',
                'options': [{'v': 'default', 'l': 'default (wrapper kernel)'}, {'v': 'pytorch', 'l': 'pytorch'}],
                'hint': 'nodes 1/7 rms_norm_function. The pytorch path is slower and '
                'is the one to try when a render comes back as pure noise.',
            },
            {
                'key': 'radial_attn',
                'type': 'toggle',
                'label': 'Radial attention',
                'def': False,
                'icon': 'ic-radial',
                'hint': 'Inserts WanVideoSetRadialAttention after the loader — sparse '
                'attention outside a dense core, which gets cheaper the '
                'longer the clip is. Below ~81 frames it is a loss.',
            },
            {
                'key': 'radial_dense_blocks',
                'type': 'int',
                'label': 'Radial dense blocks',
                'def': 1,
                'min': 0,
                'max': 40,
                'step': 1,
                'icon': 'ic-denseblocks',
                'hint': 'How many transformer blocks stay fully dense. More = closer to normal attention and slower.',
            },
            {
                'key': 'radial_dense_steps',
                'type': 'int',
                'label': 'Radial dense steps',
                'def': 2,
                'min': 0,
                'max': 100,
                'step': 1,
                'icon': 'ic-densesteps',
                'hint': 'How many of the first timesteps run dense. The early steps '
                'set the composition, so starving them shows.',
            },
            {
                'key': 'radial_decay',
                'type': 'knob',
                'label': 'Radial decay',
                'def': 0.2,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-decay',
                'hint': 'How fast attention thins out with distance. Higher = '
                'sparser and faster, with more temporal drift.',
            },
            {
                'key': 'radial_block_size',
                'type': 'select',
                'label': 'Radial block size',
                'def': '128',
                'icon': 'ic-blocksize',
                'options': [{'v': '128', 'l': '128'}, {'v': '64', 'l': '64'}],
                'hint': 'Sparsity granularity. 64 is finer and slower.',
            },
            {
                'key': 't5_precision',
                'type': 'select',
                'label': 'T5 precision',
                'def': '',
                'icon': 'ic-t5',
                'options': [
                    {'v': '', 'l': 'as the graph ships it'},
                    {'v': 'bf16', 'l': 'bf16'},
                    {'v': 'fp16', 'l': 'fp16'},
                    {'v': 'fp32', 'l': 'fp32'},
                ],
                'hint': 'node 2. The text encoder runs once per render, so fp32 here '
                'costs seconds, not minutes — worth it on a long prompt.',
            },
            {
                'key': 'vae_precision',
                'type': 'select',
                'label': 'VAE precision',
                'def': '',
                'icon': 'ic-vaeprec',
                'options': [
                    {'v': '', 'l': 'as the graph ships it'},
                    {'v': 'bf16', 'l': 'bf16'},
                    {'v': 'fp16', 'l': 'fp16'},
                    {'v': 'fp32', 'l': 'fp32'},
                ],
                'hint': 'node 4. fp16 decode is where colour banding in flat skies '
                'usually comes from; fp32 costs VRAM at the decode spike.',
            },
            {
                'key': 't5_device',
                'type': 'select',
                'label': 'T5 device',
                'def': 'gpu',
                'icon': 'ic-cpugpu',
                'options': [{'v': 'gpu', 'l': 'gpu'}, {'v': 'cpu', 'l': 'cpu — slower, no VRAM'}],
                'hint': 'node 20 device. Encoding the prompt on the CPU frees the '
                'T5 footprint for the sampler on a tight card.',
            },
            {
                'key': 't5_cache',
                'type': 'toggle',
                'label': 'Cache text embeds',
                'def': False,
                'icon': 'ic-diskcache',
                'hint': 'node 20 use_disk_cache. Re-uses the encoded prompt across '
                'renders. Only pays when you are sweeping the sampler with '
                'the prompt held still — which is most of a variant run.',
            },
        ],
    },
]
