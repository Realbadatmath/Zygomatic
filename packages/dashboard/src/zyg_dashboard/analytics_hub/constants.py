# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module imports, paths and the tuning constants of the Analytics collector."""

# ruff: noqa: F401 — the original module header, re-exported by __init__

from __future__ import annotations

import csv
import glob
import hashlib
import json
import logging as _zyg_logging
import math
import os
import re
import time
from datetime import datetime, timedelta

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the zyg_dashboard package dir
from zyg_dashboard import metrics_hub as mh  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__package__)


RUNTIME = mh.RUNTIME
DAY = mh.DAY
TZ = mh.TZ
CONFIG_PATH = os.path.join(RUNTIME, 'analytics_config.json')
SYSUSAGE_PATH = os.path.join(RUNTIME, 'system_usage.jsonl')
CACHE_DIR = os.path.join(RUNTIME, 'analytics_cache')
TELEMETRY_CACHE = os.path.join(CACHE_DIR, 'telemetry_daily.json')
TREND_DAYS = 56
HORIZON_DAYS = 30
GPU_BUSY_UTIL = 20.0  # a minute counts as "busy" at or above this mean utilisation
INFER_MIN_S, INFER_MAX_S = 20, 36 * 3600

DEFAULT_CONFIG = {
    'views_per_content': 1000,  # the operator's floor: "a minimal of 1k views per generated content"
    'rpm_usd': 2.0,  # gross revenue per 1 000 views — an assumption, see the card
    'rpm_scenarios': [0.5, 1.0, 2.0, 5.0, 10.0],
    'kwh_price_eur': 0.30,
    'active_hours_per_day': 24,
    'eur_per_usd': None,  # None -> quota_config.json value
}

CONTENT_KINDS = {
    'scholarly': 'Scholarly documentary',
    'crime': 'Crime documentary',
    'storyteller': 'Storyteller episode',
    'kidsmusic': 'Kids music video',
    'tokitoki': 'TokiToki episode',
    'remix_ai': 'Remix AI clip',
    'video': 'Video pipeline',
    'manga': 'Manga',
    'clipfarm': 'Clipfarm',
    'stocks': 'Stocks',
}
ASSET_KINDS = {'character': 'Character', 'creature': 'Creature', 'contact_sheet': 'Contact sheet'}
API = ('anthropic_api', 'openai_api')
