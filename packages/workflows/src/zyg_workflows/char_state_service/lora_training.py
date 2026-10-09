# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character LoRA training: bible params and the per-family trainer.

Moved verbatim out of the old single-file char_state_service.py (lines 3249-3589).
"""

import os
from zyg_workflows import gui_state
from zyg_workflows.runtime import (
    _char_gen_jobs,
)
from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
    _zyg_log,
)
from zyg_workflows.char_state_service.char_state import (
    _char_stage_end,
    _char_stage_start,
)


def _char_params_from_bible(char_id: str) -> tuple[dict, dict]:
    """Rebuild (params, info) for *char_id* from its character bible on disk.

    Used by the per-character preview-regeneration route so it doesn't need the
    original request payload that produced the character.  Loads every
    descriptor the v2 schema carries so the regenerated preview matches what
    Stage 3.5 would produce for new scenes.
    """
    dataset_dir = str(_CHARS_DATASETS / char_id)
    params: dict = {}
    info: dict = {'dataset_dir': dataset_dir, 'trigger_token': f'ZYG_CHAR_{char_id[:6].upper()}'}
    try:
        from zyg_workflows import character_bible_service as _cbs_pp

        pkg = _cbs_pp.load(char_id) or {}
        ident = pkg.get('identity') or {}
        style = pkg.get('style_profile') or {}
        params = {
            'gender': ident.get('gender', 'female'),
            'age': ident.get('age'),
            'age_range': ident.get('age_range', ''),
            'height': ident.get('height_m', 1.70),
            'skin_tone': ident.get('skin_tone', 'medium'),
            'hair_color': ident.get('hair_color', 'brown'),
            'hair_style': ident.get('hair_style', ''),
            'hair_length': ident.get('hair_length', ''),
            'hair_texture': ident.get('hair_texture', ''),
            'eye_color': ident.get('eye_color', 'brown'),
            'eye_shape': ident.get('eye_shape', ''),
            'eyebrow_style': ident.get('eyebrow_style', ''),
            'face_shape': ident.get('face_shape', ''),
            'nose_shape': ident.get('nose_shape', ''),
            'lip_shape': ident.get('lip_shape', ''),
            'facial_hair': ident.get('facial_hair', 'none'),
            'muscle_mass': ident.get('muscle_mass') or ident.get('body_build', 20),
            'distinctive_marks': ident.get('distinctive_marks', ''),
            'ethnic_heritage': ident.get('ethnic_heritage', ''),
            'style': style.get('render_style', 'photorealistic'),
            'genre': style.get('genre', 'general'),
            'default_clothing': style.get('default_clothing', ''),
            'accessories': style.get('accessories', ''),
            'default_expression': style.get('default_expression', ''),
            'posture': style.get('posture', ''),
        }
        # Run auto-defaults so any older-schema bible missing newer keys is
        # still rendered with a complete prompt.
        params = _cbs_pp.apply_auto_defaults(params, seed_key=char_id)
        if pkg.get('trigger_token'):
            info['trigger_token'] = pkg['trigger_token']
        if pkg.get('dataset_dir'):
            info['dataset_dir'] = pkg['dataset_dir']
        info['package'] = pkg
        _mf = ((pkg.get('conditioning') or {}).get('model_family') or '').strip().lower()
        if _mf in ('flux', 'sdxl', 'qwen', 'klein'):
            params['model_family'] = _mf
            info['model_family'] = _mf
    except Exception as _exc:
        _zyg_log.warning('bible params not built, falling back to the defaults: %s', _exc)
    return params, info


def _char_train_lora_for_family(
    char_id: str,
    info: dict,
    train_mf: str,
    trainer,
    emit_fn,
    job: dict,
    *,
    unload_flux_vram: bool = False,
) -> dict:
    """Run SimpleTuner for one model family; return final trainer status dict."""
    import time as _time

    pass  # (global stmt removed: names moved to gui_state)
    stage_name = {
        'sdxl': 'Stage 1c — SDXL LoRA Training',
        'qwen': 'Stage 1c — QWEN LoRA Training',
    }.get(train_mf, 'Stage 1c — FLUX LoRA Training')
    _char_stage_start(char_id, stage_name)
    if unload_flux_vram:
        try:
            if gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
                gui_state._FLUX_DEV_PIPELINE_CACHE = None
                import gc as _gc_1c

                _gc_1c.collect()
                import torch as _torch_1c

                _torch_1c.cuda.empty_cache()
                emit_fn(
                    'Stage 1c — in-process FLUX preview pipeline unloaded (VRAM freed)',
                    stage=stage_name,
                )
        except Exception as _vram_e:
            emit_fn(
                f'Stage 1c — VRAM pre-unload warning: {_vram_e}',
                level='WARN',
                stage=stage_name,
            )
    # v2 flywheel refine: left alone, start_training finds v1's checkpoint, resumes
    # at global_step == max_train_steps and trains ZERO steps (silent no-op — the
    # whole flywheel payoff was fake). Clear the stale done-job so a fresh run is
    # created, and raise the step target above v1's so the resume trains real
    # steps on the expanded (original + expansion) dataset.
    _refine_steps = None
    if job.get('stage') == 'lora_refine':
        try:
            from zyg_workflows import lora_trainer_service as _lts_refine

            # Defaults must track lora_trainer_service._QUICK_STEPS (1200 since
            # 2026-07-09 — 200 left the LoRA nearly untrained); refine adds 400.
            _base = int(os.environ.get('ZYG_LORA_TRAIN_STEPS', '1200'))
            _refine_steps = _base + int(os.environ.get('ZYG_LORA_REFINE_STEPS', '400'))
            _lts_refine._training_jobs.pop(char_id, None)
            emit_fn(
                f'Stage 1c — LoRA v2 refine: training to {_refine_steps} steps on the '
                f'expanded dataset (resumes v1, adds {_refine_steps - _base} real steps)',
                stage=stage_name,
            )
        except Exception as _rf_exc:
            emit_fn(f'Stage 1c — refine step-bump warning: {_rf_exc}', level='WARN', stage=stage_name)
            _refine_steps = None
    emit_fn(
        f'Stage 1c — SimpleTuner {train_mf.upper()} LoRA training started (trigger: {info.get("trigger_token", "")})',
        stage=stage_name,
    )
    # Defer v1 checkpoint cleanup when a flywheel refine will follow — the v2
    # --resume_from_checkpoint needs those dirs (2026-07-18: v1's own cleanup
    # deleted them, silently turning every "refine" into a from-scratch
    # retrain; run_pipeline sweeps leftovers after the flywheel finishes).
    _is_refine = job.get('stage') == 'lora_refine'
    _defer_cleanup = (
        not _is_refine
        and job.get('pipeline') == 'multi_angle_contact_sheet'
        and bool(job.get('flywheel', True))
        and bool(job.get('kick_lora', True))
    )
    # 2026-07-25: SDXL ⟹ ANIMATED. The SDXL leg trains an animated (3D-toon)
    # twin on its OWN animated dataset (photoreal tiles restyled through the
    # animated checkpoint) so the LoRA renders on-model. FLUX keeps the
    # photoreal dataset. ZYG_SDXL_ANIMATED=0 restores the photoreal SDXL twin.
    _train_dataset_dir = info['dataset_dir']
    if train_mf == 'sdxl' and os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no'):
        # FAIL LOUD (review): a silent fallback to the photoreal dataset would
        # train the SDXL LoRA on photoreal tiles but render it on the 3D-toon
        # base — an off-model twin that silently ships. Abort the SDXL leg
        # instead (return a failed status; the FLUX photoreal LoRA is unaffected).
        try:
            # 2026-07-26: ISOLATED per-character style profile. If the bible
            # carries style_profile.restyle = <name>, restyle the training tiles
            # into that style (e.g. Arcane) via the isolated arcane_restyle path
            # instead of the global 3D-toon animated path. Absent → unchanged
            # (the public zero_public flow never sets it). See arcane_restyle.py.
            _restyle_profile = ''
            try:
                from zyg_workflows import character_bible_service as _cbs_sp

                _restyle_profile = str(
                    (((_cbs_sp.load(char_id) or {}).get('style_profile') or {}).get('restyle')) or ''
                ).strip()
            except Exception:
                _restyle_profile = ''
            _styled_cfg = None
            if _restyle_profile:
                try:
                    from zyg_workflows import arcane_restyle as _styled

                    _styled_cfg = _styled.load_profile(_restyle_profile)
                except Exception:
                    _styled_cfg = None
            # 2026-07-26: fail LOUD when a restyle profile is REQUESTED but does not
            # resolve — silently falling through to the global 3D-toon dataset below
            # would ship a toon twin for a character the operator explicitly flagged
            # for an isolated style (e.g. a typo'd 'arcane' instead of the profile
            # key 'arcane_animation'). The outer try aborts the SDXL leg cleanly.
            if _restyle_profile and not (_styled_cfg and _styled_cfg.get('restyle')):
                raise RuntimeError(
                    f'style_profile.restyle={_restyle_profile!r} did not resolve to a valid '
                    f'restyle profile in character_style_profiles.json — refusing to silently '
                    f'fall back to the global 3D-toon dataset (use the exact profile key, '
                    f"e.g. 'arcane_animation')"
                )
            if _restyle_profile and _styled_cfg and _styled_cfg.get('restyle'):
                from zyg_workflows import arcane_restyle as _styled

                _train_dataset_dir = _styled.build_styled_sdxl_dataset(
                    char_id,
                    info['dataset_dir'],
                    style_cfg=_styled_cfg['restyle'],
                    log_fn=lambda m: emit_fn(m, stage=stage_name),
                )
                emit_fn(
                    f'Stage 1c — SDXL styled dataset ({_restyle_profile}) ready → {_train_dataset_dir}',
                    stage=stage_name,
                )
            else:
                from zyg_workflows import animated_sdxl_dataset as _anim_ds

                _train_dataset_dir = _anim_ds.build_animated_sdxl_dataset(
                    char_id,
                    info['dataset_dir'],
                    log_fn=lambda m: emit_fn(m, stage=stage_name),
                )
                emit_fn(f'Stage 1c — SDXL animated dataset ready → {_train_dataset_dir}', stage=stage_name)
        except Exception as _anim_e:
            emit_fn(
                f'Stage 1c — animated SDXL dataset build FAILED ({_anim_e}) — '
                f'aborting the SDXL twin (photoreal FLUX LoRA unaffected)',
                level='ERROR',
                stage=stage_name,
            )
            _char_stage_end(
                char_id, stage_name, status='failed', extra={'error': f'animated dataset: {str(_anim_e)[:180]}'}
            )
            _cj = _char_gen_jobs.get(char_id) or job
            _cj['lora_failed'] = True
            _cj['lora_error'] = f'animated SDXL dataset build failed: {str(_anim_e)[:180]}'
            return {'failed': True, 'error': f'animated dataset: {_anim_e}', 'model_family': 'sdxl'}
    # Medusa isolation (2026-08-06): the trained LoRA is the one artifact this
    # function writes that lives OUTSIDE contact_sheet_pipeline.py (whose
    # dataset-root chokepoints medusa_pipeline already redirects for this
    # thread) — LoraTrainerService resolves its own output root independently.
    # Reuse the SAME thread-local flag medusa_pipeline sets for the duration of
    # a Medusa run (this function executes on that same thread, synchronously,
    # as contact_sheet_pipeline's train_lora_fn callback) rather than adding a
    # new detector; None on every non-Medusa thread, so start_training/
    # get_status fall back to their normal shared output root unchanged.
    _medusa_output_root = None
    try:
        from zyg_workflows import medusa_pipeline as _medp

        if getattr(_medp._MEDUSA_TLS, 'swimwear', False):
            _medusa_output_root = _medp.MEDUSA_CHAR_OUTPUT_ROOT
    except Exception as _exc:
        _zyg_log.debug('medusa swimwear output root not resolved: %s', _exc)

    trainer.start_training(
        char_id,
        _train_dataset_dir,
        trigger_token=info['trigger_token'],
        model_family=train_mf,
        cleanup_after=not _defer_cleanup,
        lora_version=2 if _is_refine else 1,
        output_root=_medusa_output_root,
        **({'total_steps': _refine_steps} if _refine_steps else {}),
    )
    # Step-scaled kill budget (was a hard 60*60): the 2026-07-09 step bump
    # (200→1200, +400 refine) at 1024 pixel-area runs ~3-3.5 s/step plus model
    # load, int8-quanto quantization, first-run VAE re-cache and validation
    # renders — a fixed hour SIGKILLed the training this fix exists to deliver.
    # 6 s/step worst-case + 30 min fixed overhead; env-overridable.
    _lora_step_target = _refine_steps or int(os.environ.get('ZYG_LORA_TRAIN_STEPS', '1200'))
    _LORA_TIMEOUT = int(
        os.environ.get(
            'ZYG_LORA_TIMEOUT_SEC',
            str(_lora_step_target * 6 + 30 * 60),
        )
    )
    _elapsed = 0
    _last_pct = -1
    _st: dict = {}
    while _elapsed < _LORA_TIMEOUT:
        _time.sleep(10)
        _elapsed += 10
        _st = trainer.get_status(char_id, model_family=train_mf, output_root=_medusa_output_root)
        _pct = int(_st.get('pct', 0))
        if _pct != _last_pct and _pct % 10 == 0 and _pct > 0:
            emit_fn(
                f'Stage 1c — LoRA training {_pct}% '
                f'({_st.get("step", 0)}/{_st.get("total_steps") or _lora_step_target} steps)',
                stage=stage_name,
            )
            _last_pct = _pct
        if _st.get('done'):
            emit_fn(
                f'Stage 1c — LoRA training complete: {_st.get("lora_path", "")}',
                stage=stage_name,
            )
            _char_stage_end(
                char_id,
                stage_name,
                extra={
                    'total_steps': _st.get('total_steps'),
                    'final_step': _st.get('step'),
                    'lora_path': _st.get('lora_path'),
                    'model_family': train_mf,
                },
            )
            return _st
        if _st.get('failed'):
            _lora_err = _st.get('error', 'unknown')
            emit_fn(
                f'Stage 1c — LoRA training failed: {_lora_err} — IPAdapter fallback will be used',
                level='WARN',
                stage=stage_name,
            )
            for _log_line in _st.get('log_tail') or []:
                if _log_line.strip():
                    emit_fn(
                        f'  [training.log] {_log_line.strip()}',
                        level='ERROR',
                        stage=stage_name,
                    )
            _cj = _char_gen_jobs.get(char_id) or job
            _cj['lora_failed'] = True
            _cj['lora_error'] = _lora_err
            _char_stage_end(
                char_id,
                stage_name,
                status='failed',
                extra={'error': str(_lora_err)[:200]},
            )
            return _st
    emit_fn(
        f'Stage 1c — LoRA training timed out ({_LORA_TIMEOUT // 60} min). Killing process and freeing VRAM.',
        level='WARN',
        stage=stage_name,
    )
    try:
        _st_job = trainer._training_jobs.get(char_id) if hasattr(trainer, '_training_jobs') else None
        if _st_job is None:
            from zyg_workflows import lora_trainer_service as _lts_kill

            _st_job = _lts_kill._training_jobs.get(char_id)
        if _st_job and _st_job.proc and _st_job.proc.poll() is None:
            _st_job.proc.terminate()
            _time.sleep(3)
            if _st_job.proc.poll() is None:
                _st_job.proc.kill()
    except Exception as _kill_e:
        emit_fn(
            f'Stage 1c — Could not kill SimpleTuner: {_kill_e}',
            level='WARN',
            stage=stage_name,
        )
    _cj = _char_gen_jobs.get(char_id) or job
    _cj['lora_failed'] = True
    _cj['lora_error'] = f'Training timed out after {_LORA_TIMEOUT // 60} min'
    _char_stage_end(char_id, stage_name, status='failed', extra={'error': 'timeout'})
    return _st
