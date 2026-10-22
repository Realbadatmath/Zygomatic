# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.hair_assets.headframe`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.tools.hair_assets.headframe` still
reaches it.

Dumps the measured head frame of every OBJ named on the command line.
"""

import json
import sys

from zyg_workflows.tools.hair_assets.headframe import head_frame, read_obj_verts


def main() -> int:
    for p in sys.argv[1:]:
        f = head_frame(read_obj_verts(p))
        print(p)
        print(' ', json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
