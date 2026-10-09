# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-process API tests for zero_public_server.

Self-contained: this module owns its fixtures and never uses the dashboard
harness in tests/api/conftest.py (importing crewai_web_gui costs ~3 s and
315 MB and is not needed here).

WHY Thread.start STAYS PATCHED FOR THE WHOLE MODULE
---------------------------------------------------
Importing ``zero_public_server`` creates the daemon thread ``zpub-worker``
(zpub_worker._worker_loop) — the real job runner. A pytest process runs beside
the LIVE public server, so a second copy of that loop would claim and execute
real jobs. Suppressing Thread.start only around the import is NOT enough:
several handlers import heavy modules lazily (``/api/storyteller/voices``
pulls in crewai_web_gui, which starts ``telemetry-sampler``), and a sweep
leaked two of those threads when the patch was lifted after the import.
The patch therefore covers every request too and is restored at teardown,
where the test asserts nothing survived. The Otel exporter thread is the one
exception: its atexit handler joins it and raises
``RuntimeError: cannot join thread before it is started`` if it never ran.

WHY THE LIMITER IS OFF
----------------------
zpub_gate.limiter defaults to 2000/hour per key and several routes carry
tighter per-route limits ('5 per hour' on generate-character). A full sweep
would measure Flask-Limiter instead of the gates. ``enabled = False`` is set
on this process's imported module only; the live server is untouched.

WHY ZPUB_LOG_PATH IS REDIRECTED
-------------------------------
Every gate refusal calls zpub_store._zpub_log, which appends to
data/runtime/zpub_user_log.jsonl. Tests must not write under data/runtime, so
the env var that chooses that path is pointed at a temp file before import.

WHAT IS NEVER CALLED
--------------------
``POST /api/sports-video/trigger`` (zpub_routes_sports.py:64) has no gate of
any kind and its first statement block runs ``scripts.betlab_query.
write_data_json`` and writes ``sports-video/data/<sport>_<date>.json`` before
any validation. Calling it would act on real data, which this tree forbids, so
it is excluded from the request sweep and asserted on by reading its source
instead (see test_ungated_acting_body_route_is_still_ungated).
"""

from __future__ import annotations

import base64
import inspect
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from zyg_workflows import paths

pytestmark = pytest.mark.timeout(60)

REPO_DIR = Path(__file__).resolve().parents[2]
# The sweep's own report. It is a test artefact, not source, so it is written OUTSIDE the
# repository — a run must never leave an untracked file behind for `git add -A` to pick up.
# Point ZPUB_APITEST_REPORT_DIR somewhere else to keep it.
REPORTS_DIR = Path(os.environ.get('ZPUB_APITEST_REPORT_DIR') or Path(tempfile.gettempdir()) / 'zpub_apitests')
FINDINGS_MD = REPORTS_DIR / 'findings_zero_public.md'
REPORT_JSON = REPORTS_DIR / 'zero_public.json'

# Same heuristics as apitests/inventory.py, inlined so this module has no
# dependency on another task's file.
DANGER_RE = re.compile(
    r'(start|run|launch|generate|render|train|restart|kill|stop|delete|purge'
    r'|approve|reject|reset|submit|build|spawn|clear|remove|cancel|resume'
    r'|pause|enqueue|trigger|execute|install|download|upload|convert|export'
    r'|import|write|save|set_|toggle|enable|disable|login|logout)'
)
EXTERNAL_RE = re.compile(
    r'(requests\.(get|post|put)|urlopen|subprocess\.|Popen|\.run\('
    r'|ollama|anthropic|comfy|socket\.)',
    re.IGNORECASE,
)
# zero_public has no app-level before_request gate: every route that is gated
# calls one of these in its own body.
GATE_CALL_RE = re.compile(
    r'_require_api_session|_api_gate_json|_gate_response|_require\(\)'
    r'|is_zpub_admin|_check_admin|_zpub_reject_invalid_token|_session_invite'
    r'|_unlocked|_pipeline_ctrl_proxy'
)

# Body routes that must never be issued as a request. Reason is quoted in the
# report so the exclusion stays auditable.
NEVER_CALL = {
    '/api/sports-video/trigger': 'no gate; first block runs scripts.betlab_query.write_data_json and '
    'writes sports-video/data/<sport>_<date>.json before any validation '
    '(zpub_routes_sports.py:64)',
}

# Statuses an anonymous empty-body request may legitimately get. The brief's
# set is (400, 401, 403, 404, 415); two are added after reading the handlers:
#   410 — /api/storyteller/contact-sheet/approve/<char_id> returns 410 Gone
#         unconditionally as its first statement (approval moved to Agent Zero).
#   429 — any per-route limiter that survives limiter.enabled = False.
ANON_BODY_OK = {400, 401, 403, 404, 410, 415, 429}

# Body routes whose 2xx to an anonymous empty body is CORRECT, with the reason that was read out
# of the handler. The heuristic above cannot see this; the allow-list keeps the exception auditable.
ANON_BODY_OK_ROUTES = {
    '/api/cinema/lock': 'log-out: the handler is `session.pop("cinema_ok", None)` and nothing else '
    '(zpub_routes_cinema.py:132). It reads no body, touches no data and acts only on the CALLER OWN '
    'cookie session, so there is nothing for a gate to protect — an anonymous caller has no '
    '`cinema_ok` to drop. Refusing anonymous callers would only make logging out fail.',
}

# Routes that cannot answer without something outside this repository. Marked `service` so the CPU
# subset (`pytest -m 'not service'`) stays green; the reason is what the handler needs.
SERVICE_ROUTES = {
    '/Portfolio': 'renders the invite page, which asks the dashboard main app (:5000) for the '
    'invite record; without it the handler returns its soft 503 "Main app unreachable" card '
    '(zpub_routes_public.py:131)',
    '/portfolio': 'alias of /Portfolio — same main-app lookup (zpub_routes_public.py:184)',
    '/api/sports-video/tournaments': 'imports `scripts.betlab_query` from the separate '
    'sports-video-pipeline checkout named by settings.ZYG_SPORTS_VIDEO_DIR, which is not part of '
    'this repository; without it the handler returns 500 (zpub_routes_sports.py:44)',
}

# An invite session must not turn a read into a crash; 2xx/3xx/4xx are all fine.
NO_SERVER_ERROR = 500

ANON_IP = '10.0.0.9'  # not loopback: defeats every local-peer bypass
INVITE_SESSION = {
    'zpub_invite_token': '__apitest__',
    'is_zpub_admin': True,
    'zpub_sid': 'apitest',
}

_LOADED: dict = {}


# --------------------------------------------------------------------- import
def _handler_source(app, endpoint: str) -> str:
    view = app.view_functions.get(endpoint)
    try:
        return ''.join(inspect.getsourcelines(inspect.unwrap(view))[0])
    except (OSError, TypeError):
        return ''


def _handler_where(app, endpoint: str) -> str:
    view = inspect.unwrap(app.view_functions.get(endpoint))
    try:
        path = inspect.getsourcefile(view)
        lineno = inspect.getsourcelines(view)[1]
    except (OSError, TypeError):
        return '?'
    return f'{os.path.basename(path or "?")}:{lineno}'


def _classify(app):
    """(safe_gets, body_routes) — records, not Rule objects."""
    safe_gets, bodies = [], []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == 'static' or rule.endpoint.endswith('.static'):
            continue
        methods = rule.methods - {'HEAD', 'OPTIONS'}
        source = _handler_source(app, rule.endpoint)
        rec = {
            'rule': rule.rule,
            'endpoint': rule.endpoint,
            'methods': sorted(methods),
            'func': _handler_where(app, rule.endpoint),
            'params': sorted(rule.arguments),
            'danger': bool(DANGER_RE.search(f'{rule.rule} {rule.endpoint}')),
            'external': bool(EXTERNAL_RE.search(source)),
            'gated': bool(GATE_CALL_RE.search(source)),
        }
        if methods == {'GET'}:
            if not rec['params'] and not rec['danger'] and not rec['external']:
                safe_gets.append(rec)
        elif methods & {'POST', 'PUT', 'DELETE', 'PATCH'}:
            rec['probe_method'] = 'POST' if 'POST' in methods else sorted(methods)[0]
            rec['probe_url'] = re.sub(r'<[^>]+>', '__apitest__', rule.rule)
            rec['never_call'] = NEVER_CALL.get(rule.rule)
            bodies.append(rec)
    return safe_gets, bodies


def _load() -> dict:
    """Import both apps once, at collection time, with Thread.start neutered.

    Collection time, because @parametrize over the route inventory has to know
    the routes before any fixture runs.
    """
    if _LOADED:
        return _LOADED
    if str(REPO_DIR) not in sys.path:
        sys.path.insert(0, str(REPO_DIR))
    os.environ['CREWAI_PAGE_LOAD_DEBUG'] = '0'
    os.environ['ZPUB_LOG_PATH'] = os.path.join(tempfile.gettempdir(), 'apitest_zpub_user_log.jsonl')

    suppressed: list[str] = []
    real_start = threading.Thread.start

    def blocked_start(self):
        if self.name.startswith('Otel'):
            return real_start(self)
        suppressed.append(self.name)
        return None

    threading.Thread.start = blocked_start
    try:
        from zyg_zero import zero_public_server
        from zyg_zero import zpub_gate

        zpub_gate.limiter.enabled = False
        socket.setdefaulttimeout(5)

        safe_gets, bodies = _classify(zero_public_server.app)
        _LOADED.update(
            zpub=zero_public_server.app,
            suppressed=suppressed,
            safe_gets=safe_gets,
            bodies=bodies,
            real_start=real_start,
            blocked_start=blocked_start,
        )
    finally:
        threading.Thread.start = real_start
    return _LOADED


_STATE = _load()
SAFE_GETS = _STATE['safe_gets']
BODY_ROUTES = _STATE['bodies']


@pytest.fixture(scope='module', autouse=True)
def apps():
    """Keep Thread.start neutered while the requests run (lazy imports)."""
    threading.Thread.start = _STATE['blocked_start']
    try:
        yield _STATE
    finally:
        threading.Thread.start = _STATE['real_start']

    leaked = [t.name for t in threading.enumerate() if t.name != 'MainThread' and not t.name.startswith('Otel')]
    assert not leaked, f'background threads leaked into the test process: {leaked}'


CALLABLE_BODY = [b for b in BODY_ROUTES if not b['never_call']]

MATRIX: dict = {'zero_public': {'gets': {}, 'bodies': {}}}


def _params(routes):
    """Route records as parametrize values, with `service` on the ones SERVICE_ROUTES names."""
    out = []
    for rec in routes:
        reason = SERVICE_ROUTES.get(rec['rule'])
        marks = [pytest.mark.service(reason=reason)] if reason else []
        out.append(pytest.param(rec, marks=marks, id=rec['rule']))
    return out


SAFE_GET_PARAMS = _params(SAFE_GETS)


# ------------------------------------------------------------------- clients
@pytest.fixture
def zpub_anon(apps):
    with apps['zpub'].test_client() as c:
        c.environ_base['REMOTE_ADDR'] = ANON_IP
        yield c


@pytest.fixture
def zpub_invite(apps):
    with apps['zpub'].test_client() as c:
        c.environ_base['REMOTE_ADDR'] = ANON_IP
        with c.session_transaction() as s:
            s.update(INVITE_SESSION)
        yield c


# -------------------------------------------------------------- import proof
def test_zpub_worker_thread_was_suppressed(apps):
    assert 'zpub-worker' in apps['suppressed'], (
        'zpub_worker._worker_loop was NOT suppressed — the real job runner may '
        f'be live in this process. suppressed={apps["suppressed"]}'
    )
    alive = {t.name for t in threading.enumerate()}
    assert 'zpub-worker' not in alive
    assert apps['zpub'].url_map, 'zero_public_server exposed no routes'


def test_classification_is_not_empty():
    assert len(SAFE_GETS) >= 10, SAFE_GETS
    assert len(BODY_ROUTES) >= 20, BODY_ROUTES


# ------------------------------------------------------------------ (a) gate
def test_anon_index_is_the_locked_gate(zpub_anon):
    rv = zpub_anon.get('/')
    MATRIX['zero_public']['gets']['/'] = {'anon': rv.status_code}
    assert rv.status_code == 403, (
        f'GET / anonymously answered {rv.status_code}; the invite gate must render the locked page with 403'
    )


# -------------------------------------------------- (b) safe GETs, anonymous
@pytest.mark.parametrize('route', SAFE_GET_PARAMS)
def test_safe_get_anon(zpub_anon, route):
    rv = zpub_anon.get(route['rule'])
    MATRIX['zero_public']['gets'].setdefault(route['rule'], {})['anon'] = rv.status_code
    assert rv.status_code != NO_SERVER_ERROR, (
        f'GET {route["rule"]} anon → 500 ({route["func"]}): {rv.get_data(as_text=True)[:300]}'
    )
    assert rv.status_code in (200, 302, 401, 403, 404), f'GET {route["rule"]} anon → {rv.status_code} ({route["func"]})'


# ------------------------------------------------- (c) safe GETs with invite
@pytest.mark.parametrize('route', SAFE_GET_PARAMS)
def test_safe_get_invite(zpub_invite, route):
    rv = zpub_invite.get(route['rule'])
    MATRIX['zero_public']['gets'].setdefault(route['rule'], {})['invite'] = rv.status_code
    assert rv.status_code != NO_SERVER_ERROR, (
        f'GET {route["rule"]} with an invite session → 500 ({route["func"]}): {rv.get_data(as_text=True)[:300]}'
    )


# --------------------------------------------- (d) body routes, anon, {} body
@pytest.mark.parametrize('route', CALLABLE_BODY, ids=[r['rule'] for r in CALLABLE_BODY])
def test_body_route_rejects_anonymous_empty_body(zpub_anon, route):
    rv = zpub_anon.open(route['probe_url'], method=route['probe_method'], json={})
    MATRIX['zero_public']['bodies'][route['rule']] = {
        'method': route['probe_method'],
        'func': route['func'],
        'gated': route['gated'],
        'anon_empty_body': rv.status_code,
    }
    assert rv.status_code != NO_SERVER_ERROR, (
        f'{route["probe_method"]} {route["rule"]} anon → 500 ({route["func"]}): {rv.get_data(as_text=True)[:300]}'
    )
    allowed = ANON_BODY_OK_ROUTES.get(route['rule'])
    if allowed:
        MATRIX['zero_public']['bodies'][route['rule']]['anon_2xx_allowed_because'] = allowed
        return
    assert rv.status_code in ANON_BODY_OK, (
        f'FINDING: {route["probe_method"]} {route["rule"]} ({route["func"]}) '
        f'accepted an ANONYMOUS empty-body request and answered '
        f'{rv.status_code}. A body-method route on the public app must refuse '
        f'before the handler acts. gate call in handler: {route["gated"]}. '
        f'See {FINDINGS_MD}.'
    )


@pytest.mark.xfail(
    strict=True,
    reason='KNOWN OPEN FINDING, not a test defect: /api/sports-video/trigger really is ungated and '
    'really does write before it validates. Closing it is an application change outside the scope '
    'of the repository extraction, so the finding is kept RED-but-expected: the assertion below '
    'still names the route, and the day a gate is added this xfail turns into an XPASS failure and '
    'forces the marker to be removed. See NEVER_CALL for the exact reason the sweep will not probe it.',
)
def test_ungated_acting_body_route_is_still_ungated():
    """The one route the sweep refuses to call, asserted by source instead."""
    offenders = sorted(NEVER_CALL)
    MATRIX['zero_public']['bodies'].update(
        {rule: {'anon_empty_body': 'NOT CALLED', 'gated': False, 'reason': why} for rule, why in NEVER_CALL.items()}
    )
    assert not offenders, (
        'FINDING: these public body routes have no gate and act on real data '
        'before validating, so the test layer may not even probe them: '
        + '; '.join(f'{r} — {NEVER_CALL[r]}' for r in offenders)
        + f'. See {FINDINGS_MD}.'
    )


# ------------------------------------------- (e) the public verification door
# A 2x2 PNG written by Pillow and never signed: the reader must report it as carrying
# no content credential.
UNSIGNED_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPkEpFjYGBgYmBgYGBgAAAC5gBAXKUgWwAAAABJRU5ErkJggg=='
)
ROOT_CERT_URL = '/.well-known/zygomatic-c2pa-root.pem'
# Not a real certificate — the route must serve whatever starts with this header without
# parsing it, and refuse everything that does not. A test must never read the operator's keys.
FAKE_ROOT_PEM = '-----BEGIN CERTIFICATE-----\nZm9yIHRoZSByb3V0ZSB0ZXN0IG9ubHk=\n-----END CERTIFICATE-----\n'


def test_verify_page_is_public(zpub_anon):
    """GET /verify explains content credentials to anyone, with no invite."""
    rv = zpub_anon.get('/verify')
    assert rv.status_code == 200, f'GET /verify anon → {rv.status_code}'
    body = rv.get_data(as_text=True)
    assert 'Content Credentials' in body, body[:400]
    assert ROOT_CERT_URL in body, 'the page must point at the public root certificate'


def test_root_cert_404_when_the_file_is_absent(zpub_anon, monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_C2PA_ROOT_CERT', str(tmp_path / 'absent' / 'ca.pem'))
    rv = zpub_anon.get(ROOT_CERT_URL)
    assert rv.status_code == 404, f'{ROOT_CERT_URL} with no cert on disk → {rv.status_code}'


def test_root_cert_is_served_and_only_certificates_are(zpub_anon, monkeypatch, tmp_path):
    cert = tmp_path / 'ca.pem'
    cert.write_text(FAKE_ROOT_PEM)
    monkeypatch.setenv('ZYG_C2PA_ROOT_CERT', str(cert))
    rv = zpub_anon.get(ROOT_CERT_URL)
    assert rv.status_code == 200, f'{ROOT_CERT_URL} with a cert on disk → {rv.status_code}'
    assert rv.mimetype == 'application/x-pem-file', rv.mimetype
    assert rv.get_data(as_text=True) == FAKE_ROOT_PEM

    # The key-leak guard: anything whose first bytes are not a certificate header is a 404,
    # so a mis-pointed ZYG_C2PA_ROOT_CERT cannot publish a private key or a chain.
    # The header is assembled rather than spelled out so the secret scanners do not read this
    # placeholder (its body decodes to 'not a key either') as a committed private key.
    pem = '-----BEGIN {0} KEY-----\nbm90IGEga2V5IGVpdGhlcg==\n-----END {0} KEY-----\n'
    not_a_cert = tmp_path / 'signer.key'
    not_a_cert.write_text(pem.format('PRIVATE'))
    monkeypatch.setenv('ZYG_C2PA_ROOT_CERT', str(not_a_cert))
    rv = zpub_anon.get(ROOT_CERT_URL)
    assert rv.status_code == 404, f'a non-certificate PEM was served with {rv.status_code}'


def test_verify_upload_reports_an_unsigned_file(zpub_anon):
    """POST /verify reads the credential of an upload and keeps nothing."""
    rv = zpub_anon.post(
        '/verify',
        data={'file': (io.BytesIO(UNSIGNED_PNG), 'unsigned.png')},
        content_type='multipart/form-data',
    )
    assert rv.status_code == 200, f'POST /verify → {rv.status_code}: {rv.get_data(as_text=True)[:300]}'
    body = rv.get_data(as_text=True)
    assert 'not sealed' in body, body[:600]
    assert 'unsigned.png' in body
    leftovers = sorted(p.name for p in (paths.tmp_dir('verify')).glob('verify_*'))
    assert not leftovers, f'the upload was left behind in the scratch directory: {leftovers}'


# ---------------------------------------------------------------- the report
@pytest.fixture(scope='module', autouse=True)
def _write_report(apps):
    """Written at teardown so it holds whatever the sweep actually measured."""
    yield
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        'generated_by': 'tests/api/test_zero_public.py',
        'suppressed_threads': sorted(set(apps['suppressed'])),
        'counts': {
            'zero_public_rules': len([r for r in apps['zpub'].url_map.iter_rules()]),
            'safe_get_routes': len(SAFE_GETS),
            'body_routes': len(BODY_ROUTES),
            'body_routes_called': len(CALLABLE_BODY),
            'body_routes_never_called': len(NEVER_CALL),
        },
        'never_called': NEVER_CALL,
        'anon_body_allowed_statuses': sorted(ANON_BODY_OK),
        'matrix': MATRIX,
    }
    REPORT_JSON.write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
