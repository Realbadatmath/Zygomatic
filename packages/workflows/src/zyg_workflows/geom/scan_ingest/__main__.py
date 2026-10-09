# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.scan_ingest` — the entry point the old scan_ingest.py
carried as its `if __name__ == '__main__'` block (lines 2647-2650).
"""

import sys

from zyg_workflows.geom.scan_ingest.orchestration import main


if __name__ == '__main__':
    sys.exit(main())
