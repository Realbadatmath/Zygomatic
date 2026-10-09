# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_arch_assets.py — end-to-end proof that the Studio can place a pack asset.

    PLAYWRIGHT_BROWSERS_PATH=  venv/bin/python test_arch_assets.py

Drives the REAL page against the running :8899 server and asserts on the scene
graph, not on pixels.

Deliberately NOT a screenshot test. Per the studio's own testing notes the
headless renderer on this box only ever gets SwiftShader and --screenshot may
composite the WebGL canvas as black, so a picture proves nothing. What is
asserted here is the thing that actually has to work: the loader fetches the
glTF, the scene graph gains real meshes, and the placeholder is gone.

Uses the SYSTEM Chrome (channel='chrome'): the pinned playwright chromium for
this version is not in ~/.cache/ms-playwright and downloading a second browser
to test a page the box can already render is not worth the disk.

One case per pack SHAPE, because the shapes fail differently: a single-file
.glb, and a .gltf whose .bin and textures are separate files the browser
resolves relative to the document URL — which is the whole reason the asset
route is path-based rather than a query string.
"""

import json
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

URL = paths.ZYG_KANBAN_URL + '/inspection.html#architecture'

# One item from each pack SHAPE: a single-file GLB, and a .gltf whose buffer
# and textures are separate files resolved relative to the document URL.
CASES = [
    ('kenney/building-kit', 'wall-half'),
    ('polyhaven_arch', 'ArmChair_01_2k'),
    ('quaternius/medieval_village_megakit', None),  # first item in the pack
]

SCRIPT = """
async ([pack, item]) => {
  if (typeof AR === 'undefined') return {err: 'AR missing'};
  if (!window.THREE || !THREE.GLTFLoader) return {err: 'GLTFLoader missing'};
  if (!AR.scene) { arEnsure(); }
  if (!AR.sections || !AR.sections.length) return {err: 'library not loaded'};

  const sec = AR.sections.find(s => s.key === 'assets');
  if (!sec) return {err: 'no assets section'};
  const grp = sec.groups.find(g => g.pack === pack);
  if (!grp) return {err: 'pack not in rail: ' + pack};
  const it = item ? grp.items.find(i => i.p.item === item) : grp.items[0];
  if (!it) return {err: 'item not in pack: ' + item};

  const rec = arNewObj('asset', it.p, 0, 0, 0);
  const t0 = Date.now();
  while (!rec.assetOk && !rec.assetErr && Date.now() - t0 < 30000) {
    await new Promise(r => setTimeout(r, 100));
  }
  let meshes = 0, tris = 0, textured = 0, placeholders = 0;
  const box = new THREE.Box3();
  rec.node.traverse(o => {
    if (o.userData && o.userData.arPlaceholder) placeholders++;
    if (o.isMesh) {
      meshes++;
      const g = o.geometry;
      if (g) {
        tris += (g.index ? g.index.count : (g.attributes.position||{count:0}).count) / 3;
        if (!o.userData.arPlaceholder) box.expandByObject(o);
      }
      if (o.material && o.material.map) textured++;
    }
  });
  const s = new THREE.Vector3(); if (!box.isEmpty()) box.getSize(s);
  return {
    item: it.id, url: it.u, ok: !!rec.assetOk, err: rec.assetErr || null,
    ms: Date.now() - t0, meshes, tris: Math.round(tris), textured, placeholders,
    size_m: [+s.x.toFixed(3), +s.y.toFixed(3), +s.z.toFixed(3)],
    name: rec.name,
  };
}
"""


def main():
    out, failures = [], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel='chrome',
            args=[
                '--enable-unsafe-swiftshader',  # no GPU reachable headless on this box
                '--disable-gpu-sandbox',
            ],
        )
        page = browser.new_page()
        page.on('pageerror', lambda e: print(f'  [pageerror] {e}', file=sys.stderr))
        # The engine asks before discarding unsaved work and headless hangs on
        # a modal, so answer every dialog before it can block.
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        # The tab loads its library only when it is ENTERED; a hash alone does
        # not run the router in this SPA.
        page.wait_for_function('typeof goToView === "function"', timeout=60000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.sections && AR.sections.length > 0', timeout=60000)
        for pack, item in CASES:
            try:
                r = page.evaluate(SCRIPT, [pack, item])
            except Exception as e:
                r = {'err': f'{type(e).__name__}: {e}'}
            r['pack'] = pack
            out.append(r)
            bad = r.get('err') or not r.get('ok') or r.get('meshes', 0) < 1 or r.get('placeholders', 1) != 0
            failures += bool(bad)
            mark = 'FAIL' if bad else 'PASS'
            print(f'{mark}  {pack:<38} {json.dumps(r)}')
        browser.close()
    print(f'\n{len(out) - failures}/{len(out)} passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
