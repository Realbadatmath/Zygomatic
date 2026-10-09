# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.value_model — value model and parlays.

Verbatim section of the original sports_ingest.py (lines 1438-1773); no logic changes.
"""

from __future__ import annotations

import statistics

from zyg_workflows.sports_ingest.helpers import settings


# ── value model ─────────────────────────────────────────────────────────────


def _devig(prices: dict) -> dict:
    """One bookmaker's decimal prices → vig-free implied probabilities."""
    imp = {k: (1.0 / v) for k, v in prices.items() if v and v > 1.0}
    total = sum(imp.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in imp.items()}


# Sharp books and exchanges. Their de-vigged line is the closest public proxy for
# the true probability, so it anchors "fair" when one of them prices the market.
_SHARP_BOOKS = {
    'pinnacle',
    'betfair',
    'betfair_ex_eu',
    'betfair_ex_uk',
    'smarkets',
    'matchbook',
    'betonline.ag',
    'betonlineag',
    'circa sports',
}


def price_event(event: dict) -> dict:
    """Fair probabilities, best available price per outcome, and the market's shape.

    Three corrections that a naive median gets wrong, all of them measured on real
    responses 2026-08-06:

    1. CONSENSUS OUTCOME SET. 1xBet quotes a "Draw" at 50.0 on two-man MMA fights.
       A median taken per-outcome would hand Draw a ~1.8% probability sourced from
       exactly one book, and the renormalisation then shaved that 1.8% off both
       real fighters — a systematic negative bias on every affected event. Only
       outcomes quoted by at least half the books survive.

    2. SHARP ANCHOR. Fair is 0.6 × the sharp/exchange de-vig + 0.4 × the median of
       the rest when a sharp book is present. Comparing a soft book's price to a
       consensus that mostly consists of soft books finds no value, because the
       soft books move together.

    3. LEAVE-ONE-OUT. The book offering the best price on an outcome is excluded
       from that outcome's fair estimate. Otherwise the very book you intend to
       bet is helping decide that its own price is generous.
    """
    books = event.get('bookmakers') or []
    parsed, best_price, best_book = [], {}, {}
    for bk in books:
        mkt = next((m for m in (bk.get('markets') or []) if m.get('key') == 'h2h'), None)
        if not mkt:
            continue
        prices = {}
        for o in mkt.get('outcomes') or []:
            nm, pr = o.get('name'), o.get('price')
            if not nm or not pr or float(pr) <= 1.0:
                continue
            prices[nm] = float(pr)
        if prices:
            title = bk.get('title') or bk.get('key') or ''
            parsed.append(
                {
                    'title': title,
                    'prices': prices,
                    'sharp': title.lower() in _SHARP_BOOKS or (bk.get('key') or '').lower() in _SHARP_BOOKS,
                }
            )
    if not parsed:
        return {'n_books': 0, 'fair_prob': {}, 'best_price': {}, 'best_book': {}, 'outcomes': [], 'sharp_anchor': ''}

    # (1) consensus outcome set
    counts = {}
    for p in parsed:
        for nm in p['prices']:
            counts[nm] = counts.get(nm, 0) + 1
    quorum = max(2, (len(parsed) + 1) // 2)
    outcomes = sorted([nm for nm, c in counts.items() if c >= quorum])
    if len(outcomes) < 2:
        outcomes = sorted(counts, key=lambda n: -counts[n])[:3]

    for p in parsed:
        p['prices'] = {k: v for k, v in p['prices'].items() if k in outcomes}
        p['fair'] = _devig(p['prices'])
        for nm, pr in p['prices'].items():
            if pr > best_price.get(nm, 0):
                best_price[nm] = pr
                best_book[nm] = p['title']

    sharps = [p for p in parsed if p['sharp'] and p['fair']]
    sharp_anchor = ', '.join(sorted({p['title'] for p in sharps})) if sharps else ''

    fair_prob = {}
    for nm in outcomes:
        # (3) leave-one-out: drop the book that quotes the best price on this outcome
        pool = [p for p in parsed if p['fair'] and nm in p['fair'] and p['title'] != best_book.get(nm)]
        if not pool:
            pool = [p for p in parsed if p['fair'] and nm in p['fair']]
        if not pool:
            continue
        sharp_vals = [p['fair'][nm] for p in pool if p['sharp']]
        soft_vals = [p['fair'][nm] for p in pool if not p['sharp']]
        if sharp_vals and soft_vals:
            fair_prob[nm] = 0.6 * statistics.median(sharp_vals) + 0.4 * statistics.median(soft_vals)  # (2)
        else:
            fair_prob[nm] = statistics.median(sharp_vals or soft_vals)
    total = sum(fair_prob.values())
    if total > 0:
        fair_prob = {k: v / total for k, v in fair_prob.items()}
    return {
        'n_books': len(parsed),
        'fair_prob': fair_prob,
        'best_price': {k: v for k, v in best_price.items() if k in outcomes},
        'best_book': {k: v for k, v in best_book.items() if k in outcomes},
        'outcomes': outcomes,
        'sharp_anchor': sharp_anchor,
    }


def _kelly(prob: float, price: float, fraction: float = 0.25, cap: float = 0.02) -> float:
    """Quarter-Kelly stake as a fraction of bankroll, hard-capped at `cap`.

    Full Kelly is mathematically optimal and practically ruinous on estimated
    edges; quarter-Kelly with a 2% ceiling is what actually survives a season.
    """
    b = price - 1.0
    if b <= 0:
        return 0.0
    edge = (prob * price) - 1.0
    if edge <= 0:
        return 0.0
    return max(0.0, min(cap, (edge / b) * fraction))


def score_event(event: dict, category: str, entity_map: dict) -> dict:
    """Turn one priced fixture into a rankable bet with its reasoning.

    Like the market department, every number in `drivers` is measured here; the
    narration writer may only rephrase them.
    """
    s = settings()
    pricing = price_event(event)
    fair, best, bestbk = pricing['fair_prob'], pricing['best_price'], pricing['best_book']
    if not fair or not best:
        return {}

    min_odds = float(s.get('min_odds') or 1.2)
    max_odds = float(s.get('max_odds') or 8.0)
    cands = []
    for nm, p in fair.items():
        price = best.get(nm)
        if not price or not (min_odds <= price <= max_odds):
            continue
        edge = (p * price) - 1.0
        cands.append({'selection': nm, 'fair_prob': p, 'price': price, 'book': bestbk.get(nm, ''), 'edge': edge})
    if not cands:
        return {}
    cands.sort(key=lambda c: c['edge'], reverse=True)
    pick = cands[0]

    home = event.get('home_team') or ''
    away = event.get('away_team') or ''
    fav = min(fair, key=lambda k: -fair[k]) if fair else ''
    fav_prob = fair.get(fav, 0)

    min_edge = float(s.get('min_edge_pct') or 1.5)
    bet_type = 'value' if pick['edge'] * 100.0 >= min_edge else 'confidence'
    anchor = pricing.get('sharp_anchor') or ''

    drivers = []
    drivers.append(
        f'{pricing["n_books"]} bookmakers price this match'
        + (f', and against the sharp line at {anchor} ' if anchor else ', and the vig-free consensus ')
        + f'{pick["selection"]} is a {pick["fair_prob"] * 100:.0f} percent chance'
    )
    # No "best available price at <book>" phrasing: spoken every chapter it
    # grated (operator 2026-08-08). The bookmaker stays ON SCREEN; narration
    # only argues the number.
    drivers.append(f'the {pick["price"]:.2f} on offer implies only {100.0 / pick["price"]:.0f} percent')
    if bet_type == 'value':
        drivers.append(
            f'that gap is an edge of {pick["edge"] * 100:.1f} percent '
            f'— the market is paying more than the true odds, which is '
            f'the whole reason this bet is on the card'
        )
    else:
        # Say it plainly. A betting channel that pretends every pick is +EV is a
        # betting channel nobody can check.
        drivers.append(
            f'there is no pricing edge here — the fair price and the '
            f'best available price are within {abs(pick["edge"]) * 100:.1f} '
            f'percent of each other, so this is a confidence pick on the '
            f'{pick["fair_prob"] * 100:.0f} percent likelihood, not a value bet'
        )
    if pick['selection'] == fav:
        drivers.append(f'{pick["selection"]} is the market favourite at {fav_prob * 100:.0f} percent')
    elif fav:
        drivers.append(f'this is against the favourite {fav} ({fav_prob * 100:.0f} percent) — an underdog call')
    spread = 0.0
    if pick['fair_prob'] > 0:
        fair_price = 1.0 / pick['fair_prob']
        spread = (pick['price'] - fair_price) / fair_price * 100.0

    # ranking: value first, then market confidence, then liquidity
    edge_pts = max(-1.0, min(3.0, pick['edge'] * 20.0))
    conf_pts = pick['fair_prob'] * 1.6
    liq_pts = min(1.0, pricing['n_books'] / 12.0)
    rank = edge_pts + conf_pts + liq_pts

    return {
        'event_id': event.get('id'),
        'category': category,
        'sport_key': event.get('sport_key') or '',
        'league': (event.get('sport_title') or '').strip(),
        'commence_time': event.get('commence_time'),
        'home': home,
        'away': away,
        'home_entity': entity_map.get(home) or {},
        'away_entity': entity_map.get(away) or {},
        'selection': pick['selection'],
        'price': round(pick['price'], 2),
        'book': pick['book'],
        'bet_type': bet_type,  # 'value' | 'confidence'
        'sharp_anchor': anchor,
        'fair_prob': round(pick['fair_prob'], 4),
        'fair_price': round(1.0 / pick['fair_prob'], 2) if pick['fair_prob'] else 0,
        'implied_prob': round(1.0 / pick['price'], 4),
        'edge_pct': round(pick['edge'] * 100.0, 2),
        'stake_pct': round(_kelly(pick['fair_prob'], pick['price']) * 100.0, 2),
        'n_books': pricing['n_books'],
        'price_spread_pct': round(spread, 1),
        'all_outcomes': [
            {'name': k, 'fair_prob': round(v, 4), 'best_price': round(best.get(k, 0), 2)}
            for k, v in sorted(fair.items(), key=lambda x: -x[1])
        ],
        'drivers': drivers,
        'rank': round(rank, 3),
    }


# ── parlays (operator enhancement 2026-08-07) ───────────────────────────────
# "build workflow to also create a parlay sheet … parlays between 2-4 matches,
# never more matches per parlay. show the parlays after having explained all
# matches and showing the bet overview." Every number here is COMPUTED — the
# narration only reads them, same contract as the drivers. Combined price is
# the product of each leg's best price across books, so the episode says out
# loud that a single bookmaker's parlay price will differ.


def build_parlays(
    bets: list, min_legs: int = 2, max_legs: int = 4, max_parlays: int = 4, banker_ids: list = None
) -> list:
    """Deterministic parlay candidates from the on-air card.

    Only positive-edge legs qualify (a parlay compounds a bad leg's negative
    edge as fast as a good leg's positive one). One bet per match by
    construction, so legs never share a fixture. Stake is quarter-Kelly on the
    COMBINED probability/price, hard-capped at 0.5% — a quarter of the singles
    cap, because parlay variance is brutal."""
    from itertools import combinations

    max_legs = max(min_legs, min(4, int(max_legs)))  # never more than 4
    legs = [
        b
        for b in bets or []
        if float(b.get('fair_prob') or 0) > 0 and float(b.get('price') or 0) > 1.0 and float(b.get('edge_pct') or 0) > 0
    ]
    if len(legs) < min_legs:
        return []

    def _mk(combo, label):
        price = prob = 1.0
        for l in combo:
            price *= float(l['price'])
            prob *= float(l['fair_prob'])
        edge = prob * price - 1.0
        stake = _kelly(prob, price, fraction=0.25, cap=0.005) * 100.0
        return {
            'label': label,
            'legs': [
                {
                    'event_id': l.get('event_id'),
                    'match': f'{l.get("home")} vs {l.get("away")}',
                    'selection': l.get('selection'),
                    'price': l.get('price'),
                }
                for l in combo
            ],
            'n_legs': len(combo),
            'price': round(price, 2),
            'prob_pct': round(prob * 100.0, 2),
            'edge_pct': round(edge * 100.0, 1),
            'stake_pct': round(stake, 2),
        }

    by_edge = sorted(legs, key=lambda b: -float(b.get('edge_pct') or 0))
    out, used = [], set()

    def _add(combo, label):
        key = tuple(sorted(str(l.get('event_id')) for l in combo))
        if key in used:
            return
        used.add(key)
        out.append(_mk(combo, label))

    # THE BANKERS — operator rule 2026-08-08: the two most-likely-to-win picks
    # (the day's one-unit bets) are ALWAYS on the parlay sheet, edge filter or
    # not. Listed first.
    if banker_ids:
        bank = [
            b
            for b in bets or []
            if b.get('event_id') in set(banker_ids)
            and float(b.get('fair_prob') or 0) > 0
            and float(b.get('price') or 0) > 1.0
        ]
        if len(bank) >= 2:
            _add(bank[:2], 'The Bankers ★★★')
    if len(by_edge) >= 2:
        _add(by_edge[:2], 'The Double')
    if len(by_edge) >= 3 and max_legs >= 3:
        _add(by_edge[:3], 'The Treble')
    if len(by_edge) >= 4 and max_legs >= 4:
        _add(by_edge[:4], 'The Four-Fold')
    # the least-wild option: the 2-leg combo with the highest combined chance
    best = None
    for c in combinations(legs, 2):
        p = float(c[0]['fair_prob']) * float(c[1]['fair_prob'])
        if best is None or p > best[0]:
            best = (p, c)
    if best:
        _add(list(best[1]), 'The Safer Double')
    return out[:max_parlays]
