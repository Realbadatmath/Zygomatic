# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_jackmona_daily.py — the two children's SERIES, one episode each per day.

2026-10-02, operator: "one workflow for children's music that generates 2
children's songs a day — Life of Jack and Life of Mona."

The fourth sibling of the daily batchers (bp_zero documentary auto-mode,
bp_storyteller_daily, bp_melody_daily) and it follows their contract exactly:

  * imported at the BOTTOM of crewai_web_gui.py, where the main globals exist and
    the running __main__ instance is aliased as `crewai_web_gui` in sys.modules;
  * single Flask process + use_reloader=False, so the watcher daemon started at
    import runs exactly once;
  * TWO SEQUENTIAL runs, never two at once — a song render holds the GPU and the
    picture leg holds ComfyUI's single submit lock, and
    /api/internal/kidsmusic/start refuses to start while any pipeline is running.
    This batcher enforces that itself rather than firing a start into a 409;
  * restart-safe: `_workflow_jobs` is in-process and the health probe has
    restarted this GUI dozens of times, several times mid-song, so an episode
    whose pipeline id is not in the registry is settled from DISK (its own
    manifest) instead of waiting forever.

WHAT IS DIFFERENT FROM THE MELODY BATCHER. That one invents five unrelated songs
a day. This one runs two SERIES: who the children are, what they look like, what
today's episode is about and how long it runs all come from
`kids_series_people`, which keeps the ledger of every episode so tomorrow does
not sing today again. The batcher here is only the clock and the queue.

WHY THE EPISODE IS RECORDED AT START, NOT AT FINISH. A crash between start and
finish would otherwise hand tomorrow the same moment. A missing episode is a gap;
a repeated episode looks like a series with no memory, which is worse.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import timedelta as _timedelta

from flask import Blueprint, jsonify, request

from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log  # noqa: E402

from zyg_workflows import kids_series_people as P
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('jackmona', __name__)

_JM_DAILY_PATH = os.path.join(_RUNTIME_DIR, 'jackmona_daily.json')
_JM_BATCH_PATH = os.path.join(_RUNTIME_DIR, 'jackmona_daily_batch.json')
_JM_OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'kidsmusic')
_JM_LOCK = threading.RLock()

# 03:00 Amsterdam, on the operator's call: the pair takes about an hour of GPU
# and this way it never competes with work anyone is watching.
_JM_HOUR = max(0, min(23, int(os.environ.get('ZYG_JACKMONA_HOUR', '3'))))
# The same free-RAM gate every other batcher on this box uses.
_JM_MIN_FREE_RAM_GB = float(os.environ.get('ZYG_JACKMONA_MIN_FREE_RAM_GB', '24'))
# A pipeline id that is not in the registry and has no manifest yet is treated as
# ours for this long before being called orphaned.
_JM_ORPHAN_STALE_S = 900


# ── settings, read at every tick so the board can change them live ───────────


def _aq_get(key, default):
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get('jackmona', key)
    except Exception:  # noqa: BLE001 — env default is the floor
        return default


def _jm_hour() -> int:
    try:
        return max(0, min(23, int(_aq_get('hour', _JM_HOUR))))
    except (TypeError, ValueError):
        return _JM_HOUR


def _jm_min_ram() -> float:
    return _JM_MIN_FREE_RAM_GB


def _jm_free_ram_gb() -> float:
    """Free RAM in GB. MemAvailable, not MemFree — the page cache is reclaimable
    and counting only MemFree held the batch back on a box that was fine."""
    try:
        with open('/proc/meminfo', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return float(line.split()[1]) / (1024.0 * 1024.0)
    except OSError as _exc:
        _zyg_log.warning('/proc/meminfo unreadable, assuming RAM is free: %s', _exc)
    return 999.0


def _jm_pipeline_busy() -> str:
    """The pipeline id currently holding the box, or ''. Any department counts —
    a documentary render and a song render want the same GPU."""
    try:
        for pid, j in list(_workflow_jobs.items()):
            if j.get('status') == 'running':
                return str(pid)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('running-job scan failed, treating the box as idle: %s', _exc)
    return ''


# ── state files ──────────────────────────────────────────────────────────────


def _jm_today() -> str:
    return _ams_now().strftime('%Y-%m-%d')


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return default
    return d if isinstance(d, type(default)) else default


def _save(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def _daily_load() -> dict:
    d = _load(_JM_DAILY_PATH, {})
    return {
        'enabled': bool(d.get('enabled')),
        'paused': bool(d.get('paused')),
        'done_date': d.get('done_date'),
        'last_run_at': d.get('last_run_at'),
    }


def _daily_save(d: dict) -> None:
    _save(_JM_DAILY_PATH, d)


def _batch_load() -> dict:
    return _load(_JM_BATCH_PATH, {})


def _batch_save(b: dict) -> None:
    _save(_JM_BATCH_PATH, b)


# ── settling an episode from the registry, or from disk after a restart ───────


def _disk_outcome(pid: str) -> str:
    """'done' | 'failed' | '' — read off the song's own manifest, which is the
    only witness that survives a GUI restart."""
    if not pid:
        return ''
    man = os.path.join(_JM_OUT_ROOT, pid, 'manifest.json')
    try:
        with open(man, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return ''
    if d.get('ok') is True:
        return 'done'
    if d.get('ok') is False:
        return 'failed'
    return 'done' if (d.get('delivery') or {}).get('picked') else ''


def _pipeline_outcome(entry: dict) -> str:
    """'done' | 'failed' | '' (still running)."""
    pid = entry.get('pipeline_id')
    if not pid:
        return 'failed'
    try:
        j = _workflow_jobs.get(pid)
    except Exception:  # noqa: BLE001
        j = None
    if j is not None:
        st = str(j.get('status') or '')
        if st == 'running':
            return ''
        if st in ('completed', 'done', 'finished'):
            return 'done'
        if st in ('failed', 'error', 'stopped', 'aborted'):
            return _disk_outcome(pid) or 'failed'
        return ''
    # Not in the registry: this process never launched it, so we were restarted
    # under it. Disk decides; until the manifest exists, give it a grace window.
    out = _disk_outcome(pid)
    if out:
        return out
    started = entry.get('started_at') or ''
    try:
        from datetime import datetime

        t0 = datetime.fromisoformat(started)
        age = (_ams_now() - t0).total_seconds()
    except Exception:  # noqa: BLE001
        age = _JM_ORPHAN_STALE_S + 1
    return '' if age < _JM_ORPHAN_STALE_S else 'failed'


def _title_of(pid: str) -> str:
    try:
        with open(os.path.join(_JM_OUT_ROOT, pid, 'manifest.json'), encoding='utf-8') as fh:
            return str(json.load(fh).get('title') or '')[:120]
    except (OSError, ValueError):
        return ''


# ── the day's pair ───────────────────────────────────────────────────────────


def _create_batch() -> dict:
    """Today's two episodes: Jack then Mona, both 'scheduled'.

    The moment and the episode number are decided HERE and written to the ledger
    immediately, so the pair is fixed even if the box reboots before either song
    starts — and so the two never pick the same moment.
    """
    with _JM_LOCK:
        today = _jm_today()
        eps = []
        for i, slug in enumerate(P.SLUGS):
            brief = P.episode_brief(slug)
            P.record_episode(
                slug,
                brief['theme'],
                n=brief['episode'],
                seconds=brief['seconds'],
                date=today,
                extra={'status': 'scheduled'},
            )
            eps.append(
                {
                    'id': i,
                    'series': slug,
                    'name': P.PEOPLE[slug]['name'],
                    'episode': brief['episode'],
                    'moment': brief['theme'],
                    'seconds': brief['seconds'],
                    'singer': brief['singer'],
                    'status': 'scheduled',
                    'pipeline_id': None,
                    'title': None,
                    'started_at': None,
                    'ended_at': None,
                    'error': None,
                }
            )
        batch = {'batch_date': today, 'created_at': _ams_iso(), 'auto': True, 'episodes': eps}
        _batch_save(batch)
        _zero_audit_log(
            'jackmona_batch_created',
            {
                'date': today,
                'episodes': [f'{e["name"]} #{e["episode"]}: {e["moment"][:80]}' for e in eps],
            },
        )
        return batch


def _start_episode(entry: dict) -> None:
    """Launch one episode through the Children's Music pipeline."""
    try:
        from zyg_workflows import pipeline_kidsmusic as _km
    except Exception as e:  # noqa: BLE001
        entry['status'] = 'failed'
        entry['error'] = f"children's music workflow unavailable: {type(e).__name__}"
        entry['ended_at'] = _ams_iso()
        return
    try:
        song = P.episode_brief(entry['series'], moment=entry['moment'], n=entry['episode'])
    except Exception as e:  # noqa: BLE001
        entry['status'] = 'failed'
        entry['error'] = f'brief failed: {type(e).__name__}: {e}'[:200]
        entry['ended_at'] = _ams_iso()
        return
    try:
        info = _km.start_kidsmusic(directive=song['theme'], song=song)
    except Exception as e:  # noqa: BLE001
        info = {'error': f'{type(e).__name__}: {e}'}
    info = info if isinstance(info, dict) else {}
    pid = info.get('job_id') or info.get('pipeline_id')
    if pid and info.get('status') == 'running' and not info.get('error'):
        entry['status'] = 'in_production'
        entry['pipeline_id'] = pid
        entry['started_at'] = _ams_iso()
        P.attach_job(entry['series'], entry['episode'], pid)
        _zero_audit_log(
            'jackmona_episode_started',
            {
                'series': entry['series'],
                'episode': entry['episode'],
                'moment': entry['moment'][:200],
                'pipeline_id': pid,
                'seconds': entry.get('seconds'),
            },
        )
    else:
        entry['status'] = 'failed'
        entry['error'] = (info or {}).get('error') or 'start failed'
        entry['ended_at'] = _ams_iso()
        _zero_audit_log(
            'jackmona_episode_start_failed',
            {'series': entry['series'], 'episode': entry['episode'], 'error': entry['error']},
        )


def _batch_tick() -> None:
    """Settle whatever is in production, then start the next scheduled episode —
    only while the toggle is on, the box is free and RAM allows."""
    with _JM_LOCK:
        batch = _batch_load()
        eps = batch.get('episodes') if isinstance(batch, dict) else None
        if not eps:
            return
        changed = False

        for e in eps:
            if e.get('status') == 'in_production':
                outcome = _pipeline_outcome(e)
                if outcome == 'done':
                    e['status'] = 'done'
                    e['ended_at'] = _ams_iso()
                    e['title'] = _title_of(e.get('pipeline_id') or '')
                    P.settle_episode(e['series'], e.get('pipeline_id'), title=e['title'], status='done')
                    changed = True
                elif outcome == 'failed':
                    e['status'] = 'failed'
                    e['ended_at'] = _ams_iso()
                    e['error'] = e.get('error') or 'pipeline failed'
                    P.settle_episode(e['series'], e.get('pipeline_id'), status='failed')
                    changed = True
                break  # sequential: one at a time

        if changed:
            _batch_save(batch)
        if any(e.get('status') == 'in_production' for e in eps):
            return

        daily = _daily_load()
        if not daily.get('enabled') or daily.get('paused'):
            return
        nxt = next((e for e in eps if e.get('status') == 'scheduled'), None)
        if not nxt:
            return
        if _jm_pipeline_busy():
            return  # another department has the GPU
        if _jm_free_ram_gb() < _jm_min_ram():
            return  # retry next tick
        _start_episode(nxt)
        _batch_save(batch)


def _scheduler_tick() -> None:
    """At most one pair per calendar day, and never on top of a live one.

    Carry-over rather than replacement: if yesterday's pair has not settled (a
    long picture leg, a box busy all night) it finishes first. No episode is
    abandoned to make room for a new day.
    """
    daily = _daily_load()
    if not daily.get('enabled'):
        return
    today = _jm_today()
    if daily.get('done_date') == today:
        return
    batch = _batch_load()
    if isinstance(batch, dict) and batch.get('episodes'):
        if any(e.get('status') in ('scheduled', 'in_production') for e in batch['episodes']):
            return
    if _ams_now().hour < _jm_hour():
        return
    _create_batch()
    daily['done_date'] = today
    daily['last_run_at'] = _ams_iso()
    _daily_save(daily)


def _watcher() -> None:
    """Daemon: fire the day's pair and advance it, every 30 s."""
    while True:
        time.sleep(30)
        for fn in (_scheduler_tick, _batch_tick):
            try:
                fn()
            except Exception as _exc:  # noqa: BLE001 — a tick must never die
                _zyg_log.warning('jackmona %s tick failed, retrying in 30 s: %s', fn.__name__, _exc)


def _next_run_label() -> str:
    daily = _daily_load()
    if not daily.get('enabled'):
        return ''
    batch = _batch_load()
    if isinstance(batch, dict) and batch.get('episodes'):
        if any(e.get('status') in ('scheduled', 'in_production') for e in batch['episodes']):
            return 'after the current pair'
    now = _ams_now()
    today = now.strftime('%Y-%m-%d')
    due_today = now.hour < _jm_hour() and daily.get('done_date') != today
    day = today if due_today else (now + _timedelta(days=1)).strftime('%Y-%m-%d')
    return f'{day} {_jm_hour():02d}:00'


def _set_enabled(enabled: bool) -> dict:
    with _JM_LOCK:
        d = _daily_load()
        d['enabled'] = bool(enabled)
        if not enabled:
            d['paused'] = False
        _daily_save(d)
        _zero_audit_log('jackmona_daily_mode', {'enabled': bool(enabled)})
        return d


def _set_paused(paused: bool) -> dict:
    with _JM_LOCK:
        d = _daily_load()
        d['paused'] = bool(paused)
        _daily_save(d)
        _zero_audit_log('jackmona_daily_pause', {'paused': bool(paused)})
        return d


def _abort() -> dict:
    """Stop a running episode and mark the rest of today's pair aborted. The
    ledger keeps its rows — a moment that was spent is spent."""
    with _JM_LOCK:
        batch = _batch_load()
        stopped = None
        for e in batch.get('episodes') or []:
            if e.get('status') == 'in_production' and e.get('pipeline_id'):
                # The same two steps bp_melody_daily's abort uses: the job's own
                # stop event, then the latched halt every GPU submitter checks.
                try:
                    job = _workflow_jobs.get(e['pipeline_id'])
                    ev = (job or {}).get('stop_event')
                    if ev is not None:
                        ev.set()
                    from zyg_workflows import pipeline_control as _pc

                    _pc.request_halt('Aborted from the Approval Queue')
                    stopped = e['pipeline_id']
                except Exception as _exc:  # noqa: BLE001
                    _zyg_log.warning(
                        'halt request for %s failed, marking the entry failed anyway: %s', e['pipeline_id'], _exc
                    )
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
            elif e.get('status') == 'scheduled':
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
        _batch_save(batch)
        _zero_audit_log('jackmona_abort', {'stopped': stopped})
        return {'ok': True, 'stopped': stopped}


# ── HTTP ─────────────────────────────────────────────────────────────────────


@bp.route('/api/jackmona/daily_mode', methods=['GET', 'POST'])
def api_jackmona_daily_mode():
    """GET or POST the two-series daily toggle (POST {enabled|paused: bool})."""
    if request.method == 'POST' and request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'localhost only'}), 401
    if request.method == 'GET':
        return jsonify(_daily_load())
    data = request.get_json(silent=True) or {}
    if 'paused' in data:
        return jsonify({'ok': True, 'state': _set_paused(bool(data['paused']))})
    try:
        state = _set_enabled(bool(data.get('enabled')))
    except Exception as e:  # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'enabled': state['enabled'], 'state': state})


@bp.route('/api/jackmona/daily_batch')
def api_jackmona_daily_batch():  # read-only; the card and the operator's shell
    """Today's pair, the toggle, and both series' ledgers — for the board."""
    return jsonify(
        {
            'batch': _batch_load() or None,
            'daily': _daily_load(),
            'next_run': _next_run_label(),
            'busy_with': _jm_pipeline_busy(),
            'series': P.series_rows(),
            'seconds_band': list(__import__('zyg_workflows.kids_music_theory').SONG_SECONDS),
        }
    )


@bp.route('/api/jackmona/abort', methods=['POST'])
def api_jackmona_abort():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'localhost only'}), 401
    return jsonify(_abort())


@bp.route('/api/jackmona/run_now', methods=['POST'])
def api_jackmona_run_now():
    """Build today's pair now instead of waiting for the hour. The toggle still
    governs whether the tick will START them, so this cannot smuggle production
    past a disabled workflow."""
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'localhost only'}), 401
    batch = _batch_load()
    if isinstance(batch, dict) and any(
        e.get('status') in ('scheduled', 'in_production') for e in (batch.get('episodes') or [])
    ):
        return jsonify({'ok': False, 'error': 'a pair is already in flight', 'batch': batch}), 409
    b = _create_batch()
    d = _daily_load()
    d['done_date'] = _jm_today()
    d['last_run_at'] = _ams_iso()
    _daily_save(d)
    return jsonify({'ok': True, 'batch': b, 'enabled': d['enabled']})


# ── the watcher (single process, use_reloader=False → runs once) ──────────────
threading.Thread(target=_watcher, daemon=True, name='jackmona-daily-watcher').start()
