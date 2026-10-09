# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The still-generation half of `stage_02_image_prep`: ComfyUI first, then local FLUX.

`stage_02_images.stage_02_image_prep` was 534 lines. Everything that is not the
stage's own control flow lives here: the uploaded-image copy, the ComfyUI batch,
the FLUX load (T5 on the CPU, style LoRA), the ControlNet/IPAdapter/Real-ESRGAN
services, the per-scene render and the teardown. The orchestrator keeps what
touches the `VideoContext` and the process-wide GPU lock (`ctx._flux_gpu_acq_v`,
`_GPU_PIPELINE_LOCK`, `_deep_unload_flux_pipeline_cache`) and the `ZYG_FORCE_FLUX_LOCAL`
read whose settings entry names that file.

One `FluxStillRun` stands in for the twenty-odd locals the old function shared
between its phases; `ScenePlan` is the per-scene FLUX call. The import direction
is one-way — `stage_02_images` imports this module at module level and nothing
here imports it back — and `torch`/`gc`/`FluxPipeline` and the ControlNet and
IPAdapter services stay lazy (passed in, or imported inside the phase that needs
them), so an ImportError still lands in the orchestrator's `_flux_err` handler
and the run falls back to blank frames exactly as before.
"""

import os
import random as _random
from dataclasses import dataclass

from zyg_workflows import gui_state
from zyg_workflows import paths
from zyg_workflows.pipeline_config import _dsl, _FLUX_LORA_PATH, _FLUX_LORA_SCALE, _STYLE_LORA_DIR

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


@dataclass
class FluxStillRun:
    """The still-generation run: the job's inputs plus the state its phases share.

    The first ten fields are the stage's read-only inputs (`log` is the driver's
    four-argument `_log` closure, called as ``log(level, 'Stage 2', message)``);
    the rest is what the old function kept in locals across its phases —
    `torch`/`gc` and the two service modules so this module imports neither at
    module level, and the ControlNet pipe, the IPAdapter reference and the lazily
    loaded Real-ESRGAN upsampler, all of which outlive one scene.
    """

    log: object
    images_dir: str
    out_dir: str
    scenes: list
    directive: str
    visual_style: str
    vscfg: dict
    job: dict
    n_scenes: int
    scene_images: list
    torch: object = None
    gc: object = None
    cn_svc: object = None
    ipa_svc: object = None
    cn_pipe: object = None
    ipa_ready: bool = False
    subject_ref_path: str | None = None
    esrgan_up: object = None
    esrgan_model_path: str = ''
    esrgan_available: bool = False


@dataclass
class ScenePlan:
    """One scene's FLUX call: the prompt text, the canvas and the sampler knobs."""

    prompt: str
    width: int
    height: int
    seed: int
    steps: int
    cfg: float


def copy_uploaded_stills(image_paths, n_scenes, images_dir):
    """Copy the first *n_scenes* uploads into *images_dir* as ``scene_NNNN.<ext>``.

    Returns the ordered list of destination paths. An upload whose path no longer
    exists is skipped, so the list can be shorter than *image_paths* — that gap is
    what the FLUX phase then fills.
    """
    scene_images = []  # final ordered list of image paths, one per scene
    for i, up in enumerate(image_paths[:n_scenes]):
        if os.path.exists(up):
            ext = os.path.splitext(up)[1].lower() or '.jpg'
            dest = os.path.join(images_dir, f'scene_{i:04d}{ext}')
            import shutil as _shutil

            _shutil.copy2(up, dest)
            scene_images.append(dest)
    return scene_images


def _dsl_scene_yaml(out_dir, scene_idx):
    """Return the DSL scene yaml path for *scene_idx*, or None when the DSL is off.

    A dsl_runtime that cannot be imported or cannot name the file is logged and
    treated as "no yaml": the still is generated without it.
    """
    if _dsl is None or not _dsl.is_enabled('video'):
        return None
    try:
        from zyg_workflows.dsl_runtime import scene_yaml_path

        return scene_yaml_path(os.path.join(out_dir, 'dsl'), scene_idx)
    except Exception as _exc:
        _zyg_log.warning('DSL scene yaml unavailable, the still is generated without it: %s', _exc)
    return None


def comfy_still_batch(run, n_missing):
    """Generate the *n_missing* missing stills on the ComfyUI server, if it is up.

    Appends every accepted still to ``run.scene_images`` and stops at the first
    scene whose QA never passes. Returns nothing and raises whatever the Comfy
    services raise: the orchestrator logs that and falls back to diffusers. A
    ComfyUI that is not available is a silent no-op.
    """
    _log = run.log
    from zyg_workflows import comfy_generation_service as _cgs_st2
    from zyg_workflows import video_flux_still_service as _vfs_st2

    if not _cgs_st2.is_available():
        return
    _log('INFO', 'Stage 2', 'ComfyUI primary — routing hero stills to Comfy (FLUX Dev + QA retries)')
    _vid_char_id_c = run.job.get('char_id', '') or ''
    _pkg_vid_c = None
    if _vid_char_id_c:
        from zyg_workflows import character_bible_service as _cbs_st2

        _pkg_vid_c = _cbs_st2.load(_vid_char_id_c)
    _start_idx_c = len(run.scene_images)
    for _fi_c in range(n_missing):
        _scene_idx_c = _start_idx_c + _fi_c
        _sc_c = run.scenes[_scene_idx_c] if _scene_idx_c < len(run.scenes) else {}
        _dest_c = os.path.join(run.images_dir, f'scene_{_scene_idx_c:04d}.png')
        _dsl_yaml_c = _dsl_scene_yaml(run.out_dir, _scene_idx_c)
        _ok_c, _bk_c = _vfs_st2.generate_still_with_retries(
            _dest_c,
            _sc_c,
            run.directive,
            run.visual_style,
            run.vscfg,
            dsl_yaml_path=_dsl_yaml_c,
            char_id=_vid_char_id_c,
            char_pkg=_pkg_vid_c,
            model_family=run.job.get('model_family', 'flux'),
            log_fn=lambda m: _log('INFO', 'Stage 2', m),
        )
        if _ok_c:
            run.scene_images.append(_dest_c)
            _log('INFO', 'Stage 2', f'Scene {_scene_idx_c}: ComfyGen ({_bk_c})')
        else:
            _log(
                'WARNING',
                'Stage 2',
                f'Scene {_scene_idx_c}: still QA failed after all attempts ({_bk_c})',
            )
            break
    if len(run.scene_images) >= run.n_scenes:
        _log('INFO', 'Stage 2', f'ComfyUI generated {run.n_scenes} still(s) — in-process FLUX not loaded')


def wait_for_flux_vram(log):
    """Wait for ~26 GB of free VRAM before FLUX loads, evicting Comfy models if needed.

    Advisory only: the wait failing is logged as non-fatal and the load proceeds,
    which is what the monolith did.
    """
    try:
        from zyg_workflows import _comfy_client as _cc_pre_flux

        _ok_vg_flux, _free_gb_flux = _cc_pre_flux.wait_for_free_vram_gb(
            min_free_gb=26.0,
            timeout_s=180.0,
            try_evict=True,
            log_fn=lambda m: log('INFO', 'Stage 2', m),
        )
        log('INFO', 'Stage 2', f'Pre-FLUX VRAM wait: ok={_ok_vg_flux} free={_free_gb_flux:.1f} GB')
    except Exception as _vram_wait_e:
        log('WARNING', 'Stage 2', f'Pre-FLUX VRAM wait failed (non-fatal): {_vram_wait_e}')


def _t5_cpu_prompt_embeds(self, prompt=None, num_images_per_prompt=1, max_sequence_length=512, device=None, dtype=None):
    """FLUX's ``_get_t5_prompt_embeds`` with T5-XXL left wherever its parameters are.

    Bound onto the pipeline as a method so the text encoder can stay in CPU RAM
    (~9 GB of VRAM saved): the token ids go to the encoder's own device and only
    the embeddings come back to the pipeline's execution device.
    """
    device = device or self._execution_device
    prompt = [prompt] if isinstance(prompt, str) else prompt
    batch_size = len(prompt)
    text_inputs = self.tokenizer_2(
        prompt,
        padding='max_length',
        max_length=max_sequence_length,
        truncation=True,
        return_length=False,
        return_overflowing_tokens=False,
        return_tensors='pt',
    )
    _t5_dev = next(self.text_encoder_2.parameters()).device
    _emb = self.text_encoder_2(text_inputs.input_ids.to(_t5_dev), output_hidden_states=False)[0].to(
        dtype=self.text_encoder_2.dtype, device=device
    )
    _, seq_len, _ = _emb.shape
    _emb = _emb.repeat(1, num_images_per_prompt, 1)
    return _emb.view(batch_size * num_images_per_prompt, seq_len, -1)


def _normalise_lora_keys(raw):
    """Rename SimpleTuner's ``.lora.down/.lora.up`` keys to diffusers' ``.lora_A/.lora_B``."""
    return {k.replace('.lora.down.', '.lora_A.').replace('.lora.up.', '.lora_B.'): v for k, v in raw.items()}


def _load_style_lora(run):
    """Load this visual style's LoRA onto the cached FLUX pipeline.

    Tries, in the monolith's order: ``vscfg['lora']`` (a file in the style LoRA
    directory), ``vscfg['lora_dir']`` (a SimpleTuner export, whose keys are
    normalised first), then the global documentary LoRA. Returns True when one of
    them loaded; every failure is logged and the run continues without a LoRA.
    """
    _log = run.log
    _vscfg = run.vscfg
    # ── Load style LoRA if configured for this visual_style ──
    _style_lora_file = _vscfg.get('lora')
    _style_lora_scale = _vscfg.get('scale', 1.0)
    _style_lora_loaded = False
    if _style_lora_file:
        _style_lora_path = os.path.join(_STYLE_LORA_DIR, _style_lora_file)
        if os.path.exists(_style_lora_path):
            try:
                gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_style_lora_path)
                gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                    ['default_0'],
                    adapter_weights=[_style_lora_scale],
                )
                _style_lora_loaded = True
                _log(
                    'INFO',
                    'Stage 2',
                    f'Style LoRA loaded: {_style_lora_file} @ scale {_style_lora_scale}',
                )
            except Exception as _slora_e:
                _log('WARNING', 'Stage 2', f'Style LoRA load failed (continuing without): {_slora_e}')
        else:
            _log('WARNING', 'Stage 2', f'Style LoRA file not found: {_style_lora_path}')
    elif _vscfg.get('lora_dir'):
        # Style-specific LoRA from a directory (e.g. documentary-cinematic).
        # SimpleTuner keys use .lora.down/.lora.up — normalize to diffusers convention.
        try:
            import safetensors.torch as _st_lora

            _lora_sf = os.path.join(_vscfg['lora_dir'], 'pytorch_lora_weights.safetensors')
            if os.path.exists(_lora_sf):
                _norm_lora = _normalise_lora_keys(_st_lora.load_file(_lora_sf))
                gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_norm_lora)
                gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                    ['default_0'],
                    adapter_weights=[_vscfg.get('lora_dir_scale', 0.75)],
                )
                _style_lora_loaded = True
                _log(
                    'INFO',
                    'Stage 2',
                    f'Style LoRA loaded from dir: {_vscfg["lora_dir"]} @ scale {_vscfg.get("lora_dir_scale", 0.75)}',
                )
            else:
                _log('WARNING', 'Stage 2', f'lora_dir LoRA file not found: {_lora_sf}')
        except Exception as _lora_dir_e:
            _log(
                'WARNING',
                'Stage 2',
                f'lora_dir LoRA load failed (continuing without): {_lora_dir_e}',
            )
    elif _FLUX_LORA_PATH:
        # fallback to global documentary LoRA if no style LoRA
        try:
            import safetensors.torch as _st_lora

            _lora_sf = os.path.join(_FLUX_LORA_PATH, 'pytorch_lora_weights.safetensors')
            _norm_lora = _normalise_lora_keys(_st_lora.load_file(_lora_sf))
            gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_norm_lora)
            gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                ['default_0'],
                adapter_weights=[_FLUX_LORA_SCALE],
            )
            _style_lora_loaded = True
            _log('INFO', 'Stage 2', f'LoRA loaded: {_FLUX_LORA_PATH} @ scale {_FLUX_LORA_SCALE}')
        except Exception as _lora_e:
            _log('WARNING', 'Stage 2', f'LoRA load failed (continuing without): {_lora_e}')
    # ────────────────────────────────────────────────────
    return _style_lora_loaded


def load_flux_pipeline(run, flux_model_path, flux_pipeline_cls):
    """Put FLUX.1-schnell in ``gui_state._FLUX_PIPELINE_CACHE``, T5 on the CPU, LoRA on top.

    *flux_pipeline_cls* is `diffusers.FluxPipeline`, passed in so this module never
    imports diffusers at module level; `run.torch` and `run.gc` are the same deal.
    An already warm cache is reused as it is — no LoRA is claimed for it, because
    its adapter state may be stale.
    """
    _log = run.log
    _torch_v = run.torch
    _gc_v = run.gc
    if gui_state._FLUX_PIPELINE_CACHE is None:
        _torch_v.cuda.empty_cache()
        _gc_v.collect()
        _log('INFO', 'Stage 2', 'Loading FLUX.1-schnell…')
        gui_state._FLUX_PIPELINE_CACHE = flux_pipeline_cls.from_pretrained(
            flux_model_path,
            torch_dtype=_torch_v.bfloat16,
            local_files_only=True,
        )
        gui_state._FLUX_PIPELINE_CACHE.transformer.to('cuda')
        gui_state._FLUX_PIPELINE_CACHE.text_encoder.to('cuda')
        gui_state._FLUX_PIPELINE_CACHE.vae.to('cuda')
        import types as _types_flux_v

        gui_state._FLUX_PIPELINE_CACHE._get_t5_prompt_embeds = _types_flux_v.MethodType(
            _t5_cpu_prompt_embeds, gui_state._FLUX_PIPELINE_CACHE
        )
        _log('INFO', 'Stage 2', 'FLUX loaded — T5-XXL on CPU (~9 GB RAM), ~24 GB VRAM used')
        _load_style_lora(run)
    else:
        _log('INFO', 'Stage 2', 'Using cached FLUX model')  # cache may have stale LoRA state


def setup_quality_services(run):
    """Load ControlNet, settle the IPAdapter state and locate Real-ESRGAN.

    Fills `run.cn_svc`, `run.ipa_svc`, `run.cn_pipe`, `run.ipa_ready`,
    `run.subject_ref_path` and the two ESRGAN fields. Real-ESRGAN itself is NOT
    loaded here — it would eat ~200 MB of the VRAM headroom FLUX needs for its
    attention buffers → OOM; it is lazy-loaded per scene, after inference. Ends by
    defragmenting the CUDA allocator, which ControlNet setup leaves fragmented.
    """
    _log = run.log
    # ── Quality enhancement services: ControlNet, IPAdapter, ESRGAN ──
    from zyg_workflows import controlnet_service as _cn_svc_v
    from zyg_workflows import ipadapter_service as _ipa_svc_v

    run.cn_svc = _cn_svc_v
    run.ipa_svc = _ipa_svc_v
    run.cn_pipe = None
    run.ipa_ready = False  # IPAdapter disabled (no HuggingFace connectivity)
    run.subject_ref_path = None
    run.esrgan_up = None
    # ControlNet: T5-XXL is now on CPU RAM (~9 GB freed), so VRAM is ~33 GB.
    # ControlNet Union needs ~6 GB — well within the ~15 GB headroom.
    try:
        run.cn_pipe = _cn_svc_v.setup(
            gui_state._FLUX_PIPELINE_CACHE,
            log_fn=lambda m: _log('INFO', 'Stage 2', m),
        )
        if run.cn_pipe is not None:
            _log(
                'INFO',
                'Stage 2',
                'ControlNet pose conditioning loaded ✓ (scene continuity guided by pose skeleton)',
            )
        else:
            _log('WARNING', 'Stage 2', 'ControlNet unavailable — using base FLUX for all scenes')
    except BaseException as _cn_load_e_v:
        run.cn_pipe = None
        _log('WARNING', 'Stage 2', f'ControlNet load failed: {_cn_load_e_v}')
    run.esrgan_model_path = str(paths.ZYG_REALESRGAN_ROOT / 'RealESRGAN_x4plus.pth')
    run.esrgan_available = os.path.exists(run.esrgan_model_path)
    # Defragment CUDA allocator before inference — ControlNet setup
    # may leave fragmented allocations that prevent contiguous blocks
    try:
        run.torch.cuda.empty_cache()
        run.gc.collect()
    except Exception as _exc:
        _zyg_log.debug('CUDA allocator defragmentation skipped: %s', _exc)


def scene_render_plan(run, vfs, sc_data, scene_idx):
    """Build one scene's FLUX call: prompt, canvas size, seed, steps, guidance.

    *vfs* is `video_flux_still_service`, passed in by the orchestrator. The seed is
    fresh per scene; when the DSL is enabled for video, the scene's yaml may
    override the prompt and all three knobs, and a DSL failure is logged and
    leaves the defaults (24 steps, cfg 3.5) standing.
    """
    _log = run.log
    _prompt = vfs.build_flux_prompt(sc_data, run.directive, run.vscfg)
    _flux_w, _flux_h, _ = vfs.flux_dimensions(sc_data)
    _gen_seed_v = _random.randint(0, 2**32 - 1)
    _flux_steps_v = 24
    _flux_cfg_v = 3.5
    if _dsl is not None and _dsl.is_enabled('video'):
        try:
            from zyg_workflows.dsl_runtime import merge_flux_generation_params, scene_yaml_path

            _dsl_dir_v = os.path.join(run.out_dir, 'dsl')
            _prompt, _gen_seed_v, _flux_steps_v, _flux_cfg_v = merge_flux_generation_params(
                _prompt,
                seed=_gen_seed_v,
                steps=_flux_steps_v,
                cfg=_flux_cfg_v,
                dsl_yaml_path=scene_yaml_path(_dsl_dir_v, scene_idx),
                is_schnell=False,
                portrait_mode=vfs.is_portrait_shot(sc_data),
            )
        except Exception as _dsl_flx_e:
            _log('WARNING', 'Stage 2', f'DSL FLUX merge skipped: {_dsl_flx_e}')
    return ScenePlan(
        prompt=_prompt,
        width=_flux_w,
        height=_flux_h,
        seed=_gen_seed_v,
        steps=_flux_steps_v,
        cfg=_flux_cfg_v,
    )


def _comfy_character_still(run, plan, scene_idx, dest_path):
    """Try ComfyUI's character-bible path for one scene; True when the still landed.

    Only attempted when the job names a `char_id` and Comfy is up. On success the
    still is appended to ``run.scene_images`` here, so the caller returns at once;
    any failure is logged and False sends the scene down the diffusers path.
    """
    _log = run.log
    # ── ComfyUI primary path (optional character bible) ─────
    _vid_char_id = run.job.get('char_id', '') or ''
    if not _vid_char_id:
        return False
    try:
        from zyg_workflows import comfy_generation_service as _cgs_vid
        from zyg_workflows import character_bible_service as _cbs_vid

        if _cgs_vid.is_available():
            _pkg_vid = _cbs_vid.load(_vid_char_id)
            _ok_vid, _bk_vid = _cgs_vid.generate_still(
                dest_path,
                plan.prompt,
                width=1360,
                height=768,
                steps=plan.steps,
                cfg=plan.cfg,
                seed=plan.seed,
                character_package=_pkg_vid,
                char_id=_vid_char_id,
                model_family=run.job.get('model_family', 'flux'),
                log_fn=lambda m: _log('INFO', 'Stage 2', m),
            )
            if _ok_vid:
                run.scene_images.append(dest_path)
                _log('INFO', 'Stage 2', f'Scene {scene_idx}: ComfyGen ({_bk_vid})')
                return True
    except Exception as _cgs_vid_e:
        _log('WARNING', 'Stage 2', f'ComfyGen failed — diffusers fallback: {_cgs_vid_e}')
    return False


def _flux_generate_image(run, plan, scene_idx):
    """Run FLUX locally for one scene and return the PIL image.

    Wraps the generation in the two optional conditioners: IPAdapter scene
    continuity (scenes 1+, once a reference is registered) and a ControlNet pose
    extracted from the previous still. A ControlNet generation failure falls back
    to the base pipeline with the same kwargs, and the ControlNet always goes back
    to the CPU afterwards.
    """
    _log = run.log
    _cn_svc_v = run.cn_svc
    _ipa_svc_v = run.ipa_svc
    # ── IPAdapter scene-continuity conditioning (scenes 1+) ──
    _was_ipa_v = False
    if run.ipa_ready and scene_idx > 0 and run.subject_ref_path:
        try:
            _was_ipa_v = _ipa_svc_v.condition_pipe(
                gui_state._FLUX_PIPELINE_CACHE,
                'scene_ref',
                scale=0.55,
                log_fn=lambda m: _log('INFO', 'Stage 2', m),
            )
        except Exception as _ipa_cond_e:
            _log('WARNING', 'Stage 2', f'IPAdapter condition: {_ipa_cond_e}')
    # ── ControlNet: extract pose from previous frame ──────
    _cn_ctrl_img_v = None
    if run.cn_pipe is not None and run.scene_images:
        try:
            _cn_ctrl_img_v = _cn_svc_v.get_pose_image(
                f'scene_{scene_idx}',
                run.scene_images[-1],
            )
        except Exception:
            _cn_ctrl_img_v = None
    # ── Generate with FLUX (ControlNet-wrapped if available) ─
    _gen_kw_v = dict(
        prompt=plan.prompt,
        guidance_scale=plan.cfg,
        num_inference_steps=plan.steps,
        width=plan.width,
        height=plan.height,
        generator=run.torch.Generator('cuda').manual_seed(plan.seed),
    )
    if run.cn_pipe is not None and _cn_ctrl_img_v is not None:
        try:
            _cn_svc_v.controlnet_to_cuda(run.cn_pipe)
            _img_result = run.cn_pipe(
                control_image=_cn_ctrl_img_v,
                **_gen_kw_v,
            ).images[0]
        except Exception as _cn_gen_e:
            _log('WARNING', 'Stage 2', f'ControlNet gen failed: {_cn_gen_e}')
            _img_result = gui_state._FLUX_PIPELINE_CACHE(**_gen_kw_v).images[0]
        finally:
            _cn_svc_v.controlnet_to_cpu(run.cn_pipe)
    else:
        _img_result = gui_state._FLUX_PIPELINE_CACHE(**_gen_kw_v).images[0]
    # ── Reset IPAdapter conditioning after generation ─────
    if _was_ipa_v:
        try:
            _ipa_svc_v.reset_conditioning(gui_state._FLUX_PIPELINE_CACHE)
        except Exception as _exc:
            _zyg_log.warning('IPAdapter reset_conditioning failed, conditioning may persist: %s', _exc)
    return _img_result


def _esrgan_upscale(run, dest_path, scene_idx):
    """4×-upscale *dest_path* with Real-ESRGAN; returns the new path, or *dest_path*.

    The upsampler is lazy-loaded on first use — here, after FLUX inference, and
    never before it, or its ~200 MB comes out of the headroom FLUX needs. Any
    failure is logged and the un-upscaled master frame is kept.
    """
    _log = run.log
    _torch_v = run.torch
    try:
        # Lazy-load ESRGAN here (post-FLUX inference) so it never
        # steals the VRAM headroom FLUX needs during generation.
        if run.esrgan_up is None:
            from basicsr.archs.rrdbnet_arch import RRDBNet as _RRDBNet_v
            import realesrgan as _realesrgan_v

            _esrgan_mdl_v = _RRDBNet_v(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=4,
            )
            run.esrgan_up = _realesrgan_v.RealESRGANer(
                scale=4,
                model_path=run.esrgan_model_path,
                model=_esrgan_mdl_v,
                tile=512,
                tile_pad=16,
                pre_pad=0,
                half=_torch_v.cuda.is_available(),
                device='cuda' if _torch_v.cuda.is_available() else 'cpu',
            )
            _log('INFO', 'Stage 2', 'Real-ESRGAN 4× upsampler ready')
        import cv2 as _cv2_v

        _esrgan_in = _cv2_v.imread(dest_path, _cv2_v.IMREAD_COLOR)
        _esrgan_out, _ = run.esrgan_up.enhance(_esrgan_in, outscale=4)
        _esrgan_path = dest_path.replace('.png', '_4x.png')
        _cv2_v.imwrite(_esrgan_path, _esrgan_out)
        _log('INFO', 'Stage 2', f'ESRGAN 4× applied: scene {scene_idx + 1}')
        return _esrgan_path
    except Exception as _esrgan_e:
        _log('WARNING', 'Stage 2', f'ESRGAN failed: {_esrgan_e}')
    return dest_path


def render_one_scene(run, plan, scene_idx):
    """Produce one scene's still and append its path to ``run.scene_images``.

    ComfyUI's character path first; otherwise FLUX locally — generate, save the
    master frame, register scene 0 as the IPAdapter reference, then optionally
    Real-ESRGAN 4×. Exceptions propagate: the orchestrator's per-scene handler
    logs them and the loop goes on to the next scene.
    """
    _log = run.log
    _dest_path = os.path.join(run.images_dir, f'scene_{scene_idx:04d}.png')
    if _comfy_character_still(run, plan, scene_idx, _dest_path):
        return
    _img_result = _flux_generate_image(run, plan, scene_idx)
    # ── Save master frame ─────────────────────────────────
    _img_result.save(_dest_path)
    # ── Register scene 0 as IPAdapter visual reference ────
    if run.ipa_ready and scene_idx == 0 and run.subject_ref_path is None:
        try:
            run.ipa_svc.register_reference('scene_ref', _dest_path)
            run.subject_ref_path = _dest_path
        except Exception as _ipa_reg_e:
            _log('WARNING', 'Stage 2', f'IPAdapter register: {_ipa_reg_e}')
    # ── Real-ESRGAN 4× upscale before WAN conditioning ────
    if run.esrgan_available:
        _dest_path = _esrgan_upscale(run, _dest_path, scene_idx)
    run.scene_images.append(_dest_path)
    _log('INFO', 'Stage 2', f'FLUX [{run.visual_style}] scene {scene_idx + 1}/{run.n_scenes}')


def teardown_image_services(run):
    """Tear ControlNet, IPAdapter and Real-ESRGAN down before FLUX is unloaded.

    The monolith guarded each block with ``'_name' in dir()``; all three names are
    bound by the time this runs — `setup_quality_services` precedes it inside the
    same `try` — so the guards are the `is not None` / truth checks alone. Every
    teardown failure is swallowed with a note: the FLUX unload after it matters
    more than a hook left on a pipeline that is about to be dropped.
    """
    _log = run.log
    # ── Teardown ControlNet and IPAdapter before FLUX unload ─
    try:
        if run.cn_pipe is not None:
            run.cn_svc.teardown(
                run.cn_pipe,
                log_fn=lambda m: _log('INFO', 'Stage 2', m),
            )
            run.cn_pipe = None
    except Exception as _exc:
        _zyg_log.warning('ControlNet teardown failed, hooks stay on the pipeline: %s', _exc)
    try:
        if run.ipa_ready:
            run.ipa_svc.teardown(
                gui_state._FLUX_PIPELINE_CACHE,
                log_fn=lambda m: _log('INFO', 'Stage 2', m),
            )
    except Exception as _exc:
        _zyg_log.warning('IPAdapter teardown failed, hooks stay on the cached pipeline: %s', _exc)
    # ── Explicit Real-ESRGAN teardown — release VRAM now ─────
    try:
        if run.esrgan_up is not None:
            # Move model off GPU first, then drop the reference
            try:
                run.esrgan_up.model.cpu()
            except Exception as _exc:
                _zyg_log.debug('Real-ESRGAN move to CPU skipped: %s', _exc)
            run.esrgan_up = None
            _log('INFO', 'Stage 2', 'Real-ESRGAN unloaded from VRAM')
    except Exception as _exc:
        _zyg_log.debug('Real-ESRGAN teardown skipped: %s', _exc)
