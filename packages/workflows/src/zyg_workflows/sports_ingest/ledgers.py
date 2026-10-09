# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.ledgers — star experiment ledger and the one-unit bet ledger.

Verbatim section of the original sports_ingest.py (lines 2090-2170); no logic changes.
"""

from __future__ import annotations

import os

from zyg_workflows.sports_ingest.constants import _LOCK, _RUNTIME
from zyg_workflows.sports_ingest.helpers import _iso, _load, _save


# ── star experiment ledger (operator debate 2026-08-08) ─────────────────────
# Operator argues form/H2H should outrank market probability for the two
# one-unit bets; the market-efficiency case says otherwise. Instead of
# arguing: every episode logs BOTH selections — market_stars (shipped) and
# form_stars (counterfactual) — so a few weeks of results settles it.
_STAR_EXP_PATH = os.path.join(_RUNTIME, 'sports_star_experiment.json')


def star_experiment_add(
    job_id: str, channel: str, category: str, day: str, market_stars: list, form_stars: list, bets: list
) -> None:
    with _LOCK:
        d = _load(_STAR_EXP_PATH, {}) or {}
        rows = d.get('episodes') or []
        rows.append(
            {
                'at': _iso(),
                'job_id': job_id,
                'channel': channel,
                'category': category,
                'match_day': day,
                'market_stars': market_stars,
                'form_stars': form_stars,
                'bets': [
                    {
                        'event_id': b.get('event_id'),
                        'match': f'{b.get("home")} vs {b.get("away")}',
                        'selection': b.get('selection'),
                        'odds': b.get('price'),
                        'fair_prob': b.get('fair_prob'),
                        'form_score': b.get('form_score'),
                        'result': '',
                    }
                    for b in bets or []
                ],
            }
        )
        d['episodes'] = rows[-500:]
        _save(_STAR_EXP_PATH, d)


# ── the one-unit bet ledger (operator rule 2026-08-08) ──────────────────────
# "only ever bet 1 unit on every selection, but don't bet every selection of
# the 7 — just pick the most likely 2 of 7 to win. single bets, not parlays.
# register in a json file all of the matches we selected to bet on and their
# correlating odds."
_UNIT_BETS_PATH = os.path.join(_RUNTIME, 'sports_unit_bets.json')


def unit_bets_add(bets: list, channel: str, category: str, job_id: str, match_day: str) -> None:
    with _LOCK:
        d = _load(_UNIT_BETS_PATH, {}) or {}
        rows = d.get('bets') or []
        for b in bets or []:
            rows.append(
                {
                    'at': _iso(),
                    'job_id': job_id,
                    'channel': channel,
                    'category': category,
                    'match_day': match_day,
                    'event_id': b.get('event_id'),
                    'match': f'{b.get("home")} vs {b.get("away")}',
                    'selection': b.get('selection'),
                    'odds': b.get('price'),
                    'book': b.get('book'),
                    'fair_prob': b.get('fair_prob'),
                    'edge_pct': b.get('edge_pct'),
                    'units': 1,
                    'stars': 3,
                    'result': '',
                }
            )
        d['bets'] = rows[-2000:]
        _save(_UNIT_BETS_PATH, d)


def unit_bets(limit: int = 200) -> list:
    return list(reversed((_load(_UNIT_BETS_PATH, {}) or {}).get('bets', [])))[:limit]
