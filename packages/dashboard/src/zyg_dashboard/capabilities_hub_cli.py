# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.capabilities_hub`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.capabilities_hub` still reaches it."""

import json
import os
import sys

from zyg_dashboard.capabilities_hub import (
    STEPS,
    asset_index,
    inspect,
    load_sheet,
    record_sheet,
    section_capabilities,
)


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in capabilities_hub."""
    args = sys.argv[1:]
    verb = args[0] if args else 'section'
    if verb == 'list':
        for s in STEPS:
            sh = load_sheet(s['id'])
            print(
                f'{s["id"]:<18} {s["group"]:<9} {(sh["status"] if sh else "no sheet"):<10} '
                f'{(str(sh["coverage"]["pct"]) + "%" if sh else "—"):>7}  {s["label"]}'
            )
    elif verb == 'show':
        print(json.dumps(load_sheet(args[1]), indent=1, default=str))
    elif verb == 'inspect':
        print(json.dumps(inspect(args[1]), indent=1, default=str))
    elif verb == 'record':
        src = args[args.index('--file') + 1] if '--file' in args else None
        rec = json.load(open(src, encoding='utf-8')) if src else json.load(sys.stdin)
        print(record_sheet(rec))
    elif verb == 'assets':
        for k, v in asset_index().items():
            print(k, v, 'OK' if os.path.exists(v) else 'MISSING')
    else:
        print(json.dumps(section_capabilities(), indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
