# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_pipeline steps: logging, stage order, approval and QC valves.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 3245-3609).
"""

from __future__ import annotations

import os
from typing import Callable
from zyg_workflows import contact_sheet_pipeline as _csp

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')

# ── run_pipeline steps ───────────────────────────────────────────────────────

# write_manifest() rewrites a manifest wholesale from keyword arguments, so
# every caller that only wants to flip `approved` has to carry the remaining
# keys through `extra=`. These are the keys write_manifest owns itself.
_MANIFEST_RESERVED = (
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

PIPELINE_STAGE_ORDER = [
    'sheet_generate',
    'awaiting_approval',
    'tile_crop',
    'identity_qc',
    'captions',
    'lora_training',
    'angle_expansion',
    'lora_refine',
    'done',
]


def emit_log(
    char_id: str,
    msg: str,
    level: str,
    stage: str,
    log_fn: Callable[..., None] | None,
) -> None:
    """Persist EVERY line to the untrimmed run log first, so a completed run's
    full trace survives the 50-event state cap, then fan out to whichever
    signature *log_fn* accepts."""
    _csp.append_run_log(char_id, msg, level=level)
    if not log_fn:
        return
    for caller in (
        lambda: log_fn(msg, level=level, stage=stage),
        lambda: log_fn(msg, level=level),
        lambda: log_fn(msg),
        lambda: log_fn(level, stage or '', msg),
    ):
        try:
            caller()
            return
        except TypeError as _exc:
            _zyg_log.debug('log_fn signature did not match this call shape: %s', _exc)
            continue


def skip_before(stage: str, resume_from: str) -> bool:
    """True when *stage* completed on a prior run (it precedes resume_from).

    A paused run parks at the stage it was interrupted on (job['stage']); on
    resume the worker relaunches with resume=True + resume_from=<that stage>.
    Stages strictly *before* resume_from already wrote their durable artifacts
    (cells/, tiles, manifest, LoRA), so we skip their compute and reload only
    the variables later stages need. The resume_from stage itself re-runs —
    cheap, because the per-cell / per-expansion loops skip existing files.
    """
    if not resume_from:
        return False
    try:
        return PIPELINE_STAGE_ORDER.index(stage) < PIPELINE_STAGE_ORDER.index(resume_from)
    except ValueError:
        return False


def park_for_operator(
    char_id: str,
    reason: str,
    *,
    job: dict,
    set_stage: Callable[[str], None],
    halt_check: Callable[[], None] | None,
    log: Callable[..., None],
) -> None:
    """Reset manifest approval and park at awaiting_approval until the
    operator allows (the stage hook auto-queues a Zero review card)."""
    log(reason, level='WARNING')
    m_park = _csp.load_manifest(char_id) or {}
    _park_extra = {k: m_park[k] for k in m_park if k not in _MANIFEST_RESERVED}
    _csp.write_manifest(
        char_id,
        rows=int(m_park.get('rows') or _csp.DEFAULT_ROWS),
        cols=int(m_park.get('cols') or _csp.DEFAULT_COLS),
        gutter=int(m_park.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(m_park.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(m_park.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=m_park.get('sheet_path') or _csp.master_sheet_path(char_id),
        approved=False,
        tiles=m_park.get('tiles') or [],
        extra=_park_extra,
    )
    job['approved'] = False
    set_stage('awaiting_approval')
    if not _csp.wait_for_approval(job, halt_check=halt_check):
        raise RuntimeError(f'operator approval timed out ({reason[:80]})')


def step_idqc_preflight(char_id: str, job: dict, log: Callable[..., None]) -> None:
    """Fail-CLOSED identity QC preflight (2026-07-18).

    A broken ArcFace embed worker used to degrade QC to a logged skip,
    shipping a fully unverified dataset that looked like a normal green run.
    If QC is enabled+required, prove the worker responds BEFORE burning hours
    of GPU on 48 cells.
    """
    _idqc_on = os.environ.get(
        'ZYG_CONTACT_SHEET_IDQC',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    _idqc_required = os.environ.get(
        'ZYG_CONTACT_SHEET_IDQC_REQUIRED',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _idqc_on and _idqc_required and not job.get('resume'):
        try:
            from zyg_workflows import identity_qc_service as _idqc_pre

            _pre_ok, _pre_why = _idqc_pre.available()
        except Exception as _pre_exc:
            _pre_ok, _pre_why = False, str(_pre_exc)[:160]
        if not _pre_ok:
            log(
                f'Identity QC preflight FAILED ({_pre_why}) — parking run. '
                'Fix the embed worker, or set ZYG_CONTACT_SHEET_IDQC_REQUIRED=0 '
                'to deliberately run unverified.',
                level='ERROR',
            )
            from zyg_workflows import pipeline_control as _pc_pre

            raise _pc_pre.PipelinePaused(char_id, f'identity QC unavailable: {_pre_why}')


def step_persist_sheet_manifest(
    char_id: str,
    job: dict,
    *,
    sheet_path: str,
    rows: int,
    cols: int,
    auto_approve: bool,
) -> None:
    """Record the generated sheet, carrying the generator's own keys forward."""
    existing = _csp.load_manifest(char_id) or {}
    job['generation_mode'] = existing.get('generation_mode', 'dual_canvas_esrgan')
    job['dual_sheet'] = bool(existing.get('dual_sheet'))
    preserve = {
        k: existing[k]
        for k in (
            'generation_mode',
            'dual_sheet',
            'angle_set',
            'sheet_count',
            'total_tiles',
            'sheets',
            'sheet_paths',
            'identity_anchor_face',
            'sheet_a_seed',
            'sheet_b_identity_lock',
            'native_sheet_path',
            'native_width',
            'native_height',
            'upscaled_width',
            'upscaled_height',
            'upscale_factor',
            'export_cell_width',
            'export_cell_height',
            # per_cell / pose_locked modes: dropping cell_paths here would send
            # split_sheet_into_tiles down the grid-slicing path over the preview
            # composite — the exact corruption per-cell mode exists to eliminate.
            'cell_paths',
            'cell_angles',
            'sheet_seed',
            'pose_maps_used',
            'ipa_reference_cell',
            'pose_dir',
            # corpus mode (2026-08-09): the plan (labels+axes+hash) drives
            # plan-versioned resume and the derived-cap dedup; anchor_family
            # records which base rendered cell 0; dataset_dedup is the export
            # hygiene summary. write_manifest rewrites wholesale — anything not
            # whitelisted here dies at the next stage boundary.
            'anchor_family',
            'cell_plan',
            'dataset_dedup',
        )
        if k in existing
    }
    _csp.write_manifest(
        char_id,
        rows=int(existing.get('rows') or rows),
        cols=int(existing.get('cols') or cols),
        gutter=int(existing.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(existing.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(existing.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=sheet_path,
        approved=auto_approve,
        extra=preserve,
    )


def step_sheet_approval(
    char_id: str,
    job: dict,
    *,
    sheet_path: str,
    rows: int,
    cols: int,
    auto_approve: bool,
    resume_crop: bool,
    set_stage: Callable[[str], None],
    halt_check: Callable[[], None] | None,
    log: Callable[..., None],
) -> None:
    """Single-approval flow: the Agent Zero pre-start Allow is the only human
    gate. The objective QC stage (ArcFace + content-truth + yaw) replaces the
    manual sheet review; a pass-rate safety valve re-summons the operator only
    when quality actually collapses."""
    review_gate = os.environ.get('ZYG_CONTACT_SHEET_REVIEW_GATE', '0').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    if auto_approve or not review_gate or resume_crop:
        job['approved'] = True
        log(
            'Auto-approve — skipping manual review gate'
            if auto_approve
            else 'Resume — sheet already approved on prior run'
            if resume_crop
            else 'Single-approval flow — continuing to identity QC (objective gate)',
        )
    else:
        set_stage('awaiting_approval')
        log('Contact sheet ready for review — approve via API to continue')
        if not _csp.wait_for_approval(job, halt_check=halt_check):
            raise RuntimeError('Contact sheet approval timed out')

    manifest = _csp.load_manifest(char_id) or {}
    manifest['approved'] = True
    manifest['approved_at'] = _csp._ams_iso()
    post_approve_extra = {k: manifest[k] for k in manifest if k not in _MANIFEST_RESERVED}
    _csp.write_manifest(
        char_id,
        rows=int(manifest.get('rows') or rows),
        cols=int(manifest.get('cols') or cols),
        gutter=int(manifest.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(manifest.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(manifest.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=sheet_path,
        approved=True,
        tiles=manifest.get('tiles') or [],
        extra=post_approve_extra,
    )


def step_qc_backstop(
    char_id: str,
    idqc_summary: dict | None,
    *,
    park: Callable[[str], None],
    log: Callable[..., None],
) -> None:
    """Fail-closed backstop (2026-07-18).

    A SKIPPED QC (worker died mid-run, unexpected error) also skipped the
    pass-rate valve — the dataset shipped completely unverified with a green
    status. An explicit ZYG_CONTACT_SHEET_IDQC=0 is the operator's deliberate
    choice and passes; any other skip parks for approval so a human decides.
    Then rebuild the library preview so the sheet the operator reviews is the
    sheet that trains (2026-07-16) — QC repairs land in tiles/.
    """
    _qc_skip_reason = (idqc_summary or {}).get('skipped')
    if (
        _qc_skip_reason
        and 'ZYG_CONTACT_SHEET_IDQC=0' not in str(_qc_skip_reason)
        and os.environ.get(
            'ZYG_CONTACT_SHEET_IDQC_REQUIRED',
            '1',
        )
        .strip()
        .lower()
        not in ('0', 'false', 'no', 'off')
    ):
        park(
            f'Identity QC did NOT run ({str(_qc_skip_reason)[:120]}) — dataset is '
            'unverified. Approve only if you deliberately want to continue without QC.',
        )
        log('Operator approved proceeding WITHOUT identity QC — continuing')

    try:
        if int((idqc_summary or {}).get('regenerated') or 0) > 0:
            _csp.restitch_master_sheets(char_id, log_fn=log)
    except Exception as _rs_exc:
        log(f'Sheet re-stitch after QC failed ({_rs_exc}) — library preview may show pre-repair cells', level='WARN')


def step_qc_pass_rate_valve(
    char_id: str,
    idqc_summary: dict | None,
    *,
    job: dict,
    set_stage: Callable[[str], None],
    halt_check: Callable[[], None] | None,
    log: Callable[..., None],
) -> None:
    """Safety valve for the single-approval flow.

    QC is the objective gate, but if quality collapses (pass-rate under
    threshold after repairs), park the run and summon the operator via the Zero
    review card instead of silently training on a thin/degraded dataset.
    """
    _valve_counts = (idqc_summary or {}).get('counts') or {}
    _valve_total = sum(_valve_counts.values())
    if _valve_total and 'skipped' not in (idqc_summary or {}):
        _ok_n = _valve_counts.get('pass', 0) + _valve_counts.get('no_face_expected', 0)
        # The valve must see EVERY dataset exclusion, not just verdict fails:
        # VLM-flagged ghost tiles keep verdict 'pass' (ArcFace is blind to
        # ghosts) while being dropped from the dataset — a mass VLM exclusion
        # has to park the run exactly like a mass identity failure (2026-07-16
        # review). usable = total - excluded; min() avoids double-counting
        # tiles that are both verdict-failed and excluded.
        _excluded_n = int((idqc_summary or {}).get('excluded_from_dataset') or 0)
        _usable_n = max(0, _valve_total - _excluded_n)
        _rate = min(_ok_n, _usable_n) / _valve_total
        _min_rate = float(os.environ.get('ZYG_CONTACT_SHEET_QC_MIN_PASS_RATE', '0.60'))
        if _rate < _min_rate:
            log(
                f'QC pass-rate {_rate * 100:.0f}% below safety valve '
                f'{_min_rate * 100:.0f}% — parking run for operator review',
                level='WARN',
            )
            m_valve = _csp.load_manifest(char_id) or {}
            _valve_extra = {k: m_valve[k] for k in m_valve if k not in _MANIFEST_RESERVED}
            _csp.write_manifest(
                char_id,
                rows=int(m_valve.get('rows') or _csp.DEFAULT_ROWS),
                cols=int(m_valve.get('cols') or _csp.DEFAULT_COLS),
                gutter=int(m_valve.get('gutter_px') or _csp.DEFAULT_GUTTER),
                cell_w=int(m_valve.get('cell_width') or _csp.DEFAULT_CELL_W),
                cell_h=int(m_valve.get('cell_height') or _csp.DEFAULT_CELL_H),
                sheet_path=m_valve.get('sheet_path') or _csp.master_sheet_path(char_id),
                approved=False,
                tiles=m_valve.get('tiles') or [],
                extra=_valve_extra,
            )
            job['approved'] = False
            set_stage('awaiting_approval')
            if not _csp.wait_for_approval(job, halt_check=halt_check):
                raise RuntimeError('QC safety-valve approval timed out')
            log('Operator approved below-threshold QC results — continuing')
