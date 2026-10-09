# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.__main__ — the old module's `python -m` entry point."""

from zyg_workflows.storyteller_scene_service import SECOND_LEDGER_INTRO, build_scene

if __name__ == '__main__':
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else None
    r = build_scene(SECOND_LEDGER_INTRO, out_dir=out)
    sys.exit(0 if r else 1)
