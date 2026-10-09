// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* mep_services — the building's services: ducts, pipes, cable trays, solar
   panels, rooftop plant, chimneys, rainwater goods and radiators.

   Local frame (as every family): the record's x/z is the object's plan centre,
   the geometry's BOTTOM sits at y = 0, +Y is up. Horizontal runs (duct, pipe,
   cable_tray, gutter) lie along LOCAL +X so the record's ry aims them exactly
   the way a wall's ry aims a wall — 0 = along +X, and a point at plan angle
   theta is (r cos theta, -r sin theta).

   The solar panel is the only tilted kind: a w x d board of thickness t,
   pivoted about the local X axis by `tilt` degrees and stood on four legs of
   height `leg`, so its lowest edge is at y = leg and it is
   leg + d*sin(tilt) + t*cos(tilt) tall overall. The board itself is drawn with
   sub:'mat_glass' whatever the record's own material is. */
(function(){
  var PI = Math.PI;

  function tubeX(k, r, len, cy){          // a cylinder lying along local +X
    var g = new k.THREE.CylinderGeometry(r, r, Math.max(len, 1e-3), 16);
    g.rotateZ(PI / 2);                    // +Y axis -> -X axis: the tube runs along X
    g.translate(0, cy, 0);
    return g;
  }
  function tubeY(k, r, h){                // a cylinder standing on y = 0
    var g = new k.THREE.CylinderGeometry(r, r, Math.max(h, 1e-3), 16);
    g.translate(0, h / 2, 0);
    return g;
  }

  /* ── horizontal runs ─────────────────────────────────────────────────── */
  AR_EXT.geom.duct = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var L = N('len', 4), w = N('w', 0.4), h = N('h', 0.3);
    return [{g: k.box(L, h, w, 0, h / 2, 0)}];
  };
  AR_EXT.geom.pipe = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var L = N('len', 4), r = N('r', 0.05);
    return [{g: tubeX(k, r, L, r)}];
  };
  AR_EXT.geom.cable_tray = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var L = N('len', 4), w = N('w', 0.3), h = N('h', 0.05), t = 0.008;
    return [{g: k.box(L, 0.01, w, 0, 0.005, 0)},
            {g: k.box(L, h, t, 0, h / 2,  (w / 2 - t / 2))},
            {g: k.box(L, h, t, 0, h / 2, -(w / 2 - t / 2))}];
  };
  AR_EXT.geom.gutter = function(p, k){    // an open U-channel of half-width r
    var N = function(a, b){ return k.num(p[a], b); };
    var L = N('len', 4), r = N('r', 0.08), t = 0.012;
    return [{g: k.box(L, t, 2 * r, 0, t / 2, 0)},
            {g: k.box(L, r, t, 0, r / 2,  (r - t / 2))},
            {g: k.box(L, r, t, 0, r / 2, -(r - t / 2))}];
  };

  /* ── vertical runs ───────────────────────────────────────────────────── */
  AR_EXT.geom.downpipe = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    return [{g: tubeY(k, N('r', 0.05), N('h', 2.7))}];
  };
  AR_EXT.geom.antenna = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var h = N('h', 3), r = N('r', 0.03), P = [{g: tubeY(k, r, h)}], i;
    for(i = 0; i < 3; i++){                // three director bars, along local Z
      P.push({g: k.box(0.03, 0.03, 0.6, 0, h * (0.55 + 0.2 * i), 0)});
    }
    return P;
  };
  AR_EXT.geom.satellite_dish = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var r = N('r', 0.4), h = N('h', 0.5);
    var g = new k.THREE.CylinderGeometry(r, 0.08, 0.4 * r, 24);
    g.translate(0, h + 0.2 * r, 0);
    return [{g: tubeY(k, 0.04, h)}, {g: g, sub: 'mat_steel'}];
  };

  /* ── plant & fittings ────────────────────────────────────────────────── */
  AR_EXT.geom.hvac_unit = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = N('w', 1.2), d = N('d', 0.8), h = N('h', 1.0);
    var rr = Math.min(w, d) * 0.3;
    var fan = new k.THREE.CylinderGeometry(rr, rr, 0.06, 16);
    fan.translate(0, h - 0.03, 0);        // sunk into the lid: no change to the bbox
    return [{g: k.box(w, h, d, 0, h / 2, 0)}, {g: fan, sub: 'mat_steel'}];
  };
  AR_EXT.geom.water_tank = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    return [{g: tubeY(k, N('r', 1.0), N('h', 2.0))}];
  };
  AR_EXT.geom.chimney = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = N('w', 0.6), d = N('d', 0.6), h = N('h', 1.5), cap = N('cap', 0.1);
    return [{g: k.box(w, h, d, 0, h / 2, 0)},
            {g: k.box(w + 0.1, cap, d + 0.1, 0, h + cap / 2, 0)}];
  };
  AR_EXT.geom.radiator = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = N('w', 1.0), h = N('h', 0.6), t = N('t', 0.1);
    return [{g: k.box(w, h, t, 0, h / 2, 0)}];
  };
  AR_EXT.geom.solar_panel = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = N('w', 1.7), d = N('d', 1.0), tilt = N('tilt', 30), t = N('t', 0.04), leg = N('leg', 0.3);
    var a = tilt * PI / 180, ca = Math.cos(a), sa = Math.sin(a);
    var g = new k.THREE.BoxGeometry(w, t, d);
    g.rotateX(a);                          // the +Z edge drops, the -Z (north) edge rises
    g.translate(0, leg + t / 2 * ca + d / 2 * sa, 0);
    var P = [{g: g, sub: 'mat_glass'}], i, j;
    var lx = Math.max(0.05, w / 2 - 0.15), lz = Math.max(0.05, d * ca / 2 - 0.15);
    for(i = -1; i <= 1; i += 2){
      for(j = -1; j <= 1; j += 2){
        P.push({g: k.box(0.05, leg, 0.05, i * lx, leg / 2, j * lz)});
      }
    }
    return P;
  };

  AR_EXT.label.duct = 'Duct';
  AR_EXT.label.pipe = 'Pipe';
  AR_EXT.label.cable_tray = 'Cable tray';
  AR_EXT.label.solar_panel = 'Solar panel';
  AR_EXT.label.hvac_unit = 'HVAC unit';
  AR_EXT.label.water_tank = 'Water tank';
  AR_EXT.label.chimney = 'Chimney';
  AR_EXT.label.gutter = 'Gutter';
  AR_EXT.label.downpipe = 'Downpipe';
  AR_EXT.label.antenna = 'Antenna';
  AR_EXT.label.satellite_dish = 'Satellite dish';
  AR_EXT.label.radiator = 'Radiator';
})();
