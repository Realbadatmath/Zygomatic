# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.run_scene_shores_v26 [--verify-only]` — the entry
point the deleted single-file script carried as its `__main__` guard."""

from zyg_workflows.run_scene_shores_v26.main import main

raise SystemExit(main())
