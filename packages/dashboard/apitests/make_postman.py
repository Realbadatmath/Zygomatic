#!/usr/bin/env python3
"""Generate the Postman collection (v2.1.0) and environment from apitests/routes.json.

Layer B of the API test layer. Layer A is pytest + Flask test_client (in-process,
tests/api/). This module turns the SAME route inventory into a collection that can
be driven by Postman interactively or by Newman headless.

Safety contract, mirrored from the inventory's ``risk`` classification:

* ``exclude`` routes (and every body-method route this inventory could not verify)
  are parked under one top-level folder whose pre-request script *throws* unless
  ``ALLOW_DANGEROUS=1``. They are never run by accident.
* ``validate`` routes may be POSTed an empty ``{}`` body: the handler was read and
  rejects it with a 4xx before any write. The test asserts the recorded status.
* ``safe`` routes and all GETs only assert "not 5xx".
* Credentials are never written to a file: ``ZYG_USER``/``ZYG_PASS`` ship empty and
  every login-gated request skips itself while they are empty, so an anonymous
  Newman run reports skips rather than a wall of 401s.

The "Health (open, no login)" folder is the only part that is safe to run live
against 127.0.0.1 without credentials — see run_newman.sh.

Usage:  ../.venv/bin/python apitests/make_postman.py
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTES = HERE / 'routes.json'
COLLECTION = HERE / 'zygomatic.postman_collection.json'
ENVIRONMENT = HERE / 'zygomatic.postman_environment.json'

SCHEMA = 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'
NS = uuid.UUID('5f1c0b8e-0000-4000-8000-7a7967706f73')  # stable ids across runs

# One base-url variable per app.
BASE_VAR = {
    'dashboard': 'dash_url',
    'zero_public': 'zpub_url',
    'medusa': 'medusa_url',
}
BASE_URL = {
    'dash_url': 'http://127.0.0.1:5000',
    'zpub_url': 'http://127.0.0.1:5001',
    'medusa_url': 'http://127.0.0.1:5300',
}
APP_ORDER = ['dashboard', 'zero_public', 'medusa']  # skill_proxy retired 2026-10-05

HEALTH_FOLDER = 'Health (open, no login)'
EXCLUDED_FOLDER = 'EXCLUDED — side effects (never run blind)'

BODY_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')

# Placeholder per Werkzeug converter — identical to tests/api/test_get_smoke_dashboard.py
# (task 3): syntactically valid for the converter, naming an object that cannot
# exist, so the handler takes its not-found branch instead of touching real data.
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

# Routes outside the dashboard that belong in the health folder.
EXTRA_HEALTH = {('medusa', '/', 'GET')}

# GETs that write and are not caught by the inventory's danger regex. Same list
# as tests/api/test_medusa.py GET_EXCLUDE — a GET that writes is an `exclude`.
HAND_EXCLUDED = {
    ('medusa', '/api/vicky/chat', 'GET'): 'medusa_vicky.open_chat() rewrites data/runtime/vicky/current.json and '
    'mints a chat file when the store is empty — a GET that writes',
}

SKIP_WITHOUT_LOGIN = [
    '// No credentials configured: skip rather than collect a wall of 401s.',
    "if (!pm.environment.get('ZYG_USER')) {",
    '    pm.execution.skipRequest();',
    '}',
]

# MEASURED 2026-10-02 with newman 6.2.2: a bare `throw` in a pre-request script
# does NOT stop the send — newman logs "Error in prerequest-script" and dispatches
# the request anyway (4 POSTs to /api/safety/* went out and were only stopped by
# the dashboard's 401 login gate). pm.execution.skipRequest() DOES stop it
# (verified: 2 pre-request scripts executed, 0 requests sent). So skip first, then
# throw, so the run is also marked failed and the operator sees why.
DANGEROUS_GUARD = [
    '// This route has side effects the inventory could not prove away.',
    "if (pm.environment.get('ALLOW_DANGEROUS') !== '1') {",
    "    console.error('BLOCKED ' + pm.info.requestName +",
    "                  ': set ALLOW_DANGEROUS=1 to run this');",
    '    pm.execution.skipRequest();  // must come first: throw alone does not',
    '                                 // stop newman from sending the request',
    "    throw new Error('set ALLOW_DANGEROUS=1 to run this');",
    '}',
]

NOT_5XX = [
    "pm.test('not 5xx', () => pm.expect(pm.response.code).to.be.below(500));",
]


def _id(*parts: str) -> str:
    return str(uuid.uuid5(NS, '|'.join(parts)))


def _script(kind: str, exec_lines: list[str]) -> dict:
    return {
        'listen': kind,
        'script': {'type': 'text/javascript', 'exec': exec_lines},
    }


def _param_name(inner: str) -> tuple[str, str]:
    """``int:job_id`` -> ('job_id', 'int'); ``name`` -> ('name', 'default')."""
    if ':' in inner:
        converter, name = inner.rsplit(':', 1)
        converter = converter.split('(', 1)[0]
    else:
        converter, name = 'default', inner
    return name, converter


def _url(base_var: str, rule: str, params: dict[str, str]) -> dict:
    """Postman url object; ``<converter:name>`` becomes a ``{{name}}`` variable."""

    def sub(match):
        name, converter = _param_name(match.group(1))
        params.setdefault(name, CONVERTER_VALUES.get(converter, '__apitest__'))
        return '{{%s}}' % name

    path = _PARAM_RE.sub(sub, rule)
    raw = '{{%s}}%s' % (base_var, path)
    return {
        'raw': raw,
        'host': ['{{%s}}' % base_var],
        'path': [seg for seg in path.split('/') if seg],
    }


def classify(route: dict, method: str, app: str) -> str:
    """Which top-level folder a (route, method) pair belongs to.

    health    — open, no login, GET, no side effect: the one live-runnable set.
    excluded  — risk 'exclude', any unverified body method, any danger/external GET.
    validate  — an empty {} body is rejected with a 4xx before any write.
    safe      — verified idempotent body method.
    get       — everything else (plain reads).
    """
    rule, risk = route['rule'], route.get('risk')
    if (app, rule, method) in HAND_EXCLUDED:
        return 'excluded'
    if (app, rule, method) in EXTRA_HEALTH:
        return 'health'
    if (
        app == 'dashboard'
        and route['gate'] == 'open'
        and method == 'GET'
        and not route['danger']
        and not route['external']
    ):
        return 'health'
    if method in BODY_METHODS:
        # Unclassified body methods (the three non-dashboard apps) are excluded:
        # "could not verify" is the same risk class as "has side effects".
        return risk if risk in ('validate', 'safe') else 'excluded'
    if risk == 'exclude' or route['danger'] or route['external']:
        return 'excluded'
    return 'get'


def make_request(route: dict, method: str, app: str, kind: str, params: dict[str, str]) -> dict:
    base_var = BASE_VAR[app]
    name = '%s %s' % (method, route['rule'])
    headers = []
    body = None
    pre: list[str] = []
    test = list(NOT_5XX)

    if kind == 'excluded':
        pre += DANGEROUS_GUARD
    if app == 'dashboard' and route['gate'] == 'login':
        if pre:
            pre.append('')
        pre += SKIP_WITHOUT_LOGIN

    if method in BODY_METHODS:
        headers.append({'key': 'Content-Type', 'value': 'application/json'})
        headers.append({'key': 'X-CSRF-Token', 'value': '{{csrf_token}}'})
        body = {'mode': 'raw', 'raw': '{}', 'options': {'raw': {'language': 'json'}}}
        if kind == 'validate':
            want = route.get('empty_body_status')
            test = [
                "pm.test('empty body rejected with %s', () => pm.expect(pm.response.code).to.eql(%s));" % (want, want),
            ]

    event = []
    if pre:
        event.append(_script('prerequest', pre))
    event.append(_script('test', test))

    why = route.get('why') or HAND_EXCLUDED.get((app, route['rule'], method))
    item = {
        'name': name,
        'id': _id(app, route['rule'], method),
        'event': event,
        'request': {
            'method': method,
            'header': headers,
            'url': _url(base_var, route['rule'], params),
            'description': 'endpoint %s · %s · gate %s · risk %s%s'
            % (route['endpoint'], route['func'], route['gate'], route.get('risk') or '-', ' · ' + why if why else ''),
        },
    }
    if body:
        item['request']['body'] = body
    return item


def login_helpers() -> list[dict]:
    """POST /api/login then GET /api/csrf-token, storing the token in the env."""
    login_body = json.dumps({'role': 'admins', 'id': '{{ZYG_USER}}', 'password': '{{ZYG_PASS}}'}, indent=2)
    login = {
        'name': 'Login (sets the session cookie)',
        'id': _id('helper', 'login'),
        'event': [
            _script('prerequest', SKIP_WITHOUT_LOGIN),
            _script(
                'test',
                [
                    "pm.test('login answered', () => pm.expect(pm.response.code).to.be.below(500));",
                    "pm.test('login succeeded', () => "
                    "pm.expect(pm.response.json().success, 'check ZYG_USER/ZYG_PASS')"
                    '.to.be.true);',
                ],
            ),
        ],
        'request': {
            'method': 'POST',
            'header': [{'key': 'Content-Type', 'value': 'application/json'}],
            'body': {'mode': 'raw', 'raw': login_body, 'options': {'raw': {'language': 'json'}}},
            'url': _url('dash_url', '/api/login', {}),
            'description': 'CSRF-exempt. Fill ZYG_USER/ZYG_PASS in Postman; they are '
            'empty on disk by design and this request skips itself '
            'while ZYG_USER is empty.',
        },
    }
    csrf = {
        'name': 'Get CSRF token (stores {{csrf_token}})',
        'id': _id('helper', 'csrf'),
        'event': [
            _script('prerequest', SKIP_WITHOUT_LOGIN),
            _script(
                'test',
                [
                    "pm.test('csrf token issued', () => pm.expect(pm.response.code).to.eql(200));",
                    "pm.environment.set('csrf_token', pm.response.json().csrf_token);",
                ],
            ),
        ],
        'request': {
            'method': 'GET',
            'header': [],
            'url': _url('dash_url', '/api/csrf-token', {}),
            'description': 'Every body-method request sends this as X-CSRF-Token.',
        },
    }
    return [login, csrf]


def group_by_blueprint(
    app: str, pairs: list[tuple[dict, str, str]], params: dict[str, str], suffix: str = ''
) -> list[dict]:
    """One folder per blueprint, named ``<app>/<blueprint><suffix>``.

    ``newman --folder NAME`` matches every folder with that name, so the names must
    be unique across the whole collection: the app qualifier separates the
    dashboard's ``medusa`` blueprint from the ``medusa`` app, and the suffix
    separates a runnable folder from its excluded twin.
    """
    folders: dict[str, list[dict]] = {}
    for route, method, kind in pairs:
        bp = route['blueprint'] or '(app)'
        folders.setdefault(bp, []).append(make_request(route, method, app, kind, params))
    return [
        {'name': '%s/%s%s' % (app, bp, suffix), 'id': _id('folder', app, bp + suffix), 'item': folders[bp]}
        for bp in sorted(folders)
    ]


def build() -> tuple[dict, dict, dict[str, int]]:
    inventory = json.loads(ROUTES.read_text())
    params: dict[str, str] = {}

    buckets: dict[str, dict[str, list]] = {'health': {}, 'excluded': {}, 'app': {}}
    for app in APP_ORDER:
        for route in inventory['apps'][app]:
            for method in route['methods']:
                kind = classify(route, method, app)
                bucket = kind if kind in ('health', 'excluded') else 'app'
                buckets[bucket].setdefault(app, []).append((route, method, kind))

    items: list[dict] = []

    health_items = []
    for app in APP_ORDER:
        for route, method, kind in buckets['health'].get(app, []):
            health_items.append(make_request(route, method, app, kind, params))
    items.append(
        {
            'name': HEALTH_FOLDER,
            'id': _id('folder', HEALTH_FOLDER),
            'description': 'Open endpoints: no session, no body, no side effects. The '
            'only folder run live by run_newman.sh.',
            'item': health_items,
        }
    )

    for app in APP_ORDER:
        app_item = []
        if app == 'dashboard':
            app_item += login_helpers()
        app_item += group_by_blueprint(app, buckets['app'].get(app, []), params)
        if not app_item:
            continue  # every route of this app is health or excluded
        items.append(
            {
                'name': app,
                'id': _id('folder', app),
                'description': 'base url {{%s}} (default %s)' % (BASE_VAR[app], BASE_URL[BASE_VAR[app]]),
                'item': app_item,
            }
        )

    excluded_apps = []
    for app in APP_ORDER:
        pairs = buckets['excluded'].get(app, [])
        if pairs:
            excluded_apps.append(
                {
                    'name': '%s (excluded)' % app,
                    'id': _id('folder', 'excluded', app),
                    'item': group_by_blueprint(app, pairs, params, ' (excluded)'),
                }
            )
    items.append(
        {
            'name': EXCLUDED_FOLDER,
            'id': _id('folder', EXCLUDED_FOLDER),
            'description': 'Routes that start work, write, delete, approve, call out or '
            'could not be verified. Every request throws unless '
            'ALLOW_DANGEROUS=1. Do not set it against production data.',
            'item': excluded_apps,
        }
    )

    collection = {
        'info': {
            '_postman_id': _id('collection', 'zygomatic'),
            'name': 'Zygomatic API (554 routes, 4 apps)',
            'schema': SCHEMA,
            'description': __doc__,
        },
        'item': items,
        'variable': (
            [{'key': k, 'value': v, 'type': 'string'} for k, v in BASE_URL.items()]
            + [{'key': k, 'value': params[k], 'type': 'string'} for k in sorted(params)]
        ),
    }

    env_values = [{'key': k, 'value': v, 'type': 'default', 'enabled': True} for k, v in BASE_URL.items()]
    env_values += [
        # Empty by design — never write a credential into a file in this repo.
        {'key': 'ZYG_USER', 'value': '', 'type': 'secret', 'enabled': True},
        {'key': 'ZYG_PASS', 'value': '', 'type': 'secret', 'enabled': True},
        {'key': 'csrf_token', 'value': '', 'type': 'default', 'enabled': True},
        {'key': 'ALLOW_DANGEROUS', 'value': '0', 'type': 'default', 'enabled': True},
    ]
    env_values += [{'key': k, 'value': params[k], 'type': 'default', 'enabled': True} for k in sorted(params)]
    environment = {
        'id': _id('environment', 'local'),
        'name': 'Zygomatic local (127.0.0.1)',
        'values': env_values,
        '_postman_variable_scope': 'environment',
        '_postman_exported_at': datetime.now(timezone.utc).isoformat(),
        '_postman_exported_using': 'apitests/make_postman.py',
    }

    counts = {kind: sum(len(v) for v in buckets[kind].values()) for kind in buckets}
    return collection, environment, counts


def count_requests(items: list[dict]) -> int:
    return sum(count_requests(it['item']) if 'item' in it else 1 for it in items)


def main() -> None:
    collection, environment, counts = build()
    COLLECTION.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + '\n')
    ENVIRONMENT.write_text(json.dumps(environment, indent=2, ensure_ascii=False) + '\n')

    total = 0
    for folder in collection['item']:
        n = count_requests(folder['item'])
        total += n
        print('%5d  %s' % (n, folder['name']))
        for sub in folder['item']:
            if 'item' in sub:
                print('%5d    %s' % (count_requests(sub['item']), sub['name']))
    print('%5d  TOTAL requests' % total)
    print('       buckets: %s' % counts)
    print(
        '       path-param variables: %d'
        % sum(
            1
            for v in environment['values']
            if v['key'] not in BASE_URL and v['key'] not in ('ZYG_USER', 'ZYG_PASS', 'csrf_token', 'ALLOW_DANGEROUS')
        )
    )
    print('       wrote %s' % COLLECTION)
    print('       wrote %s' % ENVIRONMENT)


if __name__ == '__main__':
    main()
