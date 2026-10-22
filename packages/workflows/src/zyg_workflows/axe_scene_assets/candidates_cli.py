# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.axe_scene_assets.candidates`, moved out of the library
module so that library code never prints;
`python -m zyg_workflows.axe_scene_assets.candidates` still reaches it.
"""

import sys
import time

from zyg_workflows.axe_scene_assets.candidates import build_tree_plate


def main() -> int:
    def _lg(m):
        print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    full, anchor = build_tree_plate(seed=seed, log_fn=_lg)
    _lg(f'DONE  full={full}  anchor={anchor}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
