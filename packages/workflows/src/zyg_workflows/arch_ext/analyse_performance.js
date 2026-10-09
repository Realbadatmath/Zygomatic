// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* analyse_performance — Analyse ▸ Daylight, Energy, U-value, Structure, Code check.

   Five ACTIONS behind five dock icons (a_daylight, a_energy, a_uvalue, a_struct,
   a_code). The first four also register themselves on AR_EXT.analyses — the
   studio-wide registry of "a check that can be run over the drawing" — and
   a_code runs EVERY entry of that registry, whichever family put it there, in
   one sheet.

   A registry entry is
       {id, name, family, run(opt) -> {rows, issues, summary, ...}}
   and an issue is
       {severity: 'error'|'warning'|'info', text, ids: [record ids]}
   but a_code reads foreign entries defensively (a bare function, `fn`/`check`
   instead of `run`, `problems`/`items` instead of `issues`, a plain string
   result) so a sibling family with a slightly different idea still shows up.

   Everything here is READ-ONLY on the document except the U-value layer editor
   (which arPush()es before it writes AR.doc.ext.analyse_performance) — so no
   report costs you an undo step. The daylight overlay is scene furniture, not
   records: it is removed when the sheet closes.

   Document state: AR.doc.ext.analyse_performance = {constructions: {...},
   degree_days: 2800}. Nothing is written there until you edit a layer.       */
(function(){
  if(!window.AR_EXT) return;
  AR_EXT.analyses = AR_EXT.analyses || [];

  var AP = window.analyse_performance = window.analyse_performance || {};
  var FAM = 'analyse_performance';

  /* ── small helpers ──────────────────────────────────────────────────── */
  function N(v, d){ return (typeof arNum === 'function') ? arNum(v, d) : (isFinite(parseFloat(v)) ? parseFloat(v) : d); }
  function E(s){ return (typeof esc === 'function') ? esc(String(s)) : String(s).replace(/[&<>"]/g, function(c){
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]; }); }
  function f(v, n){ var d = (n === undefined ? 2 : n); return (Math.round(v * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d); }
  function objs(){ return (window.AR && AR.objs) ? AR.objs : []; }
  function isWall(o){ return o.kind === 'wall' || o.kind === 'partition'; }
  function isOpening(k){ return (typeof arIsOpening === 'function') ? arIsOpening(k)
    : (k === 'door' || k === 'double_door' || k === 'window' || k === 'opening'); }
  function isRoof(o){ return String(o.kind).lastIndexOf('roof_', 0) === 0; }
  function storeyH(){ return (window.AR && AR.defaults && N(AR.defaults.wall_h, 2.7)) || 2.7; }
  function storeyOf(o){ return Math.round(N(o.y, 0) / storeyH()); }
  function cellOf(x, z){ try { return arCellName(x, z); } catch(e){ return f(x, 1) + ',' + f(z, 1); } }

  /* the two ends of a wall on the plan. THREE rotation.y = ry sends local +X
     to (cos ry, -sin ry), so the ends sit at +-len/2 along that. */
  function wallEnds(w){
    var L = N(w.p.len, 4), c = Math.cos(w.ry || 0), s = Math.sin(w.ry || 0);
    return [{x: w.x + L / 2 * c, z: w.z - L / 2 * s}, {x: w.x - L / 2 * c, z: w.z + L / 2 * s}];
  }
  /* the wall's outward-ish normal on the plan: local +Z is (sin ry, cos ry) */
  function wallNormal(w){ return {x: Math.sin(w.ry || 0), z: Math.cos(w.ry || 0)}; }

  function shoelace(pts){
    var a = 0;
    for(var i = 0; i < pts.length; i++){
      var p = pts[i], q = pts[(i + 1) % pts.length];
      a += p.x * q.z - q.x * p.z;
    }
    return a / 2;
  }
  function perimeter(pts){
    var L = 0;
    for(var i = 0; i < pts.length; i++){
      var p = pts[i], q = pts[(i + 1) % pts.length];
      L += Math.sqrt((p.x - q.x) * (p.x - q.x) + (p.z - q.z) * (p.z - q.z));
    }
    return L;
  }
  function centroid(pts){
    var x = 0, z = 0;
    pts.forEach(function(p){ x += p.x; z += p.z; });
    return {x: x / pts.length, z: z / pts.length};
  }
  function ptInPoly(pts, x, z){
    var inside = false;
    for(var i = 0, j = pts.length - 1; i < pts.length; j = i++){
      var a = pts[i], b = pts[j];
      if(((a.z > z) !== (b.z > z)) && (x < (b.x - a.x) * (z - a.z) / (b.z - a.z) + a.x)) inside = !inside;
    }
    return inside;
  }
  function distToSeg(x, z, a, b){
    var dx = b.x - a.x, dz = b.z - a.z, L2 = dx * dx + dz * dz;
    var t = L2 > 1e-9 ? ((x - a.x) * dx + (z - a.z) * dz) / L2 : 0;
    t = Math.max(0, Math.min(1, t));
    var px = a.x + t * dx, pz = a.z + t * dz;
    return Math.sqrt((x - px) * (x - px) + (z - pz) * (z - pz));
  }
  function distToPoly(pts, x, z){
    var m = 1e9;
    for(var i = 0; i < pts.length; i++) m = Math.min(m, distToSeg(x, z, pts[i], pts[(i + 1) % pts.length]));
    return m;
  }

  /* ── rooms ──────────────────────────────────────────────────────────────
     Three sources, in order: another family's rooms() if that family's JS is
     loaded, then `zone` records carrying a point list, then our own planar
     face finder over the closed wall loops of each storey. */

  function normPts(raw, rec){
    var out = [];
    (raw || []).forEach(function(p){
      var lx, lz;
      if(Array.isArray(p)){ lx = N(p[0], NaN); lz = N(p[1], NaN); }
      else if(p && typeof p === 'object'){ lx = N(p.x, NaN); lz = N(p.z !== undefined ? p.z : p.y, NaN); }
      if(!isFinite(lx) || !isFinite(lz)) return;
      if(rec){
        var c = Math.cos(rec.ry || 0), s = Math.sin(rec.ry || 0);
        out.push({x: rec.x + lx * c + lz * s, z: rec.z - lx * s + lz * c});
      } else out.push({x: lx, z: lz});
    });
    return out;
  }

  function zoneRooms(){
    var out = [];
    objs().forEach(function(o){
      if(o.hidden) return;
      if(String(o.kind) !== 'zone' && String(o.kind).lastIndexOf('zone', 0) !== 0) return;
      var pts = normPts(o.p && (o.p.pts || o.p.points), o);
      if(pts.length < 3) return;
      if(shoelace(pts) < 0) pts = pts.slice().reverse();
      out.push({id: o.id, name: String(o.name || (o.p && o.p.name) || 'Zone'), pts: pts,
                area: Math.abs(shoelace(pts)), perim: perimeter(pts), storey: storeyOf(o),
                y: N(o.y, 0), walls: []});
    });
    /* the walls that bound a zone: same storey, centre within 1 m of the outline */
    var walls = objs().filter(function(o){ return !o.hidden && isWall(o); });
    out.forEach(function(r){
      r.walls = walls.filter(function(w){ return storeyOf(w) === r.storey && distToPoly(r.pts, w.x, w.z) < 1.0; });
    });
    return out;
  }

  /* Planar face traversal. Half-edges around each node are sorted by angle;
     the successor of a half-edge is the edge BEFORE its twin in that ascending
     order (i.e. the next one clockwise), which walks every bounded face with
     its interior on the left — so a bounded face has a POSITIVE shoelace and
     the unbounded outer face a negative one. Dead-end walls are walked out and
     back and contribute no area. */
  function loopsOf(walls, storey){
    var TOL = 0.35, nodes = [];
    function nodeAt(p){
      for(var i = 0; i < nodes.length; i++){
        var dx = nodes[i].x - p.x, dz = nodes[i].z - p.z;
        if(dx * dx + dz * dz < TOL * TOL) return i;
      }
      nodes.push({x: p.x, z: p.z});
      return nodes.length - 1;
    }
    var half = [];
    walls.forEach(function(w){
      var e = wallEnds(w), a = nodeAt(e[0]), b = nodeAt(e[1]);
      if(a === b) return;
      var i = half.length;
      half.push({from: a, to: b, w: w, twin: i + 1});
      half.push({from: b, to: a, w: w, twin: i});
    });
    if(!half.length) return [];
    half.forEach(function(h){
      h.ang = Math.atan2(nodes[h.to].z - nodes[h.from].z, nodes[h.to].x - nodes[h.from].x);
    });
    var around = {};
    half.forEach(function(h, i){ (around[h.from] = around[h.from] || []).push(i); });
    Object.keys(around).forEach(function(k){
      around[k].sort(function(a, b){ return half[a].ang - half[b].ang; });
      around[k].forEach(function(i, pos){ half[i].pos = pos; });
    });
    function next(i){
      var t = half[i].twin, ring = around[half[t].from];
      return ring[(half[t].pos - 1 + ring.length) % ring.length];
    }
    var seen = {}, rooms = [], n = 0;
    for(var s = 0; s < half.length; s++){
      if(seen[s]) continue;
      var cyc = [], i = s, guard = 0;
      while(!seen[i] && guard++ < 4000){ seen[i] = 1; cyc.push(i); i = next(i); }
      if(i !== s || cyc.length < 3) continue;
      var pts = cyc.map(function(h){ return {x: nodes[half[h].from].x, z: nodes[half[h].from].z}; });
      var A = shoelace(pts);
      if(A < 0.5) continue;                       /* the outer face, or noise */
      n++;
      var ws = cyc.map(function(h){ return half[h].w; });
      rooms.push({id: 'room' + storey + '_' + n, name: 'Room ' + n + ' @' + cellOf(centroid(pts).x, centroid(pts).z),
                  pts: pts, area: A, perim: perimeter(pts), storey: storey,
                  y: storey * storeyH(), walls: ws});
    }
    return rooms;
  }

  function wallLoops(){
    var walls = objs().filter(function(o){ return !o.hidden && isWall(o) && N(o.p.len, 0) > 0.05; });
    var by = {}, out = [];
    walls.forEach(function(w){ var k = storeyOf(w); (by[k] = by[k] || []).push(w); });
    Object.keys(by).sort(function(a, b){ return a - b; }).forEach(function(k){
      out = out.concat(loopsOf(by[k], parseInt(k, 10)));
    });
    return out;
  }

  function foreignRooms(){
    var AN = window.analyse_planning;
    if(!AN || typeof AN.rooms !== 'function') return null;
    var r;
    try { r = AN.rooms(); } catch(e){ return null; }
    var list = Array.isArray(r) ? r : (r && (r.rooms || r.list)) || [];
    var out = [];
    list.forEach(function(x, i){
      var pts = normPts(x.pts || x.points || x.poly || x.outline, null);
      if(pts.length < 3) return;
      if(shoelace(pts) < 0) pts = pts.slice().reverse();
      var ws = (x.walls || []).map(function(w){
        return (w && w.kind) ? w : (typeof arFind === 'function' ? arFind(String(w)) : null); }).filter(Boolean);
      var st = x.storey !== undefined ? x.storey : storeyOf({y: N(x.y, 0)});
      if(!ws.length){
        var c = centroid(pts);
        ws = objs().filter(function(w){ return !w.hidden && isWall(w) && storeyOf(w) === st
          && distToPoly(pts, w.x, w.z) < 1.0; });
      }
      out.push({id: String(x.id || ('ap_room' + i)), name: String(x.name || x.label || ('Room ' + (i + 1))),
                pts: pts, area: N(x.area, Math.abs(shoelace(pts))), perim: N(x.perim, N(x.perimeter, perimeter(pts))),
                storey: st, y: N(x.y, st * storeyH()), walls: ws});
    });
    return out.length ? out : null;
  }

  /** Every enclosed space of the drawing, and where the list came from. */
  AP.rooms = function(){
    var fr = foreignRooms();
    if(fr) return {rooms: fr, source: 'window.analyse_planning.rooms()'};
    var zr = zoneRooms();
    if(zr.length) return {rooms: zr, source: 'zone records (p.pts)'};
    return {rooms: wallLoops(), source: 'closed wall loops per storey (own loop finder)'};
  };

  /* which walls are interior (a room on BOTH sides) — everything else is envelope */
  function wallRoomCount(rooms){
    var c = {};
    rooms.forEach(function(r){ (r.walls || []).forEach(function(w){ if(w) c[w.id] = (c[w.id] || 0) + 1; }); });
    return c;
  }

  /* openings hosted by a wall — the same test arSyncHoles uses, without writing */
  function openingsOf(walls){
    var map = {};
    walls.forEach(function(w){ map[w.id] = []; });
    objs().forEach(function(o){
      if(o.hidden || !isOpening(o.kind)) return;
      var best = null, bd = 1e9;
      walls.forEach(function(w){
        var len = N(w.p.len, 4), t = N(w.p.t, 0.24), h = N(w.p.h, 2.7);
        if(o.y < w.y - 0.05 || o.y > w.y + h - 0.05) return;
        var c = Math.cos(-(w.ry || 0)), s = Math.sin(-(w.ry || 0));
        var dx = o.x - w.x, dz = o.z - w.z, lx = dx * c - dz * s, lz = dx * s + dz * c;
        if(Math.abs(lx) > len / 2 + 0.001) return;
        var d = Math.abs(lz);
        if(d > t / 2 + 0.45) return;
        if(d < bd){ bd = d; best = w; }
      });
      if(best) map[best.id].push(o);
    });
    return map;
  }

  /* ── constructions and U-values ─────────────────────────────────────────
     U = 1 / (Rsi + sum d/lambda + Rse); a layer may instead carry a fixed
     thermal resistance `r` (glazing units, cavities, membranes). */
  var RSI = 0.13, RSE = 0.04;
  var DEFAULT_CONS = {
    mat_concrete: {label: 'Concrete wall, insulated (default wall)', type: 'wall', layers: [
      {name: 'plaster', d: 0.012, lambda: 0.51},
      {name: 'insulation (mineral wool)', d: 0.12, lambda: 0.035},
      {name: 'concrete', d: 0.24, lambda: 2.0}]},
    mat_brick: {label: 'Brick cavity wall', type: 'wall', layers: [
      {name: 'plaster', d: 0.012, lambda: 0.51},
      {name: 'blockwork', d: 0.10, lambda: 1.13},
      {name: 'insulation (cavity fill)', d: 0.10, lambda: 0.035},
      {name: 'facing brick', d: 0.10, lambda: 0.77}]},
    mat_blockwork: {label: 'Blockwork wall', type: 'wall', layers: [
      {name: 'plaster', d: 0.012, lambda: 0.51},
      {name: 'insulation', d: 0.10, lambda: 0.035},
      {name: 'blockwork', d: 0.20, lambda: 1.13}]},
    mat_timber: {label: 'Timber frame wall', type: 'wall', layers: [
      {name: 'plasterboard', d: 0.0125, lambda: 0.25},
      {name: 'insulation between studs', d: 0.14, lambda: 0.038},
      {name: 'sheathing', d: 0.018, lambda: 0.13},
      {name: 'timber cladding', d: 0.022, lambda: 0.13}]},
    mat_glass: {label: 'Double glazing unit', type: 'glass', layers: [
      {name: 'sealed double glazed unit (argon, low-e)', r: 0.739}]},
    roof: {label: 'Warm flat/pitched roof', type: 'roof', layers: [
      {name: 'roof covering', d: 0.01, lambda: 0.23},
      {name: 'insulation (PIR)', d: 0.22, lambda: 0.035},
      {name: 'deck', d: 0.018, lambda: 0.13}]},
    floor: {label: 'Insulated ground slab', type: 'floor', layers: [
      {name: 'screed', d: 0.05, lambda: 1.15},
      {name: 'insulation', d: 0.16, lambda: 0.035},
      {name: 'concrete slab', d: 0.20, lambda: 2.0}]}
  };
  /* Bouwbesluit 2021, nieuwbouw (NL) — maximum U per element, W/m2K */
  var NL_LIMIT = {wall: 0.21, roof: 0.16, floor: 0.21, glass: 1.65};

  function extBag(){ return (window.AR && AR.doc && AR.doc.ext && AR.doc.ext[FAM]) || {}; }

  function normLayers(v){
    var arr = Array.isArray(v) ? v : (v && Array.isArray(v.layers) ? v.layers : null);
    if(!arr) return null;
    return arr.map(function(l){
      return {name: String((l && l.name) || 'layer'),
              d: (l && l.d !== undefined) ? N(l.d, 0) : undefined,
              lambda: (l && l.lambda !== undefined) ? N(l.lambda, 1) : undefined,
              r: (l && l.r !== undefined) ? N(l.r, 0) : undefined};
    });
  }

  /** The live construction table: defaults, overridden by AR.doc.ext. No write. */
  AP.constructions = function(){
    var out = {}, over = extBag().constructions || {};
    Object.keys(DEFAULT_CONS).forEach(function(k){
      out[k] = {label: DEFAULT_CONS[k].label, type: DEFAULT_CONS[k].type,
                layers: DEFAULT_CONS[k].layers.map(function(l){ return {name: l.name, d: l.d, lambda: l.lambda, r: l.r}; }),
                edited: false};
    });
    Object.keys(over).forEach(function(k){
      var L = normLayers(over[k]);
      if(!L) return;
      out[k] = {label: (over[k] && over[k].label) || (out[k] && out[k].label) || k,
                type: (over[k] && over[k].type) || (out[k] && out[k].type) || 'wall',
                layers: L, edited: true};
    });
    Object.keys(out).forEach(function(k){ out[k].u = uOf(out[k].layers); out[k].key = k; });
    return out;
  };

  function uOf(layers){
    var R = RSI + RSE;
    (layers || []).forEach(function(l){
      if(l.r !== undefined && isFinite(l.r)) R += Math.max(0, l.r);
      else if(l.d !== undefined && l.lambda) R += Math.max(0, l.d) / Math.max(0.001, l.lambda);
    });
    return 1 / Math.max(0.02, R);
  }
  AP.uOf = uOf;

  /* which construction applies to a record */
  function consKey(o, cons){
    if(isOpening(o.kind)) return cons.mat_glass ? 'mat_glass' : null;
    if(isRoof(o)) return 'roof';
    if(o.kind === 'slab' || o.kind === 'pad') return 'floor';
    if(o.mat && cons[o.mat]) return o.mat;
    return 'mat_concrete';
  }
  AP.consKey = consKey;

  /** Edit one layer field and persist it in AR.doc.ext.analyse_performance. */
  AP.setLayer = function(key, idx, field, value){
    var cons = AP.constructions(), c = cons[key];
    if(!c) return;
    var v = parseFloat(value);
    if(!isFinite(v) || v < 0) { arToast('A layer thickness or lambda must be a positive number.', 'warn'); return; }
    if(typeof arPush === 'function') arPush();
    AR.doc.ext = AR.doc.ext || {};
    AR.doc.ext[FAM] = AR.doc.ext[FAM] || {};
    var t = AR.doc.ext[FAM].constructions = AR.doc.ext[FAM].constructions || {};
    var layers = normLayers(t[key]) || c.layers.map(function(l){ return {name: l.name, d: l.d, lambda: l.lambda, r: l.r}; });
    if(!layers[idx]) return;
    layers[idx][field] = v;
    t[key] = {label: c.label, type: c.type, layers: layers.map(function(l){
      var o = {name: l.name};
      if(l.r !== undefined) o.r = l.r;
      if(l.d !== undefined) o.d = l.d;
      if(l.lambda !== undefined) o.lambda = l.lambda;
      return o; })};
    if(typeof arDirty === 'function') arDirty(true);
    AP.uvalueSheet();
  };

  /* ── orientation ────────────────────────────────────────────────────────
     North is -Z by default (up in the top view). AR.doc.ext.light_sun.north,
     when another family has set it, is read as DEGREES the north arrow is
     turned from -Z towards +X. */
  function northVec(){
    var ls = (window.AR && AR.doc && AR.doc.ext && AR.doc.ext.light_sun) || {};
    var deg = N(ls.north, 0);
    var a = deg * Math.PI / 180;
    return {x: Math.sin(a), z: -Math.cos(a), deg: deg};
  }
  function compass(nx, nz, nrt){
    /* bearing of (nx,nz) measured clockwise from north, on the plan */
    var b = Math.atan2(nx * nrt.z - nz * nrt.x, nx * nrt.x + nz * nrt.z) * 180 / Math.PI;
    b = ((b % 360) + 360) % 360;
    var i = Math.round(b / 90) % 4;
    return ['N', 'W', 'S', 'E'][i];
  }

  /* the outward normal of an envelope wall: away from the room it bounds, or
     away from the building's centre when it bounds nothing */
  function outward(w, rooms, cx, cz){
    var n = wallNormal(w), mine = null;
    rooms.forEach(function(r){ if(!mine && (r.walls || []).indexOf(w) >= 0) mine = r; });
    var tx, tz;
    if(mine){ var c = centroid(mine.pts); tx = c.x; tz = c.z; } else { tx = cx; tz = cz; }
    var dot = n.x * (w.x - tx) + n.z * (w.z - tz);
    return dot >= 0 ? n : {x: -n.x, z: -n.z};
  }

  /* ── obstruction / vertical sky angle ───────────────────────────────── */
  function topY(o){
    var p = o.p || {};
    if(p.h !== undefined) return N(o.y, 0) + N(p.h, 0);
    if(p.t !== undefined) return N(o.y, 0) + N(p.t, 0);
    if(p.r !== undefined) return N(o.y, 0) + 2 * N(p.r, 0);
    return N(o.y, 0);
  }
  var SKIP_OBS = {ground: 1, pad: 1, road: 1, path: 1, guide_line: 1, guide_circle: 1, person: 1, annotation: 1, dimension: 1};
  function skyAngle(room, ownWalls){
    var c = centroid(room.pts), eye = room.y + 1.2, best = 65, who = '';
    objs().forEach(function(o){
      if(o.hidden || isOpening(o.kind) || SKIP_OBS[o.kind] || String(o.kind).lastIndexOf('sculpt_', 0) === 0) return;
      if(ownWalls.indexOf(o) >= 0) return;
      if(ptInPoly(room.pts, o.x, o.z)) return;               /* inside the room is not an obstruction */
      var dx = o.x - c.x, dz = o.z - c.z, dist = Math.sqrt(dx * dx + dz * dz);
      if(dist < 0.5 || dist > 20) return;
      var rise = topY(o) - eye;
      if(rise <= 0.1) return;
      var th = 90 - Math.atan2(rise, dist) * 180 / Math.PI;
      if(th < best){ best = th; who = o.id + ' ' + o.kind + ' at ' + f(dist, 1) + ' m, top ' + f(topY(o), 1) + ' m'; }
    });
    return {theta: Math.max(5, best), obstruction: who};
  }

  /* ── the daylight overlay (scene furniture, not records) ─────────────── */
  var RAMP = ['#b4231f', '#d97a1c', '#d8c320', '#7fb832', '#2f9e4f'];
  AP.overlayClear = function(){
    if(!AP._overlay || !window.AR || !AR.scene) { AP._overlay = null; return; }
    AP._overlay.forEach(function(m){
      AR.scene.remove(m);
      if(m.geometry) m.geometry.dispose();
      if(m.material) m.material.dispose();
    });
    AP._overlay = null;
    if(typeof arRender === 'function') arRender();
  };
  function overlayPaint(rows){
    AP.overlayClear();
    if(!window.AR || !AR.scene || typeof THREE === 'undefined') return;
    var made = [];
    rows.forEach(function(r){
      try {
        var sh = new THREE.Shape();
        r.room.pts.forEach(function(p, i){ if(i) sh.lineTo(p.x, p.z); else sh.moveTo(p.x, p.z); });
        sh.closePath();
        var g = new THREE.ShapeGeometry(sh);
        g.rotateX(Math.PI / 2);                        /* shape (x, y) -> world (x, 0, y) */
        var m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
          color: new THREE.Color(RAMP[r.step]), transparent: true, opacity: 0.42,
          side: THREE.DoubleSide, depthWrite: false}));
        m.position.y = r.room.y + 0.03;
        m.renderOrder = 3;
        m.userData.apOverlay = 1;
        AR.scene.add(m);
        made.push(m);
      } catch(e){ /* a self-intersecting outline is not worth a broken report */ }
    });
    AP._overlay = made.length ? made : null;
    if(typeof arRender === 'function') arRender();
  }

  /* ── 1. DAYLIGHT ────────────────────────────────────────────────────── */
  var T_GLASS = 0.7, R_SURF = 0.5, FRAME = 0.8;
  function livingish(name){ return /living|lounge|sitting|bed|kitchen|dining|study|office|family/i.test(String(name)); }

  AP.daylight = function(opt){
    opt = opt || {};
    var R = AP.rooms(), rooms = R.rooms;
    var walls = objs().filter(function(o){ return !o.hidden && isWall(o); });
    var hosted = openingsOf(walls), cnt = wallRoomCount(rooms);
    var forced = (opt.target !== undefined && opt.target !== null && opt.target !== '') ? N(opt.target, null) : null;
    var rows = [], issues = [];
    rooms.forEach(function(r){
      var ws = r.walls || [], h = 0;
      ws.forEach(function(w){ h = Math.max(h, N(w.p.h, storeyH())); });
      if(!h) h = storeyH();
      var Aw = 0, nw = 0, ext = 0;
      ws.forEach(function(w){
        var interior = (cnt[w.id] || 0) >= 2;
        if(interior) return;
        ext++;
        (hosted[w.id] || []).forEach(function(o){
          if(o.kind !== 'window') return;
          Aw += N(o.p.w, 1.2) * N(o.p.h, 1.4) * FRAME;
          nw++;
        });
      });
      var Atot = 2 * r.area + r.perim * h;
      var sky = skyAngle(r, ws);
      var df = Atot > 0 ? (Aw * sky.theta * T_GLASS) / (Atot * (1 - R_SURF * R_SURF)) : 0;
      var target = forced !== null ? forced : (livingish(r.name) ? 2.0 : 1.0);
      var step = Math.max(0, Math.min(4, Math.floor((target > 0 ? df / target : 0) * 4)));
      rows.push({room: r, df: df, target: target, Aw: Aw, Atot: Atot, theta: sky.theta,
                 obstruction: sky.obstruction, windows: nw, extWalls: ext, h: h, step: step});
      if(df < target){
        issues.push({severity: df < target / 2 ? 'error' : 'warning',
                     ids: ws.map(function(w){ return w.id; }),
                     text: E(r.name) + ': average daylight factor ' + f(df, 2) + ' % is below the '
                       + f(target, 1) + ' % target (BRE 209)' + (nw ? '' : ' — no window on an exterior wall')});
      }
    });
    return {id: 'a_daylight', name: 'Daylight factor', family: FAM, source: R.source, rows: rows, issues: issues,
            summary: rooms.length + ' room' + (rooms.length === 1 ? '' : 's') + ' from ' + R.source
              + '; ' + issues.length + ' below target'};
  };

  function daylightSheet(opt){
    var r = AP.daylight(opt);
    var h = '<p class="ar-note">Average daylight factor, BRE Digest 209 / BS 8206-2: '
      + '<b>DF % = (A<sub>w</sub> &times; &theta; &times; T) / (A<sub>total</sub> &times; (1 &minus; R&sup2;))</b>. '
      + 'Glass area A<sub>w</sub> = window w &times; h &times; ' + FRAME + ' frame factor, on exterior walls only; '
      + 'T = ' + T_GLASS + ' glass transmittance; R = ' + R_SURF + ' area-weighted internal reflectance; '
      + 'A<sub>total</sub> = floor + ceiling + internal wall area. &theta; = 65&deg; vertical sky angle unless a record '
      + 'within 20 m is tall enough to cut it. Targets: 2 % living spaces, 1 % other'
      + (opt && opt.target ? ' (overridden to ' + f(N(opt.target, 2), 1) + ' % for every room)' : '') + '.</p>'
      + '<p class="ar-note">Rooms from: <b>' + E(r.source) + '</b>.</p>';
    if(!r.rows.length){
      h += '<p>No enclosed room was found. Draw walls that close a loop, or add a <code>zone</code> record with a point list.</p>';
      arSheet('Daylight factor', h);
      return r;
    }
    h += '<table class="ar-tbl"><tr><th>Room</th><th>Floor m&sup2;</th><th>Windows</th><th>A<sub>w</sub> m&sup2;</th>'
      + '<th>A<sub>total</sub> m&sup2;</th><th>&theta;&deg;</th><th>DF %</th><th>Target</th><th></th></tr>';
    r.rows.forEach(function(x){
      h += '<tr><td>' + E(x.room.name) + '</td><td>' + f(x.room.area, 1) + '</td><td>' + x.windows + '</td><td>'
        + f(x.Aw, 2) + '</td><td>' + f(x.Atot, 1) + '</td><td>' + f(x.theta, 0) + '</td>'
        + '<td style="color:' + RAMP[x.step] + ';font-weight:600">' + f(x.df, 2) + '</td><td>' + f(x.target, 1) + '</td>'
        + '<td>' + (x.df < x.target ? '<span style="color:#d97a1c">below</span>' : 'ok') + '</td></tr>';
    });
    h += '</table>';
    var obs = r.rows.filter(function(x){ return x.obstruction; });
    if(obs.length) h += '<p class="ar-note">Obstructions cutting &theta;: '
      + obs.map(function(x){ return E(x.room.name) + ' &larr; ' + E(x.obstruction); }).join('; ') + '.</p>';
    h += '<p class="ar-note">The floor overlay paints each room on the 5-step ramp '
      + RAMP.map(function(c, i){ return '<span style="color:' + c + '">&#9632;</span>' + (i === 0 ? ' 0' : (i === 4 ? ' &ge;target' : '')); }).join(' ')
      + ' &mdash; it is removed when this sheet closes.</p>';
    arSheet('Daylight factor', h);
    overlayPaint(r.rows);
    return r;
  }

  /* ── 2. U-VALUES ────────────────────────────────────────────────────── */
  AP.uvalues = function(opt){
    opt = opt || {};
    if(opt.set && typeof opt.set === 'object'){
      var wrote = false;
      Object.keys(opt.set).forEach(function(k){
        var L = normLayers(opt.set[k]);
        if(!L) return;
        if(!wrote && typeof arPush === 'function'){ arPush(); wrote = true; }
        AR.doc.ext = AR.doc.ext || {};
        AR.doc.ext[FAM] = AR.doc.ext[FAM] || {};
        AR.doc.ext[FAM].constructions = AR.doc.ext[FAM].constructions || {};
        AR.doc.ext[FAM].constructions[k] = {label: (opt.set[k] && opt.set[k].label) || k,
                                            type: (opt.set[k] && opt.set[k].type) || (DEFAULT_CONS[k] || {}).type || 'wall',
                                            layers: L};
      });
      if(wrote && typeof arDirty === 'function') arDirty(true);
    }
    var cons = AP.constructions(), rows = [], issues = [];
    Object.keys(cons).forEach(function(k){
      var c = cons[k], lim = NL_LIMIT[c.type];
      rows.push(c);
      if(lim && c.u > lim + 1e-6){
        issues.push({severity: c.u > lim * 1.5 ? 'error' : 'warning', ids: [],
                     text: c.label + ': U = ' + f(c.u, 3) + ' W/m&sup2;K is above the Bouwbesluit 2021 '
                       + c.type + ' limit of ' + lim + ' W/m&sup2;K'});
      }
    });
    return {id: 'a_uvalue', name: 'U-values', family: FAM, rows: rows, issues: issues, constructions: cons,
            summary: rows.length + ' constructions, ' + issues.length + ' above the NL new-build limit'};
  };

  AP.uvalueSheet = function(opt){
    var r = AP.uvalues(opt);
    var h = '<p class="ar-note">Thermal transmittance <b>U = 1 / (R<sub>si</sub> ' + RSI
      + ' + &Sigma; d/&lambda; + R<sub>se</sub> ' + RSE + ')</b>, W/m&sup2;K. Edit a thickness d (m) or a '
      + '&lambda; (W/mK) and the table recomputes and stores the build-up in the drawing '
      + '(<code>AR.doc.ext.analyse_performance.constructions</code>). Limits are the Bouwbesluit 2021 '
      + 'new-build maxima: wall ' + NL_LIMIT.wall + ', roof ' + NL_LIMIT.roof + ', floor ' + NL_LIMIT.floor
      + ', glazing ' + NL_LIMIT.glass + ' W/m&sup2;K.</p>';
    Object.keys(r.constructions).forEach(function(k){
      var c = r.constructions[k], lim = NL_LIMIT[c.type], bad = lim && c.u > lim + 1e-6;
      h += '<h4 style="margin:10px 0 4px">' + E(c.label) + ' <span class="ar-note">(' + E(k) + ', ' + E(c.type) + ')</span>'
        + ' &mdash; U = <b style="color:' + (bad ? '#d97a1c' : '#2f9e4f') + '">' + f(c.u, 3) + '</b> W/m&sup2;K'
        + (lim ? ' <span class="ar-note">limit ' + lim + (bad ? ' &mdash; over' : '') + '</span>' : '')
        + (c.edited ? ' <span class="ar-note">[edited]</span>' : '') + '</h4>';
      h += '<table class="ar-tbl"><tr><th>Layer</th><th>d (m)</th><th>&lambda; (W/mK)</th><th>R (m&sup2;K/W)</th></tr>';
      c.layers.forEach(function(l, i){
        var Rl = (l.r !== undefined) ? l.r : (l.d || 0) / Math.max(0.001, l.lambda || 1);
        h += '<tr><td>' + E(l.name) + '</td>'
          + '<td>' + (l.d === undefined ? '&mdash;' : '<input class="ap-in" type="number" step="0.005" min="0" value="' + l.d
            + '" style="width:5.5em" onchange="analyse_performance.setLayer(\'' + E(k) + '\',' + i + ',\'d\',this.value)">') + '</td>'
          + '<td>' + (l.lambda === undefined ? '&mdash;' : '<input class="ap-in" type="number" step="0.005" min="0.001" value="' + l.lambda
            + '" style="width:5.5em" onchange="analyse_performance.setLayer(\'' + E(k) + '\',' + i + ',\'lambda\',this.value)">') + '</td>'
          + '<td>' + f(Rl, 3) + '</td></tr>';
      });
      h += '<tr><td colspan="3" style="text-align:right"><b>R<sub>total</sub> incl. surfaces</b></td><td><b>'
        + f(1 / c.u, 3) + '</b></td></tr></table>';
    });
    arSheet('U-value / construction build-up', h);
    return r;
  };

  /* ── 3. ENERGY ──────────────────────────────────────────────────────── */
  var ACH = 0.5, C_AIR = 0.34;      /* air changes per hour; W per m3 per K */
  AP.energy = function(opt){
    opt = opt || {};
    var cons = AP.constructions(), R = AP.rooms(), rooms = R.rooms;
    var walls = objs().filter(function(o){ return !o.hidden && isWall(o); });
    var hosted = openingsOf(walls), cnt = wallRoomCount(rooms), nrt = northVec();
    var cx = 0, cz = 0;
    walls.forEach(function(w){ cx += w.x; cz += w.z; });
    if(walls.length){ cx /= walls.length; cz /= walls.length; }

    var orient = {N: {wall: 0, glass: 0}, E: {wall: 0, glass: 0}, S: {wall: 0, glass: 0}, W: {wall: 0, glass: 0}};
    var wallGross = 0, wallNet = 0, glassA = 0, doorA = 0, HA = 0, parts = [];
    walls.forEach(function(w){
      if((cnt[w.id] || 0) >= 2) return;                       /* fully interior */
      var L = N(w.p.len, 4), h = N(w.p.h, storeyH()), A = L * h;
      var op = hosted[w.id] || [], g = 0, dr = 0;
      op.forEach(function(o){
        var a = N(o.p.w, 1) * N(o.p.h, 2.1);
        if(o.kind === 'window') g += a; else dr += a;
      });
      var n = outward(w, rooms, cx, cz), face = compass(n.x, n.z, nrt);
      orient[face].wall += A;
      orient[face].glass += g;
      wallGross += A; glassA += g; doorA += dr;
      wallNet += Math.max(0, A - g - dr);
    });
    var wallU = 0, wn = 0;
    walls.forEach(function(w){
      if((cnt[w.id] || 0) >= 2) return;
      var k = consKey(w, cons);
      if(cons[k]){ wallU += cons[k].u; wn++; }
    });
    wallU = wn ? wallU / wn : (cons.mat_concrete ? cons.mat_concrete.u : 0.3);
    parts.push({what: 'exterior walls (net of openings)', area: wallNet, u: wallU});
    if(glassA + doorA > 0) parts.push({what: 'windows and doors', area: glassA + doorA, u: cons.mat_glass ? cons.mat_glass.u : 1.1});

    var roofA = 0, floorA = 0;
    objs().forEach(function(o){
      if(o.hidden) return;
      var p = o.p || {};
      if(isRoof(o)) roofA += N(p.w, 8) * N(p.d, 6);
      else if((o.kind === 'slab' || o.kind === 'pad') && N(o.y, 0) <= 0.05) floorA += N(p.w, 6) * N(p.d, 4);
    });
    if(roofA > 0) parts.push({what: 'roofs', area: roofA, u: cons.roof.u});
    if(floorA > 0) parts.push({what: 'ground slabs', area: floorA, u: cons.floor.u});
    parts.forEach(function(p){ p.h = p.area * p.u; HA += p.h; });

    var vol = 0;
    rooms.forEach(function(r){ vol += r.area * storeyH(); });
    if(!vol) vol = floorA * storeyH();
    var Hv = ACH * vol * C_AIR;
    var H = HA + Hv;
    var dd = N(opt.degree_days, N(extBag().degree_days, 2800));
    var kwh = H * 24 * dd / 1000;

    var issues = [];
    ['N', 'E', 'S', 'W'].forEach(function(o){
      var a = orient[o];
      if(a.wall < 1) return;
      var g = a.glass / a.wall;
      if(g > 0.40) issues.push({severity: 'warning', ids: [],
        text: 'Glazing ratio ' + f(g * 100, 0) + ' % on the ' + o + ' facade is above 40 % — overheating and heat loss risk'});
      else if(g < 0.10) issues.push({severity: 'warning', ids: [],
        text: 'Glazing ratio ' + f(g * 100, 0) + ' % on the ' + o + ' facade is below 10 % — that facade will be dark'});
    });
    if(!wallGross) issues.push({severity: 'error', ids: [], text: 'No exterior wall found — there is no heated envelope to model'});

    return {id: 'a_energy', name: 'Energy model', family: FAM, issues: issues, source: R.source,
            parts: parts, orient: orient, north: nrt, wallGross: wallGross, wallNet: wallNet,
            glass: glassA, doors: doorA, roofA: roofA, floorA: floorA, volume: vol,
            HA: HA, Hv: Hv, H: H, degree_days: dd, kwh: kwh, rooms: rooms.length,
            /* window area / exterior wall area over the whole envelope — the same
               number the assistant's energy_summary() prints as `glazing_ratio`.
               The 40 % / 10 % flags above are per orientation, this is the total. */
            glazingRatio: wallGross ? glassA / wallGross : 0,
            summary: 'envelope ' + f(wallGross + roofA + floorA, 0) + ' m&sup2;, H = ' + f(H, 1)
              + ' W/K, ' + f(kwh, 0) + ' kWh/year'};
  };

  function energySheet(opt){
    var r = AP.energy(opt);
    var h = '<p class="ar-note">The heated envelope is every wall that is <b>not fully interior</b> '
      + '(a room on one side only, or no room at all), plus roofs and ground slabs. Rooms from: <b>'
      + E(r.source) + '</b>. North is ' + (r.north.deg ? f(r.north.deg, 0) + '&deg; from &minus;Z '
      + '(AR.doc.ext.light_sun.north)' : '&minus;Z, up in the top view (no north set)') + '.</p>';
    h += arRows([['Exterior wall area, gross', f(r.wallGross, 1) + ' m&sup2;'],
                 ['Exterior wall area, net of openings', f(r.wallNet, 1) + ' m&sup2;'],
                 ['Window area', f(r.glass, 1) + ' m&sup2;'],
                 ['Door / opening area', f(r.doors, 1) + ' m&sup2;'],
                 ['Roof area', f(r.roofA, 1) + ' m&sup2;'],
                 ['Ground slab area', f(r.floorA, 1) + ' m&sup2;'],
                 ['Heated volume', f(r.volume, 1) + ' m&sup3; (' + r.rooms + ' rooms &times; ' + f(storeyH(), 2) + ' m)']]);
    h += arRows([['Glazing ratio, whole envelope (window area / exterior wall area)',
                  '<b>' + f(r.glazingRatio * 100, 1) + ' %</b>']]);
    h += '<h4 style="margin:10px 0 4px">Glazing ratio by orientation</h4>'
      + '<table class="ar-tbl"><tr><th>Facade</th><th>Wall m&sup2;</th><th>Glass m&sup2;</th><th>Ratio</th><th></th></tr>';
    ['N', 'E', 'S', 'W'].forEach(function(o){
      var a = r.orient[o], g = a.wall > 0 ? a.glass / a.wall : 0;
      var flag = a.wall < 1 ? '' : (g > 0.40 ? '<span style="color:#d97a1c">&gt; 40 %</span>'
        : (g < 0.10 ? '<span style="color:#d97a1c">&lt; 10 %</span>' : 'ok'));
      h += '<tr><td>' + o + '</td><td>' + f(a.wall, 1) + '</td><td>' + f(a.glass, 1) + '</td><td>'
        + f(g * 100, 1) + ' %</td><td>' + flag + '</td></tr>';
    });
    h += '</table>';
    h += '<h4 style="margin:10px 0 4px">Heat loss coefficient H = &Sigma; U&middot;A + ventilation</h4>'
      + '<table class="ar-tbl"><tr><th>Element</th><th>A m&sup2;</th><th>U W/m&sup2;K</th><th>U&middot;A W/K</th></tr>';
    r.parts.forEach(function(p){
      h += '<tr><td>' + E(p.what) + '</td><td>' + f(p.area, 1) + '</td><td>' + f(p.u, 3) + '</td><td>' + f(p.h, 1) + '</td></tr>';
    });
    h += '<tr><td>ventilation ' + ACH + ' ach &times; ' + f(r.volume, 1) + ' m&sup3; &times; ' + C_AIR + ' W/m&sup3;K</td>'
      + '<td>&mdash;</td><td>&mdash;</td><td>' + f(r.Hv, 1) + '</td></tr>'
      + '<tr><td><b>H total</b></td><td></td><td></td><td><b>' + f(r.H, 1) + '</b></td></tr></table>';
    h += arRows([['Degree-days (NL default, editable via AR.doc.ext.analyse_performance.degree_days)', f(r.degree_days, 0) + ' Kd'],
                 ['Annual heating estimate = H &times; 24 &times; Kd / 1000', '<b>' + f(r.kwh, 0) + ' kWh/year</b>']]);
    h += '<p class="ar-note">Assumptions: U-values come from the a_uvalue construction table (wall U is the mean over the '
      + 'envelope walls\' materials); the ventilation term is ' + ACH + ' air changes per hour at ' + C_AIR
      + ' W/m&sup3;K; heated volume is the room floor area &times; the storey height; no solar or internal gains, '
      + 'no thermal bridges, no system efficiency &mdash; this is a steady-state fabric estimate, not an NTA 8800 calculation.</p>';
    arSheet('Energy model', h);
    return r;
  }

  /* ── 4. STRUCTURE ───────────────────────────────────────────────────── */
  var SPAN_DEPTH = {mat_timber: 20, mat_concrete: 25, mat_steel: 30};
  function beamRule(mat){ return SPAN_DEPTH[mat] || 20; }
  function supportsUnder(o, yTop){
    /* walls and columns whose top reaches the underside of `o` */
    return objs().filter(function(s){
      if(s.hidden || s === o) return false;
      if(!(isWall(s) || s.kind === 'column_rect' || s.kind === 'column_round')) return false;
      var t = topY(s);
      return t > yTop - 1.2 && t < yTop + 0.6;
    });
  }
  function gapAlong(coords, lo, hi){
    var c = coords.filter(function(v){ return v > lo - 0.01 && v < hi + 0.01; }).concat([lo, hi]);
    c.sort(function(a, b){ return a - b; });
    var g = 0;
    for(var i = 1; i < c.length; i++) g = Math.max(g, c[i] - c[i - 1]);
    return g;
  }

  AP.structure = function(){
    var issues = [], rows = [];
    var all = objs().filter(function(o){ return !o.hidden; });
    all.forEach(function(o){
      var p = o.p || {};
      if(o.kind === 'beam'){
        var span = N(p.len, 5), dep = N(p.h, 0.4), lim = beamRule(o.mat), ratio = dep > 0 ? span / dep : 1e9;
        rows.push(['Beam ' + o.id + ' (' + E(o.mat) + ')', 'span ' + f(span, 2) + ' m / depth ' + f(dep, 2)
          + ' m = ' + f(ratio, 1) + ' (limit ' + lim + ')']);
        if(ratio > lim) issues.push({severity: ratio > lim * 1.4 ? 'error' : 'warning', ids: [o.id],
          text: 'Beam ' + o.id + ': span/depth ' + f(ratio, 1) + ' exceeds the ' + lim + ' rule of thumb for '
            + E(o.mat).replace('mat_', '') + ' (span ' + f(span, 2) + ' m, depth ' + f(dep, 2) + ' m)'});
      } else if(o.kind === 'column_rect' || o.kind === 'column_round'){
        var ch = N(p.h, 3), least = o.kind === 'column_round' ? 2 * N(p.r, 0.18) : Math.min(N(p.w, 0.3), N(p.d, 0.3));
        var sl = least > 0 ? ch / least : 1e9;
        rows.push(['Column ' + o.id, 'height ' + f(ch, 2) + ' m / least dim ' + f(least, 3) + ' m = ' + f(sl, 1) + ' (limit 20)']);
        if(sl > 20) issues.push({severity: sl > 30 ? 'error' : 'warning', ids: [o.id],
          text: 'Column ' + o.id + ': slenderness ' + f(sl, 1) + ' (unbraced height ' + f(ch, 2)
            + ' m / least dimension ' + f(least, 3) + ' m) is over the 20 rule of thumb'});
      } else if(o.kind === 'slab'){
        var w = N(p.w, 6), d = N(p.d, 4), t = N(p.t, 0.22), yb = N(o.y, 0);
        var sup = supportsUnder(o, yb);
        var sx = gapAlong(sup.map(function(s){ return s.x; }), o.x - w / 2, o.x + w / 2);
        var sz = gapAlong(sup.map(function(s){ return s.z; }), o.z - d / 2, o.z + d / 2);
        var sp = Math.min(sx, sz), rr = t > 0 ? sp / t : 1e9;
        rows.push(['Slab ' + o.id, 'span ' + f(sp, 2) + ' m / thickness ' + f(t, 3) + ' m = ' + f(rr, 1)
          + ' (limit 30, ' + sup.length + ' supports found)']);
        if(rr > 30) issues.push({severity: rr > 45 ? 'error' : 'warning', ids: [o.id],
          text: 'Slab ' + o.id + ': span/thickness ' + f(rr, 1) + ' exceeds 30 (shorter span ' + f(sp, 2)
            + ' m, thickness ' + f(t, 3) + ' m)'});
      } else if(isRoof(o)){
        var rw = N(p.w, 8), rd = N(p.d, 6), sp2 = Math.min(rw, rd);
        var inner = objs().filter(function(s){
          if(s.hidden || s === o) return false;
          if(!(isWall(s) || s.kind === 'column_rect' || s.kind === 'column_round' || s.kind === 'truss')) return false;
          return Math.abs(s.x - o.x) < rw / 2 - 0.6 && Math.abs(s.z - o.z) < rd / 2 - 0.6;
        });
        rows.push(['Roof ' + o.id, 'span ' + f(sp2, 2) + ' m, ' + inner.length + ' internal supports (limit 12 m clear)']);
        if(sp2 > 12 && !inner.length) issues.push({severity: 'warning', ids: [o.id],
          text: 'Roof ' + o.id + ': ' + f(sp2, 2) + ' m clear span with no internal support — over the 12 m rule of thumb'});
      }
    });
    return {id: 'a_struct', name: 'Structure', family: FAM, rows: rows, issues: issues,
            summary: rows.length + ' structural members checked, ' + issues.length + ' flagged'};
  };

  function structSheet(){
    var r = AP.structure();
    var h = '<p class="ar-note"><b>Rules of thumb, not a calculation.</b> Beam span/depth: timber 20, concrete 25, '
      + 'steel 30 (by the record\'s material). Slab shorter span / thickness: 30, where the span is the largest gap '
      + 'between the walls and columns found under the slab. Column unbraced height / least dimension: 20. '
      + 'Roof clear span without an internal support: 12 m. Every one of these is a preliminary sizing check &mdash; '
      + 'an engineer sizes the member.</p>';
    h += r.rows.length ? arRows(r.rows) : '<p>No beam, column, slab or roof in the drawing.</p>';
    if(r.issues.length){
      h += '<h4 style="margin:10px 0 4px">Flagged</h4><ul>';
      r.issues.forEach(function(i){ h += '<li style="color:' + sevCol(i.severity) + '">' + i.text + '</li>'; });
      h += '</ul>';
    } else h += '<p style="color:#2f9e4f">Nothing flagged.</p>';
    arSheet('Structure', h);
    return r;
  }

  /* ── 5. CODE CHECK — run every registered analysis ───────────────────── */
  function sevCol(s){
    s = String(s || '').toLowerCase();
    if(s === 'error' || s === 'bad' || s === 'fail') return '#b4231f';
    if(s === 'warning' || s === 'warn') return '#d97a1c';
    return '#8a8f98';
  }
  function sevKey(s){
    s = String(s || '').toLowerCase();
    if(s === 'error' || s === 'bad' || s === 'fail') return 'error';
    if(s === 'warning' || s === 'warn') return 'warning';
    return 'info';
  }
  function entryFn(e){ return (typeof e === 'function') ? e : (e && (e.run || e.fn || e.check || e.act)) || null; }
  function entryName(e){ return String((e && (e.name || e.label || e.title || e.id)) || 'analysis'); }
  function entryId(e){ return String((e && (e.id || e.key || e.name)) || ''); }
  function normIssues(res){
    if(!res) return [];
    if(typeof res === 'string') return [{severity: 'info', text: res, ids: []}];
    var arr = Array.isArray(res) ? res : (res.issues || res.problems || res.items || res.flags || []);
    if(!Array.isArray(arr)) return [];
    return arr.map(function(it){
      if(typeof it === 'string') return {severity: 'warning', text: it, ids: []};
      if(!it || typeof it !== 'object') return {severity: 'info', text: String(it), ids: []};
      var ids = it.ids || it.objects || it.records || (it.id && String(it.id).lastIndexOf('o', 0) === 0 ? [it.id] : []);
      return {severity: sevKey(it.severity || it.level || it.sev || it.kind),
              text: String(it.text || it.msg || it.message || it.title || it.what || JSON.stringify(it)),
              ids: Array.isArray(ids) ? ids.map(String) : []};
    });
  }

  AP.code = function(opt){
    opt = opt || {};
    var only = Array.isArray(opt.only) ? opt.only.map(String) : null;
    var reg = (AR_EXT.analyses || []).slice();
    var out = {checks: [], errors: 0, warnings: 0, offenders: [], when: new Date().toISOString()};
    reg.forEach(function(e){
      var id = entryId(e);
      if(only && only.indexOf(id) < 0) return;
      var sec = {id: id, name: entryName(e), family: String((e && e.family) || ''), issues: [], error: '', summary: ''};
      var fn = entryFn(e);
      if(!fn){ sec.error = 'registry entry has no run() function'; out.checks.push(sec); return; }
      try {
        var res = fn.call(e, {});
        sec.issues = normIssues(res);
        sec.summary = String((res && res.summary) || '');
        if(res && res.source) sec.source = String(res.source);
      } catch(err){
        sec.error = String((err && err.message) || err);
      }
      sec.issues.forEach(function(i){
        if(i.severity === 'error') out.errors++;
        else if(i.severity === 'warning') out.warnings++;
        (i.ids || []).forEach(function(x){ if(out.offenders.indexOf(x) < 0) out.offenders.push(x); });
      });
      out.checks.push(sec);
    });
    out.summary = out.errors + ' error' + (out.errors === 1 ? '' : 's') + ', ' + out.warnings
      + ' warning' + (out.warnings === 1 ? '' : 's') + ' across ' + out.checks.length
      + ' check' + (out.checks.length === 1 ? '' : 's');
    AP.lastCode = out;
    AP.lastCodeJson = JSON.stringify(out, null, 2);
    return out;
  };

  AP.selectOffenders = function(){
    var ids = (AP.lastCode && AP.lastCode.offenders) || [];
    if(!ids.length){ arToast('No offending object was named by any check.'); return; }
    arSelect(ids);
    arToast('Selected ' + ids.length + ' offending object' + (ids.length === 1 ? '' : 's') + '.');
  };
  AP.downloadCode = function(){
    if(!AP.lastCodeJson){ arToast('Run the code check first.'); return; }
    arDownload(new Blob([AP.lastCodeJson], {type: 'application/json'}), 'code_check.json');
  };

  function codeSheet(opt){
    var r = AP.code(opt);
    var h = '<p><b>' + E(r.summary) + '</b></p>'
      + '<p><button class="ar-btn" onclick="analyse_performance.selectOffenders()">Select all offenders ('
      + r.offenders.length + ')</button> '
      + '<button class="ar-btn" onclick="analyse_performance.downloadCode()">Download JSON</button></p>';
    if(!r.checks.length) h += '<p>No analysis is registered on <code>AR_EXT.analyses</code>.</p>';
    r.checks.forEach(function(sec){
      var n = sec.issues.length;
      h += '<h4 style="margin:12px 0 4px">' + E(sec.name)
        + ' <span class="ar-note">(' + E(sec.id) + (sec.family ? ', ' + E(sec.family) : '') + ') &mdash; '
        + (sec.error ? '<span style="color:#b4231f">failed</span>' : n + ' issue' + (n === 1 ? '' : 's')) + '</span></h4>';
      if(sec.error){ h += '<p style="color:#b4231f">' + E(sec.error) + '</p>'; return; }
      if(sec.summary) h += '<p class="ar-note">' + sec.summary + '</p>';
      if(!n){ h += '<p style="color:#2f9e4f">Nothing flagged.</p>'; return; }
      h += '<ul>';
      sec.issues.forEach(function(i){
        h += '<li style="color:' + sevCol(i.severity) + '">' + i.text
          + (i.ids && i.ids.length ? ' <span class="ar-note">[' + E(i.ids.join(', ')) + ']</span>' : '') + '</li>';
      });
      h += '</ul>';
    });
    arSheet('Code check', h);
    return r;
  }

  /* ── registry + icons ───────────────────────────────────────────────── */
  function reg(id, name, run){
    for(var i = 0; i < AR_EXT.analyses.length; i++){
      var e = AR_EXT.analyses[i];
      if(e && (e.id === id)){ AR_EXT.analyses[i] = {id: id, name: name, family: FAM, run: run}; return; }
    }
    AR_EXT.analyses.push({id: id, name: name, family: FAM, run: run});
  }
  reg('a_daylight', 'Daylight factor', function(o){ return AP.daylight(o); });
  reg('a_energy', 'Energy model', function(o){ return AP.energy(o); });
  reg('a_uvalue', 'U-values', function(o){ return AP.uvalues(o && o.set ? o : {}); });
  reg('a_struct', 'Structure', function(){ return AP.structure(); });

  function askTarget(opt){
    if(opt && typeof opt === 'object') return opt;
    var v = prompt('Daylight factor target in %, or blank for the BRE defaults (2 % living, 1 % other)', '');
    return (v === null || String(v).trim() === '') ? {} : {target: parseFloat(v)};
  }

  AR_EXT.tools.a_daylight = {assist: 1,
    tip: 'Daylight factor — how much of the outside sky each part of a room can see (BRE average DF, with a floor overlay)',
    act: function(opt){ daylightSheet(askTarget(opt)); }};

  AR_EXT.tools.a_energy = {assist: 1,
    tip: 'Energy model — the heated envelope, its area, how much of it is glass, and the heat-loss coefficient',
    act: function(opt){ energySheet(opt && typeof opt === 'object' ? opt : {}); }};

  AR_EXT.tools.a_uvalue = {assist: 1,
    tip: 'Thermal transmittance per construction — the wall build-up, not just its thickness (editable layers)',
    act: function(opt){ AP.uvalueSheet(opt && typeof opt === 'object' ? opt : {}); }};

  AR_EXT.tools.a_struct = {assist: 1,
    tip: 'Structural sanity — span/depth of every beam, slab and roof, and column slenderness',
    act: function(){ structSheet(); }};

  AR_EXT.tools.a_code = {assist: 1,
    tip: 'Compliance report — every registered analysis run in one pass, with what failed and where',
    act: function(opt){ codeSheet(opt && typeof opt === 'object' ? opt : {}); }};

  /* the daylight overlay lives only as long as its sheet */
  AR_EXT.ready.push(function(){
    var base = arSheetClose;
    arSheetClose = function(){ try { AP.overlayClear(); } catch(e){} base(); };
  });
})();
