# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared ComfyUI HTTP client used by flux_fill_service, blender_character_service,
and wan_video_service when ZYG_USE_COMFYUI=1.

The client speaks to a locally running ComfyUI server (ZYG_COMFY_HOST/ZYG_COMFY_PORT,
loopback port 8188 by default).
Workflows live in _comfy_workflows/*.json; this module loads a template, applies
a small set of substitutions, POSTs it, polls /history, and returns produced
file paths from ComfyUI's output directory.

Design notes
------------
- No mutation of workflow JSON on disk; substitutions happen on a deep-copied
  dict so concurrent submits stay isolated.
- Errors raise ComfyUIError. Callers are expected to catch and fall back to
  their existing diffusers code path (the env-var gate makes this trivial).
- 2026-08-25 (P-07): :8188 is ONE server shared by the documentary, creature,
  storyteller and contact-sheet workers. submit() therefore serialises across
  processes with an fcntl.flock on <crews>/data/runtime/comfy_<port>.lock
  (ZYG_COMFY_SUBMIT_LOCK=0 disables), and interrupt_execution() refuses to
  fire the server-wide /interrupt unless the running prompt is one THIS
  process submitted (ZYG_COMFY_GLOBAL_INTERRUPT=1 or force_global=True
  restores the old blind behaviour).
"""

from __future__ import annotations

import copy
import errno
import fcntl
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests
import logging as _zyg_logging

from zyg_workflows.bin import exe
from zyg_workflows.paths import ZYG_COMFY_INPUT, ZYG_COMFY_OUTPUT, ZYG_COMFY_ROOT, tmp_dir

_zyg_log = _zyg_logging.getLogger(__name__)


COMFY_HOST = os.environ.get('ZYG_COMFY_HOST', '127.0.0.1')
COMFY_PORT = int(os.environ.get('ZYG_COMFY_PORT', '8188'))
COMFY_OUTPUT = str(ZYG_COMFY_OUTPUT)
COMFY_INPUT = str(ZYG_COMFY_INPUT)

_WORKFLOW_DIR = Path(__file__).resolve().parent / '_comfy_workflows'
_POLL_INTERVAL_S = 0.5
_DEFAULT_TIMEOUT_S = 600
_OBJECT_INFO_CACHE: dict | None = None

_log = logging.getLogger(__name__)

# P-07: prompt ids THIS process submitted and has not yet seen finish. Only
# these may be interrupted without ZYG_COMFY_GLOBAL_INTERRUPT=1 — ComfyUI's
# /interrupt is server-wide and the server is shared.
_OWNED_PROMPT_IDS: set[str] = set()
_OWNED_LOCK = threading.Lock()

# Cross-process submit serialisation (fcntl.flock), held from POST /prompt
# until the job completes or raises. ZYG_COMFY_SUBMIT_LOCK=0 disables;
# ZYG_COMFY_SUBMIT_LOCK_PATH overrides the file; ZYG_COMFY_SUBMIT_LOCK_WAIT_S
# caps the wait (default 3600 s — a Wan job ahead of us can take 40 min; the
# effective budget is max(caller timeout_s, this) so a long job budget is
# never cut short by the env cap).
_SUBMIT_LOCK_POLL_S = 0.5
_SUBMIT_LOCK_WAIT_DEFAULT_S = 3600.0

# Timing of the most recent submit() in this process: lock/queue wait and
# execution are reported SEPARATELY so a wait behind another client can never
# masquerade as render cost (P-07 / P-13).
last_submit_timing: dict[str, Any] = {}


class ComfyUIError(RuntimeError):
    """Raised when ComfyUI submission or polling fails."""


def is_enabled() -> bool:
    """True iff ZYG_USE_COMFYUI is set to a truthy value."""
    return os.environ.get('ZYG_USE_COMFYUI', '').strip().lower() in ('1', 'true', 'yes', 'on')


def get_object_info(refresh: bool = False) -> dict:
    """Return ComfyUI /object_info (cached)."""
    global _OBJECT_INFO_CACHE
    if _OBJECT_INFO_CACHE is not None and not refresh:
        return _OBJECT_INFO_CACHE
    try:
        r = requests.get(_url('/object_info'), timeout=10)
        r.raise_for_status()
        _OBJECT_INFO_CACHE = r.json()
        return _OBJECT_INFO_CACHE
    except requests.RequestException:
        return {}


def has_node(class_type: str) -> bool:
    return class_type in get_object_info()


def list_instantid_model_files(refresh: bool = False) -> list[str]:
    """Return filenames accepted by ComfyUI InstantIDModelLoader (may be empty)."""
    info = get_object_info(refresh=refresh)
    node = info.get('InstantIDModelLoader') or {}
    required = (node.get('input') or {}).get('required') or {}
    raw = required.get('instantid_file')
    if isinstance(raw, (list, tuple)) and raw:
        first = raw[0]
        if isinstance(first, (list, tuple)):
            return [str(x) for x in first if x]
        return [str(first)]
    return []


def resolve_instantid_model_file(preferred: str | None = None) -> str | None:
    """Pick an InstantID weight file that ComfyUI will accept."""
    available = list_instantid_model_files()
    if not available:
        return None
    if preferred and preferred in available:
        return preferred
    for cand in (
        preferred,
        'instantid_sdxl.safetensors',
        'ip-adapter.bin',
    ):
        if cand and cand in available:
            return cand
    return available[0]


def server_reachable(timeout_s: float = 1.5) -> bool:
    """Quick liveness probe — used to short-circuit the ComfyUI path if the
    server isn't running, so callers fall back to their diffusers code."""
    try:
        r = requests.get(_url('/system_stats'), timeout=timeout_s)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _keep_models_loaded() -> bool:
    return os.environ.get('ZYG_COMFY_KEEP_LOADED', '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def comfy_server_pid() -> int | None:
    """Return ComfyUI main.py PID if running."""
    try:
        import subprocess as _sp

        _pg = _sp.run(
            ['pgrep', '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
            capture_output=True,
            timeout=5,
            text=True,
        )
        for _line in _pg.stdout.split():
            if _line.strip().isdigit():
                return int(_line.strip())
    except Exception as _exc:
        _zyg_log.debug('comfy server pid probe failed: %s', _exc)
    return None


def comfy_process_rss_mb(pid: int | None = None) -> int:
    """Resident RAM (MiB) for the ComfyUI server process."""
    pid = pid or comfy_server_pid()
    if not pid:
        return 0
    try:
        with open(f'/proc/{pid}/status') as _f:
            for _line in _f:
                if _line.startswith('VmRSS:'):
                    return int(_line.split()[1]) // 1024
    except OSError as _exc:
        _zyg_log.debug('process RSS read failed for pid %s: %s', pid, _exc)
    return 0


def comfy_gpu_used_mb(pid: int | None = None) -> int:
    """VRAM MiB used by the ComfyUI server process (0 if not on GPU)."""
    pid = pid or comfy_server_pid()
    if not pid:
        return 0
    try:
        import subprocess as _sp

        _r = _sp.run(
            [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        for _line in _r.stdout.strip().splitlines():
            _parts = [p.strip() for p in _line.split(',')]
            if len(_parts) == 2 and _parts[0].isdigit() and int(_parts[0]) == pid:
                return int(_parts[1])
    except Exception as _exc:
        _zyg_log.debug('nvidia-smi vram probe failed: %s', _exc)
    return 0


def queue_is_busy(timeout_s: float = 3.0) -> bool:
    """True when Comfy has a running or pending workflow."""
    if not server_reachable(timeout_s=1.0):
        return False
    try:
        r = requests.get(_url('/queue'), timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
        return bool(data.get('queue_running') or data.get('queue_pending'))
    except requests.RequestException:
        return False


def free_vram(unload_models: bool = True, free_memory: bool = True, timeout_s: float = 5.0) -> bool:
    """Ask ComfyUI to drop cached models and free GPU/executor memory.

    Returns True on a 200 response, False on any failure (caller can ignore).
    ComfyUI's /free endpoint sets queue flags processed by the prompt worker
    (unload models, reset executor cache, gc + empty CUDA cache). The worker is
    woken immediately via notify(), but gc runs on a ~10s interval — use
    :func:`release_memory` when callers need to wait for RAM/VRAM to drop.
    """
    if not server_reachable(timeout_s=1.0):
        return False
    try:
        r = requests.post(
            _url('/free'),
            json={'unload_models': bool(unload_models), 'free_memory': bool(free_memory)},
            timeout=timeout_s,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def _wait_for_queue_idle(timeout_s: float = 120.0, poll_s: float = 0.5) -> bool:
    deadline = time.monotonic() + max(1.0, timeout_s)
    while time.monotonic() < deadline:
        if not queue_is_busy():
            return True
        time.sleep(poll_s)
    return not queue_is_busy()


def wait_for_idle(timeout_s: float = 120.0, poll_s: float = 0.5) -> bool:
    """Block until the ComfyUI queue has nothing running or pending.

    Public wrapper of :func:`_wait_for_queue_idle` — the polite alternative to
    a global ``/interrupt`` when a caller needs the shared server quiet (P-07).
    Returns True when idle, False when still busy after ``timeout_s``. An
    unreachable server counts as idle (there is nothing to wait for).
    """
    return _wait_for_queue_idle(timeout_s=timeout_s, poll_s=poll_s)


def restart_server(timeout_s: float = 90.0, log_fn=None) -> bool:
    """Restart the headless ComfyUI server (drops all host RAM + VRAM)."""

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    _start = ZYG_COMFY_ROOT / 'start_server.sh'
    if not _start.is_file():
        _log('Comfy restart skipped — start_server.sh not found')
        return False
    try:
        import subprocess as _sp

        _sp.run(
            [exe('pkill'), '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
            timeout=10,
        )
        time.sleep(2)
        with open(os.devnull, 'w') as _devnull:
            _sp.Popen(
                ['nohup', str(_start)],
                stdout=_devnull,
                stderr=_devnull,
                start_new_session=True,
            )
        _log('ComfyUI restart issued — waiting for /system_stats…')
    except Exception as exc:
        _log(f'Comfy restart failed: {exc}')
        return False

    deadline = time.monotonic() + max(5.0, timeout_s)
    while time.monotonic() < deadline:
        if server_reachable(timeout_s=2.0):
            _log(f'ComfyUI back online (RSS ~{comfy_process_rss_mb()} MiB)')
            return True
        time.sleep(1.5)
    _log('ComfyUI restart timed out')
    return False


def release_memory(
    wait: bool = True,
    timeout_s: float = 45.0,
    log_fn=None,
    max_idle_rss_mb: float | None = None,
    restart_if_stuck: bool | None = None,
) -> dict:
    """Unload Comfy models/cache and optionally wait until host RAM drops.

    Returns a summary dict with ``ok``, ``rss_mb_before/after``, ``gpu_mb_after``,
    and ``restarted`` keys.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    summary = {
        'ok': False,
        'skipped': False,
        'rss_mb_before': 0,
        'rss_mb_after': 0,
        'gpu_mb_after': 0,
        'restarted': False,
    }

    if _keep_models_loaded():
        summary['skipped'] = True
        summary['ok'] = True
        return summary

    if not server_reachable(timeout_s=1.5):
        return summary

    if max_idle_rss_mb is None:
        max_idle_rss_mb = float(os.environ.get('ZYG_COMFY_MAX_IDLE_RAM_MB', '4096') or '4096')
    if restart_if_stuck is None:
        restart_if_stuck = os.environ.get('ZYG_COMFY_RESTART_ON_STUCK', '1').strip().lower() in (
            '1',
            'true',
            'yes',
            'on',
        )

    pid = comfy_server_pid()
    summary['rss_mb_before'] = comfy_process_rss_mb(pid)

    if wait:
        _wait_for_queue_idle(timeout_s=min(timeout_s, 120.0))

    # Comfy gc_collect_interval is 10s — allow two passes for unload + gc.
    _gc_wait = float(os.environ.get('ZYG_COMFY_FREE_GC_SEC', '12') or '12')
    _rounds = max(1, int(os.environ.get('ZYG_COMFY_FREE_ROUNDS', '2') or '2'))
    _posted = False
    for _round in range(_rounds):
        if free_vram():
            _posted = True
            if wait and _round < _rounds - 1:
                time.sleep(_gc_wait)
        elif not _posted:
            break

    if wait and _posted:
        time.sleep(_gc_wait)

    summary['rss_mb_after'] = comfy_process_rss_mb(pid)
    summary['gpu_mb_after'] = comfy_gpu_used_mb(pid)
    summary['ok'] = _posted

    if restart_if_stuck and summary['rss_mb_after'] > max_idle_rss_mb and not queue_is_busy():
        _log(
            f'Comfy still holding {summary["rss_mb_after"]} MiB RAM '
            f'(limit {max_idle_rss_mb:.0f} MiB, GPU {summary["gpu_mb_after"]} MiB) — restarting server'
        )
        if restart_server(log_fn=_log):
            summary['restarted'] = True
            summary['rss_mb_after'] = comfy_process_rss_mb()
            summary['gpu_mb_after'] = comfy_gpu_used_mb()
            summary['ok'] = True
        else:
            summary['ok'] = False

    return summary


def wait_for_free_vram_gb(
    min_free_gb: float,
    timeout_s: float = 120.0,
    poll_s: float = 2.0,
    try_evict: bool = True,
    log_fn=None,
) -> tuple[bool, float]:
    """Block until at least *min_free_gb* of CUDA VRAM is free.

    If *try_evict* is True, an initial ComfyUI /free call is issued before
    polling. Returns ``(ok, free_gb_at_return)``.
    """
    try:
        import torch as _torch
    except ImportError:
        return True, float('inf')
    if not _torch.cuda.is_available():
        return True, float('inf')

    def _free_gb() -> float:
        try:
            _torch.cuda.empty_cache()
            free_b, _ = _torch.cuda.mem_get_info(0)
            return free_b / 1e9
        except Exception:
            return -1.0

    if try_evict:
        evicted = free_vram()
        if evicted and log_fn:
            log_fn('ComfyUI /free called — waiting for VRAM eviction…')

    deadline = time.monotonic() + max(1.0, timeout_s)
    free_gb = _free_gb()
    while time.monotonic() < deadline:
        if free_gb >= min_free_gb:
            return True, free_gb
        time.sleep(poll_s)
        free_gb = _free_gb()
    return free_gb >= min_free_gb, free_gb


def load_workflow(name: str) -> dict:
    """Load a workflow template by name (without .json extension)."""
    path = _WORKFLOW_DIR / f'{name}.json'
    if not path.is_file():
        raise ComfyUIError(f'workflow template not found: {path}')
    with open(path) as f:
        return json.load(f)


def _global_interrupt_allowed() -> bool:
    return os.environ.get('ZYG_COMFY_GLOBAL_INTERRUPT', '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def _track_prompt(prompt_id: str) -> None:
    with _OWNED_LOCK:
        _OWNED_PROMPT_IDS.add(prompt_id)


def _untrack_prompt(prompt_id: str) -> None:
    with _OWNED_LOCK:
        _OWNED_PROMPT_IDS.discard(prompt_id)


def owned_prompt_ids() -> set[str]:
    """Prompt ids THIS process has submitted and not yet seen finish."""
    with _OWNED_LOCK:
        return set(_OWNED_PROMPT_IDS)


def queue_snapshot(timeout_s: float = 3.0) -> dict[str, list[str]]:
    """``{'running': [prompt_id, …], 'pending': [prompt_id, …]}`` from /queue.

    Returns ``{}`` when the server cannot be read. ComfyUI queue entries are
    ``[number, prompt_id, prompt, extra_data, outputs_to_execute]``.
    """
    try:
        r = requests.get(_url('/queue'), timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    snap: dict[str, list[str]] = {'running': [], 'pending': []}
    for key in ('running', 'pending'):
        for item in data.get(f'queue_{key}') or []:
            if isinstance(item, (list, tuple)) and len(item) > 1 and item[1]:
                snap[key].append(str(item[1]))
    return snap


def _post_interrupt(timeout_s: float) -> bool:
    try:
        r = requests.post(_url('/interrupt'), timeout=timeout_s)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _delete_pending(prompt_id: str, timeout_s: float) -> bool:
    """Remove one PENDING prompt from the queue (never touches a running job)."""
    try:
        r = requests.post(_url('/queue'), json={'delete': [prompt_id]}, timeout=timeout_s)
        return r.status_code == 200
    except requests.RequestException:
        return False


def interrupt_execution(
    timeout_s: float = 5.0,
    prompt_id: str | None = None,
    force_global: bool = False,
) -> bool:
    """Interrupt a running ComfyUI prompt — but only one of OURS (best-effort).

    ComfyUI's ``/interrupt`` is server-wide and :8188 is shared by the
    documentary, creature, storyteller and contact-sheet workers. P-07: Stage
    3.5 exclusivity fired it blind ("Global interrupt (no prompt_id
    specified)") 14 s after another client's 2.5-minute cell had finished —
    one bad timing away from killing someone else's render.

    Rules
    -----
    * ``force_global=True`` or env ``ZYG_COMFY_GLOBAL_INTERRUPT=1`` → the old
      behaviour: POST /interrupt unconditionally.
    * ``prompt_id`` given → interrupted only if THIS process submitted it (see
      :func:`owned_prompt_ids`) and it is currently running. An owned prompt
      that is still *pending* is removed from the queue instead (that never
      touches another client's job) and counts as success.
    * ``prompt_id`` omitted → resolved to the running prompt(s) when ALL of
      them are ours (the blocking-render watchdog, the pause path and the GUI
      halt call this with no id from the process that owns the render);
      otherwise declined.

    Every decline returns False and logs a WARNING saying why.
    """
    if not server_reachable(timeout_s=1.0):
        return False
    if force_global or _global_interrupt_allowed():
        ok = _post_interrupt(timeout_s)
        _log.info(
            'comfy interrupt: GLOBAL /interrupt (%s) -> %s',
            'force_global' if force_global else 'ZYG_COMFY_GLOBAL_INTERRUPT=1',
            'accepted' if ok else 'refused',
        )
        return ok

    owned = owned_prompt_ids()
    snap = queue_snapshot(timeout_s=timeout_s)
    running = snap.get('running', [])
    pending = snap.get('pending', [])

    if prompt_id is None:
        if not running:
            # Not a real decline — there is nothing to interrupt. INFO, because
            # vram_manager's Stage 3.5 sweep calls this on every run start.
            _log.info(
                'comfy interrupt: nothing is running on :%d — no-op (this process owns %d in-flight prompt(s))',
                COMFY_PORT,
                len(owned),
            )
            return False
        foreign = [p for p in running if p not in owned]
        if foreign:
            _log.warning(
                'comfy interrupt declined: running prompt(s) %s belong to another client '
                '(this process owns %s). Pass prompt_id=<yours>, force_global=True, or set '
                'ZYG_COMFY_GLOBAL_INTERRUPT=1 to override.',
                [p[:8] for p in foreign],
                [p[:8] for p in sorted(owned)] or 'nothing',
            )
            return False
        ok = _post_interrupt(timeout_s)
        _log.info(
            'comfy interrupt: our running prompt(s) %s -> %s', [p[:8] for p in running], 'accepted' if ok else 'refused'
        )
        return ok

    if prompt_id not in owned:
        _log.warning('comfy interrupt declined: prompt %s was not submitted by this process', prompt_id[:8])
        return False
    if not snap:
        # /queue could not be read (transient failure) but ownership is already
        # proven — do NOT class our prompt as "neither running nor pending" and
        # leave it as a zombie. Fire /interrupt (harmless on an idle server;
        # with the submit lock the running job can only be ours) and also
        # dequeue it in case it was still pending.
        ok = _post_interrupt(timeout_s)
        _delete_pending(prompt_id, timeout_s)
        _log.warning(
            'comfy interrupt: /queue unreadable — our prompt %s interrupted on ownership alone -> %s',
            prompt_id[:8],
            'accepted' if ok else 'refused',
        )
        return ok
    if prompt_id in running:
        ok = _post_interrupt(timeout_s)
        _log.info('comfy interrupt: our prompt %s -> %s', prompt_id[:8], 'accepted' if ok else 'refused')
        return ok
    if prompt_id in pending:
        ok = _delete_pending(prompt_id, timeout_s)
        _log.info(
            'comfy interrupt: our prompt %s was pending, not running — %s from the queue',
            prompt_id[:8],
            'removed' if ok else 'could NOT be removed',
        )
        return ok
    _log.warning(
        'comfy interrupt declined: our prompt %s is neither running nor pending (already finished?)', prompt_id[:8]
    )
    return False


def _default_should_abort() -> bool:
    try:
        from zyg_workflows import pipeline_control as _pc

        return _pc.halt_requested()
    except ImportError:
        return False


def _submit_lock_enabled() -> bool:
    return os.environ.get('ZYG_COMFY_SUBMIT_LOCK', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def submit_lock_path() -> str:
    """``<crews>/data/runtime/comfy_<port>.lock`` — the runtime dir that already
    holds scholarly_stills_backend's ``scholarly_gpu.lock``; falls back to
    ``$ZYG_TMP_DIR/zyg_comfy_<port>.lock`` when that dir is not writable.
    ``ZYG_COMFY_SUBMIT_LOCK_PATH`` overrides."""
    env = os.environ.get('ZYG_COMFY_SUBMIT_LOCK_PATH', '').strip()
    if env:
        return env
    runtime = Path(__file__).resolve().parent / 'data' / 'runtime'
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        if os.access(str(runtime), os.W_OK):
            return str(runtime / f'comfy_{COMFY_PORT}.lock')
    except OSError as _exc:
        _zyg_log.warning('comfy lock dir %s not usable, falling back to the tmp dir: %s', runtime, _exc)
    return str(tmp_dir() / f'zyg_comfy_{COMFY_PORT}.lock')


def _submit_lock_wait_s() -> float:
    """``ZYG_COMFY_SUBMIT_LOCK_WAIT_S`` as a float. An unparseable or
    non-finite value logs a warning and falls back to the 3600 s default —
    a bad env value must never raise ValueError out of submit()."""
    raw = os.environ.get('ZYG_COMFY_SUBMIT_LOCK_WAIT_S', '').strip()
    if not raw:
        return _SUBMIT_LOCK_WAIT_DEFAULT_S
    try:
        val = float(raw)
    except ValueError:
        val = float('nan')
    if val != val or val in (float('inf'), float('-inf')):
        _log.warning(
            'ZYG_COMFY_SUBMIT_LOCK_WAIT_S=%r is not a finite number — using the default %.0fs',
            raw,
            _SUBMIT_LOCK_WAIT_DEFAULT_S,
        )
        return _SUBMIT_LOCK_WAIT_DEFAULT_S
    return val


def _acquire_submit_lock(should_abort=None, timeout_s: float | None = None) -> int | None:
    """Block until this process holds the cross-process submit lock.

    Returns the lock fd (release with :func:`_release_submit_lock`), or None
    when the lock is disabled or the file cannot be opened (the submit then
    proceeds unserialised — logged). ``should_abort`` is polled while waiting
    so a halt request is honoured before the POST. Raises ComfyUIError on
    abort, or when the wait budget runs out. The budget is
    ``max(timeout_s, ZYG_COMFY_SUBMIT_LOCK_WAIT_S)`` (env default 3600) so the
    caller's own job budget bounds it and is never cut short by the env cap.
    The descriptor is closed on EVERY non-acquired exit, including a
    ``should_abort()`` that raises.
    """
    if not _submit_lock_enabled():
        return None
    path = submit_lock_path()
    _created = not os.path.exists(path)
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM):
            _log.warning('comfy submit lock unavailable (%s: %s) — submitting unserialised', path, exc)
            return None
        # Created by another uid without write access for us: flock(2) works
        # on a read-only descriptor, so still serialise instead of giving up.
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError as exc2:
            _log.warning('comfy submit lock unavailable (%s: %s) — submitting unserialised', path, exc2)
            return None
    else:
        if _created:
            try:
                # 0o644, not the 0o666 this used to force: a second uid only needs to READ the
                # file to flock it, which is exactly what the EACCES branch above already does,
                # so world-write bought nothing and let any local user truncate the lock.
                os.chmod(path, 0o644)  # best-effort: the umask may have masked the open(2) mode
            except OSError as _exc:
                _zyg_log.debug('submit lock chmod 0o644 skipped: %s', _exc)
    wait_s = _submit_lock_wait_s()
    if timeout_s is not None:
        try:
            wait_s = max(wait_s, float(timeout_s))
        except (TypeError, ValueError) as _exc:
            _zyg_log.warning('invalid submit lock timeout %r, keeping %.1fs: %s', timeout_s, wait_s, _exc)
    t0 = time.monotonic()
    deadline = t0 + max(1.0, wait_s)
    announced = False
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                if announced:
                    _log.info('comfy submit lock acquired after %.1fs', time.monotonic() - t0)
                return fd
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    _log.warning('comfy submit lock failed (%s: %s) — submitting unserialised', path, exc)
                    return None
            if callable(should_abort) and should_abort():
                raise ComfyUIError('interrupted — pipeline halt requested while waiting for the ComfyUI submit lock')
            if time.monotonic() >= deadline:
                raise ComfyUIError(
                    f'timed out after {wait_s:.0f}s waiting for the ComfyUI submit lock '
                    f'({path}) — another client is still rendering on :{COMFY_PORT}'
                )
            if not announced and time.monotonic() - t0 > 2.0:
                announced = True
                _log.info('comfy submit lock busy (%s) — another client is rendering on :%d, waiting', path, COMFY_PORT)
            time.sleep(_SUBMIT_LOCK_POLL_S)
    finally:
        # Declined flock, abort, timeout, or ANY exception from should_abort()
        # / sleep (KeyboardInterrupt, SystemExit included): never leak the fd.
        if not acquired:
            try:
                os.close(fd)
            except OSError as _exc:
                _zyg_log.debug('submit lock fd close skipped: %s', _exc)


def _release_submit_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as _exc:
        _zyg_log.debug('submit lock flock release skipped: %s', _exc)
    try:
        os.close(fd)
    except OSError as _exc:
        _zyg_log.debug('submit lock fd close skipped: %s', _exc)


def submit(
    workflow: dict,
    overrides: dict[str, dict[str, Any]] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    should_abort=None,
) -> list[str]:
    """Submit a workflow to ComfyUI and block until it completes.

    Parameters
    ----------
    workflow : dict
        The workflow template (from load_workflow).
    overrides : dict[str, dict[str, Any]] | None
        Per-node input overrides keyed by node id. E.g.
        ``{"6": {"text": "a cat"}, "31": {"seed": 1234}}`` patches
        nodes 6 and 31 before submit. Missing keys preserve template defaults.
    timeout_s : float
        Total wall-clock budget for the job. Raises ComfyUIError on timeout.
    should_abort : callable | None
        If provided, called each poll interval; when True, interrupts ComfyUI and
        raises ComfyUIError. Defaults to :func:`pipeline_control.halt_requested`.

    Returns
    -------
    list[str]
        Absolute paths to output files produced by SaveImage / VHS_VideoCombine
        nodes, in the order ComfyUI reported them.
    """
    wf = copy.deepcopy(workflow)
    if overrides:
        for node_id, patch in overrides.items():
            if node_id not in wf:
                raise ComfyUIError(f'override references unknown node id: {node_id}')
            wf[node_id].setdefault('inputs', {}).update(patch)

    # fixed id lets the preview watcher subscribe to THIS submission's live previews
    client_id = os.environ.get('ZYG_COMFY_CLIENT_ID', '').strip() or str(uuid.uuid4())
    body = {'prompt': wf, 'client_id': client_id}
    _abort = should_abort if callable(should_abort) else _default_should_abort

    # P-07: cross-process serialisation. Held from the POST until the job has
    # completed (or raised) and the INSTANT post-job /free has been POSTed, so
    # the next holder starts on a server already told to unload. The waiting
    # part of release_memory (idle wait, gc rounds, restart-if-stuck — a minute
    # or more) runs in the finally block AFTER the lock is released so it never
    # blocks another client from even queueing.
    _t_lock0 = time.monotonic()
    lock_fd = _acquire_submit_lock(_abort, timeout_s=timeout_s)
    _lock_wait_s = time.monotonic() - _t_lock0
    prompt_id: str | None = None
    _post_release: dict[str, bool] = {}
    _t_exec0 = time.monotonic()
    try:
        try:
            r = requests.post(_url('/prompt'), json=body, timeout=30)
        except requests.RequestException as exc:
            raise ComfyUIError(f'submit failed: {exc}') from exc

        if r.status_code != 200:
            try:
                err = r.json()
            except ValueError:
                err = {'raw': r.text[:1000]}
            node_errs = err.get('node_errors') or {}
            msg = err.get('error', {}).get('message') or err.get('error') or 'unknown error'
            detail_lines = [f'submit rejected ({r.status_code}): {msg}']
            for nid, ne in node_errs.items():
                for e in ne.get('errors', []):
                    detail_lines.append(f'  node {nid} [{ne.get("class_type", "?")}]: {e.get("message", e)}')
            raise ComfyUIError('\n'.join(detail_lines))

        payload = r.json()
        prompt_id = payload.get('prompt_id')
        if not prompt_id:
            raise ComfyUIError(f'no prompt_id in response: {payload}')
        _track_prompt(prompt_id)
        return _poll_until_complete(prompt_id, timeout_s, _abort, post_release=_post_release)
    finally:
        _exec_s = time.monotonic() - _t_exec0
        if prompt_id:
            _untrack_prompt(prompt_id)
        _release_submit_lock(lock_fd)
        last_submit_timing.update(
            {
                'prompt_id': prompt_id,
                'lock_wait_s': round(_lock_wait_s, 2),
                'exec_s': round(_exec_s, 2),
            }
        )
        _log.debug(
            'comfy submit %s: lock wait %.1fs, execution %.1fs', (prompt_id or '(rejected)')[:8], _lock_wait_s, _exec_s
        )
        if _post_release.get('needed'):
            # Lock released: the slow part of the post-job release (queue idle
            # wait + gc rounds + restart-if-stuck) no longer holds other
            # clients back. Best-effort — the outputs are already produced.
            try:
                release_memory(wait=True, log_fn=None)
            except Exception as exc:  # housekeeping must not eat the result
                _log.warning('comfy submit %s: post-job release_memory failed — %s', (prompt_id or '?')[:8], exc)


def _poll_until_complete(prompt_id: str, timeout_s: float, _abort, post_release: dict | None = None) -> list[str]:
    """Poll /history/<prompt_id> until completed / errored / timed out.

    Helper of :func:`submit`; runs with the submit lock held. On abort it
    interrupts (or dequeues) OUR prompt only. On timeout it also interrupts
    our prompt best-effort so the next lock holder does not inherit a zombie.

    On completion only the instant ``/free`` POST happens here (under the
    lock). When ``post_release`` is given, ``post_release['needed'] = True``
    tells :func:`submit` to run the slow ``release_memory(wait=True)`` after
    the lock is released; without it (direct callers) the old in-line wait
    is kept.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _abort():
            # Our prompt only: running -> /interrupt, still pending -> dequeued.
            interrupt_execution(prompt_id=prompt_id)
            free_vram()
            raise ComfyUIError('interrupted — pipeline halt requested')
        try:
            h = requests.get(_url(f'/history/{prompt_id}'), timeout=10)
            h.raise_for_status()
        except requests.RequestException as exc:
            raise ComfyUIError(f'history poll failed: {exc}') from exc
        hist = h.json().get(prompt_id)
        if hist and hist.get('status', {}).get('completed'):
            outputs = _collect_outputs(hist)
            # ComfyUI keeps loaded checkpoints in VRAM until explicitly evicted.
            # Free by default so idle GPU drops from ~35 GB to near-zero after each job.
            if not _keep_models_loaded():
                free_vram()  # instant POST only — the wait/restart part must not hold the lock
                if post_release is not None:
                    post_release['needed'] = True
                else:
                    release_memory(wait=True, log_fn=None)
            return outputs
        if hist and hist.get('status', {}).get('status_str') == 'error':
            status_blob = hist.get('status', {})
            detail_lines = ['workflow errored']
            # Surface execution_error / execution_interrupted from status.messages
            for msg in status_blob.get('messages', []) or []:
                if not isinstance(msg, (list, tuple)) or len(msg) < 2:
                    continue
                ev_type, payload = msg[0], msg[1]
                if ev_type in ('execution_error', 'execution_interrupted'):
                    nid = payload.get('node_id', '?')
                    nty = payload.get('node_type', '?')
                    exm = payload.get('exception_message') or payload.get('exception_type') or 'unknown'
                    detail_lines.append(f'  node {nid} [{nty}]: {exm}')
                    # Include first 3 lines of traceback if present
                    tb = payload.get('traceback') or []
                    if isinstance(tb, list):
                        for tb_line in tb[:3]:
                            detail_lines.append(f'    {str(tb_line)[:200]}')
            # Also surface per-output errors recorded against nodes
            for nid, node_out in (hist.get('outputs') or {}).items():
                err = node_out.get('error')
                if err:
                    detail_lines.append(f'  node {nid} output error: {str(err)[:200]}')
            raise ComfyUIError('\n'.join(detail_lines))
        time.sleep(_POLL_INTERVAL_S)

    if interrupt_execution(prompt_id=prompt_id):
        _log.warning(
            'comfy submit: prompt %s timed out after %.0fs — interrupted it so the '
            'next client does not queue behind a zombie',
            prompt_id[:8],
            timeout_s,
        )
    raise ComfyUIError(f'timeout after {timeout_s}s waiting for prompt {prompt_id}')


def stage_input_image(src_path: str) -> str:
    """Copy/symlink a local image into ComfyUI's input directory so LoadImage
    nodes can reach it by basename. Returns the basename to use in workflow."""
    src = Path(src_path)
    if not src.is_file():
        raise ComfyUIError(f'input image not found: {src_path}')
    os.makedirs(COMFY_INPUT, exist_ok=True)
    dst = Path(COMFY_INPUT) / f'{uuid.uuid4().hex[:8]}_{src.name}'
    try:
        os.symlink(src.resolve(), dst)
    except (OSError, FileExistsError):
        import shutil

        shutil.copy2(src, dst)
    return dst.name


def _collect_outputs(history_entry: dict) -> list[str]:
    """Extract absolute file paths from a completed history entry."""
    out: list[str] = []
    for node_out in (history_entry.get('outputs') or {}).values():
        for key in ('images', 'gifs', 'videos', 'audio'):
            for item in node_out.get(key, []):
                subfolder = item.get('subfolder', '')
                filename = item.get('filename', '')
                if not filename:
                    continue
                full = Path(COMFY_OUTPUT) / subfolder / filename
                out.append(str(full))
    return out


def _url(path: str) -> str:
    return f'http://{COMFY_HOST}:{COMFY_PORT}{path}'
