# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.continuity_qc` — kept working after the package split.

The `if __name__ == '__main__': _main(sys.argv[1:])` tail of the original
single-file module now lives in continuity_qc/ownership.py, where it can never
fire; this entry point is the same call.
"""

import sys

from zyg_workflows.continuity_qc import _main

_main(sys.argv[1:])
