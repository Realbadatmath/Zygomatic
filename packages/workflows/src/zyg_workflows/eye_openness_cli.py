# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.eye_openness`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.eye_openness` still reaches it.
"""

import json
import sys

from zyg_workflows.eye_openness import measure


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in eye_openness."""

    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 2:
        print('usage: eye_openness.py CLIP [x0 y0 x1 y1]')
        return 2
    bx = tuple(float(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else None
    print(json.dumps(measure(sys.argv[1], box=bx, log_fn=_lg), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
