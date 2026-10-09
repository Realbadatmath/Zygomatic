# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The blueprint must register on a bare Flask app, with no dashboard present.

That is the whole point of the decoupling: ``runtime.limiter`` is None outside the
GUI, so ``_limit()`` has to fall back to a no-op instead of raising, and the state
directory has to be resolved from ZYG_DATA_ROOT at call time rather than imported
from the dashboard.
"""

import json

import pytest
from flask import Flask
from zyg_workflows import runtime

from zyg_nexus.bp_creator_nexus import bp


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'limiter', None)
    monkeypatch.setattr(runtime, 'runtime_dir', lambda: str(tmp_path / 'runtime'))
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


@pytest.mark.api
def test_get_state_on_bare_app(client):
    """GET answers with an empty, well-formed store and no wildcard CORS grant."""
    resp = client.get('/api/creator-nexus/state')
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body['success'] is True
    assert body['exists'] is False
    assert body['keys'] == {}
    assert resp.headers.get('Access-Control-Allow-Origin') is None
    assert resp.headers['Cache-Control'] == 'no-store'


@pytest.mark.api
def test_cors_origin_only_from_allowlist(client, monkeypatch):
    monkeypatch.setenv('ZYG_CORS_ORIGINS', 'http://nexus.example:8090')
    allowed = client.get('/api/creator-nexus/state', headers={'Origin': 'http://nexus.example:8090'})
    assert allowed.headers['Access-Control-Allow-Origin'] == 'http://nexus.example:8090'
    denied = client.get('/api/creator-nexus/state', headers={'Origin': 'http://evil.example'})
    assert denied.headers.get('Access-Control-Allow-Origin') is None
