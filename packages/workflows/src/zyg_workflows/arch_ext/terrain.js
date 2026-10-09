// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* terrain — ground, not building. Six kinds:

     terrain         a value-noise heightfield over w x d, (res+1)^2 vertices
     hill            a smooth cosine mound, 2r across and h tall
     slope           a solid wedge rising to h across d, turned by p.dir
     plateau         a flat-topped mound; w x d is the BASE, the top is inset
                     batter*h on every side
     retaining_wall  len long, h tall, t thick at the top, battered at the back
     berm            a ridge len long with a triangular w x h section

   Local frame: the record's x/z is the CENTRE in plan, the ground sits at
   y=0 and everything grows to +Y. Plan angles are the studio's: 0 = +X,
   90 = -Z (north = up in the top view), so g.rotateY(+theta) turns +X to -Z.

   THE NOISE IS A CONTRACT. hash/vnoise below are byte-for-byte the same
   arithmetic as value_noise() in arch_assistant_ext/terrain.py and in
   arch_blender_ext/terrain.py. A terrain record therefore has the same
   height in the tab, in Blender and in the assistant's own arithmetic —
   the test proves it by evaluating the noise in Python and comparing the
   number with this geometry's bounding box. Change one copy and you have
   three different landscapes. */
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

  AR_EXT.geom.terrain = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',20), d=N('d',20), amp=N('amp',2), seed=N('seed',1), base=N('base',0);
    var res=Math.max(2, Math.min(96, Math.round(N('res',24))));
    var pos=[], idx=[], i, j;
    for(j=0;j<=res;j++){
      for(i=0;i<=res;i++){
        pos.push(-w/2 + i/res*w, base + amp*vnoise(i/res*4, j/res*4, seed), -d/2 + j/res*d);
      }
    }
    for(j=0;j<res;j++){
      for(i=0;i<res;i++){
        var a=j*(res+1)+i, b=a+1, c=a+res+1, e=c+1;
        idx.push(a,c,b, b,c,e);                 /* both triangles face +Y */
      }
    }
    return [{g: mesh(k, pos, idx), sub:'mat_grass'}];
  };

  AR_EXT.geom.hill = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=Math.max(0.2, N('r',8)), h=N('h',3), seg=32, rings=12;
    var pos=[0,h,0], idx=[], i, kk;
    for(kk=1;kk<=rings;kk++){
      var rad=r*kk/rings, y=h*0.5*(1+Math.cos(Math.PI*rad/r));
      for(i=0;i<seg;i++){ var an=2*Math.PI*i/seg; pos.push(Math.cos(an)*rad, y, Math.sin(an)*rad); }
    }
    var ctr=1+rings*seg;
    pos.push(0,0,0);
    function ring(kk,i){ return 1 + (kk-1)*seg + (i%seg); }
    for(i=0;i<seg;i++) idx.push(0, ring(1,i+1), ring(1,i));                     /* apex fan, up */
    for(kk=1;kk<rings;kk++){
      for(i=0;i<seg;i++){
        var A0=ring(kk,i), A1=ring(kk,i+1), B0=ring(kk+1,i), B1=ring(kk+1,i+1);
        idx.push(A1,A0,B0, A1,B0,B1);
      }
    }
    for(i=0;i<seg;i++) idx.push(ctr, ring(rings,i), ring(rings,i+1));           /* flat base, down */
    return [{g: mesh(k, pos, idx)}];
  };

  AR_EXT.geom.slope = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',10), d=N('d',10), h=N('h',2), dir=N('dir',0);
    /* the wedge is drawn in the profile plane and turned a quarter so the run
       lies along Z: low edge at z=-d/2, high edge (y=h) at z=+d/2. */
    var g=k.prism([[-d/2,0],[d/2,0],[d/2,h]], w);
    g.rotateY(-Math.PI/2 + dir*Math.PI/180);
    g.computeVertexNormals();
    return [{g:g}];
  };

  AR_EXT.geom.plateau = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',20), d=N('d',20), h=N('h',1.5), batter=N('batter',0.5);
    var b=Math.max(0, Math.min(batter*h, w/2-0.05, d/2-0.05));
    var tw=w/2-b, td=d/2-b;
    var pos=[-w/2,0,-d/2,  w/2,0,-d/2,  w/2,0,d/2,  -w/2,0,d/2,
             -tw,h,-td,    tw,h,-td,    tw,h,td,    -tw,h,td];
    var idx=[];
    [[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7],[4,5,6,7],[0,3,2,1]].forEach(function(f){
      idx.push(f[0],f[1],f[2], f[0],f[2],f[3]);
    });
    return [{g: mesh(k, pos, idx)}];
  };

  AR_EXT.geom.retaining_wall = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var len=N('len',10), h=N('h',1.5), t=N('t',0.3), batter=N('batter',0.1);
    var T=t+batter*h;                       /* thickness at the base */
    var g=k.prism([[-T/2,0],[T/2,0],[-T/2+t,h],[-T/2,h]], len);
    g.rotateY(Math.PI/2);                   /* run along X, section across Z */
    g.computeVertexNormals();
    return [{g:g}];
  };

  AR_EXT.geom.berm = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var len=N('len',20), w=N('w',4), h=N('h',1.2);
    var g=k.prism([[-w/2,0],[w/2,0],[0,h]], len);
    g.rotateY(Math.PI/2);
    g.computeVertexNormals();
    return [{g:g}];
  };

  AR_EXT.label.terrain = 'Terrain';
  AR_EXT.label.hill = 'Hill';
  AR_EXT.label.slope = 'Slope';
  AR_EXT.label.plateau = 'Plateau';
  AR_EXT.label.retaining_wall = 'Retaining wall';
  AR_EXT.label.berm = 'Berm';
})();
