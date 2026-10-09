# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > System — live hardware, services, probe and disks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from zyg_workflows.bin import exe
from zyg_workflows.paths import ZYG_COMFY_URL, ZYG_OLLAMA_URL, ZYG_SESSION_TREE_URL

from .constants import HEALTH_LOG, _zyg_log
from .helpers import _http_json, _iso, _ts
from .runs import _window
from .llm import _int

# ── system: live hardware, services, probe, disks ────────────────────────────

SERVICES = (
    # label, unit, scope, port
    ('Workflows GUI', 'crewai-gui.service', 'system', 5000),
    ('ComfyUI', 'comfyui.service', 'system', 8188),
    ('Ollama', 'ollama.service', 'system', 11434),
    ('Zero public', 'zero-public.service', 'system', 5001),
    ('Creator Nexus', 'creator-nexus.service', 'system', 8090),
    ('Kanban / Inspection', 'kanban-server.service', 'user', 8899),
    ('Session Tree', 'session-tree.service', 'user', 7100),
    ('Medusa', 'medusa.service', 'user', 5300),
    ('Medusa presets', 'medusa-presets.service', 'user', 5301),
    ('Skill proxy', 'skill-proxy.service', 'user', None),
    ('Hub launcher', None, None, 7000),
    ('Hub restart API', None, None, 7001),
)


def _systemctl_show(units, scope):
    if not units:
        return {}
    env = dict(os.environ)
    if scope == 'user':
        uid = os.getuid()
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
        env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{uid}/bus')
    try:
        cmd = (
            [exe('systemctl')]
            + (['--user'] if scope == 'user' else [])
            + [
                'show',
                '--no-pager',
                '-p',
                'Id,LoadState,ActiveState,SubState,MainPID,NRestarts,ActiveEnterTimestamp,Result',
            ]
            + list(units)
        )
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=4, env=env).stdout
    except Exception:
        return {}
    res = {}
    for block in out.strip().split('\n\n'):
        kv = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if kv.get('Id'):
            res[kv['Id']] = kv
    return res


def _listeners():
    try:
        import psutil

        found = {}
        for c in psutil.net_connections(kind='inet'):
            if c.status == psutil.CONN_LISTEN and c.laddr:
                if c.laddr.port not in found or (found[c.laddr.port] is None and c.pid):
                    found[c.laddr.port] = c.pid
        return found
    except Exception:
        return {}


def _proc_brief(pid):
    try:
        import psutil

        p = psutil.Process(pid)
        cmd = ' '.join(p.cmdline()[:3])
        return {'cmd': cmd[:110], 'age_s': round(time.time() - p.create_time())}
    except Exception:
        return {'cmd': '', 'age_s': None}


def _cgroup(pid):
    try:
        with open(f'/proc/{pid}/cgroup', encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def _services():
    units = {'system': [s[1] for s in SERVICES if s[2] == 'system'], 'user': [s[1] for s in SERVICES if s[2] == 'user']}
    shows = {scope: _systemctl_show(u, scope) for scope, u in units.items()}
    ports = _listeners()
    out = []
    for label, unit, scope, port in SERVICES:
        kv = shows.get(scope, {}).get(unit, {}) if unit else {}
        port_open = port in ports if port else None
        owner = ports.get(port) if port else None
        owner_in_unit = (unit in _cgroup(owner)) if (owner and unit) else None
        active = kv.get('ActiveState', '')
        detail = ''
        if not unit:
            state = 'ok' if port_open else 'down'
            detail = '' if port_open else f':{port} not listening (no systemd unit)'
        elif not kv or kv.get('LoadState') == 'not-found':
            state, detail = 'unknown', 'unit not found / systemctl unavailable'
        elif port_open and owner and owner_in_unit is False:
            # Checked BEFORE the unit state: on 2026-09-11 comfyui.service sat in
            # activating/auto-restart, exiting 1 every ~10 s against an orphan that held :8188 —
            # a "starting" label would have hidden exactly that.
            state = 'orphan'
            detail = (
                f'unit {active}/{kv.get("SubState", "")} but :{port} answers from pid {owner} outside the '
                'unit — no restart policy or probe recovery applies to it'
            )
            if kv.get('SubState') == 'auto-restart' or (_int(kv.get('NRestarts')) or 0) > 0:
                detail += f' · the unit is crash-looping against it (restart counter {kv.get("NRestarts")})'
        elif active == 'active':
            if port and not port_open:
                state, detail = 'degraded', f'unit active but :{port} is not listening'
            else:
                state = 'ok'
        elif active in ('activating', 'reloading'):
            state = 'starting'
        elif port_open:
            state = 'orphan'
            detail = (
                f'unit {active} ({kv.get("Result", "")}) but :{port} answers from a process outside the '
                'unit — no restart policy or probe recovery applies to it'
            )
        elif active == 'failed':
            state, detail = 'failed', f'unit failed ({kv.get("Result", "")})'
        else:
            state = 'stopped'
        row = {
            'label': label,
            'unit': unit,
            'scope': scope,
            'port': port,
            'state': state,
            'detail': detail,
            'active': active or None,
            'sub': kv.get('SubState'),
            'restarts': _int(kv.get('NRestarts')),
            'since': _iso(_ts_systemd(kv.get('ActiveEnterTimestamp'))),
            'port_pid': owner,
        }
        if state == 'orphan' and owner:
            row['owner'] = _proc_brief(owner)
        out.append(row)
    return out


def _ts_systemd(v):
    # "Thu 2026-09-10 23:35:26 CEST" -> epoch
    if not v:
        return None
    m = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', v)
    return _ts(m.group(1)) if m else None


def _health_events(since):
    ev = []
    try:
        with open(HEALTH_LOG, encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()[-2000:]
    except OSError as exc:
        return {'events': [], 'error': f'{type(exc).__name__}: {exc}'[:120]}
    for line in lines:
        m = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)$', line.strip())
        if not m:
            continue
        ts = _ts(m.group(1))
        if since and ts and ts < since:
            continue
        text = m.group(2)
        u = re.search(r'([\w@.-]+\.service)', text)
        kind = 'restart' if 'RESTART' in text else 'strike' if 'strike' in text.lower() else 'event'
        ev.append({'ts': _iso(ts), 'kind': kind, 'unit': u.group(1) if u else '', 'text': text[:160]})
    return {
        'events': ev[::-1],
        'restarts': sum(1 for e in ev if e['kind'] == 'restart'),
        'strikes': sum(1 for e in ev if e['kind'] == 'strike'),
        'log_last_write': _iso(os.path.getmtime(HEALTH_LOG)),
    }


def _disks():
    out, seen = [], set()
    try:
        import psutil

        parts = psutil.disk_partitions(all=False)
    except Exception:
        parts = []
    mounts = [
        p.mountpoint
        for p in parts
        if p.fstype not in ('squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'efivarfs', 'vfat')
        and not p.mountpoint.startswith(('/boot', '/snap', '/run', '/sys', '/proc', '/dev'))
    ] or ['/']
    for mnt in mounts:
        try:
            dev = os.stat(mnt).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            u = shutil.disk_usage(mnt)
        except OSError as _exc:
            _zyg_log.debug('mount %s not statable, left out of the disk roll-up: %s', mnt, _exc)
            continue
        used = u.total - u.free  # same convention as /api/disk_usage (reserved blocks count as used)
        out.append(
            {
                'mount': mnt,
                'total_gb': round(u.total / 2**30, 1),
                'free_gb': round(u.free / 2**30, 1),
                'used_pct': round(used / u.total * 100, 1) if u.total else None,
            }
        )
    return out


def section_system(days=7, now=None, telemetry=None):
    now = now or time.time()
    t = telemetry or {}
    gpus = []
    for g in t.get('gpus') or []:
        procs = sorted(g.get('processes') or [], key=lambda p: -(p.get('vram_mb') or 0))[:10]
        gpus.append(
            {
                k: g.get(k)
                for k in (
                    'index',
                    'capacity_pct',
                    'utilization_pct',
                    'clock_pct',
                    'memory_used_mb',
                    'memory_total_mb',
                    'power_w',
                    'power_limit_w',
                    'temperature_c',
                    'fan_pct',
                )
            }
            | {'processes': [{k: p.get(k) for k in ('pid', 'label', 'vram_mb', 'sm_pct', 'mem_pct')} for p in procs]}
        )
    comfy = _http_json(f'{ZYG_COMFY_URL}/queue')
    ollama = _http_json(f'{ZYG_OLLAMA_URL}/api/ps')
    tree = _http_json(f'{ZYG_SESSION_TREE_URL}/api/health')
    return {
        'telemetry': {
            'cpu_pct': t.get('cpu_pct_raw'),
            'cpu_cores_busy': round((t.get('cpu_pct') or 0) / 100, 1) if t.get('cpu_pct') is not None else None,
            'cpu_temp_c': t.get('cpu_temp_c'),
            'ram_pct': t.get('ram_pct'),
            'ram_used_mb': t.get('ram_used_mb'),
            'ram_total_mb': t.get('ram_total_mb'),
            'gpu_work_active': t.get('gpu_work_active'),
            'available': bool(t),
        },
        'gpus': gpus,
        'services': _services(),
        'health_probe': _health_events(_window(days, now)) | {'window_days': days},
        'disks': _disks(),
        'comfy_queue': {
            'running': len(comfy.get('queue_running') or []),
            'pending': len(comfy.get('queue_pending') or []),
        }
        if '_error' not in comfy
        else comfy,
        'ollama': {
            'models': [
                {
                    'name': m.get('name'),
                    'vram_mb': round((m.get('size_vram') or 0) / 2**20),
                    'expires': m.get('expires_at'),
                }
                for m in ollama.get('models') or []
            ]
        }
        if '_error' not in ollama
        else ollama,
        'session_tree': tree,
    }
