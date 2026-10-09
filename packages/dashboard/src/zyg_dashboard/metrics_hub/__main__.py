# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python3 -m zyg_dashboard.metrics_hub <section> [--days N]` prints one section."""

from __future__ import annotations

import json
import sys

from zyg_dashboard.metrics_hub import quality_detail, section

name = sys.argv[1] if len(sys.argv) > 1 else 'overview'
d = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 30
if '--detail' in sys.argv:  # python3 metrics_hub.py quality --detail tile:fallbacks
    print(json.dumps(quality_detail(sys.argv[sys.argv.index('--detail') + 1], days=d), indent=1, default=str))
else:
    print(json.dumps(section(name, d), indent=1, default=str))
