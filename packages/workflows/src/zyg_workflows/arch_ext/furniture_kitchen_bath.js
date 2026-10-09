// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* furniture_kitchen_bath — kitchen units, white goods and sanitary ware.

   Frame (same as furniture_living): the record's x/z is the CENTRE of the
   footprint, the bottom sits at y = 0, and the piece FACES local -Z (north in
   the top view) — so a unit standing against the north wall of a room is
   turned ry = PI to face back into the room.

   Every kind's bounding box is EXACTLY what its parameters say: a fridge with
   w 0.7, h 1.8, d 0.7 measures 0.7 x 1.8 x 0.7 and nothing sticks out. Handles,
   taps, door lines and hobs are all built inside that box, so the tools can
   pack a run of units against a wall with plain arithmetic. */
(function(){
  var STEEL='mat_steel', GLASS='mat_glass', STONE='mat_stone', DARK='mat_paint_dark', WHITE='mat_paint_white';

  function cyl(k, r, h, seg, cx, cy, cz, axis){        // axis: 'y' (default), 'z' or 'x'
    var g=new k.THREE.CylinderGeometry(Math.max(r,1e-4), Math.max(r,1e-4), Math.max(h,1e-4), seg||24);
    if(axis==='z') g.rotateX(Math.PI/2);
    else if(axis==='x') g.rotateZ(Math.PI/2);
    g.translate(cx||0, cy||0, cz||0);
    return g;
  }

  /* a rectangular rim: the four strips left when an inner box is taken out of
     an outer one. Used for the sink basin and the bathtub. */
  function rim(k, w, d, y0, hh, t, cy_off){
    var out=[], cy=y0+hh/2, cz=cy_off||0;
    out.push({g: k.box(w, hh, t, 0, cy, cz + d/2 - t/2), sub: null});
    out.push({g: k.box(w, hh, t, 0, cy, cz - d/2 + t/2), sub: null});
    out.push({g: k.box(t, hh, d - 2*t, -w/2 + t/2, cy, cz), sub: null});
    out.push({g: k.box(t, hh, d - 2*t,  w/2 - t/2, cy, cz), sub: null});
    return out;
  }

  /* ── kitchen ───────────────────────────────────────────────────────────── */
  AR_EXT.geom.kitchen_counter = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',2.0), d=N('d',0.6), h=N('h',0.9), top=Math.min(N('top',0.04), h*0.5);
    var P=[];
    P.push({g: k.box(L, h - top, d, 0, (h - top)/2, 0)});                        // carcass
    P.push({g: k.box(L, top, d, 0, h - top/2, 0), sub: STONE});                  // worktop
    P.push({g: k.box(Math.max(L - 0.1, 0.05), 0.02, 0.02, 0, h - top - 0.08, -d/2 + 0.01), sub: STEEL});
    return P;
  };
  AR_EXT.geom.kitchen_island = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',2.0), d=N('d',0.9), h=N('h',0.9), top=0.04;
    return [{g: k.box(w - 0.04, h - top, d - 0.04, 0, (h - top)/2, 0)},
            {g: k.box(w, top, d, 0, h - top/2, 0), sub: STONE},
            {g: k.box(Math.max(w - 0.3, 0.05), 0.02, 0.02, 0, h - top - 0.1, -d/2 + 0.03), sub: STEEL}];
  };
  AR_EXT.geom.wall_cabinet = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',1.2), d=N('d',0.35), h=N('h',0.7);
    return [{g: k.box(L, h, d, 0, h/2, 0)},
            {g: k.box(0.02, h - 0.06, 0.01, 0, h/2, -d/2 + 0.005), sub: DARK},    // door split
            {g: k.box(Math.max(L - 0.12, 0.05), 0.02, 0.02, 0, 0.06, -d/2 + 0.01), sub: STEEL}];
  };
  AR_EXT.geom.sink = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), d=N('d',0.5), h=N('h',0.9), t=0.07, rimh=0.24;
    var P=[{g: k.box(w, h - rimh, d, 0, (h - rimh)/2, 0)}];                       // cabinet
    var r=rim(k, w, d, h - rimh, rimh, t, 0);                                     // basin rim
    for(var i=0;i<r.length;i++){ P.push({g: r[i].g, sub: STEEL}); }
    P.push({g: k.box(w - 2*t, 0.02, d - 2*t, 0, h - rimh + 0.01, 0), sub: STEEL});  // basin floor
    P.push({g: cyl(k, 0.02, 0.18, 12, 0, h - 0.09, d/2 - 0.05), sub: STEEL});       // tap
    return P;
  };
  AR_EXT.geom.stove = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), d=N('d',0.6), h=N('h',0.9), hob=0.03;
    var P=[{g: k.box(w, h - hob, d, 0, (h - hob)/2, 0)},
           {g: k.box(w, hob, d, 0, h - hob/2, 0), sub: STEEL},
           {g: k.box(w - 0.06, (h - hob)*0.5, 0.02, 0, (h - hob)*0.4, -d/2 + 0.01), sub: GLASS}];
    for(var i=0;i<4;i++){
      P.push({g: cyl(k, 0.075, 0.006, 14, (i%2 ? 1 : -1)*w*0.22, h - 0.003, (i<2 ? 1 : -1)*d*0.2), sub: DARK});
    }
    return P;
  };
  AR_EXT.geom.fridge = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.7), d=N('d',0.7), h=N('h',1.8);
    return [{g: k.box(w, h, d, 0, h/2, 0)},
            {g: k.box(w, 0.02, 0.01, 0, h*0.62, -d/2 + 0.005), sub: DARK},        // door line
            {g: k.box(0.03, Math.min(0.5, h*0.3), 0.04, w/2 - 0.09, h*0.78, -d/2 + 0.02), sub: STEEL},
            {g: k.box(0.03, Math.min(0.5, h*0.3), 0.04, w/2 - 0.09, h*0.42, -d/2 + 0.02), sub: STEEL}];
  };
  AR_EXT.geom.dishwasher = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), d=N('d',0.6), h=N('h',0.85);
    return [{g: k.box(w, h, d, 0, h/2, 0)},
            {g: k.box(w - 0.06, h - 0.12, 0.02, 0, h/2 - 0.02, -d/2 + 0.01), sub: STEEL},
            {g: k.box(w - 0.12, 0.03, 0.03, 0, h - 0.07, -d/2 + 0.015), sub: STEEL}];
  };
  AR_EXT.geom.washing_machine = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), d=N('d',0.6), h=N('h',0.85);
    return [{g: k.box(w, h, d, 0, h/2, 0)},
            {g: cyl(k, Math.min(0.22, w*0.38), 0.03, 20, 0, h*0.5, -d/2 + 0.015, 'z'), sub: GLASS},
            {g: k.box(w - 0.08, 0.08, 0.02, 0, h - 0.08, -d/2 + 0.01), sub: DARK}];  // control panel
  };

  /* ── bathroom ──────────────────────────────────────────────────────────── */
  AR_EXT.geom.toilet = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.4), d=N('d',0.7), h=N('h',0.8), cist=0.2, pan=Math.min(0.4, h - 0.1);
    var pd=Math.max(d - cist, 0.1);
    return [{g: k.box(w, pan, pd, 0, pan/2, -d/2 + pd/2)},                        // pan
            {g: k.box(w, 0.04, pd - 0.04, 0, pan + 0.02, -d/2 + pd/2), sub: WHITE}, // seat
            {g: k.box(w, h - pan, cist, 0, pan + (h - pan)/2, d/2 - cist/2)}];    // cistern
  };
  AR_EXT.geom.bathtub = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('l',1.7), w=N('w',0.75), h=N('h',0.55), t=0.06, base=0.12;
    var P=[{g: k.box(L, base, w, 0, base/2, 0)}];                                 // base + tub floor
    P.push({g: k.box(L, h - base, t, 0, base + (h - base)/2,  w/2 - t/2)});
    P.push({g: k.box(L, h - base, t, 0, base + (h - base)/2, -w/2 + t/2)});
    P.push({g: k.box(t, h - base, w - 2*t, -L/2 + t/2, base + (h - base)/2, 0)});
    P.push({g: k.box(t, h - base, w - 2*t,  L/2 - t/2, base + (h - base)/2, 0)});
    P.push({g: cyl(k, 0.02, Math.min(0.14, h - base - 0.02), 12, -L/2 + 0.12, h - 0.09, 0), sub: STEEL});
    return P;
  };
  AR_EXT.geom.shower = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.9), d=N('d',0.9), h=N('h',2.0), tray=Math.min(N('tray',0.05), h*0.5), g=0.02;
    return [{g: k.box(w, tray, d, 0, tray/2, 0)},                                  // tray
            {g: k.box(g, h - tray, d, w/2 - g/2, tray + (h - tray)/2, 0), sub: GLASS},
            {g: k.box(w, h - tray, g, 0, tray + (h - tray)/2, -d/2 + g/2), sub: GLASS},
            {g: k.box(0.06, 0.30, 0.06, -w/2 + 0.06, h - 0.55, d/2 - 0.06), sub: STEEL},   // riser
            {g: cyl(k, 0.09, 0.03, 16, -w/2 + 0.16, h - 0.28, d/2 - 0.16), sub: STEEL}];   // head
  };
  AR_EXT.geom.washbasin = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), d=N('d',0.45), h=N('h',0.85), bowl=0.13;
    return [{g: k.box(Math.min(0.25, w*0.5), h - 0.15, Math.min(0.25, d*0.6), 0, (h - 0.15)/2, 0)},  // pedestal
            {g: k.box(w, bowl, d, 0, h - 0.02 - bowl/2, 0)},                       // bowl block
            {g: k.box(w - 0.14, 0.02, d - 0.14, 0, h - 0.03, -0.02), sub: WHITE},  // basin floor
            {g: cyl(k, 0.02, 0.10, 12, 0, h - 0.05, d/2 - 0.05), sub: STEEL}];     // tap
  };
  AR_EXT.geom.mirror = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',0.6), h=N('h',0.8), t=N('t',0.02);
    return [{g: k.box(w, h, t/2, 0, h/2,  t/4)},                                   // backing
            {g: k.box(w - 0.04, h - 0.04, t/2, 0, h/2, -t/4), sub: GLASS}];        // glass
  };
  AR_EXT.geom.towel_rail = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',0.6);
    return [{g: k.box(0.02, 0.06, 0.10, -L/2 + 0.01, 0.03, 0), sub: STEEL},
            {g: k.box(0.02, 0.06, 0.10,  L/2 - 0.01, 0.03, 0), sub: STEEL},
            {g: cyl(k, 0.015, L, 12, 0, 0.03, -0.035, 'x'), sub: STEEL}];
  };
  AR_EXT.geom.boiler = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=N('r',0.3), h=N('h',1.2);
    return [{g: cyl(k, r, h*0.92, 24, 0, h*0.46, 0)},
            {g: cyl(k, r*0.6, h*0.08, 20, 0, h*0.96, 0), sub: STEEL},
            {g: k.box(r*1.2, 0.10, 0.02, 0, h*0.6, -r + 0.01), sub: DARK}];
  };

  AR_EXT.label.kitchen_counter = 'Kitchen counter';
  AR_EXT.label.kitchen_island = 'Kitchen island';
  AR_EXT.label.wall_cabinet = 'Wall cabinet';
  AR_EXT.label.sink = 'Sink';
  AR_EXT.label.stove = 'Cooker';
  AR_EXT.label.fridge = 'Fridge';
  AR_EXT.label.dishwasher = 'Dishwasher';
  AR_EXT.label.washing_machine = 'Washing machine';
  AR_EXT.label.toilet = 'Toilet';
  AR_EXT.label.bathtub = 'Bath';
  AR_EXT.label.shower = 'Shower';
  AR_EXT.label.washbasin = 'Washbasin';
  AR_EXT.label.mirror = 'Mirror';
  AR_EXT.label.towel_rail = 'Towel rail';
  AR_EXT.label.boiler = 'Boiler';
})();
