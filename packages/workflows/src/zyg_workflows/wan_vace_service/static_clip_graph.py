# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The graph stages of generate_vace_static_clip: staging, the VACE graph, the submit.

Extracted from static_clip.py (2026-10-09). Every node id, every input key and every log
line is the one the single function emitted; the helpers only make the graph buildable —
and therefore assertable — without a ComfyUI server: each takes the comfy client it stages
through as its first argument, so a test can pass a stub that returns the names it likes.
"""

import logging as _zyg_logging

from zyg_workflows.wan_vace_service.base import (
    _T2V_MODEL,
    _VACE_MODULE,
    _env_flag,
    _log_noop,
    os,
    shutil,
)
from zyg_workflows.wan_vace_service.graded_pin import PIN_WHOLE_MASK, build_graded_pin_mask

_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_vace_service')


def stage_graph_inputs(comfy, still_fit, controls, masks, ref_images_paths=None):
    """Upload the images the graph loads. -> (st_still, st_ctrl, st_mask, st_refs).

    st_ctrl / st_mask are None when that channel is a per-frame directory (node 13 / 15
    read the folder instead). CANON REFS (2026-07-29 identity fix): ref_images is VACE's
    STRONGEST identity channel (paper: refs enter as keep-unchanged latent frames under
    full attention). Feeding the scene anchor here made the drifted anchor the identity
    authority. When canon portrait cutouts are supplied they take that seat instead; the
    control frames keep the layout. Missing ref paths are dropped silently, as ever.
    """
    st_still = comfy.stage_input_image(still_fit)
    st_ctrl = None if controls.ctrl_dir else comfy.stage_input_image(controls.control_src)
    st_mask = None if masks.mask_dir else comfy.stage_input_image(masks.mask_path)
    st_refs = [comfy.stage_input_image(p) for p in (ref_images_paths or []) if p and os.path.isfile(p)]
    return st_still, st_ctrl, st_mask, st_refs


def wire_source_nodes(g, st_ctrl, st_mask, ctrl_dir, mask_dir, size, num_frames, log_fn=None):
    """(4) CONTROL + MASK SOURCE NODES. Mutates G in place.

    Single-image path (11/13, 14/15) is untouched; the sequence path swaps each
    RepeatImageBatch for LoadImagesFromFolderKJ. image_load_cap and start_index are
    MANDATORY there (declared optional but positional-without-default in load_images(),
    ComfyUI-KJNodes/nodes/image_nodes.py:3416) and the folder is read in sorted() order,
    hence the zero-padded names build_mask_sequence writes.
    """
    log = log_fn or _log_noop
    W, H = size
    _seq_kw = {
        'width': W,
        'height': H,
        'keep_aspect_ratio': 'stretch',
        'image_load_cap': int(num_frames),
        'start_index': 0,
    }
    if ctrl_dir:
        g['13'] = {'class_type': 'LoadImagesFromFolderKJ', 'inputs': dict(folder=os.path.abspath(ctrl_dir), **_seq_kw)}
    else:
        g['11'] = {'class_type': 'LoadImage', 'inputs': {'image': st_ctrl}}
        g['13'] = {'class_type': 'RepeatImageBatch', 'inputs': {'image': ['11', 0], 'amount': int(num_frames)}}
    if mask_dir:
        g['15'] = {'class_type': 'LoadImagesFromFolderKJ', 'inputs': dict(folder=os.path.abspath(mask_dir), **_seq_kw)}
        log(
            f'[vace] PER-FRAME MASK SEQUENCE: {num_frames} masks from '
            f'{os.path.basename(mask_dir)}' + (f' + {num_frames} matched control frames' if ctrl_dir else '')
        )
    else:
        g['14'] = {'class_type': 'LoadImage', 'inputs': {'image': st_mask}}
        g['15'] = {'class_type': 'RepeatImageBatch', 'inputs': {'image': ['14', 0], 'amount': int(num_frames)}}


def wire_canon_refs(g, st_refs, log_fn=None):
    """Wire up to three canon refs (single image or ImageBatch chain) into node 60's ref seat."""
    log = log_fn or _log_noop
    if not st_refs:
        return
    prev_ref = None
    for ri, rname in enumerate(st_refs[:3]):
        nid = f'7{ri + 1}'
        g[nid] = {'class_type': 'LoadImage', 'inputs': {'image': rname}}
        if prev_ref is None:
            prev_ref = [nid, 0]
        else:
            bid = f'7{ri + 5}'
            g[bid] = {'class_type': 'ImageBatch', 'inputs': {'image1': prev_ref, 'image2': [nid, 0]}}
            prev_ref = [bid, 0]
    g['60']['inputs']['ref_images'] = prev_ref
    log(f'[vace] canon refs wired ({len(st_refs)})')


def wire_set_embed(
    g,
    comfy,
    set_plate_path,
    size,
    num_frames,
    set_strength=1.0,
    set_end_percent=0.88,
    subject_strength=None,
    subject_end_percent=None,
    log_fn=None,
):
    """A5 — the SET embed (node 59) chained into the subject embed. -> False to abort.

    Must be called AFTER the ref block so it can copy the FINAL ref wiring. A missing plate
    file leaves the graph single-embed and is not an error. False is returned only for the
    mismatched-refs trap below, which would crash the run hours in.
    """
    log = log_fn or _log_noop
    W, H = size
    if not os.path.isfile(set_plate_path):
        log(f'[vace] set plate missing ({set_plate_path}) — staying single-embed')
        return True
    st_plate = comfy.stage_input_image(set_plate_path)
    s_str = 0.5 if subject_strength is None else float(subject_strength)
    s_end = 0.35 if subject_end_percent is None else float(subject_end_percent)
    g['61'] = {'class_type': 'LoadImage', 'inputs': {'image': st_plate}}
    g['62'] = {'class_type': 'RepeatImageBatch', 'inputs': {'image': ['61', 0], 'amount': int(num_frames)}}
    g['59'] = {
        'class_type': 'WanVideoVACEEncode',
        'inputs': {
            'vae': ['4', 0],
            'width': W,
            'height': H,
            'num_frames': int(num_frames),
            'strength': float(set_strength),
            'vace_start_percent': 0.0,
            'vace_end_percent': float(set_end_percent),
            'input_frames': ['62', 0],
            'input_masks': ['16', 0],
        },
    }
    # HARD TRAP (verified in wrapper source): has_ref is OR'd ACROSS embeds
    # (nodes_sampler.py:323-324) and the noise tensor gains +1 latent frame if ANY
    # embed has refs (:338). If the two embeds carry different ref_images their
    # contexts differ by one latent frame and the window slicer context[0][:,c]
    # (:1922) indexes out of range — the run CRASHES hours in. The two embeds MUST
    # receive the IDENTICAL ref_images input.
    if 'ref_images' in g['60']['inputs']:
        g['59']['inputs']['ref_images'] = list(g['60']['inputs']['ref_images'])
    if g['59']['inputs'].get('ref_images') != g['60']['inputs'].get('ref_images'):
        log(
            '[vace] ABORT: set/subject embeds have mismatched ref_images — this '
            'would crash the window slicer (nodes_sampler.py:1922)'
        )
        return False
    g['60']['inputs']['prev_vace_embeds'] = ['59', 0]
    g['60']['inputs']['strength'] = s_str
    g['60']['inputs']['vace_end_percent'] = s_end
    log(
        f'[vace] TWO EMBEDS: set(59) {float(set_strength):.2f}/end '
        f'{float(set_end_percent):.2f} -> subject(60) {s_str:.2f}/end {s_end:.2f}, '
        f'refs identical ({g["60"]["inputs"].get("ref_images")})'
    )
    return True


def wire_context_options(g, context_frames, context_overlap, context_stride, fuse_method, log_fn=None):
    """Add the context-options node (65) for single-stream long video. Mutates G in place.

    Overlapping windows over ONE noise field (FreeNoise) — no segment boundaries, no
    re-derivation (2026-07-30 continuity research). A7: fuse_method is passed EXPLICITLY —
    the wrapper default is silently 'linear' (nodes.py:1906) and v8 omitted it.
    overlap/stride deliberately unchanged.
    """
    log = log_fn or _log_noop
    g['65'] = {
        'class_type': 'WanVideoContextOptions',
        'inputs': {
            'context_schedule': 'uniform_standard',
            'context_frames': int(context_frames),
            'context_stride': int(context_stride),
            'context_overlap': int(context_overlap),
            'freenoise': True,
            'verbose': False,
            'fuse_method': str(fuse_method or 'pyramid'),
        },
    }
    log(
        f'[vace] context windows: {context_frames}f overlap {context_overlap} '
        f'stride {context_stride} fuse={fuse_method or "pyramid"}'
    )


def apply_graded_pin(g, comfy, out_dir, size, pin_mask_src, pin_regions_res, log_fn=None):
    """(3) GRADED PIN / DIFFERENTIAL DIFFUSION — ZYG_VACE_DIFFDIFF (default OFF).

    Mutates G in place; never aborts the run. LoadImage(graded grey) -> ImageToMask ->
    WanVideoEncode(image=still, mask=...) -> sampler.samples, which is the ONLY route by
    which noise_mask reaches the sampler (nodes.py:2292 returns {"samples": ...,
    "noise_mask": mask}; nodes_sampler.py:735 reads it back off that LATENT).
    add_noise_to_samples MUST be True: with it False the sampler sets noise =
    input_samples verbatim (nodes_sampler.py:729-733) and the run starts from the CLEAN
    still latent, i.e. it renders the still back. With it True and denoise_strength 1.0,
    timesteps[0] is 1000 so the blend is pure noise — the pin comes only from the per-step
    diffdiff assignment, exactly as intended.

    2026-08-01: the pin is PER-REGION and its default list is EMPTY. With no regions this
    whole block is skipped before anything is staged or written, so the submitted graph is
    byte-identical to ZYG_VACE_DIFFDIFF=0 — the flag alone can no longer change a render.
    """
    log = log_fn or _log_noop
    W, H = size
    if not _env_flag('ZYG_VACE_DIFFDIFF'):
        return
    if not pin_regions_res:
        log(
            '[diffdiff] ZYG_VACE_DIFFDIFF=1 but the pin region list is EMPTY — pin stays '
            'OFF and the graph is byte-identical to ZYG_VACE_DIFFDIFF=0. Pass '
            'pin_regions=[{"box": (x0,y0,x1,y1), "level": 0.65}] (see '
            'pin_regions_from_meta), or ZYG_VACE_DIFFDIFF_WHOLE_MASK=1 for the v12 pin'
        )
        return
    if (W % 16) or (H % 16):
        log(
            f'[diffdiff] SKIPPED: {W}x{H} is not divisible by 16 — WanVideoEncode would '
            'silently resize (nodes.py:2265) and the latent grid would not match noise'
        )
        return
    pin_png = build_graded_pin_mask(
        pin_mask_src,
        os.path.join(out_dir, '_vace_diffdiff_mask.png'),
        size=(W, H),
        pin_regions=pin_regions_res,
        log_fn=log,
    )
    if not pin_png:
        log('[diffdiff] no graded mask — staying binary')
        return
    st_pin = comfy.stage_input_image(pin_png)
    g['17'] = {'class_type': 'LoadImage', 'inputs': {'image': st_pin}}
    g['18'] = {'class_type': 'ImageToMask', 'inputs': {'image': ['17', 0], 'channel': 'red'}}
    g['19'] = {
        'class_type': 'WanVideoEncode',
        'inputs': {
            'vae': ['4', 0],
            'image': ['10', 0],
            'enable_vae_tiling': False,
            'tile_x': 272,
            'tile_y': 272,
            'tile_stride_x': 144,
            'tile_stride_y': 128,
            'mask': ['18', 0],
        },
    }
    g['30']['inputs']['samples'] = ['19', 0]
    g['30']['inputs']['add_noise_to_samples'] = True
    g['30']['inputs']['denoise_strength'] = 1.0
    _pin_what = 'WHOLE MASK (v12 bisect)' if pin_regions_res == PIN_WHOLE_MASK else f'{len(pin_regions_res)} region(s)'
    log(
        f'[vace] GRADED PIN ON ({_pin_what}): WanVideoEncode(19) -> '
        'sampler.samples (applied to the fused full-length latent outside the '
        'window loop, nodes_sampler.py:2564 — seam-identical by construction)'
    )


def model_and_lora_nodes(loras=None):
    """The model loader (1) and the chained LoRA selects (80, 81, ...). -> a fresh graph dict.

    Each LoRA is wired into the previous one through prev_lora and the last one into the
    loader's 'lora' input, which is how a character/style chain reaches the model. Put each
    LoRA's trigger token in the prompt — the chain itself carries no semantics.
    """
    g = {
        '1': {
            'class_type': 'WanVideoModelLoader',
            'inputs': {
                'model': _T2V_MODEL,
                'base_precision': 'bf16',
                'quantization': 'fp8_e4m3fn',
                'load_device': 'offload_device',
                'attention_mode': os.environ.get('ZYG_WAN_ATTENTION', 'sdpa').strip() or 'sdpa',
                'extra_model': ['7', 0],
            },
        },
    }
    # chained character/style LoRAs → model loader 'lora' input
    prev = None
    for i, (lname, lstr) in enumerate(loras or []):
        nid = f'8{i}'
        node = {
            'class_type': 'WanVideoLoraSelect',
            'inputs': {'lora': lname, 'strength': float(lstr), 'low_mem_load': False},
        }
        if prev:
            node['inputs']['prev_lora'] = [prev, 0]
        g[nid] = node
        prev = nid
    if prev:
        g['1']['inputs']['lora'] = [prev, 0]
    return g


def encoder_nodes(
    st_still,
    pos,
    neg,
    size,
    num_frames,
    vace_strength=0.7,
    vace_start_percent=0.0,
    vace_end_percent=0.7,
):
    """The T5/VAE/VACE loaders, the still, the text encode (20) and the subject embed (60).

    -> a dict to update into the graph. Node 60 takes its control from 13 and its mask from
    16, both of which wire_source_nodes() supplies, and holds the still as its single ref
    until wire_canon_refs() replaces that seat.
    """
    W, H = size
    return {
        '2': {
            'class_type': 'LoadWanVideoT5TextEncoder',
            'inputs': {'model_name': 'umt5-xxl-enc-bf16.safetensors', 'precision': 'bf16'},
        },
        '4': {
            'class_type': 'WanVideoVAELoader',
            'inputs': {'model_name': 'Wan2_1_VAE_bf16.safetensors', 'precision': 'bf16'},
        },
        '7': {'class_type': 'WanVideoVACEModelSelect', 'inputs': {'vace_model': _VACE_MODULE}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': st_still}},
        '16': {'class_type': 'ImageToMask', 'inputs': {'image': ['15', 0], 'channel': 'red'}},
        '20': {
            'class_type': 'WanVideoTextEncode',
            'inputs': {'t5': ['2', 0], 'positive_prompt': pos, 'negative_prompt': neg, 'force_offload': True},
        },
        '60': {
            'class_type': 'WanVideoVACEEncode',
            'inputs': {
                'vae': ['4', 0],
                'width': W,
                'height': H,
                'num_frames': int(num_frames),
                'strength': float(vace_strength),
                'vace_start_percent': float(vace_start_percent),
                'vace_end_percent': float(vace_end_percent),
                'input_frames': ['13', 0],
                'ref_images': ['10', 0],
                'input_masks': ['16', 0],
            },
        },
    }


def sampler_and_output_nodes(steps=30, cfg=5.0, shift=2.0, seed=7):
    """The sampler (30), the decode (40) and the mp4 tail (45, 50). -> a dict to update in.

    'unipc' and fps 17.0 are not configurable here, by design: the scheduler is the one the
    VACE graph was tuned on and the 17fps clip is what the interpolation step expects.
    """
    return {
        '30': {
            'class_type': 'WanVideoSampler',
            'inputs': {
                'model': ['1', 0],
                'image_embeds': ['60', 0],
                'text_embeds': ['20', 0],
                'steps': int(steps),
                'cfg': float(cfg),
                'shift': float(shift),
                'seed': int(seed),
                'scheduler': 'unipc',
                'riflex_freq_index': 0,
                'force_offload': True,
            },
        },
        '40': {
            'class_type': 'WanVideoDecode',
            'inputs': {
                'vae': ['4', 0],
                'samples': ['30', 0],
                'enable_vae_tiling': False,
                'tile_x': 272,
                'tile_y': 272,
                'tile_stride_x': 144,
                'tile_stride_y': 128,
            },
        },
        '45': {'class_type': 'CreateVideo', 'inputs': {'images': ['40', 0], 'fps': 17.0}},
        '50': {
            'class_type': 'SaveVideo',
            'inputs': {'video': ['45', 0], 'filename_prefix': 'ZygVace', 'format': 'mp4', 'codec': 'h264'},
        },
    }


def build_vace_graph(
    comfy,
    still_fit,
    masks,
    controls,
    size,
    pos,
    neg,
    num_frames=65,
    steps=30,
    cfg=5.0,
    shift=2.0,
    seed=7,
    vace_strength=0.7,
    vace_start_percent=0.0,
    vace_end_percent=0.7,
    loras=None,
    ref_images_paths=None,
    set_plate_path=None,
    set_strength=1.0,
    set_end_percent=0.88,
    subject_strength=None,
    subject_end_percent=None,
    context_windows=False,
    context_frames=81,
    context_overlap=24,
    context_stride=4,
    fuse_method='pyramid',
    pin_regions_res=None,
    out_dir=None,
    log_fn=None,
):
    """Stage the inputs and build the whole VACE prompt graph. -> the graph, or None to abort.

    Node order is the order the single function emitted: loader + LoRA chain, the core
    nodes (text encode 20, VACE encode 60), the control/mask sources, the canon refs, the
    A5 set embed (which may abort), the context options, the sampler/decode/save tail, and
    finally the graded pin. None means a refusal that was already logged.
    """
    log = log_fn or _log_noop
    W, H = size
    st_still, st_ctrl, st_mask, st_refs = stage_graph_inputs(comfy, still_fit, controls, masks, ref_images_paths)
    g = model_and_lora_nodes(loras)
    g.update(
        encoder_nodes(
            st_still,
            pos,
            neg,
            (W, H),
            int(num_frames),
            vace_strength=vace_strength,
            vace_start_percent=vace_start_percent,
            vace_end_percent=vace_end_percent,
        )
    )
    wire_source_nodes(g, st_ctrl, st_mask, controls.ctrl_dir, masks.mask_dir, (W, H), int(num_frames), log_fn=log)
    wire_canon_refs(g, st_refs, log_fn=log)
    if set_plate_path and not wire_set_embed(
        g,
        comfy,
        set_plate_path,
        (W, H),
        int(num_frames),
        set_strength=set_strength,
        set_end_percent=set_end_percent,
        subject_strength=subject_strength,
        subject_end_percent=subject_end_percent,
        log_fn=log,
    ):
        return None
    if context_windows:
        wire_context_options(g, context_frames, context_overlap, context_stride, fuse_method, log_fn=log)
    g.update(sampler_and_output_nodes(steps=steps, cfg=cfg, shift=shift, seed=seed))
    if context_windows:
        g['30']['inputs']['context_options'] = ['65', 0]
    apply_graded_pin(g, comfy, out_dir, (W, H), masks.pin_mask_src, pin_regions_res, log_fn=log)
    return g


def record_graph_debug(
    g,
    pos,
    neg,
    masks,
    pin_regions_res,
    loras=None,
    seed=7,
    steps=30,
    cfg=5.0,
    shift=2.0,
    vace_strength=0.7,
    beat_map=None,
):
    """Hand the prompts, the graph and the mask to the active pipeline_debug recorder.

    Best-effort by design: a run must not fail because the debug recorder is absent or
    unhappy, so every failure is a debug log line. In sequence mode mask_path is a
    directory, so the union PNG is snapshotted instead.
    """
    try:
        from zyg_workflows import pipeline_debug as _dbg

        _d = _dbg.get_active()
        _d.record_prompts(
            'vace',
            positive=pos,
            negative=neg,
            model=_T2V_MODEL,
            module=_VACE_MODULE,
            loras=str(loras or []),
            seed=seed,
            steps=steps,
            cfg=cfg,
            shift=shift,
            vace_strength=vace_strength,
            beat_map=str(beat_map or ''),
            mask_sequence=str(masks.mask_dir or ''),
            pin_regions=str(pin_regions_res or []),
        )
        _d.record_graph('vace', g)
        # in sequence mode mask_path is a directory — snapshot the union PNG instead
        _d.snapshot('vace_mask', masks.pin_mask_src if os.path.isfile(str(masks.pin_mask_src)) else masks.mask_path)
    except Exception as _exc:
        _zyg_log.debug('debug recorder skipped the vace graph and mask snapshot: %s', _exc)


def submit_static_graph(comfy, g, out_dir, interpolate=True, log_fn=None):
    """Attest the models, submit the graph, bring back the clip. -> clip path or None.

    2026-07-30 model attestation (see lora_attest.py) — hash-verify the character/prop LoRA
    chain, the T2V checkpoint, the VACE module and the VAE before any frame is rendered.
    Warn-only; ZYG_LORA_ATTEST=strict raises before submit. The output is copied to
    `<out_dir>/vace_static.mp4` (the fixed name every caller reads) and, with interpolate,
    replaced in place by its 24fps version when that succeeds.
    """
    log = log_fn or _log_noop
    try:
        from zyg_workflows import lora_attest as _attest
    except Exception:
        _attest = None
    if _attest is not None:
        try:
            _attest.attest_submit(g, tag='vace', log_fn=log)
        except _attest.AttestationError as e:
            log(f'[vace] BLOCKED before submit by model attestation (strict): {e}')
            return None
    try:
        outs = comfy.submit(g, timeout_s=int(os.environ.get('ZYG_WAN_TIMEOUT_S', '2400')))
    except Exception as e:
        log(f'[vace] submit failed: {e}')
        return None
    if not (outs and os.path.isfile(outs[0])):
        log('[vace] no output')
        return None
    clip = os.path.join(out_dir, 'vace_static.mp4')
    shutil.copy2(outs[0], clip)
    if interpolate:
        try:
            from zyg_workflows import wan_video_service as WVS

            ip = clip.replace('.mp4', '_24fps.mp4')
            if WVS._interpolate_clip(clip, ip, log):
                os.replace(ip, clip)
        except Exception as e:
            log(f'[vace] interpolation skipped ({e})')
    log(f'[vace] → {clip}')
    return clip
