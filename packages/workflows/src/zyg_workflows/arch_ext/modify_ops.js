// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* modify_ops — the Modify section's three unwired icons, as real POINTER MODES:

     offset  (AR_EXT.modes.offset)  a parallel copy of a wall / partition /
                                    guide line / guide circle / guide polygon
                                    at a distance you give.
     fillet  (AR_EXT.modes.fillet)  two walls trimmed or extended until their
                                    centre lines meet, then optionally rounded
                                    with a wall_arc of the radius you give.
     follow  (AR_EXT.modes.follow)  "Follow me": sweep a w x h profile along a
                                    path (a guide-line chain, a point list or a
                                    wall) -> ONE record of the new kind `sweep`.

   THE FRAME (verified against inspection.html: arClick sets
   `w.ry = Math.atan2(-(b.z-a.z), (b.x-a.x))`, and arch_assistant._wall_world
   reads a point back as `x + lx*cos(ry), z - lx*sin(ry)`):

       along the wall   dir = ( cos(ry), -sin(ry) )     in x/z
       across the wall  nrm = ( sin(ry),  cos(ry) )     in x/z   (dir . nrm = 0)

   The brief's "(-sin(ry), cos(ry))" is NOT perpendicular to that direction
   (their dot product is -sin(2·ry)); THREE's makeRotationY sends local +Z to
   world (sin, 0, cos), which is the vector used here.

   CLICKING WITHOUT A POINTER. Each mode's `click(P, e, g)` picks the record
   under `e` with arPick(e) when `e` is a real pointer event. When `e` is a
   plain object it is read as the click itself, so a test (or the console) can
   drive the modes with no pointer at all:

       AR_EXT.modes.offset.click(null, {rec: wall, distance: 1.5});
       AR_EXT.modes.fillet.click(null, {rec: wallA});
       AR_EXT.modes.fillet.click(null, {rec: wallB, radius: 1});
       AR_EXT.modes.follow.click(null, {rec: line, w: 0.3, h: 0.3});

   The same fields are what a person is prompt()ed for, so both paths run one
   arithmetic. Every edit goes behind ONE arPush() called BEFORE it. */
(function(){
  var EPS = 1e-9, TOL = 0.01;                 /* 1 cm: "the same point" */

  function isArr(v){ return Object.prototype.toString.call(v)==='[object Array]'; }
  function num(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }

  /* the record this click is on: a real event goes through arPick, a plain
     object carries `rec` (the harness has no pointer) */
  function pick(e){
    if(e && typeof e==='object' && e.rec) return e.rec;
    if(!e || typeof e.clientX!=='number') return null;
    var h = arPick(e);
    return h ? h.rec : null;
  }
  /* a field of the click object, else a prompt with that default */
  function ask(e, key, question, dflt){
    if(e && typeof e==='object' && e[key]!==undefined && e[key]!==null) return num(e[key], dflt);
    var a = prompt(question, String(dflt));
    if(a===null) return null;                 /* cancelled */
    return num(a, dflt);
  }
  function isWall(r){ return !!r && (r.kind==='wall' || r.kind==='partition'); }
  function dirOf(r){ return {x: Math.cos(r.ry||0), z: -Math.sin(r.ry||0)}; }
  function nrmOf(r){ return {x: Math.sin(r.ry||0), z:  Math.cos(r.ry||0)}; }
  function ends(r){
    var L = num(r.p && r.p.len, 4)/2, d = dirOf(r);
    return [{x: r.x - d.x*L, z: r.z - d.z*L}, {x: r.x + d.x*L, z: r.z + d.z*L}];
  }
  function dist(a, b){ return Math.hypot(a.x-b.x, a.z-b.z); }
  function cross(u, v){ return u.x*v.z - u.z*v.x; }
  /* the ry that puts a wall's local +X along a -> b */
  function ryOf(a, b){ return Math.atan2(-(b.z-a.z), (b.x-a.x)); }
  /* a clean [[x,z],...] ring, or null */
  function ptsOf(v){
    var out = [], i, a, x, z;
    if(!isArr(v)) return null;
    for(i=0;i<v.length;i++){
      a = v[i];
      if(!isArr(a) || a.length<2) continue;
      x = Number(a[0]); z = Number(a[1]);
      if(isFinite(x) && isFinite(z)) out.push([x, z]);
    }
    return out.length>=2 ? out : null;
  }
  /* a record's local [x,z] point in world coordinates */
  function toWorld(r, p){
    var c = Math.cos(r.ry||0), s = Math.sin(r.ry||0);
    return {x: r.x + p[0]*c + p[1]*s, z: r.z - p[0]*s + p[1]*c};
  }
  function copyP(p){ return JSON.parse(JSON.stringify(p||{})); }
  function clone(r, x, z){
    var o = arNewObj(r.kind, copyP(r.p), x, z, r.y||0);
    o.ry = r.ry||0; o.rx = r.rx||0; o.rz = r.rz||0; o.s = r.s||1;
    o.mat = r.mat; o.grp = r.grp||''; o.name = r.name;
    /* rec.meta is the per-record user data (layer, tag, zone…): a parallel copy
       that dropped it would silently fall off its layer */
    o.meta = copyP(r.meta);
    arApplyTransform(o); arApplyMat(o);
    return o;
  }

  /* ── offset ─────────────────────────────────────────────────────────────
     ONE parallel copy of the clicked record at distance d (the sign picks the
     side). A wall/partition/guide_line slides along its own normal; a
     guide_circle grows or shrinks its radius; a point list is inset/outset. */
  function offsetPts(pts, d, closed){
    /* every edge is moved d along its left normal; a vertex is the meeting of
       its two moved edges (a plain parallel move where they are collinear) */
    var n = pts.length, i, out = [], segs = [];
    for(i=0;i<n-1+(closed?1:0);i++){
      var a = pts[i], b = pts[(i+1)%n];
      var ex = b[0]-a[0], ez = b[1]-a[1], L = Math.hypot(ex, ez);
      if(L < EPS){ segs.push(null); continue; }
      ex /= L; ez /= L;
      segs.push({a:{x:a[0]+ez*d, z:a[1]-ex*d}, u:{x:ex, z:ez}});   /* left normal (ez, -ex) */
    }
    function meet(s0, s1, fallback){
      if(!s0) return s1 ? [s1.a.x, s1.a.z] : fallback;
      if(!s1) return [s0.a.x + s0.u.x*0, s0.a.z + s0.u.z*0];
      var den = cross(s0.u, s1.u);
      if(Math.abs(den) < 1e-7) return [s1.a.x, s1.a.z];            /* collinear */
      var w = {x: s1.a.x - s0.a.x, z: s1.a.z - s0.a.z};
      var t = cross(w, s1.u)/den;
      return [s0.a.x + s0.u.x*t, s0.a.z + s0.u.z*t];
    }
    for(i=0;i<n;i++){
      var prev = closed ? segs[(i-1+segs.length)%segs.length] : (i>0 ? segs[i-1] : null);
      var next = closed ? segs[i%segs.length] : (i<segs.length ? segs[i] : null);
      if(!prev && next) out.push([next.a.x, next.a.z]);
      else if(prev && !next) out.push([prev.a.x + prev.u.x*dist({x:pts[i-1][0],z:pts[i-1][1]},{x:pts[i][0],z:pts[i][1]}),
                                       prev.a.z + prev.u.z*dist({x:pts[i-1][0],z:pts[i-1][1]},{x:pts[i][0],z:pts[i][1]})]);
      else out.push(meet(prev, next, pts[i]));
    }
    return out.map(function(p){ return [Math.round(p[0]*1e6)/1e6, Math.round(p[1]*1e6)/1e6]; });
  }

  AR_EXT.modes.offset = {
    hint: function(){ return 'Offset — click a wall, partition, guide line, guide circle or guide polygon, then give the distance (a negative distance offsets the other way).'; },
    cancel: function(){},
    click: function(P, e, g){
      var r = pick(e);
      if(!r){ arToast('Click a wall, partition or guide to offset.'); return; }
      var poly = (r.kind==='guide_poly' || r.kind==='guide_path') ? ptsOf(r.p && r.p.pts) : null;
      if(!poly && r.p && r.kind!=='wall' && r.kind!=='partition' && r.kind!=='guide_line' && r.kind!=='guide_circle') poly = ptsOf(r.p.pts);
      if(!isWall(r) && r.kind!=='guide_line' && r.kind!=='guide_circle' && !poly){
        arToast('<b>'+esc(arKindLabel(r.kind))+'</b> has no edge to offset — click a wall, a partition, a guide line, a guide circle or a guide polygon.','warn');
        return;
      }
      var d = ask(e, 'distance', 'Offset distance in metres (negative offsets the other way)', 1);
      if(d===null) return;
      if(Math.abs(d) < 1e-4){ arToast('An offset of 0 m would land on top of the original.','warn'); return; }
      arPush();
      var o;
      if(r.kind==='guide_circle'){
        o = clone(r, r.x, r.z);
        o.p.r = Math.max(0.01, num(r.p.r, 1) + d);
        arRebuild(o);
      } else if(poly){
        o = clone(r, r.x, r.z);
        o.p.pts = offsetPts(poly, d, !!(r.p && r.p.closed));
        arRebuild(o);
      } else {
        var nv = nrmOf(r);
        o = clone(r, r.x + nv.x*d, r.z + nv.z*d);
      }
      o.name = (r.name||arKindLabel(r.kind)) + ' offset';
      arSelect([o.id]); arSyncHoles(); arPanel(); arOutliner(); arDirty(true);
      arToast('Offset <b>'+esc(arKindLabel(r.kind))+'</b> by <b>'+arFmt(d)+' m</b>.');
    }
  };

  /* ── fillet ─────────────────────────────────────────────────────────────
     Click wall A, then wall B. Their centre lines are intersected; each wall's
     NEAR end is moved onto that corner (trimmed or extended) while its FAR end
     stays put. With a radius > 0 both are pulled back by r/tan(theta/2) — the
     tangent length of a fillet of radius r on an interior angle theta, which
     is the same number as the brief's r*tan(turn/2) — and one wall_arc of
     radius r is dropped between the two tangent points. */
  var FIL = {a: null};

  /* PLAN, then apply. Working out both trims before either wall is touched is
     what keeps a refusal honest: the earlier version moved wall A and only then
     discovered that wall B could not be trimmed, so "nothing done" was a lie
     and the half-applied edit sat inside the undo step. */
  function trimPlan(w, corner){
    /* whichever end of w is nearer `corner` is the one that will move */
    var E = ends(w), near = dist(E[0], corner) <= dist(E[1], corner) ? 0 : 1;
    var far = E[1-near], L = dist(far, corner);
    if(L < 1e-4) return null;
    return {far: far, len: L, u: {x: (corner.x-far.x)/L, z: (corner.z-far.z)/L}};
  }
  function applyTrim(w, far, end){
    var L = dist(far, end);
    w.p.len = Math.round(L*1e6)/1e6;
    w.x = (far.x + end.x)/2; w.z = (far.z + end.z)/2;
    w.ry = ryOf(far, end);
    arRebuild(w); arApplyTransform(w);
  }
  /* the point t back from the corner along a plan's own direction */
  function pullBack(pl, t){
    var nl = pl.len - t;
    return {x: pl.far.x + pl.u.x*nl, z: pl.far.z + pl.u.z*nl};
  }
  /* plan angle in DEGREES of a point about a centre: 0 = +X, 90 = -Z */
  function planDeg(c, p){ return Math.atan2(-(p.z-c.z), (p.x-c.x))*180/Math.PI; }

  AR_EXT.modes.fillet = {
    hint: function(){ return FIL.a ? 'Fillet — now click the SECOND wall, then give the radius (0 = a sharp corner).'
                                   : 'Fillet — click the FIRST of the two walls to join.'; },
    cancel: function(){ FIL.a = null; },
    click: function(P, e, g){
      var r = pick(e);
      if(!r){ arToast('Click a wall or partition.'); return; }
      if(!isWall(r)){ arToast('Fillet joins WALLS — <b>'+esc(arKindLabel(r.kind))+'</b> has no centre line.','warn'); return; }
      if(!FIL.a || !arFind(FIL.a.id)){
        FIL.a = r; arSelect([r.id]); arHint(AR_EXT.modes.fillet.hint());
        arToast('First wall: <b>'+esc(r.name)+'</b>. Now click the second.');
        return;
      }
      var A = FIL.a, B = r;
      if(A.id === B.id){ arToast('Click a DIFFERENT wall for the second edge.','warn'); return; }
      var dA = dirOf(A), dB = dirOf(B), den = cross(dA, dB);
      if(Math.abs(den) < 1e-6){ arToast('Those two walls are parallel — there is no corner to fillet.','warn'); FIL.a = null; return; }
      var EA = ends(A), EB = ends(B);
      var w0 = {x: EB[0].x - EA[0].x, z: EB[0].z - EA[0].z};
      var t = cross(w0, dB)/den;
      var X = {x: EA[0].x + dA.x*t, z: EA[0].z + dA.z*t};        /* the corner */
      var rad = ask(e, 'radius', 'Fillet radius in metres (0 = a sharp corner)', 0);
      if(rad===null){ FIL.a = null; return; }
      rad = Math.max(0, rad);

      /* both trims are worked out BEFORE anything is pushed or moved, so a
         refusal leaves the document (and the undo ring) untouched */
      var plA = trimPlan(A, X), plB = trimPlan(B, X);
      if(!plA || !plB){ arToast('One of the walls would collapse onto the corner — nothing done.','bad'); FIL.a = null; return; }
      /* unit vectors pointing AWAY from the corner along each wall */
      var uA = {x: -plA.u.x, z: -plA.u.z}, uB = {x: -plB.u.x, z: -plB.u.z};
      var theta = Math.acos(Math.max(-1, Math.min(1, uA.x*uB.x + uA.z*uB.z)));   /* interior angle */

      arPush();                                                   /* ONE push, before both edits */
      applyTrim(A, plA.far, X); applyTrim(B, plB.far, X);
      var ids = [A.id, B.id], arcRec = null, msg;
      if(rad > 1e-4 && theta > 1e-3 && Math.PI - theta > 1e-3){
        if(!(window.AR_EXT && AR_EXT.geom && AR_EXT.geom.wall_arc)){
          arToast('Corner joined SHARP: the rounded corner needs the <b>curved_walls</b> family (kind <code>wall_arc</code>) and it is not loaded.','warn');
        } else {
          var T = rad/Math.tan(theta/2);                            /* = rad * tan(turn/2) */
          if(plA.len - T < 0.05 || plB.len - T < 0.05){
            /* neither wall has been shortened yet: the sharp corner above stands */
            arToast('Radius <b>'+arFmt(rad)+' m</b> is bigger than the walls — the corner was left sharp.','warn');
          } else {
            var pa = pullBack(plA, T), pb = pullBack(plB, T);
            applyTrim(A, plA.far, pa); applyTrim(B, plB.far, pb);
            var bis = {x: uA.x + uB.x, z: uA.z + uB.z}, bl = Math.hypot(bis.x, bis.z);
            bis.x /= bl; bis.z /= bl;
            var cd = rad/Math.sin(theta/2);
            var C = {x: X.x + bis.x*cd, z: X.z + bis.z*cd};         /* the arc's centre */
            var a0 = planDeg(C, pa), a1 = planDeg(C, pb);
            var da = ((a1 - a0) % 360 + 540) % 360 - 180;           /* the short way round */
            arcRec = arNewObj('wall_arc', {r: Math.round(rad*1e6)/1e6, a0: Math.round(a0*1e4)/1e4,
                                           a1: Math.round((a0+da)*1e4)/1e4,
                                           h: (num(A.p.h, 2.7)+num(B.p.h, 2.7))/2,
                                           t: (num(A.p.t, 0.24)+num(B.p.t, 0.24))/2, seg: 24},
                              Math.round(C.x*1e6)/1e6, Math.round(C.z*1e6)/1e6, A.y||0);
            arcRec.mat = A.mat; arcRec.grp = A.grp||''; arcRec.name = 'Fillet';
            arApplyTransform(arcRec); arApplyMat(arcRec);
            ids.push(arcRec.id);
          }
        }
      }
      msg = arcRec ? ('Filleted with a <b>'+arFmt(rad)+' m</b> radius.')
                   : ('Corner joined at <b>'+arFmt(X.x)+', '+arFmt(X.z)+'</b>.');
      arSelect(ids); arSyncHoles(); arPanel(); arOutliner(); arDirty(true);
      arToast(msg);
      FIL.a = null;
      arHint(AR_EXT.modes.fillet.hint());
    }
  };

  /* ── follow me (sweep) ──────────────────────────────────────────────────
     Click the PATH, then give the profile. The path may be
       · one guide_line — with every guide_line joined to it end-to-end within
         1 cm walked in both directions, so a chain drawn with the Line tool is
         one path;
       · any record carrying p.pts (guide_poly, guide_path, slab_poly…);
       · a wall — its two ends.
     The result is ONE record of kind `sweep`, p {pts, w, h, closed}. */
  function chainOf(seed){
    var all = AR.objs.filter(function(o){ return o.kind==='guide_line' && !o.hidden; });
    var used = {}, E = ends(seed), path = [E[0], E[1]];
    used[seed.id] = 1;
    function grow(atEnd){
      for(var guard=0; guard<400; guard++){
        var tip = atEnd ? path[path.length-1] : path[0], found = null;
        for(var i=0;i<all.length;i++){
          var o = all[i];
          if(used[o.id] || Math.abs((o.y||0) - (seed.y||0)) > 1e-6) continue;
          var e2 = ends(o);
          if(dist(e2[0], tip) <= TOL){ found = {o: o, next: e2[1]}; break; }
          if(dist(e2[1], tip) <= TOL){ found = {o: o, next: e2[0]}; break; }
        }
        if(!found) return;
        used[found.o.id] = 1;
        if(atEnd) path.push(found.next); else path.unshift(found.next);
        if(dist(path[0], path[path.length-1]) <= TOL) return;     /* closed the loop */
      }
    }
    grow(true); grow(false);
    return path;
  }

  AR_EXT.modes.follow = {
    hint: function(){ return 'Follow me — click the path first (a guide line or chain of them, a guide polygon or a wall), then give the profile width and height.'; },
    cancel: function(){},
    click: function(P, e, g){
      var r = pick(e);
      if(!r){ arToast('Click the path to sweep along: a guide line, a guide polygon or a wall.'); return; }
      var world = null, closed = 0, pl = ptsOf(r.p && r.p.pts);
      if(pl){
        world = pl.map(function(p){ return toWorld(r, p); });
        closed = r.p.closed ? 1 : 0;
      } else if(r.kind==='guide_line'){
        world = chainOf(r);
      } else if(isWall(r) || r.kind==='beam'){
        world = ends(r);
      } else {
        arToast('<b>'+esc(arKindLabel(r.kind))+'</b> is not a path — click a guide line, a guide polygon or a wall.','warn');
        return;
      }
      if(!world || world.length < 2){ arToast('That path has no length to sweep along.','warn'); return; }
      if(!closed && world.length > 2 && dist(world[0], world[world.length-1]) <= TOL){ world.pop(); closed = 1; }
      var w = ask(e, 'w', 'Profile WIDTH in metres', 0.3);
      if(w===null) return;
      var h = ask(e, 'h', 'Profile HEIGHT in metres', 0.3);
      if(h===null) return;
      w = Math.max(0.005, Math.abs(w)); h = Math.max(0.005, Math.abs(h));
      var cx = 0, cz = 0, i;
      for(i=0;i<world.length;i++){ cx += world[i].x; cz += world[i].z; }
      cx = Math.round(cx/world.length*1e6)/1e6; cz = Math.round(cz/world.length*1e6)/1e6;
      var pts = world.map(function(p){ return [Math.round((p.x-cx)*1e6)/1e6, Math.round((p.z-cz)*1e6)/1e6]; });
      arPush();
      var o = arNewObj('sweep', {pts: pts, w: Math.round(w*1e6)/1e6, h: Math.round(h*1e6)/1e6, closed: closed},
                       cx, cz, r.y||0);
      o.mat = r.mat && r.kind!=='guide_line' ? r.mat : 'mat_timber';
      o.name = 'Sweep';
      arApplyTransform(o); arApplyMat(o);
      arSelect([o.id]); arSyncHoles(); arPanel(); arOutliner(); arDirty(true);
      var legs = pts.length - 1 + (closed ? 1 : 0);
      arToast('Swept a <b>'+arFmt(w)+' &times; '+arFmt(h)+' m</b> profile along <b>'+legs+'</b> leg'+(legs===1?'':'s')+'.');
    }
  };

  /* ── the kind the sweep makes ───────────────────────────────────────────
     One box per leg, butt-jointed (no mitre): the same recipe arMemberG uses,
     written out so the section stays UPRIGHT (w across the path, h up) instead
     of following a 3-D direction. Local frame: the record's x/z is the origin
     of p.pts, bottom at y = 0. */
  AR_EXT.geom.sweep = function(p, k){
    var pts = ptsOf(p && p.pts) || [[0,0],[1,0]];
    var w = Math.max(0.005, k.num(p.w, 0.3)), h = Math.max(0.005, k.num(p.h, 0.3));
    var closed = !!(p && p.closed), out = [], i, n = pts.length;
    var last = closed ? n : n-1;
    for(i=0;i<last;i++){
      var a = pts[i], b = pts[(i+1)%n];
      var dx = b[0]-a[0], dz = b[1]-a[1], L = Math.hypot(dx, dz);
      if(L < 1e-4) continue;
      var g = k.box(L, h, w, 0, h/2, 0);
      g.rotateY(Math.atan2(-dz, dx));            /* local +X onto the leg */
      g.translate((a[0]+b[0])/2, 0, (a[1]+b[1])/2);
      out.push({g: g});
    }
    if(!out.length) out.push({g: k.box(0.05, h, w, 0, h/2, 0)});
    return out;
  };
  AR_EXT.label.sweep = 'Swept profile';
})();
