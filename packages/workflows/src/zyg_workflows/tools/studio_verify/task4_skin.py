#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 4 — proof that Character Studio's swatches are now sRGB-correct.

Injects the same character the acceptance run used (the first of
/inspect/api/list), screenshots the studio at the operator's zoom, and samples a
40x40 px patch on the forehead and one on the back of a hand.  Then stages
identity.skin_tone='deep' and samples again.  Also tallies which rule of
char_dress.js's band() fires on the foot vertices.

Run:  ../.venv/bin/python tools/studio_verify/task4_skin.py
"""

import json
import os
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(CREWS, 'output', 'studio_verify')
URL = paths.ZYG_KANBAN_URL + '/inspection.html'
VW, VH = 2507, 1567

# ── in-page: where the forehead and the back of a hand land on the screenshot,
#    which band rule the feet take, and what the shader was actually handed ────
PROBE = r"""
(VWPX) => {
  const under = (o, n) => { for (let p = o; p; p = p.parent) if (p.name === n) return true;
                            return false; };
  let body = null, best = -1;
  CS3.model.traverse(o => {
    if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
    if (under(o, 'CS3_DRESS') || under(o, 'CS3_HAIR')) return;
    if (/eye[lr]$/i.test(o.name || '')) return;
    const c = o.geometry.attributes.position.count;
    if (c > best) { best = c; body = o; }
  });
  if (!body) return {err: 'no body mesh'};
  CS3.model.updateMatrixWorld(true);
  const pa = body.geometry.attributes.position, m = body.matrixWorld;
  const n = pa.count, v = new THREE.Vector3();
  const W = new Float32Array(n * 3);
  let minY = Infinity, maxY = -Infinity, minX = Infinity, maxX = -Infinity;
  for (let i = 0; i < n; i++) {
    v.set(pa.getX(i), pa.getY(i), pa.getZ(i)).applyMatrix4(m);
    W[i * 3] = v.x; W[i * 3 + 1] = v.y; W[i * 3 + 2] = v.z;
    if (v.y < minY) minY = v.y; if (v.y > maxY) maxY = v.y;
    if (v.x < minX) minX = v.x; if (v.x > maxX) maxX = v.x;
  }
  const H = maxY - minY, cx = (minX + maxX) / 2, yTop = maxY;
  const headH = 0.13 * H;

  // centroid of a predicate, and the vertex nearest it
  const pickCentroid = (test) => {
    let sx = 0, sy = 0, sz = 0, k = 0;
    for (let i = 0; i < n; i++) if (test(i)) { sx += W[i*3]; sy += W[i*3+1]; sz += W[i*3+2]; k++; }
    return k ? {x: sx/k, y: sy/k, z: sz/k, n: k} : null;
  };
  // forehead: the skin strip between the hairline cut (yTop-0.18*headH) and the
  // brow (yTop-0.42*headH), near the midline, on the forward face
  let zFwdSum = 0, zFwdN = 0;
  for (let i = 0; i < n; i++) if (W[i*3+1] > yTop - headH) { zFwdSum += W[i*3+2]; zFwdN++; }
  const zc = zFwdN ? zFwdSum / zFwdN : 0;
  let pos = 0, neg = 0;
  for (let i = 0; i < n; i++) {
    const y = W[i*3+1];
    if (y < yTop - 0.9*headH || y > yTop - 0.42*headH) continue;
    if (Math.abs(W[i*3] - cx) > 0.10 * (maxX - minX)) continue;
    const d = W[i*3+2] - zc;
    if (d > pos) pos = d; if (d < neg) neg = d;
  }
  const fwd = (pos >= -neg) ? 1 : -1;
  const forehead = pickCentroid(i => {
    const y = W[i*3+1];
    if (y < yTop - 0.40*headH || y > yTop - 0.20*headH) return false;
    if (Math.abs(W[i*3] - cx) > 0.035 * H) return false;
    return fwd * (W[i*3+2] - zc) > 0.02 * H;
  });
  // hand: the outermost cluster below the waist band that char_dress calls 'hand'
  const hand = pickCentroid(i => {
    const h = (W[i*3+1] - minY) / H;
    return h > 0.40 && h < 0.50 && (W[i*3] - cx) > 0.19 * H;
  });

  // project world -> screenshot device px (html{zoom:.67}, so scale by VWPX/innerWidth)
  const cv = CS3.renderer.domElement, rect = cv.getBoundingClientRect();
  const k = VWPX / window.innerWidth;
  const proj = (p) => {
    if (!p) return null;
    const q = new THREE.Vector3(p.x, p.y, p.z).project(CS3.camera);
    return [ (rect.left + (q.x*.5+.5)*rect.width) * k,
             (rect.top + (-q.y*.5+.5)*rect.height) * k ];
  };

  // which band() rule the foot vertices take, recomputed from char_dress's own
  // constants (H_SHOE .045, H_HAND .52, H_NECK .80, X_HAND .19)
  const foot = {neck: 0, hand: 0, bare_or_shoe: 0, total: 0};
  for (let i = 0; i < n; i++) {
    const h = (W[i*3+1] - minY) / H;
    if (h >= 0.045) continue;
    foot.total++;
    const x = W[i*3] - cx;
    if (h >= 0.80) foot.neck++;
    else if (h < 0.52 && Math.abs(x) > 0.19 * H) foot.hand++;
    else foot.bare_or_shoe++;
  }

  // what actually reached the vertex-colour attribute, at those same points
  const ca = body.geometry.attributes.color;
  const sample = (p) => {
    if (!p || !ca) return null;
    let bi = -1, bd = Infinity;
    for (let i = 0; i < n; i++) {
      const dx = W[i*3]-p.x, dy = W[i*3+1]-p.y, dz = W[i*3+2]-p.z;
      const d = dx*dx + dy*dy + dz*dz;
      if (d < bd) { bd = d; bi = i; }
    }
    const lin = [ca.getX(bi), ca.getY(bi), ca.getZ(bi)];
    const to8 = u => Math.round(255 * (u <= 0.0031308 ? u*12.92
                                     : 1.055*Math.pow(u, 1/2.4) - 0.055));
    return {linear: lin.map(u => +u.toFixed(4)), as_srgb_8bit: lin.map(to8)};
  };
  const footV = (() => {           // a foot vertex, for the shoe/skin question
    let bi = -1, bd = Infinity;
    for (let i = 0; i < n; i++) {
      const h = (W[i*3+1] - minY) / H;
      if (h >= 0.045) continue;
      const d = Math.abs(W[i*3] - cx);
      if (d < bd) { bd = d; bi = i; }
    }
    if (bi < 0 || !ca) return null;
    const lin = [ca.getX(bi), ca.getY(bi), ca.getZ(bi)];
    const to8 = u => Math.round(255 * (u <= 0.0031308 ? u*12.92
                                     : 1.055*Math.pow(u, 1/2.4) - 0.055));
    return {linear: lin.map(u => +u.toFixed(4)), as_srgb_8bit: lin.map(to8)};
  })();

  return {
    skin_tone: (typeof cstVal === 'function' ? cstVal('identity.skin_tone') : null),
    footwear: (typeof cstVal === 'function' ? cstVal('wardrobe.footwear') : null),
    colour_shoes: (typeof cstVal === 'function' ? cstVal('wardrobe.colour_shoes') : null),
    hair_color: (typeof cstVal === 'function' ? cstVal('identity.hair_color') : null),
    outputEncoding_is_sRGB: CS3.renderer.outputEncoding === THREE.sRGBEncoding,
    bodyH: +H.toFixed(4), fwd: fwd,
    foreheadPx: proj(forehead), handPx: proj(hand),
    foreheadVerts: forehead ? forehead.n : 0, handVerts: hand ? hand.n : 0,
    footBand: foot,
    vcol_forehead: sample(forehead), vcol_hand: sample(hand), vcol_foot: footV,
    bodyMatColor: body.material && body.material.color
      ? [body.material.color.r, body.material.color.g, body.material.color.b] : null,
    bodyMatVertexColors: !!(body.material && body.material.vertexColors)
  };
}
"""

CLAY_PROBE = r"""
() => {
  // the page's own clay is 0xb9b2a8; after the dress hook every non-body mesh
  // carries the skin swatch instead. Report what each non-hair mesh holds now.
  const under = (o, n) => { for (let p = o; p; p = p.parent) if (p.name === n) return true;
                            return false; };
  const out = [];
  CS3.model.traverse(o => {
    if (!o.isMesh || !o.material) return;
    if (under(o, 'CS3_DRESS') || under(o, 'CS3_HAIR')) return;
    out.push({name: o.name || '(unnamed)',
              verts: o.geometry.attributes.position.count,
              vertexColors: !!o.material.vertexColors,
              color: [+o.material.color.r.toFixed(4), +o.material.color.g.toFixed(4),
                      +o.material.color.b.toFixed(4)]});
  });
  return out.sort((a, b) => b.verts - a.verts).slice(0, 8);
}
"""


def patch(png, cx, cy, half=20):
    im = Image.open(png).convert('RGB')
    x0, y0 = max(0, int(cx - half)), max(0, int(cy - half))
    x1, y1 = min(im.width, int(cx + half)), min(im.height, int(cy + half))
    if x1 <= x0 or y1 <= y0:
        return None
    crop = im.crop((x0, y0, x1, y1))
    px = list(crop.getdata())
    n = len(px)
    mean = [round(sum(p[i] for p in px) / n, 2) for i in range(3)]
    # background of the 3D stage is a flat near-black/near-grey; count how much
    # of the patch is NOT body so the mean can be read honestly
    bg = sum(1 for p in px if max(p) < 40)
    return {'box': [x0, y0, x1, y1], 'mean_rgb': mean, 'n': n, 'dark_bg_frac': round(bg / n, 3)}


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
