# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet finalisation, the expansion manifest and the regen circuit breaker.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 2296-2519).
"""

from __future__ import annotations

import os
from typing import Callable
from zyg_workflows import contact_sheet_pipeline as _csp
from zyg_workflows import provenance_seal as _seal
from .cell_plan import CellRun

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_finalize_sheet(
    run: CellRun,
    *,
    out_path: str,
    aset: str,
    total: int,
    gutter: int,
    cell_paths: list[str],
    cell_angles: list[str],
    anchor_face: str | None,
    cell_plan: dict,
    failures: int,
    pose_ready: bool,
    on_cell_progress: Callable[[int, int], None] | None,
) -> str | None:
    """Minimum-cell floor, preview page stitching and the manifest write."""
    # Fractional floor (2026-08-09): the fixed total-6 default collapsed to
    # nothing at corpus scale (234/240 is a stricter bar than 42/48). Default
    # 85% of the plan with a 12-cell absolute minimum; the absolute
    # ZYG_CONTACT_SHEET_MIN_CELLS override still wins when set.
    import math as _math_mo

    _min_ok_frac = float(os.environ.get('ZYG_SHEET_MIN_OK_FRAC', '0.85'))
    _min_ok_default = max(12, int(_math_mo.ceil(_min_ok_frac * total)))
    min_ok = int(os.environ.get('ZYG_CONTACT_SHEET_MIN_CELLS', str(_min_ok_default)))
    min_ok = max(1, min(min_ok, total))
    if len(cell_paths) < min_ok:
        if run.log_fn:
            run.log_fn(
                f'Per-cell sheet: only {len(cell_paths)}/{total} cells OK ({failures} failed, need {min_ok})',
            )
        return None

    # Approval preview: stitch pages of 6 at uniform preview size. Preview ONLY —
    # tiles come from the per-cell files, never from slicing these sheets.
    page_paths: list[str] = []
    parts = 'abcdefghijklmnopqrstuvwxyz'
    for pi in range(0, len(cell_paths), 6):
        page_cells = cell_paths[pi : pi + 6]
        part = parts[pi // 6] if pi // 6 < len(parts) else f'p{pi // 6}'
        page_path = _csp.master_sheet_path_part(run.char_id, part)
        _csp._stitch_cell_images(
            page_cells,
            page_path,
            2,
            3,
            _csp.EXPORT_CELL_W,
            _csp.EXPORT_CELL_H,
            gutter,
            run.log_fn,
        )
        page_paths.append(page_path)
    _csp._composite_sheet_stack(page_paths, out_path, log_fn=run.log_fn)
    _seal.seal(out_path, pipeline='contact_sheet', run_id=run.char_id, log_fn=run.log_fn)

    _csp.write_manifest(
        run.char_id,
        rows=2,
        cols=3,
        gutter=gutter,
        cell_w=_csp.EXPORT_CELL_W,
        cell_h=_csp.EXPORT_CELL_H,
        sheet_path=out_path,
        extra={
            'generation_mode': 'per_cell_ipa',
            'angle_set': aset,
            'total_tiles': len(cell_paths),
            'cell_paths': cell_paths,
            'cell_angles': cell_angles,
            'identity_anchor_face': anchor_face,
            'sheet_seed': run.base_seed,
            'pose_maps_used': pose_ready,
            'export_cell_width': _csp.EXPORT_CELL_W,
            'export_cell_height': _csp.EXPORT_CELL_H,
            'anchor_family': run.anchor_family,
            'cell_plan': cell_plan,
        },
    )
    if run.progress_job is not None:
        run.progress_job['sheet_substage'] = 'sheet_complete'
        run.progress_job['sheet_cells_done'] = len(cell_paths)
    if on_cell_progress:
        on_cell_progress(len(cell_paths), total)
    if run.log_fn:
        run.log_fn(
            f'Per-cell contact sheet ready — {len(cell_paths)}/{total} cells, '
            f'{len(page_paths)} preview pages stitched for review',
        )
    return out_path


def step_expansion_manifest(
    char_id: str,
    *,
    total: int,
    kept: list[str],
    exp_dir: str,
    lora_path: str,
    log_fn: Callable[[str], None] | None,
) -> None:
    """Re-write the manifest with the flywheel expansion tally."""
    m = _csp.load_manifest(char_id) or {}
    extra = {
        k: m[k]
        for k in m
        if k
        not in (
            'char_id',
            'pipeline',
            'rows',
            'cols',
            'gutter_px',
            'cell_width',
            'cell_height',
            'sheet_path',
            'approved',
            'approved_at',
            'tiles',
            'updated_at',
        )
    }
    extra['flywheel'] = {
        'expansion_total': total,
        'expansion_kept': len(kept),
        'expansion_dir': exp_dir,
        'lora_v1': lora_path,
        'expanded_at': _csp._ams_iso(),
    }
    _csp.write_manifest(
        char_id,
        rows=int(m.get('rows') or _csp.DEFAULT_ROWS),
        cols=int(m.get('cols') or _csp.DEFAULT_COLS),
        gutter=int(m.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(m.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(m.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=m.get('sheet_path') or _csp.master_sheet_path(char_id),
        approved=bool(m.get('approved')),
        tiles=m.get('tiles') or [],
        extra=extra,
    )
    if log_fn:
        log_fn(f'Angle expansion complete — {len(kept)}/{total} kept for LoRA v2')


def scaled_budget(env_name: str, base_default: int, qc_scale: float) -> int:
    """QC budget scaling (2026-08-09).

    Corpus sheets run 70-240 cells, so every absolute per-run QC budget keeps
    its calibrated value at 48 cells and grows proportionally with
    cell_count/48. An env var that is explicitly SET stays an absolute
    override, exactly as before.
    """
    raw = os.environ.get(env_name, '').strip()
    if raw:
        try:
            return int(raw)
        except ValueError as _exc:
            _zyg_log.warning('%s=%r is not an integer, using the scaled default: %s', env_name, raw, _exc)
    import math as _math_qb

    return int(_math_qb.ceil(base_default * qc_scale))


def needs_regen(t: dict, fail_class: tuple) -> bool:
    """True when a tile must go through the regen ladder.

    ANY face-expected tile with no detectable face is broken, not a detector
    limit — the 2026-07-16 Kira Dunn audit showed the heavy ghost-mottled cells
    all come back no_face, and the old frontal-only rule let 5 of them
    (oblique/profile/pitch) train untouched.
    """
    if t.get('vlm_flag'):
        return True
    v = t.get('identity_verdict')
    if v in fail_class:
        return True
    return v == 'no_face' and t.get('identity_visibility') != 'back'


def step_regen_circuit_breaker(
    char_id: str,
    tiles: list[dict],
    allow_regen: bool,
    log_fn: Callable[[str], None] | None,
) -> None:
    """REGEN CIRCUIT BREAKER.

    Regens edit the SAME anchor, so if the anchor is broken (non-photographic
    -> ArcFace can't read it), every regen scores ~0 and 44 minutes are wasted
    producing nothing usable (2026-07-12). If a large fraction of face-expected
    cells returned no_face, the anchor itself is the problem — skip the doomed
    regen loop and park for review instead of grinding.
    """
    _face_expected = [
        t
        for t in tiles
        if t.get('identity_visibility') not in ('back',) and t.get('identity_verdict') != 'no_face_expected'
    ]
    _no_face_n = sum(1 for t in _face_expected if t.get('identity_verdict') == 'no_face')
    _no_face_frac = (_no_face_n / len(_face_expected)) if _face_expected else 0.0
    # 0.30: the 2026-07-12 collapse measured 14/41 = 0.341, so a 0.35 threshold
    # would NOT have fired on the very incident it was written for.
    _breaker = float(os.environ.get('ZYG_IDQC_NOFACE_ABORT_FRAC', '0.30'))
    if allow_regen and _face_expected and _no_face_frac >= _breaker:
        if log_fn:
            log_fn(
                f'Identity QC CIRCUIT BREAKER: {_no_face_n}/{len(_face_expected)} '
                f'face-expected cells are no_face ({_no_face_frac:.0%} ≥ {_breaker:.0%}) — '
                f'the anchor is likely non-photographic; parking the run '
                f'(set ZYG_IDQC_NOFACE_ABORT_FRAC=1 to disable)',
            )
        # Raise PipelinePaused so the run actually UNWINDS to the GUI's paused
        # handler. The old pause()+return let the pipeline continue into caption
        # writing and multi-hour LoRA training on the broken dataset (the
        # returned summary lacked the nested 'counts' key the QC safety valve
        # reads, so that valve was silently bypassed too).
        from zyg_workflows import pipeline_control as _pc_cb

        raise _pc_cb.PipelinePaused(
            char_id,
            f'identity QC: {_no_face_frac:.0%} of cells undetectable (broken anchor)',
        )
