# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers ``do_GET`` was split into (2026-10-09).

``zyg_dashboard.kanban_server.routes.do_GET`` was a 511-line if-ladder. Its blocks
moved to :mod:`zyg_dashboard.kanban_server.routes_get`, and four of the extracted
helpers used to be unreachable except through a live HTTP request:

* ``voice_spec_row`` / ``voice_spec_payload`` — the ``_vrow`` CLOSURE of
  ``/voice/api/spec``, which is exercised in isolation here for the first time;
* ``list_still_drops`` — the 24-line drop-folder scan of ``/video/api/stills``;
* ``medusa_mesh_allowed`` — the fail-closed cross-scope guard of ``/mesh/img``;
* ``send_file_bytes`` — the read-and-write-whole block the three mesh routes
  each carried a copy of.

No GPU, no network, no service: the voice studio and the mesh registry are
replaced by plain stand-ins, and the still drops are real files in ``tmp_path``.
"""

import logging
import os

import pytest

try:
    from zyg_dashboard.kanban_server import routes, routes_get
except ModuleNotFoundError as exc:  # pragma: no cover - a core-only checkout
    pytest.skip(f'kanban_server needs a package this environment has not got: {exc}', allow_module_level=True)


# ── the sentinel and the table ───────────────────────────────────────────────


def test_miss_is_a_sentinel_distinct_from_none():
    """A dispatcher that matched nothing must be distinguishable from one that answered None.

    Several branches legitimately return ``None`` (a client that hung up
    mid-write), so ``do_GET`` cannot use ``None`` to mean "not my route".
    """
    assert routes_get.MISS is not None
    assert routes_get.MISS is routes._GET_MISS
    assert routes._GET_DISPATCHERS is routes_get.DISPATCHERS


def test_the_dispatchers_are_the_ladder_in_its_original_order():
    """The ladder's blocks, in order: several prefixes shadow each other."""
    assert [f.__name__ for f in routes_get.DISPATCHERS] == [
        'dispatch_inspect_library',
        'dispatch_music_and_movement',
        'dispatch_vfx_ext_sfx',
        'dispatch_merge',
        'dispatch_media_files',
        'dispatch_voice',
        'dispatch_video',
        'dispatch_kanban_api',
        'dispatch_mesh_images',
        'dispatch_medusa_assets',
    ]


def test_every_dispatcher_misses_an_unknown_path():
    """A path no block claims must fall through all ten to the static-file tail."""
    for fn in routes_get.DISPATCHERS:
        assert fn(None, '/definitely-not-a-route') is routes_get.MISS, fn.__name__


# ── list_still_drops: the /video/api/stills drop folder ──────────────────────


def test_list_still_drops_lists_images_newest_first(tmp_path):
    """Only image extensions, newest first, each with an out/-relative path."""
    for name, mtime in (('a.png', 1000), ('b.JPG', 3000), ('c.webp', 2000)):
        fp = tmp_path / name
        fp.write_bytes(b'not really an image')
        os.utime(fp, (mtime, mtime))
    (tmp_path / 'notes.txt').write_text('ignored')
    (tmp_path / 'sub.png').mkdir()

    rows = routes_get.list_still_drops(str(tmp_path))

    assert [r['name'] for r in rows] == ['b.JPG', 'c.webp', 'a.png']
    assert [r['mtime'] for r in rows] == [3000, 2000, 1000]
    assert rows[0]['path'] == 'out/video_studio/_stills/b.JPG'
    # Pillow cannot read these bytes, so the size degrades to 0x0 rather than raising
    assert all(r['w'] == 0 and r['h'] == 0 for r in rows)


def test_list_still_drops_creates_a_missing_drop_folder(tmp_path):
    """The route is a GET on a folder an operator may never have made."""
    sd = tmp_path / 'video_studio' / '_stills'
    assert routes_get.list_still_drops(str(sd)) == []
    assert sd.is_dir()


# ── voice_spec_row / voice_spec_payload: the old _vrow closure ───────────────


class _FullStudio:
    """A voice studio that implements every optional hook ``_vrow`` probes for."""

    RACKS = [{'id': 'r1'}]
    DEFAULT_LINES = ['hello']
    MAX_PREVIEW_CHARS = 240
    SOURCE_LICENCES = {'bench': 'CC0-1.0'}
    VOICES = {
        'v1': {
            'id': 'v1',
            'name': 'One',
            'role': 'narrator',
            'sex': 'f',
            'source': 'bench:x',
            'age_class': 'adult',
            'vtl_caution_cm': 11.5,
            'vtl_caution_note': 'pre-pubertal',
            'reference_only': 1,
        }
    }

    def defaults(self):
        """The rack defaults."""
        return {'speed': 1.0}

    def singable_voices(self):
        """Unsorted on purpose: the payload must sort them."""
        return {'v9', 'v1'}

    def publication_policy(self, v):
        """Blocked unless the voice is publishable."""
        return {'publishable': False, 'blockers': ['reference_only']}

    def audition_clips(self, v):
        """One seed wav per voice."""
        return [{'p': v['id'] + '/seed.wav'}]


class _BareStudio:
    """A voice studio from before the policy/clips/singable hooks existed."""

    RACKS = []
    DEFAULT_LINES = []
    MAX_PREVIEW_CHARS = 10
    VOICES = {'v2': {'id': 'v2', 'name': 'Two', 'role': 'extra', 'source': 'scrape:y'}}

    def defaults(self):
        """No defaults at all."""
        return {}


def test_voice_spec_row_carries_the_fields_a_picker_was_blind_to():
    """age_class, the VTL caution, reference_only and the publication policy all ride along."""
    vs = _FullStudio()
    row = routes_get.voice_spec_row(vs, vs.VOICES['v1'])

    assert row['age_class'] == 'adult'
    assert row['caution_cm'] == 11.5
    assert row['caution_note'] == 'pre-pubertal'
    assert row['reference_only'] is True
    assert row['publishable'] is False
    assert row['publish_blockers'] == ['reference_only']
    assert row['clips'] == [{'p': 'v1/seed.wav'}]
    # a bench row carries a measurement, so its declared sex is certain
    assert row['sex_certain'] is True
    assert row['licence'] == 'CC0-1.0'


def test_voice_spec_row_degrades_when_the_optional_hooks_are_absent():
    """Every hook is reached through hasattr, so an older studio must still produce a row."""
    vs = _BareStudio()
    row = routes_get.voice_spec_row(vs, vs.VOICES['v2'])

    assert row == {
        'id': 'v2',
        'name': 'Two',
        'role': 'extra',
        'sex': '',
        'source': 'scrape:y',
        'age_class': '',
        'caution_cm': None,
        'caution_note': '',
        'reference_only': False,
        'sex_certain': False,
        'licence': '',
        'publishable': None,
        'publish_blockers': [],
        'clips': [],
    }


def test_voice_spec_payload_sorts_singable_and_carries_the_voice_independent_bits():
    """The spec is racks + defaults + one row per voice + the two global fields."""
    vs = _FullStudio()
    out = routes_get.voice_spec_payload(vs)

    assert out['racks'] == [{'id': 'r1'}]
    assert out['defaults'] == {'speed': 1.0}
    assert [r['id'] for r in out['voices']] == ['v1']
    assert out['singable'] == ['v1', 'v9']
    assert out['default_lines'] == ['hello']
    assert out['max_chars'] == 240
    assert routes_get.voice_spec_payload(_BareStudio())['singable'] == []


# ── medusa_mesh_allowed: the fail-closed cross-scope guard ──────────────────


@pytest.fixture
def mesh_registry(monkeypatch):
    """``mesh_registry(derived, medusa_ids)`` stands in for the mesh list and the ID set."""

    def _install(derived, medusa_ids):
        monkeypatch.setattr(routes_get, '_mesh_list', lambda: {'derived': derived})
        monkeypatch.setattr(routes_get, '_is_medusa_char', lambda cid, path: cid in medusa_ids)

    return _install


@pytest.mark.parametrize(
    ('rel', 'allowed'),
    [
        ('derived/mdz1/body.png', True),
        # an original is tied to no character at all
        ('originals/body.png', False),
        # a derived mesh off the male base
        ('derived/mdz2/body.png', False),
        # a derived mesh of a character that is not Medusa's
        ('derived/other/body.png', False),
        # a character the registry has never heard of
        ('derived/ghost/body.png', False),
    ],
)
def test_medusa_mesh_allowed_only_passes_a_verified_medusa_female_derived_mesh(mesh_registry, rel, allowed):
    """Originals and any other character's mesh are refused, as _serve_image refuses them."""
    mesh_registry(
        {
            'mdz1': {'params': {'base': 'female'}},
            'mdz2': {'params': {'base': 'male'}},
            'other': {'params': {'base': 'female'}},
        },
        {'mdz1', 'mdz2'},
    )
    assert routes_get.medusa_mesh_allowed(rel) is allowed


def test_medusa_mesh_allowed_fails_closed_on_a_registry_with_no_params(mesh_registry):
    """A record without params must not read as the female base."""
    mesh_registry({'mdz1': {}}, {'mdz1'})
    assert routes_get.medusa_mesh_allowed('derived/mdz1/body.png') is False


# ── send_file_bytes: the read-and-write-whole block ─────────────────────────


class _FakeHandler:
    """Records the response the helper writes, the way wfile/send_header would see it."""

    def __init__(self):
        self.status = None
        self.headers = []
        self.errors = []
        self.body = None
        self.ended = False
        self.wfile = self

    def send_response(self, code):
        """Record the status line."""
        self.status = code

    def send_header(self, k, v):
        """Record one header."""
        self.headers.append((k, v))

    def end_headers(self):
        """Record the blank line."""
        self.ended = True

    def send_error(self, code):
        """Record an error response and answer the way BaseHTTPRequestHandler does."""
        self.errors.append(code)
        return None

    def write(self, data):
        """Record the body and answer the byte count, as a real wfile does."""
        self.body = data
        return len(data)


def test_send_file_bytes_writes_the_whole_file_with_a_type_and_a_length(tmp_path):
    """Content type comes off the extension; no Cache-Control unless one is asked for."""
    fp = tmp_path / 'render.png'
    fp.write_bytes(b'\x89PNG' + b'x' * 20)
    h = _FakeHandler()

    assert routes_get.send_file_bytes(h, str(fp)) == 24

    assert h.status == 200
    assert dict(h.headers) == {'Content-Type': 'image/png', 'Content-Length': '24'}
    assert h.ended and h.body == b'\x89PNG' + b'x' * 20
    assert h.errors == []


def test_send_file_bytes_adds_the_cache_header_only_when_asked(tmp_path):
    """/gnm/img sends no-cache; the two /mesh/img routes send nothing."""
    fp = tmp_path / 'fit.json'
    fp.write_bytes(b'{}')
    h = _FakeHandler()

    routes_get.send_file_bytes(h, str(fp), cache='no-cache')

    assert dict(h.headers)['Cache-Control'] == 'no-cache'
    assert dict(h.headers)['Content-Type'] == 'application/json'


def test_send_file_bytes_404s_when_the_file_vanished(tmp_path):
    """A running refresh may delete the file between the containment check and the open."""
    h = _FakeHandler()

    assert routes_get.send_file_bytes(h, str(tmp_path / 'gone.png')) is None

    assert h.errors == [404]
    assert h.status is None


def test_send_file_bytes_swallows_a_client_that_hung_up(tmp_path):
    """A dropped connection answers None — which is why MISS is not None."""
    fp = tmp_path / 'render.png'
    fp.write_bytes(b'data')

    class _Gone(_FakeHandler):
        def write(self, data):
            """The client closed the socket mid-write."""
            raise BrokenPipeError('client went away')

    h = _Gone()
    assert routes_get.send_file_bytes(h, str(fp)) is None
    assert h.errors == []


def test_send_file_bytes_falls_back_to_octet_stream(tmp_path):
    """An extension the mesh table does not know must still be served, not refused."""
    fp = tmp_path / 'mesh.obj'
    fp.write_bytes(b'v 0 0 0\n')
    h = _FakeHandler()

    routes_get.send_file_bytes(h, str(fp))

    assert dict(h.headers)['Content-Type'] == 'application/octet-stream'


# ── _flag: the query-string truthiness the ladder read inline ───────────────


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('1', True),
        ('true', True),
        ('yes', True),
        # the table is exact and lower-case: nothing else counts
        ('True', False),
        ('YES', False),
        ('on', False),
        ('0', False),
        ('false', False),
        ('', False),
    ],
)
def test_flag_accepts_only_the_three_documented_spellings(value, expected):
    """``?x=`` is true for 1/true/yes and for nothing else, case-sensitively."""
    assert routes_get._flag({'x': value}, 'x') is expected


def test_flag_treats_an_absent_parameter_as_false():
    """A missing parameter must not raise: every caller passes the raw query dict."""
    assert routes_get._flag({}, 'x') is False


# ── _sfx_merge_get / _voice_merge_get: the merger reads ─────────────────────


class _MergeHandler:
    """Records ``_send_json`` / ``_send_ranged`` / ``send_error`` instead of answering."""

    def __init__(self, query=None):
        self.json = []
        self.ranged = []
        self.errors = []
        self._q = query or {}

    def _query(self):
        """The parsed query string the dispatcher hands to the read helpers."""
        return self._q

    def _send_json(self, payload, code=200):
        """Record one JSON answer and its status."""
        self.json.append((code, payload))
        return 'json'

    def _send_ranged(self, fp, ctype, cache, attach=None):
        """Record one range-capable file answer."""
        self.ranged.append({'fp': fp, 'ctype': ctype, 'cache': cache, 'attach': attach})
        return 'ranged'

    def send_error(self, code):
        """Record an error response."""
        self.errors.append(code)
        return None


class _Merger:
    """A merger stand-in: no audio pipeline, just the four hooks the reads call."""

    def __init__(self, recipe=None, resolved='/w/mix.wav'):
        self._recipe = recipe
        self._resolved = resolved

    def spec(self):
        """The merger's capability spec."""
        return {'ok': True, 'stems': 2}

    def recipe(self, f):
        """The stored recipe for ``f``, or None when nothing is stored."""
        return self._recipe

    def resolve_audio(self, p):
        """The absolute path for a content-addressed name, or None when unknown."""
        return self._resolved

    def content_type(self, rel):
        """Content type by extension, as the real merger computes it."""
        return 'image/png'


def test_sfx_merge_get_sanitises_a_hostile_download_name():
    """``?dl=`` becomes a Content-Disposition name, so traversal and quotes must be stripped.

    The extension is taken from the resolved path and not from ``dl``, so a
    client cannot rename a PNG into something the browser will execute.
    """
    h = _MergeHandler({'p': 'a/b.png', 'dl': '../../etc/pa$swd"x'})

    assert routes_get._sfx_merge_get(h, '/inspect/merge/asset', _Merger(), h._query()) == 'ranged'

    # the slashes, the dollar and the quote are deleted outright (not replaced),
    # so no separator survives and the name cannot climb out of a download dir
    assert h.ranged[0]['attach'] == '....etcpaswdx.png'
    assert '/' not in h.ranged[0]['attach']
    assert h.ranged[0]['cache'] == 'public, max-age=86400'


def test_sfx_merge_get_download_name_falls_back_when_nothing_survives():
    """A ``dl`` made only of rejected characters must not yield a bare extension."""
    h = _MergeHandler({'p': 'a/b.png', 'dl': '/@@/'})

    routes_get._sfx_merge_get(h, '/inspect/merge/asset', _Merger(), h._query())

    assert h.ranged[0]['attach'] == 'sfx.png'


def test_sfx_merge_get_truncates_a_very_long_download_name():
    """80 characters of stem, then the extension — a filesystem-safe length."""
    h = _MergeHandler({'p': 'a/b.png', 'dl': 'z' * 200})

    routes_get._sfx_merge_get(h, '/inspect/merge/asset', _Merger(), h._query())

    assert h.ranged[0]['attach'] == 'z' * 80 + '.png'


def test_sfx_merge_get_sends_no_attachment_without_dl():
    """Without ``?dl=`` the asset is shown inline, which is how the analysis pictures load."""
    h = _MergeHandler({'p': 'a/b.png'})

    routes_get._sfx_merge_get(h, '/inspect/merge/asset', _Merger(), h._query())

    assert h.ranged[0]['attach'] is None


def test_sfx_merge_get_404s_an_asset_that_does_not_resolve():
    """An unresolvable name is refused before any attachment name is built."""
    h = _MergeHandler({'p': '../secret', 'dl': 'x'})

    assert routes_get._sfx_merge_get(h, '/inspect/merge/asset', _Merger(resolved=None), h._query()) is None

    assert h.errors == [404] and h.ranged == []


def test_sfx_merge_get_404s_a_recipe_that_was_never_stored():
    """A missing recipe is a 404 JSON body, not an empty 200."""
    h = _MergeHandler({'f': 'mix.wav'})

    routes_get._sfx_merge_get(h, '/inspect/api/merge/recipe', _Merger(recipe=None), h._query())

    assert h.json == [(404, {'error': 'no recipe stored for that file'})]


def test_sfx_merge_get_returns_a_stored_recipe():
    """A stored recipe rides in an ok envelope."""
    h = _MergeHandler({'f': 'mix.wav'})

    routes_get._sfx_merge_get(h, '/inspect/api/merge/recipe', _Merger(recipe={'gain': 2}), h._query())

    assert h.json == [(200, {'ok': True, 'recipe': {'gain': 2}})]


def test_sfx_merge_get_404s_an_unknown_path():
    """The helper is the tail of a prefix match, so it must refuse what it does not know."""
    h = _MergeHandler()

    assert routes_get._sfx_merge_get(h, '/inspect/api/merge/nope', _Merger(), {}) is None
    assert h.errors == [404]


def test_voice_merge_get_serves_a_stem_with_a_cacheable_header():
    """Voice stems are content-addressed too, so they are cacheable for a day."""
    h = _MergeHandler({'p': 'v/stem.wav'})

    assert routes_get._voice_merge_get(h, '/voice/merge/audio', _Merger(), h._query()) == 'ranged'

    assert h.ranged[0]['ctype'] == 'audio/wav'
    assert h.ranged[0]['cache'] == 'public, max-age=86400'


def test_voice_merge_get_404s_a_recipe_that_was_never_stored():
    """Same envelope as the SFX merger's, which the shared front end relies on."""
    h = _MergeHandler({'f': 'line.wav'})

    routes_get._voice_merge_get(h, '/voice/api/merge/recipe', _Merger(recipe=None), h._query())

    assert h.json == [(404, {'error': 'no recipe stored for that file'})]


# ── dispatch_merge: the 503 and the 400 the ladder wrapped the reads in ─────


def test_dispatch_merge_503s_when_the_sfx_merger_is_absent(monkeypatch):
    """An optional module that failed to import must answer 503 with its import error."""
    monkeypatch.setattr(routes_get, '_sfx_merger', lambda: None)
    monkeypatch.setitem(routes_get._MERGE_MOD, 'err', 'no soundfile')
    h = _MergeHandler()

    routes_get.dispatch_merge(h, '/inspect/api/merge/spec')

    assert h.json == [(503, {'error': 'sfx merger unavailable: no soundfile'})]


def test_dispatch_merge_503s_when_the_voice_merger_is_absent(monkeypatch):
    """The voice branch reports its own module's error, not the SFX one's."""
    monkeypatch.setattr(routes_get, '_voice_merger', lambda: None)
    monkeypatch.setitem(routes_get._VOICE_MERGE_MOD, 'err', 'no torch')
    h = _MergeHandler()

    routes_get.dispatch_merge(h, '/voice/api/merge/spec')

    assert h.json == [(503, {'error': 'voice merger unavailable: no torch'})]


def test_dispatch_merge_400s_a_hostile_query_instead_of_tracebacking(monkeypatch, caplog):
    """A merger that raises on a crafted query must become a 400, and be logged."""

    class _Hostile(_Merger):
        def spec(self):
            """The crafted query made the merger blow up."""
            raise ValueError('bad stem index')

    monkeypatch.setattr(routes_get, '_sfx_merger', _Hostile)
    h = _MergeHandler()

    with caplog.at_level(logging.INFO, logger=routes_get.__name__):
        routes_get.dispatch_merge(h, '/inspect/api/merge/spec')

    assert h.json == [(400, {'error': 'ValueError: bad stem index'})]
    assert 'merge GET error on /inspect/api/merge/spec' in caplog.text


def test_dispatch_merge_truncates_a_huge_error_message(monkeypatch):
    """A 300-character cap keeps a pathological message out of the JSON body."""

    class _Hostile(_Merger):
        def spec(self):
            """A merger whose exception carries a megabyte of text."""
            raise ValueError('y' * 5000)

    monkeypatch.setattr(routes_get, '_sfx_merger', _Hostile)
    h = _MergeHandler()

    routes_get.dispatch_merge(h, '/inspect/api/merge/spec')

    assert len(h.json[0][1]['error']) == 300


def test_dispatch_merge_misses_a_path_that_is_not_a_merger_path():
    """``/inspect/api/mergers`` is not a merge path: the prefix test must be exact."""
    assert routes_get.dispatch_merge(_MergeHandler(), '/inspect/api/mergers') is routes_get.MISS
    assert routes_get.dispatch_merge(_MergeHandler(), '/voice/api/mergex') is routes_get.MISS
