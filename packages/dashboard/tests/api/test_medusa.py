# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-process API tests for the Medusa GUI (:5300, ``~/Zygomatic/medusa``).

WHY THIS MODULE CARRIES ITS OWN FIXTURE
---------------------------------------
``medusa_server`` lives outside the crews tree and reads its data relative to
the process' working directory, so it needs ``sys.path`` and ``os.chdir``
pointed at ``~/Zygomatic/medusa`` for the duration of the
session (both restored in the fixture's teardown). The import is still run
under the same thread suppression the crews harness uses — measured, Medusa
starts no background thread of its own, and the fixture asserts that.

WHAT THE TESTS ARE ALLOWED TO CALL
----------------------------------
Medusa has no login: ``medusa_ipgate`` is the only gate and the test client's
default REMOTE_ADDR (127.0.0.1) is on its allowlist, so any request made here
reaches the real handler and runs against the operator's REAL data under
``~/Zygomatic/medusa/data/runtime``. Every route is therefore
classified by READING its handler:

``safe``      idempotent, no write, no outbound POST.
``validate``  an empty JSON body is rejected with a 4xx *before* the first
              write, subprocess, thread or outbound request.
``exclude``   anything else — a job starter, a POST forwarded to the live
              :5000 crews API, a URL downloader, a delete, or the operator's
              approval queue. These are NEVER called with a body from an
              allowlisted address; the only thing asserted about them is that
              the ip gate answers 403 from a non-allowlisted address, which
              happens before the handler runs.

The per-route decision and its reason are written to
``apitests/reports/medusa.json``.
"""

import inspect
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.timeout(60)]

# The Medusa app is a separate checkout (ZYG_MEDUSA_APP_DIR, see docs/configuration.md); without it
# these tests have nothing to import.
MEDUSA_DIR = Path(os.environ.get('ZYG_MEDUSA_APP_DIR', '~/Zygomatic/medusa')).expanduser()
if not MEDUSA_DIR.is_dir():
    pytest.skip(f'the Medusa app checkout is not here ({MEDUSA_DIR}); set ZYG_MEDUSA_APP_DIR', allow_module_level=True)
CREWS_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = CREWS_DIR / 'apitests' / 'reports'

BLOCKED_ADDR = '10.0.0.9'

# The tree's shared heuristics, applied to rule+endpoint and to handler source.
DANGER_RE = re.compile(
    r'(start|run|launch|generate|render|train|restart|kill|stop|delete|purge|'
    r'approve|reject|reset|submit|build|spawn|clear|remove|cancel|resume|pause|'
    r'enqueue|trigger|execute|install|download|upload|convert|export|import|'
    r'write|save|set_|toggle|enable|disable|login|logout)'
)
EXTERNAL_RE = re.compile(
    r'(requests\.(get|post|put)|urlopen|subprocess\.|Popen|\.run\(|ollama|'
    r'anthropic|comfy|socket\.)'
)

# GETs the heuristics clear but a handler read does not. Hand-excluded, with
# the reason that goes into the report.
GET_EXCLUDE = {
    '/api/vicky/chat': 'handler calls medusa_vicky.open_chat(), which rewrites '
    'data/runtime/vicky/current.json and mints a chat file when the store '
    'is empty — a GET that writes, so it stays out of the sweep',
}

# Body-method routes cleared by reading the handler top-down to the first side
# effect. (rule, method, url, expected status range, why).
VALIDATE_CASES = [
    (
        '/api/medusa/models/<model_id>/images',
        'POST',
        '/api/medusa/models/__apitest__/images',
        (400,),
        'medusa_server.py:4033 — request.files.getlist("files") is empty for a '
        'JSON body, so the handler returns 400 before the requests.post forward',
    ),
    (
        '/api/medusa/training/characters/<char_id>/images',
        'POST',
        '/api/medusa/training/characters/__apitest__/images',
        (400,),
        'medusa_server.py:4184 — same shape: no "images" field, 400 before the multipart forward to the live crews API',
    ),
    (
        '/api/vicky/upload',
        'POST',
        '/api/vicky/upload',
        (400,),
        'medusa_server.py:4335 — request.files.get("file") is None, 400 before '
        'medusa_vicky.save_upload touches the uploads folder',
    ),
    (
        '/api/vicky/chat/<action>',
        'POST',
        '/api/vicky/chat/__apitest_unknown__',
        (404,),
        'medusa_vicky.handle_post:1375 — an unrecognised action falls through '
        'every branch to {"error": "not found"}, 404; no branch body runs',
    ),
    (
        '/api/vicky/chat/<action>',
        'POST',
        '/api/vicky/chat/delete',
        (400,),
        'medusa_vicky.handle_post:1368 + chat_delete:837 — with {} there is no '
        '"all" and the id is "", which _valid_chat_id rejects, so chat_delete '
        'returns False before any os.remove and the answer is 400',
    ),
    (
        '/api/resources/upload',
        'POST',
        '/api/resources/upload',
        (400,),
        'medusa_resources.py:1635 — no "pages" field, 400 before the staging folder is written',
    ),
    (
        '/api/resources/preview',
        'POST',
        '/api/resources/preview',
        (400,),
        'medusa_resources.py:1944 — _split_urls({}) is empty, 400 before '
        '_fetch_page issues any outbound request (preview downloads nothing else)',
    ),
    (
        '/api/resources/jobs/<job_id>/cancel',
        'POST',
        '/api/resources/jobs/__apitest__/cancel',
        (404,),
        'medusa_resources.py:2019 — _JOBS has no such id, 404 before the cancel flag is set on anything',
    ),
]

SAFE_CASES = [
    (
        '/api/vicky/cancel',
        'POST',
        '/api/vicky/cancel',
        (200,),
        'medusa_vicky.cancel_job:1163 — JOBS.get("") is None, so it returns '
        '{"ok": false, "error": "no such job"} without touching a job; the route '
        'jsonifies that at 200',
    ),
]

EXCLUDE_CASES = [
    (
        '/api/generate_character',
        'POST',
        '/api/generate_character',
        'forwards the body as POST /api/medusa/generate to the LIVE crews API '
        'on :5000, which starts a character generation',
    ),
    (
        '/api/medusa/pending/<req_id>/decide',
        'POST',
        '/api/medusa/pending/__apitest__/decide',
        'decides the operator approval queue on the live crews API',
    ),
    (
        '/api/medusa/models',
        'POST',
        '/api/medusa/models',
        'POST is forwarded verbatim to the live crews API (creates a model row)',
    ),
    (
        '/api/medusa/models/<path:sub>',
        'POST',
        '/api/medusa/models/__apitest__/x',
        'wildcard proxy: every POST/PATCH/DELETE is forwarded to the live crews '
        'API, so the effect is whatever bp_medusa_models does',
    ),
    (
        '/api/medusa/models/<path:sub>',
        'PATCH',
        '/api/medusa/models/__apitest__',
        'same wildcard proxy, mutating method',
    ),
    ('/api/medusa/models/<path:sub>', 'DELETE', '/api/medusa/models/__apitest__', 'same wildcard proxy, delete'),
    (
        '/api/medusa/training/characters',
        'POST',
        '/api/medusa/training/characters',
        'forwarded POST creates a training character on the live crews API',
    ),
    (
        '/api/medusa/training/characters/<char_id>',
        'DELETE',
        '/api/medusa/training/characters/__apitest__',
        'forwarded DELETE removes a training character and its images',
    ),
    (
        '/api/medusa/training/characters/<char_id>/train',
        'POST',
        '/api/medusa/training/characters/__apitest__/train',
        'starts a LoRA training run on the live crews API',
    ),
    (
        '/api/medusa/training/characters/<char_id>/sheet',
        'POST',
        '/api/medusa/training/characters/__apitest__/sheet',
        'builds a contact sheet (GPU render) on the live crews API',
    ),
    (
        '/api/medusa/training/characters/<char_id>/body-prepare',
        'POST',
        '/api/medusa/training/characters/__apitest__/body-prepare',
        'starts body preparation on the live crews API',
    ),
    (
        '/api/medusa/training/characters/<char_id>/images/<image_id>',
        'DELETE',
        '/api/medusa/training/characters/__apitest__/images/__apitest__',
        'forwarded DELETE removes a training image',
    ),
    (
        '/api/medusa/training/scan-folder',
        'POST',
        '/api/medusa/training/scan-folder',
        'forwarded to the live crews API, which walks an import root',
    ),
    (
        '/api/medusa/training/import-folders',
        'POST',
        '/api/medusa/training/import-folders',
        'forwarded import copies folders into the training store',
    ),
    (
        '/api/medusa/training/sheets/build-all',
        'POST',
        '/api/medusa/training/sheets/build-all',
        'starts a batch of contact-sheet renders on the live crews API',
    ),
    (
        '/api/resources/fetch-urls',
        'POST',
        '/api/resources/fetch-urls',
        'downloads the addresses in the body (planner job + extraction threads)',
    ),
    (
        '/api/resources/sets/<set_name>',
        'DELETE',
        '/api/resources/sets/__apitest__',
        'shutil.rmtree of a resources set — a delete against real operator data',
    ),
    (
        '/api/vicky/start',
        'POST',
        '/api/vicky/start',
        'starts a `claude -p` subprocess and appends a message to a real chat',
    ),
]


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope='session')
def medusa_app():
    """The imported medusa_server module, with cwd and sys.path pointed at it."""
    old_cwd = os.getcwd()
    sys.path.insert(0, str(MEDUSA_DIR))
    os.chdir(MEDUSA_DIR)

    # Threads already running when this fixture is built belong to whatever
    # else the session imported (the dashboard harness leaves the Otel exporter
    # alive). Only threads this import adds are Medusa's responsibility.
    before = {t.ident for t in threading.enumerate()}

    suppressed = []
    real_start = threading.Thread.start

    def _blocked_start(self):
        if self.name.startswith('Otel'):
            return real_start(self)
        suppressed.append(self.name)
        return None

    threading.Thread.start = _blocked_start
    try:
        import medusa_server as m
    finally:
        threading.Thread.start = real_start
        # Restored as soon as the import is done rather than at session
        # teardown: every Medusa data root (BASE_DIR, the Vicky runtime, the
        # resources root) is absolute, derived from __file__, so the chdir is
        # only needed for the import itself — and a session-scoped chdir would
        # leak into whatever test module runs after this one.
        os.chdir(old_cwd)

    socket.setdefaulttimeout(5)

    # Measured 2026-10-02: Medusa starts no background worker at import.
    assert suppressed == [], f'medusa_server started background threads: {suppressed}'
    added = [t.name for t in threading.enumerate() if t.ident not in before]
    assert added == [], f'importing medusa_server added live threads: {added}'

    try:
        yield m
    finally:
        if str(MEDUSA_DIR) in sys.path:
            sys.path.remove(str(MEDUSA_DIR))


@pytest.fixture
def med(medusa_app):
    """Client from 127.0.0.1 — passes medusa_ipgate."""
    with medusa_app.app.test_client() as c:
        yield c


@pytest.fixture
def med_blocked(medusa_app):
    """Client from an address the ip gate does not allow."""
    with medusa_app.app.test_client() as c:
        c.environ_base['REMOTE_ADDR'] = BLOCKED_ADDR
        yield c


def _rules(medusa_app):
    return sorted(medusa_app.app.url_map.iter_rules(), key=lambda r: str(r))


def _sweepable_gets(medusa_app):
    """GET-only, no path params, not danger, not external, not hand-excluded."""
    out = []
    for rule in _rules(medusa_app):
        if rule.endpoint == 'static' or rule.arguments:
            continue
        methods = rule.methods - {'HEAD', 'OPTIONS'}
        if methods != {'GET'}:
            continue
        path = str(rule)
        if path in GET_EXCLUDE:
            continue
        if DANGER_RE.search(f'{path} {rule.endpoint}'):
            continue
        try:
            src = inspect.getsource(medusa_app.app.view_functions[rule.endpoint])
        except (OSError, TypeError):
            src = ''
        if EXTERNAL_RE.search(src):
            continue
        out.append(path)
    return out


# ── the ip gate ─────────────────────────────────────────────────────────────
def test_index_from_localhost_is_200(med):
    r = med.get('/')
    assert r.status_code == 200, r.data[:200]


def test_index_from_blocked_address_is_403_json(med_blocked):
    r = med_blocked.get('/')
    assert r.status_code == 403, r.data[:200]
    assert r.is_json, r.headers.get('Content-Type')
    assert r.get_json().get('ok') is False, r.get_json()


def test_medusa_has_no_health_endpoint(med):
    """Pinned so the Postman layer never assumes the crews /api/health here."""
    assert med.get('/api/health').status_code == 404


# ── (b) the GET sweep ───────────────────────────────────────────────────────
def test_get_sweep_never_500s(medusa_app, med):
    paths = _sweepable_gets(medusa_app)
    assert len(paths) >= 10, f'the GET sweep collapsed to {paths}'

    rows, bad = [], []
    for path in paths:
        t0 = time.time()
        r = med.get(path)
        rows.append(
            {
                'route': path,
                'method': 'GET',
                'class': 'safe',
                'status': r.status_code,
                'ms': round((time.time() - t0) * 1000),
                'why': 'GET-only, no path params, cleared by the danger and external heuristics',
            }
        )
        if r.status_code not in (200, 204, 400, 404):
            bad.append((path, r.status_code, r.data[:200]))

    _stash(rows)
    assert not bad, bad


# ── (c) body methods ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    'rule,method,url,expected,why',
    VALIDATE_CASES + SAFE_CASES,
    ids=[f'{m}:{u}' for _r, m, u, _e, _w in VALIDATE_CASES + SAFE_CASES],
)
def test_empty_body_is_rejected_before_any_write(med, rule, method, url, expected, why):
    r = med.open(url, method=method, json={})
    _stash(
        [
            {
                'route': rule,
                'method': method,
                'url': url,
                'class': 'validate' if expected != (200,) else 'safe',
                'status': r.status_code,
                'expected': list(expected),
                'why': why,
            }
        ]
    )
    assert r.status_code in expected, (url, r.status_code, r.data[:300])


def test_every_body_method_route_is_classified(medusa_app):
    """A new POST/PUT/DELETE/PATCH route must be read and classified, not
    silently left untested."""
    declared = {(rule, method) for rule, method, _u, _e, _w in VALIDATE_CASES + SAFE_CASES}
    declared |= {(rule, method) for rule, method, _u, _w in EXCLUDE_CASES}

    actual = set()
    for rule in _rules(medusa_app):
        if rule.endpoint == 'static':
            continue
        for method in rule.methods - {'HEAD', 'OPTIONS', 'GET'}:
            actual.add((str(rule), method))

    assert actual - declared == set(), 'unclassified body-method routes'
    assert declared - actual == set(), 'classified routes that no longer exist'


@pytest.mark.parametrize('rule,method,url,why', EXCLUDE_CASES, ids=[f'{m}:{u}' for _r, m, u, _w in EXCLUDE_CASES])
def test_excluded_route_is_refused_by_the_ip_gate(med_blocked, rule, method, url, why):
    """The one thing that is safe to assert about an excluded route: the gate
    answers before the handler can run."""
    r = med_blocked.open(url, method=method, json={})
    _stash(
        [
            {
                'route': rule,
                'method': method,
                'url': url,
                'class': 'exclude',
                'status_from_blocked_addr': r.status_code,
                'why': why,
            }
        ]
    )
    assert r.status_code == 403, (url, r.status_code, r.data[:300])


# ── report ──────────────────────────────────────────────────────────────────
_ROWS = []


def _stash(rows):
    _ROWS.extend(rows)


@pytest.fixture(scope='session', autouse=True)
def write_report(medusa_app):
    yield
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rules = [
        {
            'rule': str(r),
            'endpoint': r.endpoint,
            'methods': sorted(r.methods - {'HEAD', 'OPTIONS'}),
            'params': sorted(r.arguments),
        }
        for r in _rules(medusa_app)
    ]
    payload = {
        'app': 'medusa_server',
        'source': str(MEDUSA_DIR / 'medusa_server.py'),
        'generated_by': 'tests/api/test_medusa.py',
        'rules_total': len(rules),
        'gate': f'medusa_ipgate only (no login); 127.0.0.1 allowed, {BLOCKED_ADDR} refused with 403 JSON',
        'get_excluded_by_hand': GET_EXCLUDE,
        'rules': rules,
        'checked': _ROWS,
    }
    (REPORTS_DIR / 'medusa.json').write_text(json.dumps(payload, indent=2, default=str))
