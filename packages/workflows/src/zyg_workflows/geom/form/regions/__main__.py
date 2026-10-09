# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.form.regions` — the entry point the single module carried
in its own `if __name__ == '__main__'` block. A package reaches __main__ through this file
instead, so `python -m zyg_workflows.geom.form.regions build`, which load_regions() prints
as the fix when regions.json has not been authored yet, keeps working unchanged.
"""

from zyg_workflows.geom.form.regions.builder import main

raise SystemExit(main())
