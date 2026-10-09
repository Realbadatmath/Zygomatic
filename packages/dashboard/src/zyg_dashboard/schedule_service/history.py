# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import (
    AGENT_MODEL_SLUG,
    _AGENT_LEDGER,
    _AGENT_OPEN,
    _AMS,
    _RUNTIME,
    _SCHEDULE_DIR,
    _load_json,
    _parse_iso,
    _slugify,
    ams_now,
    ams_today,
    datetime,
    json,
    model_registry,
    os,
    re,
    timedelta,
)
from .durations import DEFAULT_DURATIONS, _PIPELINE_FALLBACK_MODEL, _STATE_FILE_TYPES
from .live import _entry
from .planning import _parse_day
import logging as _zyg_logging_split

_zyg_log = _zyg_logging_split.getLogger('zyg_dashboard.schedule_service')

# ── history reconstruction ───────────────────────────────────────────────────
# Rebuilds past days' 24h schedules from the ACTUAL run records: every state
# file's stage_timeline (started_at/ended_at) becomes per-stage bars, plus the
# legacy Schedule/history/<date>.json archives. kind='history', never reserved.

_HISTORY_CACHE = os.path.join(_RUNTIME, 'schedule_history_index.json')
_history_mem: dict = {'sig': None, 'days': {}}


def _history_signature() -> str:
    import glob as _glob

    n, newest = 0, 0.0
    for pat, _pt in _STATE_FILE_TYPES:
        for f in _glob.glob(os.path.join(_RUNTIME, pat)):
            n += 1
            try:
                newest = max(newest, os.path.getmtime(f))
            except OSError as _exc:
                _zyg_log.debug('%s not statable, left out of the history signature: %s', f, _exc)
    return f'v3:{n}:{int(newest)}'  # v3 (2026-09-05): keyed by every covered day


def _build_history_index() -> dict:
    """{date: [entry, ...]} from all state files' completed stage records."""
    import glob as _glob

    idx: dict[str, list] = {}
    for pat, ptype in _STATE_FILE_TYPES:
        for f in _glob.glob(os.path.join(_RUNTIME, pat)):
            d = _load_json(f, None)
            if not isinstance(d, dict):
                continue
            _id_keys = {
                'documentary': ('pipeline_id',),
                'storyteller': ('pipeline_id',),
                'contact_sheet': ('char_id',),
                'char_gen': ('char_id',),
                'creature': ('creature_id', 'char_id'),
            }.get(ptype, ('pipeline_id', 'char_id'))
            jid = next((str(d[k]) for k in _id_keys if d.get(k)), os.path.basename(f))
            pt = str(d.get('department') or ptype).lower()
            if pt in ('scholarly', 'crime'):
                pt = 'documentary'
            if pt not in DEFAULT_DURATIONS and pt not in _PIPELINE_FALLBACK_MODEL:
                pt = ptype
            topic = str(d.get('scholarly_topic') or d.get('story_prompt') or '')[:50]
            for n, st in enumerate(d.get('stage_timeline') or []):
                nm = str(st.get('name') or '')
                if not nm or nm.lower() == 'done':
                    continue
                s0 = _parse_iso(st.get('started_at'))
                s1 = _parse_iso(st.get('ended_at'))
                if not s0 or not s1 or (s1 - s0).total_seconds() < 120:
                    continue
                e = _entry(
                    eid=f'hist_{pt}_{jid}_{n}',
                    source='history',
                    kind='history',
                    ptype=pt,
                    stage=nm,
                    label=f'{pt}:{jid[:10]} {nm}' + (f' — {topic}' if topic else ''),
                    start=s0,
                    end=s1,
                    status=str(st.get('status') or 'completed'),
                    reserved=False,
                )
                # 2026-09-05: a stage that crosses midnight (creature Sheet
                # Review 18:07 → 14:53 next day) must be found from BOTH days'
                # pages — index it under every calendar day it touches.
                for day in _days_of(e):
                    idx.setdefault(day, []).append(e)
    return idx


def _days_of(e: dict) -> list[str]:
    """Every ISO calendar day an entry covers (start day … end day)."""
    d0 = _parse_day(e.get('date')) or _parse_day((e.get('start_iso') or '')[:10])
    d1 = _parse_day((e.get('end_iso') or '')[:10]) or d0
    if d0 is None:
        return []
    if d1 is None or d1 < d0:
        d1 = d0
    n = min((d1 - d0).days, 31)
    return [(d0 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n + 1)]


def _history_index() -> dict:
    sig = _history_signature()
    if _history_mem['sig'] == sig:
        return _history_mem['days']
    cache = _load_json(_HISTORY_CACHE, None)
    if isinstance(cache, dict) and cache.get('_sig') == sig:
        _history_mem.update(sig=sig, days=cache.get('days', {}))
        return _history_mem['days']
    days = _build_history_index()
    _history_mem.update(sig=sig, days=days)
    try:
        _tmp = f'{_HISTORY_CACHE}.{os.getpid()}.tmp'
        with open(_tmp, 'w', encoding='utf-8') as fh:
            json.dump({'_sig': sig, 'days': days}, fh)
        os.replace(_tmp, _HISTORY_CACHE)
    except OSError as _exc:
        _zyg_log.warning('history cache %s not written, the index is rebuilt next time: %s', _HISTORY_CACHE, _exc)
    return days


def _archive_entries_for(scope: str, day: str) -> list[dict]:
    """Legacy Schedule/history/<date>.json snapshots (2025-era manual data);
    ai_model there is a display NAME, not an id."""
    d = _load_json(os.path.join(_SCHEDULE_DIR, 'history', f'{day}.json'), None)
    if not isinstance(d, dict):
        return []
    out = []
    reg = model_registry(scope, include_deprecated=True)
    by_name = {m['name'].lower(): m['slug'] for m in reg.values()}
    for i, e in enumerate(d.get('entries') or []):
        if not isinstance(e, dict):
            continue
        dev_key = 'gpu_device' if scope == 'gpu' else 'cpu_device'
        if scope == 'cpu' and dev_key not in e and 'cpu_percent' not in e:
            continue
        if scope == 'gpu' and 'gpu_percent' not in e and dev_key not in e:
            continue
        name = str(e.get('ai_model') or '')
        slug = by_name.get(name.lower()) or _slugify(name) or 'unknown'
        try:
            start = datetime.strptime(f'{day} {e.get("start_time", "00:00")}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
            end = datetime.strptime(f'{day} {e.get("end_time", "00:00")}', '%Y-%m-%d %H:%M').replace(tzinfo=_AMS)
            if end <= start:
                end += timedelta(days=1)
        except ValueError as _exc:
            _zyg_log.warning('archived entry %s has unparsable times, left out of the day: %s', e.get('id'), _exc)
            continue
        ent = _entry(
            eid=str(e.get('id') or f'arch_{day}_{i}'),
            source='history',
            kind='history',
            ptype='manual',
            stage='archived entry',
            label=f'{e.get("agent", "archived")} / {name}',
            start=start,
            end=end,
            agent=str(e.get('agent') or 'archived'),
            slug=slug,
            device=scope,
            status='archived',
            reserved=False,
        )
        out.append(ent)
    return out


def history_entries_for(scope: str, days: list[str]) -> list[dict]:
    today = ams_today()
    past = [d for d in days if d < today]
    if not past:
        return []
    idx = _history_index()
    out: list[dict] = []
    seen: set[str] = set()
    for day in past:
        for e in idx.get(day, []):
            if e.get('device') == scope and e['id'] not in seen:
                seen.add(e['id'])
                out.append(e)
        out.extend(_archive_entries_for(scope, day))
    return out


# ── agent sessions (Claude Code in VS Code) ──────────────────────────────────
# Orange bars: every span in which an agent session was measurably on this
# device, from the ledger agent_activity.py writes.  Labelled with the busiest
# command the session ran in that span (the Session Tree board's task titles
# are behind a browser-only API by rule, so they are not joined here).

_agent_mem: dict = {'sig': None, 'spans': []}


def _file_sig(path: str) -> str:
    try:
        st = os.stat(path)
        return f'{int(st.st_mtime)}:{st.st_size}'
    except OSError:
        return 'missing'


def _agent_spans() -> list[dict]:
    sig = _file_sig(_AGENT_LEDGER) + '|' + _file_sig(_AGENT_OPEN)
    if _agent_mem['sig'] == sig:
        return _agent_mem['spans']
    spans: list[dict] = []
    try:
        with open(_AGENT_LEDGER, encoding='utf-8') as fh:
            for ln in fh:
                try:
                    rec = json.loads(ln)
                except ValueError as _exc:
                    _zyg_log.debug('malformed agent ledger record skipped: %s', _exc)
                    continue
                if isinstance(rec, dict):
                    spans.append(rec)
    except OSError as _exc:
        _zyg_log.debug('no agent ledger at %s yet: %s', _AGENT_LEDGER, _exc)
    d = _load_json(_AGENT_OPEN, None)
    if isinstance(d, dict):
        for rec in d.get('spans') or []:
            if isinstance(rec, dict):
                rec = dict(rec)
                rec['open'] = True
                spans.append(rec)
    _agent_mem.update(sig=sig, spans=spans)
    return spans


def _agent_what(rec: dict) -> str:
    cmds = [str(c) for c in (rec.get('cmds') or []) if c]
    kinds = [str(k) for k in (rec.get('kinds') or [])]
    if cmds:
        c = cmds[0]
        # the interesting token is the script, not the interpreter path — keep
        # the script's parent dir so `comfyui/main.py` stays recognisable
        c = re.sub(r'^\S*/(python[\d.]*|bash|sh)\s+', '', c)
        m = re.match(r'^(\S+?/)?([^/\s]+/[^/\s]+)(\s.*)?$', c)
        if m and m.group(1):
            c = m.group(2) + (m.group(3) or '')
        return c[:70]
    return ', '.join(kinds) or 'hardware active'


def agent_entries_for(scope: str, days: list[str], now: datetime | None = None) -> list[dict]:
    now = now or ams_now()
    if not days:
        return []
    w0 = datetime.strptime(min(days), '%Y-%m-%d').replace(tzinfo=_AMS)
    w1 = datetime.strptime(max(days), '%Y-%m-%d').replace(tzinfo=_AMS) + timedelta(days=1)
    out: list[dict] = []
    for rec in _agent_spans():
        if rec.get('device') != scope:
            continue
        try:
            t0 = float(rec.get('start_ts') or 0)
            t1 = float(rec.get('end_ts') or 0)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('agent span without numeric timestamps skipped: %s', _exc)
            continue
        if not t0:
            continue
        is_open = bool(rec.get('open'))
        start = datetime.fromtimestamp(t0, tz=_AMS)
        end = now if is_open else datetime.fromtimestamp(t1 or t0, tz=_AMS)
        if end <= start:
            end = start + timedelta(seconds=60)
        if end < w0 or start >= w1:
            continue
        name = str(rec.get('name') or rec.get('short') or 'agent')
        sid = str(rec.get('sid') or '')
        cmds = [str(c) for c in (rec.get('cmds') or [])]
        kinds = [str(k) for k in (rec.get('kinds') or [])]
        e = _entry(
            eid=f'agent_{scope}_{sid[:8]}_{int(t0)}',
            source='agent_ledger',
            kind='agent',
            ptype='agent',
            stage=', '.join(kinds) or 'session',
            label=f'🕱 {name} — {_agent_what(rec)}',
            start=start,
            end=end,
            agent=name,
            slug=AGENT_MODEL_SLUG,
            device=scope,
            status='running' if is_open else ('recovered' if rec.get('recovered') else 'completed'),
            reserved=False,
            priority='Low',
        )
        e.update(
            {
                'session_id': sid,
                'session_name': name,
                'project': rec.get('project') or '',
                'entrypoint': rec.get('entrypoint') or '',
                'cmds': cmds[:5],
                'peak_vram_mb': rec.get('peak_vram_mb'),
                'peak_cpu_cores': rec.get('peak_cpu_cores'),
                'peak_ram_mb': rec.get('peak_ram_mb'),
                'open': is_open,
            }
        )
        out.append(e)
    return out
