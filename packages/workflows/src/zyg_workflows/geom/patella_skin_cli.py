# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.patella_skin`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.patella_skin` still reaches it.
"""

import json
import sys

from zyg_workflows.geom.patella_skin import report


def main() -> int:
    """The report dump that used to live under `if __name__` in patella_skin."""
    print(json.dumps(report(), indent=1, default=float))
    return 0


if __name__ == '__main__':
    sys.exit(main())
