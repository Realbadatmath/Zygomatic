# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-cell generation steps: identity locks, prompts, kwargs, crops, cell-00 gates.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 1940-2295).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from zyg_workflows import contact_sheet_pipeline as _csp
from .anchor_ctx import AnchorCtx
from .anchor_structure_gates import run_anchor_gates
from .cell_plan import CellRun

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_identity_locks(log_fn: Callable[[str], None] | None) -> tuple[bool, bool]:
    """Lock capability probe — strongest available per cell type.

    rotation cells -> Qwen-Image-Edit camera rotation of the anchor (edit,
    cannot drift) -> PuLID -> IPA fallback chain; frontal cells -> PuLID-FLUX
    face-ID -> IPA fallback. Returns (qwen_ok, pulid_ok).
    """
    from zyg_workflows import comfy_generation_service as _cgs

    qwen_ok = False
    pulid_ok = False
    try:
        qwen_ok = _cgs.has_qwen_edit_angles()
        pulid_ok = _cgs.has_pulid_flux()
    except Exception as _exc:
        _zyg_log.warning('identity lock probe failed, assuming qwen_edit and pulid unavailable: %s', _exc)
    qwen_unet = None
    try:
        qwen_unet = _cgs.qwen_edit_unet() if qwen_ok else None
    except Exception as _exc:
        _zyg_log.debug('qwen edit unet name unavailable for the lock log line: %s', _exc)
    if log_fn:
        log_fn(
            f'Identity locks — qwen_edit: {"ON" if qwen_ok else "off"}'
            f'{f" ({qwen_unet})" if qwen_unet else ""}, '
            f'pulid: {"ON" if pulid_ok else "off"}, '
            f'ipa fallback: {"ON" if _cgs.has_flux_ipadapter() else "off"}',
        )
    return qwen_ok, pulid_ok


def step_cells_dir(char_id: str, cell_plan: dict, log_fn: Callable[[str], None] | None) -> str:
    """Create cells/ and write the plan sidecar up front.

    A paused run must leave its plan on disk so the resume can label-verify
    index reuse (the manifest only lands at the end of a successful pass).
    """
    cdir = os.path.join(_csp.contact_sheet_dir(char_id), 'cells')
    os.makedirs(cdir, exist_ok=True)
    try:
        _plan_tmp = os.path.join(cdir, 'cell_plan.json.tmp')
        with open(_plan_tmp, 'w', encoding='utf-8') as _pf:
            json.dump(cell_plan, _pf, indent=2)
        os.replace(_plan_tmp, os.path.join(cdir, 'cell_plan.json'))
    except Exception as _plan_exc:
        if log_fn:
            log_fn(f'Cell plan sidecar write failed ({_plan_exc})')
    return cdir


def step_resume_cell(run: CellRun, idx: int, total: int, angle: str, cell_path: str) -> tuple[str, str]:
    """Decide whether a prior (paused) run's cell file can be reused.

    Reuse avoids paying for the FLUX/Qwen generation again. Gated on the job's
    resume flag so a fresh run for a re-used char_id still regenerates from
    scratch. cell_00 must still yield the identity anchor. Read-side 02d
    compat: pre-migration runs left cell_NN.png files. Plan-versioned
    (2026-08-09): index reuse additionally requires the stored plan label at
    this index to MATCH — a changed plan means the file on disk is a different
    cell spec.

    Returns (verdict, cell_path) where verdict is 'regen' (generate it),
    'anchor' (cell_00 reused: fall THROUGH so the anchor gates re-run
    verify-only — run d835e071 resumed straight past them: eye colour never
    verified or synced to the bible, no profile anchor, structure check blind)
    or 'reuse' (the caller records the file and skips the cell).
    """
    _resuming = bool(run.progress_job is not None and run.progress_job.get('resume'))
    _resume_file = _csp._find_indexed_file(run.cdir, 'cell', idx)
    _label_ok = run.resume_label_ok(idx, angle) if run.resume_label_ok else True
    if _resuming and os.path.isfile(_resume_file) and not _label_ok:
        if run.log_fn:
            run.log_fn(
                f'Cell {idx + 1}/{total}: plan changed since prior run '
                f'(stored label mismatch) — regenerating instead of reusing',
            )
    elif _resuming and os.path.isfile(_resume_file):
        cell_path = _resume_file
        if idx == 0:
            if run.log_fn:
                run.log_fn(
                    f'Cell 1/{total} reused (resume) — re-running anchor gates in verify-only mode',
                )
            return 'anchor', cell_path
        return 'reuse', cell_path
    return 'regen', cell_path


def step_cell_prompt(run: CellRun, idx: int, angle: str, qwen_ok: bool) -> tuple[str, str | None]:
    """Build the cell prompt. Returns (prompt, instruction)."""
    from zyg_workflows import comfy_generation_service as _cgs

    instruction = _csp._qwen_angle_instruction(angle, run.params) if (qwen_ok and idx > 0) else None

    if idx == 0 or instruction is None:
        _fr = _csp._framing_clause(angle)
        if idx == 0:
            # Anchor is the texture source for all 47 Qwen edit cells downstream.
            # Describe the photographic capture context, not abstract aesthetics —
            # FLUX routes "shot on Canon / ISO 400" to its photography training
            # data rather than the beauty-portrait / beauty-render cluster.
            # 'amateur photo on flickr in 2007' is the Amateur Photography v6
            # realism LoRA's calibrated trigger phrase — with the LoRA at 0.80
            # it decisively anchors FLUX in the camera-roll/photography cluster
            # instead of the webtoon/illustration one (A/B-verified 2026-07-15).
            _photo_anchor = os.environ.get(
                'ZYG_CONTACT_SHEET_PHOTO_ANCHOR',
                'amateur photo on flickr in 2007, candid photograph, ',
            )
            scene = (
                f'{run.skin_clause}{_photo_anchor}single person, looking directly into camera, direct frontal gaze, '
                f'shot on Canon EF 85mm f/1.4 at f/2.8 ISO 400, '
                f'open visible skin pores, fine skin microvariation and texture, '
                f'natural skin imperfections, capillary flush under skin surface, '
                f'fine vellus facial hair, subtle natural facial asymmetry, '
                f'subtle film grain, slight depth-of-field background softness, '
                f'unretouched photograph, not airbrushed, not retouched, '
                f'neutral studio background{_fr}, {run.style_extra}, {run.trigger}'
            )
        else:
            scene = (
                f'{angle}, single person, exact same person as reference, '
                f'neutral studio background{_fr}, '
                f'{run.style_extra}, {run.trigger}'
            )
        prompt = _cgs.build_locked_prompt(scene, run.pkg, studio_preview=True)
    else:
        # Edit instruction IS the prompt for Qwen cells.
        prompt = instruction
    return prompt, instruction


def step_cell_gen_kwargs(
    run: CellRun,
    *,
    idx: int,
    total: int,
    angle: str,
    cell_w: int,
    cell_h: int,
    instruction: str | None,
    anchor_cell: str | None,
    anchor_cell_body: str | None,
    anchor_face: str | None,
    pose_ready: bool,
    pulid_ok: bool,
) -> dict | None:
    """The generate_still kwargs for one cell.

    None replaces the three inline `continue` sites (the caller counts the
    failure); the log line each one emitted is unchanged.
    """
    from zyg_workflows import comfy_generation_service as _cgs

    gen_kwargs: dict[str, Any] = {
        'width': cell_w,
        'height': cell_h,
        'steps': run.steps,
        'cfg': run.cfg,
        'seed': run.base_seed + idx * 9973,
        'character_package': run.gen_pkg,
        # Pass the anchor family THROUGH rather than collapsing everything
        # that is not qwen to 'flux'. That collapse silently relabelled a
        # klein cell as a FLUX render, which the licence pause then refused —
        # a permissively-licensed model blocked by the gate that exists to
        # stop the non-commercial one (2026-08-23).
        'char_id': run.char_id,
        'model_family': (run.anchor_family if run.anchor_family in ('qwen', 'klein') else 'flux'),
        'log_fn': run.log_fn,
        'skip_qa': True,
        'studio_preview': True,
        'prompt_finalized': True,
        'flux_guidance': run.cfg,
        'extra_negative': run.cell_neg,
        # Engage true CFG (and thus the anti-anime negative) at ~18% of the
        # schedule on flux XlabsSampler cells — A/B-validated for the contact
        # sheet; other app flux callers keep legacy inert-negative behavior.
        'cfg_start_frac': float(os.environ.get('ZYG_FLUX_CFG_START_FRAC', '0.18')),
    }
    if idx == 0:
        if run.anchor_family == 'qwen':
            # FLUX-exit anchor: qwen_txt2img graph, same prompt/negative
            # machinery; the anchor gates below are image-side, unchanged.
            gen_kwargs['force_workflow'] = 'qwen_txt2img'
            gen_kwargs['cfg'] = run.anchor_cfg
            gen_kwargs.pop('flux_guidance', None)
            # The realism LoRA is FLUX-arch — never staged on the qwen base.
        elif run.anchor_family == 'klein':
            # FLUX.2 klein-4B anchor (2026-08-25). The base is undistilled
            # and wants real CFG in the 4-5 band; anchor_cfg (2.6) is a
            # FLUX-guidance-era number, so it is a floor here, not the value.
            gen_kwargs['force_workflow'] = 'klein_txt2img'
            gen_kwargs['cfg'] = max(run.anchor_cfg, float(os.environ.get('ZYG_KLEIN_ANCHOR_CFG', '4.0')))
            gen_kwargs.pop('flux_guidance', None)
            gen_kwargs.pop('force_unet', None)
        else:
            gen_kwargs['force_workflow'] = 'flux_txt2img'
            gen_kwargs['force_unet'] = run.unet
            gen_kwargs['cfg'] = run.anchor_cfg
            gen_kwargs['flux_guidance'] = run.anchor_cfg
            if run.realism_lora_path and os.path.isfile(run.realism_lora_path):
                gen_kwargs['style_lora_path'] = run.realism_lora_path
                gen_kwargs['style_lora_scale'] = run.realism_lora_scale
    elif instruction is not None:
        # Rotation cell: edit the FULL anchor cell (not the face crop).
        # Full-body cells reference the body anchor (complete outfit incl.
        # shoes); every head/close-up/medium cell references the HEAD anchor
        # so its face arrives at the edit model at ~700px, not ~100px.
        _edit_ref = (
            anchor_cell_body
            if (_csp._is_full_body_angle(angle) and anchor_cell_body and os.path.isfile(anchor_cell_body))
            else anchor_cell
        )
        if not _edit_ref or not os.path.isfile(_edit_ref):
            if run.log_fn:
                run.log_fn(f'Cell {idx + 1}/{total} skipped — no anchor cell for edit')
            return None
        gen_kwargs['reference_image'] = _edit_ref
        gen_kwargs['force_workflow'] = 'qwen_edit_angle'
        _csp._strip_detailer_for_steep(gen_kwargs, angle)
    else:
        if run.anchor_family in ('qwen', 'klein'):
            # The PuLID/pose-IPA/IPA fallbacks are ALL FLUX graphs. With a
            # qwen or klein anchor they must never fire — the corpus plan builder
            # guarantees every non-anchor label is qwen_edit-mappable, so
            # landing here means an unmappable label slipped through.
            # Exclude the cell loudly instead of silently submitting a
            # licence-paused FLUX graph (2026-08-09).
            if run.log_fn:
                run.log_fn(
                    f'Cell {idx + 1}/{total} EXCLUDED — label has no '
                    f'qwen_edit instruction and anchor_family=qwen forbids '
                    f'the FLUX PuLID/IPA fallback ({angle[:60]})',
                )
            return None
        if not anchor_face or not os.path.isfile(anchor_face):
            if run.log_fn:
                run.log_fn(f'Cell {idx + 1}/{total} skipped — no identity anchor from cell 00')
            return None
        gen_kwargs['reference_image'] = anchor_face
        gen_kwargs['force_unet'] = run.unet
        pose_path = _cgs.pose_map_path(idx) if pose_ready else ''
        if pulid_ok:
            gen_kwargs['force_workflow'] = 'flux_pulid_cell'
        elif pose_ready and os.path.isfile(pose_path):
            gen_kwargs['pose_image'] = pose_path
            gen_kwargs['force_workflow'] = 'flux_pose_ipa_cell'
        else:
            gen_kwargs['force_workflow'] = 'flux_character_ipadapter'
    return gen_kwargs


def step_closeup_crop(
    run: CellRun,
    *,
    idx: int,
    total: int,
    angle: str,
    cell_w: int,
    cell_h: int,
    cell_path: str,
    anchor_cell: str | None,
    cell_paths: list[str],
    cell_angles: list[str],
    cell0_reused: bool,
) -> tuple[bool, str] | None:
    """CLOSE-UP BY CROP (2026-07-21).

    A close-up ZOOM through Qwen stamps a shrunk double-exposure of the whole
    figure onto the skin. Produce the close-up by cropping an already-rendered
    cell of the same rotation instead — no scale change through the edit model,
    no ghost. Returns (ok, backend) when the crop was produced, else None so
    the caller falls through to the normal Qwen path.
    """
    _closeup_toggle = os.environ.get('ZYG_CLOSEUP_CROP', '1').strip().lower() not in ('0', 'false', 'no', 'off')
    _cu_light = _csp._lighting_grade_kind(angle)
    _cu_is_relight = _csp._is_relight_angle(angle)
    if (
        _closeup_toggle
        and idx > 0
        and not (idx == 0 and cell0_reused)
        and (_csp._is_closeup_zoom_angle(angle) or _cu_is_relight)
    ):
        _cu_src = _csp._closeup_source_cell(angle, anchor_cell, cell_paths, cell_angles)
        # Fill-frame/extreme close-ups crop tight; relight tiles keep a
        # looser head-and-shoulders framing (they are 'front view' shots).
        _cu_tight = (not _cu_is_relight) and any(k in angle.lower() for k in ('fill frame', 'extreme close'))
        if (
            _cu_src
            and os.path.isfile(_cu_src)
            and _csp._closeup_crop_from(
                _cu_src,
                cell_w,
                cell_h,
                cell_path,
                tight=_cu_tight,
                lighting=_cu_light,
                log_fn=run.log_fn,
            )
        ):
            ok, backend = True, ('relight-crop' if _cu_is_relight else 'closeup-crop')
            if run.log_fn:
                _why = f'relight ({_cu_light}) by CROP+grade' if _cu_is_relight else 'close-up by CROP'
                run.log_fn(
                    f'Cell {idx + 1}/{total}: {_why} from {os.path.basename(_cu_src)} — no Qwen re-synthesis, no ghost',
                )
            return ok, backend
    return None


def run_cell0_gates(
    run: CellRun,
    *,
    cell_path: str,
    gen_kwargs: dict,
    prompt: str,
    cell0_reused: bool,
    qwen_ok: bool,
    body_anchor_path: str,
    anchor_cell_body: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Every cell-00 gate, in the order they had inline.

    Returns (anchor_cell, anchor_face, anchor_cell_body).
    """
    ctx = AnchorCtx(
        char_id=run.char_id,
        params=run.params,
        log_fn=run.log_fn,
        cell_path=cell_path,
        anchor_path=_csp.identity_anchor_face_path(run.char_id),
        gen_kwargs=gen_kwargs,
        prompt=prompt,
        pkg=run.pkg,
        progress_job=run.progress_job,
        anchor_family=run.anchor_family,
        cell0_reused=cell0_reused,
        render_style=run.render_style,
        realism_lora_path=run.realism_lora_path,
        realism_lora_scale=run.realism_lora_scale,
        anchor_skin=run.anchor_skin,
        anchor_cfg=run.anchor_cfg,
        dark_retry_cfg=run.dark_retry_cfg,
        qwen_ok=qwen_ok,
        base_seed=run.base_seed,
        unet=run.unet,
        skin_clause=run.skin_clause,
        style_extra=run.style_extra,
        trigger=run.trigger,
        body_anchor_path=body_anchor_path,
        anchor_cell_body=anchor_cell_body,
    )
    run_anchor_gates(ctx)
    return ctx.anchor_cell, ctx.anchor_face, ctx.anchor_cell_body
