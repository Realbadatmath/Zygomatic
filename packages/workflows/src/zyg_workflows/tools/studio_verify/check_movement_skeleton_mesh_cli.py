# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.check_movement_skeleton_mesh`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.check_movement_skeleton_mesh` still reaches it.
"""

import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.check_movement_skeleton_mesh import (
    run,
)


def main():
    shoot = '--no-shot' not in sys.argv
    with sync_playwright() as pw:
        sk, c, made = run(pw, shoot)
    print(
        "\nPASS — the Bones layer is the actor's own skeleton: %d pieces, "
        "%d vertices, skinned to the body's %d joints; %d rig joints still drawn"
        % (c['bone'], sk['vertices'], sk['bones'], c['joint'])
    )
    for p in made:
        print('      %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
