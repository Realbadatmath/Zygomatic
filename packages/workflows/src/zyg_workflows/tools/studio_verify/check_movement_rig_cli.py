# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.check_movement_rig`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.check_movement_rig` still reaches it.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.check_movement_rig import (
    SHOT,
    SHOT_FIT,
    VIEWPORTS,
    run,
)


def main():
    runs = []
    with sync_playwright() as pw:
        for i, (w, h) in enumerate(VIEWPORTS):
            runs.append(run(pw, w, h, shoot=(i == 0)))
    print(
        json.dumps(
            {
                'ok': True,
                'runs': runs,
                'screenshot': SHOT,
                'screenshot_bytes': os.path.getsize(SHOT),
                'screenshot_fit': SHOT_FIT,
                'screenshot_fit_bytes': os.path.getsize(SHOT_FIT),
            },
            indent=1,
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
