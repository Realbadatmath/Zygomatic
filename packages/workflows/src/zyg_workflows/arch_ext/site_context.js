// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* site_context — the five icons that put a drawing on a real piece of ground:
     st_bound  Site boundary  (MODE)   click the corners, Enter closes; area + setbacks
     st_sat    Aerial         (SWITCH) an OSM / Esri tile mosaic under the drawing, in metres
     st_veg    Planting       (ACTION) scatter trees inside the boundary or the selection
     st_road   Roads          (MODE)   click a chain of points, one road record per leg
     f_img     Underlay       (ACTION) a scanned plan or sketch on the ground, to scale

   ONE new kind, `site_boundary`: p {pts:[[x,z],...] LOCAL metres, closed:1}.
   It is a VOID kind — a line loop with tick posts and an area label, no solid,
   nothing in Blender. Everything else here reuses the studio's own kinds
   (`tree`, `road`) so the boundary is the only thing anybody has to learn.

   WHERE STATE LIVES
     AR.doc.ext.light_sun     = {lat, lon, north}   shared with the sun family:
                                the geolocation belongs to the DRAWING, not to
                                whichever icon asked for it first.
     AR.doc.ext.site_context  = {sat:{source, zoom, on}, underlay:{data_url, width_m, opacity, rot}}
     rec.meta.setback         = the inset distance, on a setback polygon
     rec.grp                  = 'planting' / 'roads'

   ATTRIBUTION IS NOT OPTIONAL. OSM tiles are ODbL and Esri's World Imagery is
   licensed for display with a credit; while the aerial is on, a corner div
   says so. Turning the underlay off removes both the tiles and the credit —
   they appear and disappear together on purpose. */
(function(){
  var SC = {
    bpts: [],            /* the boundary being clicked                       */
    rpts: [],            /* the road chain being clicked                     */
    roadW: 6,
    sat: null,           /* THREE.Group of the tile mosaic                   */
    satInfo: null,
    credit: null,        /* the attribution div                             */
    under: null,         /* THREE.Mesh of the image underlay                */
    pending: null,       /* the promise of the last async act()             */
    extSeen: null        /* identity of the ext object we last applied      */
  };
  var TAU = Math.PI * 2;
  var EXT_BASE = '/inspect/api/architecture/ext/site_context/';
  var CREDIT = {osm: '&copy; OpenStreetMap contributors',
                esri: '&copy; Esri, Maxar, Earthstar Geographics'};

  /* ── small arithmetic ──────────────────────────────────────────────────── */
  function n(v, d){ v = Number(v); return isFinite(v) ? v : d; }
  function ring(v){                       /* [[x,z],…] -> clean pairs        */
    var out = [], i, a, x, z;
    if(Object.prototype.toString.call(v) !== '[object Array]') return out;
    for(i = 0; i < v.length; i++){
      a = v[i];
      if(Object.prototype.toString.call(a) !== '[object Array]' || a.length < 2) continue;
      x = Number(a[0]); z = Number(a[1]);
      if(isFinite(x) && isFinite(z)) out.push([x, z]);
    }
    if(out.length > 3 && Math.abs(out[0][0] - out[out.length - 1][0]) < 1e-9
                      && Math.abs(out[0][1] - out[out.length - 1][1]) < 1e-9) out.pop();
    return out;
  }
  function shoelace(pts){                 /* SIGNED area; +ve = anticlockwise in x/z */
    var a = 0, i, j;
    for(i = 0, j = pts.length - 1; i < pts.length; j = i++)
      a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1]);
    return a / 2;
  }
  function areaOf(pts){ return Math.abs(shoelace(pts)); }
  function centroid(pts){
    var sx = 0, sz = 0, i;
    for(i = 0; i < pts.length; i++){ sx += pts[i][0]; sz += pts[i][1]; }
    return [sx / pts.length, sz / pts.length];
  }
  function inPoly(x, z, pts){             /* ray cast, pts in the same frame  */
    var inside = false, i, j, xi, zi, xj, zj;
    for(i = 0, j = pts.length - 1; i < pts.length; j = i++){
      xi = pts[i][0]; zi = pts[i][1]; xj = pts[j][0]; zj = pts[j][1];
      if(((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi) + xi)) inside = !inside;
    }
    return inside;
  }
  function distToEdges(x, z, pts){        /* shortest distance to the ring    */
    var best = Infinity, i, j, ax, az, bx, bz, dx, dz, t, px, pz;
    for(i = 0, j = pts.length - 1; i < pts.length; j = i++){
      ax = pts[j][0]; az = pts[j][1]; bx = pts[i][0]; bz = pts[i][1];
      dx = bx - ax; dz = bz - az;
      t = (dx * dx + dz * dz) < 1e-12 ? 0 : ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz);
      t = Math.max(0, Math.min(1, t));
      px = ax + dx * t; pz = az + dz * t;
      best = Math.min(best, Math.hypot(x - px, z - pz));
    }
    return best;
  }
  /* Inset by d along each vertex's bisector. Simple on purpose: a convex or
     mildly concave site plot is what a setback is drawn on, and the caller is
     told when the result stops being a polygon. */
  function offsetPoly(pts, d){
    var sign = shoelace(pts) > 0 ? 1 : -1, out = [], i, N = pts.length;
    for(i = 0; i < N; i++){
      var p = pts[(i - 1 + N) % N], c = pts[i], q = pts[(i + 1) % N];
      var n1 = norm(p, c), n2 = norm(c, q);
      var bx = n1[0] + n2[0], bz = n1[1] + n2[1];
      var L = Math.hypot(bx, bz);
      if(L < 1e-9){ bx = n1[0]; bz = n1[1]; L = Math.hypot(bx, bz) || 1; }
      var cosHalf = Math.max(0.25, (n1[0] * bx + n1[1] * bz) / L);   /* mitre cap */
      out.push([c[0] + sign * bx / L * d / cosHalf, c[1] + sign * bz / L * d / cosHalf]);
    }
    return out;
    /* inward normal of the edge a->b for an anticlockwise ring */
    function norm(a, b){
      var dx = b[0] - a[0], dz = b[1] - a[1], L = Math.hypot(dx, dz) || 1;
      return [dz / L, -dx / L];
    }
  }
  function fmtArea(m2){
    return m2 >= 10000 ? (m2 / 10000).toFixed(3) + ' ha (' + Math.round(m2) + ' m²)'
                       : m2.toFixed(m2 < 100 ? 2 : 0) + ' m²';
  }
  /* The legs of a closed traverse, the way a surveyor writes them down: a
     LENGTH and a BEARING clockwise from north. North on the plan is −Z, so the
     bearing of (dx, dz) is atan2(dx, −dz); the drawing's own north angle
     (doc.ext.light_sun.north, shared with the sun family) turns a grid bearing
     into a true one. */
  function legsOf(pts){
    var out = [], i, N = pts.length, north = n(sunExt().north, 0);
    for(i = 0; i < N; i++){
      var a = pts[i], b = pts[(i + 1) % N];
      var dx = b[0] - a[0], dz = b[1] - a[1];
      out.push({i: i + 1, j: (i + 1) % N + 1,
                len: Math.hypot(dx, dz),
                bearing: (Math.atan2(dx, -dz) * 180 / Math.PI + north + 360) % 360});
    }
    return out;
  }
  function fmtBearing(deg){
    var d = Math.floor(deg), m = Math.round((deg - d) * 60);
    if(m === 60){ m = 0; d = (d + 1) % 360; }
    return (d < 100 ? (d < 10 ? '00' : '0') : '') + d + '° ' + (m < 10 ? '0' : '') + m + '′';
  }
  /* the survey report the icon's tooltip promises: bearings and lengths */
  function surveySheet(pts, title, extra){
    var legs = legsOf(pts), rows = [], per = 0;
    legs.forEach(function(L){
      per += L.len;
      rows.push(['Leg ' + L.i + '→' + L.j, L.len.toFixed(3) + ' m &middot; ' + fmtBearing(L.bearing)]);
    });
    rows.unshift(['Area', fmtArea(areaOf(pts))]);
    rows.splice(1, 0, ['Perimeter', per.toFixed(3) + ' m'], ['Corners', String(pts.length)]);
    arSheet(title || 'Site boundary', arRows(rows)
      + '<div style="opacity:.7;margin-top:6px">Bearings run clockwise from north'
      + (n(sunExt().north, 0) ? ' (drawing north ' + n(sunExt().north, 0) + '°)' : ' (grid north, −Z)')
      + '. ' + (extra || 'A setback insets a second line off this one.') + '</div>');
    return {legs: legs, perimeter: per, area: areaOf(pts)};
  }
  /* mulberry32 — the same stream arch_assistant_ext/site_context.py draws, so
     the icon and the assistant twin scatter a seed the same way. */
  function mulberry(seed){
    var a = (seed >>> 0) || 1;
    return function(){
      a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) | 0;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  /* 'AB12' -> the centre of that cell in metres, at the drawing's LIVE cell size */
  function cellXZ(name){
    var m = /^([A-Za-z]+)\s*(\d+)$/.exec(String(name || '').trim());
    if(!m) return null;
    var s = m[1].toUpperCase(), c = 0, i;
    for(i = 0; i < s.length; i++) c = c * 26 + (s.charCodeAt(i) - 64);
    c -= 1;
    var r = parseInt(m[2], 10) - 1;
    if(!(c >= 0 && r >= 0)) return null;
    return {x: AR_CELL_O + (c + 0.5) * AR_CELL_M, z: AR_CELL_O + (r + 0.5) * AR_CELL_M};
  }
  function cellsToPts(cells){
    var out = [], i, p;
    if(Object.prototype.toString.call(cells) !== '[object Array]') return out;
    for(i = 0; i < cells.length; i++){
      p = (typeof cells[i] === 'string') ? cellXZ(cells[i])
        : (cells[i] && isFinite(cells[i].x) ? {x: Number(cells[i].x), z: Number(cells[i].z)} : null);
      if(p) out.push([p.x, p.z]);
    }
    return out;
  }
  function ext(){
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    if(!AR.doc.ext.site_context || typeof AR.doc.ext.site_context !== 'object') AR.doc.ext.site_context = {};
    return AR.doc.ext.site_context;
  }
  function sunExt(){
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    if(!AR.doc.ext.light_sun || typeof AR.doc.ext.light_sun !== 'object') AR.doc.ext.light_sun = {};
    return AR.doc.ext.light_sun;
  }

  /* ── the kind: a line polygon with tick posts ──────────────────────────── */
  /* r144 LineBasicMaterial ignores dashes without computeLineDistances and a
     LineDashedMaterial, and a part cannot carry its own material — so the
     surveyor's dashed line is drawn the way a surveyor actually pegs one out:
     a thin solid line through the corners plus a short post every 5 m. */
  AR_EXT.geom.site_boundary = function(p, k){
    var THREE = k.THREE, pts = ring(p.pts), i, v = [];
    if(pts.length < 2) pts = [[-10, -10], [10, -10], [10, 10], [-10, 10]];
    var closed = p.closed === undefined ? true : !!p.closed;
    var N = closed ? pts.length : pts.length - 1;
    for(i = 0; i < N; i++){
      var a = pts[i], b = pts[(i + 1) % pts.length];
      v.push(new THREE.Vector3(a[0], 0.02, a[1]), new THREE.Vector3(b[0], 0.02, b[1]));
      /* tick posts every 5 m along the leg, 0.5 m tall */
      var L = Math.hypot(b[0] - a[0], b[1] - a[1]), steps = Math.floor(L / 5), s;
      for(s = 0; s <= steps; s++){
        var t = L < 1e-6 ? 0 : (s * 5) / L;
        var px = a[0] + (b[0] - a[0]) * t, pz = a[1] + (b[1] - a[1]) * t;
        v.push(new THREE.Vector3(px, 0.02, pz), new THREE.Vector3(px, 0.52, pz));
      }
    }
    return [{g: new THREE.BufferGeometry().setFromPoints(v), line: 1}];
  };
  AR_EXT.label.site_boundary = 'Site boundary';

  /* ── the area label ────────────────────────────────────────────────────── */
  function labelSprite(text){
    var cv = document.createElement('canvas'), pad = 12;
    var ctx = cv.getContext('2d');
    ctx.font = '600 36px system-ui, sans-serif';
    var w = Math.ceil(ctx.measureText(text).width) + pad * 2;
    cv.width = w; cv.height = 56;
    ctx = cv.getContext('2d');
    ctx.font = '600 36px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(8,14,20,0.78)';
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.fillStyle = '#7ff0ff';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, pad, cv.height / 2);
    var tex = new THREE.CanvasTexture(cv);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, transparent: true, depthTest: false}));
    sp.scale.set(cv.width / 56 * 3, 3, 1);
    sp.userData.scText = text;      /* what the label SAYS, readable without pixels */
    return sp;
  }
  function labelFor(rec){
    var pts = ring(rec.p && rec.p.pts);
    if(pts.length < 3) return null;
    var a = areaOf(pts), c = centroid(pts);
    var sp = labelSprite((rec.meta && rec.meta.setback ? 'setback ' + rec.meta.setback + ' m — ' : '') + fmtArea(a));
    sp.position.set(c[0], 2.2, c[1]);
    sp.userData.arId = rec.id;
    sp.userData.scLabel = 1;
    /* r144's Sprite shares ONE module-level geometry between every sprite in
       the page: letting arDisposeNode call geometry.dispose() on it would empty
       the buffer for all of them. `arShared` is the studio's own flag for
       exactly that (pack assets), and our arRebuild wrapper disposes the
       canvas texture and the material itself. */
    sp.userData.arShared = 1;
    return sp;
  }

  /* ── the boundary as the rest of the studio sees it ────────────────────── */
  function boundaryRecs(){
    return AR.objs.filter(function(o){ return o.kind === 'site_boundary' && !(o.meta && o.meta.setback); });
  }
  function worldPoly(rec){
    var pts = ring(rec.p && rec.p.pts), c = Math.cos(rec.ry || 0), s = Math.sin(rec.ry || 0);
    return pts.map(function(q){
      /* the studio's node rotation about +Y: x' = x cos + z sin, z' = -x sin + z cos */
      return [rec.x + q[0] * c + q[1] * s, rec.z - q[0] * s + q[1] * c];
    });
  }
  function boundaryPoly(){
    var r = boundaryRecs();
    return r.length ? worldPoly(r[r.length - 1]) : null;
  }

  function makeBoundary(worldPts, meta){
    var pts = ring(worldPts);
    if(pts.length < 3) return null;
    var c = centroid(pts);
    var local = pts.map(function(q){ return [Math.round((q[0] - c[0]) * 1e4) / 1e4,
                                             Math.round((q[1] - c[1]) * 1e4) / 1e4]; });
    var rec = arNewObj('site_boundary', {pts: local, closed: 1}, c[0], c[1], 0);
    rec.grp = 'site';
    if(meta) rec.meta = meta;
    arRebuild(rec);
    return rec;
  }

  /* ── st_bound: the mode ────────────────────────────────────────────────── */
  function boundHint(){
    if(!SC.bpts.length) return 'Click the first corner of the site. <b>Enter</b> closes the boundary, <b>Esc</b> drops it.';
    var a = SC.bpts.length >= 3 ? ' &middot; area so far <b>' + fmtArea(areaOf(SC.bpts)) + '</b>' : '';
    return SC.bpts.length + ' corner' + (SC.bpts.length === 1 ? '' : 's') +
           ' &middot; <b>Enter</b> closes' + a;
  }
  function boundRubber(P){
    if(!SC.bpts.length || !P){ AR.rubber.visible = false; return; }
    var v = [], i;
    for(i = 0; i < SC.bpts.length; i++) v.push(new THREE.Vector3(SC.bpts[i][0], 0.03, SC.bpts[i][1]));
    v.push(new THREE.Vector3(P.x, 0.03, P.z));
    v.push(new THREE.Vector3(SC.bpts[0][0], 0.03, SC.bpts[0][1]));
    AR.rubber.geometry.setFromPoints(v);
    AR.rubber.visible = true;
  }
  function closeBoundary(){
    if(SC.bpts.length < 3){ arToast('A site boundary needs at least three corners.', 'warn'); return null; }
    arPush();
    var rec = makeBoundary(SC.bpts, null);
    SC.bpts = [];
    AR.rubber.visible = false;
    if(rec){
      arSelect([rec.id]); arPanel(); arOutliner();
      surveySheet(worldPoly(rec), 'Site boundary');
      arToast('Site boundary closed — <b>' + fmtArea(areaOf(ring(rec.p.pts))) + '</b>. '
            + '<a href="#" onclick="site_context.setbackPrompt();return false;">Add a setback&hellip;</a>');
    }
    arHint(boundHint());
    return rec;
  }
  AR_EXT.modes.st_bound = {
    click: function(P){ if(!P) return; SC.bpts.push([P.x, P.z]); arHint(boundHint()); boundRubber(P); },
    move: function(P){ boundRubber(P); },
    hint: function(){ return boundHint(); },
    cancel: function(){ SC.bpts = []; AR.rubber.visible = false; },
    key: function(e){
      if(e.key === 'Enter'){ closeBoundary(); return true; }
      if(e.key === 'Escape'){ SC.bpts = []; AR.rubber.visible = false; arHint(boundHint()); return true; }
      return false;
    }
  };
  AR_EXT.tools.st_bound = {
    assist: 1, tog: 1,
    tip: 'Site boundary — click the corners, Enter closes it; the area is labelled and a setback insets a second line',
    on: function(){ return AR.tool === 'st_bound'; },
    act: function(opt){
      if(opt && typeof opt === 'object' && opt.setback !== undefined){ doSetback(Number(opt.setback)); return; }
      var pts = (opt && typeof opt === 'object') ? cellsToPts(opt.cells) : [];
      if(pts.length >= 3){
        arPush();
        var rec = makeBoundary(pts, null);
        if(rec){ arSelect([rec.id]); arPanel(); arOutliner();
                 surveySheet(worldPoly(rec), 'Site boundary');
                 arToast('Site boundary — <b>' + fmtArea(areaOf(ring(rec.p.pts))) + '</b>.'); }
        return;
      }
      if(AR.tool === 'st_bound'){ SC.bpts = []; arToolApply('select'); return; }
      SC.bpts = [];
      arToolApply('st_bound');
    }
  };
  function doSetback(d){
    var poly = boundaryPoly();
    if(!poly){ arToast('Draw a site boundary first — a setback is measured off it.', 'warn'); return null; }
    d = n(d, NaN);
    if(!isFinite(d) || d <= 0){ arToast('A setback needs a distance in metres.', 'warn'); return null; }
    var inset = offsetPoly(poly, d);
    if(areaOf(inset) < 0.01 || areaOf(inset) >= areaOf(poly)){
      arToast('A ' + d + ' m setback leaves nothing of this site.', 'warn'); return null;
    }
    arPush();
    var rec = makeBoundary(inset, {setback: d});
    if(rec){
      rec.name = 'Setback ' + d + ' m';
      arSelect([rec.id]); arPanel(); arOutliner();
      surveySheet(worldPoly(rec), 'Setback ' + d + ' m',
                  'This is the buildable area, ' + d + ' m inside the site boundary.');
      arToast('Setback <b>' + d + ' m</b> — buildable area <b>' + fmtArea(areaOf(ring(rec.p.pts))) + '</b>.');
    }
    return rec;
  }

  /* ── st_road: the mode ─────────────────────────────────────────────────── */
  function roadHint(){
    if(!SC.rpts.length) return 'Click where the road starts &middot; width <b>' + SC.roadW +
                               ' m</b> &middot; <b>Enter</b> or <b>Esc</b> ends the run.';
    return SC.rpts.length + ' point' + (SC.rpts.length === 1 ? '' : 's') + ' &middot; width <b>' + SC.roadW +
           ' m</b> &middot; <b>Enter</b> ends the run.';
  }
  function roadLeg(a, b, w){
    var len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if(len < 1e-3) return null;
    var rec = arNewObj('road', {len: len, w: w, t: 0.08}, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0);
    rec.ry = Math.atan2(-(b[1] - a[1]), b[0] - a[0]);
    rec.grp = 'roads';
    rec.mat = 'mat_asphalt';
    arApplyTransform(rec); arApplyMat(rec);
    return rec;
  }
  AR_EXT.modes.st_road = {
    click: function(P){
      if(!P) return;
      if(SC.rpts.length){
        arPush();
        var r = roadLeg(SC.rpts[SC.rpts.length - 1], [P.x, P.z], SC.roadW);
        if(r){ arSelect([r.id], true); arPanel(); arOutliner(); }
        else AR.undo.pop();
      }
      SC.rpts.push([P.x, P.z]);
      AR.rubber.visible = false;
      arHint(roadHint());
    },
    move: function(P){
      if(!SC.rpts.length || !P){ AR.rubber.visible = false; return; }
      var a = SC.rpts[SC.rpts.length - 1];
      AR.rubber.geometry.setFromPoints([new THREE.Vector3(a[0], 0.03, a[1]), new THREE.Vector3(P.x, 0.03, P.z)]);
      AR.rubber.visible = true;
      arHint('<b>' + Math.hypot(P.x - a[0], P.z - a[1]).toFixed(2) + ' m</b> &middot; width ' + SC.roadW + ' m');
    },
    hint: function(){ return roadHint(); },
    cancel: function(){ SC.rpts = []; AR.rubber.visible = false; },
    key: function(e){
      if(e.key === 'Enter' || e.key === 'Escape'){
        SC.rpts = []; AR.rubber.visible = false; arHint(roadHint()); return true;
      }
      return false;
    }
  };
  AR_EXT.tools.st_road = {
    assist: 1, tog: 1,
    tip: 'Roads — click a chain of points and each leg becomes a road of the width you set; Enter ends the run',
    on: function(){ return AR.tool === 'st_road'; },
    act: function(opt){
      var o = (opt && typeof opt === 'object') ? opt : null;
      var w = o ? n(o.width, 6) : n(prompt('Road width in metres:', String(SC.roadW)), SC.roadW);
      SC.roadW = Math.max(0.5, Math.min(60, w));
      var pts = o ? cellsToPts(o.cells) : [];
      if(pts.length >= 2){
        arPush();
        var ids = [], i, r;
        for(i = 1; i < pts.length; i++){ r = roadLeg(pts[i - 1], pts[i], SC.roadW); if(r) ids.push(r.id); }
        if(!ids.length){ AR.undo.pop(); arToast('Those points are all in the same place.', 'warn'); return; }
        arSelect(ids); arPanel(); arOutliner();
        arToast('Drew <b>' + ids.length + '</b> road leg' + (ids.length === 1 ? '' : 's') + ' at ' + SC.roadW + ' m wide.');
        return;
      }
      if(AR.tool === 'st_road'){ SC.rpts = []; arToolApply('select'); return; }
      SC.rpts = [];
      arToolApply('st_road');
    }
  };

  /* ── st_veg: planting ──────────────────────────────────────────────────── */
  /* what a tree IS here: whatever tree kind the drawing knows about. The
     forests family registers its own; if none is loaded the studio's own
     `tree` kind is drawn, which is always there. */
  function treeKind(query, species){
    var want = String(species || query || 'tree').toLowerCase(), hits = [], i, j, k;
    for(i = 0; i < (AR.sections || []).length; i++){
      var sec = AR.sections[i];
      for(j = 0; j < (sec.groups || []).length; j++)
        for(k = 0; k < (sec.groups[j].items || []).length; k++){
          var it = sec.groups[j].items[k];
          if(!it.kind || String(it.kind).indexOf('tree') < 0) continue;
          if(AR_EXT.geom[it.kind] || it.kind === 'tree') hits.push({kind: it.kind, p: it.p || {}, n: it.n || it.kind});
        }
    }
    var exact = hits.filter(function(h){ return h.kind.toLowerCase().indexOf(want) >= 0
                                             || String(h.n).toLowerCase().indexOf(want) >= 0; });
    var pick = (exact[0] || hits[0]);
    if(pick) return pick;
    /* nothing in the rail: the studio's own kind, with arGeom's own defaults */
    return {kind: 'tree', p: {h: 6, r_can: 2, r_trunk: 0.18}, n: 'Tree'};
  }
  function footprints(){
    var out = [];
    AR.objs.forEach(function(o){
      var p = o.p || {}, hw = 0, hd = 0;
      if(o.kind === 'slab' || o.kind === 'roof_flat'){ hw = n(p.w, 0) / 2; hd = n(p.d, 0) / 2; }
      else if(o.kind === 'wall' || o.kind === 'partition'){
        var L = n(p.len, 0) / 2, t = n(p.t, 0.2) / 2, c = Math.abs(Math.cos(o.ry || 0)), s = Math.abs(Math.sin(o.ry || 0));
        hw = L * c + t * s; hd = L * s + t * c;
      } else if(o.kind === 'slab_poly'){
        var pr = ring(p.pts); if(!pr.length) return;
        hw = Math.max.apply(null, pr.map(function(q){ return Math.abs(q[0]); }));
        hd = Math.max.apply(null, pr.map(function(q){ return Math.abs(q[1]); }));
      } else if(o.kind === 'box' || o.kind === 'massing'){ hw = n(p.w, 0) / 2; hd = n(p.d, 0) / 2; }
      else return;
      if(hw <= 0 && hd <= 0) return;
      out.push([o.x - hw - 1, o.z - hd - 1, o.x + hw + 1, o.z + hd + 1]);   /* +1 m clear */
    });
    return out;
  }
  AR_EXT.tools.st_veg = {
    assist: 1,
    tip: 'Planting — scatter trees over the site boundary (or the selection) at a real spacing, clear of the buildings',
    act: function(opt){
      var o = (opt && typeof opt === 'object') ? opt : null;
      var count = Math.max(1, Math.min(500, Math.round(o ? n(o.count, 20) : n(prompt('How many trees?', '20'), 20))));
      var inside = o ? String(o.inside || 'boundary') : 'boundary';
      var poly = null, label = '';
      if(inside === 'selection' && AR.sel.length){
        var b = arBounds(true);
        poly = [[b.c.x - b.r, b.c.z - b.r], [b.c.x + b.r, b.c.z - b.r],
                [b.c.x + b.r, b.c.z + b.r], [b.c.x - b.r, b.c.z + b.r]];
        label = 'the selection';
      } else {
        poly = boundaryPoly();
        label = 'the site boundary';
      }
      if(!poly || poly.length < 3){
        arToast('Draw a site boundary first (or select something and pass inside:"selection").', 'warn'); return;
      }
      var T = treeKind(o && o.query, o && o.species);
      var xs = poly.map(function(q){ return q[0]; }), zs = poly.map(function(q){ return q[1]; });
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
      var z0 = Math.min.apply(null, zs), z1 = Math.max.apply(null, zs);
      var boxes = footprints(), rnd = mulberry(n(o && o.seed, 20260907)), placed = [], tries = 0;
      var MIN = 3;                                    /* metres between trunks */
      while(placed.length < count && tries < count * 400){
        tries++;
        var x = x0 + rnd() * (x1 - x0), z = z0 + rnd() * (z1 - z0), i, ok = true;
        if(!inPoly(x, z, poly)) continue;
        if(distToEdges(x, z, poly) < 1) continue;      /* keep 1 m inside      */
        for(i = 0; i < boxes.length; i++)
          if(x >= boxes[i][0] && x <= boxes[i][2] && z >= boxes[i][1] && z <= boxes[i][3]){ ok = false; break; }
        if(!ok) continue;
        for(i = 0; i < placed.length; i++)
          if(Math.hypot(x - placed[i][0], z - placed[i][1]) < MIN){ ok = false; break; }
        if(!ok) continue;
        placed.push([x, z]);
      }
      if(!placed.length){ arToast('No room for a tree inside ' + label + ' that clears the buildings.', 'warn'); return; }
      arPush();
      var ids = [];
      placed.forEach(function(q){
        /* every tree gets its OWN p: sharing one object would make the
           Properties panel edit the whole wood at once. */
        var r = arNewObj(T.kind, JSON.parse(JSON.stringify(T.p)),
                         Math.round(q[0] * 1e3) / 1e3, Math.round(q[1] * 1e3) / 1e3, 0);
        r.grp = 'planting';
        r.ry = rnd() * TAU;
        arApplyTransform(r);
        ids.push(r.id);
      });
      arSelect(ids); arPanel(); arOutliner(); arSyncHoles();
      arToast('Planted <b>' + ids.length + '</b> &times; ' + esc(T.n) + ' inside ' + label +
              (ids.length < count ? ' (asked for ' + count + ' — the rest would not fit at 3 m spacing)' : '') + '.');
    }
  };

  /* ── st_sat: the aerial underlay ───────────────────────────────────────── */
  function credit(html){
    if(!SC.credit){
      var st = document.getElementById('ar-stage');
      if(!st) return;
      SC.credit = document.createElement('div');
      SC.credit.id = 'sc-attrib';
      SC.credit.style.cssText = 'position:absolute;right:8px;bottom:6px;z-index:40;pointer-events:none;'
        + 'font:11px/1.5 system-ui,sans-serif;color:#cfe6ef;background:rgba(6,12,18,.62);'
        + 'padding:2px 7px;border-radius:4px;letter-spacing:.2px;';
      st.appendChild(SC.credit);
    }
    SC.credit.innerHTML = html || '';
    SC.credit.style.display = html ? '' : 'none';
  }
  function satOff(){
    if(SC.sat){
      SC.sat.traverse(function(o){
        if(o.geometry) o.geometry.dispose();
        if(o.material){ if(o.material.map) o.material.map.dispose(); o.material.dispose(); }
      });
      AR.scene.remove(SC.sat);
      SC.sat = null;
    }
    SC.satInfo = null;
    credit('');
  }
  function satOn(o){
    var s = sunExt();
    var lat = n(s.lat, NaN), lon = n(s.lon, NaN);
    if(o && isFinite(n(o.lat, NaN))){ lat = n(o.lat, NaN); lon = n(o.lon, NaN); }
    if(!isFinite(lat) || !isFinite(lon)){
      var a = prompt('Site latitude, longitude (decimal degrees):', '52.3702, 4.8952');
      var m = String(a || '').split(',');
      lat = n(m[0], NaN); lon = n(m[1], NaN);
      if(!isFinite(lat) || !isFinite(lon)){ arToast('An aerial needs a latitude and a longitude.', 'warn'); return null; }
    }
    /* the geolocation belongs to the drawing: the sun family reads the SAME keys */
    s.lat = Math.round(lat * 1e6) / 1e6;
    s.lon = Math.round(lon * 1e6) / 1e6;
    var north = n(s.north, 0);

    var e = ext();
    var zoom = Math.max(1, Math.min(19, Math.round(o ? n(o.zoom, n(e.sat && e.sat.zoom, 18)) : n(e.sat && e.sat.zoom, 18))));
    var source = String((o && o.source) || (e.sat && e.sat.source) || 'osm').toLowerCase();
    if(!CREDIT[source]) source = 'osm';

    /* Web Mercator: metres per pixel at this latitude, 256 px to the tile */
    var mpp = 156543.03392804097 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom);
    var tileM = mpp * 256;
    var N = Math.pow(2, zoom);
    var fx = (lon + 180) / 360 * N;
    var fy = (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * N;
    var tx = Math.floor(fx), ty = Math.floor(fy);

    satOff();
    var grp = new THREE.Group(), loader = new THREE.TextureLoader(), dx, dz;
    for(dx = -1; dx <= 1; dx++) for(dz = -1; dz <= 1; dz++){
      var g = new THREE.PlaneGeometry(tileM, tileM);
      g.rotateX(-Math.PI / 2);
      var mat = new THREE.MeshBasicMaterial({color: 0x9aa4ac, depthWrite: false});
      var mesh = new THREE.Mesh(g, mat);
      /* tile +x is east (+x here), tile +y is SOUTH, which is +z in this frame */
      mesh.position.set(dx * tileM, 0, dz * tileM);
      mesh.renderOrder = -10;
      grp.add(mesh);
      (function(material, X, Y){
        loader.load(EXT_BASE + 'tile?z=' + zoom + '&x=' + X + '&y=' + Y + '&source=' + source,
          function(tex){ material.map = tex; material.color.setHex(0xffffff); material.needsUpdate = true; },
          null, function(){ /* one dead tile stays grey; the mosaic still stands */ });
      })(mat, tx + dx, ty + dz);
    }
    /* put the exact lat/lon under the site centre, not under the tile corner */
    var offE = (fx - tx - 0.5) * tileM, offS = (fy - ty - 0.5) * tileM;
    var site = boundaryPoly(), cx = 0, cz = 0;
    if(site){ var c = centroid(site); cx = c[0]; cz = c[1]; }
    grp.position.set(cx - offE, -0.01, cz - offS);
    grp.rotation.y = -north * Math.PI / 180;
    AR.scene.add(grp);

    SC.sat = grp;
    SC.satInfo = {on: true, source: source, zoom: zoom, lat: s.lat, lon: s.lon, north: north,
                  tiles: 9, tile_m: tileM, size_m: tileM * 3, mpp: mpp, x: tx, y: ty};
    e.sat = {source: source, zoom: zoom, on: true};
    SC.extSeen = AR.doc.ext;        /* ext() may have created it: do not re-apply */
    credit(CREDIT[source] + ' &middot; aerial underlay, zoom ' + zoom);
    arDirty(true);
    return SC.satInfo;
  }
  AR_EXT.tools.st_sat = {
    assist: 1, tog: 1,
    tip: 'Aerial — OpenStreetMap or Esri imagery under the drawing at the site\'s coordinates, scaled to metres',
    on: function(){ return !!SC.sat; },
    act: function(opt){
      var o = (opt && typeof opt === 'object') ? opt : null;
      if(SC.sat && !(o && o.on)){
        satOff();
        var e = ext(); e.sat = e.sat || {}; e.sat.on = false;
        SC.extSeen = AR.doc.ext;
        arToast('Aerial underlay off.');
        return;
      }
      var info = satOn(o);
      if(info) arToast('Aerial: <b>' + info.source.toUpperCase() + '</b> zoom ' + info.zoom + ' &middot; '
                     + info.size_m.toFixed(0) + ' m across &middot; ' + info.mpp.toFixed(2) + ' m/px.');
    }
  };

  /* ── f_img: the image underlay ─────────────────────────────────────────── */
  var MAX_UNDERLAY = 2 * 1024 * 1024;
  function underOff(){
    if(SC.under){
      if(SC.under.geometry) SC.under.geometry.dispose();
      if(SC.under.material){ if(SC.under.material.map) SC.under.material.map.dispose(); SC.under.material.dispose(); }
      AR.scene.remove(SC.under);
      SC.under = null;
    }
  }
  function underApply(u){
    return new Promise(function(res, rej){
      var img = new Image();
      img.onload = function(){
        underOff();
        var aspect = img.naturalHeight / (img.naturalWidth || 1);
        var w = Math.max(0.05, n(u.width_m, 10)), d = w * aspect;
        var g = new THREE.PlaneGeometry(w, d);
        g.rotateX(-Math.PI / 2);
        var tex = new THREE.Texture(img); tex.needsUpdate = true;
        var mat = new THREE.MeshBasicMaterial({map: tex, transparent: true,
                                               opacity: Math.max(0.05, Math.min(1, n(u.opacity, 0.85))),
                                               depthWrite: false});
        var mesh = new THREE.Mesh(g, mat);
        var b = AR.objs.length ? arBounds(false) : {c: {x: 0, z: 0}};
        mesh.position.set(b.c.x, -0.02, b.c.z);
        mesh.rotation.y = -n(u.rot, 0) * Math.PI / 180;
        mesh.renderOrder = -9;
        mesh.userData.scUnderlay = 1;
        AR.scene.add(mesh);
        SC.under = mesh;
        res({width_m: w, depth_m: d, px: [img.naturalWidth, img.naturalHeight]});
      };
      img.onerror = function(){ rej(new Error('that file is not an image the browser can read')); };
      img.src = u.data_url;
    });
  }
  function underSheet(){
    var u = (ext().underlay) || {};
    arSheet('Underlay image', arRows([
      ['Width', '<input id="sc-u-w" type="number" step="0.1" min="0.1" value="' + n(u.width_m, 10) + '" style="width:7em"> m'],
      ['Opacity', '<input id="sc-u-o" type="range" min="5" max="100" value="' + Math.round(n(u.opacity, 0.85) * 100) + '">'],
      ['Rotation', '<input id="sc-u-r" type="number" step="1" value="' + n(u.rot, 0) + '" style="width:7em"> &deg;'],
      ['', '<button onclick="site_context.underlayApplySheet()">Apply</button> '
         + '<button onclick="site_context.underlayRemove()">Remove</button>']
    ]) + '<div style="opacity:.7;margin-top:6px">The image sits at y = &minus;0.02 m, under the drawing plane, '
       + 'and is saved with the drawing.</div>');
  }
  function setUnderlay(u){
    var e = ext();
    e.underlay = {data_url: u.data_url, width_m: n(u.width_m, 10),
                  opacity: n(u.opacity, 0.85), rot: n(u.rot, 0)};
    SC.extSeen = AR.doc.ext;
    arDirty(true);
    return underApply(e.underlay);
  }
  AR_EXT.tools.f_img = {
    assist: 1,
    tip: 'Underlay — a scanned plan or a sketch on the ground under the drawing, scaled to a width you give in metres',
    act: function(opt){
      var o = (opt && typeof opt === 'object') ? opt : null;
      if(o && o.data_url){
        if(String(o.data_url).length > MAX_UNDERLAY){
          arToast('That image is larger than 2 MB — it would bloat every save of this drawing.', 'bad');
          SC.pending = Promise.resolve(null); return;
        }
        SC.pending = setUnderlay({data_url: o.data_url, width_m: n(o.width_m, 10),
                                  opacity: n(o.opacity, 0.85), rot: n(o.rot, 0)})
          .then(function(r){ arToast('Underlay placed — <b>' + r.width_m.toFixed(2) + ' &times; '
                                   + r.depth_m.toFixed(2) + ' m</b>.'); underSheet(); return r; })
          .catch(function(e){ arToast(esc(e.message || String(e)), 'bad'); return null; });
        return;
      }
      if(o && o.sheet){ underSheet(); return; }
      /* a person: the file picker */
      var inp = document.createElement('input');
      inp.type = 'file';
      inp.accept = 'image/*';
      inp.style.display = 'none';
      document.body.appendChild(inp);
      inp.onchange = function(){
        var f = inp.files && inp.files[0];
        document.body.removeChild(inp);
        if(!f) return;
        if(f.size > MAX_UNDERLAY){
          arToast('<b>' + esc(f.name) + '</b> is ' + (f.size / 1048576).toFixed(1)
                + ' MB — the underlay is saved inside the drawing, so 2 MB is the limit.', 'bad');
          return;
        }
        var wm = n(prompt('How wide is this image on the ground, in metres?', '20'), 20);
        var fr = new FileReader();
        fr.onload = function(){
          if(String(fr.result).length > MAX_UNDERLAY){
            arToast('That image encodes to more than 2 MB — the underlay is refused.', 'bad'); return;
          }
          SC.pending = setUnderlay({data_url: String(fr.result), width_m: wm, opacity: 0.85, rot: 0})
            .then(function(r){ arToast('Underlay <b>' + esc(f.name) + '</b> — ' + r.width_m.toFixed(2)
                                     + ' &times; ' + r.depth_m.toFixed(2) + ' m.'); underSheet(); return r; })
            .catch(function(e){ arToast(esc(e.message || String(e)), 'bad'); return null; });
        };
        fr.readAsDataURL(f);
      };
      inp.click();
    }
  };

  /* ── the family's public surface ───────────────────────────────────────── */
  window.site_context = {
    boundary: boundaryPoly,                 /* the world polygon, for other families */
    area: function(){ var p = boundaryPoly(); return p ? areaOf(p) : 0; },
    legs: function(){ var p = boundaryPoly(); return p ? legsOf(p) : []; },
    setback: doSetback,
    setbackPrompt: function(){ doSetback(n(prompt('Setback distance in metres:', '5'), NaN)); },
    satInfo: function(){ return SC.satInfo; },
    underlayMesh: function(){ return SC.under; },
    underlayRemove: function(){ underOff(); delete ext().underlay; SC.extSeen = AR.doc.ext;
                               arDirty(true); arSheetClose(); arToast('Underlay removed.'); },
    underlayApplySheet: function(){
      var w = document.getElementById('sc-u-w'), o = document.getElementById('sc-u-o'), r = document.getElementById('sc-u-r');
      var u = ext().underlay;
      if(!u){ arToast('There is no underlay to change.', 'warn'); return; }
      SC.pending = setUnderlay({data_url: u.data_url, width_m: w ? Number(w.value) : u.width_m,
                                opacity: o ? Number(o.value) / 100 : u.opacity,
                                rot: r ? Number(r.value) : u.rot})
        .then(function(res){ arToast('Underlay ' + res.width_m.toFixed(2) + ' &times; ' + res.depth_m.toFixed(2) + ' m.');
                             return res; })
        .catch(function(e){ arToast(esc(e.message || String(e)), 'bad'); return null; });
    },
    /* the tests (and anything that presses an icon and then wants the result)
       await the last asynchronous act */
    settled: function(){ return SC.pending || Promise.resolve(null); },
    inPoly: inPoly,
    _sc: SC
  };

  /* ── labels, and re-applying what the drawing carries ──────────────────── */
  AR_EXT.ready.push(function(){
    var baseRebuild = arRebuild;
    arRebuild = function(rec){
      if(rec && rec._scLabel){
        if(rec._scLabel.material){ if(rec._scLabel.material.map) rec._scLabel.material.map.dispose();
                                   rec._scLabel.material.dispose(); }
        rec._scLabel = null;
      }
      baseRebuild(rec);
      if(rec && rec.kind === 'site_boundary' && rec.node){
        var sp = labelFor(rec);
        if(sp){ rec.node.add(sp); rec._scLabel = sp; }
      }
    };
    /* A drawing that was opened, injected or undone brings its own ext: the
       underlay and the aerial come back with it. AR.doc.ext is REPLACED (never
       patched) by arOpen/arNew, so its identity is the cheapest honest signal
       that the document changed. */
    AR_EXT.ticks.push(function(){
      if(AR.doc.ext === SC.extSeen) return;
      SC.extSeen = AR.doc.ext;
      var e = (AR.doc.ext && AR.doc.ext.site_context) || {};
      if(e.underlay && e.underlay.data_url) underApply(e.underlay).catch(function(){});
      else underOff();
      if(e.sat && e.sat.on) satOn({source: e.sat.source, zoom: e.sat.zoom});
      else satOff();
    });
  });
})();
