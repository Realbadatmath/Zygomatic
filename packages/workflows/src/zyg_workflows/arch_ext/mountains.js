// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* mountains — real mountains, not rolling ground. Six kinds:

     mountain        ONE peak: a radial cosine falloff over radius r, roughened
                     by (1 - rug*noise) and NORMALISED so the highest vertex is
                     exactly h. The foot is flat at y=0 (the falloff is clamped
                     to 0 at the rim), so the box is 2r x h x 2r.
     mountain_range  a lattice len x w whose height is the max of `peaks`
                     mountain falloffs spaced along X, normalised to h.
     ridge           a sharp crest along X, triangular in section, the crest
                     wandering by rug*noise along the length, normalised to h.
     volcano         a truncated cone (r at the foot, crater_r at the rim at
                     y=h) with a bowl crater_d deep inside the rim.
     mesa            a flat-topped table mountain: r at the foot, top_r at the
                     rim, the cliff profile jittered around the circumference.
                     The table top is a SECOND part carrying sub:'mat_grass';
                     the cliffs keep the record's rock.
     valley          a trough lattice w x d with a flat floor floor_w wide
                     running along Z, the sides rising to h at x = +-w/2 —
                     the piece a river runs BETWEEN. The sides are the record's
                     material (grass by default) and the floor is a SECOND part
                     carrying sub:'mat_soil', laid 20 mm above y=0 so it does
                     not z-fight; the bounding box is unchanged by it.

   The terrain family owns rolling ground and the single smooth hill; this
   family owns everything that is a mountain. Nothing here touches it.

   Local frame: the record's x/z is the CENTRE in plan, the ground is y=0,
   everything grows to +Y. Plan angles are the studio's: 0 = +X, 90 = -Z.

   THE NOISE IS A CONTRACT. hash/vnoise below are byte-for-byte the arithmetic
   of value_noise() in arch_assistant_ext/terrain.py, copied again into
   arch_assistant_ext/mountains.py and arch_blender_ext/mountains.py. Change
   one copy and the same record is three different mountains. The test proves
   the copies agree by computing, in Python, the snow line at which the snow
   cap disappears and asking this geometry how many parts it built either
   side of it.

   Faces whose centroid stands above snow*h are a SECOND part carrying
   sub:'mat_snow'; the body keeps the record's own material (mat_rock by
   default). A snow line at or above 1.0 leaves ONE part. */
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
  /* normalise a (res+1)^2 lattice of raw heights so its maximum is exactly h */
  function normalise(H, res, h){
    var mx=0, i, j;
    for(j=0;j<=res;j++) for(i=0;i<=res;i++) if(H[j][i]>mx) mx=H[j][i];
    var s = mx>1e-9 ? h/mx : 0;
    for(j=0;j<=res;j++) for(i=0;i<=res;i++) H[j][i]*=s;
    return s;
  }
  /* split the lattice into a rock part and a snow part by triangle centroid */
  function splitLattice(k, pos, H, res, line){
    var body=[], snow=[], i, j;
    for(j=0;j<res;j++){
      for(i=0;i<res;i++){
        var a=j*(res+1)+i, b=a+1, c=a+res+1, e=c+1;
        var c1=(H[j][i]+H[j+1][i]+H[j][i+1])/3;
        var c2=(H[j][i+1]+H[j+1][i]+H[j+1][i+1])/3;
        if(c1>line){ snow.push(a,c,b); } else { body.push(a,c,b); }
        if(c2>line){ snow.push(b,c,e); } else { body.push(b,c,e); }
      }
    }
    var P=[];
    if(body.length) P.push({g: mesh(k, pos, body)});
    if(snow.length) P.push({g: mesh(k, pos, snow), sub:'mat_snow'});
    return P;
  }

  /* ── one peak ─────────────────────────────────────────────────────────── */
  AR_EXT.geom.mountain = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=Math.max(0.5, N('r',60)), h=Math.max(0.01, N('h',40)), rug=N('rug',0.45);
    var seed=N('seed',1), snow=N('snow',0.7);
    var res=Math.max(4, Math.min(96, Math.round(N('res',48))));
    var H=[], pos=[], i, j;
    for(j=0;j<=res;j++){
      H.push([]);
      for(i=0;i<=res;i++){
        var x=-r + i/res*2*r, z=-r + j/res*2*r;
        var dist=Math.sqrt(x*x + z*z);
        var f = dist>=r ? 0 : 0.5*(1+Math.cos(Math.PI*dist/r));
        var v = f*(1 - rug*vnoise(i/res*6, j/res*6, seed));
        H[j].push(v>0 ? v : 0);
      }
    }
    normalise(H, res, h);
    for(j=0;j<=res;j++) for(i=0;i<=res;i++) pos.push(-r + i/res*2*r, H[j][i], -r + j/res*2*r);
    return splitLattice(k, pos, H, res, snow*h);
  };

  /* ── a chain of peaks ─────────────────────────────────────────────────── */
  AR_EXT.geom.mountain_range = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var len=Math.max(1, N('len',200)), w=Math.max(1, N('w',80)), h=Math.max(0.01, N('h',50));
    var peaks=Math.max(1, Math.min(40, Math.round(N('peaks',4))));
    var rug=N('rug',0.45), seed=N('seed',1), snow=N('snow',0.75);
    var res=Math.max(4, Math.min(96, Math.round(N('res',64))));
    var pk=[], m;
    for(m=0;m<peaks;m++){
      pk.push([-len/2 + (m+0.5)*len/peaks, 0.65*len/peaks, 1 + 0.5*(hash(m,0,seed)-0.5)]);
    }
    var H=[], pos=[], i, j;
    for(j=0;j<=res;j++){
      H.push([]);
      for(i=0;i<=res;i++){
        var x=-len/2 + i/res*len, z=-w/2 + j/res*w, base=0;
        for(m=0;m<peaks;m++){
          var dx=x-pk[m][0], pr=pk[m][1], dist=Math.sqrt(dx*dx + z*z);
          if(dist<pr){
            var f=pk[m][2]*0.5*(1+Math.cos(Math.PI*dist/pr));
            if(f>base) base=f;
          }
        }
        var v=base*(1 - rug*vnoise(i/res*6, j/res*6, seed));
        H[j].push(v>0 ? v : 0);
      }
    }
    normalise(H, res, h);
    for(j=0;j<=res;j++) for(i=0;i<=res;i++) pos.push(-len/2 + i/res*len, H[j][i], -w/2 + j/res*w);
    return splitLattice(k, pos, H, res, snow*h);
  };

  /* ── a sharp crest ────────────────────────────────────────────────────── */
  AR_EXT.geom.ridge = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var len=Math.max(0.5, N('len',80)), w=Math.max(0.2, N('w',20)), h=Math.max(0.01, N('h',15));
    var rug=N('rug',0.3), seed=N('seed',1);
    var res=Math.max(2, Math.min(96, Math.round(N('res',32))));
    var raw=[], mx=0, i;
    for(i=0;i<=res;i++){
      var v=1 - rug*vnoise(i/res*6, 0.5, seed);
      if(v<0) v=0;
      raw.push(v);
      if(v>mx) mx=v;
    }
    var s = mx>1e-9 ? h/mx : 0;
    var pos=[], idx=[];
    for(i=0;i<=res;i++){
      var x=-len/2 + i/res*len;
      pos.push(x, 0, -w/2);        /* 3i     left foot  */
      pos.push(x, raw[i]*s, 0);    /* 3i+1   crest      */
      pos.push(x, 0, w/2);         /* 3i+2   right foot */
    }
    function L(n){ return 3*n; }
    function C(n){ return 3*n+1; }
    function R(n){ return 3*n+2; }
    for(i=0;i<res;i++){
      idx.push(L(i), C(i), C(i+1),  L(i), C(i+1), L(i+1));      /* -Z flank */
      idx.push(R(i), R(i+1), C(i+1),  R(i), C(i+1), C(i));      /* +Z flank */
      idx.push(L(i), L(i+1), R(i+1),  L(i), R(i+1), R(i));      /* underside */
    }
    idx.push(L(0), C(0), R(0));
    idx.push(R(res), C(res), L(res));
    return [{g: mesh(k, pos, idx)}];
  };

  /* ── volcano ──────────────────────────────────────────────────────────── */
  AR_EXT.geom.volcano = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=Math.max(0.5, N('r',50)), h=Math.max(0.05, N('h',35));
    var cr=Math.max(0.05, Math.min(N('crater_r',10), 0.9*r));
    var cd=Math.max(0.05, Math.min(N('crater_d',8), 0.9*h));
    var seg=Math.max(8, Math.min(128, Math.round(N('seg',48))));
    var rings=Math.max(2, Math.min(48, Math.round(N('rings',16))));
    var crings=Math.max(3, Math.round(rings/2));
    var pos=[], idx=[], i, kk;
    for(kk=0;kk<=rings;kk++){
      var t=kk/rings, rad=r + (cr-r)*t, y=h*t;
      for(i=0;i<seg;i++){ var an=2*Math.PI*i/seg; pos.push(Math.cos(an)*rad, y, Math.sin(an)*rad); }
    }
    var nOut=(rings+1)*seg;
    for(kk=1;kk<crings;kk++){
      var crad=cr*(1 - kk/crings), cy=h - cd*0.5*(1+Math.cos(Math.PI*crad/cr));
      for(i=0;i<seg;i++){ var a2=2*Math.PI*i/seg; pos.push(Math.cos(a2)*crad, cy, Math.sin(a2)*crad); }
    }
    var iBot=nOut + (crings-1)*seg;
    pos.push(0, h-cd, 0);
    var iBase=iBot+1;
    pos.push(0, 0, 0);
    function O(kk,i){ return kk*seg + (i%seg); }
    function K(m,i){ return m===0 ? O(rings,i) : (nOut + (m-1)*seg + (i%seg)); }
    for(kk=0;kk<rings;kk++){
      for(i=0;i<seg;i++){
        var j=(i+1)%seg;
        idx.push(O(kk,i), O(kk+1,i), O(kk+1,j),  O(kk,i), O(kk+1,j), O(kk,j));
      }
    }
    for(kk=0;kk<crings-1;kk++){
      for(i=0;i<seg;i++){
        var j2=(i+1)%seg;
        idx.push(K(kk,i), K(kk+1,i), K(kk+1,j2),  K(kk,i), K(kk+1,j2), K(kk,j2));
      }
    }
    for(i=0;i<seg;i++){ var j3=(i+1)%seg; idx.push(K(crings-1,i), iBot, K(crings-1,j3)); }
    for(i=0;i<seg;i++){ var j4=(i+1)%seg; idx.push(iBase, O(0,i), O(0,j4)); }
    return [{g: mesh(k, pos, idx)}];
  };

  /* ── mesa ─────────────────────────────────────────────────────────────── */
  AR_EXT.geom.mesa = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=Math.max(0.5, N('r',40)), h=Math.max(0.05, N('h',25));
    var tr=Math.max(0.2, N('top_r',30)), rug=N('rug',0.25), seed=N('seed',1);
    var seg=Math.max(8, Math.min(128, Math.round(N('seg',48))));
    var rings=8, pos=[], idx=[], i, kk;
    var top=[], expo=[];
    for(i=0;i<seg;i++){
      top.push(tr*(1 - rug*vnoise(i/seg*6, 0.5, seed)));
      expo.push(1 + 0.6*vnoise(i/seg*6, 3.5, seed));
    }
    for(kk=0;kk<=rings;kk++){
      var t=kk/rings, y=h*t;
      for(i=0;i<seg;i++){
        var an=2*Math.PI*i/seg;
        var rad=r + (top[i]-r)*Math.pow(t, expo[i]);
        pos.push(Math.cos(an)*rad, y, Math.sin(an)*rad);
      }
    }
    var iTop=(rings+1)*seg;
    pos.push(0, h, 0);
    var iBase=iTop+1;
    pos.push(0, 0, 0);
    function O(kk,i){ return kk*seg + (i%seg); }
    for(kk=0;kk<rings;kk++){
      for(i=0;i<seg;i++){
        var j=(i+1)%seg;
        idx.push(O(kk,i), O(kk+1,i), O(kk+1,j),  O(kk,i), O(kk+1,j), O(kk,j));
      }
    }
    for(i=0;i<seg;i++){ var j3=(i+1)%seg; idx.push(iBase, O(0,i), O(0,j3)); }
    /* the table top is GRASS, the cliffs below it are the record's rock */
    var cap=[];
    for(i=0;i<seg;i++){ var j2=(i+1)%seg; cap.push(iTop, O(rings,j2), O(rings,i)); }
    return [{g: mesh(k, pos, idx)}, {g: mesh(k, pos, cap), sub:'mat_grass'}];
  };

  /* ── valley ───────────────────────────────────────────────────────────── */
  AR_EXT.geom.valley = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(1, N('w',120)), d=Math.max(1, N('d',80)), h=Math.max(0.01, N('h',30));
    var fw=Math.max(0, Math.min(N('floor_w',20), w-0.2));
    var prof=Math.round(N('profile',0));
    var res=Math.max(4, Math.min(96, Math.round(N('res',32))));
    var pos=[], idx=[], i, j;
    var run=Math.max(1e-6, w/2 - fw/2);
    var col=[];
    for(i=0;i<=res;i++){
      var x=-w/2 + i/res*w, t=(Math.abs(x) - fw/2)/run;
      if(t<0) t=0; if(t>1) t=1;
      col.push(prof===1 ? h*0.5*(1-Math.cos(Math.PI*t)) : h*t);
    }
    for(j=0;j<=res;j++){
      for(i=0;i<=res;i++) pos.push(-w/2 + i/res*w, col[i], -d/2 + j/res*d);
    }
    for(j=0;j<res;j++){
      for(i=0;i<res;i++){
        var a=j*(res+1)+i, b=a+1, c=a+res+1, e=c+1;
        idx.push(a,c,b, b,c,e);
      }
    }
    var P=[{g: mesh(k, pos, idx)}];
    /* the sides are GRASS (the record's own material); the floor the river runs
       on is a SOIL strip floor_w wide, laid 20 mm over the flat floor so it does
       not z-fight. It is inside the trough, so the bounding box is unchanged. */
    if(fw > 0.05){
      var fy=0.02, hw=fw/2, hd=d/2;
      var sp=[-hw,fy,-hd,  hw,fy,-hd,  hw,fy,hd,  -hw,fy,hd];
      P.push({g: mesh(k, sp, [0,3,2, 0,2,1]), sub:'mat_soil'});
    }
    return P;
  };

  AR_EXT.label.mountain = 'Mountain';
  AR_EXT.label.mountain_range = 'Mountain range';
  AR_EXT.label.ridge = 'Ridge';
  AR_EXT.label.volcano = 'Volcano';
  AR_EXT.label.mesa = 'Mesa';
  AR_EXT.label.valley = 'Valley';
})();
