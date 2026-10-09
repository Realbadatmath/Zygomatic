// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* openings_special — the openings the built-in `window`/`door` pair cannot say:
   window_arch (round-topped), window_round (a bullseye), window_bay (a
   three-sided box projecting OUT of the wall, toward local -Z), window_strip
   (a ribbon), door_garage, door_sliding, door_french — plus curtain_wall,
   which is NOT an opening but a whole glazed wall face.

   Local frame, same as the built-in `case 'window'`: origin on the wall line
   at the record's x/z, +X along the wall, +Y up from the record's y (the
   storey base), Z = the wall's thickness direction. Openings register in
   AR_EXT.openings so arSyncHoles cuts the wall; the hole is always the
   RECTANGLE p.w x p.h at p.sill — the arch and the circle are frame drawn in
   front of it, which is why window_round carries w = h = 2r alongside r. */
(function(){
  var FT = 0.06;          // frame section
  var WT = 0.16;          // frame depth through the wall (built-in window: 0.06 + 0.10)

  /* an elliptical ring (arch head / round frame) standing in the XY plane and
     extruded through the wall thickness. a0..a1 in radians. */
  function ringG(k, cx, cy, rxi, ryi, rxo, ryo, a0, a1, depth, seg){
    var THREE = k.THREE, sh = new THREE.Shape();
    sh.absellipse(cx, cy, rxo, ryo, a0, a1, false);
    sh.absellipse(cx, cy, rxi, ryi, a1, a0, true);
    sh.closePath();
    var g = new THREE.ExtrudeGeometry(sh, {depth: depth, bevelEnabled: false, curveSegments: seg});
    g.translate(0, 0, -depth / 2);
    g.computeVertexNormals();
    return g;
  }

  /* a filled ellipse (the glass behind an arch head or a round frame) */
  function discG(k, cx, cy, rx, ry, a0, a1, seg){
    var THREE = k.THREE, sh = new THREE.Shape();
    sh.absellipse(cx, cy, rx, ry, a0, a1, false);
    sh.closePath();
    var g = new THREE.ExtrudeGeometry(sh, {depth: 0.012, bevelEnabled: false, curveSegments: seg});
    g.translate(0, 0, -0.006);
    g.computeVertexNormals();
    return g;
  }

  /* a plan polygon extruded UPWARDS. pts are (x, v) with v mapped to -Z — the
     same handedness as curved_walls.js: rotateX(-90) sends shape +Y to -Z and
     the extrusion +Z to +Y. */
  function planPrismG(k, pts, hgt, y0){
    var THREE = k.THREE, sh = new THREE.Shape(), i;
    sh.moveTo(pts[0][0], pts[0][1]);
    for(i = 1; i < pts.length; i++) sh.lineTo(pts[i][0], pts[i][1]);
    sh.closePath();
    var g = new THREE.ExtrudeGeometry(sh, {depth: hgt, bevelEnabled: false});
    g.rotateX(-Math.PI / 2);
    g.translate(0, y0 || 0, 0);
    g.computeVertexNormals();
    return g;
  }

  /* a thin pane between two plan points, standing from y0 to y0+hgt */
  function paneG(k, ax, az, bx, bz, hgt, y0, inset){
    var THREE = k.THREE;
    var dx = bx - ax, dz = bz - az, L = Math.sqrt(dx * dx + dz * dz) - (inset || 0);
    if(L < 0.02) return null;
    var g = new THREE.BoxGeometry(L, hgt, 0.012);
    g.rotateY(Math.atan2(-dz, dx));
    g.translate((ax + bx) / 2, y0 + hgt / 2, (az + bz) / 2);
    return g;
  }

  /* ── a round-topped window ───────────────────────────────────────────────
     p.h is the height to the SPRINGING; p.arch is the rise above it. */
  AR_EXT.geom.window_arch = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 1.2), h = N('h', 1.4), sill = N('sill', 0.9), arch = N('arch', N('w', 1.2) / 2);
    if(arch < 0.05) arch = 0.05;
    var P = [];
    P.push({g: k.box(FT, h, WT, -(w / 2 + FT / 2), sill + h / 2, 0)});          // jambs
    P.push({g: k.box(FT, h, WT,  (w / 2 + FT / 2), sill + h / 2, 0)});
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, sill - FT / 2, 0)});                // sill board
    P.push({g: ringG(k, 0, sill + h, w / 2, arch, w / 2 + FT, arch + FT, 0, Math.PI, WT, 24)});
    P.push({g: k.box(w - 0.02, h - 0.02, 0.012, 0, sill + h / 2, 0), sub: 'mat_glass'});
    P.push({g: discG(k, 0, sill + h, w / 2 - 0.01, arch - 0.01, 0, Math.PI, 24), sub: 'mat_glass'});
    return P;
  };

  /* ── a bullseye ──────────────────────────────────────────────────────────
     centre at sill + r. w = h = 2r travel with the record so arSyncHoles
     cuts a square hole the frame covers. */
  AR_EXT.geom.window_round = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var r = N('r', 0.6), sill = N('sill', 1.2), cy = sill + r;
    var P = [];
    P.push({g: ringG(k, 0, cy, r, r, r + FT, r + FT, 0, Math.PI * 2, WT, 32)});
    P.push({g: k.box(2 * r, 0.04, 0.05, 0, cy, 0)});                            // glazing bars
    P.push({g: k.box(0.04, 2 * r, 0.05, 0, cy, 0)});
    P.push({g: discG(k, 0, cy, r, r, 0, Math.PI * 2, 32), sub: 'mat_glass'});
    return P;
  };

  /* ── a bay: a three-sided glazed box projecting toward local -Z ──────────
     The hole in the wall stays the plain w x h rectangle at sill. */
  AR_EXT.geom.window_bay = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 2.4), h = N('h', 1.4), sill = N('sill', 0.9), dep = N('depth', 0.8);
    if(dep < 0.1) dep = 0.1;
    var out = [[-w / 2, 0], [-w * 0.25, dep], [w * 0.25, dep], [w / 2, 0]];     // shape v -> -Z
    var cor = [[-w / 2, 0], [-w * 0.25, -dep], [w * 0.25, -dep], [w / 2, 0]];   // the same in world x/z
    var P = [], i, g;
    P.push({g: planPrismG(k, out, FT, sill)});                                  // sill slab
    P.push({g: planPrismG(k, out, FT, sill + h - FT)});                         // head slab
    for(i = 0; i < 4; i++) P.push({g: k.box(FT, h, FT, cor[i][0], sill + h / 2, cor[i][1])});
    for(i = 0; i < 3; i++){
      g = paneG(k, cor[i][0], cor[i][1], cor[i + 1][0], cor[i + 1][1], h - 2 * FT, sill + FT, FT);
      if(g) P.push({g: g, sub: 'mat_glass'});
    }
    return P;
  };

  /* ── a ribbon window ─────────────────────────────────────────────────────*/
  AR_EXT.geom.window_strip = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 8), h = N('h', 1.0), sill = N('sill', 1.1);
    var P = [], i;
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, sill - FT / 2, 0)});                // bottom rail
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, sill + h + FT / 2, 0)});            // top rail
    P.push({g: k.box(FT, h, WT, -(w / 2 + FT / 2), sill + h / 2, 0)});          // end jambs
    P.push({g: k.box(FT, h, WT,  (w / 2 + FT / 2), sill + h / 2, 0)});
    var bays = Math.max(1, Math.round(w / 1.5));
    for(i = 1; i < bays; i++)
      P.push({g: k.box(0.05, h, 0.08, -w / 2 + w * i / bays, sill + h / 2, 0)});
    P.push({g: k.box(w - 0.02, h - 0.02, 0.012, 0, sill + h / 2, 0), sub: 'mat_glass'});
    return P;
  };

  /* ── an up-and-over garage door ──────────────────────────────────────────*/
  AR_EXT.geom.door_garage = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 2.5), h = N('h', 2.2), n = Math.max(1, Math.min(24, Math.round(N('panels', 4))));
    var P = [], i, ph = h / n;
    P.push({g: k.box(FT, h, WT, -(w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(FT, h, WT,  (w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, h + FT / 2, 0)});
    for(i = 0; i < n; i++)
      P.push({g: k.box(w - 0.04, ph - 0.03, 0.06, 0, (i + 0.5) * ph, 0), sub: 'mat_steel'});
    return P;
  };

  /* ── a two-leaf sliding glass door ───────────────────────────────────────*/
  AR_EXT.geom.door_sliding = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 2.4), h = N('h', 2.1);
    var P = [];
    P.push({g: k.box(FT, h, WT, -(w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(FT, h, WT,  (w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, h + FT / 2, 0)});
    P.push({g: k.box(w / 2 - 0.03, h - FT, 0.02, -w / 4, (h - FT) / 2 + FT / 2, -0.03), sub: 'mat_glass'});
    P.push({g: k.box(w / 2 - 0.03, h - FT, 0.02,  w / 4, (h - FT) / 2 + FT / 2,  0.03), sub: 'mat_glass'});
    return P;
  };

  /* ── french doors: two glazed leaves in a timber frame ───────────────────*/
  AR_EXT.geom.door_french = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 1.6), h = N('h', 2.1), lw = w / 2 - 0.02;
    var P = [], s;
    P.push({g: k.box(FT, h, WT, -(w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(FT, h, WT,  (w / 2 + FT / 2), h / 2, 0)});
    P.push({g: k.box(w + 2 * FT, FT, WT, 0, h + FT / 2, 0)});
    for(s = -1; s <= 1; s += 2){
      var cx = s * w / 4;
      P.push({g: k.box(0.05, h - 0.04, 0.05, cx - (lw / 2 - 0.025), (h - 0.04) / 2, 0), sub: 'mat_timber'});
      P.push({g: k.box(0.05, h - 0.04, 0.05, cx + (lw / 2 - 0.025), (h - 0.04) / 2, 0), sub: 'mat_timber'});
      P.push({g: k.box(lw, 0.05, 0.05, cx, 0.025, 0), sub: 'mat_timber'});
      P.push({g: k.box(lw, 0.05, 0.05, cx, h - 0.065, 0), sub: 'mat_timber'});
      P.push({g: k.box(lw - 0.1, h - 0.2, 0.014, cx, (h - 0.04) / 2, 0), sub: 'mat_glass'});
    }
    return P;
  };

  /* ── a curtain wall: a mullion/transom grid with glass filling len x h ───
     NOT an opening — it replaces a wall face, so it is not registered in
     AR_EXT.openings and no hole is ever cut for it. */
  AR_EXT.geom.curtain_wall = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var L = N('len', 6), h = N('h', 2.7), mu = N('mullion', 1.5), tr = N('transom', 1.2), t = N('t', 0.15);
    if(mu < 0.2) mu = 0.2;
    if(tr < 0.2) tr = 0.2;
    var P = [], i, x, y;
    var nv = Math.max(1, Math.round(L / mu)), nh = Math.max(1, Math.round(h / tr));
    P.push({g: k.box(L, h, 0.012, 0, h / 2, 0), sub: 'mat_glass'});             // the sheet of glass
    for(i = 0; i <= nv; i++){
      x = Math.max(-L / 2 + FT / 2, Math.min(L / 2 - FT / 2, -L / 2 + L * i / nv));
      P.push({g: k.box(FT, h, t, x, h / 2, 0)});
    }
    for(i = 0; i <= nh; i++){
      y = Math.max(FT / 2, Math.min(h - FT / 2, h * i / nh));
      P.push({g: k.box(L, FT, t, 0, y, 0)});
    }
    return P;
  };

  AR_EXT.label.window_arch = 'Arched window';
  AR_EXT.label.window_round = 'Round window';
  AR_EXT.label.window_bay = 'Bay window';
  AR_EXT.label.window_strip = 'Strip window';
  AR_EXT.label.door_garage = 'Garage door';
  AR_EXT.label.door_sliding = 'Sliding door';
  AR_EXT.label.door_french = 'French doors';
  AR_EXT.label.curtain_wall = 'Curtain wall';

  AR_EXT.openings.window_arch = 1;
  AR_EXT.openings.window_round = 1;
  AR_EXT.openings.window_bay = 1;
  AR_EXT.openings.window_strip = 1;
  AR_EXT.openings.door_garage = 1;
  AR_EXT.openings.door_sliding = 1;
  AR_EXT.openings.door_french = 1;
})();
