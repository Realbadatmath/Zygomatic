# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 2b proof — Creature Studio stands on a THIRD-PARTY base creature.

Headless WebGL through Playwright + SwiftShader at the operator's 67 % zoom
viewport (2507x1567). Four assertions, three screenshots:

  1. base    — with nothing injected the pane loads a base from BASES.json and
               the #crst-hint credit names Quaternius / Kenney / Smithsonian and
               never 'Pufferball'                     → task2b_creature_base.png
  2. picker  — the v_base tool opens the picker; choosing the SECOND base loads a
               different mesh (different vertex count) and pins it in
               localStorage 'crst.basecreature'      → task2b_creature_picker.png
  3. blue    — ctAdd('cc_base') + '#0044ff' makes the rendered pixels of the mesh
               blue-dominant (mean B > mean R and mean G, measured on the pixels
               that changed between the two frames)  → task2b_creature_blue.png
  4. own     — injecting d0e44ab002ad loads ITS mesh, and the emissive materials
               are reported: which were multiplied by the coat, which (eyes) were
               left alone.

Run:  ../.venv/bin/python tools/studio_verify/task2b_creature_base.py
"""

import json
import os

from PIL import Image
from playwright.sync_api import sync_playwright
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(CREWS, 'output', 'studio_verify')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#creatures'

PROBE = """() => {
  const X = window.CRST3X, m = X && X.model;
  if (!m) return {ready:false, why:'no model'};
  let meshes = 0, verts = 0;
  m.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position) {
      meshes++; verts += o.geometry.attributes.position.count; } });
  const h = document.getElementById('crst-hint');
  const lg = document.getElementById('crst-3dleg');
  return {ready: meshes > 0 && verts > 500, meshes, verts,
          url: X.url, label: X.label, axis: X.axis, clip: X.clip,
          mixer: !!X.mixer, hint: h ? h.textContent : '',
          legend: lg ? lg.textContent : '',
          empty: (document.getElementById('crst-empty')||{}).textContent || '',
          pin: window.localStorage.getItem('crst.basecreature') || '',
          three: !!CT.three, failed: CRST3.failed || ''};
}"""

EMIS = """() => {
  const X = window.CRST3X, out = [];
  (X.parts||[]).forEach(p => {
    const e = p.mesh.material.emissive, o = p.emis;
    if (!o) return;
    const live = (e.r+e.g+e.b) > 0.0001, was = (o.r+o.g+o.b) > 0.0001;
    if (!live && !was) return;
    out.push({name: p.mesh.material.name || p.mesh.name || '(unnamed)',
              eye: !!p.eye, map: !!p.map,
              orig: [+o.r.toFixed(3), +o.g.toFixed(3), +o.b.toFixed(3)],
              now:  [+e.r.toFixed(3), +e.g.toFixed(3), +e.b.toFixed(3)]});
  });
  return {mats: out, tinted: X.tinted || [], excluded: X.excluded || []};
}"""


def canvas_box(pg):
    b = pg.evaluate("""() => { const h = document.getElementById('crst-3d');
        const r = h.getBoundingClientRect();
        return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
    return (int(b['x']), int(b['y']), int(b['x'] + b['w']), int(b['y'] + b['h']))


def shoot_crop(pg, path, box):
    pg.screenshot(path=path)
    return Image.open(path).convert('RGB').crop(box)


def mean_changed(before, after, thr=12):
    """Mean RGB of `after` over the pixels that changed — i.e. the mesh."""
    a, b = before.tobytes(), after.tobytes()
    n = len(b) // 3
    r = g = bl = 0
    hit = 0
    for i in range(n):
        j = i * 3
        if abs(b[j] - a[j]) > thr or abs(b[j + 1] - a[j + 1]) > thr or abs(b[j + 2] - a[j + 2]) > thr:
            r += b[j]
            g += b[j + 1]
            bl += b[j + 2]
            hit += 1
    if not hit:
        return None
    return {'r': round(r / hit, 2), 'g': round(g / hit, 2), 'b': round(bl / hit, 2), 'px': hit, 'of': n}


def main():
    os.makedirs(OUT, exist_ok=True)
    errs = []
    res = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': 2507, 'height': 1567})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append('console.' + m.type + ': ' + m.text) if m.type == 'error' else None)
        pg.goto(URL, wait_until='load', timeout=90000)
        pg.evaluate("() => { try { localStorage.removeItem('crst.basecreature'); } catch(e){} }")
        pg.reload(wait_until='load', timeout=90000)

        # ── 1. the default base ──────────────────────────────────────────
        st = None
        for _ in range(60):
            st = pg.evaluate(PROBE)
            if st.get('ready'):
                break
            pg.wait_for_timeout(500)
        print('BASE     ', json.dumps(st))
        if not (st and st.get('ready')):
            raise RuntimeError(f'no base mesh after 30 s: {st}')
        hint = st['hint']
        if not any(w in hint for w in ('Quaternius', 'Kenney', 'Smithsonian')):
            raise RuntimeError(f'credit names no third-party pack: {hint!r}')
        if not ('Pufferball' not in hint and 'pufferball' not in st['url']):
            raise RuntimeError(f'the pufferball is still the base: {hint!r} {st["url"]!r}')
        if 'Base creature' not in st['empty']:
            raise RuntimeError(f'empty hint changed: {st["empty"]!r}')
        p1 = os.path.join(OUT, 'task2b_creature_base.png')
        pg.screenshot(path=p1)
        print('shot     ', p1, os.path.getsize(p1), 'bytes')
        res['base'] = st

        # ── 2. the picker, and the SECOND base ───────────────────────────
        pg.click('.crst-tool[data-ct="v_base"]')
        pg.wait_for_timeout(600)
        panel = pg.evaluate("""() => {
          const el = document.getElementById('crst-panel');
          const cards = document.querySelectorAll('#crst-panel-bd [data-base]');
          const ids = []; cards.forEach(c => ids.push(c.getAttribute('data-base')));
          return {on: el.classList.contains('on'),
                  title: (document.getElementById('crst-panel-title')||{}).textContent,
                  cards: ids.length, first: ids.slice(0,3),
                  imgs: document.querySelectorAll('#crst-panel-bd img').length};
        }""")
        print('PICKER   ', json.dumps(panel))
        if not (panel['on'] and panel['cards'] > 1):
            raise RuntimeError(f'picker did not open: {panel}')
        second = panel['first'][1]
        pg.click('#crst-panel-bd [data-base="%s"] button' % second)
        after = None
        for _ in range(60):
            after = pg.evaluate(PROBE)
            if after.get('ready') and after['pin'] == second and after['verts'] != st['verts']:
                break
            pg.wait_for_timeout(500)
        print('SECOND   ', json.dumps(after))
        if after['pin'] != second:
            raise RuntimeError(f'pin not written: {after}')
        if after['verts'] == st['verts']:
            raise RuntimeError(f'mesh did not change: {st["verts"]} -> {after["verts"]}')
        p2 = os.path.join(OUT, 'task2b_creature_picker.png')
        pg.screenshot(path=p2)
        print('shot     ', p2, os.path.getsize(p2), 'bytes')
        res['picker'] = {'panel': panel, 'second': second, 'after': after}

        # ── 3. cc_base #0044ff → the rendered mesh goes blue ─────────────
        # freeze the idle clip so the only pixels that move are the coat
        pg.evaluate('() => { if (CRST3X.mixer) CRST3X.mixer.timeScale = 0; }')
        pg.evaluate('() => { ctPanelClose && ctPanelClose(); }')
        pg.wait_for_timeout(900)
        box = canvas_box(pg)
        pre = shoot_crop(pg, os.path.join(OUT, '_task2b_pre.png'), box)
        pg.evaluate("() => { ctClear(); ctAdd('cc_base'); ctSet(0,'col','#0044ff',false); }")
        pg.wait_for_timeout(1500)
        p3 = os.path.join(OUT, 'task2b_creature_blue.png')
        post = shoot_crop(pg, p3, box)
        mb = mean_changed(pre, post)
        print('BLUE     ', json.dumps({'box': list(box), 'mean_changed': mb}))
        if not mb:
            raise RuntimeError('no pixel changed when the coat went blue')
        if not (mb['b'] > mb['r'] and mb['b'] > mb['g']):
            raise RuntimeError(f'not blue-dominant: {mb}')
        print('shot     ', p3, os.path.getsize(p3), 'bytes')
        res['blue'] = {'box': list(box), 'mean_changed': mb}

        # ── 4. the creature's OWN mesh, and its emissives ────────────────
        pg.evaluate("""async () => {
          const r = await fetch('/inspect/api/creatures', {cache:'no-store'});
          const d = await r.json();
          const list = d.creatures || d.items || d.rows || [];
          const c = list.find(x => x.id === 'd0e44ab002ad');
          if (!c) throw new Error('d0e44ab002ad not in /inspect/api/creatures');
          crstLoadCreature(c);
        }""")
        own = None
        for _ in range(90):
            own = pg.evaluate("""() => ({
              glb: (CT.facts && CT.facts.mesh && CT.facts.mesh.glb_url) || '',
              url: window.CRST3X.url, label: window.CRST3X.label,
              axis: window.CRST3X.axis, clip: window.CRST3X.clip,
              hint: (document.getElementById('crst-hint')||{}).textContent || '',
              verts: (() => { let v=0; const m=window.CRST3X.model;
                        if(m) m.traverse(o=>{ if(o.isMesh&&o.geometry) v+=o.geometry.attributes.position.count; });
                        return v; })()})""")
            if own['glb'] and own['url'] == own['glb']:
                break
            pg.wait_for_timeout(500)
        print('OWN      ', json.dumps(own))
        if not own['glb']:
            raise RuntimeError('creature d0e44ab002ad has no mesh.glb_url')
        if own['url'] != own['glb']:
            raise RuntimeError(f'3D did not switch to the own mesh: {own}')
        if 'Own mesh' not in own['hint']:
            raise RuntimeError(f'credit line not the own mesh: {own["hint"]!r}')
        pg.evaluate("() => { ctClear(); ctAdd('cc_base'); ctSet(0,'col','#0044ff',false); }")
        pg.wait_for_timeout(1500)
        em = pg.evaluate(EMIS)
        print('EMISSIVE ', json.dumps(em))
        p4 = os.path.join(OUT, 'task2b_creature_own.png')
        pg.screenshot(path=p4)
        print('shot     ', p4, os.path.getsize(p4), 'bytes')
        res['own'] = {'mesh': own, 'emissive': em}

        br.close()

    print('PAGE ERRORS', json.dumps(errs[:12]))
    res['page_errors'] = errs
    with open(os.path.join(OUT, 'task2b_creature_base.json'), 'w', encoding='utf-8') as fh:
        json.dump(res, fh, indent=1)
    print('ALL ASSERTIONS PASSED')


if __name__ == '__main__':
    main()
