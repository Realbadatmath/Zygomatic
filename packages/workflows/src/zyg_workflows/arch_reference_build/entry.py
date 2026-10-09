# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The file Blender runs: ``blender -b --factory-startup --python <this> -- …``.

``--python`` takes a FILE, so the builder keeps one, and everything it used to
hold now lives in the package beside it. The parent directory goes on sys.path
so ``import arch_reference_build`` resolves under --factory-startup, where the
server's PYTHONPATH is not there to help.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arch_reference_build.main import main  # noqa: E402

main()
