# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_dashboard.analytics_hub [--days N] [rebuild-telemetry]` — print the payload."""

from __future__ import annotations

import json
import sys
import time

from .section import section_analytics
from .sysusage import telemetry_days


if __name__ == '__main__':
    d = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 30
    if 'rebuild-telemetry' in sys.argv:
        t0 = time.time()
        days_, n = telemetry_days(rebuild=True)
        print(f'telemetry cache rebuilt: {n} files, {len(days_)} days, {time.time() - t0:.1f}s')
        sys.exit(0)
    print(json.dumps(section_analytics(d), indent=1, default=str))
