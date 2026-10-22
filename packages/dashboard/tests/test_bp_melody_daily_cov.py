# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for ``zyg_dashboard.bp_melody_daily``, the Melody daily auto-batcher.

Offline by construction: the three state paths, the output root, the audit log, the clock,
the job registry, the settings card, the song bank and the Ollama hop are all replaced, so
no test touches the repo's runtime JSON, the local model or the GPU.
"""

from __future__ import annotations

import builtins
import contextlib
import json
import logging
import os
import sys
import threading as _threading
import urllib.request
from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import Flask

# bp_melody_daily starts its `melody-daily-watcher` thread on its last line; a second copy must
# not run inside the test process (it would poll the live queues and trip tests/api/conftest.py's
# thread-leak check), so the thread is neutered for the import only — as test_bp_jackmona_daily_cov.
_real_thread_start = _threading.Thread.start


def _no_watcher_start(self):
    if self.name == 'melody-daily-watcher':
        return None
    return _real_thread_start(self)


_threading.Thread.start = _no_watcher_start
try:
    import zyg_dashboard.bp_melody_daily as M
finally:
    _threading.Thread.start = _real_thread_start

FIXED_NOW = datetime(2026, 5, 4, 9, 30, 0)
FIXED_ISO = '2026-05-04T09:30:00'
TODAY = '2026-05-04'


def _boom(*a, **kw):  # a dependency that is simply not there
    raise RuntimeError('offline')


@pytest.fixture
def mel(tmp_path, monkeypatch):
    """The module with every outside edge redirected into ``tmp_path``."""
    audit: list[tuple] = []
    jobs: dict = {}
    monkeypatch.setattr(M, '_MEL_DAILY_PATH', str(tmp_path / 'rt' / 'melody_daily.json'))
    monkeypatch.setattr(M, '_MEL_BATCH_PATH', str(tmp_path / 'rt' / 'melody_daily_batch.json'))
    monkeypatch.setattr(M, '_MEL_HISTORY_PATH', str(tmp_path / 'rt' / 'melody_daily_history.json'))
    monkeypatch.setattr(M, '_MEL_OUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(M, '_workflow_jobs', jobs)
    monkeypatch.setattr(M, '_zero_audit_log', lambda event, payload=None: audit.append((event, payload)))
    monkeypatch.setattr(M, '_ams_now', lambda: FIXED_NOW)
    monkeypatch.setattr(M, '_ams_iso', lambda *a, **k: FIXED_ISO)
    # Default-only stand-ins for the settings card and the pre-emptive song bank, read at every
    # tick: they keep the repo's approval_queue_settings.json out of the tests. Both are tested
    # for real below.
    monkeypatch.setattr(M, '_aq_get', lambda key, default: default)
    monkeypatch.setattr(M, '_aq_bank', lambda: None)
    return SimpleNamespace(M=M, audit=audit, jobs=jobs, tmp=tmp_path)


@pytest.fixture
def client(mel):
    app = Flask(__name__)
    app.register_blueprint(M.bp)
    return app.test_client()


def manifest(pid, payload, raw=None):
    """Write ``pid``'s song manifest under the redirected output root."""
    d = os.path.join(M._MEL_OUT_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'manifest.json')
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(raw if raw is not None else json.dumps(payload))
    return d


def song(**over):
    """One batch entry in the shape ``_mel_create_daily_batch`` writes."""
    e = dict.fromkeys(('pipeline_id', 'title', 'started_at', 'ended_at', 'error'))
    e.update(id=0, theme='a little green frog who hops', mood='playful', age_band='toddler')
    e.update(theme_source='pool', bank_id=None, status='scheduled')
    e.update(over)
    return e


def batch(*songs, date=TODAY):
    return {'batch_date': date, 'created_at': FIXED_ISO, 'auto': True, 'per_day': 5, 'songs': list(songs)}


def test_the_card_and_the_bank_are_optional_and_their_settings_are_clamped(monkeypatch):
    import zyg_dashboard

    card = SimpleNamespace(get=lambda section, key: f'{section}/{key}')
    bank = SimpleNamespace(songs_take=lambda n: [])
    for name, mod in (('approval_queue_settings', card), ('preempt_bank', bank)):
        monkeypatch.setitem(sys.modules, f'zyg_dashboard.{name}', mod)
        monkeypatch.setattr(zyg_dashboard, name, mod, raising=False)
    assert M._aq_get('hour', 3) == 'melody/hour'
    assert M._aq_bank() is bank
    for name in ('approval_queue_settings', 'preempt_bank'):
        monkeypatch.setitem(sys.modules, f'zyg_dashboard.{name}', None)
        monkeypatch.delattr(zyg_dashboard, name)
    assert M._aq_get('hour', 11) == 11  # the env default survives a missing card
    assert M._aq_bank() is None
    for setting, expected in [(0, 1), (3, 3), (20, 20), (-5, 1), (99, 20), ('7', 7)]:
        monkeypatch.setattr(M, '_aq_get', lambda key, default, s=setting: s)
        assert M._mel_per_day() == expected, setting
    for setting, expected in [(0, 0), (9, 9), (23, 23), (-5, 0), (99, 23), ('7', 7)]:
        monkeypatch.setattr(M, '_aq_get', lambda key, default, s=setting: s)
        assert M._mel_hour() == expected, setting
    monkeypatch.setattr(M, '_aq_get', lambda key, default: '12.5')
    assert M._mel_min_ram() == 12.5
    monkeypatch.setattr(M, '_aq_get', lambda key, default: default)
    assert M._mel_min_ram() == M._MEL_MIN_FREE_RAM_GB


def test_bank_settle_needs_both_a_bank_and_a_bank_id(mel, monkeypatch, caplog):
    M._mel_bank_settle(song(bank_id='b0'), 'done')  # no bank at all → inert
    settled: list[tuple] = []
    bank = SimpleNamespace(songs_settle=lambda bid, outcome, pid: settled.append((bid, outcome, pid)))
    monkeypatch.setattr(M, '_aq_bank', lambda: bank)
    M._mel_bank_settle(song(), 'done')  # no bank_id → inert
    assert settled == []
    M._mel_bank_settle(song(bank_id='b1', pipeline_id='km-1'), 'done')
    assert settled == [('b1', 'done', 'km-1')]
    monkeypatch.setattr(M, '_aq_bank', lambda: SimpleNamespace(songs_settle=_boom))
    with caplog.at_level(logging.WARNING, logger=M.__name__):
        M._mel_bank_settle(song(bank_id='b2'), 'failed')
    assert 'bank settle for b2 failed' in caplog.text


def test_the_json_helpers_and_the_three_state_files_round_trip(mel, caplog):
    assert M._mel_today() == TODAY
    p = str(mel.tmp / 'rt' / 'state.json')
    assert M._mel_load(p, dict) == {}
    assert M._mel_load(p, {'a': 1}) == {'a': 1}
    M._mel_save(p, {'k': 1})
    assert M._mel_load(p, dict) == {'k': 1}
    assert not os.path.exists(p + '.tmp')  # _save creates the dir and leaves no temp file
    os.makedirs(p + '.tmp')  # a directory where the temp file belongs: the write cannot land
    with caplog.at_level(logging.WARNING, logger=M.__name__):
        M._mel_save(p, {'k': 2})
    assert 'is not persisted' in caplog.text
    assert M._mel_load(p, dict) == {'k': 1}
    assert M._mel_daily_load() == {
        'enabled': False,
        'done_date': None,
        'last_run_at': None,
        'per_day': M._MEL_PER_DAY,
        'hour': M._MEL_HOUR,
        'paused': False,
    }
    M._mel_daily_save({'enabled': 1, 'paused': 0, 'done_date': TODAY, 'last_run_at': FIXED_ISO, 'junk': 'x'})
    d = M._mel_daily_load()
    assert (d['enabled'], d['paused'], d['done_date'], d['last_run_at']) == (True, False, TODAY, FIXED_ISO)
    assert M._mel_batch_load() == {}
    M._mel_batch_save(batch())
    assert M._mel_batch_load()['batch_date'] == TODAY
    assert M._mel_history_load() == []
    M._mel_history_add(['  a frog  ', '', 'a duck'])
    assert M._mel_history_load() == ['a frog', 'a duck']
    M._mel_history_add([str(i) for i in range(500)])
    assert M._mel_history_load() == [str(i) for i in range(100, 500)]  # kept at the last 400


def test_the_gates_read_meminfo_and_the_job_registry_and_forgive_both(mel, monkeypatch):
    mel.jobs['idle-1'] = {'status': 'completed'}
    assert M._mel_pipeline_busy() == ''
    mel.jobs['song-2'] = {'status': 'running'}
    assert M._mel_pipeline_busy() == 'song-2'

    class Hostile(dict):
        def items(self):
            raise RuntimeError('registry gone')

    monkeypatch.setattr(M, '_workflow_jobs', Hostile())
    assert M._mel_pipeline_busy() == ''
    assert 0.0 < M._mel_free_ram_gb() < 4096.0  # MemAvailable on this box
    real_open = builtins.open

    def no_procfs(path, *a, **k):
        if str(path) == '/proc/meminfo':
            raise OSError('no procfs')
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, 'open', no_procfs)
    assert M._mel_free_ram_gb() == 999.0


def test_disk_outcome_reads_the_manifest_then_the_folder_age(mel):
    for i, (payload, expected) in enumerate([({'ok': True}, 'done'), ({}, 'done'), ({'ok': False}, 'failed')]):
        manifest(f'pid-{i}', payload)
        assert M._mel_disk_outcome(f'pid-{i}') == expected, payload
    assert M._mel_disk_outcome('never-rendered') == 'failed'  # no folder at all
    os.makedirs(os.path.join(M._MEL_OUT_ROOT, 'fresh'))
    assert M._mel_disk_outcome('fresh') == 'running'  # touched just now
    old = os.path.join(M._MEL_OUT_ROOT, 'old')
    os.makedirs(old)
    long_ago = FIXED_NOW.timestamp() - M._MEL_ORPHAN_STALE_S * 4
    os.utime(old, (long_ago, long_ago))
    assert M._mel_disk_outcome('old') == 'failed'
    truncated = manifest('pid-bad', None, raw='{ truncated')
    os.symlink('nowhere-at-all', os.path.join(truncated, 'broken'))
    assert M._mel_disk_outcome('pid-bad') == 'failed'  # a dangling link breaks getmtime
    manifest('titled', {'title': 'T' * 300})
    assert M._mel_song_title('titled') == 'T' * 120
    manifest('untitled', {'title': None})
    assert M._mel_song_title('untitled') == ''
    assert M._mel_song_title('nope') == ''


def test_pipeline_outcome_reads_the_registry_then_the_public_status_then_the_disk(mel, monkeypatch):
    registry = [('completed', 'done'), ('done', 'done'), ('Succeeded', 'done'), ('finished', 'done')]
    registry += [('failed', 'failed'), ('cancelled', 'failed'), ('halted', 'failed'), ('rejected', 'failed')]
    for status, expected in registry:
        mel.jobs['km-1'] = {'status': status}
        assert M._mel_pipeline_outcome('km-1') == expected, status
    public = [('all stages complete', 'done'), ('finished', 'done'), ('failed hard', 'failed')]
    public += [('cancel requested', 'failed'), ('stage 3 of 7', 'running'), ('', 'running'), (None, 'running')]
    mel.jobs['km-1'] = {'status': 'running'}
    for pub, expected in public:
        monkeypatch.setattr(M, '_resolve_pipeline_public_status', lambda job, p=pub: p)
        assert M._mel_pipeline_outcome('km-1') == expected, pub
    monkeypatch.setattr(M, '_resolve_pipeline_public_status', _boom)
    assert M._mel_pipeline_outcome('km-1') == 'running'
    assert M._mel_pipeline_outcome('') == 'failed'
    assert M._mel_pipeline_outcome('orphan') == 'failed'  # gone from the registry, nothing on disk
    manifest('orphan', {'ok': True})
    assert M._mel_pipeline_outcome('orphan') == 'done'


def test_norm_the_theme_gate_and_the_themes_already_produced(mel, caplog):
    assert M._mel_norm('A Little, Green FROG!') == 'a little green frog'
    assert M._mel_norm(None) == ''
    avoid = {'a little green frog'}
    rows = [('a little green frog', False), ('A Little Green Frog!', False), ('short', False)]
    rows += [('x' * 91, False), ('a frog who is dead in the pond', False), (None, False)]
    rows += [('a brand new puppy learning to sit', True)]
    for theme, want in rows:
        assert M._mel_theme_ok(theme, avoid) is want, theme
    with caplog.at_level(logging.WARNING, logger=M.__name__):
        assert M._mel_produced_themes() == set()  # there is no output root yet
    assert 'output root unreadable' in caplog.text
    manifest('a', {'brief': {'theme': 'A Little Green Frog'}})
    manifest('b', {'brief': {}})
    manifest('c', {})
    manifest('d', {'brief': None})
    manifest('e', None, raw='{ truncated')
    os.makedirs(os.path.join(M._MEL_OUT_ROOT, 'f'))  # a folder with no manifest at all
    M._mel_history_add(['Sleepy Moon!'])
    assert M._mel_produced_themes() == {'a little green frog', 'sleepy moon'}


def test_pool_briefs_skip_used_themes_then_reuse_with_an_offset(mel):
    out = M._mel_pool_briefs(3, set())
    assert [b['source'] for b in out] == ['pool'] * 3
    assert [b['theme'] for b in out] == [t for t, _, _ in M._MEL_SEED_POOL[:3]]
    avoid = {M._mel_norm(t) for t, _, _ in M._MEL_SEED_POOL}
    M._mel_history_add(['one', 'two'])  # len(history) is the offset the reuse rotates by
    out = M._mel_pool_briefs(2, avoid)
    assert [b['source'] for b in out] == ['pool-reused'] * 2
    assert [b['theme'] for b in out] == [M._MEL_SEED_POOL[2][0], M._MEL_SEED_POOL[3][0]]


def _llm(monkeypatch, reply, *, via_audit=True):
    """Point the module's Ollama hop at a canned reply (``None`` = the box is down)."""
    import zyg_workflows

    probe = _boom if reply is None else (lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setitem(sys.modules, 'zyg_workflows.net', SimpleNamespace(safe_urlopen=probe))
    if via_audit:
        la = SimpleNamespace(ollama_post=lambda url, payload, timeout=0, stage='': reply)
        monkeypatch.setitem(sys.modules, 'zyg_workflows.llm_audit', la)
        monkeypatch.setattr(zyg_workflows, 'llm_audit', la, raising=False)
        return
    monkeypatch.setitem(sys.modules, 'zyg_workflows.llm_audit', None)  # → the urllib fallback
    monkeypatch.delattr(zyg_workflows, 'llm_audit', raising=False)

    class _Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(reply).encode()

    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: _Reply())


_GOOD = {
    'Songs': [  # the capitalised key the model returns a good fraction of the time
        {'theme': 'a  little red   train that says toot toot.', 'mood': 'happy', 'age_band': 'toddler'},
        'a paper boat sailing down the rainy street',  # a bare string row
        42,  # not a row at all
        {'topic': 'a tiny seed that grows into a sunflower', 'mood': 'nope', 'audience': 'martian'},
        {'theme': 'tiny'},  # too short for the theme gate
    ]
}


def test_propose_briefs_parses_the_models_answer_in_every_shape(mel, monkeypatch):
    M._mel_history_add(['a frog'])  # so the prompt names recent themes too
    _llm(monkeypatch, {'response': '```' + json.dumps(_GOOD) + '```'})
    out = M._mel_propose_briefs(3, set())
    assert [b['theme'] for b in out] == [
        'a little red train that says toot toot',
        'a paper boat sailing down the rainy street',
        'a tiny seed that grows into a sunflower',
    ]
    assert [b['mood'] for b in out] == ['happy', 'playful', 'marching']  # rotated when unusable
    assert [b['age_band'] for b in out] == ['toddler', 'preschool', 'early']
    assert {b['source'] for b in out} == {'llm'}
    _llm(monkeypatch, {'response': '', 'thinking': '{"themes": "a kite that pulls against the string"}'})
    assert [b['theme'] for b in M._mel_propose_briefs(2, set())] == ['a kite that pulls against the string']
    reply = {'response': json.dumps({'topics': [{'theme': 'a snowman built in the front garden'}]})}
    _llm(monkeypatch, reply, via_audit=False)
    assert M._mel_propose_briefs(1, set())[0]['theme'] == 'a snowman built in the front garden'
    _llm(monkeypatch, {'response': json.dumps(_GOOD)})
    train = M._mel_norm('a little red train that says toot toot')
    assert train not in {M._mel_norm(b['theme']) for b in M._mel_propose_briefs(2, {train})}
    _llm(monkeypatch, None)
    assert M._mel_propose_briefs(2, set()) == []


def test_pick_briefs_takes_the_bank_first_then_tops_up(mel, monkeypatch):
    rows = [{'id': f'b{i}', 'theme': f'bank song {i} about a sleepy cat', 'mood': None} for i in range(4)]
    monkeypatch.setattr(M, '_aq_bank', lambda: SimpleNamespace(songs_take=lambda n: rows[:n]))
    got = M._mel_pick_briefs(2)
    assert [b['source'] for b in got] == ['bank'] * 2
    assert [b['bank_id'] for b in got] == ['b0', 'b1']
    assert [b['mood'] for b in got] == ['happy', 'playful']  # rotated: the bank left them empty
    llm = {'theme': 'an llm topic about a windmill turning', 'mood': 'gentle', 'age_band': 'early', 'source': 'llm'}
    monkeypatch.setattr(M, '_aq_bank', lambda: SimpleNamespace(songs_take=lambda n: rows[:1]))
    monkeypatch.setattr(M, '_mel_propose_briefs', lambda n, avoid: [llm][:n])
    assert [b['source'] for b in M._mel_pick_briefs(4)] == ['bank', 'llm', 'pool', 'pool']
    monkeypatch.setattr(M, '_aq_bank', lambda: SimpleNamespace(songs_take=_boom))
    assert [b['source'] for b in M._mel_pick_briefs(1)] == ['llm']  # a bank that throws is skipped


def _km_stub(monkeypatch, info):
    """Stand in for the two workflow modules ``_mel_start_song`` imports."""
    import zyg_workflows

    theory = SimpleNamespace(song_seconds=lambda i: 130 + i, DEFAULT_SINGER='alto')
    km = SimpleNamespace(start_kidsmusic=info if callable(info) else (lambda directive, song: info))
    for name, mod in (('kids_music_theory', theory), ('pipeline_kidsmusic', km)):
        monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', mod)
        monkeypatch.setattr(zyg_workflows, name, mod, raising=False)


def test_start_song_without_the_workflow_package_fails_the_entry(mel, monkeypatch):
    import zyg_workflows

    monkeypatch.setitem(sys.modules, 'zyg_workflows.kids_music_theory', None)
    monkeypatch.delattr(zyg_workflows, 'kids_music_theory', raising=False)
    e = song()
    M._mel_start_song(e)
    want = ('failed', 'melody workflow unavailable: ModuleNotFoundError', FIXED_ISO)
    assert (e['status'], e['error'], e['ended_at']) == want


def test_start_song_records_the_pipeline_it_launched(mel, monkeypatch):
    seen = {}

    def start(directive, song):
        seen.update(directive=directive, song=song)
        return {'job_id': 'km-7', 'status': 'running'}

    _km_stub(monkeypatch, start)
    e = song(id=2)
    M._mel_start_song(e)
    assert (e['status'], e['pipeline_id'], e['started_at']) == ('in_production', 'km-7', FIXED_ISO)
    assert seen['directive'] == e['theme']
    assert seen['song']['seconds'] == 132 and seen['song']['singer'] == 'alto'
    assert seen['song']['sung'] is True and seen['song']['candidates'] == 48
    assert mel.audit[-1] == ('melody_daily_song_started', {'theme': e['theme'][:200], 'pipeline_id': 'km-7'})


@pytest.mark.parametrize(
    'info,error',
    [
        ({'error': 'the renderer is down'}, 'the renderer is down'),
        ({'job_id': 'km-8', 'status': 'queued'}, 'start failed'),
        ('not a dict at all', 'start failed'),
        (_boom, 'RuntimeError: offline'),
    ],
)
def test_start_song_failures_are_recorded_on_the_entry(mel, monkeypatch, info, error):
    _km_stub(monkeypatch, info)
    e = song()
    M._mel_start_song(e)
    assert (e['status'], e['error'], e['ended_at']) == ('failed', error, FIXED_ISO)
    assert mel.audit[-1][0] == 'melody_daily_song_start_failed'


def test_batch_tick_settles_a_finished_song_then_starts_the_next(mel, monkeypatch):
    settled, started = [], []
    monkeypatch.setattr(M, '_mel_bank_settle', lambda e, o: settled.append(o))
    monkeypatch.setattr(M, '_mel_start_song', lambda e: started.append(e['id']))
    monkeypatch.setattr(M, '_mel_free_ram_gb', lambda: 999.0)
    M._mel_batch_tick()  # no state file at all
    M._mel_batch_save(batch())
    M._mel_batch_tick()  # a batch with no songs
    manifest('km-1', {'ok': True, 'title': 'The Little Green Frog'})
    M._mel_batch_save(batch(song(id=0, status='in_production', pipeline_id='km-1'), song(id=1)))
    M._mel_daily_save({'enabled': True})
    M._mel_batch_tick()
    s = M._mel_batch_load()['songs']
    assert (s[0]['status'], s[0]['title'], s[0]['ended_at']) == ('done', 'The Little Green Frog', FIXED_ISO)
    assert settled == ['done'] and started == [1]


def test_batch_tick_fails_a_vanished_pipeline_waits_on_a_live_one_and_gates_the_start(mel, monkeypatch):
    started = []
    monkeypatch.setattr(M, '_mel_bank_settle', lambda e, o: None)
    monkeypatch.setattr(M, '_mel_free_ram_gb', lambda: 999.0)
    monkeypatch.setattr(M, '_mel_start_song', lambda e: started.append(e['id']))
    M._mel_daily_save({'enabled': True})
    M._mel_batch_save(batch(song(id=0, status='in_production', pipeline_id='gone')))
    M._mel_batch_tick()  # no job, no folder → the entry is settled as failed
    s = M._mel_batch_load()['songs']
    assert (s[0]['status'], s[0]['error']) == ('failed', 'pipeline failed')
    mel.jobs['km-2'] = {'status': 'running'}
    monkeypatch.setattr(M, '_resolve_pipeline_public_status', lambda job: 'stage 2 of 7')
    M._mel_batch_save(batch(song(id=0, status='in_production', pipeline_id='km-2'), song(id=1)))
    M._mel_batch_tick()  # still in production → the next song waits
    assert M._mel_batch_load()['songs'][1]['status'] == 'scheduled'
    M._mel_batch_save(batch(song(id=0)))
    M._mel_daily_save({'enabled': False})
    M._mel_batch_tick()  # the toggle is off
    M._mel_daily_save({'enabled': True, 'paused': True})
    M._mel_batch_tick()  # the card is paused
    M._mel_daily_save({'enabled': True})
    M._mel_batch_save(batch(song(id=0, status='done')))
    M._mel_batch_tick()  # nothing is scheduled
    M._mel_batch_save(batch(song(id=0)))
    M._mel_batch_tick()  # km-2, another department, has the GPU
    mel.jobs.clear()
    monkeypatch.setattr(M, '_mel_free_ram_gb', lambda: 1.0)
    M._mel_batch_tick()  # not enough free RAM
    assert started == []


def test_scheduler_tick_builds_at_most_one_batch_a_day(mel, monkeypatch):
    created = []
    monkeypatch.setattr(M, '_mel_create_daily_batch', lambda: created.append(1))
    M._mel_scheduler_tick()  # the toggle is off
    M._mel_daily_save({'enabled': True, 'done_date': TODAY})
    M._mel_scheduler_tick()  # already built today
    M._mel_daily_save({'enabled': True})
    M._mel_batch_save(batch(song(id=0)))
    M._mel_scheduler_tick()  # yesterday's batch is still live
    M._mel_batch_save(batch(song(id=0, status='done')))
    monkeypatch.setattr(M, '_aq_get', lambda key, default: 23 if key == 'hour' else default)
    M._mel_scheduler_tick()  # 09:30 is before the 23:00 build hour
    assert created == []
    monkeypatch.setattr(M, '_aq_get', lambda key, default: 0 if key == 'hour' else default)
    M._mel_scheduler_tick()
    assert created == [1]
    d = M._mel_daily_load()
    assert (d['done_date'], d['last_run_at']) == (TODAY, FIXED_ISO)


class _Stop(Exception):
    """Breaks the watcher's endless loop from inside its own sleep."""


def test_the_watcher_logs_both_tick_failures_and_keeps_going(mel, monkeypatch, caplog):
    ticks = []

    def sleep(seconds):
        ticks.append(seconds)
        if len(ticks) > 1:  # let the loop go round twice, then leave it
            raise _Stop

    monkeypatch.setattr(M.time, 'sleep', sleep)
    monkeypatch.setattr(M, '_mel_scheduler_tick', _boom)
    monkeypatch.setattr(M, '_mel_batch_tick', _boom)
    with caplog.at_level(logging.WARNING, logger=M.__name__), pytest.raises(_Stop):
        M._mel_watcher()
    assert 'scheduler tick failed' in caplog.text and 'batch tick failed' in caplog.text
    assert ticks == [30, 30]


def test_daily_set_on_creates_todays_batch_and_launches_one_song(mel, monkeypatch):
    started = []
    monkeypatch.setattr(M, '_mel_start_song', lambda e: started.append(e['id']))
    monkeypatch.setattr(M, '_mel_propose_briefs', lambda n, avoid: [])
    monkeypatch.setattr(M, '_mel_free_ram_gb', lambda: 999.0)
    n = M._mel_per_day()
    out = M._mel_daily_set(True)
    assert (out['enabled'], out['done_date'], out['last_run_at']) == (True, TODAY, FIXED_ISO)
    b = M._mel_batch_load()
    assert (b['batch_date'], b['auto'], b['per_day'], len(b['songs'])) == (TODAY, True, n, n)
    assert {s['theme_source'] for s in b['songs']} == {'pool'}
    assert M._mel_history_load() == [s['theme'] for s in b['songs']]
    assert started == [0]
    assert ('melody_daily_enabled', {'date': TODAY}) in mel.audit
    assert ('melody_daily_batch_created', {'date': TODAY, 'count': n, 'llm_themes': 0}) in mel.audit
    themes = [s['theme'] for s in b['songs']]
    M._mel_daily_set(True)  # a second enable keeps the live batch
    assert [s['theme'] for s in M._mel_batch_load()['songs']] == themes
    assert M._mel_daily_set(False)['enabled'] is False
    assert ('melody_daily_disabled', {}) in mel.audit
    assert M._mel_pause(True)['paused'] is True
    assert M._mel_pause(False)['paused'] is False
    assert [e for e, _ in mel.audit[-2:]] == ['melody_daily_paused', 'melody_daily_resumed']


def test_stop_job_sets_the_stop_event_and_asks_for_a_halt(mel, monkeypatch):
    import zyg_workflows

    assert M._mel_stop_job('') is False
    assert M._mel_stop_job('not-a-job') is False
    halts = []
    pc = SimpleNamespace(request_halt=lambda why: halts.append(why))
    monkeypatch.setitem(sys.modules, 'zyg_workflows.pipeline_control', pc)
    monkeypatch.setattr(zyg_workflows, 'pipeline_control', pc, raising=False)
    ev = _threading.Event()
    mel.jobs['km-1'] = {'stop_event': ev}
    mel.jobs['km-2'] = {'stop_event': None}
    assert M._mel_stop_job('km-1') is True and M._mel_stop_job('km-2') is True
    assert ev.is_set() and halts == ['Aborted from the Approval Queue'] * 2
    monkeypatch.setattr(pc, 'request_halt', _boom)
    assert M._mel_stop_job('km-1') is False


def test_abort_fails_every_live_song_and_turns_the_toggle_off(mel, monkeypatch):
    monkeypatch.setattr(M, '_mel_stop_job', lambda pid: pid == 'km-1')
    live = song(id=0, status='in_production', pipeline_id='km-1')
    M._mel_batch_save(batch(live, song(id=1), song(id=2, status='done')))
    M._mel_daily_save({'enabled': True, 'paused': True})
    out = M._mel_abort()
    s = M._mel_batch_load()['songs']
    assert [e['status'] for e in s] == ['failed', 'failed', 'done']
    assert s[0]['error'] == s[1]['error'] == 'aborted by operator'
    assert s[0]['ended_at'] == s[1]['ended_at'] == FIXED_ISO
    assert (out['enabled'], out['paused']) == (False, False)
    assert ('melody_daily_aborted', {'stopped_pipeline': 'km-1'}) in mel.audit
    M._mel_batch_save({})  # nothing live → the abort is still safe
    assert M._mel_abort()['enabled'] is False


def test_next_run_label(mel, monkeypatch):
    monkeypatch.setattr(M, '_aq_get', lambda key, default: 9 if key == 'hour' else default)
    assert M._mel_next_run_label() == ''  # the toggle is off
    M._mel_daily_save({'enabled': True})
    M._mel_batch_save(batch(song(id=0, status='in_production')))
    assert M._mel_next_run_label() == 'after current batch'
    M._mel_batch_save(batch(song(id=0, status='done')))
    assert M._mel_next_run_label() == '2026-05-05 09:00'  # 09:00 has passed, so tomorrow
    monkeypatch.setattr(M, '_aq_get', lambda key, default: 23 if key == 'hour' else default)
    assert M._mel_next_run_label() == '2026-05-04 23:00'
    M._mel_daily_save({'enabled': True, 'done_date': TODAY})
    assert M._mel_next_run_label() == '2026-05-05 23:00'


def test_the_daily_mode_route_reads_and_writes_the_toggle(mel, client, monkeypatch):
    got = client.get('/api/melody/daily_mode')
    assert got.status_code == 200 and got.get_json()['enabled'] is False
    calls = []
    monkeypatch.setattr(M, '_mel_daily_set', lambda enabled: calls.append(enabled))
    body = client.post('/api/melody/daily_mode', json={'enabled': True}).get_json()
    assert (body['ok'], body['enabled'], body['state']['enabled']) == (True, True, False)
    assert client.post('/api/melody/daily_mode', data=b'not json').get_json()['enabled'] is False
    assert calls == [True, False]
    monkeypatch.setattr(M, '_mel_daily_set', _boom)
    bad = client.post('/api/melody/daily_mode', json={'enabled': True})
    assert bad.status_code == 500
    assert bad.get_json() == {'ok': False, 'error': 'batch create failed: offline'}


def test_the_daily_batch_route_reports_the_whole_card(mel, client):
    empty = client.get('/api/melody/daily_batch').get_json()
    assert (empty['batch'], empty['busy_with'], empty['next_run']) == (None, '', '')
    M._mel_batch_save(batch(song(id=0, status='in_production')))
    M._mel_daily_save({'enabled': True})
    mel.jobs['km-3'] = {'status': 'running'}
    full = client.get('/api/melody/daily_batch').get_json()
    assert full['batch']['batch_date'] == TODAY and full['daily']['enabled'] is True
    assert (full['next_run'], full['busy_with']) == ('after current batch', 'km-3')
