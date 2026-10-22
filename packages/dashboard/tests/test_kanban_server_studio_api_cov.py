# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for :mod:`zyg_dashboard.kanban_server.studio_api`.

The module is a ``BaseHTTPRequestHandler`` mixin, not a blueprint: every method
wants the handler surface (``_send_json``, ``_query``, ``_json_body``,
``send_response`` …) the sibling mixins supply. ``_Handler`` supplies exactly
that and records what was sent, so each route runs offline. The studio modules
are never imported: ``_arch``/``_cstudio`` are monkeypatched to return a
``SimpleNamespace`` of plain functions (an instance attribute is not bound, so
no ``self`` is needed), and the lazy ``from zyg_workflows import …`` imports are
satisfied by attributes on the real package plus ``sys.modules`` entries
(``None`` there stages an ImportError).
"""

import io
import sys
import types

import pytest

import zyg_dashboard.kanban_server.studio_api as M


class _Handler(M._StudioApiMixin):
    """Everything the mixin inherits from its siblings and the stdlib."""

    def __init__(self, query=None, body=None):
        self.q = {} if query is None else query
        self.body = {} if body is None else body
        self.wfile = io.BytesIO()
        self.sent = None
        self.code = None
        self.hdrs = {}
        self.ended = False
        self.errors = []
        self.limits = []

    def _send_json(self, obj, code=200):
        self.sent = (obj, code)
        return 'json'

    def _query(self):
        return self.q

    def _json_body(self, limit=65536):
        self.limits.append(limit)
        return self.body

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.hdrs[key] = value

    def send_error(self, code, *a, **kw):
        self.errors.append(code)
        self.code = code
        return 'error'

    def end_headers(self):
        self.ended = True


def _mk(**kw):
    return _Handler(**kw)


def _raiser(exc):
    def _fn(*a, **kw):
        raise exc

    return _fn


def _ar(**kw):
    """A stand-in for ``zyg_workflows.architecture_studio``."""
    base = {
        'MAX_DOC_BYTES': 1 << 20,
        'library': lambda: {'ok': True, 'drawings': ['a']},
        'load_project': lambda pid: {'ok': bool(pid), 'id': pid},
        'save_project': lambda doc, pid='', name='': {'ok': True, 'id': 'p1', 'objects': 3},
        'delete_project': lambda pid: {'ok': bool(pid)},
        'rename_project': lambda pid, name: {'ok': bool(name)},
        'ext_dispatch': lambda method, rest, payload: {'ok': True, 'method': method, 'rest': rest},
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


def _cs(**kw):
    """A stand-in for ``zyg_workflows.character_studio``."""
    base = {
        'spec': lambda: {'ok': True, 'fields': {}},
        'read': lambda cid, cdir: {'ok': True, 'id': cid},
        'edit': lambda cid, cdir, edits: {'ok': True, 'applied': edits},
        'resolve_body': lambda cid: {'body': 'anny', 'why': 'exact'},
        'body_axes': lambda bname: {'ok': True, 'axes': {}},
        'write_candidate': lambda bname, edits, note='': {'ok': True, 'applied': edits, 'path': '/x.json'},
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture
def arch(monkeypatch):
    """Install an architecture studio; the test may swap in another."""

    def _install(ar):
        monkeypatch.setattr(M, '_arch', lambda: ar)
        return ar

    monkeypatch.setattr(M, '_ARCH_MOD', {'m': None, 'err': 'ImportError: no studio'})
    _install(_ar())
    return _install


@pytest.fixture
def cstudio(monkeypatch):
    """Install a character studio plus a permissive id guard."""

    def _install(m, *, cdir='/chars/ada', medusa=False):
        monkeypatch.setattr(M, '_cstudio', lambda: m)
        monkeypatch.setattr(M, '_safe_char_dir', lambda cid: cdir)
        monkeypatch.setattr(M, '_is_medusa_char', lambda cid, d: medusa)
        return m

    monkeypatch.setattr(M, '_CSTUDIO_MOD', {'m': None, 'err': 'ImportError: no studio'})
    monkeypatch.setattr(M, '_NAME_CACHE', {})
    monkeypatch.setattr(M, '_LIST_CACHE', {'data': 'stale'})
    _install(_cs())
    return _install


@pytest.fixture
def no_studio(monkeypatch):
    """Both studios unimportable, the way a bare runner sees them."""
    monkeypatch.setattr(M, '_arch', lambda: None)
    monkeypatch.setattr(M, '_cstudio', lambda: None)
    monkeypatch.setattr(M, '_ARCH_MOD', {'m': None, 'err': 'ImportError: nope'})
    monkeypatch.setattr(M, '_CSTUDIO_MOD', {'m': None, 'err': 'ImportError: nope'})


@pytest.mark.parametrize(
    'meth,args',
    [
        ('_arch_unavailable', ()),
        ('_arch_get', ('/inspect/api/architecture',)),
        ('_arch_post', ('/inspect/api/architecture/save',)),
        ('_arch_ext', ('GET', '/inspect/api/architecture/ext/doors/list', {})),
        ('_cs_guard', ()),
        ('_cs_get', ('/inspect/api/char/spec',)),
        ('_cs_get', ('/inspect/api/char/bible',)),
        ('_cs_post', ('/inspect/api/char/bible/save',)),
        ('_cs_post', ('/inspect/api/char/body',)),
    ],
)
def test_without_a_studio_module_every_route_is_503(no_studio, meth, args):
    h = _mk()
    getattr(h, meth)(*args)
    obj, code = h.sent
    assert code == 503
    assert 'ImportError: nope' in obj['error']


def test_arch_get_library(arch):
    h = _mk()
    h._arch_get('/inspect/api/architecture')
    assert h.sent == ({'ok': True, 'drawings': ['a']}, 200)


@pytest.mark.parametrize('pid,code', [('p1', 200), ('', 404)])
def test_arch_get_project(arch, pid, code):
    h = _mk(query={'id': pid})
    h._arch_get('/inspect/api/architecture/project')
    assert h.sent[1] == code


@pytest.mark.parametrize('exc,code', [(ValueError('bad id'), 400), (OSError('disk gone'), 500)])
def test_arch_get_errors(arch, exc, code):
    arch(_ar(load_project=_raiser(exc)))
    h = _mk(query={'id': 'p1'})
    h._arch_get('/inspect/api/architecture/project')
    assert h.sent == ({'error': str(exc)[:200]}, code)


def test_arch_get_delegates_assistant_and_ext(arch, monkeypatch):
    seen = []
    monkeypatch.setattr(M._StudioApiMixin, '_arch_assist', lambda self, m, p: seen.append(('assist', m, p)))
    monkeypatch.setattr(M._StudioApiMixin, '_arch_ext', lambda self, m, p, pay: seen.append(('ext', m, p, pay)))
    h = _mk(query={'k': 'v'})
    h._arch_get('/inspect/api/architecture/assistant/info')
    h._arch_get('/inspect/api/architecture/ext/doors/list')
    assert seen == [
        ('assist', 'GET', '/inspect/api/architecture/assistant/info'),
        ('ext', 'GET', '/inspect/api/architecture/ext/doors/list', {'k': 'v'}),
    ]


@pytest.fixture
def ext_dispatch(monkeypatch):
    """Drive both dispatchers through one callable: ``run(which, res)``."""
    import zyg_workflows

    holder = {}

    def _fn(method, rest, payload):
        if isinstance(holder['res'], Exception):
            raise holder['res']
        return holder['res']

    monkeypatch.setattr(M, '_arch', lambda: _ar(ext_dispatch=_fn))
    fake = types.SimpleNamespace(dispatch=_fn)
    monkeypatch.setattr(zyg_workflows, 'studio_ext_dispatch', fake, raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.studio_ext_dispatch', fake)

    def _run(which, res, payload=None):
        holder['res'] = res
        h = _mk()
        if which == 'arch':
            out = h._arch_ext('POST', '/inspect/api/architecture/ext/doors/list', payload)
        else:
            out = h._studio_ext('POST', '/inspect/api/studio/doors/list', payload)
        return h, out

    return _run


@pytest.mark.parametrize('which', ['arch', 'studio'])
@pytest.mark.parametrize(
    'res,code',
    [({'ok': True, 'n': 1}, 200), ({'error': 'bad'}, 400), ({'error': 'bad', 'code': 422}, 422)],
)
def test_ext_dict_answers(ext_dispatch, which, res, code):
    h, out = ext_dispatch(which, res)
    assert out == 'json'
    assert h.sent == (res, code)


@pytest.mark.parametrize('which', ['arch', 'studio'])
def test_ext_raises_is_500(ext_dispatch, which):
    h, _ = ext_dispatch(which, RuntimeError('kaboom'))
    assert h.sent[1] == 500
    assert 'kaboom' in h.sent[0]['error']


@pytest.mark.parametrize('which', ['arch', 'studio'])
def test_ext_tuple_bytes_download(ext_dispatch, which):
    h, out = ext_dispatch(which, (b'PK\x03\x04', 'application/zip', 'pa"ck.zip'))
    assert out is None
    assert h.code == 200
    assert h.hdrs['Content-Type'] == 'application/zip'
    assert h.hdrs['Content-Disposition'] == 'attachment; filename="pack.zip"'
    assert h.hdrs['Content-Length'] == '4'
    assert h.hdrs['Cache-Control'] == 'no-store'
    assert h.ended is True
    assert h.wfile.getvalue() == b'PK\x03\x04'


@pytest.mark.parametrize('which', ['arch', 'studio'])
def test_ext_tuple_str_without_mime_or_name(ext_dispatch, which):
    h, out = ext_dispatch(which, ('hello',))
    assert out is None
    assert h.hdrs['Content-Type'] == 'application/octet-stream'
    assert 'Content-Disposition' not in h.hdrs
    assert h.wfile.getvalue() == b'hello'


def test_studio_ext_import_failure_is_500(monkeypatch):
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, 'studio_ext_dispatch', raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.studio_ext_dispatch', None)
    h = _mk()
    h._studio_ext('GET', '/inspect/api/studio/', None)
    assert h.sent[1] == 500


@pytest.fixture
def assistant(monkeypatch):
    import zyg_workflows

    def _install(**kw):
        base = {
            'BODY_LIMIT': 1 << 20,
            'handle_get': lambda path, q: ({'ok': True, 'where': 'get'}, 200),
            'handle_post': lambda path, body: ({'ok': True, 'where': 'post'}, 201),
        }
        base.update(kw)
        fake = types.SimpleNamespace(**base)
        monkeypatch.setattr(zyg_workflows, 'arch_assistant', fake, raising=False)
        monkeypatch.setitem(sys.modules, 'zyg_workflows.arch_assistant', fake)
        return fake

    _install()
    return _install


def test_arch_assist_import_failure_is_503(monkeypatch):
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, 'arch_assistant', raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.arch_assistant', None)
    h = _mk()
    h._arch_assist('GET', '/inspect/api/architecture/assistant/info')
    assert h.sent[1] == 503
    assert 'assistant unavailable' in h.sent[0]['error']


@pytest.mark.parametrize('method,where,code', [('GET', 'get', 200), ('POST', 'post', 201)])
def test_arch_assist_json(assistant, method, where, code):
    h = _mk()
    assert h._arch_assist(method, '/inspect/api/architecture/assistant/job') == 'json'
    assert h.sent == ({'ok': True, 'where': where}, code)
    if method == 'POST':
        assert h.limits == [1 << 20]


def test_arch_assist_raises_is_500(assistant):
    def _boom(path, q):
        raise KeyError('job')

    assistant(handle_get=_boom)
    h = _mk()
    h._arch_assist('GET', '/inspect/api/architecture/assistant/job')
    assert h.sent[1] == 500


@pytest.mark.parametrize(
    'out,mime,payload',
    [((b'\x89PNG', 'image/png'), 'image/png', b'\x89PNG'), (('raw',), 'application/octet-stream', b'raw')],
)
def test_arch_assist_tuple_is_a_file(assistant, out, mime, payload):
    assistant(handle_get=lambda path, q: (out, 200))
    h = _mk()
    assert h._arch_assist('GET', '/inspect/api/architecture/assistant/picture') is None
    assert h.code == 200
    assert h.hdrs['Content-Type'] == mime
    assert h.hdrs['Content-Length'] == str(len(payload))
    assert h.ended is True
    assert h.wfile.getvalue() == payload


def test_arch_post_delegates_assistant(arch, monkeypatch):
    seen = []
    monkeypatch.setattr(M._StudioApiMixin, '_arch_assist', lambda self, m, p: seen.append((m, p)))
    _mk()._arch_post('/inspect/api/architecture/assistant/start')
    assert seen == [('POST', '/inspect/api/architecture/assistant/start')]


def test_arch_post_delegates_ext_with_a_raised_body_cap(arch, monkeypatch):
    seen = []
    monkeypatch.setattr(M._StudioApiMixin, '_arch_ext', lambda self, m, p, pay: seen.append((m, p, pay)))
    h = _mk(body={'doc': {}})
    h._arch_post('/inspect/api/architecture/ext/doors/apply')
    assert seen == [('POST', '/inspect/api/architecture/ext/doors/apply', {'doc': {}})]
    assert h.limits == [(1 << 20) + (1 << 16)]


def test_arch_post_save_logs_and_returns_the_id(arch):
    h = _mk(body={'doc': {'objects': []}, 'id': 'p1', 'name': 'House'})
    h._arch_post('/inspect/api/architecture/save')
    assert h.sent == ({'ok': True, 'id': 'p1', 'objects': 3}, 200)
    assert h.limits == [(1 << 20) + (1 << 16)]


def test_arch_post_save_failure_is_400(arch):
    arch(_ar(save_project=lambda doc, pid='', name='': {'ok': False, 'error': 'too big'}))
    h = _mk(body={})
    h._arch_post('/inspect/api/architecture/save')
    assert h.sent == ({'ok': False, 'error': 'too big'}, 400)


@pytest.mark.parametrize(
    'path,body,code',
    [
        ('/inspect/api/architecture/delete', {'id': 'p1'}, 200),
        ('/inspect/api/architecture/delete', {}, 404),
        ('/inspect/api/architecture/rename', {'id': 'p1', 'name': 'Barn'}, 200),
        ('/inspect/api/architecture/rename', {'id': 'p1'}, 400),
    ],
)
def test_arch_post_delete_and_rename(arch, path, body, code):
    h = _mk(body=body)
    h._arch_post(path)
    assert h.sent[1] == code


@pytest.mark.parametrize('exc,code', [(ValueError('nope'), 400), (OSError('ro fs'), 500)])
def test_arch_post_errors(arch, exc, code):
    arch(_ar(delete_project=_raiser(exc)))
    h = _mk(body={'id': 'p1'})
    h._arch_post('/inspect/api/architecture/delete')
    assert h.sent == ({'error': str(exc)[:200]}, code)


def test_arch_unknown_paths_are_404(arch):
    for meth, path in [('_arch_get', '/inspect/api/architecture/x'), ('_arch_post', '/inspect/api/architecture/y')]:
        h = _mk(body={})
        assert getattr(h, meth)(path) == 'error'
        assert h.errors == [404]


def test_cs_guard_happy(cstudio):
    h = _mk(query={'id': 'ada'})
    m, cid, cdir = h._cs_guard()
    assert (cid, cdir) == ('ada', '/chars/ada')
    assert m.spec() == {'ok': True, 'fields': {}}


def test_cs_guard_rejects_an_unsafe_id(cstudio):
    cstudio(_cs(), cdir=None)
    h = _mk(query={'id': '../etc'})
    assert h._cs_guard() is None
    assert h.errors == [404]


@pytest.mark.parametrize('medusa,scope', [(True, ''), (False, 'medusa')])
def test_cs_guard_is_fail_closed_across_scopes(cstudio, medusa, scope):
    cstudio(_cs(), medusa=medusa)
    h = _mk(query={'id': 'ada', 'scope': scope})
    assert h._cs_guard() is None
    assert h.errors == [404]


_GUARDED = [
    ('_cs_get', '/inspect/api/char/bible'),
    ('_cs_post', '/inspect/api/char/bible/save'),
    ('_cs_post', '/inspect/api/char/body'),
    ('_cs_post', '/inspect/api/char/body/save'),
    ('_cs_post', '/inspect/api/char/plates'),
]


@pytest.mark.parametrize('meth,path', _GUARDED)
def test_a_failed_guard_stops_every_guarded_route(cstudio, meth, path):
    cstudio(_cs(), cdir=None)
    h = _mk(query={'id': 'ada'})
    assert getattr(h, meth)(path) is None
    assert h.errors == [404]


def test_cs_get_spec(cstudio):
    h = _mk()
    h._cs_get('/inspect/api/char/spec')
    assert h.sent == ({'ok': True, 'fields': {}}, 200)


@pytest.mark.parametrize('out,code', [({'ok': True, 'id': 'ada'}, 200), ({'ok': False}, 404)])
def test_cs_get_bible(cstudio, out, code):
    cstudio(_cs(read=lambda cid, cdir: out))
    h = _mk(query={'id': 'ada'})
    h._cs_get('/inspect/api/char/bible')
    assert h.sent == (out, code)


@pytest.mark.parametrize('meth,path', [('_cs_get', '/inspect/api/char/x'), ('_cs_post', '/inspect/api/char/y')])
def test_cs_unknown_paths_are_404(cstudio, meth, path):
    h = _mk(query={'id': 'ada'})
    assert getattr(h, meth)(path) == 'error'


def test_cs_post_bible_save_clears_the_caches(cstudio):
    h = _mk(query={'id': 'ada'}, body={'edits': {'name': 'Ada'}})
    M._NAME_CACHE['ada'] = 'old'
    h._cs_post('/inspect/api/char/bible/save')
    assert h.sent == ({'ok': True, 'applied': {'name': 'Ada'}}, 200)
    assert h.limits == [256000]
    assert 'ada' not in M._NAME_CACHE
    assert M._LIST_CACHE['data'] is None


def test_cs_post_bible_save_failure_keeps_the_caches(cstudio):
    cstudio(_cs(edit=lambda cid, cdir, edits: {'ok': False, 'error': 'not editable'}))
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/bible/save')
    assert h.sent[1] == 400
    assert M._LIST_CACHE['data'] == 'stale'


def test_cs_post_bible_save_raises_is_500(cstudio):
    cstudio(_cs(edit=_raiser(KeyError('field'))))
    h = _mk(query={'id': 'ada'}, body={'edits': {}})
    h._cs_post('/inspect/api/char/bible/save')
    assert h.sent[1] == 500
    assert h.sent[0]['error'].startswith('KeyError')


@pytest.mark.parametrize('path', ['/inspect/api/char/body', '/inspect/api/char/body/save', '/inspect/api/char/plates'])
def test_body_panel_without_a_linked_body_is_404(cstudio, path):
    link = {'body': '', 'why': 'no body for this character'}
    cstudio(_cs(resolve_body=lambda cid: link))
    h = _mk(query={'id': 'ada'})
    h._cs_post(path)
    assert h.sent == ({'ok': False, 'state': 'unavailable', 'link': link, 'error': link['why']}, 404)


def test_body_axes_ok_carries_the_link(cstudio):
    h = _mk(query={'id': 'ada'})
    h._cs_post('/inspect/api/char/body')
    assert h.sent[1] == 200
    assert h.sent[0]['link'] == {'body': 'anny', 'why': 'exact'}
    assert h.limits == [40_000]


def test_body_axes_raises_is_500(cstudio):
    cstudio(_cs(body_axes=_raiser(RuntimeError('no axes'))))
    h = _mk(query={'id': 'ada'})
    h._cs_post('/inspect/api/char/body')
    assert h.sent[1] == 500
    assert h.sent[0]['error'] == 'RuntimeError: no axes'


def test_body_save_ok_logs_the_candidate(cstudio):
    h = _mk(query={'id': 'ada'}, body={'edits': {'bust': 1.0}, 'note': 'S05'})
    h._cs_post('/inspect/api/char/body/save')
    assert h.sent[1] == 200
    assert h.sent[0]['applied'] == {'bust': 1.0}
    assert h.sent[0]['link']['body'] == 'anny'


def test_body_save_failure_is_400(cstudio):
    cstudio(_cs(write_candidate=lambda b, e, note='': {'ok': False, 'error': 'locked'}))
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/body/save')
    assert h.sent[1] == 400


def test_body_save_raises_is_500(cstudio):
    cstudio(_cs(write_candidate=_raiser(ValueError('bad axis'))))
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/body/save')
    assert h.sent[1] == 500


@pytest.fixture
def plates(monkeypatch):
    """Stand in for ``zyg_workflows.geom.body_plates`` (a Blender job)."""
    import zyg_workflows.geom as geom

    def _install(**kw):
        base = {
            'build': lambda b, char_id='', force=False, size=768, samples=24: {'built': [b, size, samples, force]},
            'load_manifest': lambda bname, cid: {'loaded': bname},
            'plates_dir': lambda bname, cid: f'/plates/{bname}/{cid}',
        }
        base.update(kw)
        fake = types.SimpleNamespace(**base)
        monkeypatch.setattr(geom, 'body_plates', fake, raising=False)
        monkeypatch.setitem(sys.modules, 'zyg_workflows.geom.body_plates', fake)
        return fake

    _install()
    return _install


def test_plates_load_manifest(cstudio, plates):
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/plates')
    link = {'body': 'anny', 'why': 'exact'}
    assert h.sent == ({'ok': True, 'manifest': {'loaded': 'anny'}, 'link': link, 'dir': '/plates/anny/ada'}, 200)


def test_plates_render_on_request(cstudio, plates):
    h = _mk(query={'id': 'ada'}, body={'render': 1, 'force': 1, 'size': '512', 'samples': '8'})
    h._cs_post('/inspect/api/char/plates')
    assert h.sent[0]['manifest'] == {'built': ['anny', 512, 8, True]}


def test_plates_missing_manifest_is_404(cstudio, plates):
    plates(load_manifest=lambda bname, cid: None)
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/plates')
    obj, code = h.sent
    assert code == 404
    assert obj['state'] == 'not_found'
    assert obj['dir'] == '/plates/anny/ada'


def test_plates_raises_is_500(cstudio, plates):
    def _boom(bname, cid):
        raise OSError('render dir gone')

    plates(load_manifest=_boom)
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/plates')
    assert h.sent[1] == 500
    assert h.sent[0]['error'] == 'OSError: render dir gone'


def test_plates_import_failure_is_500(cstudio, monkeypatch):
    import zyg_workflows.geom as geom

    monkeypatch.delattr(geom, 'body_plates', raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.geom.body_plates', None)
    h = _mk(query={'id': 'ada'}, body={})
    h._cs_post('/inspect/api/char/plates')
    assert h.sent[1] == 500
