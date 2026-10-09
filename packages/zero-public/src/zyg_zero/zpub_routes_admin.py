# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import json
import logging as _zyg_logging
import os
import uuid
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    session,
)

from zyg_zero.zpub_config import INTERNAL_TOKEN
from zyg_zero.zpub_store import (
    ZPUB_LOG_PATH,
    _LOG_DIR,
    _enqueue,
    _link_token_job,
    _load_job,
    _log_lock,
    _pending_load,
    _pending_lock,
    _pending_save,
    _persist_job,
    _save_job,
    _zpub_log,
)

bp = Blueprint('zpub_admin', __name__)

_zyg_log = _zyg_logging.getLogger(__name__)


# 2026-07-31: security hardening after the identity audit. Three routes in this
# module authorised on network position instead of on a credential:
#   * /api/admin/run_approved/<req_id>  skipped the token check for loopback,
#   * /api/pending_status/<req_id>      had no auth at all,
#   * /api/tunnel-url                   had no auth at all.
# The app is fronted by an in-process cloudflared tunnel (see
# _start_public_tunnel in zero_public_server.py) and had no ProxyFix, so
# request.remote_addr was 127.0.0.1 for ALL public traffic — the "internal
# only" loopback shortcut was in practice open to the entire internet.
# Each fix defaults to ON and reverts individually via its ZYG_ env flag.
def _zyg_flag(name: str, default: str = '1') -> bool:
    """Return True unless the env var is explicitly set to a falsey value."""
    return (os.environ.get(name, default) or '').strip().lower() not in (
        '',
        '0',
        'false',
        'no',
        'off',
    )


# Require a real credential on /api/admin/run_approved (was: loopback bypass).
ZYG_ZPUB_ADMIN_STRICT_AUTH = _zyg_flag('ZYG_ZPUB_ADMIN_STRICT_AUTH')
# Gate /api/pending_status on the submitter's own session/invite (was: open).
ZYG_ZPUB_PENDING_STATUS_AUTH = _zyg_flag('ZYG_ZPUB_PENDING_STATUS_AUTH')
# Gate /api/tunnel-url on an invite session or the admin token (was: open).
ZYG_ZPUB_TUNNEL_URL_AUTH = _zyg_flag('ZYG_ZPUB_TUNNEL_URL_AUTH')


# ── Admin: user activity logs ──────────────────────────────────────────────────


def _check_admin(req) -> bool:
    """Return True if request carries a valid admin token (reuses INTERNAL_TOKEN).

    2026-07-31: additionally accept the ``X-Zero-Public-Token`` header — that is
    the header the internal main-app proxy already builds in ``_int_headers()``
    (zpub_main_api.py), so internal callers have a credential path that does not
    depend on the removed localhost bypass. compare_digest is wrapped because it
    raises TypeError on non-ASCII input (an attacker-controlled header must not
    be able to 500 this route).
    """
    if not INTERNAL_TOKEN:
        return False
    import hmac as _hmac

    for t in (
        (req.args.get('token') or '').strip(),
        (req.headers.get('Authorization') or '').removeprefix('Bearer ').strip(),
        (req.headers.get('X-Zero-Public-Token') or '').strip(),
    ):
        if not t:
            continue
        try:
            if _hmac.compare_digest(t, INTERNAL_TOKEN):
                return True
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    return False


@bp.route('/api/admin/run_approved/<req_id>', methods=['POST'])
def api_admin_run_approved(req_id: str):
    """Called by crewai_web_gui when operator approves a pending manual request.
    Re-submits the stored payload through the normal pipeline path."""
    # 2026-07-31 SECURITY FIX: this used to skip _check_admin entirely whenever
    # request.remote_addr looked like loopback. cloudflared terminates the
    # public tunnel in-process and there was no ProxyFix, so remote_addr was
    # 127.0.0.1 for EVERY public visitor (verified: 18,734 of ~18,900 logged
    # events in data/runtime/zpub_user_log.jsonl carry ip=127.0.0.1 against ~100
    # from real LAN addresses). Since POST /api/storyteller/generate returns the
    # submitter their own pending_id in its 202 body, any internet visitor could
    # POST it straight back here and self-approve a parked job, bypassing the
    # manual operator-review gate that guards a ~45-minute GPU pipeline.
    # Auth is now unconditional; _check_admin accepts ?token=, Authorization:
    # Bearer, or the X-Zero-Public-Token header the internal proxy already uses.
    # EMERGENCY REVERT ONLY: ZYG_ZPUB_ADMIN_STRICT_AUTH=0 restores the old
    # loopback trust. Needed only if this ships before the cross-file change
    # that makes bp_zero_public_store.py send headers=_int_headers() on its
    # POST to /api/admin/run_approved/<req_id> (that caller currently sends no
    # credential at all and relies on the bypass).
    if not _check_admin(request):
        if ZYG_ZPUB_ADMIN_STRICT_AUTH:
            _zpub_log('admin_run_approved_denied', ip=request.remote_addr or 'unknown', req_id=req_id)
            return jsonify({'error': 'Forbidden'}), 403
        if (request.remote_addr or '') not in ('127.0.0.1', '::1', 'localhost'):
            return jsonify({'error': 'Forbidden'}), 403
        _zpub_log('admin_run_approved_legacy_localhost', ip=request.remote_addr or 'unknown', req_id=req_id)

    with _pending_lock:
        data = _pending_load()
        req = next((r for r in data if r['id'] == req_id), None)
        if not req:
            return jsonify({'error': 'Pending request not found'}), 404
        if req['status'] != 'pending':
            return jsonify({'error': f'Request already {req["status"]}'}), 409

    # 2026-07-25: storyteller manual requests park a FULLY-BUILT job (status
    # pending_approval) and reference it by id — just release it (flip to
    # queued + enqueue) rather than rebuilding a generic job that lacks the
    # storyteller_params/department the worker needs.
    _story_job_id = (req.get('body_snapshot') or {}).get('storyteller_job_id')
    if _story_job_id:
        parked = _load_job(_story_job_id)
        if not parked:
            return jsonify({'error': f'parked storyteller job {_story_job_id} not found'}), 404
        parked['status'] = 'queued'
        parked['current_stage'] = 'Waiting in queue…'
        _save_job(parked)
        _enqueue(_story_job_id)
        if req.get('token'):
            _link_token_job(req['token'], _story_job_id)
        with _pending_lock:
            data = _pending_load()
            for r in data:
                if r['id'] == req_id:
                    r['status'] = 'approved'
                    r['decided_at'] = datetime.utcnow().isoformat() + 'Z'
                    r['approved_job_id'] = _story_job_id
                    break
            _pending_save(data)
        _zpub_log('storyteller_manual_approved_run', req_id=req_id, job_id=_story_job_id)
        return jsonify({'ok': True, 'job_id': _story_job_id})

    # Re-run by injecting into the job queue using the stored body snapshot
    body = req.get('body_snapshot', {})
    body['prompt'] = req.get('prompt', body.get('prompt', ''))
    token = req.get('token', '')

    # Temporarily set session token so the submit route accepts it
    with current_app.test_request_context():
        pass  # no-op; we build the job directly below

    # Directly enqueue the job, bypassing token credit check (already approved)
    job_id = uuid.uuid4().hex
    pipeline_type = req.get('pipeline', body.get('pipeline_type', body.get('type', 'documentary')))
    job = {
        'job_id': job_id,
        'token': token,
        'prompt': req.get('prompt', ''),
        'pipeline': pipeline_type,
        'status': 'queued',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'output_files': [],
        'approved_from_pending': req_id,
    }
    # Copy all original body fields into job
    for k, v in body.items():
        if k not in job:
            job[k] = v

    _persist_job(job)
    _enqueue(job_id)
    # Link job to user's invite token so it appears in their library sidebar.
    # This was missing for the approval path — normal submissions call _link_token_job
    # at submit time, but approved-from-pending jobs skipped it entirely.
    if token:
        _link_token_job(token, job_id)

    # Mark pending request as approved
    with _pending_lock:
        data = _pending_load()
        for r in data:
            if r['id'] == req_id:
                r['status'] = 'approved'
                r['decided_at'] = datetime.utcnow().isoformat() + 'Z'
                r['approved_job_id'] = job_id
                break
        _pending_save(data)

    _zpub_log('manual_approved_run', req_id=req_id, job_id=job_id, pipeline=pipeline_type)
    return jsonify({'ok': True, 'job_id': job_id})


def _pending_status_authorised(req: dict) -> bool:
    """2026-07-31: /api/pending_status/<req_id> was completely ungated.

    Gated on the SUBMITTER's identity rather than on admin, because the
    legitimate pollers are the submitting user's own browser —
    templates/assets/js/zpub_pending_notification.js (_startPoll/_checkOnLoad)
    and templates/assets/js/zpub_storyteller.js (_stCsPendingPoll) — which send
    only the session cookie. Admin credentials are accepted too so the operator
    console keeps working.
    """
    if _check_admin(request) or session.get('is_zpub_admin'):
        return True
    # Read the session directly rather than calling zpub_gate._session_id(),
    # which would mint and persist a new sid as a side effect of a GET.
    sid = session.get('zpub_sid') or ''
    invite = session.get('zpub_invite_token') or ''
    if sid and req.get('session_id') and sid == req.get('session_id'):
        return True
    if invite and req.get('token') and invite == req.get('token'):
        return True
    # Legacy/foreign records carry neither field (58 of 76 rows on 2026-07-31 —
    # e.g. the contact-sheet cards written by the main app), so they cannot be
    # attributed to a submitter. Fall back to "any authenticated invite session"
    # so the existing polling UI degrades instead of hard-failing.
    if not req.get('session_id') and not req.get('token'):
        return bool(invite)
    return False


@bp.route('/api/pending_status/<req_id>', methods=['GET'])
def api_pending_status(req_id: str):
    """Polled by zero_public.html to track the status of a pending manual request."""
    data = _pending_load()
    req = next((r for r in data if r.get('id') == req_id), None)
    if not req:
        return jsonify({'error': 'Not found'}), 404
    # 2026-07-31: was unauthenticated — any visitor could poll any req_id.
    # ZYG_ZPUB_PENDING_STATUS_AUTH=0 reverts to open.
    if ZYG_ZPUB_PENDING_STATUS_AUTH and not _pending_status_authorised(req):
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(
        {
            'status': req.get('status', 'pending'),  # pending | queued | approved | declined
            'job_id': req.get('approved_job_id') or None,  # set when approved
        }
    )


def _read_logs(limit: int = 500) -> list:
    """Return the last `limit` log entries as a list of dicts."""
    if not os.path.isfile(ZPUB_LOG_PATH):
        return []
    entries = []
    try:
        with _log_lock:
            with open(ZPUB_LOG_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception as _exc:
                            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return entries[-limit:]


@bp.route('/api/admin/logs')
def api_admin_logs():
    if not _check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    limit = min(int(request.args.get('limit', 500)), 2000)
    return jsonify({'logs': list(reversed(_read_logs(limit)))})


@bp.route('/api/tunnel-url')
def api_tunnel_url():
    """Return the current Cloudflare tunnel URL (if active)."""
    # 2026-07-31: was unauthenticated. It discloses the public ingress URL,
    # which for a *quick* (trycloudflare) tunnel is effectively an unlisted
    # bypass URL. No caller exists in the live tree, so gate it on an invite
    # session or the admin token. ZYG_ZPUB_TUNNEL_URL_AUTH=0 reverts to open.
    if ZYG_ZPUB_TUNNEL_URL_AUTH and not (
        _check_admin(request) or session.get('is_zpub_admin') or session.get('zpub_invite_token')
    ):
        return jsonify({'error': 'Forbidden'}), 403
    sidecar = os.path.join(_LOG_DIR, 'tunnel_url.txt')
    try:
        with open(sidecar) as _f:
            url = _f.read().strip()
        return jsonify({'url': url, 'active': bool(url)})
    except FileNotFoundError:
        return jsonify({'url': None, 'active': False})


@bp.route('/admin/logs')
def admin_logs_page():
    if not _check_admin(request):
        return '<h1>401 Unauthorized</h1><p>Provide ?token=ZERO_PUBLIC_TOKEN</p>', 401
    token_param = request.args.get('token', '')
    entries = list(reversed(_read_logs(1000)))
    rows = []
    for e in entries:
        event = e.get('event', '')
        color = {
            'submit': '#7c3aed',
            'job_done': '#16a34a',
            'job_failed': '#dc2626',
            'rate_limited': '#d97706',
            'invite_rejected': '#b45309',
            'invite_visit': '#0891b2',
            'page_visit': '#475569',
            'job_start': '#2563eb',
        }.get(event, '#64748b')
        prompt = e.get('prompt_preview') or e.get('prompt', '')
        rows.append(f"""<tr>
          <td style="white-space:nowrap;color:#94a3b8">{e.get('ts', '')}</td>
          <td><span style="background:{color};color:#fff;padding:2px 7px;border-radius:4px;font-size:11px">{event}</span></td>
          <td style="font-family:monospace;font-size:12px">{e.get('ip', '')}</td>
          <td style="font-size:12px">{e.get('invite_label') or e.get('invite_token') or ''}</td>
          <td style="font-size:12px">{e.get('session_id', '')}</td>
          <td style="font-size:12px">{e.get('job_id', '')}</td>
          <td style="max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px" title="{prompt}">{prompt}</td>
          <td style="font-size:12px;color:#ef4444">{e.get('error', '') or ''}</td>
        </tr>""")
    rows_html = (
        '\n'.join(rows)
        if rows
        else '<tr><td colspan="8" style="text-align:center;padding:24px;color:#64748b">No log entries yet.</td></tr>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Zero — User Logs</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    * {{ box-sizing:border-box; margin:0; padding:0 }}
    body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:24px }}
    h1 {{ font-size:22px; font-weight:700; margin-bottom:4px }}
    p.sub {{ color:#64748b; font-size:13px; margin-bottom:20px }}
    .toolbar {{ display:flex; gap:8px; margin-bottom:14px; align-items:center }}
    input#filter {{ background:#1e293b; border:1px solid #334155; color:#e2e8f0; padding:6px 12px; border-radius:6px; font-size:13px; width:260px }}
    button {{ background:#7c3aed; color:#fff; border:none; padding:6px 14px; border-radius:6px; cursor:pointer; font-size:13px }}
    .wrap {{ overflow-x:auto }}
    table {{ border-collapse:collapse; width:100%; min-width:900px }}
    thead th {{ background:#1e293b; padding:8px 10px; text-align:left; font-size:12px; font-weight:600; color:#94a3b8; border-bottom:1px solid #334155; white-space:nowrap }}
    tbody tr {{ border-bottom:1px solid #1e293b }}
    tbody tr:hover {{ background:#1e293b }}
    tbody td {{ padding:7px 10px; vertical-align:top }}
    .count {{ color:#94a3b8; font-size:12px }}
  </style>
</head>
<body>
  <h1>Zero — User Logs</h1>
  <p class="sub">Showing last {len(entries)} entries &nbsp;·&nbsp; <span class="count">auto-refreshes on reload</span></p>
  <div class="toolbar">
    <input id="filter" type="text" placeholder="Filter by event, IP, prompt…" oninput="filterTable(this.value)">
    <button onclick="location.reload()">↻ Refresh</button>
    <button onclick="window.open('/api/admin/logs?token={token_param}','_blank')">JSON</button>
  </div>
  <div class="wrap">
    <table id="logtable">
      <thead><tr>
        <th>Timestamp (UTC)</th><th>Event</th><th>IP</th>
        <th>Invite</th><th>Session</th><th>Job ID</th>
        <th>Prompt preview</th><th>Error</th>
      </tr></thead>
      <tbody id="tbody">{rows_html}</tbody>
    </table>
  </div>
  <script>
    function filterTable(q) {{
      q = q.toLowerCase();
      document.querySelectorAll('#tbody tr').forEach(function(r) {{
        r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""
