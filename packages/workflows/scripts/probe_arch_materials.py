# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""probe_arch_materials.py — proof that a CC0 surface tiles at LIFE SIZE.

    venv/bin/python probe_arch_materials.py

"A texture appeared" is not the claim worth testing — that would pass just as
happily with the bricks stretched three times life size across a wall, which is
the failure this whole feature exists to avoid. So the assertions are on the
arithmetic that makes it right:

  * the albedo is sRGB and the data maps are LINEAR (getting this wrong washes
    the colour out and is easy to miss by eye),
  * texture.repeat is exactly 1/size_m,
  * UVs are in METRES — a 4 m wall's u range spans 4, not 1,
  * so tiles-across = wall length / material size, INDEPENDENTLY of the wall,
  * and two walls of different lengths agree on tile size at the joint, which
    is the thing a viewer actually notices.
"""

import json
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

URL = paths.ZYG_KANBAN_URL + '/inspection.html#architecture'

SCRIPT = """
async () => {
  if (typeof AR === 'undefined') return {err: 'AR missing'};
  if (!AR.scene) arEnsure();
  if (!AR.sections || !AR.sections.length) return {err: 'library not loaded'};

  const sec = AR.sections.find(s => s.key === 'materials');
  const item = sec && sec.groups.flatMap(g => g.items)
                       .find(i => i.kind.startsWith('acg_') && i.p.maps && i.p.maps.map);
  if (!item) return {err: 'no textured surface in the rail'};
  const sizeM = item.p.size_m;

  // Two walls of DIFFERENT lengths, same material. If tiling were the old
  // 0..1 mapping they would show the same tile count and disagree on scale.
  const mk = (len) => {
    const r = arNewObj('wall', {len, h: 2.7, t: 0.24}, 0, 0, 0);
    r.mat = item.kind; arApplyMat(r); arApplyUV(r);
    return r;
  };
  const a = mk(4.0), b = mk(9.0);

  const mat = arMat(item.kind);
  const t0 = Date.now();
  while (mat.map && !mat.map.image && Date.now() - t0 < 30000) {
    await new Promise(r => setTimeout(r, 100));
  }

  // u-range of the widest face on each wall, in metres.
  const uSpan = (rec) => {
    let lo = Infinity, hi = -Infinity;
    rec.node.traverse(o => {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes.uv) return;
      const uv = o.geometry.attributes.uv;
      for (let i = 0; i < uv.count; i++) {
        const u = uv.getX(i);
        if (u < lo) lo = u;
        if (u > hi) hi = u;
      }
    });
    return hi - lo;
  };

  const enc = (t) => t ? (t.encoding !== undefined ? t.encoding
                        : (t.colorSpace !== undefined ? t.colorSpace : null)) : null;

  return {
    kind: item.kind, size_m: sizeM, note: item.note,
    slots: ['map','normalMap','roughnessMap','metalnessMap','aoMap'].filter(s => !!mat[s]),
    loaded: !!(mat.map && mat.map.image),
    baseColorWhite: mat.color.getHexString() === 'ffffff',
    repeat: [+mat.map.repeat.x.toFixed(6), +mat.map.repeat.y.toFixed(6)],
    wants_repeat: [+(1/sizeM[0]).toFixed(6), +(1/sizeM[1]).toFixed(6)],
    albedo_srgb: enc(mat.map) === (THREE.sRGBEncoding !== undefined ? THREE.sRGBEncoding : 'srgb'),
    normal_linear: mat.normalMap ? enc(mat.normalMap) ===
        (THREE.LinearEncoding !== undefined ? THREE.LinearEncoding : 'srgb-linear') : null,
    uspan_4m: +uSpan(a).toFixed(3),
    uspan_9m: +uSpan(b).toFixed(3),
    tiles_4m: +(uSpan(a) / sizeM[0]).toFixed(3),
    tiles_9m: +(uSpan(b) / sizeM[0]).toFixed(3),
    has_uv2: !!(a.node.children[0] && a.node.children[0].geometry.attributes.uv2),
  };
}
"""


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page()
        page.on('pageerror', lambda e: print(f'  [pageerror] {e}', file=sys.stderr))
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function('typeof goToView === "function"', timeout=60000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.sections && AR.sections.length > 0', timeout=60000)
        r = page.evaluate(SCRIPT)
        browser.close()

    print(json.dumps(r, indent=1))
    if r.get('err'):
        print('FAIL: ' + r['err'])
        return 1

    sx = r['size_m'][0]
    checks = [
        ('albedo loaded', r['loaded']),
        ('base colour is white (map is not tinted)', r['baseColorWhite']),
        ('albedo is sRGB', r['albedo_srgb']),
        ('normal map is linear', r['normal_linear'] is not False),
        ('repeat == 1/size_m', r['repeat'] == r['wants_repeat']),
        ('uv2 exists for aoMap', r['has_uv2']),
        ('4 m wall spans 4 m of UV', abs(r['uspan_4m'] - 4.0) < 0.01),
        ('9 m wall spans 9 m of UV', abs(r['uspan_9m'] - 9.0) < 0.01),
        (
            'tile count scales with the wall',
            abs(r['tiles_4m'] - 4.0 / sx) < 0.01 and abs(r['tiles_9m'] - 9.0 / sx) < 0.01,
        ),
        # Compare each wall's implied tile size against the MATERIAL's size,
        # not against each other's rounded tile count — tiles_* is reported to
        # 3 dp, so 4/2.667 and 9/6 differ by 2e-4 for reporting reasons alone.
        (
            "both walls tile at the material's real size",
            abs(r['uspan_4m'] / r['tiles_4m'] - sx) < 0.01 and abs(r['uspan_9m'] / r['tiles_9m'] - sx) < 0.01,
        ),
    ]
    bad = 0
    for name, ok in checks:
        print(f'{"PASS" if ok else "FAIL"}  {name}')
        bad += not ok
    print(f'\n{len(checks) - bad}/{len(checks)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
