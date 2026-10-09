// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* file_manage_setup — nine icons about the LIFE of a drawing and the SETUP of
   the studio, wired through the ICON seam (2026-09-07).

     File   f_tmpl     templates: save the current drawing as one, start from one
            f_ver      version history: every save kept, restore or label one
            f_auto     autosave: a quiet snapshot every N seconds while dirty
            f_archive  zip the drawing, its versions and its exports as one issue
     Setup  p_prefs    every 'ar.' preference this tab keeps, editable, resettable
            p_theme    dark / light / blueprint, as a class on #view-architecture
            p_perf     live frame numbers and the knobs that trade quality for them
            p_help     every icon with its tooltip, the keys, the assistant's tools
            p_about    what this engine is, from the files rather than from a note

   The disk half is arch_server_ext/file_manage_setup.py; nothing in
   inspection.html was edited to make any of this real. Globals this file must
   leave behind (the sheets' own buttons call them) are all FMS_-prefixed. */
(function(){
  var FAM = 'file_manage_setup';
  var EP  = '/inspect/api/architecture/ext/' + FAM + '/';
  var LS  = 'ar.' + FAM + '.';

  /* ── state ─────────────────────────────────────────────────────────────── */
  var FMS = {
    auto: false, every_s: 120, autoN: 0, timer: null,
    theme: 'dark',
    perf: {ratio: 0, shadows: null, tex: 'high', freeze_on: false, freeze_m: 60, reduced: false},
    busy: null,          /* the last async press, so a test (or a caller) can await it */
    sheet: ''            /* which of our sheets is open, for the live perf numbers */
  };
  window.FMS = FMS;

  function post(op, body){
    return fetch(EP + op, {method: 'POST', headers: {'Content-Type': 'application/json'},
                           body: JSON.stringify(body || {})});
  }
  function postJ(op, body){ return post(op, body).then(function(r){ return r.json(); }); }
  function track(p){ FMS.busy = p; return p; }
  function lsGet(k, d){ try{ var v = localStorage.getItem(LS + k); return v === null ? d : v; }catch(e){ return d; } }
  function lsSet(k, v){ try{ localStorage.setItem(LS + k, String(v)); }catch(e){} }
  function ask(opt, field, question, dflt){
    if(opt && typeof opt === 'object' && opt[field] !== undefined && opt[field] !== null) return opt[field];
    return prompt(question, dflt);
  }
  function fmtBytes(n){
    n = Number(n) || 0;
    return n < 1024 ? (n + ' B') : n < 1048576 ? ((n / 1024).toFixed(1) + ' kB') : ((n / 1048576).toFixed(2) + ' MB');
  }
  function docPid(){ return (AR.doc && AR.doc.id) || ''; }

  /* Replace the whole document with `doc`, the way arOpen does it — but in
     place, as ONE undo step, so a template or a restored version can be taken
     back with Ctrl+Z. arPush() goes first, before anything is touched. */
  function loadDoc(doc, name, keepId){
    arPush();
    AR.objs.slice().forEach(arRemove);
    AR.objs = []; AR.sel = [];
    var max = 0;
    (doc.objects || []).forEach(function(o){
      var rec = {id: o.id || ('o' + (max + 1)), kind: o.kind, name: o.name || arKindLabel(o.kind),
                 p: o.p || {}, x: arNum(o.x, 0), y: arNum(o.y, 0), z: arNum(o.z, 0),
                 rx: arNum(o.rx, 0), ry: arNum(o.ry, 0), rz: arNum(o.rz, 0), s: arNum(o.s, 1),
                 mat: o.mat || 'mat_concrete', hidden: !!o.hidden, grp: o.grp || '',
                 meta: (o.meta && typeof o.meta === 'object') ? o.meta : {}};
      AR.objs.push(rec);
      var n = parseInt(String(rec.id).replace('o', ''), 10); if(n > max) max = n;
    });
    AR.seq = max + 1;
    AR.objs.forEach(arRebuild);
    arSyncHoles();
    AR.doc.name = name || doc.name || 'Untitled drawing';
    AR.doc.ext = (doc.ext && typeof doc.ext === 'object') ? doc.ext : {};
    if(!keepId) AR.doc.id = '';                 /* a template opens as a NEW drawing */
    arSelSync(); arPanel(); arOutliner(); arDocName(); arDirty(true); arHud();
    if(window.arRailRender) arRailRender();
  }

  /* ══ f_tmpl — templates ════════════════════════════════════════════════ */
  function tmplList(){
    return track(postJ('templates', {}).then(function(d){
      var rows = (d.templates || []).map(function(t){
        return '<tr><td>' + esc(t.name) + '</td>'
             + '<td style="text-align:right">' + t.objects + ' obj '
             + '<button class="fms-btn" onclick="FMS_tmplNew(\'' + esc(t.id) + '\')">open</button></td></tr>';
      }).join('');
      arSheet('Templates', '<div class="sh">Start from a template</div>'
        + '<table class="ar-tbl">' + (rows || '<tr><td>no templates yet</td><td></td></tr>') + '</table>'
        + '<div class="sh">This drawing</div>'
        + '<p style="font-size:.72rem;color:#9aa4b2;margin:2px 0 8px">'
        + 'Saving the current drawing as a template keeps it out of the way of your own '
        + 'work: it is an ordinary drawing with one flag set, listed only here.</p>'
        + '<button class="fms-btn" onclick="FMS_tmplSave()">Save this drawing as a template</button>');
      FMS.sheet = 'f_tmpl';
      return d;
    }));
  }
  function tmplNew(idOrName){
    var body = /^[a-z0-9-]+$/.test(String(idOrName || '')) ? {id: idOrName} : {name: idOrName};
    return track(postJ('open_template', body).then(function(d){
      if(d.error){ arToast(esc(d.error), 'bad'); return d; }
      loadDoc(d.doc || {}, d.name, false);
      arSheetClose(); FMS.sheet = '';
      arToast('New drawing from template <b>' + esc(d.name) + '</b> — ' + AR.objs.length
            + ' objects. It has no name yet; the first save will ask for one.');
      return d;
    }));
  }
  function tmplSave(name){
    name = String(name || '').trim();
    if(!name) return Promise.resolve({error: 'cancelled'});
    return track(postJ('save_template', {doc: arDocOut(), name: name}).then(function(d){
      if(d.error){ arToast(esc(d.error), 'bad'); return d; }
      arToast('Saved as a template: <b>' + esc(d.name) + '</b> (' + d.objects + ' objects).');
      if(FMS.sheet === 'f_tmpl') tmplList();
      return d;
    }));
  }
  window.FMS_tmplNew = tmplNew;
  window.FMS_tmplSave = function(){
    var n = prompt('Name for the template:', (AR.doc.name || 'Template'));
    if(n) tmplSave(n);
  };

  AR_EXT.tools.f_tmpl = {
    assist: 1,
    tip: 'Templates — start a new drawing from a stock one, or keep this drawing as a template',
    act: function(opt){
      var action = (opt && typeof opt === 'object' && opt.action) ? String(opt.action) : 'list';
      if(action === 'save'){
        var n = ask(opt, 'name', 'Name for the template:', (AR.doc.name || 'Template'));
        return tmplSave(n);
      }
      if(action === 'new') return tmplNew(ask(opt, 'name', 'Template to start from (name or id):', ''));
      return tmplList();
    }
  };

  /* ══ f_ver — version history ═══════════════════════════════════════════ */
  function snapshot(label){
    var pid = docPid();
    if(!pid) return Promise.resolve({error: 'the drawing has no name yet — save it first'});
    return postJ('snapshot', {pid: pid, doc: arDocOut(), label: label || ''});
  }
  function verList(){
    var pid = docPid();
    if(!pid){ arToast('Save the drawing first — versions are kept per drawing.', 'warn');
              return Promise.resolve({error: 'unsaved'}); }
    return track(postJ('versions', {pid: pid, action: 'list'}).then(function(d){
      var rows = (d.versions || []).map(function(v){
        return '<tr><td>' + esc(v.saved || v.stamp)
             + (v.label ? ' <b>' + esc(v.label) + '</b>' : '') + '</td>'
             + '<td style="text-align:right">' + v.objects + ' obj '
             + '<button class="fms-btn" onclick="FMS_verRestore(\'' + v.stamp + '\')">restore</button> '
             + '<button class="fms-btn" onclick="FMS_verLabel(\'' + v.stamp + '\')">label</button></td></tr>';
      }).join('');
      arSheet('Versions of ' + esc(AR.doc.name || pid),
        '<div class="sh">' + (d.versions || []).length + ' kept (newest first, ' + (d.keep || 50) + ' max)</div>'
        + '<table class="ar-tbl">' + (rows || '<tr><td>nothing kept yet — save the drawing</td><td></td></tr>') + '</table>'
        + '<p style="font-size:.72rem;color:#9aa4b2;margin:8px 0 0">Restoring loads that version into '
        + 'this tab as the current document. It is one undo step and it does not overwrite the named '
        + 'save until you save again.</p>');
      FMS.sheet = 'f_ver';
      return d;
    }));
  }
  function verRestore(stamp){
    var pid = docPid();
    if(!pid) return Promise.resolve({error: 'unsaved'});
    return track(postJ('versions', {pid: pid, action: 'restore', stamp: stamp}).then(function(d){
      if(d.error){ arToast(esc(d.error), 'bad'); return d; }
      loadDoc(d.doc || {}, (d.doc || {}).name, true);
      arSheetClose(); FMS.sheet = '';
      arToast('Restored version <b>' + esc(stamp) + '</b> — ' + AR.objs.length
            + ' objects. Ctrl+Z puts it back.');
      return d;
    }));
  }
  function verLabel(stamp, label){
    var pid = docPid();
    if(!pid) return Promise.resolve({error: 'unsaved'});
    return track(postJ('versions', {pid: pid, action: 'label', stamp: stamp, label: label || ''})
      .then(function(d){
        if(d.error){ arToast(esc(d.error), 'bad'); return d; }
        arToast('Labelled <b>' + esc(d.label || '(none)') + '</b>.');
        if(FMS.sheet === 'f_ver') verList();
        return d;
      }));
  }
  window.FMS_verRestore = verRestore;
  window.FMS_verLabel = function(stamp){
    var l = prompt('Label for this version:', '');
    if(l !== null) verLabel(stamp, l);
  };

  AR_EXT.tools.f_ver = {
    assist: 1,
    tip: 'Version history — every save kept on a shelf, with restore and a label for the ones worth naming',
    act: function(opt){
      var action = (opt && typeof opt === 'object' && opt.action) ? String(opt.action) : 'list';
      if(action === 'restore') return verRestore(ask(opt, 'stamp', 'Version stamp to restore:', ''));
      if(action === 'label')  return verLabel(ask(opt, 'stamp', 'Version stamp to label:', ''),
                                              ask(opt, 'label', 'Label:', ''));
      if(action === 'snapshot') return track(snapshot(opt && opt.label));
      return verList();
    }
  };

  /* ══ f_auto — autosave ═════════════════════════════════════════════════ */
  function autoTick(){
    if(!FMS.auto) return;
    if(!AR.dirty || !docPid()) return;
    FMS.busy = snapshot('autosave').then(function(d){
      if(d.error) return d;
      FMS.autoN++;
      if(FMS.autoN % 10 === 1 || FMS.autoN % 10 === 0)
        arToast('Autosaved — ' + FMS.autoN + ' snapshot' + (FMS.autoN === 1 ? '' : 's')
              + ' kept for <b>' + esc(AR.doc.name || docPid()) + '</b>.');
      return d;
    });
    return FMS.busy;
  }
  function autoSet(on, every_s){
    FMS.auto = !!on;
    if(every_s !== undefined && every_s !== null){
      var v = parseFloat(every_s);
      if(isFinite(v) && v >= 1) FMS.every_s = v;
    }
    if(FMS.timer){ clearInterval(FMS.timer); FMS.timer = null; }
    if(FMS.auto) FMS.timer = setInterval(autoTick, FMS.every_s * 1000);
    lsSet('autosave', JSON.stringify({on: FMS.auto, every_s: FMS.every_s}));
    if(window.arToolsRender) arToolsRender();
    return FMS.auto;
  }
  AR_EXT.tools.f_auto = {
    tog: 1, assist: 1,
    tip: 'Autosave — while this is on, a dirty saved drawing is snapshotted to its version shelf every couple of minutes',
    on: function(){ return !!FMS.auto; },
    act: function(opt){
      var want = (opt && typeof opt === 'object' && opt.on !== undefined) ? !!opt.on : !FMS.auto;
      var every = (opt && typeof opt === 'object') ? opt.every_s : undefined;
      autoSet(want, every);
      arToast(FMS.auto
        ? ('Autosave <b>on</b> — every ' + FMS.every_s + ' s while the drawing is dirty and has a name.')
        : 'Autosave <b>off</b>.');
      return FMS.auto;
    }
  };

  /* ══ f_archive — the issue package ═════════════════════════════════════ */
  AR_EXT.tools.f_archive = {
    assist: 1,
    tip: 'Archive — zip the drawing with every version kept and every export named after it, as one issue package',
    act: function(){
      var pid = docPid();
      if(!pid){ arToast('Save the drawing first — an archive is built around its id.', 'warn');
                return Promise.resolve(null); }
      return track(post('archive', {pid: pid, doc: arDocOut()}).then(function(r){
        if(!r.ok) return r.json().then(function(e){ arToast(esc(e.error || 'archive failed'), 'bad'); return null; });
        return r.blob().then(function(b){
          arDownload(b, (AR.doc.name || 'drawing').replace(/[^\w-]+/g, '_') + '.zip');
          arToast('Archive downloaded — <b>' + fmtBytes(b.size) + '</b>.');
          return b;
        });
      }));
    }
  };

  /* ══ p_prefs — preferences ═════════════════════════════════════════════ */
  /* Every key this tab keeps is namespaced 'ar.' (the families) or 'ar_' (the
     studio's own older keys, ar_sky_ix and friends). Both are shown: a
     preferences sheet that hides half the preferences is a worse lie than no
     sheet at all. */
  function prefKeys(){
    var out = [];
    try{
      for(var i = 0; i < localStorage.length; i++){
        var k = localStorage.key(i);
        if(/^ar[._]/.test(k)) out.push(k);
      }
    }catch(e){}
    return out.sort();
  }
  function prefShow(v){
    try{ var j = JSON.parse(v); if(j && typeof j === 'object') return JSON.stringify(j, null, 1); }catch(e){}
    return v;
  }
  function prefsSheet(){
    var rows = prefKeys().map(function(k){
      var v = '';
      try{ v = localStorage.getItem(k) || ''; }catch(e){}
      return '<tr><td style="word-break:break-all">' + esc(k) + '</td>'
           + '<td style="text-align:right"><input class="fms-pref" data-k="' + esc(k) + '" '
           + 'value="' + esc(prefShow(v)).replace(/"/g, '&quot;') + '" '
           + 'style="width:120px;background:#1b1f27;border:1px solid #2a323d;color:inherit;'
           + 'border-radius:5px;padding:2px 5px;font:inherit"> '
           + '<button class="fms-btn" onclick="FMS_prefSet(\'' + esc(k) + '\')">set</button> '
           + '<button class="fms-btn" onclick="FMS_prefReset(\'' + esc(k) + '\')">reset</button></td></tr>';
    }).join('');
    var D = AR.defaults || {};
    var num = function(key, step, min){
      return '<input type="number" step="' + step + '" min="' + min + '" value="' + (D[key] === undefined ? '' : D[key])
           + '" onchange="FMS_defSet(\'' + key + '\', this.value)" '
           + 'style="width:80px;background:#1b1f27;border:1px solid #2a323d;color:inherit;'
           + 'border-radius:5px;padding:2px 5px;font:inherit">';
    };
    arSheet('Preferences',
      '<div class="sh">Studio defaults</div>'
      + arRows([['grid / snap (m)', num('grid', 0.05, 0.01)],
                ['wall height (m)', num('wall_h', 0.1, 0.1)],
                ['wall thickness (m)', num('wall_t', 0.01, 0.02)]])
      + '<p style="font-size:.72rem;color:#9aa4b2;margin:6px 0 0">These are what a new wall or a new '
      + 'room is made of. They are kept in <code>' + LS + 'defaults</code> and re-applied when the tab opens.</p>'
      + '<div class="sh">Stored preferences (' + prefKeys().length + ')</div>'
      + '<table class="ar-tbl">' + (rows || '<tr><td>nothing stored yet</td><td></td></tr>') + '</table>'
      + '<p style="margin:10px 0 0"><button class="fms-btn" onclick="FMS_prefResetAll()">'
      + 'Reset every preference</button></p>');
    FMS.sheet = 'p_prefs';
  }
  window.FMS_prefSet = function(k){
    var el = document.querySelector('.fms-pref[data-k="' + k + '"]');
    if(!el) return;
    try{ localStorage.setItem(k, el.value); arToast('Set <b>' + esc(k) + '</b>.'); }catch(e){}
    if(k === LS + 'defaults') applyDefaults();
  };
  window.FMS_prefReset = function(k){
    if(!confirm('Forget the preference ' + k + '?')) return;
    try{ localStorage.removeItem(k); }catch(e){}
    arToast('Reset <b>' + esc(k) + '</b>.');
    prefsSheet();
  };
  window.FMS_prefResetAll = function(){
    var ks = prefKeys();
    if(!ks.length) return;
    if(!confirm('Forget all ' + ks.length + ' stored preferences? The studio goes back to its shipped defaults.')) return;
    ks.forEach(function(k){ try{ localStorage.removeItem(k); }catch(e){} });
    arToast('Forgot ' + ks.length + ' preferences.');
    prefsSheet();
  };
  window.FMS_defSet = function(key, v){
    var n = parseFloat(v);
    if(!isFinite(n)) return;
    AR.defaults[key] = n;
    lsSet('defaults', JSON.stringify({grid: AR.defaults.grid, wall_h: AR.defaults.wall_h, wall_t: AR.defaults.wall_t}));
    if(key === 'grid' && window.arSnapV) arSnapV(n);
    arToast('Default <b>' + esc(key) + '</b> is now ' + n + '.');
  };
  function applyDefaults(){
    var raw = lsGet('defaults', '');
    if(!raw) return;
    try{
      var d = JSON.parse(raw);
      ['grid', 'wall_h', 'wall_t'].forEach(function(k){
        var n = parseFloat(d[k]); if(isFinite(n)) AR.defaults[k] = n;
      });
    }catch(e){}
  }
  AR_EXT.tools.p_prefs = {
    assist: 1,
    tip: 'Preferences — every stored setting this tab keeps, and the defaults a new wall or room is made of',
    act: function(){ prefsSheet(); }
  };

  /* ══ p_theme — the studio's look ═══════════════════════════════════════ */
  var THEMES = {
    dark:      null,
    light:     {panel: '#eef1f6', panel2: '#f8fafc', txt: '#171b22', line: '#c3ccd9',
                acc: '#0b6fa4', muted: '#5a6472', sky: 0xeef2f7},
    blueprint: {panel: '#12305a', panel2: '#0d2547', txt: '#dfe8ff', line: '#2f5a97',
                acc: '#5ce1ff', muted: '#9fb6dd', sky: 0x0b1f3d}
  };
  var ORDER = ['dark', 'light', 'blueprint'];
  var PANELS = ['.ar-rail', '.ar-toolcol', '.ar-tools', '#ar-dock', '.ar-dock',
                '.ar-panel', '.ar-sheet', '.ar-toast', '.ar-hint', '.ar-hud'];
  function themeCss(){
    var out = ['/* file_manage_setup: the studio LOOK, one class on #view-architecture */'];
    ORDER.forEach(function(name){
      var t = THEMES[name]; if(!t) return;
      var root = '#view-architecture.ar-theme-' + name + ' ';
      out.push(PANELS.map(function(s){ return root + s; }).join(',')
        + '{background:' + t.panel + ' !important;color:' + t.txt + ';border-color:' + t.line + ';}');
      out.push(PANELS.map(function(s){ return root + s + ' *'; }).join(',')
        + '{border-color:' + t.line + ';}');
      out.push(root + '.ar-tool{background:' + t.panel2 + ';color:' + t.txt + ';border-color:' + t.line + ';}');
      out.push(root + '.ar-tool.on,' + root + '.ar-tool.flash'
        + '{background:' + t.acc + ';color:' + t.panel2 + ';border-color:' + t.acc + ';}');
      out.push(root + '.ar-tsec,' + root + '.ar-dsec,' + root + '.ar-rail h4,'
        + root + '.ar-hud,' + root + '.ar-tbl td:first-child{color:' + t.muted + ';}');
      out.push(root + '.ar-hint b,' + root + '.ar-hud b,' + root + '.ar-rail h4.on{color:' + t.acc + ';}');
      out.push(root + '.fms-btn{background:' + t.panel2 + ';color:' + t.txt + ';border-color:' + t.line + ';}');
    });
    /* our own little sheet buttons, in every theme */
    out.push('.fms-btn{background:#1b1f27;border:1px solid #2a323d;color:#e6ebf2;border-radius:6px;'
           + 'padding:1px 7px;font:inherit;font-size:.68rem;cursor:pointer;}');
    out.push('.fms-btn:hover{border-color:#00e5ff;color:#00e5ff;}');
    out.push('.fms-help-row.off{display:none;}');
    return out.join('\n');
  }
  function themeStyle(){
    var el = document.getElementById('fms-theme-css');
    if(!el){
      el = document.createElement('style');
      el.id = 'fms-theme-css';
      el.textContent = themeCss();
      document.head.appendChild(el);
    }
    return el;
  }
  function themeApply(name, quiet){
    if(!THEMES.hasOwnProperty(name)) name = 'dark';
    themeStyle();
    var v = document.getElementById('view-architecture');
    if(v){
      ORDER.forEach(function(n){ v.classList.remove('ar-theme-' + n); });
      if(name !== 'dark') v.classList.add('ar-theme-' + name);
    }
    FMS.theme = name;
    lsSet('theme', name);
    /* arSkyCycle owns the sky: only the 'studio' (grey box) background is ours
       to repaint — daylight, overcast and dusk are the operator's choice. */
    var t = THEMES[name];
    try{
      var sky = (typeof AR_SKIES !== 'undefined') ? AR_SKIES[AR.skyIx || 0] : null;
      if(sky && sky.n === 'studio' && AR.scene){
        var col = new THREE.Color(t ? t.sky : sky.c);
        AR.scene.background = col;
        if(AR.scene.fog) AR.scene.fog.color = col.clone();
      }
    }catch(e){}
    if(window.arToolsRender) arToolsRender();
    if(!quiet) arToast('Theme: <b>' + name + '</b>.');
    return name;
  }
  window.FMS_theme = function(n){ themeApply(n); };
  AR_EXT.tools.p_theme = {
    tog: 1, assist: 1,
    tip: 'Theme — the dark studio, a pale paper look, or blueprint; press to cycle, or say which',
    on: function(){ return FMS.theme !== 'dark'; },
    act: function(opt){
      var want = (opt && typeof opt === 'object' && opt.theme) ? String(opt.theme) : null;
      if(!want) want = ORDER[(ORDER.indexOf(FMS.theme) + 1) % ORDER.length];
      return themeApply(want);
    }
  };

  /* ══ p_perf — frames, and the knobs that buy them ══════════════════════ */
  function perfNumbers(){
    var r = AR.renderer, info = r ? r.info : null;
    var tris = 0;
    AR.objs.forEach(function(o){
      if(!o.node || o.hidden) return;
      o.node.traverse(function(m){
        if(m.isMesh && m.geometry){
          var g = m.geometry;
          tris += g.index ? g.index.count / 3 : (g.attributes.position ? g.attributes.position.count / 3 : 0);
        }
      });
    });
    var heap = '';
    try{ if(performance.memory) heap = (performance.memory.usedJSHeapSize / 1048576).toFixed(0) + ' MB'; }catch(e){}
    var cvs = r ? r.domElement : null;
    return {fps: AR.fps || 0, objects: AR.objs.length, triangles: Math.round(tris),
            calls: info ? info.render.calls : 0,
            textures: info ? info.memory.textures : 0,
            geometries: info ? info.memory.geometries : 0,
            ratio: r ? r.getPixelRatio() : 0,
            canvas: cvs ? (cvs.width + ' x ' + cvs.height) : '',
            shadows: !!AR.shadows, tex: FMS.perf.tex,
            freeze: FMS.perf.freeze_on ? (FMS.perf.freeze_m + ' m') : 'off',
            heap: heap};
  }
  function perfSheet(){
    var n = perfNumbers();
    var btn = function(fn, label, on){
      return '<button class="fms-btn" style="' + (on ? 'border-color:#00e5ff;color:#00e5ff' : '') + '" '
           + 'onclick="' + fn + '">' + label + '</button>';
    };
    var rows = [['fps', '<b id="fms-fps">' + n.fps + '</b>'],
                ['objects', String(n.objects)],
                ['triangles (visible)', n.triangles.toLocaleString()],
                ['draw calls', '<span id="fms-calls">' + n.calls + '</span>'],
                ['textures', String(n.textures)],
                ['geometries', String(n.geometries)],
                ['canvas', n.canvas],
                ['pixel ratio', String(Math.round(n.ratio * 100) / 100)]];
    if(n.heap) rows.push(['JS heap', n.heap]);
    arSheet('Performance',
      '<div class="sh">Now</div>' + arRows(rows)
      + '<div class="sh">Knobs</div>'
      + arRows([
        ['pixel ratio', btn("FMS_perf('ratio',0.5)", '0.5', Math.abs(n.ratio - 0.5) < 0.01)
                      + ' ' + btn("FMS_perf('ratio',1)", '1', Math.abs(n.ratio - 1) < 0.01)
                      + ' ' + btn("FMS_perf('ratio',2)", '2', Math.abs(n.ratio - 2) < 0.01)],
        ['shadows', btn("FMS_perf('shadows',false)", 'off', !n.shadows)
                  + ' ' + btn("FMS_perf('shadows',true)", 'on', n.shadows)],
        ['texture quality', btn("FMS_perf('tex','low')", 'low', n.tex === 'low')
                          + ' ' + btn("FMS_perf('tex','high')", 'high', n.tex === 'high')],
        ['freeze far objects', btn("FMS_perf('freeze',false)", 'off', !FMS.perf.freeze_on)
                             + ' ' + btn("FMS_perf('freeze',60)", '60 m', FMS.perf.freeze_on)]])
      + '<p style="margin:10px 0 0">' + btn("FMS_perf('reduced',true)", 'Apply the reduced preset', FMS.perf.reduced)
      + ' ' + btn("FMS_perf('reduced',false)", 'Back to full', !FMS.perf.reduced) + '</p>'
      + '<p style="font-size:.72rem;color:#9aa4b2;margin:8px 0 0">Freezing hides records further than N metres '
      + 'from what the camera is looking at. Records you hid yourself stay hidden either way.</p>');
    FMS.sheet = 'p_perf';
    if(FMS.perfTimer) clearInterval(FMS.perfTimer);
    FMS.perfTimer = setInterval(function(){
      var sh = document.getElementById('ar-sheet');
      if(!sh || sh.style.display === 'none' || FMS.sheet !== 'p_perf'){ clearInterval(FMS.perfTimer); FMS.perfTimer = null; return; }
      var f = document.getElementById('fms-fps'), c = document.getElementById('fms-calls');
      if(f) f.textContent = String(AR.fps || 0);
      if(c && AR.renderer) c.textContent = String(AR.renderer.info.render.calls);
    }, 1000);
  }
  function perfSet(what, value){
    if(what === 'ratio'){
      var v = parseFloat(value);
      if(isFinite(v) && v > 0){ AR.renderer.setPixelRatio(v); FMS.perf.ratio = v; arSize(); }
    } else if(what === 'shadows'){
      var want = !!value;
      if(!!AR.shadows !== want) arTool('t_sun');      /* the studio owns the shadow switch */
      FMS.perf.shadows = want;
    } else if(what === 'tex'){
      FMS.perf.tex = (value === 'low') ? 'low' : 'high';
      if(window.arMatRefresh) arMatRefresh();
    } else if(what === 'freeze'){
      var m = parseFloat(value);
      FMS.perf.freeze_on = (value !== false && value !== 'off' && isFinite(m) && m > 0);
      if(FMS.perf.freeze_on) FMS.perf.freeze_m = m;
      if(!FMS.perf.freeze_on) AR.objs.forEach(function(o){ if(o.node) o.node.visible = !o.hidden; });
    } else if(what === 'reduced'){
      FMS.perf.reduced = !!value;
      if(value){ perfSet('ratio', 0.5); perfSet('shadows', false); perfSet('tex', 'low'); perfSet('freeze', 60); }
      else { perfSet('ratio', 1); perfSet('tex', 'high'); perfSet('freeze', false); }
    }
    lsSet('perf', JSON.stringify(FMS.perf));
    if(FMS.sheet === 'p_perf') perfSheet();
    if(window.arToolsRender) arToolsRender();
    return perfNumbers();
  }
  window.FMS_perf = perfSet;
  AR_EXT.tools.p_perf = {
    tog: 1, assist: 1,
    tip: 'Performance — the live frame numbers, and the pixel ratio, shadow, texture and far-object knobs that buy frames',
    on: function(){ return !!(FMS.perf.reduced || FMS.perf.freeze_on || FMS.perf.tex === 'low'
                              || (FMS.perf.ratio && FMS.perf.ratio < 1)); },
    act: function(opt){
      if(opt && typeof opt === 'object'){
        var did = false;
        if(opt.reduced !== undefined){ perfSet('reduced', opt.reduced); did = true; }
        if(opt.pixel_ratio !== undefined){ perfSet('ratio', opt.pixel_ratio); did = true; }
        if(opt.shadows !== undefined){ perfSet('shadows', opt.shadows); did = true; }
        if(opt.texture !== undefined){ perfSet('tex', opt.texture); did = true; }
        if(opt.freeze !== undefined){ perfSet('freeze', opt.freeze); did = true; }
        if(did) return perfNumbers();
      }
      perfSheet();
      return perfNumbers();
    }
  };

  /* ══ p_help — what every icon does ═════════════════════════════════════ */
  function helpRow(cls, a, b){
    return '<tr class="' + cls + '" data-fms-t="' + esc((a + ' ' + b).toLowerCase().replace(/<[^>]*>/g, '')) + '">'
         + '<td>' + a + '</td><td style="text-align:left;white-space:normal;font-family:inherit">' + b + '</td></tr>';
  }
  function helpSheet(){
    var iconRows = [], keyRows = [], nStub = 0, nIcon = 0;
    AR_TOOLS.forEach(function(sec){
      iconRows.push('<tr class="fms-help-row fms-help-sec" data-fms-t="' + esc(sec.sec.toLowerCase()) + '">'
        + '<td colspan="2" style="color:#9aa4b2;text-transform:uppercase;letter-spacing:.1em;'
        + 'font-size:.58rem;padding-top:9px">' + esc(sec.sec) + ' &middot; ' + esc(sec.bar || 'dock') + '</td></tr>');
      sec.items.forEach(function(t){
        nIcon++;
        if(t.stub) nStub++;
        iconRows.push(helpRow('fms-help-row',
          '<b>' + esc(t.lb) + '</b>' + (t.k ? ' <kbd>' + esc(t.k) + '</kbd>' : '')
            + '<br><span style="color:#6d7684;font-size:.62rem">' + esc(t.id) + '</span>',
          esc(t.tip || '') + (t.stub ? ' <b style="color:#ffcc00">[placeholder]</b>' : '')));
        if(t.k) keyRows.push(helpRow('fms-help-row', '<kbd>' + esc(t.k) + '</kbd>', esc(t.lb) + ' — ' + esc(t.tip || '')));
      });
    });
    /* the keys the studio's own keydown map answers to. The map is inside a
       closure this file cannot read, so they are written out here from the
       tooltips that document them; the extension keys below are live. */
    [['Ctrl+S', 'Save the drawing'], ['Ctrl+Z', 'Undo'], ['Ctrl+Shift+Z / Ctrl+Y', 'Redo'],
     ['Delete / Backspace', 'Delete the selection'], ['Esc', 'Cancel the draft, disarm the tool'],
     ['Enter', 'Finish the current draft'], ['Ctrl+A', 'Select all'], ['Ctrl+D', 'Duplicate'],
     ['Ctrl+C / Ctrl+V', 'Copy / paste'], ['Ctrl+G', 'Group'],
     ['Arrow keys', 'Nudge the selection'], ['Shift+R', 'Cell labels (in walk mode)'],
     ['+ / -', 'Walk speed (in walk mode)'], ['WASD, E/Q', 'Walk and rise/fall (in walk mode)']
    ].forEach(function(r){ keyRows.push(helpRow('fms-help-row', '<kbd>' + r[0] + '</kbd>', r[1])); });
    try{
      Object.keys(AR_EXT.keys || {}).sort().forEach(function(k){
        keyRows.push(helpRow('fms-help-row', '<kbd>' + esc(k) + '</kbd>', 'an extension family key'));
      });
    }catch(e){}

    var pressable = [];
    try{
      Object.keys(AR_EXT.tools || {}).sort().forEach(function(id){
        if(AR_EXT.tools[id] && AR_EXT.tools[id].assist) pressable.push(id);
      });
    }catch(e){}

    var head = '<div class="sh">Search</div>'
      + '<input id="fms-help-q" oninput="FMS_helpFilter(this.value)" placeholder="type to narrow&hellip;" '
      + 'style="width:100%;background:#1b1f27;border:1px solid #2a323d;color:inherit;border-radius:6px;'
      + 'padding:4px 7px;font:inherit;margin-bottom:4px">'
      + '<div class="sh" id="fms-help-count">' + nIcon + ' icons, ' + nStub + ' still placeholders</div>';
    var body = head
      + '<table class="ar-tbl">' + iconRows.join('') + '</table>'
      + '<div class="sh">Keyboard</div><table class="ar-tbl">' + keyRows.join('') + '</table>'
      + '<div class="sh">The assistant\u2019s tools</div>'
      + '<table class="ar-tbl" id="fms-help-tools">'
      + helpRow('fms-help-row', 'pressable icons', pressable.length ? esc(pressable.join(', ')) : 'none')
      + '<tr class="fms-help-row" data-fms-t="loading"><td>server tools</td><td>loading&hellip;</td></tr>'
      + '</table>';
    arSheet('Help', body);
    FMS.sheet = 'p_help';
    track(postJ('about', {}).then(function(d){
      var tbl = document.getElementById('fms-help-tools');
      if(!tbl) return d;
      var names = d.assistant_tools || [];
      var rows = names.map(function(n){ return helpRow('fms-help-row', esc(n), 'assistant tool'); }).join('');
      tbl.innerHTML = helpRow('fms-help-row', 'pressable icons', pressable.length ? esc(pressable.join(', ')) : 'none')
                    + rows;
      return d;
    }).catch(function(){ return null; }));
    return {icons: nIcon, stubs: nStub};
  }
  window.FMS_helpFilter = function(q){
    q = String(q || '').toLowerCase().trim();
    var n = 0;
    Array.prototype.forEach.call(document.querySelectorAll('.fms-help-row'), function(tr){
      var hit = !q || (tr.getAttribute('data-fms-t') || '').indexOf(q) >= 0;
      tr.classList.toggle('off', !hit);
      if(hit && !tr.classList.contains('fms-help-sec')) n++;
    });
    var c = document.getElementById('fms-help-count');
    if(c) c.textContent = q ? (n + ' rows match \u201c' + q + '\u201d') : c.textContent;
    return n;
  };
  AR_EXT.tools.p_help = {
    assist: 1,
    tip: 'Help — every icon in both bars with what it does, the keyboard map, and the tools the assistant can call',
    act: function(opt){
      var r = helpSheet();
      var q = (opt && typeof opt === 'object' && opt.q) ? String(opt.q) : '';
      if(q){ var el = document.getElementById('fms-help-q'); if(el) el.value = q; window.FMS_helpFilter(q); }
      return r;
    }
  };

  /* ══ p_about ═══════════════════════════════════════════════════════════ */
  AR_EXT.tools.p_about = {
    assist: 1,
    tip: 'About — what this engine is, what it stores, which libraries it borrows and under which licences',
    act: function(){
      return track(postJ('about', {}).then(function(d){
        if(d.error){ arToast(esc(d.error), 'bad'); return d; }
        var fams = Object.keys(d.families || {});
        var rev = (typeof THREE !== 'undefined' && THREE.REVISION) ? ('r' + THREE.REVISION) : 'unknown';
        /* the rows carry a class of their own: the sheet's headings are
           text-transform:uppercase, so innerText renders them shouted and a
           reader (or a test) that wants to know the licences are THERE counts
           rows rather than matching the casing of a heading. */
        var lic = (d.licences || []).map(function(l){
          return '<tr class="fms-lic-row"><td style="word-break:break-all">' + esc(l.file) + '</td>'
               + '<td style="text-align:left;white-space:normal;font-family:inherit">' + esc(l.first_line) + '</td></tr>';
        }).join('');
        var packs = (d.packs || []).map(function(p){
          return '<tr class="fms-pack-row"><td>' + esc(p.licence) + '</td><td>' + p.packs + ' packs, '
               + p.items + ' items' + (p.attrib ? ', ' + p.attrib + ' need attribution' : '') + '</td></tr>';
        }).join('');
        arSheet('About the Architecture Studio',
          arRows([['built', esc(d.built || '?') + ' (inspection.html)'],
                  ['three.js', esc(rev) + ' — vendored, MIT'],
                  ['server families', String(fams.length) + (fams.length ? ' — ' + esc(fams.join(', ')) : '')],
                  ['tab families (js)', String((d.js_families || []).length)],
                  ['assistant tools', String(d.tools || 0)],
                  ['object kinds', String(d.kinds || 0)],
                  ['drawings live in', 'data/architecture/projects/']])
          + '<div class="sh">Vendored libraries</div><table class="ar-tbl">'
          + (lic || '<tr><td>none found</td><td></td></tr>') + '</table>'
          + '<div class="sh">Asset packs by licence</div><table class="ar-tbl">'
          + (packs || '<tr><td>no catalogue</td><td></td></tr>') + '</table>'
          + '<p style="font-size:.72rem;color:#9aa4b2;margin:8px 0 0">A drawing stores PARAMETERS, never '
          + 'geometry: the same numbers are rebuilt here, in Blender and by the assistant. What it does '
          + 'not do yet is whatever is still marked [placeholder] in Help.</p>');
        FMS.sheet = 'p_about';
        d.three = rev;
        return d;
      }));
    }
  };

  /* ══ hooks ═════════════════════════════════════════════════════════════ */
  AR_EXT.matHooks.push(function(m){
    if(FMS.perf.tex !== 'low') return;
    ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap'].forEach(function(k){
      var t = m[k];
      if(!t) return;
      t.anisotropy = 1;
      try{ t.minFilter = THREE.LinearFilter; }catch(e){}
      t.needsUpdate = true;
    });
  });
  AR_EXT.ticks.push(function(){
    if(!FMS.perf.freeze_on || !AR.controls) return;
    var now = (window.performance && performance.now) ? performance.now() : Date.now();
    if(FMS._frzT && now - FMS._frzT < 300) return;
    FMS._frzT = now;
    var t = AR.controls.target, N = FMS.perf.freeze_m;
    AR.objs.forEach(function(o){
      if(!o.node) return;
      if(o.hidden){ o.node.visible = false; return; }   /* hidden stays hidden */
      var dx = o.x - t.x, dz = o.z - t.z;
      o.node.visible = (dx * dx + dz * dz) <= N * N;
    });
  });

  /* ══ ready ═════════════════════════════════════════════════════════════ */
  AR_EXT.ready.push(function(){
    themeStyle();
    applyDefaults();
    themeApply(lsGet('theme', 'dark'), true);

    try{
      var a = JSON.parse(lsGet('autosave', '{}') || '{}');
      if(a && a.every_s) FMS.every_s = parseFloat(a.every_s) || FMS.every_s;
      if(a && a.on) autoSet(true, FMS.every_s);
    }catch(e){}
    try{
      var p = JSON.parse(lsGet('perf', '{}') || '{}');
      if(p && p.tex === 'low') FMS.perf.tex = 'low';
      if(p && p.freeze_on){ FMS.perf.freeze_on = true; FMS.perf.freeze_m = parseFloat(p.freeze_m) || 60; }
    }catch(e){}

    /* every successful save leaves a copy on the version shelf. arSave is a
       function declaration (a writable global) and it resolves its fetch
       itself, so the copy is taken a moment later — long enough for the id a
       first save is given to have landed in AR.doc.id. */
    var baseSave = arSave;
    arSave = function(asNew){
      var r = baseSave(asNew);
      setTimeout(function(){ if(docPid()) snapshot('save'); }, 1500);
      return r;
    };

    /* the sheet's close button is the studio's; drop our live timer with it */
    var baseClose = arSheetClose;
    arSheetClose = function(){
      FMS.sheet = '';
      if(FMS.perfTimer){ clearInterval(FMS.perfTimer); FMS.perfTimer = null; }
      return baseClose();
    };
  });
})();
