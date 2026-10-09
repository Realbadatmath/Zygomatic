# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.mvconsist` — unchanged entry point.

mvconsist.py's own `if __name__ == '__main__': raise SystemExit(_main(sys.argv[1:]))`
moved, verbatim, into verdicts.py with the rest of its section; a submodule's guard
never fires, so the package carries the same two lines here instead.
"""

import sys

from zyg_workflows.geom.mvconsist.verdicts import _main

if __name__ == '__main__':
    raise SystemExit(_main(sys.argv[1:]))
