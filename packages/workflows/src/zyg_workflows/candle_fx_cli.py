# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.candle_fx`, moved out of the library module so that library code
never prints; `python -m zyg_workflows.candle_fx` still reaches it.
"""

import json
import os
import sys

from zyg_workflows.candle_fx import composite_candle_flicker


def main() -> int:
    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 3:
        print('usage: candle_fx.py IN.mp4 OUT.mp4 [meta.json] [strength]')
        return 2
    box = [0.444, 0.56, 0.538, 0.878]
    if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
        box = json.load(open(sys.argv[3])).get('candle_box', box)
    st = float(sys.argv[4]) if len(sys.argv) > 4 else None
    r = composite_candle_flicker(sys.argv[1], sys.argv[2], box, strength=st, log_fn=_lg)
    print('->', r)
    return 0 if r else 1


if __name__ == '__main__':
    sys.exit(main())
