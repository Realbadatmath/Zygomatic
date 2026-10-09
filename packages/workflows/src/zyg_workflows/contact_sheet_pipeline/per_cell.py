# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-cell contact sheet generator (one render per angle).

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 2945-3208).
"""

from __future__ import annotations

import os
import uuid
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CONTACT_SHEET_BEST_OF,
    DEFAULT_GUTTER,
    _normalize_angle_set,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _resolve_anchor_family,
    identity_profile_anchor_face_path,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import _cell_size_for_angle
from zyg_workflows.contact_sheet_pipeline.sheet_canvas import _generate_dual_contact_sheets
from zyg_workflows.contact_sheet_pipeline.cell_regen import _generate_cell_best_of


def _generate_per_cell_contact_sheet(
    char_id: str,
    params: dict,
    out_path: str,
    log_fn: Callable[[str], None] | None,
    *,
    model_family: str = 'flux',
    on_cell_progress: Callable[[int, int], None] | None = None,
    progress_job: dict | None = None,
    angle_set: str | None = None,
) -> str | None:
    """
    Per-cell generation — one image per angle at final training size.

    This replaces grid slicing as the tile source: the Rhea Kim forensics
    showed FLUX ignores both grid geometry (drew 2×5 / irregular collages for
    a 2×3 prompt) and per-panel angle instructions in single-canvas mode, so
    sliced tiles held half-people and every angle label was fiction. Here each
    angle is its own generation (pose ControlNet enforcing the pose when a map
    exists, IP-Adapter carrying identity from a face-detected anchor), and the
    stitched sheets exist only as an approval preview — never as a crop source.
    """
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import contact_sheet_pipeline_steps as _steps

    mf = (model_family or 'flux').strip().lower()
    if mf not in ('flux', 'qwen', 'klein'):
        if log_fn:
            log_fn('Per-cell contact sheet requires FLUX, QWEN or KLEIN')
        return None

    aset = _normalize_angle_set(angle_set)
    # Anchor family for the FLUX exit (2026-08-09): mf 'qwen' forces the qwen
    # anchor; otherwise job/env selection with 'auto' = qwen while FLUX renders
    # are licence-paused. All anchor GATES (style/texture/skin-luminance/dedup/
    # VLM/structure) operate on the image and are family-agnostic.
    # mf 'klein' (2026-08-25) forces the klein anchor the same way qwen does.
    # Both keep their rotation cells on the QWEN EDIT graph (Apache-2.0, the
    # dx8152 multi-angle LoRA) — klein's own edit graph has no angle adapter.
    _anchor_family = mf if mf in ('qwen', 'klein') else _resolve_anchor_family(progress_job)
    _engine = _steps.step_engine_gate(aset, _anchor_family, log_fn)
    if _engine == 'abort':
        return None
    if _engine == 'dual':
        return _generate_dual_contact_sheets(
            char_id,
            params,
            out_path,
            log_fn,
            model_family=mf,
            on_cell_progress=on_cell_progress,
            progress_job=progress_job,
            angle_set=angle_set,
        )

    _plan = _steps.step_build_cell_plan(char_id, aset, progress_job, log_fn)
    if _plan is None:
        return None
    angles, cell_plan, _resume_label_ok = _plan
    total = len(angles)

    gutter = DEFAULT_GUTTER

    pose_ready = False
    try:
        pose_ready = _cgs.pose_locked_stack_ready()
    except Exception:
        pose_ready = False

    if progress_job is not None:
        progress_job['dual_sheet'] = False
        progress_job['sheet_count'] = (total + 5) // 6
        progress_job['sheet_cells_total'] = total
        progress_job['angle_set'] = aset
        progress_job['generation_mode'] = 'per_cell_ipa'

    if log_fn:
        log_fn(
            f'Per-cell mode ({aset}) — {total} angles, one generation per cell '
            f'(IP-Adapter face lock{", pose ControlNet where maps exist" if pose_ready else ""}, '
            f'full-body cells at 2:3)',
        )

    run = _steps.step_cell_conditioning(char_id, params, mf, _anchor_family, progress_job, log_fn)

    qwen_ok, pulid_ok = _steps.step_identity_locks(log_fn)

    cdir = _steps.step_cells_dir(char_id, cell_plan, log_fn)
    run.cdir = cdir
    run.resume_label_ok = _resume_label_ok
    cell_paths: list[str] = []
    cell_angles: list[str] = []
    anchor_face: str | None = None
    # anchor_cell stays the HEAD anchor (cell_00) for the whole run; full-body
    # cells use anchor_cell_body (complete outfit incl. shoes). The old code
    # switched anchor_cell itself to the body anchor, so ALL 47 Qwen edits
    # referenced an 832×1216 frame whose face is ~100px — facial texture could
    # not survive that path (2026-07-09 audit).
    anchor_cell: str | None = None
    anchor_cell_body: str | None = None
    # 03d era body-anchor name; resume adopts a legacy cell_00_body.png.
    _body_anchor_path = os.path.join(cdir, 'cell_000_body.png')
    _legacy_body_anchor = os.path.join(cdir, 'cell_00_body.png')
    if not os.path.isfile(_body_anchor_path) and os.path.isfile(_legacy_body_anchor):
        _body_anchor_path = _legacy_body_anchor
    failures = 0

    # Resume gate-coverage (2026-07-19): when cell_00 is reused on resume, the
    # anchor GATES still run (verify-only) — but generation/reroll/regen paths
    # are suppressed, because downstream cells already cloned this face.
    _cell0_reused = False
    for idx, angle in enumerate(angles):
        # Pause/halt gate — the per-cell loop is the longest-running phase and
        # the most likely moment to pause, so check it every cell (this loop is
        # not reached by the run_pipeline halt_check callback).
        from zyg_workflows import pipeline_control as _pc_cell

        if _pc_cell.is_paused_for_run(char_id):
            raise _pc_cell.PipelinePaused(char_id, _pc_cell.run_pause_reason(char_id))
        if _pc_cell.halt_requested():
            raise RuntimeError('Pipeline halt requested')

        cell_w, cell_h = _cell_size_for_angle(angle)
        cell_path = os.path.join(cdir, f'cell_{idx:03d}.png')
        if progress_job is not None:
            progress_job['sheet_substage'] = f'cell_{idx:03d}'
            progress_job['sheet_cells_done'] = idx

        _resume_verdict, cell_path = _steps.step_resume_cell(run, idx, total, angle, cell_path)
        if _resume_verdict == 'anchor':
            # Generation is skipped below and every gate runs verify-only (no
            # regen/reroll — replacing the anchor now would orphan the cells).
            _cell0_reused = True
        elif _resume_verdict == 'reuse':
            cell_paths.append(cell_path)
            cell_angles.append(angle)
            if on_cell_progress:
                on_cell_progress(len(cell_paths), total)
            if log_fn:
                log_fn(f'Cell {idx + 1}/{total} reused (resume)')
            continue

        if log_fn:
            log_fn(f'Cell {idx + 1}/{total}: {angle[:70]}…')

        prompt, instruction = _steps.step_cell_prompt(run, idx, angle, qwen_ok)

        gen_kwargs = _steps.step_cell_gen_kwargs(
            run,
            idx=idx,
            total=total,
            angle=angle,
            cell_w=cell_w,
            cell_h=cell_h,
            instruction=instruction,
            anchor_cell=anchor_cell,
            anchor_cell_body=anchor_cell_body,
            anchor_face=anchor_face,
            pose_ready=pose_ready,
            pulid_ok=pulid_ok,
        )
        if gen_kwargs is None:
            failures += 1
            continue

        _closeup = _steps.step_closeup_crop(
            run,
            idx=idx,
            total=total,
            angle=angle,
            cell_w=cell_w,
            cell_h=cell_h,
            cell_path=cell_path,
            anchor_cell=anchor_cell,
            cell_paths=cell_paths,
            cell_angles=cell_angles,
            cell0_reused=_cell0_reused,
        )
        if _closeup is not None:
            ok, backend = _closeup
        elif idx == 0 and _cell0_reused:
            ok, backend = True, 'reused'
        elif CONTACT_SHEET_BEST_OF > 1 and idx > 0:
            ok, backend = _generate_cell_best_of(
                cell_path,
                prompt,
                gen_kwargs,
                CONTACT_SHEET_BEST_OF,
                anchor_face,
                angle,
                log_fn=log_fn,
                profile_anchor_path=identity_profile_anchor_face_path(char_id),
            )
        else:
            ok, backend = _cgs.generate_still(cell_path, prompt, **gen_kwargs)
        if (not ok or not os.path.isfile(cell_path)) and idx == 0:
            # Cell 00 is the anchor source — a single transient failure must not
            # kill the whole run. One retry with a fresh seed.
            if log_fn:
                log_fn(f'Cell 1/{total} (anchor) failed ({backend}) — retrying with new seed')
            gen_kwargs['seed'] = int(uuid.uuid4().int % (2**31))
            ok, backend = _cgs.generate_still(cell_path, prompt, **gen_kwargs)
        if not ok or not os.path.isfile(cell_path):
            failures += 1
            if log_fn:
                log_fn(f'Cell {idx + 1}/{total} failed ({backend})')
            if idx == 0:
                if log_fn:
                    log_fn('Anchor cell failed twice — aborting per-cell run')
                return None
            try:
                from zyg_workflows import _comfy_client as _cc

                _cc.free_vram(unload_models=False, free_memory=True)
            except Exception as _exc:
                _zyg_log.debug('vram cleanup after the failed cell skipped: %s', _exc)
            continue

        cell_paths.append(cell_path)
        cell_angles.append(angle)

        if idx == 0:
            # Every cell-00 gate (style, skin luminance, cross-character dedup,
            # attribute compliance, dedup re-check, structure, profile anchor,
            # body anchor) lives in contact_sheet_pipeline_steps and runs in the
            # same order it did inline; AnchorCtx carries the state they share.
            anchor_cell, anchor_face, anchor_cell_body = _steps.run_cell0_gates(
                run,
                cell_path=cell_path,
                gen_kwargs=gen_kwargs,
                prompt=prompt,
                cell0_reused=_cell0_reused,
                qwen_ok=qwen_ok,
                body_anchor_path=_body_anchor_path,
                anchor_cell_body=anchor_cell_body,
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

    return _steps.step_finalize_sheet(
        run,
        out_path=out_path,
        aset=aset,
        total=total,
        gutter=gutter,
        cell_paths=cell_paths,
        cell_angles=cell_angles,
        anchor_face=anchor_face,
        cell_plan=cell_plan,
        failures=failures,
        pose_ready=pose_ready,
        on_cell_progress=on_cell_progress,
    )
