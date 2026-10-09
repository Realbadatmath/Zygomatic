# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  # this module keeps the original top import block for its siblings and the package

from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
import logging as _zyg_logging

from zyg_workflows import paths as _paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.market_ingest')


_CREWS = str(_paths.PKG_DIR)
_RUNTIME = str(_paths.DATA_DIR / 'runtime')
_CACHE_DIR = os.path.join(_RUNTIME, 'market_cache')

_SETTINGS_PATH = os.path.join(_RUNTIME, 'market_settings.json')
_UNIVERSE_PATH = os.path.join(_RUNTIME, 'market_universe.json')
_ICEBOX_PATH = os.path.join(_RUNTIME, 'market_icebox.json')
_HISTORY_PATH = os.path.join(_RUNTIME, 'market_history.json')

_LOCK = threading.RLock()

_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
_HDRS = {'User-Agent': _UA, 'Accept': 'application/json,text/csv,*/*'}

DEFAULT_SETTINGS = {
    # ── scheduling ───────────────────────────────────────────────────────────
    'auto_mode': False,  # daily scheduler may start episodes by itself
    'stocks_run_at': '07:00',  # local time, daily
    'crypto_run_at': '08:00',
    # ── episode shape (operator decision 2026-08-06: 6-9 picks, 8-12 min) ────
    'picks_per_episode': 7,
    'icebox_hold': 2,  # picks researched but withheld for telegram/X
    'research_depth': 11,  # picks_per_episode + icebox_hold + spare
    'opening_chart_seconds': 10,  # spec: hold the board 10 s over the welcome
    'republish_cooldown_days': 5,  # do not re-pick the same symbol inside this
    # ── universe ─────────────────────────────────────────────────────────────
    'stock_universe': 'sp500_ndx',  # sp500_ndx | watchlist
    'stock_watchlist': [],  # used when stock_universe == 'watchlist'
    'crypto_top_n': 120,  # CoinGecko market-cap rank ceiling to screen
    'crypto_exclude': [
        'tether',
        'usd-coin',
        'dai',
        'first-digital-usd',
        'ethena-usde',
        'binance-peg-busd',
        'paypal-usd',
        'staked-ether',
        'wrapped-bitcoin',
        'wrapped-steth',
        'weth',
        'wrapped-eeth',
        'coinbase-wrapped-btc',
    ],
    # ── data providers ───────────────────────────────────────────────────────
    'twelvedata_key': '',  # free key at twelvedata.com — used as the
    'twelvedata_rpm': 8,  # RELIABLE FALLBACK; free tier is 8 req/min
    'twelvedata_first': False,  # flip to make it primary (slow: ~65 min screen)
    'alphavantage_key': '',
    'price_cache_hours': 8,
    # ── voices (seed-pool names, see data/assets/voice_seeds/pool) ───────────
    'stocks_voice': 'm04_british_crisp',
    'crypto_voice': 'm02_bright_tenor',
    # ── retention ────────────────────────────────────────────────────────────
    'delivery_ttl_hours': 72,  # spec: delete after 3 days
}

# Static fallback universe — used only when BOTH constituent sources are
# unreachable, so an episode never dies on a cold network. Mega caps only.
_STATIC_UNIVERSE = [
    'AAPL',
    'MSFT',
    'NVDA',
    'AMZN',
    'GOOGL',
    'META',
    'AVGO',
    'TSLA',
    'BRK.B',
    'JPM',
    'LLY',
    'V',
    'XOM',
    'UNH',
    'MA',
    'COST',
    'HD',
    'PG',
    'JNJ',
    'WMT',
    'NFLX',
    'ABBV',
    'CRM',
    'BAC',
    'ORCL',
    'CVX',
    'MRK',
    'KO',
    'AMD',
    'PEP',
    'ADBE',
    'LIN',
    'TMO',
    'ACN',
    'MCD',
    'CSCO',
    'ABT',
    'INTU',
    'QCOM',
    'TXN',
    'DIS',
    'CAT',
    'GE',
    'VZ',
    'INTC',
    'AMAT',
    'PFE',
    'IBM',
    'NOW',
    'UBER',
]

_SP500_CSV = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'
# Wikipedia's Nasdaq-100 article no longer carries the components table inline
# (verified 2026-08-06 — the section list has no "Components" entry), so the
# constituents come from Nasdaq's own list endpoint instead.
_NDX_LIST = 'https://api.nasdaq.com/api/quote/list-type/nasdaq100'


# ── tiny io helpers (remix_ingest.py:69-85 shape) ───────────────────────────


def _load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default() if callable(default) else default


def _save(path, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as _exc:
        _zyg_log.warning('json write to %s failed, the file keeps its previous contents: %s', path, _exc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime = None) -> str:
    return (dt or _now_utc()).strftime('%Y-%m-%dT%H:%M:%S%z')


def settings() -> dict:
    with _LOCK:
        s = dict(DEFAULT_SETTINGS)
        s.update(_load(_SETTINGS_PATH, {}))
        return s


def update_settings(patch: dict) -> dict:
    with _LOCK:
        s = _load(_SETTINGS_PATH, {})
        for k, v in (patch or {}).items():
            if k in DEFAULT_SETTINGS:
                s[k] = v
        _save(_SETTINGS_PATH, s)
    return settings()


def _get(url, params=None, timeout=20, as_json=True):
    """One guarded HTTP GET. Returns parsed json / text, or None. Never raises."""
    try:
        r = requests.get(url, params=params, headers=_HDRS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json() if as_json else r.text
    except Exception:
        return None


# ── universe ────────────────────────────────────────────────────────────────


def _fetch_sp500() -> list:
    txt = _get(_SP500_CSV, as_json=False, timeout=25)
    if not txt:
        return []
    out = []
    try:
        for row in csv.DictReader(io.StringIO(txt)):
            sym = (row.get('Symbol') or '').strip()
            if sym:
                out.append(
                    {
                        'symbol': sym,
                        'name': (row.get('Security') or sym).strip(),
                        'sector': (row.get('GICS Sector') or '').strip(),
                        'index': 'S&P 500',
                    }
                )
    except Exception:
        return []
    return out


_NAME_SUFFIX_RE = re.compile(
    r'\s+(?:Common Stock|Class [A-C] (?:Common Stock|Ordinary Shares)|'
    r'Ordinary Shares?|American Depositary Shares?|Inc\.?|Corporation|'
    r'Corp\.?|Incorporated)\b.*$',
    re.I,
)


def _clean_company(name: str) -> str:
    """'Apple Inc. Common Stock' → 'Apple'. Spoken narration should say the name
    a viewer would recognise, not the security's legal designation."""
    n = _NAME_SUFFIX_RE.sub('', (name or '').strip()).strip(' ,.')
    return n or (name or '').strip()


def _fetch_ndx() -> list:
    d = _get(_NDX_LIST, timeout=25)
    rows = []
    try:
        data = d.get('data') or {}
        rows = (data.get('data') or {}).get('rows') or data.get('rows') or []
    except Exception:
        return []
    out, seen = [], set()
    for r in rows:
        sym = (r.get('symbol') or '').strip().upper()
        if not sym or sym in seen or len(sym) > 6:
            continue
        seen.add(sym)
        out.append(
            {
                'symbol': sym,
                'name': _clean_company(r.get('companyName') or sym),
                'sector': (r.get('sector') or '').strip(),
                'index': 'Nasdaq-100',
            }
        )
    return out if len(out) >= 50 else []


def universe(force_refresh: bool = False) -> list:
    """[{symbol, name, sector, index}] — S&P 500 ∪ Nasdaq-100, cached 7 days.

    Falls back to the last good cache, then to _STATIC_UNIVERSE. An empty return
    is impossible by construction: the screen must never be blocked by a
    constituent-list outage.
    """
    s = settings()
    with _LOCK:
        cached = _load(_UNIVERSE_PATH, {})

    if (s.get('stock_universe') or 'sp500_ndx') == 'watchlist':
        wl = [w.strip().upper() for w in (s.get('stock_watchlist') or []) if str(w).strip()]
        # Borrow the company name and sector from the constituent cache when the
        # ticker is in it — otherwise the chart title and the spoken narration
        # both read "NVDA — NVDA", which is what a watchlist run produced before.
        known = {r['symbol']: r for r in (cached.get('rows') or [])}
        return [
            {
                'symbol': w,
                'name': (known.get(w) or {}).get('name') or w,
                'sector': (known.get(w) or {}).get('sector') or '',
                'index': 'watchlist',
            }
            for w in wl
        ]

    age_ok = False
    try:
        age_ok = (time.time() - float(cached.get('fetched_ts') or 0)) < 7 * 86400
    except Exception:
        age_ok = False
    if cached.get('rows') and age_ok and not force_refresh:
        return cached['rows']

    rows, by_sym = [], {}
    for r in _fetch_sp500() + _fetch_ndx():
        sym = r['symbol'].upper()
        if sym in by_sym:
            if r['index'] not in by_sym[sym]['index']:
                by_sym[sym]['index'] += ' + ' + r['index']
            continue
        by_sym[sym] = dict(r)
    rows = list(by_sym.values())

    if len(rows) >= 100:
        with _LOCK:
            _save(_UNIVERSE_PATH, {'fetched_ts': time.time(), 'fetched_at': _iso(), 'rows': rows})
        return rows
    if cached.get('rows'):
        return cached['rows']
    return [{'symbol': s_, 'name': s_, 'sector': '', 'index': 'fallback'} for s_ in _STATIC_UNIVERSE]


def crypto_universe(force_refresh: bool = False) -> list:
    """Top-N CoinGecko coins by market cap, stablecoins/wrappers removed.

    Carries `image` (the CoinGecko logo URL) so the video engine can show a real
    coin mark instead of a text placeholder.
    """
    s = settings()
    top_n = int(s.get('crypto_top_n') or 120)
    excl = set(s.get('crypto_exclude') or [])
    rows, page = [], 1
    while len(rows) < top_n and page <= 3:
        d = _get(
            'https://api.coingecko.com/api/v3/coins/markets',
            params={
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': 100,
                'page': page,
                'price_change_percentage': '24h,7d,30d',
            },
            timeout=25,
        )
        if not isinstance(d, list) or not d:
            break
        for c in d:
            cid = (c.get('id') or '').lower()
            if cid in excl or not cid:
                continue
            # Stablecoins have no tradeable thesis — drop anything pinned to $1.
            price = float(c.get('current_price') or 0)
            chg = abs(float(c.get('price_change_percentage_24h') or 0))
            if 0.985 <= price <= 1.015 and chg < 0.6:
                continue
            rows.append(
                {
                    'symbol': (c.get('symbol') or '').upper(),
                    'coin_id': cid,
                    'name': c.get('name') or cid,
                    'sector': f'rank #{c.get("market_cap_rank")}',
                    'index': 'CoinGecko top-%d' % top_n,
                    'image': c.get('image') or '',
                    'market_cap': c.get('market_cap') or 0,
                    'volume_24h': c.get('total_volume') or 0,
                    'chg_24h': c.get('price_change_percentage_24h'),
                    'chg_7d': c.get('price_change_percentage_7d_in_currency'),
                    'chg_30d': c.get('price_change_percentage_30d_in_currency'),
                }
            )
        page += 1
        time.sleep(1.2)  # CoinGecko public tier — stay well under the limit
    return rows[:top_n]
