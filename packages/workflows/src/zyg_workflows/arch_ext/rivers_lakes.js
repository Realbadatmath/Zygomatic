// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* rivers_lakes — NATURAL water. Three kinds:

     river      one meandering reach running along X; a trapezoid channel cut
                into the ground (GRAVEL bed w wide at y=-depth, banks sloping
                `bank` metres out each side up to y=0, the top 40 % of each
                bank slope in GRASS) with a flat water surface just under
                ground level. The centreline's sideways offset is ZERO at both
                ends, so consecutive reaches always meet. The record's rz tilts
                the whole reach so it runs downhill (2026-09-07, the ground seam).
     lake       an irregular basin: a wobbly ellipse rim, a shore sloping down
                to a flat bed at -depth, water at -0.15 and a thin sand rim
                lying in the outermost `rim` metres (1 m by default) of the
                `shore` band.
     waterfall  a rock lip, a vertical sheet of water h tall, and a round
                plunge pool at the foot of it.

   Canals and ponds are water_leisure's — those are BUILT water with quay walls
   and a coping. These three are the landscape kind: they sit at ground level
   and DIG, so their bounding boxes reach below y=0.

   Local frame: the record's x/z is the CENTRE in plan, ground at y=0, up = +Y.
   Plan angles are the studio's: 0 = +X, 90 = -Z, so a point at angle theta is
   (r cos theta, -r sin theta).

   THE NOISE IS A CONTRACT. hash/vnoise below are byte-for-byte the copies in
   arch_ext/terrain.js, arch_assistant_ext/terrain.py and
   arch_blender_ext/terrain.py, and arMeander/arLakeF are written out again in
   arch_assistant_ext/rivers_lakes.py and arch_blender_ext/rivers_lakes.py.
   The test evaluates the Python copies and compares the numbers with this
   geometry's bounding box; change one copy and you get three landscapes. */
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
  function cyl(k, r, h, y0, seg, rTop){
    var rt = (rTop === undefined || rTop === null) ? r : rTop;
    var g = new k.THREE.CylinderGeometry(Math.max(rt, 0), Math.max(r, 1e-4), Math.max(h, 1e-4), Math.max(6, seg || 24));
    g.translate(0, y0 + Math.max(h, 1e-4) / 2, 0);
    return g;
  }

  /* the river's sideways wander, in metres, at t along the reach (0..1).
     sin(pi*t) is the envelope: it is 0 at BOTH ends, which is what lets one
     reach hand over to the next without a kink in the bank line. */
  function arMeander(t, meander, seed){
    return meander * Math.sin(Math.PI*t) * (0.6*Math.sin(2*Math.PI*t*1.5) + 0.4*(2*vnoise(t*4, seed, seed) - 1));
  }
  /* the lake rim's radius multiplier at plan angle a */
  function arLakeF(a, wobble, seed){
    return 1 + wobble * (2*vnoise(Math.cos(a)*2 + 2, Math.sin(a)*2 + 2, seed) - 1);
  }
  /* the shore band, clamped so bed radius stays positive */
  function arLakeShore(rx, rz, wobble, shore){
    return Math.max(0.05, Math.min(shore, Math.min(rx, rz) * (1 - wobble) * 0.4));
  }
  /* the SAND band: the outermost `rim` metres of that shore, 1 m by default */
  function arLakeRim(rx, rz, wobble, shore, rim){
    return Math.max(0.05, Math.min(Math.max(0.05, rim), arLakeShore(rx, rz, wobble, shore)));
  }
  /* the channel cross-section, outer bank to outer bank: [z, y] x 6. The top
     BANKG of each bank slope is its own strip (grass); the rest of the bank
     and the whole bed are one strip (gravel). */
  var BANKG = 0.4;
  function arChannel(w, dep, bank){
    return [[-(w/2 + bank), 0], [-(w/2 + bank*(1-BANKG)), -BANKG*dep], [-w/2, -dep],
            [w/2, -dep], [w/2 + bank*(1-BANKG), -BANKG*dep], [w/2 + bank, 0]];
  }

  AR_EXT.geom.river = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=Math.max(1, N('len',60)), w=Math.max(0.5, N('w',12)), dep=Math.max(0.2, N('depth',2));
    var mea=Math.max(0, N('meander',6)), seed=N('seed',1), bank=Math.max(0.05, N('bank',2));
    var seg=Math.max(4, Math.min(200, Math.round(N('seg',24))));
    var sec=arChannel(w, dep, bank), NP=sec.length;
    var pos=[], gidx=[], vidx=[], wpos=[], widx=[], i, j, t, x, zc, hw=(w+bank)/2;
    for(i=0;i<=seg;i++){
      t=i/seg; x=-L/2 + t*L; zc=arMeander(t, mea, seed);
      for(j=0;j<NP;j++) pos.push(x, sec[j][1], zc + sec[j][0]);
      wpos.push(x, -0.15, zc - hw, x, -0.15, zc + hw);
    }
    for(i=0;i<seg;i++){
      for(j=0;j<NP-1;j++){
        var a=i*NP+j, b=a+1, c=a+NP, e=c+1;
        /* strips 0 and NP-2 are the grassy tops of the two banks */
        var tgt=(j===0 || j===NP-2) ? gidx : vidx;
        tgt.push(a, c, b, b, c, e);
      }
      var A=i*2;
      widx.push(A, A+2, A+1, A+1, A+2, A+3);
    }
    return [{g: mesh(k, pos, vidx), sub:'mat_gravel'},
            {g: mesh(k, pos, gidx), sub:'mat_grass'},
            {g: mesh(k, wpos, widx), sub:'mat_water'}];
  };

  AR_EXT.geom.lake = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var rx=Math.max(0.5, N('rx',30)), rz=Math.max(0.5, N('rz',20)), dep=Math.max(0.2, N('depth',3));
    var wob=Math.max(0, Math.min(0.9, N('wobble',0.25))), seed=N('seed',1);
    var seg=Math.max(8, Math.min(256, Math.round(N('seg',48))));
    var sh=arLakeShore(rx, rz, wob, Math.max(0.1, N('shore',3)));
    var rw=arLakeRim(rx, rz, wob, Math.max(0.1, N('shore',3)), N('rim',1));
    var O=[], M=[], B=[], W=[], S=[], i, j;
    for(i=0;i<seg;i++){
      var a=2*Math.PI*i/seg, m=arLakeF(a, wob, seed);
      var X=rx*Math.cos(a)*m, Z=-rz*Math.sin(a)*m, r=Math.max(1e-4, Math.sqrt(X*X + Z*Z));
      var f1=Math.max(0.05, (r-sh)/r), f2=Math.max(0.02, (r-2*sh)/r);
      var fw=f1 + (f2-f1)*Math.min(1, 0.15/dep);
      var fs=Math.max(0.05, (r-rw)/r);
      O.push([X,Z]); M.push([X*f1, Z*f1]); B.push([X*f2, Z*f2]); W.push([X*fw, Z*fw]);
      S.push([X*fs, Z*fs]);
    }
    /* the basin: shore slope from the water line down to a flat bed */
    var pos=[], idx=[];
    for(i=0;i<seg;i++) pos.push(M[i][0], 0, M[i][1]);
    for(i=0;i<seg;i++) pos.push(B[i][0], -dep, B[i][1]);
    var ctr=2*seg; pos.push(0, -dep, 0);
    for(i=0;i<seg;i++){
      j=(i+1)%seg;
      idx.push(i, seg+i, j, j, seg+i, seg+j);
      idx.push(ctr, seg+j, seg+i);
    }
    /* the water surface, a disc on the slope 0.15 m down */
    var wp=[], wi=[];
    for(i=0;i<seg;i++) wp.push(W[i][0], -0.15, W[i][1]);
    wp.push(0, -0.15, 0);
    for(i=0;i<seg;i++){ j=(i+1)%seg; wi.push(seg, i, j); }
    /* the sand rim: a thin ring lying in the outermost `rim` metres of the shore */
    var sp=[], si=[];
    for(i=0;i<seg;i++) sp.push(S[i][0], 0.02, S[i][1]);
    for(i=0;i<seg;i++) sp.push(O[i][0], 0.02, O[i][1]);
    for(i=0;i<seg;i++) sp.push(S[i][0], 0, S[i][1]);
    for(i=0;i<seg;i++) sp.push(O[i][0], 0, O[i][1]);
    for(i=0;i<seg;i++){
      j=(i+1)%seg;
      var it=i, ot=seg+i, ib=2*seg+i, ob=3*seg+i;
      var jt=j, ojt=seg+j, jb=2*seg+j, ojb=3*seg+j;
      si.push(it, ot, ojt, it, ojt, jt);            /* top */
      si.push(ib, ojb, ob, ib, jb, ojb);            /* bottom */
      si.push(ot, ob, ojb, ot, ojb, ojt);           /* outer skirt */
      si.push(it, ojt, ojb, it, ojb, ib);           /* inner skirt */
    }
    return [{g: mesh(k, pos, idx), sub:'mat_soil'},
            {g: mesh(k, wp, wi), sub:'mat_water'},
            {g: mesh(k, sp, si), sub:'mat_sand'}];
  };

  AR_EXT.geom.waterfall = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(0.5, N('w',8)), h=Math.max(1, N('h',12));
    var dep=Math.max(0.2, N('depth',2)), pr=Math.max(1, N('pool_r',8));
    var xf=-Math.max(0.6, pr*0.6);                       /* the fall lands upstream of the pool centre */
    return [{g: cyl(k, pr*0.7, dep, -dep, 32, pr)},                                  /* plunge pool basin */
            {g: cyl(k, pr*0.92, 0.03, -0.16, 32), sub:'mat_water'},                  /* pool surface */
            {g: k.box(0.3, h, w, xf, h/2, 0), sub:'mat_water'},                      /* the falling sheet */
            {g: k.box(2, 1, w, xf - 0.85, h + 0.5, 0), sub:'mat_rock'}];             /* the rock lip */
  };

  AR_EXT.label.river = 'River';
  AR_EXT.label.lake = 'Lake';
  AR_EXT.label.waterfall = 'Waterfall';
})();
