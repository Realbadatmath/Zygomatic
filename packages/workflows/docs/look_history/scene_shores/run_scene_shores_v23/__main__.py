# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.run_scene_shores_v23` — the entry point the old
run_scene_shores_v23.py carried as its `if __name__ == '__main__'` block (lines
1060-1061).
"""

from zyg_workflows.run_scene_shores_v23.pipeline import main


if __name__ == '__main__':
    raise SystemExit(main())
