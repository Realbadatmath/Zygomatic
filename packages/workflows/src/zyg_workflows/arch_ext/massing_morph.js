// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* massing_morph — study-model volumes (mass_taper, mass_twist, mass_setback,
   mass_loft, mass_ellipse, mass_arc, mass_chamfer, mass_round, mass_shear).

   ONE record = ONE whole volume, not a stack of storeys. Local frame: the
   record's x/z is the centre of the footprint, the bottom sits at y=0, the
   volume is p.h tall.

   EVERYTHING here is expressed as RINGS. A ring is one horizontal level: a
   closed loop of [x, y, z] points, every ring in a volume holding the same
   number of points. `ringsG` sews quads between consecutive rings and caps the
   first and the last one — so a new mass kind is a function that returns rings,
   nothing more. The Blender twin (arch_blender_ext/massing_morph.py) builds the
   same rings vertex for vertex.

   Plan convention (the studio's): angle 0 = +X, 90 = -Z (north = up in the top
   view), so a point at theta is (r cos t, -r sin t). Outlines are written in
   that order, which makes the top cap face up and the sides face outwards. */
(function(){

  /* rings -> BufferGeometry.  cap: 'fan' for a convex outline (default),
     'band' for a loop whose second half is the first half's inner twin
     (index i pairs with L-1-i) — that is the arc slab. */
  function ringsG(k, rings, cap){
    var THREE=k.THREE, R=rings.length, L=rings[0].length, pos=[], idx=[], i, j, n;
    for(i=0;i<R;i++){ var rg=rings[i]; for(j=0;j<L;j++){ pos.push(rg[j][0], rg[j][1], rg[j][2]); } }
    for(i=0;i<R-1;i++){                                   // the sides
      var a=i*L, b=(i+1)*L;
      for(j=0;j<L;j++){ n=(j+1)%L; idx.push(a+j, a+n, b+n,  a+j, b+n, b+j); }
    }
    var t=(R-1)*L;
    if(cap==='band'){
      var half=L/2;
      for(j=0;j<half-1;j++){
        var p0=j, p1=j+1, q1=L-2-j, q0=L-1-j;
        idx.push(t+p0, t+p1, t+q1,  t+p0, t+q1, t+q0);    // top of the band
        idx.push(p0, q0, q1,  p0, q1, p1);                // bottom (reversed)
      }
    } else {
      for(j=1;j<L-1;j++){ idx.push(t, t+j, t+j+1); idx.push(0, j+1, j); }
    }
    var g=new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos,3));
    g.setIndex(idx); g.computeVertexNormals(); return g;
  }

  function lift(outline, y){                               // [x,z] pairs -> a ring at height y
    var out=[], i;
    for(i=0;i<outline.length;i++) out.push([outline[i][0], y, outline[i][1]]);
    return out;
  }
  function rect(w, d){                                     // corners in plan order
    var hw=Math.max(w,0.05)/2, hd=Math.max(d,0.05)/2;
    return [[hw,-hd],[-hw,-hd],[-hw,hd],[hw,hd]];
  }
  function ellipseOut(rx, rz, seg){
    var out=[], i, n=Math.max(6, Math.round(seg));
    for(i=0;i<n;i++){ var t=2*Math.PI*i/n; out.push([Math.max(rx,0.05)*Math.cos(t), -Math.max(rz,0.05)*Math.sin(t)]); }
    return out;
  }
  function rectAt(w, d, t){                                /* the rectangle sampled along the ray at angle t */
    var ct=Math.cos(t), st=Math.sin(t);
    var sx=Math.abs(ct)<1e-9 ? 1e9 : (Math.max(w,0.05)/2)/Math.abs(ct);
    var sz=Math.abs(st)<1e-9 ? 1e9 : (Math.max(d,0.05)/2)/Math.abs(st);
    var s=Math.min(sx, sz);
    return [s*ct, -s*st];
  }
  function spin(outline, deg){                             /* rotate a plan outline about the vertical axis */
    var a=deg*Math.PI/180, c=Math.cos(a), s=Math.sin(a), out=[], i;
    for(i=0;i<outline.length;i++){
      var x=outline[i][0], z=outline[i][1];
      out.push([x*c + z*s, z*c - x*s]);
    }
    return out;
  }

  AR_EXT.geom.mass_taper = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var h=N('h',27);
    return [{g: ringsG(k, [lift(rect(N('w',10), N('d',10)), 0),
                           lift(rect(N('w_top',6), N('d_top',6)), h)])}];
  };

  AR_EXT.geom.mass_twist = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=N('w',10), d=N('d',10), h=N('h',27), tw=N('twist',45);
    var seg=Math.max(1, Math.min(200, Math.round(N('seg',10))));
    var base=rect(w, d), rings=[], i;
    for(i=0;i<=seg;i++) rings.push(lift(spin(base, tw*i/seg), h*i/seg));
    return [{g: ringsG(k, rings)}];
  };

  AR_EXT.geom.mass_setback = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=N('w',12), d=N('d',12), h=N('h',27);
    var steps=Math.max(1, Math.min(40, Math.round(N('steps',3)))), si=N('step_in',2);
    var rings=[], i;
    for(i=0;i<steps;i++){
      var ww=Math.max(0.5, w-2*si*i), dd=Math.max(0.5, d-2*si*i);
      var o=rect(ww, dd);
      rings.push(lift(o, h*i/steps));
      rings.push(lift(o, h*(i+1)/steps));
    }
    return [{g: ringsG(k, rings)}];
  };

  AR_EXT.geom.mass_loft = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=N('w',10), d=N('d',10), h=N('h',27);
    var seg=Math.max(6, Math.min(240, Math.round(N('seg',24))));
    var LEV=8, rings=[], i, j;
    for(i=0;i<LEV;i++){
      var f=i/(LEV-1), ring=[];
      for(j=0;j<seg;j++){
        var t=2*Math.PI*j/seg;
        var rp=rectAt(w, d, t);
        var ep=[Math.max(w,0.05)/2*Math.cos(t), -Math.max(d,0.05)/2*Math.sin(t)];
        ring.push([rp[0]+(ep[0]-rp[0])*f, rp[1]+(ep[1]-rp[1])*f]);
      }
      rings.push(lift(ring, h*f));
    }
    return [{g: ringsG(k, rings)}];
  };

  AR_EXT.geom.mass_ellipse = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var o=ellipseOut(N('rx',6), N('rz',4), N('seg',48)), h=N('h',27);
    return [{g: ringsG(k, [lift(o,0), lift(o,h)])}];
  };

  AR_EXT.geom.mass_arc = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var r=N('r',20), a0=N('a0',0), a1=N('a1',90), w=N('w',12), h=N('h',27);
    var seg=Math.max(4, Math.min(360, Math.round(N('seg',32))));
    if(Math.abs(a1-a0)<0.5) a1=a0+0.5;
    if(Math.abs(a1-a0)>355) a1=a0+(a1>a0?355:-355);
    var ri=Math.max(0.1, r-Math.max(w,0.1)/2), ro=r+Math.max(w,0.1)/2;
    var outer=[], inner=[], i;
    for(i=0;i<=seg;i++){
      var t=(a0+(a1-a0)*i/seg)*Math.PI/180, c=Math.cos(t), s=Math.sin(t);
      outer.push([ro*c, -ro*s]); inner.push([ri*c, -ri*s]);
    }
    var o=outer.concat(inner.reverse());
    return [{g: ringsG(k, [lift(o,0), lift(o,h)], 'band')}];
  };

  AR_EXT.geom.mass_chamfer = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=Math.max(N('w',10),0.05), d=Math.max(N('d',10),0.05), h=N('h',27);
    var c=Math.max(0.01, Math.min(N('c',1.0), Math.min(w,d)/2-0.01));
    var hw=w/2, hd=d/2;
    var o=[[hw,-hd+c],[hw-c,-hd],[-hw+c,-hd],[-hw,-hd+c],
           [-hw,hd-c],[-hw+c,hd],[hw-c,hd],[hw,hd-c]];
    return [{g: ringsG(k, [lift(o,0), lift(o,h)])}];
  };

  AR_EXT.geom.mass_round = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=Math.max(N('w',10),0.05), d=Math.max(N('d',10),0.05), h=N('h',27);
    var r=Math.max(0.01, Math.min(N('r',2), Math.min(w,d)/2-0.01));
    var hw=w/2-r, hd=d/2-r, S=6, o=[], q, i;
    var cen=[[hw,-hd],[-hw,-hd],[-hw,hd],[hw,hd]];
    for(q=0;q<4;q++){
      for(i=0;i<=S;i++){
        var t=(q*90 + 90*i/S)*Math.PI/180;
        o.push([cen[q][0]+r*Math.cos(t), cen[q][1]-r*Math.sin(t)]);
      }
    }
    return [{g: ringsG(k, [lift(o,0), lift(o,h)])}];
  };

  AR_EXT.geom.mass_shear = function(p, k){
    var N=function(a,b){ return k.num(p[a], b); };
    var w=N('w',10), d=N('d',10), h=N('h',27), sx=N('shear_x',3), sz=N('shear_z',0);
    var base=rect(w, d), top=[], i;
    for(i=0;i<base.length;i++) top.push([base[i][0]+sx, base[i][1]+sz]);
    return [{g: ringsG(k, [lift(base,0), lift(top,h)])}];
  };

  AR_EXT.label.mass_taper   = 'Tapered mass';
  AR_EXT.label.mass_twist   = 'Twisted mass';
  AR_EXT.label.mass_setback = 'Setback mass';
  AR_EXT.label.mass_loft    = 'Lofted mass';
  AR_EXT.label.mass_ellipse = 'Elliptical mass';
  AR_EXT.label.mass_arc     = 'Arc mass';
  AR_EXT.label.mass_chamfer = 'Chamfered mass';
  AR_EXT.label.mass_round   = 'Rounded mass';
  AR_EXT.label.mass_shear   = 'Sheared mass';
})();
