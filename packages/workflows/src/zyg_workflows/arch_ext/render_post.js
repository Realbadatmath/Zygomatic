// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* render_post — Render ▸ Quality preset, Occlusion, Bloom, Depth of field,
   Anti-alias, Resolution (2026-09-08).

   Post-processing through the AR_EXT.render seam. Nothing in inspection.html
   was edited: the studio already routes every frame and every snapshot through
   arRender(), which hands the frame to AR_EXT.render when a family set one.

   The three.js example passes are vendored UMD builds of r144
   (https://cdn.jsdelivr.net/npm/three@0.144.0/examples/js/…, MIT) sitting in
   vendor/three/; they are loaded here, in order, with sequential <script>
   elements from AR_EXT.ready — shaders first, then EffectComposer (which
   defines THREE.Pass / THREE.FullScreenQuad), then the passes.

   AR_EXT.render is only a function while at least one effect is on; with
   everything off it is null again and the plain renderer.render path keeps its
   speed. State lives in AR.doc.ext.render_post so it travels with the drawing.

   Icons: r_preset (cycle draft → presentation → print), r_ao, r_bloom, r_dof,
   r_aa (switches), r_res (action, pixel-ratio scale). */
(function () {
  'use strict';

  /* load order matters: every file below only needs THREE.* globals defined
     by a file above it (EffectComposer defines Pass + FullScreenQuad). */
  var FILES = [
    'CopyShader', 'SSAOShader', 'LuminosityHighPassShader', 'BokehShader', 'SMAAShader',
    'SimplexNoise',
    'EffectComposer', 'ShaderPass', 'MaskPass', 'RenderPass',
    'SSAOPass', 'UnrealBloomPass', 'BokehPass', 'SMAAPass'
  ];
  var SCALES = [0.5, 0.75, 1, 1.5, 2];
  var PRESETS = ['draft', 'presentation', 'print'];
  var DEF = {ao: false, bloom: false, dof: false, aa: false, scale: 1, bloom_strength: 0.35, preset: ''};

  /* the one global this family leaves behind, family-prefixed */
  var RP = window.arRenderPost = {
    files: FILES, loaded: false, ready: null, composer: null, passes: {}, sig: null
  };

  /* ── state (per drawing, in AR.doc.ext.render_post) ───────────────────── */
  function stRead() {
    var src = (window.AR && AR.doc && AR.doc.ext && AR.doc.ext.render_post) || null, o = {}, k;
    for (k in DEF) if (Object.prototype.hasOwnProperty.call(DEF, k)) {
      o[k] = (src && src[k] !== undefined && src[k] !== null) ? src[k] : DEF[k];
    }
    return o;
  }
  function stWrite(s) {
    if (!AR.doc) AR.doc = {id: '', name: 'Untitled drawing', ext: {}};
    if (!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    AR.doc.ext.render_post = s;
    RP.sig = sigOf(s);
    if (typeof arDirty === 'function') arDirty(true);
  }
  function sigOf(s) {
    return [s.ao ? 1 : 0, s.bloom ? 1 : 0, s.dof ? 1 : 0, s.aa ? 1 : 0, s.scale, s.bloom_strength].join('|');
  }
  function anyOn(s) { return !!(s.ao || s.bloom || s.dof || s.aa); }

  /* ── the loader ───────────────────────────────────────────────────────── */
  function loadAll() {
    if (RP.ready) return RP.ready;
    RP.ready = new Promise(function (res, rej) {
      var i = 0;
      (function next() {
        if (i >= FILES.length) { RP.loaded = true; res(true); return; }
        var name = FILES[i++];
        var el = document.createElement('script');
        el.src = 'vendor/three/' + name + '.js';
        el.async = false;
        el.onload = function () { next(); };
        el.onerror = function () { rej(new Error('vendor/three/' + name + '.js did not load')); };
        document.head.appendChild(el);
      })();
    });
    return RP.ready;
  }

  /* ── the passes, made once and reused ─────────────────────────────────── */
  function cssSize() {
    var w = (AR.host && AR.host.clientWidth) || 900, h = (AR.host && AR.host.clientHeight) || 600;
    return [Math.max(2, w), Math.max(2, h)];
  }
  function devSize() {
    var s = cssSize(), pr = AR.renderer.getPixelRatio();
    return [Math.max(2, Math.round(s[0] * pr)), Math.max(2, Math.round(s[1] * pr))];
  }
  function pRender() {
    if (!RP.passes.render) RP.passes.render = new THREE.RenderPass(AR.scene, AR.cam);
    return RP.passes.render;
  }
  function pAO() {
    if (!RP.passes.ssao) {
      var d = devSize();
      var p = new THREE.SSAOPass(AR.scene, AR.cam, d[0], d[1]);
      p.kernelRadius = 0.6;             /* scene units: 0.6 m of contact darkening */
      p.minDistance = 0.005;
      p.maxDistance = 0.1;
      RP.passes.ssao = p;
    }
    return RP.passes.ssao;
  }
  function pBloom(strength) {
    if (!RP.passes.bloom) {
      var d = devSize();
      RP.passes.bloom = new THREE.UnrealBloomPass(new THREE.Vector2(d[0], d[1]), 0.35, 0.4, 0.9);
    }
    RP.passes.bloom.strength = (strength === undefined) ? 0.35 : strength;
    RP.passes.bloom.radius = 0.4;
    RP.passes.bloom.threshold = 0.9;
    return RP.passes.bloom;
  }
  function pDof() {
    if (!RP.passes.bokeh) {
      var d = devSize(), s = cssSize();
      RP.passes.bokeh = new THREE.BokehPass(AR.scene, AR.cam, {
        focus: focusDistance(), aperture: 0.00015, maxblur: 0.01,
        aspect: s[0] / s[1], width: d[0], height: d[1]
      });
    }
    return RP.passes.bokeh;
  }
  function pAA() {
    if (!RP.passes.smaa) {
      var d = devSize();
      RP.passes.smaa = new THREE.SMAAPass(d[0], d[1]);
    }
    return RP.passes.smaa;
  }

  /* the focal plane: the selection's centre when there is one, else whatever
     the orbit controls are looking at. Read every frame — the camera moves. */
  function focusDistance() {
    var t = null;
    try {
      if (AR.sel && AR.sel.length && typeof arBounds === 'function') t = arBounds(true).c;
    } catch (e) { t = null; }
    if (!t && AR.controls) t = AR.controls.target;
    if (!t) return 10;
    return Math.max(0.1, AR.cam.position.distanceTo(t));
  }
  RP.focusDistance = focusDistance;

  /* ── the chain ────────────────────────────────────────────────────────── */
  function rebuild() {
    if (!RP.loaded || !window.AR || !AR.renderer) return;
    var s = stRead();
    if (!anyOn(s)) {                      /* give the plain path back */
      AR_EXT.render = null;
      if (RP.composer) RP.composer.passes.length = 0;
      return;
    }
    if (!RP.composer) RP.composer = new THREE.EffectComposer(AR.renderer);
    var c = RP.composer, chain = [];
    chain.push(pRender());
    if (s.ao) chain.push(pAO());
    if (s.dof) chain.push(pDof());        /* bokeh before bloom/AA: it wants a clean colour buffer */
    if (s.bloom) chain.push(pBloom(s.bloom_strength));
    if (s.aa) chain.push(pAA());          /* anti-alias the finished frame, so it goes last */
    c.passes.length = 0;
    for (var i = 0; i < chain.length; i++) c.addPass(chain[i]);
    /* BokehPass and SMAAPass write to writeBuffer but ship with needsSwap
       false (they are meant to be last). Swap when they are not. */
    var last = chain[chain.length - 1];
    if (RP.passes.bokeh) RP.passes.bokeh.needsSwap = (RP.passes.bokeh !== last);
    if (RP.passes.smaa) RP.passes.smaa.needsSwap = (RP.passes.smaa !== last);
    sizeAll();
    AR_EXT.render = renderFrame;
  }

  function renderFrame() {
    var c = RP.composer;
    if (!c || !c.passes.length) { AR.renderer.render(AR.scene, AR.cam); return; }
    var cam = AR.cam;                     /* the ortho toggle swaps AR.cam under us */
    if (RP.passes.render) RP.passes.render.camera = cam;
    if (RP.passes.ssao) RP.passes.ssao.camera = cam;
    var b = RP.passes.bokeh;
    if (b && c.passes.indexOf(b) >= 0) {
      var sz = cssSize();
      b.camera = cam;
      b.uniforms.focus.value = focusDistance();
      b.uniforms.aspect.value = sz[0] / sz[1];
    }
    c.render();
  }

  function sizeAll() {
    if (!RP.composer) return;
    var s = cssSize(), d = devSize();
    RP.composer.setSize(s[0], s[1]);      /* CSS size; the composer multiplies by its pixel ratio */
    if (RP.passes.ssao) RP.passes.ssao.setSize(d[0], d[1]);
    if (RP.passes.smaa) RP.passes.smaa.setSize(d[0], d[1]);
    if (RP.passes.bokeh) RP.passes.bokeh.renderTargetDepth.setSize(d[0], d[1]);
  }

  /* ── output resolution ────────────────────────────────────────────────── */
  function applyScale(s) {
    var dpr = window.devicePixelRatio || 1;
    var pr = Math.max(0.25, Math.min(4, (s.scale || 1) * dpr));
    AR.renderer.setPixelRatio(pr);
    if (RP.composer) RP.composer.setPixelRatio(pr);
    if (typeof arSize === 'function') arSize();   /* resizes the canvas and calls our resize hook */
    sizeAll();
  }
  function applyAll() {
    var s = stRead();
    applyScale(s);
    rebuild();
  }
  RP.apply = applyAll;

  /* ── shadows, through the studio's own switches ───────────────────────── */
  function setShadows(want) {
    if (!!AR.shadows === !!want) return;
    arTool('t_sun');
  }
  function setShadowRes(want) {
    for (var i = 0; i < 4 && (AR.shadowRes || 2048) !== want; i++) arShadowRes();
  }

  /* ── presets ──────────────────────────────────────────────────────────── */
  function applyPreset(name) {
    var s = stRead();
    if (name === 'draft') {
      s.ao = s.bloom = s.dof = s.aa = false;
      s.scale = 0.75;
      setShadows(false);
    } else if (name === 'presentation') {
      s.ao = true; s.aa = true; s.bloom = true; s.dof = false;
      s.bloom_strength = 0.2;                     /* bloom low */
      s.scale = 1;
      setShadows(true); setShadowRes(2048);
    } else if (name === 'print') {
      s.ao = true; s.aa = true; s.bloom = false; s.dof = false;
      s.scale = 2;
      setShadows(true); setShadowRes(4096);
    } else {
      return null;
    }
    s.preset = name;
    stWrite(s);
    applyAll();
    return s;
  }
  RP.preset = applyPreset;

  function label(s) {
    var on = [];
    if (s.ao) on.push('occlusion');
    if (s.bloom) on.push('bloom');
    if (s.dof) on.push('depth of field');
    if (s.aa) on.push('anti-alias');
    return on.length ? on.join(' + ') : 'nothing';
  }

  /* a switch: flip one field, drop out of whatever preset was on */
  function toggle(field, human) {
    return function (opt) {
      if (!RP.loaded) {
        loadAll().then(function () { flip(field, human, opt); })
          .catch(function (e) { arToast('Post-processing did not load: ' + esc(String(e.message || e)), 'bad'); });
        arToast('Loading the post-processing passes…');
        return;
      }
      flip(field, human, opt);
    };
  }
  function flip(field, human, opt) {
    var s = stRead();
    var want = (opt && typeof opt === 'object' && opt.on !== undefined) ? !!opt.on : !s[field];
    s[field] = want;
    if (s.preset) s.preset = 'custom';
    stWrite(s);
    applyAll();
    if (typeof arToolsRender === 'function') arToolsRender();
    arToast('<b>' + human + '</b> ' + (want ? 'on' : 'off') + ' — post-processing: ' + label(s) + '.');
  }

  /* ── registrations ────────────────────────────────────────────────────── */
  AR_EXT.tools.r_ao = {
    tog: 1, assist: 1, _ready: null,
    tip: 'Ambient occlusion — the contact darkening in the corners that makes a model sit down',
    on: function () { return stRead().ao; },
    act: toggle('ao', 'Ambient occlusion')
  };
  AR_EXT.tools.r_bloom = {
    tog: 1, assist: 1,
    tip: 'Bloom — light bleeding round the bright parts of the frame',
    on: function () { return stRead().bloom; },
    act: toggle('bloom', 'Bloom')
  };
  AR_EXT.tools.r_dof = {
    tog: 1, assist: 1,
    tip: 'Depth of field — a focal distance, so a model photograph reads as a photograph',
    on: function () { return stRead().dof; },
    act: toggle('dof', 'Depth of field')
  };
  AR_EXT.tools.r_aa = {
    tog: 1, assist: 1,
    tip: 'Anti-aliasing — SMAA over the finished frame, so an edge stops stair-stepping',
    on: function () { return stRead().aa; },
    act: toggle('aa', 'Anti-aliasing')
  };
  AR_EXT.tools.r_res = {
    assist: 1,
    tip: 'Output resolution — the pixel size of a render, independent of the viewport',
    act: function (opt) {
      var s = stRead(), v;
      if (opt && typeof opt === 'object' && opt.scale !== undefined) v = parseFloat(opt.scale);
      else v = parseFloat(prompt('Output resolution — pixels per viewport pixel (0.5, 0.75, 1, 1.5 or 2):',
        String(s.scale)));
      if (!isFinite(v) || v <= 0) { arToast('Resolution unchanged — that is not a scale.', 'warn'); return; }
      v = Math.max(0.25, Math.min(4, v));
      s.scale = v;
      if (s.preset) s.preset = 'custom';
      stWrite(s);
      applyAll();
      var c = AR.renderer.domElement;
      arToast('Output resolution <b>&times;' + arFmt(v) + '</b> — ' + c.width + ' &times; ' + c.height + ' px.');
    }
  };
  AR_EXT.tools.r_preset = {
    tog: 1, assist: 1,
    tip: 'Render preset — draft, presentation, print. One knob that sets occlusion, bloom, depth of field, anti-alias, resolution and shadows',
    on: function () { var p = stRead().preset; return !!p && p !== 'custom'; },
    act: function (opt) {
      var run = function () {
        var s = stRead(), name;
        if (opt && typeof opt === 'object' && opt.preset) name = String(opt.preset).toLowerCase();
        else if (opt && typeof opt === 'string') name = opt.toLowerCase();
        else name = PRESETS[(PRESETS.indexOf(s.preset) + 1) % PRESETS.length];
        if (PRESETS.indexOf(name) < 0) {
          arToast('Unknown preset <b>' + esc(name) + '</b> — draft, presentation or print.', 'warn');
          return;
        }
        var out = applyPreset(name);
        if (typeof arToolsRender === 'function') arToolsRender();
        arToast('Preset <b>' + name + '</b> — ' + label(out) + ', resolution &times;' + arFmt(out.scale)
          + ', shadows ' + (AR.shadows ? (AR.shadowRes || 2048) + '&sup2;' : 'off') + '.');
      };
      if (!RP.loaded) {
        arToast('Loading the post-processing passes…');
        loadAll().then(run).catch(function (e) {
          arToast('Post-processing did not load: ' + esc(String(e.message || e)), 'bad');
        });
        return;
      }
      run();
    }
  };

  AR_EXT.resizes.push(function (w, h) {
    if (!RP.composer) return;
    RP.composer.setSize(Math.max(2, w), Math.max(2, h));
    var d = devSize();
    if (RP.passes.ssao) RP.passes.ssao.setSize(d[0], d[1]);
    if (RP.passes.smaa) RP.passes.smaa.setSize(d[0], d[1]);
    if (RP.passes.bokeh) RP.passes.bokeh.renderTargetDepth.setSize(d[0], d[1]);
  });

  /* a drawing that carries render_post settings must apply them when it is
     opened, not only when an icon is pressed: six comparisons a frame. */
  AR_EXT.ticks.push(function () {
    if (!RP.loaded) return;
    var s = stRead(), sig = sigOf(s);
    if (sig === RP.sig) return;
    RP.sig = sig;
    applyAll();
    if (typeof arToolsRender === 'function') arToolsRender();
  });

  AR_EXT.ready.push(function () {
    RP.sig = sigOf(stRead());
    var p = loadAll().then(function () {
      applyAll();                       /* re-apply whatever the drawing carried */
      return true;
    }).catch(function (e) {
      console.error('render_post vendor load', e);
      return false;
    });
    AR_EXT.tools.r_ao._ready = p;       /* the tests await this */
    RP.ready = p;
  });
})();
