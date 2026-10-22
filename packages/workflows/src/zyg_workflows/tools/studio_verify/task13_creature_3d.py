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

import os

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


if __name__ == '__main__':  # the CLI lives in task13_creature_3d_cli
    from zyg_workflows.tools.studio_verify.task13_creature_3d_cli import main as _cli_main

    raise SystemExit(_cli_main())
