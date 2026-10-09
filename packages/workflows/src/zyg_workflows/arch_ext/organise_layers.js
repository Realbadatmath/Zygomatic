// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* organise_layers — Organise ▸ Outliner tree, Layers, Tags, Selection sets
   (2026-09-07, the ICON seam; nothing in inspection.html was edited).

   Wires four AR_TOOLS placeholders for real:
     o_outliner  SWITCH  the outliner as a TREE (storey ▸ group ▸ objects),
                         collapsible, instead of the flat list arOutliner() draws.
     o_layers    ACTION  the layer manager sheet: visibility and lock per layer.
     o_tags      ACTION  tags on the selection, and select-by-tag.
     o_sets      ACTION  named selection sets, saved with the drawing.

   WHERE THE STATE LIVES
     AR.doc.ext.organise_layers = {layers: [{name, hidden, locked, color}],
                                   sets: {name: [ids]}}      per DRAWING (saved,
                                   round-trips through the assistant's Drawing.ext)
     rec.meta.layer  = layer name  (unset ⇒ 'Default')        per RECORD
     rec.meta.tags   = [strings]   (unique, lower-case, trimmed)
     localStorage 'ar.organise_layers.tree' — the tree switch's latch
     localStorage 'ar.organise_layers.open' — which tree nodes are collapsed
   No geometry and no parameters are touched: this family only organises what
   is already drawn, so it registers no kinds and no Blender builders.

   PUBLIC HELPER (documented for the other families — quantities, drawings…):
     window.organise_layers = {
       layerOf(rec)      -> the record's layer name, 'Default' when unset
       tagsOf(rec)       -> a COPY of the record's tag array (never the live one)
       visibleLayers()   -> [names] of the layers that are not hidden
     }
   Read it, do not write through it; every edit here goes behind one arPush(). */
(function () {
  'use strict';
  var FAM = 'organise_layers';
  var DEFAULT_LAYER = 'Default';
  var STOREY_M = 2.7;                 /* AR.defaults.wall_h at load time */
  var NODEKEYS = [];                  /* tree node keys, addressed by index from the DOM */

  /* ── state ────────────────────────────────────────────────────────────── */
  function ext() {
    if (!AR.doc) AR.doc = {id: '', name: 'Untitled drawing', ext: {}};
    if (!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    var e = AR.doc.ext[FAM];
    if (!e || typeof e !== 'object' || Array.isArray(e)) e = AR.doc.ext[FAM] = {};
    if (!Array.isArray(e.layers) || !e.layers.length)
      e.layers = [{name: DEFAULT_LAYER, hidden: false, locked: false, color: '#8fa3b8'}];
    if (!e.sets || typeof e.sets !== 'object' || Array.isArray(e.sets)) e.sets = {};
    return e;
  }
  function layerOf(rec) {
    var n = rec && rec.meta && rec.meta.layer;
    return (n === undefined || n === null || n === '') ? DEFAULT_LAYER : String(n);
  }
  function tagsOf(rec) {
    var t = rec && rec.meta && rec.meta.tags;
    return Array.isArray(t) ? t.slice() : [];
  }
  function findLayer(e, name) {
    for (var i = 0; i < e.layers.length; i++) if (e.layers[i].name === name) return e.layers[i];
    return null;
  }
  function membersOf(name) {
    return AR.objs.filter(function (o) { return layerOf(o) === name; });
  }
  function meta(rec) { if (!rec.meta || typeof rec.meta !== 'object') rec.meta = {}; return rec.meta; }
  function normTags(v) {
    var raw = Array.isArray(v) ? v : String(v === undefined || v === null ? '' : v).split(',');
    var out = [];
    raw.forEach(function (t) {
      t = String(t === undefined || t === null ? '' : t).trim().toLowerCase().slice(0, 40);
      if (t && out.indexOf(t) < 0) out.push(t);
    });
    return out;
  }
  function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

  /* ── the tree outliner ────────────────────────────────────────────────── */
  function treeOn() { return localStorage.getItem('ar.' + FAM + '.tree') === '1'; }
  function openState() {
    try { var o = JSON.parse(localStorage.getItem('ar.' + FAM + '.open') || '{}'); return (o && typeof o === 'object') ? o : {}; }
    catch (err) { return {}; }
  }
  function saveOpen(o) { try { localStorage.setItem('ar.' + FAM + '.open', JSON.stringify(o)); } catch (err) { /* private mode */ } }
  window.organise_layers_toggleNode = function (i) {
    var k = NODEKEYS[i]; if (k === undefined) return;
    var o = openState();
    o[k] = (o[k] === false);            /* undefined/true ⇒ collapse, false ⇒ open */
    saveOpen(o); arOutliner();
  };
  function node(key, label, count, depth, open, cls) {
    NODEKEYS.push(key);
    return '<div class="ar-orow ol-node ' + cls + '" data-node="' + esc(key) + '"'
      + ' style="padding-left:' + (6 + depth * 12) + 'px"'
      + ' onclick="organise_layers_toggleNode(' + (NODEKEYS.length - 1) + ')">'
      + '<span class="lb"><b>' + (open ? '&#9662;' : '&#9656;') + ' ' + esc(label) + '</b></span>'
      + '<span class="ey">' + count + '</span></div>';
  }
  function recRow(o, depth) {
    var mark = o.lock ? ' &#128274;' : '';       /* a read: never create doc.ext here */
    return '<div class="ar-orow ol-rec' + (AR.sel.indexOf(o.id) >= 0 ? ' on' : '') + '"'
      + ' data-id="' + esc(o.id) + '" data-layer="' + esc(layerOf(o)) + '"'
      + ' style="padding-left:' + (6 + depth * 12) + 'px"'
      + ' onclick="arSelect([\'' + o.id + '\'],event.shiftKey)">'
      + '<span class="lb">' + esc(o.name) + mark + '</span>'
      + '<span class="ey" onclick="event.stopPropagation();arToggleHide(\'' + o.id + '\')" title="Show / hide">'
      + (o.hidden ? '&#128584;' : '&#128065;') + '</span></div>';
  }
  function storeyLabel(k) { return k === 0 ? 'Ground storey' : (k > 0 ? 'Storey ' + k : 'Basement ' + (-k)); }
  function renderTree() {
    var host = document.getElementById('ar-outl'); if (!host) return;
    if (!AR.objs.length) { host.innerHTML = '<div class="ar-note">The drawing is empty.</div>'; return; }
    NODEKEYS = [];
    var open = openState(), byStorey = {}, h = '';
    AR.objs.forEach(function (o) {
      var st = Math.round((o.y || 0) / STOREY_M), g = o.grp || '(ungrouped)';
      if (!byStorey[st]) byStorey[st] = {};
      if (!byStorey[st][g]) byStorey[st][g] = [];
      byStorey[st][g].push(o);
    });
    Object.keys(byStorey).map(Number).sort(function (a, b) { return b - a; }).forEach(function (st) {
      var sk = 's|' + st, sOpen = open[sk] !== false, groups = byStorey[st], n = 0;
      Object.keys(groups).forEach(function (g) { n += groups[g].length; });
      h += node(sk, storeyLabel(st), n, 0, sOpen, 'ol-storey');
      if (!sOpen) return;
      Object.keys(groups).sort().forEach(function (g) {
        var gk = sk + '|g|' + g, gOpen = open[gk] !== false;
        h += node(gk, g, groups[g].length, 1, gOpen, 'ol-group');
        if (!gOpen) return;
        groups[g].slice().reverse().forEach(function (o) { h += recRow(o, 2); });
      });
    });
    host.innerHTML = h;
  }

  /* ── layers ───────────────────────────────────────────────────────────── */
  /* READ-ONLY peek: a drawing that never used a layer must not grow a doc.ext
     entry just because it was opened. */
  function peek() {
    var e = AR.doc && AR.doc.ext && AR.doc.ext[FAM];
    return (e && typeof e === 'object' && Array.isArray(e.layers)) ? e : null;
  }
  function applyLayerState(push) {
    var e = peek(), touched = 0, pushed = false;
    if (!e) return 0;
    e.layers.forEach(function (L) {
      membersOf(L.name).forEach(function (r) {
        var wantH = !!L.hidden, wantL = !!L.locked;
        if (!!r.hidden === wantH && !!r.lock === wantL) return;
        if (push && !pushed) { arPush(); pushed = true; }
        r.hidden = wantH; r.lock = wantL; arApplyTransform(r); touched++;
      });
    });
    if (touched) { arSelSync(); arPanel(); }
    return touched;
  }
  function ensureLayer(e, name) {
    var L = findLayer(e, name);
    if (!L) { L = {name: name, hidden: false, locked: false, color: '#8fa3b8'}; e.layers.push(L); }
    return L;
  }
  function doLayer(action, name) {
    var e = ext(), L, recs, i;
    if (action === 'new') {
      name = String(name || '').trim().slice(0, 40);
      if (!name) return 'refused: a new layer needs a name.';
      if (findLayer(e, name)) return 'Layer “' + esc(name) + '” already exists.';
      arPush(); ensureLayer(e, name); arDirty(true);
      return 'Layer “' + esc(name) + '” created.';
    }
    if (action === 'assign') {
      recs = arSelRecs();
      if (!recs.length) return 'refused: nothing is selected to assign.';
      name = String(name || DEFAULT_LAYER).trim().slice(0, 40) || DEFAULT_LAYER;
      arPush(); L = ensureLayer(e, name);
      recs.forEach(function (r) { meta(r).layer = name; r.hidden = !!L.hidden; r.lock = !!L.locked; arApplyTransform(r); });
      arDirty(true); arSelSync(); arPanel();
      return plural(recs.length, 'object') + ' moved to layer “' + esc(name) + '”.';
    }
    if (action === 'hide' || action === 'show' || action === 'lock' || action === 'unlock') {
      L = findLayer(e, String(name || ''));
      if (!L) return 'refused: no layer named “' + esc(String(name || '')) + '”.';
      arPush();
      if (action === 'hide' || action === 'show') L.hidden = (action === 'hide');
      else L.locked = (action === 'lock');
      var n = membersOf(L.name).length;
      applyLayerState(false); arDirty(true); arSelSync(); arPanel();
      return 'Layer “' + esc(L.name) + '” ' + action + 'ed (' + plural(n, 'object') + ').';
    }
    if (action === 'rename') {
      L = findLayer(e, String(name || ''));
      if (!L) return 'refused: no layer named “' + esc(String(name || '')) + '”.';
      var nn = String(prompt('Rename layer “' + L.name + '” to', L.name) || '').trim().slice(0, 40);
      if (!nn || nn === L.name) return 'Rename cancelled.';
      if (findLayer(e, nn)) return 'refused: “' + esc(nn) + '” already exists.';
      arPush();
      membersOf(L.name).forEach(function (r) { meta(r).layer = nn; });
      L.name = nn; arDirty(true); arPanel();
      return 'Layer renamed to “' + esc(nn) + '”.';
    }
    if (action === 'delete') {
      L = findLayer(e, String(name || ''));
      if (!L) return 'refused: no layer named “' + esc(String(name || '')) + '”.';
      if (L.name === DEFAULT_LAYER) return 'refused: the Default layer cannot be deleted.';
      arPush();
      recs = membersOf(L.name);
      recs.forEach(function (r) { meta(r).layer = DEFAULT_LAYER; r.hidden = false; r.lock = false; arApplyTransform(r); });
      for (i = 0; i < e.layers.length; i++) if (e.layers[i] === L) { e.layers.splice(i, 1); break; }
      arDirty(true); arSelSync(); arPanel();
      return 'Layer deleted; ' + plural(recs.length, 'object') + ' returned to Default.';
    }
    return 'refused: unknown layer action “' + esc(String(action)) + '”.';
  }
  window.organise_layers_layerBtn = function (i, action) {
    var e = ext(), L = e.layers[i]; if (!L) return;
    arToast(doLayer(action, L.name)); layerSheet();
  };
  window.organise_layers_newLayer = function () {
    var n = prompt('New layer name', 'Layer ' + (ext().layers.length + 1));
    if (n === null) return;
    arToast(doLayer('new', n)); layerSheet();
  };
  function btn(js, label) {
    return '<button style="font:inherit;padding:1px 6px;margin:0 2px 2px 0;border-radius:4px;'
      + 'border:1px solid var(--line);background:transparent;color:inherit;cursor:pointer" onclick="' + js + '">' + label + '</button>';
  }
  function layerSheet() {
    var e = ext(), counts = {};
    AR.objs.forEach(function (o) { var L = layerOf(o); counts[L] = (counts[L] || 0) + 1; });
    var h = '<table class="ar-tbl ol-layers">';
    e.layers.forEach(function (L, i) {
      h += '<tr class="ol-layer" data-layer="' + esc(L.name) + '"><td>' + esc(L.name)
        + (L.hidden ? ' <span title="hidden">&#128584;</span>' : '')
        + (L.locked ? ' <span title="locked">&#128274;</span>' : '') + '</td>'
        + '<td>' + (counts[L.name] || 0) + '</td><td style="text-align:right">'
        + btn('organise_layers_layerBtn(' + i + ',\'assign\')', 'Assign selection')
        + btn('organise_layers_layerBtn(' + i + ',\'' + (L.hidden ? 'show' : 'hide') + '\')', L.hidden ? 'Show' : 'Hide')
        + btn('organise_layers_layerBtn(' + i + ',\'' + (L.locked ? 'unlock' : 'lock') + '\')', L.locked ? 'Unlock' : 'Lock')
        + btn('organise_layers_layerBtn(' + i + ',\'rename\')', 'Rename')
        + (L.name === DEFAULT_LAYER ? '' : btn('organise_layers_layerBtn(' + i + ',\'delete\')', 'Delete'))
        + '</td></tr>';
    });
    h += '</table><div style="margin-top:8px">' + btn('organise_layers_newLayer()', '+ New layer') + '</div>';
    arSheet('Layers', h);
  }

  /* ── tags ─────────────────────────────────────────────────────────────── */
  function tagCounts() {
    var c = {};
    AR.objs.forEach(function (o) { tagsOf(o).forEach(function (t) { c[t] = (c[t] || 0) + 1; }); });
    return c;
  }
  function idsWithTag(tags) {
    return AR.objs.filter(function (o) {
      var mine = tagsOf(o);
      return tags.some(function (t) { return mine.indexOf(t) >= 0; });
    }).map(function (o) { return o.id; });
  }
  window.organise_layers_tagSelect = function (tag) {
    var ids = idsWithTag([tag]);
    arSelect(ids);
    arToast(plural(ids.length, 'object') + ' tagged “' + esc(tag) + '” selected.');
  };
  function tagSheet() {
    var c = tagCounts(), keys = Object.keys(c).sort();
    if (!keys.length) { arSheet('Tags', '<div class="ar-note">Nothing is tagged yet. Select objects and press Tags again.</div>'); return; }
    var h = '<table class="ar-tbl ol-tags">';
    keys.forEach(function (t) {
      h += '<tr class="ol-tag" data-tag="' + esc(t) + '"><td>' + esc(t) + '</td><td>' + c[t] + '</td>'
        + '<td style="text-align:right">' + btn('organise_layers_tagSelect(\'' + esc(t).replace(/'/g, '') + '\')', 'Select all with tag') + '</td></tr>';
    });
    arSheet('Tags', h + '</table>');
  }
  function doTags(tags, mode) {
    var recs, n = 0;
    if (mode === 'select') {
      if (!tags.length) { tagSheet(); return 'Tag list opened.'; }
      var ids = idsWithTag(tags);
      arSelect(ids);
      return plural(ids.length, 'object') + ' tagged “' + esc(tags.join(', ')) + '” selected.';
    }
    recs = arSelRecs();
    if (!recs.length) return 'refused: nothing is selected to tag.';
    if (!tags.length) return 'refused: no tags given.';
    arPush();
    recs.forEach(function (r) {
      var have = tagsOf(r), before = have.length;
      tags.forEach(function (t) {
        var at = have.indexOf(t);
        if (mode === 'remove') { if (at >= 0) have.splice(at, 1); }
        else if (at < 0) have.push(t);
      });
      have.sort();
      meta(r).tags = have;
      if (have.length !== before) n++;
    });
    arDirty(true); arPanel();
    return (mode === 'remove' ? 'Removed ' : 'Added ') + esc(tags.join(', ')) + ' on ' + plural(recs.length, 'object')
      + ' (' + n + ' changed).';
  }

  /* ── selection sets ───────────────────────────────────────────────────── */
  window.organise_layers_setBtn = function (name, action) {
    arToast(doSet(action, name));
    if (action === 'delete') setSheet(); else arSheetClose();
  };
  function setSheet() {
    var e = ext(), keys = Object.keys(e.sets).sort();
    if (!keys.length) { arSheet('Selection sets', '<div class="ar-note">No sets saved yet. Select objects, press Selection sets and give the set a name.</div>'); return; }
    var h = '<table class="ar-tbl ol-sets">';
    keys.forEach(function (k) {
      var safe = k.replace(/[\\']/g, '');
      h += '<tr class="ol-set" data-set="' + esc(k) + '"><td>' + esc(k) + '</td><td>' + e.sets[k].length + '</td>'
        + '<td style="text-align:right">' + btn('organise_layers_setBtn(\'' + safe + '\',\'recall\')', 'Recall')
        + btn('organise_layers_setBtn(\'' + safe + '\',\'delete\')', 'Delete') + '</td></tr>';
    });
    arSheet('Selection sets', h + '</table>');
  }
  function doSet(action, name) {
    var e = ext();
    name = String(name || '').trim().slice(0, 40);
    if (action === 'list' || (!name && action !== 'save')) { setSheet(); return 'Selection sets listed.'; }
    if (action === 'save') {
      if (!name) return 'refused: a selection set needs a name.';
      if (!AR.sel.length) return 'refused: nothing is selected to save.';
      arPush(); e.sets[name] = AR.sel.slice(); arDirty(true);
      return 'Set “' + esc(name) + '” saved with ' + plural(e.sets[name].length, 'object') + '.';
    }
    if (action === 'recall') {
      var ids = e.sets[name];
      if (!ids) return 'refused: no selection set named “' + esc(name) + '”.';
      var live = ids.filter(function (id) { return !!arFind(id); }), gone = ids.length - live.length;
      arSelect(live);                                  /* read-only: no arPush */
      return 'Set “' + esc(name) + '”: ' + plural(live.length, 'object') + ' selected'
        + (gone ? ', ' + gone + ' no longer in the drawing.' : '.');
    }
    if (action === 'delete') {
      if (!(name in e.sets)) return 'refused: no selection set named “' + esc(name) + '”.';
      arPush(); delete e.sets[name]; arDirty(true);
      return 'Set “' + esc(name) + '” deleted.';
    }
    return 'refused: unknown selection-set action “' + esc(String(action)) + '”.';
  }

  /* ── the four icons ───────────────────────────────────────────────────── */
  AR_EXT.tools.o_outliner = {
    tog: 1, assist: 1,
    tip: 'Outliner as a tree — storeys, groups and their children, rather than one flat list',
    on: function () { return treeOn(); },
    act: function (opt) {
      var want = (opt && typeof opt === 'object' && opt.on !== undefined) ? !!opt.on : !treeOn();
      localStorage.setItem('ar.' + FAM + '.tree', want ? '1' : '0');
      arOutliner();
      arToast(want ? 'Outliner: tree — storey ▸ group ▸ objects. Click a heading to collapse it.'
        : 'Outliner: flat list.');
    }
  };
  AR_EXT.tools.o_layers = {
    assist: 1,
    tip: 'Layer manager — visibility and lock per layer, the way a drawing set is organised',
    act: function (opt) {
      if (opt && typeof opt === 'object' && opt.action) {
        arToast(doLayer(String(opt.action), opt.layer === undefined ? '' : String(opt.layer)));
        layerSheet(); return;
      }
      layerSheet();
    }
  };
  AR_EXT.tools.o_tags = {
    assist: 1,
    tip: 'Tag the selection — a free label you can filter, schedule and colour by',
    act: function (opt) {
      var mode = 'add', tags = [];
      if (opt && typeof opt === 'object') { mode = String(opt.mode || 'add'); tags = normTags(opt.tags); }
      else {
        if (!AR.sel.length) { tagSheet(); return; }
        var a = prompt('Tags for the selection, comma separated — prefix with - to remove');
        if (a === null) return;
        a = String(a).trim();
        if (a.charAt(0) === '-') { mode = 'remove'; a = a.slice(1); }
        tags = normTags(a);
      }
      arToast(doTags(tags, mode));
    }
  };
  AR_EXT.tools.o_sets = {
    assist: 1,
    tip: 'Saved selection sets — name a selection now and get it back later',
    act: function (opt) {
      if (opt && typeof opt === 'object' && (opt.action || opt.name)) {
        arToast(doSet(String(opt.action || 'save'), opt.name === undefined ? '' : String(opt.name)));
        return;
      }
      var n = prompt('Selection set name — blank lists the sets you have');
      if (n === null) return;
      n = String(n).trim();
      if (!n) { setSheet(); return; }
      arToast(doSet(ext().sets[n] ? 'recall' : 'save', n));
    }
  };

  /* ── wiring ───────────────────────────────────────────────────────────── */
  AR_EXT.ready.push(function () {
    STOREY_M = (AR.defaults && AR.defaults.wall_h) || 2.7;

    /* the tree replaces the flat outliner only while the switch is on */
    var baseOutliner = arOutliner;
    arOutliner = function () { if (!treeOn()) return baseOutliner(); renderTree(); };

    /* layer visibility/lock is a property of the DRAWING: re-assert it whenever
       a document arrives (open, assistant injection, undo of an injection) */
    var baseInject = arInjectDoc;
    arInjectDoc = function (objects, opt) { baseInject(objects, opt); try { applyLayerState(false); } catch (err) { /* empty doc */ } };

    applyLayerState(false);

    /* the cheat-sheet other families read (quantities, drawings, schedules) */
    window[FAM] = {
      layerOf: layerOf,
      tagsOf: tagsOf,
      visibleLayers: function () {
        return ext().layers.filter(function (L) { return !L.hidden; }).map(function (L) { return L.name; });
      }
    };
  });
})();
