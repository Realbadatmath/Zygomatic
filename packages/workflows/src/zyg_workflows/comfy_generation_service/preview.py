# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Diffusers fallback wrapper and the character preview still chain (original lines 2241-2456)."""

from __future__ import annotations

import os
from typing import Any, Callable
from zyg_workflows.comfy_generation_service.constants import (
    _PREVIEW_FACE_PORE_DENOISE,
    _PREVIEW_LORA_SCALE,
    _PREVIEW_SDXL_STEPS,
    _SDXL_IMG2IMG_DENOISE,
    _SDXL_TRAIN_REPO_ID,
    _log_default,
)
from zyg_workflows.comfy_generation_service.backend import is_available
from zyg_workflows.comfy_generation_service.flux_graph import has_instantid
from zyg_workflows.comfy_generation_service.style import (
    _is_photoreal_render_style,
    _normalize_model_family,
    _render_style_from_package,
    _restyle_profile_from_package,
    ensure_sdxl_comfy_checkpoint,
)
from zyg_workflows.comfy_generation_service.workflows import _resolve_checkpoint_sdxl
from zyg_workflows.comfy_generation_service.generate import _post_save, generate_still


def try_generate_still_with_fallback(
    out_path: str,
    scene_prompt: str,
    diffusers_fn: Callable[[], bool],
    **kwargs: Any,
) -> tuple[bool, str]:
    if is_available():
        ok, backend = generate_still(out_path, scene_prompt, **kwargs)
        if ok:
            return True, backend
    ok_d = diffusers_fn()
    return ok_d, 'diffusers' if ok_d else 'failed'


def generate_character_preview_still(
    out_path: str,
    scene_prompt: str,
    *,
    width: int = 512,
    height: int = 768,
    seed: int = 42,
    character_package: dict[str, Any] | None = None,
    char_id: str = '',
    reference_image: str | None = None,
    model_family: str = 'sdxl',
    log_fn: Callable[[str], None] | None = None,
    blender_dataset: bool = False,
) -> tuple[bool, str, bool, float]:
    """SDXL/FLUX character preview with fallback chain.

    Returns ``(success, backend_label, drift_passed, drift_score)``.

    Order: (1) character LoRA locked txt2img, (2) InstantID if allowed,
    (3) img2img from slot reference at low denoise (last resort).
    """
    import copy as _copy_pkg

    log = log_fn or _log_default
    mf = _normalize_model_family(model_family)
    steps = _PREVIEW_SDXL_STEPS if mf == 'sdxl' else 20
    cfg = 6.0 if mf == 'sdxl' else 3.5
    pkg = _copy_pkg.deepcopy(character_package) if character_package else {}
    cond = pkg.setdefault('conditioning', {})
    if mf == 'sdxl':
        _lora_p = cond.get('sdxl_lora_path')
    else:
        _lora_p = cond.get('flux_lora_path') or cond.get('lora_path')
    has_lora = bool(_lora_p and os.path.isfile(str(_lora_p)))
    _render_st = _render_style_from_package(character_package)
    # 2026-07-27: arcane/restyle gate for the QC valve (pkg.render_style is still
    # 'photorealistic' here — never mutated to the sentinel — so detect via profile).
    _rprof_v = _restyle_profile_from_package(pkg)
    if mf == 'sdxl':
        try:
            _render_st = ((pkg.get('style_profile') or {}).get('render_style') or '').strip().lower()
            # restyle → pin the profile render_checkpoint (Juggernaut) via
            # _resolve_checkpoint_sdxl (which is profile-aware); NEVER the aligned base.
            if _is_photoreal_render_style(_render_st) or _rprof_v:
                cond['sdxl_checkpoint'] = _resolve_checkpoint_sdxl(pkg)
            else:
                aligned = ensure_sdxl_comfy_checkpoint(log_fn=log)
                cond['sdxl_checkpoint'] = aligned
            cond['sdxl_train_repo'] = _SDXL_TRAIN_REPO_ID
        except Exception as _ck_e:
            log(f'ComfyGen: SDXL checkpoint warning: {_ck_e}')

    # 1) LoRA locked txt2img (no Blender reference — avoids mannequin copy-through)
    if has_lora:
        pkg_locked = _copy_pkg.deepcopy(pkg)
        pkg_locked['conditioning']['instantid_enabled'] = False
        # 2026-07-27: restyle (Arcane) SDXL valve — DISABLE the FaceDetailer re-realism
        # pass (which episodes also disable). Otherwise the valve scores a photoreal-
        # repainted face episodes never produce → wrongful park.
        _rs_valve = bool(_rprof_v and mf == 'sdxl')
        pkg_locked['conditioning']['face_detail_pass'] = not _rs_valve
        _pore = bool(pkg_locked['conditioning'].get('skin_pore_pass'))
        if mf == 'flux':
            pkg_locked['conditioning'].setdefault('hand_detail_pass', False)
            if _pore:
                pkg_locked['conditioning'].setdefault('face_detail_strength', _PREVIEW_FACE_PORE_DENOISE)
        else:
            pkg_locked['conditioning']['hand_detail_pass'] = True
            pkg_locked['conditioning'].setdefault(
                'hand_detail_strength',
                float(os.environ.get('ZYG_PREVIEW_HAND_DETAIL_DENOISE', '0.42')),
            )
        _prev_scale = float(pkg_locked['conditioning'].get('lora_scale', 0.85))
        if _rprof_v and mf == 'sdxl':
            # 2026-07-27: the arcane SDXL LoRA must be SCORED at the same strength episodes
            # render it (natural ~0.85) — the 0.65 photoreal cap and the 0.75 preview cap
            # under-apply the baked style, making the valve render photoreal-ish and score
            # off-identity → wrongly park. SDXL-only: the FLUX photoreal twin leg (same
            # restyle bible) must keep its photoreal cap. Optional profile override.
            _rls = (_rprof_v.get('restyle') or {}).get('render_lora_scale')
            pkg_locked['conditioning']['lora_scale'] = float(_rls) if _rls else _prev_scale
        else:
            if _is_photoreal_render_style(_render_st):
                _prev_scale = min(
                    _prev_scale,
                    float(os.environ.get('ZYG_PREVIEW_PHOTOREAL_LORA_SCALE', '0.65')),
                )
            pkg_locked['conditioning']['lora_scale'] = min(_prev_scale, _PREVIEW_LORA_SCALE)
        try:
            ok, backend = generate_still(
                out_path,
                scene_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg=cfg,
                seed=seed,
                character_package=pkg_locked,
                char_id=char_id,
                reference_image=None,
                model_family=mf,
                log_fn=log,
                force_workflow='sdxl_character_locked' if mf == 'sdxl' else 'flux_character_locked',
                blender_dataset=blender_dataset,
                skip_qa=True,
                studio_preview=True,
                # restyle: keep FaceDetailer OFF (see face_detail_pass above) so the valve
                # scores the same painterly face episodes render.
                **({'enable_face_detailer': False} if _rs_valve else {}),
            )
        except Exception as _lora_gen_e:
            log(f'ComfyGen: LoRA locked preview exception: {_lora_gen_e}')
            ok = False
        if ok:
            # Tag pkg_locked with the 'restyle' sentinel ONLY for the drift threshold in
            # _post_save (relaxed 0.45) — done AFTER generate_still so it never leaks a
            # junk 'restyle' token into the rendered prompt. The FLUX photoreal twin leg
            # (not _rs_valve) keeps render_style='photorealistic' → strict 0.60 floor.
            if _rs_valve:
                pkg_locked.setdefault('style_profile', {})['render_style'] = 'restyle'
            drift_ok, drift_sc = _post_save(
                out_path,
                char_id,
                scene_prompt,
                seed,
                log,
                pkg_locked,
            )
            return True, backend, drift_ok, drift_sc
        log('ComfyGen: LoRA locked preview failed — trying fallbacks')

    # 2) InstantID (photo uploads only — not Blender meshes)
    if (
        not blender_dataset
        and bool(cond.get('instantid_enabled'))
        and reference_image
        and os.path.isfile(reference_image)
        and has_instantid(mf)
    ):
        pkg_id = _copy_pkg.deepcopy(pkg)
        ok, backend = generate_still(
            out_path,
            scene_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            character_package=pkg_id,
            char_id=char_id,
            reference_image=reference_image,
            model_family=mf,
            log_fn=log,
            blender_dataset=False,
            skip_qa=True,
        )
        if ok:
            drift_ok, drift_sc = _post_save(
                out_path,
                char_id,
                scene_prompt,
                seed,
                log,
                pkg_id,
            )
            return True, backend, drift_ok, drift_sc
        log('ComfyGen: InstantID preview failed — trying img2img fallback')

    # 3) img2img last resort (low denoise so prompt can reshape, not clone mesh)
    if reference_image and os.path.isfile(reference_image):
        pkg_i2i = _copy_pkg.deepcopy(pkg)
        pkg_i2i['conditioning']['instantid_enabled'] = False
        ok, backend = generate_still(
            out_path,
            scene_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            character_package=pkg_i2i,
            char_id=char_id,
            reference_image=reference_image,
            model_family=mf,
            log_fn=log,
            force_workflow='sdxl_img2img' if mf == 'sdxl' else 'flux_img2img',
            denoise=_SDXL_IMG2IMG_DENOISE if mf == 'sdxl' else 0.45,
            blender_dataset=blender_dataset,
            skip_qa=True,
        )
        if ok:
            drift_ok, drift_sc = _post_save(
                out_path,
                char_id,
                scene_prompt,
                seed,
                log,
                pkg_i2i,
            )
            return True, backend, drift_ok, drift_sc

    return False, 'preview_all_backends_failed', False, 0.0
