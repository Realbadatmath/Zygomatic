# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage helpers of the in-process FLUX character-preview render.

Extracted on 2026-10-09 from ``render_images._render_char_preview_images``, which was
328 lines long and therefore untestable.  Every helper keeps the original log lines,
side effects and their order; the orchestrator in ``render_images`` is now the stage
sequence and nothing else.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from zyg_workflows import gui_state
from zyg_workflows import paths
from zyg_workflows import runtime as _runtime
from zyg_workflows.pipeline_config import (
    _PREVIEW_LORA_WAIT_S,
)
from zyg_workflows.char_state_service._common import (
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_preview_slot_lora_path,
)
from zyg_workflows.char_state_service.preview_provenance import (
    _preview_restyle_name,
    _write_preview_provenance,
)
from zyg_workflows.char_state_service.preview_reference import (
    _pick_char_preview_reference,
)


@dataclass
class _PreviewRun:
    """The shared inputs of one in-process FLUX preview render.

    ``params`` is re-bound by the orchestrator once the character bible's
    auto-defaults have been applied, which is why this record is mutable.
    """

    char_id: str
    params: dict
    info: dict
    dataset_dir: str
    trigger: str
    model_family: str
    log: Callable[[str], None]


def _lora_unresolved_result(model_family: str) -> dict:
    """The fail-closed result dict returned when no trained adapter resolved.

    A preview rendered on the bare base model is a stranger presented as the
    character, so the render is refused instead (the c3345deb5bde defect).
    """
    return {'rendered': [], 'skipped': False, 'lora_used': False, 'error': 'lora_unresolved', 'backend': model_family}


def _preview_provenance_extra(model_family: str, char_id: str, lora_used: bool) -> dict:
    """The ``extra`` block of the provenance sidecar written beside each preview PNG."""
    return {
        'renderer': 'diffusers_inprocess',
        'render_family': model_family,
        'tier': 'locked' if lora_used else 'other',
        'lora_scale': 0.85 if lora_used else None,
        'char_id': char_id,
    }


def _ensure_bible_package(char_id: str, info: dict, stage: str) -> None:
    """Attach the character bible package to ``info['package']`` when missing.

    *stage* only names the caller in the debug line. Never raises: a preview is
    still renderable without the bible, it just loses the descriptor set.
    """
    if info.get('package'):
        return
    try:
        from zyg_workflows import character_bible_service as _cbs_pkg_fl

        _pkg_fl = _cbs_pkg_fl.load(char_id)
        if _pkg_fl:
            info['package'] = _pkg_fl
    except Exception as _exc:
        _zyg_log.debug('bible package not loaded for the %s: %s', stage, _exc)


def _apply_bible_auto_defaults(char_id: str, params: dict) -> dict:
    """Return *params* with the bible's auto-defaults applied, or unchanged on failure.

    ``apply_auto_defaults`` guarantees a complete descriptor set even for a
    brand-new bible, so quality_suffix / negative_prompt are always available.
    """
    try:
        from zyg_workflows import character_bible_service as _cbs_ad

        return _cbs_ad.apply_auto_defaults(params, seed_key=char_id)
    except Exception as _exc:
        _zyg_log.debug('auto-defaults not applied to the params: %s', _exc)
        return params


def _comfy_flux_fast_path(run: _PreviewRun, *, comfy_render, log_fn, force: bool) -> dict | None:
    """Try the ComfyUI FLUX preview when the bible asks for InstantID / face detail.

    Returns the ComfyUI result dict when it produced — or deliberately skipped —
    images, else ``None`` so the caller falls back to the in-process renderer.
    *comfy_render* is the slot renderer to call (passed in so the orchestrator's
    own module attribute stays the single, patchable entry point).
    """
    _ensure_bible_package(run.char_id, run.info, 'flux preview')
    _cond_fl = (run.info.get('package') or {}).get('conditioning') or {}
    if not bool(_cond_fl.get('instantid_enabled') or _cond_fl.get('face_detail_pass')):
        return None
    try:
        from zyg_workflows import comfy_generation_service as _cgs_fl_chk

        if _cgs_fl_chk.is_available() and _pick_char_preview_reference(run.dataset_dir, run.info):
            _comfy_res = comfy_render(
                run.char_id,
                run.params,
                run.info,
                log_fn=log_fn,
                force=force,
                model_family='flux',
            )
            if _comfy_res.get('rendered') or _comfy_res.get('skipped'):
                return _comfy_res
            run.log(
                f'ComfyUI FLUX preview did not produce images ({_comfy_res.get("error")}) '
                '— falling back to in-process FLUX',
            )
    except Exception as _cfx:
        run.log(f'ComfyUI FLUX preview unavailable ({_cfx}) — using in-process FLUX')
    return None


def _wait_for_preview_lora(char_id: str, model_family: str, wait_for_lora_s: int | None) -> tuple[str | None, str]:
    """Wait for an in-flight LoRA training job so the preview uses the trained adapter.

    Polls the trainer every 2 s until it reports a readable adapter file, fails,
    finishes without one, or ``wait_for_lora_s`` (default ``_PREVIEW_LORA_WAIT_S``)
    elapses. Returns ``(lora_path_or_None, exit_reason)`` where the reason is one of
    ``resolved``, ``trainer_failed``, ``trainer_done_no_path``, ``wait_timeout`` or
    ``trainer_error: <message>``.
    """
    lora_path = None
    exit_reason = 'resolved'
    try:
        from zyg_workflows import lora_trainer_service as _lts_pr

        trainer = _lts_pr.get_trainer()
        deadline = time.time() + (wait_for_lora_s if wait_for_lora_s is not None else _PREVIEW_LORA_WAIT_S)
        while True:
            st = trainer.get_status(char_id, model_family=model_family)
            lora_path = st.get('lora_path') or trainer.get_lora_path(char_id, model_family=model_family)
            if lora_path and os.path.isfile(lora_path):
                break
            if st.get('failed') or st.get('done'):
                exit_reason = 'trainer_failed' if st.get('failed') else 'trainer_done_no_path'
                break
            if time.time() >= deadline:
                exit_reason = 'wait_timeout'
                break
            time.sleep(2)
    except Exception as _lwe:
        exit_reason = f'trainer_error: {str(_lwe)[:80]}'
    return lora_path, exit_reason


def _resolve_lora_from_bible(info: dict, char_id: str, dataset_dir: str, log) -> tuple[str | None, str | None]:
    """Resolve the adapter from the bible / on-disk layout the trainer knows nothing about.

    2026-07-31: the trainer wait exits on failed/done/timeout with no path at all, so
    exhaust the honest sources before giving up. Returns
    ``(path, 'resolved_from_bible')`` on success and ``(None, None)`` otherwise.
    """
    try:
        _cond_lp = (info.get('package') or {}).get('conditioning') or {}
        _alt_lp = _char_preview_slot_lora_path(_cond_lp, 'flux', char_id, dataset_dir)
        if _alt_lp and os.path.isfile(_alt_lp):
            log(f'Trainer had no adapter path — resolved from bible/disk: {os.path.basename(_alt_lp)}')
            return _alt_lp, 'resolved_from_bible'
    except Exception as _exc:
        _zyg_log.debug('adapter path not resolved from the bible: %s', _exc)
    return None, None


def _resolve_flux_model_path(log) -> tuple[str, bool]:
    """Pick the FLUX checkpoint directory for a preview render.

    Prefers flux1-dev when it is on disk; 2026-08-09: under a flux licence pause only
    the Apache-2.0 schnell weights may load, so the pause downgrades the choice.
    Returns ``(model_dir, use_dev)``.
    """
    _flux_dev_path = str(paths.ZYG_FLUX_ROOT / 'flux1-dev')
    _flux_schnell = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
    use_dev = os.path.isdir(_flux_dev_path)
    try:
        from zyg_workflows import licence_provenance as _lp_pr

        if _lp_pr.flux_paused() and use_dev:
            log('[licence] flux1-dev preview blocked (pause) — using schnell')
            use_dev = False
    except ImportError as _exc:
        _zyg_log.debug('licence pause check unavailable, keeping the chosen flux model: %s', _exc)
    return (_flux_dev_path if use_dev else _flux_schnell), use_dev


def _wait_for_preview_vram(use_dev: bool, log) -> None:
    """Evict ComfyUI and wait for enough free VRAM before FLUX loads.

    Advisory only: a tight-VRAM timeout is logged and the render proceeds anyway.
    """
    try:
        from zyg_workflows import _comfy_client as _cc_prev

        ok_vg, free_gb = _cc_prev.wait_for_free_vram_gb(
            min_free_gb=36.0 if use_dev else 22.0,
            timeout_s=300,
            poll_s=5.0,
            try_evict=True,
            log_fn=log,
        )
        if not ok_vg:
            log(f'VRAM tight ({free_gb:.1f} GB free) — proceeding anyway')
    except Exception as _exc:
        _zyg_log.debug('vram wait before the flux preview skipped: %s', _exc)


def _release_flux_pipeline(note: str, log=None) -> None:
    """Drop the cached FLUX pipeline and free its VRAM; never raises.

    *note* names the call site in the debug line taken when the teardown itself
    fails. When *log* is given, the operator-facing "VRAM freed" line is emitted.
    """
    try:
        gui_state._FLUX_DEV_PIPELINE_CACHE = None
        import gc as _gc_pr
        import torch as _torch_pr

        _gc_pr.collect()
        _torch_pr.cuda.empty_cache()
        if log is not None:
            log('FLUX unloaded, VRAM freed')
    except Exception as _exc:
        _zyg_log.debug('flux pipeline unload %s: %s', note, _exc)


def _unload_preview_lora() -> None:
    """Detach the preview adapter from the cached pipeline; never raises."""
    try:
        gui_state._FLUX_DEV_PIPELINE_CACHE.unload_lora_weights()
    except Exception as _exc:
        _zyg_log.debug('lora unload skipped: %s', _exc)


def _attach_preview_lora(lora_path: str | None, model_family: str, log) -> tuple[bool, dict | None]:
    """Load the trained adapter onto the cached pipeline at weight 0.85.

    Returns ``(lora_used, early_result)``. *early_result* is a result dict the caller
    must return immediately — the adapter failed to load or vanished, and rendering
    on bare FLUX would hand back a base-model stranger as "the character" (the
    2026-07-09 cartoon-preview audit). It is ``None`` when the render may proceed.
    """
    if lora_path and os.path.isfile(lora_path):
        try:
            gui_state._FLUX_DEV_PIPELINE_CACHE.load_lora_weights(lora_path, adapter_name='char_prev')
            gui_state._FLUX_DEV_PIPELINE_CACHE.set_adapters(['char_prev'], adapter_weights=[0.85])
            log(f'Preview using trained LoRA: {os.path.basename(lora_path)}')
            return True, None
        except Exception as _le:
            log(f'ERROR: trained-LoRA load failed ({_le}) — aborting preview')
            _release_flux_pipeline('after the lora failure skipped')
            return False, {
                'rendered': [],
                'skipped': False,
                'lora_used': False,
                'error': f'lora_load_failed: {str(_le)[:160]}',
                'backend': model_family,
            }
    if _preview_env_on('ZYG_PREVIEW_REQUIRE_LORA'):
        # 2026-07-31: belt and braces. The pre-flight guard in the orchestrator already
        # fails closed, but keep this branch so no future edit can make an unresolved
        # adapter fall through to a bare-FLUX render again.
        log(f'ERROR: adapter vanished before load ({lora_path!r}) — aborting preview')
        _release_flux_pipeline('skipped')
        return False, _lora_unresolved_result(model_family)
    return False, None


def _render_preview_slots(
    run: _PreviewRun,
    slots,
    *,
    use_dev: bool,
    lora_used: bool,
    lora_path: str | None,
) -> tuple[list[str], str | None]:
    """Render every in-process FLUX slot of *slots* into ``run.dataset_dir``.

    Each slot row is ``(slot, prompt, width, height[, model_family])``; SDXL slots are
    Comfy-only and skipped. Per slot this writes ``<slot>.png``, its ``.txt`` prompt
    sidecar and the provenance sidecar (2026-07-31 contract D), and records a
    benchmark sample. Returns ``(rendered_paths, last_error)``; a failing slot is
    logged and does not abort the others.
    """
    rendered: list[str] = []
    last_error: str | None = None
    for _slot_row in slots:
        _pslot, _pprompt, _pw, _ph = _slot_row[:4]
        _slot_mf = _slot_row[4] if len(_slot_row) > 4 else run.model_family
        if _slot_mf == 'sdxl':
            run.log(f'Skipping in-process FLUX for SDXL slot {_pslot} (Comfy-only)')
            continue
        try:
            _t0 = time.monotonic()
            _pimg = gui_state._FLUX_DEV_PIPELINE_CACHE(
                prompt=_pprompt,
                num_inference_steps=28 if use_dev else 8,
                width=_pw,
                height=_ph,
                # 2.8: previews must render in the same photoreal guidance
                # regime as the pipeline; 3.5 is FLUX's plastic-skin zone.
                guidance_scale=2.8 if use_dev else 0.0,
            ).images[0]
            try:
                _runtime.bm_record('flux_dev' if use_dev else 'flux_schnell', time.monotonic() - _t0, count=1)
            except Exception as _exc:
                _zyg_log.debug('benchmark record skipped: %s', _exc)
            _out_png = os.path.join(run.dataset_dir, f'{_pslot}.png')
            _pimg.save(_out_png)
            with open(os.path.splitext(_out_png)[0] + '.txt', 'w', encoding='utf-8') as _t:
                _t.write(_pprompt.strip() + '\n')
            _write_preview_provenance(
                _out_png,
                slot=_pslot,
                model_family=_slot_mf,
                lora_used=bool(lora_used),
                lora_path=lora_path if lora_used else None,
                trigger_token=str(run.trigger or ''),
                restyle=_preview_restyle_name(run.model_family, run.params, run.info),
                backend=('flux_dev_inprocess' if use_dev else 'flux_schnell_inprocess'),
                extra=_preview_provenance_extra(run.model_family, run.char_id, lora_used),
                log_fn=run.log,
            )
            rendered.append(_out_png)
            run.log(f'Saved {_pslot}.png')
        except Exception as _pe:
            last_error = str(_pe)[:200]
            run.log(f'Preview slot {_pslot} failed: {_pe}')
    return rendered, last_error
