# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.icebox_store — ice-box, social text and the published-bet history.

Verbatim section of the original sports_ingest.py (lines 2315-2439); no logic changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zyg_workflows.sports_ingest.constants import CATEGORIES, _HISTORY_PATH, _ICEBOX_PATH, _LOCAL_TZ, _LOCK, _zyg_log
from zyg_workflows.sports_ingest.helpers import _iso, _load, _now_utc, _save


# ── ice-box ─────────────────────────────────────────────────────────────────


def icebox() -> list:
    with _LOCK:
        return (_load(_ICEBOX_PATH, {}) or {}).get('items', [])


def icebox_add(bets: list, channel: str, category: str) -> int:
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        items = d.get('items') or []
        by_key = {(i.get('channel'), i.get('event_id')): i for i in items}
        for b in bets or []:
            by_key[(channel, b.get('event_id'))] = {
                'channel': channel,
                'category': category,
                'event_id': b.get('event_id'),
                'league': b.get('league'),
                'home': b.get('home'),
                'away': b.get('away'),
                'commence_time': b.get('commence_time'),
                'selection': b.get('selection'),
                'price': b.get('price'),
                'book': b.get('book'),
                'edge_pct': b.get('edge_pct'),
                'fair_prob': b.get('fair_prob'),
                'stake_pct': b.get('stake_pct'),
                'social_text': social_text(b, channel),
                'added_at': _iso(),
                'used': False,
                'used_at': '',
            }
        # a bet whose kick-off has passed is dead weight on the socials
        now = _now_utc()
        keep = []
        for i in by_key.values():
            try:
                ct = datetime.strptime((i.get('commence_time') or '')[:19], '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=timezone.utc
                )
                if ct < now - timedelta(hours=3):
                    continue
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('commence_time unparsable, icebox item kept: %s', _exc)
            keep.append(i)
        d['items'] = sorted(keep, key=lambda i: i.get('added_at', ''), reverse=True)[:80]
        _save(_ICEBOX_PATH, d)
        return len(bets or [])


def icebox_mark_used(channel: str, event_id: str) -> bool:
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        hit = False
        for i in d.get('items') or []:
            if i.get('channel') == channel and i.get('event_id') == event_id:
                i['used'] = True
                i['used_at'] = _iso()
                hit = True
        _save(_ICEBOX_PATH, d)
        return hit


def icebox_delete(channel: str, event_id: str) -> bool:
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        before = len(d.get('items') or [])
        d['items'] = [
            i for i in (d.get('items') or []) if not (i.get('channel') == channel and i.get('event_id') == event_id)
        ]
        _save(_ICEBOX_PATH, d)
        return len(d['items']) < before


def social_text(bet: dict, channel: str) -> str:
    emoji = (CATEGORIES.get(bet.get('category')) or {}).get('emoji', '🎯')
    try:
        ko = (
            datetime.strptime((bet.get('commence_time') or '')[:19], '%Y-%m-%dT%H:%M:%S')
            .replace(tzinfo=timezone.utc)
            .astimezone(_LOCAL_TZ)
            .strftime('%a %d %b %H:%M')
        )
    except Exception:
        ko = ''
    edge = bet.get('edge_pct') or 0
    return (
        f'{emoji} {bet.get("home")} vs {bet.get("away")}\n'
        f'{bet.get("league") or ""}{(" · " + ko) if ko else ""}\n'
        f'PICK: {bet.get("selection")} @ {bet.get("price")} ({bet.get("book")})\n'
        f'Model fair price {1 / float(bet.get("fair_prob") or 1):.2f} · '
        f'edge {edge:+.1f}% · suggested stake {bet.get("stake_pct")}% of bankroll\n'
        f'18+. Gamble responsibly. Free tips daily on {channel}.'
    )


def history_add(bets: list, channel: str, category: str, job_id: str) -> None:
    with _LOCK:
        d = _load(_HISTORY_PATH, {}) or {}
        rows = d.get('bets') or []
        for b in bets or []:
            rows.append(
                {
                    'at': _iso(),
                    'job_id': job_id,
                    'channel': channel,
                    'category': category,
                    'event_id': b.get('event_id'),
                    'league': b.get('league'),
                    'home': b.get('home'),
                    'away': b.get('away'),
                    'selection': b.get('selection'),
                    'price': b.get('price'),
                    'edge_pct': b.get('edge_pct'),
                    'commence_time': b.get('commence_time'),
                    'result': '',
                }
            )
        d['bets'] = rows[-3000:]
        _save(_HISTORY_PATH, d)


def history(limit: int = 120) -> list:
    return list(reversed((_load(_HISTORY_PATH, {}) or {}).get('bets', [])))[:limit]
