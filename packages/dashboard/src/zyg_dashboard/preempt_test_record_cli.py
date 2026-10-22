# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.preempt_test_record`, moved out of the library module
so that library code never prints; `python -m zyg_dashboard.preempt_test_record` still
reaches it.
"""

from __future__ import annotations

import json
import sys

from zyg_dashboard import test_data_hub as td
from zyg_dashboard.preempt_test_record import build_record


def main() -> int:
    rec = build_record()
    p = td.record(rec, replace=True)
    print(f'recorded {rec["id"]}: {p}')
    if '--print' in sys.argv:
        print(json.dumps(rec, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
