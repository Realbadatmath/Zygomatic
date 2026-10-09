# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401, E402
# F401: this __init__ exists to re-export; E402: the forward-reference setattr
# shim below needs `import sys` after the section imports.

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

# 2026-10-07: zpub_routes_storyteller.py (2,113 lines) became this package. Each
# section module holds a verbatim range of the old file; this __init__ imports them
# in the original section order so the module-level side effects (Blueprint
# creation, @bp.route registration) happen exactly when they used to, and re-exports
# every name the old module defined so the import path is unchanged.

import json
import logging as _zyg_logging
import os
import re
import threading
import time
import uuid
from datetime import datetime

import requests as _requests
from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from zyg_workflows import paths
from zyg_workflows.medusa_chars import filter_out_medusa, is_medusa_char
from zyg_zero.zpub_config import AVG_PIPELINE_SECONDS, MAIN_APP_URL, _ams_iso, public_url
from zyg_zero.zpub_gate import _client_ip, _require_api_session, _session_id, _session_invite, limiter
from zyg_zero.zpub_main_api import _int_headers, _parse_model_family, _parse_pipeline_options, _token_check, _token_use
from zyg_zero.zpub_store import (
    _LOG_DIR,
    _enqueue,
    _get_running,
    _link_session_job,
    _link_token_job,
    _pending_store,
    _queue_length,
    _save_job,
    _zpub_log,
)

from zyg_zero.zpub_routes_storyteller import base
from zyg_zero.zpub_routes_storyteller import proxy_routes
from zyg_zero.zpub_routes_storyteller import char_library
from zyg_zero.zpub_routes_storyteller import creatures
from zyg_zero.zpub_routes_storyteller import identity_voice
from zyg_zero.zpub_routes_storyteller import generate

from zyg_zero.zpub_routes_storyteller.base import (
    bp,
    _zyg_log,
    _zyg_flag,
    _ZPUB_REQUIRE_SESSION,
    _ZPUB_SWEEP_ADMIN_ONLY,
    _ZPUB_VALIDATE_TOKEN,
    _ZPUB_BIBLE_IDENTITY,
    _ZPUB_VOICE_VALIDATE,
    _ZPUB_LIB_IDENTITY,
    _ZPUB_LORA_USABLE_GATE,
    _ZPUB_HEX_CHARID_ONLY,
    _ZPUB_LIST_CHARS_MEDUSA_FILTER,
    _ZPUB_NAME_INDEX_TTL,
    _HEX_CHAR_ID_RE,
    _ZpubJobRejected,
    _zpub_story_gate,
    _zpub_is_listable_char_id,
)
from zyg_zero.zpub_routes_storyteller.proxy_routes import (
    _zpub_reject_invalid_token,
    api_storyteller_analyze_character_photo,
    api_storyteller_generate_character,
    api_storyteller_contact_sheet_start,
    api_storyteller_contact_sheet_status,
    api_storyteller_contact_sheet_approve,
    _pipeline_ctrl_proxy,
    api_storyteller_pipeline_pause_state,
    api_storyteller_pipeline_pause,
    api_storyteller_pipeline_resume,
    api_storyteller_contact_sheet_pause,
    api_storyteller_contact_sheet_resume,
    api_storyteller_contact_sheet_training_image,
    api_storyteller_contact_sheet_image,
    api_storyteller_list_contact_sheets,
    _storyteller_voice_catalog_response,
    api_storyteller_voice_samples_health,
    api_storyteller_voices,
    api_storyteller_voice_sample,
    api_storyteller_character_status,
)
from zyg_zero.zpub_routes_storyteller.char_library import (
    _CHAR_DATASET_ROOT,
    _slugify_for_filename,
    _NAME_INDEX_DISCRIMINATORS,
    _bible_name_index_lock,
    _bible_name_index,
    _build_bible_name_index,
    _bible_name_lookup,
    _list_same_name_bibles,
    _char_display_name_for_download,
    _compute_char_download_name,
    api_storyteller_char_image,
    _LORA_OUTPUT_ROOT,
    _DATASET_ROOT,
    _CHAR_RUNTIME_DIR,
    _zpub_char_lora_ready,
    _lora_unusable_logged,
    _zpub_char_lora_usable,
    _zpub_char_is_medusa,
    _zpub_identity_fields_from_bible,
    _zpub_char_preview_file,
    _zpub_char_trained_at,
    _zpub_char_entry_from_disk,
    _zpub_list_chars_local,
    _zpub_supplement_list_chars,
    api_storyteller_list_chars,
)
from zyg_zero.zpub_routes_storyteller.creatures import (
    _CREATURE_DATASET_ROOT,
    _creature_display_name_for_download,
    _creature_name_index_lock,
    _creature_name_index,
    _build_creature_name_index,
    _list_same_name_creature_manifests,
    _compute_creature_download_name,
    api_creature_image,
    api_creature_list_creatures,
    api_storyteller_gen_char_previews,
    api_storyteller_char_preview_status,
)
from zyg_zero.zpub_routes_storyteller.identity_voice import (
    _IDENTITY_AUTHORITY_FIELDS,
    _zpub_bible_identity_params,
    _zpub_char_render_mode,
    _zpub_apply_identity_authority,
    _MINOR_AGE,
    _zpub_as_int,
    _zpub_voice_index,
    _zpub_voice_fits,
    _zpub_pick_voice,
    _zpub_resolve_voices,
    _zpub_precheck_voice_ids,
)
from zyg_zero.zpub_routes_storyteller.generate import (
    _build_storyteller_job,
    _park_storyteller_for_approval,
    api_storyteller_generate,
    api_benchmark,
)
