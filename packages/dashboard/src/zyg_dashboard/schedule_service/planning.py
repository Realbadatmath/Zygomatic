# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import (
    _AMS,
    _MANUAL_FILES,
    _RUNTIME,
    _load_json,
    _lock,
    _parse_iso,
    ams_now,
    ams_today,
    bar_id_for,
    date,
    datetime,
    devices,
    json,
    model_registry,
    os,
    re,
    timedelta,
    uuid,
)
from .durations import DEFAULT_DURATIONS, _PIPELINE_FALLBACK_MODEL, _pipeline_total, get_duration_table
from .live import _entry, build_live_entries
import logging as _zyg_logging_split

_zyg_log = _zyg_logging_split.getLogger('zyg_dashboard.schedule_service')

# ── upcoming / scheduled entries ─────────────────────────────────────────────


def build_upcoming_entries(window_days: int = 1, start_day: str | None = None) -> list[dict]:
    now = ams_now()
    day0 = _parse_day(start_day) or now.date()
    horizon = datetime.combine(day0 + timedelta(days=window_days), datetime.min.time(), _AMS)
    floor = datetime.combine(day0, datetime.min.time(), _AMS)
    table = get_duration_table()
    out: list[dict] = []

    # 1. Zero auto-mode: next documentary batch
    auto = _load_json(os.path.join(_RUNTIME, 'zero_auto_mode.json'), {})
    batch = _load_json(os.path.join(_RUNTIME, 'zero_kanban_batch.json'), {})
    doc_total = _pipeline_total('documentary', table)
    next_run = _parse_iso(auto.get('next_run_utc')) if auto.get('enabled') else None
    pending_topics = [
        t
        for t in (batch.get('topics') or [])
        if str(t.get('status', '')).lower() in ('scheduled', 'pending', 'queued', '')
    ]
    if next_run and next_run < horizon:
        # batch size: remaining topics in current batch, else default 6
        n = len(pending_topics) or 6
        cursor = next_run
        for i in range(n):
            end = cursor + timedelta(seconds=doc_total)
            topic = (pending_topics[i].get('topic') if i < len(pending_topics) else None) or f'auto batch topic {i + 1}'
            if end > floor and cursor < horizon:
                out.append(
                    _entry(
                        eid=f'auto_{cursor.strftime("%Y%m%d%H%M")}_{i}',
                        source='auto_mode',
                        kind='scheduled',
                        ptype='documentary',
                        stage='full pipeline',
                        label=f'Auto batch: {str(topic)[:70]}',
                        start=cursor,
                        end=end,
                        status='scheduled',
                    )
                )
            cursor = end
    else:
        # batch exists but auto-mode idle: queued topics run sequentially when resumed
        cursor = now
        for i, t in enumerate(pending_topics):
            end = cursor + timedelta(seconds=doc_total)
            if end > floor and cursor < horizon:
                out.append(
                    _entry(
                        eid=f'kanban_{batch.get("batch_id", "?")}_{t.get("id", i)}',
                        source='kanban',
                        kind='queued',
                        ptype='documentary',
                        stage='full pipeline',
                        label=f'Batch queue: {str(t.get("topic", ""))[:70]}',
                        start=cursor,
                        end=end,
                        status='queued',
                    )
                )
            cursor = end

    # 2. publish/upload slots
    sched = _load_json(os.path.join(_RUNTIME, 'zero_batch_schedule.json'), {})
    for i, slot in enumerate(sched.get('slots') or []):
        up = _parse_iso(slot.get('upload_at'))
        pub = _parse_iso(slot.get('publish_at'))
        if not up or not pub or pub < floor or up > horizon:
            continue
        if pub < now:
            continue
        out.append(
            _entry(
                eid=f'publish_{i}_{pub.strftime("%Y%m%d%H%M")}',
                source='publish_slot',
                kind='scheduled',
                ptype='publish',
                stage='upload+publish',
                label=f'Publish slot {pub.strftime("%d %b %H:%M")}'
                + (f' (claimed: {str(slot.get("claimed_by", ""))[:8]})' if slot.get('claimed_by') else ''),
                start=up,
                end=pub + timedelta(minutes=15),
                status='claimed' if slot.get('claimed_by') else 'open',
                reserved=False,
            )
        )

    # 3. awaiting-approval public requests (untimed — surfaced as a list, placed at 'now')
    for p in _load_json(os.path.join(_RUNTIME, 'zpub_pending.json'), []) or []:
        # zpub_pending.json is a decision LOG — approved/declined records stay
        # in the file; only pending/queued are actually awaiting an operator.
        if str(p.get('status') or 'pending').lower() not in ('pending', 'queued'):
            continue
        pt = str(p.get('pipeline') or (p.get('body_snapshot') or {}).get('pipeline_style') or 'documentary').lower()
        if pt in ('unknown', ''):
            pt = str((p.get('body_snapshot') or {}).get('pipeline_style') or 'documentary')
        total = _pipeline_total(pt if pt in DEFAULT_DURATIONS else 'documentary', table)
        out.append(
            _entry(
                eid=f'pending_{p.get("id", uuid.uuid4().hex[:8])}',
                source='pending_approval',
                kind='awaiting-approval',
                ptype=pt if pt in _PIPELINE_FALLBACK_MODEL else 'documentary',
                stage='awaiting approval',
                label=f'Approval: {str(p.get("prompt", p.get("label", "")))[:70]}',
                start=now,
                end=now + timedelta(seconds=total),
                status='awaiting-approval',
                reserved=False,
            )
        )
    return out


def _parse_day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


# ── manual entries (legacy schedule files) ───────────────────────────────────


def manual_entries_for(scope: str, days: list[str]) -> list[dict]:
    data = _load_json(_MANUAL_FILES[scope], {})
    reg = model_registry(scope, include_deprecated=True)
    out = []
    for day in days:
        for e in data.get(day) or []:
            if not isinstance(e, dict):
                continue
            mid = str(e.get('ai_model') or '')
            info = reg.get(mid) or {}
            slug = info.get('slug') or f'model-{mid}'
            agent = e.get('agent') or 'Manual'
            start_s = str(e.get('start_time') or '00:00')
            end_s = str(e.get('end_time') or start_s)
            try:
                start = datetime.strptime(f'{day} {start_s}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
                end = datetime.strptime(f'{day} {end_s}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
                if end <= start:
                    end += timedelta(days=1)
            except ValueError as _exc:
                _zyg_log.warning(
                    'entry %s has unparsable times %r/%r, left out of the schedule: %s',
                    e.get('id'),
                    start_s,
                    end_s,
                    _exc,
                )
                continue
            ent = _entry(
                eid=str(e.get('id') or uuid.uuid4()),
                source='manual',
                kind='manual',
                ptype='manual',
                stage='manual entry',
                label=f'{agent} / {info.get("name", mid)}',
                start=start,
                end=end,
                agent=agent,
                slug=slug,
                device=scope,
                status='manual',
                reserved=False,
                priority=str(e.get('priority') or 'High'),
            )
            ent['bar_id'] = e.get('bar_id') or ent['bar_id']
            ent['legacy'] = True
            out.append(ent)
    return out


# ── conflict blocking ────────────────────────────────────────────────────────


def reserved_windows(scope: str, day: str, registries: dict | None = None) -> list[dict]:
    """Pipeline-reserved intervals (active + scheduled) on *day* for *scope*."""
    wins = []
    for e in build_live_entries(registries) + build_upcoming_entries(7):
        if not e.get('reserved'):
            continue
        if (e['device'] if e['device'] in ('gpu', 'cpu') else 'gpu') != scope:
            continue
        if e['date'] != day and e['end_iso'][:10] != day:
            continue
        wins.append(e)
    return wins


def check_conflict(
    scope: str,
    day: str,
    start_time: str,
    end_time: str,
    registries: dict | None = None,
) -> list[dict]:
    """Manual entries are BLOCKED when they overlap a reserved pipeline window
    on the same device scope (user decision 2026-07-15)."""
    try:
        start = datetime.strptime(f'{day} {start_time}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
        end = datetime.strptime(f'{day} {end_time}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
        if end <= start:
            end += timedelta(days=1)
    except ValueError:
        return [{'error': 'invalid time'}]
    conflicts = []
    windows = reserved_windows(scope, day, registries)
    if end.date() > start.date():
        _next_day = (start.date() + timedelta(days=1)).strftime('%Y-%m-%d')
        _seen_w = {w['id'] for w in windows}
        windows += [w for w in reserved_windows(scope, _next_day, registries) if w['id'] not in _seen_w]
    for w in windows:
        ws = _parse_iso(w['start_iso'])
        we = _parse_iso(w['end_iso'])
        if ws and we and start < we and end > ws:
            conflicts.append(
                {
                    'label': w['label'],
                    'pipeline': w['pipeline'],
                    'kind': w['kind'],
                    'start': w['start_time'],
                    'end': w['end_time'],
                    'date': w['date'],
                }
            )
    return conflicts


def add_manual_entry(scope: str, payload: dict, registries: dict | None = None) -> tuple[bool, dict]:
    """Validated, conflict-checked write into the legacy schedule file (full
    payload preserved — the old path silently dropped end_time/priority/device)."""
    day = str(payload.get('date') or ams_today())[:10]
    start_time = str(payload.get('start_time') or '')
    end_time = str(payload.get('end_time') or '')
    mid = str(payload.get('ai_model') or '')
    agent = str(payload.get('agent') or '').strip()
    if not (re.match(r'^\d{2}:\d{2}$', start_time) and re.match(r'^\d{2}:\d{2}$', end_time)):
        return False, {'error': 'start_time/end_time must be HH:MM'}
    if not agent:
        return False, {'error': 'agent required'}
    reg = model_registry(scope, include_deprecated=True)
    if mid not in reg:
        return False, {'error': f'unknown {scope} model id {mid}'}
    conflicts = check_conflict(scope, day, start_time, end_time, registries)
    if conflicts:
        return False, {'error': 'blocked by reserved pipeline window', 'conflicts': conflicts}
    entry = {
        'id': str(uuid.uuid4()),
        'ai_model': mid,
        'agent': agent,
        'start_time': start_time,
        'end_time': end_time,
        'date': day,
        'priority': str(payload.get('priority') or 'High'),
        'bar_id': payload.get('bar_id') or bar_id_for(agent, reg[mid]['slug']),
    }
    pct_key = 'gpu_percent' if scope == 'gpu' else 'cpu_percent'
    dev_key = 'gpu_device' if scope == 'gpu' else 'cpu_device'
    entry[pct_key] = str(payload.get(pct_key) or payload.get('percent') or '1')
    entry['memory_fraction'] = str(payload.get('memory_fraction') or '0.1')
    entry[dev_key] = str(payload.get(dev_key) or payload.get('device') or (devices(scope) or ['?'])[0])
    with _lock:
        data = _load_json(_MANUAL_FILES[scope], {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault(day, []).append(entry)
        _write_manual(scope, data)
    return True, {'entry': entry}


def delete_manual_entry(scope: str, entry_id: str, day: str) -> tuple[bool, dict]:
    with _lock:
        data = _load_json(_MANUAL_FILES[scope], {})
        rows = data.get(day) or []
        keep = [e for e in rows if str(e.get('id')) != str(entry_id)]
        if len(keep) == len(rows):
            return False, {'error': 'entry not found'}
        data[day] = keep
        _write_manual(scope, data)
    return True, {'deleted': entry_id}


def _write_manual(scope: str, data: dict) -> None:
    path = _MANUAL_FILES[scope]
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)
