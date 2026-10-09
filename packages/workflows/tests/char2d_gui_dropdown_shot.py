#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof shot for the three-column Templates picker on the Workflows board.

Opens :8899/kanban.html in headless chromium, clicks the picker trigger and
measures the open menu: three .kb-ch-col columns sharing one top edge, the four
Blueprints roman numerals, and that .kb-roman really is painted with a CSS
gradient. Writes output/char2d/_gui/dropdown_menu.png and prints the JSON.

Run with an interpreter that has playwright:
  python3 tests/char2d_gui_dropdown_shot.py
"""

import json
import pathlib

from playwright.sync_api import sync_playwright

# The playwright-managed chromium (~/.cache/ms-playwright/chromium-*/…) is NOT
# installed on this host (checked 2026-09-16), so fall back to the system Chrome.
CHROME_CANDIDATES = [
    str(pathlib.Path.home() / '.cache' / 'ms-playwright' / 'chromium-1208' / 'chrome-linux64' / 'chrome'),
    '/usr/bin/google-chrome',
]
CHROME = next((c for c in CHROME_CANDIDATES if pathlib.Path(c).exists()), None)
URL = 'http://127.0.0.1:8899/kanban.html'
OUT = pathlib.Path(__file__).resolve().parent.parent / 'output' / 'char2d' / '_gui' / 'dropdown_menu.png'

PROBE = """() => ({
  cols: document.querySelectorAll('#kb-ch-menu .kb-ch-col').length,
  romans: [...document.querySelectorAll('#kb-ch-col-blueprints .kb-roman')].map(e => e.textContent),
  gradient: getComputedStyle(document.querySelector('.kb-roman')).backgroundImage.startsWith('linear-gradient'),
  rects: [...document.querySelectorAll('#kb-ch-menu .kb-ch-col')].map(c => {
    const r = c.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top), Math.round(r.width)];
  })
})"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={'width': 2507, 'height': 1567})
        page.goto(URL)
        page.wait_for_timeout(2500)
        page.click('#kb-ch-trigger')
        page.wait_for_timeout(400)
        data = page.evaluate(PROBE)
        menu = page.query_selector('#kb-ch-menu')
        box = menu.bounding_box()
        page.screenshot(
            path=str(OUT),
            clip={
                'x': max(0, box['x'] - 8),
                'y': max(0, box['y'] - 8),
                'width': box['width'] + 16,
                'height': box['height'] + 16,
            },
        )
        browser.close()
    print(json.dumps(data))
    tops = {r[1] for r in data['rects']}
    ok = (
        data['cols'] == 3 and data['romans'] == ['I', 'II', 'III', 'IV'] and data['gradient'] is True and len(tops) == 1
    )
    print('PNG:', OUT)
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
