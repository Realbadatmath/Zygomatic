# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.self_improve` — the original `__main__` guard."""

import sys

from zyg_workflows.self_improve.cli import main

if __name__ == '__main__':
    sys.exit(main())
