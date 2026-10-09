# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: the original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

"""Creature library routes plus the character-preview sweep.

Moved verbatim out of zpub_routes_storyteller.py (lines 1218-1448).
"""

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

from zyg_zero.zpub_routes_storyteller.base import _ZPUB_NAME_INDEX_TTL, _ZPUB_SWEEP_ADMIN_ONLY, _zpub_story_gate, bp
from zyg_zero.zpub_routes_storyteller.char_library import _slugify_for_filename

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_routes_storyteller')

_CREATURE_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'creatures')


def _creature_display_name_for_download(creature_id: str) -> str:
    """Resolve creature display name from manifest or runtime job state."""
    import os as _os
    import json as _json

    manifest_path = _os.path.join(_CREATURE_DATASET_ROOT, creature_id, 'manifest.json')
    try:
        if _os.path.isfile(manifest_path):
            with open(manifest_path, encoding='utf-8') as _mf:
                meta = _json.load(_mf)
            name = (meta.get('name') or '').strip()
            if name:
                return name[:120]
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    state_path = _os.path.join(_LOG_DIR, f'creature_gen_{creature_id}.json')
    try:
        if _os.path.isfile(state_path):
            with open(state_path, encoding='utf-8') as _sf:
                st = _json.load(_sf)
            name = ((st.get('params') or {}).get('prompt') or st.get('prompt') or '').strip()
            if name:
                return name[:120]
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return ''


# 2026-07-31: same per-request full-disk scan as _list_same_name_bibles —
# memoized identically (see that comment). Only the two fields
# _compute_creature_download_name reads are retained.
_creature_name_index_lock = threading.Lock()
_creature_name_index: dict = {'built_at': 0.0, 'mtime': None, 'index': {}}


def _build_creature_name_index() -> dict:
    import os as _os
    import json as _json

    index: dict[str, list] = {}
    try:
        entries = _os.listdir(_CREATURE_DATASET_ROOT)
    except Exception:
        return index
    for other_id in entries:
        manifest_path = _os.path.join(_CREATURE_DATASET_ROOT, other_id, 'manifest.json')
        if not _os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, encoding='utf-8') as _mf:
                other = _json.load(_mf)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        other_name = (other.get('name') or '').strip().lower()
        if not other_name:
            continue
        index.setdefault(other_name, []).append(
            (
                other_id,
                {
                    'name': other.get('name') or '',
                    'species': other.get('species'),
                    'profile_key': other.get('profile_key'),
                },
            )
        )
    return index


def _list_same_name_creature_manifests(creature_id: str, display_name: str) -> list[tuple[str, dict]]:
    """Return other creatures sharing the same display name (for filename disambiguation)."""
    import os as _os

    target = (display_name or '').strip().lower()
    if not target or not _os.path.isdir(_CREATURE_DATASET_ROOT):
        return []
    if _ZPUB_NAME_INDEX_TTL <= 0:
        return [r for r in _build_creature_name_index().get(target, []) if r[0] != creature_id]
    try:
        mtime = _os.path.getmtime(_CREATURE_DATASET_ROOT)
    except Exception:
        mtime = None
    now = time.time()
    try:
        with _creature_name_index_lock:
            stale = (
                not _creature_name_index['index']
                or _creature_name_index['mtime'] != mtime
                or (now - _creature_name_index['built_at']) > _ZPUB_NAME_INDEX_TTL
            )
            if stale:
                _creature_name_index['index'] = _build_creature_name_index()
                _creature_name_index['mtime'] = mtime
                _creature_name_index['built_at'] = now
            rows = list(_creature_name_index['index'].get(target, []))
    except Exception:
        return []
    return [r for r in rows if r[0] != creature_id]


def _compute_creature_download_name(creature_id: str, base_filename: str) -> str:
    """Build a friendly download filename: ``{creature_name}.png``."""
    import os as _os

    display_name = _creature_display_name_for_download(creature_id)
    if not display_name:
        return base_filename
    name_slug = _slugify_for_filename(display_name)
    if not name_slug:
        return base_filename
    _base, ext = _os.path.splitext(base_filename)
    if not ext:
        ext = '.png'
    parts = [name_slug]
    siblings = _list_same_name_creature_manifests(creature_id, display_name)
    if siblings:
        manifest_path = _os.path.join(_CREATURE_DATASET_ROOT, creature_id, 'manifest.json')
        meta: dict = {}
        try:
            if _os.path.isfile(manifest_path):
                import json as _json

                with open(manifest_path, encoding='utf-8') as _mf:
                    meta = _json.load(_mf)
        except Exception:
            meta = {}
        species = _slugify_for_filename(str(meta.get('species') or ''), max_len=24)
        profile = _slugify_for_filename(str(meta.get('profile_key') or ''), max_len=24)
        parts.append(species or profile or creature_id[:6])
    return '_'.join(parts) + ext


@bp.route('/api/creature/creature-image/<creature_id>/<filename>')
@limiter.limit('120 per minute')
def api_creature_image(creature_id: str, filename: str):
    """Serve a creature dataset/preview image directly from disk.

    Query params:
      ``download=1`` → set ``Content-Disposition: attachment`` with a
                       friendly filename based on the creature name.
    """
    import re as _re

    if not _re.match(r'^[a-f0-9]{12}$', creature_id):
        return '', 404
    if not _re.match(r'^[a-zA-Z0-9_]+\.(png|jpg|jpeg)$', filename):
        return '', 404
    import os as _os

    img_path = _os.path.join(_CREATURE_DATASET_ROOT, creature_id, filename)
    if not _os.path.isfile(img_path):
        return '', 404
    from flask import send_file as _sf

    want_download = (request.args.get('download') or '').strip() in ('1', 'true', 'yes')
    mime = 'image/jpeg' if filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
    if want_download:
        dl_name = _compute_creature_download_name(creature_id, filename)
        return _sf(img_path, mimetype=mime, as_attachment=True, download_name=dl_name)
    return _sf(img_path, mimetype=mime)


@bp.route('/api/creature/list-creatures')
@limiter.limit('30 per minute')
def api_creature_list_creatures():
    """Proxy: list previously trained creature LoRAs."""
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/creature/list',
            headers=_int_headers(),
            timeout=10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}', 'creatures': []}), 503


@bp.route('/api/storyteller/gen-char-previews', methods=['POST'])
@limiter.limit('10 per hour')
def api_storyteller_gen_char_previews():
    """Proxy: kick off bulk FLUX preview generation for all chars missing one."""
    # 2026-07-31: this route had NO auth of any kind and attached the internal
    # service token — a confused deputy. Any anonymous visitor could POST it and
    # queue a fleet-wide sweep that loads ~36 GB of FLUX onto the GPU and
    # OVERWRITES every character's canonical portrait with a generic base-FLUX
    # render. It is an operator maintenance action, not a user action, so it now
    # requires an ADMIN session — an invite session is not enough.
    if _ZPUB_SWEEP_ADMIN_ONLY and not session.get('is_zpub_admin', False):
        _zpub_log(
            'gen_char_previews_denied',
            ip=_client_ip(),
            had_invite=bool(_session_invite()),
            user_agent=request.headers.get('User-Agent', '')[:120],
        )
        return jsonify(
            {
                'ok': False,
                'error': 'The preview sweep is an operator action — admin session required.',
            }
        ), 403
    try:
        resp = _requests.post(
            f'{MAIN_APP_URL}/api/internal/storyteller/gen-char-previews',
            headers=_int_headers(),
            timeout=10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503


@bp.route('/api/storyteller/char-preview-status')
@limiter.limit('120 per minute')
def api_storyteller_char_preview_status():
    """Proxy: return bulk preview sweep progress."""
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/char-preview-status',
            headers=_int_headers(),
            timeout=5,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503
