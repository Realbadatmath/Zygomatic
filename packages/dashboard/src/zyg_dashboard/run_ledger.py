# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compatibility shim: this module moved to `zyg_workflows.run_ledger`.

Pipelines record stages, fallbacks and gates, so the ledger belongs to the base
library. Import `from zyg_workflows import run_ledger` instead. The module
object itself is aliased so module-level caches stay single-instance.
"""

import sys as _sys

from zyg_workflows import run_ledger as _moved

_sys.modules[__name__] = _moved
