# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VRAM hand-off plumbing between ComfyUI and the boundary VLM judge.

Added 2026-07-30 for the two-tier render-inspection architecture: at pipeline
pause points ("boundary"), the strongest quantized Qwen3-VL judge needs the
GPU to itself.  ComfyUI's cached models are OFFLOADED first via its /free
endpoint, the judge runs, and ComfyUI lazily reloads models on the next
queued job (~1-3 min swap cost) — so releasing the GPU afterwards requires
NO action from us.

Live-server facts this module relies on (verified 2026-07-30 against
ComfyUI 0.22.0 on the loopback port 8188, source ai-models/comfyui/server.py:1019):

- ``POST /free`` with ``{"unload_models": true, "free_memory": true}`` sets
  queue flags that the prompt worker processes asynchronously (unload models,
  reset executor cache, gc + empty CUDA cache).  A 200 response does NOT mean
  memory is already free — we must poll nvidia-smi afterwards.
- The box is multi-tenant: musubi LoRA training and the transcriber hold
  their own VRAM that will NEVER free.  All "did the offload work" checks
  therefore measure the DELTA on ComfyUI's own PID (per-process
  ``nvidia-smi --query-compute-apps``), never absolute free VRAM.
- ``GET /queue`` -> ``queue_running`` non-empty means a job is actively
  sampling.  Freeing mid-sample kills renders, so :func:`gpu_exclusive`
  refuses (raises :class:`ComfySamplingActiveError`) in that case.

Typical use::

    from zyg_workflows.comfy_offload import gpu_exclusive, ComfySamplingActiveError
    try:
        with gpu_exclusive(min_free_gb=20, log_fn=log) as free_gb:
            model = pick_judge_tier(free_gb)   # downshift if co-tenant squeezed us
            run_judge(model, frames)
    except ComfySamplingActiveError:
        ...  # defer the judge pass; a render is mid-sample

House style: log_fn plumbed through, lazy imports, fail-safe returns.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
import logging as _zyg_logging

from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


DEFAULT_SERVER = os.environ.get(
    'ZYG_COMFY_SERVER',
    '{}:{}'.format(
        os.environ.get('ZYG_COMFY_HOST', '127.0.0.1'),
        os.environ.get('ZYG_COMFY_PORT', '8188'),
    ),
)

# ComfyUI keeps a small idle CUDA context (~0.4 GB observed) even with every
# model unloaded — per-PID usage at or below this counts as "fully offloaded".
_IDLE_FLOOR_MB = 1024

_POLL_S = 1.0


class ComfySamplingActiveError(RuntimeError):
    """Raised by gpu_exclusive when ComfyUI is actively sampling a job.

    Freeing VRAM mid-sample kills the render; callers should defer the
    judge pass and retry at the next pipeline pause point.
    """


def _log(log_fn, msg: str) -> None:
    try:
        if log_fn:
            log_fn(msg)
        else:
            _zyg_log.info(f'[comfy_offload] {msg}')
    except Exception as _exc:
        _zyg_log.debug('log emit skipped: %s', _exc)


def _url(server: str, path: str) -> str:
    server = (server or DEFAULT_SERVER).strip()
    if not server.startswith('http'):
        server = 'http://' + server
    return server.rstrip('/') + path


# --------------------------------------------------------------------------
# nvidia-smi probes (fail-safe: None / 0 on any error)
# --------------------------------------------------------------------------


def gpu_free_gb() -> float | None:
    """Free VRAM on GPU 0 in GB via nvidia-smi.  None if the query fails."""
    try:
        import subprocess as _sp

        r = _sp.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        line = r.stdout.strip().splitlines()[0].strip()
        return float(line) / 1024.0
    except Exception:
        return None


def _gpu_used_mb_by_pid(pid: int) -> int:
    """VRAM MiB held by one PID (nvidia-smi --query-compute-apps). 0 on error."""
    if not pid:
        return 0
    try:
        import subprocess as _sp

        r = _sp.run(
            [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(',')]
            if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == pid:
                return int(parts[1])
    except Exception as _exc:
        _zyg_log.warning('nvidia-smi compute-apps query failed, reporting 0 MiB: %s', _exc)
    return 0


def comfy_server_pid() -> int | None:
    """PID of the headless ComfyUI server (pgrep), None if not running."""
    try:
        import subprocess as _sp

        r = _sp.run(
            ['pgrep', '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
            capture_output=True,
            timeout=5,
            text=True,
        )
        for tok in r.stdout.split():
            if tok.strip().isdigit():
                return int(tok.strip())
    except Exception as _exc:
        _zyg_log.warning('pgrep for the comfy server failed, reporting no server: %s', _exc)
    return None


# --------------------------------------------------------------------------
# ComfyUI HTTP probes
# --------------------------------------------------------------------------


def comfy_is_sampling(server: str = DEFAULT_SERVER) -> bool:
    """True when ComfyUI has a job actively running (GET /queue queue_running).

    Fail-safe direction is REFUSE: if the server is reachable but /queue
    cannot be read/parsed, assume sampling (True) so gpu_exclusive will not
    free VRAM under an ambiguous render.  If the server is entirely down,
    nothing can be sampling — return False.
    """
    try:
        import requests

        r = requests.get(_url(server, '/queue'), timeout=5)
        r.raise_for_status()
        return bool(r.json().get('queue_running'))
    except Exception as _exc:
        _zyg_log.debug('comfy /queue probe failed, falling back to /system_stats: %s', _exc)
    # /queue failed — distinguish "server down" from "server wedged/odd".
    try:
        import requests

        r = requests.get(_url(server, '/system_stats'), timeout=3)
        return r.status_code == 200  # reachable but /queue broken -> refuse
    except Exception:
        return False  # server down -> nothing is sampling


def comfy_free(server: str = DEFAULT_SERVER, unload_models: bool = True, timeout_s: float = 120, log_fn=None) -> bool:
    """POST ComfyUI /free and poll until its OWN VRAM usage drops.

    /free only sets flags for the prompt worker (verified server.py:1019),
    so this polls nvidia-smi per-PID afterwards.  Multi-tenant safe: only
    ComfyUI's PID is measured — the musubi training / transcriber
    allocations are other PIDs and are expected NOT to move.

    Returns True once ComfyUI's usage is at/below the idle floor
    (~1 GB CUDA context) or has dropped by >=75% of what it held; False on
    POST failure or poll timeout.  Fail-safe: never raises.
    """
    pid = comfy_server_pid()
    start_mb = _gpu_used_mb_by_pid(pid) if pid else 0
    _log(log_fn, f'comfy_free: server={server} pid={pid} holds {start_mb} MiB')

    try:
        import requests

        r = requests.post(
            _url(server, '/free'),
            json={'unload_models': bool(unload_models), 'free_memory': True},
            timeout=10,
        )
        if r.status_code != 200:
            _log(log_fn, f'comfy_free: POST /free -> HTTP {r.status_code}')
            return False
    except Exception as e:
        _log(log_fn, f'comfy_free: POST /free failed ({e})')
        return False

    if start_mb <= _IDLE_FLOOR_MB:
        _log(log_fn, 'comfy_free: already at idle floor — nothing to wait for')
        return True

    target_mb = max(_IDLE_FLOOR_MB, int(start_mb * 0.25))
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while time.monotonic() < deadline:
        used = _gpu_used_mb_by_pid(pid)
        if used <= target_mb:
            _log(log_fn, f'comfy_free: offloaded {start_mb - used} MiB (pid {pid}: {start_mb} -> {used} MiB)')
            return True
        time.sleep(_POLL_S)

    used = _gpu_used_mb_by_pid(pid)
    _log(
        log_fn,
        f'comfy_free: TIMEOUT after {timeout_s}s — pid {pid} still holds '
        f'{used} MiB (started {start_mb}, wanted <= {target_mb})',
    )
    return False


def wait_for_vram(min_free_gb: float, timeout_s: float = 180, log_fn=None) -> bool:
    """Poll nvidia-smi until >= min_free_gb GB are free.  False on timeout.

    Absolute free VRAM (not per-PID): callers use this AFTER comfy_free()
    to size the judge model.  A co-tenant (LoRA training ~25 GB) can make
    the target permanently unreachable — that is a normal outcome here,
    handled by gpu_exclusive's downshift path.
    """
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while time.monotonic() < deadline:
        free = gpu_free_gb()
        if free is not None and free >= float(min_free_gb):
            _log(log_fn, f'wait_for_vram: {free:.1f} GB free (target {min_free_gb})')
            return True
        time.sleep(_POLL_S)
    free = gpu_free_gb()
    _log(log_fn, f'wait_for_vram: timeout — {free if free is not None else "?"} GB free (target {min_free_gb})')
    return False


# --------------------------------------------------------------------------
# The boundary-judge context manager
# --------------------------------------------------------------------------


@contextmanager
def gpu_exclusive(min_free_gb: float = 20, server: str = DEFAULT_SERVER, timeout_s: float = 180, log_fn=None):
    """Offload ComfyUI and yield the GPU to a caller (the boundary judge).

    Flow: refuse if ComfyUI is actively sampling (raises
    :class:`ComfySamplingActiveError` — freeing mid-sample kills renders),
    else comfy_free() + wait_for_vram(min_free_gb), then yield the ACTUAL
    free GB (float).

    If min_free_gb is unreachable (e.g. musubi training holds ~25 GB), the
    context still yields the actual free GB after a loud log — callers MUST
    check the yielded value and downshift their model tier (e.g. int4 8B
    instead of 32B) rather than assume the request was met.

    ON EXIT THIS DOES NOTHING, deliberately: ComfyUI lazily reloads its
    models when the next job is queued (~1-3 min), so no reload/restore
    call is needed or wanted here.
    """
    if comfy_is_sampling(server):
        raise ComfySamplingActiveError(
            'ComfyUI is actively sampling — refusing to free VRAM '
            '(freeing mid-sample kills the render). Retry at the next '
            'pipeline pause point.'
        )

    freed = comfy_free(server=server, timeout_s=min(120.0, float(timeout_s)), log_fn=log_fn)
    if not freed:
        _log(log_fn, 'gpu_exclusive: comfy_free did not confirm offload — continuing, but free VRAM may be low')

    reached = wait_for_vram(min_free_gb, timeout_s=timeout_s, log_fn=log_fn)
    actual = gpu_free_gb()
    actual = 0.0 if actual is None else actual
    if not reached:
        _log(
            log_fn,
            f'gpu_exclusive: WANTED {min_free_gb} GB but only {actual:.1f} GB '
            f'free (GPU co-tenant, e.g. LoRA training, holds the rest) — '
            f'yielding anyway; CALLER MUST DOWNSHIFT its model tier to fit.',
        )

    yield actual
    # No teardown: ComfyUI reloads models lazily on the next queued job.
