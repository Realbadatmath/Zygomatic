# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Preview render entry points: comfy, sdxl and the dispatcher.

Moved verbatim out of the old single-file char_state_service.py (lines 2882-3247).
"""

import os
from zyg_workflows import gui_state
from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
    _preview_env_on,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _normalize_char_model_family,
)
from zyg_workflows.char_state_service.preview_provenance import (
    _char_sync_preview_legacy_aliases,
)
from zyg_workflows.char_state_service.preview_slots import (
    _build_char_preview_slots,
)
from zyg_workflows.char_state_service.preview_reference import (
    _have_usable_char_preview,
)
from zyg_workflows.char_state_service.render_images_stages import (
    _PreviewRun,
    _apply_bible_auto_defaults,
    _attach_preview_lora,
    _comfy_flux_fast_path,
    _ensure_bible_package,
    _lora_unresolved_result,
    _release_flux_pipeline,
    _render_preview_slots,
    _resolve_flux_model_path,
    _resolve_lora_from_bible,
    _unload_preview_lora,
    _wait_for_preview_lora,
    _wait_for_preview_vram,
)
from zyg_workflows.char_state_service.render_slots import (
    _render_char_preview_slots,
)


def _render_char_preview_images_comfy(
    char_id: str,
    params: dict,
    info: dict,
    log_fn=None,
    force: bool = False,
    model_family: str = 'flux',
) -> dict:
    """Stage 1d previews via ComfyUI (FLUX or SDXL unified slot renderer)."""
    return _render_char_preview_slots(
        char_id,
        params,
        info,
        log_fn=log_fn,
        force=force,
        model_family=model_family,
    )


def _render_char_preview_images_sdxl(
    char_id: str,
    params: dict,
    info: dict,
    log_fn=None,
    force: bool = False,
) -> dict:
    """Stage 1d SDXL previews via ComfyUI (aligned SDXL 1.0 base + LoRA locked)."""
    return _render_char_preview_slots(
        char_id,
        params,
        info,
        log_fn=log_fn,
        force=force,
        model_family='sdxl',
    )


def _render_char_preview_images(
    char_id: str,
    params: dict,
    info: dict,
    log_fn=None,
    force: bool = False,
    wait_for_lora_s: int | None = None,
    model_family: str | None = None,
) -> dict:
    """Generate preview_flux_front.png + preview_flux_face.png for *char_id*.

    Idempotent: skips when both files already exist (unless force=True). Calls
    ComfyUI /free and waits for sufficient VRAM before loading FLUX. If a LoRA
    training job is still in-flight for this char, waits up to wait_for_lora_s
    seconds for it to finish so the preview uses the trained adapter.

    When ``model_family`` is ``sdxl``, renders via ComfyUI SDXL 1.0 base (aligned with LoRA train).

    Returns ``{'rendered': [...], 'skipped': bool, 'lora_used': bool, 'error': str|None}``.
    """
    info = dict(info or {})
    info['char_id'] = char_id
    mf = _normalize_char_model_family(model_family, params, info)
    if mf == 'sdxl':
        return _render_char_preview_images_sdxl(
            char_id,
            params,
            info,
            log_fn=log_fn,
            force=force,
        )

    pass  # (global stmt removed: names moved to gui_state)
    _log = log_fn or (lambda m: None)
    dataset_dir = info.get('dataset_dir') or str(_CHARS_DATASETS / char_id)
    trigger = info.get('trigger_token') or f'ZYG_CHAR_{char_id[:6].upper()}'
    run = _PreviewRun(
        char_id=char_id,
        params=params,
        info=info,
        dataset_dir=dataset_dir,
        trigger=trigger,
        model_family=mf,
        log=_log,
    )

    _comfy_res = _comfy_flux_fast_path(
        run,
        comfy_render=_render_char_preview_images_comfy,
        log_fn=log_fn,
        force=force,
    )
    if _comfy_res is not None:
        return _comfy_res

    if not force and _have_usable_char_preview(dataset_dir, mf, params, info):
        _log(f'Preview already exists for {char_id[:8]} — skipping')
        return {'rendered': [], 'skipped': True, 'lora_used': False, 'error': None}

    # Ensure info carries the character bible so quality_suffix / negative_prompt
    # are available below.  apply_auto_defaults on the params dict guarantees a
    # complete descriptor set even if the bible is brand-new.
    _ensure_bible_package(char_id, info, 'flux render')
    params = _apply_bible_auto_defaults(char_id, params)
    run.params = params

    # ── Wait for LoRA if a training job is in-flight, then exhaust the honest
    # sources the trainer does not know about (bible flux_lora_path, on-disk layout).
    lora_path, _lora_wait_exit = _wait_for_preview_lora(char_id, mf, wait_for_lora_s)
    if not (lora_path and os.path.isfile(lora_path)):
        _alt_lp, _alt_exit = _resolve_lora_from_bible(info, char_id, dataset_dir, _log)
        if _alt_lp:
            lora_path, _lora_wait_exit = _alt_lp, _alt_exit

    # ── NEVER render a preview on the base model ─────────────────────────────
    # 2026-07-31: the guard below used to be `if lora_path and os.path.isfile(...)`
    # with NO else, so an unresolved adapter simply SKIPPED the adapter load and
    # generated on bare FLUX — a base-model stranger written to
    # preview_flux_front.png (the canonical library portrait) and returned with
    # error=None.  That is the c3345deb5bde defect.  Fail CLOSED, by design, and
    # before any model is loaded.
    if not (lora_path and os.path.isfile(lora_path)) and _preview_env_on('ZYG_PREVIEW_REQUIRE_LORA'):
        _log(
            f'ERROR: no trained LoRA resolved for {char_id[:8]} ({_lora_wait_exit}) — '
            'refusing to render a base-model preview',
        )
        return _lora_unresolved_result(mf)

    try:
        from diffusers import FluxPipeline as _FP_pr
        import torch as _torch_pr

        _flux_path_pr, _use_dev_pr = _resolve_flux_model_path(_log)
        if not (os.path.isdir(_flux_path_pr) and os.path.isdir(dataset_dir)):
            return {
                'rendered': [],
                'skipped': False,
                'lora_used': False,
                'error': f'missing model ({_flux_path_pr}) or dataset ({dataset_dir})',
            }

        _wait_for_preview_vram(_use_dev_pr, _log)

        _log('Generating FLUX character preview images…')
        if gui_state._FLUX_DEV_PIPELINE_CACHE is None:
            gui_state._FLUX_DEV_PIPELINE_CACHE = _FP_pr.from_pretrained(
                _flux_path_pr, torch_dtype=_torch_pr.bfloat16
            ).to('cuda')
            gui_state._FLUX_DEV_PIPELINE_CACHE.vae.enable_tiling()

        _slots = _build_char_preview_slots(params, info, model_family=mf)

        lora_used, _early = _attach_preview_lora(lora_path, mf, _log)
        if _early is not None:
            return _early

        rendered, last_error = _render_preview_slots(
            run,
            _slots,
            use_dev=_use_dev_pr,
            lora_used=lora_used,
            lora_path=lora_path,
        )

        _unload_preview_lora()
        _release_flux_pipeline('skipped', log=_log)

        if rendered:
            _char_sync_preview_legacy_aliases(dataset_dir, mf, params, info)

        return {
            'rendered': rendered,
            'skipped': False,
            'lora_used': lora_used,
            'error': last_error if not rendered else None,
            'backend': mf,
        }

    except Exception as exc:
        if gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
            _release_flux_pipeline('after the error skipped')
        return {'rendered': [], 'skipped': False, 'lora_used': False, 'error': str(exc)[:200], 'backend': mf}
