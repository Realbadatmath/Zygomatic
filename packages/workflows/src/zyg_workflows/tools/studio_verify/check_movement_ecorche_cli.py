# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.check_movement_ecorche`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.check_movement_ecorche` still reaches it.
"""

import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.check_movement_ecorche import (
    SHOTS,
    run,
)


def main():
    with sync_playwright() as pw:
        p, px, tick = run(pw)
    print(
        '\nPASS — écorché %s %s on %d body vertices, %.1f red-over-green, '
        '%.3f ms a frame' % (p['ecName'], p['ecSize'], p['verts'], px['r'] - px['g'], tick['mean'])
    )
    for k in ('halfbare_front', 'halfbare_back', 'anat_front', 'halfskin_front', 'head'):
        print('      %s' % SHOTS[k])
    return 0


if __name__ == '__main__':
    sys.exit(main())
