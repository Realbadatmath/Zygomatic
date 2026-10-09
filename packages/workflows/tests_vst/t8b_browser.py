#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 8b browser proof — drives the real Video Studio page in system Chrome.

Two screenshots are the deliverable:
  t8b_racks.png   the console with the new AUDIO / OVERLAY / SHOTS cells drawn
  t8b_dryrun.png  a dry run started FROM A STILL, its log showing link 3/3

Nothing here is mocked: the page is the one kanban-server serves on :8899 and
the render is a real /video/api/render job (dry_run, so it submits no graph).
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8899'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'video_studio', '_wire')
KEYS = ['audio_bed', 'upscale', 'overlay_record', 'shot_list']


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    racks = os.path.join(OUT, 't8b_racks.png')
    dryrun = os.path.join(OUT, 't8b_dryrun.png')
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
        pg = br.new_page(viewport={'width': 1680, 'height': 1050})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(BASE + '/inspection.html#videos', wait_until='domcontentloaded')
        pg.evaluate("switchView('videos')")
        # the racks are drawn from /video/api/spec, so wait for a cell, not a
        # timeout — the fetch is what decides when the strip exists
        pg.wait_for_selector('#vst-ic-shot_list', timeout=30000)

        missing = [k for k in KEYS if pg.query_selector('#vst-ic-' + k) is None]
        if missing:
            print('MISSING param cells: ' + ', '.join(missing))
            return 1
        print('param cells present: ' + ', '.join(KEYS))
        for icon in ('ic-audio', 'ic-overlay', 'ic-shots', 'ic-assemble'):
            n = pg.evaluate("id=>document.querySelectorAll('symbol#'+id).length", icon)
            print(f'symbol {icon}: {n}')
            if n != 1:
                print(f'SYMBOL {icon} not in the sprite')
                return 1
        if pg.query_selector('#vst-act-assemble') is None:
            print('MISSING assemble action icon')
            return 1
        print('assemble action icon present')
        # the cells EXIST as soon as the spec lands, but their <use> sprites
        # paint a frame or two later — screenshot the settled page, or the PNG
        # is a near-empty one that compresses to nothing
        pg.wait_for_load_state('networkidle')
        pg.wait_for_timeout(1500)
        pg.screenshot(path=racks, full_page=False)
        print(f'screenshot {racks} ({os.path.getsize(racks)} bytes)')

        # ── the json / longtext controls ───────────────────────────────────
        pg.click('#vst-ic-shot_list')
        pg.wait_for_selector('#vst-json-shot_list', timeout=5000)
        rows = pg.get_attribute('#vst-json-shot_list', 'rows')
        print(f'shot_list textarea rows={rows}')
        if rows != '6':
            print('shot_list is not a rows="6" textarea')
            return 1
        for text, want_bad in (('{"shots": [', True), ('{"shots": []}', False)):
            pg.fill('#vst-json-shot_list', text)
            pg.dispatch_event('#vst-json-shot_list', 'change')
            is_bad = pg.evaluate("document.getElementById('vst-json-shot_list').classList.contains('bad')")
            print(f'  json {text!r} -> bad={is_bad} (want {want_bad})')
            if is_bad != want_bad:
                print('json validation did not mark the field as expected')
                return 1
        pg.click('#vst-ic-link_prompts')
        pg.wait_for_selector('#vst-pop.on textarea[rows="6"]', timeout=5000)
        print('link_prompts (longtext) drew a rows="6" textarea')
        pg.evaluate('vstPopClose()')

        # ── inject picker → Stills tab ─────────────────────────────────────
        pg.click('#vst-act-inject')
        pg.wait_for_selector('#vst-inject.on', timeout=10000)
        pg.click('#vst-itab-stills')
        pg.wait_for_selector('#vst-ilane-stills .cs-icard', timeout=15000)
        n_stills = pg.evaluate("document.querySelectorAll('#vst-sboard .cs-icard').length")
        print(f'stills listed: {n_stills}')
        if not n_stills:
            print('STILLS LIST EMPTY')
            return 1
        pg.click('#vst-sboard .cs-icard')
        pg.wait_for_function("!document.getElementById('vst-igo').disabled", timeout=5000)
        pg.click('#vst-igo')
        pg.wait_for_function("VST.stillPath!==''", timeout=10000)
        print('still injected: ' + pg.evaluate('VST.stillPath'))

        # ── dial it to a 3-link dry run and render ─────────────────────────
        pg.evaluate("vstSet('link_prompts','A one || B two || C three')")
        pg.evaluate("vstSet('duration_s','10.2')")
        pg.evaluate("vstSet('frames',61)")
        pg.evaluate("vstSet('dry_run',true)")
        pg.click('#vst-act-render')
        t0 = time.time()
        got = False
        while time.time() - t0 < 120:
            log = pg.evaluate("(document.getElementById('vst-log')||{}).textContent||''")
            if 'link 3/3' in log:
                got = True
                break
            time.sleep(1.0)
        log = pg.evaluate("(document.getElementById('vst-log')||{}).textContent||''")
        pg.screenshot(path=dryrun, full_page=False)
        print('screenshot ' + dryrun)
        for line in [ln for ln in log.splitlines() if 'link ' in ln][:8]:
            print('  LOG ' + line[:140])
        br.close()
        if errs:
            print('PAGE ERRORS: ' + ' | '.join(errs[:5]))
            return 1
        if not got:
            print('TIMEOUT: "link 3/3" never reached the log in 120 s')
            return 1
    print('T8B BROWSER OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
