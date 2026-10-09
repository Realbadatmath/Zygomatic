// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_photoreal.js — Character Studio: the photoreal skin on the base body.
   2026-09-19. Sorts after char_dress.js / char_eyes.js / char_hair.js on
   purpose: their hooks paint the clay skin, build the eyes and the hair
   first; this one then swaps the BODY's material for the baked albedo atlas
   when the Photoreal switch is on, leaving the eyes (char_eyes) and the hair
   (char_hair) exactly as they were built.

   What is on disk, made by char_photoreal.py: one albedo atlas per base body
   at mesh_packs/photoreal/<body>/albedo.jpg — the body's UDIM tiles packed
   into a grid — and a manifest naming which tile went into which cell. The
   body's UVs are remapped here, per vertex, by the same rule, so the mesh
   itself is never touched on disk: the clay figure on Compare's left is the
   identical GLB with its original UVs.

   The switch is remembered (localStorage cs.photoreal) and starts ON once a
   skin is baked for the body on screen — the operator's brief (2026-09-19)
   was "when you're done the 3d model should be photorealistic, then I can
   compare it to its default base model". Only an explicit switch-off is
   remembered. Turning it off hands the body back to char_dress (its skin
   material) and restores the original UVs. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;
  if (typeof CS_TOOLS === 'undefined' || typeof CST_ACT === 'undefined') return;

  var PR = { on: false, body: '', man: null, tex: null, mat: null, env: null,
             job: '', timer: null, panelOpen: false, loading: '' };
  PR.on = true;
  try { PR.on = localStorage.getItem('cs.photoreal') !== '0'; } catch (e) {}

  var API = '/inspect/api/studio/char_photoreal/';
  function get(op, q) {
    var qs = Object.keys(q || {}).map(function (k) { return k + '=' + encodeURIComponent(q[k]); }).join('&');
    return fetch(API + op + (qs ? '?' + qs : ''), { cache: 'no-cache' }).then(function (r) { return r.json(); });
  }
  function post(op, body) {
    return fetch(API + op, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify(body || {}) }).then(function (r) { return r.json(); });
  }
  function h(s) { return (typeof esc === 'function') ? esc(String(s == null ? '' : s)) : String(s == null ? '' : s); }

  /* ── the tool, in the Model section right after Base body ─────────────── */
  (function addTool() {
    for (var i = 0; i < CS_TOOLS.length; i++) {
      var sec = CS_TOOLS[i];
      if (!sec || sec.sec !== 'Model' || !sec.items) continue;
      if (sec.items.some(function (t) { return t.id === 'photoreal'; })) return;
      var at = sec.items.findIndex(function (t) { return t.id === 'basebody'; });
      sec.items.splice(at < 0 ? 0 : at + 1, 0, {
        id: 'photoreal', lb: 'Photoreal', act: 'photoreal',
        tip: 'Bake a photoreal skin for the base body from its own depth plates (klein RefControl), '
           + 'then switch it on. Compare shows the clay base against it on identical geometry',
        svg: '<circle cx="12" cy="8.2" r="3.6"/><path d="M5.4 21c.6-4.2 3.2-6.6 6.6-6.6s6 2.4 6.6 6.6"/>'
           + '<path d="M9.6 7.4l.6.6M13.8 7l.6.6M11.4 9.8h1.2" opacity=".7"/>'
      });
      return;
    }
  })();

  /* ── body mesh + UV remap ──────────────────────────────────────────────── */
  function bodyMesh(model) {
    var best = null, n = -1;
    if (!model) return null;
    model.traverse(function (o) {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      if (/eye[lr]$/i.test(o.name || '')) return;
      for (var p = o; p; p = p.parent) { if (p.name === 'cs-hair' || p.name === 'CS3_DRESS') return; }
      var c = o.geometry.attributes.position.count;
      if (c > n) { n = c; best = o; }
    });
    return best;
  }

  /* per-vertex: which UDIM tile (Blender convention, v up) -> which atlas cell.
     Faces never straddle tiles on this mesh (measured: 0 of 84 680), so a
     vertex's own tile is its face's tile. */
  function remapUV(geom, atlas) {
    var uv = geom.attributes.uv;
    if (!uv) return false;
    if (!geom.userData.uv0) geom.userData.uv0 = uv.array.slice(0);
    var src = geom.userData.uv0, out = new Float32Array(src.length);
    /* cells: [tu, tv, x0, y0, size] in pixels (2026-09-20, the head pair is
       2048 px, the rest 1024) — or the older [tu, tv, col, row] grid */
    var lut = {}, W = atlas.width, Hh = atlas.height, T = atlas.tile || 1024;
    for (var i = 0; i < atlas.tiles.length; i++) {
      var t = atlas.tiles[i];
      lut[t[0] + ',' + t[1]] = (t.length >= 5) ? [t[2], t[3], t[4]] : [t[2] * T, t[3] * T, T];
    }
    var miss = 0;
    for (var k = 0; k < src.length; k += 2) {
      var u = src[k], vb = 1.0 - src[k + 1];              /* glTF v -> Blender v */
      var tu = Math.floor(u), tv = Math.floor(vb);
      var cell = lut[tu + ',' + tv];
      if (!cell) { miss++; out[k] = 0; out[k + 1] = 0; continue; }
      out[k] = (cell[0] + (u - tu) * cell[2]) / W;
      out[k + 1] = (cell[1] + (1.0 - (vb - tv)) * cell[2]) / Hh;   /* glTF v: 0 at the top row */
    }
    geom.setAttribute('uv', new THREE.BufferAttribute(out, 2));
    geom.attributes.uv.needsUpdate = true;
    geom.userData.uvAtlas = atlas.width + 'x' + atlas.height;
    if (miss) console.warn('char_photoreal: ' + miss + ' uv pairs outside the atlas tiles');
    return true;
  }
  function restoreUV(geom) {
    if (!geom || !geom.userData.uv0) return;
    geom.setAttribute('uv', new THREE.BufferAttribute(geom.userData.uv0.slice(0), 2));
    geom.attributes.uv.needsUpdate = true;
    delete geom.userData.uvAtlas;
  }

  /* ── a small studio environment for the skin's soft reflections ───────── */
  function envMap() {
    if (PR.env || !CS3.renderer || !THREE.PMREMGenerator) return PR.env;
    try {
      var sc = new THREE.Scene();
      var geo = new THREE.BoxGeometry();
      function panel(x, y, z, sx, sy, sz, c, i) {
        var m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: c }));
        m.material.color.multiplyScalar(i);
        m.position.set(x, y, z); m.scale.set(sx, sy, sz); sc.add(m);
      }
      var room = new THREE.Mesh(new THREE.BoxGeometry(12, 12, 12), new THREE.MeshBasicMaterial({ color: 0x6f6f6f, side: THREE.BackSide }));
      sc.add(room);
      panel(0, 5.6, 0, 6, 0.2, 6, 0xffffff, 3.0);          /* ceiling soft box */
      panel(-5.6, 2, 1, 0.2, 4, 3, 0xfff2e6, 1.8);         /* warm left */
      panel(5.6, 1.5, -1, 0.2, 3, 3, 0xe6efff, 1.4);       /* cool right */
      panel(0, 2.2, -5.6, 5, 2.5, 0.2, 0xffffff, 0.9);     /* back fill */
      var pm = new THREE.PMREMGenerator(CS3.renderer);
      PR.env = pm.fromScene(sc, 0.04).texture;
      pm.dispose();
    } catch (e) { console.warn('char_photoreal env', e); PR.env = null; }
    return PR.env;
  }

  /* ── apply / remove ────────────────────────────────────────────────────── */
  function currentBody() { return (CS3 && CS3.modelId) || ''; }

  function loadTexture(pub, cb) {
    var key = pub.albedo_url + '?v=' + Math.round(pub.albedo_mtime || 0);
    if (PR.tex && PR.tex.userData.key === key) return cb(PR.tex);
    if (PR.loading === key) return;
    PR.loading = key;
    new THREE.TextureLoader().load(key, function (t) {
      PR.loading = '';
      t.flipY = false;                                    /* glTF UV origin: top-left */
      if ('colorSpace' in t && THREE.SRGBColorSpace) t.colorSpace = THREE.SRGBColorSpace;
      else if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      t.generateMipmaps = true;
      t.minFilter = THREE.LinearMipmapLinearFilter;
      try { t.anisotropy = CS3.renderer.capabilities.getMaxAnisotropy(); } catch (e) {}
      t.userData.key = key;
      if (PR.tex && PR.tex !== t) { try { PR.tex.dispose(); } catch (e) {} }
      PR.tex = t;
      cb(t);
    }, undefined, function (err) { PR.loading = ''; console.warn('char_photoreal texture', err); });
  }

  function apply() {
    if (!PR.on || !CS3.model || !PR.man || PR.man.body !== currentBody()) return;
    var m = bodyMesh(CS3.model);
    if (!m) return;
    loadTexture(PR.man, function (tex) {
      if (!PR.on || !CS3.model || bodyMesh(CS3.model) !== m) return;
      remapUV(m.geometry, PR.man.atlas);
      if (!PR.mat) {
        PR.mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.58, metalness: 0 });
        /* 2026-09-20: pores + creases at close range (char_eyes.js), nil at full-body distance */
        if (window.CSEYES && CSEYES.skinMicro) CSEYES.skinMicro(PR.mat);
      }
      PR.mat.map = tex;
      PR.mat.envMap = envMap();
      PR.mat.envMapIntensity = 0.55;
      PR.mat.needsUpdate = true;
      m.material = PR.mat;
      if (!PR.hairDone) { PR.hairDone = true; rebuildHair(); }   /* brows are in the skin now */
      if (typeof cs3dLoop === 'function') cs3dLoop();
      paintCredit();
    });
  }

  function remove() {
    if (!CS3.model) return;
    var m = bodyMesh(CS3.model);
    if (m && m.material === PR.mat) {
      restoreUV(m.geometry);
      if (window.CSDRESS && CSDRESS.run) { try { CSDRESS.run('photoreal-off'); } catch (e) {} }
    }
    PR.hairDone = false;
    rebuildHair();
    if (typeof cs3dLoop === 'function') cs3dLoop();
    paintCredit();
  }

  function paintCredit() {
    var cr = document.getElementById('cs-credit');
    if (!cr) return;
    var tag = ' · photoreal skin';
    var t = cr.textContent || '';
    if (PR.on && PR.man && PR.man.body === currentBody()) { if (t.indexOf(tag) < 0) cr.textContent = t + tag; }
    else if (t.indexOf(tag) >= 0) cr.textContent = t.replace(tag, '');
  }

  function refresh(cb) {
    var body = currentBody();
    if (!body) return;
    get('status', { body: body, job: PR.job }).then(function (j) {
      if (j && j.ok) {
        PR.body = body;
        PR.man = j.published || null;
        if (PR.man) PR.man.body = body;
        if (cb) cb(j);
        if (PR.on) apply();
      }
    }).catch(function (e) { console.warn('char_photoreal status', e); });
  }

  /* the hook: after the page and the earlier extensions have done their work */
  /* char_hair.js asks this before building brows: painted brows on the skin
     and ribbon/strand brows on top would be two pairs */
  /* Brows are only "painted" while the atlas still HAS them painted. The bake
     projects klein's eyebrows and stubble into the skin, and this used to be
     true whenever the skin was on — which suppressed the grown brows for good
     and left a flat smudge on the forehead at every angle. char_skin_dehair.py
     takes the paint off and sets `dehaired` on the manifest; from then on the
     real strands grow. */
  function browsPainted() {
    return !!(PR.on && PR.man && PR.man.body === currentBody() && !PR.man.dehaired);
  }
  function rebuildHair() { if (typeof csHairRebuild === 'function') { try { csHairRebuild(); } catch (e) {} } }
  CS3_HOOKS.push(function (why) {
    if (!CS3.model) return;
    if (PR.man && PR.man.body === currentBody()) { if (PR.on) apply(); return; }
    refresh();
  });
  if (CS3.model) refresh();

  /* ── the panel ─────────────────────────────────────────────────────────── */
  function setOn(v) {
    PR.on = !!v;
    try { localStorage.setItem('cs.photoreal', PR.on ? '1' : '0'); } catch (e) {}
    if (PR.on) { if (PR.man && PR.man.body === currentBody()) apply(); else refresh(); }
    else remove();
    panel();
  }

  function fmtAge(ts) {
    if (!ts) return '';
    var s = Math.max(0, (Date.now() / 1000) - ts);
    if (s < 90) return Math.round(s) + ' s ago';
    if (s < 5400) return Math.round(s / 60) + ' min ago';
    if (s < 172800) return (s / 3600).toFixed(1) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }

  function panel(j) {
    if (typeof CST === 'undefined' || CST.panel !== 'photoreal') return;
    var body = currentBody();
    var pub = (PR.man && PR.man.body === body) ? PR.man : null;
    var job = j && j.job;
    var live = j && j.live;
    var html = '';
    html += '<div style="margin-bottom:8px">' + cstKv('base body', body || '—')
      + cstKv('baked skin', pub ? ('yes · ' + fmtAge(pub.albedo_mtime) + ' · '
              + pub.atlas.width + '×' + pub.atlas.height + ' atlas, '
              + Object.keys(pub.views || {}).length + ' views, coverage '
              + Math.round((pub.coverage || 0) * 100) + '%') : 'not yet') + '</div>';
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px">'
      + '<button class="go" id="pr-toggle" ' + (pub ? '' : 'disabled') + '>'
      + (PR.on ? '&#9673; Photoreal skin ON — switch off' : '&#9675; Photoreal skin OFF — switch on') + '</button>'
      + '<button class="go" id="pr-bake">' + (pub ? 'Re-bake' : 'Bake now') + '</button>'
      + (job && job.status === 'running' ? '<button class="go" id="pr-stop">Stop</button>' : '')
      + '</div>';
    html += '<div class="todo" style="margin-bottom:8px">Plates from this body in Blender → depth-controlled klein renders (RefControl, Apache-2.0) → projected into the body&rsquo;s UV atlas. About 6 to 10 minutes; the GPU is used for the render stage only. Compare then shows the clay base on the left against this skin on the right, same geometry.</div>';
    if (pub && pub.strip_url) {
      html += '<img src="' + pub.strip_url + '?v=' + Math.round(pub.albedo_mtime || 0) + '" style="width:100%;border-radius:6px;margin-bottom:8px" alt="the renders this skin was baked from">';
    }
    if (live && (!job || live.job !== PR.job)) {
      html += '<div class="cst-warn">A bake is running (' + h(live.job) + ', ' + h(live.stage) + ').</div>';
    }
    if (job) {
      var st = job.status;
      html += '<div style="margin-top:6px"><b>' + h(PR.job) + '</b> · ' + h(st) + (job.stage ? ' · ' + h(job.stage) : '')
        + (job.error ? '<div class="cst-warn">' + h(job.error) + '</div>' : '') + '</div>';
      var lines = (job.log || []).slice(-14);
      html += '<pre style="font-size:11px;line-height:1.35;max-height:220px;overflow:auto;background:rgba(0,0,0,.25);padding:6px;border-radius:6px;margin-top:6px">'
        + lines.map(h).join('\n') + '</pre>';
    }
    cstPanelOpen('photoreal', 'Photoreal skin', html);
    var tg = document.getElementById('pr-toggle'); if (tg) tg.onclick = function () { setOn(!PR.on); };
    var bk = document.getElementById('pr-bake'); if (bk) bk.onclick = function () { startBake(!!pub); };
    var sp = document.getElementById('pr-stop'); if (sp) sp.onclick = function () { post('stop', { job: PR.job }).then(function () { poll(); }); };
  }

  function startBake(force) {
    var body = currentBody();
    if (!body) return;
    post('start', { body: body, force: !!force }).then(function (j) {
      if (j && j.ok) { PR.job = j.job; poll(); }
      else if (j && j.job) { PR.job = j.job; poll(); }
      else if (typeof cstMsg === 'function') cstMsg((j && j.error) || 'could not start', 'warn');
    });
  }

  function poll() {
    if (PR.timer) { clearTimeout(PR.timer); PR.timer = null; }
    if (!PR.job) return;
    get('status', { body: currentBody(), job: PR.job }).then(function (j) {
      if (!j || !j.ok) return;
      var job = j.job;
      if (j.published) { j.published.body = currentBody(); }
      var had = PR.man && PR.man.albedo_mtime;
      if (job && job.status !== 'running') {
        PR.man = j.published || PR.man;
        if (job.status === 'done' && PR.man && (!had || PR.man.albedo_mtime !== had)) {
          PR.tex = null;            /* a new file under the same URL: reload */
          if (!PR.on) setOn(true); else apply();
        }
        panel(j);
        return;
      }
      panel(j);
      PR.timer = setTimeout(poll, 3000);
    });
  }

  CST_ACT.photoreal = function () {
    CST.panel = 'photoreal';
    refresh(function (j) { panel(j); if (PR.job) poll(); });
    panel();
  };

  function isApplied() {
    if (!PR.on || !CS3.model || !PR.mat || !PR.mat.map) return false;
    var m = bodyMesh(CS3.model);
    if (!(m && m.material === PR.mat && m.geometry.userData.uvAtlas)) return false;
    var brows = 0;
    CS3.model.traverse(function (o) { if (/^cs-brow/.test(o.name || '')) brows++; });
    return brows === 0;
  }

  window.CSPHOTOREAL = { state: PR, apply: apply, remove: remove, setOn: setOn,
                         refresh: refresh, isApplied: isApplied, browsPainted: browsPainted };
})();
