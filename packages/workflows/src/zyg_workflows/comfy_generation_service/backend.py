# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VRAM housekeeping, backend selection and the ComfyUI circuit breaker (original lines 111-206, 219-297)."""

from __future__ import annotations

import time as _time_cb
import os
import subprocess
import threading
from typing import Any, Callable
from zyg_workflows.bin import exe
from zyg_workflows.comfy_generation_service.constants import _comfy, _log_default, _zyg_log


def _clear_vram_between_slots_enabled(explicit: bool | None = None) -> bool:
    """True unless explicitly disabled via arg or ``ZYG_COMFY_CLEAR_VRAM_BETWEEN_SLOTS=0``."""
    if explicit is not None:
        return bool(explicit)
    return os.environ.get('ZYG_COMFY_CLEAR_VRAM_BETWEEN_SLOTS', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def _gpu_used_mb_total() -> int:
    """Device-wide GPU memory used (MiB) via nvidia-smi — fallback for when the
    per-PID Comfy VRAM probe can't resolve a PID and reports 0 (fix G)."""
    try:
        import subprocess as _sp

        out = _sp.check_output(
            [exe('nvidia-smi'), '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            timeout=5,
        ).decode()
        return int(out.strip().split('\n')[0])
    except Exception:
        return -1


def clear_vram_between_slots(
    log_fn: Callable[[str], None] | None = None,
    label: str = 'between-slots',
) -> dict[str, Any]:
    """Drop Comfy executor/model cache between sequential stills (scholarly Stage 3.5).

    Prevents VRAM creep on long FLUX runs (e.g. slot 9+ OOM). Waits for the Comfy
    queue to go idle, then /free + :func:`_comfy.release_memory` wait, then a
    best-effort local ``torch`` cache clear.

    2026-08-25 (P-07): this used to fire a GLOBAL ``/interrupt`` whenever the
    queue was busy. ComfyUI's /interrupt is server-wide and :8188 is shared —
    during docsmoke-b58104c4 the creature worker's qwen_edit_angle jobs sat in
    the same queue, so a busy queue here is somebody ELSE's render (our own
    submit() has already returned by the time this runs). Now it waits; if the
    queue is still busy after the wait it leaves the other client alone and
    skips the /free for this slot rather than pull the models out from under it.
    """
    log = log_fn or _log_default
    summary: dict[str, Any] = {'ok': False, 'skipped': False, 'label': label}
    if not _clear_vram_between_slots_enabled():
        summary['skipped'] = True
        summary['ok'] = True
        return summary
    if _comfy is None or not is_available():
        return summary
    try:
        _idle = True
        if _comfy.queue_is_busy():
            _idle = _comfy.wait_for_idle(timeout_s=30.0)
            if not _idle:
                log(
                    f'ComfyVRAM [{label}]: queue still busy after 30s — another '
                    'client is rendering; NOT interrupting it, /free skipped this slot'
                )
                summary['busy'] = True
        if _idle:
            _rel = _comfy.release_memory(
                wait=True,
                timeout_s=float(os.environ.get('ZYG_COMFY_SLOT_FREE_TIMEOUT', '60') or '60'),
                log_fn=lambda m: log(f'ComfyVRAM [{label}]: {m}'),
            )
            summary.update(_rel)
            summary['ok'] = bool(_rel.get('ok'))
            if _rel.get('gpu_mb_after') is not None:
                # The per-PID probe returns 0 when it can't resolve the Comfy PID
                # (it printed "GPU ~0 MiB, RSS 0 MiB" for a whole run). Fall back to a
                # real device-wide reading so the telemetry means something (fix G).
                _gpu = _rel.get('gpu_mb_after')
                _rss = _rel.get('rss_mb_after')
                if not _gpu:
                    _gpu = f'{_gpu_used_mb_total()} (whole-GPU used, all processes — not Comfy-specific)'
                log(f'ComfyVRAM [{label}]: GPU ~{_gpu} MiB, RSS {_rss if _rss else "?"} MiB')
    except Exception as exc:
        log(f'ComfyVRAM [{label}]: release failed — {exc}')
    try:
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, 'ipc_collect'):
                torch.cuda.ipc_collect()
    except Exception as _exc:
        _zyg_log.debug('local torch cache clear skipped: %s', _exc)
    return summary


def is_primary_backend() -> bool:
    primary = os.environ.get('ZYG_COMFY_PRIMARY', '').strip().lower() in ('1', 'true', 'yes', 'on')
    legacy = os.environ.get('ZYG_USE_COMFYUI', '').strip().lower() in ('1', 'true', 'yes', 'on')
    return primary or legacy


# ── 2026-07-24: ComfyUI circuit breaker + wedge auto-recovery ─────────────────
# Job 10c84d83 burned 138 doomed submits (plus /free spam) against a server that
# had been fail-fast wedged for 13 hours ("'NoneType' object has no attribute
# 'model_size'" — a corrupt LoadedModel left by a failed unload; empty queue, so
# the health probe saw nothing). Three consecutive instant failures open the
# breaker (is_available() → False, pipelines go straight to their fallback);
# the known wedge signature additionally triggers ONE gated
# `sudo -n systemctl restart comfyui` per cooldown window.
_CB_LOCK = threading.Lock()
_CB_TRIP_AFTER = 3
_CB_OPEN_SECONDS = 600.0
_CB_RESTART_COOLDOWN_S = 1800.0
_CB_WEDGE_SIGNATURES = ("has no attribute 'model_size'",)
_cb_consec_failures = 0
_cb_open_until = 0.0
_cb_last_auto_restart = 0.0


def _cb_record_success() -> None:
    global _cb_consec_failures
    with _CB_LOCK:
        _cb_consec_failures = 0


def _cb_record_failure(exc_text: str, log: Callable[[str], None]) -> None:
    """Count consecutive Comfy failures; open the breaker and (for the known
    wedge signature) attempt one gated service restart per cooldown."""
    global _cb_consec_failures, _cb_open_until, _cb_last_auto_restart
    wedge = any(sig in (exc_text or '') for sig in _CB_WEDGE_SIGNATURES)
    with _CB_LOCK:
        _cb_consec_failures += 1
        tripped = wedge or _cb_consec_failures >= _CB_TRIP_AFTER
        if not tripped:
            return
        _cb_open_until = _time_cb.time() + _CB_OPEN_SECONDS
        can_restart = (
            wedge
            and os.environ.get('ZYG_COMFY_AUTO_RESTART', '1') != '0'
            and (_time_cb.time() - _cb_last_auto_restart) > _CB_RESTART_COOLDOWN_S
        )
        if can_restart:
            _cb_last_auto_restart = _time_cb.time()
    log(
        f'ComfyGen: circuit breaker OPEN ({_cb_consec_failures} consecutive failures'
        f'{", wedge signature detected" if wedge else ""}) — '
        f'skipping Comfy for {int(_CB_OPEN_SECONDS)}s'
    )
    if not (wedge and can_restart):
        return
    log('ComfyGen: known wedge signature — attempting `systemctl restart comfyui` (auto-recovery)')
    try:
        subprocess.run(
            [exe('sudo'), '-n', exe('systemctl'), 'restart', 'comfyui.service'],
            timeout=60,
            capture_output=True,
        )
        for _ in range(18):
            _time_cb.sleep(5)
            if _comfy is not None and _comfy.server_reachable():
                with _CB_LOCK:
                    _cb_open_until = 0.0
                    _cb_consec_failures = 0
                log('ComfyGen: ComfyUI restarted and reachable — circuit breaker closed')
                return
        log('ComfyGen: ComfyUI did not come back within 90s — breaker stays open')
    except Exception as _cb_exc:
        log(f'ComfyGen: auto-restart failed ({_cb_exc}) — breaker stays open')


def is_available() -> bool:
    if _time_cb.time() < _cb_open_until:
        return False
    return _comfy is not None and is_primary_backend() and _comfy.is_enabled() and _comfy.server_reachable()
