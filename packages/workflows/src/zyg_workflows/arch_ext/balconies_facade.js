// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* balconies_facade — things that hang off a facade: balcony, canopy, awning,
   cornice, pilaster, louvre_fins, sunshade, string_course, parapet_cap.

   LOCAL FRAME. The record's x/z sits on the wall's OUTER face, bottom at y=0,
   +X along the wall (the record carries the wall's ry). Every one of these
   kinds projects toward LOCAL -Z, which is the direction the assistant has
   already turned outward: the world direction of local -Z is
   (-sin(ry), -cos(ry)), and the assistant flips ry by PI whenever that vector
   points back at the group's centroid. So "away from the building" is always
   -Z here and the geometry never has to know which side of the box it is on.
   parapet_cap is the one exception: it straddles the wall (z from -w/2 to
   +w/2), because a coping stone sits ON the wall, not off it. */
(function(){
  AR_EXT.geom.balcony = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',2.4), dd=N('d',1.2), t=N('t',0.18), rh=N('rail_h',1.0), ps=N('post',0.04);
    var P=[], i;
    P.push({g: k.box(w, t, dd, 0, t/2, -dd/2)});                    // the projecting slab
    var top=t+rh, bar=ps*1.4, ybar=top-bar/2;
    var xin=w/2-ps/2, zout=-dd+ps/2;
    var n=Math.max(2, Math.round(w/0.6)+1);                          // outer-edge balusters
    for(i=0;i<n;i++) P.push({g: k.box(ps, rh, ps, -xin + 2*xin*i/(n-1), t+rh/2, zout)});
    P.push({g: k.box(ps, rh, ps, -xin, t+rh/2, -ps/2)});             // the two returns at the wall
    P.push({g: k.box(ps, rh, ps,  xin, t+rh/2, -ps/2)});
    P.push({g: k.box(w, bar, bar, 0, ybar, -dd+bar/2)});             // hand rail, three sides
    P.push({g: k.box(bar, bar, dd, -(w/2-bar/2), ybar, -dd/2)});
    P.push({g: k.box(bar, bar, dd,  (w/2-bar/2), ybar, -dd/2)});
    return P;
  };
  AR_EXT.geom.canopy = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',3), dd=N('d',1.5), t=N('t',0.12), hd=N('h_drop',0);
    /* profile (u = distance out from the wall, v = height); rotateY(90) maps
       profile u -> -Z, v -> Y and the extrusion -> X. */
    var g=k.prism([[0,0],[dd,-hd],[dd,t-hd],[0,t]], w);
    g.rotateY(Math.PI/2); g.computeVertexNormals();
    return [{g: g}];
  };
  AR_EXT.geom.awning = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',3), dd=N('d',1.2), ang=N('angle',20), t=0.04;
    var drop=dd*Math.tan(Math.max(0, Math.min(70, ang))*Math.PI/180);
    var g=k.prism([[0,-t],[dd,-drop-t],[dd,-drop],[0,0]], w);
    g.rotateY(Math.PI/2); g.computeVertexNormals();
    return [{g: g, sub: 'mat_paint_dark'}];
  };
  AR_EXT.geom.cornice = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',4), h=N('h',0.3), dd=N('d',0.25);
    return [{g: k.box(L, h*0.7, dd, 0, h*0.35, -dd/2)},
            {g: k.box(L, h*0.3, dd*0.7, 0, h*0.85, -dd*0.35)}];
  };
  AR_EXT.geom.pilaster = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var h=N('h',2.7), w=N('w',0.4), dd=N('d',0.12);
    return [{g: k.box(w, h, dd, 0, h/2, -dd/2)}];
  };
  AR_EXT.geom.louvre_fins = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',3), h=N('h',2.7), fin=N('fin',0.3), sp=Math.max(0.05, N('spacing',0.4)), t=N('t',0.03);
    var P=[], n=Math.max(2, Math.round(w/sp)+1), i;
    for(i=0;i<n;i++) P.push({g: k.box(t, h, fin, -w/2 + t/2 + (w-t)*i/(n-1), h/2, -fin/2)});
    return P;
  };
  AR_EXT.geom.sunshade = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',3), dd=N('d',0.8), t=N('t',0.05), sl=Math.max(2, Math.round(N('slats',8)));
    var P=[], db=(dd/sl)*0.7, i;
    for(i=0;i<sl;i++) P.push({g: k.box(w, t, db, 0, t/2, -(db/2 + (dd-db)*i/(sl-1)))});
    P.push({g: k.box(t, t, dd, -(w/2-t/2), t/2, -dd/2)});
    P.push({g: k.box(t, t, dd,  (w/2-t/2), t/2, -dd/2)});
    return P;
  };
  AR_EXT.geom.string_course = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',4), h=N('h',0.12), dd=N('d',0.08);
    return [{g: k.box(L, h, dd, 0, h/2, -dd/2)}];
  };
  AR_EXT.geom.parapet_cap = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',4), w=N('w',0.3), t=N('t',0.06);
    return [{g: k.box(L, t, w, 0, t/2, 0)}];        // straddles the wall, not projecting
  };
  AR_EXT.label.balcony = 'Balcony';
  AR_EXT.label.canopy = 'Canopy';
  AR_EXT.label.awning = 'Awning';
  AR_EXT.label.cornice = 'Cornice';
  AR_EXT.label.pilaster = 'Pilaster';
  AR_EXT.label.louvre_fins = 'Louvre fins';
  AR_EXT.label.sunshade = 'Sunshade';
  AR_EXT.label.string_course = 'String course';
  AR_EXT.label.parapet_cap = 'Parapet cap';
})();
