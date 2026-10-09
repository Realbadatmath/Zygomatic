# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module imports, paths and the tuning constants of the Metrics-tab collectors."""

from __future__ import annotations

import os
from datetime import timezone

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo('Europe/Amsterdam')
except Exception:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    TZ = timezone.utc
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


# One dirname more than the original metrics_hub.py: this module sits one directory deeper,
# and CREWS must keep naming the zyg_dashboard package directory.
CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(CREWS, 'data', 'runtime')
HEALTH_LOG = '/var/log/zygomatic-health.log'
DAY = 86400
# A run claiming to be in progress with no state write for this long is reported
# as stale. Pipelines write state at every stage transition; the longest single
# stage seen in the run ledger (Wan probe_and_render) averages ~1.6 h.
STALE_AFTER_S = 12 * 3600
