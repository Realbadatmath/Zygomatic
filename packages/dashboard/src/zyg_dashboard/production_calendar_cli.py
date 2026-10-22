# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.production_calendar`, moved out of the library module
so that library code never prints; `python -m zyg_dashboard.production_calendar` still
reaches it.
"""

from __future__ import annotations

import json
import sys

from zyg_dashboard.production_calendar import payload


def main() -> int:
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    print(
        json.dumps(
            payload(view=opt('--view', 'calendar'), anchor=opt('--anchor'), days=int(opt('--days', 7))),
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
