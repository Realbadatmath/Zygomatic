# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.photos — API-Sports player photos and ESPN roster headshots.

Verbatim section of the original sports_ingest.py (lines 1114-1332); no logic changes.
"""

from __future__ import annotations

import os
import time

import requests

from zyg_workflows.sports_ingest.constants import _HDRS, _LOCK, _NEG_TTL, _RUNTIME, _zyg_log
from zyg_workflows.sports_ingest.helpers import _iso, _load, _now_utc, _save, settings
from zyg_workflows.sports_ingest.thesportsdb import (
    _name_key,
    _norm_name,
    _team_cache,
    _team_cache_put,
    _variant_mismatch,
)
from zyg_workflows.sports_ingest.injuries import _ESPN_INJURIES_BASE, _ESPN_LEAGUE


# ── API-Sports player photos (operator key 2026-08-08) ──────────────────────
# The legitimate "massive library": the free plan is a subscription whose terms
# grant use of data AND media with attribution, unlike SofaScore/Transfermarkt
# (agency-owned photos, scraping prohibited — assessed and rejected 2026-08-08).
# VERIFIED from this host: /players/squads returns the CURRENT 36-man squad
# with per-player photo PNGs (media.api-sports.io), and the squad doubles as a
# membership check — a TheSportsDB cutout of a player who has TRANSFERRED AWAY
# simply is not in it. Each sport API has its own 100/day quota; ledger below
# fails closed at `apisports_daily_cap`. Burst limit is 10/min → gentle pacing.
_APISPORTS_HOSTS = {
    'soccer': ('football', 'https://v3.football.api-sports.io'),
    # basketball / american-football answer on this key too (verified /status);
    # wire their photo endpoints here once their responses are probed.
}
_APISPORTS_QUOTA_PATH = os.path.join(_RUNTIME, 'sports_apisports_quota.json')
_APISPORTS_TTL = 7 * 86400.0


def _apisports_quota() -> dict:
    return _load(_APISPORTS_QUOTA_PATH, {})


def _apisports_note(sport: str, remaining) -> None:
    with _LOCK:
        q = _apisports_quota()
        day = _now_utc().strftime('%Y-%m-%d')
        if q.get('date') != day:
            q = {'date': day}
        rec = q.get(sport) or {}
        rec['used'] = int(rec.get('used') or 0) + 1
        try:
            rec['remaining'] = int(remaining)
        except (TypeError, ValueError) as _exc:
            _zyg_log.warning('api-sports remaining header %r unusable, quota left unrecorded: %s', remaining, _exc)
        rec['last_call'] = _iso()
        q[sport] = rec
        _save(_APISPORTS_QUOTA_PATH, q)


def _apisports_get(category: str, path: str, params: dict):
    sport, base = _APISPORTS_HOSTS.get(category) or (None, None)
    if not base:
        return None
    s = settings()
    key = (s.get('apisports_key') or '').strip()
    if not key:
        _zyg_log.warning(
            'no API-Sports key — set ZYG_APISPORTS_API_KEY or apisports_key in the settings; API-Sports disabled'
        )
        return None
    q = _apisports_quota()
    cap = int(s.get('apisports_daily_cap') or 90)
    day = _now_utc().strftime('%Y-%m-%d')
    used = int((q.get(sport) or {}).get('used') or 0) if q.get('date') == day else 0
    if used >= cap:
        return None  # fail closed under the daily quota
    try:
        r = requests.get(f'{base}{path}', params=params, headers={'x-apisports-key': key}, timeout=20)
        _apisports_note(sport, r.headers.get('x-ratelimit-requests-remaining'))
        time.sleep(0.6)  # 10-requests/min burst limit
        if r.status_code != 200:
            return None
        d = r.json()
        return d.get('response') if isinstance(d, dict) else None
    except Exception:
        return None


def _apisports_team_id(category: str, team_name: str) -> str:
    ck = f'apisports_team::{category}::{_name_key(team_name)}'
    cache = _team_cache()
    hit = cache.get(ck)
    if hit:
        try:
            if (time.time() - float(hit.get('ts') or 0)) < (_APISPORTS_TTL if hit.get('id') else _NEG_TTL):
                return hit.get('id') or ''
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('cached api-sports team id has an unusable ts, refetching: %s', _exc)
    rows = _apisports_get(category, '/teams', {'search': _norm_name(team_name)}) or []
    key = _name_key(team_name)
    tid = ''
    best = None
    for r in rows:
        t = r.get('team') or {}
        tk = _name_key(t.get('name') or '')
        if tk == key:
            best = t
            break
        if best is None and tk and (key in tk or tk in key) and not _variant_mismatch(key, tk):
            best = t
    if best:
        tid = str(best.get('id') or '')
    _team_cache_put(ck, {'ts': time.time(), 'id': tid})
    return tid


def apisports_squad(category: str, team_name: str) -> dict:
    """{player_name_key: {'name', 'photo'}} for the CURRENT squad, {} unknown."""
    if category not in _APISPORTS_HOSTS:
        return {}
    tid = _apisports_team_id(category, team_name)
    if not tid:
        return {}
    ck = f'apisports_squad::{category}::{tid}'
    cache = _team_cache()
    hit = cache.get(ck)
    if hit:
        try:
            if (time.time() - float(hit.get('ts') or 0)) < (_APISPORTS_TTL if hit.get('squad') else _NEG_TTL):
                return hit.get('squad') or {}
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('cached squad has an unusable ts, refetching: %s', _exc)
    rows = _apisports_get(category, '/players/squads', {'team': tid}) or []
    squad = {}
    for p in (rows[0].get('players') if rows else []) or []:
        nm = (p.get('name') or '').strip()
        if nm:
            squad[_name_key(nm)] = {'name': nm, 'photo': p.get('photo') or ''}
    _team_cache_put(ck, {'ts': time.time(), 'squad': squad})
    return squad


def _squad_lookup(squad: dict, player_name: str) -> dict:
    """Squad row for a (possibly differently-spelled) player name, {} if absent."""
    key = _name_key(player_name)
    if key in squad:
        return squad[key]
    hits = [v for k, v in squad.items() if key and (key in k or k in key)]
    if len(hits) == 1:
        return hits[0]
    # last-name + first-initial ("F. Jonatan" style entries)
    toks = key.split()
    if toks:
        last, first = toks[-1], toks[0]
        hits = [
            v
            for k, v in squad.items()
            if k.split() and k.split()[-1] == last and (len(last) > 3) and k[:1] == first[:1]
        ]
        if len(hits) == 1:
            return hits[0]
    return {}


# ── ESPN roster headshots (second artwork site, operator 2026-08-07) ────────
# "retrieve those players from other sites where they do walk in the correct
# shirt". ESPN's keyless roster feed serves current-season headshot PNGs —
# coverage measured 2026-08-07: PEC Zwolle 11/22, Real Salt Lake 9/36, Brazil
# and Argentina ≈ 0 — so this is a FALLBACK for stale TheSportsDB art, not a
# replacement. Team match must be exact-or-unambiguous: a loose match turned
# "Independiente" into "Independiente Rivadavia" in the probe.
_ESPN_TEAMS_CACHE: dict = {}
_ESPN_ROSTER_CACHE: dict = {}
_ESPN_ART_TTL = 7 * 86400.0


def _espn_get(url):
    try:
        r = requests.get(url, headers=_HDRS, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _espn_team_id(espn_path: str, team_name: str) -> str:
    with _LOCK:
        hit = _ESPN_TEAMS_CACHE.get(espn_path)
    if not hit or (time.time() - hit['ts']) > _ESPN_ART_TTL:
        d = _espn_get(f'{_ESPN_INJURIES_BASE}/{espn_path}/teams')
        teams = {}
        try:
            rows = d['sports'][0]['leagues'][0]['teams']
        except (TypeError, KeyError, IndexError):
            rows = []
        for t in rows:
            tt = t.get('team') or {}
            if tt.get('id') and tt.get('displayName'):
                teams[_name_key(tt['displayName'])] = str(tt['id'])
        hit = {'ts': time.time(), 'teams': teams}
        with _LOCK:
            _ESPN_TEAMS_CACHE[espn_path] = hit
    key = _name_key(team_name)
    if key in hit['teams']:
        return hit['teams'][key]
    partial = [tid for tk, tid in hit['teams'].items() if key and (key in tk or tk in key)]
    return partial[0] if len(partial) == 1 else ''  # ambiguous → honest miss


def espn_headshot(team_name: str, category: str, sport_key: str, player_name: str) -> str:
    """Current-season headshot URL for a player, '' when ESPN has nothing."""
    if category != 'soccer' and not sport_key.startswith(('basketball', 'americanfootball')):
        return ''
    path = _ESPN_LEAGUE.get(sport_key or '')
    if not path:
        return ''
    tid = _espn_team_id(path, team_name)
    if not tid:
        return ''
    ck = f'{path}::{tid}'
    with _LOCK:
        hit = _ESPN_ROSTER_CACHE.get(ck)
    if not hit or (time.time() - hit['ts']) > _ESPN_ART_TTL:
        d = _espn_get(f'{_ESPN_INJURIES_BASE}/{path}/teams/{tid}/roster')
        roster = {}
        for a in (d or {}).get('athletes') or []:
            hs = (a.get('headshot') or {}).get('href') or ''
            nm = (a.get('displayName') or '').strip()
            if hs and nm:
                roster[_name_key(nm)] = hs
        hit = {'ts': time.time(), 'roster': roster}
        with _LOCK:
            _ESPN_ROSTER_CACHE[ck] = hit
    key = _name_key(player_name)
    if key in hit['roster']:
        return hit['roster'][key]
    partial = [u for pk, u in hit['roster'].items() if key and (key in pk or pk in key)]
    return partial[0] if len(partial) == 1 else ''
