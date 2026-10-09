# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  the original top import block — the siblings re-import from here

"""Movement Studio anatomy proof — the page probes and the two small helpers.

The original import block, the shot paths and timeouts, the nine JavaScript
probe sources, and ``_require`` / ``wait_for`` / ``side_of``.
"""

import json
import os
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

HERE = str(paths.PKG_DIR / 'tools' / 'studio_verify')
SHOT = os.path.join(HERE, 'movement_anatomy.png')
SHOT_HAND = os.path.join(HERE, 'movement_anatomy_hand.png')
SHOT_MUSCLE = os.path.join(HERE, 'movement_anatomy_muscle.png')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#movementstudio'
READY_TIMEOUT_MS = 240_000
EC_TIMEOUT_MS = 90_000  # 8 MB of JPEG atlas over the arch-asset route
RIG_CHANNELS = 31
SIDE_L, SIDE_R, SIDE_AXIS = 0, 1, 3
SKEL_PIECES = 135

PROBE = """() => {
  const M = window.MVR, A = window.MVA;
  if (!M) return {ready:false, why:'no MVR'};
  if (!A) return {ready:false, why:'no MVA — the anatomy file did not load'};
  const at = A.atlas;
  return {
    ready: !!M.loaded && !!A.ready,
    why: A.note || M.error || '',
    actor: M.actor || '',
    base: (M.meta && M.meta.base_body_id) || '',
    meta: (M.meta && M.meta.skeleton) || null,
    rig: (M.skeleton && M.skeleton.bones) ? M.skeleton.bones.length : 0,
    counts: A.counts,
    on: A.on,
    body: A.body,
    split: A.split, splitSide: A.splitSide,
    skin: A.skin,
    ms: A.ms || 0,
    vert: at ? at.vert : 0,
    stature: at ? +at.stature.toFixed(4) : 0,
    ankleIn: at ? at.ankleIn : null,
    hand: at && at.hand[0] ? {len:+at.hand[0].len.toFixed(4),
                              width:+at.hand[0].width.toFixed(4),
                              thick:+at.hand[0].thick.toFixed(4)} : null,
    foot: at && at.foot[0] ? {len:+at.foot[0].len.toFixed(4),
                              width:+at.foot[0].width.toFixed(4)} : null,
    torso: at && at.torso ? at.torso.filter(b=>b).length : 0
  };
}"""

# the écorché has landed AND its atlas has decoded
EC_READY = """() => {
  const A = window.MVA;
  if (!A) return {on:false, why:'no MVA'};
  if (!A.ec) return {on:false, why:A.ecNote || 'no MVA.ec yet'};
  const m = A.ec.material;
  return {on: !!(m && m.map && m.map.image && m.map.image.width),
          why: A.ecNote || 'atlas still decoding'};
}"""

# the skeleton mesh, the skin mesh, and whether they are the same rig
SKEL = """() => {
  const A = window.MVA, M = window.MVR;
  const sk = A.skel;
  if (!sk) return {found:false, note:A.note || ''};
  let skin = null;
  M.inner.traverse(o => {
    if (!skin && o.isSkinnedMesh && !(o.userData && o.userData.mvaLayer)) skin = o;
  });
  const sb = sk.skeleton ? sk.skeleton.bones : [];
  const kb = (skin && skin.skeleton) ? skin.skeleton.bones : [];
  let same = sb.length > 0 && sb.length === kb.length;
  for (let i = 0; same && i < sb.length; i++) if (sb[i] !== kb[i]) same = false;
  const g = sk.geometry, side = g.attributes.aSide;
  const hist = {};
  if (side) for (let i = 0; i < side.count; i++) {
    const v = side.getX(i); hist[v] = (hist[v] || 0) + 1;
  }
  const u = sk.material && sk.material.userData && sk.material.userData.__sideU;
  return {
    found: true, name: sk.name, isSkinnedMesh: !!sk.isSkinnedMesh,
    layer: (sk.userData && sk.userData.mvaLayer) || '',
    vertices: g.attributes.position.count,
    tris: g.index ? g.index.count / 3 : g.attributes.position.count / 3,
    bones: sb.length, sameRigAsSkin: same,
    skinName: skin ? skin.name : '', skinVisible: skin ? skin.visible : null,
    skinSideU: (skin && skin.material && skin.material.userData
                && skin.material.userData.__sideU)
               ? skin.material.userData.__sideU.value : null,
    visible: sk.visible, renderOrder: sk.renderOrder,
    frustumCulled: sk.frustumCulled, castShadow: sk.castShadow,
    colour: sk.material ? '#' + sk.material.color.getHexString() : '',
    roughness: sk.material ? sk.material.roughness : null,
    hasSide: !!side, sideHist: hist, sideU: u ? u.value : null
  };
}"""

# which instanced passes still exist at all
GFXQ = """() => {
  const g = MVA.__gfx();
  if (!g) return {none:true};
  const one = k => (g[k] === undefined ? 'undefined' : (g[k] ? g[k].count : 'null'));
  return {bone: one('bone'), solid: one('solid'), socket: one('socket'),
          boneH: one('boneH'), solidH: one('solidH'), socketH: one('socketH'),
          joint: one('joint'), link: one('link'), jointH: one('jointH')};
}"""

# everything (4a) asks about, in one round trip
EC_PROBE = """() => {
  const A = MVA, ec = A.ec, m = ec.material, g = ec.geometry;
  const body = (function () {
    let best = null, n = -1;
    MVR.inner.traverse(o => {
      if (!o.isSkinnedMesh || !o.geometry || o.userData.mvaLayer) return;
      const c = o.geometry.attributes.position.count;
      if (c > n) { n = c; best = o; }
    });
    return best;
  })();
  return {
    isSkinned: !!ec.isSkinnedMesh, name: ec.name, layer: ec.userData.mvaLayer,
    sameSkeleton: ec.skeleton === body.skeleton, sibling: ec.parent === body.parent,
    renderOrder: ec.renderOrder, frustumCulled: ec.frustumCulled,
    bindMode: ec.bindMode, bodyBindMode: body.bindMode,
    verts: g.attributes.position.count,
    bodyVerts: body.geometry.attributes.position.count,
    aSide: g.attributes.aSide ? g.attributes.aSide.count : 0,
    uvAtlas: g.userData.uvAtlas || '', uvMiss: g.userData.uvMiss,
    bodyUvAtlas: body.geometry.userData.uvAtlas || '',
    mapW: (m.map && m.map.image) ? m.map.image.width : 0,
    mapH: (m.map && m.map.image) ? m.map.image.height : 0,
    bumpW: (m.bumpMap && m.bumpMap.image) ? m.bumpMap.image.width : 0,
    bumpScale: m.bumpScale, roughness: m.roughness,
    ecName: A.ecName, ecSize: A.ecSize, ecNote: A.ecNote,
    countsMuscle: A.counts.muscle, ms: A.ms || 0
  };
}"""

# (4d) the pixel probe. buildThumbs' recipe: an offscreen target (deterministic,
# unlike scraping a canvas with no preserveDrawingBuffer), the sRGB transfer
# function put back by hand because r147 writes render targets LINEAR, and the
# figure's own screen-space box so the black stage cannot dilute the mean.
PIXEL = """() => {
  const R = MVST3.renderer, W = 200, H = 260;
  const rt = new THREE.WebGLRenderTarget(W, H, {samples: 0});
  const cam = new THREE.PerspectiveCamera(30, W / H, 0.01, 60);
  const A = MVA.atlas;
  const ctr = new THREE.Vector3().setFromMatrixPosition(A.bones.Hips.matrixWorld)
    .addScaledVector(A.up, 0.02 * A.stature);
  const d = (A.stature * 0.60) / Math.tan(cam.fov * Math.PI / 360);
  cam.position.copy(ctr).addScaledVector(A.ant, d);
  cam.lookAt(ctr);
  cam.updateMatrixWorld(true);
  cam.updateProjectionMatrix();

  const ec = MVA.ec;
  ec.geometry.computeBoundingBox();
  const bb = ec.geometry.boundingBox;
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const v = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    v.set(i & 1 ? bb.max.x : bb.min.x, i & 2 ? bb.max.y : bb.min.y,
          i & 4 ? bb.max.z : bb.min.z).applyMatrix4(ec.matrixWorld).project(cam);
    x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x);
    y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
  }
  const px = u => Math.max(0, Math.min(W - 1, Math.round((u * 0.5 + 0.5) * W)));
  const py = u => Math.max(0, Math.min(H - 1, Math.round((u * 0.5 + 0.5) * H)));
  const bx0 = px(x0), bx1 = px(x1), by0 = py(y0), by1 = py(y1);

  const lut = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i / 255;
    c = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
    lut[i] = Math.max(0, Math.min(255, Math.round(c * 255)));
  }
  const buf = new Uint8Array(W * H * 4);
  const prev = R.getRenderTarget();
  R.setRenderTarget(rt);
  R.render(MVST3.scene, cam);
  R.readRenderTargetPixels(rt, 0, 0, W, H, buf);
  R.setRenderTarget(prev);

  let r = 0, g = 0, b = 0, n = 0, lit = 0;
  for (let y = by0; y <= by1; y++) {
    for (let x = bx0; x <= bx1; x++) {
      const i = (y * W + x) * 4;
      const cr = lut[buf[i]], cg = lut[buf[i + 1]], cb = lut[buf[i + 2]];
      if (cr + cg + cb < 36) continue;            // the stage is not the body
      r += cr; g += cg; b += cb; n++;
      if (cr > cg + 25) lit++;
    }
  }
  rt.dispose();
  return {box: [bx0, by0, bx1, by1], n: n,
          r: n ? r / n : 0, g: n ? g / n : 0, b: n ? b / n : 0,
          redFrac: n ? lit / n : 0};
}"""

# the operator's A-pose: the plates were drawn in it, and mixer.setTime(0) is
# NOT it — the first frame of a mocap clip is a stride, not a rest pose.
BIND = """() => {
  MVR.paused = true;
  if (MVR.action) MVR.action.paused = true;
  MVR.inner.traverse(o => { if (o.isSkinnedMesh) o.skeleton.pose(); });
  MVR.inner.updateMatrixWorld(true);
  MVA.tick();
}"""


def _require(cond, msg):
    """Fail the proof when *cond* is false — an `assert` is removed by `python -O`."""
    if not cond:
        raise AssertionError(msg)


def wait_for(pg, js, timeout_ms, label, key='ready'):
    """`key` is named because PROBE also carries an `on` field — the three
    layer switches — and a generic "ready or on" test reads that dict as a
    pass on the very first poll, before the page has loaded anything."""
    waited, st = 0, None
    while waited < timeout_ms:
        st = pg.evaluate(js)
        if st.get(key):
            return st, waited
        if st.get('why') and 'not a cmu_mb' in st['why']:
            raise AssertionError('anatomy refused: %s' % st['why'])
        pg.wait_for_timeout(1000)
        waited += 1000
    raise AssertionError('%s never happened in %d s: %s' % (label, timeout_ms // 1000, json.dumps(st)))


def side_of(pg, what):
    """The uSideKeep uniform of a layer's material: which half it keeps."""
    return pg.evaluate(
        """(w) => {
      const o = w === 'ec' ? MVA.ec : (w === 'skel' ? MVA.skel : null);
      if (o) {
        const u = o.material.userData.__sideU;
        return {v: u ? u.value : null, vis: o.visible};
      }
      let best = null, n = -1;
      MVR.inner.traverse(m => {
        if (!m.isSkinnedMesh || m.userData.mvaLayer) return;
        const c = m.geometry.attributes.position.count;
        if (c > n) { n = c; best = m; }
      });
      const u = best.material.userData.__sideU;
      return {v: u ? u.value : null, vis: best.visible};
    }""",
        what,
    )
