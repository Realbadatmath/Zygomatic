// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* cliffs_rocks — rock, not building. Six kinds:

     cliff        a rugged rock face len long, h tall, running d back, with a
                  flat ledge on top (a grass strip when p.ledge > 0)
     escarpment   the same face, but the top is a tilted plateau sloping down
                  from y=h at the face to y=0 at the back, with a grass strip
                  p.ledge metres wide along the top edge
     boulder      a single noisy sphere sitting on the ground
     rock_field   `count` boulders hash-scattered over w x d in ONE record,
                  each one DRAPED on the ground plane (base at gx*lx + gz*lz)
                  and standing upright; 30 % of them are the lighter mat_stone.
                  p.size is the LARGEST boulder's DIAMETER, so a radius runs
                  size/2 * (0.4 + 0.6*hash) — 0.2 to 0.5 of size.
     scree        a rubble wedge leaning on the cliff behind it (high at -Z)
                  with twelve small boulders resting on it
     sea_stack    a tall rock column, rings of wandering radius, flat top

   Local frame: the record's x/z is the CENTRE in plan, the ground is y=0 and
   everything grows to +Y. Plan angles are the studio's: 0 = +X, 90 = -Z, so a
   point at angle theta is (r cos theta, -r sin theta) and g.rotateY(+theta)
   turns +X to -Z. The rock face of a cliff/escarpment looks toward -Z when the
   record is unrotated, which is why add_cliff puts the drop on the LEFT of the
   walking direction.

   THE NOISE IS A CONTRACT. hash/vnoise below are byte-for-byte the same
   arithmetic as value_noise() in arch_assistant_ext/cliffs_rocks.py and in
   arch_blender_ext/cliffs_rocks.py — copied verbatim from terrain. Change one
   copy and the same record is three different rocks. */
(function(){
  function frac(x){ return x - Math.floor(x); }
  function hash(ix, iy, seed){ return frac(Math.sin(ix*127.1 + iy*311.7 + seed*74.7) * 43758.5453); }
  function vnoise(u, v, seed){
    var ix=Math.floor(u), iy=Math.floor(v), fx=u-ix, fy=v-iy;
    var a=hash(ix,iy,seed), b=hash(ix+1,iy,seed), c=hash(ix,iy+1,seed), e=hash(ix+1,iy+1,seed);
    return a + (b-a)*fx + (c-a)*fy + (a-b-c+e)*fx*fy;
  }
  function mesh(k, pos, idx){
    var g=new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx); g.computeVertexNormals();
    return g;
  }

  /* ── the rock face shared by cliff and escarpment ──────────────────────
     A lattice of (res+1) x (res+1) points on the FRONT face (facing -Z): the
     nominal plane is z = -d/2 and each point is pushed rug either way by the
     noise. ledgeTop true  -> flat ledge at y=h back to z=+d/2 and a plain
     vertical back face (a cliff); false -> the top slopes straight down to
     y=0 at z=+d/2 (an escarpment). */
  function faceBody(len, h, d, rug, seed, res, ledgeTop){
    var pos=[], idx=[], i, j;
    for(j=0;j<=res;j++){
      for(i=0;i<=res;i++){
        pos.push(-len/2 + i/res*len, h*j/res, -d/2 - rug + 2*rug*vnoise(i/res*3, j/res*3, seed));
      }
    }
    var NF=(res+1)*(res+1), NB=NF;
    for(i=0;i<=res;i++) pos.push(-len/2 + i/res*len, 0, d/2);          /* back bottom edge */
    var NT=NB+res+1;
    if(ledgeTop) for(i=0;i<=res;i++) pos.push(-len/2 + i/res*len, h, d/2);   /* back top edge */
    function F(jj,ii){ return jj*(res+1)+ii; }
    function B(ii){ return NB+ii; }
    function T(ii){ return ledgeTop ? NT+ii : NB+ii; }
    function quad(a,b,c,e){ idx.push(a,b,c, a,c,e); }
    for(j=0;j<res;j++) for(i=0;i<res;i++) quad(F(j,i), F(j+1,i), F(j+1,i+1), F(j,i+1));   /* face, -Z */
    for(i=0;i<res;i++) quad(F(res,i), T(i), T(i+1), F(res,i+1));                          /* ledge / slope */
    for(i=0;i<res;i++) quad(F(0,i), F(0,i+1), B(i+1), B(i));                              /* bottom */
    if(ledgeTop) for(i=0;i<res;i++) quad(B(i), B(i+1), T(i+1), T(i));                     /* back */
    for(j=0;j<res;j++) idx.push(B(0), F(j+1,0), F(j,0));                                  /* -X side */
    for(j=0;j<res;j++) idx.push(B(res), F(j,res), F(j+1,res));                            /* +X side */
    if(ledgeTop){ idx.push(B(0), T(0), F(res,0)); idx.push(B(res), F(res,res), T(res)); }
    return {pos:pos, idx:idx};
  }

  /* ── one noisy sphere, translated so its lowest vertex is y = 0 ───────── */
  function boulderMesh(r, rug, seed, seg, rings){
    var pos=[], idx=[], i, j;
    function R(u,v){ return r*(1 + rug*(2*vnoise(u*3, v*3, seed) - 1)); }
    pos.push(0, R(0,0), 0);                                            /* north pole */
    for(j=1;j<rings;j++){
      var v=j/rings, phi=Math.PI*v;
      for(i=0;i<seg;i++){
        var u=i/seg, th=2*Math.PI*u, rad=R(u,v);
        pos.push(rad*Math.sin(phi)*Math.cos(th), rad*Math.cos(phi), -rad*Math.sin(phi)*Math.sin(th));
      }
    }
    var south=1+(rings-1)*seg;
    pos.push(0, -R(0,1), 0);                                           /* south pole */
    function ring(jj,ii){ return 1 + (jj-1)*seg + (ii%seg); }
    for(i=0;i<seg;i++) idx.push(0, ring(1,i), ring(1,i+1));
    for(j=1;j<rings-1;j++){
      for(i=0;i<seg;i++){
        var A=ring(j,i), Bv=ring(j,i+1), C=ring(j+1,i+1), D=ring(j+1,i);
        idx.push(A,D,C, A,C,Bv);
      }
    }
    for(i=0;i<seg;i++) idx.push(ring(rings-1,i), south, ring(rings-1,i+1));
    var miny=Infinity;
    for(i=1;i<pos.length;i+=3) if(pos[i]<miny) miny=pos[i];
    for(i=1;i<pos.length;i+=3) pos[i]-=miny;
    return {pos:pos, idx:idx};
  }

  function append(pos, idx, m, dx, dy, dz){
    var base=pos.length/3, i;
    for(i=0;i<m.pos.length;i+=3) pos.push(m.pos[i]+dx, m.pos[i+1]+dy, m.pos[i+2]+dz);
    for(i=0;i<m.idx.length;i++) idx.push(m.idx[i]+base);
  }

  AR_EXT.geom.cliff = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var len=Math.max(0.5,N('len',40)), h=Math.max(0.1,N('h',15)), d=Math.max(0.5,N('d',12));
    var rug=Math.max(0,N('rug',0.35)), seed=N('seed',1), ledge=N('ledge',1);
    var res=Math.max(2, Math.min(64, Math.round(N('res',24))));
    var m=faceBody(len,h,d,rug,seed,res,true);
    var parts=[{g: mesh(k, m.pos, m.idx)}];
    if(ledge>0){
      var lt=Math.min(ledge, h*0.9), rr=Math.min(rug, d*0.25);
      parts.push({g: k.box(len, lt, d-rr, 0, h-lt/2, rr/2), sub:'mat_grass'});
    }
    return parts;
  };

  /* the grass strip on an escarpment top: a thin slab lying ON the tilted top,
     from the front edge (y=h at z=-d/2) back `lg` metres. Its highest point is
     exactly h, so it never grows the record's bounding box. */
  function topStrip(k, len, h, d, lg){
    var t=Math.min(0.15, h*0.1), yf=h, yb=h*(1-lg/d), zf=-d/2, zb=-d/2+lg, X=len/2;
    var sp=[-X,yf,zf,  X,yf,zf,  X,yb,zb,  -X,yb,zb,
            -X,yf-t,zf, X,yf-t,zf, X,yb-t,zb, -X,yb-t,zb];
    var si=[];
    function q(a,b,c,e){ si.push(a,b,c, a,c,e); }
    q(0,3,2,1); q(4,5,6,7); q(0,1,5,4); q(3,7,6,2); q(0,4,7,3); q(1,2,6,5);
    return mesh(k, sp, si);
  }

  AR_EXT.geom.escarpment = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var len=Math.max(0.5,N('len',60)), h=Math.max(0.1,N('h',20)), d=Math.max(0.5,N('d',40));
    var rug=Math.max(0,N('rug',0.3)), seed=N('seed',1);
    var res=Math.max(2, Math.min(64, Math.round(N('res',24))));
    var m=faceBody(len,h,d,rug,seed,res,false);
    var parts=[{g: mesh(k, m.pos, m.idx)}];
    var lg=Math.max(0, Math.min(N('ledge',1), d*0.5));
    if(lg>0.01) parts.push({g: topStrip(k, len, h, d, lg), sub:'mat_grass'});
    return parts;
  };

  AR_EXT.geom.boulder = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var r=Math.max(0.05,N('r',1.5)), rug=Math.max(0,Math.min(0.9,N('rug',0.35))), seed=N('seed',1);
    var seg=Math.max(6, Math.min(48, Math.round(N('seg',12))));
    var m=boulderMesh(r, rug, seed, seg, Math.max(2, Math.round(seg/2)));
    return [{g: mesh(k, m.pos, m.idx)}];
  };

  AR_EXT.geom.rock_field = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var w=Math.max(1,N('w',30)), d=Math.max(1,N('d',30));
    var cnt=Math.max(1, Math.min(400, Math.round(N('count',20))));
    var size=Math.max(0.05,N('size',1.2)), seed=N('seed',1), rug=Math.max(0,Math.min(0.9,N('rug',0.35)));
    var gx=N('gx',0), gz=N('gz',0);
    var pos=[], idx=[], pos2=[], idx2=[], n;
    for(n=0;n<cnt;n++){
      var rr=size/2*(0.4+0.6*hash(n,3,seed));            /* size = the LARGEST diameter */
      var px=-w/2 + hash(n,1,seed)*w, pz=-d/2 + hash(n,2,seed)*d;
      var m=boulderMesh(rr, rug, seed+n+1, 8, 4);
      /* the boulder's BASE follows the ground plane; the rock stays upright */
      if(hash(n,4,seed) < 0.3) append(pos2, idx2, m, px, gx*px + gz*pz, pz);
      else                     append(pos,  idx,  m, px, gx*px + gz*pz, pz);
    }
    var parts=[];
    if(idx.length)  parts.push({g: mesh(k, pos, idx)});
    if(idx2.length) parts.push({g: mesh(k, pos2, idx2), sub:'mat_stone'});
    return parts;
  };

  AR_EXT.geom.scree = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var len=Math.max(0.5,N('len',30)), w=Math.max(0.5,N('w',12)), h=Math.max(0.1,N('h',6));
    /* the wedge: y=0 at z=+w/2, y=h at z=-w/2 — it leans on the cliff behind */
    var g=k.prism([[-w/2,0],[w/2,0],[w/2,h]], len);
    g.rotateY(Math.PI/2); g.computeVertexNormals();
    var pos=[], idx=[], n, i;
    for(n=0;n<12;n++){
      var rb=0.15+0.25*hash(n,3,1);
      var m=boulderMesh(rb, 0.3, 5+n, 8, 4);
      var hx=0, hy=0, hz=0;
      for(i=0;i<m.pos.length;i+=3){
        hx=Math.max(hx, Math.abs(m.pos[i]));
        hy=Math.max(hy, m.pos[i+1]);
        hz=Math.max(hz, Math.abs(m.pos[i+2]));
      }
      var xlo=-len/2+hx, xhi=len/2-hx, zlo=-w/2+hz, zhi=w/2-hz;
      var zmin=Math.max(zlo, w/2 - w*(1 - hy/h));                 /* keep the top under y=h */
      if(xhi<=xlo || zhi<=zmin) continue;
      var pz=zmin + hash(n,2,1)*(zhi-zmin);
      append(pos, idx, m, xlo + hash(n,1,1)*(xhi-xlo), h*(w/2-pz)/w, pz);
    }
    var parts=[{g:g}];
    if(idx.length) parts.push({g: mesh(k, pos, idx), sub:'mat_rock'});
    return parts;
  };

  AR_EXT.geom.sea_stack = function(p, k){
    var N=function(key,dv){ return k.num(p[key], dv); };
    var r=Math.max(0.2,N('r',6)), h=Math.max(0.2,N('h',25));
    var rug=Math.max(0,Math.min(0.9,N('rug',0.3))), seed=N('seed',1);
    var seg=Math.max(6, Math.min(64, Math.round(N('seg',24))));
    var rings=Math.max(2, Math.min(48, Math.round(N('rings',10))));
    var pos=[], idx=[], i, j;
    for(j=0;j<=rings;j++){
      var v=j/rings;
      for(i=0;i<seg;i++){
        var u=i/seg, th=2*Math.PI*u;
        var rad=r*(1 + rug*(2*vnoise(u*3, v*3, seed) - 1));
        pos.push(rad*Math.cos(th), h*v, -rad*Math.sin(th));
      }
    }
    var ctop=(rings+1)*seg, cbot=ctop+1;
    pos.push(0,h,0); pos.push(0,0,0);
    function R(jj,ii){ return jj*seg + (ii%seg); }
    for(j=0;j<rings;j++) for(i=0;i<seg;i++){
      idx.push(R(j+1,i), R(j,i), R(j,i+1), R(j+1,i), R(j,i+1), R(j+1,i+1));
    }
    for(i=0;i<seg;i++) idx.push(ctop, R(rings,i), R(rings,i+1));
    for(i=0;i<seg;i++) idx.push(cbot, R(0,i+1), R(0,i));
    return [{g: mesh(k, pos, idx)}];
  };

  AR_EXT.label.cliff = 'Cliff';
  AR_EXT.label.escarpment = 'Escarpment';
  AR_EXT.label.boulder = 'Boulder';
  AR_EXT.label.rock_field = 'Rock field';
  AR_EXT.label.scree = 'Scree slope';
  AR_EXT.label.sea_stack = 'Sea stack';
})();
