#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof for the 2D Character Basics blueprint boards on :8899.

Loads kanban.html in chromium, selects each board via the page's own
_selectTemplate(), and reads back what the DOM really shows: column count,
card count, the Run button's computed display, whether the empty-blueprint
note is present, and that all four char2d keys exist in BOTH template
families (TEMPLATES and the SDXL clone, which is the default view).

Exits 1 unless every expectation holds. Screenshots land in
output/char2d/_gui/board_<key>.png.

Run:  python3 tests/char2d_gui_boards.py   (in an environment that has playwright)
"""

import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:8899/kanban.html'
OUT = pathlib.Path(__file__).resolve().parents[1] / 'output' / 'char2d' / '_gui'

# The playwright-managed chromium (~/.cache/ms-playwright/chromium-*/…) is NOT
# installed on this host (checked 2026-09-16), so fall back to the system Chrome
# — same fallback tests/char2d_gui_dropdown_shot.py already uses.
CHROME_CANDIDATES = [
    str(pathlib.Path.home() / '.cache' / 'ms-playwright' / 'chromium-1208' / 'chrome-linux64' / 'chrome'),
    '/usr/bin/google-chrome',
]
CHROME = next((c for c in CHROME_CANDIDATES if pathlib.Path(c).exists()), None)

# NOTE on `cards`: renderBoard() wraps every job card in a .kb-stack, so the
# combined selector '.kb-card, .kb-stack' counts each job TWICE (28 for the 14
# cards of board I). `cards` is therefore the stack count — one per job — and
# `cards_raw` keeps the combined selector's number so the double is visible
# rather than silently corrected.
PROBE = """() => ({
  label: document.getElementById('kb-pipeline-label').textContent,
  cols:  document.querySelectorAll('#kb-board .kb-column').length,
  cards: document.querySelectorAll('#kb-board .kb-stack').length,
  cards_raw: document.querySelectorAll('#kb-board .kb-card, #kb-board .kb-stack').length,
  run:   getComputedStyle(document.getElementById('kb-char2d-run')).display,
  empty: !!document.querySelector('.kb-empty-blueprint'),
  badge: document.getElementById('total-badge').textContent,
  roman: (document.querySelector('#kb-pipeline-label .kb-roman') || {}).textContent || null,
  keys:  ['char2d_basics_1','char2d_basics_2','char2d_basics_3','char2d_basics_4']
           .every(k => k in TEMPLATES && k in TEMPLATES_SDXL),
})"""

EXPECT = {
    'char2d_basics_1': lambda r: (
        r['cols'] == 6
        and r['cards'] == 14
        and r['run'] != 'none'
        and r['empty'] is False
        and r['keys'] is True
        and r['label'].strip() == '[ 2D CHARACTER BASICS I ]'
        and r['roman'] == 'I'
        and r['badge'] == '14 jobs'
    ),
    'char2d_basics_2': lambda r: (
        r['cols'] == 0
        and r['empty'] is True
        and r['run'] == 'none'
        and r['keys'] is True
        and r['label'].strip() == '[ 2D CHARACTER BASICS II ]'
        and r['roman'] == 'II'
        and r['badge'] == '0 jobs'
    ),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={'width': 2507, 'height': 1567})
        page.goto(URL)
        page.wait_for_timeout(2500)
        for key in ('char2d_basics_1', 'char2d_basics_2'):
            page.evaluate("_selectTemplate('" + key + "')")
            page.wait_for_timeout(300)
            results[key] = page.evaluate(PROBE)
            page.screenshot(path=str(OUT / f'board_{key}.png'))
        browser.close()

    print(json.dumps(results, indent=2))
    bad = [k for k, ok in EXPECT.items() if not ok(results[k])]
    if bad:
        print('FAIL: ' + ', '.join(bad), file=sys.stderr)
        return 1
    print(
        'OK: I = 6 cols / 14 cards / 14 jobs / Run shown; '
        'II = empty placeholder / 0 jobs / no Run; '
        'both labels carry their .kb-roman numeral; all four keys in both families'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
