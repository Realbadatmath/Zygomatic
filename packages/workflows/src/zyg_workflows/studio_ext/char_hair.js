// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_hair.js — hair, beard and brows on the Character Studio 3D base body.
   2026-09-18; strands 2026-09-19.

   The preview body is the CC0 Blender Studio human base: no hair, no
   materials, one clay MeshStandardMaterial per mesh. There is no hair asset on
   disk, so the hair is grown FROM the body. A thin dark scalp shell (the
   scalp triangles pushed out 2 mm, feathered at the hairline) sits under
   thousands of ribbon STRANDS grown from the scalp field: groomed (back over
   the top, down the sides, a crown whorl, the fringe swept aside), pulled by
   gravity, waved or coiled by the texture, kept off the skin and hugged to
   the skull by a spatial hash of the body, trimmed round the ears on short
   cuts. Beards and brows are strands too. See the '── strands' section.
   The thick shell and the fall curtain below remain only as the path for a
   head with no strand spec (hairline 'fully bald' draws nothing anyway).

   The body's own material is never touched (task 9 owns skin and clothes) and
   CS3.height is never written, so cs3dFrame's framing is unchanged.

   Everything hangs off CS3_HOOKS: one function that disposes the old group and
   (re)builds from the CURRENT staged-else-saved values (cstVal). With no
   character loaded it builds a default short brown head of hair, so the base
   body is never bald by accident. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;

  /* ── the palette ──────────────────────────────────────────────────────── */
  var HAIR_HEX = {
    'black': 0x1a1512, 'dark brown': 0x3b2a1a, 'brown': 0x5a3d22,
    'light brown': 0x8b6a45, 'auburn': 0x7a3b1e, 'red': 0xa3441f,
    'blonde': 0xd9b46a, 'blond': 0xd9b46a, 'dark blond': 0xa88a4f,
    'dark blonde': 0xa88a4f, 'grey': 0x8c8c8c, 'gray': 0x8c8c8c,
    'white': 0xe8e6e2, 'silver': 0xcfcfcf, 'ginger': 0xa3441f
  };
  var GREY_HEX = 0xb8b8b8;

  /* shell thickness by length; anything longer than medium keeps the cap of a
     long head of hair and gains its length from the fall instead */
  var THICK = { 'shaved': 0.002, 'short': 0.012, 'medium': 0.02 };
  var THICK_LONG = 0.025;
  /* a coil stands off the scalp; a wave a little less */
  var TEX_MUL = { 'curly': 1.6, 'coily': 1.6, 'kinky': 1.6, 'wavy': 1.25 };
  /* how far below yTop the fall reaches, in head heights */
  /* 'medium' is collar-length: the cap alone stops at the nape and reads as a
     bald neck under a helmet from behind, so it gets a short fall too */
  var FALL_TO = { 'medium': 1.12, 'shoulder': 1.9, 'long': 3.2, 'waist-length': 4.2, 'waist length': 4.2 };
  /* the width of the soft edge on every hair boundary, in metres: the hair
     thins to nothing over this distance instead of stopping at a stair-stepped
     triangle boundary (the scalp triangles are ~5 mm) */
  var FEATHER = 0.018;
  var BEARD_T = {
    'stubble': 0.003, 'short beard': 0.01, 'full beard': 0.02,
    'goatee': 0.012, 'moustache': 0.012, 'beard': 0.012
  };
  /* how much of the greying colour is mixed in */
  var GREY_MIX = {
    'none': 0, 'temples': 1, 'streaks': 0.25, 'salt and pepper': 0.5,
    'salt-and-pepper': 0.5, 'mostly grey': 0.8, 'mostly gray': 0.8,
    'fully grey': 1, 'fully gray': 1
  };
  var ROUGH = { 'glossy': 0.25, 'shiny': 0.25, 'matte': 0.85, 'dry': 0.85, 'wet': 0.12 };

  var DEFAULTS = {
    length: 'short', color: 'brown', texture: 'straight', facial: 'none',
    brow: 'natural', hairline: 'natural', greying: 'none', behaviour: 'still'
  };

  function low(v) {
    if (v === undefined || v === null) return '';
    return String(v).toLowerCase().trim();
  }
  /* staged value else saved value, via the page's own reader */
  function val(path) {
    try {
      if (typeof cstVal === 'function' && typeof CST !== 'undefined') return low(cstVal(path));
    } catch (e) {}
    return '';
  }
  function pick(path, dflt, get) { var v = (get || val)(path); return v ? v : dflt; }

  /* get = a value reader (path → lowercase string); the studio's own is the
     default. loaded = whether a character stands behind those values — with
     none, the default short brown head of hair. */
  function readWants(get, loaded) {
    if (!get) { get = val; loaded = (typeof CS !== 'undefined' && CS && CS.loaded); }
    if (!loaded) {
      return {
        def: true, length: DEFAULTS.length, color: DEFAULTS.color,
        texture: DEFAULTS.texture, facial: DEFAULTS.facial, brow: DEFAULTS.brow,
        hairline: DEFAULTS.hairline, greying: DEFAULTS.greying, behaviour: DEFAULTS.behaviour
      };
    }
    return {
      def: false,
      length: pick('identity.hair_length', DEFAULTS.length, get),
      color: pick('identity.hair_color', DEFAULTS.color, get),
      texture: pick('identity.hair_texture', DEFAULTS.texture, get),
      facial: pick('identity.facial_hair', DEFAULTS.facial, get),
      brow: pick('identity.eyebrow_style', DEFAULTS.brow, get),
      hairline: pick('appearance.hairline', DEFAULTS.hairline, get),
      greying: pick('appearance.greying', DEFAULTS.greying, get),
      behaviour: pick('appearance.hair_behaviour', DEFAULTS.behaviour, get)
    };
  }

  /* The renderer is set to sRGB output, so a colour written straight in with
     setHex is taken as LINEAR and comes back out of the gamma curve two shades
     too pale — #5a3d22 brown renders as a light tan. Every swatch above is an
     sRGB hex, so convert it. */
  function srgb(hex) {
    var c = new THREE.Color(hex);
    if (CS3.renderer && THREE.sRGBEncoding && CS3.renderer.outputEncoding === THREE.sRGBEncoding
        && c.convertSRGBToLinear) c.convertSRGBToLinear();
    return c;
  }
  function baseColour(w) {
    var hex = HAIR_HEX[w.color];
    if (hex === undefined) hex = HAIR_HEX[DEFAULTS.color];
    return srgb(hex);
  }
  function greyAmount(w) {
    var g = GREY_MIX[w.greying];
    return (g === undefined) ? 0 : g;
  }
  function roughness(w) {
    var r = ROUGH[w.behaviour];
    return (r === undefined) ? 0.62 : r;
  }
  function thickness(w) {
    var t = THICK[w.length];
    if (t === undefined) t = THICK_LONG;
    var m = TEX_MUL[w.texture];
    return t * (m === undefined ? 1 : m);
  }

  /* ── the body, measured ───────────────────────────────────────────────── */

  function underName(o, name) {
    for (var p = o; p; p = p.parent) { if (p.name === name) return true; }
    return false;
  }
  function bodyMesh(model) {
    var best = null, n = -1;
    if (!model) return null;
    model.traverse(function (o) {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      if (/eye[lr]$/i.test(o.name || '')) return;          /* the eyes are their own meshes */
      if (underName(o, 'cs-hair') || underName(o, 'CS3_DRESS')) return;  /* our own work */
      var c = o.geometry.attributes.position.count;
      if (c > n) { n = c; best = o; }
    });
    return best;
  }

  /* world-space positions + normals of the body mesh, plus a triangle index.
     updateWorldMatrix(true, …) walks UP first: the 'model' hook fires inside
     the GLTF load callback, before the first render, so the root group's own
     matrixWorld is still the identity at that point and plain
     updateMatrixWorld() would sample the mesh in the GLB's own coordinates —
     a head of hair floating a metre or two beside the body. */
  function sampleBody(mesh) {
    mesh.updateWorldMatrix(true, false);
    var g = mesh.geometry, pa = g.attributes.position, na = g.attributes.normal;
    var m = mesh.matrixWorld, nm = new THREE.Matrix3().getNormalMatrix(m);
    var n = pa.count, P = new Float32Array(n * 3), N = new Float32Array(n * 3);
    var v = new THREE.Vector3(), w = new THREE.Vector3();
    var minY = Infinity, maxY = -Infinity, i;
    for (i = 0; i < n; i++) {
      v.set(pa.getX(i), pa.getY(i), pa.getZ(i)).applyMatrix4(m);
      P[i * 3] = v.x; P[i * 3 + 1] = v.y; P[i * 3 + 2] = v.z;
      if (v.y < minY) minY = v.y;
      if (v.y > maxY) maxY = v.y;
      if (na) {
        w.set(na.getX(i), na.getY(i), na.getZ(i)).applyMatrix3(nm);
        if (w.lengthSq() > 1e-12) w.normalize();
        N[i * 3] = w.x; N[i * 3 + 1] = w.y; N[i * 3 + 2] = w.z;
      }
    }
    var idx;
    if (g.index) { idx = g.index.array; }
    else { idx = new Uint32Array(n); for (i = 0; i < n; i++) idx[i] = i; }
    if (!na) faceNormals(P, idx, N);
    return { P: P, N: N, count: n, idx: idx, minY: minY, maxY: maxY };
  }

  /* only used when the GLB arrives without a normal attribute */
  function faceNormals(P, idx, N) {
    var a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    var ab = new THREE.Vector3(), ac = new THREE.Vector3(), cr = new THREE.Vector3(), k;
    for (var t = 0; t + 2 < idx.length; t += 3) {
      var i0 = idx[t], i1 = idx[t + 1], i2 = idx[t + 2];
      a.set(P[i0 * 3], P[i0 * 3 + 1], P[i0 * 3 + 2]);
      b.set(P[i1 * 3], P[i1 * 3 + 1], P[i1 * 3 + 2]);
      c.set(P[i2 * 3], P[i2 * 3 + 1], P[i2 * 3 + 2]);
      ab.subVectors(b, a); ac.subVectors(c, a); cr.crossVectors(ab, ac);
      for (k = 0; k < 3; k++) {
        var ii = idx[t + k];
        N[ii * 3] += cr.x; N[ii * 3 + 1] += cr.y; N[ii * 3 + 2] += cr.z;
      }
    }
    for (var i = 0; i * 3 < N.length; i++) {
      var x = N[i * 3], y = N[i * 3 + 1], z = N[i * 3 + 2];
      var L = Math.sqrt(x * x + y * y + z * z) || 1;
      N[i * 3] = x / L; N[i * 3 + 1] = y / L; N[i * 3 + 2] = z / L;
    }
  }

  /* head band metrics + which of ±Z the face looks down.
     glTF is Y-up but the front is NOT assumed: the nose is the vertex that
     sticks furthest out of the head's z centre in the nose band, and its sign
     is the forward axis. */
  function headMetrics(S) {
    var yTop = S.maxY, H = S.maxY - S.minY;
    var headH = 0.13 * H;
    var chinY = yTop - headH;
    var i, x, y, z;
    var xmin = Infinity, xmax = -Infinity, zmin = Infinity, zmax = -Infinity, band = 0;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y <= chinY) continue;
      band++;
      x = S.P[i * 3]; z = S.P[i * 3 + 2];
      if (x < xmin) xmin = x; if (x > xmax) xmax = x;
      if (z < zmin) zmin = z; if (z > zmax) zmax = z;
    }
    if (!band) return null;
    var headW = Math.max(1e-4, xmax - xmin);
    var cx = (xmin + xmax) * 0.5, zc = (zmin + zmax) * 0.5;
    var browY = yTop - 0.42 * headH;
    /* nose band: the middle of the face, between the chin and the brow */
    var pos = 0, neg = 0;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y < chinY + 0.22 * headH || y > browY) continue;
      if (Math.abs(S.P[i * 3] - cx) > 0.10 * headW) continue;
      var d = S.P[i * 3 + 2] - zc;
      if (d > pos) pos = d;
      if (d < neg) neg = d;
    }
    var fwd = (pos >= -neg) ? 1 : -1;
    /* depth range of the head along the forward axis */
    var fmin = Infinity, fmax = -Infinity;
    for (i = 0; i < S.count; i++) {
      if (S.P[i * 3 + 1] <= chinY) continue;
      var f = fwd * (S.P[i * 3 + 2] - zc);
      if (f < fmin) fmin = f;
      if (f > fmax) fmax = f;
    }
    return {
      yTop: yTop, H: H, headH: headH, headW: headW, cx: cx, zc: zc, fwd: fwd,
      browY: browY, earY: yTop - 0.62 * headH, chinY: chinY,
      fmin: fmin, fmax: fmax, depth: Math.max(1e-4, fmax - fmin),
      nosePos: pos, noseNeg: neg
    };
  }

  /* the two eyeball meshes, measured in world space: centre and diameter.
     They are the one landmark on the base body that is exact — the brow's
     place is a fixed distance above the eye, whatever the head's proportions
     — so the brows anchor to them and fall back to head fractions only when a
     body ships without eye meshes. */
  function eyeAnchors(model) {
    var out = [];
    if (!model) return out;
    model.traverse(function (o) {
      if (!o.isMesh || !/eye[lr]$/i.test(o.name || '')) return;
      var b = new THREE.Box3().setFromObject(o), c = new THREE.Vector3(), sz = new THREE.Vector3();
      b.getCenter(c); b.getSize(sz);
      out.push({ x: c.x, y: c.y, z: c.z, d: Math.max(sz.x, sz.y, sz.z) });
    });
    if (out.length !== 2) return [];
    out.sort(function (a, b) { return a.x - b.x; });
    return out;
  }

  /* ── selections ───────────────────────────────────────────────────────── */

  /* The ears. The base body is one mesh, ears included, and a shell that copies
     the scalp triangles copies the ear triangles with them: pushed 2 cm out
     along their own normals the auricle turned into a golden cone standing off
     the side of the head. Found from the mesh, not assumed: in the ear band
     (0.44–0.75 head heights below the crown) the vertices that stand out past
     90 % of the head's half-width are the protruding auricle; their depth range
     (+ a margin for the root) is the ear zone, and the skull's own half-width
     is the widest vertex in that band OUTSIDE the zone. */
  function earBox(S, M) {
    var yb0 = M.yTop - 0.75 * M.headH, yb1 = M.yTop - 0.44 * M.headH;
    var halfW = 0.5 * M.headW, i, y, ax, z;
    var z0 = Infinity, z1 = -Infinity, n = 0, ey0 = Infinity, ey1 = -Infinity;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y < yb0 || y > yb1) continue;
      ax = Math.abs(S.P[i * 3] - M.cx);
      if (ax < 0.90 * halfW) continue;
      z = S.P[i * 3 + 2];
      if (z < z0) z0 = z; if (z > z1) z1 = z; n++;
      if (y < ey0) ey0 = y; if (y > ey1) ey1 = y;
    }
    if (n < 20) return null;
    /* 2026-09-19: the zone is the auricle's own extent plus 4 mm, not the
       whole ear band: a 1.5 cm margin on a band 0.3 head-heights tall left a
       bare stripe of skull round every ear once the strands were trimmed by
       their distance to it */
    z0 -= 0.004; z1 += 0.004;
    yb0 = Math.max(yb0, ey0 - 0.004); yb1 = Math.min(yb1, ey1 + 0.004);
    var skullR = 0;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y < yb0 || y > yb1) continue;
      z = S.P[i * 3 + 2];
      if (z >= z0 && z <= z1) continue;
      ax = Math.abs(S.P[i * 3] - M.cx);
      if (ax > skullR) skullR = ax;
    }
    /* 2026-09-20: the auricle's own vertices, flagged once. Inside the ear's
       (y,z) box at or beyond the skull radius (3 mm in, so the ring of skull
       the ear grows from counts too). The operator saw hair IN the ear: the
       old test only caught strands 6 mm proud of the skull, so strands rooted
       on the concha, and strands the skin-hug step laid 2 mm above the
       auricle, survived. Roots on these vertices are refused, short cuts stop
       at them, longer hair is pushed outside them (see the growth loop). */
    var earV = new Uint8Array(S.count), ro = skullR;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y < yb0 || y > yb1) continue;
      z = S.P[i * 3 + 2];
      if (z < z0 || z > z1) continue;
      ax = Math.abs(S.P[i * 3] - M.cx);
      if (ax > skullR + 0.001) { earV[i] = 1; if (ax > ro) ro = ax; }   /* proud of the skull: the auricle only (a 3 mm ring inward left a bald notch) */
    }
    S.earV = earV;
    return { y0: yb0, y1: yb1, z0: z0, z1: z1, r: skullR + 0.002, ro: ro };
  }
  /* is (x,y,z) on the auricle itself: inside its y/z extent AND standing out
     past the skull's radius by more than a strand's clearance. earDist alone
     cannot say — the skull directly above the ear is at that same radius, so
     a strand lifted 2 mm off it there counted as "on the ear" and every
     strand over the ear was trimmed into a rectangular notch. */
  function earHit(E, x, y, z) {
    if (!E) return false;
    if (y < E.y0 - 0.004 || y > E.y1 + 0.004 || z < E.z0 - 0.004 || z > E.z1 + 0.004) return false;
    return Math.abs(x) > E.r + 0.006;
  }
  /* signed distance OUTSIDE the ear (positive = not ear, negative = on the ear) */
  function earDist(E, x, y, z) {
    if (!E) return 1;
    var box = Math.max(E.y0 - y, y - E.y1, E.z0 - z, z - E.z1);   /* <0 inside the (y,z) box */
    var side = E.r - Math.abs(x);                                    /* <0 out past the skull */
    return Math.max(box, side);
  }

  /* piecewise-linear curve over the bearing round the head: 0° = straight
     ahead, 180° = the back. Values are head heights below the crown. */
  function curve(knots, deg) {
    var i;
    if (deg <= knots[0][0]) return knots[0][1];
    for (i = 1; i < knots.length; i++) {
      if (deg <= knots[i][0]) {
        var k = (deg - knots[i - 1][0]) / (knots[i][0] - knots[i - 1][0]);
        return knots[i - 1][1] + (knots[i][1] - knots[i - 1][1]) * k;
      }
    }
    return knots[knots.length - 1][1];
  }

  /* The scalp as a signed field, metres, positive = hair. One boundary curve
     runs round the head: the hairline across the forehead (centre 0.26 head
     heights below the crown — the eye centres sit at 0.50, the brow ridge at
     ~0.44 — the corners a touch higher, then down the temple to the sideburn
     in front of the ear), the ear top at the side, and the nape at the back.
     The old cut was a flat plane 0.18 below the crown with a hard depth
     threshold: from the front the forehead ran up over the crown and the cap
     sat behind it like a helmet. The shell feathers this field over FEATHER,
     so the visible edge is the smooth iso-line, not the triangle boundary. */
  function scalpField(S, M, w) {
    var D = new Float32Array(S.count);
    var i;
    if (w.hairline === 'fully bald') { for (i = 0; i < S.count; i++) D[i] = -1; return D; }
    var hl = w.hairline;
    var longish = (FALL_TO[w.length] !== undefined);
    /* 2026-09-19: a rounded front with a slight recession at the corners,
       temples running down into SIDEBURNS in front of the ear (the ear box
       keeps the auricle itself bare), the nape behind */
    var lim = [[0, 0.245], [16, 0.24], [32, 0.25], [46, 0.31], [56, 0.42], [66, 0.55],
               [74, 0.65], [82, 0.72], [92, 0.71], [102, 0.72], [114, 0.76], [140, 0.82], [180, 0.86]];
    if (longish) lim = [[0, 0.245], [16, 0.24], [32, 0.25], [46, 0.31], [56, 0.42], [66, 0.55],
                        [74, 0.65], [82, 0.72], [92, 0.71], [102, 0.74], [114, 0.82], [140, 0.90], [180, 0.92]];
    var j;
    if (hl === 'high') { for (j = 0; j < 4; j++) lim[j][1] -= 0.05; }
    else if (hl === 'low') { for (j = 0; j < 4; j++) lim[j][1] += 0.04; }
    else if (hl === "widow's peak") { lim[0][1] += 0.05; lim[1][1] -= 0.03; lim[2][1] -= 0.01; }
    else if (hl === 'receding temples') { lim[1][1] = 0.15; lim[2][1] = 0.16; lim[3][1] = 0.25; lim[4][1] = 0.38; }
    var crown = (hl === 'bald crown');
    var crownR = 0.36 * M.headW, fc = M.fmin + 0.45 * M.depth;
    var E = M.ear;
    var x, y, z, f, yt, deg, d;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      yt = (M.yTop - y) / M.headH;
      if (yt > 1.05) { D[i] = -1; continue; }
      if (S.earV && S.earV[i]) { D[i] = -0.004; continue; }     /* no hair grows on the ear */
      x = S.P[i * 3] - M.cx; z = S.P[i * 3 + 2];
      f = M.fwd * (z - M.zc);
      deg = Math.abs(Math.atan2(x, f)) * 180 / Math.PI;
      d = (curve(lim, deg) - yt) * M.headH;
      var de = earDist(E, S.P[i * 3] - M.cx, y, z);
      if (de < d) d = de;
      if (crown) {
        var df = f - fc, dc = Math.sqrt(x * x + df * df) - crownR;
        var dy = (yt - 0.24) * M.headH;
        if (dc < dy) dc = dy;                 /* the disc only cuts the top */
        if (dc < d) d = dc;
      }
      D[i] = d;
    }
    return D;
  }
  function selFromField(D) {
    var sel = new Uint8Array(D.length);
    for (var i = 0; i < D.length; i++) if (D[i] > 0) sel[i] = 1;
    return sel;
  }

  function beardField(S, M, w) {
    var D = new Float32Array(S.count), i;
    var kind = w.facial;
    if (!kind || kind === 'none' || kind === 'clean-shaven' || kind === 'clean shaven') {
      for (i = 0; i < S.count; i++) D[i] = -1;
      return D;
    }
    var bandTop = M.browY - 0.45 * M.headH;
    if (kind === 'full beard') bandTop = M.yTop - 0.75 * M.headH;   /* up onto the cheeks */
    var bandBot = M.chinY - 0.05 * M.headH;
    var bandH = Math.max(1e-4, bandTop - bandBot);
    var frontCut = M.fmin + 0.45 * M.depth;                          /* front 55 % */
    var mouthTop = bandTop - 0.25 * bandH;
    var x, y, f, d;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      f = M.fwd * (S.P[i * 3 + 2] - M.zc);
      x = Math.abs(S.P[i * 3] - M.cx);
      d = Math.min(y - bandBot, bandTop - y, f - frontCut);
      if (kind === 'moustache') {
        d = Math.min(d, y - mouthTop, 0.35 * M.headW - x);
      } else if (kind === 'goatee') {
        d = Math.min(d, 0.32 * M.headW - x);
        /* chin patch plus the lip strip, nothing on the jaw */
        var gap = Math.max(bandBot + 0.5 * bandH - y, y - mouthTop);
        if (gap < d) d = gap;
      }
      D[i] = d;
    }
    return D;
  }

  /* ── geometry from a field: every triangle with a corner inside (D > 0).
     The offset tapers from t down to a hair's breadth over FEATHER inside the
     boundary and the vertex alpha fades the same way, so the edge is the
     smooth D = 0 line lying flat on the skin, not a 2 cm cliff along a
     stair-stepped triangle boundary. Colour is RGBA: three.js reads a
     4-component colour attribute as vertex alpha. */
  function shell(S, D, t, colFn, feather) {
    var pos = [], col = [], tri = 0;
    var i0, i1, i2, k, ii, d, s, tt;
    var c = new THREE.Color();
    var tMin = Math.min(0.0008, t);
    if (!feather) feather = 1e-6;
    for (var a = 0; a + 2 < S.idx.length; a += 3) {
      i0 = S.idx[a]; i1 = S.idx[a + 1]; i2 = S.idx[a + 2];
      if (D[i0] <= 0 && D[i1] <= 0 && D[i2] <= 0) continue;
      tri++;
      for (k = 0; k < 3; k++) {
        ii = S.idx[a + k];
        d = D[ii] / feather;
        if (d < 0) d = 0; else if (d > 1) d = 1;
        s = d * d * (3 - 2 * d);
        tt = tMin + (t - tMin) * s;
        pos.push(S.P[ii * 3] + S.N[ii * 3] * tt,
                 S.P[ii * 3 + 1] + S.N[ii * 3 + 1] * tt,
                 S.P[ii * 3 + 2] + S.N[ii * 3 + 2] * tt);
        colFn(ii, c);
        col.push(c.r, c.g, c.b, s);
      }
    }
    if (!tri) return null;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 4));
    g.computeVertexNormals();
    return g;
  }

  /* bearing round the head's vertical axis with the SEAM AT THE FACE: 0 = the
     back centre, ±π = straight ahead. The first build seamed at ±π = atan2's
     wrap, which put an open slit down the middle of the back of every fall. */
  function bearing(M, x, z) { return Math.atan2(x, -M.fwd * (z - M.zc)); }
  function binOf(th, BINS) {
    var b = Math.floor((th + Math.PI) / (2 * Math.PI) * BINS);
    return b < 0 ? 0 : (b >= BINS ? BINS - 1 : b);
  }

  /* the silhouette of the body between two heights, as a max radius per
     (height, bearing) cell about the head's own vertical axis. The curtain
     rides on it: hair hung straight down from the ear line is narrower than
     the neck and the shoulders and disappears inside the torso the moment it
     passes them, which is why the first build showed no hair at all below the
     jaw. */
  function bodyProfile(S, M, yLo, yHi, BINS) {
    var YB = 48, span = Math.max(1e-4, yHi - yLo);
    var R = new Float64Array(YB * BINS);
    var i, x, z, y, r, b, yb;
    for (i = 0; i < S.count; i++) {
      y = S.P[i * 3 + 1];
      if (y < yLo || y > yHi) continue;
      x = S.P[i * 3] - M.cx; z = S.P[i * 3 + 2] - M.zc;
      r = Math.sqrt(x * x + z * z);
      b = binOf(bearing(M, x, S.P[i * 3 + 2]), BINS);
      yb = Math.floor((y - yLo) / span * YB);
      if (yb < 0) yb = 0; if (yb >= YB) yb = YB - 1;
      if (r > R[yb * BINS + b]) R[yb * BINS + b] = r;
    }
    /* a cell with nothing in it borrows from its nearest neighbour in bearing */
    for (yb = 0; yb < YB; yb++) {
      for (b = 0; b < BINS; b++) {
        if (R[yb * BINS + b] > 0) continue;
        for (var d = 1; d < BINS; d++) {
          var l = R[yb * BINS + (b - d + BINS) % BINS], rr = R[yb * BINS + (b + d) % BINS];
          if (l > 0 || rr > 0) { R[yb * BINS + b] = Math.max(l, rr); break; }
        }
      }
    }
    return function (yy, bin) {
      var k = Math.floor((yy - yLo) / span * YB);
      if (k < 0) k = 0; if (k >= YB) k = YB - 1;
      return R[k * BINS + bin];
    };
  }

  /* the curtain: the cap's lower back boundary, extruded to targetY with a
     small outward flare, pushed out to clear the body it falls past. An
     INDEXED grid so computeVertexNormals averages across the strip and it
     shades as one smooth sheet, not forty-eight flat pleats. cutF = how far
     forward (along the face axis, metres from the head centre) the ring may
     reach: medium hair hangs BEHIND the ears, longer hair falls past them.
     The hem is rounded — longest at the back centre, lifting towards the
     sides — and the last stretch thins out through the vertex alpha. */
  function fall(S, sel, M, targetY, colour, cutF) {
    var BINS = 48, SEG = 16, FLARE = 0.04, CLEAR = 0.008, WIDEST = 1.45;
    var bestR = new Float64Array(BINS), bx = new Float64Array(BINS),
        by = new Float64Array(BINS), bz = new Float64Array(BINS);
    var got = new Uint8Array(BINS);
    var lo = M.earY - 0.10 * M.headH, hi = M.earY + 0.09 * M.headH;
    var i, x, y, z, f, r, b;
    for (i = 0; i < S.count; i++) {
      if (!sel[i]) continue;
      y = S.P[i * 3 + 1];
      if (y < lo || y > hi) continue;
      f = M.fwd * (S.P[i * 3 + 2] - M.zc);
      if (f > cutF) continue;
      x = S.P[i * 3] - M.cx; z = S.P[i * 3 + 2] - M.zc;
      r = Math.sqrt(x * x + z * z);
      b = binOf(bearing(M, x, S.P[i * 3 + 2]), BINS);
      if (!got[b] || r > bestR[b]) {
        got[b] = 1; bestR[b] = r;
        bx[b] = S.P[i * 3]; by[b] = y; bz[b] = S.P[i * 3 + 2];
      }
    }
    var ring = [];
    for (b = 0; b < BINS; b++) if (got[b]) ring.push(b);
    if (ring.length < 3) return null;

    var ringMaxY = -Infinity;
    for (i = 0; i < ring.length; i++) if (by[ring[i]] > ringMaxY) ringMaxY = by[ring[i]];
    var prof = bodyProfile(S, M, targetY - 0.05, ringMaxY, BINS);
    var lift = 0.10 * M.headH;                  /* hem rise from the back centre to the sides */

    var pos = [], col = [], idx = [];
    var cr = colour.r, cg = colour.g, cb = colour.b;
    var stationOf = {};
    function station(b) {
      if (stationOf[b] !== undefined) return stationOf[b];
      var dx = bx[b] - M.cx, dz = bz[b] - M.zc;
      var r0 = Math.sqrt(dx * dx + dz * dz) || 1e-6;
      var th = (b + 0.5) / BINS * 2 * Math.PI - Math.PI;     /* 0 = back centre */
      var hemY = targetY + lift * (1 - Math.cos(th)) * 0.5;
      var base = pos.length / 3;
      for (var s = 0; s <= SEG; s++) {
        var k = s / SEG;
        var yy = by[b] + (hemY - by[b]) * k;
        var rr = r0 * (1 + FLARE * k);
        var br = prof(yy, b) + CLEAR;
        if (br > rr) rr = br;
        /* …but no further than half again the head's own radius. Unclamped,
           the profile of the shoulders and the arms drags the curtain out to
           the width of the body and the fall reads as a cape, not as hair. */
        if (rr > r0 * WIDEST) rr = r0 * WIDEST;
        pos.push(M.cx + dx / r0 * rr, yy, M.zc + dz / r0 * rr);
        var a = k < 0.85 ? 1 : 1 - 0.6 * (k - 0.85) / 0.15;
        col.push(cr, cg, cb, a);
      }
      stationOf[b] = base;
      return base;
    }
    for (var q = 0; q + 1 < ring.length; q++) {
      var b0 = ring[q], b1 = ring[q + 1];
      if (b1 - b0 > 2) continue;                 /* the gap where the face is */
      var s0 = station(b0), s1 = station(b1);
      for (var sg = 0; sg < SEG; sg++) {
        idx.push(s0 + sg, s1 + sg, s1 + sg + 1, s0 + sg, s1 + sg + 1, s0 + sg + 1);
      }
    }
    if (!idx.length) return null;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 4));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }

  /* Two ribbons laid ON the face. The first build was two flat boxes placed
     at the front-most vertex of a band and pushed forward by a fifth of their
     depth: a box is straight and a forehead is not, so the inner ends floated
     clear of the skin and the outer ends hung in the air in front of the
     temples. Now each brow is sampled along its length: at every station the
     nearest front-facing skin vertex gives the surface point AND its normal,
     the ribbon's outer face sits that vertex's normal * t off the skin, and
     its top and bottom walls run back to the skin, so the strip follows the
     curve of the brow ridge round to the temple.
     Anchor: the eye meshes (centre + diameter), else head fractions. */
  function surfaceAt(S, M, x, y, x0, x1) {
    var best = -1, bd = Infinity, i, px, py, f;
    for (i = 0; i < S.count; i++) {
      py = S.P[i * 3 + 1];
      if (Math.abs(py - y) > 0.06 * M.headH) continue;
      px = S.P[i * 3];
      if (px < x0 || px > x1) continue;
      f = M.fwd * (S.P[i * 3 + 2] - M.zc);
      if (f < M.fmin + 0.5 * M.depth) continue;              /* the front half */
      if (M.fwd * S.N[i * 3 + 2] < 0.2) continue;             /* facing forward */
      var d = (px - x) * (px - x) + (py - y) * (py - y);
      if (d < bd) { bd = d; best = i; }
    }
    if (best < 0) return null;
    return { p: [S.P[best * 3], S.P[best * 3 + 1], S.P[best * 3 + 2]],
             n: [S.N[best * 3], S.N[best * 3 + 1], S.N[best * 3 + 2]] };
  }
  function browAnchors(M, w) {
    var b = w.brow, scale = 1;
    if (/thick|bold|strong|heavy/.test(b)) scale = 1.4;
    else if (/bushy/.test(b)) scale = 1.7;
    else if (/thin|sparse|fine/.test(b)) scale = 0.6;
    var arched = /arch/.test(b), angled = /angl|angry|stern|furrow/.test(b);
    var eyes = eyeAnchors(CS3_HAIR_CTX.model);
    var anchors;
    if (eyes.length === 2) {
      anchors = eyes.map(function (e) {
        /* the brow sits ~0.85 eyeball diameters above the eye's centre and is
           a little under two diameters long. It is HAIR on skin, so the
           ribbon is thin (~1.6 mm on a 2.7 cm eye): at 4 mm the first cut
           stood proud of the supraorbital ridge and read as a shelf. */
        return { x: e.x, y: e.y + 0.85 * e.d, halfW: 0.95 * e.d, halfH: 0.11 * e.d * scale, t: 0.06 * e.d, d: e.d };
      });
    } else {
      anchors = [-1, 1].map(function (sg) {
        return { x: M.cx + sg * 0.22 * M.headW, y: M.yTop - 0.46 * M.headH,
                 halfW: 0.11 * M.headW, halfH: 0.014 * M.headH * scale, t: 0.007 * M.headH, d: 0.12 * M.headH };
      });
    }
    anchors.forEach(function (A) {
      A.arch = function (u) {
        var yc = 0;
        if (arched) yc += 0.6 * A.halfH * (1 - Math.pow(u * 2 - 1, 2)) + 0.4 * A.halfH * u;
        if (angled) yc -= 0.8 * A.halfH * (1 - u);
        return yc;
      };
    });
    return anchors;
  }
  function brows(S, M, w, mat) {
    var out = [], k, sgn, u, i;

    var anchors = browAnchors(M, w);
    var N = 10;
    for (k = 0; k < 2; k++) {
      var A = anchors[k]; sgn = (A.x < M.cx) ? -1 : 1;
      var x0 = A.x - A.halfW - 0.02 * M.headW, x1 = A.x + A.halfW + 0.02 * M.headW;
      var pos = [], rows = [];
      for (i = 0; i <= N; i++) {
        u = i / N;                                   /* 0 = inner end (nose side) … 1 = temple */
        var x = A.x + sgn * (u * 2 - 1) * A.halfW;
        var yc = A.y + A.arch(u);
        var hh = A.halfH * (1 - 0.45 * u);         /* tapers towards the temple */
        var top = surfaceAt(S, M, x, yc + hh, x0, x1), bot = surfaceAt(S, M, x, yc - hh, x0, x1);
        if (!top || !bot) continue;
        rows.push({
          ti: top.p, to: [top.p[0] + top.n[0] * A.t, top.p[1] + top.n[1] * A.t, top.p[2] + top.n[2] * A.t],
          bi: bot.p, bo: [bot.p[0] + bot.n[0] * A.t, bot.p[1] + bot.n[1] * A.t, bot.p[2] + bot.n[2] * A.t]
        });
      }
      if (rows.length < 2) continue;
      function quad(p0, p1, p2, p3) {
        var v = [p0, p1, p2, p0, p2, p3], j;
        for (j = 0; j < 6; j++) pos.push(v[j][0], v[j][1], v[j][2]);
      }
      for (i = 0; i + 1 < rows.length; i++) {
        var a = rows[i], c = rows[i + 1];
        quad(a.bo, c.bo, c.to, a.to);               /* the face */
        quad(a.ti, c.ti, c.to, a.to);               /* top wall, back to the skin */
        quad(a.bi, a.bo, c.bo, c.bi);               /* bottom wall */
      }
      /* end caps */
      var f0 = rows[0], fl = rows[rows.length - 1];
      quad(f0.bi, f0.bo, f0.to, f0.ti);
      quad(fl.bi, fl.ti, fl.to, fl.bo);
      var g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.computeVertexNormals();
      var m = new THREE.Mesh(g, mat);
      m.name = 'cs-brow-' + (sgn < 0 ? 'L' : 'R');
      out.push(m);
    }
    return out;
  }

  /* ── strands ──────────────────────────────────────────────────────────────
     2026-09-19. The cap used to be ONE shell: the scalp triangles pushed out
     2 cm and shaded as a smooth surface, which reads as a helmet from any
     angle and shows the hairline as a hard stair-stepped line. Hair is now a
     thin dark scalp shell (so skin never shows between the roots) with
     thousands of ribbon STRANDS grown from it. Each strand starts on a scalp
     triangle, lifts off along the skin normal, bends into a groom (back over
     the top, down the sides, a whorl at the crown, the fringe swept to one
     side), is pulled down by a gravity that grows with the length, wavers or
     coils with the texture, and is kept off the skin by a spatial hash of the
     body's vertices. The ribbons carry the SKIN's normal at their nearest
     point, so they shade as one soft volume rather than as flat cards, and
     every strand gets its own shade of the colour: that is what makes it
     read as hair rather than as paint. */
  var STRAND = {
    /* lengths in head heights: [min, max] for the top of the head, the sides
       and the nape; seg = ribbon segments; density = strands per m² of
       scalp; width in metres at the root; lift = how much of the root normal
       the strand starts along; gravity = downward pull growing along it;
       earTrim = a strand that reaches the auricle stops there (a cut that is
       trimmed round the ears; longer hair falls over them); max = strand cap */
    'shaved': { top: [0.012, 0.016], side: [0.010, 0.014], nape: [0.008, 0.012], seg: 3,
                density: 450000, width: 0.0011, lift: 0.95, gravity: 0.1, earTrim: true, max: 15000, clear: 0.02 },
    'short':  { top: [0.15, 0.24], side: [0.06, 0.12], nape: [0.04, 0.08], seg: 7,
                density: 300000, width: 0.0024, lift: 0.30, gravity: 0.7, earTrim: true, max: 15000, clear: 0.014 },
    'medium': { top: [0.42, 0.58], side: [0.40, 0.55], nape: [0.32, 0.45], seg: 11,
                density: 230000, width: 0.0034, lift: 0.25, gravity: 1.4, max: 14000, clear: 0.012 },
    'shoulder': { top: [0.95, 1.25], side: [0.95, 1.25], nape: [0.85, 1.05], seg: 16,
                density: 200000, width: 0.0042, lift: 0.22, gravity: 2.0, max: 12000, clear: 0.012, clump: true },
    'long':   { top: [1.45, 1.85], side: [1.45, 1.85], nape: [1.3, 1.6], seg: 22,
                density: 190000, width: 0.0058, lift: 0.2, gravity: 2.4, max: 10000, clear: 0.013, clump: true },
    'waist-length': { top: [2.5, 3.1], side: [2.5, 3.1], nape: [2.3, 2.8], seg: 30,
                density: 180000, width: 0.0068, lift: 0.18, gravity: 2.8, max: 8000, clear: 0.014, clump: true }
  };
  STRAND['waist length'] = STRAND['waist-length'];
  /* facial hair: lengths in METRES (len), flow straight down the face */
  var BEARD_STRAND = {
    'stubble':     { len: [0.0015, 0.003], seg: 3, density: 600000, width: 0.0009, lift: 0.95, gravity: 0.1, beard: true, max: 9000 },
    'short beard': { len: [0.005, 0.010], seg: 5, density: 350000, width: 0.0014, lift: 0.6, gravity: 0.5, beard: true, max: 9000 },
    'full beard':  { len: [0.014, 0.026], seg: 7, density: 260000, width: 0.0018, lift: 0.45, gravity: 0.9, beard: true, max: 9000 },
    'goatee':      { len: [0.007, 0.013], seg: 5, density: 320000, width: 0.0015, lift: 0.55, gravity: 0.6, beard: true, max: 9000 },
    'moustache':   { len: [0.006, 0.011], seg: 5, density: 320000, width: 0.0015, lift: 0.55, gravity: 0.6, beard: true, max: 9000 },
    'beard':       { len: [0.007, 0.013], seg: 5, density: 320000, width: 0.0015, lift: 0.55, gravity: 0.6, beard: true, max: 9000 }
  };
  var STRAND_MAX = 15000;
  var HL_FEATHER = 0.007;      /* density ramps up over this distance inside the hairline */
  var BABY = 0.008;            /* within this of the hairline strands are short and fine */
  var SCALP_T = 0.0022;        /* the dark scalp shell under the strands */

  /* The ribbons are double-sided, and three's DOUBLE_SIDED shader negates
     the normal on every back-facing fragment — which for a ribbon carrying
     the SKIN's normal means half the strands, whichever way they happen to
     be wound, shaded as if they faced into the skull and caught the blue
     fill light from behind as grey streaks. The flip is dropped here: the
     normal attribute is the intended one on both faces. */
  function hairMaterial(rough) {
    var m = new THREE.MeshStandardMaterial({
      color: 0xffffff, vertexColors: true, roughness: rough, metalness: 0, side: THREE.DoubleSide
    });
    m.onBeforeCompile = function (shader) {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <normal_fragment_begin>',
        THREE.ShaderChunk.normal_fragment_begin.replace('normal = normal * faceDirection;',
          /* a strand seen from behind its skin normal is mirrored to the
             viewer's side and bent a little towards the eye: at N·V ≈ 0 the
             GGX visibility term blows up and the ribbon rendered as a white
             streak whatever its colour */
          'vec3 csVV = normalize( vViewPosition ); float csNV = dot( normal, csVV );' +
          ' if ( csNV < 0.0 ) normal = normalize( normal - 2.0 * csNV * csVV );' +
          ' normal = normalize( normal + 0.25 * csVV );'));
    };
    m.customProgramCacheKey = function () { return 'cs-hair-noflip'; };
    m.userData.csKey = 'hair';
    /* THE WIDTH FLOOR. Measured on this GPU: a hair ribbon covers 0.37 px at
       the default framing, and SIXTEEN overlapping sub-pixel opaque ribbons
       resolve to exactly the same ink as ONE — coverage saturates, so 15,000
       strands paint no more hair than a few hundred. char_0_strand_width.js
       widens each ribbon to a 1.3 px floor and scales its alpha by the ratio,
       which both stops the dropout and lets overlapping strands accumulate.
       It also flips the material to blended with depthWrite off, because r147
       clamps alpha to 1 for an opaque material (output_fragment's OPAQUE
       branch) and because with depthWrite on the 16-strand case measured back
       down to a single strand's ink. Composes with the normal-flip patch
       above rather than replacing it. Absent (bundle order changed), the
       material is exactly what it was. */
    if (window.CSSTRAND) CSSTRAND.patch(m, { minPx: 1.3 });
    return m;
  }
  function strandSpec(w) {
    if (w.hairline === 'fully bald') return null;
    return STRAND[w.length] || STRAND.long;
  }

  /* a spatial hash of every body vertex, for "nearest skin point" queries */
  function skinHash(S, cell) {
    var K = 1 << 10, map = new Map(), i;
    function key(ix, iy, iz) { return ((ix & (K - 1)) * K + (iy & (K - 1))) * K + (iz & (K - 1)); }
    for (i = 0; i < S.count; i++) {
      var k = key(Math.floor(S.P[i * 3] / cell), Math.floor(S.P[i * 3 + 1] / cell), Math.floor(S.P[i * 3 + 2] / cell));
      var a = map.get(k);
      if (a) a.push(i); else map.set(k, [i]);
    }
    /* nearest vertex to (x,y,z) within one cell in every direction: index or -1 */
    return function (x, y, z) {
      var ix = Math.floor(x / cell), iy = Math.floor(y / cell), iz = Math.floor(z / cell);
      var best = -1, bd = Infinity;
      for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) for (var dz = -1; dz <= 1; dz++) {
        var a = map.get(key(ix + dx, iy + dy, iz + dz));
        if (!a) continue;
        for (var j = 0; j < a.length; j++) {
          var ii = a[j];
          var ex = S.P[ii * 3] - x, ey = S.P[ii * 3 + 1] - y, ez = S.P[ii * 3 + 2] - z;
          var d = ex * ex + ey * ey + ez * ez;
          if (d < bd) { bd = d; best = ii; }
        }
      }
      return best;
    };
  }

  /* fast deterministic random: the same head of hair on every rebuild */
  function rngOf(seed) {
    var s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }

  /* the groom: where hair on a given point of the scalp wants to go, as a
     unit vector in the scalp's tangent plane. Coordinates: rx right of the
     head centre, f forward along the face axis, yt head-heights below the
     crown; N = the skin normal there. */
  function flowAt(M, rx, y, f, N, out, w, de) {
    var yt = (M.yTop - y) / M.headH;
    var ny = N.y;
    var up = Math.max(0, Math.min(1, ny));              /* 1 on the crown, 0 on the sides */
    var back = -M.fwd;                                   /* z sign that points backwards */
    var frontness = (f - M.fmin) / M.depth;              /* 1 at the face */
    var bear = Math.abs(Math.atan2(rx, f)) * 180 / Math.PI;
    var wb = 0.35 + 0.65 * up, wd = 0.15 + 0.85 * (1 - up);
    var ox = 0, oy = -wd, oz = back * wb;
    /* the fringe: short hair is swept across to the right and back; longer
       hair is combed back over the top and to the side, so it falls down
       the sides and the back, not down over the face */
    if (frontness > 0.55 && yt < 0.42 && bear < 60) {
      var k = (frontness - 0.55) / 0.45;
      if (w.length === 'short' || w.length === 'shaved') { ox += 0.9 * k; oz += back * 0.4 * k; oy += 0.25 * k; }
      else { ox += 0.55 * k; oz += back * 1.3 * k; oy += 0.9 * k; }
    }
    /* the crown whorl: a clockwise swirl about a point on the top-back */
    var wx = 0.08 * M.headW, wf = M.fmin + 0.30 * M.depth;
    var dx = rx - wx, df = f - wf, dist = Math.sqrt(dx * dx + df * df);
    var ww = Math.exp(-(dist * dist) / (0.03 * 0.03)) * 1.4 * up;
    if (ww > 0.01) { ox += -df / (dist + 1e-6) * ww; oz += M.fwd * (dx / (dist + 1e-6)) * ww; }
    /* round the ear the hair is combed BACK, clear of the auricle */
    if (de !== undefined && de < 0.03) { var ek = 1 - de / 0.03; oz += back * 1.6 * ek; oy *= (1 - 0.7 * ek); }
    /* longer hair: gravity dominates everywhere but the very top */
    if (w.length !== 'short') { oy -= 0.8 * (1 - up); }
    /* into the tangent plane */
    var d = ox * N.x + oy * N.y + oz * N.z;
    ox -= d * N.x; oy -= d * N.y; oz -= d * N.z;
    var L = Math.sqrt(ox * ox + oy * oy + oz * oz);
    if (L < 0.05) { ox = 0; oy = 0; oz = back; d = oz * N.z; ox -= d * N.x; oy -= d * N.y; oz -= d * N.z; L = Math.sqrt(ox * ox + oy * oy + oz * oz) || 1; }
    out.set(ox / L, oy / L, oz / L);
    return out;
  }

  /* per-root length in head heights: long on top, short at the sides and
     the nape, with the texture's spread */
  function strandLen(spec, M, yt, N, rnd, deg) {
    var up = Math.max(0, Math.min(1, N.y));
    var top = spec.top, side = spec.side, nape = spec.nape;
    var r = rnd();
    var lt = top[0] + (top[1] - top[0]) * r, ls = side[0] + (side[1] - side[0]) * r, ln = nape[0] + (nape[1] - nape[0]) * r;
    var napeK = (deg > 120 && yt > 0.55) ? Math.min(1, (yt - 0.55) / 0.25) : 0;
    var L = lt * up + ls * (1 - up);
    L = L * (1 - napeK) + ln * napeK;
    return L * M.headH;
  }

  /* build every strand ribbon into one indexed geometry.
     S = body sample, D = scalp field, M = head metrics, spec = STRAND[...],
     w = wants, colOf(rnd, i, x, y) → THREE.Color for a strand rooted at vertex i */
  function strands(S, D, M, spec, w, colOf, near) {
    var rnd = rngOf(0x51ed27 + (w.length.length << 8));
    var texture = w.texture;
    var wave = (texture === 'wavy') ? 1 : 0;
    var curl = (texture === 'curly' || texture === 'coily' || texture === 'kinky') ? (texture === 'wavy' ? 0 : 1) : 0;
    var tight = (texture === 'coily' || texture === 'kinky');
    /* segments: a curl needs ~8 per turn or it renders as a zigzag of shards,
       so the count grows with the turns the longest strand makes — and the
       strand cap shrinks to keep the whole head under a vertex budget */
    var SEG = spec.seg + (curl ? 4 : 0);
    if (curl || wave) {
      var maxL = spec.len ? spec.len[1] : (spec.top[1] * M.headH * (curl ? 1.5 : 1));
      var period = wave ? 0.09 : (tight ? 0.025 : 0.045);
      SEG = Math.max(SEG, Math.ceil(maxL / period * (wave ? 5 : 8)));
    }
    var MAXN = spec.max || STRAND_MAX;
    var budget = Math.floor(620000 / ((SEG + 1) * 2));
    if (budget < MAXN) MAXN = budget;
    var widthMul = curl ? Math.sqrt((spec.max || STRAND_MAX) / MAXN) : 1;   /* fewer, wider clumps */
    var i0, i1, i2, a, k;

    /* how many strands: scalp area × density, capped */
    var tris = [], areas = [], total = 0;
    var ax = new THREE.Vector3(), bx = new THREE.Vector3(), cx = new THREE.Vector3();
    for (a = 0; a + 2 < S.idx.length; a += 3) {
      i0 = S.idx[a]; i1 = S.idx[a + 1]; i2 = S.idx[a + 2];
      if (D[i0] <= 0 && D[i1] <= 0 && D[i2] <= 0) continue;
      ax.set(S.P[i0 * 3], S.P[i0 * 3 + 1], S.P[i0 * 3 + 2]);
      bx.set(S.P[i1 * 3], S.P[i1 * 3 + 1], S.P[i1 * 3 + 2]).sub(ax);
      cx.set(S.P[i2 * 3], S.P[i2 * 3 + 1], S.P[i2 * 3 + 2]).sub(ax);
      var area = bx.cross(cx).length() * 0.5;
      var dm = (D[i0] + D[i1] + D[i2]) / 3;
      var fade = dm / HL_FEATHER; if (fade < 0) fade = 0; else if (fade > 1) fade = 1;
      fade = fade * fade * (3 - 2 * fade);
      fade = 0.55 + 0.45 * fade;                         /* still most of the hairs at the very edge */
      tris.push(a); areas.push(area * fade); total += area * fade;
    }
    if (!tris.length) return null;
    var density = spec.density;
    if (total * density > MAXN) density = MAXN / total;

    var pos = [], nrm = [], col = [], idx = [], edg = [];
    var P = new THREE.Vector3(), N = new THREE.Vector3(), F = new THREE.Vector3();
    var dir = new THREE.Vector3(), tgt = new THREE.Vector3(), B = new THREE.Vector3();
    var jitter = new THREE.Vector3(), skinN = new THREE.Vector3(), tmpv = new THREE.Vector3(), F2 = new THREE.Vector3();
    var down = new THREE.Vector3(0, -1, 0);
    var c = new THREE.Color();
    var count = 0, t, u, v, wgt0, wgt1, wgt2;
    var pts = new Float32Array((SEG + 1) * 3), tans = new Float32Array((SEG + 1) * 3), nrms = new Float32Array((SEG + 1) * 3);

    for (t = 0; t < tris.length; t++) {
      a = tris[t];
      var want = areas[t] * density, n = Math.floor(want);
      if (rnd() < want - n) n++;
      i0 = S.idx[a]; i1 = S.idx[a + 1]; i2 = S.idx[a + 2];
      for (k = 0; k < n; k++) {
        if (count >= MAXN) break;
        u = rnd(); v = rnd(); if (u + v > 1) { u = 1 - u; v = 1 - v; }
        wgt0 = 1 - u - v; wgt1 = u; wgt2 = v;
        var d = D[i0] * wgt0 + D[i1] * wgt1 + D[i2] * wgt2;
        if (d <= 0) continue;
        P.set(S.P[i0 * 3] * wgt0 + S.P[i1 * 3] * wgt1 + S.P[i2 * 3] * wgt2,
              S.P[i0 * 3 + 1] * wgt0 + S.P[i1 * 3 + 1] * wgt1 + S.P[i2 * 3 + 1] * wgt2,
              S.P[i0 * 3 + 2] * wgt0 + S.P[i1 * 3 + 2] * wgt1 + S.P[i2 * 3 + 2] * wgt2);
        N.set(S.N[i0 * 3] * wgt0 + S.N[i1 * 3] * wgt1 + S.N[i2 * 3] * wgt2,
              S.N[i0 * 3 + 1] * wgt0 + S.N[i1 * 3 + 1] * wgt1 + S.N[i2 * 3 + 1] * wgt2,
              S.N[i0 * 3 + 2] * wgt0 + S.N[i1 * 3 + 2] * wgt1 + S.N[i2 * 3 + 2] * wgt2).normalize();
        var rx = P.x - M.cx, f = M.fwd * (P.z - M.zc);
        var yt = (M.yTop - P.y) / M.headH;
        var deg = Math.abs(Math.atan2(rx, f)) * 180 / Math.PI;
        var de = spec.beard ? 1 : earDist(M.ear, rx, P.y, P.z);
        var L, grav = spec.gravity, fringeK = 1;
        if (spec.beard) {
          /* facial hair grows down the face, a little outward at the root */
          F.copy(down); var dnn = F.dot(N); F.addScaledVector(N, -dnn);
          if (F.lengthSq() < 0.01) F.set(0, -1, 0); F.normalize();
          L = spec.len[0] + (spec.len[1] - spec.len[0]) * rnd();
        } else {
          flowAt(M, rx, P.y, f, N, F, w, de);
          L = strandLen(spec, M, yt, N, rnd, deg);
          /* trimmed round the ears: nothing rooted within 2 cm of the auricle
             keeps its full length */
          if (spec.earTrim && de < 0.02) L *= 0.45 + 0.55 * (de / 0.02);

          /* the fringe of longer hair: no gravity until it is over the top */
          var frontness = (f - M.fmin) / M.depth;
          if (!spec.earTrim && frontness > 0.55 && yt < 0.42 && deg < 60) fringeK = 0.3;
        }
        var width = spec.width * widthMul * (0.7 + 0.6 * rnd());
        var baby = d < BABY;
        if (baby) { L *= 0.45 + 0.45 * (d / BABY); width *= 0.75; }
        var lift = spec.lift * (0.7 + 0.6 * rnd()) * (curl ? 1.5 : 1);
        if (baby) lift *= 0.5;
        /* flyaways: a few fine, lighter strands standing further off the head
           soften the silhouette */
        var fly = (!baby && rnd() < 0.07);
        if (fly) { width *= 0.45; lift *= 2.2; L *= 1.15; }
        var h = L / SEG;
        /* a per-strand random lean, so neighbours do not run parallel */
        jitter.set(rnd() - 0.5, rnd() - 0.5, rnd() - 0.5).multiplyScalar(0.35);
        var phase = rnd() * Math.PI * 2, amp = 0;
        if (wave) amp = Math.min(0.012, 0.08 * L); else if (curl) amp = Math.min(tight ? 0.008 : 0.013, (tight ? 0.07 : 0.12) * L);
        if (spec.beard) amp *= 0.5;
        /* periods in METRES, so a long strand has many turns and a short one
           a fraction of one — a wave every 9 cm, a curl every 4.5, a coil every 2.5 */
        var freq = L / (wave ? 0.09 : (tight ? 0.025 : 0.045));
        if (freq < 0.5) freq = 0.5;
        var wavePrev = 0, curlPrev = 0;

        dir.copy(N).multiplyScalar(lift).addScaledVector(F, 1 - lift).add(jitter).normalize();
        pts[0] = P.x + N.x * 0.0006; pts[1] = P.y + N.y * 0.0006; pts[2] = P.z + N.z * 0.0006;
        tans[0] = dir.x; tans[1] = dir.y; tans[2] = dir.z;
        nrms[0] = N.x; nrms[1] = N.y; nrms[2] = N.z;
        var px = pts[0], py = pts[1], pz = pts[2];
        skinN.copy(N);
        var cut = -1;
        for (var s = 1; s <= SEG; s++) {
          if (cut >= 0) { pts[s * 3] = px; pts[s * 3 + 1] = py; pts[s * 3 + 2] = pz; tans[s * 3] = tans[cut * 3]; tans[s * 3 + 1] = tans[cut * 3 + 1]; tans[s * 3 + 2] = tans[cut * 3 + 2]; nrms[s * 3] = skinN.x; nrms[s * 3 + 1] = skinN.y; nrms[s * 3 + 2] = skinN.z; continue; }
          var kk = s / SEG;
          var gEff = grav * (fringeK + (1 - fringeK) * Math.min(1, kk * 1.6));
          tgt.copy(F).addScaledVector(down, gEff * kk).add(jitter).normalize();
          dir.lerp(tgt, 0.32).normalize();
          px += dir.x * h; py += dir.y * h; pz += dir.z * h;
          if (amp) {
            /* lateral wave / coil: B = across the strand, skinN = off the skin */
            B.crossVectors(dir, skinN).normalize();
            /* the wave is a bounded offset: each step moves by the CHANGE in
               amp·sin, so the strand swings ±amp about its path instead of
               drifting off on a random walk (the first build's mop) */
            var ph = phase + kk * Math.PI * 2 * freq;
            var wv = Math.sin(ph) * amp, dv = wv - wavePrev; wavePrev = wv;
            px += B.x * dv; py += B.y * dv; pz += B.z * dv;
            if (curl) { var cv = Math.cos(ph) * amp * 0.6, dc = cv - curlPrev; curlPrev = cv; px += skinN.x * dc; py += skinN.y * dc; pz += skinN.z * dc; }
          }
          /* keep it off the skin — and ON the head: a strand that keeps its
             root tangent flies off the skull in a straight line (the first
             medium build was a hedgehog), so past a clearance it is pulled
             back in, and its flow is re-read at the skin under it, which is
             what makes hair lie along the head and then down the neck */
          var ni = near(px, py, pz);
          if (ni >= 0) {
            skinN.set(S.N[ni * 3], S.N[ni * 3 + 1], S.N[ni * 3 + 2]);
            var gap = 0.0015 + width * 0.5;
            var dd = (px - S.P[ni * 3]) * skinN.x + (py - S.P[ni * 3 + 1]) * skinN.y + (pz - S.P[ni * 3 + 2]) * skinN.z;
            if (dd < gap) { px += skinN.x * (gap - dd); py += skinN.y * (gap - dd); pz += skinN.z * (gap - dd); }
            /* over the ear, never in it: longer hair that reaches the auricle
               is lifted outside its outer edge (short cuts are trimmed below) */
            if (!spec.earTrim && !spec.beard && M.ear && S.earV && S.earV[ni]) {
              var needX = M.ear.ro + gap + 0.002, axx = Math.abs(px - M.cx);
              if (axx < needX) px = M.cx + (px >= M.cx ? needX : -needX);
            }
            else if (!spec.beard && !fly && spec.clear && dd > spec.clear) {
              var pull = (dd - spec.clear) * 0.7;
              px -= skinN.x * pull; py -= skinN.y * pull; pz -= skinN.z * pull;
            }
            if (!spec.beard && !fly) {
              var sy = S.P[ni * 3 + 1];
              if (sy < M.chinY) { F2.copy(down); }
              else {
                flowAt(M, S.P[ni * 3] - M.cx, sy, M.fwd * (S.P[ni * 3 + 2] - M.zc), skinN, F2, w,
                       earDist(M.ear, S.P[ni * 3] - M.cx, sy, S.P[ni * 3 + 2]));
              }
              F.lerp(F2, 0.5).normalize();
            }
          }
          /* the ear arch: a strand that reaches the auricle is trimmed there */
          /* 2026-09-20: the cut is CONTACT with the auricle (nearest skin vertex
             is an ear vertex) or standing proud of it. Measured and rejected:
             a length cap on roots above the ear (bare notch), and a cut at the
             ear's (y,z) capsule (a bare rectangle — the skull above the auricle
             root lies inside that box and its roots were cut at segment 1) */
          if (spec.earTrim && M.ear && (earHit(M.ear, px - M.cx, py, pz) || (ni >= 0 && S.earV && S.earV[ni]))) {
            cut = s - 1; px = pts[cut * 3]; py = pts[cut * 3 + 1]; pz = pts[cut * 3 + 2];
            pts[s * 3] = px; pts[s * 3 + 1] = py; pts[s * 3 + 2] = pz;
            tans[s * 3] = tans[cut * 3]; tans[s * 3 + 1] = tans[cut * 3 + 1]; tans[s * 3 + 2] = tans[cut * 3 + 2];
            nrms[s * 3] = skinN.x; nrms[s * 3 + 1] = skinN.y; nrms[s * 3 + 2] = skinN.z;
            continue;
          }
          pts[s * 3] = px; pts[s * 3 + 1] = py; pts[s * 3 + 2] = pz;
          tans[s * 3] = px - pts[s * 3 - 3]; tans[s * 3 + 1] = py - pts[s * 3 - 2]; tans[s * 3 + 2] = pz - pts[s * 3 - 1];
          nrms[s * 3] = skinN.x; nrms[s * 3 + 1] = skinN.y; nrms[s * 3 + 2] = skinN.z;
        }
        if (cut === 0) continue;                       /* rooted against the ear: nothing to draw */
        /* the ribbon */
        colOf(rnd, i0, P.x, P.y, c);
        if (fly) c.multiplyScalar(1.18);
        var base = pos.length / 3;
        for (s = 0; s <= SEG; s++) {
          var kk2 = s / SEG;
          tmpv.set(tans[s * 3], tans[s * 3 + 1], tans[s * 3 + 2]).normalize();
          skinN.set(nrms[s * 3], nrms[s * 3 + 1], nrms[s * 3 + 2]);
          B.crossVectors(tmpv, skinN);
          if (B.lengthSq() < 1e-8) B.crossVectors(tmpv, down);
          B.normalize();
          /* a clump (long hair) keeps its width almost to the tip */
          var ww = spec.clump
            ? width * (kk2 < 0.8 ? 1 - 0.1 * kk2 : 0.92 * (1 - (kk2 - 0.8) / 0.2))
            : width * (kk2 < 0.65 ? 1 - 0.25 * kk2 : 0.84 * (1 - (kk2 - 0.65) / 0.35));
          if (cut >= 0 && s > cut) ww = 0.00002;         /* collapsed past the trim */
          if (ww < 0.00005 && !(cut >= 0 && s > cut)) ww = 0.00005;
          var hx = B.x * ww * 0.5, hy = B.y * ww * 0.5, hz = B.z * ww * 0.5;
          pos.push(pts[s * 3] - hx, pts[s * 3 + 1] - hy, pts[s * 3 + 2] - hz,
                   pts[s * 3] + hx, pts[s * 3 + 1] + hy, pts[s * 3 + 2] + hz);
          /* the width floor (char_0_strand_width.js) needs the axis this ribbon
             widens along and the SIGNED offset each edge sits at. NOTE `ww` is
             the FULL width here while browStrands() and char_lashes.js both
             call their own `ww` the HALF width — the three writers disagree, so
             only the offset actually emitted above can be trusted. */
          edg.push(B.x, B.y, B.z, -ww * 0.5, B.x, B.y, B.z, ww * 0.5);
          /* Shade with the skin's normal blended a little towards the ribbon's
             own tilt, so a strand standing off the head still turns with it.

             2026-09-23, SIGN FIX. This read tmpv.cross(B) = T x (T x N), which
             expands to T(T.N) - N: for a strand lying along the scalp T.N ~ 0,
             so it is ~ -N and the 0.2 term SUBTRACTED. Measured over 20,000
             sampled (N,T) pairs across the real lift range: dot(fn, N) was
             negative in 20,000 of 20,000, and the blended normal ended up a
             median 4.6 deg (max 14.5 deg) from the plain skin normal — the
             tilt the comment promises was never applied. The outward ribbon
             normal is B x T = N - T(T.N). Honest about the size of it: with
             the sign right the tilt is still small, because a ribbon lying on
             the scalp genuinely does face the way the scalp faces. Hair reads
             as a painted mass because a flat ribbon under isotropic GGX is not
             a fibre, not because of this term; the cure for that is a fibre
             BRDF keyed on the TANGENT, which needs its own attribute. */
          var fn = B.clone().cross(tmpv).normalize();
          var nx = skinN.x * 0.8 + fn.x * 0.2, ny = skinN.y * 0.8 + fn.y * 0.2, nz = skinN.z * 0.8 + fn.z * 0.2;
          var nl = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
          nrm.push(nx / nl, ny / nl, nz / nl, nx / nl, ny / nl, nz / nl);
          /* roots a shade darker: the shadow of the neighbours */
          var sh = 0.84 + 0.16 * Math.min(1, kk2 * 2.2);
          col.push(c.r * sh, c.g * sh, c.b * sh, c.r * sh, c.g * sh, c.b * sh);
        }
        for (s = 0; s < SEG; s++) {
          var q = base + s * 2;
          idx.push(q, q + 1, q + 3, q, q + 3, q + 2);
        }
        count++;
      }
      if (count >= MAXN) break;
    }
    if (!count) return null;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    g.setAttribute('csEdge', new THREE.Float32BufferAttribute(edg, 4));
    g.setIndex(idx);
    g.userData.strands = count;
    return g;
  }

  /* brows as hair: ~150 fine strands per brow rooted along the arc, inner
     ones pointing up and out, outer ones out and down, lying almost flat on
     the skin. A thin ribbon underneath (browRibbon) keeps the brow legible
     from across the room, where 0.5 mm strands vanish. */
  function browStrands(S, M, anchors, browCol, near) {
    var rnd = rngOf(0xb70b5);
    var pos = [], nrm = [], col = [], idx = [], edg = [];
    var B = new THREE.Vector3(), T = new THREE.Vector3(), Nn = new THREE.Vector3(), tmp = new THREE.Vector3();
    var c = new THREE.Color();
    var SEG = 4, count = 0;
    for (var k = 0; k < anchors.length; k++) {
      var A = anchors[k], sgn = (A.x < M.cx) ? -1 : 1;
      var x0 = A.x - A.halfW - 0.02 * M.headW, x1 = A.x + A.halfW + 0.02 * M.headW;
      var nS = 640;
      for (var i = 0; i < nS; i++) {
        var u = rnd();                                    /* 0 = inner … 1 = temple */
        var x = A.x + sgn * (u * 2 - 1) * A.halfW * (1 + 0.08 * (rnd() - 0.5));
        var yc = A.y + (A.arch ? A.arch(u) : 0);
        var hh = A.halfH * (1 - 0.45 * u);
        var y = yc + (rnd() * 2 - 1) * hh * 1.1;
        var sp = surfaceAt(S, M, x, y, x0, x1);
        if (!sp) continue;
        Nn.set(sp.n[0], sp.n[1], sp.n[2]);
        /* direction along the brow: up-out at the head of the brow, out at the
           middle, out-and-down at the tail */
        var dy = u < 0.3 ? 0.9 - u : (u < 0.65 ? 0.25 : -0.55 * (u - 0.65) / 0.35 - 0.05);
        T.set(sgn * (0.5 + 0.6 * u), dy, 0);
        /* every hair at its own angle, ±20°, else they read as hatching */
        var ja = (rnd() - 0.5) * 0.7, ca = Math.cos(ja), sa = Math.sin(ja);
        T.set(T.x * ca - T.y * sa, T.x * sa + T.y * ca, 0);
        var dn = T.dot(Nn); T.addScaledVector(Nn, -dn).normalize();
        var curve = (rnd() - 0.5) * 0.25;                /* bends a little along its length */
        var L = A.d * (0.10 + 0.13 * rnd()), h = L / SEG, wdt = A.t * 0.42 * (0.8 + 0.5 * rnd());
        var px = sp.p[0] + Nn.x * 0.0004, py = sp.p[1] + Nn.y * 0.0004, pz = sp.p[2] + Nn.z * 0.0004;
        colOfBrow(rnd, browCol, c);
        var base = pos.length / 3;
        for (var s = 0; s <= SEG; s++) {
          var kk = s / SEG;
          if (s) {
            var lift = (s === 1) ? 0.22 : -0.06;
            if (s > 1) { var cb = Math.cos(curve), sb = Math.sin(curve); T.set(T.x * cb - T.y * sb, T.x * sb + T.y * cb, T.z); }
            tmp.copy(T).addScaledVector(Nn, lift).normalize();
            px += tmp.x * h; py += tmp.y * h; pz += tmp.z * h;
            var ni = near(px, py, pz);
            if (ni >= 0) {
              var nx = S.N[ni * 3], ny = S.N[ni * 3 + 1], nz = S.N[ni * 3 + 2];
              var dd = (px - S.P[ni * 3]) * nx + (py - S.P[ni * 3 + 1]) * ny + (pz - S.P[ni * 3 + 2]) * nz;
              var gap = 0.0006;
              if (dd < gap) { px += nx * (gap - dd); py += ny * (gap - dd); pz += nz * (gap - dd); }
            }
          }
          B.crossVectors(T, Nn).normalize();
          var ww = wdt * (1 - 0.8 * kk) * 0.5;      /* HALF width here, unlike strands() */
          pos.push(px - B.x * ww, py - B.y * ww, pz - B.z * ww, px + B.x * ww, py + B.y * ww, pz + B.z * ww);
          edg.push(B.x, B.y, B.z, -ww, B.x, B.y, B.z, ww);
          nrm.push(Nn.x, Nn.y, Nn.z, Nn.x, Nn.y, Nn.z);
          col.push(c.r, c.g, c.b, c.r, c.g, c.b);
        }
        for (s = 0; s < SEG; s++) { var q = base + s * 2; idx.push(q, q + 1, q + 3, q, q + 3, q + 2); }
        count++;
      }
    }
    if (!count) return null;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    g.setAttribute('csEdge', new THREE.Float32BufferAttribute(edg, 4));
    g.setIndex(idx);
    g.userData.strands = count;
    return g;
  }
  function colOfBrow(rnd, base, out) {
    var k = 0.75 + 0.5 * rnd();
    out.setRGB(base.r * k, base.g * k, base.b * k);
  }

  /* ── the build ────────────────────────────────────────────────────────── */

  /* A build context: which model, where the hair group goes, whose store
     holds .hair/.hairInfo, and how values are read. The studio's own is the
     default; Compare hands in a second one for the figure beside it. */
  var CS3_HAIR_CTX = null;
  function mainCtx() {
    return { model: CS3.model, parent: (CS3.model && CS3.model.parent) || CS3.scene,
             store: CS3, wants: readWants(), main: true };
  }

  function disposeHair(store) {
    var g = store.hair;
    if (!g) return;
    if (g.parent) g.parent.remove(g);
    g.traverse(function (o) {
      if (o.isMesh) {
        if (o.geometry) o.geometry.dispose();
        if (o.material && o.material.dispose) o.material.dispose();
      }
    });
    store.hair = null;
  }

  function credit(info) {
    var cr = document.getElementById('cs-credit');
    if (!cr) return;
    cr.title = info;
  }

  function buildFor(ctx) {
    var store = ctx.store;
    disposeHair(store);
    if (!ctx.model || !ctx.parent) return;
    /* the width floor needs the drawing buffer's height and the camera's fov
       once a frame. Installed off ctx.parent, not off CS3.scene: Compare
       builds its second figure into a scene of its own
       (char_file_compare.js), and a hook on one scene never runs for it. */
    if (window.CSSTRAND) {
      var sc = ctx.parent;
      while (sc && sc.parent) sc = sc.parent;
      if (sc && sc.isScene) CSSTRAND.install(sc);
    }
    CS3_HAIR_CTX = ctx;
    var mesh = bodyMesh(ctx.model);
    if (!mesh) return;
    var w = ctx.wants;
    var S = sampleBody(mesh);
    var M = headMetrics(S);
    if (!M) return;
    M.ear = earBox(S, M);

    /* An installed groom REPLACES the part it covers. char_hair_assets.js owns
       the asset and its fit; this only stops growing what would sit inside it.
       The thin dark scalp cap is deliberately kept under a hair asset: a card
       groom is a shell with gaps, and the skin shows through them. */
    var worn = (ctx.main && window.CSHAIRASSET && CSHAIRASSET.wearing)
      ? CSHAIRASSET.wearing() : null;
    if (!worn) worn = { hair: false, beard: false, brows: false };

    var base = baseColour(w);
    var greyC = srgb(GREY_HEX);
    var gAmt = greyAmount(w);
    var temples = (w.greying === 'temples');
    var plain = base.clone();
    if (gAmt > 0 && !temples) plain.lerp(greyC, gAmt);

    /* per-vertex colour: temples grey only the sides, low down */
    var tmp = new THREE.Color();
    function colFn(i, out) {
      if (!temples) { out.copy(plain); return; }
      var x = Math.abs(S.P[i * 3] - M.cx), y = S.P[i * 3 + 1];
      if (x > 0.30 * M.headW && y < M.yTop - 0.30 * M.headH) {
        tmp.copy(base).lerp(greyC, 0.85);
        out.copy(tmp);
      } else out.copy(base);
    }
    function flatCol(i, out) { out.copy(plain); }

    var group = new THREE.Group();
    group.name = 'cs-hair';
    /* transparent for the feathered edge only: alphaTest drops the fully faded
       fringe so nothing is drawn where the hair has thinned to nothing */
    var mat = new THREE.MeshStandardMaterial({
      color: 0xffffff, vertexColors: true, roughness: roughness(w),
      metalness: 0, side: THREE.DoubleSide, transparent: true, alphaTest: 0.02
    });
    /* plain is ALREADY linear (srgb() converted it); hand the Color over as it
       is — getHex() would quantise a dark linear value back through 8 bits. */
    var solid = new THREE.MeshStandardMaterial({
      color: plain.clone(), roughness: roughness(w), metalness: 0, side: THREE.DoubleSide
    });
    /* brows are a shade darker than the hair on almost every head */
    var browMat = new THREE.MeshStandardMaterial({
      color: plain.clone().multiplyScalar(0.7), roughness: 0.9, metalness: 0, side: THREE.DoubleSide,
      transparent: true, opacity: 0.55
    });

    var info = {
      length: w.length, color: w.color, texture: w.texture, facial: w.facial,
      hairline: w.hairline, greying: w.greying, brow: w.brow,
      def: !!w.def, forward: M.fwd > 0 ? '+z' : '-z',
      headH: M.headH, headW: M.headW, yTop: M.yTop, browY: M.browY, earY: M.earY,
      headCx: M.cx, headZc: M.zc, bodyMinY: S.minY, ear: M.ear,
      capVerts: 0, fallVerts: 0, beardVerts: 0, brows: 0,
      scalpSel: 0, shoulderY: M.yTop - 1.9 * M.headH
    };

    /* (1) the cap. The shell is a copy of the scalp's own triangles pushed out
       along their vertex normals, so the push has to stay well under the
       radius of curvature of the skull: a coily 0.04 m offset on a 66k-vertex
       head turns every fold inside out and the cap renders as a lattice with
       the skin showing through. 6 % of the head's height is the ceiling. */
    var spec = strandSpec(w);
    var tCap = spec ? SCALP_T : Math.min(thickness(w), 0.06 * M.headH);
    info.thickness = tCap;
    var D = scalpField(S, M, w), sel = selFromField(D);
    for (var i = 0; i < sel.length; i++) if (sel[i]) info.scalpSel++;
    /* with strands the shell is a thin DARK scalp under them, set back 4 mm
       from the hairline so the edge is baby hair on skin, not a painted line */
    var Dcap = D;
    if (spec) { Dcap = new Float32Array(D.length); for (i = 0; i < D.length; i++) Dcap[i] = D[i] - 0.0015; }
    function scalpCol(i, out) { colFn(i, out); if (spec) out.multiplyScalar(0.62); }
    var capG = (w.hairline === 'fully bald') ? null : shell(S, Dcap, tCap, scalpCol, spec ? 0.012 : FEATHER);
    if (capG) {
      var cap = new THREE.Mesh(capG, mat);
      cap.name = 'cs-hair-cap';
      group.add(cap);
      info.capVerts = capG.attributes.position.count;
    }
    /* (1b) the strands */
    var near = skinHash(S, 0.02);
    if (spec && capG && !worn.hair) {
      var greyP = gAmt;
      var strandCol = function (rnd, i, x, y, out) {
        var g = greyP;
        if (temples) {
          var ax = Math.abs(x - M.cx);
          g = (ax > 0.30 * M.headW && y < M.yTop - 0.30 * M.headH) ? 0.85 : 0.04;
        }
        if (g > 0 && rnd() < g) { var gk = 0.8 + 0.4 * rnd(); out.setRGB(greyC.r * gk, greyC.g * gk, greyC.b * gk); return; }
        /* lightness spread skewed dark, and a touch of hue drift */
        var r = rnd(), k = 0.62 + 0.75 * r * r, lift = 0.02 * r * r;   /* black hair still has light strands */
        out.setRGB(base.r * k * (1 + 0.08 * (rnd() - 0.5)) + lift,
                   base.g * k * (1 + 0.06 * (rnd() - 0.5)) + lift,
                   base.b * k * (1 + 0.06 * (rnd() - 0.5)) + lift);
      };
      var sg = strands(S, D, M, spec, w, strandCol, near);
      if (sg) {
        var strandMat = hairMaterial(Math.min(0.95, roughness(w) + 0.05));
        var sm = new THREE.Mesh(sg, strandMat);
        sm.name = 'cs-hair-strands';
        sm.frustumCulled = false;
        group.add(sm);
        info.strands = sg.userData.strands;
        info.strandVerts = sg.attributes.position.count;
      }
    }

    /* (2) the fall curtain, for medium and longer — only when there are no
       strands to carry the length (strands reach the collar, the shoulders
       or the waist on their own now) */
    var toK = FALL_TO[w.length];
    if (capG && toK !== undefined && !worn.hair && !(spec && info.strands)) {
      /* medium hangs behind the ears; anything longer falls past them */
      var cutF = M.fmin + 0.55 * M.depth;
      if (w.length === 'medium' && M.ear) cutF = M.fwd * (M.ear.z0 - M.zc) - 0.005;
      var fg = fall(S, sel, M, M.yTop - toK * M.headH, plain, cutF);
      if (fg) {
        var fm = new THREE.Mesh(fg, mat);
        fm.name = 'cs-hair-fall';
        group.add(fm);
        info.fallVerts = fg.attributes.position.count;
        info.fallTo = M.yTop - toK * M.headH;
      }
    }

    /* (3) the beard: a thin dark shell under strands, like the scalp */
    var bt = BEARD_T[w.facial], bspec = BEARD_STRAND[w.facial] || null;
    if (bt !== undefined && !worn.beard) {
      var BD = beardField(S, M, w);
      var beardShellCol = function (i, out) { colFn(i, out); out.multiplyScalar(0.62); };
      var bg = shell(S, BD, bspec ? 0.0012 : bt, bspec ? beardShellCol : flatCol, bspec ? 0.010 : 0.6 * FEATHER);
      if (bg) {
        var bm = new THREE.Mesh(bg, mat);
        bm.name = 'cs-beard';
        group.add(bm);
        info.beardVerts = bg.attributes.position.count;
      }
      if (bspec && bg) {
        var beardCol = function (rnd, i, x, y, out) {
          var g = gAmt > 0 ? Math.min(1, gAmt * 1.3) : 0;     /* beards grey first */
          if (g > 0 && rnd() < g) { var gk = 0.8 + 0.4 * rnd(); out.setRGB(greyC.r * gk, greyC.g * gk, greyC.b * gk); return; }
          var r = rnd(), k = 0.6 + 0.75 * r * r;
          out.setRGB(base.r * k * 1.06, base.g * k, base.b * k * 0.96);
        };
        var bsg2 = strands(S, BD, M, bspec, w, beardCol, near);
        if (bsg2) {
          var bsm2 = new THREE.Mesh(bsg2, hairMaterial(Math.min(0.95, roughness(w) + 0.1)));
          bsm2.name = 'cs-beard-strands';
          bsm2.frustumCulled = false;
          group.add(bsm2);
          info.beardStrands = bsg2.userData.strands;
        }
      }
    }

    /* (4) the brows — unless the photoreal skin (char_photoreal.js) has them
       painted on the main figure, where a second pair would sit on top */
    var painted = !!(ctx.main && window.CSPHOTOREAL && CSPHOTOREAL.browsPainted && CSPHOTOREAL.browsPainted());
    if (w.brow !== 'none' && w.brow !== 'shaved' && !painted && !worn.brows) {
      /* hairs, not a ribbon: the flat ribbon read as a plate under them.
         The ribbon builder stays as the fallback for a body whose brow
         surface cannot be sampled. */
      var bsg = browStrands(S, M, browAnchors(M, w), browMat.color, near);
      if (!bsg) {
        var bl = brows(S, M, w, browMat);
        for (var j = 0; j < bl.length; j++) group.add(bl[j]);
        info.brows = bl.length;
      }
      if (bsg) {
        var bsm = new THREE.Mesh(bsg, hairMaterial(0.88));
        bsm.name = 'cs-brow-strands';
        group.add(bsm);
        info.browStrands = bsg.userData.strands;
      }
    }

    store.hairInfo = info;
    if (ctx.main) credit(hairLine(info));
    if (!group.children.length) return;
    ctx.parent.add(group);
    store.hair = group;
  }

  function build() {
    if (!CS3 || CS3.failed || !CS3.model || !CS3.scene) { disposeHair(CS3); return; }
    buildFor(mainCtx());
  }

  function hairLine(info) {
    if (info.def) return 'hair: default (no character) — short brown, natural brows';
    return 'hair: ' + info.length + ' ' + info.color + ' ' + info.texture +
           (info.facial && info.facial !== 'none' ? ' · ' + info.facial : '') +
           ' · hairline ' + info.hairline;
  }

  /* one hook, every reason: the model changed, a value was staged or saved, a
     bible was loaded, the tab was entered */
  var pending = 0;
  function rebuild(why) {
    if (pending) return;
    pending = setTimeout(function () {
      pending = 0;
      try { build(); } catch (e) { console.warn('char_hair build', why, e); }
    }, 0);
  }
  CS3_HOOKS.push(rebuild);
  window.csHairRebuild = function () { try { build(); } catch (e) { console.warn('char_hair', e); } };
  /* for a second figure: values = fn(path) → raw value (Compare passes a
     bible's flattened values), loaded = whether that is a real character */
  /* The two frames an installed groom is fitted by, measured on whichever body
     is standing. Exported so char_hair_assets.js does not measure the body a
     second time and drift from this one.

       head frame   origin (cx, yTop, zc) of the head band, unit = its width
                    — where a MakeHuman groom is stored
       skull frame  a least-squares sphere through the top DOME_FRAC of the
                    head band, unit = its radius — where a Blender Studio
                    groom is stored, fitted to the same fraction of a skull
                    that tools/hair_assets/groom_to_glb.py measured on the
                    donor. Both sides measure, neither assumes. */
  var DOME_FRAC = 0.45;
  function sphereFit(P, take) {
    var A = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]], b = [0,0,0,0], i, j, k, n = 0;
    for (k = 0; k < take.length; k++) {
      var t = take[k], x = P[t*3], y = P[t*3+1], z = P[t*3+2];
      var row = [2*x, 2*y, 2*z, 1], rhs = x*x + y*y + z*z;
      for (i = 0; i < 4; i++) { for (j = 0; j < 4; j++) A[i][j] += row[i]*row[j]; b[i] += row[i]*rhs; }
      n++;
    }
    if (n < 8) return null;
    var M4 = [];
    for (i = 0; i < 4; i++) M4.push(A[i].concat([b[i]]));
    for (var c = 0; c < 4; c++) {
      var piv = c;
      for (i = c; i < 4; i++) if (Math.abs(M4[i][c]) > Math.abs(M4[piv][c])) piv = i;
      if (Math.abs(M4[piv][c]) < 1e-12) return null;
      var tmpr = M4[c]; M4[c] = M4[piv]; M4[piv] = tmpr;
      for (var r = 0; r < 4; r++) {
        if (r === c) continue;
        var f = M4[r][c] / M4[c][c];
        for (k = c; k < 5; k++) M4[r][k] -= f * M4[c][k];
      }
    }
    var xs = [];
    for (i = 0; i < 4; i++) xs.push(M4[i][4] / M4[i][i]);
    var cc = new THREE.Vector3(xs[0], xs[1], xs[2]);
    var r2 = xs[3] + cc.lengthSq();
    if (!(r2 > 0)) return null;
    return { centre: cc, radius: Math.sqrt(r2) };
  }
  function framesFor(model) {
    var mesh = bodyMesh(model);
    if (!mesh) return null;
    var S = sampleBody(mesh), M = headMetrics(S);
    if (!M) return null;
    var cut = M.yTop - DOME_FRAC * M.headH, dome = [], i;
    for (i = 0; i < S.count; i++) if (S.P[i*3+1] > cut) dome.push(i);
    var sp = sphereFit(S.P, dome);
    var xmin = Infinity, xmax = -Infinity, zmin = Infinity, zmax = -Infinity;
    for (i = 0; i < S.count; i++) {
      if (S.P[i*3+1] <= M.chinY) continue;
      var x = S.P[i*3], z = S.P[i*3+2];
      if (x < xmin) xmin = x; if (x > xmax) xmax = x;
      if (z < zmin) zmin = z; if (z > zmax) zmax = z;
    }
    return {
      headOrigin: new THREE.Vector3((xmin+xmax)*0.5, M.yTop, (zmin+zmax)*0.5),
      headW: M.headW, headH: M.headH, yTop: M.yTop, fwd: M.fwd,
      skullCentre: sp ? sp.centre : null,
      skullRadius: sp ? sp.radius : null,
      domeCount: dome.length
    };
  }

  window.CSHAIR = {
    frames: framesFor,
    buildFor: function (model, parent, store, values, loaded) {
      var get = function (path) { try { return low(values(path)); } catch (e) { return ''; } };
      buildFor({ model: model, parent: parent, store: store, wants: readWants(get, loaded), main: false });
    },
    dispose: disposeHair
  };

  /* the bundle loads after the page script, so the body may already be standing */
  if (CS3.model) rebuild('bundle');
})();
