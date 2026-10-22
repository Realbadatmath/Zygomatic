# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.py — fixtures, odds, value-scoring and team/player artwork for the
TokiToki and Arena betting departments (2026-08-06).

Standalone module: NO crewai_web_gui import anywhere. Only stdlib + requests.

State files (data/runtime/, atomic tmp+os.replace, module RLock):
  sports_settings.json   — operator settings incl. per-channel voice + whitelist
  sports_icebox.json     — bets researched but HELD BACK for telegram / X
  sports_history.json    — every published bet (result-tracking + dedupe)
  sports_quota.json      — rolling Odds-API credit ledger (see QUOTA below)
  sports_teams.json      — TheSportsDB team/player lookups (badge, country)
  sports_art/            — downloaded badges & player cutouts, reused across runs
  sports_odds_cache/     — per (league, match day) odds, shared by both channels

THE D+2 RULE (operator spec)
"Collect data for matches 2 days ahead. Not more than 2 days ahead and not less
than 1 day. If video is created on 24 December, it is created for matches played
on 26 December." Both halves of that are satisfied by taking the WHOLE local
calendar day at today+2: it starts +24 h and ends +72 h from any moment of the
build day. `window_for()` returns exactly those UTC bounds.

QUOTA — why /events is called before /odds
The Odds API free plan is 500 credits/month. `/v4/sports/{key}/events` costs 0
(measured 2026-08-06: x-requests-last: 0), `/v4/sports/{key}/odds` costs
regions × markets. So every league is probed for free first and only leagues with
fixtures inside the D+2 window ever spend a credit. `sports_quota.json` mirrors
the x-requests-remaining header so the console can show the real balance, and
`monthly_credit_cap` fails the run closed before the key is exhausted mid-month.

SCOPE FILTERS (operator spec: "not minor leagues, only notable tournaments;
don't include teams from asia or africa for example")
  1. competition whitelist  — DEFAULT_SETTINGS['leagues'], operator-editable.
  2. continent filter       — teams resolved through TheSportsDB carry strCountry;
                              anything in Asia or Africa is dropped even when its
                              competition is whitelisted (e.g. a cross-continental
                              cup). Only a HIGH-confidence lookup may exclude:
                              unresolved and loosely-matched teams are KEPT,
                              because deleting a real fixture on a bad name match
                              is far worse than showing a placeholder badge.
  3. liquidity floor        — MMA's single sport key mixes UFC/PFL with small
                              regional cards. Bookmaker count is the promotion
                              proxy: `min_books_mma` (default 6) keeps the cards
                              the market actually prices.

ARTWORK LICENCE
Images come from TheSportsDB. Their terms (fetched 2026-08-06): free tier may not
publish to an app store (not what we do); artwork is user-created and "you must
not pass it off as your own and should link back"; "any trademarked sports logos
must be used 'As is' and should not be modified in any way". So: badges are
composited unmodified (no recolour, no crop through the mark), every episode
writes a credit line into description.txt, and `strCreativeCommons` is recorded
per asset in the episode's attribution.json. Set `thesportsdb_key` to your own
$9/mo Patreon key to move off the shared test key.
"""

from __future__ import annotations

from zyg_workflows.sports_ingest.constants import (  # noqa: F401
    json,
    os,
    re,
    statistics,
    threading,
    time,
    datetime,
    timedelta,
    timezone,
    requests,
    ZoneInfo,
    _LOCAL_TZ,
    _zyg_logging,
    _zyg_log,
    _CREWS,
    _RUNTIME,
    _ART_DIR,
    _SETTINGS_PATH,
    _ICEBOX_PATH,
    _HISTORY_PATH,
    _QUOTA_PATH,
    _TEAMS_PATH,
    _ODDS_CACHE_DIR,
    _TSDB_GAP,
    _NEG_TTL,
    _LOCK,
    _ODDS_BASE,
    _TSDB_BASE,
    _UA,
    _HDRS,
    CATEGORIES,
    DEFAULT_LEAGUES,
    _ASIA_AFRICA,
    DEFAULT_SETTINGS,
)
from zyg_workflows.sports_ingest.helpers import (  # noqa: F401
    _load,
    _save,
    _now_utc,
    _iso,
    settings,
    update_settings,
    window_for,
    _z,
)
from zyg_workflows.sports_ingest.odds_api import (  # noqa: F401
    quota,
    _note_quota,
    credits_ok,
    _odds_get,
    active_sport_keys,
    _keys_for,
    fetch_events,
    _odds_cache_path,
    fetch_odds,
    sweep_odds_cache,
)
from zyg_workflows.sports_ingest.thesportsdb import (  # noqa: F401
    _tsdb_get,
    _team_cache,
    _team_cache_put,
    _PAREN_RE,
    _norm_name,
    _TSDB_QUERY_ALIASES,
    _LEAGUE_COUNTRY,
    _TEAM_NOISE_RE,
    _COUNTRY_ALIAS,
    _country_key,
    _name_key,
    _VARIANT_RE,
    _variant_mismatch,
    _pick_row,
    lookup_entity,
    download_art,
)
from zyg_workflows.sports_ingest.key_players import (  # noqa: F401
    _PLAYER_POS_SCORE,
    _PLAYER_TTL,
    _ART_FRESH_S,
    _art_epoch,
    _team_colours,
    _shirt_matches,
    _position_score,
    team_players,
)
from zyg_workflows.sports_ingest.photos import (  # noqa: F401
    _APISPORTS_HOSTS,
    _APISPORTS_QUOTA_PATH,
    _APISPORTS_TTL,
    _apisports_quota,
    _apisports_note,
    _apisports_get,
    _apisports_team_id,
    apisports_squad,
    _squad_lookup,
    _ESPN_TEAMS_CACHE,
    _ESPN_ROSTER_CACHE,
    _ESPN_ART_TTL,
    _espn_get,
    _espn_team_id,
    espn_headshot,
)
from zyg_workflows.sports_ingest.injuries import (  # noqa: F401
    _ESPN_INJURIES_BASE,
    _ESPN_LEAGUE,
    _INJURY_CACHE,
    _INJURY_TTL,
    _INJURY_KEEP,
    _espn_injuries_for,
    team_injuries,
    _is_excluded_continent,
)
from zyg_workflows.sports_ingest.value_model import (  # noqa: F401
    _devig,
    _SHARP_BOOKS,
    price_event,
    _kelly,
    score_event,
    build_parlays,
)
from zyg_workflows.sports_ingest.results import (  # noqa: F401
    _RESULTS_CACHE_DIR,
    _RESULTS_TTL,
    _FD_BASE,
    _FD_EURO,
    _FD_NEW,
    _RESULTS_MEM,
    _http_cached,
    _euro_season_codes,
    _parse_fd_csv,
    _fd_matches,
    _fd_team_name,
    recent_results,
    h2h_results,
    _tennis_rows,
    _tennis_match_name,
    player_recent_results,
    player_h2h,
)
from zyg_workflows.sports_ingest.ledgers import (  # noqa: F401
    _STAR_EXP_PATH,
    star_experiment_add,
    _UNIT_BETS_PATH,
    unit_bets_add,
    unit_bets,
)
from zyg_workflows.sports_ingest.research_run import (  # noqa: F401
    research,
)
from zyg_workflows.sports_ingest.icebox_store import (  # noqa: F401
    icebox,
    icebox_add,
    icebox_mark_used,
    icebox_delete,
    social_text,
    history_add,
    history,
)

# Every name imported above is re-exported, not used here: this package IS the module
# the split replaced, so `__all__` declares the surface instead of a file-level noqa.
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
    '_LOCAL_TZ',
    '_zyg_logging',
    '_zyg_log',
    '_CREWS',
    '_RUNTIME',
    '_ART_DIR',
    '_SETTINGS_PATH',
    '_ICEBOX_PATH',
    '_HISTORY_PATH',
    '_QUOTA_PATH',
    '_TEAMS_PATH',
    '_ODDS_CACHE_DIR',
    '_TSDB_GAP',
    '_NEG_TTL',
    '_LOCK',
    '_ODDS_BASE',
    '_TSDB_BASE',
    '_UA',
    '_HDRS',
    'CATEGORIES',
    'DEFAULT_LEAGUES',
    '_ASIA_AFRICA',
    'DEFAULT_SETTINGS',
    '_load',
    '_save',
    '_now_utc',
    '_iso',
    'settings',
    'update_settings',
    'window_for',
    '_z',
    'quota',
    '_note_quota',
    'credits_ok',
    '_odds_get',
    'active_sport_keys',
    '_keys_for',
    'fetch_events',
    '_odds_cache_path',
    'fetch_odds',
    'sweep_odds_cache',
    '_tsdb_get',
    '_team_cache',
    '_team_cache_put',
    '_PAREN_RE',
    '_norm_name',
    '_TSDB_QUERY_ALIASES',
    '_LEAGUE_COUNTRY',
    '_TEAM_NOISE_RE',
    '_COUNTRY_ALIAS',
    '_country_key',
    '_name_key',
    '_VARIANT_RE',
    '_variant_mismatch',
    '_pick_row',
    'lookup_entity',
    'download_art',
    '_PLAYER_POS_SCORE',
    '_PLAYER_TTL',
    '_ART_FRESH_S',
    '_art_epoch',
    '_team_colours',
    '_shirt_matches',
    '_position_score',
    'team_players',
    '_APISPORTS_HOSTS',
    '_APISPORTS_QUOTA_PATH',
    '_APISPORTS_TTL',
    '_apisports_quota',
    '_apisports_note',
    '_apisports_get',
    '_apisports_team_id',
    'apisports_squad',
    '_squad_lookup',
    '_ESPN_TEAMS_CACHE',
    '_ESPN_ROSTER_CACHE',
    '_ESPN_ART_TTL',
    '_espn_get',
    '_espn_team_id',
    'espn_headshot',
    '_ESPN_INJURIES_BASE',
    '_ESPN_LEAGUE',
    '_INJURY_CACHE',
    '_INJURY_TTL',
    '_INJURY_KEEP',
    '_espn_injuries_for',
    'team_injuries',
    '_is_excluded_continent',
    '_devig',
    '_SHARP_BOOKS',
    'price_event',
    '_kelly',
    'score_event',
    'build_parlays',
    '_RESULTS_CACHE_DIR',
    '_RESULTS_TTL',
    '_FD_BASE',
    '_FD_EURO',
    '_FD_NEW',
    '_RESULTS_MEM',
    '_http_cached',
    '_euro_season_codes',
    '_parse_fd_csv',
    '_fd_matches',
    '_fd_team_name',
    'recent_results',
    'h2h_results',
    '_tennis_rows',
    '_tennis_match_name',
    'player_recent_results',
    'player_h2h',
    '_STAR_EXP_PATH',
    'star_experiment_add',
    '_UNIT_BETS_PATH',
    'unit_bets_add',
    'unit_bets',
    'research',
    'icebox',
    'icebox_add',
    'icebox_mark_used',
    'icebox_delete',
    'social_text',
    'history_add',
    'history',
]
