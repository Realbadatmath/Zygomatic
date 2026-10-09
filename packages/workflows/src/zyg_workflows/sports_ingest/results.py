# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.results — recent results + head-to-head (operator request 2026-08-08).

Verbatim section of the original sports_ingest.py (lines 1774-2089); no logic changes.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

import requests

from zyg_workflows.sports_ingest.constants import _HDRS, _LOCAL_TZ, _LOCK, _RUNTIME, _zyg_log
from zyg_workflows.sports_ingest.helpers import _now_utc
from zyg_workflows.sports_ingest.thesportsdb import _name_key, _norm_name


# ── recent results + head-to-head (operator request 2026-08-08) ─────────────
# "previous matches vs each other are a good indicator, also individual former
# 10 matches results matter, opponents faced in last 10 matches also matter."
# VERIFIED SOURCES (measured from this host 2026-08-08, all keyless):
#   soccer — football-data.co.uk: new/BRA|ARG|USA.csv (calendar-year, fresh to
#     within days) + mmz4281/<season>/<code>.csv for the European leagues
#     (26/27 files appear once those seasons start; last season's file carries
#     the history until then). API-Sports CANNOT do this on the free plan
#     (blocks the Last parameter AND current seasons — measured).
#   tennis — tennis-data.co.uk/<year>/<year>.xlsx (ATP) and /<year>w/ (WTA),
#     current files exist for 2026. NO match-duration column — time-on-court /
#     fatigue has no free source; deferred until one exists.
# TheSportsDB eventslast is capped at ONE row on the free key (measured) — dead
# end for form. These are result FACTS derived from freely published data; the
# CSVs themselves are not republished.

_RESULTS_CACHE_DIR = os.path.join(_RUNTIME, 'sports_results_cache')
_RESULTS_TTL = 12 * 3600.0
_FD_BASE = 'https://www.football-data.co.uk'
_FD_EURO = {
    'soccer_epl': 'E0',
    'soccer_spain_la_liga': 'SP1',
    'soccer_italy_serie_a': 'I1',
    'soccer_germany_bundesliga': 'D1',
    'soccer_france_ligue_one': 'F1',
    'soccer_netherlands_eredivisie': 'N1',
    'soccer_portugal_primeira_liga': 'P1',
    'soccer_belgium_first_div': 'B1',
    'soccer_spl': 'SC0',
}
_FD_NEW = {
    'soccer_brazil_campeonato': 'BRA',
    'soccer_argentina_primera_division': 'ARG',
    'soccer_usa_mls': 'USA',
}
_RESULTS_MEM: dict = {}


def _http_cached(url: str, key: str):
    """Bytes from url, disk-cached for _RESULTS_TTL. None on failure (and a
    stale copy is better than nothing, so failures fall back to it)."""
    os.makedirs(_RESULTS_CACHE_DIR, exist_ok=True)
    p = os.path.join(_RESULTS_CACHE_DIR, re.sub(r'[^A-Za-z0-9._-]', '_', key))
    try:
        if os.path.isfile(p) and (time.time() - os.path.getmtime(p)) < _RESULTS_TTL:
            with open(p, 'rb') as f:
                return f.read()
    except OSError as _exc:
        _zyg_log.debug('results cache %s unreadable, fetching instead: %s', p, _exc)
    try:
        r = requests.get(url, headers=_HDRS, timeout=30)
        if r.status_code == 200 and len(r.content) > 500:
            tmp = p + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(r.content)
            os.replace(tmp, p)
            return r.content
    except Exception as _exc:
        _zyg_log.warning('results fetch from %s failed, falling back to the stale cache: %s', url, _exc)
    try:
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                return f.read()
    except OSError as _exc:
        _zyg_log.debug('stale results cache %s unreadable: %s', p, _exc)
    return None


def _euro_season_codes() -> list:
    """['2627', '2526']-style codes: current European season first, previous as
    history (the new season's file 404s until its first matches are played)."""
    now = _now_utc().astimezone(_LOCAL_TZ)
    y = now.year % 100
    if now.month >= 7:
        cur = f'{y:02d}{(y + 1) % 100:02d}'
        prev = f'{(y - 1) % 100:02d}{y:02d}'
    else:
        cur = f'{(y - 1) % 100:02d}{y:02d}'
        prev = f'{(y - 2) % 100:02d}{(y - 1) % 100:02d}'
    return [cur, prev]


def _parse_fd_csv(raw: bytes) -> list:
    import csv as _csv
    import io as _io

    out = []
    try:
        rows = list(_csv.DictReader(_io.StringIO(raw.decode('utf-8', 'replace'))))
    except Exception:
        return out
    for r in rows:
        r = {(k or '').lstrip('﻿').strip(): v for k, v in r.items() if k}
        home = (r.get('Home') or r.get('HomeTeam') or '').strip()
        away = (r.get('Away') or r.get('AwayTeam') or '').strip()
        hg = r.get('HG') if r.get('HG') not in (None, '') else r.get('FTHG')
        ag = r.get('AG') if r.get('AG') not in (None, '') else r.get('FTAG')
        ds = (r.get('Date') or '').strip()
        if not home or not away or hg in (None, '') or ag in (None, ''):
            continue
        dt = None
        for fmt in ('%d/%m/%Y', '%d/%m/%y'):
            try:
                dt = datetime.strptime(ds, fmt)
                break
            except ValueError as _exc:
                _zyg_log.debug('date %r does not match %s: %s', ds, fmt, _exc)
                continue
        if dt is None:
            continue
        try:
            out.append({'date': dt, 'home': home, 'away': away, 'hg': int(float(hg)), 'ag': int(float(ag))})
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('match row with unusable scores skipped: %s', _exc)
            continue
    out.sort(key=lambda m: m['date'])
    return out


def _fd_matches(sport_key: str) -> list:
    """All finished matches for a competition's data source, oldest→newest."""
    with _LOCK:
        hit = _RESULTS_MEM.get(sport_key)
        if hit and (time.time() - hit['ts']) < _RESULTS_TTL:
            return hit['rows']
    rows = []
    if sport_key in _FD_NEW:
        raw = _http_cached(f'{_FD_BASE}/new/{_FD_NEW[sport_key]}.csv', f'fd_{_FD_NEW[sport_key]}.csv')
        if raw:
            rows = _parse_fd_csv(raw)
    elif sport_key in _FD_EURO:
        code = _FD_EURO[sport_key]
        for season in reversed(_euro_season_codes()):  # old first
            raw = _http_cached(f'{_FD_BASE}/mmz4281/{season}/{code}.csv', f'fd_{season}_{code}.csv')
            if raw:
                rows.extend(_parse_fd_csv(raw))
        rows.sort(key=lambda m: m['date'])
    with _LOCK:
        _RESULTS_MEM[sport_key] = {'ts': time.time(), 'rows': rows}
    return rows


def _fd_team_name(rows: list, want: str) -> str:
    """The CSV's spelling of `want`, '' when no unambiguous match."""
    names = {m['home'] for m in rows} | {m['away'] for m in rows}
    key = _name_key(want)
    for n in names:
        if _name_key(n) == key:
            return n
    part = [n for n in names if key and (_name_key(n) in key or key in _name_key(n))]
    return part[0] if len(part) == 1 else ''


def recent_results(team: str, sport_key: str, n: int = 10) -> list:
    """Last `n` finished matches for a team, newest first:
    [{date, opp, venue 'H'/'A', res 'W'/'D'/'L', gf, ga}]. [] when unknown."""
    rows = _fd_matches(sport_key or '')
    if not rows:
        return []
    nm = _fd_team_name(rows, team)
    if not nm:
        return []
    out = []
    for m in reversed(rows):
        if m['home'] == nm:
            gf, ga, venue, opp = m['hg'], m['ag'], 'H', m['away']
        elif m['away'] == nm:
            gf, ga, venue, opp = m['ag'], m['hg'], 'A', m['home']
        else:
            continue
        out.append(
            {
                'date': m['date'].strftime('%Y-%m-%d'),
                'opp': opp,
                'venue': venue,
                'gf': gf,
                'ga': ga,
                'res': 'W' if gf > ga else ('D' if gf == ga else 'L'),
            }
        )
        if len(out) >= n:
            break
    return out


def h2h_results(home: str, away: str, sport_key: str, n: int = 10) -> dict:
    """Past meetings between the two sides, newest first. {} when unknown."""
    rows = _fd_matches(sport_key or '')
    if not rows:
        return {}
    nh, na = _fd_team_name(rows, home), _fd_team_name(rows, away)
    if not nh or not na or nh == na:
        return {}
    meets = [m for m in reversed(rows) if {m['home'], m['away']} == {nh, na}][:n]
    if not meets:
        return {}
    w_home = sum(1 for m in meets if (m['hg'] > m['ag']) == (m['home'] == nh) and m['hg'] != m['ag'])
    draws = sum(1 for m in meets if m['hg'] == m['ag'])
    return {
        'meetings': [
            {'date': m['date'].strftime('%Y-%m-%d'), 'home': m['home'], 'away': m['away'], 'hg': m['hg'], 'ag': m['ag']}
            for m in meets
        ],
        'w_home': w_home,
        'w_away': len(meets) - w_home - draws,
        'draws': draws,
    }


# tennis: tennis-data.co.uk yearly workbooks (ATP + WTA). Names are
# "Sabalenka A." style — matched on surname + first initial.


def _tennis_rows(sport_key: str) -> list:
    src = (
        'atp'
        if (sport_key or '').startswith('tennis_atp')
        else 'wta'
        if (sport_key or '').startswith('tennis_wta')
        else ''
    )
    if not src:
        return []
    ck = f'tennis_{src}'
    with _LOCK:
        hit = _RESULTS_MEM.get(ck)
        if hit and (time.time() - hit['ts']) < _RESULTS_TTL:
            return hit['rows']
    year = _now_utc().astimezone(_LOCAL_TZ).year
    sub = f'{year}' if src == 'atp' else f'{year}w'
    raw = _http_cached(f'http://www.tennis-data.co.uk/{sub}/{year}.xlsx', f'td_{src}_{year}.xlsx')
    rows = []
    if raw:
        try:
            import io as _io
            import openpyxl as _px

            wb = _px.load_workbook(_io.BytesIO(raw), read_only=True)
            ws = wb[wb.sheetnames[0]]
            it = ws.iter_rows(values_only=True)
            hdr = [str(c or '').strip() for c in next(it)]
            idx = {k: hdr.index(k) for k in ('Date', 'Winner', 'Loser') if k in hdr}
            if len(idx) == 3:
                for r in it:
                    try:
                        d = r[idx['Date']]
                        w = str(r[idx['Winner']] or '').strip()
                        l = str(r[idx['Loser']] or '').strip()
                    except IndexError as _exc:
                        _zyg_log.debug('csv row is missing a column, skipped: %s', _exc)
                        continue
                    if d is None or not w or not l:
                        continue
                    if not hasattr(d, 'strftime'):
                        continue
                    rows.append({'date': d, 'winner': w, 'loser': l})
            rows.sort(key=lambda m: m['date'])
        except Exception as _te:
            _zyg_log.info(f'[SPORTS-RESULTS] tennis workbook parse failed ({_te!r})')
    with _LOCK:
        _RESULTS_MEM[ck] = {'ts': time.time(), 'rows': rows}
    return rows


def _tennis_match_name(rows: list, want: str) -> str:
    """tennis-data spells players 'Sabalenka A.' — match surname + initial."""
    toks = _norm_name(want).split()
    if not toks:
        return ''
    first, last = toks[0], toks[-1]
    lk = _name_key(last)
    names = {m['winner'] for m in rows} | {m['loser'] for m in rows}
    hits = [n for n in names if _name_key(n.split()[0] if n else '') == lk or (lk and lk in _name_key(n))]
    hits = [n for n in hits if not first or (n.split()[-1][:1].lower() == first[:1].lower() if n.split() else True)]
    return hits[0] if len(hits) == 1 else ''


def player_recent_results(player: str, sport_key: str, n: int = 10) -> list:
    rows = _tennis_rows(sport_key)
    if not rows:
        return []
    nm = _tennis_match_name(rows, player)
    if not nm:
        return []
    out = []
    for m in reversed(rows):
        if m['winner'] == nm:
            out.append({'date': m['date'].strftime('%Y-%m-%d'), 'opp': m['loser'], 'res': 'W'})
        elif m['loser'] == nm:
            out.append({'date': m['date'].strftime('%Y-%m-%d'), 'opp': m['winner'], 'res': 'L'})
        else:
            continue
        if len(out) >= n:
            break
    return out


def player_h2h(a: str, b: str, sport_key: str, n: int = 10) -> dict:
    rows = _tennis_rows(sport_key)
    if not rows:
        return {}
    na, nb = _tennis_match_name(rows, a), _tennis_match_name(rows, b)
    if not na or not nb or na == nb:
        return {}
    meets = [m for m in reversed(rows) if {m['winner'], m['loser']} == {na, nb}][:n]
    if not meets:
        return {}
    w_a = sum(1 for m in meets if m['winner'] == na)
    return {
        'meetings': [{'date': m['date'].strftime('%Y-%m-%d'), 'winner': m['winner']} for m in meets],
        'w_home': w_a,
        'w_away': len(meets) - w_a,
        'draws': 0,
    }
