#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_realism_bench.py — the same framings, before and after, every time.

The Character Studio realism defects are all things you only see at a
particular distance: the sub-pixel crust on lashes and brows appears at head
framing and vanishes at a macro, the skin's bake patches show on the body and
not on the face, the hair reads as planks only once it fills the frame. A fix
that is judged at one distance is a fix that regresses at another — so this
shoots a FIXED LADDER of framings into a named set, and two sets can be put
side by side.

    python3 tests/char_realism_bench.py --out output/realism_bench/before
    ...make changes...
    python3 tests/char_realism_bench.py --out output/realism_bench/after
    python3 tests/char_realism_bench.py --compare before after

Every shot is of the same body at the same camera, so a difference between two
sets is a difference the change made and not a difference in where we looked.
"""

import argparse
import json
import os
import time

URL = os.environ.get('CHAR_STUDIO_URL', 'http://127.0.0.1:8899/inspection.html#charstudio')

# name, target (fraction of height from the feet), distance (x head heights),
# azimuth, elevation
SHOTS = [
    # 0.945/0.9 framed the brow ridge and the top of the nose; the eye sits
    # about 0.42 head-heights below the crown, so the eye line is ~0.938 h
    ('eye_macro', 0.938, 1.5, 0.0, 0.0),
    ('face', 0.930, 2.6, 0.0, 0.0),
    ('head', 0.925, 4.4, 0.0, 0.0),
    ('head_tq', 0.925, 4.4, 35.0, 8.0),
    ('bust', 0.860, 9.0, 0.0, 0.0),
    ('body', 0.500, 34.0, 0.0, 0.0),
    ('torso', 0.640, 16.0, 20.0, 0.0),
]

FRAME_JS = """([ty, d, az, el]) => {
    var h = CS3.height || 1.7, a = az * Math.PI / 180, e = el * Math.PI / 180;
    var hh = 0.13 * h, y = h * ty, dist = hh * d;
    CS3.controls.target.set(0, y, 0);
    CS3.camera.position.set(dist * Math.cos(e) * Math.sin(a),
                            y + dist * Math.sin(e),
                            dist * Math.cos(e) * Math.cos(a));
    CS3.controls.update();
    var p = document.getElementById('cst-panel'); if (p) p.classList.remove('on');
    var c = document.getElementById('cs-credit'); if (c) c.style.display = 'none';
    var hint = document.querySelector('#cs-3d .cs-hint'); if (hint) hint.style.display = 'none';
}"""


def capture(out_dir, *, body='male_realistic', photoreal=True, size=(1000, 1000), timeout_s=240, settle_s=1.4):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    errs, shot = [], {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        ctx = b.new_context(viewport={'width': size[0], 'height': size[1]})
        ctx.add_init_script(
            'try{localStorage.setItem("cs.photoreal",%s);'
            'localStorage.setItem("cs.hairasset","");}catch(e){}' % ('"1"' if photoreal else '"0"')
        )
        ctx.add_init_script('try{localStorage.setItem("cs.basebody",%s);}catch(e){}' % json.dumps(body))
        page = ctx.new_page()
        page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        page.on('console', lambda m: errs.append('console: ' + m.text) if m.type == 'error' else None)
        page.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("charstudio")')
        page.wait_for_function('typeof CS3 !== "undefined" && CS3.model && !CS3.loading', timeout=timeout_s * 1000)
        if photoreal:
            try:
                page.wait_for_function(
                    'window.CSPHOTOREAL && CSPHOTOREAL.isApplied && CSPHOTOREAL.isApplied()', timeout=120000
                )
            except Exception:
                errs.append('photoreal skin never applied')
        info = page.evaluate("""() => ({
            model: CS3.modelId,
            hair: !!CS3.hair,
            hairInfo: CS3.hairInfo || null,
            dehaired: !!(window.CSPHOTOREAL && CSPHOTOREAL.state.man
                         && CSPHOTOREAL.state.man.dehaired),
            albedo: (window.CSPHOTOREAL && CSPHOTOREAL.state.man
                     && CSPHOTOREAL.state.man.albedo_used) || null,
        })""")
        for name, ty, d, az, el in SHOTS:
            page.evaluate(FRAME_JS, [ty, d, az, el])
            time.sleep(settle_s)
            page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            c = page.query_selector('#cs-3d canvas')
            fp = os.path.join(out_dir, name + '.png')
            (c or page).screenshot(path=fp)
            shot[name] = fp
        b.close()
    rep = {'out': out_dir, 'shots': shot, 'info': info, 'errors': errs[:30]}
    with open(os.path.join(out_dir, 'bench.json'), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, indent=1)
    return rep


def compare(root, a, b, out=None):
    """One sheet per framing: set A above set B."""
    from PIL import Image, ImageDraw

    da, db = os.path.join(root, a), os.path.join(root, b)
    names = [
        n
        for n, *_ in SHOTS
        if os.path.isfile(os.path.join(da, n + '.png')) and os.path.isfile(os.path.join(db, n + '.png'))
    ]
    if not names:
        raise SystemExit(f'no shots shared between {da} and {db}')
    ims = [(n, Image.open(os.path.join(da, n + '.png')), Image.open(os.path.join(db, n + '.png'))) for n in names]
    w, h = ims[0][1].size
    s = 460 / max(w, h)
    cw, ch = int(w * s), int(h * s)
    sheet = Image.new('RGB', (cw * len(ims), ch * 2 + 26), (12, 13, 17))
    d = ImageDraw.Draw(sheet)
    for i, (n, ia, ib) in enumerate(ims):
        sheet.paste(ia.resize((cw, ch)), (i * cw, 22))
        sheet.paste(ib.resize((cw, ch)), (i * cw, ch + 26))
        d.text((i * cw + 6, 6), n, fill=(210, 215, 225))
    d.text((6, ch + 8), f'{a}  (above)   vs   {b}  (below)', fill=(150, 200, 255))
    out = out or os.path.join(root, f'{a}_vs_{b}.png')
    sheet.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out')
    ap.add_argument('--body', default='male_realistic')
    ap.add_argument('--clay', action='store_true')
    ap.add_argument('--size', nargs=2, type=int, default=[1000, 1000])
    ap.add_argument('--compare', nargs=2, metavar=('A', 'B'))
    ap.add_argument('--root', default='output/realism_bench')
    a = ap.parse_args()
    if a.compare:
        print(compare(a.root, a.compare[0], a.compare[1]))
        return
    if not a.out:
        raise SystemExit('--out or --compare required')
    rep = capture(a.out, body=a.body, photoreal=not a.clay, size=tuple(a.size))
    print(
        json.dumps(
            {'out': rep['out'], 'shots': len(rep['shots']), 'info': rep['info'], 'errors': rep['errors']}, indent=1
        )
    )


main()
