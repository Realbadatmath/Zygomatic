# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proves the in-process harness itself: import, auth gate, CSRF, limiter.

The "no watcher thread survived" half of the proof is the ``dash_app``
fixture's teardown assertion, which runs after every test in the session.
"""

import pytest

pytestmark = [pytest.mark.api, pytest.mark.timeout(60)]


def test_health_is_open_to_anonymous(dash):
    r = dash.get('/api/health')
    assert r.status_code == 200, r.data[:200]


def test_metrics_summary_anonymous_is_401(dash):
    r = dash.get('/api/metrics/summary')
    assert r.status_code == 401, r.data[:200]


def test_metrics_summary_admin_is_200(dash_admin):
    r = dash_admin.get('/api/metrics/summary')
    assert r.status_code == 200, r.data[:200]


def test_body_method_without_csrf_is_403(dash_admin):
    r = dash_admin.post('/api/zero/chat', json={})
    assert r.status_code == 403, r.data[:200]


def test_body_method_with_csrf_reaches_handler(dash_admin):
    r = dash_admin.post('/api/zero/chat', json={}, headers=dash_admin.csrf)
    assert r.status_code == 400, r.data[:200]


def test_limiter_is_off_for_210_requests(dash_admin):
    codes = {dash_admin.get('/api/metrics/summary').status_code for _ in range(210)}
    assert codes == {200}, codes
