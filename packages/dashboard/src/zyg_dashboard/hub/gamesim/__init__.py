# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Game Simulator server, split along its sections.

The sibling ``schem_*`` modules live in the parent ``hub`` directory and are
imported by plain name, so that directory goes on ``sys.path`` here, before any
submodule of this package is loaded.
"""

import sys
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB_DIR))
