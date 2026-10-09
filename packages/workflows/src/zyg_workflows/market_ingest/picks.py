# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.market_ingest.core import (
    _HISTORY_PATH,
    _ICEBOX_PATH,
    _LOCK,
    _iso,
    _load,
    _now_utc,
    _save,
    _zyg_log,
    crypto_universe,
    datetime,
    settings,
    time,
    timedelta,
    timezone,
    universe,
)
from zyg_workflows.market_ingest.prices import fetch_bars

# ── indicators (all arithmetic lives here, never in a prompt) ───────────────


def _sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ema_series(xs, n):
    if len(xs) < n:
        return []
    k = 2.0 / (n + 1)
    out = [sum(xs[:n]) / n]
    for x in xs[n:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, n + 1):
        d = closes[-i] - closes[-i - 1]
        (gains if d > 0 else losses).append(abs(d))
    ag = sum(gains) / n
    al = sum(losses) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_pct(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        h, l, pc = bars[i]['h'], bars[i]['l'], bars[i - 1]['c']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / n
    last = bars[-1]['c']
    return (atr / last * 100.0) if last else None


def _pct(a, b):
    return ((a / b) - 1.0) * 100.0 if b else None


def indicators(bars: list) -> dict:
    """Every measured fact a pick can cite. Missing inputs give None, never a guess."""
    closes = [b['c'] for b in bars]
    vols = [b['v'] for b in bars]
    last = closes[-1]
    ind = {
        'last': last,
        'date': bars[-1]['d'],
        'sma20': _sma(closes, 20),
        'sma50': _sma(closes, 50),
        'sma100': _sma(closes, 100),
        'sma200': _sma(closes, 200),
        'rsi14': _rsi(closes, 14),
        'atr_pct': _atr_pct(bars, 14),
        'ret_5d': _pct(last, closes[-6]) if len(closes) > 6 else None,
        'ret_20d': _pct(last, closes[-21]) if len(closes) > 21 else None,
        'ret_60d': _pct(last, closes[-61]) if len(closes) > 61 else None,
        'ret_120d': _pct(last, closes[-121]) if len(closes) > 121 else None,
        'hi_52w': max(closes[-252:]) if len(closes) >= 60 else None,
        'lo_52w': min(closes[-252:]) if len(closes) >= 60 else None,
    }
    # MACD histogram (12/26/9) — trend-change confirmation
    e12, e26 = _ema_series(closes, 12), _ema_series(closes, 26)
    if e12 and e26:
        n = min(len(e12), len(e26))
        macd = [e12[-n + i] - e26[-n + i] for i in range(n)]
        sig = _ema_series(macd, 9)
        if sig:
            ind['macd_hist'] = macd[-1] - sig[-1]
            ind['macd_hist_prev'] = (macd[-2] - sig[-2]) if len(macd) > 1 and len(sig) > 1 else None
    # volume surge vs its own 20-day mean (0 for CoinGecko-sourced bars)
    if len(vols) >= 21 and sum(vols[-21:-1]) > 0:
        ind['vol_ratio'] = vols[-1] / (sum(vols[-21:-1]) / 20.0)
    # distance from the 20-day mean, in ATR units — the mean-reversion stretch
    if ind['sma20'] and ind['atr_pct']:
        atr_abs = ind['atr_pct'] / 100.0 * last
        if atr_abs:
            ind['stretch_atr'] = (last - ind['sma20']) / atr_abs
    if ind['hi_52w'] and ind['lo_52w'] and ind['hi_52w'] > ind['lo_52w']:
        ind['pos_52w'] = (last - ind['lo_52w']) / (ind['hi_52w'] - ind['lo_52w']) * 100.0
    return ind


# ── scoring: direction, horizon, and the drivers the narration must cite ────


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


_CHART_BARS = 170  # visible window on the episode chart


def _overlay_series(bars: list, tail: int) -> dict:
    """Chart overlays computed on the full history, sliced to the visible window.

    Values are None where the full lookback does not exist yet, so the chart
    simply starts that line later instead of drawing a short-window average under
    a long-window label.
    """
    closes = [b['c'] for b in bars]
    n = len(closes)
    out = {}
    for key, win in (('sma20', 20), ('sma50', 50), ('sma200', 200)):
        ser = [None] * n
        run = 0.0
        for i, c in enumerate(closes):
            run += c
            if i >= win:
                run -= closes[i - win]
            if i >= win - 1:
                ser[i] = run / win
        out[key] = ser[-tail:]
    rsi = [None] * n
    if n >= 15:
        gains = losses = 0.0
        for i in range(1, 15):
            d = closes[i] - closes[i - 1]
            gains += max(d, 0.0)
            losses += max(-d, 0.0)
        ag, al = gains / 14.0, losses / 14.0
        rsi[14] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
        for i in range(15, n):  # Wilder smoothing
            d = closes[i] - closes[i - 1]
            ag = (ag * 13 + max(d, 0.0)) / 14.0
            al = (al * 13 + max(-d, 0.0)) / 14.0
            rsi[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    out['rsi14'] = rsi[-tail:]
    return out


def score_symbol(meta: dict, bars: list) -> dict:
    """Decide direction + horizon from the bars alone and record WHY.

    Returns a pick dict. `drivers` is the evidence list — every entry carries the
    measured number that produced it, and the narration writer may only rephrase
    those entries, never add to them.

    `long_score` reads the 60-200 day structure (trend alignment, half-year
    momentum, 52-week position). `short_score` reads the 5-20 day structure
    (recent momentum, MACD turn, volume surge, ATR stretch). Whichever is larger
    in absolute terms sets the horizon, which is what makes the "short trade vs
    long trade" split in the episode a measured call and not a label.
    """
    ind = indicators(bars)
    last = ind['last']
    long_score, short_score = 0.0, 0.0
    drivers_long, drivers_short = [], []

    sma50, sma200 = ind.get('sma50'), ind.get('sma200')

    # ── long-horizon structure ───────────────────────────────────────────────
    if sma50 and sma200:
        if last > sma50 > sma200:
            long_score += 2.0
            drivers_long.append(
                (
                    'bull',
                    f'price {last:,.2f} is above its 50-day '
                    f'({sma50:,.2f}) which is above its 200-day '
                    f'({sma200:,.2f}) — a fully stacked uptrend',
                )
            )
        elif last < sma50 < sma200:
            long_score -= 2.0
            drivers_long.append(
                (
                    'bear',
                    f'price {last:,.2f} sits under its 50-day '
                    f'({sma50:,.2f}) and its 200-day ({sma200:,.2f}) '
                    f'— a fully stacked downtrend',
                )
            )
        else:
            gap = _pct(sma50, sma200)
            if gap is not None:
                long_score += _clamp(gap / 6.0, -1.0, 1.0)
                drivers_long.append(
                    ('mixed', f'the 50-day is {gap:+.1f}% versus the 200-day — the trend is still deciding')
                )
    if ind.get('ret_120d') is not None:
        long_score += _clamp(ind['ret_120d'] / 18.0, -1.6, 1.6)
        drivers_long.append(
            (('bull' if ind['ret_120d'] > 0 else 'bear'), f'it is {ind["ret_120d"]:+.1f}% over the last six months')
        )
    if ind.get('pos_52w') is not None:
        p = ind['pos_52w']
        if p >= 88:
            long_score += 0.9
            drivers_long.append(
                ('bull', f'it is trading at {p:.0f}% of its 52-week range — right up against the highs')
            )
        elif p <= 12:
            long_score -= 0.5
            drivers_long.append(('bear', f'it is at just {p:.0f}% of its 52-week range — pinned near the lows'))

    # ── short-horizon structure ──────────────────────────────────────────────
    if ind.get('ret_20d') is not None:
        short_score += _clamp(ind['ret_20d'] / 7.0, -1.8, 1.8)
        drivers_short.append(
            (('bull' if ind['ret_20d'] > 0 else 'bear'), f'it has moved {ind["ret_20d"]:+.1f}% in the last month')
        )
    if ind.get('ret_5d') is not None:
        short_score += _clamp(ind['ret_5d'] / 4.0, -1.2, 1.2)
    if ind.get('macd_hist') is not None:
        mh, mp = ind['macd_hist'], ind.get('macd_hist_prev')
        short_score += _clamp(mh / (0.01 * last if last else 1), -1.2, 1.2)
        if mp is not None and mh > 0 >= mp:
            short_score += 0.7
            drivers_short.append(('bull', 'MACD has just crossed back above its signal line — momentum turning up'))
        elif mp is not None and mh < 0 <= mp:
            short_score -= 0.7
            drivers_short.append(('bear', 'MACD has just crossed below its signal line — momentum turning down'))
    rsi = ind.get('rsi14')
    if rsi is not None:
        if rsi >= 70:
            short_score -= 0.8
            drivers_short.append(
                ('bear', f'RSI is {rsi:.0f} — overbought, and that is where short-term pullbacks start')
            )
        elif rsi <= 30:
            short_score += 0.8
            drivers_short.append(('bull', f'RSI is {rsi:.0f} — oversold, which is where bounces tend to begin'))
        else:
            short_score += (rsi - 50) / 40.0
            drivers_short.append(('mixed', f'RSI sits at {rsi:.0f} — neither stretched nor washed out'))
    if ind.get('stretch_atr') is not None:
        st = ind['stretch_atr']
        if abs(st) >= 2.0:
            short_score -= _clamp(st / 3.0, -1.0, 1.0)
            drivers_short.append(
                (
                    ('bear' if st > 0 else 'bull'),
                    f'it is {abs(st):.1f} average ranges '
                    f'{"above" if st > 0 else "below"} its 20-day mean — '
                    f'stretched, and stretched moves snap back',
                )
            )
    if ind.get('vol_ratio'):
        vr = ind['vol_ratio']
        if vr >= 1.6:
            short_score += 0.5 * (1 if short_score >= 0 else -1)
            drivers_short.append(
                ('mixed', f'volume ran {vr:.1f} times its 20-day average — real money is behind this move')
            )

    # ── horizon + direction ──────────────────────────────────────────────────
    atr = ind.get('atr_pct') or 2.0
    # High realised volatility argues for a trade, not a hold: the position has to
    # be managed on a days-to-weeks clock or the noise takes the thesis out.
    short_bias = 1.0 + _clamp((atr - 2.5) / 5.0, -0.35, 0.9)
    horizon = 'short' if abs(short_score) * short_bias > abs(long_score) else 'long'
    total = (short_score if horizon == 'short' else long_score) * 0.65 + (
        long_score if horizon == 'short' else short_score
    ) * 0.35
    direction = 'up' if total > 0 else 'down'
    conviction = _clamp(abs(total) / 3.2, 0.0, 1.0)

    drivers = (drivers_short + drivers_long) if horizon == 'short' else (drivers_long + drivers_short)
    want = 'bull' if direction == 'up' else 'bear'
    agree = [t for k, t in drivers if k == want]
    against = [t for k, t in drivers if k not in (want, 'mixed')]
    context = [t for k, t in drivers if k == 'mixed']

    return {
        'symbol': meta.get('symbol'),
        'name': meta.get('name') or meta.get('symbol'),
        'kind': meta.get('kind', 'stock'),
        'coin_id': meta.get('coin_id', ''),
        'image': meta.get('image', ''),
        'sector': meta.get('sector', ''),
        'index': meta.get('index', ''),
        'direction': direction,
        'horizon': horizon,  # 'short' trade | 'long' investment
        'conviction': round(conviction, 3),
        'score_total': round(total, 3),
        'score_short': round(short_score, 3),
        'score_long': round(long_score, 3),
        'indicators': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ind.items()},
        'drivers_for': agree[:4],
        'drivers_against': against[:2],
        'drivers_context': context[:2],
        'bars_tail': bars[-_CHART_BARS:],  # what the chart renders
        # Overlays are computed over the FULL history and then sliced to the
        # visible window. Recomputing them from the tail alone would draw a
        # 200-day average that only exists for the last few sessions and whose
        # first values are really 60-day averages wearing a 200-day label.
        'overlays': _overlay_series(bars, _CHART_BARS),
        'as_of': ind['date'],
    }


# ── the screen ──────────────────────────────────────────────────────────────


def _recent_symbols(days: int) -> set:
    cutoff = _now_utc() - timedelta(days=max(0, days))
    out = set()
    for h in (_load(_HISTORY_PATH, {}) or {}).get('picks', []):
        try:
            when = datetime.strptime(h.get('at', '')[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('history entry with an unparsable date skipped: %s', _exc)
            continue
        if when >= cutoff:
            out.add((h.get('kind'), h.get('symbol')))
    return out


def screen(kind: str = 'stock', want: int = 11, log=None, stop=None) -> list:
    """Rank the universe and return the top `want` picks, best conviction first.

    Both directions are kept: a well-argued "this is rolling over" is as much a
    pick as a breakout, and the episode is more honest for carrying both.
    """
    s = settings()
    if kind == 'crypto':
        rows = crypto_universe()
        for r in rows:
            r['kind'] = 'crypto'
    else:
        rows = universe()
        for r in rows:
            r['kind'] = 'stock'
    if log:
        log('INFO', f'{kind} universe: {len(rows)} names')

    cooldown = _recent_symbols(int(s.get('republish_cooldown_days') or 5))
    scored, misses = [], 0
    for i, meta in enumerate(rows):
        if stop and stop():
            break
        if (kind, meta.get('symbol')) in cooldown:
            continue
        bars, prov = fetch_bars(meta['symbol'], kind=kind, coin_id=meta.get('coin_id', ''), log=log)
        if len(bars) < 60:
            misses += 1
            continue
        try:
            pick = score_symbol(meta, bars)
        except Exception as e:
            if log:
                log('WARNING', f'scoring {meta.get("symbol")} failed: {e!r}')
            continue
        pick['provider'] = prov
        scored.append(pick)
        if log and (i + 1) % 50 == 0:
            log('INFO', f'screened {i + 1}/{len(rows)} ({len(scored)} scored, {misses} without data)')
        if 'cache' not in prov:
            time.sleep(0.15)  # be a polite client on the keyless providers

    if log:
        log(
            'INFO',
            f'{kind} screen complete: {len(scored)} scored, {misses} skipped '
            f'(no data), {len(cooldown)} on republish cooldown',
        )
    scored.sort(key=lambda p: p['conviction'], reverse=True)

    # Balance the tape: never ship an episode that is seven identical breakouts.
    # Every third slot goes to a bearish call when one is available; otherwise the
    # ranking stands. Both lists are already conviction-ordered.
    ups = [p for p in scored if p['direction'] == 'up']
    downs = [p for p in scored if p['direction'] == 'down']
    out, i_u, i_d = [], 0, 0
    while len(out) < want:
        if (len(out) + 1) % 3 == 0 and i_d < len(downs):
            out.append(downs[i_d])
            i_d += 1
        elif i_u < len(ups):
            out.append(ups[i_u])
            i_u += 1
        elif i_d < len(downs):
            out.append(downs[i_d])
            i_d += 1
        else:
            break
    return out


# ── ice-box: researched picks deliberately held back for telegram / X ───────


def icebox() -> list:
    with _LOCK:
        return (_load(_ICEBOX_PATH, {}) or {}).get('items', [])


def icebox_add(picks: list, channel: str) -> int:
    """Park picks for the socials. Keyed by (channel, symbol) so the same name is
    never held twice; the newest research always wins."""
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        items = d.get('items') or []
        by_key = {(i.get('channel'), i.get('symbol')): i for i in items}
        for p in picks or []:
            key = (channel, p.get('symbol'))
            by_key[key] = {
                'channel': channel,
                'symbol': p.get('symbol'),
                'name': p.get('name'),
                'kind': p.get('kind'),
                'direction': p.get('direction'),
                'horizon': p.get('horizon'),
                'conviction': p.get('conviction'),
                'as_of': p.get('as_of'),
                'last': (p.get('indicators') or {}).get('last'),
                'why': (p.get('drivers_for') or [])[:2],
                'social_text': social_text(p, channel),
                'added_at': _iso(),
                'used': False,
                'used_at': '',
            }
        d['items'] = sorted(by_key.values(), key=lambda i: i.get('added_at', ''), reverse=True)[:60]
        _save(_ICEBOX_PATH, d)
        return len(picks or [])


def icebox_mark_used(channel: str, symbol: str) -> bool:
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        hit = False
        for i in d.get('items') or []:
            if i.get('channel') == channel and i.get('symbol') == symbol:
                i['used'] = True
                i['used_at'] = _iso()
                hit = True
        _save(_ICEBOX_PATH, d)
        return hit


def icebox_delete(channel: str, symbol: str) -> bool:
    with _LOCK:
        d = _load(_ICEBOX_PATH, {}) or {}
        before = len(d.get('items') or [])
        d['items'] = [
            i for i in (d.get('items') or []) if not (i.get('channel') == channel and i.get('symbol') == symbol)
        ]
        _save(_ICEBOX_PATH, d)
        return len(d['items']) < before


def social_text(pick: dict, channel: str) -> str:
    """The ready-to-paste telegram/X line for a held-back pick."""
    ind = pick.get('indicators') or {}
    arrow = '📈' if pick.get('direction') == 'up' else '📉'
    horizon = 'SHORT-TERM TRADE' if pick.get('horizon') == 'short' else 'LONG-TERM HOLD'
    why = (pick.get('drivers_for') or [''])[0]
    px = ind.get('last')
    return (
        f'{arrow} {pick.get("symbol")} — {pick.get("name")}\n'
        f'{horizon} · {"upside" if pick.get("direction") == "up" else "downside"} '
        f'· conviction {round(float(pick.get("conviction") or 0) * 100)}%\n'
        f'{("Last $%s. " % f"{px:,.2f}") if px else ""}{why[:1].upper() + why[1:] if why else ""}\n'
        f'Not financial advice. Free tips daily on {channel}.'
    )


def history_add(picks: list, channel: str, job_id: str) -> None:
    with _LOCK:
        d = _load(_HISTORY_PATH, {}) or {}
        rows = d.get('picks') or []
        for p in picks or []:
            rows.append(
                {
                    'at': _iso(),
                    'job_id': job_id,
                    'channel': channel,
                    'kind': p.get('kind'),
                    'symbol': p.get('symbol'),
                    'name': p.get('name'),
                    'direction': p.get('direction'),
                    'horizon': p.get('horizon'),
                    'conviction': p.get('conviction'),
                    'last': (p.get('indicators') or {}).get('last'),
                }
            )
        d['picks'] = rows[-2000:]
        _save(_HISTORY_PATH, d)


def history(limit: int = 120) -> list:
    return list(reversed((_load(_HISTORY_PATH, {}) or {}).get('picks', [])))[:limit]
