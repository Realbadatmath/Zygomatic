// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* draw_guides — the three drafting POINTER MODES of the side bar's Draw group:
   Arc (arc), Polygon (poly) and Freehand (free). Each one produces a GUIDE
   record: line-only geometry, exactly like the studio's own guide_line and
   guide_circle, and void in Blender — a guide is something you draw TO, never
   something that is built.

     · guide_arc   p {x1, z1, x2, z2, x3, z3}   three points in the record's
       LOCAL frame (the record sits on the FIRST click, so x1 = z1 = 0). The
       circle through them is derived here, at 48 segments; three collinear
       points degrade to the chord instead of blowing up.
     · guide_poly  p {pts: [[x, z], ...]}       a closed ring, local to the
       first vertex. Clicked corner by corner, or a regular 3..12-gon typed as
       a digit then clicked as centre + rim point.
     · guide_path  p {pts: [[x, z], ...]}       an open freehand strip, local
       to the first point, decimated to ~0.1 m spacing.

   Parameters only: every record stores numbers the geometry is rebuilt from,
   so a guide survives save/load, undo, the assistant and the Properties panel.
   Plan convention: 0 deg = +X, 90 deg = -Z (north is up in the top view), so a
   point at angle t is (r cos t, -r sin t). */
(function(){
  var SEG = 48;                  /* segments in a rebuilt arc */
  var MAXP = 400;                /* corners / path points a guide may hold */
  var STEP = 0.1;                /* freehand decimation, metres */
  var SNAPD = 0.25;              /* click-the-first-corner-to-close tolerance */

  function r4(v){ return Math.round(v * 10000) / 10000; }
  function num(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }

  /* ── the arithmetic: the circle through three points ───────────────────
     Returns an array of [x, z] along the arc from p1 to p2 the way round that
     passes through p3, or the plain chord when the three points are collinear
     (or two of them coincide) — a straight line is the honest limit of an arc
     of infinite radius, and it keeps a degenerate record drawable. */
  function arcPoints(x1, z1, x2, z2, x3, z3, seg){
    var d = 2 * (x1 * (z2 - z3) + x2 * (z3 - z1) + x3 * (z1 - z2));
    var s1 = x1 * x1 + z1 * z1, s2 = x2 * x2 + z2 * z2, s3 = x3 * x3 + z3 * z3;
    if(Math.abs(d) < 1e-9) return [[x1, z1], [x3, z3], [x2, z2]];
    var cx = (s1 * (z2 - z3) + s2 * (z3 - z1) + s3 * (z1 - z2)) / d;
    var cz = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d;
    var r = Math.hypot(x1 - cx, z1 - cz);
    if(!isFinite(r) || r < 1e-6 || r > 1e6) return [[x1, z1], [x3, z3], [x2, z2]];
    var TAU = Math.PI * 2;
    var a1 = Math.atan2(z1 - cz, x1 - cx);
    var wrap = function(a){ a = (a - a1) % TAU; return a < 0 ? a + TAU : a; };
    var da = wrap(Math.atan2(z2 - cz, x2 - cx));
    var d3 = wrap(Math.atan2(z3 - cz, x3 - cx));
    var sweep = (d3 <= da) ? da : da - TAU;      /* go the way that passes p3 */
    if(Math.abs(sweep) < 1e-9) sweep = TAU;      /* start = end: a whole circle */
    var out = [], n = Math.max(4, seg | 0);
    for(var i = 0; i <= n; i++){
      var a = a1 + sweep * i / n;
      out.push([cx + r * Math.cos(a), cz + r * Math.sin(a)]);
    }
    return out;
  }
  function ptList(v, fb){
    if(!Array.isArray(v) || v.length < 2) return fb;
    var out = [];
    for(var i = 0; i < v.length && i < MAXP; i++){
      var q = v[i];
      if(!q || q.length < 2) continue;
      var x = num(q[0], NaN), z = num(q[1], NaN);
      if(isFinite(x) && isFinite(z)) out.push([x, z]);
    }
    return out.length >= 2 ? out : fb;
  }

  /* ── geometry: three line-only kinds ───────────────────────────────────── */
  AR_EXT.geom.guide_arc = function(p, k){
    var T = k.THREE, N = function(key, d){ return k.num(p[key], d); };
    var pts = arcPoints(N('x1', 0), N('z1', 0), N('x2', 3), N('z2', 0), N('x3', 1.5), N('z3', -1.5), SEG);
    var v = pts.map(function(q){ return new T.Vector3(q[0], 0, q[1]); });
    return [{g: new T.BufferGeometry().setFromPoints(v), line: 1, strip: 1}];
  };
  AR_EXT.geom.guide_poly = function(p, k){
    var T = k.THREE;
    var pts = ptList(p && p.pts, [[0, 0], [4, 0], [4, 4], [0, 4]]);
    var v = [];                                   /* a closed ring of segments */
    for(var i = 0; i < pts.length; i++){
      var a = pts[i], b = pts[(i + 1) % pts.length];
      v.push(new T.Vector3(a[0], 0, a[1]), new T.Vector3(b[0], 0, b[1]));
    }
    return [{g: new T.BufferGeometry().setFromPoints(v), line: 1}];
  };
  AR_EXT.geom.guide_path = function(p, k){
    var T = k.THREE;
    var pts = ptList(p && p.pts, [[0, 0], [2, 1], [4, 0]]);
    var v = [];                                   /* an open strip of segments */
    for(var i = 0; i + 1 < pts.length; i++){
      v.push(new T.Vector3(pts[i][0], 0, pts[i][1]), new T.Vector3(pts[i + 1][0], 0, pts[i + 1][1]));
    }
    return [{g: new T.BufferGeometry().setFromPoints(v), line: 1}];
  };
  AR_EXT.label.guide_arc = 'Guide arc';
  AR_EXT.label.guide_poly = 'Guide polygon';
  AR_EXT.label.guide_path = 'Guide path';

  /* ── drafting state ────────────────────────────────────────────────────── */
  var ST = {arc: [], poly: [], free: [], prev: null, digits: ''};

  function setPreview(vs){
    if(!window.AR || !AR.scene || !window.THREE) return;
    if(!ST.prev){
      ST.prev = new THREE.Line(new THREE.BufferGeometry(),
                               new THREE.LineBasicMaterial({color: 0xffc400, transparent: true, opacity: 0.9}));
      ST.prev.renderOrder = 4;
      AR.scene.add(ST.prev);
    }
    ST.prev.geometry.setFromPoints(vs);
    ST.prev.visible = vs.length > 1;
  }
  function clearPreview(){                        /* removed on cancel, as promised */
    if(!ST.prev) return;
    if(AR.scene) AR.scene.remove(ST.prev);
    if(ST.prev.geometry) ST.prev.geometry.dispose();
    if(ST.prev.material) ST.prev.material.dispose();
    ST.prev = null;
  }
  function V(x, y, z){ return new THREE.Vector3(x, y, z); }
  function rubber(a, b){
    if(!AR.rubber) return;
    AR.rubber.geometry.setFromPoints([V(a.x, a.y + 0.01, a.z), V(b.x, a.y + 0.01, b.z)]);
    AR.rubber.visible = true;
  }
  function local(pts){
    var a = pts[0];
    return pts.map(function(q){ return [r4(q.x - a.x), r4(q.z - a.z)]; });
  }
  function place(kind, p, a, what){
    arPush();                                     /* ONE undo step, before the change */
    var rec = arNewObj(kind, p, a.x, a.z, a.y);
    arSelect([rec.id]);
    arPanel();
    arToast('<b>' + esc(arKindLabel(kind)) + '</b> ' + what + '.');
    return rec;
  }
  function reset(){
    ST.arc = []; ST.poly = []; ST.free = [];
    clearPreview();
    if(AR.rubber) AR.rubber.visible = false;
  }

  /* ── Arc: three-point arc ──────────────────────────────────────────────── */
  function arcHint(){
    var n = ST.arc.length;
    return n === 0 ? 'Arc — click where the arc <b>starts</b>.'
         : n === 1 ? 'Click where the arc <b>ends</b> &middot; <b>Esc</b> cancels.'
         : 'Click a point <b>on</b> the arc &middot; <b>Esc</b> cancels.';
  }
  AR_EXT.modes.arc = {
    hint: function(){ return arcHint(); },
    cancel: function(){ ST.arc = []; clearPreview(); },
    key: function(e){
      if(e.key === 'Escape' || e.key === 'Enter'){ arCancelDraft(); return true; }
      return false;
    },
    move: function(P, e){
      if(!P || !ST.arc.length){ if(AR.rubber) AR.rubber.visible = false; return; }
      var a = ST.arc[0];
      rubber(a, ST.arc.length === 1 ? P : ST.arc[1]);
      if(ST.arc.length === 2){
        var b = ST.arc[1];
        var q = arcPoints(0, 0, b.x - a.x, b.z - a.z, P.x - a.x, P.z - a.z, SEG);
        setPreview(q.map(function(w){ return V(a.x + w[0], a.y + 0.012, a.z + w[1]); }));
      }
    },
    click: function(P){
      if(!P) return;
      ST.arc.push({x: P.x, z: P.z, y: P.y});
      if(ST.arc.length < 3){ arHint(arcHint()); return; }
      var a = ST.arc[0], b = ST.arc[1], c = ST.arc[2];
      ST.arc = [];
      clearPreview();
      if(AR.rubber) AR.rubber.visible = false;
      if(Math.hypot(b.x - a.x, b.z - a.z) < 1e-3){
        arToast('The arc&rsquo;s start and end are in the same place — click three different points.', 'warn');
        arHint(arcHint()); return;
      }
      var p = {x1: 0, z1: 0, x2: r4(b.x - a.x), z2: r4(b.z - a.z), x3: r4(c.x - a.x), z3: r4(c.z - a.z)};
      var pts = arcPoints(p.x1, p.z1, p.x2, p.z2, p.x3, p.z3, SEG);
      var L = 0;
      for(var i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      place('guide_arc', p, a, 'through 3 points, ' + L.toFixed(2) + ' m long');
      arHint(arcHint());
    }
  };

  /* ── Polygon: clicked corners, or a typed regular n-gon ────────────────── */
  function polyN(){ var n = AR._drawGuidesN | 0; return (n >= 3 && n <= 12) ? n : 0; }
  function polyHint(){
    var n = polyN(), k = ST.poly.length;
    if(n) return k === 0 ? 'Regular <b>' + n + '</b>-gon — click the <b>centre</b> &middot; <b>Esc</b> cancels.'
                         : 'Click a point on the <b>rim</b> &middot; <b>Esc</b> cancels.';
    if(k === 0) return 'Polygon — click each corner; <b>Enter</b> or the first corner closes it. '
                     + 'Or type a number <b>3&ndash;12</b> then click centre and a rim point for a regular polygon.';
    return k + ' corner' + (k === 1 ? '' : 's') + ' — click the next; <b>Enter</b> or the first corner closes '
         + '&middot; <b>Esc</b> cancels.';
  }
  function polyClose(){
    if(ST.poly.length < 3){
      if(ST.poly.length) arToast('A polygon needs at least 3 corners.', 'warn');
      ST.poly = []; clearPreview();
      if(AR.rubber) AR.rubber.visible = false;
      arHint(polyHint());
      return;
    }
    var pts = local(ST.poly), a = ST.poly[0], n = pts.length;
    ST.poly = []; clearPreview();
    if(AR.rubber) AR.rubber.visible = false;
    place('guide_poly', {pts: pts}, a, n + ' corners');
    arHint(polyHint());
  }
  function polyRegular(c, rim){
    var r = Math.hypot(rim.x - c.x, rim.z - c.z), n = polyN();
    if(r < 0.02){ arToast('The rim point is on the centre — click further out.', 'warn'); return false; }
    var t0 = Math.atan2(-(rim.z - c.z), rim.x - c.x), pts = [];
    for(var i = 0; i < n; i++){
      var t = t0 + 2 * Math.PI * i / n;
      pts.push({x: c.x + r * Math.cos(t), z: c.z - r * Math.sin(t), y: c.y});
    }
    place('guide_poly', {pts: local(pts)}, pts[0], 'regular ' + n + '-gon, radius ' + r.toFixed(2) + ' m');
    return true;
  }
  AR_EXT.modes.poly = {
    hint: function(){ return polyHint(); },
    cancel: function(){ ST.poly = []; ST.digits = ''; AR._drawGuidesN = 0; clearPreview(); },
    key: function(e){
      if(e.ctrlKey || e.metaKey || e.altKey) return false;
      if(e.key === 'Escape'){ arCancelDraft(); return true; }
      if(e.key === 'Enter'){ polyClose(); return true; }
      if(/^[0-9]$/.test(e.key)){
        if(ST.poly.length) return true;           /* the side count is chosen before the first click */
        ST.digits += e.key;
        if(parseInt(ST.digits, 10) > 12) ST.digits = e.key;
        var n = parseInt(ST.digits, 10);
        AR._drawGuidesN = (n >= 3 && n <= 12) ? n : 0;
        arHint(polyN() ? polyHint()
                       : 'Typed <b>' + ST.digits + '</b> — a regular polygon has 3 to 12 sides; type another digit.');
        return true;
      }
      return false;
    },
    move: function(P, e){
      if(!P || !ST.poly.length){ if(AR.rubber) AR.rubber.visible = false; return; }
      rubber(ST.poly[ST.poly.length - 1], P);
      if(!polyN() && ST.poly.length > 1){
        setPreview(ST.poly.map(function(q){ return V(q.x, q.y + 0.012, q.z); }));
      }
    },
    click: function(P){
      if(!P) return;
      if(polyN()){
        ST.poly.push({x: P.x, z: P.z, y: P.y});
        if(ST.poly.length < 2){ arHint(polyHint()); return; }
        var c = ST.poly[0], rim = ST.poly[1];
        ST.poly = []; clearPreview();
        if(AR.rubber) AR.rubber.visible = false;
        polyRegular(c, rim);
        AR._drawGuidesN = 0; ST.digits = '';
        arHint(polyHint());
        return;
      }
      var f = ST.poly[0];
      if(ST.poly.length >= 3 && f && Math.hypot(P.x - f.x, P.z - f.z) <= SNAPD){ polyClose(); return; }
      if(ST.poly.length >= MAXP){ arToast('A guide polygon holds at most ' + MAXP + ' corners.', 'warn'); polyClose(); return; }
      ST.poly.push({x: P.x, z: P.z, y: P.y});
      setPreview(ST.poly.map(function(q){ return V(q.x, q.y + 0.012, q.z); }));
      arHint(polyHint());
    }
  };

  /* ── Freehand: a stroke drawn with the pointer down ────────────────────── */
  function freeHint(){
    var k = ST.free.length;
    return k ? k + ' points — release to keep the path &middot; <b>Esc</b> cancels.'
             : 'Freehand — hold the pointer <b>down</b> and draw; release to keep the path.';
  }
  function freeFinish(){
    if(ST.free.length < 2){ ST.free = []; clearPreview(); return null; }
    var pts = local(ST.free), a = ST.free[0], n = pts.length, L = 0;
    for(var i = 1; i < n; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    ST.free = []; clearPreview();
    if(AR.rubber) AR.rubber.visible = false;
    var rec = place('guide_path', {pts: pts}, a, n + ' points, ' + L.toFixed(2) + ' m long');
    arHint(freeHint());
    return rec;
  }
  AR_EXT.modes.free = {
    hint: function(){ return freeHint(); },
    cancel: function(){ ST.free = []; clearPreview(); },
    key: function(e){
      if(e.key === 'Escape'){ arCancelDraft(); return true; }
      if(e.key === 'Enter'){ freeFinish(); return true; }
      return false;
    },
    move: function(P, e){
      if(e && (e.buttons & 1)){
        if(!P) return;
        var last = ST.free[ST.free.length - 1];
        if(last && Math.hypot(P.x - last.x, P.z - last.z) < STEP) return;   /* decimate to ~0.1 m */
        if(ST.free.length >= MAXP){ freeFinish(); return; }
        ST.free.push({x: P.x, z: P.z, y: P.y});
        setPreview(ST.free.map(function(q){ return V(q.x, q.y + 0.012, q.z); }));
        arHint(freeHint());
        return;
      }
      if(ST.free.length >= 2) freeFinish();       /* the pointer came up somewhere */
    },
    click: function(P){
      if(ST.free.length >= 2){ freeFinish(); return; }
      if(!P) return;
      ST.free.push({x: P.x, z: P.z, y: P.y});
      setPreview(ST.free.map(function(q){ return V(q.x, q.y + 0.012, q.z); }));
      arHint(freeHint());
    }
  };

  /* A freehand DRAG never reaches arClick — the studio reads a moved pointer as
     a camera gesture — so the stroke is closed on the canvas's own pointerup. */
  AR_EXT.ready.push(function(){
    var c = AR.renderer && AR.renderer.domElement;
    if(!c) return;
    c.addEventListener('pointerup', function(){ if(AR.tool === 'free') freeFinish(); });
    c.addEventListener('pointercancel', function(){ if(AR.tool === 'free'){ ST.free = []; clearPreview(); } });
  });
  window.arDrawGuidesReset = reset;               /* family-prefixed, for tests and tool changes */
})();
