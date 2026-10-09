# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.detail_filter` — the entry point the old
detail_filter.py carried as its `if __name__ == '__main__'` block (lines 1088-1089).
"""

import sys

from zyg_workflows.geom.detail_filter.acceptance import main


if __name__ == '__main__':
    sys.exit(main())
