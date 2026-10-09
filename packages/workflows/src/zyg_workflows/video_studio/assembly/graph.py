# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio: the Wan graph itself — the node default table, _node, the
optional-args augmentation and the ENGINE/SAMPLER/SOURCE/DECODE overrides."""

from zyg_workflows import wan_video_service as _wan

from ..options import PATHWAYS


# Every SCALAR input of every node this file builds, at the value the node's
# own INPUT_TYPES declares as its default.
#
# This table is load-bearing, not belt-and-braces. ComfyUI fills a missing
# input from the node's default only for inputs the PROMPT declares; an
# optional input the prompt omits arrives as None. WanVideoWrapper then does
# things like `if vace_blocks_to_swap > 0`, which raises
# "'>' not supported between instances of 'NoneType' and 'int'" — measured on
# 2026-09-03 by a real render, not reasoned about. Link-typed inputs are
# deliberately absent: those the wrapper does test for None.
_NODE_DEFAULTS = {
    'WanVideoApplyNAG': {'inplace': True, 'nag_alpha': 0.25, 'nag_scale': 11.0, 'nag_tau': 2.5},
    'WanVideoBlockSwap': {
        'block_swap_debug': False,
        'blocks_to_swap': 20,
        'offload_img_emb': False,
        'offload_txt_emb': False,
        'prefetch_blocks': 0,
        'use_non_blocking': False,
        'vace_blocks_to_swap': 0,
    },
    'WanVideoContextOptions': {
        'context_frames': 81,
        'context_overlap': 16,
        'context_schedule': 'uniform_standard',
        'context_stride': 4,
        'freenoise': True,
        'fuse_method': 'linear',
        'verbose': False,
    },
    'WanVideoEasyCache': {
        'cache_device': 'offload_device',
        'easycache_thresh': 0.015,
        'end_step': -1,
        'start_step': 10,
    },
    'WanVideoEnhanceAVideo': {'end_percent': 1.0, 'start_percent': 0.0, 'weight': 2.0},
    'WanVideoExperimentalArgs': {
        'bidirectional_sampling': False,
        'cfg_zero_star': False,
        'fresca_freq_cutoff': 20,
        'fresca_scale_high': 1.25,
        'fresca_scale_low': 1.0,
        'raag_alpha': 0.0,
        'temporal_score_rescaling': False,
        'tsr_k': 0.95,
        'tsr_sigma': 1.0,
        'use_fresca': False,
        'use_tcfg': False,
        'use_zero_init': False,
        'video_attention_split_steps': '',
        'zero_star_steps': 0,
    },
    'WanVideoFreeInitArgs': {
        'freeinit_d_s': 1.0,
        'freeinit_d_t': 1.0,
        'freeinit_method': 'ideal',
        'freeinit_n': 4,
        'freeinit_num_iters': 3,
    },
    'WanVideoImageResizeToClosest': {
        'aspect_ratio_preservation': 'keep_input',
        'generation_height': 480,
        'generation_width': 832,
    },
    'WanVideoLoopArgs': {'end_percent': 1.0, 'shift_skip': 6, 'start_percent': 0.0},
    'WanVideoLoraSelect': {'low_mem_load': False, 'merge_loras': True, 'strength': 1.0},
    'WanVideoMagCache': {
        'cache_device': 'offload_device',
        'end_step': -1,
        'magcache_K': 4,
        'magcache_thresh': 0.02,
        'start_step': 1,
    },
    'WanVideoSLG': {'blocks': '10', 'end_percent': 1.0, 'start_percent': 0.1},
    'WanVideoSetRadialAttention': {
        'block_size': 128,
        'decay_factor': 0.2,
        'dense_attention_mode': 'sageattn',
        'dense_blocks': 1,
        'dense_timesteps': 2,
        'dense_vace_blocks': 1,
    },
    'WanVideoTeaCache': {
        'cache_device': 'offload_device',
        'end_step': -1,
        'mode': 'e',
        'rel_l1_thresh': 0.3,
        'start_step': 1,
        'use_coefficients': True,
    },
    'WanVideoTextEncode': {
        'device': 'gpu',
        'force_offload': True,
        'negative_prompt': '',
        'positive_prompt': '',
        'use_disk_cache': False,
    },
    'WanVideoTorchCompileSettings': {
        'allow_unmerged_lora_compile': False,
        'backend': 'inductor',
        'compile_transformer_blocks_only': True,
        'dynamic': False,
        'dynamo_cache_size_limit': 64,
        'dynamo_recompile_limit': 128,
        'force_parameter_static_shapes': False,
        'fullgraph': False,
        'mode': 'default',
    },
    'WanVideoVRAMManagement': {'offload_percent': 1.0},
}


def _node(cls: str, inputs: dict) -> dict:
    """A graph node with every scalar input present — see _NODE_DEFAULTS."""
    return {'class_type': cls, 'inputs': dict(_NODE_DEFAULTS.get(cls, {}), **inputs)}


# The cache nodes disagree about the sensible range of their threshold by two
# orders of magnitude, so one dial serves all three and is clamped per cache
# rather than pretending 0.3 means the same thing to MagCache as to TeaCache.
_CACHE_NODES = {
    'teacache': ('WanVideoTeaCache', 'rel_l1_thresh', 0.30, 0.0, 1.0),
    'magcache': ('WanVideoMagCache', 'magcache_thresh', 0.02, 0.0, 0.3),
    'easycache': ('WanVideoEasyCache', 'easycache_thresh', 0.015, 0.0, 1.0),
}


def _augment_graph(p: dict, wf: dict, is22: bool, src_name: str, end_name: str, negative: str, log) -> dict:
    """Add every optional-args node the dials ask for, and return the extra
    input links to merge onto nodes 1/7/11/12/30/31.

    ``wf`` is mutated — it is always a deep copy by the time this is called.
    Kept separate from _graph_overrides for the same reason that function is
    separate from the submit: this is the half that changes the SHAPE of the
    graph, and Dry run has to be able to log both halves.

    New node ids live at 60+ so they can never collide with the template's
    1-50 or with the LoRA chain's 6/8/9.
    """
    extra = {'1': {}, '7': {}, '11': {}, '12': {}, '30': {}, '31': {}}
    samplers = ['30', '31'] if is22 else ['30']
    loaders = ['1', '7'] if is22 else ['1']

    def _add(nid, cls, inputs):
        wf[nid] = _node(cls, inputs)

    def _to_samplers(key, ref):
        for s in samplers:
            extra[s][key] = ref

    # ── source geometry ──────────────────────────────────────────────────
    start_ref = ['10', 0]
    if p['resize_mode'] != 'off':
        w, h = (int(x) for x in p['resolution'].split('x'))
        _add(
            '75',
            'WanVideoImageResizeToClosest',
            {
                'image': ['10', 0],
                'generation_width': w,
                'generation_height': h,
                'aspect_ratio_preservation': p['resize_mode'],
            },
        )
        start_ref = ['75', 0]
        extra['11']['start_image'] = start_ref
        if not is22:
            extra['12']['image_1'] = start_ref

    if end_name:
        _add('74', 'LoadImage', {'image': end_name})
        end_ref = ['74', 0]
        if p['resize_mode'] != 'off':
            w, h = (int(x) for x in p['resolution'].split('x'))
            _add(
                '76',
                'WanVideoImageResizeToClosest',
                {
                    'image': ['74', 0],
                    'generation_width': w,
                    'generation_height': h,
                    'aspect_ratio_preservation': p['resize_mode'],
                },
            )
            end_ref = ['76', 0]
        extra['11']['end_image'] = end_ref

    # ── loader-side memory args ──────────────────────────────────────────
    if int(p['block_swap']) > 0:
        _add(
            '60',
            'WanVideoBlockSwap',
            {
                'blocks_to_swap': int(p['block_swap']),
                'offload_img_emb': bool(p['swap_img_emb']),
                'offload_txt_emb': bool(p['swap_txt_emb']),
                'use_non_blocking': bool(p['nonblocking_swap']),
                'prefetch_blocks': int(p['prefetch_blocks']),
                'block_swap_debug': bool(p['debug_trace']),
            },
        )
        for l in loaders:
            extra[l]['block_swap_args'] = ['60', 0]

    if p['torch_compile'] != 'off':
        _add(
            '61',
            'WanVideoTorchCompileSettings',
            {
                'backend': p['compile_backend'],
                'fullgraph': False,
                'mode': p['torch_compile'],
                'dynamic': False,
                'dynamo_cache_size_limit': 64,
                'compile_transformer_blocks_only': bool(p['compile_blocks_only']),
            },
        )
        for l in loaders:
            extra[l]['compile_args'] = ['61', 0]

    if p['vram_offload'] != 'off':
        if int(p['block_swap']) > 0:
            log(
                'VRAM management and block swap are both on — they manage the '
                'same weights two different ways; block swap is the finer of '
                'the two'
            )
        _add('62', 'WanVideoVRAMManagement', {'offload_percent': float(p['vram_offload'])})
        for l in loaders:
            extra[l]['vram_management_args'] = ['62', 0]

    # Radial attention wraps the MODEL, so it goes between each loader and the
    # sampler it feeds rather than into an args socket.
    if p['radial_attn']:
        for nid, loader, sampler in (('63', '1', '30'), ('64', '7', '31')):
            if loader not in loaders:
                continue
            _add(
                nid,
                'WanVideoSetRadialAttention',
                {
                    'model': [loader, 0],
                    'dense_attention_mode': ('sageattn' if 'sage' in p['attention'] else p['attention']),
                    'dense_blocks': int(p['radial_dense_blocks']),
                    'dense_vace_blocks': 1,
                    'dense_timesteps': int(p['radial_dense_steps']),
                    'decay_factor': float(p['radial_decay']),
                    'block_size': int(p['radial_block_size']),
                },
            )
            extra[sampler]['model'] = [nid, 0]

    # ── sampler-side args ────────────────────────────────────────────────
    if p['cache_mode'] != 'off':
        cls, thresh_key, _d, lo, hi = _CACHE_NODES[p['cache_mode']]
        thresh = max(lo, min(hi, float(p['cache_thresh'])))
        if abs(thresh - float(p['cache_thresh'])) > 1e-9:
            log(f'cache threshold clamped to {thresh:g} for {p["cache_mode"]}')
        inp = {
            thresh_key: thresh,
            'start_step': int(p['cache_start']),
            'end_step': int(p['cache_end']),
            'cache_device': p['cache_device'],
        }
        if p['cache_mode'] == 'teacache':
            inp['use_coefficients'] = bool(p['teacache_coeff'])
            inp['mode'] = p['teacache_mode']
        elif p['cache_mode'] == 'magcache':
            inp['magcache_K'] = int(p['magcache_k'])
        _add('65', cls, inp)
        _to_samplers('cache_args', ['65', 0])

    if p['slg']:
        _add(
            '66',
            'WanVideoSLG',
            {
                'blocks': str(p['slg_blocks'] or '10'),
                'start_percent': float(p['slg_start']),
                'end_percent': float(p['slg_end']),
            },
        )
        _to_samplers('slg_args', ['66', 0])

    if p['feta']:
        _add(
            '67',
            'WanVideoEnhanceAVideo',
            {
                'weight': float(p['feta_weight']),
                'start_percent': float(p['feta_start']),
                'end_percent': float(p['feta_end']),
            },
        )
        _to_samplers('feta_args', ['67', 0])

    exp_on = (
        p['cfg_zero_star']
        or p['zero_init']
        or p['fresca']
        or p['tcfg']
        or p['tsr']
        or p['bidirectional']
        or float(p['raag_alpha']) > 0
        or str(p['attn_split_steps']).strip()
    )
    if exp_on:
        _add(
            '68',
            'WanVideoExperimentalArgs',
            {
                'video_attention_split_steps': str(p['attn_split_steps'] or ''),
                'cfg_zero_star': bool(p['cfg_zero_star']),
                'use_zero_init': bool(p['zero_init']),
                'zero_star_steps': int(p['zero_star_steps']),
                'use_fresca': bool(p['fresca']),
                'fresca_scale_low': float(p['fresca_low']),
                'fresca_scale_high': float(p['fresca_high']),
                'fresca_freq_cutoff': int(p['fresca_cutoff']),
                'use_tcfg': bool(p['tcfg']),
                'raag_alpha': float(p['raag_alpha']),
                'bidirectional_sampling': bool(p['bidirectional']),
                'temporal_score_rescaling': bool(p['tsr']),
                'tsr_k': float(p['tsr_k']),
                'tsr_sigma': float(p['tsr_sigma']),
            },
        )
        _to_samplers('experimental_args', ['68', 0])

    if p['context']:
        _add(
            '69',
            'WanVideoContextOptions',
            {
                'context_schedule': p['context_schedule'],
                'context_frames': int(p['context_frames']),
                'context_stride': int(p['context_stride']),
                'context_overlap': int(p['context_overlap']),
                'freenoise': bool(p['freenoise']),
                'verbose': bool(p['debug_trace']),
                'fuse_method': p['fuse_method'],
            },
        )
        _to_samplers('context_options', ['69', 0])

    if p['loop_seam']:
        _add(
            '70',
            'WanVideoLoopArgs',
            {
                'shift_skip': int(p['loop_shift_skip']),
                'start_percent': float(p['loop_start']),
                'end_percent': float(p['loop_end']),
            },
        )
        _to_samplers('loop_args', ['70', 0])

    if p['freeinit']:
        _add(
            '71',
            'WanVideoFreeInitArgs',
            {
                'freeinit_num_iters': int(p['freeinit_iters']),
                'freeinit_method': p['freeinit_method'],
                'freeinit_n': int(p['freeinit_n']),
                'freeinit_d_s': float(p['freeinit_ds']),
                'freeinit_d_t': float(p['freeinit_dt']),
            },
        )
        _to_samplers('freeinit_args', ['71', 0])

    # NAG needs its own encoded prompt, so it costs a second text-encode pass.
    if p['nag']:
        nag_text = str(p['nag_prompt']).strip() or negative or _wan._STATIC_SHOT_NEG
        _add('72', 'WanVideoTextEncode', {'positive_prompt': nag_text[:600], 'negative_prompt': '', 't5': ['2', 0]})
        _add(
            '73',
            'WanVideoApplyNAG',
            {
                'original_text_embeds': ['20', 0],
                'nag_text_embeds': ['72', 0],
                'nag_scale': float(p['nag_scale']),
                'nag_tau': float(p['nag_tau']),
                'nag_alpha': float(p['nag_alpha']),
            },
        )
        _to_samplers('text_embeds', ['73', 0])

    return {k: v for k, v in extra.items() if v and k in wf}


def _graph_overrides(
    p: dict,
    workflow: dict,
    src_name: str,
    prompt: str,
    negative: str,
    idx: int,
    seed: int,
    steps: float,
    guidance: float,
    shift: float,
    frames: int,
) -> dict:
    """Every ENGINE/SAMPLER/SOURCE/DECODE dial expressed as node overrides.

    Kept separate from the submit so Dry run can log exactly this dict — the
    only way to prove a dial reaches the node it claims to."""
    is22 = '31' in workflow
    w, h = (int(x) for x in p['resolution'].split('x'))
    loader = {
        'attention_mode': p['attention'],
        'base_precision': p['precision'],
        'load_device': p['load_device'],
        'rms_norm_function': p['rms_norm'],
    }
    if p['quantization']:
        loader['quantization'] = p['quantization']
    if not is22:
        wf_model = PATHWAYS.get(p['pathway'], (None, None))[1]
        if wf_model:
            loader['model'] = wf_model

    encode = {
        'width': w,
        'height': h,
        'num_frames': int(frames),
        'noise_aug_strength': float(p['noise_aug']),
        'start_latent_strength': float(p['start_latent_strength']),
        'end_latent_strength': float(p['end_latent_strength']),
        'force_offload': bool(p['force_offload']),
        'fun_or_fl2v_model': bool(p['fl2v_model']),
        'augment_empty_frames': float(p['augment_empty']),
        'tiled_vae': bool(p['encode_tiled_vae']),
    }
    sampler = {
        'seed': seed,
        'steps': int(steps),
        'cfg': float(guidance),
        'shift': float(shift),
        'scheduler': p['scheduler'],
        'riflex_freq_index': int(p['riflex']),
        'force_offload': bool(p['force_offload']),
        'denoise_strength': float(p['denoise_strength']),
        'batched_cfg': bool(p['batched_cfg']),
        'rope_function': p['rope_function'],
        'add_noise_to_samples': bool(p['add_noise_samples']),
    }
    decode = {
        'enable_vae_tiling': bool(p['vae_tiling']),
        'tile_x': int(p['tile_x']),
        'tile_y': int(p['tile_y']),
        'tile_stride_x': int(p['tile_stride_x']),
        'tile_stride_y': int(p['tile_stride_y']),
        'normalization': p['vae_norm'],
    }
    text = {'positive_prompt': prompt[:600], 'device': p['t5_device'], 'use_disk_cache': bool(p['t5_cache'])}
    if negative:
        text['negative_prompt'] = negative[:600]

    ov = {
        '1': dict(loader),
        '10': {'image': src_name},
        '11': dict(encode),
        '20': text,
        '40': decode,
        '45': {'fps': float(p['fps'])},
        '50': {'filename_prefix': f'ZygVst{"22" if is22 else "21"}_{idx:03d}'},
    }
    if p['t5_precision']:
        ov['2'] = {'precision': p['t5_precision']}
    if p['vae_precision']:
        ov['4'] = {'precision': p['vae_precision']}
    if not is22:
        # Wan2.1 is the only pathway with a CLIP-vision encoder, and the only
        # one where start/end step are the operator's to set — on 2.2 the
        # expert boundary owns them.
        ov['12'] = {
            'strength_1': float(p['clip_strength']),
            'crop': p['clip_crop'],
            'combine_embeds': p['clip_combine'],
            'force_offload': bool(p['force_offload']),
        }
        sampler['start_step'] = int(p['sampler_start_step'])
        sampler['end_step'] = int(p['sampler_end_step'])

    if is22:
        boundary = max(1, min(int(steps) - 1, int(round(int(steps) * float(p['expert_boundary'])))))
        ov['7'] = dict(loader)
        ov['30'] = dict(sampler, start_step=0, end_step=boundary)
        ov['31'] = dict(sampler, start_step=boundary, end_step=-1)
    else:
        ov['30'] = dict(sampler)
    return ov
