# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for :mod:`zyg_dashboard.agent_activity.sampler`.

Every probe (psutil, NVML, nvidia-smi, /proc, the ledger files) is faked, so
the suite runs offline on a box with no GPU and writes only under ``tmp_path``.
``start()`` is never called: it launches the real sampler thread.
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import time
from collections import deque
from types import SimpleNamespace

import pytest

from zyg_dashboard.agent_activity import sampler as MOD


# ── Fakes ───────────────────────────────────────────────────────────────────
# The three psutil exceptions the sampler catches by name.
_NoSuch, _Denied, _Zombie = (type(n, (Exception,), {}) for n in ('NoSuchProcess', 'AccessDenied', 'ZombieProcess'))


class _P:
    """A psutil.Process stand-in with exactly the surface the sampler uses."""

    def __init__(self, pid, cmdline=('python', 'x.py'), create_time=1000.0, **kw):
        self.pid = pid
        self._ppid = kw.get('ppid', 1)
        self._cpu = kw.get('cpu', 0.0)
        self._rss = kw.get('rss_mb', 0.0) * 1048576.0
        self._info_raises = kw.get('info_raises')
        self._cpu_raises = kw.get('cpu_raises', False)
        self._cpu_calls = 0
        self._info = {
            'pid': pid,
            'name': kw.get('name', 'python'),
            'cmdline': list(cmdline),
            'create_time': create_time,
            'uids': SimpleNamespace(real=kw.get('uid', MOD._UID)),
        }

    @property
    def info(self):
        if self._info_raises is not None:
            raise self._info_raises
        return self._info

    def cpu_percent(self, interval=None):
        # The first call only primes psutil's delta; raising from the second
        # exercises the sampler's "keep the previous values" path.
        self._cpu_calls += 1
        if self._cpu_raises and self._cpu_calls > 1:
            raise RuntimeError('cpu_percent exploded')
        return self._cpu

    def memory_info(self):
        return SimpleNamespace(rss=self._rss)

    def ppid(self):
        return self._ppid


def _fake_psutil(procs=(), by_pid=None):
    by_pid = dict(by_pid or {})
    return SimpleNamespace(
        process_iter=lambda attrs=None: list(procs),
        Process=lambda pid: by_pid[pid],
        NoSuchProcess=_NoSuch,
        AccessDenied=_Denied,
        ZombieProcess=_Zombie,
    )


def _span(sid='sess0001abcd', device='gpu', start_ts=1000.0, last_busy=1100.0, **kw):
    return {
        'sid': sid, 'device': device, 'start_ts': start_ts, 'last_busy': last_busy,
        'name': 'nova', 'project': 'zyg', 'cwd': '/c', 'entrypoint': 'cli', 'session_kind': 'agent',
        'peak_vram': 300.0, 'peak_cpu': 150.0, 'peak_ram': 2048.0,
        'kinds': {'render'}, 'cmds': ['ffmpeg -i a.mp4'], 'samples': 3, **kw,
    }  # fmt: skip


def _session(sid, **kw):
    return {
        'id': sid, 'short': sid[:8], 'name': sid[:8], 'project': 'zyg', 'cwd': '/c',
        'entrypoint': 'cli', 'kind': 'agent', 'events': deque(maxlen=MOD._SESS_EVENT_CAP),
        'active': False, 'alive': True, **kw,
    }  # fmt: skip


def _kinds():
    return [e['kind'] for e in MOD._events]


def _rows(tmp_path):
    text = (tmp_path / 'led' / 'ledger.jsonl').read_text(encoding='utf-8')
    return [json.loads(ln) for ln in text.splitlines()]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh module state + every write redirected under tmp_path."""
    monkeypatch.setattr(MOD, '_LEDGER_FILE', str(tmp_path / 'led' / 'ledger.jsonl'))
    monkeypatch.setattr(MOD, '_OPEN_SPANS_FILE', str(tmp_path / 'led' / 'open.json'))
    for name in ('_tracked', '_ignored', '_sessions', '_spans', '_gpu_pids'):
        monkeypatch.setattr(MOD, name, {})
    monkeypatch.setattr(MOD, '_events', deque(maxlen=MOD._EVENT_CAP))
    monkeypatch.setattr(MOD, '_gpu', dict(MOD._gpu))
    monkeypatch.setattr(MOD, '_NVML', {'mod': None, 'handles': None, 'tried': False})
    monkeypatch.setattr(MOD, '_seq', 0)
    monkeypatch.setattr(MOD, '_open_dirty', False)
    monkeypatch.setattr(MOD, '_open_flushed', 0.0)
    monkeypatch.setattr(MOD, '_sampler_error', '')


# ── Formatting helpers ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('pct', 'want'),
    [(None, 'idle'), (0.0, 'idle'), (4.0, 'idle'), (50.0, '0.50 cores'),
     (100.0, '1.0 core'), (104.0, '1.0 core'), (250.0, '2.5 cores')],
)  # fmt: skip
def test_fmt_cores_speaks_in_cores(pct, want):
    assert MOD._fmt_cores(pct) == want


@pytest.mark.parametrize(('sec', 'want'), [(-5, '0s'), (0, '0s'), (9, '9s'), (75, '1m 15s'), (3700, '1h 01m')])
def test_fmt_dur_rolls_up_to_hours(sec, want):
    assert MOD._fmt_dur(sec) == want


@pytest.mark.parametrize(
    ('cmd', 'want'),
    [('python train.py', 'train'), ('uv run pytest tests/x.py', 'test'),
     ('python comfyui/main.py', 'comfy'), ('ffmpeg -i a.mp4 b.mp4', 'render'),
     ('python pipeline_kids_music.py', 'pipeline'), ('ollama run qwen', 'model'),
     ('/usr/bin/python3 foo', 'python'), ('cat /etc/hosts', 'proc')],
)  # fmt: skip
def test_kind_of_classifies_the_command(cmd, want):
    assert MOD._kind_of(cmd) == want


def test_clean_cmd_unwraps_eval_and_redacts_credentials():
    assert MOD._clean_cmd(["bash -c eval 'ffmpeg   -i a.mp4' && pwd -P"]) == 'ffmpeg -i a.mp4'
    assert MOD._clean_cmd(['sh', '-c', 'eval "ls   -l"']) == 'ls -l'
    assert MOD._clean_cmd(['curl', '-H', 'authorization: sk-secret']) == 'curl -H authorization: ***'
    assert len(MOD._clean_cmd(['x', 'y' * 600])) == 400
    assert MOD._clean_cmd([]) == '' and MOD._clean_cmd(None) == ''


# ── /proc readers ───────────────────────────────────────────────────────────
def test_proc_readers_handle_a_live_pid_and_a_dead_one(monkeypatch, tmp_path):
    assert MOD._proc_start_ticks(os.getpid()).isdigit()
    assert MOD._proc_start_ticks(-1) is None
    target = tmp_path / 'environ'
    target.write_bytes(
        b'CLAUDE_CODE_SESSION_ID=abc\x00PATH=/x\x00CLAUDE_PID=99\x00'
        b'CLAUDE_SOMETHING_ELSE=z\x00CLAUDE_CODE_ENTRYPOINT=cli\x00'
    )
    real_open = builtins.open
    monkeypatch.setattr(
        builtins, 'open', lambda p, *a, **k: real_open(target if p == '/proc/4242/environ' else p, *a, **k)
    )
    assert MOD._read_env(4242) == {
        'CLAUDE_CODE_SESSION_ID': 'abc', 'CLAUDE_PID': '99', 'CLAUDE_CODE_ENTRYPOINT': 'cli',
    }  # fmt: skip
    assert MOD._read_env(-1) == {}  # unreadable pid


# ── Session registry ────────────────────────────────────────────────────────
def test_live_sessions_keeps_only_running_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(MOD, '_SESS_DIR', str(tmp_path / 'nope'))
    assert MOD._live_sessions() == {}  # no directory at all

    d = tmp_path / 'sessions'
    d.mkdir()
    pid = os.getpid()
    (d / 'notjson.txt').write_text('ignored', encoding='utf-8')
    (d / 'broken.json').write_text('{not json', encoding='utf-8')
    alive = {'pid': pid, 'sessionId': 'live0000aaaa', 'procStart': MOD._proc_start_ticks(pid), 'name': 'nova',
             'cwd': '/home/zyg/repos/zygomatic/', 'kind': 'agent', 'entrypoint': 'cli',
             'startedAt': 1_700_000_000_000}  # fmt: skip
    entries = {
        'nopid.json': {'sessionId': 'x'},  # no pid
        'dead.json': {'pid': pid, 'sessionId': 'deadone0', 'procStart': '999999999'},  # recycled
        'gone.json': {'pid': 9_999_999, 'sessionId': 'gone0000'},  # no such process
        'live.json': alive,
        'nostart.json': {'pid': pid, 'sessionId': 'nostart00000', 'cwd': ''},
    }
    for fn, payload in entries.items():
        (d / fn).write_text(json.dumps(payload), encoding='utf-8')
    monkeypatch.setattr(MOD, '_SESS_DIR', str(d))

    out = MOD._live_sessions()

    assert sorted(out) == ['live0000aaaa', 'nostart00000']
    assert out['live0000aaaa']['project'] == 'zygomatic'
    assert out['live0000aaaa']['started']
    assert out['nostart00000']['name'] == 'nostart0'
    assert out['nostart00000']['started'] == ''


# ── NVML / nvidia-smi ───────────────────────────────────────────────────────
def test_nvml_initialises_a_present_pynvml_exactly_once(monkeypatch):
    fake = SimpleNamespace(
        nvmlInit=lambda: None, nvmlDeviceGetCount=lambda: 2, nvmlDeviceGetHandleByIndex=lambda i: f'h{i}'
    )
    monkeypatch.setitem(sys.modules, 'pynvml', fake)
    assert MOD._nvml() is fake
    assert MOD._NVML['handles'] == ['h0', 'h1']
    MOD._NVML['mod'] = 'cached'
    assert MOD._nvml() == 'cached'  # already tried: never imported again


def test_nvml_failure_leaves_no_module(monkeypatch):
    def boom():
        raise RuntimeError('no driver')

    monkeypatch.setitem(sys.modules, 'pynvml', SimpleNamespace(nvmlInit=boom))
    assert MOD._nvml() is None


def _patch_smi(monkeypatch, run):
    monkeypatch.setattr(MOD, '_nvml', lambda: None)
    monkeypatch.setattr(MOD, 'shutil', SimpleNamespace(which=lambda n: '/usr/bin/nvidia-smi'))
    monkeypatch.setattr(MOD, 'subprocess', SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError))


def test_nvidia_refresh_respects_its_own_cache_window(monkeypatch):
    monkeypatch.setattr(MOD, '_NVIDIA_S', 600.0)
    MOD._gpu['at'] = time.time()
    monkeypatch.setattr(MOD, '_nvml', lambda: pytest.fail('must not probe'))
    MOD._nvidia_refresh()
    assert MOD._gpu['ok'] is False


def test_nvidia_refresh_sums_every_handle_through_nvml(monkeypatch):
    def util(h):
        if h == 'bad':
            raise RuntimeError('utilisation unsupported')
        return SimpleNamespace(gpu=42)

    nv = SimpleNamespace(
        nvmlDeviceGetMemoryInfo=lambda h: SimpleNamespace(total=8 * 1048576, used=2 * 1048576),
        nvmlDeviceGetUtilizationRates=util,
        nvmlDeviceGetComputeRunningProcesses=lambda h: [
            SimpleNamespace(pid=11, usedGpuMemory=1048576),
            SimpleNamespace(pid=12, usedGpuMemory=0),
        ],
    )
    MOD._NVML['handles'] = ['good', 'bad']
    monkeypatch.setattr(MOD, '_nvml', lambda: nv)

    MOD._nvidia_refresh()

    assert (MOD._gpu['total_mb'], MOD._gpu['used_mb'], MOD._gpu['util_pct']) == (16.0, 4.0, 42.0)
    assert MOD._gpu_pids == {11: 2.0}
    assert MOD._gpu['ok'] is True


def test_nvidia_refresh_falls_back_and_gives_up_without_the_binary(monkeypatch):
    def boom(h):
        raise RuntimeError('nvml died mid-read')

    MOD._NVML['handles'] = ['h0']
    monkeypatch.setattr(MOD, '_nvml', lambda: SimpleNamespace(nvmlDeviceGetMemoryInfo=boom))
    monkeypatch.setattr(MOD, 'shutil', SimpleNamespace(which=lambda n: None))

    MOD._nvidia_refresh()

    assert MOD._gpu['ok'] is False
    assert MOD._NVML['mod'] is None


def test_nvidia_refresh_parses_nvidia_smi_csv(monkeypatch):
    outs = ['8192, 2048, 37\n', '11, 512\n12, N/A\nbadline\n', '[N/A], 2048, 37\n', '']

    def run(cmd, **kw):
        if not outs:
            raise OSError('nvidia-smi is not executable here')
        return SimpleNamespace(stdout=outs.pop(0))

    _patch_smi(monkeypatch, run)

    MOD._nvidia_refresh()
    assert (MOD._gpu['total_mb'], MOD._gpu['used_mb'], MOD._gpu['util_pct']) == (8192.0, 2048.0, 37.0)
    assert MOD._gpu_pids == {11: 512.0}

    MOD._nvidia_refresh()  # unparseable totals, empty compute-apps list
    assert (MOD._gpu['total_mb'], MOD._gpu_pids, MOD._gpu['ok']) == (0.0, {}, True)

    MOD._nvidia_refresh()  # the probe itself blows up
    assert MOD._gpu['ok'] is False


# ── Process classification ──────────────────────────────────────────────────
def test_is_detached_walks_up_to_the_session_process(monkeypatch):
    loop = _P(77, ppid=77)
    monkeypatch.setattr(MOD, 'psutil', _fake_psutil(by_pid={77: loop}))
    assert MOD._is_detached(_P(10, ppid=99), 0) is True  # no session pid at all
    assert MOD._is_detached(_P(10, ppid=99), 99) is False  # direct child
    assert MOD._is_detached(_P(10, ppid=1), 99) is True  # reparented to init
    assert MOD._is_detached(loop, 99) is True  # past the depth cap
    assert MOD._is_detached(_P(10, ppid=5), 99) is True  # parent unreadable


def test_busy_fires_on_any_of_the_three_thresholds():
    base = {'vram_mb': 0.0, 'cpu_pct': 0.0, 'rss_mb': 0.0}
    assert MOD._proc_is_busy(base) is False
    assert MOD._proc_is_busy({**base, 'vram_mb': MOD._VRAM_ACTIVE_MB}) is True
    assert MOD._proc_is_busy({**base, 'cpu_pct': MOD._CPU_ACTIVE_PCT}) is True
    assert MOD._proc_is_busy({**base, 'rss_mb': MOD._RAM_ACTIVE_MB}) is True
    assert MOD._session_devices({}) == {'gpu': False, 'cpu': False}
    hot = {'vram_mb': MOD._VRAM_ACTIVE_MB, 'cpu_pct': 0.0, 'ram_mb': MOD._RAM_ACTIVE_MB}
    assert MOD._session_devices(hot) == {'gpu': True, 'cpu': True}


# ── The sampling pass ───────────────────────────────────────────────────────
def test_sample_without_psutil_records_the_reason(monkeypatch):
    monkeypatch.setattr(MOD, 'psutil', None)
    MOD._sample()
    assert MOD._sampler_error == 'psutil unavailable'


@pytest.fixture
def sampled(monkeypatch):
    """Drive ``_sample`` with a canned process list and session registry."""
    monkeypatch.setattr(MOD, '_nvidia_refresh', lambda: None)

    def run(procs, live, env, gpu_pids=None):
        monkeypatch.setattr(MOD, 'psutil', _fake_psutil(procs, {p.pid: p for p in procs}))
        monkeypatch.setattr(MOD, '_live_sessions', lambda: dict(live))
        monkeypatch.setattr(MOD, '_read_env', lambda pid: dict(env.get(pid, {})))
        MOD._gpu_pids.clear()
        MOD._gpu_pids.update(gpu_pids or {})
        MOD._sample()

    return run


def _live(sid, pid=1234):
    return {sid: {'id': sid, 'short': sid[:8], 'pid': pid, 'name': 'nova', 'cwd': '/c', 'project': 'zyg'}}


def test_sample_classifies_announces_and_aggregates(sampled):
    sid, other = 'sess0001xyz0', 'sess0002xyz0'
    procs = [
        _P(os.getpid()),  # the dashboard itself
        _P(2001, uid=MOD._UID + 1),  # another user
        _P(2002, cmdline=('ffmpeg', '-i', 'a.mp4'), cpu=900.0, rss_mb=100.0, ppid=1234),
        _P(2003),  # no CLAUDE_CODE_SESSION_ID
        _P(2004, cmdline=('/usr/bin/claude', 'mcp', 'serve')),  # infrastructure
        _P(2005, cmdline=('python', 't.py'), rss_mb=1.0, cpu_raises=True),
        _P(2006, create_time=5000.0),  # pid reused under a stale record
        _P(2007, create_time=5.0),  # already in the negative cache
        _P(2008, info_raises=_NoSuch('vanished')),
        _P(2009, info_raises=RuntimeError('weird psutil')),
    ]
    env = {
        2002: {'CLAUDE_CODE_SESSION_ID': sid, 'CLAUDE_PID': '1234'},
        2004: {'CLAUDE_CODE_SESSION_ID': sid},
        2005: {'CLAUDE_CODE_SESSION_ID': sid, 'CLAUDE_PID': 'not-a-number'},
        2006: {'CLAUDE_CODE_SESSION_ID': other},
    }
    MOD._tracked[2006] = {'pid': 2006, 'create_time': 1.0}
    MOD._ignored[2007] = 5.0

    sampled(procs, _live(sid), env, gpu_pids={2002: 500.0})

    assert sorted(MOD._tracked) == [2002, 2005, 2006]
    assert MOD._ignored.keys() >= {2003, 2004, 2007}
    assert MOD._tracked[2002]['kind'] == 'render'
    assert MOD._tracked[2002]['detached'] is False
    assert MOD._tracked[2005]['claude_pid'] == 0
    s = MOD._sessions[sid]
    assert (s['proc_count'], s['vram_mb'], s['cpu_cores'], s['active'], s['reason']) == (2, 500.0, 9.0, True, 'gpu')
    assert {'session', 'proc_start', 'hw_on'} <= set(_kinds())
    assert MOD._gpu['agent_mb'] == 500.0
    assert MOD._last_sample > 0


def test_sample_reports_what_a_finished_process_cost(sampled):
    sid = 'sess0003xyz0'
    env = dict.fromkeys((3001, 3002), {'CLAUDE_CODE_SESSION_ID': sid, 'CLAUDE_PID': '1'})
    procs = [
        _P(3001, cmdline=('python', 'render.py'), cpu=50.0, rss_mb=10.0, create_time=900.0),
        _P(3002, cmdline=('python', 'burn.py'), cpu=1500.0, rss_mb=10.0, create_time=900.0),
    ]

    sampled(procs, _live(sid, pid=1), env, gpu_pids={3001: 400.0})
    assert MOD._sessions[sid]['active'] is True

    sampled([], _live(sid, pid=1), env)

    ends = [e['text'] for e in MOD._events if e['kind'] == 'proc_end']
    assert len(ends) == 2
    assert any('MiB VRAM' in t for t in ends)
    assert any('cores' in t and 'VRAM' not in t for t in ends)
    assert MOD._sessions[sid]['active'] is False
    assert 'hw_off' in _kinds()


def test_sample_keeps_an_orphaned_session_and_drops_an_empty_one(sampled):
    orphan, empty = 'orph0001aaaa', 'empt0001aaaa'
    MOD._sessions[orphan] = _session(orphan)
    MOD._sessions[empty] = _session(empty, proc_count=0)
    proc = _P(4001, cmdline=('python', 'left.py'), cpu=1500.0, rss_mb=10.0)
    env = {4001: {'CLAUDE_CODE_SESSION_ID': orphan, 'CLAUDE_PID': '1'}}

    sampled([proc], {}, env)

    assert empty not in MOD._sessions
    assert MOD._sessions[orphan]['orphan'] is True
    assert MOD._sessions[orphan]['alive'] is False
    warn = [e for e in MOD._events if e['level'] == 'warn']
    assert warn and 'left running' in warn[0]['text']

    MOD._events.clear()
    sampled([proc], {}, env)
    assert [e for e in MOD._events if e['level'] == 'warn'] == []  # announced once


def test_sample_bounds_the_negative_cache(sampled):
    MOD._ignored.update({i: float(i) for i in range(6001)})
    sampled([], {}, {})
    assert MOD._ignored == {}


# ── Spans ───────────────────────────────────────────────────────────────────
def test_span_record_is_a_flat_jsonable_row():
    rec = MOD._span_record(_span(), 1160.0)
    assert (rec['sid'], rec['short'], rec['duration_s']) == ('sess0001abcd', 'sess0001', 160)
    assert rec['peak_cpu_cores'] == 1.5
    assert rec['kinds'] == ['render']
    assert json.loads(json.dumps(rec))['device'] == 'gpu'


def test_ledger_append_creates_the_directory(tmp_path):
    MOD._ledger_append({'sid': 'a', 'device': 'gpu'})
    MOD._ledger_append({'sid': 'b', 'device': 'cpu'})
    assert [r['sid'] for r in _rows(tmp_path)] == ['a', 'b']


@pytest.mark.parametrize('const', ['_LEDGER_FILE', '_OPEN_SPANS_FILE'])
def test_a_write_under_an_unwritable_path_is_logged_not_raised(monkeypatch, tmp_path, const):
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory', encoding='utf-8')
    monkeypatch.setattr(MOD, const, str(blocker / 'out'))
    MOD._ledger_append({'sid': 'a'})
    MOD._flush_open_spans(1.0, force=True)
    assert blocker.read_text(encoding='utf-8') == 'not a directory'


def test_close_span_ignores_an_unknown_key_and_short_spans(tmp_path):
    MOD._close_span(('nobody', 'gpu'), 1.0)
    MOD._spans[('s', 'gpu')] = _span(sid='s', start_ts=100.0, last_busy=101.0)
    MOD._close_span(('s', 'gpu'), 1.0)  # end clamped up to start → 0 s, below the floor
    assert MOD._spans == {}
    assert not (tmp_path / 'led' / 'ledger.jsonl').exists()


@pytest.mark.parametrize(('device', 'needle'), [('gpu', 'MiB VRAM'), ('cpu', 'cores')])
def test_close_span_writes_the_ledger_row_and_an_event(tmp_path, device, needle):
    MOD._sessions['sess0001abcd'] = _session('sess0001abcd')
    MOD._spans[('sess0001abcd', device)] = _span(device=device)

    MOD._close_span(('sess0001abcd', device), 1300.0)

    assert _rows(tmp_path)[0]['duration_s'] == 300
    assert _rows(tmp_path)[0]['device'] == device
    assert needle in [e for e in MOD._events if e['kind'] == 'span_end'][0]['text']
    assert MOD._open_dirty is True


def test_track_spans_opens_refreshes_and_closes(tmp_path):
    sid = 'sess0005abcd'
    MOD._sessions[sid] = _session(
        sid, vram_mb=500.0, cpu_pct=1500.0, ram_mb=4096.0,
        procs=[
            {'busy': True, 'kind': 'render', 'cmd': 'ffmpeg -i a.mp4', 'vram_mb': 500.0},
            {'busy': True, 'kind': 'test', 'cmd': 'ffmpeg -i a.mp4', 'vram_mb': 0.0},
            {'busy': False, 'kind': 'proc', 'cmd': 'sleep 1', 'vram_mb': 0.0},
        ],
    )  # fmt: skip

    MOD._track_spans(1000.0)
    MOD._track_spans(1100.0)

    gpu, cpu = MOD._spans[(sid, 'gpu')], MOD._spans[(sid, 'cpu')]
    assert gpu['samples'] == 2
    assert gpu['kinds'] == {'render'}  # the 0-MiB proc is not GPU work
    assert gpu['cmds'] == ['ffmpeg -i a.mp4']  # deduped
    assert cpu['kinds'] == {'render', 'test'}
    assert cpu['peak_ram'] == 4096.0

    MOD._sessions[sid].update({'vram_mb': 0.0, 'cpu_pct': 0.0, 'ram_mb': 0.0})
    MOD._track_spans(1100.0 + MOD._SPAN_GRACE_S + 1)

    assert MOD._spans == {}
    assert sorted(r['device'] for r in _rows(tmp_path)) == ['cpu', 'gpu']


def test_track_spans_ignores_a_dead_session_and_closes_vanished_ones():
    MOD._sessions['dead00001111'] = _session('dead00001111', alive=False, vram_mb=9000.0, cpu_pct=9000.0)
    MOD._spans[('ghost0001111', 'gpu')] = _span(sid='ghost0001111', start_ts=1.0, last_busy=2.0)
    MOD._track_spans(5000.0)
    assert MOD._spans == {}


def test_flush_open_spans_mirrors_the_open_spans(monkeypatch, tmp_path):
    MOD._spans[('sess0001abcd', 'gpu')] = _span()
    monkeypatch.setattr(MOD, '_open_flushed', 10_000.0)
    MOD._flush_open_spans(10_001.0)  # clean and recently flushed: skipped
    assert not (tmp_path / 'led' / 'open.json').exists()

    MOD._flush_open_spans(1200.0, force=True)
    d = json.loads((tmp_path / 'led' / 'open.json').read_text(encoding='utf-8'))
    assert d['spans'][0]['open'] is True
    assert d['spans'][0]['end_ts'] == 1100.0
    assert d['as_of']
    assert MOD._open_dirty is False


def test_recover_open_spans_closes_what_the_last_life_left_open(tmp_path):
    MOD._recover_open_spans()  # no snapshot from a previous life
    assert not (tmp_path / 'led' / 'ledger.jsonl').exists()

    snap = tmp_path / 'led' / 'open.json'
    snap.parent.mkdir(parents=True)
    snap.write_text(
        json.dumps({'as_of': 'x', 'spans': [
            {'sid': 'keep00001111', 'device': 'gpu', 'start_ts': 100, 'end_ts': 400, 'open': True},
            {'sid': 'tiny00001111', 'device': 'cpu', 'start_ts': 100, 'end_ts': 101},  # below the floor
            {'sid': 'junk00001111', 'start_ts': 'nope', 'end_ts': None},  # malformed
        ]}),
        encoding='utf-8',
    )  # fmt: skip

    MOD._recover_open_spans()

    rows = _rows(tmp_path)
    assert [r['sid'] for r in rows] == ['keep00001111']
    assert rows[0]['recovered'] is True and 'open' not in rows[0]
    assert _kinds() == ['ledger']
    assert json.loads(snap.read_text(encoding='utf-8'))['spans'] == []


# ── Public reader ───────────────────────────────────────────────────────────
def test_ledger_spans_without_a_ledger_returns_only_open_spans():
    MOD._spans[('sess0001abcd', 'gpu')] = _span()
    MOD._spans[('sess0001abcd', 'cpu')] = _span(device='cpu')
    assert [r['device'] for r in MOD.ledger_spans()] == ['gpu', 'cpu']
    assert [r['device'] for r in MOD.ledger_spans(device='cpu')] == ['cpu']
    assert MOD.ledger_spans()[0]['open'] is True


def test_ledger_spans_filters_by_device_and_recency(tmp_path):
    led = tmp_path / 'led' / 'ledger.jsonl'
    led.parent.mkdir(parents=True)
    led.write_text(
        json.dumps({'sid': 'a', 'device': 'gpu', 'end_ts': 100}) + '\nthis line is not json\n'
        + json.dumps({'sid': 'b', 'device': 'cpu', 'end_ts': 50}) + '\n'
        + json.dumps({'sid': 'c', 'device': 'gpu', 'end_ts': 10}) + '\n',
        encoding='utf-8',
    )  # fmt: skip

    assert [r['sid'] for r in MOD.ledger_spans()] == ['a', 'b', 'c']
    assert [r['sid'] for r in MOD.ledger_spans(since_ts=60)] == ['a']
    assert [r['sid'] for r in MOD.ledger_spans(device='gpu')] == ['a', 'c']


# ── The loop ────────────────────────────────────────────────────────────────
class _Stop(BaseException):
    pass


def test_loop_records_a_sampler_crash_and_then_sleeps(monkeypatch):
    def boom():
        raise ValueError('sample blew up')

    def sleep(_s):
        raise _Stop

    monkeypatch.setattr(MOD, '_sample', boom)
    monkeypatch.setattr(MOD, 'time', SimpleNamespace(sleep=sleep, time=lambda: 1.0))

    with pytest.raises(_Stop):
        MOD._loop()

    assert MOD._sampler_error == 'ValueError: sample blew up'
