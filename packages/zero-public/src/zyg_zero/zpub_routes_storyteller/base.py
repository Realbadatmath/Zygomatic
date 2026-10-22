# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# The original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

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
from zyg_zero import paths as _zero_paths
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

# ── re-export surface ────────────────────────────────────────────────────────
# The names above that this section's own bodies do not read: they are the
# pre-split module's attribute surface, which callers and tests reach through
# the section module (``monkeypatch.setattr(mod, 'os', …)``,
# ``mod._requests``). Declaring them is what makes the re-export deliberate
# rather than an unused import; nothing does ``import *`` from here, so __all__
# changes no behaviour.
__all__ = [
    'json',
    'threading',
    'time',
    'uuid',
    'datetime',
    '_requests',
    'jsonify',
    'request',
    'session',
    'paths',
    'filter_out_medusa',
    'is_medusa_char',
    'AVG_PIPELINE_SECONDS',
    'MAIN_APP_URL',
    '_ams_iso',
    'public_url',
    '_client_ip',
    '_session_id',
    '_session_invite',
    'limiter',
    '_int_headers',
    '_parse_model_family',
    '_parse_pipeline_options',
    '_token_check',
    '_token_use',
    '_LOG_DIR',
    '_enqueue',
    '_get_running',
    '_link_session_job',
    '_link_token_job',
    '_pending_store',
    '_queue_length',
    '_save_job',
    '_zpub_log',
]

# Flask would derive the blueprint's resource root from this submodule's own
# directory; it is pinned to the package directory the pre-split module sat in.
bp = Blueprint('zpub_story', __name__, root_path=str(_zero_paths.PKG_DIR))

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_routes_storyteller')


# ══════════════════════════════════════════════════════════════════════════════
# 2026-07-31: identity-authority + public-surface hardening.
# This blueprint is the INTERNET-FACING surface (published through a cloudflared
# tunnel) and there is no app-level before_request gate, so every
# route here is self-gating. Each behaviour change below carries a ZYG_ flag
# that DEFAULTS TO THE NEW behaviour; set it to '0' to fall back.
# ══════════════════════════════════════════════════════════════════════════════
def _zyg_flag(name: str, default: str = '1') -> bool:
    return (os.environ.get(name, default) or '').strip().lower() not in ('0', 'false', 'no', 'off')


# Read-surface session gate (list-chars, char-image, contact-sheet image/status…).
_ZPUB_REQUIRE_SESSION = _zyg_flag('ZYG_ZPUB_STORY_REQUIRE_SESSION')
# gen-char-previews is a fleet-wide mutating GPU job → admin session only.
_ZPUB_SWEEP_ADMIN_ONLY = _zyg_flag('ZYG_ZPUB_PREVIEW_SWEEP_ADMIN_ONLY')
# Validate invite tokens on the GPU-spending write routes (was presence-only).
_ZPUB_VALIDATE_TOKEN = _zyg_flag('ZYG_ZPUB_VALIDATE_INVITE_TOKEN')
# The character bible — not the request body — owns identity.
_ZPUB_BIBLE_IDENTITY = _zyg_flag('ZYG_ZPUB_BIBLE_IDENTITY_AUTHORITY')
# Submitted TTS voices must exist in the catalog and fit the bible identity.
_ZPUB_VOICE_VALIDATE = _zyg_flag('ZYG_ZPUB_VOICE_VALIDATE')
# Library rows carry the full identity descriptor set (no wizard defaults).
_ZPUB_LIB_IDENTITY = _zyg_flag('ZYG_ZPUB_LIB_IDENTITY_FIELDS')
# "LoRA ready" must respect a declined / QC-failed contact-sheet run.
_ZPUB_LORA_USABLE_GATE = _zyg_flag('ZYG_ZPUB_LORA_USABLE_GATE')
# Only 12-hex char_ids are listable (both image routes reject anything else).
_ZPUB_HEX_CHARID_ONLY = _zyg_flag('ZYG_ZPUB_HEX_CHARID_ONLY')
# Medusa (adults-only) characters stay out of the public character library.
_ZPUB_LIST_CHARS_MEDUSA_FILTER = _zyg_flag('ZYG_ZPUB_LIST_CHARS_MEDUSA_FILTER')
# TTL (seconds) for the display-name index behind ?download=1 (0 disables).
try:
    _ZPUB_NAME_INDEX_TTL = float(os.environ.get('ZYG_ZPUB_BIBLE_INDEX_TTL', '300'))
except (TypeError, ValueError):
    _ZPUB_NAME_INDEX_TTL = 300.0

_HEX_CHAR_ID_RE = re.compile(r'^[a-f0-9]{12}$')


class _ZpubJobRejected(Exception):
    """Raised by the shared job builder when a submitted field cannot be
    reconciled server-side (currently: an unknown TTS voice id). Carries the
    HTTP status + message the route should return."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _zpub_story_gate():
    """Per-route session gate for the storyteller read surface.

    Returns a 403 JSON response when the caller has neither an invite session
    nor an admin session, else None. Mirrors zpub_routes_public.py:189.
    """
    if not _ZPUB_REQUIRE_SESSION:
        return None
    return _require_api_session()


def _zpub_is_listable_char_id(cid: str) -> bool:
    """True when *cid* is a real 12-hex character id.

    Both image routes hard-reject anything else, so listing a slug directory
    (e.g. ``abel_van_haren``) produces a permanently broken library row that
    also re-arms the preview sweep on every page load.
    """
    if not _ZPUB_HEX_CHARID_ONLY:
        return bool(cid) and not cid.startswith('.')
    return bool(cid) and bool(_HEX_CHAR_ID_RE.match(cid))
