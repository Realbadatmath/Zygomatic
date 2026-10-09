# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The documentary functional-test harness, split out of the 2,089-line
`scripts/test_documentary_stack.py`.

The submodules are imported in the original section order so that the venv
re-exec, the sys.path insert and the chdir in `core` still run first.
"""

# ruff: noqa: F401

from . import core
from . import basics
from . import inpaint_and_judges
from . import gates_and_ladder
from . import staleness_and_receipts
from . import klein
from . import anachronism
from . import runner
from .runner import main
