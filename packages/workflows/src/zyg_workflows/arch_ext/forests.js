// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* forests — a whole wood as ONE record.

     forest       hundreds of trees on a jittered grid over w x d
     tree_line    a row of trees along local +X (a road, a dyke, a canal)
     orchard      a grid of small round-crowned fruit trees
     undergrowth  a seeded scatter of low shrubs on the forest floor

   WHY ONE RECORD. site_landscape's plant_trees makes one record PER tree,
   which is right for a handful of trees the user will move by hand and quite
   wrong for a wood: 400 records eat 5 % of the 8000-object ceiling and the
   frame rate with them. Here every tree of a forest is baked into TWO merged
   BufferGeometries — one for all the crowns (sub 'mat_foliage'), one for all
   the trunks (sub 'mat_timber') — so a 400-tree wood is 2 draw calls.

   LOW POLY IS THE POINT. Per tree:
     trunk    6-segment tapered cylinder, no bottom cap   3*6 = 18 tris
     conifer  8-segment cone (side fan + base cap)        2*8 = 16 tris
     poplar   the same cone, narrow (r = 0.12 h)          2*8 = 16 tris
     crown    8 x 4 low sphere (deciduous / fruit / shrub)      48 tris
   so a conifer is 34, a deciduous 66, a shrub 48. A 400-tree mixed forest is
   about 20 000 triangles; even 400 pure deciduous trees stay under 27 000.

   THE SCATTER IS A CONTRACT. hash() below is byte-for-byte the same
   arithmetic as _hash() in arch_assistant_ext/forests.py and
   arch_blender_ext/forests.py (and as terrain.js's hash), and forestGrid /
   forestSpots mirror forest_grid / forest_spots in the Python copies. The
   test evaluates the Python copy and asserts this geometry's triangle count
   and bounding box match tree for tree. Change one copy and the three
   engines grow different woods.

   Local frame, as every kind: the record's x/z is the CENTRE in plan, the
   ground is y = 0, up is +Y. tree_line runs along local +X and is turned by
   the record's ry, exactly as a fence is.

   THE GROUND DRAPES, THE TREES DO NOT LEAN (2026-09-07). gx and gz are the
   slope of the ground plane under the record along its LOCAL x and z (rise per
   metre, default 0). Every tree's BASE sits at y = gx*lx + gz*lz and the whole
   tree — trunk and crown together — is lifted by that; the trunk stays
   vertical and the crown stays round. That is why the record itself is never
   tilted with rx/rz: tilting it would lean a whole wood downhill. The triangle
   count is untouched by gx/gz; only the bounding box grows, by the plane's
   rise across the footprint (arch_assistant_ext.forests.forest_bbox() is the
   Python statement of that box, and the test asserts this geometry matches).
   Ground that is not planar is not this record's problem: the tool splits the
   block into tiles and gives each tile its own record with its own gx/gz. */
(function(){
  var MAXN = 3000;                  /* trees in one forest record */
  var MAXLINE = 400;                /* trees in one tree_line record */
  var MAXSCATTER = 2000;            /* shrubs in one undergrowth record */
  var TRUNK_SEG = 6, CONE_SEG = 8, CROWN_U = 8, CROWN_V = 4;
  var ORCHARD_RC = 1.6;

  function clamp(v, lo, hi){ return v < lo ? lo : (v > hi ? hi : v); }
  function frac(x){ return x - Math.floor(x); }
  function hash(ix, iy, seed){ return frac(Math.sin(ix*127.1 + iy*311.7 + seed*74.7) * 43758.5453); }

  function mesh(k, pos, idx, sub){
    var g = new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return sub ? {g: g, sub: sub} : {g: g};
  }

  /* ── the three primitives every tree is made of ── */
  /* tapered cylinder: r0 at the bottom, r1 at the top, no bottom cap. 3*seg tris */
  function pushCyl(pos, idx, r0, r1, y0, h, seg, cx, cz){
    var b = pos.length / 3, i, an;
    for(i = 0; i < seg; i++){ an = 2*Math.PI*i/seg; pos.push(cx + Math.cos(an)*r0, y0, cz + Math.sin(an)*r0); }
    for(i = 0; i < seg; i++){ an = 2*Math.PI*i/seg; pos.push(cx + Math.cos(an)*r1, y0 + h, cz + Math.sin(an)*r1); }
    pos.push(cx, y0 + h, cz);
    var top = b + 2*seg;
    for(i = 0; i < seg; i++){
      var j = (i + 1) % seg;
      idx.push(b + i, b + seg + i, b + seg + j);
      idx.push(b + i, b + seg + j, b + j);
      idx.push(b + seg + i, top, b + seg + j);
    }
  }
  /* cone on a base cap: 2*seg tris */
  function pushCone(pos, idx, r, y0, h, seg, cx, cz){
    var b = pos.length / 3, i, an;
    for(i = 0; i < seg; i++){ an = 2*Math.PI*i/seg; pos.push(cx + Math.cos(an)*r, y0, cz + Math.sin(an)*r); }
    pos.push(cx, y0 + h, cz);                 /* apex        b+seg   */
    pos.push(cx, y0, cz);                     /* base centre b+seg+1 */
    var apex = b + seg, ctr = b + seg + 1;
    for(i = 0; i < seg; i++){
      var j = (i + 1) % seg;
      idx.push(b + i, apex, b + j);
      idx.push(b + j, ctr, b + i);
    }
  }
  /* low sphere radius r, centre (cx, cy, cz), squashed by ys: u*(2 + 2*(v-2)) tris.
     At v = 4 the widest ring has exactly radius r and its vertices sit at 45 deg
     steps from 0, so the bounding box is exactly 2r x 2r*ys x 2r. */
  function pushSphere(pos, idx, r, cx, cy, cz, useg, vseg, ys){
    var b = pos.length / 3, i, kk;
    for(kk = 1; kk < vseg; kk++){
      var phi = Math.PI*kk/vseg, rr = Math.sin(phi)*r, yy = Math.cos(phi)*r*ys;
      for(i = 0; i < useg; i++){ var an = 2*Math.PI*i/useg; pos.push(cx + Math.cos(an)*rr, cy + yy, cz + Math.sin(an)*rr); }
    }
    var np = b + (vseg - 1)*useg, sp = np + 1;
    pos.push(cx, cy + r*ys, cz);
    pos.push(cx, cy - r*ys, cz);
    function v(kk, i){ return b + (kk - 1)*useg + (i % useg); }
    for(i = 0; i < useg; i++) idx.push(np, v(1, i + 1), v(1, i));
    for(kk = 1; kk < vseg - 1; kk++){
      for(i = 0; i < useg; i++){
        idx.push(v(kk, i), v(kk + 1, i + 1), v(kk + 1, i));
        idx.push(v(kk, i), v(kk, i + 1), v(kk + 1, i + 1));
      }
    }
    for(i = 0; i < useg; i++) idx.push(sp, v(vseg - 1, i), v(vseg - 1, i + 1));
  }

  /* ── one tree, appended to the two shared buffers ──
     kind 0 = deciduous (round crown), 1 = conifer (cone), 2 = poplar (narrow cone).
     cf scales the crown radius only (0.8-1.2 from the hash) so the canopy is not a
     lawn of identical balls; y0 is the ground height under this tree, so the tree
     stands vertically on the draped plane. The top is always y0 + H. */
  function tree(cP, cI, tP, tI, kind, cx, cz, H, cf, y0){
    H = Math.max(0.5, H);
    cf = cf > 0 ? cf : 1;
    y0 = y0 || 0;
    if(kind === 0){
      var rc = 0.36*H*cf;
      pushCyl(tP, tI, 0.05*H, 0.04*H, y0, H - 2*rc, TRUNK_SEG, cx, cz);
      pushSphere(cP, cI, rc, cx, y0 + H - rc, cz, CROWN_U, CROWN_V, 1);
    }else{
      var r = (kind === 2 ? 0.12 : 0.25)*H*cf;
      pushCyl(tP, tI, 0.045*H, 0.035*H, y0, 0.15*H, TRUNK_SEG, cx, cz);
      pushCone(cP, cI, r, y0 + 0.15*H, 0.85*H, CONE_SEG, cx, cz);
    }
  }

  /* ── the shared scatter (mirrored verbatim in the two Python copies) ── */
  function forestGrid(w, d, dens){
    var s = Math.sqrt(1/dens);
    var n = Math.max(1, Math.min(MAXN, Math.floor(w*d*dens + 0.5)));
    var nx = Math.max(1, Math.floor(w/s + 0.5));
    return {n: n, s: s, nx: nx, nz: Math.max(1, Math.ceil(n/nx))};
  }
  function forestSpots(w, d, dens, mix, h, jit, seed){
    var G = forestGrid(w, d, dens), out = [], k;
    var x0 = -w/2 + G.s/2, z0 = -d/2 + G.s/2;
    for(k = 0; k < G.n; k++){
      var j = Math.floor(k/G.nx), i = k - j*G.nx;
      out.push([x0 + i*G.s + (2*hash(i, j, seed) - 1)*jit*G.s,
                z0 + j*G.s + (2*hash(i, j, seed + 1) - 1)*jit*G.s,
                hash(i, j, seed + 2) < mix ? 1 : 0,
                h*(0.7 + 0.6*hash(i, j, seed + 3)),
                0.8 + 0.4*hash(i, j, seed + 4)]);
    }
    return out;
  }

  /* ── the kinds ── */
  AR_EXT.geom.forest = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = clamp(N('w', 100), 1, 600), d = clamp(N('d', 100), 1, 600);
    var dens = clamp(N('density', 0.04), 0.0005, 4);
    var mix = clamp(N('mix', 0.5), 0, 1), h = clamp(N('h', 14), 0.5, 120);
    var jit = clamp(N('jitter', 0.45), 0, 2), seed = N('seed', 1);
    var gx = N('gx', 0), gz = N('gz', 0);
    var spots = forestSpots(w, d, dens, mix, h, jit, seed);
    var cP = [], cI = [], tP = [], tI = [], i, s;
    for(i = 0; i < spots.length; i++){
      s = spots[i];
      tree(cP, cI, tP, tI, s[2] ? 1 : 0, s[0], s[1], s[3], s[4], gx*s[0] + gz*s[1]);
    }
    return [mesh(k, cP, cI, 'mat_foliage'), mesh(k, tP, tI, 'mat_timber')];
  };

  AR_EXT.geom.tree_line = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var L = clamp(N('len', 60), 1, 2000), sp = clamp(N('spacing', 6), 1, 100);
    var kind = Math.max(0, Math.min(2, Math.round(N('kind', 0))));
    var h = clamp(N('h', 10), 0.5, 120), jit = clamp(N('jitter', 0.2), 0, 10), seed = N('seed', 1);
    var gx = N('gx', 0), gz = N('gz', 0);
    var n = Math.max(1, Math.min(MAXLINE, Math.floor(L/sp) + 1));
    var cP = [], cI = [], tP = [], tI = [], i;
    for(i = 0; i < n; i++){
      var lx = -L/2 + i*sp, lz = (2*hash(i, 0, seed) - 1)*jit;
      tree(cP, cI, tP, tI, kind, lx, lz,
           h*(0.85 + 0.3*hash(i, 0, seed + 3)),
           0.8 + 0.4*hash(i, 0, seed + 4),
           gx*lx + gz*lz);
    }
    return [mesh(k, cP, cI, 'mat_foliage'), mesh(k, tP, tI, 'mat_timber')];
  };

  AR_EXT.geom.orchard = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = clamp(N('w', 40), 1, 600), d = clamp(N('d', 30), 1, 600);
    var sp = clamp(N('spacing', 5), 1, 100), h = clamp(N('h', 4), 1, 40);
    var gx = N('gx', 0), gz = N('gz', 0);
    var rc = Math.min(ORCHARD_RC, h*0.4);
    var nx = Math.floor(w/sp) + 1, nz = Math.floor(d/sp) + 1;
    var x0 = -(nx - 1)*sp/2, z0 = -(nz - 1)*sp/2;
    var cP = [], cI = [], tP = [], tI = [], i, j;
    for(j = 0; j < nz; j++){
      for(i = 0; i < nx; i++){
        /* an orchard is a planted grid: the crowns stay equal, only the ground drapes */
        var cx = x0 + i*sp, cz = z0 + j*sp, y0 = gx*cx + gz*cz;
        pushCyl(tP, tI, 0.09*h, 0.07*h, y0, h - 2*rc, TRUNK_SEG, cx, cz);
        pushSphere(cP, cI, rc, cx, y0 + h - rc, cz, CROWN_U, CROWN_V, 1);
      }
    }
    return [mesh(k, cP, cI, 'mat_foliage'), mesh(k, tP, tI, 'mat_timber')];
  };

  AR_EXT.geom.undergrowth = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = clamp(N('w', 40), 1, 600), d = clamp(N('d', 40), 1, 600);
    var n = Math.max(1, Math.min(MAXSCATTER, Math.round(N('count', 60))));
    var r = clamp(N('r', 0.8), 0.05, 8), seed = N('seed', 1);
    var gx = N('gx', 0), gz = N('gz', 0);
    var cP = [], cI = [], i;
    for(i = 0; i < n; i++){
      var rr = r*(0.6 + 0.8*hash(i, 0, seed + 2));
      var lx = -w/2 + hash(i, 0, seed)*w, lz = -d/2 + hash(i, 0, seed + 1)*d;
      pushSphere(cP, cI, rr, lx, gx*lx + gz*lz + 0.6*rr, lz, CROWN_U, CROWN_V, 0.6);
    }
    return [mesh(k, cP, cI, 'mat_foliage')];
  };

  AR_EXT.label.forest = 'Forest';
  AR_EXT.label.tree_line = 'Tree line';
  AR_EXT.label.orchard = 'Orchard';
  AR_EXT.label.undergrowth = 'Undergrowth';
})();
