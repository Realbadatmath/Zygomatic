# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E402  package __init__: the late-import contract below is deliberate — the
# eight section modules do `from zyg_dashboard.bp_storyteller import ...` for `bp` and the
# shared globals this file binds first, so the import order is load-bearing.
# Every name is re-exported for importers of the old single-file module; they are declared
# in __all__ at the bottom.

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import json
import os
import re
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple
from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)
from zyg_workflows import gui_state
from zyg_workflows.paths import ZYG_LORA_DATASETS, ZYG_LORA_OUTPUTS

from zyg_workflows.char_state_service import (
    _char_library_trained_at,
    _char_lora_output_ready,
    _char_lora_train_families,
    _char_mark_done,
    _char_mark_error,
    _char_params_from_bible,
    _char_preview_png_names,
    _char_reconcile_job_state,
    _char_render_style,
    _char_save_state,
    _char_stage_end,
    _char_stage_start,
    _char_train_lora_for_family,
    _contact_sheet_emit,
    _contact_sheet_resume_run,
    _contact_sheet_state_path,
    _contact_sheet_worker_alive,
    _have_usable_char_preview,
    _normalize_char_model_family,
    _render_char_preview_images,
    _resolve_char_model_family,
)

bp = Blueprint('storyteller_internal', __name__)

# These three are late by design: each imports crewai_web_gui, which imports this
# blueprint at its bottom, so `bp` must already exist when they run.
from zyg_dashboard.bp_claude_clip import _record_token_usage  # noqa: E402  late: see comment above
from zyg_dashboard.bp_zero_public_store import (  # noqa: E402  late: see comment above
    _ZPUB_PENDING_LOCK,
    _zpub_pending_load,
    _zpub_pending_save,
)
from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: see comment above
    _apply_gpu_power_limit,
    _caveman_kw,
    _contact_sheet_launch_run,
    _contact_sheet_mark_manifest_approved,
    _contact_sheet_parse_start_payload,
    limiter,
)
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: see comment above

# Round-2 split homes (packages/dashboard/docs/gui_split_map.md): these names moved
# out of crewai_web_gui.py into zyg_dashboard.gui.*, which does not import back.
from zyg_dashboard.gui.runtime_state import (  # noqa: E402  late only by position, gui.* has no cycle
    _char_gen_jobs,
    _contact_sheet_jobs,
    _runtime_path,
)
from zyg_dashboard.gui.timeutil import _ams_iso  # noqa: E402  late only by position
from zyg_dashboard.gui.zero_store import _zero_audit_log  # noqa: E402  late only by position

_zyg_log = _zyg_logging.getLogger(__name__)


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
_dsl = getattr(_main_mod, '_dsl', None)


# ── 2026-10-06 modularization: the sections below moved into submodules of this
# package (see packages/dashboard/docs/bp_storyteller_split_map.md). They are
# imported in the ORIGINAL section order so every @bp.route registration and every
# module-level side effect still happens in exactly that order, and every name the
# single-file module defined is re-bound here so no importer needs editing.
from zyg_dashboard.bp_storyteller.guards import (
    _CHARS_DATASET_ROOT,
    _CHAR_ID_RE,
    _CHAR_ID_WIDE_RE,
    _PREVIEW_REGEN_JOBS,
    _PREVIEW_REGEN_LOCK,
    _PREVIEW_SLOT_STEMS,
    _SWEEP_LOCK,
    _char_lora_usable,
    _env_on,
    _is_medusa_cid,
    _preview_provenance_map,
    _production_paused,
    _restore_parked_char_photos,
    _save_uploaded_char_photos,
)

from zyg_dashboard.bp_storyteller.chars import (
    api_internal_creature_list,
    api_internal_storyteller_analyze_character_photo,
    api_internal_storyteller_list_chars,
)

from zyg_dashboard.bp_storyteller.contact_sheet import (
    api_internal_contact_sheet_approve,
    api_internal_contact_sheet_image,
    api_internal_contact_sheet_pause,
    api_internal_contact_sheet_resume,
    api_internal_contact_sheet_start,
    api_internal_contact_sheet_status,
    api_internal_list_contact_sheets,
    api_internal_pipeline_pause,
    api_internal_pipeline_pause_state,
    api_internal_pipeline_resume,
)

from zyg_dashboard.bp_storyteller.generate_worker import (
    _make_bg_generate,
)

from zyg_dashboard.bp_storyteller.generate_character import (
    api_internal_storyteller_generate_character,
    launch_character_generate_from_snapshot,
)

from zyg_dashboard.bp_storyteller.char_admin import (
    _RETRAIN_MODEL_FAMILIES,
    _retrain_char_dir,
    _retrain_count_pairs,
    _retrain_normalize_family,
    api_internal_storyteller_character_bible,
    api_internal_storyteller_character_status,
    api_internal_storyteller_voice_sample,
    api_internal_storyteller_voices,
    api_storyteller_char_retrain,
    api_storyteller_char_retrain_status,
)

from zyg_dashboard.bp_storyteller.previews import (
    api_internal_storyteller_char_preview_status,
    api_internal_storyteller_gen_char_previews,
    api_internal_storyteller_regen_preview,
    api_internal_storyteller_regen_preview_status,
)


# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and NOT used in this module: it is read off this
# module by its importers. Declaring them is what makes the re-export deliberate rather
# than an unused import; nothing does ``import *`` from here, so __all__ changes no
# behaviour.
__all__ = [
    'json',
    'os',
    're',
    'threading',
    'uuid',
    'Any',
    'Dict',
    'List',
    'Optional',
    'Tuple',
    'jsonify',
    'request',
    'session',
    'gui_state',
    'ZYG_LORA_DATASETS',
    'ZYG_LORA_OUTPUTS',
    '_char_library_trained_at',
    '_char_lora_output_ready',
    '_char_lora_train_families',
    '_char_mark_done',
    '_char_mark_error',
    '_char_params_from_bible',
    '_char_preview_png_names',
    '_char_reconcile_job_state',
    '_char_render_style',
    '_char_save_state',
    '_char_stage_end',
    '_char_stage_start',
    '_char_train_lora_for_family',
    '_contact_sheet_emit',
    '_contact_sheet_resume_run',
    '_contact_sheet_state_path',
    '_contact_sheet_worker_alive',
    '_have_usable_char_preview',
    '_normalize_char_model_family',
    '_render_char_preview_images',
    '_resolve_char_model_family',
    '_record_token_usage',
    '_ZPUB_PENDING_LOCK',
    '_zpub_pending_load',
    '_zpub_pending_save',
    '_apply_gpu_power_limit',
    '_caveman_kw',
    '_contact_sheet_launch_run',
    '_contact_sheet_mark_manifest_approved',
    '_contact_sheet_parse_start_payload',
    'limiter',
    '_char_gen_jobs',
    '_contact_sheet_jobs',
    '_runtime_path',
    '_ams_iso',
    '_zero_audit_log',
    '_CHARS_DATASET_ROOT',
    '_CHAR_ID_RE',
    '_CHAR_ID_WIDE_RE',
    '_PREVIEW_REGEN_JOBS',
    '_PREVIEW_REGEN_LOCK',
    '_PREVIEW_SLOT_STEMS',
    '_SWEEP_LOCK',
    '_char_lora_usable',
    '_env_on',
    '_is_medusa_cid',
    '_preview_provenance_map',
    '_production_paused',
    '_restore_parked_char_photos',
    '_save_uploaded_char_photos',
    'api_internal_creature_list',
    'api_internal_storyteller_analyze_character_photo',
    'api_internal_storyteller_list_chars',
    'api_internal_contact_sheet_approve',
    'api_internal_contact_sheet_image',
    'api_internal_contact_sheet_pause',
    'api_internal_contact_sheet_resume',
    'api_internal_contact_sheet_start',
    'api_internal_contact_sheet_status',
    'api_internal_list_contact_sheets',
    'api_internal_pipeline_pause',
    'api_internal_pipeline_pause_state',
    'api_internal_pipeline_resume',
    '_make_bg_generate',
    'api_internal_storyteller_generate_character',
    'launch_character_generate_from_snapshot',
    '_RETRAIN_MODEL_FAMILIES',
    '_retrain_char_dir',
    '_retrain_count_pairs',
    '_retrain_normalize_family',
    'api_internal_storyteller_character_bible',
    'api_internal_storyteller_character_status',
    'api_internal_storyteller_voice_sample',
    'api_internal_storyteller_voices',
    'api_storyteller_char_retrain',
    'api_storyteller_char_retrain_status',
    'api_internal_storyteller_char_preview_status',
    'api_internal_storyteller_gen_char_previews',
    'api_internal_storyteller_regen_preview',
    'api_internal_storyteller_regen_preview_status',
]
