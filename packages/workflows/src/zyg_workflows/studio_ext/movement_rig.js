// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* movement_rig.js — Movement Studio opens on the skeleton, not on a video
   (2026-09-22).

   WHAT THIS REPLACES. Until today the tab's default was a copied mp4: a take of
   Abel that had already been rendered, played back through #mvst-video. You
   could not scrub the motion, you could not see the rig, and picking a
   different movement meant rendering again. The default block is gone from
   inspection.html; this file puts the actual article in the pane instead —
   Abel's cmu_mb skeleton inside the Character Studio clay base body, playing
   the captured sword walk, orbitable and scrubbable before a single GPU second
   is spent.

   ONE SKELETON runs through the whole feature: MPFB's ``cmu_mb`` rig, 31 bones
   named exactly like the CMU MotionBuilder BVH joints. Every clip in the motion
   library targets it, every actor wears it, and the SkeletonHelper drawn here
   is those same 31 bones. The body under them is the clay base body
   (Blender Studio Human Base Meshes v1.4.1, CC0), fitted to the character's own
   measurements when the fitter can reach them.

   WHERE THE WORK HAPPENS. Nothing is computed in the browser. The GLB comes
   from /inspect/api/studio/movement_rig/build → glb, which runs proxy_actor and
   rig_export_glb under Blender behind a job; this file posts, polls, and loads
   the bytes. A build that is already newer than its inputs answers `cached` on
   the first request and the pane fills in under a second.

   WRAPPING, NOT FORKING. studio_ext/*.js are concatenated and loaded AFTER the
   page script, so the four page functions this needs are taken over by
   reassignment — mvst3dLoad, mvst3dLoop, mvstLoadSubject, mvstEnter. Each still
   calls the original first (or falls through to it entirely), so a creature or
   an object injected into the tab keeps today's billboard and the dials, the
   Generate button and the Inject picker are untouched. The one thing the
   skeleton path takes over is the billboard: when MVR.glbUrl is set,
   mvst3dLoad loads a model instead of a plane.

   THE PANEL is a docked card top-left inside .cs-main with six sections —
   MOVEMENT (the library, grouped by bucket), TRANSPORT (play/scrub/speed/bones),
   FIT (what the bone-length fitter did, and a re-measure), TEACH (a video →
   GEM-X capture), EDIT (trim/speed/mirror/loop → a new clip) and RENDER (the
   take-10 VACE recipe re-pointed at this actor). Its open sections, the bones
   toggle and the speed live in localStorage under 'mvr.*'.

   FIT IS REPORTED, NOT ASSERTED. proxy_actor applies whatever its [x0.80, x1.25]
   clamp allows and reports a status — 'exact' when every group landed inside the
   3 % tolerance, 'clamped' when a group wanted more reshaping than the clamp
   permits, 'off' when the solve missed its clamped target anyway. The FIT section
   prints that status and the per-group arithmetic; 'none' means no fit was
   applied at all (the clay base body, or a character with no measurable cell). */
(function () {
  if (typeof mvst3dLoad !== 'function' || typeof mvstLoadSubject !== 'function'
      || typeof mvstEnter !== 'function' || typeof THREE === 'undefined') return;

  var API = '/inspect/api/studio/movement_rig/';
  var DEFAULT_MOTION = 'capture/qa_sword';
  /* 2026-09-23, operator: the tab opens on the plain CLAY BASE BODY, the same
     one Character Studio shows, never on a character. Follows Character
     Studio's pinned base body (localStorage 'cs.basebody'); the stylized
     bodies have no rig, so they fall back to their realistic sibling. */
  function defaultBase() {
    var pin = '';
    try { pin = localStorage.getItem('cs.basebody') || ''; } catch (e) {}
    var kind = /female/.test(pin) ? 'female_realistic' : 'male_realistic';
    return { id: 'base_' + kind, name: 'Base body · ' + kind.replace('_', ' '), base: true };
  }
  function isBase(id) { return /^base_(male|female)_realistic$/.test(String(id || '')); }
  var CLAY = 0xb9a58c;
  var EYE_RE = /(eye|cornea|iris|pupil|lash|brow)/i;

  var MVR = window.MVR = {
    glbUrl: '',          // the GLB to show; '' = the page's billboard
    actor: '',           // <char_id>__<motion with / -> _>
    motion: DEFAULT_MOTION,
    meta: null,          // the actor sidecar the build returned
    clips: [],           // /clips, once
    model: null,         // the wrapper group in MVST3.scene
    inner: null,         // the glTF scene inside it (what the clip animates)
    mixer: null,         // THREE.AnimationMixer
    action: null,
    skeleton: null,      // THREE.SkeletonHelper — .bones is the 31
    clock: null,
    dur: 0,
    speed: 1,
    paused: false,
    bones: true,
    loading: '',
    job: '',
    jobTimer: 0,
    loaded: false,       // a skeleton is in the pane and playing
    error: ''
  };

  /* ── little helpers ─────────────────────────────────────────────────────── */
  function E(id) { return document.getElementById(id); }
  function ES(s) { return (typeof esc === 'function') ? esc(String(s == null ? '' : s))
                          : String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
                              return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  /* r144 with legacy colour management: material.color and the 'color' vertex
     attribute are BOTH consumed as linear, so an sRGB swatch handed in raw is
     gamma-encoded on the way out and every mid-tone lifts towards white — the
     clay body renders as a plaster cast. Convert once, and only while the
     renderer really is encoding to sRGB. Same helper as char_hair/char_dress. */
  function srgb(hex) {
    var c = new THREE.Color(hex);
    if (MVST3.renderer && THREE.sRGBEncoding !== undefined
        && MVST3.renderer.outputEncoding === THREE.sRGBEncoding && c.convertSRGBToLinear)
      c.convertSRGBToLinear();
    return c;
  }
  /* THE ANATOMY SEAM (2026-09-23). movement_rig_anatomy.js solves ~240
     articulations, ~540 bone shafts and ~70 muscle bellies on top of the 31
     rig channels and draws them as instanced capsules. It hangs off these
     five calls and nothing else; with that file absent every one of them is
     a no-op and this tab is exactly what it was, the bare SkeletonHelper. */
  function anat(op, a, b) {
    var A = window.MVA;
    if (!A || typeof A[op] !== 'function') return null;
    try { return A[op](a, b); } catch (e) { console.error('MVA.' + op, e); return null; }
  }

  function lsGet(k, d) { try { var v = localStorage.getItem('mvr.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('mvr.' + k, String(v)); } catch (e) {} }

  /* Movement Studio's one-line status field is the only notification surface
     this view has. Never written while a render owns it (movement_track.js
     follows the same rule). */
  function status(msg, cls) {
    var st = E('mvst-status');
    if (!st || (typeof MVST !== 'undefined' && MVST.running)) return;
    st.textContent = msg || '';
    st.className = 'mvst-status ' + (cls || '');
  }

  function post(op, body) {
    return fetch(API + op, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (d) { d._code = r.status; return d; });
    });
  }
  function get(op, qs) {
    return fetch(API + op + (qs ? '?' + qs : '')).then(function (r) { return r.json(); });
  }

  /* ── the model ──────────────────────────────────────────────────────────── */
  function dropModel() {
    if (MVR.mixer) { try { MVR.mixer.stopAllAction(); } catch (e) {} }
    MVR.mixer = null; MVR.action = null; MVR.dur = 0;
    anat('drop');
    if (MVR.skeleton) { MVST3.scene.remove(MVR.skeleton); MVR.skeleton = null; }
    if (MVR.model) {
      MVST3.scene.remove(MVR.model);
      MVR.model.traverse(function (o) {
        if (o.isMesh || o.isSkinnedMesh) {
          if (o.geometry) o.geometry.dispose();
          if (o.material && o.material.dispose) o.material.dispose();
        }
      });
    }
    MVR.model = null; MVR.inner = null;
  }

  /* The billboard plane the page put up is not what we are looking at any more. */
  function dropPlane() {
    if (!MVST3.plane) return;
    MVST3.scene.remove(MVST3.plane);
    if (MVST3.plane.geometry) MVST3.plane.geometry.dispose();
    if (MVST3.plane.material) MVST3.plane.material.dispose();
    MVST3.plane = null; MVST3.loadedSrc = '';
  }

  /* The stock MVST3 rig has one hemisphere + one directional light and no
     ground. A body reads as a silhouette without a fill, and without a floor
     there is nothing to judge a stride against. Added once, kept. */
  function stage() {
    if (MVST3.__mvrStage) return;
    MVST3.__mvrStage = true;
    var lights = 0;
    MVST3.scene.traverse(function (o) { if (o.isLight) lights++; });
    if (!lights) {
      MVST3.scene.add(new THREE.HemisphereLight(0xdde4ee, 0x30353d, 0.6));
      var key = new THREE.DirectionalLight(0xffffff, 0.9);
      key.position.set(0.6, 0.8, 1.2);
      MVST3.scene.add(key);
    }
    var fill = new THREE.DirectionalLight(0xffffff, 0.4);
    fill.position.set(-1.2, 0.6, 2.2);
    MVST3.scene.add(fill);
    var grid = new THREE.GridHelper(4, 16, 0x3b4450, 0x252b33);
    grid.material.transparent = true;
    grid.material.opacity = 0.38;
    MVST3.__mvrGrid = grid;
    MVST3.scene.add(grid);
    /* a glTF's basecolour is sRGB; without an output encoding the clay reads
       washed out and the skeleton loses its contrast against it */
    if (THREE.sRGBEncoding !== undefined && 'outputEncoding' in MVST3.renderer)
      MVST3.renderer.outputEncoding = THREE.sRGBEncoding;
  }

  /* glTF is Y-up, and the exporter already puts the actor's feet near y=0. Keep
     the world scale (a 1.52 m body IS 1.52 units) so the grid reads as metres;
     only the camera moves. */
  function frame(box) {
    var size = box.getSize(new THREE.Vector3());
    var ctr = box.getCenter(new THREE.Vector3());
    var cam = MVST3.camera;
    var t = Math.tan((cam.fov * Math.PI / 180) / 2);
    var asp = cam.aspect || 0.75;
    var d = Math.max((size.y / 2) / t, (size.x / 2) / (t * asp));
    d = Math.max(1.1, d * 1.6);
    MVST3.controls.minDistance = Math.min(MVST3.controls.minDistance, 0.4);
    MVST3.controls.maxDistance = Math.max(MVST3.controls.maxDistance, d * 3);
    cam.far = Math.max(cam.far, d * 8);
    cam.updateProjectionMatrix();
    var dir = new THREE.Vector3(0.45, 0.12, 0.88).normalize().multiplyScalar(d);
    cam.position.set(ctr.x + dir.x, ctr.y + dir.y, ctr.z + dir.z);
    MVST3.controls.target.copy(ctr);
    MVST3.controls.update();
    if (MVST3.__mvrGrid) MVST3.__mvrGrid.position.set(ctr.x, box.min.y, ctr.z);
  }

  /* Clay, uniformly: the point of this view is the SHAPE and the motion, and a
     glTF's own materials are whatever the base body happened to ship. Eyes go
     darker so the head still reads as a head. */
  function clayify(root) {
    root.traverse(function (o) {
      if (!o.isMesh && !o.isSkinnedMesh) return;
      /* THE SKELETON IS NOT SKIN. The actor GLB now carries the CC0
         anatomical skeleton as a second skinned mesh named 'skeleton',
         fitted bone by bone to the same 31 joints. It is the Bones LAYER,
         so it is tagged here — before the anatomy module ever sees it — and
         given neither the clay material nor the dark-eye test. Everything
         downstream (measure, bakeSides, applySkin) skips a tagged mesh. */
      if (o.userData && o.userData.mvaLayer) return;   /* already one of ours */
      if ((o.name || '') === 'skeleton') { o.userData.mvaLayer = 'bone'; return; }
      var dark = EYE_RE.test(o.name || '') || EYE_RE.test((o.material && o.material.name) || '');
      var mat = new THREE.MeshStandardMaterial({
        color: srgb(dark ? 0x2b2622 : CLAY), roughness: dark ? 0.45 : 0.85, metalness: 0.0
      });
      mat.skinning = true;                 // r144 still reads this on the material
      if (o.material && o.material.dispose) o.material.dispose();
      o.material = mat;
      o.castShadow = false; o.receiveShadow = false;
      o.frustumCulled = false;             // a skinned body can leave its rest bbox
    });
  }

  function adopt(gltf) {
    var inner = gltf.scene || (gltf.scenes && gltf.scenes[0]);
    if (!inner) throw new Error('the GLB has no scene');
    dropPlane();
    dropModel();
    /* stage() first: it is what sets the renderer's output encoding, and
       srgb() below has to know whether to convert. */
    stage();
    clayify(inner);

    var wrap = new THREE.Group();
    wrap.add(inner);
    MVST3.scene.add(wrap);
    wrap.updateMatrixWorld(true);
    MVR.model = wrap; MVR.inner = inner;

    /* the 31 cmu_mb joints, drawn as lines through the clay.
       SkeletonHelper ships with vertexColors on (its own blue→green gradient),
       which wins over material.color — turn it off or the line colour set here
       is decoration that never reaches the screen. */
    var helper = new THREE.SkeletonHelper(inner);
    if (helper.material) {
      helper.material.vertexColors = false;
      helper.material.color = srgb(0x44d6e8);
      helper.material.linewidth = 2;
      helper.material.depthTest = false;   // inside a solid body, or it is invisible
      helper.material.transparent = true;
      helper.material.opacity = 0.95;
      helper.material.needsUpdate = true;
    }
    helper.renderOrder = 10;
    helper.visible = MVR.bones;
    MVST3.scene.add(helper);
    MVR.skeleton = helper;

    /* and the anatomy over the same 31 bones. This runs BEFORE the mixer has
       been stepped even once, which is the only moment the model is still in
       its bind pose — measure() needs that, because a body measured mid-stride
       reports a shoulder where the swing happened to put it. */
    anat('build', inner, helper);

    var clips = gltf.animations || [];
    if (clips.length) {
      MVR.mixer = new THREE.AnimationMixer(inner);
      MVR.action = MVR.mixer.clipAction(clips[0]);
      MVR.action.setLoop(THREE.LoopRepeat, Infinity);
      MVR.action.play();
      MVR.dur = clips[0].duration || 0;
      MVR.paused = false;
    }
    frame(new THREE.Box3().setFromObject(inner));
    MVR.loaded = true;
    MVR.error = '';
    return (MVR.skeleton.bones || []).length;
  }

  function loadGLB(url) {
    mvst3dEnsure(); if (MVST3.failed) return;
    mvst3dSize();
    if (typeof THREE.GLTFLoader !== 'function') {
      MVR.error = 'no GLTFLoader in this three.js build';
      status(MVR.error, 'err');
      return;
    }
    if (MVR.loading === url) return;
    MVR.loading = url;
    new THREE.GLTFLoader().load(url, function (gltf) {
      MVR.loading = '';
      try {
        var n = adopt(gltf);
        status((MVR.meta && MVR.meta.motion ? MVR.meta.motion + ' · ' : '')
               + n + ' bones · ' + MVR.dur.toFixed(1) + ' s'
               + ' · fit=' + fitStatus(MVR.meta), 'done');
        if (!MVST3.failed) { var em = E('mvst-empty'); if (em) em.style.display = 'none'; }
        mvstShowStill();
        /* mvstShowStill has almost certainly started the PAGE's tick already —
           it has no clock and no mixer, and mvst3dLoop's first line is
           `if (MVST3.raf) return`, so without this the model stands frozen in
           its rest pose and nothing says why. Hand the frame over. */
        mvst3dStop();
        mvst3dLoop();
        panelRender();
      } catch (e) {
        console.error('movement_rig adopt', e);
        MVR.error = String((e && e.message) || e);
        status('skeleton did not load: ' + MVR.error, 'err');
        panelRender();
      }
    }, null, function (e) {
      MVR.loading = '';
      console.error('movement_rig GLTFLoader', url, e);
      MVR.error = 'could not fetch the GLB';
      status(MVR.error, 'err');
      panelRender();
    });
  }

  /* ── build: cached, or a job to poll ────────────────────────────────────── */
  function buildStop() { clearTimeout(MVR.jobTimer); MVR.jobTimer = 0; MVR.job = ''; }

  /* the server's own actor-name rule (movement_rig.py actor_name) */
  function actorNameFor(charId, motion) {
    return String(charId || '') + '__' + String(motion || '').replace(/\//g, '_');
  }
  /* is THIS clip the one the loaded actor is playing? */
  function onStage(motion) {
    return !!MVR.loaded && !!MVST.subjectId && !MVR.job
      && MVR.actor === actorNameFor(MVST.subjectId, motion);
  }

  function build(charId, motion) {
    buildStop();
    MVR.motion = motion || MVR.motion;
    MVR.error = '';
    status('building ' + MVR.motion + '…', '');
    panelRender();
    return post('build', { char_id: charId, motion: MVR.motion, fit: true })
      .then(function (d) {
        if (!d || d.error) {
          MVR.error = (d && d.error) || 'build refused';
          status(MVR.error, 'err'); panelRender(); return;
        }
        MVR.actor = d.actor || MVR.actor;
        if (d.cached && d.glb) {
          MVR.meta = d.meta || null;
          MVR.glbUrl = d.glb;
          loadGLB(d.glb);
          return;
        }
        if (d.job_id) { MVR.job = d.job_id; MVR.jobTimer = setTimeout(pollJob, 1500); }
      })
      .catch(function (e) {
        MVR.error = String(e); status(MVR.error, 'err'); panelRender();
      });
  }

  function pollJob() {
    var job = MVR.job;
    if (!job) return;
    get('job', 'job_id=' + encodeURIComponent(job)).then(function (j) {
      if (MVR.job !== job) return;                 /* a newer build took over */
      if (!j || j.error && !j.status) {
        MVR.error = (j && j.error) || 'lost the build job';
        status(MVR.error, 'err'); buildStop(); panelRender(); return;
      }
      if (j.status === 'failed') {
        MVR.error = j.error || 'the build failed';
        status(MVR.error, 'err'); buildStop(); panelRender(); return;
      }
      if (j.status === 'done' && j.glb) {
        buildStop();
        MVR.meta = j.meta || null;
        MVR.actor = j.actor || MVR.actor;
        MVR.glbUrl = j.glb;
        loadGLB(j.glb);
        return;
      }
      var log = (j.log || []);
      status(log.length ? log[log.length - 1] : (j.status || 'building…'), '');
      MVR.jobTimer = setTimeout(pollJob, 3000);
    }).catch(function () {
      if (MVR.job !== job) return;
      MVR.jobTimer = setTimeout(pollJob, 3000);    /* a dropped poll is not a dead job */
    });
  }

  /* ── the panel ──────────────────────────────────────────────────────────── */
  var SECTIONS = [
    ['movement', 'Movement'], ['transport', 'Transport'], ['fit', 'Fit'],
    ['teach', 'Teach'], ['edit', 'Edit'], ['render', 'Render']
  ];
  var PANEL = { open: {}, filter: '', renderJob: '', renderTimer: 0, captureJob: '', captureTimer: 0,
                msg: {}, busy: {} };
  SECTIONS.forEach(function (s) {
    PANEL.open[s[0]] = lsGet('open.' + s[0], s[0] === 'movement' || s[0] === 'transport' ? '1' : '0') === '1';
  });

  function injectStyle() {
    if (document.getElementById('mvr-style')) return;
    var st = document.createElement('style');
    st.id = 'mvr-style';
    st.textContent =
      '#view-movement .cs-mainwrap{position:relative;}'
      + '#mvr-panel{position:absolute;left:0;top:0;width:266px;max-height:100%;'
      + 'display:none;flex-direction:column;background:rgba(12,15,20,.92);color:var(--txt,#dfe4ea);'
      + 'border:1px solid var(--line,#242a33);border-radius:11px;font-size:.70rem;z-index:6;'
      + 'box-shadow:0 8px 28px rgba(0,0,0,.55);overflow:hidden;}'
      + '#mvr-panel.on{display:flex;}'
      + '#mvr-panel .mvr-head button{margin-left:auto;padding:0 6px;font-size:.8rem;line-height:1;}'
      + '#mvr-btn{margin-left:8px;background:var(--panel,#141a24);border:1px solid var(--line,#242a33);'
      + 'border-radius:8px;color:var(--muted,#8b939e);font:inherit;font-size:.7rem;padding:4px 10px;cursor:pointer;}'
      + '#mvr-btn.on{background:#1d2d3d;color:#8fd4ff;}'
      + '#mvr-panel .mvr-head{padding:7px 10px;border-bottom:1px solid var(--line,#242a33);'
      + 'display:flex;gap:6px;align-items:baseline;flex:0 0 auto;}'
      + '#mvr-panel .mvr-head b{font-size:.72rem;letter-spacing:.04em;}'
      + '#mvr-panel .mvr-head span{color:var(--muted,#8b939e);font-size:.62rem;'
      + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
      + '#mvr-panel .mvr-scroll{overflow-y:auto;overflow-x:hidden;flex:1 1 auto;}'
      + '.mvr-sec{border-bottom:1px solid var(--line,#242a33);}'
      + '.mvr-sec>h4{margin:0;padding:6px 10px;font-size:.62rem;font-weight:600;letter-spacing:.09em;'
      + 'text-transform:uppercase;color:var(--muted,#8b939e);cursor:pointer;user-select:none;'
      + 'display:flex;justify-content:space-between;align-items:center;}'
      + '.mvr-sec>h4:hover{color:var(--txt,#dfe4ea);}'
      + '.mvr-bd{padding:2px 10px 9px;display:flex;flex-direction:column;gap:5px;}'
      + '.mvr-bd.off{display:none;}'
      + '.mvr-row{display:flex;gap:5px;align-items:center;}'
      + '.mvr-row label{flex:0 0 46px;color:var(--muted,#8b939e);font-size:.62rem;}'
      + '.mvr-clips{max-height:150px;overflow-y:auto;display:flex;flex-direction:column;gap:1px;}'
      + '.mvr-grp{color:var(--muted,#8b939e);font-size:.58rem;letter-spacing:.09em;'
      + 'text-transform:uppercase;margin:5px 0 1px;}'
      + '.mvr-clip{padding:3px 6px;border-radius:5px;cursor:pointer;display:flex;gap:5px;'
      + 'justify-content:space-between;line-height:1.25;}'
      + '.mvr-clip:hover{background:#1a212c;}'
      + '.mvr-clip.on{background:#1d2d3d;color:#8fd4ff;}'
      + '.mvr-clip i{font-style:normal;color:var(--muted,#8b939e);font-size:.58rem;flex:0 0 auto;}'
      + '#mvr-panel input,#mvr-panel select{background:#0c0f14;color:inherit;font:inherit;'
      + 'font-size:.66rem;border:1px solid var(--line,#242a33);border-radius:5px;padding:3px 6px;'
      + 'min-width:0;flex:1 1 auto;}'
      + '#mvr-panel input[type=range]{padding:0;border:none;background:none;}'
      + '#mvr-panel button{background:#141a24;color:inherit;font:inherit;font-size:.66rem;'
      + 'border:1px solid var(--line,#242a33);border-radius:5px;padding:3px 8px;cursor:pointer;'
      + 'flex:0 0 auto;}'
      + '#mvr-panel button:hover:not(:disabled){border-color:var(--accent,#6ea8fe);}'
      + '#mvr-panel button:disabled{opacity:.45;cursor:not-allowed;}'
      + '#mvr-panel button.on{background:#1d2d3d;color:#8fd4ff;}'
      + '.mvr-fitrow{display:flex;justify-content:space-between;font-size:.62rem;'
      + 'font-variant-numeric:tabular-nums;}'
      + '.mvr-note{color:var(--muted,#8b939e);font-size:.60rem;line-height:1.35;'
      + 'white-space:pre-wrap;word-break:break-word;}'
      + '.mvr-note.err{color:#f0a0a0;}';
    document.head.appendChild(st);
  }

  function ensurePanel() {
    injectStyle();
    var el = E('mvr-panel');
    if (el) return el;
    var main = document.querySelector('#view-movement .cs-main');
    var wrap = document.querySelector('#view-movement .cs-mainwrap');
    if (!main || !wrap) return null;
    el = document.createElement('div');
    el.id = 'mvr-panel';
    el.innerHTML = '<div class="mvr-head"><b>Skeleton</b><span id="mvr-sub">cmu_mb</span>'
                 + '<button type="button" id="mvr-close" title="Fold the skeleton panel away (Esc)">&times;</button></div>'
                 + '<div class="mvr-scroll" id="mvr-scroll"></div>';
    wrap.appendChild(el);
    E('mvr-close').onclick = function () { panelShow(false); };
    /* 2026-09-23, operator: the panel sat OVER the preview at the real window
       size. It now stands BESIDE the frame, on its right, in the empty part of
       the stage, open by default; the header button and Esc fold it away and
       the choice is remembered per browser. */
    ensureButton();
    window.addEventListener('resize', panelPlace);
    panelShow(lsGet('panel', '1') === '1');
    return el;
  }
  /* the frame is centred and sized from its height (3:4), so where its right
     edge falls is only known at layout time */
  function panelPlace() {
    var el = E('mvr-panel'), main = document.querySelector('#view-movement .cs-main');
    if (!el || !main) return;
    el.style.left = (main.offsetLeft + main.offsetWidth + 12) + 'px';
    el.style.top = main.offsetTop + 'px';
    el.style.maxHeight = main.offsetHeight + 'px';
  }
  function ensureButton() {
    if (E('mvr-btn')) return;
    var top = document.querySelector('#view-movement .mvst-topctl');
    if (!top) return;
    var b = document.createElement('button');
    b.id = 'mvr-btn'; b.type = 'button';
    b.textContent = 'Skeleton';
    b.title = 'Movement picker, transport, fit, teach, edit and render for the skeleton on the stage';
    b.onclick = function () { var p = E('mvr-panel'); panelShow(!(p && p.classList.contains('on'))); };
    var status = E('mvst-status');
    if (status && status.parentNode === top) top.insertBefore(b, status); else top.insertBefore(b, top.firstChild);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && E('mvr-panel') && E('mvr-panel').classList.contains('on')) panelShow(false);
    });
  }
  function panelShow(on) {
    var el = E('mvr-panel'); if (!el) return;
    el.classList.toggle('on', !!on);
    if (on) panelPlace();
    var b = E('mvr-btn'); if (b) b.classList.toggle('on', !!on);
    lsSet('panel', on ? '1' : '0');
  }

  function note(sec) {
    var m = PANEL.msg[sec];
    return m ? '<div class="mvr-note' + (m.err ? ' err' : '') + '">' + ES(m.text) + '</div>' : '';
  }
  function say(sec, text, err) { PANEL.msg[sec] = { text: text, err: !!err }; panelRender(); }

  function secMovement() {
    var f = PANEL.filter.toLowerCase();
    var buckets = [['cmu', 'CMU mocap'], ['auth', 'Authored'],
                   ['capture', 'Captured'], ['edit', 'Edited']];
    var h = '<div class="mvr-row"><input id="mvr-filter" type="text" placeholder="filter clips"'
          + ' value="' + ES(PANEL.filter) + '"></div><div class="mvr-clips">';
    var shown = 0;
    buckets.forEach(function (b) {
      var rows = MVR.clips.filter(function (c) {
        return c.bucket === b[0]
          && (!f || (c.id + ' ' + (c.label || '') + ' ' + (c.tags || []).join(' ')).toLowerCase().indexOf(f) >= 0);
      });
      if (!rows.length) return;
      h += '<div class="mvr-grp">' + ES(b[1]) + '</div>';
      rows.forEach(function (c) {
        shown++;
        h += '<div class="mvr-clip' + (c.id === MVR.motion ? ' on' : '') + '"'
           + ' data-clip="' + ES(c.id) + '" title="' + ES(c.id) + '">'
           + '<span>' + ES(c.label || c.id) + '</span>'
           + '<i>' + (c.frames ? c.frames + 'f' : '') + '</i></div>';
      });
    });
    if (!shown) h += '<div class="mvr-note">' + (MVR.clips.length ? 'nothing matches that filter'
                                                                  : 'the clip list did not load') + '</div>';
    return h + '</div>' + note('movement');
  }

  function secTransport() {
    var t = MVR.mixer ? MVR.mixer.time : 0;
    var fps = (MVR.meta && MVR.meta.fps) || 24;
    var pos = MVR.dur ? (t % MVR.dur) : 0;
    return '<div class="mvr-row">'
      + '<button id="mvr-play">' + (MVR.paused ? '&#9654; Play' : '&#10074;&#10074; Pause') + '</button>'
      + '<button id="mvr-bones" class="' + (MVR.bones ? 'on' : '')
      + '" title="The bare cmu_mb helper: one GL line per rig channel, 31 of them. '
      + 'The anatomy layers below draw the same rig as a body.">Rig</button>'
      + '<span class="mvr-note" id="mvr-read" style="margin-left:auto">'
      + pos.toFixed(2) + ' s · f' + Math.round(pos * fps) + '</span></div>'
      + '<div class="mvr-row"><label>scrub</label>'
      + '<input id="mvr-scrub" type="range" min="0" max="1000" step="1" value="'
      + (MVR.dur ? Math.round(pos / MVR.dur * 1000) : 0) + '"' + (MVR.dur ? '' : ' disabled') + '></div>'
      + '<div class="mvr-row"><label>speed</label>'
      + '<input id="mvr-speed" type="range" min="0.25" max="2" step="0.05" value="' + MVR.speed + '">'
      + '<span class="mvr-note">&times;' + MVR.speed.toFixed(2) + '</span></div>'
      + '<div class="mvr-note">' + ES(MVR.motion) + ' · '
      + (MVR.dur ? MVR.dur.toFixed(2) + ' s' : 'no clip') + ' · '
      + ((MVR.skeleton && MVR.skeleton.bones) ? MVR.skeleton.bones.length : 0) + ' rig channels</div>'
      + (anat('controls') || '');
  }

  /* proxy_actor's report: status exact | clamped | off. No report at all means
     nothing was reshaped — 'none'. */
  function fitStatus(meta) {
    var fit = (meta || {}).fit;
    return (fit && fit.status) || 'none';
  }

  /* which groups asked for more than the [x0.80, x1.25] clamp allows */
  function limitNote(fit) {
    var hit = (fit && fit.clamped_groups) || [];
    if (!hit.length) return '';
    return ' (' + hit.map(function (k) {
      var g = (fit.groups || {})[k] || {};
      return k + ' wanted \u00d7' + (+g.requested).toFixed(2)
           + ', applied \u00d7' + (+g.applied || 1).toFixed(2);
    }).join('; ') + ')';
  }

  function secFit() {
    var m = MVR.meta || {};
    var sex = String(m.base_body_id || '').replace('_realistic', '') || 'unknown';
    var h = '<div class="mvr-note">base body: ' + ES(sex)
          + (m.height_m ? ' · ' + (+m.height_m).toFixed(2) + ' m' : '') + '</div>';
    var fit = m.fit;
    if (fit && fit.groups) {
      Object.keys(fit.groups).forEach(function (k) {
        var g = fit.groups[k] || {};
        h += '<div class="mvr-fitrow"><span>' + ES(k) + '</span><span>target '
           + (+g.target).toFixed(3) + ' &middot; rig ' + (+g.rig_fraction).toFixed(3)
           + ' &middot; &times;' + (+g.applied || 1).toFixed(2)
           + ' &rarr; ' + (+g.measured).toFixed(3) + '</span></div>';
      });
      h += '<div class="mvr-note">fit: ' + ES(fitStatus(m)) + limitNote(fit) + '</div>';
      /* the fitter reshapes the base body at ITS own height and the uniform
         scale down to the bible height happens after it, so this pair is not
         the actor's stature — the line above is */
      if (fit.height_after_m)
        h += '<div class="mvr-note">fit pass ' + (+fit.height_before_m).toFixed(3)
           + ' &rarr; ' + (+fit.height_after_m).toFixed(3)
           + ' m, then scaled to the bible height</div>';
    } else if (String(m.name || '').indexOf('base_') === 0) {
      h += '<div class="mvr-note">the clay base body itself &mdash; no fit</div>';
    } else {
      /* no measurable body cell on the character's sheet: the bible height still
         scales the rig, but no group was reshaped */
      h += '<div class="mvr-note">no body cell &mdash; bible height only</div>';
    }
    return h + '<div class="mvr-row"><button id="mvr-measure"'
      + (PANEL.busy.fit ? ' disabled' : '') + '>Measure from sheet</button></div>' + note('fit');
  }

  function secTeach() {
    return '<div class="mvr-row"><input id="mvr-cap-video" type="text" placeholder="/path/to/video.mp4"'
      + ' value="' + ES(lsGet('cap.video', '')) + '"></div>'
      + '<div class="mvr-row"><input id="mvr-cap-id" type="text" placeholder="capture/my_slug"'
      + ' value="capture/"></div>'
      + '<div class="mvr-row"><input id="mvr-cap-label" type="text" placeholder="what it is"></div>'
      + '<div class="mvr-row"><button id="mvr-cap-go"' + (PANEL.captureJob ? ' disabled' : '')
      + '>Capture</button>'
      + '<span class="mvr-note">video &rarr; GEM-X &rarr; cmu_mb BVH · tens of GPU minutes</span></div>'
      + note('teach');
  }

  function secEdit() {
    return '<div class="mvr-row"><label>trim</label>'
      + '<input id="mvr-ed-a" type="number" placeholder="first"><input id="mvr-ed-b" type="number" placeholder="last"></div>'
      + '<div class="mvr-row"><label>speed</label><input id="mvr-ed-speed" type="number" step="0.05" placeholder="1.0"></div>'
      + '<div class="mvr-row"><label>loop</label><input id="mvr-ed-loop" type="number" placeholder="frames"></div>'
      + '<div class="mvr-row"><label>mirror</label><input id="mvr-ed-mirror" type="checkbox" style="flex:0 0 auto"></div>'
      + '<div class="mvr-row"><label>save</label><input id="mvr-ed-save" type="text" placeholder="slug"></div>'
      + '<div class="mvr-row"><label>label</label><input id="mvr-ed-label" type="text" placeholder="shown in the list"></div>'
      + '<div class="mvr-row"><button id="mvr-ed-go"' + (PANEL.busy.edit ? ' disabled' : '') + '>Save edit of '
      + ES(MVR.motion) + '</button></div>' + note('edit');
  }

  function secRender() {
    return '<div class="mvr-row"><button id="mvr-render"'
      + ((MVR.actor && !PANEL.renderJob) ? '' : ' disabled') + '>Render with VACE (take)</button></div>'
      + '<div class="mvr-note">the take-10 fixture recipe, re-pointed at '
      + ES(MVR.actor || 'no actor yet') + '</div>' + note('render');
  }

  var BODY = { movement: secMovement, transport: secTransport, fit: secFit,
               teach: secTeach, edit: secEdit, render: secRender };

  /* the anatomy module redraws the panel when one of its own switches moves */
  MVR.panelRender = function () { panelRender(); };

  function panelRender() {
    var el = ensurePanel(); if (!el) return;
    var sub = E('mvr-sub');
    if (sub) sub.textContent = (MVR.meta && MVR.meta.name) || MVR.actor || 'cmu_mb';
    var h = '';
    SECTIONS.forEach(function (s) {
      var on = PANEL.open[s[0]];
      h += '<div class="mvr-sec"><h4 data-sec="' + s[0] + '"><span>' + ES(s[1]) + '</span>'
         + '<span>' + (on ? '&minus;' : '+') + '</span></h4>'
         + '<div class="mvr-bd' + (on ? '' : ' off') + '">'
         + (on ? BODY[s[0]]() : '') + '</div></div>';
    });
    E('mvr-scroll').innerHTML = h;
    panelPlace();
    wire();
  }

  /* The panel is re-rendered wholesale, so every handler is re-attached here
     rather than delegated — there is exactly one panel and it is small. */
  function wire() {
    var root = E('mvr-scroll'); if (!root) return;

    Array.prototype.forEach.call(root.querySelectorAll('h4[data-sec]'), function (h) {
      h.onclick = function () {
        var k = h.getAttribute('data-sec');
        PANEL.open[k] = !PANEL.open[k];
        lsSet('open.' + k, PANEL.open[k] ? '1' : '0');
        panelRender();
      };
    });

    var f = E('mvr-filter');
    if (f) f.oninput = function () {
      PANEL.filter = f.value;
      var sel = f.selectionStart;
      panelRender();
      var nf = E('mvr-filter');
      if (nf) { nf.focus(); try { nf.setSelectionRange(sel, sel); } catch (e) {} }
    };
    Array.prototype.forEach.call(root.querySelectorAll('.mvr-clip'), function (c) {
      c.onclick = function () {
        var id = c.getAttribute('data-clip');
        /* "already selected" is NOT "already on the stage": TEACH and EDIT both
           point MVR.motion at the clip they just made, so guarding on
           id === MVR.motion made the first click on a fresh clip a dead one —
           it looked chosen and the actor kept playing the old motion, with no
           way back short of picking a second clip and returning. Ask the actor
           instead of the selection. */
        if (!id || onStage(id)) return;
        MVR.motion = id;
        lsSet('motion', id);
        if (MVST.subjectType === 'character' && MVST.subjectId) build(MVST.subjectId, id);
        else { say('movement', 'inject a character first — a clip is played by an actor.', true); }
        panelRender();
      };
    });

    var play = E('mvr-play');
    if (play) play.onclick = function () {
      MVR.paused = !MVR.paused;
      if (MVR.action) MVR.action.paused = MVR.paused;
      panelRender();
    };
    var bones = E('mvr-bones');
    if (bones) bones.onclick = function () {
      MVR.bones = !MVR.bones;
      lsSet('bones', MVR.bones ? '1' : '0');
      if (MVR.skeleton) MVR.skeleton.visible = MVR.bones;
      panelRender();
    };
    anat('wire');

    var scrub = E('mvr-scrub');
    if (scrub) scrub.oninput = function () {
      if (!MVR.mixer || !MVR.dur) return;
      var t = (+scrub.value / 1000) * MVR.dur;
      MVR.mixer.setTime(t);
      readout();
    };
    var sp = E('mvr-speed');
    if (sp) sp.oninput = function () {
      MVR.speed = +sp.value || 1;
      lsSet('speed', MVR.speed);
      var lab = sp.nextElementSibling;
      if (lab) lab.innerHTML = '&times;' + MVR.speed.toFixed(2);
    };

    var meas = E('mvr-measure');
    if (meas) meas.onclick = function () {
      if (!MVST.subjectId) return say('fit', 'no character loaded', true);
      PANEL.busy.fit = true; say('fit', 'measuring the contact sheet…');
      post('metrics', { char_id: MVST.subjectId }).then(function (d) {
        PANEL.busy.fit = false;
        if (!d || d.error) return say('fit', d && d.error || 'measure failed', true);
        var fr = d.fractions || {};
        say('fit', 'measured ' + (d.confidence || '') + ': '
            + Object.keys(fr).map(function (k) { return k + ' ' + (+fr[k]).toFixed(3); }).join(', ')
            + ' — rebuilding');
        build(MVST.subjectId, MVR.motion);
      }).catch(function (e) { PANEL.busy.fit = false; say('fit', String(e), true); });
    };

    var cap = E('mvr-cap-go');
    if (cap) cap.onclick = function () {
      var video = (E('mvr-cap-video') || {}).value || '';
      var cid = (E('mvr-cap-id') || {}).value || '';
      var label = (E('mvr-cap-label') || {}).value || '';
      lsSet('cap.video', video.trim());
      PANEL.busy.teach = true; say('teach', 'starting the capture…');
      post('capture', { video: video.trim(), clip_id: cid.trim(), label: label.trim() })
        .then(function (d) {
          PANEL.busy.teach = false;
          if (!d || !d.ok) return say('teach', (d && d.error) || 'capture refused', true);
          PANEL.captureJob = d.job_id;
          say('teach', 'capture job ' + d.job_id + ' running…');
          PANEL.captureTimer = setTimeout(capturePoll, 3000);
        }).catch(function (e) { PANEL.busy.teach = false; say('teach', String(e), true); });
    };

    var ed = E('mvr-ed-go');
    if (ed) ed.onclick = function () {
      var a = (E('mvr-ed-a') || {}).value, b = (E('mvr-ed-b') || {}).value;
      var body = { src: MVR.motion, save: ((E('mvr-ed-save') || {}).value || '').trim(),
                   label: ((E('mvr-ed-label') || {}).value || '').trim() };
      if (a !== '' && b !== '') body.trim = [+a, +b];
      if (((E('mvr-ed-speed') || {}).value || '') !== '') body.speed = +E('mvr-ed-speed').value;
      if (((E('mvr-ed-loop') || {}).value || '') !== '') body.loop = +E('mvr-ed-loop').value;
      if ((E('mvr-ed-mirror') || {}).checked) body.mirror = true;
      PANEL.busy.edit = true; say('edit', 'saving…');
      post('edit', body).then(function (d) {
        PANEL.busy.edit = false;
        if (!d || !d.ok) return say('edit', (d && d.error) || 'edit refused', true);
        var id = (d.clip && d.clip.id) || '';
        say('edit', 'saved ' + id);
        loadClips().then(function () { if (id) { MVR.motion = id; panelRender(); } });
      }).catch(function (e) { PANEL.busy.edit = false; say('edit', String(e), true); });
    };

    var rn = E('mvr-render');
    if (rn) rn.onclick = function () {
      if (!MVR.actor) return say('render', 'build an actor first', true);
      say('render', 'asking for the take…');
      post('render', { actor: MVR.actor }).then(function (d) {
        if (!d || !d.ok) {
          /* 409 with the ComfyUI reason is the documented refusal, not a bug —
             show it verbatim and leave the button disabled until it changes */
          return say('render', (d && d.error) || 'render refused', true);
        }
        PANEL.renderJob = d.job_id;
        say('render', 'render job ' + d.job_id + ' running…');
        PANEL.renderTimer = setTimeout(renderPoll, 4000);
      }).catch(function (e) { say('render', String(e), true); });
    };
  }

  function readout() {
    var r = E('mvr-read');
    if (!r || !MVR.mixer) return;
    var fps = (MVR.meta && MVR.meta.fps) || 24;
    var pos = MVR.dur ? (MVR.mixer.time % MVR.dur) : MVR.mixer.time;
    r.textContent = pos.toFixed(2) + ' s · f' + Math.round(pos * fps);
    var s = E('mvr-scrub');
    if (s && MVR.dur && document.activeElement !== s)
      s.value = Math.round(pos / MVR.dur * 1000);
  }

  function capturePoll() {
    var job = PANEL.captureJob;
    if (!job) return;
    get('job', 'job_id=' + encodeURIComponent(job)).then(function (j) {
      if (PANEL.captureJob !== job) return;
      if (!j) { PANEL.captureTimer = setTimeout(capturePoll, 4000); return; }
      if (j.status === 'failed') { PANEL.captureJob = ''; return say('teach', j.error || 'capture failed', true); }
      if (j.status === 'done') {
        PANEL.captureJob = '';
        var id = (j.clip && j.clip.id) || j.motion || '';
        say('teach', 'captured ' + id);
        loadClips().then(function () { if (id) { MVR.motion = id; panelRender(); } });
        return;
      }
      var log = j.log || [];
      say('teach', log.length ? log[log.length - 1] : (j.status || 'running…'));
      PANEL.captureTimer = setTimeout(capturePoll, 4000);
    }).catch(function () { PANEL.captureTimer = setTimeout(capturePoll, 4000); });
  }

  function renderPoll() {
    var job = PANEL.renderJob;
    if (!job) return;
    get('job', 'job_id=' + encodeURIComponent(job)).then(function (j) {
      if (PANEL.renderJob !== job) return;
      if (!j) { PANEL.renderTimer = setTimeout(renderPoll, 5000); return; }
      if (j.status === 'failed') { PANEL.renderJob = ''; return say('render', j.error || 'render failed', true); }
      if (j.status === 'done') {
        PANEL.renderJob = '';
        say('render', 'take ready' + (j.fidelity ? '\n' + j.fidelity : ''));
        mvstShowVideo(API + 'video?job_id=' + encodeURIComponent(job));
        return;
      }
      var log = j.log || [];
      say('render', log.length ? log[log.length - 1] : (j.status || 'running…'));
      PANEL.renderTimer = setTimeout(renderPoll, 5000);
    }).catch(function () { PANEL.renderTimer = setTimeout(renderPoll, 5000); });
  }

  function loadClips() {
    return get('clips').then(function (d) {
      MVR.clips = (d && d.clips) || [];
      panelRender();
      return MVR.clips;
    }).catch(function () { return []; });
  }

  /* ── the four wraps ─────────────────────────────────────────────────────── */

  /* (a) the billboard becomes a model whenever MVR.glbUrl is set */
  var _load = mvst3dLoad;
  window.mvst3dLoad = function (src) {
    if (MVR.glbUrl) { loadGLB(MVR.glbUrl); return; }
    return _load.apply(this, arguments);
  };

  /* (b) the tick drives the mixer as well as the orbit controls */
  var _loop = mvst3dLoop;
  window.mvst3dLoop = function () {
    if (!MVR.model) return _loop.apply(this, arguments);
    if (!MVST3.renderer || MVST3.raf || MVST3.failed) return;
    MVR.clock = MVR.clock || new THREE.Clock();
    MVR.clock.getDelta();
    (function tick() {
      MVST3.raf = requestAnimationFrame(tick);
      var dt = MVR.clock.getDelta();
      if (MVR.mixer && !MVR.paused) MVR.mixer.update(dt * MVR.speed);
      anat('tick');
      readout();
      MVST3.controls.update();
      MVST3.renderer.render(MVST3.scene, MVST3.camera);
    })();
  };

  /* (c) a character gets a skeleton; a creature or an object keeps the billboard */
  var _subject = mvstLoadSubject;
  window.mvstLoadSubject = function (type, c) {
    if (type !== 'character') {
      MVR.glbUrl = ''; MVR.loaded = false;
      buildStop(); dropModel();
      return _subject.apply(this, arguments);
    }
    /* the original sets the header, the ids and the dials; it also calls
       mvst3dLoad with the still, which the (a) wrap turns into the model when
       one is already up for this subject */
    MVR.glbUrl = ''; MVR.loaded = false;
    dropModel();
    var r = _subject.apply(this, arguments);
    if (c && isBase(c.id)) {
      var sub = E('mvst-csub');
      if (sub) sub.textContent = 'Blender Studio Human Base Meshes v1.4.1 · CC0 · cmu_mb skeleton';
    }
    ensurePanel(); panelRender();
    build(c && c.id, MVR.motion);
    return r;
  };

  /* (d) the tab opens on the clay base body playing the default motion
     instead of an empty pane; a character comes in through Inject Subject */
  var _enter = mvstEnter;
  window.mvstEnter = function () {
    var r = _enter.apply(this, arguments);
    ensurePanel();
    if (!MVR.clips.length) loadClips(); else panelRender();
    if (MVST.loaded || MVR.booted) return r;
    MVR.booted = true;
    MVR.motion = DEFAULT_MOTION;
    mvstLoadSubject('character', defaultBase());
    return r;
  };

  var _leave = (typeof mvstLeave === 'function') ? mvstLeave : null;
  if (_leave) window.mvstLeave = function () {
    clearTimeout(PANEL.renderTimer); clearTimeout(PANEL.captureTimer);
    return _leave.apply(this, arguments);
  };

  /* restore the panel's own state (never the motion of a foreign character) */
  /* 2026-09-23: the 31-line helper is no longer what this tab opens on. It is
     still one click away under RIG, but the anatomy layers are the drawing. */
  MVR.bones = lsGet('bones', window.MVA ? '0' : '1') === '1';
  MVR.speed = Math.min(2, Math.max(0.25, parseFloat(lsGet('speed', '1')) || 1));

  window.SX = window.SX || {};
  (window.SX.ready = window.SX.ready || []).push('movement_rig');
})();
