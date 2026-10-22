# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for :mod:`zyg_dashboard.kanban_server.creature_mesh`.

The module is a ``BaseHTTPRequestHandler`` mixin, not a Flask blueprint, so every route is a
bound method leaning on the sibling mixins' ``_query`` / ``_json_body`` / ``_send_json`` /
``_send_ranged`` surface. ``_Rec`` supplies exactly that surface and records what was sent; the
creature, song, movement and mesh roots go to ``tmp_path`` and the forwarding helpers are
monkeypatched, so nothing here touches the network, the GPU or the real trees.
"""

import io
import os
import contextlib
import json
import urllib.error
import urllib.request

import pytest

import zyg_dashboard.kanban_server.creature_mesh as M

CID = 'abcdef012345'
JID = 'a' * 12
REJECT = {'reason': 'rejected from the Kanban review gate'}


class _Rec:
    """The handler surface the mixin inherits from its siblings."""

    def __init__(self, query=None, body=None, wfile=None):
        self.q = dict(query or {})
        self.body = {} if body is None else body
        self.wfile = io.BytesIO() if wfile is None else wfile
        self.code, self.hdrs, self.ended = None, {}, False
        self.errors, self.limits = [], []
        self.json = self.ranged = self.thumbed = None

    def _query(self):
        return self.q

    def _json_body(self, limit=None):
        self.limits.append(limit)
        return self.body

    def _send_json(self, out, code=200):
        self.json = (out, code)
        return 'json'

    def _send_ranged(self, fp, ctype, cache=None, attach=None):
        self.ranged = {'fp': fp, 'ctype': ctype, 'cache': cache, 'attach': attach}
        return 'ranged'

    def _send_image_thumb_or_full(self, fp, thumb):
        self.thumbed = (fp, thumb)

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.hdrs[key] = value

    def end_headers(self):
        self.ended = True

    def send_error(self, code, *a, **kw):
        self.errors.append(code)
        self.code = code
        return 'error'


class _Handler(M._CreatureMeshMixin, _Rec):
    pass


class _Boom(io.BytesIO):
    """A wfile whose write dies the way a closed browser tab does."""

    def __init__(self, exc=BrokenPipeError):
        super().__init__()
        self.exc = exc

    def write(self, data):
        raise self.exc('client went away')


def _write(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path


def _deny_open(monkeypatch, victim):
    """Make exactly one path unreadable, leaving every other open() alone."""
    real = open

    def _open(path, *a, **kw):
        if str(path) == str(victim):
            raise OSError('permission denied')
        return real(path, *a, **kw)

    monkeypatch.setattr('builtins.open', _open)


def _gone(path):
    raise OSError('gone')


@pytest.fixture
def croot(tmp_path, monkeypatch):
    """Redirect both creature trees (dataset + output) onto tmp_path."""
    ds, out = os.path.realpath(str(tmp_path / 'ds')), os.path.realpath(str(tmp_path / 'out'))
    os.makedirs(ds)
    os.makedirs(out)
    monkeypatch.setattr(M, '_CREATURE_ROOT', ds)
    monkeypatch.setattr(M, '_CREATURE_OUT_ROOT', out)
    monkeypatch.setattr(M, '_creature_weights', lambda cid: None)
    monkeypatch.setattr(M, '_creature_dir', lambda cid, root: '')
    monkeypatch.setattr(M, '_creature_manifest', lambda d: {})
    monkeypatch.setattr(M, '_is_flux1', lambda fam: False)
    return ds, out


@pytest.mark.parametrize('cid', ['', 'nope', 'ABCDEF012345', 'abcdef01234', CID])
def test_creature_sheet_fails_closed(croot, cid):
    # the last id is well-formed but has no sheet parked under either candidate name
    h = _Handler(query={'id': cid})
    assert h._creature_sheet() == 'error'
    assert h.errors == [404]


@pytest.mark.parametrize('rel', ['contact_sheet/sheet.png', 'sheet.png'])
@pytest.mark.parametrize('closed', [False, True], ids=['sent', 'client-gone-mid-write'])
def test_creature_sheet_serves_both_candidates(croot, rel, closed):
    _write(os.path.join(croot[0], CID, *rel.split('/')), b'\x89PNG...')
    h = _Handler(query={'id': CID}, wfile=_Boom() if closed else None)
    assert h._creature_sheet() is None
    assert h.code == 200
    assert h.hdrs == {'Content-Type': 'image/png', 'Cache-Control': 'no-store', 'Content-Length': '7'}
    assert h.ended is True
    assert closed or h.wfile.getvalue() == b'\x89PNG...'


def test_creature_sheet_unreadable_file_breaks_to_404(croot, monkeypatch):
    _deny_open(monkeypatch, _write(os.path.join(croot[0], CID, 'contact_sheet', 'sheet.png')))
    h = _Handler(query={'id': CID})
    assert h._creature_sheet() == 'error'
    assert h.errors == [404]


@pytest.mark.parametrize('spec', ['nope:a.png', 'preview:', 'preview:../x.png', 'val:a.png', 'sheet:a.png'])
def test_creature_img_fails_closed(croot, spec):
    # bad category · no name · a traversal _NAME_RE refuses · 'val' with no weights · no dataset dir
    cat, name = spec.split(':', 1)
    h = _Handler(query={'id': CID, 'cat': cat, 'name': name})
    assert h._creature_img() == 'error'
    assert h.errors == [404]


def test_creature_img_rejects_a_name_with_a_path_fragment(croot, monkeypatch):
    # _NAME_RE forbids '/', so the basename guard needs a looser pattern to be reached at all
    monkeypatch.setattr(M, '_NAME_RE', M.re.compile(r'^.+\.png$'))
    h = _Handler(query={'id': CID, 'cat': 'preview', 'name': 'sub/a.png'})
    assert h._creature_img() == 'error'
    assert h.errors == [404]


def test_creature_img_withholds_flux1_pixels(croot, monkeypatch):
    monkeypatch.setattr(M, '_creature_manifest', lambda d: {'train_family': 'flux1-dev'})
    monkeypatch.setattr(M, '_creature_dir', lambda cid, root: os.path.join(root, cid))
    monkeypatch.setattr(M, '_is_flux1', lambda fam: fam == 'flux1-dev')
    h = _Handler(query={'id': CID, 'cat': 'preview', 'name': 'a.png'})
    assert h._creature_img() == 'error'
    assert h.errors == [404]


def test_creature_img_val_serves_from_the_output_tree(croot, monkeypatch):
    wdir = os.path.join(croot[1], CID, 'run1')
    fp = _write(os.path.join(wdir, 'validation_images', 'a.png'))
    monkeypatch.setattr(M, '_creature_weights', lambda cid: {'dir': wdir, 'family': 'sdxl'})
    h = _Handler(query={'id': CID, 'cat': 'val', 'name': 'a.png', 'thumb': '1'})
    assert h._creature_img() is None
    assert h.thumbed == (fp, True)


@pytest.mark.parametrize('cat', ['preview', 'sheet', 'cell', 'mesh'])
def test_creature_img_serves_every_dataset_category(croot, monkeypatch, cat):
    cdir = os.path.join(croot[0], CID)
    monkeypatch.setattr(M, '_creature_dir', lambda cid, root: cdir)
    sub = M._CREATURE_CATS[cat][0]
    fp = _write(os.path.join(cdir, sub, 'a.png') if sub else os.path.join(cdir, 'a.png'))
    h = _Handler(query={'id': CID, 'cat': cat, 'name': 'a.png'})
    assert h._creature_img() is None
    assert h.thumbed == (fp, False)


@pytest.mark.parametrize('escape', [True, False], ids=['dir-outside-the-root', 'missing-file'])
def test_creature_img_refuses_what_is_not_inside_the_tree(croot, monkeypatch, tmp_path, escape):
    cdir = os.path.realpath(str(tmp_path / 'elsewhere')) if escape else os.path.join(croot[0], CID)
    os.makedirs(cdir, exist_ok=True)
    monkeypatch.setattr(M, '_creature_dir', lambda cid, root: cdir)
    h = _Handler(query={'id': CID, 'cat': 'preview', 'name': 'gone.png'})
    assert h._creature_img() == 'error'
    assert h.errors == [404]


@pytest.fixture
def song(tmp_path, monkeypatch):
    d = os.path.realpath(str(tmp_path / 'song'))
    os.makedirs(d)
    monkeypatch.setattr(M, '_km_dir', lambda sid: d if sid == 'song-1' else '')
    monkeypatch.setattr(M, '_km_download_name', lambda song_dir, fn: 'Red Train - master.mp3')
    return d


@pytest.mark.parametrize('spec', ['nope:master.mp3', 'song-1:secrets.env', 'song-1:frames/f9.png'])
def test_km_file_fails_closed(song, spec):
    # unknown song · a name outside the fixed set · a well-formed frame that is not on disk
    sid, fn = spec.split(':', 1)
    h = _Handler(query={'id': sid, 'f': fn})
    assert h._km_file() == 'error'
    assert h.errors == [404]


@pytest.mark.parametrize('dl', ['', '1', 'true', 'yes'])
def test_km_file_streams_a_fixed_name(song, dl):
    fp = _write(os.path.join(song, 'master.mp3'))
    h = _Handler(query={'id': 'song-1', 'f': 'master.mp3', 'dl': dl})
    assert h._km_file() == 'ranged'
    attach = 'Red Train - master.mp3' if dl else None
    assert h.ranged == {'fp': fp, 'ctype': 'audio/mpeg', 'cache': 'public, max-age=3600', 'attach': attach}


@pytest.mark.parametrize(
    ('fn', 'built', 'mime'),
    [('frames/f1.png', 'frames/f001.png', 'image/png'), ('frames/t0042.jpg', 'frames/t042.jpg', 'image/jpeg')],
)
def test_km_file_rebuilds_a_storyboard_frame_name(song, fn, built, mime):
    fp = _write(os.path.join(song, *built.split('/')))
    h = _Handler(query={'id': 'song-1', 'f': fn})
    assert h._km_file() == 'ranged'
    assert (h.ranged['fp'], h.ranged['ctype']) == (fp, mime)


@pytest.fixture
def fwd(monkeypatch):
    """Record every same-host hop and reply with a scripted (out, code)."""
    calls = []
    reply = {'out': {'ok': True}, 'code': 200}

    def _km_forward(path, payload=None, method='GET', timeout=30):
        calls.append({'path': path, 'payload': payload, 'method': method, 'timeout': timeout})
        return reply['out'], reply['code']

    monkeypatch.setattr(M, '_km_forward', _km_forward)
    monkeypatch.setattr(M, '_KM_CACHE', {'data': 'stale'})
    monkeypatch.setattr(M, '_MV_CACHE', {'data': 'stale'})
    return calls, reply


# (handler, route tail, forward timeout, _json_body limit, the list cache a success clears)
POST_ROUTES = [
    ('_km_post', 'kidsmusic/start', 30, 200_000, None),
    ('_km_post', 'kidsmusic/stop', 30, 200_000, None),
    ('_km_post', 'kidsmusic/delete', 30, 200_000, '_KM_CACHE'),
    ('_km_post', 'kidsmusic/remix', 240, 200_000, '_KM_CACHE'),
    ('_ks_post', 'kidseries/start', 30, 50_000, None),
    ('_ks_post', 'kidseries/stop', 30, 50_000, None),
    ('_mv_post', 'movement/start', 30, 50_000, None),
    ('_mv_post', 'movement/stop', 30, 50_000, None),
    ('_mv_post', 'movement/prompt', 20, 50_000, None),
    ('_mv_post', 'movement/presets', 30, 50_000, None),
    ('_mv_post', 'movement/plate', 30, 50_000, None),
    ('_mv_post', 'movement/driver', 30, 50_000, None),
    ('_mv_post', 'movement/delete', 30, 50_000, '_MV_CACHE'),
]


@pytest.mark.parametrize(('meth', 'route', 'timeout', 'limit', 'cache'), POST_ROUTES)
@pytest.mark.parametrize('code', [200, 409], ids=['accepted', 'refused'])
def test_each_post_route_forwards_to_the_pipeline(fwd, meth, route, timeout, limit, cache, code):
    calls, reply = fwd
    reply['out'], reply['code'] = ({'ok': True} if code == 200 else {'error': 'busy'}), code
    body = {'id': 'song-1', 'song': {'theme': 'trains'}, 'series': 'bugs', 'subject_id': CID}
    h = _Handler(body=body)
    assert getattr(h, meth)(f'/inspect/api/{route}') == 'json'
    assert h.json == (reply['out'], code)
    assert calls == [{'path': f'/api/internal/{route}', 'payload': body, 'method': 'POST', 'timeout': timeout}]
    assert h.limits == [limit]
    if cache:
        # the card must disappear (or show the new mix) only once the hop has said yes
        assert getattr(M, cache)['data'] == (None if code == 200 else 'stale')


def test_km_post_shelf_is_a_local_write(fwd, monkeypatch):
    seen = []
    monkeypatch.setattr(M, '_km_file_song', lambda *a: (seen.append(a), ({'ok': True}, 200))[1])
    h = _Handler(body={'id': 'song-1', 'family': ' Lullaby ', 'shelf': ' Sleepy '})
    assert h._km_post('/inspect/api/kidsmusic/shelf') == 'json'
    assert seen == [('song-1', 'lullaby', 'sleepy')]  # the id is passed on, family and shelf folded
    assert h.json == ({'ok': True}, 200)


@pytest.mark.parametrize(
    ('meth', 'route'),
    [('_km_post', 'kidsmusic/nope'), ('_ks_post', 'kidseries/nope'), ('_mv_post', 'movement/nope')],
)
def test_an_unknown_post_route_is_404(fwd, meth, route):
    h = _Handler(body={})
    assert getattr(h, meth)(f'/inspect/api/{route}') == 'error'
    assert h.errors == [404]


@pytest.fixture
def mesh(monkeypatch):
    """Registry of two bodies, a job memory, and a recording job starter."""
    started = []

    def _start(kind, name, argv, dry_run=False):
        started.append({'kind': kind, 'name': name, 'argv': argv, 'dry_run': dry_run})
        return {'ok': True, 'job_id': JID}, 200

    monkeypatch.setattr(M, '_mesh_names', lambda: {'adult_male', 'adult_female'})
    monkeypatch.setattr(M, '_mesh_job_start', _start)
    monkeypatch.setattr(M, '_MESH_JOBS_MEM', {JID: {'argv': ['py', '-m', 'geom'], 'state': 'done'}})
    monkeypatch.setattr(M, '_MESH_DRYRUN_OK', set())
    monkeypatch.setattr(M, '_MESH_CACHE', {'data': 'stale'})
    return started


@pytest.mark.parametrize(
    ('body', 'expect'),
    [
        ({'job_id': JID}, ({'state': 'done', 'cmd': 'py -m geom'}, 200)),
        ({'job_id': 'nope'}, ({'error': 'bad job id'}, 400)),
        ({'job_id': 'b' * 12}, ({'error': 'unknown job'}, 404)),
    ],
)
def test_mesh_post_job_poll(mesh, body, expect):
    h = _Handler()
    h.body = body
    h._mesh_post('/mesh/api/job')
    assert h.json == expect
    assert h.limits == [20_000]


def test_mesh_post_gate_runs_the_anthro_check(mesh):
    h = _Handler(body={'name': 'adult_male'})
    assert h._mesh_post('/mesh/api/gate') == 'json'
    assert mesh[0]['kind'] == 'gate'
    assert mesh[0]['argv'][1:] == ['-m', 'geom.anthro', 'check', 'adult_male']


@pytest.mark.parametrize('route', ['/mesh/api/gate', '/mesh/api/reissue'])
def test_mesh_post_refuses_an_unregistered_body(mesh, route):
    h = _Handler(body={'name': 'nobody'})
    h._mesh_post(route)
    out, code = h.json
    assert code == 400
    assert out['known'] == ['adult_female', 'adult_male']


@pytest.mark.parametrize(
    ('body', 'approved', 'code', 'flag'),
    [
        ({'name': 'adult_male'}, False, 200, '--dry-run'),
        ({'name': 'adult_male', 'dry_run': False}, False, 409, None),
        ({'name': 'adult_male', 'dry_run': False, 'force': True}, True, 200, '--force'),
    ],
    ids=['dry-run-by-default', 'confirm-without-one-is-refused', 'confirmed-after-one'],
)
def test_mesh_post_reissue(mesh, monkeypatch, body, approved, code, flag):
    if approved:
        monkeypatch.setattr(M, '_MESH_DRYRUN_OK', {'adult_male'})
    h = _Handler(body=body)
    h._mesh_post('/mesh/api/reissue')
    assert h.json[1] == code
    if code == 409:
        assert 'dry run' in h.json[0]['error']
        return
    assert mesh[0]['dry_run'] is bool(body.get('dry_run', True))
    assert flag in mesh[0]['argv']
    assert ('--dry-run' in mesh[0]['argv']) is mesh[0]['dry_run']


@pytest.mark.parametrize(('anat', 'code'), [('toe_declash=0.005,hip_w=-1.5', 200), ('make the toes nicer', 400)])
def test_mesh_post_reissue_checks_set_anatomy(mesh, anat, code):
    h = _Handler(body={'name': 'adult_male', 'set_anatomy': anat})
    h._mesh_post('/mesh/api/reissue')
    assert h.json[1] == code
    if code == 200:
        assert mesh[0]['argv'][-2:] == ['--set-anatomy', anat]
    else:
        assert 'set_anatomy must be k=v' in h.json[0]['error']


@pytest.mark.parametrize(
    ('body', 'code', 'frag'),
    [
        ({'char_id': ''}, 400, 'char_id must be'),
        ({'char_id': 'bad/slash'}, 400, 'char_id must be'),
        ({'char_id': 'adult_male'}, 409, 'already registered'),
        ({'char_id': 'new_body', 'base': 'other'}, 400, "base must be 'male' or 'female'"),
    ],
)
def test_mesh_post_derive_fails_closed(mesh, body, code, frag):
    h = _Handler(body=body)
    h._mesh_post('/mesh/api/derive')
    assert h.json[1] == code
    assert frag in h.json[0]['error']


def test_mesh_post_derive_starts_a_job_and_clears_the_cache(mesh):
    h = _Handler(body={'char_id': 'new_body', 'base': 'female', 'no_inherit_locals': True})
    assert h._mesh_post('/mesh/api/derive') == 'json'
    argv = mesh[0]['argv']
    assert argv[1:] == ['-m', 'geom.mesh_skeletons', 'derive', 'new_body', '--base', 'female', '--no-inherit-locals']
    assert M._MESH_CACHE['data'] is None


# (body key, CLI flag, a value the CLI documents, a value that must never reach argv)
DERIVE = [
    ('phenotype', '--phenotype', 'nose_w=0.5,chin=-1', 'nose_w=wide'),
    ('bone_scale', '--bone-scale', 'spine.01=1.2', 'spine 01=1.2'),
    ('local', '--local', 'hand.l=0.5', 'hand.l'),
    ('anatomy', '--anatomy', 'toe_declash=0.005', 'toe_declash=0.005;rm -rf'),
    ('target_height', '--target-height', '1.75', 'tall'),
    ('ancestry', '--ancestry', 'north-west europe', 'north!west'),
    ('stylization_intent', '--stylization-intent', 'stylised realism', 'styl$ised'),
    ('declared_by', '--declared-by', 'ada@example.com', 'ada<script>'),
    ('note', '--note', 'derived for the pilot', 'a\x01note'),
]


@pytest.mark.parametrize(('key', 'flag', 'good', 'bad'), DERIVE)
def test_mesh_post_derive_checks_each_flag(mesh, key, flag, good, bad):
    h = _Handler(body={'char_id': 'new_body', key: good})
    h._mesh_post('/mesh/api/derive')
    assert h.json[1] == 200
    assert mesh[0]['argv'][-2:] == [flag, good]
    h = _Handler(body={'char_id': 'new_body', key: bad})
    h._mesh_post('/mesh/api/derive')
    assert h.json[1] == 400
    assert h.json[0]['error'].startswith(f'{key} has the wrong shape')


def test_mesh_post_derive_passes_a_failure_through(mesh, monkeypatch):
    monkeypatch.setattr(M, '_mesh_job_start', lambda *a, **kw: ({'error': 'busy'}, 409))
    h = _Handler(body={'char_id': 'new_body'})
    h._mesh_post('/mesh/api/derive')
    assert h.json == ({'error': 'busy'}, 409)
    assert M._MESH_CACHE['data'] == 'stale'


def test_mesh_post_unknown_route_is_404(mesh):
    h = _Handler(body={})
    assert h._mesh_post('/mesh/api/nope') == 'error'
    assert h.errors == [404]


@pytest.fixture
def mvroot(tmp_path, monkeypatch):
    root = os.path.realpath(str(tmp_path / 'mv'))
    os.makedirs(root)
    monkeypatch.setattr(M, '_MV_OUT_ROOT', root)
    return root


@pytest.mark.parametrize('meth', ['_mv_file', '_mv_thumb'])
@pytest.mark.parametrize('jid', ['NOPE', CID], ids=['bad-job-id', 'missing-clip'])
def test_mv_fails_closed(mvroot, meth, jid):
    h = _Handler(query={'id': jid})
    assert getattr(h, meth)() == 'error'
    assert h.errors == [404]


def test_mv_file_streams_the_clip(mvroot):
    fp = _write(os.path.join(mvroot, CID, 'vace_static.mp4'))
    h = _Handler(query={'id': CID})
    assert h._mv_file() == 'ranged'
    assert h.ranged == {'fp': fp, 'ctype': 'video/mp4', 'cache': 'no-store', 'attach': None}


@pytest.fixture
def poster(mvroot, tmp_path, monkeypatch):
    """A clip to poster, with the thumb cache path under tmp_path."""
    _write(os.path.join(mvroot, CID, 'vace_static.mp4'))
    tp = str(tmp_path / 'cache' / 'poster.jpg')
    monkeypatch.setattr(M, '_thumb_path', lambda fp, mt: tp)
    return tp


@pytest.mark.parametrize('cached', [True, False], ids=['already-cached', 'extracted-once'])
def test_mv_thumb_serves_a_poster(poster, monkeypatch, cached):
    if cached:
        _write(poster, b'JPEG')
        monkeypatch.setattr(M, '_make_thumb', lambda fp, dst: pytest.fail('should not re-extract'))
    else:
        monkeypatch.setattr(M, '_make_thumb', lambda fp, dst: bool(_write(dst, b'JPEG')))
    h = _Handler(query={'id': CID})
    assert h._mv_thumb() is None
    assert h.code == 200
    assert h.hdrs == {'Content-Type': 'image/jpeg', 'Content-Length': '4', 'Cache-Control': 'public, max-age=86400'}
    assert h.wfile.getvalue() == b'JPEG'


@pytest.mark.parametrize('broken', ['extraction', 'mtime', 'unreadable-poster'])
def test_mv_thumb_fails_closed(poster, monkeypatch, broken):
    if broken == 'extraction':
        monkeypatch.setattr(M, '_make_thumb', lambda fp, dst: False)
    elif broken == 'mtime':
        monkeypatch.setattr(M.os.path, 'getmtime', _gone)
    else:
        _deny_open(monkeypatch, _write(poster, b'JPEG'))
    h = _Handler(query={'id': CID})
    assert h._mv_thumb() == 'error'
    assert h.errors == [404]


@pytest.mark.parametrize('exc', [BrokenPipeError, ConnectionResetError])
def test_mv_thumb_survives_a_closed_client(poster, exc):
    _write(poster, b'JPEG')
    h = _Handler(query={'id': CID}, wfile=_Boom(exc))
    assert h._mv_thumb() is None
    assert h.code == 200


@pytest.fixture
def decide(monkeypatch):
    """A token, and a urlopen that records the request and replies ok."""
    seen = {}
    monkeypatch.setattr(M, '_internal_token', lambda: 'tok')

    def _urlopen(req, timeout=None):
        seen.update(
            url=req.full_url,
            method=req.get_method(),
            token=req.get_header('X-zero-public-token'),
            payload=json.loads(req.data.decode('utf-8')),
            timeout=timeout,
        )
        return contextlib.closing(io.BytesIO(json.dumps({'ok': True}).encode('utf-8')))

    monkeypatch.setattr(urllib.request, 'urlopen', _urlopen)
    return seen


@pytest.mark.parametrize('body', [{'id': 'nope', 'action': 'approve'}, {'id': CID, 'action': 'maybe'}, {}])
def test_creature_decide_validates_its_body(decide, body):
    h = _Handler(body=body)
    h._creature_decide()
    assert h.json == ({'error': 'need {id: <12-hex>, action: approve|reject}'}, 400)


def test_creature_decide_needs_a_token(decide, monkeypatch):
    monkeypatch.setattr(M, '_internal_token', lambda: '')
    h = _Handler(body={'id': CID, 'action': 'approve'})
    h._creature_decide()
    out, code = h.json
    assert code == 503
    assert 'ZERO_PUBLIC_TOKEN' in out['error']


@pytest.mark.parametrize(('action', 'payload'), [('APPROVE', {}), ('reject', REJECT)])
def test_creature_decide_forwards_the_decision(decide, action, payload):
    h = _Handler(body={'id': CID, 'action': action})
    assert h._creature_decide() == 'json'
    assert h.json == ({'ok': True}, 200)
    assert decide['url'].endswith(f'/api/internal/creature/{CID}/{action.lower()}')
    assert (decide['method'], decide['token'], decide['payload'], decide['timeout']) == ('POST', 'tok', payload, 30)


def _http_error(raw):
    return lambda u: urllib.error.HTTPError(u, 409, 'Conflict', {}, io.BytesIO(raw))


DECIDE_FAILS = [
    (_http_error(b'{"error": "already decided"}'), ({'error': 'already decided'}, 409)),
    (_http_error(b'<html>not json</html>'), ({'error': 'pipeline API returned 409'}, 409)),
    (lambda u: urllib.error.URLError('down'), ({'error': 'pipeline API unreachable: <urlopen error down>'}, 502)),
]


@pytest.mark.parametrize(('raise_', 'expect'), DECIDE_FAILS, ids=['json-body', 'unreadable-body', 'unreachable'])
def test_creature_decide_passes_a_failure_through(decide, monkeypatch, raise_, expect):
    def _urlopen(req, timeout=None):
        raise raise_(req.full_url)

    monkeypatch.setattr(urllib.request, 'urlopen', _urlopen)
    h = _Handler(body={'id': CID, 'action': 'approve'})
    h._creature_decide()
    assert h.json == expect
