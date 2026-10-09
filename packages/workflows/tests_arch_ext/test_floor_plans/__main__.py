# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python tests_arch_ext/test_floor_plans` — the sweep's family script, now a package.

test_all.py ran the family as a file; a directory is run through its __main__.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_floor_plans  # noqa: F401,E402  (the whole sweep runs on import, and finish() exits)
