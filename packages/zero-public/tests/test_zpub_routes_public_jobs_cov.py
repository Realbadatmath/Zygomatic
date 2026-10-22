# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline unit coverage for ``zyg_zero.zpub_routes_public.jobs``.

Nothing here touches the network, the GPU or the repository's ``data/`` tree.
``UPLOAD_ROOT``/``CHUNK_UPLOAD_ROOT`` and every helper the module imported from
``zpub_routes_public.core`` are module globals read at call time, so the autouse
``roots`` fixture repoints them at ``tmp_path`` and at recorders — no reload needed —
``render_template`` included, which exercises the HTML routes without Jinja. The routes
run on a bare Flask app with the package blueprint registered (Flask-Limiter is never
``init_app``-ed, so its decorators are inert), and ``uuid`` is faked wherever a
deterministic destination name is needed to reach the upload-failure branches.
"""

import io
import json
import os
import shutil
import types

import flask
import pytest
from werkzeug.datastructures import FileStorage
from zyg_zero.zpub_routes_public import jobs as MOD

pytestmark = pytest.mark.timeout(60)

SID = 'session-abcdef0123'
HEX = 'f' * 32
TOKEN = 'tok12345678'
PNG = b'\x89PNG\r\n\x1a\n'


def _fake_uuid(hex_value=HEX):
    """Deterministic stand-in for the module's ``uuid`` global."""
    return types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex=hex_value))


class _Proxy:
    """Wrap a module global (``os``, ``shutil``), overriding named attributes."""

    def __init__(self, real, **over):
        self.__dict__['_real'] = real
        self.__dict__.update(over)

    def __getattr__(self, key):
        return getattr(self._real, key)


def _boom(*_a, **_kw):
    raise OSError('refused')


@pytest.fixture(autouse=True)
def roots(tmp_path, monkeypatch):
    """Repoint both upload roots and stub the log, the gate and the templates."""
    up = tmp_path / 'uploads'
    chunks = up / '.preview_chunks'
    chunks.mkdir(parents=True)
    monkeypatch.setattr(MOD, 'UPLOAD_ROOT', str(up))
    monkeypatch.setattr(MOD, 'CHUNK_UPLOAD_ROOT', str(chunks))
    logged: list = []
    rendered: list = []
    monkeypatch.setattr(MOD, '_zpub_log', lambda event, **kw: logged.append((event, kw)))

    def _render(name, **ctx):
        rendered.append((name, ctx))
        return 'HTML'

    monkeypatch.setattr(MOD, 'render_template', _render)
    monkeypatch.setattr(MOD, '_session_id', lambda: SID)
    monkeypatch.setattr(MOD, '_session_invite', lambda: '')
    monkeypatch.setattr(MOD, '_gate_response', lambda: ('GATE', 403))
    monkeypatch.setattr(MOD, '_require_api_session', lambda: None)
    monkeypatch.setattr(MOD, '_jobs_for_library', lambda tok, sid: [{'job_id': 'lib', 'token': tok, 'sid': sid}])
    monkeypatch.setattr(MOD, '_load_job', lambda jid: {'job_id': jid})
    monkeypatch.setattr(MOD, '_session_jobs', lambda sid: [])
    return types.SimpleNamespace(up=up, chunks=chunks, logged=logged, rendered=rendered)


@pytest.fixture
def app():
    a = flask.Flask(__name__)
    a.config.update(TESTING=True, SECRET_KEY='jobs-cov')
    a.register_blueprint(MOD.bp)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _admin(client):
    with client.session_transaction() as sess:
        sess['is_zpub_admin'] = True


# --------------------------------------------------------------- index / job_page
@pytest.mark.parametrize('path', ['/', '/job/abc', '/uploads/preview/x.png'])
def test_every_visitor_route_is_gated_without_a_session(client, roots, path):
    assert client.get(path).status_code == 403
    assert roots.rendered == []


def test_index_as_admin_logs_and_caps_recent_jobs_at_five(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, '_session_jobs', lambda sid: [f'j{i}' for i in range(7)])
    monkeypatch.setattr(MOD, '_load_job', lambda jid: None if jid == 'j6' else {'job_id': jid})
    _admin(client)
    resp = client.get('/')
    assert resp.status_code == 200
    name, ctx = roots.rendered[-1]
    assert name == 'zero_public.html'
    assert [j['job_id'] for j in ctx['recent_jobs']] == ['j5', 'j4', 'j3', 'j2', 'j1']
    assert ctx['invite_token'] == '__admin__'
    assert ctx['active_job_id'] is None
    assert roots.logged[0][0] == 'page_visit'
    assert roots.logged[0][1]['session_id'] == SID[:8] + '…'


def test_job_page_with_invite_uses_the_token_for_the_library(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, '_session_invite', lambda: TOKEN)
    resp = client.get('/job/job-7')
    assert resp.status_code == 200
    _, ctx = roots.rendered[-1]
    assert ctx['active_job_id'] == 'job-7'
    assert ctx['invite_token'] == TOKEN
    assert ctx['recent_jobs'][0]['token'] == TOKEN
    assert ctx['invite_used'] == 0 and ctx['invite_max'] == 0


def test_job_page_as_admin_falls_back_to_the_admin_sentinel(client, roots):
    _admin(client)
    assert client.get('/job/job-9').status_code == 200
    assert roots.rendered[-1][1]['invite_token'] == '__admin__'


# ------------------------------------------------------------------------ uploads
def test_uploads_serves_an_existing_file_with_an_immutable_cache_header(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, '_session_invite', lambda: TOKEN)
    target = roots.up / 'preview' / SID / 'shot.png'
    target.parent.mkdir(parents=True)
    target.write_bytes(PNG)
    resp = client.get(f'/uploads/preview/{SID}/shot.png')
    assert resp.status_code == 200
    assert resp.data == PNG
    assert resp.headers['Cache-Control'] == 'private, max-age=31536000, immutable'


def test_uploads_missing_file_is_404(client, monkeypatch):
    monkeypatch.setattr(MOD, '_session_invite', lambda: TOKEN)
    resp = client.get('/uploads/preview/nope.png')
    assert resp.status_code == 404
    assert resp.get_json() == {'error': 'Not found'}


def test_uploads_rejects_a_path_that_escapes_the_upload_root(app, monkeypatch):
    monkeypatch.setattr(MOD, '_session_invite', lambda: TOKEN)
    with app.test_request_context('/uploads/x'):
        body, status = MOD.uploads('../../../etc/passwd')
    assert status == 400
    assert body.get_json() == {'error': 'Invalid path'}


# ---------------------------------------------------------- chunk-dir unit helpers
def test_preview_chunk_helpers_build_and_remove_the_directory(roots):
    d = MOD._preview_chunk_dir(HEX)
    assert d == os.path.join(str(roots.chunks), HEX)
    MOD._cleanup_preview_chunks(HEX)  # absent → no-op
    os.makedirs(d)
    (roots.chunks / HEX / 'part').write_bytes(b'x')
    MOD._cleanup_preview_chunks(HEX)
    assert not os.path.isdir(d)


def test_finalize_preview_upload_moves_then_reports_a_move_failure(roots, tmp_path, monkeypatch):
    src = tmp_path / 'assembled'
    src.write_bytes(b'movie')
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    url, err = MOD._finalize_preview_upload(SID, '.mp4', str(src))
    assert err is None
    assert url == f'/uploads/preview/{SID}/{HEX}.mp4'
    assert (roots.up / 'preview' / SID / f'{HEX}.mp4').read_bytes() == b'movie'

    monkeypatch.setattr(MOD, 'shutil', _Proxy(shutil, move=_boom))
    url, err = MOD._finalize_preview_upload(SID, '.mp4', str(src))
    assert url is None
    assert err.startswith('Upload failed: refused')


# ------------------------------------------------- api_preview_upload, single shot
def _post_file(client, body=PNG, filename='shot.png', field='file'):
    return client.post(
        '/api/preview_upload',
        data={field: (io.BytesIO(body), filename)},
        content_type='multipart/form-data',
    )


def test_preview_upload_honours_the_api_gate(client, monkeypatch):
    monkeypatch.setattr(MOD, '_require_api_session', lambda: ({'error': 'gate'}, 401))
    resp = _post_file(client)
    assert resp.status_code == 401
    assert resp.get_json() == {'error': 'gate'}


def test_preview_upload_without_a_file_is_rejected(client):
    resp = client.post('/api/preview_upload', data={}, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'No file provided'


def test_preview_upload_rejects_an_unsupported_extension(client):
    resp = _post_file(client, filename='notes.txt')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Unsupported file type: .txt'


@pytest.mark.parametrize(('filename', 'is_video'), [('shot.png', False), ('clip.mp4', True)])
def test_preview_upload_stores_images_and_small_videos(client, roots, monkeypatch, filename, is_video):
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    resp = _post_file(client, filename=filename)
    assert resp.status_code == 200
    ext = os.path.splitext(filename)[1]
    assert resp.get_json() == {'success': True, 'url': f'/uploads/preview/{SID}/{HEX}{ext}', 'is_video': is_video}
    assert (roots.up / 'preview' / SID / f'{HEX}{ext}').read_bytes() == PNG


def test_preview_upload_rejects_a_file_over_the_image_limit(client, monkeypatch):
    monkeypatch.setattr(MOD, 'MAX_UPLOAD_BYTES', 4)
    resp = _post_file(client)
    assert resp.status_code == 413
    assert resp.get_json()['error'].startswith('File too large (max 0 MB)')


def test_preview_upload_reports_a_save_failure(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    (roots.up / 'preview' / SID / f'{HEX}.png').mkdir(parents=True)  # save() must now fail
    resp = _post_file(client)
    assert resp.status_code == 500
    assert resp.get_json()['error'].startswith('Upload failed: ')


def test_preview_upload_tolerates_a_stream_that_cannot_seek(client, monkeypatch):
    """The size probe is best-effort: an unseekable upload stream still stores."""
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    monkeypatch.setattr(FileStorage, 'seek', _boom, raising=False)
    resp = _post_file(client)
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


# ----------------------------------------------------- api_preview_upload, chunked
def _post_chunk(client, *, upload_id=HEX, index=0, total=1, filename='clip.mp4', body=b'video', size=None, file=True):
    payload = {
        'upload_id': upload_id,
        'chunk_index': str(index),
        'total_chunks': str(total),
        'filename': filename,
        'total_size': str(len(body) if size is None else size),
    }
    if file:
        payload['file'] = (io.BytesIO(body), 'part.bin')
    return client.post('/api/preview_upload', data=payload, content_type='multipart/form-data')


def _write_meta(roots, **over):
    meta = {'sid': SID, 'filename': 'clip.mp4', 'ext': '.mp4', 'total_chunks': 2, 'total_size': 10}
    meta.update(over)
    d = roots.chunks / HEX
    d.mkdir(parents=True, exist_ok=True)
    (d / '_meta.json').write_text(json.dumps(meta), encoding='utf-8')


CHUNK_REJECTIONS = [
    ({'upload_id': 'not-hex'}, 400, 'Invalid upload_id'),
    ({'index': 'x'}, 400, 'Invalid chunk metadata'),
    ({'index': 0, 'total': 0}, 400, 'Invalid chunk index'),
    ({'index': 3, 'total': 2}, 400, 'Invalid chunk index'),
    ({'filename': 'notes.txt'}, 400, 'Unsupported file type: .txt'),
    ({'size': 0}, 413, 'File too large (max 1024 MB)'),
    ({'size': 'not-a-number'}, 413, 'File too large (max 1024 MB)'),
    ({'size': 2**40}, 413, 'File too large (max 1024 MB)'),
    ({'file': False}, 400, 'No chunk provided'),
    ({'index': 1, 'total': 2}, 400, 'Upload session expired — retry upload'),
]


@pytest.mark.parametrize(('kwargs', 'status', 'error'), CHUNK_REJECTIONS)
def test_chunked_preview_upload_rejections(client, kwargs, status, error):
    resp = _post_chunk(client, **kwargs)
    assert resp.status_code == status
    assert resp.get_json() == {'success': False, 'error': error}


def test_chunked_preview_upload_refuses_a_foreign_session(client, roots):
    _write_meta(roots, sid='someone-else')
    resp = _post_chunk(client, index=1, total=2, size=10)
    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Upload session mismatch'


def test_chunked_preview_upload_refuses_changed_metadata(client, roots):
    _write_meta(roots, total_chunks=5)
    resp = _post_chunk(client, index=1, total=2, size=10)
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Chunk metadata mismatch'


def test_chunked_preview_upload_reports_a_chunk_save_failure(client, roots):
    (roots.chunks / HEX / '00000').mkdir(parents=True)  # save() must now fail
    resp = _post_chunk(client)
    assert resp.status_code == 500
    assert resp.get_json()['error'].startswith('Chunk save failed: ')
    assert not os.path.isdir(roots.chunks / HEX)


def test_chunked_preview_upload_refuses_an_oversized_chunk(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, 'PREVIEW_CHUNK_BYTES', 0)
    resp = _post_chunk(client, body=b'x' * 600_000)
    assert resp.status_code == 413
    assert resp.get_json()['error'] == 'Chunk too large'
    assert not os.path.isdir(roots.chunks / HEX)


def test_chunked_preview_upload_accepts_an_intermediate_chunk(client, roots):
    resp = _post_chunk(client, index=0, total=2, size=10)
    assert resp.status_code == 200
    assert resp.get_json() == {'success': True, 'chunk': 0, 'complete': False}
    assert (roots.chunks / HEX / '00000').read_bytes() == b'video'
    assert json.loads((roots.chunks / HEX / '_meta.json').read_text(encoding='utf-8'))['sid'] == SID


def test_chunked_preview_upload_survives_an_unreadable_chunk_size(client, monkeypatch):
    monkeypatch.setattr(MOD, 'os', _Proxy(os, path=_Proxy(os.path, getsize=_boom)))
    resp = _post_chunk(client, index=0, total=2, size=10)
    assert resp.status_code == 200
    assert resp.get_json()['complete'] is False


def test_chunked_preview_upload_reports_a_failed_assembly(client, roots):
    _write_meta(roots)  # chunk 00000 was never saved
    resp = _post_chunk(client, index=1, total=2, size=10)
    assert resp.status_code == 500
    assert resp.get_json()['error'].startswith('Assembly failed: missing chunk 0')


def test_chunked_preview_upload_refuses_a_size_mismatch(client):
    resp = _post_chunk(client, body=b'abcde', size=10)
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Uploaded size mismatch — retry upload'


def test_chunked_preview_upload_reports_a_finalize_failure(client, monkeypatch):
    monkeypatch.setattr(MOD, 'shutil', _Proxy(shutil, move=_boom))
    resp = _post_chunk(client, body=b'abcde')
    assert resp.status_code == 500
    assert resp.get_json()['error'].startswith('Upload failed: refused')


def test_chunked_preview_upload_assembles_every_chunk(client, roots, monkeypatch):
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    assert _post_chunk(client, index=0, total=2, body=b'aaa', size=6).status_code == 200
    resp = _post_chunk(client, index=1, total=2, body=b'bbb', size=6)
    assert resp.status_code == 200
    url = f'/uploads/preview/{SID}/{HEX}.mp4'
    assert resp.get_json() == {'success': True, 'url': url, 'is_video': True, 'complete': True}
    assert (roots.up / 'preview' / SID / f'{HEX}.mp4').read_bytes() == b'aaabbb'
    assert not os.path.isdir(roots.chunks / HEX)


# ----------------------------------------------------------------------- api_submit
@pytest.fixture
def store(monkeypatch):
    """Replace every store/parse helper ``api_submit`` reaches with a recorder."""
    rec = types.SimpleNamespace(saved=[], enqueued=[], sessions=[], tokens=[], pending=[])
    monkeypatch.setattr(MOD, '_parse_model_family', lambda raw: raw or 'sdxl')
    monkeypatch.setattr(MOD, '_parse_pipeline_options', lambda raw: dict(raw) if isinstance(raw, dict) else {})
    monkeypatch.setattr(MOD, '_parse_creature_options', lambda raw: {'raw': raw})
    monkeypatch.setattr(MOD, '_token_use', lambda tok: {'ok': True})
    monkeypatch.setattr(MOD, '_token_check', lambda tok: {'valid': False})
    monkeypatch.setattr(MOD, '_check_rate_limit', lambda ip: True)
    monkeypatch.setattr(MOD, '_save_job', lambda job: rec.saved.append(job))
    monkeypatch.setattr(MOD, '_enqueue', lambda jid: rec.enqueued.append(jid))
    monkeypatch.setattr(MOD, '_link_session_job', lambda sid, jid: rec.sessions.append((sid, jid)))
    monkeypatch.setattr(MOD, '_link_token_job', lambda tok, jid: rec.tokens.append((tok, jid)))
    monkeypatch.setattr(MOD, '_pending_store', lambda req: rec.pending.append(req))
    monkeypatch.setattr(MOD, '_queue_length', lambda: 3)
    monkeypatch.setattr(MOD, '_get_running', lambda: True)
    monkeypatch.setattr(MOD, '_ams_iso', lambda: '2026-01-01T00:00:00+01:00')
    monkeypatch.setattr(MOD, 'public_url', lambda: 'http://example.org')
    monkeypatch.setattr(MOD, 'uuid', _fake_uuid())
    return rec


def test_submit_without_a_token_is_denied(client, store, roots):
    resp = client.post('/api/submit', json={'prompt': 'a whale'})
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'Access denied. A valid invite link is required.'}
    assert [e[0] for e in roots.logged] == ['gate_blocked']


@pytest.mark.parametrize(
    ('prompt', 'error'),
    [
        ('', 'Please enter a prompt.'),
        ('   ', 'Please enter a prompt.'),
        ('x' * 2001, 'Prompt too long (max 2 000 characters).'),
    ],
)
def test_submit_validates_the_prompt(client, store, prompt, error):
    _admin(client)
    resp = client.post('/api/submit', json={'prompt': prompt})
    assert resp.status_code == 400
    assert resp.get_json() == {'error': error}


def test_submit_as_admin_queues_a_documentary_job(client, store):
    _admin(client)
    resp = client.post('/api/submit', json={'prompt': 'a whale'})
    assert resp.status_code == 200
    expect = {'job_id': HEX, 'status': 'queued', 'queue_position': 3, 'ahead': 3, 'eta_minutes': 135}
    assert resp.get_json() == {**expect, 'job_url': f'/job/{HEX}'}
    (job,) = store.saved
    assert job['invite_token'] == '__admin__'
    assert job['pipeline_style'] == 'documentary'
    assert job['narration_enabled'] is True
    assert job['pipeline_options'] == {'burn_subtitles': True}  # documentary + narration
    assert not job['short_doc_mode']  # no total_duration_sec → the `and` chain stops at None
    assert job['creature_options'] is None and job['char_id'] == ''
    assert job['created_at'] == '2026-01-01T00:00:00+01:00'
    assert store.enqueued == [HEX]
    assert store.sessions == [(SID, HEX)]
    assert store.tokens == []  # the admin sentinel is never linked as a token


SUBMIT_FIELDS = [
    ({'visual_style': 'MANGA'}, 'visual_style', 'manga'),
    ({'visual_style': 'bogus'}, 'visual_style', 'cinematic'),
    ({'scene_mode': 'Continuous'}, 'scene_mode', 'continuous'),
    ({'scene_mode': 'bogus'}, 'scene_mode', 'independent'),
    ({'pipeline_style': 'bogus'}, 'pipeline_style', 'documentary'),
    ({'pipeline_style': 'intro'}, 'pipeline_style', 'intro'),
    ({'video_duration_minutes': 9}, 'video_duration_minutes', 3.0),
    ({'video_duration_minutes': 0.01}, 'video_duration_minutes', 0.25),
    ({'video_duration_minutes': 'nope'}, 'video_duration_minutes', 0.5),
    ({'narration_enabled': False}, 'narration_enabled', False),
    ({'narration_enabled': 'no'}, 'narration_enabled', False),
    ({'narration_enabled': 'yes'}, 'narration_enabled', True),
    ({'ending_text': ' ' + 'e' * 250}, 'ending_text', 'e' * 200),
    ({'model_family': 'flux'}, 'model_family', 'flux'),
    ({'character_id': 'char-1', 'pipeline_style': 'video'}, 'char_id', 'char-1'),
    ({'char_id': 'char-2'}, 'char_id', ''),  # kept only for the video pipeline
]


@pytest.mark.parametrize(('body', 'field', 'expected'), SUBMIT_FIELDS)
def test_submit_normalises_json_fields(client, store, body, field, expected):
    _admin(client)
    resp = client.post('/api/submit', json={'prompt': 'a whale', **body})
    assert resp.status_code == 200
    assert store.saved[0][field] == expected


def test_submit_accepts_form_encoded_bodies(client, store):
    _admin(client)
    form = {
        'prompt': ' a whale ', 'pipeline_style': 'storyteller', 'model_family': 'FLUX',
        'video_duration_minutes': 'nope', 'narration_enabled': 'FALSE', 'visual_style': 'Anime',
        'scene_mode': 'continuous', 'ending_text': 'the end', 'char_id': 'char-3',
    }  # fmt: skip
    resp = client.post('/api/submit', data=form, content_type='application/x-www-form-urlencoded')
    assert resp.status_code == 200
    (job,) = store.saved
    expect = {
        'prompt': 'a whale', 'pipeline_style': 'storyteller', 'model_family': 'flux',
        'video_duration_minutes': 0.5, 'narration_enabled': False, 'visual_style': 'anime',
        'scene_mode': 'continuous', 'ending_text': 'the end',
    }  # fmt: skip
    assert {k: job[k] for k in expect} == expect


@pytest.mark.parametrize(
    ('seconds', 'style', 'field', 'expected'),
    [(90, 'video', 'video_duration_minutes', 1.5), (120, 'documentary', 'short_doc_mode', True)],
)
def test_submit_reads_duration_from_options(client, store, monkeypatch, seconds, style, field, expected):
    monkeypatch.setattr(MOD, '_parse_pipeline_options', lambda raw: {'total_duration_sec': seconds})
    _admin(client)
    assert client.post('/api/submit', json={'prompt': 'a whale', 'pipeline_style': style}).status_code == 200
    assert store.saved[0][field] == expected


def test_submit_keeps_creature_options_for_the_creature_pipeline(client, store):
    _admin(client)
    body = {'prompt': 'a whale', 'pipeline_style': 'creature', 'creature_options': {'legs': 4}}
    assert client.post('/api/submit', json=body).status_code == 200
    assert store.saved[0]['creature_options'] == {'raw': {'legs': 4}}


TOKEN_REFUSALS = [
    ('exhausted', 'This invite link has reached its request limit.'),
    ('expired', 'This invite link has expired.'),
    ('revoked', 'This invite link has been revoked.'),
    ('not_found', 'Invite link not found.'),
    ('main_app_unreachable', 'Server is temporarily unavailable. Please try again shortly.'),
    ('something_else', 'Invite link is no longer valid.'),
]


@pytest.mark.parametrize(('reason', 'message'), TOKEN_REFUSALS)
def test_submit_maps_every_invite_refusal(client, store, roots, monkeypatch, reason, message):
    monkeypatch.setattr(MOD, '_token_use', lambda tok: {'ok': False, 'reason': reason})
    resp = client.post('/api/submit', json={'prompt': 'a whale', 'invite_token': TOKEN})
    assert resp.status_code == 403
    assert resp.get_json() == {'error': message}
    assert 'invite_rejected' in [e[0] for e in roots.logged]


def test_submit_queues_a_manual_permission_request(client, store, roots, monkeypatch):
    manual = {'ok': False, 'reason': 'manual_permission_required', 'entry': {'label': 'Ada'}}
    monkeypatch.setattr(MOD, '_token_use', lambda tok: manual)
    monkeypatch.setattr(MOD, '_session_invite', lambda: TOKEN)
    resp = client.post('/api/submit', json={'prompt': 'a whale', 'pipeline_type': 'video', 'voice': 'calm'})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body['pending'] is True
    assert body['pending_id'] == 'preq_' + HEX[:12]
    (req,) = store.pending
    assert req['token'] == TOKEN
    assert req['label'] == 'Ada'
    assert req['invite_url'] == f'http://example.org/u/{TOKEN}'
    assert req['pipeline'] == 'video'
    assert req['voice'] == 'calm'
    assert req['status'] == 'pending' and req['decided_at'] is None
    assert req['requested_at'].endswith('Z')
    assert 'manual_pending_queued' in [e[0] for e in roots.logged]
    assert store.saved == []


def test_submit_queues_a_manual_token_even_when_the_credit_was_spent(client, store, monkeypatch):
    checked = {'valid': True, 'entry': {'permission': 'manual', 'label': 'Ada'}}
    monkeypatch.setattr(MOD, '_token_check', lambda tok: checked)
    resp = client.post('/api/submit', json={'prompt': 'a whale', 'invite_token': TOKEN, 'type': 'intro'})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body['pending_id'] == 'preq_' + HEX[:12]
    assert 'awaiting manual approval' in body['message']
    (req,) = store.pending
    assert req['pipeline'] == 'intro'
    assert req['session_id'] == SID
    assert store.saved == []


def test_submit_reports_the_rate_limit(client, store, roots, monkeypatch):
    monkeypatch.setattr(MOD, '_check_rate_limit', lambda ip: False)
    resp = client.post('/api/submit', json={'prompt': 'a whale', 'invite_token': TOKEN})
    assert resp.status_code == 429
    assert 'max 2 jobs per hour' in resp.get_json()['error']
    assert 'rate_limited' in [e[0] for e in roots.logged]


def test_submit_with_a_valid_token_links_the_token_to_the_job(client, store, roots):
    resp = client.post('/api/submit', json={'prompt': 'a whale', 'invite_token': TOKEN})
    assert resp.status_code == 200
    assert store.tokens == [(TOKEN, HEX)]
    assert store.saved[0]['invite_token'] == TOKEN
    assert 'submit' in [e[0] for e in roots.logged]


def test_submit_with_no_queue_reports_a_one_minute_eta(client, store, monkeypatch):
    monkeypatch.setattr(MOD, '_queue_length', lambda: 0)
    monkeypatch.setattr(MOD, '_get_running', lambda: False)
    _admin(client)
    resp = client.post('/api/submit', json={'prompt': 'a whale'})
    assert resp.get_json()['eta_minutes'] == 1
    assert resp.get_json()['ahead'] == 0


def test_submit_saves_only_the_acceptable_uploaded_images(client, store, roots, monkeypatch):
    monkeypatch.setattr(MOD, 'MAX_UPLOAD_BYTES', 32)
    _admin(client)
    images = [
        (io.BytesIO(PNG), 'keep.png'), (io.BytesIO(b'x'), 'skip.txt'),
        (io.BytesIO(b'y' * 64), 'toobig.png'), (io.BytesIO(b''), ''),
    ]  # fmt: skip
    data = {'prompt': 'a whale', 'pipeline_style': 'video', 'images': images}
    resp = client.post('/api/submit', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    paths = store.saved[0]['uploaded_image_paths']
    assert paths == [str(roots.up / HEX / f'{HEX}.png')]
    assert os.path.isfile(paths[0])
