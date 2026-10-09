#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CPU/RAM process attribution, the disk sweep, the background telemetry sampler.

Lines 2840-3229 of the original module, verbatim. ``_PROC_CPU_PREV`` and
``_PROC_PREV_TS`` are rebound by ``_sample_top_processes`` through a ``global``
statement, so they and their only mutator stay together in this one module.
Importing this module starts the ``telemetry-sampler`` daemon thread, exactly as
the original line 3225 did.
"""

from zyg_dashboard.crewai_web_gui._bootstrap import (
    _TELEMETRY_CACHE,
    _ams_now,
    _runtime_path,
    _zyg_log,
    gui_state,
    os,
    shutil,
    threading,
    time,
)
from zyg_dashboard.crewai_web_gui.telemetry_gpu import _GPU_PROC_PATTERNS, _gpu_processes, _rotate_runtime_logs
from zyg_workflows.vram_manager import _comfy_vram_used_mb, _gpu_work_active

# ── CPU / RAM attribution: who is actually using the box ─────────────────────
# The sidebar and the Workflows rings both answer "where is it going?" from this
# table. CPU% here is an INSTANTANEOUS share on the 0-<cores>00 scale, computed
# from /proc cpu_times deltas between two samples — psutil's own default
# Process.cpu_percent() would hand back a lifetime average, which hides exactly
# the spike an operator is hunting (see the 1558%-vs-2266% case in the core-cap
# notes).
_PROC_LABELS: dict = {}  # pid -> friendly name

# Checked BEFORE _GPU_PROC_PATTERNS and only by _proc_label, so GPU attribution
# keeps its existing labels byte for byte. These are the processes that dominate
# the CPU and RAM tables on this box; without them the biggest rows read
# "MainThread" or "node", which names nothing.
_PROC_EXTRA_PATTERNS = [
    ('anthropic.claude-code', 'Claude Code (VS Code)'),
    ('session_tree_server', 'Session Tree board'),
    ('zero_public_server', 'Zero Public'),
    ('crewai_web_gui', 'Crews GUI'),
    ('kanban_server', 'Kanban server'),
    ('vscode-pylance', 'Pylance (VS Code)'),
    ('ms-python', 'VS Code Python extension'),
    ('extensionhostprocess', 'VS Code extension host'),
    ('vscode-server', 'VS Code server'),
]


def _proc_label(pid: int) -> str:
    """Friendly name for any pid. /proc is read once per pid, then cached."""
    lbl = _PROC_LABELS.get(pid)
    if lbl:
        return lbl
    try:
        with open(f'/proc/{pid}/comm') as _cf:
            comm = _cf.read().strip()
    except Exception:
        return f'pid {pid}'
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as _cf:
            cmd = _cf.read().replace(b'\x00', b' ').decode('utf-8', 'replace').strip()
    except Exception:
        cmd = ''
    low = cmd.lower()
    lbl = None
    for needle, name in _PROC_EXTRA_PATTERNS + _GPU_PROC_PATTERNS:
        if needle in low:
            lbl = name
            break
    if not lbl:
        # Name the program and the script it runs. `comm` alone is not enough: an
        # interpreter ("python", "node") names nothing, and a process that renamed
        # its main thread reports that name instead ("MainThread").
        _toks = cmd.split()
        _argv0 = os.path.basename(_toks[0]) if _toks else ''
        _prog = comm if (comm and _argv0 and comm.lower() in _argv0.lower()) else (_argv0 or comm)
        _script = ''
        for _tok in _toks[1:]:
            _b = os.path.basename(_tok)
            if _b.endswith(('.py', '.js', '.sh')) and not _tok.startswith('-'):
                _script = _b
                break
        lbl = f'{_prog} {_script}'.strip() if _script else (_prog or comm or f'pid {pid}')
    _PROC_LABELS[pid] = lbl
    if len(_PROC_LABELS) > 2048:  # bound the cache on a long-lived process
        _PROC_LABELS.clear()
    return lbl


_PROC_CPU_PREV: dict = {}  # pid -> cumulative cpu seconds at last sample
_PROC_PREV_TS: float = 0.0
_PROC_SAMPLE_EVERY = 3.0  # seconds between process-table sweeps
_DISK_SAMPLE_EVERY = 30.0  # seconds between filesystem sweeps


def _sample_top_processes(_ps, limit: int = 8) -> dict:
    """Top CPU and RAM consumers, shaped for the telemetry hover panels."""
    global _PROC_CPU_PREV, _PROC_PREV_TS
    now = time.time()
    dt = now - _PROC_PREV_TS
    cur: dict = {}
    rows: list = []
    for _p in _ps.process_iter(['pid', 'cpu_times', 'memory_info']):
        try:
            _info = _p.info
            _pid = _info.get('pid')
            _ct = _info.get('cpu_times')
            _mi = _info.get('memory_info')
            if _pid is None:
                continue
            _tot = (_ct.user + _ct.system) if _ct else None
            if _tot is not None:
                cur[_pid] = _tot
            _prev = _PROC_CPU_PREV.get(_pid)
            _pct = None
            if _prev is not None and _tot is not None and dt > 0.2:
                _pct = max(0.0, (_tot - _prev) / dt * 100.0)
            rows.append({'pid': _pid, 'cpu_pct': _pct, 'rss_mb': (_mi.rss / 1048576.0) if _mi else 0.0})
        except Exception as _exc:
            _zyg_log.debug('process %s sample skipped: %s', _pid, _exc)
            continue
    _PROC_CPU_PREV = cur
    _PROC_PREV_TS = now
    if not rows:
        return {}

    def _shape(_r):
        return {
            'pid': _r['pid'],
            'label': _proc_label(_r['pid']),
            'cpu_pct': round(_r['cpu_pct'] or 0.0, 1),
            'rss_mb': round(_r['rss_mb'], 1),
        }

    _by_cpu = sorted((_r for _r in rows if (_r['cpu_pct'] or 0) >= 0.5), key=lambda _r: -_r['cpu_pct'])[:limit]
    _by_ram = sorted((_r for _r in rows if _r['rss_mb'] >= 1.0), key=lambda _r: -_r['rss_mb'])[:limit]
    return {
        'cpu_procs': [_shape(_r) for _r in _by_cpu],
        'ram_procs': [_shape(_r) for _r in _by_ram],
        'proc_count': len(rows),
        'proc_sampled_at': round(now, 1),
    }


def _sample_disks(_ps) -> list:
    """Free/used space per real filesystem, largest first. One entry per device,
    so /home on the root LV is not counted twice."""
    out, seen = [], set()
    try:
        parts = _ps.disk_partitions(all=False)
    except Exception:
        parts = []
    mounts = [
        _pt.mountpoint
        for _pt in parts
        if _pt.fstype not in ('squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'efivarfs', 'vfat')
        and not _pt.mountpoint.startswith(('/boot', '/snap', '/run', '/sys', '/proc', '/dev'))
    ] or ['/']
    for _mnt in mounts:
        try:
            _dev = os.stat(_mnt).st_dev
            if _dev in seen:
                continue
            seen.add(_dev)
            _u = shutil.disk_usage(_mnt)
        except OSError as _exc:
            _zyg_log.debug('mount %s not statable, left out of the disk list: %s', _mnt, _exc)
            continue
        # shutil's `used` skips the ~5% root-reserved blocks while `free` is what
        # the user can actually write, so used/total would disagree with free/total.
        # Report from the user's point of view: anything not free counts as used.
        _used = _u.total - _u.free
        out.append(
            {
                'mount': _mnt,
                'total_gb': round(_u.total / 2**30, 1),
                'used_gb': round(_used / 2**30, 1),
                'free_gb': round(_u.free / 2**30, 1),
                'used_pct': round(_used / _u.total * 100, 1) if _u.total else 0.0,
            }
        )
    out.sort(key=lambda _d: -_d['total_gb'])
    return out


def _telemetry_sampler_loop():
    """Daemon thread: sample CPU/RAM/GPU every 2s, write to _TELEMETRY_CACHE."""
    import psutil as _ps
    import glob as _gl

    # Init pynvml once — keep handle open permanently, reuse _nv in loop
    _nvml_ok = False
    _nvml_handles = []
    _nv = None
    try:
        import pynvml as _nv

        _nv.nvmlInit()
        for _i in range(_nv.nvmlDeviceGetCount()):
            _nvml_handles.append(_nv.nvmlDeviceGetHandleByIndex(_i))
        _nvml_ok = True
    except Exception as _exc:
        _zyg_log.warning('nvml unavailable, the telemetry tick reports no gpu: %s', _exc)

    # Pre-warm psutil CPU counter (first call always returns 0.0)
    try:
        _ps.cpu_percent(interval=None)
    except Exception as _exc:
        _zyg_log.debug('psutil cpu counter not pre-warmed: %s', _exc)

    # Find CPU temp sysfs path once
    _cpu_temp_path = None
    try:
        for _zone in sorted(_gl.glob('/sys/class/thermal/thermal_zone*/type')):
            with open(_zone) as _zt:
                _ztype = _zt.read().strip()
            if _ztype in ('x86_pkg_temp', 'coretemp', 'cpu_thermal', 'cpu-thermal'):
                _cpu_temp_path = _zone.replace('/type', '/temp')
                break
    except Exception as _exc:
        _zyg_log.debug('no cpu thermal zone found: %s', _exc)

    _proc_sample_last = 0.0
    _disk_sample_last = 0.0

    while True:
        try:
            _rotate_runtime_logs()
            snap = {}
            # CPU — interval=None returns cached delta since last call (non-blocking)
            # Multiply by cpu_count so value is on 0–2400 scale matching the UI circles
            _raw_cpu = _ps.cpu_percent(interval=None)
            _ncpu = _ps.cpu_count() or 1
            snap['cpu_pct'] = round(_raw_cpu * _ncpu, 1)
            snap['cpu_pct_raw'] = round(_raw_cpu, 1)  # 0–100 normalised, for circle display
            # The UI must not guess the ceiling from a ratio: send the real thread
            # count and the 0–2400 scale it implies (24 threads on this box).
            snap['cpu_count'] = _ncpu
            snap['cpu_count_physical'] = _ps.cpu_count(logical=False) or _ncpu
            snap['cpu_pct_max'] = _ncpu * 100
            try:
                snap['load_avg'] = [round(_l, 2) for _l in os.getloadavg()]
            except Exception as _exc:
                _zyg_log.debug('load average unavailable: %s', _exc)
            _vm = _ps.virtual_memory()
            snap['ram_pct'] = _vm.percent
            snap['ram_used_mb'] = round(_vm.used / 1024 / 1024, 1)
            snap['ram_total_mb'] = round(_vm.total / 1024 / 1024, 1)

            # CPU temp — sysfs direct (fastest, no GIL contention)
            _cpu_temp = None
            if _cpu_temp_path:
                try:
                    with open(_cpu_temp_path) as _tf:
                        _cpu_temp = round(int(_tf.read().strip()) / 1000.0, 1)
                except Exception as _exc:
                    _zyg_log.debug('cpu temp sysfs read failed, trying psutil sensors: %s', _exc)
            if _cpu_temp is None:
                try:
                    _temps = _ps.sensors_temperatures()
                    for _key in ('coretemp', 'k10temp', 'cpu_thermal', 'acpitz'):
                        if _key in _temps and _temps[_key]:
                            _cpu_temp = round(_temps[_key][0].current, 1)
                            break
                except Exception as _exc:
                    _zyg_log.debug('psutil sensors gave no cpu temp: %s', _exc)
            if _cpu_temp is not None:
                snap['cpu_temp_c'] = _cpu_temp

            snap['comfy_vram_mb'] = _comfy_vram_used_mb()
            snap['gpu_work_active'] = _gpu_work_active()

            # GPU — reuse persistent handles, never re-init
            gpus = []
            if _nvml_ok:
                try:
                    for _i, _h in enumerate(_nvml_handles):
                        _util = _nv.nvmlDeviceGetUtilizationRates(_h).gpu
                        _mem = _nv.nvmlDeviceGetMemoryInfo(_h)
                        _temp = None
                        try:
                            _temp = float(_nv.nvmlDeviceGetTemperature(_h, _nv.NVML_TEMPERATURE_GPU))
                        except Exception as _exc:
                            _zyg_log.debug('gpu temperature unavailable: %s', _exc)
                        _fan_rpm = None
                        try:
                            _fan_rpm = int(_nv.nvmlDeviceGetFanSpeed(_h))
                        except Exception as _exc:
                            _zyg_log.debug('gpu fan speed unavailable: %s', _exc)
                        _power_w = None
                        try:
                            _power_w = round(_nv.nvmlDeviceGetPowerUsage(_h) / 1000, 1)
                        except Exception as _exc:
                            _zyg_log.debug('gpu power draw unavailable: %s', _exc)
                        _power_cap_w = None
                        try:
                            _power_cap_w = round(_nv.nvmlDeviceGetEnforcedPowerLimit(_h) / 1000, 1)
                        except Exception as _exc:
                            _zyg_log.debug('gpu power limit unavailable: %s', _exc)
                        # SM clock vs its max — the factor that turns a duty cycle
                        # into a capacity figure (see _gpu_processes above).
                        _clk, _clk_max, _clk_pct = None, None, None
                        try:
                            _clk = int(_nv.nvmlDeviceGetClockInfo(_h, _nv.NVML_CLOCK_SM))
                            _clk_max = int(_nv.nvmlDeviceGetMaxClockInfo(_h, _nv.NVML_CLOCK_SM))
                            if _clk_max > 0:
                                _clk_pct = round(_clk / _clk_max * 100, 1)
                        except Exception as _exc:
                            _zyg_log.debug('gpu sm clock unavailable, capacity falls back to utilisation: %s', _exc)
                        _capacity = round(float(_util) * _clk / _clk_max, 1) if _clk and _clk_max else float(_util)
                        gpus.append(
                            {
                                'index': _i,
                                'utilization_pct': float(_util),
                                'capacity_pct': _capacity,
                                'clock_sm_mhz': _clk,
                                'clock_sm_max_mhz': _clk_max,
                                'clock_pct': _clk_pct,
                                'memory_used_mb': round(_mem.used / 1024 / 1024, 1),
                                'memory_total_mb': round(_mem.total / 1024 / 1024, 1),
                                'temperature_c': _temp,
                                'fan_pct': _fan_rpm,
                                'power_w': _power_w,
                                'power_limit_w': _power_cap_w,
                                'processes': _gpu_processes(_nv, _h),
                            }
                        )
                except Exception as _exc:
                    _zyg_log.debug('gpu telemetry sample failed, this tick reports no gpu: %s', _exc)
            snap['gpus'] = gpus
            # Process table and filesystems on their own slower cadences — a /proc
            # sweep of ~600 pids does not belong on the 1 s hardware tick. Keys
            # left out of `snap` keep their previous value (the cache is .update()d).
            _now_s = time.time()
            if _now_s - _proc_sample_last >= _PROC_SAMPLE_EVERY:
                _proc_sample_last = _now_s
                try:
                    snap.update(_sample_top_processes(_ps))
                except Exception as _exc:
                    _zyg_log.debug('process table sample skipped this tick: %s', _exc)
            if _now_s - _disk_sample_last >= _DISK_SAMPLE_EVERY:
                _disk_sample_last = _now_s
                try:
                    snap['disks'] = _sample_disks(_ps)
                except Exception as _exc:
                    _zyg_log.debug('disk sample skipped this tick: %s', _exc)
            # CPU fan RPM via psutil sensors_fans (may not be available on all boards)
            try:
                # `psutil` is bound as `_ps` in this function; the bare name was a
                # NameError every tick, swallowed by the except below, so the fan RPM
                # never once reached the panel.
                _fans = _ps.sensors_fans() if hasattr(_ps, 'sensors_fans') else {}
                for _fn, _flist in _fans.items():
                    if _flist:
                        snap['cpu_fan_rpm'] = int(_flist[0].current)
                        break
            except Exception as _exc:
                _zyg_log.debug('cpu fan rpm unavailable: %s', _exc)
            # CPU frequency fallback — shown when fan RPM unavailable
            try:
                _freq = _ps.cpu_freq()
                if _freq:
                    snap['cpu_freq_mhz'] = round(_freq.current, 0)
            except Exception as _exc:
                _zyg_log.debug('cpu frequency unavailable: %s', _exc)
            _TELEMETRY_CACHE.update(snap)
            # Write one row to the active run's telemetry log (if a pipeline is running)
            _active = gui_state._TELEMETRY_LOG_PIPELINE_ID
            if _active:
                try:
                    _log_file = _runtime_path(f'telemetry_{_active}.csv')
                    _row_exists = os.path.exists(_log_file)
                    with open(_log_file, 'a') as _tf:
                        if not _row_exists:
                            _tf.write(
                                'timestamp,cpu_pct_raw,cpu_pct_scaled,cpu_temp_c,cpu_freq_mhz,gpu_util_pct,gpu_temp_c,gpu_fan_pct,gpu_mem_used_mb,gpu_mem_total_mb,vram_pct,gpu_power_w,ram_used_mb\n'
                            )
                        _gpu0 = (snap.get('gpus') or [{}])[0]
                        _vmem_used = _gpu0.get('memory_used_mb', 0) or 0
                        _vmem_total = _gpu0.get('memory_total_mb', 1) or 1
                        _vram_pct_csv = round(_vmem_used / _vmem_total * 100, 1)
                        _tf.write(
                            f'{_ams_now().strftime("%Y-%m-%dT%H:%M:%S%z")},'
                            f'{snap.get("cpu_pct_raw", "")},'
                            f'{snap.get("cpu_pct", "")},'
                            f'{snap.get("cpu_temp_c", "")},'
                            f'{snap.get("cpu_freq_mhz", "")},'
                            f'{_gpu0.get("utilization_pct", "")},'
                            f'{_gpu0.get("temperature_c", "")},'
                            f'{_gpu0.get("fan_pct", "")},'
                            f'{_gpu0.get("memory_used_mb", "")},'
                            f'{_gpu0.get("memory_total_mb", "")},'
                            f'{_vram_pct_csv},'
                            f'{_gpu0.get("power_w", "")},'
                            f'{snap.get("ram_used_mb", "")}\n'
                        )
                except Exception as _exc:
                    _zyg_log.debug('telemetry csv row not written for %s: %s', _active, _exc)
        except Exception as _exc:
            _zyg_log.warning('telemetry tick failed, the panel keeps the previous snapshot: %s', _exc)
        time.sleep(1)


# Pipeline ID currently running (set when pipeline starts, cleared when done)
gui_state._TELEMETRY_LOG_PIPELINE_ID: str = ''

_telemetry_thread = threading.Thread(target=_telemetry_sampler_loop, name='telemetry-sampler', daemon=True)
_telemetry_thread.start()


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
