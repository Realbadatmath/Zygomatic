#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_hair_assets_shot.py — the operator's eye on the installed hair grooms.

Stands the clay base body in the live Character Studio, wears one groom at a
time through CSHAIRASSET.pick(), frames the head and writes a PNG each. The fit
is computed in the browser from the body actually standing there, so this is
the check that the frame the converter measured on the donor and the frame
char_hair.js measures here agree — on the screen, not in a bounding box.

    python3 tests/char_hair_assets_shot.py --out /tmp/grooms --max 6
    python3 tests/char_hair_assets_shot.py --out /tmp/g --ids makehuman_system_hair_cc0'|'afro01
"""

import argparse
import json
import os
import time

URL = os.environ.get('CHAR_STUDIO_URL', 'http://127.0.0.1:8899/inspection.html#charstudio')

FRAME_JS = """([az, el]) => {
    var h = CS3.height || 1.7, a = az * Math.PI / 180, e = el * Math.PI / 180;
    var ty = h * 0.93, d = h * 0.40;
    CS3.controls.target.set(0, ty, 0);
    CS3.camera.position.set(d * Math.cos(e) * Math.sin(a), ty + d * Math.sin(e),
                            d * Math.cos(e) * Math.cos(a));
    CS3.controls.update();
    var p = document.getElementById('cst-panel'); if (p) p.classList.remove('on');
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--body', default='body_male_realistic')
    ap.add_argument('--ids', nargs='*', default=None)
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--az', type=float, default=0.0)
    ap.add_argument('--timeout', type=int, default=180)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    errs, shots = [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        ctx = b.new_context(viewport={'width': 1200, 'height': 1200})
        ctx.add_init_script(
            'try{localStorage.setItem("cs.photoreal","0");localStorage.setItem("cs.hairasset","");}catch(e){}'
        )
        ctx.add_init_script('try{localStorage.setItem("cs.basebody",%s);}catch(e){}' % json.dumps(a.body))
        page = ctx.new_page()
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: errs.append('console ' + m.type + ': ' + m.text) if m.type == 'error' else None)
        page.goto(URL, wait_until='domcontentloaded', timeout=a.timeout * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=a.timeout * 1000)
        page.evaluate('goToView("charstudio")')
        page.wait_for_function('typeof CS3 !== "undefined" && CS3.model && !CS3.loading', timeout=a.timeout * 1000)
        page.wait_for_function('window.CSHAIRASSET && CSHAIRASSET.state.loaded', timeout=a.timeout * 1000)
        cat = page.evaluate(
            '() => ({items: CSHAIRASSET.state.items.map(i => '
            '({id:i.id,label:i.label,kind:i.kind,part:i.part})), '
            'frames: (function(f){ return f ? {headW:f.headW, '
            'skullRadius:f.skullRadius, domeCount:f.domeCount} : null; })'
            '(CSHAIRASSET.frames())})'
        )
        ids = a.ids or [i['id'] for i in cat['items']]
        if a.max:
            ids = ids[: a.max]
        print('frames on the standing body:', json.dumps(cat['frames']))
        for gid in ids:
            page.evaluate('id => CSHAIRASSET.pick(id)', gid)
            try:
                page.wait_for_function(
                    'window.CSHAIRASSET && CSHAIRASSET.state.group && !CSHAIRASSET.state.err', timeout=90000
                )
            except Exception:
                errs.append(f'{gid}: no group after 90 s ' + str(page.evaluate('() => CSHAIRASSET.state.err')))
                continue
            page.evaluate(FRAME_JS, [a.az, 0.0])
            time.sleep(1.2)
            page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            canvas = page.query_selector('#cs-3d canvas')
            fp = os.path.join(a.out, gid.split('|')[-1] + '.png')
            (canvas or page).screenshot(path=fp)
            shots.append(fp)
            print('shot', gid)
        b.close()
    print(json.dumps({'shots': len(shots), 'errors': errs[:20]}, indent=1))


main()
