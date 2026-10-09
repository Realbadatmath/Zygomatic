# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""market_ingest.py — universe, price history, indicators and pick-scoring for the
Stockmarket and Cryptodaily departments (2026-08-06).

Standalone module: NO crewai_web_gui import anywhere (safe to import at module
scope from bp_market and pipeline_market). Only stdlib + requests.

State files (data/runtime/, atomic tmp+os.replace, module RLock):
  market_settings.json    — operator settings incl. auto_mode, per-channel voice
  market_universe.json    — cached S&P500 + Nasdaq-100 constituents (weekly refresh)
  market_icebox.json      — researched picks deliberately HELD BACK for telegram/X
  market_history.json     — every published pick (cooldown + "we called this" recall)
  market_cache/*.json     — per-symbol daily OHLCV, TTL-capped

WHY THE NUMBERS ARE COMPUTED HERE AND NOT BY THE LLM
Every figure that reaches the narration (RSI, moving averages, returns, ATR,
volume ratios, the direction verdict itself) is computed in `indicators()` /
`score_symbol()` from the raw bars. The LLM only ever turns an already-decided,
already-measured `drivers` list into spoken English. An LLM that is allowed to
invent a price target will invent one, and on a finance channel that is the one
class of error you cannot walk back.

PROVIDER CHAIN (measured 2026-08-06 from this host)
  stocks : stockanalysis → nasdaq → twelvedata(key) → alphavantage(key)
           * Yahoo (query1/query2 finance chart) hard-429s this IP — unusable.
           * Stooq now sits behind a JS proof-of-work challenge — unusable.
           * twelvedata free tier = 800/day but only 8 requests/MINUTE (measured
             via /api_usage), so it sits AFTER the unmetered sources: carrying the
             whole 517-name screen on it would take ~65 min every morning. It is
             the dependable safety net for names the keyless sources drop.
             `twelvedata_first: true` flips it if you ever want the SLA over speed.
  crypto : binance → coinbase → kraken → coingecko
           All four are official, documented, keyless public market-data
           endpoints. CoinGecko additionally supplies the ranked universe and the
           coin logos (its /coins/markets image URLs).
"""

# ruff: noqa: E402,F401  # the original top import block and the re-export block are deliberate

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

from zyg_workflows.market_ingest.core import (
    _zyg_log,
    _CREWS,
    _RUNTIME,
    _CACHE_DIR,
    _SETTINGS_PATH,
    _UNIVERSE_PATH,
    _ICEBOX_PATH,
    _HISTORY_PATH,
    _LOCK,
    _UA,
    _HDRS,
    DEFAULT_SETTINGS,
    _STATIC_UNIVERSE,
    _SP500_CSV,
    _NDX_LIST,
    _load,
    _save,
    _now_utc,
    _iso,
    settings,
    update_settings,
    _get,
    _fetch_sp500,
    _NAME_SUFFIX_RE,
    _clean_company,
    _fetch_ndx,
    universe,
    crypto_universe,
)
from zyg_workflows.market_ingest.prices import (
    _cache_path,
    _cache_get,
    _cache_put,
    _norm_bars,
    _TD_CALLS,
    _TD_LOCK,
    _twelvedata_throttle,
    _p_twelvedata,
    _p_stockanalysis,
    _p_nasdaq,
    _p_alphavantage,
    _BINANCE_QUOTE,
    _p_binance,
    _p_coinbase,
    _KRAKEN_ALIAS,
    _p_kraken,
    _p_coingecko_ohlc,
    fetch_bars,
)
from zyg_workflows.market_ingest.picks import (
    _sma,
    _ema_series,
    _rsi,
    _atr_pct,
    _pct,
    indicators,
    _clamp,
    _CHART_BARS,
    _overlay_series,
    score_symbol,
    _recent_symbols,
    screen,
    icebox,
    icebox_add,
    icebox_mark_used,
    icebox_delete,
    social_text,
    history_add,
    history,
)
