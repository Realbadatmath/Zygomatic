# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rendering the preview slots: _render_char_preview_slots.

Moved verbatim out of the old single-file char_state_service.py (lines 2544-2880);
its stages live in render_slots_stages.py since the 2026-10 function-size split.
"""

import os

from zyg_workflows.runtime import (
    _char_gen_jobs,
)
from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _normalize_char_model_family,
)
from zyg_workflows.char_state_service.preview_provenance import (
    _char_sync_preview_legacy_aliases,
    _preview_restyle_name,
)
from zyg_workflows.char_state_service.preview_slots import (
    _build_char_preview_slots,
)
from zyg_workflows.char_state_service.preview_reference import (
    _have_usable_char_preview,
    _preview_backend_tier,
)
from zyg_workflows.char_state_service import render_slots_stages as _stages


def _render_char_preview_slots(
    char_id: str,
    params: dict,
    info: dict,
    log_fn=None,
    force: bool = False,
    model_family: str | None = None,
) -> dict:
    """Stage 1d previews: LoRA locked txt2img first, InstantID for photos, img2img last."""
    from zyg_workflows import comfy_generation_service as _cgs_prev

    _log = log_fn or (lambda m: None)
    mf = _normalize_char_model_family(model_family, params, info)
    info = dict(info or {})
    info['char_id'] = char_id
    _job = _char_gen_jobs.get(char_id) or {}
    info.setdefault('render_mode', _job.get('render_mode'))
    dataset_dir = info.get('dataset_dir') or str(_CHARS_DATASETS / char_id)
    os.makedirs(dataset_dir, exist_ok=True)

    if not force and _have_usable_char_preview(dataset_dir, mf, params, info):
        _log(f'Preview already exists for {char_id[:8]} — skipping')
        return _stages.early_preview_result(mf, skipped=True, error=None, warning='', quality_ok=True)

    if not _cgs_prev.is_available():
        return _stages.early_preview_result(
            mf,
            skipped=False,
            error='comfy_unavailable',
            warning='ComfyUI unavailable',
            quality_ok=False,
        )

    _stages.load_bible_package(char_id, info)
    state = _stages.preview_conditioning_state(char_id, params, info, dataset_dir, mf, _job)
    _pkg = state['pkg']
    _has_lora = state['has_lora']
    _blender_ds = state['blender_ds']

    _stages.wait_for_preview_vram(_log)

    _log(f'Generating character preview images (ComfyUI, {state["label"]})…')
    _slots = _build_char_preview_slots(params, info, model_family=mf)
    rendered: list[str] = []
    backends: list[str] = []
    slot_meta: dict[str, dict] = {}
    last_error: str | None = None
    _seed_round = int(os.environ.get('ZYG_PREVIEW_SEED_ROUND', '0') or '0')
    _base_seed = int(abs(hash(char_id)) % 2_000_000_000) + _seed_round * 1_000_003
    _front_slot = _slots[0][0] if _slots else ''
    _render_lc = _stages.resolve_render_style(mf, params, info)
    # 2026-07-31: the restyle profile name that actually applies to this render, for
    # the provenance sidecars below ('' when the photoreal FLUX twin leg is rendering).
    _slot_restyle = _preview_restyle_name(mf, params, info)

    _run = _stages.SlotRun(
        char_id=char_id,
        dataset_dir=dataset_dir,
        pkg=_pkg,
        params=params,
        info=info,
        mf=mf,
        blender_ds=_blender_ds,
        front_slot=_front_slot,
        render_lc=_render_lc,
        slot_restyle=_slot_restyle,
        base_seed=_base_seed,
        log_fn=_log,
    )
    for _idx, _slot in enumerate(_slots):
        _err = _stages.render_slot(
            _run,
            _cgs_prev,
            idx=_idx,
            slot=_slot,
            rendered=rendered,
            backends=backends,
            slot_meta=slot_meta,
        )
        if _err:
            last_error = _err

    if rendered:
        _char_sync_preview_legacy_aliases(dataset_dir, mf, params, info)

    _stages.register_front_reference(char_id, rendered, _front_slot, slot_meta, _log)

    preview_quality_ok, _warnings = _stages.preview_warnings(
        mf,
        params,
        info,
        rendered=rendered,
        slot_meta=slot_meta,
        front_slot=_front_slot,
        job=_job,
    )

    return {
        'rendered': rendered,
        'skipped': False,
        'lora_used': _has_lora and any(_preview_backend_tier(b) == 'locked' for b in backends),
        'error': last_error if not rendered else None,
        'backend': mf,
        'backends': backends,
        'slot_meta': slot_meta,
        'preview_quality_ok': preview_quality_ok,
        'preview_warning': '; '.join(_warnings),
    }
