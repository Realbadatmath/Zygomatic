# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline unit coverage for zyg_workflows.pipeline_common: every path the module derives is
redirected into tmp_path by monkeypatching its own constants (_PC_DATA_DIR,
_FLUX_PERF_TELEMETRY_PATH), so nothing here touches a service, the network or a tracked data
file. Case tables live inside the tests (one branch per row) to stay under the 600-line cap."""

import json
import logging
import os
import sys
import types

import pytest

import zyg_workflows
from zyg_workflows import gui_state
from zyg_workflows import pipeline_common as mod


# ── test-run predicates ─────────────────────────────────────────────────────
def test_is_test_pipeline_id():
    for pid in ('docsmoke-123', 'GATECHECK-9', '  introsmoke-x  ', 'smoke', 'smoketest-7'):
        assert mod.is_test_pipeline_id(pid) is True
    for pid in ('a1b2c3', '', '   ', None, 123, ['docsmoke-1']):
        assert mod.is_test_pipeline_id(pid) is False


def test_is_smoke_output_dir(monkeypatch, tmp_path):
    smoke = tmp_path / 'docsmoke-42'
    smoke.mkdir()
    assert mod.is_smoke_output_dir(str(smoke)) is True
    assert mod.is_smoke_output_dir(str(smoke) + '/') is True

    plain = tmp_path / 'run-abc'
    plain.mkdir()
    assert mod.is_smoke_output_dir(str(plain)) is False
    (plain / mod.SMOKE_MARKER_FILE).write_text('1')
    assert mod.is_smoke_output_dir(str(plain)) is True

    for bad in (None, '', '   ', 7):
        assert mod.is_smoke_output_dir(bad) is False

    monkeypatch.setattr(mod, 'is_test_pipeline_id', lambda _v: (_ for _ in ()).throw(RuntimeError('nope')))
    assert mod.is_smoke_output_dir(str(plain)) is False


def test_smoke_output_root(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(mod, '_PC_DATA_DIR', str(tmp_path / 'data'))
    root = mod.smoke_output_root()
    assert root == str(tmp_path / 'data' / 'output' / 'smoke')
    assert os.path.isdir(root)

    blocker = tmp_path / 'blocked'
    blocker.write_text('not a directory')
    monkeypatch.setattr(mod, '_PC_DATA_DIR', str(blocker))
    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        assert mod.smoke_output_root().endswith(os.path.join('output', 'smoke'))
    assert 'could not be created' in caplog.text


def test_state_file_pipeline_id():
    cases = {'/x/pipeline_abc123_state.json': 'abc123', 'storyteller_my_run_state.json': 'my_run'}
    cases.update({'/x/pipeline_docsmoke-1_state.json': 'docsmoke-1', '/x/pipeline.json': '', '': ''})
    cases['/x/_state.json'] = ''
    for path, expected in cases.items():
        assert mod.state_file_pipeline_id(path) == expected
    assert mod.state_file_pipeline_id(None) == ''

    class Hostile:
        def __str__(self):
            raise ValueError('no str for you')

    assert mod.state_file_pipeline_id(Hostile()) == ''


def _state(tmp_path, pid, mtime):
    p = tmp_path / f'pipeline_{pid}_state.json'
    p.write_text(json.dumps({'pipeline_id': pid}))
    os.utime(p, (mtime, mtime))
    return str(p)


def test_recent_state_files_is_newest_first_and_drops_tests(tmp_path):
    old = _state(tmp_path, 'aaa', 1_000_000)
    new = _state(tmp_path, 'bbb', 2_000_000)
    smoke = _state(tmp_path, 'gatecheck-9', 3_000_000)
    pattern = str(tmp_path / 'pipeline_*_state.json')

    assert mod.recent_state_files(pattern) == [new, old]
    assert mod.recent_state_files(pattern, include_tests=True) == [smoke, new, old]
    assert mod.recent_state_files(pattern, limit=1) == [new]
    assert mod.recent_state_files(pattern, limit=-3) == [new, old]


def test_recent_state_files_tolerates_broken_paths(monkeypatch, tmp_path):
    good = _state(tmp_path, 'aaa', 2_000_000)
    link = tmp_path / 'pipeline_zzz_state.json'
    link.symlink_to(tmp_path / 'gone_forever')
    paths = mod.recent_state_files(str(tmp_path / 'pipeline_*_state.json'))
    assert paths[0] == good
    assert str(link) in paths

    monkeypatch.setattr(mod.glob, 'glob', lambda _p: (_ for _ in ()).throw(OSError('glob exploded')))
    assert mod.recent_state_files('*.json') == []


def test_standalone_gui_stand_ins_are_inert():
    if 'crewai_web_gui' in sys.modules:
        pytest.skip('the GUI is loaded, the real helpers are bound')
    assert mod._creature_save_state('any-id') is None
    assert mod._creature_stage_key('Sheet Render') == 'Sheet Render'
    assert mod._creature_stage_key(None) == ''
    assert mod._ensure_comfy_offload_env() is None


# ── cleanup ─────────────────────────────────────────────────────────────────
@pytest.fixture
def run_dir(tmp_path):
    """An output dir holding one of every file class _cleanup_pipeline_output triages."""
    out_dir = tmp_path / 'run'
    out_dir.mkdir()
    (out_dir / 'final.mp4').write_bytes(b'x' * 2048)
    (out_dir / 'slideshow.mp4').write_bytes(b'y' * 1024)
    (out_dir / 'concat.txt').write_text('file x')
    (out_dir / 'scenes.yaml').write_text('a: 1')
    (out_dir / 'extra.yml').write_text('b: 2')
    (out_dir / '_az_chunk_001.mp3').write_bytes(b'')
    (out_dir / '_az_chunk_002.mp3').write_bytes(b'audio')
    (out_dir / 'narration.mp3').write_bytes(b'keep me')
    (out_dir / 'subs.srt').write_text('1')
    (out_dir / 'a_subdir').mkdir()
    (out_dir / 'flux_images').mkdir()
    (out_dir / 'flux_images' / 'scene_1.png').write_bytes(b'p' * 512)
    return out_dir


def test_cleanup_removes_intermediates_and_flux_images(run_dir):
    for missing in ('', None, '/definitely/not/here'):
        assert mod._cleanup_pipeline_output(missing, 'final.mp4') is None
    lines: list[str] = []
    mod._cleanup_pipeline_output(str(run_dir), str(run_dir / 'final.mp4'), log_fn=lines.append)

    for kept in ('final.mp4', 'narration.mp3', 'subs.srt', '_az_chunk_002.mp3', 'a_subdir'):
        assert (run_dir / kept).exists(), kept
    for gone in ('slideshow.mp4', 'concat.txt', 'scenes.yaml', 'extra.yml', '_az_chunk_001.mp3'):
        assert not (run_dir / gone).exists(), gone
    assert not (run_dir / 'flux_images').exists()
    assert 'Cleanup: removed slideshow.mp4' in lines
    assert 'Cleanup: removed flux_images/' in lines
    assert any(line.startswith('Cleanup complete') for line in lines)


def test_cleanup_keeps_stills_when_asked(run_dir):
    lines: list[str] = []
    mod._cleanup_pipeline_output(str(run_dir), 'final.mp4', log_fn=lines.append, keep_stills=True)
    assert (run_dir / 'flux_images' / 'scene_1.png').exists()
    assert 'Cleanup: kept flux_images/ (keep_stills)' in lines
    assert (run_dir / 'final.mp4').exists()


def test_cleanup_without_a_logger_or_a_final_video(run_dir, tmp_path):
    assert mod._cleanup_pipeline_output(str(run_dir), '') is None
    assert not (run_dir / 'final.mp4').exists()

    nothing_to_free = tmp_path / 'empty-run'
    nothing_to_free.mkdir()
    (nothing_to_free / 'concat.txt').write_text('x')
    lines: list[str] = []
    mod._cleanup_pipeline_output(str(nothing_to_free), 'final.mp4', log_fn=lines.append)
    assert lines == []


def test_cleanup_survives_unlink_failures(monkeypatch, run_dir, caplog):
    def no_remove(_path):
        raise OSError('read-only file system')

    monkeypatch.setattr(os, 'remove', no_remove)
    with caplog.at_level(logging.DEBUG, logger=mod.__name__):
        mod._cleanup_pipeline_output(str(run_dir), str(run_dir / 'final.mp4'), log_fn=lambda _m: None)

    for survivor in ('slideshow.mp4', 'concat.txt', 'scenes.yaml', '_az_chunk_001.mp3'):
        assert (run_dir / survivor).exists(), survivor
    assert 'skipped' in caplog.text


def test_cleanup_survives_listdir_failures(monkeypatch, run_dir, caplog):
    real_listdir = os.listdir

    def picky_listdir(path):
        if str(path).endswith('flux_images'):
            raise OSError('flux_images is unreadable')
        return real_listdir(path)

    with monkeypatch.context() as m:
        m.setattr(os, 'listdir', picky_listdir)
        with caplog.at_level(logging.DEBUG, logger=mod.__name__):
            mod._cleanup_pipeline_output(str(run_dir), 'final.mp4')
    assert 'flux_images cleanup skipped' in caplog.text

    monkeypatch.setattr(os, 'listdir', lambda _p: (_ for _ in ()).throw(ValueError('listdir went sideways')))
    lines: list[str] = []
    mod._cleanup_pipeline_output(str(run_dir), 'final.mp4', log_fn=lines.append)
    assert lines == ['Cleanup warning (non-fatal): listdir went sideways']


# ── flux perf telemetry ─────────────────────────────────────────────────────
def test_flux_perf_family_and_clamp():
    cases = {None: 'flux', '': 'flux', 'FLUX': 'flux', '  Qwen-Image 2512 ': 'qwen_image_2512'}
    cases.update({'sdxl': 'sdxl', '***': 'flux', 42: '42'})
    for raw, expected in cases.items():
        assert mod._flux_perf_family(raw) == expected
    assert mod._flux_perf_clamp('flux') == (3.0, 60.0)
    assert mod._flux_perf_clamp('qwen') == (3.0, 120.0)


@pytest.fixture
def telemetry(monkeypatch, tmp_path):
    path = tmp_path / 'flux_perf_telemetry.json'
    monkeypatch.setattr(mod, '_FLUX_PERF_TELEMETRY_PATH', str(path))
    return path


def test_flux_perf_telemetry_path_per_family(telemetry, monkeypatch):
    assert mod._flux_perf_telemetry_path() == str(telemetry)
    assert mod._flux_perf_telemetry_path('flux') == str(telemetry)
    assert mod._flux_perf_telemetry_path('qwen') == str(telemetry).replace('.json', '_qwen.json')

    monkeypatch.setattr(mod, '_FLUX_PERF_TELEMETRY_PATH', '/tmp/telemetry_no_ext')
    assert mod._flux_perf_telemetry_path('sdxl') == '/tmp/telemetry_no_ext_sdxl.json'


def test_load_estimate_defaults_on_a_missing_or_unusable_file(telemetry):
    assert mod._load_flux_seconds_per_image_estimate() == 10.0
    assert mod._load_flux_seconds_per_image_estimate(default=7.5) == 7.5
    for body, default in (('{not json at all', 8.0), ('[1, 2, 3]', 9.0), ('{"estimate_s_per_image": "x"}', 6.0)):
        telemetry.write_text(body)
        assert mod._load_flux_seconds_per_image_estimate(default=default) == default


def test_load_estimate_clamps(telemetry):
    rows = [(12.5, 'flux', 12.5), (0, 'flux', 10.0), (-4, 'flux', 10.0), (1.0, 'flux', 3.0)]
    rows += [(999.0, 'flux', 60.0), (999.0, 'qwen', 120.0)]
    for stored, family, expected in rows:
        path = telemetry if family == 'flux' else telemetry.with_name(f'flux_perf_telemetry_{family}.json')
        path.write_text(json.dumps({'estimate_s_per_image': stored}))
        assert mod._load_flux_seconds_per_image_estimate(family=family) == expected


def test_update_estimate_smooths_and_writes(telemetry):
    telemetry.write_text(json.dumps({'estimate_s_per_image': 10.0}))
    updated = mod._update_flux_seconds_per_image_estimate(20.0, image_count=8)
    assert updated == pytest.approx(13.5)
    payload = json.loads(telemetry.read_text())
    assert payload['estimate_s_per_image'] == pytest.approx(13.5)
    assert payload['last_observed_s_per_image'] == pytest.approx(20.0)
    assert payload['last_image_count'] == 8
    assert payload['updated_at']
    assert 'family' not in payload


def test_update_estimate_tags_a_non_flux_family(telemetry):
    updated = mod._update_flux_seconds_per_image_estimate(90.0, image_count=-5, family='Qwen')
    payload = json.loads(telemetry.with_name('flux_perf_telemetry_qwen.json').read_text())
    assert payload['family'] == 'qwen'
    assert payload['last_image_count'] == 0
    assert payload['estimate_s_per_image'] == updated
    assert not telemetry.exists()


def test_update_estimate_leaves_a_test_run_or_a_bad_observation_alone(telemetry, caplog):
    telemetry.write_text(json.dumps({'estimate_s_per_image': 11.0}))
    with caplog.at_level(logging.INFO, logger=mod.__name__):
        assert mod._update_flux_seconds_per_image_estimate(70.0, pipeline_id='docsmoke-1') == pytest.approx(11.0)
    assert '[FLUX-PERF] test run docsmoke-1' in caplog.text
    for observed in (0, -3.0):
        assert mod._update_flux_seconds_per_image_estimate(observed) == pytest.approx(11.0)
    assert json.loads(telemetry.read_text())['estimate_s_per_image'] == pytest.approx(11.0)


def test_update_estimate_survives_an_unwritable_telemetry_path(monkeypatch, tmp_path, caplog):
    unwritable = tmp_path / 'telemetry_dir.json'
    unwritable.mkdir()
    monkeypatch.setattr(mod, '_FLUX_PERF_TELEMETRY_PATH', str(unwritable))
    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        updated = mod._update_flux_seconds_per_image_estimate(20.0)
    assert updated == pytest.approx(13.5)
    assert 'flux perf telemetry write failed' in caplog.text


# ── option / timing normalisation ───────────────────────────────────────────
def test_parse_pipeline_model_family():
    cases = {'flux': 'flux', 'SDXL': 'sdxl', '  Flux ': 'flux', 'qwen': 'flux', '': 'flux'}
    for raw, expected in cases.items():
        assert mod._parse_pipeline_model_family(raw) == expected
    assert mod._parse_pipeline_model_family(None) == 'flux'


def test_resolve_video_timing():
    rows = [({'test_scene': True}, 3.0, (1, 5.0, 5.0)), (None, 1.0, (4, 15.0, 60.0)), ({}, 0.0, (2, 15.0, 30.0))]
    rows += [({}, 99.0, (12, 15.0, 180.0)), ({'total_duration_sec': 'nonsense'}, 1.0, (4, 15.0, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_duration_sec': 'x'}, 1.0, (4, 15.0, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_duration_sec': 1}, 1.0, (12, 3.5, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_duration_sec': 999}, 1.0, (3, 20.0, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_count': 2}, 1.0, (2, 15.0, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_count': 99}, 1.0, (4, 15.0, 60.0))]
    rows += [({'total_duration_sec': 60, 'scene_count': 'two'}, 1.0, (4, 15.0, 60.0))]
    rows += [({'total_duration_sec': 10, 'scene_count': 5}, 1.0, (1, 10.0, 10.0))]
    for options, minutes, (n_scenes, scene_duration, total) in rows:
        assert mod._resolve_video_timing(options, minutes) == {
            'n_scenes': n_scenes,
            'scene_duration': scene_duration,
            'total_duration_sec': total,
        }, options


def test_normalize_pipeline_options_defaults():
    for raw in (None, {}, 'not a dict', 7):
        assert mod._normalize_pipeline_options(raw) == {
            'enable_bgm': True,
            'burn_subtitles': True,
            'enable_watermark': False,
            'test_scene': False,
            'image_intensity': 'high',
        }


def test_normalize_pipeline_options_booleans():
    for falsey in (False, 'off', 'FALSE', '0', 'no'):
        assert mod._normalize_pipeline_options({'enable_bgm': falsey})['enable_bgm'] is False
    for truthy in (True, 'yes', 1):
        assert mod._normalize_pipeline_options({'enable_bgm': truthy})['enable_bgm'] is True
    assert mod._normalize_pipeline_options({'burn_subtitles': 'no', 'test_scene': 'on'}) == {
        'enable_bgm': True,
        'burn_subtitles': False,
        'enable_watermark': False,
        'test_scene': True,
        'image_intensity': 'high',
    }


def test_normalize_pipeline_options_clamps_numbers_and_dials():
    rows = [({'scene_count': 5}, 'scene_count', 5), ({'scene_count': 99}, 'scene_count', 12)]
    rows += [({'total_duration_sec': 1}, 'total_duration_sec', 3.5)]
    rows += [({'total_duration_sec': 99999}, 'total_duration_sec', 1800.0)]
    rows += [({'scene_duration_sec': 1}, 'scene_duration_sec', 3.5)]
    rows += [({'scene_duration_sec': 99}, 'scene_duration_sec', 20.0)]
    rows += [({'manga_panel_fps': 90}, 'manga_panel_fps', 30), ({'manga_panel_fps': 12}, 'manga_panel_fps', 12)]
    rows += [({'image_intensity': 'EXTREME'}, 'image_intensity', 'extreme')]
    rows += [({'image_intensity': 'standard'}, 'image_intensity', 'standard')]
    rows += [({'image_intensity': 'glowing'}, 'image_intensity', 'high')]
    for raw, key, expected in rows:
        assert mod._normalize_pipeline_options(raw)[key] == expected, raw


def test_normalize_pipeline_options_drops_unusable_numbers(caplog):
    numeric = ('scene_count', 'total_duration_sec', 'scene_duration_sec', 'manga_panel_fps')
    rows = [{k: 'x'} for k in numeric] + [dict.fromkeys(numeric, 0)]
    with caplog.at_level(logging.DEBUG, logger=mod.__name__):
        for raw in rows:
            out = mod._normalize_pipeline_options(raw)
            assert not [k for k in numeric if k in out], raw
    assert 'not numeric' in caplog.text


def test_normalize_pipeline_options_preempt():
    recorded = {'mode': 'record', 'entry': 'e1', 'dry_run': False}
    rows = [({'mode': 'record', 'entry': 'e1'}, recorded), ({'mode': 'record', 'entry': 'e1', 'x': 1}, recorded)]
    rows += [({'mode': 'replay', 'entry': 7, 'dry_run': True}, {'mode': 'replay', 'entry': '7', 'dry_run': True})]
    rows += [({'mode': 'wipe', 'entry': 'e1'}, None), ({'mode': 'record'}, None), ('record', None), (None, None)]
    for preempt, expected in rows:
        assert mod._normalize_pipeline_options({'preempt': preempt}).get('preempt') == expected, preempt
    out = mod._normalize_pipeline_options({'preempt': {'mode': 'replay', 'entry': 'e' * 400}})
    assert out['preempt']['entry'] == 'e' * 120


# ── creature training worker ────────────────────────────────────────────────
@pytest.fixture
def creature(monkeypatch):
    """A job registry plus inert GUI/runtime sinks for _run_creature_training."""
    saved: list[str] = []
    errors: list[tuple] = []
    recorded: list[dict] = []
    offloads: list[int] = []
    job = {'stop_event': None, 'model_family': 'flux'}
    monkeypatch.setattr(mod, '_creature_gen_jobs', {'c1': job})
    monkeypatch.setattr(mod, '_creature_save_state', lambda cid: saved.append(cid))
    monkeypatch.setattr(mod, '_creature_stage_key', lambda name: str(name or '').lower())
    monkeypatch.setattr(mod, '_ensure_comfy_offload_env', lambda: offloads.append(1))
    monkeypatch.setattr(mod, '_push_error_log', lambda *a: errors.append(a))
    monkeypatch.setattr(mod._runtime, 'bm_record_pipeline', lambda j: recorded.append(j))
    monkeypatch.setattr(gui_state, '_pipeline_stop_flag', False, raising=False)
    from zyg_workflows import pipeline_control as pc

    monkeypatch.setattr(pc, 'halt_requested', lambda: False)
    return types.SimpleNamespace(
        job=job, saved=saved, errors=errors, recorded=recorded, offloads=offloads, monkeypatch=monkeypatch
    )


def _stub_service(creature, impl):
    from zyg_workflows import creature_training_service as cts

    creature.monkeypatch.setattr(cts, 'run_creature_training', impl)


def test_run_creature_training_completes(creature, caplog):
    assert mod._run_creature_training('unknown-id', 'frog') is None

    def impl(job, creature_id, directive, **kw):
        assert (directive, kw['image_paths'], kw['model_family'], kw['phase']) == ('frog', [], 'flux', 'full')
        kw['halt_check']()
        kw['set_stage']('Sheet')
        kw['complete_stage']('Sheet')
        kw['log_fn']('INFO', 'Sheet', 'rendered')

    _stub_service(creature, impl)
    with caplog.at_level(logging.INFO, logger=mod.__name__):
        mod._run_creature_training('c1', 'frog')

    job = creature.job
    assert (job['status'], job['stage'], job['current_stage']) == ('completed', 'done', 'done')
    assert job['ended']
    assert [(e['name'], e['status']) for e in job['stage_timeline']] == [('Sheet', 'completed')]
    assert job['stage_timeline'][0]['ended_at']
    assert creature.recorded == [job]
    assert creature.errors == [('INFO', 'Sheet', 'rendered', 'c1')]
    assert creature.offloads == [1]
    assert creature.saved == ['c1', 'c1']  # the completed stage and the finished job each save
    assert '[CREATURE-TRAIN][INFO][Sheet] rendered' in caplog.text


def test_run_creature_training_trims_the_debug_log(creature):
    creature.job['debug_events'] = [{'ts': '', 'level': 'INFO', 'stage': 's', 'msg': str(i)} for i in range(500)]
    _stub_service(creature, lambda job, cid, d, **kw: kw['log_fn']('INFO', 'Sheet', 'one more'))
    mod._run_creature_training('c1', 'd')
    assert len(creature.job['debug_events']) == 300
    assert creature.job['debug_events'][-1]['msg'] == 'one more'


def test_run_creature_training_keeps_a_stage_running(creature):
    def impl(job, creature_id, directive, **kw):
        kw['set_stage']('Sheet')
        kw['set_stage']('Sheet')
        kw['set_stage']('LoRA')

    _stub_service(creature, impl)
    mod._run_creature_training('c1', 'd')
    assert [(e['name'], e['status']) for e in creature.job['stage_timeline']] == [
        ('Sheet', 'running'),
        ('LoRA', 'running'),
    ]
    assert 'ended_at' not in creature.job['stage_timeline'][0]


@pytest.mark.parametrize('status', ['stopped', 'awaiting_review', 'failed'])
def test_run_creature_training_respects_a_service_status(creature, status):
    _stub_service(creature, lambda job, cid, d, **kw: job.update(status=status))
    mod._run_creature_training('c1', 'd', phase='train')
    assert creature.job['status'] == status
    assert 'ended' not in creature.job
    assert creature.recorded == []


def test_run_creature_training_fails_a_stage(creature):
    _stub_service(creature, lambda job, cid, d, **kw: kw['fail_stage']('Sheet', 'comfy refused'))
    mod._run_creature_training('c1', 'd')
    job = creature.job
    assert (job['status'], job['error']) == ('failed', 'comfy refused')
    assert job['ended']
    assert ('ERROR', 'Sheet', 'comfy refused', 'c1') in creature.errors


@pytest.mark.parametrize('flag', ['global', 'halt', 'event', 'mid-stage'])
def test_run_creature_training_stops_on_request(creature, flag):
    from zyg_workflows import pipeline_control as pc

    def stop_the_world():
        creature.monkeypatch.setattr(gui_state, '_pipeline_stop_flag', True, raising=False)

    if flag == 'global':
        stop_the_world()
    elif flag == 'halt':
        creature.monkeypatch.setattr(pc, 'halt_requested', lambda: True)
    elif flag == 'event':
        creature.job['stop_event'] = types.SimpleNamespace(is_set=lambda: True)

    if flag == 'mid-stage':
        _stub_service(creature, lambda job, cid, d, **kw: (stop_the_world(), kw['set_stage']('Sheet')))
    else:
        _stub_service(creature, lambda *a, **k: pytest.fail('the service must not run'))
    mod._run_creature_training('c1', 'd')
    assert creature.job['status'] == 'stopped'
    assert 'stopped by user' in creature.job['error']
    assert creature.errors[-1][0] == 'WARN'


def test_run_creature_training_reraises_a_foreign_runtime_error(creature):
    _stub_service(creature, lambda *a, **k: (_ for _ in ()).throw(RuntimeError('CUDA out of memory')))
    with pytest.raises(RuntimeError, match='CUDA out of memory'):
        mod._run_creature_training('c1', 'd')


def test_run_creature_training_records_an_unexpected_failure(creature):
    _stub_service(creature, lambda *a, **k: (_ for _ in ()).throw(ValueError('sheet json was garbage')))
    mod._run_creature_training('c1', 'd')
    assert creature.job['status'] == 'failed'
    assert creature.job['error'] == 'sheet json was garbage'
    assert any('Traceback' in call[2] for call in creature.errors)


# ── job status read-outs ────────────────────────────────────────────────────
def test_resolve_pipeline_public_status(monkeypatch):
    monkeypatch.setattr(mod, '_workflow_pipeline_worker_alive', lambda pid: False)
    rows = [({'pipeline_id': 'p1', 'ended': '2026-01-01'}, 'completed')]
    rows += [({'ended': '2026-01-01', 'error': '   '}, 'completed'), ({'error': 'boom'}, 'failed')]
    rows += [({'status': 'done'}, 'completed'), ({'status': 'COMPLETED'}, 'completed')]
    rows += [({'status': 'stopped'}, 'stopped'), ({'status': 'interrupted'}, 'interrupted')]
    rows += [({'pipeline_id': 'p1'}, 'interrupted'), ({'pipeline_id': 'p1', 'status': 'queued'}, 'interrupted')]
    rows += [({'status': 'error'}, 'failed'), ({'status': 'failed'}, 'failed')]
    rows += [({}, 'unknown'), ({'status': 'queued'}, 'unknown')]
    for job, expected in rows:
        assert mod._resolve_pipeline_public_status(job) == expected, job

    seen: list[str] = []

    def alive(pid):
        seen.append(pid)
        return True

    monkeypatch.setattr(mod, '_workflow_pipeline_worker_alive', alive)
    assert mod._resolve_pipeline_public_status({'pipeline_id': ' p1 ', 'ended': 'x'}) == 'running'
    assert seen == ['p1']


def test_pipeline_current_stage_from_job():
    rows = [({'current_stage': '  Flux Images '}, 'Flux Images')]
    rows += [({'current_stage': '  ', 'debug_events': [{'stage': 'Audio'}, {'stage': ' '}]}, 'Audio')]
    rows += [({'debug_events': [{'stage': 'A'}, {'stage': 'B'}]}, 'B'), ({'debug_events': [{}]}, '')]
    rows += [({'debug_events': None}, ''), ({}, '')]
    for job, expected in rows:
        assert mod._pipeline_current_stage_from_job(job) == expected, job


# ── subtitle word timings ───────────────────────────────────────────────────
def test_normalize_word_timings_for_subs(caplog):
    rows = [(None, []), ([], []), ([(' spaced ', 1)], [('spaced', 1.0)]), ([None, (), ('', 1.0)], [])]
    rows += [([('hello', 0.5), ('world', '1.25', 0.3)], [('hello', 0.5), ('world', 1.25)])]
    rows += [([('word',)], []), ([('word', 'not a float')], []), (['bare string'], [])]
    with caplog.at_level(logging.DEBUG, logger=mod.__name__):
        for raw, expected in rows:
            assert mod._normalize_word_timings_for_subs(raw) == expected, raw
    assert 'malformed word timing skipped' in caplog.text


@pytest.fixture
def murch(monkeypatch):
    fake = types.ModuleType('zyg_workflows.murch_engine')
    monkeypatch.setitem(sys.modules, 'zyg_workflows.murch_engine', fake)
    monkeypatch.setattr(zyg_workflows, 'murch_engine', fake, raising=False)
    return fake


def test_align_narration_skips_without_both_sides(murch):
    for narration, raw in (('', [('hi', 0.0)]), ('Hello world.', None), ('Hello world.', [('', 1.0)])):
        timings, coverage = mod._align_narration_word_timings(narration, raw)
        assert coverage == 0.0
        assert timings == mod._normalize_word_timings_for_subs(raw)


def test_align_narration_delegates_to_murch(murch):
    seen = {}

    def align(timings, narration, *, voice_mode, min_coverage):
        seen.update(timings=timings, narration=narration, voice_mode=voice_mode, min_coverage=min_coverage)
        return [('Hello,', 0.0), ('world.', 0.5)], 0.9

    murch.align_script_to_word_timings = align
    out, coverage = mod._align_narration_word_timings(
        'Hello, world.', [('hello', 0.0), ('world', 0.5)], voice_mode='dialogue', min_coverage=0.25
    )
    assert (out, coverage) == ([('Hello,', 0.0), ('world.', 0.5)], 0.9)
    assert seen == {
        'timings': [('hello', 0.0), ('world', 0.5)],
        'narration': 'Hello, world.',
        'voice_mode': 'dialogue',
        'min_coverage': 0.25,
    }


def test_align_narration_falls_back_when_murch_fails(murch, caplog):
    def boom(*a, **k):
        raise RuntimeError('alignment diverged')

    murch.align_script_to_word_timings = boom
    with caplog.at_level(logging.INFO, logger=mod.__name__):
        out, coverage = mod._align_narration_word_timings('Hello world.', [('hello', 0.0)])
    assert (out, coverage) == ([('hello', 0.0)], 0.0)
    assert '[SUBTITLES] Script alignment failed: alignment diverged' in caplog.text
