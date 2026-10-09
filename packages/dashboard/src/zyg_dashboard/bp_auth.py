# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import re
from flask import (
    Blueprint,
    jsonify,
    redirect,
    request,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint('auth', __name__)
from zyg_dashboard.gui.runtime_state import _load_json, _save_json  # noqa: E402
from zyg_dashboard.gui.telemetry import SESSION_VALIDITY_TOKEN, _login_debug, _page_load_debug  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _ensure_csrf_token,
    app,
    get_remote_address,
    hashlib,
    hmac,
    limiter,
    url_for,
)
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first

_zyg_log = _zyg_logging.getLogger(__name__)


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
API_ADAPTER_AVAILABLE = getattr(_main_mod, 'API_ADAPTER_AVAILABLE', None)
API_DEV_MODE = getattr(_main_mod, 'API_DEV_MODE', None)
API_DEV_TOKEN = getattr(_main_mod, 'API_DEV_TOKEN', None)
DASHBOARD_AVAILABLE = getattr(_main_mod, 'DASHBOARD_AVAILABLE', None)
USERS_DATA_PATH = getattr(_main_mod, 'USERS_DATA_PATH', None)


# A bare 64-hex digest is the pre-2026-10-05 `password_hash`: unsalted sha256, so a
# single rainbow table broke every account at once. Records in that shape are still
# accepted once, then rewritten as a salted scrypt hash on the next successful login.
_LEGACY_SHA256_RE = re.compile(r'\A[0-9a-f]{64}\Z')


def _hash_password(password: str) -> str:
    """Salted, stretched hash of `password` (werkzeug scrypt) for storage in `password_hash`."""
    return generate_password_hash(password)


def _legacy_sha256(password: str) -> str:
    """The retired unsalted digest — read-only, to verify an un-upgraded record once."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _upgrade_password(user, password, users_data=None, users_path=None):
    """Rewrite a legacy credential as a salted hash and drop any plaintext field.

    Mutates `user` in place. When `users_data` (the whole file) and `users_path` are
    given, the upgraded file is persisted, so a legacy record is upgraded on the first
    successful login and the plaintext never survives it. The password itself is never
    logged.
    """
    user['password_hash'] = _hash_password(password)
    user.pop('passwords', None)
    user.pop('password', None)
    if users_data is not None and users_path:
        if not _save_json(users_path, users_data):
            _zyg_log.warning('password upgrade for %r could not be persisted', user.get('id'))


def _check_password(user, password, users_data=None, users_path=None):
    """Return True if `password` matches `user`; upgrade legacy credentials on success.

    Accepted shapes, in order: a salted werkzeug hash in `password_hash` (current), a
    bare sha256 digest in `password_hash` (legacy), a `passwords` list or a single
    `password` field in plaintext (legacy migration leftovers). The last three are
    verified once and then replaced by a salted hash via `_upgrade_password`.
    """
    if not password:
        return False
    stored_hash = user.get('password_hash')
    if stored_hash:
        if _LEGACY_SHA256_RE.match(stored_hash):
            if not hmac.compare_digest(stored_hash, _legacy_sha256(password)):
                return False
            _upgrade_password(user, password, users_data, users_path)
            return True
        return check_password_hash(stored_hash, password)
    # Legacy plaintext, kept only so a never-logged-in account can still be migrated.
    stored_list = user.get('passwords')
    candidates = [p for p in stored_list if isinstance(p, str)] if isinstance(stored_list, list) else []
    single = user.get('password')
    if isinstance(single, str):
        candidates.append(single)
    if not any(hmac.compare_digest(p, password) for p in candidates):
        return False
    _upgrade_password(user, password, users_data, users_path)
    return True


@bp.route('/api/login', methods=['POST'])
@limiter.limit('10/minute', key_func=get_remote_address)
def api_login():
    """Validate role + id/password (or spectators with no credentials) and set session."""
    data = request.get_json() or {}
    role = (data.get('role') or '').strip().lower()
    if role not in ('admins', 'operators', 'spectators'):
        return jsonify({'success': False, 'message': 'Invalid role'})

    if role == 'spectators':
        # Dev-only: when control plane is used but dev mode is off, no dev token — OIDC required.
        if API_ADAPTER_AVAILABLE and not API_DEV_MODE:
            return jsonify(
                {
                    'success': False,
                    'message': 'Login via OIDC (Keycloak); dev token is disabled. Set CONTROL_PLANE_DEV_MODE=true for local setup only.',
                }
            ), 501
        session['user_role'] = 'spectators'
        session['user_id'] = None
        session['_validity'] = SESSION_VALIDITY_TOKEN  # so this session is accepted until server restarts
        session.permanent = False  # Never persist spectator so login page is shown again after browser close
        if API_ADAPTER_AVAILABLE and API_DEV_MODE and API_DEV_TOKEN:
            session['api_token'] = 'dev:spectator'  # noqa: S105  dev-mode sentinel value, not a credential
        _login_debug('  -> set session user_role=spectators _validity=token permanent=False -> 200 success')
        _page_load_debug('login OK role=spectators -> redirect to dashboard')
        return jsonify({'success': True, 'role': 'spectators'})

    user_id = (data.get('id') or '').strip()
    password = data.get('password') or ''
    if not user_id or not password:
        return jsonify({'success': False, 'message': 'Login ID and password are required'})

    if not DASHBOARD_AVAILABLE:
        return jsonify({'success': False, 'message': 'User data not available'})
    users_data = _load_json(USERS_DATA_PATH, {'admins': [], 'operators': [], 'ai_operators': [], 'spectators': []})
    role_key = 'operators' if role == 'operators' else 'admins'
    users_list = users_data.get(role_key) or []
    user = next((u for u in users_list if (u.get('id') or '').strip().lower() == user_id.lower()), None)
    if not user or not _check_password(user, password, users_data=users_data, users_path=USERS_DATA_PATH):
        _login_debug('  -> 400 Invalid ID or password')
        return jsonify({'success': False, 'message': 'Invalid ID or password'})

    # Dev-only: when control plane is used but dev mode is off, require OIDC — do not set dev token.
    if API_ADAPTER_AVAILABLE and not API_DEV_MODE:
        return jsonify(
            {
                'success': False,
                'message': 'Login via OIDC (Keycloak); dev token is disabled. Set CONTROL_PLANE_DEV_MODE=true for local setup only.',
            }
        ), 501

    session['user_role'] = role
    session['user_id'] = user.get('id')
    session['user_name'] = user.get('name') or user.get('id') or user_id
    session['_validity'] = SESSION_VALIDITY_TOKEN  # invalidate this session when server restarts
    if API_ADAPTER_AVAILABLE and API_DEV_MODE and API_DEV_TOKEN:
        session['api_token'] = (
            f'dev:{user.get("id") or user_id}:{role.rstrip("s")}'  # operators -> operator, admins -> admin
        )
    if data.get('remember'):
        session.permanent = True
    _login_debug(
        f'  -> set session user_role={role!r} user_id={user.get("id")!r} permanent={data.get("remember")} -> 200 success'
    )
    _page_load_debug(f'login OK role={role!r} user_id={user.get("id")!r} -> redirect to dashboard')
    return jsonify({'success': True, 'role': role, 'user_id': user.get('id') or user_id})


def _logout_clear_cookie(response):
    """Remove the session cookie from the browser so next visit (e.g. after launcher restart) shows login."""
    cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    response.delete_cookie(cookie_name, path='/')
    return response


@bp.route('/logout')
def logout_page():
    """Clear session and redirect to login (GET so logout works via link or redirect)."""
    _page_load_debug('logout: clearing session (GET /logout)')
    session.clear()
    response = redirect(url_for('login_page'))
    return _logout_clear_cookie(response)


@bp.route('/api/logout', methods=['POST'])
def api_logout():
    """Clear session and log out (for JS fetch)."""
    _page_load_debug('logout: clearing session (POST /api/logout)')
    session.clear()
    response = jsonify({'success': True})
    return _logout_clear_cookie(response)


@bp.route('/api/health')
def api_health():
    """Liveness probe — public, no auth (used by restart button polling)."""
    return jsonify({'ok': True})


@bp.route('/api/restart', methods=['POST'])
def api_restart():
    """Restart Flask + Zero Public via restart_flask.sh (halt jobs, free stale :5001)."""
    if not session.get('user_role'):
        return jsonify({'error': 'Unauthorized'}), 401
    import subprocess as _sub_rs
    import os as _os_rs
    import threading as _thr_rs

    from zyg_workflows.bin import exe

    _script = _os_rs.path.join(_os_rs.path.dirname(_os_rs.path.abspath(__file__)), 'restart_flask.sh')

    def _do_restart():
        import time as _t

        _t.sleep(0.5)
        _restart_log = _os_rs.path.join(
            _os_rs.path.dirname(_script),
            'data',
            'runtime',
            'restart.log',
        )
        try:
            # Write the header line only; DO NOT pass this handle to Popen.
            # restart_flask.sh uses `tee -a "$RESTART_LOG"` for its own logging —
            # if we also redirect Popen stdout to the same file, every line is doubled.
            with open(_restart_log, 'a', encoding='utf-8') as _log_f:
                _log_f.write(
                    f'\n[{_t.strftime("%Y-%m-%dT%H:%M:%S")}] api_restart spawned restart_flask.sh\n',
                )
        except OSError as _exc:
            _zyg_log.debug('restart log header write skipped: %s', _exc)
        # stdout/stderr go to DEVNULL — the script logs itself via tee
        _sub_rs.Popen(
            [exe('bash'), _script],
            close_fds=True,
            cwd=_os_rs.path.dirname(_script),
            stdout=_sub_rs.DEVNULL,
            stderr=_sub_rs.DEVNULL,
            start_new_session=True,
        )

    _thr_rs.Thread(target=_do_restart, daemon=True).start()
    return jsonify(
        {
            'ok': True,
            'message': 'Restarting dashboard, Zero Public, and halting active pipelines…',
        }
    )


@bp.route('/api/dashboard/my_account')
def dashboard_my_account_get():
    """Get current operator's account (operators only)."""
    if session.get('user_role') != 'operators' or not session.get('user_id'):
        return jsonify({'error': 'For operators only'}), 403
    if not DASHBOARD_AVAILABLE:
        return jsonify({})
    data = _load_json(USERS_DATA_PATH, {'admins': [], 'operators': [], 'ai_operators': [], 'spectators': []})
    uid = session.get('user_id')
    users_list = data.get('operators') or []
    user = next((u for u in users_list if (u.get('id') or '') == uid), None)
    if not user:
        return jsonify({})
    out = {
        'name': user.get('name'),
        'id': user.get('id'),
        'email': user.get('email') or '',
        'phone': user.get('phone') or '',
        'login_method': user.get('login_method') or 'id_password',
        'devices': user.get('devices') or '',
    }
    return jsonify(out)


@bp.route('/api/dashboard/my_account', methods=['POST'])
def dashboard_my_account_save():
    # No disk write: account data is owned by control plane.
    return jsonify({'success': False, 'message': 'Account updates via control plane.'}), 501


@bp.route('/api/csrf-token')
def api_csrf_token():
    """GET CSRF token for pages that don't have it in meta (e.g. gpu_schedule, cpu_schedule). Requires session."""
    _ensure_csrf_token()
    return jsonify({'csrf_token': session.get('_csrf_token', '')})
