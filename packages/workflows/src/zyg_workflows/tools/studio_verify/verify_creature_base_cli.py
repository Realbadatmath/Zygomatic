# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.verify_creature_base`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.verify_creature_base` still reaches it.
"""

import argparse
import base64
import json
import sys
import time

from zyg_workflows.tools.studio_verify.verify_creature_base import URL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('--fur', action='store_true')
    ap.add_argument('--shot', default='')
    ap.add_argument('--timeout', type=int, default=120)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            headless=True,
            args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
        )
        ctx = b.new_context(viewport={'width': 2507, 'height': 1567})
        ctx.add_init_script("try{localStorage.setItem('crst.basecreature',%s)}catch(e){}" % json.dumps(a.base))
        pg = ctx.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append('console.error: ' + m.text) if m.type == 'error' else None)
        pg.goto(URL, wait_until='load', timeout=60000)
        pg.wait_for_timeout(3500)
        if not pg.evaluate('CT.three'):
            pg.evaluate('ct3dToggle()')
        t0 = time.time()
        info = {}
        while time.time() - t0 < a.timeout:
            info = pg.evaluate("""() => { var X=window.CRST3X||{}; var m=X.model, n=0;
              if(m) m.traverse(function(o){ if(o.isMesh) n++; });
              var p=(X.parts||[])[0];
              return {url:X.url||'', clip:X.clip||'', meshes:n, label:X.label||'', fur:X.furShells||0,
                      hasMap: !!(p&&p.mesh.material.map), vc: p? !!p.mesh.material.vertexColors : false,
                      failed:(window.CRST3||{}).failed||false}; }""")
            if info.get('meshes') and info.get('clip'):
                break
            pg.wait_for_timeout(1500)
        # Deterministic: advance the clip's mixer ourselves instead of trusting
        # requestAnimationFrame to tick inside a wait (it does not, reliably, when
        # the GPU is busy or the window is throttled — a 2026-09-20 false failure).
        head = pg.evaluate("""() => { var h=null; if(!window.CRST3X||!CRST3X.model) return null;
            CRST3X.model.traverse(function(o){ if(!h && o.name==='Head') h=o; }); return h? h.quaternion.toArray() : null; }""")
        head2 = pg.evaluate("""() => { var X=window.CRST3X; if(!X||!X.model||!X.mixer) return null;
            var h=null; X.model.traverse(function(o){ if(!h && o.name==='Head') h=o; }); if(!h) return null;
            var best=null, q0=h.quaternion.toArray();
            for (var i=0;i<12;i++){ X.mixer.update(0.25); X.model.updateMatrixWorld(true); var q=h.quaternion.toArray();
              var d=0; for (var k=0;k<4;k++) d+=Math.abs(q[k]-q0[k]); if(best===null||d>best.d) best={d:d,q:q}; }
            return best.q; }""")
        info['head_moved'] = bool(head and head2 and head != head2)
        info['errors'] = errs[:5]
        if a.shot:
            d = pg.evaluate(
                "() => { CRST3.renderer.render(CRST3.scene, CRST3.camera); return CRST3.renderer.domElement.toDataURL('image/png'); }"
            )
            open(a.shot, 'wb').write(base64.b64decode(d.split(',', 1)[1]))
            info['shot'] = a.shot
        b.close()
    ok = (
        bool(info.get('meshes'))
        and info.get('clip') == 'Idle'
        and info.get('head_moved')
        and not info['errors']
        and '?v=' in info.get('url', '')
        and (not a.fur or info.get('fur', 0) > 0)
    )
    info['ok'] = ok
    print(json.dumps(info))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
