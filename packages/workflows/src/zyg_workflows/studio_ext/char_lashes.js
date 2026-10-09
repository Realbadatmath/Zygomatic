// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_lashes.js — eyelashes on the Character Studio 3D base body. 2026-09-20.

   The base body has no lashes at all; at the wheel's closest stop the lid
   edge was a bare painted line. Each eye now carries ~150 upper lashes (9–11
   mm on a 12 mm globe, thick at the root, curling up and out) and ~55 lower
   ones (shorter, straighter, sparser), rooted on the LID LOOP that
   char_eyes.js measures from the body mesh (the innermost skin vertex per
   bearing round the gaze). Ribbon strands as in char_hair.js, two ribbons
   crossed per lash so a lash is never seen edge-on, vertex colour from the
   hair colour a good deal darker, and the same DOUBLE_SIDED normal fix as
   the hair material (a ribbon at N·V ≈ 0 rendered as a white streak).

   The group is a child of the model ROOT in root-local coordinates, so it
   leaves with the model (Compare's disposeFigure removes the model) and
   moves with it; char_dress.paint() skips 'cs-lashes'. Rebuilt on every
   hook, after char_dress has scaled the body (the hook is deferred, like
   the hair's). Compare's second figure comes through CSLASH.buildFor().

   2026-09-22 (eye macro, backup char_lashes.js.bak-eyemacro-20260922): beside
   a real macro the lashes were thin, sparse, straight, greyish. Now ~230
   upper per eye at 7–10 mm (real: 8–12), sweeping forward then up and out,
   ~95 lower at 3.6–5.5 mm going down; wider at the root (0.29 mm), tapering
   to a point; 40 % in clumps of 2–4; near-black (hair × 0.1); roughness 0.38
   with the eye studio env, and each ribbon carries its own plane normal
   (blended with the old outward one) so a glossy highlight runs along the
   curve instead of one flat tone. The material is transparent so
   char_eyes' distance LOD can fade the lashes out under 30 px of eye. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;

  var HAIR_HEX = {
    'black': 0x1a1512, 'dark brown': 0x3b2a1a, 'brown': 0x5a3d22,
    'light brown': 0x8b6a45, 'auburn': 0x7a3b1e, 'red': 0xa3441f,
    'blonde': 0xd9b46a, 'blond': 0xd9b46a, 'dark blond': 0xa88a4f,
    'dark blonde': 0xa88a4f, 'grey': 0x8c8c8c, 'gray': 0x8c8c8c,
    'white': 0xe8e6e2, 'silver': 0xcfcfcf, 'ginger': 0xa3441f
  };
  var UPPER = { n: 230, len: [0.52, 0.66], seg: 7, w0: 0.011, a0: [0.0, 0.1], a1: [0.5, 0.9], side: [0.4, 0.85], root: 0.03, clumps: 0.4 };  /* a0 ≥ 0: never towards the eye; even lengths; more sideways than up */
  var LOWER = { n: 75, len: [0.22, 0.36], seg: 6, w0: 0.008, a0: [0.2, 0.4], a1: [0.3, 0.6], side: [0.1, 0.45], root: 0.025, clumps: 0.3 };
  /* side: a sideways sweep along the lid (towards the temple for 3 in 4)
     that grows along the lash — from the front a lash curving only in depth
     projects to a straight radial spoke; this is what makes it a curve. */
  /* len, w0, root: in eye radii. a0/a1: the lash direction is f + t·(a0 + a1·s)
     for s along the lash — t is the outward direction in the lid plane, so
     the upper lashes start almost straight forward and curl up/out, the
     lower start down/out and stay nearly straight. */

  function low(v) { return (v === undefined || v === null) ? '' : String(v).toLowerCase().trim(); }
  function pageVal(path) {
    try { if (typeof cstVal === 'function') return low(cstVal(path)); } catch (e) {}
    return '';
  }
  function rngOf(seed) {
    var s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  function hairColour(word, store) {
    var w = word || (store && store.hairInfo && store.hairInfo.color) || 'brown';
    var hex = HAIR_HEX[w];
    if (hex === undefined) {
      for (var k in HAIR_HEX) { if (HAIR_HEX.hasOwnProperty(k) && w.indexOf(k) >= 0) { hex = HAIR_HEX[k]; break; } }
    }
    if (hex === undefined) hex = HAIR_HEX.brown;
    var c = new THREE.Color(hex);
    if (c.convertSRGBToLinear) c.convertSRGBToLinear();
    /* lashes are darker than the hair on every head; blond lashes are tan */
    return c.multiplyScalar(0.22);
  }

  function lashMaterial() {
    var env = null;
    try { env = (window.CSEYES && CSEYES.env) ? CSEYES.env('hot') : null; } catch (e) { env = null; }
    var m = new THREE.MeshStandardMaterial({
      color: 0xffffff, vertexColors: true, roughness: 0.3, metalness: 0, side: THREE.DoubleSide,
      envMap: env, envMapIntensity: 0.15, transparent: true, opacity: 1, depthWrite: true   /* the hot env has a ×150 core: 0.15 keeps the gloss, no glitter at head distance */
    });
    m.onBeforeCompile = function (shader) {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <normal_fragment_begin>',
        THREE.ShaderChunk.normal_fragment_begin.replace('normal = normal * faceDirection;',
          'vec3 csVV = normalize( vViewPosition ); float csNV = dot( normal, csVV );' +
          ' if ( csNV < 0.0 ) normal = normalize( normal - 2.0 * csNV * csVV );' +
          ' normal = normalize( normal + 0.25 * csVV );'));
    };
    m.customProgramCacheKey = function () { return 'cs-lash-noflip'; };
    m.userData.csKey = 'lash';
    /* the same width floor the hair uses: a lash is the thinnest thing on the
       figure and the worst dropout case measured. 1.6 px rather than the hair's
       1.3 — a lash carries no colour of its own to lose, and the lid line wants
       to read as continuous rather than as 230 separate slivers. */
    if (window.CSSTRAND) CSSTRAND.patch(m, { minPx: 1.6 });
    return m;
  }

  /* one lid's lashes into the shared arrays. arc: the loop's bins from the
     inner corner to the outer corner (bearing order), spec: UPPER/LOWER */
  function lashes(loop, arc, spec, sgnOut, rnd, col, out) {
    var NB = loop.n, R = loop.R, f = loop.f, c = loop.c;
    var P = new THREE.Vector3(), T = new THREE.Vector3(), D = new THREE.Vector3(), N = new THREE.Vector3();
    var B1 = new THREE.Vector3(), B2 = new THREE.Vector3(), tmp = new THREE.Vector3(), q = new THREE.Quaternion();
    var up = loop.up, right = loop.right;
    var count = 0, tries = 0, clumpAt = -1, clumpLeft = 0;
    while (count < spec.n && tries < spec.n * 6) {
      tries++;
      var u;
      if (clumpLeft > 0) { u = clumpAt + (rnd() - 0.5) * 0.016; clumpLeft--; }
      else {
        u = rnd();
        /* sparse at the inner corner (real lids have few lashes there),
           densest over the outer two thirds */
        var dens = 0.2 + 0.8 * Math.min(1, Math.max(0, (u - 0.05) / 0.3));
        if (rnd() > dens) continue;
        if (rnd() < spec.clumps) { clumpAt = u; clumpLeft = 1 + Math.floor(rnd() * 3); }
      }
      u = Math.min(0.995, Math.max(0.005, u));
      /* the root: interpolate the arc */
      var x = u * (arc.length - 1), i0 = Math.floor(x), tt = x - i0, i1 = Math.min(arc.length - 1, i0 + 1);
      P.copy(loop.pts[arc[i0]]).lerp(loop.pts[arc[i1]], tt);
      /* outward in the lid plane: away from the gaze axis */
      T.subVectors(P, c); T.addScaledVector(f, -T.dot(f)).normalize();
      /* the root sits a hair forward of the lid edge, on the margin */
      P.addScaledVector(f, spec.root * R * 0.6).addScaledVector(T, spec.root * R * 0.4);
      /* jitter the outward direction round the gaze by ±14°, and lean the
         outer lashes towards the temple */
      var lean = sgnOut * (0.6 * Math.max(0, u - 0.35) + 0.15);
      T.addScaledVector(right, lean).normalize();
      q.setFromAxisAngle(f, (rnd() - 0.5) * 0.9);
      T.applyQuaternion(q);
      var lenProfile = 0.7 + 0.3 * Math.sin(Math.PI * Math.min(1, 0.1 + u * 0.95));
      var L = R * (spec.len[0] + (spec.len[1] - spec.len[0]) * rnd()) * lenProfile;
      var a0 = spec.a0[0] + (spec.a0[1] - spec.a0[0]) * rnd();
      var a1 = spec.a1[0] + (spec.a1[1] - spec.a1[0]) * rnd();
      /* the sweep follows the position along the lid: temple-wards over the
         outer two thirds, a little nose-wards near the inner corner, so no
         lash is dragged across the iris */
      var side = (spec.side[0] + (spec.side[1] - spec.side[0]) * rnd()) * (0.35 + 0.65 * Math.max(0, (u - 0.15) / 0.85)) * (u < 0.12 && rnd() < 0.5 ? -sgnOut : sgnOut);
      var w0 = spec.w0 * R * (0.8 + 0.45 * rnd());
      var SEG = spec.seg, h = L / SEG;
      var k = 0.6 + 0.5 * rnd();
      var cr = col.r * k, cg = col.g * k, cb = col.b * k;
      /* shading normal: outward and forward */
      N.copy(f).addScaledVector(T, 0.6).normalize();
      var base = out.pos.length / 3;
      var px = P.x, py = P.y, pz = P.z;
      for (var s = 0; s <= SEG; s++) {
        var kk = s / SEG;
        if (s) {
          /* the sweep is quadratic: the root leaves the lid nearly straight
             forward (foreshortened from the front), the tip curls up and out */
          D.copy(f).addScaledVector(T, a0 + a1 * kk * kk).addScaledVector(right, side * kk).normalize();
          px += D.x * h; py += D.y * h; pz += D.z * h;
        } else D.copy(f).addScaledVector(T, a0).normalize();
        /* two crossed ribbons, tapering to a point */
        B1.crossVectors(D, up); if (B1.lengthSq() < 1e-8) B1.crossVectors(D, right); B1.normalize();
        B2.crossVectors(D, B1).normalize();
        var ww = w0 * Math.pow(1 - kk, 0.9) * 0.5;      /* to a point */
        out.pos.push(px - B1.x * ww, py - B1.y * ww, pz - B1.z * ww, px + B1.x * ww, py + B1.y * ww, pz + B1.z * ww,
                     px - B2.x * ww, py - B2.y * ww, pz - B2.z * ww, px + B2.x * ww, py + B2.y * ww, pz + B2.z * ww);
        /* the width floor's axis + signed offset, one vec4 per vertex, for both
           crossed ribbons. `ww` is the HALF width here (strands() in
           char_hair.js calls its own `ww` the FULL width — only the offset
           actually emitted above is trustworthy). A lash root is 0.106-0.165 mm
           and covers 0.10 px at the default framing: measured, an opaque strip
           that thin renders NOTHING at 8 of 16 sub-pixel offsets, which is the
           black crust round the lid. */
        out.edg.push(B1.x, B1.y, B1.z, -ww, B1.x, B1.y, B1.z, ww,
                     B2.x, B2.y, B2.z, -ww, B2.x, B2.y, B2.z, ww);
        /* ribbon 1 lies in (D, B1): its plane normal is B2; ribbon 2's is B1.
           Half the old shared normal keeps the strand from going black
           edge-on; half the plane normal lets the highlight travel along it. */
        tmp.copy(N).addScaledVector(B2, B2.dot(N) < 0 ? -1 : 1).normalize();
        out.nrm.push(tmp.x, tmp.y, tmp.z, tmp.x, tmp.y, tmp.z);
        tmp.copy(N).addScaledVector(B1, B1.dot(N) < 0 ? -1 : 1).normalize();
        out.nrm.push(tmp.x, tmp.y, tmp.z, tmp.x, tmp.y, tmp.z);
        for (var r = 0; r < 4; r++) out.col.push(cr, cg, cb);
      }
      for (s = 0; s < SEG; s++) {
        var q0 = base + s * 4;
        out.idx.push(q0, q0 + 1, q0 + 5, q0, q0 + 5, q0 + 4);
        out.idx.push(q0 + 2, q0 + 3, q0 + 7, q0 + 2, q0 + 7, q0 + 6);
      }
      count++;
    }
    return count;
  }

  /* the loop's upper arc from the inner corner to the outer corner, and the
     lower arc likewise. Bearing 0 = +right, π/2 = up. Which end is the inner
     corner depends on the eye: the nose side is where the OTHER eye is. */
  function arcs(loop, noseSign) {
    var NB = loop.n, up = [], lo = [], i;
    for (i = 0; i <= NB / 2; i++) up.push(i % NB);                 /* 0 … π  (right → up → left) */
    for (i = NB / 2; i <= NB; i++) lo.push(i % NB);                /* π … 2π (left → down → right) */
    /* bearing 0 (= +right) is the nose side when noseSign·right·x > 0 */
    var rightIsNose = (loop.right.x * noseSign) > 0;
    if (!rightIsNose) up.reverse(); else lo.reverse();
    /* trim the corners: no lashes in the last 6 % at each end */
    var cut = Math.max(1, Math.round(NB * 0.03));
    return { up: up.slice(cut, up.length - cut), lo: lo.slice(cut, lo.length - cut), sgnOut: rightIsNose ? -1 : 1 };
  }

  function dispose(store) {
    var g = store && store.lashes;
    if (!g) return;
    if (g.parent) g.parent.remove(g);
    g.traverse(function (o) { if (o.isMesh) { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); } });
    store.lashes = null;
  }

  function buildFor(ctx) {
    var model = ctx.model, store = ctx.store;
    dispose(store);
    if (!model || !window.CSEYES || !CSEYES.eyeMeshes) return;
    var t0 = performance.now();
    var eyes = CSEYES.eyeMeshes(model);
    if (eyes.length !== 2) return;
    var body = CSEYES.bodyMesh(model);
    if (!body) return;
    var fwd = new THREE.Vector3(0, 0, CSEYES.forwardOf(model, eyes));
    var mx = 0.5 * (eyes[0].centre.x + eyes[1].centre.x);
    var out = { pos: [], nrm: [], col: [], idx: [], edg: [] };
    var col = hairColour(ctx.hair, store);
    var rnd = rngOf(0x1a5e5);
    var n = 0, i;
    for (i = 0; i < 2; i++) {
      var e = eyes[i], noseSign = (e.centre.x < mx) ? 1 : -1;
      var toNose = new THREE.Vector3(noseSign, 0, 0);
      var loop = (store._eyeLoops && store._eyeLoops[i]) || CSEYES.lidLoop(body, CSEYES.worldBasis(e, fwd, toNose));
      if (!loop) continue;
      var A = arcs(loop, noseSign);
      n += lashes(loop, A.up, UPPER, A.sgnOut, rnd, col, out);
      n += lashes(loop, A.lo, LOWER, A.sgnOut, rnd, col, out);
    }
    if (!n) return;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(out.pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(out.nrm, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(out.col, 3));
    g.setAttribute('csEdge', new THREE.Float32BufferAttribute(out.edg, 4));
    g.setIndex(out.idx);
    /* world coordinates inside the root: the group carries the root's inverse */
    model.updateWorldMatrix(true, false);
    var grp = new THREE.Group();
    grp.name = 'cs-lashes';
    grp.matrixAutoUpdate = false;
    grp.matrix.copy(model.matrixWorld).invert();
    grp.matrixWorldNeedsUpdate = true;
    var m = new THREE.Mesh(g, lashMaterial());
    m.name = 'cs-lashes-mesh';
    m.frustumCulled = false;
    grp.add(m);
    model.add(grp);
    store.lashes = grp;
    store.lashInfo = { lashes: n, verts: out.pos.length / 3, ms: performance.now() - t0 };
  }

  var pending = 0;
  function rebuild(why) {
    if (pending) return;
    pending = setTimeout(function () {
      pending = 0;
      if (!CS3 || CS3.failed || !CS3.model) { dispose(CS3); return; }
      try { buildFor({ model: CS3.model, store: CS3, hair: pageVal('identity.hair_color') }); }
      catch (e) { console.warn('char_lashes', why, e); }
    }, 0);
  }
  CS3_HOOKS.push(rebuild);
  window.CSLASH = {
    buildFor: function (model, store, values) {
      var hair = '';
      try { hair = low(values ? values('identity.hair_color') : ''); } catch (e) {}
      buildFor({ model: model, store: store, hair: hair });
    },
    dispose: dispose, rebuild: function () { rebuild('manual'); }
  };
  if (CS3.model) rebuild('bundle');
})();
