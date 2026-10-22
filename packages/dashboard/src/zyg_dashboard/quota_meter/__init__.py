# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402
#   E402: the submodule imports and the shims must follow the original import block,
#         which this file re-does verbatim so old attribute reads still resolve.

"""quota_meter.py — the Claude subscription quota meter and the two costs behind it. 2026-09-17.

Why this exists. Until today every "cost" the GUI showed for Claude Code work was the
CLI's own `total_cost_usd`, labelled "of quota" in the Architecture Studio panel and
"API-equivalent" in the Metrics tab. Measured 2026-09-17 against three real sessions:

  * the number is priced by the CLI that ran the job — /usr/local/bin/claude is 2.1.74
    (March 2026) whose price table stops at Opus 4.6 / Sonnet 4.6. Any newer model is
    "unknown" and priced at the Opus rate: a 49-turn Sonnet 5 job was reported as
    $5.8446; at Sonnet 5 list price it is $2.63 (the CLI's own arithmetic reproduced to
    the cent with its table: input 5, output 25, cache write 6.25, cache read 0.5);
  * it ignores the 1-hour cache-write premium Claude Code actually pays (2x input, not
    1.25x): an Opus 5 job reported as $3.9769 is $4.57 at list;
  * none of it is a quota. The login is a Max subscription: nothing is billed per token,
    and Claude meters usage as PERCENTAGES of a session (5-hour) and a weekly window.

What Claude exposes (GET https://api.anthropic.com/api/oauth/usage with the login's
OAuth token, the same call `/usage` makes in the CLI): `five_hour` and `seven_day`
{utilization %, resets_at}, scoped weekly limits per model family (`limits[]`), the
week's start (`seven_day_breakdown.window_started_at`) and a per-surface split of the
week (Claude Code / Chats / Cowork / Other). The weekly window is a FIXED 7-day window
that resets to 0 % at `resets_at` — the operator's "renewed every week" is right; it
is not a rolling window and it is not a calendar week.

THE TWO COSTS, and the method (every number on the Quota tab comes from these lines):

  1. API-equivalent cost = what the same tokens would have cost on API billing.
     Per model: input, output, cache write (5-minute and 1-hour buckets priced
     separately), cache read and web-search requests at Anthropic list price (table
     PRICING below, checked against the claude-api reference cached 2026-06-24). The
     tokens come from the session transcripts under ~/.claude/projects — every session
     of this login on this machine, interactive and `claude -p` alike, de-duplicated
     by message id (a multi-block message is written once per block, same usage).

  2. Subscription cost = the plan price spread over Claude's own weekly window.
     Weekly price W: the plan bills per calendar month, so W = price x 12 / 52.1775
     (a 28-day "4 weeks = 180 EUR" would count 13 payments a year; `billing_days`
     switches to that basis if the invoices really are every 28 days).
     Consumed this week  = seven_day.utilization % x W        (Claude's number, not ours)
     Cost of one % point = W / 100
     Per model           = consumed x (API-equivalent cost of the model this week
                                       / API-equivalent cost of all models this week)
     The split assumes the meter charges models in proportion to their list price.
     The tab prints the implied "% per API-dollar" so a drift in that assumption is
     visible instead of silent, and the surface split tells how much of the week was
     not Claude Code (chats on claude.ai share the same meter and leave no transcript
     here — that part is attributed to "other surfaces", never to a model).
     Effective rate      = consumed EUR / API-equivalent USD of the week: below the
     EUR/USD rate the subscription is the cheaper way to buy this week's work.

Nothing here refreshes the OAuth token: the CLI does that on any interactive turn. An
expired token is reported as such and the last sample stays on screen.

CLI:  python3 quota_meter.py sample            # one fetch -> data/runtime/quota_samples.jsonl
      python3 quota_meter.py report [--days 7] [--json]
      python3 quota_meter.py scan [--days 7]   # (re)build the transcript cache only
Served by metrics_hub.section('quota') at /api/metrics/hub/quota?days=N.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo('Europe/Amsterdam')
except Exception:  # pragma: no cover
    TZ = timezone.utc
import logging as _zyg_logging

# ── the 2026-10 split ────────────────────────────────────────────────────────
# quota_meter.py became this package. Two shims keep the single-file contract:
#  (1) metrics_hub.llm._quota_meter() asks devreload.maybe_reload() when the file's mtime
#      moves; reload re-executes ONLY this __init__, and the section modules would come
#      back out of sys.modules with their old, env-captured constants. Drop them first.
for _m in [_m for _m in sys.modules if _m.startswith(f'{__name__}.')]:
    del sys.modules[_m]

# the sections, in the order the single module ran them
from .pricing import (
    BUCKET_S,
    CACHE_PATH,
    CACHE_VERSION,
    CONFIG_PATH,
    CRED_PATH,
    CREWS,
    DAY,
    DEFAULT_CONFIG,
    DEFAULT_LANES,
    HOME,
    INTERACTIVE_ENTRYPOINTS,
    LEGACY_CLI_UNKNOWN_MODEL,
    OAUTH_BETA,
    PRICING,
    PROJECTS_DIR,
    QuotaError,
    RUNTIME,
    SAMPLES_PATH,
    SCAN_CAP_DAYS,
    STATUS_PATH,
    TREE_MARKER,
    TREE_MARKER_ROWS,
    TREE_TASK_RE,
    USAGE_KEYS,
    USAGE_URL,
    WEB_SEARCH_USD,
    WEEK,
    WEEKS_PER_MONTH,
    _PRICING_BY_LEN,
    _add,
    _zero,
    _zyg_log,
    load_config,
    model_key,
    price_row,
    price_tokens,
    price_usage,
    price_usage_total,
    usage_from_message,
    weekly_price,
)
from .transcripts import (
    _norm_kw,
    _read_cache_at,
    _slug_words,
    _tree_task,
    _ts_iso,
    _write_json_atomic,
    aggregate,
    aggregate_lanes,
    classify,
    daily_series,
    parse_transcript,
    scan_transcripts,
)
from .calculation import (
    _append_sample,
    _credentials,
    _history,
    _implied_rates,
    _lane_split,
    _limit,
    _write_status,
    compute,
    fetch_usage,
    parse_usage_payload,
    read_samples,
    read_status,
    report,
    sample,
)
from .cli import _fmt_report, _iso, main

#  (2) monkeypatch.setattr(quota_meter, 'CRED_PATH', ...) (tests/test_quota_meter.py:285)
#      used to rebind the one global every reader saw. Across modules it would only
#      rebind the package attribute, so writes are forwarded into every section module
#      that holds the name.
import types as _zyg_types  # noqa: E402

# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and is not used in this module: quota_meter.py became this
# package and the single file's whole surface — public and underscore — is re-exported
# here for its importers. Nothing does ``import *`` from it, so __all__ changes no
# behaviour; it only tells ruff these imports are deliberate.
__all__ = [
    'fcntl',
    'json',
    'os',
    're',
    'time',
    'urllib',
    'datetime',
    'timedelta',
    'urlsplit',
    '_zyg_logging',
    'BUCKET_S',
    'CACHE_PATH',
    'CACHE_VERSION',
    'CONFIG_PATH',
    'CRED_PATH',
    'CREWS',
    'DAY',
    'DEFAULT_CONFIG',
    'DEFAULT_LANES',
    'HOME',
    'INTERACTIVE_ENTRYPOINTS',
    'LEGACY_CLI_UNKNOWN_MODEL',
    'OAUTH_BETA',
    'PRICING',
    'PROJECTS_DIR',
    'QuotaError',
    'RUNTIME',
    'SAMPLES_PATH',
    'SCAN_CAP_DAYS',
    'STATUS_PATH',
    'TREE_MARKER',
    'TREE_MARKER_ROWS',
    'TREE_TASK_RE',
    'USAGE_KEYS',
    'USAGE_URL',
    'WEB_SEARCH_USD',
    'WEEK',
    'WEEKS_PER_MONTH',
    '_PRICING_BY_LEN',
    '_add',
    '_zero',
    '_zyg_log',
    'load_config',
    'model_key',
    'price_row',
    'price_tokens',
    'price_usage',
    'price_usage_total',
    'usage_from_message',
    'weekly_price',
    '_norm_kw',
    '_read_cache_at',
    '_slug_words',
    '_tree_task',
    '_ts_iso',
    '_write_json_atomic',
    'aggregate',
    'aggregate_lanes',
    'classify',
    'daily_series',
    'parse_transcript',
    'scan_transcripts',
    '_append_sample',
    '_credentials',
    '_history',
    '_implied_rates',
    '_lane_split',
    '_limit',
    '_write_status',
    'compute',
    'fetch_usage',
    'parse_usage_payload',
    'read_samples',
    'read_status',
    'report',
    'sample',
    '_fmt_report',
    '_iso',
    'main',
]


_SECTIONS = tuple(sys.modules[f'{__name__}.{_n}'] for _n in ('pricing', 'transcripts', 'calculation', 'cli'))


class _QuotaMeterModule(_zyg_types.ModuleType):
    """A package whose attribute writes reach the section modules, as a single file's did."""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                setattr(_m, name, value)

    def __delattr__(self, name):
        super().__delattr__(name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                delattr(_m, name)


sys.modules[__name__].__class__ = _QuotaMeterModule
