# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.pgdb`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.pgdb` still reaches it.
"""

import sys

from zyg_workflows.pgdb import dsn, ping


def main() -> int:
    print(dsn(), ping())
    return 0


if __name__ == '__main__':
    sys.exit(main())
