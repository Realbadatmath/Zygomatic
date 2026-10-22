# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.verify_melody_boards`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.verify_melody_boards` still reaches it.
"""

import sys

from zyg_workflows.tools.verify_melody_boards import (
    CHECK_JS,
    CINE,
    CINE_COLS,
    CINE_DROPPED,
    CINE_JS,
    URL,
    WIRED,
    _launch,
)


def main():
    from playwright.sync_api import sync_playwright

    cine = '--cinematic' in sys.argv[1:]
    errors = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console.error: ' + m.text) if m.type == 'error' else None)
        page.goto(URL, wait_until='domcontentloaded', timeout=30000)
        # The flyout rows are built by _buildMelodyMenu() after init.
        # state='attached', not the default 'visible': the Melodies group is
        # collapsed until the operator clicks its chevron, so the rows are in
        # the DOM (which is all this checks) but never visible on load.
        page.wait_for_selector(
            '#kb-chgrp-melodies .kb-ch-item[data-key="mel_children_dance"]', state='attached', timeout=15000
        )
        res = page.evaluate(CINE_JS, [CINE, CINE_DROPPED, CINE_COLS, WIRED]) if cine else page.evaluate(CHECK_JS, WIRED)
        browser.close()

    fails = list(res.get('fail') or [])
    if errors:
        fails.append(f'{len(errors)} page error(s): ' + ' | '.join(errors[:5]))
    if fails:
        for f in fails:
            print('FAIL: ' + f)
        return 1
    if cine:
        print(
            f'PASS  {len(CINE)} cinematic boards = kidsmusic minus Pictures '
            f'and Lyrics ({res["want_cols"]} cols '
            f'[{",".join(CINE_COLS)}] / {res["want_cards"]} cards) in '
            f'TEMPLATES and TEMPLATES_SDXL, each naming its style + four '
            f'voices and its instrumental caption; the {len(WIRED)} children '
            f'boards still 6/12; 0 page errors'
        )
        return 0
    print(
        f'PASS  11 wired children boards = kidsmusic clone '
        f'({res["ref_cols"]} cols / {res["ref_cards"]} cards) in TEMPLATES '
        f'and TEMPLATES_SDXL; mel_children_dance 5/0 + kb-ch-off; '
        f'0 page errors'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
