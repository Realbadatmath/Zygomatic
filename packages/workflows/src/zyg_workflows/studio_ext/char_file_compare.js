// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_file_compare.js — Character Studio: Compare as a 3D A/B on the stage.
   2026-09-19. Sorts after char_file.js on purpose: it replaces that file's
   CST_ACT.compare (a two-column field diff in the panel) with a split stage.

   LEFT  = the base default of the injected 3D model: the same CC0 GLB the
           studio stands on, loaded again, clay, untouched — no hair, no skin,
           no scale, no dress. Or, when the operator injects a second character
           from the panel, THAT character built the same way as the right side.
   RIGHT = the modified version: the studio's own scene, live, so a value
           staged while comparing shows up on the right at once.

   One camera drives both halves (OrbitControls on the one canvas), rendered
   with a scissor split so the two figures are always seen from the same angle
   at the same size. The frame widens from 3:4 to 3:2 while comparing so each
   half keeps the studio's portrait proportion. Everything is undone by Stop,
   by leaving the tab, or by a new inject. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CST_ACT === 'undefined') return;

  var CMP = { on: false, mode: 'base', scene: null, model: null, store: null,
              other: null, loading: '', raf: 0, list: null, lastAspect: 0 };
  var CLAY = { body: 0xb9b2a8, eye: 0x3a3632 };

  /* ── the split render loop ────────────────────────────────────────────── */
  var pageLoop = cs3dLoop;
  cs3dLoop = function () {
    if (CMP.on) return cmpLoop();
    return pageLoop();
  };
  function cmpLoop() {
    if (CS3.raf || CS3.failed || !CS3.renderer) return;
    var R = CS3.renderer, cam = CS3.camera;
    (function tick() {
      CS3.raf = requestAnimationFrame(tick);
      CS3.controls.update();
      var size = R.getSize(new THREE.Vector2()), w = size.x, h = size.y;
      if (!w || !h) return;
      var hw = Math.floor(w / 2);
      var asp = hw / h;
      if (Math.abs(cam.aspect - asp) > 1e-6) { cam.aspect = asp; cam.updateProjectionMatrix(); }
      R.setScissorTest(true);
      R.setViewport(0, 0, hw, h); R.setScissor(0, 0, hw, h);
      if (CMP.scene) R.render(CMP.scene, cam);
      R.setViewport(hw, 0, w - hw, h); R.setScissor(hw, 0, w - hw, h);
      R.render(CS3.scene, cam);
      R.setScissorTest(false);
    })();
  }
  function restoreView() {
    if (!CS3.renderer) return;
    var size = CS3.renderer.getSize(new THREE.Vector2());
    CS3.renderer.setScissorTest(false);
    CS3.renderer.setViewport(0, 0, size.x, size.y);
    if (size.y) { CS3.camera.aspect = size.x / size.y; CS3.camera.updateProjectionMatrix(); }
  }

  /* ── the left-hand scene ──────────────────────────────────────────────── */
  function ensureScene() {
    if (CMP.scene) return CMP.scene;
    var s = new THREE.Scene();
    s.add(new THREE.HemisphereLight(0xdde4ee, 0x30353d, 0.6));
    var d1 = new THREE.DirectionalLight(0xffffff, 0.85); d1.position.set(0.8, 1.4, 1.6); s.add(d1);
    var d2 = new THREE.DirectionalLight(0x9fb4d6, 0.35); d2.position.set(-1.4, 0.6, -1.0); s.add(d2);
    CMP.scene = s;
    return s;
  }
  function disposeFigure() {
    if (CMP.store) {
      try { if (window.CSHAIR) CSHAIR.dispose(CMP.store); } catch (e) {}
      if (CMP.store.dress && CMP.store.dress.parent) CMP.store.dress.parent.remove(CMP.store.dress);
    }
    if (CMP.model) {
      if (CMP.model.parent) CMP.model.parent.remove(CMP.model);
      CMP.model.traverse(function (o) { if (o.isMesh && o.geometry) o.geometry.dispose(); });
    }
    CMP.model = null; CMP.store = null;
  }

  /* which CC0 body stands under a character: the operator's pin, else the
     bible's gender in the style already on the stage — cs3dBaseForChar's rule */
  function bodyFor(values) {
    var id = CS3.pinned;
    if (!id && values) {
      var g = String(values['identity.gender'] || '').toLowerCase();
      var cur = cs3dBody(CS3.modelId), style = cur ? cur.style : 'realistic';
      var m = CS_BASE_BODIES.find(function (b) { return b.gender === g && b.style === style; });
      if (m) id = m.id;
    }
    return cs3dBody(id || CS3.modelId || CS_BASE_DEFAULT) || cs3dBody(CS_BASE_DEFAULT);
  }

  /* load a fresh copy of a body GLB (the browser has it cached) and stand it
     on the origin exactly as cs3dLoadModel does */
  function loadBody(b, done) {
    if (!THREE.GLTFLoader) return done(null, 'GLTFLoader missing');
    var token = CMP.loading = b.id + ':' + Date.now();
    new THREE.GLTFLoader().load(CS_BASE_URL + b.file, function (g) {
      if (CMP.loading !== token) return;                 /* a later pick won */
      CMP.loading = '';
      var root = g.scene || g.scenes[0];
      var clay = new THREE.MeshStandardMaterial({ color: CLAY.body, roughness: 0.8, metalness: 0 });
      var eye = new THREE.MeshStandardMaterial({ color: CLAY.eye, roughness: 0.35, metalness: 0 });
      root.traverse(function (o) {
        if (!o.isMesh) return;
        o.material = /eye[lr]$/i.test(o.name || '') ? eye : clay;
      });
      var box = new THREE.Box3().setFromObject(root), c = new THREE.Vector3(); box.getCenter(c);
      root.position.set(-c.x, -box.min.y, -c.z);
      done(root, null);
    }, undefined, function (err) {
      if (CMP.loading !== token) return;
      CMP.loading = '';
      done(null, String(err && err.message || err || 'load failed'));
    });
  }

  function showBase() {
    CMP.mode = 'base'; CMP.other = null;
    disposeFigure();
    var b = cs3dBody(CS3.modelId) || cs3dBody(CS_BASE_DEFAULT);
    if (!b) return;
    label('left', 'loading…');
    loadBody(b, function (root, err) {
      if (!CMP.on || CMP.mode !== 'base') return;
      if (!root) { label('left', 'base body failed: ' + err); return; }
      disposeFigure();
      CMP.model = root; CMP.store = {};
      ensureScene().add(root);
      label('left', 'BASE · ' + b.lb + ' · untouched');
    });
  }

  function showOther(id) {
    var entry = (CMP.list || []).find(function (c) { return c.id === id; }) || { id: id, name: id };
    CMP.mode = 'other'; CMP.other = { id: id, name: entry.name, values: null };
    disposeFigure();
    label('left', 'loading ' + entry.name + '…');
    cfPost('other', { id: id }).then(function (j) {
      if (!CMP.on || !CMP.other || CMP.other.id !== id) return;
      if (!j.ok) { label('left', j.error || ('HTTP ' + j._code)); return; }
      CMP.other.name = j.name; CMP.other.values = j.values || {};
      var b = bodyFor(CMP.other.values);
      loadBody(b, function (root, err) {
        if (!CMP.on || !CMP.other || CMP.other.id !== id) return;
        if (!root) { label('left', 'body failed: ' + err); return; }
        disposeFigure();
        CMP.model = root; CMP.store = {};
        var scene = ensureScene(); scene.add(root);
        var vals = CMP.other.values;
        var getter = function (p) { return vals[p]; };
        try {
          if (window.CSDRESS) CSDRESS.runFor({ model: root, store: CMP.store, val: function (p) {
            var v = vals[p]; return (v === null || v === undefined) ? '' : String(v); }, main: false });
        } catch (e) { console.warn('compare dress', e); }
        try {
          if (window.CSHAIR) CSHAIR.buildFor(root, scene, CMP.store, getter, true);
        } catch (e) { console.warn('compare hair', e); }
        try {
          if (window.CSLASH) CSLASH.buildFor(root, CMP.store, getter);   /* lashes (2026-09-20) */
        } catch (e) { console.warn('compare lashes', e); }
        label('left', j.name + ' · modified · ' + b.lb);
        renderDiff();
      });
    }).catch(function (e) { label('left', String(e)); });
  }

  /* ── overlay: labels + the divider ───────────────────────────────────── */
  function overlay() {
    var main = document.querySelector('#view-charstudio .cs-main');
    if (!main) return null;
    var ov = document.getElementById('cs-cmp-ov');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'cs-cmp-ov';
      ov.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:4;display:none';
      ov.innerHTML =
        '<div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,.18)"></div>'
        + '<div id="cs-cmp-l" style="position:absolute;left:12px;top:12px;max-width:44%;font-size:11px;'
        + 'color:#cfd6e0;background:rgba(10,12,16,.7);padding:6px 10px;border-radius:8px"></div>'
        + '<div id="cs-cmp-r" style="position:absolute;left:calc(50% + 12px);top:12px;max-width:44%;font-size:11px;'
        + 'color:#cfd6e0;background:rgba(10,12,16,.7);padding:6px 10px;border-radius:8px"></div>';
      main.appendChild(ov);
    }
    return ov;
  }
  function label(side, text) {
    var el = document.getElementById(side === 'left' ? 'cs-cmp-l' : 'cs-cmp-r');
    if (el) el.textContent = text;
  }
  function rightLabel() {
    var name = (typeof CS !== 'undefined' && CS.charId) ? (CS.charName || CS.charId) : 'no character';
    var b = cs3dBody(CS3.modelId);
    label('right', name + ' · modified' + (b ? ' · ' + b.lb : ''));
  }
  function frameWide(on) {
    var main = document.querySelector('#view-charstudio .cs-main');
    if (!main) return;
    if (on) { main.dataset.cmpAspect = main.style.aspectRatio || ''; main.style.aspectRatio = '3 / 2'; }
    else { main.style.aspectRatio = main.dataset.cmpAspect || ''; }
    /* the canvas follows the frame on the next layout pass */
    setTimeout(function () { if (typeof cs3dSize === 'function') cs3dSize(); }, 0);
    setTimeout(function () { if (typeof cs3dSize === 'function') cs3dSize(); }, 250);
  }

  /* ── on / off ─────────────────────────────────────────────────────────── */
  function cmpOn() {
    if (CMP.on) return;
    if (typeof cs3dEnsure === 'function') cs3dEnsure();
    if (CS3.failed) return;
    if (typeof cfGridOff === 'function') cfGridOff();     /* the sheet grid hides the body */
    CMP.on = true;
    var ov = overlay(); if (ov) ov.style.display = 'block';
    frameWide(true);
    rightLabel();
    if (typeof cs3dStop === 'function') cs3dStop();
    cmpLoop();
    showBase();
  }
  function cmpOff() {
    if (!CMP.on) return;
    CMP.on = false; CMP.loading = '';
    if (typeof cs3dStop === 'function') cs3dStop();
    disposeFigure();
    var ov = document.getElementById('cs-cmp-ov'); if (ov) ov.style.display = 'none';
    frameWide(false);
    restoreView();
    if (CS3.model) pageLoop();
  }
  window.csCompareOff = cmpOff;
  window.csCompareOn = cmpOn;
  window.CSCMP = CMP;

  /* the stage's own hooks: a new base body re-loads the left figure; a new
     character injected re-labels the right */
  if (typeof CS3_HOOKS !== 'undefined') CS3_HOOKS.push(function (why) {
    if (!CMP.on) return;
    if (why === 'model') { if (CMP.mode === 'base') showBase(); }
    if (why === 'load' || why === 'model' || why === 'save') rightLabel();
    if (why === 'load' && CMP.other && typeof CS !== 'undefined' && CS.charId === CMP.other.id) showBase();
  });
  /* leaving the tab stops the loop; coming back must not restart the plain one over the split */
  if (typeof csLeave === 'function') {
    var pageLeave = csLeave;
    csLeave = function () { cmpOff(); return pageLeave.apply(this, arguments); };
  }

  /* ── the panel ────────────────────────────────────────────────────────── */
  var CMP_SECS = ['identity', 'face', 'eyes', 'hair', 'body', 'wardrobe', 'accessories'];
  function panel() {
    var html =
      '<div class="cst-hint big">Left: the <b>base default</b> of the injected 3D model — the CC0 body as '
      + 'it loads, untouched. Right: the <b>modified</b> version — skin, hair, height and dress from '
      + 'this character&rsquo;s bible, live. One camera drives both: drag to orbit, wheel to zoom.</div>'
      + '<div class="cst-field"><label>Left side</label>'
      + '<select id="cs-cmp-pick" onchange="csComparePick(this.value)">'
      + '<option value=""' + (CMP.mode === 'base' ? ' selected' : '') + '>Base default (untouched body)</option>'
      + (CMP.list || []).map(function (c) {
          return '<option value="' + esc(c.id) + '"' + (CMP.other && CMP.other.id === c.id ? ' selected' : '') + '>'
            + 'Inject: ' + esc(c.name) + ' — ' + esc(c.id) + '</option>'; }).join('')
      + '</select></div>'
      + '<div class="cst-hint">Pick a character to inject it on the left and compare it against the one '
      + 'in the studio — both built the same way from their bibles.</div>'
      + '<div class="cst-foot"><button class="go" onclick="csCompareOff();cstPanelClose&&cstPanelClose()">Stop comparing</button></div>'
      + '<div id="cs-cmp-diff"></div>';
    cstPanelOpen('d_compare', 'Compare', html);
    renderDiff();
  }
  window.csComparePick = function (id) {
    if (!CMP.on) cmpOn();
    if (!id) { showBase(); renderDiff(); }
    else showOther(id);
  };
  /* the field diff from the old panel, kept under the picker when a second
     character is in — a highlighted row is one the two bibles disagree about */
  function renderDiff() {
    var body = document.getElementById('cs-cmp-diff');
    if (!body) return;
    if (CMP.mode !== 'other' || !CMP.other || !CMP.other.values) { body.innerHTML = ''; return; }
    if (typeof CST === 'undefined' || !CST.spec || !CST.values || !(typeof CS !== 'undefined' && CS.charId)) {
      body.innerHTML = '<div class="cst-hint">Inject a character into the studio to see the fields side by side.</div>';
      return;
    }
    var F = CST.spec.fields, secs = CST.spec.sections || [], diff = 0, rows = '', vals = CMP.other.values;
    secs.filter(function (s) { return CMP_SECS.indexOf(s) >= 0; }).forEach(function (s) {
      var ps = Object.keys(F).filter(function (p) { return F[p].sec === s; });
      if (!ps.length) return;
      rows += '<div class="cst-grp">' + esc(s) + '</div>';
      ps.forEach(function (p) {
        var a = cfShow(vals[p]), b = cfShow(CST.values[p]), ne = (a !== b);
        if (ne) diff++;
        rows += '<div class="kv"' + (ne ? ' style="background:rgba(255,176,0,.10)"' : '') + '>'
          + '<b>' + esc(p.split('.').pop()) + '</b><span>'
          + esc(a) + '<span class="dim"> │ </span>' + esc(b) + '</span></div>';
      });
    });
    body.innerHTML = cstKv('fields that differ', diff)
      + '<div class="cst-hint">left = ' + esc(CMP.other.name) + ' · right = ' + esc(CS.charName || CS.charId) + '</div>'
      + rows;
  }

  CST_ACT.compare = function () {
    cmpOn();
    cstPanelOpen('d_compare', 'Compare', '<div class="todo">reading the library&hellip;</div>');
    var others = (typeof cfOthers === 'function') ? cfOthers() : Promise.resolve([]);
    others.then(function (list) { CMP.list = list; panel(); })
          .catch(function (e) { CMP.list = []; panel(); console.warn('compare list', e); });
  };

  if (window.SX && SX.ready) SX.ready.push('char_file_compare');
})();
