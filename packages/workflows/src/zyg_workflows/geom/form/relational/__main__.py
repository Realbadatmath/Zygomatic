# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.relational` — the entry point that reached the
CLI relational.py ran from its own `if __name__ == '__main__'`.
"""

import sys

from zyg_workflows.geom.form.relational.cli import main

if __name__ == '__main__':
    sys.exit(main())
