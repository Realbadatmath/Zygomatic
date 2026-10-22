# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.scene_plates`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.scene_plates` still reaches it.
"""

import sys

from zyg_workflows.scene_plates import build


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in scene_plates."""
    if len(sys.argv) != 2:
        print('usage: scene_plates.py <shot_dir>')
        return 2
    build(sys.argv[1])
    return 0


if __name__ == '__main__':
    sys.exit(main())
