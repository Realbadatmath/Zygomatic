# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.injuries — injuries (operator enhancement 2026-08-07) and the continent filter.

Verbatim section of the original sports_ingest.py (lines 1333-1437); no logic changes.
"""

from __future__ import annotations

import re
import time

import requests

from zyg_workflows.sports_ingest.constants import _ASIA_AFRICA, _HDRS, _LOCK
from zyg_workflows.sports_ingest.thesportsdb import _name_key


# ── injuries (operator enhancement 2026-08-07) ──────────────────────────────
# ESPN's keyless injuries feed at site.web.api.espn.com, VERIFIED from this host
# 2026-08-07: NFL 32 teams / 800 entries, NBA 99, WNBA 30 — but EVERY soccer
# league (eng.1, esp.1, ita.1, ger.1, fra.1, ned.1, usa.1, bra.1, arg.1, por.1)
# answers 200 with ZERO entries, and site.api.espn.com (no `.web`) 403s outright.
# So injuries are real data for NFL/basketball episodes and honestly absent for
# soccer — the claims guard in briefing_jobs blocks the LLM from inventing them
# there. Soccer paths stay mapped so the day ESPN populates them we pick it up.

_ESPN_INJURIES_BASE = 'https://site.web.api.espn.com/apis/site/v2/sports'
_ESPN_LEAGUE = {
    'basketball_nba': 'basketball/nba',
    'basketball_wnba': 'basketball/wnba',
    'americanfootball_nfl': 'football/nfl',
    'americanfootball_nfl_preseason': 'football/nfl',
    'soccer_epl': 'soccer/eng.1',
    'soccer_spain_la_liga': 'soccer/esp.1',
    'soccer_italy_serie_a': 'soccer/ita.1',
    'soccer_germany_bundesliga': 'soccer/ger.1',
    'soccer_france_ligue_one': 'soccer/fra.1',
    'soccer_netherlands_eredivisie': 'soccer/ned.1',
    'soccer_portugal_primeira_liga': 'soccer/por.1',
    'soccer_usa_mls': 'soccer/usa.1',
    'soccer_brazil_campeonato': 'soccer/bra.1',
    'soccer_argentina_primera_division': 'soccer/arg.1',
}
_INJURY_CACHE: dict = {}  # {espn_path: {'ts', 'teams': {name_key: [...]}}}
_INJURY_TTL = 6 * 3600.0
# 'Active' means practising/playing — not an absence worth airtime.
_INJURY_KEEP = re.compile(
    r'out|doubtful|questionable|day.to.day|injured reserve|'
    r'suspension',
    re.I,
)


def _espn_injuries_for(espn_path: str) -> dict:
    with _LOCK:
        hit = _INJURY_CACHE.get(espn_path)
        if hit and (time.time() - hit['ts']) < _INJURY_TTL:
            return hit['teams']
    teams = {}
    try:
        r = requests.get(f'{_ESPN_INJURIES_BASE}/{espn_path}/injuries', headers=_HDRS, timeout=20)
        groups = (r.json() or {}).get('injuries') or [] if r.status_code == 200 else []
    except Exception:
        groups = []
    for g in groups:
        tname = g.get('displayName') or (g.get('team') or {}).get('displayName') or ''
        rows = []
        for e in g.get('injuries') or []:
            status = (e.get('status') or '').strip()
            if not _INJURY_KEEP.search(status):
                continue
            ath = e.get('athlete') or {}
            rows.append(
                {
                    'player': (ath.get('displayName') or '').strip(),
                    'status': status,
                    'detail': ((e.get('details') or {}).get('type') or '').strip(),
                }
            )
        if tname and rows:
            teams[_name_key(tname)] = rows[:4]
    with _LOCK:
        _INJURY_CACHE[espn_path] = {'ts': time.time(), 'teams': teams}
    return teams


def team_injuries(team_name: str, sport_key: str) -> list:
    """[{player, status, detail}] for a team, [] when the feed has nothing.

    Facts, not guesses: only ever returns what ESPN lists under a team whose
    name genuinely matches — a fuzzy hit on the wrong club would put a fake
    absence on air, which is exactly the class of error this build removes."""
    path = _ESPN_LEAGUE.get(sport_key or '')
    if not path:
        return []
    teams = _espn_injuries_for(path)
    if not teams:
        return []
    key = _name_key(team_name)
    if key in teams:
        return teams[key]
    for tk, rows in teams.items():
        if key and (key in tk or tk in key):
            return rows
    return []


def _is_excluded_continent(rec: dict) -> bool:
    """Only a HIGH-confidence lookup may exclude a fixture.

    A low-confidence match is a guess, and acting on a guess here deletes a real
    match from the card with no trace. "Pumas" resolved to a South African club
    on the first run — under the old code that would have quietly dropped a Liga
    MX fixture for being "African".
    """
    rec = rec or {}
    if rec.get('confidence') != 'high':
        return False
    c = rec.get('country', '').lower().strip()
    return bool(c) and c in _ASIA_AFRICA
