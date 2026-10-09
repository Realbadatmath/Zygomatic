# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LoRA flywheel: angle expansion with the trained v1 LoRA.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 4602-4913).
"""

from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    EXPANSION_COUNT,
    EXPANSION_MIN_SCORE,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _anchor_cell_path,
    _body_anchor_path_for,
    _find_indexed_file,
    build_identity_snippet,
    contact_sheet_dir,
    identity_anchor_face_path,
    load_manifest,
    training_dataset_dir,
    trigger_token_for,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    _cell_size_for_angle,
    _framing_clause,
    _is_full_body_angle,
    _qwen_angle_instruction,
    _strip_detailer_for_steep,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import (
    _build_sheet_character_package,
    _comfy_availability,
    caption_style_description,
)


# LoRA flywheel: the angles a face-embedding lock cannot hold (embeddings carry no
# back-of-head, crown, or body information) — generated with the trained v1 LoRA,
# which learned whole appearance, then folded back into the dataset for v2.
EXPANSION_ANGLES = [
    'camera from directly behind, full body back view, standing A-pose, hair and outfit back detail',
    'camera from behind rotated 45 degrees left, back three-quarter view, full body standing',
    'camera from behind rotated 45 degrees right, back three-quarter view, full body standing',
    'camera directly overhead, top-down view of head crown, hair parting and shoulders',
    'camera from behind slightly above, close-up back of head, hair whorl and hairline detail',
    'camera high angle 45 degrees above, full body three-quarter left view',
    'camera high angle 45 degrees above, full body three-quarter right view',
    'camera low worm eye view from below, full body front view',
    'camera low angle from below, three-quarter left upper body view',
    'camera rotated 90 degrees left, full body left profile, standing A-pose',
    'camera rotated 90 degrees right, full body right profile, standing A-pose',
    'camera rotated 120 degrees left, back three-quarter head and shoulders, ear visible',
    'camera rotated 120 degrees right, back three-quarter head and shoulders, ear visible',
    'camera straight on, full body front view, T-pose arms straight out, flat even lighting',
    'camera from directly behind, full body back view, T-pose arms straight out, flat even lighting',
    'camera slightly below chin level, upward view, jawline neck and under-chin detail',
]


def run_angle_expansion(
    char_id: str,
    params: dict,
    lora_path: str,
    *,
    model_family: str = 'flux',
    log_fn: Callable[[str], None] | None = None,
    progress_job: dict | None = None,
    halt_check: Callable[[], None] | None = None,
) -> list[str]:
    """
    Flywheel stage 1: generate hard angles with the freshly trained LoRA, gate
    them through identity QC where a face is visible, and copy survivors into
    the dataset as expansion_XX.png + caption. Returns kept dataset paths.
    """
    import copy

    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import contact_sheet_pipeline_steps as _steps

    ok_avail, reason = _comfy_availability()
    if not ok_avail:
        if log_fn:
            log_fn(f'Angle expansion skipped — {reason}')
        return []
    if not lora_path or not os.path.isfile(lora_path):
        if log_fn:
            log_fn(f'Angle expansion skipped — LoRA not found: {lora_path}')
        return []

    mf = (model_family or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = 'flux'
    angles = EXPANSION_ANGLES[: max(1, min(EXPANSION_COUNT, len(EXPANSION_ANGLES)))]
    # Remove expansion angles whose first camera-position phrase already appears
    # in the main sheet (e.g. 120° three-quarter is in the extended set G/H).
    # Compare the text before the first comma to handle label wording differences.
    _main_keys = {
        t.get('angle', '').split(',')[0].strip().lower()
        for t in (load_manifest(char_id) or {}).get('tiles', [])
        if t.get('angle')
    }
    _pre_dedup = len(angles)
    angles = [a for a in angles if a.split(',')[0].strip().lower() not in _main_keys]
    if len(angles) < _pre_dedup and log_fn:
        log_fn(
            f'Expansion dedup: {_pre_dedup - len(angles)} angle(s) skipped (already covered by main sheet)',
        )
    pkg = _build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    cond = gen_pkg.setdefault('conditioning', {})
    cond['hand_detail_pass'] = False
    cond['instantid_enabled'] = False
    # Family-keyed LoRA slot — the comfy service reads qwen_lora_path /
    # klein_lora_path for those families (never the FLUX-era 'lora_path'
    # fallback).
    cond[
        'flux_lora_path'
        if mf == 'flux'
        else 'qwen_lora_path'
        if mf == 'qwen'
        else 'klein_lora_path'
        if mf == 'klein'
        else 'sdxl_lora_path'
    ] = lora_path

    trigger = trigger_token_for(char_id)
    style_extra = caption_style_description((params or {}).get('style', 'photorealistic'))
    ident = build_identity_snippet(params)
    exp_dir = os.path.join(contact_sheet_dir(char_id), 'expansion')
    os.makedirs(exp_dir, exist_ok=True)
    dataset_dir = training_dataset_dir(char_id)
    os.makedirs(dataset_dir, exist_ok=True)

    try:
        from zyg_workflows import identity_qc_service as _idqc

        idqc_ok, _ = _idqc.available()
    except ImportError:
        _idqc = None
        idqc_ok = False
    anchor = identity_anchor_face_path(char_id)
    anchor_ok = idqc_ok and os.path.isfile(anchor)

    # Same lock stack as the main sheet — Qwen rotation edits produce CLEAN backs
    # (the old LoRA-txt2img path painted a face onto back-of-head prompts, wasting
    # ~3/16 cells to mislabeled_angle and running FaceDetailer on faceless shots).
    qwen_ok = False
    pulid_ok = False
    try:
        qwen_ok = mf in ('flux', 'qwen') and _cgs.has_qwen_edit_angles()
        pulid_ok = mf == 'flux' and _cgs.has_pulid_flux()
    except Exception as _exc:
        _zyg_log.warning('expansion identity lock probe failed, assuming qwen_edit and pulid unavailable: %s', _exc)
    anchor_cell = _anchor_cell_path(char_id)
    anchor_cell_ok = os.path.isfile(anchor_cell)
    # Body anchor for full-body expansion angles (head cells keep cell_00 so
    # the face reaches the edit model at full size, not ~100px).
    _exp_body_anchor = _body_anchor_path_for(char_id)
    _exp_body_ok = os.path.isfile(_exp_body_anchor)

    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))
    base_seed = int(uuid.uuid4().int % (2**31))
    unet = os.environ.get('ZYG_CONTACT_SHEET_UNET', 'flux1-dev.safetensors')

    if log_fn:
        log_fn(
            f'Angle expansion — {len(angles)} hard angles '
            f'(qwen: {"ON" if qwen_ok else "off"}, pulid: {"ON" if pulid_ok else "off"}, '
            f'LoRA fallback {os.path.basename(lora_path)}, QC {"on" if anchor_ok else "off"}, '
            f'keep floor {EXPANSION_MIN_SCORE})',
        )

    kept: list[str] = []
    for i, angle in enumerate(angles):
        if callable(halt_check):
            halt_check()
        if progress_job is not None:
            progress_job['sheet_substage'] = f'expansion_{i:03d}'
            progress_job['sheet_cells_done'] = i
            progress_job['sheet_cells_total'] = len(angles)

        cell_w, cell_h = _cell_size_for_angle(angle)
        instruction = _qwen_angle_instruction(angle, params) if qwen_ok else None
        out = os.path.join(exp_dir, f'expansion_{i:03d}.png')
        gen_kwargs: dict[str, Any] = {
            'width': cell_w,
            'height': cell_h,
            'steps': steps,
            'cfg': cfg,
            'seed': base_seed + i * 9973,
            'character_package': gen_pkg,
            'char_id': char_id,
            'model_family': mf,
            'log_fn': log_fn,
            'skip_qa': True,
            'studio_preview': True,
            'prompt_finalized': True,
            'extra_negative': (
                'blurry, low quality, different person, inconsistent identity, deformed body, extra limbs'
            ),
        }
        if instruction is not None and anchor_cell_ok:
            # Qwen rotation edit of the anchor cell — best for backs/rotations.
            prompt = instruction
            gen_kwargs['reference_image'] = (
                _exp_body_anchor if (_is_full_body_angle(angle) and _exp_body_ok) else anchor_cell
            )
            gen_kwargs['force_workflow'] = 'qwen_edit_angle'
            _strip_detailer_for_steep(gen_kwargs, angle)
        elif pulid_ok and anchor_ok:
            # PuLID face-ID lock for frontal-ish expansion angles.
            scene = (
                f'{angle}, single person, exact same person as reference, '
                f'character reference portrait, neutral studio background'
                f'{_framing_clause(angle)}, {style_extra}, {trigger}'
            )
            prompt = _cgs.build_locked_prompt(scene, pkg, studio_preview=True)
            gen_kwargs['reference_image'] = anchor
            gen_kwargs['force_workflow'] = 'flux_pulid_cell'
            gen_kwargs['force_unet'] = unet
            gen_kwargs['flux_guidance'] = cfg
        elif mf == 'qwen':
            # No qwen instruction for this angle and the PuLID / plain-txt2img
            # fallbacks are identity-free or FLUX-arch — skip loudly rather
            # than render an unlocked stranger for the v2 dataset (2026-08-09).
            if log_fn:
                log_fn(
                    f'Expansion {i + 1}/{len(angles)} skipped — no qwen edit '
                    f'path for this angle (qwen family has no locked fallback)',
                )
            continue
        else:
            # Last resort: LoRA txt2img (the original path).
            scene = f'{angle}, character reference, neutral studio background, {style_extra}, {trigger}'
            prompt = _cgs.build_locked_prompt(scene, pkg, studio_preview=True)
            if mf == 'flux':
                gen_kwargs['force_unet'] = unet
                gen_kwargs['flux_guidance'] = cfg
        # Resume: reuse an expansion tile a prior (paused) run already rendered;
        # QC below still re-runs (cheap) to decide whether to keep it.
        # Read-side 02d compat for pre-migration expansion files.
        _resuming = bool(progress_job is not None and progress_job.get('resume'))
        _exp_resume = _find_indexed_file(exp_dir, 'expansion', i)
        if _resuming and os.path.isfile(_exp_resume):
            out = _exp_resume
            ok, backend = True, 'resume-reuse'
            if log_fn:
                log_fn(f'Expansion {i + 1}/{len(angles)} reused (resume)')
        else:
            ok, backend = _cgs.generate_still(out, prompt, **gen_kwargs)
        if not ok or not os.path.isfile(out):
            if log_fn:
                log_fn(f'Expansion {i + 1}/{len(angles)} failed ({backend})')
            continue

        verdict = 'unscored'
        score = None
        if anchor_ok and _idqc is not None:
            try:
                rep = _idqc.score_images_against_anchor(anchor, [{'path': out, 'angle': angle}])
                r = (rep.get('results') or {}).get(out) or {}
                verdict = r.get('verdict') or 'unscored'
                score = r.get('score')
            except Exception as exc:
                if log_fn:
                    log_fn(f'Expansion {i + 1} QC error ({exc}) — keeping unscored')
        # Drop any fail-class content (drift, multi-face collage, edge-cut,
        # mislabeled angle); no_face on back/profile shots is expected.
        _fc = tuple(getattr(_idqc, 'FAIL_CLASS', ('fail',))) if _idqc is not None else ('fail',)
        if verdict in _fc:
            if log_fn:
                log_fn(
                    f'Expansion {i + 1}/{len(angles)} dropped — {verdict} (score {score})',
                )
            continue
        # Quality floor: a scored tile below the floor is too weak an identity to
        # train v2 on. Unscored faceless backs (no_face_expected) always pass.
        if isinstance(score, (int, float)) and score < EXPANSION_MIN_SCORE:
            if log_fn:
                log_fn(
                    f'Expansion {i + 1}/{len(angles)} dropped — identity {score} < floor {EXPANSION_MIN_SCORE}',
                )
            continue

        # VLM defect judge (2026-07-16): expansion tiles come from the same
        # ghost-prone qwen-edit path as the main sheet and must pass the same
        # gate before training v2 — ArcFace floors alone are blind to ghosts.
        # release() right away: ComfyUI generates the next angle immediately
        # after and must not fight the local vision model for VRAM.
        try:
            from zyg_workflows import cell_vlm_judge as _vlm_exp

            if not _vlm_exp.enabled():
                _vlm_exp = None
        except Exception:
            _vlm_exp = None
        if _vlm_exp is not None:
            _exp_anchor = _anchor_cell_path(char_id)
            _ej = _vlm_exp.judge_cell(
                out,
                anchor_path=_exp_anchor if os.path.isfile(_exp_anchor) else None,
                angle=angle,
                log_fn=log_fn,
            )
            _vlm_exp.release()
            if _ej.get('flagged'):
                if log_fn:
                    log_fn(
                        f'Expansion {i + 1}/{len(angles)} dropped — VLM '
                        f'[{_ej.get("tier")}]: {(_ej.get("defect") or "defect")[:80]}',
                    )
                continue

        stem = f'expansion_{i:03d}'
        dest_png = os.path.join(dataset_dir, f'{stem}.png')
        shutil.copy2(out, dest_png)
        # 03d migration: remove a stale 02d pair for the same index so the
        # prefix listings never see the tile twice.
        for _lext in ('.png', '.txt'):
            _lp = os.path.join(dataset_dir, f'expansion_{i:02d}{_lext}')
            if os.path.isfile(_lp):
                try:
                    os.remove(_lp)
                except OSError as _exc:
                    _zyg_log.warning(
                        'stale 02d expansion file %s not removed, listings may see the tile twice: %s', _lp, _exc
                    )
        caption = f'{trigger}, {ident}, {angle}, {style_extra}'
        with open(os.path.join(dataset_dir, f'{stem}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(caption.strip() + '\n')
        kept.append(dest_png)
        if log_fn:
            log_fn(
                f'Expansion {i + 1}/{len(angles)} kept ({backend}, score {score if score is not None else "n/a"})',
            )

    _steps.step_expansion_manifest(
        char_id,
        total=len(angles),
        kept=kept,
        exp_dir=exp_dir,
        lora_path=lora_path,
        log_fn=log_fn,
    )
    return kept
