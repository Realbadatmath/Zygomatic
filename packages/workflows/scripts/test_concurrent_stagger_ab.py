#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Production-parity staggered scholarly pipeline A/B test.

Exercises two real ``_run_scholarly_pipeline`` workers with:
  - Real TTS (narration_enabled=True)
  - Full FLUX resolution/steps (no smoke cap unless profile=smoke)
  - pipeline_options scene_count + duration caps (not _SCHOLARLY_SMOKE_MAX_IMAGES)
  - Pipeline B starts when Pipeline A enters Stage 4 (dashboard-realistic overlap)
  - SCHOLARLY_GPU_LOCK cross-process mutex

Profiles (``ZYG_STAGGER_AB_PROFILE``):
  parity (default) — production-like load
  smoke           — legacy fast path (2 images, silent Stage 4, fixed offset)

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  ZYG_SCHOLARLY_STAGGER_CONCURRENT=1 \\
  ../.venv/bin/python scripts/test_concurrent_stagger_ab.py

Output: data/runtime/stagger_ab_<timestamp>.json
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_CREWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CREWS))

_RUNTIME = _CREWS / 'data' / 'runtime'
_PROFILE = os.environ.get('ZYG_STAGGER_AB_PROFILE', 'parity').strip().lower()
_IS_SMOKE = _PROFILE in ('smoke', 'legacy', 'fast')

# ── Parity defaults (override via env) ───────────────────────────────────────
_PARITY_SCENE_COUNT = int(os.environ.get('ZYG_STAGGER_AB_SCENE_COUNT', '10'))
_PARITY_DURATION_SEC = float(os.environ.get('ZYG_STAGGER_AB_DURATION_SEC', '90'))
_PARITY_CHAR_ID = os.environ.get('ZYG_STAGGER_AB_CHAR_ID', '1a2b6cfc0f93').strip()
_STOP_AFTER_S4 = os.environ.get('ZYG_STAGGER_AB_STOP_AFTER_S4', '1' if not _IS_SMOKE else '0').strip().lower() in (
    '1',
    'true',
    'yes',
    'on',
)
_STOP_AFTER_S35 = os.environ.get('ZYG_STAGGER_AB_STOP_AFTER_S35', '0').strip().lower() in (
    '1',
    'true',
    'yes',
    'on',
)
_POLL_STAGE_S = float(os.environ.get('ZYG_STAGGER_AB_POLL_S', '0.25'))
_WAIT_A_STAGE4_TIMEOUT_S = float(os.environ.get('ZYG_STAGGER_AB_WAIT_A_S4_S', '3600'))

TOPICS = (
    ('hydroponics', 'Hydroponics vertical farming nutrient film techniques scholarly documentary'),
    ('solar_energy', 'Solar photovoltaic grid battery storage scholarly documentary'),
)


def _log(msg: str) -> None:
    print(f'[stagger-ab] {msg}', flush=True)


def _truthy(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes', 'on')


def _vram_snapshot() -> dict:
    try:
        import torch

        if not torch.cuda.is_available():
            return {'cuda': False}
        free_b, total_b = torch.cuda.mem_get_info(0)
        alloc_gb = torch.cuda.memory_allocated(0) / 1024**3
        return {
            'cuda': True,
            'free_gb': round(free_b / 1024**3, 2),
            'total_gb': round(total_b / 1024**3, 2),
            'alloc_gb': round(alloc_gb, 2),
        }
    except Exception as exc:
        return {'error': str(exc)}


def _lock_meta() -> dict:
    from zyg_workflows import scholarly_stills_backend as ssb

    return ssb.read_scholarly_gpu_lock_meta()


def _job(gui, pid: str) -> dict:
    return gui._workflow_jobs.get(pid) or {}


def _job_stage(gui, pid: str) -> str:
    return _job(gui, pid).get('current_stage') or _job(gui, pid).get('status') or 'unknown'


def _stage_completed(gui, pid: str, stage_name: str) -> bool:
    st = (_job(gui, pid).get('stages') or {}).get(stage_name) or {}
    return st.get('status') == 'completed'


def _stage35_done(gui, pid: str) -> bool:
    return _stage_completed(gui, pid, 'Stage 3.5: AI Image Generation')


def _stage4_done(gui, pid: str) -> bool:
    return _stage_completed(gui, pid, 'Stage 4: TTS Narration')


def _in_stage4(gui, pid: str) -> bool:
    return 'Stage 4' in _job_stage(gui, pid)


def _parity_pipeline_options() -> dict:
    return {
        'scene_count': _PARITY_SCENE_COUNT,
        'total_duration_sec': _PARITY_DURATION_SEC,
        'enable_bgm': False,
        'burn_subtitles': False,
    }


def _wait_for_stage4(gui, pid: str, timeout_s: float) -> float:
    """Block until pipeline enters Stage 4; return seconds waited."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if _in_stage4(gui, pid):
            return time.time() - t0
        job = _job(gui, pid)
        if job.get('status') in ('error', 'stopped', 'done'):
            raise RuntimeError(
                f'Pipeline {pid[:8]} ended before Stage 4: status={job.get("status")} error={job.get("error")}'
            )
        time.sleep(_POLL_STAGE_S)
    raise TimeoutError(f'Pipeline {pid[:8]} did not reach Stage 4 within {timeout_s}s')


def _monitor(
    gui,
    pipeline_ids: list[str],
    telemetry: list[dict],
    stop: threading.Event,
) -> None:
    t0 = time.time()
    while not stop.is_set():
        row = {
            't_s': round(time.time() - t0, 1),
            'vram': _vram_snapshot(),
            'lock': _lock_meta(),
            'stages': {pid[:8]: _job_stage(gui, pid) for pid in pipeline_ids},
        }
        telemetry.append(row)
        holder = (row['lock'].get('pipeline_id') or '')[:8]
        if holder:
            _log(
                f't={row["t_s"]:.0f}s lock={holder} vram_free={row["vram"].get("free_gb")} '
                f'A={row["stages"].get(pipeline_ids[0][:8], "?")} '
                f'B={row["stages"].get(pipeline_ids[1][:8], "?")}'
            )
        time.sleep(5)


def _start_pipeline(
    gui,
    topic: str,
    directive: str,
    *,
    narration_enabled: bool,
    pipeline_options: dict | None,
    char_id: str,
) -> str:
    job = gui._start_scholarly_pipeline_internal(
        directive=directive,
        topic=topic,
        narration_enabled=narration_enabled,
        visual_style='cinematic',
        model_family='sdxl',
        char_id=char_id,
        pipeline_options=pipeline_options,
    )
    return job['job_id']


def _apply_profile_env() -> None:
    os.environ.setdefault('ZYG_SCHOLARLY_STAGGER_CONCURRENT', '1')
    os.environ.setdefault('ZYG_SCHOLARLY_GPU_LOCK', '1')
    if _IS_SMOKE:
        os.environ.setdefault('ZYG_SKIP_GPU_EXCLUSIVE', '1')
    elif not os.environ.get('ZYG_SKIP_GPU_EXCLUSIVE'):
        # Production-like: run GPU exclusivity sweep (do not set skip)
        pass


def main() -> int:
    _apply_profile_env()
    _log(f'Profile: {_PROFILE} (smoke={_IS_SMOKE})')

    _log('Importing crewai_web_gui (15–30s)…')
    from zyg_dashboard import crewai_web_gui as gui  # noqa: E402

    if _IS_SMOKE:
        gui._SCHOLARLY_SMOKE_MAX_IMAGES = int(os.environ.get('ZYG_STAGGER_AB_SMOKE_IMAGES', '2'))
        pipeline_options = None
        narration_enabled = False
        char_id = ''
        _log(f'SMOKE: cap={gui._SCHOLARLY_SMOKE_MAX_IMAGES} images, narration off')
    else:
        gui._SCHOLARLY_SMOKE_MAX_IMAGES = 0
        pipeline_options = _parity_pipeline_options()
        narration_enabled = True
        char_id = _PARITY_CHAR_ID
        _log(
            f'PARITY: scene_count={_PARITY_SCENE_COUNT} duration_sec={_PARITY_DURATION_SEC} '
            f'narration=on char_id={char_id or "(none)"} smoke_cap=0 (full res/steps)'
        )

    pid_a = _start_pipeline(
        gui,
        TOPICS[0][0],
        TOPICS[0][1],
        narration_enabled=narration_enabled,
        pipeline_options=pipeline_options,
        char_id=char_id,
    )
    _log(f'Pipeline A started: {pid_a}')

    b_launch_mode = 'stage4_trigger'
    wait_a_s4 = 0.0
    if _IS_SMOKE:
        offset = float(os.environ.get('ZYG_STAGGER_AB_OFFSET_S', '30'))
        _log(f'SMOKE: sleeping {offset:.0f}s before Pipeline B')
        time.sleep(offset)
        b_launch_mode = f'fixed_offset_{offset:.0f}s'
    else:
        _log('Waiting for Pipeline A to enter Stage 4 (real overlap trigger)…')
        wait_a_s4 = _wait_for_stage4(gui, pid_a, _WAIT_A_STAGE4_TIMEOUT_S)
        _log(f'Pipeline A entered Stage 4 after {wait_a_s4:.1f}s — launching B now')

    pid_b = _start_pipeline(
        gui,
        TOPICS[1][0],
        TOPICS[1][1],
        narration_enabled=narration_enabled,
        pipeline_options=pipeline_options,
        char_id=char_id,
    )
    _log(f'Pipeline B started: {pid_b} (mode={b_launch_mode})')

    pipeline_ids = [pid_a, pid_b]
    telemetry: list[dict] = []
    mon_stop = threading.Event()
    mon = threading.Thread(
        target=_monitor,
        args=(gui, pipeline_ids, telemetry, mon_stop),
        daemon=True,
        name='stagger-ab-monitor',
    )
    mon.start()

    events: list[dict] = []
    wait_pool_logged = False
    b_acquired_after_a_s35 = False
    overlap_a_s4_b_pre_s35 = False
    t0 = time.time()
    timeout_s = float(os.environ.get('ZYG_STAGGER_AB_TIMEOUT_S', '14400'))

    def _record(name: str, **extra) -> None:
        events.append({'t_s': round(time.time() - t0, 1), 'event': name, **extra})

    exit_code = 1
    try:
        while time.time() - t0 < timeout_s:
            meta = _lock_meta()
            holder = meta.get('pipeline_id') or ''
            a_s4 = _in_stage4(gui, pid_a)
            b_stage = _job_stage(gui, pid_b)

            if a_s4 and pid_b and not _stage35_done(gui, pid_b):
                if 'Stage 3' in b_stage or 'Stage 2' in b_stage or 'Stage 1' in b_stage:
                    if not overlap_a_s4_b_pre_s35:
                        overlap_a_s4_b_pre_s35 = True
                        _record('overlap_a_stage4_b_upstream', b_stage=b_stage)
                        _log(f'Overlap: A in Stage 4 while B still in upstream work ({b_stage})')

            if holder == pid_b and not b_acquired_after_a_s35:
                if _stage35_done(gui, pid_a):
                    b_acquired_after_a_s35 = True
                    _record('b_gpu_lock_after_a_stage35')
                    _log('Pipeline B holds GPU lock after A completed Stage 3.5')

            if (
                not wait_pool_logged
                and holder == pid_a
                and a_s4
                and ('Stage 3.5' in b_stage or 'wait' in b_stage.lower())
            ):
                wait_pool_logged = True
                _record('b_wait_pool_while_a_stage4', lock_holder=holder[:8])
                _log('Pipeline B in Stage 3.5 wait pool while A in Stage 4')

            if not wait_pool_logged and holder and holder != pid_b and 'Stage 3.5' in b_stage:
                wait_pool_logged = True
                _record('b_wait_pool', lock_holder=holder[:8], b_stage=b_stage)

            statuses = [_job(gui, p).get('status') for p in pipeline_ids]
            if all(s in ('done', 'completed', 'error', 'stopped', 'failed') for s in statuses):
                _log(f'Both pipelines terminal: {dict(zip([p[:8] for p in pipeline_ids], statuses))}')
                break

            if _STOP_AFTER_S35 and all(_stage35_done(gui, p) for p in pipeline_ids):
                _log('Both completed Stage 3.5 — stop requested (ZYG_STAGGER_AB_STOP_AFTER_S35)')
                for p in pipeline_ids:
                    ev = _job(gui, p).get('stop_event')
                    if ev:
                        ev.set()
                break

            if _STOP_AFTER_S4 and all(_stage4_done(gui, p) for p in pipeline_ids):
                _log('Both completed Stage 4 — stop requested (parity TTS overlap proven)')
                for p in pipeline_ids:
                    ev = _job(gui, p).get('stop_event')
                    if ev:
                        ev.set()
                break

            time.sleep(_POLL_STAGE_S * 4)
    except Exception as exc:
        _log(f'Harness monitor error (non-fatal): {exc}')
    finally:
        mon_stop.set()
        mon.join(timeout=15)

    passed = False
    results = {
        'profile': _PROFILE,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'b_launch_mode': b_launch_mode,
        'wait_a_stage4_s': round(wait_a_s4, 1),
        'parity_scene_count': _PARITY_SCENE_COUNT if not _IS_SMOKE else None,
        'parity_duration_sec': _PARITY_DURATION_SEC if not _IS_SMOKE else None,
        'narration_enabled': narration_enabled,
        'char_id': char_id or None,
        'smoke_max_images': gui._SCHOLARLY_SMOKE_MAX_IMAGES,
        'pipeline_a': pid_a,
        'pipeline_b': pid_b,
        'events': events,
        'overlap_a_stage4_b_upstream': overlap_a_s4_b_pre_s35,
        'wait_pool_observed': wait_pool_logged,
        'b_acquired_after_a_stage35': b_acquired_after_a_s35,
        'final_jobs': {
            p: {
                'status': _job(gui, p).get('status'),
                'stage': _job_stage(gui, p),
                'stage35_completed': _stage35_done(gui, p),
                'stage4_completed': _stage4_done(gui, p),
                'error': _job(gui, p).get('error'),
            }
            for p in pipeline_ids
        },
        'telemetry_samples': len(telemetry),
        'last_vram': _vram_snapshot(),
        'last_lock': _lock_meta(),
        'elapsed_s': round(time.time() - t0, 1),
    }

    try:
        out = _RUNTIME / f'stagger_ab_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w', encoding='utf-8') as fh:
            json.dump({'summary': results, 'telemetry': telemetry[-240:]}, fh, indent=2)
        _log(f'Report: {out}')
    except Exception as exc:
        _log(f'Failed to write report JSON: {exc}')

    if _IS_SMOKE:
        passed = results['final_jobs'][pid_a].get('stage35_completed') and results['final_jobs'][pid_b].get(
            'stage35_completed'
        )
    else:
        _a_st = results['final_jobs'][pid_a].get('status')
        _b_st = results['final_jobs'][pid_b].get('status')
        passed = (
            wait_a_s4 > 0
            and results['overlap_a_stage4_b_upstream']
            and results['final_jobs'][pid_a].get('stage35_completed')
            and results['final_jobs'][pid_b].get('stage35_completed')
            and (_STOP_AFTER_S4 and (results['final_jobs'][pid_a].get('stage4_completed') or _in_stage4(gui, pid_a)))
            or (not _STOP_AFTER_S4 and _a_st == 'completed' and _b_st == 'completed')
        )

    _log(f'PASS={passed}')
    exit_code = 0 if passed else 1
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
