// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* site_landscape — everything that stands on the ground around a building:
   fences and hedges, four kinds of planting, street furniture, kerbs and
   pavements, parking bays and a curved piece of road.

   Local frame, as every kind here: the record's x/z is the object's centre in
   plan, the bottom sits at y = 0, up is +Y. A "long" kind (fence, hedge, kerb,
   sidewalk) runs along local +X and is rotated by the record's ry, exactly the
   way a wall is. Plan angles for road_curved are the studio convention:
   0 = +X (east), 90 = -Z (north / up in the top view), so a point at θ is
   (r cosθ, -r sinθ). Sizes are literal: tree_conifer h 8 r 2 is 4 x 8 x 4.

   GROUND (2026-09-07): the thin surfaces — flowerbed, sidewalk, parking_bay —
   carry the ground plane in two parameters gx, gz: the rise per metre along the
   record's LOCAL x and z. The record itself stays UPRIGHT (tilting it would lean
   whatever stands on it); the slab is SHEARED instead, so its corners land on
   the plane: y += gx*x + gz*z at every vertex. Blender does the same arithmetic
   in arch_blender_ext/site_landscape.py (there studio z is -y, hence the sign).
   Everything else is a point or a linear thing and is placed by the tool with a
   record y and, for a run, an rz lean — no parameter needed here. */
(function(){
  /* Shear a slab onto the ground plane: every vertex rises by gx*x + gz*z.
     A pure shear, so the plan footprint and the thickness are untouched. */
  function drape(g, gx, gz){
    if(!gx && !gz) return g;
    var pos=g.attributes.position, i;
    for(i=0;i<pos.count;i++) pos.setY(i, pos.getY(i) + gx*pos.getX(i) + gz*pos.getZ(i));
    pos.needsUpdate=true;
    g.computeVertexNormals();
    return g;
  }

  function arcSlab(k, r, a0, a1, w, t, seg){
    var THREE=k.THREE;
    var ri=Math.max(0.05, r-w/2), ro=r+w/2;
    var s0=a0*Math.PI/180, s1=a1*Math.PI/180;   /* rotateX(-90) maps shape +Y to -Z: the plan convention */
    var cw = s1 < s0;
    var sh=new THREE.Shape();
    sh.absarc(0,0,ro, s0, s1, cw);
    sh.absarc(0,0,ri, s1, s0, !cw);
    sh.closePath();
    var g=new THREE.ExtrudeGeometry(sh, {depth:t, bevelEnabled:false, curveSegments:Math.max(4, seg)});
    g.rotateX(-Math.PI/2);
    g.computeVertexNormals();
    return g;
  }

  /* ── boundaries ── */
  AR_EXT.geom.fence = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var L=N('len',5), h=N('h',1.2), np=Math.max(2,Math.round(N('posts',3)));
    var nr=Math.max(0,Math.round(N('rails',3))), t=N('t',0.04);
    var P=[], i;
    for(i=0;i<np;i++) P.push({g: k.box(t, h, t, -L/2 + L*i/(np-1), h/2, 0)});
    for(i=0;i<nr;i++) P.push({g: k.box(L, t*1.2, t*0.6, 0, h*(i+1)/(nr+0.4), 0)});
    return P;
  };
  AR_EXT.geom.hedge = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var L=N('len',5), h=N('h',1.2), w=N('w',0.6);
    return [{g: k.box(L, h, w, 0, h/2, 0), sub:'mat_grass'}];
  };

  /* ── planting ── */
  AR_EXT.geom.tree_conifer = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var h=Math.max(0.5,N('h',8)), r=Math.max(0.1,N('r',2));
    var rt=Math.max(0.05, Math.min(r*0.4, r*0.09 + 0.02));
    var g=new THREE.CylinderGeometry(rt*0.85, rt, h*0.2, 10); g.translate(0, h*0.1, 0);
    var c=new THREE.ConeGeometry(r, h*0.85, 20); c.translate(0, h*0.15 + h*0.425, 0);
    return [{g:g, sub:'mat_timber'}, {g:c, sub:'mat_grass'}];
  };
  AR_EXT.geom.tree_deciduous = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var h=Math.max(0.5,N('h',7)), rc=Math.max(0.1,N('r_can',3)), rt=Math.max(0.03,N('r_trunk',0.25));
    rt=Math.min(rt, rc*0.8);
    var trunk=Math.max(0.2, h-rc);
    var g=new THREE.CylinderGeometry(rt*0.8, rt, trunk, 12); g.translate(0, trunk/2, 0);
    var c=new THREE.SphereGeometry(rc, 32, 16); c.translate(0, h-rc, 0);
    return [{g:g, sub:'mat_timber'}, {g:c, sub:'mat_grass'}];
  };
  AR_EXT.geom.tree_palm = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var h=Math.max(0.5,N('h',7)), nf=Math.max(3,Math.round(N('fronds',7)));
    var P=[], i;
    var g=new THREE.CylinderGeometry(h*0.019, h*0.026, h, 10); g.translate(0, h/2, 0);
    P.push({g:g, sub:'mat_timber'});
    var L=h*0.34;
    for(i=0;i<nf;i++){
      var f=k.box(L, 0.05, 0.42, L/2, -0.025, 0);
      f.rotateZ(-0.34);
      f.rotateY(i*Math.PI*2/nf);
      f.translate(0, h, 0);
      P.push({g:f, sub:'mat_grass'});
    }
    return P;
  };
  AR_EXT.geom.shrub = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var r=Math.max(0.05,N('r',0.6)), h=Math.max(0.05,N('h',0.8));
    var g=new THREE.SphereGeometry(r, 14, 10);
    g.scale(1, h/(2*r), 1); g.translate(0, h/2, 0);
    return [{g:g, sub:'mat_grass'}];
  };
  AR_EXT.geom.flowerbed = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=N('w',3), d=N('d',1.5), t=N('t',0.15), gx=N('gx',0), gz=N('gz',0);
    return [{g: drape(k.box(w, t, d, 0, t/2, 0), gx, gz), sub:'mat_grass'}];
  };

  /* ── street furniture ── */
  AR_EXT.geom.lamp_post = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var h=Math.max(0.5,N('h',4)), r=Math.max(0.02,N('r',0.06));
    var g=new THREE.CylinderGeometry(r, r*1.35, h, 12); g.translate(0, h/2, 0);
    return [{g:g}, {g: k.box(0.36, 0.12, 0.36, 0, h-0.06, 0), sub:'mat_glass'}];
  };
  AR_EXT.geom.bench = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var L=Math.max(0.4,N('len',1.8)), h=Math.max(0.15,N('h',0.45)), d=0.45;
    var P=[{g: k.box(L, 0.06, d, 0, h-0.03, 0), sub:'mat_timber'}];
    P.push({g: k.box(0.07, h-0.06, d*0.8, -L/2+0.12, (h-0.06)/2, 0)});
    P.push({g: k.box(0.07, h-0.06, d*0.8,  L/2-0.12, (h-0.06)/2, 0)});
    return P;
  };
  AR_EXT.geom.bin = function(p, k){
    var THREE=k.THREE, N=function(a,b){ return k.num(p[a], b); };
    var r=Math.max(0.05,N('r',0.25)), h=Math.max(0.1,N('h',0.9));
    var g=new THREE.CylinderGeometry(r, r*0.85, h*0.9, 16); g.translate(0, h*0.45, 0);
    var lid=new THREE.CylinderGeometry(r, r, h*0.1, 16); lid.translate(0, h*0.95, 0);
    return [{g:g}, {g:lid, sub:'mat_paint_dark'}];
  };

  /* ── ground ── */
  AR_EXT.geom.kerb = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var L=N('len',5), h=N('h',0.12), w=N('w',0.15);
    return [{g: k.box(L, h, w, 0, h/2, 0)}];
  };
  AR_EXT.geom.sidewalk = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var L=N('len',10), w=N('w',2), t=N('t',0.06), gx=N('gx',0), gz=N('gz',0);
    return [{g: drape(k.box(L, t, w, 0, t/2, 0), gx, gz)}];
  };
  AR_EXT.geom.parking_bay = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=Math.max(0.4,N('w',2.5)), d=Math.max(0.4,N('d',5)), t=Math.max(0.005,N('t',0.02));
    var gx=N('gx',0), gz=N('gz',0);
    var lw=Math.min(0.12, w/6), lt=t*0.4;
    var P=[{g: drape(k.box(w, t, d, 0, t/2, 0), gx, gz)}];
    P.push({g: drape(k.box(lw, lt, d, -(w/2-lw/2), t-lt/2, 0), gx, gz), sub:'mat_paint_white'});
    P.push({g: drape(k.box(lw, lt, d,  (w/2-lw/2), t-lt/2, 0), gx, gz), sub:'mat_paint_white'});
    P.push({g: drape(k.box(w, lt, lw, 0, t-lt/2, -(d/2-lw/2)), gx, gz), sub:'mat_paint_white'});
    return P;
  };
  AR_EXT.geom.road_curved = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var r=Math.max(0.5,N('r',10)), a0=N('a0',0), a1=N('a1',90);
    var w=Math.max(0.2,N('w',6)), t=Math.max(0.01,N('t',0.08)), seg=Math.round(N('seg',24));
    if(Math.abs(a1-a0)<0.5) a1=a0+0.5;
    if(Math.abs(a1-a0)>=360) a1=a0+359.9;
    return [{g: arcSlab(k, r, a0, a1, w, t, seg)}];
  };

  AR_EXT.label.fence = 'Fence';
  AR_EXT.label.hedge = 'Hedge';
  AR_EXT.label.tree_conifer = 'Conifer';
  AR_EXT.label.tree_deciduous = 'Tree';
  AR_EXT.label.tree_palm = 'Palm';
  AR_EXT.label.shrub = 'Shrub';
  AR_EXT.label.flowerbed = 'Flower bed';
  AR_EXT.label.lamp_post = 'Lamp post';
  AR_EXT.label.bench = 'Bench';
  AR_EXT.label.bin = 'Litter bin';
  AR_EXT.label.kerb = 'Kerb';
  AR_EXT.label.sidewalk = 'Pavement';
  AR_EXT.label.parking_bay = 'Parking bay';
  AR_EXT.label.road_curved = 'Curved road';
})();
