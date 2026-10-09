#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tools_arch_screenshot.py — the operator's eye on the Architecture Studio.

Blender renders tell you what the geometry IS; this tells you what the operator
SEES. It drives the live studio tab in headless Chrome (the same launch as
`arch_ext_harness.browser_kinds`), opens a saved drawing through the tab's own
`arOpen(pid)` — or injects a document dict — puts the camera at a named view,
waits two animation frames, and writes the WebGL canvas to a PNG.

    python tools_arch_screenshot.py --project heath-landscape-demo --view eye --out /tmp/x.png
    python tools_arch_screenshot.py --doc /tmp/drawing.json --view aerial --out /tmp/y.png

Views:
  eye     — walk height (1.7 m) above the ground at the drawing's SOUTH edge,
            looking north, 50 degree lens. The operator standing in it.
  aerial  — 45 degrees above the horizon in the south-west, whole lot in frame.
  iso / top / front / right / back / left  — the tab's own arView().

Studio frame: X east, Y up, Z south. The camera is the tab's camera, so the
picture is exactly what the browser draws — sky, sun, shadows, vertex colours
and all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

URL = os.environ.get('ARCH_STUDIO_URL', paths.ZYG_KANBAN_URL + '/inspection.html#architecture')
TAB_VIEWS = ('iso', 'top', 'front', 'right', 'back', 'left', 'bottom')
CAM_VIEWS = ('eye', 'aerial')
VIEWS = CAM_VIEWS + TAB_VIEWS

EYE_HEIGHT_M = 1.7
EYE_FOV_DEG = 50.0

# ── the camera, placed in the tab ────────────────────────────────────────────
_CAMERA_SCRIPT = r"""
(cfg) => {
  const box = new THREE.Box3();
  AR.objs.forEach(o => { if (o.node && !o.hidden) box.expandByObject(o.node); });
  if (box.isEmpty()) box.set(new THREE.Vector3(-5, 0, -5), new THREE.Vector3(5, 5, 5));
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  const span = Math.max(4, Math.max(s.x, s.y, s.z));
  const out = {view: cfg.view, objs: AR.objs.length, span: span, ortho: !!AR.ortho,
               min: [box.min.x, box.min.y, box.min.z], max: [box.max.x, box.max.y, box.max.z]};
  if (cfg.view === 'eye' || cfg.view === 'aerial') {
    /* both need a perspective camera; arOrthoToggle() flips it back and rebuilds AR.controls */
    if (AR.ortho && typeof arOrthoToggle === 'function') { try { arOrthoToggle(); } catch (e) {} }
    const cam = AR.cam;
    if (cfg.view === 'eye') {
      /* South is +Z in the studio frame. The ground height is sampled just INSIDE
         the south edge, but the camera stands just OUTSIDE it — placed inside, it
         ends up buried in the terrain slab and the frame is one flat cut face. */
      const probeZ = box.max.z - Math.min(3, span * 0.03);
      const eyeZ = box.max.z - Math.min(8, span * 0.05);   /* a few metres INSIDE the edge (outside, the ground's cut edge showed as a void) */
      /* 2026-09-07: the box can overhang the ground (tree crowns past its edge), so
         walk the probe INWARD (toward -Z, north) until something is hit; fall back to
         the base plane (0), never box.min.y — that stood the camera under a valley. */
      let groundY = 0, standIn = 0;
      const nodes = AR.objs.filter(o => o.node && !o.hidden).map(o => o.node);
      const maxIn = Math.max(4, span * 0.3);
      /* the top hit under the probe: ground -> stand 1.7 m on it; anything else (a
         wood, a building) -> the camera is INSIDE it, so stand on top of it instead
         (2026-09-07: half the gallery's eye shots were a hall of trunks) */
      const GROUND = /^(ground|terrain|hill|slope|plateau|berm|pad|beach|dune_field|island|mesa|mountain|mountain_range|valley|ridge|cliff|escarpment|scree|sculpt_)/;
      const kindOf = (obj) => { let n = obj; while (n) { const o = AR.objs.find(r => r.node === n); if (o) return o.kind; n = n.parent; } return ''; };
      for (let din = 0; din <= maxIn; din += 2) {
        const rc = new THREE.Raycaster(new THREE.Vector3(c.x, box.max.y + 50, probeZ - din),
                                       new THREE.Vector3(0, -1, 0));
        const hits = rc.intersectObjects(nodes, true);
        if (hits.length) {
          const k = kindOf(hits[0].object);
          groundY = hits[0].point.y; out.probe_in = din; out.probe_kind = k;
          standIn = GROUND.test(k) ? 0 : 1.5;        /* on a canopy: a little higher, to see over it */
          break;
        }
      }
      out.ground = groundY;
      const eyeY = groundY + cfg.eye_h + standIn;
      cam.position.set(c.x, eyeY, eyeZ);
      if (AR.controls) AR.controls.target.set(c.x, eyeY, box.min.z);
      if (cam.isPerspectiveCamera) { cam.fov = cfg.fov; cam.updateProjectionMatrix(); }
      out.cam = [c.x, eyeY, eyeZ];
    } else {
      /* 45 degrees up, from the south-west: west is -X, south is +Z */
      const k = Math.SQRT2;
      const v = new THREE.Vector3(-1, k, 1).normalize();
      const p = c.clone().add(v.multiplyScalar(span * 1.55));
      cam.position.copy(p);
      if (AR.controls) AR.controls.target.copy(c);
      if (cam.isPerspectiveCamera) { cam.fov = 45; cam.updateProjectionMatrix(); }
      out.cam = [p.x, p.y, p.z];
    }
    if (AR.controls) { AR.controls.maxPolarAngle = Math.PI * 0.999; AR.controls.update(); }
    cam.updateMatrixWorld(true);
  } else {
    arView(cfg.view);
    out.cam = [AR.cam.position.x, AR.cam.position.y, AR.cam.position.z];
  }
  return out;
}
"""

_TWO_FRAMES = r"""
() => new Promise(res => requestAnimationFrame(() => requestAnimationFrame(() => res(true))))
"""


def shoot(out_png, project='', doc=None, view='eye', width=1600, height=1000, url=URL, timeout_s=180, quiet=False):
    """Open the studio, place the camera, screenshot the canvas. Returns a dict
    with what the tab reported (object count, bounds, camera position, bytes)."""
    from playwright.sync_api import sync_playwright

    v = str(view or 'eye').lower()
    if v not in VIEWS:
        raise ValueError(f'view must be one of {", ".join(VIEWS)}')
    if not project and not doc:
        raise ValueError('pass a project id or a document to draw')
    out_png = os.path.abspath(out_png)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)

    errs: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': int(width), 'height': int(height)})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(url, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        page.evaluate('window.confirm = () => true; window.prompt = (q, d) => d || "1";')

        if project:
            page.evaluate('(pid) => arOpen(pid)', project)
            page.wait_for_function('AR.doc && AR.doc.id && AR.objs.length > 0', timeout=timeout_s * 1000)
        else:
            page.evaluate(
                r"""(doc) => {
                AR.objs.slice().forEach(arRemove); AR.objs = []; AR.sel = []; AR.undo = []; AR.redo = [];
                AR.doc = {id: doc.id || '', name: doc.name || 'injected'};
                if (typeof arSetCellM === 'function') arSetCellM(doc.cell_m);
                let max = 0;
                (doc.objects || []).forEach(o => {
                  const rec = {id: o.id || ('o' + (max + 1)), kind: o.kind, name: o.name || arKindLabel(o.kind),
                               p: o.p || {}, x: arNum(o.x, 0), y: arNum(o.y, 0), z: arNum(o.z, 0),
                               rx: arNum(o.rx, 0), ry: arNum(o.ry, 0), rz: arNum(o.rz, 0), s: arNum(o.s, 1),
                               mat: o.mat || 'mat_concrete', hidden: !!o.hidden, grp: o.grp || ''};
                  AR.objs.push(rec);
                  const n = parseInt(String(rec.id).replace('o', ''), 10); if (n > max) max = n;
                });
                AR.seq = max + 1;
                AR.objs.forEach(arRebuild);
                if (typeof arSyncHoles === 'function') arSyncHoles();
                arSelSync(); arHud();
            }""",
                doc,
            )

        info = page.evaluate(_CAMERA_SCRIPT, {'view': v, 'eye_h': EYE_HEIGHT_M, 'fov': EYE_FOV_DEG})
        page.evaluate(_TWO_FRAMES)
        page.evaluate(_TWO_FRAMES)
        canvas = page.query_selector('#ar-stage canvas')
        if canvas is None:
            browser.close()
            raise RuntimeError('the studio has no canvas — WebGL did not start (' + '; '.join(errs[:2]) + ')')
        canvas.screenshot(path=out_png)
        browser.close()

    info['path'] = out_png
    info['bytes'] = os.path.getsize(out_png) if os.path.exists(out_png) else 0
    if errs:
        info['page_errors'] = errs[:3]
    if not quiet:
        _zyg_log.info('ARCH_SHOT ' + json.dumps(info))
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--project', default='', help='saved drawing id, e.g. heath-landscape-demo')
    ap.add_argument('--doc', default='', help='path to a document JSON to inject instead')
    ap.add_argument('--view', default='eye', choices=list(VIEWS))
    ap.add_argument('--out', required=True, help='PNG to write')
    ap.add_argument('--width', type=int, default=1600)
    ap.add_argument('--height', type=int, default=1000)
    ap.add_argument('--url', default=URL)
    ap.add_argument('--timeout', type=int, default=180)
    a = ap.parse_args(argv)
    doc = None
    if a.doc:
        with open(a.doc, 'r', encoding='utf-8') as fh:
            doc = json.load(fh)
        doc = doc.get('doc') if isinstance(doc, dict) and 'doc' in doc else doc
    try:
        info = shoot(
            a.out,
            project=a.project,
            doc=doc,
            view=a.view,
            width=a.width,
            height=a.height,
            url=a.url,
            timeout_s=a.timeout,
        )
    except Exception as e:
        print('ARCH_SHOT_FAIL %s: %s' % (type(e).__name__, e))
        return 1
    return 0 if info.get('bytes', 0) > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
