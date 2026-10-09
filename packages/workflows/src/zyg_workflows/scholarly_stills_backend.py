# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
scholarly_stills_backend.py
===========================
Stage 3.5 scholarly documentary stills — production backend policy.

Hardcoded default: in-process **diffusers** (FLUX.1-schnell + bible + ControlNet).

Comfy is **never** used for routine production runs. Enable only for heavy
character asset curation when automated HandFixer pass-through is required and
the ~6.5× time penalty is acceptable (parity benchmark 2026-06-03).

Set ``ZYG_SCHOLARLY_COMFY_IMAGES=1`` for that path only.
"""

from __future__ import annotations

import fcntl
import gc
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Cross-process Stage 3.5 GPU mutex (FLUX + ControlNet). One holder at a time.
SCHOLARLY_GPU_LOCK_ENV = 'ZYG_SCHOLARLY_GPU_LOCK'
_STAGGER_CONCURRENT_ENV = 'ZYG_SCHOLARLY_STAGGER_CONCURRENT'

_CREWS_ROOT = Path(__file__).resolve().parent
SCHOLARLY_GPU_LOCK_PATH = Path(
    os.environ.get(
        'ZYG_SCHOLARLY_GPU_LOCK_PATH',
        str(_CREWS_ROOT / 'data' / 'runtime' / 'scholarly_gpu.lock'),
    ),
)
SCHOLARLY_GPU_LOCK_META_PATH = SCHOLARLY_GPU_LOCK_PATH.with_suffix('.json')

_LOCK_POLL_S_DEFAULT = 10.0
_LOCK_STALE_S_DEFAULT = 7200.0

# Open lock file held until release (flock is tied to the file description).
_active_lock_fh: Any = None
_active_lock_pipeline_id: str | None = None


class ScholarlyGpuLockStopped(Exception):
    """Raised when a pipeline stop is requested while waiting for SCHOLARLY_GPU_LOCK."""


def scholarly_gpu_lock_enabled() -> bool:
    """Lock is on unless explicitly disabled (benchmarks / single-thread debug)."""
    return os.environ.get(SCHOLARLY_GPU_LOCK_ENV, '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def scholarly_stagger_concurrent_enabled() -> bool:
    """Allow overlapping scholarly pipelines; skip killing sibling Flask workers."""
    return os.environ.get(_STAGGER_CONCURRENT_ENV, '').strip().lower() in _COMFY_CURATION_TRUTHY


def _lock_poll_s() -> float:
    raw = os.environ.get('ZYG_SCHOLARLY_GPU_LOCK_POLL_S', '')
    try:
        return float(raw) if raw else _LOCK_POLL_S_DEFAULT
    except ValueError:
        return _LOCK_POLL_S_DEFAULT


def _lock_stale_s() -> float:
    raw = os.environ.get('ZYG_SCHOLARLY_GPU_LOCK_STALE_S', '')
    try:
        return float(raw) if raw else _LOCK_STALE_S_DEFAULT
    except ValueError:
        return _LOCK_STALE_S_DEFAULT


def _write_lock_meta(meta: dict) -> None:
    SCHOLARLY_GPU_LOCK_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHOLARLY_GPU_LOCK_META_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)
    tmp.replace(SCHOLARLY_GPU_LOCK_META_PATH)


def read_scholarly_gpu_lock_meta() -> dict:
    try:
        with open(SCHOLARLY_GPU_LOCK_META_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _clear_lock_meta() -> None:
    try:
        SCHOLARLY_GPU_LOCK_META_PATH.unlink(missing_ok=True)
    except OSError as _exc:
        _zyg_log.debug('gpu lock meta unlink skipped: %s', _exc)


def _maybe_break_stale_lock(log_fn: Callable[[str], None] | None) -> None:
    meta = read_scholarly_gpu_lock_meta()
    if not meta:
        return
    acquired = float(meta.get('acquired_at') or 0)
    if not acquired or (time.time() - acquired) < _lock_stale_s():
        return
    holder_pid = int(meta.get('pid') or 0)
    if holder_pid > 0:
        try:
            os.kill(holder_pid, 0)
            return
        except OSError as _exc:
            _zyg_log.debug('lock holder pid %s is gone: %s', holder_pid, _exc)
    if log_fn:
        log_fn(
            f'SCHOLARLY_GPU_LOCK stale ({time.time() - acquired:.0f}s) — '
            f'clearing meta from dead holder pid={holder_pid}'
        )
    _clear_lock_meta()


def acquire_scholarly_gpu_lock(
    pipeline_id: str,
    *,
    log_fn: Callable[[str], None] | None = None,
    poll_s: float | None = None,
    timeout_s: float | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """Block until this pipeline holds the cross-process Stage 3.5 GPU lock."""
    global _active_lock_fh, _active_lock_pipeline_id

    if not scholarly_gpu_lock_enabled():
        if log_fn:
            log_fn('SCHOLARLY_GPU_LOCK disabled — proceeding without queue')
        return

    if _active_lock_pipeline_id == pipeline_id and _active_lock_fh is not None:
        return

    poll = _lock_poll_s() if poll_s is None else poll_s
    deadline = (time.time() + timeout_s) if timeout_s else None
    SCHOLARLY_GPU_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    lock_fh = open(SCHOLARLY_GPU_LOCK_PATH, 'a+', encoding='utf-8')
    while True:
        if stop_check and stop_check():
            lock_fh.close()
            raise ScholarlyGpuLockStopped('pipeline stop requested while waiting for GPU lock')

        _maybe_break_stale_lock(log_fn)
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = read_scholarly_gpu_lock_meta()
            if log_fn:
                hid = (holder.get('pipeline_id') or '?')[:8]
                log_fn(
                    'GPU occupied by competing pipeline run. '
                    f'Dropping into staggered queue wait pool… '
                    f'(holder={hid} pid={holder.get("pid")})'
                )
            if deadline and time.time() >= deadline:
                lock_fh.close()
                raise TimeoutError(
                    f'SCHOLARLY_GPU_LOCK timeout after {timeout_s}s (holder={holder.get("pipeline_id")})'
                ) from exc
            time.sleep(poll)
            continue

        meta = {
            'pipeline_id': pipeline_id,
            'pid': os.getpid(),
            'acquired_at': time.time(),
        }
        _write_lock_meta(meta)
        _active_lock_fh = lock_fh
        _active_lock_pipeline_id = pipeline_id
        if log_fn:
            log_fn(f'SCHOLARLY_GPU_LOCK acquired (pid={os.getpid()} pipeline={pipeline_id[:8]})')
        return


def release_scholarly_gpu_lock(
    pipeline_id: str,
    *,
    pipe: Any = None,
    cn_pipe: Any = None,
    cn_service: Any = None,
    log_fn: Callable[[str], None] | None = None,
    skip_vram_teardown: bool = False,
) -> None:
    """Teardown FLUX VRAM (if needed) and release SCHOLARLY_GPU_LOCK."""
    global _active_lock_fh, _active_lock_pipeline_id

    if not scholarly_gpu_lock_enabled():
        return

    if _active_lock_pipeline_id and _active_lock_pipeline_id != pipeline_id:
        if log_fn:
            log_fn(
                f'SCHOLARLY_GPU_LOCK release skipped — holder is {_active_lock_pipeline_id[:8]}, not {pipeline_id[:8]}'
            )
        return

    if not skip_vram_teardown:
        aggressive_release_flux_pipeline_vram(
            pipe,
            cn_pipe=cn_pipe,
            cn_service=cn_service,
            log_fn=log_fn,
        )

    if _active_lock_fh is not None:
        try:
            fcntl.flock(_active_lock_fh.fileno(), fcntl.LOCK_UN)
            _active_lock_fh.close()
        except OSError as _exc:
            _zyg_log.warning('gpu lock release failed, the lock file may stay held: %s', _exc)
        _active_lock_fh = None

    _active_lock_pipeline_id = None
    _clear_lock_meta()
    if log_fn:
        log_fn(f'SCHOLARLY_GPU_LOCK released (pipeline={pipeline_id[:8]})')


# ── Locked production default (do not change without a new parity benchmark) ──
SCHOLARLY_PRODUCTION_BACKEND = 'diffusers'

# Opt-in Comfy curation: HandFixer + pose/IP stack in one graph; not for pipelines.
SCHOLARLY_COMFY_CURATION_ENV = 'ZYG_SCHOLARLY_COMFY_IMAGES'

_COMFY_CURATION_TRUTHY = frozenset(('1', 'true', 'yes', 'on'))


def scholarly_comfy_curation_enabled() -> bool:
    """True only when explicitly opted in for critical character sheet curation."""
    return os.environ.get(SCHOLARLY_COMFY_CURATION_ENV, '').strip().lower() in _COMFY_CURATION_TRUTHY


# ── Still-image FAMILY (2026-08-25) ─────────────────────────────────────────
# Which generator renders the documentary stills. 'qwen' = Qwen-Image-2512
# (Apache-2.0, real CFG so negatives are LIVE, ~far stronger prompt adherence)
# through ComfyUI — the production default since the Black Death audit showed
# that subject-absent renders, the CG nave, baked-in letterbox bars, cloned
# faces and the modern-object priors were all a 4-step distilled model at
# guidance 0. 'flux' restores in-process FLUX.1-schnell + diffusers exactly as
# it was. Anything else falls back to 'flux' with a warning at the call site.
SCHOLARLY_STILL_FAMILY_ENV = 'ZYG_SCHOLARLY_STILL_FAMILY'
SCHOLARLY_STILL_FAMILY_DEFAULT = 'qwen'
SCHOLARLY_STILL_FAMILIES = ('qwen', 'flux')


def scholarly_still_family() -> str:
    """'qwen' (default) or 'flux' — the family that renders Stage 3.5 stills."""
    v = os.environ.get(SCHOLARLY_STILL_FAMILY_ENV, '').strip().lower()
    return v if v in SCHOLARLY_STILL_FAMILIES else SCHOLARLY_STILL_FAMILY_DEFAULT


def scholarly_backend_label() -> str:
    if scholarly_comfy_curation_enabled():
        return 'comfy_curation'
    if scholarly_still_family() == 'qwen':
        return 'comfy_qwen'
    return SCHOLARLY_PRODUCTION_BACKEND


def scholarly_comfy_curation_hint() -> str:
    return (
        f'Comfy curation is opt-in only — set {SCHOLARLY_COMFY_CURATION_ENV}=1 '
        '(HandFixer + pose/IP; ~6.5× slower than diffusers). '
        f'Production default: {SCHOLARLY_PRODUCTION_BACKEND}.'
    )


def aggressive_release_flux_pipeline_vram(
    pipe: Any,
    *,
    cn_pipe: Any = None,
    cn_service: Any = None,
    log_fn: Callable[[str], None] | None = None,
) -> float | None:
    """Release FLUX + optional ControlNet from GPU (benchmark handoff / Comfy leg)."""

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if cn_service is not None and cn_pipe is not None:
        try:
            cn_service.teardown(cn_pipe, log_fn=log_fn)
        except Exception as _exc:
            _zyg_log.debug('controlnet teardown skipped: %s', _exc)

    try:
        import torch
    except ImportError:
        return None

    if pipe is not None:
        for attr in ('transformer', 'text_encoder', 'text_encoder_2', 'vae'):
            mod = getattr(pipe, attr, None)
            if mod is not None and hasattr(mod, 'to'):
                try:
                    mod.to('cpu')
                except Exception as _exc:
                    _zyg_log.debug('module move to cpu skipped, vram may stay held: %s', _exc)
        del pipe

    gc.collect()
    if not torch.cuda.is_available():
        return None
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    torch.cuda.empty_cache()
    free_gb = torch.cuda.mem_get_info(0)[0] / 1024**3
    _log(f'FLUX VRAM released — free: {free_gb:.1f} GB')
    return free_gb


# ── Persistent FLUX worker ────────────────────────────────────────────────────
_FLUX_WORKER_PERSISTENT_ENV = 'ZYG_SCHOLARLY_FLUX_PERSISTENT'
_FLUX_WORKER_IDLE_S_ENV = 'ZYG_FLUX_WORKER_IDLE_S'


def scholarly_flux_persistent_enabled() -> bool:
    """True when ZYG_SCHOLARLY_FLUX_PERSISTENT=1."""
    return os.environ.get(_FLUX_WORKER_PERSISTENT_ENV, '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


class ScholarlyFluxWorker:
    """
    Keeps FLUX loaded across concurrent scholarly pipeline batches.

    One pipeline at a time borrows the loaded FLUX/CN pipe via
    acquire_pipe_slot() / release_pipe_slot().  Between borrows the model
    stays in VRAM.  After idle_timeout seconds with no borrower the worker
    unloads FLUX and releases the GPU lock.

    Lifecycle
    ---------
    1. First pipeline: claim_start() → True → acquire GPU lock → load FLUX →
       complete_start(pipe, cn_pipe, teardown_fn) → acquire_pipe_slot() → generate
       → release_pipe_slot()
    2. Subsequent pipelines: is_running_or_starting() → True →
       wait_until_running() → acquire_pipe_slot() → generate → release_pipe_slot()
    3. After idle_timeout: worker background thread calls teardown_fn() which
       unloads FLUX and releases the GPU lock.

    Enable with ZYG_SCHOLARLY_FLUX_PERSISTENT=1.
    Tune idle timeout with ZYG_FLUX_WORKER_IDLE_S (default 600 s).
    """

    _singleton_lock: threading.Lock = threading.Lock()
    _singleton: 'ScholarlyFluxWorker | None' = None

    @classmethod
    def get(cls) -> 'ScholarlyFluxWorker':
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pipe_lock = threading.Lock()  # serial access: one pipeline at a time
        self._pipe: Any = None
        self._cn_pipe: Any = None
        self._teardown_fn: Callable | None = None
        self._log_fn: Callable[[str], None] | None = None
        self._starting = False
        self._idle_thread: threading.Thread | None = None
        self._idle_timeout = float(os.environ.get(_FLUX_WORKER_IDLE_S_ENV, '30'))
        self._last_release_t: float = 0.0
        self._stopped = False

    # ── State queries ──────────────────────────────────────────────────────

    def is_running(self) -> bool:
        t = self._idle_thread
        return (not self._stopped) and (t is not None) and t.is_alive()

    def is_running_or_starting(self) -> bool:
        with self._lock:
            return self._starting or self.is_running()

    # ── Startup protocol ───────────────────────────────────────────────────

    def claim_start(self) -> bool:
        """Atomically claim responsibility for loading FLUX.  Returns True if won."""
        with self._lock:
            if self._starting or self.is_running():
                return False
            self._starting = True
            return True

    def cancel_start(self) -> None:
        """Reset _starting if FLUX load failed (e.g. lock acquire aborted)."""
        with self._lock:
            self._starting = False

    def complete_start(
        self,
        pipe: Any,
        cn_pipe: Any,
        teardown_fn: Callable,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        """Called after FLUX is loaded.  Starts the idle-timeout background thread."""
        with self._lock:
            self._pipe = pipe
            self._cn_pipe = cn_pipe
            self._teardown_fn = teardown_fn
            self._log_fn = log_fn
            self._starting = False
            self._stopped = False
            self._last_release_t = time.monotonic()
            self._idle_thread = threading.Thread(
                target=self._idle_loop,
                name='flux-persistent-worker-idle',
                daemon=True,
            )
            self._idle_thread.start()
        _log = log_fn or (lambda m: None)
        _log(
            f'[FluxWorker] started — idle_timeout={self._idle_timeout:.0f}s '
            f'pipe={type(pipe).__name__} cn={cn_pipe is not None}'
        )

    def wait_until_running(self, timeout: float = 120.0) -> None:
        """Block until worker is fully running.  Raises RuntimeError / TimeoutError."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self.is_running():
                    return
                if not self._starting:
                    raise RuntimeError('[FluxWorker] start was claimed but aborted')
            time.sleep(0.25)
        raise TimeoutError(f'[FluxWorker] did not become ready within {timeout:.0f}s')

    # ── Pipe access ────────────────────────────────────────────────────────

    def get_pipe(self) -> Any:
        return self._pipe

    def get_cn_pipe(self) -> Any:
        return self._cn_pipe

    def acquire_pipe_slot(self, timeout: float = 600.0) -> tuple:
        """Block until exclusive pipe access is granted.  Returns (pipe, cn_pipe)."""
        if not self._pipe_lock.acquire(timeout=timeout):
            raise TimeoutError(f'[FluxWorker] could not acquire pipe slot within {timeout:.0f}s')
        return self._pipe, self._cn_pipe

    def release_pipe_slot(self) -> None:
        """Release pipe back to the pool and reset the idle timer."""
        self._last_release_t = time.monotonic()
        try:
            self._pipe_lock.release()
        except RuntimeError as _exc:
            _zyg_log.debug('pipe lock was already released: %s', _exc)

    # ── Idle management ────────────────────────────────────────────────────

    def emergency_stop(self, log_fn: Callable[[str], None] | None = None) -> None:
        """Signal the worker to stop as soon as possible.

        If no inference is running the teardown fires immediately.
        If FLUX is mid-inference the idle loop picks up _stopped on its next
        tick, waits for the pipe lock to free (i.e. inference completes), then
        calls teardown so the GPU lock is released promptly.
        """
        _log = log_fn or (lambda m: None)
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._last_release_t = 0.0  # force idle-loop timeout check
        # Fast path: pipe lock is free — tear down right now
        if self._pipe_lock.acquire(blocking=False):
            self._pipe_lock.release()
            self._shutdown(_log)
        else:
            _log('[FluxWorker] emergency stop signaled — waiting for current inference to finish')
            # _idle_loop will see _stopped=True and drive teardown after the lock frees

    def _idle_loop(self) -> None:
        _log = self._log_fn or (lambda m: None)
        poll = min(10.0, self._idle_timeout / 6)
        while True:
            time.sleep(poll)
            if self._stopped:
                # Emergency stop: wait for any active inference to finish, then tear down.
                if self._pipe_lock.acquire(timeout=300.0):
                    self._pipe_lock.release()
                self._shutdown(_log)
                return
            idle_s = time.monotonic() - self._last_release_t
            if idle_s < self._idle_timeout:
                continue
            # Try to acquire pipe slot — if someone is using it, reset timer
            if not self._pipe_lock.acquire(blocking=False):
                self._last_release_t = time.monotonic()
                continue
            # Got the lock exclusively — no pipeline is using the pipe
            self._pipe_lock.release()
            _log(
                f'[FluxWorker] idle {idle_s:.0f}s >= {self._idle_timeout:.0f}s — unloading FLUX and releasing GPU lock'
            )
            self._shutdown(_log)
            return

    def _shutdown(self, log_fn: Callable[[str], None]) -> None:
        teardown = None
        with self._lock:
            self._stopped = True
            self._pipe = None
            self._cn_pipe = None
            teardown = self._teardown_fn
            self._teardown_fn = None
        if teardown:
            try:
                teardown()
            except Exception as td_e:
                log_fn(f'[FluxWorker] teardown error (non-fatal): {td_e}')
        log_fn('[FluxWorker] stopped — FLUX unloaded, GPU lock released')
