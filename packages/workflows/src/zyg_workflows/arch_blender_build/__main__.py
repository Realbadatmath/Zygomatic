#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The entry point the old arch_blender_build.py carried as its `if __name__ == '__main__'`
block, reachable two ways:

  blender -b --python .../arch_blender_build/__main__.py -- --in DRAWING.json --out OUT.blend
  python -m zyg_workflows.arch_blender_build -- --in DRAWING.json --out OUT.blend

Blender runs a script by PATH, with no package context and `zyg_workflows` not necessarily
importable, so the sys.path bootstrap below exists for exactly that case. Every caller that
spells out `.../arch_blender_build.py` must now spell out `.../arch_blender_build/__main__.py`.
"""

import os
import sys

try:
    from zyg_workflows.arch_blender_build.cli import main
except ImportError:  # run by path: put <...>/src on sys.path and retry
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from zyg_workflows.arch_blender_build.cli import main


if __name__ == '__main__':
    main()
