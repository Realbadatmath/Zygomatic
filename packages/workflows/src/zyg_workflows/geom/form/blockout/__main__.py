# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.blockout` — what `python blockout.py` used to be.

argparse names the program after sys.argv[0], so it is restored to the old file name;
without that the usage line would read `__main__.py` instead of `blockout.py`.
"""

import os
import sys

from zyg_workflows.geom.form.blockout import main

if __name__ == '__main__':
    sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'blockout.py')
    sys.exit(main())
