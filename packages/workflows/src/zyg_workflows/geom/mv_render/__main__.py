# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script entry point, moved verbatim from the tail of geom/mv_render.py.

It is reached two ways, exactly as the pre-split file was:
`python -m zyg_workflows.geom.mv_render`, and `blender -b --python <this file>`
(see `_render_positive`, which builds this path from `constants.ROOT`).
"""

import sys

from zyg_workflows.geom.mv_render import main
from zyg_workflows.geom.mv_render.blender_main import _bl_main

if __name__ == '__main__':
    try:
        import bpy  # noqa: F401

        _in_blender = True
    except ImportError:
        _in_blender = False
    if _in_blender:
        _bl_main(sys.argv[sys.argv.index('--') + 1])
    else:
        sys.exit(main())
