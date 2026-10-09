// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* precision_snaps — object snapping for Architecture Studio (2026-09-07).

   Wires the seven Precision placeholders through the AR_EXT.snaps seam:
     pr_end  Endpoint       the corner of a wall, the end of a beam
     pr_mid  Midpoint       the centre of an edge
     pr_cen  Centre         of a circle, a column, a room
     pr_int  Intersection   where two wall lines or two guides cross
     pr_perp Perpendicular  the foot of the perpendicular from the draft's first point
     pr_tan  Tangent        the tangent points from the draft's first point to a circle
     pr_near Nearest        the closest point on the nearest edge

   Each icon is an independent SWITCH; any combination may be on. The hook runs
   AFTER grid snap on every draft click and every rubber-band move, and the first
   non-null answer wins, so one hook serves all seven and resolves the priority
   itself: endpoint > intersection > midpoint > centre > perpendicular > tangent
   > nearest, nearest-first inside a class.

   Candidates come from ONE index over the records on the current drawing plane
   band (|rec.y - AR.level| < 2.7), rebuilt lazily whenever a cheap signature of
   AR.objs changes. Settings persist in localStorage 'ar.precision_snaps' and are
   mirrored in AR.doc.ext.precision_snaps so they travel with the drawing.

   Nothing in inspection.html was edited to make these icons real. */
(function(){
  'use strict';

  var IDS = ['pr_end', 'pr_mid', 'pr_cen', 'pr_int', 'pr_perp', 'pr_tan', 'pr_near'];
  var LB = {pr_end: 'Endpoint', pr_mid: 'Midpoint', pr_cen: 'Centre', pr_int: 'Intersection',
            pr_perp: 'Perpendicular', pr_tan: 'Tangent', pr_near: 'Nearest'};
  /* snap type -> the icon that switches it on */
  var TYPE_ID = {endpoint: 'pr_end', midpoint: 'pr_mid', centre: 'pr_cen', intersection: 'pr_int',
                 perpendicular: 'pr_perp', tangent: 'pr_tan', nearest: 'pr_near'};
  /* the order a tie is settled in — first wins */
  var PRIO = ['endpoint', 'intersection', 'midpoint', 'centre', 'perpendicular', 'tangent', 'nearest'];
  var COL = {endpoint: 0x00e5ff, intersection: 0xff5c8a, midpoint: 0x7cffb2, centre: 0xffd166,
             perpendicular: 0xb388ff, tangent: 0xff9f43, nearest: 0x9aa7b4};
  var TIP = {
    pr_end: 'Snap to endpoints — the corner of a wall, the end of a beam',
    pr_mid: 'Snap to midpoints — the centre of an edge, which is where a door usually wants to be',
    pr_cen: 'Snap to centres — of a circle, a column, a room',
    pr_int: 'Snap to intersections — where two guides or two wall lines cross',
    pr_perp: 'Snap perpendicular to an edge — the right angle you cannot eyeball at 30&deg;',
    pr_tan: 'Snap tangent to an arc or a circle',
    pr_near: 'Snap to the nearest point on an edge, wherever along it you happen to be'};

  /* kinds whose plan geometry is a centre LINE of length p.len along local +X */
  var LINEAR = {wall: 1, partition: 1, beam: 1, guide_line: 1, road: 1, path: 1, railing: 1};
  /* kinds whose plan silhouette is a CIRCLE of radius p.r — tangents come from these */
  var ROUND = {guide_circle: 1, column_round: 1, cylinder: 1, disc: 1, bollard: 1};
  /* only these centre lines are crossed pairwise for intersections */
  var CROSSABLE = {wall: 1, partition: 1, guide_line: 1};

  var MAX_SEGS = 400;          /* cap on the segments fed to the pairwise cross */
  var MAX_INTS = 4000;         /* and on the crossings kept */
  var BAND = 2.7;              /* one storey: the drawing plane's band */
  var PIXELS = 12;             /* the snap radius, in screen pixels */

  var IDX = null, SIG = '';

  function num(v, d){ var n = parseFloat(v); return isFinite(n) ? n : d; }
  function r6(v){ return Math.round(v * 1e6) / 1e6; }

  function state(){
    if(!AR.precision_snaps){
      var on = {};
      IDS.forEach(function(id){ on[id] = false; });
      AR.precision_snaps = {on: on, radius: 0};
    }
    return AR.precision_snaps;
  }
  function anyOn(){
    var on = state().on;
    for(var i = 0; i < IDS.length; i++) if(on[IDS[i]]) return true;
    return false;
  }

  /* ── persistence ───────────────────────────────────────────────────────── */
  function save(quiet){
    var on = state().on, plain = {};
    IDS.forEach(function(id){ plain[id] = !!on[id]; });
    try{ localStorage.setItem('ar.precision_snaps', JSON.stringify(plain)); }catch(e){}
    try{
      if(AR.doc){ AR.doc.ext = AR.doc.ext || {}; AR.doc.ext.precision_snaps = plain; }
      /* restoring the saved preferences is not an edit — only a press is */
      if(!quiet && typeof arDirty === 'function') arDirty(true);
    }catch(e2){}
  }
  function load(){
    var on = state().on, src = null;
    try{ src = JSON.parse(localStorage.getItem('ar.precision_snaps') || 'null'); }catch(e){}
    try{ if(AR.doc && AR.doc.ext && AR.doc.ext.precision_snaps) src = AR.doc.ext.precision_snaps; }catch(e2){}
    if(src && typeof src === 'object') IDS.forEach(function(id){ on[id] = !!src[id]; });
    save(true);
  }

  /* ── the snap radius: 12 screen pixels, in metres, at the pointer's depth ── */
  function radius(){
    var st = state();
    if(st.radius > 0) return st.radius;                 /* an explicit override (tests, presets) */
    var r = 0.3;
    try{
      var el = AR.renderer && AR.renderer.domElement;
      var h = (el && (el.clientHeight || el.height)) || 900;
      if(AR.ortho && AR.camO){
        var wh = Math.abs(AR.camO.top - AR.camO.bottom) / (AR.camO.zoom || 1);
        r = wh * PIXELS / h;
      } else if(AR.camP){
        var t = (AR.controls && AR.controls.target) || new THREE.Vector3();
        var dist = AR.camP.position.distanceTo(t);
        r = 2 * dist * Math.tan(AR.camP.fov * Math.PI / 360) * PIXELS / h;
      }
    }catch(e){}
    return Math.max(0.01, Math.min(5, r));
  }

  /* ── the candidate index ───────────────────────────────────────────────── */
  function signature(){
    var n = AR.objs.length, s = 0, pos = 0;
    for(var i = 0; i < n; i++){
      var r = AR.objs[i];
      s += (parseInt(String(r.id).replace(/\D/g, ''), 10) || 0) + (r.hidden ? 0.5 : 0);
      pos += (r.x || 0) + (r.z || 0) + (r.y || 0) + (r.ry || 0);
    }
    return n + '|' + s + '|' + Math.round(pos * 1e4) + '|' + (AR._prEdit || 0) + '|' + (AR.level || 0);
  }

  function segInt(p, q){
    var r1 = p.bx - p.ax, r2 = p.bz - p.az, s1 = q.bx - q.ax, s2 = q.bz - q.az;
    var den = r1 * s2 - r2 * s1;
    if(Math.abs(den) < 1e-12) return null;                       /* parallel */
    var ox = q.ax - p.ax, oz = q.az - p.az;
    var t = (ox * s2 - oz * s1) / den, u = (ox * r2 - oz * r1) / den;
    if(t < -1e-9 || t > 1 + 1e-9 || u < -1e-9 || u > 1 + 1e-9) return null;
    return {x: p.ax + t * r1, z: p.az + t * r2};
  }

  function build(){
    var pts = [], segs = [], circles = [], lvl = AR.level || 0;
    (AR.objs || []).forEach(function(rec){
      if(!rec || rec.hidden) return;
      if(Math.abs((rec.y || 0) - lvl) >= BAND) return;
      var k = rec.kind || '', p = rec.p || {}, ry = rec.ry || 0;
      var cs = Math.cos(ry), sn = Math.sin(ry), x = rec.x || 0, z = rec.z || 0;
      /* a local plan point (lx, lz) under a rotation of ry about the vertical */
      var loc = function(lx, lz){ return {x: x + lx * cs + lz * sn, z: z - lx * sn + lz * cs}; };

      pts.push({x: x, z: z, t: 'centre', id: rec.id});           /* every record's bbox centre */

      var L = num(p.len, 0), W = num(p.w, 0), D = num(p.d, 0), R = num(p.r, 0);
      if(LINEAR[k] && L > 1e-6){
        var a = loc(-L / 2, 0), b = loc(L / 2, 0);
        pts.push({x: a.x, z: a.z, t: 'endpoint', id: rec.id});
        pts.push({x: b.x, z: b.z, t: 'endpoint', id: rec.id});
        pts.push({x: (a.x + b.x) / 2, z: (a.z + b.z) / 2, t: 'midpoint', id: rec.id});
        segs.push({ax: a.x, az: a.z, bx: b.x, bz: b.z, cross: !!CROSSABLE[k]});
      } else if(W > 1e-6 && D > 1e-6){
        var c = [loc(-W / 2, -D / 2), loc(W / 2, -D / 2), loc(W / 2, D / 2), loc(-W / 2, D / 2)];
        for(var i = 0; i < 4; i++){
          var j = (i + 1) % 4;
          pts.push({x: c[i].x, z: c[i].z, t: 'endpoint', id: rec.id});
          pts.push({x: (c[i].x + c[j].x) / 2, z: (c[i].z + c[j].z) / 2, t: 'midpoint', id: rec.id});
          segs.push({ax: c[i].x, az: c[i].z, bx: c[j].x, bz: c[j].z, cross: false});
        }
      }
      if(ROUND[k] && R > 1e-6) circles.push({x: x, z: z, r: R, id: rec.id});
    });

    /* intersections: the wall/guide centre lines against each other */
    var ls = [];
    for(var s = 0; s < segs.length && ls.length < MAX_SEGS; s++) if(segs[s].cross) ls.push(segs[s]);
    var made = 0;
    for(var m = 0; m < ls.length && made < MAX_INTS; m++)
      for(var n = m + 1; n < ls.length && made < MAX_INTS; n++){
        var q = segInt(ls[m], ls[n]);
        if(q){ pts.push({x: q.x, z: q.z, t: 'intersection'}); made++; }
      }
    return {pts: pts, segs: segs, circles: circles};
  }

  function index(){
    var sg = signature();
    if(!IDX || sg !== SIG){ IDX = build(); SIG = sg; }
    return IDX;
  }

  /* ── the four draft-relative constructions ─────────────────────────────── */
  function foot(a, s){                                    /* perpendicular from a onto s */
    var dx = s.bx - s.ax, dz = s.bz - s.az, L2 = dx * dx + dz * dz;
    if(L2 < 1e-12) return null;
    var t = ((a.x - s.ax) * dx + (a.z - s.az) * dz) / L2;
    if(t < -1e-3 || t > 1 + 1e-3) return null;            /* the foot must land ON the edge */
    return {x: s.ax + t * dx, z: s.az + t * dz};
  }
  function closest(P, s){                                 /* nearest point on s */
    var dx = s.bx - s.ax, dz = s.bz - s.az, L2 = dx * dx + dz * dz;
    if(L2 < 1e-12) return {x: s.ax, z: s.az};
    var t = Math.max(0, Math.min(1, ((P.x - s.ax) * dx + (P.z - s.az) * dz) / L2));
    return {x: s.ax + t * dx, z: s.az + t * dz};
  }
  function tangents(a, c){                                /* the two tangent points from a to c */
    var ax = a.x - c.x, az = a.z - c.z, d2 = ax * ax + az * az, r = c.r;
    if(!(r > 1e-6) || d2 <= r * r + 1e-9) return [];      /* a is inside or on the circle */
    var k = r * r / d2, h = r * Math.sqrt(d2 - r * r) / d2;
    var bx = c.x + k * ax, bz = c.z + k * az, px = -az, pz = ax;
    return [{x: bx + h * px, z: bz + h * pz}, {x: bx - h * px, z: bz - h * pz}];
  }

  /* ── the hook itself ───────────────────────────────────────────────────── */
  function query(P, g, e){
    if(!P || !anyOn()) return null;
    var on = state().on, R = radius(), ix = index(), best = null;
    var take = function(t, x, z){
      if(!on[TYPE_ID[t]]) return;
      var dx = x - P.x, dz = z - P.z, d = Math.sqrt(dx * dx + dz * dz);
      if(d > R) return;
      var pr = PRIO.indexOf(t);
      if(!best || pr < best.pr || (pr === best.pr && d < best.d)) best = {pr: pr, d: d, x: x, z: z, t: t};
    };
    for(var i = 0; i < ix.pts.length; i++) take(ix.pts[i].t, ix.pts[i].x, ix.pts[i].z);

    var a = AR.draft && AR.draft.a;
    if(a && on.pr_perp)
      for(var s = 0; s < ix.segs.length; s++){ var f = foot(a, ix.segs[s]); if(f) take('perpendicular', f.x, f.z); }
    if(a && on.pr_tan)
      for(var c = 0; c < ix.circles.length; c++){
        var tp = tangents(a, ix.circles[c]);
        for(var t2 = 0; t2 < tp.length; t2++) take('tangent', tp[t2].x, tp[t2].z);
      }
    if(on.pr_near)
      for(var n = 0; n < ix.segs.length; n++){ var q = closest(P, ix.segs[n]); take('nearest', q.x, q.z); }

    if(!best) return null;
    return {x: r6(best.x), z: r6(best.z), y: (AR.level || 0), snap: best.t};
  }

  AR_EXT.snaps.push(function(P, g, e){
    try{ return query(P, g, e); }catch(err){ return null; }
  });

  /* ── the seven switches ────────────────────────────────────────────────── */
  IDS.forEach(function(id){
    AR_EXT.tools[id] = {
      tog: 1, assist: 1, tip: TIP[id],
      on: function(){ return !!state().on[id]; },
      act: function(opt){
        var on = state().on, v;
        if(opt && typeof opt === 'object' && opt.on !== undefined)
          v = !(opt.on === false || opt.on === 0 || opt.on === '0' || opt.on === 'false' || opt.on === 'off');
        else v = !on[id];
        on[id] = v;
        save();
        if(!v && AR._prMark) AR._prMark.visible = false;
        arToast('<b>' + LB[id] + '</b> snap ' + (v ? 'on' : 'off') + '.');
      }
    };
  });

  /* the setter the tests (and a preset) use instead of driving the camera */
  window.arPrecisionSnapsRadius = function(m){
    var v = num(m, 0);
    state().radius = v > 0 ? v : 0;
    return state().radius;
  };
  /* the snap the hook would give for a plan point — the assistant/test read-only view */
  window.arPrecisionSnapAt = function(P){ return query(P, null, null); };

  /* ── the marker + the hint suffix ──────────────────────────────────────── */
  function afterMove(g, e){
    var res = null;
    try{
      if(g && anyOn()) res = query({x: arSnapV(g.x), z: arSnapV(g.z), y: AR.level}, g, e);
    }catch(err){}
    var mk = AR._prMark;
    if(mk){
      if(res){
        mk.position.set(res.x, (res.y || 0) + 0.02, res.z);
        mk.material.color.setHex(COL[res.snap] || 0x00e5ff);
        mk.visible = true;
      } else mk.visible = false;
    }
    var el = document.getElementById('ar-hint');
    if(el){
      /* strip our own suffix first, so a hundred moves never stack a hundred names */
      var h = el.innerHTML.replace(/<span class="pr-snap">[\s\S]*?<\/span>/g, '');
      if(res) h += '<span class="pr-snap"> &middot; ' + res.snap + '</span>';
      el.innerHTML = h;
      el.style.display = h ? 'block' : 'none';
    }
    return res;
  }
  window.arPrecisionSnapMove = afterMove;

  AR_EXT.ready.push(function(){
    state();
    load();

    /* the feedback ring: 0.15 m, coloured per snap type, drawn over everything */
    var pts = [];
    for(var i = 0; i <= 32; i++){
      var a = i / 32 * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * 0.15, 0, Math.sin(a) * 0.15));
    }
    var geo = new THREE.BufferGeometry().setFromPoints(pts);
    var mk = new THREE.Line(geo, new THREE.LineBasicMaterial({color: 0x00e5ff, transparent: true,
                                                              opacity: 0.95, depthTest: false}));
    mk.renderOrder = 999; mk.frustumCulled = false; mk.visible = false;
    AR.scene.add(mk);
    AR._prMark = mk;

    /* every pointer move while a tool is armed: the studio draws its rubber band
       and writes the hint, then we mark the snap and name it. */
    var baseMove = arDraftMove;
    arDraftMove = function(g, e){
      baseMove(g, e);
      try{ afterMove(g, e); }catch(err){}
    };
    /* the index's edit counter: every document change is pushed before it happens */
    var basePush = arPush;
    AR._prEdit = AR._prEdit || 0;
    arPush = function(){ AR._prEdit++; return basePush(); };
  });
})();
