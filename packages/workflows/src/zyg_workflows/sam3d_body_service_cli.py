# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.sam3d_body_service`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.sam3d_body_service` still reaches it.
"""

import json
import sys

from zyg_workflows.sam3d_body_service import (
    available,
    fit_one,
    mhr_decode_available,
)


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in sam3d_body_service."""
    print('available:', available())
    print('mhr decode:', mhr_decode_available())
    if len(sys.argv) > 1:
        rec = fit_one(sys.argv[1], log_fn=lambda m: print(m, file=sys.stderr))
        print(
            json.dumps(
                {k: v for k, v in (rec or {}).items() if k in ('detected', 'bbox', 't_s', 'focal_length')}, indent=1
            )
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
