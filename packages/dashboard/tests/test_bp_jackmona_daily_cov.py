# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for ``zyg_dashboard.bp_jackmona_daily`` — the Jack & Mona daily pair.

Offline by construction: the series ledger (``P``), the audit log, the Amsterdam
clock, the pipeline registry and the three state paths are all replaced, so no
test touches the repo's runtime JSON, ComfyUI or the GPU.
"""

from __future__ import annotations

import builtins
import json
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask

import threading as _threading

# bp_jackmona_daily starts its `jackmona-daily-watcher` thread at import (line ~545);
# a second copy of that watcher must not run inside the test process (it would poll
# the live queues and trip tests/api/conftest.py's thread-leak check), so the thread
# is neutered for the duration of the import only — the same technique the api
# harness uses for the whole GUI.
_real_thread_start = _threading.Thread.start


def _no_watcher_start(self):
    if self.name == 'jackmona-daily-watcher':
        return None
    return _real_thread_start(self)


_threading.Thread.start = _no_watcher_start
try:
    import zyg_dashboard.bp_jackmona_daily as M
finally:
    _threading.Thread.start = _real_thread_start

FIXED_NOW = datetime(2026, 5, 4, 9, 30, 0)
FIXED_ISO = '2026-05-04T09:30:00'
TODAY = '2026-05-04'
REMOTE = {'REMOTE_ADDR': '10.1.2.3'}


class FakePeople:
    """Stand-in for ``zyg_workflows.kids_series_people``, the series ledger."""

    SLUGS = ('jack', 'mona')
    PEOPLE = {'jack': {'name': 'Jack'}, 'mona': {'name': 'Mona'}}

    def __init__(self) -> None:
        self.recorded: list[tuple] = []
        self.attached: list[tuple] = []
        self.settled: list[tuple] = []
        self.brief_exc: Exception | None = None

    def episode_brief(self, slug, *, moment=None, n=None, log_fn=None):
        if self.brief_exc is not None:
            raise self.brief_exc
        return {'theme': moment or f'{slug} loses a shoe', 'episode': n or 7, 'seconds': 95, 'singer': f'{slug}-voice'}

    def record_episode(self, slug, moment, *, n=None, job_id=None, title=None, seconds=None, date=None, extra=None):
        self.recorded.append((slug, moment, n, seconds, date, extra))

    def attach_job(self, slug, episode_n, pid):
        self.attached.append((slug, episode_n, pid))

    def settle_episode(self, slug, pid, *, title=None, status=None):
        self.settled.append((slug, pid, title, status))

    def series_rows(self):
        return [{'slug': 'jack', 'episodes': 3}, {'slug': 'mona', 'episodes': 2}]


@pytest.fixture
def jm(tmp_path, monkeypatch):
    """The module with every outside edge redirected into ``tmp_path``."""
    audit: list[tuple] = []
    people = FakePeople()
    jobs: dict = {}
    monkeypatch.setattr(M, '_JM_DAILY_PATH', str(tmp_path / 'rt' / 'jackmona_daily.json'))
    monkeypatch.setattr(M, '_JM_BATCH_PATH', str(tmp_path / 'rt' / 'jackmona_daily_batch.json'))
    monkeypatch.setattr(M, '_JM_OUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(M, '_workflow_jobs', jobs)
    monkeypatch.setattr(M, '_zero_audit_log', lambda event, payload=None: audit.append((event, payload)))
    monkeypatch.setattr(M, '_ams_now', lambda: FIXED_NOW)
    monkeypatch.setattr(M, '_ams_iso', lambda *a, **k: FIXED_ISO)
    monkeypatch.setattr(M, 'P', people)
    return SimpleNamespace(M=M, P=people, audit=audit, jobs=jobs, tmp=tmp_path)


@pytest.fixture
def client(jm):
    app = Flask(__name__)
    app.register_blueprint(M.bp)
    return app.test_client()


def manifest(pid, payload):
    """Write ``pid``'s song manifest under the redirected output root."""
    d = os.path.join(M._JM_OUT_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(payload, fh)


def episode(**over):
    """One batch entry in the shape ``_create_batch`` writes."""
    e = dict.fromkeys(('pipeline_id', 'title', 'started_at', 'ended_at', 'error'))
    e.update(id=0, series='jack', name='Jack', episode=7, moment='jack loses a shoe')
    e.update(seconds=95, singer='jack-voice', status='scheduled')
    e.update(over)
    return e


def fake_km(monkeypatch, result):
    """Install a fake ``zyg_workflows.pipeline_kidsmusic`` and record the call."""
    import zyg_workflows

    calls: list[dict] = []

    def start_kidsmusic(**kw):
        calls.append(kw)
        if isinstance(result, Exception):
            raise result
        return result

    km = SimpleNamespace(start_kidsmusic=start_kidsmusic)
    monkeypatch.setattr(zyg_workflows, 'pipeline_kidsmusic', km, raising=False)
    return calls


def unimportable(monkeypatch, name):
    """Make ``from zyg_workflows import <name>`` raise, as on a bare runner."""
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, name, raising=False)
    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', None)


# ── settings, read at every tick ────────────────────────────────────────────


def test_aq_get_reads_the_settings_then_falls_back_to_the_env_default(monkeypatch):
    import zyg_dashboard

    fake = SimpleNamespace(get=lambda section, key: f'{section}/{key}')
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.approval_queue_settings', fake)
    monkeypatch.setattr(zyg_dashboard, 'approval_queue_settings', fake, raising=False)
    assert M._aq_get('hour', 3) == 'jackmona/hour'
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.approval_queue_settings', None)
    monkeypatch.delattr(zyg_dashboard, 'approval_queue_settings')
    assert M._aq_get('hour', 11) == 11


@pytest.mark.parametrize(
    ('setting', 'expected'),
    [(0, 0), (3, 3), (23, 23), (-5, 0), (99, 23), ('7', 7), (None, M._JM_HOUR), ('half past three', M._JM_HOUR)],
)
def test_jm_hour_is_clamped_or_falls_back(monkeypatch, setting, expected):
    monkeypatch.setattr(M, '_aq_get', lambda key, default: setting)
    assert M._jm_hour() == expected


def test_the_ram_floor_the_clock_and_an_unreadable_meminfo(jm, monkeypatch):
    assert M._jm_min_ram() == M._JM_MIN_FREE_RAM_GB
    assert M._jm_today() == TODAY
    assert 0.0 < M._jm_free_ram_gb() < 4096.0  # MemAvailable on this box
    real_open = builtins.open

    def boom(path, *a, **k):
        if str(path) == '/proc/meminfo':
            raise OSError('no procfs')
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, 'open', boom)
    assert M._jm_free_ram_gb() == 999.0


def test_pipeline_busy_reports_the_running_job_and_forgives_a_broken_registry(jm, monkeypatch):
    jm.jobs['idle-1'] = {'status': 'completed'}
    assert M._jm_pipeline_busy() == ''
    jm.jobs['song-2'] = {'status': 'running'}
    assert M._jm_pipeline_busy() == 'song-2'

    class Hostile(dict):
        def items(self):
            raise RuntimeError('registry gone')

    monkeypatch.setattr(M, '_workflow_jobs', Hostile())
    assert M._jm_pipeline_busy() == ''


# ── state files ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('written', 'expected'), [(None, {}), ('not json', {}), ('[1, 2]', {}), ('{"k": 1}', {'k': 1})]
)
def test_load_defaults_on_anything_but_the_right_shape(tmp_path, written, expected):
    path = tmp_path / 'state.json'
    if written is not None:
        path.write_text(written, encoding='utf-8')
    assert M._load(str(path), {}) == expected


def test_the_two_state_files_normalise_and_round_trip(jm):
    assert M._daily_load() == {'enabled': False, 'paused': False, 'done_date': None, 'last_run_at': None}
    M._daily_save({'enabled': 1, 'paused': 0, 'done_date': TODAY, 'last_run_at': FIXED_ISO, 'junk': 'x'})
    assert M._daily_load() == {'enabled': True, 'paused': False, 'done_date': TODAY, 'last_run_at': FIXED_ISO}
    assert not os.path.exists(f'{M._JM_DAILY_PATH}.tmp')  # _save creates the dir and leaves no temp file
    assert M._batch_load() == {}
    M._batch_save({'batch_date': TODAY, 'episodes': []})
    assert M._batch_load()['batch_date'] == TODAY


# ── settling an episode, from the registry or from disk ─────────────────────


def test_disk_outcome_reads_the_manifest(jm):
    cases = [
        ({'ok': True}, 'done'),
        ({'ok': False}, 'failed'),
        ({'delivery': {'picked': True}}, 'done'),
        ({'delivery': {'picked': False}}, ''),
        ({'delivery': None}, ''),
        ({}, ''),
    ]
    for i, (payload, expected) in enumerate(cases):
        manifest(f'pid-{i}', payload)
        assert M._disk_outcome(f'pid-{i}') == expected, payload
    assert M._disk_outcome('') == ''
    assert M._disk_outcome('never-rendered') == ''
    manifest('pid-bad', {})
    (jm.tmp / 'out' / 'pid-bad' / 'manifest.json').write_text('{ truncated', encoding='utf-8')
    assert M._disk_outcome('pid-bad') == ''


@pytest.mark.parametrize(
    ('status', 'expected'),
    [('running', ''), ('completed', 'done'), ('done', 'done'), ('finished', 'done'), ('queued', ''), (None, '')],
)
def test_pipeline_outcome_from_the_registry(jm, status, expected):
    jm.jobs['pid-1'] = {'status': status}
    assert M._pipeline_outcome(episode(pipeline_id='pid-1')) == expected


@pytest.mark.parametrize('status', ['failed', 'error', 'stopped', 'aborted'])
def test_a_dead_job_still_lets_the_manifest_speak(jm, status):
    jm.jobs['pid-1'] = {'status': status}
    assert M._pipeline_outcome(episode(pipeline_id='pid-1')) == 'failed'
    manifest('pid-1', {'ok': True})
    assert M._pipeline_outcome(episode(pipeline_id='pid-1')) == 'done'


def test_pipeline_outcome_survives_a_broken_registry(jm, monkeypatch):
    class Hostile(dict):
        def get(self, key, default=None):
            raise RuntimeError('registry gone')

    monkeypatch.setattr(M, '_workflow_jobs', Hostile())
    manifest('pid-1', {'ok': True})
    assert M._pipeline_outcome(episode(pipeline_id='pid-1')) == 'done'


def test_an_orphan_is_settled_from_disk_then_by_age(jm):
    assert M._pipeline_outcome(episode(pipeline_id=None)) == 'failed'
    manifest('settled', {'ok': False})
    assert M._pipeline_outcome(episode(pipeline_id='settled')) == 'failed'
    fresh = (FIXED_NOW - timedelta(seconds=60)).isoformat()
    assert M._pipeline_outcome(episode(pipeline_id='orphan', started_at=fresh)) == ''
    stale = (FIXED_NOW - timedelta(seconds=M._JM_ORPHAN_STALE_S + 60)).isoformat()
    assert M._pipeline_outcome(episode(pipeline_id='orphan', started_at=stale)) == 'failed'
    for started in ('', 'yesterday evening'):
        assert M._pipeline_outcome(episode(pipeline_id='orphan', started_at=started)) == 'failed'


def test_title_of_reads_and_truncates_the_manifest_title(jm):
    manifest('pid-1', {'title': 'T' * 300})
    assert M._title_of('pid-1') == 'T' * 120
    manifest('pid-2', {'title': None})
    assert M._title_of('pid-2') == ''
    assert M._title_of('nope') == ''


def test_create_batch_schedules_both_series_and_records_them(jm):
    batch = M._create_batch()
    assert batch['batch_date'] == TODAY
    assert batch['auto'] is True
    assert [(e['series'], e['name']) for e in batch['episodes']] == [('jack', 'Jack'), ('mona', 'Mona')]
    assert [e['singer'] for e in batch['episodes']] == ['jack-voice', 'mona-voice']
    assert {e['status'] for e in batch['episodes']} == {'scheduled'}
    assert [r[0] for r in jm.P.recorded] == ['jack', 'mona']
    assert jm.P.recorded[0][3:] == (95, TODAY, {'status': 'scheduled'})
    assert M._batch_load() == batch
    assert jm.audit[-1][0] == 'jackmona_batch_created'
    assert len(jm.audit[-1][1]['episodes']) == 2


def test_start_episode_marks_the_entry_in_production(jm, monkeypatch):
    calls = fake_km(monkeypatch, {'job_id': 'km-1', 'status': 'running'})
    e = episode()
    M._start_episode(e)
    assert (e['status'], e['pipeline_id'], e['started_at']) == ('in_production', 'km-1', FIXED_ISO)
    assert calls[0]['directive'] == 'jack loses a shoe'
    assert calls[0]['song']['episode'] == 7
    assert jm.P.attached == [('jack', 7, 'km-1')]
    assert jm.audit[-1][0] == 'jackmona_episode_started'
    fake_km(monkeypatch, {'pipeline_id': 'km-2', 'status': 'running'})  # the other id key
    e2 = episode()
    M._start_episode(e2)
    assert (e2['status'], e2['pipeline_id']) == ('in_production', 'km-2')


@pytest.mark.parametrize(
    ('result', 'expected_error'),
    [
        ({'job_id': 'km-3', 'status': 'queued'}, 'start failed'),
        ({'error': 'ComfyUI is down'}, 'ComfyUI is down'),
        ({'job_id': 'km-4', 'status': 'running', 'error': 'half a lock'}, 'half a lock'),
        ({}, 'start failed'),
        ('not a dict at all', 'start failed'),
        (RuntimeError('submit lock held'), 'RuntimeError: submit lock held'),
    ],
)
def test_start_episode_records_every_refusal(jm, monkeypatch, result, expected_error):
    fake_km(monkeypatch, result)
    e = episode()
    M._start_episode(e)
    assert (e['status'], e['error'], e['ended_at']) == ('failed', expected_error, FIXED_ISO)
    assert jm.audit[-1][0] == 'jackmona_episode_start_failed'


def test_start_episode_without_the_workflow_or_without_a_brief(jm, monkeypatch):
    unimportable(monkeypatch, 'pipeline_kidsmusic')
    e = episode()
    M._start_episode(e)
    assert (e['status'], e['ended_at']) == ('failed', FIXED_ISO)
    assert "children's music workflow unavailable" in e['error']
    fake_km(monkeypatch, {'job_id': 'km-5', 'status': 'running'})
    jm.P.brief_exc = ValueError('no moments left')
    e2 = episode()
    M._start_episode(e2)
    assert e2['status'] == 'failed'
    assert e2['error'].startswith('brief failed: ValueError: no moments left')


# ── the batch tick ──────────────────────────────────────────────────────────


def test_batch_tick_settles_a_finished_episode(jm):
    jm.jobs['km-1'] = {'status': 'completed'}
    manifest('km-1', {'title': 'Jack and the Shoe'})
    M._batch_save({'episodes': [episode(status='in_production', pipeline_id='km-1'), episode(id=1, series='mona')]})
    M._batch_tick()
    eps = M._batch_load()['episodes']
    assert (eps[0]['status'], eps[0]['title'], eps[0]['ended_at']) == ('done', 'Jack and the Shoe', FIXED_ISO)
    assert jm.P.settled == [('jack', 'km-1', 'Jack and the Shoe', 'done')]


def test_batch_tick_settles_a_failed_episode_and_starts_the_next(jm, monkeypatch):
    jm.jobs['km-1'] = {'status': 'failed'}
    calls = fake_km(monkeypatch, {'job_id': 'km-2', 'status': 'running'})
    monkeypatch.setattr(M, '_jm_free_ram_gb', lambda: 999.0)
    M._daily_save({'enabled': True})
    M._batch_save({'episodes': [episode(status='in_production', pipeline_id='km-1'), episode(id=1, series='mona')]})
    M._batch_tick()
    eps = M._batch_load()['episodes']
    assert (eps[0]['status'], eps[0]['error']) == ('failed', 'pipeline failed')
    assert jm.P.settled == [('jack', 'km-1', None, 'failed')]
    assert eps[1]['status'] == 'in_production'
    assert len(calls) == 1


def test_batch_tick_starts_only_the_first_scheduled_episode(jm, monkeypatch):
    monkeypatch.setattr(M, '_jm_free_ram_gb', lambda: 999.0)
    fake_km(monkeypatch, {'job_id': 'km-7', 'status': 'running'})
    M._daily_save({'enabled': True})
    M._batch_save({'episodes': [episode(), episode(id=1, series='mona')]})
    M._batch_tick()
    eps = M._batch_load()['episodes']
    assert (eps[0]['status'], eps[0]['pipeline_id']) == ('in_production', 'km-7')
    assert eps[1]['status'] == 'scheduled'


def test_batch_tick_waits_while_an_episode_is_still_running(jm, monkeypatch):
    jm.jobs['km-1'] = {'status': 'running'}
    monkeypatch.setattr(M, '_start_episode', lambda e: pytest.fail('must not start a second episode'))
    M._daily_save({'enabled': True})
    M._batch_save({'episodes': [episode(status='in_production', pipeline_id='km-1'), episode(id=1, series='mona')]})
    M._batch_tick()
    assert M._batch_load()['episodes'][1]['status'] == 'scheduled'


@pytest.mark.parametrize(
    ('daily', 'eps', 'extra_job', 'ram'),
    [
        ({'enabled': False}, [episode()], None, 999.0),  # toggle off
        ({'enabled': True, 'paused': True}, [episode()], None, 999.0),  # paused
        ({'enabled': True}, [episode(status='done'), episode(id=1, status='failed')], None, 999.0),  # none scheduled
        ({'enabled': True}, [episode()], 'doc-9', 999.0),  # another department has the GPU
        ({'enabled': True}, [episode()], None, 1.0),  # not enough free RAM
    ],
)
def test_batch_tick_starts_nothing_when_it_must_not(jm, monkeypatch, daily, eps, extra_job, ram):
    if extra_job:
        jm.jobs[extra_job] = {'status': 'running'}
    monkeypatch.setattr(M, '_jm_free_ram_gb', lambda: ram)
    monkeypatch.setattr(M, '_start_episode', lambda e: pytest.fail('must not start'))
    M._daily_save(daily)
    M._batch_save({'episodes': eps})
    M._batch_tick()
    assert [e['status'] for e in M._batch_load()['episodes']] == [e['status'] for e in eps]


def test_scheduler_tick_is_inert_unless_the_day_is_due(jm, monkeypatch):
    M._batch_tick()  # no batch at all: both ticks are no-ops
    M._scheduler_tick()  # toggle off
    M._daily_save({'enabled': True, 'done_date': TODAY})
    M._scheduler_tick()  # already ran today
    M._daily_save({'enabled': True})
    monkeypatch.setattr(M, '_jm_hour', lambda: 23)
    M._scheduler_tick()  # the hour has not come
    assert M._batch_load() == {}
    assert M._daily_load()['done_date'] is None


def test_scheduler_tick_carries_an_unsettled_pair_over(jm):
    M._daily_save({'enabled': True})
    for status in ('scheduled', 'in_production'):
        M._batch_save({'batch_date': '2026-05-03', 'episodes': [episode(status=status)]})
        M._scheduler_tick()
        assert M._batch_load()['batch_date'] == '2026-05-03'


def test_scheduler_tick_creates_the_pair_and_stamps_the_day(jm, monkeypatch):
    monkeypatch.setattr(M, '_jm_hour', lambda: 3)
    M._daily_save({'enabled': True})
    M._batch_save({'batch_date': '2026-05-03', 'episodes': [episode(status='done')]})
    M._scheduler_tick()
    assert M._batch_load()['batch_date'] == TODAY
    daily = M._daily_load()
    assert (daily['done_date'], daily['last_run_at']) == (TODAY, FIXED_ISO)


# ── the watcher daemon ──────────────────────────────────────────────────────


class StopWatcher(Exception):
    """Breaks ``_watcher``'s endless loop from inside its own sleep."""


def test_watcher_runs_both_ticks_and_survives_a_raising_one(jm, monkeypatch):
    ran: list[str] = []
    sleeps: list[int] = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise StopWatcher

    def boom():
        ran.append('batch')
        raise RuntimeError('disk full')

    monkeypatch.setattr(M, 'time', SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(M, '_scheduler_tick', lambda: ran.append('scheduler'))
    monkeypatch.setattr(M, '_batch_tick', boom)
    with pytest.raises(StopWatcher):
        M._watcher()
    assert ran == ['scheduler', 'batch']
    assert sleeps == [30, 30]


def test_next_run_label_is_blank_while_disabled_and_defers_to_a_live_pair(jm):
    assert M._next_run_label() == ''
    M._daily_save({'enabled': True})
    M._batch_save({'episodes': [episode(status='in_production')]})
    assert M._next_run_label() == 'after the current pair'


@pytest.mark.parametrize(
    ('hour', 'done_date', 'expected'),
    [(23, None, f'{TODAY} 23:00'), (3, None, '2026-05-05 03:00'), (23, TODAY, '2026-05-05 23:00')],
)
def test_next_run_label_picks_the_next_due_day(jm, monkeypatch, hour, done_date, expected):
    monkeypatch.setattr(M, '_jm_hour', lambda: hour)
    M._daily_save({'enabled': True, 'done_date': done_date})
    assert M._next_run_label() == expected


def test_set_enabled_on_and_off_clears_the_pause(jm):
    assert M._set_paused(True)['paused'] is True
    state = M._set_enabled(True)
    assert (state['enabled'], state['paused']) == (True, True)
    off = M._set_enabled(False)
    assert (off['enabled'], off['paused']) == (False, False)
    assert M._set_paused(False)['paused'] is False
    pause, mode = 'jackmona_daily_pause', 'jackmona_daily_mode'
    assert [a[0] for a in jm.audit] == [pause, mode, mode, pause]


def test_abort_stops_the_live_episode_and_fails_the_rest(jm, monkeypatch):
    import zyg_workflows

    halts: list[str] = []
    stopped: list[bool] = []
    monkeypatch.setattr(zyg_workflows, 'pipeline_control', SimpleNamespace(request_halt=halts.append), raising=False)
    jm.jobs['km-1'] = {'stop_event': SimpleNamespace(set=lambda: stopped.append(True))}
    eps = [
        episode(status='in_production', pipeline_id='km-1'),
        episode(id=1, series='mona'),
        episode(id=2, status='done'),
    ]
    M._batch_save({'episodes': eps})
    assert M._abort() == {'ok': True, 'stopped': 'km-1'}
    assert stopped == [True]
    assert halts == ['Aborted from the Approval Queue']
    saved = M._batch_load()['episodes']
    assert [e['status'] for e in saved] == ['failed', 'failed', 'done']
    assert saved[0]['error'] == 'aborted by operator'
    assert jm.audit[-1] == ('jackmona_abort', {'stopped': 'km-1'})


def test_abort_fails_the_entry_even_when_the_halt_request_breaks(jm, monkeypatch):
    unimportable(monkeypatch, 'pipeline_control')
    jm.jobs['km-1'] = {}
    M._batch_save({'episodes': [episode(status='in_production', pipeline_id='km-1')]})
    assert M._abort() == {'ok': True, 'stopped': None}
    assert M._batch_load()['episodes'][0]['status'] == 'failed'
    M._save(M._JM_BATCH_PATH, {})
    assert M._abort() == {'ok': True, 'stopped': None}  # an empty batch aborts cleanly


# ── HTTP ────────────────────────────────────────────────────────────────────


def test_daily_mode_get_then_enable_pause_and_disable(client, jm):
    r = client.get('/api/jackmona/daily_mode')
    assert r.status_code == 200
    assert r.get_json() == {'enabled': False, 'paused': False, 'done_date': None, 'last_run_at': None}
    r = client.post('/api/jackmona/daily_mode', json={'enabled': True})
    assert r.status_code == 200
    assert (r.get_json()['ok'], r.get_json()['enabled']) == (True, True)
    assert M._daily_load()['enabled'] is True
    r = client.post('/api/jackmona/daily_mode', json={'paused': True})
    assert (r.status_code, r.get_json()['state']['paused']) == (200, True)
    r = client.post('/api/jackmona/daily_mode', data='not json', content_type='text/plain')
    assert (r.status_code, r.get_json()['enabled']) == (200, False)


def test_post_daily_mode_reports_a_write_failure(client, jm, monkeypatch):
    def boom(enabled):
        raise OSError('read-only runtime')

    monkeypatch.setattr(M, '_set_enabled', boom)
    r = client.post('/api/jackmona/daily_mode', json={'enabled': True})
    assert r.status_code == 500
    assert r.get_json() == {'ok': False, 'error': 'read-only runtime'}


@pytest.mark.parametrize('path', ['/api/jackmona/daily_mode', '/api/jackmona/abort', '/api/jackmona/run_now'])
def test_the_write_routes_are_localhost_only(client, jm, path):
    r = client.post(path, json={}, environ_base=REMOTE)
    assert r.status_code == 401
    assert r.get_json() == {'error': 'localhost only'}


def test_daily_batch_is_the_whole_card(client, jm, monkeypatch):
    import zyg_workflows

    monkeypatch.setattr(zyg_workflows, 'SONG_SECONDS', (60, 90, 120), raising=False)
    monkeypatch.setattr(M, '_jm_hour', lambda: 3)
    empty = client.get('/api/jackmona/daily_batch').get_json()
    assert (empty['batch'], empty['next_run'], empty['busy_with']) == (None, '', '')
    M._set_enabled(True)
    M._create_batch()
    jm.jobs['doc-9'] = {'status': 'running'}
    r = client.get('/api/jackmona/daily_batch')
    assert r.status_code == 200
    body = r.get_json()
    assert body['batch']['batch_date'] == TODAY
    assert body['daily']['enabled'] is True
    assert body['next_run'] == 'after the current pair'
    assert body['busy_with'] == 'doc-9'
    assert body['series'] == jm.P.series_rows()
    assert body['seconds_band'] == [60, 90, 120]


def test_abort_route(client, jm):
    M._batch_save({'episodes': [episode()]})
    r = client.post('/api/jackmona/abort')
    assert r.status_code == 200
    assert r.get_json() == {'ok': True, 'stopped': None}
    assert M._batch_load()['episodes'][0]['status'] == 'failed'


def test_run_now_builds_the_pair_and_stamps_the_day(client, jm):
    r = client.post('/api/jackmona/run_now')
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert [e['series'] for e in body['batch']['episodes']] == ['jack', 'mona']
    assert body['enabled'] is False
    assert M._daily_load()['done_date'] == TODAY


def test_run_now_refuses_while_a_pair_is_in_flight(client, jm):
    M._batch_save({'batch_date': TODAY, 'episodes': [episode(status='in_production', pipeline_id='km-1')]})
    r = client.post('/api/jackmona/run_now')
    assert r.status_code == 409
    assert r.get_json()['error'] == 'a pair is already in flight'
    assert jm.P.recorded == []
