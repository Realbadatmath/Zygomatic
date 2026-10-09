# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.hands` — the entry point the old hands.py
carried as its `if __name__ == '__main__'` block.
"""

import sys

from zyg_workflows.geom.form.hands.cli import main

if __name__ == '__main__':
    sys.exit(main())
