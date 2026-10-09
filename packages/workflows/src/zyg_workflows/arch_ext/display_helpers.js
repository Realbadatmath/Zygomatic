// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* display_helpers — six Display-section icons, wired for real (2026-09-07).

     d_bbox      Bounds        switch  — a Box3Helper per visible record
     d_ground    Ground        switch  — the shadow-catching plane, independent of t_sun
     d_labels    Labels        switch  — a name pill sprite per visible record (cap 400)
     d_colorby   Colour by     cycle   — off / material / storey / kind / tag
     d_transp    Glass         cycle   — fast / sorted / dithered
     d_backface  Normals       cycle   — double / cull / normals

   Nothing in inspection.html was edited. State is per DRAWING, in
   AR.doc.ext.display_helpers, so it is saved with the file and round-trips
   through the assistant. The three "live" helpers (boxes, labels, normals) are
   THREE objects on AR.scene keyed by record id, kept in step by ONE
   AR_EXT.ticks hook; the two material cycles ride AR_EXT.matHooks so every
   material the studio makes or refreshes gets the current mode, including the
   ones made after the switch was thrown.

   Only the tab's own globals are used (AR, arToast, arMatRefresh, arApplyMat,
   arMatRGB, arSelRecs, arKindLabel, esc). No new libraries. */
(function () {
  'use strict';

  var FAMILY = 'display_helpers';
  var DEF = {bbox: false, ground: null, labels: false, colorby: 'off', transp: 'fast', backface: 'double'};
  var CB_ORDER = ['off', 'material', 'storey', 'kind', 'tag'];
  var TQ_ORDER = ['fast', 'sorted', 'dithered'];
  var BF_ORDER = ['double', 'cull', 'normals'];
  var TQ_NOTE = {
    fast: 'no depth sorting, glass writes depth. Cheapest, and what is behind the glass may be wrong.',
    sorted: 'back-to-front sorting, glass does not write depth. The honest look.',
    dithered: 'a screen-door cut-out instead of blending — order-independent, and it never sorts wrong.'
  };
  var SEL_COL = 0xffb020, REST_COL = 0x4a5060;
  var STOREY_RAMP = [0x4f8ef7, 0x37b36b, 0xf2b134, 0xe0603a, 0x9a6ae0, 0x2fb8b0];
  var LABEL_CAP = 400;
  /* sizeAttenuation is FALSE, so this scale is screen-relative (NDC-ish), not
     metres: a name has to stay readable when you zoom out to the whole site,
     which a 0.3 m billboard does not. 0.055 is about 2.5 % of the viewport
     height per line — the same weight as the HUD text. */
  var LABEL_H = 0.055;
  var NORMAL_LEN = 0.3;

  /* ── state ──────────────────────────────────────────────────────────────
     `ground: null` means "not decided here" — the plane then follows t_sun as
     it always did. The moment someone presses the icon the value becomes true
     or false and the tick hook re-asserts it every frame, which is how this
     switch overrides the shadow switch's coupling without editing arTool.

     st() READS and never writes: a drawing nobody has pressed these icons on
     must come back out of arDocOut() byte-identical, so the defaults are not
     stamped into AR.doc.ext until someone actually changes one (stw()). */
  function st() {
    if (!window.AR || !AR.doc) return null;
    var s = AR.doc.ext && AR.doc.ext[FAMILY];
    if (!s || typeof s !== 'object') return DEF;      /* shared, read-only */
    for (var k in DEF) if (!(k in s)) s[k] = DEF[k];
    return s;
  }
  function stw() {
    if (!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    var s = AR.doc.ext[FAMILY];
    if (!s || typeof s !== 'object') { s = AR.doc.ext[FAMILY] = {}; }
    for (var k in DEF) if (!(k in s)) s[k] = DEF[k];
    return s;
  }
  function want(opt, field, cur) {
    if (opt && typeof opt === 'object' && opt[field] !== undefined) return !!opt[field];
    return !cur;
  }
  function pick(opt, field, order, cur) {
    if (opt && typeof opt === 'object' && opt[field] !== undefined) return String(opt[field]);
    var i = order.indexOf(cur);
    return order[(i < 0 ? 0 : i + 1) % order.length];
  }

  /* ── d_bbox: one Box3Helper per visible record ──────────────────────────
     Box3Helper is a unit cube whose updateMatrixWorld reads .box, so a box
     that is refitted is drawn refitted with no geometry rewrite. The
     selection is refitted EVERY frame (it is the one being dragged); the rest
     is fitted once, when its helper is made or its node was rebuilt. */
  var boxes = {};
  function boxDrop(id) {
    var h = boxes[id];
    if (!h) return;
    AR.scene.remove(h);
    if (h.geometry) h.geometry.dispose();
    if (h.material) h.material.dispose();
    delete boxes[id];
  }
  function boxClear() { for (var id in boxes) boxDrop(id); }
  function boxTick(s) {
    if (!s.bbox) { boxClear(); return; }
    var seen = {}, i, r, h, sel;
    for (i = 0; i < AR.objs.length; i++) {
      r = AR.objs[i];
      if (!r.node || r.hidden) continue;
      seen[r.id] = 1;
      sel = AR.sel.indexOf(r.id) >= 0;
      h = boxes[r.id];
      if (h && h.userData.dhNode !== r.node) { boxDrop(r.id); h = null; }
      if (!h) {
        h = new THREE.Box3Helper(new THREE.Box3(), sel ? SEL_COL : REST_COL);
        h.userData.dh = 1; h.userData.dhNode = r.node; h.userData.dhFit = 0;
        h.material.depthTest = false; h.material.transparent = true; h.renderOrder = 998;
        AR.scene.add(h); boxes[r.id] = h;
      }
      if (sel || !h.userData.dhFit) { h.box.setFromObject(r.node); h.userData.dhFit = 1; }
      h.material.color.setHex(sel ? SEL_COL : REST_COL);
    }
    for (var id in boxes) if (!seen[id]) boxDrop(id);
  }

  /* ── d_ground ───────────────────────────────────────────────────────── */
  function groundOn() {
    var s = st();
    if (!s) return false;
    if (s.ground === null || s.ground === undefined) return !!(AR.ground && AR.ground.visible);
    return !!s.ground;
  }
  function groundTick(s) {
    if (s.ground === null || s.ground === undefined) return;   /* still t_sun's business */
    if (AR.ground && AR.ground.visible !== !!s.ground) AR.ground.visible = !!s.ground;
  }

  /* ── d_labels: a canvas pill per record ─────────────────────────────── */
  var labels = {};
  function labelTex(text) {
    var c = document.createElement('canvas'), pad = 18, fs = 40, font = '600 ' + fs + 'px system-ui, sans-serif';
    var g = c.getContext('2d');
    g.font = font;
    c.width = Math.max(48, Math.ceil(g.measureText(text).width) + pad * 2);
    c.height = fs + pad;
    g = c.getContext('2d');
    g.font = font; g.textBaseline = 'middle';
    var rr = c.height / 2;
    g.beginPath();
    g.moveTo(rr, 0); g.lineTo(c.width - rr, 0);
    g.arc(c.width - rr, rr, rr, -Math.PI / 2, Math.PI / 2);
    g.lineTo(rr, c.height);
    g.arc(rr, rr, rr, Math.PI / 2, -Math.PI / 2);
    g.closePath();
    g.fillStyle = 'rgba(12,16,22,0.84)'; g.fill();
    g.strokeStyle = 'rgba(0,229,255,0.55)'; g.lineWidth = 2.5; g.stroke();
    g.fillStyle = '#e8eef5'; g.fillText(text, pad, c.height / 2 + 1);
    var t = new THREE.CanvasTexture(c);
    t.needsUpdate = true;
    return {tex: t, aspect: c.width / c.height};
  }
  function labelDrop(id) {
    var sp = labels[id];
    if (!sp) return;
    AR.scene.remove(sp);
    if (sp.material) { if (sp.material.map) sp.material.map.dispose(); sp.material.dispose(); }
    delete labels[id];
  }
  function labelClear() { for (var id in labels) labelDrop(id); }
  var _labelBox = null, _labelC = null;
  function labelTick(s) {
    if (!s.labels) { labelClear(); return; }
    if (!_labelBox) { _labelBox = new THREE.Box3(); _labelC = new THREE.Vector3(); }
    var seen = {}, n = 0, over = 0, i, r, sp, txt;
    for (i = 0; i < AR.objs.length; i++) {
      r = AR.objs[i];
      if (!r.node || r.hidden) continue;
      if (n >= LABEL_CAP) { over++; continue; }
      n++; seen[r.id] = 1;
      txt = String(r.name || arKindLabel(r.kind) || r.id).slice(0, 42);
      sp = labels[r.id];
      if (sp && sp.userData.dhText !== txt) { labelDrop(r.id); sp = null; }
      if (!sp) {
        var t = labelTex(txt);
        sp = new THREE.Sprite(new THREE.SpriteMaterial({map: t.tex, transparent: true, depthTest: false, sizeAttenuation: false}));
        sp.scale.set(LABEL_H * t.aspect, LABEL_H, 1);
        sp.renderOrder = 1000; sp.userData.dh = 1; sp.userData.dhText = txt;
        AR.scene.add(sp); labels[r.id] = sp;
      }
      _labelBox.setFromObject(r.node);
      if (_labelBox.isEmpty()) sp.position.set(r.x, (r.y || 0) + 0.25, r.z);
      else { _labelBox.getCenter(_labelC); sp.position.set(_labelC.x, _labelBox.max.y + 0.2, _labelC.z); }
    }
    for (var id in labels) if (!seen[id]) labelDrop(id);
    if (over && !AR._dhLabelToast) {
      AR._dhLabelToast = 1;
      arToast('Labels: the first ' + LABEL_CAP + ' objects are named — ' + over + ' more are left off so the viewport stays readable.', 'warn');
    }
    if (!over) AR._dhLabelToast = 0;
  }

  /* ── d_colorby ───────────────────────────────────────────────────────── */
  var colMats = {};
  function colMat(hex) {
    if (!colMats[hex]) {
      var m = new THREE.MeshStandardMaterial({color: hex, roughness: 0.85, metalness: 0.0, side: THREE.DoubleSide});
      m.userData.dhCol = 1;
      colMats[hex] = m;
      sideOne(m);
    }
    return colMats[hex];
  }
  function hashHex(str) {
    var h = 0;
    for (var i = 0; i < str.length; i++) h = (h * 131 + str.charCodeAt(i)) >>> 0;
    return new THREE.Color().setHSL((h % 360) / 360, 0.55, 0.56).getHex();
  }
  function colKey(r, by) {
    if (by === 'material') {
      var rgb = arMatRGB(r.mat), c = new THREE.Color();
      c.setRGB(rgb[0], rgb[1], rgb[2]);
      var d = AR.matDefs[r.mat];
      return {hex: c.getHex(), lb: (d && d.n) || String(r.mat || '').replace('mat_', '').replace(/_/g, ' ')};
    }
    if (by === 'storey') {
      var k = Math.round((r.y || 0) / (AR.defaults.wall_h || 2.7));
      return {hex: STOREY_RAMP[((k % STOREY_RAMP.length) + STOREY_RAMP.length) % STOREY_RAMP.length], lb: 'Storey ' + k};
    }
    if (by === 'kind') return {hex: hashHex(String(r.kind)), lb: arKindLabel(r.kind)};
    if (by === 'tag') {
      var t = (r.meta && r.meta.tags && r.meta.tags.length) ? String(r.meta.tags[0]) : '';
      return t ? {hex: hashHex(t), lb: t} : {hex: 0x808080, lb: 'untagged'};
    }
    return null;
  }
  function colApply(r, by) {
    var k = colKey(r, by);
    if (!k || !r.node) return;
    var m = colMat(k.hex);
    r.node.traverse(function (o) {
      if (!o.isMesh) return;
      if (o.userData.dhOrig === undefined) o.userData.dhOrig = o.material;
      o.material = m;
    });
    r._dhBy = by; r._dhNode = r.node;
  }
  function colRestore(r) {
    if (r.node) {
      r.node.traverse(function (o) {
        if (!o.isMesh) return;
        if (o.userData.dhOrig !== undefined) { o.material = o.userData.dhOrig; delete o.userData.dhOrig; }
      });
      /* the belt to that brace: whatever the node is now, the record's own
         preset is what a restored mesh must be wearing */
      arApplyMat(r);
    }
    r._dhBy = null; r._dhNode = null;
  }
  function colOff() {
    if (!AR._dhColOn) return;
    AR.objs.forEach(colRestore);
    AR._dhColOn = 0;
    legend(null);
  }
  function colTick(s) {
    var by = s.colorby || 'off';
    if (by === 'off') { colOff(); return; }
    AR._dhColOn = 1;
    for (var i = 0; i < AR.objs.length; i++) {
      var r = AR.objs[i];
      if (!r.node) continue;
      /* a rebuild (arRebuild / arGroundRefresh / an injection) makes a NEW
         node whose meshes wear the preset again — re-applied here */
      if (r._dhBy !== by || r._dhNode !== r.node) colApply(r, by);
    }
    legend(by);
  }
  var _legendKey = '';
  function legend(by) {
    var el = document.getElementById('ar-dh-legend');
    if (!by) {
      _legendKey = '';
      if (el && el.parentNode) el.parentNode.removeChild(el);
      return;
    }
    var seen = {}, rows = [], key = by + '#' + AR.objs.length;
    AR.objs.forEach(function (r) { key += '|' + r.mat + ':' + r.kind + ':' + r.y + ':' + (r.hidden ? 1 : 0); });
    if (key === _legendKey && el) return;
    _legendKey = key;
    AR.objs.forEach(function (r) {
      if (r.hidden) return;
      var k = colKey(r, by);
      if (!k) return;
      var kk = k.hex + '|' + k.lb;
      if (seen[kk]) return;
      seen[kk] = 1;
      rows.push('<div><i style="display:inline-block;width:10px;height:10px;border-radius:2px;'
        + 'margin-right:6px;background:#' + ('000000' + k.hex.toString(16)).slice(-6) + '"></i>' + esc(k.lb) + '</div>');
    });
    if (!el) {
      var host = document.getElementById('ar-stage');
      if (!host) return;
      el = document.createElement('div');
      el.id = 'ar-dh-legend';
      el.style.cssText = 'position:absolute;left:10px;bottom:10px;z-index:6;pointer-events:none;'
        + 'background:rgba(12,16,22,.84);border:1px solid rgba(0,229,255,.25);border-radius:8px;'
        + 'padding:7px 10px;font:11px/1.6 system-ui,sans-serif;color:#cfe0ef;max-height:42%;overflow:hidden';
      host.appendChild(el);
    }
    el.innerHTML = '<b style="color:#8fd8ea">Colour by ' + esc(by) + '</b>' + rows.slice(0, 24).join('')
      + (rows.length > 24 ? '<div style="opacity:.6">+' + (rows.length - 24) + ' more</div>' : '');
  }

  /* ── d_transp: the material hook ─────────────────────────────────────────
     r144 has no alphaHash, so "dithered" is the classic screen door: an 8x8
     checkerboard alphaMap and alphaTest 0.5 turn a 50 % surface into holes
     that need no sorting at all. Only presets that ARE see-through (op < 1)
     are touched — a foliage cut-out's own alphaTest is not ours to move. */
  var CHECK = null;
  function checker() {
    if (CHECK) return CHECK;
    var c = document.createElement('canvas');
    c.width = c.height = 8;
    var g = c.getContext('2d');
    for (var y = 0; y < 8; y++) for (var x = 0; x < 8; x++) {
      g.fillStyle = ((x + y) % 2) ? '#ffffff' : '#000000';
      g.fillRect(x, y, 1, 1);
    }
    CHECK = new THREE.CanvasTexture(c);
    CHECK.magFilter = THREE.NearestFilter;
    CHECK.minFilter = THREE.NearestFilter;
    CHECK.wrapS = CHECK.wrapT = THREE.RepeatWrapping;
    CHECK.repeat.set(96, 96);
    CHECK.needsUpdate = true;
    return CHECK;
  }
  function transpOne(m, def) {
    var s = st();
    if (!s) return;
    var op = (def && def.op !== undefined && def.op !== null) ? Number(def.op) : 1;
    if (!(op < 1)) return;
    var mode = s.transp || 'fast';
    if (mode === 'dithered') {
      m.alphaMap = checker();
      m.alphaTest = 0.5;
      m.transparent = false;
      m.depthWrite = true;
      m.opacity = 1;
    } else {
      if (m.alphaMap === CHECK) m.alphaMap = null;
      m.alphaTest = 0;
      m.transparent = true;
      m.opacity = op;
      m.depthWrite = (mode === 'fast');
    }
    m.needsUpdate = true;
  }

  /* ── d_backface ─────────────────────────────────────────────────────── */
  function sideOne(m) {
    var s = st();
    if (!s) return;
    m.side = (s.backface === 'cull') ? THREE.FrontSide : THREE.DoubleSide;
    m.needsUpdate = true;
  }
  var normObj = null;
  function normClear() {
    if (!normObj) return;
    AR.scene.remove(normObj);
    normObj.geometry.dispose();
    normObj.material.dispose();
    normObj = null;
  }
  function normBuild() {
    normClear();
    var pts = [];
    var a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    var cb = new THREE.Vector3(), ab = new THREE.Vector3(), n = new THREE.Vector3();
    arSelRecs().forEach(function (r) {
      if (!r.node || r.hidden) return;
      r.node.updateMatrixWorld(true);
      r.node.traverse(function (o) {
        if (!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
        var g = o.geometry, pos = g.attributes.position, idx = g.index;
        var count = idx ? idx.count : pos.count, i, i0, i1, i2, cx, cy, cz;
        for (i = 0; i + 2 < count; i += 3) {
          i0 = idx ? idx.getX(i) : i; i1 = idx ? idx.getX(i + 1) : i + 1; i2 = idx ? idx.getX(i + 2) : i + 2;
          a.fromBufferAttribute(pos, i0).applyMatrix4(o.matrixWorld);
          b.fromBufferAttribute(pos, i1).applyMatrix4(o.matrixWorld);
          c.fromBufferAttribute(pos, i2).applyMatrix4(o.matrixWorld);
          cb.subVectors(c, b); ab.subVectors(a, b);
          n.crossVectors(cb, ab);
          if (n.lengthSq() < 1e-14) n.set(0, 1, 0); else n.normalize();
          cx = (a.x + b.x + c.x) / 3; cy = (a.y + b.y + c.y) / 3; cz = (a.z + b.z + c.z) / 3;
          pts.push(cx, cy, cz, cx + n.x * NORMAL_LEN, cy + n.y * NORMAL_LEN, cz + n.z * NORMAL_LEN);
        }
      });
    });
    if (!pts.length) return;
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    normObj = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({color: 0x00e5ff, depthTest: false, transparent: true, opacity: 0.9}));
    normObj.renderOrder = 1001;
    normObj.userData.dh = 1;
    AR.scene.add(normObj);
  }
  function normTick(s) {
    if (s.backface !== 'normals') { normClear(); AR._dhNormKey = ''; return; }
    var key = AR.sel.join(',') + '#' + arSelRecs().map(function (r) { return r.node ? r.node.id : 0; }).join(',');
    if (key !== AR._dhNormKey) { AR._dhNormKey = key; normBuild(); }
  }

  /* every material the studio makes or refreshes gets both material cycles */
  AR_EXT.matHooks.push(function (m, def) {
    transpOne(m, def);
    sideOne(m);
  });
  function refreshMats() {
    var s = st();
    if (AR.renderer) AR.renderer.sortObjects = (s.transp !== 'fast');
    arMatRefresh();
    for (var hex in colMats) sideOne(colMats[hex]);   /* the colour-by overrides are materials too */
  }

  /* ── the one frame hook ─────────────────────────────────────────────── */
  AR_EXT.ticks.push(function () {
    var s = st();
    if (!s || !AR.scene) return;
    boxTick(s);
    groundTick(s);
    labelTick(s);
    colTick(s);
    normTick(s);
  });

  AR_EXT.ready.push(function () {
    refreshMats();
    var s = st();
    if (s && (s.ground === true || s.ground === false) && AR.ground) AR.ground.visible = !!s.ground;
  });

  /* what the test (and a curious operator) can read without a screenshot */
  window.display_helpers_info = function () {
    var s = st() || {}, cnt = 0, id;
    for (id in boxes) cnt++;
    var ln = 0;
    for (id in labels) ln++;
    return {
      state: JSON.parse(JSON.stringify(s)),
      boxes: cnt,
      box_colors: Object.keys(boxes).map(function (k) { return '#' + ('000000' + boxes[k].material.color.getHex().toString(16)).slice(-6); }),
      labels: ln,
      normal_verts: normObj ? normObj.geometry.attributes.position.count : 0,
      legend: !!document.getElementById('ar-dh-legend'),
      ground_visible: !!(AR.ground && AR.ground.visible),
      sort_objects: !!(AR.renderer && AR.renderer.sortObjects)
    };
  };

  /* ── the six registrations ──────────────────────────────────────────── */
  AR_EXT.tools.d_bbox = {
    tog: 1, assist: 1,
    tip: 'Bounding boxes &mdash; draw each object&rsquo;s extents, which is how you find the one that is 40 m wide. Amber round the selection, grey round the rest',
    on: function () { var s = st(); return !!(s && s.bbox); },
    act: function (opt) {
      var s = stw();
      s.bbox = want(opt, 'on', s.bbox);
      arToast('Bounding boxes <b>' + (s.bbox ? 'on' : 'off') + '</b>' + (s.bbox ? ' — amber is the selection.' : '.'));
    }
  };

  AR_EXT.tools.d_ground = {
    tog: 1, assist: 1,
    tip: 'Ground plane on/off &mdash; the surface the shadows land on. Overrides the Shadows switch: off here stays off',
    on: groundOn,
    act: function (opt) {
      var s = stw(), v = want(opt, 'on', groundOn());
      s.ground = v;
      if (AR.ground) AR.ground.visible = v;
      arToast('Ground plane <b>' + (v ? 'on' : 'off') + '</b>'
        + (v && !AR.shadows ? ' — turn Shadows on to see anything land on it.' : '.'));
    }
  };

  AR_EXT.tools.d_labels = {
    tog: 1, assist: 1,
    tip: 'Object name labels drawn in the viewport &mdash; a pill over each object, the first ' + LABEL_CAP + ' of them',
    on: function () { var s = st(); return !!(s && s.labels); },
    act: function (opt) {
      var s = stw();
      s.labels = want(opt, 'on', s.labels);
      if (!s.labels) AR._dhLabelToast = 0;
      arToast('Object labels <b>' + (s.labels ? 'on' : 'off') + '</b>.');
    }
  };

  AR_EXT.tools.d_colorby = {
    assist: 1,
    tip: 'Colour the model by material, by tag, by storey or by kind instead of by its surfaces &mdash; press to cycle, off last',
    on: function () { var s = st(); return !!(s && s.colorby && s.colorby !== 'off'); },
    act: function (opt) {
      var s = stw(), by = pick(opt, 'by', CB_ORDER, s.colorby || 'off');
      if (CB_ORDER.indexOf(by) < 0) {
        arToast('Colour by: <b>' + esc(by) + '</b> is not one of ' + CB_ORDER.join(', ') + '.', 'bad');
        return;
      }
      s.colorby = by;
      if (by === 'off') { colOff(); arToast('Colouring off — the surfaces are back.'); return; }
      arToast('Coloured by <b>' + by + '</b> — the legend is bottom left.');
    }
  };

  AR_EXT.tools.d_transp = {
    assist: 1,
    tip: 'Transparency quality &mdash; how glass sorts against what is behind it: fast, sorted, or a dithered screen door',
    on: function () { var s = st(); return !!(s && s.transp && s.transp !== 'fast'); },
    act: function (opt) {
      var s = stw(), m = pick(opt, 'mode', TQ_ORDER, s.transp || 'fast');
      if (TQ_ORDER.indexOf(m) < 0) {
        arToast('Glass: <b>' + esc(m) + '</b> is not ' + TQ_ORDER.join(', ') + '.', 'bad');
        return;
      }
      s.transp = m;
      refreshMats();
      arToast('Glass: <b>' + m + '</b> — ' + TQ_NOTE[m]);
    }
  };

  AR_EXT.tools.d_backface = {
    assist: 1,
    tip: 'Face normals / back-face culling &mdash; the tell for a surface that is inside out: double-sided, culled, or normals drawn on the selection',
    on: function () { var s = st(); return !!(s && s.backface && s.backface !== 'double'); },
    act: function (opt) {
      var s = stw(), m = pick(opt, 'mode', BF_ORDER, s.backface || 'double');
      if (BF_ORDER.indexOf(m) < 0) {
        arToast('Normals: <b>' + esc(m) + '</b> is not ' + BF_ORDER.join(', ') + '.', 'bad');
        return;
      }
      s.backface = m;
      refreshMats();
      if (m !== 'normals') { normClear(); AR._dhNormKey = ''; }
      arToast(m === 'cull' ? 'Back faces culled — anything that vanishes is inside out.'
        : (m === 'normals' ? ('Face normals drawn on the selection (' + NORMAL_LEN + ' m, cyan).')
          : 'Double-sided again — every face draws from both sides.'));
    }
  };
}());
