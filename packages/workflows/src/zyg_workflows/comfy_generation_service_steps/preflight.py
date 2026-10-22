# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

# This module carries comfy_generation_service_steps.py's original top import block verbatim.
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

# Re-exported for the sibling steps, which read it back out of this module
# (submit.py: ``from .preflight import Any, Callable, StillRenderCtx, _svc, os, shutil``).
__all__ = ['shutil']

_zyg_log = logging.getLogger('zyg_workflows.comfy_generation_service_steps')


def _svc() -> Any:
    """The parent service module, imported on use to avoid an import cycle."""
    from zyg_workflows import comfy_generation_service as _service

    return _service


@dataclass
class StillRenderCtx:
    """Everything the post-workflow-load steps of ``generate_still`` share.

    ``workflow`` and ``overrides`` are the live objects the steps mutate, so the
    sequence of patches is exactly the one the single function applied.
    """

    log: Callable[[str], None]
    comfy: Any
    workflow: dict[str, Any]
    workflow_name: str
    out_path: str
    char_id: str
    scene_prompt: str
    full_prompt: str
    full_negative: str
    mf: str
    unet: str
    is_schnell: bool
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    denoise: float | None
    flux_guidance: float | None
    cfg_start_frac: float | None
    studio_preview: bool
    shot_type: str | None
    scene_emotion: str | None
    enable_face_detailer: bool | None
    character_package: dict[str, Any] | None
    cond_pkg: dict[str, Any]
    init_image: str | None
    reference_image: str | None
    pose_image: str | None
    lora_name: str | None
    style_lora_name: str | None
    style_lora_scale: float
    medusa_base_name: str | None
    medusa_base_scale: float
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def set_node(self, node_id: str, patch: dict[str, Any]) -> None:
        """Only register an override if the workflow actually has that node."""
        if node_id in self.workflow:
            self.overrides[node_id] = patch


# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #


def flux_licence_paused(mf: str, log: Callable[[str], None]) -> bool:
    """True when this FLUX render must refuse on licence grounds.

    2026-08-09 licence pause. FLUX.1-dev is under the BFL Non-Commercial
    License and this channel is monetised; the SDXL leg is unaffected. Uses the
    existing (False, label) refusal protocol rather than raising. NOTE: pausing
    deliberately does NOT silently fall back to flux1-schnell — a character LoRA
    trained on flux1-dev stays a derivative of a non-commercial base whichever
    unet loads it, so a swap would buy the appearance of clearance, not clearance.
    """
    if mf != 'flux':
        return False
    try:
        from zyg_workflows import licence_provenance as _lp

        if _lp.flux_paused():
            log(
                '[licence] FLUX still generation PAUSED — flux1-dev is under the '
                'BFL Non-Commercial License. ZYG_FLUX_RENDERS=allowed to resume.'
            )
            return True
    except ImportError as _exc:
        _zyg_log.warning(
            'flux licence-pause check unavailable, continuing with the FLUX still render: %s',
            _exc,
        )
    return False


def compose_prompts(
    scene_prompt: str,
    character_package: dict[str, Any] | None,
    *,
    model_family: str | None,
    prompt_finalized: bool,
    studio_preview: bool,
    solo_subject: bool,
    human_subject: bool,
    extra_negative: str,
) -> tuple[str, str, dict[str, Any] | None, str]:
    """Build the final positive/negative pair and the effective render style.

    Returns ``(full_prompt, full_negative, character_package, model_family)``:
    the package comes back because the SDXL animated/restyle sentinels are
    written into a DEEPCOPY of it — never the saved bible.
    """
    svc = _svc()
    if prompt_finalized:
        # Same clause-boundary cap as build_locked_prompt — a blind [:1500]
        # here re-truncated the pipeline's already-trimmed 2000-char prompts
        # mid-word on the FLUX anchor path (review finding, 2026-07-09).
        full_prompt = svc._trim_prompt_at_clause(
            scene_prompt or '',
            int(os.environ.get('ZYG_FLUX_PROMPT_MAX_CHARS', '2000')),
        )
    else:
        full_prompt = svc.build_locked_prompt(
            scene_prompt,
            character_package,
            studio_preview=studio_preview,
        )
    full_negative = svc.build_locked_negative_prompt(
        character_package,
        studio_preview=studio_preview,
        solo_subject=solo_subject,
        human_subject=human_subject,
    )
    if extra_negative:
        full_negative = f'{full_negative}, {extra_negative}'.strip(', ')
    mf = svc._normalize_model_family(model_family)
    # 2026-07-25: SDXL ⟹ ANIMATED (operator directive). This is the single
    # cascade point — force the effective render style to 'animated' on every
    # SDXL render so the checkpoint pick (_resolve_checkpoint_sdxl), the
    # cross-style negatives, and the drift threshold all key on animated
    # without per-call plumbing. FLUX renders keep the character's real style.
    # ZYG_SDXL_ANIMATED=0 restores legacy SDXL-as-photoreal.
    # Gate on the animated-twin MARKER, not mere SDXL family — a legacy
    # photoreal-SDXL character (or a contact-sheet SDXL cell rendered before
    # the animated LoRA exists) has no sdxl_render_style marker and must NOT be
    # force-toon'd. update_lora sets the marker when the animated SDXL LoRA is
    # registered, so storyteller renders of a proper twin still engage.
    if (
        mf == 'sdxl'
        and character_package
        and not studio_preview
        and str(((character_package.get('conditioning') or {}).get('sdxl_render_style')) or '').strip().lower()
        == 'animated'
        and os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no')
    ):
        import copy as _copy_sdxl_anim

        character_package = _copy_sdxl_anim.deepcopy(character_package)
        character_package.setdefault('style_profile', {})['render_style'] = 'animated'
    # 2026-07-27: RESTYLE (Arcane) render mode — DISTINCT from the animated
    # (DynaVision) path. NO `not studio_preview` guard: this must fire for BOTH the
    # episode render AND the post-train QC/studio-preview render so the negatives,
    # checkpoint pick and drift threshold all key on the 'restyle' sentinel and the
    # baked-in painterly style is not fought by anti-cartoon negatives. Mutually
    # exclusive with the animated path by data (a restyle char has no 'animated'
    # marker; an animated char has no style_profile.restyle). Sentinel is written
    # only into a deepcopy — never the saved bible.
    if mf == 'sdxl' and character_package:
        _rprof_gs = svc._restyle_profile_from_package(character_package)
        if _rprof_gs:
            import copy as _copy_sdxl_rs

            character_package = _copy_sdxl_rs.deepcopy(character_package)
            character_package.setdefault('style_profile', {})['render_style'] = 'restyle'
            _rs_ckpt = str((_rprof_gs.get('render_checkpoint') or '')).strip()
            if _rs_ckpt:
                character_package.setdefault('conditioning', {})['sdxl_checkpoint'] = _rs_ckpt
    if character_package:
        _render_st = svc._render_style_from_package(character_package)
        full_negative = svc._append_render_style_negatives(
            full_negative,
            _render_st,
            studio_preview=studio_preview,
        )
    # 2026-07-27: restyle sanitizer — runs on the FINALIZED strings so it removes the
    # baked/late photoreal POSITIVES (skin pores, film grain, RAW-photo, 85mm, the raw
    # 'photorealistic' render_style token) and anti-PAINTERLY NEGATIVES (painterly,
    # digital painting, concept art, illustration, hand-painted, PHOTOREAL_SKIN_NEG
    # smooth-skin terms) that upstream sites injected before this sentinel existed —
    # for both the episode (prompt_finalized) and QC-valve renders. SDXL-only (the FLUX
    # photoreal twin leg keeps its photoreal prompt).
    if mf == 'sdxl' and svc._restyle_profile_from_package(character_package):
        full_prompt = svc._strip_clause_tokens(full_prompt, svc._RESTYLE_POS_STRIP)
        full_negative = svc._strip_clause_tokens(full_negative, svc._RESTYLE_NEG_STRIP)
    # 2026-08-26: drop the person-only anatomy clauses when the subject is not a
    # person. Applied HERE, after every source has contributed (bible base +
    # _ANATOMY_NEG + the caller's extra_negative + the render-style block), so it
    # cannot be defeated by a clause arriving from a path that predates the flag.
    # See _NONHUMAN_NEG_STRIP for what goes and what deliberately stays.
    if not human_subject:
        full_negative = svc._strip_clause_tokens(full_negative, svc._NONHUMAN_NEG_STRIP)
    # P-06: dedupe once the string is FINAL — bible base + _ANATOMY_NEG + the
    # caller's extra_negative repeated "bad anatomy" x3 / "extra fingers" x3 /
    # "watermark" x2 in a 1,251-char string, and _append_render_style_negatives
    # above re-adds clauses the base already carries ("wax figure skin",
    # "airbrushed", "extra fingers"). First occurrence wins. Runs after the
    # restyle strip so this is the exact string node 21 receives.
    full_negative = svc._dedupe_negative_clauses(full_negative)
    return full_prompt, full_negative, character_package, mf


def resolve_unet_and_sampling(
    mf: str,
    character_package: dict[str, Any] | None,
    *,
    force_unet: str | None,
    force_workflow: str | None,
    steps: int,
    cfg: float,
) -> tuple[str, bool, int, float]:
    """Pick the unet and clamp steps/cfg for the distilled models.

    Returns ``(unet, is_schnell, steps, cfg)``.
    """
    svc = _svc()
    unet = force_unet or (
        svc._resolve_unet(character_package)
        if mf == 'flux'
        else (svc.qwen_t2i_unet() or '')
        if mf == 'qwen'
        else (svc.klein_t2i_unet() or '')
        if mf == 'klein'
        else ''
    )
    is_schnell = ('schnell' in (unet or '').lower()) if mf == 'flux' else False
    if mf == 'flux' and is_schnell and steps > 8 and not force_unet:
        steps = 4
        cfg = 1.0
    # Same rule, same reason, different family: the distilled klein is a 4-step
    # cfg-1.0 model. Handing it 20 steps at cfg 5 is the schnell mistake again —
    # the guidance is baked in, so real CFG on top of it degrades the sample.
    # The UNDISTILLED base is untouched here; it genuinely wants 20 steps/cfg 5.
    if (
        mf == 'klein'
        and svc.klein_is_distilled(unet)
        and not force_unet
        and (force_workflow or '').startswith(('klein', ''))
        and 'qwen_edit' not in (force_workflow or '')
    ):
        if steps > 8:
            steps = 4
        cfg = 1.0
    return unet, is_schnell, steps, cfg


def stage_medusa_base_lora(
    medusa_base_lora: dict | None,
    mf: str,
    log: Callable[[str], None],
) -> tuple[str | None, float]:
    """Stage the Medusa base LoRA; returns ``(staged_name, scale)``.

    Staged under a per-model filename by medusa_model_lora (never a shared
    name — see that module on the 28/28 + 37/39 mis-render). A family mismatch
    drops it rather than loading qwen weights onto klein.
    """
    if not medusa_base_lora:
        return None, 0.0
    try:
        from zyg_workflows import medusa_model_lora as _mml

        if _mml.normalize_family(medusa_base_lora.get('family')) != mf:
            log(f'ComfyGen: medusa base LoRA is for {medusa_base_lora.get("family")}, this render is {mf} — skipping')
        else:
            return (
                _mml.stage(
                    str(medusa_base_lora.get('path') or ''),
                    str(medusa_base_lora.get('model_id') or ''),
                    mf,
                    log,
                ),
                float(medusa_base_lora.get('scale') or 0.85),
            )
    except Exception as _mb_exc:  # noqa: BLE001 — never fail a render on this
        log(f'ComfyGen: medusa base LoRA unavailable ({_mb_exc}) — rendering without')
    return None, 0.0


def stage_character_lora_for_family(
    character_package: dict[str, Any] | None,
    char_id: str,
    mf: str,
    log: Callable[[str], None],
) -> str | None:
    """Stage the character adapter for this family, or None when there is none."""
    if not character_package:
        return None
    cond_l = character_package.get('conditioning') or {}
    if mf == 'flux':
        _lora_p = cond_l.get('flux_lora_path') or cond_l.get('lora_path')
    elif mf == 'qwen':
        # No legacy fallback: 'lora_path' is FLUX-era and must never route
        # FLUX weights onto the qwen base.
        _lora_p = cond_l.get('qwen_lora_path')
    elif mf == 'klein':
        # Same rule: a klein render loads a klein adapter or none at all.
        _lora_p = cond_l.get('klein_lora_path')
    else:
        _lora_p = cond_l.get('sdxl_lora_path')
    _cid_stage = (char_id or '').strip() or str(
        character_package.get('character_id') or '',
    ).strip()
    return _svc()._stage_character_lora(
        _lora_p,
        log,
        model_family=mf,
        char_id=_cid_stage,
    )


def select_workflow(
    character_package: dict[str, Any] | None,
    init_for_wf: str | None,
    reference_image: str | None,
    lora_name: str | None,
    *,
    mf: str,
    blender_dataset: bool,
    force_workflow: str | None,
    pose_image: str | None,
    medusa_base_name: str | None,
    medusa_base_scale: float,
    log: Callable[[str], None],
) -> tuple[str, str | None]:
    """Pick the graph; returns ``(workflow_name, medusa_base_name)``.

    ``medusa_base_name`` comes back because a missing ``<family>_medusa_base``
    template drops the base adapter for the rest of the render.
    """
    svc = _svc()
    workflow_name = svc._pick_workflow(
        character_package,
        init_for_wf,
        reference_image,
        lora_name,
        model_family=mf,
        blender_dataset=blender_dataset,
        force_workflow=force_workflow,
        pose_image=pose_image,
    )
    if (
        mf == 'klein'
        and pose_image
        and os.path.isfile(pose_image)
        and workflow_name != 'klein_refcontrol'
        and not force_workflow
    ):
        log(
            'ComfyGen: klein control image supplied but the RefControl adapter is not '
            f'installed ({svc._KLEIN_CONTROL_LORA} in models/loras) — falling back to '
            f'{workflow_name}, which treats the image as an appearance reference, not '
            'as geometry'
        )
    # Medusa base LoRA => the private <family>_medusa_base graph. Placed BEFORE
    # the character-locked abort below on purpose: that guard exists because the
    # *_character_locked graphs carry a stale hardcoded lora_name, and the
    # medusa graph's node 13 is explicitly zeroed a few lines down when this
    # render has no character, so it is not exposed to the same hazard.
    if medusa_base_name:
        _medusa_wf = f'{mf}_medusa_base'
        if svc._workflow_template_exists(_medusa_wf):
            log(f'ComfyGen: medusa base LoRA active -> {_medusa_wf} (node 14 @ {medusa_base_scale})')
            workflow_name = _medusa_wf
        else:
            log(f'ComfyGen: {_medusa_wf} graph missing — rendering without the medusa base LoRA')
            medusa_base_name = None
    return workflow_name, medusa_base_name


def qwen_edit_resolution_cap(
    workflow_name: str,
    width: int,
    height: int,
    qwen_max_mp: float | None,
    log: Callable[[str], None],
) -> tuple[int, int, tuple[int, int] | None]:
    """Qwen-Image-Edit ~1MP working budget (2026-07-19).

    The edit model internally downscales anything above ~1 megapixel, which
    softened faces on every 1024×1152 (1.18MP) edit tile (run 0cc9541b;
    community-documented limit — see Qwen-Edit unblur adapters). Generate within
    budget and Lanczos-upscale back to the requested size after saving, so
    sheet/tile geometry stays uniform. ZYG_QWEN_EDIT_MAX_MP=0 disables.

    Returns ``(width, height, upscale_back_or_None)``.
    """
    if 'qwen_edit' not in (workflow_name or ''):
        return width, height, None
    if qwen_max_mp is not None:
        _max_mp = float(qwen_max_mp)
    else:
        try:
            _max_mp = float(os.environ.get('ZYG_QWEN_EDIT_MAX_MP', '1.0'))
        except ValueError:
            _max_mp = 1.0
    _budget = int(_max_mp * 1024 * 1024)
    if _budget > 0 and width * height > _budget:
        import math as _math

        _scale = _math.sqrt(_budget / float(width * height))
        _new_w = max(16, int(width * _scale) // 16 * 16)
        _new_h = max(16, int(height * _scale) // 16 * 16)
        log(
            f'ComfyGen: qwen-edit 1MP cap — generating at {_new_w}×{_new_h} '
            f'(was {width}×{height}), upscaling back after save',
        )
        return _new_w, _new_h, (width, height)
    return width, height, None
