# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""analytics_hub.py — the Metrics > Analytics collector (:5000/metrics, subtab Analytics). 2026-09-18.

One payload, `section_analytics(days)`, drives a kanban board of analytic cards. Every card
carries its own history (bucketed like the rest of the hub), a forecast and, where the
approval queue matters, a scenario "every toggle on the Approval Queue stays on". The
frontend (static/js/dashboard_analytics.js) only draws what is in the payload; nothing is
computed in the browser, so the table twin, the tooltip and the chart cannot disagree.

Sources — the SAME files the other Metrics sections read (metrics_hub.collect_runs /
collect_llm, quota_meter samples, agent_sessions_ledger) plus:
  * data/runtime/system_usage.jsonl — minute samples from zyg-sysusage.service (2026-09-18 on);
  * data/runtime/telemetry_<pipeline>.csv — the GUI's per-second log, written only while a
    clipfarm / crime / scholarly pipeline ran (2026-03-22 .. 2026-08-25), aggregated per day
    into data/runtime/analytics_cache/telemetry_daily.json;
  * the three Approval Queue toggles (zero_auto_mode.json, storyteller_daily.json,
    melody_daily.json), their batches and the per-day volumes their code defines;
  * data/runtime/analytics_config.json — the stated assumptions (views per content, RPM,
    kWh price, active hours). Assumptions are shipped with every payload and editable
    from the tab; a number that rests on one says so in its card.

Honesty rules (see metrics_hub.py): a run's duration is `recorded` (stage timings or an
end stamp), `inferred` (last state write minus start — the kids-music state is written
once, at the end, so its wall time is start minus the first output file), or missing —
never guessed, and the basis is counted per kind. Forecasts are an ordinary least-squares
trend over the last TREND_DAYS days with an 80 % residual band, and the payload says so.
Income is `assumed views × RPM` and is labelled as such everywhere it appears.

Hot-reloaded by metrics_hub.section('analytics') when this file's mtime changes.
`python3 analytics_hub.py [--days N]` prints the payload.
"""

# ruff: noqa: F401 — this __init__ is the old module namespace, re-exported whole

from __future__ import annotations

import csv
import glob
import hashlib
import json
import logging as _zyg_logging
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zyg_dashboard import metrics_hub as mh  # noqa: E402

from .constants import (
    API,
    ASSET_KINDS,
    CACHE_DIR,
    CONFIG_PATH,
    CONTENT_KINDS,
    CREWS,
    DAY,
    DEFAULT_CONFIG,
    GPU_BUSY_UTIL,
    HORIZON_DAYS,
    INFER_MAX_S,
    INFER_MIN_S,
    RUNTIME,
    SYSUSAGE_PATH,
    TELEMETRY_CACHE,
    TREND_DAYS,
    TZ,
    _zyg_log,
)
from .config import (
    load_config,
    save_config,
)
from .helpers import (
    _bucket_series,
    _daily_keys,
    _day,
    _daykey,
    _delta,
    _fc_bucketed,
    _forecast,
    _forecast_keys,
    _median,
    _r,
    _week_start,
)
from .runs import (
    _OUTDIR_MIN,
    _outdir_first_write,
    _state_path,
    enrich_runs,
)
from .sysusage import (
    _SYS,
    _aggregate_csv,
    _run_hours_by_day,
    _sysusage_days,
    telemetry_days,
)
from .approval import (
    _batch_counts,
    _pick_count,
    approval_queue,
)
from .sources import (
    _sources,
    _version,
)
from .arch_studio import (
    ARCH_CLASSES,
    ARCH_DIR,
    ARCH_LEDGER,
    ARCH_SOURCES,
    ARCH_TEST_TEXTS,
    _arch_builds,
    _arch_outputs,
    _arch_ts,
    arch_studio_card,
)
from .preempt_bank import (
    _preempt_targets,
    preempt_bank_card,
)
from .section import (
    section_analytics,
)

__all__ = [
    'API',
    'ARCH_CLASSES',
    'ARCH_DIR',
    'ARCH_LEDGER',
    'ARCH_SOURCES',
    'ARCH_TEST_TEXTS',
    'ASSET_KINDS',
    'CACHE_DIR',
    'CONFIG_PATH',
    'CONTENT_KINDS',
    'CREWS',
    'DAY',
    'DEFAULT_CONFIG',
    'GPU_BUSY_UTIL',
    'HORIZON_DAYS',
    'INFER_MAX_S',
    'INFER_MIN_S',
    'RUNTIME',
    'SYSUSAGE_PATH',
    'TELEMETRY_CACHE',
    'TREND_DAYS',
    'TZ',
    '_OUTDIR_MIN',
    '_SYS',
    '_aggregate_csv',
    '_arch_builds',
    '_arch_outputs',
    '_arch_ts',
    '_batch_counts',
    '_bucket_series',
    '_daily_keys',
    '_day',
    '_daykey',
    '_delta',
    '_fc_bucketed',
    '_forecast',
    '_forecast_keys',
    '_median',
    '_outdir_first_write',
    '_pick_count',
    '_preempt_targets',
    '_r',
    '_run_hours_by_day',
    '_sources',
    '_state_path',
    '_sysusage_days',
    '_version',
    '_week_start',
    '_zyg_log',
    'approval_queue',
    'arch_studio_card',
    'enrich_runs',
    'load_config',
    'preempt_bank_card',
    'save_config',
    'section_analytics',
    'telemetry_days',
]
