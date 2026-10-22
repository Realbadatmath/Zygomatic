# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Character state service — job state, LoRA discovery, preview render and training.

Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).

2026-10-06: the 3,589-line char_state_service.py became this package. Every section
moved verbatim; the import path, every public and underscore name and the section
order are unchanged. The original top import block is re-done below so attribute
accesses like ``char_state_service.os`` still resolve.
"""

import json
import os
import time
import threading
from datetime import datetime, timezone
from zyg_workflows import gui_state

from zyg_workflows import paths
from zyg_workflows import runtime as _runtime
from zyg_workflows.vram_manager import _release_pipeline_vram
from zyg_workflows.pipeline_config import (
    _ANIMATED_USE_FLUX,
    _CHAR_DEFAULT_MODEL_FAMILY,
    _CHAR_DRIFT_ANIMATED,
    _CHAR_DRIFT_MIN,
    _CHAR_DUAL_LORA_PHOTOREAL,
    _CHAR_PHOTOREAL_HYBRID_PREVIEW,
    _CHAR_STATE_FILENAME_FMT,
    _CONTACT_SHEET_STATE_FMT,
    _PHOTOREAL_CLIP_NEG,
    _PHOTOREAL_CLIP_POS,
    _PREVIEW_FACE_SEED_CANDIDATES,
    _PREVIEW_LORA_WAIT_S,
    _PREVIEW_SEED_CANDIDATES,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _ams_now,
    _char_gen_jobs,
    _contact_sheet_jobs,
    _contact_sheet_push_review_pending,
    _creature_gen_jobs,
    _parse_iso_to_ams,
    _runtime_path,
)
import logging as _zyg_logging

from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
    _CHARS_OUTPUTS,
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.char_state import (
    _char_save_state,
    _char_stage_end,
    _char_stage_start,
    _char_state_path,
)
from zyg_workflows.char_state_service.contact_sheet import (
    _bg_contact_sheet_pipeline,
    _contact_sheet_close_running_timeline,
    _contact_sheet_derive_stage,
    _contact_sheet_emit,
    _contact_sheet_orphan_stale_running_job,
    _contact_sheet_release_run_vram,
    _contact_sheet_release_vram_on_done,
    _contact_sheet_reload_jobs_from_disk,
    _contact_sheet_resume_run,
    _contact_sheet_save_state,
    _contact_sheet_stage_end,
    _contact_sheet_stage_start,
    _contact_sheet_state_path,
    _contact_sheet_worker_alive,
)
from zyg_workflows.char_state_service.creature import (
    CREATURE_STAGE_ORDER,
    _creature_derive_pipeline_stage,
    _creature_external_pid_alive,
    _creature_mark_stale,
    _creature_refresh_external,
    _creature_reload_jobs_from_disk,
    _creature_save_state,
    _creature_stage_key,
    _creature_state_path,
    _creature_worker_alive,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_effective_hybrid_preview,
    _char_family_lora_dirs,
    _char_family_lora_weights_exist,
    _char_has_sdxl_lora,
    _char_is_photoreal_style,
    _char_library_trained_at,
    _char_lora_family_roots,
    _char_lora_output_ready,
    _char_lora_train_families,
    _char_newest_iso,
    _char_photoreal_hybrid_preview,
    _char_preview_png_names,
    _char_preview_slot_lora_path,
    _char_preview_slot_names,
    _char_render_style,
    _char_restyle_profile,
    _char_trained_at_from_adapters,
    _char_trained_at_from_status,
    _char_trained_at_from_timeline,
    _discover_char_lora_deep,
    _discover_char_sdxl_lora,
    _lora_checkpoint_num,
    _normalize_char_model_family,
    _resolve_char_model_family,
)
from zyg_workflows.char_state_service.preview_provenance import (
    _char_sync_preview_legacy_aliases,
    _preview_family_from_name,
    _preview_provenance_path,
    _preview_restyle_name,
    _read_preview_provenance,
    _write_preview_provenance,
)
from zyg_workflows.char_state_service.job_state import (
    _char_close_running_timeline,
    _char_derive_pipeline_stage,
    _char_mark_done,
    _char_mark_error,
    _char_orphan_stale_running_job,
    _char_reconcile_job_state,
    _char_reload_jobs_from_disk,
)
from zyg_workflows.char_state_service.preview_slots import (
    _build_char_preview_slots,
)
from zyg_workflows.char_state_service.preview_reference import (
    _char_contact_sheet_anchor,
    _char_id_from_info,
    _char_is_blender_dataset,
    _have_usable_char_preview,
    _is_generated_preview_name,
    _iter_info_image_paths,
    _pick_char_preview_reference,
    _pick_char_preview_reference_for_slot,
    _preview_backend_tier,
)
from zyg_workflows.char_state_service.preview_qa import (
    _generate_preview_slot_best_of_n,
    _preview_attempt_rank,
    _preview_face_yolo_count,
    _preview_hand_qa,
    _preview_hand_yolo_score,
)
from zyg_workflows.char_state_service.render_slots import (
    _render_char_preview_slots,
)
from zyg_workflows.char_state_service.render_images import (
    _render_char_preview_images,
    _render_char_preview_images_comfy,
    _render_char_preview_images_sdxl,
)
from zyg_workflows.char_state_service.lora_training import (
    _char_params_from_bible,
    _char_train_lora_for_family,
)

# ── re-export surface ────────────────────────────────────────────────────────
# Every name above is imported for re-export, not for use in this file: the
# blueprints and the pipelines read them off this module with
# ``from zyg_workflows.char_state_service import X`` or ``getattr(mod, 'X')``,
# and the original top import block is re-done here so attribute accesses like
# ``char_state_service.os`` still resolve (see the docstring's contract).
# Declaring them is what makes the re-export deliberate rather than an unused
# import; nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    'json',
    'os',
    'time',
    'threading',
    'datetime',
    'timezone',
    'gui_state',
    'paths',
    '_runtime',
    '_release_pipeline_vram',
    '_ANIMATED_USE_FLUX',
    '_CHAR_DEFAULT_MODEL_FAMILY',
    '_CHAR_DRIFT_ANIMATED',
    '_CHAR_DRIFT_MIN',
    '_CHAR_DUAL_LORA_PHOTOREAL',
    '_CHAR_PHOTOREAL_HYBRID_PREVIEW',
    '_CHAR_STATE_FILENAME_FMT',
    '_CONTACT_SHEET_STATE_FMT',
    '_PHOTOREAL_CLIP_NEG',
    '_PHOTOREAL_CLIP_POS',
    '_PREVIEW_FACE_SEED_CANDIDATES',
    '_PREVIEW_LORA_WAIT_S',
    '_PREVIEW_SEED_CANDIDATES',
    '_ams_iso',
    '_ams_now',
    '_char_gen_jobs',
    '_contact_sheet_jobs',
    '_contact_sheet_push_review_pending',
    '_creature_gen_jobs',
    '_parse_iso_to_ams',
    '_runtime_path',
    '_zyg_logging',
    '_CHARS_DATASETS',
    '_CHARS_OUTPUTS',
    '_preview_env_on',
    '_zyg_log',
    '_char_save_state',
    '_char_stage_end',
    '_char_stage_start',
    '_char_state_path',
    '_bg_contact_sheet_pipeline',
    '_contact_sheet_close_running_timeline',
    '_contact_sheet_derive_stage',
    '_contact_sheet_emit',
    '_contact_sheet_orphan_stale_running_job',
    '_contact_sheet_release_run_vram',
    '_contact_sheet_release_vram_on_done',
    '_contact_sheet_reload_jobs_from_disk',
    '_contact_sheet_resume_run',
    '_contact_sheet_save_state',
    '_contact_sheet_stage_end',
    '_contact_sheet_stage_start',
    '_contact_sheet_state_path',
    '_contact_sheet_worker_alive',
    'CREATURE_STAGE_ORDER',
    '_creature_derive_pipeline_stage',
    '_creature_external_pid_alive',
    '_creature_mark_stale',
    '_creature_refresh_external',
    '_creature_reload_jobs_from_disk',
    '_creature_save_state',
    '_creature_stage_key',
    '_creature_state_path',
    '_creature_worker_alive',
    '_char_effective_hybrid_preview',
    '_char_family_lora_dirs',
    '_char_family_lora_weights_exist',
    '_char_has_sdxl_lora',
    '_char_is_photoreal_style',
    '_char_library_trained_at',
    '_char_lora_family_roots',
    '_char_lora_output_ready',
    '_char_lora_train_families',
    '_char_newest_iso',
    '_char_photoreal_hybrid_preview',
    '_char_preview_png_names',
    '_char_preview_slot_lora_path',
    '_char_preview_slot_names',
    '_char_render_style',
    '_char_restyle_profile',
    '_char_trained_at_from_adapters',
    '_char_trained_at_from_status',
    '_char_trained_at_from_timeline',
    '_discover_char_lora_deep',
    '_discover_char_sdxl_lora',
    '_lora_checkpoint_num',
    '_normalize_char_model_family',
    '_resolve_char_model_family',
    '_char_sync_preview_legacy_aliases',
    '_preview_family_from_name',
    '_preview_provenance_path',
    '_preview_restyle_name',
    '_read_preview_provenance',
    '_write_preview_provenance',
    '_char_close_running_timeline',
    '_char_derive_pipeline_stage',
    '_char_mark_done',
    '_char_mark_error',
    '_char_orphan_stale_running_job',
    '_char_reconcile_job_state',
    '_char_reload_jobs_from_disk',
    '_build_char_preview_slots',
    '_char_contact_sheet_anchor',
    '_char_id_from_info',
    '_char_is_blender_dataset',
    '_have_usable_char_preview',
    '_is_generated_preview_name',
    '_iter_info_image_paths',
    '_pick_char_preview_reference',
    '_pick_char_preview_reference_for_slot',
    '_preview_backend_tier',
    '_generate_preview_slot_best_of_n',
    '_preview_attempt_rank',
    '_preview_face_yolo_count',
    '_preview_hand_qa',
    '_preview_hand_yolo_score',
    '_render_char_preview_slots',
    '_render_char_preview_images',
    '_render_char_preview_images_comfy',
    '_render_char_preview_images_sdxl',
    '_char_params_from_bible',
    '_char_train_lora_for_family',
]
