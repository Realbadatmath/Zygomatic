# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.acceptance`, moved out of the library
module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.acceptance` still reaches it.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.acceptance import (
    OUT,
    RES,
    URL,
    VH,
    VW,
    charstudio,
    check,
    creatures,
    measure,
    mesh,
    movement,
    page_offline_checks,
)


def main():
    os.makedirs(OUT, exist_ok=True)
    page_offline_checks()

    console_errors = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': VW, 'height': VH})
        pg.on('console', lambda m: console_errors.append('console.error: ' + m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: console_errors.append('pageerror: ' + str(e)))
        pg.goto(URL, wait_until='load', timeout=120000)
        pg.wait_for_function('typeof CS_TOOLS !== "undefined" && typeof CT !== "undefined"', timeout=60000)
        pg.wait_for_timeout(1500)

        loaded = pg.evaluate('() => !!(window.SX && SX.ready)')
        measure('page', 'SX_present', bool(loaded))

        # ── 1. CHARACTER STUDIO ──────────────────────────────────────────────
        charstudio(pg)
        # ── 2. CREATURE STUDIO ───────────────────────────────────────────────
        creatures(pg)
        # ── 3. MOVEMENT STUDIO ───────────────────────────────────────────────
        movement(pg)
        # ── 4. MESH STUDIO ───────────────────────────────────────────────────
        mesh(pg)

        ext_errors = [e for e in console_errors if 'studio_ext' in e]
        measure('page', 'console_errors', console_errors[:25])
        measure('page', 'console_errors_total', len(console_errors))
        check('page', "no console error mentions 'studio_ext'", not ext_errors, ext_errors[:5])
        br.close()

    RES['pass'] = not RES['failures']
    path = os.path.join(OUT, 'acceptance.json')
    with open(path, 'w') as f:
        json.dump(RES, f, indent=2, sort_keys=False)
    print('\nwrote ' + path)
    print('RESULT %s — %d failure(s)' % ('PASS' if RES['pass'] else 'FAIL', len(RES['failures'])))
    for f_ in RES['failures']:
        print('   ! ' + f_)
    return 0 if RES['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
