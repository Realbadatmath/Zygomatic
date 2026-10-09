# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""generate_still - the ComfyUI still execution entry point (original lines 40-42, 1965-2238)."""

from __future__ import annotations

import os
from typing import Any, Callable
from zyg_workflows import comfy_generation_service_steps as _steps
from zyg_workflows.comfy_generation_service.constants import _bible, _comfy, _cqa, _log_default, _neg_log
from zyg_workflows.comfy_generation_service.backend import (
    _clear_vram_between_slots_enabled,
    clear_vram_between_slots,
    is_available,
)
from zyg_workflows.comfy_generation_service.style import _normalize_model_family
from zyg_workflows.comfy_generation_service.workflows import _drift_threshold_for_package, _stage_style_lora


# P-06: generate_still logs the fully composed negative ONCE per process at
# DEBUG so a run's log shows what the sampler was actually pushed away from.
_NEG_LOGGED_ONCE = False


def _post_save(
    out_path: str,
    char_id: str,
    full_prompt: str,
    seed: int,
    log_fn: Callable[[str], None],
    character_package: dict[str, Any] | None = None,
) -> tuple[bool, float]:
    """Run consistency QA after save. Returns (drift_passed, drift_score)."""
    passed, score = True, 1.0
    if char_id and _cqa:
        _cqa.ensure_reference_from_bible(char_id, log_fn=log_fn)
        thr = _drift_threshold_for_package(character_package)
        _res = _cqa.check_drift(
            out_path,
            char_id,
            threshold=thr,
            log_fn=log_fn,
        )
        passed, score = _res[0], _res[1]
        # 2026-07-31: check_drift used to return a hardcoded (True, 1.0) — a
        # guaranteed PASS — when the character had no cached reference embedding.
        # It now reports 'unknown' with a -1.0 sentinel instead. That is NOT a
        # drift failure, and must not be logged or recorded as one: an unverified
        # frame is unverified, and a retry cannot fix a missing reference.
        _status = getattr(_res, 'status', 'ok' if passed else 'drift')
        if _status == 'unknown':
            log_fn('ComfyGen: identity UNVERIFIED (no reference embedding) — not a drift failure')
            passed, score = True, None
        elif not passed:
            log_fn(f'ComfyGen: identity drift (score={score:.3f}) — caller may retry')
        if _bible:
            _bible.record_scene_shot(char_id, os.path.basename(out_path), out_path, full_prompt, seed, score)
    return passed, (1.0 if score is None else score)


def generate_still(
    out_path: str,
    scene_prompt: str,
    *,
    width: int = 1280,
    height: int = 720,
    steps: int = 20,
    cfg: float = 3.5,
    seed: int = 42,
    denoise: float | None = None,
    character_package: dict[str, Any] | None = None,
    char_id: str = '',
    init_image: str | None = None,
    reference_image: str | None = None,
    model_family: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    force_workflow: str | None = None,
    blender_dataset: bool = False,
    skip_qa: bool = False,
    studio_preview: bool = False,
    extra_negative: str = '',
    style_lora_path: str | None = None,
    style_lora_scale: float = 0.75,
    force_unet: str | None = None,
    flux_guidance: float | None = None,
    prompt_finalized: bool = False,
    enable_face_detailer: bool | None = None,
    cfg_start_frac: float | None = None,
    shot_type: str | None = None,
    scene_emotion: str | None = None,
    require_drift_pass: bool = False,
    pose_image: str | None = None,
    clear_vram_after: bool | None = None,
    qwen_max_mp: float | None = None,
    solo_subject: bool = True,
    human_subject: bool = True,
    medusa_base_lora: dict | None = None,
) -> tuple[bool, str]:
    """Generate one still via ComfyUI. Returns (success, backend_label).

    qwen_max_mp overrides ZYG_QWEN_EDIT_MAX_MP for this call only — lifted for
    face close-ups/relights that need more resolution than the 1MP default.

    solo_subject=False drops the bible's single-subject ban ("multiple people,
    crowd, group shot, …") from the negative — for scene stills that are not
    about one locked character (P-06; documentary Stage 3.5 passes
    ``solo_subject=bool(package)``).

    medusa_base_lora is a MEDUSA-ONLY model-level adapter, as
    {'model_id','path','family','scale'} from medusa_model_lora.resolve_active().
    It defaults to None and NOTHING in this tree passes it except the Medusa
    worker, which obtains it from a thread-local (see medusa_model_lora's
    isolation contract). When present it selects <family>_medusa_base — a graph
    carrying a second LoraLoader at node 14, ahead of the character LoRA at
    node 13 — so a base adapter can never enter a storyteller/documentary/
    creature render, whose graphs have no node 14 to put it in.

    human_subject=False drops the person-only anatomy clauses ("extra fingers",
    "three fingers", "mutated hands", "claw hands", the earring/jewelry pair)
    from the negative. Pass it for creatures, animals and props: those clauses
    guard human hands, and on a subject whose real anatomy is a three-toed foot
    or a stubby four-finger paw they argue against the body plan at any cfg > 1
    (2026-08-26, Zygo AI Pufferball — rendered limbless with them live).
    """
    global _NEG_LOGGED_ONCE
    log = log_fn or _log_default
    _do_clear_after = _clear_vram_between_slots_enabled(clear_vram_after)

    def _maybe_clear_vram(tag: str) -> None:
        if _do_clear_after:
            clear_vram_between_slots(log_fn=log, label=tag)

    if not is_available():
        return False, 'unavailable'

    if _steps.flux_licence_paused(_normalize_model_family(model_family), log):
        return False, 'flux_licence_paused'

    if not reference_image and character_package and _bible and not prompt_finalized:
        reference_image = _bible.get_master_reference(character_package)

    full_prompt, full_negative, character_package, mf = _steps.compose_prompts(
        scene_prompt,
        character_package,
        model_family=model_family,
        prompt_finalized=prompt_finalized,
        studio_preview=studio_preview,
        solo_subject=solo_subject,
        human_subject=human_subject,
        extra_negative=extra_negative,
    )
    # P-06: the negative is final for node 21 here (the qwen-edit branch only
    # appends its fixed waxy-skin term later). Log it once per process at DEBUG
    # so a run's log shows the real string, not the [:120] excerpt per slot.
    if not _NEG_LOGGED_ONCE:
        _NEG_LOGGED_ONCE = True
        _neg_log.debug(
            'ComfyGen: composed negative (first render this process, family=%s, solo_subject=%s, %d chars): %s',
            mf,
            solo_subject,
            len(full_negative),
            full_negative,
        )
    unet, is_schnell, steps, cfg = _steps.resolve_unet_and_sampling(
        mf,
        character_package,
        force_unet=force_unet,
        force_workflow=force_workflow,
        steps=steps,
        cfg=cfg,
    )

    style_lora_name = _stage_style_lora(style_lora_path, log) if style_lora_path else None
    _medusa_base_name, _medusa_base_scale = _steps.stage_medusa_base_lora(medusa_base_lora, mf, log)
    lora_name = _steps.stage_character_lora_for_family(character_package, char_id, mf, log)

    # Blender training refs are greybox — never drive runtime img2img from them.
    _init_for_wf = init_image
    if blender_dataset and init_image and lora_name and mf == 'sdxl':
        _init_for_wf = None
        if force_workflow is None:
            force_workflow = 'sdxl_character_locked'

    workflow_name, _medusa_base_name = _steps.select_workflow(
        character_package,
        _init_for_wf,
        reference_image,
        lora_name,
        mf=mf,
        blender_dataset=blender_dataset,
        force_workflow=force_workflow,
        pose_image=pose_image,
        medusa_base_name=_medusa_base_name,
        medusa_base_scale=_medusa_base_scale,
        log=log,
    )

    # 2026-07-31: the *_character_locked graphs carry a hardcoded default lora_name
    # (the old shared 'character_lora.safetensors'). If staging produced nothing and
    # we still ran one of those graphs, Comfy would quietly load whatever stale file
    # sits at that name — i.e. some other character. Refuse instead: a failed render
    # is recoverable, a render of the wrong person shipped as this character is not.
    if (workflow_name or '').endswith('_character_locked') and not lora_name:
        log(
            f'ComfyGen: {workflow_name} selected but no character LoRA was staged — '
            'aborting rather than rendering with the workflow default',
        )
        return False, 'character_lora_not_staged'
    if style_lora_name and mf == 'flux' and workflow_name == 'flux_txt2img':
        workflow_name = 'flux_txt2img_style'
    width, height, _qwen_upscale_back = _steps.qwen_edit_resolution_cap(
        workflow_name,
        width,
        height,
        qwen_max_mp,
        log,
    )
    try:
        workflow = _comfy.load_workflow(workflow_name)
    except _comfy.ComfyUIError as exc:
        log(f'ComfyGen: workflow load failed — {exc}')
        return False, 'workflow_error'

    ctx = _steps.StillRenderCtx(
        log=log,
        comfy=_comfy,
        workflow=workflow,
        workflow_name=workflow_name,
        out_path=out_path,
        char_id=char_id,
        scene_prompt=scene_prompt,
        full_prompt=full_prompt,
        full_negative=full_negative,
        mf=mf,
        unet=unet,
        is_schnell=is_schnell,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
        denoise=denoise,
        flux_guidance=flux_guidance,
        cfg_start_frac=cfg_start_frac,
        studio_preview=studio_preview,
        shot_type=shot_type,
        scene_emotion=scene_emotion,
        enable_face_detailer=enable_face_detailer,
        character_package=character_package,
        cond_pkg=(character_package or {}).get('conditioning', {}),
        init_image=init_image,
        reference_image=reference_image,
        pose_image=pose_image,
        lora_name=lora_name,
        style_lora_name=style_lora_name,
        style_lora_scale=style_lora_scale,
        medusa_base_name=_medusa_base_name,
        medusa_base_scale=_medusa_base_scale,
    )

    _steps.configure_detailer_passes(ctx)
    _steps.apply_prompt_and_sampler(ctx)
    _refusal = _steps.apply_model_nodes(ctx)
    if _refusal:
        return False, _refusal
    _steps.apply_face_detailer_patch(ctx)
    _steps.apply_hand_detailer_patch(ctx)
    _refusal = _steps.apply_workflow_overrides(ctx)
    if _refusal:
        return False, _refusal
    _steps.log_submission(ctx)

    outputs, _fail = _steps.submit_render(ctx, _maybe_clear_vram)
    if _fail or outputs is None:
        return False, _fail or 'no_output'

    _steps.save_render_output(ctx, outputs, _qwen_upscale_back)
    _steps.apply_render_time_restyle(ctx)
    _hand_fixer_ok = _steps.run_hand_fixer_stage(ctx)

    if not skip_qa:
        _drift_ok, _drift_sc = _post_save(
            out_path,
            char_id,
            full_prompt,
            seed,
            log,
            character_package,
        )
        if require_drift_pass and not _drift_ok:
            log(f'ComfyGen: rejected — identity drift score={_drift_sc:.3f}')
            _maybe_clear_vram('post-drift-reject')
            return False, 'drift'
    backend = f'comfy_{workflow_name}'
    if _hand_fixer_ok:
        backend += '+handfixer'
    _maybe_clear_vram('post-still')
    return True, backend
