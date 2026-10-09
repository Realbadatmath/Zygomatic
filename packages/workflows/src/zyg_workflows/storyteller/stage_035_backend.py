# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.5, part 1 — which image backend this run gets, and loading it.

Two functions, both hoisted out of the `with _GPU_PIPELINE_LOCK:` block of
``pipeline_storyteller._run_storyteller_pipeline``:

* :func:`load_flux_diffusers` was the nested ``_st_load_flux_diffusers``
  closure. Its two ``nonlocal`` declarations named six of the block's locals
  (``_flux_i2i_pipe``, ``_use_dev_st``, ``_st_lora_loaded``,
  ``_st_lora_active``, ``_ipa_ready_st``, ``_ipa_svc_st``,
  ``_flux_model_path_st``); each one is now a field of the
  :class:`~zyg_workflows.storyteller.context.ImageGenState` passed in as
  ``st``. It is called from three places — once here, twice from
  ``stage_035_generate.generate_one`` on the Comfy-failure fallback path.
* :func:`select_backend` is the flat statement sequence that followed it:
  pick diffusers-FLUX or Comfy-SDXL, re-resolve a LoRA whose family does not
  match the model, build the img2img pipeline when there is VRAM and a Blender
  reference for it, choose the visual-style prompt prefix, and read the scene
  QC thresholds.

Nothing here changes what a statement does; only where a rebound name lives.
See ``SPLIT_LOG.md``."""

from __future__ import annotations

import logging as _zyg_logging
import os
import tempfile
import time

from zyg_workflows import gui_state, paths
from zyg_workflows.pipeline_storyteller import _st_env_on
from zyg_workflows.vram_manager import _deep_unload_flux_pipeline_cache

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def prepare_flux_paths(ctx, st) -> float:
    """Import torch/diffusers, choose the FLUX checkpoint, wait for VRAM.

    Returns the minimum-free-VRAM figure the guard used, which is the only
    value the rest of the block took from this range. Everything else it binds
    (`st._torch_st`, `st._FluxPipeline`, the two model paths, `st._use_dev_st`)
    is shared with `load_flux_diffusers` and therefore lives on `st`.
    """
    _log = ctx._log

    import torch as _torch_st
    from diffusers import FluxPipeline as _FluxPipeline

    st._torch_st = _torch_st
    st._FluxPipeline = _FluxPipeline
    st._flux_dev_path_st = str(paths.ZYG_FLUX_ROOT / 'flux1-dev')
    st._flux_schnell_path = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
    st._use_dev_st = os.path.isdir(st._flux_dev_path_st)
    # 2026-08-09: this diffusers fallback previously BYPASSED the flux
    # licence pause. Under pause, flux1-dev (BFL NC) must not load;
    # flux1-schnell (Apache-2.0) remains allowed.
    try:
        from zyg_workflows import licence_provenance as _lp_st35

        if _lp_st35.flux_paused() and st._use_dev_st:
            _log('INFO', 'Stage 3.5', '[licence] flux1-dev diffusers fallback blocked (pause) — schnell only')
            st._use_dev_st = False
    except ImportError as _exc:
        _zyg_log.warning('licence_provenance unavailable, the flux1-dev pause was not checked: %s', _exc)
    st._flux_model_path_st = st._flux_dev_path_st if st._use_dev_st else st._flux_schnell_path

    _min_vram_gb = float(os.environ.get('ZYG_SDXL_COMFY_MIN_VRAM_GB', '10')) if st._st_comfy_primary else 36.0
    if st._st_comfy_primary:
        _deep_unload_flux_pipeline_cache(
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
    return _min_vram_gb


def wait_for_vram(ctx, _min_vram_gb: float) -> None:
    """Wait for VRAM before loading FLUX or running the Comfy SDXL batch.

    SimpleTuner training (if running) holds ~16-30 GB; ComfyUI server (port
    8188) typically holds 20-30 GB of cached FLUX weights between requests.
    The shared helper POSTs /free to ComfyUI then polls until ≥36 GB free.
    """
    _log = ctx._log
    try:
        from zyg_workflows import _comfy_client as _cc_st
        import subprocess as _sp_st

        _vram_lock_flag = os.path.join(tempfile.gettempdir(), 'zyg_pause_lora_training.flag')
        try:
            _r = _sp_st.run(['pgrep', '-f', 'simpletuner/.*train.py'], capture_output=True, text=True, timeout=3)
            _train_running = bool((_r.stdout or '').strip())
        except Exception:
            _train_running = False
        if _train_running:
            try:
                with open(_vram_lock_flag, 'w') as _vlf:
                    _vlf.write(f'pid={os.getpid()} stage=3.5 start={time.time():.0f}\n')
                _log('INFO', 'Stage 3.5', 'Concurrent LoRA training detected — signaled pause via flag')
            except Exception as _exc:
                _zyg_log.warning('VRAM pause flag write failed, concurrent LoRA training will not pause: %s', _exc)

        _ok_vg, _free_gb = _cc_st.wait_for_free_vram_gb(
            min_free_gb=_min_vram_gb,
            timeout_s=7200,
            poll_s=10.0,
            try_evict=True,
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
        if _ok_vg:
            _log('INFO', 'Stage 3.5', f'VRAM guard cleared — {_free_gb:.1f} GB free')
        else:
            _log(
                'WARNING',
                'Stage 3.5',
                f'VRAM guard timed out — proceeding with {_free_gb:.1f} GB free (Schnell fallback may be used)',
            )
    except Exception as _exc:
        _zyg_log.warning('VRAM guard failed, Stage 3.5 proceeds without it: %s', _exc)


def load_flux_diffusers(ctx, st, *, load_ipadapter: bool = True) -> bool:
    """Load FLUX diffusers + optional LoRA/IPAdapter (after Comfy VRAM release)."""
    # 2026-07-31: _ipa_svc_st was added to the old `nonlocal` list. It was
    # set to None at the top of the block and NEVER reassigned — only the
    # _ipa_ready_st boolean was propagated — so every later call
    # (condition_pipe / reset_conditioning / register_reference / teardown)
    # raised AttributeError on None and was swallowed, while the log claimed
    # 'identity conditioning enabled'. The mechanism has never worked.
    _log = ctx._log
    char_id = ctx.char_id
    model_family = ctx.model_family
    _ssh_st = st._ssh_st
    _torch_st = st._torch_st
    if gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
        return True
    try:
        from zyg_workflows import _comfy_client as _cc_flux_ld

        _cc_flux_ld.free_vram()
        _cc_flux_ld.wait_for_free_vram_gb(
            min_free_gb=36.0,
            timeout_s=600,
            poll_s=5.0,
            try_evict=True,
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
    except Exception as _exc:
        _zyg_log.debug('comfy VRAM release before the FLUX load skipped: %s', _exc)
    _free_pre, _total_vram = _torch_st.cuda.mem_get_info(0)
    _has_vram_for_dev = _free_pre / 1e9 >= 36.0
    st._use_dev_st = st._use_dev_st and _has_vram_for_dev
    st._flux_model_path_st = st._flux_dev_path_st if st._use_dev_st else st._flux_schnell_path
    if not _has_vram_for_dev and os.path.isdir(st._flux_dev_path_st):
        _log(
            'INFO',
            'Stage 3.5',
            f'VRAM tight ({_free_pre / 1e9:.1f} GB free / {_total_vram / 1e9:.0f} GB total) '
            f'— using FLUX Schnell to avoid OOM (Dev needs ≥36 GB free)',
        )
    _log('INFO', 'Stage 3.5', f'Loading FLUX.1-{"dev" if st._use_dev_st else "schnell"} (diffusers)…')
    gui_state._FLUX_DEV_PIPELINE_CACHE = st._FluxPipeline.from_pretrained(
        st._flux_model_path_st,
        torch_dtype=_torch_st.bfloat16,
    ).to('cuda')
    gui_state._FLUX_DEV_PIPELINE_CACHE.vae.enable_tiling()

    from zyg_workflows import character_lora_family as _clf_st35_ld

    if st.lora_path and model_family == 'flux':
        if _clf_st35_ld.lora_path_matches_family(st.lora_path, 'flux'):
            _log('INFO', 'Stage 3.5', f'Loading FLUX character LoRA: {st.lora_path}')
            st._st_lora_loaded = _ssh_st.flux_load_character_lora(
                gui_state._FLUX_DEV_PIPELINE_CACHE,
                st.lora_path,
                lambda m: _log('INFO', 'Stage 3.5', m),
                scale=0.8,
            )
        else:
            _log('WARNING', 'Stage 3.5', 'LoRA path is not FLUX-family — skipping diffusers LoRA load')
            _resolved = _clf_st35_ld.resolve_char_lora_path(char_id, 'flux') if char_id else None
            if _resolved:
                st._st_lora_loaded = _ssh_st.flux_load_character_lora(
                    gui_state._FLUX_DEV_PIPELINE_CACHE,
                    _resolved,
                    lambda m: _log('INFO', 'Stage 3.5', m),
                    scale=0.8,
                )
        if st.lora_path and not st._st_lora_loaded:
            _log('WARNING', 'Stage 3.5', 'FLUX LoRA load failed — txt2img without LoRA weights')
            st._st_lora_active = False

    if load_ipadapter:
        try:
            from zyg_workflows import ipadapter_service as _ipa_svc_ld

            if _ipa_svc_ld.setup(
                gui_state._FLUX_DEV_PIPELINE_CACHE,
                log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
            ):
                # 2026-07-31: keep the SERVICE, not just the flag.
                st._ipa_svc_st = _ipa_svc_ld
                st._ipa_ready_st = True
                _log('INFO', 'Stage 3.5', 'IPAdapter service loaded — identity conditioning enabled')
            else:
                _log(
                    'INFO',
                    'Stage 3.5',
                    'IPAdapter setup declined — identity conditioning DISABLED on the diffusers path',
                )
        except Exception as _ipa_ld_e:
            _log('INFO', 'Stage 3.5', f'IPAdapter not available ({_ipa_ld_e!r}) — proceeding without')
    else:
        _log(
            'INFO',
            'Stage 3.5',
            'IPAdapter conditioning disabled by ZYG_ST_IPADAPTER_DIFFUSERS=0 '
            '— diffusers scenes get NO identity conditioning',
        )
    return True


# Visual style quality prefix — biased toward bright, clean, readable output.
# Avoid dark/moody/cinematic terms that push FLUX toward muddy brown shadows.
_STYLE_PREFIX_ST = {
    'cinematic': 'bright animated movie lighting, soft daylight, high-key illumination, vibrant colors, clean global illumination, balanced exposure, ',
    'anime': 'anime art style, vibrant saturated colors, studio ghibli inspired, bright soft lighting, clean linework, ',
    'disney': 'disney 2D animation style, expressive, vibrant colors, warm soft lighting, clean bright frame, ',
    'art': 'digital concept art, detailed illustration, bright studio lighting, vivid colors, clean composition, ',
    'realism': 'photorealistic, sharp detail, warm natural daylight, soft shadows, clear skin tones, bright exposure, ',
    '3d_render': '3D render, Pixar-inspired lighting, subsurface scattering, warm soft illumination, vibrant colors, ',
    'filmic': 'warm film photography, soft natural light, gentle shadows, clear exposure, vibrant tones, ',
    'scenery': 'epic landscape photography, golden hour, wide angle, bright natural lighting, vivid colors, ',
    'mjv6': 'artistic masterpiece, intricate detail, bright studio lighting, award winning, vibrant, ',
}


def select_backend(ctx, st) -> None:
    """Load the chosen backend, fix up the LoRA, set the prompt prefix and QC bar."""
    _animated_render = ctx._animated_render
    _log = ctx._log
    _restyle_caption_prefix = ctx._restyle_caption_prefix
    _restyle_render = ctx._restyle_render
    char_id = ctx.char_id
    model_family = ctx.model_family
    pipeline_state = ctx.pipeline_state
    visual_style = ctx.visual_style
    _char_ref_img = st._char_ref_img
    _ssh_st = st._ssh_st
    _torch_st = st._torch_st

    if st._st_use_flux_diffusers:
        load_flux_diffusers(
            ctx,
            st,
            load_ipadapter=_st_env_on('ZYG_ST_IPADAPTER_DIFFUSERS'),
        )
        if st.lora_path and model_family == 'sdxl':
            _log('INFO', 'Stage 3.5', 'SDXL LoRA is applied via Comfy only (not loaded into FLUX diffusers)')

    elif st.lora_path and model_family == 'sdxl':
        from zyg_workflows import character_lora_family as _clf_st35b

        if not _clf_st35b.lora_path_matches_family(st.lora_path, 'sdxl'):
            _fixed = _clf_st35b.resolve_char_lora_path(char_id, 'sdxl') if char_id else None
            if _fixed:
                st.lora_path = _fixed
                st._st_lora_active = True
                if pipeline_state.get('character_bible'):
                    try:
                        from zyg_workflows import character_bible_service as _cbs_fix

                        _cbs_fix.update_lora(char_id, st.lora_path, model_family='sdxl')
                    except Exception as _exc:
                        _zyg_log.warning('character bible lora update failed, the bible keeps the stale path: %s', _exc)
            else:
                _log(
                    'WARNING',
                    'Stage 3.5',
                    'No SDXL LoRA for this character — identity via Comfy reference only',
                )
                st.lora_path = None
                st._st_lora_active = False

    # Build img2img pipeline only when FLUX diffusers is loaded
    _min_i2i_gb = float(os.environ.get('ZYG_IMG2IMG_MIN_VRAM_GB', '4.0'))
    if (
        gui_state._FLUX_DEV_PIPELINE_CACHE is not None
        and _char_ref_img
        and os.path.isfile(_char_ref_img)
        and os.path.getsize(_char_ref_img) > 10_000
    ):
        _free_i2i_gb = _ssh_st.cuda_free_gb()
        if _free_i2i_gb < _min_i2i_gb:
            _log(
                'INFO',
                'Stage 3.5',
                f'Img2img skipped — {_free_i2i_gb:.1f} GB VRAM free (need ≥{_min_i2i_gb:.1f} GB); using txt2img/Comfy',
            )
        else:
            try:
                from diffusers import FluxImg2ImgPipeline as _FluxI2I_st

                st._flux_i2i_pipe = _FluxI2I_st.from_pipe(gui_state._FLUX_DEV_PIPELINE_CACHE)
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Img2img pipeline ready — Blender reference: '
                    f'{os.path.basename(_char_ref_img)} ({_free_i2i_gb:.1f} GB free)',
                )
            except Exception as _i2i_e:
                _i2i_msg = str(_i2i_e)
                _log('WARNING', 'Stage 3.5', f'Img2img setup failed ({_i2i_msg}) — using txt2img')
                if 'out of memory' in _i2i_msg.lower():
                    try:
                        _torch_st.cuda.empty_cache()
                    except Exception as _exc:
                        _zyg_log.debug('cuda cache clear after the img2img OOM skipped: %s', _exc)

    st._style_prefix_st = _STYLE_PREFIX_ST.get(visual_style, 'bright soft lighting, vibrant colors, clean exposure, ')
    # 2026-07-25: SDXL twin = 3D-toon — override the (photoreal-ish)
    # style prefix (the animated-effective package is built per-scene
    # below, once _b_st is loaded).
    if _animated_render:
        st._style_prefix_st = (
            '3D Pixar animation style, stylized 3d animated movie still, '
            'cel-shaded, vibrant colors, clean bright frame, '
        )
    elif _restyle_render and _restyle_caption_prefix:
        # Arcane painterly prefix (not the Pixar/photoreal prefix).
        st._style_prefix_st = _restyle_caption_prefix

    if st._st_comfy_primary:
        _log(
            'INFO',
            'Stage 3.5',
            'IPAdapter deferred — Comfy-primary uses LoRA + reference; diffusers IPAdapter only on fallback path',
        )

    # ── Scene image quality checker ───────────────────────────────────
    # 2026-07-25: animated (SDXL twin) frames use the relaxed
    # 'animated' sharpness floor — 3D-toon flat shading legitimately
    # lowers Laplacian variance (run b6dae41a soft-photoreal aside,
    # DynaVision renders crisp but flat-region-heavy).
    st._qc_style_st = 'animated' if (_animated_render or _restyle_render) else visual_style
    _QC_MIN_BRIGHT_ST, _QC_MIN_SHARP_ST = _ssh_st.scene_qc_thresholds(
        st._qc_style_st,
        lora_active=st._st_lora_active,
    )
    _log(
        'INFO',
        'Stage 3.5',
        f'Scene QC thresholds: brightness≥{_QC_MIN_BRIGHT_ST:.0f}, '
        f'sharp≥{_QC_MIN_SHARP_ST:.0f} (style={visual_style}, '
        f'lora={"yes" if st._st_lora_active else "no"})',
    )
