// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* water_leisure — water and leisure kinds for Architecture Studio.

   pool, pond, canal, fountain, playground_slide, swing, sandpit,
   sports_court, goal_posts, tennis_net, sun_lounger, umbrella.

   Local frame: the record's x/z is the CENTRE in plan, y = 0 is the ground.
   Basins DIG: a pool's floor sits at -depth and its coping rim rises to
   +coping, so a pool's bounding box spans depth+coping in Y with its minimum
   BELOW the ground plane. That is deliberate — a hole in the ground is the
   only honest way to draw one. A ROOFTOP pool is the exception: p.raised
   lifts the whole basin so it stands on the deck (see the pool comment). Water surfaces are thin boxes/discs carrying
   sub:'mat_water'; painted court lines carry sub:'mat_paint_white'. */
(function(){
  function cyl(k, r, h, y0, seg, rTop){
    var rt = (rTop === undefined || rTop === null) ? r : rTop;
    var g = new k.THREE.CylinderGeometry(Math.max(rt, 0), Math.max(r, 1e-4), Math.max(h, 1e-4), Math.max(6, seg || 24));
    g.translate(0, y0 + Math.max(h, 1e-4) / 2, 0);
    return g;
  }
  /* an elliptical dish: a cone of unit radius squashed to rx by rz */
  function dish(k, rx, rz, h, y0, seg, shrink){
    var s = (shrink === undefined) ? 1 : shrink;
    var g = new k.THREE.CylinderGeometry(1, Math.max(s, 0.05), Math.max(h, 1e-4), Math.max(8, seg || 32));
    g.scale(Math.max(rx, 0.05), 1, Math.max(rz, 0.05));
    g.translate(0, y0 + Math.max(h, 1e-4) / 2, 0);
    return g;
  }

  /* ── water ───────────────────────────────────────────────────────────── */
  /* A pool has a `raised` parameter (2026-09-08): metres the rim stands above
     the level it sits on. raised = 0 is the sunk garden basin (floor at -depth,
     the hole is in the parameters); raised = depth is a rooftop pool STANDING
     on its deck with the walls exposed — the water is then above the deck, so
     it can be seen. Contract, identical in arch_blender_ext/water_leisure.py:
       floor box 0.2 thick from raised-depth; walls 0.2 thick from raised-depth
       to raised+coping; water at raised-0.1. p.inf = 'n'|'s'|'e'|'w' is the
       INFINITY edge: that wall has no coping — it stops at the water level and
       is glass (a weir) — and a catch trough 0.5 wide x 0.4 deep sits outside
       it, from raised-0.5 to raised-0.1. With raised 0 and no inf the six
       parts are exactly what they were before this parameter existed. */
  AR_EXT.geom.pool = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 8), d = N('d', 4), dep = Math.max(0.2, N('depth', 1.5)), cop = Math.max(0, N('coping', 0.4));
    var R = Math.max(0, N('raised', 0));
    var inf = String(p.inf || '').toLowerCase().charAt(0);
    if('nsew'.indexOf(inf) < 0 || inf === '') inf = '';
    var t = 0.2, P = [], H = dep + cop, yc = R + (cop - dep) / 2;
    var Hw = Math.max(0.05, dep - 0.1), yw = R - dep + Hw / 2;                        // the weir: to water level
    var dw = Math.max(0.05, d - 2 * t);
    P.push({g: k.box(w, t, d, 0, R - dep + t / 2, 0)});                               // basin floor
    if(inf === 'n') P.push({g: k.box(w, Hw, t, 0, yw, -(d / 2 - t / 2)), sub: 'mat_glass'});
    else            P.push({g: k.box(w, H, t, 0, yc, -(d / 2 - t / 2))});             // long walls
    if(inf === 's') P.push({g: k.box(w, Hw, t, 0, yw,  (d / 2 - t / 2)), sub: 'mat_glass'});
    else            P.push({g: k.box(w, H, t, 0, yc,  (d / 2 - t / 2))});
    if(inf === 'w') P.push({g: k.box(t, Hw, dw, -(w / 2 - t / 2), yw, 0), sub: 'mat_glass'});
    else            P.push({g: k.box(t, H, dw, -(w / 2 - t / 2), yc, 0)});            // end walls
    if(inf === 'e') P.push({g: k.box(t, Hw, dw,  (w / 2 - t / 2), yw, 0), sub: 'mat_glass'});
    else            P.push({g: k.box(t, H, dw,  (w / 2 - t / 2), yc, 0)});
    P.push({g: k.box(Math.max(0.05, w - 2 * t), 0.04, dw, 0, R - 0.1, 0), sub: 'mat_water'});
    /* the catch trough outside the weir: 0.5 wide, 0.4 deep, top at the water level */
    if(inf === 'n')      P.push({g: k.box(w, 0.4, 0.5, 0, R - 0.3, -(d / 2 + 0.25))});
    else if(inf === 's') P.push({g: k.box(w, 0.4, 0.5, 0, R - 0.3,  (d / 2 + 0.25))});
    else if(inf === 'w') P.push({g: k.box(0.5, 0.4, d, -(w / 2 + 0.25), R - 0.3, 0)});
    else if(inf === 'e') P.push({g: k.box(0.5, 0.4, d,  (w / 2 + 0.25), R - 0.3, 0)});
    /* entry steps (2026-09-12): p.steps = 'n'|'s'|'e'|'w' is the side they descend
       from, never the weir side. n treads of 0.3 m rise and 0.35 m run, the top
       one 0.3 m under the water, each a box from the inner wall face inward to
       (i+1) x run, standing on the basin floor — the union is a stair. Tread
       width 2.4 m, or what the side allows. Same numbers in Blender. */
    var st = String(p.steps || '').toLowerCase().charAt(0);
    if('nsew'.indexOf(st) < 0 || st === inf) st = '';
    if(st){
      var n = Math.max(1, Math.min(5, Math.floor((dep - 0.15) / 0.3))), run = 0.35, i;
      var side = (st === 'n' || st === 's') ? w : d, sw = Math.max(0.4, Math.min(2.4, side - 2 * t - 0.4));
      var y0 = R - dep + t;                                                           // the floor top
      for(i = 0; i < n; i++){
        var top = R - 0.1 - 0.3 * (i + 1), hh = Math.max(0.03, top - y0), ex = run * (i + 1), yc = y0 + hh / 2;
        if(st === 'n')      P.push({g: k.box(sw, hh, ex, 0, yc, -(d / 2 - t) + ex / 2)});
        else if(st === 's') P.push({g: k.box(sw, hh, ex, 0, yc,  (d / 2 - t) - ex / 2)});
        else if(st === 'w') P.push({g: k.box(ex, hh, sw, -(w / 2 - t) + ex / 2, yc, 0)});
        else                P.push({g: k.box(ex, hh, sw,  (w / 2 - t) - ex / 2, yc, 0)});
      }
    }
    return P;
  };
  /* A bank is read in two bands (2026-09-07): the TOP 30 % of it is turf
     (mat_grass), what is below is the bed (mat_soil); the water surface is
     mat_water. The bands stack over the same extent the single part used to
     cover, so every bounding box is unchanged. BANK_TOP is the same number in
     arch_blender_ext/water_leisure.py. */
  var BANK_TOP = 0.30;
  AR_EXT.geom.pond = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var rx = N('rx', 4), rz = N('rz', 3), dep = Math.max(0.15, N('depth', 0.6));
    /* the cone runs from 0.72 r at the bed up to 1.00 r at the rim, so at the
       split its scale is s = 0.72 + 0.28 * (1 - BANK_TOP) */
    var s = 0.72 + 0.28 * (1 - BANK_TOP);
    return [{g: dish(k, rx * s, rz * s, dep * (1 - BANK_TOP), -dep, 32, 0.72 / s), sub: 'mat_soil'},
            {g: dish(k, rx, rz, dep * BANK_TOP, -dep * BANK_TOP, 32, s), sub: 'mat_grass'},
            {g: dish(k, Math.max(0.1, rx - 0.15), Math.max(0.1, rz - 0.15), 0.03, -0.12, 32, 1),
             sub: 'mat_water'}];
  };
  AR_EXT.geom.canal = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var L = N('len', 20), w = N('w', 6), dep = Math.max(0.2, N('depth', 1.5));
    var t = 0.3, P = [], H = dep + 0.1;
    var hb = H * BANK_TOP, hq = H - hb;                                               // turf cap, quay below
    P.push({g: k.box(L, t, w, 0, -dep + t / 2, 0), sub: 'mat_soil'});                 // bed
    P.push({g: k.box(L, hq, t, 0, -dep + hq / 2, -(w / 2 - t / 2))});                 // quay walls
    P.push({g: k.box(L, hq, t, 0, -dep + hq / 2,  (w / 2 - t / 2))});
    P.push({g: k.box(L, hb, t, 0, -dep + hq + hb / 2, -(w / 2 - t / 2)), sub: 'mat_grass'});
    P.push({g: k.box(L, hb, t, 0, -dep + hq + hb / 2,  (w / 2 - t / 2)), sub: 'mat_grass'});
    P.push({g: k.box(L, 0.04, Math.max(0.05, w - 2 * t), 0, -0.1, 0), sub: 'mat_water'});
    return P;
  };
  AR_EXT.geom.fountain = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var r = Math.max(0.4, N('r', 2)), n = Math.max(1, Math.round(N('tiers', 3))), h = Math.max(1.0, N('h', 2.5));
    var P = [], i;
    P.push({g: cyl(k, r, 0.45, 0, 32)});                                              // basin
    P.push({g: cyl(k, Math.max(0.1, r - 0.12), 0.02, 0.34, 32), sub: 'mat_water'});
    P.push({g: cyl(k, Math.max(0.06, r * 0.10), h, 0, 16)});                          // stem
    for(i = 0; i < n; i++){
      var f = (i + 1) / n, yy = 0.45 + (h - 0.75) * f;
      var rr = Math.max(0.15, r * (0.62 - 0.40 * i / n));
      P.push({g: cyl(k, rr, 0.10, yy, 24)});
      P.push({g: cyl(k, Math.max(0.06, rr - 0.05), 0.02, yy + 0.10, 24), sub: 'mat_water'});
    }
    return P;
  };

  /* ── play ────────────────────────────────────────────────────────────── */
  AR_EXT.geom.playground_slide = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var h = Math.max(0.6, N('h', 2)), L = Math.max(1.2, N('l', 4)), w = Math.max(0.25, N('w', 0.6));
    var P = [], i, x0 = -L / 2;
    var pts = [[x0 + 0.08, h], [L / 2, 0.12], [L / 2, 0.02], [x0 + 0.08, h - 0.10]];
    P.push({g: k.prism(pts, w)});                                                     // the chute
    P.push({g: k.box(0.08, h, 0.08, x0 + 0.04, h / 2, -(w / 2 - 0.04))});             // ladder posts
    P.push({g: k.box(0.08, h, 0.08, x0 + 0.04, h / 2,  (w / 2 - 0.04))});
    var rungs = Math.max(2, Math.round(h / 0.35));
    for(i = 1; i <= rungs; i++) P.push({g: k.box(0.06, 0.05, w - 0.16, x0 + 0.04, h * i / (rungs + 1), 0)});
    return P;
  };
  AR_EXT.geom.swing = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = Math.max(0.8, N('w', 3)), h = Math.max(0.8, N('h', 2.4)), n = Math.max(1, Math.round(N('seats', 2)));
    var P = [], i;
    P.push({g: k.box(w, 0.12, 0.12, 0, h - 0.06, 0)});                                // top beam
    P.push({g: k.box(0.12, h, 0.12, -(w / 2 - 0.06), h / 2, 0)});                     // posts
    P.push({g: k.box(0.12, h, 0.12,  (w / 2 - 0.06), h / 2, 0)});
    for(i = 0; i < n; i++){
      var cx = -w / 2 + w * (i + 1) / (n + 1), sy = Math.min(0.45, h * 0.22);
      P.push({g: k.box(0.04, h - 0.12 - sy, 0.04, cx - 0.18, (h - 0.12 + sy) / 2, 0)});
      P.push({g: k.box(0.04, h - 0.12 - sy, 0.04, cx + 0.18, (h - 0.12 + sy) / 2, 0)});
      P.push({g: k.box(0.45, 0.05, 0.35, cx, sy, 0)});                                // seat
    }
    return P;
  };
  AR_EXT.geom.sandpit = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = Math.max(0.6, N('w', 4)), d = Math.max(0.6, N('d', 4)), t = Math.max(0.05, N('t', 0.3));
    var b = 0.2, P = [], H = t + 0.25, yc = (0.25 - t) / 2;
    P.push({g: k.box(w - 2 * b, t, d - 2 * b, 0, -t / 2, 0)});                        // the sand
    P.push({g: k.box(w, H, b, 0, yc, -(d / 2 - b / 2))});                             // timber kerb
    P.push({g: k.box(w, H, b, 0, yc,  (d / 2 - b / 2))});
    P.push({g: k.box(b, H, d - 2 * b, -(w / 2 - b / 2), yc, 0)});
    P.push({g: k.box(b, H, d - 2 * b,  (w / 2 - b / 2), yc, 0)});
    return P;
  };

  /* ── sport ───────────────────────────────────────────────────────────── */
  AR_EXT.geom.sports_court = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = Math.max(2, N('w', 28)), d = Math.max(2, N('d', 15)), ln = N('lines', 1);
    var P = [{g: k.box(w, 0.10, d, 0, 0.05, 0)}];
    if(ln > 0.5){
      var m = Math.min(0.5, Math.min(w, d) * 0.05), t = 0.12, y = 0.105;
      var W = w - 2 * m, D = d - 2 * m;
      P.push({g: k.box(W, 0.012, t, 0, y, -(D / 2)), sub: 'mat_paint_white'});
      P.push({g: k.box(W, 0.012, t, 0, y,  (D / 2)), sub: 'mat_paint_white'});
      P.push({g: k.box(t, 0.012, D, -(W / 2), y, 0), sub: 'mat_paint_white'});
      P.push({g: k.box(t, 0.012, D,  (W / 2), y, 0), sub: 'mat_paint_white'});
      P.push({g: k.box(t, 0.012, D, 0, y, 0), sub: 'mat_paint_white'});               // halfway line
    }
    return P;
  };
  AR_EXT.geom.goal_posts = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = Math.max(0.8, N('w', 7.32)), h = Math.max(0.5, N('h', 2.44)), d = Math.max(0.3, N('d', 2));
    var P = [];
    P.push({g: k.box(0.12, h, 0.12, -(w / 2 - 0.06), h / 2, 0.06)});                  // uprights
    P.push({g: k.box(0.12, h, 0.12,  (w / 2 - 0.06), h / 2, 0.06)});
    P.push({g: k.box(w, 0.12, 0.12, 0, h - 0.06, 0.06)});                             // crossbar
    P.push({g: k.box(0.10, h * 0.45, 0.10, -(w / 2 - 0.05), h * 0.225, d - 0.05)});   // back stanchions
    P.push({g: k.box(0.10, h * 0.45, 0.10,  (w / 2 - 0.05), h * 0.225, d - 0.05)});
    P.push({g: k.box(w, 0.10, 0.10, 0, 0.05, d - 0.05)});                             // back ground bar
    P.push({g: k.box(w - 0.24, 0.02, d - 0.12, 0, h * 0.72, d / 2), sub: 'mat_paint_white'});   // net
    return P;
  };
  AR_EXT.geom.tennis_net = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = Math.max(1, N('w', 12.8)), h = Math.max(0.3, N('h', 1.07));
    return [{g: k.box(0.10, h, 0.10, -(w / 2 - 0.05), h / 2, 0)},
            {g: k.box(0.10, h, 0.10,  (w / 2 - 0.05), h / 2, 0)},
            {g: k.box(w - 0.20, h - 0.08, 0.03, 0, (h - 0.08) / 2, 0)},
            {g: k.box(w - 0.20, 0.06, 0.04, 0, h - 0.03, 0), sub: 'mat_paint_white'}];
  };

  /* ── poolside ────────────────────────────────────────────────────────── */
  AR_EXT.geom.sun_lounger = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var L = Math.max(0.6, N('l', 1.9)), w = Math.max(0.3, N('w', 0.7)), h = Math.max(0.15, N('h', 0.4));
    var P = [], i, xs = [-(L / 2 - 0.08), (L / 2 - 0.08)], zs = [-(w / 2 - 0.08), (w / 2 - 0.08)];
    P.push({g: k.box(L, 0.10, w, 0, h - 0.05, 0)});                                   // mattress
    P.push({g: k.box(L * 0.34, 0.06, w - 0.10, -(L / 2 - L * 0.17), h - 0.13, 0)});   // raised head panel
    for(i = 0; i < 4; i++) P.push({g: k.box(0.06, h - 0.10, 0.06, xs[i % 2], (h - 0.10) / 2, zs[i < 2 ? 0 : 1])});
    return P;
  };
  AR_EXT.geom.umbrella = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var r = Math.max(0.3, N('r', 1.5)), h = Math.max(0.8, N('h', 2.3));
    return [{g: cyl(k, 0.035, h, 0, 16)},
            {g: cyl(k, r, 0.50, h - 0.50, 20, 0.0)},
            {g: cyl(k, 0.09, 0.10, h - 0.60, 12)}];
  };

  AR_EXT.label.pool = 'Swimming pool';
  AR_EXT.label.pond = 'Pond';
  AR_EXT.label.canal = 'Canal';
  AR_EXT.label.fountain = 'Fountain';
  AR_EXT.label.playground_slide = 'Slide';
  AR_EXT.label.swing = 'Swing frame';
  AR_EXT.label.sandpit = 'Sandpit';
  AR_EXT.label.sports_court = 'Sports court';
  AR_EXT.label.goal_posts = 'Goal posts';
  AR_EXT.label.tennis_net = 'Tennis net';
  AR_EXT.label.sun_lounger = 'Sun lounger';
  AR_EXT.label.umbrella = 'Parasol';
})();
