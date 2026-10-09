# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python3 -m zyg_workflows.geom.anthro.build_reference` — the entry point the single
module carried in its own `if __name__ == '__main__'` block. A package reaches __main__
through this file instead, so the invocation the module docstring documents and the one
geom/anthro/reference.py tells the user to run keep working unchanged.
"""

from zyg_workflows.geom.anthro.build_reference.pipeline import main

raise SystemExit(main())
