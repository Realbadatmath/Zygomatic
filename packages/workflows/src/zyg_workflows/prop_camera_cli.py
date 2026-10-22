# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_camera`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.prop_camera` still reaches it.
"""

import json
import sys

from zyg_workflows.prop_camera import book_page_points, solve_camera


def main() -> int:
    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 2:
        print('usage: prop_camera.py SHOT_META.json [W H] [--open A] [--thick T] [--f PX]')
        return 2
    meta = json.load(open(sys.argv[1]))
    W = int(sys.argv[2]) if len(sys.argv) > 2 else 832
    H = int(sys.argv[3]) if len(sys.argv) > 3 else 480
    a = sys.argv

    def _o(n, d):
        return float(a[a.index(n) + 1]) if n in a else d

    open_a, thick = _o('--open', 0.30), _o('--thick', 0.11)
    f = _o('--f', 0.0) or None
    pts = book_page_points(thick=thick, open_a=open_a)
    r = solve_camera(meta['page_quad'], (W, H), pts, focal_px=f, log_fn=_lg)
    if not r:
        return 1
    print(json.dumps(r, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
