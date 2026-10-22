# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for ``zyg_workflows.run_ledger``.

Nothing here touches a server: ``run_ledger.pgdb`` is replaced by a namespace whose
``connect``/``rows``/``dsn`` are backed by a throwaway **sqlite** file under ``tmp_path``
(the module's SQL is portable apart from the ``%s`` placeholders, which the fake rewrites to
``?``). NVML and the ``nvidia-smi`` shell fallback are faked in full, and the sha256 sidecar
is redirected to ``tmp_path`` so no tracked file is ever written."""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import types

import pytest

from zyg_workflows import run_ledger

# ── a sqlite-backed stand-in for pgdb ────────────────────────────────────────

_SCHEMA = (
    'CREATE TABLE fallbacks (id INTEGER PRIMARY KEY AUTOINCREMENT, component TEXT, expected TEXT,'
    ' actual TEXT, detail TEXT, run_id TEXT, ts REAL, ts_iso TEXT)',
    'CREATE TABLE gates (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, gate TEXT, outcome TEXT,'
    ' score REAL, tag TEXT, ts REAL, ts_iso TEXT)',
    'CREATE TABLE stages (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stage TEXT, device TEXT,'
    ' model_id TEXT, weights_sha256 TEXT, dtype TEXT, fallback_taken TEXT, wall_s REAL,'
    ' vram_peak_mb REAL, ts REAL, ts_iso TEXT)',
)

FAKE_DSN = 'postgresql://test@/ledger_fake'


def _iso(ts):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))


class _Conn:
    """What ``pgdb.connect()`` yields: an object with psycopg's ``execute(sql, args)``."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, args=()):
        return self._raw.execute(sql.replace('%s', '?'), tuple(args))


class _Ledger:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as c:
            for stmt in _SCHEMA:
                c.execute(stmt)

    @contextlib.contextmanager
    def connect(self, dsn=None):
        raw = sqlite3.connect(self.path)
        try:
            yield _Conn(raw)
            raw.commit()
        finally:
            raw.close()

    def rows(self, sql, params=(), dsn=None):
        raw = sqlite3.connect(self.path)
        try:
            raw.row_factory = sqlite3.Row
            cur = raw.execute(sql.replace('%s', '?'), tuple(params))
            return [dict(r) for r in cur.fetchall()]
        finally:
            raw.close()

    def _ins(self, sql, params):  # direct seeding, for reads whose input needs a chosen timestamp
        with sqlite3.connect(self.path) as c:
            c.execute(sql, params)

    def gate(self, run_id, gate, outcome, ts, score=None, tag=''):
        self._ins(
            'INSERT INTO gates (run_id, gate, outcome, score, tag, ts, ts_iso) VALUES (?,?,?,?,?,?,?)',
            (run_id, gate, outcome, score, tag, ts, _iso(ts)),
        )

    def fallback(self, component, expected, actual, run_id, ts):
        self._ins(
            'INSERT INTO fallbacks (component, expected, actual, detail, run_id, ts, ts_iso) VALUES (?,?,?,?,?,?,?)',
            (component, expected, actual, '', run_id, ts, _iso(ts)),
        )

    def stage(self, run_id, stage, ts):
        self._ins('INSERT INTO stages (run_id, stage, ts, ts_iso) VALUES (?,?,?,?)', (run_id, stage, ts, _iso(ts)))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A fake ``run_ledger.pgdb`` over a sqlite file; the real pgdb is never touched."""
    lg = _Ledger(tmp_path / 'ledger.sqlite3')
    monkeypatch.setattr(
        run_ledger, 'pgdb', types.SimpleNamespace(connect=lg.connect, rows=lg.rows, dsn=lambda: FAKE_DSN)
    )
    monkeypatch.delenv('ZYG_RUN_ID', raising=False)
    return lg


@pytest.fixture(autouse=True)
def _sha_sidecar_in_tmp(tmp_path, monkeypatch):
    """Never let the sha256 cache land on the tracked sidecar path."""
    monkeypatch.setattr(run_ledger, '_SHA_CACHE_PATH', str(tmp_path / 'sha' / 'sha256_cache.json'))
    monkeypatch.setattr(run_ledger, '_sha_cache', None)
    yield
    run_ledger._sha_cache = None


# ── plumbing ─────────────────────────────────────────────────────────────────


def test_db_path_is_the_pgdb_dsn_and_now_pairs_epoch_with_iso(ledger):
    assert run_ledger.db_path() == FAKE_DSN
    t, iso = run_ledger._now()
    assert isinstance(t, float) and iso == time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


@pytest.mark.parametrize(
    ('arg', 'env', 'expected'),
    [
        ('explicit', 'from-env', 'explicit'),
        (None, 'from-env', 'from-env'),
        (None, None, 'adhoc'),
        (None, '', 'adhoc'),
        (17, 'from-env', '17'),
    ],
)
def test_current_run_id_resolution_order(monkeypatch, arg, env, expected):
    if env is None:
        monkeypatch.delenv('ZYG_RUN_ID', raising=False)
    else:
        monkeypatch.setenv('ZYG_RUN_ID', env)
    assert run_ledger.current_run_id(arg) == expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(None, None), (True, None), (False, None), (3, 3.0), ('4.5', 4.5), ('nope', None), ([], None), (-0.25, -0.25)],
)
def test_num_coerces_or_gives_up(value, expected):
    assert run_ledger._num(value) == expected


@pytest.mark.parametrize('with_log_fn', [True, False])
def test_insert_failure_is_swallowed(monkeypatch, with_log_fn):
    def boom(*_a, **_k):
        raise RuntimeError('server gone')

    monkeypatch.setattr(run_ledger, 'pgdb', types.SimpleNamespace(connect=boom, dsn=lambda: FAKE_DSN))
    seen = []
    log_fn = seen.append if with_log_fn else None
    assert run_ledger._insert('INSERT INTO gates VALUES (%s)', ('x',), log_fn) is False
    assert ('server gone' in seen[0]) if with_log_fn else seen == []


# ── recording API, read back through the reads ───────────────────────────────


def test_record_fallback_round_trips_truncates_and_honours_the_env_run_id(ledger, monkeypatch):
    assert run_ledger.record_fallback('loudnorm', 'linear', 'dynamic', detail='d' * 2000, run_id='r1') is True
    (row,) = run_ledger.fallbacks_for_run('r1')
    assert (row['component'], row['expected'], row['actual'], row['run_id']) == ('loudnorm', 'linear', 'dynamic', 'r1')
    assert len(row['detail']) == 1000 and row['ts_iso']

    monkeypatch.setenv('ZYG_RUN_ID', 'env-run')
    assert run_ledger.record_fallback('whisper', 'cuda:large-v3', 'cpu:base') is True
    assert [r['run_id'] for r in run_ledger.fallbacks_for_run()] == ['env-run']


@pytest.mark.parametrize(('outcome', 'stored'), [(True, 'pass'), (False, 'fail'), ('PASS', 'pass'), ('skip', 'skip')])
def test_record_gate_normalizes_the_outcome(ledger, outcome, stored):
    assert run_ledger.record_gate('r2', 'motion:abel', outcome, score='0.5', tag='t') is True
    rows = run_ledger.gates_for_run('r2')
    assert rows[-1]['outcome'] == stored
    assert rows[-1]['score'] == 0.5


def test_record_gate_keeps_a_bad_score_out_of_the_table(ledger):
    assert run_ledger.record_gate('r3', 'g', 'fail', score='not-a-number') is True
    assert run_ledger.gates_for_run('r3')[0]['score'] is None


def test_record_stage_records_full_provenance(ledger):
    provenance = {
        'device': 'cuda:0',
        'model_id': 'wan2.1-vace-14b',
        'weights_sha256': 'a' * 80,  # over the column's 64 chars, so the truncation shows
        'dtype': 'fp16',
        'fallback_taken': 'cpu-path',
        'wall_s': '5321.0',
        'vram_peak_mb': 20480,
    }
    assert run_ledger.record_stage('wan_render', run_id='r4', **provenance) is True
    (row,) = run_ledger.stages_for_run('r4')
    assert (row['stage'], row['device']) == ('wan_render', 'cuda:0')
    assert len(row['weights_sha256']) == 64
    assert (row['wall_s'], row['vram_peak_mb']) == (5321.0, 20480.0)


def test_record_stage_leaves_every_optional_column_null(ledger):
    assert run_ledger.record_stage('bare', run_id='r5') is True
    (row,) = run_ledger.stages_for_run('r5')
    assert [row[k] for k in ('device', 'model_id', 'weights_sha256', 'dtype', 'fallback_taken')] == [None] * 5


def test_rows_turns_a_broken_ledger_into_an_empty_list(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('down')

    monkeypatch.setattr(run_ledger, 'pgdb', types.SimpleNamespace(rows=boom, dsn=lambda: FAKE_DSN))
    assert run_ledger._rows('SELECT 1') == []
    assert run_ledger.gates_for_run('x') == run_ledger.stages_for_run('x') == run_ledger.fallbacks_for_run('x') == []


# ── weight attestation ───────────────────────────────────────────────────────


def test_sha256_file_hashes_then_serves_from_the_cache(tmp_path):
    blob = tmp_path / 'ckpt.safetensors'
    blob.write_bytes(b'z' * (5 * 1024 * 1024))  # > one 4 MiB read, so the chunk loop spins twice
    digest = run_ledger.sha256_file(blob)
    assert digest == hashlib.sha256(b'z' * (5 * 1024 * 1024)).hexdigest()

    with open(run_ledger._SHA_CACHE_PATH, encoding='utf-8') as f:
        entry = json.load(f)[os.path.abspath(str(blob))]
    assert entry['sha256'] == digest and entry['size'] == 5 * 1024 * 1024

    # a second call must not re-hash: poison the cached digest and watch it come back
    run_ledger._sha_cache[os.path.abspath(str(blob))]['sha256'] = 'cached-not-recomputed'
    assert run_ledger.sha256_file(blob) == 'cached-not-recomputed'


def test_sha256_file_reloads_a_cache_written_by_an_earlier_process(tmp_path):
    blob = tmp_path / 'w.bin'
    blob.write_bytes(b'hello')
    st = os.stat(blob)
    os.makedirs(os.path.dirname(run_ledger._SHA_CACHE_PATH), exist_ok=True)
    with open(run_ledger._SHA_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump({os.path.abspath(str(blob)): {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sha256': 'pre'}}, f)
    assert run_ledger.sha256_file(blob) == 'pre'


def test_sha256_file_rehashes_when_the_file_was_clobbered_in_place(tmp_path):
    blob = tmp_path / 'w.bin'
    blob.write_bytes(b'first')
    first = run_ledger.sha256_file(blob)
    time.sleep(0.01)
    blob.write_bytes(b'second-and-longer')
    second = run_ledger.sha256_file(blob)
    assert second != first
    assert second == hashlib.sha256(b'second-and-longer').hexdigest()


def test_sha256_file_on_a_missing_path_is_none_and_logged(tmp_path):
    seen = []
    assert run_ledger.sha256_file(tmp_path / 'nope.bin', log_fn=seen.append) is None
    assert 'sha256_file' in seen[0]
    assert run_ledger.sha256_file(tmp_path / 'nope.bin') is None


@pytest.mark.parametrize('payload', ['[1, 2, 3]', 'not json at all', '"a string"'])
def test_load_sha_cache_rejects_anything_that_is_not_a_dict(payload):
    os.makedirs(os.path.dirname(run_ledger._SHA_CACHE_PATH), exist_ok=True)
    with open(run_ledger._SHA_CACHE_PATH, 'w', encoding='utf-8') as f:
        f.write(payload)
    run_ledger._sha_cache = None
    assert run_ledger._load_sha_cache() == {}


def test_save_sha_cache_survives_an_unwritable_sidecar(tmp_path, monkeypatch):
    wall = tmp_path / 'wall'
    wall.write_text('not a directory')
    monkeypatch.setattr(run_ledger, '_SHA_CACHE_PATH', str(wall / 'sha256_cache.json'))
    run_ledger._sha_cache = {'k': {'sha256': 'x'}}
    run_ledger._save_sha_cache()  # must not raise
    blob = tmp_path / 'b.bin'
    blob.write_bytes(b'q')
    assert run_ledger.sha256_file(blob) == hashlib.sha256(b'q').hexdigest()


# ── NVML and the nvidia-smi fallback ─────────────────────────────────────────


def _fake_pynvml(**over):
    mem = types.SimpleNamespace(total=24 * 1048576, used=3 * 1048576, free=21 * 1048576)
    mod = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlShutdown=lambda: None,
        nvmlDeviceGetCount=lambda: 2,
        nvmlDeviceGetHandleByIndex=lambda i: f'h{i}',
        nvmlDeviceGetMemoryInfo=lambda h: mem,
        nvmlSystemGetDriverVersion=lambda: b'570.86.10',
        nvmlDeviceGetName=lambda h: 'NVIDIA RTX 5090',
    )
    for k, v in over.items():
        setattr(mod, k, v)
    return mod


@pytest.fixture
def nvml_state(monkeypatch):
    monkeypatch.setattr(run_ledger, '_nvml_state', {'mod': None, 'init': False, 'dead': False})
    monkeypatch.setattr(atexit, 'register', lambda fn, *a, **k: fn)
    return run_ledger._nvml_state


def test_nvml_short_circuits_once_it_is_dead(nvml_state):
    nvml_state['dead'] = True
    assert run_ledger._nvml() is None


def _raise(*_a):
    raise RuntimeError('no driver')


# `None` in sys.modules makes `import pynvml` raise ImportError; the other variant imports
# and then fails in nvmlInit.
@pytest.mark.parametrize('fake', [None, 'init-raises'])
def test_nvml_marks_itself_dead_when_pynvml_is_unusable(nvml_state, monkeypatch, fake):
    monkeypatch.setitem(sys.modules, 'pynvml', None if fake is None else _fake_pynvml(nvmlInit=_raise))
    assert run_ledger._nvml() is None
    assert nvml_state['dead'] is True


def test_nvml_initialises_once_and_is_reused(nvml_state, monkeypatch):
    calls = []
    mod = _fake_pynvml(nvmlInit=lambda: calls.append(1))
    monkeypatch.setitem(sys.modules, 'pynvml', mod)
    assert run_ledger._nvml() is mod
    assert run_ledger._nvml() is mod
    assert calls == [1] and nvml_state['init'] is True


def test_nvml_shutdown_resets_init_and_tolerates_a_raise(nvml_state):
    run_ledger._nvml_shutdown()  # never initialised: a no-op
    assert nvml_state['init'] is False

    nvml_state.update(mod=_fake_pynvml(), init=True)
    run_ledger._nvml_shutdown()
    assert nvml_state['init'] is False

    nvml_state.update(mod=_fake_pynvml(nvmlShutdown=_raise), init=True)
    run_ledger._nvml_shutdown()  # must not raise


def test_gpu_info_from_nvml(nvml_state, monkeypatch):
    """Also covers ``_s`` on both its branches: the driver is bytes, the name is a str."""
    monkeypatch.setitem(sys.modules, 'pynvml', _fake_pynvml())
    info = run_ledger.gpu_info()
    assert (info['source'], info['driver'], info['name'], info['count']) == ('nvml', '570.86.10', 'NVIDIA RTX 5090', 2)
    assert (info['vram_total_mb'], info['vram_used_mb'], info['vram_free_mb']) == (24, 3, 21)
    assert run_ledger.vram_used_mb() == 3


def _smi(stdout):
    def run(cmd, **_kw):
        assert cmd[0].endswith('nvidia-smi')
        return types.SimpleNamespace(stdout=stdout, stderr='', returncode=0)

    return run


def test_gpu_info_falls_back_to_nvidia_smi_when_nvml_query_raises(nvml_state, monkeypatch):
    monkeypatch.setitem(sys.modules, 'pynvml', _fake_pynvml(nvmlDeviceGetCount=_raise))
    monkeypatch.setattr(run_ledger, 'exe', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(subprocess, 'run', _smi('570.86.10, NVIDIA RTX 5090, 32607, 4096\n'))
    info = run_ledger.gpu_info()
    assert info['source'] == 'nvidia-smi'
    assert (info['driver'], info['name'], info['count']) == ('570.86.10', 'NVIDIA RTX 5090', 1)
    assert (info['vram_total_mb'], info['vram_used_mb'], info['vram_free_mb']) == (32607, 4096, 28511)
    assert nvml_state['dead'] is True


@pytest.mark.parametrize('reason', ['short-line', 'no-binary'])
def test_gpu_info_gives_up_without_nvml_and_without_a_usable_smi(nvml_state, monkeypatch, reason):
    nvml_state['dead'] = True
    if reason == 'short-line':
        monkeypatch.setattr(run_ledger, 'exe', lambda name: '/usr/bin/' + name)
        monkeypatch.setattr(subprocess, 'run', _smi('no gpu here\n'))
    else:
        monkeypatch.setattr(run_ledger, 'exe', _raise)  # bin.exe raises MissingExecutable
    assert run_ledger.gpu_info() == {'source': None}
    assert run_ledger.vram_used_mb() is None


# ── two-run reads ────────────────────────────────────────────────────────────


def test_known_runs_spans_all_three_tables(ledger):
    ledger.stage('run-a', 'render', ts=1000.0)
    ledger.gate('run-a', 'motion', 'pass', ts=1060.5)
    ledger.fallback('loudnorm', 'linear', 'dynamic', 'run-a', ts=1030.0)
    ledger.gate('run-b', 'motion', 'fail', ts=2000.0)
    rows = run_ledger.known_runs()
    assert [r['run_id'] for r in rows] == ['run-b', 'run-a']
    assert (rows[1]['n'], rows[1]['wall_s'], rows[0]['wall_s']) == (3, 60.5, 0.0)
    assert [r['run_id'] for r in run_ledger.known_runs(limit=0)] == ['run-b']  # the limit floor


def test_gate_scores_for_run_keeps_the_last_outcome(ledger):
    ledger.gate('r', 'motion', 'fail', ts=10.0, score=0.07, tag='frozen-motion')
    ledger.gate('r', 'motion', 'pass', ts=20.0, score=0.81, tag='')
    ledger.gate('r', 'hands', 'pass', ts=30.0)
    scores = run_ledger.gate_scores_for_run('r')
    assert (scores['motion']['outcome'], scores['motion']['score'], scores['motion']['tag']) == ('pass', 0.81, '')
    assert scores['motion']['ts_iso'] == _iso(20.0)
    assert scores['hands']['score'] is None


def test_compare_gates_reports_flips_regressions_and_one_sided_gates(ledger):
    both = [
        # gate, outcome+score in run A, outcome+score in run B
        ('motion', 'pass', 0.9, 'fail', 0.2),  # a regression, with a delta
        ('hands', 'pass', 0.5, 'pass', 0.5),  # unchanged -> absent from 'changed'
        ('loudness', 'pass', None, 'pass', 0.4),  # same outcome, score appeared -> delta None
    ]
    for gate, a_out, a_score, b_out, b_score in both:
        ledger.gate('A', gate, a_out, ts=10.0, score=a_score)
        ledger.gate('B', gate, b_out, ts=20.0, score=b_score)
    ledger.gate('A', 'only_a', 'fail', ts=10.0, score=0.1)
    ledger.gate('B', 'only_b', 'pass', ts=20.0, score=0.3)

    out = run_ledger.compare_gates('A', 'B')
    assert (out['a'], out['b']) == ('A', 'B')
    assert [c['gate'] for c in out['changed']] == ['loudness', 'motion']
    assert out['a_only'] == ['only_a'] and out['b_only'] == ['only_b']
    (reg,) = out['regressions']
    assert (reg['gate'], reg['flip'], reg['delta']) == ('motion', 'pass->fail', -0.7)
    assert (reg['a_outcome'], reg['b_outcome'], reg['a_score'], reg['b_score']) == ('pass', 'fail', 0.9, 0.2)
    loud = next(c for c in out['changed'] if c['gate'] == 'loudness')
    assert loud['flip'] == '' and loud['delta'] is None


def test_compare_gates_is_fail_safe(monkeypatch):
    def boom(_run_id=None):
        raise RuntimeError('ledger unreadable')

    monkeypatch.setattr(run_ledger, 'gate_scores_for_run', boom)
    out = run_ledger.compare_gates('A', 'B')
    assert (out['a'], out['b'], out['error']) == ('A', 'B', 'ledger unreadable')
    assert out['changed'] == out['regressions'] == out['a_only'] == out['b_only'] == []


# ── trends ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        ((4, 4, 5, 5), None),  # n1 underpowered
        ((5, 5, 4, 4), None),  # n2 underpowered
        ((8, 8, 8, 8), None),  # se == 0
        ((0, 8, 8, 8), -4.0),
        ((8, 8, 0, 8), 4.0),
    ],
)
def test_two_prop_z(args, expected):
    z = run_ledger._two_prop_z(*args)
    assert z is None if expected is None else pytest.approx(expected) == z


@pytest.fixture
def drifting(ledger):
    """Prior half 8/8 pass for ``slide``, recent half 0/8 — the ghost-face shape."""
    now = time.time()
    prior, recent = now - 10 * 86400.0, now - 2 * 86400.0
    for i in range(8):
        ledger.gate('p%d' % i, 'slide', 'pass', ts=prior + i, score=0.9)
        ledger.gate('r%d' % i, 'slide', 'fail', ts=recent + i, score=0.1, tag='frozen-motion')
        ledger.gate('p%d' % i, 'climb', 'fail', ts=prior + i)
        ledger.gate('r%d' % i, 'climb', 'pass', ts=recent + i)
        ledger.gate('p%d' % i, 'steady', 'pass', ts=prior + i)
        ledger.gate('r%d' % i, 'steady', 'pass', ts=recent + i)
    ledger.gate('r0', 'steady', 'skipped', ts=recent)  # neither pass nor fail -> ignored
    ledger.gate('r0', 'thin', 'fail', ts=recent, tag='')  # underpowered -> z None
    ledger.fallback('loudnorm', 'linear', 'dynamic', 'r0', ts=recent)
    ledger.fallback('loudnorm', 'linear', 'dynamic', 'r1', ts=recent + 1)
    ledger.fallback('whisper', 'cuda:large-v3', 'cpu:base', 'r0', ts=recent)
    ledger.stage('stage-only-run', 'render', ts=recent)
    return ledger


def test_trends_flags_a_drop_a_rise_and_the_silent_degrades(drifting):
    t = run_ledger.trends(days=14)
    assert t['ok'] is True and t['days'] == 14 and t['db'] == FAKE_DSN
    assert t['runs'] == 17  # 8 prior + 8 recent gate runs + the stages-only run
    assert [g['gate'] for g in t['gates']] == ['climb', 'slide', 'steady', 'thin']
    by_gate = {g['gate']: g for g in t['gates']}

    slide = by_gate['slide']
    assert (slide['n'], slide['passed'], slide['pass_rate']) == (16, 8, 0.5)
    assert (slide['prior_n'], slide['prior_pass_rate']) == (8, 1.0)
    assert (slide['recent_n'], slide['recent_pass_rate']) == (8, 0.0)
    assert (slide['z'], slide['shift'], slide['mean_score']) == (-4.0, 'drop', 0.5)
    assert [d['n'] for d in slide['daily']] == [8, 8] and slide['last_seen']

    assert (by_gate['climb']['shift'], by_gate['climb']['z']) == ('rise', 4.0)
    assert by_gate['steady']['shift'] is None and by_gate['steady']['z'] is None
    assert by_gate['thin']['z'] is None and by_gate['thin']['mean_score'] is None

    assert any("gate 'slide'" in a and 'REGRESSION' in a for a in t['alerts'])
    assert any("gate 'climb'" in a and 'improved' in a for a in t['alerts'])
    assert t['tags'] == [{'tag': 'frozen-motion', 'count': 8, 'runs': 8}]
    assert [f['component'] for f in t['fallbacks']] == ['loudnorm', 'whisper']
    assert (t['fallbacks'][0]['count'], t['fallbacks'][0]['runs']) == (2, 2)
    assert sum("silent degrade 'loudnorm'" in a for a in t['alerts']) == 1


def test_trends_and_format_on_an_empty_window(ledger):
    t = run_ledger.trends(days=0)  # the window floor: 0 -> 1 day
    assert (t['ok'], t['days'], t['runs']) == (True, 1, 0)
    assert t['gates'] == [] and t['tags'] == [] and t['fallbacks'] == [] and t['alerts'] == []
    text = run_ledger.format_trends(days=14)
    assert '(no gate rows in window)' in text and text.count('(none)') == 3


def test_trends_is_fail_safe(monkeypatch, ledger):
    def boom(*_a, **_k):
        raise RuntimeError('rows exploded')

    monkeypatch.setattr(run_ledger, '_rows', boom)
    assert run_ledger.trends(days=3) == {'ok': False, 'error': 'rows exploded', 'days': 3, 'db': FAKE_DSN}


def test_format_trends_renders_the_full_table(drifting):
    text = run_ledger.format_trends(days=14)
    assert 'run ledger — last 14d   db=' + FAKE_DSN in text
    assert 'GATES' in text and 'RECURRING FAILURE TAGS' in text
    assert 'SILENT DEGRADES (fallbacks)' in text and 'ALERTS' in text
    assert 'slide' in text and 'drop' in text and 'rise' in text
    assert '100.0%' in text and '  0.0%' in text and '   -  ' in text  # _pct, both branches
    assert '-4.00' in text and '+4.00' in text
    assert 'frozen-motion' in text and 'loudnorm' in text and '! ' in text


def test_format_trends_reports_a_failure_instead_of_a_table():
    assert run_ledger.format_trends({'ok': False, 'error': 'db down'}) == 'run_ledger trends FAILED: db down'


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_main_trends_prints_the_table(drifting, capsys):
    assert run_ledger._main(['--trends', '--days', '14']) == 0
    assert 'GATES' in capsys.readouterr().out


@pytest.mark.parametrize('argv', [['--trends', '--days', 'banana'], ['--trends', '--days']])
def test_main_days_falls_back_on_an_unusable_value(ledger, capsys, argv):
    assert run_ledger._main(argv) == 0
    assert 'last 14d' in capsys.readouterr().out


def test_main_read_flags_all_print_json(ledger, capsys):
    ledger.stage('A', 'render', ts=5.0)
    ledger.gate('A', 'motion', 'pass', ts=6.0, score=0.9)
    ledger.fallback('loudnorm', 'linear', 'dynamic', 'A', ts=7.0)
    ledger.gate('B', 'motion', 'fail', ts=8.0, score=0.2)

    assert run_ledger._main(['--run', 'A']) == 0
    out = json.loads(capsys.readouterr().out)
    assert [len(out[k]) for k in ('stages', 'gates', 'degradations')] == [1, 1, 1]

    assert run_ledger._main(['--runs']) == 0
    assert [r['run_id'] for r in json.loads(capsys.readouterr().out)] == ['B', 'A']

    assert run_ledger._main(['--compare', 'A', 'B']) == 0
    assert json.loads(capsys.readouterr().out)['regressions'][0]['gate'] == 'motion'

    assert run_ledger._main(['--json', '--days', '3']) == 0
    assert json.loads(capsys.readouterr().out)['days'] == 3


def test_main_gpu_prints_gpu_info(monkeypatch, capsys):
    monkeypatch.setattr(run_ledger, 'gpu_info', lambda: {'source': 'nvml', 'count': 1})
    assert run_ledger._main(['--gpu']) == 0
    assert json.loads(capsys.readouterr().out) == {'source': 'nvml', 'count': 1}


def test_main_usage_errors(capsys):
    assert run_ledger._main(['--compare', 'A']) == 2
    assert 'usage: python3 run_ledger.py --compare' in capsys.readouterr().out
    assert run_ledger._main([]) == 1
    out = capsys.readouterr().out
    assert 'run_ledger.py' in out and '--trends' in out and '--compare' in out
