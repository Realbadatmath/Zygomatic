# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``python -m zyg_workflows.scene_shot_run SHOT.json --engine vace`` -- the entry point the
single-file scene_shot_run.py carried as its ``if __name__ == '__main__'`` block, kept for the
callers that ran that file by path (studio_ext_server/movement_rig.py)."""

from zyg_workflows.scene_shot_run.runner import main

if __name__ == '__main__':
    main()
