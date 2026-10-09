# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The load steps of `setup_flux_pipes`, one function per block it used to inline.

`setup_flux_pipes` in `stages_37_54_flux_setup` was 390 lines — the whole
"get FLUX, its LoRA, its ControlNet and its worker onto the card" sequence as
one frame, which is why none of it had ever been exercised without a GPU. The
blocks here are that body, in source order and statement for statement:

* `teardown_stale_controlnet` — the pre-load ControlNet teardown;
* `evict_ollama_models` — the Ollama VRAM eviction and its confirmation read;
* `load_flux_pipeline` — the VRAM wait, `from_pretrained`, the per-component
  `.to('cuda')` moves, the T5-on-CPU patch and VAE tiling. The patch's
  `_t5_cpu_fwd` closure is `t5_cpu_prompt_embeds` here, a module-level function
  bound with `types.MethodType` exactly as the nested `def` was;
* `load_style_lora` — the three-way `visual_style` LoRA ladder, with the key
  rewrite it does twice as `normalize_lora_keys`;
* `load_controlnet` — the `from_pipe()` ControlNet load and the T5 placement
  that follows it;
* `claim_flux_worker` — the FluxWorker ownership transfer and the pipe-slot
  acquisition. The transfer's `_fw_teardown_fn` closure is `release_for_worker`
  here, handed to `complete_start` as a `functools.partial` so the worker still
  calls it with no arguments;
* `resolve_controlnet_pipe` — the post-load ControlNet assignment.

Every function takes the stage context as `ctx` (the object the orchestrator
reads `_log`, `_debug` and the backend handles off) plus the values that were
plain locals of the one frame; nothing is read back out of a closure. The two
pure ones — `normalize_lora_keys` and `style_lora_config` — need no context at
all, which is what makes the ladder testable without a card.
"""

import functools
import gc as _gc_flux
import json
import os
import types

from zyg_workflows import gui_state
from zyg_workflows.net import safe_urlopen
from zyg_workflows.pipeline_config import (
    _FLUX_LORA_PATH,
    _FLUX_LORA_SCALE,
    _OLLAMA_BASE_URL,
    _STYLE_LORA_CONFIG,
    _STYLE_LORA_DIR,
)
from zyg_workflows.pipeline_scholarly import (
    _smoke_cap,
)
from zyg_workflows.vram_manager import (
    _deep_unload_flux_pipeline_cache,
    _wait_for_vram,
    _wait_ollama_unload,
)


def teardown_stale_controlnet(ctx, torch_flux):
    """Free a ControlNet pipeline left behind by an earlier Stage 3.5.

    In: the stage context (for `_log`/`_debug`) and the imported `torch` module.
    Out: nothing — and nothing at all happens when `_CN_PIPE_CACHE` is already
    empty. `FluxControlNetPipeline` holds internal refs to FLUX tensors, so
    clearing the cache without a `gc.collect()` leaves them resident and a
    second Stage 3.5 in the same process spikes to two FLUX copies.
    """
    _debug = ctx._debug
    _log = ctx._log
    if gui_state._CN_PIPE_CACHE is None:
        return
    try:
        from zyg_workflows import controlnet_service as _cns_pre

        _cns_pre.teardown(
            gui_state._CN_PIPE_CACHE,
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
    except Exception as _cn_pre_e:
        _debug('Stage 3.5', f'Pre-load CN teardown (non-fatal): {_cn_pre_e}', level='WARN')
    gui_state._CN_PIPE_CACHE = None
    _gc_flux.collect()
    torch_flux.cuda.empty_cache()
    _free_pre = torch_flux.cuda.mem_get_info(0)[0] / 1024**3
    _log('INFO', 'Stage 3.5', f'ControlNet torn down before FLUX load — {_free_pre:.1f} GB VRAM free')


def evict_ollama_models(ctx):
    """Unload every hot Ollama model so its 5-7 GB of VRAM is FLUX's.

    In: the stage context. Out: nothing. Each model gets a `keep_alive: 0`
    generate call and a bounded wait, then one confirmation read of `/api/ps`
    names whatever is still resident. The whole block is non-fatal: an Ollama
    that cannot be reached is logged and the load goes ahead.
    """
    _debug = ctx._debug
    _log = ctx._log
    try:
        _ops = json.loads(safe_urlopen(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read())

        for _om in _ops.get('models', []):
            _omn = _om.get('name', '')
            if _omn:
                _upl = json.dumps({'model': _omn, 'prompt': ' ', 'keep_alive': 0, 'stream': False}).encode()
                safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_upl, timeout=60)
                _wait_ollama_unload(_omn, timeout=30)
                _log('INFO', 'Stage 3.5', f'Ollama unloaded: {_omn} — VRAM freed')
        # Confirm all models are gone before proceeding
        _verify = json.loads(safe_urlopen(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read())
        _still_hot = [m.get('name', '') for m in _verify.get('models', []) if m.get('name')]
        if _still_hot:
            _log('WARNING', 'Stage 3.5', f'Ollama models still in VRAM after eviction: {_still_hot}')
        else:
            _log('INFO', 'Stage 3.5', 'Ollama VRAM confirmed clear')
    except Exception as _ollama_unload_e:
        _debug('Stage 3.5', f'Ollama unload failed (non-fatal): {_ollama_unload_e}', level='WARN')


def t5_cpu_prompt_embeds(self, prompt=None, num_images_per_prompt=1, max_sequence_length=512, device=None, dtype=None):
    """Encode the prompt with T5-XXL where it lives (CPU), return embeds on *device*.

    In: the FLUX pipeline as `self` plus `FluxPipeline._get_t5_prompt_embeds`'s
    own arguments. Out: the `(batch * num_images_per_prompt, seq_len, dim)`
    embedding tensor, moved to the transformer's device. Bound onto the pipeline
    by `load_flux_pipeline`, which is what keeps the 9 GB text encoder in CPU
    RAM while the transformer, CLIP and VAE have the card.
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


def load_flux_pipeline(ctx, torch_flux, flux_pipeline_cls):
    """Load FLUX into `gui_state._FLUX_PIPELINE_CACHE` and place its components.

    In: the stage context (for `_flux_model_path` and the log hooks), the
    imported `torch` module and the `FluxPipeline` class the prelude imported.
    Out: nothing — the pipeline is published on `gui_state`, as the monolith
    published it. Transformer + CLIP + VAE go to CUDA (~24 GB), T5-XXL stays in
    CPU RAM behind `t5_cpu_prompt_embeds`, and VAE tiling is enabled so the
    decode fits beside ControlNet.
    """
    _debug = ctx._debug
    _flux_model_path = ctx._flux_model_path
    _log = ctx._log
    _vram_ok = _wait_for_vram(25.0, timeout=120, label='FLUX load')
    if not _vram_ok:
        _log('WARNING', 'Stage 3.5', 'Could not free 25GB VRAM — forcing torch cache clear')
        _debug('Stage 3.5', 'Forcing torch CUDA cache empty before FLUX load', level='WARN')
    torch_flux.cuda.empty_cache()
    _gc_flux.collect()
    _smoke_flux = _smoke_cap() > 0
    _log(
        'INFO',
        'Stage 3.5',
        'Loading FLUX.1-schnell (VRAM, smoke mode)…' if _smoke_flux else 'Loading FLUX.1-schnell (VRAM)…',
    )
    # Load FLUX to CPU first, then selectively move components to CUDA.
    # T5-XXL (text_encoder_2, ~9 GB) stays in CPU RAM — it only runs once
    # per image to encode the text prompt (~0.5s), then is idle.
    # Transformer + CLIP + VAE go to CUDA (~24 GB). This frees ~9 GB VRAM
    # so ControlNet (6.2 GB) fits comfortably alongside FLUX.
    gui_state._FLUX_PIPELINE_CACHE = flux_pipeline_cls.from_pretrained(
        _flux_model_path,
        torch_dtype=torch_flux.bfloat16,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    gui_state._FLUX_PIPELINE_CACHE.transformer.to('cuda')
    gui_state._FLUX_PIPELINE_CACHE.text_encoder.to('cuda')
    gui_state._FLUX_PIPELINE_CACHE.vae.to('cuda')
    # Patch T5 encoding: run on CPU (where model lives), move tiny
    # embedding tensor (~512×4096 floats) to CUDA for the transformer.
    gui_state._FLUX_PIPELINE_CACHE._get_t5_prompt_embeds = types.MethodType(
        t5_cpu_prompt_embeds, gui_state._FLUX_PIPELINE_CACHE
    )
    # VAE tiling: decode the latent in spatial tiles instead of all-at-once.
    # Without tiling, the VAE decoder needs ~144 MB of activation headroom
    # that isn't available after FLUX+ControlNet fill 47/47.4 GB VRAM.
    # Tiling reduces peak VRAM during decode by ~10–15 GB with no quality cost.
    gui_state._FLUX_PIPELINE_CACHE.enable_vae_tiling()
    _log(
        'INFO',
        'Stage 3.5',
        'FLUX loaded — transformer+CLIP+VAE on CUDA (~24 GB), T5-XXL on CPU (~9 GB RAM), VAE tiling enabled',
    )


def normalize_lora_keys(raw):
    """Rewrite SimpleTuner LoRA keys to the diffusers convention.

    In: the state dict `safetensors.torch.load_file` returned. Out: a new dict
    with `.lora.down.` → `.lora_A.` and `.lora.up.` → `.lora_B.`; the values are
    the same tensors. The two directory-LoRA branches of `load_style_lora` both
    do this, and `load_lora_weights` rejects the un-rewritten keys.
    """
    return {k.replace('.lora.down.', '.lora_A.').replace('.lora.up.', '.lora_B.'): v for k, v in raw.items()}


def style_lora_config(visual_style):
    """The `_STYLE_LORA_CONFIG` entry for *visual_style*, or the cinematic one.

    In: the run's visual style name. Out: that style's config dict — the
    `cinematic` entry stands in for a style the table does not know, which is
    what keeps an unknown style from crashing the load.
    """
    return _STYLE_LORA_CONFIG.get(visual_style, _STYLE_LORA_CONFIG['cinematic'])


def load_style_lora(ctx):
    """Load the style LoRA for `ctx.visual_style` onto the cached FLUX pipeline.

    In: the stage context. Out: `True` when a LoRA was actually applied. Three
    exclusive sources, in the monolith's order: the style's single `lora` file
    under `_STYLE_LORA_DIR`, else its `lora_dir` safetensors, else the global
    `_FLUX_LORA_PATH`. Every failure is a warning and the load continues
    without the LoRA — a missing style file never fails the stage.
    """
    _log = ctx._log
    visual_style = ctx.visual_style
    _sch_vscfg = style_lora_config(visual_style)
    _sch_lora_file = _sch_vscfg.get('lora')
    _sch_lora_scale = _sch_vscfg.get('scale', 1.0)
    _sch_lora_loaded = False
    if _sch_lora_file:
        _sch_lora_path = os.path.join(_STYLE_LORA_DIR, _sch_lora_file)
        if os.path.exists(_sch_lora_path):
            try:
                gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_sch_lora_path)
                gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                    ['default_0'],
                    adapter_weights=[_sch_lora_scale],
                )
                _sch_lora_loaded = True
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Style LoRA loaded: {_sch_lora_file} @ scale {_sch_lora_scale} [{visual_style}]',
                )
            except Exception as _slora_e:
                _log(
                    'WARNING',
                    'Stage 3.5',
                    f'Style LoRA load failed (continuing without): {_slora_e}',
                )
        else:
            _log('WARNING', 'Stage 3.5', f'Style LoRA file not found: {_sch_lora_path}')
    elif _sch_vscfg.get('lora_dir'):
        # Style-specific LoRA from a directory (e.g. documentary-cinematic).
        # SimpleTuner keys use .lora.down/.lora.up — normalize to diffusers convention.
        try:
            import safetensors.torch as _st_lora

            _lora_sf = os.path.join(_sch_vscfg['lora_dir'], 'pytorch_lora_weights.safetensors')
            if os.path.exists(_lora_sf):
                _norm_lora = normalize_lora_keys(_st_lora.load_file(_lora_sf))
                gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_norm_lora)
                gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                    ['default_0'],
                    adapter_weights=[_sch_vscfg.get('lora_dir_scale', 0.75)],
                )
                _sch_lora_loaded = True
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Style LoRA loaded from dir: {_sch_vscfg["lora_dir"]} @ scale {_sch_vscfg.get("lora_dir_scale", 0.75)} [{visual_style}]',
                )
            else:
                _log('WARNING', 'Stage 3.5', f'lora_dir LoRA file not found: {_lora_sf}')
        except Exception as _lora_dir_e:
            _log(
                'WARNING',
                'Stage 3.5',
                f'lora_dir LoRA load failed (continuing without): {_lora_dir_e}',
            )
    elif _FLUX_LORA_PATH:
        try:
            import safetensors.torch as _st_lora

            _lora_sf = os.path.join(_FLUX_LORA_PATH, 'pytorch_lora_weights.safetensors')
            _norm_lora = normalize_lora_keys(_st_lora.load_file(_lora_sf))
            gui_state._FLUX_PIPELINE_CACHE.load_lora_weights(_norm_lora)
            gui_state._FLUX_PIPELINE_CACHE.set_adapters(
                ['default_0'],
                adapter_weights=[_FLUX_LORA_SCALE],
            )
            _sch_lora_loaded = True
            _log('INFO', 'Stage 3.5', f'LoRA loaded: {_FLUX_LORA_PATH} @ scale {_FLUX_LORA_SCALE}')
        except Exception as _lora_e:
            _log('WARNING', 'Stage 3.5', f'LoRA load failed (continuing without): {_lora_e}')
    _log('INFO', 'Stage 3.5', f'Visual style: {visual_style} — {_sch_vscfg["claude_hint"]}')
    return _sch_lora_loaded


def load_controlnet(ctx):
    """Wrap the CUDA-resident FLUX in a ControlNet pipeline, or log why not.

    In: the stage context. Out: nothing — the pipeline is published on
    `gui_state._CN_PIPE_CACHE` (left `None` when it cannot load, so the anatomy
    shots fall back to base FLUX). ControlNet (6.6 GB) stays in CPU RAM and is
    swapped per shot; T5-XXL moves to CUDA whenever ControlNet is active,
    because mixed CPU/CUDA placement crashes inside `FluxControlNetPipeline`.
    """
    _log = ctx._log
    gui_state._CN_PIPE_CACHE = None
    try:
        from zyg_workflows import controlnet_service as _cns_loader

        _cn_loaded = _cns_loader.setup(
            gui_state._FLUX_PIPELINE_CACHE,
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
        if _cn_loaded is not None:
            gui_state._CN_PIPE_CACHE = _cn_loaded
            # Always move T5-XXL to CUDA when ControlNet is active.
            # Mixed CPU/CUDA device placement causes mat-mul device
            # mismatches and "cpu tensor from cuda generator" crashes
            # inside FluxControlNetPipeline. Peak VRAM with T5 on CUDA:
            # ~32 GB (FLUX 23 + ControlNet 6.6 + T5 9) — fits on 48 GB.
            _cns_loader.prepare_flux_for_controlnet(
                gui_state._FLUX_PIPELINE_CACHE,
                _cn_loaded,
                log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
            )
            _log(
                'INFO',
                'Stage 3.5',
                'ControlNet pose conditioning loaded ✓ (anatomy shots will use FluxControlNetPipeline)',
            )
        else:
            _log('WARNING', 'Stage 3.5', 'ControlNet unavailable — anatomy shots use base FLUX')
    except BaseException as _cn_load_e:
        gui_state._CN_PIPE_CACHE = None
        _log('WARNING', 'Stage 3.5', f'ControlNet load failed: {_cn_load_e}')

    _t5_loc = 'CUDA' if gui_state._CN_PIPE_CACHE is not None else 'CPU RAM'
    _log(
        'INFO',
        'Stage 3.5',
        f'FLUX on VRAM (~23 GB / 48 GB, ControlNet in CPU RAM, T5-XXL on {_t5_loc}) — '
        f'fast inference '
        f'({"ControlNet active" if gui_state._CN_PIPE_CACHE is not None else "base FLUX only"})',
    )


def release_for_worker(sch_backend, log, pipe, cn_pipe):
    """Release the GPU lock and the cached weights on behalf of the FluxWorker.

    In: the stills backend module, the stage's `_log`, and the pipes the worker
    took ownership of. Out: nothing. `claim_flux_worker` hands this to
    `complete_start` as a `functools.partial` over all four arguments, so the
    worker's idle thread still calls it with none — `release_scholarly_gpu_lock`
    only moves the weights to CPU, so the cache clear is what lets Python
    collect the ~32 GB it would otherwise keep pinned in RAM.
    """
    try:
        from zyg_workflows import controlnet_service as _cns_fw_td
    except ImportError:
        _cns_fw_td = None
    sch_backend.release_scholarly_gpu_lock(
        '_flux_worker',
        pipe=pipe,
        cn_pipe=cn_pipe,
        cn_service=_cns_fw_td,
        log_fn=lambda m: log('INFO', 'Stage 3.5', m),
    )
    # Clear module-level cache refs so Python GC can collect
    # the model weights from CPU RAM (release_scholarly_gpu_lock
    # moves to CPU but doesn't clear _FLUX_PIPELINE_CACHE, which
    # keeps ~32 GB of weights pinned in RAM indefinitely).
    _deep_unload_flux_pipeline_cache(
        log_fn=lambda m: log('INFO', 'Stage 3.5', m),
    )


def claim_flux_worker(fs, ctx, flux_pipe, sch_fw_active):
    """Hand FLUX to the persistent worker when we loaded it, then take a slot.

    In: the loop state (for the `_sch_fw_active` mirror the skeleton reads), the
    stage context, the pipe just loaded or found cached, and whether the worker
    was already active. Out: `(flux_pipe, sch_fw_active)` — the pipe to render
    with (the worker's, once it owns one) and the updated flag. The GPU lock
    moves with the ownership: `ctx._sch_gpu_lock_held` goes False here so the
    skeleton's `finally` does not release a lock the worker now holds.
    """
    _fw_claimed_start = ctx._fw_claimed_start
    _log = ctx._log
    _sch_backend = ctx._sch_backend
    _sch_fw = ctx._sch_fw
    if _sch_fw is None:
        return flux_pipe, sch_fw_active
    if _fw_claimed_start and not sch_fw_active and flux_pipe is not None:
        # We loaded FLUX — hand ownership to the persistent worker
        _fw_pipe_ref = flux_pipe
        _fw_cn_ref = gui_state._CN_PIPE_CACHE
        _sch_fw.complete_start(
            _fw_pipe_ref,
            _fw_cn_ref,
            functools.partial(release_for_worker, _sch_backend, _log, _fw_pipe_ref, _fw_cn_ref),
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
        sch_fw_active = fs._sch_fw_active = True
        ctx._sch_gpu_lock_held = False  # lock transferred to worker
        _log('INFO', 'Stage 3.5', '[FluxWorker] FLUX ownership transferred — GPU lock held by worker')
    if sch_fw_active:
        # Acquire exclusive serial access to the shared FLUX pipe
        flux_pipe, _ = _sch_fw.acquire_pipe_slot(timeout=600.0)
    return flux_pipe, sch_fw_active


def resolve_controlnet_pipe(ctx, sch_fw_active):
    """Pick the ControlNet pipe the slot loop will condition anatomy shots with.

    In: the stage context and whether the FluxWorker owns the pipes. Out:
    `(cns, cn_pipe)` — the `controlnet_service` module (for `get_pose_image()`)
    and the pipeline, or `(None, None)` when there is no ControlNet. The pipe
    comes from the worker when it owns one, else from `gui_state._CN_PIPE_CACHE`
    — which the fresh-load block filled and a cache-hit run carries over.
    """
    _debug = ctx._debug
    _log = ctx._log
    _sch_fw = ctx._sch_fw
    _cns = None
    _cn_pipe = _sch_fw.get_cn_pipe() if sch_fw_active and _sch_fw is not None else gui_state._CN_PIPE_CACHE
    if _cn_pipe is not None:
        try:
            from zyg_workflows import controlnet_service as _cns

            _log(
                'INFO',
                'Stage 3.5',
                'ControlNet pose conditioning active — anatomy shots guided by pose skeleton',
            )
        except ImportError:
            _cn_pipe = None
            _log('WARNING', 'Stage 3.5', 'controlnet_service not importable — ControlNet disabled')
    else:
        _debug('Stage 3.5', 'ControlNet not available — using base FLUX for all shots')
    _debug('Stage 3.5', f'ControlNet pipe ready: {_cn_pipe is not None}')
    return _cns, _cn_pipe
