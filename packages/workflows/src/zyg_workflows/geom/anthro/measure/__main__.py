# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.anthro.measure` — the entry point the old measure.py
carried as its `if __name__ == '__main__'` block.
"""

from zyg_workflows.geom.anthro.measure.selftest import main

if __name__ == '__main__':
    raise SystemExit(main())
