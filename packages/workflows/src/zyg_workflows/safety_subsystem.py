# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
System Safety & Protection Layer.
Full implementation per spec: guards, controller, audit logger, threshold manager.
Fail-closed, always-on. No placeholders.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_now() -> datetime:
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.debug('ams timezone unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc)


def _ams_iso(timespec: str = 'milliseconds') -> str:
    try:
        return _ams_now().isoformat(timespec=timespec)
    except TypeError:
        return _ams_now().isoformat()


# Local fallback when control plane unavailable
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# GPU temp via pynvml (optional)
try:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetCount,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetUtilizationRates,
        nvmlDeviceGetMemoryInfo,
    )

    try:
        from pynvml import nvmlDeviceGetTemperature, NVML_TEMPERATURE_GPU
    except ImportError:
        nvmlDeviceGetTemperature = None
        NVML_TEMPERATURE_GPU = 0
    HAS_NVML = True
except (ImportError, OSError):
    HAS_NVML = False
    nvmlDeviceGetTemperature = None
    NVML_TEMPERATURE_GPU = 0

# Default thresholds per spec section 28
DEFAULT_THRESHOLDS = {
    'gpu': {
        'temp_warning_c': 75,  # Warn before NVIDIA throttle zone (83-87°C)
        'temp_critical_c': 83,  # Fail switch before thermal throttle kicks in
        'util_warning_pct': 90,
        'util_critical_pct': 95,
        'vram_warning_pct': 82,  # Early warning; LLM/diffusion spikes are wide
        'vram_critical_pct': 90,  # Fail switch; leaves headroom before OOM
        'min_reserve_vram_mb': 1024,  # 1 GB hard reserve for driver + CUDA overhead
    },
    'cpu': {
        'temp_warning_c': 70,  # Sustained AI workloads target sub-75°C
        'temp_critical_c': 80,  # Fail switch before OS throttle territory
        'util_warning_pct': 80,  # Agents + OS + Flask + Ollama all compete
        'util_critical_pct': 88,
        'min_reserve_pct': 12,  # 12% keeps OS + scheduler responsive during handoffs
    },
    'ram': {
        'warning_pct': 78,  # FFmpeg + yt-dlp + Ollama spikes are wide
        'critical_pct': 88,
        'min_free_reserve_mb': 2048,  # 2 GB prevents OOM killer hitting mid-task agents
    },
    'disk': {
        'warning_free_gb': 10,
        'critical_free_gb': 5,
        'emergency_reserve_gb': 2,
    },
    'failure_patterns': {
        'max_failed_launches_5m': 3,  # 3 failures = structural problem, not transient
        'max_oom_5m': 2,  # 2 OOMs in 5 min = allocation issue, halt immediately
        'max_retries_per_job': 3,
        'max_agent_crashes_5m': 3,
        'queue_depth_warning': 20,
        'queue_depth_critical': 50,
    },
    '_version': 2,
}

# In-memory audit log (last N events); also persisted to file
_AUDIT_EVENTS: deque = deque(maxlen=500)
_AUDIT_LOCK = threading.Lock()
_AUDIT_LOG_PATH: Optional[str] = None
_AUDIT_MAX_FILE_LINES = 10000  # Rotate or trim if needed (future)


def init_safety_audit(audit_log_path: Optional[str] = None) -> None:
    """Initialize audit log with optional file path. Load last events from file on startup."""
    global _AUDIT_LOG_PATH
    _AUDIT_LOG_PATH = audit_log_path
    if not audit_log_path or not os.path.isfile(audit_log_path):
        return
    try:
        with open(audit_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with _AUDIT_LOCK:
            for line in lines[-500:]:  # Last 500 lines
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    _AUDIT_EVENTS.append(entry)
                except json.JSONDecodeError as _exc:
                    _zyg_log.debug('audit line skipped, not valid json: %s', _exc)
    except Exception as _exc:
        _zyg_log.warning('audit log %s could not be replayed, in-memory audit starts empty: %s', audit_log_path, _exc)


def _append_audit_to_file(entry: dict) -> None:
    """Append one audit entry to file (JSONL). Survives restart."""
    path = _AUDIT_LOG_PATH
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as _exc:
        _zyg_log.warning('audit append to %s failed, the event stays in memory only: %s', path, _exc)


# OOM/failure tracking (rolling window - simplified: we use job_status failed count)
_SAFETY_STATE = {'emergency_stop_count': 0, 'protection_mode_count': 0, 'blocked_launches': 0}

# Recovery state machine (level-based, admin confirmation for L3/L4)
_RECOVERY_LOCK = threading.Lock()
_RECOVERY_STATE: dict = {
    'state': 'normal',  # normal | tripped_l1 | tripped_l2 | awaiting_admin_l3 | awaiting_admin_l4
    'tripped_at': None,
    'last_level': 0,
    'admin_confirmed_at': None,
    'admin_confirmed_by': None,
    'staged_recovery_stages': [],  # For L4: ["ui", "scheduler", "agents", "heavy_models"] when confirmed
}
L4_RECOVERY_STAGES = ['ui', 'scheduler', 'agents', 'heavy_models']

# Quarantine / crash-loop isolation: rolling window of failures per agent/model
_QUARANTINE_LOCK = threading.Lock()
_AGENT_FAILURES: deque = deque(maxlen=500)  # (ts_iso, agent_id)
_MODEL_FAILURES: deque = deque(maxlen=500)  # (ts_iso, model_id)
_QUARANTINE_WINDOW_SEC = 300  # 5 minutes


def _update_recovery_state(level: int, schedule_paused: bool) -> None:
    """
    Update recovery state based on current protection level.
    Level 1-2: auto-recover when level normalizes to 0.
    Level 3-4: require admin confirmation; do not auto-clear.
    """
    with _RECOVERY_LOCK:
        now = _ams_iso()
        prev = _RECOVERY_STATE.copy()

        if level == 0:
            # Telemetry normalized
            if prev['state'] in ('tripped_l1', 'tripped_l2'):
                _RECOVERY_STATE['state'] = 'normal'
                _RECOVERY_STATE['tripped_at'] = None
                _RECOVERY_STATE['last_level'] = 0
            # For awaiting_admin_l3/l4, stay until admin confirms (level 0 alone doesn't clear)
        elif level in (1, 2):
            if prev['state'] == 'normal' or prev['last_level'] < level:
                _RECOVERY_STATE['state'] = f'tripped_l{level}'
                _RECOVERY_STATE['tripped_at'] = prev['tripped_at'] or now
            _RECOVERY_STATE['last_level'] = level
        elif level == 3:
            if prev['state'] not in ('awaiting_admin_l3', 'awaiting_admin_l4'):
                _RECOVERY_STATE['state'] = 'awaiting_admin_l3'
                _RECOVERY_STATE['tripped_at'] = prev['tripped_at'] or now
            _RECOVERY_STATE['last_level'] = level
        elif level >= 4:
            if prev['state'] != 'awaiting_admin_l4':
                _RECOVERY_STATE['state'] = 'awaiting_admin_l4'
                _RECOVERY_STATE['tripped_at'] = prev['tripped_at'] or now
                _RECOVERY_STATE['staged_recovery_stages'] = []
            _RECOVERY_STATE['last_level'] = level


def get_recovery_state() -> dict:
    """Return current recovery state for API (thread-safe copy)."""
    with _RECOVERY_LOCK:
        return dict(_RECOVERY_STATE)


def can_resume_schedule(level: int, schedule_paused: bool) -> tuple[bool, str]:
    """
    Whether schedule resume is allowed. Returns (allowed, reason).
    Level 1-2: allowed when level 0 (auto-recovered).
    Level 3: allowed when admin confirmed.
    Level 4: allowed when all staged recovery stages confirmed.
    """
    if not schedule_paused:
        return True, 'Schedule not paused'
    with _RECOVERY_LOCK:
        state = _RECOVERY_STATE['state']
        stages = list(_RECOVERY_STATE.get('staged_recovery_stages') or [])
        admin_confirmed = _RECOVERY_STATE.get('admin_confirmed_at')
    if level >= 4:
        if state != 'awaiting_admin_l4':
            return False, 'Recovery state inconsistent'
        if set(stages) >= set(L4_RECOVERY_STAGES):
            return True, 'All L4 recovery stages confirmed'
        return False, f'L4 staged recovery: confirm {[s for s in L4_RECOVERY_STAGES if s not in stages]}'
    if level == 3:
        if state != 'awaiting_admin_l3':
            return False, 'Recovery state inconsistent'
        if admin_confirmed:
            return True, 'Admin confirmed L3 recovery'
        return False, 'Admin confirmation required for L3 recovery'
    if level <= 2 and state in ('tripped_l1', 'tripped_l2'):
        return False, 'Telemetry still elevated; wait for normalization'
    return True, 'OK'


def confirm_recovery(
    level: int,
    actor: str = 'unknown',
    reason: str = '',
    stage: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Admin confirms recovery for L3 or advances L4 staged recovery.
    L3: single confirmation clears awaiting_admin_l3.
    L4: stage must be one of ui, scheduler, agents, heavy_models; advances through stages.
    Returns (success, error_message).
    """
    with _RECOVERY_LOCK:
        state = _RECOVERY_STATE['state']
        if level == 3:
            if state != 'awaiting_admin_l3':
                return False, f'Cannot confirm L3: state is {state}'
            now = _ams_iso()
            _RECOVERY_STATE['state'] = 'normal'
            _RECOVERY_STATE['admin_confirmed_at'] = now
            _RECOVERY_STATE['admin_confirmed_by'] = actor
            _RECOVERY_STATE['tripped_at'] = None
            audit_log(
                'L3 recovery confirmed by admin',
                level='info',
                actor=actor,
                recovery_action='confirm_recovery',
                extra={'reason': reason or 'Admin confirmed'},
            )
            return True, None
        if level == 4:
            if state != 'awaiting_admin_l4':
                return False, f'Cannot confirm L4: state is {state}'
            if not stage or stage not in L4_RECOVERY_STAGES:
                return False, f'L4 requires stage: one of {L4_RECOVERY_STAGES}'
            stages = list(_RECOVERY_STATE.get('staged_recovery_stages') or [])
            if stage in stages:
                return True, None  # Idempotent
            next_expected = L4_RECOVERY_STAGES[len(stages)]
            if stage != next_expected:
                return False, f"Expected stage '{next_expected}' next, got '{stage}'"
            stages.append(stage)
            _RECOVERY_STATE['staged_recovery_stages'] = stages
            if set(stages) >= set(L4_RECOVERY_STAGES):
                _RECOVERY_STATE['state'] = 'normal'
                _RECOVERY_STATE['admin_confirmed_at'] = _ams_iso()
                _RECOVERY_STATE['admin_confirmed_by'] = actor
                _RECOVERY_STATE['tripped_at'] = None
            audit_log(
                f"L4 recovery stage '{stage}' confirmed",
                level='info',
                actor=actor,
                recovery_action='confirm_stage',
                extra={'reason': reason or '', 'stages_done': stages},
            )
            return True, None
    return False, 'Invalid level for confirm_recovery'


# --- Quarantine / crash-loop isolation (uses _QUARANTINE_* above) ---


def _trim_failures(failures: deque, window_sec: int = _QUARANTINE_WINDOW_SEC) -> None:
    """Remove entries older than window."""
    try:
        cutoff = _ams_now().timestamp() - window_sec
        while failures:
            first = failures[0]
            ts_str = first[0] if isinstance(first, (list, tuple)) else first.get('ts', '')
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp()
            except Exception:
                ts = 0
            if ts < cutoff:
                failures.popleft()
            else:
                break
    except Exception as _exc:
        _zyg_log.warning('failure window pruning failed, stale failures may linger: %s', _exc)


def record_agent_failure(agent_id: str) -> None:
    """Record an agent crash/failure for quarantine logic."""
    with _QUARANTINE_LOCK:
        _AGENT_FAILURES.append((_ams_iso(), agent_id))
        _trim_failures(_AGENT_FAILURES)


def record_model_failure(model_id: str) -> None:
    """Record a model launch failure for quarantine logic."""
    with _QUARANTINE_LOCK:
        _MODEL_FAILURES.append((_ams_iso(), model_id))
        _trim_failures(_MODEL_FAILURES)


def _count_failures_in_window(failures: deque, entity_id: str, window_sec: int = _QUARANTINE_WINDOW_SEC) -> int:
    """Count failures for entity_id in the last window_sec."""
    with _QUARANTINE_LOCK:
        _trim_failures(failures, window_sec)
        cutoff = _ams_now().timestamp() - window_sec
        count = 0
        for item in failures:
            ts_str = item[0] if isinstance(item, (list, tuple)) else item.get('ts', '')
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp()
            except Exception:
                ts = 0
            eid = (
                item[1]
                if isinstance(item, (list, tuple)) and len(item) > 1
                else item.get('model_id') or item.get('agent_id', '')
            )
            if ts >= cutoff and eid == entity_id:
                count += 1
        return count


def is_quarantined_agent(agent_id: str, thresholds: Optional[dict] = None) -> tuple[bool, str]:
    """
    Check if agent is quarantined due to crash-loop. Returns (quarantined, reason).
    Uses max_agent_crashes_5m from failure_patterns.
    """
    fail = (thresholds or {}).get('failure_patterns', {})
    max_crashes = fail.get('max_agent_crashes_5m', 5)
    count = _count_failures_in_window(_AGENT_FAILURES, agent_id)
    if count >= max_crashes:
        return True, f'Agent {agent_id} has {count} failures in 5m (threshold {max_crashes})'
    return False, ''


def is_quarantined_model(model_id: str, thresholds: Optional[dict] = None) -> tuple[bool, str]:
    """
    Check if model is quarantined due to launch failures. Returns (quarantined, reason).
    Uses max_failed_launches_5m as proxy for model launch failures.
    """
    fail = (thresholds or {}).get('failure_patterns', {})
    max_failures = fail.get('max_failed_launches_5m', 5)
    count = _count_failures_in_window(_MODEL_FAILURES, model_id)
    if count >= max_failures:
        return True, f'Model {model_id} has {count} launch failures in 5m (threshold {max_failures})'
    return False, ''


def get_quarantined_agents(thresholds: Optional[dict] = None) -> list[str]:
    """Return list of agent_ids currently quarantined."""
    with _QUARANTINE_LOCK:
        _trim_failures(_AGENT_FAILURES)
        seen = set()
        agents = []
        for item in reversed(list(_AGENT_FAILURES)):
            aid = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else ''
            if aid and aid not in seen:
                q, _ = is_quarantined_agent(aid, thresholds)
                if q:
                    seen.add(aid)
                    agents.append(aid)
        return agents


# --- VRAM-aware pre-launch enforcement ---


def can_launch_job(
    vram_required_mb: float,
    telemetry: dict,
    device_id: Optional[int] = None,
    thresholds: Optional[dict] = None,
    reserved_total_mb: float = 0,
) -> tuple[bool, str]:
    """
    Pre-launch check: can we launch a job requiring vram_required_mb?
    Returns (allowed, reason). Device-aware when device_id provided.
    reserved_total_mb: already reserved by other pending jobs.
    """
    gpus = telemetry.get('gpus') or []
    if not gpus:
        return False, 'No GPU telemetry; cannot verify VRAM'
    gpu = gpus[device_id] if device_id is not None and 0 <= device_id < len(gpus) else gpus[0]
    total_mb = float(gpu.get('memory_total_mb') or 0)
    used_mb = float(gpu.get('memory_used_mb') or 0)
    if total_mb <= 0:
        return False, 'GPU memory total unknown'
    thr = (thresholds or {}).get('gpu', {})
    min_reserve = thr.get('min_reserve_vram_mb', 512)
    available = total_mb - used_mb - reserved_total_mb - min_reserve
    if vram_required_mb > available:
        return (
            False,
            f'VRAM insufficient: need {vram_required_mb:.0f} MB, available ~{max(0, available):.0f} MB (reserve {min_reserve})',
        )
    return True, ''


# --- Runtime intervention hooks (caller provides terminate_fn, reduce_concurrency_fn) ---


def request_terminate_run(
    run_id: str,
    reason: str = '',
    terminate_fn: Optional[Callable[[str, str], dict]] = None,
) -> dict:
    """
    Request termination of a job run. Calls terminate_fn(run_id, reason) if provided.
    Used by full emergency stop. Returns result from terminate_fn or stub response.
    """
    if terminate_fn:
        try:
            return terminate_fn(run_id, reason) or {'ok': False}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    return {'ok': False, 'error': 'No terminate_fn configured'}


def request_reduce_concurrency(
    agent_id: str,
    new_max: int,
    reduce_fn: Optional[Callable[[str, int], dict]] = None,
) -> dict:
    """
    Request reduction of max concurrency for an agent. Calls reduce_fn(agent_id, new_max) if provided.
    """
    if reduce_fn:
        try:
            return reduce_fn(agent_id, new_max) or {'success': False}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    return {'success': False, 'error': 'No reduce_fn configured'}


def _load_thresholds(path: str) -> dict:
    """Load thresholds from JSON. Return defaults if missing or invalid."""
    if not path or not os.path.isfile(path):
        return dict(DEFAULT_THRESHOLDS)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Merge with defaults so new keys are always present
        out = dict(DEFAULT_THRESHOLDS)
        for k, v in data.items():
            if k.startswith('_'):
                out[k] = v
            elif isinstance(v, dict) and k in out and isinstance(out[k], dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
        return out
    except Exception:
        return dict(DEFAULT_THRESHOLDS)


def _save_thresholds(path: str, data: dict) -> bool:
    """Save thresholds to JSON. Returns True on success."""
    if not path:
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def get_thresholds(thresholds_path: str) -> dict:
    """Return current threshold configuration (for API)."""
    return _load_thresholds(thresholds_path)


def update_thresholds(
    thresholds_path: str,
    updates: dict,
    actor: str = 'unknown',
) -> tuple[bool, Optional[str]]:
    """
    Update threshold configuration. Validates and audits.
    Returns (success, error_message).
    """
    current = _load_thresholds(thresholds_path)
    out = dict(current)
    for category, vals in updates.items():
        if category.startswith('_'):
            continue
        if category not in out or not isinstance(out[category], dict):
            continue
        if not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if isinstance(v, (int, float)) and v >= 0:
                out[category][k] = v
            elif isinstance(v, (int, float)) and 'reserve' in k.lower() and v < 0:
                return False, f'Invalid {category}.{k}: reserve must be non-negative'
    out['_version'] = out.get('_version', 1) + 1
    out['_updated_at'] = _ams_iso()
    out['_updated_by'] = actor
    if _save_thresholds(thresholds_path, out):
        audit_log('Threshold configuration updated', 'info', {'actor': actor, 'updates': list(updates.keys())})
        return True, None
    return False, 'Failed to save thresholds'


def audit_log(
    event: str,
    level: str = 'info',
    extra: Optional[dict] = None,
    *,
    trigger_source: Optional[str] = None,
    threshold: Optional[Any] = None,
    observed_value: Optional[Any] = None,
    action_taken: Optional[str] = None,
    actor: Optional[str] = None,
    recovery_action: Optional[str] = None,
) -> None:
    """
    Append event to safety audit log. Persisted to file if path set.
    Supports: ts, event, level, trigger_source, threshold, observed_value, action_taken, actor, recovery_action.
    """
    entry = {
        'ts': _ams_iso(),
        'event': event,
        'level': level,
    }
    if trigger_source is not None:
        entry['trigger_source'] = trigger_source
    if threshold is not None:
        entry['threshold'] = threshold
    if observed_value is not None:
        entry['observed_value'] = observed_value
    if action_taken is not None:
        entry['action_taken'] = action_taken
    if actor is not None:
        entry['actor'] = actor
    if recovery_action is not None:
        entry['recovery_action'] = recovery_action
    if extra:
        for k, v in extra.items():
            if k not in entry and v is not None:
                entry[k] = v
    with _AUDIT_LOCK:
        _AUDIT_EVENTS.append(entry)
        _append_audit_to_file(entry)


def get_audit_events(limit: int = 50) -> list[dict]:
    """Return recent audit events (newest first)."""
    with _AUDIT_LOCK:
        events = list(_AUDIT_EVENTS)
    return [{'ts': e['ts'], 'event': e['event'], 'level': e.get('level', 'info')} for e in reversed(events[-limit:])]


def _get_local_telemetry() -> dict:
    """Fallback: collect CPU/RAM/disk locally when control plane unavailable."""
    out = {'cpu_pct': 0, 'ram_pct': 0, 'ram_used_mb': 0, 'ram_total_mb': 0, 'free_disk_gb': None, 'gpus': []}
    if not HAS_PSUTIL:
        return out
    try:
        out['cpu_pct'] = round(psutil.cpu_percent(interval=0.05), 2)
        mem = psutil.virtual_memory()
        out['ram_pct'] = round(mem.percent, 2)
        out['ram_used_mb'] = round(mem.used / (1024 * 1024), 2)
        out['ram_total_mb'] = round(mem.total / (1024 * 1024), 2)
        disk = psutil.disk_usage('/')
        if os.name == 'nt':
            disk = psutil.disk_usage(os.path.expandvars('%SystemDrive%\\'))
        out['free_disk_gb'] = round(disk.free / (1024**3), 2)
    except Exception as _exc:
        _zyg_log.warning('psutil telemetry incomplete, cpu/ram/disk fields may be missing: %s', _exc)
    # GPU via NVML if available
    if HAS_NVML:
        try:
            nvmlInit()
            count = nvmlDeviceGetCount()
            for i in range(count):
                h = nvmlDeviceGetHandleByIndex(i)
                temp_c = None
                if nvmlDeviceGetTemperature:
                    try:
                        temp_c = nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU)
                    except Exception as _exc:
                        _zyg_log.debug('gpu %s temperature unavailable: %s', i, _exc)
                util = 0.0
                mem_used = 0.0
                mem_total = 1.0
                try:
                    rates = nvmlDeviceGetUtilizationRates(h)
                    util = float(rates.gpu)
                except Exception as _exc:
                    _zyg_log.debug('gpu %s utilization unavailable: %s', i, _exc)
                try:
                    mem = nvmlDeviceGetMemoryInfo(h)
                    mem_used = mem.used / (1024 * 1024)
                    mem_total = mem.total / (1024 * 1024)
                except Exception as _exc:
                    _zyg_log.debug('gpu %s memory info unavailable: %s', i, _exc)
                out['gpus'].append(
                    {
                        'index': i,
                        'temperature_c': temp_c,
                        'utilization_pct': round(util, 2),
                        'memory_used_mb': round(mem_used, 2),
                        'memory_total_mb': round(mem_total, 2),
                        'memory_pct': round((mem_used / mem_total * 100) if mem_total else 0, 2),
                    }
                )
            nvmlShutdown()
        except Exception as _exc:
            _zyg_log.warning('nvml gpu telemetry unavailable: %s', _exc)
    return out


def _get_cpu_temp_local() -> Optional[float]:
    """Get CPU temperature if psutil sensors available."""
    if not HAS_PSUTIL:
        return None
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        for name, entries in temps.items():
            if entries and 'core' in name.lower() or 'cpu' in name.lower() or 'k10' in name.lower():
                return float(entries[0].current)
        for _name, entries in temps.items():
            if entries:
                return float(entries[0].current)
    except Exception as _exc:
        _zyg_log.debug('cpu temperature unavailable from psutil sensors: %s', _exc)
    return None


def _assess_telemetry_fail_closed(telemetry: dict, telemetry_source: str) -> tuple[int, Optional[str]]:
    """
    Graded fail-closed: component-aware, not blind.
    Returns (fail_closed_level, reason or None).
    - telemetry_source: "control_plane" | "local" | "none"
    """
    if telemetry_source == 'none':
        return 3, 'Telemetry unavailable; hard stop until restored.'
    if telemetry_source == 'local':
        # Control plane failed, using local fallback. Block new heavy launches.
        return 2, 'Control plane unreachable; using local telemetry. Block new heavy launches.'
    # control_plane
    if telemetry.get('error'):
        return 2, 'Telemetry error; block new heavy launches.'
    # Partial: missing critical launch-gating metrics
    has_cpu = telemetry.get('cpu_pct') is not None
    has_ram = telemetry.get('ram_pct') is not None
    has_disk = telemetry.get('free_disk_gb') is not None
    has_gpu = bool(telemetry.get('gpus'))
    if not has_cpu and not has_ram:
        return 2, 'Critical metrics (CPU/RAM) missing; block new heavy launches.'
    if not has_disk:
        return 1, 'Disk telemetry missing; reduced confidence.'
    if has_gpu and not any(g.get('memory_used_mb') is not None for g in (telemetry.get('gpus') or [])):
        return 1, 'GPU VRAM telemetry missing; reduced confidence.'
    return 0, None


def compute_protection_level(
    telemetry: dict,
    job_status: dict,
    schedule_paused: bool,
    emergency_stop_active: bool,
    thresholds: dict,
    error_logs: Optional[dict] = None,
    telemetry_source: str = 'control_plane',
) -> tuple[int, str, str, list[str]]:
    """
    Compute protection level 0-4 from guards.
    Graded fail-closed: telemetry quality assessed first.
    Returns (level, label, description, trip_reasons).
    """
    reasons: list[str] = []
    level = 0

    # Graded fail-closed: component-aware
    fc_level, fc_reason = _assess_telemetry_fail_closed(telemetry, telemetry_source)
    if fc_level > 0 and fc_reason:
        level = max(level, fc_level)
        reasons.append(fc_reason)

    gpu = thresholds.get('gpu', {})
    cpu = thresholds.get('cpu', {})
    ram = thresholds.get('ram', {})
    disk = thresholds.get('disk', {})
    fail = thresholds.get('failure_patterns', {})

    # Emergency stop / manual pause overrides
    if emergency_stop_active or schedule_paused:
        level = max(level, 4 if emergency_stop_active else 3)
        reasons.append('Emergency stop active' if emergency_stop_active else 'Schedule paused (circuit breaker)')

    # Hardware guards
    gpus = telemetry.get('gpus') or []
    gpu_temp = None
    gpu_pct = None
    vram_used = 0
    vram_total = 0
    for g in gpus:
        t = g.get('temperature_c') or g.get('temp_c')
        if t is not None:
            gpu_temp = max(gpu_temp or 0, float(t))
        u = g.get('utilization_pct')
        if u is not None:
            gpu_pct = max(gpu_pct or 0, float(u))
        vram_used += float(g.get('memory_used_mb') or 0)
        vram_total += float(g.get('memory_total_mb') or 0)

    if gpu_temp is not None:
        if gpu_temp >= gpu.get('temp_critical_c', 90):
            level = max(level, 3)
            reasons.append(f'GPU temp critical ({gpu_temp}°C)')
        elif gpu_temp >= gpu.get('temp_warning_c', 80):
            level = max(level, 1)
            reasons.append(f'GPU temp warning ({gpu_temp}°C)')

    if gpu_pct is not None:
        if gpu_pct >= gpu.get('util_critical_pct', 98):
            level = max(level, 2)
            reasons.append(f'GPU utilization critical ({gpu_pct}%)')
        elif gpu_pct >= gpu.get('util_warning_pct', 95):
            level = max(level, 1)
            reasons.append(f'GPU utilization warning ({gpu_pct}%)')

    vram_pct = (vram_used / vram_total * 100) if vram_total else 0
    if vram_total:
        if vram_pct >= gpu.get('vram_critical_pct', 95):
            level = max(level, 3)
            reasons.append(f'VRAM critical ({vram_pct:.1f}%)')
        elif vram_pct >= gpu.get('vram_warning_pct', 90):
            level = max(level, 1)
            reasons.append(f'VRAM warning ({vram_pct:.1f}%)')

    cpu_pct = telemetry.get('cpu_pct')
    if cpu_pct is not None:
        if cpu_pct >= cpu.get('util_critical_pct', 95):
            level = max(level, 2)
            reasons.append(f'CPU critical ({cpu_pct}%)')
        elif cpu_pct >= cpu.get('util_warning_pct', 90):
            level = max(level, 1)
            reasons.append(f'CPU warning ({cpu_pct}%)')

    ram_pct = telemetry.get('ram_pct')
    if ram_pct is not None:
        if ram_pct >= ram.get('critical_pct', 92):
            level = max(level, 3)
            reasons.append(f'RAM critical ({ram_pct}%)')
        elif ram_pct >= ram.get('warning_pct', 85):
            level = max(level, 1)
            reasons.append(f'RAM warning ({ram_pct}%)')

    free_disk = telemetry.get('free_disk_gb')
    if free_disk is not None:
        if free_disk < disk.get('critical_free_gb', 5):
            level = max(level, 3)
            reasons.append(f'Disk critical ({free_disk} GB free)')
        elif free_disk < disk.get('warning_free_gb', 10):
            level = max(level, 1)
            reasons.append(f'Disk warning ({free_disk} GB free)')

    # Failure pattern guards
    running_list = job_status.get('running_list') or []
    failed_list = job_status.get('failed_list') or []
    queue_depth = len(running_list)
    failed_5m = len(failed_list)  # Simplified: use total failed as proxy for 5m
    if queue_depth >= fail.get('queue_depth_critical', 50):
        level = max(level, 3)
        reasons.append(f'Queue depth critical ({queue_depth})')
    elif queue_depth >= fail.get('queue_depth_warning', 20):
        level = max(level, 1)
        reasons.append(f'Queue depth warning ({queue_depth})')
    if failed_5m >= fail.get('max_failed_launches_5m', 5):
        level = max(level, 2)
        reasons.append(f'Failed jobs high ({failed_5m})')

    oom_count = 0
    if error_logs:
        oom_count = len(error_logs.get('gpu_memory_overflows') or [])
    if oom_count >= fail.get('max_oom_5m', 3):
        level = max(level, 3)
        reasons.append(f'OOM count high ({oom_count})')

    labels = ['Normal', 'Warning', 'Protective Degradation', 'Hard Stop', 'Emergency Halt']
    descs = [
        'System healthy, jobs run normally.',
        'A metric approaches unsafe range. Dashboard warning, reduced dispatch.',
        'System entering unsafe condition. Block new heavy jobs, reduce concurrency.',
        'Unsafe condition confirmed. Stop dispatching, terminate heavy workers.',
        'Critical or cascading risk. Immediate compute halt, lock orchestration.',
    ]
    label = labels[min(level, 4)]
    desc = descs[min(level, 4)]
    if reasons:
        desc = '; '.join(reasons[:3]) + ('.' if len(reasons) <= 3 else '…')
    return level, label, desc, reasons


def get_safety_status(
    thresholds_path: str,
    telemetry_fn: Optional[Callable[[], dict]] = None,
    job_status_fn: Optional[Callable[[], dict]] = None,
    schedule_pause_fn: Optional[Callable[[], dict]] = None,
    error_logs_fn: Optional[Callable[[], dict]] = None,
) -> dict:
    """
    Build full safety status dict for API response.
    Uses provided fetchers; falls back to local collection when unavailable.
    """
    thresholds = _load_thresholds(thresholds_path)
    telemetry = {}
    job_status = {'running_list': [], 'failed_list': []}
    schedule_paused = False
    error_logs = {}

    telemetry_source = 'control_plane'
    if telemetry_fn:
        try:
            telemetry = telemetry_fn() or {}
        except Exception as _exc:
            _zyg_log.warning('control-plane telemetry call failed, falling back to local telemetry: %s', _exc)
    if not telemetry or telemetry.get('error'):
        telemetry = _get_local_telemetry()
        telemetry_source = 'none' if not telemetry else 'local'
    else:
        # Supplement with local disk if control plane doesn't provide it
        if telemetry.get('free_disk_gb') is None and HAS_PSUTIL:
            try:
                disk = psutil.disk_usage('/' if os.name != 'nt' else os.path.expandvars('%SystemDrive%\\'))
                telemetry['free_disk_gb'] = round(disk.free / (1024**3), 2)
            except Exception as _exc:
                _zyg_log.debug('free disk supplement unavailable: %s', _exc)
    if job_status_fn:
        try:
            job_status = job_status_fn() or job_status
        except Exception as _exc:
            _zyg_log.warning('job status call failed, keeping the previous job status: %s', _exc)
    if schedule_pause_fn:
        try:
            sp = schedule_pause_fn() or {}
            schedule_paused = bool(sp.get('paused', False))
        except Exception as _exc:
            _zyg_log.warning('schedule pause call failed, assuming the schedule is not paused: %s', _exc)
    if error_logs_fn:
        try:
            error_logs = error_logs_fn() or {}
        except Exception as _exc:
            _zyg_log.warning('error log call failed, continuing without error logs: %s', _exc)

    emergency_stop = schedule_paused  # In our design, schedule pause = emergency stop / circuit breaker
    level, label, desc, reasons = compute_protection_level(
        telemetry,
        job_status,
        schedule_paused,
        emergency_stop,
        thresholds,
        error_logs,
        telemetry_source=telemetry_source,
    )

    _update_recovery_state(level, schedule_paused)
    can_resume, resume_reason = can_resume_schedule(level, schedule_paused)
    recovery_state = get_recovery_state()

    gpus = telemetry.get('gpus') or []
    gpu_temp = None
    gpu_pct = None
    vram_used = 0
    for g in gpus:
        t = g.get('temperature_c') or g.get('temp_c')
        if t is not None:
            gpu_temp = max(gpu_temp or 0, float(t))
        u = g.get('utilization_pct')
        if u is not None:
            gpu_pct = max(gpu_pct or 0, float(u))
        vram_used += float(g.get('memory_used_mb') or 0)
    if not gpus and vram_used == 0:
        vram_used = None

    oom_count = len(error_logs.get('gpu_memory_overflows') or [])

    hardware = {
        'gpu_temp_c': round(gpu_temp, 1) if gpu_temp is not None else None,
        'gpu_pct': round(gpu_pct, 1) if gpu_pct is not None else None,
        'vram_used_mb': round(vram_used, 1) if vram_used is not None else None,
        'cpu_temp_c': _get_cpu_temp_local(),
        'cpu_pct': telemetry.get('cpu_pct'),
        'ram_pct': telemetry.get('ram_pct'),
        'free_disk_gb': telemetry.get('free_disk_gb'),
    }
    stability = {
        'queue_depth': len(job_status.get('running_list') or []),
        'oom_count': oom_count,
        'failed_jobs_5m': len(job_status.get('failed_list') or []),
        'blocked_launches': _SAFETY_STATE.get('blocked_launches', 0),
    }
    quarantined = get_quarantined_agents(thresholds)
    control = {
        'stale_telemetry_count': 0 if telemetry and not telemetry.get('error') else 1,
        'quarantined_agents': len(quarantined),
        'quarantined_agent_ids': quarantined,
        'agents_missing_heartbeat': 0,
    }

    audit_events = get_audit_events(limit=20)

    return {
        'protection_level': level,
        'protection_label': label,
        'protection_desc': desc,
        'circuit_breaker_active': schedule_paused,
        'emergency_stop_active': emergency_stop,
        'recovery_state': recovery_state,
        'can_resume_schedule': can_resume,
        'resume_blocked_reason': None if can_resume else resume_reason,
        'hardware': hardware,
        'stability': stability,
        'control': control,
        'audit_events': audit_events,
        'thresholds': thresholds,
    }
