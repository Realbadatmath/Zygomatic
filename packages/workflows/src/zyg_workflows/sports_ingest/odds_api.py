# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.odds_api — Odds API with a credit ledger.

Verbatim section of the original sports_ingest.py (lines 392-552); no logic changes.
"""

from __future__ import annotations

import os
import re
import time
from datetime import timedelta

import requests

from zyg_workflows.sports_ingest.constants import (
    DEFAULT_LEAGUES,
    _HDRS,
    _LOCK,
    _ODDS_BASE,
    _ODDS_CACHE_DIR,
    _QUOTA_PATH,
    _zyg_log,
)
from zyg_workflows.sports_ingest.helpers import _iso, _load, _now_utc, _save, _z, settings, window_for


# ── Odds API with a credit ledger ───────────────────────────────────────────


def quota() -> dict:
    return _load(_QUOTA_PATH, {'remaining': None, 'used': None, 'month': '', 'spent_this_month': 0, 'last_call': ''})


def _note_quota(resp, cost_hint: int = 0) -> None:
    with _LOCK:
        q = quota()
        month = _now_utc().strftime('%Y-%m')
        if q.get('month') != month:
            q = {'month': month, 'spent_this_month': 0}
        try:
            last = int(resp.headers.get('x-requests-last') or 0)
        except (TypeError, ValueError):
            last = cost_hint
        q['spent_this_month'] = int(q.get('spent_this_month') or 0) + last
        for hdr, key in (('x-requests-remaining', 'remaining'), ('x-requests-used', 'used')):
            try:
                q[key] = int(resp.headers.get(hdr))
            except (TypeError, ValueError) as _exc:
                _zyg_log.warning('quota header %s unusable, %s left unrecorded: %s', hdr, key, _exc)
        q['last_call'] = _iso()
        _save(_QUOTA_PATH, q)


def credits_ok() -> 'tuple[bool, str]':
    s = settings()
    q = quota()
    cap = int(s.get('monthly_credit_cap') or 450)
    spent = int(q.get('spent_this_month') or 0)
    if q.get('month') == _now_utc().strftime('%Y-%m') and spent >= cap:
        return False, f'monthly Odds-API cap reached ({spent}/{cap} credits)'
    rem = q.get('remaining')
    if isinstance(rem, int) and rem <= 5:
        return False, f'Odds API key has {rem} credits left'
    return True, f'{spent}/{cap} credits used this month' + (f', {rem} left on the key' if isinstance(rem, int) else '')


def _odds_get(path, params, cost_hint=0, timeout=25):
    s = settings()
    p = dict(params or {})
    p['apiKey'] = (s.get('odds_api_key') or '').strip()
    if not p['apiKey']:
        _zyg_log.warning('no Odds API key — set ZYG_ODDS_API_KEY or odds_api_key in the settings; odds disabled')
        return None
    try:
        r = requests.get(f'{_ODDS_BASE}{path}', params=p, headers=_HDRS, timeout=timeout)
        _note_quota(r, cost_hint)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def active_sport_keys() -> list:
    """[{key,title,group,active}] — /sports costs 0 credits."""
    d = _odds_get('/sports/', {}, cost_hint=0)
    return d if isinstance(d, list) else []


def _keys_for(category: str) -> list:
    """Whitelisted, currently-active sport keys for a category."""
    s = settings()
    want = (s.get('leagues') or DEFAULT_LEAGUES).get(category) or []
    active = {k['key'] for k in active_sport_keys() if k.get('active')}
    if category == 'tennis':  # tournament keys rotate weekly → prefix match
        return sorted(k for k in active if any(k.startswith(p) for p in want))
    return [k for k in want if k in active]


def fetch_events(category: str, log=None, day_override: str = '') -> list:
    """All D+2 fixtures for a category. FREE — /events costs 0 credits."""
    utc_from, utc_to, day = window_for(day_override=day_override)
    out = []
    for key in _keys_for(category):
        d = _odds_get(
            f'/sports/{key}/events', {'commenceTimeFrom': _z(utc_from), 'commenceTimeTo': _z(utc_to)}, cost_hint=0
        )
        if not isinstance(d, list):
            continue
        for e in d:
            e['sport_key'] = key
            out.append(e)
        if log and d:
            log('INFO', f'{key}: {len(d)} fixture(s) on {day}')
        time.sleep(0.25)
    return out


def _odds_cache_path(sport_key: str, day: str) -> str:
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', f'{sport_key}_{day}')
    return os.path.join(_ODDS_CACHE_DIR, f'{safe}.json')


def fetch_odds(sport_key: str, log=None, day_override: str = '') -> list:
    """h2h decimal odds for one league inside the D+2 window. COSTS CREDITS.

    Cached per (league, match day) — WITHOUT this the free plan cannot survive a
    month. TokiToki and Arena research the SAME five categories for the SAME
    D+2 day, so an uncached build pays for every league twice: measured on the
    2026-08-08 card that is 11 credits per channel per day (soccer alone had 9
    live leagues), 22/day, ~660/month against a 500-credit plan — and more once
    the NBA, NFL and the tennis tour are all in season. One fetch, both channels.

    The trade is that the second channel quotes prices up to `odds_cache_hours`
    old. Every episode already says on screen and in the description that odds
    move and to check your own book before placing, and the two channels build
    about an hour apart. Set `odds_cache_hours` to 0 to always pay twice.
    """
    s = settings()
    utc_from, utc_to, day = window_for(day_override=day_override)
    path = _odds_cache_path(sport_key, day)
    ttl_h = float(s.get('odds_cache_hours') or 0)
    if ttl_h > 0:
        c = _load(path, None)
        try:
            fresh = c and (time.time() - float(c.get('ts') or 0)) < ttl_h * 3600
        except (TypeError, ValueError):
            fresh = False
        if fresh and isinstance(c.get('events'), list):
            if log:
                age_m = (time.time() - float(c['ts'])) / 60.0
                log('INFO', f'{sport_key}: odds served from cache ({age_m:.0f} min old) — 0 credits')
            return c['events']

    regions = (s.get('odds_regions') or 'eu').strip()
    d = _odds_get(
        f'/sports/{sport_key}/odds',
        {
            'regions': regions,
            'markets': 'h2h',
            'oddsFormat': 'decimal',
            'commenceTimeFrom': _z(utc_from),
            'commenceTimeTo': _z(utc_to),
        },
        cost_hint=len(regions.split(',')),
    )
    rows = d if isinstance(d, list) else []
    if rows and ttl_h > 0:
        _save(path, {'ts': time.time(), 'at': _iso(), 'day': day, 'sport_key': sport_key, 'events': rows})
    return rows


def sweep_odds_cache(keep_days: int = 3) -> int:
    """Drop cached odds for match days that have already been and gone."""
    cutoff = (_now_utc() - timedelta(days=max(1, keep_days))).date().isoformat()
    n = 0
    try:
        for fn in os.listdir(_ODDS_CACHE_DIR):
            m = re.search(r'(\d{4}-\d{2}-\d{2})\.json$', fn)
            if m and m.group(1) < cutoff:
                os.remove(os.path.join(_ODDS_CACHE_DIR, fn))
                n += 1
    except OSError as _exc:
        _zyg_log.debug('odds cache prune stopped after %s files: %s', n, _exc)
    return n
