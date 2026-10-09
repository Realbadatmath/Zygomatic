#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The clipfarm starter, the runtime log rotation, GPU process attribution.

Lines 2569-2839 of the original module, verbatim. ``_log_rotate_last_check`` is
rebound by ``_rotate_runtime_logs`` through a ``global`` statement, so the name and
its only mutator stay together in this one module.
"""

from zyg_dashboard.crewai_web_gui._bootstrap import (
    _ams_iso,
    _runtime_path,
    _workflow_jobs,
    _zyg_log,
    gui_state,
    os,
    shutil,
    threading,
    time,
    uuid,
)
from zyg_dashboard.crewai_web_gui.claude_clips import _clear_pipeline_halt
from zyg_dashboard.crewai_web_gui.pages import controller
from zyg_workflows.pipeline_clipfarm import _run_clipfarm_pipeline


def _start_clipfarm_internal(directive: str = None) -> dict:
    """Start the staged Clipfarm pipeline in a background thread. Returns job info."""
    # Sanity check — need at least the source scanner
    if 'CLIPFARM-Source-Scanner-Agent' not in controller.agents:
        return {'error': 'Source Scanner agent not found'}
    agent = controller.agents['CLIPFARM-Source-Scanner-Agent']
    if type(agent).__name__ == 'MockAgent':
        return {'error': 'Ollama not running — agents in mock mode'}

    pipeline_id = str(uuid.uuid4())
    _clear_pipeline_halt()
    _stop_event = threading.Event()
    _workflow_jobs[pipeline_id] = {
        'status': 'running',
        'pipeline_id': pipeline_id,
        'department': 'clipfarm',  # schedule aggregation classifies by this
        'started': _ams_iso(),
        'current_stage': None,
        'stages': {},
        'result': None,
        'error': None,
        'stop_event': _stop_event,
    }
    threading.Thread(
        target=_run_clipfarm_pipeline,
        args=(pipeline_id, directive),
        daemon=True,
        name=f'clipfarm-pipeline-{pipeline_id[:8]}',
    ).start()
    return {'job_id': pipeline_id, 'status': 'running'}


# 2026-07-17 heavy-tranche: _zero_evaluate_approval moved to bp_zero.py


# 2026-07-17 heavy-tranche: _process_pending_approvals moved to bp_zero.py


# 2026-07-17 heavy-tranche: _approval_worker moved to bp_zero.py


# 2026-07-17 heavy-tranche: lines 4370-4370 moved to bp_zero.py


# 2026-07-17 heavy-tranche: workflow_status moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: workflow_status_active moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: kanban_status moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: kanban_clear_errors moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: pipeline_stages moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: agent_tree moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: agent_network moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: available_models moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: agent_model_audit moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: _load_feedback_workflow_data moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_workflow_box_ids moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_agents_active moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_metrics_summary moved to bp_metrics.py


# 2026-07-17 heavy-tranche: get_metrics_all moved to bp_metrics.py


# 2026-07-17 heavy-tranche: get_metrics_dashboard moved to bp_metrics.py


# 2026-07-17 heavy-tranche: _backfill_char_gen_states_from_bibles moved to bp_metrics.py


gui_state._CHAR_GEN_BACKFILL_DONE = False
gui_state._CHAR_GEN_RELOAD_DONE = False
gui_state._CREATURE_GEN_RELOAD_DONE = False
gui_state._CONTACT_SHEET_RELOAD_DONE = False

_METRICS_PIPELINE_LABELS = {
    'scholarly': 'Scholarly Documentary',
    'crime': 'Crime Documentary',
    'clipfarm': 'Clipfarm',
    'video': 'Video Pipeline',
    'manga': 'Manga',
    'character_brief': 'Character Brief (Claude)',
    'character': 'Character Generation',
    'agent_zero': 'Agent Zero',
    'unknown': 'Other / Legacy',
}


# 2026-07-17 heavy-tranche: _metrics_fmt_duration moved to bp_metrics.py


# 2026-07-17 heavy-tranche: _metrics_normalize_stage moved to bp_metrics.py


# 2026-07-17 heavy-tranche: _compute_metrics_dashboard moved to bp_metrics.py


# 2026-10-06 round-2 split: _read_local_telemetry and the _TELEMETRY_CACHE import site
# moved to zyg_dashboard.gui.telemetry

# ── Background telemetry sampler ─────────────────────────────────────────────
# Samples hardware every 2s on its own daemon thread so Flask requests never
# block waiting on psutil or pynvml, even under 100% CPU load.

_LOG_ROTATE_MAX_BYTES = int(os.environ.get('ZYG_LOG_ROTATE_MAX_MB', '150')) * 1024 * 1024
_LOG_ROTATE_KEEP = 3
_log_rotate_last_check = 0.0


def _rotate_runtime_logs():
    """2026-07-24: copytruncate-rotate flask.log/kanban.log (they reached 327MB /
    24MB with no rotation anywhere; systemd appends with O_APPEND so truncate is
    safe — writers continue at offset 0). Called from the telemetry sampler."""
    global _log_rotate_last_check
    now = time.time()
    if now - _log_rotate_last_check < 600:
        return
    _log_rotate_last_check = now
    import gzip as _gz

    for _name in ('flask.log', 'kanban.log'):
        try:
            _p = _runtime_path(_name)
            if not os.path.isfile(_p) or os.path.getsize(_p) < _LOG_ROTATE_MAX_BYTES:
                continue
            for _i in range(_LOG_ROTATE_KEEP - 1, 0, -1):
                _src, _dst = f'{_p}.{_i}.gz', f'{_p}.{_i + 1}.gz'
                if os.path.isfile(_src):
                    os.replace(_src, _dst)
            with open(_p, 'rb') as _fin, _gz.open(f'{_p}.1.gz', 'wb') as _fout:
                shutil.copyfileobj(_fin, _fout, 1024 * 1024)
            with open(_p, 'r+b') as _ft:
                _ft.truncate(0)
            _zyg_log.info(f'[LOG-ROTATE] {_name} rotated (> {_LOG_ROTATE_MAX_BYTES >> 20} MB)')
        except Exception as _lr_e:
            _zyg_log.info(f'[LOG-ROTATE] {_name} rotation failed: {_lr_e}')


# ── GPU attribution: who is actually using the card ──────────────────────────
# nvidia-smi's "GPU-Util" (NVML utilization.gpu) is a DUTY CYCLE: the share of the
# sample window in which at least one kernel was resident. It says how OFTEN, never
# how HARD. On an idle card the driver drops the SM clock to ~210 MHz of 3105, so a
# trivial compositor blit occupies ~15x more of the window than the same blit at
# boost — and the ring reads 35% while the card draws 30 W of 450 W. Scaling the
# duty cycle by the current clock ratio gives a number that tracks capacity ACTUALLY
# consumed, which is what an operator wants to read before launching a pipeline.
_GPU_PROC_LABELS: dict = {}  # pid -> friendly name (pids are not reused fast)

# Matched in order against the process cmdline; first hit wins.
_GPU_PROC_PATTERNS = [
    ('type=gpu-process', 'Chrome (GPU/compositing)'),
    ('type=renderer', 'Chrome (tab)'),
    ('type=utility', 'Chrome (utility)'),
    ('/chrome', 'Chrome'),
    ('comfyui', 'ComfyUI'),
    ('transcriber', 'Transcribe'),
    ('kanban_server', 'Kanban server'),
    ('crewai_web_gui', 'Crews GUI'),
    ('ollama', 'Ollama'),
    ('xfwm4', 'xfwm4 (desktop compositor)'),
    ('xorg', 'Xorg (display server)'),
    ('xfdesktop', 'Xfdesktop'),
    ('blender', 'Blender'),
    ('ffmpeg', 'ffmpeg'),
]


def _gpu_proc_label(pid: int) -> str:
    """Friendly name for a pid holding the GPU. Cached — /proc is read once."""
    lbl = _GPU_PROC_LABELS.get(pid)
    if lbl:
        return lbl
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as _cf:
            cmd = _cf.read().replace(b'\x00', b' ').decode('utf-8', 'replace').strip()
    except Exception:
        return f'pid {pid}'
    low = cmd.lower()
    lbl = None
    for needle, name in _GPU_PROC_PATTERNS:
        if needle in low:
            lbl = name
            break
    if not lbl:
        try:
            with open(f'/proc/{pid}/comm') as _cf:
                lbl = _cf.read().strip() or f'pid {pid}'
        except Exception:
            lbl = f'pid {pid}'
    _GPU_PROC_LABELS[pid] = lbl
    if len(_GPU_PROC_LABELS) > 512:  # bound the cache on a long-lived process
        _GPU_PROC_LABELS.clear()
    return lbl


def _gpu_processes(_nv, _handle) -> list:
    """Per-process GPU usage: SM/mem/enc/dec share plus VRAM held.

    Two NVML sources, unioned by pid — utilization samples (what pmon prints) cover
    only processes that ran a kernel in the lookback window, while the running-process
    lists cover everything holding memory, including a model sitting idle in VRAM.
    """
    procs: dict = {}
    try:
        since = int((time.time() - 4) * 1_000_000)
        for _s in _nv.nvmlDeviceGetProcessUtilization(_handle, since) or []:
            _pid = int(getattr(_s, 'pid', 0) or 0)
            if _pid <= 0:
                continue
            _prev = procs.get(_pid)
            # NVML can return several samples per pid; keep the most recent.
            if _prev and _prev.get('_ts', 0) >= getattr(_s, 'timeStamp', 0):
                continue
            procs[_pid] = {
                'pid': _pid,
                '_ts': getattr(_s, 'timeStamp', 0),
                'sm_pct': int(getattr(_s, 'smUtil', 0) or 0),
                'mem_pct': int(getattr(_s, 'memUtil', 0) or 0),
                'enc_pct': int(getattr(_s, 'encUtil', 0) or 0),
                'dec_pct': int(getattr(_s, 'decUtil', 0) or 0),
            }
    except Exception as _exc:
        _zyg_log.debug('per-process gpu utilisation sample unavailable: %s', _exc)

    for _getter, _kind in (
        ('nvmlDeviceGetComputeRunningProcesses', 'compute'),
        ('nvmlDeviceGetGraphicsRunningProcesses', 'graphics'),
    ):
        try:
            for _rp in getattr(_nv, _getter)(_handle) or []:
                _pid = int(getattr(_rp, 'pid', 0) or 0)
                if _pid <= 0:
                    continue
                _mem = getattr(_rp, 'usedGpuMemory', None)
                _e = procs.setdefault(_pid, {'pid': _pid, 'sm_pct': 0, 'mem_pct': 0, 'enc_pct': 0, 'dec_pct': 0})
                _e['kind'] = _kind
                _e['vram_mb'] = round((_mem or 0) / 1024 / 1024, 1) if _mem else 0.0
        except Exception as _exc:
            _zyg_log.debug('nvml %s unavailable, those processes are missing: %s', _getter, _exc)

    out = []
    for _pid, _e in procs.items():
        if not os.path.exists(f'/proc/{_pid}'):
            continue  # sample outlived the process
        _e.pop('_ts', None)
        _e.setdefault('kind', 'compute')
        _e.setdefault('vram_mb', 0.0)
        _e['label'] = _gpu_proc_label(_pid)
        out.append(_e)
    out.sort(key=lambda _e: (-_e['sm_pct'], -_e['vram_mb']))
    return out[:12]
