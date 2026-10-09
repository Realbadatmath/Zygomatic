# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.market_ingest.core import (
    _CACHE_DIR,
    _get,
    _iso,
    _load,
    _now_utc,
    _save,
    _zyg_log,
    datetime,
    os,
    re,
    settings,
    threading,
    time,
    timedelta,
    timezone,
)

# ── price history: cache + provider chain ───────────────────────────────────


def _cache_path(kind, symbol) -> str:
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', f'{kind}_{symbol}')
    return os.path.join(_CACHE_DIR, f'{safe}.json')


def _cache_get(kind, symbol):
    p = _cache_path(kind, symbol)
    d = _load(p, None)
    if not d or not d.get('bars'):
        return None
    ttl_h = float(settings().get('price_cache_hours') or 8)
    try:
        if (time.time() - float(d.get('ts') or 0)) > ttl_h * 3600:
            return None
    except Exception:
        return None
    return d


def _cache_put(kind, symbol, bars, provider):
    _save(
        _cache_path(kind, symbol),
        {'ts': time.time(), 'at': _iso(), 'provider': provider, 'symbol': symbol, 'kind': kind, 'bars': bars},
    )


def _norm_bars(rows) -> list:
    """Sort ascending by date, drop malformed/zero rows, keep the last 400."""
    out = []
    for b in rows or []:
        try:
            o, h, l, c = float(b['o']), float(b['h']), float(b['l']), float(b['c'])
            if c <= 0 or h <= 0:
                continue
            out.append({'d': str(b['d'])[:10], 'o': o, 'h': h, 'l': l, 'c': c, 'v': float(b.get('v') or 0)})
        except (KeyError, TypeError, ValueError) as _exc:
            _zyg_log.debug('malformed price bar skipped: %s', _exc)
            continue
    out.sort(key=lambda x: x['d'])
    # collapse duplicate dates (providers occasionally repeat the latest bar)
    dedup, last_d = [], None
    for b in out:
        if b['d'] == last_d:
            dedup[-1] = b
        else:
            dedup.append(b)
            last_d = b['d']
    return dedup[-400:]


# --- stocks -----------------------------------------------------------------

_TD_CALLS: list = []
_TD_LOCK = threading.Lock()


def _twelvedata_throttle(rpm: int) -> None:
    """Block until a Twelve Data request is allowed.

    The free "basic" plan is 800 requests/day but only **8 per minute** (measured
    2026-08-06 via /api_usage: plan_limit 8, plan_daily_limit 800). Without this
    the screen fires ~7 requests a second and every one after the eighth comes
    back 429, which the provider chain would read as "twelvedata is down" and
    silently fall through for the rest of the run.
    """
    if rpm <= 0:
        return
    while True:
        with _TD_LOCK:
            now = time.time()
            _TD_CALLS[:] = [t for t in _TD_CALLS if now - t < 60.0]
            if len(_TD_CALLS) < rpm:
                _TD_CALLS.append(now)
                return
            wait = 60.0 - (now - _TD_CALLS[0]) + 0.05
        time.sleep(max(0.1, min(wait, 30.0)))


def _p_twelvedata(symbol, key):
    _twelvedata_throttle(int(settings().get('twelvedata_rpm') or 8))
    d = _get(
        'https://api.twelvedata.com/time_series',
        params={'symbol': symbol, 'interval': '1day', 'outputsize': 400, 'apikey': key, 'format': 'JSON'},
        timeout=25,
    )
    if not isinstance(d, dict) or d.get('status') == 'error':
        return None
    vals = d.get('values') or []
    return (
        _norm_bars(
            [
                {
                    'd': v.get('datetime'),
                    'o': v.get('open'),
                    'h': v.get('high'),
                    'l': v.get('low'),
                    'c': v.get('close'),
                    'v': v.get('volume'),
                }
                for v in vals
            ]
        )
        or None
    )


def _p_stockanalysis(symbol):
    d = _get(
        f'https://stockanalysis.com/api/symbol/s/{symbol.lower()}/history',
        params={'range': '2Y', 'period': 'Daily'},
        timeout=25,
    )
    if not isinstance(d, dict) or d.get('status') != 200:
        return None
    return (
        _norm_bars(
            [
                {'d': r.get('t'), 'o': r.get('o'), 'h': r.get('h'), 'l': r.get('l'), 'c': r.get('c'), 'v': r.get('v')}
                for r in (d.get('data') or [])
            ]
        )
        or None
    )


def _p_nasdaq(symbol):
    to_d = _now_utc().date()
    from_d = to_d - timedelta(days=560)
    d = _get(
        f'https://api.nasdaq.com/api/quote/{symbol.upper()}/historical',
        params={'assetclass': 'stocks', 'fromdate': from_d.isoformat(), 'todate': to_d.isoformat(), 'limit': 400},
        timeout=25,
    )
    try:
        rows = d['data']['tradesTable']['rows']
    except Exception:
        return None

    def _n(x):
        return float(str(x).replace('$', '').replace(',', '').strip() or 0)

    out = []
    for r in rows:
        try:
            dt = datetime.strptime(r['date'], '%m/%d/%Y').date().isoformat()
            out.append(
                {
                    'd': dt,
                    'o': _n(r.get('open')),
                    'h': _n(r.get('high')),
                    'l': _n(r.get('low')),
                    'c': _n(r.get('close')),
                    'v': _n(r.get('volume')),
                }
            )
        except (KeyError, TypeError, ValueError) as _exc:
            _zyg_log.debug('malformed price bar skipped: %s', _exc)
            continue
    return _norm_bars(out) or None


def _p_alphavantage(symbol, key):
    d = _get(
        'https://www.alphavantage.co/query',
        params={'function': 'TIME_SERIES_DAILY', 'symbol': symbol, 'outputsize': 'full', 'apikey': key},
        timeout=30,
    )
    ts = (d or {}).get('Time Series (Daily)') or {}
    return (
        _norm_bars(
            [
                {
                    'd': k,
                    'o': v.get('1. open'),
                    'h': v.get('2. high'),
                    'l': v.get('3. low'),
                    'c': v.get('4. close'),
                    'v': v.get('5. volume'),
                }
                for k, v in ts.items()
            ]
        )
        or None
    )


# --- crypto -----------------------------------------------------------------

_BINANCE_QUOTE = 'USDT'


def _p_binance(symbol):
    d = _get(
        'https://api.binance.com/api/v3/klines',
        params={'symbol': f'{symbol.upper()}{_BINANCE_QUOTE}', 'interval': '1d', 'limit': 400},
        timeout=25,
    )
    if not isinstance(d, list) or len(d) < 60:
        return None
    return (
        _norm_bars(
            [
                {
                    'd': datetime.fromtimestamp(k[0] / 1000, timezone.utc).date().isoformat(),
                    'o': k[1],
                    'h': k[2],
                    'l': k[3],
                    'c': k[4],
                    'v': k[5],
                }
                for k in d
            ]
        )
        or None
    )


def _p_coinbase(symbol):
    # Coinbase caps a candles response at 300 rows; two windows cover 400 days.
    bars = []
    end = _now_utc()
    for _ in range(2):
        start = end - timedelta(days=290)
        d = _get(
            f'https://api.exchange.coinbase.com/products/{symbol.upper()}-USD/candles',
            params={'granularity': 86400, 'start': start.isoformat(), 'end': end.isoformat()},
            timeout=25,
        )
        if not isinstance(d, list) or not d:
            break
        for k in d:  # [time, low, high, open, close, volume]
            try:
                bars.append(
                    {
                        'd': datetime.fromtimestamp(k[0], timezone.utc).date().isoformat(),
                        'o': k[3],
                        'h': k[2],
                        'l': k[1],
                        'c': k[4],
                        'v': k[5],
                    }
                )
            except Exception as _exc:
                _zyg_log.debug('malformed kraken candle skipped: %s', _exc)
                continue
        end = start - timedelta(days=1)
        time.sleep(0.4)
    return _norm_bars(bars) or None


_KRAKEN_ALIAS = {'BTC': 'XBT'}


def _p_kraken(symbol):
    pair = f'{_KRAKEN_ALIAS.get(symbol.upper(), symbol.upper())}USD'
    d = _get('https://api.kraken.com/0/public/OHLC', params={'pair': pair, 'interval': 1440}, timeout=25)
    try:
        res = d['result']
        key = next(k for k in res if k != 'last')
        rows = res[key]
    except Exception:
        return None
    return (
        _norm_bars(
            [
                {
                    'd': datetime.fromtimestamp(r[0], timezone.utc).date().isoformat(),
                    'o': r[1],
                    'h': r[2],
                    'l': r[3],
                    'c': r[4],
                    'v': r[6],
                }
                for r in rows
            ]
        )
        or None
    )


def _p_coingecko_ohlc(coin_id):
    d = _get(
        f'https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc', params={'vs_currency': 'usd', 'days': 365}, timeout=25
    )
    if not isinstance(d, list) or len(d) < 40:
        return None
    return (
        _norm_bars(
            [
                {
                    'd': datetime.fromtimestamp(k[0] / 1000, timezone.utc).date().isoformat(),
                    'o': k[1],
                    'h': k[2],
                    'l': k[3],
                    'c': k[4],
                    'v': 0,
                }
                for k in d
            ]
        )
        or None
    )


def fetch_bars(symbol: str, kind: str = 'stock', coin_id: str = '', log=None) -> 'tuple[list, str]':
    """(bars, provider). Cache first, then the chain. ([], '') when all fail."""
    cached = _cache_get(kind, symbol)
    if cached:
        return cached['bars'], cached['provider'] + ' (cache)'

    s = settings()
    bars, provider = None, ''
    if kind == 'crypto':
        chain = [
            ('binance', lambda: _p_binance(symbol)),
            ('coinbase', lambda: _p_coinbase(symbol)),
            ('kraken', lambda: _p_kraken(symbol)),
        ]
        if coin_id:
            chain.append(('coingecko', lambda: _p_coingecko_ohlc(coin_id)))
    else:
        # Order is throughput-first, not preference-first. Twelve Data is the most
        # dependable source here (real contract, real SLA) but its free tier caps
        # at 8 requests/minute — carrying the whole 517-name screen on it would
        # take ~65 minutes every morning. So the unmetered sources go first and
        # Twelve Data covers whatever they miss or lose, which is a handful of
        # names rather than five hundred. Set `twelvedata_first` to flip it.
        td_key = (s.get('twelvedata_key') or '').strip()
        td = [('twelvedata', lambda: _p_twelvedata(symbol, td_key))] if td_key else []
        keyless = [('stockanalysis', lambda: _p_stockanalysis(symbol)), ('nasdaq', lambda: _p_nasdaq(symbol))]
        chain = (td + keyless) if s.get('twelvedata_first') else (keyless + td)
        if (s.get('alphavantage_key') or '').strip():
            chain.append(('alphavantage', lambda: _p_alphavantage(symbol, s['alphavantage_key'].strip())))

    for name, fn in chain:
        try:
            bars = fn()
        except Exception as e:
            if log:
                log('WARNING', f'{name} raised on {symbol}: {e!r}')
            bars = None
        if bars and len(bars) >= 60:
            provider = name
            break
    if not bars:
        return [], ''
    _cache_put(kind, symbol, bars, provider)
    return bars, provider
