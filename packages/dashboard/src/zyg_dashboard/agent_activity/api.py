# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_dashboard.agent_activity.sampler import (
    _events,
    _gpu,
    _last_sample,
    _lock,
    _sample,
    _sampler_error,
    _seq,
    _sessions,
    start,
)
from zyg_dashboard.agent_activity.transcripts import _transcript_items
from zyg_dashboard.agent_activity.tunables import (
    _CPU_ACTIVE_CORES,
    _CPU_ACTIVE_PCT,
    _NCPU,
    _RAM_ACTIVE_MB,
    _SAMPLE_S,
    _VRAM_ACTIVE_MB,
    _iso,
    _now_iso,
)
import re
import time
from datetime import datetime

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


# ── Public API ──────────────────────────────────────────────────────────────
def snapshot(since: int = 0) -> dict:
    """Everything the Live Tail needs in one poll.

    ``since`` is the highest event ``seq`` the caller already has; only newer
    events come back, so the page can append instead of re-rendering (and can
    never double-log a line it has already shown).
    """
    start()
    if psutil is None:
        # Same SHAPE as a healthy payload, so a page rendering it hits real
        # zeroes instead of undefined fields — only `ok` says it is degraded.
        return {
            'ok': False,
            'error': 'psutil unavailable',
            'sessions': [],
            'events': [],
            'count': 0,
            'active': 0,
            'orphans': 0,
            'seq': 0,
            'as_of': _now_iso(),
            'sampled': '',
            'stale': True,
            'cpu_count': _NCPU,
            'gpu': {k: v for k, v in _gpu.items() if k != 'at'},
            'thresholds': {
                'cpu_cores': _CPU_ACTIVE_CORES,
                'cpu_pct': _CPU_ACTIVE_PCT,
                'vram_mb': _VRAM_ACTIVE_MB,
                'ram_mb': _RAM_ACTIVE_MB,
            },
        }
    # First call after boot: take a pass inline so the panel is never blank
    # while the 2 s sampler warms up.
    if not _last_sample:
        try:
            _sample()
            time.sleep(0.12)
            _sample()
        except Exception as _exc:
            _zyg_log.warning('inline warm-up sample failed, the activity panel starts empty: %s', _exc)
    with _lock:
        sessions = []
        for s in _sessions.values():
            sessions.append({k: v for k, v in s.items() if k != 'events'})
        sessions.sort(
            key=lambda x: (
                not x.get('active'),
                x.get('orphan', False),
                -(x.get('vram_mb') or 0),
                -(x.get('cpu_pct') or 0),
                x.get('name', ''),
            )
        )
        evs = [e for e in _events if e['seq'] > since]
        return {
            'ok': True,
            'as_of': _now_iso(),
            'sampled': _iso(_last_sample) if _last_sample else '',
            'stale': bool(_last_sample and time.time() - _last_sample > _SAMPLE_S * 6),
            'error': _sampler_error,
            'count': sum(1 for s in sessions if s.get('alive')),
            # THE BADGE NUMBER: live sessions measurably on the hardware.
            'active': sum(1 for s in sessions if s.get('active') and s.get('alive')),
            'orphans': sum(1 for s in sessions if s.get('orphan')),
            'sessions': sessions,
            'events': evs,
            'seq': _seq,
            'gpu': {k: v for k, v in _gpu.items() if k != 'at'},
            'cpu_count': _NCPU,
            'thresholds': {
                'cpu_cores': _CPU_ACTIVE_CORES,
                'cpu_pct': _CPU_ACTIVE_PCT,
                'vram_mb': _VRAM_ACTIVE_MB,
                'ram_mb': _RAM_ACTIVE_MB,
            },
        }


def session_tail(sid: str, limit: int = 120) -> dict:
    """One session's own Live Tail: its hardware events merged with its work.

    The two feeds answer different questions — the process events say what the
    box is doing, the transcript says what the agent asked for — and neither is
    readable without the other.  They are merged on timestamp.
    """
    start()
    if not re.match(r'^[0-9a-fA-F-]{8,40}$', sid or ''):
        return {'error': 'bad session id'}
    with _lock:
        s = _sessions.get(sid)
        base = {k: v for k, v in (s or {}).items() if k != 'events'}
        own = list((s or {}).get('events') or [])
    lines = [{'ts': e['ts'], 'level': e['level'], 'kind': e['kind'], 'text': e['text']} for e in own]
    for it in _transcript_items(sid, limit):
        lines.append({'ts': it['ts'], 'level': it['level'], 'kind': 'work', 'text': it['text']})

    def _key(ln):
        t = ln.get('ts') or ''
        # Transcript stamps are UTC 'Z'; event stamps carry a local offset.
        try:
            return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
        except Exception:
            return 0.0

    lines.sort(key=_key)
    if not base:
        base = {'id': sid, 'short': sid[:8], 'name': sid[:8], 'alive': False}
    base['lines'] = lines[-limit:]
    base['as_of'] = _now_iso()
    return base
