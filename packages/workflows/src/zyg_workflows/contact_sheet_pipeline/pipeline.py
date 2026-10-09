# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""QC safety valve, approval wait, quality metrics and run_pipeline.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 5242-5709).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable

from zyg_workflows import paths
from zyg_workflows.contact_sheet_pipeline.constants import (
    DEFAULT_COLS,
    DEFAULT_ROWS,
    LORA_TRAINING_ENABLED,
    _normalize_angle_set,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    contact_sheet_dir,
    identity_anchor_face_path,
    load_manifest,
    master_sheet_path,
)
from zyg_workflows.contact_sheet_pipeline.angle_selection import custom_angle_labels_for_job
from zyg_workflows.contact_sheet_pipeline.dispatch import generate_contact_sheet
from zyg_workflows.contact_sheet_pipeline.tiles import split_sheet_into_tiles
from zyg_workflows.contact_sheet_pipeline.identity_qc import (
    _tile_texture_score,
    run_identity_qc,
)


def run_qc_safety_valve(
    char_id: str,
    params: dict,
    *,
    model_family: str = 'flux',
    log_fn: Callable[[str], None] | None = None,
    halt_check: Callable[[], None] | None = None,
) -> dict:
    """Post-training acceptance test (2026-07-18).

    The kanban has advertised a 'QC Safety Valve' card since the single-approval
    flow landed, but nothing ever validated what the trained LoRA actually
    learned — the flywheel scores its expansion tiles, the final artifact was
    never tested. Render a small validation set WITH the freshly trained LoRA
    (bible conditioning carries the lora_path) and prove the model reproduces
    the anchor identity + real skin texture. Returns
    {'verdict': 'pass'|'fail'|'skipped', 'stills': [...], 'reason': ...}.
    """
    out: dict[str, Any] = {'verdict': 'skipped', 'stills': []}
    try:
        from zyg_workflows import identity_qc_service as _idqc

        _ok, _why = _idqc.available()
        if not _ok:
            out['reason'] = f'identity QC unavailable ({_why})'
            return out
        from zyg_workflows import character_bible_service as _cbs
        from zyg_workflows import comfy_generation_service as _cgs

        pkg = _cbs.load(char_id)
        if not pkg:
            out['reason'] = 'no character bible'
            return out
        anchor = identity_anchor_face_path(char_id)
        if not os.path.isfile(anchor):
            out['reason'] = 'no anchor face'
            return out
        prefix = _cbs.identity_prompt_prefix(pkg)
        views = (
            ('front', 'front view portrait, head and shoulders, looking directly at camera'),
            ('three_quarter', 'three-quarter view portrait, head and shoulders'),
            ('profile', 'left side profile portrait, head and shoulders'),
        )
        valve_dir = os.path.join(contact_sheet_dir(char_id), 'qc_valve')
        os.makedirs(valve_dir, exist_ok=True)
        min_sim = float(os.environ.get('ZYG_QC_VALVE_MIN_SIM', '0.42'))
        min_sim_profile = float(os.environ.get('ZYG_QC_VALVE_MIN_SIM_PROFILE', '0.22'))
        tex_floor = float(os.environ.get('ZYG_QC_VALVE_MIN_TEXTURE', '30'))
        rendered: list[tuple[str, str]] = []
        for tag, view in views:
            if callable(halt_check):
                halt_check()
            outp = os.path.join(valve_dir, f'valve_{tag}.png')
            prompt = f'{prefix}, {view}, neutral studio background, {_cbs.PHOTOREAL_STYLE_PHRASE}'
            try:
                okg, _backend = _cgs.generate_still(
                    outp,
                    prompt,
                    width=1024,
                    height=1152,
                    steps=28,
                    cfg=3.5,
                    seed=int(uuid.uuid4().int % (2**31)),
                    character_package=pkg,
                    char_id=char_id,
                    model_family=model_family,
                    log_fn=log_fn,
                    skip_qa=True,
                    studio_preview=True,
                )
            except Exception as _gv_exc:
                if log_fn:
                    log_fn(f'QC valve: {tag} still failed ({str(_gv_exc)[:100]})')
                okg = False
            if okg and os.path.isfile(outp):
                rendered.append((tag, outp))
        if len(rendered) < 2:
            out['verdict'] = 'fail'
            out['reason'] = f'only {len(rendered)}/3 validation stills rendered'
            return out
        emb = _idqc.embed_images([anchor] + [p for _, p in rendered], log_fn=None)
        an_vec = (emb.get(anchor) or {}).get('embedding')
        if not an_vec:
            out['verdict'] = 'fail'
            out['reason'] = 'anchor face not embeddable'
            return out
        failures: list[str] = []
        for tag, p in rendered:
            e = emb.get(p) or {}
            vec = e.get('embedding')
            sim = _idqc.cosine(vec, an_vec) if vec else None
            tex = _tile_texture_score(p, e.get('bbox')) if e.get('face_detected') else None
            out['stills'].append(
                {
                    'view': tag,
                    'sim': round(sim, 4) if sim is not None else None,
                    'texture': round(tex, 1) if tex is not None else None,
                }
            )
            floor = min_sim_profile if tag == 'profile' else min_sim
            if sim is None or sim < floor:
                failures.append(f'{tag} sim {sim if sim is None else round(sim, 3)} < {floor:g}')
            elif tex is not None and tex < tex_floor:
                failures.append(f'{tag} texture {tex:.0f} < {tex_floor:g} (waxy)')
        out['verdict'] = 'fail' if failures else 'pass'
        if failures:
            out['reason'] = '; '.join(failures)[:300]
        return out
    except Exception as exc:
        out['verdict'] = 'error'
        out['reason'] = str(exc)[:200]
        return out


def wait_for_approval(
    job: dict,
    *,
    poll_s: float = 5.0,
    timeout_s: int | None = None,
    halt_check: Callable[[], None] | None = None,
) -> bool:
    timeout_s = (
        timeout_s
        if timeout_s is not None
        else int(
            os.environ.get('ZYG_CONTACT_SHEET_APPROVE_TIMEOUT', '86400'),
        )
    )
    char_id = job.get('char_id') or ''
    elapsed = 0.0
    while elapsed < timeout_s:
        if callable(halt_check):
            halt_check()
        if job.get('approved'):
            return True
        m = load_manifest(char_id)
        if m and m.get('approved'):
            job['approved'] = True
            return True
        # Operator DECLINE (2026-07-20): a live worker must exit the wait
        # promptly instead of polling `approved` for the full 24h timeout. The
        # decline handler set a manifest flag + job stage; unwind cleanly as a
        # park (PipelinePaused is BaseException, so it is not swallowed by the
        # stage QC guards) with the stage already moved off awaiting_approval.
        if job.get('review_declined') or (m and m.get('review_declined')):
            job['review_declined'] = True
            if job.get('stage') == 'awaiting_approval':
                job['stage'] = 'review_declined'
            from zyg_workflows import pipeline_control as _pc_dec

            raise _pc_dec.PipelinePaused(char_id, 'contact-sheet review declined by operator')
        time.sleep(poll_s)
        elapsed += poll_s
    return False


_QUALITY_METRICS_PATH = str(paths.DATA_DIR / 'runtime' / 'character_quality_metrics.jsonl')


def _append_quality_metrics(char_id: str, job: dict, params: dict) -> None:
    """One JSONL row per completed run (2026-07-18) — before this, each run's
    QC numbers lived only in its own state file, so quality regressions (the
    waxy-skin era, the same-face era) were invisible until a human happened to
    open a sheet. Grep/plot this file for trends."""
    import datetime as _dt

    qc = job.get('identity_qc') or {}
    dd = (job.get('params') or {}).get('_anchor_dedup') or {}
    valve = job.get('qc_safety_valve') or {}
    row = {
        'ts': _dt.datetime.now().isoformat(timespec='seconds'),
        'char_id': char_id,
        'name': (params or {}).get('name'),
        'gender': (params or {}).get('gender'),
        'qc_ran': 'skipped' not in qc,
        'qc_counts': qc.get('counts'),
        'qc_mean_score': qc.get('mean_score'),
        'qc_min_score': qc.get('min_score'),
        'qc_regenerated': qc.get('regenerated'),
        'qc_excluded': qc.get('excluded_from_dataset'),
        'anchor_dedup_max_sim': dd.get('max_sim'),
        'anchor_dedup_vs': dd.get('vs'),
        'anchor_attr_mismatches': (job.get('anchor_attributes') or {}).get('mismatches'),
        'lora_trained': not job.get('lora_training_disabled') and bool(job.get('kick_lora', True)),
        'lora_refined': bool(job.get('lora_refined')),
        'valve_verdict': valve.get('verdict'),
        'valve_stills': valve.get('stills'),
        'started': job.get('started'),
    }
    os.makedirs(os.path.dirname(_QUALITY_METRICS_PATH), exist_ok=True)
    with open(_QUALITY_METRICS_PATH, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def run_pipeline(
    job: dict,
    *,
    train_lora_fn: Callable[..., dict] | None = None,
    log_fn: Callable[[str], None] | None = None,
    halt_check: Callable[[], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_cell_progress: Callable[[int, int], None] | None = None,
) -> None:
    """
    Execute contact sheet pipeline stages on *job* (mutates job dict).

    train_lora_fn(char_id, info, train_mf, trainer, emit_fn, job) → status dict
    """
    from zyg_workflows import contact_sheet_pipeline_steps as _steps

    char_id = job['char_id']
    params = job.get('params') or {}
    rows = int(job.get('rows') or DEFAULT_ROWS)
    cols = int(job.get('cols') or DEFAULT_COLS)
    kick_lora = bool(job.get('kick_lora', True))
    auto_approve = bool(job.get('auto_approve', False))
    model_family = (job.get('model_family') or 'flux').strip().lower()
    # 'qwen' is a first-class train-plan family (2026-08-09 FLUX exit): the
    # dataset-review gate, train_lora_fn callback and bible updates are all
    # family-parameterized, so it flows through the training kick unchanged.
    # 'klein' (FLUX.2 [klein] 4B, Apache-2.0) joins on the same terms, 2026-08-23.
    if model_family not in ('flux', 'sdxl', 'qwen', 'klein'):
        model_family = 'flux'

    def _log(msg: str, level: str = 'INFO', stage: str = '') -> None:
        _steps.emit_log(char_id, msg, level, stage, log_fn)

    def _train_emit(msg: str, level: str = 'INFO', stage: str = '') -> None:
        _log(msg, level=level, stage=stage or 'LoRA Training')

    def _set_stage(name: str) -> None:
        job['stage'] = name
        if on_stage:
            on_stage(name)

    # Announce a gated LoRA up front, not just at the end (2026-07-17): four
    # runs in a row finished "done" with kick_lora=true and no LoRA before
    # anyone noticed the master switch was off.
    if kick_lora and not LORA_TRAINING_ENABLED:
        _log(
            'LoRA training is globally DISABLED (ZYG_CONTACT_SHEET_LORA_TRAINING=0) '
            '— this run will stop after dataset prep; no LoRA v1 / flywheel / v2 '
            'will be trained despite kick_lora=true. Set '
            'ZYG_CONTACT_SHEET_LORA_TRAINING=1 to re-enable.',
            level='WARNING',
        )
        job['lora_training_disabled'] = True

    def _park_for_operator(reason: str) -> None:
        _steps.park_for_operator(
            char_id,
            reason,
            job=job,
            set_stage=_set_stage,
            halt_check=halt_check,
            log=_log,
        )

    _steps.step_idqc_preflight(char_id, job, _log)

    resume_from = (job.get('resume_from') or '').strip() if job.get('resume') else ''

    def _skip_before(stage: str) -> bool:
        return _steps.skip_before(stage, resume_from)

    if resume_from:
        _log(f'Resuming pipeline at stage: {resume_from}')

    _set_stage('sheet_generate')
    sheet_mode = job.get('sheet_mode') or os.environ.get('ZYG_CONTACT_SHEET_MODE', 'auto')
    angle_set = _normalize_angle_set(job.get('angle_set'))
    if angle_set == 'custom':
        # Resolve the operator selection ONCE, here, so the label list the
        # generator uses is also the one the log and the manifest plan record.
        _custom_labels = custom_angle_labels_for_job(job)
        if not _custom_labels:
            _log('angle_set=custom with no valid angle selection — falling back to the extended 48-angle set')
            angle_set = 'extended'
        else:
            job['angle_labels'] = _custom_labels
            _log(f'Custom angle plan — {len(_custom_labels)} angles ({(len(_custom_labels) + 5) // 6} preview pages)')
    job['angle_set'] = angle_set

    def _cell_prog(done: int, total: int) -> None:
        job['sheet_cells_done'] = done
        job['sheet_cells_total'] = total
        if on_cell_progress:
            on_cell_progress(done, total)

    if _skip_before('tile_crop'):
        sheet_path = (load_manifest(char_id) or {}).get('sheet_path') or master_sheet_path(char_id)
        _log('Resume — reusing existing contact sheet (skipping generation)')
    else:
        sheet_path = generate_contact_sheet(
            char_id,
            params,
            rows=rows,
            cols=cols,
            log_fn=_log,
            mode=sheet_mode,
            model_family=model_family,
            on_cell_progress=_cell_prog,
            progress_job=job,
            angle_set=angle_set,
        )
    job['sheet_path'] = sheet_path
    _steps.step_persist_sheet_manifest(
        char_id,
        job,
        sheet_path=sheet_path,
        rows=rows,
        cols=cols,
        auto_approve=auto_approve,
    )

    _steps.step_sheet_approval(
        char_id,
        job,
        sheet_path=sheet_path,
        rows=rows,
        cols=cols,
        auto_approve=auto_approve,
        resume_crop=_skip_before('tile_crop'),
        set_stage=_set_stage,
        halt_check=halt_check,
        log=_log,
    )

    _set_stage('tile_crop')
    tiles = split_sheet_into_tiles(char_id, log_fn=_log)
    job['tile_count'] = len(tiles)

    _set_stage('identity_qc')
    if _skip_before('identity_qc'):
        idqc_summary = job.get('identity_qc') or (load_manifest(char_id) or {}).get('identity_qc') or {'resumed': True}
        _log('Resume — reusing prior identity QC results')
    else:
        try:
            tiles, idqc_summary = run_identity_qc(
                char_id,
                params,
                tiles,
                model_family=model_family,
                log_fn=_log,
                progress_job=job,
                halt_check=halt_check,
            )
        except Exception as _qc_exc:
            # The drift gate must never brick a run — degrade to a logged skip.
            _log(f'Identity QC error ({_qc_exc}) — continuing without gate', level='WARN')
            idqc_summary = {'skipped': str(_qc_exc)[:200]}
    job['identity_qc'] = idqc_summary

    _steps.step_qc_backstop(char_id, idqc_summary, park=_park_for_operator, log=_log)

    _steps.step_qc_pass_rate_valve(
        char_id,
        idqc_summary,
        job=job,
        set_stage=_set_stage,
        halt_check=halt_check,
        log=_log,
    )

    _set_stage('captions')
    n_cap, dataset_dir = _steps.step_captions(
        char_id,
        params,
        tiles,
        job=job,
        resume_captions=_skip_before('captions'),
        log=_log,
    )

    if kick_lora and not LORA_TRAINING_ENABLED:
        _log(
            'LoRA training DISABLED (ZYG_CONTACT_SHEET_LORA_TRAINING=0) — '
            'dataset is prepared and ready; review the sheet, then re-enable '
            'the flag to train',
            level='WARNING',
        )
        job['lora_training_disabled'] = True  # kanban shows training as not-run
        kick_lora = False

    if not kick_lora:
        _set_stage('done')
        job['status'] = 'done'
        _log(f'Pipeline done (LoRA skipped) — {n_cap} training images ready')
        return

    if train_lora_fn is None:
        _set_stage('done')
        job['status'] = 'done'
        _log('LoRA training skipped — no train_lora_fn')
        return

    _steps.step_dataset_review(
        char_id,
        n_cap=n_cap,
        job=job,
        auto_approve=auto_approve,
        resume_training=_skip_before('lora_training'),
        park=_park_for_operator,
        log=_log,
    )

    _set_stage('lora_training')
    trainer, info, primary_lora_path = _steps.step_lora_training(
        char_id,
        params,
        job=job,
        dataset_dir=dataset_dir,
        n_cap=n_cap,
        model_family=model_family,
        train_lora_fn=train_lora_fn,
        resume_training=_skip_before('lora_training'),
        train_emit=_train_emit,
        log=_log,
    )

    _steps.step_lora_flywheel(
        char_id,
        params,
        job=job,
        dataset_dir=dataset_dir,
        info=info,
        trainer=trainer,
        model_family=model_family,
        train_lora_fn=train_lora_fn,
        primary_lora_path=primary_lora_path,
        set_stage=_set_stage,
        train_emit=_train_emit,
        halt_check=halt_check,
        log=_log,
    )

    _steps.step_checkpoint_sweep(
        char_id,
        model_family=model_family,
        dataset_dir=dataset_dir,
        log=_log,
    )

    _steps.step_qc_safety_valve(
        char_id,
        params,
        job=job,
        model_family=model_family,
        primary_lora_path=primary_lora_path,
        park=_park_for_operator,
        halt_check=halt_check,
        log=_log,
    )

    _set_stage('done')
    job['status'] = 'done'
    _steps.step_finish_bible(
        char_id,
        params,
        job=job,
        dataset_dir=dataset_dir,
        log=_log,
    )
