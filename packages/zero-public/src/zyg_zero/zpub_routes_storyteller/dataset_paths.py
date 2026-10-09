# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The storyteller-character dataset root, in a module nobody's routes live in.

`proxy_routes` and `char_library` both read `_DATASET_ROOT`, but `char_library`
must register its routes AFTER `proxy_routes`, so proxy_routes cannot import it
from there. The constant lives here instead: a leaf module with no blueprint and
no side effects, which either section may import at its top.
"""

from zyg_workflows import paths

_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
