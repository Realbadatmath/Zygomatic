// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* site_terrain — Site ▸ Terrain, Contours, Cut and fill (2026-09-07).

   Three dock icons that make the v3 sculpted ground reachable:

   · st_terrain  lays the ONE `ground` record when there is none, and afterwards
                 opens a sheet from which every sculpt kind can be armed on the
                 rail's own placement path, the building footprints flattened,
                 and the ground's own parameters edited.
   · st_contour  a switch: marching-squares contour lines of H(x, z) drawn as one
                 THREE.LineSegments over the ground, every fifth line heavier and
                 labelled, rebuilt whenever the ground is rebuilt.
   · st_cutfill  a read-only report: earthwork volumes between the ground and the
                 base of each slab, per slab and in total, with a balance button
                 that moves a slab to the elevation where cut equals fill.

   Nothing here duplicates the heightfield: H comes from ground_v3's own exported
   arithmetic (AR_EXT.ground_v3.heightAt), with a downward raycast against the
   built ground mesh as the fallback when that export is missing. Licence: the
   file is part of this repository; no third-party code is vendored. */
(function(){
  var FAM = 'site_terrain';
  var CONTOUR_COL = 0xd9b36c, CONTOUR_MAJOR = 0xffe6ad;
  var CONTOUR_MAX_CELLS = 200, CONTOUR_CELL_DIV = 160, CONTOUR_MAX_LEVELS = 400;
  var CUTFILL_CELL = 0.25, TRUCK_M3 = 8;

  /* the ground's own defaults and the ten sculpts', straight from
     arch_ext/ground_v3.json — PARAMETERS only, never geometry */
  var GROUND_DEF = {w: 200, d: 200, res: 100, seed: 1, base: 0, amp: 1.5,
                    snow_h: 60, water_h: -0.15, grass_max_slope: 32};
  var SCULPT_DEF = {
    sculpt_peak:    {r: 40, h: 30, rug: 0.45, seed: 1, feather: 8},
    sculpt_ridge:   {len: 120, w: 40, h: 25, rug: 0.35, seed: 1, feather: 12},
    sculpt_mesa:    {r: 40, h: 25, top_r: 28, rug: 0.25, seed: 1, feather: 8},
    sculpt_cut:     {len: 200, w: 60, depth: 15, floor_w: 15, profile: 0, feather: 20},
    sculpt_channel: {len: 120, w: 12, depth: 2, meander: 6, seed: 1, bank: 2, feather: 12},
    sculpt_basin:   {rx: 40, rz: 28, depth: 6, wobble: 0.25, seed: 1, shore: 6, feather: 0},
    sculpt_flat:    {w: 40, d: 40, level: 0, feather: 6},
    sculpt_step:    {len: 120, h: 20, d: 40, rug: 0.3, seed: 1, feather: 12},
    sculpt_dunes:   {w: 160, d: 80, h: 10, seed: 1, dir: 0, feather: 16},
    sculpt_shelf:   {w: 200, d: 120, depth: 8, feather: 20}
  };
  /* the ground parameters the sheet exposes, and what they mean */
  var GROUND_FIELDS = [
    ['w', 'size X (m)', 1], ['d', 'size Z (m)', 1], ['res', 'lattice cells', 1],
    ['base', 'base level (m)', 0.1], ['amp', 'base roll (m)', 0.1],
    ['water_h', 'water level (m)', 0.05], ['snow_h', 'snow line (m)', 1],
    ['grass_max_slope', 'grass max slope (deg)', 1], ['seed', 'seed', 1]
  ];

  function num(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }
  function fmt(v, d){ var m = Math.pow(10, d || 0); return (Math.round(v * m) / m).toFixed(d || 0); }
  var BTN = 'style="border:1px solid var(--line);background:var(--panel2);color:var(--txt);'
          + 'border-radius:6px;padding:2px 9px;cursor:pointer;font:inherit;font-size:.7rem;"';
  var INP = 'style="width:84px;background:var(--panel2);border:1px solid var(--line);color:var(--txt);'
          + 'border-radius:5px;padding:2px 5px;font:inherit;font-size:.7rem;text-align:right;"';
  function clone(o){ return JSON.parse(JSON.stringify(o || {})); }
  function isObj(o){ return !!o && typeof o === 'object'; }

  /* ── the document ─────────────────────────────────────────────────────── */
  function theGround(){
    for(var i = 0; i < AR.objs.length; i++) if(AR.objs[i].kind === 'ground') return AR.objs[i];
    return null;
  }
  function sculptKinds(){
    var out = [], L = (window.AR_EXT && AR_EXT.label) || {};
    for(var k in L) if(L.hasOwnProperty(k) && k.lastIndexOf('sculpt_', 0) === 0) out.push(k);
    if(!out.length) for(var j in SCULPT_DEF) if(SCULPT_DEF.hasOwnProperty(j)) out.push(j);
    return out;
  }
  function defaultsFor(kind){ return clone(SCULPT_DEF[kind] || {}); }

  /* 'C4' → the centre of that cell, in metres. The tab names cells but never
     parses one back, so the family carries its own inverse of arCellName. */
  function cellCentre(name){
    var m = /^([A-Za-z]+)\s*(\d+)$/.exec(String(name || '').trim());
    if(!m) return null;
    var letters = m[1].toUpperCase(), c = 0, i;
    for(i = 0; i < letters.length; i++) c = c * 26 + (letters.charCodeAt(i) - 64);
    c -= 1;
    var r = parseInt(m[2], 10) - 1;
    if(c < 0 || r < 0) return null;
    var o = (typeof AR_CELL_O === 'number') ? AR_CELL_O : -150;
    var s = (typeof AR_CELL_M === 'number') ? AR_CELL_M : 1;
    return {x: o + (c + 0.5) * s, z: o + (r + 0.5) * s};
  }

  /* the plan centre of what is drawn (the sculpts and the ground excluded —
     they ARE the land), or the origin when the drawing is empty */
  function planCentre(){
    var n = 0, x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9;
    AR.objs.forEach(function(o){
      if(o.kind === 'ground' || String(o.kind || '').lastIndexOf('sculpt_', 0) === 0) return;
      var e = extentOf(o);
      if(!e) return;
      n++;
      x0 = Math.min(x0, e.x - e.w / 2); x1 = Math.max(x1, e.x + e.w / 2);
      z0 = Math.min(z0, e.z - e.d / 2); z1 = Math.max(z1, e.z + e.d / 2);
    });
    if(!n) return {x: 0, z: 0, w: 0, d: 0};
    return {x: (x0 + x1) / 2, z: (z0 + z1) / 2, w: x1 - x0, d: z1 - z0};
  }
  /* a record's footprint in plan: centre, local width/depth and yaw */
  function extentOf(o){
    var p = o.p || {}, sc = num(o.s, 1) || 1;
    var w, d;
    if(o.kind === 'wall' || o.kind === 'partition'){ w = num(p.len, 4); d = num(p.t, 0.24); }
    else if(o.kind === 'slab' || o.kind === 'footing' || o.kind === 'pad'){ w = num(p.w, 6); d = num(p.d, 4); }
    else return null;
    return {x: num(o.x, 0), z: num(o.z, 0), w: Math.abs(w) * sc, d: Math.abs(d) * sc, ry: num(o.ry, 0)};
  }

  /* ── H(x, z) in WORLD metres ──────────────────────────────────────────── */
  function worldToLocal(g, wx, wz){
    var sc = num(g.s, 1) || 1, ry = num(g.ry, 0), c = Math.cos(ry), s = Math.sin(ry);
    var dx = wx - num(g.x, 0), dz = wz - num(g.z, 0);
    return {lx: (dx * c - dz * s) / sc, lz: (dx * s + dz * c) / sc};
  }
  function localToWorld(g, lx, lz){
    var sc = num(g.s, 1) || 1, ry = num(g.ry, 0), c = Math.cos(ry), s = Math.sin(ry);
    return {x: num(g.x, 0) + sc * (lx * c + lz * s), z: num(g.z, 0) + sc * (-lx * s + lz * c)};
  }
  /* the exported arithmetic first (exact and cheap); the built mesh second */
  function heightFn(g){
    var G = window.AR_EXT && AR_EXT.ground_v3;
    var sc = num(g.s, 1) || 1, gy = num(g.y, 0);
    if(G && typeof G.heightAt === 'function'){
      return function(wx, wz){
        var L = worldToLocal(g, wx, wz);
        return gy + sc * G.heightAt(g.p || {}, L.lx, L.lz, AR.objs, num(g.x, 0), num(g.z, 0), num(g.ry, 0));
      };
    }
    var ray = new THREE.Raycaster(), down = new THREE.Vector3(0, -1, 0), from = new THREE.Vector3();
    var top = gy + 1e4;
    return function(wx, wz){                       /* fallback: sample the mesh on screen */
      if(!g.node) return gy;
      from.set(wx, top, wz);
      ray.set(from, down);
      var hit = ray.intersectObject(g.node, true);
      return hit.length ? hit[0].point.y : gy;
    };
  }

  /* ── st_terrain ───────────────────────────────────────────────────────── */
  function makeGround(size){
    var c = planCentre();
    var p = clone(GROUND_DEF);
    var want = num(size, 0);
    if(want > 0){ p.w = want; p.d = want; }
    else if(c.w > 0){ p.w = Math.max(50, Math.ceil((c.w * 3 + 40) / 10) * 10); p.d = Math.max(50, Math.ceil((c.d * 3 + 40) / 10) * 10); }
    arPush();
    var g = arNewObj('ground', p, c.x, c.z, 0);
    g.name = 'Ground';
    g.mat = 'mat_grass';
    arApplyMat(g);
    arSelect([g.id]);
    arDirty(true); arOutliner(); arPanel();
    return g;
  }
  function placeSculpt(kind, cell, extra){
    var g = theGround() || makeGround(0);
    var p = defaultsFor(kind);
    if(isObj(extra)) for(var k in extra) if(extra.hasOwnProperty(k) && typeof extra[k] === 'number') p[k] = extra[k];
    var at = cell ? cellCentre(cell) : null;
    if(!at){ var c = planCentre(); at = {x: c.x, z: c.z}; }
    arPush();
    var rec = arNewObj(kind, p, at.x, at.z, 0);
    rec.name = arKindLabel(kind);
    arSelect([rec.id]);
    arDirty(true); arOutliner(); arPanel();
    return rec;
  }

  function sheetTerrain(){
    var g = theGround();
    if(!g){ arToast('There is no ground yet.', 'warn'); return; }
    var h = '<p class="ar-note">The drawing has ONE ground. Every landform below is a <b>sculpt of it</b> — '
          + 'a parameter of the surface, not a solid parked on a lawn. Arm one and click where it goes.</p>';
    h += '<table class="ar-tbl"><tr><td colspan="2"><b>Sculpts</b></td></tr>';
    sculptKinds().forEach(function(k){
      var d = SCULPT_DEF[k] || {}, bits = [];
      for(var key in d) if(d.hasOwnProperty(key) && key !== 'seed' && key !== 'feather') bits.push(key + ' ' + d[key]);
      h += '<tr><td>' + esc(arKindLabel(k)) + '<br><small>' + esc(bits.join(', ')) + '</small></td>'
         + '<td><button ' + BTN + ' onclick="siteTerrainArm(&quot;' + k + '&quot;)">place</button></td></tr>';
    });
    h += '</table>';
    var foot = footprintRecs();
    h += '<table class="ar-tbl"><tr><td colspan="2"><b>Ground</b></td></tr>'
       + '<tr><td>flatten under buildings<br><small>' + foot.length + ' slab/wall footprint'
       + (foot.length === 1 ? '' : 's') + '</small></td>'
       + '<td><button ' + BTN + ' onclick="siteTerrainFlatten()"' + (foot.length ? '' : ' disabled')
       + '>flatten</button></td></tr>';
    GROUND_FIELDS.forEach(function(f){
      h += '<tr><td>' + esc(f[1]) + '</td><td><input ' + INP + ' type="number" step="' + f[2]
         + '" value="' + num(g.p[f[0]], GROUND_DEF[f[0]]) + '" '
         + 'onchange="siteTerrainGroundSet(&quot;' + f[0] + '&quot;, this.value)"></td></tr>';
    });
    h += '</table>';
    arSheet('Terrain', h);
  }

  function footprintRecs(){
    return AR.objs.filter(function(o){
      return !o.hidden && (o.kind === 'slab' || o.kind === 'wall' || o.kind === 'partition');
    });
  }
  /* one arPush, then a sculpt_flat sized to every footprint. The pad is the
     footprint plus a 2 m working margin so the batter feathers OUTSIDE the
     building instead of tilting the ground under it. */
  function flattenUnderBuildings(){
    var recs = footprintRecs();
    if(!recs.length){ arToast('Nothing to flatten — draw a slab or a wall first.', 'warn'); return 0; }
    var g = theGround() || makeGround(0);
    arPush();
    var n = 0;
    recs.forEach(function(o){
      var e = extentOf(o);
      if(!e) return;
      var margin = 2, feather = 2;
      var p = {w: e.w + 2 * margin, d: e.d + 2 * margin, level: num(o.y, 0), feather: feather};
      var rec = arNewObj('sculpt_flat', p, e.x, e.z, 0);
      rec.ry = e.ry; arApplyTransform(rec);
      rec.name = 'Pad · ' + (o.name || arKindLabel(o.kind));
      rec.meta.site_terrain_pad_for = o.id;
      n++;
    });
    arDirty(true); arOutliner(); arPanel();
    arToast('Flattened under <b>' + n + '</b> footprint' + (n === 1 ? '' : 's') + ' — one level pad each, battered 2 m at its rim.');
    return n;
  }

  window.siteTerrainArm = function(kind){
    var p = defaultsFor(kind);
    AR.place = {id: FAM + ':' + kind, kind: kind, p: p, n: arKindLabel(kind)};
    arTool('place', AR.place);
    arSheetClose();
    arHint('Click on the plan to place <b>' + esc(arKindLabel(kind)) + '</b> — hold <b>Shift</b> to keep placing.');
  };
  window.siteTerrainFlatten = function(){ flattenUnderBuildings(); sheetTerrain(); };
  window.siteTerrainGroundSet = function(key, v){
    var g = theGround();
    if(!g) return;
    var val = num(v, null);
    if(val === null) return;
    arPush();
    g.p[key] = val;
    arRebuild(g); arApplyTransform(g);
    arDirty(true); arPanel();
    if(AR._stContourOn) buildContours();
  };

  AR_EXT.tools.st_terrain = {
    assist: 1,
    on: function(){ return !!theGround(); },
    tip: 'Terrain — lay the one sculpted ground, then sculpt it: peaks, ridges, valleys, river beds and level pads',
    act: function(opt){
      var o = isObj(opt) ? opt : {};
      if(o.kind){ placeSculpt(String(o.kind), o.cell, o); return; }
      var g = theGround();
      if(!g){
        g = makeGround(o.size);
        arToast('Ground laid: <b>' + arFmt(num(g.p.w, 200)) + ' &times; ' + arFmt(num(g.p.d, 200))
              + ' m</b>. Press <b>Terrain</b> again for the sculpts — a peak, a ridge, a valley, a river bed or a level pad — '
              + 'each one a parameter of THIS surface, not a solid on top of it.');
        return;
      }
      sheetTerrain();
    }
  };

  /* ── st_contour ───────────────────────────────────────────────────────── */
  /* marching squares, the standard 16 cases as pairs of cell edges:
     e0 = c00→c10 (south), e1 = c10→c11 (east), e2 = c11→c01 (north), e3 = c01→c00 (west) */
  var MS = [[], [[3, 0]], [[0, 1]], [[3, 1]], [[1, 2]], [[3, 0], [1, 2]], [[0, 2]], [[3, 2]],
            [[2, 3]], [[2, 0]], [[0, 1], [2, 3]], [[2, 1]], [[1, 3]], [[1, 0]], [[0, 3]], []];

  function edgePoint(e, x0, x1, z0, z1, h00, h10, h11, h01, L){
    function t(a, b){ var dd = b - a; return Math.abs(dd) < 1e-12 ? 0.5 : (L - a) / dd; }
    var u;
    if(e === 0){ u = t(h00, h10); return [x0 + (x1 - x0) * u, z0]; }
    if(e === 1){ u = t(h10, h11); return [x1, z0 + (z1 - z0) * u]; }
    if(e === 2){ u = t(h11, h01); return [x1 + (x0 - x1) * u, z1]; }
    u = t(h01, h00); return [x0, z1 + (z0 - z1) * u];
  }

  function contourInterval(){
    var v = num(AR.doc && AR.doc.ext && AR.doc.ext[FAM] && AR.doc.ext[FAM].interval, 0);
    return v > 0 ? v : 1;
  }
  function setInterval_(v){
    if(!AR.doc.ext) AR.doc.ext = {};
    if(!AR.doc.ext[FAM]) AR.doc.ext[FAM] = {};
    AR.doc.ext[FAM].interval = v;
  }

  function removeContours(){
    var grp = AR._stContour;
    if(!grp) return;
    grp.traverse(function(o){
      if(o.geometry) o.geometry.dispose();
      if(o.material){
        if(o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
    });
    AR.scene.remove(grp);
    AR._stContour = null;
  }

  function levelSprite(level, x, y, z){
    var cv = document.createElement('canvas');
    cv.width = 128; cv.height = 48;
    var g2 = cv.getContext('2d');
    g2.font = 'bold 30px sans-serif';
    g2.textAlign = 'center'; g2.textBaseline = 'middle';
    g2.fillStyle = 'rgba(12,16,20,0.72)';
    g2.fillRect(0, 0, 128, 48);
    g2.fillStyle = '#ffe6ad';
    g2.fillText(arFmt(level) + ' m', 64, 25);
    var tex = new THREE.CanvasTexture(cv);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, transparent: true, depthTest: false}));
    sp.position.set(x, y, z);
    sp.scale.set(6, 2.25, 1);
    sp.renderOrder = 998;
    return sp;
  }

  function buildContours(){
    removeContours();
    var g = theGround();
    if(!g) return null;
    var iv = contourInterval();
    var p = g.p || {}, sc = num(g.s, 1) || 1;
    var w = Math.max(1, Math.abs(num(p.w, 200))), dd = Math.max(1, Math.abs(num(p.d, 200)));
    var size = Math.max(w, dd);
    var cell = size / CONTOUR_CELL_DIV;
    var nx = Math.max(4, Math.min(CONTOUR_MAX_CELLS, Math.round(w / cell)));
    var nz = Math.max(4, Math.min(CONTOUR_MAX_CELLS, Math.round(dd / cell)));
    var H = heightFn(g), i, j;
    var hs = new Float64Array((nx + 1) * (nz + 1));
    var xs = new Float64Array((nx + 1) * (nz + 1)), zs = new Float64Array((nx + 1) * (nz + 1));
    var lo = Infinity, hi = -Infinity;
    for(j = 0; j <= nz; j++){
      var lz = -dd / 2 + j / nz * dd;
      for(i = 0; i <= nx; i++){
        var lx = -w / 2 + i / nx * w;
        var W = localToWorld(g, lx, lz), idx = j * (nx + 1) + i;
        xs[idx] = W.x; zs[idx] = W.z;
        var h = H(W.x, W.z);
        hs[idx] = h;
        if(h < lo) lo = h;
        if(h > hi) hi = h;
      }
    }
    if(!isFinite(lo) || !isFinite(hi) || hi - lo < 1e-6){
      arToast('The ground is level — there is nothing for a contour to follow.', 'warn');
      return null;
    }
    var k0 = Math.ceil(lo / iv), k1 = Math.floor(hi / iv);
    if(k1 - k0 + 1 > CONTOUR_MAX_LEVELS) k1 = k0 + CONTOUR_MAX_LEVELS - 1;
    var pos = [], col = [], majors = {}, nSeg = 0, nMaj = 0;
    var cMinor = new THREE.Color(CONTOUR_COL), cMajor = new THREE.Color(CONTOUR_MAJOR);
    for(var kk = k0; kk <= k1; kk++){
      var L = kk * iv, major = (kk % 5 === 0);
      var C = major ? cMajor : cMinor, y = L + 0.02;
      for(j = 0; j < nz; j++) for(i = 0; i < nx; i++){
        var a = j * (nx + 1) + i, b = a + 1, c = a + nx + 1, e = c + 1;
        var h00 = hs[a], h10 = hs[b], h01 = hs[c], h11 = hs[e];
        var ci = (h00 > L ? 1 : 0) | (h10 > L ? 2 : 0) | (h11 > L ? 4 : 0) | (h01 > L ? 8 : 0);
        var segs = MS[ci];
        if(!segs.length) continue;
        for(var q = 0; q < segs.length; q++){
          var P = edgePoint(segs[q][0], xs[a], xs[b], zs[a], zs[c], h00, h10, h11, h01, L);
          var Q = edgePoint(segs[q][1], xs[a], xs[b], zs[a], zs[c], h00, h10, h11, h01, L);
          pos.push(P[0], y, P[1], Q[0], y, Q[1]);
          col.push(C.r, C.g, C.b, C.r, C.g, C.b);
          nSeg++;
          if(major && !majors[kk]) majors[kk] = [L, P[0], y + 0.4, P[1]];
        }
      }
      if(major && majors[kk]) nMaj++;
    }
    if(!pos.length){
      arToast('No contour crosses this ground at <b>' + arFmt(iv) + ' m</b> — try a finer interval.', 'warn');
      return null;
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    var mat = new THREE.LineBasicMaterial({vertexColors: true, transparent: true, opacity: 0.9});
    var lines = new THREE.LineSegments(geo, mat);
    lines.name = 'site_terrain_contours';
    lines.renderOrder = 997;
    var grp = new THREE.Group();
    grp.name = 'site_terrain_contour_group';
    grp.add(lines);
    for(var m in majors) if(majors.hasOwnProperty(m)){
      var s = majors[m];
      grp.add(levelSprite(s[0], s[1], s[2], s[3]));
    }
    AR.scene.add(grp);
    AR._stContour = grp;
    AR._stContourInfo = {interval: iv, levels: k1 - k0 + 1, majors: nMaj, segments: nSeg,
                         vertices: pos.length / 3, min: lo, max: hi, grid: [nx, nz]};
    return AR._stContourInfo;
  }

  AR_EXT.tools.st_contour = {
    assist: 1, tog: 1,
    on: function(){ return !!AR._stContourOn; },
    tip: 'Contours — lines of equal height across the ground at a chosen interval, every fifth one heavier and labelled',
    act: function(opt){
      var o = isObj(opt) ? opt : {};
      if(AR._stContourOn && o.interval === undefined){
        AR._stContourOn = false;
        removeContours();
        arToast('Contours off.');
        return;
      }
      if(!theGround()){ arToast('There is no ground yet — press <b>Terrain</b> first.', 'warn'); return; }
      var iv;
      if(o.interval !== undefined) iv = num(o.interval, contourInterval());
      else iv = num(prompt('Contour interval in metres', String(contourInterval())), contourInterval());
      if(!(iv > 0)){ arToast('A contour interval must be greater than zero.', 'bad'); return; }
      setInterval_(iv);
      AR._stContourOn = true;
      var info = buildContours();
      if(!info){ AR._stContourOn = false; return; }
      arDirty(true);
      arToast('Contours at <b>' + arFmt(iv) + ' m</b>: ' + info.levels + ' level'
            + (info.levels === 1 ? '' : 's') + ' from ' + arFmt(info.min) + ' to ' + arFmt(info.max)
            + ' m, ' + info.majors + ' labelled.');
    }
  };

  /* ── st_cutfill ───────────────────────────────────────────────────────── */
  function slabsFor(which){
    var all = AR.objs.filter(function(o){ return !o.hidden && o.kind === 'slab'; });
    if(which === 'all') return all;
    var sel = arSelRecs().filter(function(o){ return o.kind === 'slab'; });
    return sel.length ? sel : all;
  }
  /* the volumes between H(x, z) and a slab's base, on a 0.25 m grid over its
     own footprint — cut is ground ABOVE the base, fill is ground BELOW it */
  function volumesFor(H, rec, base){
    var e = extentOf(rec);
    if(!e) return null;
    var nx = Math.max(1, Math.min(400, Math.round(e.w / CUTFILL_CELL)));
    var nz = Math.max(1, Math.min(400, Math.round(e.d / CUTFILL_CELL)));
    var sx = e.w / nx, sz = e.d / nz, a = sx * sz;
    var c = Math.cos(e.ry), s = Math.sin(e.ry);
    var cut = 0, fill = 0, i, j;
    for(j = 0; j < nz; j++){
      var lz = -e.d / 2 + (j + 0.5) * sz;
      for(i = 0; i < nx; i++){
        var lx = -e.w / 2 + (i + 0.5) * sx;
        var wx = e.x + lx * c + lz * s, wz = e.z - lx * s + lz * c;
        var dh = H(wx, wz) - base;
        if(dh > 0) cut += dh * a; else fill += -dh * a;
      }
    }
    return {cut: cut, fill: fill, net: cut - fill, area: e.w * e.d, samples: nx * nz};
  }

  function cutFillReport(which, level){
    var g = theGround();
    if(!g){ arToast('There is no ground to measure against — press <b>Terrain</b> first.', 'warn'); return null; }
    var recs = slabsFor(which);
    if(!recs.length){ arToast('No slab to measure — draw one, or select it.', 'warn'); return null; }
    var H = heightFn(g), rows = [], tc = 0, tf = 0;
    recs.forEach(function(r){
      var base = (level === undefined || level === null) ? num(r.y, 0) : num(level, num(r.y, 0));
      var v = volumesFor(H, r, base);
      if(!v) return;
      v.id = r.id; v.name = r.name || arKindLabel(r.kind); v.base = base;
      rows.push(v);
      tc += v.cut; tf += v.fill;
    });
    var out = {which: which, rows: rows, cut: tc, fill: tf, net: tc - tf,
               trucks: Math.ceil(Math.max(tc, tf) / TRUCK_M3), truck_m3: TRUCK_M3};
    AR._stCutFill = out;
    var h = '<p class="ar-note">Earthwork between the ground and each slab\'s base, sampled on a '
          + CUTFILL_CELL + ' m grid. <b>Cut</b> is ground above the base that has to come out; '
          + '<b>fill</b> is ground below it that has to go in.</p>';
    var body = [['<b>slab</b>', '<b>base m · cut m³ · fill m³ · net m³</b>']];
    rows.forEach(function(v){
      body.push([esc(v.name), fmt(v.base, 2) + ' · ' + fmt(v.cut, 1) + ' · ' + fmt(v.fill, 1)
                 + ' · ' + fmt(v.net, 1)]);
    });
    body.push(['<b>total cut</b>', '<b>' + fmt(tc, 1) + ' m³</b>']);
    body.push(['<b>total fill</b>', '<b>' + fmt(tf, 1) + ' m³</b>']);
    body.push(['<b>net (cut − fill)</b>', '<b>' + fmt(tc - tf, 1) + ' m³</b>']);
    body.push(['truck loads at ' + TRUCK_M3 + ' m³', String(out.trucks)]);
    h += arRows(body);
    if(rows.length === 1)
      h += '<p><button ' + BTN + ' onclick="siteTerrainBalance()">balance cut and fill</button> '
         + '<small>— move the slab to the elevation where the two are equal.</small></p>';
    arSheet('Cut and fill', h);
    return out;
  }

  /* the elevation at which cut equals fill, by bisection on net(y) — net is
     monotonically decreasing in y, so a plain bisection converges */
  function balanceLevel(H, rec){
    var e = extentOf(rec);
    if(!e) return null;
    var lo = Infinity, hi = -Infinity, i, j, n = 12;
    for(j = 0; j <= n; j++) for(i = 0; i <= n; i++){
      var lx = -e.w / 2 + i / n * e.w, lz = -e.d / 2 + j / n * e.d;
      var c = Math.cos(e.ry), s = Math.sin(e.ry);
      var h = H(e.x + lx * c + lz * s, e.z - lx * s + lz * c);
      if(h < lo) lo = h;
      if(h > hi) hi = h;
    }
    if(!isFinite(lo) || !isFinite(hi)) return null;
    if(hi - lo < 1e-6) return lo;
    var a = lo, b = hi;
    for(var it = 0; it < 40; it++){
      var mid = (a + b) / 2, v = volumesFor(H, rec, mid);
      if(!v) return null;
      if(v.net > 0) a = mid; else b = mid;
      if(b - a < 1e-4) break;
    }
    return (a + b) / 2;
  }

  window.siteTerrainBalance = function(){
    var last = AR._stCutFill;
    if(!last || last.rows.length !== 1){ arToast('Select one slab and run Cut and fill first.', 'warn'); return; }
    var rec = arFind(last.rows[0].id), g = theGround();
    if(!rec || !g){ arToast('That slab is gone.', 'bad'); return; }
    var H = heightFn(g), lv = balanceLevel(H, rec);
    if(lv === null){ arToast('Cut and fill cannot be balanced here.', 'bad'); return; }
    arPush();
    rec.y = Math.round(lv * 1000) / 1000;
    arApplyTransform(rec);
    arDirty(true); arPanel(); arSelSync();
    arToast('<b>' + esc(rec.name || 'Slab') + '</b> set to <b>' + fmt(rec.y, 3) + ' m</b> — cut balances fill.');
    cutFillReport('selection', undefined);
  };

  AR_EXT.tools.st_cutfill = {
    assist: 1,
    tip: 'Cut and fill — the earthwork volumes between the existing ground and each slab, per slab and in total, with the balancing level',
    act: function(opt){
      var o = isObj(opt) ? opt : {};
      var which = o.which === 'all' ? 'all'
                : (o.which === 'selection' ? 'selection' : (AR.sel.length ? 'selection' : 'all'));
      cutFillReport(which, o.level);
    }
  };

  /* ── keep the contours current ────────────────────────────────────────── */
  AR_EXT.ready.push(function(){
    /* arGroundRefresh is a function declaration — a writable global. The base
       coalesces its rebuild into ONE animation frame, so the recompute goes a
       frame after that one. */
    var base = arGroundRefresh;
    arGroundRefresh = function(rec){
      base(rec);
      if(!AR._stContourOn) return;
      if(AR._stContourRAF) return;
      AR._stContourRAF = requestAnimationFrame(function(){
        requestAnimationFrame(function(){
          AR._stContourRAF = 0;
          if(AR._stContourOn) buildContours();
        });
      });
    };
  });

  /* the family's own arithmetic, for tests_arch_ext/test_site_terrain.py */
  AR_EXT.site_terrain = {theGround: theGround, buildContours: buildContours, removeContours: removeContours,
                         heightFn: heightFn, cutFillReport: cutFillReport, balanceLevel: balanceLevel,
                         cellCentre: cellCentre, sculptKinds: sculptKinds, SCULPT_DEF: SCULPT_DEF,
                         GROUND_DEF: GROUND_DEF};
})();
