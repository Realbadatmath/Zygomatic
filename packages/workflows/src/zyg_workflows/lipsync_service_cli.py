# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.lipsync_service`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.lipsync_service` still reaches it.
"""

import json
import sys

from zyg_workflows.lipsync_service import (
    available,
    lipsync,
)


def main() -> int:  # pragma: no cover
    """What used to run under `if __name__` in lipsync_service."""
    print('available:', available())
    if len(sys.argv) > 3:
        print(
            json.dumps(
                {'mp4': lipsync(sys.argv[1], sys.argv[2], sys.argv[3], log_fn=lambda m: print(m, file=sys.stderr))}
            )
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
