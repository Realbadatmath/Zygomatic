// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* organise_model — Organise ▸ Make component, Components, Storeys, Grid lines, Rooms,
   Room labels. Six icons of the dock's Organise section, wired through the ICON seam
   (AR_EXT). Nothing in inspection.html is edited; three new kinds are
   registered through AR_EXT.geom.

   THE THREE KINDS
   ---------------
   component  p {name, children:[{kind, p, x, y, z, rx, ry, rz, s, mat} …]}
       One definition, many instances. The children's x/y/z are RELATIVE to
       the component's origin, which is the selection's plan centre on its
       lowest ground (bbox centre in x/z, bbox min in y). The geometry is the
       children's own arGeom() output, each part transformed by the child's
       matrix and carried over with its material: a part keeps its own `sub`
       when it has one, otherwise the child's `mat` becomes the part's `sub`,
       so a component of a brick wall and a glass pane stays brick and glass
       whatever the instance's own material is.
       THE DEFINITION lives in AR.doc.ext.organise_model.components[name]
       (saved with the drawing, round-trips through the assistant). An
       instance's p.children is a COPY of it — parameters, so an old file
       that predates the definition still loads and still draws. "Edit
       definition" (the browser sheet, or o_comp {edit:name, from:instanceId})
       rewrites the definition from the chosen instance and then rewrites
       every other instance's p.children from it and rebuilds them.
       LIMITS, honestly: explode composes only ry (a component tipped with
       rx/rz explodes to children without that tip); a wall inside a component
       is no longer a `wall` record, so arSyncHoles() cannot cut an opening
       into it.

   gridline   p {len, label, axis:'x'|'z'}
       A structural grid line: a LINE part along the drawing plane (no solid,
       VOID in Blender — arch_assistant_ext/organise_model.VOID_KINDS) plus its
       label as a canvas sprite at the far end, maintained by the ticks hook.
       A gridline is deliberately a WALL-LIKE SEGMENT: it carries p.len and ry
       exactly as a wall does (local +X, centred on x/z, ry = -PI/2 runs it
       along +Z), so any generic "segment" reading finds its two ends and its
       crossings with no special case for the kind.
       BUT the studio has no such generic reading yet, so the snap the tooltip
       promises is registered here — see "grid snap" below.

   zone       p {pts:[[x,z] …] local, name, use, h}
       A room/zone: a thin extruded polygon (THREE.Shape -> ExtrudeGeometry,
       h 0.05 m) so it is pickable and reads on the plan, in a flat colour
       preset chosen by its use, labelled with its name and its shoelace area
       in m² by the same ticks hook.

   STATE.  AR.doc.ext.organise_model = {components:{name:[children]}, storeys:
   [{name, el, h}], labels:false}. NOTE: the studio's undo ring (arSnapshot) holds the RECORDS
   only — AR.doc.ext is outside it, so undo after a storey edit restores the
   records but not the storey list. That is the studio's snapshot, not this
   family's to change; every edit here still calls arPush() first, which is
   what marks the drawing dirty.

   ROOM LABELS ARE OFF BY DEFAULT (2026-09-12). The zone label sprites (name +
   area) used to be drawn unconditionally; on a 20-storey tower that is 76
   "Apartment x.xx" strips over the facade before anyone asked for them. They
   now follow AR.doc.ext.organise_model.labels — Organise ▸ Room labels
   (o_zone_labels), a switch saved with the drawing, so a file nobody pressed
   it on opens clean. Grid-line letters are NOT governed by it: a grid line
   without its letter is not a grid line.

   THE STOREY HEIGHTS ARE OURS ONLY. A storey's own h is honoured by the
   Storeys sheet's "go" buttons and by organise_model.storeyAt(y). The dock's
   built-in Level up / Level down (pr_up / pr_dn) step AR.defaults.wall_h
   (2.7 m) and are not ours to change without editing inspection.html, so a
   3.0 m storey is reached from the sheet, not from those two arrows. */
(function(){
  'use strict';

  var DEF_H = 2.7;                       /* the studio's own storey height */
  var geomDepth = 0;                     /* a component inside a component: bounded */
  var gridDraft = null;                  /* the gridline mode's first point */
  var zoneDraft = null;                  /* the zone mode's vertex chain */

  function N(v, d){ return (typeof arNum === 'function') ? arNum(v, d) : (isFinite(+v) ? +v : d); }
  function clone(v){ return JSON.parse(JSON.stringify(v === undefined ? null : v)); }
  function isObj(o){ return !!o && typeof o === 'object' && !Array.isArray(o); }
  /* the sheet has no button style of its own — carry one rather than invent a class */
  var BTN = ' style="border:1px solid var(--line);background:transparent;color:var(--muted);'
          + 'border-radius:4px;padding:1px 6px;font:inherit;font-size:.68rem;cursor:pointer"';
  function btn(call, lb, t){
    return '<button' + BTN + ' onclick="' + call + '" title="' + esc(t) + '">' + esc(lb) + '</button>';
  }

  /* ── document state ─────────────────────────────────────────────────── */
  function ext(){
    if(!AR.doc) AR.doc = {ext:{}};
    if(!isObj(AR.doc.ext)) AR.doc.ext = {};
    var e = AR.doc.ext.organise_model;
    if(!isObj(e)) e = AR.doc.ext.organise_model = {};
    if(!isObj(e.components)) e.components = {};
    if(!Array.isArray(e.storeys) || !e.storeys.length)
      e.storeys = [{name:'Ground', el:0, h:(AR.defaults && AR.defaults.wall_h) || DEF_H}];
    return e;
  }

  /* read-only: a drawing nobody pressed the switch on must not be stamped */
  function labelsOn(){
    var e = window.AR && AR.doc && isObj(AR.doc.ext) ? AR.doc.ext.organise_model : null;
    return !!(isObj(e) && e.labels);
  }

  function childList(p){ return (isObj(p) && Array.isArray(p.children)) ? p.children : []; }
  function instances(name){
    return AR.objs.filter(function(o){ return o.kind === 'component' && String((o.p||{}).name||'') === name; });
  }

  /* ── geometry ───────────────────────────────────────────────────────── */
  AR_EXT.geom.component = function(p, k){
    var THREE = k.THREE, out = [];
    if(geomDepth > 4) return out;                 /* a component that contains itself */
    geomDepth++;
    try{
      childList(p).forEach(function(c){
        if(!isObj(c) || !c.kind) return;
        var parts;
        try{ parts = arGeom(String(c.kind), isObj(c.p) ? c.p : {}) || []; }
        catch(e){ parts = []; }
        var s = k.num(c.s, 1) || 1;
        var m = new THREE.Matrix4().compose(
          new THREE.Vector3(k.num(c.x, 0), k.num(c.y, 0), k.num(c.z, 0)),
          new THREE.Quaternion().setFromEuler(new THREE.Euler(k.num(c.rx, 0), k.num(c.ry, 0), k.num(c.rz, 0))),
          new THREE.Vector3(s, s, s));
        parts.forEach(function(pt){
          if(!pt || !pt.g) return;
          var g = pt.g.clone();
          g.applyMatrix4(m);
          var o = {g:g};
          if(pt.line) o.line = 1;
          if(pt.strip) o.strip = 1;
          if(pt.vcolors) o.vcolors = pt.vcolors;
          /* the part's own sub wins; otherwise the CHILD's material becomes the
             sub, so the component keeps the materials it was made from */
          var sub = pt.sub || c.mat;
          if(sub) o.sub = sub;
          out.push(o);
        });
      });
    } finally { geomDepth--; }
    return out;
  };

  AR_EXT.geom.gridline = function(p, k){
    var L = Math.max(0.1, k.num(p && p.len, 20));
    var g = new k.THREE.BufferGeometry().setFromPoints(
      [new k.THREE.Vector3(-L/2, 0, 0), new k.THREE.Vector3(L/2, 0, 0)]);
    return [{g:g, line:1}];
  };

  /* a use is a flat colour, not a texture: a zone is a diagram over the model */
  var ZONE_MAT = {living:'mat_timber', bedroom:'mat_plaster', kitchen:'mat_concrete',
                  bathroom:'mat_glass', circulation:'mat_asphalt', office:'mat_plaster',
                  retail:'mat_brick', storage:'mat_concrete', plant:'mat_concrete',
                  outdoor:'mat_grass', garden:'mat_grass'};

  function zonePts(p){
    var out = [];
    if(!isObj(p) || !Array.isArray(p.pts)) return out;
    p.pts.forEach(function(q){
      if(!q) return;
      var x = N(q[0], NaN), z = N(q[1], NaN);
      if(isFinite(x) && isFinite(z)) out.push([x, z]);
    });
    return out;
  }
  function shoelace(pts){
    var s = 0;
    for(var i=0;i<pts.length;i++){
      var a = pts[i], b = pts[(i+1)%pts.length];
      s += a[0]*b[1] - b[0]*a[1];
    }
    return Math.abs(s)/2;
  }

  AR_EXT.geom.zone = function(p, k){
    var THREE = k.THREE, pts = zonePts(p);
    if(pts.length < 3) return [];
    /* rotateX(-90°) maps the shape's +Y to world -Z, so a plan point (x, z)
       is written into the shape as (x, -z) and comes back out at (x, ·, z) */
    var sh = new THREE.Shape();
    sh.moveTo(pts[0][0], -pts[0][1]);
    for(var i=1;i<pts.length;i++) sh.lineTo(pts[i][0], -pts[i][1]);
    sh.closePath();
    var h = Math.max(0.005, k.num(p.h, 0.05));
    var g = new THREE.ExtrudeGeometry(sh, {depth:h, bevelEnabled:false});
    g.rotateX(-Math.PI/2);
    g.computeVertexNormals();
    return [{g:g, sub: ZONE_MAT[String(p.use||'').toLowerCase()] || 'mat_glass'}];
  };

  AR_EXT.label.component = 'Component';
  AR_EXT.label.gridline  = 'Grid line';
  AR_EXT.label.zone      = 'Room / zone';

  /* ── labels: canvas sprites kept in step by the ticks hook ──────────── */
  function sprite(text){
    var cv = document.createElement('canvas'), f = 40;
    var ctx = cv.getContext('2d');
    ctx.font = '600 '+f+'px system-ui, "Segoe UI", sans-serif';
    cv.width = Math.max(48, Math.ceil(ctx.measureText(text).width) + 28);
    cv.height = Math.ceil(f*1.55);
    ctx = cv.getContext('2d');
    ctx.font = '600 '+f+'px system-ui, "Segoe UI", sans-serif';
    ctx.fillStyle = 'rgba(9,16,22,0.74)';
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.fillStyle = '#8fe9ff';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, cv.width/2, cv.height/2 + 1);
    var tex = new THREE.CanvasTexture(cv);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({map:tex, transparent:true,
                                                        depthTest:false, depthWrite:false}));
    var mh = 0.62;
    sp.scale.set(mh*cv.width/cv.height, mh, 1);
    sp.renderOrder = 9;
    /* three r144 gives EVERY Sprite the same module-level geometry: letting
       arDisposeNode dispose it would empty every other label in the scene */
    sp.userData.arShared = 1;
    sp.userData.orgLabel = 1;
    sp.userData.orgText = text;
    return sp;
  }
  function labelOf(rec){
    if(rec.kind === 'gridline') return String((rec.p||{}).label || '').trim();
    if(rec.kind === 'zone'){
      var pts = zonePts(rec.p), a = pts.length >= 3 ? shoelace(pts) : 0;
      var nm = String((rec.p||{}).name || rec.name || 'Zone').trim();
      return nm + '  ' + (Math.round(a*100)/100) + ' m\u00b2';
    }
    return '';
  }
  function placeLabel(rec, sp){
    if(rec.kind === 'gridline'){
      sp.position.set(Math.max(0.1, N((rec.p||{}).len, 20))/2 + 0.7, 0.2, 0);
    } else {
      var pts = zonePts(rec.p), cx = 0, cz = 0;
      if(pts.length){
        var xs = pts.map(function(q){ return q[0]; }), zs = pts.map(function(q){ return q[1]; });
        cx = (Math.min.apply(null, xs) + Math.max.apply(null, xs))/2;
        cz = (Math.min.apply(null, zs) + Math.max.apply(null, zs))/2;
      }
      sp.position.set(cx, Math.max(0.005, N((rec.p||{}).h, 0.05)) + 0.35, cz);
    }
  }
  function dropLabel(rec){
    if(!rec.node) return;
    var kids = rec.node.children;
    for(var j=kids.length-1;j>=0;j--){
      var c = kids[j];
      if(!(c.userData && c.userData.orgLabel)) continue;
      rec.node.remove(c);
      if(c.material){ if(c.material.map) c.material.map.dispose(); c.material.dispose(); }
    }
  }
  function labels(){
    if(!window.AR || !AR.objs || !window.THREE) return 0;
    var n = 0, on = labelsOn();
    for(var i=0;i<AR.objs.length;i++){
      var r = AR.objs[i];
      if(r.kind === 'component'){
        /* the studio's Place tool names only pack assets; a component placed
           from the browser would otherwise read "Component" in the outliner */
        var pn = String((r.p||{}).name || '');
        if(pn && (r.name === 'Component' || !r.name)) r.name = pn;
        continue;
      }
      if((r.kind !== 'gridline' && r.kind !== 'zone') || !r.node) continue;
      if(r.kind === 'zone' && !on){ dropLabel(r); continue; }   /* the switch is off */
      var txt = labelOf(r), cur = null, kids = r.node.children;
      for(var j=0;j<kids.length;j++) if(kids[j].userData && kids[j].userData.orgLabel) cur = kids[j];
      if(cur && cur.userData.orgText === txt){ placeLabel(r, cur); n++; continue; }
      if(cur){
        r.node.remove(cur);
        if(cur.material){ if(cur.material.map) cur.material.map.dispose(); cur.material.dispose(); }
      }
      if(!txt) continue;
      var sp = sprite(txt);
      sp.userData.arId = r.id;
      r.node.add(sp);
      placeLabel(r, sp);
      n++;
    }
    return n;
  }
  var tick = 0;
  AR_EXT.ticks.push(function(){ if((tick++ % 12) === 0) labels(); });

  /* ── the component's own maths ──────────────────────────────────────── */
  function originOf(recs){
    var box = new THREE.Box3(), any = false;
    recs.forEach(function(r){ if(r.node){ box.expandByObject(r.node); any = true; } });
    if(!any){
      var xs = recs.map(function(r){ return r.x; }), zs = recs.map(function(r){ return r.z; });
      return {x:(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2, y:Math.min.apply(null, recs.map(function(r){ return r.y; })),
              z:(Math.min.apply(null,zs)+Math.max.apply(null,zs))/2};
    }
    return {x:(box.min.x+box.max.x)/2, y:box.min.y, z:(box.min.z+box.max.z)/2};
  }
  function childOf(rec, o){
    return {kind:rec.kind, p:clone(rec.p || {}),
            x:+(rec.x - o.x).toFixed(4), y:+(rec.y - o.y).toFixed(4), z:+(rec.z - o.z).toFixed(4),
            rx:rec.rx||0, ry:rec.ry||0, rz:rec.rz||0, s:rec.s||1, mat:rec.mat||'mat_concrete'};
  }
  function rebuildAll(name){
    var def = ext().components[name] || [], n = 0;
    instances(name).forEach(function(r){
      r.p.children = clone(def);
      arRebuild(r); arApplyTransform(r); n++;
    });
    labels();
    return n;
  }

  /* ── the public helpers (sheet buttons and other families) ──────────── */
  var API = {
    /* the storey that holds height y, by name ('' when y is below the lowest) */
    storeyAt: function(y){
      var v = N(y, 0), list = ext().storeys, best = '';
      for(var i=0;i<list.length;i++){
        var el = N(list[i].el, 0), h = N(list[i].h, DEF_H);
        if(v >= el - 1e-6 && v < el + h - 1e-6) return String(list[i].name || '');
        if(v >= el - 1e-6) best = String(list[i].name || '');
      }
      return best;
    },
    storeys: function(){ return clone(ext().storeys); },
    components: function(){ return clone(ext().components); },
    labels: labels,
    roomLabels: labelsOn,
    zoneArea: function(rec){ var p = zonePts(rec && rec.p); return p.length >= 3 ? shoelace(p) : 0; },
    zoneLabel: labelOf,
    go: function(name){
      var s = ext().storeys.filter(function(q){ return String(q.name) === String(name); })[0];
      if(!s){ arToast('No storey called <b>'+esc(String(name))+'</b>.', 'warn'); return; }
      arSetLevel(N(s.el, 0));
      arToast('Drawing plane on <b>'+esc(String(s.name))+'</b> at '+arFmt(N(s.el,0))+' m.');
    },
    place: function(name){
      var def = ext().components[name];
      if(!def || !def.length){ arToast('No definition for <b>'+esc(String(name))+'</b>.', 'warn'); return; }
      arSheetClose();
      arTool('place', {kind:'component', p:{name:String(name), children:clone(def)}, n:String(name)});
      arToast('Click to place another <b>'+esc(String(name))+'</b>. Shift-click keeps placing.');
    },
    selectAll: function(name){
      var ids = instances(String(name)).map(function(r){ return r.id; });
      if(!ids.length){ arToast('No instances of <b>'+esc(String(name))+'</b>.', 'warn'); return; }
      arSelect(ids);
      arToast('Selected '+ids.length+' instance'+(ids.length===1?'':'s')+' of <b>'+esc(String(name))+'</b>.');
    },
    explode: function(id){
      var rec = arFind(String(id));
      if(!rec || rec.kind !== 'component'){ arToast('That is not a component.', 'warn'); return 0; }
      var kids = childList(rec.p);
      if(!kids.length){ arToast('That component has no children.', 'warn'); return 0; }
      arPush();
      var co = Math.cos(rec.ry||0), si = Math.sin(rec.ry||0), S = rec.s||1, ids = [];
      kids.forEach(function(c){
        if(!isObj(c) || !c.kind) return;
        var lx = N(c.x,0)*S, ly = N(c.y,0)*S, lz = N(c.z,0)*S;
        var o = arNewObj(String(c.kind), isObj(c.p) ? c.p : {},
                         rec.x + lx*co + lz*si, rec.z - lx*si + lz*co, rec.y + ly);
        o.rx = N(c.rx,0); o.ry = (rec.ry||0) + N(c.ry,0); o.rz = N(c.rz,0);
        o.s = S * (N(c.s,1) || 1);
        if(c.mat) o.mat = String(c.mat);
        o.grp = rec.grp || '';
        arApplyTransform(o); arApplyMat(o);
        ids.push(o.id);
      });
      var nm = String((rec.p||{}).name || rec.name || 'component');
      arRemove(rec);
      arSelect(ids); arSyncHoles(); arPanel(); arOutliner(); labels();
      arToast('Exploded <b>'+esc(nm)+'</b> into '+ids.length+' object'+(ids.length===1?'':'s')+'.');
      return ids.length;
    },
    editDefinition: function(name, fromId){
      var nm = String(name);
      var src = fromId ? arFind(String(fromId)) : instances(nm)[0];
      if(!src || src.kind !== 'component' || String((src.p||{}).name||'') !== nm){
        arToast('Pick an instance of <b>'+esc(nm)+'</b> to take the definition from.', 'warn');
        return 0;
      }
      arPush();
      ext().components[nm] = clone(childList(src.p));
      var n = rebuildAll(nm);
      arPanel(); arOutliner();
      arToast('Definition of <b>'+esc(nm)+'</b> rewritten from '+esc(src.id)+' — '+n+' instance'+(n===1?'':'s')+' rebuilt.');
      return n;
    },
    browse: function(){ return AR_EXT.tools.o_browse.act(); },
    sheetStoreys: function(){ return AR_EXT.tools.o_levels.act(); }
  };
  window.organise_model = API;

  /* ── o_comp — make (or re-define) a component ───────────────────────── */
  AR_EXT.tools.o_comp = {
    assist: 1,
    tip: 'Component — one definition, many instances. Edit it once and every copy in the drawing changes',
    act: function(opt){
      var o = isObj(opt) ? opt : null;
      if(o && o.edit) return API.editDefinition(String(o.edit), o.from);

      var recs = arSelRecs().filter(function(r){ return !r.hidden; });
      if(!recs.length){ arToast('Select the objects to turn into a component first.', 'warn'); return; }
      var name = o ? String(o.name || '') : String(prompt('Name for this component', 'Component 1') || '');
      name = name.trim();
      if(!name){ arToast('A component needs a name.', 'warn'); return; }

      var origin = originOf(recs);
      var kids = recs.map(function(r){ return childOf(r, origin); });
      arPush();
      ext().components[name] = clone(kids);
      recs.forEach(arRemove);
      var rec = arNewObj('component', {name:name, children:clone(kids)}, origin.x, origin.z, origin.y);
      rec.name = name;
      arSelect([rec.id]); arSyncHoles(); arPanel(); arOutliner(); labels();
      arToast('<b>'+esc(name)+'</b> is a component of '+kids.length+' object'+(kids.length===1?'':'s')+
              ' — place more from <b>Components</b>.');
      return rec.id;
    }
  };

  /* ── o_browse — the component browser ───────────────────────────────── */
  AR_EXT.tools.o_browse = {
    assist: 1,
    tip: 'Component browser — every definition in the drawing, with how many instances each has',
    act: function(){
      var e = ext(), names = Object.keys(e.components).sort();
      /* instances of a definition that is not in ext (an old file) still count */
      AR.objs.forEach(function(r){
        var n = r.kind === 'component' ? String((r.p||{}).name||'') : '';
        if(n && names.indexOf(n) < 0){ e.components[n] = clone(childList(r.p)); names.push(n); }
      });
      names.sort();
      if(!names.length){
        arSheet('Components', '<p>No components yet. Select some objects and press '
              + '<b>Make component</b> to turn them into one.</p>');
        return 0;
      }
      var rows = names.map(function(n){
        var inst = instances(n), kids = (e.components[n]||[]).length;
        var q = "'" + n.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'";
        return '<tr><td><b>' + esc(n) + '</b></td>'
             + '<td>' + inst.length + ' instance' + (inst.length===1?'':'s') + '</td>'
             + '<td>' + kids + ' child' + (kids===1?'':'ren') + '</td><td>'
             + btn('organise_model.place('+q+')', 'Place another', 'Arm the Place tool with this component')
             + ' ' + btn('organise_model.selectAll('+q+')', 'Select all', 'Select every instance of this component')
             + (inst.length ? ' ' + btn('organise_model.explode(\''+inst[0].id+'\')', 'Explode',
                                        'Replace the first instance with its children')
                            + ' ' + btn('organise_model.editDefinition('+q+', \''+inst[0].id+'\')', 'Edit definition',
                                        'Take the definition from this instance and rebuild every other one')
                            : '')
             + '</td></tr>';
      });
      arSheet('Components (' + names.length + ')',
              '<table class="ar-tbl"><tr><td><b>name</b></td><td><b>instances</b></td>'
            + '<td><b>children</b></td><td><b>actions</b></td></tr>' + rows.join('') + '</table>'
            + '<p>A definition is shared: <b>Edit definition</b> takes the children of the instance you '
            + 'name and rewrites every other instance from them.</p>');
      return names.length;
    }
  };

  /* ── o_levels — the storey manager ──────────────────────────────────── */
  function storeySheet(){
    var list = ext().storeys;
    var rows = list.map(function(s, i){
      var el = N(s.el, 0), h = N(s.h, DEF_H);
      var q = "'" + String(s.name).replace(/\\/g,'\\\\').replace(/'/g,"\\'") + "'";
      return '<tr><td><b>'+esc(String(s.name))+'</b></td><td>'+arFmt(el)+' m</td><td>'+arFmt(h)+' m</td>'
           + '<td>' + btn('organise_model.go('+q+')', 'go', 'Put the drawing plane on this storey')
           + (i ? ' ' + btn('arTool(\'o_levels\', {action:\'remove\', name:'+q+'})', 'remove', 'Remove this storey') : '')
           + '</td></tr>';
    });
    arSheet('Storeys (' + list.length + ')',
            '<table class="ar-tbl"><tr><td><b>name</b></td><td><b>elevation</b></td><td><b>height</b></td>'
          + '<td><b></b></td></tr>' + rows.join('') + '</table>'
          + '<p><b>go</b> puts the drawing plane on the storey, whatever its height. The dock\'s '
          + '<b>Level up</b> / <b>Level down</b> arrows always step '
          + arFmt((AR.defaults && AR.defaults.wall_h) || DEF_H) + ' m — they are the studio\'s, not this sheet\'s, '
          + 'so a storey of another height is reached from here.</p>');
    return list.length;
  }
  AR_EXT.tools.o_levels = {
    assist: 1,
    tip: 'Storey manager — named levels with heights, so the drawing plane snaps to a floor instead of a number',
    act: function(opt){
      var e = ext(), o = isObj(opt) ? opt : null;
      var a = o ? String(o.action || '') : '';
      if(a === 'add'){
        var last = e.storeys[e.storeys.length-1];
        var h = N(o.height, (AR.defaults && AR.defaults.wall_h) || DEF_H);
        if(!(h > 0.2) || h > 100){ arToast('A storey height must be between 0.2 and 100 m.', 'warn'); return; }
        var el = (o.elevation === undefined || o.elevation === null)
               ? N(last.el, 0) + N(last.h, DEF_H) : N(o.elevation, 0);
        var nm = String(o.name || ('Level ' + e.storeys.length)).trim() || ('Level ' + e.storeys.length);
        if(e.storeys.some(function(s){ return String(s.name) === nm; })){
          arToast('There is already a storey called <b>'+esc(nm)+'</b>.', 'warn'); return;
        }
        arPush();
        e.storeys.push({name:nm, el:+el.toFixed(4), h:+h.toFixed(4)});
        e.storeys.sort(function(p, q){ return N(p.el,0) - N(q.el,0); });
        arToast('Storey <b>'+esc(nm)+'</b> at '+arFmt(el)+' m, '+arFmt(h)+' m high.');
        return storeySheet();
      }
      if(a === 'remove'){
        var nm2 = String(o.name || '');
        if(e.storeys.length < 2){ arToast('The last storey cannot be removed.', 'warn'); return; }
        var before = e.storeys.length;
        arPush();
        e.storeys = e.storeys.filter(function(s){ return String(s.name) !== nm2; });
        if(e.storeys.length === before){ arToast('No storey called <b>'+esc(nm2)+'</b>.', 'warn'); return; }
        arToast('Storey <b>'+esc(nm2)+'</b> removed.');
        return storeySheet();
      }
      if(a === 'set' || a === 'go'){
        if(o.name){ API.go(String(o.name)); return e.storeys.length; }
        arSetLevel(N(o.elevation, 0));
        arToast('Drawing plane at <b>'+arFmt(N(o.elevation,0))+' m</b> ('+esc(API.storeyAt(N(o.elevation,0)) || 'no storey')+').');
        return e.storeys.length;
      }
      return storeySheet();
    }
  };

  /* ── o_gridlines — the structural grid (action) + one extra line (mode) ─ */
  function colIndex(s){
    var c = 0;
    for(var i=0;i<s.length;i++) c = c*26 + (s.charCodeAt(i) - 64);
    return c - 1;
  }
  function cellXZ(nm){
    var m = /^([A-Za-z]+)\s*(\d+)$/.exec(String(nm||'').trim());
    if(!m) return {x:0, z:0};
    var M = (typeof AR_CELL_M === 'number') ? AR_CELL_M : 1;
    var O = (typeof AR_CELL_O === 'number') ? AR_CELL_O : -150;
    return {x: O + (colIndex(m[1].toUpperCase()) + 0.5)*M, z: O + (parseInt(m[2],10) - 0.5)*M};
  }
  function series(spec, dflt){
    var s = String(spec === undefined || spec === null || spec === '' ? dflt : spec).trim();
    var m = /^([A-Za-z]+|\d+)\s*-\s*([A-Za-z]+|\d+)$/.exec(s);
    var out = [];
    if(m){
      var a = m[1], b = m[2];
      if(/^\d+$/.test(a) && /^\d+$/.test(b)){
        for(var i=parseInt(a,10); i<=parseInt(b,10) && out.length<200; i++) out.push(String(i));
      } else {
        for(var c=colIndex(a.toUpperCase()); c<=colIndex(b.toUpperCase()) && out.length<200; c++){
          var t = '', k = c;
          do { t = String.fromCharCode(65 + (k%26)) + t; k = Math.floor(k/26) - 1; } while(k >= 0);
          out.push(t);
        }
      }
      return out;
    }
    s.split(/[,\s]+/).forEach(function(v){ if(v && out.length<200) out.push(v); });
    return out;
  }
  function nextLabel(){
    var n = AR.objs.filter(function(o){ return o.kind === 'gridline'; }).length;
    return 'G' + (n + 1);
  }
  function newGridline(len, label, axis, x, z, ry, grp){
    var r = arNewObj('gridline', {len:+len.toFixed(4), label:String(label), axis:axis}, x, z, AR.level);
    r.ry = ry; r.grp = grp || 'grid'; r.name = 'Grid ' + label;
    arApplyTransform(r);
    return r;
  }
  AR_EXT.tools.o_gridlines = {
    assist: 1,
    tip: 'Structural grid — lettered and numbered lines that columns and walls snap to',
    act: function(opt){
      var o = isObj(opt) ? opt : null;
      if(!o && AR.tool === 'o_gridlines'){ gridDraft = null; arToolApply('select'); return 0; }
      var letters = series(o ? o.letters : prompt('Lettered grid lines (e.g. A-F)', 'A-F'), 'A-F');
      var numbers = series(o ? o.numbers : prompt('Numbered grid lines (e.g. 1-8)', '1-8'), '1-8');
      var dx = N(o ? o.dx : prompt('Spacing of the lettered lines (m)', '6'), 6);
      var dy = N(o ? o.dy : prompt('Spacing of the numbered lines (m)', '6'), 6);
      var org = cellXZ(o ? (o.origin || 'A1') : (prompt('Origin cell of the grid', 'A1') || 'A1'));
      if(!letters.length && !numbers.length){ arToast('A grid needs at least one line.', 'warn'); return 0; }
      if(!(dx > 0.05) || !(dy > 0.05)){ arToast('Grid spacing must be more than 0.05 m.', 'warn'); return 0; }

      var spanX = (letters.length - 1) * dx, spanZ = (numbers.length - 1) * dy;
      var lenLetter = spanZ + dy, lenNumber = spanX + dx;      /* a half-bay past each end */
      arPush();
      var ids = [];
      letters.forEach(function(lb, i){
        /* a lettered line runs along +Z: ry = -PI/2 turns local +X onto +Z */
        ids.push(newGridline(lenLetter, lb, 'z', org.x + i*dx, org.z + spanZ/2, -Math.PI/2).id);
      });
      numbers.forEach(function(lb, j){
        ids.push(newGridline(lenNumber, lb, 'x', org.x + spanX/2, org.z + j*dy, 0).id);
      });
      arSelect(ids); arPanel(); arOutliner(); labels();
      arToolApply('o_gridlines');                              /* armed for extra lines */
      arToast(ids.length + ' grid lines (' + letters.length + ' lettered at ' + arFmt(dx) + ' m, '
            + numbers.length + ' numbered at ' + arFmt(dy) + ' m). Click two points for one more.');
      return ids.length;
    }
  };
  AR_EXT.modes.o_gridlines = {
    click: function(P){
      if(!P) return;
      if(!gridDraft){ gridDraft = {x:P.x, z:P.z}; arHint('Click the far end of the grid line.'); return; }
      var dx = P.x - gridDraft.x, dz = P.z - gridDraft.z, len = Math.hypot(dx, dz);
      if(len < 0.05){ gridDraft = null; AR.rubber.visible = false; return; }
      var lb = String(prompt('Label for this grid line', nextLabel()) || nextLabel()).trim() || nextLabel();
      arPush();
      var r = newGridline(len, lb, Math.abs(dx) >= Math.abs(dz) ? 'x' : 'z',
                          (gridDraft.x + P.x)/2, (gridDraft.z + P.z)/2, Math.atan2(-dz, dx));
      gridDraft = null; AR.rubber.visible = false;
      arSelect([r.id]); arPanel(); arOutliner(); labels();
      arToast('Grid line <b>'+esc(lb)+'</b>, '+arFmt(len)+' m.');
    },
    move: function(P){
      if(!gridDraft || !P){ AR.rubber.visible = false; return; }
      AR.rubber.geometry.setFromPoints([new THREE.Vector3(gridDraft.x, AR.level+0.01, gridDraft.z),
                                        new THREE.Vector3(P.x, AR.level+0.01, P.z)]);
      AR.rubber.visible = true;
      arHint('<b>'+Math.hypot(P.x-gridDraft.x, P.z-gridDraft.z).toFixed(3)+' m</b> — click the far end.');
    },
    hint: function(){
      return gridDraft ? 'Click the far end of the grid line.'
                       : 'Grid lines — click the two ends of one more line. <b>Esc</b> stops.';
    },
    cancel: function(){ gridDraft = null; if(AR.rubber) AR.rubber.visible = false; }
  };

  /* ── grid snap ──────────────────────────────────────────────────────────
     The o_gridlines tooltip promises that columns and walls SNAP to the grid,
     and keeping that promise is this family's job, not another family's.
     precision_snaps builds its candidate index from a CLOSED whitelist of
     kinds (its LINEAR table names wall, partition, beam, guide_line, road,
     path, railing; its CROSSABLE table names wall, partition, guide_line) —
     it has no generic "anything carrying p.len and ry is a segment" reading,
     and those tables are private to its IIFE, so however wall-like a gridline
     record is it never reaches them. Only the bbox CENTRE (pr_cen), which that
     family offers for every record whatever its kind, works on a grid line
     today. So the three classes a grid actually needs — the two ends, the
     centre of the line, and every crossing of two grid lines — are offered
     here, for kind 'gridline' ONLY.
     It behaves like the rest of Precision rather than beside it: each class is
     gated on that family's live switch (pr_end / pr_mid / pr_int), so a user
     who turned endpoint snapping off does not get it back through the side
     door, and it uses that family's radius override when a test or a preset
     set one. When precision_snaps is not loaded at all there are no switches
     to read, and the tooltip is still ours to keep, so ends and crossings are
     offered and midpoints are not.
     The bundle concatenates arch_ext/*.js in ALPHABETICAL order, so this hook
     is registered — and therefore asked — before precision_snaps'. It stands
     aside whenever that family has a candidate of its own strictly nearer to
     the pointer, so a wall corner still beats a grid line under it. */
  var SNAP_SW = {endpoint: 'pr_end', midpoint: 'pr_mid', intersection: 'pr_int'};
  var SNAP_PRIO = ['endpoint', 'intersection', 'midpoint'];
  var snapIdx = null, snapSig = '';

  function gridSig(){
    var n = 0, acc = 0;
    AR.objs.forEach(function(r){
      if(r.kind !== 'gridline') return;
      n++;
      acc += (r.x||0) + (r.z||0) + (r.y||0) + (r.ry||0) + N((r.p||{}).len, 0) + N(r.s, 1)
           + (r.hidden ? 0.25 : 0);
    });
    return n + '|' + Math.round(acc * 1e4) + '|' + (AR.level || 0);
  }
  function gridSegs(){
    var out = [], lvl = AR.level || 0;
    AR.objs.forEach(function(r){
      if(r.kind !== 'gridline' || r.hidden) return;
      if(Math.abs((r.y||0) - lvl) >= DEF_H) return;      /* the drawing plane's band */
      var L = N((r.p||{}).len, 0) * (N(r.s, 1) || 1);
      if(!(L > 1e-6)) return;
      /* a local +X half-length under a rotation of ry about the vertical */
      var ry = r.ry || 0, cs = Math.cos(ry), sn = Math.sin(ry), hx = L/2*cs, hz = -L/2*sn;
      out.push({ax: (r.x||0) - hx, az: (r.z||0) - hz, bx: (r.x||0) + hx, bz: (r.z||0) + hz});
    });
    return out;
  }
  function segCross(p, q){
    var r1 = p.bx - p.ax, r2 = p.bz - p.az, s1 = q.bx - q.ax, s2 = q.bz - q.az;
    var den = r1*s2 - r2*s1;
    if(Math.abs(den) < 1e-12) return null;                /* parallel: no crossing */
    var ox = q.ax - p.ax, oz = q.az - p.az;
    var t = (ox*s2 - oz*s1)/den, u = (ox*r2 - oz*r1)/den;
    if(t < -1e-9 || t > 1+1e-9 || u < -1e-9 || u > 1+1e-9) return null;
    return {x: p.ax + t*r1, z: p.az + t*r2};
  }
  function gridPts(){
    var sg = gridSig();
    if(snapIdx && sg === snapSig) return snapIdx;
    var segs = gridSegs().slice(0, 400), pts = [];
    segs.forEach(function(s){
      pts.push({x:s.ax, z:s.az, t:'endpoint'});
      pts.push({x:s.bx, z:s.bz, t:'endpoint'});
      pts.push({x:(s.ax+s.bx)/2, z:(s.az+s.bz)/2, t:'midpoint'});
    });
    var made = 0;
    for(var i=0; i<segs.length && made<4000; i++)
      for(var j=i+1; j<segs.length && made<4000; j++){
        var q = segCross(segs[i], segs[j]);
        if(q){ pts.push({x:q.x, z:q.z, t:'intersection'}); made++; }
      }
    snapIdx = pts; snapSig = sg;
    return pts;
  }
  function snapOn(t){
    var st = AR.precision_snaps;
    if(!st || !st.on) return t !== 'midpoint';       /* Precision not loaded: our promise stands */
    return !!st.on[SNAP_SW[t]];
  }
  function snapR(){
    var st = AR.precision_snaps;
    if(st && st.radius > 0) return st.radius;        /* the explicit override tests/presets set */
    /* the same 12 screen pixels in metres precision_snaps uses, mirrored because
       its radius() is private; 0.3 m when there is no camera to measure against */
    try{
      var el = AR.renderer && AR.renderer.domElement;
      var h = (el && (el.clientHeight || el.height)) || 900;
      if(AR.ortho && AR.camO) return Math.abs(AR.camO.top - AR.camO.bottom)/(AR.camO.zoom||1)*12/h;
      if(AR.camP){
        var tg = (AR.controls && AR.controls.target) || new THREE.Vector3();
        return 2*AR.camP.position.distanceTo(tg)*Math.tan(AR.camP.fov*Math.PI/360)*12/h;
      }
    }catch(e){}
    return 0.3;
  }
  AR_EXT.snaps.push(function(P){
    try{
      if(!P) return null;
      var R = snapR(), best = null;
      gridPts().forEach(function(q){
        if(!snapOn(q.t)) return;
        var d = Math.hypot(q.x - P.x, q.z - P.z);
        if(d > R) return;
        var pr = SNAP_PRIO.indexOf(q.t);
        if(!best || pr < best.pr || (pr === best.pr && d < best.d))
          best = {pr:pr, d:d, x:q.x, z:q.z, t:q.t};
      });
      if(!best) return null;
      /* stand aside when the Precision family has something nearer of its own */
      if(typeof window.arPrecisionSnapAt === 'function'){
        var o = window.arPrecisionSnapAt(P);
        if(o && Math.hypot(o.x - P.x, o.z - P.z) < best.d - 1e-9) return null;
      }
      return {x: Math.round(best.x*1e6)/1e6, z: Math.round(best.z*1e6)/1e6,
              y: (AR.level || 0), snap: best.t};
    }catch(e){ return null; }
  });

  /* ── o_zones — rooms and zones ──────────────────────────────────────── */
  function makeZone(pts, name, use, h){
    if(pts.length < 3){ arToast('A zone needs at least three points.', 'warn'); return null; }
    var xs = pts.map(function(q){ return q[0]; }), zs = pts.map(function(q){ return q[1]; });
    var cx = (Math.min.apply(null,xs) + Math.max.apply(null,xs))/2;
    var cz = (Math.min.apply(null,zs) + Math.max.apply(null,zs))/2;
    var local = pts.map(function(q){ return [+(q[0]-cx).toFixed(4), +(q[1]-cz).toFixed(4)]; });
    arPush();
    var rec = arNewObj('zone', {pts:local, name:String(name), use:String(use), h:N(h, 0.05)}, cx, cz, AR.level);
    rec.name = String(name); rec.grp = 'zones';
    arSelect([rec.id]); arPanel(); arOutliner(); labels();
    arToast('Zone <b>'+esc(String(name))+'</b> (' + esc(String(use)) + ') — '
          + (Math.round(shoelace(pts)*100)/100) + ' m\u00b2.'
          + (labelsOn() ? '' : ' Room labels are off — <b>Organise ▸ Room labels</b> shows the names.'));
    return rec;
  }
  function finishZone(){
    if(!zoneDraft || zoneDraft.length < 3){ arToast('Click at least three corners first.', 'warn'); return null; }
    var pts = zoneDraft.slice();
    zoneDraft = null; AR.rubber.visible = false;
    var name = String(prompt('Name of this room / zone', 'Room') || 'Room').trim() || 'Room';
    var use = String(prompt('Use (living, bedroom, kitchen, bathroom, circulation, office, retail, storage, plant, outdoor)',
                            'living') || 'living').trim().toLowerCase();
    return makeZone(pts, name, use, 0.05);
  }
  AR_EXT.tools.o_zones = {
    assist: 1,
    tip: 'Rooms and zones — a named enclosed area that carries its own floor area and function',
    act: function(opt){
      var o = isObj(opt) ? opt : null;
      if(o && (Array.isArray(o.pts) || Array.isArray(o.cells))){
        var pts = Array.isArray(o.pts)
          ? o.pts.map(function(q){ return [N(q && q[0], 0), N(q && q[1], 0)]; })
          : o.cells.map(function(c){ var v = cellXZ(c); return [v.x, v.z]; });
        var rec = makeZone(pts, o.name || 'Room', String(o.use || 'living').toLowerCase(), o.h);
        return rec ? rec.id : null;
      }
      if(!o && AR.tool === 'o_zones'){ zoneDraft = null; AR.rubber.visible = false; arToolApply('select'); return 0; }
      zoneDraft = [];
      arToolApply('o_zones');
      arHint('Rooms — click each corner, <b>Enter</b> closes the room. <b>Esc</b> cancels.');
      return 0;
    }
  };
  AR_EXT.modes.o_zones = {
    click: function(P){
      if(!P) return;
      zoneDraft = zoneDraft || [];
      zoneDraft.push([P.x, P.z]);
      arHint(zoneDraft.length + ' corner' + (zoneDraft.length===1?'':'s')
           + (zoneDraft.length >= 3 ? ' — <b>Enter</b> closes the room.' : ' — keep clicking.'));
    },
    move: function(P){
      if(!zoneDraft || !zoneDraft.length || !P){ if(!zoneDraft || !zoneDraft.length) AR.rubber.visible = false; return; }
      var pts = zoneDraft.map(function(q){ return new THREE.Vector3(q[0], AR.level+0.01, q[1]); });
      pts.push(new THREE.Vector3(P.x, AR.level+0.01, P.z));
      if(zoneDraft.length >= 2) pts.push(pts[0].clone());
      AR.rubber.geometry.setFromPoints(pts);
      AR.rubber.visible = true;
    },
    key: function(e){
      if(e.key === 'Enter' && zoneDraft && zoneDraft.length >= 3){ finishZone(); return true; }
      return false;
    },
    hint: function(){
      var n = zoneDraft ? zoneDraft.length : 0;
      return n ? (n + ' corner' + (n===1?'':'s') + (n>=3 ? ' — <b>Enter</b> closes the room.' : ' — keep clicking.'))
               : 'Rooms — click each corner of the room, <b>Enter</b> closes it.';
    },
    cancel: function(){ zoneDraft = null; if(AR.rubber) AR.rubber.visible = false; }
  };

  /* Organise ▸ Room labels — the switch the zone labels follow. Off by default. */
  AR_EXT.tools.o_zone_labels = {
    tog: 1, assist: 1,
    tip: 'Room and apartment names with their floor area, drawn over every room in the viewport &mdash; off until you switch it on',
    on: labelsOn,
    act: function(opt){
      var e = ext(), v = (isObj(opt) && opt.on !== undefined) ? !!opt.on : !e.labels;
      e.labels = v;
      labels();
      var n = AR.objs.filter(function(o){ return o.kind === 'zone' && !o.hidden; }).length;
      arToast(v ? 'Room labels <b>on</b> — ' + n + ' room' + (n===1?'':'s') + ' named in the viewport.'
                : 'Room labels <b>off</b>.');
      return v ? n : 0;
    }
  };

  /* the label pass wants a scene: run it once the engine exists */
  AR_EXT.ready.push(function(){ try{ labels(); }catch(e){} });
})();
