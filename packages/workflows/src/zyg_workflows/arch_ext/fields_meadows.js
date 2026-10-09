// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* fields_meadows — the farmed and the wild ground between the buildings:

     crop_field  a soil plate with rows of crop; crop 4 is the striped Dutch
                 bulb field (bollenveld), red / white / yellow in a 3-cycle
     meadow      a grass plate with hash-scattered flower heads (weiland)
     marsh       a shallow basin with water just below ground and reeds (moeras)
     vineyard    rows of posts carrying a continuous vine mass

   Local frame, as every kind: the record's x/z is the CENTRE in plan, the
   ground is y = 0, up is +Y. A marsh DIGS — its basin runs down to -depth —
   everything else grows from the ground up. `dir` turns a field's rows on the
   plan in degrees (0 = rows along +X, 90 = rows along -Z), the studio's own
   convention: a plan point (x, z) turned by theta lands at
   (x*cos + z*sin, -x*sin + z*cos), which is what THREE's rotateY(+theta) does.

   THE DRAPE (2026-09-07). gx and gz are the slope of the ground plane under
   the record, rise per metre along the record's LOCAL x and z — the numbers
   arch_assistant.ground_plane() measured. Every solid here is DRAPED, never
   tilted: its four base corners are dropped to y = gx*X + gz*Z (X, Z the
   corner's plan position AFTER the `dir` turn) and its side edges stay
   vertical, so a field follows the hillside while its rows, its posts and its
   flowers still stand up straight. gx = gz = 0 is the flat case and builds
   exactly the boxes this file built before. Water (marsh) is never draped —
   it lies level, and the assistant refuses uneven ground for it.

   ROWS FILL THE PLOT. A field of depth d at `spacing` carries
   floor(d/spacing)+1 rows, spread evenly so the outer edges of the first and
   the last row land exactly on the plot edge. A row is LOW and WIDE — its
   band is 0.6 x spacing, so the soil shows between the stripes. The bounding
   box is therefore w x d on the plan whatever the spacing is — the same
   arithmetic lives in arch_assistant_ext/fields_meadows.py (field_rows) and in
   arch_blender_ext/fields_meadows.py, and the test compares the triangle
   counts the three copies produce.

   THE SCATTER IS A CONTRACT. hash() below is byte-for-byte the generator in
   arch_ext/terrain.js and value_noise() in the terrain Python copies:
   frac(sin(i*127.1 + j*311.7 + seed*74.7) * 43758.5453). Flowers and reeds
   are placed with it, so the same seed grows the same meadow in the tab, in
   Blender and in the assistant's own arithmetic. Change one copy and you have
   three different landscapes. */
(function(){
  function frac(x){ return x - Math.floor(x); }
  function hash(ix, iy, seed){ return frac(Math.sin(ix*127.1 + iy*311.7 + seed*74.7) * 43758.5453); }

  /* a triangle accumulator: many little solids merged into ONE part, so a
     10 000-flower meadow is one draw call and one material, not 10 000 */
  function acc(){ return {pos: [], idx: []}; }

  /* Box of w x h x d centred at (cx, cz) in the PRE-turn plan, with its base
     dropped onto the ground plane and its sides vertical. rot turns the plan
     by that many radians (the record's `dir`); gx, gz are the plane's slopes
     along the record's local X and Z, applied AFTER the turn. With
     rot = gx = gz = 0 this is an ordinary axis-aligned box with its bottom at
     cy — the flat case every old drawing still gets. */
  function boxInto(A, w, h, d, cx, cy, cz, rot, gx, gz){
    var c = Math.cos(rot || 0), s = Math.sin(rot || 0);
    var GX = gx || 0, GZ = gz || 0;
    var b = A.pos.length / 3, i;
    var x0 = cx - w/2, x1 = cx + w/2, z0 = cz - d/2, z1 = cz + d/2;
    var corners = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    var lo = [], hi = [];
    for(i = 0; i < 4; i++){
      var X = corners[i][0]*c + corners[i][1]*s;
      var Z = -corners[i][0]*s + corners[i][1]*c;
      var y0 = cy + GX*X + GZ*Z;
      lo.push([X, y0, Z]); hi.push([X, y0 + h, Z]);
    }
    for(i = 0; i < 4; i++) A.pos.push(lo[i][0], lo[i][1], lo[i][2]);
    for(i = 0; i < 4; i++) A.pos.push(hi[i][0], hi[i][1], hi[i][2]);
    var F = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]];
    for(i = 0; i < 6; i++){
      var q = F[i];
      A.idx.push(b+q[0], b+q[1], b+q[2], b+q[0], b+q[2], b+q[3]);
    }
  }

  /* a seg-sided prism of radius r, h tall, standing on cy — a reed */
  function cylInto(A, r, h, seg, cx, cy, cz){
    var b = A.pos.length / 3, i, an;
    for(i = 0; i < seg; i++){ an = 2*Math.PI*i/seg; A.pos.push(cx + Math.cos(an)*r, cy, cz + Math.sin(an)*r); }
    for(i = 0; i < seg; i++){ an = 2*Math.PI*i/seg; A.pos.push(cx + Math.cos(an)*r, cy + h, cz + Math.sin(an)*r); }
    for(i = 0; i < seg; i++){
      var j = (i + 1) % seg;
      A.idx.push(b+i, b+j, b+seg+j, b+i, b+seg+j, b+seg+i);
    }
    for(i = 1; i < seg - 1; i++){
      A.idx.push(b, b+i+1, b+i);
      A.idx.push(b+seg, b+seg+i, b+seg+i+1);
    }
  }

  function mesh(k, A){
    var g = new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(A.pos, 3));
    g.setIndex(A.idx);
    g.computeVertexNormals();
    return g;
  }

  /* row centres across a plot `d` deep: floor(d/spacing)+1 rows, spread so
     that a row `band` wide reaches exactly to +-d/2 at both ends */
  function rowsOf(d, spacing, band){
    var n = Math.max(2, Math.min(2000, Math.floor(d / Math.max(0.05, spacing)) + 1));
    var span = Math.max(0, d - band), step = span / (n - 1), out = [], j;
    for(j = 0; j < n; j++) out.push(-span/2 + j*step);
    return out;
  }

  /* crop -> the sub materials its rows cycle through */
  var CROP_SUB = [['mat_sand'],                                   /* 0 wheat  */
                  ['mat_foliage'],                                /* 1 corn   */
                  ['mat_foliage'],                                /* 2 potato */
                  ['mat_grass'],                                  /* 3 hay    */
                  ['mat_brick', 'mat_paint_white', 'mat_sand']];  /* 4 tulips */
  var FLOWER_SUB = ['mat_paint_white', 'mat_brick', 'mat_sand'];
  var ROW_FRAC = 0.6;      /* a row is 0.6 x spacing wide: a stripe, not a pipe */

  AR_EXT.geom.crop_field = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = Math.max(0.5, N('w', 60)), d = Math.max(0.5, N('d', 40));
    var crop = Math.max(0, Math.min(4, Math.round(N('crop', 0))));
    var sp = Math.max(0.05, N('spacing', 0.75)), h = Math.max(0.05, N('h', 0.3));
    var rot = N('dir', 0) * Math.PI / 180;
    var gx = N('gx', 0), gz = N('gz', 0);
    var band = Math.max(0.05, ROW_FRAC * sp);
    var subs = CROP_SUB[crop], nc = subs.length, i, j;
    var soil = acc();
    boxInto(soil, w, 0.05, d, 0, 0, 0, rot, gx, gz);
    var A = [];
    for(i = 0; i < nc; i++) A.push(acc());
    var zs = rowsOf(d, sp, band);
    for(j = 0; j < zs.length; j++) boxInto(A[j % nc], w, h, band, 0, 0.05, zs[j], rot, gx, gz);
    var P = [{g: mesh(k, soil), sub: 'mat_soil'}];
    for(i = 0; i < nc; i++) if(A[i].idx.length) P.push({g: mesh(k, A[i]), sub: subs[i]});
    return P;
  };

  AR_EXT.geom.meadow = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = Math.max(0.5, N('w', 60)), d = Math.max(0.5, N('d', 40));
    var nf = Math.max(0, Math.min(2000, Math.round(N('flowers', 200))));
    var seed = N('seed', 1), h = Math.max(0.05, N('h', 0.25));
    var gx = N('gx', 0), gz = N('gz', 0);
    var plate = acc();
    boxInto(plate, w, 0.08, d, 0, 0, 0, 0, gx, gz);
    var A = [acc(), acc(), acc()], i;
    var iw = Math.max(0.01, w - 0.15), id = Math.max(0.01, d - 0.15);
    for(i = 0; i < nf; i++){
      var x = -iw/2 + hash(i, 1, seed) * iw;
      var z = -id/2 + hash(i, 2, seed) * id;
      var c = Math.floor(hash(i, 3, seed) * 3) % 3;
      boxInto(A[c], 0.15, 0.15, 0.15, x, h, z, 0, gx, gz);
    }
    var P = [{g: mesh(k, plate), sub: 'mat_grass'}];
    for(i = 0; i < 3; i++) if(A[i].idx.length) P.push({g: mesh(k, A[i]), sub: FLOWER_SUB[i]});
    return P;
  };

  /* marsh is WATER: it lies LEVEL. No gx/gz — the assistant refuses to put one
     on ground that varies more than 0.5 m. */
  AR_EXT.geom.marsh = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = Math.max(0.5, N('w', 60)), d = Math.max(0.5, N('d', 40));
    var dep = Math.max(0.1, N('depth', 0.4));
    var nr = Math.max(0, Math.min(1500, Math.round(N('reeds', 150))));
    var seed = N('seed', 1), rh = Math.max(0.2, N('reed_h', 1.8));
    var t = 0.12, iw = Math.max(0.02, w - 2*t), id = Math.max(0.02, d - 2*t), i;
    var rim = acc();
    boxInto(rim, w, dep, t, 0, -dep, -(d/2 - t/2), 0, 0, 0);
    boxInto(rim, w, dep, t, 0, -dep,  (d/2 - t/2), 0, 0, 0);
    boxInto(rim, t, dep, id, -(w/2 - t/2), -dep, 0, 0, 0, 0);
    boxInto(rim, t, dep, id,  (w/2 - t/2), -dep, 0, 0, 0, 0);
    var bed = acc();
    boxInto(bed, iw, Math.max(0.02, dep - 0.25), id, 0, -dep, 0, 0, 0, 0);
    var wat = acc();
    boxInto(wat, iw, 0.04, id, 0, -0.14, 0, 0, 0, 0);        /* surface at -0.10 */
    var reeds = acc();
    var sw = Math.max(0.01, w - 0.2), sd = Math.max(0.01, d - 0.2);
    for(i = 0; i < nr; i++){
      cylInto(reeds, 0.05, rh, 4, -sw/2 + hash(i, 1, seed) * sw, 0, -sd/2 + hash(i, 2, seed) * sd);
    }
    var P = [{g: mesh(k, rim)},
             {g: mesh(k, bed), sub: 'mat_soil'},
             {g: mesh(k, wat), sub: 'mat_water'}];
    if(reeds.idx.length) P.push({g: mesh(k, reeds), sub: 'mat_foliage'});
    return P;
  };

  AR_EXT.geom.vineyard = function(p, k){
    var N = function(a, b){ return k.num(p[a], b); };
    var w = Math.max(0.5, N('w', 60)), d = Math.max(0.5, N('d', 40));
    var rs = Math.max(0.3, N('row_spacing', 2.5)), h = Math.max(0.2, N('h', 1.8));
    var rot = N('dir', 0) * Math.PI / 180;
    var gx = N('gx', 0), gz = N('gz', 0);
    var zs = rowsOf(d, rs, 0.5), i, j;
    var np = Math.max(2, Math.min(400, Math.floor(w / 6) + 1));
    var pspan = Math.max(0, w - 0.1), pstep = pspan / (np - 1);
    var posts = acc(), vines = acc();
    for(j = 0; j < zs.length; j++){
      boxInto(vines, w, h * 0.6, 0.5, 0, h * 0.4, zs[j], rot, gx, gz);
      for(i = 0; i < np; i++) boxInto(posts, 0.1, h, 0.1, -pspan/2 + i*pstep, 0, zs[j], rot, gx, gz);
    }
    return [{g: mesh(k, posts), sub: 'mat_timber'},
            {g: mesh(k, vines), sub: 'mat_foliage'}];
  };

  AR_EXT.label.crop_field = 'Crop field';
  AR_EXT.label.meadow = 'Meadow';
  AR_EXT.label.marsh = 'Marsh';
  AR_EXT.label.vineyard = 'Vineyard';
})();
