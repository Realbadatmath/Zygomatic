// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ground_v3 — ONE sculpted heightfield per drawing, in the tab (2026-09-07).

   `ground` is the only geometry this family draws: a lattice mesh whose height
   at every vertex is the base roll PLUS the contribution of every `sculpt_*`
   record in the drawing, read through kit.records. The ten sculpt kinds are
   VOID — a thin outline of their footprint at y = 0.05 so the operator can
   select and drag them, and nothing else. That is what makes a valley a valley
   instead of a raised plinth: the cut is a term in the ground's own sum, not a
   solid parked on a lawn.

   THE ARITHMETIC IS A CONTRACT. hash / vnoise / meanderOffset / lakeFactor /
   smoothstep / band / featherOf, the ten sculpt functions, fieldAt, heightAt,
   slopeDeg and colourWeights below are the SAME arithmetic as
   arch_assistant_ext/ground_v3.py and arch_blender_ext/ground_v3.py, line for
   line. Change one copy and you have three landscapes. hash/vnoise are verbatim
   from arch_ext/terrain.js; meanderOffset/lakeFactor verbatim from the river and
   lake kinds, so a sculpt_channel wanders exactly like the river drawn on it.

   Every sculpt function returns [dh, mask]: `dh` metres to add (or, for a SET
   sculpt, the LEVEL), `mask` 0..1 how much of it is felt there. Two sculpts are
   SET: sculpt_flat always, and a sculpt_channel that names level0 AND level1.
   The mask lets the record's own y shift a raise's base without leaving a step
   at the rim, and tells the colour a vertex is in a dune belt or a sea bed.

   Local frame: the record's x/z is the CENTRE in plan, y = 0 is the record's
   base, up is +Y. */
(function(){
  var RES_MAX = 200, RES_MIN = 4, BASE_CELL = 50.0, FEATHER_FRAC = 0.20;
  var COLOUR_BAND = 2.0, SLOPE_BAND = 8.0, WATER_SOIL = 0.30;
  var COLOUR_MATS = ['mat_grass', 'mat_sand', 'mat_rock', 'mat_snow', 'mat_soil'];
  var SAND_KINDS = {sculpt_dunes: 1, sculpt_shelf: 1};

  function num(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }
  function N(p, key, d){ return num((p || {})[key], d); }

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

  /* ── the feather ──────────────────────────────────────────────────────── */
  function clamp(v, lo, hi){ return v < lo ? lo : (v > hi ? hi : v); }
  function smoothstep(t){ t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function band(dist, fe){
    if(fe <= 1e-9) return dist > 0 ? 1 : 0;
    return smoothstep(dist / fe);
  }
  function featherOf(p, size){
    var f = N(p, 'feather', 0);
    if(f <= 0) f = FEATHER_FRAC * size;
    return clamp(f, 0, size);
  }

  /* ── the ten sculpts: [dh, mask] in the sculpt's own LOCAL plan frame ─── */
  function sPeak(p, lx, lz){
    var r = Math.max(0.5, N(p, 'r', 40)), h = N(p, 'h', 30);
    var rug = clamp(N(p, 'rug', 0.45), 0, 0.9), seed = N(p, 'seed', 1);
    var rho = Math.hypot(lx, lz);
    if(rho >= r) return [0, 0];
    var mask = 0.5 * (1 + Math.cos(Math.PI * rho / r)) * band(r - rho, featherOf(p, r));
    if(mask <= 0) return [0, 0];
    var n0 = 1 - rug * vnoise(3.0, 3.0, seed);
    var n = 1 - rug * vnoise((lx / r * 0.5 + 0.5) * 6.0, (lz / r * 0.5 + 0.5) * 6.0, seed);
    return [h * mask * (n0 > 1e-6 ? n / n0 : 1.0), mask];
  }
  function sRidge(p, lx, lz){
    var ln = Math.max(1, N(p, 'len', 120)), w = Math.max(1, N(p, 'w', 40));
    var h = N(p, 'h', 25), rug = clamp(N(p, 'rug', 0.35), 0, 0.9), seed = N(p, 'seed', 1);
    if(Math.abs(lx) > ln / 2 || Math.abs(lz) > w / 2) return [0, 0];
    var t = (lx + ln / 2) / ln;
    var crest = 0.15 * w * (2 * vnoise(t * 4.0, seed, seed) - 1);
    var q = Math.abs(lz - crest) / (w / 2);
    if(q >= 1) return [0, 0];
    var mask = (1 - q) * band(Math.min(lx + ln / 2, ln / 2 - lx), featherOf(p, ln / 2));
    if(mask <= 0) return [0, 0];
    var n = Math.max(0, 1 - rug * vnoise(t * 6.0, (lz / w + 0.5) * 6.0, seed));
    return [h * mask * n, mask];
  }
  function sMesa(p, lx, lz){
    var r = Math.max(0.5, N(p, 'r', 40)), h = N(p, 'h', 25);
    var tr = clamp(N(p, 'top_r', r * 0.7), 0, r * 0.95);
    var rug = clamp(N(p, 'rug', 0.25), 0, 0.9), seed = N(p, 'seed', 1);
    var rho = Math.hypot(lx, lz);
    if(rho >= r) return [0, 0];
    var prof, ero;
    if(rho <= tr){ prof = 1.0; ero = 1.0; }
    else {
      var u = (rho - tr) / (r - tr);
      prof = 1.0 - smoothstep(u);
      ero = Math.max(0, 1 - rug * u * vnoise((lx / r * 0.5 + 0.5) * 6.0, (lz / r * 0.5 + 0.5) * 6.0, seed));
    }
    var mask = prof * band(r - rho, featherOf(p, r));
    if(mask <= 0) return [0, 0];
    return [h * mask * ero, mask];
  }
  function sCut(p, lx, lz){
    var ln = Math.max(1, N(p, 'len', 200)), w = Math.max(1, N(p, 'w', 60));
    var dep = N(p, 'depth', 15);
    var fw = clamp(N(p, 'floor_w', w * 0.25), 0, w * 0.95);
    var pr = clamp(N(p, 'profile', 0), 0, 1);
    if(Math.abs(lx) > ln / 2 || Math.abs(lz) > w / 2) return [0, 0];
    var a = Math.abs(lz), sec;
    if(a <= fw / 2) sec = 1.0;
    else {
      var u = (a - fw / 2) / (w / 2 - fw / 2);
      if(u >= 1) return [0, 0];
      sec = (1 - u) * (1 - pr) + (1 - smoothstep(u)) * pr;
    }
    var mask = sec * band(Math.min(lx + ln / 2, ln / 2 - lx), featherOf(p, ln / 2));
    if(mask <= 0) return [0, 0];
    return [-dep * mask, mask];
  }
  /* A sculpt_channel's SET bed, or null. When a channel names BOTH level0 and
     level1 it stops being a trough dug `depth` below whatever rolls past and
     becomes a bed SET to a straight fall from level0 (at local x = -len/2) to
     level1 (at +len/2) — which is what makes a river read as a river: the water
     is one sloping plane and the bed under it cannot surface through it half way
     down the reach. Without the pair the old behaviour is untouched. */
  function channelLevels(p){
    p = p || {};
    if(p.level0 === undefined || p.level0 === null) return null;
    if(p.level1 === undefined || p.level1 === null) return null;
    return [num(p.level0, 0), num(p.level1, 0)];
  }
  function sChannel(p, lx, lz){
    var ln = Math.max(1, N(p, 'len', 120)), w = Math.max(0.5, N(p, 'w', 12));
    var dep = N(p, 'depth', 2), mea = Math.max(0, N(p, 'meander', 6));
    var seed = N(p, 'seed', 1), bk = Math.max(0.05, N(p, 'bank', 2));
    if(Math.abs(lx) > ln / 2) return [0, 0];
    var t = (lx + ln / 2) / ln;
    var a = Math.abs(lz - meanderOffset(t, mea, seed));
    if(a >= w / 2 + bk) return [0, 0];
    var sec = a <= w / 2 ? 1.0 : 1.0 - smoothstep((a - w / 2) / bk);
    var lv = channelLevels(p);
    if(lv){                                    /* SET: dh is the LEVEL, like sFlat */
      if(sec <= 0) return [0, 0];              /* no end band — reaches of one river */
      return [lv[0] + (lv[1] - lv[0]) * t, sec];   /* share a node level and must butt */
    }
    var mask = sec * band(Math.min(lx + ln / 2, ln / 2 - lx), featherOf(p, ln / 2));
    if(mask <= 0) return [0, 0];
    return [-dep * mask, mask];
  }
  function sBasin(p, lx, lz){
    var rx = Math.max(0.5, N(p, 'rx', 40)), rz = Math.max(0.5, N(p, 'rz', 28));
    var dep = N(p, 'depth', 6), wob = clamp(N(p, 'wobble', 0.25), 0, 0.9);
    var seed = N(p, 'seed', 1), shore = Math.max(0.05, N(p, 'shore', 6));
    var f = lakeFactor(Math.atan2(lz, lx), wob, seed);
    if(f <= 1e-6) return [0, 0];
    var e = Math.hypot(lx / (rx * f), lz / (rz * f));
    if(e >= 1) return [0, 0];
    var sf = clamp(shore / Math.min(rx, rz), 0.02, 0.9);
    var mask = e <= 1 - sf ? 1.0 : 1.0 - smoothstep((e - (1 - sf)) / sf);
    if(mask <= 0) return [0, 0];
    return [-dep * mask, mask];
  }
  function sFlat(p, lx, lz){
    /* the one SET sculpt: dh is the LEVEL. Byte-for-byte the weight
       arch_assistant._sculpt_flat_weight uses, so pad_level() is idempotent. */
    var w = Math.abs(N(p, 'w', 0)), dd = Math.abs(N(p, 'd', 0));
    if(w <= 0 || dd <= 0 || Math.abs(lx) > w / 2 || Math.abs(lz) > dd / 2) return [0, 0];
    var f = N(p, 'feather', 0);
    f = Math.min(Math.max(f, 0), w / 2, dd / 2);
    if(f <= 1e-9) return [N(p, 'level', 0), 1.0];
    var t = Math.min((w / 2 - Math.abs(lx)) / f, (dd / 2 - Math.abs(lz)) / f, 1.0);
    return [N(p, 'level', 0), t * t * (3 - 2 * t)];
  }
  function sStep(p, lx, lz){
    var ln = Math.max(1, N(p, 'len', 120)), h = N(p, 'h', 20), dd = Math.max(1, N(p, 'd', 40));
    var rug = clamp(N(p, 'rug', 0.3), 0, 0.9), seed = N(p, 'seed', 1);
    if(Math.abs(lx) > ln / 2 || Math.abs(lz) > dd / 2) return [0, 0];
    var t = (lx + ln / 2) / ln;
    var fz = 0.06 * dd * (2 * vnoise(t * 5.0, seed, seed) - 1);
    var lift = smoothstep((lz - fz) / Math.max(0.5, 0.08 * dd));
    if(lift <= 0) return [0, 0];
    var mask = lift * band(Math.min(lx + ln / 2, ln / 2 - lx), featherOf(p, ln / 2))
                    * band(dd / 2 - lz, featherOf(p, dd / 2));
    if(mask <= 0) return [0, 0];
    var n = Math.max(0, 1 - rug * vnoise(t * 6.0, (lz / dd + 0.5) * 6.0, seed));
    return [h * mask * n, mask];
  }
  function sDunes(p, lx, lz){
    var w = Math.max(1, N(p, 'w', 160)), dd = Math.max(1, N(p, 'd', 80));
    var h = N(p, 'h', 10), seed = N(p, 'seed', 1);
    var a = N(p, 'dir', 0) * Math.PI / 180.0;
    if(Math.abs(lx) > w / 2 || Math.abs(lz) > dd / 2) return [0, 0];
    var c = Math.cos(a), s = Math.sin(a);
    var rx = lx * c - lz * s, rz = lx * s + lz * c;
    var ridged = 1.0 - Math.abs(2 * vnoise((rx / w + 0.5) * 8.0, (rz / dd + 0.5) * 2.0, seed) - 1);
    var mask = band(Math.min(w / 2 - Math.abs(lx), dd / 2 - Math.abs(lz)), featherOf(p, Math.min(w, dd) / 2));
    if(mask <= 0) return [0, 0];
    return [h * ridged * mask, mask];
  }
  function sShelf(p, lx, lz){
    var w = Math.max(1, N(p, 'w', 200)), dd = Math.max(1, N(p, 'd', 120));
    var dep = N(p, 'depth', 8);
    if(Math.abs(lx) > w / 2 || Math.abs(lz) > dd / 2) return [0, 0];
    var mask = band(Math.min(w / 2 - Math.abs(lx), dd / 2 - Math.abs(lz)), featherOf(p, Math.min(w, dd) / 2));
    if(mask <= 0) return [0, 0];
    return [-dep * mask, mask];
  }
  var SCULPTS = {
    sculpt_peak: sPeak, sculpt_ridge: sRidge, sculpt_mesa: sMesa, sculpt_cut: sCut,
    sculpt_channel: sChannel, sculpt_basin: sBasin, sculpt_flat: sFlat,
    sculpt_step: sStep, sculpt_dunes: sDunes, sculpt_shelf: sShelf
  };

  /* ── H(lx, lz) = base + the sum of the sculpts ────────────────────────── */
  function baseHeight(p, lx, lz){
    var w = Math.max(1, Math.abs(N(p, 'w', 200))), dd = Math.max(1, Math.abs(N(p, 'd', 200)));
    return N(p, 'base', 0) + N(p, 'amp', 1.5) *
           vnoise((lx + w / 2) / BASE_CELL, (lz + dd / 2) / BASE_CELL, N(p, 'seed', 1));
  }

  /* (H, sand) at a point in the GROUND's own local plan frame. The sculpts
     around it are in WORLD coordinates, so the point goes back out to the world
     through the ground's origin and yaw first — the inverse of world_to_local. */
  function fieldAt(p, lx, lz, records, ox, oz, ory){
    var h = baseHeight(p, lx, lz);
    var c = Math.cos(ory || 0), s = Math.sin(ory || 0);
    var wx = (ox || 0) + lx * c + lz * s;
    var wz = (oz || 0) - lx * s + lz * c;
    var sand = 0, flats = null, recs = records || [];
    for(var i = 0; i < recs.length; i++){
      var o = recs[i];
      if(!o || o.hidden) continue;
      var fn = SCULPTS[o.kind];
      if(!fn) continue;
      var sc = num(o.s, 1) || 1;
      var dx = wx - num(o.x, 0), dz = wz - num(o.z, 0);
      var ry = num(o.ry, 0), cc = Math.cos(ry), ss = Math.sin(ry);
      var dm = fn(o.p || {}, (dx * cc - dz * ss) / sc, (dx * ss + dz * cc) / sc);
      if(dm[1] <= 0) continue;
      if(o.kind === 'sculpt_flat' ||           /* a SET sculpt: dm[0] is the LEVEL */
         (o.kind === 'sculpt_channel' && channelLevels(o.p))){
        (flats = flats || []).push(dm); continue;
      }
      h += dm[0] * sc + num(o.y, 0) * dm[1];
      if(SAND_KINDS[o.kind] && dm[1] > sand) sand = dm[1];
    }
    if(flats) for(var j = 0; j < flats.length; j++)     /* SET semantics, applied LAST */
      h = h * (1 - flats[j][1]) + flats[j][0] * flats[j][1];
    return [h, sand];
  }
  function heightAt(p, lx, lz, records, ox, oz, ory){
    return fieldAt(p, lx, lz, records, ox, oz, ory)[0];
  }
  function slopeDeg(hs, n, i, j, stepx, stepz){
    var res = n - 1;
    var i0 = i > 0 ? i - 1 : i, i1 = i < res ? i + 1 : i;
    var j0 = j > 0 ? j - 1 : j, j1 = j < res ? j + 1 : j;
    var gx = (hs[j * n + i1] - hs[j * n + i0]) / Math.max(1e-6, (i1 - i0) * stepx);
    var gz = (hs[j1 * n + i] - hs[j0 * n + i]) / Math.max(1e-6, (j1 - j0) * stepz);
    return Math.atan(Math.hypot(gx, gz)) * 180 / Math.PI;
  }

  /* ── colour: the weights of (grass, sand, rock, snow, soil) ───────────── */
  function colourWeights(h, slope, sand, waterH, snowH, grassMaxSlope){
    var wSand = clamp(sand, 0, 1);
    var wRock = smoothstep((slope - grassMaxSlope) / SLOPE_BAND);
    var wSnow = smoothstep((h - snowH) / COLOUR_BAND);
    var wSoil = 1 - smoothstep((h - (waterH + WATER_SOIL)) / COLOUR_BAND);
    var rest = (1 - wSnow) * (1 - wSoil);
    return [(1 - wSand) * (1 - wRock) * rest,
            wSand * (1 - wRock) * rest,
            wRock * rest,
            wSnow * (1 - wSoil),
            wSoil];
  }

  /* the record whose params ARE p — arGeom is handed the params, but the
     sculpts around it are in world coordinates, so it needs the origin */
  function groundRecord(p, records){
    var recs = records || [], i;
    for(i = 0; i < recs.length; i++) if(recs[i] && recs[i].kind === 'ground' && recs[i].p === p) return recs[i];
    for(i = 0; i < recs.length; i++) if(recs[i] && recs[i].kind === 'ground') return recs[i];
    return null;
  }

  /* ── the one part with geometry in this family ────────────────────────── */
  AR_EXT.geom.ground = function(p, k){
    var T = k.THREE;
    var w = Math.max(1, Math.abs(N(p, 'w', 200))), dd = Math.max(1, Math.abs(N(p, 'd', 200)));
    var res = Math.round(clamp(N(p, 'res', 100), RES_MIN, RES_MAX));
    var n = res + 1, recs = k.records || [];
    var g0 = groundRecord(p, recs);
    var ox = g0 ? num(g0.x, 0) : 0, oz = g0 ? num(g0.z, 0) : 0, ory = g0 ? num(g0.ry, 0) : 0;

    var pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3);
    var hs = new Float32Array(n * n), sd = new Float32Array(n * n);
    var i, j, idx;
    for(j = 0; j < n; j++){
      var lz = -dd / 2 + j / res * dd;
      for(i = 0; i < n; i++){
        var lx = -w / 2 + i / res * w;
        var hsand = fieldAt(p, lx, lz, recs, ox, oz, ory);
        idx = j * n + i;
        hs[idx] = hsand[0]; sd[idx] = hsand[1];
        pos[idx * 3] = lx; pos[idx * 3 + 1] = hsand[0]; pos[idx * 3 + 2] = lz;
      }
    }
    var pal = [], m;
    for(m = 0; m < COLOUR_MATS.length; m++) pal.push(k.matRGB ? k.matRGB(COLOUR_MATS[m]) : [0.6, 0.6, 0.6]);
    var waterH = N(p, 'water_h', -0.15), snowH = N(p, 'snow_h', 60), gms = N(p, 'grass_max_slope', 32);
    var stepx = w / res, stepz = dd / res;
    for(j = 0; j < n; j++) for(i = 0; i < n; i++){
      idx = j * n + i;
      var ws = colourWeights(hs[idx], slopeDeg(hs, n, i, j, stepx, stepz), sd[idx], waterH, snowH, gms);
      var r = 0, gg = 0, b = 0;
      for(m = 0; m < 5; m++){ r += ws[m] * pal[m][0]; gg += ws[m] * pal[m][1]; b += ws[m] * pal[m][2]; }
      col[idx * 3] = r; col[idx * 3 + 1] = gg; col[idx * 3 + 2] = b;
    }
    /* winding: (v00, v01, v10) and (v10, v01, v11) both face +Y */
    var big = n * n > 65535;
    var ind = big ? new Uint32Array(res * res * 6) : new Uint16Array(res * res * 6), c = 0;
    for(j = 0; j < res; j++) for(i = 0; i < res; i++){
      var v00 = j * n + i, v10 = v00 + 1, v01 = v00 + n, v11 = v01 + 1;
      ind[c++] = v00; ind[c++] = v01; ind[c++] = v10;
      ind[c++] = v10; ind[c++] = v01; ind[c++] = v11;
    }
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
    g.setIndex(new T.BufferAttribute(ind, 1));
    g.computeVertexNormals();
    return [{g: g, vcolors: col}];
  };

  /* ── the ten VOID sculpts: an outline of the footprint, nothing else ──── */
  var Y = 0.05;
  function rect(T, w, d){
    var hw = w / 2, hd = d / 2;
    var pts = [-hw, Y, -hd,  hw, Y, -hd,   hw, Y, -hd,  hw, Y, hd,
                hw, Y,  hd, -hw, Y,  hd,  -hw, Y,  hd, -hw, Y, -hd];
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
    return [{g: g, line: 1}];
  }
  function ellipse(T, rx, rz, steps){
    var pts = [], i, a;
    steps = steps || 48;
    for(i = 0; i <= steps; i++){ a = i / steps * Math.PI * 2; pts.push(rx * Math.cos(a), Y, rz * Math.sin(a)); }
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
    return [{g: g, line: 1, strip: 1}];
  }
  AR_EXT.geom.sculpt_peak = function(p, k){ var r = Math.max(0.5, N(p, 'r', 40)); return ellipse(k.THREE, r, r); };
  AR_EXT.geom.sculpt_mesa = function(p, k){ var r = Math.max(0.5, N(p, 'r', 40)); return ellipse(k.THREE, r, r); };
  AR_EXT.geom.sculpt_basin = function(p, k){
    return ellipse(k.THREE, Math.max(0.5, N(p, 'rx', 40)), Math.max(0.5, N(p, 'rz', 28)));
  };
  AR_EXT.geom.sculpt_ridge = function(p, k){ return rect(k.THREE, Math.max(1, N(p, 'len', 120)), Math.max(1, N(p, 'w', 40))); };
  AR_EXT.geom.sculpt_cut = function(p, k){ return rect(k.THREE, Math.max(1, N(p, 'len', 200)), Math.max(1, N(p, 'w', 60))); };
  AR_EXT.geom.sculpt_channel = function(p, k){
    return rect(k.THREE, Math.max(1, N(p, 'len', 120)),
                Math.max(0.5, N(p, 'w', 12)) + 2 * Math.max(0.05, N(p, 'bank', 2)) + 2 * Math.max(0, N(p, 'meander', 6)));
  };
  AR_EXT.geom.sculpt_flat = function(p, k){ return rect(k.THREE, Math.max(0.1, Math.abs(N(p, 'w', 40))), Math.max(0.1, Math.abs(N(p, 'd', 40)))); };
  AR_EXT.geom.sculpt_step = function(p, k){ return rect(k.THREE, Math.max(1, N(p, 'len', 120)), Math.max(1, N(p, 'd', 40))); };
  AR_EXT.geom.sculpt_dunes = function(p, k){ return rect(k.THREE, Math.max(1, N(p, 'w', 160)), Math.max(1, N(p, 'd', 80))); };
  AR_EXT.geom.sculpt_shelf = function(p, k){ return rect(k.THREE, Math.max(1, N(p, 'w', 200)), Math.max(1, N(p, 'd', 120))); };

  AR_EXT.label.ground = 'Ground';
  AR_EXT.label.sculpt_peak = 'Sculpt: peak';
  AR_EXT.label.sculpt_ridge = 'Sculpt: ridge';
  AR_EXT.label.sculpt_mesa = 'Sculpt: mesa';
  AR_EXT.label.sculpt_cut = 'Sculpt: valley';
  AR_EXT.label.sculpt_channel = 'Sculpt: river bed';
  AR_EXT.label.sculpt_basin = 'Sculpt: lake bed';
  AR_EXT.label.sculpt_flat = 'Sculpt: level pad';
  AR_EXT.label.sculpt_step = 'Sculpt: escarpment';
  AR_EXT.label.sculpt_dunes = 'Sculpt: dunes';
  AR_EXT.label.sculpt_shelf = 'Sculpt: sea bed';

  /* the family's own arithmetic, exposed for tests_arch_ext/test_ground_v3.py */
  AR_EXT.ground_v3 = {vnoise: vnoise, heightAt: heightAt, fieldAt: fieldAt,
                      colourWeights: colourWeights, slopeDeg: slopeDeg, sculpts: SCULPTS,
                      baseHeight: baseHeight, COLOUR_MATS: COLOUR_MATS,
                      channelLevels: channelLevels};
})();
