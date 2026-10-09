# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.5, part 3 — render one scene image, Comfy first, diffusers second.

``_st_generate_one``, the largest closure of the old
`with _GPU_PIPELINE_LOCK:` block, hoisted to module level as
:func:`generate_one`. Its ``nonlocal _st_lora_loaded, _flux_i2i_pipe,
_use_dev_st, _ipa_ready_st`` line is gone: all four are fields of the
:class:`~zyg_workflows.storyteller.context.ImageGenState` passed in as ``st``
(``_ipa_ready_st`` was in the declaration but the body never rebound it).

``_run_pipe`` stays a nested ``def`` — it is called twice from two branches of
one function and closes over that call's ``prompt``/``init_img``, so it is not
a cross-module hoist and nothing about it changes.

The Comfy-failure fallback calls back into
:func:`~zyg_workflows.storyteller.stage_035_backend.load_flux_diffusers`; that
is the only edge between the Stage 3.5 modules that is not image_gen → part.
See ``SPLIT_LOG.md``."""

from __future__ import annotations

import logging as _zyg_logging
import os
import time

from zyg_workflows import gui_state
from zyg_workflows.runtime import _bm_record
from zyg_workflows.storyteller.stage_035_backend import load_flux_diffusers

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def generate_one(
    ctx,
    st,
    prompt: str,
    path: str,
    init_img: str | None = None,
    *,
    seed_attempt: int = 0,
    scene_index: int = 0,
    shot_type: str = 'medium',
    scene_emotion: str = 'calm',
) -> bool:
    """Run FLUX/Comfy for one scene; return True on success.

    Storyteller uses LoRA locked txt2img for Blender-trained characters
    (never greybox portrait img2img). Photo-based chars may use scene_0
    as a photoreal img2img anchor after scene 0 passes QC.
    """
    _animated_render = ctx._animated_render
    _check_stop = ctx._check_stop
    _log = ctx._log
    _restyle_render = ctx._restyle_render
    char_id = ctx.char_id
    model_family = ctx.model_family
    pipeline_state = ctx.pipeline_state
    _ssh_st = st._ssh_st
    _st_blender_ds = st._st_blender_ds
    _st_comfy_primary = st._st_comfy_primary
    _st_drift_ref_ok = st._st_drift_ref_ok
    _torch_st = st._torch_st
    # 2026-07-24 r3: gate the still-image anchor ONCE for every
    # backend — Comfy AND diffusers fallback. LoRA identities
    # never anchor to a still (the init composition beats the
    # scene prompt; run dd36662e cloned the preview 24×, and the
    # diffusers _run_pipe below reads init_img directly).
    if st._st_lora_active and not _st_blender_ds:
        init_img = None
    try:
        _check_stop()
        import copy as _copy_st_gen
        from zyg_workflows import comfy_generation_service as _cgs_stg

        if _cgs_stg.is_available():
            _pkg_st = pipeline_state.get('character_bible')
            if _pkg_st:
                _pkg_st = _copy_st_gen.deepcopy(_pkg_st)
                _pkg_st.setdefault('conditioning', {})['hand_detail_pass'] = True
            _seed_st = _ssh_st.scene_generation_seed(
                path,
                scene_index=scene_index,
                attempt=seed_attempt,
            )
            _init_use = None
            # 2026-07-24 r3: LoRA-locked scenes NEVER take a still-image
            # init. Run dd36662e anchored every scene to the character
            # preview at denoise 0.55 — the init composition beat every
            # scene prompt and all 24 scenes shipped as near-copies of
            # preview_flux_face.png (pixel MAD 10-14/255). With a trained
            # LoRA the identity lives in the LoRA; txt2img lets each
            # scene's own prompt control setting and composition. Chars
            # WITHOUT a LoRA keep the pixel anchor (their only identity
            # mechanism) at a denoise high enough for scene variety.
            if not _st_blender_ds and not st._st_lora_active:
                if init_img and os.path.isfile(init_img):
                    _init_use = init_img
                elif scene_index > 0:
                    _s0m = pipeline_state.get('_st_scene0_master')
                    if _s0m and os.path.isfile(_s0m):
                        _init_use = _s0m
            _denoise_st = 0.70 if _init_use else None
            if _init_use and seed_attempt > 0:
                _denoise_st = max(0.58, 0.70 - seed_attempt * 0.06)
            _force_wf = None
            if _st_comfy_primary and st._st_lora_active:
                if scene_index == 0 or _st_blender_ds or not _init_use:
                    # 2026-07-24 fix: workflow must match the model family — the
                    # hardcoded sdxl_character_locked paired SDXL base with a FLUX
                    # LoRA on FLUX runs (unmappable graph, guaranteed Comfy error).
                    _force_wf = (
                        'flux_character_locked' if (model_family or '').lower() == 'flux' else 'sdxl_character_locked'
                    )
            # r4/2026-07-25: the FaceDetailer pore/realism pass
            # re-realisms a 3D-toon face — disable for animated.
            # r4/2026-07-27: also disable for restyle — the FaceDetailer
            # pore/realism pass repaints a painterly Arcane face photoreal.
            _fd_enable = not (_animated_render or _restyle_render)
            if not (_animated_render or _restyle_render):
                try:
                    from zyg_workflows import character_bible_service as _cbs_fd

                    _fd_enable = _cbs_fd.storyteller_face_detail_enabled(
                        shot_type,
                        scene_emotion,
                    )
                except Exception as _exc:
                    _zyg_log.warning('face-detail policy lookup failed, using the render-mode default: %s', _exc)
            _comfy_kwargs = dict(
                width=1280,
                height=720,
                steps=20 if st._use_dev_st else 4,
                cfg=3.5 if st._use_dev_st else 1.0,
                seed=_seed_st,
                denoise=_denoise_st,
                character_package=_pkg_st,
                char_id=char_id,
                init_image=_init_use,
                reference_image=None if _st_blender_ds else (pipeline_state.get('char_reference_image')),
                model_family=model_family,
                log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
                force_workflow=_force_wf,
                blender_dataset=_st_blender_ds,
                prompt_finalized=True,
                enable_face_detailer=_fd_enable,
                shot_type=shot_type,
                scene_emotion=scene_emotion,
                # 2026-07-25: the drift reference is the photoreal
                # master; a 3D-toon frame scores low against it, so
                # drift must not be fatal for animated renders
                # (consistency comes from the animated LoRA + dupe gate).
                # 2026-07-31: …and only when a VERIFIED reference
                # embedding exists (see _st_drift_ref_ok).
                require_drift_pass=(
                    scene_index == 0 and _st_drift_ref_ok and not (_animated_render or _restyle_render)
                ),
            )
            _ok_c, _bk_c = _cgs_stg.generate_still(path, prompt, **_comfy_kwargs)
            if not _ok_c and _st_comfy_primary:
                try:
                    from zyg_workflows import _comfy_client as _cc_retry

                    _cc_retry.free_vram()
                except Exception as _exc:
                    _zyg_log.debug('comfy VRAM release before the retry skipped: %s', _exc)
                _ok_c, _bk_c = _cgs_stg.generate_still(path, prompt, **_comfy_kwargs)
            if _ok_c:
                _log('INFO', 'Stage 3.5', f'ComfyGen OK ({_bk_c}) → {os.path.basename(path)}')
                return True
            if _st_comfy_primary:
                _log(
                    'INFO',
                    'Stage 3.5',
                    'ComfyGen failed — loading diffusers FLUX fallback (VRAM permitting)',
                )
                if not load_flux_diffusers(ctx, st, load_ipadapter=False):
                    return False
    except Exception as _cgs_st_e:
        if _st_comfy_primary:
            _log('WARNING', 'Stage 3.5', f'ComfyGen failed ({_cgs_st_e}) — trying diffusers fallback')
            if not load_flux_diffusers(ctx, st, load_ipadapter=False):
                return False
        else:
            _log('WARNING', 'Stage 3.5', f'ComfyGen failed — diffusers fallback: {_cgs_st_e}')

    if gui_state._FLUX_DEV_PIPELINE_CACHE is None:
        _log('WARNING', 'Stage 3.5', 'FLUX diffusers not loaded — cannot run fallback generation')
        return False

    def _run_pipe():
        if init_img and st._flux_i2i_pipe is not None:
            from PIL import Image as _PIL_i2i

            # r3: cover-crop, not plain resize — a square init
            # stretched to 16:9 fed anamorphic proportions into
            # every downstream i2i render.
            _base = _PIL_i2i.open(init_img).convert('RGB')
            _bs = max(1280 / _base.width, 720 / _base.height)
            _base = _base.resize(
                (max(1280, round(_base.width * _bs)), max(720, round(_base.height * _bs))),
                _PIL_i2i.LANCZOS,
            )
            _bl = (_base.width - 1280) // 2
            _bt = (_base.height - 720) // 2
            _base = _base.crop((_bl, _bt, _bl + 1280, _bt + 720))
            return st._flux_i2i_pipe(
                prompt=prompt,
                image=_base,
                strength=0.65,
                height=720,
                width=1280,
                num_inference_steps=20 if st._use_dev_st else 8,
                guidance_scale=3.5 if st._use_dev_st else 0.0,
                max_sequence_length=512 if st._use_dev_st else 256,
            ).images[0]
        return gui_state._FLUX_DEV_PIPELINE_CACHE(
            prompt=prompt,
            height=720,
            width=1280,
            num_inference_steps=20 if st._use_dev_st else 8,
            guidance_scale=3.5 if st._use_dev_st else 0.0,
            max_sequence_length=512 if st._use_dev_st else 256,
        ).images[0]

    try:
        _t0 = time.monotonic()
        _img = _run_pipe()
        _mode = 'flux_i2i' if (init_img and st._flux_i2i_pipe) else ('flux_dev' if st._use_dev_st else 'flux_schnell')
        _bm_record(_mode, time.monotonic() - _t0, count=1)
        _img.save(path)
        return True
    except Exception as _ge:
        _ge_msg = str(_ge).lower()
        _is_oom = 'out of memory' in _ge_msg
        _is_dtype = 'must have the same dtype' in _ge_msg
        if _is_oom or _is_dtype:
            # Tier 1: model CPU offload — keeps transformer on GPU, offloads text
            # encoders + VAE; saves ~8 GB VRAM, ~15% slower.
            # After load_lora_weights + set_adapters, some adapter layers
            # may be in float32; force everything back to bfloat16 before
            # re-running to avoid "Float and BFloat16" matmul errors.
            try:
                if _is_dtype:
                    _log(
                        'WARNING',
                        'Stage 3.5',
                        'dtype mismatch — coercing pipeline back to bfloat16 and retrying…',
                    )
                else:
                    _log('WARNING', 'Stage 3.5', 'OOM — retrying with model CPU offload…')
                try:
                    gui_state._FLUX_DEV_PIPELINE_CACHE.enable_model_cpu_offload()
                except Exception as _exc:
                    _zyg_log.warning('model CPU offload failed, the OOM retry may OOM again: %s', _exc)
                # Coerce all sub-modules + LoRA adapter params to bfloat16
                for _comp_name in (
                    'transformer',
                    'text_encoder',
                    'text_encoder_2',
                    'vae',
                ):
                    _comp = getattr(gui_state._FLUX_DEV_PIPELINE_CACHE, _comp_name, None)
                    if _comp is None:
                        continue
                    try:
                        for _p in _comp.parameters():
                            if _p.dtype == _torch_st.float32:
                                _p.data = _p.data.to(_torch_st.bfloat16)
                        for _b in _comp.buffers():
                            if _b.dtype == _torch_st.float32:
                                _b.data = _b.data.to(_torch_st.bfloat16)
                    except Exception as _exc:
                        _zyg_log.warning(
                            'bfloat16 coercion failed for %s, the dtype retry may fail again: %s',
                            _comp_name,
                            _exc,
                        )
                _torch_st.cuda.empty_cache()
                # Retry LoRA load only if it hasn't been successfully loaded yet
                if st.lora_path and model_family == 'flux' and not st._st_lora_loaded:
                    try:
                        st._st_lora_loaded = _ssh_st.flux_load_character_lora(
                            gui_state._FLUX_DEV_PIPELINE_CACHE,
                            st.lora_path,
                            lambda m: _log('INFO', 'Stage 3.5', m),
                        )
                    except Exception as _lora_retry_e:
                        _log('WARNING', 'Stage 3.5', f'LoRA retry load failed: {_lora_retry_e}')
                        st._st_lora_loaded = False
                _t0 = time.monotonic()
                _img = _run_pipe()
                _bm_record('flux_model_offload', time.monotonic() - _t0, count=1)
                _img.save(path)
                return True
            except Exception as _cpu_e:
                _log('WARNING', 'Stage 3.5', f'Model CPU offload retry failed: {_cpu_e}')
        _log('WARNING', 'Stage 3.5', f'FLUX generate failed: {_ge}')
        return False
