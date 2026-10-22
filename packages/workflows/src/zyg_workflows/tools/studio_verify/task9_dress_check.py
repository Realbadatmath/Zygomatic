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

import os

from PIL import Image
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


if __name__ == '__main__':  # the CLI lives in task9_dress_check_cli
    from zyg_workflows.tools.studio_verify.task9_dress_check_cli import main as _cli_main

    raise SystemExit(_cli_main())
