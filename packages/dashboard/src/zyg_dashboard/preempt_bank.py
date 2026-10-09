# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""preempt_bank.py — the Pre-Emptive generation bank: Claude calls made in advance. 2026-09-20.

THE IDEA. The documentary pipeline makes ~10-14 TEXT Claude calls per episode (subject,
script, hook, fact check, scene descriptions, emotion curve, time-locked scenes, era lock,
the FLUX prompt batch, the period re-ask, the era checks) and then ~40-60 VISION calls that
judge rendered frames. The text calls depend only on the topic, the scraped essay and each
other, so they can be made NOW, while the subscription is there, and replayed LATER when it
is not. The vision calls cannot be pre-made (the frames do not exist yet) — but every one of
them already has a local fallback (Qwen3-VL, OCR, moondream) that the call site takes when a
turn is refused. So a production run without subscription = the recorded brain + local
rendering + local judges.

HOW.
  * A RECORD run is a normal scholarly pipeline started with
    pipeline_options={'preempt': {'mode': 'record', 'entry': <id>}}. subscription_llm.run_turn
    appends every successful turn (hash of system + text blocks, its stage, the reply) to the
    entry's turns.jsonl. The pipeline stops right after the FLUX prompt batch — before any
    image is rendered — snapshots the essay and marks the entry `ready`.
  * A REPLAY run is the same pipeline with mode 'replay'. Stage 2 takes the banked essay
    instead of scraping; run_turn answers each text call from the ledger: exact hash first,
    then the next unused record of the same stage with the same prompt header (TTS timings
    and a re-fetched Wikipedia block shift a few characters between runs; the answer is the
    same answer). A call with an image, or one that has no record, goes live if
    `live_allowed()` says so, else raises SubscriptionLimitError so the call site takes its
    local fallback — never the API key.
  * The children's song workflow makes NO Claude calls (lyrics, storyboard and the frame
    judge are local Ollama), so its bank is only a list of pre-picked briefs.

Context is a contextvar: every pipeline runs on its own thread, so record/replay never
crosses into another pipeline's calls. Layout under data/runtime/preempt/:
    state.json                       — the builder's play/pause state (bp_preempt)
    documentary/<id>/entry.json      — topic, status, counts, timestamps
    documentary/<id>/turns.jsonl     — the recorded turns
    documentary/<id>/state.json      — the snapshot (essay_text, research_meta, script…)
    songs.json                       — the song briefs bank
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(_CREWS, 'data', 'runtime')
ROOT = os.environ.get('ZYG_PREEMPT_DIR') or os.path.join(RUNTIME, 'preempt')
DOC_DIR = os.path.join(ROOT, 'documentary')
SONGS_PATH = os.path.join(ROOT, 'songs.json')
STATE_PATH = os.path.join(ROOT, 'state.json')
_LOCK = threading.RLock()
_CTX: contextvars.ContextVar = contextvars.ContextVar('preempt_ctx', default=None)

ENTRY_STATUSES = ('building', 'ready', 'claimed', 'consumed', 'failed', 'interrupted')
SIG_CHARS = 200  # prompt header length that identifies a call within a stage
MAX_RENDER_ATTEMPTS = 2  # a ready brain whose render failed twice is retired


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def _read_json(path: str, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default() if callable(default) else default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, path)


# ── record / replay context ─────────────────────────────────────────────────


def set_context(mode: str, entry_id: str):
    """Enter record or replay mode on THIS thread. Returns the token for reset()."""
    if mode not in ('record', 'replay') or not entry_id:
        return _CTX.set(None)
    ctx = {
        'mode': mode,
        'entry_id': str(entry_id),
        'dir': os.path.join(DOC_DIR, str(entry_id)),
        'used': set(),
        'hits': 0,
        'misses': 0,
        'recorded': 0,
        'live': 0,
        'refused': 0,
        '_turns': None,
    }
    return _CTX.set(ctx)


def clear_context(token=None) -> None:
    try:
        if token is not None:
            _CTX.reset(token)
            return
    except (ValueError, LookupError) as _exc:
        _zyg_log.debug('context token does not belong to this context, clearing instead: %s', _exc)
    _CTX.set(None)


def current() -> dict | None:
    return _CTX.get()


def _text_of(blocks: list) -> str:
    return '\n'.join(str(b.get('text') or '') for b in (blocks or []) if b.get('type') == 'text').strip()


def _has_image(blocks: list) -> bool:
    return any(b.get('type') == 'image' for b in (blocks or []))


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def request_hash(model: str, system: str, blocks: list) -> str:
    h = hashlib.sha256()
    h.update(_norm(model).encode())
    h.update(b'\x00')
    h.update(_norm(system).encode())
    h.update(b'\x00')
    h.update(_norm(_text_of(blocks)).encode())
    return h.hexdigest()


def request_sig(stage: str, system: str, blocks: list) -> str:
    h = hashlib.sha256()
    h.update(_norm(stage).encode())
    h.update(b'\x00')
    h.update(_norm(system).encode())
    h.update(b'\x00')
    h.update(_norm(_text_of(blocks))[:SIG_CHARS].encode())
    return h.hexdigest()[:24]


def _turns_path(ctx: dict) -> str:
    return os.path.join(ctx['dir'], 'turns.jsonl')


def _load_turns(ctx: dict) -> list:
    if ctx.get('_turns') is None:
        rows = []
        try:
            with open(_turns_path(ctx), encoding='utf-8') as fh:
                for i, line in enumerate(fh):
                    try:
                        r = json.loads(line)
                    except ValueError as _exc:
                        _zyg_log.debug('malformed turn record skipped in %s: %s', _turns_path(ctx), _exc)
                        continue
                    r['_i'] = i
                    rows.append(r)
        except OSError as _exc:
            _zyg_log.debug('no turns ledger at %s yet: %s', _turns_path(ctx), _exc)
        ctx['_turns'] = rows
    return ctx['_turns']


def record_turn(
    ctx: dict,
    *,
    model: str,
    stage: str,
    system: str,
    blocks: list,
    text: str,
    usage: dict | None = None,
    requested_model: str = None,
) -> None:
    """Append one successful live turn (text-only) to the entry's ledger."""
    if not ctx or ctx.get('mode') != 'record' or _has_image(blocks):
        return
    row = {
        'ts': _now(),
        'stage': stage or '',
        'model': model,
        'requested_model': requested_model,
        'hash': request_hash(model, system, blocks),
        'sig': request_sig(stage, system, blocks),
        'request_head': _text_of(blocks)[:SIG_CHARS],
        'request_chars': len(_text_of(blocks)),
        'text': text,
        'usage': usage or {},
    }
    with _LOCK:
        os.makedirs(ctx['dir'], exist_ok=True)
        with open(_turns_path(ctx), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    ctx['recorded'] = ctx.get('recorded', 0) + 1


# A record run that was interrupted (2026-09-23: another session restarted the GUI mid-wave
# and 18 recordings 7-13 turns deep were lost, 418k output tokens) leaves its turns on disk.
# Re-running the same entry reuses them by the same matcher a replay uses, so a lost run
# costs the turns it had not reached yet — not all of them.
_RESUME_ERRORS = ('vanished', 'stale', 'restart', 'gui restarted')


def resume_turn(ctx: dict, *, model: str, stage: str, system: str, blocks: list) -> dict | None:
    """During a RECORD run: the answer already recorded for this call, or None."""
    if not ctx or ctx.get('mode') != 'record' or _has_image(blocks):
        return None
    hit = _match_turn(ctx, model=model, stage=stage, system=system, blocks=blocks, tiers=2)
    if hit:
        ctx['resumed'] = ctx.get('resumed', 0) + 1
    return hit


def _match_turn(ctx: dict, *, model: str, stage: str, system: str, blocks: list, tiers: int = 4) -> dict | None:
    """The next unused recorded turn that answers this call, or None. A record is used once.

    Tiers, in order — a replay uses all four, a resume only the first two, because a resumed
    RECORD run must not substitute a loosely-matched answer for a call whose prompt really
    changed (a re-scraped essay, say): a miss there is correct, and simply goes live.
      1 exact hash (model + system + text)   3 same stage, header equal with digits normalised
      2 same stage + 200-char header sig     4 same stage, first 60 chars (digits normalised)
    """
    rows = _load_turns(ctx)
    used = ctx['used']
    h = request_hash(model, system, blocks)
    sig = request_sig(stage, system, blocks)
    pick = None
    for r in rows:
        if r['_i'] not in used and r.get('hash') == h:
            pick = r
            break
    if pick is None and tiers >= 2:
        for r in rows:
            if r['_i'] not in used and r.get('sig') == sig:
                pick = r
                break
    if pick is None and tiers >= 3:
        want = re.sub(r'\d+', '#', _norm(_text_of(blocks))[:SIG_CHARS])
        for r in rows:
            if r['_i'] in used or _norm(r.get('stage')) != _norm(stage):
                continue
            if re.sub(r'\d+', '#', _norm(r.get('request_head') or '')) == want:
                pick = r
                break
    if pick is None and tiers >= 4:
        # the prompt's instruction line names the call; its body is what drifted
        want60 = re.sub(r'\d+', '#', _norm(_text_of(blocks))[:60])
        for r in rows:
            if r['_i'] in used or _norm(r.get('stage')) != _norm(stage):
                continue
            have60 = re.sub(r'\d+', '#', _norm(r.get('request_head') or '')[:60])
            n = min(len(want60), len(have60))
            if n >= 24 and want60[:n] == have60[:n]:
                pick = r
                break
    if pick is None:
        return None
    used.add(pick['_i'])
    return {
        'text': pick.get('text') or '',
        'usage': pick.get('usage') or {},
        'match': 'hash' if pick.get('hash') == h else 'sig',
        'recorded_ts': pick.get('ts'),
    }


def replay_turn(ctx: dict, *, model: str, stage: str, system: str, blocks: list) -> dict | None:
    """The recorded answer for this call during a REPLAY run, or None."""
    if not ctx or ctx.get('mode') != 'replay' or _has_image(blocks):
        return None
    hit = _match_turn(ctx, model=model, stage=stage, system=system, blocks=blocks, tiers=4)
    if hit is None:
        ctx['misses'] = ctx.get('misses', 0) + 1
        return None
    ctx['hits'] = ctx.get('hits', 0) + 1
    return hit


# ── quota / live guard ──────────────────────────────────────────────────────

_QUOTA_CACHE: dict = {'ts': 0.0, 'row': None, 'error': ''}
QUOTA_TTL_S = 120.0


def quota_snapshot(max_age_s: float = QUOTA_TTL_S) -> dict:
    """The login's usage windows: {'five_hour_pct','seven_day_pct','five_hour_resets_at',
    'seven_day_resets_at','sampled_at','error'}. Cached; the live endpoint is asked at most
    every `max_age_s` seconds. Falls back to the quota meter's last status file."""
    now = time.time()
    with _LOCK:
        if _QUOTA_CACHE['row'] is not None and now - _QUOTA_CACHE['ts'] < max_age_s:
            return _QUOTA_CACHE['row']
    row = {
        'five_hour_pct': None,
        'seven_day_pct': None,
        'five_hour_resets_at': None,
        'seven_day_resets_at': None,
        'sampled_at': None,
        'error': '',
    }
    try:
        from zyg_dashboard import quota_meter

        payload = quota_meter.fetch_usage(timeout=8.0)
        p = quota_meter.parse_usage_payload(payload, now)
        row.update(
            five_hour_pct=p['five_hour']['pct'],
            seven_day_pct=p['seven_day']['pct'],
            five_hour_resets_at=_iso(p['five_hour']['resets_at']),
            seven_day_resets_at=_iso(p['seven_day']['resets_at']),
            sampled_at=_iso(now),
        )
    except Exception as exc:  # noqa: BLE001 — no network, no login: fall back to the meter's file
        row['error'] = f'{type(exc).__name__}: {exc}'[:160]
        try:
            from zyg_dashboard import quota_meter

            st = quota_meter.read_status()
            if st.get('last_ok_ts'):
                row.update(
                    five_hour_pct=st.get('five_hour_pct'),
                    seven_day_pct=st.get('seven_day_pct'),
                    sampled_at=_iso(st.get('last_ok_ts')),
                )
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('quota meter fallback failed, the row carries no usage percentages: %s', _exc)
    with _LOCK:
        _QUOTA_CACHE.update(ts=now, row=row)
    return row


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).astimezone().isoformat(timespec='minutes')
    except (TypeError, ValueError, OSError):
        return None


def state_load() -> dict:
    return _read_json(STATE_PATH, dict)


def state_save(st: dict) -> None:
    with _LOCK:
        _write_json(STATE_PATH, st)


def note_limit(resets_at_iso: str | None = None, reason: str = '') -> None:
    """A turn was refused by the subscription limit: hold live calls until the reset."""
    st = state_load()
    until = resets_at_iso
    if not until:
        q = quota_snapshot(max_age_s=0)
        until = q.get('five_hour_resets_at') or q.get('seven_day_resets_at')
    st['limit_until'] = until
    st['limit_reason'] = (reason or 'subscription limit')[:200]
    st['limit_noted_at'] = _now()
    state_save(st)


def limit_hold() -> tuple:
    """(holding: bool, until_iso: str|None, reason: str) from the last refused turn."""
    st = state_load()
    until = st.get('limit_until')
    if not until:
        return False, None, ''
    try:
        t = datetime.fromisoformat(str(until))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t <= datetime.now(timezone.utc):
            return False, until, ''
    except ValueError:
        return False, None, ''
    return True, until, st.get('limit_reason') or 'subscription limit'


def live_allowed(ctx: dict | None = None, policy: str = None) -> tuple:
    """(allowed: bool, why: str) — may a production run spend a live turn on a call that has
    no recorded answer? Policy from the Pre-Emptive card: always | never | auto (quota meter
    shows room and no refused turn is holding)."""
    if policy is None:
        try:
            from zyg_dashboard import approval_queue_settings as aqs

            policy = aqs.get('preempt', 'live_when_exhausted')
        except Exception:  # noqa: BLE001
            policy = 'auto'
    if policy == 'always':
        return True, 'policy: always'
    if policy == 'never':
        return False, 'policy: never — replay + local fallbacks only'
    holding, until, reason = limit_hold()
    if holding:
        return False, f'limit hold until {until} ({reason})'
    q = quota_snapshot()
    for key in ('five_hour_pct', 'seven_day_pct'):
        pct = q.get(key)
        if isinstance(pct, (int, float)) and pct >= 99.5:
            return False, f'{key.replace("_pct", "")} window at {pct:.0f} %'
    return True, 'quota available'


# ── documentary entries ─────────────────────────────────────────────────────


def _entry_path(entry_id: str) -> str:
    return os.path.join(DOC_DIR, entry_id, 'entry.json')


def _slug(topic: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', str(topic or '').lower()).strip('-')[:40]
    return s or 'topic'


def new_entry(topic: str, pool_label: str = '') -> dict:
    with _LOCK:
        eid = f'd-{time.strftime("%Y%m%d")}-{_slug(topic)}-{uuid.uuid4().hex[:6]}'
        e = {
            'id': eid,
            'topic': str(topic).strip(),
            'pool': pool_label or '',
            'status': 'building',
            'created_at': _now(),
            'built_at': None,
            'brain_pipeline_id': None,
            'turns': 0,
            'claimed_by': None,
            'claimed_at': None,
            'consumed_at': None,
            'render_attempts': 0,
            'error': None,
            'chars': {},
        }
        _write_json(_entry_path(eid), e)
        return e


def load_entry(entry_id: str) -> dict | None:
    e = _read_json(_entry_path(str(entry_id)), None)
    return e if isinstance(e, dict) else None


def save_entry(e: dict) -> None:
    with _LOCK:
        _write_json(_entry_path(e['id']), e)


def list_entries() -> list:
    out = []
    try:
        for d in sorted(os.listdir(DOC_DIR)):
            e = _read_json(os.path.join(DOC_DIR, d, 'entry.json'), None)
            if isinstance(e, dict) and e.get('id'):
                out.append(e)
    except OSError as _exc:
        _zyg_log.warning('%s not listable, reporting no entries: %s', DOC_DIR, _exc)
    out.sort(key=lambda e: e.get('created_at') or '')
    return out


def counts() -> dict:
    c = {s: 0 for s in ENTRY_STATUSES}
    for e in list_entries():
        c[e.get('status') or 'failed'] = c.get(e.get('status') or 'failed', 0) + 1
    c['total'] = sum(c[s] for s in ENTRY_STATUSES)
    c['built'] = c['ready'] + c['claimed'] + c['consumed']
    return c


def reap_stale_building(max_age_s: int = 900) -> int:
    """Fail entries stuck in `building` whose run is long gone. Returns how many.

    2026-09-23: the GUI crashed mid-wave and came back with an empty job registry, leaving
    12 entries in `building` for ever. `counts()['building']` gates new starts so the target
    is not overshot — so those 12 ghosts made the builder believe 100 were accounted for and
    it stopped at 88. An entry that has not been written to in 15 minutes is not building.
    """
    n = 0
    for e in list_entries():
        if e.get('status') != 'building':
            continue
        try:
            age = time.time() - os.path.getmtime(_entry_path(e['id']))
        except OSError:
            age = max_age_s + 1
        turns_path = os.path.join(DOC_DIR, e['id'], 'turns.jsonl')
        try:
            age = min(age, time.time() - os.path.getmtime(turns_path))
        except OSError as _exc:
            _zyg_log.debug('no turns ledger at %s, judging staleness on the entry file alone: %s', turns_path, _exc)
        if age < max_age_s:
            continue
        finish_entry(e['id'], False, error=f'stale: no progress for {int(age // 60)} min (run lost)')
        n += 1
    return n


def bank_metrics() -> dict:
    """One measured picture of the bank for the Metrics tab (2026-09-23).

    Per entry: what the recording cost (turns, tokens, wall seconds) and, once the
    entry has been replayed into an episode, what the replay hit, missed and had to
    take live. Nothing here is computed from an assumption; every number comes from
    a file the bank wrote while it ran.
    """
    rows, tot = (
        [],
        {
            'entries': 0,
            'built': 0,
            'turns': 0,
            'input_tokens': 0,
            'output_tokens': 0,
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'build_s': 0,
            'timed': 0,
            'replayed_entries': 0,
            'replay_hits': 0,
            'replay_misses': 0,
            'replay_live': 0,
            'replay_refused': 0,
            'tokens_saved': 0,
        },
    )
    for e in list_entries():
        m = e.get('metrics') if isinstance(e.get('metrics'), dict) else None
        if not m or not m.get('turns'):
            m = turn_metrics(e['id'])
            st, en = _epoch(e.get('created_at')), _epoch(e.get('built_at') or e.get('created_at'))
            m['build_s'] = round(en - st) if (st and en and en >= st) else None
        rp = e.get('last_replay') if isinstance(e.get('last_replay'), dict) else {}
        row = {
            'id': e['id'],
            'topic': e.get('topic'),
            'pool': e.get('pool'),
            'status': e.get('status'),
            'created_at': e.get('created_at'),
            'built_at': e.get('built_at'),
            'consumed_at': e.get('consumed_at'),
            'pipeline_id': e.get('brain_pipeline_id'),
            'error': e.get('error'),
            'turns': m.get('turns') or 0,
            'input_tokens': m.get('input_tokens') or 0,
            'output_tokens': m.get('output_tokens') or 0,
            'cache_read_tokens': m.get('cache_read_tokens') or 0,
            'cache_write_tokens': m.get('cache_write_tokens') or 0,
            'build_s': m.get('build_s'),
            'stages': m.get('stages') or {},
            'replay': {
                'hits': int(rp.get('hits') or 0),
                'misses': int(rp.get('misses') or 0),
                'live': int(rp.get('live') or 0),
                'refused': int(rp.get('refused') or 0),
            }
            if rp
            else None,
        }
        rows.append(row)
        tot['entries'] += 1
        tot['built'] += 1 if e.get('status') in ('ready', 'claimed', 'consumed') else 0
        for k in ('turns', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'):
            tot[k] += row[k]
        if row['build_s']:
            tot['build_s'] += row['build_s']
            tot['timed'] += 1
        if row['replay']:
            tot['replayed_entries'] += 1
            tot['replay_hits'] += row['replay']['hits']
            tot['replay_misses'] += row['replay']['misses']
            tot['replay_live'] += row['replay']['live']
            tot['replay_refused'] += row['replay']['refused']
            # A replayed turn is a turn the subscription did NOT have to answer again.
            if row['turns']:
                tot['tokens_saved'] += round(row['output_tokens'] * row['replay']['hits'] / row['turns'])
    songs = songs_load()
    return {
        'entries': rows,
        'totals': tot,
        'counts': counts(),
        'songs_counts': songs_counts(),
        'songs': [
            {
                'id': r.get('id'),
                'theme': r.get('theme'),
                'mood': r.get('mood'),
                'age_band': r.get('age_band'),
                'source': r.get('source'),
                'status': r.get('status'),
                'created_at': r.get('created_at'),
                'claimed_at': r.get('claimed_at'),
            }
            for r in songs
        ],
        'state': state_load(),
        'generated_at': _now(),
    }


def turn_count(entry_id: str) -> int:
    n = 0
    try:
        with open(os.path.join(DOC_DIR, entry_id, 'turns.jsonl'), encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    n += 1
    except OSError as _exc:
        _zyg_log.debug('no turns ledger for %s, counting zero turns: %s', entry_id, _exc)
    return n


def turn_metrics(entry_id: str) -> dict:
    """What this entry's recording actually cost, from its own ledger (2026-09-23).

    The usage each turn was billed at is written with the turn, so the bank is
    self-describing: the metrics never have to re-join the audit log to say what a
    banked brain cost, and a replay can report the same numbers as tokens SAVED.
    """
    m = {
        'turns': 0,
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read_tokens': 0,
        'cache_write_tokens': 0,
        'stages': {},
        'first_ts': None,
        'last_ts': None,
        'chars': 0,
    }
    try:
        with open(os.path.join(DOC_DIR, str(entry_id), 'turns.jsonl'), encoding='utf-8') as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('malformed turn record skipped for %s: %s', entry_id, _exc)
                    continue
                u = r.get('usage') or {}
                m['turns'] += 1
                m['input_tokens'] += int(u.get('input_tokens') or 0)
                m['output_tokens'] += int(u.get('output_tokens') or 0)
                m['cache_read_tokens'] += int(u.get('cache_read_input_tokens') or 0)
                m['cache_write_tokens'] += int(u.get('cache_creation_input_tokens') or 0)
                m['chars'] += len(str(r.get('text') or ''))
                st = str(r.get('stage') or '?')
                m['stages'][st] = m['stages'].get(st, 0) + 1
                ts = r.get('ts')
                if ts:
                    m['first_ts'] = m['first_ts'] or ts
                    m['last_ts'] = ts
    except OSError as _exc:
        _zyg_log.debug('no turns ledger for %s, metrics stay at zero: %s', entry_id, _exc)
    m['tokens'] = m['input_tokens'] + m['output_tokens']
    return m


def _epoch(iso: str):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def snapshot(entry_id: str, state: dict) -> None:
    """The record run's pipeline state at the stop point: what a replay run injects."""
    keep = {}
    for k in (
        'essay_text',
        'research_meta',
        'essay_title',
        'essay_authors',
        'script',
        'word_count',
        'youtube_title',
        'youtube_description',
        'youtube_tags',
        'era_lock',
        '_stage3_scene_list',
        'turning_points',
        'tts_duration',
        'scholarly_topic',
        'directive',
        'preempt_n_slots',
    ):
        if k in state:
            keep[k] = state[k]
    keep['snapshot_at'] = _now()
    with _LOCK:
        _write_json(os.path.join(DOC_DIR, entry_id, 'state.json'), keep)


def replay_state(entry_id: str) -> dict:
    return _read_json(os.path.join(DOC_DIR, str(entry_id), 'state.json'), dict) or {}


def finish_entry(entry_id: str, ok: bool, error: str = '', pipeline_id: str = None, chars: dict = None) -> dict | None:
    e = load_entry(entry_id)
    if not e:
        return None
    e['brain_pipeline_id'] = pipeline_id or e.get('brain_pipeline_id')
    e['turns'] = turn_count(entry_id)
    m = turn_metrics(entry_id)
    started, ended = _epoch(e.get('created_at')), _epoch(_now())
    m['build_s'] = round(ended - started) if (started and ended and ended >= started) else None
    e['metrics'] = m
    if chars:
        e['chars'] = chars
    if ok and e['turns'] > 0 and replay_state(entry_id).get('essay_text'):
        e['status'] = 'ready'
        e['built_at'] = _now()
        e['error'] = None
    else:
        err = error or ('no turns recorded' if e['turns'] == 0 else 'no snapshot')
        # Work in hand: the run lost its process, not its recording. Re-running this entry
        # reuses every turn already on disk (resume_turn), so it is queued, not discarded.
        resumable = e['turns'] > 0 and any(w in err.lower() for w in _RESUME_ERRORS)
        e['status'] = 'interrupted' if resumable else 'failed'
        e['error'] = err[:300]
    save_entry(e)
    return e


def take_interrupted() -> dict | None:
    """The oldest entry whose recording was cut off, put back into `building`.

    Its turns.jsonl is kept, so the re-run reuses every turn it already holds.
    """
    with _LOCK:
        for e in list_entries():
            if e.get('status') != 'interrupted':
                continue
            e['status'] = 'building'
            e['resumed_at'] = _now()
            e['resume_count'] = int(e.get('resume_count') or 0) + 1
            save_entry(e)
            return e
    return None


def take_ready(n: int) -> list:
    """Claim up to n ready entries (oldest first). Returns the entries, now `claimed`."""
    out = []
    with _LOCK:
        for e in list_entries():
            if len(out) >= n:
                break
            if e.get('status') == 'ready':
                e['status'] = 'claimed'
                e['claimed_at'] = _now()
                save_entry(e)
                out.append(e)
    return out


def attach(entry_id: str, pipeline_id: str) -> None:
    e = load_entry(entry_id)
    if e:
        e['claimed_by'] = pipeline_id
        e['status'] = 'claimed'
        save_entry(e)


def settle(entry_id: str, outcome: str, ctx_stats: dict | None = None) -> None:
    """The production run that used this brain finished: done → consumed; failed → back to
    ready for one more try, then failed."""
    e = load_entry(entry_id)
    if not e:
        return
    if ctx_stats:
        e['last_replay'] = {k: ctx_stats.get(k) for k in ('hits', 'misses', 'live', 'refused')}
    if outcome == 'done':
        e['status'] = 'consumed'
        e['consumed_at'] = _now()
    else:
        e['render_attempts'] = int(e.get('render_attempts') or 0) + 1
        if e['render_attempts'] >= MAX_RENDER_ATTEMPTS:
            e['status'] = 'failed'
            e['error'] = f'production run failed {e["render_attempts"]}×'
        else:
            e['status'] = 'ready'
            e['claimed_by'] = None
            e['claimed_at'] = None
    save_entry(e)


def release(entry_id: str) -> None:
    """A claimed entry whose batch was aborted before its run started: back to ready."""
    e = load_entry(entry_id)
    if e and e.get('status') == 'claimed' and not e.get('claimed_by'):
        e['status'] = 'ready'
        e['claimed_at'] = None
        save_entry(e)


def delete_entry(entry_id: str) -> bool:
    d = os.path.join(DOC_DIR, str(entry_id))
    if not os.path.isdir(d) or '/' in str(entry_id) or '..' in str(entry_id):
        return False
    with _LOCK:
        shutil.rmtree(d, ignore_errors=True)
    return True


def banked_topics() -> set:
    """Normalised topics already in the bank (any status but failed) — the builder skips them."""
    out = set()
    for e in list_entries():
        if e.get('status') != 'failed':
            out.add(re.sub(r'[^a-z0-9 ]', '', str(e.get('topic') or '').lower()).strip())
    return out


# ── songs bank ───────────────────────────────────────────────────────────────


def songs_load() -> list:
    d = _read_json(SONGS_PATH, dict)
    rows = d.get('briefs') if isinstance(d, dict) else None
    return list(rows or [])


def songs_save(rows: list) -> None:
    with _LOCK:
        _write_json(SONGS_PATH, {'briefs': rows, 'saved_at': _now()})


def songs_counts() -> dict:
    c = {'ready': 0, 'claimed': 0, 'consumed': 0, 'failed': 0}
    for r in songs_load():
        c[r.get('status') or 'ready'] = c.get(r.get('status') or 'ready', 0) + 1
    c['total'] = sum(c.values())
    c['built'] = c['ready'] + c['claimed'] + c['consumed']
    return c


def songs_add(briefs: list) -> int:
    with _LOCK:
        rows = songs_load()
        have = {re.sub(r'[^a-z0-9 ]', '', str(r.get('theme') or '').lower()).strip() for r in rows}
        n = 0
        for b in briefs or []:
            theme = str(b.get('theme') or '').strip()
            key = re.sub(r'[^a-z0-9 ]', '', theme.lower()).strip()
            if not theme or key in have:
                continue
            have.add(key)
            rows.append(
                {
                    'id': f's-{uuid.uuid4().hex[:8]}',
                    'theme': theme,
                    'mood': b.get('mood'),
                    'age_band': b.get('age_band'),
                    'source': b.get('source', 'llm'),
                    'status': 'ready',
                    'created_at': _now(),
                    'claimed_at': None,
                    'pipeline_id': None,
                }
            )
            n += 1
        songs_save(rows)
        return n


def songs_take(n: int) -> list:
    """Claim up to n ready briefs (oldest first)."""
    out = []
    with _LOCK:
        rows = songs_load()
        for r in rows:
            if len(out) >= n:
                break
            if r.get('status') == 'ready':
                r['status'] = 'claimed'
                r['claimed_at'] = _now()
                out.append(dict(r))
        songs_save(rows)
    return out


def songs_settle(brief_id: str, outcome: str, pipeline_id: str = None) -> None:
    with _LOCK:
        rows = songs_load()
        for r in rows:
            if r.get('id') == brief_id:
                r['pipeline_id'] = pipeline_id or r.get('pipeline_id')
                r['status'] = 'consumed' if outcome == 'done' else 'failed'
                break
        songs_save(rows)


def songs_delete(brief_id: str) -> bool:
    with _LOCK:
        rows = songs_load()
        keep = [r for r in rows if r.get('id') != brief_id]
        if len(keep) == len(rows):
            return False
        songs_save(keep)
        return True


def songs_banked_themes() -> set:
    return {
        re.sub(r'[^a-z0-9 ]', '', str(r.get('theme') or '').lower()).strip()
        for r in songs_load()
        if r.get('status') != 'failed'
    }
