# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_vicky.ledger — the append-only conversation ledger and the partial-answer spool.

Lines 493-691 of the original medusa_vicky.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from __future__ import annotations

import json
import os
import time
import logging as _zyg_logging

from .constants import (
    CONV_DIR,
    PARTIAL_DIR,
    PARTIAL_FLUSH_CHARS,
    PARTIAL_FLUSH_S,
    _CLOCK,
)

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── conversation ledger ───────────────────────────────────────────────────────
# Every request is written to disk twice: a `start` line the moment the job
# exists, an `end` line when it finishes. A start without an end means the
# process died under it (a medusa.service restart kills the CLI with it) —
# _close_orphans() runs at import and writes those `end` lines with status
# "killed", so the ledger never has a silent hole.
def _conv_path(day: str = '') -> str:
    return os.path.join(CONV_DIR, (day or time.strftime('%Y-%m-%d')) + '.jsonl')


def _conv_write(entry: dict) -> None:
    try:
        os.makedirs(CONV_DIR, exist_ok=True)
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), **entry}
        with _CLOCK:
            with open(_conv_path(), 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[medusa_vicky] ledger write failed: {e!r}')


def _partial_path(jid: str) -> str:
    return os.path.join(PARTIAL_DIR, f'{jid}.txt')


def _partial_write(job: dict, force: bool = False) -> None:
    """Mirror the in-flight thinking block to disk, throttled, so a restart
    cannot take it — rewritten whole via a tmp + os.replace so a reader never
    sees a half-written file."""
    jid = str(job.get('id') or '')
    txt = job.get('_think') or ''
    if not jid or not txt:
        return
    now = time.time()
    if (
        not force
        and (now - float(job.get('_pflush') or 0)) < PARTIAL_FLUSH_S
        and (len(txt) - int(job.get('_pflushed') or 0)) < PARTIAL_FLUSH_CHARS
    ):
        return
    try:
        os.makedirs(PARTIAL_DIR, exist_ok=True)
        head = json.dumps({'id': jid, 't0': job.get('_blk_t0'), 'n': len(job.get('thoughts') or []) + 1})
        tmp = _partial_path(jid) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(head + '\n' + txt)
        os.replace(tmp, _partial_path(jid))
        job['_pflush'], job['_pflushed'] = now, len(txt)
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[medusa_vicky] partial thought write failed: {e!r}')


def _partial_clear(job_or_id) -> None:
    is_job = isinstance(job_or_id, dict)
    jid = str((job_or_id.get('id') if is_job else job_or_id) or '')
    if is_job:
        job_or_id['_pflush'] = job_or_id['_pflushed'] = 0
    if not jid:
        return
    for f in (_partial_path(jid), _partial_path(jid) + '.tmp'):
        try:
            os.remove(f)
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _partial_read(jid: str) -> dict | None:
    f = _partial_path(jid)
    try:
        with open(f, encoding='utf-8') as fh:
            head, _, text = fh.read().partition('\n')
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        meta = json.loads(head)
    except ValueError:
        meta = {}
    secs = 0.0
    try:
        if meta.get('t0'):
            secs = round(max(0.0, os.path.getmtime(f) - float(meta['t0'])), 1)
    except (OSError, TypeError, ValueError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return {'s': secs, 'text': text, 'partial': True}


def _partial_sweep(folded=()) -> None:
    folded = set(folded or ())
    try:
        for f in os.listdir(PARTIAL_DIR):
            p = os.path.join(PARTIAL_DIR, f)
            try:
                stale = (time.time() - os.path.getmtime(p)) > 2 * 86400
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if f[:-4] in folded or f[:-8] in folded or stale:
                try:
                    os.remove(p)
                except OSError as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _conv_start(job: dict) -> None:
    body = job.get('body') or {}
    _conv_write(
        {
            'event': 'start',
            'id': job['id'],
            'text': str(body.get('text') or '')[:4000],
            'engine': job.get('engine'),
            'chat': job.get('chat'),
            'session_in': str(body.get('session') or '') or None,
        }
    )


def _conv_end(job: dict) -> None:
    _partial_clear(job)
    _conv_write(
        {
            'event': 'end',
            'id': job['id'],
            'status': job.get('status'),
            'elapsed': round(time.time() - job['t0'], 1),
            'engine': job.get('engine'),
            'model': job.get('model'),
            'session': job.get('session'),
            'auth': job.get('auth'),
            'steps': job.get('steps'),
            'usage': job.get('usage'),
            'think_s': job.get('think_s'),
            'thoughts': [{'s': t.get('s'), 'text': str(t.get('text') or '')} for t in (job.get('thoughts') or [])],
            'reply': str(job.get('reply') or ''),
            'error': job.get('error'),
            'log': job.get('log', []),
        }
    )


def _close_orphans() -> int:
    """Start lines without an end line (today and yesterday) get an `end` with
    status 'killed'. Runs when the module loads, i.e. after every restart."""
    n = 0
    folded = []
    try:
        days = [time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400 * k)) for k in (1, 0)]
        for day in days:
            p = _conv_path(day)
            if not os.path.exists(p):
                continue
            starts, ends, thoughts = {}, set(), {}
            with open(p, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except ValueError as _exc:
                        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                        continue
                    if e.get('event') == 'start':
                        starts[e.get('id')] = e
                    elif e.get('event') == 'end':
                        ends.add(e.get('id'))
                    elif e.get('event') == 'thought':
                        thoughts.setdefault(e.get('id'), []).append({'s': e.get('s'), 'text': e.get('text') or ''})
            for jid, e in starts.items():
                if jid in ends:
                    continue
                th = list(thoughts.get(jid) or [])
                part = _partial_read(jid)
                if part:
                    th.append(part)
                    folded.append(jid)
                _conv_write(
                    {
                        'event': 'end',
                        'id': jid,
                        'status': 'killed',
                        'started': e.get('ts'),
                        'day': day,
                        'error': 'the server restarted (or crashed) while Vicky was working — the CLI died with it',
                        'text': e.get('text', ''),
                        'partial_thought': bool(part),
                        'thoughts': th,
                        'think_s': round(sum(float(t.get('s') or 0) for t in th), 1),
                    }
                )
                n += 1
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[medusa_vicky] orphan close failed: {e!r}')
    _partial_sweep(folded)
    if n:
        _zyg_log.info(f'[medusa_vicky] ledger: closed {n} conversation(s) killed by the last restart')
    return n
