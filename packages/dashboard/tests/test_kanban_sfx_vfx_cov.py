# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for ``zyg_dashboard.kanban.sfx_vfx``.

Everything is offline: the eight lazy ``zyg_workflows`` loaders are fed fake
modules through ``sys.modules``, every library root is redirected at the
module's own constants, and the one background thread the module starts is
replaced by a synchronous shim.
"""

import os
import sys
import json
import base64
import wave
from types import SimpleNamespace

import pytest

from zyg_dashboard.kanban import sfx_vfx as mod


# ── helpers ────────────────────────────────────────────────────────────────


def _inject(monkeypatch, name, obj):
    """Make ``from zyg_workflows import <name>`` yield ``obj``."""
    import zyg_workflows

    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', obj)
    monkeypatch.setattr(zyg_workflows, name, obj, raising=False)


def _break(monkeypatch, name):
    """Make ``from zyg_workflows import <name>`` raise ImportError."""
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, name, raising=False)
    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', None)


def _write_wav(path, frames=800, ch=1, sr=8000, width=2):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(b'\0' * (frames * ch * width))
    return str(path)


LOADERS = [
    ('_alib', 'asset_library_service', '_ALIB_MOD'),
    ('_vfxa', 'vfx_ingest', '_VFXA_MOD'),
    ('_vfxfx', 'vfx_fx', '_VFXFX_MOD'),
    ('_crfx', 'creature_fx', '_CRFX_MOD'),
    ('_pfx', 'picture_fx', '_PFX_MOD'),
    ('_sfx_merger', 'sfx_merger', '_MERGE_MOD'),
    ('_music_studio', 'music_studio', '_MUSIC_MOD'),
    ('_voice_merger', 'voice_merger', '_VOICE_MERGE_MOD'),
]


# ── the eight lazy loaders ─────────────────────────────────────────────────


@pytest.mark.parametrize('fn_name,wf_name,slot', LOADERS)
def test_loader_imports_once(monkeypatch, fn_name, wf_name, slot):
    monkeypatch.setattr(mod, slot, {'m': None, 'err': ''})
    fake = SimpleNamespace(tag=wf_name)
    _inject(monkeypatch, wf_name, fake)
    fn = getattr(mod, fn_name)
    assert fn() is fake
    # second call takes the memoised slot, not the import
    _break(monkeypatch, wf_name)
    assert fn() is fake


@pytest.mark.parametrize('fn_name,wf_name,slot', LOADERS)
def test_loader_records_import_failure(monkeypatch, fn_name, wf_name, slot):
    monkeypatch.setattr(mod, slot, {'m': None, 'err': ''})
    _break(monkeypatch, wf_name)
    fn = getattr(mod, fn_name)
    assert fn() is None
    assert getattr(mod, slot)['err']
    # the remembered error short-circuits every later call
    _inject(monkeypatch, wf_name, SimpleNamespace())
    assert fn() is None


# ── _alib_probe ────────────────────────────────────────────────────────────


def test_probe_missing_file_is_zeros(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_ALIB_PROBE', {})
    assert mod._alib_probe(str(tmp_path / 'nope.wav')) == (0.0, 0, 0, 0)


def test_probe_reads_wav_header_and_memoises(monkeypatch, tmp_path):
    cache = {}
    monkeypatch.setattr(mod, '_ALIB_PROBE', cache)
    fp = _write_wav(tmp_path / 'a.wav', frames=4000, ch=2, sr=8000, width=2)
    assert mod._alib_probe(fp) == (0.5, 2, 8000, 16)
    assert cache[fp][1] == (0.5, 2, 8000, 16)
    # the memo hit returns without re-reading the header
    monkeypatch.setitem(sys.modules, 'wave', None)
    assert mod._alib_probe(fp) == (0.5, 2, 8000, 16)


def test_probe_broken_wav_falls_through_to_mutagen(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_ALIB_PROBE', {})
    fp = tmp_path / 'broken.wav'
    fp.write_bytes(b'not a riff header at all')
    info = SimpleNamespace(length=2.25, channels=1, sample_rate=22050, bits_per_sample=8)
    monkeypatch.setitem(sys.modules, 'mutagen', SimpleNamespace(File=lambda p: SimpleNamespace(info=info)))
    assert mod._alib_probe(str(fp)) == (2.25, 1, 22050, 8)


def test_probe_mutagen_without_info(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_ALIB_PROBE', {})
    fp = tmp_path / 'b.mp3'
    fp.write_bytes(b'\x00' * 32)
    monkeypatch.setitem(sys.modules, 'mutagen', SimpleNamespace(File=lambda p: None))
    assert mod._alib_probe(str(fp)) == (0.0, 0, 0, 0)


def test_probe_without_mutagen_logs_and_returns_zeros(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_ALIB_PROBE', {})
    fp = tmp_path / 'c.ogg'
    fp.write_bytes(b'\x00' * 16)
    monkeypatch.setitem(sys.modules, 'mutagen', None)
    assert mod._alib_probe(str(fp)) == (0.0, 0, 0, 0)


# ── _alib_ai_state ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    'rec,want',
    [
        ({'transform': 'MODEL'}, 'model'),
        ({'transform': 'dsp'}, 'dsp'),
        ({'transform': 'something-else', 'no_ai_training': True}, 'dsp'),
        ({'no_ai_training': False}, 'model'),
        ({}, ''),
        ({'no_ai_training': None}, ''),
    ],
)
def test_alib_ai_state(rec, want):
    assert mod._alib_ai_state(rec) == want


# ── _api_sfx ───────────────────────────────────────────────────────────────


class _FakeAls:
    def __init__(self, root, recs):
        self._root = root
        self._recs = recs
        self._CATEGORIES = {
            'sfx': {'kind': 'audio', 'label': 'SFX'},
            'vocal_fx': {'kind': 'audio'},
            'clips': {'kind': 'video', 'label': 'Clips'},
            'broken': {'kind': 'audio', 'label': 'Broken'},
        }

    def _audio_dir(self, key):
        return os.path.join(self._root, key)

    def load_assets(self, key):
        if key == 'broken':
            raise RuntimeError('library index is corrupt')
        return self._recs.get(key, [])


@pytest.fixture
def sfx_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_ALIB_CACHE', {})
    monkeypatch.setattr(mod, '_ALIB_PROBE', {})
    monkeypatch.setattr(mod, '_ALIB_MOD', {'m': None, 'err': ''})
    monkeypatch.setattr(mod, '_ALIB_DEFER_MIN', 2)
    (tmp_path / 'sfx').mkdir()
    _write_wav(tmp_path / 'sfx' / 'wave.wav')
    return tmp_path


def test_api_sfx_without_library_reports_the_error(monkeypatch, sfx_env):
    monkeypatch.setattr(mod, '_ALIB_MOD', {'m': None, 'err': 'ImportError: boom'})
    out = mod._api_sfx()
    assert out['files'] == [] and out['categories'] == []
    assert 'asset library unavailable' in out['error']


def test_api_sfx_builds_records(monkeypatch, sfx_env):
    monkeypatch.setattr(mod, '_ALIB_DEFER_MIN', 100)
    recs = {
        'sfx': [
            {
                'file': 'wave.wav',
                'descriptor': 'Ocean waves',
                'pack_label': 'Pack One',
                'group': 'water',
                'size': 1234,
                'license_id': 'cc0',
                'ucs_category': 'WATER',
                'bed': True,
                'slate_suspect': True,
                'no_ai_training': False,
                'sex': 'Male',
            },
            {'id': 'gone.wav', 'source': 'Pack One', 'verbal': True, 'asr_text': 'x' * 300},
            {'file': '', 'id': ''},
            {'file': 'scream.wav', 'name': 'Female Scream 12a', 'group': 'Female', 'sex': 'f'},
            {'file': 'plain.wav', 'group': 'male', 'name': 'male', 'sex': 'unspecified'},
        ]
    }
    monkeypatch.setattr(mod, '_ALIB_MOD', {'m': _FakeAls(str(sfx_env), recs), 'err': ''})
    out = mod._api_sfx()
    cats = {c['key']: c for c in out['categories']}
    assert set(cats) == {'sfx', 'vocal_fx', 'broken'}
    assert cats['sfx']['label'] == 'SFX' and cats['sfx']['count'] == 5
    assert cats['vocal_fx']['label'] == 'vocal_fx'
    assert cats['sfx']['desc'].startswith('Ambience BEDS')
    assert cats['broken']['count'] == 0  # load_assets raised, the rest still list
    assert out['packs'] == ['Pack One', 'Individual files (no pack)']
    by_file = {f['f']: f for f in out['files']}
    assert set(by_file) == {'wave.wav', 'gone.wav', 'scream.wav', 'plain.wav'}
    first = by_file['wave.wav']
    assert (first['n'], first['g'], first['p'], first['t']) == ('Ocean waves', 'water', 0, 'model')
    assert (first['d'], first['ch'], first['sr'], first['bt']) == (0.1, 1, 8000, 16)
    assert (first['s'], first['l'], first['u'], first['b'], first['q']) == (1234, 'cc0', 'WATER', True, True)
    assert first['x'] == 'm' and first['m'] > 0
    assert by_file['gone.wav']['m'] == 0  # no file on disk
    assert by_file['gone.wav']['v'] is True and len(by_file['gone.wav']['vt']) == 160
    assert by_file['gone.wav']['p'] == 0  # 'source' is the pack label fallback
    assert by_file['scream.wav']['g'] == 'Female Scream'  # take number stripped
    assert by_file['scream.wav']['x'] == 'f'
    assert by_file['plain.wav']['g'] == 'male'  # stem == name, group kept
    assert by_file['plain.wav']['x'] == ''  # only m/f ride as a sex
    assert out['loaded'] == ['sfx'] and out['generated'] == first['m']


def test_api_sfx_defers_a_large_library_until_asked(monkeypatch, sfx_env):
    recs = {'sfx': [{'file': 'wave.wav'}, {'file': 'wave.wav'}]}
    monkeypatch.setattr(mod, '_ALIB_MOD', {'m': _FakeAls(str(sfx_env), recs), 'err': ''})
    out = mod._api_sfx()
    assert [c['deferred'] for c in out['categories'] if c['key'] == 'sfx'] == [True]
    assert out['files'] == []
    opened = mod._api_sfx(extra=('sfx', ''))
    assert [c['deferred'] for c in opened['categories'] if c['key'] == 'sfx'] == [False]
    assert len(opened['files']) == 2


def test_api_sfx_cache_is_per_shape_and_force_bypasses_it(monkeypatch, sfx_env):
    als = _FakeAls(str(sfx_env), {'sfx': [{'file': 'wave.wav'}]})
    monkeypatch.setattr(mod, '_ALIB_MOD', {'m': als, 'err': ''})
    first = mod._api_sfx()
    assert mod._api_sfx() is first  # 20 s TTL hit
    assert set(mod._ALIB_CACHE) == {''}
    als._recs = {}
    assert mod._api_sfx(extra=('sfx',))['files'] == []  # other shape, own entry
    assert set(mod._ALIB_CACHE) == {'', 'sfx'}
    assert mod._api_sfx(force=True)['files'] == []


# ── _api_vfx_assets ────────────────────────────────────────────────────────


class _FakeVi:
    CATEGORIES = {
        'vfx_volumes': {'label': 'Volumes', 'kind': 'volume', 'desc': 'VDB packs'},
        'vfx_clips': {'label': 'Clips', 'kind': 'video'},
    }

    def __init__(self, libs, meta=None, boom=False):
        self.LIBS = libs
        self._meta = meta or {}
        self._boom = boom

    def load_sidecar(self):
        if self._boom:
            raise RuntimeError('sidecar is not json')
        return self._meta


@pytest.fixture
def vfx_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_VFXA_CACHE', {'ts': 0.0, 'data': None})
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': None, 'err': ''})
    (tmp_path / 'vfx_volumes').mkdir()
    (tmp_path / 'vfx_volumes' / 'smoke_red.webm').write_bytes(b'\x00')
    (tmp_path / 'vfx_volumes' / 'poster.png').write_bytes(b'\x00')
    return tmp_path


def test_api_vfx_assets_without_module(monkeypatch, vfx_env):
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': None, 'err': 'ImportError: cv2'})
    out = mod._api_vfx_assets()
    assert 'vfx library unavailable' in out['error'] and out['files'] == []


def test_api_vfx_assets_with_unreadable_sidecar(monkeypatch, vfx_env):
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), boom=True), 'err': ''})
    out = mod._api_vfx_assets()
    assert 'vfx sidecar unreadable' in out['error'] and out['categories'] == []


def test_api_vfx_assets_builds_records(monkeypatch, vfx_env):
    meta = {
        'k1': {
            'cat': 'vfx_volumes',
            'file': 'smoke.vdb',
            'name': 'Smoke',
            'pack_label': ' Smoke Pack ',
            'group': 'smoke',
            'kind': 'volume',
            'bytes': '2048',
            'w': 1920,
            'h': 1080,
            'fps': 24,
            'dur': 1.5,
            'frames': 48,
            'transform': 'dsp',
            'license_id': 'lic-1',
            'poster': 'poster.png',
            'preview': 'smoke_red.webm',
            'preview_src': 'render',
            'preview_error': '',
            'preview_dur': 2.0,
            'element': 'el.webm',
            'element_w': 3840,
            'element_h': 2160,
            'element_bytes': 99,
            'element_variants': [
                {'name': 'red', 'element': 'smoke_red.webm', 'bytes': 7},
                {'name': 'gone', 'element': 'missing.webm', 'bytes': 7},
                {'name': 'blank'},
            ],
            'sims': 10,
        },
        'k2': {'cat': 'vfx_clips', 'file': 'burst.mp4'},
        'k3': {'cat': 'not_a_category', 'file': 'x.mp4'},
        'k4': {'cat': 'vfx_clips', 'file': ''},
    }
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    out = mod._api_vfx_assets()
    assert out['packs'] == ['Smoke Pack', 'Individual files (no pack)']
    rec = out['files'][0]
    assert (rec['c'], rec['f'], rec['n'], rec['p'], rec['g']) == ('vfx_volumes', 'smoke.vdb', 'Smoke', 0, 'smoke')
    assert (rec['s'], rec['w'], rec['h'], rec['fps'], rec['d'], rec['fr']) == (2048, 1920, 1080, 24.0, 1.5, 48)
    assert (rec['t'], rec['l'], rec['po'], rec['pv'], rec['pvs'], rec['pvd']) == (
        'dsp',
        'lic-1',
        'poster.png',
        'smoke_red.webm',
        'render',
        2.0,
    )
    assert (rec['el'], rec['elw'], rec['elh'], rec['els'], rec['sm']) == ('el.webm', 3840, 2160, 99, 10)
    assert rec['elv'] == [{'n': 'red', 'f': 'smoke_red.webm', 's': 7}]  # the missing file is dropped
    assert (out['files'][1]['f'], out['files'][1]['n'], out['files'][1]['sm']) == ('burst.mp4', 'burst.mp4', 1)
    cats = {c['key']: c for c in out['categories']}
    assert cats['vfx_volumes'] == {
        'key': 'vfx_volumes',
        'label': 'Volumes',
        'kind': 'volume',
        'count': 1,
        'desc': 'VDB packs',
    }
    assert cats['vfx_clips']['desc'] == '' and cats['vfx_clips']['count'] == 1


def test_api_vfx_assets_shares_one_pack_index(monkeypatch, vfx_env):
    meta = {
        'k1': {'cat': 'vfx_clips', 'file': 'a.mp4', 'pack_label': 'Shared Pack'},
        'k2': {'cat': 'vfx_clips', 'file': 'b.mp4', 'pack_label': 'Shared Pack'},
        'k3': {'cat': 'vfx_volumes', 'file': 'c.vdb', 'pack_label': 'Shared Pack'},
    }
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    out = mod._api_vfx_assets()
    assert out['packs'] == ['Shared Pack']  # labelled once, indexed once
    assert [f['p'] for f in out['files']] == [0, 0, 0]
    counts = {c['key']: c['count'] for c in out['categories']}
    assert counts == {'vfx_clips': 2, 'vfx_volumes': 1}


def test_api_vfx_assets_cache_and_force(monkeypatch, vfx_env):
    vi = _FakeVi(str(vfx_env), {'k': {'cat': 'vfx_clips', 'file': 'a.mp4'}})
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': vi, 'err': ''})
    first = mod._api_vfx_assets()
    assert mod._api_vfx_assets() is first
    vi._meta = {}
    assert mod._api_vfx_assets(force=True)['files'] == []


# ── _fx_stack_arg ──────────────────────────────────────────────────────────


def test_fx_stack_arg_empty():
    assert mod._fx_stack_arg('') == []
    assert mod._fx_stack_arg(None) == []


def test_fx_stack_arg_decodes_base64url_json():
    stack = [{'op': 'eq', 'expr': "a='b',c=1%"}]
    raw = base64.urlsafe_b64encode(json.dumps(stack).encode()).decode().rstrip('=')
    assert mod._fx_stack_arg(raw) == stack


def test_fx_stack_arg_rejects_garbage():
    with pytest.raises(ValueError, match='unreadable stack'):
        mod._fx_stack_arg('!!!!not-base64!!!!')


# ── _vfx_featured_preview ──────────────────────────────────────────────────


def test_featured_preview_without_module(monkeypatch, vfx_env):
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': None, 'err': 'ImportError: cv2'})
    assert mod._vfx_featured_preview() == {}


def test_featured_preview_with_unreadable_sidecar(monkeypatch, vfx_env):
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), boom=True), 'err': ''})
    assert mod._vfx_featured_preview() == {}


@pytest.mark.parametrize(
    'meta',
    [
        {},
        {'k': {'cat': 'vfx_volumes'}},
        {'k': 'not a dict'},
        {'k': {'featured': True, 'cat': 'nope'}},
    ],
)
def test_featured_preview_without_a_pick(monkeypatch, vfx_env, meta):
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    assert mod._vfx_featured_preview() == {}


@pytest.mark.parametrize('poster', ['', 'sub/poster.png', '.hidden.png', 'absent.png'])
def test_featured_preview_rejects_an_unservable_poster(monkeypatch, vfx_env, poster):
    meta = {'k': {'featured': True, 'cat': 'vfx_volumes', 'poster': poster}}
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    assert mod._vfx_featured_preview() == {}


def test_featured_preview_happy_path(monkeypatch, vfx_env):
    meta = {
        'zz': {'featured': True, 'cat': 'vfx_volumes', 'poster': 'poster.png'},
        'aa': {
            'featured': True,
            'cat': 'vfx_volumes',
            'poster': 'poster.png',
            'preview': 'smoke_red.webm',
            'name': '  Red Smoke  ',
        },
    }
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    out = mod._vfx_featured_preview()
    assert out['label'] == 'Red Smoke'  # the lowest sidecar key wins the tie
    assert out['thumb'] == '/inspect/vfx/asset?cat=vfx_volumes&f=poster.png'
    assert out['preview'] == '/inspect/vfx/asset?cat=vfx_volumes&f=smoke_red.webm'


def test_featured_preview_label_falls_back_to_the_poster_stem(monkeypatch, vfx_env):
    meta = {'k': {'featured': True, 'cat': 'vfx_volumes', 'poster': 'poster.png', 'name': '   '}}
    monkeypatch.setattr(mod, '_VFXA_MOD', {'m': _FakeVi(str(vfx_env), meta), 'err': ''})
    out = mod._vfx_featured_preview()
    assert out['label'] == 'poster' and out['preview'] == ''


# ── volume preview jobs ────────────────────────────────────────────────────


@pytest.fixture
def volpv_env(monkeypatch):
    monkeypatch.setattr(mod, '_VOLPV_JOBS', {})
    monkeypatch.setattr(mod, '_VFXA_CACHE', {'ts': 123.0, 'data': {'files': []}})
    return mod._VOLPV_JOBS


@pytest.mark.parametrize(
    'result,want_state',
    [({'failed': 0, 'built': 1}, 'done'), ({'failed': 2}, 'error')],
)
def test_volpv_worker_runs_the_builder(monkeypatch, volpv_env, result, want_state):
    seen = {}

    def build_all(only=None, force=None, log=None):
        seen.update(only=only, force=force)
        log('starting')
        return result

    _inject(monkeypatch, 'vfx_volume_preview', SimpleNamespace(build_all=build_all))
    volpv_env['cloud.vdb'] = {'state': 'running', 'log': [], 'started': 1.0}
    mod._volpv_worker('cloud.vdb')
    assert seen == {'only': 'cloud.vdb', 'force': False}
    job = volpv_env['cloud.vdb']
    assert job['state'] == want_state and job['result'] == result
    assert job['log'] == ['starting'] and job['finished'] > 0
    assert mod._VFXA_CACHE['ts'] == 0.0  # the rail must rebuild


def test_volpv_worker_reports_a_builder_crash(monkeypatch, volpv_env):
    def build_all(**kw):
        raise RuntimeError('no VDB reader')

    _inject(monkeypatch, 'vfx_volume_preview', SimpleNamespace(build_all=build_all))
    volpv_env['fire.vdb'] = {'state': 'running', 'log': ['x'] * 50, 'started': 1.0}
    mod._volpv_worker('fire.vdb')
    job = volpv_env['fire.vdb']
    assert job['state'] == 'error'
    assert 'RuntimeError: no VDB reader' in job['result']['error']
    assert len(job['log']) == 40  # the log keeps the last 40 lines only


def test_volpv_worker_survives_a_job_that_vanished(monkeypatch, volpv_env):
    def build_all(only=None, force=None, log=None):
        log('orphan line')
        return {'failed': 0}

    _inject(monkeypatch, 'vfx_volume_preview', SimpleNamespace(build_all=build_all))
    mod._volpv_worker('ghost.vdb')
    assert volpv_env == {}  # no job to log into and none resurrected
    assert mod._VFXA_CACHE['ts'] == 0.0


def test_volpv_start_and_status(monkeypatch, volpv_env):
    started = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None):
            self._run = lambda: target(*args)
            started.append((target.__name__, args, daemon))

        def start(self):
            self._run()

    monkeypatch.setattr(mod, 'threading', SimpleNamespace(Thread=_Thread))
    _inject(monkeypatch, 'vfx_volume_preview', SimpleNamespace(build_all=lambda **kw: {'failed': 0}))

    assert mod._volpv_status('cloud.vdb') == {'state': 'idle'}
    body, code = mod._volpv_start('cloud.vdb')
    assert (body, code) == ({'ok': True, 'state': 'running', 'file': 'cloud.vdb'}, 200)
    assert started[0][0] == '_volpv_worker' and started[0][1] == ('cloud.vdb',) and started[0][2] is True
    status = mod._volpv_status('cloud.vdb')
    assert status['state'] == 'done' and status['result'] == {'failed': 0}
    assert status['elapsed'] >= 0 and status['log'] == []


def test_volpv_start_refuses_a_second_job(monkeypatch, volpv_env):
    volpv_env['busy.vdb'] = {'state': 'running', 'log': [], 'started': 1.0}
    body, code = mod._volpv_start('other.vdb')
    assert code == 409 and 'busy.vdb' in body['error']
    assert 'other.vdb' not in volpv_env


# ── module constants the two rails read ────────────────────────────────────


def test_mime_tables_and_descriptions_cover_the_libraries():
    assert mod._ALIB_EXT_MIME['.wav'] == 'audio/wav'
    assert mod._VFXA_EXT_MIME['.mp4'] == 'video/mp4'
    assert set(mod._ALIB_CAT_DESC) >= {'sfx', 'vocal_fx', 'foley', 'soundtracks', 'merged', 'instruments'}
    assert mod._ALIB_CACHE_TTL == mod._VFXA_CACHE_TTL == 20.0
