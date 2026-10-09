# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Post-training cleanup of a character training run."""

import os
import logging
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.model_paths import (  # noqa: F401
    _DATASET_ROOT,
)
from zyg_workflows.lora_trainer_service.job_state import (  # noqa: F401
    TrainingJob,
    _family_lora_weights_dir,
    _legacy_lora_weights_dir,
    _normalize_train_family,
    _training_jobs,
)
from zyg_workflows.lora_trainer_service.helpers import (  # noqa: F401
    _find_latest_checkpoint,
    _save_status,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')


def cleanup_char_training(
    char_id: str,
    model_family: str = 'flux',
    output_root: str | None = None,
    dataset_dir: str = '',
) -> None:
    """Public end-of-run sweep (2026-07-18): removes leftover checkpoint dirs
    for *char_id*. Used by the pipeline after the flywheel finishes (or is
    skipped) when v1 training deferred its own cleanup. Idempotent; keeps the
    recorded lora_path's directory and the root export like the internal path."""
    job = _training_jobs.get(char_id)
    if job is None or _normalize_train_family(job.model_family) != _normalize_train_family(model_family):
        job = TrainingJob(
            char_id,
            dataset_dir or os.path.join(_DATASET_ROOT, char_id, 'training'),
            f'ZYG_CHAR_{char_id[:6].upper()}',
            1,
            model_family=model_family,
            output_root=output_root,
        )
        job.lora_path = _find_latest_checkpoint(job.output_dir, job.model_family)
    _cleanup_after_training(job)
    # Same post-cleanup safety as the worker: never leave a recorded path
    # pointing at a file the sweep just removed.
    live = _training_jobs.get(char_id)
    if live is not None and live.lora_path and not os.path.isfile(live.lora_path):
        live.lora_path = _find_latest_checkpoint(live.output_dir, live.model_family)
        _save_status(live, 'done' if live.done else 'failed')
        try:
            from zyg_workflows import character_bible_service as _cbs_sw

            _cbs_sw.update_lora(char_id, live.lora_path, model_family=live.model_family)
        except Exception as _exc:
            _zyg_log.warning(
                'character bible LoRA registration for %s failed, the bible keeps the old path: %s', char_id, _exc
            )


def _cleanup_after_training(job: 'TrainingJob') -> None:
    """Free resume-only artifacts once training has a usable final LoRA.

    Deletes checkpoint-* dirs (optimizer.bin resume state dominates; only the
    checkpoint holding job.lora_path is kept, when the final resolved there
    instead of the root export) plus this family's SimpleTuner vae/text caches
    in the dataset dir — SimpleTuner regenerates those on the next run. Root
    end-of-run export, logs, validation images and configs are kept.
    Set ZYG_LORA_KEEP_CHECKPOINTS=1 to disable.
    """
    if os.environ.get('ZYG_LORA_KEEP_CHECKPOINTS') == '1':
        return
    import glob as _glob
    import shutil as _shutil

    keep_dir = ''
    if job.lora_path and (os.sep + 'checkpoint-') in job.lora_path:
        keep_dir = os.path.dirname(os.path.abspath(job.lora_path))
    mf = _normalize_train_family(job.model_family)
    removed = 0
    for wdir in {_family_lora_weights_dir(job.output_dir, mf), _legacy_lora_weights_dir(job.output_dir)}:
        if not os.path.isdir(wdir):
            continue
        for entry in os.scandir(wdir):
            if entry.is_dir() and entry.name.startswith('checkpoint-') and os.path.abspath(entry.path) != keep_dir:
                try:
                    _shutil.rmtree(entry.path)
                    removed += 1
                except OSError as exc:
                    logger.warning(f'[LoraTrainer] cleanup: could not remove {entry.path}: {exc}')
    # vae/text caches are kept by default — they make retraining the same char
    # faster and cost ~70 MB each (owner's 2026-07-16 call). Opt in to remove.
    caches = []
    if os.environ.get('ZYG_LORA_CLEAN_CACHES') == '1':
        caches = _glob.glob(os.path.join(job.dataset_dir, f'vae_cache_{mf}*')) + _glob.glob(
            os.path.join(job.dataset_dir, f'text_cache_{mf}*')
        )
        for cache in caches:
            try:
                _shutil.rmtree(cache)
            except OSError as exc:
                logger.warning(f'[LoraTrainer] cleanup: could not remove {cache}: {exc}')
    logger.info(
        f'[LoraTrainer] {job.char_id}: post-training cleanup — removed {removed} '
        f'checkpoint dir(s) and {len(caches)} cache dir(s), kept {job.lora_path}',
    )
