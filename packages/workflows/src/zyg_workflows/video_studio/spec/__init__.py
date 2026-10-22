# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, parameter spec — RACKS, ACTIONS and the sanitizer over them.

Moved verbatim (lines 179-4001 of the old single-file module). This is the
declarative surface the GUI builds its three rails from, plus the three
functions that are only meaningful against it: defaults(), sanitize() (which
clamps whatever a caller sends) and nondefault().

Nothing here is a threshold the pipeline reads directly — every value is a
default, a range or a label the spec publishes.
"""

import json

from zyg_workflows import wan_video_service as _wan

from ..options import (
    RESOLUTIONS,
    _ambience_options,
    _DEF_PATHWAY,
    _lora_options,
    _lut_options,
    _vfx_element_options,
)

# Submodules in the original section order, so module-level side effects — the
# calls to _lut_options() and friends inside the rack literals — run exactly
# when they used to.
from .racks import RACKS
from .actions import ACTIONS
from .sanitize import _PARAMS, defaults, nondefault, sanitize

# The package's re-export surface: every name the spec section exposed, in
# import order. Declared so the imports above need no file-level suppression.
__all__ = [
    'json',
    '_wan',
    'RESOLUTIONS',
    '_ambience_options',
    '_DEF_PATHWAY',
    '_lora_options',
    '_lut_options',
    '_vfx_element_options',
    'RACKS',
    'ACTIONS',
    '_PARAMS',
    'defaults',
    'nondefault',
    'sanitize',
]
