# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.task9_dress_check`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.studio_verify.task9_dress_check` still reaches it.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.task9_dress_check import OUT, URL, VH, VW, mean_rgb, probe_js


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
