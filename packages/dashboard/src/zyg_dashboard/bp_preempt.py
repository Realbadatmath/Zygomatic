# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_preempt.py — the "Pre-Emptive generation" workflow on the Approval Queue board. 2026-09-20.

What it does while ON: builds the bank in preempt_bank.py —
  * documentary: one BRAIN run at a time (the scholarly pipeline in record mode: every
    text Claude call made and written to the entry, the run stops before the first image),
    until `documentary_target` entries are banked. The Documentary batcher then uses those
    entries first and replays their Claude calls, so episodes render with no subscription.
  * songs: `songs_target` children's-song briefs pre-picked by the LOCAL model (the song
    workflow makes no Claude calls at all — this only fills the queue).

Gates before a brain run: login + CLI present, no limit hold (a refused turn holds until
the reset), the quota meter under `quota_ceiling_pct` on both windows, no other pipeline
running (one at a time is the house rule), free RAM, and a short cooldown after a failure.

Controls: play (enable), pause (finish the current run, start nothing), abort (stop the
current run, keep what is banked, switch off). Same contract as bp_melody_daily: imported at
the bottom of crewai_web_gui.py; the watcher daemon runs once per process.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time

from flask import Blueprint, jsonify, request

from zyg_dashboard import preempt_bank as _pb
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _ZERO_POOL_LABELS,
    _ZERO_TOPIC_POOLS_PATH,
)
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('preempt', __name__)
_LOCK = threading.RLock()
_TICK_S = 30
_FAIL_COOLDOWN_S = 120
_SONG_CHUNK = 10
# Measured 2026-09-23: a headless claude CLI process peaks at ~610 MB RSS (10 concurrent
# turns = 6.0 GB), plus the run's own pipeline state in the GUI. 1 GB per concurrent
# recording, over an 8 GB floor for everything else on the box.
_RAM_PER_RUN_GB = 1.0
_RAM_FLOOR_GB = 8.0
_DEFAULT_CONCURRENCY = 20


def _aq_get(key: str, default):
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get('preempt', key)
    except Exception:  # noqa: BLE001
        return default


# ── state ────────────────────────────────────────────────────────────────────


def state_load() -> dict:
    st = _pb.state_load()
    st.setdefault('enabled', False)
    st.setdefault('paused', False)
    st.setdefault('documentary', {})
    st.setdefault('songs', {})
    return st


def state_save(st: dict) -> None:
    _pb.state_save(st)


def _norm(t: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', str(t or '').lower()).strip()


# ── gates ────────────────────────────────────────────────────────────────────


def _busy_pipeline(ignore_preempt: bool = True) -> str:
    """A FOREIGN pipeline that is running, or ''.

    2026-09-23: brain runs used to block each other through this gate. A record run no
    longer synthesises TTS, so it touches no GPU and holds no VRAM — the one-pipeline house
    rule still applies to everything else, but not to the bank's own recordings.
    """
    try:
        for pid, j in _workflow_jobs.items():
            if str(j.get('status') or '').lower() != 'running':
                continue
            if ignore_preempt and (j.get('preempt') or {}).get('mode') == 'record':
                continue
            return pid
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('running-job scan failed, treating the box as idle: %s', _exc)
    return ''


def _running_entries(st: dict) -> list:
    """The bank's own in-flight recordings, oldest first."""
    d = st.setdefault('documentary', {})
    runs = d.get('running')
    if runs is None:  # migrate the old single-slot state
        cur = d.get('current')
        runs = [cur] if cur else []
        d['running'] = runs
    return runs


def _free_ram_gb() -> float:
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1048576.0
    except OSError as _exc:
        _zyg_log.debug('/proc/meminfo unreadable, reporting free RAM as unknown: %s', _exc)
    return -1.0


def gate_reason(n_running: int = 0) -> str:
    """'' when another brain run may start now, else the reason it waits."""
    try:
        from zyg_workflows import subscription_llm as _sl

        if not _sl.login_present():
            return 'no Claude login on this machine'
        if not os.path.exists(_sl.CLI_BIN):
            return 'Claude Code CLI not found'
    except Exception as exc:  # noqa: BLE001
        return f'subscription client unavailable: {type(exc).__name__}'
    holding, until, why = _pb.limit_hold()
    if holding:
        return f'quota hold until {until} ({why})'
    ceiling = float(_aq_get('quota_ceiling_pct', 90))
    q = _pb.quota_snapshot()
    for key, label in (('five_hour_pct', '5-hour'), ('seven_day_pct', '7-day')):
        pct = q.get(key)
        if isinstance(pct, (int, float)) and pct >= ceiling:
            reset = q.get(key.replace('_pct', '_resets_at')) or '?'
            return f'{label} window at {pct:.0f} % ≥ ceiling {ceiling:.0f} % — resumes after {reset}'
    busy = _busy_pipeline()
    if busy:
        return f'another pipeline is running ({busy[:8]})'
    # What the NEXT run needs, not what all of them need: the recordings already going have
    # taken their memory, and MemAvailable already reflects it. Charging for them again made
    # the gate stop at about 15 of a requested 30 on a 63 GB box.
    avail = _free_ram_gb()
    need = max(_RAM_FLOOR_GB + _RAM_PER_RUN_GB, float(_aq_get('min_free_ram_gb', 0) or 0))
    if 0 <= avail < need:
        return f'RAM gate: {avail:.1f} GB free < {need:.1f} GB ({n_running} recording now)'
    st = state_load()
    last_fail = float((st.get('documentary') or {}).get('last_fail_ts') or 0)
    if last_fail and time.time() - last_fail < _FAIL_COOLDOWN_S:
        return f'cooldown after a failed run ({int(_FAIL_COOLDOWN_S - (time.time() - last_fail))} s)'
    return ''


# ── topic picking ────────────────────────────────────────────────────────────


def _produced_topics() -> set:
    try:
        from zyg_dashboard import bp_zero as _bz

        return set(_bz._zero_produced_topics())
    except Exception:  # noqa: BLE001
        return set()


def pick_topic() -> tuple:
    """(label, topic) from the pools, avoiding produced and banked topics; round-robin
    over pools so the bank is as varied as a batch of six."""
    try:
        with open(_ZERO_TOPIC_POOLS_PATH, encoding='utf-8') as fh:
            pools = json.load(fh)
    except (OSError, ValueError):
        return '', ''
    avoid = _produced_topics() | _pb.banked_topics()
    labels = list(_ZERO_POOL_LABELS)
    random.shuffle(labels)
    for key, label in labels:
        fresh = [t for t in (pools.get(key) or []) if _norm(t) not in avoid]
        if fresh:
            return label, random.choice(fresh)
    return '', ''


# ── the documentary brain run ────────────────────────────────────────────────


def _job_outcome(pid: str) -> tuple:
    """('running'|'done'|'failed'|'unknown', error)."""
    job = _workflow_jobs.get(pid or '')
    if job:
        st = str(job.get('status') or '').lower()
        if st == 'running':
            return 'running', ''
        if st == 'completed':
            return 'done', ''
        return 'failed', str(job.get('error') or st)
    try:
        with open(os.path.join(_RUNTIME_DIR, f'pipeline_{pid}_state.json'), encoding='utf-8') as fh:
            d = json.load(fh)
        if d.get('status') == 'completed' and d.get('preempt'):
            return 'done', ''
        if d.get('ended') or d.get('error'):
            return 'failed', str(d.get('error') or 'ended without a snapshot')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('pipeline state unreadable, the outcome stays unknown: %s', _exc)
    return 'unknown', ''


def _settle_current(st: dict) -> bool:
    """Settle every recording that has finished. Returns True if anything changed."""
    d = st['documentary']
    runs = _running_entries(st)
    changed = False
    for cur in list(runs):
        if not cur:
            runs.remove(cur)
            changed = True
            continue
        outcome, err = _job_outcome(cur.get('pipeline_id'))
        if outcome == 'running':
            continue
        if outcome == 'unknown':
            # Restarted under it and no state file: give it one more tick window, then fail.
            started = cur.get('started_ts') or 0
            if time.time() - float(started) < 3 * _TICK_S:
                continue
            outcome, err = 'failed', 'run vanished (GUI restarted?)'
        e = _pb.finish_entry(cur['entry_id'], outcome == 'done', error=err, pipeline_id=cur.get('pipeline_id'))
        runs.remove(cur)
        d['last'] = {
            'entry_id': cur['entry_id'],
            'topic': cur.get('topic'),
            'outcome': outcome,
            'error': err or None,
            'turns': (e or {}).get('turns'),
            'ended_at': _ams_iso(),
        }
        if outcome != 'done':
            d['last_fail_ts'] = time.time()
            if any(w in (err or '').lower() for w in ('limit', 'rejected', 'usage')):
                _pb.note_limit(reason=err)
        _zero_audit_log(
            'preempt_brain_finished',
            {
                'entry': cur['entry_id'],
                'topic': cur.get('topic'),
                'outcome': outcome,
                'error': err or None,
                'turns': (e or {}).get('turns'),
            },
        )
        changed = True
    d['current'] = runs[0] if runs else None  # the card still shows one
    return changed


def _start_brain_run(st: dict) -> bool:
    d = st['documentary']
    # Work in hand first: an entry whose recording was cut off re-runs against the turns it
    # already holds, so it costs only what it never reached. Only then a fresh topic.
    entry = _pb.take_interrupted()
    if entry:
        topic, label = entry['topic'], entry.get('pool') or ''
        _zero_audit_log(
            'preempt_brain_resumed',
            {
                'entry': entry['id'],
                'topic': topic,
                'turns_in_hand': entry.get('turns'),
                'attempt': entry.get('resume_count'),
            },
        )
    else:
        label, topic = pick_topic()
        if not topic:
            d['note'] = 'topic pools exhausted against produced + banked topics'
            return False
        entry = _pb.new_entry(topic, label)
    try:
        info = _start_scholarly_pipeline_internal(
            directive=topic,
            topic='scholarly',
            narration_enabled=True,
            visual_style='cinematic',
            model_family='flux',
            pipeline_options={'preempt': {'mode': 'record', 'entry': entry['id']}},
        )
        pid = info.get('job_id')
    except Exception as exc:  # noqa: BLE001
        _pb.finish_entry(entry['id'], False, error=f'start failed: {exc!r}')
        d['last_fail_ts'] = time.time()
        d['note'] = f'start failed: {exc!r}'[:200]
        return False
    entry['brain_pipeline_id'] = pid
    _pb.save_entry(entry)
    rec = {
        'entry_id': entry['id'],
        'topic': topic,
        'pipeline_id': pid,
        'started_at': _ams_iso(),
        'started_ts': time.time(),
    }
    _running_entries(st).append(rec)
    d['current'] = rec
    d['note'] = ''
    _zero_audit_log('preempt_brain_started', {'entry': entry['id'], 'topic': topic, 'pipeline_id': pid})
    return True


def _documentary_tick(st: dict) -> None:
    # Ghost `building` entries count against the target, so a lost run would otherwise
    # shrink the bank's ceiling for ever (2026-09-23: stopped at 88 of 100 that way).
    try:
        reaped = _pb.reap_stale_building()
        if reaped:
            _zero_audit_log('preempt_stale_reaped', {'entries': reaped})
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('stale building reap failed, ghost entries still count against the target: %s', _exc)
    changed = _settle_current(st)
    d = st['documentary']
    if changed:
        state_save(st)
    if not st.get('enabled') or st.get('paused'):
        return
    target = int(_aq_get('documentary_target', 100))
    want = max(1, int(_aq_get('concurrency', _DEFAULT_CONCURRENCY)))
    started = 0
    for _ in range(want):
        runs = _running_entries(st)
        if len(runs) >= want:
            break
        c = _pb.counts()
        # `building` counts the entries already in flight, so the target is never overshot.
        # `interrupted` entries are unfinished work, not bank: they are not counted here,
        # and _start_brain_run takes them before any fresh topic. What stopped the 09-23
        # build at 88 of 100 was ghost `building` entries, and the reaper above clears those.
        if c['built'] + c['building'] >= target:
            d['note'] = (
                f'target reached: {c["built"]} banked' if not runs else f'{c["built"]} banked, {len(runs)} recording'
            )
            break
        why = gate_reason(len(runs))
        if why:
            if d.get('note') != why:
                d['note'] = why
            break
        if not _start_brain_run(st):
            break
        started += 1
    if started:
        d['note'] = f'{len(_running_entries(st))} recording in parallel'
    state_save(st)


# ── the song briefs ──────────────────────────────────────────────────────────


def _songs_tick(st: dict) -> None:
    s = st['songs']
    if not st.get('enabled') or st.get('paused'):
        return
    target = int(_aq_get('songs_target', 100))
    c = _pb.songs_counts()
    need = target - c['built']
    if need <= 0:
        s['note'] = f'target reached: {c["built"]} briefs banked'
        state_save(st)
        return
    if _busy_pipeline():  # a FOREIGN pipeline only — recordings hold no VRAM
        s['note'] = 'waiting: another pipeline is running (the local model would contend for VRAM)'
        state_save(st)
        return
    try:
        from zyg_dashboard import bp_melody_daily as _bm

        avoid = set(_bm._mel_produced_themes()) | _pb.songs_banked_themes()
        chunk = min(_SONG_CHUNK, need)
        briefs = _bm._mel_propose_briefs(chunk, avoid)
        src = 'llm'
        if len(briefs) < chunk:
            for b in briefs:
                avoid.add(_bm._mel_norm(b['theme']))
            briefs += _bm._mel_pool_briefs(chunk - len(briefs), avoid)
            src = 'llm+pool' if briefs and any(b.get('source') == 'llm' for b in briefs) else 'pool'
        added = _pb.songs_add(briefs)
        s['last_added_at'] = _ams_iso()
        s['last_added'] = added
        s['note'] = f'{added} briefs added ({src})'
        _zero_audit_log('preempt_songs_added', {'added': added, 'source': src})
    except Exception as exc:  # noqa: BLE001
        s['note'] = f'song brief pick failed: {exc!r}'[:200]
    state_save(st)


# ── watcher + controls ───────────────────────────────────────────────────────


def tick() -> None:
    with _LOCK:
        # Songs FIRST (2026-09-23). A brief chunk needs the box free of a pipeline, and a
        # documentary tick starts one that runs ~27 min — so with a full documentary target
        # the song bank never saw an idle moment and stayed where it was. Briefs are local
        # and cost seconds; taking them in the gap between brain runs is what fills both banks.
        try:
            _songs_tick(state_load())
        except Exception as exc:  # noqa: BLE001
            st = state_load()
            st['songs']['note'] = f'tick error: {exc!r}'[:200]
            state_save(st)
        st = state_load()
        try:
            _documentary_tick(st)
        except Exception as exc:  # noqa: BLE001
            st['documentary']['note'] = f'tick error: {exc!r}'[:200]
            state_save(st)


def _watcher() -> None:
    while True:
        time.sleep(_TICK_S)
        try:
            tick()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('preempt tick failed, retrying in %s s: %s', _TICK_S, _exc)


def play() -> dict:
    with _LOCK:
        st = state_load()
        st['enabled'] = True
        st['paused'] = False
        st['started_at'] = st.get('started_at') or _ams_iso()
        state_save(st)
    _zero_audit_log(
        'preempt_enabled',
        {'documentary_target': _aq_get('documentary_target', 100), 'songs_target': _aq_get('songs_target', 100)},
    )
    threading.Thread(target=tick, daemon=True, name='preempt-kick').start()
    return state_load()


def pause(paused: bool = True) -> dict:
    with _LOCK:
        st = state_load()
        st['paused'] = bool(paused)
        state_save(st)
    _zero_audit_log('preempt_paused' if paused else 'preempt_resumed', {})
    return state_load()


def abort() -> dict:
    with _LOCK:
        st = state_load()
        runs = list(_running_entries(st))
        stopped = []
        for cur in runs:
            if not (cur and cur.get('pipeline_id')):
                continue
            job = _workflow_jobs.get(cur['pipeline_id'])
            try:
                if job and job.get('stop_event') is not None:
                    job['stop_event'].set()
                stopped.append(cur['pipeline_id'])
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning(
                    'stop signal for %s failed, finishing the entry as aborted anyway: %s', cur['pipeline_id'], _exc
                )
            _pb.finish_entry(cur['entry_id'], False, error='aborted by operator', pipeline_id=cur.get('pipeline_id'))
            st['documentary']['last'] = {
                'entry_id': cur['entry_id'],
                'topic': cur.get('topic'),
                'outcome': 'aborted',
                'ended_at': _ams_iso(),
            }
        if stopped:
            try:
                from zyg_workflows import pipeline_control as _pc

                _pc.request_halt('Aborted from the Approval Queue')
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('halt request failed, the running pipeline may continue: %s', _exc)
        st['documentary']['running'] = []
        st['documentary']['current'] = None
        st['enabled'] = False
        st['paused'] = False
        state_save(st)
    _zero_audit_log('preempt_aborted', {'stopped_pipeline': stopped})
    return state_load()


def view() -> dict:
    """What the Approval Queue card shows: state, targets, quota, entries."""
    st = state_load()
    d = st.get('documentary') or {}
    c = _pb.counts()
    sc = _pb.songs_counts()
    dt = int(_aq_get('documentary_target', 100))
    stt = int(_aq_get('songs_target', 100))
    runs = []
    for r in d.get('running') or ([d['current']] if d.get('current') else []):
        job = _workflow_jobs.get((r or {}).get('pipeline_id') or '') or {}
        runs.append(dict(r or {}, stage=job.get('current_stage') or 'starting'))
    cur = runs[0] if runs else None
    q = _pb.quota_snapshot()
    holding, until, why = _pb.limit_hold()
    concurrency = max(1, int(_aq_get('concurrency', _DEFAULT_CONCURRENCY)))
    gate = gate_reason(len(runs)) if (st.get('enabled') and not st.get('paused') and len(runs) < concurrency) else ''
    return {
        'state': {k: st.get(k) for k in ('enabled', 'paused', 'started_at')},
        'quota': dict(q, hold=holding, hold_until=until, hold_reason=why),
        'gate': gate,
        'targets': [
            {
                'id': 'documentary',
                'label': 'Documentary episodes',
                'target': dt,
                'ready': c['ready'],
                'building': c['building'],
                'claimed': c['claimed'],
                'consumed': c['consumed'],
                'failed': c['failed'],
                'built': c['built'],
                'pct': round(100.0 * min(c['built'], dt) / dt, 1) if dt else 0.0,
                'current': cur,
                'running': runs,
                'concurrency': concurrency,
                'note': d.get('note') or '',
                'last': d.get('last'),
            },
            {
                'id': 'songs',
                'label': "Children's songs",
                'target': stt,
                'ready': sc['ready'],
                'building': 0,
                'claimed': sc['claimed'],
                'consumed': sc['consumed'],
                'failed': sc['failed'],
                'built': sc['built'],
                'pct': round(100.0 * min(sc['built'], stt) / stt, 1) if stt else 0.0,
                'current': None,
                'note': (st.get('songs') or {}).get('note') or '',
                'info': 'The song workflow makes no Claude calls: lyrics, storyboard and the frame judge '
                'run on local Ollama. This bank only pre-picks song briefs so the queue is full.',
            },
        ],
        'entries': _pb.list_entries(),
        'songs': _pb.songs_load(),
    }


# ── HTTP ─────────────────────────────────────────────────────────────────────


@bp.route('/api/preempt/state')
def api_preempt_state():
    return jsonify(view())


@bp.route('/api/preempt/action', methods=['POST'])
def api_preempt_action():
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '')
    if action == 'play':
        play()
    elif action == 'pause':
        pause(True)
    elif action == 'resume':
        pause(False)
    elif action == 'abort':
        abort()
    else:
        return jsonify({'ok': False, 'error': f'unknown action {action!r}'}), 400
    return jsonify({'ok': True, 'state': view()['state']})


@bp.route('/api/preempt/entry/<entry_id>/verify', methods=['POST'])
def api_preempt_verify(entry_id):
    """Dry-run replay of a banked entry: the scholarly pipeline in replay mode, stopped
    where a record run stops (after the prompt batch, before any image). Proves the
    entry replays; the ledger is not consumed (the used-set is per run)."""
    e = _pb.load_entry(entry_id)
    if not e or e.get('status') not in ('ready', 'claimed', 'consumed'):
        return jsonify({'ok': False, 'error': 'entry not found or not built'}), 404
    if _busy_pipeline():
        return jsonify({'ok': False, 'error': 'a pipeline is running'}), 409
    try:
        info = _start_scholarly_pipeline_internal(
            directive=e['topic'],
            topic='scholarly',
            narration_enabled=True,
            visual_style='cinematic',
            model_family='flux',
            pipeline_options={'preempt': {'mode': 'replay', 'entry': e['id'], 'dry_run': True}},
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}), 500
    _zero_audit_log(
        'preempt_verify_started', {'entry': e['id'], 'topic': e['topic'], 'pipeline_id': info.get('job_id')}
    )
    return jsonify({'ok': True, 'pipeline_id': info.get('job_id')})


@bp.route('/api/preempt/job/<pid>')
def api_preempt_job(pid):
    j = _workflow_jobs.get(pid) or {}
    return jsonify(
        {
            'status': j.get('status'),
            'stage': j.get('current_stage'),
            'result': j.get('result'),
            'error': j.get('error'),
            'preempt_stats': j.get('preempt_stats'),
            'preempt': j.get('preempt'),
        }
    )


threading.Thread(target=_watcher, daemon=True, name='preempt-watcher').start()
