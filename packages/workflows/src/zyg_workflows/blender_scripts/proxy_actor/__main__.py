# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The by-path entry the single-file proxy_actor.py was: Blender runs a script by PATH,

    blender -b --python .../blender_scripts/proxy_actor/__main__.py -- --body base --name ...

with no package context and ``zyg_workflows`` not necessarily importable, so the sys.path
bootstrap below exists for exactly that case. The package runs ``main()`` at import time,
exactly as the file did, so importing it IS running it. Callers that spelled out
``.../blender_scripts/proxy_actor.py`` now spell out ``.../blender_scripts/proxy_actor/__main__.py``.
"""

import os
import sys

try:
    import zyg_workflows.blender_scripts.proxy_actor  # noqa: F401  main() runs at import
except ImportError:  # run by path: put <...>/src on sys.path and retry
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    import zyg_workflows.blender_scripts.proxy_actor  # noqa: F401
