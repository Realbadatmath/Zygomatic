# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: the original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

"""Storyteller job builder, the generate route and the benchmark route.

Moved verbatim out of zpub_routes_storyteller.py (lines 1871-2113).
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

from zyg_zero.zpub_routes_storyteller.base import _ZpubJobRejected, bp
from zyg_zero.zpub_routes_storyteller.identity_voice import (
    _zpub_apply_identity_authority,
    _zpub_precheck_voice_ids,
    _zpub_resolve_voices,
)


def _build_storyteller_job(data: dict, sid: str, token: str) -> tuple:
    """Build a storyteller job dict from a request body. Shared by the direct
    submit path and the manual-approval release so an approved job is byte-for-
    byte what a direct submission would have produced. Returns (job, job_id)."""
    story_prompt = (data.get('story_prompt') or data.get('prompt') or '').strip()
    char_id = (data.get('char_id') or '').strip()
    try:
        clip_duration_minutes = float(data.get('clip_duration_minutes', 10.0))
        clip_duration_minutes = max(0.17, min(20.0, clip_duration_minutes))
    except (ValueError, TypeError):
        clip_duration_minutes = 10.0
    _VALID_CAMERAS = {'automatic', 'front', 'side', 'back', '3quarter', 'closeup', 'overhead', 'low'}
    camera_mode = (data.get('camera_mode') or 'automatic').strip().lower()
    if camera_mode not in _VALID_CAMERAS:
        camera_mode = 'automatic'
    voice_style = (data.get('voice_style') or 'narration').strip()
    narrator_voice = (data.get('narrator_voice') or '').strip()
    character_voice = (data.get('character_voice') or '').strip()
    visual_style = (data.get('visual_style') or 'cinematic').strip()
    era_start = data.get('era_start')
    era_end = data.get('era_end')
    character_params = data.get('character_params') or {}
    if not isinstance(character_params, dict):
        character_params = {}
    # 2026-07-31: identity is rebuilt SERVER-SIDE from the character bible and
    # the on-disk manifest — the request body no longer describes who the
    # character is. Done here (not in the route) so the parked manual-approval
    # release path gets exactly the same job the direct path would produce.
    character_params, _identity = _zpub_apply_identity_authority(char_id, character_params)
    # …and the voices are validated against the catalog using that identity.
    narrator_voice, character_voice = _zpub_resolve_voices(
        narrator_voice,
        character_voice,
        _identity,
        char_id,
    )
    model_family = _parse_model_family(data.get('model_family'))
    pipeline_options = _parse_pipeline_options(data.get('pipeline_options'))
    job_id = uuid.uuid4().hex
    job = {
        'job_id': job_id,
        'session_id': sid,
        'invite_token': token,
        # 2026-07-31: remote_addr is 127.0.0.1 for all tunnel traffic — record
        # the edge-resolved client address so abuse is attributable.
        'ip': _client_ip(),
        'prompt': story_prompt,
        'pipeline_style': 'storyteller',
        'video_duration_minutes': clip_duration_minutes,
        'narration_enabled': True,
        'visual_style': visual_style,
        'model_family': model_family,
        'pipeline_options': pipeline_options,
        'scene_mode': 'independent',
        'ending_text': '',
        'uploaded_image_paths': [],
        'storyteller_params': {
            'char_id': char_id,
            'character_params': character_params,
            'voice_style': voice_style,
            'narrator_voice': narrator_voice,
            'character_voice': character_voice,
            'clip_duration_minutes': clip_duration_minutes,
            'era_start': era_start,
            'era_end': era_end,
            'camera_mode': camera_mode,
            'story_prompt': story_prompt,
        },
        'status': 'queued',
        'department': 'storyteller',
        'pipeline_id': None,
        'created_at': _ams_iso(),
        'started_at': None,
        'completed_at': None,
        'current_stage': 'Waiting in queue…',
        'output_dir': None,
        'output_files': [],
        'result': None,
        'error': None,
    }
    return job, job_id


def _park_storyteller_for_approval(data: dict, sid: str, token: str, entry: dict):
    """Manual-permission storyteller request → park the fully-built job as
    pending_approval (NOT enqueued) and register it in the operator approval
    queue. Returns the pending req_id. On approval, run_approved just flips the
    parked job to queued + enqueues it (no rebuild)."""
    job, job_id = _build_storyteller_job(data, sid, token)
    job['status'] = 'pending_approval'
    job['current_stage'] = 'Awaiting operator approval…'
    _save_job(job)
    if token and token != '__admin__':  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
        _link_token_job(token, job_id)  # shows as pending in the user's library
    _link_session_job(sid, job_id)
    req_id = 'preq_' + uuid.uuid4().hex[:12]
    _pending_store(
        {
            'id': req_id,
            'token': token,
            'label': (entry or {}).get('label', ''),
            'invite_url': f'{public_url()}/u/{token}' if token else '',
            'prompt': (job.get('prompt') or '')[:500],
            'pipeline': 'storyteller',
            'voice': (data.get('voice_style') or ''),
            'style': (data.get('visual_style') or ''),
            'model': (data.get('model_family') or ''),
            'ip': _client_ip(),  # 2026-07-31: edge IP, not 127.0.0.1
            'session_id': sid,
            'body_snapshot': {'storyteller_job_id': job_id},
            'requested_at': datetime.utcnow().isoformat() + 'Z',
            'status': 'pending',
            'decided_at': None,
            'approved_job_id': None,
        }
    )
    _zpub_log(
        'storyteller_manual_pending_queued',
        ip=_client_ip(),
        req_id=req_id,
        job_id=job_id,
        label=(entry or {}).get('label', ''),
        prompt_preview=(job.get('prompt') or '')[:80],
    )
    return req_id


@bp.route('/api/storyteller/generate', methods=['POST'])
@limiter.limit('10 per hour')
def api_storyteller_generate():
    """
    Submit a Storyteller pipeline job.
    Body: {
        story_prompt, char_id, voice_style?, clip_duration_minutes?,
        era_start?, era_end?, camera_mode?, visual_style?, invite_token?
    }
    """
    sid = _session_id()
    is_admin = session.get('is_zpub_admin', False)

    data = request.get_json(silent=True) or {}
    story_prompt = (data.get('story_prompt') or data.get('prompt') or '').strip()
    char_id = (data.get('char_id') or '').strip()

    if not story_prompt:
        return jsonify({'error': 'story_prompt is required'}), 400
    if len(story_prompt) > 2000:
        return jsonify({'error': 'Prompt too long (max 2000 characters)'}), 400

    # 2026-07-31: catch an unknown TTS voice id before _token_use() spends one
    # of the invite's requests on a job that cannot be built.
    _voice_blocked = _zpub_precheck_voice_ids(data)
    if _voice_blocked:
        return _voice_blocked

    try:
        if not is_admin:
            token = (data.get('invite_token') or '').strip() or _session_invite()
            if not token:
                return jsonify({'error': 'Access denied. A valid invite link is required.'}), 403

            token_info = _token_check(token)
            if token_info.get('valid') and token_info.get('entry', {}).get('permission') == 'manual':
                # 2026-07-25 FIX: manual-permission storyteller requests were dropped
                # with a message and NEVER queued for operator approval (unlike the
                # generic public route). Park the job + register it in the approval
                # queue so it appears in the operator's pending dashboard.
                req_id = _park_storyteller_for_approval(data, sid, token, token_info.get('entry', {}))
                return jsonify(
                    {
                        'pending': True,
                        'pending_id': req_id,
                        'message': 'Your story is awaiting operator approval. It will appear in '
                        'your library once approved — you can safely close this page.',
                    }
                ), 202

            use_result = _token_use(token)
            if not use_result.get('ok', False):
                reason = use_result.get('reason', 'unknown')
                if reason == 'manual_permission_required':
                    req_id = _park_storyteller_for_approval(data, sid, token, use_result.get('entry', {}))
                    return jsonify(
                        {
                            'pending': True,
                            'pending_id': req_id,
                            'message': 'Your story is awaiting operator approval. It will appear in '
                            'your library once approved — you can safely close this page.',
                        }
                    ), 202
                msgs = {
                    'exhausted': 'This invite link has reached its request limit.',
                    'expired': 'This invite link has expired.',
                    'revoked': 'This invite link has been revoked.',
                    'not_found': 'Invite link not found.',
                    'main_app_unreachable': 'Server is temporarily unavailable.',
                }
                return jsonify({'error': msgs.get(reason, 'Invite link is no longer valid.')}), 403
        else:
            token = '__admin__'  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret

        job, job_id = _build_storyteller_job(data, sid, token)
    except _ZpubJobRejected as _rej:
        # 2026-07-31: server-side reconciliation refused the submission (unknown
        # voice id). Shared with the parked-approval path above by design.
        return jsonify({'error': _rej.message}), _rej.status
    _save_job(job)
    _enqueue(job_id)
    _link_session_job(sid, job_id)
    if token and token != '__admin__':  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
        _link_token_job(token, job_id)

    qlen = _queue_length()
    ahead = qlen + (1 if _get_running() else 0) - 1
    eta_min = max(10, ahead * AVG_PIPELINE_SECONDS // 60) if ahead > 0 else 10

    _zpub_log(
        'storyteller_submit',
        ip=_client_ip(),
        session_id=sid[:8] + '…',
        job_id=job_id,
        char_id=char_id[:8] if char_id else None,
        story_prompt_preview=story_prompt[:80],
    )

    return jsonify(
        {'job_id': job_id, 'status': 'queued', 'queue_position': qlen, 'ahead': max(0, ahead), 'eta_minutes': eta_min}
    )


@bp.route('/api/benchmark', methods=['GET'])
@limiter.limit('30 per minute')
def api_benchmark():
    """Proxy: fetch benchmark telemetry from main app."""
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/benchmark',
            headers=_int_headers(),
            timeout=10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Main app unreachable: {e}', 'rows': []}), 503
