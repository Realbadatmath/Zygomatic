# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""metrics_hub.py — the collectors behind the Metrics tab (:5000/metrics). 2026-09-11.

Why this module exists. Measured against the live GUI on 2026-09-11, the old
/api/metrics/dashboard (bp_metrics._compute_metrics_dashboard) took 11.7 s and
reported several numbers that were structurally wrong:

  * "success" meant "has an `ended` timestamp": kidsmusic (61 completed, 6 failed,
    no `ended` field) read 0 %, while failed runs that did write `ended` read as ok;
  * tokitoki / remix_ai runs frozen at status=running since Aug 9 / Aug 30 showed
    as live, and 152 scholarly states with no status at all were folded in silently;
  * API spend came from token_usage.json — a rolling 1 000-row window last written
    2026-08-25 — and priced Haiku 4.5 at a quarter of its list price;
  * token-only rows ("Storyteller 49 runs · 100 % ok") were API-call counts.

Rules every collector here follows (the measure-before-claim discipline):

  * A run is completed/failed only when its record says so, or when NAMED evidence
    supports it — then `inferred` is set and counted separately. A run that
    started and never wrote an end is `stale`, neither success nor failure.
  * Success rate = completed / (completed + failed). Stale, cancelled and
    unrecorded runs are reported beside it, never folded in.
  * Test / smoke / synthetic rows are excluded, and every exclusion is counted in
    the payload so the reader can see what was left out.
  * Each section names its sources and their coverage limits.

Flask-free and import-safe: `python3 metrics_hub.py overview --days 30` prints a
section. bp_metrics.py serves it at /api/metrics/hub/<section>?days=N.
"""

# ruff: noqa: F401 — this __init__ is the old module namespace, re-exported whole

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
from zyg_workflows import pgdb
import subprocess
import sys
import threading
import time
from zyg_workflows.bin import exe
from zyg_workflows.net import safe_urlopen
from zyg_workflows.paths import ZYG_COMFY_URL, ZYG_OLLAMA_URL, ZYG_SESSION_TREE_URL
from datetime import datetime, timedelta, timezone
import logging as _zyg_logging

from .constants import (
    TZ,
    _zyg_log,
    CREWS,
    RUNTIME,
    HEALTH_LOG,
    DAY,
    STALE_AFTER_S,
)

from .helpers import (
    _is_test_id,
    _is_test_id_impl,
    _ts,
    _iso,
    _pct,
    _short,
    _num,
    _rate,
    _req_arg,
    _read_json,
    _iter_jsonl,
    _http_json,
    _CACHE,
    _UNREADABLE,
    _LOCK,
    _cached,
    _prune,
    _MEMO,
    _memo,
)

from .runs import (
    KIND_LABELS,
    FAMILIES,
    FAMILY_LABELS,
    _KIND_FAMILY,
    STATUSES,
    _DONE,
    _FAIL,
    _CANCEL,
    _OPEN,
    STATUS_RULES,
    _family,
    _norm_stage,
    _stages,
    _run_record,
    _load_pipeline_state,
    _load_char_gen,
    _load_creature_gen,
    _load_contact_sheet,
    _RUN_SOURCES,
    _classify,
    collect_runs,
    _window,
    _bucketing,
    _bucket_of,
    _run_row,
    _runs_daily,
)

from .llm import (
    PRICING,
    _PRICING_BY_LEN,
    PROVIDER_LABELS,
    _model_key,
    _price,
    _int,
    _err_message,
    _load_audit_file,
    _load_context_ledger,
    collect_llm,
    section_llm,
    _QUOTA_MOD,
    _quota_meter,
)

from .pipelines import (
    section_pipelines,
)

from .characters import (
    section_characters,
    _character_quality,
)

from .quality import (
    _test_run_ids,
    _run_class,
    _ledger_rows,
    _DETAIL_ROWS,
    _OUTCOME_TONE,
    _fb_name,
    _fb_key,
    _dbg_key,
    _debug_index,
    _test_reason,
    _tbl,
    _fact,
    _run_cell,
    _GATE_COLS,
    _gate_row,
    _FALL_COLS,
    _fall_row,
)

from .detail import (
    quality_detail,
)

from .quality_section import (
    section_quality,
)

from .system import (
    SERVICES,
    _systemctl_show,
    _listeners,
    _proc_brief,
    _cgroup,
    _services,
    _ts_systemd,
    _health_events,
    _disks,
    section_system,
)

from .overview import (
    section_agents,
    _FRESHNESS,
    _freshness,
    section_overview,
)

from .dispatch import (
    SECTIONS,
    _ANALYTICS_MOD,
    _analytics_mod,
    section_analytics,
    _TESTDATA_MOD,
    _testdata_mod,
    section_test_data,
    _CAPABILITIES_MOD,
    _capabilities_mod,
    section_capabilities,
    _LINEAGE_MOD,
    _lineage_mod,
    section_stack_lineage,
    _EXPANSION_MOD,
    _expansion_mod,
    section_expansion,
    section_quota,
    section,
)

try:  # bound only when zoneinfo imported cleanly, exactly as in the original header
    from .constants import ZoneInfo
except ImportError:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    pass
