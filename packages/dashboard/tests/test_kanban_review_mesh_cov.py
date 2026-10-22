# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CI-safe coverage tests for ``zyg_dashboard.kanban.review_mesh``: every root the module
derives at import is redirected to tmp_path and every subprocess, thread and sibling-package
import is faked, so the file runs offline with no GPU, no services and no writes outside tmp."""

import hashlib
import importlib
import json
import os
import sys
import time
import types

import pytest

MOD = importlib.import_module('zyg_dashboard.kanban.review_mesh')
_DATA_CACHES = ('_MESH_CACHE', '_PROP_CACHE', '_MV_CACHE', '_GNM_CACHE', '_LIST_CACHE')
_ROOT_CONSTS = (
    ('_CHARS_ROOT', 'chars'),
    ('_RUNTIME', 'runtime'),
    ('_MESH_ROOT', 'mesh'),
    ('_PROP_ROOT', 'prop'),
    ('_MV_OUT_ROOT', 'mv'),
    ('_GNM_ROOT', 'gnm'),
)


@pytest.fixture(autouse=True)
def _pristine():
    """Leave every module-level cache as it was found, before and after each test."""

    def _reset():
        for name in _DATA_CACHES:
            getattr(MOD, name).clear()
            getattr(MOD, name).update({'ts': 0.0, 'data': None})
        MOD._MEDUSA_IDS_CACHE.clear()
        MOD._MEDUSA_IDS_CACHE.update({'ts': 0.0, 'ids': None})
        for c in (MOD._NAME_CACHE, MOD._FACET_CACHE, MOD._MESH_RUNNING, MOD._MESH_JOBS_MEM, MOD._MESH_DRYRUN_OK):
            c.clear()

    _reset()
    yield
    _reset()


@pytest.fixture
def roots(tmp_path, monkeypatch):
    p = {k: tmp_path / k for k in ('chars', 'runtime', 'mesh', 'prop', 'mv', 'gnm')}
    for d in p.values():
        d.mkdir()
    for const, key in _ROOT_CONSTS:
        monkeypatch.setattr(MOD, const, os.path.realpath(p[key]))
    monkeypatch.setattr(MOD, '_MESH_JOBS', str(p['mesh'] / '_jobs'))
    return p


def _wj(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding='utf-8')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_pml(monkeypatch, *, assets=None, verify=None, boom=None):
    fake = types.ModuleType('zyg_workflows.prop_mesh_library')

    def _list_assets():
        if boom:
            raise RuntimeError(boom)
        return list(assets or [])

    fake.list_assets = _list_assets
    fake.verify = lambda: dict(verify or {})
    monkeypatch.setitem(sys.modules, 'zyg_workflows.prop_mesh_library', fake)
    monkeypatch.setattr(sys.modules['zyg_workflows'], 'prop_mesh_library', fake, raising=False)


def _mkchar(root, cid, *, bible=None, cells=(), arcane=(), medusa=False, sheet=True):
    d = root / cid
    d.mkdir(parents=True, exist_ok=True)
    if sheet:
        (d / 'contact_sheet' / 'cells').mkdir(parents=True)
    for n in cells:
        (d / 'contact_sheet' / 'cells' / n).write_bytes(b'img')
    if arcane:
        (d / 'arcane_instantid').mkdir(parents=True)
    for n in arcane:
        (d / 'arcane_instantid' / n).write_bytes(b'img')
    if bible is not None:
        _wj(d / 'character_bible.json', bible)
    if medusa:
        (d / '.medusa_origin').write_text('', encoding='utf-8')
    return d


@pytest.mark.parametrize(
    ('fn', 'cache', 'clock'),
    [
        ('_mesh_list', '_MESH_CACHE', time.time),
        ('_prop_mesh_list', '_PROP_CACHE', time.time),
        ('_api_movement_library', '_MV_CACHE', time.time),
        ('_gnm_fits', '_GNM_CACHE', time.time),
        ('_api_list_all', '_LIST_CACHE', time.monotonic),
    ],
)
def test_a_fresh_cache_is_served_without_touching_disk(roots, fn, cache, clock):
    sentinel = {'sentinel': fn}
    getattr(MOD, cache).update(ts=clock(), data=sentinel)
    assert getattr(MOD, fn)() is sentinel


@pytest.mark.parametrize(
    ('env', 'dotenv', 'want'),
    [
        ('from-env', None, 'from-env'),
        ('', '# note\nZERO_PUBLIC_TOKEN="from-file"\n', 'from-file'),
        ('', 'OTHER=1\n', ''),
        ('', None, ''),
    ],
)
def test_internal_token(tmp_path, monkeypatch, env, dotenv, want):
    here = tmp_path / 'a' / 'b' / 'c'
    here.mkdir(parents=True)
    if env:
        monkeypatch.setenv('ZERO_PUBLIC_TOKEN', env)
    else:
        monkeypatch.delenv('ZERO_PUBLIC_TOKEN', raising=False)
    if dotenv:
        (here / '.env').write_text(dotenv, encoding='utf-8')
    monkeypatch.setattr(MOD, 'HERE', str(here))
    assert MOD._internal_token() == want


def test_mesh_list_without_a_registry(roots):
    assert MOD._mesh_list() == {'originals': {}, 'derived': {}, 'verified': 'no registry yet'}


@pytest.mark.parametrize(('cached', 'want'), [(None, 'registry unreadable'), ({'stale': True}, None)])
def test_mesh_list_with_an_unreadable_registry(roots, cached, want):
    (roots['mesh'] / 'registry.json').write_text('{not json', encoding='utf-8')
    MOD._MESH_CACHE.update(ts=0.0, data=cached)
    out = MOD._mesh_list()
    assert out == ({'originals': {}, 'derived': {}, 'verified': want} if want else cached)


def test_mesh_list_verifies_hashes_and_anthro_reports(roots):
    mesh = roots['mesh']
    (mesh / 'orig_f').mkdir()
    (mesh / 'orig_f' / 'body.glb').write_bytes(b'female-body')
    (mesh / 'orig_f' / 'p.png').write_bytes(b'preview')
    _wj(mesh / 'orig_f' / 'anthro_report.json', {'verdict': 'PASS'})
    (mesh / 'orig_m').mkdir()
    (mesh / 'orig_m' / 'body.glb').write_bytes(b'male-body')
    female = {
        'dir': 'orig_f',
        'glb': 'body.glb',
        'sha256': _sha(mesh / 'orig_f' / 'body.glb'),
        'aux_sha256': {'p.png': _sha(mesh / 'orig_f' / 'p.png')},
        'anthro': {'report': 'orig_f/anthro_report.json'},
    }
    _wj(
        mesh / 'registry.json',
        {
            'originals': {
                'female': female,
                'male': {'dir': 'orig_m', 'glb': 'body.glb', 'sha256': '0' * 64},
                'ghost': {'dir': 'nowhere', 'glb': 'gone.glb', 'sha256': '0' * 64},
            },
            'derived': {'abel': {'anthro_report': 'derived/abel/anthro_report.json'}},
        },
    )
    out = MOD._mesh_list()
    assert out['verified'] == {'female': 'verified-immutable', 'male': 'HASH MISMATCH', 'ghost': 'HASH MISMATCH'}
    assert out['originals']['female']['anthro_report_present'] is True
    assert out['originals']['male']['anthro_report'] is None
    assert out['derived']['abel']['anthro_report_present'] is False
    assert MOD._MESH_CACHE['data'] is out


def test_prop_mesh_list_survives_a_broken_library(roots, monkeypatch):
    _fake_pml(monkeypatch, boom='no prop_mesh_library here')
    out = MOD._prop_mesh_list()
    assert out == {'assets': {}, 'verified': {}, 'error': 'no prop_mesh_library here'}
    assert MOD._PROP_CACHE['data'] is out


def test_prop_mesh_list_summarises_each_asset(roots, monkeypatch):
    _fake_pml(
        monkeypatch,
        assets=[
            {'id': 'pb01', 'name': 'Pufferball', 'sha256': {'a': 'b'}, 'previews': ['pb01/front.png']},
            {'id': 'zz02', 'name': 'Zebra', 'kind': 'creature'},
        ],
        verify={'pb01': {'ok': True}, 'zz02': {'ok': False}},
    )
    out = MOD._prop_mesh_list()
    assert 'sha256' not in out['assets']['pb01']
    assert out['assets']['pb01']['root'] == 'props'
    assert out['assets']['pb01']['integrity'] == 'verified'
    assert out['assets']['zz02']['integrity'] == 'HASH MISMATCH'


def test_api_movement_objects_passes_the_error_through(monkeypatch):
    monkeypatch.setattr(MOD, '_prop_mesh_list', lambda: {'error': 'boom'})
    assert MOD._api_movement_objects() == {'objects': [], 'error': 'boom'}


def test_api_movement_objects_sorts_by_name(monkeypatch):
    assets = {'zz02': {'name': 'Zebra', 'kind': 'creature', 'previews': ['zz02/front.png']}, 'pb01': {}}
    monkeypatch.setattr(MOD, '_prop_mesh_list', lambda: {'assets': assets})
    out = MOD._api_movement_objects()['objects']
    assert [o['name'] for o in out] == ['Zebra', 'pb01']
    assert out[0]['front_image'] == {'p': 'zz02/front.png'}
    assert out[1] == {'id': 'pb01', 'name': 'pb01', 'kind': 'prop', 'front_image': None}


def test_api_movement_library_without_the_root(roots):
    os.rmdir(roots['mv'])
    assert MOD._api_movement_library(force=True) == {'jobs': [], 'count': 0}


def test_api_movement_library_lists_newest_first(roots):
    mv = roots['mv']
    (mv / 'not-a-job-id').mkdir()
    (mv / ('b' * 12)).write_text('a file, not a job dir', encoding='utf-8')
    (mv / ('c' * 12)).mkdir()  # no job.json at all
    for jid, upd in (('a' * 12, 10.0), ('d' * 12, 99.0)):
        d = mv / jid
        d.mkdir(exist_ok=True)
        _wj(d / 'job.json', {'status': 'done', 'subject_id': 'abel', 'preset': 'walk', 'updated': upd})
    (mv / ('d' * 12) / 'vace_static.mp4').write_bytes(b'clip')
    out = MOD._api_movement_library(force=True)
    assert out['count'] == 2
    assert [j['job_id'] for j in out['jobs']] == ['d' * 12, 'a' * 12]
    assert [j['has_clip'] for j in out['jobs']] == [True, False]
    assert out['jobs'][0]['subject_name'] == 'abel' and out['jobs'][0]['action'] == 'walk'
    assert MOD._MV_CACHE['data'] is out


def test_gnm_fits_with_nothing_on_disk(roots):
    out = MOD._gnm_fits()
    assert out['fits'] == [] and out['has_baseline'] is False
    assert 'no registered body is modified' in out['note']


def test_gnm_fits_ignores_a_malformed_summary(roots):
    _wj(roots['gnm'] / 'fits' / 'summary.json', [1, 2])
    assert MOD._gnm_fits()['fits'] == []


def test_gnm_fits_reports_metrics_renders_and_baseline(roots):
    gnm = roots['gnm']
    _wj(
        gnm / 'fits' / 'summary.json',
        [
            {'body': 'abel', 'date': '2026-08-21', 'metrics': {'face_rms_mm': 5.4}},
            {'body': 'cornelis', 'metrics': {'face_rms_mm': 6.1}},
            {'body': 'no_metrics_record'},
        ],
    )
    _wj(gnm / 'fits_phase1_baseline' / 'summary.json', [{'body': 'abel', 'metrics': {'face_rms_mm': 5.5}}])
    for v in (0, 2):
        (gnm / 'fits' / f'gnm_fit_abel_v{v:02d}.png').write_bytes(b'png')
    out = MOD._gnm_fits()
    assert [r['body'] for r in out['fits']] == ['abel', 'cornelis']
    assert out['fits'][0]['renders'] == ['fits/gnm_fit_abel_v00.png', 'fits/gnm_fit_abel_v02.png']
    assert out['fits'][0]['baseline'] == {'face_rms_mm': 5.5}
    assert out['fits'][1]['renders'] == [] and out['fits'][1]['baseline'] == {}
    assert out['has_baseline'] is True


def test_gnm_fits_falls_back_to_the_baseline_bodies(roots):
    _wj(roots['gnm'] / 'fits_phase1_baseline' / 'summary.json', [{'body': 'abel', 'metrics': {'x': 1}}])
    out = MOD._gnm_fits()
    assert [r['body'] for r in out['fits']] == ['abel'] and out['fits'][0]['metrics'] == {}


@pytest.mark.parametrize(
    ('reg', 'want'),
    [({'originals': {'female': {}}, 'derived': {'abel': {}}}, {'female', 'abel'}), ({}, set())],
)
def test_mesh_names_comes_off_the_registry(monkeypatch, reg, want):
    monkeypatch.setattr(MOD, '_mesh_list', lambda: reg)
    assert MOD._mesh_names() == want


@pytest.mark.parametrize(
    ('text', 'want'),
    [
        (None, []),
        ('', []),
        ('abel  aaaaaaaa -> bbbbbbbb', []),  # needs the two-space indent
        ('  abel  deadbeef -> cafebabe  same  \n  noise\n', [('abel', 'deadbeef', 'cafebabe', 'same')]),
        ('  female  11111111->22222222', [('female', '11111111', '22222222', '')]),
    ],
)
def test_mesh_parse_hashes(text, want):
    rows = MOD._mesh_parse_hashes(text)
    assert [(r['name'], r['before'], r['after'], r['verdict']) for r in rows] == want


@pytest.mark.parametrize('text', [None, '', 'nothing to see here\n'])
def test_mesh_parse_verdict_without_a_verdict_line(text):
    assert MOD._mesh_parse_verdict(text) == {}


def test_mesh_parse_verdict_collects_the_known_tokens():
    text = (
        'building\n'
        'anthro char=abel verdict=PASS exit=0 gates=12 pass=11 warn=1 fail=0 '
        'unrun_blocking=0 worst=hip ignored=9 json=/home/x/legacy tree/anthro_report.json\n'
    )
    out = MOD._mesh_parse_verdict(text)
    assert out['verdict'] == 'PASS' and out['exit'] == 0
    assert out['gates'] == '12' and out['pass'] == '11' and out['warn'] == '1' and out['worst'] == 'hip'
    assert 'ignored' not in out
    assert out['json'] == '/home/x/legacy tree/anthro_report.json'


def test_mesh_parse_verdict_takes_the_last_line_and_needs_no_json():
    text = 'anthro char=abel verdict=PASS exit=0\nanthro char=abel verdict=FAIL exit=2\n'
    assert MOD._mesh_parse_verdict(text) == {'verdict': 'FAIL', 'exit': 2}


def _job(tmp_path, **kw):
    jid = kw.pop('job_id', 'a' * 12)
    job = {
        'job_id': jid,
        'kind': 'reissue',
        'name': 'abel',
        'dry_run': False,
        'status': 'running',
        'log': str(tmp_path / f'{jid}.log'),
        'hashes': [],
        'rc': None,
    }
    job.update(kw)
    MOD._MESH_JOBS_MEM[jid] = job
    return jid, job


def _fake_popen(monkeypatch, lines, rc):
    class _P:
        def __init__(self, argv, **kw):
            self.argv = argv
            self.stdout = iter(lines)

        def wait(self):
            return rc

    monkeypatch.setattr(MOD.subprocess, 'Popen', _P)


@pytest.mark.parametrize(
    ('kind', 'dry', 'lines', 'rc', 'status', 'dryok', 'cleared'),
    [
        ('reissue', True, ['  abel  deadbeef -> cafebabe  same\n'], 0, 'done', True, False),
        ('reissue', False, [], 0, 'done', False, True),
        ('gate', False, ['anthro char=abel verdict=FAIL exit=2 gates=3\n'], 2, 'done', True, False),
        ('gate', False, ['crashed\n'], 1, 'error', True, False),
    ],
)
def test_mesh_job_run(tmp_path, monkeypatch, kind, dry, lines, rc, status, dryok, cleared):
    _fake_popen(monkeypatch, lines, rc)
    MOD._MESH_CACHE['data'] = {'stale': True}
    MOD._MESH_DRYRUN_OK.add('abel')
    jid, job = _job(tmp_path, kind=kind, dry_run=dry)
    MOD._MESH_RUNNING['abel'] = jid
    MOD._mesh_job_run(jid, ['/bin/true', kind], 'abel')
    assert job['status'] == status and job['rc'] == rc
    assert 'abel' not in MOD._MESH_RUNNING
    assert ('abel' in MOD._MESH_DRYRUN_OK) is dryok
    assert (MOD._MESH_CACHE['data'] is None) is cleared
    assert bool(job['verdict']) is (rc == 2)
    assert f'$ /bin/true {kind}' in (tmp_path / f'{jid}.log').read_text(encoding='utf-8')


def test_mesh_job_run_leaves_another_jobs_lock_alone(tmp_path, monkeypatch):
    _fake_popen(monkeypatch, [], 0)
    jid, job = _job(tmp_path)
    MOD._MESH_RUNNING['abel'] = 'someone-else'
    MOD._mesh_job_run(jid, ['/bin/true'], 'abel')
    assert job['status'] == 'done' and MOD._MESH_RUNNING['abel'] == 'someone-else'


def test_mesh_job_run_never_raises(tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise OSError('no such interpreter')

    monkeypatch.setattr(MOD.subprocess, 'Popen', _boom)
    jid, job = _job(tmp_path)
    MOD._mesh_job_run(jid, ['/nope'], 'abel')
    assert job['status'] == 'error' and job['rc'] == -1 and 'no such interpreter' in job['error']


def _no_thread(monkeypatch):
    """Record the thread that would start — the suite forbids leaking one into the process."""
    started = []

    class _T:
        def __init__(self, *a, **kw):
            self.kw = kw

        def start(self):
            started.append(self.kw)

    monkeypatch.setattr(MOD.threading, 'Thread', _T)
    monkeypatch.setattr(MOD, '_mesh_job_run', lambda *a: None)
    return started


def test_mesh_job_start_creates_the_job(roots, monkeypatch):
    started = _no_thread(monkeypatch)
    body, code = MOD._mesh_job_start('gate', 'abel', ['/bin/true', 'abel'], dry_run=True)
    assert code == 200 and body['ok'] is True
    jid = body['job_id']
    assert MOD._MESH_RUNNING['abel'] == jid
    job = MOD._MESH_JOBS_MEM[jid]
    assert job['kind'] == 'gate' and job['dry_run'] is True and job['status'] == 'running'
    assert os.path.isdir(MOD._MESH_JOBS) and started[0]['name'] == f'mesh-gate-{jid}'


def test_mesh_job_start_refuses_a_second_job_on_one_body(roots, monkeypatch):
    _no_thread(monkeypatch)
    MOD._MESH_RUNNING['abel'] = 'b' * 12
    body, code = MOD._mesh_job_start('reissue', 'abel', ['/bin/true'])
    assert code == 409
    assert body == {'error': 'abel already has a job running', 'job_id': 'b' * 12}


@pytest.mark.parametrize('props', [{'assets': {'pb01': {}}, 'verified': {'pb01': 'verified'}}, {'error': 'broken'}])
def test_mesh_list_scoped_default_merges_the_props_lane(monkeypatch, props):
    monkeypatch.setattr(MOD, '_mesh_list', lambda: {'originals': {'female': {}}, 'derived': {}})
    monkeypatch.setattr(MOD, '_prop_mesh_list', lambda: props)
    out = MOD._mesh_list_scoped('')
    assert out['originals'] == {'female': {}}
    assert out['props'] == (props.get('assets') or {})
    assert out.get('props_error') == props.get('error')


def test_mesh_list_scoped_medusa_keeps_female_medusa_derived_only(roots, monkeypatch):
    reg = {
        'originals': {'female': {}, 'male': {}},
        'derived': {
            'medusa_f': {'params': {'base': 'female'}},
            'medusa_m': {'params': {'base': 'male'}},
            'plain_f': {'params': {'base': 'female'}},
        },
    }
    monkeypatch.setattr(MOD, '_mesh_list', lambda: reg)
    for cid in ('medusa_f', 'medusa_m'):
        (roots['runtime'] / f'medusa_{cid}_state.json').write_text('{}', encoding='utf-8')
    out = MOD._mesh_list_scoped('medusa')
    assert out['originals'] == {} and out['props'] == {} and list(out['derived']) == ['medusa_f']


@pytest.mark.parametrize('cid', [None, '', 'short', 'bad-id!', 'x' * 40, 'missingchar'])
def test_safe_char_dir_refuses(roots, cid):
    assert MOD._safe_char_dir(cid) is None


def test_safe_char_dir_refuses_a_symlink_out_of_the_root(roots, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (roots['chars'] / 'linkchar').symlink_to(elsewhere, target_is_directory=True)
    assert MOD._safe_char_dir('linkchar') is None


def test_safe_char_dir_accepts_a_real_child(roots):
    (roots['chars'] / 'abel_01').mkdir()
    assert MOD._safe_char_dir('abel_01') == os.path.join(MOD._CHARS_ROOT, 'abel_01')


def test_display_name_prefers_display_name_then_identity_then_id(roots):
    chars = roots['chars']
    for cid, bible in (
        ('with_display', {'display_name': 'Abel', 'identity': {'name': 'ignored'}}),
        ('with_identity', {'identity': {'name': 'Cornelis'}}),
        ('empty_bible', {}),
    ):
        _wj(chars / cid / 'character_bible.json', bible)
    assert MOD._display_name(str(chars / 'with_display'), 'with_display') == 'Abel'
    assert MOD._display_name(str(chars / 'with_identity'), 'with_identity') == 'Cornelis'
    assert MOD._display_name(str(chars / 'empty_bible'), 'empty_bible') == 'empty_bible'
    assert MOD._display_name(str(chars / 'no_bible'), 'no_bible') == 'no_bible'
    MOD._NAME_CACHE['with_display'] = 'Cached'
    assert MOD._display_name(str(chars / 'with_display'), 'with_display') == 'Cached'


def test_char_facets_without_a_bible(roots):
    assert MOD._char_facets(str(roots['chars'] / 'nope'), 'nope') == {'render_style': '', 'gender': ''}
    assert MOD._FACET_CACHE == {}


def test_char_facets_reads_and_then_caches_on_mtime(roots):
    d = roots['chars'] / 'abel_01'
    _wj(d / 'character_bible.json', {'style_profile': {'render_style': 'arcane'}, 'identity': {'gender': 'male'}})
    want = {'render_style': 'arcane', 'gender': 'male'}
    assert MOD._char_facets(str(d), 'abel_01') == want
    assert MOD._char_facets(str(d), 'abel_01') == want
    assert MOD._FACET_CACHE['abel_01'][1] == want


def test_char_facets_with_a_malformed_bible(roots):
    d = roots['chars'] / 'abel_01'
    d.mkdir()
    (d / 'character_bible.json').write_text('{not json', encoding='utf-8')
    assert MOD._char_facets(str(d), 'abel_01') == {'render_style': '', 'gender': ''}


def test_runtime_status(roots):
    state = {'status': 'running', 'stage': 'cells', 'current_stage': 'cell_3', 'sheet_cells_done': 3}
    _wj(roots['runtime'] / 'contact_sheet_abel_01.json', state)
    out = MOD._runtime_status('abel_01')
    assert out['status'] == 'running' and out['current'] == 'cell_3' and out['cells_done'] == 3
    assert MOD._runtime_status('missing') == {}


def test_manifest_qc(roots):
    d = roots['chars'] / 'abel_01'
    _wj(d / 'contact_sheet' / 'manifest.json', {'approved': True, 'identity_qc': {'mean_score': 0.82, 'total': 9}})
    out = MOD._manifest_qc(str(d))
    assert out['approved'] is True and out['mean'] == 0.82 and out['total'] == 9
    assert MOD._manifest_qc(str(roots['chars'] / 'nope')) == {}


def test_list_images_filters_sorts_and_skips_unstatable(roots):
    cells = roots['chars'] / 'abel_01' / 'contact_sheet' / 'cells'
    cells.mkdir(parents=True)
    for n in ('cell_2.png', 'cell_1.webp', 'cell_cand_9.png', 'tile_x.png', 'notes.txt'):
        (cells / n).write_bytes(b'img')
    (cells / 'cell_dangling.png').symlink_to(cells / 'gone-for-good.png')
    out = MOD._list_images(str(roots['chars'] / 'abel_01'), 'cells')
    assert [r['name'] for r in out] == ['cell_1.webp', 'cell_2.png']
    assert isinstance(out[0]['mtime'], float)
    assert MOD._list_images(str(roots['chars'] / 'nope'), 'cells') == []


def test_list_images_tiles_and_arcane_categories(roots):
    d = roots['chars'] / 'abel_01'
    (d / 'contact_sheet' / 'tiles').mkdir(parents=True)
    for n in ('tile_a.png', 'regen_b.png', 'other.png'):
        (d / 'contact_sheet' / 'tiles' / n).write_bytes(b'img')
    _mkchar(roots['chars'], 'abel_01', arcane=('final_01.png',), sheet=False)
    assert [r['name'] for r in MOD._list_images(str(d), 'tiles')] == ['regen_b.png', 'tile_a.png']
    assert [r['name'] for r in MOD._list_images(str(d), 'arcane_final')] == ['final_01.png']


def test_medusa_id_set_reads_state_files_then_caches(roots):
    rt = roots['runtime']
    for n in ('medusa_abel_01_state.json', 'medusa_pending.json', 'medusa__state.json', 'other.json'):
        (rt / n).write_text('{}', encoding='utf-8')
    assert MOD._medusa_id_set() == {'abel_01'}
    (rt / 'medusa_cornelis_state.json').write_text('{}', encoding='utf-8')
    assert MOD._medusa_id_set() == {'abel_01'}  # 4 s TTL: served from the cache


def test_medusa_id_set_without_the_runtime_dir(roots):
    os.rmdir(roots['runtime'])
    assert MOD._medusa_id_set() == set()


def test_is_medusa_char_by_marker_and_by_state_file(roots):
    chars, rt = roots['chars'], roots['runtime']
    _mkchar(chars, 'marked_01', medusa=True, sheet=False)
    _mkchar(chars, 'stated_01', sheet=False)
    (rt / 'medusa_stated_01_state.json').write_text('{}', encoding='utf-8')
    assert MOD._is_medusa_char('marked_01', str(chars / 'marked_01'), set()) is True
    assert MOD._is_medusa_char('stated_01', str(chars / 'stated_01')) is True
    assert MOD._is_medusa_char('plain_01', str(chars / 'plain_01'), {'other'}) is False


def test_is_medusa_char_when_the_marker_is_not_checkable(roots, monkeypatch):
    real_exists = os.path.exists

    def _exists(path):
        if str(path).endswith('.medusa_origin'):
            raise OSError('permission denied')
        return real_exists(path)

    monkeypatch.setattr(MOD.os.path, 'exists', _exists)
    assert MOD._is_medusa_char('abel_01', str(roots['chars'] / 'abel_01'), {'abel_01'}) is True


def test_api_list_all_without_the_chars_root(roots):
    os.rmdir(roots['chars'])
    assert MOD._api_list_all() == []


def test_api_list_all_builds_one_card_per_character(roots):
    chars = roots['chars']
    _mkchar(chars, 'bad-id!', cells=('cell_1.png',))
    _mkchar(chars, 'nosheet_01', sheet=False)
    _mkchar(
        chars,
        'abel_01',
        bible={'style_profile': {'render_style': 'arcane'}, 'identity': {'gender': 'male'}},
        cells=('cell_1.png', 'cell_2.png'),
        arcane=('final_01.png',),
        medusa=True,
    )
    _mkchar(chars, 'cornelis_01', cells=('cell_9.png',))
    _wj(roots['runtime'] / 'contact_sheet_abel_01.json', {'status': 'running', 'stage': 'cells'})
    out = MOD._api_list_all()
    cards = {c['id']: c for c in out}
    assert set(cards) == {'abel_01', 'cornelis_01'}
    assert cards['abel_01']['front_image']['cat'] == 'arcane_final' and cards['abel_01']['pic_count'] == 3
    assert cards['abel_01']['active'] is True and cards['abel_01']['is_medusa'] is True
    assert cards['abel_01']['render_style'] == 'arcane' and cards['abel_01']['gender'] == 'male'
    assert cards['cornelis_01']['front_image']['cat'] == 'cells'
    assert cards['cornelis_01']['active'] is False and cards['cornelis_01']['is_medusa'] is False
    assert MOD._LIST_CACHE['data'] is out


def test_api_list_all_when_the_sheet_dir_is_not_statable(roots, monkeypatch):
    _mkchar(roots['chars'], 'abel_01', cells=('cell_1.png',))
    real_getmtime = os.path.getmtime

    def _getmtime(path):
        if str(path).endswith('contact_sheet'):
            raise OSError('permission denied')
        return real_getmtime(path)

    monkeypatch.setattr(MOD.os.path, 'getmtime', _getmtime)
    (card,) = MOD._api_list_all()
    assert card['id'] == 'abel_01' and card['updated'] == 0.0


def test_api_list_is_fail_closed_on_scope(monkeypatch):
    listing = [{'id': 'm1', 'is_medusa': True}, {'id': 'p1', 'is_medusa': False}]
    monkeypatch.setattr(MOD, '_api_list_all', lambda: listing)
    assert [r['id'] for r in MOD._api_list('medusa')] == ['m1']
    assert [r['id'] for r in MOD._api_list('')] == ['p1']
    assert 'is_medusa' not in MOD._api_list('medusa')[0]


def test_api_char_refuses_unknown_and_cross_scope(roots):
    _mkchar(roots['chars'], 'abel_01', cells=('cell_1.png',), medusa=True)
    assert MOD._api_char('nope_01', '') is None
    assert MOD._api_char('abel_01', '') is None


def test_api_char_returns_the_detail_view(roots):
    d = _mkchar(
        roots['chars'], 'abel_01', bible={'display_name': 'Abel'}, cells=('cell_1.png',), arcane=('final_01.png',)
    )
    _wj(d / 'contact_sheet' / 'manifest.json', {'approved': True, 'identity_qc': {'mean_score': 0.9}})
    _wj(roots['runtime'] / 'contact_sheet_abel_01.json', {'status': 'running', 'stage': 'cells', 'error': ''})
    out = MOD._api_char('abel_01', '')
    assert out['name'] == 'Abel' and out['active'] is True and out['qc']['approved'] is True
    assert [g['cat'] for g in out['groups']] == ['arcane_final', 'cells']
    assert out['groups'][0]['label'] == MOD._CAT_LABELS['arcane_final']
    assert isinstance(out['server_time'], float)


def test_api_pictures_is_scoped_and_newest_first(roots, monkeypatch):
    chars = roots['chars']
    _mkchar(chars, 'abel_01', cells=('cell_1.png',), arcane=('final_01.png',))
    _mkchar(chars, 'medusa_01', cells=('cell_9.png',), medusa=True)
    os.utime(chars / 'abel_01' / 'arcane_instantid' / 'final_01.png', (5000, 5000))
    os.utime(chars / 'abel_01' / 'contact_sheet' / 'cells' / 'cell_1.png', (9000, 9000))
    real = MOD._api_list_all
    monkeypatch.setattr(MOD, '_api_list_all', lambda: real() + [{'id': 'ghost_01', 'name': 'Ghost'}])
    pics = MOD._api_pictures('')['pictures']
    assert [(p['id'], p['file']) for p in pics] == [('abel_01', 'cell_1.png'), ('abel_01', 'final_01.png')]
    assert pics[0]['cat'] == 'cells' and pics[0]['label'] == MOD._CAT_LABELS['cells']
    assert MOD._api_pictures('medusa')['pictures'][0]['id'] == 'medusa_01'


def test_import_refuses_a_non_http_gui_url(monkeypatch):
    """The import-time scheme guard: the forwarders attach a token to _MAIN_APP, so a
    file:// or custom-handler ZYG_GUI_URL must stop the module from loading at all."""
    good = MOD._MAIN_APP
    monkeypatch.setenv('ZYG_GUI_URL', 'file:///tmp/not-a-server')
    try:
        with pytest.raises(RuntimeError, match='must be an http:// or https:// URL'):
            importlib.reload(MOD)
    finally:
        monkeypatch.setenv('ZYG_GUI_URL', good)
        importlib.reload(MOD)
    assert MOD._MAIN_APP == good
