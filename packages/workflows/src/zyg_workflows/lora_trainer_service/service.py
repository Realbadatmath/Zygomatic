# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LoraTrainerService — the training orchestrator."""

import os
import json
import logging
import threading
from typing import Optional
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service import service_training as _training
from zyg_workflows.lora_trainer_service.model_paths import (  # noqa: F401
    _EPOCH_STEP_CEIL,
    _EPOCH_STEP_FLOOR,
    _KLEIN_HF_ID,
    _KLEIN_PINNED_REV,
    _OUTPUT_ROOT,
    _QUICK_STEPS,
    _QWEN_HF_ID,
    _QWEN_PINNED_REV,
    _SIMPLE_TUNER_DIR,
    _STATUS_SAVE_INTERVAL_S,
    _TRAIN_MODEL_PATH,
    _ensure_klein_diffusers_weights,
    _ensure_qwen_diffusers_weights,
    _ensure_sdxl_diffusers_weights,
)
from zyg_workflows.lora_trainer_service.job_state import (  # noqa: F401
    TrainingJob,
    _VRAM_RELEASED_EVENT,
    _normalize_train_family,
    _progress_fields,
    _read_disk_train_family,
    _record_start_result,
    _training_jobs,
)
from zyg_workflows.lora_trainer_service.config_support import (  # noqa: F401
    _cleanup_after_training,
)
from zyg_workflows.lora_trainer_service.st_config import (  # noqa: F401
    _drop_stale_benchmarks,
    _ensure_preview_captions,
    _read_config_value,
    stamp_lora_alpha,
)
from zyg_workflows.lora_trainer_service.st_config_writers import (  # noqa: F401
    _write_st_config_flux,
    _write_st_config_klein,
    _write_st_config_qwen,
    _write_st_config_sdxl,
    _write_st_multidatabackend,
)
from zyg_workflows.lora_trainer_service.helpers import (  # noqa: F401
    _checkpoint_matches_family,
    _find_latest_checkpoint,
    _save_status,
    _status_path_for,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')


class LoraTrainerService:
    """Start and monitor FLUX / SDXL / Qwen character LoRA training via SimpleTuner."""

    def start_training(
        self,
        char_id: str,
        dataset_dir: str,
        trigger_token: Optional[str] = None,
        total_steps: int = _QUICK_STEPS,
        model_family: str = 'flux',
        output_root: str | None = None,
        cleanup_after: bool = True,
        lora_version: int = 1,
        loss_mask_dir: str | None = None,
        train_mode: str = 'identity',
        max_steps: int | None = None,
        validation_prompt: str | None = None,
    ) -> str:
        """
        Start background LoRA training.

        Returns trigger_token (ZYG_CHAR_<char_id[:6]>) when a training thread was
        actually launched, and '' when this call REFUSED to launch one (already
        trained, or another family is mid-flight in this character's single job
        slot). 2026-07-31: both refusals used to return the trigger token too, so
        a caller could not tell a launch from a refusal — it then polled
        get_status() and read the OTHER leg's progress as its own. Either way
        last_start_result(char_id) carries {'started', 'reason', 'model_family',
        'trigger_token'}. ZYG_LORA_START_SIGNAL_REFUSAL=0 restores the old
        always-return-the-token behaviour.

        The caller should poll get_status() until done=True before running the pipeline.
        """
        if trigger_token is None:
            trigger_token = f'ZYG_CHAR_{char_id[:6].upper()}'

        # Epoch-scaled steps (2026-07-18): a flat step count trains a 64-image
        # expanded dataset for 33% fewer effective epochs than a 43-image one.
        # When the caller didn't pass an explicit target, normalise to
        # ~ZYG_LORA_EPOCHS effective epochs over the actual image count,
        # clamped so tiny/huge datasets can't produce degenerate schedules.
        if total_steps == _QUICK_STEPS and os.environ.get(
            'ZYG_LORA_EPOCH_SCALED',
            '1',
        ).strip().lower() not in ('0', 'false', 'no', 'off'):
            try:
                _n_imgs = sum(1 for f in os.listdir(dataset_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
            except OSError:
                _n_imgs = 0
            if _n_imgs:
                _epochs = max(5, int(os.environ.get('ZYG_LORA_EPOCHS', '26')))
                # max_steps=None -> the global ceiling; 0 -> no ceiling at all.
                _ceil = _EPOCH_STEP_CEIL if max_steps is None else max_steps
                _want = max(_EPOCH_STEP_FLOOR, _n_imgs * _epochs)
                total_steps = min(_want, _ceil) if _ceil else _want
                logger.info(
                    f'[LoraTrainer] {char_id}: epoch-scaled steps — {_n_imgs} images '
                    f'× {_epochs} epochs → {total_steps} steps'
                    + (
                        f' (CAPPED at {_ceil}; {_want} would give the full '
                        f'{_epochs} passes, {total_steps / _n_imgs:.1f} as scheduled)'
                        if total_steps < _want
                        else f' ({total_steps / _n_imgs:.1f} passes per image)'
                    ),
                )

        mf = _normalize_train_family(model_family)

        # 2026-08-09 licence pause. Training on FLUX.1-dev mints a NEW derivative
        # of a non-commercially-licensed base (_TRAIN_MODEL_PATH prefers flux1-dev
        # and the schnell fallback is explicitly rejected for LoRA quality), and
        # this channel is monetised. Refuse through the existing refusal protocol
        # rather than raising: callers already handle '' + last_start_result().
        if mf == 'flux':
            try:
                from zyg_workflows import licence_provenance as _lp

                if _lp.flux_paused():
                    logger.warning(
                        f'[LoraTrainer] {char_id}: FLUX training PAUSED — flux1-dev is '
                        f'under the BFL Non-Commercial License. '
                        f'ZYG_FLUX_RENDERS=allowed to resume.',
                    )
                    return _record_start_result(
                        char_id,
                        False,
                        'flux_licence_paused',
                        mf,
                        trigger_token,
                    )
            except ImportError as _exc:
                _zyg_log.warning('licence_provenance unavailable, the FLUX licence pause check was skipped: %s', _exc)

        if char_id in _training_jobs and not _training_jobs[char_id].failed:
            job = _training_jobs[char_id]
            if job.done and job.model_family == mf:
                logger.info(f'[LoraTrainer] {char_id}: already trained ({mf}) — skipping')
                return _record_start_result(
                    char_id,
                    False,
                    'already_trained',
                    mf,
                    trigger_token,
                )
            if not job.done:
                logger.warning(
                    f'[LoraTrainer] {char_id}: training in progress ({job.model_family}) — '
                    f'REFUSING to start {mf}; no {mf} training was launched by this call',
                )
                return _record_start_result(
                    char_id,
                    False,
                    f'busy_training_{_normalize_train_family(job.model_family)}',
                    mf,
                    trigger_token,
                )

        job = TrainingJob(
            char_id,
            dataset_dir,
            trigger_token,
            total_steps,
            model_family=mf,
            output_root=output_root,
            cleanup_after=cleanup_after,
            lora_version=lora_version,
            loss_mask_dir=loss_mask_dir,
            train_mode=train_mode,
            validation_prompt=validation_prompt,
        )
        _training_jobs[char_id] = job
        _VRAM_RELEASED_EVENT.clear()  # Training starting — VRAM will be consumed

        t = threading.Thread(target=self._train_worker, args=(job,), daemon=True, name=f'lora-train-{char_id[:8]}')
        job.thread = t
        t.start()
        logger.info(
            f'[LoraTrainer] {char_id}: training thread started (family={mf}, trigger={trigger_token})',
        )
        return _record_start_result(char_id, True, 'launched', mf, trigger_token)

    def get_status(
        self,
        char_id: str,
        model_family: str | None = None,
        output_root: str | None = None,
    ) -> dict:
        """Return current training status for a char_id.

        Falls back to filesystem scan when the job is not in memory (e.g.
        after a server restart) so that fully-trained LoRAs are still
        discoverable without re-running training.
        """
        mf_want = _normalize_train_family(model_family) if model_family else None
        job = _training_jobs.get(char_id)
        # 2026-07-31: mf_want used to be consulted ONLY inside the disk-recovery
        # branch below, so an in-memory job answered for EVERY family. _training_jobs
        # is keyed by char_id alone (one slot per character), and the dual-LoRA flow
        # (ZYG_CHAR_DUAL_LORA_PHOTOREAL=1) trains flux then sdxl for the same
        # char_id — the second start_training overwrote the slot and the first
        # family's status was misreported forever: a FLUX caller was handed the
        # SDXL lora_path (preview aborts with lora_load_failed), and a failed SDXL
        # leg made pipeline_storyteller drop to IPAdapter-only even though a valid
        # FLUX adapter sat on disk. Apply the same family gate get_lora_path uses:
        # on a mismatch fall through to disk recovery, which IS family-scoped.
        # ZYG_LORA_STATUS_FAMILY_STRICT=0 restores the pre-fix behaviour.
        if (
            job is not None
            and mf_want
            and _normalize_train_family(job.model_family) != mf_want
            and os.environ.get(
                'ZYG_LORA_STATUS_FAMILY_STRICT',
                '1',
            )
            .strip()
            .lower()
            not in ('0', 'false', 'no', 'off')
        ):
            logger.debug(
                f'[LoraTrainer] {char_id}: in-memory job is '
                f'{job.model_family}, caller asked for {mf_want} — '
                f'resolving {mf_want} from disk',
            )
            job = None
        if job is None:
            # Try to recover status from disk (crash/restart recovery)
            root = output_root or _OUTPUT_ROOT
            output_dir = os.path.join(root, char_id)
            trigger = f'ZYG_CHAR_{char_id[:6].upper()}'
            _disk_mf = _read_disk_train_family(output_dir)
            lora_path = _find_latest_checkpoint(output_dir, mf_want or _disk_mf)
            # Qwen never shares status files with FLUX: the flux/legacy fallback
            # names below would hand a qwen query flux's trigger_token/metadata.
            for _name in ([f'training_status_{mf_want}.json'] if mf_want else []) + (
                [
                    'training_status_flux.json',
                    'training_status.json',
                ]
                if mf_want not in ('qwen', 'klein')
                else []
            ):
                try:
                    with open(os.path.join(output_dir, _name)) as _sf:
                        _saved = json.load(_sf)
                    _disk_mf = _normalize_train_family(_saved.get('model_family'))
                    trigger = _saved.get('trigger_token', trigger)
                    break
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('training status %s unreadable, trying the next name: %s', _name, _exc)
                    continue
            if mf_want and _disk_mf and _disk_mf != mf_want:
                lora_path = None
            if (
                lora_path
                and mf_want
                and not _checkpoint_matches_family(
                    lora_path,
                    output_dir,
                    mf_want,
                )
            ):
                lora_path = None
            if lora_path:
                # A safetensors file on disk means training completed (or
                # reached a usable checkpoint).  Derive step count from the
                # checkpoint directory name (e.g. checkpoint-2000 → 2000).
                import re as _re

                _m = _re.search(r'checkpoint-(\d+)', lora_path)
                step = int(_m.group(1)) if _m else _QUICK_STEPS
                # Load persisted status (family-scoped first) for accurate metadata
                _saved_start_time = None
                _saved_total_steps = None
                try:
                    _sp = _status_path_for(output_dir, mf_want or _disk_mf)
                    if not os.path.isfile(_sp) and mf_want not in ('qwen', 'klein'):
                        _sp = os.path.join(output_dir, 'training_status.json')
                    with open(_sp) as _sf:
                        _saved = json.load(_sf)
                    trigger = _saved.get('trigger_token', trigger)
                    step = _saved.get('step', step)
                    _saved_start_time = _saved.get('start_time')
                    _saved_total_steps = _saved.get('total_steps')
                except Exception as _exc:
                    _zyg_log.warning(
                        'training status for %s unreadable, reporting the in-memory step instead: %s', char_id, _exc
                    )
                _result = {
                    'char_id': char_id,
                    'step': step,
                    'total_steps': _QUICK_STEPS,
                    'pct': min(100.0, step / _QUICK_STEPS * 100),
                    'done': True,
                    'failed': False,
                    'error': None,
                    'lora_path': lora_path,
                    'trigger_token': trigger,
                    'model_family': _disk_mf or 'flux',
                    'status': 'done',
                }
                # 2026-08-09: a status file with a recorded start_time means this
                # recovery had a live step count alongside it — surface elapsed/eta
                # computed from it. Pure checkpoint-only recovery (no status file,
                # or one predating this field) leaves these keys absent rather than
                # fabricating a guess.
                if _saved_start_time:
                    _result.update(
                        _progress_fields(
                            _saved_start_time,
                            step,
                            _saved_total_steps or _QUICK_STEPS,
                        )
                    )
                return _result
            return {
                'char_id': char_id,
                'step': 0,
                'total_steps': 0,
                'pct': 0,
                'done': False,
                'failed': False,
                'error': None,
                'lora_path': None,
                'trigger_token': None,
                'status': 'not_found',
            }
        d = job.to_dict()
        d['status'] = 'done' if job.done else ('failed' if job.failed else 'training')
        return d

    def get_lora_path(
        self,
        char_id: str,
        model_family: str | None = None,
        output_root: str | None = None,
    ) -> Optional[str]:
        """Return the safetensors path once training completes, else None."""
        mf = _normalize_train_family(model_family) if model_family else None
        job = _training_jobs.get(char_id)
        if job and job.done and (not mf or job.model_family == mf):
            return job.lora_path
        root = output_root or (job.output_root if job else _OUTPUT_ROOT)
        output_dir = os.path.join(root, char_id)
        if mf:
            # Read the FAMILY-SCOPED status first; only fall back to the legacy
            # shared file if the scoped one is absent. Without this, the sdxl
            # lookup read a training_status.json that the flux v2 refine had just
            # overwritten (family='flux') and always returned None.
            saved = None
            for _name in (f'training_status_{mf}.json', 'training_status.json'):
                try:
                    with open(os.path.join(output_dir, _name)) as _sf:
                        saved = json.load(_sf)
                    break
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('training status %s unreadable, trying the next name: %s', _name, _exc)
                    continue
            # If a scoped status exists it must match; if only the legacy file
            # exists and mismatches, fall through to the on-disk checkpoint scan
            # (the weights dir is itself family-named) rather than hard-failing.
            _scoped = os.path.isfile(os.path.join(output_dir, f'training_status_{mf}.json'))
            if saved is not None and _scoped and _normalize_train_family(saved.get('model_family')) != mf:
                return None
        return _find_latest_checkpoint(output_dir, mf)

    # ── Worker ────────────────────────────────────────────────────────────────────
    def _train_worker(self, job: TrainingJob):
        try:
            self._run_training(job)
        except Exception as exc:
            logger.error(f'[LoraTrainer] {job.char_id}: uncaught error: {exc}', exc_info=True)
            job.failed = True
            job.error_msg = str(exc)

    def _run_training(self, job: TrainingJob):
        """Run one SimpleTuner training to its end, phase by phase.

        The orchestrator of `service_training`: each phase of the old 389-line
        body is one function there, called where the block stood. Every `return`
        here is one the monolith made, and the phase that returns False (or
        `ready=False`) has already written the job's status and released the
        VRAM event — nothing to undo at this level.
        """
        os.makedirs(job.output_dir, exist_ok=True)

        # ── Check base model available ────────────────────────────────────────────
        base = _training.prepare_base_model(job)
        if not base.ready:
            return

        # ── Write SimpleTuner config ──────────────────────────────────────────────
        config_dir = _training.write_simpletuner_config(job, base)

        # ── Pre-flight VRAM eviction ──────────────────────────────────────────────
        _training.preflight_vram(job)

        # ── Launch SimpleTuner ────────────────────────────────────────────────────
        if not _training.launch_simpletuner(job, config_dir):
            return

        log_path = os.path.join(job.output_dir, f'training_{job.model_family}.log')
        _training.stream_training_log(job, log_path)

        ret = job.proc.wait()
        if ret != 0:
            _training.handle_nonzero_exit(job, ret, log_path)
            return

        _training.finalize_success(job)
