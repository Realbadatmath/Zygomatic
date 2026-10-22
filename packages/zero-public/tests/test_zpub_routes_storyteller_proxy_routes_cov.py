# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline unit coverage for ``zyg_zero.zpub_routes_storyteller.proxy_routes``.

Seventeen Flask routes forwarding to the studio's internal API, so nothing here needs
the network, the GPU or the repository's ``data/`` tree: :func:`_proxy` swaps the module
global ``_requests`` for a ``_Resp`` stand-in (or a raising stub for the 503 branches);
the autouse ``env`` fixture repoints both disk roots the bodies read at call time
(``paths.ZYG_LORA_DATASETS``, ``_DATASET_ROOT``) at ``tmp_path``; :func:`_install` fakes
the lazily imported ``zyg_workflows`` helpers *on the package* as well as in
``sys.modules``, because ``from pkg import name`` resolves the package attribute first
(``_install(..., name=None)`` makes such an import fail instead); and the routes run on a
bare Flask app where Flask-Limiter is never ``init_app``-ed, so ``@limiter.limit`` is
inert and the read gate ``_zpub_story_gate`` is stubbed per test.
"""

import io
import sys
import types

import flask
import pytest
import zyg_workflows
from zyg_zero.zpub_routes_storyteller import proxy_routes as MOD

pytestmark = pytest.mark.timeout(60)

CID = 'aaaaaaaaaaaa'
MP = 'multipart/form-data'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 8
MP3 = b'ID3' + b'\x00' * 16


def _boom(*_a, **_kw):
    raise RuntimeError('helper down')


class _Resp:
    """Minimal ``requests.Response`` stand-in for the internal-API hop."""

    def __init__(self, *, status=200, payload=None, ok=None, headers=None, chunks=(b'IMG',)):
        self.status_code = status
        self.ok = (status < 400) if ok is None else ok
        self.headers = dict(headers or {})
        self._payload = {'ok': True} if payload is None else payload
        self._chunks = chunks

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=0):
        return iter(self._chunks)


def _proxy(monkeypatch, resp=None, exc=None):
    """Replace ``_requests`` and return the list of (method, url, kwargs) calls."""
    calls: list = []

    def _verb(method):
        def _call(url, **kw):
            calls.append((method, url, kw))
            if exc is not None:
                raise exc
            return resp if resp is not None else _Resp()

        return _call

    monkeypatch.setattr(MOD, '_requests', types.SimpleNamespace(get=_verb('GET'), post=_verb('POST')))
    return calls


def _fakemod(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(f'zyg_workflows.{name}')
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _install(monkeypatch, **mods) -> None:  # install, or with None break, zyg_workflows.<name>
    for name, mod in mods.items():
        if mod is None:
            monkeypatch.delattr(zyg_workflows, name, raising=False)
            monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', None)
        else:
            monkeypatch.setattr(zyg_workflows, name, mod, raising=False)
            monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', mod)


def _voices(monkeypatch, tmp_path, **over):
    """Install a ``storyteller_voice_preview_service`` fake for the four voice routes."""
    attrs = {
        'VOICE_SAMPLE_V1': 'Once upon a time.',
        'VOICE_SAMPLE_V2': 'And then the door opened.',
        'default_voice_id': lambda: 'nl-NL-FennaNeural',
        'grouped_voices_for_api': lambda kind: [{'label': kind.title(), 'voices': []}],
        'SAMPLES_ROOT': str(tmp_path),
        'migrate_legacy_wav_samples': lambda: None,
        'resolve_sample_path': lambda vid, variant: '',
        'sample_mimetype': lambda path: 'audio/mpeg',
    }
    attrs.update(over)
    _install(monkeypatch, storyteller_voice_preview_service=_fakemod('svps', **attrs))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    """Repoint both disk roots, silence the audit log and neutralise the gates."""
    lora, datasets = tmp_path / 'lora', tmp_path / 'datasets'
    (lora / 'storyteller_chars').mkdir(parents=True)
    datasets.mkdir()
    monkeypatch.setattr(MOD, 'paths', types.SimpleNamespace(ZYG_LORA_DATASETS=lora))
    monkeypatch.setattr(MOD, '_DATASET_ROOT', str(datasets))
    logged: list = []
    monkeypatch.setattr(MOD, '_zpub_log', lambda event, **kw: logged.append((event, kw)))
    monkeypatch.setattr(MOD, '_int_headers', lambda: {'X-Internal': 'test'})
    monkeypatch.setattr(MOD, '_client_ip', lambda: '203.0.113.7')
    monkeypatch.setattr(MOD, '_session_id', lambda: 'sid-1')
    monkeypatch.setattr(MOD, '_session_invite', lambda: '')
    monkeypatch.setattr(MOD, '_token_check', lambda token: {'valid': True})
    return types.SimpleNamespace(lora=lora, sheets=lora / 'storyteller_chars', datasets=datasets, logged=logged)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(MOD, '_zpub_story_gate', lambda: None)
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='proxy-routes-cov')
    app.register_blueprint(MOD.bp)
    return app.test_client()


def _admin(client):
    with client.session_transaction() as sess:
        sess['is_zpub_admin'] = True


def _photo(name='face.png', ctype='image/png'):
    return (io.BytesIO(PNG), name, ctype)


# ───────────────────────────────────────────────────── invite-token validation
REJECTIONS = [
    ('expired', 'This invite link has expired.'),
    ('revoked', 'This invite link has been revoked.'),
    ('not_found', 'Invite link not found.'),
    ('token_not_found', 'Invite link not found.'),
    ('main_app_unreachable', 'Server is temporarily unavailable.'),
    ('weird', 'Access denied. A valid invite link is required.'),
    ('', 'Access denied. A valid invite link is required.'),
]


@pytest.mark.parametrize(('reason', 'message'), REJECTIONS)
def test_reject_invalid_token_maps_every_reason(client, monkeypatch, env, reason, message):
    monkeypatch.setattr(MOD, '_token_check', lambda token: {'valid': False, 'reason': reason})
    resp = client.post('/api/storyteller/contact-sheet/start', json={'invite_token': 'invite-placeholder'})
    assert resp.status_code == 403
    assert resp.get_json() == {'error': message}
    event, fields = env.logged[-1]
    assert event == 'invite_token_rejected'
    assert fields['route'] == 'contact-sheet/start'
    assert fields['token_preview'] == 'invite-p…'  # the first eight characters


def test_reject_invalid_token_returns_none_when_the_flag_is_off(client, monkeypatch):
    monkeypatch.setattr(MOD, '_ZPUB_VALIDATE_TOKEN', False)
    monkeypatch.setattr(MOD, '_token_check', _boom)  # never consulted
    _proxy(monkeypatch, resp=_Resp(payload={'started': True}))
    resp = client.post('/api/storyteller/contact-sheet/start', json={'invite_token': 'x'})
    assert (resp.status_code, resp.get_json()) == (200, {'started': True})


def test_token_check_returning_none_is_a_rejection(client, monkeypatch):
    monkeypatch.setattr(MOD, '_token_check', lambda token: None)
    resp = client.post('/api/storyteller/contact-sheet/start', json={'invite_token': 'tok'})
    assert resp.status_code == 403


# every GPU-spending write route refuses a caller with no invite at all
TOKENLESS = [
    ('/api/storyteller/analyze-character-photo', {'data': {'note': 'none'}, 'content_type': MP}),
    ('/api/storyteller/generate-character', {'json': {}}),
    ('/api/storyteller/generate-character', {'data': {'params': '{}'}, 'content_type': MP}),
    ('/api/storyteller/contact-sheet/start', {'json': {'angles': 48}}),
]


@pytest.mark.parametrize(('path', 'kwargs'), TOKENLESS)
def test_every_write_route_denies_a_tokenless_caller(client, path, kwargs):
    resp = client.post(path, **kwargs)
    assert resp.status_code == 403
    assert resp.get_json()['error'].startswith('Access denied')


# ──────────────────────────────────────────────── analyze-character-photo (POST)
def test_analyze_photo_requires_multipart(client):
    resp = client.post('/api/storyteller/analyze-character-photo', json={'invite_token': 'tok'})
    assert (resp.status_code, resp.get_json()) == (400, {'error': 'multipart/form-data required'})


def test_analyze_photo_takes_the_token_from_the_session(client, monkeypatch):
    monkeypatch.setattr(MOD, '_session_invite', lambda: 'session-tok')
    seen: list = []
    monkeypatch.setattr(MOD, '_token_check', lambda token: seen.append(token) or {'valid': True})
    _proxy(monkeypatch, resp=_Resp(payload={'fields': {'hair_color': 'auburn'}}))
    resp = client.post('/api/storyteller/analyze-character-photo', data={'photo': _photo()}, content_type=MP)
    assert (resp.status_code, seen) == (200, ['session-tok'])
    assert resp.get_json() == {'fields': {'hair_color': 'auburn'}}


def test_analyze_photo_rejects_an_invalid_token(client, monkeypatch, env):
    monkeypatch.setattr(MOD, '_token_check', lambda token: {'valid': False, 'reason': 'revoked'})
    resp = client.post(
        '/api/storyteller/analyze-character-photo',
        data={'photo': _photo(), 'invite_token': 'tok'},
        content_type=MP,
    )
    assert (resp.status_code, resp.get_json()) == (403, {'error': 'This invite link has been revoked.'})
    assert env.logged[-1][1]['route'] == 'analyze-character-photo'


def test_analyze_photo_requires_a_photo_part(client):
    _admin(client)
    resp = client.post('/api/storyteller/analyze-character-photo', data={'note': 'no file here'}, content_type=MP)
    assert (resp.status_code, resp.get_json()) == (400, {'error': 'photo file required'})


def test_analyze_photo_forwards_the_file_and_the_upstream_status(client, monkeypatch):
    calls = _proxy(monkeypatch, resp=_Resp(status=422, payload={'ok': False, 'error': 'no face'}))
    resp = client.post(
        '/api/storyteller/analyze-character-photo',
        data={'photo': _photo('selfie.jpg', 'image/jpeg'), 'invite_token': ' tok '},
        content_type=MP,
    )
    assert (resp.status_code, resp.get_json()) == (422, {'ok': False, 'error': 'no face'})
    method, url, kw = calls[0]
    assert (method, kw['timeout']) == ('POST', 180)
    assert url.endswith('/api/internal/storyteller/analyze-character-photo')
    assert kw['files'] == [('photo', ('selfie.jpg', PNG, 'image/jpeg'))]
    assert kw['headers'] == {'X-Internal': 'test'}


def test_analyze_photo_reports_empty_fields_when_the_hop_fails(client, monkeypatch):
    _admin(client)
    _proxy(monkeypatch, exc=OSError('connection refused'))
    resp = client.post('/api/storyteller/analyze-character-photo', data={'photo': _photo()}, content_type=MP)
    body = resp.get_json()
    assert (resp.status_code, body['ok'], body['fields']) == (503, False, {})
    assert 'connection refused' in body['error']


# ───────────────────────────────────────────────────── generate-character (POST)
def test_generate_character_rejects_an_invalid_token(client, monkeypatch, env):
    monkeypatch.setattr(MOD, '_token_check', lambda token: {'valid': False, 'reason': 'expired'})
    resp = client.post('/api/storyteller/generate-character', json={'invite_token': '  tok  '})
    assert resp.status_code == 403
    assert env.logged[-1][1]['route'] == 'generate-character'


def test_generate_character_forwards_json(client, monkeypatch):
    calls = _proxy(monkeypatch, resp=_Resp(status=202, payload={'job_id': 'j1'}))
    body = {'invite_token': 'tok', 'hair_color': 'auburn', 'gender': 'f'}
    resp = client.post('/api/storyteller/generate-character', json=body)
    assert (resp.status_code, resp.get_json()) == (202, {'job_id': 'j1'})
    method, url, kw = calls[0]
    assert (method, kw['timeout'], kw['json']) == ('POST', 20, body)
    assert url.endswith('/api/internal/storyteller/generate-character')


@pytest.mark.parametrize('family', ['FLUX', 'sdxl'])
def test_generate_character_forwards_multipart_with_a_known_family(client, monkeypatch, family):
    calls = _proxy(monkeypatch)
    params = '{"invite_token": "tok", "model_family": "%s"}' % family
    resp = client.post(
        '/api/storyteller/generate-character',
        data={'params': params, 'photos': [_photo('a.png'), _photo('b.png')]},
        content_type=MP,
    )
    assert resp.status_code == 200
    _method, _url, kw = calls[0]
    assert kw['data'] == {'params': params, 'model_family': family.lower()}
    assert [name for name, _part in kw['files']] == ['photos', 'photos']
    assert kw['files'][0][1] == ('a.png', PNG, 'image/png')
    assert kw['timeout'] == 60


# ``params`` that is valid JSON but not an object (``.get`` raises, the suppressing
# branch runs) and one whose family is neither flux nor sdxl: neither may reach the form.
@pytest.mark.parametrize('params', ['"a bare string"', '{"model_family": "  "}'])
def test_generate_character_multipart_forwards_no_unknown_family(client, monkeypatch, params):
    _admin(client)
    calls = _proxy(monkeypatch)
    resp = client.post('/api/storyteller/generate-character', data={'params': params}, content_type=MP)
    assert resp.status_code == 200
    _method, _url, kw = calls[0]
    assert (kw['data'], kw['files']) == ({'params': params}, None)


# ───────────────────────────────────────────── contact-sheet start/status/approve
def test_contact_sheet_start_forwards_as_admin(client, monkeypatch):
    _admin(client)
    calls = _proxy(monkeypatch, resp=_Resp(payload={'char_id': CID}))
    resp = client.post('/api/storyteller/contact-sheet/start', json={'angles': 48})
    assert (resp.status_code, resp.get_json()) == (200, {'char_id': CID})
    _method, url, kw = calls[0]
    assert url.endswith('/api/internal/storyteller/contact-sheet/start')
    assert (kw['json'], kw['timeout']) == ({'angles': 48}, 30)


def test_contact_sheet_status_forwards_the_upstream_status(client, monkeypatch):
    calls = _proxy(monkeypatch, resp=_Resp(status=404, payload={'error': 'unknown char'}))
    resp = client.get(f'/api/storyteller/contact-sheet/status/{CID}')
    assert (resp.status_code, resp.get_json()) == (404, {'error': 'unknown char'})
    assert calls[0][1].endswith(f'/api/internal/storyteller/contact-sheet/status/{CID}')
    assert calls[0][2]['timeout'] == 15


def test_contact_sheet_approve_is_gone_by_design(client):
    _admin(client)
    resp = client.post(f'/api/storyteller/contact-sheet/approve/{CID}')
    assert resp.status_code == 410
    assert resp.get_json()['ok'] is False
    assert 'Agent Zero' in resp.get_json()['error']


# ───────────────────────────────────────────────── pause / resume (admin only)
# (verb, tail): the upstream path is the same tail under ``/api/internal/storyteller/``.
CTRL_ROUTES = [
    ('get', 'pipeline/pause-state'),
    ('post', 'pipeline/pause'),
    ('post', 'pipeline/resume'),
    ('post', f'contact-sheet/pause/{CID}'),
    ('post', f'contact-sheet/resume/{CID}'),
]


@pytest.mark.parametrize(('verb', 'tail'), CTRL_ROUTES)
def test_pipeline_controls_are_admin_only(client, verb, tail):
    resp = getattr(client, verb)(f'/api/storyteller/{tail}')
    assert (resp.status_code, resp.get_json()) == (403, {'ok': False, 'error': 'Admin only'})


@pytest.mark.parametrize(('verb', 'tail'), CTRL_ROUTES)
def test_pipeline_controls_forward_for_an_admin(client, monkeypatch, verb, tail):
    _admin(client)
    body = {'why': 'operator'} if verb == 'post' else None
    calls = _proxy(monkeypatch, resp=_Resp(payload={'paused': True}))
    resp = getattr(client, verb)(f'/api/storyteller/{tail}', json=body)
    assert (resp.status_code, resp.get_json()) == (200, {'paused': True})
    method, url, kw = calls[0]
    assert (method, url.endswith(f'/api/internal/storyteller/{tail}'), kw['timeout']) == (verb.upper(), True, 20)
    assert kw.get('json') == body


# ──────────────────────────────────────────── contact-sheet training composite
# a char_id that is not twelve lowercase hex digits, and a well-formed one with no file
@pytest.mark.parametrize('char_id', ['ABEL', CID])
def test_training_image_404s_for_a_bad_id_or_a_missing_composite(client, char_id):
    assert client.get(f'/api/storyteller/contact-sheet/training-image/{char_id}').status_code == 404


def test_training_image_serves_the_png_uncached(client, env):
    sheet = env.sheets / CID / 'contact_sheet'
    sheet.mkdir(parents=True)
    (sheet / 'contact_sheet_training.png').write_bytes(PNG)
    resp = client.get(f'/api/storyteller/contact-sheet/training-image/{CID}')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'image/png', PNG)
    assert resp.headers['Cache-Control'] == 'no-store, must-revalidate'
    assert resp.headers['Pragma'] == 'no-cache'


# ───────────────────────────────────────────────────── contact-sheet image proxy
def test_contact_sheet_image_streams_the_upstream_body_and_its_headers(client, monkeypatch):
    hdrs = {'content-type': 'image/jpeg', 'Content-Disposition': 'inline; filename=sheet.jpg'}
    calls = _proxy(monkeypatch, resp=_Resp(headers={**hdrs, 'X-Sheet-Variant': 'master_part'}, chunks=(b'AA', b'BB')))
    resp = client.get(f'/api/storyteller/contact-sheet/image/{CID}?v=2')
    assert (resp.status_code, resp.data) == (200, b'AABB')
    assert resp.headers['Content-Type'] == 'image/jpeg'
    assert resp.headers['Cache-Control'] == 'no-store, must-revalidate'
    assert resp.headers['Pragma'] == 'no-cache'
    assert resp.headers['Content-Disposition'] == 'inline; filename=sheet.jpg'
    assert resp.headers['X-Sheet-Variant'] == 'master_part'
    _method, _url, kw = calls[0]
    assert (kw['stream'], kw['timeout'], kw['params']['v']) == (True, 30, '2')


def test_contact_sheet_image_defaults_the_content_type(client, monkeypatch):
    _proxy(monkeypatch, resp=_Resp(chunks=(PNG,)))
    resp = client.get(f'/api/storyteller/contact-sheet/image/{CID}')
    assert (resp.status_code, resp.headers['Content-Type'], resp.data) == (200, 'image/png', PNG)
    assert 'X-Sheet-Variant' not in resp.headers


def test_contact_sheet_image_passes_an_upstream_error_through(client, monkeypatch):
    _proxy(monkeypatch, resp=_Resp(status=502))
    resp = client.get(f'/api/storyteller/contact-sheet/image/{CID}')
    assert (resp.status_code, resp.data) == (502, b'')


def test_contact_sheet_image_disk_fallback_rejects_a_non_hex_id(client, monkeypatch):
    _proxy(monkeypatch, exc=OSError('upstream down'))
    assert client.get('/api/storyteller/contact-sheet/image/not-hex').status_code == 404


@pytest.mark.parametrize('helper', ['missing', 'blank', 'raises'])
def test_contact_sheet_image_disk_fallback_404s_without_a_master(client, monkeypatch, helper):
    _proxy(monkeypatch, exc=OSError('upstream down'))
    if helper == 'missing':
        _install(monkeypatch, contact_sheet_pipeline=None)
    elif helper == 'blank':
        _install(monkeypatch, contact_sheet_pipeline=_fakemod('csp'))  # no any_master_sheet_path
    else:
        _install(monkeypatch, contact_sheet_pipeline=_fakemod('csp', any_master_sheet_path=_boom))
    assert client.get(f'/api/storyteller/contact-sheet/image/{CID}').status_code == 404


def test_contact_sheet_image_disk_fallback_uses_the_pipeline_path(client, monkeypatch, tmp_path):
    _proxy(monkeypatch, exc=OSError('upstream down'))
    part = tmp_path / 'contact_sheet_master_part_01.png'
    part.write_bytes(PNG)
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('csp', any_master_sheet_path=lambda cid: str(part)))
    resp = client.get(f'/api/storyteller/contact-sheet/image/{CID}')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'image/png', PNG)


@pytest.mark.parametrize(('query', 'attachment'), [('', False), ('?download=1', True), ('?download=no', False)])
def test_contact_sheet_image_disk_fallback_honours_download(client, monkeypatch, env, query, attachment):
    _proxy(monkeypatch, exc=OSError('upstream down'))
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('csp', any_master_sheet_path=lambda cid: ''))
    sheet = env.datasets / CID / 'contact_sheet'
    sheet.mkdir(parents=True)
    (sheet / 'contact_sheet_master.png').write_bytes(PNG)
    resp = client.get(f'/api/storyteller/contact-sheet/image/{CID}{query}')
    assert (resp.status_code, resp.data) == (200, PNG)
    disposition = resp.headers.get('Content-Disposition', '')
    assert ('attachment' in disposition) is attachment
    if attachment:
        assert f'contact_sheet_{CID[:8]}.png' in disposition


# ─────────────────────────────────────────────────────── list-contact-sheets
@pytest.mark.parametrize(('query', 'expected'), [('?model_family=FLUX', {'model_family': 'flux'}), ('?x=1', {})])
def test_list_contact_sheets_forwards_a_known_family_only(client, monkeypatch, query, expected):
    calls = _proxy(monkeypatch, resp=_Resp(payload={'sheets': [], 'count': 0}))
    resp = client.get(f'/api/storyteller/list-contact-sheets{query}')
    assert (resp.status_code, resp.get_json()) == (200, {'sheets': [], 'count': 0})
    assert calls[0][2]['params'] == expected


def test_list_contact_sheets_falls_back_to_the_local_library(client, monkeypatch):
    rows = [
        {'char_id': CID, 'status': 'running', 'lora_ready': False},
        {'char_id': 'bbbbbbbbbbbb', 'status': 'done', 'lora_ready': True},
    ]
    _proxy(monkeypatch, resp=_Resp(status=503, payload={}))
    _install(
        monkeypatch,
        contact_sheet_pipeline=_fakemod('csp', list_contact_sheet_library=lambda model_family: list(rows)),
    )
    monkeypatch.setattr(MOD, 'filter_out_medusa', lambda sheets: sheets)
    body = client.get('/api/storyteller/list-contact-sheets').get_json()
    assert body == {'sheets': rows, 'count': 2, 'pending_count': 1, 'trained_count': 1, 'source': 'local'}


def test_list_contact_sheets_logs_a_proxy_exception(client, monkeypatch, env):
    _proxy(monkeypatch, exc=OSError('connection refused'))
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('csp', list_contact_sheet_library=lambda model_family: []))
    monkeypatch.setattr(MOD, 'filter_out_medusa', lambda sheets: sheets)
    body = client.get('/api/storyteller/list-contact-sheets').get_json()
    assert body['source'] == 'local' and body['count'] == 0
    assert env.logged[-1][0] == 'list_contact_sheets_proxy_fail'
    assert 'connection refused' in env.logged[-1][1]['error']


def test_list_contact_sheets_500s_when_the_local_library_fails(client, monkeypatch):
    _proxy(monkeypatch, exc=OSError('upstream down'))
    _install(monkeypatch, contact_sheet_pipeline=None)
    resp = client.get('/api/storyteller/list-contact-sheets')
    assert resp.status_code == 500
    body = resp.get_json()
    assert (body['sheets'], body['count']) == ([], 0)
    assert body['error']


# ──────────────────────────────────────────────────────────── voice catalog
@pytest.mark.parametrize(
    ('query', 'kind'), [('', 'character'), ('?kind=NARRATOR', 'narrator'), ('?kind=robot', 'character')]
)
def test_voices_normalises_the_kind(client, monkeypatch, tmp_path, query, kind):
    _voices(monkeypatch, tmp_path)
    body = client.get(f'/api/storyteller/voices{query}').get_json()
    assert body['kind'] == kind
    assert body['groups'] == [{'label': kind.title(), 'voices': []}]
    assert body['default_voice'] == 'nl-NL-FennaNeural'
    assert body['sample_phrases'] == {'v1': 'Once upon a time.', 'v2': 'And then the door opened.'}


def test_voices_500s_when_the_catalog_fails(client, monkeypatch, tmp_path):
    _voices(monkeypatch, tmp_path, grouped_voices_for_api=_boom)
    resp = client.get('/api/storyteller/voices')
    assert resp.status_code == 500
    assert 'helper down' in resp.get_json()['error']


def test_voices_500s_when_the_service_cannot_be_imported(client, monkeypatch):
    _install(monkeypatch, storyteller_voice_preview_service=None)
    assert client.get('/api/storyteller/voices').status_code == 500


@pytest.mark.parametrize('count', [0, 2])
def test_voice_samples_health_counts_the_mp3s_on_disk(client, monkeypatch, tmp_path, count):
    migrated: list = []
    _voices(monkeypatch, tmp_path, migrate_legacy_wav_samples=lambda: migrated.append(1))
    for index in range(count):
        nested = tmp_path / f'voice{index}'
        nested.mkdir()
        (nested / 'v1.mp3').write_bytes(MP3)
    body = client.get('/api/storyteller/voice-samples-health').get_json()
    assert (body['ok'], body['sample_count']) == (count > 0, count)
    assert (body['root'], body['server_has_route'], migrated) == (str(tmp_path), True, [1])


@pytest.mark.parametrize('variant', ['v3', '', 'wav'])
def test_voice_sample_rejects_an_unknown_variant(client, monkeypatch, tmp_path, variant):
    _voices(monkeypatch, tmp_path)
    resp = client.get(f'/api/storyteller/voice-sample/nl-NL-FennaNeural/{variant}')
    assert resp.status_code in (400, 404)
    if resp.status_code == 400:
        assert resp.get_json() == {'error': 'variant must be v1 or v2'}


# '' → the service has not generated it yet; a path that is not on disk → send_file raises
@pytest.mark.parametrize(('resolved', 'status'), [('', 404), ('gone.mp3', 500)])
def test_voice_sample_reports_a_sample_it_cannot_serve(client, monkeypatch, tmp_path, resolved, status):
    _voices(monkeypatch, tmp_path, resolve_sample_path=lambda vid, variant: resolved and str(tmp_path / resolved))
    resp = client.get('/api/storyteller/voice-sample/nl-NL-FennaNeural/v1')
    assert (resp.status_code, bool(resp.get_json()['error'])) == (status, True)


def test_voice_sample_serves_the_mp3_with_a_week_long_cache(client, monkeypatch, tmp_path):
    sample = tmp_path / 'fenna_v2.mp3'
    sample.write_bytes(MP3)
    _voices(monkeypatch, tmp_path, resolve_sample_path=lambda vid, variant: str(sample))
    resp = client.get('/api/storyteller/voice-sample/nl-NL-FennaNeural/V2')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'audio/mpeg', MP3)
    assert resp.headers['Cache-Control'] == 'public, max-age=604800'
    assert resp.headers['Accept-Ranges'] == 'bytes'


# ───────────────────────────────────────────────────────────── character-status
def test_character_status_forwards_the_upstream_payload(client, monkeypatch):
    calls = _proxy(monkeypatch, resp=_Resp(payload={'stage': 'lora_training', 'pct': 41}))
    resp = client.get(f'/api/storyteller/character-status/{CID}')
    assert (resp.status_code, resp.get_json()) == (200, {'stage': 'lora_training', 'pct': 41})
    _method, url, kw = calls[0]
    assert url.endswith(f'/api/internal/storyteller/character-status/{CID}')
    assert kw['timeout'] == 10


# ─────────────────────────────── the shared failure modes: dead hop, missing session
# Every proxying route turns a raising hop into a 503 quoting the upstream error.
UNREACHABLE = [
    ('post', '/api/storyteller/generate-character', {'json': {}}),
    ('post', '/api/storyteller/contact-sheet/start', {'json': {}}),
    ('get', f'/api/storyteller/contact-sheet/status/{CID}', {}),
    ('get', '/api/storyteller/pipeline/pause-state', {}),
    ('get', f'/api/storyteller/character-status/{CID}', {}),
]


@pytest.mark.parametrize(('verb', 'path', 'kwargs'), UNREACHABLE)
def test_every_proxied_route_reports_an_unreachable_main_app(client, monkeypatch, verb, path, kwargs):
    _admin(client)
    _proxy(monkeypatch, exc=OSError('no route to host'))
    resp = getattr(client, verb)(path, **kwargs)
    assert resp.status_code == 503
    assert 'no route to host' in resp.get_json()['error']


GATED = [
    f'/api/storyteller/contact-sheet/status/{CID}',
    f'/api/storyteller/contact-sheet/training-image/{CID}',
    f'/api/storyteller/contact-sheet/image/{CID}',
    '/api/storyteller/list-contact-sheets',
    f'/api/storyteller/character-status/{CID}',
]


@pytest.mark.parametrize('path', GATED)
def test_every_read_route_is_session_gated(client, monkeypatch, path):
    monkeypatch.setattr(MOD, '_zpub_story_gate', lambda: ('denied', 403))
    assert client.get(path).status_code == 403
