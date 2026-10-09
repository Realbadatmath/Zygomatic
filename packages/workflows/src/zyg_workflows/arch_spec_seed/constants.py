# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.constants — the paths the seed writer runs from.

Moved verbatim out of the 1,179-line arch_spec_seed.py; original lines 19-27.
"""

from __future__ import annotations

# This module inherits the single file's own top import block; `json` is used
# by cli.py and re-exported from here, so F401 must not strip it.
# ruff: noqa: F401

import json
import os
import sys

from zyg_workflows import paths

#: The ``zyg_workflows`` package directory, which ``arch_assistant_ext`` hangs off.
#: ``cli.main`` puts that extension directory on ``sys.path`` itself, at the one
#: point where the ``object_specs`` module it loads by file path needs it there.
HERE = str(paths.PKG_DIR)
