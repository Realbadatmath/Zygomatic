# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every module of this package imports cleanly in a child process (scripts/import_smoke.py).

The skip list beside this file names the modules that cannot yet; it only shrinks (the ratchet
counts it). A failure here is an import-time regression: a re-export that stopped binding, a
by-path caller of a file that became a package, a name a sibling binds late.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.basename(os.path.dirname(HERE))
TOOL = os.path.join(HERE, '..', '..', '..', 'scripts', 'import_smoke.py')


def test_every_module_imports():
    if not os.path.exists(TOOL):
        import pytest

        pytest.skip('scripts/import_smoke.py is not shipped with this checkout')
    r = subprocess.run(
        [sys.executable, TOOL, 'run', '--package', PACKAGE, '--workers', '4', '--quiet'],
        capture_output=True,
        text=True,
        check=False,
        timeout=3600,
    )
    assert r.returncode == 0, r.stdout + r.stderr
