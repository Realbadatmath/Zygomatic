# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Single-canvas and dual contact-sheet generators (Comfy canvas path).

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 1693-2126, 3209-3346).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CANVAS_GEN_H,
    CANVAS_GEN_W,
    CONTACT_SHEET_HAND_FIXER,
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_GUTTER,
    DUAL_SHEET_COLS,
    DUAL_SHEET_ROWS,
    EXPORT_CELL_H,
    EXPORT_CELL_W,
    SHEET_B_ANCHOR_ENABLED,
    SHEET_B_IPA_SCALE,
    SHEET_B_USE_IPA,
    UPSCALE_FACTOR,
    _normalize_angle_set,
    _zyg_log,
    sheet_parts_for,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _angle_label,
    _angles_for_sheet_part,
    contact_sheet_dir,
    identity_anchor_face_path,
    master_sheet_path_part,
    native_sheet_path,
    trigger_token_for,
    write_manifest,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import (
    _build_grid_forcing_prompt,
    _build_sheet_character_package,
    _extract_sheet_identity_anchor,
    _grid_cell_size,
    _upscale_sheet_comfy,
    _upscale_sheet_pil,
    caption_style_description,
)
from zyg_workflows.contact_sheet_pipeline.stitch import (
    _composite_sheet_stack,
    _stitch_cell_images,
)


def _generate_sheet_single_canvas(
    char_id: str,
    params: dict,
    out_path: str,
    rows: int,
    cols: int,
    gutter: int,
    log_fn: Callable[[str], None] | None,
    *,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
    progress_job: dict | None = None,
    native_path: str | None = None,
    sheet_part: str = '',
    sheet_angles: list[str] | None = None,
    progress_base: int = 0,
    progress_total: int | None = None,
    substage_prefix: str = '',
    identity_anchor_face: str | None = None,
    identity_sheet_native: str | None = None,
    anchor_seed: int | None = None,
    skip_vram_wait: bool = False,
) -> tuple[str | None, int | None]:
    """
    Architecture A — Perfect Pixel: 1920×1080 FLUX txt2img → ESRGAN upscale → master PNG.

    Returns (master_path, seed_used). Sheet B may use identity_anchor_face / identity_sheet_native.
    """

    def _substage(name: str, done: int = 0, total: int = 0) -> None:
        label = f'{substage_prefix}{name}' if substage_prefix else name
        if progress_job is not None:
            progress_job['sheet_substage'] = label
            if total > 0:
                progress_job['sheet_cells_total'] = total
                progress_job['sheet_cells_done'] = done
        if on_cell_progress and total > 0:
            on_cell_progress(done, total)

    from zyg_workflows import comfy_generation_service as _cgs

    mf = (model_family or 'flux').strip().lower()
    if mf != 'flux':
        if log_fn:
            log_fn('Single-canvas sheet uses FLUX only — falling back to per-cell SDXL')
        cells_path = _generate_sheet_comfy_cells(
            char_id,
            params,
            out_path,
            rows,
            cols,
            DEFAULT_CELL_W,
            DEFAULT_CELL_H,
            gutter,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
        )
        return cells_path, None

    if skip_vram_wait:
        # A FLUX sheet just rendered in this run — the weights are resident, so
        # the 22 GB free-VRAM gate can never pass (keep-loaded Comfy) and would
        # only burn the full timeout. Generation reuses the loaded model.
        if log_fn:
            log_fn('VRAM gate skipped — FLUX already resident from previous sheet')
    else:
        try:
            from zyg_workflows import _comfy_client as _cc

            _cc.wait_for_free_vram_gb(
                min_free_gb=22.0,
                timeout_s=int(os.environ.get('ZYG_CONTACT_SHEET_VRAM_WAIT_S', '45')),
                poll_s=5.0,
                # Avoid Comfy /free unload_all_models() while XLabs IP-Adapter patches are active.
                try_evict=False,
                log_fn=log_fn,
            )
        except Exception as exc:
            if log_fn:
                log_fn(f'VRAM wait skipped ({exc})')

    import copy

    pkg = _build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    cond = gen_pkg.setdefault('conditioning', {})
    if not CONTACT_SHEET_HAND_FIXER:
        cond['hand_detail_pass'] = False
    cond['instantid_enabled'] = False

    trigger = trigger_token_for(char_id)
    native_path = native_path or native_sheet_path(char_id, sheet_part or None)
    gen_w, gen_h = CANVAS_GEN_W, CANVAS_GEN_H
    prompt = _build_grid_forcing_prompt(
        params,
        pkg,
        rows=rows,
        cols=cols,
        trigger=trigger,
        sheet_angles=sheet_angles,
        sheet_part=sheet_part,
    )

    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))
    seed = int(anchor_seed if anchor_seed is not None else (uuid.uuid4().int % (2**31)))
    unet = os.environ.get('ZYG_CONTACT_SHEET_UNET', 'flux1-dev.safetensors')

    part_lbl = f' sheet {sheet_part.upper()}' if sheet_part else ''
    sheet_cells = rows * cols
    total_cells = progress_total if progress_total is not None else sheet_cells

    force_workflow: str | None = 'flux_txt2img'
    init_image: str | None = None
    reference_image: str | None = None
    denoise: float | None = None
    stage_mode = 'txt2img'

    sp = sheet_part.lower()
    if sp and sp != 'a' and SHEET_B_ANCHOR_ENABLED and identity_anchor_face and os.path.isfile(identity_anchor_face):
        face_ref = identity_anchor_face
        if SHEET_B_USE_IPA and _cgs.has_flux_ipadapter():
            reference_image = face_ref
            cond['ipadapter_scale'] = SHEET_B_IPA_SCALE
            force_workflow = 'flux_character_ipadapter'
            stage_mode = 'ipadapter'
            if log_fn:
                log_fn(
                    f'Stage 1{part_lbl} — FLUX txt2img + IP-Adapter face lock '
                    f'({os.path.basename(face_ref)}, scale {SHEET_B_IPA_SCALE}, seed {seed})',
                )
        elif log_fn:
            log_fn(
                f'Stage 1{part_lbl} — FLUX txt2img (face anchor in prompt, seed {seed})',
            )

    if stage_mode == 'txt2img' and log_fn and sp == 'a':
        log_fn(
            f'Stage 1{part_lbl} — FLUX txt2img {gen_w}×{gen_h} ({rows}×{cols}, {unet})',
        )

    _substage('flux_native_1920', progress_base, total_cells)

    gen_kwargs: dict[str, Any] = {
        'width': gen_w,
        'height': gen_h,
        'steps': steps,
        'cfg': cfg,
        'seed': seed,
        'character_package': gen_pkg,
        'char_id': char_id,
        'model_family': 'flux',
        'log_fn': log_fn,
        'skip_qa': True,
        'studio_preview': True,
        'prompt_finalized': True,
        'force_unet': unet,
        'flux_guidance': cfg,
    }
    if force_workflow:
        gen_kwargs['force_workflow'] = force_workflow
    if init_image:
        gen_kwargs['init_image'] = init_image
    if reference_image:
        gen_kwargs['reference_image'] = reference_image
    if denoise is not None:
        gen_kwargs['denoise'] = denoise

    ok, backend = _cgs.generate_still(native_path, prompt, **gen_kwargs)
    if not ok and stage_mode == 'ipadapter':
        if log_fn:
            log_fn(
                f'Stage 1{part_lbl} IP-Adapter failed ({backend}) — '
                f'retry fresh txt2img grid (seed {seed}, no full-sheet img2img)',
            )
        gen_kwargs.pop('init_image', None)
        gen_kwargs['reference_image'] = None
        gen_kwargs.pop('denoise', None)
        gen_kwargs['force_workflow'] = 'flux_txt2img'
        ok, backend = _cgs.generate_still(native_path, prompt, **gen_kwargs)

    if not ok or not os.path.isfile(native_path):
        if log_fn:
            log_fn(f'Stage 1{part_lbl} failed ({backend})')
        return None, seed
    if log_fn:
        log_fn(f'Stage 1{part_lbl} OK ({backend}) → {native_path}')

    mid = progress_base + max(1, sheet_cells // 2)
    _substage('esrgan_upscale', mid, total_cells)
    scale = UPSCALE_FACTOR
    if log_fn:
        log_fn(f'Stage 2{part_lbl} — ESRGAN {scale}x upscale')
    try:
        _upscale_sheet_comfy(native_path, out_path, scale=scale, log_fn=log_fn)
    except Exception as exc:
        if log_fn:
            log_fn(f'Comfy ESRGAN failed ({exc}) — PIL LANCZOS fallback')
        _upscale_sheet_pil(native_path, out_path, scale=scale, log_fn=log_fn)

    if not os.path.isfile(out_path):
        return None, seed

    # 2026-08-09 restoration gate (shadow). The upscaler is a NEW place detail can
    # be invented, and until now nothing measured the image the viewer actually
    # sees — identity QC runs on tiles cropped from this sheet, and 'texture-
    # collapse' is the opposite failure (detail LOST). Measures the delta against
    # a LANCZOS upscale of the same source, which invents nothing by construction.
    # Fail-safe and non-blocking: QC breakage must never stop a sheet.
    try:
        from zyg_workflows import restoration_qc as _rq

        _rm = _rq.measure_pair(native_path, out_path)
        _rv, _rwhy = _rq.judge(_rm)
        if log_fn:
            log_fn(f'Stage 2{part_lbl} restoration_fidelity: {_rv.upper()} — {_rwhy}')
        try:
            from zyg_workflows import run_ledger as _rl

            _rl.record_gate(
                os.environ.get('ZYG_RUN_ID') or 'adhoc',
                _rq.GATE_NAME,
                _rv.upper(),
                score=_rm.get('delta'),
                tag=f'sheet{part_lbl}',
            )
        except Exception as _exc:
            _zyg_log.debug('restoration_fidelity gate not recorded in the run ledger: %s', _exc)
    except Exception as _rq_exc:
        if log_fn:
            log_fn(f'Stage 2{part_lbl} restoration_fidelity skipped ({_rq_exc})')

    from PIL import Image

    up = Image.open(out_path)
    uw, uh = up.size
    up.close()
    slice_cw, slice_ch = _grid_cell_size(uw, uh, rows, cols, gutter)
    if log_fn:
        log_fn(
            f'Stage 2{part_lbl} complete — {uw}×{uh} '
            f'(cells ~{slice_cw}×{slice_ch}, export {EXPORT_CELL_W}×{EXPORT_CELL_H})',
        )
    if not sheet_part:
        write_manifest(
            char_id,
            rows=rows,
            cols=cols,
            gutter=gutter,
            cell_w=slice_cw,
            cell_h=slice_ch,
            sheet_path=out_path,
            extra={
                'generation_mode': 'single_canvas_esrgan',
                'native_sheet_path': native_path,
                'native_width': gen_w,
                'native_height': gen_h,
                'upscaled_width': uw,
                'upscaled_height': uh,
                'upscale_factor': scale,
                'export_cell_width': EXPORT_CELL_W,
                'export_cell_height': EXPORT_CELL_H,
            },
        )
    _substage('sheet_complete', progress_base + sheet_cells, total_cells)
    return out_path, seed


def _generate_dual_contact_sheets(
    char_id: str,
    params: dict,
    composite_path: str,
    log_fn: Callable[[str], None] | None,
    *,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
    progress_job: dict | None = None,
    angle_set: str | None = None,
) -> str | None:
    """N sequential 2×3 FLUX+ESRGAN runs (24 or 48 angles) + stacked composite for approval."""
    rows, cols = DUAL_SHEET_ROWS, DUAL_SHEET_COLS
    gutter = DEFAULT_GUTTER
    aset = _normalize_angle_set(angle_set)
    if aset == 'custom':
        # Fixed 2×3 pages cannot express an arbitrary angle selection
        # (2026-09-16). Say so instead of rendering 48 angles nobody asked for.
        if log_fn:
            log_fn('Multi-sheet mode cannot render a custom angle selection (per-cell mode only) — aborting')
        return None
    parts = sheet_parts_for(aset)
    sheet_count = len(parts)
    total = rows * cols * sheet_count
    cells_per_sheet = rows * cols

    if progress_job is not None:
        progress_job['dual_sheet'] = True
        progress_job['sheet_count'] = sheet_count
        progress_job['sheet_cells_total'] = total
        progress_job['angle_set'] = aset

    if log_fn:
        log_fn(
            f'Multi-sheet mode ({aset}) — {sheet_count}×{rows}×{cols} = {total} angles '
            f'(~630px native cells, 1920×1080 → ESRGAN → {EXPORT_CELL_W}×{EXPORT_CELL_H} tiles)',
        )

    seed_a: int | None = None
    anchor_face = identity_anchor_face_path(char_id)
    master_paths: list[str] = []
    sheet_specs: list[dict] = []
    angle_offset = 0

    for si, part in enumerate(parts):
        angles = _angles_for_sheet_part(part)
        path = master_sheet_path_part(char_id, part)
        native = native_sheet_path(char_id, part)
        substage = f'{part}_'
        progress_base = si * cells_per_sheet

        ok, used_seed = _generate_sheet_single_canvas(
            char_id,
            params,
            path,
            rows,
            cols,
            gutter,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
            progress_job=progress_job,
            native_path=native,
            sheet_part=part,
            sheet_angles=angles,
            progress_base=progress_base,
            progress_total=total,
            substage_prefix=substage,
            identity_anchor_face=anchor_face if os.path.isfile(anchor_face) else None,
            identity_sheet_native=None,
            anchor_seed=seed_a,
            skip_vram_wait=(si > 0),
        )
        if not ok:
            return None

        master_paths.append(path)
        if part == 'a':
            seed_a = used_seed
            _extract_sheet_identity_anchor(
                native,
                anchor_face,
                rows=rows,
                cols=cols,
                gutter=gutter,
                log_fn=log_fn,
            )
            if log_fn and SHEET_B_ANCHOR_ENABLED:
                log_fn(
                    f'Identity anchor ready — sheets B–D use face lock + seed {seed_a} '
                    f'(txt2img grids, no full-sheet img2img)',
                )

        sheet_specs.append(
            {
                'part': part,
                'angles': angles,
                'angle_offset': angle_offset,
                'master_path': path,
                'native_path': native,
                'rows': rows,
                'cols': cols,
            }
        )
        angle_offset += len(angles)

    if progress_job is not None:
        progress_job['sheet_substage'] = 'composite_preview'

    _composite_sheet_stack(master_paths, composite_path, log_fn=log_fn)

    from PIL import Image

    up_a = Image.open(master_paths[0])
    uw, uh = up_a.size
    up_a.close()
    slice_cw, slice_ch = _grid_cell_size(uw, uh, rows, cols, gutter)
    scale = UPSCALE_FACTOR

    sheet_paths_map = {spec['part']: spec['master_path'] for spec in sheet_specs}
    sheet_paths_map['composite'] = composite_path

    write_manifest(
        char_id,
        rows=rows,
        cols=cols,
        gutter=gutter,
        cell_w=slice_cw,
        cell_h=slice_ch,
        sheet_path=composite_path,
        extra={
            'generation_mode': 'multi_canvas_esrgan',
            'dual_sheet': True,
            'angle_set': aset,
            'sheet_count': sheet_count,
            'total_tiles': total,
            'sheets': sheet_specs,
            'sheet_paths': sheet_paths_map,
            'native_width': CANVAS_GEN_W,
            'native_height': CANVAS_GEN_H,
            'upscaled_width': uw,
            'upscaled_height': uh,
            'upscale_factor': scale,
            'export_cell_width': EXPORT_CELL_W,
            'export_cell_height': EXPORT_CELL_H,
            'identity_anchor_face': anchor_face if os.path.isfile(anchor_face) else None,
            'sheet_a_seed': seed_a,
            'sheet_b_identity_lock': SHEET_B_ANCHOR_ENABLED,
        },
    )
    if progress_job is not None:
        progress_job['sheet_substage'] = 'sheet_complete'
        progress_job['sheet_cells_done'] = total
        progress_job['generation_mode'] = 'multi_canvas_esrgan'
        progress_job['sheet_b_identity_lock'] = SHEET_B_ANCHOR_ENABLED
    if on_cell_progress:
        on_cell_progress(total, total)
    if log_fn:
        log_fn(
            f'Multi-sheet contact ready — {total} angles '
            f'({sheet_count}×{rows}×{cols}, {aset} set), composite for review',
        )
    return composite_path


def _generate_sheet_comfy_cells(
    char_id: str,
    params: dict,
    out_path: str,
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    gutter: int,
    log_fn: Callable[[str], None] | None,
    *,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
) -> str | None:
    """
    Legacy: one Comfy still per grid cell (anchor img2img), then stitch.
    """
    from zyg_workflows import comfy_generation_service as _cgs

    mf = (model_family or (params or {}).get('model_family') or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl'):
        mf = 'flux'
    total = rows * cols
    if total < 1:
        return None

    try:
        from zyg_workflows import _comfy_client as _cc

        _cc.wait_for_free_vram_gb(
            min_free_gb=20.0 if mf == 'flux' else 14.0,
            timeout_s=int(os.environ.get('ZYG_CONTACT_SHEET_VRAM_WAIT_S', '45')),
            poll_s=5.0,
            try_evict=True,
            log_fn=log_fn,
        )
    except Exception as _vr_exc:
        if log_fn:
            log_fn(f'Contact sheet VRAM wait skipped ({_vr_exc})')

    pkg = _build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    trigger = trigger_token_for(char_id)
    style_extra = caption_style_description((params or {}).get('style', 'photorealistic'))
    sheet_neg_extra = (
        'blurry, low quality, multiple different people, collage of strangers, '
        'watermark, text, logo, duplicate faces, inconsistent identity'
    )

    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '20' if mf == 'flux' else '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5' if mf == 'flux' else '6.0'))
    base_seed = int(uuid.uuid4().int % (2**31))
    i2i_denoise = float(os.environ.get('ZYG_CONTACT_SHEET_I2I_DENOISE', '0.48'))

    tdir = os.path.join(contact_sheet_dir(char_id), 'cells')
    os.makedirs(tdir, exist_ok=True)
    cell_paths: list[str] = []
    anchor_ref: str | None = None
    failures = 0

    if log_fn:
        log_fn(
            f'Comfy contact sheet: {rows}×{cols} ({total} cells) via {mf.upper()} @ {cell_w}×{cell_h}px',
        )

    for idx in range(total):
        angle = _angle_label(idx)
        scene = (
            f'{angle}, character reference portrait, same person, neutral studio background, {style_extra}, {trigger}'
        )
        prompt = _cgs.build_locked_prompt(scene, pkg, studio_preview=True)
        cell_path = os.path.join(tdir, f'cell_{idx:03d}.png')
        ref = anchor_ref if idx > 0 and anchor_ref and os.path.isfile(anchor_ref) else None
        if log_fn:
            log_fn(f'Cell {idx + 1}/{total}: {angle[:72]}…')

        gen_kwargs: dict[str, Any] = {
            'width': cell_w,
            'height': cell_h,
            'steps': steps,
            'cfg': cfg,
            'seed': base_seed + idx * 9973,
            'character_package': pkg,
            'char_id': char_id,
            'model_family': mf,
            'log_fn': log_fn,
            'skip_qa': True,
            'studio_preview': True,
            'prompt_finalized': True,
            'extra_negative': sheet_neg_extra,
        }
        if ref:
            gen_kwargs['init_image'] = ref
            gen_kwargs['reference_image'] = ref
            gen_kwargs['denoise'] = i2i_denoise
            if mf == 'flux':
                gen_kwargs['force_workflow'] = 'flux_img2img'
            else:
                gen_kwargs['force_workflow'] = 'sdxl_img2img'

        ok, backend = _cgs.generate_still(cell_path, prompt, **gen_kwargs)
        if not ok or not os.path.isfile(cell_path):
            failures += 1
            if log_fn:
                log_fn(f'Cell {idx + 1}/{total} failed ({backend})')
            continue
        cell_paths.append(cell_path)
        if anchor_ref is None:
            anchor_ref = cell_path
        if on_cell_progress:
            on_cell_progress(len(cell_paths), total)
        if log_fn:
            log_fn(f'Cell {idx + 1}/{total} OK ({backend})')

    min_ok = int(os.environ.get('ZYG_CONTACT_SHEET_MIN_CELLS', str(total)))
    min_ok = max(1, min(min_ok, total))
    if len(cell_paths) < min_ok:
        if log_fn:
            log_fn(
                f'Comfy contact sheet: only {len(cell_paths)}/{total} cells succeeded '
                f'({failures} failed, need {min_ok})',
            )
        return None

    while len(cell_paths) < total:
        cell_paths.append(cell_paths[-1])

    return _stitch_cell_images(
        cell_paths,
        out_path,
        rows,
        cols,
        cell_w,
        cell_h,
        gutter,
        log_fn,
    )
