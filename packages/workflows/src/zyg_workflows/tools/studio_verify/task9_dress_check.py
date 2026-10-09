#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 9 proof: studio_ext/char_dress.js on the Character Studio base body.

Headless chromium (swiftshader) at the operator's 67 % zoom viewport, two
states: the default base body, then one with skin_tone 'deep', a red top, a
hat, glasses and height 1.95 staged. Screenshots + the numbers the brief asks
for. No GPU, no model imports.
"""

import json
import os
import sys

from PIL import Image
from playwright.sync_api import sync_playwright
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(CREWS, 'output', 'studio_verify')
URL = paths.ZYG_KANBAN_URL + '/inspection.html'
VW, VH = 2507, 1567

PROBE = r"""
() => {
  const r = {};
  r.height = CS3.height;
  r.modelId = CS3.modelId;
  r.scale = [CS3.model.scale.x, CS3.model.scale.y, CS3.model.scale.z];
  r.dress = CS3.dress ? CS3.dress.children.length : -1;
  const b = window.CSDRESS.base();
  r.baseH = b.H; r.headW = b.headW; r.headH = b.headH; r.front = b.front;
  r.verts = b.n;
  r.bodyMat = { vertexColors: !!b.mesh.material.vertexColors,
                hasColorAttr: !!b.mesh.geometry.attributes.color };
  // world bbox of the BODY MESH only (the dress group is excluded on purpose)
  const bb = new THREE.Box3().setFromObject(b.mesh);
  r.worldH = bb.max.y - bb.min.y;
  r.worldFeet = bb.min.y;
  // projected height with a FIXED reference camera (same pose for both states,
  // so the number is the geometry, not the re-framing)
  const cam = new THREE.PerspectiveCamera(35, VWVH, 0.01, 60);
  cam.position.set(0, 0.85, 1.7 * 1.75);
  cam.lookAt(0, 0.85, 0);
  cam.updateMatrixWorld(true); cam.updateProjectionMatrix();
  const lo = new THREE.Vector3(0, bb.min.y, 0).project(cam);
  const hi = new THREE.Vector3(0, bb.max.y, 0).project(cam);
  r.projH = Math.abs(lo.y - hi.y) * 0.5 * VHPX;
  // where the torso lands on the PAGE, with the live camera
  const cv = CS3.renderer.domElement, rect = cv.getBoundingClientRect();
  const P = (x, y) => {
    const v = new THREE.Vector3(x, y, 0).project(CS3.camera);
    return [rect.left + (v.x * 0.5 + 0.5) * rect.width,
            rect.top + (-v.y * 0.5 + 0.5) * rect.height];
  };
  const h = CS3.height;
  const c = P(0, h * 0.62), e = P(h * 0.085, h * 0.62);
  // inspection.html sets html{zoom:.67}: getBoundingClientRect is in UNZOOMED
  // CSS px, the screenshot is in device px. One factor converts the two.
  const k = VWPX / window.innerWidth;   // = 0.67; devicePixelRatio says the same
  r.zoom = k;
  r.torso = { cx: c[0] * k, cy: c[1] * k, hw: Math.abs(e[0] - c[0]) * k };
  r.canvas = [rect.left * k, rect.top * k, rect.width * k, rect.height * k];
  return r;
}
"""


def probe_js():
    return PROBE.replace('VWVH', str(VW / VH)).replace('VHPX', str(VH)).replace('VWPX', str(VW))


def mean_rgb(png, cx, cy, hw, hh):
    im = Image.open(png).convert('RGB')
    x0, y0 = max(0, int(cx - hw)), max(0, int(cy - hh))
    x1, y1 = min(im.width, int(cx + hw)), min(im.height, int(cy + hh))
    px = list(im.crop((x0, y0, x1, y1)).tobytes())
    px = [tuple(px[i : i + 3]) for i in range(0, len(px), 3)]
    n = len(px)
    s = [0, 0, 0]
    for p in px:
        s[0] += p[0]
        s[1] += p[1]
        s[2] += p[2]
    return [round(v / n, 2) for v in s], (x0, y0, x1, y1)


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': VW, 'height': VH})
        errs = []
        pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
        pg.goto(URL, wait_until='load')
        pg.wait_for_function('typeof CS3!=="undefined" && typeof window.CSDRESS!=="undefined"', timeout=30000)
        pg.evaluate("() => switchView('charstudio')")
        pg.wait_for_function('!!CS3.model && !!CS3.dress !== undefined && !!CS3.modelId', timeout=30000)
        pg.wait_for_timeout(2500)

        a = pg.evaluate(probe_js())
        pa = os.path.join(OUT, 'task9_dress_default.png')
        pg.screenshot(path=pa)
        res['default'] = a

        pg.evaluate("""() => {
          CST.dirty['identity.skin_tone']  = 'deep';
          CST.dirty['wardrobe.colour_top'] = '#aa2222';
          CST.dirty['wardrobe.headwear']   = 'hat';
          CST.dirty['accessories.eyewear'] = 'glasses';
          CST.dirty['identity.height_m']   = '1.95';
          cs3dHooksRun('stage');
        }""")
        pg.wait_for_timeout(2000)
        b = pg.evaluate(probe_js())
        pb = os.path.join(OUT, 'task9_dress_staged.png')
        pg.screenshot(path=pb)
        res['staged'] = b

        # every enum branch, once: nothing may throw and the group must rebuild
        sweep = pg.evaluate("""() => {
          const hats = ['none','cap','flat cap','hat','wide-brim hat','hood','veil',
                        'helmet','headscarf','crown','beanie'];
          const specs = ['none','glasses','round glasses','sunglasses','monocle',
                         'goggles','pince-nez'];
          const outer = ['none','coat','cloak','jacket','armour','robe','waistcoat','shawl'];
          const cond  = ['clean','dusty','muddy','bloodied'];
          const shoes = ['shoes','bare feet'];
          const build = ['slender build','average build','athletic build',
                         'muscular build','heavy build'];
          const out = {headwear:{}, eyewear:{}, outerwear:{}, condition:{}, footwear:{}, build:{}};
          const set = (k, v) => { if (v === null) delete CST.dirty[k]; else CST.dirty[k] = v; };
          const one = (bucket, key, list) => {
            for (const v of list) {
              set(key, v);
              try { cs3dHooksRun('stage'); }
              catch (e) { out[bucket][v] = 'THREW ' + e; continue; }
              out[bucket][v] = (CS3.dress ? CS3.dress.children.length : -1);
            }
            set(key, null);
          };
          set('wardrobe.headwear', null); set('accessories.eyewear', null);
          one('headwear',  'wardrobe.headwear',   hats);
          one('eyewear',   'accessories.eyewear', specs);
          one('outerwear', 'wardrobe.outerwear',  outer);
          one('condition', 'wardrobe.condition',  cond);
          one('footwear',  'wardrobe.footwear',   shoes);
          one('build',     'identity.body_build', build);
          out.muscle = [];
          for (const mm of [1, 50, 75, 100]) {
            set('identity.muscle_mass', String(mm)); cs3dHooksRun('stage');
            out.muscle.push([mm, +CS3.model.scale.x.toFixed(5)]);
          }
          set('identity.muscle_mass', null);
          set('identity.height_m', null); cs3dHooksRun('stage');
          out.reverted = { height: CS3.height, dress: CS3.dress.children.length };
          return out;
        }""")
        res['sweep'] = sweep
        res['console_errors'] = errs[:20]
        br.close()

    ha = res['default']['torso']['hw']
    ma, ra = mean_rgb(pa, res['default']['torso']['cx'], res['default']['torso']['cy'], ha, ha)
    hb = res['staged']['torso']['hw']
    mb, rb = mean_rgb(pb, res['staged']['torso']['cx'], res['staged']['torso']['cy'], hb, hb)
    res['torso_mean_default'] = {'rgb': ma, 'box': ra}
    res['torso_mean_staged'] = {'rgb': mb, 'box': rb}
    res['torso_redness_default'] = round(ma[0] - (ma[1] + ma[2]) / 2, 2)
    res['torso_redness_staged'] = round(mb[0] - (mb[1] + mb[2]) / 2, 2)
    res['worldH_ratio'] = round(res['staged']['worldH'] / res['default']['worldH'], 5)
    res['projH_ratio'] = round(res['staged']['projH'] / res['default']['projH'], 5)
    print(json.dumps(res, indent=2))

    ok = True
    if res['torso_redness_staged'] <= res['torso_redness_default']:
        print('FAIL: torso did not move toward red')
        ok = False
    if abs(res['staged']['worldH'] - 1.95) > 0.02:
        print('FAIL: staged world height != 1.95')
        ok = False
    if res['staged']['dress'] < 4:
        print('FAIL: CS3.dress.children.length < 4')
        ok = False
    if res['default']['dress'] != 0:
        print('FAIL: default state should have an empty dress group')
        ok = False
    for p in (pa, pb):
        if not os.path.getsize(p):
            print('FAIL: empty', p)
            ok = False
    sw = res['sweep']
    for bucket, got in sw.items():
        if bucket in ('muscle', 'reverted') or not isinstance(got, dict):
            continue
        for k, v in got.items():
            if not isinstance(v, int):
                print('FAIL: %s=%s -> %s' % (bucket, k, v))
                ok = False
    for k, v in sw['headwear'].items():
        if k != 'none' and v < 1:
            print('FAIL: headwear %s drew nothing' % k)
            ok = False
    for k, v in sw['eyewear'].items():
        if k != 'none' and v < 1:
            print('FAIL: eyewear %s drew nothing' % k)
            ok = False
    if res['console_errors']:
        print('FAIL: console errors', res['console_errors'])
        ok = False
    if abs(sw['reverted']['height'] - res['default']['baseH']) > 1e-6:
        print("FAIL: clearing height_m did not go back to the body's own")
        ok = False
    if sw['muscle'][-1][1] <= sw['muscle'][0][1]:
        print('FAIL: muscle_mass did not widen the body')
        ok = False
    print('RESULT', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
