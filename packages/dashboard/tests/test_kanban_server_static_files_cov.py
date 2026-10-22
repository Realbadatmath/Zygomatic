# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for :mod:`zyg_dashboard.kanban_server.static_files`.

The module is a handler mixin, not a Flask blueprint: every method wants the
``BaseHTTPRequestHandler`` surface plus the sibling mixins' ``_send_ranged``
and ``translate_path``. ``_Rec``/``_Handler`` supply exactly that and record
what was sent, so every route runs offline against files under tmp_path.
"""

import io
import os
import json
import gzip
import builtins

import pytest

import zyg_dashboard.kanban_server.static_files as M


class _Rec:
    """Everything the mixin inherits from its siblings and the stdlib."""

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs

    def end_headers(self):
        self.ended = True

    def translate_path(self, path):
        return self.tp

    def _send_ranged(self, fp, ctype, cache=None, attach=None):
        self.ranged = {'fp': fp, 'ctype': ctype, 'cache': cache, 'attach': attach}
        return 'ranged'

    def address_string(self):
        return '10.0.0.1'


class _Handler(M._StaticFilesMixin, _Rec):
    def __init__(self, path='/', headers=None, wfile=None, tp=''):
        self.path = path
        self.headers = {} if headers is None else headers
        self.wfile = io.BytesIO() if wfile is None else wfile
        self.tp = tp
        self.code = None
        self.hdrs = {}
        self.ended = False
        self.errors = []
        self.ranged = None

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.hdrs[key] = value

    def send_error(self, code, *a, **kw):
        self.errors.append(code)
        self.code = code


class _Boom(io.BytesIO):
    """A wfile whose write dies the way a closed browser tab does."""

    def __init__(self, exc=BrokenPipeError):
        super().__init__()
        self.exc = exc

    def write(self, data):
        raise self.exc('client went away')


def _mk(**kw):
    return _Handler(**kw)


def _raise_open_for(monkeypatch, bad):
    """Make open() fail for one path only (an unreadable file on disk)."""
    real = builtins.open

    def fake(p, *a, **kw):
        if isinstance(p, (str, bytes, os.PathLike)) and os.fspath(p) == bad:
            raise OSError('unreadable')
        return real(p, *a, **kw)

    monkeypatch.setattr(builtins, 'open', fake)


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch):
    """Never share the process-wide memo/gzip caches between tests."""
    monkeypatch.setattr(M, '_JSON_MEMO', {})
    monkeypatch.setattr(M, '_STATIC_GZ', {})


@pytest.fixture
def char_tree(tmp_path, monkeypatch):
    """One character directory with a cells/ picture in it."""
    cells = tmp_path / 'chars' / 'ada' / 'contact_sheet' / 'cells'
    cells.mkdir(parents=True)
    (cells / 'front.png').write_bytes(b'\x89PNG' + b'0' * 32)
    monkeypatch.setattr(M, '_safe_char_dir', lambda cid: str(cells.parents[1]) if cid == 'ada' else None)
    monkeypatch.setattr(M, '_is_medusa_char', lambda cid, cdir, medusa_ids=None: cid == 'gorgon')
    monkeypatch.setattr(M, '_medusa_still_path', lambda name: None if name == 'ghost.png' else str(cells / 'front.png'))
    return cells.parents[1]


@pytest.fixture
def media_roots(tmp_path, monkeypatch):
    """The default output root and one named media root, each with a clip."""
    out, dout = tmp_path / 'output', tmp_path / 'data_output'
    for d in (out, dout):
        (d / 'clips').mkdir(parents=True)
        (d / 'clips' / 'shot.mp4').write_bytes(b'MP4')
        (d / 'clips' / 'shot.png').write_bytes(b'\x89PNG')
    reg = {'clips/shot.mp4': {'start': 3.0, 'end': 6.0}, 'clips/shot.png': {'start': 0, 'end': 1}}
    monkeypatch.setattr(M, '_OUTPUT_ROOT', str(out))
    monkeypatch.setattr(M, '_MEDIA_ROOTS', {'dout': str(dout)})
    monkeypatch.setattr(M, '_preview_registry', lambda: reg)
    return out, dout


class _FakeAlib:
    def __init__(self, root):
        self._root = root
        self._CATEGORIES = {'foley': {'kind': 'audio'}, 'plates': {'kind': 'video'}}

    def _audio_dir(self, cat):
        return str(self._root)


class _FakeVfxa:
    def __init__(self, libs):
        self.LIBS = str(libs)
        self.CATEGORIES = {'smoke': {}}


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    """The audio and VFX libraries, one registered file each."""
    audio, vfx = tmp_path / 'audio' / 'foley', tmp_path / 'vfx_libs' / 'smoke'
    audio.mkdir(parents=True)
    vfx.mkdir(parents=True)
    (audio / 'door.wav').write_bytes(b'RIFFwav')
    (vfx / 'plate.mp4').write_bytes(b'MP4plate')
    monkeypatch.setattr(M, '_alib', lambda: _FakeAlib(audio))
    monkeypatch.setattr(M, '_vfxa', lambda: _FakeVfxa(vfx.parent))
    return audio, vfx


def test_the_handler_serves_out_of_here_by_default():
    h = _Handler.__new__(_Handler)
    M._StaticFilesMixin.__init__(h, 'sock', 'addr')
    assert h.init_kwargs == {'directory': M.HERE}


@pytest.mark.parametrize(
    'path, cached',
    [('/kanban.html', False), ('/kanban_main.js?v=9', False), ('/style.css', False), ('/logo.png', True)],
)
def test_script_and_page_assets_are_sent_no_cache(path, cached):
    h = _mk(path=path)
    h.end_headers()
    assert h.ended is True
    assert ('Cache-Control' in h.hdrs) is (not cached)


def test_the_access_log_names_the_peer(caplog):
    with caplog.at_level('INFO', logger=M._zyg_log.name):
        _mk().log_message('%s %s', 'GET', '/kanban.html')
    assert '10.0.0.1 - GET /kanban.html' in caplog.text


# ── _send_json ──────────────────────────────────────────────────────────────
def test_a_payload_is_sent_plain_with_an_etag_under_its_own_code():
    h = _mk()
    h._send_json({'ok': True}, code=404)
    assert (h.code, h.hdrs['Content-Type'], h.hdrs['Cache-Control']) == (404, 'application/json', 'no-cache')
    assert h.hdrs['ETag'].startswith('"')
    assert 'Content-Encoding' not in h.hdrs
    assert json.loads(h.wfile.getvalue()) == {'ok': True}
    assert h.hdrs['Content-Length'] == str(len(h.wfile.getvalue()))


def test_the_same_object_is_serialised_once_under_a_memo_key():
    payload = {'rows': list(range(20))}
    first = _mk()
    first._send_json(payload, memo_key='inst')
    assert M._JSON_MEMO['inst'][0] is payload
    second = _mk()
    second._send_json(payload, memo_key='inst')
    assert second.hdrs['ETag'] == first.hdrs['ETag']
    assert second.wfile.getvalue() == first.wfile.getvalue()
    _mk()._send_json({'rows': []}, memo_key='inst')
    assert M._JSON_MEMO['inst'][0] == {'rows': []}


def test_a_full_memo_is_cleared_rather_than_grown():
    for i in range(M._JSON_GZ_MAX):
        _mk()._send_json({'i': i}, memo_key=f'k{i}')
    assert len(M._JSON_MEMO) == M._JSON_GZ_MAX
    _mk()._send_json({'i': 'last'}, memo_key='overflow')
    assert list(M._JSON_MEMO) == ['overflow']


def test_a_poll_that_already_holds_the_payload_gets_a_304():
    probe = _mk()
    probe._send_json({'ok': True})
    h = _mk(headers={'If-None-Match': probe.hdrs['ETag']})
    h._send_json({'ok': True})
    assert (h.code, h.hdrs['Content-Length'], h.wfile.getvalue()) == (304, '0', b'')
    on_error = _mk(headers={'If-None-Match': probe.hdrs['ETag']})
    on_error._send_json({'ok': True}, code=500)
    assert on_error.code == 500
    assert on_error.wfile.getvalue()


def test_a_big_payload_is_gzipped_only_for_a_client_that_asks():
    big = {'rows': ['x' * 40 for _ in range(200)]}
    h = _mk(headers={'Accept-Encoding': 'gzip, deflate'})
    h._send_json(big)
    assert (h.hdrs['Content-Encoding'], h.hdrs['Vary']) == ('gzip', 'Accept-Encoding')
    assert len(h.wfile.getvalue()) < M._JSON_GZ_MIN
    assert json.loads(gzip.decompress(h.wfile.getvalue())) == big
    plain = _mk()
    plain._send_json(big)
    assert 'Content-Encoding' not in plain.hdrs


def test_a_client_that_hangs_up_mid_json_is_only_logged():
    h = _mk(wfile=_Boom())
    h._send_json({'ok': True})
    assert h.code == 200


@pytest.mark.parametrize(
    'path, allowed',
    [
        ('/kanban.html', True),
        ('/js/kanban_main.js', True),
        ('/img/logo.png', True),
        ('/fonts/inter.woff2', True),
        ('/kanban_server.py', False),
        ('/agent_configurations.json', False),
        ('/.env', False),
        ('/.bak_20260905/kanban.html', False),
        ('/sub/.hidden/x.js', False),
        ('/inspection.html.bak-perf-20260905', False),
        ('/', False),
    ],
)
def test_only_six_kinds_of_asset_leave_the_source_tree(path, allowed):
    assert _mk()._static_allowed(path) is allowed


def test_a_directory_url_never_lists_anything():
    h = _mk(path='/')
    assert h.list_directory('/tmp') is None
    assert h.errors == [404]


def test_what_the_gzip_path_leaves_to_the_stdlib_handler(tmp_path, monkeypatch):
    gz = {'Accept-Encoding': 'gzip'}
    assert _mk(path='/logo.png', headers=gz)._serve_static_gz('/logo.png') is False
    assert _mk(path='/kanban.html')._serve_static_gz('/kanban.html') is False
    assert _mk(path='/g.html', headers=gz, tp=str(tmp_path / 'g.html'))._serve_static_gz('/g.html') is False
    (tmp_path / 'assets').mkdir()
    adir = _mk(path='/assets', headers=gz, tp=str(tmp_path / 'assets'))
    assert adir._serve_static_gz('/assets.html') is False
    fp = tmp_path / 'page.html'
    fp.write_text('<p>hi</p>')
    _raise_open_for(monkeypatch, str(fp))
    assert _mk(path='/page.html', headers=gz, tp=str(fp))._serve_static_gz('/page.html') is False


def test_a_text_asset_is_compressed_once_cached_and_revalidated(tmp_path):
    fp = tmp_path / 'inspection.html'
    body = '<html>' + 'y' * 5000 + '</html>'
    fp.write_text(body)
    gz = {'Accept-Encoding': 'gzip'}
    first = _mk(path='/inspection.html', headers=gz, tp=str(fp))
    assert first._serve_static_gz('/inspection.html') is True
    assert first.code == 200
    assert first.hdrs['Content-Type'] == M._STATIC_GZ_TYPES['.html']
    assert (first.hdrs['Content-Encoding'], first.hdrs['Vary']) == ('gzip', 'Accept-Encoding')
    assert gzip.decompress(first.wfile.getvalue()).decode() == body
    assert list(M._STATIC_GZ) == [str(fp)]

    second = _mk(path='/inspection.html', headers=gz, tp=str(fp))
    assert second._serve_static_gz('/inspection.html') is True
    assert second.wfile.getvalue() == first.wfile.getvalue()

    stale = M._STATIC_GZ[str(fp)]
    os.utime(fp, (1_000_000, 1_000_000))
    third = _mk(path='/inspection.html', headers=gz, tp=str(fp))
    third._serve_static_gz('/inspection.html')
    assert M._STATIC_GZ[str(fp)][0] != stale[0]

    held = _mk(path='/inspection.html', headers={**gz, 'If-None-Match': third.hdrs['ETag']}, tp=str(fp))
    assert held._serve_static_gz('/inspection.html') is True
    assert (held.code, held.wfile.getvalue()) == (304, b'')


def test_a_client_that_hangs_up_mid_gzip_is_only_logged(tmp_path):
    fp = tmp_path / 'x.svg'
    fp.write_text('<svg/>')
    h = _mk(path='/x.svg', headers={'Accept-Encoding': 'gzip'}, wfile=_Boom(ConnectionResetError), tp=str(fp))
    assert h._serve_static_gz('/x.svg') is True


def test_the_query_string_is_flattened_to_one_value_per_key():
    assert _mk(path='/i?id=ada&cat=cells&name=a.png&name=b.png')._query() == {
        'id': 'ada',
        'cat': 'cells',
        'name': 'a.png',
    }
    assert _mk(path='/inspect/img')._query() == {}


@pytest.mark.parametrize(
    'method, query, code',
    [
        ('_serve_image', 'id=nobody&cat=cells&name=front.png', 404),
        ('_serve_image', 'id=ada&cat=nosuch&name=front.png', 404),
        ('_serve_image', 'id=ada&cat=cells', 404),
        ('_serve_image', 'id=ada&cat=cells&name=../../etc/passwd', 404),
        ('_serve_image', 'id=ada&cat=cells&name=front.png&scope=medusa', 404),
        ('_serve_medusa_img', 'name=front.png', 404),
        ('_serve_medusa_img', 'scope=medusa&name=ghost.png', 404),
        ('_serve_thumb', 'path=clips/ghost.mp4', 404),
        ('_serve_preview', 'path=clips/other.mp4', 404),
        ('_serve_preview', 'path=clips/shot.png', 404),
        ('_serve_download', 'path=clips/ghost.mp4', 404),
        ('_serve_download', 'path=clips/shot.mp4&subs=burn', 404),
        ('_serve_sfx', 'cat=nosuch&f=door.wav', 404),
        ('_serve_sfx', 'cat=plates&f=door.wav', 404),
        ('_serve_sfx', 'cat=foley', 404),
        ('_serve_sfx', 'cat=foley&f=sub%2Fdoor.wav', 404),
        ('_serve_sfx', 'cat=foley&f=.hidden.wav', 404),
        ('_serve_sfx', 'cat=foley&f=door.exe', 404),
        ('_serve_sfx', 'cat=foley&f=missing.wav', 404),
        ('_serve_vfx_asset', 'cat=nosuch&f=plate.mp4', 404),
        ('_serve_vfx_asset', 'cat=smoke', 404),
        ('_serve_vfx_asset', 'cat=smoke&f=sub%2Fplate.mp4', 404),
        ('_serve_vfx_asset', 'cat=smoke&f=.hidden.mp4', 404),
        ('_serve_vfx_asset', 'cat=smoke&f=plate.vdb', 404),
        ('_serve_vfx_asset', 'cat=smoke&f=missing.mp4', 404),
    ],
)
def test_a_request_that_fails_a_guard_is_refused(char_tree, media_roots, libraries, method, query, code):
    h = _mk(path='/r?' + query)
    getattr(h, method)()
    assert h.errors == [code]


def test_the_library_routes_are_503_without_their_service(monkeypatch):
    monkeypatch.setattr(M, '_alib', lambda: None)
    monkeypatch.setattr(M, '_vfxa', lambda: None)
    sfx, vfx = _mk(path='/s?cat=foley&f=door.wav'), _mk(path='/v?cat=smoke&f=plate.mp4')
    sfx._serve_sfx()
    vfx._serve_vfx_asset()
    assert (sfx.errors, vfx.errors) == ([503], [503])


def test_a_symlink_out_of_an_allowed_root_is_refused(char_tree, media_roots, libraries, tmp_path):
    out, audio, vfx = media_roots[0], libraries[0], libraries[1]
    (tmp_path / 'master').write_bytes(b'secret')
    for link in (char_tree / 'contact_sheet' / 'cells' / 'escape.png', out / 'clips' / 'link.mp4'):
        link.symlink_to(tmp_path / 'master')
    (audio / 'escape.wav').symlink_to(tmp_path / 'master')
    (vfx / 'escape.mp4').symlink_to(tmp_path / 'master')
    img = _mk(path='/i?id=ada&cat=cells&name=escape.png')
    img._serve_image()
    sfx = _mk(path='/s?cat=foley&f=escape.wav')
    sfx._serve_sfx()
    vfx_h = _mk(path='/v?cat=smoke&f=escape.mp4')
    vfx_h._serve_vfx_asset()
    assert (img.errors, sfx.errors, vfx_h.errors) == ([404], [404], [404])
    assert _mk()._resolve_media_path('clips/link.mp4') is None


def test_a_known_picture_and_medusa_still_are_served_in_full(char_tree):
    for path in ('/i?id=ada&cat=cells&name=front.png', '/m?scope=medusa&name=front.png'):
        h = _mk(path=path)
        h._serve_image() if 'id=ada' in path else h._serve_medusa_img()
        assert h.code == 200
        assert h.hdrs['Content-Type'] == 'image/png'
        assert h.hdrs['Cache-Control'] == 'public, max-age=30'
        assert h.wfile.getvalue() == (char_tree / 'contact_sheet' / 'cells' / 'front.png').read_bytes()


def test_a_registered_sample_and_plate_are_streamed(libraries):
    audio, vfx = libraries
    sfx = _mk(path='/sfx/file?cat=foley&f=door.wav')
    assert sfx._serve_sfx() == 'ranged'
    assert sfx.ranged == {'fp': str(audio / 'door.wav'), 'ctype': 'audio/wav', 'cache': None, 'attach': None}
    plate = _mk(path='/vfx/file?cat=smoke&f=plate.mp4')
    assert plate._serve_vfx_asset() == 'ranged'
    expect = {'fp': str(vfx / 'plate.mp4'), 'ctype': 'video/mp4', 'cache': 'public, max-age=3600', 'attach': None}
    assert plate.ranged == expect


# ── _send_image_thumb_or_full ───────────────────────────────────────────────
def test_a_grid_card_gets_a_jpeg_thumb_built_once(tmp_path, monkeypatch):
    src = tmp_path / 'big.png'
    src.write_bytes(b'\x89PNG' + b'0' * 64)
    thumb = tmp_path / 'thumbs' / 'big.jpg'
    thumb.parent.mkdir()

    def make(fp, dst, w):
        assert w == M._IMG_THUMB_W
        open(dst, 'wb').write(b'JPEGDATA')
        return True

    monkeypatch.setattr(M, '_img_thumb_path', lambda fp, mtime, w: str(thumb))
    monkeypatch.setattr(M, '_make_img_thumb', make)
    h = _mk()
    h._send_image_thumb_or_full(str(src), True)
    assert (h.code, h.hdrs['Content-Type']) == (200, 'image/jpeg')
    assert h.hdrs['Cache-Control'] == 'public, max-age=3600'
    assert h.wfile.getvalue() == b'JPEGDATA'
    monkeypatch.setattr(M, '_make_img_thumb', lambda *a: pytest.fail('must not rebuild an existing thumb'))
    again = _mk()
    again._send_image_thumb_or_full(str(src), True)
    assert again.wfile.getvalue() == b'JPEGDATA'


def test_a_thumb_that_cannot_be_built_or_read_falls_back_to_the_original(tmp_path, monkeypatch):
    src = tmp_path / 'big.jpg'
    src.write_bytes(b'JFIForiginal')
    monkeypatch.setattr(M, '_img_thumb_path', lambda fp, mtime, w: str(tmp_path / 'nope.jpg'))
    monkeypatch.setattr(M, '_make_img_thumb', lambda fp, dst, w: False)
    unbuilt = _mk()
    unbuilt._send_image_thumb_or_full(str(src), True)
    assert (unbuilt.code, unbuilt.hdrs['Cache-Control']) == (200, 'public, max-age=30')
    assert unbuilt.hdrs['Content-Type'] == 'image/jpeg'
    assert unbuilt.wfile.getvalue() == b'JFIForiginal'

    locked = tmp_path / 'locked.jpg'
    locked.write_bytes(b'JPEG')
    monkeypatch.setattr(M, '_img_thumb_path', lambda fp, mtime, w: str(locked))
    _raise_open_for(monkeypatch, str(locked))
    unread = _mk()
    unread._send_image_thumb_or_full(str(src), True)
    assert unread.wfile.getvalue() == b'JFIForiginal'


def test_a_vanished_source_404s_and_an_odd_type_is_octet_stream(tmp_path):
    gone = _mk()
    gone._send_image_thumb_or_full(str(tmp_path / 'gone.png'), True)
    assert gone.errors == [404]
    src = tmp_path / 'sheet.tiff'
    src.write_bytes(b'II*\x00')
    odd = _mk()
    odd._send_image_thumb_or_full(str(src), True)
    assert odd.hdrs['Content-Type'] == 'application/octet-stream'


def test_a_client_that_hangs_up_mid_image_is_only_logged(tmp_path, monkeypatch):
    src = tmp_path / 'a.png'
    src.write_bytes(b'\x89PNG')
    full = _mk(wfile=_Boom())
    full._send_image_thumb_or_full(str(src), False)
    assert full.code == 200
    thumb = tmp_path / 'a.jpg'
    thumb.write_bytes(b'JPEG')
    monkeypatch.setattr(M, '_img_thumb_path', lambda fp, mtime, w: str(thumb))
    small = _mk(wfile=_Boom())
    small._send_image_thumb_or_full(str(src), True)
    assert small.hdrs['Content-Type'] == 'image/jpeg'


@pytest.mark.parametrize(
    'rel',
    ['', '/etc/passwd.png', '../secrets/x.mp4', 'clips/shot.exe', 'clips/medusa_shot.mp4', 'dout/', 'clips/gone.mp4'],
)
def test_a_media_path_that_fails_a_guard_resolves_to_nothing(media_roots, rel):
    assert _mk()._resolve_media_path(rel) is None


def test_a_clip_resolves_under_the_default_root_or_a_named_one(media_roots):
    out, dout = media_roots
    assert _mk()._resolve_media_path('clips/shot.mp4') == str(out / 'clips' / 'shot.mp4')
    assert _mk()._resolve_media_path('dout/clips/shot.mp4') == str(dout / 'clips' / 'shot.mp4')
    assert _mk(path='/inspect/media?path=clips/shot.mp4')._resolve_media_path() == str(out / 'clips' / 'shot.mp4')


def test_a_clip_that_vanishes_before_its_mtime_is_refused(media_roots, monkeypatch):
    clip = str(media_roots[0] / 'clips' / 'shot.mp4')
    (media_roots[0] / 'clips' / 'shot.srt').write_text('1\n')
    real = os.path.getmtime

    def fake(p):
        if os.fspath(p) == clip:
            raise OSError('gone')
        return real(p)

    monkeypatch.setattr(os.path, 'getmtime', fake)
    for method, query in (
        ('_serve_thumb', 'path=clips/shot.mp4'),
        ('_serve_preview', 'path=clips/shot.mp4'),
        ('_serve_download', 'path=clips/shot.mp4&subs=burn'),
    ):
        h = _mk(path='/r?' + query)
        getattr(h, method)()
        assert h.errors == [404], method


def test_a_poster_or_preview_that_ffmpeg_cannot_make_is_refused(media_roots, tmp_path, monkeypatch):
    monkeypatch.setattr(M, '_thumb_path', lambda fp, mtime: str(tmp_path / 'poster.jpg'))
    monkeypatch.setattr(M, '_make_thumb', lambda fp, dst: False)
    monkeypatch.setattr(M, '_preview_path', lambda fp, mt, s, e: str(tmp_path / 'cut.mp4'))
    monkeypatch.setattr(M, '_make_preview', lambda fp, dst, s, e: False)
    poster = _mk(path='/inspect/thumb?path=clips/shot.mp4')
    poster._serve_thumb()
    cut = _mk(path='/inspect/preview?path=clips/shot.mp4')
    cut._serve_preview()
    assert (poster.errors, cut.errors) == ([404], [404])


def test_a_poster_is_extracted_once_then_served(media_roots, tmp_path, monkeypatch):
    poster = tmp_path / 'posters' / 'shot.jpg'
    poster.parent.mkdir()
    calls = []

    def make(fp, dst):
        calls.append(fp)
        open(dst, 'wb').write(b'POSTER')
        return True

    monkeypatch.setattr(M, '_thumb_path', lambda fp, mtime: str(poster))
    monkeypatch.setattr(M, '_make_thumb', make)
    h = _mk(path='/inspect/thumb?path=clips/shot.mp4')
    h._serve_thumb()
    assert (h.code, h.hdrs['Content-Type']) == (200, 'image/jpeg')
    assert h.hdrs['Cache-Control'] == 'public, max-age=86400'
    assert h.wfile.getvalue() == b'POSTER'
    again = _mk(path='/inspect/thumb?path=clips/shot.mp4', wfile=_Boom(ConnectionResetError))
    again._serve_thumb()
    assert calls == [str(media_roots[0] / 'clips' / 'shot.mp4')]
    assert again.code == 200


def test_a_poster_that_cannot_be_read_404s(media_roots, tmp_path, monkeypatch):
    poster = tmp_path / 'locked.jpg'
    poster.write_bytes(b'POSTER')
    monkeypatch.setattr(M, '_thumb_path', lambda fp, mtime: str(poster))
    _raise_open_for(monkeypatch, str(poster))
    h = _mk(path='/inspect/thumb?path=clips/shot.mp4')
    h._serve_thumb()
    assert h.errors == [404]


def test_a_preview_is_cut_from_the_registered_window_then_streamed(media_roots, tmp_path, monkeypatch):
    cut = tmp_path / 'cut.mp4'
    seen = []

    def make(fp, dst, start, end):
        seen.append((start, end))
        open(dst, 'wb').write(b'CUT')
        return True

    monkeypatch.setattr(M, '_preview_path', lambda fp, mt, s, e: str(cut))
    monkeypatch.setattr(M, '_make_preview', make)
    h = _mk(path='/inspect/preview?path=clips/shot.mp4')
    assert h._serve_preview() == 'ranged'
    assert seen == [(3.0, 6.0)]
    assert h.ranged == {'fp': str(cut), 'ctype': 'video/mp4', 'cache': 'public, max-age=86400', 'attach': None}


def test_a_plain_download_is_sent_as_an_attachment(media_roots):
    h = _mk(path='/inspect/download?path=clips/shot.mp4')
    assert h._serve_download() == 'ranged'
    assert (h.ranged['attach'], h.ranged['cache']) == ('shot.mp4', 'no-store')


def test_a_hardsub_is_burnt_once_then_downloaded(media_roots, tmp_path, monkeypatch):
    (media_roots[0] / 'clips' / 'shot.srt').write_text('1\n')
    burnt = tmp_path / 'burnt.mp4'
    monkeypatch.setattr(M, '_subburn_path', lambda fp, mt: str(burnt))
    monkeypatch.setattr(M, '_make_subburn', lambda fp, srt, dst: False)
    failed = _mk(path='/inspect/download?path=clips/shot.mp4&subs=burn')
    failed._serve_download()
    assert failed.errors == [500]

    def make(fp, srt, dst):
        open(dst, 'wb').write(b'BURNT')
        return True

    monkeypatch.setattr(M, '_make_subburn', make)
    h = _mk(path='/inspect/download?path=clips/shot.mp4&subs=burn')
    assert h._serve_download() == 'ranged'
    assert (h.ranged['fp'], h.ranged['attach']) == (str(burnt), 'shot_subtitled.mp4')
    monkeypatch.setattr(M, '_make_subburn', lambda *a: pytest.fail('must not re-burn'))
    assert _mk(path='/inspect/download?path=clips/shot.mp4&subs=burn')._serve_download() == 'ranged'
