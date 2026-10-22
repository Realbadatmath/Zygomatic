# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage tests for zyg_dashboard.bp_movement.

The blueprint is plumbing over things it does not own: movement_studio's dial
vocabulary, three subject registries, two subprocesses in the SAM 3D Body venv.
All are faked — path globals repointed at tmp_path, `MS` replaced by a namespace
of lambdas, registries injected as attributes on the `zyg_workflows` package
(what `from zyg_workflows import x` reads before importing a submodule). Nothing
here touches the GPU, the network, or a tracked data file.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import subprocess
import sys
import types

import pytest
from flask import Flask

import zyg_workflows
import zyg_dashboard.bp_movement as M

API = '/api/internal/movement/'
JOB = 'a1b2c3d4e5f6'
OTHER = 'f6e5d4c3b2a1'
DRIVER = 'driver.mp4'
GATED = ['prompt', 'plate', 'driver', 'presets', 'delete', 'start', 'stop']
ROOTS = {'_OUT_ROOT': 'out/movement', '_TRACK_ROOT': 'out/movement/_tracks', '_CHARS_ROOT': 'chars'}
ROOTS |= {'_CREATURE_ROOT': 'creatures', '_CREATURE_OUT_ROOT': 'creature_out'}
ROOTS |= {'_PROP_ROOT': 'props', '_LORA_ROOT': 'loras'}

# every keyword _run_job reads back out of MS.render_kwargs when it logs the shot
RENDER_KW = {'num_frames': 33, 'width': 480, 'height': 480, 'shift': 5.0, 'cfg': 1.0, 'steps': 4, 'seed': 7}
RENDER_KW |= {'vace_strength': 1.0, 'vace_start_percent': 0.0, 'vace_end_percent': 0.35}
RENDER_KW |= {'context_windows': True, 'pin_regions': None}


# ── fixtures and helpers ────────────────────────────────────────────────────
@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Every path the module derived at import time, repointed at tmp_path."""
    base = os.path.realpath(str(tmp_path))
    paths = {'base': base, '_BODY_PY': os.path.join(base, 'body_python')}
    for name, rel in ROOTS.items():
        paths[name] = os.path.join(base, rel)
        os.makedirs(paths[name], exist_ok=True)
        monkeypatch.setattr(M, name, paths[name])
    monkeypatch.setattr(M, '_BODY_PY', paths['_BODY_PY'])
    monkeypatch.setattr(M, '_HERE', base)
    M._ACTIVE['job_id'] = M._ACTIVE_TRACK['job_id'] = None
    yield paths
    M._ACTIVE['job_id'] = M._ACTIVE_TRACK['job_id'] = None


@pytest.fixture
def ms(monkeypatch):
    """movement_studio, reduced to the surface bp_movement actually calls."""
    fake = types.SimpleNamespace(
        _ENV_KEYS=('ZYG_MV_SET', 'ZYG_MV_UNSET', 'ZYG_MV_KEEP'),
        spec=lambda: {'actions': ['wave']},
        sanitize=lambda p: dict(p or {}),
        compose_prompt=lambda params, action: f'composed<{action}>',
        nondefault=lambda params: {'seed': 7},
        render_kwargs=lambda params=None, **kw: dict(RENDER_KW),
        env_overrides=lambda params: {'ZYG_MV_SET': '1', 'ZYG_MV_UNSET': ''},
        control_kwargs=lambda params, generate_fn=None, log_fn=None: {},
        lora_chain=lambda params, auto_name='': [auto_name] if auto_name else [],
        still_for=lambda params, still: still,
        plate_chip=lambda params: {'plate': '', 'why': 'no control path'},
        presets=lambda: ['bow', 'wave'],
        preset_save=lambda name, params, action: f'saved:{name}',
        preset_load=lambda name: {'_action': 'wave', 'seed': 3},
        preset_delete=lambda name: None,
    )
    monkeypatch.setattr(M, 'MS', fake)
    return fake


@pytest.fixture
def client(roots, ms):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(M.bp)
    return app.test_client()


@pytest.fixture
def no_threads(monkeypatch):
    """threading.Thread, recorded by name and never started."""
    started = []

    def thread(target=None, name=None, args=(), daemon=False):
        started.append(name)
        return types.SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(M, 'threading', types.SimpleNamespace(Thread=thread))
    return started


def _inject(monkeypatch, name, module):
    """Put a fake zyg_workflows submodule where `from zyg_workflows import x` looks."""
    monkeypatch.setattr(zyg_workflows, name, module, raising=False)
    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', module)


def _png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n')
    return path


def _resolvers(monkeypatch, fn):
    monkeypatch.setattr(M, '_RESOLVERS', {'character': fn, 'creature': fn, 'object': fn})


def _subject(**over):
    return {'still': '/stills/a.png', 'binding': 'zedperson', 'lora': 'wan_chars/x.safetensors', 'refs': [], **over}


def _appcore(monkeypatch, jobs):
    mod = types.ModuleType('zyg_dashboard.appcore')
    if jobs is not None:
        mod._workflow_jobs = jobs
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.appcore', mod)


def _canon(monkeypatch, still, *, vace=None, raises=False):
    def build_vace_ref(sid):
        if raises:
            raise RuntimeError('no bust yet')
        return vace

    ns = types.SimpleNamespace(
        canon_portrait=lambda sid: still,
        canon_prompt_binding=lambda sid: f'{sid}_token',
        build_vace_ref=build_vace_ref,
    )
    _inject(monkeypatch, 'canon_service', ns)


# ── the error surface: the localhost gate and every refusal ─────────────────
@pytest.mark.parametrize('route', GATED)
def test_a_remote_caller_is_refused_by_every_mutating_route(client, route):
    r = client.post(API + route, json={}, environ_base={'REMOTE_ADDR': '10.1.2.3'})
    assert r.status_code == 401 and r.get_json() == {'error': 'localhost only'}


@pytest.mark.parametrize(
    ('method', 'path', 'payload', 'status', 'fragment'),
    [
        ('post', 'presets', {'op': 'rename'}, 400, "unknown op 'rename'"),
        ('post', 'delete', {'job_id': 'nope'}, 400, 'bad job_id'),
        ('post', 'delete', {'job_id': JOB}, 404, 'unknown job'),
        ('post', 'stop', {'job_id': 'x'}, 400, 'bad job_id'),
        ('post', 'stop', {'job_id': JOB}, 404, 'unknown job'),
        ('get', f'status?job_id={JOB}', None, 404, 'unknown job'),
        ('get', 'driver', None, 404, 'unknown track job'),
        ('post', 'driver', {'clip': '/no/such.mp4', 'plate_mode': 'rainbow'}, 400, 'plate_mode must be one of'),
        ('post', 'driver', {'clip': '/no/such.mp4'}, 404, 'driver clip not found'),
        ('post', 'start', {'subject_type': 'alien', 'motion_prompt': 'x'}, 400, "unknown subject_type 'alien'"),
        ('post', 'start', {'subject_type': 'character', 'motion_prompt': 'x', 'mode': 'go'}, 400, 'mode must be'),
    ],
)
def test_the_refusal_of_every_route(client, monkeypatch, method, path, payload, status, fragment):
    _resolvers(monkeypatch, lambda sid: _subject())
    r = getattr(client, method)(API + path, json=payload)
    assert r.status_code == status and fragment in r.get_json()['error']


# ── job.json, the one source of truth status.html polls ─────────────────────
def test_job_json_merges_logs_and_survives_a_corrupt_file(roots):
    run_dir = os.path.join(roots['_OUT_ROOT'], JOB)
    os.makedirs(run_dir)
    assert M._write_job(run_dir, status='queued', job_id=JOB)['status'] == 'queued'
    assert M._write_job(run_dir, status='running')['job_id'] == JOB
    for i in range(205):
        M._append_log(JOB, run_dir, f'line {i}')
    log = M._read_job(JOB)['log']
    assert len(log) == 200 and log[-1].endswith('line 204')
    with open(os.path.join(run_dir, 'job.json'), 'w', encoding='utf-8') as fh:
        fh.write('{not json')
    assert set(M._write_job(run_dir, status='error')) == {'status', 'updated'}
    assert M._read_job('../etc') is None and M._read_track_job('nope') is None
    assert M._read_track_job(JOB) is None


# ── image pools ─────────────────────────────────────────────────────────────
def test_the_image_pools_sort_filter_limit_and_tolerate_a_missing_folder(tmp_path):
    d = str(tmp_path / 'pool')
    for n in ('cell_2.png', 'cell_1.JPG', 'cell_3.webp', 'notes.txt', 'other_1.png'):
        _png(os.path.join(d, n))
    assert [os.path.basename(p) for p in M._images_in(d, 'cell_')] == ['cell_1.JPG', 'cell_2.png', 'cell_3.webp']
    assert len(M._images_in(d, 'cell_', limit=2)) == 2 and len(M._images_in(d)) == 4
    assert M._images_in(os.path.join(d, 'nope')) == []
    assert os.path.basename(M._first_image(d, 'cell_')) == 'cell_1.JPG'
    assert M._first_image(os.path.join(d, 'nope')) is None
    os.makedirs(os.path.join(d, 'empty'))
    assert M._first_image(os.path.join(d, 'empty')) is None


# ── subject resolution: character ───────────────────────────────────────────
def test_resolve_character_refuses_bad_ids_unknown_folders_and_missing_portraits(roots, monkeypatch):
    assert M._resolve_character('ab') is None
    assert M._resolve_character('../../etc/passwd') is None
    assert M._resolve_character('zedperson') is None
    os.makedirs(os.path.join(roots['_CHARS_ROOT'], 'zedperson'))
    _canon(monkeypatch, None)
    assert M._resolve_character('zedperson') is None
    _canon(monkeypatch, os.path.join(roots['base'], 'gone.png'))
    assert M._resolve_character('zedperson') is None


def test_resolve_character_collects_the_lora_and_the_refs_best_first(roots, monkeypatch):
    d = os.path.join(roots['_CHARS_ROOT'], 'zedperson')
    still = _png(os.path.join(d, 'portrait.png'))
    bust = _png(os.path.join(roots['base'], 'bust.png'))
    _png(os.path.join(d, 'arcane_instantid', 'cell_1.png'))
    _png(os.path.join(d, 'contact_sheet', 'cells', 'cell_9.png'))
    _png(os.path.join(roots['_LORA_ROOT'], 'wan_chars', 'wan_char_zedperson_t2v.safetensors'))
    _canon(monkeypatch, still, vace=bust)
    got = M._resolve_character('zedperson')
    assert got['still'] == still and got['binding'] == 'zedperson_token'
    assert got['lora'] == 'wan_chars/wan_char_zedperson_t2v.safetensors'
    assert [os.path.basename(r) for r in got['refs']] == ['bust.png', 'cell_1.png', 'cell_9.png']
    # a ref build that raises is not a failed subject — the cells carry on alone
    _canon(monkeypatch, still, raises=True)
    assert [os.path.basename(r) for r in M._resolve_character('zedperson')['refs']] == ['cell_1.png', 'cell_9.png']


# ── subject resolution: creature ────────────────────────────────────────────
@pytest.mark.parametrize('flux', ['weights', 'manifest', None])
def test_resolve_creature_refuses_unknown_stillless_and_flux1_dev_subjects(roots, flux):
    assert M._resolve_creature('nope') is None
    assert M._resolve_creature(JOB) is None
    d = os.path.join(roots['_CREATURE_ROOT'], JOB)
    os.makedirs(d)
    assert M._resolve_creature(JOB) is None  # a folder with no usable still
    _png(os.path.join(d, 'preview_1.png'))
    if flux == 'weights':
        os.makedirs(os.path.join(roots['_CREATURE_OUT_ROOT'], JOB, 'lora-weights-flux1-dev'))
    elif flux == 'manifest':
        with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as fh:
            json.dump({'train_family': 'FLUX'}, fh)
    assert (M._resolve_creature(JOB) is None) is (flux is not None)


def test_resolve_creature_prefers_a_preview_and_reads_the_trigger_token(roots, monkeypatch):
    d = os.path.join(roots['_CREATURE_ROOT'], JOB)
    hero = _png(os.path.join(d, 'preview_1.png'))
    _png(os.path.join(d, 'preview_2.png'))
    _png(os.path.join(d, 'ref_1.png'))
    with open(os.path.join(d, 'brief.json'), 'w', encoding='utf-8') as fh:
        json.dump({'trigger_token': 'grib', 'train_family': 'wan'}, fh)
    with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as fh:
        fh.write('{broken')
    os.makedirs(os.path.join(roots['_CREATURE_OUT_ROOT'], JOB, 'lora-weights-wan'))
    got = M._resolve_creature(JOB)
    assert got['still'] == hero and got['lora'] is None and got['binding'] == 'grib'
    assert [os.path.basename(r) for r in got['refs']] == ['preview_1.png', 'preview_2.png', 'ref_1.png']
    # an unlistable weights directory falls back to the manifest's family, it does not raise
    out = os.path.realpath(os.path.join(roots['_CREATURE_OUT_ROOT'], JOB))
    real = os.listdir

    def boom(path):
        if os.path.realpath(path) == out:
            raise PermissionError('no access')
        return real(path)

    monkeypatch.setattr(os, 'listdir', boom)
    assert M._resolve_creature(JOB)['still'] == hero


@pytest.mark.parametrize(
    ('rel', 'name'),
    [(('contact_sheet',), 'sheet_a.png'), (('contact_sheet', 'cells'), 'cell_a.png'), ((), 'ref_a.png')],
)
def test_resolve_creature_falls_back_through_the_hero_priority(roots, rel, name):
    hero = _png(os.path.join(roots['_CREATURE_ROOT'], JOB, *rel, name))
    got = M._resolve_creature(JOB)
    assert got['still'] == hero and got['binding'] == ''


# ── subject resolution: object ──────────────────────────────────────────────
@pytest.mark.parametrize('rec', ['no-registry', None, {}, {'previews': []}, {'previews': ['../escape.png']}])
def test_resolve_object_refuses_a_preview_that_is_absent_or_outside_the_prop_root(roots, monkeypatch, rec):
    assert M._resolve_object('') is None
    _png(os.path.join(roots['base'], 'escape.png'))
    if rec == 'no-registry':
        monkeypatch.delattr(zyg_workflows, 'prop_mesh_library', raising=False)
        monkeypatch.setitem(sys.modules, 'zyg_workflows.prop_mesh_library', None)
    else:
        _inject(monkeypatch, 'prop_mesh_library', types.SimpleNamespace(get=lambda sid: rec))
    assert M._resolve_object('pufferball') is None


def test_resolve_object_returns_the_mesh_previews_and_its_wan_lora(roots, monkeypatch):
    hero = _png(os.path.join(roots['_PROP_ROOT'], 'pufferball', 'view_a.png'))
    _png(os.path.join(roots['_PROP_ROOT'], 'pufferball', 'view_b.png'))
    _png(os.path.join(roots['_LORA_ROOT'], 'wan_props', 'wan_prop_pufferball.safetensors'))
    previews = ['pufferball/view_a.png', 'pufferball/view_b.png', 'pufferball/gone.png']
    rec = {'name': 'Pufferball', 'previews': previews}
    _inject(monkeypatch, 'prop_mesh_library', types.SimpleNamespace(get=lambda sid: rec))
    got = M._resolve_object('pufferball')
    assert got['still'] == hero and got['binding'] == 'Pufferball'
    assert got['lora'] == 'wan_props/wan_prop_pufferball.safetensors'
    assert [os.path.basename(r) for r in got['refs']] == ['view_a.png', 'view_b.png']


# ── env scope, advisory identity score, prompt composition ──────────────────
def test_env_scope_restores_set_unset_and_untouched_keys(ms, monkeypatch):
    monkeypatch.setenv('ZYG_MV_SET', 'before')
    monkeypatch.delenv('ZYG_MV_UNSET', raising=False)
    monkeypatch.setenv('ZYG_MV_KEEP', 'keep')
    with M._env_scope({'ZYG_MV_SET': 'during', 'ZYG_MV_UNSET': '', 'ZYG_MV_KEEP': 7}):
        assert os.environ['ZYG_MV_SET'] == 'during' and os.environ['ZYG_MV_KEEP'] == '7'
        assert 'ZYG_MV_UNSET' not in os.environ
    assert os.environ['ZYG_MV_SET'] == 'before' and os.environ['ZYG_MV_KEEP'] == 'keep'
    assert 'ZYG_MV_UNSET' not in os.environ
    with M._env_scope(None):
        assert os.environ['ZYG_MV_SET'] == 'before'


def test_score_run_is_advisory_in_all_three_outcomes(monkeypatch, tmp_path):
    lines = []
    _inject(monkeypatch, 'identity_bank', types.SimpleNamespace())
    assert M._score_run(str(tmp_path), lines.append) == {} and lines == []
    _inject(monkeypatch, 'identity_bank', types.SimpleNamespace(score_run=lambda rd: {'mean': 0.91, 'frames': 33}))
    assert M._score_run(str(tmp_path), lines.append) == {'mean': 0.91, 'frames': 33}
    assert 'identity (advisory): frames=33, mean=0.91' in lines[-1]

    def boom(rd):
        raise RuntimeError('clip gone')

    _inject(monkeypatch, 'identity_bank', types.SimpleNamespace(score_run=boom))
    assert M._score_run(str(tmp_path), lines.append) == {}
    assert 'identity score unavailable (RuntimeError: clip gone)' in lines[-1]


# ── the read-only and preview routes ────────────────────────────────────────
def test_resolve_prompt_prefers_a_sent_sentence_over_the_dials(ms):
    assert M._resolve_prompt({'motion_prompt': '  waves  ', 'action': 'wave'}, {}) == ('waves', 'wave')
    assert M._resolve_prompt({'preset': 'bow'}, {}) == ('composed<bow>', 'bow')
    assert M._resolve_prompt({}, {}) == ('composed<>', '')


def test_the_spec_plate_and_preset_listings_are_served_from_the_studio(client):
    assert client.get(API + 'spec').get_json() == {'actions': ['wave']}
    assert client.post(API + 'plate', json={'params': {}}).get_json() == {'plate': '', 'why': 'no control path'}
    assert client.get(API + 'presets').get_json() == {'presets': ['bow', 'wave']}


def test_prompt_route_without_a_usable_subject_omits_the_binding(client, monkeypatch):
    body = client.post(API + 'prompt', json={'action': 'bow', 'params': {'binding': True}}).get_json()
    assert body['ok'] is True and body['action'] == 'bow'
    assert body['motion_prompt'] == body['prompt'] == 'composed<bow>' and body['binding'] == ''
    assert body['render_kwargs'] == RENDER_KW and body['nondefault'] == {'seed': 7}
    assert body['env'] == {'ZYG_MV_SET': '1', 'ZYG_MV_UNSET': ''} and 'static shot' in body['camera_prefix']
    _resolvers(monkeypatch, lambda sid: None)
    gone = {'subject_type': 'creature', 'subject_id': JOB, 'params': {'binding': 1}}
    assert client.post(API + 'prompt', json=gone).get_json()['binding'] == ''


def test_prompt_route_prefixes_the_subject_binding_when_the_dial_is_on(client, monkeypatch):
    _resolvers(monkeypatch, lambda sid: _subject())
    sent = {'subject_type': 'character', 'subject_id': 'zedperson', 'motion_prompt': 'waves'}
    sent['params'] = {'binding': True, 'negative_prompt': 'blurry'}
    body = client.post(API + 'prompt', json=sent).get_json()
    assert body['binding'] == 'zedperson' and body['prompt'] == 'zedperson. waves'
    assert body['extra_negative'] == 'blurry'


def test_presets_route_saves_loads_deletes_and_reports_a_storage_error(client, ms):
    assert client.post(API + 'presets', json={'op': 'save', 'name': 'calm'}).get_json() == {
        'ok': True,
        'name': 'saved:calm',
    }
    loaded = client.post(API + 'presets', json={'op': 'load', 'name': 'calm'})
    assert loaded.get_json() == {'ok': True, 'action': 'wave', 'params': {'seed': 3}}
    assert client.post(API + 'presets', json={'op': 'delete', 'name': 'calm'}).get_json() == {'ok': True}

    def boom(name):
        raise ValueError('no such preset')

    ms.preset_load = boom
    bad = client.post(API + 'presets', json={'op': 'load', 'name': 'ghost'})
    assert bad.status_code == 400 and bad.get_json() == {'error': 'no such preset'}


# ── delete, status, stop ────────────────────────────────────────────────────
def test_a_job_is_polled_until_it_carries_a_clip_then_refused_while_running_and_finally_deleted(client, roots):
    run_dir = os.path.join(roots['_OUT_ROOT'], JOB)
    os.makedirs(run_dir)
    M._write_job(run_dir, status='running', output_file='')
    running = client.get(f'{API}status?job_id={JOB}').get_json()
    assert running['status'] == 'running' and 'video_url' not in running
    M._write_job(run_dir, status='done', output_file='vace_static.mp4')
    assert client.get(f'{API}status?job_id={JOB}').get_json()['video_url'] == f'/inspect/movement/file?id={JOB}'
    M._ACTIVE['job_id'] = JOB
    busy = client.post(API + 'delete', json={'job_id': JOB})
    assert busy.status_code == 409 and 'stop it first' in busy.get_json()['error']
    M._ACTIVE['job_id'] = None

    def boom(path):
        raise OSError('device busy')

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(shutil, 'rmtree', boom)
        failed = client.post(API + 'delete', json={'job_id': JOB})
        assert failed.status_code == 500 and 'could not delete' in failed.get_json()['error']
    assert client.post(API + 'delete', json={'job_id': JOB}).get_json() == {'ok': True, 'job_id': JOB}
    assert not os.path.isdir(run_dir)


def test_stop_route_writes_abort_and_reports_a_write_failure(client, roots, monkeypatch):
    run_dir = os.path.join(roots['_OUT_ROOT'], JOB)
    os.makedirs(run_dir)
    ok = client.post(API + 'stop', json={'job_id': JOB})
    assert ok.status_code == 200 and ok.get_json()['ok'] is True
    with open(os.path.join(run_dir, 'ABORT'), encoding='utf-8') as fh:
        assert 'stopped from Movement Studio' in fh.read()
    real_open = builtins.open

    def boom(path, *a, **kw):
        if str(path).endswith('ABORT'):
            raise OSError('read-only fs')
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, 'open', boom)
    failed = client.post(API + 'stop', json={'job_id': JOB})
    assert failed.status_code == 500 and 'could not write ABORT' in failed.get_json()['error']


# ── start ───────────────────────────────────────────────────────────────────
def test_start_route_requires_a_motion_sentence_and_a_usable_subject(client, monkeypatch, ms):
    _resolvers(monkeypatch, lambda sid: None)
    _appcore(monkeypatch, None)  # no _workflow_jobs at all — the busy check must not block
    gone = client.post(API + 'start', json={'subject_type': 'object', 'subject_id': 'ball', 'motion_prompt': 'spins'})
    assert gone.status_code == 404 and 'no usable still image' in gone.get_json()['error']
    ms.compose_prompt = lambda params, action: ''
    empty = client.post(API + 'start', json={'subject_type': 'character'})
    assert empty.status_code == 400 and empty.get_json() == {'error': 'motion_prompt is required'}


@pytest.mark.parametrize('blocker', ['own', 'workflow'])
def test_start_route_is_one_pipeline_at_a_time(client, monkeypatch, blocker):
    _resolvers(monkeypatch, lambda sid: _subject())
    if blocker == 'own':
        M._ACTIVE['job_id'] = running = OTHER
    else:
        running = 'p9'
        _appcore(monkeypatch, {'p9': {'status': 'running'}})
    r = client.post(API + 'start', json={'subject_type': 'character', 'motion_prompt': 'x'})
    assert r.status_code == 409 and r.get_json() == {'error': 'pipeline_busy', 'running_id': running}


@pytest.mark.parametrize(('mode', 'frames'), [('probe', 33), ('full', 81)])
def test_start_route_writes_the_job_and_spawns_the_render_thread(client, monkeypatch, no_threads, mode, frames):
    _resolvers(monkeypatch, lambda sid: _subject())
    _appcore(monkeypatch, {'p1': {'status': 'done'}})
    sent = {'subject_type': 'character', 'subject_id': 'zedperson', 'subject_name': 'Zed', 'action': 'wave'}
    sent |= {'mode': mode, 'motion_prompt': 'waves', 'params': {'binding': True, 'num_frames': 81}}
    body = client.post(API + 'start', json=sent).get_json()
    assert body['ok'] is True
    job = M._read_job(body['job_id'])
    assert job['status'] == 'queued' and job['subject_name'] == 'Zed'
    assert job['preset'] == job['action'] == 'wave' and job['prompt'] == 'zedperson. waves'
    assert job['num_frames'] == frames and job['params'] == {'binding': True, 'num_frames': 81}
    assert no_threads == [f'movement-{body["job_id"]}']


# ── the render thread body ──────────────────────────────────────────────────
def _watchdog(aborted):
    """render_abort.watchdog's contract: .start() returns itself, .stop() the verdict."""
    wd = types.SimpleNamespace(stop=lambda: aborted)
    wd.start = lambda: wd
    return wd


def _render_env(monkeypatch, roots, *, clip_name=None, aborted=False, raises=None):
    run_dir = os.path.join(roots['_OUT_ROOT'], JOB)
    os.makedirs(run_dir, exist_ok=True)

    def generate(still, prompt, rd, loras=None, ref_images_paths=None, log_fn=None, **kw):
        log_fn('submitted to comfy')
        if raises is not None:
            raise raises
        if clip_name is None:
            return None
        with open(os.path.join(rd, clip_name), 'wb') as fh:
            fh.write(b'mp4')
        return os.path.join(rd, clip_name)

    _inject(monkeypatch, 'render_abort', types.SimpleNamespace(watchdog=lambda rd, log_fn=None: _watchdog(aborted)))
    _inject(monkeypatch, 'wan_vace_service', types.SimpleNamespace(generate_vace_static_clip=generate))
    _inject(monkeypatch, 'identity_bank', types.SimpleNamespace(score_run=lambda rd: {'mean': 0.88}))
    return run_dir


def test_run_job_logs_the_dials_scores_the_clip_and_ends_done(roots, ms, monkeypatch):
    run_dir = _render_env(monkeypatch, roots, clip_name='vace_static.mp4')
    plate = _png(os.path.join(roots['base'], 'plates', 'p_0.png'))
    meta = {'asset': 'ball', 'view': 'front', 'kind': 'depth'}
    ms.control_kwargs = lambda params, generate_fn=None, log_fn=None: {
        'prop_plates': [{'plate': plate, 'meta': meta, 'strength': 0.6}]
    }
    ms.still_for = lambda params, still: os.path.join(roots['base'], 'scene_plate.png')
    refs = [_png(os.path.join(roots['base'], 'r1.png')), os.path.join(roots['base'], 'gone.png')]
    subj = _subject(still=_png(os.path.join(roots['base'], 'still.png')), refs=refs)

    M._run_job(JOB, run_dir, subj, 'zedperson. waves', 'full', {'identity_refs': 2}, 81)

    job = M._read_job(JOB)
    assert job['status'] == 'done' and job['output_file'] == 'vace_static.mp4'
    assert job['identity'] == {'mean': 0.88}
    text = '\n'.join(job['log'])
    assert 'render starting (full)' in text and 'scene still <- ' in text
    assert 'prop plate: p_0.png (ball/front/depth) strength=0.6' in text
    assert '33f 480x480 shift=5.0' in text
    assert "loras=['wan_chars/x.safetensors'] refs=1 windows=on pin_regions=off" in text
    assert 'non-default dials: seed=7' in text and text.endswith('done')
    assert M._ACTIVE['job_id'] is None


def test_run_job_ends_the_job_on_an_abort_and_on_a_clipless_render(roots, ms, monkeypatch):
    ms.nondefault = lambda params: {}  # an all-default dial state logs no dial line
    run_dir = _render_env(monkeypatch, roots, aborted=True, raises=RuntimeError('interrupted'))
    M._run_job(JOB, run_dir, _subject(refs=None, lora=None), 'waves', 'probe', {}, 33)
    job = M._read_job(JOB)
    assert job['status'] == 'aborted' and 'ended' in job
    assert 'ERROR: RuntimeError: interrupted' in '\n'.join(job['log'])
    assert 'aborted by operator' in job['log'][-1]
    assert 'non-default dials' not in '\n'.join(job['log'])

    _render_env(monkeypatch, roots, clip_name=None)
    M._run_job(JOB, run_dir, _subject(), 'waves', 'probe', {}, 33)
    job = M._read_job(JOB)
    assert job['status'] == 'error' and job['error'] == 'render failed — see log'


# ── the driver route ────────────────────────────────────────────────────────
def test_driver_route_refuses_a_missing_venv_and_a_busy_gpu_then_queues_the_job(client, roots, no_threads):
    clip = os.path.join(roots['base'], DRIVER)
    with open(clip, 'wb') as fh:
        fh.write(b'mp4')
    no_venv = client.post(API + 'driver', json={'clip': clip})
    assert no_venv.status_code == 500 and 'SAM 3D Body venv missing' in no_venv.get_json()['error']
    with open(roots['_BODY_PY'], 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\n')
    M._ACTIVE_TRACK['job_id'] = OTHER
    busy = client.post(API + 'driver', json={'clip': clip})
    assert busy.status_code == 409 and busy.get_json()['running_id'] == OTHER
    M._ACTIVE_TRACK['job_id'] = None

    sent = {'clip': clip, 'plate_mode': 'depth', 'subject': 'the dancer', 'subject_name': 'Zed'}
    body = client.post(API + 'driver', json=sent).get_json()
    assert body['ok'] is True
    job = M._read_track_job(body['job_id'])
    assert job['status'] == 'queued' and job['plate_mode'] == 'depth' and job['clip'] == clip
    assert job['out_dir'] == body['out_dir']
    assert no_threads == [f'movement-track-{body["job_id"]}']
    assert client.get(f'{API}driver?job={body["job_id"]}').get_json()['status'] == 'queued'


# ── the track thread body ───────────────────────────────────────────────────
def _track_runner(out, *, pose_rc=0, write_track=True, masks=0, report=None, raise_on=None):
    calls = []

    def run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append(cmd[2])
        if raise_on == cmd[2]:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if cmd[2] == 'geom.pose_track':
            if write_track:
                with open(os.path.join(out, 'track.json'), 'w', encoding='utf-8') as fh:
                    json.dump({'frames': 33}, fh)
            for i in range(masks):
                _png(os.path.join(out, 'masks', f'm_{i}.png'))
            return subprocess.CompletedProcess(cmd, pose_rc, 'pose line\n', 'pose stderr\n')
        with open(os.path.join(out, 'plates_report.json'), 'w', encoding='utf-8') as fh:
            fh.write('{truncated' if report == 'corrupt' else json.dumps(report))
        return subprocess.CompletedProcess(cmd, 0, 'plate line\n', 'plate stderr\n')

    return run, calls


def _track(roots, monkeypatch, mode, subject, subject_name, **kw):
    out = os.path.join(roots['_TRACK_ROOT'], JOB)
    os.makedirs(out, exist_ok=True)
    run, calls = _track_runner(out, **kw)
    monkeypatch.setattr(subprocess, 'run', run)
    M._run_track(JOB, out, os.path.join(roots['base'], DRIVER), mode, subject, subject_name)
    return M._read_track_job(JOB), calls


def test_run_track_extracts_plates_and_reports_the_subject_it_used(roots, monkeypatch):
    modes = {'composite': {'dir': '/plates/composite', 'frames': 33, 'audit_ok': True}}
    job, calls = _track(
        roots, monkeypatch, 'composite', ' the dancer ', 'Zed', masks=3, report={'size': [8], 'modes': modes}
    )
    assert calls == ['geom.pose_track', 'geom.track_plates']
    assert job['status'] == 'done' and job['subject'] == 'the dancer'
    assert job['masks'] == 3 and job['mask_reason'] == ''
    assert job['frames'] == 33 and job['size'] == [8] and job['plate_audit_ok'] is True
    assert 'done — 33 composite plates' in job['log'][-1]
    assert M._ACTIVE_TRACK['job_id'] is None


def test_run_track_falls_back_to_the_subject_name_and_warns_on_a_grey_audit(roots, monkeypatch):
    verdict = {'dir': '/plates/depth', 'frames': 9, 'audit_ok': False, 'audit_verdict': 'constant'}
    job, _ = _track(roots, monkeypatch, 'depth', '', 'Zed', report={'modes': {'depth': verdict}})
    assert job['subject'] == 'Zed' and job['status'] == 'done' and job['plate_audit_ok'] is False
    assert job['masks'] == 0 and job['mask_reason'] == "SAM 3 found no subject for 'Zed'"
    assert any('WARNING depth plates audit: constant' in ln for ln in job['log'])


def test_run_track_uses_a_generic_noun_and_fails_without_a_track_json(roots, monkeypatch):
    job, _ = _track(roots, monkeypatch, 'seg', '', '', pose_rc=2, write_track=False)
    assert job['subject'] == 'the person' and job['error'] == 'pose_track exit 2 — no track.json'
    assert any('pose stderr' in ln for ln in job['log'])


@pytest.mark.parametrize('report', [{'modes': {'depth': {'dir': '/x'}}}, 'corrupt'])
def test_run_track_fails_when_the_requested_mode_has_no_plates(roots, monkeypatch, report):
    job, _ = _track(roots, monkeypatch, 'normal', 'dancer', '', masks=1, report=report)
    assert job['status'] == 'error' and job['error'] == 'track_plates exit 0 — no normal plates'
    assert any('plate stderr' in ln for ln in job['log'])


def test_run_track_reports_a_timeout_and_an_unexpected_error(roots, monkeypatch):
    job, _ = _track(roots, monkeypatch, 'skeleton', 'dancer', '', raise_on='geom.pose_track')
    assert job['error'] == 'timed out after 3600s'

    def boom(*a, **kw):
        raise ValueError('no such interpreter')

    monkeypatch.setattr(subprocess, 'run', boom)
    out = os.path.join(roots['_TRACK_ROOT'], JOB)
    M._run_track(JOB, out, os.path.join(roots['base'], DRIVER), 'skeleton', 'dancer', '')
    assert M._read_track_job(JOB)['error'] == 'ValueError: no such interpreter'
    assert M._ACTIVE_TRACK['job_id'] is None
