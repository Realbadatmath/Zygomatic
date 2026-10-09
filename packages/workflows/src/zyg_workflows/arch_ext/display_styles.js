// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* display_styles — Architecture Studio ICON family (2026-09-07).
   Wires six Display icons that were placeholders:

     d_tex      Textures on/off
     d_shaded   Shaded (solid faces, materials off)
     d_mono     White model (monochrome)
     d_hidden   Hidden line (the drafting view)
     d_edges    Edge outlines, with a line weight
     d_sketchy  Sketchy edges (hand-drawn line weight)

   All six are SWITCHES (tog + on()). Nothing in inspection.html was edited:
   the face treatments run through AR_EXT.matHooks (which fires on every
   material made AND on every arMatRefresh, so the whole cache is re-styled by
   one call), the line work is per-record overlay Groups parented to rec.node
   so they follow the record's transform, and an AR_EXT.ticks hook keeps those
   overlays honest (rebuild when rec.node was replaced, drop them when the
   record is gone) and re-applies the styles when a loaded drawing brings its
   own settings in.

   STATE lives in the document: AR.doc.ext.display_styles =
     {style:'textured'|'shaded'|'mono'|'hidden', tex:0|1, edges:0|1,
      sketchy:0|1, weight:1|2|3}
   `style` is the one-of-four face treatment (pressing shaded/mono/hidden turns
   the other two off; 'textured' is the plain state). `tex` is Textures within
   the plain state — the other three styles have their maps off by definition,
   so Textures reads off while they are on and pressing it returns to
   'textured'. `edges` and `sketchy` are independent switches; hidden line and
   sketchy both force the edge overlay on.

   LINE WEIGHT, stated plainly: three.js on WebGL draws every line 1 px wide
   whatever `linewidth` says, so weight 2 and 3 draw the SAME outline 2 or 3
   times, each copy nudged 0.006 m x (copy index) in world X and Y. That reads
   as a heavier line at any sane zoom; it is not a true stroke width, and this
   file does not pretend otherwise.

   Sketchy jitter is SEEDED from the record id (a 32-bit FNV/LCG pair below),
   so the wobble is stable across frames and rebuilds instead of shimmering. */
(function(){
  'use strict';

  var DS_GREY = '#9a9a94';        /* shaded: neutral modelling grey            */
  var DS_WHITE = '#f2f2f0';       /* white model                               */
  var DS_EDGE = 0x101216;         /* visible edges                             */
  var DS_HIDDEN = 0x6a6f7a;       /* the dashed lines behind a face            */
  var DS_ANGLE = 30;              /* EdgesGeometry crease angle, degrees       */
  var DS_JITTER = 0.02;           /* sketchy: +/- metres per vertex            */
  var DS_NUDGE = 0.006;           /* weight: metres per extra copy             */

  var dsOver = {};                /* rec.id -> {grp, node, sig}                */
  var dsAnyOver = false;
  var dsSigLast = null;
  var dsBusy = false;

  /* ── state ─────────────────────────────────────────────────────────────── */
  function dsState(){
    if(!window.AR) return {style:'textured', tex:1, edges:0, sketchy:0, weight:1};
    if(!AR.doc || typeof AR.doc !== 'object') AR.doc = {id:'', name:'Untitled drawing', ext:{}};
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    var s = AR.doc.ext.display_styles;
    if(!s || typeof s !== 'object') s = {};
    var style = (s.style === 'shaded' || s.style === 'mono' || s.style === 'hidden') ? s.style : 'textured';
    var w = Math.round(Number(s.weight));
    var out = {
      style: style,
      tex: (s.tex === 0 || s.tex === false) ? 0 : 1,
      edges: (s.edges === 1 || s.edges === true) ? 1 : 0,
      sketchy: (s.sketchy === 1 || s.sketchy === true) ? 1 : 0,
      weight: (w === 2 || w === 3) ? w : 1
    };
    AR.doc.ext.display_styles = out;      /* normalised in place: the signature is stable */
    return out;
  }
  function dsSig(){ var s = dsState(); return s.style+'|'+s.tex+'|'+s.edges+'|'+s.sketchy+'|'+s.weight; }
  function dsMapsOn(s){ return s.style === 'textured' && !!s.tex; }
  function dsEdgesOn(s){ return !!(s.edges || s.sketchy || s.style === 'hidden'); }

  /* ── faces: one material hook does every style ─────────────────────────── */
  function dsOrig(m, def){
    if(!m.userData._dsOrig){
      m.userData._dsOrig = {
        col: m.color ? m.color.clone() : new THREE.Color(0xffffff),
        rough: m.roughness, metal: m.metalness,
        vc: !!m.vertexColors,
        textured: !!(m.map || (def && def.maps && def.maps.map))
      };
      /* the brief's stash: the maps live on the material until a style needs
         them gone, and come back from here — never re-created, never lost */
      m.userData._maps = {map:m.map||null, normalMap:m.normalMap||null,
                          roughnessMap:m.roughnessMap||null, aoMap:m.aoMap||null};
    }
    return m.userData._dsOrig;
  }
  function dsStyleMat(m, def, id){
    if(!m || !m.color || !m.isMaterial) return;
    var o = dsOrig(m, def), maps = m.userData._maps, s = dsState();
    var on = dsMapsOn(s);
    m.color.copy(o.col);
    m.roughness = o.rough; m.metalness = o.metal;
    m.vertexColors = o.vc;
    if(on){
      m.map = maps.map; m.normalMap = maps.normalMap;
      m.roughnessMap = maps.roughnessMap; m.aoMap = maps.aoMap;
    }else{
      m.map = null; m.normalMap = null; m.roughnessMap = null; m.aoMap = null;
      /* a textured preset's base colour is WHITE (it multiplies the
         photograph), so without the map it has to fall back to the preset's
         own flat colour or the surface goes blank white */
      if(o.textured) m.color.set((def && def.col) || DS_GREY);
    }
    if(s.style === 'shaded'){ m.color.set(DS_GREY); m.roughness = 0.85; m.metalness = 0; m.vertexColors = false; }
    else if(s.style === 'mono'){ m.color.set(DS_WHITE); m.roughness = 0.9; m.metalness = 0; m.vertexColors = false; }
    else if(s.style === 'hidden'){ m.color.set('#ffffff'); m.roughness = 1; m.metalness = 0; m.vertexColors = false; }
    if(s.sketchy){                                   /* faces desaturated 30 % */
      var hsl = {h:0, s:0, l:0};
      m.color.getHSL(hsl);
      m.color.setHSL(hsl.h, hsl.s * 0.7, hsl.l);
    }
    /* opacity and transparency are never touched: glass stays glass in every
       style, which is what "white model" means to anyone who has drawn one */
    m.needsUpdate = true;
  }
  AR_EXT.matHooks.push(function(m, def, id){ try{ dsStyleMat(m, def, id); }catch(e){} });

  /* ── lines: a seeded wobble so sketchy does not shimmer ────────────────── */
  function dsHash(str){
    var h = 2166136261, i;
    for(i = 0; i < str.length; i++){ h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function dsRandom(seed){
    var st = seed >>> 0;
    return function(){ st = (Math.imul(st, 1664525) + 1013904223) >>> 0; return st / 4294967296; };
  }
  function dsJitter(geom, seed){
    var g = geom.clone(), pos = g.attributes.position, rnd = dsRandom(seed), i;
    for(i = 0; i < pos.count; i++){
      pos.setXYZ(i,
        pos.getX(i) + (rnd() - 0.5) * 2 * DS_JITTER,
        pos.getY(i) + (rnd() - 0.5) * 2 * DS_JITTER,
        pos.getZ(i) + (rnd() - 0.5) * 2 * DS_JITTER);
    }
    pos.needsUpdate = true;
    return g;
  }
  function dsMeshes(rec){
    var out = [];
    rec.node.traverse(function(o){
      if(!o.isMesh) return;                       /* LineSegments and Sprites excluded */
      if(o.userData && o.userData.dsOverlay) return;
      if(!o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      out.push(o);
    });
    return out;
  }
  function dsBuildOverlay(rec){
    var s = dsState(), grp = new THREE.Group();
    grp.name = 'ds-edges';
    grp.userData.dsOverlay = 1;
    rec.node.updateMatrixWorld(true);
    var inv = new THREE.Matrix4().copy(rec.node.matrixWorld).invert();
    var seed = dsHash(String(rec.id)), copies = s.sketchy ? 2 : s.weight, i;
    dsMeshes(rec).forEach(function(mesh, mi){
      var eg;
      try{ eg = new THREE.EdgesGeometry(mesh.geometry, DS_ANGLE); }catch(e){ return; }
      if(!eg.attributes || !eg.attributes.position || !eg.attributes.position.count){ eg.dispose(); return; }
      mesh.updateMatrixWorld(true);
      eg.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, mesh.matrixWorld));
      if(s.style === 'hidden'){
        /* the drafting view: what a face hides is drawn DASHED and without a
           depth test, so it shows through the solid it is behind; the visible
           edges are the depth-tested pass drawn on top of it */
        var dg = eg.clone();
        var dl = new THREE.LineSegments(dg, new THREE.LineDashedMaterial({
          color: DS_HIDDEN, depthTest: false, transparent: true, opacity: 0.9,
          dashSize: 0.15, gapSize: 0.1
        }));
        dl.computeLineDistances();
        dl.renderOrder = 1;
        dl.userData.dsOverlay = 1;
        grp.add(dl);
      }
      for(i = 0; i < copies; i++){
        var g = s.sketchy ? dsJitter(eg, (seed + mi * 7919 + i * 104729) >>> 0) : (i ? eg.clone() : eg);
        var mat = new THREE.LineBasicMaterial({
          color: DS_EDGE, depthTest: true,
          transparent: !!s.sketchy, opacity: s.sketchy ? 0.6 : 1
        });
        var ln = new THREE.LineSegments(g, mat);
        if(!s.sketchy && i) ln.position.set(DS_NUDGE * i, DS_NUDGE * i, 0);
        ln.renderOrder = 2;
        ln.userData.dsOverlay = 1;
        grp.add(ln);
      }
      if(s.sketchy) eg.dispose();
    });
    rec.node.add(grp);
    return grp;
  }
  function dsDrop(id){
    var e = dsOver[id];
    if(!e) return;
    if(e.grp){
      if(e.grp.parent) e.grp.parent.remove(e.grp);
      e.grp.traverse(function(o){
        if(o.geometry) o.geometry.dispose();
        if(o.material && o.material.dispose) o.material.dispose();
      });
    }
    delete dsOver[id];
  }
  function dsClearOverlays(){
    Object.keys(dsOver).forEach(dsDrop);
    dsAnyOver = false;
  }
  function dsSyncOverlays(){
    var s = dsState();
    if(!window.AR || !AR.objs) return;
    if(!dsEdgesOn(s)){ if(dsAnyOver) dsClearOverlays(); return; }
    var sig = dsSig(), live = {}, i, rec, e;
    for(i = 0; i < AR.objs.length; i++){
      rec = AR.objs[i];
      if(!rec.node) continue;
      live[rec.id] = 1;
      e = dsOver[rec.id];
      /* the cheap comparison the brief asks for: a rebuilt record has a NEW
         node object, so identity alone says "your overlay is stale" */
      if(e && e.node === rec.node && e.sig === sig && e.grp.parent === rec.node) continue;
      dsDrop(rec.id);
      dsOver[rec.id] = {grp: dsBuildOverlay(rec), node: rec.node, sig: sig};
    }
    Object.keys(dsOver).forEach(function(id){ if(!live[id]) dsDrop(id); });
    dsAnyOver = true;
  }

  /* ── apply: faces through the cache, then the line work ────────────────── */
  function dsApply(){
    if(dsBusy) return;
    dsBusy = true;
    try{
      dsSigLast = dsSig();
      if(window.arMatRefresh) arMatRefresh();     /* every cached material back through the hook */
      dsSyncOverlays();
      if(window.arToolsRender) arToolsRender();
    }finally{ dsBusy = false; }
  }
  function dsSet(patch){
    var s = dsState(), k;
    for(k in patch) if(Object.prototype.hasOwnProperty.call(patch, k)) s[k] = patch[k];
    AR.doc.ext.display_styles = s;
    dsState();
    dsApply();
    if(window.arDirty && !AR._quiet) arDirty(true);   /* a display style is part of the drawing */
  }
  function dsWant(opt, cur){
    /* an assistant press carries {on:true|false}; a person's click toggles */
    if(opt && typeof opt === 'object' && opt.on !== undefined) return !!opt.on;
    return !cur;
  }
  /* Turning the outlines off has to mean it. Sketchy is only lines, so it goes
     with them; hidden line cannot exist without them, so that one is refused
     out loud rather than silently ignored. */
  function dsEdgesOff(s){
    if(s.style === 'hidden'){
      if(window.arToast) arToast('Hidden line <b>is</b> the outlines — turn Hidden line off first.', 'warn');
      return;
    }
    dsSet({edges: 0, sketchy: 0});
  }
  function dsStyleSwitch(name){
    return {
      tog: 1, assist: 1,
      on: function(){ return dsState().style === name; },
      act: function(opt){
        var want = dsWant(opt, dsState().style === name);
        dsSet({style: want ? name : 'textured', tex: want ? 0 : 1});
      }
    };
  }

  AR_EXT.tools.d_tex = Object.assign(dsStyleSwitch('textured'), {
    tip: 'Textures on/off — draw the surfaces with their CC0 photographs, or with the preset\u2019s flat colour',
    on: function(){ var s = dsState(); return s.style === 'textured' && !!s.tex; },
    act: function(opt){
      var s = dsState(), want = dsWant(opt, s.style === 'textured' && !!s.tex);
      /* turning textures back ON is also the way home from shaded/mono/hidden,
         all three of which are map-less by definition */
      dsSet(want ? {style: 'textured', tex: 1} : {tex: 0, style: s.style});
    }
  });
  AR_EXT.tools.d_shaded = Object.assign(dsStyleSwitch('shaded'), {
    tip: 'Shaded — solid faces in a neutral grey, materials and textures off. The plain modelling view'
  });
  AR_EXT.tools.d_mono = Object.assign(dsStyleSwitch('mono'), {
    tip: 'White model — every surface off-white, so the form reads without the materials arguing (glass stays glass)'
  });
  AR_EXT.tools.d_hidden = {
    tog: 1, assist: 1,
    tip: 'Hidden line — white faces with black outlines and the edges behind them dashed. The drafting view',
    on: function(){ return dsState().style === 'hidden'; },
    act: function(opt){
      var want = dsWant(opt, dsState().style === 'hidden');
      /* the drafting view IS its line work: hidden line forces the outlines on */
      dsSet(want ? {style: 'hidden', tex: 0, edges: 1} : {style: 'textured', tex: 1});
    }
  };
  AR_EXT.tools.d_edges = {
    tog: 1, assist: 1,
    tip: 'Edge outlines — profile lines around each solid; weight 1\u20133 (WebGL draws 1 px lines, so 2 and 3 are the outline drawn twice or three times, nudged)',
    on: function(){ return dsEdgesOn(dsState()); },
    act: function(opt){
      var s = dsState();
      if(opt && typeof opt === 'object'){
        var w = Math.round(Number(opt.weight));
        var want = (opt.on !== undefined) ? !!opt.on : true;
        var wt = (w === 2 || w === 3) ? w : (w === 1 ? 1 : s.weight);
        if(want) dsSet({edges: 1, weight: wt});
        else { dsSet({weight: wt}); dsEdgesOff(dsState()); }
        return;
      }
      if(dsEdgesOn(s)){ dsEdgesOff(s); return; }
      var a = prompt('Edge weight — 1, 2 or 3 (0 leaves the outlines off)', String(s.weight));
      if(a === null) return;
      var n = Math.round(Number(a));
      if(!n){ dsSet({edges: 0}); return; }
      dsSet({edges: 1, weight: (n === 2 || n === 3) ? n : 1});
    }
  };
  AR_EXT.tools.d_sketchy = {
    tog: 1, assist: 1,
    tip: 'Sketchy edges — the outlines drawn twice with a hand-drawn wobble and the faces desaturated, for a drawing that should not look decided yet',
    on: function(){ return !!dsState().sketchy; },
    act: function(opt){
      var want = dsWant(opt, !!dsState().sketchy);
      /* a sketch without its lines is just a washed-out render */
      dsSet(want ? {sketchy: 1, edges: 1} : {sketchy: 0});
    }
  };

  AR_EXT.ticks.push(function(){
    try{
      if(!window.AR || !AR.built) return;
      var sig = dsSig();
      if(sig !== dsSigLast){ dsApply(); return; }   /* a loaded drawing brought its own settings */
      dsSyncOverlays();
    }catch(e){}
  });
  AR_EXT.ready.push(function(){
    try{ dsSigLast = null; dsApply(); }catch(e){}
  });

  /* two family-prefixed globals, for the test and for the console */
  window.arDisplayStyles = function(){ return dsState(); };
  window.arDisplayStylesOverlays = function(){ return Object.keys(dsOver); };
})();
