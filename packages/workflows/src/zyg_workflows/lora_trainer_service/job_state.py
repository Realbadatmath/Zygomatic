# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Global job state, progress helpers and the TrainingJob record."""

import os
import json
import logging
import subprocess
import threading
import time
from typing import Optional
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.model_paths import (  # noqa: F401
    _OUTPUT_ROOT,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')

# ── Global job state ─────────────────────────────────────────────────────────────
_training_jobs: dict = {}  # char_id → TrainingJob

# Outcome of the most recent start_training() call per char_id (2026-07-31):
# {'started': bool, 'reason': str, 'model_family': str, 'trigger_token': str, 'ts': float}
_last_start_results: dict = {}


def _record_start_result(
    char_id: str,
    started: bool,
    reason: str,
    model_family: str,
    trigger_token: str,
) -> str:
    """Record a start_training outcome; return what start_training should return.

    A refusal returns '' so the caller can tell it apart from a launch; the
    reason stays available via last_start_result(). Set
    ZYG_LORA_START_SIGNAL_REFUSAL=0 to return the trigger token either way
    (pre-2026-07-31 behaviour) — the record is written regardless.
    """
    _last_start_results[char_id] = {
        'started': bool(started),
        'reason': reason,
        'model_family': _normalize_train_family(model_family),
        'trigger_token': trigger_token,
        'ts': time.time(),
    }
    if started or os.environ.get(
        'ZYG_LORA_START_SIGNAL_REFUSAL',
        '1',
    ).strip().lower() in ('0', 'false', 'no', 'off'):
        return trigger_token
    return ''


def last_start_result(char_id: str) -> dict:
    """Outcome of the last start_training() for *char_id* ({} when never called)."""
    return dict(_last_start_results.get(char_id) or {})


# Set when any training job finishes (done or failed); cleared when new training starts.
# The storyteller pipeline waits on this before loading FLUX Dev so both never share VRAM.
_VRAM_RELEASED_EVENT = threading.Event()
_VRAM_RELEASED_EVENT.set()  # No training active at startup → VRAM is free


def _normalize_train_family(model_family: str | None) -> str:
    mf = (model_family or 'flux').strip().lower()
    return mf if mf in ('flux', 'sdxl', 'qwen', 'klein') else 'flux'


def _family_lora_weights_dir(output_dir: str, model_family: str) -> str:
    """Per-family output dir so SDXL checkpoints are never resumed for FLUX (and vice versa)."""
    mf = _normalize_train_family(model_family)
    return os.path.join(output_dir, f'lora-weights-{mf}')


def _legacy_lora_weights_dir(output_dir: str) -> str:
    return os.path.join(output_dir, 'lora-weights')


def _read_disk_train_family(output_dir: str) -> str | None:
    for name in (
        'training_status_flux.json',
        'training_status_sdxl.json',
        'training_status_qwen.json',
        'training_status_klein.json',
        'training_status.json',
    ):
        try:
            with open(os.path.join(output_dir, name)) as sf:
                return _normalize_train_family(json.load(sf).get('model_family'))
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('training status %s unreadable, trying the next name: %s', name, _exc)
            continue
    return None


def _iso_utc(epoch_s: float) -> str:
    """UTC ISO-8601 timestamp ('...Z') for an epoch-seconds value."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch_s))


def _progress_fields(start_time: float | None, step: int, total_steps: int) -> dict:
    """Elapsed/rate/ETA fields shared by TrainingJob.to_dict() and the disk-recovery
    branch of get_status() (2026-08-09), so a live view and a post-restart-recovered
    view agree on how these are computed. Returns None fields rather than a fabricated
    guess when there isn't enough data yet (job just started, or start_time unknown).
    """
    if not start_time:
        return {
            'start_time': None,
            'elapsed_s': None,
            'step_rate': None,
            'eta_s': None,
            'eta_iso': None,
        }
    elapsed_s = round(time.time() - start_time, 1)
    step_rate = (step / elapsed_s) if step > 0 and elapsed_s > 0 else None
    eta_s = None
    if step_rate and total_steps and step < total_steps:
        eta_s = round((total_steps - step) / step_rate)
    eta_iso = _iso_utc(time.time() + eta_s) if eta_s is not None else None
    return {
        'start_time': start_time,
        'elapsed_s': elapsed_s,
        'step_rate': step_rate,
        'eta_s': eta_s,
        'eta_iso': eta_iso,
    }


class TrainingJob:
    """Holds live state for one LoRA training run."""

    def __init__(
        self,
        char_id: str,
        dataset_dir: str,
        trigger_token: str,
        total_steps: int,
        model_family: str = 'flux',
        output_root: str | None = None,
        cleanup_after: bool = True,
        lora_version: int = 1,
        loss_mask_dir: str | None = None,
        train_mode: str = 'identity',
        validation_prompt: str | None = None,
    ):
        self.char_id = char_id
        self.dataset_dir = dataset_dir
        # loss_mask_dir: directory of greyscale masks paired by filename with
        # dataset_dir. Black pixels are excluded from the loss (SimpleTuner
        # conditioning mask). None = today's behaviour, byte-identical config.
        self.loss_mask_dir = loss_mask_dir
        self.train_mode = train_mode or 'identity'
        # validation_prompt: overrides the train_mode branch in
        # _validation_prompt(). Set it when the subject is not a person — a
        # creature or an animal renders as a HUMAN under either default branch.
        # None = today's behaviour, byte-identical config.
        self.validation_prompt = (validation_prompt or '').strip() or None
        self.trigger_token = trigger_token
        self.total_steps = total_steps
        # cleanup_after=False keeps checkpoint-* dirs after this training so a
        # flywheel v2 refine can actually --resume_from_checkpoint (2026-07-18:
        # v1's own cleanup used to delete them, silently turning every "refine"
        # into a full from-scratch retrain). The caller sweeps at run end.
        self.cleanup_after = bool(cleanup_after)
        self.lora_version = max(1, int(lora_version or 1))
        self.model_family = _normalize_train_family(model_family)
        self.step = 0
        self.done = False
        self.failed = False
        self.error_msg = ''
        self.lora_path: Optional[str] = None
        self.sdxl_comfy_checkpoint: Optional[str] = None
        self.log_tail: list = []  # last 25 lines of training.log on failure
        self.thread: Optional[threading.Thread] = None
        self.proc: Optional[subprocess.Popen] = None
        self.output_root = output_root or _OUTPUT_ROOT
        self.output_dir = os.path.join(self.output_root, char_id)
        # Anchor for elapsed_s/step_rate/eta_s (see to_dict()). The job object is
        # created exactly when start_training() launches the training thread, so
        # this is the right "training start" instant — not a guess.
        self.start_time = time.time()

    def to_dict(self) -> dict:
        d = {
            'char_id': self.char_id,
            'step': self.step,
            'total_steps': self.total_steps,
            'pct': round(self.step / max(self.total_steps, 1) * 100, 1),
            'done': self.done,
            'failed': self.failed,
            'error': self.error_msg[:300] if self.failed else None,
            'log_tail': self.log_tail[-10:] if self.failed else [],
            'lora_path': self.lora_path,
            'trigger_token': self.trigger_token,
            'model_family': self.model_family,
            'sdxl_comfy_checkpoint': self.sdxl_comfy_checkpoint,
        }
        # 2026-08-09: additive real elapsed/rate/ETA so live views (Medusa :5300
        # Training tab, /gpu_schedule.html) can show a real countdown instead of a
        # guessed constant. _save_status() persists these too since it just spreads
        # to_dict() to disk.
        d.update(_progress_fields(self.start_time, self.step, self.total_steps))
        return d
