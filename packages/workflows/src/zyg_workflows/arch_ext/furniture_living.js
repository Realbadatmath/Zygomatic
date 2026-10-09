// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* furniture_living — the pieces that make a room readable: beds, wardrobes,
   nightstands, seating, tables, chairs, desks, bookcases, a tv unit, a rug and
   a floor lamp. Everything is boxes plus a couple of cylinders.

   FRAME (the same for all 14 kinds, and the same in arch_blender_ext/):
     · the record's x/z is the FOOTPRINT CENTRE, the bottom sits at y = 0;
     · p.w is the width along local X, p.d (or p.l on a bed) the depth along
       local Z, p.h the height along Y;
     · the FRONT faces local -Z, so a record with ry = 0 faces north (up in the
       top view) — a wardrobe on the east wall wants ry = +pi/2 (front west).
   Sub-materials: mat_timber for frames and carcasses, mat_paint_white for the
   soft parts (mattresses, cushions, lampshades) so a single record still reads
   as furniture whatever material the user gives it. */
(function(){
  function cyl(k, rTop, rBot, h, cy, cx, cz, seg){
    var g = new k.THREE.CylinderGeometry(Math.max(rTop, 1e-4), Math.max(rBot, 1e-4),
                                         Math.max(h, 1e-4), Math.max(6, seg || 20));
    g.translate(cx || 0, cy || 0, cz || 0);
    return g;
  }

  /* ── beds ── the head board stands at -Z, so ry = 0 puts the head against a
     north wall and the sleeper's feet point south. Total height is p.head. */
  function bedParts(p, k, dw, dl, dh, dhead){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', dw), l = N('l', dl), h = N('h', dh);
    var head = Math.max(N('head', dhead), h + 0.15);
    var P = [];
    P.push({g: k.box(w, h * 0.62, l, 0, h * 0.31, 0), sub: 'mat_timber'});                    // base frame
    P.push({g: k.box(w - 0.08, h * 0.38, l - 0.08, 0, h * 0.81, 0), sub: 'mat_paint_white'}); // mattress
    P.push({g: k.box(w, head, 0.06, 0, head / 2, -l / 2 + 0.03), sub: 'mat_timber'});         // head board
    var pw = w > 1.2 ? (w / 2 - 0.10) : (w - 0.16);                                           // one or two pillows
    var px = w > 1.2 ? (pw / 2 + 0.05) : 0;
    P.push({g: k.box(pw, 0.12, 0.34, -px, h + 0.06, -l / 2 + 0.30), sub: 'mat_paint_white'});
    if (w > 1.2) P.push({g: k.box(pw, 0.12, 0.34, px, h + 0.06, -l / 2 + 0.30), sub: 'mat_paint_white'});
    return P;
  }
  AR_EXT.geom.bed_single = function(p, k){ return bedParts(p, k, 0.9, 2.0, 0.5, 0.9); };
  AR_EXT.geom.bed_double = function(p, k){ return bedParts(p, k, 1.6, 2.0, 0.5, 1.0); };

  /* ── a carcass with fronts (wardrobe, nightstand) ── */
  function carcass(p, k, dw, dd, dh, fronts, handles){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', dw), d = N('d', dd), h = N('h', dh);
    var P = [{g: k.box(w, h, d, 0, h / 2, 0), sub: 'mat_timber'}];
    var i, fw = (w - 0.06) / fronts, fh = (h - 0.12) / (fronts > 1 && dh < 1.0 ? fronts : 1);
    if (dh >= 1.0) {                                   // tall: full-height leaves side by side
      for (i = 0; i < fronts; i++)
        P.push({g: k.box(fw - 0.01, h - 0.10, 0.025, -w / 2 + 0.03 + fw * (i + 0.5), h / 2, -d / 2 + 0.013),
                sub: 'mat_paint_white'});
    } else {                                           // low: drawers stacked
      for (i = 0; i < fronts; i++)
        P.push({g: k.box(w - 0.06, fh - 0.02, 0.02, 0, 0.06 + fh * (i + 0.5), -d / 2 + 0.011),
                sub: 'mat_paint_white'});
    }
    if (handles)
      for (i = 0; i < fronts; i++)
        P.push({g: k.box(0.02, dh >= 1.0 ? 0.14 : 0.02, 0.03,
                         dh >= 1.0 ? (i === 0 ? -0.05 : 0.05) : 0,
                         dh >= 1.0 ? h * 0.55 : (0.06 + ((h - 0.12) / fronts) * (i + 0.5)),
                         -d / 2 + 0.028), sub: 'mat_steel'});
    return P;
  }
  AR_EXT.geom.wardrobe = function(p, k){ return carcass(p, k, 1.2, 0.6, 2.1, 2, true); };
  AR_EXT.geom.nightstand = function(p, k){ return carcass(p, k, 0.45, 0.4, 0.55, 2, true); };

  /* ── seating ── the back stands at +Z, so the seat faces -Z (north at ry 0) */
  function seating(p, k, dw, dd, dh, dseat){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', dw), d = N('d', dd), h = N('h', dh);
    var seat = Math.min(N('seat', dseat), h - 0.15);
    var P = [];
    P.push({g: k.box(w, seat * 0.4, d, 0, seat * 0.2, 0), sub: 'mat_timber'});                    // plinth
    P.push({g: k.box(w - 0.30, seat * 0.6, d - 0.22, 0, seat * 0.7, -0.11), sub: 'mat_paint_white'}); // cushion
    P.push({g: k.box(w, h, 0.22, 0, h / 2, d / 2 - 0.11), sub: 'mat_paint_white'});               // back
    P.push({g: k.box(0.15, seat + 0.22, d, -(w / 2 - 0.075), (seat + 0.22) / 2, 0), sub: 'mat_paint_white'});
    P.push({g: k.box(0.15, seat + 0.22, d, (w / 2 - 0.075), (seat + 0.22) / 2, 0), sub: 'mat_paint_white'});
    return P;
  }
  AR_EXT.geom.sofa = function(p, k){ return seating(p, k, 2.2, 0.9, 0.85, 0.45); };
  AR_EXT.geom.armchair = function(p, k){ return seating(p, k, 0.9, 0.9, 0.85, 0.45); };

  /* ── tables ── */
  function table(p, k, dw, dd, dh, topT){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', dw), d = N('d', dd), h = N('h', dh);
    var t = Math.min(topT, h * 0.4), lh = h - t, i, j;
    var P = [{g: k.box(w, t, d, 0, h - t / 2, 0), sub: 'mat_timber'}];
    for (i = -1; i <= 1; i += 2)
      for (j = -1; j <= 1; j += 2)
        P.push({g: k.box(0.06, lh, 0.06, i * (w / 2 - 0.06), lh / 2, j * (d / 2 - 0.06)), sub: 'mat_timber'});
    return P;
  }
  AR_EXT.geom.coffee_table = function(p, k){ return table(p, k, 1.1, 0.6, 0.42, 0.05); };
  AR_EXT.geom.dining_table = function(p, k){ return table(p, k, 1.8, 0.9, 0.75, 0.06); };

  AR_EXT.geom.chair = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 0.45), d = N('d', 0.45), h = N('h', 0.9);
    var seat = Math.min(N('seat', 0.45), h - 0.2), i, j;
    var P = [{g: k.box(w, 0.05, d, 0, seat - 0.025, 0), sub: 'mat_paint_white'},
             {g: k.box(w, h - seat, 0.05, 0, seat + (h - seat) / 2, d / 2 - 0.025), sub: 'mat_timber'}];
    for (i = -1; i <= 1; i += 2)
      for (j = -1; j <= 1; j += 2)
        P.push({g: k.box(0.04, seat - 0.05, 0.04, i * (w / 2 - 0.04), (seat - 0.05) / 2, j * (d / 2 - 0.04)),
                sub: 'mat_timber'});
    return P;
  };

  AR_EXT.geom.desk = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 1.4), d = N('d', 0.7), h = N('h', 0.75);
    return [{g: k.box(w, 0.04, d, 0, h - 0.02, 0), sub: 'mat_timber'},
            {g: k.box(0.04, h - 0.04, d - 0.06, -(w / 2 - 0.02), (h - 0.04) / 2, 0), sub: 'mat_timber'},
            {g: k.box(0.04, h - 0.04, d - 0.06, (w / 2 - 0.02), (h - 0.04) / 2, 0), sub: 'mat_timber'},
            {g: k.box(w - 0.12, 0.35, 0.03, 0, h - 0.04 - 0.175, d / 2 - 0.02), sub: 'mat_timber'}];
  };

  AR_EXT.geom.bookcase = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 0.9), d = N('d', 0.35), h = N('h', 2.0);
    var n = Math.max(1, Math.min(20, Math.round(N('shelves', 5))));
    var P = [{g: k.box(0.03, h, d, -(w / 2 - 0.015), h / 2, 0), sub: 'mat_timber'},
             {g: k.box(0.03, h, d, (w / 2 - 0.015), h / 2, 0), sub: 'mat_timber'},
             {g: k.box(w, 0.03, d, 0, 0.015, 0), sub: 'mat_timber'},
             {g: k.box(w, 0.03, d, 0, h - 0.015, 0), sub: 'mat_timber'},
             {g: k.box(w - 0.06, h - 0.06, 0.015, 0, h / 2, d / 2 - 0.008), sub: 'mat_paint_white'}];
    for (var i = 1; i < n; i++)
      P.push({g: k.box(w - 0.06, 0.02, d - 0.02, 0, h * i / n, 0), sub: 'mat_timber'});
    return P;
  };

  AR_EXT.geom.tv_unit = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 1.6), d = N('d', 0.45), h = N('h', 0.5), diag = N('screen', 1.2);
    var sw = diag * 16 / Math.sqrt(16 * 16 + 9 * 9), sh = diag * 9 / Math.sqrt(16 * 16 + 9 * 9);
    if (sw > w) { sh *= w / sw; sw = w; }                 // never wider than the unit
    return [{g: k.box(w, h, d, 0, h / 2, 0), sub: 'mat_timber'},
            {g: k.box(w / 2 - 0.04, h - 0.10, 0.02, -w / 4, h / 2, -d / 2 + 0.011), sub: 'mat_paint_white'},
            {g: k.box(w / 2 - 0.04, h - 0.10, 0.02, w / 4, h / 2, -d / 2 + 0.011), sub: 'mat_paint_white'},
            {g: k.box(0.30, 0.06, 0.20, 0, h + 0.03, d / 2 - 0.12), sub: 'mat_steel'},
            {g: k.box(sw, sh, 0.04, 0, h + 0.06 + sh / 2, d / 2 - 0.12), sub: 'mat_paint_dark'}];
  };

  AR_EXT.geom.rug = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var w = N('w', 2.4), d = N('d', 1.7), t = Math.max(N('t', 0.02), 0.005);
    return [{g: k.box(w, t, d, 0, t / 2, 0)}];
  };

  AR_EXT.geom.lamp_floor = function(p, k){
    var N = function(key, d){ return k.num(p[key], d); };
    var h = N('h', 1.6), r = N('r', 0.2);
    var shade = Math.min(0.30, h * 0.3);
    return [{g: cyl(k, r * 0.55, r * 0.55, 0.03, 0.015, 0, 0, 24), sub: 'mat_steel'},
            {g: cyl(k, 0.018, 0.018, h - shade, (h - shade) / 2, 0, 0, 12), sub: 'mat_steel'},
            {g: cyl(k, r * 0.7, r, shade, h - shade / 2, 0, 0, 24), sub: 'mat_paint_white'}];
  };

  AR_EXT.label.bed_single = 'Single bed';
  AR_EXT.label.bed_double = 'Double bed';
  AR_EXT.label.wardrobe = 'Wardrobe';
  AR_EXT.label.nightstand = 'Nightstand';
  AR_EXT.label.sofa = 'Sofa';
  AR_EXT.label.armchair = 'Armchair';
  AR_EXT.label.coffee_table = 'Coffee table';
  AR_EXT.label.dining_table = 'Dining table';
  AR_EXT.label.chair = 'Chair';
  AR_EXT.label.desk = 'Desk';
  AR_EXT.label.bookcase = 'Bookcase';
  AR_EXT.label.tv_unit = 'TV unit';
  AR_EXT.label.rug = 'Rug';
  AR_EXT.label.lamp_floor = 'Floor lamp';
})();
