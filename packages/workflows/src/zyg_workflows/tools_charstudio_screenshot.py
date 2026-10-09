#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tools_charstudio_screenshot.py — the operator's eye on the Character Studio.

Drives the live studio tab in headless Chrome (the same launch as
tools_arch_screenshot.py: channel=chrome + swiftshader, so WebGL renders
without a display), waits for the base body, optionally switches the
photoreal skin on and/or Compare, frames the whole figure or the head, and
writes the stage to a PNG. Page errors are collected and printed.

    python tools_charstudio_screenshot.py --out /tmp/a.png
    python tools_charstudio_screenshot.py --photoreal --frame head --out /tmp/b.png
    python tools_charstudio_screenshot.py --photoreal --compare --out /tmp/c.png
    python tools_charstudio_screenshot.py --photoreal --frame head --az 40 --out /tmp/d.png
"""

import argparse
import json
import os
import sys
import time
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


URL = os.environ.get('CHAR_STUDIO_URL', paths.ZYG_KANBAN_URL + '/inspection.html#charstudio')


FRAME_JS = """([frame, az, el, hidePanel]) => {
    var h = CS3.height || 1.7, a = az * Math.PI / 180, e = el * Math.PI / 180;
    var ty = frame === 'head' ? h * 0.93 : h * 0.5;
    var d = frame === 'head' ? h * 0.36 : h * 1.75;
    if (frame === 'fit') { d = (h * 0.60) / Math.tan(CS3.camera.fov * Math.PI / 360); }
    CS3.controls.target.set(0, ty, 0);
    CS3.camera.position.set(d * Math.cos(e) * Math.sin(a), ty + d * Math.sin(e), d * Math.cos(e) * Math.cos(a));
    CS3.controls.update();
    if (hidePanel) { var p = document.getElementById('cst-panel'); if (p) p.classList.remove('on'); }
}"""


def _frame(page, frame, az, el, hide_panel=True):
    """Whole figure or the head, from an azimuth (deg, 0 = front) and elevation."""
    page.evaluate(FRAME_JS, [frame, float(az), float(el), bool(hide_panel)])


def _settle(page, settle_s):
    time.sleep(settle_s)
    page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def shoot(
    out_png,
    *,
    photoreal=False,
    compare=False,
    frame='body',
    az=0.0,
    el=0.0,
    width=1600,
    height=1400,
    body='',
    url=URL,
    timeout_s=180,
    settle_s=2.5,
    panel=False,
    clay=False,
    models=False,
):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    errs, logs = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        ctx = browser.new_context(viewport={'width': int(width), 'height': int(height)})
        # --photoreal forces the switch on, --clay forces it off; neither
        # leaves localStorage alone so the page's own default is what is shot
        if photoreal or clay:
            ctx.add_init_script(
                'try{localStorage.setItem("cs.photoreal", %s);}catch(e){}' % ('"1"' if photoreal else '"0"')
            )
        if body:
            ctx.add_init_script('try{localStorage.setItem("cs.basebody", %s);}catch(e){}' % json.dumps(body))
        page = ctx.new_page()
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: logs.append(m.type + ': ' + m.text) if m.type in ('error', 'warning') else None)
        page.on('dialog', lambda d: d.accept())
        page.goto(url, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("charstudio")')
        page.wait_for_function('typeof CS3 !== "undefined" && CS3.model && !CS3.loading', timeout=timeout_s * 1000)
        if photoreal:
            page.wait_for_function(
                'window.CSPHOTOREAL && CSPHOTOREAL.isApplied && CSPHOTOREAL.isApplied()', timeout=timeout_s * 1000
            )
        if compare:
            page.evaluate('CST_ACT.compare()')
            page.wait_for_function('window.CSCMP && CSCMP.on && CSCMP.model', timeout=timeout_s * 1000)
            if photoreal:
                page.wait_for_function('CSPHOTOREAL.isApplied()', timeout=timeout_s * 1000)
        if models:
            page.wait_for_function('window.CSMODELS && document.getElementById("csm-btn")', timeout=timeout_s * 1000)
            page.evaluate('CSMODELS.open()')
            page.wait_for_function(
                'document.querySelectorAll("#csm-menu .csm-item").length > 1', timeout=timeout_s * 1000
            )
            page.hover('#csm-menu .csm-item.derived')
            page.wait_for_function(
                'document.getElementById("csm-card").classList.contains("on")', timeout=timeout_s * 1000
            )
            time.sleep(1.5)
        if panel:
            page.evaluate('CST_ACT.photoreal()')
            page.wait_for_function(
                'document.querySelector("#cst-panel.on #pr-toggle") !== null', timeout=timeout_s * 1000
            )
        _frame(page, frame, az, el, hide_panel=not (panel or models))
        if not (photoreal or clay):
            try:
                page.wait_for_function('window.CSPHOTOREAL && CSPHOTOREAL.isApplied()', timeout=60000)
            except Exception as _exc:
                _zyg_log.warning('photoreal never reported applied, shooting the page as it stands: %s', _exc)
        _settle(page, settle_s)
        canvas = None if (panel or models) else page.query_selector('#cs-3d canvas')
        info = page.evaluate("""() => {
            var m = null; CS3.model.traverse(o => { if (o.isMesh && (!m || o.geometry.attributes.position.count > m.geometry.attributes.position.count) && !/eye[lr]$/i.test(o.name||'')) m = o; });
            return { modelId: CS3.modelId, bodyVerts: m ? m.geometry.attributes.position.count : 0,
                     material: m && m.material ? (m.material.map ? 'textured ' + m.material.map.image.width + 'x' + m.material.map.image.height : 'plain #' + m.material.color.getHexString()) : 'none',
                     uvAtlas: m && m.geometry.userData.uvAtlas || '', compare: !!(window.CSCMP && CSCMP.on),
                     photoreal: !!(window.CSPHOTOREAL && CSPHOTOREAL.state.on) };
        }""")
        if canvas:
            canvas.screenshot(path=out_png)
        else:
            page.screenshot(path=out_png)
        browser.close()
    return {'out': out_png, 'errors': errs, 'console': logs[-20:], 'info': info}


# the Models card (char_models.js) shows the model AS THE STUDIO STANDS IT:
# photoreal skin + the groom char_hair.js builds + char_eyes.js eyes.  klein's
# bake photos are of the bald base mesh (the depth plates carry no hair), so a
# card built from them showed a bald man while the frame showed hair.
PREVIEW_SHOTS = [
    # name,        frame,  az,  el, viewport (w, h), crop aspect (w:h)
    ('head_front', 'head', 0.0, 0.0, (1400, 1400), (1, 1)),
    ('body_front', 'fit', 0.0, 0.0, (1400, 1700), (3, 4)),  # the WHOLE figure, straight on
    ('head_tq', 'head', 35.0, 0.0, (1400, 1700), (3, 4)),
]


def shoot_previews(out_dir, *, body='', url=URL, timeout_s=180, settle_s=2.0, shots=PREVIEW_SHOTS):
    """Shoot every PREVIEW_SHOTS framing of the photoreal model in ONE page
    and write <out_dir>/<name>.png (centre-cropped to the shot's aspect).
    Returns {'files': {name: path}, 'errors': [...], 'info': {...}}."""
    from playwright.sync_api import sync_playwright
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    errs, files, info = [], {}, {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        w0, h0 = shots[0][4]
        ctx = browser.new_context(viewport={'width': w0, 'height': h0})
        ctx.add_init_script('try{localStorage.setItem("cs.photoreal", "1");}catch(e){}')
        if body:
            ctx.add_init_script('try{localStorage.setItem("cs.basebody", %s);}catch(e){}' % json.dumps(body))
        page = ctx.new_page()
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(url, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("charstudio")')
        page.wait_for_function('typeof CS3 !== "undefined" && CS3.model && !CS3.loading', timeout=timeout_s * 1000)
        page.wait_for_function(
            'window.CSPHOTOREAL && CSPHOTOREAL.isApplied && CSPHOTOREAL.isApplied()', timeout=timeout_s * 1000
        )
        # the groom is rebuilt after the skin lands (brows move into the skin); let it finish
        # char_hair.js parents the groom beside the body (model.parent || scene)
        page.wait_for_function(
            '() => !!(CS3.scene && CS3.scene.getObjectByName("cs-hair"))', timeout=90000, polling=500
        )
        page.add_style_tag(content='.cs-hint, #cs-credit, #cst-panel { display: none !important; }')
        info = page.evaluate("""() => ({ modelId: CS3.modelId, photoreal: !!CSPHOTOREAL.state.on,
              hair: !!CS3.scene.getObjectByName("cs-hair"),
              hairVerts: (function(){ var n=0; var g=CS3.scene.getObjectByName("cs-hair"); if(g) g.traverse(o=>{ if(o.isMesh) n+=o.geometry.attributes.position.count; }); return n; })() })""")
        for name, frame, az, el, (w, h), (aw, ah) in shots:
            page.set_viewport_size({'width': w, 'height': h})
            _frame(page, frame, az, el)
            _settle(page, settle_s)
            canvas = page.query_selector('#cs-3d canvas')
            tmp = os.path.join(out_dir, name + '.raw.png')
            (canvas or page).screenshot(path=tmp)
            im = Image.open(tmp).convert('RGB')
            W, H = im.size
            cw, ch = (W, int(W * ah / aw)) if W * ah <= H * aw else (int(H * aw / ah), H)
            x0, y0 = (W - cw) // 2, (H - ch) // 2
            dest = os.path.join(out_dir, name + '.png')
            im.crop((x0, y0, x0 + cw, y0 + ch)).save(dest)
            os.remove(tmp)
            files[name] = dest
        browser.close()
    return {'files': files, 'errors': errs, 'info': info}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    ap.add_argument('--photoreal', action='store_true')
    ap.add_argument('--clay', action='store_true', help='force the photoreal switch off')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--frame', default='body', choices=['body', 'head'])
    ap.add_argument('--az', type=float, default=0.0)
    ap.add_argument('--el', type=float, default=0.0)
    ap.add_argument('--body', default='')
    ap.add_argument('--panel', action='store_true', help='open the Photoreal panel and shoot the whole page')
    ap.add_argument(
        '--models', action='store_true', help='open the Models dropdown, hover the first derived model, shoot the page'
    )
    ap.add_argument('--width', type=int, default=1600)
    ap.add_argument('--height', type=int, default=1400)
    ap.add_argument('--url', default=URL)
    ap.add_argument(
        '--previews',
        default='',
        help='write the Models-card previews (head_front/body_front/head_tq PNGs) into this directory and exit',
    )
    a = ap.parse_args(argv)
    if a.previews:
        r = shoot_previews(a.previews, body=a.body, url=a.url)
        print(json.dumps(r, indent=1))
        return 1 if r['errors'] else 0
    r = shoot(
        a.out,
        photoreal=a.photoreal,
        compare=a.compare,
        frame=a.frame,
        az=a.az,
        el=a.el,
        body=a.body,
        width=a.width,
        height=a.height,
        url=a.url,
        panel=a.panel,
        clay=a.clay,
        models=a.models,
    )
    print(json.dumps(r, indent=1))
    return 1 if r['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
