# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""generate_contact_sheet — the mode dispatcher over the sheet generators.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 1277-1463).
"""

from __future__ import annotations

import os
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_COLS,
    DEFAULT_GUTTER,
    DEFAULT_ROWS,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _resolve_sheet_mode,
    contact_sheet_dir,
    master_sheet_path,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import (
    _comfy_availability,
    _sdxl_per_cell_enabled,
)
from zyg_workflows.contact_sheet_pipeline.stitch import _generate_sheet_mock
from zyg_workflows.contact_sheet_pipeline.sheet_canvas import (
    _generate_dual_contact_sheets,
    _generate_sheet_comfy_cells,
    _generate_sheet_single_canvas,
)
from zyg_workflows.contact_sheet_pipeline.pose_locked import _generate_pose_locked_contact_sheet
from zyg_workflows.contact_sheet_pipeline.per_cell import _generate_per_cell_contact_sheet


def generate_contact_sheet(
    char_id: str,
    params: dict,
    *,
    rows: int = DEFAULT_ROWS,
    cols: int = DEFAULT_COLS,
    cell_w: int = DEFAULT_CELL_W,
    cell_h: int = DEFAULT_CELL_H,
    gutter: int = DEFAULT_GUTTER,
    log_fn: Callable[[str], None] | None = None,
    mode: str | None = None,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
    progress_job: dict | None = None,
    angle_set: str | None = None,
) -> str:
    """
    Build contact_sheet_master.png. Returns path to master image.

    mode: ``mock`` | ``cells`` | ``single_canvas`` | ``dual_canvas`` / ``auto`` (N×2×3 + ESRGAN tiles).
    angle_set: ``extended`` (8 sheets, 48 angles — default) | ``classic`` (4 sheets, 24 angles)
               | ``corpus`` (70-240 cells, training-corpus plan — per-cell mode only)
               | ``custom`` (operator-picked angles from ``progress_job['angle_ids']``
                 — per-cell mode only; see angle_ids_to_labels).
    progress_job: optional runtime job dict — receives ``sheet_substage`` during single-canvas runs.
    """
    os.makedirs(contact_sheet_dir(char_id), exist_ok=True)
    out_path = master_sheet_path(char_id)
    mode = _resolve_sheet_mode(mode)

    if mode == 'mock':
        return _generate_sheet_mock(
            char_id,
            params,
            out_path,
            rows,
            cols,
            cell_w,
            cell_h,
            gutter,
            log_fn,
        )

    ok_avail, reason = _comfy_availability()
    if not ok_avail:
        raise RuntimeError(f'Comfy contact sheet unavailable: {reason}')

    if mode == 'per_cell':
        mf_pc = (model_family or 'flux').strip().lower()
        # 'qwen' rides the same per-cell engine as flux — the anchor renders on
        # the qwen_txt2img graph and every other cell is a qwen edit, so the
        # SDXL source-tile detour below must not capture it (2026-08-09).
        # 'klein' likewise (2026-08-23): klein_txt2img for the anchor,
        # klein_edit_angle for every other cell.
        if mf_pc not in ('flux', 'qwen', 'klein'):
            # 2026-07-26: SDXL gets the FULL 48-angle per-cell sheet by generating
            # photoreal FLUX+Qwen SOURCE tiles through the (unmodified, battle-tested)
            # per-cell generator with model_family forced to 'flux'. The scope is the
            # sheet only — run_pipeline keeps model_family='sdxl', so identity QC and
            # LoRA training (incl. the Arcane restyle) stay SDXL. Gated on the flag +
            # capabilities; ANY capability-miss / None / non-pause failure falls back
            # to the legacy 6-cell SDXL path. A user pause / pipeline halt propagates.
            from zyg_workflows import comfy_generation_service as _cgs_disp
            from zyg_workflows import pipeline_control as _pc_disp

            ok_path = None
            _caps = False
            try:
                _caps = bool(_cgs_disp.has_qwen_edit_angles() and _cgs_disp.has_flux_ipadapter())
            except Exception:
                _caps = False
            if _sdxl_per_cell_enabled() and _caps:
                if log_fn:
                    log_fn(
                        'SDXL 48-angle per-cell: generating photoreal FLUX+Qwen source '
                        'tiles (the SDXL/Arcane LoRA restyles them)'
                    )
                try:
                    ok_path = _generate_per_cell_contact_sheet(
                        char_id,
                        params,
                        out_path,
                        log_fn,
                        model_family='flux',  # scoped to sheet gen; QC/training stay sdxl
                        on_cell_progress=on_cell_progress,
                        progress_job=progress_job,
                        angle_set=angle_set,
                    )
                except _pc_disp.PipelinePaused:
                    raise
                except RuntimeError as exc:
                    if 'halt' in str(exc).lower():
                        raise
                    if log_fn:
                        log_fn(f'SDXL per-cell failed ({exc}) — falling back to 6-cell')
                    ok_path = None
                except Exception as exc:
                    if log_fn:
                        log_fn(f'SDXL per-cell error ({exc}) — falling back to 6-cell')
                    ok_path = None
            if not ok_path:
                if log_fn:
                    _why = (
                        'disabled'
                        if not _sdxl_per_cell_enabled()
                        else 'FLUX-IPA/Qwen unavailable'
                        if not _caps
                        else 'per-cell fallback'
                    )
                    log_fn(f'SDXL contact sheet: using legacy 6-cell path ({_why})')
                ok_path = _generate_sheet_comfy_cells(
                    char_id,
                    params,
                    out_path,
                    rows,
                    cols,
                    cell_w,
                    cell_h,
                    gutter,
                    log_fn,
                    model_family=model_family,
                    on_cell_progress=on_cell_progress,
                )
        else:
            ok_path = _generate_per_cell_contact_sheet(
                char_id,
                params,
                out_path,
                log_fn,
                model_family=model_family,
                on_cell_progress=on_cell_progress,
                progress_job=progress_job,
                angle_set=angle_set,
            )
    elif mode == 'cells':
        ok_path = _generate_sheet_comfy_cells(
            char_id,
            params,
            out_path,
            rows,
            cols,
            cell_w,
            cell_h,
            gutter,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
        )
    elif mode == 'pose_locked_cells':
        ok_path = _generate_pose_locked_contact_sheet(
            char_id,
            params,
            out_path,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
            progress_job=progress_job,
        )
    elif mode in ('dual_canvas', 'dual'):
        ok_path = _generate_dual_contact_sheets(
            char_id,
            params,
            out_path,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
            progress_job=progress_job,
            angle_set=angle_set,
        )
    else:
        ok_path, _seed = _generate_sheet_single_canvas(
            char_id,
            params,
            out_path,
            rows,
            cols,
            gutter,
            log_fn,
            model_family=model_family,
            on_cell_progress=on_cell_progress,
            progress_job=progress_job,
        )
    if ok_path:
        return ok_path
    raise RuntimeError('Comfy contact sheet generation failed — check Contact Sheet Generation logs')
