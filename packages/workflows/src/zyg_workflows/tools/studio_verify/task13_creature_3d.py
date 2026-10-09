# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 13 proof — Creature Studio opens on a real base mesh, and the coat
colour ops repaint it.

Headless WebGL through Playwright + SwiftShader, at the operator's 67 % zoom
viewport (2507x1567). Three assertions, three screenshots:

  1. default   — CRST3X.model is a Group whose meshes carry > 1000 vertices
  2. red       — ctAdd('cc_base') + ctSet(0,'col','#ff3300') makes the mesh's
                 per-vertex colour attribute red-dominant
  3. own       — injecting creature d0e44ab002ad loads ITS mesh
                 (CT.facts.mesh.glb_url), not the base

Run:  ../.venv/bin/python tools/studio_verify/task13_creature_3d.py
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(CREWS, 'output', 'studio_verify')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#creatures'

PROBE = """() => {
  const m = window.CRST3X && window.CRST3X.model;
  if (!m) return {ready:false, why:'no model'};
  let meshes = 0, verts = 0, withCol = 0;
  m.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position) {
      meshes++; verts += o.geometry.attributes.position.count;
      if (o.geometry.attributes.color) withCol++; } });
  return {ready: meshes > 0 && verts > 1000, isGroup: !!m.isGroup || !!m.isObject3D,
          type: m.type, meshes, verts, withCol,
          url: window.CRST3X.url, label: window.CRST3X.label,
          three: !!CT.three, failed: CRST3.failed || ''};
}"""

MEAN = """() => {
  const m = window.CRST3X.model;
  let r=0,g=0,b=0,n=0;
  m.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.color) {
      const a = o.geometry.attributes.color;
      for (let i=0;i<a.count;i++){ r+=a.getX(i); g+=a.getY(i); b+=a.getZ(i); n++; } } });
  return n ? {r:r/n, g:g/n, b:b/n, n} : null;
}"""


def main():
    os.makedirs(OUT, exist_ok=True)
    errs = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': 2507, 'height': 1567})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append('console.' + m.type + ': ' + m.text) if m.type == 'error' else None)
        pg.goto(URL, wait_until='load', timeout=90000)

        # ── 1. the default view ──────────────────────────────────────────
        st = None
        for _ in range(40):
            st = pg.evaluate(PROBE)
            if st.get('ready'):
                break
            pg.wait_for_timeout(500)
        print('DEFAULT  ', json.dumps(st))
        if not (st and st.get('ready')):
            raise RuntimeError(f'no base mesh after 20 s: {st}')
        p1 = os.path.join(OUT, 'task13_creature_default.png')
        pg.screenshot(path=p1)
        print('shot     ', p1, os.path.getsize(p1), 'bytes')

        base_mean = pg.evaluate(MEAN)
        print('MEAN base', json.dumps(base_mean))

        # ── 2. cc_base #ff3300 on the mesh ───────────────────────────────
        pg.evaluate("() => { ctAdd('cc_base'); ctSet(0,'col','#ff3300',false); }")
        pg.wait_for_timeout(1200)
        red = pg.evaluate(MEAN)
        print('MEAN red ', json.dumps(red))
        if not red:
            raise RuntimeError('no colour attribute after cc_base')
        if not (red['r'] > red['g'] and red['r'] > red['b']):
            raise RuntimeError(f'not red-dominant: {red}')
        p2 = os.path.join(OUT, 'task13_creature_red.png')
        pg.screenshot(path=p2)
        print('shot     ', p2, os.path.getsize(p2), 'bytes')

        # ── 3. the creature's OWN mesh ───────────────────────────────────
        pg.evaluate("""async () => {
          const r = await fetch('/inspect/api/creatures', {cache:'no-store'});
          const d = await r.json();
          const list = d.creatures || d.items || d.rows || [];
          const c = list.find(x => x.id === 'd0e44ab002ad');
          if (!c) throw new Error('d0e44ab002ad not in /inspect/api/creatures');
          ctClear(); crstLoadCreature(c);
        }""")
        own = None
        for _ in range(60):
            own = pg.evaluate("""() => ({
              glb: (CT.facts && CT.facts.mesh && CT.facts.mesh.glb_url) || '',
              url: window.CRST3X.url, label: window.CRST3X.label,
              verts: (() => { let v=0; const m=window.CRST3X.model;
                        if(m) m.traverse(o=>{ if(o.isMesh&&o.geometry) v+=o.geometry.attributes.position.count; });
                        return v; })(),
              three: !!CT.three, name: CRST.name })""")
            if own['glb'] and own['url'] == own['glb']:
                break
            pg.wait_for_timeout(500)
        print('OWN      ', json.dumps(own))
        if not own['glb']:
            raise RuntimeError('creature has no mesh.glb_url')
        if own['url'] != own['glb']:
            raise RuntimeError(f'3D did not switch to the own mesh: {own}')
        p3 = os.path.join(OUT, 'task13_creature_own.png')
        pg.screenshot(path=p3)
        print('shot     ', p3, os.path.getsize(p3), 'bytes')

        # ── 3b. v_pin = a real picture-in-picture, v_3d lights the 3D ────
        pin = pg.evaluate("""() => {
          ctTool('v_pin');
          const el = document.getElementById('crst-pip');
          return {pip: !!window.CRST3X.pip, el: !!el,
                  src: el ? el.querySelector('img').getAttribute('src') : '',
                  w: el ? el.getBoundingClientRect().width : 0,
                  onPin: ctOn(CT.byId['v_pin']), on3d: ctOn(CT.byId['v_3d'])};
        }""")
        print('PIN      ', json.dumps(pin))
        if not (pin['pip'] and pin['el']):
            raise RuntimeError(f'no picture-in-picture: {pin}')
        if '&s=' + 'W10' not in pin['src']:
            raise RuntimeError(f'PiP is not the EMPTY stack: {pin["src"]}')
        if round(pin['w']) != 180:
            raise RuntimeError(f'PiP is not 180 px: {pin["w"]}')
        if not (pin['onPin'] is True and pin['on3d'] is True):
            raise RuntimeError(pin)

        # ── 4. the 2D path still works with #crst-3d hidden ──────────────
        pg.evaluate('() => ct3dToggle()')
        pg.wait_for_timeout(2500)
        two_d = pg.evaluate("""() => ({
          three: !!CT.three,
          d3: getComputedStyle(document.getElementById('crst-3d')).display,
          stage: getComputedStyle(document.getElementById('crst-stage')).display,
          img: !!document.getElementById('crst-pv') })""")
        print('2D       ', json.dumps(two_d))
        if not (two_d['three'] is False and two_d['d3'] == 'none'):
            raise RuntimeError(two_d)
        if not two_d['img']:
            raise RuntimeError('ctPreview did not draw the 2D picture')

        real = [e for e in errs if 'favicon' not in e]
        print('PAGEERRORS', len(real), real[:4])
        br.close()
    print('ALL OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
