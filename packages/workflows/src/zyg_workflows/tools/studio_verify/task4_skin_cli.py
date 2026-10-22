# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.task4_skin`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.studio_verify.task4_skin` still reaches it.
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.task4_skin import CLAY_PROBE, OUT, PROBE, URL, VH, VW, patch


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {'when': time.strftime('%Y-%m-%d %H:%M:%S'), 'viewport': [VW, VH]}
    errs = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': VW, 'height': VH})
        pg.on('console', lambda m: errs.append('console.error: ' + m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        pg.goto(URL, wait_until='load', timeout=120000)
        pg.wait_for_function('typeof CS_TOOLS !== "undefined"', timeout=60000)
        pg.evaluate("() => { location.hash='charstudio'; switchView('charstudio'); }")
        pg.wait_for_function('!!(window.CS3 && CS3.model && CS3.hair)', timeout=120000)
        pg.wait_for_timeout(2500)

        inj = pg.evaluate("""async () => {
          const r = await fetch('/inspect/api/list', {cache: 'no-store'});
          const d = await r.json();
          const s = (d.sheets || [])[0];
          if (!s) throw new Error('/inspect/api/list has no sheets');
          if (window.STATE && Array.isArray(STATE.list) && !STATE.list.length)
            STATE.list = d.sheets;
          csLoadChar(s);
          return {id: s.id, name: s.name, total: (d.sheets || []).length};
        }""")
        res['injected'] = inj
        pg.wait_for_function('() => !!(window.CS && CS.charId)', timeout=60000)
        pg.wait_for_timeout(3500)

        shot = os.path.join(OUT, 'task4b_skin_after.png')
        pg.screenshot(path=shot)
        a = pg.evaluate(PROBE, VW)
        res['after'] = a
        res['clay'] = pg.evaluate(CLAY_PROBE)
        if a.get('foreheadPx'):
            res['after']['forehead_patch'] = patch(shot, *a['foreheadPx'])
        if a.get('handPx'):
            res['after']['hand_patch'] = patch(shot, *a['handPx'])

        # ── stage skin_tone = 'deep' ─────────────────────────────────────────
        pg.evaluate("""() => { CST.dirty['identity.skin_tone'] = 'deep';
                               cs3dHooksRun('stage'); }""")
        pg.wait_for_timeout(2500)
        shot2 = os.path.join(OUT, 'task4b_skin_deep.png')
        pg.screenshot(path=shot2)
        d = pg.evaluate(PROBE, VW)
        res['deep'] = d
        if d.get('foreheadPx'):
            res['deep']['forehead_patch'] = patch(shot2, *d['foreheadPx'])
        if d.get('handPx'):
            res['deep']['hand_patch'] = patch(shot2, *d['handPx'])

        pg.evaluate('() => { try { cstRevertAll(); } catch (e) {} }')
        res['console_errors'] = errs[:20]
        br.close()

    with open(os.path.join(OUT, 'task4b_skin.json'), 'w') as f:
        json.dump(res, f, indent=2)

    def line(tag, s):
        fp = s.get('forehead_patch') or {}
        hp = s.get('hand_patch') or {}
        print(
            '%-6s skin_tone=%-8r forehead 40x40 mean=%s (bg %.0f%%)  hand 40x40 mean=%s (bg %.0f%%)'
            % (
                tag,
                s.get('skin_tone'),
                fp.get('mean_rgb'),
                100 * fp.get('dark_bg_frac', 0),
                hp.get('mean_rgb'),
                100 * hp.get('dark_bg_frac', 0),
            )
        )
        print(
            '       vertex colour forehead linear=%s -> sRGB8 %s'
            % (s['vcol_forehead']['linear'], s['vcol_forehead']['as_srgb_8bit'])
            if s.get('vcol_forehead')
            else '       (no vertex colour)'
        )

    print('\ninjected: %s (%s) of %d' % (inj['name'], inj['id'], inj['total']))
    print('outputEncoding is sRGBEncoding: %s' % res['after']['outputEncoding_is_sRGB'])
    line('AFTER', res['after'])
    line('DEEP', res['deep'])
    print(
        '\nfootwear=%r colour_shoes=%r  foot band tally=%s'
        % (res['after']['footwear'], res['after']['colour_shoes'], res['after']['footBand'])
    )
    print('foot vertex colour: %s' % res['after']['vcol_foot'])
    print(
        'body material: vertexColors=%s color=%s' % (res['after']['bodyMatVertexColors'], res['after']['bodyMatColor'])
    )
    print('non-hair meshes: %s' % json.dumps(res['clay']))
    print('console errors: %d %s' % (len(errs), errs[:3]))
    print('wrote ' + shot)
    return 0


if __name__ == '__main__':
    sys.exit(main())
