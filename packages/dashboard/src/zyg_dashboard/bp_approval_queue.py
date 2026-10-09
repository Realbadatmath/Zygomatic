# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_approval_queue.py — the rebuilt Approval Queue board: one kanban of WORKFLOW cards. 2026-09-20.

GET  /api/approval_queue/board                       — every card in one payload (contract in the JS header)
GET  /api/approval_queue/calendar?view=&anchor=&days= — the calendar / production overview panel
                                                       (production_calendar.py, hot-reloaded)
POST /api/approval_queue/<wf>/action   {action}      — play | pause | abort
POST /api/approval_queue/<wf>/settings {key: value}  — the card's adjustable settings (approval_queue_settings.py)
POST /api/approval_queue/preempt/item/<id>/action    — delete a banked entry / song brief

Cards: documentary (bp_zero auto-mode), storyteller (bp_storyteller_daily), melody
(bp_melody_daily) and preempt (bp_preempt — the Pre-Emptive generation bank). The three
production batchers keep their own state files and watcher threads; this module only reads
them and forwards the controls, so the old /api/zero/auto_mode etc. keep working too.
"""

from __future__ import annotations

import json
import os

from flask import Blueprint, jsonify, request

from zyg_dashboard import approval_queue_settings as _aqs
from zyg_dashboard import preempt_bank as _pb
from zyg_dashboard.gui.runtime_state import _workflow_jobs
from zyg_dashboard.gui.timeutil import _ams_iso
from zyg_dashboard.gui.zero_store import ZERO_AUDIT_PATH
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('approval_queue', __name__)

ACCENT = {
    'documentary': '#2e8b57',
    'storyteller': '#b5761f',
    'melody': '#1f8ea8',
    'jackmona': '#c1557a',
    'preempt': '#6a4fbf',
}
COLUMN_LABELS = {
    'scheduled': 'Scheduled',
    'in_production': 'In Production',
    'done': 'Done',
    'failed': 'Failed',
    'blocked': 'Blocked',
    'building': 'Building',
    'ready': 'Ready',
    'claimed': 'Claimed',
    'consumed': 'Used',
    'aborted': 'Aborted',
}
HISTORY_PREFIX = {
    'documentary': ('auto_mode', 'kanban_batch', 'zero_kanban'),
    'storyteller': ('storyteller_daily',),
    'melody': ('melody_daily',),
    'jackmona': ('jackmona_daily',),
    'preempt': ('preempt',),
}


def _fmt(ts) -> str:
    return str(ts or '').replace('T', ' ')[:16]


def _count(rows: list) -> dict:
    c = {'scheduled': 0, 'in_production': 0, 'done': 0, 'failed': 0, 'blocked': 0}
    for e in rows or []:
        k = e.get('status') or 'scheduled'
        c[k] = c.get(k, 0) + 1
    return c


def _history(wf: str, limit: int = 8) -> list:
    """The last audit events for this workflow, newest first (tail of zero_audit.jsonl)."""
    out = []
    prefixes = HISTORY_PREFIX.get(wf, ())
    try:
        with open(ZERO_AUDIT_PATH, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 256 * 1024))
            chunk = fh.read().decode('utf-8', 'replace')
        for line in reversed(chunk.splitlines()):
            try:
                r = json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('skipping unparseable zero audit line: %s', _exc)
                continue
            act = str(r.get('action') or '')
            if not act.startswith(prefixes):
                continue
            p = r.get('payload') or {}
            detail = ''
            if isinstance(p, dict):
                bits = []
                for k in (
                    'topic',
                    'theme',
                    'template_id',
                    'entry',
                    'error',
                    'outcome',
                    'added',
                    'stopped_pipeline',
                    'topics',
                    'count',
                ):
                    if p.get(k) not in (None, '', [], {}):
                        v = p[k]
                        if isinstance(v, list):
                            v = f'{len(v)} items'
                        bits.append(f'{k}={str(v)[:60]}')
                detail = ' · '.join(bits)
            out.append({'ts': _fmt(r.get('timestamp')), 'event': act, 'detail': detail})
            if len(out) >= limit:
                break
    except OSError as _exc:
        _zyg_log.warning('zero audit read failed, the history panel is incomplete: %s', _exc)
    return out


def _state_of(enabled: bool, paused: bool, busy: bool, attention: bool) -> str:
    if not enabled:
        return 'off'
    if paused:
        return 'paused'
    if attention:
        return 'attention'
    return 'running' if busy else 'waiting'


def _actions(enabled: bool, paused: bool) -> list:
    if not enabled:
        return ['play']
    return ['play', 'abort'] if paused else ['pause', 'abort']


def _min_ram_gb(wf: str) -> float:
    """The free-RAM gate each batcher applies. It is NOT a board setting (see
    approval_queue_settings.py): the board states the rule, the environment sets it."""
    base = os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24')
    env = {
        'storyteller': 'ZYG_STORYTELLER_MIN_FREE_RAM_GB',
        'melody': 'ZYG_MELODY_MIN_FREE_RAM_GB',
        'jackmona': 'ZYG_JACKMONA_MIN_FREE_RAM_GB',
    }.get(wf)
    try:
        return float(os.environ.get(env, base) if env else base)
    except (TypeError, ValueError):
        return 24.0


def _rules(wf: str) -> list:
    """The start conditions this workflow obeys — shown read-only on the card, so nobody has to
    guess why nothing started. These are the batchers' own gates, not adjustable here."""
    out = [
        f'At least {_min_ram_gb(wf):g} GB free RAM (MemAvailable) before an item starts — the '
        'same gate every batcher on this box uses.',
        'One item at a time per workflow; an unfinished batch carries over rather than being replaced.',
        'Pause stops new starts and lets the running item finish; abort stops the run itself.',
    ]
    if wf == 'documentary':
        out.append('A new batch is armed only after the previous one has fully settled.')
    if wf == 'jackmona':
        out.append(
            'Each episode is recorded in the series ledger the moment it is CHOSEN, not when '
            'it finishes — a crash mid-render costs an episode, never a repeat.'
        )
        out.append(
            'A moment already sung is never offered again; past the hand-written pool the '
            'local model proposes fresh ones, and the pool rotates rather than restarting.'
        )
        out.append(
            "Jack's episodes are only about Jack and Mona's only about Mona: neither "
            "child's prompt, pool or look mentions the other."
        )
    if wf == 'preempt':
        out.append(
            'No brain run is started at or above the quota ceiling, nor during a limit hold; '
            'it resumes by itself after the reset.'
        )
    else:
        out.append(
            "Production items make no subscription calls of their own beyond the pipeline's "
            'own budget; the Pre-Emptive bank is where Claude quota is spent.'
        )
    return out


def _job_stage(pid: str) -> str:
    j = _workflow_jobs.get(pid or '') or {}
    return str(j.get('current_stage') or '')


# ── documentary ──────────────────────────────────────────────────────────────


def _documentary() -> dict:
    from zyg_dashboard import bp_zero as _bz

    auto = _bz._zero_auto_mode_load()
    batch = _bz._zero_kanban_load() or {}
    rows = batch.get('topics') or []
    c = _count(rows)
    enabled, paused = bool(auto.get('enabled')), bool(auto.get('paused'))
    busy = c['in_production'] > 0
    fin = bool(rows) and (c['done'] + c['failed']) == len(rows)
    last_failed = (
        bool(rows)
        and rows[-1].get('status') == 'failed'
        and not any(e.get('status') in ('scheduled', 'in_production') for e in rows)
    )
    items = []
    for e in rows:
        lines = []
        if e.get('started_at'):
            lines.append('Started ' + _fmt(e['started_at']))
        if e.get('ended_at'):
            lines.append('Ended ' + _fmt(e['ended_at']))
        if e.get('status') == 'in_production':
            st = _job_stage(e.get('pipeline_id'))
            if st:
                lines.append(st)
        flags = []
        if e.get('bank_id'):
            flags.append('bank')
        if (e.get('error') or '').startswith('aborted'):
            flags.append('aborted')
        items.append(
            {
                'id': str(e.get('id')),
                'status': e.get('status') or 'scheduled',
                'title': e.get('topic'),
                'no': f'#{int(e.get("id", 0)) + 1}',
                'lines': lines,
                'pipeline_id': e.get('pipeline_id'),
                'error': e.get('error'),
                'started_at': e.get('started_at'),
                'ended_at': e.get('ended_at'),
                'flags': flags,
            }
        )
    s = _aqs.all_values('documentary')
    next_run = auto.get('next_run_utc')
    if enabled:
        if paused:
            note = 'paused — the running episode finishes, nothing new starts'
        elif next_run:
            note = f'next batch {_fmt(next_run)} AMS'
        elif c['scheduled'] or c['in_production']:
            note = 'batch in progress'
        else:
            note = 'next batch is armed when this one completes'
    else:
        note = ('last batch finished ' + _fmt(_bz._zero_kanban_completed_at(batch))) if (rows and fin) else 'idle'
    bank_ready = _pb.counts()['ready']
    if s.get('use_bank_first'):
        note += f' · {bank_ready} pre-built in the bank'
    batch_note = ''
    if batch:
        batch_note = (
            ('Last batch ' if fin else 'Batch ')
            + str(batch.get('batch_id') or '—')
            + ' · '
            + ('auto' if batch.get('auto_triggered') else 'manual')
            + ' · created '
            + _fmt(batch.get('created_at'))
            + (f' · {c["done"] + c["failed"]} / {len(rows)} complete' if rows else '')
        )
    return {
        'id': 'documentary',
        'name': 'Documentary',
        'accent': ACCENT['documentary'],
        'kind': 'scholarly',
        'desc': f'{s["topics_per_batch"]} documentary topics per batch, one at a time; the next batch '
        f'{s["cadence_days"]} day(s) later at {int(s["batch_hour"]):02d}:00 AMS.',
        'enabled': enabled,
        'paused': paused,
        'busy': busy,
        'state': _state_of(enabled, paused, busy, last_failed and enabled),
        'state_note': note,
        'counts': c,
        'columns': ['scheduled', 'in_production', 'done', 'failed'],
        'column_labels': COLUMN_LABELS,
        'items': items,
        'batch_note': batch_note,
        'actions': _actions(enabled, paused),
        'settings': _aqs.fields('documentary'),
        'history': _history('documentary'),
        'rules': _rules('documentary'),
    }


# ── storyteller ──────────────────────────────────────────────────────────────


def _storyteller() -> dict:
    from zyg_dashboard import bp_storyteller_daily as _bs

    daily = _bs._std_daily_load()
    batch = _bs._std_batch_load() or {}
    rows = batch.get('episodes') or []
    c = _count(rows)
    enabled, paused = bool(daily.get('enabled')), bool(daily.get('paused'))
    busy = c['in_production'] > 0
    items = []
    for i, e in enumerate(rows):
        lines = []
        if e.get('character'):
            lines.append(e['character'])
        if e.get('blocked_reason'):
            lines.append(e['blocked_reason'])
        if e.get('started_at'):
            lines.append('Started ' + _fmt(e['started_at']))
        if e.get('status') == 'in_production':
            st = _job_stage(e.get('pipeline_id'))
            if st:
                lines.append(st)
        items.append(
            {
                'id': str(i),
                'status': e.get('status') or 'scheduled',
                'title': e.get('series_title') or e.get('template_id'),
                'no': f'Ep {e.get("episode_no")}' if e.get('episode_no') is not None else '',
                'lines': lines,
                'pipeline_id': e.get('pipeline_id'),
                'error': e.get('error'),
                'started_at': e.get('started_at'),
                'ended_at': e.get('ended_at'),
                'flags': ['aborted'] if (e.get('error') or '').startswith('aborted') else [],
            }
        )
    s = _aqs.all_values('storyteller')
    if enabled:
        note = 'paused' if paused else (f'{len(rows)} episodes today' if rows else "building today's batch…")
    else:
        note = 'idle'
    return {
        'id': 'storyteller',
        'name': 'Storyteller',
        'accent': ACCENT['storyteller'],
        'kind': 'storyteller',
        'desc': f'One episode per enabled series template per day (cap {s["max_per_day"]}), launched one at a time.',
        'enabled': enabled,
        'paused': paused,
        'busy': busy,
        'state': _state_of(enabled, paused, busy, False),
        'state_note': note,
        'counts': c,
        'columns': ['scheduled', 'in_production', 'done', 'failed', 'blocked'],
        'column_labels': COLUMN_LABELS,
        'items': items,
        'batch_note': ('Batch ' + str(batch.get('batch_date') or '')) if batch else '',
        'actions': _actions(enabled, paused),
        'settings': _aqs.fields('storyteller'),
        'rules': _rules('storyteller'),
        'history': _history('storyteller'),
    }


# ── melody ───────────────────────────────────────────────────────────────────


def _melody() -> dict:
    from zyg_dashboard import bp_melody_daily as _bm

    daily = _bm._mel_daily_load()
    batch = _bm._mel_batch_load() or {}
    rows = batch.get('songs') or []
    c = _count(rows)
    enabled, paused = bool(daily.get('enabled')), bool(daily.get('paused'))
    busy = c['in_production'] > 0
    items = []
    for e in rows:
        lines = []
        if e.get('title'):
            lines.append('“' + e['title'] + '”')
        if e.get('mood'):
            lines.append(e['mood'] + (' · ' + e['age_band'] if e.get('age_band') else ''))
        if e.get('started_at'):
            lines.append('Started ' + _fmt(e['started_at']))
        if e.get('status') == 'in_production':
            st = _job_stage(e.get('pipeline_id'))
            if st:
                lines.append(st)
        flags = [e['theme_source']] if e.get('theme_source') else []
        if (e.get('error') or '').startswith('aborted'):
            flags.append('aborted')
        items.append(
            {
                'id': str(e.get('id')),
                'status': e.get('status') or 'scheduled',
                'title': e.get('theme'),
                'no': '',
                'lines': lines,
                'pipeline_id': e.get('pipeline_id'),
                'error': e.get('error'),
                'started_at': e.get('started_at'),
                'ended_at': e.get('ended_at'),
                'flags': flags,
            }
        )
    s = _aqs.all_values('melody')
    try:
        nxt = _bm._mel_next_run_label()
    except Exception:  # noqa: BLE001
        nxt = ''
    if enabled:
        note = (
            'paused'
            if paused
            else (
                (f'{len(rows)} songs today' if rows else "building today's batch…")
                + (f' · next {nxt} AMS' if nxt else '')
            )
        )
    else:
        note = 'idle'
    bank = _pb.songs_counts()['ready']
    if s.get('use_bank_first'):
        note += f' · {bank} briefs in the bank'
    return {
        'id': 'melody',
        'name': 'Melody',
        'accent': ACCENT['melody'],
        'kind': 'kidsmusic',
        'desc': f"{s['per_day']} children's songs a day from {int(s['hour']):02d}:00 AMS, composed one at a time. "
        'No Claude calls: everything runs on local models.',
        'enabled': enabled,
        'paused': paused,
        'busy': busy,
        'state': _state_of(enabled, paused, busy, False),
        'state_note': note,
        'counts': c,
        'columns': ['scheduled', 'in_production', 'done', 'failed'],
        'column_labels': COLUMN_LABELS,
        'items': items,
        'batch_note': ('Batch ' + str(batch.get('batch_date') or '')) if batch else '',
        'actions': _actions(enabled, paused),
        'settings': _aqs.fields('melody'),
        'rules': _rules('melody'),
        'history': _history('melody'),
    }


# ── Life of Jack / Life of Mona ──────────────────────────────────────────────


def _jackmona() -> dict:
    """Two series, one episode each per day. Unlike the melody card there is no
    bank and no theme source to report: what an episode is about comes from the
    series' own ledger, so the card shows the episode NUMBER and how much of each
    child's hand-written pool is still unused — the two numbers that say whether
    the series can keep going on its own."""
    from zyg_dashboard import bp_jackmona_daily as _bj
    from zyg_workflows import kids_series_people as _ksp

    daily = _bj._daily_load()
    batch = _bj._batch_load() or {}
    rows = batch.get('episodes') or []
    c = _count(rows)
    enabled, paused = bool(daily.get('enabled')), bool(daily.get('paused'))
    busy = c['in_production'] > 0
    items = []
    for e in rows:
        lines = []
        if e.get('title'):
            lines.append('“' + e['title'] + '”')
        lines.append(
            f'{e.get("name", "?")} · episode {e.get("episode", "?")}'
            + (f' · {int(e["seconds"])}s' if e.get('seconds') else '')
        )
        if e.get('started_at'):
            lines.append('Started ' + _fmt(e['started_at']))
        if e.get('status') == 'in_production':
            st = _job_stage(e.get('pipeline_id'))
            if st:
                lines.append(st)
        flags = [e['series']] if e.get('series') else []
        if (e.get('error') or '').startswith('aborted'):
            flags.append('aborted')
        items.append(
            {
                'id': str(e.get('id')),
                'status': e.get('status') or 'scheduled',
                'title': e.get('moment'),
                'no': str(e.get('episode') or ''),
                'lines': lines,
                'pipeline_id': e.get('pipeline_id'),
                'error': e.get('error'),
                'started_at': e.get('started_at'),
                'ended_at': e.get('ended_at'),
                'flags': flags,
            }
        )
    sv = _aqs.all_values('jackmona')
    try:
        nxt = _bj._next_run_label()
    except Exception:  # noqa: BLE001
        nxt = ''
    series = _ksp.series_rows()
    if enabled:
        note = (
            'paused'
            if paused
            else (
                (f'{len(rows)} episodes today' if rows else "building today's pair…")
                + (f' · next {nxt} AMS' if nxt else '')
            )
        )
    else:
        note = 'idle'
    note += ' · ' + ', '.join(f'{r["name"]} at #{r["next_episode"]}' for r in series)
    from zyg_workflows import kids_music_theory as _T

    lo, hi = _T.SONG_SECONDS
    return {
        'id': 'jackmona',
        'name': 'Jack & Mona',
        'accent': ACCENT['jackmona'],
        'kind': 'kidsmusic',
        'desc': (
            f"Two children's series, one episode each a day from "
            f'{int(sv["hour"]):02d}:00 AMS, one at a time: Life of Jack '
            f'(male voice) and Life of Mona (female voice), '
            f'{int(lo)}–{int(hi)}s each. Every episode is one moment of that '
            f"child's own day, never the other's, and the ledger stops a "
            f'moment being sung twice. No Claude calls — local models only.'
        ),
        'enabled': enabled,
        'paused': paused,
        'busy': busy,
        'state': _state_of(enabled, paused, busy, False),
        'state_note': note,
        'counts': c,
        'columns': ['scheduled', 'in_production', 'done', 'failed'],
        'column_labels': COLUMN_LABELS,
        'items': items,
        'batch_note': ('Pair ' + str(batch.get('batch_date') or '')) if batch else '',
        'actions': _actions(enabled, paused),
        'settings': _aqs.fields('jackmona'),
        'rules': _rules('jackmona'),
        'history': _history('jackmona'),
        'targets': [
            {'label': f'{r["label"]} — pool unused', 'built': r['pool_left'], 'target': r['pool_size']} for r in series
        ],
    }


# ── pre-emptive generation ───────────────────────────────────────────────────


def _preempt() -> dict:
    from zyg_dashboard import bp_preempt as _bpp

    v = _bpp.view()
    st = v['state']
    enabled, paused = bool(st.get('enabled')), bool(st.get('paused'))
    doc, songs = v['targets']
    busy = bool(doc.get('current'))
    items = []
    for i, e in enumerate(v['entries']):
        lines = [f'{e.get("turns") or 0} Claude turns recorded'] if e.get('status') != 'building' else []
        if e.get('built_at'):
            lines.append('built ' + _fmt(e['built_at']))
        if e.get('status') == 'building' and doc.get('current') and doc['current'].get('entry_id') == e['id']:
            lines.append(doc['current'].get('stage') or 'starting')
        if e.get('claimed_by'):
            lines.append('run ' + str(e['claimed_by'])[:8])
        if e.get('consumed_at'):
            lines.append('used ' + _fmt(e['consumed_at']))
        items.append(
            {
                'id': e['id'],
                'status': e.get('status') or 'failed',
                'title': e.get('topic'),
                'no': f'D-{i + 1}',
                'lines': lines,
                'pipeline_id': e.get('claimed_by') or e.get('brain_pipeline_id'),
                'error': e.get('error'),
                'started_at': e.get('created_at'),
                'ended_at': e.get('built_at'),
                'flags': ['documentary'] + ([e['pool']] if e.get('pool') else []),
            }
        )
    for i, r in enumerate(v['songs']):
        items.append(
            {
                'id': r['id'],
                'status': r.get('status') or 'ready',
                'title': r.get('theme'),
                'no': f'S-{i + 1}',
                'lines': [((r.get('mood') or '') + (' · ' + r['age_band'] if r.get('age_band') else '')).strip(' ·')],
                'pipeline_id': r.get('pipeline_id'),
                'error': None,
                'started_at': r.get('created_at'),
                'ended_at': None,
                'flags': ['song', r.get('source') or 'llm'],
            }
        )
    c = {
        'building': doc['building'],
        'ready': doc['ready'] + songs['ready'],
        'claimed': doc['claimed'] + songs['claimed'],
        'consumed': doc['consumed'] + songs['consumed'],
        'failed': doc['failed'] + songs['failed'],
        'scheduled': 0,
        'in_production': doc['building'],
        'done': doc['consumed'] + songs['consumed'],
        'blocked': 0,
    }
    q = v['quota']
    # Attention = something the operator must look at: a quota hold, no login/CLI, a failed run's
    # cooldown, or the last brain run failed. Waiting for the box (another pipeline, RAM) is not.
    gate = str(v.get('gate') or '')
    serious = any(w in gate.lower() for w in ('quota', 'limit', 'login', 'cli', 'cooldown', 'unavailable'))
    last_failed = bool((doc.get('last') or {}).get('outcome') in ('failed', 'aborted')) and not busy
    attention = bool(q.get('hold')) or (enabled and not paused and not busy and (serious or last_failed))
    if enabled:
        if paused:
            note = 'paused — the current brain run finishes, nothing new starts'
        elif busy:
            note = f'building "{doc["current"].get("topic")}" — {doc["current"].get("stage")}'
        elif v.get('gate'):
            note = 'waiting: ' + v['gate']
        else:
            note = doc.get('note') or 'ready to build'
    else:
        note = 'off'
    doc_target = doc['target']
    doc['note'] = f'{doc["ready"]} ready · {doc["building"]} building · {doc["consumed"]} used · {doc["failed"]} failed'
    songs['note'] = f'{songs["ready"]} ready · {songs["consumed"]} used'
    return {
        'id': 'preempt',
        'name': 'Pre-Emptive generation',
        'accent': ACCENT['preempt'],
        'kind': 'preempt',
        'desc': f'Makes every text Claude call for {doc_target} documentary episodes now (brain runs, no rendering) '
        f'and pre-picks {songs["target"]} song briefs, so production can run when the subscription is out. '
        'Image judges are not pre-made; they fall to local models.',
        'enabled': enabled,
        'paused': paused,
        'busy': busy,
        'state': _state_of(enabled, paused, busy, attention),
        'state_note': note,
        'counts': c,
        'columns': ['building', 'ready', 'claimed', 'consumed', 'failed'],
        'column_labels': COLUMN_LABELS,
        'items': items,
        'batch_note': f'Bank: {doc["built"]} / {doc_target} documentary brains · {songs["built"]} / {songs["target"]} song briefs',
        'actions': _actions(enabled, paused),
        'settings': _aqs.fields('preempt'),
        'history': _history('preempt'),
        'rules': _rules('preempt'),
        'targets': [doc, songs],
        'item_actions': ['delete'],
        'quota': q,
    }


def _workflow(wf: str) -> dict:
    return {
        'documentary': _documentary,
        'storyteller': _storyteller,
        'melody': _melody,
        'jackmona': _jackmona,
        'preempt': _preempt,
    }[wf]()


def _quota() -> dict:
    q = _pb.quota_snapshot()
    holding, until, why = _pb.limit_hold()
    return {
        'five_hour_pct': q.get('five_hour_pct'),
        'seven_day_pct': q.get('seven_day_pct'),
        'five_hour_resets_at': q.get('five_hour_resets_at'),
        'seven_day_resets_at': q.get('seven_day_resets_at'),
        'sampled_at': q.get('sampled_at'),
        'error': q.get('error') or '',
        'hold': holding,
        'hold_until': until,
        'hold_reason': why,
    }


# ── routes ───────────────────────────────────────────────────────────────────


@bp.route('/api/approval_queue/board')
def api_board():
    wfs = []
    for wf in ('documentary', 'storyteller', 'melody', 'jackmona', 'preempt'):
        try:
            wfs.append(_workflow(wf))
        except Exception as exc:  # noqa: BLE001 — one broken card must not blank the board
            wfs.append(
                {
                    'id': wf,
                    'name': wf.title(),
                    'accent': ACCENT[wf],
                    'kind': wf,
                    'enabled': False,
                    'paused': False,
                    'busy': False,
                    'state': 'attention',
                    'state_note': f'card error: {type(exc).__name__}: {exc}'[:200],
                    'counts': _count([]),
                    'columns': [],
                    'column_labels': COLUMN_LABELS,
                    'items': [],
                    'batch_note': '',
                    'actions': [],
                    'settings': [],
                    'history': [],
                }
            )
    return jsonify({'ts': _ams_iso(), 'quota': _quota(), 'workflows': wfs})


_PC_MOD = {'mod': None, 'mtime': 0.0}


def _pc():
    """production_calendar, re-imported when its file changes (the metrics-hub hot-reload rule,
    so the panel can be corrected without restarting the GUI)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _PC_MOD['mod']
    if mod is None:
        from zyg_dashboard import production_calendar as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _PC_MOD['mod'] is not None and mtime != _PC_MOD['mtime']:
            mod = maybe_reload(mod)
        _PC_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001 — keep the loaded module rather than blanking the panel
        _zyg_log.info(f'[APPROVAL-QUEUE] production_calendar reload failed: {exc}')
    return mod


@bp.route('/api/approval_queue/calendar')
def api_calendar():
    """The panel next to the cards: 7/14/28 days of plan (calendar) or numbers (production),
    anchored anywhere from a year back to 28 days ahead."""
    args = request.args
    try:
        days = int(args.get('days') or 7)
    except ValueError:
        days = 7
    try:
        data = _pc().payload(
            view=args.get('view') or 'calendar',
            anchor=args.get('anchor') or None,
            days=days,
            fresh=str(args.get('fresh') or '') in ('1', 'true'),
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:300]}), 500
    return jsonify(data)


@bp.route('/api/approval_queue/<wf>/action', methods=['POST'])
def api_action(wf):
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '')
    if wf not in ('documentary', 'storyteller', 'melody', 'jackmona', 'preempt'):
        return jsonify({'ok': False, 'error': f'unknown workflow {wf!r}'}), 404
    if action not in ('play', 'pause', 'abort'):
        return jsonify({'ok': False, 'error': f'unknown action {action!r}'}), 400
    try:
        if wf == 'documentary':
            from zyg_dashboard import bp_zero as _bz

            {
                'play': lambda: (
                    _bz._zero_auto_mode_set(True)
                    if not _bz._zero_auto_mode_load().get('enabled')
                    else _bz._zero_pause(False)
                ),
                'pause': lambda: _bz._zero_pause(True),
                'abort': _bz._zero_abort,
            }[action]()
        elif wf == 'storyteller':
            from zyg_dashboard import bp_storyteller_daily as _bs

            {
                'play': lambda: (
                    _bs._std_daily_set(True) if not _bs._std_daily_load().get('enabled') else _bs._std_pause(False)
                ),
                'pause': lambda: _bs._std_pause(True),
                'abort': _bs._std_abort,
            }[action]()
        elif wf == 'melody':
            from zyg_dashboard import bp_melody_daily as _bm

            {
                'play': lambda: (
                    _bm._mel_daily_set(True) if not _bm._mel_daily_load().get('enabled') else _bm._mel_pause(False)
                ),
                'pause': lambda: _bm._mel_pause(True),
                'abort': _bm._mel_abort,
            }[action]()
        elif wf == 'jackmona':
            from zyg_dashboard import bp_jackmona_daily as _bj

            {
                'play': lambda: (
                    _bj._set_enabled(True) if not _bj._daily_load().get('enabled') else _bj._set_paused(False)
                ),
                'pause': lambda: _bj._set_paused(True),
                'abort': _bj._abort,
            }[action]()
        else:
            from zyg_dashboard import bp_preempt as _bpp

            {'play': _bpp.play, 'pause': lambda: _bpp.pause(True), 'abort': _bpp.abort}[action]()
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:300]}), 500
    return jsonify({'ok': True, 'workflow': _workflow(wf)})


@bp.route('/api/approval_queue/<wf>/settings', methods=['POST'])
def api_settings(wf):
    if wf not in _aqs.SCHEMA:
        return jsonify({'ok': False, 'error': f'unknown workflow {wf!r}'}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({'ok': False, 'error': 'no settings given'}), 400
    try:
        _aqs.update(wf, data)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    try:
        from zyg_dashboard.appcore import _zero_audit_log

        _zero_audit_log(
            f'{wf}_settings_changed' if wf != 'documentary' else 'auto_mode_settings_changed',
            {k: data[k] for k in list(data)[:12]},
        )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('settings-change audit entry could not be written: %s', _exc)
    return jsonify({'ok': True, 'settings': _aqs.fields(wf), 'workflow': _workflow(wf)})


@bp.route('/api/approval_queue/preempt/item/<item_id>/action', methods=['POST'])
def api_preempt_item(item_id):
    data = request.get_json(silent=True) or {}
    if str(data.get('action') or '') != 'delete':
        return jsonify({'ok': False, 'error': 'only delete is supported'}), 400
    if item_id.startswith('s-'):
        ok = _pb.songs_delete(item_id)
    else:
        e = _pb.load_entry(item_id)
        if e and e.get('status') not in ('ready', 'failed'):
            return jsonify(
                {'ok': False, 'error': f'entry is {e.get("status")}; only ready or failed entries can be deleted'}
            ), 409
        ok = _pb.delete_entry(item_id)
    if not ok:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return jsonify({'ok': True})
