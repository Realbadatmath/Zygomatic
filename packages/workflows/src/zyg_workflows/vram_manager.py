# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import subprocess
import time
from zyg_workflows import gui_state
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL, _SAFETY_THRESHOLDS_PATH
from zyg_workflows.runtime import (
    _ams_iso,
    _backend_debug,
    _char_gen_jobs,
    _GPU_PIPELINE_LOCK,
    _reconcile_stale_workflow_jobs,
    _runtime_path,
    _TELEMETRY_CACHE,
    _workflow_pipeline_worker_alive,
    workflow_jobs as _workflow_jobs,
)
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


def _get_free_vram_gb() -> float:
    """Return free VRAM in GB for GPU 0, capped by _CALIBRATION['max_vram_gb']. Returns 999 on error."""
    try:
        import subprocess as _smi_sp

        _r = _smi_sp.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _lines = [l.strip() for l in _r.stdout.splitlines() if l.strip()]
        if _lines:
            _parts = _lines[0].split(',')
            _phys_free_gb = int(_parts[0].strip()) / 1024.0
            _phys_total_gb = int(_parts[1].strip()) / 1024.0 if len(_parts) > 1 else 48.0
            _max_vram_gb = gui_state._CALIBRATION.get('max_vram_gb', 48.0)
            _used_gb = _phys_total_gb - _phys_free_gb
            # Ceiling free = how much of our calibrated limit is still available
            _ceiling_free = max(0.0, _max_vram_gb - _used_gb)
            return min(_phys_free_gb, _ceiling_free)
    except Exception as _exc:
        _zyg_log.warning('free-vram query failed, reporting 999 GB free so the gate stays open: %s', _exc)
    return 999.0


def _wait_for_vram(required_gb: float, timeout: int = 300, label: str = '') -> bool:
    """Block until GPU has at least `required_gb` free VRAM, or timeout.
    Returns True if headroom available, False if timed out.
    Default timeout raised to 300s — a 70B model can take ~2.5 min to fully drain."""
    import time as _time_vram

    _deadline = _time_vram.time() + timeout
    while _time_vram.time() < _deadline:
        _free = _get_free_vram_gb()
        if _free >= required_gb:
            return True
        _backend_debug(
            f'VRAM wait: need {required_gb:.0f} GB, have {_free:.1f} GB free{" [" + label + "]" if label else ""} — sleeping 10s'
        )
        _time_vram.sleep(10)
    return False


def _ensure_comfy_offload_env() -> None:
    """When ComfyUI is reachable, default env so stills/WAN route off-process."""
    try:
        from zyg_workflows import _comfy_client as _cc_env
    except ImportError:
        return
    if _cc_env.server_reachable():
        os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
        os.environ.setdefault('ZYG_USE_COMFYUI', '1')


def _deep_unload_flux_pipeline_cache(log_fn=None) -> None:
    """Move FLUX components to CPU, drop cache refs, gc + double empty_cache (Stage 3.5 pattern)."""
    pass  # (global stmt removed: names moved to gui_state)
    _flux_target = None
    try:
        for _pipe in (gui_state._FLUX_DEV_PIPELINE_CACHE, gui_state._FLUX_PIPELINE_CACHE):
            if _pipe is None:
                continue
            try:
                _pipe.unload_lora_weights()
            except Exception as _exc:
                _zyg_log.debug('lora unload on the flux pipe skipped: %s', _exc)
            if _flux_target is None:
                _flux_target = _pipe
        gui_state._FLUX_DEV_PIPELINE_CACHE = None
        if gui_state._FLUX_PIPELINE_CACHE is not None:
            _flux_target = _flux_target or gui_state._FLUX_PIPELINE_CACHE
            gui_state._FLUX_PIPELINE_CACHE = None
            gui_state._CN_PIPE_CACHE = None
    except Exception as _de:
        if log_fn:
            log_fn(f'FLUX cache detach warning: {_de}')
    if _flux_target is not None:
        try:
            for _flux_comp_attr in ('transformer', 'vae', 'text_encoder', 'text_encoder_2'):
                _flux_comp = getattr(_flux_target, _flux_comp_attr, None)
                if _flux_comp is not None:
                    try:
                        _flux_comp.to('cpu')
                    except Exception as _exc:
                        _zyg_log.debug('flux %s stayed on the GPU: %s', _flux_comp_attr, _exc)
            del _flux_target
        except Exception as _exc:
            _zyg_log.debug('flux component sweep incomplete, some VRAM may stay held: %s', _exc)
    try:
        import gc as _gc_flux_deep
        import torch as _torch_flux_deep

        _gc_flux_deep.collect()
        if _torch_flux_deep.cuda.is_available():
            _torch_flux_deep.cuda.empty_cache()
            import time as _t_flux_deep

            _t_flux_deep.sleep(3)
            _gc_flux_deep.collect()
            _torch_flux_deep.cuda.empty_cache()
        if log_fn:
            log_fn('FLUX pipeline cache deep-unloaded')
    except Exception as _exc:
        _zyg_log.debug('torch cache flush after the flux unload skipped: %s', _exc)


def _evict_all_ollama_models(log_fn=None) -> list[str]:
    """Unload every Ollama model from VRAM (photo analysis, Stage 3, idle sweeper)."""
    try:
        from zyg_workflows import character_photo_analysis_service as _cpas_ev

        return _cpas_ev.evict_all_ollama_models(
            log_fn=log_fn or (lambda m: print(f'[VRAM] {m}', flush=True)),
        )
    except Exception as exc:
        if log_fn:
            log_fn(f'Ollama evict-all failed: {exc}')
        return []


def _ollama_loaded_vram_mb() -> int:
    """Approximate VRAM MiB held by loaded Ollama models."""
    try:
        import json as _j_om

        from zyg_workflows.net import safe_urlopen as _open_om

        _raw = _open_om(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read()
        _ps = _j_om.loads(_raw)
        total = 0
        for _m in _ps.get('models') or []:
            try:
                total += int(_m.get('size_vram') or 0)
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('ollama reported a non-numeric size_vram, not counted: %s', _exc)
        return total // (1024 * 1024) if total else 0
    except Exception:
        return 0


def _release_pipeline_vram(label: str = '', log_fn=None, wait_comfy: bool = True, allow_restart: bool = True) -> None:
    """Free VRAM/RAM held by Comfy, in-process FLUX, MusicGen, and WAN module globals.

    allow_restart=False keeps release_memory from restarting the SHARED ComfyUI
    server when its RSS looks stuck — a restart is more destructive to another
    client's queued render than the global /interrupt this module stopped
    issuing (P-07), so it is only permitted when the queue was seen idle.
    """

    def _msg(text: str) -> None:
        if log_fn:
            log_fn(f'{label}: {text}' if label else text)

    try:
        from zyg_workflows import _comfy_client as _cc_rel

        if _cc_rel.server_reachable():
            if wait_comfy:
                _summary = _cc_rel.release_memory(
                    wait=True,
                    log_fn=_msg,
                    restart_if_stuck=(None if allow_restart else False),
                )
                if _summary.get('skipped'):
                    _msg('ComfyUI keep-loaded — skip release')
                elif _summary.get('restarted'):
                    _msg(
                        f'ComfyUI restarted — RSS now {_summary.get("rss_mb_after", "?")} MiB, '
                        f'GPU {_summary.get("gpu_mb_after", "?")} MiB'
                    )
                elif _summary.get('ok'):
                    _msg(
                        f'ComfyUI memory released — RSS '
                        f'{_summary.get("rss_mb_before", "?")}→{_summary.get("rss_mb_after", "?")} MiB, '
                        f'GPU {_summary.get("gpu_mb_after", "?")} MiB'
                    )
                else:
                    _msg('ComfyUI /free skipped or failed')
            elif _cc_rel.free_vram():
                _msg('ComfyUI /free — models evicted')
            else:
                _msg('ComfyUI /free skipped or failed')
    except ImportError as _exc:
        _zyg_log.debug('comfy client not importable, nothing to free there: %s', _exc)
    except Exception as _cfe:
        _msg(f'Comfy release non-fatal: {_cfe}')

    try:
        _evicted = _evict_all_ollama_models(log_fn=_msg)
        if _evicted:
            _msg(f'Ollama VRAM released ({len(_evicted)} model(s))')
    except Exception as _oll_e:
        _msg(f'Ollama release non-fatal: {_oll_e}')

    _deep_unload_flux_pipeline_cache(log_fn=log_fn)

    try:
        from zyg_workflows import musicgen_service as _mgs_rel

        _mgs_rel.unload()
        _msg('MusicGen unloaded')
    except Exception as _exc:
        _zyg_log.debug('musicgen unload skipped, it may still hold VRAM: %s', _exc)

    try:
        from zyg_workflows import ace_step_service as _ace_rel

        _ace_rel.unload()
        _msg('ACE-Step unloaded')
    except Exception as _exc:
        _zyg_log.debug('ace-step unload skipped, it may still hold VRAM: %s', _exc)

    try:
        from zyg_workflows import wan_video_service as _wvs_rel

        _wvs_rel._unload_pipe(log_fn=log_fn)
        _wvs_rel._unload_t2v_pipe(log_fn=log_fn)
        _msg('WAN pipes unloaded')
    except Exception as _exc:
        _zyg_log.debug('wan pipe unload skipped, it may still hold VRAM: %s', _exc)

    try:
        import gc as _gc_rel
        import torch as _torch_rel

        _gc_rel.collect()
        if _torch_rel.cuda.is_available():
            _torch_rel.cuda.empty_cache()
            if hasattr(_torch_rel.cuda, 'ipc_collect'):
                _torch_rel.cuda.ipc_collect()
    except Exception as _exc:
        _zyg_log.debug('final torch cache flush skipped: %s', _exc)


_FLASK_DASHBOARD_SCRIPT = 'crewai_web_gui.py'
_GUI_SYSTEMD_UNIT = 'crewai-gui.service'
_KILL_SIBLING_FLASK_ENV = 'ZYG_KILL_SIBLING_FLASK'


def _proc_ppid(pid: int) -> int:
    """Parent pid from the /proc/<pid>/status PPid line (0 when unreadable / pid 1)."""
    try:
        with open(f'/proc/{pid}/status', 'r', encoding='utf-8', errors='replace') as _fh:
            for _line in _fh:
                if _line.startswith('PPid:'):
                    return int(_line.split()[1])
    except (OSError, ValueError, IndexError) as _exc:
        _zyg_log.debug('ppid of %s unreadable, treated as 0: %s', pid, _exc)
    return 0


def _proc_argv(pid: int) -> list[str]:
    """NUL-separated argv from /proc/<pid>/cmdline ([] for zombies / unreadable)."""
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as _fh:
            _raw = _fh.read()
    except OSError:
        return []
    return [_a.decode('utf-8', 'replace') for _a in _raw.split(b'\0') if _a]


def _proc_in_gui_unit(pid: int) -> bool:
    """True when /proc/<pid>/cgroup places the process inside crewai-gui.service."""
    try:
        with open(f'/proc/{pid}/cgroup', 'r', encoding='utf-8', errors='replace') as _fh:
            return _GUI_SYSTEMD_UNIT in _fh.read()
    except OSError:
        return False


def _gui_service_main_pid() -> int:
    """MainPID of crewai-gui.service via `systemctl show` (0 when systemd/unit absent or inactive)."""
    try:
        _out = subprocess.check_output(
            [exe('systemctl'), 'show', '-p', 'MainPID', '--value', _GUI_SYSTEMD_UNIT],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        return int(_out) if _out.isdigit() else 0
    except Exception:
        return 0


def _is_flask_dashboard_argv(argv: list[str]) -> bool:
    """Exact-argv rule: an element that IS crewai_web_gui.py or ENDS with /crewai_web_gui.py.

    Deliberately NOT a substring test — `pgrep -f` matched any shell whose command
    line merely mentioned the filename (e.g. `bash -c "... crewai_web_gui.py ..."`)."""
    return any(_a == _FLASK_DASHBOARD_SCRIPT or _a.endswith('/' + _FLASK_DASHBOARD_SCRIPT) for _a in argv)


def _stop_secondary_flask_dashboards(log_fn=None, keep_pid: int | None = None) -> list[int]:
    """Terminate DUPLICATE crewai_web_gui.py processes so Stage 3.5 has exclusive GPU/RAM.

    2026-08-25 (P-01): the old `pgrep -f crewai_web_gui.py` + SIGTERM-everything-but-me
    killed the PRODUCTION GUI whenever a documentary ran outside the service process
    (smoke / gatecheck / bench / CLI re-render): from there the systemd unit looked
    "secondary", exited 0 on SIGTERM (so Restart=on-failure stayed inert) and stayed
    down until zyg-health's second strike, ~2-4 min later.

    Now: candidates come from /proc/<pid>/cmdline with an exact argv rule, and a
    PROTECTED set is never signalled: self, keep_pid, every ancestor on the PPid
    chain, the crewai-gui.service MainPID, and any pid whose cgroup lies inside
    crewai-gui.service. ZYG_KILL_SIBLING_FLASK ("1" default) still SIGTERMs true
    duplicates; "0" disables the kill entirely (logged).

    Returns the list of pids that were actually SIGTERMed (unchanged contract).
    """
    import signal as _sig_fl
    import time as _t_fl

    def _say(m: str) -> None:
        if log_fn:
            log_fn(m)

    _self_pid = os.getpid()
    _keep = keep_pid if keep_pid is not None else _self_pid
    _stopped: list[int] = []
    _kill_enabled = os.environ.get(_KILL_SIBLING_FLASK_ENV, '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )

    # ── PROTECTED set (pid → reason, for the log line) ───────────────────────
    _protected: dict[int, str] = {_self_pid: 'self', _keep: 'keep_pid'}
    for _root in (_self_pid, _keep):
        _p = _root
        for _ in range(64):  # bounded walk — PPid chains are short, and loops are impossible
            _pp = _proc_ppid(_p)
            if _pp <= 0 or _pp in _protected:
                break
            _protected[_pp] = 'ancestor'
            _p = _pp
    _main_pid = _gui_service_main_pid()
    if _main_pid > 0:
        _protected[_main_pid] = 'systemd crewai-gui MainPID'

    # ── candidates: exact argv match over /proc/*/cmdline ────────────────────
    _candidates: list[int] = []
    try:
        for _entry in os.listdir('/proc'):
            if not _entry.isdigit():
                continue
            _pid = int(_entry)
            if _pid == _self_pid or _pid == _keep:
                continue
            if _is_flask_dashboard_argv(_proc_argv(_pid)):
                _candidates.append(_pid)
    except Exception as _sf_e:
        _say(f'Secondary Flask scan failed: {_sf_e}')
        return _stopped

    _left_running: list[int] = []
    for _pid in sorted(_candidates):
        _why = _protected.get(_pid)
        if _why is None and _proc_in_gui_unit(_pid):
            _why = f'{_GUI_SYSTEMD_UNIT} cgroup'
        if _why is not None:
            _say(f'protected: PID {_pid} (systemd crewai-gui / ancestor) — not signalled [{_why}]')
            continue
        if not _kill_enabled:
            _left_running.append(_pid)
            continue
        try:
            os.kill(_pid, _sig_fl.SIGTERM)
            _stopped.append(_pid)
        except ProcessLookupError as _exc:
            _zyg_log.debug('Flask PID %s was already gone: %s', _pid, _exc)
        except PermissionError:
            _say(f'Cannot stop Flask PID {_pid} (permission denied)')

    if _left_running:
        _say(
            f'{_KILL_SIBLING_FLASK_ENV}=0 — sibling Flask kill disabled; '
            f'duplicate {_FLASK_DASHBOARD_SCRIPT} PID(s) left running: {_left_running}'
        )
    if _stopped:
        _t_fl.sleep(2)  # settle: let the SIGTERMed dashboards release VRAM/RAM
        _say(f'Stopped {len(_stopped)} secondary Flask dashboard(s): {_stopped}')
    return _stopped


# 2026-08-25 (P-07): how long Stage 3.5 waits for the SHARED ComfyUI queue to drain
# instead of firing a global /interrupt. Matches _comfy_client's own idle-wait ceiling.
_STAGE35_COMFY_IDLE_TIMEOUT_S = 120.0


def _enforce_gpu_exclusivity_before_stage35(log_fn=None, pipeline_id: str = '') -> None:
    """Tier 1: free GPU before scholarly Stage 3.5 (Ollama, Comfy, duplicate Flask, caches)."""
    if os.environ.get('ZYG_SKIP_GPU_EXCLUSIVE', '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    ):
        if log_fn:
            log_fn('GPU exclusivity skipped (ZYG_SKIP_GPU_EXCLUSIVE)')
        return

    def _msg(m: str) -> None:
        if log_fn:
            log_fn(m)

    _msg('GPU exclusivity: halting competing workloads before Stage 3.5…')
    try:
        from zyg_workflows import scholarly_stills_backend as _ssb_ex

        _stagger = _ssb_ex.scholarly_stagger_concurrent_enabled()
    except ImportError:
        _stagger = False
    if _stagger:
        _msg(
            f'Staggered concurrent pipelines — skipping secondary Flask shutdown ({_ssb_ex._STAGGER_CONCURRENT_ENV}=1)'
        )
    else:
        _stop_secondary_flask_dashboards(log_fn=_msg)

    # 2026-08-25 (P-07): ComfyUI is a SHARED server (creature worker, storyteller,
    # Voices tab…). The old `interrupt_execution()` here was a GLOBAL /interrupt —
    # "Global interrupt (no prompt_id specified)" — that would have killed another
    # client's multi-minute render. Now: wait for the queue to drain, never interrupt;
    # a still-busy queue is logged and we proceed (/free only acts between prompts).
    _idle = True
    try:
        from zyg_workflows import _comfy_client as _cc_ex

        if _cc_ex.server_reachable(timeout_s=2.0):
            _wait_idle = getattr(_cc_ex, 'wait_for_idle', None)
            if _wait_idle is None:
                _wait_idle = getattr(_cc_ex, '_wait_for_queue_idle', None)
            if _wait_idle is not None:
                import time as _t_cc

                _t0_cc = _t_cc.monotonic()
                # Staggered concurrent pipelines share the server on purpose:
                # a long wait here would stall the second pipeline ~2 min
                # behind the first one's still batch, so only a short grace
                # wait applies in that mode.
                _wait_s = 10.0 if _stagger else _STAGE35_COMFY_IDLE_TIMEOUT_S
                _idle = bool(_wait_idle(timeout_s=_wait_s))
                if _idle:
                    _msg(
                        f'ComfyUI queue idle after {_t_cc.monotonic() - _t0_cc:.1f}s wait '
                        f'— no interrupt sent (shared server)'
                    )
            if not _idle:
                _msg('ComfyUI queue busy after wait — proceeding without interrupt')
            _cc_ex.free_vram()
    except Exception as _ccx_e:
        _msg(f'Comfy wait/free non-fatal: {_ccx_e}')

    _release_pipeline_vram(
        'Stage 3.5 exclusivity',
        log_fn=_msg,
        wait_comfy=True,
        # Never restart the shared server while another client's job is queued.
        allow_restart=_idle,
    )

    _evicted = _evict_all_ollama_models(log_fn=_msg)
    if _evicted:
        _msg(f'Ollama evicted {len(_evicted)} model(s): {", ".join(_evicted[:6])}')

    import time as _t_ex

    for _wait_i in range(12):
        if _ollama_loaded_vram_mb() < 50:
            break
        _t_ex.sleep(2)
    else:
        _msg(f'WARN: Ollama may still hold VRAM (~{_ollama_loaded_vram_mb()} MiB)')

    try:
        import torch as _torch_ex

        if _torch_ex.cuda.is_available():
            _torch_ex.cuda.empty_cache()
            _free_gb = _torch_ex.cuda.mem_get_info(0)[0] / 1024**3
            _msg(f'Post-exclusivity VRAM free: {_free_gb:.1f} GB')
    except Exception as _exc:
        _zyg_log.debug('post-exclusivity vram report unavailable: %s', _exc)

    if not _wait_for_vram(25.0, timeout=180, label='Stage 3.5 exclusivity'):
        _msg('WARN: <25 GB VRAM free after exclusivity sweep — FLUX load may OOM')


def _workflow_job_gpu_active(job: dict) -> bool:
    """True only when a pipeline job has a live worker thread (not stale ``running``)."""
    if (job or {}).get('status') != 'running':
        return False
    pid = (job.get('pipeline_id') or '').strip()
    return bool(pid and _workflow_pipeline_worker_alive(pid))


def _char_gen_worker_alive(char_id: str) -> bool:
    cid = (char_id or '').strip()
    if not cid:
        return False
    import threading as _th_cg

    needle = f'char-gen-{cid[:8]}'
    return any(t.name == needle and t.is_alive() for t in _th_cg.enumerate())


def _gpu_work_active() -> bool:
    """True when a pipeline or character job is actively using the GPU."""
    try:
        if _GPU_PIPELINE_LOCK.locked():
            return True
    except Exception as _exc:
        _zyg_log.warning('pipeline lock probe failed, GPU work may be reported idle: %s', _exc)
    try:
        for _wj in _workflow_jobs.values():
            if _workflow_job_gpu_active(_wj):
                return True
    except Exception as _exc:
        _zyg_log.warning('workflow job scan failed, GPU work may be reported idle: %s', _exc)
    try:
        for _cj in _char_gen_jobs.values():
            if (_cj or {}).get('status') != 'running':
                continue
            cid = (_cj.get('char_id') or '').strip()
            if cid and _char_gen_worker_alive(cid):
                return True
    except Exception as _exc:
        _zyg_log.warning('character job scan failed, GPU work may be reported idle: %s', _exc)
    return False


def _comfy_server_pid() -> int | None:
    """Return ComfyUI main.py PID if running, and pin it to cores 0-20."""
    try:
        import subprocess as _sp_cp

        _pg = _sp_cp.run(
            ['pgrep', '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
            capture_output=True,
            timeout=5,
            text=True,
        )
        for _line in _pg.stdout.split():
            if _line.strip().isdigit():
                _pid = int(_line.strip())
                try:
                    # Was set(range(21)) — one core over the shared ceiling.
                    from zyg_workflows import cpu_cap as _cpu_cap_cf

                    _cpu_cap_cf.apply_to_pid(_pid)
                except Exception as _exc:
                    _zyg_log.debug('cpu cap not applied to comfy pid %s: %s', _pid, _exc)
                return _pid
    except Exception as _exc:
        _zyg_log.debug('comfy server pid lookup failed, treated as not running: %s', _exc)
    return None


def _comfy_vram_used_mb() -> int:
    """VRAM MiB used by the ComfyUI server process (0 if not running)."""
    _cpid = _comfy_server_pid()
    if not _cpid:
        return 0
    try:
        import subprocess as _sp_cv

        _r = _sp_cv.run(
            [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        for _line in _r.stdout.strip().splitlines():
            _parts = [p.strip() for p in _line.split(',')]
            if len(_parts) == 2 and _parts[0].isdigit() and int(_parts[0]) == _cpid:
                return int(_parts[1])
    except Exception as _exc:
        _zyg_log.debug('comfy vram query failed, reporting 0 MiB in use: %s', _exc)
    return 0


def _startup_vram_sweep() -> None:
    """On web-server boot: evict Comfy cached models and in-process GPU globals."""
    try:
        import subprocess as _sp_boot

        _before = _sp_boot.run(
            [exe('nvidia-smi'), '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        _bline = _before.stdout.strip().splitlines()
        _bused = _bline[0].split(',')[0].strip() if _bline else '?'
        _zyg_log.info(f'[VRAM] Startup sweep — GPU used {_bused} MiB before release')
    except Exception as _exc:
        _zyg_log.debug('pre-sweep vram reading unavailable: %s', _exc)
    _reconcile_stale_workflow_jobs()
    _release_pipeline_vram('startup', log_fn=lambda m: print(f'[VRAM] {m}', flush=True))
    try:
        import subprocess as _sp_boot2

        _after = _sp_boot2.run(
            [exe('nvidia-smi'), '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        _aline = _after.stdout.strip().splitlines()
        if _aline:
            _parts = [p.strip() for p in _aline[0].split(',')]
            _zyg_log.info(
                f'[VRAM] Startup sweep complete — GPU used {_parts[0]} MiB, '
                f'free {_parts[1] if len(_parts) > 1 else "?"} MiB'
            )
    except Exception as _exc:
        _zyg_log.debug('post-sweep vram reading unavailable: %s', _exc)


def _comfy_idle_vram_sweeper_loop() -> None:
    """Background thread: free ComfyUI VRAM/RAM when no GPU work is active."""
    import time as _t_sweep

    _interval = float(os.environ.get('ZYG_COMFY_IDLE_FREE_SEC', '90') or '90')
    if _interval <= 0:
        return
    _vram_threshold_mb = int(os.environ.get('ZYG_COMFY_IDLE_FREE_MB', '8192') or '8192')
    _ram_threshold_mb = int(os.environ.get('ZYG_COMFY_IDLE_FREE_RAM_MB', '6144') or '6144')
    while True:
        _t_sweep.sleep(_interval)
        if os.environ.get('ZYG_COMFY_KEEP_LOADED', '').strip().lower() in (
            '1',
            'true',
            'yes',
            'on',
        ):
            continue
        if _gpu_work_active():
            continue
        _ollama_vram = _ollama_loaded_vram_mb()
        if _ollama_vram >= 512:
            try:
                _zyg_log.info(f'[VRAM] Idle sweeper: Ollama holding {_ollama_vram} MiB — no active GPU jobs, evicting')
                _evict_all_ollama_models(
                    log_fn=lambda m: print(f'[VRAM] {m}', flush=True),
                )
            except Exception as _oll_sw:
                _zyg_log.info(f'[VRAM] Ollama idle sweeper error: {_oll_sw}')
            continue
        _used_vram = _comfy_vram_used_mb()
        _used_rss = 0
        try:
            from zyg_workflows import _comfy_client as _cc_sw

            _used_rss = _cc_sw.comfy_process_rss_mb()
        except Exception as _exc:
            _zyg_log.debug('comfy rss probe failed, counting 0 MiB: %s', _exc)
        if _used_vram < _vram_threshold_mb and _used_rss < _ram_threshold_mb:
            continue
        try:
            _zyg_log.info(
                f'[VRAM] Idle sweeper: ComfyUI {_used_vram} MiB VRAM, '
                f'Comfy RSS {_used_rss} MiB — no active GPU jobs, releasing'
            )
            _release_pipeline_vram('idle-sweeper', log_fn=lambda m: print(f'[VRAM] {m}', flush=True))
        except Exception as _sw_e:
            _zyg_log.info(f'[VRAM] Idle sweeper error: {_sw_e}')


def _wait_for_hardware_headroom(label: str = '', timeout: int = 300) -> bool:
    """Block until GPU wattage, CPU%, and RAM are all under calibration hard ceilings.
    Returns True when headroom is available, False on timeout."""
    import time as _t_hw
    import psutil as _ps_hw

    _deadline = _t_hw.time() + timeout
    while _t_hw.time() < _deadline:
        _reasons = []
        # GPU wattage ceiling
        _gpu_cache = _TELEMETRY_CACHE.get('gpus', [])
        if _gpu_cache:
            _power_w = float(_gpu_cache[0].get('power_w', 0) or 0)
            _max_watts = gui_state._CALIBRATION.get('max_gpu_watts', 450.0)
            if _power_w > _max_watts:
                _reasons.append(f'GPU {_power_w:.0f}W > limit {_max_watts:.0f}W')
        # CPU ceiling
        _cpu_pct = float(_TELEMETRY_CACHE.get('cpu_pct') or _ps_hw.cpu_percent(interval=None))
        _max_cpu = gui_state._CALIBRATION.get('max_cpu_pct', 80.0)
        if _cpu_pct >= _max_cpu:
            _reasons.append(f'CPU {_cpu_pct:.0f}% >= limit {_max_cpu:.0f}%')
        # RAM ceiling
        _ram_used_gb = _ps_hw.virtual_memory().used / 1024**3
        _max_ram_gb = gui_state._CALIBRATION.get('max_ram_gb', 56.0)
        if _ram_used_gb >= _max_ram_gb:
            _reasons.append(f'RAM {_ram_used_gb:.1f} GB >= limit {_max_ram_gb:.1f} GB')
        if not _reasons:
            return True
        _tag = f' [{label}]' if label else ''
        _backend_debug(f'HW headroom wait{_tag}: {"; ".join(_reasons)} — sleeping 5s')
        _t_hw.sleep(5)
    return False


def _wait_ollama_unload(model_name: str, timeout: int = 30) -> None:
    """Poll Ollama /api/ps until model_name is no longer listed (confirmed VRAM freed).

    Fire-and-forget keep_alive=0 requests don't guarantee the model is actually
    evicted before the next caller tries to allocate VRAM.  This tight loop ensures
    we don't proceed until the GPU driver has reclaimed the pages.
    Falls back silently if the Ollama API is unreachable (assume unloaded).
    """
    import json as _j_ou
    import time as _t_ou

    from zyg_workflows.net import safe_urlopen as _open_ou

    _deadline = _t_ou.time() + timeout
    while _t_ou.time() < _deadline:
        try:
            _raw = _open_ou(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read()
            _ps = _j_ou.loads(_raw)
            _names = [m.get('name', '') for m in _ps.get('models', [])]
            if not any(model_name.split(':')[0] in n for n in _names):
                return  # confirmed evicted
        except Exception:
            return  # API down / unreachable — assume unloaded
        _t_ou.sleep(1)
    _backend_debug(f'_wait_ollama_unload: {model_name} still present after {timeout}s — proceeding anyway')


def _read_safety_thresholds() -> dict:
    try:
        with open(_SAFETY_THRESHOLDS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _check_hardware_now() -> tuple:
    """Read live hardware metrics and check against safety_thresholds.json.
    Returns (blocked: bool, reason: str)."""
    try:
        import psutil

        thresholds = _read_safety_thresholds()
        gpu_thresh = thresholds.get('gpu', {})
        cpu_thresh = thresholds.get('cpu', {})
        ram_thresh = thresholds.get('ram', {})

        # CPU — use cached value from telemetry sampler to avoid blocking 300ms
        cpu_pct = _TELEMETRY_CACHE.get('cpu_pct') or psutil.cpu_percent(interval=None)
        if cpu_pct >= cpu_thresh.get('util_critical_pct', 95):
            return True, f'CPU critical: {cpu_pct}% >= {cpu_thresh.get("util_critical_pct")}%'

        # RAM
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        if ram_pct >= ram_thresh.get('critical_pct', 92):
            return True, f'RAM critical: {ram_pct}% >= {ram_thresh.get("critical_pct")}%'

        # GPU via telemetry cache (uses persistent pynvml handles — no init/shutdown overhead)
        try:
            _gpu_cache = _TELEMETRY_CACHE.get('gpus', [])
            for _gc in _gpu_cache:
                _util = _gc.get('utilization_pct', 0)
                _vram_total = _gc.get('memory_total_mb', 1)
                _vram_used = _gc.get('memory_used_mb', 0)
                _vram_pct = _vram_used / _vram_total * 100 if _vram_total else 0
                _temp = _gc.get('temperature_c') or 0
                _i = _gc.get('index', 0)
                if _temp >= gpu_thresh.get('temp_critical_c', 85):
                    return True, f'GPU[{_i}] temp critical: {_temp}°C >= {gpu_thresh.get("temp_critical_c")}°C'
                if _util > gpu_thresh.get('util_critical_pct', 100):
                    return True, f'GPU[{_i}] utilisation critical: {_util}% >= {gpu_thresh.get("util_critical_pct")}%'
                if _vram_pct >= gpu_thresh.get('vram_critical_pct', 93):
                    return True, f'GPU[{_i}] VRAM critical: {_vram_pct:.1f}% >= {gpu_thresh.get("vram_critical_pct")}%'
                _power_w = float(_gc.get('power_w', 0) or 0)
                _max_watts = gui_state._CALIBRATION.get('max_gpu_watts', 450.0)
                if _power_w > _max_watts:
                    return True, f'GPU[{_i}] power {_power_w:.0f}W > calibration limit {_max_watts:.0f}W'
        except Exception as _exc:
            _zyg_log.warning('gpu threshold check failed, not blocking on hardware: %s', _exc)

        return False, ''
    except Exception:
        return False, ''  # Never block on monitoring error


def _hw_monitor_loop(pipeline_id: str):
    """Background thread: checks hardware every 20s while pipeline is running."""
    pass  # (global stmt removed: names moved to gui_state)

    while True:
        job = _workflow_jobs.get(pipeline_id)
        if not job or job.get('status') not in ('running',):
            break
        blocked, reason = _check_hardware_now()
        if blocked and not gui_state._hw_block_active:
            gui_state._hw_block_active = True
            gui_state._hw_block_reason = reason
            # Log the block
            try:
                log_path = _runtime_path('clipfarm_processing_log.json')
                entries = []
                if os.path.exists(log_path):
                    with open(log_path) as _f:
                        entries = json.load(_f)
                entries.append(
                    {
                        'level': 'ERROR',
                        'agent': 'hw_monitor',
                        'pipeline_id': pipeline_id,
                        'message': f'Hardware block activated: {reason}',
                        'timestamp': _ams_iso(timespec='seconds'),
                    }
                )
                with open(log_path, 'w') as _f:
                    json.dump(entries[-500:], _f, indent=2)
            except Exception as _exc:
                _zyg_log.warning('hardware block not written to the processing log, block still active: %s', _exc)
        elif not blocked and gui_state._hw_block_active:
            # Metrics recovered — lift the block
            gui_state._hw_block_active = False
            gui_state._hw_block_reason = ''
        # Poll fast (5s) while blocked so we lift the gate quickly after VRAM is freed;
        # poll slow (20s) when everything is healthy to keep overhead low.
        time.sleep(5 if gui_state._hw_block_active else 20)
