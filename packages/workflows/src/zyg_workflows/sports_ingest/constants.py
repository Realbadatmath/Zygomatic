# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.constants — module docstring constants, paths, scope filters and DEFAULT_SETTINGS.

Verbatim section of the original sports_ingest.py (lines 60-303); no logic changes.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:  # pragma: no cover
    _LOCAL_TZ = timezone(timedelta(hours=2))
import logging as _zyg_logging

# SPLIT NOTE: was `getLogger(__name__)` in the single-file module; `__package__`
# keeps the logger name 'zyg_workflows.sports_ingest' exactly as before.
_zyg_log = _zyg_logging.getLogger(__package__)


# SPLIT NOTE: one extra dirname() — this module now sits one directory deeper
# than the old sports_ingest.py, so _CREWS still resolves to zyg_workflows/.
_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUNTIME = os.path.join(_CREWS, 'data', 'runtime')
_ART_DIR = os.path.join(_RUNTIME, 'sports_art')

_SETTINGS_PATH = os.path.join(_RUNTIME, 'sports_settings.json')
_ICEBOX_PATH = os.path.join(_RUNTIME, 'sports_icebox.json')
_HISTORY_PATH = os.path.join(_RUNTIME, 'sports_history.json')
_QUOTA_PATH = os.path.join(_RUNTIME, 'sports_quota.json')
_TEAMS_PATH = os.path.join(_RUNTIME, 'sports_teams.json')
_ODDS_CACHE_DIR = os.path.join(_RUNTIME, 'sports_odds_cache')

# TheSportsDB pacing. 0.3 s against the shared test key "3" got 80 of 110 club
# lookups rate-limited into permanent negative cache entries; 1.4 s resolves the
# same names cleanly. A miss is only remembered for _NEG_TTL so a bad minute can
# never cost a badge forever.
_TSDB_GAP = float(os.environ.get('ZYG_TSDB_GAP_S', '1.4') or 1.4)
_NEG_TTL = float(os.environ.get('ZYG_TSDB_NEG_TTL_S', '21600') or 21600)

_LOCK = threading.RLock()

_ODDS_BASE = 'https://api.the-odds-api.com/v4'
_TSDB_BASE = 'https://www.thesportsdb.com/api/v1/json'

_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
_HDRS = {'User-Agent': _UA, 'Accept': 'application/json,image/*,*/*'}

# The five categories, and how each one is presented on screen.
#   entity 'team'   → badge artwork, "Home vs Away"
#   entity 'player' → fighter/player cutout, "A vs B"
CATEGORIES = {
    'soccer': {'label': 'Soccer', 'entity': 'team', 'tsdb_sport': 'Soccer', 'emoji': '⚽'},
    'basketball': {'label': 'Basketball', 'entity': 'team', 'tsdb_sport': 'Basketball', 'emoji': '🏀'},
    'nfl': {'label': 'NFL', 'entity': 'team', 'tsdb_sport': 'American Football', 'emoji': '🏈'},
    'tennis': {'label': 'Tennis', 'entity': 'player', 'tsdb_sport': 'Tennis', 'emoji': '🎾'},
    'mma': {'label': 'MMA', 'entity': 'player', 'tsdb_sport': 'Fighting', 'emoji': '🥊'},
}

# Tier-1 competitions only, Asia and Africa excluded at the source.
# ORDER IS PRIORITY ORDER — `research()` prices from the top and stops once it has
# enough candidates, so whatever sits at the bottom is what gets skipped on a busy
# day. Domestic cups are LAST deliberately: an EFL Cup first round is 29 fixtures
# of League One and League Two clubs, which is exactly the "minor leagues" the
# brief rules out, while its later rounds still get picked up on a quiet day.
# Tennis sport keys rotate weekly per tournament, so tennis matches by PREFIX.
DEFAULT_LEAGUES = {
    'soccer': [
        # big five domestic leagues
        'soccer_epl',
        'soccer_spain_la_liga',
        'soccer_italy_serie_a',
        'soccer_germany_bundesliga',
        'soccer_france_ligue_one',
        # european club competitions
        'soccer_uefa_champs_league',
        'soccer_uefa_europa_league',
        'soccer_uefa_europa_conference_league',
        # national-team tournaments
        'soccer_fifa_world_cup',
        'soccer_uefa_european_championship',
        'soccer_uefa_nations_league',
        # strong second tier of domestic leagues
        'soccer_netherlands_eredivisie',
        'soccer_portugal_primeira_liga',
        # south america + north america
        'soccer_conmebol_copa_libertadores',
        'soccer_conmebol_copa_sudamericana',
        'soccer_brazil_campeonato',
        'soccer_argentina_primera_division',
        'soccer_usa_mls',
        'soccer_concacaf_leagues_cup',
        'soccer_belgium_first_div',
        'soccer_spl',
        # domestic cups last — see the note above
        'soccer_england_efl_cup',
        'soccer_germany_dfb_pokal',
        'soccer_spain_copa_del_rey',
        'soccer_italy_coppa_italia',
    ],
    'basketball': ['basketball_nba', 'basketball_euroleague', 'basketball_wnba'],
    'nfl': ['americanfootball_nfl', 'americanfootball_nfl_preseason'],
    'tennis': ['tennis_atp', 'tennis_wta'],  # prefix match
    'mma': ['mma_mixed_martial_arts'],
}

# Continent filter. TheSportsDB's strCountry is the authority; this list is the
# fallback when a team never resolves.
_ASIA_AFRICA = {
    'japan',
    'china',
    'south korea',
    'korea',
    'north korea',
    'india',
    'indonesia',
    'thailand',
    'vietnam',
    'malaysia',
    'singapore',
    'philippines',
    'saudi arabia',
    'qatar',
    'united arab emirates',
    'uae',
    'iran',
    'iraq',
    'israel',
    'jordan',
    'kuwait',
    'lebanon',
    'oman',
    'bahrain',
    'uzbekistan',
    'kazakhstan',
    'kyrgyzstan',
    'tajikistan',
    'turkmenistan',
    'hong kong',
    'taiwan',
    'myanmar',
    'cambodia',
    'laos',
    'bangladesh',
    'pakistan',
    'sri lanka',
    'nepal',
    'syria',
    'yemen',
    'afghanistan',
    'mongolia',
    'brunei',
    'maldives',
    'bhutan',
    'egypt',
    'nigeria',
    'south africa',
    'morocco',
    'algeria',
    'tunisia',
    'libya',
    'ghana',
    'kenya',
    'ethiopia',
    'senegal',
    'cameroon',
    'ivory coast',
    "cote d'ivoire",
    'mali',
    'angola',
    'zambia',
    'zimbabwe',
    'uganda',
    'tanzania',
    'sudan',
    'congo',
    'dr congo',
    'burkina faso',
    'guinea',
    'benin',
    'togo',
    'gabon',
    'mozambique',
    'namibia',
    'botswana',
    'rwanda',
    'malawi',
    'niger',
    'mauritania',
    'somalia',
    'madagascar',
    'cape verde',
    'gambia',
    'liberia',
    'sierra leone',
    'equatorial guinea',
    'burundi',
    'chad',
}

DEFAULT_SETTINGS = {
    # ── scheduling ───────────────────────────────────────────────────────────
    'auto_mode': False,
    'tokitoki_run_at': '12:00',  # local, daily — builds the D+2 episodes
    'arena_run_at': '13:00',
    'categories_enabled': ['soccer', 'basketball', 'nfl', 'tennis', 'mma'],
    # ── episode shape (operator decision 2026-08-06: 6-9 picks, 8-12 min) ────
    'bets_per_episode': 7,
    'icebox_hold': 4,  # spec: keep 3-4 bets on ice
    'research_depth': 14,
    'opening_chart_seconds': 8,  # spec: 5-10 s over the welcome line
    # ── selection ────────────────────────────────────────────────────────────
    'min_books': 4,  # liquidity floor for team sports
    'min_books_mma': 6,  # UFC/PFL/Bellator proxy — see docstring
    'min_edge_pct': 1.5,  # value threshold before the fallback tier
    'min_edge_on_air': -1.0,  # HARD floor — below this it is not a pick
    # a ★★★ one-unit bet must be genuinely LIKELY, not merely the least-unlikely
    # selection on a thin card (a 3-bet card once starred two 18-25% Draws)
    'unit_bet_min_prob': 0.35,
    'max_odds': 8.0,  # nobody wants a 12.0 lottery ticket on air
    'min_odds': 1.20,
    'exclude_asia_africa': True,
    # ── api ──────────────────────────────────────────────────────────────────
    'odds_api_key': os.environ.get('ZYG_ODDS_API_KEY', ''),
    'odds_regions': 'eu',  # 1 credit per region per market — keep at 1
    'monthly_credit_cap': 450,  # fail closed before the 500 free plan dies
    'odds_cache_hours': 8,  # share one fetch between the two channels
    'max_leagues_priced': 5,  # requests/episode ceiling — see research()
    'thesportsdb_key': '3',  # shared test key; $9/mo Patreon gives yours
    # API-Sports (api-football etc.) — operator key added 2026-08-08. One key,
    # SEPARATE 100-request/day quota PER SPORT API (football / basketball /
    # american-football each count on their own, verified via /status).
    'apisports_key': os.environ.get('ZYG_APISPORTS_API_KEY', ''),
    'apisports_daily_cap': 90,  # fail closed with headroom under the 100
    # ── voices (seed-pool names) ─────────────────────────────────────────────
    # 2026-08-07 operator: TokiToki must be MALE (was f02). 2026-08-08: "a bit
    # more uplifting/energetic" than m08's wry-relaxed read → m02, the bright
    # friendly tenor with light energetic delivery.
    'tokitoki_voice': 'm02_bright_tenor',
    'arena_voice': 'm07_dark_resonant',
    # ── retention ────────────────────────────────────────────────────────────
    'delivery_ttl_hours': 72,
}

#: The original top import block, re-exported: sports_ingest/__init__.py reads it.
__all__ = [
    'json',
    'os',
    're',
    'statistics',
    'threading',
    'time',
    'datetime',
    'timedelta',
    'timezone',
    'requests',
    'ZoneInfo',
    '_zyg_logging',
    '_zyg_log',
]
