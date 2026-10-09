# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.curvature` — the entry point the old curvature.py carried as its
`if __name__ == '__main__'` block.
"""

from zyg_workflows.geom.form.curvature.selftest import main


if __name__ == '__main__':
    raise SystemExit(main())
