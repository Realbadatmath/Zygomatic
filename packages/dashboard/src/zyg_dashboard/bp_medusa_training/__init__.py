# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Medusa Training blueprint — upload-your-own-photos LoRA training for
"dedicated" / specialized characters, driven from the Medusa (:5300) GUI's
Training tab.

ISOLATION CONTRACT (read this before touching this file):
    Every character created here lives ONLY under _TRAIN_DATASET_ROOT /
    _TRAIN_OUTPUT_ROOT below — dedicated top-level trees that are siblings of,
    and byte-for-byte disjoint from, `lora-datasets/storyteller_chars` and
    `lora-outputs/storyteller_chars` (the roots every other workflow — the
    :5000 storyteller/crime/documentary/etc pipelines — hardcodes and scans
    directly via os.listdir/glob). Nothing in this module ever imports
    contact_sheet_pipeline, char_state_service, character_bible_service,
    character_lora_family, or any other shared character/dataset module, and
    it must stay that way: those are exactly the modules that feed the
    general workflow character pickers. The only shared code touched is the
    generic, path-parameterized `lora_trainer_service.LoraTrainerService`,
    called with an explicit dataset_dir/output_root that always points inside
    the isolated roots below.

    char_id format is `mdt_<12 hex>` (see _new_char_id) — deliberately NOT the
    bare `<12 hex>` shape used by regular/Medusa-swimwear characters, so even
    the process-wide `_training_jobs` dict in lora_trainer_service.py (keyed
    by char_id alone) can never collide with a non-dedicated character.

    Do NOT add a generic sweep over `lora-datasets/*` or `lora-outputs/*` in
    this codebase without first confirming it explicitly excludes
    `medusa_training/` — that is the one thing that would break isolation.

Endpoints (all under /api/medusa/training/..., so they inherit the existing
localhost-only bypass in crewai_web_gui.py's before_request — the same rule
already applied to /api/medusa/*):
    POST   /api/medusa/training/characters                      create a dedicated character
    GET    /api/medusa/training/characters                      list them (+ live training status)
    GET    /api/medusa/training/characters/<char_id>             one character's detail
    DELETE /api/medusa/training/characters/<char_id>             delete it (dataset + output)
    POST   /api/medusa/training/characters/<char_id>/images       upload reference photos (multipart)
    GET    /api/medusa/training/characters/<char_id>/images/<id>  serve one image (gallery)
    DELETE /api/medusa/training/characters/<char_id>/images/<id>  remove one image
    POST   /api/medusa/training/characters/<char_id>/train         start LoRA training
    GET    /api/medusa/training/characters/<char_id>/status        poll training status
    POST   /api/medusa/training/scan-folder                        preview a disk folder
    POST   /api/medusa/training/import-folders                     one folder -> one character
    GET    /api/medusa/training/import/<batch_id>                  import progress
    POST   /api/medusa/training/characters/<char_id>/sheet          build the contact sheet
    GET    /api/medusa/training/characters/<char_id>/sheet          sheet.json + live status
    GET    /api/medusa/training/characters/<char_id>/sheet/page/<p> serve a montage page
    GET    /api/medusa/training/sheets                             all sheets (Medusa-only)
    POST   /api/medusa/training/sheets/build-all                   build every missing sheet
    GET    /api/medusa/training/loras                              trained LoRAs (Medusa-only)
    GET    /api/medusa/training/loras/<id>/<fam>/sample/<name>      one validation render

CONTACT SHEETS (2026-08-07). A "contact sheet" here is NOT the 48-angle GPU
render that contact_sheet_pipeline.py produces (~4h26m/character). It is the
operator's OWN photographs classified into that same canonical angle taxonomy,
captioned from a fixed vocabulary, QC'd and assembled — CPU only, seconds per
character. See medusa_sheet_service.py. Sheets live at
<char_dir>/contact_sheet/ inside the isolated dataset root and are reachable
ONLY through the endpoints above, which are localhost-gated and filter to
mdt_* ids; nothing under lora-datasets/storyteller_chars is ever read.

Contract (same as the other bp_*.py modules): imported at the BOTTOM of
crewai_web_gui.py, after main's globals exist.
"""

# Re-export surface: every name the pre-split module defined.

from __future__ import annotations

import io
import json
import os
import re
import shutil
import threading
import uuid
from typing import Any

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename
from zyg_workflows.paths import ZYG_HOME, ZYG_LORA_DATASETS, ZYG_LORA_OUTPUTS
import logging as _zyg_logging

from zyg_dashboard.bp_medusa_training.storage import (
    _zyg_log,
    bp,
    _TRAIN_DATASET_ROOT,
    _TRAIN_OUTPUT_ROOT,
    _CHAR_ID_RE,
    _IMAGE_NAME_RE,
    _SHEET_PAGE_RE,
    _TRIGGER_STRIP_RE,
    _ALLOWED_EXTS,
    _MAX_FILE_BYTES,
    _MAX_REQUEST_BYTES,
    _MAX_FILES_PER_UPLOAD,
    _MAX_IMAGES_PER_CHAR,
    _TRAIN_MAX_STEPS,
    _MAX_EDGE_PX,
    MIN_IMAGES_TO_TRAIN,
    MEDUSA_IMPORT_ROOT,
    _IMPORT_ROOTS,
    _IMPORT_SKIP_DIRS,
    _MAX_SCAN_ENTRIES,
    _LIST_THUMBS,
    _IO_LOCK,
    _now_iso,
    _fmt_ts,
    _safe_char_dir,
    _safe_output_dir,
    _new_char_id,
    _auto_trigger,
    _sanitize_trigger,
    _normalize_family,
    _normalize_mode,
    _meta_path,
    _load_meta,
    _save_meta,
    _write_marker,
    _list_images,
    _new_image_id,
    _ingest_image_bytes,
    _ingest_one_image,
)
from zyg_dashboard.bp_medusa_training.folder_import import (
    _ingest_path,
    _safe_import_path,
    _in_import_roots,
    _count_images_in,
    _list_images_in,
    _scan_parent,
    _import_jobs,
    _import_lock,
    _body_jobs,
    _body_lock,
    _body_set,
    _body_status,
    _body_running,
    _import_set,
    _run_import,
    api_training_import_root,
    api_training_scan_folder,
    api_training_import_folders,
    api_training_import_status,
)
from zyg_dashboard.bp_medusa_training.contact_sheet import (
    api_training_build_sheet,
    api_training_get_sheet,
    api_training_sheet_page,
    api_training_body_prepare,
    api_training_body_status,
    api_training_list_sheets,
    api_training_build_all_sheets,
)
from zyg_dashboard.bp_medusa_training.endpoints import (
    _character_view,
    api_training_create_character,
    api_training_list_characters,
    api_training_get_character,
    api_training_delete_character,
    api_training_upload_images,
    api_training_get_image,
    api_training_delete_image,
    api_training_start,
    api_training_status,
    _LORA_FAMILIES,
    _SAMPLE_NAME_RE,
    _SAMPLE_STEP_RE,
    _LORA_SAMPLES,
    _lora_samples,
    api_training_list_loras,
    api_training_lora_sample,
)


# ── re-export surface ──
# Every name below is imported above and NOT used in this module; it is here so
# importers keep resolving it through this module. Nothing does ``import *`` from
# here, so __all__ changes no behaviour -- it is how ruff is told these are public.
__all__ = [
    'io',
    'json',
    'os',
    're',
    'shutil',
    'threading',
    'uuid',
    'Any',
    'Blueprint',
    'jsonify',
    'request',
    'send_file',
    'secure_filename',
    'ZYG_HOME',
    'ZYG_LORA_DATASETS',
    'ZYG_LORA_OUTPUTS',
    '_zyg_logging',
    '_zyg_log',
    'bp',
    '_TRAIN_DATASET_ROOT',
    '_TRAIN_OUTPUT_ROOT',
    '_CHAR_ID_RE',
    '_IMAGE_NAME_RE',
    '_SHEET_PAGE_RE',
    '_TRIGGER_STRIP_RE',
    '_ALLOWED_EXTS',
    '_MAX_FILE_BYTES',
    '_MAX_REQUEST_BYTES',
    '_MAX_FILES_PER_UPLOAD',
    '_MAX_IMAGES_PER_CHAR',
    '_TRAIN_MAX_STEPS',
    '_MAX_EDGE_PX',
    'MIN_IMAGES_TO_TRAIN',
    'MEDUSA_IMPORT_ROOT',
    '_IMPORT_ROOTS',
    '_IMPORT_SKIP_DIRS',
    '_MAX_SCAN_ENTRIES',
    '_LIST_THUMBS',
    '_IO_LOCK',
    '_now_iso',
    '_fmt_ts',
    '_safe_char_dir',
    '_safe_output_dir',
    '_new_char_id',
    '_auto_trigger',
    '_sanitize_trigger',
    '_normalize_family',
    '_normalize_mode',
    '_meta_path',
    '_load_meta',
    '_save_meta',
    '_write_marker',
    '_list_images',
    '_new_image_id',
    '_ingest_image_bytes',
    '_ingest_one_image',
    '_ingest_path',
    '_safe_import_path',
    '_in_import_roots',
    '_count_images_in',
    '_list_images_in',
    '_scan_parent',
    '_import_jobs',
    '_import_lock',
    '_body_jobs',
    '_body_lock',
    '_body_set',
    '_body_status',
    '_body_running',
    '_import_set',
    '_run_import',
    'api_training_import_root',
    'api_training_scan_folder',
    'api_training_import_folders',
    'api_training_import_status',
    'api_training_build_sheet',
    'api_training_get_sheet',
    'api_training_sheet_page',
    'api_training_body_prepare',
    'api_training_body_status',
    'api_training_list_sheets',
    'api_training_build_all_sheets',
    '_character_view',
    'api_training_create_character',
    'api_training_list_characters',
    'api_training_get_character',
    'api_training_delete_character',
    'api_training_upload_images',
    'api_training_get_image',
    'api_training_delete_image',
    'api_training_start',
    'api_training_status',
    '_LORA_FAMILIES',
    '_SAMPLE_NAME_RE',
    '_SAMPLE_STEP_RE',
    '_LORA_SAMPLES',
    '_lora_samples',
    'api_training_list_loras',
    'api_training_lora_sample',
]
