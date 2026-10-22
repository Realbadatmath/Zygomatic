# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bp_zero — the kanban board store, batch creation and the kanban / auto-scheduler ticks.

Moved verbatim out of bp_zero.py (original lines 1232-1670) by the 2026-10-06
modularization wave; zero logic edits.
"""

from zyg_dashboard.bp_zero.constants import (
    _AMS_TZ,
    _RUNTIME_DIR,
    _ZERO_AUTO_MODE_PATH,
    _ZERO_BATCH_SCHEDULE_PATH,
    _ZERO_KANBAN_LOCK,
    _ZERO_KANBAN_PATH,
    _ams_iso,
    _ams_now,
    _resolve_pipeline_public_status,
    _start_scholarly_pipeline_internal,
    _workflow_jobs,
    _zero_audit_log,
    _zyg_log,
    _zyg_pkg_dir,
    gui_state,
    json,
    os,
    time,
)
from zyg_dashboard.bp_zero.topics import (
    _aq_bank,
    _aq_get,
    _aq_topics_per_batch,
    _zero_bank_settle,
    _zero_compute_batch_publish_slots,
    _zero_next_batch_topics,
    _zero_pipeline_options_for,
)

# ── re-export surface ────────────────────────────────────────────────────────
# This module inherits the pre-split top import block. `_zyg_pkg_dir` is the
# only name in it this file does not read itself; it is kept here because the
# package's modules re-import the block off each other. Declaring it is what
# makes the re-export deliberate rather than an unused import; nothing does
# ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    '_zyg_pkg_dir',
]


_ZERO_KANBAN_ARCHIVE_PATH = os.path.join(_RUNTIME_DIR, 'zero_kanban_archive.jsonl')


def _zero_kanban_load() -> dict:
    try:
        with open(_ZERO_KANBAN_PATH, 'r', encoding='utf-8') as _f:
            return json.load(_f)
    except Exception:
        return {}


def _zero_kanban_save(batch: dict) -> None:
    try:
        with open(_ZERO_KANBAN_PATH, 'w', encoding='utf-8') as _f:
            json.dump(batch, _f, indent=2)
    except Exception as _exc:
        _zyg_log.warning('kanban board not saved, the change is lost on restart: %s', _exc)


def _zero_kanban_completed_at(batch: dict) -> str:
    """When the batch finished: the latest ended_at across its topics, else created_at."""
    ends = [e.get('ended_at') for e in (batch.get('topics') or []) if e.get('ended_at')]
    return max(ends) if ends else (batch.get('created_at') or '')


def _zero_kanban_retire_if_stale(batch: dict) -> bool:
    """Archive a finished batch and clear the live slot once it is old enough.

    2026-09-06: zero_kanban_batch.json is a SINGLE-SLOT file that was only ever
    overwritten by the next batch — never cleared. With auto-mode off there is no
    next batch, so the Approval Queue board kept presenting a long-finished batch
    as the current queue (a 2026-08-14 documentary was still sitting in "Done"
    three weeks later). Nothing was stuck: the pipeline had completed and
    _zero_auto_scheduler_tick already ignores batches with no active items — the
    board was just showing a stale file.

    A finished batch stays visible for ZYG_KANBAN_RETAIN_HOURS (default 24) so the
    operator still sees the day's result, then moves to zero_kanban_archive.jsonl
    (history is kept, not deleted) and the live slot is cleared.

    Returns True when the batch was retired.
    """
    topics = batch.get('topics') or []
    if not topics or not all(e.get('status') in ('done', 'failed') for e in topics):
        return False
    try:
        retain_h = float(os.environ.get('ZYG_KANBAN_RETAIN_HOURS', '24'))
    except Exception:
        retain_h = 24.0
    done_at = _zero_kanban_completed_at(batch)
    if retain_h > 0 and done_at:
        try:
            from datetime import datetime as _dt_r, timedelta as _td_r

            _d = _dt_r.fromisoformat(done_at)
            if _d.tzinfo is None:
                _d = _d.replace(tzinfo=_AMS_TZ)
            if _ams_now() - _d < _td_r(hours=retain_h):
                return False  # still today's result — keep it on the board
        except Exception as _exc:
            _zyg_log.warning('completion time %r unparsable, archiving the board anyway: %s', done_at, _exc)
    try:
        rec = dict(batch)
        rec['archived_at'] = _ams_iso()
        rec['completed_at'] = done_at
        with open(_ZERO_KANBAN_ARCHIVE_PATH, 'a', encoding='utf-8') as _f:
            _f.write(json.dumps(rec) + '\n')
    except Exception as _exc:
        _zyg_log.warning('kanban archive append failed, this batch is not kept: %s', _exc)
    try:
        os.remove(_ZERO_KANBAN_PATH)
    except FileNotFoundError as _exc:
        _zyg_log.debug('no kanban board file to remove: %s', _exc)
    except Exception:
        _zero_kanban_save({})
    _zero_audit_log(
        'kanban_batch_archived',
        {
            'batch_id': batch.get('batch_id'),
            'completed_at': done_at,
            'topics': len(topics),
        },
    )
    return True


def _zero_auto_mode_load() -> dict:
    try:
        with open(_ZERO_AUTO_MODE_PATH, 'r', encoding='utf-8') as _f:
            return json.load(_f)
    except Exception:
        return {'enabled': False, 'paused': False, 'next_run_utc': None, 'last_run_at': None}


def _zero_auto_mode_save(state: dict) -> None:
    try:
        with open(_ZERO_AUTO_MODE_PATH, 'w', encoding='utf-8') as _f:
            json.dump(state, _f, indent=2)
    except Exception as _exc:
        _zyg_log.warning('auto mode state not saved, the cadence is lost on restart: %s', _exc)


def _zero_kanban_pipeline_outcome(pipeline_id: str) -> str:
    """Returns 'running' | 'done' | 'failed' | 'unknown' for a given pipeline."""
    job = _workflow_jobs.get(pipeline_id)
    if job:
        pub = _resolve_pipeline_public_status(job)
        if pub == 'running':
            return 'running'
        if pub == 'completed':
            return 'done'
        if pub in ('failed', 'stopped', 'interrupted'):
            return 'failed'
    st_path = os.path.join(_RUNTIME_DIR, f'pipeline_{pipeline_id}_state.json')
    try:
        with open(st_path, 'r', encoding='utf-8') as _f:
            st = json.load(_f)
        if st.get('ended') and not (st.get('error') or '').strip():
            return 'done'
        if (st.get('error') or '').strip():
            return 'failed'
        if (st.get('status') or '') in ('done', 'completed'):
            return 'done'
        if (st.get('status') or '') == 'running':
            return 'running'
    except Exception as _exc:
        _zyg_log.debug('pipeline state %s unreadable, outcome stays unknown: %s', st_path, _exc)
    return 'unknown'


def _zero_kanban_create_batch(topics: list, auto_triggered: bool = False) -> None:
    """Create a new kanban batch and immediately start the first pipeline.

    Safe to call from any thread.  Acquires _ZERO_KANBAN_LOCK internally.
    """
    import uuid as _uuid_kb

    _cap = _aq_topics_per_batch()
    entries = []
    for i, t in enumerate(list(topics)[:_cap]):
        _t = t if isinstance(t, dict) else {'topic': t}
        entries.append(
            {
                'id': i,
                'topic': _t.get('topic'),
                'status': 'scheduled',
                'pipeline_id': None,
                'started_at': None,
                'ended_at': None,
                'bank_id': _t.get('bank_id'),
                'pool': _t.get('label'),
            }
        )
    batch = {
        'batch_id': str(_uuid_kb.uuid4())[:8],
        'created_at': _ams_iso(),
        'auto_triggered': auto_triggered,
        'topics': entries,
    }
    # Publish schedule FIRST, then start pipeline 1. The old order started the
    # pipeline and wrote the schedule afterwards, leaving a window in which the
    # run could claim a slot from the PREVIOUS batch's file — whose times are by
    # then in the past. The window was never reached in practice (an episode
    # needs ~45 min before it surfaces in the approval queue and claims), but
    # the ordering was only accidentally safe. Writing first removes the race.
    try:
        _batch_slots = _zero_compute_batch_publish_slots(len(entries))
        with open(_ZERO_BATCH_SCHEDULE_PATH, 'w', encoding='utf-8') as _bsf:
            json.dump(
                {
                    'batch_id': batch['batch_id'],
                    'created_at': batch['created_at'],
                    'count': len(_batch_slots),
                    'slots': _batch_slots,
                },
                _bsf,
                indent=2,
            )
    except Exception as _exc:
        _zyg_log.warning('batch schedule sidecar not written, the slots are not visible: %s', _exc)

    # Start first pipeline
    if entries:
        first = entries[0]
        try:
            info = _start_scholarly_pipeline_internal(
                directive=first['topic'],
                topic='scholarly',
                narration_enabled=True,
                visual_style='cinematic',
                model_family='flux',
                pipeline_options=_zero_pipeline_options_for(first),
            )
            first['pipeline_id'] = info['job_id']
            if first.get('bank_id') and _aq_bank() is not None:
                _aq_bank().attach(first['bank_id'], info['job_id'])
            first['status'] = 'in_production'
            first['started_at'] = _ams_iso()
        except Exception:
            first['status'] = 'failed'
            first['ended_at'] = _ams_iso()

    with _ZERO_KANBAN_LOCK:
        _zero_kanban_save(batch)


def _mem_available_gb() -> float:
    """MemAvailable from /proc/meminfo in GB, or -1.0 when unreadable."""
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1048576.0
    except Exception as _exc:
        _zyg_log.debug('MemAvailable unreadable, reporting -1: %s', _exc)
    return -1.0


def _zero_batch_release_models() -> None:
    """Drop in-process model caches between batch items and return heap to the OS.

    Documentary pipelines run FLUX/T5/ControlNet inside this process; letting one
    item's residency overlap the next item's load OOM-killed the server
    (42 GB RSS, 2026-07-05 09:51). Reload cost per item is minutes; a crash
    costs the whole batch.
    """
    pass  # (global stmt removed: names moved to gui_state)
    try:
        gui_state._FLUX_PIPELINE_CACHE = None
        gui_state._FLUX_DEV_PIPELINE_CACHE = None
        gui_state._CN_PIPE_CACHE = None
    except Exception as _exc:
        _zyg_log.debug('flux pipeline cache release skipped: %s', _exc)
    try:
        # The scholarly FLUX stack lives in ScholarlyFluxWorker._pipe, not the
        # caches above — the 11:11 OOM showed this release missed the real holder.
        from zyg_workflows import scholarly_stills_backend as _ssb_bat

        _fw_bat = _ssb_bat.ScholarlyFluxWorker.get()
        if _fw_bat.is_running():
            _fw_bat.emergency_stop()
    except Exception as _exc:
        _zyg_log.warning('scholarly flux worker not stopped, its VRAM stays held: %s', _exc)
    try:
        import gc as _gc

        _gc.collect()
    except Exception as _exc:
        _zyg_log.debug('gc collect skipped: %s', _exc)
    try:
        import torch as _torch_rel

        if _torch_rel.cuda.is_available():
            _torch_rel.cuda.empty_cache()
    except Exception as _exc:
        _zyg_log.debug('cuda cache not emptied: %s', _exc)
    try:
        # glibc keeps freed arenas mapped; trim so RSS actually drops for the OOM killer's math.
        import ctypes as _ct

        _ct.CDLL('libc.so.6').malloc_trim(0)
    except Exception as _exc:
        _zyg_log.debug('malloc_trim skipped, RSS may stay high: %s', _exc)


def _zero_kanban_tick() -> None:
    """Advance the kanban batch: detect pipeline completion, then start the next scheduled entry."""
    with _ZERO_KANBAN_LOCK:
        batch = _zero_kanban_load()
        if not batch:
            return
        topics = batch.get('topics', [])
        changed = False

        # Detect completion of any in_production pipeline
        for entry in topics:
            if entry.get('status') != 'in_production':
                continue
            pid = entry.get('pipeline_id')
            if not pid:
                continue
            outcome = _zero_kanban_pipeline_outcome(pid)
            if outcome == 'done':
                entry['status'] = 'done'
                entry['ended_at'] = _ams_iso()
                _zero_bank_settle(entry, 'done')
                changed = True
            elif outcome == 'failed':
                entry['status'] = 'failed'
                entry['ended_at'] = _ams_iso()
                _zero_bank_settle(entry, 'failed')
                changed = True

        # Start next scheduled entry when nothing is in_production
        if not any(e.get('status') == 'in_production' for e in topics):
            next_e = next((e for e in topics if e.get('status') == 'scheduled'), None)
            if next_e and _zero_auto_mode_load().get('paused'):
                next_e = None  # Approval Queue: paused — finish, start nothing
            if next_e:
                pass  # (global stmt removed: names moved to gui_state)
                # Structural RAM safety: fresh slate between items, then hold
                # this tick (watcher retries in 30 s) until MemAvailable clears
                # the gate — starting anyway is how the 09:51 OOM happened.
                _zero_batch_release_models()
                _min_gb = float(_aq_get('min_free_ram_gb', os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24')))
                _avail = _mem_available_gb()
                if _min_gb > 0 and 0 <= _avail < _min_gb:
                    if not gui_state._ZERO_RAM_GATE_HOLDING:
                        gui_state._ZERO_RAM_GATE_HOLDING = True
                        _zyg_log.info(
                            f'[ZERO-KANBAN] RAM gate holding next item — '
                            f'{_avail:.1f} GB available < {_min_gb:.0f} GB required'
                        )
                        _zero_audit_log(
                            'auto_mode_ram_gate_hold',
                            {
                                'available_gb': round(_avail, 1),
                                'required_gb': _min_gb,
                                'next_topic': (next_e.get('topic') or '')[:80],
                            },
                        )
                    if changed:
                        _zero_kanban_save(batch)
                    return
                if gui_state._ZERO_RAM_GATE_HOLDING:
                    gui_state._ZERO_RAM_GATE_HOLDING = False
                    _zyg_log.info(f'[ZERO-KANBAN] RAM gate released — {_avail:.1f} GB available')
                    _zero_audit_log(
                        'auto_mode_ram_gate_release',
                        {
                            'available_gb': round(_avail, 1),
                        },
                    )
                try:
                    info = _start_scholarly_pipeline_internal(
                        directive=next_e['topic'],
                        topic='scholarly',
                        narration_enabled=True,
                        visual_style='cinematic',
                        model_family='flux',
                        pipeline_options=_zero_pipeline_options_for(next_e),
                    )
                    next_e['pipeline_id'] = info['job_id']
                    if next_e.get('bank_id') and _aq_bank() is not None:
                        _aq_bank().attach(next_e['bank_id'], info['job_id'])
                    next_e['status'] = 'in_production'
                    next_e['started_at'] = _ams_iso()
                    changed = True
                except Exception:
                    next_e['status'] = 'failed'
                    next_e['ended_at'] = _ams_iso()
                    changed = True

        if changed:
            _zero_kanban_save(batch)

        # When the whole batch finishes and auto mode is on, arm the recurring schedule.
        # next_run_utc=None means "waiting for batch to complete before scheduling next run".
        if topics and all(e.get('status') in ('done', 'failed') for e in topics):
            _auto = _zero_auto_mode_load()
            if _auto.get('enabled') and not _auto.get('next_run_utc'):
                from datetime import timedelta as _td_next

                _next = (_ams_now() + _td_next(days=int(_aq_get('cadence_days', 2)))).replace(
                    hour=int(_aq_get('batch_hour', 9)), minute=0, second=0, microsecond=0
                )
                _auto['next_run_utc'] = _next.isoformat()
                _zero_auto_mode_save(_auto)
            # ...then retire it off the board once it is no longer today's result.
            _zero_kanban_retire_if_stale(batch)


def _zero_auto_scheduler_tick() -> None:
    """Fire a new kanban batch if Zero auto-mode is enabled and the scheduled time has arrived."""
    state = _zero_auto_mode_load()
    if not state.get('enabled'):
        return
    next_run = state.get('next_run_utc')
    if not next_run:
        return
    _now = _ams_now()
    try:
        from datetime import datetime as _dt_as

        _next = _dt_as.fromisoformat(next_run)
        if _next.tzinfo is None:
            _next = _next.replace(tzinfo=_AMS_TZ)
    except Exception:
        return
    if _now < _next:
        return

    # Skip if the previous batch still has active items; retry in 1 hour.
    batch = _zero_kanban_load()
    if batch and any(e.get('status') in ('scheduled', 'in_production') for e in batch.get('topics', [])):
        from datetime import timedelta as _td_retry

        state['next_run_utc'] = (_now + _td_retry(hours=1)).isoformat()
        _zero_auto_mode_save(state)
        return

    try:
        picks = _zero_next_batch_topics()
        _zero_kanban_create_batch(picks, auto_triggered=True)
        _zero_audit_log(
            'auto_mode_batch_created',
            {'topics': [t['topic'] for t in picks], 'from_bank': sum(1 for t in picks if t.get('bank_id'))},
        )
    except Exception as _exc:
        _zyg_log.warning('auto mode batch not created, retrying on the next tick: %s', _exc)

    # Clear next_run_utc — the kanban watcher sets it (+2 days @ 09:00 AMS)
    # once the new batch fully completes, keeping the cadence self-correcting.
    try:
        state['next_run_utc'] = None
        state['last_run_at'] = _ams_iso()
        _zero_auto_mode_save(state)
    except Exception as _exc:
        _zyg_log.warning('auto mode cadence not written back, the next run time is stale: %s', _exc)


def _zero_kanban_watcher() -> None:
    """Daemon: advances the sequential kanban queue and fires auto-mode batches every 30 s."""
    while True:
        time.sleep(30)
        try:
            _zero_kanban_tick()
        except Exception as _exc:
            _zyg_log.warning('kanban tick failed, retrying in 30 s: %s', _exc)
        try:
            _zero_auto_scheduler_tick()
        except Exception as _exc:
            _zyg_log.warning('auto scheduler tick failed, retrying in 30 s: %s', _exc)
