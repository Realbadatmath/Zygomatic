# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.vlm_report` — the CLI the original module ran under
its `if __name__ == '__main__'` guard."""

import sys

from zyg_workflows.vlm_report.entry import _cli

if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
