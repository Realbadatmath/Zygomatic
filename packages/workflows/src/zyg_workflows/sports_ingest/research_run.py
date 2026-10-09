# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.research_run — the research run.

Verbatim section of the original sports_ingest.py (lines 2171-2314); no logic changes.
"""

from __future__ import annotations

import time

from zyg_workflows.sports_ingest.constants import DEFAULT_LEAGUES
from zyg_workflows.sports_ingest.helpers import settings, window_for
from zyg_workflows.sports_ingest.odds_api import credits_ok, fetch_events, fetch_odds
from zyg_workflows.sports_ingest.thesportsdb import lookup_entity
from zyg_workflows.sports_ingest.injuries import _is_excluded_continent
from zyg_workflows.sports_ingest.value_model import score_event


# ── the research run ────────────────────────────────────────────────────────


def research(category: str, want: int = 14, log=None, stop=None, day_override: str = '') -> dict:
    """Fixtures → odds → filters → ranked bets for the D+2 day.

    Returns {'day', 'bets', 'skipped', 'credit_note'}. Never raises; an empty
    'bets' with a populated 'skipped' is a legitimate quiet-day answer.
    """
    s = settings()
    _uf, _ut, day = window_for(day_override=day_override)
    skipped = []

    def _log(level, msg):
        if log:
            log(level, msg)

    ok, why = credits_ok()
    if not ok:
        _log('ERROR', f'Odds API gate: {why}')
        return {'day': day, 'bets': [], 'skipped': [f'odds api: {why}'], 'credit_note': why}

    events = fetch_events(category, log=log, day_override=day_override)
    if not events:
        _log('WARNING', f'no {category} fixtures on {day} in the whitelisted competitions')
        return {'day': day, 'bets': [], 'skipped': ['no fixtures in the D+2 window'], 'credit_note': why}

    # Price the BIGGEST competitions first and stop as soon as there are plenty of
    # candidates. An episode needs ~14 selections; pricing all nine live soccer
    # leagues to rank 53 of them costs nine requests out of a 500/month free plan
    # for candidates that were never going to make the card. Whitelist order is
    # priority order (EPL, La Liga, Serie A, … first), which is also the right
    # editorial order for "only notable tournaments".
    priority = (s.get('leagues') or DEFAULT_LEAGUES).get(category) or []
    live = {e['sport_key'] for e in events}
    n_fix = {k: sum(1 for e in events if e['sport_key'] == k) for k in live}
    keys = sorted(live, key=lambda k: (priority.index(k) if k in priority else 999, -n_fix[k], k))
    max_leagues = max(1, int(s.get('max_leagues_priced') or 5))
    _log('INFO', f'{len(events)} {category} fixture(s) on {day} across {len(keys)} competition(s)')

    priced, used_keys = [], []
    enough = max(12, want * 3)
    # `max_leagues_priced` is a SOFT cap. It exists to protect the free-plan
    # request budget, but on a thin day it starved the card: 5 leagues gave 15
    # fixtures for a 7-bet show, and the bottom of that card scraped down to a
    # -3.7% edge pick on a 1.21 favourite. Padding an episode with bets we would
    # not place is worse than spending two more requests, so the cap can be
    # exceeded up to `ceiling` while the pool is still short of what the card
    # needs.
    ceiling = min(len(keys), max_leagues + 4)
    for k in keys:
        if stop and stop():
            break
        if len(priced) >= enough or len(used_keys) >= ceiling:
            break
        # `want` fixtures is NOT `want` usable bets. Roughly half are lost to the
        # bookmaker floor, the continent filter and the negative-edge floor —
        # measured 2026-08-06: 15 fixtures produced 8 qualified bets, which filled
        # the 7-bet card but left 1 for the ice box instead of the 4 the brief
        # asks for. Price against twice the target so the ice box survives a
        # thin day; the ceiling still bounds the request cost.
        if len(used_keys) >= max_leagues and len(priced) >= want * 2:
            break
        rows = fetch_odds(k, log=log, day_override=day_override)
        used_keys.append(k)
        for e in rows:
            e['sport_key'] = k
            priced.append(e)
        time.sleep(0.3)
    unpriced = [k for k in keys if k not in used_keys]
    if unpriced:
        # never a silent cap — say what was left out and why
        why_stop = (
            'enough candidates'
            if len(priced) >= enough
            else (f'hard ceiling {ceiling}' if len(used_keys) >= ceiling else f'max_leagues_priced={max_leagues}')
        )
        _log(
            'INFO',
            f'priced {len(used_keys)} league(s) → {len(priced)} fixture(s); '
            f'stopped before {", ".join(unpriced)} ({why_stop})',
        )
    if not priced:
        return {'day': day, 'bets': [], 'skipped': ['no odds returned for the window'], 'credit_note': credits_ok()[1]}

    # keep only fixtures actually inside the D+2 day (the odds endpoint is
    # inclusive at its bounds and occasionally returns a neighbouring fixture)
    want_ids = {e.get('id') for e in events}
    priced = [e for e in priced if e.get('id') in want_ids]

    min_books = int(s.get('min_books_mma' if category == 'mma' else 'min_books') or 4)
    scored = []
    for e in priced:
        if stop and stop():
            break
        names = [n for n in (e.get('home_team'), e.get('away_team')) if n]
        entity_map = {n: lookup_entity(n, category, league_hint=e.get('sport_key') or '') for n in names}
        if s.get('exclude_asia_africa') and any(_is_excluded_continent(r) for r in entity_map.values()):
            skipped.append(f'{e.get("home_team")} vs {e.get("away_team")} (Asia/Africa filter)')
            continue
        bet = score_event(e, category, entity_map)
        if not bet:
            continue
        if bet['n_books'] < min_books:
            skipped.append(
                f'{bet["home"]} vs {bet["away"]} (only {bet["n_books"]} bookmakers — below the {min_books}-book floor)'
            )
            continue
        scored.append(bet)

    scored.sort(key=lambda b: b['rank'], reverse=True)
    # HARD FLOOR. A bet priced below fair is one we would not place ourselves, so
    # it does not go on air and it does not go on the socials either — it is
    # simply not a pick. A short honest card beats a padded one; the pipeline
    # already refuses to build under three selections.
    floor = float(s.get('min_edge_on_air') if s.get('min_edge_on_air') is not None else -1.0)
    rejected = [b for b in scored if b['edge_pct'] < floor]
    scored = [b for b in scored if b['edge_pct'] >= floor]
    if rejected:
        _log(
            'INFO',
            f'{len(rejected)} bet(s) below the {floor:+.1f}% edge floor were '
            f'dropped, not padded onto the card: '
            + '; '.join(f'{b["home"]} vs {b["away"]} ({b["edge_pct"]:+.1f}%)' for b in rejected[:5]),
        )
        skipped.extend(f'{b["home"]} vs {b["away"]} (edge {b["edge_pct"]:+.1f}% below floor)' for b in rejected)
    min_edge = float(s.get('min_edge_pct') or 1.5)
    value = [b for b in scored if b['edge_pct'] >= min_edge]
    rest = [b for b in scored if b['edge_pct'] < min_edge]
    ordered = value + rest  # value first, confidence fills the card
    _log(
        'INFO',
        f'{len(scored)} priced bet(s) survived the filters '
        f'({len(value)} with ≥{min_edge}% edge); {len(skipped)} skipped',
    )
    return {
        'day': day,
        'bets': ordered[:want],
        'skipped': skipped[:40],
        'credit_note': credits_ok()[1],
        'n_value': len(value),
    }
