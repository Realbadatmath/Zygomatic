# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Isolated storage roots, path safety, meta.json and image ingest.

`_ingest_path` sits with the allowlist it calls, in folder_import.py.

Moved verbatim out of bp_medusa_training.py; this module carries the pre-split
file's top import block and its Blueprint.
"""

# ruff: noqa: F401  # the original top import block lives here; siblings re-import from it

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

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_medusa_training')


# root_path kept from the pre-split module: Flask derives it from this module's
# own directory, which is the package directory the single file's root_path was.
bp = Blueprint('medusa_training', __name__)

# ── Isolated storage roots (see module docstring — never point these at
#    storyteller_chars / animals / creatures / wan_chars) ────────────────────
_TRAIN_DATASET_ROOT = os.path.realpath(
    os.environ.get('ZYG_MEDUSA_TRAINING_DATASET_ROOT', str(ZYG_LORA_DATASETS / 'medusa_training'))
)
_TRAIN_OUTPUT_ROOT = os.path.realpath(
    os.environ.get('ZYG_MEDUSA_TRAINING_OUTPUT_ROOT', str(ZYG_LORA_OUTPUTS / 'medusa_training'))
)

_CHAR_ID_RE = re.compile(r'^mdt_[0-9a-f]{12}$')
_IMAGE_NAME_RE = re.compile(r'^img_[0-9a-f]{8}\.png$')
# Serves BOTH the angle montage (medusa_sheet_NN) and the body-mode mask
# check sheet (medusa_bodymask_NN). Both live in contact_sheet/ and both
# are strictly Medusa-private.
_SHEET_PAGE_RE = re.compile(r'^medusa_(?:sheet|bodymask)_[0-9]{2,4}\.png$')
_TRIGGER_STRIP_RE = re.compile(r'[^A-Za-z0-9_]')

_ALLOWED_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
_MAX_FILE_BYTES = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_FILE_MB', '40')) * 1024 * 1024

# Per-REQUEST caps only. They bound one HTTP call so a single upload cannot
# exhaust memory or disk in one shot — they are NOT a cap on how many photos a
# character may have. The browser chunks a large selection into many requests
# and the server-side folder import bypasses HTTP entirely, so both paths scale
# to arbitrarily large sets.
_MAX_REQUEST_BYTES = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_REQUEST_MB', '1024')) * 1024 * 1024
_MAX_FILES_PER_UPLOAD = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_FILES_PER_REQUEST', '200'))

# Hard ceiling per character — a runaway guard, not a design limit. 0 disables.
_MAX_IMAGES_PER_CHAR = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_IMAGES', '5000'))

# Step ceiling handed to lora_trainer_service.start_training. 0 = none, so the
# schedule is exactly images x ZYG_LORA_EPOCHS. Set a number here to re-impose
# a wall-clock bound without touching the shared default.
_TRAIN_MAX_STEPS = int(os.environ.get('ZYG_MEDUSA_TRAIN_MAX_STEPS', '0'))

_MAX_EDGE_PX = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_EDGE_PX', '2048'))
MIN_IMAGES_TO_TRAIN = 5

# ── Server-side folder import ────────────────────────────────────────────────
# Scanning a path the operator types is a filesystem read primitive, so it is
# confined to an allowlist of roots.
#
# 2026-08-08: narrowed from the whole home tree ('~:/media/<user>:/mnt') to
# ONE dedicated drop folder. The scan endpoint is reachable
# from the Medusa GUI, so the roots are its blast radius — a dedicated folder
# means a mistake or a stray caller can only ever see photos the operator
# deliberately put there, never the rest of their home directory.
#
# The folder is deliberately NOT under lora-datasets/, crews/output/ or
# crews/data/output/ — those are trees other workflows scan (see the isolation
# contract above). Override with ZYG_MEDUSA_TRAINING_IMPORT_ROOTS
# (colon-separated) to add e.g. an external drive.
MEDUSA_IMPORT_ROOT = os.path.realpath(os.environ.get('ZYG_MEDUSA_IMPORT_ROOT', str(ZYG_HOME / 'medusa_import')))

_IMPORT_ROOTS = tuple(
    os.path.realpath(p)
    for p in (os.environ.get('ZYG_MEDUSA_TRAINING_IMPORT_ROOTS') or MEDUSA_IMPORT_ROOT).split(':')
    if p.strip()
)

try:
    os.makedirs(MEDUSA_IMPORT_ROOT, exist_ok=True)
except OSError as _exc:
    _zyg_log.warning('medusa import root %s could not be created: %s', MEDUSA_IMPORT_ROOT, _exc)
# Directories never worth scanning, and dangerous to walk.
_IMPORT_SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.cache'}
_MAX_SCAN_ENTRIES = int(os.environ.get('ZYG_MEDUSA_TRAINING_MAX_SCAN', '200000'))

# Thumbnails returned per character by the LIST endpoint (the detail endpoint
# still returns all of them). Keeps an 80-character poll small.
_LIST_THUMBS = int(os.environ.get('ZYG_MEDUSA_TRAINING_LIST_THUMBS', '12'))

_IO_LOCK = threading.Lock()


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _fmt_ts(ts: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S')


# ── Path safety (mirrors medusa_server.py's _safe_config_path pattern) ───────
def _safe_char_dir(char_id: str, must_exist: bool = True) -> str | None:
    if not isinstance(char_id, str) or not _CHAR_ID_RE.match(char_id):
        return None
    root = os.path.realpath(_TRAIN_DATASET_ROOT)
    p = os.path.realpath(os.path.join(root, char_id))
    if os.path.dirname(p) != root:
        return None
    if must_exist and not os.path.isdir(p):
        return None
    return p


def _safe_output_dir(char_id: str) -> str | None:
    if not isinstance(char_id, str) or not _CHAR_ID_RE.match(char_id):
        return None
    root = os.path.realpath(_TRAIN_OUTPUT_ROOT)
    p = os.path.realpath(os.path.join(root, char_id))
    if os.path.dirname(p) != root:
        return None
    return p


def _new_char_id() -> str:
    return f'mdt_{uuid.uuid4().hex[:12]}'


def _auto_trigger(char_id: str) -> str:
    return f'ZYG_MDT_{char_id[4:10].upper()}'


def _sanitize_trigger(raw: Any) -> str:
    return _TRIGGER_STRIP_RE.sub('', str(raw or '')).strip('_').upper()[:32]


def _normalize_family(raw: Any) -> str:
    v = str(raw or 'flux').strip().lower()
    return v if v in ('flux', 'sdxl', 'qwen', 'klein') else 'flux'


def _normalize_mode(raw: Any) -> str:
    """identity | body.

    Fail-safe direction is IDENTITY: an unrecognised value must never silently
    mode a character as a body template, because body mode masks faces out of
    the training loss and the operator would only discover the mistake as a LoRA
    that cannot reproduce the person.
    """
    v = str(raw or 'identity').strip().lower()
    if v in ('body', 'body_template', 'bodytemplate'):
        return 'body'
    return 'identity'


# ── meta.json (atomic write, mirrors bp_medusa.py's _save_json) ─────────────
def _meta_path(char_id: str) -> str:
    return os.path.join(_TRAIN_DATASET_ROOT, char_id, 'meta.json')


def _load_meta(char_id: str) -> dict | None:
    if not _CHAR_ID_RE.match(char_id or ''):
        return None
    p = _meta_path(char_id)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_meta(char_id: str, meta: dict) -> None:
    d = os.path.join(_TRAIN_DATASET_ROOT, char_id)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'meta.json')
    tmp = f'{p}.tmp.{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)
    os.replace(tmp, p)


def _write_marker(char_id: str) -> None:
    """Defense-in-depth origin stamp — mirrors bp_medusa.py's .medusa_origin."""
    try:
        d = os.path.join(_TRAIN_DATASET_ROOT, char_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, '.medusa_training_origin'), 'w', encoding='utf-8') as fh:
            json.dump({'origin': 'medusa_training', 'char_id': char_id}, fh)
    except OSError as _exc:
        _zyg_log.warning('training origin marker for %s not written: %s', char_id, _exc)


# ── Images ────────────────────────────────────────────────────────────────
def _list_images(char_id: str) -> list[dict]:
    cdir = _safe_char_dir(char_id)
    if not cdir:
        return []
    train_dir = os.path.join(cdir, 'training')
    try:
        names = sorted(n for n in os.listdir(train_dir) if _IMAGE_NAME_RE.match(n))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            out.append({'id': n, 'bytes': os.path.getsize(os.path.join(train_dir, n))})
        except OSError as _exc:
            _zyg_log.debug('skipping training image with an unreadable size: %s', _exc)
            continue
    return out


def _new_image_id(train_dir: str) -> str:
    for _ in range(10):
        cand = f'img_{uuid.uuid4().hex[:8]}.png'
        if not os.path.exists(os.path.join(train_dir, cand)):
            return cand
    return f'img_{uuid.uuid4().hex[:12]}.png'


def _ingest_image_bytes(raw: bytes, ext: str, train_dir: str, meta: dict) -> dict:
    """Decode, normalise and store one image. Shared by upload and folder import."""
    if ext not in _ALLOWED_EXTS:
        return {'error': f'unsupported file type "{ext or "?"}" — use PNG/JPG/WEBP'}
    if not raw:
        return {'error': 'empty file'}
    if len(raw) > _MAX_FILE_BYTES:
        return {'error': f'file exceeds {_MAX_FILE_BYTES // (1024 * 1024)}MB limit'}

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return {'error': 'image processing unavailable on the server (Pillow not installed)'}

    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
    except Exception:
        return {'error': 'not a valid image (decode failed)'}

    if max(img.size) > _MAX_EDGE_PX:
        img.thumbnail((_MAX_EDGE_PX, _MAX_EDGE_PX), Image.LANCZOS)

    image_id = _new_image_id(train_dir)
    img_path = os.path.join(train_dir, image_id)
    img.save(img_path, 'PNG')

    # Placeholder caption. The sheet build rewrites every .txt from the measured
    # angle vocabulary — see medusa_sheet_service.caption_for.
    caption = meta.get('trigger_token', '')
    suffix = (meta.get('caption_suffix') or '').strip()
    if suffix:
        caption = f'{caption}, {suffix}'
    with open(img_path[:-4] + '.txt', 'w', encoding='utf-8') as fh:
        fh.write(caption)

    w, h = img.size
    return {'image_id': image_id, 'width': w, 'height': h, 'bytes': os.path.getsize(img_path)}


def _ingest_one_image(file_storage, train_dir: str, meta: dict) -> dict:
    filename = file_storage.filename or ''
    ext = os.path.splitext(secure_filename(filename))[1].lower()
    raw = file_storage.stream.read(_MAX_FILE_BYTES + 1)
    return _ingest_image_bytes(raw, ext, train_dir, meta)
