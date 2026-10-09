# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pose-locked contact sheet generator.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 2127-2423).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CONTACT_SHEET_ANGLE_LABELS,
    DEFAULT_GUTTER,
    EXPORT_CELL_H,
    EXPORT_CELL_W,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    contact_sheet_dir,
    identity_anchor_face_path,
    trigger_token_for,
    write_manifest,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import (
    _build_sheet_character_package,
    _extract_sheet_identity_anchor,
    caption_style_description,
)
from zyg_workflows.contact_sheet_pipeline.stitch import _stitch_cell_images


def _generate_pose_locked_contact_sheet(
    char_id: str,
    params: dict,
    out_path: str,
    log_fn: Callable[[str], None] | None,
    *,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
    progress_job: dict | None = None,
) -> str | None:
    """
    Perfect-consistency stack: cell 00 txt2img anchor, cells 01+ FLUX + Union pose CN + IP-Adapter.
    No per-cell img2img — identity from cell 00 reference, structure from static OpenPose maps.
    """
    from zyg_workflows import comfy_generation_service as _cgs

    if not _cgs.pose_locked_stack_ready():
        if log_fn:
            log_fn('Pose-locked stack unavailable — need IP-Adapter, Union ControlNet, and pose assets')
        return None

    mf = (model_family or 'flux').strip().lower()
    if mf != 'flux':
        if log_fn:
            log_fn('Pose-locked contact sheet requires FLUX')
        return None

    cell_w = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_CELL_W', str(EXPORT_CELL_W)))
    cell_h = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_CELL_H', str(EXPORT_CELL_H)))
    angles = list(CONTACT_SHEET_ANGLE_LABELS)
    max_cells = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_MAX_CELLS', '0') or '0')
    if max_cells > 0:
        angles = angles[:max_cells]
    # Static pose library may be smaller than the angle set (24 maps vs 48
    # extended angles) — cap so min_ok math stays on genuinely reachable cells.
    n_maps = 0
    while n_maps < len(angles) and os.path.isfile(_cgs.pose_map_path(n_maps)):
        n_maps += 1
    if n_maps < len(angles):
        if log_fn:
            log_fn(
                f'Pose-locked mode: {n_maps} pose maps available — capping {len(angles)} angles to {n_maps}',
            )
        angles = angles[:n_maps]
    if not angles:
        if log_fn:
            log_fn('Pose-locked mode: no pose maps found')
        return None
    total = len(angles)
    preview_rows = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_PREVIEW_ROWS', '4'))
    preview_cols = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_PREVIEW_COLS', '6'))
    gutter = DEFAULT_GUTTER

    if progress_job is not None:
        progress_job['dual_sheet'] = False
        progress_job['sheet_count'] = 1
        progress_job['sheet_cells_total'] = total
        progress_job['generation_mode'] = 'pose_locked_ipa_openpose'

    if log_fn:
        log_fn(
            f'Pose-locked mode — {total} cells @ {cell_w}×{cell_h} '
            f'(FLUX + Union pose ControlNet + IP-Adapter, no img2img chain)',
        )

    try:
        from zyg_workflows import _comfy_client as _cc

        _cc.wait_for_free_vram_gb(
            min_free_gb=22.0,
            timeout_s=int(os.environ.get('ZYG_CONTACT_SHEET_VRAM_WAIT_S', '45')),
            poll_s=5.0,
            try_evict=True,
            log_fn=log_fn,
        )
    except Exception as exc:
        if log_fn:
            log_fn(f'VRAM wait skipped ({exc})')

    pkg = _build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    gen_pkg = dict(pkg) if pkg else {}
    cond = gen_pkg.setdefault('conditioning', {})
    cond['hand_detail_pass'] = False
    cond['instantid_enabled'] = os.environ.get('ZYG_CONTACT_SHEET_POSE_USE_INSTANTID', '1').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    # Pose-locked tuning: stronger identity & pose constraints by default.
    try:
        cond['ipadapter_scale'] = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_IPA_SCALE', '0.90'))
    except Exception:
        cond['ipadapter_scale'] = 0.90

    trigger = trigger_token_for(char_id)
    style_extra = caption_style_description((params or {}).get('style', 'photorealistic'))
    sheet_neg = (
        'blurry, low quality, multiple different people, collage of strangers, '
        'duplicate panels, inconsistent identity, wrong pose, deformed body, '
        'lingerie, underwear, bra, bikini, nude, topless, cleavage, '
        'strapless, bare shoulders, see-through dress'
    )
    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))
    seed = int(uuid.uuid4().int % (2**31))
    unet = os.environ.get('ZYG_CONTACT_SHEET_UNET', 'flux1-dev.safetensors')

    tdir = os.path.join(contact_sheet_dir(char_id), 'cells')
    os.makedirs(tdir, exist_ok=True)
    cell_paths: list[str] = []
    ipa_ref: str | None = None
    ipa_ref_face: str | None = None
    use_face_ref = os.environ.get('ZYG_CONTACT_SHEET_POSE_IPA_FACE_REF', '1').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    failures = 0

    for idx in range(total):
        angle = angles[idx]
        cell_path = os.path.join(tdir, f'cell_{idx:03d}.png')
        pose_path = _cgs.pose_map_path(idx)
        if not os.path.isfile(pose_path):
            if log_fn:
                log_fn(f'Cell {idx + 1}/{total} skipped — missing pose map {pose_path}')
            failures += 1
            continue

        if idx == 0:
            # No reference exists for the anchor; keep prompt clean to avoid
            # contradictory "same as reference" conditioning.
            scene = f'{angle}, character reference portrait, neutral studio background, {style_extra}, {trigger}'
        else:
            scene = (
                f'{angle}, exact same person and outfit as reference, character reference portrait, '
                f'neutral studio background, {style_extra}, {trigger}'
            )
        prompt = _cgs.build_locked_prompt(scene, pkg, studio_preview=True)

        if progress_job is not None:
            progress_job['sheet_substage'] = f'cell_{idx:03d}_pose_ipa'
            progress_job['sheet_cells_done'] = idx

        if log_fn:
            log_fn(f'Cell {idx + 1}/{total}: {angle[:72]}…')

        # Vary RNG per cell to prevent duplicates while remaining reproducible.
        cell_seed = seed + idx * 9973
        gen_kwargs: dict[str, Any] = {
            'width': cell_w,
            'height': cell_h,
            'steps': steps,
            'cfg': cfg,
            'seed': cell_seed,
            'character_package': gen_pkg,
            'char_id': char_id,
            'model_family': 'flux',
            'log_fn': log_fn,
            'skip_qa': True,
            'studio_preview': True,
            'prompt_finalized': True,
            'force_unet': unet,
            'flux_guidance': cfg,
            'extra_negative': sheet_neg,
            'pose_image': pose_path,
        }

        if idx == 0:
            gen_kwargs['force_workflow'] = 'flux_txt2img'
        else:
            ref_img = ipa_ref_face if use_face_ref and ipa_ref_face and os.path.isfile(ipa_ref_face) else ipa_ref
            if not ref_img or not os.path.isfile(ref_img):
                failures += 1
                if log_fn:
                    log_fn(f'Cell {idx + 1}/{total} skipped — no identity reference from cell 00')
                continue
            gen_kwargs['reference_image'] = ref_img
            # For best consistency: drive from anchor via img2img latent + identity lock + pose.
            use_i2i = os.environ.get('ZYG_CONTACT_SHEET_POSE_USE_I2I', '1').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
            if use_i2i and ipa_ref and os.path.isfile(ipa_ref):
                gen_kwargs['init_image'] = ipa_ref
                gen_kwargs['denoise'] = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_I2I_DENOISE', '0.35'))
                gen_kwargs['force_workflow'] = 'flux_pose_ipa_i2i_cell'
            else:
                gen_kwargs['force_workflow'] = (
                    'flux_pose_instantid_cell' if cond.get('instantid_enabled') else 'flux_pose_ipa_cell'
                )

        ok, backend = _cgs.generate_still(cell_path, prompt, **gen_kwargs)
        if not ok or not os.path.isfile(cell_path):
            failures += 1
            if log_fn:
                log_fn(f'Cell {idx + 1}/{total} failed ({backend})')
            try:
                from zyg_workflows import _comfy_client as _cc

                # XLabs IP-Adapter patches FLUX modules; Comfy can crash during unload_all_models().
                # Keep models loaded; only request executor/memory cleanup.
                _cc.free_vram(unload_models=False, free_memory=True)
            except Exception as _exc:
                _zyg_log.debug('vram cleanup after the failed cell skipped: %s', _exc)
            continue

        cell_paths.append(cell_path)
        if ipa_ref is None:
            ipa_ref = cell_path
            anchor_path = identity_anchor_face_path(char_id)
            _extract_sheet_identity_anchor(
                cell_path,
                anchor_path,
                rows=1,
                cols=1,
                gutter=0,
                log_fn=log_fn,
            )
            ipa_ref_face = anchor_path if os.path.isfile(anchor_path) else None
            if log_fn:
                log_fn(
                    f'Cell 00 anchor — IP-Adapter reference {os.path.basename(cell_path)} (seed {cell_seed})',
                )

        if on_cell_progress:
            on_cell_progress(len(cell_paths), total)
        if log_fn:
            log_fn(f'Cell {idx + 1}/{total} OK ({backend})')

        try:
            from zyg_workflows import _comfy_client as _cc

            _cc.free_vram(unload_models=False, free_memory=True)
        except Exception as _exc:
            _zyg_log.debug('vram cleanup after the cell skipped: %s', _exc)

    min_ok = int(os.environ.get('ZYG_CONTACT_SHEET_MIN_CELLS', str(max(12, total - 4))))
    min_ok = max(1, min(min_ok, total))
    if len(cell_paths) < min_ok:
        if log_fn:
            log_fn(
                f'Pose-locked sheet: only {len(cell_paths)}/{total} cells OK ({failures} failed, need {min_ok})',
            )
        return None

    while len(cell_paths) < total:
        cell_paths.append(cell_paths[-1])

    stitched = _stitch_cell_images(
        cell_paths,
        out_path,
        preview_rows,
        preview_cols,
        cell_w,
        cell_h,
        gutter,
        log_fn,
    )
    if not stitched:
        return None

    write_manifest(
        char_id,
        rows=preview_rows,
        cols=preview_cols,
        gutter=gutter,
        cell_w=cell_w,
        cell_h=cell_h,
        sheet_path=out_path,
        extra={
            'generation_mode': 'pose_locked_ipa_openpose',
            'total_tiles': total,
            'pose_dir': _cgs._POSE_DIR,
            'ipa_reference_cell': ipa_ref,
            'identity_anchor_face': identity_anchor_face_path(char_id),
            'sheet_seed': seed,
            'export_cell_width': cell_w,
            'export_cell_height': cell_h,
            'cell_paths': cell_paths,
        },
    )
    if progress_job is not None:
        progress_job['sheet_substage'] = 'sheet_complete'
        progress_job['sheet_cells_done'] = total
        progress_job['generation_mode'] = 'pose_locked_ipa_openpose'
    if on_cell_progress:
        on_cell_progress(total, total)
    if log_fn:
        log_fn(f'Pose-locked contact ready — {len(cell_paths)} cells stitched for review')
    return out_path
