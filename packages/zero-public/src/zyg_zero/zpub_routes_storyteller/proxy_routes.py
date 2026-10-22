# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# The original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

"""Storyteller proxy routes: photo analysis, character generation, contact sheets, voices.

Moved verbatim out of zpub_routes_storyteller.py (lines 119-579).
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

from zyg_zero.zpub_routes_storyteller.base import _ZPUB_VALIDATE_TOKEN, _zpub_story_gate, bp
from zyg_zero.zpub_routes_storyteller.dataset_paths import _DATASET_ROOT

# ── re-export surface ────────────────────────────────────────────────────────
# The names above that this section's own bodies do not read: they are the
# pre-split module's attribute surface, which callers and tests reach through
# the section module (``monkeypatch.setattr(mod, 'os', …)``,
# ``mod._requests``). Declaring them is what makes the re-export deliberate
# rather than an unused import; nothing does ``import *`` from here, so __all__
# changes no behaviour.
__all__ = [
    'json',
    're',
    'threading',
    'time',
    'uuid',
    'datetime',
    'Blueprint',
    'is_medusa_char',
    'AVG_PIPELINE_SECONDS',
    '_ams_iso',
    'public_url',
    '_require_api_session',
    '_parse_model_family',
    '_parse_pipeline_options',
    '_token_use',
    '_LOG_DIR',
    '_enqueue',
    '_get_running',
    '_link_session_job',
    '_link_token_job',
    '_pending_store',
    '_queue_length',
    '_save_job',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_routes_storyteller')

# ══════════════════════════════════════════════════════════════════════════════
# ── Storyteller proxy routes ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _zpub_reject_invalid_token(token: str, route: str):
    """2026-07-31: validate an invite token the way api_storyteller_generate does.

    ``generate-character``, ``contact-sheet/start`` and
    ``analyze-character-photo`` used to gate on token PRESENCE only, so the
    literal string ``"x"`` was enough to launch LoRA training and ~4.5-hour
    contact-sheet runs through the internal service token. Returns None when
    the token is valid, else the (response, status) tuple to return.
    """
    if not _ZPUB_VALIDATE_TOKEN:
        return None
    info = _token_check(token) or {}
    if info.get('valid'):
        return None
    reason = str(info.get('reason') or 'invalid')
    _zpub_log(
        'invite_token_rejected', ip=_client_ip(), route=route, reason=reason[:40], token_preview=(token or '')[:8] + '…'
    )
    msgs = {
        'expired': 'This invite link has expired.',
        'revoked': 'This invite link has been revoked.',
        'not_found': 'Invite link not found.',
        'token_not_found': 'Invite link not found.',
        'main_app_unreachable': 'Server is temporarily unavailable.',
    }
    return jsonify({'error': msgs.get(reason, 'Access denied. A valid invite link is required.')}), 403


@bp.route('/api/storyteller/analyze-character-photo', methods=['POST'])
@limiter.limit('30 per hour')
def api_storyteller_analyze_character_photo():
    """Proxy: vision analysis for Character Generation photo upload."""
    _session_id()  # called for its side effect: mints this visitor's session ID if it has none
    is_admin = session.get('is_zpub_admin', False)
    is_multipart = request.content_type and 'multipart/form-data' in request.content_type
    if not is_multipart:
        return jsonify({'error': 'multipart/form-data required'}), 400
    if not is_admin:
        token = _session_invite() or (request.form.get('invite_token') or '').strip() or ''
        if not token:
            return jsonify({'error': 'Access denied. A valid invite link is required.'}), 403
        # 2026-07-31: presence was the ONLY check — validate for real.
        blocked = _zpub_reject_invalid_token(token, 'analyze-character-photo')
        if blocked:
            return blocked
    try:
        photo = request.files.get('photo')
        if not photo:
            return jsonify({'error': 'photo file required'}), 400
        files_list = [('photo', (photo.filename, photo.read(), photo.content_type))]
        resp = _requests.post(
            f'{MAIN_APP_URL}/api/internal/storyteller/analyze-character-photo',
            files=files_list,
            headers=_int_headers(),
            timeout=180,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Main app unreachable: {e}', 'fields': {}}), 503


@bp.route('/api/storyteller/generate-character', methods=['POST'])
@limiter.limit('5 per hour')
def api_storyteller_generate_character():
    """
    Proxy: trigger Blender character generation + LoRA training on main app.
    Supports both JSON and multipart/form-data (for photo uploads).
    Body: {hair_color, eye_color, skin_tone?, gender, height?, style, char_id?}
    """
    _session_id()  # called for its side effect: mints this visitor's session ID if it has none
    is_admin = session.get('is_zpub_admin', False)

    # Determine if this is a multipart upload
    is_multipart = request.content_type and 'multipart/form-data' in request.content_type

    if not is_admin:
        if is_multipart:
            import json as _jm

            token = _jm.loads(request.form.get('params', '{}') or '{}').get('invite_token', '') or _session_invite()
        else:
            token = (request.get_json(silent=True) or {}).get('invite_token', '') or _session_invite()
        if not token:
            return jsonify({'error': 'Access denied. A valid invite link is required.'}), 403
        # 2026-07-31: any non-empty string used to pass — `-d '{"invite_token":"x"}'`
        # started Blender character generation + a full LoRA training run.
        blocked = _zpub_reject_invalid_token(str(token).strip(), 'generate-character')
        if blocked:
            return blocked

    try:
        if is_multipart:
            # Forward multipart to internal endpoint
            import json as _jm

            files_list = [('photos', (f.filename, f.read(), f.content_type)) for f in request.files.getlist('photos')]
            form_data = {'params': request.form.get('params', '{}')}
            try:
                _parsed = _jm.loads(form_data['params'] or '{}')
                _mf = (_parsed.get('model_family') or '').strip().lower()
                if _mf in ('flux', 'sdxl'):
                    form_data['model_family'] = _mf
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            resp = _requests.post(
                f'{MAIN_APP_URL}/api/internal/storyteller/generate-character',
                data=form_data,
                files=files_list or None,
                headers=_int_headers(),
                timeout=60,
            )
        else:
            data = request.get_json(silent=True) or {}
            resp = _requests.post(
                f'{MAIN_APP_URL}/api/internal/storyteller/generate-character',
                json=data,
                headers=_int_headers(),
                timeout=20,
            )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503


@bp.route('/api/storyteller/contact-sheet/start', methods=['POST'])
@limiter.limit('10 per hour')
def api_storyteller_contact_sheet_start():
    """Proxy: multi-angle contact sheet pipeline (sheet → approve → tiles → LoRA)."""
    data = request.get_json(silent=True) or {}
    if not session.get('is_zpub_admin', False):
        token = data.get('invite_token', '') or _session_invite()
        if not token:
            return jsonify({'error': 'Access denied. A valid invite link is required.'}), 403
        # 2026-07-31: presence-only gate let any string kick a ~4.5-hour
        # exclusive-GPU 48-angle contact-sheet build. Validate the invite.
        blocked = _zpub_reject_invalid_token(str(token).strip(), 'contact-sheet/start')
        if blocked:
            return blocked
    try:
        resp = _requests.post(
            f'{MAIN_APP_URL}/api/internal/storyteller/contact-sheet/start',
            json=data,
            headers=_int_headers(),
            timeout=30,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503


@bp.route('/api/storyteller/contact-sheet/status/<char_id>')
@limiter.exempt
def api_storyteller_contact_sheet_status(char_id: str):
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/contact-sheet/status/{char_id}',
            headers=_int_headers(),
            timeout=15,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503


@bp.route('/api/storyteller/contact-sheet/approve/<char_id>', methods=['POST'])
@limiter.limit('30 per hour')
def api_storyteller_contact_sheet_approve(char_id: str):
    # Sheet approval is Agent Zero-only by operator request — the public site
    # shows the preview; the decision lives on the review card in Zero chat.
    return jsonify(
        {
            'ok': False,
            'error': 'Sheet approval happens in Agent Zero — open the review card in Zero chat.',
        }
    ), 410


# ── Pause / resume controls (admin only) ─────────────────────────────────────
def _pipeline_ctrl_proxy(method: str, path: str, timeout: int = 20):
    if not session.get('is_zpub_admin', False):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403
    try:
        fn = _requests.post if method == 'POST' else _requests.get
        kw = {'headers': _int_headers(), 'timeout': timeout}
        if method == 'POST':
            kw['json'] = request.get_json(silent=True) or {}
        resp = fn(f'{MAIN_APP_URL}{path}', **kw)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Main app unreachable: {e}'}), 503


@bp.route('/api/storyteller/pipeline/pause-state')
@limiter.exempt
def api_storyteller_pipeline_pause_state():
    return _pipeline_ctrl_proxy('GET', '/api/internal/storyteller/pipeline/pause-state')


@bp.route('/api/storyteller/pipeline/pause', methods=['POST'])
@limiter.limit('60 per hour')
def api_storyteller_pipeline_pause():
    return _pipeline_ctrl_proxy('POST', '/api/internal/storyteller/pipeline/pause')


@bp.route('/api/storyteller/pipeline/resume', methods=['POST'])
@limiter.limit('60 per hour')
def api_storyteller_pipeline_resume():
    return _pipeline_ctrl_proxy('POST', '/api/internal/storyteller/pipeline/resume')


@bp.route('/api/storyteller/contact-sheet/pause/<char_id>', methods=['POST'])
@limiter.limit('60 per hour')
def api_storyteller_contact_sheet_pause(char_id: str):
    return _pipeline_ctrl_proxy('POST', f'/api/internal/storyteller/contact-sheet/pause/{char_id}')


@bp.route('/api/storyteller/contact-sheet/resume/<char_id>', methods=['POST'])
@limiter.limit('60 per hour')
def api_storyteller_contact_sheet_resume(char_id: str):
    return _pipeline_ctrl_proxy('POST', f'/api/internal/storyteller/contact-sheet/resume/{char_id}')


@bp.route('/api/storyteller/contact-sheet/training-image/<char_id>')
@limiter.exempt
def api_storyteller_contact_sheet_training_image(char_id: str):
    """Training-set-only composite (2026-07-20) — served DIRECTLY from disk
    (same box) so it works even when the main app hasn't restarted yet."""
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    import re as _re

    if not _re.match(r'^[a-f0-9]{12}$', char_id):
        return '', 404
    _p = os.path.join(
        str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'),
        char_id,
        'contact_sheet',
        'contact_sheet_training.png',
    )
    if not os.path.isfile(_p):
        return '', 404
    from flask import send_file as _sf

    _r = _sf(_p, mimetype='image/png')
    _r.headers['Cache-Control'] = 'no-store, must-revalidate'
    _r.headers['Pragma'] = 'no-cache'
    return _r


@bp.route('/api/storyteller/contact-sheet/image/<char_id>')
@limiter.limit('120 per minute')
def api_storyteller_contact_sheet_image(char_id: str):
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/contact-sheet/image/{char_id}',
            headers=_int_headers(),
            params=request.args,
            timeout=30,
            stream=True,
        )
        if not resp.ok:
            return '', resp.status_code
        from flask import Response as _FlaskResponse

        _hdrs = {'Content-Type': resp.headers.get('content-type', 'image/png')}
        # no-store (2026-07-19): the sheet is RE-STITCHED after QC repairs —
        # a cached copy showed the pre-repair sheet on the review card, so the
        # operator could not see what they were approving.
        _hdrs['Cache-Control'] = 'no-store, must-revalidate'
        _hdrs['Pragma'] = 'no-cache'
        _cd = resp.headers.get('Content-Disposition')
        if _cd:
            _hdrs['Content-Disposition'] = _cd
        # 2026-07-31: the internal route now reports WHICH sheet it served
        # (training / master_fallback / master_part / master_part_fallback).
        # Forward it so the review UI can say when it is showing the full
        # master — QC-excluded tiles included — instead of the training set.
        _sv = resp.headers.get('X-Sheet-Variant')
        if _sv:
            _hdrs['X-Sheet-Variant'] = _sv
        return _FlaskResponse(
            resp.iter_content(chunk_size=65536),
            status=resp.status_code,
            headers=_hdrs,
        )
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    import re as _re

    if not _re.match(r'^[a-f0-9]{12}$', char_id):
        return '', 404
    # 2026-07-31: 48-angle characters write multi-part sheets and have no
    # monolithic contact_sheet_master.png, so this disk fallback 404'd for
    # exactly the characters the library now advertises a sheet URL for.
    img_path = ''
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp_fb

        img_path = getattr(_csp_fb, 'any_master_sheet_path', lambda _c: '')(char_id) or ''
    except Exception:
        img_path = ''
    if not img_path:
        img_path = os.path.join(_DATASET_ROOT, char_id, 'contact_sheet', 'contact_sheet_master.png')
    if not os.path.isfile(img_path):
        return '', 404
    from flask import send_file as _sf

    want_download = (request.args.get('download') or '').strip().lower() in ('1', 'true', 'yes')
    if want_download:
        return _sf(img_path, mimetype='image/png', as_attachment=True, download_name=f'contact_sheet_{char_id[:8]}.png')
    return _sf(img_path, mimetype='image/png')


@bp.route('/api/storyteller/list-contact-sheets')
@limiter.limit('30 per minute')
def api_storyteller_list_contact_sheets():
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    _mf = (request.args.get('model_family') or '').strip().lower()
    if _mf not in ('flux', 'sdxl'):
        _mf = ''
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/list-contact-sheets',
            headers=_int_headers(),
            params={'model_family': _mf} if _mf else {},
            timeout=15,
        )
        if resp.ok:
            return jsonify(resp.json()), resp.status_code
    except Exception as _e:
        _zpub_log('list_contact_sheets_proxy_fail', error=str(_e)[:120])
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp

        sheets = _csp.list_contact_sheet_library(model_family=_mf)
        # Medusa chars must never surface in the PUBLIC library — strip them here.
        sheets = filter_out_medusa(sheets)
        return jsonify(
            {
                'sheets': sheets,
                'count': len(sheets),
                'pending_count': sum(1 for s in sheets if s.get('status') == 'running'),
                'trained_count': sum(1 for s in sheets if s.get('lora_ready')),
                'source': 'local',
            }
        )
    except Exception as exc:
        return jsonify({'sheets': [], 'count': 0, 'error': str(exc)[:200]}), 500


def _storyteller_voice_catalog_response(kind: str):
    """Voice catalog with local Azure V1/V2 sample URLs (only ready voices)."""
    from zyg_workflows.storyteller_voice_preview_service import (
        VOICE_SAMPLE_V1,
        VOICE_SAMPLE_V2,
        default_voice_id,
        grouped_voices_for_api,
    )

    k = (kind or 'character').strip().lower()
    if k not in ('character', 'narrator'):
        k = 'character'
    return jsonify(
        {
            'kind': k,
            'groups': grouped_voices_for_api(kind=k),
            'sample_phrases': {'v1': VOICE_SAMPLE_V1, 'v2': VOICE_SAMPLE_V2},
            'default_voice': default_voice_id(),
        }
    )


@bp.route('/api/storyteller/voice-samples-health')
@limiter.limit('60 per minute')
def api_storyteller_voice_samples_health():
    """Diagnostics: sample files on disk (for debugging silent playback)."""
    import glob as _glob
    from zyg_workflows.storyteller_voice_preview_service import SAMPLES_ROOT, migrate_legacy_wav_samples

    migrate_legacy_wav_samples()
    mp3s = _glob.glob(os.path.join(SAMPLES_ROOT, '**', '*.mp3'), recursive=True)
    return jsonify(
        {
            'ok': len(mp3s) > 0,
            'sample_count': len(mp3s),
            'root': SAMPLES_ROOT,
            'server_has_route': True,
        }
    )


@bp.route('/api/storyteller/voices')
@limiter.limit('30 per minute')
def api_storyteller_voices():
    """Storyteller voice catalog (?kind=character|narrator). Served locally."""
    try:
        return _storyteller_voice_catalog_response(request.args.get('kind'))
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@bp.route('/api/storyteller/voice-sample/<voice_id>/<variant>')
@limiter.limit('240 per minute')
def api_storyteller_voice_sample(voice_id: str, variant: str):
    """Serve pre-generated local Azure MP3 (v1 or v2)."""
    from flask import send_file as _send_file
    from zyg_workflows.storyteller_voice_preview_service import (
        resolve_sample_path,
        sample_mimetype,
    )

    variant = (variant or '').strip().lower()
    if variant not in ('v1', 'v2'):
        return jsonify({'error': 'variant must be v1 or v2'}), 400
    path = resolve_sample_path(voice_id, variant)
    if not path:
        return jsonify({'error': 'Sample not generated yet'}), 404
    try:
        resp = _send_file(
            path,
            mimetype=sample_mimetype(path),
            as_attachment=False,
            conditional=True,
        )
        resp.headers['Cache-Control'] = 'public, max-age=604800'
        resp.headers['Accept-Ranges'] = 'bytes'
        return resp
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@bp.route('/api/storyteller/character-status/<char_id>')
@limiter.limit('60 per minute')
def api_storyteller_character_status(char_id: str):
    """Proxy: poll character generation + LoRA training status."""
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session
    if blocked:
        return blocked
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/character-status/{char_id}',
            headers=_int_headers(),
            timeout=10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}'}), 503
