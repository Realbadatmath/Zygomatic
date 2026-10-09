// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* precision_input — Precision ▸ Angle snap, Axis lock, Work plane, Type it, Guides
   (2026-09-07). Five dock icons wired through the ICON seam alone: nothing in
   inspection.html is edited, and every mechanism below is a published hook.

   WHERE EACH ICON CAN ACT (the honest seams)
   ─ pr_angle has TWO mechanisms, because the studio's 15° rotate snap lives
     inside arDragStep and no hook sees it:
       (a) DRAFTING — an AR_EXT.snaps hook rounds the direction from AR.draft.a
           to the pointer to the increment, so a wall/line/beam run lands on
           5° / 10° / 22.5° / … while keeping the distance you dragged;
       (b) ROTATE — an AR_EXT.ticks hook watches the selection's ry between
           frames while AR.tool === 'rotate'. A drag step changed it → the tick
           re-rounds ry to the increment, so the drag ENDS on your increment
           even though arDragStep quantised it to 15° on the way.
   ─ pr_axis locks the next drag/draft to an axis: the same snaps hook projects
     the pointer onto the axis line through AR.draft.a while drafting, and the
     same ticks hook re-imposes the locked coordinate on the selection during a
     move drag. shift+X / shift+Z / shift+Y set it from the keyboard.
   ─ pr_plane moves the DRAWING PLANE (AR.level) onto a record's top face. It is
     the LEVEL-plane version of "draw on a face": a tilted work plane would need
     arGroundAt to intersect an arbitrary plane, which is inside inspection.html
     and not reachable from a hook — see not_done.
   ─ pr_coord completes an open draft at an exact point by arming a one-shot
     override in the snaps hook and then calling arClick at a screen point whose
     ground ray hits the plane; the override, not the pointer, decides the point.
     arClick is wrapped so the one-shot dies on the click and survives moves.
   ─ pr_guide shows / hides / clears every record whose kind starts with 'guide_'.

   STATE. Per drawing in AR.doc.ext.precision_input (JSON-plain: saved, loaded,
   round-tripped through the assistant): {angle, angle_on, axis, plane, guides}.
   Settings are NOT put on the undo ring — arSnapshot() holds records only, so an
   arPush() for a setting would push a no-op. pr_guide DOES change records and so
   calls arPush() once, before the change. */
(function(){
'use strict';

var FAM = 'precision_input';
var DEF = {angle: 15, angle_on: false, axis: 'off', plane: null, guides: 'show'};
/* the two-click tools whose direction an angle snap means something for */
var DIR_TOOLS = {wall: 1, line: 1, beam: 1};
var AXIS_NEXT = {off: 'x', x: 'z', z: 'y', y: 'off'};
/* the studio's own digit shortcuts — reproduced so binding 0-9 for "type it"
   does not silently swallow the view keys when there is no draft open */
var VIEW_KEY = {'1': 'v_top', '2': 'v_front', '3': 'v_right', '4': 'v_iso',
                '5': 'v_back', '6': 'v_left', '7': 'v_bottom'};

function num(v, d){ v = Number(v); return isFinite(v) ? v : d; }
function tidy(v){ return Math.round(v * 1e6) / 1e6; }

/* read-only view of the settings: never creates AR.doc.ext (on() and the frame
   hooks call this, and a report must not write to the document) */
function piRead(){
  var e = (window.AR && AR.doc && AR.doc.ext && AR.doc.ext[FAM]) || null;
  if(!e || typeof e !== 'object') return {angle: DEF.angle, angle_on: false, axis: 'off', plane: null, guides: 'show'};
  return {angle: (typeof e.angle === 'number' && isFinite(e.angle)) ? e.angle : DEF.angle,
          angle_on: !!e.angle_on,
          axis: (e.axis === 'x' || e.axis === 'y' || e.axis === 'z') ? e.axis : 'off',
          plane: (e.plane && typeof e.plane === 'object') ? e.plane : null,
          guides: (e.guides === 'hide') ? 'hide' : 'show'};
}
/* writable settings object, created on first use */
function piState(){
  AR.doc = AR.doc || {id: '', name: 'Untitled drawing'};
  if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
  var s = AR.doc.ext[FAM];
  if(!s || typeof s !== 'object') s = AR.doc.ext[FAM] = {};
  var r = piRead();
  s.angle = r.angle; s.angle_on = r.angle_on; s.axis = r.axis;
  s.plane = r.plane; s.guides = r.guides;
  return s;
}
function isGuide(o){ return String((o && o.kind) || '').indexOf('guide_') === 0; }
function guideRecs(){ return (window.AR && AR.objs) ? AR.objs.filter(isGuide) : []; }

/* ── the snap hook: typed point ▸ axis lock ▸ angle snap ─────────────────── */
var piOnce = null;              /* {x, z, y} — the next arClick lands exactly here */

AR_EXT.snaps.push(function(P, g, e){
  if(!P || !window.AR) return null;
  if(piOnce) return {x: piOnce.x, z: piOnce.z,
                     y: (piOnce.y !== undefined ? piOnce.y : P.y), snap: 'typed'};
  var d = AR.draft;
  if(!d || !d.a) return null;
  var s = piRead(), a = d.a;
  if(s.axis !== 'off'){
    /* x-lock slides along X (z frozen), z-lock along Z, y-lock pins the plan
       point entirely — a vertical lock has no freedom on the drawing plane */
    if(s.axis === 'x') return {x: P.x, z: a.z, y: P.y, snap: 'axis X'};
    if(s.axis === 'z') return {x: a.x, z: P.z, y: P.y, snap: 'axis Z'};
    return {x: a.x, z: a.z, y: P.y, snap: 'axis Y'};
  }
  if(!s.angle_on || !(s.angle > 0) || !DIR_TOOLS[AR.tool]) return null;
  var dx = P.x - a.x, dz = P.z - a.z, dist = Math.hypot(dx, dz);
  if(dist < 1e-6) return null;
  var inc = s.angle * Math.PI / 180;
  var th = Math.round(Math.atan2(-dz, dx) / inc) * inc;       /* 0° = +X, 90° = −Z */
  return {x: tidy(a.x + dist * Math.cos(th)), z: tidy(a.z - dist * Math.sin(th)),
          y: P.y, snap: 'angle ' + s.angle + '\u00b0'};
});

/* ── the frame hook: rotate angle snap + axis lock during a move drag ────── */
var ryPrev = null;              /* id -> ry last frame (rotate) */
var mvState = null;             /* {prev, base} per-id positions (move) */

AR_EXT.ticks.push(function(){
  if(!window.AR || !AR.objs) return;
  var T = AR.tool;
  if(T !== 'rotate') ryPrev = null;
  if(T !== 'move') mvState = null;
  if(T !== 'rotate' && T !== 'move') return;
  var s = piRead();
  if(T === 'rotate' && s.angle > 0) rotateTick(s);
  else if(T === 'move' && s.axis !== 'off') moveTick(s);
});

function rotateTick(s){
  var recs = arSelRecs();
  if(!recs.length){ ryPrev = null; return; }
  var now = {}, changed = false, i, r;
  for(i = 0; i < recs.length; i++){
    r = recs[i]; now[r.id] = r.ry || 0;
    if(ryPrev && ryPrev[r.id] !== undefined && Math.abs((r.ry || 0) - ryPrev[r.id]) > 1e-9) changed = true;
  }
  if(changed){
    var inc = s.angle * Math.PI / 180;
    for(i = 0; i < recs.length; i++){
      r = recs[i];
      var q = Math.round((r.ry || 0) / inc) * inc;
      if(Math.abs(q - (r.ry || 0)) > 1e-12){ r.ry = q; arApplyTransform(r); }
      now[r.id] = r.ry || 0;
    }
  }
  ryPrev = now;
}

function moveTick(s){
  var recs = arSelRecs();
  if(!recs.length){ mvState = null; return; }
  var cur = {}, changed = false, i, r, p;
  for(i = 0; i < recs.length; i++){
    r = recs[i]; cur[r.id] = {x: r.x, y: r.y, z: r.z};
    p = mvState && mvState.prev && mvState.prev[r.id];
    if(p && (Math.abs(r.x - p.x) > 1e-9 || Math.abs(r.y - p.y) > 1e-9 || Math.abs(r.z - p.z) > 1e-9)) changed = true;
  }
  if(!changed){ mvState = {prev: cur, base: null}; return; }
  var base = (mvState && mvState.base) || mvState.prev;        /* the pre-drag positions */
  var fixed = {};
  for(i = 0; i < recs.length; i++){
    r = recs[i]; var b = base[r.id];
    if(b){
      if(s.axis === 'x'){ r.z = b.z; r.y = b.y; }
      else if(s.axis === 'z'){ r.x = b.x; r.y = b.y; }
      else { r.x = b.x; r.z = b.z; }                            /* Y: only up/down survives */
      arApplyTransform(r);
    }
    fixed[r.id] = {x: r.x, y: r.y, z: r.z};
  }
  mvState = {prev: fixed, base: base};
}

/* ── wrapping two globals: the hint badge and the one-shot's lifetime ────── */
AR_EXT.ready.push(function(){
  var baseHint = arHint;
  arHint = function(html){
    if(!html){ baseHint(html); return; }
    var s = piRead(), tags = [];
    if(s.axis !== 'off') tags.push('lock <b>' + s.axis.toUpperCase() + '</b>');
    if(s.angle_on && s.angle > 0) tags.push('angle <b>' + s.angle + '&deg;</b>');
    if(s.plane) tags.push('plane <b>' + arFmt(num(s.plane.h, 0)) + ' m</b>');
    if(piOnce) tags.push('typed <b>' + arFmt(piOnce.x) + ', ' + arFmt(piOnce.z) + '</b>');
    baseHint(tags.length ? (html + ' &nbsp;&middot;&nbsp; ' + tags.join(' &nbsp; ')) : html);
  };
  /* a typed point must survive every pointer move (arDraftMove snaps too) and
     die on the click that spends it — so it is cleared HERE and nowhere else */
  var baseClick = arClick;
  arClick = function(e){
    try{ baseClick(e); }
    finally{ if(piOnce){ piOnce = null; arHint(arToolHint(AR.tool)); } }
  };
});

/* ── pr_angle ───────────────────────────────────────────────────────────── */
AR_EXT.tools.pr_angle = {
  assist: 1,
  tip: 'Angle snap increment — drafting a wall, line or beam rounds its direction to it, '
     + 'and a rotate drag lands on it instead of the studio\u2019s 15&deg;',
  on: function(){ return piRead().angle !== 15; },
  act: function(opt){
    var s = piState(), deg = null;
    if(opt && typeof opt === 'object' && opt.deg !== undefined) deg = Number(opt.deg);
    else if(opt && typeof opt === 'object' && opt.degrees !== undefined) deg = Number(opt.degrees);
    else {
      var t = prompt('Angle snap increment in degrees (0 = off, 15 = the studio default)', String(s.angle));
      if(t === null) return;
      deg = Number(String(t).replace(/[^0-9.]/g, ''));
    }
    if(!isFinite(deg) || deg < 0 || deg >= 180){ arToast('Angle snap wants 0\u2013179 degrees.', 'bad'); return; }
    s.angle = Math.round(deg * 1000) / 1000;
    s.angle_on = s.angle > 0;
    arDirty(true); arOpts(); arHint(arToolHint(AR.tool));
    arToast(s.angle > 0
      ? 'Angle snap <b>' + s.angle + '&deg;</b> \u2014 wall/line/beam runs and rotate drags land on it.'
      : 'Angle snap <b>off</b> for drafting; a rotate drag still uses the studio\u2019s 15&deg; (hold <b>Alt</b> for free angles).');
  }
};

/* ── pr_axis ────────────────────────────────────────────────────────────── */
function axisReport(s){
  arDirty(true); arOpts(); arToolsRender(); arHint(arToolHint(AR.tool));
  arToast(s.axis === 'off'
    ? 'Axis lock <b>off</b>.'
    : 'Axis lock <b>' + s.axis.toUpperCase() + '</b> \u2014 the next draft and the next move drag keep every other coordinate.');
}
function axisSet(a){
  var s = piState();
  s.axis = (s.axis === a) ? 'off' : a;
  axisReport(s);
}
AR_EXT.tools.pr_axis = {
  assist: 1,
  tip: 'Lock the next drag or draft to X, Y or Z \u2014 press to cycle, or shift+X / shift+Z / shift+Y',
  on: function(){ return piRead().axis !== 'off'; },
  act: function(opt){
    var s = piState(), ax = null;
    if(opt && typeof opt === 'object' && opt.axis !== undefined) ax = String(opt.axis).toLowerCase().trim();
    if(ax === null) ax = AXIS_NEXT[s.axis] || 'x';
    if(ax === '' || ax === 'none' || ax === 'free') ax = 'off';
    if(['x', 'y', 'z', 'off'].indexOf(ax) < 0){ arToast('Axis lock wants <b>x</b>, <b>z</b>, <b>y</b> or <b>off</b>.', 'bad'); return; }
    s.axis = ax;
    axisReport(s);
  }
};
AR_EXT.keys['shift+x'] = function(){ axisSet('x'); };
AR_EXT.keys['shift+z'] = function(){ axisSet('z'); };
AR_EXT.keys['shift+y'] = function(){ axisSet('y'); };

/* ── pr_plane ───────────────────────────────────────────────────────────── */
function planeSet(rec, face){
  var top = num(rec.y, 0);
  if(rec.node){
    var b = new THREE.Box3().setFromObject(rec.node);
    if(!b.isEmpty()) top = (face === 'bottom') ? b.min.y : b.max.y;
  }
  if(!isFinite(top)) top = num(rec.y, 0);
  top = Math.round(top * 10000) / 10000;
  var s = piState();
  s.plane = {rec: rec.id, face: (face === 'bottom' ? 'bottom' : 'top'), h: top};
  arSetLevel(top);
  arDirty(true); arToolsRender(); arOpts();
  var nm = rec.name || arKindLabel(rec.kind) || rec.kind;
  arToast('Work plane on <b>' + esc(String(nm)) + '</b> at <b>' + arFmt(top) + ' m</b>.');
  arHint('Drawing on <b>' + esc(String(nm)) + '</b> at ' + arFmt(top) + ' m \u2014 press <b>Work plane</b> again for the ground.');
}
AR_EXT.modes.pr_plane_pick = {
  click: function(P, e, g){
    var h = arPick(e);
    if(!h){ arToast('Click an object \u2014 the work plane goes on its top face.', 'warn'); return; }
    planeSet(h.rec, 'top');
    arToolApply('select');
  },
  move: function(){ AR.rubber.visible = false; },
  hint: function(){ return 'Work plane: click the object to draw on \u2014 the plane moves to its top face. <b>Esc</b> cancels.'; },
  cancel: function(){},
  key: function(e){ if(e.key === 'Escape'){ arToolApply('select'); return true; } return false; }
};
AR_EXT.tools.pr_plane = {
  assist: 1,
  tip: 'Draw on a face instead of the ground \u2014 the drawing plane moves to the top face of the object you click; press again for the ground',
  on: function(){ return !!piRead().plane; },
  act: function(opt){
    var s = piState();
    if(s.plane){
      s.plane = null; arSetLevel(0);
      arDirty(true); arToolsRender(); arOpts(); arHint(arToolHint(AR.tool));
      arToast('Work plane back on the ground at <b>0.00 m</b>.');
      return;
    }
    var rec = null, face = 'top';
    if(opt && typeof opt === 'object'){
      if(opt.face) face = String(opt.face).toLowerCase();
      if(opt.rec !== undefined){
        rec = arFind(String(opt.rec));
        if(!rec){ arToast('No object with id <b>' + esc(String(opt.rec)) + '</b>.', 'bad'); return; }
      } else if(!opt.pick && AR.sel.length) rec = arFind(AR.sel[0]);
    }
    if(rec){ planeSet(rec, face); return; }
    arToolApply('pr_plane_pick');
    arToast('Click the object whose top face the work plane should sit on.');
  }
};

/* ── pr_coord ───────────────────────────────────────────────────────────── */
/* a screen point whose ground ray meets the drawing plane: arClick needs a
   pointer event for arGroundAt, and the snap hook decides the point anyway */
function aimEvent(){
  var c = AR.renderer && AR.renderer.domElement;
  if(!c) return null;
  AR.cam.updateMatrixWorld(true);
  var r = c.getBoundingClientRect();
  var cand = [[0.5, 0.5], [0.5, 0.62], [0.5, 0.75], [0.5, 0.38], [0.35, 0.6], [0.65, 0.6]];
  for(var i = 0; i < cand.length; i++){
    var e = {clientX: r.left + r.width * cand[i][0], clientY: r.top + r.height * cand[i][1],
             shiftKey: false, altKey: false, ctrlKey: false, button: 0};
    if(arGroundAt(e)) return e;
  }
  return null;
}
AR_EXT.tools.pr_coord = {
  assist: 1,
  tip: 'Type it \u2014 finish the run at an exact length and angle, or an exact point, instead of clicking it. '
     + 'With a draft open the digit keys open it pre-filled',
  act: function(opt){
    var a = (AR.draft && AR.draft.a) || null;
    var len = null, ang = 0, px = null, pz = null, rel = false;
    if(opt && typeof opt === 'object'){
      if(opt.len !== undefined || opt.length !== undefined){
        len = Number(opt.len !== undefined ? opt.len : opt.length);
        ang = num(opt.angle, 0);
      } else if(opt.x !== undefined || opt.z !== undefined){
        px = num(opt.x, 0); pz = num(opt.z, 0); rel = !!opt.relative;
      } else { arToast('Type it wants <b>{len, angle}</b> or <b>{x, z}</b>.', 'bad'); return; }
    } else {
      var pre = (typeof opt === 'string') ? opt : '';
      var txt = prompt(a ? 'Length, angle\u00b0   \u2014 or  @dx, dz  for an offset,  =x, z  for a point'
                         : 'Point as  x, z  \u2014 the next click lands there',
                       pre || (a ? '5, 0' : '0, 0'));
      if(txt === null) return;
      txt = String(txt).trim();
      if(!txt){ return; }
      var abs = false;
      if(txt.charAt(0) === '@'){ rel = true; txt = txt.slice(1); }
      else if(txt.charAt(0) === '='){ abs = true; txt = txt.slice(1); }
      var bits = txt.split(/[,;\s]+/).filter(function(b){ return b !== ''; }).map(Number);
      if(!bits.length || bits.some(function(b){ return !isFinite(b); })){
        arToast('Could not read <b>' + esc(String(txt)) + '</b> \u2014 try  <b>5</b>  or  <b>5, 90</b>  or  <b>@2, -3</b>.', 'bad');
        return;
      }
      if(rel || abs || !a){ px = bits[0]; pz = num(bits[1], 0); }
      else { len = bits[0]; ang = num(bits[1], 0); }
    }

    var pt;
    if(len !== null){
      if(!isFinite(len) || len <= 0){ arToast('Type it wants a length greater than zero.', 'bad'); return; }
      if(!a){ arToast('Start the run first \u2014 click where the wall or line begins, then type its length.', 'warn'); return; }
      var th = ang * Math.PI / 180;
      pt = {x: tidy(a.x + len * Math.cos(th)), z: tidy(a.z - len * Math.sin(th)), y: a.y};
    } else if(rel){
      if(!a){ arToast('An offset needs a run in progress \u2014 type <b>=x, z</b> for a point instead.', 'warn'); return; }
      pt = {x: tidy(a.x + px), z: tidy(a.z + pz), y: a.y};
    } else {
      pt = {x: tidy(px), z: tidy(pz), y: a ? a.y : AR.level};
    }

    piOnce = pt;
    if(!a){
      arHint('Next click lands at <b>x ' + arFmt(pt.x) + ' &nbsp; z ' + arFmt(pt.z) + '</b> \u2014 click anywhere in the viewport.');
      arToast('Next click set to <b>' + arFmt(pt.x) + ', ' + arFmt(pt.z) + '</b> \u2014 arm a tool and click.');
      return;
    }
    var ev = aimEvent();
    if(!ev){
      piOnce = null;
      arToast('The drawing plane is not on screen \u2014 orbit until the ground is visible and type it again.', 'bad');
      return;
    }
    var was = AR.objs.length;
    arClick(ev);
    arToast(len !== null
      ? 'Typed <b>' + arFmt(len) + ' m</b> at <b>' + arFmt(ang) + '&deg;</b>' + (AR.objs.length > was ? '.' : ' \u2014 nothing was drawn.')
      : 'Typed <b>' + arFmt(pt.x) + ', ' + arFmt(pt.z) + '</b>' + (AR.objs.length > was ? '.' : ' \u2014 nothing was drawn.'));
  }
};
/* digits open Type it pre-filled WHILE a draft is open; with no draft they must
   behave exactly as the studio's own keydown map does, because AR_EXT.keys is
   consulted first and swallows the key either way */
'0123456789'.split('').forEach(function(d){
  AR_EXT.keys[d] = function(){
    if(AR.draft && AR.draft.a){ AR_EXT.tools.pr_coord.act(d); return; }
    if(VIEW_KEY[d]) arTool(VIEW_KEY[d]);
  };
});

/* ── pr_guide ───────────────────────────────────────────────────────────── */
AR_EXT.tools.pr_guide = {
  assist: 1,
  tip: 'Guides \u2014 show or hide every guide line and circle, or clear them all in one go',
  on: function(){
    var gs = guideRecs();
    return gs.length > 0 && gs.every(function(r){ return !!r.hidden; });
  },
  act: function(opt){
    var s = piState(), mode = null;
    if(opt && typeof opt === 'object' && opt.mode !== undefined) mode = String(opt.mode).toLowerCase().trim();
    if(mode === null){
      /* the prompt is pre-filled with the next step of the cycle, so Enter
         cycles show/hide and typing "clear" is the way to the third door */
      var next = AR_EXT.tools.pr_guide.on() ? 'show' : 'hide';
      var t = prompt('Guides: show, hide or clear?', next);
      if(t === null) return;
      mode = String(t).toLowerCase().trim();
    }
    if(['show', 'hide', 'clear'].indexOf(mode) < 0){ arToast('Guides: type <b>show</b>, <b>hide</b> or <b>clear</b>.', 'bad'); return; }
    var gs = guideRecs();
    if(!gs.length){ arToast('No guides in this drawing \u2014 the <b>Line</b> and <b>Circle</b> tools draw them.', 'warn'); return; }
    if(mode === 'clear'){
      if(!confirm('Delete ' + gs.length + ' guide' + (gs.length === 1 ? '' : 's') + '? Undo brings them back.')) return;
      arPush();
      gs.forEach(function(r){ arRemove(r); });
      AR.sel = AR.sel.filter(function(id){ return !!arFind(id); });
      s.guides = 'show';
      arSelSync(); arOutliner(); arPanel(); arToolsRender(); arDirty(true);
      arToast('Cleared <b>' + gs.length + '</b> guide' + (gs.length === 1 ? '' : 's') + '.');
      return;
    }
    var hide = (mode === 'hide');
    arPush();
    gs.forEach(function(r){ r.hidden = hide; arApplyTransform(r); });
    s.guides = hide ? 'hide' : 'show';
    arSelSync(); arOutliner(); arPanel(); arToolsRender(); arDirty(true);
    arToast((hide ? 'Hid ' : 'Showing ') + '<b>' + gs.length + '</b> guide' + (gs.length === 1 ? '' : 's') + '.');
  }
};

})();
