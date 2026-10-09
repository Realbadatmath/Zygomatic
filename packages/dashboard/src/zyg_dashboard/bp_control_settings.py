# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Added 2026-08-05 — "Control Settings" tab (Settings > Security > Control Settings).
#
# A single master catalogue of every guardrail, quality gate, parameter, and
# content policy rule enforced across Medusa, Creator Nexus, the port-5000
# platform core, and the generation pipelines ("workflows"), each row carrying
# a unique ID and a Name / Function / Activated / Location so it can be
# individually verified and maintained over time.
#
# Gated by its own password, independent of the normal dashboard login:
#   - username is fixed to "Zygomatic" (not stored — nothing to check it against)
#   - first visit offers a one-time setup: password + confirm, must match
#   - the password is never stored in a recoverable form. It is salted and run
#     through PBKDF2-HMAC-SHA256 at 600,000 iterations (OWASP 2023 minimum for
#     this KDF) before being written to disk — a one-way digest, not
#     encryption, so there is no key anywhere that could decrypt it back.
#   - nobody, including this server process's own code paths, ever reads the
#     password back out — only a fresh attempt can be re-hashed and compared.
#
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist).
import logging as _zyg_logging
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time

from flask import Blueprint, jsonify, request, session

bp = Blueprint('control_settings', __name__)

from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    get_remote_address,
    limiter,
)

_zyg_log = _zyg_logging.getLogger(__name__)


_CS_DIR = os.path.join(_RUNTIME_DIR, 'control_settings')
_AUTH_PATH = os.path.join(_CS_DIR, 'auth.json')
_LOCKOUT_LOG_PATH = os.path.join(_CS_DIR, 'unlock_attempts.jsonl')

_CATEGORIES = {
    'guardrails': os.path.join(_CS_DIR, 'guardrails.json'),
    'quality_gates': os.path.join(_CS_DIR, 'quality_gates.json'),
    'parameters': os.path.join(_CS_DIR, 'parameters.json'),
    'policy_rules': os.path.join(_CS_DIR, 'policy_rules.json'),
}

_ID_PREFIX = {
    'guardrails': 'GRD',
    'quality_gates': 'QGT',
    'parameters': 'PRM',
    'policy_rules': 'PLC',
}

FIXED_USERNAME = 'Zygomatic'
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10

_lock = threading.Lock()
_fail_lock = threading.Lock()
_fail_counts = {}  # ip -> [timestamps of recent failures]
_LOCKOUT_WINDOW_SEC = 15 * 60
_LOCKOUT_MAX_ATTEMPTS = 5


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json_private(path, data):
    """Write JSON atomically and lock the file down to owner-only (auth.json holds the password digest)."""
    os.makedirs(_CS_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as _exc:
        _zyg_log.warning('owner-only chmod of %s failed, it keeps the default permissions: %s', tmp, _exc)
    os.replace(tmp, path)


def _save_json(path, data):
    os.makedirs(_CS_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def _verify_password(password, salt_hex, hash_hex, iterations):
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return hmac.compare_digest(digest.hex(), hash_hex)


def _is_admin():
    return session.get('user_role') in ('admin', 'admins')


def _is_locked_out(ip):
    with _fail_lock:
        attempts = _fail_counts.get(ip) or []
        now = time.time()
        attempts = [t for t in attempts if now - t < _LOCKOUT_WINDOW_SEC]
        _fail_counts[ip] = attempts
        return len(attempts) >= _LOCKOUT_MAX_ATTEMPTS


def _record_failure(ip):
    with _fail_lock:
        _fail_counts.setdefault(ip, []).append(time.time())


def _clear_failures(ip):
    with _fail_lock:
        _fail_counts.pop(ip, None)


def _next_id(category, items):
    prefix = _ID_PREFIX[category]
    best = 0
    for it in items:
        rid = str(it.get('id') or '')
        if rid.startswith(prefix + '-'):
            try:
                n = int(rid.split('-', 1)[1])
                best = max(best, n)
            except ValueError as _exc:
                _zyg_log.debug('ignoring id with a non-numeric suffix %s: %s', rid, _exc)
    return f'{prefix}-{best + 1:03d}'


@bp.route('/api/control-settings/status')
def cs_status():
    if not _is_admin():
        return jsonify({'success': False, 'message': 'Admin role required'}), 403
    configured = os.path.exists(_AUTH_PATH)
    return jsonify(
        {
            'success': True,
            'username': FIXED_USERNAME,
            'configured': configured,
            'unlocked': bool(session.get('control_settings_unlocked')),
        }
    )


@bp.route('/api/control-settings/setup', methods=['POST'])
@limiter.limit('5/hour', key_func=get_remote_address)
def cs_setup():
    if not _is_admin():
        return jsonify({'success': False, 'message': 'Admin role required'}), 403
    with _lock:
        if os.path.exists(_AUTH_PATH):
            return jsonify({'success': False, 'message': 'A Control Settings password is already configured.'}), 409
        data = request.get_json(silent=True) or {}
        password = data.get('password') or ''
        confirm = data.get('confirm_password') or ''
        if len(password) < MIN_PASSWORD_LENGTH:
            return jsonify(
                {'success': False, 'message': f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'}
            ), 400
        if not hmac.compare_digest(password, confirm):
            return jsonify({'success': False, 'message': 'Password and confirmation do not match.'}), 400
        salt_hex, hash_hex = _hash_password(password)
        _save_json_private(
            _AUTH_PATH,
            {
                'username': FIXED_USERNAME,
                'algo': 'pbkdf2_sha256',
                'iterations': PBKDF2_ITERATIONS,
                'salt': salt_hex,
                'hash': hash_hex,
            },
        )
    session['control_settings_unlocked'] = True
    return jsonify({'success': True, 'message': 'Control Settings password created.'})


@bp.route('/api/control-settings/unlock', methods=['POST'])
@limiter.limit('10/minute', key_func=get_remote_address)
def cs_unlock():
    if not _is_admin():
        return jsonify({'success': False, 'message': 'Admin role required'}), 403
    ip = get_remote_address()
    if _is_locked_out(ip):
        return jsonify({'success': False, 'message': 'Too many failed attempts. Try again in 15 minutes.'}), 429
    auth = _load_json(_AUTH_PATH, None)
    if not auth:
        return jsonify({'success': False, 'message': 'Control Settings has not been set up yet.'}), 409
    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    ok = bool(password) and _verify_password(
        password, auth['salt'], auth['hash'], auth.get('iterations', PBKDF2_ITERATIONS)
    )
    if not ok:
        _record_failure(ip)
        return jsonify({'success': False, 'message': 'Incorrect password.'}), 401
    _clear_failures(ip)
    session['control_settings_unlocked'] = True
    return jsonify({'success': True})


@bp.route('/api/control-settings/lock', methods=['POST'])
def cs_lock():
    session.pop('control_settings_unlocked', None)
    return jsonify({'success': True})


def _require_unlocked():
    if not _is_admin():
        return jsonify({'success': False, 'message': 'Admin role required'}), 403
    if not session.get('control_settings_unlocked'):
        return jsonify({'success': False, 'message': 'Control Settings is locked.'}), 401
    return None


@bp.route('/api/control-settings/data')
def cs_data_all():
    err = _require_unlocked()
    if err:
        return err
    out = {}
    for cat, path in _CATEGORIES.items():
        out[cat] = _load_json(path, {'items': []}).get('items', [])
    return jsonify({'success': True, 'data': out})


@bp.route('/api/control-settings/data/<category>', methods=['GET'])
def cs_data_get(category):
    err = _require_unlocked()
    if err:
        return err
    if category not in _CATEGORIES:
        return jsonify({'success': False, 'message': 'Unknown category'}), 404
    items = _load_json(_CATEGORIES[category], {'items': []}).get('items', [])
    return jsonify({'success': True, 'items': items})


@bp.route('/api/control-settings/data/<category>', methods=['PATCH'])
@limiter.limit('60/hour', key_func=get_remote_address)
def cs_data_patch(category):
    err = _require_unlocked()
    if err:
        return err
    if category not in _CATEGORIES:
        return jsonify({'success': False, 'message': 'Unknown category'}), 404
    body = request.get_json(silent=True) or {}
    items = body.get('items')
    if not isinstance(items, list):
        return jsonify({'success': False, 'message': 'Body must include an "items" array.'}), 400
    with _lock:
        for it in items:
            if not it.get('id'):
                it['id'] = _next_id(category, items)
            for field in ('name', 'function', 'location'):
                it[field] = str(it.get(field) or '').strip()
            if it.get('activated') not in ('yes', 'no', 'conditional'):
                it['activated'] = 'no'
        _save_json(_CATEGORIES[category], {'items': items})
    return jsonify({'success': True, 'items': items})
