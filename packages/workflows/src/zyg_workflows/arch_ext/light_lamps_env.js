// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* light_lamps_env — Lighting: the environment, the lamps and their photometry.
   Wires three dock icons of the Light section that were placeholders:

     l_hdri  Environment — a photographed sky as the light source and as what
             the glass reflects. Cycles off -> each bundled 1k HDRI -> off.
     l_lamp  Lights — places point / spot / area lights for an interior after
             dark. Each record is a small pickable marker; the REAL three.js
             light is kept in step with it every frame.
     l_ies   Photometric — reads an IESNA LM-63 profile, draws its polar
             intensity curve and gives the selected spot that luminaire's
             measured beam angle and flux instead of a guessed cone.

   Vendored three r144 examples (MIT), loaded on demand from AR_EXT.ready:
     vendor/three/RGBELoader.js               (.hdr -> THREE.DataTexture)
     vendor/three/RectAreaLightUniformsLib.js (RectAreaLight needs its LTC LUTs)
   Assets, with their own License.txt + PROVENANCE.json, served by
   arch_server_ext/light_lamps_env.py:
     data/assets/mesh_packs/hdri/*.hdr   CC0 1.0, Poly Haven
     data/assets/mesh_packs/ies/*.ies    MIT, three.js examples/ies

   THE RECORD IS THE MARKER, THE LIGHT FOLLOWS IT. A light kind's geometry is a
   0.12 m marker CENTRED ON THE RECORD ORIGIN (not bottom-at-y=0 like the solid
   kinds), because the record's own x/y/z is where the photons come from: the
   THREE light sits exactly at the record's world position, so what the outliner
   says and what the renderer does are the same number. Parameters only in
   rec.p — the light itself lives in a Map keyed by record id and is created,
   moved, recoloured and removed by the ticks hook. */
(function(){
  var FAM = 'light_lamps_env';
  var API = '/inspect/api/architecture/ext/' + FAM + '/';
  var KINDS = {light_point: 1, light_spot: 1, light_area: 1};
  var LABEL = {light_point: 'Point light', light_spot: 'Spot light', light_area: 'Area light'};
  var DEFAULTS = {
    light_point: {w: 12, r: 8, col: '#ffe9c4'},
    light_spot:  {w: 20, r: 12, angle: 35, pen: 0.3, col: '#ffe9c4'},
    light_area:  {w: 30, x: 1.0, z: 0.6, col: '#ffe9c4'}
  };
  var CAP = 32;                     /* the scene's light budget — a forward renderer recompiles every material past it */
  var MARKER_MAT = 'mat_plaster';   /* the brightest preset the studio ships; the marker is a fitting, not a surface */
  var LIGHTS = {};                  /* rec.id -> {kind, light, target} — the only place a THREE light is held */
  var CACHE = {hdri: null, ies: null};
  var SCRIPTS = {};

  function num(v, d){ v = Number(v); return isFinite(v) ? v : d; }
  function clamp(v, lo, hi){ return v < lo ? lo : (v > hi ? hi : v); }
  function isLight(kind){ return !!KINDS[kind]; }

  /* watts-ish -> three.js intensity. A profiled luminaire answers with its
     MEASURED flux instead of the record's nominal wattage, which is the whole
     point of loading an IES file. */
  function intensityOf(p){
    var lm = num(p && p.ies_lm, 0);
    if(lm > 0) return clamp(lm / 200, 0.05, 20);
    return clamp(num(p && p.w, 12) / 10, 0.01, 20);
  }

  /* ── geometry: the pickable marker, centred on the record origin ───────── */
  AR_EXT.geom.light_point = function(p, k){
    return [{g: new k.THREE.SphereGeometry(0.06, 16, 10), sub: MARKER_MAT}];
  };
  AR_EXT.geom.light_spot = function(p, k){
    /* a cone hanging under the origin, its mouth as wide as the beam */
    var h = 0.18, a = clamp(k.num(p.angle, 35), 3, 80) * Math.PI / 180;
    var g = new k.THREE.ConeGeometry(clamp(h * Math.tan(a), 0.02, 0.5), h, 18, 1, true);
    g.translate(0, -h / 2, 0);
    return [{g: g, sub: MARKER_MAT}];
  };
  AR_EXT.geom.light_area = function(p, k){
    var w = clamp(k.num(p.x, 1.0), 0.05, 20), d = clamp(k.num(p.z, 0.6), 0.05, 20);
    return [{g: k.box(w, 0.03, d, 0, 0, 0), sub: MARKER_MAT}];
  };
  AR_EXT.label.light_point = LABEL.light_point;
  AR_EXT.label.light_spot = LABEL.light_spot;
  AR_EXT.label.light_area = LABEL.light_area;

  /* ── vendored three modules, loaded once, on demand ───────────────────── */
  function need(file, has){
    if(has()) return Promise.resolve(true);
    if(SCRIPTS[file]) return SCRIPTS[file];
    SCRIPTS[file] = new Promise(function(res, rej){
      var s = document.createElement('script');
      s.src = 'vendor/three/' + file + '.js';
      s.onload = function(){ has() ? res(true) : rej(new Error(file + ' loaded but did not define its class')); };
      s.onerror = function(){ rej(new Error('could not load vendor/three/' + file + '.js')); };
      document.head.appendChild(s);
    });
    return SCRIPTS[file];
  }
  function needRGBE(){ return need('RGBELoader', function(){ return !!(window.THREE && THREE.RGBELoader); }); }
  function needRectArea(){
    return need('RectAreaLightUniformsLib', function(){ return !!(window.THREE && THREE.RectAreaLightUniformsLib); })
      .then(function(){ if(!AR._lleRectInit){ THREE.RectAreaLightUniformsLib.init(); AR._lleRectInit = 1; } return true; });
  }

  /* ── document state ───────────────────────────────────────────────────── */
  function state(){
    AR.doc = AR.doc || {};
    AR.doc.ext = AR.doc.ext || {};
    AR.doc.ext[FAM] = AR.doc.ext[FAM] || {};
    return AR.doc.ext[FAM];
  }

  /* ── the light map: records in, THREE lights out, every frame ─────────── */
  function makeLight(rec){
    var e = {kind: rec.kind, light: null, target: null};
    if(rec.kind === 'light_point'){
      e.light = new THREE.PointLight(0xffffff, 1, 8);
    }else if(rec.kind === 'light_spot'){
      e.light = new THREE.SpotLight(0xffffff, 1, 12, 0.6, 0.3, 1);
      e.target = new THREE.Object3D();
      AR.scene.add(e.target);
      e.light.target = e.target;
    }else{
      e.light = new THREE.RectAreaLight(0xffffff, 1, 1, 1);
      needRectArea().catch(function(err){ console.error('arch_ext ' + FAM, err); });
    }
    e.light.userData.arId = rec.id;
    e.light.userData.lle = 1;
    AR.scene.add(e.light);
    return e;
  }
  function dropLight(id){
    var e = LIGHTS[id];
    if(!e) return;
    if(e.light){ AR.scene.remove(e.light); if(e.light.dispose) e.light.dispose(); }
    if(e.target) AR.scene.remove(e.target);
    delete LIGHTS[id];
  }
  var _pos = null, _quat = null, _scl = null, _dir = null;
  function syncLight(e, rec){
    if(!_pos){ _pos = new THREE.Vector3(); _quat = new THREE.Quaternion(); _scl = new THREE.Vector3(); _dir = new THREE.Vector3(); }
    rec.node.updateMatrixWorld(true);
    rec.node.matrixWorld.decompose(_pos, _quat, _scl);
    var p = rec.p || {}, L = e.light;
    L.position.copy(_pos);
    L.color.set(String(p.col || '#ffe9c4'));
    L.intensity = intensityOf(p);
    if(rec.kind === 'light_point'){
      L.distance = clamp(num(p.r, 8), 0, 500);
    }else if(rec.kind === 'light_spot'){
      L.distance = clamp(num(p.r, 12), 0, 500);
      L.angle = clamp(num(p.angle, 35), 1, 89) * Math.PI / 180;
      L.penumbra = clamp(num(p.pen, 0.3), 0, 1);
      /* aim 2 m along the record's own -Y, so rx/rz tilt the beam and ry spins it */
      _dir.set(0, -1, 0).applyQuaternion(_quat).multiplyScalar(2);
      e.target.position.copy(_pos).add(_dir);
      e.target.updateMatrixWorld(true);
    }else{
      L.width = clamp(num(p.x, 1.0), 0.05, 20);
      L.height = clamp(num(p.z, 0.6), 0.05, 20);
      L.lookAt(_pos.x, _pos.y - 1, _pos.z);   /* a RectAreaLight emits along its own -Z: face it at the floor */
    }
  }
  function lleTick(){
    if(!AR || !AR.scene) return;
    var seen = {}, n = 0, i, o;
    for(i = 0; i < AR.objs.length; i++){
      o = AR.objs[i];
      if(!isLight(o.kind) || o.hidden || !o.node) continue;
      if(n >= CAP) break;                     /* over the budget: the record stays, the light does not */
      n++;
      seen[o.id] = 1;
      var e = LIGHTS[o.id];
      if(e && e.kind !== o.kind){ dropLight(o.id); e = null; }
      if(!e) e = LIGHTS[o.id] = makeLight(o);
      try{ syncLight(e, o); }catch(err){ /* a half-built record on the frame it is created */ }
    }
    for(var id in LIGHTS) if(!seen[id]) dropLight(id);   /* deleted, hidden, or pushed past the cap */
  }
  AR_EXT.ticks.push(lleTick);
  window.lleSyncLights = lleTick;             /* the family-prefixed handle the test drives */
  window.lleLightCount = function(){ var n = 0; for(var k in LIGHTS) n++; return n; };

  /* ── l_hdri: the sky as the light ─────────────────────────────────────── */
  function hdriList(){
    if(CACHE.hdri) return Promise.resolve(CACHE.hdri);
    return fetch(API + 'list').then(function(r){ return r.json(); }).then(function(j){
      if(!j || !j.ok) throw new Error((j && j.error) || 'the sky library did not answer');
      CACHE.hdri = j;
      return j;
    });
  }
  function disposeEnv(){
    if(AR._lleEnv){ AR._lleEnv.dispose(); AR._lleEnv = null; }
    if(AR._lleBg){ AR._lleBg.dispose(); AR._lleBg = null; }
  }
  function skyIsDaylight(){
    try{ return AR_SKIES[AR.skyIx || 0].n === 'daylight'; }catch(e){ return false; }
  }
  function setHdri(name){
    name = String(name == null ? 'off' : name);
    if(name === 'off' || name === ''){
      disposeEnv();
      AR.scene.environment = null;
      AR.scene.background = new THREE.Color(AR._fogCol || 0x9fbdd8);
      state().hdri = null;
      arToast('Environment light <b>off</b> — back to the flat background.');
      arToolsRender();
      return Promise.resolve({hdri: null});
    }
    return needRGBE().then(hdriList).then(function(j){
      var it = null;
      (j.items || []).forEach(function(x){ if(x.name === name) it = x; });
      if(!it) throw new Error('unknown sky: ' + name);
      return new Promise(function(res, rej){
        new THREE.RGBELoader().load(API + 'hdri?name=' + encodeURIComponent(name),
          function(tex){ res({tex: tex, it: it, lic: j.licence}); },
          undefined,
          function(){ rej(new Error('could not read ' + it.file)); });
      });
    }).then(function(r){
      var tex = r.tex;
      tex.mapping = THREE.EquirectangularReflectionMapping;
      var pm = new THREE.PMREMGenerator(AR.renderer);
      pm.compileEquirectangularShader();
      var env = pm.fromEquirectangular(tex).texture;
      pm.dispose();
      disposeEnv();                            /* only after the new one exists */
      AR.scene.environment = env;
      AR._lleEnv = env;
      /* the background is the user's switch, not ours: only a 'daylight' sky is
         replaced by the photograph — overcast / dusk / studio stay as chosen */
      if(skyIsDaylight()){ AR.scene.background = tex; AR._lleBg = tex; }
      else { tex.dispose(); }
      state().hdri = r.it.name;
      arToast('Environment: <b>' + esc(r.it.label || r.it.name) + '</b> — ' + esc(r.lic || '') + '.');
      arToolsRender();
      return {hdri: r.it.name, background: skyIsDaylight()};
    }).catch(function(err){
      arToast('Environment light failed: ' + esc(String(err && err.message || err)), 'bad');
      return {hdri: state().hdri || null, error: String(err && err.message || err)};
    });
  }
  AR_EXT.tools.l_hdri = {
    assist: 1, tog: 1,
    tip: 'HDRI environment — a photographed sky as the light source, and what the glass reflects. Cycles off / each bundled CC0 sky',
    on: function(){ return !!(AR.doc && AR.doc.ext && AR.doc.ext[FAM] && AR.doc.ext[FAM].hdri); },
    act: function(opt){
      if(opt && typeof opt === 'object' && opt.name != null) return setHdri(opt.name);
      return hdriList().then(function(j){
        var names = (j.items || []).map(function(x){ return x.name; });
        if(!names.length){ arToast('No HDRIs in the library.', 'warn'); return {hdri: null}; }
        var cur = state().hdri, i = names.indexOf(cur);
        return setHdri(i < 0 ? names[0] : (i + 1 < names.length ? names[i + 1] : 'off'));
      });
    }
  };

  /* ── l_lamp: place a lamp ─────────────────────────────────────────────── */
  function cellXZ(cell){
    /* the inverse of arCellName: bijective base-26 letters + a 1-based row,
       answered at the CENTRE of the cell so arCellName gives the name back */
    var m = String(cell || '').trim().toUpperCase().replace(/\s+/g, '').match(/^([A-Z]{1,3})(\d{1,3})$/);
    if(!m) return null;
    var c = 0, s = m[1], i;
    for(i = 0; i < s.length; i++) c = c * 26 + (s.charCodeAt(i) - 64);
    c -= 1;
    var r = parseInt(m[2], 10) - 1;
    if(c < 0 || r < 0 || c >= 300 || r >= 300) return null;
    return {x: AR_CELL_O + (c + 0.5) * AR_CELL_M, z: AR_CELL_O + (r + 0.5) * AR_CELL_M};
  }
  function lightCount(){
    var n = 0;
    AR.objs.forEach(function(o){ if(isLight(o.kind)) n++; });
    return n;
  }
  function paramsFor(kind, opt){
    var p = JSON.parse(JSON.stringify(DEFAULTS[kind]));
    if(opt && typeof opt === 'object'){
      if(opt.watts != null) p.w = clamp(num(opt.watts, p.w), 0.1, 5000);
      if(opt.colour) p.col = String(opt.colour);
      if(opt.color) p.col = String(opt.color);
      if(opt.range != null) p.r = clamp(num(opt.range, p.r), 0, 500);
      if(opt.angle != null && kind === 'light_spot') p.angle = clamp(num(opt.angle, p.angle), 3, 80);
    }
    return p;
  }
  AR_EXT.tools.l_lamp = {
    assist: 1,
    tip: 'Artificial lights — place point, spot and area lights for an interior after dark. Click to place a point light; the assistant may name a kind and a cell',
    act: function(opt){
      var kind = 'light_point';
      if(opt && typeof opt === 'object' && opt.kind){
        kind = String(opt.kind);
        if(kind.lastIndexOf('light_', 0) !== 0) kind = 'light_' + kind;
      }
      if(!isLight(kind)){ arToast('Not a lamp kind: ' + esc(String(kind)), 'bad'); return {error: 'kind'}; }
      if(lightCount() >= CAP){
        arToast('The scene already holds ' + CAP + ' lights — that is the budget. Delete one first.', 'warn');
        return {error: 'cap', cap: CAP};
      }
      var p = paramsFor(kind, opt);
      var cell = opt && typeof opt === 'object' ? opt.cell : null;
      if(!cell){
        /* the rail's own mechanism: arm a placement, the next ground click drops it */
        arTool('place', {kind: kind, p: p, n: LABEL[kind]});
        arHint('Click where the ' + LABEL[kind].toLowerCase() + ' goes — shift-click to keep placing.');
        return {armed: kind};
      }
      var at = cellXZ(cell);
      if(!at){ arToast('Not a grid cell: ' + esc(String(cell)), 'bad'); return {error: 'cell'}; }
      var h = AR.defaults.wall_h || 2.7;
      var base = (opt.storey != null) ? num(opt.storey, 0) * h : AR.level;
      /* a lamp hangs just under the ceiling of its storey unless told otherwise */
      var y = (opt.y != null) ? base + num(opt.y, 0) : base + h - 0.3;
      arPush();
      var rec = arNewObj(kind, p, at.x, at.z, y);
      rec.name = LABEL[kind];
      arApplyTransform(rec);
      arSelect([rec.id]);
      arPanel();
      lleTick();
      arToast('Placed a <b>' + esc(LABEL[kind]) + '</b> in ' + esc(arCellName(rec.x, rec.z) || String(cell)) +
              ' at ' + arFmt(y) + ' m.');
      return {id: rec.id, kind: kind, cell: arCellName(rec.x, rec.z), x: rec.x, y: rec.y, z: rec.z};
    }
  };

  /* ── l_ies: a measured luminaire instead of a guessed cone ─────────────── */
  function iesList(){
    if(CACHE.ies) return Promise.resolve(CACHE.ies);
    return fetch(API + 'ies_list').then(function(r){ return r.json(); }).then(function(j){
      if(!j || !j.ok) throw new Error((j && j.error) || 'the IES library did not answer');
      CACHE.ies = j;
      return j;
    });
  }
  /* IESNA LM-63 — the same arithmetic as arch_server_ext/light_lamps_env.parse_ies.
     After the keyword header and the TILT= line the file is one free-running
     stream of numbers, wrapped over as many lines as the writer felt like. */
  function llePhotometry(text){
    var lines = String(text).replace(/\r/g, '').split('\n'), i = 0, tilt = 'NONE', found = false;
    for(; i < lines.length; i++){
      var s = lines[i].trim().toUpperCase();
      if(s.lastIndexOf('TILT=', 0) === 0){ tilt = s.slice(5).trim() || 'NONE'; i++; found = true; break; }
    }
    if(!found) throw new Error('no TILT= line — this is not an LM-63 photometric file');
    var tok = [];
    lines.slice(i).join(' ').replace(/,/g, ' ').split(/\s+/).forEach(function(t){
      if(!t) return;
      var v = Number(t);
      if(isFinite(v)) tok.push(v);
    });
    var k = 0;
    if(tilt === 'INCLUDE'){ k += 1; var np = tok[k++] | 0; k += 2 * np; }
    function nx(d){ var v = (k < tok.length) ? tok[k] : d; k++; return v; }
    var lamps = nx(1), lpl = nx(-1), mult = nx(1);
    var nv = nx(0) | 0, nh = nx(0) | 0;
    var type = nx(1) | 0, units = nx(2) | 0;
    nx(0); nx(0); nx(0);
    var ballast = nx(1); nx(1); var watts = nx(0);
    if(nv < 2 || nh < 1 || tok.length - k < nv + nh + nv * nh)
      throw new Error('truncated LM-63 body: ' + nv + ' x ' + nh + ' angles do not fit');
    var va = [], ha = [], cd = [], j;
    for(j = 0; j < nv; j++) va.push(tok[k++]);
    for(j = 0; j < nh; j++) ha.push(tok[k++]);
    var scale = (mult || 1) * (ballast || 1);
    for(j = 0; j < nv * nh; j++) cd.push(tok[k++] * scale);

    var col0 = cd.slice(0, nv), peak = 0, pi = 0;
    for(j = 0; j < nv; j++) if(col0[j] > peak){ peak = col0[j]; pi = j; }
    var beam = va[nv - 1], half = peak / 2;
    for(j = pi + 1; j < nv; j++){
      if(col0[j] <= half){
        var a0 = va[j - 1], a1 = va[j], c0 = col0[j - 1], c1 = col0[j];
        beam = (c0 === c1) ? a1 : a0 + (c0 - half) * (a1 - a0) / (c0 - c1);
        break;
      }
    }
    var flux = 0, D = Math.PI / 180;
    for(j = 0; j < nv - 1; j++){
      var t0 = va[j] * D, t1 = va[j + 1] * D, sum = 0;
      for(var h = 0; h < nh; h++) sum += (cd[h * nv + j] + cd[h * nv + j + 1]) / 2;
      flux += 2 * Math.PI * (sum / nh) * (Math.cos(t0) - Math.cos(t1));
    }
    flux = Math.abs(flux);
    var declared = (lpl > 0) ? lamps * lpl : 0;
    return {tilt: tilt, lamps: lamps, lumens_per_lamp: lpl, mult: mult, ballast: ballast,
            n_v: nv, n_h: nh, photo_type: type, units: units, watts: watts,
            v_angles: va, h_angles: ha, cd: cd, col0: col0,
            peak_cd: Math.round(peak * 100) / 100, peak_angle: va[pi],
            beam_angle: Math.round(beam * 100) / 100,
            lumens: Math.round((declared || flux) * 10) / 10,
            lumens_measured: Math.round(flux * 10) / 10};
  }
  window.llePhotometry = llePhotometry;       /* family-prefixed: the test parses the same way the icon does */

  /* the polar diagram: nadir points DOWN the page, the curve mirrored either
     side of the axis the way a photometric data sheet draws it */
  function polarSvg(ph){
    var W = 340, H = 260, cx = W / 2, cy = 70, R = 165, D = Math.PI / 180;
    var peak = ph.peak_cd || 1, i, parts = [];
    for(i = 0; i < 4; i++){
      var rr = R * (i + 1) / 4;
      parts.push('<circle cx="' + cx + '" cy="' + cy + '" r="' + rr.toFixed(1) +
                 '" fill="none" stroke="#7d8794" stroke-width=".6" stroke-dasharray="2 3"/>');
    }
    [0, 30, 60, 90, 120].forEach(function(a){
      var x = cx + R * Math.sin(a * D), y = cy + R * Math.cos(a * D);
      parts.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) +
                 '" stroke="#7d8794" stroke-width=".6"/>');
      if(a) parts.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + (2 * cx - x).toFixed(1) + '" y2="' + y.toFixed(1) +
                       '" stroke="#7d8794" stroke-width=".6"/>');
      parts.push('<text x="' + (x + (a > 90 ? -16 : 4)).toFixed(1) + '" y="' + (y + 10).toFixed(1) +
                 '" font-size="9" fill="#9aa4b2">' + a + '\u00b0</text>');
    });
    function path(sign){
      var d = '';
      for(i = 0; i < ph.n_v; i++){
        var t = ph.v_angles[i] * D, rr = R * clamp(ph.col0[i] / peak, 0, 1);
        d += (i ? 'L' : 'M') + (cx + sign * rr * Math.sin(t)).toFixed(1) + ' ' + (cy + rr * Math.cos(t)).toFixed(1) + ' ';
      }
      return d;
    }
    parts.push('<path d="' + path(1) + '" fill="none" stroke="#ffcf6b" stroke-width="1.8"/>');
    parts.push('<path d="' + path(-1) + '" fill="none" stroke="#ffcf6b" stroke-width="1.8" opacity=".55"/>');
    var b = ph.beam_angle * D;
    parts.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + (cx + R * Math.sin(b)).toFixed(1) + '" y2="' +
               (cy + R * Math.cos(b)).toFixed(1) + '" stroke="#67e8f9" stroke-width="1.2" stroke-dasharray="4 3"/>');
    parts.push('<text x="6" y="' + (H - 6) + '" font-size="10" fill="#9aa4b2">peak ' + Math.round(peak) +
               ' cd \u00b7 half-intensity at ' + ph.beam_angle.toFixed(1) + '\u00b0</text>');
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" style="max-width:360px;display:block;margin:0 auto 8px">' +
           parts.join('') + '</svg>';
  }
  function applyIes(name, ph){
    var recs = arSelRecs().filter(function(r){ return r.kind === 'light_spot'; });
    if(!recs.length) return [];
    arPush();
    var ids = [];
    recs.forEach(function(r){
      r.p.ies = name;
      r.p.angle = Math.round(clamp(ph.beam_angle, 3, 80) * 10) / 10;
      r.p.ies_lm = Math.round(ph.lumens);
      r.p.ies_cd = Math.round(ph.peak_cd);
      if(ph.watts > 0) r.p.w = ph.watts;
      arRebuild(r);
      ids.push(r.id);
    });
    arPanel();
    lleTick();
    return ids;
  }
  AR_EXT.tools.l_ies = {
    assist: 1,
    tip: 'IES photometric profiles — a real luminaire\u2019s measured beam instead of a cone of light: draws the polar curve and gives the selected spot its angle and flux',
    act: function(opt){
      return iesList().then(function(j){
        var items = j.items || [];
        if(!items.length){ arToast('No IES profiles in the library.', 'warn'); return {error: 'empty'}; }
        var name = (opt && typeof opt === 'object' && opt.name) ? String(opt.name) : null;
        if(!name){
          var ask = items.map(function(x, i){ return (i + 1) + '. ' + x.name + ' — ' + x.label; }).join('\n');
          name = prompt('IES profile:\n' + ask, items[0].name);
          if(name == null) return {cancelled: true};
          name = String(name).trim();
          var byNo = parseInt(name, 10);
          if(String(byNo) === name && byNo >= 1 && byNo <= items.length) name = items[byNo - 1].name;
        }
        var it = null;
        items.forEach(function(x){ if(x.name === name) it = x; });
        if(!it) throw new Error('unknown profile: ' + name);
        return fetch(API + 'ies?name=' + encodeURIComponent(name)).then(function(r){ return r.text(); }).then(function(txt){
          var ph = llePhotometry(txt);
          var ids = applyIes(name, ph);
          arSheet('Photometry \u2014 ' + esc(it.label || name),
            polarSvg(ph) + arRows([
              ['profile', esc(it.label || name)],
              ['file', esc(it.file) + ' \u00b7 ' + it.kb + ' kB'],
              ['licence', esc(j.licence || '')],
              ['angles', ph.n_v + ' vertical \u00d7 ' + ph.n_h + ' horizontal = ' + ph.cd.length + ' candela values'],
              ['peak intensity', Math.round(ph.peak_cd) + ' cd at ' + ph.peak_angle + '\u00b0'],
              ['beam (half intensity)', ph.beam_angle.toFixed(1) + '\u00b0 half-angle'],
              ['luminous flux', Math.round(ph.lumens) + ' lm' + (ph.lumens_per_lamp > 0 ? ' (declared)' : ' (integrated \u2014 absolute photometry)')],
              ['input power', ph.watts ? ph.watts + ' W' : '\u2014'],
              ['applied to', ids.length ? ids.length + ' selected spot light(s)' : 'nothing \u2014 select a spot light first']
            ]));
          if(ids.length) arToast('Applied <b>' + esc(it.label || name) + '</b> to ' + ids.length + ' spot light(s): ' +
                                 ph.beam_angle.toFixed(1) + '\u00b0 beam, ' + Math.round(ph.lumens) + ' lm.');
          else arToast('Read <b>' + esc(it.label || name) + '</b> \u2014 select a spot light to apply it.', 'warn');
          return {name: name, beam_angle: ph.beam_angle, lumens: ph.lumens, cd: ph.cd.length,
                  n_v: ph.n_v, n_h: ph.n_h, applied: ids};
        });
      }).catch(function(err){
        arToast('IES: ' + esc(String(err && err.message || err)), 'bad');
        return {error: String(err && err.message || err)};
      });
    }
  };

  /* ── what the press answered ──────────────────────────────────────────── */
  /* arTool() calls act() and returns nothing, so a caller that pressed the icon
     the way a person does cannot see what it decided (or, for l_hdri and l_ies,
     await the promise it is still working through). Every act's answer is kept
     here under the icon's id: lleLast('l_hdri') is the value the LAST press of
     that icon returned — a plain object, or the promise to await. */
  var LAST = {};                    /* module-local: the bundle runs before AR exists */
  ['l_hdri', 'l_lamp', 'l_ies'].forEach(function(id){
    var t = AR_EXT.tools[id], inner = t.act;
    t.act = function(opt){
      var v = inner.call(t, opt);
      LAST[id] = v;
      return v;
    };
  });
  window.lleLast = function(id){ return LAST[id]; };

  /* ── once the engine exists ───────────────────────────────────────────── */
  AR_EXT.ready.push(function(){
    needRectArea().catch(function(){});        /* the LTC tables, warmed up before the first area light */
    var want = (AR.doc && AR.doc.ext && AR.doc.ext[FAM] && AR.doc.ext[FAM].hdri) || null;
    if(want) setHdri(want);                    /* a drawing that was saved with a sky gets it back */
    lleTick();
  });
})();
