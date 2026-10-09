# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.mesh_skeletons` — the entry point the old
single-file module carried at its very end (lines 3511-3512).
"""

import sys

from zyg_workflows.geom.mesh_skeletons.cli import main

if __name__ == '__main__':
    sys.exit(main())
