# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.anthro.gates` — the entry point the old gates.py
carried as its `if __name__ == '__main__'` block.
"""

import sys

from zyg_workflows.geom.anthro.gates.cli import main

if __name__ == '__main__':
    sys.exit(main())
