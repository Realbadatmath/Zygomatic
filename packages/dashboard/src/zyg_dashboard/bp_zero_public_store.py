# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import fcntl as _fcntl
import json
import os
import threading
from flask import Blueprint, jsonify, request
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.paths import ZYG_PUBLIC_URL
from zyg_dashboard.crewai_web_gui import (
    _contact_sheet_launch_run,
    _contact_sheet_mark_declined,
    _contact_sheet_mark_manifest_approved,
    _contact_sheet_parse_start_payload,
    secrets,
    timedelta,
)

# Round-2 split homes: see packages/dashboard/docs/gui_split_map.md
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR
from zyg_dashboard.gui.timeutil import _ams_now, _parse_iso_to_ams
from zyg_dashboard.gui.zero_store import _zero_audit_log
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

bp = Blueprint('zero_public_store', __name__)


# ── Zero Public URL token store ────────────────────────────────────────────────
_ZPUB_URLS_PATH = os.path.join(_RUNTIME_DIR, 'zero_public_urls.json')
_ZPUB_LOCK = threading.Lock()  # in-process lock; fcntl used for file-level lock
_ZPUB_TTL_DAYS = 7
_ZPUB_PUBLIC_BASE = os.environ.get('ZPUB_PUBLIC_BASE', 'http://ZygomaticsZero.local:5001').rstrip('/')
_ZPUB_TUNNEL_SIDECAR = os.path.join(_RUNTIME_DIR, 'tunnel_url.txt')

#: An invite normally carries nothing but a label. When a caller does name a deliverable in
#: the mint request, these are the keys it arrives under, and the token hands that file to a
#: stranger — so under ZYG_C2PA=strict it has to be sealed before the token exists.
_ZPUB_DELIVERABLE_KEYS = ('deliverable', 'file', 'path')


def _zpub_public_base() -> str:
    """Return the current public base URL — prefers live Cloudflare tunnel sidecar over env var."""
    try:
        with open(_ZPUB_TUNNEL_SIDECAR) as _f:
            url = _f.read().strip()
        if url.startswith('http'):
            return url.rstrip('/')
    except FileNotFoundError as _exc:
        _zyg_log.debug('no tunnel sidecar, using the configured public base: %s', _exc)
    return _ZPUB_PUBLIC_BASE


def _zpub_load() -> list:
    """Load token list from disk, auto-marking expired entries."""
    if not os.path.isfile(_ZPUB_URLS_PATH):
        return []
    try:
        with open(_ZPUB_URLS_PATH, 'r', encoding='utf-8') as _f:
            data = json.load(_f)
    except Exception:
        return []
    now = _ams_now()
    changed = False
    for entry in data:
        if 'permission' not in entry:
            entry['permission'] = 'automatic'
            changed = True
        if entry.get('status') == 'active':
            expires = entry.get('expires_at', '')
            try:
                _exp_dt = _parse_iso_to_ams(expires)
                if _exp_dt and _exp_dt < now:
                    entry['status'] = 'expired'
                    changed = True
            except Exception as _exc:
                _zyg_log.warning('expiry %r unparsable, leaving the token active: %s', expires, _exc)
    if changed:
        _zpub_save_raw(data)
    return data


def _zpub_save_raw(data: list) -> None:
    """Write token list to disk (no locking — caller must hold lock)."""
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    tmp = _ZPUB_URLS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as _f:
        json.dump(data, _f, indent=2, ensure_ascii=False)
    os.replace(tmp, _ZPUB_URLS_PATH)


def _zpub_save(data: list) -> None:
    """Write token list with in-process lock."""
    with _ZPUB_LOCK:
        _zpub_save_raw(data)


def _zpub_find(token: str, data: list) -> dict | None:
    """Return the entry matching token, or None."""
    return next((e for e in data if e.get('token') == token), None)


def _zpub_atomic_increment(token: str) -> dict:
    """
    Thread-safe, file-safe counter increment.
    Returns dict with keys: ok (bool), entry (dict), reason (str).
    Uses both threading.Lock (in-process) and fcntl.flock (cross-process).
    """
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    lock_path = _ZPUB_URLS_PATH + '.lock'
    with _ZPUB_LOCK:
        try:
            lf = open(lock_path, 'w')
            _fcntl.flock(lf, _fcntl.LOCK_EX)
            data = _zpub_load()
            entry = _zpub_find(token, data)
            if not entry:
                return {'ok': False, 'reason': 'token_not_found', 'entry': None}
            now = _ams_now()
            # Check expiry
            try:
                _exp_dt = _parse_iso_to_ams(entry.get('expires_at', ''))
                if _exp_dt and _exp_dt < now:
                    entry['status'] = 'expired'
                    _zpub_save_raw(data)
                    return {'ok': False, 'reason': 'expired', 'entry': entry}
            except Exception as _exc:
                _zyg_log.warning('expiry %r unparsable, not expiring the token: %s', entry.get('expires_at', ''), _exc)
            if entry.get('status') == 'revoked':
                return {'ok': False, 'reason': 'revoked', 'entry': entry}
            if entry.get('permission') == 'manual':
                _zero_audit_log('debug_manual_permission_check', {'token': token, 'permission': 'manual'})
                return {'ok': False, 'reason': 'manual_permission_required', 'entry': entry}
            else:
                _zero_audit_log(
                    'debug_manual_permission_check', {'token': token, 'permission': entry.get('permission', 'none')}
                )
            used = int(entry.get('used_requests', 0))
            max_r = int(entry.get('max_requests', 2))
            if used >= max_r:
                entry['status'] = 'exhausted'
                _zpub_save_raw(data)
                return {'ok': False, 'reason': 'exhausted', 'entry': entry}
            entry['used_requests'] = used + 1
            if entry['used_requests'] >= max_r:
                entry['status'] = 'exhausted'
            _zpub_save_raw(data)
            return {'ok': True, 'reason': 'ok', 'entry': entry}
        finally:
            try:
                _fcntl.flock(lf, _fcntl.LOCK_UN)
                lf.close()
            except Exception as _exc:
                _zyg_log.warning('releasing the zpub store lock failed: %s', _exc)


# ── Zero Public URL API (login-protected) ──────────────────────────────────────


@bp.route('/api/zero_public/urls', methods=['GET'])
def api_zpub_list():
    data = _zpub_load()
    base = _zpub_public_base()
    enriched = [{**e, 'invite_url': f'{base}/u/{e["token"]}'} for e in data]
    return jsonify({'urls': enriched, 'public_base': base})


@bp.route('/api/zero_public/urls', methods=['POST'])
def api_zpub_create():
    body = request.get_json(silent=True) or {}
    label = (body.get('label') or '').strip()[:80]
    max_req = max(1, min(100, int(body.get('max_requests', 2))))
    perm = (body.get('permission') or 'automatic').strip()
    if perm not in ('automatic', 'manual'):
        perm = 'automatic'
    if not label:
        return jsonify({'error': 'label is required'}), 400
    deliverable = next((str(body[k]) for k in _ZPUB_DELIVERABLE_KEYS if body.get(k)), '')
    if (
        deliverable
        and (os.environ.get('ZYG_C2PA', 'warn') or '').strip().lower() == 'strict'
        and os.path.splitext(deliverable)[1].lower() in _seal.SUPPORTED
        and not _seal.is_sealed(deliverable)
    ):
        return jsonify({'error': 'deliverable is not sealed'}), 409
    token = secrets.token_hex(16)
    now = _ams_now()
    expires = now + timedelta(days=_ZPUB_TTL_DAYS)
    entry = {
        'token': token,
        'label': label,
        'permission': perm,
        'max_requests': max_req,
        'used_requests': 0,
        'created_at': now.isoformat(),
        'expires_at': expires.isoformat(),
        'status': 'active',
    }
    with _ZPUB_LOCK:
        data = _zpub_load()
        data.append(entry)
        _zpub_save_raw(data)
    _zero_audit_log(
        'zpub_create', {'label': label, 'max_requests': max_req, 'permission': perm, 'token': token[:8] + '…'}
    )
    return jsonify({'entry': {**entry, 'invite_url': f'{_zpub_public_base()}/u/{token}'}})


@bp.route('/api/zero_public/urls/<token>', methods=['DELETE'])
def api_zpub_revoke(token):
    with _ZPUB_LOCK:
        data = _zpub_load()
        entry = _zpub_find(token, data)
        if not entry:
            return jsonify({'error': 'not found'}), 404
        entry['status'] = 'revoked'
        _zpub_save_raw(data)
    _zero_audit_log('zpub_revoke', {'token': token[:8] + '…'})
    return jsonify({'ok': True})


@bp.route('/api/zero_public/token_check/<token>', methods=['GET'])
def api_zpub_token_check(token):
    """Used by zero_public_server to validate a token WITHOUT incrementing."""
    data = _zpub_load()
    entry = _zpub_find(token, data)
    if not entry:
        return jsonify({'valid': False, 'reason': 'token_not_found'}), 404
    return jsonify(
        {'valid': entry.get('status') in ('active', 'exhausted'), 'reason': entry.get('status'), 'entry': entry}
    )


@bp.route('/api/zero_public/token_use/<token>', methods=['POST'])
def api_zpub_token_use(token):
    """Called by zero_public_server when a job is actually submitted — atomically increments counter."""
    result = _zpub_atomic_increment(token)
    if result['ok']:
        return jsonify({'ok': True, 'entry': result['entry']})
    return jsonify({'ok': False, 'reason': result['reason'], 'entry': result['entry']}), 403


# ── Manual-permission pending queue ──────────────────────────────────────────
_ZPUB_PENDING_PATH = os.path.join(os.path.dirname(__file__), 'data', 'runtime', 'zpub_pending.json')
_ZPUB_PENDING_LOCK = threading.Lock()
_ZPUB_PUBLIC_SERVER = os.environ.get('ZERO_PUBLIC_SERVER_URL', ZYG_PUBLIC_URL)


def _zpub_pending_load() -> list:
    try:
        with open(_ZPUB_PENDING_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def _zpub_pending_save(data: list) -> None:
    os.makedirs(os.path.dirname(_ZPUB_PENDING_PATH), exist_ok=True)
    tmp = _ZPUB_PENDING_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _ZPUB_PENDING_PATH)


@bp.route('/api/zero_public/pending', methods=['GET'])
def api_zpub_pending_list():
    """Return pending manual-permission requests for the dashboard."""
    with _ZPUB_PENDING_LOCK:
        data = _zpub_pending_load()
    # Return only pending/queued items (exclude decided ones older than 24h)
    import datetime as _dt

    cutoff = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(hours=24)).isoformat() + 'Z'
    visible = [
        r
        for r in data
        if r.get('status') == 'pending'
        or r.get('status') == 'queued'
        or (r.get('status') in ('approved', 'declined') and (r.get('decided_at') or '') > cutoff)
    ]
    return jsonify({'pending': visible, 'count': sum(1 for r in visible if r.get('status') == 'pending')})


@bp.route('/api/zero_public/pending/<req_id>/decide', methods=['POST'])
def api_zpub_pending_decide(req_id: str):
    """Operator decides on a pending manual request: allow | queue | decline."""
    body = request.get_json(force=True, silent=True) or {}
    action = (body.get('action') or '').lower().strip()
    if action not in ('allow', 'queue', 'decline'):
        return jsonify({'error': 'action must be allow, queue, or decline'}), 400

    with _ZPUB_PENDING_LOCK:
        data = _zpub_pending_load()
        req = next((r for r in data if r['id'] == req_id), None)
        if not req:
            return jsonify({'error': 'Pending request not found'}), 404
        if req.get('status') not in ('pending', 'queued'):
            return jsonify({'error': f'Request already {req["status"]}'}), 409

        import datetime as _dt

        now = _dt.datetime.utcnow().isoformat() + 'Z'

        # Decision latency (2026-07-18): observed 4-second 03:00 approvals
        # suggested the review gate was being rubber-stamped. Log the
        # request→decision gap so approval quality is measurable; a sub-30s
        # allow on a review card means nobody looked at the sheet.
        try:
            _req_ts = _dt.datetime.fromisoformat(
                (req.get('requested_at') or '').replace('Z', '+00:00'),
            )
            _lat_s = round(
                (_dt.datetime.now(_dt.timezone.utc) - _req_ts).total_seconds(),
                1,
            )
        except (ValueError, TypeError):
            _lat_s = None
        _zero_audit_log(
            'zpub_decision_latency',
            {
                'req_id': req_id,
                'pipeline': (req.get('pipeline') or ''),
                'action': action,
                'latency_s': _lat_s,
                'rubber_stamp_suspect': bool(_lat_s is not None and _lat_s < 30 and action == 'allow'),
            },
        )

        _pipeline_kind = (req.get('pipeline') or '').strip().lower()

        # 2026-08-09 licence gate at the approval boundary. A contact-sheet run
        # TRAINS the adapter it will render with, so at this point the only
        # knowable licence fact is the base family it will derive from. Refusing
        # here costs an approval; letting it through costs a GPU slot and then
        # stops at the render gate anyway. Fail-open by design: a broken licence
        # module must not freeze the approval queue.
        if action == 'allow':
            try:
                from zyg_workflows import licence_provenance as _lp

                # A creature review card carries its train family in `model`
                # and has no body_snapshot (the run already exists). Without
                # this it fell through to the flux default and the licence gate
                # refused every klein creature approval — 2026-08-26.
                _fam = (
                    (req.get('body_snapshot') or {}).get('model_family')
                    or (req.get('model') if _pipeline_kind == 'creature_review' else '')
                    or os.environ.get('ZYG_CHAR_DEFAULT_MODEL_FAMILY', 'flux')
                )
                _dec = _lp.family_decision(_fam)
                if not _dec['allowed']:
                    _zero_audit_log(
                        'licence_refused_approval',
                        {
                            'req_id': req_id,
                            'family': _dec['family'],
                            'verdict': _dec['verdict'],
                            'reason': _dec['reason'],
                        },
                    )
                    return jsonify(
                        {
                            'error': f'Licence gate refused this run: {_dec["reason"]}.',
                            'licence_verdict': _dec['verdict'],
                            'family': _dec['family'],
                        }
                    ), 409
            except ImportError as _exc:
                _zyg_log.warning('licence gate module unavailable, the run is not gated: %s', _exc)
            except Exception as _lic_exc:  # never freeze the queue on QC breakage
                _zyg_log.info(f'[zpub] licence gate skipped ({_lic_exc})')

        if action == 'allow' and _pipeline_kind == 'contact_sheet':
            # Start the parked contact-sheet run in-process — a direct function
            # call, not a self-POST (that hop hit the before_request auth gate
            # and 401'd since it carried no X-Zero-Public-Token header).
            try:
                payload = dict(req.get('body_snapshot') or {})
                payload['zero_approved'] = True
                _sp = _contact_sheet_parse_start_payload(payload)
                resp_payload, _st = _contact_sheet_launch_run(_sp)
                if _st == 200:
                    cid = resp_payload.get('char_id', '')
                    req['status'] = 'approved'
                    req['decided_at'] = now
                    req['approved_job_id'] = cid
                    _zpub_pending_save(data)
                    _zero_audit_log('contact_sheet_approved', {'req_id': req_id, 'char_id': cid})
                    return jsonify({'ok': True, 'action': 'allow', 'job_id': cid})
                return jsonify(
                    {
                        'error': resp_payload.get('message') or f'contact-sheet start returned {_st}',
                    }
                ), 502
            except Exception as exc:
                return jsonify({'error': f'contact-sheet start failed: {exc}'}), 502

        if action == 'allow' and _pipeline_kind == 'character_generate':
            # 2026-07-31: character generation now parks for operator approval like
            # contact_sheet does (it launches GPU LoRA training and a billed brief).
            # Same in-process launch, not a self-POST — the HTTP hop would hit the
            # auth gate with no internal token.
            try:
                from zyg_dashboard import bp_storyteller as _bps_cg

                resp_payload, _st = _bps_cg.launch_character_generate_from_snapshot(
                    req.get('body_snapshot') or {},
                )
                if _st in (200, 202):
                    cid = resp_payload.get('char_id', '')
                    req['status'] = 'approved'
                    req['decided_at'] = now
                    req['approved_job_id'] = cid
                    _zpub_pending_save(data)
                    _zero_audit_log('character_generate_approved', {'req_id': req_id, 'char_id': cid})
                    return jsonify({'ok': True, 'action': 'allow', 'job_id': cid})
                return jsonify(
                    {
                        'error': resp_payload.get('error')
                        or resp_payload.get('message')
                        or f'character-generate start returned {_st}',
                    }
                ), 502
            except Exception as exc:
                return jsonify({'error': f'character-generate start failed: {exc}'}), 502

        if action == 'allow' and _pipeline_kind == 'creature_review':
            # Creature sheet review (2026-08-26): resume the parked run straight
            # into captions + LoRA training. Same in-process call the API route
            # makes — no self-POST, which would hit the auth gate with no token.
            cid = (req.get('creature_id') or req.get('char_id') or '').strip()
            try:
                from zyg_dashboard import bp_pipeline_api as _bpa_cr

                resp_payload, _st = _bpa_cr.approve_creature_review(cid)
            except Exception as exc:
                return jsonify({'error': f'creature approve failed: {exc}'}), 502
            if _st != 200:
                return jsonify(resp_payload), _st
            req['status'] = 'approved'
            req['decided_at'] = now
            req['approved_job_id'] = cid
            _zpub_pending_save(data)
            _zero_audit_log('creature_review_approved', {'req_id': req_id, 'creature_id': cid})
            return jsonify({'ok': True, 'action': 'allow', 'job_id': cid})

        if action == 'allow' and _pipeline_kind == 'contact_sheet_review':
            # Mid-run sheet review: flip the manifest flag the worker polls.
            cid = (req.get('char_id') or '').strip()
            try:
                _contact_sheet_mark_manifest_approved(cid)
            except Exception as exc:
                return jsonify({'error': f'manifest approve failed: {exc}'}), 500
            req['status'] = 'approved'
            req['decided_at'] = now
            req['approved_job_id'] = cid
            _zpub_pending_save(data)
            _zero_audit_log('contact_sheet_review_approved', {'req_id': req_id, 'char_id': cid})
            return jsonify({'ok': True, 'action': 'allow', 'job_id': cid})

        if action == 'allow':
            # Tell zero_public_server to run this job
            try:
                import requests as _req

                # 2026-07-31: run_approved no longer trusts remote_addr==127.0.0.1.
                # Behind the cloudflared tunnel EVERY public visitor presented as
                # loopback, so that shortcut let a requester approve their own job.
                # This hop must now present the shared internal credential.
                resp = _req.post(
                    f'{_ZPUB_PUBLIC_SERVER}/api/admin/run_approved/{req_id}',
                    headers={'X-Zero-Public-Token': os.environ.get('ZERO_PUBLIC_TOKEN', '')},
                    timeout=10,
                )
                if resp.status_code == 200:
                    job_id = resp.json().get('job_id', '')
                    req['status'] = 'approved'
                    req['decided_at'] = now
                    req['approved_job_id'] = job_id
                    _zpub_pending_save(data)
                    _zero_audit_log(
                        'zpub_manual_approved', {'req_id': req_id, 'job_id': job_id, 'label': req.get('label', '')}
                    )
                    return jsonify({'ok': True, 'action': 'allow', 'job_id': job_id})
                else:
                    return jsonify({'error': f'zero_public_server returned {resp.status_code}'}), 502
            except Exception as exc:
                return jsonify({'error': f'Could not reach zero_public_server: {exc}'}), 502

        elif action == 'queue':
            req['status'] = 'queued'
            _zpub_pending_save(data)
            _zero_audit_log('zpub_manual_queued', {'req_id': req_id, 'label': req.get('label', '')})
            return jsonify({'ok': True, 'action': 'queue'})

        else:  # decline
            # Contact-sheet declines must also move the JOB off awaiting_approval
            # (2026-07-20): flipping only the card left the run reporting
            # awaiting_approval, so the wizard kept showing "awaiting your
            # decision" for an already-declined card.
            if _pipeline_kind in ('contact_sheet', 'contact_sheet_review'):
                _cid = (req.get('char_id') or '').strip()
                if _cid:
                    try:
                        _contact_sheet_mark_declined(_cid)
                    except Exception as _dexc:
                        _zero_audit_log(
                            'contact_sheet_decline_error',
                            {'req_id': req_id, 'char_id': _cid, 'error': str(_dexc)[:200]},
                        )
            elif _pipeline_kind == 'creature_review':
                # Same rule as the contact sheet: flipping only the card would
                # leave the run reporting awaiting_review for ever.
                _cid = (req.get('creature_id') or req.get('char_id') or '').strip()
                if _cid:
                    try:
                        from zyg_dashboard import bp_pipeline_api as _bpa_dec

                        _bpa_dec.reject_creature_review(_cid, 'declined at sheet review')
                    except Exception as _dexc:
                        _zero_audit_log(
                            'creature_review_decline_error',
                            {'req_id': req_id, 'creature_id': _cid, 'error': str(_dexc)[:200]},
                        )
            req['status'] = 'declined'
            req['decided_at'] = now
            _zpub_pending_save(data)
            _zero_audit_log('zpub_manual_declined', {'req_id': req_id, 'label': req.get('label', '')})
            return jsonify({'ok': True, 'action': 'decline'})
