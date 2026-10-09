# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.angles` — the CLI angles.py carried in its
own `if __name__ == '__main__'` guard before the split."""

import sys

from zyg_workflows.geom.form.angles.aggregate import main

if __name__ == '__main__':
    # argparse takes its prog from basename(sys.argv[0]); under -m that is now this
    # __main__.py, where before the split it was angles.py. Restored so the usage line
    # the module docstring advertises is byte-identical to the pre-split one.
    sys.argv[0] = 'angles.py'
    sys.exit(main())
