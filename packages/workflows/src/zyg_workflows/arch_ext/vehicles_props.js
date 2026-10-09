// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* vehicles_props — the things that stand ON a site rather than being built:
   road vehicles (car, van, bus, truck, bicycle, motorcycle, tractor, forklift),
   a boat, and the plant a building site carries (crane_tower, scaffold,
   container, dumpster, pallet).

   Local frame, like every kind: origin at the BASE CENTRE, bottom at y=0,
   +Y up. Every vehicle runs its LENGTH along local +X with the FRONT toward
   +X, its WIDTH along Z and its HEIGHT along Y, so a record's bounding box is
   exactly l x h x w — the parameters mean what they say and the tab's size
   check can be exact. Wheels are cylinders with their axis along Z, radius r,
   centre at y=r (so the vehicle stands on the ground) and outer faces at
   +-w/2 (so the wheels, not the body, set the width). They are drawn in
   mat_paint_dark through the part's `sub`.

   scaffold's front (the open side you climb) faces local -Z; the wall it
   leans on is at local +Z. crane_tower's jib runs toward +X, the counter-jib
   and its counterweight toward -X. */
(function(){
  var WHEEL_MAT = 'mat_paint_dark';

  function cyl(k, r, len, cx, cy, cz, seg){
    var g = new k.THREE.CylinderGeometry(Math.max(r, 1e-3), Math.max(r, 1e-3), Math.max(len, 1e-3), Math.max(6, seg || 14));
    g.rotateX(Math.PI / 2);                 // axis Y -> Z
    g.translate(cx || 0, cy || 0, cz || 0);
    return g;
  }
  /* one axle = two wheels, outer faces exactly at +-w/2 */
  function axle(k, out, x, r, tw, w){
    var zc = Math.max(tw / 2, (w - tw) / 2);
    out.push({g: cyl(k, r, tw, x, r, zc), sub: WHEEL_MAT});
    out.push({g: cyl(k, r, tw, x, r, -zc), sub: WHEEL_MAT});
  }
  /* box between two heights, centred on (cx, cz) */
  function slab(k, out, sx, sz, y0, y1, cx, cz, sub){
    var part = {g: k.box(sx, Math.max(y1 - y0, 1e-3), sz, cx || 0, (y0 + y1) / 2, cz || 0)};
    if(sub) part.sub = sub;
    out.push(part);
  }

  /* ── road vehicles ─────────────────────────────────────────────────── */
  AR_EXT.geom.car = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 4.5), w = N('w', 1.8), h = N('h', 1.5);
    var r = Math.min(0.34, h * 0.24, l * 0.09), tw = Math.min(0.2, w * 0.14), P = [];
    slab(k, P, l, w, r * 0.55, h * 0.62, 0, 0);                       // body
    slab(k, P, l * 0.5, w * 0.86, h * 0.62, h, -l * 0.04, 0);         // cabin
    axle(k, P, l * 0.34, r, tw, w);
    axle(k, P, -l * 0.32, r, tw, w);
    return P;
  };
  AR_EXT.geom.van = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 5.5), w = N('w', 2.0), h = N('h', 2.4);
    var r = Math.min(0.38, h * 0.18, l * 0.09), tw = Math.min(0.24, w * 0.14), P = [];
    slab(k, P, l * 0.72, w, r * 0.55, h, -l * 0.14, 0);               // cargo body
    slab(k, P, l * 0.34, w, r * 0.55, h * 0.74, l * 0.33, 0);         // cab
    slab(k, P, l * 0.30, w * 0.94, h * 0.46, h * 0.70, l * 0.33, 0, 'mat_glass');
    axle(k, P, l * 0.32, r, tw, w);
    axle(k, P, -l * 0.30, r, tw, w);
    return P;
  };
  AR_EXT.geom.bus = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 12), w = N('w', 2.5), h = N('h', 3.2);
    var r = Math.min(0.5, h * 0.17), tw = Math.min(0.3, w * 0.13), P = [];
    slab(k, P, l, w, r * 0.6, h * 0.42, 0, 0);                        // skirt
    slab(k, P, l * 0.94, w, h * 0.42, h * 0.80, 0, 0, 'mat_glass');   // window band
    slab(k, P, l, w, h * 0.80, h, 0, 0);                              // roof
    axle(k, P, l * 0.34, r, tw, w);
    axle(k, P, -l * 0.30, r, tw, w);
    return P;
  };
  AR_EXT.geom.truck = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 9), w = N('w', 2.5), h = N('h', 3.6);
    var r = Math.min(0.52, h * 0.16), tw = Math.min(0.3, w * 0.13), P = [];
    slab(k, P, l, w * 0.8, h * 0.22, h * 0.30, 0, 0);                 // chassis
    slab(k, P, l * 0.68, w, h * 0.30, h, -l * 0.16, 0);               // box body
    slab(k, P, l * 0.26, w, r * 0.6, h * 0.72, l * 0.37, 0);          // cab
    axle(k, P, l * 0.36, r, tw, w);
    axle(k, P, -l * 0.26, r, tw, w);
    return P;
  };
  AR_EXT.geom.tractor = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 4), w = N('w', 2.2), h = N('h', 2.8);
    var rr = Math.min(0.75, h * 0.28, l * 0.20), rf = rr * 0.56;
    var tw = Math.min(0.45, w * 0.22), P = [];
    slab(k, P, l, w * 0.5, h * 0.16, h * 0.26, 0, 0);                 // chassis
    slab(k, P, l * 0.5, w * 0.55, h * 0.20, h * 0.56, l * 0.24, 0);   // bonnet
    slab(k, P, l * 0.42, w * 0.72, h * 0.20, h, -l * 0.20, 0);        // cab
    axle(k, P, -l * 0.22, rr, tw, w);
    axle(k, P, l * 0.33, rf, tw * 0.7, w * 0.82);
    return P;
  };
  AR_EXT.geom.forklift = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 3), w = N('w', 1.2), h = N('h', 2.1);
    var r = Math.min(0.3, h * 0.16), tw = Math.min(0.2, w * 0.17), P = [];
    slab(k, P, l * 0.66, w, r * 0.6, h * 0.60, -l * 0.17, 0);         // body
    slab(k, P, 0.1, w * 0.18, 0.04, h, l * 0.42, w * 0.28);           // mast posts
    slab(k, P, 0.1, w * 0.18, 0.04, h, l * 0.42, -w * 0.28);
    slab(k, P, l * 0.24, w * 0.62, 0.02, 0.09, l * 0.38, 0);          // forks
    axle(k, P, l * 0.28, r, tw, w);
    axle(k, P, -l * 0.30, r, tw, w);
    return P;
  };

  /* ── two-wheelers: no `w` parameter, the handlebar sets the width ──── */
  function twoWheeler(k, l, h, w, rFrac){
    var r = Math.min(h * rFrac, l * 0.24), tw = Math.max(0.05, r * 0.16), P = [];
    P.push({g: cyl(k, r, tw, l / 2 - r, r, 0), sub: WHEEL_MAT});
    P.push({g: cyl(k, r, tw, -(l / 2 - r), r, 0), sub: WHEEL_MAT});
    slab(k, P, l * 0.5, w * 0.22, h * 0.42, h * 0.62, -l * 0.02, 0);   // frame / tank
    slab(k, P, l * 0.14, w * 0.30, h * 0.66, h * 0.80, -l * 0.16, 0);  // saddle
    slab(k, P, l * 0.10, w, h * 0.80, h, l * 0.30, 0);                 // handlebar
    slab(k, P, 0.06, w * 0.16, r, h * 0.86, l / 2 - r, 0);             // fork
    return P;
  }
  AR_EXT.geom.bicycle = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    return twoWheeler(k, N('l', 1.8), N('h', 1.0), 0.55, 0.35);
  };
  AR_EXT.geom.motorcycle = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    return twoWheeler(k, N('l', 2.1), N('h', 1.1), 0.8, 0.30);
  };

  /* ── boat: a hull prism (side profile extruded across the beam) ────── */
  AR_EXT.geom.boat = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 6), w = N('w', 2.2), h = N('h', 1.5), hh = h * 0.55, P = [];
    P.push({g: k.prism([[-l / 2, hh], [-l / 2, hh * 0.32], [-l * 0.30, 0], [l * 0.26, 0],
                        [l / 2, hh * 0.45], [l / 2, hh]], w)});
    slab(k, P, l * 0.34, w * 0.70, hh, h, -l * 0.06, 0);               // wheelhouse
    return P;
  };

  /* ── site plant ────────────────────────────────────────────────────── */
  AR_EXT.geom.crane_tower = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var h = N('h', 30), jib = N('jib', 25), m = N('mast', 1.6);
    var cj = jib * 0.35, jh = m * 0.55, P = [];
    slab(k, P, m, m, 0, h, 0, 0);                                      // mast
    slab(k, P, jib + cj, m * 0.6, h - jh, h, (jib - cj) / 2, 0);       // jib + counter-jib
    slab(k, P, cj * 0.34, m * 0.8, h - jh - jh * 1.4, h - jh, -cj * 0.78, 0);  // counterweight
    slab(k, P, m * 1.2, m * 0.9, h - jh - m * 1.1, h - jh, m * 0.9, 0);        // operator cab
    slab(k, P, m * 0.5, m * 0.5, h - jh - m * 1.6, h - jh, jib * 0.86, 0, 'mat_paint_dark'); // hook block
    return P;
  };
  AR_EXT.geom.scaffold = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 6), h = N('h', 6), dp = N('d', 1.2);
    var bays = Math.max(1, Math.round(N('bays', 3))), lifts = Math.max(1, Math.round(N('lifts', 3)));
    var t = 0.06, P = [], i, j;
    var zr = [Math.max(t / 2, (dp - t) / 2), -Math.max(t / 2, (dp - t) / 2)];
    for(i = 0; i <= bays; i++){
      var px = -(w - t) / 2 + (w - t) * i / bays;
      for(j = 0; j < 2; j++) slab(k, P, t, t, 0, h, px, zr[j]);        // standards
      slab(k, P, t, dp, h - t, h, px, 0);                              // transoms at the top lift
    }
    for(i = 1; i <= lifts; i++){
      var py = h * i / lifts;
      for(j = 0; j < 2; j++) slab(k, P, w, t, py - t, py, 0, zr[j]);   // ledgers
      slab(k, P, w - t, dp - t, py - t - 0.04, py - t, 0, 0, 'mat_timber');  // boards
    }
    return P;
  };
  AR_EXT.geom.container = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 6.06), w = N('w', 2.44), h = N('h', 2.59), P = [];
    slab(k, P, l, w, 0, h, 0, 0);
    slab(k, P, 0.05, w * 0.9, h * 0.05, h * 0.95, l / 2 - 0.04, 0, 'mat_paint_dark');  // doors
    return P;
  };
  AR_EXT.geom.dumpster = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 3), w = N('w', 1.8), h = N('h', 1.4), P = [];
    slab(k, P, l, w, 0, h * 0.82, 0, 0);                               // skip body
    slab(k, P, l, w, h * 0.82, h, 0, 0, 'mat_paint_dark');             // rim / lid
    return P;
  };
  AR_EXT.geom.pallet = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var l = N('l', 1.2), w = N('w', 0.8), h = N('h', 0.15), b = Math.min(0.022, h * 0.16), P = [];
    slab(k, P, l, w, h - b, h, 0, 0);                                  // top deck
    slab(k, P, l, w, 0, b, 0, 0);                                      // bottom boards
    slab(k, P, l * 0.1, w, b, h - b, -l * 0.45, 0);                    // bearers
    slab(k, P, l * 0.1, w, b, h - b, 0, 0);
    slab(k, P, l * 0.1, w, b, h - b, l * 0.45, 0);
    return P;
  };

  AR_EXT.label.car = 'Car';
  AR_EXT.label.van = 'Van';
  AR_EXT.label.bus = 'Bus';
  AR_EXT.label.truck = 'Truck';
  AR_EXT.label.bicycle = 'Bicycle';
  AR_EXT.label.motorcycle = 'Motorcycle';
  AR_EXT.label.boat = 'Boat';
  AR_EXT.label.tractor = 'Tractor';
  AR_EXT.label.forklift = 'Forklift';
  AR_EXT.label.crane_tower = 'Tower crane';
  AR_EXT.label.scaffold = 'Scaffold';
  AR_EXT.label.container = 'Shipping container';
  AR_EXT.label.dumpster = 'Skip';
  AR_EXT.label.pallet = 'Pallet';
})();
