// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_eyes.js — real eyes on the Character Studio 3D base body.  2026-09-19,
   rebuilt for close range 2026-09-20 (backup char_eyes.js.bak-photoreal-20260920).

   The CC0 body ships two eyeball spheres (…eye.L / …eye.R, 24 mm) with no
   material. The first cut painted a 1024² iris on the sphere: at the wheel's
   closest stop the operator saw a flat brown disc, a plain pupil, no corneal
   bulge, an even white sclera. This build is what a photograph shows:

   · IRIS at 2048²: a dish (the cap inside the limbus is flattened onto the
     limbus plane and hollowed 0.25 mm, so the iris sits BEHIND the cornea),
     radial fibre bundles in three layers, crypts, contraction furrows, a
     raised collarette, a pupillary ruff, pigment flecks, a limbal ring, a
     pupil whose size is jittered per colour. The same fibre field is drawn
     into a height canvas → tangent-space normal map, so fibres catch light.
   · CORNEA: its own transparent cap (MeshPhysicalMaterial transmission 1,
     ior 1.376, roughness 0.02) on the real corneal sphere (r 0.65 R, centre
     0.44 R forward: apex ≈ 1 mm proud of the sclera, limbus at 29°). Measured
     against the lids: the bulge fades to nothing 1° short of the lid edge in
     every bearing, so it never exits the lid skin (the upper lid on this body
     covers the eye down to 17.5° off the axis, where its skin sits 0–1.5 mm
     off the globe — a full bulge would have poked through).
   · SCLERA: warm off-white going pink-grey to the corners, branching
     capillaries denser at the corners, an ambient-occlusion band under the
     upper lid, a clear coat that stops at the limbus (clearcoatMap) so the
     cornea is the only wet highlight over the iris. A studio environment map
     (one soft box, a cool fill) gives every eye a window-shaped catchlight.
   · A tear meniscus: a thin glassy tube along the lower lid margin.
   · Lashes live in char_lashes.js; they root on the lid loop measured here
     (CSEYES.lidLoop) — the innermost body vertex per bearing round the gaze.
   · CSEYES.skinMicro(material): pores + creases as a procedural world-space
     bump on any MeshStandardMaterial, faded out by pixel footprint so the
     full-body view is untouched. char_dress (skin) and char_photoreal (baked
     albedo) call it.

   How the texture is placed: the sphere's own UVs are thrown away and rebuilt
   as a POLAR map about the gaze axis: uv = 0.5 + 0.5·sqrt(theta/π)·(cos phi,
   sin phi), so the iris (theta < 29°) fills the middle 40 % of the canvas.
   The gaze is the head's forward axis turned 2° in towards the nose per eye.

   2026-09-22 EYE MACRO (backup char_eyes.js.bak-eyemacro-20260922), measured
   against a real macro (Documents/the-human-eye.webp: iris mean 77 / std 54,
   lit sclera 225) at a 6 cm frame on the left eye:
   · IRIS per pixel (paintIris): three octaves of RIDGED radial noise, Worley
     crypts outside the collarette, a jagged collarette, broken furrows,
     amber pupillary zone, lighter outer band, sharp limbal ring. std 17 → 34.
   · The eye is TWO meshes: the body's 2 176-vertex sphere is replaced by a
     dense sphere about the gaze (denseSphere; the pupil edge was a hexagon)
     open at the front = the SCLERA (clearcoat + env); a 'cs-iris' cap in the
     eye group carries the iris, matte, NO env (env fill hazed every shadow).
   · A hand-built mip chain (mipChain): from the level where the iris is
     ~26 px the pupil is drawn larger and the iris darker, so the body-distance
     eye keeps a dark centre (proven: GPU mips min 65, ours 42).
   · TWO envs: 'hot' (key card ×60, 25°×19°) for the cornea catchlight and
     lash gloss, 'soft' (×20) for sclera/margin/tear. Cornea roughness 0,
     thickness 0.6 mm (more rippled through the mesh), 36×128 rings.
   · loopTheta is Catmull-Rom (linear creased the cornea's lid fade).
   · The lid SHADOW follows the measured lid loop per bearing (lidShadow),
     blended upper→lower round the corners; the old horizontal band cut
     across the sclera.
   · Lid MARGIN (marginGeometry): a 2-row strip from the globe to the lid
     edge, pink wet waterline below, dark lash line above. Tear tube 0.26 mm.
   · Distance LOD (installFade, scene.onBeforeRender): cornea hidden under
     CORNEA_MIN_PX of eye radius, lashes fade 30 → 6 px.
   · skinMicro's cell-border net 0.3 → 0.12 (a honeycomb at macro).
   SECOND PASS, same day, against MEASURED profiles of the photograph
   (scratchpad profiles.py: iris luminance/angular-std/skew per radial band,
   limbus profile per 0.1 mm, sclera profile along the horizontal):
   · the iris ground follows IRIS_PROFILE (dark ruff 64 → bright band 137 at
     s 0.35 → dark rim 50), light threads ADDED on the darker outer half,
     dark crypts only in the bright band, a soft wandering pupil edge with a
     serrated ruff, a 0.5 mm limbus S-ramp into a blue-grey sclera;
   · the iris cap has specularIntensity 0 — its 4 % sheen was a grey veil
     over the pupil (34/255 with the cornea hidden and the lights off);
   · the hot env's broad cards are dark (the cornea reflected them as a
     milky film); one PMREMGenerator per env (two fromScene calls on one
     generator gave a different catchlight per load); the soft box sits
     BEHIND the key card (coplanar, it hid it);
   · socketAmbient(): hemisphere/ambient irradiance × 0.3 on the eye
     materials so the key's spherical gradient shows;
   · lid margin = a 0.5 mm glossy lip, the tear line visible; lashes never
     start towards the eye (a0 ≥ 0) and sweep along the lid by position.
   Not done: the upper lid crease (skin/atlas), true lid shadowing (no shadow
   maps in this scene), a lid-shaped shadow per eye (the texture is shared),
   the photograph's light direction (our key is upper-right, d1 in
   inspection.html; its shadow side is 25–45, ours 55–75).

   Shared with char_dress.js: its paint() hands the eye meshes over here
   (CSEYES.applyFor); the CS3_HOOKS entry covers the first load, which
   happens before this file in the bundle. Compare's second figure comes
   through applyFor() with its own store. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;

  /* sRGB hex per word of the bible's identity.eye_color; a #rrggbb is taken as-is */
  var IRIS = {
    'brown': '#5a3a1e', 'dark brown': '#3d2412', 'light brown': '#8a5a30',
    'black': '#2a1a10', 'hazel': '#7d6a36', 'amber': '#b57a2a', 'green': '#4c7a45',
    'blue': '#4a7db5', 'light blue': '#6fa3d3', 'grey': '#7d8288', 'gray': '#7d8288',
    'grey-blue': '#6a8399', 'gray-blue': '#6a8399', 'blue-grey': '#6a8399',
    'violet': '#6b5a9a', 'heterochromia': '#5a3a1e'
  };
  var IRIS_DEF = '#5a3a1e';
  var TEX_SIZE = 2048;
  var CONVERGE = 2 * Math.PI / 180;       /* each eye turns this much in */
  /* angular sizes on a 24 mm globe: iris 11.7 mm across → half-angle 29°,
     pupil 4 mm across → 9.6° */
  var IRIS_THETA = 29.2 * Math.PI / 180;
  var PUPIL_THETA = 8.8 * Math.PI / 180;   /* 3.7 mm: a pupil in macro light */
  var DISH = 0.045;                       /* iris concavity, in eye radii (0.54 mm: the iris sits BEHIND the cornea) */
  var CORNEA_MIN_PX = 18;                 /* the cornea shell is hidden when the eye's radius is under this on screen */
  var MARGIN = { back: 0.004, fwd: 0.00012, side: 0.00012, lip: 0.0003 };  /* lid margin: globe lift (eye radii), edge lift fwd/out, lip depth (m) */
  /* the cornea as a sphere: radius and forward offset in eye radii, and a
     scale on the resulting bulge (0.9 keeps the apex ≈ 1 mm proud) */
  var CORNEA = { rc: 0.65, off: 0.44, k: 0.9, capTheta: 31 * Math.PI / 180, lift: 0.0035 };
  var LID_FADE_IN = 4.5 * Math.PI / 180;  /* bulge fades over this, ending … */
  var LID_FADE_END = 1.0 * Math.PI / 180; /* … this far short of the lid edge */
  var LOOP_BINS = 48;

  var texCache = {};   /* hex → {map, ...}; one per colour, shared by both eyes */
  var shared = { normal: null, coat: null, env: null, envSoft: null };

  function low(v) { return (v === undefined || v === null) ? '' : String(v).toLowerCase().trim(); }
  function pageVal(path) {
    try { if (typeof cstVal === 'function') return low(cstVal(path)); } catch (e) {}
    return '';
  }
  function irisHex(word) {
    if (/^#[0-9a-f]{6}$/.test(word)) return word;
    if (IRIS[word]) return IRIS[word];
    /* 'dark brown eyes', 'deep blue' … — first palette word that appears */
    for (var k in IRIS) { if (IRIS.hasOwnProperty(k) && word.indexOf(k) >= 0) return IRIS[k]; }
    return IRIS_DEF;
  }

  /* map radius from the angle off the gaze axis: sqrt spreads the front cap */
  function rOf(theta) { return Math.sqrt(Math.max(0, theta) / Math.PI); }

  /* ── colour helpers ───────────────────────────────────────────────────── */
  function hexRGB(hex) {
    return [parseInt(hex.substr(1, 2), 16), parseInt(hex.substr(3, 2), 16), parseInt(hex.substr(5, 2), 16)];
  }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function shade(c, k) {
    return [Math.min(255, Math.round(c[0] * k)), Math.min(255, Math.round(c[1] * k)), Math.min(255, Math.round(c[2] * k))];
  }
  function mix(a, b, t) {
    return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)];
  }
  /* deterministic noise so both eyes and every rebuild draw the same iris */
  function rng(seed) {
    var s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  function hashHex(hex) {
    var h = 2166136261;
    for (var i = 0; i < hex.length; i++) { h ^= hex.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }

  /* ── the textures ─────────────────────────────────────────────────────── */
  /* The colour canvas and a height canvas are drawn in ONE pass from ONE
     random sequence, so the normal map (colour-independent, cached once) lines
     up with the fibres of every colour. Height: 128 = the iris plane, brighter
     = raised (fibre bundles, the collarette), darker = sunk (crypts, furrows). */
  /* ── periodic value noise for the iris (period px in x, so the fibre
     field closes round the clock) ── */
  function vnHash(ix, iy, seed) {
    var h = (ix * 374761393 + iy * 668265263 + seed * 1442695041) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177); h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  }
  function vnoise(x, y, px, seed) {
    var ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
    var i0 = ((ix % px) + px) % px, i1 = (i0 + 1) % px;
    var a = vnHash(i0, iy, seed), b = vnHash(i1, iy, seed), c = vnHash(i0, iy + 1, seed), d = vnHash(i1, iy + 1, seed);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  }
  function sstep(a, b, x) { var t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); }

  /* ── the iris, per pixel, in polar coordinates about the pupil centre.
     s = 0 at the pupil edge, 1 at the limbus, LINEAR on the iris plane
     (the map's radius is sqrt(theta), so s comes from rad²). Written
     straight into the colour ImageData (over the sclera already drawn) and
     into the height ImageData.

     2026-09-22, second pass, built from MEASUREMENT of the reference macro
     (Documents/the-human-eye.webp, 36.5 px/mm; scratchpad profiles.py):
       · luminance per 0.4 mm band from the pupil out: 64 (a dark ruff),
         108, 129, 137 (the bright band round the collarette), 131, 120,
         109, 90, 65, 50 (a dark rim) — IRIS_PROFILE below. The first
         build had this upside down (brightest at the pupil).
       · fibre contrast SIGN per band (skew of the band's luminance): thin
         LIGHT threads on a darker ground in the outer half (+0.4…+0.9)
         and next to the pupil; thin DARK crypts between bright fibres only
         in the bright band (−0.5). Angular std ≈ 45 mid-iris, ≈ 30 at the
         ends. So: the ground follows the profile; light threads are
         ADDED, sparse and irregular (gated by a low-frequency field, broken
         along their length), with their amplitude largest at s 0.55–0.85;
         crypts are subtracted only at s 0.12–0.55.
       · the limbus is not a line: inside the rim the ground falls to ~45
         over 0.7 mm, then a 0.5 mm S-ramp from dark grey-blue up to the
         sclera, and the sclera stays a little blue-grey (AO of the corneal
         bulge) for another 0.8 mm.
       · the pupil edge is soft (0.1 mm) and wanders ±3 %, with a serrated
         dark ruff over the first 0.3 mm.
     The colour is the bible's, in the first build's palette: warm near the
     pupil, the plain colour mid-iris, greyer then darker at the rim; each
     zone's colour is rescaled to the profile's luminance. ── */
  var IRIS_PROFILE = [[0.0, 50], [0.1, 72], [0.19, 120], [0.27, 146], [0.36, 155], [0.45, 150], [0.54, 142],
                      [0.63, 128], [0.72, 104], [0.80, 74], [0.86, 72], [0.92, 104], [0.97, 150], [1.0, 170]];
  function profileAt(s) {
    var P = IRIS_PROFILE;
    if (s <= P[0][0]) return P[0][1];
    for (var i = 1; i < P.length; i++) if (s <= P[i][0]) {
      var t = (s - P[i - 1][0]) / (P[i][0] - P[i - 1][0]);
      return P[i - 1][1] + (P[i][1] - P[i - 1][1]) * t;
    }
    return P[P.length - 1][1];
  }
  function lumOf(c) { return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
  function paintIris(img, hgt, S, cx, cy, rPupil, rIris, iris) {
    var d = img.data, hd = hgt ? hgt.data : null;
    /* the first build's palette, as hues (each is rescaled to the profile) */
    var warm = mix(iris, [200, 120, 40], 0.4);
    var mid = iris;
    var grey = mix(iris, [118, 108, 100], 0.35);
    var rim = mix(iris, [44, 36, 32], 0.5);
    var limbGrey = [50, 44, 40];
    var pupilC = [4, 3, 3];
    var rI2 = rIris * rIris;
    var r0 = Math.max(0, Math.floor(cx - rIris * 1.16)), r1 = Math.min(S - 1, Math.ceil(cx + rIris * 1.16));
    var TAU = Math.PI * 2;
    for (var y = r0; y <= r1; y++) {
      for (var x = r0; x <= r1; x++) {
        var dx = x + 0.5 - cx, dy = y + 0.5 - cy, rad2 = dx * dx + dy * dy;
        if (rad2 > rI2 * 1.16 * 1.16) continue;
        var u = Math.atan2(dy, dx) / TAU; if (u < 0) u += 1;
        /* the pupil edge wanders ±3 % round the clock */
        var rp = rPupil * (1 + 0.06 * (vnoise(u * 6, 0.5, 6, 31) - 0.5) + 0.024 * (vnoise(u * 40, 0.5, 40, 32) - 0.5));
        var rP2 = rp * rp;
        var s = (rad2 - rP2) / (rI2 - rP2);            /* linear on the iris plane */
        var k = (y * S + x) * 4;
        if (s < -0.03) {
          d[k] = pupilC[0]; d[k + 1] = pupilC[1]; d[k + 2] = pupilC[2]; d[k + 3] = 255;
          if (hd) { hd[k] = hd[k + 1] = hd[k + 2] = 128; }
          continue;
        }
        var sPos = Math.max(0, s);
        /* ── fields ── */
        var uw = u + 0.0035 * (vnoise(u * 24, s * 3, 24, 7) - 0.5) * 2 + 0.012 * (vnoise(u * 8, s * 2, 8, 9) - 0.5);
        var A = vnoise(uw * 40, s * 2 + 1, 40, 1);                                   /* sector tone */
        var B = vnoise(uw * 260, s * 9 + 3, 260, 2); B = Math.pow(1 - Math.abs(2 * B - 1), 2.5);    /* threads */
        var C = vnoise(uw * 900, s * 16 + 7, 900, 3); C = Math.pow(1 - Math.abs(2 * C - 1), 3.0);   /* fine threads */
        var Dk = vnoise(uw * 140, s * 30 + 11, 140, 14);                              /* breaks along the length */
        var G1 = vnoise(uw * 90, s * 5 + 2, 90, 21), G2 = vnoise(uw * 150, s * 6 + 5, 150, 22);   /* spacing gates */
        var thread = B * (0.3 + 0.9 * Dk) * sstep(0.22, 0.68, G1) + 0.6 * C * sstep(0.32, 0.78, G2);
        thread = Math.min(1, thread);
        /* collarette: a jagged boundary at s ≈ 0.3 */
        var sc = 0.3 + 0.07 * (vnoise(u * 14, 0.5, 14, 4) - 0.5) + 0.03 * (vnoise(u * 90, 0.5, 90, 5) - 0.5);
        var ridge = Math.exp(-Math.pow((s - sc) / 0.014, 2)) * (0.5 + 0.5 * vnoise(u * 120, 0.5, 120, 23));
        /* crypts: Worley, radially elongated, only in the bright band */
        var pit = 0;
        if (s > 0.1 && s < 0.6) {
          var cu = u * 36, cv = s * 4.5, iu = Math.floor(cu), iv = Math.floor(cv), best = 9, bestId = 0;
          for (var oy = -1; oy <= 1; oy++) for (var ox = -1; ox <= 1; ox++) {
            var gu = ((iu + ox) % 36 + 36) % 36, gv = iv + oy;
            var fu = vnHash(gu, gv, 11), fv = vnHash(gu, gv, 12);
            var ddu = (cu - (iu + ox + fu)) * 1.5, ddv = (cv - (gv + fv)) * 0.7;
            var dd = ddu * ddu + ddv * ddv;
            if (dd < best) { best = dd; bestId = vnHash(gu, gv, 13); }
          }
          if (bestId < 0.5) pit = (1 - sstep(0.012, 0.11, best)) * sstep(0.1, 0.18, s) * (1 - sstep(0.48, 0.6, s));
        }
        /* furrows: two broken rings in the outer half */
        var f1 = 0.64 + 0.02 * (vnoise(u * 9, 0.5, 9, 6) - 0.5), f2 = 0.8 + 0.025 * (vnoise(u * 11, 0.5, 11, 8) - 0.5);
        var fur = (Math.exp(-Math.pow((s - f1) / 0.011, 2)) + Math.exp(-Math.pow((s - f2) / 0.013, 2))) * sstep(0.3, 0.6, vnoise(u * 20, 0.5, 20, 10));
        /* ── the ground: the profile's luminance in the zone's hue ── */
        var Lt = profileAt(sPos);
        var wz = 1 - sstep(sc - 0.02, sc + 0.02, s);            /* pupillary zone */
        var gz = sstep(0.5, 0.8, s), rz = sstep(0.8, 0.97, s);
        var col = mix(mid, warm, wz); col = mix(col, grey, gz); col = mix(col, rim, rz);
        var lc = Math.max(1, lumOf(col)), scale = Lt / lc;
        var ds = 0.45 * sstep(1.2, 2.6, scale);              /* lifted colours go tan, not orange */
        col = [col[0] + (lc - col[0]) * ds, col[1] + (lc - col[1]) * ds, col[2] + (lc - col[2]) * ds];
        /* ── modulation ── */
        var amp = 2.0 * (1 - sstep(0.08, 0.15, s)) + 0.9 * sstep(0.12, 0.2, s) * (1 - sstep(0.45, 0.55, s))
                + 1.3 * sstep(0.5, 0.6, s) * (1 - sstep(0.82, 0.9, s)) + 0.6 * sstep(0.85, 0.92, s);
        var mod = (0.8 + 0.4 * A) * (1 + 1.8 * amp * (thread - 0.22));
        mod += 0.35 * ridge;
        mod *= 1 - 0.85 * pit;
        mod *= 1 - 0.22 * Math.min(1, fur);
        /* the ruff: a serrated dark fringe over the first 0.3 mm, and the
           soft pupil edge */
        var ser = 0.25 + 0.75 * vnoise(u * 160, 0.5, 160, 33);
        mod *= 1 - 0.65 * (1 - sstep(0.0, 0.1, s)) * ser;
        mod = Math.max(0.05, mod);
        var r = Math.min(255, col[0] * scale * mod), g = Math.min(255, col[1] * scale * mod), b = Math.min(255, col[2] * scale * mod);
        /* pupil edge: soft over ±0.012 in s (≈ 0.1 mm) */
        var pe = sstep(-0.03, 0.0, s);
        r = pupilC[0] + (r - pupilC[0]) * pe; g = pupilC[1] + (g - pupilC[1]) * pe; b = pupilC[2] + (b - pupilC[2]) * pe;
        /* ── the limbus: S-ramp from dark grey-blue to the sclera over s 0.98–1.12
           (0.5 mm), then the sclera stays blue-grey (AO) out to s 1.3 ── */
        var tL = sstep(0.93, 1.12, s);
        var ao = 0.93 + 0.07 * sstep(1.1, 1.35, s);
        /* a WARM grey AO (the blue-grey read as a cold cast on the whole white) */
        var sr = d[k] * Math.min(1, ao + 0.025), sg = d[k + 1] * ao, sb = d[k + 2] * (ao - 0.02);
        var gI = 1 - 0.7 * sstep(0.84, 1.0, s);                  /* grey-blue creeps into the rim */
        r = r * gI + limbGrey[0] * (1 - gI); g = g * gI + limbGrey[1] * (1 - gI); b = b * gI + limbGrey[2] * (1 - gI);
        r = r + (sr - r) * tL; g = g + (sg - g) * tL; b = b + (sb - b) * tL;
        d[k] = Math.round(r); d[k + 1] = Math.round(g); d[k + 2] = Math.round(b); d[k + 3] = 255;
        if (hd) {
          var h = 128 + 40 * amp * (thread - 0.22) + 30 * ridge - 60 * pit - 25 * Math.min(1, fur);
          h = 128 + (h - 128) * (1 - tL) * pe;
          h = Math.round(Math.min(255, Math.max(0, h)));
          hd[k] = hd[k + 1] = hd[k + 2] = h; hd[k + 3] = 255;
        }
      }
    }
  }

  /* ── the upper lid's shadow, following the MEASURED lid edge per bearing
     (lid(phi) → theta of the edge, radians; the default is 17.5° at the top
     widening to 40° at the corners). Deep at the edge (0.72), gone 12°
     inside it; the lower lid throws a lighter one over 5°. Under the lids
     the globe stays dark, which is what the margin gap shows. Per pixel over
     the front hemisphere of the map (2026-09-22; the old band was a straight
     horizontal gradient, and its top edge cut across the sclera wherever the
     lid runs further out than at the centre). ── */
  function lidShadow(g, S, lid) {
    var cx = S / 2, R = S / 2, rMax = rOf(80 * Math.PI / 180) * R, r0 = Math.max(0, Math.floor(cx - rMax)), r1 = Math.min(S - 1, Math.ceil(cx + rMax));
    var img = g.getImageData(r0, r0, r1 - r0 + 1, r1 - r0 + 1), d = img.data, W = r1 - r0 + 1;
    var D2R = Math.PI / 180, UPW = 12 * D2R, LOW = 4 * D2R, TAU = Math.PI * 2;
    var tint = [26, 14, 9];
    if (!lid) lid = function (phi) { var a = Math.abs(Math.sin(phi)); return (17.5 + 22.5 * (1 - a)) * D2R; };
    for (var y = r0; y <= r1; y++) for (var x = r0; x <= r1; x++) {
      var dx = x + 0.5 - cx, dy = cx - (y + 0.5);               /* canvas rows run down; bearing π/2 = up */
      var r = Math.hypot(dx, dy) / R; if (r > 1) continue;
      var theta = r * r * Math.PI, phi = Math.atan2(dy, dx); if (phi < 0) phi += TAU;
      /* upper lid: deep and wide; lower: light and narrow; blended round the
         corners so there is no seam on the horizontal */
      var te = lid(phi), up = sstep(-0.35, 0.35, dy / (R * Math.max(r, 1e-3)));
      var amp = 0.3 + 0.42 * sstep(0.0, 0.7, up), wid = LOW + (UPW - LOW) * sstep(0.55, 0.9, up);
      var a = amp * sstep(te - wid, te, theta);
      if (a <= 0) continue;
      var k = ((y - r0) * W + (x - r0)) * 4;
      d[k] = Math.round(d[k] + (tint[0] - d[k]) * a);
      d[k + 1] = Math.round(d[k + 1] + (tint[1] - d[k + 1]) * a);
      d[k + 2] = Math.round(d[k + 2] + (tint[2] - d[k + 2]) * a);
    }
    g.putImageData(img, r0, r0);
  }

  /* ── the mip chain by hand: level 0 is the canvas; the GPU's own averages
     turned the eye into a pale disc at body distance (a 2.5 px pupil
     averaged into a mid-brown iris and the white next to it). From the level
     where the iris is ~50 px on screen and down, the pupil is drawn larger
     and the iris darker, so a distant eye still reads as a dark eye. The
     chain is complete down to 1×1 (an incomplete chain samples black). ── */
  function mipChain(cv, rPupil, rIris) {
    var chain = [cv], S = cv.width, prev = cv, lvl = 0;
    while (S > 1) {
      S >>= 1; lvl++;
      var c = document.createElement('canvas'); c.width = S; c.height = S;
      var g = c.getContext('2d');
      g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
      g.drawImage(prev, 0, 0, S, S);
      var k = S / cv.width, rI = rIris * k, rP = rPupil * k, cx = S / 2, cy = S / 2;
      if (lvl >= 5 && S >= 2) {                      /* 64 px map: iris ≈ 26 px on screen */
        var t = Math.min(1, (lvl - 4) / 3);          /* 5 → ⅓, 6 → ⅔, 7+ → 1 */
        g.fillStyle = 'rgba(24,15,10,' + (0.85 * t) + ')';
        g.beginPath(); g.arc(cx, cy, rI, 0, Math.PI * 2); g.fill();
        g.fillStyle = 'rgba(8,5,4,' + (0.95 * t) + ')';
        g.beginPath(); g.arc(cx, cy, rP + (rI - rP) * 0.55 * t, 0, Math.PI * 2); g.fill();
      }
      chain.push(c); prev = c;
    }
    return chain;
  }

  function drawEye(hex, lid) {
    var S = TEX_SIZE, cv = document.createElement('canvas');
    cv.width = S; cv.height = S;
    var g = cv.getContext('2d');
    var needH = !shared.normal;
    var hc = null, gh = null;
    if (needH) {
      hc = document.createElement('canvas'); hc.width = S; hc.height = S;
      gh = hc.getContext('2d');
      gh.fillStyle = 'rgb(128,128,128)'; gh.fillRect(0, 0, S, S);
      gh.lineCap = 'round';
    }
    var cx = S / 2, cy = S / 2, R = S / 2;
    var rIris = rOf(IRIS_THETA) * R;
    /* pupil size differs a little from face to face: ±7 % by colour hash */
    var pj = 0.93 + 0.14 * ((hashHex(hex) % 1000) / 1000);
    var rPupil = rOf(PUPIL_THETA) * R * pj;
    var iris = hexRGB(hex), rnd = rng(0x9e3779b9), i;
    var pale = mix(iris, [238, 226, 205], 0.4), warm = mix(iris, [200, 120, 40], 0.35), deep = shade(iris, 0.3);

    /* ── sclera: bright, warm off-white; pinker only in the corners (the part
       in the socket). The old ramp reached beige at theta 40° and rendered
       at 157 — a lit sclera in a photograph is 200+. ── */
    var sc = g.createRadialGradient(cx, cy, rIris, cx, cy, R);
    sc.addColorStop(0, '#efe8e1');
    sc.addColorStop(0.16, '#f0e9e2');     /* theta 45°: still white */
    sc.addColorStop(0.33, '#e4c9bd');     /* 65° */
    sc.addColorStop(0.51, '#c9a99d');     /* 90° */
    sc.addColorStop(1, '#b6968e');
    g.fillStyle = sc; g.fillRect(0, 0, S, S);
    /* the corners: warm, pink, subsurface flesh behind the thin conjunctiva */
    for (i = 0; i < 2; i++) {
      var bx = cx + (i ? -1 : 1) * R * 0.66;
      var bg = g.createRadialGradient(bx, cy, 0, bx, cy, R * 0.36);
      bg.addColorStop(0, 'rgba(226,150,140,0.5)');
      bg.addColorStop(0.6, 'rgba(226,150,140,0.18)');
      bg.addColorStop(1, 'rgba(226,150,140,0)');
      g.fillStyle = bg; g.fillRect(0, 0, S, S);
    }

    /* capillaries: branching, from the rim inward, at the CORNERS only
       (|cos a| weighting), stopping well short of the limbus */
    g.lineCap = 'round';
    function vein(x, y, a, len, w, depth, col) {
      var n = 8 + Math.floor(rnd() * 5), stepL = len / n;
      g.beginPath(); g.moveTo(x, y);
      for (var k = 0; k < n; k++) {
        a += (rnd() - 0.5) * 0.4;
        x += Math.cos(a) * stepL; y += Math.sin(a) * stepL;
        g.lineTo(x, y);
        if (Math.hypot(x - cx, y - cy) < rIris * 1.2) break;
        if (depth > 0 && rnd() < 0.42) {
          var ca = a + (rnd() < 0.5 ? 1 : -1) * (0.45 + 0.6 * rnd());
          vein(x, y, ca, len * (0.45 + 0.3 * rnd()), w * 0.6, depth - 1, col);
          g.beginPath(); g.moveTo(x, y);
        }
      }
      g.strokeStyle = col; g.lineWidth = w; g.stroke();
    }
    for (i = 0; i < 90; i++) {
      var va = rnd() * Math.PI * 2;
      var ca0 = Math.abs(Math.cos(va));
      if (rnd() > Math.pow(ca0, 2.5)) continue;      /* corners only */
      var r0 = R * (0.62 + 0.36 * rnd());
      var vx = cx + Math.cos(va) * r0, vy = cy + Math.sin(va) * r0;
      var inward = Math.atan2(cy - vy, cx - vx) + (rnd() - 0.5) * 0.9;
      var w = 0.8 + 1.6 * rnd();
      vein(vx, vy, inward, R * (0.1 + 0.2 * rnd()), w, 2, rgba([190, 56, 54], 0.1 + 0.2 * rnd()));
    }
    /* a faint yellowish tint patch (pinguecula side) at the outer corner */
    var pg0 = g.createRadialGradient(cx + R * 0.52, cy + R * 0.02, 0, cx + R * 0.52, cy, R * 0.2);
    pg0.addColorStop(0, 'rgba(226,196,130,0.14)'); pg0.addColorStop(1, 'rgba(226,196,130,0)');
    g.fillStyle = pg0; g.fillRect(0, 0, S, S);

    /* ── the iris, per pixel ── */
    var img = g.getImageData(0, 0, S, S);
    var hgt = gh ? gh.getImageData(0, 0, S, S) : null;
    paintIris(img, hgt, S, cx, cy, rPupil, rIris, iris);
    g.putImageData(img, 0, 0);
    if (gh) gh.putImageData(hgt, 0, 0);

    /* pigment flecks: small dark spots and a few pale ones, on the ciliary zone */
    for (i = 0; i < 60; i++) {
      var fla = rnd() * Math.PI * 2, flr = rPupil * 1.2 + (rIris * 0.9 - rPupil * 1.2) * rnd();
      var flc = rnd() < 0.7 ? deep : (rnd() < 0.5 ? warm : pale);
      g.fillStyle = rgba(flc, 0.35 + 0.4 * rnd());
      g.save(); g.translate(cx + Math.cos(fla) * flr, cy + Math.sin(fla) * flr); g.rotate(fla);
      g.scale(1.6, 1);
      g.beginPath(); g.arc(0, 0, 1.5 + 3.5 * rnd(), 0, Math.PI * 2); g.fill(); g.restore();
    }
    /* the shadow the upper lid throws: an occlusion band from the lid edge
       (theta ≈ 17°, 320 px above centre on this map) down over the iris top.
       Milder than before (0.55): the lid margin geometry now throws its own
       real shadow line, and the fibres must stay readable under it. */
    lidShadow(g, S, lid);

    var tex = new THREE.CanvasTexture(cv);
    if (THREE.sRGBEncoding) tex.encoding = THREE.sRGBEncoding;
    if (CS3.renderer && CS3.renderer.capabilities) tex.anisotropy = CS3.renderer.capabilities.getMaxAnisotropy();
    try { tex.mipmaps = mipChain(cv, rPupil, rIris); tex.generateMipmaps = false; } catch (e) { console.warn('char_eyes mips', e); }
    tex.needsUpdate = true;
    if (needH) shared.normal = normalFromHeight(hc, 2.0);
    return tex;
  }

  /* height canvas → tangent-space normal map (Sobel-ish central differences).
     UV v runs UP while canvas rows run DOWN, and CanvasTexture flips Y, so a
     slope towards larger v is a slope towards SMALLER row index. */
  function normalFromHeight(hc0, strength) {
    /* half the colour map's size: fibre slopes need no more, and the JS
       Sobel over 2048² cost 2 s once per page (headless CPU) — 1024² is 4× less */
    var S = hc0.width >> 1, hc = document.createElement('canvas');
    hc.width = S; hc.height = S;
    var g = hc.getContext('2d');
    g.drawImage(hc0, 0, 0, S, S);
    var src = g.getImageData(0, 0, S, S).data;
    var out = g.createImageData(S, S), o = out.data;
    var H = new Float32Array(S * S);
    for (var i = 0; i < S * S; i++) H[i] = src[i * 4] / 255;
    for (var y = 0; y < S; y++) {
      var ym = y > 0 ? y - 1 : y, yp = y < S - 1 ? y + 1 : y;
      for (var x = 0; x < S; x++) {
        var xm = x > 0 ? x - 1 : x, xp = x < S - 1 ? x + 1 : x;
        var dx = (H[y * S + xp] - H[y * S + xm]) * strength;
        var dy = (H[ym * S + x] - H[yp * S + x]) * strength;     /* + = higher towards larger v */
        var nx = -dx, ny = -dy, nz = 1;
        var L = Math.sqrt(nx * nx + ny * ny + 1);
        var k = (y * S + x) * 4;
        o[k] = Math.round((nx / L * 0.5 + 0.5) * 255);
        o[k + 1] = Math.round((ny / L * 0.5 + 0.5) * 255);
        o[k + 2] = Math.round((nz / L * 0.5 + 0.5) * 255);
        o[k + 3] = 255;
      }
    }
    g.putImageData(out, 0, 0);
    var t = new THREE.CanvasTexture(hc);
    if (CS3.renderer && CS3.renderer.capabilities) t.anisotropy = CS3.renderer.capabilities.getMaxAnisotropy();
    t.needsUpdate = true;
    return t;
  }
  /* clear coat only on the sclera: the cornea is the wet surface over the iris */
  function coatMap() {
    if (shared.coat) return shared.coat;
    var S = 512, cv = document.createElement('canvas'); cv.width = S; cv.height = S;
    var g = cv.getContext('2d'), rI = rOf(IRIS_THETA) * S / 2;
    g.fillStyle = '#fff'; g.fillRect(0, 0, S, S);
    var gr = g.createRadialGradient(S / 2, S / 2, rI * 0.92, S / 2, S / 2, rI * 1.08);
    gr.addColorStop(0, 'rgba(0,0,0,1)'); gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr; g.beginPath(); g.arc(S / 2, S / 2, rI * 1.08, 0, Math.PI * 2); g.fill();
    shared.coat = new THREE.CanvasTexture(cv);
    shared.coat.needsUpdate = true;
    return shared.coat;
  }
  function texture(hex, lid) {
    if (!texCache[hex]) texCache[hex] = drawEye(hex, lid);
    return texCache[hex];
  }
  /* one lid function for the shared texture: the two eyes' loops averaged,
     the eye whose nose is at bearing 0 mirrored (phi → π − phi) so both read
     as 'nose at bearing π' */
  function lidOf(loops, mirror) {
    var have = [];
    for (var i = 0; i < loops.length; i++) if (loops[i]) have.push({ loop: loops[i], m: mirror[i] });
    if (!have.length) return null;
    return function (phi) {
      var t = 0;
      for (var j = 0; j < have.length; j++) {
        var ph = have[j].m ? Math.PI - phi : phi;
        t += loopTheta(have[j].loop, ((ph % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI));
      }
      return t / have.length;
    };
  }

  /* ── a studio for the catchlight: one big soft box up-left-front (where the
     key light is), a cool card on the right, a dark room ── */
  function eyeEnv(kind) {
    if (shared.env === null) buildEnvs();
    if (!shared.env) return null;
    return kind === 'soft' ? shared.envSoft : shared.env;
  }
  function buildEnvs() {
    shared.env = false;
    if (!CS3.renderer || !THREE.PMREMGenerator) return;
    try {
      var pm = new THREE.PMREMGenerator(CS3.renderer);
      shared.env = envScene(pm, 60.0, 0.12);   /* hot: the catchlight only, broad cards dark */
      pm.dispose();
      var pm2 = new THREE.PMREMGenerator(CS3.renderer);
      shared.envSoft = envScene(pm2, 20.0, 1.2); /* soft: the sclera's wet sheen */
      pm2.dispose();
    } catch (e) { console.warn('char_eyes env', e); shared.env = false; }
  }
  function envScene(pm, hot, broad) {
    {
      var sc = new THREE.Scene();
      sc.add(new THREE.Mesh(new THREE.BoxGeometry(16, 16, 16), new THREE.MeshBasicMaterial({ color: 0x2a2c30, side: THREE.BackSide })));
      function card(dir, w, h, col, k, dist, disc) {
        var mat = new THREE.MeshBasicMaterial({ color: col, side: THREE.DoubleSide });
        if (disc) {
          /* a soft-edged disc: radial gradient, white centre to black rim */
          var cv = document.createElement('canvas'); cv.width = cv.height = 128;
          var g2 = cv.getContext('2d'), gr = g2.createRadialGradient(64, 64, 0, 64, 64, 64);
          gr.addColorStop(0, '#fff'); gr.addColorStop(0.55, '#fff'); gr.addColorStop(1, '#000');
          g2.fillStyle = gr; g2.fillRect(0, 0, 128, 128);
          mat.map = new THREE.CanvasTexture(cv);
        }
        var m = new THREE.Mesh(disc ? new THREE.CircleGeometry(w * 0.5, 48) : new THREE.PlaneGeometry(w, h), mat);
        m.material.color.multiplyScalar(k);
        m.position.copy(dir).normalize().multiplyScalar(dist || 5);
        m.lookAt(0, 0, 0);
        sc.add(m);
      }
      /* 2026-09-22: the key is a SMALL, very bright card (0.9 × 0.7 m at
         5 m, ×60). The cornea reflects 2.5 % at normal incidence, so the
         old ×3.2 box gave a catchlight of 0.08 — invisible. ×60 saturates
         it, while its small solid angle (0.025 sr) adds only ~0.15 to the
         sclera's diffuse. The fill stays broad and dim. */
      if (broad < 0.5) {
        /* the HOT env's key is a soft-edged DISC 1.2 m at 5 m (14°): a round
           ~1 mm catchlight, not a window */
        card(new THREE.Vector3(0.8, 1.4, 1.6), 1.2, 1.2, 0xfff6ea, hot * 2.0, 5, true);
      } else {
        card(new THREE.Vector3(0.8, 1.4, 1.6), 2.2, 1.7, 0xfff6ea, hot);  /* the soft env keeps a broad key for the sheen */
      }
      card(new THREE.Vector3(0.8, 1.4, 1.6), 3.4, 2.8, 0xfff6ea, broad, 5.3);  /* its soft box round it, BEHIND it (coplanar, it hid the key) */
      card(new THREE.Vector3(1.4, 0.1, 1.4), 0.4, 0.4, 0xe8eefc, hot * 0.4); /* a second, small: the photograph's second glint */
      card(new THREE.Vector3(-1.4, 0.6, -1.0), 2.0, 2.4, 0xe9e2da, broad); /* fill, warm-neutral (the cool one tinted the sclera blue) */
      card(new THREE.Vector3(0, -1, 0.4), 4, 4, 0xb9a99a, 0.1 * broad);   /* floor bounce */
      return pm.fromScene(sc, 0.02).texture;
    }
  }

  /* ── socket occlusion (2026-09-22): the eye materials receive the scene's
     hemisphere/ambient irradiance scaled by CS_AMB — a globe in a socket sees
     little sky, and the flat fill was hiding the key light's spherical
     gradient (the photograph runs 220 → 110 across the sclera; ours ran
     226 → 178). Injected after lights_fragment_begin, so the env map and the
     direct lights are untouched. ── */
  function socketAmbient(mat, k) {
    if (!mat || mat.userData.csAmb) return mat;
    mat.userData.csAmb = true;
    var amb = (k || 0.3).toFixed(3);
    var prev = mat.onBeforeCompile;
    mat.onBeforeCompile = function (shader, renderer) {
      if (typeof prev === 'function') { try { prev.call(mat, shader, renderer); } catch (e) {} }
      shader.fragmentShader = shader.fragmentShader.replace('#include <lights_fragment_begin>',
        '#include <lights_fragment_begin>\nirradiance *= ' + amb + ';');
    };
    var prevKey = mat.customProgramCacheKey;
    mat.customProgramCacheKey = function () { return 'cs-amb-' + amb + '|' + (typeof prevKey === 'function' ? prevKey.call(mat) : ''); };
    mat.needsUpdate = true;
    return mat;
  }

  /* ── the geometry ─────────────────────────────────────────────────────── */
  /* forward axis of the body, in world space: the eyes stand in front of the
     head's centre, so the sign of (eye − head centre) along z is the answer */
  function forwardOf(model, eyes) {
    var box = new THREE.Box3().setFromObject(model), c = new THREE.Vector3(); box.getCenter(c);
    var zc = 0, i;
    var top = box.max.y, band = top - 0.13 * (box.max.y - box.min.y);
    var n = 0;
    model.traverse(function (o) {
      if (!o.isMesh || !o.geometry || /eye[lr]$/i.test(o.name || '') || /^cs-/.test(o.name || '')) return;
      var pa = o.geometry.attributes.position; if (!pa || pa.count < 5000) return;
      var v = new THREE.Vector3();
      for (var k = 0; k < pa.count; k += 7) {
        v.set(pa.getX(k), pa.getY(k), pa.getZ(k)).applyMatrix4(o.matrixWorld);
        if (v.y > band) { zc += v.z; n++; }
      }
    });
    zc = n ? zc / n : c.z;
    var ez = 0;
    for (i = 0; i < eyes.length; i++) ez += eyes[i].centre.z;
    ez /= eyes.length;
    return (ez >= zc) ? 1 : -1;
  }
  function bodyMesh(model) {
    var best = null, n = -1;
    model.traverse(function (o) {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      if (/eye[lr]$/i.test(o.name || '')) return;
      for (var p = o; p; p = p.parent) { if (/^cs-/.test(p.name || '') || p.name === 'CS3_DRESS') return; }
      var c = o.geometry.attributes.position.count;
      if (c > n) { n = c; best = o; }
    });
    return best;
  }

  /* the eye's frame in its OWN space: converged gaze f, up, right, centre, radius */
  function localBasis(mesh, fwdWorld, toNoseWorld) {
    var g = mesh.geometry;
    mesh.updateWorldMatrix(true, false);
    var inv = new THREE.Matrix4().copy(mesh.matrixWorld).invert();
    var nm = new THREE.Matrix3().getNormalMatrix(inv);
    var f = fwdWorld.clone().applyMatrix3(nm).normalize();
    var toNose = toNoseWorld.clone().applyMatrix3(nm).normalize();
    f.addScaledVector(toNose, Math.tan(CONVERGE)).normalize();
    var up = new THREE.Vector3(0, 1, 0).applyMatrix3(nm).normalize();
    var right = new THREE.Vector3().crossVectors(up, f).normalize();
    up.crossVectors(f, right).normalize();
    if (mesh.userData.csLocal) return { f: f, up: up, right: right, c: mesh.userData.csLocal.c.clone(), R: mesh.userData.csLocal.R };
    g.computeBoundingSphere();
    return { f: f, up: up, right: right, c: g.boundingSphere.center.clone(), R: g.boundingSphere.radius };
  }
  /* the same frame in WORLD space (for the lid loop and the lashes) */
  function worldBasis(eye, fwdWorld, toNoseWorld) {
    var f = fwdWorld.clone().addScaledVector(toNoseWorld, Math.tan(CONVERGE)).normalize();
    var up = new THREE.Vector3(0, 1, 0);
    var right = new THREE.Vector3().crossVectors(up, f).normalize();
    up.crossVectors(f, right).normalize();
    return { f: f, up: up, right: right, c: eye.centre.clone(), R: eye.R };
  }

  /* polar UVs about the gaze, radial normals, and the iris DISH: the cap
     inside the limbus is flattened onto the limbus plane and hollowed a
     little, so the iris sits behind the cornea (anterior chamber ≈ 2.5 mm
     on a 12 mm globe once the cornea is on) */
  /* the body's eyeball is 2 176 vertices (1 088 triangles): at macro the
     sharp pupil edge showed the facets as a hexagon. Rebuilt as a sphere of
     rings ABOUT THE GAZE, rings crowded to the front (theta ∝ (i/NR)^1.6:
     31 rings inside the limbus, 15 inside the pupil), same centre and radius
     in the mesh's own space. 2026-09-22. */
  function denseSphere(B, t0, t1, NR, pw) {
    var NS = 160, pos = [], idx = [], i, j;
    for (i = 0; i <= NR; i++) {
      var theta = t0 + (t1 - t0) * Math.pow(i / NR, pw), sT = Math.sin(theta), cT = Math.cos(theta);
      for (j = 0; j <= NS; j++) {
        var phi = j / NS * Math.PI * 2, cp = Math.cos(phi), sp = Math.sin(phi);
        pos.push(B.c.x + B.R * (B.f.x * cT + (B.right.x * cp + B.up.x * sp) * sT),
                 B.c.y + B.R * (B.f.y * cT + (B.right.y * cp + B.up.y * sp) * sT),
                 B.c.z + B.R * (B.f.z * cT + (B.right.z * cp + B.up.z * sp) * sT));
      }
    }
    for (i = 0; i < NR; i++) for (j = 0; j < NS; j++) {
      var a0 = i * (NS + 1) + j, a1 = a0 + 1, b0 = a0 + NS + 1, b1 = b0 + 1;
      if (i > 0 || t0 > 0) idx.push(a0, b0, a1);
      if (i < NR - 1 || t1 < Math.PI) idx.push(a1, b0, b1);
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    return g;
  }
  /* 2026-09-22: the eye is TWO meshes sharing one texture. The body's eye
     mesh becomes the SCLERA (a sphere open at the front, theta ≥ 29.2°):
     wet — clearcoat, an environment to reflect. A new 'cs-iris' cap
     (theta ≤ 29.2°, dished) carries the IRIS: matte, the fibre normal map,
     NO environment fill (its irradiance had lifted every iris shadow into a
     haze). The rims coincide vertex for vertex. */
  function polarUVs(mesh, B) {
    if (!mesh.geometry.userData.csDense) {
      var old = mesh.geometry, ng = denseSphere(B, IRIS_THETA, Math.PI, 64, 1.0);
      ng.userData.csDense = true;
      mesh.geometry = ng;
      mesh.userData.csLocal = { c: B.c.clone(), R: B.R };
      if (old && old.dispose && !old.userData.csKeep) { try { old.dispose(); } catch (e) {} }
    }
    polarize(mesh.geometry, B);
  }
  function irisCap(B) {
    var g = denseSphere(B, 0, IRIS_THETA, 40, 1.3);
    polarize(g, B);
    return g;
  }
  function polarize(g, B) {
    var pa = g.attributes.position;
    if (!pa) return;
    var f = B.f, up = B.up, right = B.right, c = B.c, R = B.R;
    var uv = new Float32Array(pa.count * 2), d = new THREE.Vector3();
    var nn = new Float32Array(pa.count * 3);
    var cosL = Math.cos(IRIS_THETA);
    for (var i = 0; i < pa.count; i++) {
      d.set(pa.getX(i) - c.x, pa.getY(i) - c.y, pa.getZ(i) - c.z);
      var len = d.length() || R; d.divideScalar(len);
      var cosT = Math.max(-1, Math.min(1, d.dot(f)));
      var theta = Math.acos(cosT);
      var phi = Math.atan2(d.dot(up), d.dot(right));
      var r = rOf(theta) * 0.5;
      uv[i * 2] = 0.5 + r * Math.cos(phi);
      uv[i * 2 + 1] = 0.5 + r * Math.sin(phi);
      /* the bundle's eyeball normals are split per face; the radial direction
         IS the normal of a sphere — smooth, exact */
      nn[i * 3] = d.x; nn[i * 3 + 1] = d.y; nn[i * 3 + 2] = d.z;
      if (theta < IRIS_THETA) {
        var t = theta / IRIS_THETA;
        var rho = R * cosL / Math.max(cosL, cosT) - DISH * R * (1 - t * t);
        pa.setXYZ(i, c.x + d.x * rho, c.y + d.y * rho, c.z + d.z * rho);
        /* a shallow dish: mostly the gaze direction, tilting outward at the rim */
        var k = 0.35 * t;
        nn[i * 3] = f.x + d.x * k; nn[i * 3 + 1] = f.y + d.y * k; nn[i * 3 + 2] = f.z + d.z * k;
        var L = Math.hypot(nn[i * 3], nn[i * 3 + 1], nn[i * 3 + 2]);
        nn[i * 3] /= L; nn[i * 3 + 1] /= L; nn[i * 3 + 2] /= L;
      }
    }
    pa.needsUpdate = true;
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.attributes.uv.needsUpdate = true;
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nn, 3));
    g.attributes.normal.needsUpdate = true;
    g.computeBoundingSphere(); g.computeBoundingBox();
  }

  /* ── the lids, measured: per bearing round the gaze, the innermost body
     vertex (smallest theta) that is not the conjunctival back of the lid
     (those sit INSIDE the globe). Returns theta of the lid edge, its point
     and normal, per bin, smoothed. Bearing 0 = right (temple for the left
     eye), π/2 = up. World space. ── */
  function lidLoop(body, W) {
    var NB = LOOP_BINS, th = new Float32Array(NB), pts = [], nrm = [], i;
    for (i = 0; i < NB; i++) { th[i] = Infinity; pts.push(null); nrm.push(null); }
    if (!body) return null;
    body.updateWorldMatrix(true, false);
    var pa = body.geometry.attributes.position, na = body.geometry.attributes.normal;
    var m = body.matrixWorld, nm = new THREE.Matrix3().getNormalMatrix(m);
    var v = new THREE.Vector3(), n = new THREE.Vector3(), d = new THREE.Vector3();
    var c = W.c, R = W.R, lim = R * 1.7, inner = -0.03 * R;
    for (i = 0; i < pa.count; i++) {
      v.set(pa.getX(i), pa.getY(i), pa.getZ(i)).applyMatrix4(m);
      d.subVectors(v, c);
      var len = d.length();
      if (len > lim || len - R < inner) continue;
      d.divideScalar(len);
      var cosT = d.dot(W.f);
      if (cosT < 0.2) continue;
      var theta = Math.acos(Math.min(1, cosT));
      var phi = Math.atan2(d.dot(W.up), d.dot(W.right));
      var b = ((Math.round(phi / (2 * Math.PI) * NB) % NB) + NB) % NB;
      if (theta < th[b]) {
        th[b] = theta;
        pts[b] = v.clone();
        if (na) { n.set(na.getX(i), na.getY(i), na.getZ(i)).applyMatrix3(nm).normalize(); nrm[b] = n.clone(); }
        else nrm[b] = d.clone();
      }
    }
    /* fill gaps from the neighbours, then smooth round the loop */
    var have = 0;
    for (i = 0; i < NB; i++) if (pts[i]) have++;
    if (have < NB * 0.6) return null;
    for (i = 0; i < NB; i++) {
      if (pts[i]) continue;
      var a = i, bb = i, k;
      for (k = 1; k < NB; k++) { a = (i - k + NB) % NB; if (pts[a]) break; }
      for (k = 1; k < NB; k++) { bb = (i + k) % NB; if (pts[bb]) break; }
      pts[i] = pts[a].clone().lerp(pts[bb], 0.5); nrm[i] = nrm[a].clone().lerp(nrm[bb], 0.5).normalize();
      th[i] = 0.5 * (th[a] + th[bb]);
    }
    function smooth(arrP, arrT) {
      var P2 = [], T2 = new Float32Array(NB);
      for (var j = 0; j < NB; j++) {
        var jm = (j - 1 + NB) % NB, jp = (j + 1) % NB;
        P2.push(arrP[jm].clone().multiplyScalar(0.25).addScaledVector(arrP[j], 0.5).addScaledVector(arrP[jp], 0.25));
        T2[j] = 0.25 * arrT[jm] + 0.5 * arrT[j] + 0.25 * arrT[jp];
      }
      return { P: P2, T: T2 };
    }
    var s1 = smooth(pts, th), s2 = smooth(s1.P, s1.T);
    return { n: NB, theta: s2.T, pts: s2.P, nrm: nrm, f: W.f, up: W.up, right: W.right, c: W.c, R: W.R };
  }
  function loopTheta(loop, phi) {
    if (!loop) return Infinity;
    var NB = loop.n, x = phi / (2 * Math.PI) * NB;
    var i0 = Math.floor(x), t = x - i0;
    var b = ((i0 % NB) + NB) % NB, a = (b + NB - 1) % NB, c = (b + 1) % NB, d = (b + 2) % NB;
    /* Catmull-Rom across the bins: linear gave the cornea's lid fade a crease
       at every bin, and the refraction through the creases rippled the iris */
    var T = loop.theta, t2 = t * t, t3 = t2 * t;
    return 0.5 * ((2 * T[b]) + (-T[a] + T[c]) * t + (2 * T[a] - 5 * T[b] + 4 * T[c] - T[d]) * t2 + (-T[a] + 3 * T[b] - 3 * T[c] + T[d]) * t3);
  }

  /* the cornea cap, in the eye's own frame; the bulge fades to nothing
     short of the lid edge in every bearing */
  function corneaGeometry(B, loop) {
    var NR = 36, NS = 128, R = B.R, pos = [], idx = [], i, j;
    var rc = CORNEA.rc, off = CORNEA.off;
    for (i = 0; i <= NR; i++) {
      var theta = CORNEA.capTheta * Math.pow(i / NR, 0.8);
      var sinT = Math.sin(theta), cosT = Math.cos(theta);
      var rhoC = off * cosT + Math.sqrt(Math.max(0, rc * rc - off * off * sinT * sinT));
      var bulge = Math.max(0, rhoC - 1) * CORNEA.k;
      for (j = 0; j <= NS; j++) {
        var phi = j / NS * Math.PI * 2;
        var te = loopTheta(loop, phi), S = 1;
        if (isFinite(te)) {
          var a = te - LID_FADE_IN, b = te - LID_FADE_END;
          if (theta >= b) S = 0;
          else if (theta > a) { var u = (theta - a) / (b - a); S = 1 - u * u * (3 - 2 * u); }
        }
        var rho = R * (1 + Math.max(CORNEA.lift, bulge * S));
        var dx = B.right.x * Math.cos(phi) + B.up.x * Math.sin(phi);
        var dy = B.right.y * Math.cos(phi) + B.up.y * Math.sin(phi);
        var dz = B.right.z * Math.cos(phi) + B.up.z * Math.sin(phi);
        pos.push(B.c.x + (B.f.x * cosT + dx * sinT) * rho,
                 B.c.y + (B.f.y * cosT + dy * sinT) * rho,
                 B.c.z + (B.f.z * cosT + dz * sinT) * rho);
      }
    }
    for (i = 0; i < NR; i++) for (j = 0; j < NS; j++) {
      var a0 = i * (NS + 1) + j, a1 = a0 + 1, b0 = a0 + NS + 1, b1 = b0 + 1;
      idx.push(a0, b0, b1, a0, b1, a1);
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    /* the pole shares NS+1 coincident vertices: their averaged normals are
       right, but make the apex exact */
    var nn = g.attributes.normal;
    for (j = 0; j <= NS; j++) nn.setXYZ(j, B.f.x, B.f.y, B.f.z);
    return g;
  }

  /* tear film along the lower lid margin: a glassy tube in world space,
     from the loop's lower arc (bearings π … 2π) */
  function meniscusGeometry(loop) {
    if (!loop || !THREE.CatmullRomCurve3 || !THREE.TubeGeometry) return null;
    var NB = loop.n, pts = [], i;
    var i0 = Math.round(NB * 0.56), i1 = Math.round(NB * 0.95);
    /* the same 3× smoothing as the margin strip, so the line has no facets */
    var sm = [];
    for (i = 0; i < NB; i++) sm.push(loop.pts[i].clone());
    for (var r = 0; r < 3; r++) {
      var s2 = [];
      for (i = 0; i < NB; i++) s2.push(sm[(i - 1 + NB) % NB].clone().multiplyScalar(0.25).addScaledVector(sm[i], 0.5).addScaledVector(sm[(i + 1) % NB], 0.25));
      sm = s2;
    }
    for (i = i0; i <= i1; i++) {
      var p = sm[i % NB].clone();
      /* on the globe, at the lid's edge, a hair forward */
      var d = p.clone().sub(loop.c).normalize();
      p.copy(loop.c).addScaledVector(d, loop.R + 0.0004);
      pts.push(p);
    }
    if (pts.length < 4) return null;
    var curve = new THREE.CatmullRomCurve3(pts, false, 'centripetal', 0.5);
    return new THREE.TubeGeometry(curve, 160, loop.R * 0.0065, 6, false);   /* 0.15 mm across, 160 segments */
  }

  /* ── the lid MARGIN (2026-09-22): the lids on this body are a skin sheet
     whose edge sits 0–1.5 mm off the globe; between that edge and the globe
     the photograph shows the margin — a wet pink waterline along the lower
     lid. A 2-row strip along the LOWER lid's loop arc, vertex-coloured:
     row 0 a 0.5 mm lip towards the globe (the wet edge), row 1 at the lid
     edge a hair forward and out. World space. ── */
  function marginGeometry(loop) {
    if (!loop) return null;
    var NB = loop.n, pos = [], col = [], idx = [], i, r;
    var c = loop.c, R = loop.R, f = loop.f;
    var P = new THREE.Vector3(), d = new THREE.Vector3(), T = new THREE.Vector3();
    var UP = [[120, 78, 70], [110, 70, 62]];          /* (unused: the strip is lower-lid only) */
    var LO = [[196, 138, 124], [186, 126, 112]];      /* lower: lid skin, barely pinker than the face */
    /* the loop's points zigzag between mesh rows; smooth them twice more for
       the strip (the lashes keep the measured points) */
    var sm = [];
    for (i = 0; i < NB; i++) sm.push(loop.pts[i].clone());
    for (r = 0; r < 3; r++) {
      var s2 = [];
      for (i = 0; i < NB; i++) s2.push(sm[(i - 1 + NB) % NB].clone().multiplyScalar(0.25).addScaledVector(sm[i], 0.5).addScaledVector(sm[(i + 1) % NB], 0.25));
      sm = s2;
    }
    /* the LOWER lid only (bins from just past the inner corner round the
       bottom to just short of the outer): the upper lid's edge is under the
       lashes and its own shadow, and a strip there rendered as a pale band */
    /* the arc as ONE smooth curve (Catmull-Rom through the smoothed bins,
       sampled 6× finer): the bins showed as straight facets at the corners */
    var i0 = Math.round(NB * 0.56), i1 = Math.round(NB * 0.95), ctrl = [];
    for (var ii = i0; ii <= i1; ii++) ctrl.push(sm[ii % NB].clone());
    var curve = new THREE.CatmullRomCurve3(ctrl, false, 'centripetal', 0.5);
    var NS = (i1 - i0) * 6, n = 0;
    for (var k2 = 0; k2 <= NS; k2++) {
      n++;
      var phi = (i0 + (i1 - i0) * k2 / NS) / NB * Math.PI * 2, sn = Math.sin(phi);
      var t = sstep(-0.18, 0.18, sn);                 /* 1 = upper lid, 0 = lower, blended at the corners */
      P.copy(curve.getPoint(k2 / NS));
      d.subVectors(P, c).normalize();
      T.copy(d).addScaledVector(f, -d.dot(f)).normalize();
      var gap = Math.max(0, P.distanceTo(c) - R * (1 + MARGIN.back));
      var rows = [
        P.clone().addScaledVector(d, -Math.min(gap, MARGIN.lip)),
        P.clone().addScaledVector(f, MARGIN.fwd).addScaledVector(T, MARGIN.side)
      ];
      for (r = 0; r < 2; r++) {
        pos.push(rows[r].x, rows[r].y, rows[r].z);
        var cu = UP[r], cl = LO[r];
        col.push((cl[0] + (cu[0] - cl[0]) * t) / 255, (cl[1] + (cu[1] - cl[1]) * t) / 255, (cl[2] + (cu[2] - cl[2]) * t) / 255);
      }
    }
    for (i = 0; i < n - 1; i++) {
      var a = i * 2, b = (i + 1) * 2;
      idx.push(a, b, b + 1, a, b + 1, a + 1);
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    var cc = new THREE.Float32BufferAttribute(col, 3);
    g.setAttribute('color', cc);
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }

  /* ── distance LOD (2026-09-22): at body distance the eye is 6 px across;
     the cornea shell (a transmission pass + a saturated env reflection at
     its grazing rim) and 450 sub-pixel lashes turned it into a pale disc.
     Per frame, from the eye's projected radius: the cornea is hidden under
     CORNEA_MIN_PX, the lashes fade out between 30 and 6 px. Hooked on the
     scene's onBeforeRender (called once per render, before the render list
     is built, so the change is visible in the same frame), chained. ── */
  /* eye radius in px at which a lash ribbon is finally wide enough to be
     drawn solid; below it the row is faded toward a soft line */
  var LASH_FULL_PX = 150;

  function installFade(model) {
    var sc = model;
    while (sc && sc.parent) sc = sc.parent;
    if (!sc || !sc.isScene || sc.userData.csEyeFade) return;
    sc.userData.csEyeFade = true;
    var prev = sc.onBeforeRender;
    var w = new THREE.Vector3();
    sc.onBeforeRender = function (renderer, scene, camera) {
      if (typeof prev === 'function') { try { prev.apply(this, arguments); } catch (e) {} }
      if (!camera || !camera.isPerspectiveCamera) return;
      var k = 0.5 * renderer.domElement.height / Math.tan(camera.fov * Math.PI / 360);
      var px = 0, corneas = [], lashes = [];
      scene.traverse(function (o) {
        if (o.name === 'cs-eye' && o.userData.R) {
          o.getWorldPosition(w);
          var p = o.userData.R * k / Math.max(1e-4, w.distanceTo(camera.position));
          px = Math.max(px, p);
          o.userData.px = p;
          corneas.push(o);
        } else if (o.name === 'cs-lashes-mesh') lashes.push(o);
      });
      var i;
      for (i = 0; i < corneas.length; i++) {
        var cm = corneas[i].getObjectByName('cs-cornea');
        if (cm) cm.visible = corneas[i].userData.px > CORNEA_MIN_PX;
      }
      /* 2026-09-23: the fade only ran 6 -> 30 px, so from 30 px upward every
         one of the ~230 near-black lashes per lid was drawn at full opacity
         while each ribbon still covered well UNDER a pixel. Sub-pixel opaque
         geometry cannot be resolved by a rasteriser: at head framing (~45 px
         of eye radius) they aliased into the black crust round the lid an
         operator called out. A lash only earns full opacity once it is wide
         enough on screen to BE a lash — so the ramp continues to LASH_FULL_PX,
         and in between the lashes read as the soft dark line a real lash row
         reads as at that distance, instead of as 230 hard slivers. */
      var op = Math.min(1, Math.max(0, (px - 6) / 24))
             * (0.34 + 0.66 * Math.min(1, Math.max(0, (px - 30) / (LASH_FULL_PX - 30))));
      for (i = 0; i < lashes.length; i++) {
        var m = lashes[i].material;
        if (!m) continue;
        if (m.opacity !== op) { m.opacity = op; m.transparent = true; }
        lashes[i].visible = op > 0.02;
      }
    };
  }

  /* ── apply ───────────────────────────────────────────────────────────── */
  function eyeMeshes(model) {
    var out = [];
    model.traverse(function (o) {
      if (!o.isMesh || !/eye[lr]$/i.test(o.name || '')) return;
      var c = new THREE.Vector3(), R;
      if (o.userData.csLocal) {
        /* the sclera sphere is open at the front: its box centre would sit
           0.76 mm back — use the globe centre measured before the rebuild */
        o.updateWorldMatrix(true, false);
        c.copy(o.userData.csLocal.c).applyMatrix4(o.matrixWorld);
        R = o.userData.csLocal.R * o.matrixWorld.getMaxScaleOnAxis();
      } else {
        var b = new THREE.Box3().setFromObject(o), sz = new THREE.Vector3();
        b.getCenter(c); b.getSize(sz);
        R = 0.5 * Math.max(sz.x, sz.y, sz.z);
      }
      out.push({ mesh: o, centre: c, R: R });
    });
    return out;
  }
  function disposeExtras(mesh) {
    var g = mesh.userData.csEyeGroup;
    if (!g) return;
    if (g.parent) g.parent.remove(g);
    g.traverse(function (o) { if (o.isMesh && o.geometry) o.geometry.dispose(); });
    mesh.userData.csEyeGroup = null;
  }

  /* model: the figure; store: where the materials are kept (CS3 or Compare's);
     colourWord: the bible's identity.eye_color (word or hex) */
  function applyFor(model, store, colourWord) {
    if (!model) return 0;
    var t0 = performance.now();
    var eyes = eyeMeshes(model);
    if (!eyes.length) return 0;
    var hex = irisHex(low(colourWord));
    var env = eyeEnv('soft'), envHot = eyeEnv('hot');
    var mat = store._eyeMatReal;
    if (!mat) {
      /* the SCLERA: wet, reflecting the studio */
      mat = store._eyeMatReal = new THREE.MeshPhysicalMaterial({
        color: 0xffffff, roughness: 0.38, metalness: 0,
        clearcoat: 1.0, clearcoatRoughness: 0.22,
        envMap: env, envMapIntensity: 0.34
      });
      socketAmbient(mat, 0.3);
    }
    var imat = store._irisMat;
    if (!imat) {
      /* the IRIS: matte, fibres in relief, no environment fill */
      /* specularIntensity 0: the 4 % dielectric sheen at roughness 0.6 put a
         grey veil (34/255) over the pupil and every crypt — measured with the
         cornea hidden and the lights off; the wet specular is the cornea's */
      imat = store._irisMat = new THREE.MeshPhysicalMaterial({
        color: 0xffffff, roughness: 0.6, metalness: 0, clearcoat: 0, specularIntensity: 0,
        normalScale: new THREE.Vector2(1.0, 1.0)
      });
      socketAmbient(imat, 0.3);
    }
    var applyTex = function (lidFn) {
      if (store._eyeHex === hex) return;
      mat.map = texture(hex, lidFn);
      mat.needsUpdate = true;
      imat.map = mat.map;
      imat.normalMap = shared.normal;
      imat.needsUpdate = true;
      store._eyeHex = hex;
    };
    var cmat = store._corneaMat;
    if (!cmat) {
      /* thickness = half the anterior chamber (1.2 mm; 2 mm decentred the limbus 0.7 mm against the pupil): the transmission ray is
         refracted over that depth, so the iris is seen THROUGH a lens —
         magnified a little, shifted at the rim — not painted on the sphere */
      cmat = store._corneaMat = new THREE.MeshPhysicalMaterial({
        color: 0xffffff, metalness: 0, roughness: 0.0,
        transmission: 1.0, thickness: 0.0012, ior: 1.376,
        clearcoat: 0, specularIntensity: 1.0,
        envMap: envHot, envMapIntensity: 1.0, side: THREE.FrontSide
      });
    }
    var tmat = store._tearMat;
    if (!tmat) {
      tmat = store._tearMat = new THREE.MeshPhysicalMaterial({
        color: 0xf2e8e2, metalness: 0, roughness: 0.12, transparent: true, opacity: 0.45,
        clearcoat: 1, clearcoatRoughness: 0.12, envMap: env, envMapIntensity: 0.5, depthWrite: false
      });
    }
    var mmat = store._marginMat;
    if (!mmat) {
      mmat = store._marginMat = new THREE.MeshPhysicalMaterial({
        color: 0xffffff, vertexColors: true, metalness: 0, roughness: 0.3,
        clearcoat: 0.6, clearcoatRoughness: 0.15, envMap: env, envMapIntensity: 0.15, side: THREE.DoubleSide,
        transparent: true, opacity: 0.4, depthWrite: false
      });
      socketAmbient(mmat, 0.3);
    }
    var fwdSign = forwardOf(model, eyes);
    var fwd = new THREE.Vector3(0, 0, fwdSign);
    var body = bodyMesh(model);
    var mx = 0;
    for (var i = 0; i < eyes.length; i++) mx += eyes[i].centre.x;
    mx /= eyes.length;
    var loops = [], mirror = [], Ws = [];
    for (i = 0; i < eyes.length; i++) {
      var toNose0 = new THREE.Vector3((eyes[i].centre.x < mx) ? 1 : -1, 0, 0);
      Ws.push(worldBasis(eyes[i], fwd, toNose0));
      loops.push(lidLoop(body, Ws[i]));
      /* nose at bearing 0 when toNose runs along +right */
      mirror.push(toNose0.dot(Ws[i].right) > 0);
    }
    applyTex(lidOf(loops, mirror));
    for (i = 0; i < eyes.length; i++) {
      var e = eyes[i];
      var toNose = new THREE.Vector3((e.centre.x < mx) ? 1 : -1, 0, 0);
      var W = Ws[i];
      var loop = loops[i];
      var LB = localBasis(e.mesh, fwd, toNose);
      if (!e.mesh.geometry.userData.csPolar) {
        polarUVs(e.mesh, LB);
        e.mesh.geometry.userData.csPolar = true;
      }
      e.mesh.material = mat;
      /* the cornea + tear film: a sibling group in the eye's own frame */
      if (!e.mesh.userData.csEyeGroup || e.mesh.userData.csEyeGroup.parent !== e.mesh.parent) {
        disposeExtras(e.mesh);
        var grp = new THREE.Group();
        grp.name = 'cs-eye';
        grp.position.copy(e.mesh.position); grp.quaternion.copy(e.mesh.quaternion); grp.scale.copy(e.mesh.scale);
        /* both are built in WORLD space (the loop's frame) and brought into
           the group's frame, so the lid bearings line up whatever the eye
           node's own transform is */
        e.mesh.parent.updateWorldMatrix(true, false);
        grp.updateMatrix();
        var toGrp = new THREE.Matrix4().multiplyMatrices(e.mesh.parent.matrixWorld, grp.matrix).invert();
        /* the iris cap is built in the eye's OWN frame — the group carries
           the eye node's transform, so it drops straight in */
        var im = new THREE.Mesh(irisCap(LB), imat);
        im.name = 'cs-iris';
        grp.add(im);
        var cg = corneaGeometry(W, loop);
        cg.applyMatrix4(toGrp);
        var cm = new THREE.Mesh(cg, cmat);
        cm.name = 'cs-cornea'; cm.renderOrder = 2;
        grp.add(cm);
        var tg = meniscusGeometry(loop);
        if (tg) {
          var tm = new THREE.Mesh(tg, tmat);
          tm.name = 'cs-tear'; tm.renderOrder = 3;
          tg.applyMatrix4(toGrp);
          grp.add(tm);
        }
        var mg = marginGeometry(loop);
        if (mg) {
          var mm = new THREE.Mesh(mg, mmat);
          mm.name = 'cs-margin'; mm.renderOrder = 1;
          mg.applyMatrix4(toGrp);
          grp.add(mm);
        }
        grp.userData.R = e.R;
        e.mesh.parent.add(grp);
        e.mesh.userData.csEyeGroup = grp;
      } else {
        e.mesh.userData.csEyeGroup.traverse(function (o) {
          if (o.name === 'cs-iris') o.material = imat;
          if (o.name === 'cs-cornea') o.material = cmat;
          if (o.name === 'cs-tear') o.material = tmat;
          if (o.name === 'cs-margin') o.material = mmat;
        });
      }
    }
    installFade(model);
    store._eyeLoops = loops;
    store._eyeMs = performance.now() - t0;
    return eyes.length;
  }

  /* ── skin at close range: pores and creases as a world-space bump ─────
     Installed on a MeshStandard/Physical material through onBeforeCompile.
     The height field is analytic (Worley pores at ~0.38 mm, two octaves of
     value noise, ridged crease lines); its screen-space derivative perturbs
     the normal the way bumpMap does. The strength is scaled by the world
     size of a pixel: at a full-body distance (≈1 mm per pixel) it is zero,
     so nothing shimmers and the far view is exactly what it was. ── */
  var SKIN_GLSL = [
    'varying vec3 vCsW;',
    'float csHash(vec3 p){ p = fract(p * vec3(0.1031, 0.1030, 0.0973)); p += dot(p, p.yxz + 33.33); return fract((p.x + p.y) * p.z); }',
    'float csNoise(vec3 x){ vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);',
    '  return mix(mix(mix(csHash(i), csHash(i + vec3(1,0,0)), f.x), mix(csHash(i + vec3(0,1,0)), csHash(i + vec3(1,1,0)), f.x), f.y),',
    '             mix(mix(csHash(i + vec3(0,0,1)), csHash(i + vec3(1,0,1)), f.x), mix(csHash(i + vec3(0,1,1)), csHash(i + vec3(1,1,1)), f.x), f.y), f.z); }',
    'float csPores(vec3 p){ vec3 i = floor(p), f = fract(p); float d1 = 9.0, d2 = 9.0, depth = 0.0;',
    '  for (int z = -1; z <= 1; z++) for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {',
    '    vec3 g = vec3(float(x), float(y), float(z));',
    '    vec3 o = vec3(csHash(i + g), csHash(i + g + 7.1), csHash(i + g + 13.7));',
    '    vec3 r = g + o - f; float dd = dot(r, r);',
    '    if (dd < d1) { d2 = d1; d1 = dd; depth = csHash(i + g + 3.3); } else if (dd < d2) { d2 = dd; } }',
    '  float rad = 0.16 + 0.14 * depth;',
    '  float pore = 1.0 - smoothstep(0.0, rad, sqrt(d1));',
    '  /* the cell borders are the fine furrow network of skin micro-relief */',
    '  float edge = 1.0 - smoothstep(0.0, 0.10, sqrt(d2) - sqrt(d1));',
    '  return -pore * pore * step(0.35, depth) - 0.12 * edge; }',
    'float csSkinH(vec3 w){ vec3 p = w * 2600.0;',
    '  float h = 0.7 * csPores(p);',
    '  h += 0.4 * (csNoise(p * 0.45) - 0.5) + 0.2 * (csNoise(p * 1.6 + 31.0) - 0.5);',
    '  return h; }'
  ].join('\n');
  var SKIN_PERTURB = [
    '{',
    '  float csPx = length(fwidth(vCsW));',
    '  float csK = 1.0 - smoothstep(0.00012, 0.00050, csPx);',
    '  float csH0 = csSkinH(vCsW);',
    '  vec2 csDH = vec2(dFdx(csH0), dFdy(csH0)) * (CS_BUMP * csK);',
    '  vec3 csSp = -vViewPosition;',
    '  vec3 csSx = dFdx(csSp), csSy = dFdy(csSp);',
    '  vec3 csR1 = cross(csSy, normal), csR2 = cross(normal, csSx);',
    '  float csDet = dot(csSx, csR1);',
    '  vec3 csG = sign(csDet) * (csDH.x * csR1 + csDH.y * csR2);',
    '  normal = normalize(abs(csDet) * normal - csG);',
    '}'
  ].join('\n');
  function skinMicro(mat, bump) {
    if (!mat || mat.userData.csMicro) return mat;
    mat.userData.csMicro = true;
    var amp = (bump || 0.000045).toExponential(3);
    var prev = mat.onBeforeCompile;
    mat.onBeforeCompile = function (shader, renderer) {
      if (typeof prev === 'function') { try { prev.call(mat, shader, renderer); } catch (e) {} }
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec3 vCsW;')
        .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvCsW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\n#define CS_BUMP ' + amp + '\n' + SKIN_GLSL)
        .replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>\n' + SKIN_PERTURB);
    };
    var prevKey = mat.customProgramCacheKey;
    mat.customProgramCacheKey = function () {
      return 'cs-skin-micro-' + amp + '|' + (typeof prevKey === 'function' ? prevKey.call(mat) : '');
    };
    mat.needsUpdate = true;
    return mat;
  }

  function run() {
    if (!CS3 || CS3.failed || !CS3.model) return;
    applyFor(CS3.model, CS3, pageVal('identity.eye_color'));
  }
  CS3_HOOKS.push(function (why) {
    try { run(); } catch (e) { console.warn('char_eyes', why, e); }
  });
  if (CS3.model) { try { run(); } catch (e) { console.warn('char_eyes init', e); } }

  window.CSEYES = { applyFor: applyFor, run: run, irisHex: irisHex, texture: texture,
                    skinMicro: skinMicro, lidLoop: lidLoop, loopTheta: loopTheta,
                    eyeMeshes: eyeMeshes, worldBasis: worldBasis, forwardOf: forwardOf,
                    bodyMesh: bodyMesh, env: eyeEnv, shared: shared, installFade: installFade };
})();
