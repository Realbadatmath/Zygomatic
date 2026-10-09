# ruff: noqa: F401  (this module inherits the original top import block)
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import hmac
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    stream_with_context,
)

from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal
from zyg_zero import settings, zpub_portfolio_deck
from zyg_zero.zpub_config import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_VIDEO_EXTS,
    AVG_PIPELINE_SECONDS,
    CHUNK_UPLOAD_ROOT,
    INTERNAL_TOKEN,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_BYTES,
    PREVIEW_CHUNK_BYTES,
    RATE_LIMIT_PER_HOUR,
    UPLOAD_ROOT,
    _ams_iso,
    public_url,
)
from zyg_zero.zpub_gate import _gate_response, _require_api_session, _session_id, _session_invite, limiter
from zyg_zero.zpub_main_api import (
    _get_pipeline_status,
    _parse_creature_options,
    _parse_model_family,
    _parse_pipeline_options,
    _token_check,
    _token_use,
)
from zyg_zero.zpub_store import (
    _check_rate_limit,
    _enqueue,
    _get_running,
    _jobs_for_library,
    _link_session_job,
    _link_token_job,
    _load_job,
    _pending_store,
    _queue_length,
    _queue_position,
    _save_job,
    _session_jobs,
    _set_running,
    _zpub_log,
)

bp = Blueprint('zpub_public', __name__)


@bp.app_context_processor
def _inject_licence_state():
    """Expose the FLUX licence pause to all templates.

    While ZYG_FLUX_RENDERS is paused (the default; flux1-dev is BFL
    Non-Commercial and the channel is monetised), the FLUX option is hidden
    from the public model pickers: character renders/training on the FLUX leg
    are hard-refused by the gate, so offering it only produces failed jobs.
    The option reappears automatically when the pause is lifted.
    Fail-closed: if the licence module can't be read, don't offer FLUX.
    """
    try:
        from zyg_workflows import licence_provenance as _lp

        return {'flux_renders_paused': bool(_lp.flux_paused())}
    except Exception:
        return {'flux_renders_paused': True}


# ── Routes ─────────────────────────────────────────────────────────────────────


@bp.route('/admin-enter')
def admin_enter():
    """Admin bypass — validates INTERNAL_TOKEN then opens a no-rate-limit admin session."""
    t = request.args.get('t', '')
    if not INTERNAL_TOKEN or not hmac.compare_digest(t.encode('utf-8'), INTERNAL_TOKEN.encode('utf-8')):
        return jsonify({'error': 'Forbidden'}), 403
    session['is_zpub_admin'] = True
    session.permanent = True
    _zpub_log('admin_enter', ip=request.remote_addr or 'unknown')
    return redirect('/')


@bp.route('/u/<token>')
def invite_page(token):
    """Invite-link entry point — validates the token then renders the appropriate page state."""
    ip = request.remote_addr or 'unknown'
    ua = request.headers.get('User-Agent', '')[:120]
    info = _token_check(token)
    if not info.get('valid', False):
        reason = info.get('reason', 'unknown')
        _zpub_log('invite_visit', ip=ip, token=token[:8] + '…', result=reason, user_agent=ua)
        if reason in ('expired', 'revoked', 'not_found'):
            return render_template(
                'zero_public.html',
                recent_jobs=[],
                active_job_id=None,
                invite_mode='expired',
                invite_token=token,
            ), 410
        # Main app unreachable or other error — show a soft error
        return render_template(
            'zero_public.html',
            recent_jobs=[],
            active_job_id=None,
            invite_mode='error',
            invite_token=token,
        ), 503
    entry = info.get('entry') or {}
    label = entry.get('label', '')
    # Resolve the stable per-browser session id up front — it's what keeps
    # the Library populated across invite-token rotation/expiry, not the
    # token itself (see _jobs_for_library).
    sid = _session_id()
    _zpub_log(
        'invite_visit',
        ip=ip,
        token=token[:8] + '…',
        invite_label=label,
        result=entry.get('status', 'active'),
        user_agent=ua,
    )
    if entry.get('status') == 'exhausted':
        # Still set the session token so the user can return and download their video
        session['zpub_invite_token'] = token
        session.permanent = True
        return render_template(
            'zero_public.html',
            recent_jobs=_jobs_for_library(token, sid),
            active_job_id=None,
            invite_mode='exhausted',
            invite_token=token,
            invite_label=label,
            invite_used=entry.get('used_requests', 0),
            invite_max=entry.get('max_requests', 2),
        )
    # Active link — show the normal submission form, scoped to this token
    session['zpub_invite_token'] = token  # persist so subsequent page loads stay open
    session.permanent = True
    return render_template(
        'zero_public.html',
        recent_jobs=_jobs_for_library(token, sid),
        active_job_id=None,
        invite_mode='active',
        invite_token=token,
        invite_label=label,
        invite_used=entry.get('used_requests', 0),
        invite_max=entry.get('max_requests', 2),
    )


# ── Vanity invite alias ────────────────────────────────────────────────────────
# A memorable URL to hand out on a CV / job application. The page is rendered
# IN PLACE rather than redirected, so the address bar keeps saying /Portfolio
# and the raw invite token is never shown. Point it elsewhere with
# ZPUB_PORTFOLIO_TOKEN (no default: a deployment names its own invite); unset,
# expired or revoked, this falls through to the normal expired-invite card like
# any other /u/<token> visit.
_PORTFOLIO_TOKEN = os.environ.get('ZPUB_PORTFOLIO_TOKEN', '')


@bp.route('/Portfolio')
@bp.route('/portfolio')
def portfolio_invite_page():
    """Vanity alias for the long-lived portfolio invite — renders /u/<token>."""
    return invite_page(_PORTFOLIO_TOKEN)
