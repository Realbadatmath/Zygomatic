# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Body-method (POST/PUT/DELETE/PATCH) tests for the dashboard, by risk class.

WHY THIS IS NOT A SWEEP
-----------------------
The dashboard has 166 body-method rules. Calling them is not like calling a GET:
a handler that runs writes the operator's real state under ``data/runtime``,
starts a pipeline, trains, approves or deletes. There is no test data root. So
this module never asks "what does this route do" — it asks the three questions
that can be answered without letting a handler act:

1. **GATE** — does ``require_login`` (crewai_web_gui.py:410-560) answer *before*
   the handler? An anonymous request from a non-localhost address must get a 401
   on every ``/api/*`` body route that is not in the no-login allowlist. This is
   the one assertion that is safe for *every* gated route, including the ones
   classified ``exclude``: the 401 proves the handler was never entered.
   ``gate == 'localhost'`` routes are requested the same way — the localhost
   bypass must not apply to 10.0.0.9, so they too must answer 401. Routes with
   ``gate == 'open'`` are *not* requested at all: for them the gate is designed
   to let the request through, so the handler would run.

2. **CSRF** — ``_require_csrf`` (crewai_web_gui.py:391-407) rejects a body method
   on ``/api/*`` without a matching ``X-CSRF-Token``. Measured ordering: login
   first, CSRF second, handler last. Only ``safe``/``validate`` routes are used
   here, so that a future reordering which lets the request reach a handler
   cannot start anything destructive.

3. **VALIDATE** — a ``validate`` route is one whose handler was read top-down and
   provably rejects an empty JSON body with a 4xx *before* any write, subprocess,
   thread or network call. Those are the only routes this module is allowed to
   actually execute with a session, and the assertion is that the rejection still
   happens: a 2xx means the handler accepted ``{}`` and did whatever it does, a
   5xx means it crashed on the empty body instead of validating it. Both are
   findings for the operator and are written to
   ``apitests/reports/findings_post_dashboard.md`` — they are NOT reclassified to
   make the suite green.

``safe`` routes (no write and no external call, verified by reading the handler)
are executed with a session too, and asserted only not to 5xx.

``exclude`` routes are never executed with a session. They appear in group 1
(anonymous 401) and in one summary test that pins their count and lists them, so
that a route silently leaving the exclude set is visible as a count change.

The risk classes come from ``apitests/routes.json`` (fields ``risk``,
``empty_body_status``, ``why``), merged in by ``apitests/merge_classify.py``.
"""

import json
import re
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

BODY_METHODS = ('DELETE', 'PATCH', 'POST', 'PUT')

# A handler that crashed, as opposed to one that answered. 501 (control-plane
# migration stub) and 503 (service state) are deliberate replies on this
# dashboard and are not failures.
CRASH_STATUSES = (500, 502)

CREWS_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = CREWS_DIR / 'apitests' / 'reports'
FINDINGS_MD = REPORTS_DIR / 'findings_post_dashboard.md'

# Placeholder per Werkzeug converter: syntactically valid for the converter but
# naming an object that cannot exist, so a handler that does reach its lookup
# takes the not-found branch instead of touching real data.
CONVERTER_VALUES = {
    'int': '1',
    'float': '1.0',
    'uuid': '00000000-0000-4000-8000-000000000000',
    'path': '__apitest__',
    'string': '__apitest__',
    'any': '__apitest__',
    'default': '__apitest__',
}

_PARAM_RE = re.compile(r'<([^>]+)>')


def _fill(rule):
    def sub(match):
        inner = match.group(1)
        conv = inner.split(':', 1)[0] if ':' in inner else 'default'
        conv = conv.split('(', 1)[0]
        return CONVERTER_VALUES.get(conv, '__apitest__')

    return _PARAM_RE.sub(sub, rule)


def _first_body_method(route):
    for method in BODY_METHODS:
        if method in route['methods']:
            return method
    raise AssertionError(f'{route["rule"]} has no body method: {route["methods"]}')


def _load_routes():
    """Read the inventory at collection time (fixtures do not exist yet).

    Every test still requests the ``routes`` fixture, so a missing inventory
    produces that fixture's skip reason instead of a silent zero-test run.
    """
    return json.loads((CREWS_DIR / 'apitests' / 'routes.json').read_text())


try:
    _ROUTES = _load_routes()
except Exception:  # inventory missing/unreadable: the `routes` fixture skips
    _ROUTES = {'apps': {'dashboard': []}}

_BODY = [r for r in _ROUTES['apps']['dashboard'] if set(BODY_METHODS) & set(r['methods'])]

_GATED = [r for r in _BODY if r['gate'] != 'open']
_VALIDATE = [r for r in _BODY if r['risk'] == 'validate']
_SAFE = [r for r in _BODY if r['risk'] == 'safe']
_EXCLUDE = [r for r in _BODY if r['risk'] == 'exclude']
_CSRF_SET = [r for r in _BODY if r['risk'] in ('safe', 'validate') and r['gate'] == 'login']


def _ids(rules):
    return [f'{_first_body_method(r)} {r["rule"]}' for r in rules]


_ROWS = {'gate': [], 'csrf': [], 'validate': [], 'safe': []}
_FINDINGS = []
_REPORT = []


@pytest.fixture(autouse=True)
def _capture_report(report):
    if not _REPORT:
        _REPORT.append(report)
    yield


@pytest.fixture(scope='module', autouse=True)
def _write_report():
    yield
    if not _REPORT:
        return

    def _status_counts(rows):
        counts = {}
        for row in rows:
            counts[str(row['status'])] = counts.get(str(row['status']), 0) + 1
        return dict(sorted(counts.items()))

    _REPORT[0](
        'post_dashboard',
        {
            'summary': {
                'body_routes': len(_BODY),
                'by_risk': {
                    'safe': len(_SAFE),
                    'validate': len(_VALIDATE),
                    'exclude': len(_EXCLUDE),
                },
                'by_gate': {g: sum(1 for r in _BODY if r['gate'] == g) for g in sorted({r['gate'] for r in _BODY})},
                'by_group': {
                    'gate_requested': len(_GATED),
                    'gate_not_requested_open': len(_BODY) - len(_GATED),
                    'csrf_requested': len(_CSRF_SET),
                    'validate_requested': len(_VALIDATE),
                    'safe_requested': len(_SAFE),
                },
                'by_group_statuses': {name: _status_counts(rows) for name, rows in _ROWS.items()},
                'findings': len(_FINDINGS),
            },
            'exclude_never_executed': sorted(
                [
                    {
                        'rule': r['rule'],
                        'method': _first_body_method(r),
                        'endpoint': r['endpoint'],
                        'func': r['func'],
                        'gate': r['gate'],
                        'why': r.get('why', ''),
                    }
                    for r in _EXCLUDE
                ],
                key=lambda r: r['rule'],
            ),
            'validate_results': sorted(_ROWS['validate'], key=lambda r: r['rule']),
            'safe_results': sorted(_ROWS['safe'], key=lambda r: r['rule']),
            'gate_results': sorted(_ROWS['gate'], key=lambda r: r['rule']),
            'csrf_results': sorted(_ROWS['csrf'], key=lambda r: r['rule']),
        },
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        '# Findings: dashboard body-method routes vs an empty JSON body',
        '',
        'Generated by `tests/api/test_post_dashboard.py` (group 3: admin session + CSRF, `json={}`).',
        '',
        'A `validate` route is one whose handler was read and found to reject an '
        'empty body with a 4xx before any side effect. A route listed below did '
        'not: it either crashed (5xx) or accepted the empty body (2xx). Neither '
        'is fixed by reclassifying the route.',
        '',
    ]
    if not _FINDINGS:
        lines.append('**No findings.** Every `validate` route rejected `{}` with a 4xx.')
    else:
        lines.append(f'**{len(_FINDINGS)} finding(s).**')
        lines.append('')
        for f in sorted(_FINDINGS, key=lambda r: r['rule']):
            lines += [
                f'## `{f["method"]} {f["rule"]}` → {f["status"]} (expected {f["expected"]})',
                '',
                f'* endpoint: `{f["endpoint"]}` at `{f["func"]}`',
                f'* kind: {f["kind"]}',
                f'* classified because: {f["why"]}',
                '',
                '```',
                f['body'].strip()[:1200],
                '```',
                '',
            ]
    FINDINGS_MD.write_text('\n'.join(lines) + '\n')


def _record(group, route, method, url, resp, started, **extra):
    row = {
        'rule': route['rule'],
        'url': url,
        'method': method,
        'endpoint': route['endpoint'],
        'func': route['func'],
        'gate': route['gate'],
        'risk': route['risk'],
        'status': resp.status_code,
        'ms': round((time.perf_counter() - started) * 1000, 1),
    }
    row.update(extra)
    _ROWS[group].append(row)
    return row


@pytest.mark.parametrize('route', _GATED, ids=_ids(_GATED))
def test_gate_rejects_anonymous_body_request(dash_remote, routes, route):
    """Anonymous, non-localhost: the login gate must answer 401, not the handler.

    This is the only assertion made about ``exclude`` routes, and it is the
    reason it can be made about them: a 401 proves the handler never ran.
    """
    method = _first_body_method(route)
    url = _fill(route['rule'])
    started = time.perf_counter()
    resp = dash_remote.open(url, method=method, json={})
    _record('gate', route, method, url, resp, started)
    assert resp.status_code == 401, (
        f'{method} {url} from 10.0.0.9 without a session answered '
        f'{resp.status_code}, expected 401 from require_login '
        f'(gate={route["gate"]}, risk={route["risk"]}, '
        f'{route["endpoint"]} at {route["func"]}); '
        f'body starts: {resp.get_data(as_text=True)[:300]!r}'
    )


@pytest.mark.parametrize('route', _CSRF_SET, ids=_ids(_CSRF_SET))
def test_csrf_rejects_missing_token(dash_admin, routes, route):
    """An admin session without ``X-CSRF-Token`` must get 403 before the handler."""
    method = _first_body_method(route)
    url = _fill(route['rule'])
    started = time.perf_counter()
    resp = dash_admin.open(url, method=method, json={})
    _record('csrf', route, method, url, resp, started)
    assert resp.status_code == 403, (
        f'{method} {url} with an admin session but NO CSRF header answered '
        f'{resp.status_code}, expected 403 from _require_csrf '
        f'({route["endpoint"]} at {route["func"]}); '
        f'body starts: {resp.get_data(as_text=True)[:300]!r}'
    )


@pytest.mark.parametrize('route', _VALIDATE, ids=_ids(_VALIDATE))
def test_validate_route_rejects_empty_body(dash_admin, routes, route):
    """An empty JSON body must be rejected with a 4xx, as the classification claims."""
    method = _first_body_method(route)
    url = _fill(route['rule'])
    expected = route['empty_body_status']
    started = time.perf_counter()
    resp = dash_admin.open(url, method=method, json={}, headers=dash_admin.csrf)
    body = resp.get_data(as_text=True)
    row = _record(
        'validate',
        route,
        method,
        url,
        resp,
        started,
        expected=expected,
        matched_expected=(expected is not None and resp.status_code == expected),
        body_head=body[:300],
    )

    status = resp.status_code
    kind = None
    if status >= 500:
        kind = '5xx: the handler crashed on the empty body instead of validating it'
    elif 200 <= status < 300:
        kind = (
            '2xx: the handler ACCEPTED an empty body and ran — the route is '
            'not safe to call with {} and must not stay classified validate'
        )
    if kind:
        _FINDINGS.append(
            {
                'rule': route['rule'],
                'method': method,
                'status': status,
                'expected': expected,
                'endpoint': route['endpoint'],
                'func': route['func'],
                'kind': kind,
                'why': route.get('why', ''),
                'body': body,
            }
        )
        row['finding'] = kind

    assert status < 500, (
        f'{method} {url} answered {status} on an empty body — a validate route '
        f'must reject it, not crash ({route["endpoint"]} at {route["func"]}). '
        f'Classified because: {route.get("why", "")!r}. '
        f'Body: {body[:900]!r}'
    )
    assert not (200 <= status < 300), (
        f'{method} {url} ACCEPTED an empty body ({status}) — the handler ran '
        f'({route["endpoint"]} at {route["func"]}). Reclassify the route to '
        f'exclude after checking what it did; do not loosen this assertion. '
        f'Classified because: {route.get("why", "")!r}. '
        f'Body: {body[:900]!r}'
    )
    # The contract is "the classification's exact status, or any 4xx": a route
    # that answers 400 where the classification predicted 404 still rejected the
    # empty body before acting, which is the property under test. The exact
    # status is kept in the report (``matched_expected``) so a drift is visible
    # without turning it into a red suite.
    assert status == expected or 400 <= status < 500, (
        f'{method} {url} answered {status} on an empty body, expected '
        f'{expected} or any 4xx ({route["endpoint"]} at {route["func"]}); '
        f'body: {body[:300]!r}'
    )


@pytest.mark.parametrize('route', _SAFE, ids=_ids(_SAFE))
def test_safe_route_does_not_crash(dash_admin, routes, route):
    """A ``safe`` route (no write, no external call) must not crash.

    "Crash" is 500/502 only, the same rule ``test_get_smoke_dashboard`` uses.
    501 and 503 are *declared* answers on this dashboard, not failures: seven of
    the routes here are stubs left behind by the control-plane migration and
    answer ``501 {"message": "... use control plane"}`` by design (measured
    2026-10-02; the classification already predicted 501 for four of them). A
    test that failed on those would be measuring the migration, not the API.
    """
    method = _first_body_method(route)
    url = _fill(route['rule'])
    started = time.perf_counter()
    resp = dash_admin.open(url, method=method, json={}, headers=dash_admin.csrf)
    body = resp.get_data(as_text=True)
    _record('safe', route, method, url, resp, started, expected=route['empty_body_status'], body_head=body[:300])
    assert resp.status_code not in CRASH_STATUSES, (
        f'{method} {url} answered {resp.status_code} ({route["endpoint"]} at {route["func"]}); body: {body[:900]!r}'
    )


def test_exclude_routes_are_never_executed(routes):
    """Pin the exclude set: 123 routes that this suite only ever calls anonymously.

    If this count moves, a route changed class — read the diff before touching
    anything else, because the new class decides whether a handler is allowed to
    run inside the test process.

    166 -> 168 body routes on 2026-10-06, when the inventory was regenerated
    after the monorepo move: /api/skill/inbound went away with the Skill VM and
    bp_jackmona_daily.py's abort / daily_mode / run_now arrived, all three
    `exclude` (121 -> 123).
    """
    assert len(_BODY) == 168, f'dashboard body-method routes: {len(_BODY)}, expected 168'
    assert len(_EXCLUDE) == 123, (
        f'exclude routes: {len(_EXCLUDE)}, expected 123; '
        f'risk counts = safe {len(_SAFE)}, validate {len(_VALIDATE)}, '
        f'exclude {len(_EXCLUDE)}'
    )
    executed = {(r['rule'], r['method']) for rows in (_ROWS['validate'], _ROWS['safe']) for r in rows}
    leaked = sorted({(r['rule'], _first_body_method(r)) for r in _EXCLUDE} & executed)
    assert not leaked, f'exclude routes were executed with a session: {leaked}'
