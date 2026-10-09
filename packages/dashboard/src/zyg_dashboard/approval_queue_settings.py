# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""approval_queue_settings.py — the one settings file behind the Approval Queue cards. 2026-09-20.

Why. The three production batchers (bp_zero documentary auto-mode, bp_storyteller_daily,
bp_melody_daily) took their cadence from module constants and environment variables read
once at import: six topics per batch, "+2 days at 09:00", five songs a day at 09:00, a 24 GB
RAM gate. Changing any of them meant an edit and a GUI restart. The rebuilt Approval Queue
board lets the operator expand a workflow card and adjust these, so they live here, in
data/runtime/approval_queue_settings.json, read at each watcher tick (a file read every 30 s
is nothing). Environment variables remain the DEFAULT for a key that was never saved, so a
box that never touches the board behaves exactly as before.

NOT adjustable (2026-09-22): the free-RAM gate. It used to be a field per card, which let the
board contradict the rule the rest of the box runs on. The gate stays where it always was — the
batchers' own `ZYG_*_MIN_FREE_RAM_GB` environment defaults (24 GB), the same figure bp_sports,
bp_remix, bp_remixai and bp_market use — and the cards state it instead of offering it. A value
saved by the old field is ignored: `get()` raises KeyError for a field that is not in the schema,
and every caller reads it through `_aq_get(key, default)`, which falls back to that default.

Schema per workflow: an ordered list of fields (key, label, type, default, min, max, step,
options, help). `get(wf, key)` returns the saved value or the default; `update(wf, {...})`
validates and saves; `fields(wf)` is the UI shape.
"""

from __future__ import annotations

import json
import os
import threading
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(_CREWS, 'data', 'runtime')
PATH = os.environ.get('ZYG_APPROVAL_QUEUE_SETTINGS') or os.path.join(_RUNTIME, 'approval_queue_settings.json')
_LOCK = threading.RLock()
_CACHE: dict = {'mtime': None, 'data': {}}


def _env_num(name: str, default):
    v = os.environ.get(name, '')
    if v.strip():
        try:
            return type(default)(float(v)) if isinstance(default, int) else float(v)
        except ValueError as _exc:
            _zyg_log.warning('%s is not numeric, using the default %r: %s', name, default, _exc)
    return default


def _f(key, label, typ, default, lo=None, hi=None, step=1, options=None, help_=''):
    return {
        'key': key,
        'label': label,
        'type': typ,
        'default': default,
        'min': lo,
        'max': hi,
        'step': step,
        'options': options or [],
        'help': help_,
    }


SCHEMA: dict = {
    'documentary': [
        _f(
            'topics_per_batch',
            'Topics per batch',
            'number',
            6,
            1,
            12,
            1,
            help_='Documentary topics queued per batch (was a fixed 6).',
        ),
        _f(
            'cadence_days',
            'Days between batches',
            'number',
            2,
            1,
            14,
            1,
            help_='The next batch is armed this many days after the previous one completes.',
        ),
        _f(
            'batch_hour', 'Batch hour (Amsterdam)', 'number', 9, 0, 23, 1, help_='Hour of the day the next batch fires.'
        ),
        _f(
            'use_bank_first',
            'Use pre-built episodes first',
            'bool',
            True,
            help_='Take topics from the Pre-Emptive bank (recorded Claude calls) before drawing from the pools.',
        ),
    ],
    'storyteller': [
        _f(
            'max_per_day',
            'Episodes per day (cap)',
            'number',
            22,
            1,
            22,
            1,
            help_='At most this many of the enabled series templates get an episode per day.',
        ),
    ],
    'melody': [
        _f('per_day', 'Songs per day', 'number', _env_num('ZYG_MELODY_PER_DAY', 5), 1, 20, 1),
        _f('hour', 'Batch hour (Amsterdam)', 'number', _env_num('ZYG_MELODY_HOUR', 9), 0, 23, 1),
        _f(
            'use_bank_first',
            'Use pre-picked song briefs first',
            'bool',
            True,
            help_="Take the day's song briefs from the Pre-Emptive song bank before asking the local model.",
        ),
    ],
    'jackmona': [
        _f(
            'hour',
            'Pair hour (Amsterdam)',
            'number',
            _env_num('ZYG_JACKMONA_HOUR', 3),
            0,
            23,
            1,
            help_="When the day's two episodes are built. 03:00 by default — the pair is about an "
            'hour of GPU and this way it never competes with work anyone is watching.',
        ),
    ],
    'preempt': [
        _f(
            'documentary_target',
            'Documentary episodes to pre-build',
            'number',
            100,
            0,
            500,
            1,
            help_='Brain-only runs (every text Claude call recorded, no rendering) until this many are banked.',
        ),
        _f(
            'songs_target',
            "Children's song briefs to pre-pick",
            'number',
            100,
            0,
            500,
            1,
            help_='The song workflow makes no Claude calls; this only pre-picks briefs so 100 songs are queued.',
        ),
        _f(
            'concurrency',
            'Recordings at once',
            'number',
            20,
            1,
            60,
            1,
            help_='Brain runs in parallel. Measured 2026-09-23: ~1 GB RAM each (a headless CLI peaks at 610 MB) '
            'and a recording holds no GPU, so the ceiling is RAM — about 45 on a 63 GB box with the usual '
            'services up. The gate holds a new start when free RAM would drop under 8 GB.',
        ),
        _f(
            'quota_ceiling_pct',
            'Stop building at quota %',
            'number',
            90,
            50,
            100,
            1,
            help_='No new brain run is started once the 5-hour or 7-day window is at or above this. Resumes after the reset.',
        ),
        _f(
            'live_when_exhausted',
            'Live Claude calls during replay',
            'select',
            'auto',
            options=[
                ['auto', 'Auto — only while the meter shows quota left'],
                ['never', 'Never — replayed answers and local fallbacks only'],
                ['always', 'Always — try Claude for every unrecorded call'],
            ],
            help_='What a production run does for a call that has no recorded answer (image judges, drift).',
        ),
    ],
}


def _load() -> dict:
    with _LOCK:
        try:
            mt = os.path.getmtime(PATH)
        except OSError:
            _CACHE.update(mtime=None, data={})
            return {}
        if _CACHE['mtime'] == mt:
            return _CACHE['data']
        try:
            with open(PATH, encoding='utf-8') as fh:
                data = json.load(fh) or {}
        except (OSError, ValueError):
            data = {}
        _CACHE.update(mtime=mt, data=data if isinstance(data, dict) else {})
        return _CACHE['data']


def _save(data: dict) -> None:
    with _LOCK:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, PATH)
        _CACHE.update(mtime=None)


def _field(wf: str, key: str) -> dict | None:
    for f in SCHEMA.get(wf, []):
        if f['key'] == key:
            return f
    return None


def _coerce(f: dict, value):
    """Validate one value against its field. Raises ValueError."""
    t = f['type']
    if t == 'bool':
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(value)
    if t == 'number':
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{f["key"]}: not a number') from exc
        if f['min'] is not None and v < f['min']:
            raise ValueError(f'{f["key"]}: below {f["min"]}')
        if f['max'] is not None and v > f['max']:
            raise ValueError(f'{f["key"]}: above {f["max"]}')
        return int(v) if float(v).is_integer() and isinstance(f['default'], int) else v
    if t == 'select':
        allowed = [o[0] for o in f['options']]
        if value not in allowed:
            raise ValueError(f'{f["key"]}: must be one of {allowed}')
        return value
    raise ValueError(f'{f["key"]}: unknown field type')


def get(wf: str, key: str):
    f = _field(wf, key)
    if f is None:
        raise KeyError(f'{wf}.{key}')
    saved = _load().get(wf) or {}
    if key in saved:
        try:
            return _coerce(f, saved[key])
        except ValueError as _exc:
            _zyg_log.warning('saved value for %s.%s is invalid, using the default: %s', wf, key, _exc)
    return f['default']


def all_values(wf: str) -> dict:
    return {f['key']: get(wf, f['key']) for f in SCHEMA.get(wf, [])}


def fields(wf: str) -> list:
    out = []
    for f in SCHEMA.get(wf, []):
        row = {k: f[k] for k in ('key', 'label', 'type', 'min', 'max', 'step', 'options', 'help')}
        row['value'] = get(wf, f['key'])
        row['default'] = f['default']
        out.append(row)
    return out


def update(wf: str, changes: dict) -> dict:
    """Validate every change first, then save all of them. Returns the new values."""
    if wf not in SCHEMA:
        raise KeyError(wf)
    clean = {}
    for k, v in (changes or {}).items():
        f = _field(wf, k)
        if f is None:
            raise ValueError(f'unknown setting {k}')
        clean[k] = _coerce(f, v)
    with _LOCK:
        data = dict(_load())
        sec = dict(data.get(wf) or {})
        sec.update(clean)
        data[wf] = sec
        _save(data)
    return all_values(wf)
