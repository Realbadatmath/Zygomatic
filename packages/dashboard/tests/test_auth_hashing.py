# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_auth password storage — salted hashing and the upgrade-on-login path.

Pinned here (2026-10-05): `password_hash` used to be an unsalted sha256 digest and
`passwords` / `password` could hold plaintext. Both are now read once and rewritten
as a salted werkzeug hash on the next successful login, and the plaintext field is
removed from the stored record.

bp_auth imports the dashboard's module globals from crewai_web_gui, which pulls in
the whole Flask application (crewai, matplotlib, a secret key, ...). The module
boundary is stubbed below so these four functions can be unit-tested on their own.
Every file this test touches is under pytest's tmp_path — never the real
dashboard_users.json.
"""

import hashlib
import hmac
import json
import os
import sys
import types

import pytest
from flask import Flask

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


_SAVED_MODULES = {}


def _install_main_module_stub():
    """Stand in for zyg_dashboard.crewai_web_gui with the names bp_auth imports."""
    import zyg_dashboard

    for name in ('zyg_dashboard.crewai_web_gui', 'zyg_dashboard.bp_auth'):
        _SAVED_MODULES[name] = sys.modules.get(name)

    stub = types.ModuleType('zyg_dashboard.crewai_web_gui')
    stub.SESSION_VALIDITY_TOKEN = 'test-validity-token'  # noqa: S105  test fixture, not a credential
    stub.USERS_DATA_PATH = None  # the tests pass the path explicitly
    stub.DASHBOARD_AVAILABLE = False
    stub.API_ADAPTER_AVAILABLE = False
    stub.API_DEV_MODE = False
    stub.API_DEV_TOKEN = None
    stub.app = Flask(__name__)
    stub.hashlib = hashlib
    stub.hmac = hmac
    stub.limiter = types.SimpleNamespace(limit=lambda *a, **k: lambda fn: fn, exempt=lambda fn: fn)
    stub.get_remote_address = lambda: '127.0.0.1'
    stub.url_for = lambda *a, **k: '/login'
    stub._ensure_csrf_token = lambda: None
    stub._login_debug = lambda *a, **k: None
    stub._page_load_debug = lambda *a, **k: None

    def _load_json(path, default):
        if not os.path.exists(path):
            return default
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)

    def _save_json(path, data):
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        return True

    stub._load_json = _load_json
    stub._save_json = _save_json
    sys.modules['zyg_dashboard.crewai_web_gui'] = stub
    zyg_dashboard.crewai_web_gui = stub


def _restore_main_module():
    """Drop the stub again so no later test imports it as the dashboard.

    bp_auth binds every name it needs from crewai_web_gui at import time, so the
    module object this file already holds keeps working without the stub, while a
    later importer (tests/api, which drives the real Flask app) gets a freshly
    wired real crewai_web_gui/bp_auth pair instead of a bare keyless Flask app.
    """
    import zyg_dashboard

    for name, previous in _SAVED_MODULES.items():
        attr = name.rpartition('.')[2]
        if previous is None:
            sys.modules.pop(name, None)
            if attr in vars(zyg_dashboard):
                delattr(zyg_dashboard, attr)
        else:
            sys.modules[name] = previous
            setattr(zyg_dashboard, attr, previous)


_install_main_module_stub()

from zyg_dashboard import bp_auth  # noqa: E402  needs the stub above in sys.modules

_restore_main_module()


@pytest.fixture
def users_file(tmp_path):
    """A throwaway dashboard_users.json; the production file is never opened."""
    return tmp_path / 'dashboard_users.json'


def _write(users_file, user):
    data = {'admins': [user], 'operators': [], 'ai_operators': [], 'spectators': []}
    users_file.write_text(json.dumps(data), encoding='utf-8')
    return data


def test_hash_is_salted_and_not_the_password():
    first = bp_auth._hash_password('correct horse battery staple')
    second = bp_auth._hash_password('correct horse battery staple')
    assert first != second, 'two hashes of one password must differ — otherwise there is no salt'
    assert 'correct horse battery staple' not in first
    assert not bp_auth._LEGACY_SHA256_RE.match(first)
    assert bp_auth._check_password({'password_hash': first}, 'correct horse battery staple')
    assert bp_auth._check_password({'password_hash': second}, 'correct horse battery staple')


def test_wrong_password_is_refused():
    user = {'id': 'ada', 'password_hash': bp_auth._hash_password('lovelace')}
    assert not bp_auth._check_password(user, 'Lovelace')
    assert not bp_auth._check_password(user, '')
    assert not bp_auth._check_password(user, 'lovelace ')
    assert not bp_auth._check_password({'id': 'nobody'}, 'anything')


def test_legacy_sha256_hash_verifies_then_upgrades(users_file):
    legacy = hashlib.sha256(b'hunter2').hexdigest()
    user = {'id': 'ada', 'password_hash': legacy}
    data = _write(users_file, user)

    assert not bp_auth._check_password(user, 'hunter3', users_data=data, users_path=str(users_file))
    assert user['password_hash'] == legacy, 'a failed login must not rewrite the record'

    assert bp_auth._check_password(user, 'hunter2', users_data=data, users_path=str(users_file))
    assert user['password_hash'] != legacy
    assert not bp_auth._LEGACY_SHA256_RE.match(user['password_hash'])

    stored = json.loads(users_file.read_text(encoding='utf-8'))['admins'][0]
    assert stored['password_hash'] == user['password_hash'], 'the upgrade must be persisted'
    # The upgraded record still authenticates, and the old digest no longer does.
    assert bp_auth._check_password(stored, 'hunter2')
    assert not bp_auth._check_password(stored, legacy)


def test_legacy_plaintext_fields_verify_then_are_removed(users_file):
    user = {'id': 'ada', 'passwords': ['hunter2', 'olderone'], 'password': 'hunter2'}
    data = _write(users_file, user)

    assert not bp_auth._check_password(user, 'nope', users_data=data, users_path=str(users_file))
    assert user['passwords'] == ['hunter2', 'olderone'], 'a failed login must not rewrite the record'

    assert bp_auth._check_password(user, 'olderone', users_data=data, users_path=str(users_file))
    assert 'passwords' not in user and 'password' not in user
    assert bp_auth._check_password(user, 'olderone')

    stored = json.loads(users_file.read_text(encoding='utf-8'))['admins'][0]
    assert 'passwords' not in stored and 'password' not in stored, 'plaintext must not survive on disk'
    assert bp_auth._check_password(stored, 'olderone')


def test_upgrade_without_a_path_touches_no_file(users_file):
    user = {'id': 'ada', 'password_hash': hashlib.sha256(b'hunter2').hexdigest()}
    assert bp_auth._check_password(user, 'hunter2')
    assert not bp_auth._LEGACY_SHA256_RE.match(user['password_hash'])
    assert not users_file.exists()
