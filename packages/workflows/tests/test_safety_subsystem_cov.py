# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for the safety subsystem: guards, recovery, quarantine, audit log, thresholds.

Everything here runs offline: no GPU, no control plane, no psutil or NVML call reaches the
real machine. The ``safety`` fixture swaps every mutable module global for a fresh one, and
every path the module touches points into ``tmp_path``.
"""

import copy
import json
import threading
import types
from collections import deque

import pytest

from zyg_workflows import safety_subsystem as _mod

_CLEAN_RECOVERY = {
    'state': 'normal',
    'tripped_at': None,
    'last_level': 0,
    'admin_confirmed_at': None,
    'admin_confirmed_by': None,
    'staged_recovery_stages': [],
}


@pytest.fixture
def safety(monkeypatch):
    """The module with every mutable global replaced, so tests cannot leak into each other."""
    monkeypatch.setattr(_mod, '_AUDIT_EVENTS', deque(maxlen=500))
    monkeypatch.setattr(_mod, '_AUDIT_LOG_PATH', None)
    monkeypatch.setattr(_mod, '_AGENT_FAILURES', deque(maxlen=500))
    monkeypatch.setattr(_mod, '_MODEL_FAILURES', deque(maxlen=500))
    monkeypatch.setattr(_mod, '_RECOVERY_STATE', dict(_CLEAN_RECOVERY, staged_recovery_stages=[]))
    # _load_thresholds returns a SHALLOW copy of DEFAULT_THRESHOLDS, so update_thresholds would
    # otherwise edit the package default in place for the rest of the session.
    monkeypatch.setattr(_mod, 'DEFAULT_THRESHOLDS', copy.deepcopy(_mod.DEFAULT_THRESHOLDS))
    return _mod


def _thr(safety):
    return copy.deepcopy(safety.DEFAULT_THRESHOLDS)


def _boom(*_a, **_kw):
    raise RuntimeError('subsystem unreachable')


def test_ams_clock_falls_back_to_utc_and_to_a_timespec_free_isoformat(safety, monkeypatch):
    assert safety._ams_now().tzinfo is not None
    assert safety._ams_iso().count(':') >= 2
    monkeypatch.setattr(safety, '_AMS_TZ', None)
    assert safety._ams_now().utcoffset().total_seconds() == 0
    # A tzinfo datetime.now() refuses sends us down the except branch, also to UTC.
    monkeypatch.setattr(safety, '_AMS_TZ', object())
    assert safety._ams_now().utcoffset().total_seconds() == 0

    class _NoTimespec:
        def isoformat(self, *a, **kw):
            if a or kw:
                raise TypeError('timespec unsupported')
            return '2026-01-01T00:00:00'

    monkeypatch.setattr(safety, '_ams_now', lambda: _NoTimespec())
    assert safety._ams_iso() == '2026-01-01T00:00:00'


def test_init_safety_audit_without_a_usable_path_keeps_the_log_in_memory(safety, tmp_path):
    safety.init_safety_audit(None)
    assert safety._AUDIT_LOG_PATH is None
    missing = tmp_path / 'nope.jsonl'
    safety.init_safety_audit(str(missing))
    assert safety._AUDIT_LOG_PATH == str(missing)
    assert safety.get_audit_events() == []
    for i in range(3):
        safety.audit_log(f'event-{i}')  # in memory and appended to a fresh file, newest first
    assert [e['event'] for e in safety.get_audit_events(limit=2)] == ['event-2', 'event-1']
    assert len(missing.read_text(encoding='utf-8').splitlines()) == 3


def test_init_safety_audit_replays_the_file_and_skips_the_junk(safety, tmp_path):
    path = tmp_path / 'audit.jsonl'
    path.write_text(
        json.dumps({'ts': 't1', 'event': 'first', 'level': 'info'})
        + '\n\nnot json at all\n'
        + json.dumps({'ts': 't2', 'event': 'second', 'level': 'warning'})
        + '\n',
        encoding='utf-8',
    )
    safety.init_safety_audit(str(path))
    events = safety.get_audit_events()
    assert [e['event'] for e in events] == ['second', 'first']
    assert events[0]['level'] == 'warning'


def test_the_audit_log_survives_a_file_it_cannot_read_or_write(safety, tmp_path, monkeypatch):
    path = tmp_path / 'audit.jsonl'
    path.write_text('{}\n', encoding='utf-8')
    monkeypatch.setattr(safety, 'open', _boom, raising=False)
    safety.init_safety_audit(str(path))
    assert safety.get_audit_events() == []
    safety.audit_log('still recorded')
    assert safety.get_audit_events()[0]['event'] == 'still recorded'


def test_audit_log_records_every_field_and_persists_to_the_file(safety, tmp_path):
    path = tmp_path / 'audit.jsonl'
    safety.init_safety_audit(str(path))
    safety.audit_log(
        'GPU too hot',
        level='critical',
        extra={'reason': 'thermal', 'ignored': None, 'event': 'must not overwrite'},
        trigger_source='gpu',
        threshold=83,
        observed_value=91.5,
        action_taken='terminate',
        actor='admin',
        recovery_action='confirm_recovery',
    )
    entry = json.loads(path.read_text(encoding='utf-8').strip())
    assert entry['event'] == 'GPU too hot'
    assert entry['level'] == 'critical'
    assert entry['trigger_source'] == 'gpu'
    assert entry['threshold'] == 83
    assert entry['observed_value'] == 91.5
    assert entry['action_taken'] == 'terminate'
    assert entry['actor'] == 'admin'
    assert entry['recovery_action'] == 'confirm_recovery'
    assert entry['reason'] == 'thermal'
    assert 'ignored' not in entry


@pytest.mark.parametrize(
    ('level', 'expected'),
    [
        (1, 'tripped_l1'),
        (2, 'tripped_l2'),
        (3, 'awaiting_admin_l3'),
        (4, 'awaiting_admin_l4'),
        (7, 'awaiting_admin_l4'),
    ],
)
def test_update_recovery_state_trips_to_the_matching_state(safety, level, expected):
    safety._update_recovery_state(level, False)
    state = safety.get_recovery_state()
    assert (state['state'], state['last_level']) == (expected, level)
    assert state['tripped_at'] is not None


def test_update_recovery_state_escalates_l1_to_l2_and_auto_recovers(safety):
    safety._update_recovery_state(1, False)
    tripped_at = safety.get_recovery_state()['tripped_at']
    safety._update_recovery_state(2, False)
    assert safety.get_recovery_state()['state'] == 'tripped_l2'
    assert safety.get_recovery_state()['tripped_at'] == tripped_at
    safety._update_recovery_state(0, False)
    assert safety.get_recovery_state() == _CLEAN_RECOVERY


def test_update_recovery_state_leaves_the_admin_levels_latched(safety):
    safety._update_recovery_state(3, True)
    safety._update_recovery_state(0, True)  # level 0 alone does not clear an L3
    safety._update_recovery_state(3, True)  # an L3 already waiting is not re-stamped
    assert safety.get_recovery_state()['state'] == 'awaiting_admin_l3'
    safety._RECOVERY_STATE['staged_recovery_stages'] = ['ui', 'scheduler']
    safety._update_recovery_state(4, True)
    assert safety.get_recovery_state()['staged_recovery_stages'] == []
    safety._RECOVERY_STATE['staged_recovery_stages'] = ['ui']
    safety._update_recovery_state(4, True)  # already awaiting_admin_l4: the stages survive
    assert safety.get_recovery_state()['staged_recovery_stages'] == ['ui']


def test_can_resume_schedule_needs_the_right_confirmation_per_level(safety):
    assert safety.can_resume_schedule(4, False) == (True, 'Schedule not paused')
    assert safety.can_resume_schedule(4, True) == (False, 'Recovery state inconsistent')
    safety._update_recovery_state(4, True)
    allowed, reason = safety.can_resume_schedule(4, True)
    assert not allowed
    assert 'L4 staged recovery: confirm' in reason
    safety._RECOVERY_STATE['staged_recovery_stages'] = list(safety.L4_RECOVERY_STAGES)
    assert safety.can_resume_schedule(4, True) == (True, 'All L4 recovery stages confirmed')
    safety._RECOVERY_STATE.update(_CLEAN_RECOVERY)
    assert safety.can_resume_schedule(3, True) == (False, 'Recovery state inconsistent')
    safety._update_recovery_state(3, True)
    assert safety.can_resume_schedule(3, True) == (False, 'Admin confirmation required for L3 recovery')
    safety._RECOVERY_STATE['admin_confirmed_at'] = '2026-01-01T00:00:00'
    assert safety.can_resume_schedule(3, True) == (True, 'Admin confirmed L3 recovery')
    safety._RECOVERY_STATE.update(_CLEAN_RECOVERY)
    safety._update_recovery_state(2, True)
    assert safety.can_resume_schedule(1, True) == (False, 'Telemetry still elevated; wait for normalization')
    safety._update_recovery_state(0, True)
    assert safety.can_resume_schedule(0, True) == (True, 'OK')


def test_confirm_recovery_l3_clears_the_state_and_audits(safety):
    assert safety.confirm_recovery(3, actor='ada') == (False, 'Cannot confirm L3: state is normal')
    assert safety.confirm_recovery(2) == (False, 'Invalid level for confirm_recovery')
    safety._update_recovery_state(3, True)
    assert safety.confirm_recovery(3, actor='ada', reason='cooled down') == (True, None)
    state = safety.get_recovery_state()
    assert (state['state'], state['admin_confirmed_by'], state['tripped_at']) == ('normal', 'ada', None)
    assert safety.get_audit_events()[0]['event'] == 'L3 recovery confirmed by admin'


def test_confirm_recovery_l4_walks_the_stages_in_order_and_is_idempotent(safety):
    assert safety.confirm_recovery(4) == (False, 'Cannot confirm L4: state is normal')
    safety._update_recovery_state(4, True)
    for bad_stage in (None, 'nonsense'):
        ok, err = safety.confirm_recovery(4, stage=bad_stage)
        assert not ok
        assert err.startswith('L4 requires stage:')
    assert safety.confirm_recovery(4, stage='agents') == (False, "Expected stage 'ui' next, got 'agents'")
    for stage in safety.L4_RECOVERY_STAGES[:-1]:
        assert safety.confirm_recovery(4, actor='ada', stage=stage) == (True, None)
        assert safety.confirm_recovery(4, actor='ada', stage=stage) == (True, None)  # idempotent
    # The last stage clears the state, so re-confirming anything afterwards is refused.
    assert safety.confirm_recovery(4, actor='ada', stage=safety.L4_RECOVERY_STAGES[-1]) == (True, None)
    assert safety.confirm_recovery(4, actor='ada', stage='ui') == (False, 'Cannot confirm L4: state is normal')
    state = safety.get_recovery_state()
    assert (state['state'], state['admin_confirmed_by']) == ('normal', 'ada')
    assert state['staged_recovery_stages'] == safety.L4_RECOVERY_STAGES


def test_record_failures_quarantines_an_agent_and_a_model(safety):
    thresholds = _thr(safety)
    assert safety.is_quarantined_agent('writer', thresholds) == (False, '')
    for _ in range(3):
        safety.record_agent_failure('writer')
        safety.record_model_failure('llama')
    quarantined, reason = safety.is_quarantined_agent('writer', thresholds)
    assert quarantined
    assert '3 failures in 5m (threshold 3)' in reason
    quarantined, reason = safety.is_quarantined_model('llama', thresholds)
    assert quarantined
    assert '3 launch failures in 5m (threshold 3)' in reason
    # Another identity in the same window is untouched.
    assert safety.is_quarantined_agent('editor', thresholds)[0] is False
    assert safety.is_quarantined_model('qwen', thresholds)[0] is False
    # Without thresholds the built-in limit of five applies, so three is not yet enough.
    assert safety.is_quarantined_agent('writer') == (False, '')
    assert safety.is_quarantined_model('llama') == (False, '')
    for _ in range(2):
        safety.record_agent_failure('writer')
        safety.record_model_failure('llama')
    assert safety.is_quarantined_agent('writer')[0] is True
    assert safety.is_quarantined_model('llama')[0] is True


def test_the_failure_window_prunes_the_stale_entries_and_reads_both_entry_shapes(safety):
    old = '2001-01-01T00:00:00.000+01:00'
    fresh = safety._ams_iso()
    failures = deque([(old, 'a'), ('not-a-timestamp', 'b'), (fresh, 'c'), (old, 'd')])
    safety._trim_failures(failures)
    assert list(failures) == [(fresh, 'c'), (old, 'd')]
    shapeless = deque([5])  # an entry that is neither a tuple nor a mapping
    safety._trim_failures(shapeless)
    assert list(shapeless) == [5]
    failures = deque(
        [{'ts': fresh, 'model_id': 'llama'}, {'ts': fresh, 'agent_id': 'writer'}, {'ts': fresh, 'model_id': 'llama'}]
    )
    assert safety._count_failures_in_window(failures, 'llama') == 2
    assert safety._count_failures_in_window(failures, 'writer') == 1
    assert safety._count_failures_in_window(failures, 'absent') == 0
    # A fresh entry at the front stops the pruning, so the junk behind it reaches the counter.
    junk = deque([(fresh, 'writer'), ('nonsense', 'writer')])
    assert safety._count_failures_in_window(junk, 'writer', window_sec=10) == 1


def test_get_quarantined_agents_lists_only_the_crash_loopers(safety, monkeypatch):
    assert safety.get_quarantined_agents(_thr(safety)) == []
    safety._AGENT_FAILURES.append((safety._ams_iso(),))  # no agent id: skipped
    assert safety.get_quarantined_agents(_thr(safety)) == []
    # get_quarantined_agents holds _QUARANTINE_LOCK and then calls is_quarantined_agent, which
    # takes the same non-reentrant lock again — so the production path is only reachable here
    # with a reentrant lock. See the report's not_done.
    monkeypatch.setattr(safety, '_QUARANTINE_LOCK', threading.RLock())
    safety._AGENT_FAILURES.clear()
    for _ in range(3):
        safety.record_agent_failure('writer')
    safety.record_agent_failure('editor')
    assert safety.get_quarantined_agents(_thr(safety)) == ['writer']


_TWO_GPUS = {
    'gpus': [
        {'memory_total_mb': 8192, 'memory_used_mb': 8000},
        {'memory_total_mb': 24576, 'memory_used_mb': 1024},
    ]
}


_ONE_GPU = {'gpus': [{'memory_total_mb': 8192, 'memory_used_mb': 1024}]}
_NO_VRAM = 'VRAM insufficient: need {} MB, available ~{} MB (reserve {})'


@pytest.mark.parametrize(
    ('need_mb', 'telemetry', 'device_id', 'reserved_mb', 'with_thresholds', 'expected'),
    [
        (1000, {}, None, 0, True, (False, 'No GPU telemetry; cannot verify VRAM')),
        (1000, {'gpus': []}, None, 0, True, (False, 'No GPU telemetry; cannot verify VRAM')),
        (1000, {'gpus': [{'memory_total_mb': 0}]}, None, 0, True, (False, 'GPU memory total unknown')),
        (1000, _ONE_GPU, None, 0, True, (True, '')),
        (1000, _ONE_GPU, 9, 0, True, (True, '')),  # out-of-range device id: first GPU
        (4096, _TWO_GPUS, 0, 0, True, (False, _NO_VRAM.format(4096, 0, 1024))),
        (4096, _TWO_GPUS, 1, 0, True, (True, '')),
        (4096, _TWO_GPUS, 1, 20000, True, (False, _NO_VRAM.format(4096, 2528, 1024))),
        (8000, _TWO_GPUS, 0, 0, False, (False, _NO_VRAM.format(8000, 0, 512))),  # built-in reserve
    ],
)
def test_can_launch_job_decides_from_the_gpu_telemetry(
    safety, need_mb, telemetry, device_id, reserved_mb, with_thresholds, expected
):
    assert (
        safety.can_launch_job(
            need_mb,
            telemetry,
            device_id=device_id,
            thresholds=_thr(safety) if with_thresholds else None,
            reserved_total_mb=reserved_mb,
        )
        == expected
    )


def test_the_intervention_hooks_report_whatever_the_caller_supplied(safety):
    assert safety.request_terminate_run('run-1', 'too hot', lambda r, s: {'ok': True, 'run': r}) == {
        'ok': True,
        'run': 'run-1',
    }
    assert safety.request_terminate_run('run-1', '', lambda r, s: None) == {'ok': False}
    assert safety.request_terminate_run('run-1', '', _boom) == {'ok': False, 'error': 'subsystem unreachable'}
    assert safety.request_terminate_run('run-1') == {'ok': False, 'error': 'No terminate_fn configured'}
    assert safety.request_reduce_concurrency('writer', 1, lambda a, n: {'success': True, 'max': n}) == {
        'success': True,
        'max': 1,
    }
    assert safety.request_reduce_concurrency('writer', 1, lambda a, n: None) == {'success': False}
    assert safety.request_reduce_concurrency('writer', 1, _boom) == {
        'success': False,
        'error': 'subsystem unreachable',
    }
    assert safety.request_reduce_concurrency('writer', 1) == {'success': False, 'error': 'No reduce_fn configured'}


def test_thresholds_are_loaded_with_the_defaults_filled_in(safety, tmp_path):
    assert safety._load_thresholds('') == safety.DEFAULT_THRESHOLDS
    assert safety.get_thresholds(str(tmp_path / 'absent.json')) == safety.DEFAULT_THRESHOLDS
    broken = tmp_path / 'broken.json'
    broken.write_text('{ this is not json', encoding='utf-8')
    assert safety._load_thresholds(str(broken)) == safety.DEFAULT_THRESHOLDS
    path = tmp_path / 'thresholds.json'
    path.write_text(
        json.dumps({'_version': 9, 'gpu': {'temp_warning_c': 60}, 'novel': 5, 'cpu': 'not a dict'}),
        encoding='utf-8',
    )
    loaded = safety._load_thresholds(str(path))
    assert loaded['_version'] == 9
    assert loaded['gpu']['temp_warning_c'] == 60
    assert loaded['gpu']['temp_critical_c'] == safety.DEFAULT_THRESHOLDS['gpu']['temp_critical_c']
    assert loaded['novel'] == 5
    assert loaded['cpu'] == 'not a dict'


def test_save_thresholds_reports_success_and_failure(safety, tmp_path):
    assert safety._save_thresholds('', {'a': 1}) is False
    path = tmp_path / 'out.json'
    assert safety._save_thresholds(str(path), {'a': 1}) is True
    assert json.loads(path.read_text(encoding='utf-8')) == {'a': 1}
    assert safety._save_thresholds(str(tmp_path), {'a': 1}) is False  # a directory


def test_update_thresholds_writes_validated_values_and_audits(safety, tmp_path, monkeypatch):
    path = tmp_path / 'thresholds.json'
    assert safety.update_thresholds(
        str(path),
        {
            'gpu': {'temp_warning_c': 70},
            '_version': 99,  # underscore keys are not caller-settable
            'unknown_category': {'x': 1},
            'cpu': 'not a dict',
        },
        actor='ada',
    ) == (True, None)
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written['gpu']['temp_warning_c'] == 70
    assert written['_version'] == safety.DEFAULT_THRESHOLDS['_version'] + 1
    assert written['_updated_by'] == 'ada'
    assert 'unknown_category' not in written
    assert isinstance(written['cpu'], dict)
    assert safety.get_audit_events()[0]['event'] == 'Threshold configuration updated'
    assert safety.update_thresholds(str(path), {'gpu': {'min_reserve_vram_mb': -1}}) == (
        False,
        'Invalid gpu.min_reserve_vram_mb: reserve must be non-negative',
    )
    monkeypatch.setattr(safety, '_save_thresholds', lambda p, d: False)
    assert safety.update_thresholds(str(path), {'ram': {'warning_pct': 50}}) == (False, 'Failed to save thresholds')


class _FakeMem:
    percent = 61.5
    used = 8 * 1024**3
    total = 32 * 1024**3


class _FakeDisk:
    free = 120 * 1024**3


def _fake_psutil(**overrides):
    fake = types.SimpleNamespace(
        cpu_percent=lambda interval=None: 17.25,
        virtual_memory=lambda: _FakeMem(),
        disk_usage=lambda path: _FakeDisk(),
        sensors_temperatures=lambda: {},
    )
    for key, value in overrides.items():
        setattr(fake, key, value)
    return fake


def _use_psutil(monkeypatch, **overrides):
    monkeypatch.setattr(_mod, 'HAS_PSUTIL', True)
    monkeypatch.setattr(_mod, 'psutil', _fake_psutil(**overrides), raising=False)


def _install_nvml(monkeypatch, **overrides):
    funcs = {
        'nvmlInit': lambda: None,
        'nvmlShutdown': lambda: None,
        'nvmlDeviceGetCount': lambda: 1,
        'nvmlDeviceGetHandleByIndex': lambda i: f'gpu{i}',
        'nvmlDeviceGetUtilizationRates': lambda h: types.SimpleNamespace(gpu=42),
        'nvmlDeviceGetMemoryInfo': lambda h: types.SimpleNamespace(used=4 * 1024**3, total=8 * 1024**3),
        'nvmlDeviceGetTemperature': lambda h, sensor: 61,
        'NVML_TEMPERATURE_GPU': 0,
    }
    funcs.update(overrides)
    monkeypatch.setattr(_mod, 'HAS_NVML', True)
    for name, value in funcs.items():
        monkeypatch.setattr(_mod, name, value, raising=False)


def test_local_telemetry_reads_cpu_ram_and_disk_when_psutil_is_there(safety, monkeypatch):
    monkeypatch.setattr(safety, 'HAS_NVML', False)
    monkeypatch.setattr(safety, 'HAS_PSUTIL', False)
    assert safety._get_local_telemetry() == {
        'cpu_pct': 0,
        'ram_pct': 0,
        'ram_used_mb': 0,
        'ram_total_mb': 0,
        'free_disk_gb': None,
        'gpus': [],
    }
    _use_psutil(monkeypatch)
    out = safety._get_local_telemetry()
    assert (out['cpu_pct'], out['ram_pct']) == (17.25, 61.5)
    assert (out['ram_used_mb'], out['ram_total_mb']) == (8192.0, 32768.0)
    assert out['free_disk_gb'] == 120.0
    assert out['gpus'] == []
    # On Windows the system drive is measured instead of /.
    seen = []
    _use_psutil(monkeypatch, disk_usage=lambda path: seen.append(path) or _FakeDisk())
    monkeypatch.setattr(safety.os, 'name', 'nt')
    assert safety._get_local_telemetry()['free_disk_gb'] == 120.0
    assert len(seen) == 2
    # A psutil that throws leaves the defaults in place.
    _use_psutil(monkeypatch, cpu_percent=_boom)
    assert safety._get_local_telemetry()['cpu_pct'] == 0


_GPU_FIELDS = ('index', 'temperature_c', 'utilization_pct', 'memory_used_mb', 'memory_total_mb', 'memory_pct')


def _gpu_row(telemetry):
    (gpu,) = telemetry['gpus']
    assert set(gpu) == set(_GPU_FIELDS)
    return tuple(gpu[field] for field in _GPU_FIELDS)


def test_local_telemetry_reads_the_gpus_through_nvml(safety, monkeypatch):
    _use_psutil(monkeypatch)
    _install_nvml(monkeypatch)
    assert _gpu_row(safety._get_local_telemetry()) == (0, 61, 42.0, 4096.0, 8192.0, 50.0)
    # Each reading degrades on its own, and a failed nvmlInit drops the whole list.
    _install_nvml(
        monkeypatch,
        nvmlDeviceGetTemperature=None,
        nvmlDeviceGetUtilizationRates=_boom,
        nvmlDeviceGetMemoryInfo=_boom,
    )
    assert _gpu_row(safety._get_local_telemetry()) == (0, None, 0.0, 0.0, 1.0, 0.0)
    _install_nvml(monkeypatch, nvmlDeviceGetTemperature=_boom)
    assert _gpu_row(safety._get_local_telemetry())[1] is None
    _install_nvml(monkeypatch, nvmlInit=_boom)
    assert safety._get_local_telemetry()['gpus'] == []


def test_cpu_temp_local_prefers_a_core_sensor_then_any_sensor_then_none(safety, monkeypatch):
    monkeypatch.setattr(safety, 'HAS_PSUTIL', False)
    assert safety._get_cpu_temp_local() is None
    _use_psutil(monkeypatch)
    assert safety._get_cpu_temp_local() is None  # no sensors at all
    _use_psutil(
        monkeypatch,
        sensors_temperatures=lambda: {
            'acpitz': [types.SimpleNamespace(current=31.0)],
            'coretemp': [types.SimpleNamespace(current=55.5)],
        },
    )
    assert safety._get_cpu_temp_local() == 55.5
    _use_psutil(
        monkeypatch,
        sensors_temperatures=lambda: {'nvme': [], 'wifi': [types.SimpleNamespace(current=44.0)]},
    )
    assert safety._get_cpu_temp_local() == 44.0
    _use_psutil(monkeypatch, sensors_temperatures=_boom)
    assert safety._get_cpu_temp_local() is None


def _telemetry(**over):
    out = {'cpu_pct': 10, 'ram_pct': 20, 'free_disk_gb': 100, 'gpus': []}
    out.update(over)
    return out


def _gpu(**over):
    out = {'temperature_c': 40, 'utilization_pct': 10, 'memory_used_mb': 1024, 'memory_total_mb': 24576}
    out.update(over)
    return out


@pytest.mark.parametrize(
    ('telemetry', 'source', 'expected_level', 'expected_fragment'),
    [
        ({}, 'none', 3, 'Telemetry unavailable'),
        ({}, 'local', 2, 'Control plane unreachable'),
        ({'error': 'boom'}, 'control_plane', 2, 'Telemetry error'),
        ({'free_disk_gb': 1}, 'control_plane', 2, 'Critical metrics (CPU/RAM) missing'),
        ({'cpu_pct': 10, 'ram_pct': 20}, 'control_plane', 1, 'Disk telemetry missing'),
        (_telemetry(gpus=[{'utilization_pct': 10}]), 'control_plane', 1, 'GPU VRAM telemetry missing'),
        (_telemetry(), 'control_plane', 0, None),
    ],
)
def test_assess_telemetry_fail_closed(safety, telemetry, source, expected_level, expected_fragment):
    level, reason = safety._assess_telemetry_fail_closed(telemetry, source)
    assert level == expected_level
    if expected_fragment is None:
        assert reason is None
    else:
        assert expected_fragment in reason


@pytest.mark.parametrize(
    ('telemetry', 'expected_level', 'expected_fragment'),
    [
        (_telemetry(), 0, None),
        (_telemetry(gpus=[_gpu(temperature_c=90)]), 3, 'GPU temp critical'),
        (_telemetry(gpus=[_gpu(temperature_c=None, temp_c=78)]), 1, 'GPU temp warning'),
        (_telemetry(gpus=[_gpu(utilization_pct=99)]), 2, 'GPU utilization critical'),
        (_telemetry(gpus=[_gpu(utilization_pct=92)]), 1, 'GPU utilization warning'),
        (_telemetry(gpus=[_gpu(memory_used_mb=24000)]), 3, 'VRAM critical'),
        (_telemetry(gpus=[_gpu(memory_used_mb=21000)]), 1, 'VRAM warning'),
        (_telemetry(cpu_pct=95), 2, 'CPU critical'),
        (_telemetry(cpu_pct=85), 1, 'CPU warning'),
        (_telemetry(ram_pct=95), 3, 'RAM critical'),
        (_telemetry(ram_pct=80), 1, 'RAM warning'),
        (_telemetry(free_disk_gb=2), 3, 'Disk critical'),
        (_telemetry(free_disk_gb=8), 1, 'Disk warning'),
    ],
)
def test_compute_protection_level_grades_each_hardware_guard(safety, telemetry, expected_level, expected_fragment):
    level, label, desc, reasons = safety.compute_protection_level(
        telemetry, {'running_list': [], 'failed_list': []}, False, False, _thr(safety)
    )
    assert level == expected_level
    assert label == ['Normal', 'Warning', 'Protective Degradation', 'Hard Stop', 'Emergency Halt'][expected_level]
    if expected_fragment is None:
        assert reasons == []
        assert desc == 'System healthy, jobs run normally.'
    else:
        assert any(expected_fragment in r for r in reasons)
        assert desc.endswith('.')


@pytest.mark.parametrize(
    ('job_status', 'error_logs', 'expected_level', 'expected_reason'),
    [
        ({'running_list': ['j'] * 50, 'failed_list': []}, None, 3, 'Queue depth critical (50)'),
        ({'running_list': ['j'] * 20, 'failed_list': []}, None, 1, 'Queue depth warning (20)'),
        ({'running_list': [], 'failed_list': ['j'] * 3}, None, 2, 'Failed jobs high (3)'),
        ({}, {'gpu_memory_overflows': ['oom', 'oom']}, 3, 'OOM count high (2)'),
        ({}, {'gpu_memory_overflows': []}, 0, None),
    ],
)
def test_compute_protection_level_grades_the_failure_patterns(
    safety, job_status, error_logs, expected_level, expected_reason
):
    level, _label, _desc, reasons = safety.compute_protection_level(
        _telemetry(), job_status, False, False, _thr(safety), error_logs
    )
    assert level == expected_level
    assert reasons == ([] if expected_reason is None else [expected_reason])


def test_compute_protection_level_lets_the_manual_overrides_win_and_elides_long_reasons(safety):
    level, label, _desc, reasons = safety.compute_protection_level(_telemetry(), {}, True, False, _thr(safety))
    assert (level, label) == (3, 'Hard Stop')
    assert 'Schedule paused (circuit breaker)' in reasons
    level, label, _desc, reasons = safety.compute_protection_level(_telemetry(), {}, True, True, _thr(safety))
    assert (level, label) == (4, 'Emergency Halt')
    assert 'Emergency stop active' in reasons
    telemetry = _telemetry(cpu_pct=95, ram_pct=95, free_disk_gb=1, gpus=[_gpu(temperature_c=90, utilization_pct=99)])
    level, _label, desc, reasons = safety.compute_protection_level(
        telemetry, {'running_list': ['j'] * 60, 'failed_list': []}, False, True, _thr(safety)
    )
    assert level == 4
    assert len(reasons) > 3
    assert desc.endswith('…')


def test_get_safety_status_builds_the_api_payload_from_the_control_plane(safety, tmp_path, monkeypatch):
    monkeypatch.setattr(safety, '_get_cpu_temp_local', lambda: 52.0)
    telemetry = _telemetry(gpus=[_gpu(temperature_c=70.4, utilization_pct=55.6)])
    status = safety.get_safety_status(
        str(tmp_path / 'thresholds.json'),
        telemetry_fn=lambda: telemetry,
        job_status_fn=lambda: {'running_list': ['a', 'b'], 'failed_list': ['c']},
        schedule_pause_fn=lambda: {'paused': False},
        error_logs_fn=lambda: {'gpu_memory_overflows': ['oom']},
    )
    assert (status['protection_level'], status['protection_label']) == (0, 'Normal')
    assert status['circuit_breaker_active'] is False
    assert status['can_resume_schedule'] is True
    assert status['resume_blocked_reason'] is None
    hardware = status['hardware']
    assert tuple(hardware[k] for k in ('gpu_temp_c', 'gpu_pct', 'vram_used_mb')) == (70.4, 55.6, 1024.0)
    assert tuple(hardware[k] for k in ('cpu_temp_c', 'cpu_pct', 'ram_pct', 'free_disk_gb')) == (52.0, 10, 20, 100)
    assert status['stability'] == {'queue_depth': 2, 'oom_count': 1, 'failed_jobs_5m': 1, 'blocked_launches': 0}
    assert status['control'] == {
        'stale_telemetry_count': 0,
        'quarantined_agents': 0,
        'quarantined_agent_ids': [],
        'agents_missing_heartbeat': 0,
    }
    assert status['audit_events'] == []
    assert status['thresholds'] == safety.DEFAULT_THRESHOLDS
    assert status['recovery_state']['state'] == 'normal'


def test_get_safety_status_supplements_the_disk_then_falls_back_and_fails_closed(safety, tmp_path, monkeypatch):
    monkeypatch.setattr(safety, '_get_cpu_temp_local', lambda: None)
    _use_psutil(monkeypatch)
    path = str(tmp_path / 'thresholds.json')
    status = safety.get_safety_status(path, telemetry_fn=lambda: {'cpu_pct': 5, 'ram_pct': 6})
    assert status['hardware']['free_disk_gb'] == 120.0
    assert status['hardware']['vram_used_mb'] is None
    _use_psutil(monkeypatch, disk_usage=_boom)
    status = safety.get_safety_status(path, telemetry_fn=lambda: {'cpu_pct': 5, 'ram_pct': 6})
    assert status['hardware']['free_disk_gb'] is None
    assert status['protection_level'] == 1  # disk telemetry missing: reduced confidence
    # A control plane that answers with an error falls back to the local collector.
    monkeypatch.setattr(safety, '_get_local_telemetry', lambda: _telemetry())
    status = safety.get_safety_status(path, telemetry_fn=lambda: {'error': 'down'})
    assert status['protection_level'] == 2
    assert 'Control plane unreachable' in status['protection_desc']
    assert status['control']['stale_telemetry_count'] == 0
    monkeypatch.setattr(safety, '_get_local_telemetry', lambda: {})
    status = safety.get_safety_status(path)
    assert status['protection_level'] == 3
    assert 'Telemetry unavailable' in status['protection_desc']
    assert status['control']['stale_telemetry_count'] == 1


def test_get_safety_status_survives_every_fetcher_blowing_up(safety, tmp_path, monkeypatch):
    monkeypatch.setattr(safety, '_get_cpu_temp_local', lambda: None)
    monkeypatch.setattr(safety, '_get_local_telemetry', lambda: _telemetry())
    status = safety.get_safety_status(
        str(tmp_path / 'thresholds.json'),
        telemetry_fn=_boom,
        job_status_fn=_boom,
        schedule_pause_fn=_boom,
        error_logs_fn=_boom,
    )
    assert status['protection_level'] == 2
    assert status['stability'] == {'queue_depth': 0, 'oom_count': 0, 'failed_jobs_5m': 0, 'blocked_launches': 0}
    assert status['emergency_stop_active'] is False


def test_get_safety_status_reports_an_emergency_halt_when_the_schedule_is_paused(safety, tmp_path, monkeypatch):
    monkeypatch.setattr(safety, '_get_cpu_temp_local', lambda: None)
    status = safety.get_safety_status(
        str(tmp_path / 'thresholds.json'),
        telemetry_fn=lambda: _telemetry(),
        job_status_fn=lambda: None,
        schedule_pause_fn=lambda: {'paused': True},
        error_logs_fn=lambda: None,
    )
    assert status['protection_level'] == 4
    assert status['emergency_stop_active'] is True
    assert status['circuit_breaker_active'] is True
    assert status['recovery_state']['state'] == 'awaiting_admin_l4'
    assert status['can_resume_schedule'] is False
    assert 'L4 staged recovery' in status['resume_blocked_reason']
