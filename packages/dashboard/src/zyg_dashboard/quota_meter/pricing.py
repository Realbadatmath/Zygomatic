# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# The original top-level import block lives here verbatim; the siblings
# (calculation, transcripts, cli, __init__) re-import from it, so the names
# this module does not use itself are re-exports — see __all__ below.

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

from zyg_dashboard import paths
from zyg_workflows.paths import ZYG_DATA_ROOT

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo('Europe/Amsterdam')
except Exception:  # pragma: no cover
    TZ = timezone.utc
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.quota_meter')

# Imports this module holds for its siblings rather than for itself:
# fcntl, time, urlsplit (calculation), sys, time (cli), timedelta (transcripts),
# datetime (calculation, transcripts), urllib.request (calculation).
__all__ = [
    'datetime',
    'fcntl',
    'sys',
    'time',
    'timedelta',
    'urllib',
    'urlsplit',
]


CREWS = str(paths.PKG_DIR)
RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(CREWS, 'data', 'runtime')
HOME = os.path.expanduser('~')
PROJECTS_DIR = os.environ.get('ZYG_CLAUDE_PROJECTS_DIR') or os.path.join(HOME, '.claude', 'projects')
CRED_PATH = os.environ.get('ZYG_CLAUDE_CREDENTIALS') or os.path.join(HOME, '.claude', '.credentials.json')
USAGE_URL = os.environ.get('ZYG_CLAUDE_USAGE_URL') or 'https://api.anthropic.com/api/oauth/usage'
OAUTH_BETA = 'oauth-2025-04-20'  # the header the CLI sends on every OAuth call
SAMPLES_PATH = os.path.join(RUNTIME, 'quota_samples.jsonl')
STATUS_PATH = os.path.join(RUNTIME, 'quota_meter_status.json')
CACHE_PATH = os.path.join(RUNTIME, 'quota_transcripts_cache.json')
CONFIG_PATH = os.path.join(RUNTIME, 'quota_config.json')
CACHE_VERSION = 2  # bump whenever parse_transcript's shape changes: the cache is
# keyed on (mtime, size) only, so a new field would otherwise be
# missing from every entry parsed by an older build.

DAY = 86400.0
WEEK = 7 * DAY
BUCKET_S = 300  # transcript usage is kept in 5-minute buckets
WEEKS_PER_MONTH = 365.25 / 7 / 12  # 4.348 — a calendar month in weeks
SCAN_CAP_DAYS = 90  # "all time" on the tab means this much transcript

# ── Lanes: what the week was actually spent on ───────────────────────────────
# The operator's two questions of this meter are "what did producing content cost" and
# "what did building the stack cost". Neither is a surface Claude reports, so the split is
# made here, from the transcripts, and every rule below is config, not a hunch:
#
#   production      a workflow spending Claude as an inference step, unattended: the
#                   documentary pipeline, the architecture assistant, Vicky, the
#                   assistants of the other apps. Identified by the cwd their headless
#                   `claude -p` runs in (each has its own CLI directory, on purpose).
#   session tree    one board-spawned executor, one task. The transcript says so in its
#                   own first line. A tree is content or infrastructure by what it was
#                   building, matched on the tree slug (`tree_content` wins, then
#                   `tree_infra`, then `tree_default`).
#   interactive     everything else: the operator and an agent in an editor or terminal.
#                   Always infrastructure — this is the building side by definition.
#
# Trees and interactive sessions both add up to the infrastructure side; production
# workflows and content trees add up to the production side.
#
# A workflow_dirs match is tested as a SUBSTRING of the transcript's cwd, so the two
# patterns under the data root keep its TAIL rather than its absolute path: a transcript
# recorded under another copy of the tree still lands in the right lane. ZYG_DATA_ROOT is
# the single source of truth for the components.
_DATA_TAIL = os.path.join(os.sep, *ZYG_DATA_ROOT.parts[-3:])
DEFAULT_LANES = {
    'workflow_dirs': [
        {'match': os.path.join(_DATA_TAIL, 'runtime', 'scholarly-llm-cli'), 'label': 'Documentary (scholarly)'},
        {'match': os.path.join(_DATA_TAIL, 'runtime', 'arch_assistant', 'cli'), 'label': 'Architecture assistant'},
        {'match': '/nomologin/assistant/cli', 'label': 'Nomologin assistant'},
        # Vicky's cwd IS Medusa's own folder, so an editor session opened there would look
        # like her: only a non-interactive entrypoint counts.
        {'match': '/Zygomatic/medusa', 'label': 'Vicky (Medusa)', 'headless_only': True},
    ],
    'tree_content': ['-intro-', 'ledger', 'eagle', 'episode', 'kids-', 'documentary', 'storyteller'],
    'tree_infra': ['capabilit', 'test', 'studio', 'gate', 'metric', ' gui ', 'board', 'bench', 'schedule'],
    'tree_default': 'infrastructure',
}

# The board's spawn prompt, verbatim from session_tree_server.py. A transcript whose
# opening row starts with this IS one executor's single task.
TREE_MARKER = 'You are a Session Tree executor'
TREE_TASK_RE = re.compile(r'You are a Session Tree executor\..{0,200}?ONE task:\s*([^\s#]+)#(\d+)', re.S)
TREE_MARKER_ROWS = 6  # how many opening rows may carry it before we stop looking

# An entrypoint a human is sitting in front of. Anything else that is not a known workflow
# directory and not a tree executor is still counted as interactive, but this list is what
# keeps a headless run out of the `headless_only` workflow directories.
INTERACTIVE_ENTRYPOINTS = ('claude-vscode', 'cli', 'claude-code', 'claude-cli')

DEFAULT_CONFIG = {
    'subscription_price': 180.0,  # what the operator pays per billing period
    'currency': 'EUR',
    'billing': 'month',  # 'month' (calendar month, 12 payments a year) or 'days'
    'billing_days': 28,  # only used when billing == 'days'
    'eur_per_usd': 0.85,  # for the API-equivalent column in EUR; a config value, not a live rate
    'sample_max_age_s': 900,  # a report fetches live when the last sample is older than this
    'plan_label': 'Claude Max 20x',
    'lanes': DEFAULT_LANES,
}

# USD per 1M tokens: (prefix, input, output, cache write 5 min, cache write 1 h, cache read).
# Cache write is 1.25x input for the 5-minute TTL and 2x for the 1-hour TTL; cache read is
# 10 % of input except Claude Fable 5.1 / Mythos 5.1 ($0.25). Longest prefix wins.
PRICING = (
    ('claude-fable-5-1', 10.0, 50.0, 12.5, 20.0, 0.25),
    ('claude-mythos-5-1', 10.0, 50.0, 12.5, 20.0, 0.25),
    ('claude-fable-5', 10.0, 50.0, 12.5, 20.0, 1.0),
    ('claude-mythos-5', 10.0, 50.0, 12.5, 20.0, 1.0),
    ('claude-opus-5', 5.0, 25.0, 6.25, 10.0, 0.5),
    ('claude-opus-4-8', 5.0, 25.0, 6.25, 10.0, 0.5),
    ('claude-opus-4-7', 5.0, 25.0, 6.25, 10.0, 0.5),
    ('claude-opus-4-6', 5.0, 25.0, 6.25, 10.0, 0.5),
    ('claude-opus-4-5', 5.0, 25.0, 6.25, 10.0, 0.5),
    ('claude-opus-4-1', 15.0, 75.0, 18.75, 30.0, 1.5),
    ('claude-opus-4', 15.0, 75.0, 18.75, 30.0, 1.5),
    ('claude-3-opus', 15.0, 75.0, 18.75, 30.0, 1.5),
    ('claude-sonnet-5', 2.0, 10.0, 2.5, 4.0, 0.2),
    ('claude-sonnet-4', 3.0, 15.0, 3.75, 6.0, 0.3),
    ('claude-3-7-sonnet', 3.0, 15.0, 3.75, 6.0, 0.3),
    ('claude-3-5-sonnet', 3.0, 15.0, 3.75, 6.0, 0.3),
    ('claude-haiku-4-5', 1.0, 5.0, 1.25, 2.0, 0.1),
    ('claude-3-5-haiku', 0.8, 4.0, 1.0, 1.6, 0.08),
    ('claude-3-haiku', 0.25, 1.25, 0.3, 0.5, 0.03),
)
_PRICING_BY_LEN = sorted(PRICING, key=lambda p: -len(p[0]))
WEB_SEARCH_USD = 0.01  # per request, all models

# What claude 2.1.74 charges a model it does not know (measured 2026-09-17, see docstring):
# the Opus 4.x row with a flat 1.25x cache write. Kept so the old numbers can be explained.
LEGACY_CLI_UNKNOWN_MODEL = (5.0, 25.0, 6.25, 6.25, 0.5)

USAGE_KEYS = ('input', 'output', 'cache_5m', 'cache_1h', 'cache_read', 'web_search', 'messages')


class QuotaError(Exception):
    pass


# ── config ───────────────────────────────────────────────────────────────────


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg['lanes'] = dict(DEFAULT_LANES)
    try:
        with open(CONFIG_PATH, encoding='utf-8') as fh:
            stored = json.load(fh)
        cfg.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG and k != 'lanes'})
        # `lanes` merges one key at a time, so a config that overrides only `tree_content`
        # keeps the shipped workflow directories instead of silently emptying them.
        if isinstance(stored.get('lanes'), dict):
            cfg['lanes'].update({k: v for k, v in stored['lanes'].items() if k in DEFAULT_LANES})
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('config %s unreadable, continuing with the shipped defaults: %s', CONFIG_PATH, _exc)
    for key, env in (
        ('subscription_price', 'ZYG_SUBSCRIPTION_PRICE'),
        ('eur_per_usd', 'ZYG_EUR_PER_USD'),
        ('billing_days', 'ZYG_SUBSCRIPTION_BILLING_DAYS'),
    ):
        if os.environ.get(env):
            try:
                cfg[key] = float(os.environ[env])
            except ValueError as _exc:
                _zyg_log.warning('%s=%r is not a number, keeping %r: %s', env, os.environ[env], cfg[key], _exc)
    if os.environ.get('ZYG_SUBSCRIPTION_BILLING') in ('month', 'days'):
        cfg['billing'] = os.environ['ZYG_SUBSCRIPTION_BILLING']
    return cfg


def weekly_price(cfg: dict) -> float:
    """The subscription price per Claude week. Monthly billing = 12 payments a year spread
    over 52.18 weeks; 'days' billing divides the price by the invoice interval."""
    price = float(cfg.get('subscription_price') or 0)
    if cfg.get('billing') == 'days':
        days = float(cfg.get('billing_days') or 28)
        return price * 7.0 / days if days else 0.0
    return price / WEEKS_PER_MONTH


# ── pricing ──────────────────────────────────────────────────────────────────


def model_key(model) -> str:
    m = str(model or '').strip().lower()
    if m.endswith('[1m]'):
        m = m[:-4]
    # drop a trailing -YYYYMMDD snapshot suffix
    parts = m.rsplit('-', 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        m = parts[0]
    return m or 'unknown'


def price_row(model):
    """(input, output, cache write 5m, cache write 1h, cache read) per MTok, or None."""
    ml = model_key(model)
    for prefix, *rates in _PRICING_BY_LEN:
        if ml.startswith(prefix):
            return tuple(rates)
    return None


def price_usage(model, usage: dict, rates=None):
    """API list cost in USD of one usage vector {input, output, cache_5m, cache_1h,
    cache_read, web_search}; None when the model has no price."""
    r = rates or price_row(model)
    if not r:
        return None
    return (
        (usage.get('input', 0) or 0) * r[0]
        + (usage.get('output', 0) or 0) * r[1]
        + (usage.get('cache_5m', 0) or 0) * r[2]
        + (usage.get('cache_1h', 0) or 0) * r[3]
        + (usage.get('cache_read', 0) or 0) * r[4]
    ) / 1e6 + (usage.get('web_search', 0) or 0) * WEB_SEARCH_USD


def price_usage_total(by_model: dict) -> float:
    """API-equivalent cost of a {model: usage vector} map. A model with no price row adds
    nothing rather than raising — the same models land in `unpriced_models` on the tab."""
    return sum((price_usage(m, u) or 0.0) for m, u in (by_model or {}).items())


def price_tokens(model, tin=0, tout=0, cache_write=0, cache_read=0, cache_ttl='1h'):
    """Audit-log shape (no 5m/1h split). Claude Code writes its cache with the 1-hour
    TTL (measured: 193,362 of 194,895 cache-write tokens on a Sonnet 5 job), so an
    unsplit cache write is priced as 1 h unless told otherwise."""
    w = int(cache_write or 0)
    u = {
        'input': tin or 0,
        'output': tout or 0,
        'cache_read': cache_read or 0,
        'cache_5m': w if cache_ttl == '5m' else 0,
        'cache_1h': 0 if cache_ttl == '5m' else w,
    }
    return price_usage(model, u)


def usage_from_message(usage: dict) -> dict:
    """Transcript `message.usage` -> our usage vector."""
    cc = usage.get('cache_creation') or {}
    w1h = int(cc.get('ephemeral_1h_input_tokens') or 0)
    w5m = int(cc.get('ephemeral_5m_input_tokens') or 0)
    total_w = int(usage.get('cache_creation_input_tokens') or 0)
    if not cc and total_w:
        w1h = total_w  # no split recorded: Claude Code's TTL is 1 h
    st = usage.get('server_tool_use') or {}
    return {
        'input': int(usage.get('input_tokens') or 0),
        'output': int(usage.get('output_tokens') or 0),
        'cache_5m': w5m,
        'cache_1h': w1h,
        'cache_read': int(usage.get('cache_read_input_tokens') or 0),
        'web_search': int(st.get('web_search_requests') or 0),
        'messages': 1,
    }


def _zero():
    return {k: 0 for k in USAGE_KEYS}


def _add(into: dict, vec) -> dict:
    if isinstance(vec, dict):
        for k in USAGE_KEYS:
            into[k] = into.get(k, 0) + int(vec.get(k, 0) or 0)
    else:
        for k, v in zip(USAGE_KEYS, vec):
            into[k] = into.get(k, 0) + int(v or 0)
    return into
