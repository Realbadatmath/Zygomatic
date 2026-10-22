# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.asset_fetch_keyed`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.asset_fetch_keyed` still reaches it.
"""

from __future__ import annotations

import sys

from zyg_workflows.asset_fetch_keyed import _env, blenderkit, sketchfab


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in asset_fetch_keyed."""
    a = sys.argv[1:]
    if not a or '--status' in a:
        print(
            'SKETCHFAB_TOKEN:',
            'set' if _env('SKETCHFAB_TOKEN') else 'MISSING',
            '| BLENDERKIT_API_KEY:',
            'set' if _env('BLENDERKIT_API_KEY') else 'MISSING',
        )
        return 0
    src, query = a[0], a[1] if len(a) > 1 else ''
    lic = a[a.index('--license') + 1] if '--license' in a else 'cc0'
    mx = int(a[a.index('--max') + 1]) if '--max' in a else 10
    got = sketchfab(query, lic, mx) if src == 'sketchfab' else blenderkit(query, mx)
    print(f'{len(got)} pack(s) written; now run: python3 mesh_pack_dims.py {src}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
