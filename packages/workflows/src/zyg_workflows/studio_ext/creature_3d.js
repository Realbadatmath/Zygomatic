// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── creature_3d.js ── Creature Studio: a real mesh behind the 3D toggle ──────
   2026-09-18.

   What was here before: #crst-3d was an orbit rig showing the creature's hero
   PNG on a PlaneGeometry billboard, reachable only through the 'v_pin' tool —
   which is named "Pin source" and means something else entirely. A creature
   with no picture had nothing at all to look at, and the coat-colour tools
   (cc_base / cc_second / cc_accent / px_tint …) only ever showed up in the
   rendered picture, never on a body.

   What this file does, entirely by wrapping page globals (studio_ext seam —
   this bundle is loaded AFTER inspection.html's own script block, so every
   ct... / crst3d... global already exists):

     1. crst3dLoad  → loads a GLB with THREE.GLTFLoader instead of a billboard.
        Source order: the creature's OWN mesh (CT.facts.mesh.glb_url, served by
        studio_ext_server/creature.py) else the chosen base creature — the one
        pinned in localStorage 'crst.basecreature', else base_creatures[0]. The
        bases are THIRD-PARTY CC0 stand-ins (Quaternius animals, Kenney
        cube-pets, a Smithsonian deer); our own pufferball is NOT among them, it
        only ever appears as one creature's own mesh. The billboard stays as the
        fallback when the loader fails, so nothing regresses.
     2. crstEnter   → with nothing injected the tab now OPENS on the base
        creature in 3D rather than on an empty box.
     3. ctTool/ctOn → 'v_3d' is the 3D toggle (its real meaning), 'v_pin' is a
        real picture-in-picture of the untouched source, and 'v_base' opens the
        base-creature picker.
     4. ctSync/ctPreviewSoon → the colour part of the stack is mirrored onto the
        mesh as a per-vertex colour attribute, recomputed from the ORIGINAL
        colours every time (never accumulated). Textured meshes with no COLOR_0
        are tinted on material.color instead, and every material's emissive is
        multiplied by the same coat colour — the pufferball drives its face
        plate and its eyes through emissive, so without that they stayed yellow
        under a blue coat. Eye materials are excluded from the emissive pass.
     5. crst3dLoop  → replaced with a tick that also drives a THREE.AnimationMixer
        so a rigged base (Quaternius, Kenney) stands in its idle clip.

   Colour space: the CRST3 renderer is put into THREE.sRGBEncoding output here
   (the page's rig never set it, unlike every other studio). In r144 that makes
   materials, textures and vertex colours LINEAR, so every swatch that arrives
   as an sRGB hex from the toolbox goes through THREE.Color.convertSRGBToLinear()
   before it lands on anything. Skipping that is the washed-out-to-white bug.

   The 2D path is untouched: ctPreview still owns #crst-stage, and with
   #crst-3d hidden nothing in here runs.

   Geometry convention for the colour bands: every vertex is normalised once at
   load time into [0,1] over the whole model's bounding box — nx across, ny up,
   nz depth with +z taken as the FRONT (the glTF convention the pufferball and
   the Kenney pets both follow). That is an assumption, so it is MEASURED: when
   the bounding box is longer across X than across Z the body lies along X, and
   the two horizontal coordinates are swapped as they are stored so the bands
   below keep reading 'nz' as along-the-body. The legend chip says which. */

(function () {
  'use strict';
  if (typeof CRST3 === 'undefined' || typeof CT === 'undefined') return;

  /* ── state ────────────────────────────────────────────────────────────── */
  var CX = window.CRST3X = {
    model: null,        // THREE.Group (our wrapper) currently in the scene
    inner: null,        // the loaded glTF scene inside it — what the mixer drives
    parts: [],          // [{mesh, orig, norm, matCol, emis, map, eye, n}]
    url: '',            // the GLB url that produced `model`
    label: '',          // credit line for the hint
    loading: '',        // url in flight
    pip: false,         // picture-in-picture of the untouched source
    lastKey: '',        // signature of the last tint, to skip no-op repaints
    bases: null,        // the base list, when it came from our own fetch
    mixer: null,        // THREE.AnimationMixer for the idle clip, or null
    clip: '',           // the clip that is playing
    axis: 'z'           // which horizontal axis the bands run along
  };

  var PIN_KEY = 'crst.basecreature';
  var EYE_RE = /eye|pupil|iris/i;

  var BILLBOARD = crst3dLoad;          // the original, kept as the fallback
  var HOST_ID = 'crst-3d';

  /* #crst-3d carries no CSS rule of its own (only #cs-3d and #mvst-3d do), so
     its height is 0 and crst3dSize() bails out before the renderer is ever
     sized. Give it the same absolute box its sibling stage has. */
  function host() {
    var h = document.getElementById(HOST_ID);
    if (h && h.style.position !== 'absolute') {
      h.style.position = 'absolute';
      h.style.left = h.style.top = h.style.right = h.style.bottom = '0';
    }
    return h;
  }

  /* ── colour helpers ───────────────────────────────────────────────────── */
  /* Every swatch in the toolbox is an sRGB hex — that is what a colour picker
     hands you and what the 2D leg feeds Pillow. Everything in this file below
     this line is LINEAR, because the renderer encodes to sRGB on output (see
     rendererSRGB). One conversion, at the door. */
  var _CONV = new THREE.Color();
  function hex2rgb(s) {
    s = String(s || '').trim();
    var m = /^#?([0-9a-f]{6})$/i.exec(s);
    if (!m) return null;
    var n = parseInt(m[1], 16);
    _CONV.setRGB(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
    _CONV.convertSRGBToLinear();
    return [_CONV.r, _CONV.g, _CONV.b];
  }

  /* The page's own CRST3 rig never set an output encoding (#cs-3d, the arch
     viewer and the mesh studio all do). Without it a glTF's sRGB basecolor
     texture is decoded to linear and then written out raw — the model reads
     washed out and a tint cannot be judged. Set once, on the shared renderer. */
  function rendererSRGB() {
    var r = CRST3.renderer;
    if (!r || r.__crstSRGB) return;
    if (THREE.sRGBEncoding !== undefined && 'outputEncoding' in r)
      r.outputEncoding = THREE.sRGBEncoding;
    r.__crstSRGB = true;
  }
  function lum(r, g, b) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

  function rgb2hsl(r, g, b) {
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), h = 0, s = 0, l = (mx + mn) / 2;
    if (mx !== mn) {
      var d = mx - mn;
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      if (mx === r) h = (g - b) / d + (g < b ? 6 : 0);
      else if (mx === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h /= 6;
    }
    return [h, s, l];
  }
  function h2c(p, q, t) {
    if (t < 0) t += 1; if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  }
  function hsl2rgb(h, s, l) {
    if (s === 0) return [l, l, l];
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    return [h2c(p, q, h + 1 / 3), h2c(p, q, h), h2c(p, q, h - 1 / 3)];
  }

  /* ── the bands ────────────────────────────────────────────────────────── */
  /* cc_second 'where' → which normalised slab of the body it paints. The
     percentages are the brief's: underside 40 %, chest 35 % front, legs 25 %,
     face top 30 % front, back top 40 %, tail rear 30 % by depth. */
  function secondBand(where, nx, ny, nz) {
    switch (String(where || '').replace(/^the\s+/, '')) {
      case 'underside':        return ny <= 0.40;
      case 'chest and throat': return ny <= 0.35 && nz >= 0.50;
      case 'legs':             return ny <= 0.25;
      case 'face':             return ny >= 0.70 && nz >= 0.50;
      case 'back':             return ny >= 0.60;
      case 'tail':             return nz <= 0.30;
      default:                 return ny <= 0.40;
    }
  }
  /* cc_accent 'where' → the extreme 8 % (6 % for claws). */
  function accentBand(where, nx, ny, nz) {
    switch (String(where || '').replace(/^the\s+/, '')) {
      case 'tail tip':            return nz <= 0.08;
      case 'claws and horn tips': return ny <= 0.06 || ny >= 0.94;
      case 'inside of the ears':  return ny >= 0.92;
      case 'eye rings':           return ny >= 0.92 && nz >= 0.60;
      case 'spines':              return ny >= 0.92;
      case 'fins':                return Math.abs(nx - 0.5) >= 0.42;
      default:                    return ny >= 0.92;
    }
  }

  var MORPH = {
    'albino, white with red eyes':  '#f4f0ea',
    'melanistic, all black':        '#17130f',
    'leucistic, pale with dark eyes': '#e6dccf',
    'piebald':                      '#e9e2d5',
    'golden':                       '#d9a441'
  };

  /* ── which source the mesh should come from ───────────────────────────── */
  function baseList() {
    return (CT.ops && CT.ops.base_creatures) || CX.bases || [];
  }
  function pinnedId() {
    try { return window.localStorage.getItem(PIN_KEY) || ''; } catch (e) { return ''; }
  }
  /* The pinned base, else the first of the list. A pin that no longer names a
     base (the list is data, it can change under the browser) is not an error —
     it falls back rather than showing nothing. */
  function chosenBase() {
    var list = baseList(), pin = pinnedId(), i;
    if (!list.length) return null;
    for (i = 0; i < list.length; i++) if (list[i].id === pin) return list[i];
    return list[0];
  }

  function meshSource() {
    var f = CT.facts;
    if (f && f.mesh && f.mesh.glb_url) {
      return { url: f.mesh.glb_url,
               label: 'Own mesh: ' + (f.mesh.source || 'this creature')
                      + (f.mesh.licence ? ' · ' + f.mesh.licence : ''),
               own: true };
    }
    var b = chosenBase();
    if (b) return { url: b.url, label: 'Base creature: ' + b.lb, own: false };
    return null;
  }

  /* ── load a GLB ───────────────────────────────────────────────────────── */
  function dropModel() {
    if (CX.mixer) { try { CX.mixer.stopAllAction(); } catch (e) {} }
    CX.mixer = null; CX.clip = '';
    if (!CX.model) { CX.inner = null; CX.parts = []; CX.lastKey = ''; return; }
    CRST3.scene.remove(CX.model);
    CX.model.traverse(function (o) {
      if (o.isMesh) {
        if (o.geometry) o.geometry.dispose();
        if (o.material && o.material.dispose) o.material.dispose();
      }
    });
    CX.model = null; CX.inner = null; CX.parts = []; CX.lastKey = '';
  }

  function adoptModel(root) {
    /* one pass: own the materials (a glTF material is shared between meshes and
       we are about to recolour one of them), remember the original vertex
       colours and the original emissive, and normalise every vertex into the
       model's bbox.

       The fit goes on a WRAPPER group rather than on the glTF scene itself: a
       rigged base's idle clip animates nodes inside that scene, and scaling the
       node a track writes to is a fight the clip wins. */
    root.updateMatrixWorld(true);
    var box = new THREE.Box3().setFromObject(root);
    var size = box.getSize(new THREE.Vector3());
    var hgt = size.y || size.x || 1;
    var k = 2.2 / hgt;                       // the billboard's height, kept
    var ctr = box.getCenter(new THREE.Vector3());

    var wrap = new THREE.Group();
    wrap.add(root);
    wrap.scale.setScalar(k);
    wrap.position.copy(ctr).multiplyScalar(-k);
    wrap.updateMatrixWorld(true);

    /* which way the body runs. A quadruped is longer nose-to-tail than it is
       wide, so the longer horizontal extent IS the body axis; +z is only the
       usual answer, not a law (the Smithsonian scan is +x). 1.05 keeps a body
       that is square in plan on the documented default. */
    CX.axis = (size.x > size.z * 1.05) ? 'x' : 'z';
    var swap = CX.axis === 'x';

    var parts = [];
    root.traverse(function (o) {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
      var g = o.geometry, pos = g.attributes.position, n = pos.count;

      if (!o.material) o.material = new THREE.MeshStandardMaterial({ color: 0xbfc6cf, roughness: 0.8 });
      else o.material = o.material.clone();
      if (o.material.side !== undefined) o.material.side = THREE.DoubleSide;

      var ca = g.attributes.color, orig = null;
      if (ca) {
        orig = new Float32Array(n * 3);
        for (var i = 0; i < n; i++) {
          orig[i * 3] = ca.getX(i); orig[i * 3 + 1] = ca.getY(i); orig[i * 3 + 2] = ca.getZ(i);
        }
        o.material.vertexColors = true;      // the TRELLIS recon's COLOR_0
      }

      var norm = new Float32Array(n * 3);
      var v = new THREE.Vector3();
      for (var j = 0; j < n; j++) {
        v.fromBufferAttribute(pos, j).applyMatrix4(o.matrixWorld);
        var ax = size.x ? (v.x / (size.x * k) + 0.5) : 0.5;
        var az = size.z ? (v.z / (size.z * k) + 0.5) : 0.5;
        norm[j * 3]     = swap ? az : ax;    // across the body
        norm[j * 3 + 1] = size.y ? (v.y / (size.y * k) + 0.5) : 0.5;
        norm[j * 3 + 2] = swap ? ax : az;    // along the body, 1 = front
      }
      var mc = o.material.color ? o.material.color.clone() : new THREE.Color(0xffffff);
      parts.push({
        mesh: o, orig: orig, norm: norm, matCol: mc, n: n,
        /* the pufferball's face plate and eyes are lit through emissive, so a
           coat colour that only touches material.color leaves them yellow */
        emis: o.material.emissive ? o.material.emissive.clone() : null,
        map: !!o.material.map,
        eye: EYE_RE.test(o.name || '') || EYE_RE.test(o.material.name || '')
      });
    });

    CX.model = wrap; CX.inner = root; CX.parts = parts;
    CRST3.scene.add(wrap);

    /* the stock rig has one hemisphere + one directional light; a solid body
       needs a fill from the camera side or half of it reads as a silhouette */
    if (!CRST3.__fill) {
      CRST3.__fill = new THREE.DirectionalLight(0xffffff, 0.45);
      CRST3.__fill.position.set(-1.2, 0.6, 2.2);
      CRST3.scene.add(CRST3.__fill);
    }

    frame(size.clone().multiplyScalar(k));
    return parts.length;
  }

  /* the billboard sat the camera at hgt*1.35, which already clipped a 2.2-unit
     plane at this 35° FOV; a solid body is wider than it is tall as often as
     not, so fit BOTH axes and leave a margin. */
  function frame(size) {
    var cam = CRST3.camera;
    var t = Math.tan((cam.fov * Math.PI / 180) / 2);
    var asp = cam.aspect || 1;
    var d = Math.max((size.y / 2) / t, (size.x / 2) / (t * asp), (size.z / 2) / (t * asp));
    d = Math.max(1.2, d * 1.45 + size.z / 2);
    CRST3.controls.maxDistance = Math.max(CRST3.controls.maxDistance, d * 1.9);
    var dir = new THREE.Vector3(0.38, 0.20, 0.90).normalize().multiplyScalar(d);
    cam.position.copy(dir);
    CRST3.controls.target.set(0, 0, 0);
    CRST3.controls.update();
    CX.dist = d;
  }

  /* ── the idle clip ────────────────────────────────────────────────────── */
  /* Every Quaternius animal and every Kenney cube-pet ships a clip list; the
     one worth standing in is the idle. Anything else (Attack, Death, Gallop) is
     a choice, not a default, so a model with no idle stays in its rest pose. */
  function playIdle(gltf, root) {
    var clips = (gltf && gltf.animations) || [], i, idle = null;
    /* the plain 'Idle' first (an exporter may reorder the clip list, and
       Idle_2 / Idle_HeadLow are different stances), else the first idle-ish */
    for (i = 0; i < clips.length; i++) {
      if (/^idle$/i.test(clips[i].name || '')) { idle = clips[i]; break; }
    }
    for (i = 0; !idle && i < clips.length; i++) {
      if (/idle/i.test(clips[i].name || '')) { idle = clips[i]; break; }
    }
    if (!idle) return '';
    CX.mixer = new THREE.AnimationMixer(root);
    CX.mixer.clipAction(idle).play();
    CX.clip = idle.name || 'idle';
    return CX.clip;
  }

  function loadMesh(src) {
    crst3dEnsure(); if (CRST3.failed) return;
    rendererSRGB();
    host(); crst3dSize();

    var s = meshSource();
    if (!s || typeof THREE.GLTFLoader !== 'function') { BILLBOARD(src); return; }
    if (CX.url === s.url && CX.model) { CX.label = s.label; hintChip(); crst3dLoop(); return; }
    if (CX.loading === s.url) return;
    CX.loading = s.url;

    new THREE.GLTFLoader().load(s.url, function (gltf) {
      CX.loading = '';
      try {
        /* the billboard, if one is up, is not what we are looking at any more */
        if (CRST3.plane) {
          CRST3.scene.remove(CRST3.plane);
          CRST3.plane.geometry.dispose(); CRST3.plane.material.dispose();
          CRST3.plane = null; CRST3.loadedSrc = '';
        }
        dropModel();
        var inner = gltf.scene || gltf.scenes[0];
        var n = adoptModel(inner);
        CX.url = s.url; CX.label = s.label;
        if (!n) { BILLBOARD(src); return; }
        playIdle(gltf, inner);
        tint(true);
        /* shell fur for a base that ships a fur map (creature_fur.js) */
        if (window.CRST3FUR && !s.own) {
          try { CRST3FUR.attach(CX, chosenBase()); } catch (e) { console.error('creature_fur', e); }
        }
        hintChip(); legend();
        crst3dLoop();
      } catch (e) {
        console.error('creature_3d adopt', e);
        BILLBOARD(src);
      }
    }, null, function (e) {
      CX.loading = '';
      console.error('creature_3d GLTFLoader', s.url, e);
      BILLBOARD(src);                       // the hero PNG on its plane, as before
    });
  }

  /* ── the tint pass ────────────────────────────────────────────────────── */
  function colourPlan() {
    var rows = (typeof ctEffective === 'function' ? ctEffective() : []).filter(function (r) { return r.on; });
    var p = { base: null, second: null, accent: null, tint: null, sat: 0, psat: 0,
              bright: 0, contrast: 0, hue: 0, temp: 0, rough: null, any: false };
    rows.forEach(function (r) {
      var q = r.p || {};
      switch (r.op) {
        case 'cc_albino': if (q.v && q.v !== 'none' && MORPH[q.v]) { p.base = hex2rgb(MORPH[q.v]); p.any = true; } break;
        case 'cc_base':   if (hex2rgb(q.col)) { p.base = hex2rgb(q.col); p.any = true; } break;
        case 'cc_second': if (hex2rgb(q.col)) { p.second = { c: hex2rgb(q.col), w: q.where }; p.any = true; } break;
        case 'cc_accent': if (hex2rgb(q.col)) { p.accent = { c: hex2rgb(q.col), w: q.where }; p.any = true; } break;
        case 'px_tint':   if (hex2rgb(q.col)) { p.tint = { c: hex2rgb(q.col), a: (+q.a || 0) / 100 }; p.any = true; } break;
        case 'cc_sat':    p.sat = +q.v || 0; if (p.sat) p.any = true; break;
        case 'px_sat':    p.psat = +q.v || 0; if (p.psat) p.any = true; break;
        case 'px_bright': p.bright = +q.v || 0; if (p.bright) p.any = true; break;
        case 'px_contrast': p.contrast = +q.v || 0; if (p.contrast) p.any = true; break;
        case 'px_hue':    p.hue = +q.a || 0; if (p.hue) p.any = true; break;
        case 'px_temp':   p.temp = +q.v || 0; if (p.temp) p.any = true; break;
        case 'cs_fur':    p.rough = { none: 0.5, short: 0.75, medium: 0.85 }[q.len];
                          if (p.rough === undefined) p.rough = 0.95;
                          p.any = true; break;
      }
    });
    return p;
  }

  /* The one multiply a WHOLE material gets — for the emissive channel and for a
     textured mesh's material.color, neither of which can carry a per-vertex
     band. It follows the base coat colour, then px_tint's blend, then
     temperature: the same chain a vertex walks, minus the bands and the
     per-vertex shading term. */
  function matMul(p) {
    var r = 1, g = 1, b = 1;
    if (p.base) { r = p.base[0]; g = p.base[1]; b = p.base[2]; }
    if (p.tint && p.tint.a > 0) {
      var a = p.tint.a;
      r = r * (1 - a) + r * p.tint.c[0] * a;
      g = g * (1 - a) + g * p.tint.c[1] * a;
      b = b * (1 - a) + b * p.tint.c[2] * a;
    }
    if (p.temp) { var tw = p.temp / 100; r *= 1 + 0.35 * tw; b *= 1 - 0.35 * tw; }
    return [clamp01(r), clamp01(g), clamp01(b)];
  }

  function tint(force) {
    if (!CX.parts.length) return;
    var p = colourPlan();
    var key = JSON.stringify(p);
    if (!force && key === CX.lastKey) return;
    CX.lastKey = key;

    var hueRot = p.hue / 360, satK = 1 + (p.sat + p.psat) / 100;
    var brK = 1 + p.bright / 100, ctK = 1 + p.contrast / 100;
    var tw = p.temp / 100;
    var mul = matMul(p);
    CX.tinted = []; CX.excluded = [];        // what the report/legend can read

    CX.parts.forEach(function (part) {
      var m = part.mesh, g = m.geometry, n = part.n;
      var nm = m.material.name || m.name || '(unnamed)';

      if (p.rough !== null && p.rough !== undefined && m.material.roughness !== undefined)
        m.material.roughness = p.rough;

      if (!p.any) {                         // nothing colour-ish in the stack
        if (part.orig) {
          writeColours(g, part.orig, n);
          m.material.vertexColors = true;
        } else if (g.attributes.color) {
          g.deleteAttribute('color');
          m.material.vertexColors = false;
        }
        if (m.material.color) m.material.color.copy(part.matCol);
        if (part.emis) m.material.emissive.copy(part.emis);
        m.material.needsUpdate = true;
        return;
      }

      /* emissive first, because it is the channel that ignored the coat: a face
         plate or a glow reads as its own colour whatever material.color says.
         Eyes keep theirs — a blue creature does not get blue pupils. */
      if (part.emis) {
        if (part.eye) {
          m.material.emissive.copy(part.emis);
          if (CX.excluded.indexOf(nm) < 0) CX.excluded.push(nm);
        } else {
          m.material.emissive.setRGB(part.emis.r * mul[0],
                                     part.emis.g * mul[1],
                                     part.emis.b * mul[2]);
          if ((part.emis.r || part.emis.g || part.emis.b) && CX.tinted.indexOf(nm) < 0)
            CX.tinted.push(nm);
        }
      }

      /* a textured mesh with no COLOR_0: the map carries the look, so the coat
         multiplies material.color and the texture keeps its detail. Painting a
         flat vertex colour over it would throw the texture away. */
      if (!part.orig && part.map) {
        if (g.attributes.color) g.deleteAttribute('color');
        m.material.vertexColors = false;
        if (m.material.color)
          m.material.color.setRGB(clamp01(part.matCol.r * mul[0]),
                                  clamp01(part.matCol.g * mul[1]),
                                  clamp01(part.matCol.b * mul[2]));
        m.material.needsUpdate = true;
        return;
      }

      /* the base we recolour FROM: the original vertex colours, or the material's
         own colour when the mesh has none. Its mean luminance is the reference,
         so a recolour keeps the model's shading instead of flattening it. */
      var src = part.orig, ref = 0.5, i;
      if (src) {
        var acc = 0;
        for (i = 0; i < n; i++) acc += lum(src[i * 3], src[i * 3 + 1], src[i * 3 + 2]);
        ref = acc / n || 0.5;
      } else {
        ref = lum(part.matCol.r, part.matCol.g, part.matCol.b) || 0.5;
      }

      var out = new Float32Array(n * 3);
      for (i = 0; i < n; i++) {
        var or_, og, ob;
        if (src) { or_ = src[i * 3]; og = src[i * 3 + 1]; ob = src[i * 3 + 2]; }
        else { or_ = part.matCol.r; og = part.matCol.g; ob = part.matCol.b; }

        var nx = part.norm[i * 3], ny = part.norm[i * 3 + 1], nz = part.norm[i * 3 + 2];
        var pick = p.base;
        if (p.second && secondBand(p.second.w, nx, ny, nz)) pick = p.second.c;
        if (p.accent && accentBand(p.accent.w, nx, ny, nz)) pick = p.accent.c;

        var r, gg, b;
        if (pick) {
          var sh = clamp01(lum(or_, og, ob) / (ref || 0.5)) * 1.0;
          sh = 0.45 + 0.75 * sh;            // keep the shading, never crush it
          r = pick[0] * sh; gg = pick[1] * sh; b = pick[2] * sh;
        } else { r = or_; gg = og; b = ob; }

        if (p.tint && p.tint.a > 0) {       // Image.blend(rgb, multiply(rgb, solid), a)
          var a = p.tint.a;
          r = r * (1 - a) + r * p.tint.c[0] * a;
          gg = gg * (1 - a) + gg * p.tint.c[1] * a;
          b = b * (1 - a) + b * p.tint.c[2] * a;
        }
        if (tw) { r *= 1 + 0.35 * tw; b *= 1 - 0.35 * tw; }
        if (ctK !== 1) { r = 0.5 + (r - 0.5) * ctK; gg = 0.5 + (gg - 0.5) * ctK; b = 0.5 + (b - 0.5) * ctK; }
        if (brK !== 1) { r *= brK; gg *= brK; b *= brK; }
        if (satK !== 1 || hueRot) {
          var h = rgb2hsl(clamp01(r), clamp01(gg), clamp01(b));
          var c2 = hsl2rgb((h[0] + hueRot + 1) % 1, clamp01(h[1] * satK), h[2]);
          r = c2[0]; gg = c2[1]; b = c2[2];
        }
        out[i * 3] = clamp01(r); out[i * 3 + 1] = clamp01(gg); out[i * 3 + 2] = clamp01(b);
      }

      writeColours(g, out, n);
      m.material.vertexColors = true;
      if (m.material.color) m.material.color.setRGB(1, 1, 1);   // let the attribute speak
      m.material.needsUpdate = true;
    });
  }

  function writeColours(g, arr, n) {
    var a = g.attributes.color;
    if (a && a.itemSize === 3 && a.count === n && a.array && a.array.length === arr.length
        && a.array.set && a.array.BYTES_PER_ELEMENT === 4) {
      a.array.set(arr); a.needsUpdate = true;
    } else {
      g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
    }
  }

  /* ── chips ────────────────────────────────────────────────────────────── */
  function hintChip() {
    var h = document.getElementById('crst-hint');
    if (!h || !CT.three) return;
    h.textContent = 'drag = orbit · wheel = zoom · right-click = centre' + (CX.label ? '  ·  ' + CX.label : '');
  }
  function legend() {
    var h = host(); if (!h) return;
    var el = document.getElementById('crst-3dleg');
    if (!el) {
      el = document.createElement('div');
      el.id = 'crst-3dleg';
      el.style.cssText = 'position:absolute;left:10px;top:10px;z-index:4;pointer-events:none;'
        + 'font-size:10.5px;line-height:1.35;color:var(--muted);background:rgba(18,20,24,.72);'
        + 'border:1px solid rgba(255,255,255,.10);border-radius:6px;padding:4px 8px;max-width:330px;';
      h.appendChild(el);
    }
    el.textContent = '3D mirrors: base, second, accent, tint, saturation — '
      + 'generative ops render only in the picture'
      + '  ·  bands: ' + CX.axis + '-axis'
      + (CX.clip ? '  ·  clip: ' + CX.clip : '');
  }
  function emptyHint(on) {
    var e = document.getElementById('crst-empty'); if (!e) return;
    if (on) {
      if (!e.dataset.sx) { e.dataset.sx = e.innerHTML; e.dataset.sxs = e.getAttribute('style') || ''; }
      e.innerHTML = 'Base creature — <b>Inject Creature</b> to work on one of yours';
      /* one line at the foot of the stage, not a full-bleed flex box over the
         model — and never eating an orbit drag */
      e.style.cssText = 'position:absolute;left:0;right:0;bottom:8px;top:auto;display:block;'
        + 'text-align:center;pointer-events:none;';
    } else if (e.dataset.sx !== undefined) {
      e.innerHTML = e.dataset.sx;
      e.setAttribute('style', e.dataset.sxs || '');
      delete e.dataset.sx; delete e.dataset.sxs;
    }
  }

  /* ── picture-in-picture of the untouched source ───────────────────────── */
  function pipUrl() {
    if (!CT.facts || !CT.cat || !CT.name) return '';
    return '/inspect/creature/fx/frame?id=' + encodeURIComponent(CT.facts.id)
      + '&cat=' + encodeURIComponent(CT.cat)
      + '&f=' + encodeURIComponent(CT.name)
      + '&s=' + ctB64([])                   // an EMPTY stack: the source itself
      + '&view=rgb&w=720';
  }
  function pipDraw() {
    var st = document.getElementById('crst-stage');
    var wrap = st && st.parentNode; if (!wrap) return;
    var el = document.getElementById('crst-pip');
    if (!CX.pip) { if (el) el.remove(); return; }
    var u = pipUrl();
    if (!u) { CX.pip = false; if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('div');
      el.id = 'crst-pip';
      el.style.cssText = 'position:absolute;left:14px;bottom:34px;z-index:6;width:180px;'
        + 'border:1px solid rgba(255,255,255,.18);border-radius:7px;overflow:hidden;'
        + 'background:#14161a;box-shadow:0 6px 18px rgba(0,0,0,.5);pointer-events:none;';
      el.innerHTML = '<img style="display:block;width:100%">'
        + '<div style="font-size:9.5px;text-align:center;padding:2px 0 3px;color:var(--muted)">'
        + 'pinned source</div>';
      wrap.appendChild(el);
    }
    el.querySelector('img').src = u;
  }

  /* ── the base-creature picker ─────────────────────────────────────────── */
  /* ctPanelOpen's kind→renderer table is a literal inside the page, so a new
     panel is added by wrapping the function rather than by editing the table.
     Everything else about the panel (the #crst-panel shell, the .crst-h header,
     the .crst-note prose) is the page's own idiom. */
  function basesPanel(bd) {
    var list = baseList(), pin = pinnedId();
    if (!list.length) {
      bd.innerHTML = '<div class="crst-note">No base creatures. '
        + 'data/assets/mesh_packs/quaternius_animals/BASES.json is missing or empty — '
        + 'the studio falls back to the flat picture.</div>';
      return;
    }
    var h = '<div class="crst-h"><span>Base creature</span>'
      + '<span class="n">' + list.length + '</span><span class="sp"></span>'
      + (pin ? '<span style="color:var(--acc)">pinned</span>' : '<span class="sc">first of the list</span>')
      + '</div>'
      + '<div class="crst-note">Third-party CC0 stand-ins — none of them ours. This is what '
      + 'the pane shows while nothing is injected; a creature with its own mesh always shows '
      + 'that instead. The pin is kept in this browser only.</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px">';
    list.forEach(function (b) {
      var on = b.id === pin;
      h += '<div style="width:104px;border-radius:7px;padding:5px;cursor:pointer;'
        + 'background:rgba(255,255,255,.03);border:1px solid '
        + (on ? 'var(--acc)' : 'rgba(255,255,255,.10)') + '"'
        + ' data-base="' + esc(b.id) + '" title="' + esc(b.lb) + '"'
        + ' onclick="CRST3X.use(\'' + esc(b.id) + '\')">'
        + (b.prev
            ? '<img src="' + esc(b.prev) + '" alt="" style="display:block;width:100%;'
              + 'border-radius:4px;background:#14161a" onerror="this.style.display=\'none\'">'
            : '<div style="height:52px;border-radius:4px;background:#14161a;display:flex;'
              + 'align-items:center;justify-content:center;font-size:9px;color:var(--muted)">'
              + 'no preview</div>')
        + '<div style="font-size:9.5px;line-height:1.25;margin-top:4px;'
        + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(b.lb) + '</div>'
        + '<button type="button" class="crst-usebase" style="margin-top:4px;width:100%;'
        + 'font-size:9.5px;padding:2px 0"'
        + ' onclick="event.stopPropagation();CRST3X.use(\'' + esc(b.id) + '\')">'
        + (on ? 'Pinned' : 'Use') + '</button></div>';
    });
    h += '</div><button type="button" id="crst-unpin" style="font-size:10px;padding:3px 10px"'
      + (pin ? '' : ' disabled') + ' onclick="CRST3X.unpin()">Unpin</button>';
    bd.innerHTML = h;
  }

  function repaintPanel() {
    if (CT.panel !== 'bases') return;
    var bd = document.getElementById('crst-panel-bd');
    if (bd) basesPanel(bd);
  }

  CX.use = function (id) {
    var list = baseList(), i, hit = null;
    for (i = 0; i < list.length; i++) if (list[i].id === id) hit = list[i];
    if (!hit) return;
    try { window.localStorage.setItem(PIN_KEY, id); } catch (e) {}
    if (!CT.three) { ct3dToggle(); } else { loadMesh(''); }
    repaintPanel();
    if (typeof ctRenderBars === 'function') ctRenderBars();
    if (typeof ctToast === 'function') ctToast(hit.lb);
  };
  CX.unpin = function () {
    try { window.localStorage.removeItem(PIN_KEY); } catch (e) {}
    loadMesh('');
    repaintPanel();
    if (typeof ctRenderBars === 'function') ctRenderBars();
  };

  /* ── wrap the page globals ────────────────────────────────────────────── */
  window.crst3dLoad = function (src) { loadMesh(src); };
  window.crst3dTint = function () { tint(true); };

  var _sync = ctSync;
  window.ctSync = function () { _sync.apply(this, arguments); tint(false); };

  var _soon = ctPreviewSoon;
  window.ctPreviewSoon = function () { _soon.apply(this, arguments); tint(false); };

  var _banner = ctBanner;
  window.ctBanner = function () { _banner.apply(this, arguments); hintChip(); };

  var _on = ctOn;
  window.ctOn = function (o) {
    if (o && o.id === 'v_3d') return !!CT.three;
    if (o && o.id === 'v_pin') return !!CX.pip;
    if (o && o.id === 'v_base') return !!pinnedId();
    return _on.apply(this, arguments);
  };

  var _panel = ctPanelOpen;
  window.ctPanelOpen = function (kind) {
    if (kind !== 'bases') return _panel.apply(this, arguments);
    var el = document.getElementById('crst-panel');
    var bd = document.getElementById('crst-panel-bd');
    var ti = document.getElementById('crst-panel-title');
    if (!el || !bd || !ti) return;
    CT.panel = 'bases'; CT.panelArg = {};
    el.classList.add('on');
    ti.textContent = 'Base creature';
    basesPanel(bd);
  };

  /* the stock loop has no clock and no mixer; a rigged base needs both, and the
     page calls crst3dLoop by name from four places so replacing it is enough */
  var _clock = null;
  window.crst3dLoop = function () {
    if (!CRST3.renderer || CRST3.raf) return;
    _clock = _clock || new THREE.Clock();
    _clock.getDelta();
    (function tick() {
      CRST3.raf = requestAnimationFrame(tick);
      var dt = _clock.getDelta();
      if (CX.mixer) CX.mixer.update(dt);
      CRST3.controls.update();
      CRST3.renderer.render(CRST3.scene, CRST3.camera);
    })();
  };

  var _toggle = ct3dToggle;
  window.ct3dToggle = function () {
    host();
    var going = !CT.three;
    if (going) { crst3dEnsure(); if (!CRST3.failed) loadMesh(''); }
    _toggle.apply(this, arguments);
    if (CT.three) { crst3dSize(); legend(); hintChip(); }
  };

  var _tool = ctTool;
  window.ctTool = function (id) {
    if (id === 'v_3d') {                    // works with nothing injected: that is the point
      ctFlash(id); ct3dToggle(); return;
    }
    if (id === 'v_pin') {
      if (!ctLoaded()) { ctToast('Pin source needs a creature — inject one first.', true); return; }
      CX.pip = !CX.pip; ctFlash(id); pipDraw(); ctRenderBars(); return;
    }
    if (id === 'v_base') {                  // also works with nothing injected
      ctFlash(id); ctPanelOpen('bases'); return;
    }
    return _tool.apply(this, arguments);
  };

  var _preview = ctPreview;
  window.ctPreview = function () { var r = _preview.apply(this, arguments); pipDraw(); return r; };

  var _facts = ctFacts;
  window.ctFacts = function () {
    var pr = _facts.apply(this, arguments);
    if (pr && pr.then) pr.then(function (d) {
      if (d && CT.three) loadMesh('');      // the creature's own mesh, if it has one
      return d;
    });
    return pr;
  };

  var _enter = crstEnter;
  window.crstEnter = function () {
    _enter.apply(this, arguments);
    host();
    if (CRST.id) { if (CT.three) { loadMesh(''); crst3dSize(); legend(); } return; }
    /* nothing injected: the base creature is what the operator sees first */
    emptyHint(true);
    var boot = function () {
      crst3dEnsure(); if (CRST3.failed) return;
      if (!CT.three) {
        CT.three = true;
        document.getElementById('crst-3d').style.display = 'block';
        document.getElementById('crst-stage').style.display = 'none';
        ctRenderBars();
      }
      crst3dSize(); loadMesh(''); legend(); ctBanner();
    };
    if (CT.ops) boot();
    else ctLoadOps().then(boot, boot);
  };

  var _loadCreature = crstLoadCreature;
  window.crstLoadCreature = function (c) {
    emptyHint(false);
    var was = CT.three;                     // keep whatever view mode we were in
    _loadCreature.apply(this, arguments);
    CT.three = was;
    document.getElementById('crst-3d').style.display = was ? 'block' : 'none';
    document.getElementById('crst-stage').style.display = was ? 'none' : 'flex';
  };

  /* the base list is on CT.ops, but the tab can open before ctLoadOps resolves */
  if (typeof api === 'function') {
    api('/inspect/api/studio/creature/bases').then(function (d) {
      if (d && d.bases) CX.bases = d.bases;
    }).catch(function () {});
  }

  window.SX = window.SX || {};
  (window.SX.ready = window.SX.ready || []).push('creature_3d');
})();
