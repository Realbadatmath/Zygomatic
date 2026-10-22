# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
lora_trainer_service.py
=======================
Background FLUX / SDXL / Qwen LoRA training wrapper using SimpleTuner.

Usage::

    from zyg_workflows.lora_trainer_service import LoraTrainerService
    svc = LoraTrainerService()
    svc.start_training('abc123', '$ZYG_LORA_DATASETS/storyteller_chars/abc123')
    # ... later ...
    status = svc.get_status('abc123')
    # {'step': 450, 'total_steps': 1000, 'done': False, 'lora_path': None}
    # or when done:
    # {'step': 1000, 'total_steps': 1000, 'done': True, 'lora_path': '/path/to/lora.safetensors'}

SimpleTuner is at $ZYG_SIMPLETUNER_DIR (default ~/SimpleTuner).
FLUX.1-dev weights are required for training (flux1-schnell is inference-only).
If FLUX.1-dev is unavailable, training is skipped and IPAdapter-only mode is used.
"""

import os
import re
import json
import logging
import shutil
import subprocess
import threading
import time
from typing import Optional
import logging as _zyg_logging
from zyg_workflows import paths


# ── Sections (imported in the original declaration order) ───────────────────────
from zyg_workflows.lora_trainer_service.model_paths import (
    _SIMPLE_TUNER_DIR,
    _DATASET_ROOT,
    _OUTPUT_ROOT,
    _CREATURE_OUTPUT_ROOT,
    _FLUX_DEV_PATH,
    _FLUX_SCHNELL_PATH,
    _TRAIN_MODEL_PATH,
    _SDXL_COMFY_CKPT,
    _SDXL_DIFFUSERS_HF_ID,
    _SDXL_DIFFUSERS_HF_REVISION,
    _SDXL_HF_CACHE_ROOT,
    _SDXL_LOCAL_DIFFUSERS,
    _SDXL_WEIGHT_FILENAMES,
    _QWEN_HF_ID,
    _QWEN_PINNED_REV,
    _QWEN_HF_SNAPSHOT,
    _QWEN_LOCAL_DIFFUSERS,
    _KLEIN_HF_ID,
    _KLEIN_PINNED_REV,
    _KLEIN_LOCAL_DIFFUSERS,
    _sdxl_submodel_has_weights,
    _sdxl_diffusers_complete,
    _iter_sdxl_diffusers_candidates,
    _resolve_sdxl_train_path,
    _ensure_sdxl_diffusers_weights,
    _sdxl_train_model_ready,
    _qwen_submodel_has_weights,
    _qwen_diffusers_complete,
    _resolve_qwen_train_path,
    _ensure_qwen_diffusers_weights,
    _klein_diffusers_complete,
    _resolve_klein_train_path,
    _ensure_klein_diffusers_weights,
    _DEPRECATED_ST_CONFIG_KEYS,
    _GROUP_OFFLOAD_KEYS,
    _QUICK_STEPS,
    _EPOCH_STEP_FLOOR,
    _EPOCH_STEP_CEIL,
    _STATUS_SAVE_INTERVAL_S,
)
from zyg_workflows.lora_trainer_service.job_state import (
    _training_jobs,
    _last_start_results,
    _record_start_result,
    last_start_result,
    _VRAM_RELEASED_EVENT,
    _normalize_train_family,
    _family_lora_weights_dir,
    _legacy_lora_weights_dir,
    _read_disk_train_family,
    _iso_utc,
    _progress_fields,
    TrainingJob,
)
from zyg_workflows.lora_trainer_service.service import (
    LoraTrainerService,
)
from zyg_workflows.lora_trainer_service.config_support import (
    cleanup_char_training,
    _cleanup_after_training,
)
from zyg_workflows.lora_trainer_service.st_config import (
    _ensure_preview_captions,
    _read_trained_scale,
    stamp_lora_alpha,
    _validation_prompt,
    _validation_interval,
    _read_config_value,
    _drop_stale_benchmarks,
)
from zyg_workflows.lora_trainer_service.st_config_writers import (
    _write_st_config_flux,
    _write_st_config_sdxl,
    _write_st_config_qwen,
    _write_st_config_klein,
    _write_st_multidatabackend,
)
from zyg_workflows.lora_trainer_service.helpers import (
    _EXPORT_NAME_ORDER,
    _export_name_rank,
    _scan_lora_weights_dir,
    _find_latest_checkpoint,
    _legacy_dir_is_unclaimed_flux,
    _checkpoint_matches_family,
    _status_path_for,
    _save_status,
)
from zyg_workflows.lora_trainer_service.singleton import (
    _trainer_instance,
    get_trainer,
)

_zyg_log = _zyg_logging.getLogger(__name__)
logger = logging.getLogger(__name__)


# ── re-export surface ─────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: this file
# exists so that ``zyg_workflows.lora_trainer_service.<name>``
# resolves exactly as it did on the pre-split single-file module.
# Nothing does ``import *`` from here.
__all__ = [
    'os',
    're',
    'json',
    'shutil',
    'subprocess',
    'threading',
    'time',
    'Optional',
    'paths',
    '_SIMPLE_TUNER_DIR',
    '_DATASET_ROOT',
    '_OUTPUT_ROOT',
    '_CREATURE_OUTPUT_ROOT',
    '_FLUX_DEV_PATH',
    '_FLUX_SCHNELL_PATH',
    '_TRAIN_MODEL_PATH',
    '_SDXL_COMFY_CKPT',
    '_SDXL_DIFFUSERS_HF_ID',
    '_SDXL_DIFFUSERS_HF_REVISION',
    '_SDXL_HF_CACHE_ROOT',
    '_SDXL_LOCAL_DIFFUSERS',
    '_SDXL_WEIGHT_FILENAMES',
    '_QWEN_HF_ID',
    '_QWEN_PINNED_REV',
    '_QWEN_HF_SNAPSHOT',
    '_QWEN_LOCAL_DIFFUSERS',
    '_KLEIN_HF_ID',
    '_KLEIN_PINNED_REV',
    '_KLEIN_LOCAL_DIFFUSERS',
    '_sdxl_submodel_has_weights',
    '_sdxl_diffusers_complete',
    '_iter_sdxl_diffusers_candidates',
    '_resolve_sdxl_train_path',
    '_ensure_sdxl_diffusers_weights',
    '_sdxl_train_model_ready',
    '_qwen_submodel_has_weights',
    '_qwen_diffusers_complete',
    '_resolve_qwen_train_path',
    '_ensure_qwen_diffusers_weights',
    '_klein_diffusers_complete',
    '_resolve_klein_train_path',
    '_ensure_klein_diffusers_weights',
    '_DEPRECATED_ST_CONFIG_KEYS',
    '_GROUP_OFFLOAD_KEYS',
    '_QUICK_STEPS',
    '_EPOCH_STEP_FLOOR',
    '_EPOCH_STEP_CEIL',
    '_STATUS_SAVE_INTERVAL_S',
    '_training_jobs',
    '_last_start_results',
    '_record_start_result',
    'last_start_result',
    '_VRAM_RELEASED_EVENT',
    '_normalize_train_family',
    '_family_lora_weights_dir',
    '_legacy_lora_weights_dir',
    '_read_disk_train_family',
    '_iso_utc',
    '_progress_fields',
    'TrainingJob',
    'LoraTrainerService',
    'cleanup_char_training',
    '_cleanup_after_training',
    '_ensure_preview_captions',
    '_read_trained_scale',
    'stamp_lora_alpha',
    '_validation_prompt',
    '_validation_interval',
    '_read_config_value',
    '_drop_stale_benchmarks',
    '_write_st_config_flux',
    '_write_st_config_sdxl',
    '_write_st_config_qwen',
    '_write_st_config_klein',
    '_write_st_multidatabackend',
    '_EXPORT_NAME_ORDER',
    '_export_name_rank',
    '_scan_lora_weights_dir',
    '_find_latest_checkpoint',
    '_legacy_dir_is_unclaimed_flux',
    '_checkpoint_matches_family',
    '_status_path_for',
    '_save_status',
    '_trainer_instance',
    'get_trainer',
]
