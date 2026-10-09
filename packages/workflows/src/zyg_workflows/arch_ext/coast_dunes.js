// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* coast_dunes — the shoreline: where the land stops. Five kinds:

     sea         a water lattice at ground level over a flat sea bed
     beach       a sand wedge rising from the water edge to a back crest
     dune_field  a solid field of ridged sand dunes (duin)
     island      a wobbly-rimmed hill with a sand beach ring round it
     breakwater  a rubble mound with a trapezoid section (strekdam)

   Local frame: the record's x/z is the CENTRE in plan, the ground sits at
   y=0. Plan angles are the studio's: 0 = +X, 90 = -Z (north = up in the top
   view), so g.rotateY(+theta) turns +X to -Z.

   THE SEA DIGS. Its water surface sits just below y=0 and its bed is at
   -depth, exactly like water_leisure's pond and canal — a body of water is
   a hole in the ground filled to the brim, and that is the only honest way
   to draw one. Everything else here sits ON the ground: a beach, a dune
   field and an island all have their lowest point at y=0.

   THE BEACH KNOWS WHICH SIDE THE WATER IS ON. Its water edge (y=0) is at
   local z = -w/2 and its crest (y=h) at local z = +w/2. With ry=0 the
   record walks along +X, so local -Z is world -Z = north, which is the
   LEFT of that walking direction. Turn the record with ry and the sea
   stays on the left. add_beach() states the same rule in words.

   TWO MATERIALS OVER ONE VERTEX ARRAY. The beach's first 15% of width (the
   rows nearest the water) is wet sand — mat_soil — and every dune quad whose
   average height passes 70% of h is marram grass — mat_grass. Both are index
   subsets of the SAME positions, so the bounding box of a beach and of a dune
   field is exactly what it was before the looks were added; only the colour
   under the tide line and on the crests changes. arch_blender_ext does the
   same with material_index.

   THE NOISE IS A CONTRACT. hash/vnoise below are byte-for-byte the same
   arithmetic as value_noise() in arch_assistant_ext/coast_dunes.py and in
   arch_blender_ext/coast_dunes.py (and as terrain's, which they were copied
   from). The test evaluates the Python copies of the sea's wave, the dune
   normalisation and the island's rim and compares the numbers with this
   geometry's bounding box. Change one copy and you get three coasts. */
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
  /* a free quad (four fresh vertices) — used for skirts and floors */
  function quad(pos, idx, a, b, c, e){
    var n=pos.length/3;
    pos.push(a[0],a[1],a[2], b[0],b[1],b[2], c[0],c[1],c[2], e[0],e[1],e[2]);
    idx.push(n, n+1, n+2, n, n+2, n+3);
  }
  /* the lattice of a (nx+1) x (nz+1) grid whose vertices start at index 0 */
  function lattice(idx, nx, nz){ latticeRows(idx, nx, 0, nz); }
  /* rows j0..j1-1 of that lattice only — how the wet-sand band and the marram
     crests get their own material without moving a single vertex */
  function latticeRows(idx, nx, j0, j1){
    for(var j=j0;j<j1;j++){
      for(var i=0;i<nx;i++){
        var a=j*(nx+1)+i, b=a+1, c=a+nx+1, e=c+1;
        idx.push(a,c,b, b,c,e);                 /* both triangles face +Y */
      }
    }
  }

  /* ── the sea ─────────────────────────────────────────────────────────── */
  AR_EXT.geom.sea = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(1, N('w',200)), d=Math.max(1, N('d',200));
    var dep=Math.max(0.4, N('depth',6)), wave=Math.max(0, N('wave',0.15)), seed=N('seed',1);
    var res=Math.max(2, Math.min(96, Math.round(N('res',32))));
    var pos=[], idx=[], i, j;
    for(j=0;j<=res;j++){
      for(i=0;i<=res;i++){
        pos.push(-w/2 + i/res*w,
                 -0.3 + wave*(2*vnoise(i/res*8, j/res*8, seed) - 1),
                 -d/2 + j/res*d);
      }
    }
    lattice(idx, res, res);
    return [{g: mesh(k, pos, idx), sub:'mat_water'},
            {g: k.box(w, 0.2, d, 0, -dep, 0), sub:'mat_sand'}];
  };

  /* ── the beach ───────────────────────────────────────────────────────── */
  /* a solid wedge: water edge (y=0) at z=-w/2, crest (y=h) at z=+w/2, with
     a cosine profile across and a gentle along-shore swell from the noise,
     the whole field scaled so its highest point is exactly h. */
  var BX = 24, BZ = 20;                        /* segments along / across */
  var WET = 0.15, WETJ = Math.round(BZ*WET);   /* wet sand: the 15% (3 rows) at the water edge */
  function beachField(w, h, seed){
    var raw=[], mx=1e-9, i, j;
    for(j=0;j<=BZ;j++){
      raw.push([]);
      for(i=0;i<=BX;i++){
        var prof = 0.5*(1 - Math.cos(Math.PI*j/BZ));
        var amp  = 1 - 0.15*(2*vnoise(i/BX*3, 4.5, seed) - 1);
        var v = prof*amp;
        raw[j].push(v); if(v > mx) mx = v;
      }
    }
    return {raw: raw, sc: h/mx};
  }
  AR_EXT.geom.beach = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=Math.max(1, N('len',60)), w=Math.max(1, N('w',25)), h=Math.max(0.05, N('h',2)), seed=N('seed',1);
    var f=beachField(w, h, seed), raw=f.raw, sc=f.sc;
    var X=function(i){ return -L/2 + i/BX*L; }, Z=function(j){ return -w/2 + j/BZ*w; };
    var pos=[], idx=[], wet=[], i, j;
    for(j=0;j<=BZ;j++) for(i=0;i<=BX;i++) pos.push(X(i), raw[j][i]*sc, Z(j));
    latticeRows(wet, BX, 0, WETJ);               /* the wet band at the water edge */
    latticeRows(idx, BX, WETJ, BZ);              /* the dry sand behind it */
    for(i=0;i<BX;i++){                                            /* the back scarp */
      quad(pos, idx, [X(i+1),0,Z(BZ)], [X(i),0,Z(BZ)],
                     [X(i),raw[BZ][i]*sc,Z(BZ)], [X(i+1),raw[BZ][i+1]*sc,Z(BZ)]);
    }
    for(j=0;j<BZ;j++){                                            /* the two ends */
      quad(pos, idx, [X(0),0,Z(j+1)], [X(0),0,Z(j)],
                     [X(0),raw[j][0]*sc,Z(j)], [X(0),raw[j+1][0]*sc,Z(j+1)]);
      quad(pos, idx, [X(BX),0,Z(j)], [X(BX),0,Z(j+1)],
                     [X(BX),raw[j+1][BX]*sc,Z(j+1)], [X(BX),raw[j][BX]*sc,Z(j)]);
    }
    quad(pos, idx, [-L/2,0,-w/2], [-L/2,0,w/2], [L/2,0,w/2], [L/2,0,-w/2]);   /* the floor */
    /* two parts over ONE vertex array: the bounding box is the same wedge, only
       the material of the first WETJ rows differs — that is the wet sand the
       tide keeps dark. */
    return [{g: mesh(k, pos, idx), sub:'mat_sand'},
            {g: mesh(k, pos, wet), sub:'mat_soil'}];
  };

  /* ── the dune field ──────────────────────────────────────────────────── */
  /* RIDGED noise: 1 - |2v-1| makes creases where the value noise crosses
     0.5. The i frequency is low and the j frequency high, so the ridges run
     along the record's X — across the wind. */
  AR_EXT.geom.dune_field = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(1, N('w',120)), d=Math.max(1, N('d',60)), h=Math.max(0.05, N('h',8));
    var seed=N('seed',1), dir=N('dir',0);
    var res=Math.max(2, Math.min(96, Math.round(N('res',40))));
    var raw=[], mx=1e-9, i, j, v;
    for(j=0;j<=res;j++){
      raw.push([]);
      for(i=0;i<=res;i++){
        v = 1 - Math.abs(2*vnoise(i/res*2.5, j/res*7, seed) - 1);
        raw[j].push(v); if(v > mx) mx = v;
      }
    }
    var sc = h/mx;                                       /* the peak is exactly h */
    var X=function(i){ return -w/2 + i/res*w; }, Z=function(j){ return -d/2 + j/res*d; };
    var pos=[], idx=[], crest=[];
    for(j=0;j<=res;j++) for(i=0;i<=res;i++) pos.push(X(i), raw[j][i]*sc, Z(j));
    /* MARRAM GRASS: the quads whose four corners average above 70% of h are the
       crests the marram holds. Same vertices, second material — the bounding
       box does not move. */
    var MARRAM = 0.70, lim = MARRAM*h;
    for(j=0;j<res;j++){
      for(i=0;i<res;i++){
        var q0=j*(res+1)+i, q1=q0+1, q2=q0+res+1, q3=q2+1;
        var avg = (raw[j][i] + raw[j][i+1] + raw[j+1][i] + raw[j+1][i+1])*sc/4;
        (avg > lim ? crest : idx).push(q0,q2,q1, q1,q2,q3);
      }
    }
    for(i=0;i<res;i++){
      quad(pos, idx, [X(i),0,Z(0)], [X(i+1),0,Z(0)],
                     [X(i+1),raw[0][i+1]*sc,Z(0)], [X(i),raw[0][i]*sc,Z(0)]);
      quad(pos, idx, [X(i+1),0,Z(res)], [X(i),0,Z(res)],
                     [X(i),raw[res][i]*sc,Z(res)], [X(i+1),raw[res][i+1]*sc,Z(res)]);
    }
    for(j=0;j<res;j++){
      quad(pos, idx, [X(0),0,Z(j+1)], [X(0),0,Z(j)],
                     [X(0),raw[j][0]*sc,Z(j)], [X(0),raw[j+1][0]*sc,Z(j+1)]);
      quad(pos, idx, [X(res),0,Z(j)], [X(res),0,Z(j+1)],
                     [X(res),raw[j+1][res]*sc,Z(j+1)], [X(res),raw[j][res]*sc,Z(j)]);
    }
    quad(pos, idx, [-w/2,0,-d/2], [-w/2,0,d/2], [w/2,0,d/2], [w/2,0,-d/2]);
    var g=mesh(k, pos, idx), out=[{g: g, sub:'mat_sand'}];
    if(dir){ g.rotateY(dir*Math.PI/180); g.computeVertexNormals(); }
    if(crest.length){
      var gc=mesh(k, pos, crest);
      if(dir){ gc.rotateY(dir*Math.PI/180); gc.computeVertexNormals(); }
      out.push({g: gc, sub:'mat_grass'});
    }
    return out;
  };

  /* ── the island ──────────────────────────────────────────────────────── */
  /* the rim radius wanders with the noise round the circumference; the grass
     falls from h at the centre to 0.3 at the rim, and a sand ring `beach`
     wide runs on from there down to y=0. */
  function islandRim(r, wobble, seed, seg){
    var R=[], i;
    for(i=0;i<seg;i++){
      var a=2*Math.PI*i/seg;
      R.push(r*(1 + wobble*(2*vnoise(Math.cos(a)*2+2, Math.sin(a)*2+2, seed) - 1)));
    }
    return R;
  }
  AR_EXT.geom.island = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=Math.max(1, N('r',40)), h=Math.max(0.5, N('h',6));
    var wob=Math.max(0, Math.min(0.9, N('wobble',0.3))), bch=Math.max(0.2, N('beach',6));
    var seed=N('seed',1);
    var seg=Math.max(8, Math.min(128, Math.round(N('seg',48))));
    var rings=Math.max(2, Math.min(40, Math.round(N('rings',10))));
    var R=islandRim(r, wob, seed, seg);
    var pos=[0,h,0], idx=[], i, kk;
    for(kk=1;kk<=rings;kk++){
      var f=kk/rings, y=0.3 + (h-0.3)*0.5*(1 + Math.cos(Math.PI*f));
      for(i=0;i<seg;i++){
        var a=2*Math.PI*i/seg;
        pos.push(Math.cos(a)*R[i]*f, y, Math.sin(a)*R[i]*f);
      }
    }
    var outer=1+rings*seg;                                    /* the sand ring's outer rim */
    for(i=0;i<seg;i++){
      var an=2*Math.PI*i/seg;
      pos.push(Math.cos(an)*(R[i]+bch), 0, Math.sin(an)*(R[i]+bch));
    }
    var ctr=outer+seg;
    pos.push(0,0,0);
    function ring(kk,i){ return 1 + (kk-1)*seg + (i%seg); }
    function out(i){ return outer + (i%seg); }
    for(i=0;i<seg;i++) idx.push(0, ring(1,i+1), ring(1,i));                    /* apex fan */
    for(kk=1;kk<rings;kk++){
      for(i=0;i<seg;i++){
        var A0=ring(kk,i), A1=ring(kk,i+1), B0=ring(kk+1,i), B1=ring(kk+1,i+1);
        idx.push(A1,A0,B0, A1,B0,B1);
      }
    }
    var sand=[];
    for(i=0;i<seg;i++){                                                        /* the beach ring */
      sand.push(ring(rings,i+1), ring(rings,i), out(i));
      sand.push(ring(rings,i+1), out(i), out(i+1));
    }
    for(i=0;i<seg;i++) idx.push(ctr, out(i+1), out(i));                        /* the flat base */
    var g=mesh(k, pos, idx);
    var gs=new k.THREE.BufferGeometry();
    gs.setAttribute('position', new k.THREE.Float32BufferAttribute(pos, 3));
    gs.setIndex(sand); gs.computeVertexNormals();
    return [{g: g}, {g: gs, sub:'mat_sand'}];
  };

  /* ── the breakwater ──────────────────────────────────────────────────── */
  AR_EXT.geom.breakwater = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=Math.max(1, N('len',60)), w=Math.max(0.5, N('w',8)), h=Math.max(0.2, N('h',3));
    var g=k.prism([[-w/2,0],[w/2,0],[w/6,h],[-w/6,h]], L);
    g.rotateY(Math.PI/2);                        /* the mound runs along X */
    g.computeVertexNormals();
    return [{g: g, sub:'mat_rock'}];
  };

  AR_EXT.label.sea = 'Sea';
  AR_EXT.label.beach = 'Beach';
  AR_EXT.label.dune_field = 'Dune field';
  AR_EXT.label.island = 'Island';
  AR_EXT.label.breakwater = 'Breakwater';
})();
