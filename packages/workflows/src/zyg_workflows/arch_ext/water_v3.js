// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* water_v3 — the water that SITS ON the v3 sculpted bed, in the tab (2026-09-07).

   Three kinds, water only, no bed: the bed is a sculpt of the ONE ground
   (sculpt_basin / sculpt_channel / sculpt_shelf) and the v1 lake/river/sea
   kinds' own bowls and slabs would read as plinths on top of it.

     water_body   {rx, rz, wobble, seed, seg}    a lake / pond surface
     water_path   {len, w, meander, seed, seg,   a river / stream reach surface
                   level0, level1}               (the pair makes it SLOPE)
     water_plane  {w, d, wave, seed, res}        the sea surface

   water_path and water_plane are SKINS: WATER_T = 0.02 m from the top face to
   the bottom face, so a record's bbox height is 0.02 (plus the swell or the
   fall) and the surface reads as water rather than as a block of ice.
   water_body is a single fan — see discFan. Every part carries sub: 'mat_water',
   and arMat gives every preset side: THREE.DoubleSide with transparent/opacity
   from the preset (mat_water is op 0.6) — so these are two-sided translucent
   surfaces you can see the bed through, from above and from underneath.

   THE SHORELINE IS A CONTRACT. hash/vnoise are verbatim from arch_ext/terrain.js;
   meanderOffset/lakeFactor verbatim from arch_ext/ground_v3.js. A water_body over
   a sculpt_basin of the same rx/rz/wobble/seed has EXACTLY the basin's rim; a
   water_path over a sculpt_channel of the same len/meander/seed lies exactly in
   its trough. Four copies of one arithmetic: this file, arch_assistant_ext/
   water_v3.py, arch_blender_ext/water_v3.py and ground_v3.

   Local frame: the record's x/z is the CENTRE in plan, the water SURFACE is
   y = 0 (the record's own y is the water level), +Y is up. */
(function(){
  var WATER_T = 0.02;

  function num(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }
  function N(p, key, d){ return num((p || {})[key], d); }
  function clamp(v, lo, hi){ return v < lo ? lo : (v > hi ? hi : v); }

  /* ── the shared noise ─────────────────────────────────────────────────── */
  function hash(ix, iy, seed){
    var v = Math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453;
    return v - Math.floor(v);
  }
  function vnoise(u, v, seed){
    var ix = Math.floor(u), iy = Math.floor(v), fx = u - ix, fy = v - iy;
    var a = hash(ix, iy, seed), b = hash(ix + 1, iy, seed);
    var c = hash(ix, iy + 1, seed), e = hash(ix + 1, iy + 1, seed);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy;
  }
  function meanderOffset(t, meander, seed){
    return meander * Math.sin(Math.PI * t) * (0.6 * Math.sin(2 * Math.PI * t * 1.5)
           + 0.4 * (2 * vnoise(t * 4, seed, seed) - 1));
  }
  function lakeFactor(a, wobble, seed){
    return 1 + wobble * (2 * vnoise(Math.cos(a) * 2 + 2, Math.sin(a) * 2 + 2, seed) - 1);
  }

  /* ── mesh helpers ─────────────────────────────────────────────────────── */
  function mesh(THREE, pos, idx){
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }

  /* THE LAKE IS ONE FAN, NOT A DISC OF ICE.

     It used to be a closed skin: a top fan at y = 0, a second fan at y = -T and
     a rim skirt. Two fans 0.02 m apart, both wound as if their centre triangle
     faced the other way, gave the studio a radial pattern of dark and light
     wedges — a lake that read as a paper windmill. There is nothing for the
     underside to do either: the record's own y is the water level, the basin bed
     is `shore` metres lower, and arMat already gives mat_water DoubleSide, so one
     surface is visible from above AND from underneath.

     So: ONE fan, `ring.length` triangles, wound (centre, ring[i], ring[i+1]) so
     computeVertexNormals gives every one of them +Y, at y = +WATER_T — a
     centimetre clear of the record's datum, which is also clear of anything else
     that was placed at exactly the water level. */
  function discFan(THREE, ring){
    var pos = [], idx = [], L = ring.length, i, cx = 0, cz = 0;
    for(i = 0; i < L; i++){ cx += ring[i][0]; cz += ring[i][1]; }
    cx /= L; cz /= L;
    pos.push(cx, WATER_T, cz);                     /* 0 = the centre */
    for(i = 0; i < L; i++) pos.push(ring[i][0], WATER_T, ring[i][1]);
    for(i = 0; i < L; i++) idx.push(0, 1 + i, 1 + (i + 1) % L);
    return mesh(THREE, pos, idx);
  }

  /* An open ribbon skin: `left` and `right` are two [[x, z], ...] banks of the
     same length and `ys` the surface height at each of the n stations. Top at
     ys[i], bottom at ys[i] - T, skirts on both banks and both ends, so a reach
     seen end-on is still a closed surface. ys is what lets a reach FALL: a river
     held at one level goes under the valley's own roll half way along. */
  function ribbonSkin(THREE, left, right, ys){
    var pos = [], idx = [], n = left.length, i;
    var t0 = pos.length / 3;
    for(i = 0; i < n; i++){ pos.push(left[i][0], ys[i], left[i][1]); pos.push(right[i][0], ys[i], right[i][1]); }
    var b0 = pos.length / 3;
    for(i = 0; i < n; i++){ pos.push(left[i][0], ys[i] - WATER_T, left[i][1]); pos.push(right[i][0], ys[i] - WATER_T, right[i][1]); }
    for(i = 0; i < n - 1; i++){
      var tl = t0 + 2 * i, tr = tl + 1, tl2 = tl + 2, tr2 = tl + 3;
      var bl = b0 + 2 * i, br = bl + 1, bl2 = bl + 2, br2 = bl + 3;
      idx.push(tl, tr, tr2, tl, tr2, tl2);         /* top */
      idx.push(bl, br2, br, bl, bl2, br2);         /* bottom */
      idx.push(tl, tl2, bl2, tl, bl2, bl);         /* left bank */
      idx.push(tr, br, br2, tr, br2, tr2);         /* right bank */
    }
    var e = 2 * (n - 1);
    idx.push(t0, b0, b0 + 1, t0, b0 + 1, t0 + 1);                          /* upstream cap */
    idx.push(t0 + e, t0 + e + 1, b0 + e + 1, t0 + e, b0 + e + 1, b0 + e);  /* downstream cap */
    return mesh(THREE, pos, idx);
  }

  /* A rectangular lattice skin with a swell: the old `sea` surface, with the
     -0.3 baseline taken OUT (the record's y is the sea level now) and with no
     bed slab under it (the bed is a sculpt_shelf). */
  function sheetSkin(THREE, w, dd, res, hfn){
    var pos = [], idx = [], i, j, nx = res + 1, H = [];
    for(j = 0; j <= res; j++){ H.push([]); for(i = 0; i <= res; i++) H[j].push(hfn(i, j)); }
    var t0 = pos.length / 3;
    for(j = 0; j <= res; j++) for(i = 0; i <= res; i++)
      pos.push(-w / 2 + i / res * w, H[j][i], -dd / 2 + j / res * dd);
    var b0 = pos.length / 3;
    for(j = 0; j <= res; j++) for(i = 0; i <= res; i++)
      pos.push(-w / 2 + i / res * w, H[j][i] - WATER_T, -dd / 2 + j / res * dd);
    for(j = 0; j < res; j++) for(i = 0; i < res; i++){
      var a = t0 + j * nx + i, b = a + 1, c = a + nx + 1, e = a + nx;
      idx.push(a, b, c, a, c, e);
      var A = b0 + j * nx + i, B = A + 1, C = A + nx + 1, E = A + nx;
      idx.push(A, C, B, A, E, C);
    }
    function rim(p, q){ idx.push(p, q, q - t0 + b0, p, q - t0 + b0, p - t0 + b0); }
    for(i = 0; i < res; i++){
      rim(t0 + i, t0 + i + 1);                                       /* j = 0 edge */
      rim(t0 + res * nx + i + 1, t0 + res * nx + i);                 /* j = res edge */
      rim(t0 + (i + 1) * nx, t0 + i * nx);                           /* i = 0 edge */
      rim(t0 + i * nx + res, t0 + (i + 1) * nx + res);               /* i = res edge */
    }
    return mesh(THREE, pos, idx);
  }

  /* ── the three kinds ──────────────────────────────────────────────────── */
  function bodyRing(p){
    var rx = Math.max(0.5, N(p, 'rx', 30)), rz = Math.max(0.5, N(p, 'rz', 20));
    var wob = clamp(N(p, 'wobble', 0.25), 0, 0.9), seed = N(p, 'seed', 1);
    var seg = clamp(Math.round(N(p, 'seg', 48)), 8, 256), ring = [], i;
    for(i = 0; i < seg; i++){
      var a = 2 * Math.PI * i / seg, m = lakeFactor(a, wob, seed);
      ring.push([rx * Math.cos(a) * m, -rz * Math.sin(a) * m]);
    }
    return ring;
  }

  function pathEdges(p){
    var ln = Math.max(1, N(p, 'len', 60)), w = Math.max(0.2, N(p, 'w', 8));
    var mea = Math.max(0, N(p, 'meander', 6)), seed = N(p, 'seed', 1);
    var seg = clamp(Math.round(N(p, 'seg', 24)), 2, 200), left = [], right = [], i;
    for(i = 0; i <= seg; i++){
      var t = i / seg, x = -ln / 2 + t * ln, zc = meanderOffset(t, mea, seed);
      left.push([x, zc - w / 2]);
      right.push([x, zc + w / 2]);
    }
    return [left, right];
  }

  /* A water_path's FALL, or null: [level0, level1] is the surface height at the
     start (local x = -len/2) and the end (+len/2), in the RECORD's own frame —
     its y is the datum, so carve_river writes level0 = 0 and level1 = the drop
     to the next node. Without both the reach is flat, as it always was. The bed
     under it is a SET sculpt_channel of the same two levels, so they fall
     together: ground_v3.channelLevels. */
  function pathLevels(p){
    p = p || {};
    if(p.level0 === undefined || p.level0 === null) return null;
    if(p.level1 === undefined || p.level1 === null) return null;
    return [num(p.level0, 0), num(p.level1, 0)];
  }
  function pathY(p, t){
    var lv = pathLevels(p);
    return lv ? lv[0] + (lv[1] - lv[0]) * t : 0;
  }

  AR_EXT.geom.water_body = function(p, k){
    return [{g: discFan(k.THREE, bodyRing(p)), sub: 'mat_water'}];
  };

  AR_EXT.geom.water_path = function(p, k){
    var e = pathEdges(p), n = e[0].length, ys = [], i;
    for(i = 0; i < n; i++) ys.push(pathY(p, n > 1 ? i / (n - 1) : 0));
    return [{g: ribbonSkin(k.THREE, e[0], e[1], ys), sub: 'mat_water'}];
  };

  AR_EXT.geom.water_plane = function(p, k){
    var w = Math.max(1, N(p, 'w', 200)), dd = Math.max(1, N(p, 'd', 120));
    var wave = Math.max(0, N(p, 'wave', 0.15)), seed = N(p, 'seed', 1);
    var res = clamp(Math.round(N(p, 'res', 24)), 2, 200);
    return [{g: sheetSkin(k.THREE, w, dd, res, function(i, j){
      return wave * (2 * vnoise(i / res * 8, j / res * 8, seed) - 1);
    }), sub: 'mat_water'}];
  };

  AR_EXT.label.water_body = 'Water: lake surface';
  AR_EXT.label.water_path = 'Water: river surface';
  AR_EXT.label.water_plane = 'Water: sea surface';

  /* the family's arithmetic, for anything that has to agree with it */
  AR_EXT.water_v3 = {vnoise: vnoise, meanderOffset: meanderOffset, lakeFactor: lakeFactor,
                     bodyRing: bodyRing, pathEdges: pathEdges, WATER_T: WATER_T,
                     pathLevels: pathLevels, pathY: pathY};
})();
