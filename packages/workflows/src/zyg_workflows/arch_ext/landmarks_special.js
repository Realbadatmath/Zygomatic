// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* landmarks_special — the fifteen landmark kinds (windmill, lighthouse,
   water_tower, silo, geodesic_dome, tent, gazebo, obelisk, arch_monument,
   spire, minaret, stadium_ring, wind_turbine, pyramid_stepped, ferris_wheel).

   Local frame, as every extension: the record's x/z is the plan CENTRE, the
   bottom sits at y = 0, up is +Y. Everything is assembled from cylinders,
   cones, lathes, boxes and one icosphere — the parameters mean exactly what
   the rail and the assistant say they mean, so a bbox is a contract:

     windmill      h + sails reach            lighthouse   h + lantern
     water_tower   h (tank is the top tank_h) silo         h + cone
     geodesic_dome 2r x r x 2r (a hemisphere) tent         2r x h x 2r
     gazebo        h + roof_h                 obelisk      h, w square
     arch_monument w x h x d                  spire        h
     minaret       h                          stadium_ring 2rx x tiers*tier_h x 2rz
     wind_turbine  h + blade                  pyramid_stepped w x h x w
     ferris_wheel  2r + clearance
*/
(function(){
  var PI = Math.PI, TAU = PI * 2;

  /* a vertical (optionally tapered) drum: bottom radius r0, top radius r1,
     height h, bottom face at y0. */
  function drum(THREE, r0, r1, h, seg, y0){
    var g = new THREE.CylinderGeometry(Math.max(1e-4, r1), Math.max(1e-4, r0), Math.max(1e-4, h), Math.max(3, Math.round(seg)));
    g.translate(0, y0 + h / 2, 0);
    return g;
  }
  /* a closed ring band between two concentric ellipses, y0..y0+h. Built by hand
     rather than with ExtrudeGeometry so the extents are exactly the semi-axes:
     a point at plan angle a is (ax*cos a, -az*sin a) — the studio convention. */
  function ringBand(THREE, axo, azo, axi, azi, y0, h, seg){
    var pos = [], idx = [], i;
    seg = Math.max(8, Math.round(seg));
    axi = Math.max(0.02, axi); azi = Math.max(0.02, azi);
    for(i = 0; i < seg; i++){
      var a = i / seg * TAU, c = Math.cos(a), s = Math.sin(a);
      pos.push(axo * c, y0, -azo * s);
      pos.push(axo * c, y0 + h, -azo * s);
      pos.push(axi * c, y0, -azi * s);
      pos.push(axi * c, y0 + h, -azi * s);
    }
    for(i = 0; i < seg; i++){
      var A = i * 4, B = ((i + 1) % seg) * 4;
      idx.push(A + 0, B + 0, B + 1, A + 0, B + 1, A + 1);   // outer skin
      idx.push(B + 2, A + 2, A + 3, B + 2, A + 3, B + 3);   // inner skin
      idx.push(A + 1, B + 1, B + 3, A + 1, B + 3, A + 3);   // tread on top
      idx.push(A + 2, B + 2, B + 0, A + 2, B + 0, A + 0);   // soffit
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx); g.computeVertexNormals();
    return g;
  }
  /* a member of length L pointing out of (0,0) in the XY plane at angle `rot`
     measured from +Y (a blade, a spoke, a raking leg), thickness `th` in Z. */
  function arm(k, L, wide, th, rot, ox, oy, oz){
    var g = k.box(wide, Math.max(1e-4, L), th, 0, L / 2, 0);
    g.rotateZ(rot);
    g.translate(ox, oy, oz);
    return g;
  }

  /* ── mills, towers, tanks ─────────────────────────────────────────────── */
  AR_EXT.geom.windmill = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE, P = [], i;
    var h = N('h', 12), r = N('r', 3), cap = N('cap', 2),
        sails = Math.max(2, Math.round(N('sails', 4))), sl = N('sail_len', 8);
    P.push({g: drum(T, r, r * 0.6, h, 24, 0)});                       // tapered brick tower
    P.push({g: new T.ConeGeometry(r * 0.74, Math.max(0.05, cap), 24)});
    P[P.length - 1].g.translate(0, h + cap / 2, 0);
    var hz = -(r * 0.6 + r * 0.16);                                   // hub on the -z face
    var hub = drum(T, r * 0.2, r * 0.2, r * 0.42, 12, 0);
    hub.rotateX(PI / 2); hub.translate(0, h, hz + r * 0.1);
    P.push({g: hub});
    for(i = 0; i < sails; i++){
      P.push({g: arm(k, sl, Math.max(0.3, sl * 0.09), Math.max(0.06, sl * 0.02), i * TAU / sails, 0, h, hz)});
    }
    return P;
  };

  AR_EXT.geom.lighthouse = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var h = N('h', 20), rb = N('r_base', 3), rt = N('r_top', 2), lan = Math.max(0.4, N('lantern', 2.5));
    var deck = Math.min(0.25, lan * 0.08), drumH = lan * 0.6, capH = lan - deck - drumH;
    return [{g: drum(T, rb, rt, h, 32, 0)},
            {g: drum(T, rt * 1.3, rt * 1.3, deck, 32, h)},
            {g: drum(T, rt * 1.05, rt * 1.05, drumH, 24, h + deck), sub: 'mat_glass'},
            {g: drum(T, rt * 1.12, 0.02, capH, 24, h + deck + drumH)}];
  };

  AR_EXT.geom.water_tower = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE, P = [], i;
    var h = N('h', 15), rt = N('r_tank', 4), th = Math.min(N('tank_h', 4), h * 0.9),
        legs = Math.max(3, Math.round(N('legs', 4)));
    var lh = Math.max(0.2, h - th), lr = rt * 0.72;
    for(i = 0; i < legs; i++){
      var a = i * TAU / legs;
      P.push({g: k.box(rt * 0.09, lh, rt * 0.09, lr * Math.cos(a), lh / 2, -lr * Math.sin(a))});
    }
    var ring = new T.TorusGeometry(lr, rt * 0.03, 6, Math.max(8, legs * 6));
    ring.rotateX(PI / 2); ring.translate(0, lh * 0.55, 0);
    P.push({g: ring});
    P.push({g: drum(T, rt, rt, th, 32, h - th)});                    // the tank
    return P;
  };

  AR_EXT.geom.silo = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var r = N('r', 3), h = N('h', 12), cn = Math.max(0.05, N('cone', 2));
    var cone = new T.ConeGeometry(r, cn, 32);
    cone.translate(0, h + cn / 2, 0);
    return [{g: drum(T, r, r, h, 32, 0)}, {g: cone}];
  };

  /* ── shells & shelters ────────────────────────────────────────────────── */
  AR_EXT.geom.geodesic_dome = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var r = N('r', 8), det = Math.max(1, Math.min(4, Math.round(N('detail', 1))));
    var g = new T.IcosahedronGeometry(r, det);
    var pos = g.attributes.position;                                  // flatten the lower half onto the ground
    for(var i = 0; i < pos.count; i++){ if(pos.getY(i) < 0) pos.setY(i, 0); }
    pos.needsUpdate = true;
    g.computeVertexNormals();
    return [{g: g}];
  };

  AR_EXT.geom.tent = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var r = N('r', 6), h = N('h', 5), sides = Math.max(3, Math.round(N('sides', 8)));
    var g = new T.ConeGeometry(r, h, sides);
    g.translate(0, h / 2, 0);
    return [{g: g}, {g: drum(T, r * 0.035, r * 0.035, h, 8, 0)}];
  };

  AR_EXT.geom.gazebo = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE, P = [], i;
    var r = N('r', 2.5), h = N('h', 2.6), posts = Math.max(3, Math.round(N('posts', 6))), rh = N('roof_h', 1.2);
    P.push({g: drum(T, r * 1.06, r * 1.06, 0.15, Math.max(8, posts * 4), 0)});
    for(i = 0; i < posts; i++){
      var a = i * TAU / posts;
      P.push({g: k.box(0.12, h - 0.15, 0.12, r * 0.92 * Math.cos(a), 0.15 + (h - 0.15) / 2, -r * 0.92 * Math.sin(a))});
    }
    var roof = new T.ConeGeometry(r * 1.06, Math.max(0.05, rh), posts);
    roof.translate(0, h + rh / 2, 0);
    P.push({g: roof});
    return P;
  };

  /* ── monuments ────────────────────────────────────────────────────────── */
  AR_EXT.geom.obelisk = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var h = N('h', 10), w = N('w', 1.2), top = w * 0.62, S = Math.SQRT2;
    var shaft = new T.CylinderGeometry(top / S, w / S, h * 0.9, 4);
    shaft.rotateY(PI / 4); shaft.translate(0, h * 0.45, 0);
    var pyr = new T.ConeGeometry(top / S, h * 0.1, 4);
    pyr.rotateY(PI / 4); pyr.translate(0, h * 0.95, 0);
    return [{g: shaft}, {g: pyr}];
  };

  AR_EXT.geom.arch_monument = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 8), h = N('h', 10), dd = N('d', 3);
    var ow = Math.min(N('opening_w', 4), w * 0.9), oh = Math.min(N('opening_h', 7), h * 0.92);
    var leg = (w - ow) / 2;
    return [{g: k.box(leg, oh, dd, -(w - leg) / 2, oh / 2, 0)},
            {g: k.box(leg, oh, dd, (w - leg) / 2, oh / 2, 0)},
            {g: k.box(w, h - oh, dd, 0, oh + (h - oh) / 2, 0)}];
  };

  AR_EXT.geom.spire = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var r = N('r', 3), h = N('h', 12), sides = Math.max(3, Math.round(N('sides', 8)));
    var cone = new T.ConeGeometry(r, h * 0.88, sides);
    cone.translate(0, h * 0.12 + h * 0.44, 0);
    return [{g: drum(T, r, r, h * 0.12, sides, 0)}, {g: cone}];
  };

  AR_EXT.geom.minaret = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE;
    var r = N('r', 1.5), h = N('h', 25);
    var by = Math.max(0.15, Math.min(0.92, N('balcony', 0.7))) * h;
    var rail = new T.TorusGeometry(r * 1.6, r * 0.05, 6, 24);
    rail.rotateX(PI / 2); rail.translate(0, by + 0.75, 0);
    return [{g: drum(T, r, r * 0.62, h * 0.9, 24, 0)},
            {g: drum(T, r * 1.6, r * 1.6, 0.3, 24, by - 0.15)},
            {g: rail},
            {g: drum(T, r * 0.75, 0.02, h * 0.1, 24, h * 0.9)}];
  };

  /* ── big structures ───────────────────────────────────────────────────── */
  AR_EXT.geom.stadium_ring = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, P = [], i;
    var rx = N('rx', 60), rz = N('rz', 45), tiers = Math.max(1, Math.min(12, Math.round(N('tiers', 3)))),
        th = N('tier_h', 4), td = N('tier_d', 8);
    for(i = 0; i < tiers; i++){
      var fo = Math.max(0.06, (rx - (tiers - 1 - i) * td) / rx);      // the TOP tier is the full rx/rz
      var fi = Math.max(0.04, (rx - (tiers - i) * td) / rx);
      P.push({g: ringBand(k.THREE, rx * fo, rz * fo, rx * fi, rz * fi, i * th, th, 48)});
    }
    return P;
  };

  AR_EXT.geom.wind_turbine = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE, P = [], i;
    var h = N('h', 60), bl = N('blade', 30), rm = N('r_mast', 2);
    P.push({g: drum(T, rm, rm * 0.45, h, 24, 0)});
    var hy = h + rm * 0.55, hz = -rm * 0.6;
    P.push({g: k.box(rm * 1.2, rm * 1.1, rm * 3, 0, hy, hz)});        // nacelle
    var hub = new T.ConeGeometry(rm * 0.55, rm * 1.2, 16);
    hub.rotateX(-PI / 2); hub.translate(0, hy, hz - rm * 2.1);
    P.push({g: hub});
    for(i = 0; i < 3; i++){
      P.push({g: arm(k, bl, Math.max(0.3, bl * 0.055), Math.max(0.1, bl * 0.012), i * TAU / 3, 0, hy, hz - rm * 2.6)});
    }
    return P;
  };

  AR_EXT.geom.pyramid_stepped = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, P = [], i;
    var w = N('w', 30), steps = Math.max(1, Math.min(40, Math.round(N('steps', 5)))), h = N('h', 20);
    var sh = h / steps;
    for(i = 0; i < steps; i++){
      var side = w * (1 - i / steps);
      P.push({g: k.box(side, sh, side, 0, i * sh + sh / 2, 0)});
    }
    return P;
  };

  AR_EXT.geom.ferris_wheel = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); }, T = k.THREE, P = [], i;
    var r = N('r', 15), cab = Math.max(3, Math.min(48, Math.round(N('cabins', 12))));
    var hy = r + Math.max(0.5, r * 0.07), rt = r * 0.035, off = r * 0.09;
    for(i = -1; i <= 1; i += 2){                                      // two rims
      var rim = new T.TorusGeometry(r, rt, 8, 48);
      rim.translate(0, hy, i * off);
      P.push({g: rim});
    }
    var hub = drum(T, r * 0.05, r * 0.05, off * 2.4, 12, 0);
    hub.rotateX(PI / 2); hub.translate(0, hy, 0);
    P.push({g: hub});
    for(i = 0; i < cab; i++){
      var a = i * TAU / cab, cw = r * 0.09;
      P.push({g: arm(k, r, r * 0.012, r * 0.012, a, 0, hy, 0)});
      P.push({g: k.box(cw, cw * 1.2, cw * 1.6, -r * Math.sin(a), hy + r * Math.cos(a) - cw * 0.6, 0)});
    }
    var lx = r * 0.6, L = Math.sqrt(lx * lx + hy * hy);
    for(i = -1; i <= 1; i += 2){
      P.push({g: arm(k, L, r * 0.03, r * 0.03, Math.atan2(lx, hy), lx, 0, i * off * 1.4)});
      P.push({g: arm(k, L, r * 0.03, r * 0.03, Math.atan2(-lx, hy), -lx, 0, i * off * 1.4)});
    }
    return P;
  };

  AR_EXT.label.windmill = 'Windmill';
  AR_EXT.label.lighthouse = 'Lighthouse';
  AR_EXT.label.water_tower = 'Water tower';
  AR_EXT.label.silo = 'Silo';
  AR_EXT.label.geodesic_dome = 'Geodesic dome';
  AR_EXT.label.tent = 'Tent';
  AR_EXT.label.gazebo = 'Gazebo';
  AR_EXT.label.obelisk = 'Obelisk';
  AR_EXT.label.arch_monument = 'Monumental arch';
  AR_EXT.label.spire = 'Spire';
  AR_EXT.label.minaret = 'Minaret';
  AR_EXT.label.stadium_ring = 'Stadium ring';
  AR_EXT.label.wind_turbine = 'Wind turbine';
  AR_EXT.label.pyramid_stepped = 'Stepped pyramid';
  AR_EXT.label.ferris_wheel = 'Ferris wheel';
})();
