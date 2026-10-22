# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline unit coverage for ``zyg_zero.zpub_routes_cinema``.

The 21 routes run on a bare Flask app with the blueprint registered: Flask-Limiter is never
``init_app``-ed there, so ``@limiter.limit``/``@limiter.exempt`` are inert and the session cookie is
the only gate. Every call into the real library goes through the module global ``cine``, which the
autouse fixture replaces with ``_Cine`` — a recorder answering from memory, so no scan, no ffmpeg
and no thread ever starts. ``_zpub_log`` (the real one appends to ``data/runtime/``) becomes a list,
``_client_ip`` a constant, ``_FAILS`` a fresh dict, and ``HOME`` points at ``tmp_path`` so
``_browse_roots`` only ever offers that tree.
"""

import contextlib
import os

import flask
import pytest
from werkzeug.security import generate_password_hash
from zyg_zero import zpub_routes_cinema as MOD

pytestmark = pytest.mark.timeout(60)

SESS = 'a' * 16  # matches _HLS_ID_RE
IP = '198.51.100.7'
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 16
PW = 'open-sesame'
# One iteration: ``check_password_hash`` reads the cost from the hash, so the gate tests stay fast.
PW_HASH = generate_password_hash(PW, method='pbkdf2:sha256:1')


class _Cine:
    """Stand-in for ``zyg_zero.zpub_cinema``: every helper the routes call, answering from memory."""

    VIDEO_EXTS = {'.mkv', '.mp4'}

    def __init__(self):
        self.calls, self.logged = [], []
        self.item = self.detail = self.hls_sess = self.scan_state = None
        self.thumb = self.built_thumb = self.subtitle = self.playlist = ''
        self.start_value = 4.0
        self.board_payload, self.library = {'shelves': []}, {'items': {}, 'roots': []}
        self.hls_out, self.scan = {'session': SESS, 'offset': 0.0}, {'scan_id': 'scan-1'}
        self.prefs = {'defaults': {'audio': 'eng'}, 'shows': {'dune': {'burn': 1}}}
        self.series = {'folders': ['01. Season 1']}

    def _note(self, *row, ret=None):
        self.calls.append(row)
        return ret

    def board(self):
        return self._note('board', ret=dict(self.board_payload))

    def item_detail(self, item_id):
        return self._note('item_detail', item_id, ret=self.detail)

    def get_item(self, item_id):
        return self._note('get_item', item_id, ret=self.item)

    def thumb_path(self, item_id):
        return self.thumb

    def build_thumb(self, item):
        return self._note('build_thumb', ret=self.built_thumb)

    def stream_transcode(self, item, start, audio_id, burn):
        return self._note('stream_transcode', start, audio_id, burn, ret=iter([b'fragmented-mp4']))

    def exact_start(self, item, t, burn):
        return self._note('exact_start', t, burn, ret=self.start_value)

    def start_hls(self, item, start, audio_id, burn):
        return self._note('start_hls', start, audio_id, burn, ret=dict(self.hls_out))

    def get_hls(self, sess_id):
        return self._note('get_hls', sess_id, ret=self.hls_sess)

    def _hls_read_playlist(self, out_dir):
        return (self.playlist, 0, 0.0)

    def note_hls_segment(self, sess, index):
        self._note('note_hls_segment', index)

    def close_hls(self, sess_id):
        self._note('close_hls', sess_id)

    def subtitle_vtt(self, item, sub_id):
        return self._note('subtitle_vtt', sub_id, ret=self.subtitle)

    def shift_vtt(self, text, offset):
        return self._note('shift_vtt', offset, ret=f'{text}|shifted {offset}')

    def load_library(self):
        return self.library

    def save_library(self, lib):
        self._note('save_library', sorted(lib.get('items') or {}))

    def start_scan(self, root):
        return self._note('start_scan', root, ret=dict(self.scan))

    def scan_status(self, scan_id):
        return self._note('scan_status', scan_id, ret=self.scan_state)

    def load_prefs(self):
        return self.prefs

    def update_prefs(self, patch, show):
        return self._note('update_prefs', patch, show, ret=self.prefs)

    def show_key(self, show):
        return (show or '').strip().lower()

    def set_series_name(self, current, name):
        return self._note('set_series_name', current, name, ret=dict(self.series))


class _Entry:
    # An os.scandir entry; raises=True makes the route's is_dir probe fail.
    def __init__(self, name, raises=False):
        self.name, self._raises = name, raises

    def is_dir(self, follow_symlinks=True):
        if self._raises:
            raise OSError(f'stat refused: {self.name}')
        return False


class _OsProxy:
    # The module's os with a hostile scandir; every other attribute is the real one.
    def __init__(self, real, error=None, entries=()):
        self._real, self._error, self._entries = real, error, entries

    def __getattr__(self, key):
        return getattr(self._real, key)

    def scandir(self, path):
        if self._error is not None:
            raise self._error
        return contextlib.nullcontext(iter(self._entries))


@pytest.fixture(autouse=True)
def cine(tmp_path, monkeypatch):
    """Replace the library, the audit log, the client IP, the lockout table and the browse root."""
    fake = _Cine()
    monkeypatch.setattr(MOD, 'cine', fake)
    monkeypatch.setattr(MOD, '_zpub_log', lambda event, **kw: fake.logged.append((event, kw)))
    monkeypatch.setattr(MOD, '_client_ip', lambda: IP)
    monkeypatch.setattr(MOD, '_FAILS', {})
    monkeypatch.setenv('HOME', str(tmp_path))
    return fake


@pytest.fixture
def app():
    out = flask.Flask(__name__)
    out.config.update(TESTING=True, SECRET_KEY='cinema-cov')
    out.register_blueprint(MOD.bp)
    return out


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.fixture
def client(app):
    out = app.test_client()
    with out.session_transaction() as sess:
        sess['cinema_ok'] = True
    return out


@pytest.fixture
def video(cine, tmp_path):
    """A film that really is on disk, so the ``os.path.isfile`` guards pass. 120 s long."""
    path = tmp_path / 'dune.mkv'
    path.write_bytes(b'0123456789')
    cine.item = {'path': str(path), 'duration': 120}
    return path


@pytest.fixture
def vtt(cine, tmp_path):
    """A subtitle track on disk, with ``get_item`` answering for its film."""
    track = tmp_path / 'eng.vtt'
    track.write_text('WEBVTT\n', encoding='utf-8')
    cine.item = {'path': str(tmp_path / 'dune.mkv')}
    cine.subtitle = str(track)
    return track


# ------------------------------------------------------------------------------- password + gate
def test_password_hash_prefers_plaintext_then_hash_then_the_default(monkeypatch):
    monkeypatch.setenv('ZYG_CINEMA_PASSWORD', '  open-sesame  ')
    monkeypatch.delenv('ZYG_CINEMA_PASSWORD_HASH', raising=False)
    monkeypatch.setattr(MOD, 'generate_password_hash', lambda pw, method=None: f'gen:{pw}:{method}')
    assert MOD._password_hash() == 'gen:open-sesame:pbkdf2:sha256:600000'
    monkeypatch.setenv('ZYG_CINEMA_PASSWORD', '   ')
    monkeypatch.setenv('ZYG_CINEMA_PASSWORD_HASH', ' pbkdf2:sha256:1$abc$def ')
    assert MOD._password_hash() == 'pbkdf2:sha256:1$abc$def'
    monkeypatch.setenv('ZYG_CINEMA_PASSWORD_HASH', '')
    assert MOD._password_hash() == MOD._DEFAULT_HASH


LOCKOUT = [
    ({}, 0),  # nothing recorded yet
    ({'count': MOD._FREE_TRIES, 'last': 1.0e12}, 0),  # still inside the free tries
    ({'count': MOD._FREE_TRIES + 2, 'last': 0.0}, 0),  # the delay has long expired
]


@pytest.mark.parametrize(('rec', 'expected'), LOCKOUT)
def test_lockout_remaining_table(monkeypatch, rec, expected):
    monkeypatch.setattr(MOD, '_FAILS', {'k': dict(rec)} if rec else {})
    assert MOD._lockout_remaining('k') == expected


def test_lockout_grows_exponentially_is_capped_and_then_clears(monkeypatch):
    monkeypatch.setattr(MOD, 'time', type('T', (), {'time': staticmethod(lambda: 1000.0)}))
    MOD._FAILS['k'] = {'count': MOD._FREE_TRIES + 2, 'last': 1000.0}
    assert MOD._lockout_remaining('k') == 2**2 * 5
    MOD._FAILS['k'] = {'count': MOD._FREE_TRIES + 40, 'last': 1000.0}
    assert MOD._lockout_remaining('k') == MOD._MAX_DELAY
    MOD._clear_fails('k')
    MOD._note_fail('k')
    MOD._note_fail('k')
    assert MOD._FAILS['k'] == {'count': 2, 'last': 1000.0}
    MOD._clear_fails('k')
    assert MOD._FAILS == {}


_GATED_GET = (
    '/api/cinema/board /api/cinema/item/x1 /api/cinema/thumb/x1.jpg /api/cinema/play/x1 '
    '/api/cinema/transcode/x1 /api/cinema/seek/x1 /api/cinema/subtitle/x1/2.vtt /api/cinema/browse '
    f'/api/cinema/hls/{SESS}/index.m3u8 /api/cinema/hls/{SESS}/init.mp4 /api/cinema/scan/scan-1 /api/cinema/prefs'
).split()
_GATED_POST = (
    f'/api/cinema/hls/start/{SESS} /api/cinema/hls/{SESS}/close /api/cinema/scan '
    '/api/cinema/forget/x1 /api/cinema/prefs /api/cinema/series_name'
).split()
GATED = [('GET', p) for p in _GATED_GET] + [('POST', p) for p in _GATED_POST]


@pytest.mark.parametrize(('method', 'path'), GATED)
def test_every_library_route_is_locked_without_the_session_flag(anon, cine, method, path):
    resp = anon.open(path, method=method)
    assert resp.status_code == 403
    assert resp.get_json() == {'success': False, 'error': 'locked'}
    assert cine.calls == []


def test_unlock_rejects_a_wrong_password_then_locks_the_ip_out(anon, cine, monkeypatch):
    monkeypatch.setattr(MOD, '_PW_HASH', PW_HASH)
    for _ in range(MOD._FREE_TRIES + 1):
        resp = anon.post('/api/cinema/unlock', json={'password': 'nope'})
        assert (resp.status_code, resp.get_json()['error']) == (401, 'Incorrect password')
    # The right password no longer helps: the per-IP backoff answers first.
    locked = anon.post('/api/cinema/unlock', json={'password': PW})
    assert locked.status_code == 429
    body = locked.get_json()
    assert body['retry_after'] > 0 and 'Too many attempts' in body['error']
    assert [event for event, _ in cine.logged] == ['cinema_unlock'] * (MOD._FREE_TRIES + 1)
    assert cine.logged[0][1] == {'ip': IP, 'result': 'denied'}


def test_unlock_takes_the_password_from_a_form_body_and_sets_the_flag(anon, cine, monkeypatch):
    monkeypatch.setattr(MOD, '_PW_HASH', PW_HASH)
    assert anon.post('/api/cinema/unlock').status_code == 401  # no body at all
    ok = anon.post('/api/cinema/unlock', data={'password': f' {PW} '})
    assert ok.get_json() == {'success': True, 'redirect': '/cinema'}
    assert cine.logged[-1] == ('cinema_unlock', {'ip': IP, 'result': 'ok'})
    assert MOD._FAILS == {}  # the one failure above was cleared by the success
    assert anon.get('/api/cinema/board').status_code == 200


def test_lock_clears_the_flag_and_is_safe_when_already_locked(client, anon):
    assert client.post('/api/cinema/lock').get_json() == {'success': True}
    assert client.get('/api/cinema/board').status_code == 403
    assert anon.post('/api/cinema/lock').get_json() == {'success': True}


def test_cinema_page_redirects_home_until_unlocked(anon, client, monkeypatch):
    resp = anon.get('/cinema')
    assert (resp.status_code, resp.headers['Location']) == (302, '/')
    monkeypatch.setattr(MOD, 'render_template', lambda name: f'rendered {name}')
    assert client.get('/cinema').data == b'rendered zero_cinema.html'


# ----------------------------------------------------------------------------------- library API
def test_board_merges_the_payload_and_item_404s_before_it_has_a_detail(client, cine):
    cine.board_payload = {'shelves': [{'title': 'Recent'}], 'count': 1}
    assert client.get('/api/cinema/board').get_json() == {'success': True, 'shelves': [{'title': 'Recent'}], 'count': 1}
    assert client.get('/api/cinema/item/x1').status_code == 404
    cine.detail = {'id': 'x1', 'title': 'Dune'}
    assert client.get('/api/cinema/item/x1').get_json() == {'success': True, 'item': cine.detail}


def test_thumb_404s_without_an_item_a_file_or_a_build(client, cine, tmp_path):
    assert client.get('/api/cinema/thumb/x1.jpg').status_code == 404  # no item
    cine.item = {'path': str(tmp_path / 'dune.mkv')}
    cine.thumb = str(tmp_path / 'missing.jpg')
    assert client.get('/api/cinema/thumb/x1.jpg').status_code == 404  # build_thumb → ''
    assert ('build_thumb',) in cine.calls
    cine.built_thumb = str(tmp_path / 'still-missing.jpg')
    assert client.get('/api/cinema/thumb/x1.jpg').status_code == 404  # built, but not on disk


@pytest.mark.parametrize('prebuilt', [True, False])
def test_thumb_serves_a_cached_or_freshly_built_jpeg(client, cine, tmp_path, prebuilt):
    made = tmp_path / 'thumb.jpg'
    made.write_bytes(JPEG)
    cine.item = {'path': str(tmp_path / 'dune.mkv')}
    cine.thumb = str(made) if prebuilt else str(tmp_path / 'absent.jpg')
    cine.built_thumb = '' if prebuilt else str(made)
    resp = client.get('/api/cinema/thumb/x1.jpg')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'image/jpeg', JPEG)
    assert resp.headers['Cache-Control'] == 'private, max-age=86400'


# -------------------------------------------------------------------------------------- playback
@pytest.mark.parametrize('route', ['play', 'transcode'])
def test_play_and_transcode_404_without_an_item_or_a_file(client, cine, tmp_path, route):
    assert client.get(f'/api/cinema/{route}/x1').status_code == 404
    cine.item = {'path': str(tmp_path / 'gone.mkv')}
    assert client.get(f'/api/cinema/{route}/x1').status_code == 404
    cine.item = {}  # no path key at all
    assert client.get(f'/api/cinema/{route}/x1').status_code == 404


@pytest.mark.parametrize('name', ['dune.mp4', 'dune.zyg'])  # known extension, then the mime fallback
def test_play_streams_the_original_file_with_byte_ranges(client, cine, tmp_path, name):
    film = tmp_path / name
    film.write_bytes(b'0123456789')
    cine.item = {'path': str(film)}
    resp = client.get('/api/cinema/play/x1')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'video/mp4', b'0123456789')
    assert resp.headers['Accept-Ranges'] == 'bytes'
    ranged = client.get('/api/cinema/play/x1', headers={'Range': 'bytes=2-4'})
    assert (ranged.status_code, ranged.data) == (206, b'234')


TIMES = [
    ('?t=12.5', 12.5),  # inside the duration
    ('?t=abc', 0.0),  # unparseable
    ('?t=-9', 0.0),  # clamped up to zero
    ('?t=600', 119.0),  # clamped down to duration - 1
    ('', 0.0),  # absent
]


@pytest.mark.parametrize(('query', 'expected'), TIMES)
def test_transcode_normalises_the_start_time(client, cine, video, query, expected):
    resp = client.get(f'/api/cinema/transcode/x1{query}')
    assert (resp.status_code, resp.data) == (200, b'fragmented-mp4')
    assert (resp.headers['Cache-Control'], resp.headers['Accept-Ranges']) == ('no-store', 'none')
    assert ('stream_transcode', expected, None, '') in cine.calls


def test_transcode_passes_the_audio_track_and_the_burn_choice(client, cine, video):
    cine.item['duration'] = 0  # an unknown duration clamps nothing
    client.get('/api/cinema/transcode/x1?t=3&a=2&burn=%20sub3%20')
    assert ('stream_transcode', 3.0, '2', 'sub3') in cine.calls


@pytest.mark.parametrize(('query', 'expected'), TIMES)
def test_seek_404s_for_an_unknown_item_then_reports_the_real_keyframe_start(client, cine, query, expected):
    missing = client.get('/api/cinema/seek/x1')
    assert (missing.status_code, missing.get_json()['error']) == (404, 'Not found')
    cine.item = {'duration': 120}
    cine.start_value = 3.70049
    body = client.get(f'/api/cinema/seek/x1{query}').get_json()
    assert body == {'success': True, 'requested': expected, 'start': 3.7}
    assert ('exact_start', expected, '') in cine.calls


# ------------------------------------------------------------------------------------------- HLS
def test_hls_start_404s_then_resolves_the_start_then_reports_a_failure_as_503(client, cine, video):
    cine.item, cine.start_value = None, 7.5
    assert client.post(f'/api/cinema/hls/start/{SESS}').status_code == 404  # no item
    cine.item = {'path': str(video.parent / 'gone.mkv')}
    assert client.post(f'/api/cinema/hls/start/{SESS}').status_code == 404  # not on disk
    cine.item = {'path': str(video), 'duration': 120}
    body = client.post(f'/api/cinema/hls/start/{SESS}?t=600&a=1&burn=sub2').get_json()
    assert body == {'success': True, 'session': SESS, 'offset': 0.0}
    assert ('exact_start', 119.0, 'sub2') in cine.calls  # t clamped to duration - 1
    assert ('start_hls', 7.5, '1', 'sub2') in cine.calls
    cine.hls_out = {'error': 'low_disk', 'free_gb': 0.4}
    resp = client.post(f'/api/cinema/hls/start/{SESS}?t=bad')
    assert resp.status_code == 503
    assert resp.get_json() == {'success': False, 'error': 'low_disk', 'free_gb': 0.4}
    assert ('exact_start', 0.0, '') in cine.calls  # unparseable t → 0.0


def test_hls_playlist_404s_on_a_bad_id_410s_when_reaped_then_serves_the_manifest(client, cine, tmp_path):
    assert client.get('/api/cinema/hls/not-hex/index.m3u8').status_code == 404
    assert client.get(f'/api/cinema/hls/{SESS}/index.m3u8').status_code == 410
    cine.hls_sess = {'dir': str(tmp_path)}
    assert client.get(f'/api/cinema/hls/{SESS}/index.m3u8').status_code == 404  # nothing written yet
    cine.playlist = '#EXTM3U\n#EXT-X-TARGETDURATION:4\n'
    resp = client.get(f'/api/cinema/hls/{SESS}/index.m3u8')
    assert (resp.status_code, resp.mimetype) == (200, 'application/vnd.apple.mpegurl')
    assert (resp.headers['Cache-Control'], resp.data.decode()) == ('no-store', cine.playlist)


BAD_SEGMENTS = [(SESS, 'seg1.m4s'), (SESS, '../../etc/passwd'), (SESS, 'init.mp5'), ('zz', 'init.mp4')]


@pytest.mark.parametrize(('sess_id', 'name'), BAD_SEGMENTS)
def test_hls_segment_404s_on_anything_ffmpeg_would_not_have_written(client, cine, sess_id, name):
    cine.hls_sess = {'dir': '/nonexistent'}
    assert client.get(f'/api/cinema/hls/{sess_id}/{name}').status_code == 404


@pytest.mark.parametrize(('name', 'noted'), [('init.mp4', False), ('seg00007.m4s', True)])
def test_hls_segment_410s_404s_then_serves_the_file_and_notes_media_segments(client, cine, tmp_path, name, noted):
    assert client.get(f'/api/cinema/hls/{SESS}/{name}').status_code == 410  # session reaped
    cine.hls_sess = {'dir': str(tmp_path)}
    assert client.get(f'/api/cinema/hls/{SESS}/{name}').status_code == 404  # ffmpeg has not written it
    (tmp_path / name).write_bytes(b'moof')
    resp = client.get(f'/api/cinema/hls/{SESS}/{name}')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'video/mp4', b'moof')
    assert resp.headers['Cache-Control'] == 'private, max-age=3600'
    assert (('note_hls_segment', 7) in cine.calls) is noted


def test_hls_close_ignores_a_bogus_id_and_closes_a_real_one(client, cine):
    assert client.post('/api/cinema/hls/not-hex/close').get_json() == {'success': True}
    assert cine.calls == []
    assert client.post(f'/api/cinema/hls/{SESS}/close').get_json() == {'success': True}
    assert cine.calls == [('close_hls', SESS)]


# ------------------------------------------------------------------------------------- subtitles
def test_subtitle_404s_without_an_item_a_track_or_a_file(client, cine, tmp_path):
    assert client.get('/api/cinema/subtitle/x1/2.vtt').status_code == 404  # no item
    cine.item = {'path': str(tmp_path / 'dune.mkv')}
    assert client.get('/api/cinema/subtitle/x1/2.vtt').status_code == 404  # subtitle_vtt → ''
    cine.subtitle = str(tmp_path / 'absent.vtt')
    assert client.get('/api/cinema/subtitle/x1/2.vtt').status_code == 404  # not on disk
    assert ('subtitle_vtt', '2') in cine.calls


@pytest.mark.parametrize('query', ['', '?shift=0', '?shift=junk'])
def test_subtitle_serves_the_file_verbatim_without_a_usable_shift(client, vtt, query):
    resp = client.get(f'/api/cinema/subtitle/x1/2.vtt{query}')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'text/vtt', b'WEBVTT\n')
    assert resp.headers['Cache-Control'] == 'private, max-age=3600'


def test_subtitle_rebases_the_cues_then_404s_when_the_file_cannot_be_read(client, cine, vtt, monkeypatch):
    resp = client.get('/api/cinema/subtitle/x1/2.vtt?shift=-4.25')
    assert (resp.status_code, resp.mimetype, resp.data) == (200, 'text/vtt', b'WEBVTT\n|shifted -4.25')
    assert resp.headers['Cache-Control'] == 'no-store'
    assert ('shift_vtt', -4.25) in cine.calls

    def _refuse(*_a, **_kw):
        raise OSError('read refused')

    # A module global named ``open`` shadows the builtin the body resolves to.
    monkeypatch.setattr(MOD, 'open', _refuse, raising=False)
    assert client.get('/api/cinema/subtitle/x1/2.vtt?shift=3').status_code == 404


# ------------------------------------------------------------------------------ roots + browsing
def test_browse_offers_the_roots_dedupes_them_and_adds_media_and_mnt(client, cine, tmp_path, monkeypatch):
    body = client.get('/api/cinema/browse').get_json()
    assert (body['success'], body['path'], body['parent']) == (True, '', None)
    assert body['roots'][0] == str(tmp_path)
    assert {'name': tmp_path.name, 'path': str(tmp_path)} in body['dirs']
    extra = tmp_path / 'nas'
    cine.library = {'roots': [str(tmp_path), str(extra), str(extra)]}
    roots = MOD._browse_roots()
    assert (roots[0], roots.count(str(tmp_path)), roots.count(str(extra))) == (str(tmp_path), 1, 1)
    # Forced isdir, so the /media + /mnt branch does not depend on the runner's filesystem.
    monkeypatch.setattr(MOD.os.path, 'isdir', lambda path: True)
    assert MOD._browse_roots()[1:3] == ['/media', '/mnt']


def test_within_roots_accepts_children_of_home_and_survives_a_broken_path(monkeypatch, tmp_path):
    (tmp_path / 'movies').mkdir()
    assert MOD._within_roots(str(tmp_path)) is True
    assert MOD._within_roots(str(tmp_path / 'movies')) is True
    assert MOD._within_roots(str(tmp_path.parent / 'definitely-elsewhere')) is False

    def _refuse(_path):
        raise OSError('realpath refused')

    monkeypatch.setattr(MOD.os.path, 'realpath', _refuse)
    assert MOD._within_roots(str(tmp_path)) is False


@pytest.mark.parametrize('raw', ['/etc', '~/absent-folder'])
def test_browse_refuses_a_folder_outside_the_roots_or_missing(client, raw):
    resp = client.get('/api/cinema/browse', query_string={'path': f'  {raw}  '})
    assert (resp.status_code, resp.get_json()['error']) == (400, 'Folder not accessible')


def test_browse_lists_sub_folders_counts_videos_hides_dotfiles_and_stops_at_the_root(client, tmp_path):
    films = tmp_path / 'films'
    films.mkdir()
    for name in ('Zeta', 'alpha', '.hidden'):
        (films / name).mkdir()
    (films / 'dune.mkv').write_bytes(b'x')
    (films / 'notes.txt').write_text('x', encoding='utf-8')
    body = client.get('/api/cinema/browse', query_string={'path': str(films)}).get_json()
    assert [d['name'] for d in body['dirs']] == ['alpha', 'Zeta']
    assert (body['videos'], body['path'], body['parent']) == (1, str(films), str(tmp_path))
    top = client.get('/api/cinema/browse', query_string={'path': str(tmp_path)}).get_json()
    assert top['parent'] is None  # the parent of HOME is outside every root


def test_browse_skips_unstatable_entries_and_reports_a_denied_folder(client, tmp_path, monkeypatch):
    films = tmp_path / 'films'
    films.mkdir()
    monkeypatch.setattr(MOD, 'os', _OsProxy(os, entries=[_Entry('weird', raises=True), _Entry('clip.mp4')]))
    body = client.get('/api/cinema/browse', query_string={'path': str(films)}).get_json()
    assert (body['dirs'], body['videos']) == ([], 1)
    monkeypatch.setattr(MOD, 'os', _OsProxy(os, error=PermissionError('nope')))
    resp = client.get('/api/cinema/browse', query_string={'path': str(films)})
    assert (resp.status_code, resp.get_json()['error']) == (403, 'Permission denied')


# -------------------------------------------------------------------------------------- scanning
def test_scan_needs_a_folder_inside_the_roots_then_starts_and_is_audited(client, cine, tmp_path):
    films = tmp_path / 'films'
    films.mkdir()
    assert client.post('/api/cinema/scan', json={}).get_json()['error'] == 'No folder given'
    outside = client.post('/api/cinema/scan', json={'path': '/etc'})
    assert (outside.status_code, outside.get_json()['error']) == (400, 'Folder is outside the allowed roots')
    assert cine.calls == []
    cine.scan = {'error': 'already scanning'}
    refused = client.post('/api/cinema/scan', data={'path': str(films)})
    assert (refused.status_code, refused.get_json()) == (400, {'success': False, 'error': 'already scanning'})
    assert cine.logged == []
    cine.scan = {'scan_id': 'scan-1'}
    started = client.post('/api/cinema/scan', json={'path': '~/films'}).get_json()
    assert started == {'success': True, 'scan_id': 'scan-1'}
    assert ('start_scan', str(films)) in cine.calls
    assert cine.logged == [('cinema_scan', {'ip': IP, 'path': str(films)})]


def test_scan_status_and_forget_404_on_unknown_ids_then_answer(client, cine):
    status = client.get('/api/cinema/scan/scan-1')
    assert (status.status_code, status.get_json()['error']) == (404, 'Unknown scan')
    cine.scan_state = {'done': 3, 'total': 9}
    assert client.get('/api/cinema/scan/scan-1').get_json() == {'success': True, 'done': 3, 'total': 9}
    gone = client.post('/api/cinema/forget/x1')
    assert (gone.status_code, gone.get_json()['error']) == (404, 'Not found')
    cine.library = {'items': {'x1': {'title': 'Dune'}, 'x2': {}}}
    assert client.post('/api/cinema/forget/x1').get_json() == {'success': True}
    assert ('save_library', ['x2']) in cine.calls
    assert 'x1' not in cine.library['items']


# ----------------------------------------------------------------------------------------- prefs
def test_prefs_reads_the_defaults_and_overrides_then_patches_them(client, cine):
    assert client.get('/api/cinema/prefs').get_json() == {
        'success': True,
        'defaults': {'audio': 'eng'},
        'shows': {'dune': {'burn': 1}},
    }
    assert client.post('/api/cinema/prefs', json={'prefs': {'audio': 'fra'}}).get_json() == {
        'success': True,
        'show': '',
        'defaults': {'audio': 'eng'},
        'overrides': {},
    }
    assert ('update_prefs', {'audio': 'fra'}, '') in cine.calls
    body = client.post('/api/cinema/prefs', json={'prefs': {'burn': None}, 'show': ' Dune '}).get_json()
    assert (body['show'], body['overrides']) == ('dune', {'burn': 1})
    assert ('update_prefs', {'burn': None}, ' Dune ') in cine.calls
    cine.prefs = {}  # a library with nothing stored yet still answers both keys
    assert client.get('/api/cinema/prefs').get_json() == {'success': True, 'defaults': {}, 'shows': {}}


@pytest.mark.parametrize('body', [{}, {'prefs': 'eng'}, {'prefs': None}])
def test_prefs_save_refuses_a_patch_that_is_not_an_object(client, cine, body):
    resp = client.post('/api/cinema/prefs', json=body)
    assert (resp.status_code, resp.get_json()['error']) == (400, 'prefs must be an object')
    assert cine.calls == []


def test_series_name_needs_a_name_404s_on_an_unknown_one_then_renames_and_audits(client, cine):
    resp = client.post('/api/cinema/series_name', json={'name': 'Sandman'})
    assert (resp.status_code, resp.get_json()['error']) == (400, 'Which series?')
    assert cine.calls == []
    cine.series = {'error': 'no such folder'}
    unknown = client.post('/api/cinema/series_name', json={'show': '01. Season 1'})
    assert (unknown.status_code, unknown.get_json()) == (404, {'success': False, 'error': 'no such folder'})
    assert cine.logged == []
    cine.series = {'folders': ['01. Season 1']}
    body = client.post('/api/cinema/series_name', json={'show': ' 01. Season 1 ', 'name': ' Sandman '}).get_json()
    assert body == {'success': True, 'folders': ['01. Season 1']}
    assert ('set_series_name', '01. Season 1', 'Sandman') in cine.calls
    assert cine.logged == [('cinema_series_named', {'ip': IP, 'was': '01. Season 1', 'now': 'Sandman', 'folders': 1})]
