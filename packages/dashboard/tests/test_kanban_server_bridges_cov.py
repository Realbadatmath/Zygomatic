# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for :mod:`zyg_dashboard.kanban_server.bridges`.

The module is a ``BaseHTTPRequestHandler`` mixin, not a Flask blueprint: every
method wants the stdlib handler surface plus the sibling mixins' ``_send_json``,
``_query``, ``_json_body`` and ``_resolve_media_path``.  ``_Rec``/``_Handler``
supply exactly that and record what was sent, so every bridge runs offline.

The two bridges that reach into ``zyg_workflows`` import it *inside* the method,
so ``_fake_workflows`` puts a bare :class:`types.ModuleType` in ``sys.modules``
under that name.  It has no ``__path__``, which is what makes the failure half
deterministic: ``from zyg_workflows import voice_bridge`` cannot fall back to
the real submodule and raises ``ImportError`` for the ``except`` branch.
"""

import io
import os
import re
import sys
import types
import builtins

import pytest

import zyg_dashboard.kanban_server.bridges as M


class _Rec:
    """Everything the mixin inherits from its siblings and the stdlib."""

    def end_headers(self):
        self.ended = True

    def _query(self):
        return dict(self.query)

    def _json_body(self, limit=None):
        self.body_limit = limit
        return dict(self.body)

    def _send_json(self, obj, code=200, memo_key=None):
        self.json = (obj, code)
        return 'json'

    def _resolve_media_path(self, rel=None):
        return self.media


class _Handler(M._BridgesMixin, _Rec):
    def __init__(self, path='/', headers=None, wfile=None, query=None, body=None, media=None):
        self.path = path
        self.headers = {} if headers is None else headers
        self.wfile = io.BytesIO() if wfile is None else wfile
        self.query = {} if query is None else query
        self.body = {} if body is None else body
        self.media = media
        self.code = None
        self.hdrs = {}
        self.ended = False
        self.errors = []
        self.ranged = None
        self.json = None
        self.body_limit = None

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.hdrs[key] = value

    def send_error(self, code, *a, **kw):
        self.errors.append(code)
        self.code = code
        return 'error'


class _RangedRec(_Handler):
    """A handler whose byte-range send is recorded instead of performed."""

    def _send_ranged(self, fp, mime, cache='public, max-age=30', attach=None):
        self.ranged = {'fp': fp, 'mime': mime, 'cache': cache, 'attach': attach}
        return 'ranged'


class _Boom(io.BytesIO):
    """A wfile whose write dies the way a closed browser tab does."""

    def __init__(self, exc=BrokenPipeError):
        super().__init__()
        self.exc = exc

    def write(self, data):
        raise self.exc('client went away')


def _mk(**kw):
    return _Handler(**kw)


def _mkrec(**kw):
    return _RangedRec(**kw)


def _raise_open_for(monkeypatch, bad):
    """Make open() fail for one path only (an unreadable file on disk)."""
    real = builtins.open

    def fake(p, *a, **kw):
        if isinstance(p, (str, bytes, os.PathLike)) and os.fspath(p) == bad:
            raise OSError('unreadable')
        return real(p, *a, **kw)

    monkeypatch.setattr(builtins, 'open', fake)


def _fake_workflows(monkeypatch, **attrs):
    """Stand in for the zyg_workflows package, with only the named members."""
    mod = types.ModuleType('zyg_workflows')
    for key, value in attrs.items():
        setattr(mod, key, value)
    monkeypatch.setitem(sys.modules, 'zyg_workflows', mod)
    return mod


class _VB:
    """The voice bridge seam: four entry points, each a recorded stub."""

    BODY_LIMIT = 4096

    def __init__(self, bundle='', get=None, post=None, sse=None):
        self._bundle = bundle
        self._get, self._post, self._sse = get, post, sse
        self.seen = []

    def bundle_js(self):
        return self._bundle

    def handle_get(self, path, query):
        self.seen.append(('GET', path, query))
        return self._get() if callable(self._get) else self._get

    def handle_post(self, path, body):
        self.seen.append(('POST', path, body))
        return self._post() if callable(self._post) else self._post

    def handle_sse(self, handler, query):
        self.seen.append(('SSE', query))
        return self._sse() if callable(self._sse) else self._sse


class _AA:
    """architecture_assets: the fence that owns containment, stubbed out."""

    def __init__(self, resolved=None, mime='model/gltf+json'):
        self.resolved, self.mime = resolved, mime
        self.seen = []

    def resolve_url(self, rel):
        self.seen.append(rel)
        return self.resolved

    def mime_for(self, fp):
        return self.mime


# ── the two *_ext bundles ───────────────────────────────────────────────────
@pytest.fixture
def ext_tree(tmp_path, monkeypatch):
    """arch_ext/ and studio_ext/ under a HERE of our own."""
    arch, studio = tmp_path / 'arch_ext', tmp_path / 'studio_ext'
    arch.mkdir()
    studio.mkdir()
    (arch / 'a_walls.js').write_text('AR_EXT.geom.wall = 1;')
    (arch / 'b_roof.js').write_text('AR_EXT.geom.roof = 2;')
    (arch / 'c_locked.js').write_text('unreadable on purpose')
    (studio / 'y_locked.js').write_text('unreadable on purpose')
    (studio / 'z_grid.js').write_text('SX.ready.push(1);')
    (studio / '_notes.js').write_text('prose, not code')
    monkeypatch.setattr(M, 'HERE', str(tmp_path))
    return arch, studio


def _assert_bundle_headers(h):
    assert h.code == 200
    assert h.hdrs['Content-Type'] == 'application/javascript; charset=utf-8'
    assert h.hdrs['Cache-Control'] == 'no-store'
    assert h.hdrs['Content-Length'] == str(len(h.wfile.getvalue()))
    assert h.ended is True


def test_the_arch_bundle_is_every_file_in_name_order_behind_the_registry(ext_tree, monkeypatch):
    _raise_open_for(monkeypatch, str(ext_tree[0] / 'c_locked.js'))
    h = _mk()
    h._serve_arch_ext_bundle()
    body = h.wfile.getvalue().decode()
    _assert_bundle_headers(h)
    assert 'window.AR_EXT = window.AR_EXT ||' in body
    assert body.index('a_walls.js') < body.index('b_roof.js')
    assert 'AR_EXT.geom.roof = 2;' in body
    assert 'console.error("arch_ext c_locked.js unreadable: unreadable");' in body
    assert 'unreadable on purpose' not in body


def test_the_studio_bundle_skips_the_underscore_docs(ext_tree, monkeypatch):
    _raise_open_for(monkeypatch, str(ext_tree[1] / 'y_locked.js'))
    h = _mk()
    h._serve_studio_ext_bundle()
    body = h.wfile.getvalue().decode()
    _assert_bundle_headers(h)
    assert 'window.SX = window.SX || {ready:[]};' in body
    assert 'SX.ready.push(1);' in body
    assert '_notes.js' not in body and 'prose, not code' not in body
    assert 'console.error("studio_ext y_locked.js unreadable: unreadable");' in body


def test_an_empty_extension_directory_is_just_the_preamble(tmp_path, monkeypatch):
    monkeypatch.setattr(M, 'HERE', str(tmp_path))
    for method, marker in (('_serve_arch_ext_bundle', 'AR_EXT'), ('_serve_studio_ext_bundle', 'window.SX')):
        h = _mk()
        getattr(h, method)()
        assert len(h.wfile.getvalue().decode().split('\n')) == 2
        assert marker in h.wfile.getvalue().decode()


# ── the voice bundle ────────────────────────────────────────────────────────
def test_the_voice_bundle_comes_straight_from_the_bridge(monkeypatch):
    _fake_workflows(monkeypatch, voice_bridge=_VB(bundle='window.VB = {actions:{}};'))
    h = _mk()
    h._serve_voice_ext_bundle()
    _assert_bundle_headers(h)
    assert h.wfile.getvalue() == b'window.VB = {actions:{}};'


def test_a_missing_voice_bridge_degrades_to_an_inert_registry(monkeypatch):
    _fake_workflows(monkeypatch)
    h = _mk()
    h._serve_voice_ext_bundle()
    body = h.wfile.getvalue().decode()
    _assert_bundle_headers(h)
    assert 'window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};' in body
    assert 'voice_ext bundle unavailable: ' in body
    assert body.count('"') == 2


def test_a_client_that_hangs_up_mid_voice_bundle_is_only_logged(monkeypatch):
    _fake_workflows(monkeypatch, voice_bridge=_VB(bundle='x'))
    h = _mk(wfile=_Boom())
    h._serve_voice_ext_bundle()
    assert h.code == 200
    assert h.hdrs['Content-Length'] == '1'


# ── the voice bridge itself ─────────────────────────────────────────────────
def test_both_voice_routes_are_503_without_the_bridge(monkeypatch):
    _fake_workflows(monkeypatch)
    h = _mk()
    assert h._voice_bridge('GET', '/inspect/api/voice/state') == 'json'
    obj, code = h.json
    assert code == 503 and obj['error'].startswith('voice bridge unavailable: ')
    sse = _mk()
    sse._voice_bridge_sse()
    assert sse.json[1] == 503


def test_a_get_and_a_post_are_forwarded_with_the_query_and_the_body(monkeypatch):
    vb = _VB(get=({'state': 'idle'}, 200), post=({'ok': True}, 201))
    _fake_workflows(monkeypatch, voice_bridge=vb)
    get = _mk(query={'view': 'arch'})
    assert get._voice_bridge('GET', '/inspect/api/voice/state') == 'json'
    assert get.json == ({'state': 'idle'}, 200)
    post = _mk(body={'op': 'say'})
    post._voice_bridge('POST', '/inspect/api/voice/do')
    assert post.json == ({'ok': True}, 201)
    assert post.body_limit == _VB.BODY_LIMIT
    assert vb.seen == [
        ('GET', '/inspect/api/voice/state', {'view': 'arch'}),
        ('POST', '/inspect/api/voice/do', {'op': 'say'}),
    ]


def test_an_exploding_voice_op_answers_500_and_is_logged(monkeypatch, caplog):
    def boom():
        raise RuntimeError('no capture device')

    _fake_workflows(monkeypatch, voice_bridge=_VB(get=boom))
    h = _mk()
    with caplog.at_level('INFO', logger=M._zyg_log.name):
        h._voice_bridge('GET', '/inspect/api/voice/state')
    assert h.json == ({'error': 'no capture device'}, 500)
    assert 'voice bridge GET /inspect/api/voice/state' in caplog.text


@pytest.mark.parametrize(
    'res, payload, mime, disposition',
    [
        ((b'RIFFwav', 'audio/wav', 'take.wav'), b'RIFFwav', 'audio/wav', 'attachment; filename="take.wav"'),
        ((bytearray(b'OggS'), None, None), b'OggS', 'application/octet-stream', None),
        (('a line', 'text/plain', 'od"d.txt'), b'a line', 'text/plain', 'attachment; filename="odd.txt"'),
    ],
)
def test_a_rendered_payload_is_sent_raw_rather_than_wrapped_in_json(monkeypatch, res, payload, mime, disposition):
    _fake_workflows(monkeypatch, voice_bridge=_VB(get=res))
    h = _mk()
    assert h._voice_bridge('GET', '/inspect/api/voice/render') is None
    assert h.json is None
    assert (h.code, h.hdrs['Content-Type'], h.hdrs['Cache-Control']) == (200, mime, 'no-store')
    assert h.hdrs['Content-Length'] == str(len(payload))
    assert h.hdrs.get('Content-Disposition') == disposition
    assert h.wfile.getvalue() == payload


def test_a_client_that_hangs_up_mid_payload_is_only_logged(monkeypatch):
    _fake_workflows(monkeypatch, voice_bridge=_VB(get=(b'RIFF', 'audio/wav', None)))
    h = _mk(wfile=_Boom(ConnectionResetError))
    assert h._voice_bridge('GET', '/inspect/api/voice/render') is None
    assert h.code == 200


def test_the_sse_stream_is_handed_the_handler_and_the_query(monkeypatch):
    vb = _VB(sse='streamed')
    _fake_workflows(monkeypatch, voice_bridge=vb)
    h = _mk(query={'since': '7'})
    assert h._voice_bridge_sse() == 'streamed'
    assert vb.seen == [('SSE', {'since': '7'})]


def test_an_sse_stream_that_dies_is_logged_and_swallowed(monkeypatch, caplog):
    def boom():
        raise RuntimeError('driver tab reloaded')

    _fake_workflows(monkeypatch, voice_bridge=_VB(sse=boom))
    h = _mk()
    with caplog.at_level('INFO', logger=M._zyg_log.name):
        assert h._voice_bridge_sse() is None
    assert 'voice bridge sse' in caplog.text
    assert h.json is None


# ── the Architecture Studio mesh packs ──────────────────────────────────────
def test_an_arch_asset_is_503_without_the_asset_module(monkeypatch):
    _fake_workflows(monkeypatch)
    h = _mkrec()
    h._serve_arch_asset('/inspect/arch-asset/pack/scene.gltf')
    assert h.errors == [503]


def test_an_unquotable_or_unresolvable_arch_url_is_404(monkeypatch):
    aa = _AA(resolved=None)
    _fake_workflows(monkeypatch, architecture_assets=aa)
    missing = _mkrec()
    missing._serve_arch_asset('/inspect/arch-asset/pack/ghost.bin')
    assert (missing.errors, aa.seen) == ([404], ['pack/ghost.bin'])

    def boom(_):
        raise ValueError('not decodable')

    monkeypatch.setattr(M, '_urlunquote', boom)
    broken = _mkrec()
    broken._serve_arch_asset('/inspect/arch-asset/pack/%ZZ.bin')
    assert broken.errors == [404]


def test_a_resolved_pack_file_is_streamed_as_immutable(monkeypatch, tmp_path):
    fp = tmp_path / 'scene.bin'
    fp.write_bytes(b'GLB')
    aa = _AA(resolved=str(fp), mime='application/octet-stream')
    _fake_workflows(monkeypatch, architecture_assets=aa)
    h = _mkrec()
    assert h._serve_arch_asset('/inspect/arch-asset/town%20hall/scene.bin') == 'ranged'
    assert aa.seen == ['town hall/scene.bin']
    assert h.ranged == {
        'fp': str(fp),
        'mime': 'application/octet-stream',
        'cache': 'public, max-age=86400',
        'attach': None,
    }


# ── /inspect/media ──────────────────────────────────────────────────────────
@pytest.mark.parametrize('name', [None, 'notes.txt', 'clip.mkv'])
def test_media_needs_a_resolved_path_with_a_known_extension(tmp_path, name):
    media = None if name is None else str(tmp_path / name)
    h = _mkrec(media=media)
    h._serve_media()
    assert h.errors == [404]
    assert h.ranged is None


@pytest.mark.parametrize('name, mime', [('shot.mp4', 'video/mp4'), ('card.JPEG', 'image/jpeg'), ('s.vtt', 'text/vtt')])
def test_a_whitelisted_media_file_is_streamed_with_its_mime(tmp_path, name, mime):
    fp = tmp_path / name
    fp.write_bytes(b'x')
    h = _mkrec(media=str(fp))
    assert h._serve_media() == 'ranged'
    assert h.ranged == {'fp': str(fp), 'mime': mime, 'cache': 'public, max-age=30', 'attach': None}


# ── _send_ranged ────────────────────────────────────────────────────────────
@pytest.fixture
def clip(tmp_path):
    fp = tmp_path / 'shot.mp4'
    fp.write_bytes(bytes(range(256)) * 4)
    return fp


def test_a_whole_file_is_sent_with_accept_ranges_and_a_filename(clip):
    h = _mk()
    h._send_ranged(str(clip), 'video/mp4', cache='no-store', attach='shot.mp4')
    assert (h.code, h.hdrs['Content-Type'], h.hdrs['Accept-Ranges']) == (200, 'video/mp4', 'bytes')
    assert (h.hdrs['Cache-Control'], h.hdrs['Content-Length']) == ('no-store', '1024')
    assert h.hdrs['Content-Disposition'] == 'attachment; filename="shot.mp4"'
    assert 'Content-Range' not in h.hdrs
    assert h.wfile.getvalue() == clip.read_bytes()


@pytest.mark.parametrize(
    'rng, code, start, length',
    [
        ('bytes=0-99', 206, 0, 100),
        ('bytes=10-', 206, 10, 1014),
        ('bytes=-64', 206, 960, 64),
        ('bytes=0-99999', 206, 0, 1024),
        ('bytes=whatever', 200, 0, 1024),
        (None, 200, 0, 1024),
    ],
)
def test_a_range_request_is_answered_with_exactly_that_slice(clip, rng, code, start, length):
    h = _mk(headers={} if rng is None else {'Range': rng})
    h._send_ranged(str(clip), 'video/mp4')
    assert (h.code, h.hdrs['Content-Length']) == (code, str(length))
    assert h.wfile.getvalue() == clip.read_bytes()[start : start + length]
    expected = 'bytes %d-%d/1024' % (start, start + length - 1) if code == 206 else None
    assert h.hdrs.get('Content-Range') == expected


@pytest.mark.parametrize('rng', ['bytes=2000-', 'bytes=1024-2000', 'bytes=500-100'])
def test_a_range_outside_the_file_is_416_with_a_zero_length(clip, rng):
    h = _mk(headers={'Range': rng})
    assert h._send_ranged(str(clip), 'video/mp4') is None
    assert (h.code, h.hdrs['Content-Range'], h.hdrs['Content-Length']) == (416, 'bytes */1024', '0')
    assert (h.ended, h.wfile.getvalue()) == (True, b'')


def test_a_file_that_cannot_be_sized_or_opened_is_404(tmp_path, clip, monkeypatch):
    gone = _mk()
    gone._send_ranged(str(tmp_path / 'ghost.mp4'), 'video/mp4')
    assert gone.errors == [404]
    _raise_open_for(monkeypatch, str(clip))
    locked = _mk()
    locked._send_ranged(str(clip), 'video/mp4')
    assert (locked.errors, locked.code) == ([404], 404)


def test_a_client_that_hangs_up_mid_stream_stops_the_loop(clip):
    h = _mk(wfile=_Boom(ConnectionResetError))
    h._send_ranged(str(clip), 'video/mp4')
    assert (h.code, h.hdrs['Content-Length']) == (200, '1024')


def test_a_file_that_runs_short_of_its_size_ends_the_stream(clip, monkeypatch):
    real_size, real_open = os.path.getsize, builtins.open
    short = io.BytesIO(b'TRUNC')
    monkeypatch.setattr(os.path, 'getsize', lambda p: 4096 if os.fspath(p) == str(clip) else real_size(p))
    monkeypatch.setattr(
        builtins,
        'open',
        lambda p, *a, **kw: short if os.fspath(p) == str(clip) else real_open(p, *a, **kw),
    )
    h = _mk()
    h._send_ranged(str(clip), 'video/mp4')
    assert (h.hdrs['Content-Length'], h.wfile.getvalue()) == ('4096', b'TRUNC')


# ── the two deleters ────────────────────────────────────────────────────────
@pytest.fixture
def char_tree(tmp_path, monkeypatch):
    """One character with two pictures, under a characters root of our own."""
    chars = tmp_path / 'chars'
    cells = chars / 'ada' / 'contact_sheet' / 'cells'
    cells.mkdir(parents=True)
    (cells / 'front.png').write_bytes(b'\x89PNGfront')
    (cells / 'side.png').write_bytes(b'\x89PNGside')
    monkeypatch.setattr(M, '_CHARS_ROOT', str(chars))
    monkeypatch.setattr(M, '_safe_char_dir', lambda cid: str(chars / cid) if cid in ('ada', 'gorgon') else None)
    monkeypatch.setattr(M, '_is_medusa_char', lambda cid, cdir, medusa_ids=None: cid == 'gorgon')
    monkeypatch.setattr(M, '_LIST_CACHE', {'ts': 1234.5})
    monkeypatch.setattr(M, '_NAME_CACHE', {'ada': 'Ada Lovelace'})
    return chars


@pytest.mark.parametrize(
    'query, code, err',
    [
        ({'cat': 'cells', 'name': 'front.png'}, 400, 'bad params'),
        ({'id': 'nobody', 'cat': 'cells', 'name': 'front.png'}, 400, 'bad params'),
        ({'id': 'ada', 'cat': 'nosuch', 'name': 'front.png'}, 400, 'bad params'),
        ({'id': 'ada', 'cat': 'cells'}, 400, 'bad params'),
        ({'id': 'ada', 'cat': 'cells', 'name': '../../etc/passwd'}, 400, 'bad params'),
        ({'id': 'ada', 'cat': 'cells', 'name': '.hidden.png'}, 400, 'bad params'),
        ({'id': 'ada', 'cat': 'cells', 'name': 'front.png', 'scope': 'medusa'}, 404, 'not found'),
        ({'id': 'gorgon', 'cat': 'cells', 'name': 'front.png'}, 404, 'not found'),
        ({'id': 'ada', 'cat': 'cells', 'name': 'ghost.png'}, 404, 'not found'),
        ({'id': 'ada', 'cat': 'arcane_final', 'name': 'front.png'}, 404, 'not found'),
    ],
)
def test_a_picture_delete_that_fails_a_guard_changes_nothing(char_tree, query, code, err):
    h = _mk(query=query)
    assert h._delete_image() == 'json'
    assert h.json == ({'error': err}, code)
    assert (char_tree / 'ada' / 'contact_sheet' / 'cells' / 'front.png').exists()
    assert not (char_tree / 'ada' / '.deleted').exists()


def test_a_deleted_picture_moves_into_the_recoverable_trash(char_tree, caplog):
    cells = char_tree / 'ada' / 'contact_sheet' / 'cells'
    trash = char_tree / 'ada' / '.deleted'
    with caplog.at_level('INFO', logger=M._zyg_log.name):
        h = _mk(query={'id': 'ada', 'cat': 'cells', 'name': 'front.png'})
        h._delete_image()
    assert h.json == ({'ok': True}, 200)
    assert not (cells / 'front.png').exists()
    assert (trash / 'cells__front.png').read_bytes() == b'\x89PNGfront'
    assert M._LIST_CACHE['ts'] == 0.0
    assert 'deleted (to trash): ada/cells/front.png' in caplog.text


def test_a_second_delete_of_the_same_name_is_numbered_not_overwritten(char_tree):
    cells = char_tree / 'ada' / 'contact_sheet' / 'cells'
    trash = char_tree / 'ada' / '.deleted'
    for body in (b'first', b'second', b'third'):
        (cells / 'front.png').write_bytes(body)
        _mk(query={'id': 'ada', 'cat': 'cells', 'name': 'front.png'})._delete_image()
    assert (trash / 'cells__front.png').read_bytes() == b'first'
    assert (trash / 'cells__1__front.png').read_bytes() == b'second'
    assert (trash / 'cells__2__front.png').read_bytes() == b'third'


@pytest.mark.parametrize(
    'query, code, err',
    [
        ({}, 400, 'bad params'),
        ({'id': 'nobody'}, 400, 'bad params'),
        ({'id': 'ada', 'scope': 'medusa'}, 404, 'not found'),
        ({'id': 'gorgon'}, 404, 'not found'),
    ],
)
def test_a_character_delete_that_fails_a_guard_changes_nothing(char_tree, query, code, err):
    h = _mk(query=query)
    assert h._delete_character() == 'json'
    assert h.json == ({'error': err}, code)
    assert (char_tree / 'ada').is_dir()
    assert not (char_tree / '.deleted').exists()


def test_a_deleted_character_moves_whole_into_the_root_trash(char_tree, caplog):
    with caplog.at_level('INFO', logger=M._zyg_log.name):
        h = _mk(query={'id': 'ada'})
        h._delete_character()
    assert h.json == ({'ok': True, 'id': 'ada'}, 200)
    assert not (char_tree / 'ada').exists()
    assert (char_tree / '.deleted' / 'ada' / 'contact_sheet' / 'cells' / 'front.png').exists()
    assert M._LIST_CACHE['ts'] == 0.0
    assert 'ada' not in M._NAME_CACHE
    assert 'deleted character (to trash): ada' in caplog.text

    (char_tree / 'ada' / 'contact_sheet').mkdir(parents=True)
    _mk(query={'id': 'ada'})._delete_character()
    assert (char_tree / '.deleted' / 'ada__1' / 'contact_sheet').is_dir()


def test_the_basename_check_still_refuses_a_separator_the_regex_let_through(char_tree, monkeypatch):
    """Defence in depth: `_NAME_RE` forbids '/', so this guard is only reachable
    once that regex is relaxed — which is exactly why it is worth having."""
    monkeypatch.setattr(M, '_NAME_RE', re.compile(r'.+'))
    h = _mk(query={'id': 'ada', 'cat': 'cells', 'name': 'sub/front.png'})
    assert h._delete_image() == 'json'
    assert h.json == ({'error': 'bad name'}, 400)
    assert not (char_tree / 'ada' / '.deleted').exists()


def test_a_trash_move_that_the_filesystem_refuses_answers_500(char_tree, monkeypatch):
    def refuse(src, dst):
        raise OSError('read-only file system')

    monkeypatch.setattr(os, 'rename', refuse)
    picture = _mk(query={'id': 'ada', 'cat': 'cells', 'name': 'front.png'})
    picture._delete_image()
    assert picture.json == ({'error': 'read-only file system'}, 500)
    character = _mk(query={'id': 'ada'})
    character._delete_character()
    assert character.json == ({'error': 'read-only file system'}, 500)
    assert M._LIST_CACHE['ts'] == 1234.5
