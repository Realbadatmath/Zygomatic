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

import os

from PIL import Image
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


if __name__ == '__main__':  # the CLI lives in task2b_creature_base_cli
    from zyg_workflows.tools.studio_verify.task2b_creature_base_cli import main as _cli_main

    raise SystemExit(_cli_main())
