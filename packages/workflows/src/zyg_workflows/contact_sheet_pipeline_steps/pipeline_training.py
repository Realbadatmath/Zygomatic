# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_pipeline steps: captions, dataset review, LoRA training and the bible finish.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 3610-4080).
"""

from __future__ import annotations

import os
from typing import Any, Callable
from zyg_workflows import contact_sheet_pipeline as _csp

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_captions(
    char_id: str,
    params: dict,
    tiles: list[dict],
    *,
    job: dict,
    resume_captions: bool,
    log: Callable[..., None],
) -> tuple[int, str]:
    """Archive the prior dataset, dedup, caption, and sync the trainer dir.

    Returns (captioned tile count, dataset dir).
    """
    if resume_captions:
        _cap_dir = _csp.training_dataset_dir(char_id)
        n_cap = (
            len([f for f in os.listdir(_cap_dir) if f.startswith('contactsheet_') and f.endswith('.png')])
            if os.path.isdir(_cap_dir)
            else 0
        )
        log(f'Resume — reusing {n_cap} existing captioned tiles')
    else:
        # Archive any existing dataset before writing new captions so a re-run
        # never silently overwrites the previously approved training set.
        _ds_dir = _csp.training_dataset_dir(char_id)
        if os.path.isdir(_ds_dir):
            _existing_tiles = [f for f in os.listdir(_ds_dir) if f.startswith('contactsheet_') and f.endswith('.png')]
            if _existing_tiles:
                import time as _time_mod

                _archive_ts = _time_mod.strftime('%Y%m%d_%H%M%S')
                _archive_dir = os.path.join(_ds_dir, 'archive', _archive_ts)
                os.makedirs(_archive_dir, exist_ok=True)
                for _af in _existing_tiles:
                    _asrc = os.path.join(_ds_dir, _af)
                    _adst = os.path.join(_archive_dir, _af)
                    os.rename(_asrc, _adst)
                    _atxt = _asrc.replace('.png', '.txt')
                    if os.path.isfile(_atxt):
                        os.rename(_atxt, _adst.replace('.png', '.txt'))
                log(f'Dataset archived ({len(_existing_tiles)} tiles → archive/{_archive_ts})')
        # Intra-set dedup (2026-08-09): AFTER identity-QC exclusions, BEFORE
        # captions/sync — near-duplicates and over-capped derived cells are
        # excluded from the dataset here but STAY in the sheet.
        job['dataset_dedup'] = _csp.dedup_dataset_tiles(char_id, tiles, log_fn=log)
        n_cap = _csp.write_tile_captions(char_id, params, tiles, log_fn=log)
    # Trainer-facing dir holds ONLY png+txt pairs — SimpleTuner rglobs
    # recursively and must never see the contact_sheet/ working files.
    dataset_dir = _csp.training_dataset_dir(char_id)
    paths = sorted(
        (
            os.path.join(dataset_dir, f)
            for f in os.listdir(dataset_dir)
            if f.startswith('contactsheet_') and f.endswith('.png')
        ),
        key=_csp._stem_index,
    )
    _csp.sync_dataset_manifest(char_id, params, paths)
    job['dataset_dir'] = dataset_dir
    job['trigger_token'] = _csp.trigger_token_for(char_id)
    return n_cap, dataset_dir


def step_dataset_review(
    char_id: str,
    *,
    n_cap: int,
    job: dict,
    auto_approve: bool,
    resume_training: bool,
    park: Callable[[str], None],
    log: Callable[..., None],
) -> None:
    """Training-set sheet + dataset review gate (2026-07-18/20).

    The sheet is stitched from exactly the tiles that train, so the review
    shows what an Allow approves — the master sheet keeps excluded tiles for
    exhibition and cannot. Sheet approval fires BEFORE tile repairs and
    exclusions, so the dataset that actually trains was never human-reviewed —
    and pure-QC gating missed the ghost-face batch (2026-07-16). One more
    operator Allow before training GPU is committed; auto_approve runs skip it.
    """
    try:
        _csp.stitch_training_sheet(char_id, log_fn=log)
    except Exception as _ts_exc:
        log(f'Training-set sheet warning ({_ts_exc})', level='WARN')

    _ds_review_on = os.environ.get(
        'ZYG_CONTACT_SHEET_DATASET_REVIEW',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _ds_review_on and not auto_approve and not resume_training:
        _qc_sum_dr = job.get('identity_qc') or {}
        _qc_counts_dr = _qc_sum_dr.get('counts') or {}
        park(
            f'Dataset ready for FINAL review — {n_cap} training tiles '
            f'({_qc_counts_dr.get("pass", "?")} QC pass, '
            f'{_qc_sum_dr.get("excluded_from_dataset", "?")} excluded, '
            f'{_qc_sum_dr.get("regenerated", "?")} repaired). '
            'Approve to start LoRA training.',
        )
        log('Dataset review approved — starting LoRA training')


def step_lora_training(
    char_id: str,
    params: dict,
    *,
    job: dict,
    dataset_dir: str,
    n_cap: int,
    model_family: str,
    train_lora_fn: Callable[..., dict],
    resume_training: bool,
    train_emit: Callable[..., None],
    log: Callable[..., None],
) -> tuple[Any, dict, str | None]:
    """Train LoRA v1 (plus the optional SDXL twin).

    Returns (trainer, info dict, primary LoRA path or None).
    """
    from zyg_workflows import lora_trainer_service as _lts

    trainer = _lts.get_trainer()
    info = {
        'char_id': char_id,
        'dataset_dir': dataset_dir,
        'trigger_token': job['trigger_token'],
        'manifest': _csp.load_manifest(char_id),
    }

    primary_lora_path: str | None = None
    if resume_training:
        # Resuming into the flywheel — LoRA v1 already trained on a prior run.
        # Reload its path so angle expansion / refine can proceed.
        try:
            primary_lora_path = trainer.get_lora_path(char_id, model_family=model_family)
        except Exception as _lp_exc:
            log(f'Resume — could not reload LoRA v1 path ({_lp_exc})', level='WARN')
        log(f'Resume — skipping LoRA v1 training (reusing {primary_lora_path or "n/a"})')
        return trainer, info, primary_lora_path

    train_plan = [model_family]
    # Dual default OFF since 2026-07-18 (SDXL twin ≈ doubles training GPU;
    # base-vs-Juggernaut mismatch made it weak anyway). Opt back in via env.
    dual = os.environ.get('ZYG_CHAR_DUAL_LORA_PHOTOREAL', '0').lower() in ('1', 'true', 'yes')
    style = (params.get('style') or '').strip().lower()
    # The twin pairing is flux<->sdxl ONLY. A qwen or klein run must never
    # schedule a FLUX twin: that would mint a flux1-dev derivative — the
    # exact non-commercial exposure those families exist to leave behind.
    if dual and model_family in ('flux', 'sdxl') and style in ('photorealistic', 'cinematic', 'realistic', 'photo', ''):
        other = 'sdxl' if model_family == 'flux' else 'flux'
        if other not in train_plan:
            train_plan.append(other)

    for train_mf in train_plan:
        log(f'Starting SimpleTuner {train_mf.upper()} LoRA ({n_cap} contact-sheet tiles)')
        st = train_lora_fn(
            char_id,
            info,
            train_mf,
            trainer,
            train_emit,
            job,
        )
        if st.get('failed'):
            job['lora_failed'] = True
            job['lora_error'] = st.get('error')
            raise RuntimeError(st.get('error') or f'{train_mf} LoRA training failed')
        if train_mf == model_family and st.get('lora_path'):
            primary_lora_path = st['lora_path']
        try:
            from zyg_workflows import character_bible_service as _cbs

            if st.get('lora_path'):
                _cbs.update_lora(char_id, st['lora_path'], model_family=train_mf)
        except Exception as _e:
            log(f'Bible LoRA update warning: {_e}', level='WARN')
    return trainer, info, primary_lora_path


def step_lora_flywheel(
    char_id: str,
    params: dict,
    *,
    job: dict,
    dataset_dir: str,
    info: dict,
    trainer: Any,
    model_family: str,
    train_lora_fn: Callable[..., dict],
    primary_lora_path: str | None,
    set_stage: Callable[[str], None],
    train_emit: Callable[..., None],
    halt_check: Callable[[], None] | None,
    log: Callable[..., None],
) -> None:
    """LoRA flywheel: v1 generates the angles the face anchor can't lock,
    survivors join the dataset, v2 retrains on the expanded set."""
    flywheel_on = bool(job.get('flywheel', _csp.FLYWHEEL_ENABLED))
    if flywheel_on and primary_lora_path:
        set_stage('angle_expansion')
        try:
            expansion_paths = _csp.run_angle_expansion(
                char_id,
                params,
                primary_lora_path,
                model_family=model_family,
                log_fn=log,
                progress_job=job,
                halt_check=halt_check,
            )
        except Exception as _fw_exc:
            log(f'Angle expansion error ({_fw_exc}) — keeping LoRA v1', level='WARN')
            expansion_paths = []
        job['expansion_kept'] = len(expansion_paths)

        if expansion_paths:
            all_paths = sorted(
                (
                    os.path.join(dataset_dir, f)
                    for f in os.listdir(dataset_dir)
                    if f.endswith('.png') and (f.startswith('contactsheet_') or f.startswith('expansion_'))
                ),
                key=lambda p: (0 if os.path.basename(p).startswith('contactsheet_') else 1, _csp._stem_index(p)),
            )
            _csp.sync_dataset_manifest(char_id, params, all_paths)
            try:
                _csp.stitch_training_sheet(char_id, log_fn=log)  # expansion joined
            except Exception as _exc:
                _zyg_log.debug('training sheet restitch after expansion skipped: %s', _exc)
            set_stage('lora_refine')
            log(
                f'LoRA v2 refine — retraining {model_family.upper()} on '
                f'{len(all_paths)} images ({len(expansion_paths)} expansion angles added)',
            )
            info['manifest'] = _csp.load_manifest(char_id)
            # Pass lora_version so the trainer can optionally adjust hyperparameters
            # (lower LR, more steps) for the larger v2 dataset.
            info['lora_version'] = 2
            info['dataset_count'] = len(all_paths)
            st2 = train_lora_fn(
                char_id,
                info,
                model_family,
                trainer,
                train_emit,
                job,
            )
            if st2.get('failed'):
                # v1 already trained and registered — a failed refine is a warning.
                log(
                    f'LoRA v2 refine failed ({st2.get("error")}) — keeping v1',
                    level='WARN',
                )
                job['lora_refine_failed'] = True
            else:
                job['lora_refined'] = True
                try:
                    from zyg_workflows import character_bible_service as _cbs_v2

                    if st2.get('lora_path'):
                        _cbs_v2.update_lora(
                            char_id,
                            st2['lora_path'],
                            model_family=model_family,
                        )
                except Exception as _e2:
                    log(f'Bible LoRA v2 update warning: {_e2}', level='WARN')

            _step_sdxl_flywheel_refine(
                char_id,
                params,
                job=job,
                info=info,
                trainer=trainer,
                model_family=model_family,
                train_lora_fn=train_lora_fn,
                all_paths=all_paths,
                train_emit=train_emit,
                log=log,
            )
        else:
            log('Flywheel: no expansion images kept — skipping LoRA v2 retrain')
    elif flywheel_on and not primary_lora_path:
        log('Flywheel skipped — no primary LoRA path reported by trainer', level='WARN')


def _step_sdxl_flywheel_refine(
    char_id: str,
    params: dict,
    *,
    job: dict,
    info: dict,
    trainer: Any,
    model_family: str,
    train_lora_fn: Callable[..., dict],
    all_paths: list[str],
    train_emit: Callable[..., None],
    log: Callable[..., None],
) -> None:
    """SDXL flywheel: if dual-LoRA was trained on this run, refine it too on
    the expanded dataset. SDXL v1 was trained on 48 tiles; now it gets the
    same expanded set that FLUX v2 just used."""
    _dual_style = (params.get('style') or '').strip().lower()
    _dual_enabled = os.environ.get('ZYG_CHAR_DUAL_LORA_PHOTOREAL', '0').lower() in ('1', 'true', 'yes')
    if (
        _dual_enabled
        and _dual_style in ('photorealistic', 'cinematic', 'realistic', 'photo', '')
        and model_family == 'flux'
    ):
        try:
            from zyg_workflows import lora_trainer_service as _lts_sdxl

            _sdxl_v1_path = _lts_sdxl.get_trainer().get_lora_path(
                char_id,
                model_family='sdxl',
            )
        except Exception:
            _sdxl_v1_path = None
        if _sdxl_v1_path and os.path.isfile(_sdxl_v1_path):
            log(
                f'SDXL LoRA v2 refine — retraining on {len(all_paths)} images',
            )
            _sdxl_info = dict(info)
            _sdxl_info['lora_version'] = 2
            _sdxl_info['dataset_count'] = len(all_paths)
            try:
                st3 = train_lora_fn(
                    char_id,
                    _sdxl_info,
                    'sdxl',
                    trainer,
                    train_emit,
                    job,
                )
                if st3.get('failed'):
                    log(
                        f'SDXL LoRA v2 refine failed ({st3.get("error")}) — keeping SDXL v1',
                        level='WARN',
                    )
                else:
                    try:
                        from zyg_workflows import character_bible_service as _cbs_sdxl

                        if st3.get('lora_path'):
                            _cbs_sdxl.update_lora(
                                char_id,
                                st3['lora_path'],
                                model_family='sdxl',
                            )
                    except Exception as _e3:
                        log(f'Bible SDXL LoRA v2 update warning: {_e3}', level='WARN')
            except Exception as _sdxl_fw_exc:
                log(f'SDXL flywheel error ({_sdxl_fw_exc}) — keeping v1', level='WARN')


def step_checkpoint_sweep(
    char_id: str,
    *,
    model_family: str,
    dataset_dir: str,
    log: Callable[..., None],
) -> None:
    """End-of-flywheel checkpoint sweep (2026-07-18).

    v1 training defers its own cleanup so the v2 refine can
    --resume_from_checkpoint. Whichever branch we exited through (refined,
    no-expansion skip, expansion error), remove the leftover resume-state dirs
    now — final exports are kept and recorded paths are re-verified.
    """
    try:
        from zyg_workflows import lora_trainer_service as _lts_sweep

        _sweep_fams = [model_family]
        if os.environ.get(
            'ZYG_CHAR_DUAL_LORA_PHOTOREAL',
            '0',
        ).lower() in ('1', 'true', 'yes'):
            _sweep_fams.append('sdxl' if model_family == 'flux' else 'flux')
        for _fam_sw in _sweep_fams:
            _lts_sweep.cleanup_char_training(char_id, _fam_sw, dataset_dir=dataset_dir)
        log('Checkpoint sweep complete — resume dirs removed, final exports kept')
    except Exception as _sw_exc:
        log(f'Checkpoint sweep warning ({_sw_exc})', level='WARN')


def step_qc_safety_valve(
    char_id: str,
    params: dict,
    *,
    job: dict,
    model_family: str,
    primary_lora_path: str | None,
    park: Callable[[str], None],
    halt_check: Callable[[], None] | None,
    log: Callable[..., None],
) -> None:
    """QC SAFETY VALVE (2026-07-18) — post-training acceptance test.

    Only meaningful when a LoRA actually trained this run; renders 3
    validation stills with the trained LoRA and verifies identity + texture
    before the character is declared done. Fail/error parks for approval so a
    drifted LoRA never enters the library silently.
    """
    _valve_on = os.environ.get(
        'ZYG_QC_SAFETY_VALVE',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _valve_on and primary_lora_path:
        log('QC safety valve — rendering validation stills with the trained LoRA')
        job['sheet_substage'] = 'qc_safety_valve'
        try:
            _valve = _csp.run_qc_safety_valve(
                char_id,
                params,
                model_family=model_family,
                log_fn=log,
                halt_check=halt_check,
            )
        except Exception as _valve_exc:
            _valve = {'verdict': 'error', 'reason': str(_valve_exc)[:200]}
        job['qc_safety_valve'] = _valve
        if _valve.get('verdict') == 'pass':
            _sims = [s.get('sim') for s in _valve.get('stills', []) if s.get('sim') is not None]
            log(
                f'QC safety valve PASS — {len(_valve.get("stills", []))} stills, '
                f'sims {", ".join(f"{s:.3f}" for s in _sims)}',
            )
        elif _valve.get('verdict') in ('fail', 'error'):
            park(
                f'QC safety valve {_valve.get("verdict").upper()}: '
                f'{_valve.get("reason", "no detail")} — the trained LoRA did not '
                'reproduce the anchor identity. Approve to accept it anyway.',
            )
            log('Operator accepted the LoRA despite valve failure — continuing')
        else:
            log(f'QC safety valve skipped ({_valve.get("reason", "?")})', level='WARN')


def step_finish_bible(
    char_id: str,
    params: dict,
    *,
    job: dict,
    dataset_dir: str,
    log: Callable[..., None],
) -> None:
    """Refresh the character bible and append the run's quality metrics."""
    try:
        from zyg_workflows import character_bible_service as _cbs_done

        info = {
            'char_id': char_id,
            'dataset_dir': dataset_dir,
            'trigger_token': job['trigger_token'],
            'manifest': _csp._read_meta(dataset_dir, os.path.join(_csp._OUTPUT_ROOT, char_id)),
        }
        _cbs_done.build_from_character_generate(
            char_id,
            params,
            info,
            log_fn=log,
        )
    except Exception as _bible_e:
        log(f'Character bible refresh warning: {_bible_e}', level='WARN')
    try:
        _csp._append_quality_metrics(char_id, job, params)
    except Exception as _qm_exc:
        log(f'Quality metrics append failed ({_qm_exc})', level='WARN')
    log('Multi-angle contact sheet pipeline complete')
