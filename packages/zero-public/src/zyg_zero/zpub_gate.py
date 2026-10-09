# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import os
import re
import uuid
from flask import (
    jsonify,
    render_template,
    request,
    session,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from zyg_zero.zpub_main_api import _token_check
from zyg_zero.zpub_store import _zpub_log

# 2026-07-31: every external request reaches this app through the in-process
# cloudflared tunnel, so ``request.remote_addr`` is 127.0.0.1 for essentially
# 100% of public traffic (measured: 18,706 / 18,826 IP-bearing log events).
# Every per-IP limit therefore collapsed into ONE shared global bucket — a
# trivial denial of service against the whole public surface, and every abuse
# investigation resolved to '127.0.0.1'.
#
# The limiter key now PREFERS the edge-supplied client IP when one is present,
# but never at the cost of the existing protection:
#   * the key is ``remote_addr|edge_ip`` — the peer address always stays in the
#     key, so a caller can never escape their remote_addr bucket entirely;
#   * only ``CF-Connecting-IP`` is trusted (Cloudflare overwrites any
#     client-supplied value at the edge). ``X-Forwarded-For`` is deliberately
#     NOT trusted for the key: it is client-appendable, so honouring it would
#     hand an attacker an unlimited supply of fresh buckets;
#   * the header is only consulted when the peer is loopback/private, i.e. the
#     request really did arrive via the local tunnel.
# Set ZYG_ZPUB_FORWARDED_IP_KEY=0 to restore the pre-2026-07-31 behaviour.
_ZPUB_FORWARDED_IP_KEY = (os.environ.get('ZYG_ZPUB_FORWARDED_IP_KEY', '1') or '').strip().lower() not in (
    '0',
    'false',
    'no',
    'off',
)

# Header set (and overwritten) by the Cloudflare edge. Not client-controllable
# for traffic that actually transited Cloudflare.
_TRUSTED_CLIENT_IP_HEADER = 'CF-Connecting-IP'

_LOOPBACK_PEER_RE = re.compile(
    r'^(127\.|::1$|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|fd|fc)',
    re.IGNORECASE,
)


def _peer_is_local(addr: str) -> bool:
    """True when the TCP peer is loopback/private — i.e. the local tunnel."""
    return bool(addr) and bool(_LOOPBACK_PEER_RE.match(addr))


def _edge_client_ip() -> str:
    """Real client IP as reported by the Cloudflare edge, or '' when unknown."""
    if not _ZPUB_FORWARDED_IP_KEY:
        return ''
    try:
        peer = request.remote_addr or ''
        if not _peer_is_local(peer):
            return ''  # direct connection — headers are attacker-controlled
        raw = (request.headers.get(_TRUSTED_CLIENT_IP_HEADER) or '').strip()
    except Exception:
        return ''
    if not raw or len(raw) > 64:
        return ''
    # Single address only; anything comma-separated is a forwarded chain and
    # therefore not the edge header we trust.
    if ',' in raw or not re.match(r'^[0-9a-fA-F:.]+$', raw):
        return ''
    return raw


def _client_ip() -> str:
    """Best-known client address for logging/attribution (never raises)."""
    try:
        peer = request.remote_addr or 'unknown'
    except Exception:
        return 'unknown'
    edge = _edge_client_ip()
    return f'{peer}|{edge}' if edge else peer


def _rate_limit_key() -> str:
    """Limiter key: peer address, narrowed by the trusted edge IP when present.

    Never weaker than ``get_remote_address`` — the peer address is always part
    of the key; the edge IP only SPLITS an existing bucket into per-visitor
    sub-buckets.
    """
    try:
        peer = get_remote_address() or 'unknown'
    except Exception:
        peer = 'unknown'
    edge = _edge_client_ip()
    return f'{peer}|{edge}' if edge else peer


limiter = Limiter(
    key_func=_rate_limit_key,
    # Preview pages load many /uploads assets; per-route exempt handles those.
    default_limits=['2000 per hour'],
    storage_uri='memory://',  # fallback; rate-limit state is per-process
)
# NOTE: bound to the app in zero_public_server.py via limiter.init_app(app)


def _session_id() -> str:
    """Return (and create if needed) a stable session ID for this visitor."""
    if 'zpub_sid' not in session:
        session['zpub_sid'] = uuid.uuid4().hex
        session.permanent = True
    return session['zpub_sid']


def _session_invite() -> str | None:
    """Return the validated invite token stored in this session, or None."""
    return session.get('zpub_invite_token') or None


def _gate_response():
    """Return a 403 locked-gate response for requests with no valid session invite."""
    # 2026-07-31: log the edge-resolved client IP — remote_addr is 127.0.0.1
    # for all tunnel traffic, which made every abuse trail useless.
    ip = _client_ip()
    _zpub_log('gate_blocked', ip=ip, path=request.path, user_agent=request.headers.get('User-Agent', '')[:120])
    return render_template(
        'zero_public.html',
        recent_jobs=[],
        active_job_id=None,
        invite_mode='locked',
        invite_token=None,
    ), 403


def _api_gate_json(message: str = 'Session expired — refresh the page and open your invite link again.'):
    """JSON 403 for API routes (avoid HTML gate page breaking fetch().json())."""
    # 2026-07-31: see _gate_response — edge-resolved client IP.
    ip = _client_ip()
    _zpub_log('gate_blocked', ip=ip, path=request.path, user_agent=request.headers.get('User-Agent', '')[:120])
    return jsonify({'success': False, 'error': message}), 403


def _bootstrap_session_from_request() -> None:
    """Restore invite session from invite_token when the cookie session is missing."""
    if _session_invite() or session.get('is_zpub_admin'):
        return
    token = (request.form.get('invite_token') or '').strip() or (request.headers.get('X-Invite-Token') or '').strip()
    if not token or token == '__admin__':  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
        return
    info = _token_check(token)
    entry = info.get('entry') or {}
    if info.get('valid') or entry.get('status') == 'exhausted':
        session['zpub_invite_token'] = token
        session.permanent = True


def _require_api_session():
    _bootstrap_session_from_request()
    if not _session_invite() and not session.get('is_zpub_admin'):
        return _api_gate_json()
    return None
