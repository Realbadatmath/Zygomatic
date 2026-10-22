# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.voice_assign`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.voice_assign` still reaches it.
"""

import sys

from zyg_workflows.voice_assign import (
    _voices_for_view,
    view,
)


def main() -> int:  # pragma: no cover — operator smoke test
    import argparse

    ap = argparse.ArgumentParser(description='Voice assignments — CLI smoke test')
    ap.add_argument('--voice', default='abel')
    a = ap.parse_args()
    v = view(a.voice, _voices_for_view())
    print(f'{len(v["characters"])} characters, {len(v["workflows"])} workflows')
    for kind in ('characters', 'workflows'):
        for r in v[kind]:
            if r['saved'] or r['live'] or r['other']:
                print(
                    f'  [{kind[:4]}] {r["name"][:38]:38}  saved={r["saved"]!s:5} '
                    f'live={r["live"]!s:5} other={r["other_name"] or "-"}'
                )
    return 0


if __name__ == '__main__':
    sys.exit(main())
