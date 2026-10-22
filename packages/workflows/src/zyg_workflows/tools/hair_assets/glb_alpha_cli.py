# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.hair_assets.glb_alpha`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.tools.hair_assets.glb_alpha` still
reaches it.

    python3 -m zyg_workflows.tools.hair_assets.glb_alpha MASK 0.5 file.glb [file.glb ...]
"""

import sys

from zyg_workflows.tools.hair_assets.glb_alpha import patch


def main() -> int:
    mode = sys.argv[1]
    cutoff = float(sys.argv[2])
    for p in sys.argv[3:]:
        print(p, patch(p, mode, cutoff))
    return 0


if __name__ == '__main__':
    sys.exit(main())
