# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.voice_texture`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.voice_texture` still reaches it.
"""

import os

from zyg_workflows.voice_texture import scan


def main() -> int:
    import sys

    rows = scan(sys.argv[1:], log_fn=print)
    print(f'{"voice":34s} {"wear":>6s} {"F0":>6s} {"HNR":>6s} {"jit%":>5s} {"shim%":>6s} {"CPPS":>6s} {"floor":>6s}')
    for r in rows:
        tag = '  REJECTED: ' + r['rejected'] if r['rejected'] else ''
        print(
            f'{os.path.basename(r["path"])[:34]:34s} {r["wear"]:6.2f} '
            f'{r["f0"]:6.1f} {r["hnr"]:6.2f} {r["jitter"]:5.2f} '
            f'{r["shimmer"]:6.2f} {r["cpps"]:6.2f} {r["floor_db"]:6.1f}{tag}'
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
