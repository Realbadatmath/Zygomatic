# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compatibility shim: this module moved to `zyg_workflows.gui_state`.

It holds pipeline/GPU state, not GUI state, so it now lives in the base
library. Import `from zyg_workflows import gui_state` instead. Aliasing the
module object (rather than re-exporting names) is required: every name here is
REBOUND at runtime, so the two paths must be the same module object.
"""

import sys as _sys

from zyg_workflows import gui_state as _moved

_sys.modules[__name__] = _moved
