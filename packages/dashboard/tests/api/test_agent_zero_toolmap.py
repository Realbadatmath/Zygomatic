# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-process route tests for the Agent Zero v2 tool map.

The claim these tests exist to prove: a tool call is made **as the person talking to
Agent Zero**. ``toolmap_exec`` dispatches through the live app's ``test_client`` with the
caller's own session cookie, so the dashboard's own gates decide the answer -- a
login-gated route answers 401 when the cookie is missing, and the same route answers
with data when the admin session is passed in. There is no internal bypass.

The session cookie is read with ``client.get_cookie('session').value`` (werkzeug 3.1.6 /
flask 3.1.3 on this box; ``get_cookie`` returns a ``Cookie`` dataclass whose ``value`` is
the signed session string). The older ``client.cookie_jar`` is gone in werkzeug 3.
"""

import json

import pytest

from zyg_dashboard.agent_zero import _host, toolmap, toolmap_exec

pytestmark = [pytest.mark.api, pytest.mark.timeout(120)]


@pytest.fixture(autouse=True)
def _quiet_tool_log(tmp_path, monkeypatch):
    """Keep the executor's audit log out of the live ``data/runtime`` directory."""
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))


@pytest.fixture
def admin_cookie(dash_admin):
    cookie = dash_admin.get_cookie('session')
    assert cookie is not None, 'the admin fixture carries no session cookie'
    return cookie.value


def test_health_runs_in_process_with_the_users_session(dash_app, admin_cookie):
    out = toolmap_exec.call('system.health', {}, cookie=admin_cookie, actor='apitest')
    assert out['ok'] is True, out['text']
    assert out['status'] == 200
    assert '"ok": true' in out['text'], out['text']
    assert out['risk'] == 'read'
    assert out['needs_confirmation'] is False
    assert out['ms'] >= 0


def test_a_gated_route_is_refused_without_the_users_session(dash_app):
    """No cookie, no data: the dashboard's ``require_login`` is what authorises a tool.

    ``system.health`` itself is an *open* route (gate=open in the inventory, 200 to an
    anonymous caller on the live server), so the proof is made on a login-gated read
    tool instead.
    """
    out = toolmap_exec.call('system.pipeline_active', {}, cookie='')
    assert out['ok'] is False
    assert out['status'] == 401, out['text']


def test_the_same_gated_route_answers_with_the_session(dash_app, admin_cookie):
    out = toolmap_exec.call('system.pipeline_active', {}, cookie=admin_cookie)
    assert out['ok'] is True, out['text']
    assert out['status'] == 200


def test_zero_find_through_execute_names_the_tool(dash_app):
    out = toolmap_exec.execute('zero_find', {'query': 'telemetry'}, actor='apitest')
    assert out['ok'] is True
    assert 'system.telemetry' in out['text']
    assert '[GET /api/telemetry]' in out['text']


def test_zero_call_passes_query_parameters(dash_app, admin_cookie):
    out = toolmap_exec.execute(
        'zero_call',
        {'tool': 'system.audit_trail', 'args': {'limit': 2}},
        cookie=admin_cookie,
    )
    assert out['ok'] is True, out['text']
    assert out['text'].startswith('GET /api/zero/audit-trail -> 200')


def test_a_path_parameter_is_substituted(dash_app, admin_cookie):
    out = toolmap_exec.call('system.metrics_hub', {'section': 'system'}, cookie=admin_cookie)
    assert '/api/metrics/hub/system ->' in out['text'], out['text']


def test_a_missing_path_parameter_is_reported_not_requested(dash_app, admin_cookie):
    out = toolmap_exec.call('system.metrics_hub', {}, cookie=admin_cookie)
    assert out['ok'] is False
    assert 'needs path parameter(s): section' in out['text']


def test_a_danger_tool_is_never_dispatched_without_confirmation(dash_app, admin_cookie):
    """The live pipelines must still be running after this test: nothing was called."""
    out = toolmap_exec.call('zero.stop', {}, cookie=admin_cookie)
    assert out['ok'] is False
    assert out['needs_confirmation'] is True
    assert out['confirm_id']
    assert 'CONFIRMATION REQUIRED' in out['text']
    assert 'status' not in out, 'a danger tool must not reach the route at all'
    toolmap_exec.PENDING.pop(out['confirm_id'], None)


def test_the_runtime_url_map_adds_auto_tools_but_not_to_the_index(dash_app):
    """With the host loaded, the uncurated tail is findable -- and still not advertised."""
    curated_count = sum(len(group['tools']) for group in toolmap.groups())
    full = toolmap.catalog()
    autos = [tool for tool in full if not tool['curated']]
    assert len(full) > curated_count, 'the live url_map added no auto tools'
    assert autos, 'no auto tool was derived from the url_map'
    index = toolmap.index_text()
    for tool in autos[:25]:
        assert tool['id'] not in index, f'{tool["id"]} leaked into the index'
    assert all(tool['id'].startswith('auto.') for tool in autos)
    assert all(tool['risk'] in ('read', 'act', 'danger') for tool in autos)


def test_an_auto_tool_is_reachable_through_find_and_runs(dash_app, admin_cookie):
    hits = toolmap.find('pipeline_stages')
    assert hits and hits[0]['kind'] == 'http'
    out = toolmap_exec.call(hits[0]['id'], {}, cookie=admin_cookie)
    assert out['status'] in (200, 403, 404, 500), out['text']


def test_executions_land_in_the_tool_log(dash_app, admin_cookie):
    toolmap_exec.call('system.health', {}, cookie=admin_cookie, actor='apitest')
    with open(toolmap_exec.log_path(), encoding='utf-8') as fh:
        rows = [json.loads(line) for line in fh]
    assert rows, 'nothing was logged'
    assert rows[-1]['tool'] == 'system.health'
    assert rows[-1]['status'] == 200
    assert rows[-1]['actor'] == 'apitest'
