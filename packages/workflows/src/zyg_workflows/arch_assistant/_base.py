# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shared module header of the old single-file arch_assistant.py (lines 45-68).

HERE climbs one directory more than the original line did: the old module WAS
zyg_workflows/arch_assistant.py, so HERE was the zyg_workflows directory, and
data/architecture, data/runtime/arch_assistant and arch_mcp_shim.py all hang off it.
The logger keeps the old module's name for the same reason.
"""

from __future__ import annotations

import logging as _zyg_logging
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH_DIR = os.path.join(HERE, 'data', 'architecture')
BLEND_DIR = os.path.join(ARCH_DIR, 'blender')

_zyg_log = _zyg_logging.getLogger(__package__)
